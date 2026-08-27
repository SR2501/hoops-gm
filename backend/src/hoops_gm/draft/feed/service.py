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

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
    arrival_order,
    matching_key,
    publication_order,
)
from hoops_gm.draft.feed.recognise import (
    RPC_CAPTURE_SOURCES,
    SNAPSHOT_CAPTURE_SOURCES,
    RecognitionContext,
    league_id_in,
    league_id_in_page_url,
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
    #: Captures for this league that are page snapshots rather than RPC bodies,
    #: and so cannot be read as picks however well the recogniser works.
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
    #: draft room's traffic is being served by Fantrax's service worker
    #: (``fx-sw.js``) and never reaching page script. That is a known
    #: possibility, not a bug in this unit, and it has a different remedy from
    #: every other zero on this screen.
    snapshots_for_this_league: int = 0
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
) -> tuple[int, int, int]:
    """Write recognised instants as observations.

    Returns ``(written, already_present, rejected)``.

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
    return written, already, rejected_rows


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
        sale_instants += sum(1 for instant in result.instants if instant.kind is InstantKind.SALE)
        stored, seen, refused = _store(
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

    notes: list[str] = [
        f"Scanned the {scan_limit} newest captures; older ones were not examined."
        if len(rows) >= scan_limit
        else "Scanned every stored capture."
    ]
    if snapshots and examined == 0:
        notes.append(
            f"{snapshots} capture(s) for this league are page snapshots rather than "
            "RPC bodies, and no RPC capture for this league was found. Rendered HTML "
            "is not the JSON the recogniser reads, so this feed can see the draft "
            "room being captured and still read nothing from it. The usual cause is "
            "Fantrax serving the draft room from its service worker, where page "
            "script cannot observe the response."
        )
    elif snapshots:
        notes.append(
            f"{snapshots} capture(s) for this league are page snapshots and were not "
            "read; only RPC bodies are."
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
        coerced_to_kind=coerced,
        fields_dropped=tuple(sorted(dropped_names)),
        observations_rejected=rejected_rows,
        rejected=rejected,
        instants_recognised=recognised,
        observations_written=written,
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
    written, already, refused = _store(
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
            sequence=row.id,
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
    """
    if row.participant_id is None:
        return "no_seat_for_team_external_id"
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
    tracker already enforces — turn order, roster limits, budget, a player
    taken twice — applies unchanged to a machine-fed pick. There is no
    fast path here that a hand-recorded pick does not also take.
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


def _transport_contact(
    session: Session,
    context: RecognitionContext | str,
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
    * **Only RPC capture sources count.** A ``rendered-view`` HTML snapshot is
      stored under the *page* URL and proves the userscript is alive, but not
      that the data endpoint is being read.
    * **Contact never rescues a source that has produced nothing.** That rule
      lives in :func:`freshness_of`; see the comment there.

    Together these exclude the defect that matters: *a feed that has read zero
    picks reporting itself as not silent* because some capture mentioning this
    league happened to land.

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
    candidates = session.execute(
        select(BridgePayload.created_at, BridgePayload.request_url)
        .where(
            BridgePayload.source.in_(RPC_CAPTURE_SOURCES),
            BridgePayload.request_url.contains(context.fantrax_league_id, autoescape=True),
        )
        .order_by(BridgePayload.created_at.desc())
        .limit(_CONTACT_SCAN_LIMIT)
    ).all()
    for created_at, request_url in candidates:
        if league_id_in(request_url) == context.fantrax_league_id:
            return {SourceTransport.BRIDGE_CAPTURE: created_at}
    return {}


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

    contact_at = _transport_contact(session, context)
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
    )


def instants_for(rows: list[DraftFeedObservation]) -> list[ObservedInstant]:
    """Rehydrate stored rows into the pure type, keeping provenance intact."""
    return [_to_instant(row) for row in rows]


def observation_key(row: DraftFeedObservation) -> tuple[str, str] | None:
    """The reconciliation key for a stored row, via the same function the pure
    path uses — so a stored row and a live reading can never key differently."""
    return matching_key(_to_instant(row))
