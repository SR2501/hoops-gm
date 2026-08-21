from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from hoops_gm.calendar import (
    ScoringPeriodProjectionResult,
    StaleScoringPeriodProjectionError,
    activate_deadline_calendar,
    derive_deadline_calendar,
    project_scoring_periods,
    scoring_period_artifact_key,
)
from hoops_gm.db.lineage import (
    NBA_SCHEDULE_ARTIFACT_KEY,
    SCHEDULE_COMPLETENESS_SUMMARY_KEY,
    PendingScheduleGame,
    check_cohort,
    current_refresh,
    lock_refresh_scope,
    record_refresh,
    schedule_completeness,
    schedule_content_version,
    verify_refresh,
)
from hoops_gm.db.models.enums import RefreshArtifactType, SeasonType
from hoops_gm.db.models.identity import NbaTeam
from hoops_gm.db.models.league import League, ScoringPeriod
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.importers import (
    import_games,
    import_league_settings,
    import_schedule,
    import_teams,
)
from hoops_gm.ingest.league_settings import (
    BRIDGE_SOURCE,
    PlayoffRules,
    SettingEvidence,
    SourcedSetting,
    parse_official_league_settings,
)
from hoops_gm.ingest.nba import (
    NbaStatsClient,
    NbaTeamRecord,
    ScheduleParseResult,
    build_schedule_density,
    parse_schedule,
    parse_teams,
    playoff_scheduled_game_counts,
    scheduled_game_counts,
)
from hoops_gm.ingest.nba.schedule import _plausible_season_date

pytestmark = pytest.mark.adapter_contract
FIXTURES = Path(__file__).resolve().parent / "fixtures"
EASTERN = ZoneInfo("America/New_York")

#: The whole-object slice. ``nba_scheduleleaguev2_2026_27.json`` is
#: field-trimmed and its team blocks carry four keys, so it cannot show what
#: the source publishes for an undecided team; this one can, and holds all six
#: of the 2026-27 season's pending games.
PENDING_FIXTURE = "nba_scheduleleaguev2_2026_27_pending_knockout.json"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def resolved_schedule_payload() -> Any:
    """The recorded payload with the not-yet-drawn Cup games dropped.

    Kept, post-ADR-013, for the tests that need a cohort with *no* pending
    games — the invariants about resolved counts and persisted rows are
    clearer stated against one. It is no longer a workaround: the unfiltered
    payload imports perfectly well now, and
    ``test_schedule_import_records_source_declared_pending_games_without_refusing``
    is what proves it.
    """

    payload = load("nba_scheduleleaguev2_2026_27.json")
    for game_date in payload["leagueSchedule"]["gameDates"]:
        game_date["games"] = [
            game
            for game in game_date["games"]
            if game["homeTeam"]["teamId"] != 0 and game["awayTeam"]["teamId"] != 0
        ]
    return payload


def import_schedule_teams(session: Session, result: Any) -> None:
    team_ids = {
        team_id
        for record in result.games
        for team_id in (record.home_nba_team_id, record.away_nba_team_id)
    }
    import_teams(
        session,
        [
            NbaTeamRecord(team_id, f"T{team_id % 10_000_000:07d}", f"Team {team_id}")
            for team_id in sorted(team_ids)
        ],
    )


def test_schedule_fixture_resolves_games_and_reconciles_the_two_time_fields() -> None:
    result = parse_schedule(load("nba_scheduleleaguev2_2026_27.json"), season="2026-27")

    assert result.source_game_count == 12
    assert len(result.games) == 10
    assert result.pending_game_ids == ("0022601201", "0022601202")
    assert result.unresolved_game_ids == ()
    assert result.games[0].game.game_date == date(2026, 10, 20)
    assert result.games[0].game.tipoff_utc is not None
    assert result.games[0].game.tipoff_utc.hour == 19


def test_schedule_team_ids_and_tricodes_agree_with_static_team_source() -> None:
    result = parse_schedule(load("nba_scheduleleaguev2_2026_27.json"), season="2026-27")
    static = {
        team.nba_team_id: team.abbreviation for team in parse_teams(load("nba_static_teams.json"))
    }

    for record in result.games:
        assert static[record.home_nba_team_id] == record.home_tricode
        assert static[record.away_nba_team_id] == record.away_tricode


def test_schedule_parser_rejects_a_mismatched_time_sibling() -> None:
    payload = load("nba_scheduleleaguev2_2026_27.json")
    payload["leagueSchedule"]["gameDates"][0]["games"][0]["gameDateTimeUTC"] = (
        "2026-10-20T20:00:00Z"
    )

    with pytest.raises(SourceContractError, match="inconsistent EST/UTC"):
        parse_schedule(payload, season="2026-27")


def test_schedule_client_uses_the_official_schedule_endpoint() -> None:
    calls: list[dict[str, object]] = []

    class Endpoint:
        def get_dict(self) -> dict[str, object]:
            return {"leagueSchedule": {"seasonYear": "2026-27", "gameDates": []}}

    def factory(endpoint: str, **kwargs: object) -> Endpoint:
        calls.append({"endpoint": endpoint, **kwargs})
        return Endpoint()

    client = NbaStatsClient(endpoint_factory=factory)
    client.schedule_league(season="2026-27")

    assert calls == [
        {
            "endpoint": "ScheduleLeagueV2",
            "timeout": 60.0,
            "league_id": "00",
            "season": "2026-27",
        }
    ]


def test_schedule_import_is_idempotent_and_counts_against_scoring_periods(session: Any) -> None:
    result = parse_schedule(resolved_schedule_payload(), season="2026-27")
    team_ids = {
        team_id
        for record in result.games
        for team_id in (record.home_nba_team_id, record.away_nba_team_id)
    }
    import_schedule_teams(session, result)
    league = League(
        name="Test league",
        season="2026-27",
        fantrax_league_id="schedule-import-test",
        scoring_type="h2h_categories",
        draft_type="auction",
    )
    session.add(league)
    session.flush()

    first = import_schedule(session, result)
    second = import_schedule(session, result)
    projection = _project_periods(
        session,
        league,
        [(1, date(2026, 10, 19), date(2026, 10, 25), True)],
    )
    counts = scheduled_game_counts(session, league_id=league.id, season="2026-27")
    refresh = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key="nba-schedule",
        season="2026-27",
    )

    assert first.created == 30
    assert second.updated == 30
    assert refresh is not None
    assert session.scalars(select(TeamScheduleEntry)).all()
    assert len(counts) == len(team_ids)
    assert sum(row.games for row in counts) == 6
    assert {row.games for row in counts} == {0, 1}
    assert {row.schedule_version for row in counts} == {refresh.version}
    assert {row.schedule_refreshed_at for row in counts} == {refresh.refreshed_at}
    assert {row.schedule_refresh_id for row in counts} == {refresh.id}
    assert {row.projection_version for row in counts} == {projection.lineage.projection_version}
    assert {row.projection_refresh_id for row in counts} == {
        projection.lineage.projection_refresh_id
    }


def test_schedule_import_registers_a_refresh_that_converges_on_re_import(session: Any) -> None:
    """The schedule refresh registry is a side effect of ``import_schedule``.

    A re-import that changes nothing must not invent a new schedule cohort:
    downstream ``schedule_version`` stamps (``schedule_context.py``) would
    otherwise go stale for no reason every time the importer merely confirms
    what it already knew.
    """
    result = parse_schedule(resolved_schedule_payload(), season="2026-27")
    import_schedule_teams(session, result)

    import_schedule(session, result)
    first_run = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key="nba-schedule",
        season="2026-27",
    )
    assert first_run is not None
    assert first_run.season == "2026-27"
    assert first_run.summary["team_schedule_rows"] == 20

    import_schedule(session, result)
    second_run = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key="nba-schedule",
        season="2026-27",
    )
    assert second_run is not None

    assert second_run.id == first_run.id, "identical facts must not open a new cohort"
    assert second_run.version == first_run.version
    assert second_run.refreshed_at >= first_run.refreshed_at

    entries = session.scalars(
        select(TeamScheduleEntry).where(
            TeamScheduleEntry.season == "2026-27",
            TeamScheduleEntry.season_type == SeasonType.REGULAR,
        )
    ).all()
    density = build_schedule_density(
        entries,
        schedule_version=second_run.version,
        schedule_refreshed_at=second_run.refreshed_at,
    )

    assert {row.schedule_version for row in density} == {second_run.version}
    assert {row.schedule_refreshed_at for row in density} == {second_run.refreshed_at}
    assert (
        check_cohort(session, schedule_version=density[0].schedule_version)[0].status == "current"
    )

    stale_density = build_schedule_density(
        entries,
        schedule_version="stale-schedule-version",
        schedule_refreshed_at=second_run.refreshed_at,
    )
    assert (
        check_cohort(session, schedule_version=stale_density[0].schedule_version)[0].status
        == "stale"
    )


def test_schedule_refresh_summary_records_auditable_source_completeness(session: Any) -> None:
    """ "Why is this the current schedule cohort" must be answerable from the row.

    The counts the source itself reported, what resolved, what did not, and
    what was actually persisted — without them, a refresh row asserts a
    complete season on nothing but the importer's word.
    """
    result = parse_schedule(resolved_schedule_payload(), season="2026-27")
    import_schedule_teams(session, result)

    import_schedule(session, result)
    run = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        season="2026-27",
    )

    assert run is not None
    assert run.source == "nba_api:ScheduleLeagueV2"
    assert run.summary[SCHEDULE_COMPLETENESS_SUMMARY_KEY] == {
        "season": "2026-27",
        "season_type": "regular",
        "source_game_count": 10,
        "resolved_game_count": 10,
        "unresolved_game_ids": [],
        "pending_game_ids": [],
        "pending_games": [],
        "persisted_team_row_count": 20,
    }
    completeness = schedule_completeness(run.summary)
    assert completeness is not None
    assert completeness.season_type is SeasonType.REGULAR
    assert completeness.source_game_count == completeness.resolved_game_count
    assert run.version == schedule_content_version(session, season="2026-27")


def test_schedule_import_records_source_declared_pending_games_without_refusing(
    session: Any,
) -> None:
    """ADR-013: a game the source has not drawn yet is recorded, not refused.

    Driven against the unfiltered recorded payload — the same twelve games the
    pre-ADR-013 importer refused outright. The registered block must account
    for all twelve, persist rows for only the ten that resolved, and name the
    two it did not so that no consumer has to infer them from a subtraction.
    """
    result = parse_schedule(load("nba_scheduleleaguev2_2026_27.json"), season="2026-27")
    import_schedule_teams(session, result)

    import_schedule(session, result)
    run = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        season="2026-27",
    )

    assert run is not None
    block = run.summary[SCHEDULE_COMPLETENESS_SUMMARY_KEY]
    assert block == {
        "season": "2026-27",
        "season_type": "regular",
        "source_game_count": 12,
        "resolved_game_count": 10,
        "persisted_team_row_count": 20,
        "unresolved_game_ids": [],
        "pending_game_ids": ["0022601201", "0022601202"],
        "pending_games": [
            {
                "nba_game_id": "0022601201",
                "game_date": "2026-12-04",
                "game_label": "Emirates NBA Cup",
                "game_sub_label": "",
                "game_subtype": "",
                "date_absence_reason": "",
            },
            {
                "nba_game_id": "0022601202",
                "game_date": "2026-12-04",
                "game_label": "Emirates NBA Cup",
                "game_sub_label": "",
                "game_subtype": "",
                "date_absence_reason": "",
            },
        ],
    }

    completeness = schedule_completeness(run.summary)
    assert completeness is not None
    assert completeness.source_game_count == completeness.resolved_game_count + len(
        completeness.pending_game_ids
    )
    # The pending games are recorded, and deliberately have no schedule rows:
    # a game with no teams cannot have a team_schedule row without inventing
    # the attribution the source withheld.
    persisted = _persisted_schedule_rows(session, "2026-27")
    assert {row[0] for row in persisted}.isdisjoint(completeness.pending_game_ids)
    assert len(persisted) == 20


def test_schedule_parser_reads_every_pending_game_in_the_real_season() -> None:
    """The whole-object fixture, which is the one that can show a null team block.

    ``nba_scheduleleaguev2_2026_27.json`` is field-trimmed and cannot: its team
    blocks were reduced to four keys, so it says nothing about ``teamSlug`` or
    the labels. This fixture keeps the source's own objects, and holds all six
    of the 2026-27 season's pending games.
    """
    result = parse_schedule(load(PENDING_FIXTURE), season="2026-27")

    assert result.source_game_count == 24
    assert len(result.games) == 18
    assert result.unresolved_game_ids == ()
    assert result.pending_game_ids == (
        "0022601201",
        "0022601202",
        "0022601203",
        "0022601204",
        "0022601229",
        "0022601230",
    )
    assert result.source_game_count == len(result.games) + len(result.pending_games)
    labels = [
        (game.game_date, game.game_label, game.game_sub_label) for game in result.pending_games
    ]
    assert labels == [
        (date(2026, 12, 4), "Emirates NBA Cup", "Quarterfinal"),
        (date(2026, 12, 4), "Emirates NBA Cup", "Quarterfinal"),
        (date(2026, 12, 5), "Emirates NBA Cup", "Quarterfinal"),
        (date(2026, 12, 5), "Emirates NBA Cup", "Quarterfinal"),
        (date(2026, 12, 8), "Emirates NBA Cup", "Semifinal"),
        (date(2026, 12, 8), "Emirates NBA Cup", "Semifinal"),
    ]
    assert {game.game_subtype for game in result.pending_games} == {"in-season-knockout"}


def test_a_degenerate_pending_date_does_not_cost_the_whole_season() -> None:
    """Reproduces the defect a reviewer found: one bad date returned no season.

    Under the strict reconciliation this raised out of `parse_schedule`, so a
    single unreconcilable timestamp on a single undrawn Cup fixture returned
    **nothing** — not 1,200 games with one flagged, not even a `--dry-run`
    view. That is ADR-013's explicitly rejected outcome arriving through a
    different field, and the source argues it is reachable: every pending game
    carries `seriesText: "Date subject to change"`, and these same objects
    already use a degenerate year-0001 sentinel for `gameTimeEst`.

    Three shapes, because the mutation must reproduce the failure rather than
    a neighbour of it: a date that disagrees with its UTC sibling, one that is
    unparseable, and one that is absent entirely.
    """
    for mutation in ("disagree", "unparseable", "absent"):
        payload = load(PENDING_FIXTURE)
        hits = 0
        for game_date in payload["leagueSchedule"]["gameDates"]:
            for game in game_date["games"]:
                if game["gameId"] != "0022601229":
                    continue
                hits += 1
                if mutation == "disagree":
                    game["gameDateTimeEst"] = "2026-12-08T00:30:00Z"
                elif mutation == "unparseable":
                    game["gameDateTimeEst"] = "the eighth of December"
                else:
                    del game["gameDateTimeEst"]
        assert hits == 1, mutation

        result = parse_schedule(payload, season="2026-27")

        assert len(result.games) == 18, f"{mutation} cost resolved games"
        assert len(result.pending_games) == 6, f"{mutation} cost a pending game"
        assert result.unresolved_game_ids == ()
        degraded = {
            game.nba_game_id: game.date_absence_reason
            for game in result.pending_games
            if game.game_date is None
        }
        expected_reason = {
            "disagree": "irreconcilable",
            "unparseable": "unreadable",
            # Deleting only the Eastern field leaves the UTC one carrying a
            # date, so the source HAS committed and we cannot read it in the
            # shape this parser needs. That is a fault, not an undecided
            # bracket -- the correction a reviewer forced, and this
            # expectation is the one that was wrong before it.
            "absent": "unreadable",
        }[mutation]
        assert degraded == {"0022601229": expected_reason}, mutation
        # Every other pending game keeps its date; the leniency is per game,
        # not a blanket loss of the field.
        assert all(
            game.game_date is not None and game.date_absence_reason == ""
            for game in result.pending_games
            if game.nba_game_id != "0022601229"
        )


def test_the_four_causes_of_a_missing_pending_date_are_not_conflated() -> None:
    """``None`` alone said "not yet decided" where that is false three times in four.

    One ``except`` covered both time parses, so a null date meant any of: the
    source declined to give a date, the source gave one we could not read, or
    the source's two fields contradict each other. **Only the first is "not
    yet decided."** The conflation ran in the comforting direction — told the
    source has not decided, an operator waits; told the date could not be
    read, an operator investigates — and it sat inside the very field added so
    a published fact would not be reported as a fault.

    Two of these cases are here because a reviewer proved the first attempt
    wrong, and both are worth naming:

    ``half_published`` — the source gives the date in one field and withholds
    the sibling. The first fix returned ``not_offered`` if *either* field was
    empty, so the canonical example of "the source declined to give a date"
    was a payload in which the source gives the date. That is the same
    conflation one level down, in the same comforting direction.

    ``implausible`` — both fields agree on a date in 1900. **Agreement is not
    validity.** The NBA uses a ``1900-01-01`` epoch as a live placeholder for
    ``gameTimeEst`` on every resolved game in this very fixture, and a
    placeholder pair in the *date* fields reconciles exactly, because 1900's
    Eastern offset really is -05:00. It would have been recorded as a decided
    date in 1900 with no reason at all — strictly worse than ``None``, which
    at least says we do not know.
    """

    def _clear_both(game: dict[str, Any]) -> None:
        game["gameDateTimeEst"] = ""
        game["gameDateTimeUTC"] = ""

    def _epoch_placeholder(game: dict[str, Any]) -> None:
        game["gameDateTimeEst"] = "1900-01-01T00:00:00Z"
        game["gameDateTimeUTC"] = "1900-01-01T05:00:00Z"

    causes: dict[str, Callable[[dict[str, Any]], None]] = {
        "not_offered": _clear_both,
        "unreadable": lambda g: g.__setitem__("gameDateTimeEst", "not a timestamp"),
        "irreconcilable": lambda g: g.__setitem__("gameDateTimeEst", "2026-12-08T00:30:00Z"),
        "implausible": _epoch_placeholder,
    }
    # Named separately because it is the case that must NOT be `not_offered`.
    half_published: dict[str, Callable[[dict[str, Any]], None]] = {
        "unreadable": lambda g: g.__setitem__("gameDateTimeUTC", ""),
    }

    for expected, mutate in {**causes, **half_published}.items():
        payload = load(PENDING_FIXTURE)
        for game_date in payload["leagueSchedule"]["gameDates"]:
            for game in game_date["games"]:
                if game["gameId"] == "0022601229":
                    mutate(game)

        result = parse_schedule(payload, season="2026-27")

        by_id = {game.nba_game_id: game for game in result.pending_games}
        assert by_id["0022601229"].date_absence_reason == expected
        assert by_id["0022601229"].game_date is None
        # A game that kept its date carries no reason: the two halves of the
        # same fact must never disagree.
        assert by_id["0022601201"].date_absence_reason == ""
        assert by_id["0022601201"].game_date is not None


def test_a_date_published_in_one_field_only_is_a_fault_not_an_undecided_bracket() -> None:
    """The reviewer's N2, driven per field rather than per cause.

    Both directions, because the first fix looped the two keys and returned
    on the first empty one — so whichever field happened to be checked first
    decided the answer. A source that publishes the date in either field has
    committed to a date; failing to read it is our problem to investigate, not
    a bracket to wait for.
    """
    for withheld, kept in (
        ("gameDateTimeUTC", "gameDateTimeEst"),
        ("gameDateTimeEst", "gameDateTimeUTC"),
    ):
        payload = load(PENDING_FIXTURE)
        for game_date in payload["leagueSchedule"]["gameDates"]:
            for game in game_date["games"]:
                if game["gameId"] == "0022601229":
                    assert game[kept], "the kept field must actually carry a date"
                    del game[withheld]

        result = parse_schedule(payload, season="2026-27")

        by_id = {game.nba_game_id: game for game in result.pending_games}
        assert by_id["0022601229"].date_absence_reason == "unreadable", (
            f"withholding {withheld} while {kept} carries a date is the source having "
            "committed, so it must not read as not_offered"
        )


def test_a_reconciling_epoch_placeholder_is_not_a_decided_date() -> None:
    """Agreement is not validity, and this source really does use epoch placeholders.

    Driven from the fixture's own evidence rather than an invented shape: the
    resolved games in it carry ``gameTimeEst: 1900-01-01T...`` today. The same
    convention applied to the date fields produces a pair that reconciles
    perfectly and would otherwise be recorded as a real, decided date.
    """
    payload = load(PENDING_FIXTURE)
    resolved_placeholders = {
        game["gameTimeEst"][:10]
        for entry in payload["leagueSchedule"]["gameDates"]
        for game in entry["games"]
        if game["homeTeam"]["teamId"] != 0
    }
    assert resolved_placeholders == {"1900-01-01"}, (
        "this test's premise is that the source uses a 1900 epoch placeholder; "
        f"it now uses {resolved_placeholders}"
    )

    for entry in payload["leagueSchedule"]["gameDates"]:
        for game in entry["games"]:
            if game["gameId"] == "0022601229":
                game["gameDateTimeEst"] = "1900-01-01T00:00:00Z"
                game["gameDateTimeUTC"] = "1900-01-01T05:00:00Z"

    result = parse_schedule(payload, season="2026-27")
    by_id = {game.nba_game_id: game for game in result.pending_games}

    assert by_id["0022601229"].game_date is None
    assert by_id["0022601229"].date_absence_reason == "implausible"
    assert len(result.games) == 18, "the season must survive a placeholder date"


def test_an_out_of_range_timestamp_does_not_escape_as_an_overflow() -> None:
    """The lenient path caught only `SourceContractError`, and that was not enough.

    `datetime.astimezone` raises `OverflowError` — not a `SourceContractError`
    — when a conversion falls outside `datetime.min`/`max`. So a pending game
    with a year-0001 value one non-UTC offset from the boundary propagated an
    `OverflowError` straight out of `parse_schedule` and cost the whole
    season, which is precisely the outcome this function exists to prevent,
    arriving through the exception type rather than the field.

    Not hypothetical: **year-0001 is the sentinel this source already emits**
    for undecided times, on all six pending games in the recorded fixture.
    """
    boundary_shapes = (
        ("gameDateTimeUTC", "0001-01-01T00:00:00+05:00"),
        ("gameDateTimeEst", "9999-12-31T23:59:59"),
    )
    for field, value in boundary_shapes:
        payload = load(PENDING_FIXTURE)
        for game_date in payload["leagueSchedule"]["gameDates"]:
            for game in game_date["games"]:
                if game["gameId"] == "0022601229":
                    game[field] = value

        result = parse_schedule(payload, season="2026-27")

        by_id = {game.nba_game_id: game for game in result.pending_games}
        assert len(result.games) == 18, f"{field}={value} cost the season"
        assert by_id["0022601229"].game_date is None
        assert by_id["0022601229"].date_absence_reason == "unreadable"


def test_a_pending_record_cannot_be_built_with_an_absence_and_no_reason() -> None:
    """The producer must not be able to construct what the reader refuses.

    `_pending_games` enforces "date absent iff reason present" on read-back.
    Without the same check on construction the producer type is strictly wider
    than the reader accepts, so `as_summary()` could serialise a block that
    can never be read again — a row that is written successfully and then
    turns the schedule-grid read path into a hard error.
    """
    with pytest.raises(ValueError, match="game_date absent"):
        PendingScheduleGame(
            nba_game_id="0022601201",
            game_date=None,
            game_label="Emirates NBA Cup",
            game_sub_label="Quarterfinal",
            game_subtype="in-season-knockout",
        )
    with pytest.raises(ValueError, match="game_date present"):
        PendingScheduleGame(
            nba_game_id="0022601201",
            game_date=date(2026, 12, 4),
            game_label="Emirates NBA Cup",
            game_sub_label="Quarterfinal",
            game_subtype="in-season-knockout",
            date_absence_reason="not_offered",
        )


def test_a_reconciling_epoch_placeholder_on_a_RESOLVED_game_refuses_the_season() -> None:
    """The half of the placeholder trap I fixed on the lenient path and not the strict one.

    A resolved game's date is **persisted**, joins ``player_participation``,
    and is the denominator of every expected-games number, so a placeholder
    that reconciles is far worse here than on the pending side — and the
    EST/UTC reconciliation cannot see it, because a placeholder *pair* agrees
    exactly. Verified before the fix: the parser returned a resolved game with
    ``game_date = 1900-01-01`` and imported it.

    Refused rather than degraded, because on this side a wrong date is
    indistinguishable from a real one downstream.
    """
    payload = load(PENDING_FIXTURE)
    for entry in payload["leagueSchedule"]["gameDates"]:
        for game in entry["games"]:
            if game["gameId"] == "0022600001":
                game["gameDateTimeEst"] = "1900-01-01T00:00:00Z"
                game["gameDateTimeUTC"] = "1900-01-01T05:00:00Z"

    with pytest.raises(SourceContractError, match="not in season 2026-27"):
        parse_schedule(payload, season="2026-27")


def test_every_real_game_in_the_fixture_is_inside_its_own_season_window() -> None:
    """The plausibility bound must not be able to refuse a legitimate game.

    Driven over the whole recorded cohort rather than a sampled date, because
    a bound that is wrong at an edge is wrong exactly where the season starts
    and ends — 2026-10-20 and 2027-04-11 here.
    """
    result = parse_schedule(load(PENDING_FIXTURE), season="2026-27")

    assert len(result.games) == 18
    assert all(_plausible_season_date(record.game.game_date, "2026-27") for record in result.games)
    assert all(game.date_absence_reason == "" for game in result.pending_games)


def test_a_degenerate_date_on_a_RESOLVED_game_still_kills_the_import() -> None:
    """The other half of the asymmetry, which is what makes it a judgement and not a hole.

    A resolved game's date is persisted, joins `player_participation`, and is
    the denominator of every expected-games number. Leniency there would be
    the mislabelled-field bug this project already ate once. Asserted so that
    anyone widening the pending leniency has to walk past this.
    """
    payload = load(PENDING_FIXTURE)
    for game_date in payload["leagueSchedule"]["gameDates"]:
        for game in game_date["games"]:
            if game["gameId"] == "0022600001":
                game["gameDateTimeEst"] = "2026-10-20T00:30:00Z"

    with pytest.raises(SourceContractError, match="inconsistent EST/UTC"):
        parse_schedule(payload, season="2026-27")


@pytest.mark.parametrize("field", ["teamName", "teamCity", "teamTricode", "teamSlug"])
def test_every_identity_field_alone_makes_a_zero_id_game_a_failure(field: str) -> None:
    """Each of the four naming fields must be load-bearing, not just the tricode.

    A reviewer narrowed `_TEAM_IDENTITY_FIELDS` to `("teamTricode",)` and 224
    tests stayed green — so three quarters of the guard was unexercised, and
    `teamSlug` is the field the whole-object fixture was added to make
    visible. Parametrised so removing any one field from the guard fails here.
    """
    payload = load(PENDING_FIXTURE)
    for game_date in payload["leagueSchedule"]["gameDates"]:
        for game in game_date["games"]:
            if game["gameId"] == "0022601229":
                assert game["homeTeam"][field] is None
                game["homeTeam"][field] = "Lakers" if field != "teamTricode" else "LAL"

    result = parse_schedule(payload, season="2026-27")

    assert result.unresolved_game_ids == ("0022601229",), (
        f"a zero teamId beside a populated {field} must be a resolution failure"
    )
    assert "0022601229" not in result.pending_game_ids


def test_a_zero_team_id_beside_a_named_team_is_a_failure_not_a_pending_game() -> None:
    """Mutation check for the guard ADR-013 keeps: reproduce the failure it guards.

    The distinction pending rests on is that the source withheld the identity
    *entirely*. If it names a team without giving an id, it has claimed an
    assignment we cannot resolve — indistinguishable from the parser losing a
    team, which is the 1,225-of-1,230 defect the completeness contract exists
    for. Constructed here by taking a real pending game and populating one
    naming field, which is precisely the payload shape that would otherwise
    slip through as "not yet decided".

    This mutation is also what keeps ``unresolved_game_ids`` reachable at all.
    Without this branch the parser could only resolve, zero out, or raise, and
    the importer's unresolved refusal would be a guard that reads correctly
    and can never fire.
    """
    payload = load(PENDING_FIXTURE)
    mutated = 0
    for game_date in payload["leagueSchedule"]["gameDates"]:
        for game in game_date["games"]:
            if game["gameId"] == "0022601229":
                assert game["homeTeam"]["teamId"] == 0
                assert game["homeTeam"]["teamTricode"] is None
                game["homeTeam"]["teamTricode"] = "LAL"
                mutated += 1
    assert mutated == 1, "the mutation must land on exactly the game it claims to mutate"

    result = parse_schedule(payload, season="2026-27")

    assert result.unresolved_game_ids == ("0022601229",)
    assert "0022601229" not in result.pending_game_ids
    assert len(result.pending_games) == 5
    assert result.source_game_count == 24


def test_import_refuses_the_mutated_cohort_the_parser_flagged(session: Any) -> None:
    """The second half of the mutation check: the refusal actually fires.

    A parser that classifies correctly and an importer that ignores the
    classification would be the same false comfort. Driven end to end rather
    than by constructing a ``ScheduleParseResult`` by hand, because a
    hand-built result is a shape no parser produces.
    """
    payload = load(PENDING_FIXTURE)
    for game_date in payload["leagueSchedule"]["gameDates"]:
        for game in game_date["games"]:
            if game["gameId"] == "0022601229":
                game["homeTeam"]["teamTricode"] = "LAL"
    result = parse_schedule(payload, season="2026-27")
    import_schedule_teams(session, result)

    with pytest.raises(SourceContractError, match="named but did not identify"):
        import_schedule(session, result)

    assert session.scalars(select(TeamScheduleEntry)).all() == []
    assert (
        current_refresh(
            session,
            RefreshArtifactType.SCHEDULE,
            artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
            season="2026-27",
        )
        is None
    )


def test_schedule_import_refuses_a_source_count_that_ignores_pending_games(
    session: Any,
) -> None:
    """The completeness invariant is ``resolved + pending``, and it is enforced.

    Mutation of the arithmetic rather than of the payload: a source count that
    exceeds resolved plus pending means games went missing between the source
    and the parse, which is the original defect regardless of how many are
    pending.
    """
    result = parse_schedule(load(PENDING_FIXTURE), season="2026-27")
    import_schedule_teams(session, result)

    with pytest.raises(SourceContractError, match="18 resolved and 6 are pending"):
        import_schedule(session, replace(result, source_game_count=25))

    assert session.scalars(select(TeamScheduleEntry)).all() == []


def test_the_schedule_version_does_not_change_when_only_the_pending_set_changes(
    session: Any,
) -> None:
    """A property worth pinning precisely because it is surprising.

    ``schedule_content_version`` fingerprints persisted ``team_schedule``
    rows, and a pending game has none — it has no teams, so there is nothing
    to persist. Two cohorts differing only in which games are pending
    therefore share a version, which means a consumer must not cache the
    pending set keyed on the version alone.

    Driven both ways round rather than asserted: import the filtered cohort,
    record the version, then import the recorded payload whose only
    difference is two pending games, and require the version to be unchanged
    while the completeness block is not.
    """
    filtered = parse_schedule(resolved_schedule_payload(), season="2026-27")
    import_schedule_teams(session, filtered)
    import_schedule(session, filtered)
    before = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        season="2026-27",
    )
    assert before is not None
    before_block = schedule_completeness(before.summary)
    assert before_block is not None
    assert before_block.pending_game_ids == ()
    before_version = before.version

    with_pending = parse_schedule(load("nba_scheduleleaguev2_2026_27.json"), season="2026-27")
    import_schedule(session, with_pending)
    after = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        season="2026-27",
    )

    assert after is not None
    assert after.version == before_version, (
        "the schedule version moved when only the pending set changed; if this now holds, "
        "the caching caveat in _register_schedule_refresh is stale and should be removed"
    )
    after_block = schedule_completeness(after.summary)
    assert after_block is not None
    assert after_block.pending_game_ids == ("0022601201", "0022601202")


def test_schedule_import_refuses_a_source_count_that_disagrees_with_resolved_games(
    session: Any,
) -> None:
    result = parse_schedule(resolved_schedule_payload(), season="2026-27")
    import_schedule_teams(session, result)

    with pytest.raises(SourceContractError, match=r"source reported 11.*10 resolved and 0 are"):
        import_schedule(session, replace(result, source_game_count=11))

    assert session.scalars(select(TeamScheduleEntry)).all() == []
    assert (
        current_refresh(
            session,
            RefreshArtifactType.SCHEDULE,
            artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
            season="2026-27",
        )
        is None
    )


def test_schedule_import_refuses_games_whose_teams_are_not_in_the_database(session: Any) -> None:
    """A missing mapping used to be two silently absent rows, not an error."""
    result = parse_schedule(resolved_schedule_payload(), season="2026-27")
    all_team_ids = sorted(
        {
            team_id
            for record in result.games
            for team_id in (record.home_nba_team_id, record.away_nba_team_id)
        }
    )
    import_teams(
        session,
        [
            NbaTeamRecord(team_id, f"T{team_id % 10_000_000:07d}", f"Team {team_id}")
            for team_id in all_team_ids[:-1]
        ],
    )

    with pytest.raises(SourceContractError, match="are not in"):
        import_schedule(session, result)

    assert session.scalars(select(TeamScheduleEntry)).all() == []
    assert (
        current_refresh(
            session,
            RefreshArtifactType.SCHEDULE,
            artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
            season="2026-27",
        )
        is None
    )


def test_schedule_import_persists_exactly_two_mirrored_rows_per_parsed_game(session: Any) -> None:
    """The persisted cohort is checked on stable NBA ids, not on row counts."""
    result = parse_schedule(resolved_schedule_payload(), season="2026-27")
    import_schedule_teams(session, result)

    import_schedule(session, result)

    observed = _persisted_schedule_rows(session, "2026-27")
    expected = {
        (record.game.nba_game_id, home, away, record.game.game_date, is_home)
        for record in result.games
        for home, away, is_home in (
            (record.home_nba_team_id, record.away_nba_team_id, True),
            (record.away_nba_team_id, record.home_nba_team_id, False),
        )
    }

    assert observed == expected
    assert len(observed) == 2 * len(result.games)


def test_schedule_import_refuses_rows_that_fall_outside_the_parsed_cohort(session: Any) -> None:
    """Inconsistent evidence is refused, not synchronised away.

    A payload that no longer lists a game the database already holds might be
    a real postponement or a truncated response, and the importer cannot tell
    which. Deleting the leftover rows would cascade into ``quant``'s derived
    ``opponent_context`` and could not be undone by re-running the import, so
    the refresh simply does not register: both the rows and the operator's
    options survive, and the previously registered cohort stays current
    because it still describes the database exactly.
    """
    result = parse_schedule(resolved_schedule_payload(), season="2026-27")
    import_schedule_teams(session, result)
    import_schedule(session, result)
    before = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        season="2026-27",
    )
    assert before is not None
    registered_version = before.version
    original_tipoff = result.games[0].game.tipoff_utc
    assert original_tipoff is not None
    changed_first = replace(
        result.games[0],
        game=replace(result.games[0].game, tipoff_utc=original_tipoff + timedelta(hours=1)),
    )

    shortened = ScheduleParseResult(
        season=result.season,
        games=(changed_first, *result.games[1:-1]),
        unresolved_game_ids=(),
        source_game_count=len(result.games) - 1,
    )

    with pytest.raises(SourceContractError, match="does not match the parsed cohort"):
        import_schedule(session, shortened)
    session.commit()

    after = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        season="2026-27",
    )
    assert after is not None
    assert after.version == registered_version, "a refused import must not register a refresh"
    assert len(_persisted_schedule_rows(session, "2026-27")) == 2 * len(result.games)
    assert check_cohort(session, schedule_version=registered_version)[0].status == "current"
    persisted_game = session.scalar(
        select(NbaGame).where(NbaGame.nba_game_id == result.games[0].game.nba_game_id)
    )
    assert persisted_game is not None
    assert persisted_game.tipoff_utc == original_tipoff


def test_schedule_import_refuses_a_persisted_game_that_contradicts_the_source(
    session: Any,
) -> None:
    """``nba_games`` and ``team_schedule`` must never disagree about a fixture.

    ``import_games`` deliberately never rewrites a game's core identity, so a
    pre-existing row saying the game is a day later survives the import
    untouched — and without this check ``team_schedule`` would be written with
    the source's date against a game ``nba_games`` dates differently. Two
    tables quietly contradicting each other about when a game is played is
    worse than either being absent.
    """
    result = parse_schedule(resolved_schedule_payload(), season="2026-27")
    import_schedule_teams(session, result)
    contradicted = result.games[0].game
    import_games(
        session,
        [replace(contradicted, game_date=contradicted.game_date + timedelta(days=1))],
    )

    with pytest.raises(SourceContractError, match="contradict the parsed schedule"):
        import_schedule(session, result)

    assert session.scalars(select(TeamScheduleEntry)).all() == []
    assert (
        current_refresh(
            session,
            RefreshArtifactType.SCHEDULE,
            artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
            season="2026-27",
        )
        is None
    )


def test_same_row_count_schedule_mutation_is_never_reported_current(session: Any) -> None:
    """The failure this whole seam exists for.

    A fingerprint over surrogate primary keys, or a version compared only as a
    stored string, both report "current" after the facts underneath change —
    the row count is identical and the registry never noticed. ``check_cohort``
    recomputes from the persisted rows instead, so the old label can no longer
    be validated.
    """
    result = parse_schedule(resolved_schedule_payload(), season="2026-27")
    import_schedule_teams(session, result)
    import_schedule(session, result)
    run = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        season="2026-27",
    )
    assert run is not None
    registered_version = run.version
    assert check_cohort(session, schedule_version=registered_version)[0].status == "current"

    before = session.scalars(select(TeamScheduleEntry)).all()
    mutated = sorted(before, key=lambda entry: (entry.game_id, entry.team_id))[0]
    mutated_game = session.get(NbaGame, mutated.game_id)
    assert mutated_game is not None
    mutated_game.game_date = mutated_game.game_date + timedelta(days=1)
    for entry in before:
        if entry.game_id == mutated.game_id:
            entry.game_date = mutated_game.game_date
    session.flush()

    [check] = check_cohort(session, schedule_version=registered_version)
    after = session.scalars(select(TeamScheduleEntry)).all()

    assert len(after) == len(before), "the mutation must not change the row count"
    assert check.status == "stale"
    assert check.current_version is None
    observed_version = schedule_content_version(session, season="2026-27")
    verification = verify_refresh(session, run)
    assert verification.is_current is False
    assert verification.current_version is None
    assert verification.observed_content_version == observed_version
    [observed_claim] = check_cohort(session, schedule_version=observed_version)
    assert observed_claim.status == "stale"
    assert observed_claim.current_version is None
    # The registry itself is untouched: detection comes from recomputing the
    # content, not from a producer having registered something new.
    assert run.version == registered_version


@pytest.mark.parametrize(
    "contradiction",
    ["season", "season_type", "game_date", "home_away"],
)
def test_schedule_serializer_refuses_nba_game_identity_that_contradicts_team_schedule(
    session: Any,
    contradiction: str,
) -> None:
    result = parse_schedule(resolved_schedule_payload(), season="2026-27")
    import_schedule_teams(session, result)
    import_schedule(session, result)
    game = session.scalar(select(NbaGame).order_by(NbaGame.nba_game_id))
    assert game is not None

    if contradiction == "season":
        game.season = "2025-26"
    elif contradiction == "season_type":
        game.season_type = SeasonType.PLAYOFFS
    elif contradiction == "game_date":
        game.game_date = game.game_date + timedelta(days=1)
    else:
        game.home_team_id, game.away_team_id = game.away_team_id, game.home_team_id
    session.flush()

    with pytest.raises(ValueError, match="contradicts team_schedule"):
        schedule_content_version(session, season="2026-27")


def _persisted_schedule_rows(
    session: Session, season: str
) -> set[tuple[str, int, int, date, bool]]:
    """The persisted cohort keyed on stable NBA identifiers."""

    team = aliased(NbaTeam)
    opponent = aliased(NbaTeam)
    rows = session.execute(
        select(
            NbaGame.nba_game_id,
            team.nba_team_id,
            opponent.nba_team_id,
            TeamScheduleEntry.game_date,
            TeamScheduleEntry.is_home,
        )
        .join(NbaGame, NbaGame.id == TeamScheduleEntry.game_id)
        .join(team, team.id == TeamScheduleEntry.team_id)
        .join(opponent, opponent.id == TeamScheduleEntry.opponent_team_id)
        .where(
            TeamScheduleEntry.season == season,
            TeamScheduleEntry.season_type == SeasonType.REGULAR,
        )
    ).all()
    return {
        (nba_game_id, team_nba_id, opponent_nba_id, game_date, bool(is_home))
        for nba_game_id, team_nba_id, opponent_nba_id, game_date, is_home in rows
    }


def test_playoff_schedule_counts_complete_league_scoped_team_period_grid(
    session: Session,
) -> None:
    teams = [
        NbaTeam(nba_team_id=1, abbreviation="ONE", name="One"),
        NbaTeam(nba_team_id=2, abbreviation="TWO", name="Two"),
        NbaTeam(nba_team_id=3, abbreviation="THREE", name="Three"),
        NbaTeam(nba_team_id=4, abbreviation="FOUR", name="Four"),
    ]
    leagues = [
        League(
            name="Primary",
            season="2026-27",
            fantrax_league_id="playoff-primary",
            scoring_type="h2h_categories",
            draft_type="auction",
        ),
        League(
            name="Other",
            season="2026-27",
            fantrax_league_id="playoff-other",
            scoring_type="h2h_categories",
            draft_type="auction",
        ),
    ]
    session.add_all([*teams, *leagues])
    session.flush()
    _add_schedule_game(session, 101, date(2027, 3, 1), teams[0], teams[1])
    _add_schedule_game(session, 102, date(2027, 3, 7), teams[0], teams[2])
    _add_schedule_game(session, 103, date(2027, 3, 8), teams[1], teams[2])
    _add_schedule_game(session, 104, date(2027, 3, 14), teams[0], teams[1])
    _add_schedule_game(session, 105, date(2027, 3, 15), teams[0], teams[1])
    _add_schedule_game(
        session,
        106,
        date(2027, 3, 1),
        teams[0],
        teams[1],
        season="2025-26",
    )
    _add_schedule_game(
        session,
        107,
        date(2027, 3, 1),
        teams[0],
        teams[1],
        season_type=SeasonType.PLAYOFFS,
    )
    refreshed_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version="schedule-v1",
        source="test",
        season="2026-27",
        refreshed_at=refreshed_at,
    )
    session.flush()
    primary_projection = _project_periods(
        session,
        leagues[0],
        [
            (6, date(2027, 2, 22), date(2027, 2, 28), False),
            (7, date(2027, 3, 1), date(2027, 3, 7), True),
            (8, date(2027, 3, 8), date(2027, 3, 14), True),
            (9, date(2027, 3, 22), date(2027, 3, 28), True),
        ],
    )
    other_projection = _project_periods(
        session,
        leagues[1],
        [(20, date(2027, 3, 8), date(2027, 3, 14), True)],
    )

    primary = playoff_scheduled_game_counts(session, league_id=leagues[0].id, season="2026-27")

    assert [(row.period_number, row.team_id, row.games) for row in primary] == [
        (7, teams[0].id, 2),
        (7, teams[1].id, 1),
        (7, teams[2].id, 1),
        (7, teams[3].id, 0),
        (8, teams[0].id, 1),
        (8, teams[1].id, 2),
        (8, teams[2].id, 1),
        (8, teams[3].id, 0),
        (9, teams[0].id, 0),
        (9, teams[1].id, 0),
        (9, teams[2].id, 0),
        (9, teams[3].id, 0),
    ]
    assert {row.schedule_version for row in primary} == {"schedule-v1"}
    assert {row.schedule_refreshed_at for row in primary} == {refreshed_at}
    assert {row.projection_version for row in primary} == {
        primary_projection.lineage.projection_version
    }
    assert {row.deadline_calendar_id for row in primary} == {
        primary_projection.lineage.deadline_calendar_id
    }
    assert {row.settings_snapshot_id for row in primary} == {
        primary_projection.lineage.settings_snapshot_id
    }
    assert all(
        row.schedule_refreshed_at.tzinfo is not None
        and row.schedule_refreshed_at.utcoffset() is not None
        for row in primary
    )
    assert {
        row.period_number
        for row in playoff_scheduled_game_counts(session, league_id=leagues[1].id, season="2026-27")
    } == {20}
    assert {
        row.projection_version
        for row in playoff_scheduled_game_counts(
            session,
            league_id=leagues[1].id,
            season="2026-27",
        )
    } == {other_projection.lineage.projection_version}


def test_scheduled_game_counts_fail_without_an_active_period_projection(
    session: Session,
) -> None:
    league = _add_league(session)
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version="schedule-v1",
        source="test",
        season="2026-27",
    )

    with pytest.raises(RuntimeError, match="no active deadline calendar"):
        scheduled_game_counts(session, league_id=league.id, season="2026-27")


def test_scheduled_game_counts_locks_schedule_and_period_projection_scopes(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[RefreshArtifactType, str, str | None]] = []
    league = _add_league(session)
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version="schedule-v1",
        source="test",
        season="2026-27",
    )
    _project_periods(
        session,
        league,
        [(1, date(2026, 10, 20), date(2026, 10, 26), True)],
    )

    def capture_lock(
        target_session: Session,
        *,
        artifact_type: RefreshArtifactType,
        artifact_key: str,
        season: str | None,
    ) -> None:
        calls.append((artifact_type, artifact_key, season))
        lock_refresh_scope(
            target_session,
            artifact_type=artifact_type,
            artifact_key=artifact_key,
            season=season,
        )

    monkeypatch.setattr(
        "hoops_gm.calendar.scoring_periods.lock_refresh_scope",
        capture_lock,
    )

    assert scheduled_game_counts(session, league_id=league.id, season="2026-27") == []
    assert calls == [
        (RefreshArtifactType.SCHEDULE, NBA_SCHEDULE_ARTIFACT_KEY, "2026-27"),
        (
            RefreshArtifactType.SCHEDULE,
            scoring_period_artifact_key(league.id),
            "2026-27",
        ),
    ]


def test_scheduled_game_counts_reject_a_different_season_cohort(session: Session) -> None:
    league = _add_league(session)
    current = record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version="schedule-v1",
        source="test",
        season="2026-27",
    )
    _project_periods(
        session,
        league,
        [(1, date(2026, 10, 20), date(2026, 10, 26), True)],
    )
    session.delete(current)
    session.flush()
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version="schedule-v1",
        source="test",
        season="2025-26",
    )

    with pytest.raises(RuntimeError, match="stale NBA schedule"):
        scheduled_game_counts(session, league_id=league.id, season="2026-27")


def test_playoff_counts_reject_period_rows_that_no_longer_match_projection(
    session: Session,
) -> None:
    league = _add_league(session)
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version="schedule-v1",
        source="test",
        season="2026-27",
    )
    _project_periods(
        session,
        league,
        [(1, date(2026, 10, 20), date(2026, 10, 26), True)],
    )
    period = session.scalar(
        select(ScoringPeriod).where(
            ScoringPeriod.league_id == league.id,
            ScoringPeriod.period_number == 1,
        )
    )
    assert period is not None
    period.end_date = date(2026, 10, 25)
    session.flush()

    with pytest.raises(StaleScoringPeriodProjectionError, match="do not match"):
        playoff_scheduled_game_counts(
            session,
            league_id=league.id,
            season="2026-27",
        )


def test_playoff_counts_reject_mismatched_projection_refresh_lineage(
    session: Session,
) -> None:
    league = _add_league(session)
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version="schedule-v1",
        source="test",
        season="2026-27",
    )
    _project_periods(
        session,
        league,
        [(1, date(2026, 10, 20), date(2026, 10, 26), True)],
    )
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=scoring_period_artifact_key(league.id),
        version="mismatched-projection",
        source="test",
        season="2026-27",
        refreshed_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    with pytest.raises(StaleScoringPeriodProjectionError, match="is stale"):
        playoff_scheduled_game_counts(
            session,
            league_id=league.id,
            season="2026-27",
        )


def test_scheduled_game_counts_reject_a_season_outside_the_league(session: Session) -> None:
    league = _add_league(session)
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version="schedule-v1",
        source="test",
        season="2025-26",
    )

    with pytest.raises(RuntimeError, match=r"league .* is for season '2026-27', not '2025-26'"):
        scheduled_game_counts(session, league_id=league.id, season="2025-26")


def test_schedule_density_uses_team_schedule_only_for_calendar_arithmetic() -> None:
    refreshed_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    rows = [
        TeamScheduleEntry(
            id=1,
            team_id=42,
            game_id=101,
            opponent_team_id=2,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 15),
            is_home=True,
        ),
        TeamScheduleEntry(
            id=2,
            team_id=42,
            game_id=102,
            opponent_team_id=3,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 16),
            is_home=False,
        ),
        TeamScheduleEntry(
            id=3,
            team_id=42,
            game_id=103,
            opponent_team_id=4,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 17),
            is_home=False,
        ),
        TeamScheduleEntry(
            id=4,
            team_id=42,
            game_id=104,
            opponent_team_id=5,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 18),
            is_home=False,
        ),
        TeamScheduleEntry(
            id=5,
            team_id=42,
            game_id=105,
            opponent_team_id=6,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 20),
            is_home=False,
        ),
        TeamScheduleEntry(
            id=6,
            team_id=3,
            game_id=99,
            opponent_team_id=8,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 14),
            is_home=True,
        ),
        TeamScheduleEntry(
            id=7,
            team_id=3,
            game_id=102,
            opponent_team_id=42,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 16),
            is_home=True,
        ),
    ]

    density = build_schedule_density(
        rows,
        schedule_version="schedule-v1",
        schedule_refreshed_at=refreshed_at,
    )
    team_density = [row for row in density if row.team_id == 42]
    by_date = {row.game_date: row for row in team_density}

    assert {row.schedule_version for row in density} == {"schedule-v1"}
    assert {row.schedule_refreshed_at for row in density} == {refreshed_at}
    assert {row.season for row in density} == {"2026-27"}
    assert {row.season_type for row in density} == {SeasonType.REGULAR}
    assert by_date[date(2026, 10, 15)].rest_days_differential is None
    assert by_date[date(2026, 10, 16)].is_back_to_back is True
    assert by_date[date(2026, 10, 16)].rest_days == 0
    assert by_date[date(2026, 10, 16)].rest_days_differential == -1
    assert by_date[date(2026, 10, 17)].games_in_4_days == 3
    assert by_date[date(2026, 10, 17)].is_3_in_4 is True
    assert by_date[date(2026, 10, 18)].games_in_5_days == 4
    assert by_date[date(2026, 10, 18)].is_4_in_5 is True
    assert by_date[date(2026, 10, 18)].games_in_6_days == 4
    assert by_date[date(2026, 10, 18)].is_4_in_6 is True
    assert by_date[date(2026, 10, 18)].road_trip_length == 3
    assert by_date[date(2026, 10, 18)].road_trip_structure == (3, 4, 5)
    assert by_date[date(2026, 10, 20)].rest_days == 1
    assert by_date[date(2026, 10, 20)].road_trip_length == 4
    assert by_date[date(2026, 10, 20)].road_trip_structure == (3, 4, 5, 6)


def test_schedule_density_requires_refresh_lineage() -> None:
    with pytest.raises(ValueError, match="schedule_version"):
        build_schedule_density(
            [],
            schedule_version="",
            schedule_refreshed_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        build_schedule_density(
            [],
            schedule_version="schedule-v1",
            schedule_refreshed_at=datetime(2026, 8, 18, 12, 0),
        )


@pytest.mark.parametrize(
    ("second_season", "second_season_type"),
    [
        ("2025-26", SeasonType.REGULAR),
        ("2026-27", SeasonType.PLAYOFFS),
    ],
)
def test_schedule_density_rejects_mixed_season_cohorts(
    second_season: str,
    second_season_type: SeasonType,
) -> None:
    rows = [
        TeamScheduleEntry(
            id=1,
            team_id=42,
            game_id=101,
            opponent_team_id=2,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 15),
            is_home=True,
        ),
        TeamScheduleEntry(
            id=2,
            team_id=42,
            game_id=102,
            opponent_team_id=3,
            season=second_season,
            season_type=second_season_type,
            game_date=date(2026, 10, 16),
            is_home=False,
        ),
    ]

    with pytest.raises(ValueError, match="one season and season type"):
        build_schedule_density(
            rows,
            schedule_version="schedule-v1",
            schedule_refreshed_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
        )


def _add_schedule_game(
    session: Session,
    number: int,
    game_date: date,
    home: NbaTeam,
    away: NbaTeam,
    *,
    season: str = "2026-27",
    season_type: SeasonType = SeasonType.REGULAR,
) -> None:
    game = NbaGame(
        nba_game_id=str(number),
        season=season,
        season_type=season_type,
        game_date=game_date,
        home_team_id=home.id,
        away_team_id=away.id,
    )
    session.add(game)
    session.flush()
    session.add_all(
        [
            TeamScheduleEntry(
                game_id=game.id,
                team_id=home.id,
                opponent_team_id=away.id,
                season=season,
                season_type=season_type,
                game_date=game_date,
                is_home=True,
            ),
            TeamScheduleEntry(
                game_id=game.id,
                team_id=away.id,
                opponent_team_id=home.id,
                season=season,
                season_type=season_type,
                game_date=game_date,
                is_home=False,
            ),
        ]
    )


def _project_periods(
    session: Session,
    league: League,
    periods: list[tuple[int, date, date, bool]],
) -> ScoringPeriodProjectionResult:
    if league.fantrax_league_id is None:
        raise AssertionError("test league must carry a Fantrax id")
    playoff_numbers = tuple(number for number, _, _, is_playoff in periods if is_playoff)
    if not playoff_numbers:
        raise AssertionError("the settings contract cannot express known zero-playoff periods")

    payload: dict[str, object] = {
        "seasonYear": int(league.season[:4]),
        "startDate": min(start_date for _, start_date, _, _ in periods).isoformat(),
        "endDate": max(end_date for _, _, end_date, _ in periods).isoformat(),
        "scoringPeriods": [
            {
                "number": number,
                "startDate": datetime.combine(
                    start_date,
                    time.min,
                    tzinfo=EASTERN,
                ).isoformat(),
                "endDate": datetime.combine(
                    end_date,
                    time(23, 59, 59),
                    tzinfo=EASTERN,
                ).isoformat(),
            }
            for number, start_date, end_date, _ in periods
        ],
    }
    document = parse_official_league_settings(
        payload,
        source_league_id=league.fantrax_league_id,
        capture_ref=f"sha256:schedule-test-{league.id}",
    ).model_copy(
        update={
            "playoffs": SourcedSetting(
                value=PlayoffRules(period_numbers=playoff_numbers),
                evidence=(
                    SettingEvidence(
                        source=BRIDGE_SOURCE,
                        status="observed",
                        source_path="League Rules > Playoffs",
                        capture_ref=f"bridge_payload:schedule-test-{league.id}",
                    ),
                ),
            )
        }
    )
    import_league_settings(
        session,
        league=league,
        document=document,
        source_payload_sha256=hashlib.sha256(document.canonical_json().encode()).hexdigest(),
        observed_at=datetime(2026, 8, 18, tzinfo=UTC),
    )
    calendar = derive_deadline_calendar(session, league).calendar
    activate_deadline_calendar(session, league, calendar.version)
    return project_scoring_periods(
        session,
        league,
        projected_at=datetime(2026, 8, 19, 18, tzinfo=UTC),
    )


def _add_league(session: Session, *, season: str = "2026-27") -> League:
    league = League(
        name=f"Test league {season}",
        season=season,
        fantrax_league_id=f"schedule-test-{season}",
        scoring_type="h2h_categories",
        draft_type="auction",
    )
    session.add(league)
    session.flush()
    return league
