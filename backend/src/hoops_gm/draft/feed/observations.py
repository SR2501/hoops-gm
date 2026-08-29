"""What one source says happened, and where exactly that claim came from.

Pure dataclasses. No database, no HTTP, no clock — the clock is passed in, so a
freshness figure is never quietly read off the machine that is computing it.

The one idea worth stating twice: **an instant carries its provenance, not its
source's provenance.** A per-source label ("this came from the bridge") is
enough to draw a badge and not enough to establish that two agreeing readings
are two readings. :class:`InstantProvenance` names the exact artifact — the
bytes for a captured response, the parsed board for a rendered one, and ADR-020
records why those differ — so :mod:`hoops_gm.draft.feed.reconcile` can refuse to
call one read two.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from hoops_gm.db.models.enums import DraftFeedInstantKind as InstantKind
from hoops_gm.db.models.enums import DraftFeedTransport as SourceTransport
from hoops_gm.identity.names import normalize_key

#: The two enums live in :mod:`hoops_gm.db.models.enums` and are re-exported
#: here under the names this package reads better with. One definition, so the
#: value stored in ``draft_feed_observations.transport`` and the value the
#: independence guard compares are the same object rather than two lists that
#: can drift — the drift being invisible until the day a stored row stops
#: matching a live reading.
__all__ = [
    "InstantKind",
    "InstantProvenance",
    "ObservedInstant",
    "RecognitionResult",
    "SourceBoardReading",
    "SourceTransport",
    "UnrecognisedShape",
    "matching_key",
]


@dataclass(frozen=True, slots=True)
class InstantProvenance:
    """Which read produced one instant.

    ``artifact_key`` identifies the **artifact**, not the row and not the
    request. For an RPC bridge capture that is the userscript's ``dedupe_key``,
    which is ``METHOD:hash(url):hash(body)`` — so the same response captured
    twice, by two different capture paths, into two different
    ``bridge_payloads`` rows, still produces one key. Keying on the row id
    instead would make a duplicate look like corroboration. For an official
    read it is the SHA-256 of the raw response body, which the client already
    computes.

    **For two of the three readers the artifact is the bytes. For the third it
    is not, and this paragraph exists because the previous one said "the bytes"
    flatly.** ADR-020 keys a rendered board reading on a digest of the *parsed
    board* — sorted ``(round, pick_in_round, seat, player_external_id or
    player_name)`` with the seat count and the round count, and deliberately
    not ``captured_at``, ``truncated`` or a parser version. Two snapshots of an
    unchanged board differ in their HTML on every capture (timers, focus
    classes, Angular's own churn) and are one reading of one board, so
    byte-keying would store every pick once per snapshot and make
    ``SourceFreshness.instant_count`` a count of snapshots rather than of
    picks.

    **The stronger-sounding reason for this is false and is named here so
    nobody reaches for it later.** Byte-keying would *not* fool the
    independence guard: :func:`~hoops_gm.draft.feed.reconcile._independence`
    refuses two board readings either way, because they share a transport —
    and note that it tests ``shared_artifacts`` *first* and ``shared_transports``
    second, so which of the two refusals is reported depends on the keying while
    the verdict does not. The cost byte-keying carries is volume, not a false
    witness.

    An ADR that contradicts a docstring and leaves the docstring standing has
    produced a false guarantee, which is the shape this repository keeps
    finding; the same correction is made on
    :class:`~hoops_gm.db.models.draft_feed.DraftFeedObservation`, which carried
    the claim a second time.

    ``received_at`` is **our** clock: the moment the row appeared in our
    database, or the moment our HTTP client returned. It is the only value any
    freshness figure is allowed to be computed from.

    ``source_claimed_at`` is whatever the source said about itself. It is
    carried so a screen can show it and so a disagreement with ``received_at``
    is visible, and it is never subtracted from anything. AGENTS.md records why:
    ``gameEt`` in the NBA box score carries a ``Z`` and is Eastern, five hours
    off its own sibling. Timezone-correct parsing of a field that lies about its
    timezone is still wrong.
    """

    transport: SourceTransport
    artifact_key: str
    #: Which recogniser produced this instant. Published so "why did the board
    #: think that" has an answer that is a name rather than a guess.
    recogniser: str
    received_at: datetime
    source_claimed_at: datetime | None = None
    #: Where inside the artifact this came from — e.g. ``responses[1].data``
    #: and the index within the list. A path, not a copy of the payload.
    locator: str = ""
    #: Storage order, when this instant was read back from a row. ``None`` for
    #: an instant that has not been stored.
    #:
    #: Carried because ordering two readings needs a tie-break and a timestamp
    #: is not one: two captures inside a second share ``received_at`` under
    #: production SQLite. Without it every consumer working on instants —
    #: ``_newest_per_key``, ``freshness_of`` — silently kept whichever tied
    #: reading it happened to see first, while the apply path, which works on
    #: rows and *has* the id, kept the last. **Two passes answering "which
    #: reading is current" with different answers**, which is the drift this
    #: package exists to catch.
    sequence: int | None = None


@dataclass(frozen=True, slots=True)
class ObservedInstant:
    """One claim, by one source, that one thing happened in the draft.

    Every field except ``provenance`` and ``kind`` is optional, because a source
    that reports half of a pick is reporting something real and dropping it
    would lose the pick rather than record it honestly — the same trade
    ``draft_events.player_label`` already makes for a name the crosswalk has
    never seen.

    Nothing here is resolved against our own identifiers. ``team_external_id``
    is Fantrax's team id and ``player_external_id`` is Fantrax's player id;
    turning either into one of our rows is
    :mod:`hoops_gm.draft.feed.service`'s job and is done against facts we
    already hold, never inferred here. ``source_seat`` is different: it is the
    rendered board's column ordinal and is retained without any resolution to a
    participant.
    """

    kind: InstantKind
    provenance: InstantProvenance
    team_external_id: str | None = None
    #: One-indexed rendered-board column. This is a source coordinate, never a
    #: ``DraftParticipant.team_slot`` or a franchise identity.
    source_seat: int | None = None
    #: The mutable label rendered above ``source_seat`` in this snapshot.
    source_seat_label: str | None = None
    player_label: str | None = None
    player_external_id: str | None = None
    #: One-indexed overall pick, when the source states one.
    overall_pick: int | None = None
    round_number: int | None = None
    pick_in_round: int | None = None
    #: An observed clearing price. Never a computed one.
    amount: Decimal | None = None
    #: Set when this instant is a record of something read and **not** a claim
    #: about a player. ``None`` for every ordinary reading.
    #:
    #: The recogniser sets it at read time and nothing ever clears it, which is
    #: the point: the state it names is *"a record was here and this module
    #: could not identify who it was about"*, and an id that cannot be read is
    #: not going to become readable.
    #:
    #: **This exists because the alternative was silence.** A record whose
    #: ``player_external_id`` was present and unreadable used to be dropped by
    #: :func:`~hoops_gm.draft.feed.recognise._accept_list` and counted only in
    #: the ``POST`` ingest response's ``unrecognised``. ``FeedStatus`` carries
    #: no such field and a live board polls ``GET``, so the board was short a
    #: player with every channel reading clean. Driven at PR #104 head
    #: ``7a66d4e``: ``POST -> written 1, unrecognised
    #: [('player_external_id_unreadable', 1)]``; ``GET -> observations 1
    #: applied 1 pending 0 blocked () skipped ()``.
    #:
    #: Three cheaper routes were closed deliberately. ``player_external_id=None``
    #: on an ordinary applicable row is what the round-eleven identity work
    #: forbade, because it makes *supplied and refused* indistinguishable from
    #: *never supplied*; this keeps them apart by naming the field.
    #: ``blocked_reason`` leaves the row pending and therefore an application
    #: candidate. Re-deriving the state at status time would be two paths
    #: answering one question, which is the defect class thirteen review rounds
    #: were spent removing.
    #:
    #: An instant carrying this **names no player**: the recogniser stores
    #: neither a label nor an id on it, so it cannot be reconciled as a reading
    #: about anybody. That is the enforcing half, and it is structural rather
    #: than a rule — see :func:`matching_key`.
    #:
    #: **One direction only.** The recogniser sets it and
    #: :func:`~hoops_gm.draft.feed.service._store` writes it to the row;
    #: ``_to_instant`` does not read it back, because the *column* is broader
    #: than this field. ``apply_observations`` also writes ``already_in_log``
    #: and ``duplicate_within_run`` there, and those rows are real readings of a
    #: pick.
    skipped_reason: str | None = None


def publication_order(
    claimed_at: datetime | None,
    received_at: datetime,
    sequence: int,
) -> tuple[datetime, int]:
    """Where a reading sits in the order its **source** published it.

    Distinct from arrival order, which is :func:`arrival_order`. The two are
    routinely the same and are not the same *fact*, and this package had them
    conflated: ``observed_at`` is our clock at the moment a capture reached the
    backend, and every ordering decision — identity supersession, the
    newest-per-transport collapse, reconciliation's newest-per-key — was made
    on it.

    That is correct for freshness and wrong for supersession. The userscript
    posts captures without a global queue, so two captures published a second
    apart can be delivered in either order; the later publication then carries
    the *earlier* ``observed_at``, and "which reading is current" is answered
    backwards. Driven: a correction published second and delivered first put
    the stale reading on the board — wrong buyer *and* wrong price — and
    blocked the true one as ``identity_superseded``, which reads on the status
    screen exactly like a correction being handled properly.

    ``claimed_at`` is the capture's own timestamp, which is the browser's
    clock and therefore **self-describing and not to be trusted on its own**.
    It is used to *order* and never to compute an age; ``feed_status`` still
    measures every interval against ``observed_at``, our clock, and that
    remains the rule its docstring states. Where the two orders disagree about
    which reading is current, the caller refuses rather than picking one — see
    ``_identity_conflicts``.

    ``sequence`` breaks ties, because two captures inside one second share a
    timestamp under production SQLite's ``CURRENT_TIMESTAMP`` without any
    fixture help.
    """
    return (claimed_at or received_at, sequence)


def arrival_order(received_at: datetime, sequence: int) -> tuple[datetime, int]:
    """Where a reading sits in the order it reached **us**. Our clock.

    Kept beside :func:`publication_order` rather than inlined at its two call
    sites, so that "these are two different orderings" is a thing the code
    says rather than a thing a reader has to notice.
    """
    return (received_at, sequence)


def matching_key(instant: ObservedInstant) -> tuple[str, str] | None:
    """The key two sources are compared on, or ``None`` when there isn't one.

    **The player, not the coordinate.** The disagreement worth catching is
    "these two sources name different buyers, prices or slots for the same
    player", and keying on the coordinate would file that as two unrelated
    single-source observations instead. A coordinate mismatch for one player is
    then a *field* disagreement, which is what it is.

    An external player id wins over a label when present, because it is the
    source's own identifier rather than a string we normalised. When it is
    absent the normalised label is used, and
    :func:`hoops_gm.identity.names.normalize_key` erases more than it looks
    like it does — digits and generational suffixes do not survive, so
    ``"Gary Payton II"`` keys to ``"gary payton"``. That is acceptable for
    comparing two sources' spellings of one real player and is **not** a
    cross-source identity claim; ADR-008 and R23 are about exactly that
    laundering.

    **A refused record has no key because it names nobody**, not because this
    function checks a flag. :func:`~hoops_gm.draft.feed.recognise._instant_from`
    stores neither a label nor an id on a record whose identity it could not
    read, and migration ``0021`` permits a row naming no player *only* when it
    carries a ``skipped_reason``. So "never joins identity matching" holds by
    construction here rather than by a rule someone could later narrow.

    The flag is deliberately **not** consulted: ``skipped_reason`` on a stored
    row is broader than this type's, because
    :func:`~hoops_gm.draft.feed.service.apply_observations` also writes
    ``already_in_log`` and ``duplicate_within_run`` there — and those are
    genuine readings of a pick whose whole value is being reconciled against
    the other source. Keying off the flag would delete the corroboration signal
    at the moment it is worth something.
    """
    if instant.player_external_id:
        return ("player_external_id", instant.player_external_id)
    if instant.player_label:
        key = normalize_key(instant.player_label)
        if key:
            return ("player_key", key)
    return None


@dataclass(frozen=True, slots=True)
class UnrecognisedShape:
    """A payload that reached us and that no recogniser could read.

    The **top-level key names** of the block, and a count. Not the payload:
    this is summarised into an API response and a Fantrax response body can
    contain a whole league. Key names are what tells the next person writing a
    recogniser where to look, and they are the thing a five-minute fix needs.

    Counted and published rather than logged and forgotten, because the failure
    this guards against is silence: a feed that recognises nothing looks exactly
    like a draft where nothing has happened yet.
    """

    #: Sorted tuple of the block's top-level keys, or ``("<list>",)`` etc. for
    #: a non-object block.
    keys: tuple[str, ...]
    occurrences: int
    #: One example locator, so the raw payload can still be found by hand.
    example_locator: str
    #: Why it was not recognised, in this package's own vocabulary.
    reason: str


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    """What one recogniser made of one artifact.

    Both halves are always populated. A result with instants *and* unrecognised
    shapes is the normal case for a batched ``/fxpa/req`` response, which
    carries one entry per method in the request — so "we read the draft block
    and did not read the four beside it" is the honest report.
    """

    instants: tuple[ObservedInstant, ...] = ()
    unrecognised: tuple[UnrecognisedShape, ...] = ()
    #: Set when the whole artifact was rejected before any block was examined —
    #: wrong URL, wrong league, undecodable envelope. ``None`` means the
    #: artifact was examined.
    rejected: str | None = None
    #: Records that named a field their kind forbids, and so were stored with it
    #: dropped. A snake pick carrying a price, or an auction sale carrying a
    #: round and pick number. Counted rather than silent because the drop is a
    #: real loss of information, and because a non-zero value is good evidence
    #: that the draft's snapshotted format disagrees with what the source is
    #: actually publishing — which is worth knowing before it matters.
    coerced_to_kind: int = 0
    #: The names of the fields dropped, deduplicated across this artifact. The
    #: count above says *how many* records lost something; this says *what*, and
    #: only this can tell "an auction's ordinals were discarded, which is
    #: expected" from "every price was discarded on a draft we think is a
    #: snake", which is not.
    fields_dropped: tuple[str, ...] = field(default_factory=tuple)
    #: Fields the recogniser deliberately did not read, named so an absence is
    #: distinguishable from an oversight.
    notes: tuple[str, ...] = field(default_factory=tuple)
    #: Present only for a successfully parsed rendered-board artifact.
    source_board: SourceBoardReading | None = None

    @property
    def recognised_count(self) -> int:
        """Instants that are readings of a **pick**.

        Excludes instants carrying a ``skipped_reason``, which are records this
        module stored precisely because it could *not* identify them. Counting
        those here would publish ``instants_recognised`` as evidence that a
        record was read, on the one channel whose job is saying how much of the
        payload we understood.
        """
        return sum(1 for instant in self.instants if instant.skipped_reason is None)


@dataclass(frozen=True, slots=True)
class SourceBoardReading:
    """Snapshot-level facts from one rendered board, with no participant identity."""

    artifact_key: str
    recogniser: str
    observed_at: datetime
    contact_at: datetime
    layout: str
    seat_count: int
    round_count: int
    picks_made: int
    seat_labels: tuple[str, ...]
