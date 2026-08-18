"""Writing parsed projection rows into the database.

Reuses the existing identity crosswalk machinery rather than inventing a
second one: :class:`~hoops_gm.identity.IdentityResolver` and
:func:`hoops_gm.ingest.importers.import_resolutions` already do exactly what a
projection source needs — match a raw name/team/position against the
canonical player list, write the accepted matches to ``player_external_ids``,
and hand back everything that needs a human. This module supplies the
resolvable records and turns accepted matches into ``projections`` rows; it
does not re-implement matching.

Two properties matter more than the write itself:

* **content-addressed versioning** — a ``projection_imports`` row is keyed by
  source, season and the SHA-256 of the file's bytes, so re-running the same
  file converges onto the same import rather than minting a new "version" for
  identical content, while an updated file or a new season creates a new one.
* **idempotent row writes** — a ``projections`` row is upserted by
  ``(projection_import_id, player_id)``, so reprocessing one import (for
  example after the crosswalk gains a new player) converges rather than
  duplicates.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import ExternalSource, ScoringType
from hoops_gm.db.models.identity import NbaTeam, Player, PlayerExternalId
from hoops_gm.db.models.projections import (
    Projection,
    ProjectionImport,
    ProjectionSource,
    SourceGamesPlayedAssumption,
)
from hoops_gm.identity import IdentityResolver, ResolutionReport, ResolvableRecord
from hoops_gm.identity.names import normalize_name
from hoops_gm.ingest.importers import ImportCounts, import_resolutions
from hoops_gm.ingest.projections.models import ProjectionParseResult, ProjectionSourceRow
from hoops_gm.ingest.projections.parser import parse_projection_csv
from hoops_gm.ingest.projections.profiles import (
    CANONICAL_STAT_FIELDS,
    PROFILES_BY_SOURCE,
    ColumnProfile,
)

__all__ = [
    "ProjectionImportOutcome",
    "build_player_targets",
    "get_or_create_projection_import",
    "get_or_create_projection_source",
    "import_projection_csv",
    "import_projection_rows",
    "resolve_projection_identities",
]


def _content_checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def get_or_create_projection_source(
    session: Session,
    *,
    source: ExternalSource,
    display_name: str,
    assumed_scoring_type: ScoringType | None = None,
    notes: str | None = None,
) -> ProjectionSource:
    """Fetch the registered source, or register it on first use.

    One row per :class:`ExternalSource` (``uq_projection_sources_source``);
    calling this twice for the same source updates the display metadata
    rather than creating a duplicate.
    """
    row = session.scalar(select(ProjectionSource).where(ProjectionSource.source == source))
    if row is None:
        row = ProjectionSource(source=source, display_name=display_name)
        session.add(row)
    row.display_name = display_name
    if assumed_scoring_type is not None:
        row.assumed_scoring_type = assumed_scoring_type
    if notes is not None:
        row.notes = notes
    session.flush()
    return row


def get_or_create_projection_import(
    session: Session,
    *,
    source: ProjectionSource,
    season: str,
    content: bytes,
    original_filename: str | None = None,
    assumed_scoring_type: ScoringType | None = None,
    raw_payload_ref: str | None = None,
    imported_at: datetime | None = None,
) -> tuple[ProjectionImport, bool]:
    """Fetch the import matching this exact file's bytes, or create it.

    Returns ``(row, created)``. ``created`` is ``False`` when a
    byte-identical file was already imported for this source and season — the
    natural key is ``(source_id, season, content_sha256)``, not a counter, so
    an accidental re-run of the same download never mints a second "version"
    of nothing while the same bytes cannot leak an earlier season into a new
    import.
    """
    checksum = _content_checksum(content)
    existing = session.scalar(
        select(ProjectionImport).where(
            ProjectionImport.source_id == source.id,
            ProjectionImport.season == season,
            ProjectionImport.content_sha256 == checksum,
        )
    )
    if existing is not None:
        return existing, False

    row = ProjectionImport(
        source_id=source.id,
        season=season,
        imported_at=imported_at or datetime.now(UTC),
        content_sha256=checksum,
        original_filename=original_filename,
        assumed_scoring_type=assumed_scoring_type,
        raw_payload_ref=raw_payload_ref,
    )
    session.add(row)
    session.flush()
    return row, True


def build_player_targets(session: Session) -> list[ResolvableRecord]:
    """Existing canonical players as identity-resolution targets.

    Keyed by each player's **NBA** external id, not the player's own primary
    key. ``import_resolutions`` (``ingest/importers.py``) looks up an
    accepted match's target key against the ``player_external_ids`` rows
    sourced from :data:`ExternalSource.NBA` to find the ``player_id`` to
    write — exactly what ``backfill.build_crosswalk`` does for the Fantrax
    crosswalk, and reused here rather than re-implemented. A canonical player
    with no NBA link cannot be a resolution target through this path; that is
    correct, since NBA.com is the anchor every stat in this project keys to
    (identity/resolver.py) and a player absent from it is not yet the anchor
    anything else can be matched onto.
    """
    teams = {team.id: team.abbreviation for team in session.scalars(select(NbaTeam))}
    players_by_id = {player.id: player for player in session.scalars(select(Player))}
    nba_links = session.scalars(
        select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.NBA)
    )

    targets: list[ResolvableRecord] = []
    for link in nba_links:
        player = players_by_id.get(link.player_id)
        if player is None:
            continue
        targets.append(
            ResolvableRecord.build(
                key=link.external_id,
                name=player.full_name,
                team=teams.get(player.current_team_id) if player.current_team_id else None,
                position=player.primary_position,
            )
        )
    return targets


def resolve_projection_identities(
    session: Session, rows: Sequence[ProjectionSourceRow]
) -> ResolutionReport:
    """Resolve parsed CSV rows against the canonical player crosswalk.

    The resolvable record's ``key`` is the row's normalised name. Projection
    CSVs carry no identifier of any kind (plan.md), so the raw name string is
    the only stable handle a source gives us across repeated imports — the
    same reasoning ``PlayerExternalId.external_name`` documents for why the
    raw string *is* the evidence here. Duplicate names within one file are
    rejected by the parser before this ever runs, so this key is unique
    within ``rows``.
    """
    targets = build_player_targets(session)
    records = [
        ResolvableRecord.build(
            key=normalize_name(row.player_name).key,
            name=row.player_name,
            team=row.team,
            position=row.position,
        )
        for row in rows
    ]
    resolver = IdentityResolver(targets)
    return resolver.resolve(records)


def _apply_row(projection: Projection, row: ProjectionSourceRow) -> None:
    for field_name in CANONICAL_STAT_FIELDS:
        setattr(projection, field_name, getattr(row, field_name))
    projection.raw_row = dict(row.raw_row)


def _upsert_games_played_assumption(
    session: Session, projection: Projection, row: ProjectionSourceRow
) -> None:
    if row.assumed_games_played is None and row.assumed_games_played_raw is None:
        return
    existing = session.scalar(
        select(SourceGamesPlayedAssumption).where(
            SourceGamesPlayedAssumption.projection_id == projection.id
        )
    )
    if existing is None:
        existing = SourceGamesPlayedAssumption(projection_id=projection.id)
        session.add(existing)
    existing.assumed_games_played = row.assumed_games_played
    existing.assumed_games_played_raw = row.assumed_games_played_raw


def import_projection_rows(
    session: Session,
    *,
    projection_import: ProjectionImport,
    rows: Sequence[ProjectionSourceRow],
    source: ExternalSource,
) -> tuple[ImportCounts, ResolutionReport]:
    """Resolve identities and upsert ``projections`` rows for one import batch.

    Only **accepted** resolutions produce a ``projections`` row — a needs-
    review or unmatched row belongs in the report handed back to a human
    (``hoops_gm.identity.report``), not in the data with a guessed
    ``player_id`` attached to it.
    """
    report = resolve_projection_identities(session, rows)
    import_resolutions(session, report.all_resolutions(), source=source)

    player_by_key = {
        link.external_id: link.player_id
        for link in session.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == source)
        )
    }
    rows_by_key = {normalize_name(row.player_name).key: row for row in rows}

    existing_by_player = {
        proj.player_id: proj
        for proj in session.scalars(
            select(Projection).where(Projection.projection_import_id == projection_import.id)
        )
    }

    counts = ImportCounts()
    for resolution in report.accepted:
        key = resolution.source_record.key
        row = rows_by_key.get(key)
        player_id = player_by_key.get(key)
        if row is None or player_id is None:
            counts.skipped += 1
            continue

        projection = existing_by_player.get(player_id)
        if projection is None:
            projection = Projection(
                projection_import_id=projection_import.id,
                player_id=player_id,
                season=projection_import.season,
            )
            session.add(projection)
            counts.created += 1
        else:
            counts.updated += 1

        _apply_row(projection, row)
        session.flush()  # projection.id is required by the 1:1 GP assumption row
        _upsert_games_played_assumption(session, projection, row)

    session.flush()
    return counts, report


@dataclass
class ProjectionImportOutcome:
    """Everything one call to :func:`import_projection_csv` produced."""

    projection_source: ProjectionSource
    projection_import: ProjectionImport
    #: Whether this call created a new ``projection_imports`` row. ``False``
    #: means a byte-identical file was already on record; rows are still
    #: (re)processed in that case, so the result reflects the crosswalk as it
    #: stands now rather than as it stood on the first import.
    import_created: bool
    counts: ImportCounts
    identity_report: ResolutionReport
    #: The full parse result, including every warning — not just what was
    #: fatal. A caller that only checks ``counts``/``identity_report`` still
    #: has this available before deciding whether a percentage-only column or
    #: an unconverted season-total warning needs a human's attention.
    parse_result: ProjectionParseResult


def import_projection_csv(
    session: Session,
    *,
    source: ExternalSource,
    display_name: str,
    season: str,
    csv_text: str,
    original_filename: str | None = None,
    assumed_scoring_type: ScoringType | None = None,
    profile: ColumnProfile | None = None,
    raw_payload_ref: str | None = None,
) -> ProjectionImportOutcome:
    """Parse, version and write one projection CSV — the single entry point.

    Ties together the three pieces this package keeps separate on purpose:
    :func:`~hoops_gm.ingest.projections.parser.parse_projection_csv` (pure
    parsing and validation), the identity crosswalk
    (:func:`resolve_projection_identities`), and the versioned write
    (:func:`get_or_create_projection_import` /
    :func:`import_projection_rows`). A caller with a CSV file and nothing
    else needs only this function.
    """
    resolved_profile = profile or PROFILES_BY_SOURCE.get(source)
    if resolved_profile is None:
        raise ValueError(
            f"no built-in column profile for {source!r}; pass one explicitly via `profile=`"
        )

    parsed = parse_projection_csv(csv_text, resolved_profile, season=season)

    source_row = get_or_create_projection_source(
        session,
        source=source,
        display_name=display_name,
        assumed_scoring_type=assumed_scoring_type,
    )
    projection_import, created = get_or_create_projection_import(
        session,
        source=source_row,
        season=season,
        content=csv_text.encode("utf-8"),
        original_filename=original_filename,
        assumed_scoring_type=assumed_scoring_type,
        raw_payload_ref=raw_payload_ref,
    )

    counts, identity_report = import_projection_rows(
        session,
        projection_import=projection_import,
        rows=parsed.rows,
        source=source,
    )

    projection_import.row_count = parsed.total_rows
    projection_import.matched_count = len(identity_report.accepted)
    projection_import.needs_review_count = len(identity_report.needs_review)
    projection_import.unmatched_count = len(identity_report.unmatched)
    projection_import.rejected_count = parsed.rejected_count
    session.flush()

    return ProjectionImportOutcome(
        projection_source=source_row,
        projection_import=projection_import,
        import_created=created,
        counts=counts,
        identity_report=identity_report,
        parse_result=parsed,
    )
