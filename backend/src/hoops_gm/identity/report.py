"""The unmatched-players report.

The tail is where identity resolution fails, and it fails quietly: a player who
matches wrongly produces confident, plausible, wrong numbers everywhere
downstream and looks like a modelling bug for weeks. So the resolver is
required to hand a human a list, and the list has to say *why* — which is what
the per-field evidence is for.

Three sections, because they need three different actions:

**Ambiguous** — a good match exists but a nearly-as-good one also exists. This
is the dangerous section and it is printed first. Two people share a name and
the resolver refused to guess.

**Low confidence** — one plausible candidate, not strong enough to accept.
Usually a genuine match missing corroboration, most often because Fantrax gave
``"(N/A)"`` for the team.

**No candidate** — nothing shares a name key at all. Usually a player who is
not in the other source: a two-way contract, a summer-league invitee, someone
who retired.

Written as text rather than a UI. The plan lists a manual-override UI for this
item; that is a `frontend` surface over the same data, and the resolver's job
is to produce the data and the reasons. Shipping the report first means the
tail is adjudicable now rather than after another phase.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence

from hoops_gm.identity.resolver import Resolution, ResolutionReport

#: Columns of the CSV a human edits to adjudicate the tail. ``decision`` and
#: ``chosen_target_key`` are the two a person fills in; everything else is
#: context. The evidence columns are the reason this is adjudicable at all.
REVIEW_COLUMNS = (
    "source_key",
    "source_name",
    "source_team",
    "source_position",
    "suggested_target_key",
    "suggested_target_name",
    "suggested_target_team",
    "confidence",
    "name_evidence",
    "team_evidence",
    "position_evidence",
    "suffix_evidence",
    "runner_up_key",
    "runner_up_name",
    "runner_up_confidence",
    "reason",
    "decision",
    "chosen_target_key",
)


def _row(resolution: Resolution) -> dict[str, str]:
    best = resolution.best
    runner_up = resolution.runner_up
    evidence = resolution.evidence
    return {
        "source_key": resolution.source_record.key,
        "source_name": resolution.source_record.raw_name,
        "source_team": resolution.source_record.team or "",
        "source_position": resolution.source_record.position or "",
        "suggested_target_key": best.target.key if best else "",
        "suggested_target_name": best.target.raw_name if best else "",
        "suggested_target_team": (best.target.team or "") if best else "",
        "confidence": f"{resolution.confidence:.4f}",
        "name_evidence": evidence.name.value,
        "team_evidence": evidence.team.value,
        "position_evidence": evidence.position.value,
        "suffix_evidence": evidence.suffix.value,
        "runner_up_key": runner_up.target.key if runner_up else "",
        "runner_up_name": runner_up.target.raw_name if runner_up else "",
        "runner_up_confidence": f"{runner_up.confidence:.4f}" if runner_up else "",
        "reason": resolution.reason,
        # Left blank for a human. An empty decision means "not yet looked at",
        # which is different from a decision to reject, and the difference is
        # why the column is not defaulted.
        "decision": "",
        "chosen_target_key": "",
    }


def is_ambiguous(resolution: Resolution) -> bool:
    """Two candidates the resolver could not separate, in either direction.

    ``ambiguous:`` is one source row that matched two players equally well.
    ``collision:`` is two source rows that both claimed one player. Different
    shapes, same required action: a human chooses.
    """
    return resolution.reason.startswith(("ambiguous:", "collision:"))


def partition(
    report: ResolutionReport,
) -> tuple[list[Resolution], list[Resolution], list[Resolution]]:
    """Split the non-accepted resolutions into the three actionable groups."""
    ambiguous = [r for r in report.needs_review if is_ambiguous(r)]
    low_confidence = [r for r in report.needs_review if not is_ambiguous(r)]
    return ambiguous, low_confidence, list(report.unmatched)


def to_csv(resolutions: Sequence[Resolution]) -> str:
    """Render resolutions as the CSV a human edits to adjudicate them."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(REVIEW_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for resolution in resolutions:
        writer.writerow(_row(resolution))
    return buffer.getvalue()


def render_summary(report: ResolutionReport, *, source_label: str = "source") -> str:
    """A short human-readable summary, for a log line or a handoff entry."""
    ambiguous, low_confidence, no_candidate = partition(report)
    lines = [
        f"Identity resolution for {source_label}: {report.total} records",
        f"  accepted automatically : {len(report.accepted):5d}  ({report.match_rate:.1%})",
        f"  ambiguous, need a human: {len(ambiguous):5d}",
        f"  low confidence         : {len(low_confidence):5d}",
        f"  no candidate at all    : {len(no_candidate):5d}",
    ]
    if ambiguous:
        lines.append("")
        lines.append("  Ambiguous — two candidates too close to separate:")
        for resolution in ambiguous[:20]:
            best = resolution.best
            runner_up = resolution.runner_up
            lines.append(
                f"    {resolution.source_record.raw_name!r} "
                f"-> {best.target.raw_name!r} @ {best.confidence:.2f} "
                f"vs {runner_up.target.raw_name!r} @ {runner_up.confidence:.2f}"
                if best and runner_up
                else f"    {resolution.source_record.raw_name!r}"
            )
        if len(ambiguous) > 20:
            lines.append(f"    ... and {len(ambiguous) - 20} more")
    return "\n".join(lines)
