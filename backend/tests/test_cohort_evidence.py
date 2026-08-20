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
    GameIdentityReconciliation,
    _league_game_finder_ids,
    _player_game_log_ids,
    _schedule_league_ids,
    content_sha256,
    source_file_sha256,
)

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


@pytest.fixture
def league_game_finder() -> Any:
    return load("nba_leaguegamefinder_cohort_window_2025_26.json")


@pytest.fixture
def player_game_logs() -> Any:
    return load("nba_playergamelogs_cohort_window_2025_26.json")


@pytest.fixture
def schedule_league() -> Any:
    return load("nba_scheduleleaguev2_cohort_window_2025_26.json")


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

    def test_agreement_among_fewer_views_is_not_the_same_claim(self) -> None:
        """An absent witness must not be counted as a corroborating one."""
        reconciliation = GameIdentityReconciliation(
            start=START, end=END, views={"persisted_nba_games": IN_WINDOW}
        )

        assert reconciliation.agreed
        assert set(reconciliation.as_summary()["counts"]) == {"persisted_nba_games"}


class TestTheCommittedManifestStillDescribesThisCode:
    """A fingerprint nobody checks is a comment.

    The manifest records the SHA-256 of every repository file the cohort's
    derivation depends on, including the generator itself. Editing one of those
    files without regenerating leaves a manifest that describes code which no
    longer exists — a stale provenance claim, which is worse than none, because
    it looks checked.
    """

    @pytest.fixture(scope="class")
    def manifest(self) -> Any:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

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
