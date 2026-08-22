#!/usr/bin/env python3
"""Resolve `docs/backlog.md`'s dependency graph, and fail on edges that cannot be true.

Runs in CI and is runnable locally:

    python scripts/backlog_graph.py
    python scripts/backlog_graph.py --summary "$GITHUB_STEP_SUMMARY"

``AGENTS.md`` defines a task as ready when every dependency is done, and
``docs/backlog.md`` carries a machine-readable ``- **Depends on:**`` line under
every item. Until this script existed, **nothing resolved one against the
other**, and in a single day that produced three separate failures:

1. ``schedule-cohort-fingerprint-list`` depended on ``injury-report-backfill``,
   which is not a slug in the file. A dangling edge is invisible to a reader
   scanning 122 items in file order, and it silently removes a real constraint.
2. ``availability-model`` carried prose saying it was blocked while its edges
   named only ``done`` items. Human-readable said blocked, machine-readable
   said ready.
3. The whole auction capability sat ten dependencies behind one unstarted item,
   and that was found by someone writing a throwaway script while looking for
   something else.

**What fails and what only prints, and why the line is there.**

A check fails only where the file asserts something that *cannot be true* and
exactly one edit makes it true: an edge naming an item that does not exist, a
cycle, a self-edge, a duplicated slug, an item with no status, a heading the
parser cannot read, or a `done` item resting on one that is not done.

Everything about the *shape* of the remaining work — path lengths, the ready
set, what a given item unblocks — is printed and never fails. The reason is not
that a long path is unimportant; it is that no edit to the backlog legitimately
shortens one. The only changes that would turn such a job green are deleting an
edge or misreporting a status, so the guard's own remedy would be falsifying
the data it reads. A guard like that is worse than absent.

**What this cannot do, stated because the printed output invites the
assumption.** It cannot detect failure 2 above. Distinguishing prose that
contradicts its own edges from prose that agrees with them requires reading
English. What it does instead is print the ready set, so a human reads
"``availability-model``: ready" and contradicts it. That is visibility, not
detection, and the distinction matters — this script would have caught failures
1 and 3 outright and would only have *shown someone* failure 2.

Exit code 1 means a defect was found. Exit code 0 means every edge resolved.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKLOG = REPO_ROOT / "docs" / "backlog.md"

#: ``### `slug` - Title``. The slug pattern is deliberately permissive: an
#: unconventional slug is still a real item, and dropping it from the graph for
#: being oddly named is precisely the silent loss this file exists to prevent.
HEADING_RE = re.compile(r"^### +`([^`]+)`(.*)$")
#: Any other ``### `` line. Not an item, and not something to pass over quietly.
ANY_H3_RE = re.compile(r"^### ")
#: ``- [x] **done**``, optionally followed by a dated note.
STATUS_RE = re.compile(r"^- \[([ x])\] \*\*([a-z]+)\*\*")
DEPENDS_PREFIX = "- **Depends on:**"
#: Dependencies are always backtick-quoted, which is what lets one item write
#: prose around them (``player-position-eligibility`` explains why half of it
#: depends on nothing) without the prose being read as an edge.
TOKEN_RE = re.compile(r"`([^`]+)`")

DONE = "done"
KNOWN_STATUSES = frozenset({DONE, "pending", "blocked"})


@dataclass(frozen=True)
class Item:
    """One backlog entry."""

    slug: str
    title: str
    status: str
    depends_on: tuple[str, ...]
    line: int


@dataclass(frozen=True)
class Defect:
    """Something the file claims that cannot be true."""

    kind: str
    message: str
    line: int | None = None

    def render(self) -> str:
        where = f"line {self.line}: " if self.line is not None else ""
        return f"[{self.kind}] {where}{self.message}"


@dataclass(frozen=True)
class Analysis:
    """The printed half. None of this can fail the build."""

    ready: tuple[str, ...]
    blocked: tuple[str, ...]
    unblocks: tuple[tuple[str, int], ...]
    chains: tuple[tuple[str, ...], ...]


def parse_backlog(text: str) -> tuple[list[Item], list[Defect]]:
    """Split the backlog into items, reporting anything unreadable as a defect.

    Returns items in file order. A heading that cannot be parsed is reported
    rather than skipped: an item that vanishes from the graph takes its
    constraints with it, and the graph then looks *cleaner* than the truth.
    """
    lines = text.splitlines()
    defects: list[Defect] = []

    starts: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match:
            title = match.group(2).strip().lstrip("-—").strip()
            starts.append((index, match.group(1), title))
        elif ANY_H3_RE.match(line):
            defects.append(
                Defect(
                    "malformed-heading",
                    f"{line.strip()!r} is an item heading the parser cannot read; "
                    "expected '### `slug` - Title'",
                    index + 1,
                )
            )

    items: list[Item] = []
    for position, (index, slug, title) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        body = lines[index:end]
        line_number = index + 1

        status = _parse_status(body, slug, line_number, defects)
        depends_on = _parse_depends(body, slug, line_number, defects)
        items.append(
            Item(
                slug=slug,
                title=title,
                status=status,
                depends_on=depends_on,
                line=line_number,
            )
        )

    return items, defects


def _parse_status(
    body: Sequence[str], slug: str, line: int, defects: list[Defect]
) -> str:
    for candidate in body:
        match = STATUS_RE.match(candidate)
        if not match:
            continue
        checkbox, status = match.group(1), match.group(2)
        if status not in KNOWN_STATUSES:
            defects.append(
                Defect(
                    "unknown-status",
                    f"`{slug}` is marked **{status}**, which is not one of "
                    f"{', '.join(sorted(KNOWN_STATUSES))}",
                    line,
                )
            )
        elif (checkbox == "x") != (status == DONE):
            defects.append(
                Defect(
                    "checkbox-disagrees-with-status",
                    f"`{slug}` has '[{checkbox}]' beside **{status}**; a ticked box "
                    "and a done marker have to agree",
                    line,
                )
            )
        return status

    defects.append(
        Defect("missing-status", f"`{slug}` has no '- [ ] **status**' marker", line)
    )
    return "unknown"


def _parse_depends(
    body: Sequence[str], slug: str, line: int, defects: list[Defect]
) -> tuple[str, ...]:
    found = [candidate for candidate in body if candidate.startswith(DEPENDS_PREFIX)]
    if len(found) > 1:
        defects.append(
            Defect(
                "duplicate-depends-line",
                f"`{slug}` has {len(found)} 'Depends on:' lines; which one is "
                "authoritative is unanswerable",
                line,
            )
        )
    if not found:
        return ()
    return tuple(TOKEN_RE.findall(found[0]))


def find_defects(items: Sequence[Item]) -> list[Defect]:
    """Every graph-level claim that cannot be true.

    The empty-set guard comes first and is not a formality. A parser that
    silently stops matching returns no items, every loop below iterates over
    nothing, and the run reports a clean graph — which is the exact shape of
    failure this repository keeps finding in its verification tools rather than
    in its code.
    """
    if not items:
        return [
            Defect(
                "no-items",
                "no backlog items parsed at all. Either the file is empty or its "
                "item format changed under this parser; both make every check "
                "below vacuous",
            )
        ]

    defects: list[Defect] = []
    by_slug: dict[str, Item] = {}
    for slug, count in Counter(item.slug for item in items).items():
        if count > 1:
            lines = ", ".join(str(i.line) for i in items if i.slug == slug)
            defects.append(
                Defect(
                    "duplicate-slug",
                    f"`{slug}` is defined {count} times (lines {lines}); an edge "
                    "naming it cannot say which is meant",
                )
            )
    for item in items:
        by_slug.setdefault(item.slug, item)

    for item in items:
        for dependency in item.depends_on:
            if dependency == item.slug:
                defects.append(
                    Defect(
                        "self-dependency",
                        f"`{item.slug}` depends on itself",
                        item.line,
                    )
                )
            elif dependency not in by_slug:
                defects.append(
                    Defect(
                        "dangling-dependency",
                        f"`{item.slug}` depends on `{dependency}`, which is not an "
                        "item in this file",
                        item.line,
                    )
                )

    defects.extend(_find_cycles(by_slug))

    for item in items:
        if item.status != DONE:
            continue
        for dependency in item.depends_on:
            blocker = by_slug.get(dependency)
            if blocker is not None and blocker.status != DONE:
                defects.append(
                    Defect(
                        "done-rests-on-unfinished",
                        f"`{item.slug}` is **done** but depends on `{dependency}`, "
                        f"which is **{blocker.status}**; one of the two is wrong. "
                        "Resolve by correcting whichever status is untrue - not by "
                        "deleting the edge, which turns this green by erasing the "
                        "record that the work was ever related",
                        item.line,
                    )
                )

    return defects


def _find_cycles(by_slug: Mapping[str, Item]) -> list[Defect]:
    """Iterative depth-first search, so a deep chain cannot exhaust the stack."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(by_slug, WHITE)
    defects: list[Defect] = []
    seen: set[tuple[str, ...]] = set()

    for root in by_slug:
        if colour[root] != WHITE:
            continue
        path: list[str] = []
        stack: list[tuple[str, Iterable[str]]] = [(root, iter(_edges(by_slug, root)))]
        colour[root] = GREY
        path.append(root)
        while stack:
            node, edges = stack[-1]
            advanced = False
            for nxt in edges:
                if colour[nxt] == GREY:
                    cycle = tuple(path[path.index(nxt) :]) + (nxt,)
                    if cycle not in seen:
                        seen.add(cycle)
                        defects.append(
                            Defect(
                                "cycle",
                                "dependency cycle: " + " -> ".join(f"`{c}`" for c in cycle),
                                by_slug[nxt].line,
                            )
                        )
                elif colour[nxt] == WHITE:
                    colour[nxt] = GREY
                    path.append(nxt)
                    stack.append((nxt, iter(_edges(by_slug, nxt))))
                    advanced = True
                    break
            if not advanced:
                colour[node] = BLACK
                path.pop()
                stack.pop()

    return defects


def _edges(by_slug: Mapping[str, Item], slug: str) -> list[str]:
    """Resolvable edges only. Dangling ones are already reported as defects."""
    return [d for d in by_slug[slug].depends_on if d in by_slug and d != slug]


def analyse(items: Sequence[Item], *, chain_limit: int = 10) -> Analysis:
    """The shape of the remaining work. Never fails; see the module docstring."""
    by_slug = {item.slug: item for item in items}
    unfinished = [i.slug for i in items if i.status != DONE]

    # `pending`, not merely "not done". `blind-mocks` is marked **blocked** and
    # has no dependencies at all, so a rule of "every dependency is done" calls
    # it ready — while the file says in the same breath that no site currently
    # offers the auction mocks it needs. Reporting it as ready would have been
    # this script committing the exact defect it prints the ready set to expose:
    # a machine-readable claim contradicting the prose beside it.
    ready = tuple(
        sorted(
            item.slug
            for item in items
            if item.status == "pending"
            and all(by_slug[d].status == DONE for d in _edges(by_slug, item.slug))
        )
    )

    longest = _longest_chains(by_slug, unfinished)
    chains = tuple(
        sorted(longest.values(), key=lambda chain: (-len(chain), chain[0]))[:chain_limit]
    )

    downstream: Counter[str] = Counter()
    for slug in unfinished:
        for reached in _reachable(by_slug, slug):
            if reached != slug:
                downstream[reached] += 1
    unblocks = tuple(
        sorted(
            ((slug, downstream.get(slug, 0)) for slug in ready),
            key=lambda pair: (-pair[1], pair[0]),
        )
    )

    return Analysis(
        ready=ready,
        blocked=tuple(sorted(i.slug for i in items if i.status == "blocked")),
        unblocks=unblocks,
        chains=chains,
    )


def _longest_chains(
    by_slug: Mapping[str, Item], unfinished: Sequence[str]
) -> dict[str, tuple[str, ...]]:
    """Longest chain of not-done dependencies beneath each not-done item.

    Iterative post-order, for the same stack-safety reason as the cycle search.
    Callers must have established the graph is acyclic first.
    """
    memo: dict[str, tuple[str, ...]] = {}
    pending = set(unfinished)

    for start in unfinished:
        if start in memo:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            slug, expanded = stack.pop()
            if slug in memo:
                continue
            children = [d for d in _edges(by_slug, slug) if d in pending]
            if not expanded:
                stack.append((slug, True))
                stack.extend((child, False) for child in children if child not in memo)
                continue
            best: tuple[str, ...] = ()
            for child in children:
                candidate = memo[child]
                if len(candidate) > len(best):
                    best = candidate
            memo[slug] = (slug,) + best

    return memo


def _reachable(by_slug: Mapping[str, Item], start: str) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        slug = stack.pop()
        if slug in seen:
            continue
        seen.add(slug)
        stack.extend(_edges(by_slug, slug))
    return seen


def render_report(
    items: Sequence[Item], defects: Sequence[Defect], analysis: Analysis, source: Path
) -> str:
    """Markdown, so the same text works on a terminal and in a job summary."""
    counts = Counter(item.status for item in items)
    tally = ", ".join(f"{counts[s]} {s}" for s in sorted(counts))
    out: list[str] = [
        "## Backlog dependency graph",
        "",
        f"`{source.as_posix()}` - **{len(items)} items** ({tally}).",
        "",
    ]

    out.append("### Defects")
    out.append("")
    if defects:
        out.append(f"**{len(defects)} found.** Each is an edge or a status that cannot be true.")
        out.append("")
        out.extend(f"- {defect.render()}" for defect in defects)
    else:
        out.append(
            "None of the kind this job can see: every dependency resolves to an item in "
            "the file, no cycles, no status contradicting its own checkbox. That is a "
            "narrow claim. It is **not** a statement that the backlog is accurate - an "
            "item whose prose says it is blocked while its `Depends on:` line names only "
            "finished work is well-formed, and passes here silently."
        )
    out.append("")

    out.append(f"### Ready - every dependency done ({len(analysis.ready)})")
    out.append("")
    unresolved = [d for d in defects if d.kind == "dangling-dependency"]
    if unresolved:
        out.append(
            f"**Computed on an unsound graph.** {len(unresolved)} dependency token(s) "
            "above name an item that does not exist, and an edge that resolves to "
            "nothing is an edge that constrains nothing. Any item carrying one has had "
            "a real constraint silently dropped, so it may appear here **only because "
            "the file is broken**. Fix the dangling edge, then read this list."
        )
        out.append("")
    out.append(
        "Read this list against what you believe. It is the only place a status note "
        "that contradicts its own `Depends on:` line becomes visible, and nothing here "
        "can detect that contradiction for you."
    )
    out.append("")
    out.extend(f"- `{slug}`" for slug in analysis.ready)
    out.append("")

    if analysis.blocked:
        out.append(f"### Blocked ({len(analysis.blocked)})")
        out.append("")
        out.append(
            "Marked **blocked** in the file. Deliberately not in the ready list above, "
            "even where every dependency is done."
        )
        out.append("")
        out.extend(f"- `{slug}`" for slug in analysis.blocked)
        out.append("")

    out.append("### What starting a ready item would unblock")
    out.append("")
    out.append("| ready item | unfinished items waiting behind it |")
    out.append("| --- | --- |")
    out.extend(f"| `{slug}` | {count} |" for slug, count in analysis.unblocks)
    out.append("")

    out.append("### Deepest remaining chains")
    out.append("")
    out.append(
        "Longest path of unfinished dependencies beneath each unfinished item. "
        "Printed, never failed: no honest edit to the backlog shortens one of these."
    )
    out.append("")
    for chain in analysis.chains:
        arrow = " <- ".join(f"`{slug}`" for slug in chain)
        out.append(f"- **{len(chain)} deep** - {arrow}")
    out.append("")

    return "\n".join(out)


def _safe_stdout() -> None:
    """A malformed-heading defect quotes the offending line verbatim.

    That line is arbitrary file content, and printing it through a cp1252
    Windows console can raise ``UnicodeEncodeError`` -- which would report a
    crash where the script had in fact done its job and found a defect.
    """
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="backslashreplace")


def main(argv: Sequence[str] | None = None) -> int:
    _safe_stdout()
    # A short ASCII description rather than __doc__: --help is printed through
    # whatever encoding the console has, and this script has to run on a
    # cp1252 Windows terminal as well as a CI runner.
    parser = argparse.ArgumentParser(
        description="Resolve docs/backlog.md's dependency graph; fail on edges that cannot be true."
    )
    parser.add_argument(
        "backlog",
        nargs="?",
        type=Path,
        default=DEFAULT_BACKLOG,
        help="path to the backlog (default: docs/backlog.md)",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="also append the report here, e.g. $GITHUB_STEP_SUMMARY",
    )
    parser.add_argument(
        "--chain-limit",
        type=int,
        default=10,
        help="how many of the deepest chains to print (default: 10)",
    )
    args = parser.parse_args(argv)

    source: Path = args.backlog
    if not source.is_file():
        print(f"error: {source} does not exist", file=sys.stderr)
        return 1

    items, defects = parse_backlog(source.read_text(encoding="utf-8"))
    defects = list(defects) + find_defects(items)

    fatal = {d.kind for d in defects} & {"no-items", "duplicate-slug", "cycle"}
    analysis = (
        Analysis((), (), (), ())
        if fatal
        else analyse(items, chain_limit=args.chain_limit)
    )

    report = render_report(items, defects, analysis, source)
    print(report)
    sys.stdout.flush()
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(report + "\n")

    if defects:
        print(
            f"\nFAILED: {len(defects)} defect(s) in {source.as_posix()}.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
