"""The command that makes a backfilled store able to serve reliability evidence.

**The precondition is built the way the backfill leaves it, deliberately.**
``hoops_gm.ingest.backfill`` writes ``nba_games``, ``player_game_logs`` and
``player_participation`` and writes no ``team_schedule`` rows and no
``refresh_runs``. :func:`_backfilled_season` reproduces exactly that state — a
complete, correct season of observations that ``compute_reliability_scorecards``
cannot produce a single scorecard from. Building it here rather than through
``import_schedule`` is the point: routing the input through the schedule
importer would create the very rows whose absence is the thing under test.

The success path is then built entirely by production writers:
``publish_reliability_evidence`` calling ``import_schedule`` and
``publish_reliability_cohorts``. Nothing in this file writes a
``team_schedule`` row or a ``refresh_runs`` row itself.

**Why the season is full-size rather than a handful of games.** The refusal in
:func:`require_complete_regular_season` is the only thing standing between a
truncated ledger and a silently wrong ``is_back_to_back`` flag, and a suite
that only ever exercised four games would never distinguish "the derivation is
exact" from "the derivation happens to work here". 1,230 rows costs about a
second.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hoops_gm.availability import compute_reliability_scorecards
from hoops_gm.availability.reliability import (
    ReliabilityInputError,
    StaleReliabilityCohortError,
    _source_snapshot,
    publish_reliability_cohorts,
)
from hoops_gm.core.config import Settings
from hoops_gm.db.lineage import NBA_SCHEDULE_ARTIFACT_KEY, record_refresh
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
    RefreshArtifactType,
    RefreshRun,
    SeasonType,
    TeamScheduleEntry,
)
from hoops_gm.dev.publish_reliability_evidence import (
    DERIVED_SOURCE,
    REGULAR_SEASON_GAMES,
    REGULAR_SEASON_GAMES_PER_TEAM,
    REGULAR_SEASON_TEAMS,
    DerivationRefused,
    main,
    publish_reliability_evidence,
    require_complete_regular_season,
    schedule_from_played_games,
)
from hoops_gm.ingest.importers import SCHEDULE_REFRESH_SOURCE, import_schedule
from hoops_gm.ingest.nba.models import NbaGameRecord
from hoops_gm.ingest.nba.schedule import ScheduleGameRecord, ScheduleParseResult

SEASON = "2025-26"
OPENING_DAY = date(2025, 10, 21)
LAST_GAME_DAY = date.fromordinal(OPENING_DAY.toordinal() + REGULAR_SEASON_GAMES_PER_TEAM - 1)


def _teams(session: Session) -> list[NbaTeam]:
    teams = [
        NbaTeam(nba_team_id=1610612700 + index, abbreviation=f"T{index:02d}", name=f"Team {index}")
        for index in range(REGULAR_SEASON_TEAMS)
    ]
    session.add_all(teams)
    session.flush()
    return teams


def _round_robin(teams: list[NbaTeam], round_index: int) -> list[tuple[NbaTeam, NbaTeam]]:
    """One round of the circle method: every team paired exactly once.

    Each round giving every team exactly one game is what makes 82 rounds
    produce exactly 82 games per team, which is the condition
    :func:`require_complete_regular_season` checks against constants it did
    not derive from this data.
    """

    rotating = teams[1:]
    offset = round_index % len(rotating)
    order = [teams[0], *rotating[offset:], *rotating[:offset]]
    half = len(order) // 2
    pairs = list(zip(order[:half], list(reversed(order[half:])), strict=True))
    # Alternate orientation so no team is home in all 82 of its games.
    return [(b, a) if round_index % 2 else (a, b) for a, b in pairs]


def _backfilled_season(session: Session) -> None:
    """A store in the state a completed box-score backfill leaves it in."""

    teams = _teams(session)
    number = 0
    for round_index in range(REGULAR_SEASON_GAMES_PER_TEAM):
        game_date = date.fromordinal(OPENING_DAY.toordinal() + round_index)
        for home, away in _round_robin(teams, round_index):
            number += 1
            session.add(
                NbaGame(
                    season=SEASON,
                    season_type=SeasonType.REGULAR,
                    nba_game_id=f"00225{number:05d}",
                    game_date=game_date,
                    status=GameStatus.FINAL,
                    home_team_id=home.id,
                    away_team_id=away.id,
                    home_score=110,
                    away_score=100,
                    tipoff_utc=datetime(
                        game_date.year, game_date.month, game_date.day, 23, 30, tzinfo=UTC
                    ),
                )
            )
    session.flush()


def _observations(session: Session, *, games: int = 4) -> Player:
    """One player with real production and one recorded absence.

    ``_source_snapshot`` refuses a window holding no player game logs, so the
    ledger needs at least one; the absence is what makes the resulting
    scorecard say anything at all about availability.
    """

    player = Player(full_name="Observed Player", normalized_name="observedplayer")
    session.add(player)
    session.flush()
    rows = session.scalars(
        select(NbaGame).order_by(NbaGame.game_date, NbaGame.nba_game_id).limit(games)
    ).all()
    for index, game in enumerate(rows):
        if index == 0:
            session.add(
                PlayerParticipation(
                    player_id=player.id,
                    game_id=game.id,
                    team_id=game.home_team_id,
                    outcome=ParticipationOutcome.INACTIVE,
                    reason=DnpReason.NONE_GIVEN,
                    raw_comment="",
                    source=ExternalSource.NBA,
                    inactive_list_available=True,
                )
            )
            continue
        session.add(
            PlayerGameLog(
                player_id=player.id,
                game_id=game.id,
                team_id=game.home_team_id,
                seconds_played=1800 + index * 60,
                field_goals_made=5,
                field_goals_attempted=10,
                three_pointers_made=2,
                three_pointers_attempted=5,
                free_throws_made=4,
                free_throws_attempted=5,
                points=20,
                offensive_rebounds=1,
                defensive_rebounds=4,
                rebounds=5,
                assists=4,
                steals=1,
                blocks=1,
                turnovers=2,
                personal_fouls=2,
                plus_minus=0,
            )
        )
    session.flush()
    return player


def _rows(
    session: Session, model: type[NbaGame] | type[TeamScheduleEntry] | type[RefreshRun]
) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _scored_final_games(session: Session) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(NbaGame)
            .where(
                NbaGame.status == GameStatus.FINAL,
                NbaGame.home_score.is_not(None),
                NbaGame.away_score.is_not(None),
            )
        )
        or 0
    )


def test_a_backfilled_store_cannot_serve_reliability_until_this_command_runs(
    session: Session,
) -> None:
    """The whole reason the command exists, asserted from both sides."""

    _backfilled_season(session)
    player = _observations(session)

    assert _rows(session, NbaGame) == REGULAR_SEASON_GAMES
    assert _rows(session, TeamScheduleEntry) == 0
    assert _rows(session, RefreshRun) == 0

    result = publish_reliability_evidence(session, season=SEASON)

    assert result.games == REGULAR_SEASON_GAMES
    assert result.team_schedule_rows == REGULAR_SEASON_GAMES * 2
    assert result.claim.as_of_date == LAST_GAME_DAY
    assert result.claim.window_start == OPENING_DAY

    run = compute_reliability_scorecards(session, claim=result.claim)

    assert [card.player_id for card in run.scorecards] == [player.id]
    assert run.scorecards[0].availability.overall.direct_non_play == 1
    assert run.scorecards[0].availability.overall.direct_play == 3
    assert run.final_games == REGULAR_SEASON_GAMES


def test_derived_schedule_import_does_not_blank_the_scores_it_walks_over(
    session: Session,
) -> None:
    """The control for the score-blanking hazard, driven rather than asserted.

    ``import_games`` assigns ``game.home_score = record.home_score``
    unconditionally on a row it already has, and only ever *sets* status to
    final. A derived record that omitted scores would therefore leave 1,230
    games marked final with no score in them — a store that still looks
    complete and is not.

    The second half is the reading in which the guarantee is false: the same
    cohort with scores stripped out really does blank them. Without that half
    the first assertion would pass just as happily against an importer that
    never touched scores at all, and would exclude nothing.
    """

    _backfilled_season(session)
    parsed = schedule_from_played_games(session, season=SEASON)
    import_schedule(session, parsed, source=DERIVED_SOURCE)
    session.flush()

    assert _scored_final_games(session) == REGULAR_SEASON_GAMES

    stripped = replace(
        parsed,
        games=tuple(
            replace(record, game=replace(record.game, home_score=None, away_score=None))
            for record in parsed.games
        ),
    )
    import_schedule(session, stripped, source=DERIVED_SOURCE)
    session.flush()

    assert _scored_final_games(session) == 0, (
        "stripping scores from the derived records did not blank them, so "
        "carrying scores through is not what keeps the ledger intact and the "
        "assertion above excludes nothing"
    )


def test_the_row_count_names_the_table_it_counted(session: Session) -> None:
    """A count that survives a re-publish, because it counts rows and not writes.

    The defect this excludes, found on the owner's real store on 2026-08-26:
    ``PublishResult`` reported ``team_schedule_rows_created`` and
    ``team_schedule_rows_updated`` straight off ``import_schedule``'s
    ``ImportCounts``, and ``_persist_schedule_cohort`` seeds that object from
    ``import_games`` before it writes a single ``team_schedule`` row. So
    ``updated`` counted **nba_games**. The printed pair was ``created 2460,
    updated 1230`` for a table holding 2,460 rows — two tables summed under a
    name claiming one of them, every integer individually correct.

    The reading in which the old flag is false and the defect present is the
    **second** publish, which is why this test runs it twice. On a first run
    ``created`` is 2,460 and coincidentally equals the table count, so an
    assertion on ``created`` alone passes over the bug — the pre-existing test
    at :func:`test_a_backfilled_store_cannot_serve_reliability_until_this_command_runs`
    did exactly that. On a re-publish every row already exists, so the
    importer creates nothing: the old field would report **0** rows for a table
    that still holds 2,460. Read back from the table, the number does not move.
    """

    _backfilled_season(session)
    _observations(session)

    first = publish_reliability_evidence(session, season=SEASON)
    second = publish_reliability_evidence(session, season=SEASON)

    persisted = _rows(session, TeamScheduleEntry)

    assert persisted == REGULAR_SEASON_GAMES * 2
    assert first.team_schedule_rows == persisted
    assert second.team_schedule_rows == persisted, (
        "the re-published count moved while the table did not, so it is "
        "counting writes rather than rows and names a table it did not count"
    )

    # The other half of the same lie: whatever this number is, it must not be
    # the game count wearing a schedule label.
    assert first.team_schedule_rows != _rows(session, NbaGame)


def test_refuses_a_ledger_that_is_one_game_short(session: Session) -> None:
    _backfilled_season(session)
    dropped = session.scalars(select(NbaGame).order_by(NbaGame.nba_game_id).limit(1)).one()
    session.delete(dropped)
    session.flush()

    with pytest.raises(DerivationRefused) as excinfo:
        require_complete_regular_season(session, season=SEASON)

    message = str(excinfo.value)
    assert f"{REGULAR_SEASON_GAMES - 1} final regular-season game(s)" in message
    assert "Off-count teams" in message


def test_refuses_a_season_with_no_played_games(session: Session) -> None:
    _teams(session)

    with pytest.raises(DerivationRefused) as excinfo:
        require_complete_regular_season(session, season=SEASON)

    assert "no final regular-season games" in str(excinfo.value)


def test_the_refresh_row_names_this_command_not_an_endpoint_it_never_called(
    session: Session,
) -> None:
    """Lineage is the row that answers 'where did this schedule come from'."""

    _backfilled_season(session)
    _observations(session)
    publish_reliability_evidence(session, season=SEASON)

    sources = {
        run.source
        for run in session.scalars(
            select(RefreshRun).where(RefreshRun.artifact_type == RefreshArtifactType.SCHEDULE)
        )
    }
    assert sources == {DERIVED_SOURCE}
    assert SCHEDULE_REFRESH_SOURCE not in sources


def test_publishing_over_a_real_schedule_does_not_relabel_where_it_came_from(
    session: Session,
) -> None:
    """The lineage row keeps the producer that actually fetched the rows.

    The defect excluded: a store whose schedule came from ``ScheduleLeagueV2``
    reports, after this command runs, that its schedule was derived from
    ``nba_games``. That is a lie in the single row that answers "where did this
    schedule come from", and the true answer is gone rather than ambiguous.

    The mechanism, driven by an independent review before this test existed:
    ``schedule_content_version`` hashes the ``team_schedule`` rows and does not
    include ``source``, so a derived cohort over the same games produces the
    *same* version; ``record_refresh`` was idempotent on
    ``(artifact_type, artifact_key, version, season)`` and assigned
    ``existing.source = source`` in place. One row, last writer wins. This was
    invisible until ``import_schedule`` gained ``source=`` for this command,
    because until then only one value was ever passed for a SCHEDULE row.

    The reading in which this assertion holds and the defect is present: none
    that I can construct — the assertion is on the recorded source itself, and
    a relabel is exactly a change to that value. The weaker assertion this
    replaces (that *some* SCHEDULE row exists) is satisfied by the relabelled
    row, which is why row-existence checks never caught it.

    Note what is *not* asserted: that a conflict raises. **Nothing raises, here
    or anywhere.** An earlier draft of this docstring said "the raise is asserted
    separately below, against the primitive" — that was true of a fix which has
    since been reverted, and the sentence outlived it. ``LineageSourceConflict``
    occurs zero times in this repository. The test "below" asserts the
    *opposite*: that the primitive still relabels.

    That matters more than a stale cross-reference usually would, because the
    sentence was load-bearing. It told a reader that an independent primitive
    level guard ruled out the failure mode this test's argument depends on. No
    such guard exists, so this test is the *only* thing standing between the
    publisher and the relabel, and it should be read that way.
    """

    _backfilled_season(session)
    _observations(session)

    real = schedule_from_played_games(session, season=SEASON)
    import_schedule(session, real)
    before = _rows(session, TeamScheduleEntry)

    result = publish_reliability_evidence(session, season=SEASON)

    assert result.schedule_derived is False
    assert result.team_schedule_rows == before
    assert result.games == len(real.games)
    sources = {
        run.source
        for run in session.scalars(
            select(RefreshRun).where(RefreshRun.artifact_type == RefreshArtifactType.SCHEDULE)
        )
    }
    assert sources == {SCHEDULE_REFRESH_SOURCE}
    assert DERIVED_SOURCE not in sources
    # And the claim it published over that real cohort still serves.
    run = compute_reliability_scorecards(session, claim=result.claim)
    assert run.scorecards


def test_the_reported_schedule_source_is_the_one_the_database_holds(
    session: Session,
) -> None:
    """The printed provenance must be read back, not assumed from the branch taken.

    ``main`` used to print ``"schedule_source": DERIVED_SOURCE`` as a constant.
    On the skip branch this command writes no schedule row at all, so the JSON
    announced ``schedule_derived: false`` beside a derived source while
    ``refresh_runs.source`` held ``nba_api:ScheduleLeagueV2`` — an operator-facing
    field confidently describing something other than what it says, on the exact
    path added to *protect* that provenance.

    Same shape as the ``created 2460, updated 1230`` count this class's docstring
    records, and found the same way: by comparing the reported value against the
    store rather than against the code that produced it. An independent review
    found it; no test touched ``main``'s output before this one.

    Both branches are asserted, because a constant equal to the derived value is
    already correct on the derive branch — checking only that branch is the
    reading in which this test passes and the defect survives untouched.
    """

    _backfilled_season(session)
    _observations(session)

    derived_result = publish_reliability_evidence(session, season=SEASON)
    assert derived_result.schedule_derived is True
    assert derived_result.schedule_source == DERIVED_SOURCE

    recorded = session.scalars(
        select(RefreshRun).where(RefreshRun.artifact_type == RefreshArtifactType.SCHEDULE)
    ).one()
    assert derived_result.schedule_source == recorded.source, (
        "the reported source must be the recorded one, not the branch's constant"
    )


def test_the_reported_schedule_source_is_the_real_importers_on_the_skip_branch(
    session: Session,
) -> None:
    """The skip branch reports the importer that actually wrote the cohort.

    This is the half that fails against a hard-coded ``DERIVED_SOURCE``: the
    command skips deriving, writes no schedule row, and must report the
    provenance already in the database rather than the one it would have written.
    """

    _backfilled_season(session)
    _observations(session)

    real = schedule_from_played_games(session, season=SEASON)
    import_schedule(session, real)
    session.commit()

    result = publish_reliability_evidence(session, season=SEASON)

    assert result.schedule_derived is False
    assert result.schedule_source == SCHEDULE_REFRESH_SOURCE
    assert result.schedule_source != DERIVED_SOURCE
    recorded = session.scalars(
        select(RefreshRun).where(RefreshRun.artifact_type == RefreshArtifactType.SCHEDULE)
    ).one()
    assert result.schedule_source == recorded.source


def test_the_reported_schedule_source_is_whatever_the_row_says_not_one_of_two_constants(
    session: Session,
) -> None:
    """A third source string must survive to the report, or nothing is being read back.

    The pair of branch tests above is weaker than it looks, and an independent
    review demonstrated it: replacing the read-back with
    ``DERIVED_SOURCE if derived else SCHEDULE_REFRESH_SOURCE`` leaves **all** of
    them green. They pin that the two branches report two different strings that
    happen to be right today - not that either was ever read out of
    ``refresh_runs``. The comment on the code claims the stronger property, so the
    claim was unpinned by exactly the tests written to pin it.

    Name the defect: reporting a constant selected by the branch taken. Name the
    reading in which the branch tests are green and that defect is present:
    branch-derived constants, because ``DERIVED_SOURCE`` and
    ``SCHEDULE_REFRESH_SOURCE`` exhaust the sources that reach ``nba-schedule``
    *today*. That exhaustiveness is the accident this test removes: it stamps a
    source that is neither, so any implementation not reading the database
    reports one of two strings this test rejects.

    This matters the moment a third producer writes that scope, which is not
    hypothetical - the parameterisation of ``import_schedule`` on this branch is
    what created the second one.
    """

    third_party = "some-other-importer:nba-schedule"
    _backfilled_season(session)
    _observations(session)

    real = schedule_from_played_games(session, season=SEASON)
    import_schedule(session, real, source=third_party)
    session.commit()

    result = publish_reliability_evidence(session, season=SEASON)

    assert result.schedule_derived is False
    assert result.schedule_source == third_party, (
        "the report must carry the recorded source, not a constant the branch selects"
    )
    assert result.schedule_source not in {DERIVED_SOURCE, SCHEDULE_REFRESH_SOURCE}


def test_the_command_prints_the_source_it_read_not_the_one_it_would_have_written(
    session: Session,
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The operator JSON is the artefact that lied, so the assertion belongs there.

    The defect this test exists for was a hard-coded ``"schedule_source":
    DERIVED_SOURCE`` in ``main``'s printed payload, announcing a derived source
    beside ``schedule_derived: false``. An independent review restored that exact
    line at its exact location and **all twenty-three tests stayed green**: every
    assertion was on ``PublishResult``, a field introduced by the same commit, and
    nothing in the repository called ``main`` at all.

    So the fix's regression barrier did not exist at the defect's own location.
    Pinning the dataclass and calling the command covered is the coverage-check
    shape this project keeps finding - the mechanism that broke was never read.

    ``main`` opens its own ``Database`` from ``--database-url``, so this seeds
    through the fixture session, commits, and then lets the command connect
    independently. That is also the only way the printed payload can be observed
    the way an operator observes it.

    **The ``session.commit()`` below is load-bearing and not tidiness.** ``main``
    connects as a second client, so uncommitted work is invisible to it - and on
    Postgres, where CI runs this same suite, the fixture session would still hold
    row locks that the command's own writes would block on. It would hang there
    rather than fail, while passing on SQLite. Do not move the commit below the
    ``main`` call, and do not assume the fixture session's state is visible.
    """

    _backfilled_season(session)
    _observations(session)

    real = schedule_from_played_games(session, season=SEASON)
    import_schedule(session, real)
    session.commit()

    exit_code = main(["--database-url", settings.database_url, "--season", SEASON])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schedule_derived"] is False
    assert payload["schedule_source"] == SCHEDULE_REFRESH_SOURCE, (
        "the printed source must be the recorded one; this is the field that lied"
    )
    assert payload["schedule_source"] != DERIVED_SOURCE
    assert payload["season"] == SEASON


def test_record_refresh_still_relabels_which_is_why_the_publisher_skips(
    session: Session,
) -> None:
    """Pins a defect this PR deliberately does **not** fix. Read the reason.

    ``record_refresh`` is idempotent on ``(artifact_type, artifact_key, version,
    season)`` and assigns ``existing.source = source`` in place.
    ``schedule_content_version`` hashes the ``team_schedule`` rows and does not
    include ``source``, so two producers that agree on content and disagree on
    source collide on one row: the last writer wins and the earlier provenance
    is *gone* rather than ambiguous. This test asserts that this is what happens
    today, so the defect is executable rather than only described.

    **Why it is not fixed here.** I fixed it, and then the Adapter gate refused
    the fix, correctly. ``docs/adapters/nba-injury-report-cohort-2025-10-21--
    2026-04-12.json`` fingerprints ``backend/src/hoops_gm/db/lineage.py`` among
    its six source files, and ``test_cohort_evidence.py`` requires every live
    manifest to describe code that still exists. Editing the file invalidates a
    published provenance claim, and the only honest repair is regenerating that
    manifest from the store it was derived from.

    That regeneration **is** available to this lane, and an earlier version of
    this docstring said it was not. The claim was that the generator refuses
    without ``--allow-fetch`` because three reconciliation views have no capture,
    so the repair needs live ``stats.nba.com`` calls. **Driven, and false.** The
    refusal came from ``--raw-root`` defaulting to ``backend/data/raw``, which
    does not exist; the captures are in the operator's payload store, and pointed
    at it the generator runs offline and exits 0 with all four views agreed.

    Two results from actually running it. At an **unmodified** tree, regenerating
    over the committed path leaves an **empty git diff** — so the manifest is
    exactly reproducible and any later comparison is controlled rather than
    lucky. With the primitive fixed, exactly **one** of 1656 leaves moves: the
    ``db/lineage.py`` fingerprint, ``daf7d90d…`` to ``2e3d8eb9…``, matching the
    pair CI reported. Every cohort number is byte-identical, which is positive
    evidence the lineage change does not reach the injury cohort.

    **So the reason this is not fixed here is ownership, not feasibility.** That
    manifest is ``data-engineer``'s artifact under the Adapter gate. A manifest
    regenerated by ``backend`` **passes its own fingerprint check by
    construction** — the check compares the manifest to the tree that produced
    it, so it is green whoever ran it. Green would mean the bytes agree, not that
    this lane was entitled to republish another lane's evidence, and no gate in
    the repository distinguishes those two.

    So the hazard is closed where this PR created reach for it — the publisher
    skips deriving when a real cohort is already current, which the test above
    pins — and left open in the primitive, recorded here and in the handoff, to
    be closed by a unit that owns the manifest regeneration alongside it.

    **The defect is reachable, not latent, and an earlier draft of this docstring
    said otherwise.** It claimed the revert "also removed
    ``import_schedule(source=...)``". It did not: ``origin/main`` has
    ``import_schedule(session, parsed)``, this PR adds
    ``source: str = SCHEDULE_REFRESH_SOURCE``, and this module's derive branch
    passes ``import_schedule(session, parsed, source=DERIVED_SOURCE)``.
    SCHEDULE/``nba-schedule`` is the only
    multi-source scope in the codebase and **this PR is what made it one**. The
    claim was inherited from a review of the tree rather than driven, and it is
    contradicted by the file it was written in.

    So what holds the defect off is the runtime skip below, in one of the two
    orderings — not an absence of reach.

    **The reading in which this test passes and the defect is absent:** none —
    it asserts the relabel directly. When the primitive is fixed, this test
    fails, which is the intended signal and the point of writing it this way.
    """

    _backfilled_season(session)
    parsed = schedule_from_played_games(session, season=SEASON)
    import_schedule(session, parsed)
    row = session.scalars(
        select(RefreshRun).where(RefreshRun.artifact_type == RefreshArtifactType.SCHEDULE)
    ).one()
    version, original_source = row.version, row.source
    assert original_source == SCHEDULE_REFRESH_SOURCE

    relabelled = record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version=version,
        source=DERIVED_SOURCE,
        season=SEASON,
    )

    # The defect, stated as an assertion: one row, and the real importer's
    # provenance has been overwritten rather than recorded alongside.
    assert relabelled.source == DERIVED_SOURCE
    surviving = session.scalars(
        select(RefreshRun).where(RefreshRun.artifact_type == RefreshArtifactType.SCHEDULE)
    ).all()
    assert [r.source for r in surviving] == [DERIVED_SOURCE]
    assert SCHEDULE_REFRESH_SOURCE not in {r.source for r in surviving}


def test_the_refusal_a_backfilled_store_reaches_is_the_missing_refresh_cohort(
    session: Session,
) -> None:
    """Which refusal, exactly — because the screen named the wrong one twice.

    The merged reliability screen said the owner's 2025-26 store "has no
    ``team_schedule`` table at all". It has the table; the table is empty. The
    correction that replaced that claim named the empty-schedule check in
    ``_source_snapshot`` instead, and that is one refusal too late:
    ``publish_reliability_cohorts`` requires a current
    ``schedule:nba-schedule`` refresh **before** it reads ``team_schedule``,
    and a backfilled store has no ``refresh_runs`` rows either. So the refusal
    actually reached is ``StaleReliabilityCohortError``, with the empty-schedule
    ``ReliabilityInputError`` immediately behind it.

    Both halves are asserted because either alone is compatible with the wrong
    story: the first without the second would not show that emptiness is also
    fatal, and the second without the first would not show which one a caller
    meets. This test is why the frontend blocker text for those rows now names
    the missing cohort rather than a missing table.

    Verified against a copy of the owner's real store on 2026-08-26, where the
    same two messages appear in the same order.
    """

    _backfilled_season(session)
    _observations(session)

    assert _rows(session, TeamScheduleEntry) == 0
    assert _rows(session, RefreshRun) == 0
    # The table is present and queryable. A missing table raises
    # OperationalError here rather than returning an empty list.
    assert session.scalars(select(TeamScheduleEntry)).all() == []

    with pytest.raises(StaleReliabilityCohortError) as first:
        publish_reliability_cohorts(session, season=SEASON, as_of_date=LAST_GAME_DAY)
    assert "no current schedule:nba-schedule cohort" in str(first.value)
    session.rollback()

    _backfilled_season(session)
    _observations(session)
    with pytest.raises(ReliabilityInputError) as second:
        _source_snapshot(
            session,
            season=SEASON,
            season_type=SeasonType.REGULAR,
            window_start=None,
            as_of_date=LAST_GAME_DAY,
        )
    assert "no scheduled team games found" in str(second.value)


def test_a_caller_that_says_nothing_still_stamps_the_nba_endpoint(session: Session) -> None:
    """The default is unchanged, so no existing importer's lineage moved.

    Deliberately not a full season: ``import_schedule`` checks its cohort for
    internal consistency, not for being 82 games long, and the claim under
    test is about one string.
    """

    teams = _teams(session)
    home, away = teams[0], teams[1]
    record = ScheduleGameRecord(
        game=NbaGameRecord(
            nba_game_id="0022500001",
            season=SEASON,
            season_type=SeasonType.REGULAR.value,
            game_date=OPENING_DAY,
            home_team_id=home.nba_team_id,
            away_team_id=away.nba_team_id,
            home_score=None,
            away_score=None,
            tipoff_utc=None,
        ),
        home_nba_team_id=home.nba_team_id,
        away_nba_team_id=away.nba_team_id,
        home_tricode=home.abbreviation,
        away_tricode=away.abbreviation,
    )
    import_schedule(
        session,
        ScheduleParseResult(
            season=SEASON,
            games=(record,),
            unresolved_game_ids=(),
            source_game_count=1,
            pending_games=(),
        ),
    )
    session.flush()

    run = session.scalars(
        select(RefreshRun).where(RefreshRun.artifact_type == RefreshArtifactType.SCHEDULE)
    ).one()
    assert run.source == SCHEDULE_REFRESH_SOURCE
