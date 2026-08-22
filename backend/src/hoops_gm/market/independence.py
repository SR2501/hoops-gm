"""Whether a published price list may be used as a benchmark.

This is a **consumption** rule, not an ingestion rule, which is why it lives
outside ``ingest/``. Every source in ``auction_value_sources`` is imported,
stored, queryable and displayable. What this module decides is narrower and
harder: whether a source's numbers constitute *independent evidence* about the
market, such that our disagreement with them means anything.

## Why this is a refusal and not a warning

The owner's differentiator is not beating the consensus — most of our numbers
should mirror it. It is explaining and defending the handful of players where
we disagree. That makes a seeded auction value the **benchmark we are measured
against**, and it makes circularity worse than merely noisy:

* a source derived from projections we also use will *agree* with us wherever
  our valuation formula resembles theirs — fake agreement, which hides real
  disagreements;
* and it will *disagree* wherever the two formulas differ — fake disagreement,
  which invents an edge we do not have.

Both are indistinguishable from the real thing by inspection. A document
saying "beware circularity" cannot catch either, and this project spent a day
cataloguing documents of exactly that kind that caught nothing. So the guard is
a query with a hard result.

## What it actually checks

A source is inadmissible as independent evidence when the set of projection
publishers its method consumes intersects the set of projection publishers we
have imported. Nothing subtler: no similarity score, no threshold. The join is
``auction_value_source_inputs.our_projection_source`` against
``projection_sources`` that have at least one ``projection_imports`` row.

"Has at least one import" rather than "is registered" on purpose: a registered
source with no imported file contributes nothing to our numbers, and refusing
on it would be refusing on an intention rather than on data we hold.

**The rule is "refuse unless lineage is established and disjoint", not "refuse
when lineage intersects".** Those differ on the case that matters. An earlier
version implemented the second, so a source with *no* recorded lineage was
cleared: the overlap test examined an empty set, found no intersection, and
reported that as independence. Deleting a source's lineage rows turned a live
circularity refusal into a pass. Absence of evidence is not a clearance, and
the empty-set check reporting success is the oldest failure in this
repository's register — it arrived here in the guard written to prevent a
different one.

So there are three lineage verdicts, not two: overlapping lineage refuses,
*unrecorded* lineage refuses, and established disjoint lineage passes,
carrying a caveat if the derivation *method* is unknown. A source believed to
observe real auctions rather than derive from projections still records an
input row — with no projection source — so that "established as deriving from
nothing of ours" stays distinguishable from "nobody looked".

**It fires on any source whose projection lineage we also import.** That is
demonstrated end-to-end against a real Basketball Monster projection import
through the ordinary CSV path. Hashtag is the case people reach for, and it is
a genuinely reachable circular case *at the source level*, but note that no
Hashtag projection can be imported today at all: ``import_projection_csv``
refuses an unverified profile and only Basketball Monster is verified. That
path refuses Hashtag one step earlier, so the Hashtag arm of this guard awaits
an import path that does not yet exist.

Separately, a basis we could not establish also blocks benchmark use, for an
unrelated reason: a dollar figure whose budget, league size or category count
is unknown is not comparable to ours at all. Same verdict, different cause, and
the two are reported as different findings rather than one boolean. A basis we
*inferred* rather than read is admissible but never silent.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import AuctionValueDerivation, BasisEvidence, ExternalSource
from hoops_gm.db.models.market import (
    BASIS_FIELDS,
    AuctionValueImport,
    AuctionValueSource,
    AuctionValueSourceInput,
)
from hoops_gm.db.models.projections import ProjectionImport, ProjectionSource

__all__ = [
    "BenchmarkAdmissibility",
    "IndependenceFinding",
    "assess_benchmark_admissibility",
    "assess_source_independence",
    "imported_projection_sources",
]

#: Finding codes. Strings rather than an enum: these are diagnostic labels for
#: humans and logs, not a stored vocabulary, and adding one should not require
#: a migration.
CIRCULAR_LINEAGE = "circular_lineage"
#: No lineage rows at all, so overlap could not be tested. A refusal.
LINEAGE_UNESTABLISHED = "lineage_unestablished"
#: Lineage is known and disjoint, but the method turning inputs into dollars
#: is not. A caveat.
DERIVATION_UNESTABLISHED = "derivation_unestablished"
BASIS_UNESTABLISHED = "basis_unestablished"
#: A basis field carries a figure we inferred rather than one the source
#: stated. A caveat, and deliberately not silent — see the note in
#: :func:`assess_benchmark_admissibility`.
BASIS_INFERRED = "basis_inferred"


@dataclass(frozen=True)
class IndependenceFinding:
    """One reason a source is, or is not quite, usable as a benchmark."""

    code: str
    #: ``False`` means this finding alone disqualifies the source as
    #: independent evidence. ``True`` means it is a caveat worth surfacing that
    #: does not disqualify — an unestablished derivation is still a usable
    #: benchmark, provided it is labelled.
    admissible: bool
    detail: str


@dataclass(frozen=True)
class BenchmarkAdmissibility:
    """The verdict for one source, with every reason behind it."""

    source_slug: str
    findings: tuple[IndependenceFinding, ...]

    @property
    def admissible(self) -> bool:
        return all(finding.admissible for finding in self.findings)

    @property
    def blocking_findings(self) -> tuple[IndependenceFinding, ...]:
        return tuple(finding for finding in self.findings if not finding.admissible)

    def explain(self) -> str:
        verdict = "admissible as independent market evidence"
        if not self.admissible:
            verdict = "NOT admissible as independent market evidence"
        lines = [f"{self.source_slug}: {verdict}"]
        lines.extend(f"  [{finding.code}] {finding.detail}" for finding in self.findings)
        return "\n".join(lines)


def imported_projection_sources(session: Session) -> frozenset[ExternalSource]:
    """Projection publishers we hold at least one imported file from.

    The honest form of "in our blend": registration is an intention, an import
    is data we actually have.
    """
    rows = session.execute(
        select(ProjectionSource.source)
        .join(ProjectionImport, ProjectionImport.source_id == ProjectionSource.id)
        .distinct()
    ).scalars()
    return frozenset(rows)


def assess_source_independence(
    session: Session, source: AuctionValueSource
) -> tuple[IndependenceFinding, ...]:
    """Lineage findings for one source: circularity, and derivation clarity."""
    ours = imported_projection_sources(session)

    inputs = list(
        session.execute(
            select(AuctionValueSourceInput).where(AuctionValueSourceInput.source_id == source.id)
        ).scalars()
    )

    findings: list[IndependenceFinding] = []

    overlapping = sorted(
        {
            item.our_projection_source.value
            for item in inputs
            if item.our_projection_source is not None and item.our_projection_source in ours
        }
    )
    if overlapping:
        shared = ", ".join(overlapping)
        findings.append(
            IndependenceFinding(
                code=CIRCULAR_LINEAGE,
                admissible=False,
                detail=(
                    f"{source.slug} derives from projections published by {shared}, and we have "
                    f"imported {shared} projections ourselves. Comparing our valuation against "
                    f"this source measures the difference between two valuation formulas over "
                    f"the same underlying projections, not a difference of opinion about "
                    f"players — so agreement here is not corroboration and disagreement here is "
                    f"not an edge.\n"
                    f"        THIS IS THE GUARD WORKING, NOT A DATA ERROR. It fires for any "
                    f"auction-value source whose projection lineage we also import, and it is "
                    f"expected to fire the moment we begin importing a publisher we previously "
                    f"only benchmarked against. The source stays imported, stored and "
                    f"displayable; only its use as *independent evidence* is refused.\n"
                    f"        To make {source.slug} admissible again, stop importing {shared} "
                    f"projections. Do not loosen this check."
                ),
            )
        )

    if not inputs:
        findings.append(
            IndependenceFinding(
                code=LINEAGE_UNESTABLISHED,
                admissible=False,
                detail=(
                    f"{source.slug} has no recorded inputs, so its lineage could not be tested "
                    f"for overlap with ours at all. This is a refusal, not a caveat: the check "
                    f"above examined an empty set and would have reported 'no overlap' for a "
                    f"source that is wholly derived from projections we import.\n"
                    f"        Absence of evidence is not a clearance. Two routes make that "
                    f"concrete — a source registered with no lineage rows clears, and deleting "
                    f"the lineage rows of a source the guard is actively refusing flips it to "
                    f"admissible. Both are demonstrated in the tests.\n"
                    f"        To make {source.slug} admissible, record what it derives from. "
                    f"A source believed to observe real auctions still records an input row "
                    f"with kind=OBSERVED_AUCTIONS and no projection source, so 'we established "
                    f"that it derives from nothing of ours' and 'nobody looked' remain "
                    f"distinguishable."
                ),
            )
        )
    elif source.derivation_method is AuctionValueDerivation.UNESTABLISHED:
        findings.append(
            IndependenceFinding(
                code=DERIVATION_UNESTABLISHED,
                admissible=True,
                detail=(
                    f"{source.slug} has recorded inputs, so its lineage was tested and does not "
                    f"overlap ours, but *how* it turns those inputs into dollars is not "
                    f"established. That is a genuine caveat rather than a refusal: the "
                    f"circularity question is answered, the method question is not. Usable as a "
                    f"benchmark while labelled as such."
                ),
            )
        )

    return tuple(findings)


def assess_benchmark_admissibility(
    session: Session, auction_import: AuctionValueImport
) -> BenchmarkAdmissibility:
    """Whether one imported price list may be compared against.

    Combines the source's lineage findings with this import's basis. An
    unestablished basis blocks on its own: a dollar figure whose budget, league
    size or category count is unknown is not comparable to a price in our
    league, whatever its provenance.
    """
    source = session.get(AuctionValueSource, auction_import.source_id)
    if source is None:  # pragma: no cover - FK makes this unreachable
        raise ValueError(f"import {auction_import.id} has no source row")

    findings = list(assess_source_independence(session, source))

    unestablished = [
        value_column
        for value_column, evidence_column in BASIS_FIELDS
        if getattr(auction_import, evidence_column) == BasisEvidence.UNESTABLISHED
    ]
    if unestablished:
        missing = ", ".join(unestablished)
        findings.append(
            IndependenceFinding(
                code=BASIS_UNESTABLISHED,
                admissible=False,
                detail=(
                    f"import {auction_import.id} ({source.slug}, as of "
                    f"{auction_import.as_of_date}) has an unestablished basis: {missing}. Two "
                    f"price lists at different budgets, league sizes or category counts are "
                    f"different quantities that both look like money, so these dollars cannot "
                    f"be compared against ours until the basis is known.\n"
                    f"        Converting them to our basis would be a modelling decision — "
                    f"proportional scaling and scaling only the surplus above the per-slot "
                    f"reserve give materially different dollars for the same player — and it "
                    f"belongs to auction-values under the Model gate, not here."
                ),
            )
        )

    inferred = [
        value_column
        for value_column, evidence_column in BASIS_FIELDS
        if getattr(auction_import, evidence_column) == BasisEvidence.INFERRED
    ]
    if inferred:
        guessed = ", ".join(inferred)
        findings.append(
            IndependenceFinding(
                code=BASIS_INFERRED,
                admissible=True,
                detail=(
                    f"import {auction_import.id} ({source.slug}, as of "
                    f"{auction_import.as_of_date}) has an inferred basis for: {guessed}. These "
                    f"figures were not stated by the source; we deduced them, and a deduction "
                    f"about a budget is exactly the kind of claim that has already been wrong "
                    f"here once.\n"
                    f"        This is a caveat rather than a refusal, but it must not be "
                    f"silent. The stated/inferred distinction was recorded per field at import "
                    f"and was then dropped at consumption: an inferred basis produced findings "
                    f"byte-identical to a fully stated one, so the distinction existed in the "
                    f"database and nowhere a decision could see it. Recording a distinction "
                    f"that no consumer reads is the same as not recording it."
                    + (
                        f"\n        Basis note: {auction_import.basis_note}"
                        if auction_import.basis_note
                        else ""
                    )
                ),
            )
        )

    return BenchmarkAdmissibility(source_slug=source.slug, findings=tuple(findings))
