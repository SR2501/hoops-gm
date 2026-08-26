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
* **exact-output reconciliation** — reprocessing an import removes every
  projection and games-played assumption it previously owned, retracts stale
  automated crosswalk links through ``import_resolutions``, and rebuilds only
  the currently accepted matches. An accepted match that becomes ambiguous or
  changes players cannot survive as stale output.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.db.lineage import lock_projection_source_scope
from hoops_gm.db.models.enums import ExternalSource, ScoringType
from hoops_gm.db.models.identity import NbaTeam, Player, PlayerExternalId
from hoops_gm.db.models.projections import (
    Projection,
    ProjectionImport,
    ProjectionProfileVersion,
    ProjectionSource,
    SourceGamesPlayedAssumption,
)
from hoops_gm.identity import (
    Candidate,
    IdentityResolver,
    MatchEvidence,
    Resolution,
    ResolutionReport,
    ResolvableRecord,
)
from hoops_gm.identity.names import normalize_name
from hoops_gm.ingest.importers import ImportCounts, import_resolutions
from hoops_gm.ingest.projections.models import ProjectionParseResult, ProjectionSourceRow
from hoops_gm.ingest.projections.parser import ProjectionProfileError, parse_projection_csv
from hoops_gm.ingest.projections.profiles import (
    CANONICAL_STAT_FIELDS,
    MANUAL_PROFILE,
    PROFILES_BY_SOURCE,
    PROJECTION_IMPORT_SOURCES,
    ColumnProfile,
    ValueShape,
)
from hoops_gm.ingest.projections.verification import (
    IMPORT_BLOCKING_CHECKS,
    VerificationReport,
    verify_projection_batch,
)

__all__ = [
    "ProjectionEncodingError",
    "ProjectionImportOutcome",
    "ProjectionVerificationError",
    "build_player_targets",
    "get_or_create_projection_source",
    "import_projection_csv",
    "resolve_projection_identities",
]

_IMPORT_LOCKS_GUARD = threading.Lock()
_IMPORT_LOCKS: dict[str, threading.Lock] = {}
_SESSION_LOCKS_KEY = "projection_import_locks"
_SESSION_LOCK_LISTENER_KEY = "projection_import_lock_listener"


class ProjectionEncodingError(ValueError):
    """Raw projection bytes are not valid UTF-8/UTF-8-with-BOM."""


class ProjectionVerificationError(ValueError):
    """A parsed batch is internally well-formed but is not what it claims to be.

    Distinct from :class:`ProjectionProfileError`, which means the file cannot be
    read under this profile at all. This one means it *was* read, every cell was
    valid, and the batch as a whole still describes something other than the
    per-game projections the profile declares — the season-totals paste being the
    case that motivated it.

    It exists because the checks that detect that were, on first delivery, written
    and tested and then wired to nothing. A verification module that no import path
    calls does not protect an import path, however green its own tests are.
    """

    def __init__(self, message: str, report: VerificationReport) -> None:
        super().__init__(message)
        self.report = report


def _content_checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _decode_csv(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProjectionEncodingError(
            "projection CSV must be UTF-8 (an optional UTF-8 BOM is supported); "
            f"decoding failed at byte {exc.start}"
        ) from exc


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
    if source not in PROJECTION_IMPORT_SOURCES:
        raise ProjectionProfileError(
            f"{source.value} is an identity-anchor namespace, not a projection CSV source"
        )
    row = session.scalar(select(ProjectionSource).where(ProjectionSource.source == source))
    if row is None:
        candidate = ProjectionSource(source=source, display_name=display_name)
        try:
            with session.begin_nested():
                session.add(candidate)
                session.flush()
            row = candidate
        except IntegrityError:
            row = session.scalar(select(ProjectionSource).where(ProjectionSource.source == source))
            if row is None:
                raise
    row.display_name = display_name
    if assumed_scoring_type is not None:
        row.assumed_scoring_type = assumed_scoring_type
    if notes is not None:
        row.notes = notes
    session.flush()
    return row


def _get_or_create_projection_import(
    session: Session,
    *,
    source: ProjectionSource,
    profile_version_row: ProjectionProfileVersion,
    season: str,
    content_sha256: str,
    profile_lineage: dict[str, object],
    original_filename: str | None = None,
    assumed_scoring_type: ScoringType | None = None,
    raw_payload_ref: str | None = None,
    imported_at: datetime | None = None,
) -> tuple[ProjectionImport, bool]:
    """Fetch the import matching this exact file's bytes, or create it.

    Returns ``(row, created)``. ``created`` is ``False`` when a
    byte-identical file was already imported for this source and season — the
    natural key includes source, season, bytes, profile id and profile version.
    Reusing bytes under a revised profile therefore preserves both
    interpretations. Reusing a profile id/version with a changed recipe fails
    loudly rather than rewriting the old import's meaning.
    """
    if profile_version_row.source_id != source.id:
        raise ProjectionProfileError("profile version belongs to a different projection source")
    _validate_lineage_against_profile_version(
        profile_version_row,
        profile_lineage=profile_lineage,
    )

    existing = session.scalar(
        select(ProjectionImport).where(
            ProjectionImport.source_id == source.id,
            ProjectionImport.season == season,
            ProjectionImport.content_sha256 == content_sha256,
            ProjectionImport.profile_version_id == profile_version_row.id,
        )
    )
    if existing is not None:
        _assert_profile_lineage(
            existing,
            profile_version_row=profile_version_row,
            profile_lineage=profile_lineage,
        )
        return existing, False

    candidate = ProjectionImport(
        source_id=source.id,
        profile_version_id=profile_version_row.id,
        season=season,
        imported_at=imported_at or datetime.now(UTC),
        content_sha256=content_sha256,
        profile_id=profile_version_row.profile_id,
        profile_version=profile_version_row.profile_version,
        profile_verified=profile_version_row.verified,
        profile_definition_sha256=profile_version_row.definition_sha256,
        profile_lineage=profile_lineage,
        original_filename=original_filename,
        assumed_scoring_type=assumed_scoring_type,
        raw_payload_ref=raw_payload_ref,
    )
    try:
        with session.begin_nested():
            session.add(candidate)
            session.flush()
        return candidate, True
    except IntegrityError:
        existing = session.scalar(
            select(ProjectionImport).where(
                ProjectionImport.source_id == source.id,
                ProjectionImport.season == season,
                ProjectionImport.content_sha256 == content_sha256,
                ProjectionImport.profile_version_id == profile_version_row.id,
            )
        )
        if existing is None:
            raise
        _assert_profile_lineage(
            existing,
            profile_version_row=profile_version_row,
            profile_lineage=profile_lineage,
        )
        return existing, False


def _hold_import_lock_until_transaction_end(
    session: Session,
    key: str,
) -> None:
    """Serialize importers sharing one database connection.

    This is the *in-process* half of the pair, and it is not redundant with
    :func:`_lock_projection_source_scope`. Under ``StaticPool`` — which
    :func:`hoops_gm.db.session.create_db_engine` selects for an in-memory
    SQLite URL, and which the test suite therefore runs on — two ``Session``
    objects share **one** DBAPI connection, so SQLite's write reservation is
    already held by both and cannot separate them. Nothing but this lock does.

    It is also the half that does nothing across processes, which is R58 and
    why the other one exists.
    """
    held = session.info.setdefault(_SESSION_LOCKS_KEY, {})
    if key in held:
        return

    with _IMPORT_LOCKS_GUARD:
        lock = _IMPORT_LOCKS.setdefault(key, threading.Lock())
    lock.acquire()
    held[key] = lock

    if session.info.get(_SESSION_LOCK_LISTENER_KEY):
        return

    def release_locks(
        completed_session: Session,
        transaction: Any,
    ) -> None:
        if transaction.parent is not None:
            return
        locks = completed_session.info.pop(_SESSION_LOCKS_KEY, {})
        for held_lock in locks.values():
            held_lock.release()

    session.info[_SESSION_LOCK_LISTENER_KEY] = True
    event.listen(session, "after_transaction_end", release_locks)


def _lock_projection_source_scope(session: Session, source: ExternalSource, season: str) -> None:
    """Serialize importers of one source **across processes**, on both dialects.

    Delegates to :func:`hoops_gm.db.lineage.lock_projection_source_scope`, which
    is where the mechanism and the R58 history are documented, and which is the
    only module in this codebase allowed to reach the lock primitive.

    **This is a writer taking a writer's lock**, which is why it is not the
    construction ``projections-api-early`` removed from the read endpoint. A
    reservation-holding *read* is a writer on SQLite and can make a hand-run
    import fail with ``database is locked``; an importer emits DML
    unconditionally, so this only moves the reservation earlier inside a
    transaction that was always going to take it. It is taken after parsing, so
    no parse time is spent holding it.
    """

    lock_projection_source_scope(session, source=source.value, season=season)


def _validate_lineage_against_profile_version(
    profile_version_row: ProjectionProfileVersion,
    *,
    profile_lineage: dict[str, object],
) -> None:
    expected = {
        "profile_id": profile_version_row.profile_id,
        "profile_version": profile_version_row.profile_version,
        "verified": profile_version_row.verified,
        "verified_seasons": profile_version_row.verified_seasons,
        "verification_evidence": profile_version_row.verification_evidence,
        "profile_definition_sha256": profile_version_row.definition_sha256,
        "profile_definition": profile_version_row.definition,
    }
    mismatches = [field for field, value in expected.items() if profile_lineage.get(field) != value]
    if mismatches:
        raise ProjectionProfileError(
            f"import lineage disagrees with its immutable profile version for fields {mismatches}"
        )


def _profile_definition(profile: ColumnProfile) -> dict[str, object]:
    return {
        "name_aliases": list(profile.name_aliases),
        "external_id_aliases": list(profile.external_id_aliases),
        "first_name_aliases": list(profile.first_name_aliases),
        "last_name_aliases": list(profile.last_name_aliases),
        "team_aliases": list(profile.team_aliases),
        "position_aliases": list(profile.position_aliases),
        "games_played_aliases": list(profile.games_played_aliases),
        "stat_columns": [
            {
                "field": column.field,
                "aliases": list(column.aliases),
                "shape": column.shape.value,
            }
            for column in profile.stat_columns
        ],
        "derived_stat_columns": [
            {
                "field": column.field,
                "terms": [
                    {"field": input_field, "coefficient": coefficient}
                    for input_field, coefficient in column.terms
                ],
            }
            for column in profile.derived_stat_columns
        ],
        "required_production_fields": list(profile.required_production_fields),
        "percentage_fallback_aliases": {
            field: list(aliases) for field, aliases in profile.percentage_fallback_aliases.items()
        },
        # Composite columns must be in the hashed definition, not merely in the
        # profile object. They decide which canonical field each half of a
        # ``pct (makes/attempts)`` cell becomes, so a definition that omitted
        # them would hash identically whether ``FG%`` decomposed into field
        # goals or into free throws. A hash that does not cover the contract it
        # claims to pin is worse than no hash, because it is trusted.
        "composite_shooting_columns": [
            {
                "made_field": column.made_field,
                "attempted_field": column.attempted_field,
                "aliases": list(column.aliases),
                "shape": column.shape.value,
            }
            for column in profile.composite_shooting_columns
        ],
        "expected_headers": list(profile.expected_headers),
        "ignored_source_headers": list(profile.ignored_source_headers),
    }


def _profile_definition_sha256(
    profile: ColumnProfile,
    definition: dict[str, object],
) -> str:
    version_contract = {
        "verified": profile.verified,
        "verified_seasons": list(profile.verified_seasons),
        "verification_evidence": profile.verification_evidence,
        "definition": definition,
    }
    encoded = json.dumps(version_contract, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _get_or_create_profile_version(
    session: Session,
    *,
    source: ProjectionSource,
    profile: ColumnProfile,
    definition: dict[str, object],
    definition_sha256: str,
) -> ProjectionProfileVersion:
    query = select(ProjectionProfileVersion).where(
        ProjectionProfileVersion.source_id == source.id,
        ProjectionProfileVersion.profile_id == profile.profile_id,
        ProjectionProfileVersion.profile_version == profile.version,
    )
    existing = session.scalar(query)
    if existing is not None:
        _assert_profile_version(
            existing,
            profile=profile,
            definition=definition,
            definition_sha256=definition_sha256,
        )
        return existing

    candidate = ProjectionProfileVersion(
        source_id=source.id,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        verified=profile.verified,
        verified_seasons=list(profile.verified_seasons),
        verification_evidence=profile.verification_evidence or "",
        definition_sha256=definition_sha256,
        definition=definition,
    )
    try:
        with session.begin_nested():
            session.add(candidate)
            session.flush()
        return candidate
    except IntegrityError:
        existing = session.scalar(query)
        if existing is None:
            raise
        _assert_profile_version(
            existing,
            profile=profile,
            definition=definition,
            definition_sha256=definition_sha256,
        )
        return existing


def _assert_profile_version(
    stored: ProjectionProfileVersion,
    *,
    profile: ColumnProfile,
    definition: dict[str, object],
    definition_sha256: str,
) -> None:
    if (
        stored.verified != profile.verified
        or stored.verified_seasons != list(profile.verified_seasons)
        or stored.verification_evidence != (profile.verification_evidence or "")
        or stored.definition_sha256 != definition_sha256
        or stored.definition != definition
    ):
        raise ProjectionProfileError(
            f"profile {profile.profile_id!r} version {profile.version!r} "
            "changed without a version bump"
        )


def _assert_profile_lineage(
    projection_import: ProjectionImport,
    *,
    profile_version_row: ProjectionProfileVersion,
    profile_lineage: dict[str, object],
) -> None:
    if (
        projection_import.profile_version_id != profile_version_row.id
        or projection_import.profile_id != profile_version_row.profile_id
        or projection_import.profile_version != profile_version_row.profile_version
        or projection_import.profile_verified != profile_version_row.verified
        or projection_import.profile_definition_sha256 != profile_version_row.definition_sha256
        or projection_import.profile_lineage != profile_lineage
    ):
        raise ProjectionProfileError(
            f"profile {projection_import.profile_id!r} version "
            f"{projection_import.profile_version!r} changed without a version bump"
        )


def _build_profile_lineage(
    profile: ColumnProfile,
    parsed: ProjectionParseResult,
    *,
    definition: dict[str, object],
    definition_sha256: str,
) -> dict[str, object]:
    columns_by_field = {column.field: column for column in profile.stat_columns}
    #: Fields that reach the row via decomposition of a composite cell rather
    #: than via a column of their own. Their lineage is materially different
    #: and is recorded as such: the source header they came from is shared
    #: with their sibling, and the value was extracted from inside it.
    composites_by_field = {
        field: composite
        for composite in profile.composite_shooting_columns
        for field in (composite.made_field, composite.attempted_field)
    }
    field_transforms: dict[str, object] = {}
    for canonical_field, source_header in parsed.resolved_headers.items():
        composite = composites_by_field.get(canonical_field)
        if composite is not None:
            component = "makes" if canonical_field == composite.made_field else "attempts"
            field_transforms[canonical_field] = {
                "source_header": source_header,
                "source_unit": composite.shape.value,
                "output_unit": ValueShape.PER_GAME.value,
                "transform": (
                    f"decompose_composite_shooting_cell[{component}]"
                    if composite.shape is ValueShape.PER_GAME
                    else f"decompose_composite_shooting_cell[{component}]"
                    "+divide_by_assumed_games_played"
                ),
                "extracted_from": (
                    "the parenthesised volume inside the percentage cell, not a column of its own"
                ),
                "reconciled_against": "the stated percentage in the same cell",
            }
        elif canonical_field in CANONICAL_STAT_FIELDS:
            column = columns_by_field[canonical_field]
            field_transforms[canonical_field] = {
                "source_header": source_header,
                "source_unit": column.shape.value,
                "output_unit": ValueShape.PER_GAME.value,
                "transform": (
                    "identity"
                    if column.shape is ValueShape.PER_GAME
                    else "divide_by_assumed_games_played"
                ),
            }
        elif canonical_field == "assumed_games_played":
            field_transforms[canonical_field] = {
                "source_header": source_header,
                "source_unit": "games",
                "output_unit": "games",
                "transform": "parse_finite_number",
            }
        else:
            field_transforms[canonical_field] = {
                "source_header": source_header,
                "source_unit": "text",
                "output_unit": "text",
                "transform": "trim",
            }

    for derived in profile.derived_stat_columns:
        terms: list[dict[str, object]] = []
        for input_field, coefficient in derived.terms:
            source_column = columns_by_field[input_field]
            terms.append(
                {
                    "input_field": input_field,
                    "coefficient": coefficient,
                    "source_header": parsed.resolved_headers[input_field],
                    "source_unit": source_column.shape.value,
                    "normalization": (
                        "identity"
                        if source_column.shape is ValueShape.PER_GAME
                        else "divide_by_assumed_games_played"
                    ),
                }
            )
        field_transforms[derived.field] = {
            "terms": terms,
            "output_unit": ValueShape.PER_GAME.value,
            "transform": "linear_combination_of_normalized_fields",
        }

    percentage_pairs = {
        "field_goals_made_per_game": "field_goals_attempted_per_game",
        "field_goals_attempted_per_game": "field_goals_made_per_game",
        "free_throws_made_per_game": "free_throws_attempted_per_game",
        "free_throws_attempted_per_game": "free_throws_made_per_game",
    }
    for field_name, paired_field in percentage_pairs.items():
        transform = field_transforms.get(field_name)
        if isinstance(transform, dict):
            transform["requires_paired_field"] = paired_field

    for made_field, source_header in parsed.resolved_percentage_headers.items():
        attempted_field = percentage_pairs[made_field]
        field_transforms[f"{made_field}__percentage_observation"] = {
            "source_header": source_header,
            "source_unit": "percentage",
            "output_unit": None,
            "transform": "not_imported",
            "reason": "percentage categories require explicit makes and attempts",
            "required_volume_fields": [made_field, attempted_field],
        }

    return {
        "profile_id": profile.profile_id,
        "profile_version": profile.version,
        "verified": profile.verified,
        "verified_seasons": list(profile.verified_seasons),
        "verification_evidence": profile.verification_evidence,
        "profile_definition_sha256": definition_sha256,
        "resolved_headers": dict(parsed.resolved_headers),
        "resolved_percentage_headers": dict(parsed.resolved_percentage_headers),
        "ignored_terminal_headers": list(parsed.ignored_terminal_headers),
        "ignored_source_headers": list(parsed.ignored_source_headers),
        "field_transforms": field_transforms,
        "profile_definition": definition,
    }


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
    session: Session,
    rows: Sequence[ProjectionSourceRow],
    *,
    source: ExternalSource,
) -> ResolutionReport:
    """Resolve parsed CSV rows against the canonical player crosswalk.

    The resolvable record's ``key`` is the vendor's stable player id when the
    verified profile exposes one, otherwise the row's normalised name. The
    player name remains the matching evidence either way; a vendor id is a
    source crosswalk key, never a canonical identity anchor. Duplicate names
    and duplicate vendor ids are rejected by the parser before this runs.
    """
    targets = build_player_targets(session)
    targets_by_key = {target.key: target for target in targets}
    nba_key_by_player_id = {
        link.player_id: link.external_id
        for link in session.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.NBA)
        )
    }
    manual_by_external_id = {
        link.external_id: link
        for link in session.scalars(
            select(PlayerExternalId).where(
                PlayerExternalId.source == source,
                PlayerExternalId.is_manual_override.is_(True),
                PlayerExternalId.current_for_source.is_not(None),
            )
        )
    }
    records = [
        ResolvableRecord.build(
            key=_projection_source_key(row),
            name=row.player_name,
            team=row.team,
            position=row.position,
        )
        for row in rows
    ]
    resolver = IdentityResolver(targets)
    inferred = resolver.resolve(records)
    report = ResolutionReport(accepted=list(inferred.accepted))
    for bucket_name, resolutions in (
        ("needs_review", inferred.needs_review),
        ("unmatched", inferred.unmatched),
    ):
        destination = getattr(report, bucket_name)
        for resolution in resolutions:
            manual = manual_by_external_id.get(resolution.source_record.key)
            target_key = nba_key_by_player_id.get(manual.player_id) if manual is not None else None
            target = targets_by_key.get(target_key) if target_key is not None else None
            if target is None:
                destination.append(resolution)
                continue
            report.accepted.append(
                Resolution(
                    source_record=resolution.source_record,
                    best=Candidate(
                        target=target,
                        evidence=MatchEvidence(),
                        confidence=1.0,
                    ),
                    runner_up=resolution.runner_up,
                    accepted=True,
                    reason="manual crosswalk override",
                )
            )
    return _reject_post_override_target_collisions(report)


def _projection_source_key(row: ProjectionSourceRow) -> str:
    return row.source_player_id or normalize_name(row.player_name).key


def _reject_post_override_target_collisions(
    report: ResolutionReport,
) -> ResolutionReport:
    by_target: dict[str, list[Resolution]] = {}
    for resolution in report.accepted:
        if resolution.best is not None:
            by_target.setdefault(resolution.best.target.key, []).append(resolution)

    collisions = {
        target_key: resolutions
        for target_key, resolutions in by_target.items()
        if len(resolutions) > 1
    }
    if not collisions:
        return report

    adjusted = ResolutionReport(
        needs_review=list(report.needs_review),
        unmatched=list(report.unmatched),
    )
    for resolution in report.accepted:
        if resolution.best is None:
            adjusted.needs_review.append(
                replace(
                    resolution,
                    accepted=False,
                    reason="accepted resolution has no target; resolve manually",
                )
            )
            continue
        competitors = collisions.get(resolution.best.target.key)
        if competitors is None:
            adjusted.accepted.append(resolution)
            continue
        other_names = [
            candidate.source_record.raw_name
            for candidate in competitors
            if candidate is not resolution
        ]
        adjusted.needs_review.append(
            replace(
                resolution,
                accepted=False,
                reason=(
                    f"collision: {len(competitors)} source records claim "
                    f"{resolution.best.target.raw_name!r} — also "
                    f"{', '.join(repr(name) for name in other_names[:3])}. "
                    "Resolve manually"
                ),
            )
        )
    return adjusted


def _apply_row(projection: Projection, row: ProjectionSourceRow) -> None:
    for field_name in CANONICAL_STAT_FIELDS:
        setattr(projection, field_name, getattr(row, field_name))


def _write_games_played_assumption(
    session: Session, projection: Projection, row: ProjectionSourceRow
) -> None:
    if row.assumed_games_played is None and row.assumed_games_played_raw is None:
        return
    session.add(
        SourceGamesPlayedAssumption(
            projection_id=projection.id,
            assumed_games_played=row.assumed_games_played,
            assumed_games_played_raw=row.assumed_games_played_raw,
        )
    )


def _nba_player_ids_by_key(session: Session) -> dict[str, int]:
    return {
        link.external_id: link.player_id
        for link in session.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.NBA)
        )
    }


def _enforce_manual_crosswalk_decisions(
    session: Session,
    report: ResolutionReport,
    *,
    source: ExternalSource,
) -> ResolutionReport:
    """Demote inferred matches that contradict a human crosswalk decision."""
    manual_by_external_id = {
        link.external_id: link
        for link in session.scalars(
            select(PlayerExternalId).where(
                PlayerExternalId.source == source,
                PlayerExternalId.is_manual_override.is_(True),
            )
        )
    }
    nba_player_ids = _nba_player_ids_by_key(session)
    adjusted = ResolutionReport(
        needs_review=list(report.needs_review),
        unmatched=list(report.unmatched),
    )
    for resolution in report.accepted:
        if resolution.best is None:
            adjusted.needs_review.append(
                replace(
                    resolution,
                    accepted=False,
                    reason="accepted resolution has no target; resolve manually",
                )
            )
            continue
        manual = manual_by_external_id.get(resolution.source_record.key)
        accepted_player_id = nba_player_ids.get(resolution.best.target.key)
        if manual is not None and manual.player_id != accepted_player_id:
            adjusted.needs_review.append(
                replace(
                    resolution,
                    accepted=False,
                    reason=(
                        "manual crosswalk conflict: resolver target disagrees with "
                        "the human-selected player"
                    ),
                )
            )
            continue
        adjusted.accepted.append(resolution)
    return adjusted


def _crosswalk_resolutions_preserving_manual_incumbents(
    session: Session,
    report: ResolutionReport,
    *,
    source: ExternalSource,
) -> list[Resolution]:
    """Prevent automation from competing with a current human-selected alias."""
    manual_by_player_id = {
        link.player_id: link
        for link in session.scalars(
            select(PlayerExternalId).where(
                PlayerExternalId.source == source,
                PlayerExternalId.current_for_source == source.value,
                PlayerExternalId.is_manual_override.is_(True),
            )
        )
    }
    nba_player_ids = _nba_player_ids_by_key(session)
    crosswalk_resolutions: list[Resolution] = []
    for resolution in report.all_resolutions():
        if not resolution.accepted or resolution.best is None:
            crosswalk_resolutions.append(resolution)
            continue
        player_id = nba_player_ids.get(resolution.best.target.key)
        incumbent = manual_by_player_id.get(player_id) if player_id is not None else None
        if incumbent is None or incumbent.external_id == resolution.source_record.key:
            crosswalk_resolutions.append(resolution)
            continue
        crosswalk_resolutions.append(
            replace(
                resolution,
                accepted=False,
                reason=(
                    "projection target accepted; automated crosswalk write skipped "
                    "because a manual alias is current for that player"
                ),
            )
        )
    return crosswalk_resolutions


def _import_projection_rows(
    session: Session,
    *,
    projection_import: ProjectionImport,
    rows: Sequence[ProjectionSourceRow],
    source: ExternalSource,
) -> tuple[ImportCounts, ResolutionReport]:
    """Resolve identities and exactly reconcile one import's projection rows.

    Only **accepted** resolutions produce a ``projections`` row — a needs-
    review or unmatched row belongs in the report handed back to a human
    (``hoops_gm.identity.report``), not in the data with a guessed
    ``player_id`` attached to it. Existing import-owned rows are deleted before
    rebuilding, in the caller's transaction, so stale identities and their
    one-to-one games-played assumptions cannot survive a re-resolution.
    """
    report = _enforce_manual_crosswalk_decisions(
        session,
        resolve_projection_identities(session, rows, source=source),
        source=source,
    )
    if _owns_current_source_crosswalk(session, projection_import):
        import_resolutions(
            session,
            _crosswalk_resolutions_preserving_manual_incumbents(
                session,
                report,
                source=source,
            ),
            source=source,
        )

    player_by_target_key = _nba_player_ids_by_key(session)
    rows_by_key = {_projection_source_key(row): row for row in rows}

    existing = list(
        session.scalars(
            select(Projection).where(Projection.projection_import_id == projection_import.id)
        )
    )
    previous_player_ids = {projection.player_id for projection in existing}
    for projection in existing:
        session.delete(projection)
    session.flush()

    counts = ImportCounts()
    written_player_ids: set[int] = set()
    for resolution in report.accepted:
        key = resolution.source_record.key
        row = rows_by_key.get(key)
        player_id = (
            player_by_target_key.get(resolution.best.target.key)
            if resolution.best is not None
            else None
        )
        if row is None or player_id is None:
            counts.skipped += 1
            continue

        projection = Projection(
            projection_import_id=projection_import.id,
            player_id=player_id,
            season=projection_import.season,
        )
        session.add(projection)
        written_player_ids.add(player_id)
        if player_id in previous_player_ids:
            counts.updated += 1
        else:
            counts.created += 1

        _apply_row(projection, row)
        session.flush()  # projection.id is required by the 1:1 GP assumption row
        _write_games_played_assumption(session, projection, row)

    counts.superseded = len(previous_player_ids - written_player_ids)
    session.flush()
    return counts, report


def _owns_current_source_crosswalk(
    session: Session,
    projection_import: ProjectionImport,
) -> bool:
    """Only the newest source/season import may mutate the global crosswalk.

    Projection rows are immutable per import, but ``player_external_ids`` is a
    source-wide current view. Replaying an older file must reconcile that
    historical import without rewinding identifiers established by a newer
    file or season.
    """
    current_import_id = session.scalar(
        select(ProjectionImport.id)
        .where(ProjectionImport.source_id == projection_import.source_id)
        .order_by(
            ProjectionImport.season.desc(),
            ProjectionImport.imported_at.desc(),
            ProjectionImport.id.desc(),
        )
        .limit(1)
    )
    return current_import_id == projection_import.id


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
    #: The post-parse verification report. Reaching this object at all means no
    #: check *failed* — a failure raises. It is carried anyway because
    #: ``NOT_RUN`` is not a pass: the baked-in-availability check is always
    #: ``NOT_RUN`` here, since the importer holds no prior-season observations,
    #: and a caller must be able to see that rather than infer a clean bill from
    #: a successful return.
    verification: VerificationReport


def import_projection_csv(
    session: Session,
    *,
    source: ExternalSource,
    display_name: str,
    season: str,
    csv_bytes: bytes,
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
    the private reconciliation boundary). A caller with a CSV file and nothing
    else needs only this function; parsed rows cannot bypass profile
    verification and byte/lineage binding through a second public writer.
    """
    content_sha256 = _content_checksum(csv_bytes)
    csv_text = _decode_csv(csv_bytes)

    registered_profile = PROFILES_BY_SOURCE.get(source)
    resolved_profile = profile or registered_profile
    if resolved_profile is None:
        raise ValueError(
            f"no built-in column profile for {source!r}; pass one explicitly via `profile=`"
        )
    if resolved_profile.source is not source:
        raise ValueError(
            f"profile source {resolved_profile.source.value!r} does not match "
            f"declared import source {source.value!r}"
        )
    if type(resolved_profile) is not ColumnProfile:
        raise ProjectionProfileError("projection profiles must be concrete ColumnProfile records")
    if resolved_profile is not registered_profile:
        raise ProjectionProfileError(
            f"profile {resolved_profile.profile_id!r} version {resolved_profile.version!r} "
            "is not the committed registry profile for this source; custom mappings are "
            "parse-preview only until backed by real fixture evidence"
        )
    if source not in PROJECTION_IMPORT_SOURCES:
        raise ProjectionProfileError(
            f"{source.value} is an identity-anchor namespace, not a projection CSV source"
        )
    wildcard_verified = "*" in resolved_profile.verified_seasons
    verified_for_season = (
        resolved_profile.verified
        and resolved_profile.verification_evidence is not None
        and bool(resolved_profile.verification_evidence.strip())
        and (
            season in resolved_profile.verified_seasons
            or (wildcard_verified and resolved_profile is MANUAL_PROFILE)
        )
    )
    if not verified_for_season:
        raise ProjectionProfileError(
            f"profile {resolved_profile.profile_id!r} version {resolved_profile.version!r} "
            f"is not verified for {source.value} season {season}; parse-preview is allowed, "
            "but production import requires a versioned mapping backed by real source evidence"
        )

    parsed = parse_projection_csv(csv_text, resolved_profile, season=season)
    verification = verify_projection_batch(resolved_profile.profile_id, parsed.rows)
    blocking = [
        finding for finding in verification.failures if finding.check in IMPORT_BLOCKING_CHECKS
    ]
    if blocking:
        detail = "; ".join(f"{finding.check}: {finding.detail}" for finding in blocking)
        raise ProjectionVerificationError(
            f"projection batch for {source.value} season {season} failed post-parse "
            f"verification and was not imported - {detail}",
            verification,
        )
    profile_definition = _profile_definition(resolved_profile)
    profile_definition_sha256 = _profile_definition_sha256(
        resolved_profile,
        profile_definition,
    )
    profile_lineage = _build_profile_lineage(
        resolved_profile,
        parsed,
        definition=profile_definition,
        definition_sha256=profile_definition_sha256,
    )
    _hold_import_lock_until_transaction_end(
        session,
        source.value,
    )
    # Before the read it protects, not after it. The old `FOR UPDATE` ran once
    # the source row had already been read and once the import row had already
    # been created, so even on PostgreSQL it was closing the window later than
    # it opened.
    _lock_projection_source_scope(session, source, season)

    source_row = get_or_create_projection_source(
        session,
        source=source,
        display_name=display_name,
        assumed_scoring_type=assumed_scoring_type,
    )
    profile_version_row = _get_or_create_profile_version(
        session,
        source=source_row,
        profile=resolved_profile,
        definition=profile_definition,
        definition_sha256=profile_definition_sha256,
    )
    projection_import, created = _get_or_create_projection_import(
        session,
        source=source_row,
        profile_version_row=profile_version_row,
        season=season,
        content_sha256=content_sha256,
        profile_lineage=profile_lineage,
        original_filename=original_filename,
        assumed_scoring_type=assumed_scoring_type,
        raw_payload_ref=raw_payload_ref,
    )

    counts, identity_report = _import_projection_rows(
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
        verification=verification,
    )
