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

import ast
import gc
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from hoops_gm.core.config import Settings
from hoops_gm.db.base import Base
from hoops_gm.db.session import absent_store_refusal, render_store_url

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "hoops_gm"
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every ``Database.from_settings`` call site in the package, and whether the
#: command it belongs to may create an absent store.
#:
#: ``"reports"``  — returns a quantity; must refuse an absent local store.
#: ``"writes"``   — creating the database is legitimate; left alone deliberately,
#:                  because a wrong classification here turns a working writer
#:                  into a crash, which is worse than a documented exposure.
#:
#: The ``"blocked"`` category is gone. It held exactly two sites, both pinned by
#: the committed four-week cohort manifest's whole-file fingerprints, and both
#: were lifted when the widened cohort was regenerated — which is the event
#: :data:`BLOCKED_REASON` named as the condition for lifting them. The category
#: is removed rather than left empty, on the instruction its own test carried.
ENGINE_CALL_SITES: dict[str, str] = {
    "app.py": "writes",
    "availability/coverage.py": "reports",
    "dev/seed_draft.py": "writes",
    "dev/seed_projections.py": "writes",
    "dev/seed_schedule_grid.py": "writes",
    "ingest/auction_values/import_csv.py": "writes",
    "ingest/backfill.py": "writes",
    # `observations` and `plan` report; `run` writes. The previous note here
    # said "`plan` and `run` write", which was half wrong: `build_plan` only
    # reads and `plan` returns before anything is written. Checked, not
    # inherited — see `backfill.STORE_REPORTING_COMMANDS`.
    "ingest/injury_report/backfill.py": "reports",
    "ingest/injury_report/cohort_evidence.py": "reports",
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

#: **The second scope limit, and the one that decayed.**
#:
#: :func:`_call_sites` finds one spelling — ``Database.from_settings(``. When
#: this census was written that was every way into a store in the package, so
#: the limit was invisible: exhaustive and narrow look identical until
#: something moves. Then `cohort_admissibility.py` opened a store through
#: ``create_engine`` over a ``sqlite3.connect`` creator, and the census went
#: from exactly complete to quietly incomplete **at exit 0, with this file
#: green**.
#:
#: A check's search pattern is part of its claim and belongs stated with it.
#: :func:`test_no_unsanctioned_module_can_open_a_store` is what makes the
#: decay loud rather than silent — see its docstring for why it scans imports
#: instead of widening this pattern.
SCAN_LIMIT = "finds one call spelling; membership is guarded by the import rule below"

#: How the two formerly-``blocked`` sites were lifted, kept because a resolved
#: exposure that leaves no trace is indistinguishable from one nobody found.
#:
#: The committed four-week cohort manifest pins a whole-file SHA-256 of four
#: source files, two of which were exactly those sites. A whole-file hash cannot
#: distinguish a guard clause that refuses before doing any work from a change to
#: the derivation itself, so **any** edit to them — including a correctness fix —
#: invalidated the manifest's provenance and turned `test_cohort_evidence.py`
#: red. Repairing it meant regenerating a cohort, which nothing could do: the
#: manifest generator takes one `Session`, and no single store held both the
#: injury reports and the participation ledger.
#:
#: `ingest/injury_report/merge_stores.py` closed that, the widened cohort was
#: regenerated over the edited files, and the guards went in with it. The
#: four-week manifest is now registered as superseded rather than regenerated —
#: see `SUPERSEDED_MANIFESTS` in `test_cohort_evidence.py` for why that is a
#: freeze and not a skip.
LIFTED_REASON = "unblocked by the widened cohort regeneration; see docs/handoff.md 2026-08-24"


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

    assert found, "scanned the package and found no engine call sites - the scan is broken"
    assert len(found) >= 10
    assert SCOPE_LIMIT
    assert SCAN_LIMIT


# --- census membership: fail loudly when a new door appears ------------------
#
# The census above enumerates *call spellings*, which is an open set:
# `create_engine(...)`, `sa.create_engine(...)`, `engine_from_config(...)`, a
# `creator=` lambda, a helper that returns an Engine. Widening it buys exactly
# the spellings you thought of, and the next one escapes identically.
#
# That is the deductive argument. The empirical one is stronger and was found
# by another lane at its own expense: a literal-string scan of this kind strips
# comments but **not docstrings**, so a module whose docstring honestly spelled
# out the call it makes had that *description* counted as a member of the audit
# register. The register was not merely incomplete, it was **wrong, with a
# fabricated entry** - and the fabrication was caused by someone documenting
# their work carefully. A text scan cannot tell a thing from a description of
# the thing, so honesty is what penalises you. That survives the objection
# "was the grep really so bad?", which the open-set argument alone does not.
#
# So this scans **imports** instead, which is a closed set: to open a store you
# must first import something that can open stores, and that is a short list of
# engine factories and DBAPI drivers. Parsing rather than matching text also
# means a docstring is a docstring: `ast.Import` nodes are the only thing
# counted, so no amount of prose about `sqlite3.connect` can forge a member.
#
# It is the same shape as `test_portability.py`'s `_DIALECT_AWARE_MODULES` - an
# allowlist of sanctioned modules rather than a pattern over call sites -
# because that shape is already understood here and it fails on *arrival*
# rather than on absence.

#: Modules permitted to open a store without going through
#: :meth:`Database.from_settings`, each with the reason it is permitted.
#:
#: A module is not sanctioned by being listed; it is listed because someone
#: wrote down why. An unrecorded entry is the thing this guards against.
SANCTIONED_STORE_OPENERS: dict[str, str] = {
    "db/session.py": (
        "the implementation of Database.from_settings itself. ADR-001 confines "
        "dialect knowledge to engine construction, and this is it."
    ),
    "ingest/injury_report/cohort_admissibility.py": (
        "opens `file:...?mode=ro` by construction, so it can neither create a "
        "store nor write into one. Deliberately outside the census above: "
        "asking whether a read-only probe 'may create a store' is a category "
        "error, not a hard call, and a census whose value is that every verdict "
        "means something cannot afford a meaningless one."
    ),
}

#: Names whose import means "this module can open a database".
#:
#: Bare ``import sqlalchemy`` is included even though nothing does it today: it
#: would permit ``sqlalchemy.create_engine(...)`` by attribute access, which is
#: precisely the kind of second spelling that defeated the call-site scan. It
#: costs nothing to close while the count is zero.
_ENGINE_FACTORIES = frozenset({"create_engine", "create_async_engine", "engine_from_config"})
_DBAPI_MODULES = frozenset(
    {"sqlite3", "psycopg", "psycopg2", "asyncpg", "aiosqlite", "pymysql", "sqlalchemy"}
)


def _store_opening_imports_in(tree: ast.AST) -> set[str]:
    """Names imported by ``tree`` that can open a database.

    Parsed rather than grepped, for two reasons that are different in kind.

    Deductively: ``from sqlalchemy import create_engine as ce`` defeats a text
    search for ``create_engine(`` while remaining an ordinary thing to write.
    The AST sees the imported name regardless of what it was bound to.

    Empirically, and more convincingly: a literal-string scan strips comments
    but not docstrings, so a module that *describes* the call it makes has that
    description counted. Only ``ast.Import`` and ``ast.ImportFrom`` nodes are
    read here, so prose cannot forge a member - see
    ``test_a_docstring_cannot_forge_a_census_entry``.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _DBAPI_MODULES:
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            for alias in node.names:
                if alias.name in _ENGINE_FACTORIES or (
                    root in _DBAPI_MODULES and root != "sqlalchemy"
                ):
                    found.add(f"{node.module}.{alias.name}")
    return found


def _store_opening_imports(path: Path) -> set[str]:
    """As :func:`_store_opening_imports_in`, for a file on disk."""
    return _store_opening_imports_in(ast.parse(path.read_text(encoding="utf-8")))


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
        else:
            assert not guards, (
                f"{relative} is classified as a writer but refuses an absent store - "
                f"creating the database is legitimate for a writer"
            )


def test_no_site_is_left_in_the_removed_blocked_category() -> None:
    """The category was emptied by a fix, so re-adding one must be deliberate.

    ``blocked`` meant "reports a quantity and is knowingly unguarded". Both of
    its members were guarded once :data:`LIFTED_REASON` describes; the category
    is gone. Reintroducing it by hand — rather than fixing the site — is the
    move this guards against, because a fresh ``blocked`` entry would inherit
    none of the scrutiny the original two carried.
    """
    assert "blocked" not in set(ENGINE_CALL_SITES.values()), (
        "a site was reclassified as 'blocked'. That category was removed after both "
        f"its members were fixed ({LIFTED_REASON}). If a genuinely new exposure "
        "exists, reinstate the category together with a written reason and a test "
        "that its cause is still live — do not add a bare entry."
    )
    assert set(ENGINE_CALL_SITES.values()) == {"reports", "writes"}


def test_a_docstring_cannot_forge_a_census_entry(tmp_path: Path) -> None:
    """Parsing means a description of a call is not counted as the call.

    This is the failure that motivated the rule, found by another lane at its
    own expense: a literal-string scan strips comments but not docstrings, so a
    module whose docstring honestly spelled out the call it makes had that
    description counted as a member of the audit register. The register gained
    a **fabricated** entry, and the cause was careful documentation.

    Driven here rather than argued: a module whose docstring and comments talk
    about opening stores, and which imports nothing, must not appear.
    """
    forgery = tmp_path / "forgery.py"
    forgery.write_text(
        '"""This module explains that one could `import sqlite3` and then call\n'
        "sqlite3.connect(path), or `from sqlalchemy import create_engine` and\n"
        'call create_engine(url). It does neither."""\n'
        "\n"
        "# import sqlite3  <- also only a comment\n"
        "VALUE = 1\n",
        encoding="utf-8",
    )

    tree = ast.parse(forgery.read_text(encoding="utf-8"))
    assert _store_opening_imports_in(tree) == set()

    # ...and the contrast that makes it a real property rather than an accident:
    # the same names, actually imported, are seen.
    real = ast.parse("import sqlite3\nfrom sqlalchemy import create_engine\n")
    assert _store_opening_imports_in(real) == {"sqlite3", "sqlalchemy.create_engine"}


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


def test_no_unsanctioned_module_can_open_a_store() -> None:
    """Fails when a new door appears, rather than passing over a shrinking domain.

    This is the check the call-site census could not be. It does **not** say
    whether a site is correct — only whether the package grew a way into a
    store that nobody recorded. Membership is what decayed; verdicts did not.

    Its own limit, stated by the same rule it exists to enforce:
    ``importlib.import_module("sqlite3")`` defeats it. That is adversarial,
    and the hazard here is accidental — nobody reaches for ``importlib`` by
    mistake.
    """
    openers = {
        path.relative_to(PACKAGE_ROOT).as_posix(): names
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if (names := _store_opening_imports(path))
    }

    assert openers, (
        "no module imports an engine factory or a DBAPI driver, which cannot be "
        "true - db/session.py does. The scan is broken, not the package clean."
    )

    unsanctioned = {k: sorted(v) for k, v in openers.items() if k not in SANCTIONED_STORE_OPENERS}
    assert unsanctioned == {}, (
        f"These modules can open a database directly, without going through "
        f"`Database.from_settings`, and are not recorded as allowed to:\n"
        f"  {unsanctioned}\n"
        f"\n"
        f"Two ways forward, and they are not equivalent:\n"
        f"  1. Route it through `Database.from_settings` "
        f"(backend/src/hoops_gm/db/session.py). That is the sanctioned door and "
        f"the usual answer.\n"
        f"  2. If it genuinely must not (the one existing exception opens "
        f"`file:...?mode=ro`, so it can neither create a store nor write to one), "
        f"add it to SANCTIONED_STORE_OPENERS with the reason. That is a decision, "
        f"not a formality: you are widening the set of code that chooses which "
        f"database this tool reads.\n"
        f"\n"
        f"Why the check is import-shaped rather than call-shaped: the census in "
        f"this file scans one call spelling. It was exactly complete when written, "
        f"and went silently incomplete at exit 0 the day a module opened a store "
        f"another way. Call spellings are an open set; imports are not.\n"
        f"\n"
        f"So please do not delete or loosen this to get a rebase through. Firing "
        f"on arrival is the entire point of it."
    )

    stale = set(SANCTIONED_STORE_OPENERS) - set(openers)
    assert stale == set(), (
        f"SANCTIONED_STORE_OPENERS exempts modules that no longer open a store "
        f"directly:\n"
        f"  {sorted(stale)}\n"
        f"\n"
        f"Delete those entries. An exemption that outlives its reason silently "
        f"covers whatever gets written in that file next, which is the same "
        f"failure as an allowlist nobody rereads."
    )


def test_every_sanctioned_opener_records_why() -> None:
    """An exemption with no stated reason decays into an unexamined one."""
    for module, reason in SANCTIONED_STORE_OPENERS.items():
        assert reason.strip(), f"{module} is exempt with no recorded reason"
        assert len(reason) > 40, f"{module}'s reason is too short to be one: {reason!r}"


def _absent(tmp_path: Path) -> Path:
    """A path that does not exist, and whose parent does not either."""
    return tmp_path / "nowhere" / "hoops_gm.db"


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

    # This CLI now disposes its engine, but the capture stays: `main` opens the
    # store through `Database.from_settings`, and a pooled connection finalised
    # during teardown — after tmp_path has removed the file underneath it — is a
    # different failure from the one being tested. Disposing twice is harmless.
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

    assert exit_code == 0, "a zero-row report exits 0 - the same code as a real answer"
    assert "observed: 0" in out
    assert str(store) not in out and store.name not in out, (
        "observations now names its store - the false-zero vector is closed, so "
        "update this test and the audit's conclusion"
    )


def test_the_startup_log_names_the_store_not_only_its_dialect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zero from the API must be attributable to the store that produced it.

    The remedy that actually closed the participation-ledger contradiction was
    naming the store beside the count. The server is where a count becomes a
    dashboard number, so it is where that ambiguity costs most.

    Asserted by recording the call rather than by capturing structlog output.
    ``configure_logging`` sets ``cache_logger_on_first_use=True``, so
    ``app.py``'s module-level logger binds its processor chain the first time
    anything logs through it — after which ``structlog.testing.capture_logs``
    cannot intercept it. A capture-based version of this test **passed alone
    and failed in the full suite**, which is worth stating plainly: that is the
    shape of a test resting on shared mutable global state. It is not flaky, it
    is order-dependent, and running it in isolation is the one way not to find
    out.
    """
    from fastapi.testclient import TestClient

    from hoops_gm import app as app_module

    recorded: list[tuple[str, dict[str, object]]] = []

    class RecordingLogger:
        def info(self, event: str, **kwargs: object) -> None:
            recorded.append((event, kwargs))

        def warning(self, event: str, **kwargs: object) -> None:
            recorded.append((event, kwargs))

        def error(self, event: str, **kwargs: object) -> None:
            recorded.append((event, kwargs))

    store = tmp_path / "hoops_gm.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{store.as_posix()}",
        bridge_secret_path=tmp_path / "bridge_secret",
        _env_file=None,
    )
    app = app_module.create_app(settings)
    monkeypatch.setattr(app_module, "log", RecordingLogger())

    with TestClient(app):
        pass

    startup = [fields for event, fields in recorded if event == "app.startup"]
    assert startup, f"no app.startup event; saw {[event for event, _ in recorded]}"
    assert startup[0]["store"] == str(store.resolve())
    assert startup[0]["dialect"] == "sqlite", "the dialect must not have been dropped for the path"


def test_the_startup_log_never_carries_a_password(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Naming the store must not become a way to leak a credential.

    Built as an engine URL rather than a live server: the assertion is about
    what `render_store_url` hands the logger, and a Postgres connection is not
    needed to check that.
    """
    safe, local_path = render_store_url(
        make_url("postgresql+psycopg://hoops:ho%25ops%23pw@127.0.0.1:5432/hoops_gm")
    )

    assert "ho%ops#pw" not in safe
    assert "ho%25ops%23pw" not in safe
    assert local_path is None, "a server-backed store has no local path to log"


def test_the_store_stays_off_the_http_surface(tmp_path: Path) -> None:
    """`health.py` deliberately keeps connection-URL information out of responses.

    Startup logging is observability and belongs to whoever runs the process;
    putting a filesystem path in an HTTP body is a REST-contract decision and a
    disclosure one. This pins the boundary so a later change has to be
    deliberate rather than incidental.
    """
    from fastapi.testclient import TestClient

    from hoops_gm.app import create_app

    store = tmp_path / "hoops_gm.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{store.as_posix()}",
        bridge_secret_path=tmp_path / "bridge_secret",
        _env_file=None,
    )

    app = create_app(settings)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.database.engine)
        for path in ("/health", "/health/ready"):
            body = client.get(path).text
            assert store.name not in body, f"{path} leaked the store filename"
            assert str(tmp_path) not in body, f"{path} leaked the store path"


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
