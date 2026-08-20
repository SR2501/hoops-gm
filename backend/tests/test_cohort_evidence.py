"""Adapter gate: the cohort's cross-source game-identity reconciliation, offline.

The representative historical injury cohort was published once, in PR #30, over
a game-identity set that was silently short by two games. Nothing failed. The
parser was clean, the counts were plausible, and the manifest asserted them. It
took an independent endpoint reporting 1,230 games where the schedule parser had
produced 1,225 to find it.

These tests pin the mechanism that makes that class of defect loud instead of
silent: three mutually independent views of the same window, each deriving the
game-identity set from its own source and its own date field, required to be
*equal*. They run against recorded fixtures containing whole real rows for six
named games — one before the window, the window's first date, the two
neutral-site 2025-12-13 games the defective parser dropped, the window's last
date, and one after it.

Boundary games are in the fixtures on purpose. A windowing bug is invisible in a
fixture whose every game sits comfortably inside the window.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from hoops_gm.ingest.injury_report.cohort_evidence import (
    RECONCILIATION_VIEWS,
    VIEW_INDEPENDENCE,
    GameIdentityReconciliation,
    _league_game_finder_ids,
    _player_game_log_ids,
    _schedule_league_ids,
    content_sha256,
    refusal_reason,
    source_file_sha256,
)
from hoops_gm.ingest.nba import parse_league_game_finder

pytestmark = pytest.mark.adapter_contract

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPO_ROOT / "docs" / "adapters" / "nba-injury-report-cohort-2025-12-08--2026-01-04.json"
)

SEASON = "2025-26"
START = date(2025, 12, 8)
END = date(2026, 1, 4)

#: The four games the window contains, of the six each fixture holds.
IN_WINDOW = ("0022500364", "0022500494", "0022501229", "0022501230")
#: The two it does not. Present in every fixture so a view that ignores its own
#: date field fails here rather than in a season's worth of evidence.
OUT_OF_WINDOW = ("0022500357", "0022500502")


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _parse_cohort_league_game_finder(payload: Any) -> Any:
    return parse_league_game_finder(payload, season=SEASON, season_type="regular")


@pytest.fixture
def league_game_finder() -> Any:
    return load("nba_leaguegamefinder_cohort_window_2025_26.json")


@pytest.fixture
def player_game_logs() -> Any:
    return load("nba_playergamelogs_cohort_window_2025_26.json")


@pytest.fixture
def schedule_league() -> Any:
    return load("nba_scheduleleaguev2_cohort_window_2025_26.json")


@pytest.fixture(scope="module")
def manifest() -> Any:
    """The committed cohort manifest.

    Module-scoped and defined at module level rather than as a class-scoped
    instance method: pytest deprecates the latter, and this repository turns
    warnings into failures, so the deprecated form fails in CI while passing on
    an older local pytest.
    """
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


class TestEachViewWindowsItself:
    def test_league_game_finder_selects_only_in_window_games(self, league_game_finder: Any) -> None:
        assert (
            _league_game_finder_ids(league_game_finder, season=SEASON, start=START, end=END)
            == IN_WINDOW
        )

    def test_player_game_logs_window_comes_from_its_own_game_date(
        self, player_game_logs: Any
    ) -> None:
        """FAILS IF: ``PlayerGameLogs`` stopped carrying ``GAME_DATE``.

        This view is only an independent witness because it applies the window
        using a column the schedule query never supplied. Losing that column
        would silently reduce the reconciliation to one source agreeing with
        itself.
        """
        assert _player_game_log_ids(player_game_logs, start=START, end=END) == IN_WINDOW

    def test_schedule_league_v2_selects_only_in_window_games(self, schedule_league: Any) -> None:
        assert (
            _schedule_league_ids(schedule_league, season=SEASON, start=START, end=END) == IN_WINDOW
        )

    @pytest.mark.parametrize("excluded", OUT_OF_WINDOW)
    def test_no_view_admits_an_out_of_window_game(
        self,
        excluded: str,
        league_game_finder: Any,
        player_game_logs: Any,
        schedule_league: Any,
    ) -> None:
        assert excluded not in _league_game_finder_ids(
            league_game_finder, season=SEASON, start=START, end=END
        )
        assert excluded not in _player_game_log_ids(player_game_logs, start=START, end=END)
        assert excluded not in _schedule_league_ids(
            schedule_league, season=SEASON, start=START, end=END
        )


class TestTheGamesTheInvalidatedCohortDropped:
    def test_both_2025_12_13_games_survive_every_view(
        self, league_game_finder: Any, player_game_logs: Any, schedule_league: Any
    ) -> None:
        """FAILS IF: the parser drops a repeated-canonical-MATCHUP game again.

        ``0022501229`` and ``0022501230`` are the only two games played on
        2025-12-13, so dropping them removed an entire game date from the
        invalidated cohort — 171 games across 25 dates instead of 173 across 26.
        """
        for ids in (
            _league_game_finder_ids(league_game_finder, season=SEASON, start=START, end=END),
            _player_game_log_ids(player_game_logs, start=START, end=END),
            _schedule_league_ids(schedule_league, season=SEASON, start=START, end=END),
        ):
            assert "0022501229" in ids
            assert "0022501230" in ids

    def test_both_rows_of_each_dropped_game_repeat_one_canonical_matchup(
        self, league_game_finder: Any
    ) -> None:
        """The defect's actual mechanism, asserted against the real captured rows.

        An ordinary game's two rows are reciprocal — ``"SAC @ IND"`` and
        ``"IND vs. SAC"`` — so the separator alone identifies which side a row
        describes. These two neutral-site games repeat one string on both rows,
        which is why side had to be resolved by team abbreviation instead.
        """
        table = league_game_finder["resultSets"][0]
        headers = table["headers"]
        game_id = headers.index("GAME_ID")
        matchup = headers.index("MATCHUP")
        abbreviation = headers.index("TEAM_ABBREVIATION")

        for target, expected in (("0022501229", "NYK @ ORL"), ("0022501230", "SAS @ OKC")):
            rows = [row for row in table["rowSet"] if row[game_id] == target]
            assert len(rows) == 2
            assert {row[matchup] for row in rows} == {expected}
            assert len({row[abbreviation] for row in rows}) == 2

        ordinary = [row for row in table["rowSet"] if row[game_id] == "0022500364"]
        assert len({row[matchup] for row in ordinary}) == 2

    def test_both_neutral_site_games_resolve_to_the_right_home_and_away(self) -> None:
        """The correctness invariant, offline, where it can block a merge.

        The cross-endpoint fact that the repeated-``MATCHUP`` class *is* the
        schedule's ``isNeutral`` class is a drift detector and lives in
        ``test_live_smoke.py``. What belongs here is the invariant a merge must
        not break: a game whose two rows repeat one string still resolves to the
        correct sides, by team abbreviation rather than by separator.

        The expected orientation is taken from the committed ``ScheduleLeagueV2``
        fixture rather than restated by hand, so this asserts agreement between
        two independently recorded endpoints instead of agreement with a number
        someone typed.
        """
        parsed = {
            game.nba_game_id: game
            for game in _parse_cohort_league_game_finder(
                load("nba_leaguegamefinder_cohort_window_2025_26.json")
            )
        }
        schedule = load("nba_scheduleleaguev2_cohort_window_2025_26.json")
        expected = {
            str(game["gameId"]): (game["homeTeam"]["teamId"], game["awayTeam"]["teamId"])
            for entry in schedule["leagueSchedule"]["gameDates"]
            for game in entry.get("games") or ()
        }

        for game_id in ("0022501229", "0022501230"):
            home, away = expected[game_id]
            assert parsed[game_id].home_team_id == home
            assert parsed[game_id].away_team_id == away
            assert parsed[game_id].home_team_id != parsed[game_id].away_team_id


class TestReconciliationRefusesToPassOnAgreementItDoesNotHave:
    def _views(self, **overrides: tuple[str, ...]) -> GameIdentityReconciliation:
        views: dict[str, tuple[str, ...]] = {
            "league_game_finder": IN_WINDOW,
            "persisted_nba_games": IN_WINDOW,
            "player_game_logs": IN_WINDOW,
            "schedule_league_v2": IN_WINDOW,
        }
        views.update(overrides)
        return GameIdentityReconciliation(start=START, end=END, views=views)

    def test_equal_views_agree_and_fingerprint_their_union(self) -> None:
        reconciliation = self._views()

        assert reconciliation.agreed
        assert reconciliation.disagreements() == {}
        assert reconciliation.union == IN_WINDOW
        assert reconciliation.as_summary()["sha256_sorted_game_ids"] == content_sha256(IN_WINDOW)

    def test_a_short_view_is_named_rather_than_reduced_to_a_count(self) -> None:
        """Exactly the invalidated cohort's shape: one view short by the 12-13 pair."""
        reconciliation = self._views(
            league_game_finder=("0022500364", "0022500494"),
            persisted_nba_games=("0022500364", "0022500494"),
        )

        assert not reconciliation.agreed
        assert reconciliation.disagreements() == {
            "league_game_finder": ["0022501229", "0022501230"],
            "persisted_nba_games": ["0022501229", "0022501230"],
        }
        # The union, not any one view, is what the summary fingerprints, so a
        # missing game changes the identity rather than shrinking quietly.
        assert reconciliation.union == IN_WINDOW

    def test_an_extra_game_in_one_view_is_a_disagreement_too(self) -> None:
        reconciliation = self._views(player_game_logs=(*IN_WINDOW, "0022500502"))

        assert not reconciliation.agreed
        assert reconciliation.disagreements() == {
            "league_game_finder": ["0022500502"],
            "persisted_nba_games": ["0022500502"],
            "schedule_league_v2": ["0022500502"],
        }

    def test_a_single_view_agrees_with_itself_which_is_not_corroboration(self) -> None:
        """Documents the permissive branch, and is named for what it asserts.

        Independent review pointed out that this test was previously called
        ``test_agreement_among_fewer_views_is_not_the_same_claim`` while
        asserting ``agreed is True`` — a protective-sounding name over the
        permissive behaviour. ``agreed`` genuinely is True for one view, because
        one set trivially equals itself. The protection lives in
        :func:`refusal_reason`, which is where it is now tested.
        """
        reconciliation = GameIdentityReconciliation(
            start=START, end=END, views={"persisted_nba_games": IN_WINDOW}
        )

        assert reconciliation.agreed
        assert set(reconciliation.as_summary()["counts"]) == {"persisted_nba_games"}

    def test_four_views_that_all_found_nothing_agree_but_witness_nothing(self) -> None:
        """FAILS IF: an empty window can be published as four-source agreement.

        Found by independent review. A mistyped window, or a raw store whose
        captures predate the requested range, makes every view empty. They then
        agree perfectly — over zero games. ``witnessed`` is the separate
        question the CLI checks, so this cannot exit 0 with a manifest claiming
        agreement across four sources.
        """
        reconciliation = self._views(
            league_game_finder=(),
            persisted_nba_games=(),
            player_game_logs=(),
            schedule_league_v2=(),
        )

        assert reconciliation.agreed
        assert not reconciliation.witnessed
        assert reconciliation.union == ()

    def test_a_populated_reconciliation_is_witnessed(self) -> None:
        assert self._views().witnessed


class TestTheRefusalPathIsExercised:
    """The guard the docs advertise as the safety property, actually run.

    ``main`` carries ``# pragma: no cover`` because it is an operator tool, and
    independent review noted that this left the exit-1 refusal — cited in the
    module docstring, in ``docs/adapters/nba-stats.md`` and in the handoff as
    the thing that stops a bad cohort being published — completely unexercised.
    :func:`refusal_reason` exists so it is not.
    """

    def _views(self, **overrides: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
        views: dict[str, tuple[str, ...]] = dict.fromkeys(RECONCILIATION_VIEWS, IN_WINDOW)
        views.update(overrides)
        return views

    def test_a_complete_agreeing_populated_reconciliation_is_publishable(self) -> None:
        assert (
            refusal_reason(GameIdentityReconciliation(start=START, end=END, views=self._views()))
            is None
        )

    def test_a_missing_view_is_refused_and_named(self) -> None:
        views = self._views()
        del views["schedule_league_v2"]

        reason = refusal_reason(GameIdentityReconciliation(start=START, end=END, views=views))

        assert reason is not None
        assert "schedule_league_v2" in reason
        assert "--allow-fetch" in reason

    def test_a_disagreement_is_refused_and_the_game_ids_are_named(self) -> None:
        reason = refusal_reason(
            GameIdentityReconciliation(
                start=START,
                end=END,
                views=self._views(schedule_league_v2=("0022500364", "0022500494")),
            )
        )

        assert reason is not None
        assert "0022501229" in reason
        assert "0022501230" in reason

    def test_four_agreeing_but_empty_views_are_refused(self) -> None:
        """The case that previously published a manifest over zero games with exit 0."""
        reason = refusal_reason(
            GameIdentityReconciliation(
                start=START, end=END, views=dict.fromkeys(RECONCILIATION_VIEWS, ())
            )
        )

        assert reason is not None
        assert "zero games" in reason


class TestTheIndependenceMapIsCheckableRatherThanTrusted:
    """Four agreeing views are not four independent witnesses, and it must say so.

    An earlier revision claimed each view derived "from its own source". Two do
    not: ``persisted_nba_games`` is the same ``LeagueGameFinder`` bytes through
    the same parser, and ``player_game_logs`` was already required equal to
    ``LeagueGameFinder`` at season scope before any row was written. Caught by
    independent review after the claim had already been repeated upstream.
    """

    def test_every_required_view_declares_its_independence(self) -> None:
        assert set(VIEW_INDEPENDENCE) == set(RECONCILIATION_VIEWS)

    def test_the_two_dependent_views_say_so_explicitly(self) -> None:
        assert "NOT source-independent" in VIEW_INDEPENDENCE["persisted_nba_games"]
        assert "guaranteed by construction" in VIEW_INDEPENDENCE["player_game_logs"]

    def test_the_manifest_publishes_the_map(self, manifest: Any) -> None:
        published = manifest["cross_source_reconciliation"]["independence"]
        assert set(published) == set(RECONCILIATION_VIEWS)
        assert published == VIEW_INDEPENDENCE


class TestPositionEvidenceReportsTheSourceRatherThanADistribution:
    """The label is a starting-lineup slot, and the manifest must say so.

    The invalidated cohort published a G/F/C distribution over
    ``BoxScoreTraditionalV3``'s ``position`` field as evidence of positional
    diversity. The endpoint emits that field for exactly five players per team —
    the starters — always as ``F,F,C,G,G``, so the distribution is forced to
    2F:2G:1C for any cohort and establishes nothing. Worse for an injury cohort:
    the players least likely to have started are exactly the injured ones, so
    "no label" was systematically the population of interest.
    """

    def test_the_manifest_does_not_claim_positional_diversity(self, manifest: Any) -> None:
        position = manifest["position_evidence"]
        assert position["positional_diversity_established"] is False
        assert "distinct_resolved_players_by_observed_label" not in position

    def test_exactly_five_players_per_team_carry_a_label(self, manifest: Any) -> None:
        """FAILS IF: the source starts labelling every player.

        That would be good news and would make real positional evidence
        possible — but it must be noticed and acted on, not absorbed.
        """
        assert list(manifest["position_evidence"]["labelled_players_per_team"]) == ["5"]

    def test_the_only_observed_sequence_is_the_starting_five(self, manifest: Any) -> None:
        assert list(manifest["position_evidence"]["distinct_label_sequences"]) == ["F,F,C,G,G"]

    def test_missing_captures_are_named_rather_than_silently_shrinking_the_denominator(
        self, manifest: Any
    ) -> None:
        """The raw store is prunable, so an absent capture must not look like a finding."""
        position = manifest["position_evidence"]
        assert position["games_without_box_score_capture"] == []
        assert position["games_with_box_score_capture"] == manifest["scope"]["games_with_tipoff"]


class TestTheCommittedManifestStillDescribesThisCode:
    """A fingerprint nobody checks is a comment.

    The manifest records the SHA-256 of every repository file the cohort's
    derivation depends on, including the generator itself. Editing one of those
    files without regenerating leaves a manifest that describes code which no
    longer exists — a stale provenance claim, which is worse than none, because
    it looks checked.
    """

    def test_every_recorded_source_fingerprint_matches_the_file_today(self, manifest: Any) -> None:
        fingerprints = manifest["operator"]["source_fingerprints"]
        assert fingerprints, "the manifest records no source fingerprints at all"
        stale = {
            relative: (recorded, source_file_sha256(REPO_ROOT / relative))
            for relative, recorded in sorted(fingerprints.items())
            if source_file_sha256(REPO_ROOT / relative) != recorded
        }
        assert not stale, (
            "the committed cohort manifest fingerprints code that has since changed: "
            f"{stale}. Regenerate it with the commands in its own operator.commands, or "
            "the provenance it publishes is a claim about a file that no longer exists."
        )

    def test_the_manifest_agrees_with_itself_about_the_cohort_scope(self, manifest: Any) -> None:
        """The three places the game count appears must not be able to drift apart."""
        reconciliation = manifest["cross_source_reconciliation"]

        assert reconciliation["agreed"] is True
        assert reconciliation["disagreements"] == {}
        assert set(reconciliation["counts"]) == {
            "league_game_finder",
            "persisted_nba_games",
            "player_game_logs",
            "schedule_league_v2",
        }
        assert len(reconciliation["game_ids"]) == manifest["scope"]["games_in_scope"]
        assert manifest["scope"]["expected_games"] == manifest["scope"]["games_in_scope"]
        assert set(reconciliation["counts"].values()) == {manifest["scope"]["games_in_scope"]}
        for game_id in ("0022501229", "0022501230"):
            assert game_id in reconciliation["game_ids"], (
                f"{game_id} is missing from the committed cohort — this is the exact "
                "omission that invalidated the previous one"
            )


class TestSourceFingerprintsAreCheckoutIndependent:
    def test_crlf_and_lf_bytes_hash_identically(self, tmp_path: Path) -> None:
        """FAILS IF: a fingerprint starts depending on the checkout's line endings.

        PR #30 published working-tree hashes taken on a Windows checkout with
        ``core.autocrlf=true``. They were reproducible on that one machine and
        nowhere else, and had to be corrected after publication.
        """
        lf = tmp_path / "lf.py"
        crlf = tmp_path / "crlf.py"
        lf.write_bytes(b"one\ntwo\nthree\n")
        crlf.write_bytes(b"one\r\ntwo\r\nthree\r\n")

        assert source_file_sha256(lf) == source_file_sha256(crlf)
