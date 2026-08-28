"""Run ``docs/backlog.md``'s own header check against the **merged** file.

``scripts/backlog_graph.py`` already answers "does this file's headline count
describe this file". The open question is *which* file it is handed, and there
is one arrangement where the answer is the wrong one.

**What is already covered, so this script does not claim it.** CI triggers on
``pull_request`` as well as ``push``, and ``actions/checkout@v4`` is used with no
``ref:`` override, so the ``pull_request`` run is checked out at GitHub's
generated merge commit rather than at the branch head. The ``backlog-graph`` job
on that run therefore does read a merged file. Anyone extending this script
should verify that against a live PR -- fetch ``refs/pull/N/merge`` and compare
it to the branch head -- rather than trusting this paragraph, because the merge
ref stops resolving once the PR closes and the claim then cannot be rechecked.

**What is not covered, which is why this exists.** That merge is computed
against ``main`` *as it was when CI ran*. If ``main`` moves before the PR is
merged -- and on 2026-08-28 it moved three times in an afternoon, at ``ea765c5``,
``4f8724e``, ``39ea327`` and ``fb35201`` -- then the merge that actually happens
is one no job ever evaluated, and nothing re-runs before the button is pressed.
There is also no way to ask the question *before* pushing, which is when it is
cheapest to answer.

**The shape that survives all of it.** Two lanes each file one backlog item.
Each increments the headline count by one, so both write the **byte-identical**
header string. Git does not conflict on a line both sides changed to the same
text, the item additions land in different regions, and the merge is completely
clean -- no human is ever prompted to look. The merged file has two more items
than its header claims, and each branch was individually correct.

That the header is usually caught by a *conflict* is not reassurance, it is
selection bias: those are the cases someone was forced to look at. Twice on
2026-08-28 the conflict fired and the right answer was **neither side** --
``main`` said ``60/0/120/180`` against a branch's ``61/1/117/179``, truth
``61/0/119/180``; then ``main`` said ``62/0/119/181`` against ``61/0/119/180``,
truth ``63/0/118/181``. The silent case has the same arithmetic and no prompt.

This script computes the merge with ``git merge-tree --write-tree``, reads
``docs/backlog.md`` out of the resulting tree, and hands the text to
``backlog_graph.parse_backlog``. It deliberately adds **no second parser**:
every rule it enforces is that module's rule, because a second implementation
of the counting would be a second thing to drift, which is the failure this
repository has found in its own docs more than once.

Why this exists as a file rather than as a paragraph: it was a rule in a lane
brief -- "compute the merge with ``git merge-tree --write-tree`` and recount the
merged file" -- carried only in chat. A rule that lives only in a chat is one
this repository has repeatedly found written down and unenforced, so it is here
instead.

Usage::

    python scripts/merged_backlog_recount.py                 # origin/main vs HEAD
    python scripts/merged_backlog_recount.py --base origin/main --head HEAD

Exit codes: ``0`` the merged file's header describes the merged file; ``1`` it
does not; ``2`` the merge could not be evaluated (conflict, or the file is
absent from the merged tree). ``2`` is **not** a pass -- an unevaluated check
that reported success is the shape every guard here exists to avoid.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKLOG_PATH = "docs/backlog.md"


def load_backlog_graph() -> ModuleType:
    """Import ``backlog_graph`` by path, so the rules have exactly one owner."""
    script = Path(__file__).resolve().parent / "backlog_graph.py"
    spec = importlib.util.spec_from_file_location("backlog_graph", script)
    if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
        raise RuntimeError(f"could not load {script}")
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: ``backlog_graph`` defines dataclasses, and
    # ``@dataclass`` resolves annotations through ``sys.modules[cls.__module__]``.
    # An unregistered module makes that lookup return None and the import dies
    # inside the standard library, several frames from anything that names it.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(args: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    """Run git and return **bytes**.

    Never ``text=True`` and never through a shell pipeline. Both re-encode, and
    a tool that rewrites its sample before measuring it is how a 2 MB file's 149
    CRLF endings got counted as 31,400 on 2026-08-28: PowerShell's ``Out-String``
    turned every LF into CRLF, so the CR count silently became the line count.
    The same class crashed an earlier draft of this script, which decoded git's
    output as cp1252 and died on a non-ASCII byte in the backlog.
    """
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)


def merged_backlog_text(base: str, head: str, *, cwd: Path = REPO_ROOT) -> str:
    """The backlog as it will exist after merging ``head`` into ``base``.

    Raises :class:`LookupError` when the merge cannot be evaluated, which the
    caller must report rather than treat as clean.
    """
    merge = _git(["merge-tree", "--write-tree", base, head], cwd=cwd)
    stdout = merge.stdout.decode("utf-8", errors="replace")
    if merge.returncode != 0:
        detail = (stdout + merge.stderr.decode("utf-8", errors="replace")).strip()
        raise LookupError(
            f"could not merge {base} into {head} cleanly; resolve the conflict "
            f"and re-run, because an unevaluated recount is not a pass.\n{detail[:2000]}"
        )

    tree = stdout.splitlines()[0].strip() if stdout.strip() else ""
    if not tree:
        raise LookupError("git merge-tree produced no tree id")

    blob = _git(["cat-file", "blob", f"{tree}:{BACKLOG_PATH}"], cwd=cwd)
    if blob.returncode != 0:
        raise LookupError(f"{BACKLOG_PATH} is not present in the merged tree {tree}")
    return blob.stdout.decode("utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recount docs/backlog.md from the MERGE of two refs, not from either "
            "branch. Catches a header that was correct on both sides and is wrong "
            "in the file they produce together."
        )
    )
    parser.add_argument("--base", default="origin/main", help="default: origin/main")
    parser.add_argument("--head", default="HEAD", help="default: HEAD")
    parser.add_argument("--repo", default=str(REPO_ROOT), help="repository to inspect")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    try:
        text = merged_backlog_text(args.base, args.head, cwd=repo)
    except LookupError as exc:
        print(f"COULD NOT EVALUATE: {exc}")
        return 2

    graph = load_backlog_graph()
    items, defects = graph.parse_backlog(text)

    print(f"merged {args.base} <- {args.head}")
    print(f"  merged {BACKLOG_PATH}: {len(items)} items")
    counts = dict.fromkeys(sorted(graph.KNOWN_STATUSES), 0)
    for item in items:
        if item.status in counts:
            counts[item.status] += 1
    print("  " + ", ".join(f"{value} {key}" for key, value in counts.items()))

    header_defects = [d for d in defects if "header" in d.kind]
    if header_defects:
        print()
        for defect in header_defects:
            where = f"line {defect.line}: " if defect.line else ""
            print(f"  FAIL [{defect.kind}] {where}{defect.message}")
        print()
        print(
            "Recount from the MERGED file above and correct the header on your "
            "branch. Never reconcile the two branches' headers against each "
            "other: on 2026-08-28 the right answer was neither side, twice."
        )
        return 1

    other = [d for d in defects if "header" not in d.kind]
    if other:
        print()
        print(f"  note: {len(other)} non-header defect(s) in the merged file:")
        for defect in other[:10]:
            print(f"    [{defect.kind}] {defect.message[:160]}")
        print("  These are backlog_graph's to fail on; this script checks the header.")

    print()
    print("OK: the merged file's header describes the merged file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
