"""The cross-source player identity resolver — risk R7.

**There is no anchor pair.** Verified live 2026-08-17: Fantrax's
``getPlayerIds`` exposes ``statsIncId``, ``rotowireId`` and ``sportRadarId``,
and NBA.com publishes none of them. The plan originally assumed Fantrax and
``nba_api`` shared a key; they do not. Every cross-source match in this project
is inferred from the very first join, which is why ``confidence``,
``match_method`` and ``is_manual_override`` are load-bearing rather than
metadata.

The ``sportRadarId`` bridge was investigated as instructed and **does not
exist**: no free, stable public dataset maps a Sportradar GUID to an NBA.com
person id. The open ID datasets carry Basketball-Reference, ESPN and Spotrac
identifiers, and are themselves built by name matching — so joining through one
would be name matching with extra steps and an extra dependency. Sportradar's
own mapping endpoint is behind a commercial subscription, which is an
owner-only decision.

The three identifiers are still recorded as first-class crosswalk rows, for two
reasons that pay off now rather than hypothetically: they de-duplicate *within*
Fantrax, where genuine duplicate names exist (two "Johnson, Jalen"), and they
survive Fantrax rotating its own ``fantraxId``. If a projection source ever
carries one, the bridge exists that day.

## How resolution works

1. **Block** on a cheap key to avoid comparing 1,788 by 5,205 pairs.
   Candidates come from the exact normalised name, then from
   ``last name + first initial``, which catches "Cam" versus "Cameron".
2. **Score** each candidate with :mod:`hoops_gm.identity.evidence` — per field,
   three-valued, so absence and disagreement stay distinct.
3. **Decide** with two thresholds and an ambiguity rule. A match is only
   automatic when it is both confident *and* clearly better than the
   runner-up; two candidates a hair apart is exactly the father-and-son case,
   and picking the higher one silently is how a season's numbers get corrupted.

Everything else goes to the unmatched report for a human, which is the point:
the tail is where this fails, and it fails quietly.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

from hoops_gm.identity.evidence import (
    FieldEvidence,
    MatchEvidence,
    compare_optional,
    compare_positions,
    compare_suffix,
    score_evidence,
)
from hoops_gm.identity.names import NormalizedName, normalize_name, normalize_team_abbreviation

#: At or above this, and unambiguous, a match is accepted automatically.
AUTO_ACCEPT_CONFIDENCE = 0.85
#: Below this, a candidate is not even offered as a suggestion.
REVIEW_FLOOR_CONFIDENCE = 0.55
#: The winner must beat the runner-up by at least this much. Two candidates
#: within a whisker of each other is the signature of two real people with the
#: same name, not of one person matched twice.
AMBIGUITY_MARGIN = 0.10

#: Credit for being the **only** candidate whose name agrees.
#:
#: Added after running the resolver against the real payloads, which showed
#: this evidence was being thrown away. ``CommonAllPlayers`` carries no
#: position at all, so a Fantrax row could reach at most 0.90 and — whenever
#: the NBA side had no current team, which is true of every player not on a
#: roster — at most 0.70. The result was 898 of 1,788 rows sitting in manual
#: review with the identical reason "name agrees, nothing else is known", which
#: is a queue no human will ever read honestly.
#:
#: But "one candidate agrees" is itself strong evidence, and it is stronger the
#: larger the pool: matching one name uniquely out of 5,205 players spanning
#: 75 years is a much better argument than three fields agreeing out of a pool
#: of ten. The bonus takes a unique, uncontradicted, exact name match to
#: exactly the auto-accept threshold — so it is accepted, and *anything at all*
#: that contradicts it drops it back to a human.
UNIQUE_NAME_BONUS = 0.15


class HasIdentityFields(Protocol):
    """The minimum a record must expose to be resolvable."""

    @property
    def identity_key(self) -> str: ...
    @property
    def identity_name(self) -> str: ...
    @property
    def identity_team(self) -> str | None: ...
    @property
    def identity_position(self) -> str | None: ...


@dataclass(frozen=True)
class ResolvableRecord:
    """One side of a comparison, normalised once and reused.

    Normalising inside the scoring loop would redo the same Unicode work
    millions of times; doing it here also means the normalised form is
    inspectable when a match is disputed.
    """

    key: str
    raw_name: str
    team: str | None
    position: str | None
    normalized: NormalizedName

    @classmethod
    def build(
        cls, *, key: str, name: str, team: str | None = None, position: str | None = None
    ) -> ResolvableRecord:
        return cls(
            key=key,
            raw_name=name,
            team=normalize_team_abbreviation(team) or None,
            position=position,
            normalized=normalize_name(name),
        )


@dataclass(frozen=True)
class Candidate:
    """A scored possibility, with the reasoning attached."""

    target: ResolvableRecord
    evidence: MatchEvidence
    confidence: float
    #: Credit added because this was the *only* candidate whose name agreed.
    #: Recorded separately so ``confidence - uniqueness_bonus`` recovers the
    #: field-evidence score and a disputed match can be re-argued from parts.
    uniqueness_bonus: float = 0.0

    @property
    def field_confidence(self) -> float:
        return self.confidence - self.uniqueness_bonus


@dataclass(frozen=True)
class Resolution:
    """The outcome for one source record."""

    source_record: ResolvableRecord
    #: Best candidate, if one scored above :data:`REVIEW_FLOOR_CONFIDENCE`.
    best: Candidate | None
    #: Runner-up, retained because the *gap* is what makes a match safe.
    runner_up: Candidate | None
    accepted: bool
    reason: str

    @property
    def confidence(self) -> float:
        return self.best.confidence if self.best else 0.0

    @property
    def evidence(self) -> MatchEvidence:
        return self.best.evidence if self.best else MatchEvidence()

    @property
    def match_method(self) -> str:
        """Which method to record on ``player_external_ids.match_method``.

        Never ``anchor_id``. No shared identifier exists between these sources,
        so claiming one would be false on the project's highest-severity risk.
        """
        if self.best is None:
            return "fuzzy"
        evidence = self.best.evidence
        if evidence.team is FieldEvidence.AGREE and evidence.position is FieldEvidence.AGREE:
            return "name_team_position"
        if evidence.team is FieldEvidence.AGREE:
            return "name_team_position"
        if self.source_record.normalized.key == self.best.target.normalized.key:
            return "normalized_name"
        return "fuzzy"


@dataclass
class ResolutionReport:
    """Everything one resolver run produced, including what it refused to do."""

    accepted: list[Resolution] = field(default_factory=list)
    needs_review: list[Resolution] = field(default_factory=list)
    unmatched: list[Resolution] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.accepted) + len(self.needs_review) + len(self.unmatched)

    @property
    def match_rate(self) -> float:
        return len(self.accepted) / self.total if self.total else 0.0

    def all_resolutions(self) -> list[Resolution]:
        return [*self.accepted, *self.needs_review, *self.unmatched]


class IdentityResolver:
    """Resolves source records against a set of canonical records.

    Neither side is privileged: the ``targets`` are whichever collection is
    being treated as canonical for this run — normally the NBA player list,
    since NBA.com is the source of the stats every number is built from.
    """

    def __init__(
        self,
        targets: Iterable[ResolvableRecord],
        *,
        auto_accept: float = AUTO_ACCEPT_CONFIDENCE,
        review_floor: float = REVIEW_FLOOR_CONFIDENCE,
        ambiguity_margin: float = AMBIGUITY_MARGIN,
    ) -> None:
        self.targets = list(targets)
        self.auto_accept = auto_accept
        self.review_floor = review_floor
        self.ambiguity_margin = ambiguity_margin

        self._by_key: dict[str, list[ResolvableRecord]] = defaultdict(list)
        self._by_last_initial: dict[str, list[ResolvableRecord]] = defaultdict(list)
        for target in self.targets:
            self._by_key[target.normalized.key].append(target)
            self._by_last_initial[target.normalized.last_first_initial].append(target)

    # -- candidate generation ---------------------------------------------

    def candidates_for(self, record: ResolvableRecord) -> list[ResolvableRecord]:
        """Blocking: the small set worth scoring, not the whole target list.

        Two blocks, unioned. The exact normalised key is the common case. The
        ``last name + first initial`` block is what catches "Cam Thomas" versus
        "Cameron Thomas" and "Nic" versus "Nicolas" — abbreviations that no
        amount of accent folding will reconcile.
        """
        seen: dict[str, ResolvableRecord] = {}
        for target in self._by_key.get(record.normalized.key, ()):
            seen[target.key] = target
        for target in self._by_last_initial.get(record.normalized.last_first_initial, ()):
            seen[target.key] = target
        return list(seen.values())

    # -- scoring -----------------------------------------------------------

    def evaluate(self, record: ResolvableRecord, target: ResolvableRecord) -> Candidate:
        name_evidence = _name_evidence(record.normalized, target.normalized)
        evidence = MatchEvidence(
            name=name_evidence,
            team=compare_optional(record.team, target.team),
            position=compare_positions(record.position, target.position),
            suffix=compare_suffix(record.normalized, target.normalized),
        )
        return Candidate(target=target, evidence=evidence, confidence=score_evidence(evidence))

    def resolve_one(self, record: ResolvableRecord) -> Resolution:
        scored = [self.evaluate(record, target) for target in self.candidates_for(record)]
        scored = self._apply_uniqueness(record, scored)
        scored.sort(key=lambda c: (-c.confidence, c.target.key))

        if not scored:
            return Resolution(
                source_record=record,
                best=None,
                runner_up=None,
                accepted=False,
                reason="no candidate shares a name key",
            )

        best = scored[0]
        runner_up = scored[1] if len(scored) > 1 else None

        if best.confidence < self.review_floor:
            return Resolution(
                source_record=record,
                best=None,
                runner_up=runner_up,
                accepted=False,
                reason=(
                    f"best candidate {best.target.raw_name!r} scored "
                    f"{best.confidence:.2f}, below the review floor "
                    f"{self.review_floor:.2f} ({best.evidence.summary()})"
                ),
            )

        # Ambiguity is checked **before** the confidence threshold, and the
        # order matters. Two candidates a hair apart is a different problem
        # from one weak candidate, and it is the more urgent one: it is the
        # signature of two real people sharing a name. Checking the threshold
        # first buries that under "scored 0.70, below auto-accept", which sends
        # a human looking for missing corroboration instead of for a
        # collision.
        if (
            runner_up is not None
            and (best.confidence - runner_up.confidence) < self.ambiguity_margin
        ):
            return Resolution(
                source_record=record,
                best=best,
                runner_up=runner_up,
                accepted=False,
                reason=(
                    f"ambiguous: {best.target.raw_name!r} at {best.confidence:.2f} and "
                    f"{runner_up.target.raw_name!r} at {runner_up.confidence:.2f} are within "
                    f"{self.ambiguity_margin:.2f}; two people with one name is the likely "
                    "explanation and a human must choose"
                ),
            )

        if best.confidence < self.auto_accept:
            return Resolution(
                source_record=record,
                best=best,
                runner_up=runner_up,
                accepted=False,
                reason=(
                    f"scored {best.confidence:.2f}, below the auto-accept "
                    f"threshold {self.auto_accept:.2f} ({best.evidence.summary()})"
                ),
            )

        return Resolution(
            source_record=record,
            best=best,
            runner_up=runner_up,
            accepted=True,
            reason=f"accepted at {best.confidence:.2f} ({best.evidence.summary()})",
        )

    def resolve(self, records: Sequence[ResolvableRecord]) -> ResolutionReport:
        resolutions = self._reject_target_collisions(
            [self.resolve_one(record) for record in records]
        )

        report = ResolutionReport()
        for resolution in resolutions:
            if resolution.accepted:
                report.accepted.append(resolution)
            elif resolution.best is not None:
                report.needs_review.append(resolution)
            else:
                report.unmatched.append(resolution)
        return report

    # -- collisions --------------------------------------------------------

    def _reject_target_collisions(self, resolutions: list[Resolution]) -> list[Resolution]:
        """Demote every match where two source records claim the same player.

        :meth:`resolve_one` asks "is this record ambiguous between candidates?"
        — one source row against many targets. It cannot see the mirror
        question: **many source rows against one target.** Two Fantrax rows can
        each be the confident best match for the same NBA player, and each is
        individually unambiguous.

        Found by running the importer, which hit
        ``uq_player_external_ids_current`` on two "Williams, Jaylin" rows both
        resolving onto one NBA player. The Phase 1 schema was right to have
        that constraint: without it the crosswalk fans out and every aggregate
        through it double-counts.

        At most one of a colliding set can be correct and nothing here can tell
        which, so all of them go to a human. Demoting rather than picking is
        the point — silently keeping the higher score would be a coin flip
        recorded as a fact.
        """
        by_target: dict[str, list[Resolution]] = defaultdict(list)
        for resolution in resolutions:
            if resolution.accepted and resolution.best is not None:
                by_target[resolution.best.target.key].append(resolution)

        colliding = {
            id(resolution): group
            for group in by_target.values()
            if len(group) > 1
            for resolution in group
        }
        if not colliding:
            return resolutions

        adjusted: list[Resolution] = []
        for resolution in resolutions:
            group = colliding.get(id(resolution))
            if group is None:
                adjusted.append(resolution)
                continue
            others = [r.source_record.raw_name for r in group if r is not resolution]
            target_name = resolution.best.target.raw_name if resolution.best else "?"
            adjusted.append(
                replace(
                    resolution,
                    accepted=False,
                    reason=(
                        f"collision: {len(group)} source records claim {target_name!r} "
                        f"— also {', '.join(repr(name) for name in others[:3])}. "
                        "At most one can be right and nothing here can tell which, "
                        "so a human must choose"
                    ),
                )
            )
        return adjusted

    # -- uniqueness --------------------------------------------------------

    def _apply_uniqueness(
        self, record: ResolvableRecord, scored: list[Candidate]
    ) -> list[Candidate]:
        """Credit a candidate for being the only one whose name agrees.

        Applied only on an **exact** normalised-key match. A prefix match
        ("cam"/"cameron") is already a judgement call, and stacking a
        uniqueness bonus on top of a judgement call is how two guesses become
        an accepted fact.
        """
        agreeing = [
            candidate
            for candidate in scored
            if candidate.evidence.name is FieldEvidence.AGREE
            and candidate.target.normalized.key == record.normalized.key
        ]
        if len(agreeing) != 1:
            return scored

        unique = agreeing[0]
        promoted = replace(
            unique,
            confidence=min(1.0, unique.confidence + UNIQUE_NAME_BONUS),
            uniqueness_bonus=UNIQUE_NAME_BONUS,
        )
        return [promoted if candidate is unique else candidate for candidate in scored]


def _name_evidence(left: NormalizedName, right: NormalizedName) -> FieldEvidence:
    """Whether two normalised names agree.

    Exact key equality is agreement. A shared surname with one given name a
    prefix of the other ("cam"/"cameron", "nic"/"nicolas") is also agreement,
    because feeds abbreviate given names and refusing those would push a real
    chunk of the league into the manual tail. Anything else disagrees — and
    name disagreement floors the score, so this is the one comparison that can
    reject a match on its own.
    """
    if not left.key or not right.key:
        return FieldEvidence.UNKNOWN
    if left.key == right.key:
        return FieldEvidence.AGREE
    if left.last and left.last == right.last and left.first and right.first:
        shorter, longer = sorted((left.first, right.first), key=len)
        # Two characters is the shortest abbreviation worth honouring; one
        # would make every "J. Smith" agree with every other.
        if len(shorter) >= 2 and longer.startswith(shorter):
            return FieldEvidence.AGREE
    return FieldEvidence.DISAGREE
