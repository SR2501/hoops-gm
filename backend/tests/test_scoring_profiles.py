"""``hoops_gm.scoring.profiles``: derivation, activation, and fail-closed mapping.

Covers the ``scoring-profiles`` backlog unit (docs/backlog.md). Snapshots in
these tests are built through the real production parser
(``parse_official_league_settings``) against a synthetic ``getLeagueInfo``-
shaped payload rather than a hand-built ``LeagueSettingsDocument`` -- that
ties every test to the actual ingestion boundary rather than a parallel
pydantic construction that could silently drift from what production code
produces. The persistence-layer CHECK constraints these tests lean on (ratio
components present, percentage keys must be RATIO, box-score vocabulary,
category-key uniqueness) already have dedicated coverage in ``test_schema.py``
-- duplicated here only where the acceptance surface for *this* unit
specifically calls for it (e.g. proving the builder itself can never produce a
row that would violate them). Portability is not re-tested per-feature here:
the whole suite already runs against both SQLite and a real Postgres instance
(see ``conftest.py``'s ``test_database_url`` fixture and ``ci.yml``), so every
test in this file is exercised on both dialects without anything
dialect-specific written here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import CategoryKind, ScoringType
from hoops_gm.db.models.league import League, LeagueScoringCategory, LeagueScoringProfile
from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot
from hoops_gm.ingest.backfill import derive_scoring_profile, ingest_official_league_settings
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.fantrax_official import (
    FantraxLeagueInfo,
    FantraxOfficialClient,
    parse_league_info,
)
from hoops_gm.ingest.league_settings import parse_official_league_settings
from hoops_gm.scoring.profiles import (
    NINE_CATEGORY_DEFINITIONS,
    NonUnitCategoryWeightError,
    SourceCategory,
    UnsupportedCategoryError,
    UnsupportedScoringFormatError,
    activate_scoring_profile_version,
    build_scoring_profile,
    current_scoring_profile,
    map_source_categories,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


_VERIFIED_SCORING_TYPE = "HEAD_TO_HEAD_ROTI_MULTI_WIN"

#: The exact nine (code, name, abbreviation, weight) tuples observed in a
#: captured Fantrax settings payload
#: (backend/tests/fixtures/fantrax_getleagueinfo_settings_sanitized.json),
#: in that document's own order.
_NINE_CAT_CONFIGS: tuple[tuple[str, str, str, float], ...] = (
    ("INDIVIDUAL_ASSISTS", "Assists", "AST", 1.0),
    ("INDIVIDUAL_BLOCKS", "Blocks", "BLK", 1.0),
    ("INDIVIDUAL_POINTS", "Points", "PTS", 1.0),
    ("INDIVIDUAL_REBOUNDS", "Rebounds", "REB", 1.0),
    ("INDIVIDUAL_STEALS", "Steals", "ST", 1.0),
    ("INDIVIDUAL_THREE_POINTERS_MADE", "Three Pointers Made", "3PTM", 1.0),
    ("INDIVIDUAL_TURNOVERS", "Turnovers", "TO", 1.0),
    ("INDIVIDUAL_FIELD_GOAL_PERCENTAGE", "Field Goal %", "FG%", 1.0),
    ("INDIVIDUAL_FREE_THROW_PERCENTAGE", "Free Throw %", "FT%", 1.0),
)

#: Convenience source-category views of the same nine, for tests exercising
#: ``map_source_categories`` directly without going through a settings
#: document at all.
_NINE_CAT_SOURCE_CATEGORIES = [
    SourceCategory(code=code, abbreviation=abbr, weight=weight, name=name)
    for code, name, abbr, weight in _NINE_CAT_CONFIGS
]


def _league(session: Session, name: str = "Test League", season: str = "2026-27") -> League:
    league = League(name=name, season=season)
    session.add(league)
    session.flush()
    return league


def _scoring_payload(
    *,
    season_year: int = 2026,
    start_date: str = "2026-10-20",
    end_date: str = "2027-03-14",
    categories: Sequence[tuple[str, str, str, float]] | None = _NINE_CAT_CONFIGS,
    raw_scoring_type: str | None = _VERIFIED_SCORING_TYPE,
) -> dict[str, object]:
    """A synthetic ``getLeagueInfo``-shaped payload for exercising the real parser.

    ``categories=None`` omits ``scoringSystem.scoringCategorySettings``
    entirely (an *absent* observation); an empty tuple produces a present-but-
    empty ``configs`` list (expected to fail closed at parse time -- see
    ``_parse_scoring_categories``); ``raw_scoring_type=None`` omits
    ``scoringSystem.type`` (also absent).
    """

    payload: dict[str, object] = {
        "seasonYear": season_year,
        "startDate": start_date,
        "endDate": end_date,
    }
    scoring_system: dict[str, object] = {}
    if raw_scoring_type is not None:
        scoring_system["type"] = raw_scoring_type
    if categories is not None:
        scoring_system["scoringCategorySettings"] = [
            {
                "configs": [
                    {
                        "scoringCategory": {"code": code, "name": name, "shortName": abbr},
                        "weight": weight,
                    }
                    for code, name, abbr, weight in categories
                ]
            }
        ]
    if scoring_system:
        payload["scoringSystem"] = scoring_system
    return payload


def _settings_snapshot(
    session: Session,
    league_id: int,
    version: int = 1,
    *,
    categories: Sequence[tuple[str, str, str, float]] | None = _NINE_CAT_CONFIGS,
    raw_scoring_type: str | None = _VERIFIED_SCORING_TYPE,
) -> LeagueSettingsSnapshot:
    """A persisted snapshot built through the real production parser.

    Ties every test in this file to ``parse_official_league_settings`` rather
    than a hand-built ``LeagueSettingsDocument`` -- see the module docstring.
    """

    document = parse_official_league_settings(
        _scoring_payload(categories=categories, raw_scoring_type=raw_scoring_type),
        source_league_id="league-1",
        capture_ref=f"test-fixture:v{version}",
    )
    snapshot = LeagueSettingsSnapshot(
        league_id=league_id,
        version=version,
        schema_version=str(document.schema_version),
        settings=document.model_dump(mode="json"),
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
    ordered = (
        ("INDIVIDUAL_TURNOVERS", "Turnovers", "TO", 1.0),
        ("INDIVIDUAL_ASSISTS", "Assists", "AST", 1.0),
        ("INDIVIDUAL_POINTS", "Points", "PTS", 1.0),
    )
    snapshot = _settings_snapshot(session, league.id, categories=ordered)

    profile = build_scoring_profile(session, league=league, settings_snapshot=snapshot)

    categories = sorted(profile.categories, key=lambda c: c.display_order)
    assert [c.key for c in categories] == ["to", "ast", "pts"]
    assert [c.display_order for c in categories] == [1, 2, 3]


def test_duplicate_source_category_is_rejected(session: Session) -> None:
    league = _league(session)
    duplicated = (
        ("INDIVIDUAL_POINTS", "Points", "PTS", 1.0),
        ("INDIVIDUAL_POINTS", "Points", "PTS", 1.0),
    )
    snapshot = _settings_snapshot(session, league.id, categories=duplicated)

    with pytest.raises(ValueError, match="duplicate"):
        build_scoring_profile(session, league=league, settings_snapshot=snapshot)

    # Fails closed before anything is persisted -- no orphaned profile row.
    assert session.query(LeagueScoringProfile).count() == 0


def test_unsupported_category_is_rejected(session: Session) -> None:
    """A code outside the observed vocabulary must not be guessed at."""
    league = _league(session)
    unknown = (
        ("INDIVIDUAL_POINTS", "Points", "PTS", 1.0),
        ("INDIVIDUAL_DOUBLE_DOUBLES", "Double-Doubles", "DD2", 1.0),
    )
    snapshot = _settings_snapshot(session, league.id, categories=unknown)

    with pytest.raises(UnsupportedCategoryError):
        build_scoring_profile(session, league=league, settings_snapshot=snapshot)

    assert session.query(LeagueScoringProfile).count() == 0


def test_an_empty_category_list_is_rejected_at_parse_time(session: Session) -> None:
    """Zero categories is the degenerate case of "missing a category" -- all of them.

    A settings document cannot even be constructed with a present-but-empty
    category list (``_parse_scoring_categories`` fails closed at parse time,
    before a snapshot with such a document could ever be persisted), so the
    rejection surfaces from ``parse_official_league_settings`` itself rather
    than from ``build_scoring_profile``.
    """
    league = _league(session)

    with pytest.raises(SourceContractError, match="present but empty"):
        _settings_snapshot(session, league.id, categories=())

    assert session.query(LeagueScoringProfile).count() == 0


def test_missing_scoring_categories_is_rejected(session: Session) -> None:
    """An *absent* scoring-categories observation must also fail closed."""
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id, categories=None)

    with pytest.raises(ValueError, match="no scoring categories"):
        build_scoring_profile(session, league=league, settings_snapshot=snapshot)

    assert session.query(LeagueScoringProfile).count() == 0


# --------------------------------------------------------------------------
# Category config shape drift: every malformed level must fail loudly
# --------------------------------------------------------------------------


def _base_payload() -> dict[str, object]:
    return {"seasonYear": 2026, "startDate": "2026-10-20", "endDate": "2027-03-14"}


def test_a_non_dict_scoring_category_settings_group_fails_closed() -> None:
    """One malformed group must not silently vanish among the valid ones.

    An earlier version of this parser ``continue``d past a non-dict group,
    which would let this exact payload -- one garbage entry alongside a
    perfectly good category -- silently produce a one-category profile
    instead of raising. A missing category is a wrong valuation with no way
    to detect it after the fact, which is exactly why this must be loud.
    """
    payload = _base_payload()
    payload["scoringSystem"] = {
        "type": _VERIFIED_SCORING_TYPE,
        "scoringCategorySettings": [
            "not-a-dict",
            {
                "configs": [
                    {
                        "scoringCategory": {
                            "code": "INDIVIDUAL_POINTS",
                            "name": "Points",
                            "shortName": "PTS",
                        },
                        "weight": 1.0,
                    }
                ]
            },
        ],
    }

    with pytest.raises(
        SourceContractError, match=r"scoringCategorySettings\[0\] must be an object"
    ):
        parse_official_league_settings(
            payload, source_league_id="league-1", capture_ref="test-fixture:drift-group"
        )


def test_a_non_list_configs_value_fails_closed() -> None:
    payload = _base_payload()
    payload["scoringSystem"] = {
        "type": _VERIFIED_SCORING_TYPE,
        "scoringCategorySettings": [{"configs": "not-a-list"}],
    }

    with pytest.raises(
        SourceContractError, match=r"scoringCategorySettings\[0\]\.configs must be a list"
    ):
        parse_official_league_settings(
            payload, source_league_id="league-1", capture_ref="test-fixture:drift-configs"
        )


def test_a_non_dict_config_entry_fails_closed() -> None:
    payload = _base_payload()
    payload["scoringSystem"] = {
        "type": _VERIFIED_SCORING_TYPE,
        "scoringCategorySettings": [{"configs": ["not-a-dict"]}],
    }

    with pytest.raises(
        SourceContractError, match=r"scoringCategorySettings\[0\]\.configs\[0\] must be an object"
    ):
        parse_official_league_settings(
            payload, source_league_id="league-1", capture_ref="test-fixture:drift-config"
        )


def test_a_non_dict_scoring_category_value_fails_closed() -> None:
    payload = _base_payload()
    payload["scoringSystem"] = {
        "type": _VERIFIED_SCORING_TYPE,
        "scoringCategorySettings": [
            {"configs": [{"scoringCategory": "not-a-dict", "weight": 1.0}]}
        ],
    }

    with pytest.raises(SourceContractError, match=r"scoringCategory must be an object"):
        parse_official_league_settings(
            payload, source_league_id="league-1", capture_ref="test-fixture:drift-category"
        )


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
# Category weight: unit weight required, fail closed on anything else
# --------------------------------------------------------------------------


def test_non_unit_category_weight_is_rejected(session: Session) -> None:
    """Weighted categories are not designed yet; a non-unit weight fails closed."""
    league = _league(session)
    weighted = (
        ("INDIVIDUAL_POINTS", "Points", "PTS", 1.0),
        ("INDIVIDUAL_ASSISTS", "Assists", "AST", 1.5),
    )
    snapshot = _settings_snapshot(session, league.id, categories=weighted)

    with pytest.raises(NonUnitCategoryWeightError):
        build_scoring_profile(session, league=league, settings_snapshot=snapshot)

    assert session.query(LeagueScoringProfile).count() == 0


def test_map_source_categories_rejects_non_unit_weight_directly() -> None:
    with pytest.raises(NonUnitCategoryWeightError):
        map_source_categories(
            [SourceCategory(code="INDIVIDUAL_POINTS", abbreviation="PTS", weight=0.5)]
        )


# --------------------------------------------------------------------------
# Scoring type: verified mapping, fail closed on unrecognised/missing
# --------------------------------------------------------------------------


def test_verified_scoring_type_maps_to_h2h_each_category(session: Session) -> None:
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)

    profile = build_scoring_profile(session, league=league, settings_snapshot=snapshot)

    assert profile.scoring_type == ScoringType.H2H_EACH_CATEGORY


def test_unsupported_scoring_type_is_rejected(session: Session) -> None:
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id, raw_scoring_type="SOME_UNKNOWN_FORMAT")

    with pytest.raises(UnsupportedScoringFormatError):
        build_scoring_profile(session, league=league, settings_snapshot=snapshot)

    assert session.query(LeagueScoringProfile).count() == 0


def test_missing_scoring_type_is_rejected(session: Session) -> None:
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id, raw_scoring_type=None)

    with pytest.raises(ValueError, match="no scoring type"):
        build_scoring_profile(session, league=league, settings_snapshot=snapshot)

    assert session.query(LeagueScoringProfile).count() == 0


# --------------------------------------------------------------------------
# scoring_type evidence source_path: must name whichever field actually won
# --------------------------------------------------------------------------


def test_scoring_type_evidence_cites_the_nested_path_when_only_nested_is_present() -> None:
    payload = _base_payload()
    payload["scoringSystem"] = {
        "type": _VERIFIED_SCORING_TYPE,
        "scoringCategorySettings": [
            {
                "configs": [
                    {
                        "scoringCategory": {
                            "code": "INDIVIDUAL_POINTS",
                            "name": "Points",
                            "shortName": "PTS",
                        },
                        "weight": 1.0,
                    }
                ]
            }
        ],
    }

    document = parse_official_league_settings(
        payload, source_league_id="league-1", capture_ref="test-fixture:nested-type"
    )

    assert document.scoring_type.value is not None
    assert document.scoring_type.value.raw_type == _VERIFIED_SCORING_TYPE
    [evidence] = document.scoring_type.evidence
    assert evidence.source_path == "$.scoringSystem.type"


def test_scoring_type_evidence_cites_the_top_level_path_when_it_wins() -> None:
    """Official priority: a top-level ``scoringType`` wins over the nested field.

    Never observed live -- ``scoringSystem.type`` is the only shape this
    adapter has actually captured -- but the parser accepts a top-level
    ``scoringType`` too under official-source precedence rules, and its
    evidence must honestly cite the field that actually won rather than
    always assuming the nested one.
    """
    payload = _base_payload()
    payload["scoringType"] = _VERIFIED_SCORING_TYPE
    payload["scoringSystem"] = {
        "type": "SOME_OTHER_FORMAT_THAT_MUST_LOSE",
        "scoringCategorySettings": [
            {
                "configs": [
                    {
                        "scoringCategory": {
                            "code": "INDIVIDUAL_POINTS",
                            "name": "Points",
                            "shortName": "PTS",
                        },
                        "weight": 1.0,
                    }
                ]
            }
        ],
    }

    document = parse_official_league_settings(
        payload, source_league_id="league-1", capture_ref="test-fixture:top-level-type"
    )

    assert document.scoring_type.value is not None
    assert document.scoring_type.value.raw_type == _VERIFIED_SCORING_TYPE
    [evidence] = document.scoring_type.evidence
    assert evidence.source_path == "$.scoringType"


# --------------------------------------------------------------------------
# Percentage categories: volume-weighted components, never raw percentages
# --------------------------------------------------------------------------


def test_percentage_categories_carry_volume_weighting_components(session: Session) -> None:
    """R9: FG%/FT% must be made/attempted pairs, never a stored raw percentage."""
    league = _league(session)
    snapshot = _settings_snapshot(
        session,
        league.id,
        categories=(
            ("INDIVIDUAL_FIELD_GOAL_PERCENTAGE", "Field Goal %", "FG%", 1.0),
            ("INDIVIDUAL_FREE_THROW_PERCENTAGE", "Free Throw %", "FT%", 1.0),
        ),
    )

    profile = build_scoring_profile(session, league=league, settings_snapshot=snapshot)

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
    snapshot = _settings_snapshot(
        session, league.id, categories=(("INDIVIDUAL_POINTS", "Points", "PTS", 1.0),)
    )
    profile = build_scoring_profile(session, league=league, settings_snapshot=snapshot)

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
        build_scoring_profile(session, league=league_a, settings_snapshot=snapshot_b)


def test_a_stale_settings_snapshot_is_rejected(session: Session) -> None:
    league = _league(session)
    stale = _settings_snapshot(session, league.id, version=1)
    _settings_snapshot(session, league.id, version=2)  # supersedes `stale`

    with pytest.raises(ValueError, match="stale"):
        build_scoring_profile(session, league=league, settings_snapshot=stale)


def test_the_current_settings_snapshot_is_accepted(session: Session) -> None:
    league = _league(session)
    _settings_snapshot(session, league.id, version=1)
    current = _settings_snapshot(session, league.id, version=2)

    profile = build_scoring_profile(session, league=league, settings_snapshot=current)

    assert profile.settings_snapshot_id == current.id
    assert profile.league_id == league.id


# --------------------------------------------------------------------------
# Content-fingerprint idempotency: re-derivation and cross-snapshot A -> B -> A
# --------------------------------------------------------------------------


def test_rederiving_from_an_unchanged_snapshot_returns_the_existing_profile(
    session: Session,
) -> None:
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)

    first = build_scoring_profile(session, league=league, settings_snapshot=snapshot)
    second = build_scoring_profile(session, league=league, settings_snapshot=snapshot)

    assert first.id == second.id
    assert session.query(LeagueScoringProfile).count() == 1


def test_a_to_b_to_a_content_match_across_snapshot_rows_mints_a_new_activatable_version(
    session: Session,
) -> None:
    """Deriving from a *new* snapshot whose content matches an old one mints a
    new version rather than reusing the old row.

    v1 (the full 9-cat content, call it C) and v3 (content byte-identical to
    C in normalized form, but a distinct snapshot row with different capture
    evidence) must produce *distinct* profile versions sharing the same
    category/scoring-type content; v2 (different content C', a
    single-category league) is a third, unrelated version. Reusing profile_a's
    row for v3 would leave it citing the now-superseded v1 snapshot, which
    ``activate_scoring_profile_version`` correctly refuses to activate --
    an unescapable A -> B -> A dead end. Minting a new version citing v3 (the
    current snapshot) has no such problem, and is provably activatable below.
    """
    league = _league(session)

    v1 = _settings_snapshot(session, league.id, version=1)
    profile_a = build_scoring_profile(session, league=league, settings_snapshot=v1)

    v2 = _settings_snapshot(
        session,
        league.id,
        version=2,
        categories=(("INDIVIDUAL_POINTS", "Points", "PTS", 1.0),),
    )
    profile_b = build_scoring_profile(session, league=league, settings_snapshot=v2)
    assert profile_b.id != profile_a.id
    assert profile_b.version == 2

    # v3's rules content is identical to v1's, despite being a distinct
    # snapshot row (different id, different source_payload_sha256/capture
    # evidence) -- content_sha256() deliberately excludes that evidence.
    v3 = _settings_snapshot(session, league.id, version=3)
    profile_c = build_scoring_profile(session, league=league, settings_snapshot=v3)

    assert profile_c.id != profile_a.id
    assert profile_c.version == 3
    assert profile_c.settings_snapshot_id == v3.id
    assert session.query(LeagueScoringProfile).count() == 3

    # Same content as profile_a (scoring type and every category's key,
    # direction, kind and ratio components), but citing the current snapshot.
    assert profile_c.scoring_type == profile_a.scoring_type

    def _content(profile: LeagueScoringProfile) -> list[tuple[str, int, CategoryKind]]:
        ordered = sorted(profile.categories, key=lambda c: c.display_order)
        return [(c.key, c.direction, c.kind) for c in ordered]

    assert _content(profile_c) == _content(profile_a)

    # And, unlike profile_a (now stale against v3), profile_c is activatable.
    activated = activate_scoring_profile_version(session, profile_c)
    assert activated.id == profile_c.id
    assert _active_id(session, league.id) == profile_c.id
    with pytest.raises(ValueError, match="stale"):
        activate_scoring_profile_version(session, profile_a)


# --------------------------------------------------------------------------
# Version activation: A -> B -> A, one active profile per league
# --------------------------------------------------------------------------


def test_a_new_profile_is_created_inactive(session: Session) -> None:
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)

    profile = build_scoring_profile(session, league=league, settings_snapshot=snapshot)

    assert profile.is_active is False
    assert current_scoring_profile(session, league.id) is None


def _active_id(session: Session, league_id: int) -> int | None:
    """``current_scoring_profile(...).id``, narrowed for mypy's benefit."""
    active = current_scoring_profile(session, league_id)
    return active.id if active is not None else None


def test_activation_a_to_b_to_a(session: Session) -> None:
    """A -> B -> A across two named profiles sharing one current snapshot.

    Activation requires ``settings_snapshot`` to be the league's current one
    (see ``activate_scoring_profile_version``'s staleness revalidation), so a
    same-snapshot pair of differently *named* profiles -- not two profiles
    from two different snapshot versions -- is the toggle this exercises.
    """
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)

    profile_a = build_scoring_profile(
        session, league=league, settings_snapshot=snapshot, name="default"
    )
    profile_b = build_scoring_profile(
        session,
        league=league,
        settings_snapshot=snapshot,
        name="alternate",
    )
    assert profile_a.id != profile_b.id
    assert profile_a.version == 1
    assert profile_b.version == 1

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
    assert [c.key for c in profile_a.categories] == [
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


def test_activating_the_already_active_profile_is_a_no_op(session: Session) -> None:
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)
    profile = build_scoring_profile(session, league=league, settings_snapshot=snapshot)

    activate_scoring_profile_version(session, profile)
    activate_scoring_profile_version(session, profile)

    assert _active_id(session, league.id) == profile.id


def test_activation_is_scoped_per_league(session: Session) -> None:
    league_a = _league(session, name="League A")
    league_b = _league(session, name="League B")
    snapshot_a = _settings_snapshot(session, league_a.id)
    snapshot_b = _settings_snapshot(session, league_b.id)

    profile_a = build_scoring_profile(session, league=league_a, settings_snapshot=snapshot_a)
    profile_b = build_scoring_profile(session, league=league_b, settings_snapshot=snapshot_b)

    activate_scoring_profile_version(session, profile_a)
    activate_scoring_profile_version(session, profile_b)

    assert _active_id(session, league_a.id) == profile_a.id
    assert _active_id(session, league_b.id) == profile_b.id


def test_only_one_active_profile_per_league_is_enforced_by_the_database(
    session: Session,
) -> None:
    """Bypassing the activation service must still be caught -- not just convention."""
    league = _league(session)
    v1 = _settings_snapshot(session, league.id, version=1)
    profile_a = build_scoring_profile(session, league=league, settings_snapshot=v1)
    v2 = _settings_snapshot(
        session,
        league.id,
        version=2,
        categories=(("INDIVIDUAL_POINTS", "Points", "PTS", 1.0),),
    )
    profile_b = build_scoring_profile(session, league=league, settings_snapshot=v2)

    profile_a.active_league_id = league.id
    session.flush()

    profile_b.active_league_id = league.id
    with pytest.raises(IntegrityError):
        session.flush()


def test_activation_revalidates_and_rejects_stale_settings(session: Session) -> None:
    """A profile derived from settings the league has since moved past cannot
    be (re)activated -- and a failed activation leaves the prior one untouched.
    """
    league = _league(session)
    v1 = _settings_snapshot(session, league.id, version=1)
    profile_a = build_scoring_profile(session, league=league, settings_snapshot=v1)
    activate_scoring_profile_version(session, profile_a)

    # A new settings version supersedes v1 without profile_a being rebuilt
    # against it -- profile_a's own settings_snapshot is now stale.
    _settings_snapshot(
        session,
        league.id,
        version=2,
        categories=(("INDIVIDUAL_POINTS", "Points", "PTS", 1.0),),
    )

    with pytest.raises(ValueError, match="stale"):
        activate_scoring_profile_version(session, profile_a)

    # The failed activation left profile_a active -- it never touched
    # anything before raising.
    assert _active_id(session, league.id) == profile_a.id


def test_activation_revalidates_and_rejects_an_empty_profile(session: Session) -> None:
    """A profile with no categories cannot be activated, however it came to
    exist -- including by direct ORM manipulation that bypassed the builder
    entirely. A failed activation leaves the prior active profile untouched.
    """
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)
    profile_a = build_scoring_profile(session, league=league, settings_snapshot=snapshot)
    activate_scoring_profile_version(session, profile_a)

    empty_profile = LeagueScoringProfile(
        league_id=league.id,
        name="alternate",
        version=1,
        scoring_type=ScoringType.H2H_EACH_CATEGORY,
        settings_snapshot_id=snapshot.id,
    )
    session.add(empty_profile)
    session.flush()
    assert empty_profile.categories == []

    with pytest.raises(ValueError, match="no scoring categories"):
        activate_scoring_profile_version(session, empty_profile)

    assert _active_id(session, league.id) == profile_a.id


# --------------------------------------------------------------------------
# The full 9-category profile, end to end
# --------------------------------------------------------------------------


def test_the_nine_category_profile_round_trips_from_source_evidence(session: Session) -> None:
    league = _league(session)
    snapshot = _settings_snapshot(session, league.id)

    profile = build_scoring_profile(session, league=league, settings_snapshot=snapshot)

    assert {c.key for c in profile.categories} == set(NINE_CATEGORY_DEFINITIONS)
    negatives = [c.key for c in profile.categories if c.direction == -1]
    assert negatives == ["to"]
    ratios = {c.key for c in profile.categories if c.kind == CategoryKind.RATIO}
    assert ratios == {"fg_pct", "ft_pct"}


# --------------------------------------------------------------------------
# Production seam: real fixture through parse -> import -> derive -> activate
# --------------------------------------------------------------------------


class _StubLeagueSettingsClient(FantraxOfficialClient):
    """Mirrors ``test_league_settings.py``'s stub: a fetch with no transport."""

    def __init__(self, result: FantraxLeagueInfo) -> None:
        self.result = result

    def get_league_info(
        self,
        league_id: str,
        *,
        max_age: timedelta | None = None,
    ) -> FantraxLeagueInfo:
        assert league_id == self.result.league_id
        assert max_age is None
        return self.result


def test_production_seam_derives_and_activates_from_the_real_fixture(session: Session) -> None:
    """Exercises the actual operator path, not just library functions.

    ``parse_league_info`` (the adapter) -> ``ingest_official_league_settings``
    (persists the snapshot) -> ``derive_scoring_profile`` (the new production
    seam in ``ingest/backfill.py``) -> explicit
    ``activate_scoring_profile_version``, all against the real captured
    fixture rather than a synthetic payload.
    """
    league = League(
        name="Production Seam League",
        season="2025-26",
        fantrax_league_id="fixture-league",
    )
    session.add(league)
    session.flush()

    info = parse_league_info(
        load("fantrax_getleagueinfo_settings_sanitized.json"),
        league_id="fixture-league",
        source_payload_sha256="c" * 64,
        source_observed_at=datetime(2026, 8, 18, tzinfo=UTC),
    )
    assert info.settings is not None

    counts = ingest_official_league_settings(
        session,
        fantrax=_StubLeagueSettingsClient(info),
        league=league,
        fantrax_league_id="fixture-league",
    )
    assert counts.created == 1

    profile = derive_scoring_profile(session, league=league)
    assert profile.is_active is False
    assert {c.key for c in profile.categories} == set(NINE_CATEGORY_DEFINITIONS)
    assert profile.scoring_type == ScoringType.H2H_EACH_CATEGORY

    activated = activate_scoring_profile_version(session, profile)
    active = current_scoring_profile(session, league.id)
    assert active is not None
    assert active.id == activated.id

    # Re-deriving without a new snapshot is a no-op -- content idempotency.
    rederived = derive_scoring_profile(session, league=league)
    assert rederived.id == profile.id
