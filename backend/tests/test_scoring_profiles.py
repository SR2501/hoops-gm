"""``hoops_gm.scoring.profiles``: derivation, activation, and fail-closed mapping.

Covers the ``scoring-profiles`` backlog unit (docs/backlog.md). The
persistence-layer CHECK constraints these tests lean on (ratio components
present, percentage keys must be RATIO, box-score vocabulary, category-key
uniqueness) already have dedicated coverage in ``test_schema.py`` --
duplicated here only where the acceptance surface for *this* unit specifically
calls for it (e.g. proving the builder itself can never produce a row that
would violate them). Portability is not re-tested per-feature here: the whole
suite already runs against both SQLite and a real Postgres instance (see
``conftest.py``'s ``test_database_url`` fixture and ``ci.yml``), so every test
in this file is exercised on both dialects without anything dialect-specific
written here.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import CategoryKind
from hoops_gm.db.models.league import League, LeagueScoringCategory, LeagueScoringProfile
from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot
from hoops_gm.scoring.profiles import (
    NINE_CATEGORY_DEFINITIONS,
    SourceCategory,
    UnsupportedCategoryError,
    activate_scoring_profile_version,
    build_scoring_profile,
    current_scoring_profile,
    map_source_categories,
)

#: The exact abbreviations observed in a captured Fantrax settings payload
#: (backend/tests/fixtures/fantrax_getleagueinfo_settings_sanitized.json),
#: in that document's own order.
_NINE_CAT_SOURCE_CATEGORIES = [
    SourceCategory(abbreviation="AST", name="Assists"),
    SourceCategory(abbreviation="BLK", name="Blocks"),
    SourceCategory(abbreviation="PTS", name="Points"),
    SourceCategory(abbreviation="REB", name="Rebounds"),
    SourceCategory(abbreviation="ST", name="Steals"),
    SourceCategory(abbreviation="3PTM", name="3-Pointers Made"),
    SourceCategory(abbreviation="TO", name="Turnovers"),
    SourceCategory(abbreviation="FG%", name="Field Goal Percentage"),
    SourceCategory(abbreviation="FT%", name="Free Throw Percentage"),
]


def _league(session: Session, name: str = "Test League", season: str = "2026-27") -> League:
    league = League(name=name, season=season)
    session.add(league)
    session.flush()
    return league


def _settings_snapshot(
    session: Session, league_id: int, version: int = 1
) -> LeagueSettingsSnapshot:
    snapshot = LeagueSettingsSnapshot(
        league_id=league_id,
        version=version,
        schema_version="2026-27.v1",
        settings={
            "lineup_lock": None,
            "waivers": None,
            "games_caps": None,
            "roster": None,
            "trade_deadline": None,
            "playoff_periods": None,
            "keeper_rules": None,
        },
        source_summary={},
        source_payload_sha256=hashlib.sha256(f"payload-{league_id}-{version}".encode()).hexdigest(),
        observed_at=datetime(2026, 8, 17, tzinfo=UTC),
    )
    session.add(snapshot)
    session.flush()
    return snapshot


# --------------------------------------------------------------------------
# Category mapping: order, duplicates, unsupported categories
# --------------------------------------------------------------------------


def test_category_order_is_preserved_from_source_order(session: Session) -> None:
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)

    ordered = [
        SourceCategory(abbreviation="TO"),
        SourceCategory(abbreviation="AST"),
        SourceCategory(abbreviation="PTS"),
    ]
    profile = build_scoring_profile(
        session, league=league, settings_snapshot=snapshot, source_categories=ordered
    )

    categories = sorted(profile.categories, key=lambda c: c.display_order)
    assert [c.key for c in categories] == ["to", "ast", "pts"]
    assert [c.display_order for c in categories] == [1, 2, 3]


def test_duplicate_source_category_is_rejected(session: Session) -> None:
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)

    duplicated = [SourceCategory(abbreviation="PTS"), SourceCategory(abbreviation="PTS")]
    with pytest.raises(ValueError, match="duplicate"):
        build_scoring_profile(
            session, league=league, settings_snapshot=snapshot, source_categories=duplicated
        )

    # Fails closed before anything is persisted -- no orphaned profile row.
    assert session.query(LeagueScoringProfile).count() == 0


def test_unsupported_category_is_rejected(session: Session) -> None:
    """An abbreviation outside the observed vocabulary must not be guessed at."""
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)

    unknown = [SourceCategory(abbreviation="PTS"), SourceCategory(abbreviation="DD2")]
    with pytest.raises(UnsupportedCategoryError):
        build_scoring_profile(
            session, league=league, settings_snapshot=snapshot, source_categories=unknown
        )

    assert session.query(LeagueScoringProfile).count() == 0


def test_an_empty_category_list_is_rejected(session: Session) -> None:
    """Zero categories is the degenerate case of "missing a category" -- all of them."""
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)

    with pytest.raises(ValueError, match="no scoring categories"):
        build_scoring_profile(
            session, league=league, settings_snapshot=snapshot, source_categories=[]
        )

    assert session.query(LeagueScoringProfile).count() == 0


def test_map_source_categories_is_pure_and_reusable() -> None:
    """The mapping function has no session dependency -- it is pure evidence mapping."""
    definitions = map_source_categories(_NINE_CAT_SOURCE_CATEGORIES)
    assert [d.key for d in definitions] == [
        "ast",
        "blk",
        "pts",
        "reb",
        "stl",
        "fg3m",
        "to",
        "fg_pct",
        "ft_pct",
    ]


# --------------------------------------------------------------------------
# Percentage categories: volume-weighted components, never raw percentages
# --------------------------------------------------------------------------


def test_percentage_categories_carry_volume_weighting_components(session: Session) -> None:
    """R9: FG%/FT% must be made/attempted pairs, never a stored raw percentage."""
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)

    profile = build_scoring_profile(
        session,
        league=league,
        settings_snapshot=snapshot,
        source_categories=[
            SourceCategory(abbreviation="FG%"),
            SourceCategory(abbreviation="FT%"),
        ],
    )

    by_key = {c.key: c for c in profile.categories}
    assert by_key["fg_pct"].kind == CategoryKind.RATIO
    assert by_key["fg_pct"].numerator_stat == "field_goals_made"
    assert by_key["fg_pct"].denominator_stat == "field_goals_attempted"
    assert by_key["ft_pct"].kind == CategoryKind.RATIO
    assert by_key["ft_pct"].numerator_stat == "free_throws_made"
    assert by_key["ft_pct"].denominator_stat == "free_throws_attempted"


def test_missing_makes_or_attempts_is_rejected_at_the_schema_layer(session: Session) -> None:
    """Defense in depth: even bypassing the builder, an incomplete ratio cannot persist.

    The builder itself can never omit a component (the canonical vocabulary
    always supplies both), so this exercises the underlying CHECK constraint
    directly against a profile the builder produced, proving the guarantee
    holds regardless of how a category row is inserted.
    """
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)
    profile = build_scoring_profile(
        session,
        league=league,
        settings_snapshot=snapshot,
        source_categories=[SourceCategory(abbreviation="PTS")],
    )

    session.add(
        LeagueScoringCategory(
            profile_id=profile.id,
            key="fg_pct",
            label="FG%",
            kind=CategoryKind.RATIO,
            numerator_stat="field_goals_made",
            # denominator_stat omitted: makes without attempts is unweightable.
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


# --------------------------------------------------------------------------
# League/season binding and stale-settings rejection
# --------------------------------------------------------------------------


def test_a_settings_snapshot_from_another_league_is_rejected(session: Session) -> None:
    league_a = _league(session, name="League A", season="2026-27")
    league_b = _league(session, name="League B", season="2026-27")
    snapshot_b = _settings_snapshot(session, league_b.id)

    with pytest.raises(ValueError, match="different league"):
        build_scoring_profile(
            session,
            league=league_a,
            settings_snapshot=snapshot_b,
            source_categories=[SourceCategory(abbreviation="PTS")],
        )


def test_a_stale_settings_snapshot_is_rejected(session: Session) -> None:
    league = _league(session)
    stale = _settings_snapshot(session, league.id, version=1)
    _settings_snapshot(session, league.id, version=2)  # supersedes `stale`

    with pytest.raises(ValueError, match="stale"):
        build_scoring_profile(
            session,
            league=league,
            settings_snapshot=stale,
            source_categories=[SourceCategory(abbreviation="PTS")],
        )


def test_the_current_settings_snapshot_is_accepted(session: Session) -> None:
    league = _league(session)
    _settings_snapshot(session, league.id, version=1)
    current = _settings_snapshot(session, league.id, version=2)

    profile = build_scoring_profile(
        session,
        league=league,
        settings_snapshot=current,
        source_categories=[SourceCategory(abbreviation="PTS")],
    )

    assert profile.settings_snapshot_id == current.id
    assert profile.league_id == league.id


# --------------------------------------------------------------------------
# Version activation: A -> B -> A, one active profile per league
# --------------------------------------------------------------------------


def test_a_new_profile_is_created_inactive(session: Session) -> None:
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)

    profile = build_scoring_profile(
        session,
        league=league,
        settings_snapshot=snapshot,
        source_categories=[SourceCategory(abbreviation="PTS")],
    )

    assert profile.is_active is False
    assert current_scoring_profile(session, league.id) is None


def _active_id(session: Session, league_id: int) -> int | None:
    """``current_scoring_profile(...).id``, narrowed for mypy's benefit."""
    active = current_scoring_profile(session, league_id)
    return active.id if active is not None else None


def test_activation_a_to_b_to_a(session: Session) -> None:
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)
    categories = [SourceCategory(abbreviation="PTS")]

    profile_a = build_scoring_profile(
        session, league=league, settings_snapshot=snapshot, source_categories=categories
    )
    profile_b = build_scoring_profile(
        session, league=league, settings_snapshot=snapshot, source_categories=categories
    )
    assert profile_a.version == 1
    assert profile_b.version == 2

    activate_scoring_profile_version(session, profile_a)
    assert _active_id(session, league.id) == profile_a.id

    activate_scoring_profile_version(session, profile_b)
    assert _active_id(session, league.id) == profile_b.id
    session.refresh(profile_a)
    assert profile_a.is_active is False

    # A -> B -> A: reactivating a superseded version is a plain repeat call,
    # not a special case.
    activate_scoring_profile_version(session, profile_a)
    assert _active_id(session, league.id) == profile_a.id
    session.refresh(profile_b)
    assert profile_b.is_active is False

    # Immutability: reactivating A did not alter its persisted content.
    assert profile_a.version == 1
    assert [c.key for c in profile_a.categories] == ["pts"]


def test_activating_the_already_active_profile_is_a_no_op(session: Session) -> None:
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)
    profile = build_scoring_profile(
        session,
        league=league,
        settings_snapshot=snapshot,
        source_categories=[SourceCategory(abbreviation="PTS")],
    )

    activate_scoring_profile_version(session, profile)
    activate_scoring_profile_version(session, profile)

    assert _active_id(session, league.id) == profile.id


def test_activation_is_scoped_per_league(session: Session) -> None:
    league_a = _league(session, name="League A")
    league_b = _league(session, name="League B")
    snapshot_a = _settings_snapshot(session, league_a.id)
    snapshot_b = _settings_snapshot(session, league_b.id)
    categories = [SourceCategory(abbreviation="PTS")]

    profile_a = build_scoring_profile(
        session, league=league_a, settings_snapshot=snapshot_a, source_categories=categories
    )
    profile_b = build_scoring_profile(
        session, league=league_b, settings_snapshot=snapshot_b, source_categories=categories
    )

    activate_scoring_profile_version(session, profile_a)
    activate_scoring_profile_version(session, profile_b)

    assert _active_id(session, league_a.id) == profile_a.id
    assert _active_id(session, league_b.id) == profile_b.id


def test_only_one_active_profile_per_league_is_enforced_by_the_database(
    session: Session,
) -> None:
    """Bypassing the activation service must still be caught -- not just convention."""
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)
    categories = [SourceCategory(abbreviation="PTS")]

    profile_a = build_scoring_profile(
        session, league=league, settings_snapshot=snapshot, source_categories=categories
    )
    profile_b = build_scoring_profile(
        session, league=league, settings_snapshot=snapshot, source_categories=categories
    )

    profile_a.active_league_id = league.id
    session.flush()

    profile_b.active_league_id = league.id
    with pytest.raises(IntegrityError):
        session.flush()


# --------------------------------------------------------------------------
# The full 9-category profile, end to end
# --------------------------------------------------------------------------


def test_the_nine_category_profile_round_trips_from_source_evidence(session: Session) -> None:
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)

    profile = build_scoring_profile(
        session,
        league=league,
        settings_snapshot=snapshot,
        source_categories=_NINE_CAT_SOURCE_CATEGORIES,
    )

    assert {c.key for c in profile.categories} == set(NINE_CATEGORY_DEFINITIONS)
    negatives = [c.key for c in profile.categories if c.direction == -1]
    assert negatives == ["to"]
    ratios = {c.key for c in profile.categories if c.kind == CategoryKind.RATIO}
    assert ratios == {"fg_pct", "ft_pct"}
