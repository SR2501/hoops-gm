"""Adapter gate: live smoke tests against the real sources.

**This is the half of the Adapter gate that can actually detect a change.**

A contract test against a recorded fixture cannot, by construction, tell us
that Fantrax or ``stats.nba.com`` changed — the fixture keeps passing forever.
Only something executing against the live source finds out. That makes these
the more important tests, not the optional ones, and it is why they assert the
*specific findings* rather than merely that a request succeeded.

They are marked ``live_smoke`` and run separately from the Code gate: a third
party's outage must not turn a correct change red on a pull request. But when
one of these fails it means an upstream this project depends on has moved, and
that must be conspicuous rather than a warning nobody reads.

Run them deliberately:

    pytest -m live_smoke

Every assertion below has a comment saying what it would mean if it failed,
because the failure message is the entire value of the test.

``cdn.nba.com`` is deliberately not exercised here. It returns an Akamai 403
from the development network (risk R26) and is a Phase 6 concern; a permanently
red smoke test teaches people to ignore red smoke tests.
"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from typing import ClassVar

import pytest

from hoops_gm.identity import IdentityResolver, ResolvableRecord
from hoops_gm.ingest.errors import SourceRejected
from hoops_gm.ingest.fantrax_official import FantraxOfficialClient, parse_league_info
from hoops_gm.ingest.injury_report import (
    InjuryReportClient,
    ReportNotAvailable,
    parse_injury_report_pdf,
    report_url,
)
from hoops_gm.ingest.injury_report.cohort_evidence import (
    GameIdentityReconciliation,
    _league_game_finder_ids,
    _player_game_log_ids,
    _schedule_league_ids,
)
from hoops_gm.ingest.nba import (
    NbaStatsClient,
    parse_box_score_summary_v3,
    parse_common_all_players,
    parse_league_game_finder,
    parse_player_game_logs,
    parse_schedule,
    parse_teams,
)
from hoops_gm.ingest.projections import (
    BASKETBALL_MONSTER_PROFILE,
    ProjectionProfileError,
    parse_projection_csv,
)
from hoops_gm.ingest.record_fixtures import (
    FIXTURE_CURRENT_SEASON,
    FIXTURE_MIDSEASON_GAME_DATE,
    FIXTURE_MIDSEASON_GAME_ID,
    FIXTURE_STATS_SEASON,
)

# The runtime candidate-selection logic for the current-season probe below is
# defined and unit-tested offline in `test_injury_report.py` (no `live_smoke`
# marker there), and imported here rather than duplicated so the exact logic
# proven offline is what this live test actually runs.
from test_injury_report import FRESHNESS_WINDOW, select_recent_report_candidate

pytestmark = pytest.mark.live_smoke

#: Live calls bypass the cache entirely. A smoke test served from a capture is
#: a contract test wearing a disguise, and would report the source as healthy
#: long after it stopped answering.
from datetime import UTC, date, datetime, timedelta  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

NO_CACHE = timedelta(0)
_EASTERN = ZoneInfo("America/New_York")
_BBM_PRIVATE_CSV_ENV = "HOOPS_GM_BBM_PROJECTION_CSV"

#: The representative historical injury cohort's window. Mirrors the committed
#: manifest's scope, so a live drift in the window's game slate turns this red
#: rather than leaving the manifest quietly stale.
COHORT_SEASON = "2025-26"
COHORT_START = date(2025, 12, 8)
COHORT_END = date(2026, 1, 4)

#: The closed vocabulary the injury report prints before its own " - "
#: separator, observed across all 9,376 raw entries in the cohort window plus
#: ``Team Suspension`` from the recorded 2025-11-01 report, which the cohort
#: window does not contain. Kept here rather than imported from the offline test
#: that also uses it, because a live smoke must not depend on a test module.
KNOWN_REASON_CATEGORIES = frozenset(
    {
        "-",
        "Coach's Decision",
        "Concussion Protocol",
        "G League",
        "Injury/Illness",
        "League Suspension",
        "NOT YET SUBMITTED",
        "Not With Team",
        "Personal Reasons",
        "Rest",
        "Return to Competition Reconditioning",
        "Team Suspension",
    }
)


@pytest.fixture
def fantrax() -> FantraxOfficialClient:
    return FantraxOfficialClient()


@pytest.fixture
def nba() -> NbaStatsClient:
    return NbaStatsClient()


@pytest.fixture
def injury_report() -> InjuryReportClient:
    return InjuryReportClient()


# ==========================================================================
# Basketball Monster private projection export
# ==========================================================================


class TestBasketballMonsterProjectionExportIsAlive:
    def test_explicit_private_export_still_matches_the_verified_contract(self) -> None:
        """FAILS IF: the explicitly supplied paid export changed shape or units.

        The path is intentionally opt-in and never echoed. CI and ordinary local
        runs skip this probe because they do not possess the private artifact.
        Failures suppress parser details so paid row values and local paths do
        not enter logs.
        """
        configured = os.getenv(_BBM_PRIVATE_CSV_ENV)
        if not configured:
            pytest.skip(f"set {_BBM_PRIVATE_CSV_ENV} explicitly to run the BBM smoke")

        try:
            content = Path(configured).read_bytes()
        except OSError:
            raise AssertionError(
                f"{_BBM_PRIVATE_CSV_ENV} must identify a readable private CSV"
            ) from None
        try:
            csv_text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise AssertionError("private BBM CSV is no longer UTF-8") from None
        try:
            parsed = parse_projection_csv(
                csv_text,
                BASKETBALL_MONSTER_PROFILE,
                season="2026-27",
            )
        except (ProjectionProfileError, ValueError):
            raise AssertionError(
                "private BBM CSV drifted from the verified 2026-27 contract"
            ) from None

        zero_game_rows: set[int] = set()
        for row_number, row in enumerate(csv.DictReader(io.StringIO(csv_text)), start=2):
            raw_games = (row.get("games") or "").strip()
            try:
                is_zero_game = not raw_games or float(raw_games.replace(",", "")) == 0
            except ValueError:
                is_zero_game = False
            if is_zero_game:
                zero_game_rows.add(row_number)

        allowed_zero_game_messages = (
            "given as a season total but no valid games-played figure",
            "row is missing required production values",
            "row has no usable production rates",
        )
        unexpected_issue = any(
            issue.row_number not in zero_game_rows
            or not any(token in issue.message for token in allowed_zero_game_messages)
            for issue in parsed.issues
        )
        if not parsed.rows or unexpected_issue:
            raise AssertionError(
                "private BBM CSV contains unexpected row failures under the verified contract"
            )


# ==========================================================================
# Fantrax official
# ==========================================================================


class TestFantraxOfficialIsAlive:
    def test_get_player_ids_still_returns_players_and_thirty_team_entities(
        self, fantrax: FantraxOfficialClient
    ) -> None:
        """FAILS IF: Fantrax changed the player payload.

        A different team-entity count means the row mix changed and the R24
        filter needs re-checking. Zero players means the endpoint moved,
        started requiring authentication, or changed shape entirely — and the
        crosswalk has no Fantrax side without it.
        """
        result = fantrax.get_player_ids(max_age=NO_CACHE)

        assert len(result.players) > 1000, (
            f"only {len(result.players)} player rows; getPlayerIds has returned "
            "~1,788 since 2026-08-17"
        )
        assert len(result.team_entities) == 30, (
            f"{len(result.team_entities)} non-player entities, expected 30 (one per "
            "franchise). The payload's row mix has changed — re-check the R24 filter"
        )
        assert not result.unclassified, (
            f"{len(result.unclassified)} rows are neither player nor team entity; "
            "a third row type has appeared"
        )

    def test_names_still_arrive_last_comma_first(self, fantrax: FantraxOfficialClient) -> None:
        """FAILS IF: Fantrax changed its name format.

        Every crosswalk match is inferred from the name. A format change breaks
        the join to NBA.com silently rather than loudly, which is precisely the
        failure this project cannot afford.
        """
        result = fantrax.get_player_ids(max_age=NO_CACHE)
        malformed = [p.name for p in result.players if ", " not in p.name]
        assert not malformed, f"names no longer 'Last, First': {malformed[:5]}"

    def test_no_nba_dot_com_identifier_has_appeared(self, fantrax: FantraxOfficialClient) -> None:
        """FAILS IF: **good news** — Fantrax started publishing an NBA.com id.

        This is the one test here that wants to fail. Risk R23 is that no
        anchor pair exists, which forces every match to be inferred. If Fantrax
        ever exposes an NBA person id, the crosswalk can anchor on a real key
        and most of the resolver becomes unnecessary.

        NBA person ids are 6-7 digit integers (``201935``, ``1642377``);
        ``statsIncId`` and ``rotowireId`` are 4-digit-ish and unrelated. A
        failure here is a prompt to re-read the payload, not a defect.
        """
        result = fantrax.get_player_ids(max_age=NO_CACHE)
        # Sample rather than scan: this is a canary, not an audit.
        for player in result.players[:200]:
            for value in (player.stats_inc_id, player.rotowire_id):
                if value and value.isdigit():
                    assert not (100000 <= int(value) <= 9999999), (
                        f"{player.name!r} has an id ({value}) in the NBA person-id "
                        "range. If Fantrax now publishes NBA ids, R23 is resolved and "
                        "the crosswalk should anchor on it instead of inferring"
                    )

    def test_adp_is_live_and_sorted(self, fantrax: FantraxOfficialClient) -> None:
        """FAILS IF: ADP stopped being published, or stopped being ordered."""
        entries = fantrax.get_adp(max_age=NO_CACHE)
        assert len(entries) > 100, f"only {len(entries)} ADP rows"
        values = [e.adp for e in entries]
        assert values == sorted(values), "ADP is no longer returned in ascending order"

    def test_the_limit_parameter_is_still_off_by_one(self, fantrax: FantraxOfficialClient) -> None:
        """FAILS IF: Fantrax fixed the off-by-one.

        ``limit=N`` returns ``N-1`` rows — verified for 1, 2, 3, 5 and 10 on
        2026-08-17. The adapter passes ``limit`` through uncorrected precisely
        so that a fix upstream shows up here rather than silently changing how
        many rows callers get.
        """
        entries = fantrax.get_adp(limit=5, max_age=NO_CACHE)
        assert len(entries) == 4, (
            f"limit=5 returned {len(entries)} rows, not 4. Fantrax may have fixed "
            "the off-by-one; if so, update the contract test and say so in the handoff"
        )

    def test_an_error_is_still_delivered_under_http_200(
        self, fantrax: FantraxOfficialClient
    ) -> None:
        """FAILS IF: Fantrax started using status codes properly, or stopped.

        Either direction matters. A client trusting ``response.ok`` parses this
        envelope as data, so the adapter checks for it on every endpoint.
        """
        with pytest.raises(SourceRejected) as caught:
            parse_league_info(fantrax.fetch_json("getLeagueInfo", {}, max_age=NO_CACHE))
        assert "leagueId" in str(caught.value)

    def test_configured_league_settings_shape_has_not_drifted(
        self, fantrax: FantraxOfficialClient
    ) -> None:
        """FAILS IF: official settings moved, disappeared, or became ambiguous."""
        league_id = os.environ.get("HOOPS_GM_FANTRAX_LEAGUE_ID")
        if not league_id:
            if os.environ.get("CI"):
                pytest.fail(
                    "CI must configure HOOPS_GM_FANTRAX_LEAGUE_ID; "
                    "otherwise league-settings drift is never exercised"
                )
            pytest.skip("set HOOPS_GM_FANTRAX_LEAGUE_ID to smoke-test league settings")

        result = fantrax.get_league_info(league_id, max_age=NO_CACHE)
        assert result.settings is not None
        assert result.settings.source_season_year >= 2025
        assert result.settings.roster_limits.value is not None
        assert result.settings.scoring_periods.value
        assert not result.unmapped_keys, (
            f"getLeagueInfo added unhandled top-level fields: {result.unmapped_keys}"
        )
        assert not result.settings.unmapped_rule_paths, (
            "getLeagueInfo now exposes an unhandled rule-shaped path: "
            f"{result.settings.unmapped_rule_paths}"
        )


# ==========================================================================
# stats.nba.com
# ==========================================================================


class TestNbaStatsIsAlive:
    def test_the_library_can_reach_the_host(self, nba: NbaStatsClient) -> None:
        """FAILS IF: ``stats.nba.com`` is unreachable or blocked.

        Note (risk R27): a ``curl`` failure against this host proves nothing.
        Raw HTTP clients with the complete documented header set get a
        connection reset while ``nba_api`` succeeds. Only this test's result is
        evidence.
        """
        assert len(parse_teams(nba.static_teams())) == 30
        players = parse_common_all_players(
            nba.common_all_players(
                season=FIXTURE_CURRENT_SEASON, only_current=True, max_age=NO_CACHE
            )
        )
        assert len(players) > 400, f"only {len(players)} current players"

    def test_current_rosters_carry_a_team_for_every_player(self, nba: NbaStatsClient) -> None:
        """FAILS IF: the current-season roster stopped carrying teams.

        The crosswalk matches on team as corroborating evidence, and it must be
        the *current* season: against a historical one, every offseason move
        becomes a spurious disagreement.
        """
        players = parse_common_all_players(
            nba.common_all_players(
                season=FIXTURE_CURRENT_SEASON, only_current=True, max_age=NO_CACHE
            )
        )
        without = [p.display_last_comma_first for p in players if not p.team_abbreviation]
        assert not without, f"{len(without)} current players have no team: {without[:5]}"

    def test_a_full_season_of_games_is_still_retrievable(self, nba: NbaStatsClient) -> None:
        """FAILS IF: ``LeagueGameFinder`` stopped returning a whole season.

        The schedule and the participation ledger are both built from this.
        """
        games = parse_league_game_finder(
            nba.league_game_finder(season=FIXTURE_STATS_SEASON, max_age=NO_CACHE),
            season=FIXTURE_STATS_SEASON,
        )
        logs = parse_player_game_logs(
            nba.player_game_logs(season=FIXTURE_STATS_SEASON, max_age=NO_CACHE)
        )
        game_ids = {game.nba_game_id for game in games}
        player_log_game_ids = {log.nba_game_id for log in logs}
        assert len(games) == 1230, (
            f"parsed {len(games)} games for {FIXTURE_STATS_SEASON}; the official regular "
            "season contains 1,230. Treat schedule, participation, and model cohorts as suspect."
        )
        assert game_ids == player_log_game_ids, (
            "LeagueGameFinder and PlayerGameLogs game identities disagree: "
            f"schedule-only={sorted(game_ids - player_log_game_ids)}, "
            f"logs-only={sorted(player_log_game_ids - game_ids)}"
        )

    def test_a_full_postseason_uses_canonical_playoff_scope(self, nba: NbaStatsClient) -> None:
        games = parse_league_game_finder(
            nba.league_game_finder(
                season=FIXTURE_STATS_SEASON,
                season_type="Playoffs",
                max_age=NO_CACHE,
            ),
            season=FIXTURE_STATS_SEASON,
            season_type="playoffs",
        )
        logs = parse_player_game_logs(
            nba.player_game_logs(
                season=FIXTURE_STATS_SEASON,
                season_type="Playoffs",
                max_age=NO_CACHE,
            )
        )

        assert len(games) == 84
        assert {game.nba_game_id for game in games} == {log.nba_game_id for log in logs}

    def test_repeated_canonical_games_agree_with_independent_orientation(
        self, nba: NbaStatsClient
    ) -> None:
        affected = {
            "2024-25": (
                "0022400147",
                "0022400621",
                "0022400633",
                "0022401229",
                "0022401230",
            ),
            "2025-26": (
                "0022500147",
                "0022500578",
                "0022500602",
                "0022501229",
                "0022501230",
            ),
        }
        for season, game_ids in affected.items():
            schedule = {
                game.nba_game_id: game
                for game in parse_league_game_finder(
                    nba.league_game_finder(season=season, max_age=NO_CACHE),
                    season=season,
                )
            }
            for game_id in game_ids:
                summary, _ = parse_box_score_summary_v3(
                    nba.box_score_summary(game_id, max_age=NO_CACHE)
                )
                assert summary is not None
                assert schedule[game_id].home_team_id == summary.home_team_id
                assert schedule[game_id].away_team_id == summary.away_team_id

    def test_the_inactive_list_is_still_populated_for_a_midseason_game(
        self, nba: NbaStatsClient
    ) -> None:
        """**The most important assertion in this file.**

        FAILS IF: ``BoxScoreSummaryV3`` stops reporting inactive players, the
        way ``BoxScoreSummaryV2`` already has.

        V2's ``InactivePlayers`` table returned data for 2025-10-21 and **zero
        rows for every subsequent date of the 2025-26 season** — bisected on
        2026-08-17. It did not error. It did not change shape. It returned an
        empty list, forever, and V2 is the endpoint most public examples use.
        Anything built on it would have held no inactives for an entire season
        while looking completely healthy.

        So this asserts a **non-zero count for a known mid-season game**, not
        that the call succeeded and not that the key exists. A test asserting
        either of those would have stayed green throughout.

        If this fails: check whether V3 has developed the same rot, and treat
        the availability ledger as suspect from that date forward until it is
        resolved. Do not adjust the assertion.
        """
        _, participation = parse_box_score_summary_v3(
            nba.box_score_summary(FIXTURE_MIDSEASON_GAME_ID, max_age=NO_CACHE)
        )

        assert participation.inactives_available, (
            f"BoxScoreSummaryV3 no longer offers an inactives key for game "
            f"{FIXTURE_MIDSEASON_GAME_ID} ({FIXTURE_MIDSEASON_GAME_DATE}). The "
            "availability ledger has lost its inactive-player source"
        )
        assert participation.inactive_count > 0, (
            f"BoxScoreSummaryV3 reported ZERO inactive players for game "
            f"{FIXTURE_MIDSEASON_GAME_ID} ({FIXTURE_MIDSEASON_GAME_DATE}). Every NBA "
            "game has inactive players, so this means V3 has developed the same "
            "silent rot as V2 — which returned empty lists for the whole 2025-26 "
            "season without erroring. Treat the availability ledger as suspect"
        )

    def test_the_v2_summary_is_still_the_wrong_answer(self, nba: NbaStatsClient) -> None:
        """FAILS IF: someone re-exposes ``BoxScoreSummaryV2`` on this client.

        Not a network test. It guards the decision, because the temptation to
        reach for V2 is real — it is the endpoint every public example uses,
        and its inactive list is empty rather than absent, so nothing about
        using it looks wrong until a season of availability data is worthless.
        """
        from hoops_gm.ingest.errors import SourceContractError
        from hoops_gm.ingest.nba.client import _default_endpoint_factory

        with pytest.raises(SourceContractError):
            _default_endpoint_factory("BoxScoreSummaryV2", game_id=FIXTURE_MIDSEASON_GAME_ID)


class TestTheForwardScheduleStillMeansWhatADR013AssumedItMeant:
    """ADR-013's flip condition, driven against the live source.

    The decision to record a game with absent team identities as *pending*
    rather than refusing rests entirely on one empirical claim: the source
    withholds team identities **because a bracket is undecided**, and for no
    other reason. If it ever does so for a different reason — a partial
    outage, a schema change, a data error — then "pending" stops meaning "not
    yet decided" and the distinction collapses into the silent-degradation
    failure the completeness contract exists to prevent.

    So these assert the pending set is *structurally explicable*, not merely
    small. A count-only assertion would stay green through exactly the
    scenario that invalidates the ADR: six games pending for six different
    reasons is indistinguishable from six pending Cup fixtures if all you
    count is six.

    **What these cannot see:** whether the resolved games are correct. That is
    the offline contract test's job. And a source that stopped publishing the
    Cup bracket altogether would show as zero pending, which fails the count
    assertion below rather than passing silently.
    """

    #: Every label the pending class is allowed to carry. Not a wildcard: the
    #: point is that an unrecognised label is a finding, not a variation.
    EXPLICABLE_LABELS: ClassVar[set[str]] = {"Emirates NBA Cup"}
    EXPLICABLE_SUBTYPES: ClassVar[set[str]] = {"in-season-knockout"}

    def test_the_forward_season_accounts_for_every_game_it_publishes(
        self, nba: NbaStatsClient
    ) -> None:
        """FAILS IF: the completeness invariant stops holding against live data.

        ``source == resolved + pending`` is the invariant ADR-013 replaced
        ``source == resolved`` with. Asserted here against the real payload
        because the committed fixture is a slice, and a slice cannot notice
        the source growing a fourth class of game.
        """
        result = parse_schedule(
            nba.schedule_league(season=FIXTURE_CURRENT_SEASON, max_age=NO_CACHE),
            season=FIXTURE_CURRENT_SEASON,
        )

        assert result.unresolved_game_ids == (), (
            "the live schedule now reports games whose teams the source named but did not "
            f"identify: {list(result.unresolved_game_ids)}. This is a resolution failure, not "
            "an undecided bracket, and import_schedule will correctly refuse the season"
        )
        assert result.source_game_count == len(result.games) + len(result.pending_games), (
            f"{result.source_game_count} source games do not account for "
            f"{len(result.games)} resolved plus {len(result.pending_games)} pending"
        )
        assert len(result.games) >= 1200, (
            f"only {len(result.games)} games resolved for {FIXTURE_CURRENT_SEASON}; 1,200 "
            "resolved on 2026-08-20 and the count only rises as the NBA fills the calendar"
        )

    def test_every_pending_game_is_an_undecided_cup_fixture(self, nba: NbaStatsClient) -> None:
        """FAILS IF: the source withholds team identities for a new reason.

        **This is the assertion ADR-013 says to revert on.** A red here does
        not mean the parser broke; it means the premise did. Read the labels
        in the failure message before changing anything, and if pending no
        longer means "not yet decided", go back to refusing.

        Zero pending is also a failure, deliberately. The Cup bracket is drawn
        in December and its knockout fixtures are published undecided every
        season, so an empty pending set before then means the source stopped
        publishing them — which changes what a complete season is, and is
        exactly as much of a finding as an inexplicable one.
        """
        result = parse_schedule(
            nba.schedule_league(season=FIXTURE_CURRENT_SEASON, max_age=NO_CACHE),
            season=FIXTURE_CURRENT_SEASON,
        )

        observed = {
            game.nba_game_id: (game.game_label, game.game_sub_label, game.game_subtype)
            for game in result.pending_games
        }
        inexplicable = {
            game_id: labels
            for game_id, labels in observed.items()
            if labels[0] not in self.EXPLICABLE_LABELS or labels[2] not in self.EXPLICABLE_SUBTYPES
        }

        assert not inexplicable, (
            "the source published games with no teams assigned for a reason other than an "
            f"undecided Emirates NBA Cup bracket: {inexplicable}. ADR-013's premise is that "
            "absent team identities mean 'not yet decided'; if that is no longer true, "
            "'pending' is silently absorbing a different failure and the ADR says to revert "
            "to refusing rather than to widen this set"
        )
        assert observed, (
            f"the live {FIXTURE_CURRENT_SEASON} schedule reports no pending games at all. The "
            "Cup knockout bracket is published undecided until December; an empty set means "
            "the source changed what it publishes, not that the season is fully scheduled"
        )
        assert {labels[1] for labels in observed.values()} <= {"Quarterfinal", "Semifinal"}, (
            f"a pending game carries an unexpected sub-label: {sorted(observed.values())}"
        )

    def test_a_pending_game_still_carries_no_team_identity_at_all(
        self, nba: NbaStatsClient
    ) -> None:
        """FAILS IF: the source starts naming a team it gives no id for.

        The pending/failure distinction rests on the identity block being
        withheld *entirely* — id zero and every naming field null. If the
        source began populating, say, ``teamTricode`` beside a zero id, the
        parser would correctly reclassify those games as failures and refuse
        the season. This asserts on the raw payload rather than on the parse
        so the diagnosis is available before the refusal is explained.
        """
        payload = nba.schedule_league(season=FIXTURE_CURRENT_SEASON, max_age=NO_CACHE)
        named_without_id = [
            (game["gameId"], side, {k: v for k, v in game[side].items() if k != "teamId"})
            for entry in payload["leagueSchedule"]["gameDates"]
            for game in entry.get("games") or ()
            if str(game.get("gameId", "")).startswith("002")
            for side in ("homeTeam", "awayTeam")
            if game[side].get("teamId") == 0
            and any(
                game[side].get(field) not in (None, "")
                for field in ("teamName", "teamCity", "teamTricode", "teamSlug")
            )
        ]

        assert not named_without_id, (
            "a game with teamId 0 now carries a populated naming field: "
            f"{named_without_id[:3]}. The source is naming a team it gave no id for, which "
            "is a resolution failure rather than an undecided bracket"
        )


class TestTheCohortWindowStillReconcilesAcrossSources:
    """The check that would have caught the invalidated cohort before it shipped.

    Three live views of the same window, required to be equal. Each applies the
    window using its own date field: ``LeagueGameFinder``'s ``GAME_DATE``,
    ``PlayerGameLogs``' own ``GAME_DATE``, and ``ScheduleLeagueV2``'s Eastern
    ``gameDateTimeEst`` reconciled against its UTC sibling. Three requests,
    throttled at ~1 req/s by the client.

    These three *are* independently fetched here, unlike the four-view set the
    cohort manifest publishes — that one includes ``persisted_nba_games``, which
    is the same ``LeagueGameFinder`` bytes through the same parser. See
    ``VIEW_INDEPENDENCE`` in ``hoops_gm.ingest.injury_report.cohort_evidence``
    before carrying the word "independent" between the two contexts.
    """

    def test_every_independent_view_names_the_same_173_games(self, nba: NbaStatsClient) -> None:
        """FAILS IF: the cohort's game-identity set stopped being agreed upstream.

        A disagreement here means the representative historical injury cohort's
        denominator is wrong, which silently poisons every availability number
        derived from it. The failure names the offending ids because the count
        alone is what made the first defect survive review.
        """
        views = {
            "league_game_finder": _league_game_finder_ids(
                nba.league_game_finder(season=COHORT_SEASON, max_age=NO_CACHE),
                season=COHORT_SEASON,
                start=COHORT_START,
                end=COHORT_END,
            ),
            "player_game_logs": _player_game_log_ids(
                nba.player_game_logs(season=COHORT_SEASON, max_age=NO_CACHE),
                start=COHORT_START,
                end=COHORT_END,
            ),
            "schedule_league_v2": _schedule_league_ids(
                nba.schedule_league(season=COHORT_SEASON, max_age=NO_CACHE),
                season=COHORT_SEASON,
                start=COHORT_START,
                end=COHORT_END,
            ),
        }
        reconciliation = GameIdentityReconciliation(start=COHORT_START, end=COHORT_END, views=views)

        assert reconciliation.agreed, (
            "independent views of the cohort window disagree on which games exist: "
            f"{reconciliation.disagreements()}"
        )
        assert len(reconciliation.union) == 173, (
            f"the cohort window now holds {len(reconciliation.union)} games, not 173. "
            "The committed cohort manifest's denominator is stale or the schedule moved."
        )

    def test_the_two_recovered_neutral_site_games_are_still_there(
        self, nba: NbaStatsClient
    ) -> None:
        """FAILS IF: a repeated-canonical-``MATCHUP`` game disappears again.

        These two are the only games played on 2025-12-13, so losing them costs
        a whole game date, which is exactly how the invalidated cohort came to
        cover 25 dates while believing it covered the window.
        """
        games = {
            game.nba_game_id: game
            for game in parse_league_game_finder(
                nba.league_game_finder(season=COHORT_SEASON, max_age=NO_CACHE),
                season=COHORT_SEASON,
            )
        }
        for game_id in ("0022501229", "0022501230"):
            assert game_id in games, f"{game_id} is absent from LeagueGameFinder again"
            assert games[game_id].game_date == date(2025, 12, 13)

    def test_drift_detector_repeated_matchup_games_are_exactly_the_neutral_site_games(
        self, nba: NbaStatsClient
    ) -> None:
        """**A drift detector, not a correctness invariant. Read this before fixing it red.**

        The five 2025-26 games whose two ``LeagueGameFinder`` rows repeat one
        canonical ``MATCHUP`` string are exactly the five the published schedule
        marks ``isNeutral: true`` — the two December NBA Cup knockouts in Las
        Vegas plus the Mexico City, Berlin and London games. That turns the
        defect class from "anomalies we happened to find" into one the upstream
        itself names, and it recurs every season.

        It couples two endpoints, so a red here does **not** mean the parser is
        wrong. The NBA could start writing reciprocal strings for neutral-site
        games, or repeat a ``MATCHUP`` for some unrelated reason, and the
        relationship would break while every line of our code stayed correct.
        The correctness invariant — that a repeated-``MATCHUP`` game still
        resolves to the right home and away teams — is asserted offline against
        recorded fixtures in ``test_adapter_contracts.py`` and
        ``test_cohort_evidence.py``, where it can block a merge. This one lives
        here precisely because it cannot.
        """
        payload = nba.league_game_finder(season=COHORT_SEASON, max_age=NO_CACHE)
        table = payload["resultSets"][0]
        headers = table["headers"]
        game_id_at = headers.index("GAME_ID")
        matchup_at = headers.index("MATCHUP")
        by_game: dict[str, list[str]] = {}
        for row in table["rowSet"]:
            by_game.setdefault(str(row[game_id_at]), []).append(str(row[matchup_at]))
        # Both conditions, not just the second. `len(set(strings)) == 1` alone
        # also matches a game with a *single* row, so a truncated payload would
        # be reported as matchup drift rather than as truncation. That cannot
        # happen today -- the histogram is 2-per-game for all 1,230 and
        # parse_league_game_finder rejects one-sided games loudly -- but the
        # predicate should say what it means.
        repeated = {
            game_id
            for game_id, strings in by_game.items()
            if len(strings) == 2 and len(set(strings)) == 1
        }

        schedule = nba.schedule_league(season=COHORT_SEASON, max_age=NO_CACHE)
        neutral = {
            str(game["gameId"])
            for entry in schedule["leagueSchedule"]["gameDates"]
            for game in entry.get("games") or ()
            if str(game.get("gameId", "")).startswith("002") and game.get("isNeutral")
        }

        assert repeated == neutral, (
            "the repeated-canonical-MATCHUP class no longer coincides with the schedule's own "
            f"isNeutral flag. repeated-only={sorted(repeated - neutral)}, "
            f"neutral-only={sorted(neutral - repeated)}. This is a DRIFT signal about how the "
            "NBA writes matchup strings, not a parser defect -- the parser resolves both shapes "
            "and is covered offline. Investigate before assuming either set is wrong."
        )

    def test_the_position_field_is_still_only_populated_for_starters(
        self, nba: NbaStatsClient
    ) -> None:
        """FAILS IF: ``BoxScoreTraditionalV3`` starts labelling every player.

        The cohort manifest withdraws its positional-diversity claim on the
        grounds that this field is a starting-lineup slot, not a player
        attribute — exactly five labels per team, always ``F,F,C,G,G``. That
        withdrawal is only correct while the source behaves this way.

        A red here is **good news**: it means real positional evidence became
        available, and `position_evidence` should be revisited rather than left
        standing. It is in the live smoke rather than the Adapter gate because
        the offline fixtures can only ever show what the source did when it was
        recorded.
        """
        body = nba.box_score_traditional(FIXTURE_MIDSEASON_GAME_ID, max_age=NO_CACHE)[
            "boxScoreTraditional"
        ]

        for side in ("homeTeam", "awayTeam"):
            players = body[side]["players"]
            non_blank = [
                label for label in (str(p.get("position") or "").strip() for p in players) if label
            ]
            assert non_blank == ["F", "F", "C", "G", "G"], (
                f"{side} of game {FIXTURE_MIDSEASON_GAME_ID} labels {len(non_blank)} of "
                f"{len(players)} players as {non_blank}. The cohort manifest's withdrawal of "
                "positional evidence assumes exactly the five starters are labelled; if that "
                "changed, the withdrawal should be revisited, not preserved."
            )


# ==========================================================================
# The crosswalk, end to end
# ==========================================================================


class TestCrosswalkAgainstLiveData:
    def test_the_live_match_rate_has_not_regressed(
        self, fantrax: FantraxOfficialClient, nba: NbaStatsClient
    ) -> None:
        """FAILS IF: the two sources drifted apart, or the resolver got worse.

        This is the number that matters for R7. It was 98.6% on 2026-08-17,
        matching every currently-rostered NBA player against the Fantrax player
        list. A drop means one of the payloads changed shape, a name format
        moved, or team abbreviations stopped agreeing — all of which corrupt
        downstream numbers silently rather than loudly.

        The threshold is a regression guard, not a target.
        """
        players = parse_common_all_players(
            nba.common_all_players(
                season=FIXTURE_CURRENT_SEASON, only_current=True, max_age=NO_CACHE
            )
        )
        fantrax_players = fantrax.get_player_ids(max_age=NO_CACHE)

        resolver = IdentityResolver(
            ResolvableRecord.build(key=p.fantrax_id, name=p.name, team=p.team, position=p.position)
            for p in fantrax_players.players
        )
        report = resolver.resolve(
            [
                ResolvableRecord.build(
                    key=str(p.nba_player_id),
                    name=p.display_last_comma_first,
                    team=p.team_abbreviation,
                )
                for p in players
            ]
        )

        assert report.match_rate > 0.95, (
            f"live crosswalk match rate fell to {report.match_rate:.1%} "
            f"({len(report.accepted)}/{report.total}). Something in one of the two "
            "payloads has moved; check the unmatched report before trusting any "
            "number that crosses sources"
        )


# ==========================================================================
# NBA official injury report
# ==========================================================================


class TestInjuryReportIsAlive:
    #: A real evening-before report from the 2025-26 season, permanently
    #: archived on the CDN. Distinct from the committed contract-test fixture
    #: timestamp so this test proves live reachability rather than replaying
    #: the same capture the offline test already checked. This instant sits
    #: in the **legacy, hourly** filename era (before 2025-12-22 ET) --
    #: ``client.report_url`` truncates it to the hour before building the URL.
    _KNOWN_GOOD_TIMESTAMP = datetime(2025, 12, 1, 13, 0, tzinfo=_EASTERN)

    #: A real evening-before report in the **current, 15-minute-granularity**
    #: filename era (on/after 2025-12-22 ET) -- the convention every request
    #: for 2026-27 actually uses. The legacy-era probe above exercises a
    #: retired code path (the hour-truncation branch of ``report_url``) and
    #: cannot, by construction, detect a regression specific to this one.
    #: Verified live 2026-08-17: ``2026-01-15 17:30`` resolves to
    #: ``Injury-Report_2026-01-15_05_30PM.pdf``.
    _KNOWN_GOOD_ACTIVE_ERA_TIMESTAMP = datetime(2026, 1, 15, 17, 30, tzinfo=_EASTERN)

    def test_a_known_historical_report_is_still_reachable_and_parses(
        self, injury_report: InjuryReportClient
    ) -> None:
        """FAILS IF: the CDN path moved, or the PDF's column layout changed.

        Unlike ``cdn.nba.com`` (risk R26, blocked from this network), this
        source has been reachable from this machine every time it has been
        checked. A failure here means the URL template, filename format era
        boundary, or table layout has drifted since 2026-08-17.
        """
        body = injury_report.fetch(self._KNOWN_GOOD_TIMESTAMP, max_age=NO_CACHE)
        result = parse_injury_report_pdf(
            body,
            report_timestamp=self._KNOWN_GOOD_TIMESTAMP,
            source_url="https://ak-static.cms.nba.com/referee/injury/"
            "Injury-Report_2025-12-01_01PM.pdf",
        )
        assert len(result.entries) > 0, "a real evening-before report had zero entries"

        # The reason-vocabulary drift alarm, on live bytes. The cohort manifest
        # publishes a category breakdown derived by splitting on the report's
        # own " - " separator, and 559 of 1,948 canonical observations are
        # G League rather than injuries -- a number a consumer will act on. If
        # the NBA switched that separator to an en dash, every reason *line*
        # would become its own "category" and the offline tests could not
        # notice: the fixture holds old bytes and the manifest is a static
        # artifact. This is the only check that sees tomorrow's payload.
        heads = {
            entry.reason_raw.strip().split(" - ", 1)[0].strip()
            for entry in result.entries
            if entry.reason_raw.strip()
        }
        assert heads <= KNOWN_REASON_CATEGORIES, (
            f"unrecognised injury-report reason categories: "
            f"{sorted(heads - KNOWN_REASON_CATEGORIES)}. Either the NBA added a category -- "
            "real news, record it in docs/handoff.md -- or the ' - ' separator changed and the "
            "cohort manifest's reason breakdown is now whole reason lines masquerading as a "
            "vocabulary."
        )

    def test_a_known_active_era_report_is_still_reachable_and_parses(
        self, injury_report: InjuryReportClient
    ) -> None:
        """FAILS IF: the current 15-minute-granularity filename convention --
        the one every 2026-27 request actually uses -- stops resolving, or
        the PDF's column layout changed for a report requested past the
        2025-12-22 format boundary.

        This is deliberately a second, separate probe from the legacy-era one
        above rather than a replacement for it: ``report_url`` branches on
        the era boundary, so the legacy probe only exercises the
        hour-truncating branch and cannot detect drift specific to this,
        the active branch. **Rotation and failure behaviour**: the NBA has
        changed this filename format once already, without any announcement
        found (see ``docs/adapters/nba-injury-report.md``), and could rotate
        to a third convention with the same silence for 2026-27. This test
        does not, and cannot, protect against that in advance -- it exists
        to fail loudly the day it happens, distinctly from the legacy probe,
        so the specific era that broke is legible from which test went red.
        It is marked ``live_smoke`` like every test in this module: visible
        on every deliberate `pytest -m live_smoke` run, but never part of the
        blocking Code/Adapter gate on a pull request (a third party's outage
        must not turn a correct change red).
        """
        body = injury_report.fetch(self._KNOWN_GOOD_ACTIVE_ERA_TIMESTAMP, max_age=NO_CACHE)
        result = parse_injury_report_pdf(
            body,
            report_timestamp=self._KNOWN_GOOD_ACTIVE_ERA_TIMESTAMP,
            source_url="https://ak-static.cms.nba.com/referee/injury/"
            "Injury-Report_2026-01-15_05_30PM.pdf",
        )
        assert len(result.entries) > 0, "a real active-era report had zero entries"

    def test_a_timestamp_with_no_published_report_is_reported_as_unavailable(
        self, injury_report: InjuryReportClient
    ) -> None:
        """FAILS IF: an off-season timestamp stops being rejected cleanly.

        Verified live 2026-08-17: this CDN answers a pre-season date with
        HTTP **403**, not 404 — the two are folded together into
        :class:`ReportNotAvailable` for exactly that reason (see
        ``client.py``). A month with no NBA games at all should never have a
        report.
        """
        off_season = datetime(2025, 8, 15, 17, 0, tzinfo=_EASTERN)
        with pytest.raises(ReportNotAvailable):
            injury_report.fetch(off_season, max_age=NO_CACHE)


class TestInjuryReportCurrentSeasonIsAlive:
    """A bounded, runtime-selected probe against whichever report should
    exist *right now*, rather than a fixed archived timestamp.

    Both probes above pin two already-*retired* filename eras against
    permanently archived PDFs. Archived URLs survive a format rotation by
    construction -- the CDN keeps serving the exact bytes it always served
    for that historical path -- so neither one can ever detect the NBA
    introducing a *third* filename convention or PDF column layout for
    2026-27. Only a request built from "now", at test-run time, has any
    chance of being served by whatever the source actually looks like today.

    The candidate itself is never a calendar guess ("yesterday"): it is
    always a date `select_recent_report_candidate` (`test_injury_report.py`)
    has independently confirmed had a real game, read from the committed,
    real `ScheduleLeagueV2` fixture, and it is only used once its own 17:30
    ET evening has actually passed relative to "now" -- see that function's
    docstring for exactly why both of those guards exist and what they
    fixed (a second focused review found a same-day future-timestamp bug and
    a routine-no-game-date false-failure risk in an earlier, calendar-only
    version of this probe).

    **What this can detect:** the CDN URL pattern or PDF column layout
    breaking for a *current*, game-backed, already-published request -- the
    one shape of drift the two archived probes above structurally cannot
    see.

    **What this cannot detect:** anything about a specific past or future
    format era (that is what the archived legacy and 15-minute probes above
    are for, and this is not a substitute for either); nor, beyond what
    `select_recent_report_candidate`'s known-game-dates + freshness guard
    already rules out, can it distinguish every possible "the source broke"
    from every possible "there happened to be no game that day" -- it can
    only ever probe a date this project has actually recorded as a real game
    day, so it says nothing about any other date.

    **Bounded by construction:** exactly one candidate timestamp, therefore
    at most one HTTP request, per run -- never a scan across multiple days.
    """

    def test_a_recently_expected_report_is_reachable_and_parses(self) -> None:
        """FAILS IF: the source or its layout has drifted for a live, current request.

        Skips (does not fail) when `select_recent_report_candidate` returns
        ``None`` -- no known game date is both already-published and fresh
        enough (see that function's docstring) -- rather than either
        producing a noisy red result against a source with nothing to
        report, or -- the failure mode this whole probe exists to avoid --
        silently treating an expected 403/404 as if it proved the adapter
        still works. A 403/404 encountered on an actual candidate is not
        caught here: it is a real failure, because the candidate is only
        ever a date this project has independently confirmed had a game.
        """
        candidate = select_recent_report_candidate(datetime.now(tz=UTC))
        if candidate is None:
            pytest.skip(
                "no known game date (from the recorded ScheduleLeagueV2 fixture) is "
                f"both already-published and within the {FRESHNESS_WINDOW.days}-day "
                "freshness window of now; no report is expected to exist for a date "
                "this probe can defend, so it is skipped rather than producing a "
                "noisy failure or silently treating an expected 403/404 as success. "
                "The candidate-selection logic itself is proven offline by "
                "test_injury_report.py::test_select_recent_report_candidate_*."
            )
        client = InjuryReportClient()
        body = client.fetch(candidate, max_age=NO_CACHE)
        result = parse_injury_report_pdf(
            body, report_timestamp=candidate, source_url=report_url(candidate)
        )
        assert len(result.entries) > 0, f"no entries parsed from the report for {candidate}"
