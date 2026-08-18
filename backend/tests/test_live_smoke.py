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

import os

import pytest

from hoops_gm.identity import IdentityResolver, ResolvableRecord
from hoops_gm.ingest.errors import SourceRejected
from hoops_gm.ingest.fantrax_official import FantraxOfficialClient, parse_league_info
from hoops_gm.ingest.nba import (
    NbaStatsClient,
    parse_box_score_summary_v3,
    parse_common_all_players,
    parse_league_game_finder,
    parse_teams,
)
from hoops_gm.ingest.record_fixtures import (
    FIXTURE_CURRENT_SEASON,
    FIXTURE_MIDSEASON_GAME_DATE,
    FIXTURE_MIDSEASON_GAME_ID,
    FIXTURE_STATS_SEASON,
)

pytestmark = pytest.mark.live_smoke

#: Live calls bypass the cache entirely. A smoke test served from a capture is
#: a contract test wearing a disguise, and would report the source as healthy
#: long after it stopped answering.
from datetime import timedelta  # noqa: E402

NO_CACHE = timedelta(0)


@pytest.fixture
def fantrax() -> FantraxOfficialClient:
    return FantraxOfficialClient()


@pytest.fixture
def nba() -> NbaStatsClient:
    return NbaStatsClient()


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
        assert len(games) > 1000, (
            f"only {len(games)} games for {FIXTURE_STATS_SEASON}; a full NBA regular "
            "season is 1,230"
        )

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
