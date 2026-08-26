"""Ingest what the feed read, and decide — narrowly — what to do about it.

Three verbs, deliberately separate.

:func:`ingest` reads artifacts and stores claims. It never touches
``draft_events``. Running it is always safe: worst case it stores rows nobody
acts on.

:func:`apply_observations` turns stored claims into log entries, through
:mod:`hoops_gm.draft.service` and only through it. This writes to **our own**
database and never to Fantrax. ``api/routes/drafts.py`` is the authority for
why that is not the Automation gate: the write path that gate governs is the
one that acts on the owner's Fantrax account, and nothing in this package sends
Fantrax anything but a GET.

:func:`feed_status` reports. It computes nothing it does not publish the
provenance of.

**The one decision made here, stated so it can be argued with.** An observed
selection is appended to the log automatically. It is not held for
confirmation. The unit exists because the owner cannot both think about value
and be a keyboard at 7:14pm, and a feed that requires a click per pick is a
keyboard with extra steps. The safety of that is not "we trust the recogniser";
it is that the log is append-only and correctable by ``void``, that every
appended event is traceable back to the exact bytes that caused it, and that a
wrong claim is refused by ``draft.state``'s derivation before it is written.

**What is deliberately not automatic.** A sale is appended too, but a
*disagreement* between the two sources never is: it is reported and left. And
an ordered draft stops applying at the first out-of-turn pick rather than
skipping it, because skipping desynchronises every subsequent pick and the
owner would find out at pick 30 rather than pick 8.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models import (
    BridgePayload,
    Draft,
    DraftFeedObservation,
    DraftFeedTransport,
    DraftParticipant,
    DraftStatus,
    FantasyTeam,
    League,
)
from hoops_gm.draft import service as draft_service
from hoops_gm.draft.feed.observations import (
    InstantKind,
    InstantProvenance,
    ObservedInstant,
    RecognitionResult,
    SourceTransport,
    UnrecognisedShape,
    matching_key,
)
from hoops_gm.draft.feed.recognise import (
    RecognitionContext,
    league_id_in,
    recognise_bridge_payload,
    recognise_official_draft_picks,
)
from hoops_gm.draft.feed.reconcile import (
    ReconciliationReport,
    SourceFreshness,
    freshness_of,
    reconcile,
)
from hoops_gm.draft.state import DraftLogError
from hoops_gm.identity.names import normalize_key
from hoops_gm.ingest.fantrax_official.models import FantraxDraftPick

#: How many stored captures one ingest examines, newest first.
#:
#: ``bridge_payloads`` accumulates every captured response, not just draft ones,
#: and an unbounded scan is not a thing to discover during a live draft. A
#: republishing draft board produces a handful of captures per pick, so this is
#: several hundred picks of history — and the bound is *stated in the status
#: response*, so a truncated scan is visible rather than silently partial.
BRIDGE_SCAN_LIMIT = 400

#: How long a source may be quiet before the status endpoint says so.
DEFAULT_SILENCE_THRESHOLD = timedelta(minutes=2)


class DraftPickSource(Protocol):
    """The narrow slice of the official client this package needs.

    A protocol rather than the concrete client so a test can drive ingest with
    a recorded fixture and no network, and so this module does not depend on
    the adapter's construction.
    """

    def get_draft_picks_with_provenance(
        self, league_id: str, *, max_age: timedelta | None = ...
    ) -> tuple[list[FantraxDraftPick], str, datetime]: ...


@dataclass(frozen=True, slots=True)
class SourceOutcome:
    """What one ingest run made of one source."""

    transport: SourceTransport
    #: ``None`` when the source ran. A string when it could not run at all —
    #: not configured, league not linked, request failed. Published rather than
    #: raised, because one source being unavailable must not stop the other.
    unavailable: str | None = None
    #: Artifacts the source offered, before any filtering. Published alongside
    #: ``artifacts_examined`` because the two together separate "the bridge is
    #: quiet" (0 scanned) from "the bridge is busy but none of it is this
    #: league" (many scanned, 0 examined). One number cannot tell those apart,
    #: and they call for opposite actions from the owner mid-draft: check the
    #: userscript, or check the configured league id.
    artifacts_scanned: int = 0
    artifacts_examined: int = 0
    #: Artifacts that were examined and rejected outright, by reason.
    rejected: dict[str, int] = field(default_factory=dict)
    instants_recognised: int = 0
    observations_written: int = 0
    observations_already_present: int = 0
    unrecognised: tuple[UnrecognisedShape, ...] = ()
    #: True when the scan hit :data:`BRIDGE_SCAN_LIMIT` and older artifacts
    #: were therefore not looked at.
    scan_truncated: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    """The result of one ingest run across both sources."""

    sources: tuple[SourceOutcome, ...]
    context_unavailable: str | None = None


@dataclass(frozen=True, slots=True)
class AppliedEvent:
    """One log entry an observation caused."""

    observation_id: int
    sequence: int
    player_label: str | None
    kind: InstantKind


@dataclass(frozen=True, slots=True)
class ApplyOutcome:
    """What :func:`apply_observations` did, and what stopped it."""

    applied: tuple[AppliedEvent, ...] = ()
    #: ``(observation_id, reason)`` for each observation deliberately not
    #: appended. Always published: an observation that silently never becomes
    #: an event is indistinguishable from one that was never read.
    skipped: tuple[tuple[int, str], ...] = ()
    #: Set when application stopped early rather than finishing. An ordered
    #: draft that hits an out-of-turn pick stops here, because skipping it
    #: would desynchronise every pick after it.
    halted: str | None = None
    last_sequence: int = 0


def build_context(session: Session, draft: Draft) -> RecognitionContext | str:
    """The facts a candidate payload is checked against, or why there are none.

    Everything here is read from our own tables. ``team_external_ids`` comes
    from ``fantasy_teams.fantrax_team_id`` for the seats *this draft* declared,
    which is the independently-held fact that makes the recogniser's anchor an
    anchor rather than a hope. A draft whose seats are not linked to Fantrax
    teams — every mock against strangers — returns ``"seats_not_linked"`` and
    is not fed. That is a refusal, not a degradation: without the anchor the
    recogniser would be matching on guessed key names alone.
    """
    league = session.get(League, draft.league_id)
    if league is None:  # pragma: no cover - FK makes this unreachable
        return "league_missing"
    if not league.fantrax_league_id:
        return "league_not_linked"

    rows = session.execute(
        select(FantasyTeam.fantrax_team_id)
        .join(DraftParticipant, DraftParticipant.fantasy_team_id == FantasyTeam.id)
        .where(DraftParticipant.draft_id == draft.id)
        .where(FantasyTeam.fantrax_team_id.is_not(None))
    ).all()
    external_ids = frozenset(str(row[0]) for row in rows if row[0])
    if not external_ids:
        return "seats_not_linked"

    return RecognitionContext(
        fantrax_league_id=league.fantrax_league_id,
        team_external_ids=external_ids,
        draft_type=draft.draft_type,
    )


def _participant_by_external_id(session: Session, draft: Draft) -> dict[str, int]:
    rows = session.execute(
        select(FantasyTeam.fantrax_team_id, DraftParticipant.id)
        .join(DraftParticipant, DraftParticipant.fantasy_team_id == FantasyTeam.id)
        .where(DraftParticipant.draft_id == draft.id)
        .where(FantasyTeam.fantrax_team_id.is_not(None))
    ).all()
    return {str(external): participant_id for external, participant_id in rows if external}


def _existing_keys(session: Session, draft: Draft) -> set[tuple[str, str, str]]:
    rows = session.execute(
        select(
            DraftFeedObservation.transport,
            DraftFeedObservation.artifact_key,
            DraftFeedObservation.locator,
        ).where(DraftFeedObservation.draft_id == draft.id)
    ).all()
    return {(str(transport), artifact, locator) for transport, artifact, locator in rows}


def _store(
    session: Session,
    draft: Draft,
    result: RecognitionResult,
    *,
    participants: dict[str, int],
    existing: set[tuple[str, str, str]],
    bridge_payload_ids: dict[str, int] | None = None,
) -> tuple[int, int]:
    """Write recognised instants as observations. Returns ``(written, seen)``.

    Idempotent on ``(transport, artifact_key, locator)`` — checked in Python
    against a set read once, *and* backed by the unique constraint. The set
    alone would be a race and the constraint alone would abort the transaction
    on Postgres, so both are here: the set makes the ordinary re-ingest cheap
    and the constraint makes the guarantee real.
    """
    written = 0
    already = 0
    for instant in result.instants:
        provenance = instant.provenance
        key = (provenance.transport.value, provenance.artifact_key, provenance.locator)
        if key in existing:
            already += 1
            continue
        existing.add(key)
        row = DraftFeedObservation(
            draft_id=draft.id,
            transport=DraftFeedTransport(provenance.transport.value),
            artifact_key=provenance.artifact_key,
            locator=provenance.locator,
            recogniser=provenance.recogniser,
            observed_at=provenance.received_at,
            source_claimed_at=provenance.source_claimed_at,
            bridge_payload_id=(bridge_payload_ids or {}).get(provenance.artifact_key),
            kind=instant.kind,
            team_external_id=instant.team_external_id,
            participant_id=participants.get(instant.team_external_id or ""),
            player_label=instant.player_label,
            player_external_id=instant.player_external_id,
            overall_pick=instant.overall_pick,
            round_number=instant.round_number,
            pick_in_round=instant.pick_in_round,
            amount=instant.amount,
        )
        session.add(row)
        written += 1
    session.flush()
    return written, already


def _tally(counter: dict[str, int], reason: str) -> None:
    counter[reason] = counter.get(reason, 0) + 1


def ingest_bridge(
    session: Session,
    draft: Draft,
    context: RecognitionContext,
    *,
    scan_limit: int = BRIDGE_SCAN_LIMIT,
) -> SourceOutcome:
    """Read stored captures for this draft's league and store what they claim."""
    rows = list(
        session.execute(
            select(BridgePayload)
            .order_by(BridgePayload.created_at.desc(), BridgePayload.id.desc())
            .limit(scan_limit)
        )
        .scalars()
        .all()
    )
    participants = _participant_by_external_id(session, draft)
    existing = _existing_keys(session, draft)

    rejected: dict[str, int] = {}
    unrecognised: list[UnrecognisedShape] = []
    recognised = 0
    written = 0
    already = 0
    examined = 0

    for row in rows:
        # Cheap pre-filter on the URL, which carries the league id. Skipping
        # here rather than counting it as a rejection keeps the rejection
        # tallies about *draft* traffic instead of drowning them in every other
        # capture the bridge has ever stored.
        if league_id_in(row.request_url) != context.fantrax_league_id:
            continue
        examined += 1
        result = recognise_bridge_payload(
            url=row.request_url,
            body_json=row.body_json,
            dedupe_key=row.dedupe_key,
            received_at=row.created_at,
            captured_at=row.captured_at,
            context=context,
        )
        if result.rejected is not None:
            _tally(rejected, result.rejected)
        recognised += result.recognised_count
        unrecognised.extend(result.unrecognised)
        stored, seen = _store(
            session,
            draft,
            result,
            participants=participants,
            existing=existing,
            bridge_payload_ids={row.dedupe_key: row.id},
        )
        written += stored
        already += seen

    return SourceOutcome(
        transport=SourceTransport.BRIDGE_CAPTURE,
        artifacts_scanned=len(rows),
        artifacts_examined=examined,
        rejected=rejected,
        instants_recognised=recognised,
        observations_written=written,
        observations_already_present=already,
        unrecognised=_summarise(unrecognised),
        scan_truncated=len(rows) >= scan_limit,
        notes=(
            f"Scanned the {scan_limit} newest captures; older ones were not examined."
            if len(rows) >= scan_limit
            else "Scanned every stored capture.",
        ),
    )


def ingest_official(
    session: Session,
    draft: Draft,
    context: RecognitionContext,
    *,
    client: DraftPickSource | None,
) -> SourceOutcome:
    """Ask the official API what it thinks happened, and store that separately.

    A failure here is reported, never raised. The bridge is the primary path
    and losing corroboration must not cost the owner his live board.
    """
    if client is None:
        return SourceOutcome(
            transport=SourceTransport.OFFICIAL_HTTP,
            unavailable="official_client_not_configured",
            notes=(
                "No Fantrax official client is configured on this app, so the "
                "corroborating source did not run.",
            ),
        )
    try:
        picks, payload_sha256, observed_at = client.get_draft_picks_with_provenance(
            context.fantrax_league_id
        )
    except Exception as error:  # reported, never raised
        return SourceOutcome(
            transport=SourceTransport.OFFICIAL_HTTP,
            unavailable=f"{type(error).__name__}: {error}",
        )

    result = recognise_official_draft_picks(
        picks,
        artifact_key=f"sha256:{payload_sha256}",
        received_at=observed_at,
        context=context,
    )
    written, already = _store(
        session,
        draft,
        result,
        participants=_participant_by_external_id(session, draft),
        existing=_existing_keys(session, draft),
    )
    return SourceOutcome(
        transport=SourceTransport.OFFICIAL_HTTP,
        artifacts_scanned=1,
        artifacts_examined=1,
        rejected={result.rejected: 1} if result.rejected else {},
        instants_recognised=result.recognised_count,
        observations_written=written,
        observations_already_present=already,
        unrecognised=result.unrecognised,
        notes=result.notes,
    )


def _summarise(shapes: list[UnrecognisedShape]) -> tuple[UnrecognisedShape, ...]:
    """Collapse repeated unrecognised shapes, keeping the count.

    A republishing draft board produces the same unreadable block on every
    capture. Publishing four hundred identical entries would bury the one
    distinct shape that matters, and reporting only the first would hide how
    much traffic is going unread.
    """
    merged: dict[tuple[tuple[str, ...], str], UnrecognisedShape] = {}
    for shape in shapes:
        key = (shape.keys, shape.reason)
        seen = merged.get(key)
        if seen is None:
            merged[key] = shape
        else:
            merged[key] = UnrecognisedShape(
                keys=seen.keys,
                occurrences=seen.occurrences + shape.occurrences,
                example_locator=seen.example_locator,
                reason=seen.reason,
            )
    return tuple(sorted(merged.values(), key=lambda shape: -shape.occurrences))


def ingest(
    session: Session,
    draft: Draft,
    *,
    client: DraftPickSource | None = None,
    scan_limit: int = BRIDGE_SCAN_LIMIT,
) -> IngestOutcome:
    """Run both sources. Neither can stop the other."""
    context = build_context(session, draft)
    if isinstance(context, str):
        return IngestOutcome(sources=(), context_unavailable=context)
    return IngestOutcome(
        sources=(
            ingest_bridge(session, draft, context, scan_limit=scan_limit),
            ingest_official(session, draft, context, client=client),
        )
    )


def _to_instant(row: DraftFeedObservation) -> ObservedInstant:
    return ObservedInstant(
        kind=InstantKind(row.kind.value),
        provenance=InstantProvenance(
            transport=SourceTransport(row.transport.value),
            artifact_key=row.artifact_key,
            recogniser=row.recogniser,
            received_at=row.observed_at,
            source_claimed_at=row.source_claimed_at,
            locator=row.locator,
        ),
        team_external_id=row.team_external_id,
        player_label=row.player_label,
        player_external_id=row.player_external_id,
        overall_pick=row.overall_pick,
        round_number=row.round_number,
        pick_in_round=row.pick_in_round,
        amount=row.amount,
    )


def load_observations(session: Session, draft: Draft) -> list[DraftFeedObservation]:
    return list(
        session.execute(
            select(DraftFeedObservation)
            .where(DraftFeedObservation.draft_id == draft.id)
            .order_by(DraftFeedObservation.observed_at, DraftFeedObservation.id)
        )
        .scalars()
        .all()
    )


def _held_keys(state: Any) -> dict[str, int]:
    """Player keys already on the board, mapped to the log sequence that put
    them there. Used to recognise a republished pick as one we already have."""
    held: dict[str, int] = {}
    for participant in state.participants:
        for holding in participant.holdings:
            held[holding.player_key] = holding.event_sequence
    return held


def _apply_order(row: DraftFeedObservation) -> tuple[int, int, int, str]:
    """Selections in the coordinate the source gave, everything else by arrival.

    An ordered draft refuses an out-of-turn pick, so applying in arrival order
    would fail whenever two captures land out of sequence — which they will,
    because a republishing board resends the whole list. Sorting by
    ``overall_pick`` puts them back in the order the draft actually happened.
    Observations without a coordinate sort after those with one, by arrival.
    """
    if row.overall_pick is not None:
        return (0, row.overall_pick, 0, row.locator)
    if row.round_number is not None and row.pick_in_round is not None:
        return (0, row.round_number * 1000 + row.pick_in_round, 0, row.locator)
    return (1, 0, row.id, row.locator)


def apply_observations(
    session: Session,
    draft: Draft,
    *,
    now: datetime | None = None,
) -> ApplyOutcome:
    """Append the log entries the stored observations imply.

    Through :mod:`hoops_gm.draft.service` only, so every derivation rule the
    tracker already enforces — turn order, roster limits, budget, a player
    taken twice — applies unchanged to a machine-fed pick. There is no
    fast path here that a hand-recorded pick does not also take.
    """
    stamp = now or datetime.now(UTC)
    state = draft_service.load_state(session, draft)
    if state.status is DraftStatus.CLOSED:
        return ApplyOutcome(halted="draft_closed", last_sequence=state.last_sequence)

    held = _held_keys(state)
    pending = [
        row
        for row in load_observations(session, draft)
        if row.applied_event_sequence is None and row.skipped_reason is None
    ]
    pending.sort(key=_apply_order)

    applied: list[AppliedEvent] = []
    skipped: list[tuple[int, str]] = []
    halted: str | None = None
    seen_this_run: set[str] = set()

    for row in pending:
        if row.participant_id is None:
            skipped.append((row.id, "no_seat_for_team_external_id"))
            row.skipped_reason = "no_seat_for_team_external_id"
            continue
        if not row.player_label:
            # The log requires a verbatim label for anything naming a player,
            # and inventing one from an external id would be a resolution this
            # package is not entitled to make.
            skipped.append((row.id, "no_player_label"))
            row.skipped_reason = "no_player_label"
            continue

        key = normalize_key(row.player_label)
        if key in seen_this_run:
            # Two sources naming the same player in one run. The first has
            # already been appended; this one is corroboration, not a second
            # pick. Checked before ``held`` because ``held`` was updated by
            # that append a moment ago and would otherwise absorb this row as
            # "already_in_log" — which is the reason meaning *the owner typed
            # it*, and conflating the two would delete the corroboration signal
            # from the status screen at the moment it is worth something.
            row.applied_event_sequence = held[key]
            row.applied_at = stamp
            row.skipped_reason = "duplicate_within_run"
            skipped.append((row.id, "duplicate_within_run"))
            continue
        if key in held:
            row.applied_event_sequence = held[key]
            row.applied_at = stamp
            row.skipped_reason = "already_in_log"
            skipped.append((row.id, "already_in_log"))
            continue

        try:
            if row.kind is InstantKind.SALE or row.amount is not None:
                if row.amount is None:
                    skipped.append((row.id, "sale_without_amount"))
                    row.skipped_reason = "sale_without_amount"
                    continue
                state = draft_service.record_sale(
                    session,
                    draft,
                    participant_id=row.participant_id,
                    amount=row.amount,
                    player_label=row.player_label,
                    note=f"feed:{row.transport.value}:{row.artifact_key}",
                )
            else:
                state = draft_service.record_pick(
                    session,
                    draft,
                    participant_id=row.participant_id,
                    player_label=row.player_label,
                    note=f"feed:{row.transport.value}:{row.artifact_key}",
                )
        except DraftLogError as error:
            row.skipped_reason = f"{error.code}: {error}"
            skipped.append((row.id, error.code))
            if error.code == "draft_pick_out_of_turn":
                # Stop rather than skip. Skipping would silently desynchronise
                # every pick after this one and the owner would find out much
                # later, which is the worst possible time.
                halted = error.code
                break
            continue

        row.applied_event_sequence = state.last_sequence
        row.applied_at = stamp
        held[key] = state.last_sequence
        seen_this_run.add(key)
        applied.append(
            AppliedEvent(
                observation_id=row.id,
                sequence=state.last_sequence,
                player_label=row.player_label,
                kind=row.kind,
            )
        )

    session.flush()
    return ApplyOutcome(
        applied=tuple(applied),
        skipped=tuple(skipped),
        halted=halted,
        last_sequence=state.last_sequence,
    )


@dataclass(frozen=True, slots=True)
class FeedStatus:
    """Everything the screen needs to say how much it can be trusted."""

    draft_id: int
    #: ``None`` when the feed can run. A string when it cannot be fed at all.
    context_unavailable: str | None
    #: Our clock at the moment this was computed, so a client can tell how old
    #: the *status* is, not just how old the feed is.
    as_of: datetime
    freshness: tuple[SourceFreshness, ...]
    reconciliation: ReconciliationReport | None
    observation_count: int
    applied_count: int
    pending_count: int
    skipped: tuple[tuple[str, int], ...]
    last_sequence: int


def feed_status(
    session: Session,
    draft: Draft,
    *,
    now: datetime | None = None,
    silence_threshold: timedelta = DEFAULT_SILENCE_THRESHOLD,
) -> FeedStatus:
    """How fresh each source is, and where the two disagree.

    Every figure is computed on ``now`` — our clock — against ``observed_at``,
    which is also our clock. No source's own timestamp reaches an arithmetic
    operation here.
    """
    stamp = now or datetime.now(UTC)
    context = build_context(session, draft)
    rows = load_observations(session, draft)
    instants = [_to_instant(row) for row in rows]

    by_transport: dict[SourceTransport, list[ObservedInstant]] = {
        SourceTransport.BRIDGE_CAPTURE: [],
        SourceTransport.OFFICIAL_HTTP: [],
    }
    for instant in instants:
        by_transport[instant.provenance.transport].append(instant)

    if instants:
        report = reconcile(
            by_transport[SourceTransport.BRIDGE_CAPTURE],
            by_transport[SourceTransport.OFFICIAL_HTTP],
            now=stamp,
            silence_threshold=silence_threshold,
        )
        freshness = report.freshness
    else:
        report = None
        freshness = tuple(
            freshness_of([], transport=transport, now=stamp, silence_threshold=silence_threshold)
            for transport in (SourceTransport.BRIDGE_CAPTURE, SourceTransport.OFFICIAL_HTTP)
        )

    skipped: dict[str, int] = {}
    for row in rows:
        if row.skipped_reason:
            _tally(skipped, row.skipped_reason.split(":")[0])

    applied = sum(1 for row in rows if row.applied_event_sequence is not None)
    pending = sum(
        1 for row in rows if row.applied_event_sequence is None and row.skipped_reason is None
    )
    state = draft_service.load_state(session, draft)

    return FeedStatus(
        draft_id=draft.id,
        context_unavailable=context if isinstance(context, str) else None,
        as_of=stamp,
        freshness=freshness,
        reconciliation=report,
        observation_count=len(rows),
        applied_count=applied,
        pending_count=pending,
        skipped=tuple(sorted(skipped.items())),
        last_sequence=state.last_sequence,
    )


def instants_for(rows: list[DraftFeedObservation]) -> list[ObservedInstant]:
    """Rehydrate stored rows into the pure type, keeping provenance intact."""
    return [_to_instant(row) for row in rows]


def observation_key(row: DraftFeedObservation) -> tuple[str, str] | None:
    """The reconciliation key for a stored row, via the same function the pure
    path uses — so a stored row and a live reading can never key differently."""
    return matching_key(_to_instant(row))
