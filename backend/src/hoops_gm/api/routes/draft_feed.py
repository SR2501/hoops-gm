"""The feed's contract: what the board heard, when, and how much to trust it.

Two endpoints, and the split matters.

``GET /drafts/{id}/feed`` reports. It is safe to poll, takes no lock, and is
the screen's answer to the question a live draft makes urgent: *is this board
current, or am I looking at a photograph?* Every figure it publishes carries
the clock it was computed on and the provenance it came from.

``POST /drafts/{id}/feed/ingest`` reads the sources and, optionally, appends
what they imply to the log.

**Neither one sends Fantrax anything but a GET.** ``routes/drafts.py``'s module
docstring is the authority for the distinction and it applies unchanged here:
the Automation gate governs the path that acts on the owner's live account, and
reading a public endpoint and writing to our own SQLite file is not that path.
If a change here ever wants to *do* something in a Fantrax draft room — make a
pick, place a bid, nominate — it belongs in the bridge behind ``safety``
sign-off and not in this file.

**Freshness is a value in the response, not an assumption behind it.** Each
source reports ``last_seen_at``, ``age_seconds`` and ``silent``, all computed
on the server's clock against the moment the claim reached us. A source that
has never spoken reports ``last_seen_at: null`` and ``silent: true`` rather
than a comfortable zero. This is the specific lesson the demo taught by serving
a stale build behind ``200 OK`` for hours: a screen that cannot tell current
from stale will show stale, confidently, and a five-minute-old board during a
live auction is worse than one that admits it is blind.

**Agreement between the sources is reported as what it is.** The response
carries ``witnessed_by_two_transports`` and never a bare ``agreed`` flag, plus
``independence``, which says whether the two sides were genuinely two reads.
The caveats are in the payload rather than only in this docstring, because a
limit that stops at the source file does not reach the person looking at the
screen.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from hoops_gm.api.deps import SessionDep
from hoops_gm.api.schemas import ErrorResponse
from hoops_gm.api.security import require_loopback_host
from hoops_gm.db.models.draft import Draft
from hoops_gm.draft import service as draft_service
from hoops_gm.draft.feed import service as feed_service
from hoops_gm.draft.feed.observations import ObservedInstant, UnrecognisedShape
from hoops_gm.draft.feed.reconcile import ReconciliationReport, SourceFreshness

router = APIRouter(prefix="/drafts", tags=["drafts"])


def _error(status_code: int, code: str, detail: str) -> HTTPException:
    """The app's error contract. ``X-Bridge-Error`` is read off the exception by
    ``app.py``'s handler and is not a response header — see ``routes/drafts.py``."""
    return HTTPException(status_code=status_code, detail=detail, headers={"X-Bridge-Error": code})


def _require_draft(session: Any, draft_id: int) -> Draft:
    draft = draft_service.load_draft(session, draft_id)
    if draft is None:
        raise _error(404, "draft_not_found", f"no draft {draft_id}")
    return draft


class FreshnessOut(BaseModel):
    """How long since one source last said anything, on the server's clock."""

    model_config = ConfigDict(extra="forbid")

    transport: str
    #: ``null`` when this source has never produced a reading. Paired with
    #: ``age_seconds``: the two are null together, so there is no reading of
    #: this object in which a silent source looks current.
    last_seen_at: datetime | None
    age_seconds: float | None
    instant_count: int
    #: Whether this source is quiet. Judged against ``contact_at`` when
    #: ``contact_is_known``, otherwise against ``last_seen_at``. The
    #: distinction matters on draft night: a bridge that has captured within
    #: the threshold but seen no new pick is waiting through a deliberation,
    #: not broken, and reporting those two identically is how an indicator
    #: becomes noise before the evening it is needed.
    silent: bool
    #: What "quiet" meant, so a screen states the threshold it was judged
    #: against instead of hard-coding a second one that can disagree.
    silence_threshold_seconds: float
    #: The newest timestamp the *source* claimed, for display only. Never used
    #: to compute ``age_seconds``.
    source_claimed_at: datetime | None = None
    #: Source claim minus our receipt, in seconds. A large value means one of
    #: the two clocks is wrong; nothing here acts on it.
    claim_skew_seconds: float | None = None
    #: When this transport last proved it was alive, regardless of whether it
    #: said anything new. For the bridge this is the newest stored capture for
    #: this league. ``null`` with ``contact_is_known=false`` means no such
    #: evidence exists — which is what the official source always reports,
    #: because its poll happens during ingest and is not recorded.
    contact_at: datetime | None = None
    contact_age_seconds: float | None = None
    contact_is_known: bool = False


class IndependenceOut(BaseModel):
    """Whether the two compared sides were two reads or one read counted twice."""

    model_config = ConfigDict(extra="forbid")

    independent: bool
    reason: str
    left_transports: list[str]
    right_transports: list[str]
    shared_artifacts: list[str]
    shared_transports: list[str]


class MatchOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_label: str | None
    key: str
    bridge_artifact: str
    official_artifact: str


class DisagreementOut(BaseModel):
    """One field, two readings, no verdict.

    There is deliberately no ``preferred`` or ``resolved_value``. A
    disagreement between the only two views we have of the draft is
    information about our own reading, and resolving it by rule would delete
    that information at the moment it is most useful.
    """

    model_config = ConfigDict(extra="forbid")

    player_label: str | None
    field_name: str
    bridge_value: str | None
    official_value: str | None
    bridge_artifact: str
    official_artifact: str


class UnrecognisedOut(BaseModel):
    """A block that reached us and that no recogniser could read.

    The top-level key names, not the payload — key names are what tells the
    next person where to look, and are the thing a five-minute fix needs.
    """

    model_config = ConfigDict(extra="forbid")

    keys: list[str]
    occurrences: int
    example_locator: str
    reason: str


class ReconciliationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    independence: IndependenceOut
    #: Named for what it measures. **Not** a count of verified picks: both
    #: sources read Fantrax, so this is consistency between two views of one
    #: upstream, not confirmation that the upstream is right.
    witnessed_by_two_transports: int
    agreements: list[MatchOut]
    #: Matching readings that could not be shown to be two reads. Same content
    #: as ``agreements``, different name, because the name is the claim.
    unwitnessed_matches: list[MatchOut]
    disagreements: list[DisagreementOut]
    only_bridge: list[str]
    only_official: list[str]
    caveats: list[str]


class FeedStatusResponse(BaseModel):
    """Everything the screen needs to say how much it can be trusted."""

    model_config = ConfigDict(extra="forbid")

    draft_id: int
    #: Our clock when this was computed, so a client can age the *status*, not
    #: just the feed.
    as_of: datetime
    #: ``null`` when the feed can run. A string when this draft cannot be fed
    #: at all — most often ``seats_not_linked``, which is every mock against
    #: strangers and is a refusal rather than a failure.
    context_unavailable: str | None
    freshness: list[FreshnessOut]
    reconciliation: ReconciliationOut | None
    observation_count: int
    applied_count: int
    pending_count: int
    #: Reasons the last apply run stopped without consuming a still-pending row.
    #:
    #: Empty is the ordinary case. Non-empty means ``pending_count`` is stuck,
    #: not queued. A live board polls this endpoint, and ``halted`` is returned
    #: only on the ingest response — so without this a feed that has permanently
    #: stopped applying is indistinguishable here from one with an item waiting
    #: for the next run.
    blocked: list[str]
    skipped: dict[str, int]
    #: The draft log's version token, the same one ``GET /drafts/{id}``
    #: publishes, so a screen can tell whether the board it holds is the board
    #: this status describes.
    last_sequence: int


class SourceOutcomeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transport: str
    #: ``null`` when the source ran. A string when it could not run at all.
    #: Reported rather than raised: one source being down must not cost the
    #: owner the other one.
    unavailable: str | None
    #: Offered by the source, before filtering. Reported next to
    #: ``artifacts_examined`` so a zero can be read: many scanned with none
    #: examined means the captures are for a different league, none scanned
    #: means the bridge is not sending anything at all.
    artifacts_scanned: int
    artifacts_examined: int
    #: Captures for this league that are page snapshots, not RPC bodies.
    #:
    #: A non-zero value with ``artifacts_examined == 0`` is the one reading of
    #: "nothing was examined" that is not about the userscript being broken or
    #: the league id being wrong: the bridge is capturing this draft, but only
    #: as rendered HTML, which is not what the recogniser reads. It has a
    #: different remedy from every other zero on this screen, so it gets its own
    #: number rather than being inferred from the absence of one.
    snapshots_for_this_league: int
    rejected: dict[str, int]
    instants_recognised: int
    #: Instants stored with a field nulled because their ``kind`` forbids it: a
    #: price on a snake pick, ordinals on an auction sale. Storing the record
    #: with the impossible field dropped is preferred to refusing it, because
    #: the seat and the player are the parts a board needs.
    #:
    #: A non-zero value has two readings and this count does not choose between
    #: them — see ``format_snapshot_suspect``, which does.
    coerced_to_kind: int
    #: True when *every* recognised instant was coerced, which is the signature
    #: of our own format record being wrong rather than of an unexpected extra
    #: field. The dangerous reading: the league is an auction, we recorded it as
    #: snake, and the board is showing an auction with no prices. Sporadic
    #: coercion is benign; total coercion is a configuration error.
    format_snapshot_suspect: bool
    #: Recognised instants the database refused. Expected to be zero. Non-zero
    #: means a record we thought we understood could not be represented, and it
    #: is counted rather than raised so one bad row does not cost the run.
    observations_rejected: int
    observations_written: int
    observations_already_present: int
    unrecognised: list[UnrecognisedOut]
    scan_truncated: bool
    notes: list[str]


class AppliedEventOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: int
    sequence: int
    player_label: str | None
    kind: str


class AppliedOut(BaseModel):
    """The outcome of an apply run, present only when one was asked for.

    A nullable object rather than fields on the response, because "apply was
    not requested" and "apply ran and appended nothing" are different facts and
    a flat ``applied: []`` renders them identically. On draft night the second
    means the feed has stopped keeping up and the first means nobody asked it
    to, and a screen cannot tell them apart from an empty list.
    """

    model_config = ConfigDict(extra="forbid")

    events: list[AppliedEventOut]
    skipped: list[str]
    #: Set when application stopped early rather than finishing. An ordered
    #: draft that meets an out-of-turn pick halts here, because skipping it
    #: would desynchronise every pick after it.
    halted: str | None


class IngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: int
    as_of: datetime
    context_unavailable: str | None
    sources: list[SourceOutcomeOut]
    #: ``null`` when the request did not ask to apply.
    applied: AppliedOut | None
    last_sequence: int
    status: FeedStatusResponse


class IngestRequest(BaseModel):
    """What one ingest run should do."""

    model_config = ConfigDict(extra="forbid")

    #: When false (the default) the run stores what the sources claim and
    #: appends nothing. Reading is always safe; appending is the part worth
    #: asking for explicitly.
    apply: bool = False
    #: How many stored captures to examine, newest first. Bounded because an
    #: unbounded scan of ``bridge_payloads`` is not a thing to discover during
    #: a live draft.
    scan_limit: int = Field(default=feed_service.BRIDGE_SCAN_LIMIT, ge=1, le=5000)


def _freshness_out(freshness: SourceFreshness) -> FreshnessOut:
    return FreshnessOut(
        transport=freshness.transport.value,
        last_seen_at=freshness.last_seen_at,
        age_seconds=freshness.age_seconds,
        instant_count=freshness.instant_count,
        silent=freshness.silent,
        silence_threshold_seconds=freshness.silence_threshold_seconds,
        source_claimed_at=freshness.source_claimed_at,
        claim_skew_seconds=freshness.claim_skew_seconds,
        contact_at=freshness.contact_at,
        contact_age_seconds=freshness.contact_age_seconds,
        contact_is_known=freshness.contact_is_known,
    )


def _scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _unrecognised_out(shape: UnrecognisedShape) -> UnrecognisedOut:
    return UnrecognisedOut(
        keys=list(shape.keys),
        occurrences=shape.occurrences,
        example_locator=shape.example_locator,
        reason=shape.reason,
    )


def _reconciliation_out(report: ReconciliationReport) -> ReconciliationOut:
    return ReconciliationOut(
        independence=IndependenceOut(
            independent=report.independence.independent,
            reason=report.independence.reason,
            left_transports=list(report.independence.left_transports),
            right_transports=list(report.independence.right_transports),
            shared_artifacts=list(report.independence.shared_artifacts),
            shared_transports=list(report.independence.shared_transports),
        ),
        witnessed_by_two_transports=report.witnessed_by_two_transports,
        agreements=[
            MatchOut(
                player_label=match.player_label,
                key=f"{match.key[0]}={match.key[1]}",
                bridge_artifact=match.left.provenance.artifact_key,
                official_artifact=match.right.provenance.artifact_key,
            )
            for match in report.agreements
        ],
        unwitnessed_matches=[
            MatchOut(
                player_label=match.player_label,
                key=f"{match.key[0]}={match.key[1]}",
                bridge_artifact=match.left.provenance.artifact_key,
                official_artifact=match.right.provenance.artifact_key,
            )
            for match in report.unwitnessed_matches
        ],
        disagreements=[
            DisagreementOut(
                player_label=item.player_label,
                field_name=item.field_name,
                bridge_value=_scalar(item.left_value),
                official_value=_scalar(item.right_value),
                bridge_artifact=item.left_provenance_key,
                official_artifact=item.right_provenance_key,
            )
            for item in report.disagreements
        ],
        only_bridge=[_one_sided_label(instant) for instant in report.only_left],
        only_official=[_one_sided_label(instant) for instant in report.only_right],
        caveats=list(report.caveats),
    )


def _one_sided_label(instant: ObservedInstant) -> str:
    """How a one-sided reading is named on the screen.

    Never returns an empty string and never drops the row. The previous form
    filtered on ``if instant.player_label``, so an instant keyed on
    ``player_external_id`` alone — a supported state, since ``matching_key``
    prefers the external id and a record naming only ``playerId`` is accepted —
    disappeared from a list whose entire purpose is making one-sided readings
    visible. ``only_left`` would be non-empty while ``only_bridge`` rendered as
    ``[]``, so "only one source saw this pick" read as "nothing to report".
    """
    if instant.player_label:
        return instant.player_label
    if instant.player_external_id:
        return f"player id {instant.player_external_id}"
    return f"unnamed instant at {instant.provenance.locator}"


def _status_out(status: feed_service.FeedStatus) -> FeedStatusResponse:
    return FeedStatusResponse(
        draft_id=status.draft_id,
        as_of=status.as_of,
        context_unavailable=status.context_unavailable,
        freshness=[_freshness_out(item) for item in status.freshness],
        reconciliation=(
            _reconciliation_out(status.reconciliation)
            if status.reconciliation is not None
            else None
        ),
        observation_count=status.observation_count,
        applied_count=status.applied_count,
        pending_count=status.pending_count,
        blocked=list(status.blocked),
        skipped=dict(status.skipped),
        last_sequence=status.last_sequence,
    )


def _draft_pick_source(request: Request) -> feed_service.DraftPickSource | None:
    """The official client, if this app has one.

    Read off ``app.state`` and defaulted to ``None`` rather than constructed
    here. Constructing a network client inside a request handler would make
    every test of this endpoint either hit Fantrax or monkeypatch a module
    global, and would make "the corroborating source is not configured"
    indistinguishable from "it failed". ``None`` is reported as
    ``unavailable: official_client_not_configured``, which is a different
    sentence on the screen.
    """
    client = getattr(request.app.state, "fantrax_official_client", None)
    if client is None:
        return None
    return client  # type: ignore[no-any-return]


@router.get(
    "/{draft_id}/feed",
    response_model=FeedStatusResponse,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="How fresh each feed source is, and where the two disagree",
)
def get_feed_status(draft_id: int, session: SessionDep, request: Request) -> FeedStatusResponse:
    """Report only. Takes no lock and appends nothing.

    Safe to poll at whatever interval the screen wants. The one thing this must
    never do is answer without saying how old its answer is, which is why
    ``as_of`` and every source's ``age_seconds`` are required fields rather
    than optional ones.
    """
    require_loopback_host(
        request,
        error_code="drafts_local_only",
        detail="Draft feed status is only served to the local machine.",
    )
    draft = _require_draft(session, draft_id)
    return _status_out(feed_service.feed_status(session, draft))


@router.post(
    "/{draft_id}/feed/ingest",
    response_model=IngestResponse,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Read both feed sources, and optionally append what they imply",
)
def ingest_feed(
    draft_id: int,
    payload: IngestRequest,
    session: SessionDep,
    request: Request,
) -> IngestResponse:
    """Read the bridge and the official API; append only if asked.

    A local write to our own database. Nothing is sent to Fantrax beyond a GET
    to its public read API — see the module docstring.

    The whole feed status comes back alongside the outcome, for the same reason
    ``POST /drafts/{id}/events`` returns the whole state: otherwise a screen
    holds an outcome it knows landed and a freshness figure that predates it,
    and has to either re-poll immediately or guess at the difference.
    """
    require_loopback_host(
        request,
        error_code="drafts_local_only",
        detail="Ingesting the draft feed is a local-only operation.",
    )
    draft = _require_draft(session, draft_id)

    outcome = feed_service.ingest(
        session,
        draft,
        client=_draft_pick_source(request),
        scan_limit=payload.scan_limit,
    )
    applied: feed_service.ApplyOutcome | None = None
    if payload.apply and outcome.context_unavailable is None:
        applied = feed_service.apply_observations(session, draft)

    status = feed_service.feed_status(session, draft)
    return IngestResponse(
        draft_id=draft.id,
        as_of=status.as_of,
        context_unavailable=outcome.context_unavailable,
        sources=[
            SourceOutcomeOut(
                transport=source.transport.value,
                unavailable=source.unavailable,
                artifacts_scanned=source.artifacts_scanned,
                artifacts_examined=source.artifacts_examined,
                snapshots_for_this_league=source.snapshots_for_this_league,
                rejected=dict(source.rejected),
                instants_recognised=source.instants_recognised,
                coerced_to_kind=source.coerced_to_kind,
                format_snapshot_suspect=source.format_snapshot_suspect,
                observations_rejected=source.observations_rejected,
                observations_written=source.observations_written,
                observations_already_present=source.observations_already_present,
                unrecognised=[_unrecognised_out(shape) for shape in source.unrecognised],
                scan_truncated=source.scan_truncated,
                notes=list(source.notes),
            )
            for source in outcome.sources
        ],
        applied=(
            None
            if applied is None
            else AppliedOut(
                events=[
                    AppliedEventOut(
                        observation_id=event.observation_id,
                        sequence=event.sequence,
                        player_label=event.player_label,
                        kind=event.kind.value,
                    )
                    for event in applied.applied
                ],
                skipped=[
                    f"{observation_id}: {reason}" for observation_id, reason in applied.skipped
                ],
                halted=applied.halted,
            )
        ),
        last_sequence=status.last_sequence,
        status=_status_out(status),
    )
