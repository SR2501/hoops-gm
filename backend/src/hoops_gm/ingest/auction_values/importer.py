"""Importing a published auction-value table into the market layer.

Reuses the CSV importer's *patterns* — content hash, immutable profile
lineage, versioned import, fail-closed identity resolution — and none of its
tables. See ``db/models/market.py`` for why.

## Identity, and why nothing is written to the crosswalk

The projection importer resolves names and then writes ``player_external_ids``
rows, giving each vendor a namespace in the crosswalk. This importer resolves
names and writes **nothing** to the crosswalk, for the same reason the tables
are separate: ``PlayerExternalId.source`` is an :class:`ExternalSource`, and
Yahoo and FantraxHQ are not in that vocabulary. Adding them would widen an
identity namespace to hold publishers that have no opinion about player
identity worth persisting — their tables carry a display name and nothing else.

So a market row anchors to ``player_id`` via the NBA-keyed resolution and
keeps ``source_player_name`` beside it as the matching evidence. If a
publisher ever exposes a stable id, ``source_player_id`` records it without
promoting it to a crosswalk key.

## Fail-closed

Rows the resolver will not accept are **not imported**. They are counted, and
the counts are stored on the import. A market benchmark attached to the wrong
player is worse than a missing one: it produces a confident, defensible-looking
disagreement about a player the source never priced.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import BasisEvidence, ExternalSource, ScoringType
from hoops_gm.db.models.identity import PlayerExternalId
from hoops_gm.db.models.market import (
    BASIS_FIELDS,
    AuctionValueImport,
    AuctionValueSource,
    AuctionValueSourceInput,
    PublishedAuctionValue,
)
from hoops_gm.identity.resolver import IdentityResolver, ResolutionReport, ResolvableRecord
from hoops_gm.ingest.auction_values.models import AuctionValueParseResult
from hoops_gm.ingest.auction_values.parser import parse_auction_value_csv
from hoops_gm.ingest.auction_values.profiles import (
    AuctionSourceDescriptor,
    AuctionValueProfile,
    profile_for,
    source_for,
)
from hoops_gm.ingest.projections.importer import build_player_targets

__all__ = [
    "AuctionImportOutcome",
    "BasisDeclaration",
    "BasisIncomplete",
    "import_auction_value_csv",
    "register_auction_value_source",
]


class BasisIncomplete(ValueError):
    """A basis field was neither stated, inferred, nor investigated.

    Raised rather than defaulted. A default budget is the failure this unit
    exists to prevent: it would make an unknown pool look like a known one, and
    every dollar in the file would then be silently comparable to ours when it
    is not.
    """


@dataclass(frozen=True)
class BasisDeclaration:
    """What the operator establishes about the price list they are importing.

    Every field is a value *and* how we came to know it. ``None`` is only legal
    when the corresponding evidence is ``UNESTABLISHED``, and the database
    enforces that pairing independently of this class — the CHECK is what makes
    it true, this is what makes it early.
    """

    budget: Decimal | None
    budget_evidence: BasisEvidence
    team_count: int | None
    team_count_evidence: BasisEvidence
    roster_size: int | None
    roster_size_evidence: BasisEvidence
    scoring_type: ScoringType | None
    scoring_type_evidence: BasisEvidence
    category_count: int | None
    category_count_evidence: BasisEvidence
    note: str | None = None

    def __post_init__(self) -> None:
        pairs = (
            ("budget", self.budget, self.budget_evidence),
            ("team_count", self.team_count, self.team_count_evidence),
            ("roster_size", self.roster_size, self.roster_size_evidence),
            ("scoring_type", self.scoring_type, self.scoring_type_evidence),
            ("category_count", self.category_count, self.category_count_evidence),
        )
        # Asserting the shape we expect rather than the absence of one we fear:
        # if BASIS_FIELDS ever grows a column, this fails loudly instead of
        # validating a subset and reporting success.
        if len(pairs) != len(BASIS_FIELDS):
            raise BasisIncomplete(
                f"BasisDeclaration checks {len(pairs)} fields but the schema declares "
                f"{len(BASIS_FIELDS)}; a basis field would go unvalidated"
            )
        inferred_any = False
        for name, value, evidence in pairs:
            if evidence is BasisEvidence.UNESTABLISHED:
                if value is not None:
                    raise BasisIncomplete(
                        f"{name} is recorded as unestablished but carries a value; a number "
                        "nobody stands behind must not be stored as if somebody does"
                    )
            elif value is None:
                raise BasisIncomplete(
                    f"{name} claims evidence {evidence.value!r} but has no value. State it, "
                    "infer it with a note, or record it as unestablished — there is no default"
                )
            if evidence is BasisEvidence.INFERRED:
                inferred_any = True
        if inferred_any and not (self.note or "").strip():
            raise BasisIncomplete(
                "an inferred basis requires a note saying what it was inferred from; an "
                "inference the next reader cannot reconstruct is just an assertion"
            )


@dataclass(frozen=True)
class AuctionImportOutcome:
    """Everything one import produced, including what it refused."""

    auction_import: AuctionValueImport
    source_row: AuctionValueSource
    created: bool
    parsed: AuctionValueParseResult
    identity_report: ResolutionReport
    values_written: int


def _content_checksum(payload: bytes) -> str:
    """SHA-256 over CRLF-normalised bytes.

    Normalised because these files are transcribed by hand from a browser and
    the line ending depends on the operator's tool, not on the publisher. An
    unnormalised hash would report the same table as new content every time the
    editor changed.
    """
    return hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest()


def _decode_csv(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("could not decode the file as UTF-8 or CP1252")


def register_auction_value_source(
    session: Session, descriptor: AuctionSourceDescriptor
) -> AuctionValueSource:
    """Ensure ``descriptor`` and its inputs exist, and match what we now believe.

    Idempotent, and it *updates* an existing row's derivation and inputs.
    Lineage is a finding rather than a fixture: establishing that a publisher
    derives from a projection set we import is exactly the discovery this guard
    exists to act on, and it must be able to arrive after the first import.
    """
    source_row = session.scalar(
        select(AuctionValueSource).where(AuctionValueSource.slug == descriptor.slug)
    )
    if source_row is None:
        source_row = AuctionValueSource(slug=descriptor.slug)
        session.add(source_row)

    source_row.display_name = descriptor.display_name
    source_row.publisher_url = descriptor.publisher_url
    source_row.derivation_method = descriptor.derivation_method
    source_row.derivation_evidence = descriptor.derivation_evidence
    source_row.notes = descriptor.notes
    source_row.data_layer = "market"
    session.flush()

    existing = {
        (row.input_kind, row.input_label): row
        for row in session.scalars(
            select(AuctionValueSourceInput).where(
                AuctionValueSourceInput.source_id == source_row.id
            )
        )
    }
    for item in descriptor.inputs:
        row = existing.pop((item.input_kind, item.input_label), None)
        if row is None:
            row = AuctionValueSourceInput(
                source_id=source_row.id,
                input_kind=item.input_kind,
                input_label=item.input_label,
            )
            session.add(row)
        row.our_projection_source = item.our_projection_source
        row.evidence = item.evidence
    for stale in existing.values():
        session.delete(stale)
    session.flush()
    return source_row


def _resolve_player_ids(
    session: Session, names: list[tuple[str, str | None, str | None]]
) -> tuple[dict[str, int], ResolutionReport]:
    """Map each distinct source player name onto a canonical ``player_id``.

    Returns only accepted matches. Anything the resolver would not accept is
    left out and counted, which is what makes this fail closed.
    """
    targets = build_player_targets(session)
    nba_key_to_player_id = {
        link.external_id: link.player_id
        for link in session.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.NBA)
        )
    }
    records = [
        ResolvableRecord.build(key=name, name=name, team=team, position=position)
        for name, team, position in names
    ]
    resolver = IdentityResolver(targets)
    inferred = resolver.resolve(records)
    report = ResolutionReport(
        accepted=list(inferred.accepted),
        needs_review=list(inferred.needs_review),
        unmatched=list(inferred.unmatched),
    )

    resolved: dict[str, int] = {}
    for resolution in report.accepted:
        if resolution.best is None:  # pragma: no cover - accepted implies a best
            continue
        target_key = resolution.best.target.key
        player_id = nba_key_to_player_id.get(target_key)
        if player_id is None:  # pragma: no cover - see the invariant below
            # Unreachable rather than defensive, and stated as a raise so it
            # stays that way. ``build_player_targets`` derives every target key
            # from ``player_external_ids`` where source = NBA, and the map above
            # is the same query in the same session, so an accepted match whose
            # key is absent means the two have diverged. Skipping silently would
            # drop a priced player out of every count without saying so; this
            # fails where the divergence is.
            raise ValueError(
                f"resolution target {target_key!r} has no NBA crosswalk row, so "
                "build_player_targets and the crosswalk lookup have diverged"
            )
        resolved[resolution.source_record.key] = player_id
    return resolved, report


def import_auction_value_csv(
    session: Session,
    *,
    profile_id: str,
    season: str,
    as_of_date: date,
    csv_bytes: bytes,
    basis: BasisDeclaration,
    original_filename: str | None = None,
    imported_at: datetime | None = None,
    profile: AuctionValueProfile | None = None,
) -> AuctionImportOutcome:
    """Import one published price list.

    ``csv_bytes`` is explicit and required: there is no path discovery and no
    network call anywhere in this module, following the manual-download adapter
    shape in ``docs/adapters/basketball-monster-projections.md``. Whatever
    fetched the bytes is the operator's browser, which keeps us clear of every
    publisher's crawling and redistribution terms.
    """
    resolved_profile = profile or profile_for(profile_id)
    descriptor = source_for(resolved_profile.source_slug)
    source_row = register_auction_value_source(session, descriptor)

    content_sha256 = _content_checksum(csv_bytes)
    csv_text = _decode_csv(csv_bytes)
    parsed = parse_auction_value_csv(csv_text, resolved_profile)

    existing = session.scalar(
        select(AuctionValueImport).where(
            AuctionValueImport.source_id == source_row.id,
            AuctionValueImport.season == season,
            AuctionValueImport.as_of_date == as_of_date,
            AuctionValueImport.content_sha256 == content_sha256,
        )
    )
    created = existing is None
    auction_import = existing or AuctionValueImport(
        source_id=source_row.id,
        season=season,
        as_of_date=as_of_date,
        content_sha256=content_sha256,
    )
    if created:
        session.add(auction_import)

    auction_import.imported_at = imported_at or datetime.now(UTC)
    auction_import.original_filename = original_filename
    auction_import.profile_id = resolved_profile.profile_id
    auction_import.profile_version = resolved_profile.version
    auction_import.profile_header_contract_verified = resolved_profile.header_contract_verified
    auction_import.profile_lineage = resolved_profile.lineage()
    auction_import.basis_budget = basis.budget
    auction_import.basis_budget_evidence = basis.budget_evidence
    auction_import.basis_team_count = basis.team_count
    auction_import.basis_team_count_evidence = basis.team_count_evidence
    auction_import.basis_roster_size = basis.roster_size
    auction_import.basis_roster_size_evidence = basis.roster_size_evidence
    auction_import.basis_scoring_type = basis.scoring_type
    auction_import.basis_scoring_type_evidence = basis.scoring_type_evidence
    auction_import.basis_category_count = basis.category_count
    auction_import.basis_category_count_evidence = basis.category_count_evidence
    auction_import.basis_note = basis.note
    session.flush()

    distinct: dict[str, tuple[str, str | None, str | None]] = {}
    for row in parsed.rows:
        distinct.setdefault(row.player_name, (row.player_name, row.team, row.position))
    resolved, identity_report = _resolve_player_ids(session, list(distinct.values()))

    session.query(PublishedAuctionValue).filter(
        PublishedAuctionValue.import_id == auction_import.id
    ).delete(synchronize_session=False)

    written = 0
    for row in parsed.rows:
        player_id = resolved.get(row.player_name)
        if player_id is None:
            continue
        session.add(
            PublishedAuctionValue(
                import_id=auction_import.id,
                player_id=player_id,
                season=season,
                as_of_date=as_of_date,
                value_kind=row.value_kind,
                value_dollars=row.value_dollars,
                value_raw=row.value_raw,
                source_player_id=row.source_player_id,
                source_player_name=row.player_name,
                data_layer="market",
            )
        )
        written += 1

    auction_import.row_count = parsed.total_rows
    auction_import.matched_count = len(identity_report.accepted)
    auction_import.needs_review_count = len(identity_report.needs_review)
    auction_import.unmatched_count = len(identity_report.unmatched)
    auction_import.rejected_count = len(parsed.rejected_row_numbers)
    session.flush()

    return AuctionImportOutcome(
        auction_import=auction_import,
        source_row=source_row,
        created=created,
        parsed=parsed,
        identity_report=identity_report,
        values_written=written,
    )
