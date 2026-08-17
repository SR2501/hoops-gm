"""Per-field match evidence — closing the question Phase 1 left open.

Phase 1 asked whether a single ``confidence`` float is sufficient, or whether
per-field evidence is needed for a human to adjudicate the tail. It deferred
the answer pending real data. The real data answers it: **evidence per field is
required**, because the dominant case is not disagreement but *absence*, and a
scalar cannot tell those apart.

The measurement, from the live ``getPlayerIds`` payload on 2026-08-17:

* 1,788 player rows, of which **1,206 carry ``team: "(N/A)"``** — two thirds of
  the payload can contribute no team evidence at all;
* ``sportRadarId`` present on 1,438, ``rotowireId`` on 1,723, ``statsIncId`` on
  only 851;
* genuine duplicate names within one source — two "Johnson, Jalen", two
  "Jackson, Justin", two "Williams, Jaylin", two "Burton, Deonte".

Collapse that into one number and two very different rows score identically:
one where the team is unknown, and one where the team is known and *wrong*. The
first is an ordinary free agent and is probably a correct match. The second is
probably two different people. A human triaging the tail needs to see which is
which, and no scalar carries it.

So each field yields :class:`FieldEvidence` — ``AGREE``, ``DISAGREE`` or
``UNKNOWN`` — which is stored per field, and confidence is derived from the
combination rather than replacing it. ``UNKNOWN`` never scores as agreement and
never as disagreement; it withholds.
"""

from __future__ import annotations

from dataclasses import dataclass

from hoops_gm.db.models.enums import FieldEvidence
from hoops_gm.identity.names import NormalizedName, normalize_positions

__all__ = [
    "FieldEvidence",
    "MatchEvidence",
    "compare_optional",
    "compare_positions",
    "compare_suffix",
    "score_evidence",
]


def compare_optional(left: str | None, right: str | None) -> FieldEvidence:
    """Compare two values where either may be absent."""
    if not left or not right:
        return FieldEvidence.UNKNOWN
    return FieldEvidence.AGREE if left == right else FieldEvidence.DISAGREE


def compare_positions(left: str | None, right: str | None) -> FieldEvidence:
    """Compare positions as overlapping sets rather than as strings.

    Sources disagree on granularity: Fantrax says ``PG`` where a box score says
    ``G``. Any overlap is agreement, because the claim being tested is "not
    contradictory", not "identical". A centre and a point guard genuinely
    disagree; a ``PG`` and a ``G`` do not.
    """
    left_set = normalize_positions(left)
    right_set = normalize_positions(right)
    if not left_set or not right_set:
        return FieldEvidence.UNKNOWN
    return FieldEvidence.AGREE if left_set & right_set else FieldEvidence.DISAGREE


def compare_suffix(left: NormalizedName, right: NormalizedName) -> FieldEvidence:
    """Compare generational suffixes.

    A suffix present on one side and absent on the other is ``UNKNOWN``, not
    disagreement: sources drop "Jr." constantly. Two *different* stated
    suffixes are real disagreement, and that is the father-and-son case the
    whole field exists for.
    """
    if not left.suffix or not right.suffix:
        return FieldEvidence.UNKNOWN
    return FieldEvidence.AGREE if left.suffix == right.suffix else FieldEvidence.DISAGREE


@dataclass(frozen=True)
class MatchEvidence:
    """The per-field verdict behind one candidate match."""

    name: FieldEvidence = FieldEvidence.UNKNOWN
    team: FieldEvidence = FieldEvidence.UNKNOWN
    position: FieldEvidence = FieldEvidence.UNKNOWN
    suffix: FieldEvidence = FieldEvidence.UNKNOWN

    @property
    def disagreements(self) -> tuple[str, ...]:
        return tuple(
            field
            for field, value in (
                ("name", self.name),
                ("team", self.team),
                ("position", self.position),
                ("suffix", self.suffix),
            )
            if value is FieldEvidence.DISAGREE
        )

    @property
    def agreements(self) -> tuple[str, ...]:
        return tuple(
            field
            for field, value in (
                ("name", self.name),
                ("team", self.team),
                ("position", self.position),
                ("suffix", self.suffix),
            )
            if value is FieldEvidence.AGREE
        )

    @property
    def unknowns(self) -> tuple[str, ...]:
        return tuple(
            field
            for field, value in (
                ("name", self.name),
                ("team", self.team),
                ("position", self.position),
                ("suffix", self.suffix),
            )
            if value is FieldEvidence.UNKNOWN
        )

    def summary(self) -> str:
        """One line a human can read in an unmatched report."""
        parts = []
        if self.agreements:
            parts.append("agree: " + ",".join(self.agreements))
        if self.disagreements:
            parts.append("DISAGREE: " + ",".join(self.disagreements))
        if self.unknowns:
            parts.append("unknown: " + ",".join(self.unknowns))
        return "; ".join(parts) or "no evidence"


#: How much each field contributes when it agrees. Name dominates because it is
#: the only field present on both sides of every comparison; team is the most
#: valuable corroborator when it exists, which is why it outweighs position.
_AGREEMENT_WEIGHT = {"name": 0.70, "team": 0.20, "position": 0.06, "suffix": 0.04}

#: What a disagreement costs. **Team is deliberately cheap, and that is a
#: correction made after running this against real data.**
#:
#: The obvious design charges heavily for a contradicted team, on the reasoning
#: that two same-named players are told apart by their teams. Running it showed
#: why that is wrong: the two sources are snapshots taken at different moments.
#: On 2026-08-17 Fantrax had Giannis Antetokounmpo on MIA, Luguentz Dort on ATL
#: and Naz Reid on CHA — the 2026-27 rosters — while ``CommonAllPlayers`` for
#: season 2025-26 had them on MIL, OKC and MIN. A 0.45 penalty pushed all three
#: below the review floor, so three of the league's better-known players came
#: out as *no candidate at all*. Mid-season the same thing happens for days
#: around any trade, whichever source updates second.
#:
#: Telling two same-named players apart is still done by team — but through the
#: **ambiguity margin**, which compares candidates against each other. The one
#: whose team agrees outscores the one whose team does not by 0.30, which is
#: comfortably decisive. That is relative evidence doing relative work, and it
#: does not punish a player merely for having been traded.
#:
#: A contradicted name still floors the score, and a contradicted suffix is
#: expensive, because father-and-son is the case with no other tell.
_DISAGREEMENT_PENALTY = {"name": 0.70, "team": 0.10, "position": 0.12, "suffix": 0.35}


def score_evidence(evidence: MatchEvidence) -> float:
    """Reduce per-field evidence to a confidence in ``[0, 1]``.

    Deliberately a plain weighted sum with published weights rather than
    anything fitted. There is no labelled training set for this problem — that
    is precisely what makes it R7 — so a learned score would be fitted to
    assumptions and would look more authoritative than it is. The weights are
    arguable; what matters is that the evidence behind them is stored
    alongside, so a disputed match is re-adjudicable without re-running
    anything.

    Name disagreement floors the score at zero: nothing else can rescue a match
    between two different names, because the name is the only evidence that is
    always present.
    """
    if evidence.name is FieldEvidence.DISAGREE:
        return 0.0

    score = 0.0
    for field, value in (
        ("name", evidence.name),
        ("team", evidence.team),
        ("position", evidence.position),
        ("suffix", evidence.suffix),
    ):
        if value is FieldEvidence.AGREE:
            score += _AGREEMENT_WEIGHT[field]
        elif value is FieldEvidence.DISAGREE:
            score -= _DISAGREEMENT_PENALTY[field]

    return max(0.0, min(1.0, score))
