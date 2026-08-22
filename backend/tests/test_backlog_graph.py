"""Tests for ``scripts/backlog_graph.py``.

Written before the script was wired into CI, because the alternative is the
class this repository keeps finding: a verification tool that examines an empty
set and reports success. Several tests below exist specifically to make that
impossible here.

Three of them are worth naming.

``test_a_backlog_with_no_items_fails`` and its siblings point the parser at
input holding nothing to iterate over, and assert it **fails** rather than
printing a clean graph. Every other check in the script is vacuous if that one
regresses.

``test_the_real_backlog_is_clean`` asserts against `docs/backlog.md` itself, and
the two mutation tests beside it exist because that assertion alone would be
**accurate and non-independent** — it would keep passing if the parser quietly
stopped recognising the file's format. They take the real file, break it in one
specific way, and require the checker to notice. That is the "delete the source
of truth and see whether it notices" discipline applied to a parser.

``test_the_historical_dangling_edge_is_caught`` reproduces the actual defect
from 2026-08-21: ``schedule-cohort-fingerprint-list`` depending on
``injury-report-backfill``, an item that does not exist.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backlog_graph.py"
REAL_BACKLOG = Path(__file__).resolve().parents[2] / "docs" / "backlog.md"


@pytest.fixture(scope="module")
def graph() -> ModuleType:
    spec = importlib.util.spec_from_file_location("backlog_graph", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- building synthetic backlogs --------------------------------------------


def item(
    slug: str,
    status: str = "pending",
    deps: Sequence[str] = (),
    *,
    depends_line: str | None = None,
    body: str = "Some prose about the item.",
) -> str:
    box = "x" if status == "done" else " "
    lines = [f"### `{slug}` - Doing {slug}", "", f"- [{box}] **{status}**"]
    if depends_line is not None:
        lines.append(depends_line)
    elif deps:
        lines.append("- **Depends on:** " + ", ".join(f"`{d}`" for d in deps))
    lines += ["", body, ""]
    return "\n".join(lines)


def backlog(*items: str, header: str = "# Build backlog\n\nSome preamble.\n\n") -> str:
    return header + "\n".join(items)


def kinds(defects: Sequence[object]) -> list[str]:
    return [d.kind for d in defects]  # type: ignore[attr-defined]


def check(graph: ModuleType, text: str) -> list[object]:
    """Parse defects and graph defects together, as ``main`` combines them."""
    items, parse_defects = graph.parse_backlog(text)
    found: list[object] = list(parse_defects)
    found.extend(graph.find_defects(items))
    return found


# --- the empty-set guard, which every other test depends on -----------------


def test_a_backlog_with_no_items_fails(graph: ModuleType) -> None:
    """The one that stops every other check from being vacuous.

    A parser that stops matching the file's format returns nothing, every loop
    iterates over an empty set, and the run reports a clean graph.
    """
    assert kinds(check(graph, "")) == ["no-items"]


def test_a_backlog_of_prose_with_no_items_fails(graph: ModuleType) -> None:
    text = "# Build backlog\n\n45 done - 1 blocked - 76 pending - 122 total\n\nProse only.\n"
    assert kinds(check(graph, text)) == ["no-items"]


def test_a_file_whose_headings_stopped_matching_fails(graph: ModuleType) -> None:
    """Format drift must be loud, not silent.

    If the heading convention changed to '## slug' tomorrow, the parser would
    find nothing. It must say so rather than report 0 defects over 0 items.
    """
    text = "# Build backlog\n\n## `some-item` - Doing it\n\n- [ ] **pending**\n"
    assert "no-items" in kinds(check(graph, text))


def test_a_heading_the_parser_cannot_read_is_reported_not_skipped(
    graph: ModuleType,
) -> None:
    """A dropped item takes its constraints with it and the graph looks cleaner.

    This is the same shape as a dropped backlog entry surviving a rebase: the
    finished file agrees with itself perfectly after a loss.
    """
    text = backlog(item("real-item"), "### Doing something without a slug\n\n- [ ] **pending**\n")
    assert "malformed-heading" in kinds(check(graph, text))


def test_a_subheading_inside_an_item_is_not_mistaken_for_one(graph: ModuleType) -> None:
    """`player-position-eligibility` really does carry '#### ' subheadings."""
    text = backlog(item("thing", body="#### A half that landed\n\nDetail."))
    items, defects = graph.parse_backlog(text)

    assert [i.slug for i in items] == ["thing"]
    assert defects == []


# --- the real file, plus the mutations that keep those claims independent ---


def test_the_real_backlog_parses_a_populated_item_set(graph: ModuleType) -> None:
    """Assert the presence expected, not merely the absence of defects."""
    items, _ = graph.parse_backlog(REAL_BACKLOG.read_text(encoding="utf-8"))

    assert len(items) > 100, "the real backlog holds ~122 items; this found almost none"
    slugs = {i.slug for i in items}
    assert "availability-model" in slugs
    assert "injury-report-historical-backfill" in slugs
    assert all(i.status in {"done", "pending", "blocked"} for i in items)
    assert any(i.depends_on for i in items), "no item parsed a single dependency"


def test_the_real_backlog_is_clean(graph: ModuleType) -> None:
    found = check(graph, REAL_BACKLOG.read_text(encoding="utf-8"))
    assert found == [], "\n".join(d.render() for d in found)  # type: ignore[attr-defined]


def test_breaking_one_real_edge_is_noticed(graph: ModuleType) -> None:
    """Independence check for the test above.

    An assertion that `docs/backlog.md` is clean would keep passing if the
    parser stopped resolving edges at all. This one requires that the checker
    is genuinely reading the real file's dependencies.
    """
    text = REAL_BACKLOG.read_text(encoding="utf-8")
    broken = text.replace("`participation-ledger`", "`participation-ledgerr`", 1)
    assert broken != text, "the token this test mutates is no longer in the backlog"

    assert "dangling-dependency" in kinds(check(graph, broken))


def test_deleting_every_real_item_is_noticed(graph: ModuleType) -> None:
    """Delete the source of truth and see whether it notices."""
    text = REAL_BACKLOG.read_text(encoding="utf-8")
    header = text.split("### `", 1)[0]
    assert header.strip(), "expected the backlog to have a header before its first item"

    assert kinds(check(graph, header)) == ["no-items"]


# --- defects that must fail --------------------------------------------------


def test_the_historical_dangling_edge_is_caught(graph: ModuleType) -> None:
    """The actual defect of 2026-08-21, reproduced.

    ``injury-report-backfill`` was never a slug; the item is
    ``injury-report-historical-backfill``.
    """
    text = backlog(
        item("injury-report-historical-backfill", "done"),
        item("schedule-cohort-fingerprint-list", deps=["injury-report-backfill"]),
    )
    found = check(graph, text)

    assert kinds(found) == ["dangling-dependency"]
    assert "injury-report-backfill" in found[0].render()  # type: ignore[attr-defined]


def test_a_self_dependency_is_caught(graph: ModuleType) -> None:
    assert kinds(check(graph, backlog(item("loop", deps=["loop"])))) == ["self-dependency"]


def test_a_two_item_cycle_is_caught(graph: ModuleType) -> None:
    text = backlog(item("a", deps=["b"]), item("b", deps=["a"]))
    assert "cycle" in kinds(check(graph, text))


def test_a_longer_cycle_is_caught(graph: ModuleType) -> None:
    text = backlog(item("a", deps=["b"]), item("b", deps=["c"]), item("c", deps=["a"]))
    found = [d for d in check(graph, text) if d.kind == "cycle"]  # type: ignore[attr-defined]

    assert found, "a three-item cycle went unreported"
    rendered = found[0].render()  # type: ignore[attr-defined]
    assert "`a`" in rendered and "`b`" in rendered and "`c`" in rendered


def test_a_cycle_reachable_only_from_a_later_root_is_caught(graph: ModuleType) -> None:
    """Depth-first colouring has to survive being entered from outside the cycle."""
    text = backlog(
        item("entry", deps=["a"]),
        item("a", deps=["b"]),
        item("b", deps=["a"]),
    )
    assert "cycle" in kinds(check(graph, text))


def test_a_duplicate_slug_is_caught(graph: ModuleType) -> None:
    """The rebase defect: both sides of a hunk taken, leaving a bare duplicate."""
    text = backlog(item("schedule-grid-ui"), item("schedule-grid-ui", "done"))
    assert "duplicate-slug" in kinds(check(graph, text))


def test_an_item_with_no_status_marker_is_caught(graph: ModuleType) -> None:
    text = backlog("### `orphan` - Doing orphan\n\nProse with no checkbox.\n")
    assert "missing-status" in kinds(check(graph, text))


def test_an_unknown_status_is_caught(graph: ModuleType) -> None:
    text = backlog("### `odd` - Doing odd\n\n- [ ] **maybe**\n")
    assert "unknown-status" in kinds(check(graph, text))


def test_a_ticked_box_beside_a_pending_marker_is_caught(graph: ModuleType) -> None:
    text = backlog("### `odd` - Doing odd\n\n- [x] **pending**\n")
    assert "checkbox-disagrees-with-status" in kinds(check(graph, text))


def test_two_depends_lines_in_one_item_are_caught(graph: ModuleType) -> None:
    text = backlog(
        item("a", "done"),
        item("b", "done"),
        "### `c` - Doing c\n\n- [ ] **pending**\n- **Depends on:** `a`\n- **Depends on:** `b`\n",
    )
    assert "duplicate-depends-line" in kinds(check(graph, text))


def test_a_done_item_resting_on_an_unfinished_one_is_caught(graph: ModuleType) -> None:
    """A contradiction, not a judgement: one of the two markers is wrong."""
    text = backlog(item("base"), item("built-on-it", "done", deps=["base"]))
    found = check(graph, text)

    assert kinds(found) == ["done-rests-on-unfinished"]


def test_a_done_item_resting_on_a_blocked_one_is_caught(graph: ModuleType) -> None:
    text = backlog(item("base", "blocked"), item("built-on-it", "done", deps=["base"]))
    assert "done-rests-on-unfinished" in kinds(check(graph, text))


def test_a_clean_backlog_reports_nothing(graph: ModuleType) -> None:
    """The other half of every test above: no crying wolf on a correct file."""
    text = backlog(
        item("root", "done"),
        item("middle", "done", deps=["root"]),
        item("leaf", deps=["middle"]),
        item("stalled", "blocked", deps=["middle"]),
    )
    assert check(graph, text) == []


def test_a_clean_report_states_the_limit_of_what_it_checked(graph: ModuleType) -> None:
    """ "No defects" is the sentence most likely to be over-read.

    The failure this guards is R61 in a CI job: a reader sees a green tick and
    a bare "None", and infers the backlog is *correct* rather than merely
    well-formed. It is not. An item whose prose says it is blocked while its
    `Depends on:` line names only finished work passes here silently -- that is
    exactly what happened to `availability-model`, and no parser can catch it
    without reading English.

    So the clean branch must say what it did not check, in the job's own
    output, not only in a docstring or a pull request nobody re-reads.
    """
    text = backlog(item("root", "done"), item("leaf", deps=["root"]))
    items, _ = graph.parse_backlog(text)
    report = graph.render_report(items, [], graph.analyse(items), Path("backlog.md"))

    head, _, _ = report.partition("### Ready")
    assert "Depends on:" in head, "the clean report never names the case it cannot see"
    assert "narrow claim" in head, "the clean report does not bound what it verified"
    # A bare "None." is the specific regression: it reads as a clean bill of health.
    assert "None." not in head, "the clean report still makes an unbounded negative claim"


def test_the_ready_list_disclaims_detection_in_the_report_itself(graph: ModuleType) -> None:
    """Printing the ready set is visibility, not detection, and must say so.

    A reader who takes this list as *verified* has been handed a stronger
    guarantee than exists.
    """
    text = backlog(item("root", "done"), item("leaf", deps=["root"]))
    items, _ = graph.parse_backlog(text)
    report = graph.render_report(items, [], graph.analyse(items), Path("backlog.md"))

    _, _, ready_section = report.partition("### Ready")
    assert "detect" in ready_section, "the ready list does not disclaim detection"


def test_the_ready_list_is_caveated_when_an_edge_dangles(graph: ModuleType) -> None:
    """A reviewer's finding: readiness computed on a graph declared unsound.

    A dangling edge is not fatal, so analysis still runs -- and `_edges()` drops
    the unresolvable token silently. The item whose constraint just vanished is
    then printed under "Ready - every dependency done", with a ready set
    identical to the clean file's.

    The build is red, so it is not a false green. But `--summary` exists
    because the summary is what actually gets read, and it asserted readiness
    on a graph the tool called broken three lines above. Caveat rather than
    suppress: killing the analysis would discard the ready list for every
    correct item because one edge is wrong.
    """
    text = backlog(
        item("root", "done"),
        item("leaf", deps=["root", "does-not-exist"]),
    )
    items, parse_defects = graph.parse_backlog(text)
    defects = list(parse_defects) + graph.find_defects(items)
    assert any(d.kind == "dangling-dependency" for d in defects), "fixture built no dangling edge"

    report = graph.render_report(items, defects, graph.analyse(items), Path("backlog.md"))
    _, _, ready_section = report.partition("### Ready")

    assert "unsound" in ready_section, "readiness is asserted over a graph known to be broken"
    assert "`leaf`" in ready_section, "the caveat swallowed the list instead of qualifying it"


def test_a_clean_file_carries_no_unsound_caveat(graph: ModuleType) -> None:
    """The other half: a caveat on every run is a caveat nobody reads."""
    text = backlog(item("root", "done"), item("leaf", deps=["root"]))
    items, _ = graph.parse_backlog(text)
    report = graph.render_report(items, [], graph.analyse(items), Path("backlog.md"))

    assert "unsound" not in report


def test_the_done_rests_on_unfinished_message_warns_against_the_erasing_fix(
    graph: ModuleType,
) -> None:
    """This guard's cheapest green-making edit is deleting the evidence.

    Every other failing condition here has an unambiguous repair. This one does
    not: an operator can satisfy it by correcting a status, or by deleting the
    edge -- and deleting the edge erases the record that the two items were
    ever related. That is the disqualifier used to argue *against* failing on
    long paths, so the message has to say which repair is meant.
    """
    text = backlog(item("dep"), item("shipped", "done", deps=["dep"]))
    defects = check(graph, text)

    matching = [d for d in defects if d.kind == "done-rests-on-unfinished"]  # type: ignore[attr-defined]
    assert matching, "the fixture did not produce the defect under test"
    assert "deleting the edge" in matching[0].message  # type: ignore[attr-defined]


# --- parsing the awkward real shapes ----------------------------------------


def test_prose_mentioning_depends_on_is_not_read_as_an_edge(graph: ModuleType) -> None:
    """Item bodies really do discuss dependencies in prose.

    ``injury-report-historical-backfill``'s description is a single paragraph
    thousands of characters long containing the words "depends on".
    """
    text = backlog(
        item("a", "done"),
        item(
            "b",
            deps=["a"],
            body="This also depends on the backend emitting `something-else` first.",
        ),
    )
    items, _ = graph.parse_backlog(text)
    by_slug = {i.slug: i for i in items}

    assert by_slug["b"].depends_on == ("a",)


def test_only_backticked_tokens_on_the_depends_line_are_edges(graph: ModuleType) -> None:
    """The ``player-position-eligibility`` shape, which really is in the file."""
    text = backlog(
        item("player-identity", "done"),
        item(
            "player-position-eligibility",
            depends_line=(
                "- **Depends on:** *(nothing, for the NBA-position half - **done**)*; "
                "`player-identity` for the Fantrax-eligibility half"
            ),
        ),
    )
    items, defects = graph.parse_backlog(text)
    by_slug = {i.slug: i for i in items}

    assert by_slug["player-position-eligibility"].depends_on == ("player-identity",)
    assert defects == []


def test_a_status_marker_with_a_trailing_note_still_parses(graph: ModuleType) -> None:
    text = backlog(
        "### `noted` - Doing noted\n\n"
        "- [ ] **pending** - *NBA-position half landed 2026-08-20; the rest outstanding*\n"
    )
    items, defects = graph.parse_backlog(text)

    assert [i.status for i in items] == ["pending"]
    assert defects == []


def test_an_item_with_no_depends_line_is_a_root_not_a_defect(graph: ModuleType) -> None:
    """Four real items have none: they are genuinely unblocked."""
    items, defects = graph.parse_backlog(backlog(item("repo-create", "done")))

    assert items[0].depends_on == ()
    assert defects == []


# --- the printed half, which must never fail --------------------------------


def test_ready_means_pending_with_every_dependency_done(graph: ModuleType) -> None:
    text = backlog(
        item("done-dep", "done"),
        item("open-dep"),
        item("is-ready", deps=["done-dep"]),
        item("not-ready", deps=["done-dep", "open-dep"]),
    )
    items, _ = graph.parse_backlog(text)
    analysis = graph.analyse(items)

    assert "is-ready" in analysis.ready
    assert "not-ready" not in analysis.ready
    assert "open-dep" in analysis.ready, "an item with no dependencies at all is ready"


def test_a_blocked_item_is_never_reported_ready(graph: ModuleType) -> None:
    """`blind-mocks` is **blocked** and depends on nothing.

    A rule of "every dependency is done" calls that ready, while the file says
    in the same breath that no site offers the auction mocks it needs. Getting
    this wrong would have made the script's own output the kind of claim it
    prints the ready set to expose.
    """
    text = backlog(item("done-dep", "done"), item("blind-mocks", "blocked", deps=["done-dep"]))
    items, _ = graph.parse_backlog(text)
    analysis = graph.analyse(items)

    assert analysis.ready == ()
    assert analysis.blocked == ("blind-mocks",)


def test_the_longest_chain_is_the_longest_chain(graph: ModuleType) -> None:
    text = backlog(
        item("one"),
        item("two", deps=["one"]),
        item("three", deps=["two"]),
        item("four", deps=["three"]),
        item("shortcut", deps=["one"]),
        item("top", deps=["four", "shortcut"]),
    )
    items, _ = graph.parse_backlog(text)
    analysis = graph.analyse(items)

    assert analysis.chains[0] == ("top", "four", "three", "two", "one")


def test_a_done_dependency_does_not_lengthen_a_chain(graph: ModuleType) -> None:
    """Chains describe remaining work, so finished links are not in them."""
    text = backlog(
        item("finished", "done"),
        item("also-finished", "done", deps=["finished"]),
        item("open", deps=["also-finished"]),
    )
    items, _ = graph.parse_backlog(text)
    analysis = graph.analyse(items)

    assert analysis.chains[0] == ("open",)


def test_unblocks_counts_everything_transitively_waiting(graph: ModuleType) -> None:
    """The number that made the ten-deep auction chain legible."""
    text = backlog(
        item("keystone"),
        item("a", deps=["keystone"]),
        item("b", deps=["a"]),
        item("c", deps=["b"]),
        item("unrelated"),
    )
    items, _ = graph.parse_backlog(text)
    counts = dict(graph.analyse(items).unblocks)

    assert counts["keystone"] == 3
    assert counts["unrelated"] == 0


def test_a_deep_chain_does_not_exhaust_the_stack(graph: ModuleType) -> None:
    """Both searches are iterative; this is what says so.

    Python's default recursion limit is ~1000, so a recursive implementation
    would raise here rather than report.
    """
    depth = 1200
    items_text = [item("link-0")]
    items_text += [item(f"link-{n}", deps=[f"link-{n - 1}"]) for n in range(1, depth)]
    text = backlog(*items_text)

    found = check(graph, text)
    assert found == []

    items, _ = graph.parse_backlog(text)
    analysis = graph.analyse(items)
    assert len(analysis.chains[0]) == depth


def test_analysis_is_skipped_rather_than_hung_on_a_cyclic_graph(
    graph: ModuleType, tmp_path: Path
) -> None:
    """Longest-path over a cycle would not terminate; ``main`` must not try."""
    path = tmp_path / "backlog.md"
    path.write_text(backlog(item("a", deps=["b"]), item("b", deps=["a"])), encoding="utf-8")

    assert graph.main([str(path)]) == 1


# --- the command line --------------------------------------------------------


def test_main_exits_zero_on_the_real_backlog(graph: ModuleType) -> None:
    assert graph.main([str(REAL_BACKLOG)]) == 0


def test_main_exits_one_on_a_dangling_edge(graph: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "backlog.md"
    path.write_text(backlog(item("a", deps=["nope"])), encoding="utf-8")

    assert graph.main([str(path)]) == 1


def test_main_exits_one_on_an_empty_file(graph: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "backlog.md"
    path.write_text("", encoding="utf-8")

    assert graph.main([str(path)]) == 1


def test_main_exits_one_when_the_backlog_is_missing(graph: ModuleType, tmp_path: Path) -> None:
    """A vanished file must not read as a graph with no problems."""
    assert graph.main([str(tmp_path / "absent.md")]) == 1


def test_the_summary_file_receives_the_report(graph: ModuleType, tmp_path: Path) -> None:
    """CI passes $GITHUB_STEP_SUMMARY here.

    Stdout in a green job is read about as often as the vitest slow-test line
    was, which is the reason this option exists.
    """
    path = tmp_path / "backlog.md"
    path.write_text(backlog(item("a", "done"), item("b", deps=["a"])), encoding="utf-8")
    summary = tmp_path / "summary.md"

    assert graph.main([str(path), "--summary", str(summary)]) == 0

    written = summary.read_text(encoding="utf-8")
    assert "Backlog dependency graph" in written
    assert "`b`" in written


def test_the_summary_file_is_appended_to_never_truncated(graph: ModuleType, tmp_path: Path) -> None:
    """$GITHUB_STEP_SUMMARY is shared with every other step in the job."""
    path = tmp_path / "backlog.md"
    path.write_text(backlog(item("a", "done")), encoding="utf-8")
    summary = tmp_path / "summary.md"
    summary.write_text("earlier step output\n", encoding="utf-8")

    graph.main([str(path), "--summary", str(summary)])

    assert summary.read_text(encoding="utf-8").startswith("earlier step output\n")


def test_the_script_runs_as_a_subprocess_against_the_real_backlog() -> None:
    """Executed the way CI executes it, not merely imported.

    ``main`` returning 0 in-process does not establish that the file runs: an
    import-time error, a missing shebang path, or a stdout encoding the runner
    cannot emit are all invisible to every other test here.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Backlog dependency graph" in result.stdout
