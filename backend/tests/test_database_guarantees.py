"""Guarantees that must hold at the database, not just in the ORM.

Every test here goes around SQLAlchemy's Python-side validation and talks to
the database in raw SQL, because that is the gap the code review found: the
enum guarantee was enforced only by ``validate_strings``, which covers the ORM
path and nothing else — not ``text()``, not an Alembic data migration, not a
bulk load, not anything opening the database file directly.

The rule these encode: **a guarantee that is never exercised is a belief, not
a guarantee.** Assert against rendered DDL and executed SQL, never against a
docstring.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import Enum as SAEnum
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.db.base import Base
from hoops_gm.db.models import NbaGame, NbaTeam, Player


def _sql_now() -> str:
    """A timestamp literal for raw SQL.

    An ISO string rather than a ``datetime``: passing the object binds through
    the sqlite3 datetime adapter, which is deprecated in Python 3.12+ and, with
    ``filterwarnings = ["error"]``, would fail the test for reasons unrelated
    to what it is checking.
    """
    return datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


# --- Enum CHECK constraints (review finding 1) --------------------------------


def _enum_columns() -> list[tuple[str, str]]:
    return [
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, SAEnum)
    ]


def test_the_schema_actually_has_enum_columns() -> None:
    """Guards the guard: the checks below are vacuous if this is empty."""
    assert len(_enum_columns()) >= 17


def test_every_enum_column_has_a_check_constraint() -> None:
    """``create_constraint`` defaults to False. Omitting it was review finding 1."""
    unprotected = [
        f"{table}.{column}"
        for table, column in _enum_columns()
        for enum_type in [Base.metadata.tables[table].columns[column].type]
        if isinstance(enum_type, SAEnum) and not enum_type.create_constraint
    ]

    assert unprotected == [], (
        "enum columns without a CHECK constraint - an unknown value will insert "
        "cleanly through any path that bypasses the ORM"
    )


def test_enum_check_constraints_reach_the_created_table(session: Session) -> None:
    """Metadata saying so is not the same as the database doing so."""
    inspector = inspect(session.get_bind())
    constraints = inspector.get_check_constraints("player_external_ids")
    definitions = " ".join(str(c.get("sqltext", "")) for c in constraints)

    assert "source" in definitions
    assert "fantrax" in definitions


def test_raw_sql_cannot_insert_an_unknown_enum_value(session: Session) -> None:
    """The test the previous suite was missing.

    The ORM-level equivalent passed on a schema with no constraint at all,
    because SQLAlchemy rejected the value in Python before it reached the
    database.
    """
    player = Player(full_name="Test Player", normalized_name="testplayer")
    session.add(player)
    session.flush()

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO player_external_ids "
                "(player_id, source, external_id, confidence, match_method, "
                " is_manual_override, created_at, updated_at) "
                "VALUES (:pid, 'espn-totally-bogus', 'x', 1.0, 'anchor_id', "
                " false, :now, :now)"
            ),
            {"pid": player.id, "now": _sql_now()},
        )


def test_raw_sql_accepts_a_known_enum_value(session: Session) -> None:
    """The constraint must reject the unknown without rejecting the known."""
    player = Player(full_name="Test Player", normalized_name="testplayer")
    session.add(player)
    session.flush()

    session.execute(
        text(
            "INSERT INTO player_external_ids "
            "(player_id, source, external_id, confidence, match_method, "
            " is_manual_override, created_at, updated_at) "
            "VALUES (:pid, 'fantrax', 'x', 1.0, 'anchor_id', false, :now, :now)"
        ),
        {"pid": player.id, "now": _sql_now()},
    )

    stored = session.execute(
        text("SELECT source FROM player_external_ids WHERE player_id = :pid"),
        {"pid": player.id},
    ).scalar_one()
    assert stored == "fantrax"


def test_adding_an_enum_member_would_require_a_migration(session: Session) -> None:
    """The claim that motivated ``portable_enum`` in the first place.

    With no CHECK constraint it was false: ``compare_metadata`` returned
    nothing when a member was added, so nothing forced a migration and CI
    stayed silent. Asserted against the constraint the database actually holds
    — every current member must be named in it, so adding one puts the database
    out of step with the models until a migration widens it.
    """
    inspector = inspect(session.get_bind())
    definitions = " ".join(
        str(constraint.get("sqltext", ""))
        for constraint in inspector.get_check_constraints("player_external_ids")
    )
    enum_type = Base.metadata.tables["player_external_ids"].columns["source"].type
    assert isinstance(enum_type, SAEnum)

    assert enum_type.enums, "guard the guard: no members to check"
    for member in enum_type.enums:
        assert member in definitions, f"{member} is not named in the database CHECK"


def test_the_check_constraint_does_not_permit_an_unlisted_value(
    session: Session,
) -> None:
    """Complements the test above: the list must be exhaustive, not illustrative."""
    inspector = inspect(session.get_bind())
    definitions = " ".join(
        str(constraint.get("sqltext", ""))
        for constraint in inspector.get_check_constraints("player_external_ids")
    )

    assert "espn" not in definitions


# --- Timezone handling (review finding 2) -------------------------------------

EASTERN = timezone(timedelta(hours=-4), "EDT")


def _game(session: Session, tipoff: datetime | None) -> NbaGame:
    home = NbaTeam(nba_team_id=1610612738, abbreviation="BOS", name="Boston")
    away = NbaTeam(nba_team_id=1610612752, abbreviation="NYK", name="New York")
    session.add_all([home, away])
    session.flush()
    game = NbaGame(
        season="2026-27",
        nba_game_id="0022600001",
        game_date=tipoff.date() if tipoff else date(2026, 10, 21),
        tipoff_utc=tipoff,
        home_team_id=home.id,
        away_team_id=away.id,
    )
    session.add(game)
    session.flush()
    return game


def test_an_aware_non_utc_tipoff_survives_the_round_trip(session: Session) -> None:
    """The four-hour bug, pinned.

    A 7:30pm Eastern tip-off is 23:30 UTC. Before the fix, SQLite discarded the
    offset and read it back as a naive 19:30 — from a write that was correct on
    Postgres. Rest-day and back-to-back detection are computed off this column,
    and both feed the availability model.
    """
    tipoff = datetime(2026, 10, 21, 19, 30, tzinfo=EASTERN)

    game = _game(session, tipoff)
    session.expire(game)
    stored = session.execute(select(NbaGame.tipoff_utc)).scalar_one()

    assert stored is not None
    assert stored.tzinfo is not None, "offset was discarded"
    assert stored.utcoffset() == timedelta(0)
    assert stored == tipoff
    assert (stored.hour, stored.minute) == (23, 30)


def test_a_utc_tipoff_survives_unchanged(session: Session) -> None:
    tipoff = datetime(2026, 10, 21, 23, 30, tzinfo=UTC)

    _game(session, tipoff)
    stored = session.execute(select(NbaGame.tipoff_utc)).scalar_one()

    assert stored == tipoff


def test_a_naive_tipoff_is_rejected_rather_than_assumed(session: Session) -> None:
    """Assuming UTC is exactly how a local wall-clock time becomes a wrong instant."""
    with pytest.raises((ValueError, Exception), match="naive datetime"):
        _game(session, datetime(2026, 10, 21, 19, 30))
        session.flush()


def test_timestamps_come_back_timezone_aware(session: Session) -> None:
    """``created_at`` must be comparable to ``datetime.now(UTC)`` on both dialects.

    Before the fix this raised ``TypeError`` on SQLite and worked on Postgres.
    """
    player = Player(full_name="Test Player", normalized_name="testplayer")
    session.add(player)
    session.flush()
    session.expire(player)

    assert player.created_at.tzinfo is not None
    assert player.updated_at.tzinfo is not None
    # The comparison itself is the assertion: it raises if either side is naive.
    assert player.created_at <= datetime.now(UTC) + timedelta(minutes=5)
    assert player.created_at >= datetime.now(UTC) - timedelta(hours=1)


def test_ordering_by_tipoff_is_correct_across_offsets(session: Session) -> None:
    """Two tip-offs whose wall-clock order is the reverse of their real order."""
    earlier_instant = datetime(2026, 10, 21, 19, 0, tzinfo=EASTERN)  # 23:00 UTC
    later_instant = datetime(2026, 10, 21, 20, 0, tzinfo=UTC)  # 20:00 UTC — earlier

    home = NbaTeam(nba_team_id=1, abbreviation="AAA", name="A")
    away = NbaTeam(nba_team_id=2, abbreviation="BBB", name="B")
    session.add_all([home, away])
    session.flush()
    session.add_all(
        [
            NbaGame(
                season="2026-27",
                nba_game_id="game-eastern",
                game_date=earlier_instant.date(),
                tipoff_utc=earlier_instant,
                home_team_id=home.id,
                away_team_id=away.id,
            ),
            NbaGame(
                season="2026-27",
                nba_game_id="game-utc",
                game_date=later_instant.date(),
                tipoff_utc=later_instant,
                home_team_id=away.id,
                away_team_id=home.id,
            ),
        ]
    )
    session.flush()

    ordered = (
        session.execute(select(NbaGame.nba_game_id).order_by(NbaGame.tipoff_utc)).scalars().all()
    )

    # 20:00 UTC genuinely precedes 23:00 UTC, despite "19:00" reading as earlier.
    assert ordered == ["game-utc", "game-eastern"]
