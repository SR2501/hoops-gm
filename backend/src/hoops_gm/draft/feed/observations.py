"""What one source says happened, and where exactly that claim came from.

Pure dataclasses. No database, no HTTP, no clock — the clock is passed in, so a
freshness figure is never quietly read off the machine that is computing it.

The one idea worth stating twice: **an instant carries its provenance, not its
source's provenance.** A per-source label ("this came from the bridge") is
enough to draw a badge and not enough to establish that two agreeing readings
are two readings. :class:`InstantProvenance` names the exact bytes, so
:mod:`hoops_gm.draft.feed.reconcile` can refuse to call one read two.
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
    "SourceTransport",
    "UnrecognisedShape",
    "matching_key",
]


@dataclass(frozen=True, slots=True)
class InstantProvenance:
    """Which read produced one instant.

    ``artifact_key`` identifies the **bytes**, not the row and not the request.
    For a bridge capture that is the userscript's ``dedupe_key``, which is
    ``METHOD:hash(url):hash(body)`` — so the same response captured twice, by
    two different capture paths, into two different ``bridge_payloads`` rows,
    still produces one key. Keying on the row id instead would make a duplicate
    look like corroboration. For an official read it is the SHA-256 of the raw
    response body, which the client already computes.

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
    already hold, never inferred here.
    """

    kind: InstantKind
    provenance: InstantProvenance
    team_external_id: str | None = None
    player_label: str | None = None
    player_external_id: str | None = None
    #: One-indexed overall pick, when the source states one.
    overall_pick: int | None = None
    round_number: int | None = None
    pick_in_round: int | None = None
    #: An observed clearing price. Never a computed one.
    amount: Decimal | None = None


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
    #: Fields the recogniser deliberately did not read, named so an absence is
    #: distinguishable from an oversight.
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def recognised_count(self) -> int:
        return len(self.instants)
