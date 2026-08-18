"""``league_settings_snapshots``: the versioned, source-attributed rules boundary.

Covers the ORM contract for `league-settings-ingest` (docs/backlog.md) --
persistence only. Nothing here parses a Fantrax payload or decides what a
league's rules mean; see ``db/models/league_settings.py`` for the boundary
this deliberately does not cross, and
``docs/league/2025-26-rules-baseline.md`` for why a historical value may never
silently fill an unverified one.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.db.base import Base
from hoops_gm.db.models import League, LeagueSettingsSnapshot


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _league(session: Session, name: str = "Test League") -> League:
    league = League(name=name, season="2026-27")
    session.add(league)
    session.flush()
    return league


def _snapshot(league_id: int, version: int = 1, **overrides: object) -> LeagueSettingsSnapshot:
    values: dict[str, object] = {
        "league_id": league_id,
        "version": version,
        "schema_version": "2026-27.v1",
        "settings": {
            "lineup_lock": {"type": "per_player_tipoff", "lock_offset_minutes": 1},
            # Absent from every source seen so far: explicit null, not omitted.
            "waivers": {
                "period_days": None,
                "processing_time_local": "01:00",
                "claim_mechanism": "priority",
                "faab_budget": None,
            },
            "games_caps": None,
            "roster": {"active": 9, "ir": 3},
            "trade_deadline": None,
            "playoff_periods": None,
            "keeper_rules": None,
        },
        "source_summary": {
            "lineup_lock.type": {"source": "fantrax_official_api", "observed_at": "2026-08-17"},
            "waivers.processing_time_local": {
                "source": "bridge_capture",
                "observed_at": "2026-08-17",
            },
            "waivers.period_days": {"source": None, "observed_at": None},
            "games_caps": {"source": None, "observed_at": None},
        },
        "source_payload_sha256": _sha256(f"payload-{version}"),
        "observed_at": datetime(2026, 8, 17, tzinfo=UTC),
    }
    values.update(overrides)
    return LeagueSettingsSnapshot(**values)


def test_the_table_is_registered_and_created(session: Session) -> None:
    inspector = inspect(session.get_bind())
    assert "league_settings_snapshots" in inspector.get_table_names()
    assert "league_settings_snapshots" in Base.metadata.tables


def test_a_snapshot_round_trips_settings_and_source_summary(session: Session) -> None:
    league = _league(session)
    session.add(_snapshot(league.id))
    session.flush()
    session.expire_all()

    [snapshot] = session.query(LeagueSettingsSnapshot).all()

    lineup_lock = snapshot.settings["lineup_lock"]
    lineup_source = snapshot.source_summary["lineup_lock.type"]
    assert isinstance(lineup_lock, dict)
    assert isinstance(lineup_source, dict)
    assert lineup_lock["type"] == "per_player_tipoff"
    assert lineup_source["source"] == "fantrax_official_api"


def test_an_absent_field_is_stored_as_null_not_omitted(session: Session) -> None:
    """The single guarantee that matters most: unknown stays unknown.

    A field no source has supplied must round-trip as an explicit ``null``
    inside the JSON document, never silently disappear and never be filled
    from the 2025-26 historical baseline.
    """
    league = _league(session)
    session.add(_snapshot(league.id))
    session.flush()
    session.expire_all()

    [snapshot] = session.query(LeagueSettingsSnapshot).all()

    assert "games_caps" in snapshot.settings
    assert snapshot.settings["games_caps"] is None
    waivers = snapshot.settings["waivers"]
    games_cap_source = snapshot.source_summary["games_caps"]
    assert isinstance(waivers, dict)
    assert isinstance(games_cap_source, dict)
    assert "faab_budget" in waivers
    assert waivers["faab_budget"] is None
    assert games_cap_source["source"] is None


def test_source_attribution_may_differ_per_field(session: Session) -> None:
    """Some fields come from the official API, others only from the bridge."""
    league = _league(session)
    session.add(_snapshot(league.id))
    session.flush()
    session.expire_all()

    [snapshot] = session.query(LeagueSettingsSnapshot).all()

    lineup_source = snapshot.source_summary["lineup_lock.type"]
    waiver_source = snapshot.source_summary["waivers.processing_time_local"]
    assert isinstance(lineup_source, dict)
    assert isinstance(waiver_source, dict)
    assert lineup_source["source"] == "fantrax_official_api"
    assert waiver_source["source"] == "bridge_capture"


def test_snapshots_are_versioned_per_league(session: Session) -> None:
    league = _league(session)
    session.add(_snapshot(league.id, version=1))
    session.flush()
    session.add(_snapshot(league.id, version=2, schema_version="2026-27.v1"))
    session.flush()

    assert {s.version for s in league.settings_snapshots} == {1, 2}


def test_a_duplicate_version_for_the_same_league_is_rejected(session: Session) -> None:
    league = _league(session)
    session.add(_snapshot(league.id, version=1))
    session.flush()

    session.add(_snapshot(league.id, version=1))
    with pytest.raises(IntegrityError):
        session.flush()


def test_the_same_version_number_is_reusable_across_different_leagues(session: Session) -> None:
    league_a = _league(session, name="League A")
    league_b = _league(session, name="League B")
    session.add(_snapshot(league_a.id, version=1))
    session.add(_snapshot(league_b.id, version=1))

    session.flush()

    assert {s.league_id for s in session.query(LeagueSettingsSnapshot).all()} == {
        league_a.id,
        league_b.id,
    }


def test_version_must_be_positive(session: Session) -> None:
    league = _league(session)
    session.add(_snapshot(league.id, version=0))

    with pytest.raises(IntegrityError):
        session.flush()


def test_source_payload_sha256_must_be_a_full_length_digest(session: Session) -> None:
    league = _league(session)
    session.add(_snapshot(league.id, source_payload_sha256="deadbeef"))

    with pytest.raises(IntegrityError):
        session.flush()


def test_a_full_length_hex_digest_is_accepted(session: Session) -> None:
    league = _league(session)
    session.add(_snapshot(league.id, source_payload_sha256=_sha256("some-real-payload")))

    session.flush()  # does not raise


def test_a_new_version_does_not_alter_the_previous_row(session: Session) -> None:
    """Immutability by convention: a settings change inserts, never updates.

    This does not enforce immutability at the database layer -- nothing in
    this schema needs to, because the caller contract is "always insert a new
    version" and the test is here to keep that contract visible and to prove
    that doing so actually preserves the prior row untouched.
    """
    league = _league(session)
    session.add(
        _snapshot(
            league.id,
            version=1,
            settings={"trade_deadline": None},
        )
    )
    session.flush()

    session.add(
        _snapshot(
            league.id,
            version=2,
            settings={"trade_deadline": "2027-02-15"},
        )
    )
    session.flush()
    session.expire_all()

    v1, v2 = (
        session.query(LeagueSettingsSnapshot)
        .filter(LeagueSettingsSnapshot.league_id == league.id)
        .order_by(LeagueSettingsSnapshot.version)
        .all()
    )
    assert v1.settings["trade_deadline"] is None
    assert v2.settings["trade_deadline"] == "2027-02-15"


def test_deleting_the_league_cascades_to_its_settings_snapshots(session: Session) -> None:
    league = _league(session)
    session.add(_snapshot(league.id))
    session.flush()

    session.delete(league)
    session.flush()

    assert session.query(LeagueSettingsSnapshot).count() == 0


def test_the_relationship_is_navigable_from_league(session: Session) -> None:
    league = _league(session)
    session.add(_snapshot(league.id, version=1))
    session.add(_snapshot(league.id, version=2))
    session.flush()
    session.expire_all()

    reloaded = session.get(League, league.id)
    assert reloaded is not None
    assert {s.version for s in reloaded.settings_snapshots} == {1, 2}
