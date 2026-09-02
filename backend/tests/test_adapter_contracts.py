"""Adapter gate: contract tests against recorded fixtures.

These run offline, on every push, and they are the mechanism that turns a
silent upstream schema change into a red build (ADR-006). They assert on the
*shape and the specific findings*, not merely that parsing did not raise —
a test that only checks "no exception" would have stayed green throughout the
period when ``BoxScoreSummaryV2`` was returning empty inactive lists.

**Never regenerate a fixture to make one of these pass.** If one goes red, find
out what changed upstream, record it in ``docs/handoff.md``, and only then run
``python -m hoops_gm.ingest.record_fixtures``.

A recorded fixture also cannot, by construction, tell us the upstream changed —
it keeps passing forever. That is what ``test_live_smoke.py`` is for, and it is
the half of the Adapter gate that actually earns its keep.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from hoops_gm.db.models.enums import DnpReason, ParticipationOutcome
from hoops_gm.ingest.errors import SourceContractError, SourceRejected
from hoops_gm.ingest.fantrax_official import (
    parse_adp,
    parse_draft_picks,
    parse_league_info,
    parse_player_ids,
)
from hoops_gm.ingest.importers import _missing_participation_player_anchors
from hoops_gm.ingest.nba import (
    MIN_POSITION_COVERAGE,
    PLAYER_INDEX_POSITIONS,
    combine_game_participation,
    parse_box_score_summary_v3,
    parse_box_score_traditional_v3,
    parse_common_all_players,
    parse_league_game_finder,
    parse_minutes_to_seconds,
    parse_participation_comment,
    parse_player_game_logs,
    parse_player_index,
    parse_teams,
)
from hoops_gm.ingest.record_fixtures import (
    _league_game_finder_fixture_ids,
    _select_league_game_finder_games,
)

pytestmark = pytest.mark.adapter_contract

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    loaded = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


# ==========================================================================
# Fantrax official
# ==========================================================================


class TestFantraxPlayerIds:
    """``getPlayerIds`` — the crosswalk's Fantrax side, and risk R24."""

    def test_the_payload_splits_into_players_and_team_entities(self) -> None:
        result = parse_player_ids(load("fantrax_getplayerids_nba.json"))

        # R24: thirty franchise entities are mixed in with the players. A naive
        # importer creates thirty garbage identity rows named "Team" and then
        # matches them against each other forever.
        assert len(result.team_entities) == 30, (
            "expected exactly one non-player entity per NBA franchise; "
            "a change here means the payload's row mix has changed"
        )
        assert len(result.players) > 1500
        assert result.unclassified == []
        assert result.total_rows == len(result.players) + 30

    def test_no_team_entity_is_parsed_as_a_player(self) -> None:
        result = parse_player_ids(load("fantrax_getplayerids_nba.json"))
        assert not [p for p in result.players if p.name == "Team"]
        assert not [p for p in result.players if p.position == "Tm"]

    def test_the_hash_in_a_team_identifier_corroborates_the_positional_label(self) -> None:
        """Both markers identify the same rows — but only one is relied on.

        ``position == "Tm"`` is what the parser uses. The ``#`` in the
        identifier is checked here as corroboration only: baking one source's
        incidental identifier format into the importer would make it
        structural, and it is not.
        """
        result = parse_player_ids(load("fantrax_getplayerids_nba.json"))
        assert all("#" in t.fantrax_id for t in result.team_entities)
        assert not [p for p in result.players if "#" in p.fantrax_id]

    def test_cross_reference_identifiers_are_optional_and_often_absent(self) -> None:
        """Every id is missing for some players, so none may be assumed.

        Measured 2026-08-17: sportRadarId on 1,438 of 1,788 rows, rotowireId on
        1,723, statsIncId on only 851. A parser that required any of them would
        drop between 4% and 52% of the payload.
        """
        result = parse_player_ids(load("fantrax_getplayerids_nba.json"))
        total = len(result.players)
        with_sportradar = sum(1 for p in result.players if p.sport_radar_id)
        with_stats_inc = sum(1 for p in result.players if p.stats_inc_id)

        assert 0 < with_sportradar < total, "sportRadarId must be present-but-partial"
        assert 0 < with_stats_inc < total, "statsIncId must be present-but-partial"
        # statsIncId is the sparsest of the three by a wide margin.
        assert with_stats_inc < with_sportradar

    def test_identifiers_are_coerced_to_text_regardless_of_json_type(self) -> None:
        """``statsIncId`` is a JSON integer, ``sportRadarId`` a string.

        Both land in ``player_external_ids.external_id``, which is a string
        column, so the coercion has to be the adapter's job.
        """
        result = parse_player_ids(load("fantrax_getplayerids_nba.json"))
        for player in result.players:
            for value in (player.stats_inc_id, player.rotowire_id, player.sport_radar_id):
                assert value is None or isinstance(value, str)

    def test_team_is_blank_for_most_rows_rather_than_absent(self) -> None:
        """``"(N/A)"`` normalises to ``""`` — unknown, not disagreeing.

        This is the measurement that settled Phase 1's open question about
        per-field evidence: two thirds of the payload can contribute no team
        evidence at all, and a single confidence float cannot distinguish that
        from a team that is known and contradicts.
        """
        result = parse_player_ids(load("fantrax_getplayerids_nba.json"))
        blank = sum(1 for p in result.players if not p.team)
        assert blank > len(result.players) / 2, (
            "most Fantrax player rows carry no team; if this stops being true "
            "the resolver's evidence weighting should be revisited"
        )
        assert not [p for p in result.players if p.team == "(N/A)"]

    def test_names_arrive_last_comma_first(self) -> None:
        result = parse_player_ids(load("fantrax_getplayerids_nba.json"))
        assert all(", " in p.name for p in result.players)

    def test_duplicate_names_exist_within_one_source(self) -> None:
        """Two people share a name inside Fantrax alone.

        This is why name-only matching cannot be trusted, and why the
        cross-reference identifiers are worth storing even though they bridge
        to nothing external.
        """
        result = parse_player_ids(load("fantrax_getplayerids_nba.json"))
        names = [p.name for p in result.players]
        duplicated = {n for n in names if names.count(n) > 1}
        assert duplicated, "expected at least one duplicated name in the payload"

    def test_a_payload_with_no_players_is_a_contract_error(self) -> None:
        with pytest.raises(SourceContractError):
            parse_player_ids({"40220#3020": {"position": "Tm", "teamName": "X"}})

    def test_a_json_array_is_a_contract_error(self) -> None:
        with pytest.raises(SourceContractError):
            parse_player_ids([{"name": "Jokic, Nikola"}])


class TestFantraxAdp:
    def test_adp_parses_and_stays_sorted(self) -> None:
        entries = parse_adp(load("fantrax_getadp_nba.json"))
        assert len(entries) > 100
        assert all(e.fantrax_id for e in entries)
        values = [e.adp for e in entries]
        assert values == sorted(values), "the endpoint has always returned ADP ascending"

    def test_limit_n_returns_n_minus_one_rows(self) -> None:
        """The ``limit`` parameter is off by one, and the adapter does not fix it.

        Verified live for limit=1, 2, 3, 5 and 10 on 2026-08-17: the endpoint
        returns ``limit - 1`` rows, and ``limit=1`` returns none at all.
        Silently adding one would hide an upstream fix; pinning it here means
        we find out if the behaviour ever changes.
        """
        entries = parse_adp(load("fantrax_getadp_nba_limit5.json"))
        assert len(entries) == 4, "limit=5 has always returned 4 rows"

    def test_a_non_numeric_adp_is_a_contract_error(self) -> None:
        with pytest.raises(SourceContractError):
            parse_adp([{"id": "abc", "name": "X", "pos": "PG", "ADP": "not a number"}])

    def test_a_missing_id_is_a_contract_error(self) -> None:
        with pytest.raises(SourceContractError):
            parse_adp([{"name": "X", "pos": "PG", "ADP": 1.0}])


class TestFantraxErrorEnvelope:
    """Fantrax signals refusal with an HTTP 200 body, not a status code."""

    def test_the_error_envelope_is_a_rejection_not_data(self) -> None:
        payload = load("fantrax_getleagueinfo_missing_league_id.json")
        # The fixture is a real HTTP 200 response body.
        assert "error" in payload

        with pytest.raises(SourceRejected) as caught:
            parse_league_info(payload)
        assert "leagueId" in str(caught.value)

    def test_every_parser_checks_the_envelope_before_parsing(self) -> None:
        """A client trusting ``response.ok`` would hand this to any of them."""
        payload = load("fantrax_getleagueinfo_missing_league_id.json")
        for parser in (parse_player_ids, parse_adp, parse_league_info):
            with pytest.raises(SourceRejected):
                parser(payload)


class TestFantraxLeagueSettings:
    """``getLeagueInfo`` — verified official settings and explicit gaps."""

    def test_success_payload_parses_the_verified_settings_shape(self) -> None:
        result = parse_league_info(
            load("fantrax_getleagueinfo_settings_sanitized.json"),
            league_id="<fixture-league>",
            capture_ref="fixture:fantrax_getleagueinfo_settings_sanitized.json",
        )

        assert result.roster_size == 14
        assert result.draft_type == "snake"
        assert result.scoring_type == "HEAD_TO_HEAD_ROTI_MULTI_WIN"
        assert len(result.scoring_categories) == 9
        assert {category.abbreviation for category in result.scoring_categories} == {
            "3PTM",
            "AST",
            "BLK",
            "FG%",
            "FT%",
            "PTS",
            "REB",
            "ST",
            "TO",
        }
        # `code` (not the numeric id, not the abbreviation) is the durable
        # mapping anchor `hoops_gm.scoring.profiles` keys off of -- tie every
        # one of the nine categories' code/abbreviation/weight exactly to
        # this capture so a future upstream rename shows up as a red build
        # here rather than a silent mis-scored category downstream.
        by_code = {category.code: category for category in result.scoring_categories}
        assert set(by_code) == {
            "INDIVIDUAL_ASSISTS",
            "INDIVIDUAL_BLOCKS",
            "INDIVIDUAL_POINTS",
            "INDIVIDUAL_REBOUNDS",
            "INDIVIDUAL_STEALS",
            "INDIVIDUAL_THREE_POINTERS_MADE",
            "INDIVIDUAL_TURNOVERS",
            "INDIVIDUAL_FIELD_GOAL_PERCENTAGE",
            "INDIVIDUAL_FREE_THROW_PERCENTAGE",
        }
        assert by_code["INDIVIDUAL_ASSISTS"].abbreviation == "AST"
        assert by_code["INDIVIDUAL_BLOCKS"].abbreviation == "BLK"
        assert by_code["INDIVIDUAL_POINTS"].abbreviation == "PTS"
        assert by_code["INDIVIDUAL_REBOUNDS"].abbreviation == "REB"
        assert by_code["INDIVIDUAL_STEALS"].abbreviation == "ST"
        assert by_code["INDIVIDUAL_THREE_POINTERS_MADE"].abbreviation == "3PTM"
        assert by_code["INDIVIDUAL_TURNOVERS"].abbreviation == "TO"
        assert by_code["INDIVIDUAL_FIELD_GOAL_PERCENTAGE"].abbreviation == "FG%"
        assert by_code["INDIVIDUAL_FREE_THROW_PERCENTAGE"].abbreviation == "FT%"
        # Every category observed live carries weight == 1.0. This is not
        # merely convenient: `hoops_gm.scoring.profiles` refuses to build a
        # profile from a non-unit weight (weighted categories are not yet
        # designed), so this fixture must keep proving the assumption holds.
        assert all(category.weight == 1.0 for category in result.scoring_categories)
        assert result.unmapped_keys == ()

        settings = result.settings
        assert settings is not None
        assert settings.source_season_year == 2025
        assert settings.source_start_date == "2025-10-21"
        assert settings.source_end_date == "2026-03-15"
        assert settings.roster_limits.value is not None
        assert settings.roster_limits.value.total == 14
        assert settings.roster_limits.value.active == 10
        assert settings.roster_limits.value.reserve == 14
        assert settings.roster_limits.value.injured_reserve is None
        assert settings.scoring_periods.value is not None
        assert len(settings.scoring_periods.value.periods) == 21
        # The settings document itself -- not just the adapter's own
        # FantraxLeagueInfo view -- must carry the same scoring evidence,
        # since `LeagueSettingsDocument` (not `FantraxLeagueInfo`) is what
        # `hoops_gm.scoring.profiles` actually derives a profile from.
        assert settings.scoring_type.value is not None
        assert settings.scoring_type.value.raw_type == "HEAD_TO_HEAD_ROTI_MULTI_WIN"
        assert settings.scoring_categories.value is not None
        assert len(settings.scoring_categories.value.categories) == 9
        assert {c.code for c in settings.scoring_categories.value.categories} == set(by_code)

    def test_unpublished_rules_remain_explicitly_unknown(self) -> None:
        result = parse_league_info(
            load("fantrax_getleagueinfo_settings_sanitized.json"),
            league_id="<fixture-league>",
            capture_ref="fixture:fantrax_getleagueinfo_settings_sanitized.json",
        )
        assert result.settings is not None

        unknown = (
            result.settings.lineup_lock,
            result.settings.waivers,
            result.settings.games_caps,
            result.settings.trade_deadline,
            result.settings.playoffs,
            result.settings.keepers,
        )
        assert all(setting.value is None for setting in unknown)
        assert all(
            evidence.status == "absent" for setting in unknown for evidence in setting.evidence
        )
        assert result.settings.unmapped_rule_paths == ()

    def test_fixture_removed_identity_sections_without_editing_retained_values(
        self, manifest: dict[str, Any]
    ) -> None:
        metadata = manifest["fantrax_getleagueinfo_settings_sanitized.json"]
        assert metadata["original_sha256"] == (
            "722b95c7bbecde2950aea9fea0ccc24519311248ee79a1320fe07455d718ae54"
        )
        assert set(metadata["removed_sections"]) == {
            "leagueHistoryId",
            "leagueName",
            "matchups",
            "playerInfo",
            "teamInfo",
        }
        assert "userSecretId" not in metadata["params"]
        payload = load("fantrax_getleagueinfo_settings_sanitized.json")
        assert not set(metadata["removed_sections"]) & set(payload)


class TestFantraxDraftPicks:
    """``getDraftPicks`` — verified live 2026-08-28, and it returned nothing.

    Every assertion here is pinned to one real response: league
    ``b2gyornvms4606iv``, holding a **completed 18-round 12-team snake draft**,
    answered ``HTTP 200 text/plain`` with 24 bytes — ``{"currentDraftPicks":[]}``.
    216 picks existed. The endpoint reported none of them.

    That is the finding, and these tests exist to stop it being quietly
    forgotten or quietly "fixed".

    **The fixture cannot, by itself, pin the key name.** Measured on the real
    chain: against ``{"currentDraftPicks":[]}`` the old reader and the new one
    both return zero picks, because an empty list looks identical to an absent
    one. The key-name defect is therefore pinned by the two constructed cases
    below, which do discriminate (``1`` vs ``0`` and ``0`` vs ``1``). A recorded
    fixture cannot test a guess — it can only test what the source sent.
    """

    FIXTURE = "fantrax_getdraftpicks_completed_snake_empty.json"

    #: The digest of the exact bytes the endpoint sent, carried out of the live
    #: read alongside the payload. Pinned here so a later reserialisation cannot
    #: arrive looking like an ordinary content change.
    CAPTURED_SHA256 = "b5811c858f69d6f11a9f6e0d5a878d9622edd21fe1d6f202a9d2bf5cfb915fca"

    def test_the_recorded_response_is_byte_exact(self) -> None:
        """A recording that has been through a serialiser is not a recording.

        24 bytes, no trailing newline, no re-indentation. Asserted on bytes and
        on the capture's own digest rather than on the decoded value, because
        everything this fixture is evidence *of* survives ``json.loads`` — and
        the thing the Adapter gate was burned by (a capture tool substituting
        its own representation for the producer's) does not show up in the
        decoded value at all. ``json.dumps`` of this payload with default
        separators is 26 bytes, not 24; that two-byte difference is the entire
        distance between a recording and a re-emission, and only the digest
        notices it.
        """
        raw = (FIXTURES / self.FIXTURE).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == self.CAPTURED_SHA256, (
            "the fixture no longer hashes to the bytes Fantrax sent on "
            "2026-08-28. If this was a deliberate re-capture, update "
            "CAPTURED_SHA256 and the manifest together; if it was a formatter, "
            "revert it - a reformatted capture is not evidence."
        )
        assert raw == b'{"currentDraftPicks":[]}'
        assert not raw.endswith(b"\n")

    def test_the_manifest_records_that_it_was_read_without_a_secret(
        self, manifest: dict[str, Any]
    ) -> None:
        """The endpoint is unauthenticated — no owner credential decision.

        This is load-bearing in the negative direction: because the read
        succeeded with only a non-secret ``leagueId``, an empty list cannot be
        explained away as "we were not logged in".
        """
        metadata = manifest[self.FIXTURE]
        assert metadata["params"] == {"leagueId": "b2gyornvms4606iv"}
        assert "userSecretId" not in metadata["params"]
        assert metadata["http_status"] == 200
        assert (FIXTURES / self.FIXTURE).stat().st_size == metadata["byte_size"]

    def test_a_completed_216_pick_draft_still_parses_to_zero_picks(self) -> None:
        """FAILS IF: someone makes this green by making the parser invent picks.

        18 rounds x 12 teams = 216 selections had already happened when this was
        captured. Zero is not the parser failing to read the payload; it is the
        payload.
        """
        assert parse_draft_picks(load(self.FIXTURE)) == []

    def test_the_real_key_is_currentDraftPicks_and_was_not_a_guess_we_had(
        self,
    ) -> None:
        """The second, independent finding — and the dangerous one.

        The parser looked for ``draftPicks`` or ``picks``. The live payload uses
        neither. Had the endpoint been returning selections all along, this
        parser would have returned zero of them and the draft feed would have
        reported a healthy, silent source. **Green tests, empty board.**

        This test asserts the shape of that near-miss so the key name cannot
        drift back to a guess.
        """
        payload = load(self.FIXTURE)
        assert set(payload) == {"currentDraftPicks"}
        assert "draftPicks" not in payload
        assert "picks" not in payload

    def test_an_empty_first_key_is_not_stepped_over_for_a_later_one(self) -> None:
        """FAILS IF: key selection goes back to a truthy ``or`` chain.

        Constructed input, not a recording — it exercises the selection rule
        that the real payload made reachable. Under ``a or b`` the empty
        ``currentDraftPicks`` is falsy and the reader falls through to
        ``draftPicks``, reporting a pick the source did not put under the key it
        actually uses. Presence-based selection reports the empty truth instead.
        """
        picks = parse_draft_picks(
            {
                "currentDraftPicks": [],
                "draftPicks": [{"teamId": "xwsfomdwms46061r", "overallPick": 91}],
            }
        )
        assert picks == []

    def test_a_populated_response_would_still_be_read(self) -> None:
        """Constructed, and honest about it: no populated payload exists.

        The field names come from the live *bridge* console on 2026-08-28
        (``draftTeamId``/``scorerId``/``overallPick``), which is a different
        recogniser and different vocabulary, so this asserts only that the
        official reader is not inert — **not** that these keys are what
        ``getDraftPicks`` would send. Nobody has seen what it would send.
        """
        picks = parse_draft_picks(
            {"currentDraftPicks": [{"teamId": "xwsfomdwms46061r", "overallPick": 91}]}
        )
        assert len(picks) == 1
        assert picks[0].team_id == "xwsfomdwms46061r"
        assert picks[0].overall_pick == 91

    def test_the_error_envelope_is_still_checked_before_parsing(self) -> None:
        with pytest.raises(SourceRejected):
            parse_draft_picks(load("fantrax_getleagueinfo_missing_league_id.json"))


# ==========================================================================
# nba_api
# ==========================================================================


class TestNbaStaticAndPlayers:
    def test_all_thirty_teams_parse(self) -> None:
        teams = parse_teams(load("nba_static_teams.json"))
        assert len(teams) == 30
        assert len({t.abbreviation for t in teams}) == 30
        assert all(t.nba_team_id > 0 for t in teams)

    def test_common_all_players_gives_a_last_comma_first_name(self) -> None:
        """The same shape Fantrax uses — convenient, and not a contract.

        The box-score endpoints give the name in parts and the game logs give
        "First Last", so the resolver normalises rather than relying on this.
        """
        players = parse_common_all_players(load("nba_commonallplayers_current.json"))
        assert len(players) > 400
        assert all(", " in p.display_last_comma_first for p in players)

    def test_the_current_season_fixture_has_a_team_for_every_player(self) -> None:
        """Which is exactly why the crosswalk must use the current season.

        Against a historical season, every player who moved in the offseason
        produces a spurious team disagreement.
        """
        players = parse_common_all_players(load("nba_commonallplayers_current.json"))
        assert all(p.team_abbreviation for p in players)

    def test_a_missing_column_is_a_contract_error(self) -> None:
        payload = load("nba_commonallplayers_current.json")
        payload["resultSets"][0]["headers"] = [
            h for h in payload["resultSets"][0]["headers"] if h != "DISPLAY_LAST_COMMA_FIRST"
        ]
        with pytest.raises(SourceContractError) as caught:
            parse_common_all_players(payload)
        assert "DISPLAY_LAST_COMMA_FIRST" in str(caught.value)

    def test_a_payload_with_no_result_sets_is_a_contract_error(self) -> None:
        with pytest.raises(SourceContractError):
            parse_common_all_players({"resource": "commonallplayers"})


class TestNbaPlayerIndexPosition:
    """``PlayerIndex`` — the project's only source of a player position.

    Every assertion here exists because something else in the project would be
    wrong without it, and each guard below is checked by *breaking the payload
    and watching the guard fire*, not merely by watching it pass on good data.
    A verifier that has only ever been seen passing is indistinguishable from
    one that cannot fail.
    """

    def test_it_lists_every_player_once_which_is_what_makes_it_an_attribute(self) -> None:
        records = parse_player_index(load("nba_playerindex_current.json"), season="2026-27")

        assert len(records) > 500
        assert len({r.nba_player_id for r in records}) == len(records)

    def test_the_position_vocabulary_is_coarse_and_has_no_point_guard(self) -> None:
        """The single most consequential fact about this field.

        `G/F/C` plus hybrids, and nothing finer — checked on 2026-08-20 against
        `PlayerIndex`, `CommonPlayerInfo` ("Guard") and `CommonTeamRoster`
        ("G"), while `PlayerIndex` answers a `PlayerPosition=PG` filter with
        `{"PlayerPosition": ["Invalid parameters"]}`.

        So this field can separate a centre from a guard — which is what the
        identity crosswalk needs — and can **not** express a Fantrax lineup
        slot. If this assertion ever fails because `PG` appeared, that is a
        genuine change in what the NBA publishes and somebody should read
        `docs/backlog.md`'s `player-position-eligibility` before celebrating.
        """
        records = parse_player_index(load("nba_playerindex_current.json"), season="2026-27")

        stated = {r.position for r in records if r.position is not None}
        assert stated <= PLAYER_INDEX_POSITIONS
        assert not stated & {"PG", "SG", "SF", "PF"}

    def test_it_is_not_the_box_score_starting_slot(self) -> None:
        """The distinction this whole record type exists to preserve.

        `BoxScoreTraditionalV3.position` is emitted for exactly five players
        per team per game, always `F,F,C,G,G`. Asserted here side by side
        rather than described, because the two fields carry the same-looking
        letters and the reason to believe they are different quantities should
        be executable.
        """
        box = load("nba_boxscoretraditionalv3_0022400306.json")["boxScoreTraditional"]
        for side in ("homeTeam", "awayTeam"):
            slots = [p.get("position") for p in box[side]["players"] if p.get("position")]
            assert sorted(slots) == ["C", "F", "F", "G", "G"], (
                "the box-score field is a five-slot starting lineup; if this ever "
                "stops being true the two fields may have converged and the "
                "position source should be re-examined"
            )

        records = parse_player_index(load("nba_playerindex_current.json"), season="2026-27")
        by_team: dict[str | None, list[str | None]] = {}
        for record in records:
            by_team.setdefault(record.team_abbreviation, []).append(record.position)

        assert len(by_team) == 30
        # A starting-lineup slot would give exactly five per team. A roster
        # listing gives a roster.
        assert min(len(v) for v in by_team.values()) > 5
        # And it could not express a hybrid at all.
        assert any(r.position and "-" in r.position for r in records)

    def test_an_unstated_position_is_preserved_as_none_never_guessed(self) -> None:
        """Six 2026-27 rows state no position, and that is real absence.

        `CommonPlayerInfo` returns `''` for the same players, all of whom have
        `FROM_YEAR: 2026`. Inventing a position for them would corroborate an
        identity match on evidence nobody supplied — which is the specific way
        a scalar confidence score lies (see `identity/evidence.py`).
        """
        records = parse_player_index(load("nba_playerindex_current.json"), season="2026-27")

        unstated = [r for r in records if r.position is None]
        assert unstated, "the fixture is expected to contain genuinely unlisted players"
        assert all(r.nba_player_id > 0 for r in unstated)

    def test_the_season_is_carried_so_a_stored_position_can_be_refreshed(self) -> None:
        records = parse_player_index(load("nba_playerindex_current.json"), season="2026-27")
        assert {r.season for r in records} == {"2026-27"}

    # -- the guards, each broken deliberately ------------------------------

    def test_rows_with_an_unusable_person_id_are_fatal_not_quietly_dropped(self) -> None:
        """Dropping them would raise the coverage figure, not lower it.

        The coverage floor divides by the rows that survived parsing, so a
        payload that loses most of its rows to unparseable `PERSON_ID`s would
        report *higher* coverage than a healthy one — a guard whose denominator
        moves with the failure it is watching for. Found by review; it was
        silently `continue` before.
        """
        payload = load("nba_playerindex_current.json")
        table = payload["resultSets"][0]
        column = table["headers"].index("PERSON_ID")
        for row in table["rowSet"][:500]:
            row[column] = None

        with pytest.raises(SourceContractError) as caught:
            parse_player_index(payload, season="2026-27")
        message = str(caught.value)
        assert "500 of 578" in message
        assert "PERSON_ID" in message

    def test_a_wholly_unusable_id_column_is_not_reported_as_an_empty_listing(self) -> None:
        """The total case, which the empty-records check used to shadow.

        When *every* id is unparseable, `records` is empty as well, and the
        `if not records` branch used to win the race — reporting "no player
        rows" for a payload that returned 578 of them. That message is the one
        this adapter's own documentation attaches to a nonexistent season,
        which returns 200 with an empty `rowSet`. So the total version of the
        failure the guard was written for was routed to a different diagnosis.
        """
        payload = load("nba_playerindex_current.json")
        table = payload["resultSets"][0]
        column = table["headers"].index("PERSON_ID")
        for row in table["rowSet"]:
            row[column] = "not-an-int"

        with pytest.raises(SourceContractError) as caught:
            parse_player_index(payload, season="2026-27")
        message = str(caught.value)
        assert "578 of 578" in message
        assert "no player rows" not in message

    def test_a_malformed_season_is_refused_at_the_parse_boundary(self) -> None:
        """SQLite would take it; PostgreSQL would not — so it is caught here.

        ``season`` lands in a 9-character column. SQLite ignores a declared
        VARCHAR length and PostgreSQL enforces it, so an over-long season is
        the ADR-001 divergence in its purest form: green locally, `value too
        long for type character varying(9)` in production. Nothing downstream
        validates it, so the parse boundary is the last place it can be caught
        cheaply.
        """
        payload = load("nba_playerindex_current.json")

        with pytest.raises(SourceContractError) as caught:
            parse_player_index(payload, season="2026-2027-extended")
        assert "YYYY-YY" in str(caught.value)

        # And the shape check does not reject the real form.
        assert parse_player_index(payload, season="2026-27")

    def test_a_season_disagreement_with_the_payload_is_a_contract_error(self) -> None:
        """The season was a pure caller assertion until independent review.

        ``season`` is stamped onto every record and thence onto
        ``players.primary_position_season``, whose entire justification is that
        a stored position must know which season it describes. Nothing checked
        it against the data — the `gameEt` shape, a self-describing value
        believed rather than corroborated. The payload echoes the season the
        server actually served, so it is checked against that.
        """
        payload = load("nba_playerindex_current.json")
        assert payload["parameters"]["Season"] == "2026-27"

        with pytest.raises(SourceContractError) as caught:
            parse_player_index(payload, season="1997-98")
        assert "1997-98" in str(caught.value)
        assert "2026-27" in str(caught.value)

    def test_a_payload_that_states_no_season_withholds_rather_than_fails(self) -> None:
        """Absence is not disagreement — the rule the whole evidence model runs on.

        If the endpoint stops echoing its parameters, "the server did not say"
        must not be read as "the server contradicted us".

        **Both routes to absence are driven**, because they are different
        branches and only one of them was covered until review: the parameters
        block disappearing entirely, and the block surviving with `Season`
        blanked or dropped. The second is the more likely upstream drift — a
        payload keeping its envelope and losing one field — and deleting the
        `declared and` sub-condition left the *entire* suite green.
        """
        # Route A: no parameters block at all.
        payload = load("nba_playerindex_current.json")
        del payload["parameters"]
        assert len(parse_player_index(payload, season="2026-27")) > 500

        # Route B: parameters present, Season blanked.
        payload = load("nba_playerindex_current.json")
        payload["parameters"]["Season"] = ""
        assert len(parse_player_index(payload, season="2026-27")) > 500

        # Route B': parameters present, Season key gone.
        payload = load("nba_playerindex_current.json")
        del payload["parameters"]["Season"]
        assert len(parse_player_index(payload, season="2026-27")) > 500

        # And a *stated* season still disagrees, so withholding has not been
        # widened into blanket acceptance.
        payload = load("nba_playerindex_current.json")
        payload["parameters"]["Season"] = "1997-98"
        with pytest.raises(SourceContractError):
            parse_player_index(payload, season="2026-27")

    def test_the_name_columns_that_are_read_are_also_required(self) -> None:
        """Every column this parser reads is pinned, not just the load-bearing ones.

        ``ResultTable.get`` returns ``None`` for an unknown column rather than
        raising, so a column that is read but not declared in ``require()``
        turns a source rename into silent ``None``s instead of a contract
        error. ``PLAYER_FIRST_NAME`` and ``PLAYER_LAST_NAME`` are read into
        every record and were unpinned until independent review; nothing
        consumes them yet, which is exactly why it would have gone unnoticed.
        """
        for column in ("PLAYER_FIRST_NAME", "PLAYER_LAST_NAME"):
            payload = load("nba_playerindex_current.json")
            payload["resultSets"][0]["headers"] = [
                h for h in payload["resultSets"][0]["headers"] if h != column
            ]
            with pytest.raises(SourceContractError) as caught:
                parse_player_index(payload, season="2026-27")
            assert column in str(caught.value)

    def test_a_missing_position_column_is_a_contract_error(self) -> None:
        payload = load("nba_playerindex_current.json")
        payload["resultSets"][0]["headers"] = [
            h for h in payload["resultSets"][0]["headers"] if h != "POSITION"
        ]

        with pytest.raises(SourceContractError) as caught:
            parse_player_index(payload, season="2026-27")
        assert "POSITION" in str(caught.value)

    def test_a_new_position_value_is_a_contract_error_not_a_silent_passthrough(self) -> None:
        """Mutation check for the vocabulary guard.

        `PG` is the mutation that matters: if the NBA ever published it, every
        stored coarse position would be describing a different vocabulary, and
        the tempting reading — "great, now we can do Fantrax eligibility" — is
        wrong for reasons that need a human. Deliberately fatal.
        """
        payload = load("nba_playerindex_current.json")
        table = payload["resultSets"][0]
        column = table["headers"].index("POSITION")
        table["rowSet"][0][column] = "PG"

        with pytest.raises(SourceContractError) as caught:
            parse_player_index(payload, season="2026-27")
        assert "'PG'" in str(caught.value)
        assert "vocabulary" in str(caught.value)

    def test_a_repeated_person_id_is_a_contract_error(self) -> None:
        """Mutation check for the one-row-per-player guard.

        Duplicating a row is what a per-stint or per-game listing would look
        like, and it is the shape that would mean "his position" no longer has
        one answer.
        """
        payload = load("nba_playerindex_current.json")
        table = payload["resultSets"][0]
        table["rowSet"].append(list(table["rowSet"][0]))

        with pytest.raises(SourceContractError) as caught:
            parse_player_index(payload, season="2026-27")
        assert "more than once" in str(caught.value)

    def test_a_lineup_slot_shaped_payload_trips_the_coverage_floor(self) -> None:
        """Mutation check for the coverage guard, using the failure it guards against.

        This is the guard's actual reason to exist, so it is broken in the
        specific way that matters rather than by nulling a column: keep a
        position for five players per team and blank the rest — exactly what
        this field would look like if it were replaced by, or degraded into, a
        starting-lineup slot. The vocabulary guard cannot see this (the values
        are still `G`/`F`/`C`) and neither can the duplicate guard (still one
        row each), which is why coverage is a separate check.
        """
        payload = load("nba_playerindex_current.json")
        table = payload["resultSets"][0]
        position = table["headers"].index("POSITION")
        team = table["headers"].index("TEAM_ABBREVIATION")

        kept: dict[Any, int] = {}
        for row in table["rowSet"]:
            count = kept.get(row[team], 0)
            if count < 5 and row[position]:
                kept[row[team]] = count + 1
            else:
                row[position] = ""

        with pytest.raises(SourceContractError) as caught:
            parse_player_index(payload, season="2026-27")
        message = str(caught.value)
        assert "starting" in message
        assert "Do not persist" in message

    def test_an_emptied_position_column_also_trips_the_coverage_floor(self) -> None:
        payload = load("nba_playerindex_current.json")
        table = payload["resultSets"][0]
        column = table["headers"].index("POSITION")
        for row in table["rowSet"]:
            row[column] = ""

        with pytest.raises(SourceContractError):
            parse_player_index(payload, season="2026-27")

    def test_the_coverage_floor_leaves_real_headroom(self) -> None:
        """The floor must be loose enough not to fire on an ordinary season.

        A guard tuned so tightly that a normal payload trips it gets disabled,
        which is a worse outcome than not having it. Observed coverage is
        98.9%; this pins the margin so a later tightening is a deliberate act.
        """
        records = parse_player_index(load("nba_playerindex_current.json"), season="2026-27")
        stated = sum(1 for r in records if r.position is not None)
        coverage = stated / len(records)

        assert coverage > MIN_POSITION_COVERAGE
        assert coverage - MIN_POSITION_COVERAGE > 0.05

    def test_a_payload_with_no_rows_is_a_contract_error(self) -> None:
        payload = load("nba_playerindex_current.json")
        payload["resultSets"][0]["rowSet"] = []

        with pytest.raises(SourceContractError) as caught:
            parse_player_index(payload, season="2026-27")
        assert "no player rows" in str(caught.value)


class TestNbaGamesAndLogs:
    def test_games_collapse_to_one_record_with_home_and_away_the_right_way_round(
        self,
    ) -> None:
        """Home and away are derived from matchup abbreviations, never row order."""
        games = parse_league_game_finder(
            load("nba_leaguegamefinder_trimmed.json"), season="2024-25"
        )
        assert games
        for game in games:
            assert game.home_team_id != game.away_team_id
        assert len({g.nba_game_id for g in games}) == len(games)

    def test_canonical_matchup_repetition_reconciles_by_team_abbreviation(self) -> None:
        games = parse_league_game_finder(
            load("nba_leaguegamefinder_reconciliation.json"), season="2024-25"
        )
        payload = load("nba_leaguegamefinder_reconciliation.json")
        table = payload["resultSets"][0]
        game_id = table["headers"].index("GAME_ID")
        matchup = table["headers"].index("MATCHUP")
        team_abbreviation = table["headers"].index("TEAM_ABBREVIATION")
        anomaly_rows = [row for row in table["rowSet"] if row[game_id] == "0022400633"]
        assert {row[matchup] for row in anomaly_rows} == {"IND @ SAS"}
        assert len({row[team_abbreviation] for row in anomaly_rows}) == 2

        assert [game.nba_game_id for game in games] == ["0022400633", "0022401188"]
        repeated = games[0]
        assert repeated.away_team_id == 1610612754
        assert repeated.home_team_id == 1610612759
        assert repeated.away_score == 136
        assert repeated.home_score == 98
        assert repeated.game_date == date(2025, 1, 25)
        assert repeated.tipoff_utc is None

    def test_row_order_does_not_change_game_order_or_reconciliation(self) -> None:
        payload = load("nba_leaguegamefinder_reconciliation.json")
        payload["resultSets"][0]["rowSet"].reverse()

        games = parse_league_game_finder(payload, season="2024-25")

        assert [game.nba_game_id for game in games] == ["0022400633", "0022401188"]
        assert games[0].away_team_id == 1610612754
        assert games[0].home_team_id == 1610612759

    def test_one_sided_game_fails_loudly_instead_of_disappearing(self) -> None:
        payload = load("nba_leaguegamefinder_reconciliation.json")
        payload["resultSets"][0]["rowSet"] = payload["resultSets"][0]["rowSet"][:1]

        with pytest.raises(SourceContractError, match="incomplete reciprocal rows"):
            parse_league_game_finder(payload, season="2024-25")

    def test_duplicate_side_row_is_rejected_even_when_identical(self) -> None:
        payload = load("nba_leaguegamefinder_reconciliation.json")
        payload["resultSets"][0]["rowSet"].append(payload["resultSets"][0]["rowSet"][0].copy())

        with pytest.raises(SourceContractError, match="duplicate away team row"):
            parse_league_game_finder(payload, season="2024-25")

    def test_conflicting_canonical_matchup_is_rejected(self) -> None:
        payload = load("nba_leaguegamefinder_reconciliation.json")
        table = payload["resultSets"][0]
        matchup = table["headers"].index("MATCHUP")
        table["rowSet"][1][matchup] = "IND vs. SAS"

        with pytest.raises(SourceContractError, match="conflicting home/away MATCHUP"):
            parse_league_game_finder(payload, season="2024-25")

    @pytest.mark.parametrize(
        ("season", "season_type", "message"),
        [
            ("2025-26", "regular", "payload season"),
            ("2024-25", "playoffs", "payload season type"),
        ],
    )
    def test_declared_source_scope_must_match_requested_scope(
        self, season: str, season_type: str, message: str
    ) -> None:
        with pytest.raises(SourceContractError, match=message):
            parse_league_game_finder(
                load("nba_leaguegamefinder_reconciliation.json"),
                season=season,
                season_type=season_type,
            )

    def test_missing_declared_source_scope_is_rejected(self) -> None:
        payload = load("nba_leaguegamefinder_reconciliation.json")
        del payload["parameters"]

        with pytest.raises(SourceContractError, match="lacks declared"):
            parse_league_game_finder(payload, season="2024-25")

    @pytest.mark.parametrize(
        ("parameter", "value"),
        [
            ("DateFrom", "01/01/2025"),
            ("DateTo", "01/31/2025"),
            ("GameID", "0022400633"),
            ("TeamID", 1610612754),
            ("VsTeamID", 1610612759),
        ],
    )
    def test_narrowed_source_scope_cannot_masquerade_as_a_full_season(
        self, parameter: str, value: object
    ) -> None:
        payload = load("nba_leaguegamefinder_reconciliation.json")
        payload["parameters"][parameter] = value

        with pytest.raises(SourceContractError, match=rf"narrowed.*{parameter}"):
            parse_league_game_finder(payload, season="2024-25")

    @pytest.mark.parametrize(
        ("parameter", "value", "message"),
        [
            ("LeagueID", "10", "not NBA league"),
            ("PlayerOrTeam", "P", "not scoped to team rows"),
        ],
    )
    def test_non_nba_or_non_team_source_scope_is_rejected(
        self, parameter: str, value: object, message: str
    ) -> None:
        payload = load("nba_leaguegamefinder_reconciliation.json")
        payload["parameters"][parameter] = value

        with pytest.raises(SourceContractError, match=message):
            parse_league_game_finder(payload, season="2024-25")

    def test_row_season_scope_must_match_requested_scope(self) -> None:
        payload = load("nba_leaguegamefinder_reconciliation.json")
        table = payload["resultSets"][0]
        season_id = table["headers"].index("SEASON_ID")
        table["rowSet"][0][season_id] = "42024"

        with pytest.raises(SourceContractError, match="row SEASON_ID"):
            parse_league_game_finder(payload, season="2024-25")

    def test_game_id_must_be_canonical_for_the_requested_scope(self) -> None:
        payload = load("nba_leaguegamefinder_reconciliation.json")
        table = payload["resultSets"][0]
        game_id = table["headers"].index("GAME_ID")
        table["rowSet"][0][game_id] = "game-2024-25"

        with pytest.raises(SourceContractError, match="noncanonical GAME_ID"):
            parse_league_game_finder(payload, season="2024-25")

    def test_points_column_is_required_for_completed_game_evidence(self) -> None:
        payload = load("nba_leaguegamefinder_reconciliation.json")
        table = payload["resultSets"][0]
        points = table["headers"].index("PTS")
        table["headers"][points] = "POINTS"

        with pytest.raises(SourceContractError, match=r"missing columns.*PTS"):
            parse_league_game_finder(payload, season="2024-25")

    def test_playoffs_scope_accepts_canonical_season_and_game_ids(self) -> None:
        games = parse_league_game_finder(
            load("nba_leaguegamefinder_playoffs.json"),
            season="2024-25",
            season_type="playoffs",
        )

        assert games
        assert all(game.nba_game_id.startswith("00424") for game in games)
        assert all(game.season_type == "playoffs" for game in games)

    def test_an_unrecognised_matchup_string_is_a_contract_error(self) -> None:
        payload = load("nba_leaguegamefinder_trimmed.json")
        table = payload["resultSets"][0]
        position = table["headers"].index("MATCHUP")
        table["rowSet"][0][position] = "LAL versus POR"
        with pytest.raises(SourceContractError):
            parse_league_game_finder(payload, season="2024-25")

    def test_game_logs_parse_with_exact_seconds(self) -> None:
        """``MIN_SEC`` is exact; ``MIN`` is a rounded decimal.

        Preferring the wrong one loses information on every row, which is the
        sort of error that never announces itself.
        """
        logs = parse_player_game_logs(load("nba_playergamelogs_trimmed.json"))
        assert logs
        played = [log for log in logs if log.seconds_played]
        assert played
        # A rounded decimal would land on a multiple of 6 seconds far more
        # often than chance; exact values do not.
        seconds = [log.seconds_played for log in played if log.seconds_played is not None]
        assert any(value % 60 not in (0, 6, 12, 24, 30, 36, 48) for value in seconds)

    def test_makes_and_attempts_are_kept_not_percentages(self) -> None:
        """Risk R9 at the ingest boundary.

        A percentage without its denominator cannot be volume-weighted later,
        and a 90% free-throw shooter on one attempt is worthless.
        """
        logs = parse_player_game_logs(load("nba_playergamelogs_trimmed.json"))
        shooters = [log for log in logs if log.field_goals_attempted]
        assert shooters
        assert all(
            log.field_goals_made is not None and log.field_goals_attempted is not None
            for log in shooters
        )


class TestMinutesParsing:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("34:12", 34 * 60 + 12),
            ("48:24", 48 * 60 + 24),
            ("1:49", 109),
            ("PT34M12.00S", 34 * 60 + 12),
            ("PT0M00.00S", 0),
            (34.2, 2052),
            # Absent is not zero: a player who did not appear has no minutes,
            # and flattening that to 0 would make an absence look like an
            # appearance that produced nothing.
            ("", None),
            (None, None),
        ],
    )
    def test_every_observed_minutes_representation(
        self, value: object, expected: int | None
    ) -> None:
        assert parse_minutes_to_seconds(value) == expected


class TestParticipationComments:
    @pytest.mark.parametrize(
        ("comment", "outcome", "reason"),
        [
            (
                "DNP - Coach's Decision",
                ParticipationOutcome.DID_NOT_PLAY,
                DnpReason.COACHES_DECISION,
            ),
            (
                "DND - Injury/Illness",
                ParticipationOutcome.DID_NOT_DRESS,
                DnpReason.INJURY_OR_ILLNESS,
            ),
            (
                "DNP - Injury/Illness",
                ParticipationOutcome.DID_NOT_PLAY,
                DnpReason.INJURY_OR_ILLNESS,
            ),
            (
                "NWT - Not With Team",
                ParticipationOutcome.NOT_WITH_TEAM,
                DnpReason.NOT_WITH_TEAM,
            ),
            # No spaces around the hyphen. Observed in the same season as the
            # spaced forms; splitting on " - " drops this one on the floor.
            (
                "NWT-Return to Competition Reconditioning",
                ParticipationOutcome.NOT_WITH_TEAM,
                DnpReason.CONDITIONING,
            ),
        ],
    )
    def test_the_real_comment_vocabulary(
        self, comment: str, outcome: ParticipationOutcome, reason: DnpReason
    ) -> None:
        assert parse_participation_comment(comment) == (outcome, reason)

    def test_an_empty_comment_means_the_player_appeared(self) -> None:
        assert parse_participation_comment("") == (None, DnpReason.NONE_GIVEN)

    def test_an_unrecognised_reason_is_other_not_a_guess(self) -> None:
        outcome, reason = parse_participation_comment("DNP - Left The Arena Early")
        assert outcome is ParticipationOutcome.DID_NOT_PLAY
        assert reason is DnpReason.OTHER

    def test_a_reason_containing_a_hyphen_keeps_its_tail(self) -> None:
        outcome, reason = parse_participation_comment("DNP - Injury/Illness - Left Knee - Soreness")
        assert outcome is ParticipationOutcome.DID_NOT_PLAY
        assert reason is DnpReason.INJURY_OR_ILLNESS


class TestBoxScoreV3:
    def test_traditional_v3_yields_box_scores_and_participation(self) -> None:
        box_scores, participation = parse_box_score_traditional_v3(
            load("nba_boxscoretraditionalv3_0022400306.json")
        )
        assert box_scores
        assert participation
        # Everyone in the box score dressed; some of them did not play.
        assert len(participation) >= len(box_scores)
        played = [r for r in participation if r.outcome is ParticipationOutcome.PLAYED]
        assert len(played) == len(box_scores)

    def test_a_dnp_record_keeps_the_raw_comment_verbatim(self) -> None:
        """The normalisation will be wrong at first; the raw text is the recourse."""
        _, participation = parse_box_score_traditional_v3(
            load("nba_boxscoretraditionalv3_0022400306.json")
        )
        absences = [r for r in participation if r.outcome is not ParticipationOutcome.PLAYED]
        assert absences, "this fixture was chosen because it contains absences"
        for record in absences:
            assert record.raw_comment.strip(), "an absence must carry the source's own words"

    def test_summary_v3_carries_tipoff_as_an_aware_utc_instant(self) -> None:
        """``UTCDateTime`` rejects a naive datetime, and rest-day detection
        depends on this column being a real instant rather than a local
        wall-clock time."""
        game, _ = parse_box_score_summary_v3(load("nba_boxscoresummaryv3_0022400306.json"))
        assert game is not None
        assert game.tipoff_utc is not None
        assert game.tipoff_utc.tzinfo is not None
        assert game.tipoff_utc.utcoffset() is not None

    def test_summary_v3_carries_inactive_players_for_a_midseason_game(self) -> None:
        """**The finding this whole fixture set exists to pin.**

        ``BoxScoreSummaryV2.InactivePlayers`` returned data for 2025-10-21 and
        **zero rows for every 2025-26 date after it** — bisected on 2026-08-17.
        V2 is the endpoint most public examples use. Had this adapter used it,
        the participation ledger would have held no inactives at all for the
        most recent season, with no error and no failing test: a pillar of this
        project built on nothing.

        So this asserts a **non-zero** count for a known mid-season game. A
        test asserting only that the call succeeded, or that the key exists,
        would have passed throughout the period the data was silently gone.
        """
        _, participation = parse_box_score_summary_v3(
            load("nba_boxscoresummaryv3_0022500560_midseason.json")
        )
        assert participation.inactives_available is True
        assert participation.inactive_count > 0, (
            "a mid-season NBA game always has inactive players; zero here means "
            "the endpoint has stopped reporting them, exactly as V2 did"
        )
        for record in participation.records:
            assert record.outcome is ParticipationOutcome.INACTIVE
            # The inactive list states no reason. Recording INJURY_OR_ILLNESS
            # because most inactives are injuries would fabricate a training
            # label for the availability model.
            assert record.reason is DnpReason.NONE_GIVEN

    def test_an_absent_inactives_key_is_not_an_empty_inactive_list(self) -> None:
        """ "Nobody was inactive" and "we no longer know" are different facts."""
        payload = load("nba_boxscoresummaryv3_0022400306.json")
        for side in ("homeTeam", "awayTeam"):
            payload["boxScoreSummary"][side].pop("inactives", None)
        _, participation = parse_box_score_summary_v3(payload)
        assert participation.inactives_available is False
        assert participation.inactive_count == 0

        payload = load("nba_boxscoresummaryv3_0022400306.json")
        for side in ("homeTeam", "awayTeam"):
            payload["boxScoreSummary"][side]["inactives"] = []
        _, participation = parse_box_score_summary_v3(payload)
        assert participation.inactives_available is True
        assert participation.inactive_count == 0

    @pytest.mark.parametrize("degraded_side", ["homeTeam", "awayTeam"])
    def test_one_team_reporting_is_not_the_source_telling_us(self, degraded_side: str) -> None:
        """A one-sided degradation is not a usable inactive list.

        Recording it as "the source told us" while half the game's inactives
        are missing is structurally the same failure as the V2 rot this column
        exists to make impossible — a partial answer presented as a whole one.
        """
        payload = load("nba_boxscoresummaryv3_0022500560_midseason.json")
        payload["boxScoreSummary"][degraded_side].pop("inactives", None)
        _, participation = parse_box_score_summary_v3(payload)
        assert participation.inactives_available is False, "one team's list is not the game's list"

    @pytest.mark.parametrize("broken", [None, {}, "none", 0])
    def test_a_malformed_inactives_value_is_not_an_empty_list(self, broken: object) -> None:
        """`null` or an object under the key is the source failing to answer.

        The type check has to precede the flag, or a malformed value is
        recorded as an honest "nobody was inactive".
        """
        payload = load("nba_boxscoresummaryv3_0022500560_midseason.json")
        payload["boxScoreSummary"]["homeTeam"]["inactives"] = broken
        _, participation = parse_box_score_summary_v3(payload)
        assert participation.inactives_available is False

    def test_inactive_players_are_absent_from_the_traditional_box_score(self) -> None:
        """Which is why both endpoints are needed, not one.

        A player on the inactive list has no row in ``BoxScoreTraditionalV3``
        at all, so the participation ledger cannot be built from it alone.
        """
        box_scores, participation = parse_box_score_traditional_v3(
            load("nba_boxscoretraditionalv3_0022500560_midseason.json")
        )
        _, summary = parse_box_score_summary_v3(
            load("nba_boxscoresummaryv3_0022500560_midseason.json")
        )
        dressed = {r.nba_player_id for r in participation}
        inactive = {r.nba_player_id for r in summary.records}
        assert inactive
        assert not (dressed & inactive)
        assert box_scores

    def test_combining_both_endpoints_gives_the_whole_game(self) -> None:
        _, participation = parse_box_score_traditional_v3(
            load("nba_boxscoretraditionalv3_0022500560_midseason.json")
        )
        _, summary = parse_box_score_summary_v3(
            load("nba_boxscoresummaryv3_0022500560_midseason.json")
        )
        combined = combine_game_participation(participation, summary)

        assert combined.inactives_available is True
        assert combined.inactive_count == len(summary.records)
        assert len(combined.records) == len(participation) + len(summary.records)
        # One row per player, always.
        identifiers = [r.nba_player_id for r in combined.records]
        assert len(identifiers) == len(set(identifiers))
        missing_id = identifiers[0]
        anchors = _missing_participation_player_anchors(
            combined,
            known_player_ids={
                str(player_id): index for index, player_id in enumerate(identifiers[1:])
            },
        )
        assert [(anchor.nba_player_id, anchor.display_first_last) for anchor in anchors] == [
            (
                missing_id,
                next(
                    record.player_name
                    for record in combined.records
                    if record.nba_player_id == missing_id
                ),
            )
        ]

    def test_the_game_date_is_the_local_date_not_the_utc_one(self) -> None:
        """A real bug, found after the PR was opened, by checking rather than assuming.

        ``nba_games.game_date`` means the **local** calendar date, because
        fantasy days are defined in local time. Game ``0022500560`` has
        ``gameTimeUTC = 2026-01-13T00:30:00Z`` and is a **2026-01-12** game.
        Taking ``tipoff.date()`` produced the 13th — wrong for every game
        tipping after 7pm Eastern, which is most of them — and disagreed with
        ``LeagueGameFinder``, so the same game got two different dates
        depending on which endpoint wrote it last.
        """
        game, _ = parse_box_score_summary_v3(
            load("nba_boxscoresummaryv3_0022500560_midseason.json")
        )
        assert game is not None
        assert game.game_date == date(2026, 1, 12), (
            "the local game date, not the UTC date of the tip-off instant"
        )
        # The instant is still the real UTC instant, on the following day.
        assert game.tipoff_utc is not None
        assert game.tipoff_utc.date() == date(2026, 1, 13)

    def test_game_et_lies_about_its_timezone_and_is_read_for_its_date_only(self) -> None:
        """``gameEt`` is Eastern time wearing a ``Z`` suffix.

        The same payload carries ``gameTimeUTC = 2024-12-01T20:30:00Z`` and
        ``gameEt = 2024-12-01T15:30:00Z`` — five hours apart, both marked UTC.
        Passing ``gameEt`` to the instant parser would produce a time five
        hours wrong, so it is only ever read for its date.
        """
        payload = load("nba_boxscoresummaryv3_0022400306.json")
        body = payload["boxScoreSummary"]
        utc = body["gameTimeUTC"]
        eastern = body["gameEt"]
        assert utc.endswith("Z") and eastern.endswith("Z")
        assert utc != eastern, "the two fields disagree despite both claiming UTC"

        game, _ = parse_box_score_summary_v3(payload)
        assert game is not None
        # The instant comes from gameTimeUTC, so it matches that field and not
        # the mislabelled local one.
        assert game.tipoff_utc is not None
        assert game.tipoff_utc.hour == 20

    def test_the_game_date_agrees_with_the_schedule_endpoint(self) -> None:
        """Two endpoints, one game, one date. The disagreement is the bug."""
        summary_game, _ = parse_box_score_summary_v3(load("nba_boxscoresummaryv3_0022400306.json"))
        assert summary_game is not None
        games = {
            g.nba_game_id: g
            for g in parse_league_game_finder(
                load("nba_leaguegamefinder_trimmed.json"), season="2024-25"
            )
        }
        scheduled = games.get(summary_game.nba_game_id)
        assert scheduled is not None
        assert scheduled.game_date == summary_game.game_date

    def test_repeated_canonical_matchup_orientation_agrees_with_summary(self) -> None:
        games = {
            game.nba_game_id: game
            for game in parse_league_game_finder(
                load("nba_leaguegamefinder_reconciliation.json"), season="2024-25"
            )
        }
        summary_game, _ = parse_box_score_summary_v3(
            load("nba_boxscoresummaryv3_0022400633_reconciliation.json")
        )

        assert summary_game is not None
        scheduled = games[summary_game.nba_game_id]
        assert scheduled.home_team_id == summary_game.home_team_id
        assert scheduled.away_team_id == summary_game.away_team_id

    def test_a_payload_without_the_v3_body_is_a_contract_error(self) -> None:
        with pytest.raises(SourceContractError):
            parse_box_score_traditional_v3({"meta": {}})
        with pytest.raises(SourceContractError):
            parse_box_score_summary_v3({"meta": {}})


# ==========================================================================
# The fixtures themselves
# ==========================================================================


class TestNbaFixtureRecording:
    def test_league_game_finder_boundary_keeps_only_complete_game_groups(self) -> None:
        payload = load("nba_leaguegamefinder_reconciliation.json")

        game_ids = _league_game_finder_fixture_ids(
            payload,
            boundary_rows=3,
            required_game_ids=(),
        )
        selected, original = _select_league_game_finder_games(payload, game_ids)

        assert game_ids == ["0022400633"]
        assert original == {"LeagueGameFinderResults": 4}
        assert len(selected["resultSets"][0]["rowSet"]) == 2

    def test_required_cross_endpoint_game_is_added_as_a_complete_group(self) -> None:
        payload = load("nba_leaguegamefinder_reconciliation.json")

        game_ids = _league_game_finder_fixture_ids(
            payload,
            boundary_rows=2,
            required_game_ids=("0022401188",),
        )
        selected, _original = _select_league_game_finder_games(payload, game_ids)

        assert game_ids == ["0022400633", "0022401188"]
        assert len(selected["resultSets"][0]["rowSet"]) == 4


class TestFixtureManifest:
    def test_every_fixture_is_described_in_the_manifest(self, manifest: dict[str, Any]) -> None:
        on_disk = {p.name for p in list(FIXTURES.glob("*.json")) + list(FIXTURES.glob("*.pdf"))} - {
            "manifest.json"
        }
        assert on_disk == set(manifest), (
            "every fixture must record where it came from and when; an undocumented "
            "fixture cannot be refreshed deliberately"
        )

    def test_every_manifest_entry_names_its_source_and_endpoint(
        self, manifest: dict[str, Any]
    ) -> None:
        for name, entry in manifest.items():
            assert entry.get("source"), name
            assert entry.get("endpoint"), name
            assert entry.get("captured_at"), name

    def test_a_trimmed_fixture_records_what_was_removed(self, manifest: dict[str, Any]) -> None:
        """Trimming removes whole rows and never edits a value.

        A fixture that had been quietly edited would be a hand-written mock
        wearing a recording's clothes, which is exactly what ADR-006 rejects.
        """
        for name, entry in manifest.items():
            if entry.get("trimmed"):
                assert entry.get("original_row_counts"), name
                assert entry.get("kept_rows_per_result_set"), name

    def test_the_trimmed_fixtures_came_from_full_size_payloads(
        self, manifest: dict[str, Any]
    ) -> None:
        """The real scale is asserted here even though the fixture is smaller."""
        logs = manifest["nba_playergamelogs_trimmed.json"]
        assert logs["original_row_counts"]["PlayerGameLogs"] > 20000, (
            "a season of player game logs is tens of thousands of rows; a much "
            "smaller number means the request stopped returning a whole season"
        )
