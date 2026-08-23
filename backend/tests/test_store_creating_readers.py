"""Which commands may create the store they open, and which must refuse.

SQLite creates a database on connect rather than refusing. For a command that
**writes**, that is correct. For a command that reports a quantity it is worth
guarding against — but **not for the reason it is tempting to give**, and the
distinction is the most useful thing in this module.

**Driven, 2026-08-23.** Pointed at an absent path, a reporting command creates
an *unmigrated* file and then dies on ``no such table``. That is litter plus a
misdiagnosis — the error blames the schema when the real fault is the path —
but it is **loud**, and nobody reads a traceback as a result. So
create-on-connect does *not* manufacture a false zero, and an earlier entry of
mine that said it did was overstating the case.

**The real false-zero vector is a store that is migrated and empty.** That is
what ``alembic upgrade head`` produces in a fresh worktree, and what the main
checkout's ``hoops_gm.db`` was at schema 0003 when it reported 0 participation
rows against a real ledger of 43,037. Such a store answers every query
honestly, reports zero, and exits **0** — indistinguishable from a real answer.

So the guard here earns its place on the narrow, evidenced ground of correct
diagnosis and no stray files. **What actually closes the false zero is naming
the store beside the count**, which is why
:mod:`hoops_gm.availability.coverage` cannot emit one without the other.

:data:`ENGINE_CALL_SITES` is the audit made permanent. Adding a call site
without classifying it fails ``test_every_engine_call_site_is_classified``,
which is the point: the previous audit was a one-off sweep, and a one-off sweep
is exactly what missed this the first time. It has already earned that —
``dev/seed_demo.py`` arrived in #81 while this branch was in review and the
census failed on first contact with it, before anyone thought to look.

**Read :data:`SCOPE_LIMIT` before treating a ``writes`` verdict as a safety
claim.** This module asks only whether a command may *create* a store. Whether
one may *write into a store it did not create* is a separate question with its
own live exposure.
"""

from __future__ import annotations

import gc
import json
from pathlib import Path

import pytest

from hoops_gm.core.config import Settings
from hoops_gm.db.session import absent_store_refusal

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "hoops_gm"
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every ``Database.from_settings`` call site in the package, and whether the
#: command it belongs to may create an absent store.
#:
#: ``"reports"``  — returns a quantity; must refuse an absent local store.
#: ``"writes"``   — creating the database is legitimate; left alone deliberately,
#:                  because a wrong classification here turns a working writer
#:                  into a crash, which is worse than a documented exposure.
#: ``"blocked"``  — reports a quantity and is **knowingly unguarded**. See
#:                  :data:`BLOCKED_REASON`. Recorded rather than fixed, so the
#:                  exposure is visible instead of forgotten.
ENGINE_CALL_SITES: dict[str, str] = {
    "app.py": "writes",
    "availability/coverage.py": "reports",
    "dev/seed_draft.py": "writes",
    "dev/seed_projections.py": "writes",
    "dev/seed_schedule_grid.py": "writes",
    "ingest/auction_values/import_csv.py": "writes",
    "ingest/backfill.py": "writes",
    # `observations` reports; `plan` and `run` write.
    "ingest/injury_report/backfill.py": "blocked",
    "ingest/injury_report/cohort_evidence.py": "blocked",
    "ingest/projections/import_csv.py": "writes",
    # Already correct before this audit: the engine is built only inside the
    # non-dry-run branch, so the read-only path never opens a store at all.
    "ingest/schedule_import.py": "writes",
    # Arrived with #81, and this census caught it on first contact — which is
    # what the census is for. A writer: it takes its target as `--database-url`
    # rather than from the environment, and carries its own `DemoSeedRefused`
    # guard. **That guard is a different question from this one** — see
    # :data:`SCOPE_LIMIT`.
    "dev/seed_demo.py": "writes",
}

#: What this module does **not** check, stated because the gap is easy to
#: mistake for coverage.
#:
#: Every classification here answers "may this command **create** a store it
#: should not?". It does not answer "may this command **write into a store it
#: did not create**?" — and #81 found exactly that: the composed seeder,
#: pointed at the real 43,037-row ledger, exits 0 and writes into it, because
#: all three of its safety guards key on proxies (`leagues` count, current
#: season, a prior BBM import) that the real store happens to answer safely.
#:
#: It is the same shape as the false zero, with the sign flipped. There, a
#: populated store answered **zero** to a question about a different store;
#: here, a populated store answers **yes** to a guard that asked a proxy
#: question. In both cases the number is honest and the question was wrong.
#:
#: A `writes` verdict below therefore means "creating a database is legitimate
#: for this command", **never** "this command is safe to point anywhere".
SCOPE_LIMIT = "classifies creation, not destination; see docs/handoff.md 2026-08-23"

#: Why the two ``blocked`` sites are not fixed here.
#:
#: The committed cohort manifest
#: ``docs/adapters/nba-injury-report-cohort-2025-12-08--2026-01-04.json`` pins a
#: whole-file SHA-256 of four source files, two of which are exactly these. A
#: whole-file hash cannot distinguish a guard clause that refuses before doing
#: any work from a change to the derivation itself, so **any** edit to them —
#: including a correctness fix — invalidates the manifest's provenance and
#: `test_cohort_evidence.py` fails.
#:
#: Repairing it means re-running the manifest's own `operator.commands`, which
#: include the injury-report `plan`/`run` pair. That is cohort work, it is
#: explicitly out of scope, and per `docs/backlog.md` the cohort in question can
#: never activate its model (whole-cohort `doubtful` is 21 against a floor of
#: 30). Reverting the guard silently would have hidden a live false-zero
#: generator — and one of these two *writes that very manifest*, so an invented
#: empty store there would record "no cohort" as a finding.
#:
#: So it is recorded instead, and the owner decides. This constant exists to
#: make that decision impossible to lose.
BLOCKED_REASON = "fingerprinted by the committed cohort manifest; see docs/handoff.md 2026-08-23"


def _call_sites() -> set[str]:
    found = set()
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "Database.from_settings(" in line.split("#", 1)[0]:
                found.add(path.relative_to(PACKAGE_ROOT).as_posix())
    return found


def test_the_scan_finds_call_sites_at_all() -> None:
    """A clean report over zero sites is the defect being hunted, not a pass."""
    found = _call_sites()

    assert found, "scanned the package and found no engine call sites — the scan is broken"
    assert len(found) >= 10
    assert SCOPE_LIMIT


def test_every_engine_call_site_is_classified() -> None:
    """A new call site must be classified, not silently inherit create-on-connect."""
    found = _call_sites()

    unclassified = found - set(ENGINE_CALL_SITES)
    vanished = set(ENGINE_CALL_SITES) - found
    assert unclassified == set(), (
        f"unclassified engine call sites: {sorted(unclassified)}. "
        f"Decide whether each reports a quantity (must refuse an absent store) "
        f"or writes (may create it), then record it in ENGINE_CALL_SITES."
    )
    assert vanished == set(), (
        f"ENGINE_CALL_SITES names sites that no longer exist: {sorted(vanished)}"
    )


def test_reporting_commands_refuse_and_writers_do_not() -> None:
    """Pins all three states: guarded, deliberately unguarded, and blocked.

    Looks for a *call* — ``absent_store_refusal(`` — rather than the bare name,
    which also appears on the import line. Deleting the guard while leaving the
    import behind is precisely what a careless edit does, and a check that
    matched the name would have stayed green through it. Confirmed by mutation:
    removing the guard block from a guarded file turns this red.
    """
    for relative, kind in ENGINE_CALL_SITES.items():
        source = (PACKAGE_ROOT / relative).read_text(encoding="utf-8")
        guards = "absent_store_refusal(" in source
        if kind == "reports":
            assert guards, f"{relative} reports a quantity but does not refuse an absent store"
        elif kind == "blocked":
            # Asserted, not merely commented. If someone regenerates the cohort
            # manifest and adds the guard, this fails and forces the
            # classification to be corrected rather than left lying.
            assert not guards, (
                f"{relative} is now guarded — good. Reclassify it as 'reports' and "
                f"drop it from the blocked set ({BLOCKED_REASON})."
            )
        else:
            assert not guards, (
                f"{relative} is classified as a writer but refuses an absent store — "
                f"creating the database is legitimate for a writer"
            )


def test_the_blocked_sites_are_blocked_for_a_recorded_reason() -> None:
    """A known exposure with no written reason decays into an unknown one."""
    blocked = {k for k, v in ENGINE_CALL_SITES.items() if v == "blocked"}

    assert blocked, "if nothing is blocked, remove the category rather than leaving it empty"
    assert BLOCKED_REASON
    # The manifest that causes the block must still fingerprint them, or the
    # block has outlived its cause and should be lifted.
    manifest = json.loads(
        (
            REPO_ROOT / "docs" / "adapters" / "nba-injury-report-cohort-2025-12-08--2026-01-04.json"
        ).read_text(encoding="utf-8")
    )
    fingerprinted = {
        path.removeprefix("backend/src/hoops_gm/")
        for path in manifest["operator"]["source_fingerprints"]
    }
    assert blocked <= fingerprinted, (
        f"these are blocked but no longer fingerprinted by the cohort manifest, "
        f"so nothing stops them being fixed now: {sorted(blocked - fingerprinted)}"
    )


# --- driven on the filesystem, not on a return value ------------------------
#
# A test that only read the returned message would pass identically whether or
# not the file had been created, which is the assertion shape that let this
# defect through in the first place.


def _absent(tmp_path: Path) -> Path:
    return tmp_path / "nowhere" / "hoops_gm.db"


def test_coverage_refuses_an_absent_store_without_creating_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from hoops_gm.availability import coverage

    target = _absent(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target.as_posix()}")

    assert coverage.main([]) == 2
    assert not target.exists()
    assert str(target) in capsys.readouterr().out


def test_an_unreadable_store_is_not_reported_as_an_empty_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 1 must mean "read it, it holds nothing" — never "could not read it".

    Without the guard these collapse: an uncaught SQLAlchemy error exits 1,
    which is the tool's documented code for an empty ledger, so a caller
    checking only the exit status reads a broken connection as a finding.

    Driven originally against a nonexistent Postgres database, which refuses
    rather than creating one. Reproduced here with a file that exists but is
    not a database, so the test needs no server and holds on either dialect.
    """
    from hoops_gm.availability import coverage

    corrupt = tmp_path / "hoops_gm.db"
    corrupt.write_bytes(b"this is not a SQLite database")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{corrupt.as_posix()}")

    exit_code = coverage.main([])

    assert exit_code == 2, "an unreadable store must not share an exit code with an empty one"
    assert "could not read" in capsys.readouterr().out


def test_the_blocked_readers_report_zero_without_naming_their_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The real false-zero vector, driven — and it is not create-on-connect.

    Pointed at an **absent** path, ``observations`` creates the file and then
    dies on ``no such table``: litter and a misdiagnosis, but loud, and nobody
    reads a traceback as a result.

    Pointed at a store that is **migrated and empty** — which is precisely what
    `alembic upgrade head` in a fresh worktree produces, and what the main
    checkout's `hoops_gm.db` was at schema 0003 — it prints ``games in scope:
    0`` and exits **0**. That is the false zero, it is indistinguishable from
    success by exit code, and **no path appears anywhere in the output**, so the
    number cannot be attributed to the store that produced it.

    That is the defect the participation-ledger contradiction was made of, and
    the remedy is the one `coverage.py` already implements: report the store
    with the count. The guard against create-on-connect is worth having for
    diagnosis and tidiness, but it is not what closes this.
    """
    from hoops_gm.db.base import Base
    from hoops_gm.db.session import Database
    from hoops_gm.ingest.injury_report import backfill

    store = tmp_path / "hoops_gm.db"
    settings = Settings(
        environment="test", database_url=f"sqlite:///{store.as_posix()}", _env_file=None
    )
    database = Database.from_settings(settings)
    Base.metadata.create_all(database.engine)
    database.dispose()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{store.as_posix()}")

    # That CLI never disposes its engine — a real if minor leak, and one more
    # thing the manifest fingerprint currently blocks fixing. Capture and close
    # what it opens, so a pooled connection is not finalised during teardown
    # after tmp_path has removed the file underneath it.
    opened: list[Database] = []
    original = Database.from_settings

    def _capture(settings_in: Settings) -> Database:
        opened.append(created := original(settings_in))
        return created

    monkeypatch.setattr(Database, "from_settings", staticmethod(_capture))
    try:
        exit_code = backfill.main(["observations", "2025-26"])
        out = capsys.readouterr().out
    finally:
        for opened_database in opened:
            opened_database.dispose()
        gc.collect()

    assert exit_code == 0, "a zero-row report exits 0 — the same code as a real answer"
    assert "observed: 0" in out
    assert str(store) not in out and store.name not in out, (
        "observations now names its store — the false-zero vector is closed, so "
        "update this test and the audit's conclusion"
    )


def test_a_present_store_is_not_refused(tmp_path: Path) -> None:
    """The guard must not fire on the normal case."""
    present = tmp_path / "hoops_gm.db"
    present.write_bytes(b"")

    assert absent_store_refusal(f"sqlite:///{present.as_posix()}") is None


def test_the_refusal_names_the_path_and_says_what_to_do(tmp_path: Path) -> None:
    target = _absent(tmp_path)

    refusal = absent_store_refusal(f"sqlite:///{target.as_posix()}")

    assert refusal is not None
    assert str(target) in refusal
    assert "DATABASE_URL" in refusal
    assert "alembic upgrade head" in refusal
    assert not target.exists()
