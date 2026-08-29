"""Comparing two sources without letting one source pretend to be two.

Three properties, in the order they matter on a draft night.

**Freshness is measured, not assumed.** :func:`freshness_of` reports the age of
the newest instant each source produced, computed on our own clock against a
``now`` the caller passes in. A source that has produced nothing gets
``last_seen_at=None`` and ``silent=True`` rather than a comfortable zero. The
failure this exists for: the demo served a stale build for hours and returned
``200 OK`` the whole time, and a draft board is the one screen where a
five-minute-old view is indistinguishable from a correct one.

**A disagreement is a finding.** :func:`reconcile` never resolves one. It does
not prefer the newer source, the official source, or the source with more
fields — it reports both readings and lets a person look. Preferring the newer
source is exactly how a wrong reading becomes the record.

**Agreement is only published when it was witnessed twice.** This is the guard,
and it is the reason this module exists at all rather than being six lines
inside the service.

## Why the independence guard is the load-bearing part

A ``frontend`` lane's probe compared a screen against an API, agreed, and was
wrong — it had read the same field into both sides. A cohort manifest nearly
shipped the same defect, comparing one endpoint with itself and reporting
``witnessed: true``, and **nothing in its output could have revealed it**,
because provenance was never recorded.

So :class:`SourceIndependence` is computed from
:class:`~hoops_gm.draft.feed.observations.InstantProvenance` and its verdict
changes what the report is allowed to say. When independence fails, matches are
published as :attr:`ReconciliationReport.unwitnessed_matches` and
:attr:`ReconciliationReport.agreements` is empty — so a consumer that reads
``agreements`` cannot be handed false corroboration even if it never looks at
the verdict.

**What the guard excludes, stated falsifiably.** The defect is *one read
counted as two*. The flag is ``independent=True``. For that flag to be true
while the defect is present, the same bytes would have to arrive under two
different ``artifact_key`` values **and** two different
:class:`~hoops_gm.draft.feed.observations.SourceTransport` values — meaning the
same HTTP response was both stored by the userscript and returned by our own
official client, which are different hosts, different paths and different
response bodies. That reading does not exist for these two sources.

**What it does not exclude, stated plainly.** Two genuinely separate reads of
one server-side truth. If Fantrax's draft room and ``getDraftPicks`` are two
views of one table, then agreement between them confirms *we read the same
table twice consistently* and confirms nothing about whether that table is
right. No arrangement of provenance can distinguish that, and calling this
"corroboration" would be the same laundering one level up. It is called
``witnessed_by_two_transports``, which is what it actually is.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from hoops_gm.draft.feed.observations import (
    ObservedInstant,
    SourceTransport,
    matching_key,
    publication_order,
)


@dataclass(frozen=True, slots=True)
class SourceFreshness:
    """How long since one source last told us anything.

    ``age_seconds`` is ``None`` when ``last_seen_at`` is, and the two move
    together: there is no reading of this object in which a source looks
    current because it has never been heard from.

    Two different clocks are reported, because they answer two different
    questions and conflating them was a real defect here. ``last_seen_at`` is
    the newest *draft instant* — "when did anything new happen". ``contact_at``
    is the newest evidence the transport itself is alive — "is it still
    listening". Between two picks in a live snake draft nothing new happens for
    minutes at a time, so a single clock reports ``silent`` on a bridge that is
    capturing perfectly, and an indicator that cries wolf during ordinary play
    is one the owner learns to ignore before the moment it is true.
    """

    transport: SourceTransport
    last_seen_at: datetime | None
    age_seconds: float | None
    instant_count: int
    #: True when the source has produced nothing, or nothing recently enough.
    #: **Read this with ``instant_count``.** When the source has produced at
    #: least one instant, ``silent`` is judged against ``contact_at`` if contact
    #: is known and against ``last_seen_at`` otherwise, and ``contact_is_known``
    #: says which. When ``instant_count`` is zero, ``silent`` is unconditionally
    #: True no matter how recent contact is — so the triple
    #: ``contact_is_known=True, contact_age_seconds=20.0, silent=True`` is
    #: consistent, not a contradiction. See :func:`freshness_of` for why.
    silent: bool
    #: The threshold ``silent`` was judged against, so the screen can say what
    #: "quiet" meant rather than hard-coding a matching number of its own.
    silence_threshold_seconds: float
    #: The newest ``source_claimed_at`` seen, for display only. Never used to
    #: compute ``age_seconds`` — see :class:`InstantProvenance`.
    source_claimed_at: datetime | None = None
    #: Signed difference between the source's claim and our receipt, in
    #: seconds, when both exist. Published because a large value means one of
    #: the two clocks is wrong and that is worth seeing before draft night,
    #: not because anything here acts on it.
    claim_skew_seconds: float | None = None
    #: When this transport last showed evidence of being alive, independent of
    #: whether it said anything new. ``None`` when the caller has no such
    #: evidence — which is a different state from "it has been quiet", and
    #: ``contact_is_known`` keeps them apart.
    contact_at: datetime | None = None
    contact_age_seconds: float | None = None
    #: False means nobody supplied proof-of-life for this transport, so
    #: ``silent`` fell back to the instant clock and will read True during an
    #: ordinary gap between picks. Published so the screen can say which
    #: question it is actually answering.
    contact_is_known: bool = False


def freshness_of(
    instants: list[ObservedInstant] | tuple[ObservedInstant, ...],
    *,
    transport: SourceTransport,
    now: datetime,
    silence_threshold: timedelta,
    contact_at: datetime | None = None,
) -> SourceFreshness:
    """Age of the newest instant this transport produced, on our clock.

    ``instants`` may contain other transports; they are filtered out here so a
    caller cannot accidentally report the bridge's freshness using the official
    source's timestamps. The defect excluded is *a silent source displaying a
    live source's age*. For the flag ``silent=False`` to be wrong in that way,
    an instant carrying ``transport`` would have to have been produced by a
    different transport, which :mod:`hoops_gm.draft.feed.recognise` sets at
    construction and never copies between instants.

    ``contact_at`` is optional proof the transport is alive that did not come
    from a draft instant — for the bridge, that a capture landed at all. It
    suppresses ``silent`` **only for a transport that has produced at least one
    instant**, because a bridge capturing continuously through a four-minute
    deliberation is not silent, it is waiting, and reporting those identically
    trains the owner to dismiss the one indicator that matters.

    For a transport that has produced **no** instants, contact does not
    suppress anything and ``silent`` stays True however recent it is. That
    asymmetry is deliberate and was a defect once: a bridge capturing page HTML
    from a service-worker-served draft room lands captures continuously while
    the recogniser reads nothing from them, so a feed that had never read a
    single pick reported ``silent=False``. Suppressing a false alarm is worth
    little; issuing a false all-clear on draft night is the thing this whole
    module exists to prevent.

    ``contact_at`` must be evidence *this* transport produced; the caller
    records it, this function only measures it.
    """
    mine = [instant for instant in instants if instant.provenance.transport is transport]
    contact_age = (now - contact_at).total_seconds() if contact_at is not None else None
    threshold = silence_threshold.total_seconds()
    if not mine:
        # Contact deliberately does NOT rescue a source that has produced
        # nothing. It suppresses silence only for a source that has been read
        # successfully at least once, which is the gap between two picks that
        # ``contact_at`` exists for.
        #
        # The defect this ordering excludes is the one that matters most on the
        # night: Fantrax serves the draft room from its service worker, the
        # userscript captures only page HTML, the recogniser reads zero picks
        # -- and a capture still lands, so contact is recent. Judging ``silent``
        # on contact alone made a feed that had never read a single pick report
        # ``silent=False``. A board frozen at pick 4 under a green indicator is
        # worse than no board, because the indicator is the thing that tells
        # him whether to look.
        return SourceFreshness(
            transport=transport,
            last_seen_at=None,
            age_seconds=None,
            instant_count=0,
            silent=True,
            silence_threshold_seconds=threshold,
            contact_at=contact_at,
            contact_age_seconds=contact_age,
            contact_is_known=contact_at is not None,
        )

    newest = max(mine, key=lambda instant: instant.provenance.received_at)
    last_seen_at = newest.provenance.received_at
    age = (now - last_seen_at).total_seconds()
    claimed = newest.provenance.source_claimed_at
    skew = (claimed - last_seen_at).total_seconds() if claimed is not None else None
    return SourceFreshness(
        transport=transport,
        last_seen_at=last_seen_at,
        age_seconds=age,
        instant_count=len(mine),
        silent=(contact_age if contact_age is not None else age) > threshold,
        silence_threshold_seconds=threshold,
        source_claimed_at=claimed,
        claim_skew_seconds=skew,
        contact_at=contact_at,
        contact_age_seconds=contact_age,
        contact_is_known=contact_at is not None,
    )


@dataclass(frozen=True, slots=True)
class SourceIndependence:
    """Whether the two sides of a comparison are two reads or one.

    ``shared_artifacts`` and ``shared_transports`` are published rather than
    collapsed into the boolean, because "these agreed but it was the same
    capture" and "these agreed but both came off the bridge" are different
    problems with different fixes, and a bare ``False`` sends whoever is
    debugging at 7pm to read this source.
    """

    independent: bool
    reason: str
    left_transports: tuple[str, ...]
    right_transports: tuple[str, ...]
    shared_artifacts: tuple[str, ...]
    shared_transports: tuple[str, ...]


def _independence(
    left: list[ObservedInstant],
    right: list[ObservedInstant],
    *,
    left_transport: SourceTransport,
    right_transport: SourceTransport,
) -> SourceIndependence:
    left_transports = {instant.provenance.transport for instant in left}
    right_transports = {instant.provenance.transport for instant in right}
    left_artifacts = {instant.provenance.artifact_key for instant in left}
    right_artifacts = {instant.provenance.artifact_key for instant in right}

    shared_artifacts = tuple(sorted(left_artifacts & right_artifacts))
    shared_transports = tuple(
        sorted(transport.value for transport in left_transports & right_transports)
    )
    names = (
        tuple(sorted(transport.value for transport in left_transports)),
        tuple(sorted(transport.value for transport in right_transports)),
    )

    if not left or not right:
        reason = "one_side_empty"
    elif shared_artifacts:
        # The exact defect: the same artifact read into both sides. Usually that
        # artifact is response bytes; ADR-020 makes rendered-board identity the
        # parsed board content instead.
        reason = "same_artifact_on_both_sides"
    elif shared_transports:
        reason = "same_transport_on_both_sides"
    elif left_transports != {left_transport} or right_transports != {right_transport}:
        # A side carrying a transport it was not declared as means the caller
        # sorted the instants wrongly, and every conclusion below it is void.
        reason = "transport_mislabelled"
    else:
        return SourceIndependence(
            independent=True,
            reason="distinct_artifacts_and_transports",
            left_transports=names[0],
            right_transports=names[1],
            shared_artifacts=(),
            shared_transports=(),
        )

    return SourceIndependence(
        independent=False,
        reason=reason,
        left_transports=names[0],
        right_transports=names[1],
        shared_artifacts=shared_artifacts,
        shared_transports=shared_transports,
    )


@dataclass(frozen=True, slots=True)
class Match:
    """One player both sides named, and whether they said the same about him."""

    key: tuple[str, str]
    left: ObservedInstant
    right: ObservedInstant

    @property
    def player_label(self) -> str | None:
        return self.left.player_label or self.right.player_label


@dataclass(frozen=True, slots=True)
class Disagreement:
    """Two sources naming different values for one field of one player.

    Carries both readings and no verdict. There is deliberately no ``winner``,
    no ``preferred`` and no ``resolved_value``: a disagreement between the only
    two views we have of the draft is information about our own reading, and
    resolving it by rule would delete that information at the moment it is most
    useful.
    """

    key: tuple[str, str]
    player_label: str | None
    field_name: str
    left_value: Any
    right_value: Any
    left_provenance_key: str
    right_provenance_key: str


#: Fields compared between two readings of one player. ``kind`` is included
#: because a snake selection and an auction sale describing the same player
#: means one of the two sources is being read under the wrong format.
_COMPARED_FIELDS: tuple[str, ...] = (
    "kind",
    "team_external_id",
    "player_external_id",
    "overall_pick",
    "round_number",
    "pick_in_round",
    "amount",
)


def values_disagree(left: Any, right: Any) -> bool:
    """Absence is not disagreement; a different value is.

    A source that omits ``round_number`` has not contradicted a source that
    supplies it, and filing that as a disagreement would bury the real ones
    under one row per missing field per pick. Decimal and int compare by value
    so ``Decimal("41")`` and ``41`` are not a finding.

    Public because :mod:`hoops_gm.draft.feed.service` asks the same question of
    the same fields for a different purpose — reconciliation reports a
    disagreement, application refuses to act on one. Those are two jobs, but
    "do these two readings differ?" must not be two implementations: the last
    five review rounds on this package all found the same defect, which was two
    functions that were meant to agree about a payload and had drifted.
    """
    if left is None or right is None:
        return False
    if isinstance(left, Decimal) or isinstance(right, Decimal):
        try:
            return Decimal(str(left)) != Decimal(str(right))
        except (ArithmeticError, ValueError):
            return True
    return bool(left != right)


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """What two sources said, and what that is and is not evidence of."""

    independence: SourceIndependence
    #: Players both sides named, agreeing on every field they both supplied,
    #: **and** genuinely read twice. Empty whenever independence fails.
    agreements: tuple[Match, ...] = ()
    #: Agreeing matches that could not be shown to be two reads. Same content
    #: as ``agreements``, different name, because the name is the claim.
    unwitnessed_matches: tuple[Match, ...] = ()
    #: Field-level contradictions. Always published, independent or not: a
    #: source contradicting itself across two artifacts is also a finding.
    disagreements: tuple[Disagreement, ...] = ()
    #: Players only one side named, keyed by transport value.
    only_left: tuple[ObservedInstant, ...] = ()
    only_right: tuple[ObservedInstant, ...] = ()
    freshness: tuple[SourceFreshness, ...] = ()
    #: Limits of this comparison, in words, carried into the API response so
    #: they reach the screen instead of stopping at this docstring.
    caveats: tuple[str, ...] = field(default_factory=tuple)

    @property
    def witnessed_by_two_transports(self) -> int:
        """How many players two different pipes independently named.

        Named for what it measures. It is **not** a count of verified picks:
        both pipes read Fantrax, so this is consistency between two views of
        one upstream, not confirmation that the upstream is right.
        """
        return len(self.agreements)


def _newest_per_key(
    instants: list[ObservedInstant],
) -> dict[tuple[str, str], ObservedInstant]:
    """One reading per player per side, keeping the one published last.

    A source that reported the same player in two captures — the ordinary case
    for a draft board that republishes the whole list on every pick — should
    not produce a self-disagreement. This is a *within*-source collapse and is
    not the cross-source preference this module refuses to make.

    Ordered by :func:`~hoops_gm.draft.feed.observations.publication_order`,
    the same rule the apply path uses, imported rather than restated so the
    two cannot drift. It previously compared ``received_at`` alone with a
    strict ``>``, which answered two different questions wrongly: ties kept
    whichever reading arrived first in the list, and arrival is not
    publication when captures are delivered out of order.
    """
    latest: dict[tuple[str, str], ObservedInstant] = {}
    for instant in instants:
        key = matching_key(instant)
        if key is None:
            continue
        seen = latest.get(key)
        if seen is None or _order_of(instant) > _order_of(seen):
            latest[key] = instant
    return latest


def _order_of(instant: ObservedInstant) -> tuple[datetime, int]:
    return publication_order(
        instant.provenance.source_claimed_at,
        instant.provenance.received_at,
        instant.provenance.sequence or 0,
    )


def reconcile(
    left: list[ObservedInstant] | tuple[ObservedInstant, ...],
    right: list[ObservedInstant] | tuple[ObservedInstant, ...],
    *,
    left_transport: SourceTransport = SourceTransport.BRIDGE_CAPTURE,
    right_transport: SourceTransport = SourceTransport.OFFICIAL_HTTP,
    now: datetime,
    silence_threshold: timedelta = timedelta(minutes=2),
    contact_at: dict[SourceTransport, datetime] | None = None,
) -> ReconciliationReport:
    """Compare two sources' readings. Detection only; nothing is resolved."""
    left_list = list(left)
    right_list = list(right)

    independence = _independence(
        left_list,
        right_list,
        left_transport=left_transport,
        right_transport=right_transport,
    )

    left_by_key = _newest_per_key(left_list)
    right_by_key = _newest_per_key(right_list)

    matches: list[Match] = []
    disagreements: list[Disagreement] = []
    for key in sorted(left_by_key.keys() & right_by_key.keys()):
        left_instant = left_by_key[key]
        right_instant = right_by_key[key]
        found: list[Disagreement] = []
        for field_name in _COMPARED_FIELDS:
            left_value = getattr(left_instant, field_name)
            right_value = getattr(right_instant, field_name)
            if values_disagree(left_value, right_value):
                found.append(
                    Disagreement(
                        key=key,
                        player_label=left_instant.player_label or right_instant.player_label,
                        field_name=field_name,
                        left_value=left_value,
                        right_value=right_value,
                        left_provenance_key=left_instant.provenance.artifact_key,
                        right_provenance_key=right_instant.provenance.artifact_key,
                    )
                )
        if found:
            disagreements.extend(found)
        else:
            matches.append(Match(key=key, left=left_instant, right=right_instant))

    only_left = tuple(left_by_key[key] for key in sorted(left_by_key.keys() - right_by_key.keys()))
    only_right = tuple(
        right_by_key[key] for key in sorted(right_by_key.keys() - left_by_key.keys())
    )

    everything = left_list + right_list
    freshness = tuple(
        freshness_of(
            everything,
            transport=transport,
            now=now,
            silence_threshold=silence_threshold,
            contact_at=(contact_at or {}).get(transport),
        )
        for transport in (left_transport, right_transport)
    )

    caveats: list[str] = [
        "Both sources read Fantrax. Agreement here is consistency between two "
        "views of one upstream, not confirmation that the upstream is correct.",
    ]
    if not independence.independent:
        caveats.append(
            f"Agreement withheld: {independence.reason}. Matching readings are "
            "reported as unwitnessed_matches."
        )

    return ReconciliationReport(
        independence=independence,
        agreements=tuple(matches) if independence.independent else (),
        unwitnessed_matches=() if independence.independent else tuple(matches),
        disagreements=tuple(disagreements),
        only_left=only_left,
        only_right=only_right,
        freshness=freshness,
        caveats=tuple(caveats),
    )


def group_by_transport(
    instants: list[ObservedInstant] | tuple[ObservedInstant, ...],
) -> dict[SourceTransport, list[ObservedInstant]]:
    """Split a mixed list by the transport recorded on each instant.

    Provided so callers sort by recorded provenance rather than by whichever
    variable they happened to have in hand — which is precisely how one read
    ends up on both sides of a comparison.
    """
    grouped: dict[SourceTransport, list[ObservedInstant]] = defaultdict(list)
    for instant in instants:
        grouped[instant.provenance.transport].append(instant)
    return dict(grouped)
