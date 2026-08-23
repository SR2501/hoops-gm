"""The cross-store join, exercised rather than asserted.

``cohort_admissibility`` joins two databases that no single store spans: the
durable ledger holds participation and no injury reports; the report sweep
holds reports and no participation. That join is the highest-risk code in the
unit, and until these tests it had no executable witness — which is exactly the
"unexamined inheritance" failure ``AGENTS.md`` says only executable tests catch.

The two fixture stores are built with **deliberately disjoint surrogate ids**.
If the join ever silently falls back to ``(game_id, player_id)`` — the local
keys :func:`cohort_evidence._participation_join` correctly uses *within* one
store — these tests go red instead of a season's worth of evidence going quietly
wrong.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from hoops_gm.db.models import (
    Base,
    InjuryReportEntry,
    NbaGame,
    NbaTeam,
    Player,
    PlayerExternalId,
    PlayerParticipation,
)
from hoops_gm.db.models.enums import (
    DnpReason,
    ExternalSource,
    GameStatus,
    InjuryReportStatus,
    MatchMethod,
    ParticipationOutcome,
    PlayerStatus,
    SeasonType,
)
from hoops_gm.db.models.injury_report import (
    CURRENT_EVIDENCE_SCHEMA_VERSION,
    LEGACY_EVIDENCE_SCHEMA_VERSION,
)
from hoops_gm.ingest.injury_report.cohort_admissibility import (
    build_admissibility_evidence,
    outcome_keyed_field_paths,
)

pytestmark = pytest.mark.adapter_contract

SEASON = "2025-26"
FREEZE = "injury-status-conversion-v2-20260821T145900Z"

#: Ten game dates, so §4's floor rules give 5 / 2 / 3 and the holdout is a
#: strict, non-trivial suffix.
DATES = [date(2025, 12, 1) + timedelta(days=i) for i in range(10)]


def _tipoff(day: date) -> datetime:
    """00:30 UTC the following day — a 7:30pm ET tip.

    Deliberately on the far side of midnight UTC from its own ``game_date``.
    ``AGENTS.md`` records that ``gameEt`` carries a ``Z`` and is not UTC, which
    shifts ``game_date`` for every game tipping after 7pm Eastern — i.e. most of
    them. A fixture whose tip-offs sit safely inside their own UTC date cannot
    see that class of defect.
    """
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(days=1, minutes=30)


@pytest.fixture
def stores() -> Iterator[tuple[Session, Session]]:
    """A participation store and a report store, with disjoint surrogate ids."""
    engines = [create_engine("sqlite://") for _ in range(2)]
    for engine in engines:
        Base.metadata.create_all(engine)
    participation = Session(engines[0])
    report = Session(engines[1])
    try:
        yield participation, report
    finally:
        # Roll back and dispose explicitly. Letting the engines fall to the
        # garbage collector raises unraisable-exception warnings that pytest
        # turns into teardown errors on unrelated tests.
        for session in (participation, report):
            session.rollback()
            session.close()
        for engine in engines:
            engine.dispose()


def _teams(session: Session, *, base: int) -> tuple[NbaTeam, NbaTeam]:
    home = NbaTeam(
        id=base, nba_team_id=1610612744, abbreviation="GSW", name="Warriors", is_active=True
    )
    away = NbaTeam(
        id=base + 1, nba_team_id=1610612747, abbreviation="LAL", name="Lakers", is_active=True
    )
    session.add_all([home, away])
    session.flush()
    return home, away


def _games(session: Session, *, base: int, home: NbaTeam, away: NbaTeam) -> list[NbaGame]:
    games = [
        NbaGame(
            id=base + index,
            season=SEASON,
            season_type=SeasonType.REGULAR,
            nba_game_id=f"002250{index:04d}",
            game_date=day,
            tipoff_utc=_tipoff(day),
            status=GameStatus.FINAL,
            home_team_id=home.id,
            away_team_id=away.id,
        )
        for index, day in enumerate(DATES)
    ]
    session.add_all(games)
    session.flush()
    return games


def _players(session: Session, *, base: int, count: int) -> list[Player]:
    players = []
    for index in range(count):
        player = Player(
            id=base + index,
            full_name=f"Player {index}",
            normalized_name=f"player {index}",
            status=PlayerStatus.ACTIVE,
        )
        session.add(player)
        session.flush()
        session.add(
            PlayerExternalId(
                player_id=player.id,
                source=ExternalSource.NBA,
                external_id=f"20000{index:02d}",
                confidence=1.0,
                match_method=MatchMethod.ANCHOR_ID,
                is_manual_override=False,
            )
        )
        players.append(player)
    session.flush()
    return players


def _build(
    participation: Session,
    report: Session,
    *,
    statuses: dict[str, InjuryReportStatus],
    outcome: ParticipationOutcome = ParticipationOutcome.PLAYED,
    schema_version: int = CURRENT_EVIDENCE_SCHEMA_VERSION,
    skip_participation_for: set[str] | None = None,
    unresolved: set[str] | None = None,
    report_tipoff_shift: timedelta | None = None,
) -> dict[str, object]:
    """Populate both stores and run the builder.

    ``statuses`` maps an external NBA player id to the designation that player
    carries on every game date.
    """
    skip_participation_for = skip_participation_for or set()
    unresolved = unresolved or set()

    # Participation store: surrogate ids start at 1.
    p_home, p_away = _teams(participation, base=1)
    p_games = _games(participation, base=1, home=p_home, away=p_away)
    _players(participation, base=1, count=len(statuses))
    p_by_external = {
        row.external_id: row.player_id for row in participation.query(PlayerExternalId).all()
    }
    for external_id in statuses:
        if external_id in skip_participation_for:
            continue
        for game in p_games:
            participation.add(
                PlayerParticipation(
                    player_id=p_by_external[external_id],
                    game_id=game.id,
                    team_id=p_home.id,
                    outcome=outcome,
                    reason=DnpReason.NONE_GIVEN,
                    raw_comment="",
                    source=ExternalSource.NBA,
                    inactive_list_available=True,
                )
            )
    participation.flush()

    # Report store: surrogate ids start at 5000, so every id differs.
    r_home, r_away = _teams(report, base=5000)
    r_games = _games(report, base=5000, home=r_home, away=r_away)
    if report_tipoff_shift is not None:
        for game in r_games:
            shifted: datetime = _tipoff(game.game_date) + report_tipoff_shift
            game.tipoff_utc = shifted
    _players(report, base=5000, count=len(statuses))
    r_by_external = {row.external_id: row.player_id for row in report.query(PlayerExternalId).all()}
    for external_id, status in statuses.items():
        for game in r_games:
            report.add(
                InjuryReportEntry(
                    # Derived from the *authoritative* instant, never from this
                    # store's own (possibly shifted) column -- otherwise the
                    # shift experiment below would move the report timestamps
                    # too and prove nothing.
                    report_timestamp=_tipoff(game.game_date) - timedelta(minutes=90),
                    game_date=game.game_date,
                    game_time_raw="07:30 (ET)",
                    matchup_raw="LAL@GSW",
                    team_raw="Golden State Warriors",
                    team_id=r_home.id,
                    game_id=game.id,
                    player_name_raw=f"Fixture, {external_id}",
                    player_id=(None if external_id in unresolved else r_by_external[external_id]),
                    status_raw=status.value.title(),
                    status=status,
                    source_url="https://example.invalid/fixture",
                    import_schema_version=schema_version,
                )
            )
    report.flush()

    return build_admissibility_evidence(participation, report, season=SEASON, freeze_id=FREEZE)


ALL_FIVE = {
    "2000000": InjuryReportStatus.OUT,
    "2000001": InjuryReportStatus.DOUBTFUL,
    "2000002": InjuryReportStatus.QUESTIONABLE,
    "2000003": InjuryReportStatus.PROBABLE,
    "2000004": InjuryReportStatus.AVAILABLE,
}


class TestTheJoinCrossesStoresOnStableIdentity:
    def test_every_observation_joins_despite_disjoint_surrogate_ids(
        self, stores: tuple[Session, Session]
    ) -> None:
        evidence = _build(*stores, statuses=ALL_FIVE)
        section = evidence["section_2_admissibility"]
        assert isinstance(section, dict)
        # 5 players x 10 dates, every one joined.
        assert section["canonical_observations_by_status"] == {
            s.value: 10 for s in ALL_FIVE.values()
        }
        assert section["direct_outcomes_by_status"] == {s.value: 10 for s in ALL_FIVE.values()}
        exclusions = evidence["exclusion_classes_by_status"]
        assert isinstance(exclusions, dict)
        assert exclusions["resolved_observations_without_participation_row"] == {}

    def test_the_stores_really_do_have_disjoint_surrogate_ids(
        self, stores: tuple[Session, Session]
    ) -> None:
        # Guards the guard: if both fixtures ever used the same id base, every
        # test in this file would pass for the wrong reason.
        _build(*stores, statuses=ALL_FIVE)
        participation, report = stores
        p_ids = {g.id for g in participation.query(NbaGame).all()}
        r_ids = {g.id for g in report.query(NbaGame).all()}
        assert p_ids and r_ids
        assert not (p_ids & r_ids)

    def test_a_missing_participation_row_is_never_inferred_as_non_play(
        self, stores: tuple[Session, Session]
    ) -> None:
        # R35: a silent ledger is not an absence.
        evidence = _build(*stores, statuses=ALL_FIVE, skip_participation_for={"2000001"})
        section = evidence["section_2_admissibility"]
        exclusions = evidence["exclusion_classes_by_status"]
        assert isinstance(section, dict)
        assert isinstance(exclusions, dict)
        assert section["direct_outcomes_by_status"]["doubtful"] == 0
        assert exclusions["resolved_observations_without_participation_row"] == {"doubtful": 10}
        assert section["canonical_observations_by_status"]["doubtful"] == 10

    def test_an_unknown_outcome_is_counted_out_of_the_direct_set(
        self, stores: tuple[Session, Session]
    ) -> None:
        evidence = _build(*stores, statuses=ALL_FIVE, outcome=ParticipationOutcome.UNKNOWN)
        section = evidence["section_2_admissibility"]
        exclusions = evidence["exclusion_classes_by_status"]
        assert isinstance(section, dict)
        assert isinstance(exclusions, dict)
        assert section["direct_outcomes_by_status"] == {s.value: 0 for s in ALL_FIVE.values()}
        assert exclusions["with_non_direct_participation_outcome"] == {
            s.value: 10 for s in ALL_FIVE.values()
        }
        assert section["admissible"] is False

    def test_an_unresolved_identity_is_its_own_exclusion_class(
        self, stores: tuple[Session, Session]
    ) -> None:
        evidence = _build(*stores, statuses=ALL_FIVE, unresolved={"2000004"})
        exclusions = evidence["exclusion_classes_by_status"]
        section = evidence["section_2_admissibility"]
        assert isinstance(exclusions, dict)
        assert isinstance(section, dict)
        assert exclusions["unresolved_player_identity"] == {"available": 10}
        assert section["direct_outcomes_by_status"]["available"] == 0


class TestTheReportStoreTipoffsAreNeverUsed:
    def test_lead_times_are_measured_against_the_authoritative_instant(
        self, stores: tuple[Session, Session]
    ) -> None:
        """Baseline for the shift experiment below.

        Every fixture report row is filed 90 minutes before the participation
        store's tip-off, so both lead-time ranges must pin to exactly 90.
        """
        baseline = _build(*stores, statuses=ALL_FIVE)
        assert baseline["lead_time_minutes"] == {
            "canonical": {"maximum": 90, "minimum": 90},
            "direct": {"maximum": 90, "minimum": 90},
        }

    def test_shifting_the_report_store_tipoff_is_reported_but_changes_no_count(
        self, stores: tuple[Session, Session]
    ) -> None:
        """The decontamination, stated as a falsifiable experiment.

        The report store's ``tipoff_utc`` is moved four hours. If the builder
        read it — for the pre-tip-off gate or for a lead time — the counts or
        the lead-time range would move. Neither may. The disagreement is still
        *reported*, because a store that disagrees is evidence even when it
        cannot affect the result.
        """
        evidence = _build(*stores, statuses=ALL_FIVE, report_tipoff_shift=timedelta(hours=4))
        agreement = evidence["cross_store_tipoff_agreement"]
        assert isinstance(agreement, dict)
        assert agreement["agreed"] is False
        assert agreement["witnessed"] is True
        assert len(agreement["tipoff_disagreements"]) == len(DATES)

        # ...and yet every count is unchanged, because the report store's
        # instants never reach the selection. That is the property that makes
        # the cross-store join sound rather than merely lucky.
        section = evidence["section_2_admissibility"]
        assert isinstance(section, dict)
        assert section["direct_outcomes_by_status"] == {s.value: 10 for s in ALL_FIVE.values()}
        assert evidence["lead_time_minutes"] == {
            "canonical": {"maximum": 90, "minimum": 90},
            "direct": {"maximum": 90, "minimum": 90},
        }

    def test_a_post_tipoff_report_row_contributes_nothing(
        self, stores: tuple[Session, Session]
    ) -> None:
        participation, report = stores
        evidence = _build(participation, report, statuses=ALL_FIVE)
        section = evidence["section_2_admissibility"]
        assert isinstance(section, dict)
        baseline = section["canonical_observations_by_status"]["out"]

        # Move every `out` row to one minute after tip-off.
        for entry in report.query(InjuryReportEntry).all():
            if entry.status is InjuryReportStatus.OUT:
                game = report.query(NbaGame).filter(NbaGame.id == entry.game_id).one()
                after_tip: datetime = _tipoff(game.game_date) + timedelta(minutes=1)
                entry.report_timestamp = after_tip
        report.flush()

        after = build_admissibility_evidence(participation, report, season=SEASON, freeze_id=FREEZE)
        section_after = after["section_2_admissibility"]
        assert isinstance(section_after, dict)
        assert baseline == len(DATES)
        assert section_after["canonical_observations_by_status"]["out"] == 0


class TestTheGateItself:
    def test_a_status_below_the_floor_refuses_the_cohort(
        self, stores: tuple[Session, Session]
    ) -> None:
        # Three held-out dates gives 3 direct outcomes per status, far under 30.
        evidence = _build(*stores, statuses=ALL_FIVE)
        section = evidence["section_2_admissibility"]
        assert isinstance(section, dict)
        assert section["split_game_dates"] == {
            "development": 5,
            "selection": 2,
            "held_out": 3,
        }
        assert section["held_out_direct_outcomes_by_status"] == {
            s.value: 3 for s in ALL_FIVE.values()
        }
        assert section["admissible"] is False
        assert section["statuses_below_floor"] == sorted(s.value for s in ALL_FIVE.values())

    def test_legacy_rows_are_excluded_rather_than_trusted(
        self, stores: tuple[Session, Session]
    ) -> None:
        evidence = _build(*stores, statuses=ALL_FIVE, schema_version=LEGACY_EVIDENCE_SCHEMA_VERSION)
        section = evidence["section_2_admissibility"]
        assert isinstance(section, dict)
        assert section["canonical_observations_by_status"] == {
            s.value: 0 for s in ALL_FIVE.values()
        }

    def test_the_builder_emits_no_outcome_keyed_field(
        self, stores: tuple[Session, Session]
    ) -> None:
        evidence = _build(*stores, statuses=ALL_FIVE)
        assert outcome_keyed_field_paths(evidence) == frozenset()

    def test_the_by_date_table_covers_every_cohort_date(
        self, stores: tuple[Session, Session]
    ) -> None:
        evidence = _build(*stores, statuses=ALL_FIVE)
        by_date = evidence["direct_outcome_counts_by_game_date"]
        assert isinstance(by_date, dict)
        assert sorted(by_date) == [d.isoformat() for d in DATES]
