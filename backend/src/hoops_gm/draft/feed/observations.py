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
from enum import StrEnum

from hoops_gm.identity.names import normalize_key


class SourceTransport(StrEnum):
    """How the bytes reached us.

    Not "which endpoint" and not "which parser" — which *pipe*. Two claims that
    travelled the same pipe are not independent of each other no matter how
    differently they were parsed afterwards, and that is the question
    :class:`~hoops_gm.draft.feed.reconcile.SourceIndependence` asks.
    """

    #: Stored by the userscript into ``bridge_payloads``. Observed traffic.
    BRIDGE_CAPTURE = "bridge_capture"
    #: Requested by us from ``/fxea/general/``. A read we initiated.
    OFFICIAL_HTTP = "official_http"


class InstantKind(StrEnum):
    """The shape of the thing a source claims happened."""

    #: An ordered-draft selection. Carries a coordinate, never a price.
    SELECTION = "selection"
    #: An auction lot clearing. Carries a price, never a coordinate.
    SALE = "sale"


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
    #: Fields the recogniser deliberately did not read, named so an absence is
    #: distinguishable from an oversight.
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def recognised_count(self) -> int:
        return len(self.instants)
