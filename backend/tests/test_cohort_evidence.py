"""Adapter gate: the cohort's cross-source game-identity reconciliation, offline.

The representative historical injury cohort was published once, in PR #30, over
a game-identity set that was silently short by two games. Nothing failed. The
parser was clean, the counts were plausible, and the manifest asserted them. It
took an independent endpoint reporting 1,230 games where the schedule parser had
produced 1,225 to find it.

These tests pin the mechanism that makes that class of defect loud instead of
silent: four views of the same window, required to be equal **as sets, not as
counts** — a count check passes a window that is the right size and the wrong
membership. They run against recorded fixtures containing whole real rows for
six named games — one before the window, the window's first date, the two
neutral-site 2025-12-13 games the defective parser dropped, the window's last
date, and one after it.

**They are not four independent witnesses**, and saying so was the second
meaning-level error independent review caught here. ``persisted_nba_games`` is
the same ``LeagueGameFinder`` bytes through the same parser; ``player_game_logs``
was already required equal to ``LeagueGameFinder`` at season scope before any row
was written, so only its *windowing* is independent. See ``VIEW_INDEPENDENCE``,
and :class:`TestTheIndependenceMapIsCheckableRatherThanTrusted` below.

Boundary games are in the fixtures on purpose. A windowing bug is invisible in a
fixture whose every game sits comfortably inside the window.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hoops_gm.ingest.injury_report import parse_injury_report_pdf
from hoops_gm.ingest.injury_report.cohort_evidence import (
    RECONCILIATION_VIEWS,
    VIEW_INDEPENDENCE,
    GameIdentityReconciliation,
    TipoffReconciliation,
    _league_game_finder_ids,
    _player_game_log_ids,
    _reason_evidence,
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

#: The report uses a closed vocabulary for the category it prints before its own
#: separator; eleven distinct values appear across all 9,376 raw entries in this
#: window. A separator change would turn every distinct reason *line* into its
#: own "category", so a cardinality bound catches the drift that a length bound
#: cannot — the longest real category (36 chars) is longer than some whole
#: reason lines (35).
_MAX_PLAUSIBLE_REASON_CATEGORIES = 20

#: Observed across all 9,376 raw entries in the 2025-12-08..2026-01-04 window,
#: plus ``Team Suspension``, which appears in the recorded 2025-11-01 report and
#: **not** in the cohort window at all. That addition was not researched — the
#: source-watching test below found it on its first run, which is both the
#: alarm working and a warning that a vocabulary derived from 28 days is not the
#: source's vocabulary. An unrecognised value is either real NBA news or
#: separator drift, and both are worth stopping for.
_KNOWN_REASON_CATEGORIES = frozenset(
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


class TestTipoffDisagreementBlocksPublication:
    """The instants, guarded like the identities.

    The tip-off comparison shipped a round after the identity reconciliation and
    initially only *reported* — a disagreement about when every game started
    published with exit 0, and zero instants compared reported ``agreed: true``.
    That is the agreed-versus-witnessed defect the identity reconciliation had
    already been corrected for, reintroduced in the same commit that documented
    why it was wrong. Independent review caught it.
    """

    def _identity(self) -> GameIdentityReconciliation:
        return GameIdentityReconciliation(
            start=START, end=END, views=dict.fromkeys(RECONCILIATION_VIEWS, IN_WINDOW)
        )

    def test_agreeing_compared_instants_publish(self) -> None:
        tipoffs = TipoffReconciliation(compared=173, absent=(), disagreements={})

        assert tipoffs.agreed and tipoffs.witnessed
        assert refusal_reason(self._identity(), tipoffs) is None

    def test_a_disagreement_is_refused_and_both_instants_are_named(self) -> None:
        tipoffs = TipoffReconciliation(
            compared=173,
            absent=(),
            disagreements={
                "0022501230": {
                    "box_score_summary_v3": "2025-12-14T02:00:00+00:00",
                    "schedule_league_v2": "2025-12-14T02:30:00+00:00",
                }
            },
        )

        reason = refusal_reason(self._identity(), tipoffs)

        assert reason is not None
        assert "0022501230" in reason
        assert "02:30:00" in reason

    def test_zero_compared_instants_agree_but_witness_nothing(self) -> None:
        tipoffs = TipoffReconciliation(
            compared=0, absent=("0022501229", "0022501230"), disagreements={}
        )

        assert tipoffs.agreed
        assert not tipoffs.witnessed
        reason = refusal_reason(self._identity(), tipoffs)
        assert reason is not None
        assert "zero tip-off instants" in reason

    def test_an_unavailable_schedule_capture_is_refused_rather_than_skipped(self) -> None:
        tipoffs = TipoffReconciliation(
            compared=0,
            absent=(),
            disagreements={},
            checked=False,
            unavailable_reason="no ScheduleLeagueV2 capture retained",
        )

        reason = refusal_reason(self._identity(), tipoffs)

        assert reason is not None
        assert "could not be reconciled" in reason

    def test_the_committed_manifest_reports_a_witnessed_agreement(self, manifest: Any) -> None:
        section = manifest["cross_source_tipoff_reconciliation"]

        assert section["checked"] is True
        assert section["agreed"] is True
        assert section["witnessed"] is True
        assert section["disagreements"] == {}
        assert section["games_compared"] == manifest["scope"]["games_with_tipoff"]


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
        """What the published artifact records. **Not a drift alarm.**

        This reads a static committed file, so it cannot notice the endpoint
        changing — regenerating the manifest needs gitignored operational state.
        The alarm that watches the source lives in
        :class:`TestThePositionFieldIsWatchedAtTheSourceNotOnlyInTheManifest`
        and in ``test_live_smoke.py``. Independent review caught this test
        claiming otherwise.
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


class TestThePositionFieldIsWatchedAtTheSourceNotOnlyInTheManifest:
    """The alarm, pointed at something that can actually change.

    The manifest-reading tests above assert what the *published artifact* says.
    They cannot detect a change in the endpoint, because regenerating the
    manifest needs gitignored operational state only the operator has — so if
    ``BoxScoreTraditionalV3`` started labelling every player tomorrow, those
    tests would stay green forever while the manifest kept publishing
    ``positional_diversity_established: false`` as current source behaviour.

    Independent review caught that the round which added
    "must be noticed and acted on, not absorbed" had shipped an alarm wired to
    the wrong thing — the same class as ``refusal_reason`` being untested and a
    fingerprint nobody checks. These assertions run against the committed
    box-score fixtures instead, and the live counterpart is in
    ``test_live_smoke.py``.
    """

    @pytest.mark.parametrize(
        "fixture",
        [
            "nba_boxscoretraditionalv3_0022400306.json",
            "nba_boxscoretraditionalv3_0022500560_midseason.json",
        ],
    )
    def test_only_the_five_starters_carry_a_position_in_a_recorded_box_score(
        self, fixture: str
    ) -> None:
        """FAILS IF: the recorded evidence stops supporting the withdrawal.

        Every team-side in a real captured box score labels exactly five
        players, and always the same slot sequence. That is what makes the
        field a lineup slot rather than a player attribute, and it is the whole
        basis for withdrawing the positional-diversity claim.
        """
        body = load(fixture)["boxScoreTraditional"]

        for side in ("homeTeam", "awayTeam"):
            players = body[side]["players"]
            labelled = [str(p.get("position") or "").strip() for p in players]
            non_blank = [label for label in labelled if label]

            assert len(players) > 5, "a fixture with no bench cannot show the asymmetry"
            assert len(non_blank) == 5, (
                f"{fixture} {side} labels {len(non_blank)} players, not 5. If the source now "
                "labels everyone, real positional evidence became possible and the withdrawal "
                "in position_evidence should be revisited rather than left standing."
            )
            assert non_blank == ["F", "F", "C", "G", "G"]


class TestTheReasonParseIsPinned:
    """The only new parse of raw source text in this change, tested.

    Independent review found ``_reason_evidence`` had no test at all — no
    fixture, no unit, nothing in the manifest assertions. It splits on the
    report's own ``" - "`` separator and publishes the result as evidence, so if
    the NBA switched to an en dash or ``": "`` the categories would silently
    collapse into ten full sentences and the manifest would publish them with a
    green suite. That is drift producing a wrong number quietly, which is the
    failure this whole change exists to prevent.
    """

    def _observation(self, reason: str) -> Any:
        return SimpleNamespace(reason_raw=reason)

    def test_the_source_separator_splits_category_from_detail(self) -> None:
        evidence = _reason_evidence(
            [
                self._observation("G League - Two-Way"),
                self._observation("G League - Two-Way"),
                self._observation("G League - On Assignment"),
                self._observation("Injury/Illness - Left Ankle; Sprain"),
            ]
        )

        assert evidence["stated_reason_categories"] == {"G League": 3, "Injury/Illness": 1}
        assert evidence["stated_reason_subcategories"]["G League"] == {
            "On Assignment": 1,
            "Two-Way": 2,
        }

    def test_two_way_and_on_assignment_are_not_collapsed(self) -> None:
        """The distinction whose loss made a published number wrong.

        A two-way contract and a standard-contract player sent down are
        different roster facts. Collapsing them let a handoff entry call the
        whole G League bucket "two-way", overstating it by 5.3 points of the
        cohort with no way for a reader to detect the error from the artifact.
        """
        evidence = _reason_evidence(
            [self._observation("G League - Two-Way")] * 455
            + [self._observation("G League - On Assignment")] * 104
        )

        assert evidence["stated_reason_categories"]["G League"] == 559
        assert evidence["stated_reason_subcategories"]["G League"] == {
            "On Assignment": 104,
            "Two-Way": 455,
        }

    def test_injury_detail_is_counted_but_never_enumerated(self) -> None:
        """Free clinical text stays out of a committed artifact."""
        evidence = _reason_evidence(
            [
                self._observation("Injury/Illness - Left Ankle; Sprain"),
                self._observation("Injury/Illness - Right Knee; Soreness"),
            ]
        )

        assert evidence["stated_reason_categories"]["Injury/Illness"] == 2
        assert "Injury/Illness" not in evidence["stated_reason_subcategories"]

    def test_the_reports_placeholder_is_distinguished_from_an_empty_string(self) -> None:
        """``-`` means "nothing to state"; an empty field means the column was absent."""
        evidence = _reason_evidence(
            [self._observation("-"), self._observation(""), self._observation("Rest")]
        )

        assert evidence["observations_with_placeholder_reason"] == 1
        assert evidence["observations_with_empty_reason_text"] == 1
        assert evidence["stated_reason_categories"] == {"-": 1, "Rest": 1}

    def test_a_laundered_reason_keeps_the_heading_the_source_chose(self) -> None:
        """``Rest - Left Knee Injury Management`` is a real observed row.

        The house rule says stated reasons are not to be trusted. This is that
        rule visible in the data: the source itself files injury management
        under Rest. The parse must not "helpfully" reclassify it.
        """
        evidence = _reason_evidence([self._observation("Rest - Left Knee Injury Management")])

        assert evidence["stated_reason_categories"] == {"Rest": 1}
        assert evidence["stated_reason_subcategories"]["Rest"] == {"Left Knee Injury Management": 1}

    def test_a_changed_separator_would_be_visible_rather_than_silent(self) -> None:
        """FAILS IF: the guard below stops discriminating.

        Length is *not* a usable discriminator, which is worth recording
        because it was my first attempt and it failed: the longest real category
        ("Return to Competition Reconditioning", 36 characters) is longer than a
        whole reason line such as "Injury/Illness - Left Ankle; Sprain" (35).
        The two ranges overlap, so a length bound cannot tell them apart.

        Cardinality discriminates by an order of magnitude. The report uses a
        closed vocabulary of about ten categories, while the tail is free text
        with 253 distinct values in this window alone. If the separator changed,
        every distinct line would become its own "category".
        """
        broken = _reason_evidence(
            [
                self._observation(f"Injury/Illness \u2013 Ailment {n}")
                for n in range(_MAX_PLAUSIBLE_REASON_CATEGORIES + 5)
            ]
        )

        assert len(broken["stated_reason_categories"]) > _MAX_PLAUSIBLE_REASON_CATEGORIES

    def test_the_committed_manifest_categories_still_look_like_categories(
        self, manifest: Any
    ) -> None:
        """What the published artifact records. **Not a drift alarm.**

        This reads a static committed file, so it cannot notice the NBA
        changing its separator — regenerating the manifest needs gitignored
        operational state. The alarms that watch the source are
        :class:`TestTheReasonVocabularyIsWatchedAtTheSource` below, against the
        recorded PDF, and its live counterpart in ``test_live_smoke.py``.
        Independent review caught this test's failure messages claiming
        otherwise.
        """
        published = manifest["reason_evidence"]["stated_reason_categories"]

        assert published, "the manifest publishes no reason categories at all"
        assert len(published) <= _MAX_PLAUSIBLE_REASON_CATEGORIES
        assert set(published) <= _KNOWN_REASON_CATEGORIES
        assert published["Injury/Illness"] > published["G League"] > 0

    def test_subcategory_counts_sum_to_their_category(self, manifest: Any) -> None:
        """A published breakdown that does not add up is a second wrong number."""
        reason = manifest["reason_evidence"]
        for head, details in reason["stated_reason_subcategories"].items():
            assert sum(details.values()) == reason["stated_reason_categories"][head], (
                f"{head} sub-counts sum to {sum(details.values())} but the category is "
                f"{reason['stated_reason_categories'][head]}. Bare rows with no detail must be "
                "bucketed, not dropped."
            )


class TestTheReasonVocabularyIsWatchedAtTheSource:
    """The reason guard, pointed at bytes the NBA produced.

    The manifest test above reads a static artifact and cannot go red on a
    separator change. This one parses the committed injury-report PDF — a real
    capture — and applies the same vocabulary bound to what the parser actually
    extracts. The live counterpart in ``test_live_smoke.py`` is the half that
    can detect tomorrow's change; this half detects a regression in our own
    parsing of yesterday's.

    Independent review caught the gap by noting that an en-dash switch would be
    caught by nothing: not the live smoke, not an offline fixture test, and not
    the manifest test.
    """

    def test_the_recorded_report_yields_only_known_reason_categories(self) -> None:
        pdf = (FIXTURES / "nba_injury_report_2025-11-01_0530pm.pdf").read_bytes()
        result = parse_injury_report_pdf(
            pdf,
            report_timestamp=datetime(2025, 11, 1, 21, 30, tzinfo=UTC),
            source_url="https://ak-static.cms.nba.com/referee/injury/"
            "Injury-Report_2025-11-01_05PM.pdf",
        )

        heads = {
            entry.reason_raw.strip().split(" - ", 1)[0].strip()
            for entry in result.entries
            if entry.reason_raw.strip()
        }

        assert heads, "the recorded report parsed no reasons at all"
        assert heads <= _KNOWN_REASON_CATEGORIES, (
            f"the recorded report yields unrecognised reason categories: "
            f"{sorted(heads - _KNOWN_REASON_CATEGORIES)}. Either our parsing of the ' - ' "
            "separator regressed, or the recorded fixture was refreshed against a changed "
            "source without updating the vocabulary."
        )
        assert len(heads) <= _MAX_PLAUSIBLE_REASON_CATEGORIES


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
