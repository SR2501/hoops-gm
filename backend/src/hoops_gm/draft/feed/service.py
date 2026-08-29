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
RPC selection with an independently anchored team id is appended to the log
automatically. It is not held for
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

Rendered-board selections are the explicit exception. Their column ordinal has
no established binding to ``DraftParticipant``, so they are stored as
``source_board_evidence_only`` and exposed through :func:`source_board_evidence`;
they never enter the application queue.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.db.lineage import lock_refresh_scope
from hoops_gm.db.models import (
    BridgePayload,
    Draft,
    DraftFeedObservation,
    DraftFeedTransport,
    DraftParticipant,
    DraftSourceBoardReading,
    DraftSourceBoardState,
    DraftStatus,
    FantasyTeam,
    League,
    RefreshArtifactType,
)
from hoops_gm.draft import service as draft_service
from hoops_gm.draft.feed.observations import (
    InstantKind,
    InstantProvenance,
    ObservedInstant,
    RecognitionResult,
    SourceTransport,
    UnrecognisedShape,
    arrival_order,
    matching_key,
    publication_order,
)
from hoops_gm.draft.feed.recognise import (
    BOARD_RECOGNISER,
    RPC_CAPTURE_SOURCES,
    SNAPSHOT_CAPTURE_SOURCES,
    RecognitionContext,
    league_id_in,
    league_id_in_page_url,
    recognise_board_snapshot,
    recognise_bridge_payload,
    recognise_official_draft_picks,
)
from hoops_gm.draft.feed.reconcile import (
    ReconciliationReport,
    SourceFreshness,
    freshness_of,
    reconcile,
    values_disagree,
)
from hoops_gm.draft.state import DraftLogError
from hoops_gm.identity.names import normalize_key
from hoops_gm.ingest.fantrax_official.models import FantraxDraftPick

logger = logging.getLogger(__name__)

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

#: How many candidate captures the proof-of-life lookup re-parses, newest first.
#:
#: The SQL substring pre-filter can match rows the exact ``league_id_in`` check
#: then rejects, so the scan has to be able to walk past them. Bounded for the
#: same reason as :data:`BRIDGE_SCAN_LIMIT`: an unbounded query is not a thing to
#: discover mid-draft. Erring low costs a false ``contact_is_known=False``, which
#: is the safe direction — it degrades to the instant clock.
_CONTACT_SCAN_LIMIT = 50

#: How many *board snapshots* one ingest parses, newest first.
#:
#: Separate from :data:`BRIDGE_SCAN_LIMIT`, and much smaller, because the two
#: bound different costs. Reading an RPC body is a dictionary walk; reading a
#: board is an HTML parse of the whole page, measured at **49 ms** on the
#: recorded 216-pick, 225 KB board. At the 400-capture scan limit that is twenty
#: seconds of CPU on a request the owner is making mid-draft.
#:
#: Eight bounds cost, not evidence. In the ordinary case a board reading is
#: cumulative, but ADR-020 decision 4 exists because a newer reading can regress.
#: Regressions are derived from rows already stored by earlier runs; on the first
#: run, an older reading outside this window can still be omitted. That limit is
#: published rather than described as harmless.
#:
#: Truncation is reported rather than inferred — see
#: :attr:`SourceOutcome.board_scan_truncated`.
BOARD_SCAN_LIMIT = 8


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
    #: Captures for this league that are page snapshots rather than RPC bodies.
    #:
    #: These are invisible to ``artifacts_examined`` by construction: a snapshot
    #: is stored under the *page* URL, not ``/fxpa/req``, so the league
    #: pre-filter skips it. Without this counter the status screen reports
    #: "scanned 200, examined 0" for a bridge that is in fact capturing this
    #: draft continuously — and the owner reads that as "the userscript is
    #: broken" and goes looking in the wrong place. The userscript's README is
    #: explicit that ``rendered-view`` "is never normalized or presented as the
    #: JSON response the userscript could not observe"; this is the backend
    #: saying the same thing back, on the screen, at the moment it costs money.
    #:
    #: A non-zero value here alongside ``artifacts_examined == 0`` means the
    #: bridge is carrying rendered HTML rather than an RPC body. ``boards_read``
    #: says whether the board recogniser could turn that HTML into evidence.
    snapshots_for_this_league: int = 0
    #: Page snapshots of this league that parsed as a draft board.
    #:
    #: Kept apart from ``artifacts_examined``, which counts RPC bodies and
    #: keeps that meaning, because the two answer different questions and the
    #: remedies for a zero differ. ``examined 0, boards_read 12`` is the state
    #: ADR-020 was written for and is **healthy**: Fantrax serves the draft room
    #: from its service worker, no RPC body is observable, and the picks are
    #: coming off the rendered page. ``examined 0, boards_read 0`` with
    #: ``snapshots_for_this_league`` non-zero is the state the service-worker
    #: note describes, and is not.
    boards_read: int = 0
    #: Why a page snapshot of this league did not become a board reading, by
    #: reason and count.
    #:
    #: Non-empty is not automatically bad — a snapshot of the league home is
    #: ``board_refused:no_board_element`` and that is the right answer. It turns
    #: bad when it is the *only* thing here, because then the owner is looking at
    #: a draft room that this feed cannot read, and the reason names whether
    #: Fantrax renamed the markup or the capture was cut mid-grid.
    board_refusals: dict[str, int] = field(default_factory=dict)
    #: True when board snapshots were dropped by :data:`BOARD_SCAN_LIMIT`.
    #: Published for the same reason as ``scan_truncated``: a bounded scan that
    #: does not say it was bounded is indistinguishable from a complete one.
    #: Previously stored readings still participate in regression detection,
    #: but an older reading outside the first ingest's window can be omitted.
    board_scan_truncated: bool = False
    #: Instants stored with a field dropped because their ``kind`` forbids it —
    #: a price on a snake pick, ordinals on an auction sale. Non-zero is a hint
    #: that the draft's snapshotted format disagrees with what the source
    #: publishes, which is worth seeing before it becomes a wrong board.
    coerced_to_kind: int = 0
    #: The names of the dropped fields, deduplicated across every artifact this
    #: source contributed. Read this before reacting to
    #: :attr:`every_instant_coerced` — the count cannot distinguish an auction's
    #: ordinals being discarded, which is the expected shape, from every price
    #: being discarded on a draft recorded as a snake, which is not.
    fields_dropped: tuple[str, ...] = ()
    #: Instants the database refused. Zero is the expected value; a non-zero one
    #: means a recognised record could not be represented, and is published
    #: rather than raised so the rest of the run still lands.
    observations_rejected: int = 0
    #: Artifacts that were examined and rejected outright, by reason.
    rejected: dict[str, int] = field(default_factory=dict)
    instants_recognised: int = 0
    observations_written: int = 0
    #: Rows this run wrote that record a **refusal** rather than a pick — a
    #: record whose player identity this module could not read, stored so the
    #: status endpoint can say the board is short of one. They are included in
    #: ``observations_written`` and deliberately excluded from
    #: ``instants_recognised``, so the two numbers differ by exactly the
    #: ``player_external_id_unreadable`` occurrences in ``unrecognised`` for
    #: newly-seen artifacts. Never applied, never reconciled, never counted as
    #: the source having produced a reading.
    observations_skipped: int = 0
    observations_already_present: int = 0
    unrecognised: tuple[UnrecognisedShape, ...] = ()
    #: True when the scan hit :data:`BRIDGE_SCAN_LIMIT` and older artifacts
    #: were therefore not looked at.
    scan_truncated: bool = False
    notes: tuple[str, ...] = ()

    @property
    def every_instant_coerced(self) -> bool:
        """Whether *every* recognised instant had a field stripped by its kind.

        **This measures a rate. It does not identify a cause, and an earlier
        version of it claimed to.** That version was called
        ``format_snapshot_suspect`` and its docstring said a total coercion rate
        was the signature of our own format snapshot being wrong — an auction
        recorded as a snake, every price stripped, the board quietly showing a
        priceless auction. Two readings falsify that as a *cause*:

        * **It fires on correct configurations.** For the official source in a
          correctly-recorded auction, ``parse_draft_picks`` fills the ordinals
          and the amount from the same row as a matter of course, so every pick
          carries both and every pick is coerced — permanently ``True`` for a
          league whose format record is right, with nothing lost. A snake keeper
          league whose board rows carry a salary column does the same on the
          bridge path.
        * **On the bridge path it cannot fire in the case it was named for.**
          An auction log read under a snake snapshot carries prices and no
          ordinals, so ``record_missing_draft_coordinate`` refuses the whole
          list before a single instant exists — and this property requires
          ``instants_recognised > 0``.

        **That second bullet is true of the bridge path only, and a review
        found it here asserted for both.** :func:`recognise_official_draft_picks
        <hoops_gm.draft.feed.recognise.recognise_official_draft_picks>` applies
        no coordinate rule at all, so on ``OFFICIAL_HTTP`` the named case *is*
        reachable: it yields instants with every price gone and this property
        ``True``. The previous wording — "not an error at all", "do not treat
        this as evidence the board is lying" — therefore told the owner to
        ignore the one published signal that catches a wrong format snapshot on
        the only source that could show it.

        So read the rate together with :attr:`fields_dropped`, which names the
        direction of the loss:

        * ``"amount"`` dropped on a draft recorded as a **snake** means every
          pick carried a price. A real snake has none to carry —
          ``parse_draft_picks`` reads ``auction_amount`` only from ``amount``,
          ``bid`` or ``salary`` — so this is either the named case or a keeper
          roster being read as a draft, and both want a human before draft
          night. It does not say which; it says look.
        * Ordinals dropped on a draft recorded as an **auction** are the
          expected shape and mean nothing is wrong.

        Not evidence on its own, and not nothing either. The direction is in
        :attr:`fields_dropped`.
        """
        return self.instants_recognised > 0 and self.coerced_to_kind == self.instants_recognised


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
    from ``fantasy_teams.fantrax_team_id`` for the seats *this draft* declared.
    RPC recognition refuses when that set is empty; rendered-board recognition
    does not need it because it publishes source columns without attribution.
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
    stored_skip_reason: str | None = None,
) -> tuple[int, int, int, int]:
    """Write recognised instants as observations.

    Returns ``(written, already_present, rejected, skipped)``. ``skipped`` is
    the subset of ``written`` that records a refusal rather than a pick, and is
    returned separately rather than recomputed by the caller so that the number
    published and the rows written come from one pass.

    Idempotent on ``(transport, artifact_key, locator)`` — checked in Python
    against a set read once, *and* backed by the unique constraint. The set
    alone would be a race and the constraint alone would abort the transaction
    on Postgres, so both are here: the set makes the ordinary re-ingest cheap
    and the constraint makes the guarantee real.

    **Each row is written inside its own savepoint.** Not defensive
    decoration: this table carries a CHECK tying ``kind`` to the fields it
    permits, and an independent review found two ordinary payload shapes that
    violated it. Those specific shapes are now conformed in the recogniser, but
    the class of failure is the point — a single unexpected record must not
    abort the flush and take every *other* observation of the run down with it,
    returning 500 to the one screen the owner is relying on mid-draft. A bad
    row is skipped and counted; the run continues.
    """
    written = 0
    already = 0
    rejected_rows = 0
    skipped_rows = 0
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
            source_seat=instant.source_seat,
            source_seat_label=instant.source_seat_label,
            participant_id=participants.get(instant.team_external_id or ""),
            player_label=instant.player_label,
            player_external_id=instant.player_external_id,
            overall_pick=instant.overall_pick,
            round_number=instant.round_number,
            pick_in_round=instant.pick_in_round,
            amount=instant.amount,
            # Set at *write* time, not by the apply pass. The recogniser
            # already knows this record can never become a pick, and deferring
            # it would leave the row pending in between -- an application
            # candidate, which is exactly what ``blocked_reason`` would have
            # made it and why that route was rejected.
            skipped_reason=instant.skipped_reason or stored_skip_reason,
        )
        try:
            with session.begin_nested():
                session.add(row)
                session.flush()
        except IntegrityError:
            logger.warning(
                "draft_feed.observation_rejected",
                extra={
                    "draft_id": draft.id,
                    "transport": provenance.transport.value,
                    "locator": provenance.locator,
                },
            )
            rejected_rows += 1
            continue
        written += 1
        if instant.skipped_reason is not None or stored_skip_reason is not None:
            skipped_rows += 1
    return written, already, rejected_rows, skipped_rows


def _record_board_attempt(
    session: Session,
    draft: Draft,
    result: RecognitionResult,
    *,
    contact_at: datetime,
    bridge_payload_id: int,
) -> None:
    """Persist board contact and each unique successful content reading.

    A reading gets its own row because an empty board has no pick observations.
    Repeated content advances contact but creates no reading and does not move
    the latest-content pointer; that preserves ADR-020's documented
    exact-content undo blind spot rather than pretending a duplicate key is new
    evidence.
    """
    state = session.get(DraftSourceBoardState, draft.id)
    if state is None:
        state = DraftSourceBoardState(
            draft_id=draft.id,
            latest_bridge_payload_id=bridge_payload_id,
            recogniser=BOARD_RECOGNISER,
            contact_at=contact_at,
        )
        session.add(state)
        session.flush()
    latest_attempt = bridge_payload_id >= state.latest_bridge_payload_id
    if latest_attempt:
        state.latest_bridge_payload_id = bridge_payload_id
        state.contact_at = contact_at
    if result.rejected is not None:
        if latest_attempt:
            state.refusal_reason = result.rejected
        return

    board = result.source_board
    if board is None:  # pragma: no cover - recogniser contract
        if latest_attempt:
            state.refusal_reason = "board_metadata_missing"
        return
    if latest_attempt:
        state.refusal_reason = None

    existing_reading = session.scalar(
        select(DraftSourceBoardReading).where(
            DraftSourceBoardReading.draft_id == draft.id,
            DraftSourceBoardReading.artifact_key == board.artifact_key,
        )
    )
    if existing_reading is not None:
        if latest_attempt and state.artifact_key == board.artifact_key:
            # Same current content, newly observed. Mutable labels and board
            # freshness may advance without manufacturing another reading.
            state.recogniser = board.recogniser
            state.board_observed_at = board.observed_at
            state.layout = board.layout
            state.seat_count = board.seat_count
            state.round_count = board.round_count
            state.picks_made = board.picks_made
            state.seat_labels = list(board.seat_labels)
        return

    occupied_slots = sorted(
        (
            {
                "source_seat": instant.source_seat,
                "round_number": instant.round_number,
                "pick_in_round": instant.pick_in_round,
                "player_label": instant.player_label,
                "player_external_id": instant.player_external_id,
            }
            for instant in result.instants
        ),
        key=lambda slot: (
            int(slot["source_seat"] or 0),
            int(slot["round_number"] or 0),
            int(slot["pick_in_round"] or 0),
        ),
    )
    if len(occupied_slots) != board.picks_made:  # pragma: no cover - recogniser contract
        raise ValueError("source board pick summary does not match picks_made")

    reading = DraftSourceBoardReading(
        draft_id=draft.id,
        bridge_payload_id=bridge_payload_id,
        artifact_key=board.artifact_key,
        recogniser=board.recogniser,
        observed_at=board.observed_at,
        layout=board.layout,
        seat_count=board.seat_count,
        round_count=board.round_count,
        picks_made=board.picks_made,
        seat_labels=list(board.seat_labels),
        occupied_slots=occupied_slots,
    )
    try:
        with session.begin_nested():
            session.add(reading)
            session.flush()
    except IntegrityError:
        # A concurrent ingest may have won the unique (draft, artifact) race.
        # Any other constraint failure is not a duplicate and must stay loud.
        if (
            session.scalar(
                select(DraftSourceBoardReading.id).where(
                    DraftSourceBoardReading.draft_id == draft.id,
                    DraftSourceBoardReading.artifact_key == board.artifact_key,
                )
            )
            is None
        ):
            raise
        return

    if latest_attempt:
        state.artifact_key = board.artifact_key
        state.recogniser = board.recogniser
        state.board_observed_at = board.observed_at
        state.layout = board.layout
        state.seat_count = board.seat_count
        state.round_count = board.round_count
        state.picks_made = board.picks_made
        state.seat_labels = list(board.seat_labels)


def _lock_board_scope(session: Session, draft: Draft) -> None:
    """Serialize one draft's board ingestion before its singleton exists."""
    lock_refresh_scope(
        session,
        artifact_type=RefreshArtifactType.SOURCE,
        artifact_key=f"draft-source-board:{draft.id}",
        season=draft.league.season,
    )


def _tally(counter: dict[str, int], reason: str) -> None:
    counter[reason] = counter.get(reason, 0) + 1


def ingest_bridge(
    session: Session,
    draft: Draft,
    context: RecognitionContext,
    *,
    scan_limit: int = BRIDGE_SCAN_LIMIT,
    board_scan_limit: int = BOARD_SCAN_LIMIT,
) -> SourceOutcome:
    """Read stored captures for this draft's league and store what they claim.

    Two readers on one transport, which is ADR-020 decision 1 in code:
    ``recognise_bridge_payload`` for an RPC body and
    ``recognise_board_snapshot`` for a rendered board. Both produce
    ``BRIDGE_CAPTURE`` instants — they arrive down the same pipe and calling
    them two transports would let the DOM board and a future ``/fxpa/req``
    capture witness each other, from the same browser, the same page and the
    same script. They are told apart by ``provenance.recogniser``.
    """
    rows = list(
        session.execute(
            select(BridgePayload)
            .order_by(BridgePayload.created_at.desc(), BridgePayload.id.desc())
            .limit(scan_limit)
        )
        .scalars()
        .all()
    )
    # A state row cannot lock its own first insertion. The independent scope
    # serializes both creation and update through commit on SQLite and Postgres.
    # It is taken after the bounded capture read so an older request that was
    # delayed here can still be identified by payload id and refused permission
    # to move the singleton backwards.
    if any(
        row.source in SNAPSHOT_CAPTURE_SOURCES
        and league_id_in_page_url(row.request_url) == context.fantrax_league_id
        for row in rows
    ):
        _lock_board_scope(session, draft)
    # Selected newest-first so ``scan_limit`` keeps the *recent* window, then
    # walked oldest-first so observations are written in publication order.
    #
    # Those are two different requirements and writing in scan order served
    # only the first. Observation ``id`` is the tie-break both identity
    # supersession and the newest-per-transport collapse fall back on when two
    # captures share an ``observed_at`` -- which production SQLite's
    # ``CURRENT_TIMESTAMP`` produces without any fixture help, because two
    # captures a fraction of a second apart round to the same second. Written
    # in scan order, the *newest* payload got the *lowest* observation id, so
    # the tie-break elected the stale reading and called the correction
    # superseded.
    #
    # Driven: publication order ``k1`` ("The Joker", t1, $50) then ``k2``
    # ("Nikola Jokic", t2, $10) put The Joker on seat one at $50 -- wrong buyer
    # and wrong price -- with the true reading blocked as
    # ``identity_superseded``, which on the status screen reads exactly like a
    # correction being handled properly.
    #
    # This is the house rule about self-describing fields applied to ordering:
    # a timestamp that cannot separate two events is not an ordering, and the
    # tie-break underneath it has to be something independently true. Arrival
    # order is that, but only if it is actually recorded in arrival order.
    rows.reverse()
    participants = _participant_by_external_id(session, draft)
    draft_format = draft_service.format_from_snapshot(draft)
    existing = _existing_keys(session, draft)

    rejected: dict[str, int] = {}
    unrecognised: list[UnrecognisedShape] = []
    recognised = 0
    written = 0
    already = 0
    examined = 0
    snapshots = 0
    coerced = 0
    dropped_names: set[str] = set()
    rejected_rows = 0
    sale_instants = 0
    skipped_rows = 0
    boards_read = 0
    board_refusals: dict[str, int] = {}
    board_notes: list[str] = []
    board_rows: list[BridgePayload] = []

    for row in rows:
        # Cheap pre-filter on the URL, which carries the league id. Skipping
        # here rather than counting it as a rejection keeps the rejection
        # tallies about *draft* traffic instead of drowning them in every other
        # capture the bridge has ever stored.
        if league_id_in(row.request_url) != context.fantrax_league_id:
            # ...but one class of skip is not noise. A page snapshot of this
            # league is stored under the page URL, so it lands here rather than
            # in the rejection tallies, and the owner sees a zero with no cause
            # attached to it. Count it separately. This reads two recorded
            # facts — the capture's own ``source`` label and the league id in
            # its path — and asserts nothing about the snapshot's contents.
            if (
                row.source in SNAPSHOT_CAPTURE_SOURCES
                and league_id_in_page_url(row.request_url) == context.fantrax_league_id
            ):
                snapshots += 1
                board_rows.append(row)
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
        coerced += result.coerced_to_kind
        dropped_names.update(result.fields_dropped)
        sale_instants += sum(
            1
            for instant in result.instants
            if instant.kind is InstantKind.SALE and instant.skipped_reason is None
        )

        stored, seen, refused, unreadable_rows = _store(
            session,
            draft,
            result,
            participants=participants,
            existing=existing,
            bridge_payload_ids={row.dedupe_key: row.id},
        )
        written += stored
        already += seen
        rejected_rows += refused
        skipped_rows += unreadable_rows

    # The board pass runs second and over its own, much smaller window. Kept
    # oldest-first within that window for the same reason the whole scan is:
    # observation ``id`` is the tie-break every ordering falls back on when two
    # captures share a second, and writing the newest board first would elect
    # the stale reading.
    board_scan_truncated = len(board_rows) > board_scan_limit
    for row in board_rows[-board_scan_limit:] if board_scan_limit else []:
        result = recognise_board_snapshot(
            url=row.request_url,
            html=row.body_raw,
            received_at=row.created_at,
            captured_at=row.captured_at,
            context=context,
            draft_format=draft_format,
        )
        _record_board_attempt(
            session,
            draft,
            result,
            contact_at=row.created_at,
            bridge_payload_id=row.id,
        )
        if result.rejected is not None:
            # Deliberately **not** merged into ``rejected``, which is documented
            # as artifacts examined on the RPC path. A snapshot of the league
            # home refusing with ``no_board_element`` is the correct answer and
            # would read there as a draft payload we could not understand.
            _tally(board_refusals, result.rejected)
            continue
        boards_read += 1
        recognised += result.recognised_count
        unrecognised.extend(result.unrecognised)
        for note in result.notes:
            if note not in board_notes:
                board_notes.append(note)

        stored, seen, refused, unreadable_rows = _store(
            session,
            draft,
            result,
            participants=participants,
            existing=existing,
            # Keyed by the board digest, not the capture's ``dedupe_key``, so
            # this link is to whichever capture first showed this board. A later
            # snapshot of the same board writes no rows and the link is not
            # rewritten — the row points at bytes that really did contain it.
            bridge_payload_ids={
                instant.provenance.artifact_key: row.id for instant in result.instants
            },
            # A source column has no established participant binding. Keep the
            # evidence visible and permanently outside the application queue.
            stored_skip_reason="source_board_evidence_only",
        )
        written += stored
        already += seen
        rejected_rows += refused
        skipped_rows += unreadable_rows

    notes: list[str] = [
        f"Scanned the {scan_limit} newest captures; older ones were not examined."
        if len(rows) >= scan_limit
        else "Scanned every stored capture."
    ]
    notes.extend(board_notes)
    if board_scan_truncated:
        notes.append(
            f"{len(board_rows)} page snapshot(s) for this league were stored and the "
            f"newest {board_scan_limit} were parsed. Previously stored board readings "
            f"still participate in regression detection, but an older reading outside "
            f"this first-ingest window may hold evidence the parsed window does not."
        )
    if snapshots and examined == 0 and boards_read == 0:
        notes.append(
            f"{snapshots} capture(s) for this league are page snapshots rather than "
            "RPC bodies, no rendered board parsed, and no RPC capture for this league "
            "was found. Fantrax's service worker is the known reason page script may "
            "see no RPC body; inspect board_refusals separately for why the rendered "
            "HTML produced no board evidence."
        )
    elif snapshots and boards_read == 0:
        notes.append(
            f"{snapshots} capture(s) for this league are page snapshots and none of "
            "them parsed as a draft board; only their RPC siblings were read."
        )
    elif snapshots:
        notes.append(
            f"{boards_read} of {snapshots} page snapshot(s) for this league parsed as "
            "a draft board. The markup carries no Fantrax team id; each column is "
            "stored as source_seat and is not attributed to DraftParticipant."
        )
    if sale_instants:
        # Non-heuristic by construction: conditioned only on a fact already
        # established — this scan produced at least one SALE instant. It
        # classifies no record and changes no outcome. Deliberately not a
        # per-record guess: a priced keeper row and an auction sale row are the
        # same tuple, so a rule that marked *some* of them would be inventing a
        # classifier, which is the failure mode this package exists to avoid.
        #
        # **A sale instant is itself proof of an auction context**, so no
        # draft-type test belongs here. :func:`~hoops_gm.draft.feed.recognise
        # ._kind_for` derives one kind per scan from ``context.draft_type``, and
        # a priced payload read under a snake context is *coerced* to
        # ``SELECTION`` with its amounts dropped rather than admitted as a sale.
        # An earlier version of this line also tested ``draft_type is AUCTION``.
        # A mutation removing that clause **survived the whole suite**, which is
        # what exposed it: not an untested branch but an unreachable one, and no
        # test could have defended it because no input distinguishes the two
        # readings. Redundancy removed rather than chased with a test.
        #
        # It exists at all because a review asked where this limit was visible
        # to someone not reading the suite, and the honest answer was "nowhere":
        # ``fields_dropped`` is empty for these rows, ``coerced_to_kind`` is
        # zero, and no unrecognised shape is produced, so every other channel
        # reports a clean read. On draft night the owner sees the board.
        notes.append(
            f"{sale_instants} sale(s) were read from bridge captures. In an auction "
            "league a priced keeper row and a sale row are the same shape — "
            "'salary' is an amount alias and is also the defining field of a "
            "keeper roster — so this feed cannot tell them apart, and some of "
            "these may not be draft sales. No real Fantrax auction payload has "
            "ever been seen, so how often this happens is unknown."
        )

    return SourceOutcome(
        transport=SourceTransport.BRIDGE_CAPTURE,
        artifacts_scanned=len(rows),
        artifacts_examined=examined,
        snapshots_for_this_league=snapshots,
        boards_read=boards_read,
        board_refusals=board_refusals,
        board_scan_truncated=board_scan_truncated,
        coerced_to_kind=coerced,
        fields_dropped=tuple(sorted(dropped_names)),
        observations_rejected=rejected_rows,
        rejected=rejected,
        instants_recognised=recognised,
        observations_written=written,
        observations_skipped=skipped_rows,
        observations_already_present=already,
        unrecognised=_summarise(unrecognised),
        scan_truncated=len(rows) >= scan_limit,
        notes=tuple(notes),
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
    written, already, refused, unreadable_rows = _store(
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
        coerced_to_kind=result.coerced_to_kind,
        fields_dropped=result.fields_dropped,
        observations_rejected=refused,
        rejected={result.rejected: 1} if result.rejected else {},
        instants_recognised=result.recognised_count,
        observations_written=written,
        observations_skipped=unreadable_rows,
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
    """Rehydrate a stored row into the pure type.

    ``skipped_reason`` is deliberately **not** carried across. On the row that
    column is broader than :attr:`ObservedInstant.skipped_reason`: the
    recogniser writes an identity refusal there at ingest, and
    :func:`apply_observations` writes ``already_in_log`` and
    ``duplicate_within_run`` there afterwards. Those two are genuine readings
    of a pick, and a rehydrated instant claiming otherwise would be a lie in
    the one direction that matters — reconciliation reads these.
    """
    return ObservedInstant(
        kind=InstantKind(row.kind.value),
        provenance=InstantProvenance(
            transport=SourceTransport(row.transport.value),
            artifact_key=row.artifact_key,
            recogniser=row.recogniser,
            received_at=row.observed_at,
            source_claimed_at=row.source_claimed_at,
            locator=row.locator,
            sequence=row.id,
        ),
        team_external_id=row.team_external_id,
        source_seat=row.source_seat,
        source_seat_label=row.source_seat_label,
        player_label=row.player_label,
        player_external_id=row.player_external_id,
        overall_pick=row.overall_pick,
        round_number=row.round_number,
        pick_in_round=row.pick_in_round,
        amount=row.amount,
    )


def names_a_player(row: DraftFeedObservation) -> bool:
    """Whether this row is a reading *about* somebody.

    The negative case is a record the recogniser stored precisely because it
    could not identify it — an unreadable ``player_external_id``, or a source
    row naming nobody at all. Migration ``0021`` permits a row naming no player
    only when it carries a ``skipped_reason``, so this predicate and "the
    recogniser refused this record's identity" pick out the same rows, enforced
    by the database rather than by a list of reason strings kept in step by
    hand.

    Used to keep such rows out of reconciliation and out of freshness. The
    freshness half is the one that bites: :func:`freshness_of` lets
    ``contact_at`` suppress ``silent`` **only for a transport that has produced
    at least one instant**, so counting a record we could not read would let a
    feed that has read no picks report itself not silent — the exact false
    all-clear that rule exists to prevent, arriving through the row added to
    make a silence visible.
    """
    return row.player_label is not None or row.player_external_id is not None


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


@dataclass(frozen=True, slots=True)
class _Recorded:
    """What the board already asserts about one player.

    ``participant_id`` and ``price`` are here because a pending observation
    naming this player has to be checked *against* them, not merely counted as
    a second sighting of the same name. The sequence alone cannot answer "does
    this reading agree with what we already show?".
    """

    sequence: int
    participant_id: int
    #: Named ``price`` on the board and ``amount`` on an observation. The two
    #: are compared, so the mapping is spelled out in ``_BOARD_FACTS`` rather
    #: than left to whoever next reads both dataclasses.
    price: Decimal | None


def _held_keys(state: Any) -> dict[str, _Recorded]:
    """Player keys already on the board, mapped to what the board says about
    them. Used to recognise a republished pick as one we already have — and to
    notice when a "republished" pick is not the same pick at all."""
    held: dict[str, _Recorded] = {}
    for participant in state.participants:
        for holding in participant.holdings:
            held[holding.player_key] = _Recorded(
                sequence=holding.event_sequence,
                participant_id=participant.participant.id,
                price=holding.price,
            )
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


@dataclass(frozen=True, slots=True)
class _Admitted:
    """The fields an admitted row supplies, with their optionality discharged.

    Returned instead of ``None`` so that the field which was *checked* and the
    field which is *used* are the same object. The first version returned a
    reason-or-``None`` and left callers re-reading ``row.participant_id``,
    which type-checks only by accident: a later edit reading a fourth field
    the admission rule never examined would have been accepted silently. mypy
    named all five of those reads, which is how this shape got written.
    """

    participant_id: int
    player_label: str


def _admit(row: DraftFeedObservation) -> _Admitted | str:
    """The values this row supplies, or why it can never be applied.

    One rule, two callers: the apply loop skips on it, and the contradiction
    pre-pass ignores the same rows so that the two passes consider exactly the
    same population. Written as a function rather than inlined twice because
    an admission rule implemented in two places that were meant to agree is
    the single defect this package's reviews have found most often — rounds
    four, seven and eight were all that shape at different depths.

    **The two team refusals are separate because their causes are.**
    ``no_seat_for_team_external_id`` means the source named a team and we have
    no seat linked to it, which the owner fixes by linking the Fantrax team.
    ``source_named_no_team`` means the reading names nobody to attribute the
    pick to at all, which he cannot fix, and which is the ordinary state of
    every rendered-board observation: the Fantrax draft board carries no team id
    in its markup — ``draftTeamId`` and ``cellTeamId`` are console vocabulary —
    so the column ordinal is the only seat identity it offers and this unit is
    not entitled to map that onto one of our participants. Reporting both under
    one string would send the owner to relink a team that is already linked.
    """
    if row.participant_id is None:
        return (
            "source_named_no_team"
            if row.team_external_id is None
            else "no_seat_for_team_external_id"
        )
    if not row.player_label:
        # The log requires a verbatim label for anything naming a player, and
        # inventing one from an external id would be a resolution this package
        # is not entitled to make.
        return "no_player_label"
    return _Admitted(participant_id=row.participant_id, player_label=row.player_label)


#: The facts about a pick that an observation supplies and the board then
#: asserts, as ``(observation attribute, recorded attribute)``.
#:
#: These, and only these, are what a second reading has to agree about before
#: it can be filed as corroboration. The set is deliberately narrower than
#: :data:`hoops_gm.draft.feed.reconcile._COMPARED_FIELDS`, which compares
#: everything two readings say: the coordinate fields order the apply pass but
#: are never passed to the draft service, so a coordinate disagreement cannot
#: make the board assert anything false about *this* holding, and blocking on
#: it would strand real picks over a difference the owner can never see.
#:
#: ``test_the_blocking_facts_are_exactly_what_the_board_is_told`` derives this
#: set from the call site rather than trusting this comment, so passing a new
#: ``row.`` field into ``record_pick``/``record_sale`` is red until someone
#: classifies it.
_BOARD_FACTS: Final[tuple[tuple[str, str], ...]] = (
    ("participant_id", "participant_id"),
    ("amount", "price"),
)


def _identity_conflicts(
    pending: list[DraftFeedObservation],
    applied: list[DraftFeedObservation],
) -> dict[str, str]:
    """Player keys where the payload's two identity signals disagree.

    Excludes: one player reaching the board twice, and two players collapsing
    into one, because the apply pass keys on the normalised label while the
    payload also carries the source's own player id.

    The apply pass groups by ``normalize_key(player_label)``. Reconciliation
    keys by ``player_external_id`` first and falls back to the label -- see
    :func:`~hoops_gm.draft.feed.observations.matching_key`. **Two rules for the
    same question is the defect this unit's reviews have found at four
    successive depths**, and this is that generator again: which readings are
    about the same player.

    Both directions are wrong and neither is loud:

    * **One id, two labels.** Driven: two captures naming ``p123`` as
      ``"Nikola Jokic"`` and ``"The Joker"``, *agreeing* on seat and price,
      both applied. The board showed one player twice and the seat's
      ``remaining_budget`` read ``100.00`` where ``150.00`` was correct -- one
      player, bought once, **debited twice**, with nothing blocked, nothing
      skipped and nothing disagreeing. Every subsequent bid the owner reasons
      about is then computed from a bank that is wrong by the price of a
      player.
    * **One label, two ids.** ``normalize_key`` erases digits and generational
      suffixes, so ``"Gary Payton II"`` keys to ``"gary payton"``. Two distinct
      players whose names differ only by a suffix therefore group together, the
      first applies and the second is filed ``duplicate_within_run``: **a pick
      that happened, reported as nothing.**

    Refusing rather than merging is the load-bearing choice. Grouping the two
    readings on a shared id would be a cross-source identity claim this package
    is not entitled to make -- ADR-008 and R23 are about precisely that
    laundering -- and taking the transitive closure of "shares an id or shares
    a label" would let two genuinely different ids become one through an
    intermediate label. A conflict is a finding, so both keys are blocked and
    the reason names the signals, which is the same trade made everywhere else
    here: visibly absent beats confidently wrong.

    Absence is not disagreement: a row carrying no external id cannot conflict
    with one that does, which is :func:`values_disagree`'s rule applied to
    identity rather than restated.

    **A source correcting itself is not a source disagreeing with itself.**
    That rule is stated six lines into :func:`_contradicted_keys` and was not
    applied here, so a bridge capture that renamed ``p123`` from ``"The Joker"``
    to ``"Nikola Jokic"`` blocked the player permanently: driven, the correct
    reading republished twice more and ``applied`` stayed ``0``, ``holdings``
    stayed empty and ``pending_count`` climbed to 3, while reconciliation
    correctly exposed only the newest reading. **The owner has no manual
    fallback**, so a player the feed can never record is a real loss and not
    merely a visible one.

    The collapse is deliberately asymmetric, and the asymmetry is the argument:

    * **One id, changing labels** collapses to the newest reading per transport.
      An id is a stable identifier and a label is display text, so a later
      reading of the same id supersedes the earlier one. The stale *key* is then
      blocked too -- otherwise it applies as a second player, which is the
      double-debit this function exists to stop, arriving through the fix for
      it.
    * **One label, several ids** does not collapse at all. Two distinct ids are
      evidence of two distinct players, so superseding one would silently drop a
      pick -- round ten's mirror defect returning wearing the fix's clothes.

    Within a single artifact the one-id-many-labels case cannot arise: list
    admission already refuses a list carrying one id twice
    (``duplicate_player_in_list``). So that direction only ever fires across
    artifacts, where it is a correction, or across transports, where it is a
    genuine conflict and still blocks.

    **Everything above reasons only about rows still pending, and the pending
    set is not the board.** On draft night ingest-and-apply runs between picks,
    so the reading a later capture corrects has usually *already applied*. Both
    checks above then see a single reading, find nothing to disagree with, and
    the defect they exist to stop happens one apply-cycle later instead:

    * **One id, two labels, applied apart.** Driven: ``p123`` applied as
      ``"The Joker"`` at $50, then republished as ``"Nikola Jokic"``. Both
      applied -- sequences 1 and 2 -- and the seat's ``remaining_budget`` read
      ``100.00`` where ``150.00`` was correct. ``pending_count=0``,
      ``blocked=()``, ``skipped=()``: one player drafted twice and debited
      twice, with every channel reporting a clean board.
    * **One label, two ids, applied apart.** Driven: ``p1`` applied as
      ``"Gary Payton"``, then ``p2`` -- a different player -- arriving under the
      same normalised key at the same seat and price. It was filed
      ``already_in_log``, and *nothing in this package ever clears*
      ``skipped_reason``, so that pick is gone permanently and the status screen
      calls it a duplicate. **A missing pick reported as nothing**, which is
      round ten's defect surviving the apply boundary its fix did not cross.

    So identity is read from applied rows too. The asymmetry between the two
    directions is unchanged, but the *response* differs from the pending case,
    and deliberately: a pending reading can be superseded because nothing has
    happened yet, while an applied one cannot be, because **this is the read
    path and it does not rewrite the board**. Editing a landed pick is a write,
    and a write needs the Automation gate and an independent sign-off this unit
    does not have. The pick is therefore blocked and named, leaving the owner a
    stated discrepancy he can correct in one keystroke rather than a silent one
    he has to notice.

    Rows skipped as ``already_in_log`` or ``duplicate_within_run`` count as
    applied history here: they carry ``applied_event_sequence``, so they are
    evidence that this id and this label landed together, which is exactly what
    the check needs.

    Absence still is not disagreement. An applied row with no external id
    contributes nothing, so a later reading that *does* carry one is not
    accused of conflicting with it -- the same rule as everywhere else here.
    """
    readings: list[tuple[DraftFeedObservation, str, str]] = []
    ids_by_label: dict[str, set[str]] = defaultdict(set)

    for row in pending:
        admitted = _admit(row)
        if isinstance(admitted, str):
            continue
        external_id = row.player_external_id
        if not external_id:
            continue
        key = normalize_key(admitted.player_label)
        readings.append((row, external_id, key))
        ids_by_label[key].add(external_id)

    # This ordering is defence in depth and nothing observable rests on it.
    # ``current`` becomes the publication-max of each ``(transport,
    # external_id)`` group, and the refusal below groups by that same key and
    # blocks the group whenever publication-max and arrival-max name different
    # labels. So the only inputs on which this sort key would change the answer
    # are inputs the refusal has already taken out of play. A mutation swapping
    # it back to arrival order stays green for that reason -- which is what
    # "unreachable" looks like from a test, and is not the same as "covered".
    # It is written this way so that narrowing the refusal cannot silently
    # restore delivery order as the tiebreak.
    current: dict[tuple[str, str], str] = {}
    for row, external_id, key in sorted(
        readings,
        key=lambda item: publication_order(
            item[0].source_claimed_at, item[0].observed_at, item[0].id
        ),
    ):
        current[(row.transport.value, external_id)] = key

    labels_by_id: dict[str, set[str]] = defaultdict(set)
    for (_transport, external_id), key in current.items():
        labels_by_id[external_id].add(key)

    conflicts: dict[str, str] = {}

    # Publication order and arrival order are two different claims about which
    # reading is current, and ``publication_order`` trusts a timestamp the
    # browser wrote. Where they disagree, this package does what it does
    # everywhere else: it refuses rather than picking a side. Preferring the
    # source's own clock would be trusting a self-describing field; preferring
    # ours would be the defect this ordering fix exists to remove.
    #
    # Scoped to one ``(transport, external_id)`` group, because that is the
    # unit supersession acts on. A disagreement between two *different*
    # players' readings is not a disagreement about either of them.
    grouped_by_id: dict[tuple[str, str], list[tuple[DraftFeedObservation, str]]] = defaultdict(list)
    for row, external_id, key in readings:
        grouped_by_id[(row.transport.value, external_id)].append((row, key))
    for (_transport, external_id), members in grouped_by_id.items():
        if len(members) < 2:
            continue
        by_publication = max(
            members,
            key=lambda item: publication_order(
                item[0].source_claimed_at, item[0].observed_at, item[0].id
            ),
        )[1]
        by_arrival = max(
            members,
            key=lambda item: arrival_order(item[0].observed_at, item[0].id),
        )[1]
        if by_publication == by_arrival:
            continue
        reason = f"capture_order_disputed:{external_id}:{by_arrival}|{by_publication}"
        conflicts.setdefault(by_publication, reason)
        conflicts.setdefault(by_arrival, reason)

    for external_id, keys in labels_by_id.items():
        if len(keys) < 2:
            continue
        reason = (
            f"identity_conflict:one_player_id_many_labels:{external_id}:{'|'.join(sorted(keys))}"
        )
        for key in keys:
            conflicts.setdefault(key, reason)
    for key, external_ids in ids_by_label.items():
        if len(external_ids) < 2:
            continue
        conflicts.setdefault(
            key,
            f"identity_conflict:one_label_many_player_ids:{key}:{'|'.join(sorted(external_ids))}",
        )
    for row, external_id, key in readings:
        live = current[(row.transport.value, external_id)]
        if key != live:
            conflicts.setdefault(key, f"identity_superseded:{external_id}:{key}->{live}")

    applied_key_for_id: dict[str, str] = {}
    applied_ids_for_key: dict[str, set[str]] = defaultdict(set)
    for row in applied:
        admitted = _admit(row)
        if isinstance(admitted, str):
            continue
        external_id = row.player_external_id
        if not external_id:
            continue
        landed_key = normalize_key(admitted.player_label)
        applied_key_for_id[external_id] = landed_key
        applied_ids_for_key[landed_key].add(external_id)

    for _row, external_id, key in readings:
        landed = applied_key_for_id.get(external_id)
        if landed is not None and landed != key:
            # This id is on the board under another name. Not superseded --
            # superseding would mean editing a landed pick, and this is the
            # read path.
            conflicts.setdefault(key, f"identity_already_applied:{external_id}:{landed}->{key}")
        already = applied_ids_for_key.get(key)
        if already and external_id not in already:
            # A different player already holds this normalised name. Blocking
            # keeps it out of ``already_in_log``, which is permanent.
            conflicts.setdefault(
                key,
                "identity_conflict:one_label_many_player_ids:"
                f"{key}:{'|'.join(sorted(already | {external_id}))}",
            )
    return conflicts


def _contradicted_keys(
    pending: list[DraftFeedObservation],
    held: dict[str, _Recorded],
    applied: list[DraftFeedObservation],
) -> dict[str, str]:
    """Player keys where the readings we hold do not agree about a board fact.

    Excludes: a second reading being filed as corroboration of the first while
    the two of them name different buyers or different prices.

    Two sources naming one player is the whole point of running two sources,
    but it is only corroboration if they *agree*. Where they do not, applying
    either one records a fact this package does not have, and the older
    behaviour applied whichever sorted first — which is the same error as
    preferring the newer source, wearing the opposite bias.

    A disagreement is therefore a refusal, not a resolution: nothing is
    applied for that key and the reason reaches the status screen. That leaves
    the player visibly absent from the board rather than confidently attached
    to the wrong seat, which is the trade this package makes everywhere else.

    Absence is not disagreement — a source that says nothing about the price
    has not contradicted one that does. That distinction is
    :func:`~hoops_gm.draft.feed.reconcile.values_disagree`'s, imported rather
    than restated so the two passes cannot drift.
    """
    grouped: dict[str, list[DraftFeedObservation]] = defaultdict(list)
    for row in pending:
        admitted = _admit(row)
        if isinstance(admitted, str):
            continue
        grouped[normalize_key(admitted.player_label)].append(row)

    contradicted: dict[str, str] = _identity_conflicts(pending, applied)
    for key, rows in grouped.items():
        # One reading per source, newest first. A draft board republishes the
        # whole list on every pick, so a source that corrects itself — or that
        # simply reported the same player twice — must not read as
        # disagreeing with itself. This is the same within-source collapse
        # :func:`~hoops_gm.draft.feed.reconcile._newest_per_key` makes, and for
        # the same stated reason: it is not the cross-source preference this
        # package refuses to make.
        #
        # Without it a single transient disagreement is permanent. The sources
        # agree from the next capture onwards and the pick stays blocked
        # anyway, because the stale reading is still pending and still
        # contradicts. That is the burnt-row failure ``blocked_reason`` exists
        # to avoid, arriving by a different door.
        newest: dict[str, DraftFeedObservation] = {}
        for row in sorted(
            rows,
            key=lambda item: publication_order(item.source_claimed_at, item.observed_at, item.id),
        ):
            newest[row.transport.value] = row

        readings: list[tuple[str, Any]] = [
            (f"{row.transport.value}:{row.artifact_key}", row) for row in newest.values()
        ]
        recorded = held.get(key)
        if recorded is not None:
            # The log is a reading too. A feed that disagrees with what the
            # owner already typed is exactly as much of a finding as two
            # sources disagreeing with each other, and filing it as
            # "already_in_log" reports the collision while discarding the
            # contradiction inside it.
            readings.append(("log", recorded))

        for index, (left_name, left) in enumerate(readings):
            for right_name, right in readings[index + 1 :]:
                for observation_field, recorded_field in _BOARD_FACTS:
                    left_value = getattr(
                        left,
                        observation_field if left_name != "log" else recorded_field,
                        None,
                    )
                    right_value = getattr(
                        right,
                        observation_field if right_name != "log" else recorded_field,
                        None,
                    )
                    if values_disagree(left_value, right_value):
                        contradicted.setdefault(
                            key,
                            f"sources_disagree:{observation_field}:"
                            f"{left_name}={left_value!r}:{right_name}={right_value!r}",
                        )
    return contradicted


def apply_observations(
    session: Session,
    draft: Draft,
    *,
    now: datetime | None = None,
) -> ApplyOutcome:
    """Append the log entries the stored observations imply.

    Through :mod:`hoops_gm.draft.service` only, so every derivation rule the
    tracker already enforces — turn order, roster limits, a player taken twice
    — applies unchanged to a machine-fed pick. There is no fast path here that
    a hand-recorded pick does not also take.

    **Budget is deliberately not in that list any more.** It used to be, and it
    was the worst rule to have here: ``Draft.auction_budget`` is one scalar for
    the whole draft, so a seat with a larger real bank raised
    ``draft_budget_exceeded``, and line 1295 below filed that into
    ``skipped_reason`` — which nothing in this package ever clears, and which
    ``pending`` above filters on. So the row was burned permanently: re-ingesting
    the same capture deduped against the burned row instead of retrying it, and
    the pick was gone from the board with no way back short of typing it by
    hand. See ``hoops_gm.draft.state``, "Why spending past the budget is not a
    refusal", and
    ``test_a_sale_past_the_assumed_budget_is_applied_rather_than_burned``.
    """
    stamp = now or datetime.now(UTC)
    state = draft_service.load_state(session, draft)

    observations = load_observations(session, draft)
    pending = [
        row
        for row in observations
        if row.applied_event_sequence is None and row.skipped_reason is None
    ]
    # Identity history. A row that was skipped as a duplicate still carries the
    # sequence it corroborated, so it is evidence about which id landed under
    # which name -- see :func:`_identity_conflicts`.
    applied_history = [row for row in observations if row.applied_event_sequence is not None]
    pending.sort(key=_apply_order)

    # Cleared before anything is attempted, so ``blocked_reason`` is always a
    # fact about *this* run. A sticky value would recreate, in a second field,
    # the exact defect that removing it from ``skipped_reason`` fixed.
    #
    # This clear used to carry a comment insisting it had to sit *above* the
    # closed-draft return. It does not, and a review proved it by moving it
    # below and watching all 59 tests pass: the stamp loop in that branch
    # overwrites every pending row anyway, so the two orderings are
    # indistinguishable. Above is still the right place — it keeps "clear, then
    # decide" in one reading order — but nothing depends on it, and the comment
    # that said otherwise was a guarantee no test could have held it to.
    for row in pending:
        row.blocked_reason = None

    if state.status is DraftStatus.CLOSED:
        # A closed draft with a pending backlog is the likeliest permanent halt
        # in this system, not an exotic one: the owner closes the draft at the
        # end of the night, the userscript keeps capturing, and ``ingest`` keeps
        # writing observations that can now never apply. That is exactly the
        # "stuck, or merely queued?" question ``blocked_reason`` was added to
        # answer, so it must be recorded on the rows rather than returned only
        # to whichever caller happened to trigger this run — a client that only
        # polls the status endpoint sees the backlog but never the reason.
        for row in pending:
            row.blocked_reason = "draft_closed"
        session.flush()
        return ApplyOutcome(halted="draft_closed", last_sequence=state.last_sequence)

    held = _held_keys(state)
    contradicted = _contradicted_keys(pending, held, applied_history)

    applied: list[AppliedEvent] = []
    skipped: list[tuple[int, str]] = []
    halted: str | None = None
    seen_this_run: set[str] = set()

    for row in pending:
        admitted = _admit(row)
        if isinstance(admitted, str):
            skipped.append((row.id, admitted))
            row.skipped_reason = admitted
            continue

        key = normalize_key(admitted.player_label)
        if key in contradicted:
            # Not ``skipped_reason``: nothing in this package ever clears that,
            # so a contradiction would burn every row for this player
            # permanently, and the owner resolving it by typing the pick
            # himself would still never see them leave the backlog.
            # ``blocked_reason`` is recomputed every run, so this states the
            # position now and stops stating it when it stops being true.
            row.blocked_reason = contradicted[key]
            continue
        if key in seen_this_run:
            # Two sources naming the same player in one run, agreeing on every
            # fact the board records. The first has already been appended; this
            # one is corroboration, not a second pick. Checked before ``held``
            # because ``held`` was updated by that append a moment ago and would
            # otherwise absorb this row as "already_in_log" — which is the
            # reason meaning *the owner typed it*, and conflating the two would
            # delete the corroboration signal from the status screen at the
            # moment it is worth something.
            row.applied_event_sequence = held[key].sequence
            row.applied_at = stamp
            row.skipped_reason = "duplicate_within_run"
            skipped.append((row.id, "duplicate_within_run"))
            continue
        if key in held:
            row.applied_event_sequence = held[key].sequence
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
                    participant_id=admitted.participant_id,
                    amount=row.amount,
                    player_label=admitted.player_label,
                    note=f"feed:{row.transport.value}:{row.artifact_key}",
                )
            else:
                state = draft_service.record_pick(
                    session,
                    draft,
                    participant_id=admitted.participant_id,
                    player_label=admitted.player_label,
                    note=f"feed:{row.transport.value}:{row.artifact_key}",
                )
        except DraftLogError as error:
            skipped.append((row.id, error.code))
            if error.code == "draft_pick_out_of_turn":
                # Stop rather than skip. Skipping would silently desynchronise
                # every pick after this one and the owner would find out much
                # later, which is the worst possible time.
                #
                # ``skipped_reason`` is deliberately *not* set on this branch.
                # Nothing in this package ever clears it, so setting it would
                # exclude the row from ``pending`` permanently: the owner types
                # the pick this one was waiting behind, re-runs, and the
                # observation that triggered the halt is silently gone — not
                # applied, not pending, with ``pending_count == 0`` telling the
                # screen there is nothing outstanding. Halting is supposed to
                # be the recoverable choice; burning the row is what made it a
                # skip with extra steps. A republishing bridge would usually
                # heal it under a new key, but the official source republishes
                # byte-identically and would not.
                halted = error.code
                row.blocked_reason = error.code
                break
            row.skipped_reason = f"{error.code}: {error}"
            continue

        row.applied_event_sequence = state.last_sequence
        row.applied_at = stamp
        # Re-derived from the board rather than assembled from ``row``, so that
        # what ``held`` says and what the board says cannot differ. Building a
        # ``_Recorded`` here from the values we happened to pass in would be a
        # second derivation of the same fact, and every review round on this
        # package has found a defect in exactly that shape. A draft is a few
        # hundred rows, so the cost is not worth a correctness argument.
        held = _held_keys(state)
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
    #: Reasons the last apply run stopped without consuming a still-pending row.
    #:
    #: Empty is the ordinary case. Non-empty means ``pending_count`` is a stuck
    #: backlog rather than a queued one, which the polling client cannot
    #: otherwise tell — ``halted`` is returned on the ingest response only, and a
    #: live board polls ``GET``. "Stuck" and "queued" look identical on a screen
    #: and mean opposite things at 7:14pm.
    blocked: tuple[str, ...]
    skipped: tuple[tuple[str, int], ...]
    last_sequence: int
    #: Board slots an earlier reading filled and the newest one does not.
    #:
    #: ADR-020 decision 4. Empty is the ordinary case. Non-empty means the
    #: rendered board went backwards, which is the owner's own words for the
    #: failure this whole feed exists to catch — *"it loses track of the
    #: draft"* — and nothing is retracted on the strength of it. Published on
    #: ``GET`` as well as on the ingest response because a live board polls
    #: ``GET``, and a finding that reaches only the ``POST`` caller is a finding
    #: the screen never shows.
    board_regressions: tuple[BoardRegression, ...] = ()


def _transport_contact(
    session: Session,
    context: RecognitionContext | str,
    *,
    board_is_a_source_here: bool = False,
) -> dict[SourceTransport, datetime]:
    """Proof-of-life per transport, independent of any draft instant.

    Only the bridge has any. An **RPC capture for this exact league** is
    evidence the userscript is running and reaching Fantrax's data endpoint,
    whether or not that particular reply contained a pick — and between two
    picks in a live draft it will not. This is what stops the freshness
    indicator reading ``silent`` through every ordinary deliberation and
    teaching the owner to dismiss it.

    Three things narrow what counts, and each excludes a row that is genuine
    but is not evidence of the property being claimed:

    * **The URL is re-parsed, not substring-matched.** ``request_url.contains``
      is kept only as a cheap SQL pre-filter; the authority is
      :func:`league_id_in`, which requires the path to be exactly ``/fxpa/req``
      and the ``leagueId`` parameter to equal ours. Substring matching accepted
      a neighbouring league whose id merely has ours as a prefix, and our id
      appearing in any unrelated query parameter. ``autoescape=True`` because
      an id containing ``_`` or ``%`` is otherwise a LIKE wildcard.
    * **Only RPC capture sources count, until a board has been read.** See
      below.
    * **Contact never rescues a source that has produced nothing.** That rule
      lives in :func:`freshness_of`; see the comment there.

    Together these exclude the defect that matters: *a feed that has read zero
    picks reporting itself as not silent* because some capture mentioning this
    league happened to land.

    ## Why a page snapshot counts once, and only once, a board has been read

    ADR-020 decision 3 puts board liveness on this clock, and it has to: a board
    reading is keyed on the board's content, so a four-minute deliberation
    produces snapshot after snapshot and **no new observation at all**. Judged
    on the instant clock the bridge would read ``silent`` through every
    deliberation of a draft it is capturing perfectly — the exact cry-wolf
    failure ``contact_at`` was added to remove, arriving by a new route.

    So ``board_is_a_source_here`` widens what counts, and the gate is a fact
    rather than a hope: it is true only when this draft already holds an
    explicit successful board reading, including a valid zero-pick board.
    Before that, a page snapshot is exactly the service-worker case — the
    userscript is alive and this feed can read nothing from it — and it still
    proves nothing, which is what
    ``test_proof_of_life_ignores_captures_that_are_not_proof_of_this_feed``
    pins. After it, a snapshot of this league's page is evidence that the pipe
    which *is* delivering picks is still delivering.

    **The widening is deliberately not narrowed to snapshots that parsed as a
    board, and that is a real loss of precision.** Any page snapshot of this
    league counts once the gate is open, including a snapshot of the league
    home. Narrowing it would mean either re-parsing every candidate at status
    time — 49 ms of HTML parse each, on the one endpoint a live board polls — or
    reading which snapshots produced rows, which is precisely the thing content
    keying makes impossible: an unchanged board writes no row, so the snapshots
    that matter most here are the ones with nothing pointing at them. What keeps
    this safe is not this function's precision but :func:`freshness_of`'s
    asymmetry, which lets contact suppress ``silent`` only for a transport that
    has already produced an instant.

    For a contact time to be wrong in the remaining direction -- a dead bridge
    reported live -- a ``bridge_payloads`` row would have to appear with a
    recent ``created_at`` while the userscript is not running. Nothing else
    writes that table; the only path is ``POST /bridge/payloads``.

    The official source deliberately gets nothing. Its poll happens inside
    ``ingest_official`` and is not recorded anywhere, and inventing a contact
    time from the status request would be proof of nothing but that the status
    endpoint was called. It reports ``contact_is_known=False`` and falls back
    to the instant clock, which is honest about what we know.
    """
    if isinstance(context, str):
        return {}
    sources = set(RPC_CAPTURE_SOURCES)
    if board_is_a_source_here:
        sources |= set(SNAPSHOT_CAPTURE_SOURCES)
    candidates = session.execute(
        select(BridgePayload.created_at, BridgePayload.request_url, BridgePayload.source)
        .where(
            BridgePayload.source.in_(sources),
            BridgePayload.request_url.contains(context.fantrax_league_id, autoescape=True),
        )
        .order_by(BridgePayload.created_at.desc())
        .limit(_CONTACT_SCAN_LIMIT)
    ).all()
    for created_at, request_url, source in candidates:
        if source in SNAPSHOT_CAPTURE_SOURCES:
            if league_id_in_page_url(request_url) == context.fantrax_league_id:
                return {SourceTransport.BRIDGE_CAPTURE: created_at}
            continue
        if league_id_in(request_url) == context.fantrax_league_id:
            return {SourceTransport.BRIDGE_CAPTURE: created_at}
    return {}


@dataclass(frozen=True, slots=True)
class BoardRegression:
    """A board slot that an earlier reading filled and the newest one does not.

    ADR-020 decision 4: **store the reading, publish this, retract nothing.**
    Refusing a regressed board would discard evidence of the exact failure the
    owner named — *"it loses track of the draft"* — and clearing the pick
    automatically would let a repaint delete a real selection.

    ``last_seen_artifact_key`` is the board digest of the newest reading that
    still held this slot, so the raw capture behind it is findable.
    """

    source_seat: int
    round_number: int
    pick_in_round: int
    player_label: str | None
    last_seen_artifact_key: str


def load_board_readings(session: Session, draft: Draft) -> list[DraftSourceBoardReading]:
    """Load explicit successful board readings in first-seen order."""
    return list(
        session.execute(
            select(DraftSourceBoardReading)
            .where(DraftSourceBoardReading.draft_id == draft.id)
            .order_by(DraftSourceBoardReading.bridge_payload_id)
        )
        .scalars()
        .all()
    )


def board_regressions(
    readings: list[DraftSourceBoardReading],
) -> tuple[BoardRegression, ...]:
    """Slots the board has lost, derived from explicit successful readings.

    One derivation, two callers — :func:`ingest_bridge`'s caller reports it on
    the ``POST`` response and :func:`feed_status` publishes it on ``GET`` —
    following :func:`_admit` rather than computing the same question twice. Two
    passes meant to agree about a payload is the defect every review round on
    this package has found.

    A reading is a parent row even when it contains zero picks. Its
    ``occupied_slots`` JSON is a compact source-coordinate summary, not a set of
    placeholder observations. Anything filled in an earlier reading and absent
    from the newest is a regression. Union rather than pairwise, so a slot lost
    two readings ago and still missing is still reported.

    **What this cannot see, stated because it is not obvious.** Content keying
    means a board that goes *back to a state already stored* writes no new
    reading row, so an undo that lands exactly on a previous board is invisible.
    ADR-020 already records that a repaint, an undo and a capture cut look
    identical at the DOM; this is that limit in its most concrete form. The case
    it does catch is the one with evidence behind it: a board that has lost a
    slot no earlier reading was missing.
    """
    if len(readings) < 2:
        return ()

    contents: list[dict[tuple[int, int, int], str | None]] = []
    for reading in readings:
        slots: dict[tuple[int, int, int], str | None] = {}
        for raw in reading.occupied_slots:
            source_seat = raw.get("source_seat")
            round_number = raw.get("round_number")
            pick_in_round = raw.get("pick_in_round")
            if not (
                isinstance(source_seat, int)
                and isinstance(round_number, int)
                and isinstance(pick_in_round, int)
            ):  # pragma: no cover - rows are written only by _record_board_attempt
                continue
            player_label = raw.get("player_label")
            slots[(source_seat, round_number, pick_in_round)] = (
                player_label if isinstance(player_label, str) else None
            )
        contents.append(slots)

    newest = contents[-1]
    lost: dict[tuple[int, int, int], BoardRegression] = {}
    for reading, slots in zip(readings[:-1], contents[:-1], strict=True):
        for slot, label in slots.items():
            if slot in newest:
                continue
            # Later earlier-readings overwrite, so the recorded key is the
            # newest reading that still held the slot rather than the first.
            lost[slot] = BoardRegression(
                source_seat=slot[0],
                round_number=slot[1],
                pick_in_round=slot[2],
                player_label=label,
                last_seen_artifact_key=reading.artifact_key,
            )
    return tuple(lost[slot] for slot in sorted(lost))


@dataclass(frozen=True, slots=True)
class SourceBoardPick:
    """One pick exactly as the rendered source board located it."""

    source_seat: int
    round_number: int
    pick_in_round: int
    overall_pick: int
    player_label: str | None
    player_external_id: str | None


@dataclass(frozen=True, slots=True)
class SourceBoardColumn:
    """One rendered source column; its label is mutable display evidence."""

    source_seat: int
    mutable_label: str | None
    picks: tuple[SourceBoardPick, ...]


@dataclass(frozen=True, slots=True)
class SourceBoardSnapshot:
    artifact_key: str
    recogniser: str
    observed_at: datetime
    layout: str
    seat_count: int
    round_count: int
    picks_made: int
    columns: tuple[SourceBoardColumn, ...]


@dataclass(frozen=True, slots=True)
class SourceBoardEvidence:
    """Read-only source-board evidence, explicitly separate from draft state."""

    draft_id: int
    as_of: datetime
    status: Literal["available", "refused", "no_reading"]
    refusal_reason: str | None
    contact_at: datetime | None
    contact_age_seconds: float | None
    board: SourceBoardSnapshot | None
    board_age_seconds: float | None
    regressions: tuple[BoardRegression, ...]
    caveats: tuple[str, ...]


_SOURCE_BOARD_CAVEATS = (
    "source_seat is a rendered column ordinal, not DraftParticipant.team_slot or identity",
    "seat labels are mutable display evidence and are never matched to participants",
    "an exact-content undo reuses an existing artifact key and cannot appear as a new regression",
    "evidence is from one football snake draft; NBA and auction board support is unestablished",
)


def source_board_evidence(
    session: Session,
    draft: Draft,
    *,
    now: datetime | None = None,
) -> SourceBoardEvidence:
    """Return the latest source board without changing draft state or events."""
    stamp = now or datetime.now(UTC)
    state = session.get(DraftSourceBoardState, draft.id)
    rows = load_observations(session, draft)
    readings = load_board_readings(session, draft)
    regressions = board_regressions(readings)
    if state is None:
        return SourceBoardEvidence(
            draft_id=draft.id,
            as_of=stamp,
            status="no_reading",
            refusal_reason=None,
            contact_at=None,
            contact_age_seconds=None,
            board=None,
            board_age_seconds=None,
            regressions=regressions,
            caveats=_SOURCE_BOARD_CAVEATS,
        )

    snapshot: SourceBoardSnapshot | None = None
    board_age: float | None = None
    if (
        state.artifact_key is not None
        and state.board_observed_at is not None
        and state.layout is not None
        and state.seat_count is not None
        and state.round_count is not None
        and state.picks_made is not None
    ):
        artifact_rows = [
            row
            for row in rows
            if row.recogniser == BOARD_RECOGNISER and row.artifact_key == state.artifact_key
        ]
        by_seat: dict[int, list[SourceBoardPick]] = defaultdict(list)
        for row in artifact_rows:
            if (
                row.source_seat is None
                or row.round_number is None
                or row.pick_in_round is None
                or row.overall_pick is None
            ):
                continue
            by_seat[row.source_seat].append(
                SourceBoardPick(
                    source_seat=row.source_seat,
                    round_number=row.round_number,
                    pick_in_round=row.pick_in_round,
                    overall_pick=row.overall_pick,
                    player_label=row.player_label,
                    player_external_id=row.player_external_id,
                )
            )
        labels = state.seat_labels or []
        columns = tuple(
            SourceBoardColumn(
                source_seat=seat,
                mutable_label=labels[seat - 1] if seat <= len(labels) else None,
                picks=tuple(sorted(by_seat.get(seat, []), key=lambda pick: pick.round_number)),
            )
            for seat in range(1, state.seat_count + 1)
        )
        snapshot = SourceBoardSnapshot(
            artifact_key=state.artifact_key,
            recogniser=state.recogniser,
            observed_at=state.board_observed_at,
            layout=state.layout,
            seat_count=state.seat_count,
            round_count=state.round_count,
            picks_made=state.picks_made,
            columns=columns,
        )
        board_age = max(0.0, (stamp - state.board_observed_at).total_seconds())

    return SourceBoardEvidence(
        draft_id=draft.id,
        as_of=stamp,
        status="refused" if state.refusal_reason is not None else "available",
        refusal_reason=state.refusal_reason,
        contact_at=state.contact_at,
        contact_age_seconds=max(0.0, (stamp - state.contact_at).total_seconds()),
        board=snapshot,
        board_age_seconds=board_age,
        regressions=regressions,
        caveats=_SOURCE_BOARD_CAVEATS,
    )


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
    board_readings = load_board_readings(session, draft)
    # A row that names nobody is a recorded refusal, not a reading — see
    # :func:`names_a_player`. It is still counted in ``observation_count`` and
    # still reported by name in ``skipped`` below; what it must not do is make
    # a source look like it has produced a pick.
    instants = [_to_instant(row) for row in rows if names_a_player(row)]

    by_transport: dict[SourceTransport, list[ObservedInstant]] = {
        SourceTransport.BRIDGE_CAPTURE: [],
        SourceTransport.OFFICIAL_HTTP: [],
    }
    for instant in instants:
        by_transport[instant.provenance.transport].append(instant)

    contact_at = _transport_contact(
        session,
        context,
        # A fact, not a setting: this draft already holds a successful reading
        # the board recogniser produced, so the page-snapshot pipe is one this
        # feed can read here. See :func:`_transport_contact`.
        board_is_a_source_here=bool(board_readings),
    )
    if instants:
        report = reconcile(
            by_transport[SourceTransport.BRIDGE_CAPTURE],
            by_transport[SourceTransport.OFFICIAL_HTTP],
            now=stamp,
            silence_threshold=silence_threshold,
            contact_at=contact_at,
        )
        freshness = report.freshness
    else:
        report = None
        freshness = tuple(
            freshness_of(
                [],
                transport=transport,
                now=stamp,
                silence_threshold=silence_threshold,
                contact_at=contact_at.get(transport),
            )
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
    # ``draft_closed`` is a claim about the draft's *current* status, so it is
    # filtered against the status rather than trusted as a stamp. The stamp is
    # written by ``apply_observations``, which only a caller passing
    # ``apply=true`` reaches; a screen polling this endpoint never runs it and
    # so can never clear it. A close is voidable (``draft.service``: "Void that
    # event to reopen it"), and without this filter a reopened draft reported
    # the one string that means "permanently halted" on every pending row, for
    # ever. That false reading was introduced by the fix that added the stamp —
    # eliminating one stale reason by manufacturing another.
    blocked = tuple(
        sorted(
            {
                row.blocked_reason
                for row in rows
                if row.blocked_reason
                and not (
                    row.blocked_reason == "draft_closed" and state.status is not DraftStatus.CLOSED
                )
            }
        ),
    )

    return FeedStatus(
        draft_id=draft.id,
        context_unavailable=context if isinstance(context, str) else None,
        as_of=stamp,
        freshness=freshness,
        reconciliation=report,
        observation_count=len(rows),
        applied_count=applied,
        pending_count=pending,
        blocked=blocked,
        skipped=tuple(sorted(skipped.items())),
        last_sequence=state.last_sequence,
        board_regressions=board_regressions(board_readings),
    )


def instants_for(rows: list[DraftFeedObservation]) -> list[ObservedInstant]:
    """Rehydrate stored rows into the pure type, keeping provenance intact."""
    return [_to_instant(row) for row in rows]


def observation_key(row: DraftFeedObservation) -> tuple[str, str] | None:
    """The reconciliation key for a stored row, via the same function the pure
    path uses — so a stored row and a live reading can never key differently."""
    return matching_key(_to_instant(row))
