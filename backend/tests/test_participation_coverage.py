"""Participation-ledger coverage, and the store every count came from.

The regression under test is not a crash. On 2026-08-22 two reports about
``player_participation`` sat on ``main`` simultaneously — 43,037 rows and 0 rows
— and **both were correct**, because they had queried two different SQLite
files that share the basename ``hoops_gm.db``. Neither named its path, so
neither could be checked. ``test_two_stores_...`` below reproduces exactly that
setup and asserts the thing that would have prevented it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from hoops_gm.availability.coverage import (
    LedgerSchemaMissing,
    StoreIdentity,
    measure_coverage,
)
from hoops_gm.core.config import Settings
from hoops_gm.db.base import Base
from hoops_gm.db.models import (
    DnpReason,
    ExternalSource,
    GameStatus,
    NbaGame,
    NbaTeam,
    ParticipationOutcome,
    Player,
    PlayerGameLog,
    PlayerParticipation,
    SeasonType,
)
from hoops_gm.db.session import Database, missing_local_store, render_store_url

SEASON = "2025-26"


# --- builders ---------------------------------------------------------------


def _teams(session: Session) -> tuple[NbaTeam, NbaTeam]:
    team = NbaTeam(nba_team_id=1, abbreviation="AAA", name="Alpha")
    opponent = NbaTeam(nba_team_id=2, abbreviation="OPP", name="Opponent")
    session.add_all([team, opponent])
    session.flush()
    return team, opponent


def _player(session: Session, name: str) -> Player:
    player = Player(full_name=name, normalized_name=name.lower().replace(" ", ""))
    session.add(player)
    session.flush()
    return player


def _game(
    session: Session,
    *,
    number: int,
    game_date: date,
    team: NbaTeam,
    opponent: NbaTeam,
    season: str = SEASON,
    status: GameStatus = GameStatus.FINAL,
) -> NbaGame:
    game = NbaGame(
        season=season,
        season_type=SeasonType.REGULAR,
        nba_game_id=f"00225{number:05d}",
        game_date=game_date,
        status=status,
        home_team_id=team.id,
        away_team_id=opponent.id,
    )
    session.add(game)
    session.flush()
    return game


def _participation(
    session: Session,
    *,
    player: Player,
    game: NbaGame,
    team: NbaTeam,
    outcome: ParticipationOutcome = ParticipationOutcome.PLAYED,
    reason: DnpReason = DnpReason.NONE_GIVEN,
    inactive_list_available: bool = True,
) -> PlayerParticipation:
    row = PlayerParticipation(
        player_id=player.id,
        game_id=game.id,
        team_id=team.id,
        outcome=outcome,
        reason=reason,
        raw_comment="",
        source=ExternalSource.NBA,
        inactive_list_available=inactive_list_available,
    )
    session.add(row)
    session.flush()
    return row


# --- the store is never separable from the count ----------------------------


def test_every_rendered_count_is_preceded_by_the_store_it_came_from(
    session: Session,
) -> None:
    team, opponent = _teams(session)
    player = _player(session, "Alpha Player")
    game = _game(session, number=1, game_date=date(2025, 10, 21), team=team, opponent=opponent)
    _participation(session, player=player, game=game, team=team)

    coverage = measure_coverage(session)
    rendered = coverage.render()

    assert coverage.store.describe() in rendered
    # The store line is the second line, above every number in the report.
    assert rendered.splitlines()[1].strip().startswith("store:")
    assert coverage.rows == 1


def test_the_json_form_carries_the_store_too(session: Session) -> None:
    team, opponent = _teams(session)
    player = _player(session, "Alpha Player")
    game = _game(session, number=1, game_date=date(2025, 10, 21), team=team, opponent=opponent)
    _participation(session, player=player, game=game, team=team)

    payload = measure_coverage(session).to_dict()

    assert set(payload) == {"store", "seasons", "totals"}
    assert payload["store"]["dialect"]
    assert payload["totals"]["rows"] == 1
    assert "outcomes" not in payload["seasons"][0]
    assert "reasons" not in payload["seasons"][0]


def test_public_text_withholds_outcome_and_reason_marginals(session: Session) -> None:
    team, opponent = _teams(session)
    player = _player(session, "Alpha Player")
    game = _game(session, number=1, game_date=date(2025, 10, 21), team=team, opponent=opponent)
    _participation(
        session,
        player=player,
        game=game,
        team=team,
        outcome=ParticipationOutcome.DID_NOT_PLAY,
        reason=DnpReason.COACHES_DECISION,
    )

    coverage = measure_coverage(session)
    assert coverage.seasons[0].outcomes
    assert coverage.seasons[0].reasons
    rendered = coverage.render()
    assert "outcomes" not in rendered
    assert "reasons" not in rendered
    assert ParticipationOutcome.DID_NOT_PLAY.value not in rendered
    assert DnpReason.COACHES_DECISION.value not in rendered


def test_two_stores_with_the_same_basename_each_report_their_own_path(
    tmp_path: Path,
) -> None:
    """The 2026-08-22 contradiction, reproduced and then made checkable.

    Two databases, both named ``hoops_gm.db``, exactly as two worktrees
    produce under the default relative SQLite URL. One populated, one empty.
    Both counts are correct; only the path distinguishes them.
    """
    populated_dir = tmp_path / "worktree-a"
    empty_dir = tmp_path / "worktree-b"
    populated_dir.mkdir()
    empty_dir.mkdir()

    def build(root: Path) -> Database:
        settings = Settings(
            environment="test",
            database_url=f"sqlite:///{(root / 'hoops_gm.db').as_posix()}",
            _env_file=None,
        )
        database = Database.from_settings(settings)
        Base.metadata.create_all(database.engine)
        return database

    populated = build(populated_dir)
    empty = build(empty_dir)
    try:
        with populated.session() as write:
            team, opponent = _teams(write)
            player = _player(write, "Alpha Player")
            game = _game(
                write, number=1, game_date=date(2025, 10, 21), team=team, opponent=opponent
            )
            _participation(write, player=player, game=game, team=team)

        with populated.session() as read:
            populated_coverage = measure_coverage(read)
        with empty.session() as read:
            empty_coverage = measure_coverage(read)

        # Same basename, and that is the whole problem.
        assert Path(populated_coverage.store.local_path or "").name == "hoops_gm.db"
        assert Path(empty_coverage.store.local_path or "").name == "hoops_gm.db"

        # Different counts, and each one carries the path that produced it.
        assert populated_coverage.rows == 1
        assert populated_coverage.is_populated
        assert empty_coverage.rows == 0
        assert not empty_coverage.is_populated
        assert populated_coverage.store.local_path != empty_coverage.store.local_path
    finally:
        populated.dispose()
        empty.dispose()


# --- an unobserved game is reported, never omitted ---------------------------


def test_a_final_game_with_no_participation_row_is_counted_and_dated(
    session: Session,
) -> None:
    """ "No observation" must not read as "nobody played"."""
    team, opponent = _teams(session)
    player = _player(session, "Alpha Player")
    observed = _game(session, number=1, game_date=date(2025, 10, 21), team=team, opponent=opponent)
    _game(session, number=2, game_date=date(2025, 11, 19), team=team, opponent=opponent)
    _participation(session, player=player, game=observed, team=team)

    season = measure_coverage(session).seasons[0]

    assert season.games_final == 2
    assert season.games_observed == 1
    assert season.games_unobserved == 1
    assert season.unobserved_dates == ("2025-11-19",)
    assert not season.is_complete
    assert season.observed_fraction == pytest.approx(0.5)


def test_a_scheduled_game_is_not_counted_as_an_observation_gap(session: Session) -> None:
    """A game that has not been played yet is not a hole in the ledger."""
    team, opponent = _teams(session)
    player = _player(session, "Alpha Player")
    played = _game(session, number=1, game_date=date(2025, 10, 21), team=team, opponent=opponent)
    _game(
        session,
        number=2,
        game_date=date(2026, 4, 12),
        team=team,
        opponent=opponent,
        status=GameStatus.SCHEDULED,
    )
    _participation(session, player=player, game=played, team=team)

    season = measure_coverage(session).seasons[0]

    assert season.games_total == 2
    assert season.games_final == 1
    assert season.games_unobserved == 0
    assert season.is_complete


def test_absences_are_rows_rather_than_missing_rows(session: Session) -> None:
    """The distinction the availability thesis rests on, counted explicitly."""
    team, opponent = _teams(session)
    played = _player(session, "Played Guy")
    sat = _player(session, "Sat Guy")
    game = _game(session, number=1, game_date=date(2025, 10, 21), team=team, opponent=opponent)
    _participation(session, player=played, game=game, team=team)
    _participation(
        session,
        player=sat,
        game=game,
        team=team,
        outcome=ParticipationOutcome.DID_NOT_PLAY,
        reason=DnpReason.COACHES_DECISION,
    )

    season = measure_coverage(session).seasons[0]

    assert season.games_unobserved == 0
    assert season.outcomes == {"played": 1, "did_not_play": 1}
    assert season.reasons == {"none_given": 1, "coaches_decision": 1}
    assert season.rows == 2


def test_an_unoffered_inactive_list_is_distinguished_from_an_empty_one(
    session: Session,
) -> None:
    team, opponent = _teams(session)
    player = _player(session, "Alpha Player")
    game = _game(session, number=1, game_date=date(2025, 10, 21), team=team, opponent=opponent)
    _participation(session, player=player, game=game, team=team, inactive_list_available=False)

    season = measure_coverage(session).seasons[0]

    assert season.rows == 1
    assert season.rows_with_inactive_list == 0


# --- totals ------------------------------------------------------------------


def test_distinct_players_across_seasons_is_measured_rather_than_summed(
    session: Session,
) -> None:
    """One player in two seasons is one player, not two."""
    team, opponent = _teams(session)
    player = _player(session, "Alpha Player")
    first = _game(session, number=1, game_date=date(2025, 10, 21), team=team, opponent=opponent)
    second = _game(
        session,
        number=2,
        game_date=date(2024, 10, 22),
        team=team,
        opponent=opponent,
        season="2024-25",
    )
    _participation(session, player=player, game=first, team=team)
    _participation(session, player=player, game=second, team=team)

    coverage = measure_coverage(session)

    assert [season.season for season in coverage.seasons] == ["2024-25", "2025-26"]
    assert sum(season.distinct_players for season in coverage.seasons) == 2
    assert coverage.distinct_players == 1
    assert coverage.rows == 2


def test_box_score_rows_are_reported_beside_participation_rows(session: Session) -> None:
    """Production and participation are separate counts and stay separate."""
    team, opponent = _teams(session)
    played = _player(session, "Played Guy")
    sat = _player(session, "Sat Guy")
    game = _game(session, number=1, game_date=date(2025, 10, 21), team=team, opponent=opponent)
    _participation(session, player=played, game=game, team=team)
    _participation(session, player=sat, game=game, team=team, outcome=ParticipationOutcome.INACTIVE)
    session.add(
        PlayerGameLog(
            player_id=played.id,
            game_id=game.id,
            team_id=team.id,
            seconds_played=1800,
            points=10,
            rebounds=5,
            assists=4,
            steals=1,
            blocks=0,
            turnovers=2,
            three_pointers_made=2,
            field_goals_made=5,
            field_goals_attempted=10,
            free_throws_made=0,
            free_throws_attempted=0,
        )
    )
    session.flush()

    season = measure_coverage(session).seasons[0]

    assert season.rows == 2
    assert season.box_score_rows == 1


def test_an_empty_ledger_reports_empty_rather_than_raising(session: Session) -> None:
    coverage = measure_coverage(session)

    assert coverage.seasons == ()
    assert coverage.rows == 0
    assert coverage.distinct_players == 0
    assert not coverage.is_populated
    assert "NO PARTICIPATION ROWS" in coverage.render()
    assert coverage.store.describe() in coverage.render()


# --- failure modes -----------------------------------------------------------


def test_a_store_without_the_schema_names_the_store_it_checked(tmp_path: Path) -> None:
    """The most likely first run of this tool: a fresh, unmigrated worktree."""
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'hoops_gm.db').as_posix()}",
        _env_file=None,
    )
    database = Database.from_settings(settings)
    try:
        with pytest.raises(LedgerSchemaMissing) as caught, database.session() as session:
            measure_coverage(session)
        assert "hoops_gm.db" in str(caught.value)
        assert "player_participation" in str(caught.value)
        assert caught.value.store.local_path is not None
    finally:
        database.dispose()


def test_an_absent_local_store_is_reported_without_being_created(tmp_path: Path) -> None:
    """A read-only report must not manufacture the store it is reporting on.

    SQLite creates a database on connect rather than refusing, so a mistyped
    path would otherwise yield a new empty file and a count that is honest,
    reproducible and meaningless — a fresh false zero, produced by the very
    check meant to settle one.
    """
    absent = tmp_path / "not-here" / "hoops_gm.db"

    reported = missing_local_store(f"sqlite:///{absent.as_posix()}")

    assert reported == str(absent)
    assert not absent.exists()
    assert not absent.parent.exists()


def test_an_existing_local_store_is_not_reported_as_missing(tmp_path: Path) -> None:
    present = tmp_path / "hoops_gm.db"
    present.write_bytes(b"")

    assert missing_local_store(f"sqlite:///{present.as_posix()}") is None


def test_a_server_backed_store_is_never_reported_as_missing() -> None:
    """Only a local file can be checked this cheaply; a server speaks for itself."""
    assert missing_local_store("postgresql+psycopg://h/db") is None
    assert missing_local_store("sqlite:///:memory:") is None


def test_a_password_never_reaches_the_rendered_store(session: Session) -> None:
    """Naming the store must not become a way to leak a credential."""
    safe, local_path = render_store_url(
        make_url("postgresql+psycopg://hoops:ho%25ops%23pw@127.0.0.1:5432/hoops_gm")
    )

    assert "ho%ops#pw" not in safe
    assert "ho%25ops%23pw" not in safe
    assert "***" in safe
    assert "127.0.0.1:5432/hoops_gm" in safe
    assert local_path is None


def test_an_in_memory_store_has_no_path_but_still_has_a_url() -> None:
    safe, local_path = render_store_url(make_url("sqlite:///:memory:"))

    assert local_path is None
    assert "memory" in safe


def test_describe_says_so_when_a_store_has_no_migration_stamp() -> None:
    identity = StoreIdentity(
        url="sqlite:///x.db", dialect="sqlite", local_path="/x.db", alembic_revision=None
    )

    assert "no alembic_version row" in identity.describe()
