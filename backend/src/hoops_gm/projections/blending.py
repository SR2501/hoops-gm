"""Deterministic, versioned blending of imported per-game production rates.

This module is deliberately downstream of ``ingest.projections`` and has no
source client. Its only production inputs are exact, verified
``ProjectionImport`` snapshots released through :func:`release_projection_import`.
Games-played assumptions are in a different table and are never selected here.

Blend profiles and activation state are immutable domain values. They are
caller-owned rather than persisted because the accepted schema has no blend
tables yet; adding those tables is an architecture decision, not a side effect
of defining the smallest honest blending contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import CategoryKind, ExternalSource, ScoringType
from hoops_gm.db.models.league import LeagueScoringCategory, LeagueScoringProfile
from hoops_gm.db.models.projections import Projection, ProjectionImport
from hoops_gm.ingest.projections.profiles import CANONICAL_STAT_FIELDS

type WeightValue = Decimal | Fraction | float | int | str
_PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_COUNTING_CATEGORY_FIELDS: Mapping[str, str] = {
    "pts": "points_per_game",
    "reb": "rebounds_per_game",
    "oreb": "offensive_rebounds_per_game",
    "dreb": "defensive_rebounds_per_game",
    "ast": "assists_per_game",
    "stl": "steals_per_game",
    "blk": "blocks_per_game",
    "to": "turnovers_per_game",
    "pf": "personal_fouls_per_game",
    "fgm": "field_goals_made_per_game",
    "fga": "field_goals_attempted_per_game",
    "fg3m": "three_pointers_made_per_game",
    "fg3a": "three_pointers_attempted_per_game",
    "ftm": "free_throws_made_per_game",
    "fta": "free_throws_attempted_per_game",
}
_SHOOTING_PAIRS: tuple[tuple[str, str], ...] = (
    ("field_goals_made_per_game", "field_goals_attempted_per_game"),
    ("three_pointers_made_per_game", "three_pointers_attempted_per_game"),
    ("free_throws_made_per_game", "free_throws_attempted_per_game"),
)


class ProjectionBlendError(ValueError):
    """Base class for fail-closed projection-blending errors."""


class UnknownProjectionInputError(ProjectionBlendError):
    """An explicitly selected import or source identity does not exist."""


class StaleProjectionInputError(ProjectionBlendError):
    """A released import or scoring profile is no longer current."""


class InvalidBlendProfileError(ProjectionBlendError):
    """Weights, category semantics, or manual inputs are invalid."""


class MissingProjectionDataError(ProjectionBlendError):
    """A positively weighted source lacks a required player/category value."""


class LayerPurityError(ProjectionBlendError):
    """A terminal, market, availability, or learned input tried to flow backward."""


class BlendInputLayer(StrEnum):
    """Declared provenance layer for a blend input.

    Values other than the first two exist only so callers can receive an
    explicit layer-purity rejection instead of having to encode forbidden data
    under a plausible projection label.
    """

    PROJECTION_IMPORT = "projection_import"
    MANUAL_OVERRIDE = "manual_override"
    AVAILABILITY = "availability"
    EXPECTED_GAMES = "expected_games"
    RANKING = "ranking"
    MARKET = "market"
    VALUATION = "valuation"
    RECOMMENDATION = "recommendation"
    MOCK_OUTCOME = "mock_outcome"


class WeightBasis(StrEnum):
    """Why a set of source weights exists."""

    USER_CONFIGURED = "user_configured"
    LEARNED_ACCURACY = "learned_accuracy"
    MARKET_CALIBRATED = "market_calibrated"
    MOCK_CALIBRATED = "mock_calibrated"


@dataclass(frozen=True)
class ReleasedProjectionImport:
    """Immutable import/package lineage handed to the blending worker."""

    import_id: int
    source: ExternalSource
    season: str
    imported_at: datetime
    content_sha256: str
    profile_id: str
    profile_version: str
    profile_definition_sha256: str
    projection_values_sha256: str
    projection_count: int
    assumed_scoring_type: ScoringType | None
    input_layer: BlendInputLayer = BlendInputLayer.PROJECTION_IMPORT


@dataclass(frozen=True)
class ManualProjectionOverride:
    """One auditable replacement for one player's blended category value(s)."""

    override_id: str
    league_id: int
    season: str
    player_id: int
    category_key: str
    values: tuple[tuple[str, WeightValue], ...]
    actor: str
    reason: str
    created_at: datetime
    input_layer: BlendInputLayer = BlendInputLayer.MANUAL_OVERRIDE

    def __post_init__(self) -> None:
        if not self.override_id.strip():
            raise InvalidBlendProfileError("manual override requires a non-empty override_id")
        if not self.actor.strip() or not self.reason.strip():
            raise InvalidBlendProfileError("manual override requires actor and reason provenance")
        if self.created_at.utcoffset() is None:
            raise InvalidBlendProfileError("manual override created_at must be timezone-aware")
        if self.player_id <= 0:
            raise InvalidBlendProfileError("manual override player_id must be positive")
        if not self.values:
            raise InvalidBlendProfileError("manual override requires at least one production value")

        normalized: list[tuple[str, Fraction]] = []
        seen: set[str] = set()
        for field, value in self.values:
            if field in seen:
                raise InvalidBlendProfileError(
                    f"manual override {self.override_id!r} repeats field {field!r}"
                )
            seen.add(field)
            fraction = _as_fraction(value, label=f"manual override field {field}")
            if fraction < 0:
                raise InvalidBlendProfileError(
                    f"manual override field {field!r} must be non-negative"
                )
            normalized.append((field, fraction))
        object.__setattr__(self, "values", tuple(sorted(normalized)))


@dataclass(frozen=True)
class SourceBlendWeight:
    """Raw user configuration and its exact normalized contribution."""

    source: ExternalSource
    raw_weight: Fraction
    normalized_weight: Fraction


@dataclass(frozen=True)
class CategoryBlendWeights:
    category_key: str
    weights: tuple[SourceBlendWeight, ...]


@dataclass(frozen=True)
class ScoringCategoryContract:
    category_key: str
    kind: CategoryKind
    direction: int
    production_fields: tuple[str, ...]


@dataclass(frozen=True)
class BlendProfile:
    """An immutable version of one league-scoped blend configuration."""

    profile_id: str
    name: str
    version: int
    league_id: int
    season: str
    scoring_profile_id: int
    scoring_profile_sha256: str
    scoring_type: ScoringType
    sources: tuple[ReleasedProjectionImport, ...]
    category_contracts: tuple[ScoringCategoryContract, ...]
    category_weights: tuple[CategoryBlendWeights, ...]
    manual_overrides: tuple[ManualProjectionOverride, ...]
    weight_basis: WeightBasis
    content_sha256: str


@dataclass(frozen=True)
class BlendCatalog:
    """Caller-owned immutable profile registry and activation pointers."""

    profiles: tuple[BlendProfile, ...] = ()
    active: tuple[tuple[int, str, str], ...] = ()


@dataclass(frozen=True)
class BlendedCategoryValue:
    category_key: str
    values: tuple[tuple[str, Fraction], ...]
    manual_override_id: str | None


@dataclass(frozen=True)
class BlendedProjection:
    player_id: int
    categories: tuple[BlendedCategoryValue, ...]
    content_sha256: str


@dataclass(frozen=True)
class BlendResult:
    profile_id: str
    profile_content_sha256: str
    projections: tuple[BlendedProjection, ...]
    content_sha256: str


def release_projection_import(
    session: Session,
    *,
    import_id: int,
    source: ExternalSource,
) -> ReleasedProjectionImport:
    """Release one exact current, verified import to a model worker.

    The release adds a digest over the normalized projection rows. That digest
    catches an in-place row edit even though the raw-file hash and mapping
    lineage still look unchanged.
    """

    projection_import = session.get(ProjectionImport, import_id)
    if projection_import is None:
        raise UnknownProjectionInputError(f"unknown projection import id {import_id}")
    if projection_import.source_row.source is not source:
        raise UnknownProjectionInputError(
            f"projection import {import_id} belongs to "
            f"{projection_import.source_row.source.value}, "
            f"not explicitly selected source {source.value}"
        )
    _validate_verified_import(projection_import)
    _assert_import_is_current(session, projection_import)
    rows = _load_projection_rows(session, projection_import)
    values_sha256 = _projection_rows_sha256(rows)
    effective_scoring_type = (
        projection_import.assumed_scoring_type
        if projection_import.assumed_scoring_type is not None
        else projection_import.source_row.assumed_scoring_type
    )
    return ReleasedProjectionImport(
        import_id=projection_import.id,
        source=source,
        season=projection_import.season,
        imported_at=projection_import.imported_at,
        content_sha256=projection_import.content_sha256,
        profile_id=projection_import.profile_id,
        profile_version=projection_import.profile_version,
        profile_definition_sha256=projection_import.profile_definition_sha256,
        projection_values_sha256=values_sha256,
        projection_count=len(rows),
        assumed_scoring_type=effective_scoring_type,
    )


def define_blend_profile(
    session: Session,
    catalog: BlendCatalog,
    *,
    league_id: int,
    name: str,
    scoring_profile_id: int,
    sources: Sequence[ReleasedProjectionImport],
    category_weights: Mapping[str, Mapping[ExternalSource, WeightValue]],
    manual_overrides: Sequence[ManualProjectionOverride] = (),
    weight_basis: WeightBasis = WeightBasis.USER_CONFIGURED,
) -> tuple[BlendCatalog, BlendProfile]:
    """Validate and register an immutable blend profile without activating it."""

    if not _PROFILE_NAME.fullmatch(name):
        raise InvalidBlendProfileError(
            "blend profile name must be 1-64 lowercase letters, digits, underscores, or hyphens"
        )
    if weight_basis is not WeightBasis.USER_CONFIGURED:
        raise LayerPurityError(
            "projection blend weights must be explicit user configuration; "
            f"{weight_basis.value} is not an approved learned weighting path"
        )
    scoring_profile = _active_scoring_profile(
        session, league_id=league_id, scoring_profile_id=scoring_profile_id
    )
    league = scoring_profile.league
    contracts, scoring_sha256 = _scoring_contract(scoring_profile)
    released = tuple(sorted(sources, key=lambda item: item.source.value))
    _validate_source_selection(
        released,
        season=league.season,
        scoring_type=scoring_profile.scoring_type,
    )
    normalized_weights = _normalize_category_weights(
        category_weights,
        contracts=contracts,
        selected_sources=tuple(item.source for item in released),
    )
    overrides = tuple(
        sorted(
            manual_overrides,
            key=lambda item: (item.player_id, item.category_key, item.override_id),
        )
    )
    _validate_manual_overrides(
        overrides,
        league_id=league_id,
        season=league.season,
        contracts=contracts,
    )

    rows_by_source = {
        release.source: _validate_and_load_release(session, release) for release in released
    }
    _validate_complete_cohort(
        rows_by_source,
        contracts=contracts,
        weights=normalized_weights,
        overrides=overrides,
    )
    content_sha256 = _profile_content_sha256(
        name=name,
        league_id=league_id,
        season=league.season,
        scoring_profile_id=scoring_profile.id,
        scoring_profile_sha256=scoring_sha256,
        sources=released,
        contracts=contracts,
        weights=normalized_weights,
        overrides=overrides,
        weight_basis=weight_basis,
    )
    existing = next(
        (
            profile
            for profile in catalog.profiles
            if profile.league_id == league_id
            and profile.name == name
            and profile.content_sha256 == content_sha256
        ),
        None,
    )
    if existing is not None:
        return catalog, existing

    version = (
        max(
            (
                profile.version
                for profile in catalog.profiles
                if profile.league_id == league_id and profile.name == name
            ),
            default=0,
        )
        + 1
    )
    profile = BlendProfile(
        profile_id=f"{name}:v{version}:{content_sha256[:12]}",
        name=name,
        version=version,
        league_id=league_id,
        season=league.season,
        scoring_profile_id=scoring_profile.id,
        scoring_profile_sha256=scoring_sha256,
        scoring_type=scoring_profile.scoring_type,
        sources=released,
        category_contracts=contracts,
        category_weights=normalized_weights,
        manual_overrides=overrides,
        weight_basis=weight_basis,
        content_sha256=content_sha256,
    )
    return replace(catalog, profiles=(*catalog.profiles, profile)), profile


def activate_blend_profile(
    session: Session,
    catalog: BlendCatalog,
    profile: BlendProfile,
) -> BlendCatalog:
    """Return a new catalog with ``profile`` current after full revalidation."""

    registered = next(
        (candidate for candidate in catalog.profiles if candidate.profile_id == profile.profile_id),
        None,
    )
    if registered != profile:
        raise InvalidBlendProfileError("cannot activate an unregistered or altered blend profile")
    _assert_profile_current(session, profile)
    active = {
        (active_league_id, active_name): active_profile_id
        for active_league_id, active_name, active_profile_id in catalog.active
    }
    active[(profile.league_id, profile.name)] = profile.profile_id
    return replace(
        catalog,
        active=tuple(
            (active_league_id, active_name, active_profile_id)
            for (active_league_id, active_name), active_profile_id in sorted(active.items())
        ),
    )


def current_blend_profile(
    catalog: BlendCatalog,
    *,
    league_id: int,
    name: str = "default",
) -> BlendProfile | None:
    """Return the explicitly active profile for one league/name scope."""

    active_id = next(
        (
            profile_id
            for active_league_id, active_name, profile_id in catalog.active
            if active_league_id == league_id and active_name == name
        ),
        None,
    )
    if active_id is None:
        return None
    return next(profile for profile in catalog.profiles if profile.profile_id == active_id)


def blend_active_projections(
    session: Session,
    catalog: BlendCatalog,
    *,
    league_id: int,
    name: str = "default",
) -> BlendResult:
    """Blend the current profile; absence of activation fails closed."""

    profile = current_blend_profile(catalog, league_id=league_id, name=name)
    if profile is None:
        raise InvalidBlendProfileError(
            f"no active blend profile for league {league_id} and name {name!r}"
        )
    return blend_projections(session, profile)


def blend_projections(session: Session, profile: BlendProfile) -> BlendResult:
    """Compute a deterministic per-game blend for a current immutable profile."""

    _assert_profile_current(session, profile)
    rows_by_source = {
        release.source: _validate_and_load_release(session, release) for release in profile.sources
    }
    _validate_complete_cohort(
        rows_by_source,
        contracts=profile.category_contracts,
        weights=profile.category_weights,
        overrides=profile.manual_overrides,
    )
    overrides = {
        (override.player_id, override.category_key): override
        for override in profile.manual_overrides
    }
    weights = {item.category_key: item for item in profile.category_weights}
    player_ids = sorted(next(iter(rows_by_source.values())))
    projections: list[BlendedProjection] = []
    for player_id in player_ids:
        category_values: list[BlendedCategoryValue] = []
        for contract in profile.category_contracts:
            configured = weights[contract.category_key]
            blended_values: list[tuple[str, Fraction]] = []
            for field in contract.production_fields:
                value = sum(
                    (
                        _projection_fraction(rows_by_source[item.source][player_id], field)
                        * item.normalized_weight
                        for item in configured.weights
                    ),
                    start=Fraction(),
                )
                blended_values.append((field, value))
            manual = overrides.get((player_id, contract.category_key))
            if manual is not None:
                values = tuple((field, _require_fraction(value)) for field, value in manual.values)
                override_id: str | None = manual.override_id
            else:
                values = tuple(blended_values)
                override_id = None
            _validate_shooting_values(
                values,
                label=f"player {player_id} category {contract.category_key}",
            )
            category_values.append(
                BlendedCategoryValue(
                    category_key=contract.category_key,
                    values=values,
                    manual_override_id=override_id,
                )
            )
        categories = tuple(category_values)
        projections.append(
            BlendedProjection(
                player_id=player_id,
                categories=categories,
                content_sha256=_sha256(
                    {
                        "player_id": player_id,
                        "categories": [_category_value_payload(value) for value in categories],
                    }
                ),
            )
        )
    output = tuple(projections)
    return BlendResult(
        profile_id=profile.profile_id,
        profile_content_sha256=profile.content_sha256,
        projections=output,
        content_sha256=_sha256(
            {
                "profile_id": profile.profile_id,
                "profile_content_sha256": profile.content_sha256,
                "projections": [
                    {"player_id": projection.player_id, "sha256": projection.content_sha256}
                    for projection in output
                ],
            }
        ),
    )


def _validate_verified_import(projection_import: ProjectionImport) -> None:
    profile = projection_import.profile_version_row
    if not projection_import.profile_verified or not profile.verified:
        raise InvalidBlendProfileError(
            f"projection import {projection_import.id} was not produced by a verified profile"
        )
    if (
        projection_import.season not in profile.verified_seasons
        and "*" not in profile.verified_seasons
    ):
        raise InvalidBlendProfileError(
            f"projection import {projection_import.id} season {projection_import.season!r} "
            "is outside its profile's verified season scope"
        )
    expected = (
        profile.profile_id,
        profile.profile_version,
        profile.definition_sha256,
    )
    actual = (
        projection_import.profile_id,
        projection_import.profile_version,
        projection_import.profile_definition_sha256,
    )
    if actual != expected:
        raise InvalidBlendProfileError(
            f"projection import {projection_import.id} has inconsistent immutable profile lineage"
        )


def _assert_import_is_current(session: Session, projection_import: ProjectionImport) -> None:
    current = session.scalar(
        select(ProjectionImport)
        .where(
            ProjectionImport.source_id == projection_import.source_id,
            ProjectionImport.season == projection_import.season,
        )
        .order_by(ProjectionImport.imported_at.desc(), ProjectionImport.id.desc())
        .limit(1)
    )
    if current is None or current.id != projection_import.id:
        current_id = current.id if current is not None else None
        raise StaleProjectionInputError(
            f"projection import {projection_import.id} is stale; current import is {current_id}"
        )


def _load_projection_rows(
    session: Session, projection_import: ProjectionImport
) -> dict[int, Projection]:
    rows = session.scalars(
        select(Projection)
        .where(Projection.projection_import_id == projection_import.id)
        .order_by(Projection.player_id)
    ).all()
    if not rows:
        raise MissingProjectionDataError(
            f"projection import {projection_import.id} contains no matched projection rows"
        )
    result: dict[int, Projection] = {}
    for row in rows:
        if row.player_id in result:
            raise MissingProjectionDataError(
                f"projection import {projection_import.id} repeats player {row.player_id}"
            )
        if row.season != projection_import.season:
            raise InvalidBlendProfileError(
                f"projection row {row.id} season {row.season!r} does not match import season "
                f"{projection_import.season!r}"
            )
        for field in CANONICAL_STAT_FIELDS:
            value = getattr(row, field)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise InvalidBlendProfileError(
                    f"projection row {row.id} has invalid per-game value {field}={value!r}"
                )
        _validate_projection_shooting_pairs(row)
        result[row.player_id] = row
    return result


def _projection_rows_sha256(rows: Mapping[int, Projection]) -> str:
    return _sha256(
        [
            {
                "player_id": player_id,
                "season": row.season,
                "rates": {
                    field: _canonical_float(getattr(row, field)) for field in CANONICAL_STAT_FIELDS
                },
            }
            for player_id, row in sorted(rows.items())
        ]
    )


def _validate_and_load_release(
    session: Session, release: ReleasedProjectionImport
) -> dict[int, Projection]:
    if release.input_layer is not BlendInputLayer.PROJECTION_IMPORT:
        raise LayerPurityError(
            f"blend source {release.import_id} declares forbidden layer {release.input_layer.value}"
        )
    projection_import = session.get(ProjectionImport, release.import_id)
    if projection_import is None:
        raise UnknownProjectionInputError(
            f"released projection import {release.import_id} no longer exists"
        )
    _validate_verified_import(projection_import)
    _assert_import_is_current(session, projection_import)
    effective_scoring_type = (
        projection_import.assumed_scoring_type
        if projection_import.assumed_scoring_type is not None
        else projection_import.source_row.assumed_scoring_type
    )
    identity = (
        projection_import.source_row.source,
        projection_import.season,
        projection_import.imported_at,
        projection_import.content_sha256,
        projection_import.profile_id,
        projection_import.profile_version,
        projection_import.profile_definition_sha256,
        effective_scoring_type,
    )
    released_identity = (
        release.source,
        release.season,
        release.imported_at,
        release.content_sha256,
        release.profile_id,
        release.profile_version,
        release.profile_definition_sha256,
        release.assumed_scoring_type,
    )
    if identity != released_identity:
        raise StaleProjectionInputError(
            f"projection import {release.import_id} no longer matches its released lineage"
        )
    rows = _load_projection_rows(session, projection_import)
    if len(rows) != release.projection_count:
        raise StaleProjectionInputError(
            f"projection import {release.import_id} row count changed after release"
        )
    if _projection_rows_sha256(rows) != release.projection_values_sha256:
        raise StaleProjectionInputError(
            f"projection import {release.import_id} values changed after release"
        )
    return rows


def _validate_source_selection(
    releases: Sequence[ReleasedProjectionImport],
    *,
    season: str,
    scoring_type: ScoringType,
) -> None:
    if not releases:
        raise InvalidBlendProfileError("a blend profile requires at least one released import")
    import_ids = [release.import_id for release in releases]
    source_ids = [release.source for release in releases]
    if len(import_ids) != len(set(import_ids)):
        raise InvalidBlendProfileError("a blend profile selects the same import more than once")
    if len(source_ids) != len(set(source_ids)):
        raise InvalidBlendProfileError("a blend profile selects more than one import per source")
    for release in releases:
        if release.input_layer is not BlendInputLayer.PROJECTION_IMPORT:
            raise LayerPurityError(
                f"blend source {release.import_id} declares forbidden layer "
                f"{release.input_layer.value}"
            )
        if release.season != season:
            raise InvalidBlendProfileError(
                f"projection import {release.import_id} season {release.season!r} "
                f"does not match league season {season!r}"
            )
        if (
            release.assumed_scoring_type is not None
            and release.assumed_scoring_type is not scoring_type
        ):
            raise InvalidBlendProfileError(
                f"projection import {release.import_id} assumes "
                f"{release.assumed_scoring_type.value}, not target {scoring_type.value}"
            )


def _active_scoring_profile(
    session: Session, *, league_id: int, scoring_profile_id: int
) -> LeagueScoringProfile:
    profile = session.get(LeagueScoringProfile, scoring_profile_id)
    if profile is None:
        raise UnknownProjectionInputError(f"unknown scoring profile id {scoring_profile_id}")
    if profile.league_id != league_id:
        raise InvalidBlendProfileError(
            f"scoring profile {scoring_profile_id} belongs to a different league"
        )
    if profile.active_league_id != league_id:
        raise StaleProjectionInputError(
            f"scoring profile {scoring_profile_id} is not active for league {league_id}"
        )
    return profile


def _scoring_contract(
    scoring_profile: LeagueScoringProfile,
) -> tuple[tuple[ScoringCategoryContract, ...], str]:
    categories = sorted(scoring_profile.categories, key=lambda item: (item.display_order, item.key))
    if not categories:
        raise InvalidBlendProfileError("active scoring profile has no categories")
    if len({category.key for category in categories}) != len(categories):
        raise InvalidBlendProfileError("active scoring profile repeats a category key")
    contracts: list[ScoringCategoryContract] = []
    payload: list[dict[str, object]] = []
    for category in categories:
        fields = _category_production_fields(category)
        contracts.append(
            ScoringCategoryContract(
                category_key=category.key,
                kind=category.kind,
                direction=category.direction,
                production_fields=fields,
            )
        )
        payload.append(
            {
                "key": category.key,
                "kind": category.kind.value,
                "direction": category.direction,
                "point_value": (
                    None if category.point_value is None else str(category.point_value)
                ),
                "numerator_stat": category.numerator_stat,
                "denominator_stat": category.denominator_stat,
                "production_fields": list(fields),
            }
        )
    contract_tuple = tuple(contracts)
    return (
        contract_tuple,
        _sha256(
            {
                "scoring_profile_id": scoring_profile.id,
                "league_id": scoring_profile.league_id,
                "name": scoring_profile.name,
                "version": scoring_profile.version,
                "scoring_type": scoring_profile.scoring_type.value,
                "settings_snapshot_id": scoring_profile.settings_snapshot_id,
                "categories": payload,
            }
        ),
    )


def _category_production_fields(category: LeagueScoringCategory) -> tuple[str, ...]:
    if category.kind is CategoryKind.COUNTING:
        field = _COUNTING_CATEGORY_FIELDS.get(category.key)
        if field is None:
            raise InvalidBlendProfileError(
                f"counting category {category.key!r} has no verified projection-field mapping"
            )
        if category.numerator_stat is not None or category.denominator_stat is not None:
            raise InvalidBlendProfileError(
                f"counting category {category.key!r} unexpectedly declares ratio components"
            )
        return (field,)
    if category.kind is not CategoryKind.RATIO:
        raise InvalidBlendProfileError(
            f"category {category.key!r} has unsupported kind {category.kind!r}"
        )
    if category.numerator_stat is None or category.denominator_stat is None:
        raise InvalidBlendProfileError(
            f"ratio category {category.key!r} is missing made/attempt volume semantics"
        )
    fields = (
        f"{category.numerator_stat}_per_game",
        f"{category.denominator_stat}_per_game",
    )
    unknown = set(fields) - set(CANONICAL_STAT_FIELDS)
    if unknown:
        raise InvalidBlendProfileError(
            f"ratio category {category.key!r} names unsupported production fields {sorted(unknown)}"
        )
    return fields


def _normalize_category_weights(
    configured: Mapping[str, Mapping[ExternalSource, WeightValue]],
    *,
    contracts: Sequence[ScoringCategoryContract],
    selected_sources: tuple[ExternalSource, ...],
) -> tuple[CategoryBlendWeights, ...]:
    expected_categories = {contract.category_key for contract in contracts}
    if set(configured) != expected_categories:
        missing = sorted(expected_categories - set(configured))
        extra = sorted(set(configured) - expected_categories)
        raise InvalidBlendProfileError(
            f"category weights must exactly match active scoring categories; "
            f"missing={missing}, extra={extra}"
        )
    expected_sources = set(selected_sources)
    normalized: list[CategoryBlendWeights] = []
    for contract in contracts:
        source_weights = configured[contract.category_key]
        if set(source_weights) != expected_sources:
            missing_sources = sorted(
                source.value for source in expected_sources - set(source_weights)
            )
            extra_sources = sorted(
                source.value for source in set(source_weights) - expected_sources
            )
            raise InvalidBlendProfileError(
                f"weights for {contract.category_key!r} must name every selected source exactly; "
                f"missing={missing_sources}, extra={extra_sources}"
            )
        raw = {
            source: _as_fraction(value, label=f"{contract.category_key} weight for {source.value}")
            for source, value in source_weights.items()
        }
        if any(value < 0 for value in raw.values()):
            raise InvalidBlendProfileError(
                f"weights for category {contract.category_key!r} must be non-negative"
            )
        total = sum(raw.values(), start=Fraction())
        if total <= 0:
            raise InvalidBlendProfileError(
                f"weights for category {contract.category_key!r} must have a positive sum"
            )
        normalized.append(
            CategoryBlendWeights(
                category_key=contract.category_key,
                weights=tuple(
                    SourceBlendWeight(
                        source=source,
                        raw_weight=raw[source],
                        normalized_weight=raw[source] / total,
                    )
                    for source in sorted(selected_sources, key=lambda item: item.value)
                ),
            )
        )
    if any(
        all(
            next(
                item for item in category.weights if item.source is selected_source
            ).normalized_weight
            == 0
            for category in normalized
        )
        for selected_source in selected_sources
    ):
        raise InvalidBlendProfileError(
            "every selected import must carry positive weight in at least one category"
        )
    return tuple(normalized)


def _validate_manual_overrides(
    overrides: Sequence[ManualProjectionOverride],
    *,
    league_id: int,
    season: str,
    contracts: Sequence[ScoringCategoryContract],
) -> None:
    contract_by_key = {contract.category_key: contract for contract in contracts}
    ids: set[str] = set()
    targets: set[tuple[int, str]] = set()
    for override in overrides:
        if override.input_layer is not BlendInputLayer.MANUAL_OVERRIDE:
            raise LayerPurityError(
                f"manual override {override.override_id!r} declares forbidden layer "
                f"{override.input_layer.value}"
            )
        if override.override_id in ids:
            raise InvalidBlendProfileError(
                f"manual override id {override.override_id!r} is duplicated"
            )
        ids.add(override.override_id)
        target = (override.player_id, override.category_key)
        if target in targets:
            raise InvalidBlendProfileError(
                f"player {override.player_id} category {override.category_key!r} "
                "has more than one manual override"
            )
        targets.add(target)
        if override.league_id != league_id or override.season != season:
            raise InvalidBlendProfileError(
                f"manual override {override.override_id!r} belongs to another league or season"
            )
        contract = contract_by_key.get(override.category_key)
        if contract is None:
            raise InvalidBlendProfileError(
                f"manual override {override.override_id!r} names unknown category "
                f"{override.category_key!r}"
            )
        fields = tuple(field for field, _ in override.values)
        if fields != tuple(sorted(contract.production_fields)):
            raise InvalidBlendProfileError(
                f"manual override {override.override_id!r} must provide exactly "
                f"{sorted(contract.production_fields)}, got {list(fields)}"
            )
        _validate_shooting_values(
            tuple((field, _require_fraction(value)) for field, value in override.values),
            label=f"manual override {override.override_id}",
        )


def _validate_complete_cohort(
    rows_by_source: Mapping[ExternalSource, Mapping[int, Projection]],
    *,
    contracts: Sequence[ScoringCategoryContract],
    weights: Sequence[CategoryBlendWeights],
    overrides: Sequence[ManualProjectionOverride],
) -> None:
    player_sets = {source: set(rows) for source, rows in rows_by_source.items()}
    expected_players = set.union(*player_sets.values())
    for source, players in player_sets.items():
        if players != expected_players:
            missing = sorted(expected_players - players)
            raise MissingProjectionDataError(
                f"source {source.value} is missing selected-cohort players {missing}"
            )
    weight_by_category = {item.category_key: item for item in weights}
    for contract in contracts:
        for item in weight_by_category[contract.category_key].weights:
            if item.normalized_weight == 0:
                continue
            for player_id, row in rows_by_source[item.source].items():
                missing_fields = [
                    field for field in contract.production_fields if getattr(row, field) is None
                ]
                if missing_fields:
                    raise MissingProjectionDataError(
                        f"source {item.source.value} import lacks {missing_fields} for "
                        f"player {player_id} category {contract.category_key!r}; "
                        "weights are never silently renormalized"
                    )
    unknown_override_players = sorted(
        {override.player_id for override in overrides} - expected_players
    )
    if unknown_override_players:
        raise InvalidBlendProfileError(
            f"manual overrides name players outside the complete source cohort "
            f"{unknown_override_players}"
        )


def _assert_profile_current(session: Session, profile: BlendProfile) -> None:
    scoring_profile = _active_scoring_profile(
        session,
        league_id=profile.league_id,
        scoring_profile_id=profile.scoring_profile_id,
    )
    contracts, scoring_sha256 = _scoring_contract(scoring_profile)
    if (
        scoring_profile.league.season != profile.season
        or scoring_profile.scoring_type is not profile.scoring_type
        or contracts != profile.category_contracts
        or scoring_sha256 != profile.scoring_profile_sha256
    ):
        raise StaleProjectionInputError(
            f"blend profile {profile.profile_id} no longer matches active scoring semantics"
        )
    for release in profile.sources:
        _validate_and_load_release(session, release)


def _profile_content_sha256(
    *,
    name: str,
    league_id: int,
    season: str,
    scoring_profile_id: int,
    scoring_profile_sha256: str,
    sources: Sequence[ReleasedProjectionImport],
    contracts: Sequence[ScoringCategoryContract],
    weights: Sequence[CategoryBlendWeights],
    overrides: Sequence[ManualProjectionOverride],
    weight_basis: WeightBasis,
) -> str:
    return _sha256(
        {
            "name": name,
            "league_id": league_id,
            "season": season,
            "scoring_profile_id": scoring_profile_id,
            "scoring_profile_sha256": scoring_profile_sha256,
            "sources": [_release_payload(source) for source in sources],
            "category_contracts": [
                {
                    "category_key": contract.category_key,
                    "kind": contract.kind.value,
                    "direction": contract.direction,
                    "production_fields": list(contract.production_fields),
                }
                for contract in contracts
            ],
            "category_weights": [
                {
                    "category_key": category.category_key,
                    "weights": [
                        {
                            "source": weight.source.value,
                            "raw": _fraction_text(weight.raw_weight),
                            "normalized": _fraction_text(weight.normalized_weight),
                        }
                        for weight in category.weights
                    ],
                }
                for category in weights
            ],
            "manual_overrides": [_override_payload(override) for override in overrides],
            "weight_basis": weight_basis.value,
        }
    )


def _release_payload(release: ReleasedProjectionImport) -> dict[str, object]:
    return {
        "import_id": release.import_id,
        "source": release.source.value,
        "season": release.season,
        "imported_at": release.imported_at.astimezone(UTC).isoformat(),
        "content_sha256": release.content_sha256,
        "profile_id": release.profile_id,
        "profile_version": release.profile_version,
        "profile_definition_sha256": release.profile_definition_sha256,
        "projection_values_sha256": release.projection_values_sha256,
        "projection_count": release.projection_count,
        "assumed_scoring_type": (
            None if release.assumed_scoring_type is None else release.assumed_scoring_type.value
        ),
        "input_layer": release.input_layer.value,
    }


def _override_payload(override: ManualProjectionOverride) -> dict[str, object]:
    return {
        "override_id": override.override_id,
        "league_id": override.league_id,
        "season": override.season,
        "player_id": override.player_id,
        "category_key": override.category_key,
        "values": [
            {"field": field, "value": _fraction_text(_require_fraction(value))}
            for field, value in override.values
        ],
        "actor": override.actor,
        "reason": override.reason,
        "created_at": override.created_at.astimezone(UTC).isoformat(),
        "input_layer": override.input_layer.value,
    }


def _category_value_payload(value: BlendedCategoryValue) -> dict[str, object]:
    return {
        "category_key": value.category_key,
        "values": [
            {"field": field, "value": _fraction_text(field_value)}
            for field, field_value in value.values
        ],
        "manual_override_id": value.manual_override_id,
    }


def _projection_fraction(row: Projection, field: str) -> Fraction:
    value = getattr(row, field)
    if value is None:
        raise MissingProjectionDataError(
            f"projection row {row.id} is missing required field {field!r}"
        )
    return Fraction(str(value))


def _validate_projection_shooting_pairs(row: Projection) -> None:
    _validate_shooting_values(
        tuple(
            (field, Fraction(str(value)))
            for field in CANONICAL_STAT_FIELDS
            if (value := getattr(row, field)) is not None
        ),
        label=f"projection row {row.id}",
    )


def _validate_shooting_values(values: Sequence[tuple[str, Fraction]], *, label: str) -> None:
    by_field = dict(values)
    for made_field, attempted_field in _SHOOTING_PAIRS:
        made = by_field.get(made_field)
        attempted = by_field.get(attempted_field)
        if (made is None) != (attempted is None):
            raise InvalidBlendProfileError(
                f"{label} must preserve complete {made_field}/{attempted_field} volume"
            )
        if made is not None and attempted is not None and made > attempted + Fraction(1, 1000):
            raise InvalidBlendProfileError(
                f"{label} has makes greater than attempts for {made_field}/{attempted_field}"
            )


def _as_fraction(value: WeightValue, *, label: str) -> Fraction:
    if isinstance(value, bool):
        raise InvalidBlendProfileError(f"{label} must be numeric, not boolean")
    try:
        fraction = value if isinstance(value, Fraction) else Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise InvalidBlendProfileError(f"{label} is not a finite numeric value") from exc
    return fraction


def _require_fraction(value: WeightValue) -> Fraction:
    if not isinstance(value, Fraction):
        raise TypeError("normalized domain value is not a Fraction")
    return value


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _canonical_float(value: float | None) -> str | None:
    return None if value is None else format(value, ".17g")


def _sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
