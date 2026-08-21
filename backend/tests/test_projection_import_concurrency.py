"""R58: the projection importer's lock, across processes and across dialects.

The defect these pin was in **merged** code. ``import_projection_csv`` guarded a
repeat import with ``SELECT ... FOR UPDATE`` on the ``projection_sources`` row,
and on SQLite that serialized nothing at all, for two independent reasons:

1. pysqlite emits ``BEGIN`` lazily, before DML and not before a ``SELECT``. On a
   repeat import of an already-registered source, no DML had been emitted when
   the lock statement ran — ``get_or_create_projection_source`` ends with
   ``row.display_name = display_name; session.flush()``, and the ORM emits no
   ``UPDATE`` when the value is unchanged, which is exactly what running the
   same import twice looks like. So the session held no write reservation.
2. SQLAlchemy's SQLite dialect renders no ``FOR UPDATE`` text at all.

The in-process ``threading.Lock`` still separated threads and did nothing
between two processes — and ``python -m hoops_gm.ingest.projections.import_csv``
is what makes two processes an ordinary thing to have.

**What these tests establish, stated at the strength they were driven at.** They
show the lock is now real: a session that has emitted no DML holds a write
reservation a second *connection* cannot write through. They do **not** show
that the old inert lock produced corruption. Four concurrent processes were run
against one SQLite file with the lock disabled, both with identical bytes and
with divergent cohorts, and every round converged correctly — because SQLite
serializes writers at the file level once DML begins, and the reconciliation on
this path is idempotent per import row. The window was real; the harm was not
reproduced. See ``docs/handoff.md``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.sql import Executable

from hoops_gm.core.config import Settings
from hoops_gm.db.models.enums import ExternalSource
from hoops_gm.db.models.lineage import RefreshRun
from hoops_gm.db.models.projections import ProjectionSource
from hoops_gm.db.session import Database
from hoops_gm.ingest.projections.importer import (
    _lock_projection_source_scope,
    get_or_create_projection_source,
)

SEASON = "2026-27"
SOURCE = ExternalSource.BASKETBALL_MONSTER


def _register_source(database: Database) -> None:
    with database.session() as session:
        get_or_create_projection_source(session, source=SOURCE, display_name="Basketball Monster")


@pytest.mark.sqlite_only
def test_the_lock_takes_a_real_write_reservation_before_any_other_dml(
    database: Database, settings: Settings
) -> None:
    """The exact condition the old ``FOR UPDATE`` failed: a lock before any write.

    Driven from a **second connection**, not from a second session on the same
    one — under ``StaticPool`` two sessions share a connection and SQLite could
    not tell them apart, which would make this pass for a reason that says
    nothing about two processes.

    It also settles a claim this lane declined to inherit from a docstring.
    ``lock_refresh_scope`` says SQLite "reserves its database-wide writer
    through a no-op update", and for a scope with **no ``refresh_runs`` row** —
    which a projection source is, since this registers none — that statement is
    a zero-row ``UPDATE``. Whether a zero-row write still takes the reservation
    is not obvious, and believing the sentence would be exactly the unexamined
    inheritance the house rules name. This is the executable version of the
    question.
    """
    _register_source(database)

    other = Database.from_settings(settings)
    holder = database.session_factory()
    try:
        # Nothing has been written on this session. Under the old `FOR UPDATE`
        # the transaction was not even open at this point.
        _lock_projection_source_scope(holder, SOURCE, SEASON)

        with other.session() as contender:
            contender.execute(text("PRAGMA busy_timeout = 250"))
            with pytest.raises(Exception, match=r"(?i)database is locked"):
                contender.execute(text("UPDATE projection_sources SET display_name = 'contended'"))
                contender.flush()
    finally:
        holder.rollback()
        holder.close()
        other.dispose()


@pytest.mark.sqlite_only
def test_the_reservation_is_released_when_the_transaction_ends(
    database: Database, settings: Settings
) -> None:
    """A lock held past its transaction would be worse than the defect it fixes.

    The negative control for the test above: the same second-connection write
    that is refused while the scope is held must succeed once it is released.
    Without this, a mutation that simply wedged the database would look like a
    working lock.
    """
    _register_source(database)

    holder = database.session_factory()
    _lock_projection_source_scope(holder, SOURCE, SEASON)
    holder.rollback()
    holder.close()

    other = Database.from_settings(settings)
    try:
        with other.session() as contender:
            contender.execute(text("PRAGMA busy_timeout = 250"))
            contender.execute(text("UPDATE projection_sources SET display_name = 'free'"))
        with other.session() as check:
            assert check.scalar(select(ProjectionSource.display_name)) == "free"
    finally:
        other.dispose()


def test_taking_the_lock_does_not_bump_updated_at(database: Database) -> None:
    """Taking a lock must not be a data change, on either dialect.

    ``ProjectionSource`` carries ``TimestampMixin``, whose ``onupdate=func.now()``
    fires on a Core ``update()``. The projections endpoint hit exactly this and
    it was a real finding: a reservation-holding statement silently moved a
    timestamp. Routing through ``lock_refresh_scope`` makes that structurally
    impossible — the reservation targets ``refresh_runs``, not
    ``projection_sources`` — and this is the regression pin on that property.

    **The stored timestamp is backdated first, and that is load-bearing.** An
    earlier version compared ``updated_at`` before against after without
    backdating, and passed whether or not the bug was present: SQLite's
    ``CURRENT_TIMESTAMP`` has one-second resolution and the whole test ran
    inside one tick. The mutation removing the guard was **NOT CAUGHT**, which
    is the only reason this paragraph exists.
    """
    old = datetime(2020, 1, 1, tzinfo=UTC)
    _register_source(database)
    with database.session() as setup:
        setup.execute(
            update(ProjectionSource).where(ProjectionSource.source == SOURCE).values(updated_at=old)
        )

    with database.session() as check:
        before = check.scalar(
            select(ProjectionSource.updated_at).where(ProjectionSource.source == SOURCE)
        )
    assert before == old, "the backdate did not apply, so this test cannot observe a bump"

    with database.session() as locker:
        _lock_projection_source_scope(locker, SOURCE, SEASON)

    with database.session() as check:
        after = check.scalar(
            select(ProjectionSource.updated_at).where(ProjectionSource.source == SOURCE)
        )

    assert after == old


def test_taking_the_lock_registers_no_refresh_run(database: Database) -> None:
    """A lock scope is not a published refresh, and must not look like one.

    ``lock_projection_source_scope`` reuses the ``refresh_runs`` lock namespace
    but registers nothing there. If it ever did, every import would advertise a
    current projection refresh that no producer stamped — and ``quant`` owns
    registering those. A consumer asking "is my projection cohort current" would
    get an answer manufactured by a lock.
    """
    _register_source(database)

    with database.session() as locker:
        _lock_projection_source_scope(locker, SOURCE, SEASON)

    with database.session() as check:
        assert check.scalar(select(func.count()).select_from(RefreshRun)) == 0


def test_the_importer_takes_the_projection_source_scope_before_it_writes(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing else observes that the importer takes this lock at all.

    Written after a mutation deleting the ``_lock_projection_source_scope`` call
    from ``import_projection_csv`` was **NOT CAUGHT** by any functional test —
    correctly, because a single-process import does not need the lock to
    succeed. A guard whose removal no test can see is a guard that will be
    removed by accident.

    The recorder patches ``hoops_gm.db.lineage.acquire_transaction_lock``, the
    same seam the schedule-grid lock-order tests use, which is only reliable
    because ``db/lineage.py`` is the sole module reaching the primitive —
    ``test_lineage_locks_are_acquired_through_exactly_one_import`` keeps it that
    way.

    It asserts the scope is taken **first**, not merely taken: the point of
    moving it ahead of ``get_or_create_projection_source`` is that the old
    ``FOR UPDATE`` ran after the source row had been read and after the import
    row had been created, closing the window later than it opened.
    """
    from hoops_gm.dev.seed_projections import (
        PLAYERS_FIXTURE,
        build_demo_csv,
        unique_named_players,
    )
    from hoops_gm.dev.seed_schedule_grid import DEFAULT_FIXTURES_DIR, load_fixture
    from hoops_gm.ingest.importers import import_nba_players
    from hoops_gm.ingest.nba.parsers import parse_common_all_players
    from hoops_gm.ingest.projections.importer import import_projection_csv

    with database.session() as setup:
        import_nba_players(
            setup, parse_common_all_players(load_fixture(DEFAULT_FIXTURES_DIR, PLAYERS_FIXTURE))
        )
    with database.session() as reader:
        csv_bytes = build_demo_csv(unique_named_players(reader, limit=4))

    taken: list[str] = []
    from hoops_gm.db.session import acquire_transaction_lock as real_lock

    def record(session: Session, *, scope_key: str, write_reservation: Executable) -> None:
        taken.append(scope_key)
        real_lock(session, scope_key=scope_key, write_reservation=write_reservation)

    monkeypatch.setattr("hoops_gm.db.lineage.acquire_transaction_lock", record)

    with database.session() as session:
        import_projection_csv(
            session,
            source=SOURCE,
            display_name="Basketball Monster 2026-27",
            season=SEASON,
            csv_bytes=csv_bytes,
        )

    expected = f"projection\x00projection-source:{SOURCE.value}\x00{SEASON}"
    assert taken, "the importer took no transaction lock at all"
    assert taken[0] == expected


def test_the_lock_scope_is_taken_even_for_an_unregistered_source(database: Database) -> None:
    """The scope must exist before the row it protects does.

    The first import of a source creates the ``projection_sources`` row, so a
    lock keyed on that row existing would leave the create race unserialized —
    the case where two processes both find nothing and both insert. Taking the
    scope must therefore succeed against an empty database, and must not bring a
    source row into existence to do it.
    """
    with database.session() as locker:
        _lock_projection_source_scope(locker, SOURCE, SEASON)

    with database.session() as check:
        assert check.scalar(select(func.count()).select_from(ProjectionSource)) == 0
