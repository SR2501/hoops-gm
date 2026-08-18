"""League settings normalization and source-priority behavior."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models import League, LeagueSettingsSnapshot
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.importers import import_league_settings
from hoops_gm.ingest.league_settings import (
    BRIDGE_SOURCE,
    GamesCapRules,
    KeeperRules,
    LeagueSettingsDocument,
    LineupLockRules,
    PlayoffRules,
    RosterLimits,
    ScoringPeriodRules,
    SettingEvidence,
    SourcedSetting,
    TradeDeadlineRules,
    WaiverRules,
    merge_settings,
    parse_official_league_settings,
)


def _official_payload() -> dict[str, object]:
    return {
        "seasonYear": 2025,
        "startDate": "2025-10-21",
        "endDate": "2026-03-15",
        "rosterInfo": {
            "positionConstraints": {
                "G": {"maxActive": 4},
                "F": {"maxActive": 4},
                "C": {"maxActive": 2},
            },
            "maxTotalPlayers": 14,
            "maxTotalActivePlayers": 10,
            "maxTotalReservePlayers": 4,
        },
        "scoringPeriods": [
            {
                "number": 1,
                "startDate": "2026-10-20T00:00:00-04:00",
                "endDate": "2026-10-25T23:59:59-04:00",
            },
            {
                "number": 2,
                "startDate": "2026-10-26T00:00:00-04:00",
                "endDate": "2026-11-01T23:59:59-05:00",
            },
        ],
    }


def test_official_fields_are_known_and_absent_fields_stay_unknown() -> None:
    settings = parse_official_league_settings(_official_payload(), capture_ref="sha256:abc")

    assert settings.roster_limits.value == RosterLimits(
        total=14,
        active=10,
        reserve=4,
        position_active={"G": 4, "F": 4, "C": 2},
    )
    assert settings.scoring_periods.value is not None
    assert len(settings.scoring_periods.value.periods) == 2
    assert settings.lineup_lock.value is None
    assert settings.waivers.value is None
    assert settings.games_caps.value is None
    assert settings.trade_deadline.value is None
    assert settings.playoffs.value is None
    assert settings.keepers.value is None
    assert all(item.status == "absent" for item in settings.waivers.evidence)
    assert settings.source_season_year == 2025


def test_no_ir_limit_is_inferred_from_the_total_reserve_limit() -> None:
    settings = parse_official_league_settings(_official_payload(), capture_ref="sha256:abc")

    assert settings.roster_limits.value is not None
    assert settings.roster_limits.value.reserve == 4
    assert settings.roster_limits.value.injured_reserve is None
    assert settings.roster_limits.value.injured_reserve_eligibility is None


def test_bridge_fills_only_an_official_unknown() -> None:
    official = parse_official_league_settings(_official_payload(), capture_ref="sha256:abc")
    bridge_evidence = (
        SettingEvidence(
            source=BRIDGE_SOURCE,
            status="observed",
            source_path="League Rules > Lineups",
            capture_ref="bridge_payload:42",
        ),
    )
    bridge = LeagueSettingsDocument(
        source_season_year=2025,
        source_start_date="2025-10-21",
        source_end_date="2026-03-15",
        lineup_lock=SourcedSetting(
            value=LineupLockRules(lock_type="per_player_tipoff"),
            evidence=bridge_evidence,
        ),
        waivers=_bridge_unknown(),
        games_caps=_bridge_unknown(),
        roster_limits=SourcedSetting(
            value=RosterLimits(total=99),
            evidence=bridge_evidence,
        ),
        scoring_periods=_bridge_unknown(),
        trade_deadline=_bridge_unknown(),
        playoffs=_bridge_unknown(),
        keepers=_bridge_unknown(),
    )

    merged = merge_settings(official, bridge)

    assert merged.lineup_lock.value == LineupLockRules(lock_type="per_player_tipoff")
    assert {item.source for item in merged.lineup_lock.evidence} == {
        "fantrax_official",
        "fantrax_bridge",
    }
    assert merged.roster_limits == official.roster_limits


def test_content_hash_changes_when_configuration_changes() -> None:
    before = parse_official_league_settings(_official_payload(), capture_ref="sha256:abc")
    changed_payload = _official_payload()
    roster = changed_payload["rosterInfo"]
    assert isinstance(roster, dict)
    roster["maxTotalPlayers"] = 15
    after = parse_official_league_settings(changed_payload, capture_ref="sha256:abc")

    assert before.content_sha256() != after.content_sha256()


def test_rule_shaped_unmapped_keys_are_loud_diagnostics() -> None:
    payload = _official_payload()
    payload["waiverSettings"] = {"mode": "priority"}

    settings = parse_official_league_settings(payload, capture_ref="sha256:abc")

    assert settings.unmapped_rule_paths == ("$.waiverSettings",)


@pytest.mark.parametrize(
    "payload",
    [
        {"rosterInfo": [], "scoringPeriods": _official_payload()["scoringPeriods"]},
        {"rosterInfo": _official_payload()["rosterInfo"], "scoringPeriods": []},
        {
            "rosterInfo": _official_payload()["rosterInfo"],
            "scoringPeriods": [{"number": 1, "startDate": "2026-10-20"}],
        },
    ],
)
def test_malformed_present_fields_fail_instead_of_becoming_unknown(
    payload: dict[str, object],
) -> None:
    with pytest.raises(SourceContractError):
        parse_official_league_settings(payload, capture_ref="sha256:abc")


def _bridge_unknown[ValueT]() -> SourcedSetting[ValueT]:
    return SourcedSetting(
        value=None,
        evidence=(
            SettingEvidence(
                source=BRIDGE_SOURCE,
                status="absent",
                source_path="League Rules",
                capture_ref="bridge_payload:42",
            ),
        ),
    )


# Keep every settings type imported and therefore type-checked as a supported
# document value, even before a live source supplies examples for all of them.
_SUPPORTED_TYPES = (
    WaiverRules,
    GamesCapRules,
    ScoringPeriodRules,
    TradeDeadlineRules,
    PlayoffRules,
    KeeperRules,
)


def test_import_rejects_a_source_season_that_does_not_match_the_league(
    session: Session,
) -> None:
    league = League(name="Future league", season="2026-27")
    session.add(league)
    session.flush()
    document = parse_official_league_settings(_official_payload(), capture_ref="fixture:official")

    with pytest.raises(ValueError, match="source seasonYear=2025 means 2025-26"):
        import_league_settings(
            session,
            league=league,
            document=document,
            source_payload_sha256="a" * 64,
            observed_at=datetime(2026, 8, 18, tzinfo=UTC),
        )


def test_import_is_versioned_idempotent_and_preserves_source_evidence(
    session: Session,
) -> None:
    league = League(name="Historical league", season="2025-26")
    session.add(league)
    session.flush()
    document = parse_official_league_settings(_official_payload(), capture_ref="fixture:official")

    first = import_league_settings(
        session,
        league=league,
        document=document,
        source_payload_sha256="a" * 64,
        observed_at=datetime(2026, 8, 18, tzinfo=UTC),
    )
    duplicate = import_league_settings(
        session,
        league=league,
        document=document,
        source_payload_sha256="a" * 64,
        observed_at=datetime(2026, 8, 18, tzinfo=UTC),
    )
    changed = document.model_copy(
        update={
            "trade_deadline": SourcedSetting(
                value=TradeDeadlineRules(deadline_at="2026-02-12T23:59:59-0500"),
                evidence=(
                    SettingEvidence(
                        source=BRIDGE_SOURCE,
                        capture_ref="fixture:bridge",
                        status="observed",
                    ),
                ),
            )
        }
    )
    second = import_league_settings(
        session,
        league=league,
        document=changed,
        source_payload_sha256="b" * 64,
        observed_at=datetime(2026, 8, 19, tzinfo=UTC),
    )

    snapshots = list(
        session.scalars(select(LeagueSettingsSnapshot).order_by(LeagueSettingsSnapshot.version))
    )
    assert first.created == 1
    assert duplicate.skipped == 1
    assert second.created == 1
    assert [snapshot.version for snapshot in snapshots] == [1, 2]
    first_deadline = snapshots[0].settings["trade_deadline"]
    second_deadline = snapshots[1].settings["trade_deadline"]
    games_cap_source = snapshots[0].source_summary["games_caps"]
    assert isinstance(first_deadline, dict)
    assert isinstance(second_deadline, dict)
    assert isinstance(second_deadline["value"], dict)
    assert isinstance(games_cap_source, list)
    assert isinstance(games_cap_source[0], dict)
    assert first_deadline["value"] is None
    assert second_deadline["value"]["deadline_at"] == "2026-02-12T23:59:59-0500"
    assert games_cap_source[0]["status"] == "absent"
