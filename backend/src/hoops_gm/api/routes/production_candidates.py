"""Read-only production ranking for one recorded draft.

The numeric path is intentionally narrow and entirely producer-owned:

``released projection import -> ephemeral identity blend -> frozen z-score``.

Every complete projected player enters the scorer before resolved live draft
holdings are excluded. Historical game-log presence is attached afterwards and
never changes membership, order, or score.

Consistency is detected rather than locked (ADR-014). The handler re-observes
the draft revision, league structure, canonical projection/scoring releases,
and the exact narrow health snapshot before returning. A detected change is the
single retryable refusal. This does not promise detection of every write: a
moved-and-reverted state or a database snapshot that continues to expose an
older transaction can evade the second observation. The promise is a coherent
older payload or a typed conflict, never freshness.

The health read has one definition, reused for both observations. It joins
``player_game_logs.game_id`` to ``nba_games.id`` and filters by the publication's
season, season type, inclusive date window, final-game status, and the candidate
``player_id`` set. Its fingerprint covers those scope fields, candidate IDs,
and each selected log's ``id``, ``player_id``, ``game_id``, ``team_id``,
``nba_game_id``, ``game_date``, and nullable ``seconds_played``. Zero seconds is
therefore a credited row, not a filter. No box-score production, participation,
opportunity denominator, source games-played assumption, or inferred absence is
read.

Canonical ``players.full_name`` and ``nba_teams.abbreviation`` are display
metadata joined by ``players.current_team_id = nba_teams.id``. They are outside
the projection, blend, score, and health fingerprints. A concurrent relabel can
therefore produce a fresher label on the same canonical ``player_id``; it cannot
move a score to another player.

``projection_sources.display_name`` and
``projection_imports.original_filename`` are also descriptive metadata outside
the numeric fingerprints. Unlike player labels, they are joined to the exact
released import/source identity and re-observed with that release before the
response is returned, so a source relabel cannot be mixed into an older release
silently.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from fractions import Fraction
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hoops_gm.api.deps import SessionDep
from hoops_gm.api.schemas import ErrorResponse
from hoops_gm.api.security import require_loopback_host
from hoops_gm.availability.reliability import RELIABILITY_SOURCE_KEY
from hoops_gm.db.lineage import current_refresh
from hoops_gm.db.models.draft import Draft
from hoops_gm.db.models.enums import (
    CategoryKind,
    DraftStatus,
    ExternalSource,
    GameStatus,
    RefreshArtifactType,
    ScoringType,
    SeasonType,
)
from hoops_gm.db.models.identity import NbaTeam, Player
from hoops_gm.db.models.league import League, LeagueScoringProfile
from hoops_gm.db.models.projections import ProjectionImport, ProjectionSource
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog
from hoops_gm.draft import service as draft_service
from hoops_gm.draft.formats import DraftFormatError
from hoops_gm.draft.state import DraftLogError, DraftStateView
from hoops_gm.ingest.projections.profiles import PROJECTION_IMPORT_SOURCES
from hoops_gm.projections.blending import (
    BlendCatalog,
    BlendedProjection,
    BlendProfile,
    BlendResult,
    MissingProjectionDataError,
    ProjectionBlendError,
    ReleasedProjectionImport,
    StaleProjectionInputError,
    UnknownProjectionInputError,
    WeightBasis,
    blend_projections,
    define_blend_profile,
    release_projection_import,
)
from hoops_gm.scoring.profiles import current_scoring_profile
from hoops_gm.valuation.zscore import (
    InvalidZScoreInputError,
    ProductionZScoreResult,
    ReplacementState,
    ScaleStatus,
    score_production_zscores,
)

router = APIRouter(prefix="/drafts", tags=["production-candidates"])

IDENTITY_BLEND_NAME = "production-candidates-identity"
CANONICAL_CATEGORY_KEYS = frozenset(
    {"pts", "reb", "ast", "stl", "blk", "fg3m", "to", "fg_pct", "ft_pct"}
)
RATE_FIELDS = (
    "points_per_game",
    "rebounds_per_game",
    "assists_per_game",
    "steals_per_game",
    "blocks_per_game",
    "turnovers_per_game",
    "three_pointers_made_per_game",
    "field_goals_made_per_game",
    "field_goals_attempted_per_game",
    "free_throws_made_per_game",
    "free_throws_attempted_per_game",
)
HEALTH_FINGERPRINT_ALGORITHM = "production-candidate-game-log-presence-v1"
HEALTH_COUNTING_RULE = "player_game_log_rows_in_window_including_zero_seconds"

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
CategoryKey = Literal["pts", "reb", "ast", "stl", "blk", "fg3m", "to", "fg_pct", "ft_pct"]
ProjectionSourceValue = Literal[
    "basketball_monster",
    "fantasypros",
    "hashtag",
    "darko",
    "manual",
]
SUPPORTED_SOURCE_VALUES = (
    "basketball_monster",
    "fantasypros",
    "hashtag",
    "darko",
    "manual",
)


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LimitationsOut(_ContractModel):
    strategy_included: Literal[False]
    punt_adjustment_included: Literal[False]
    budget_or_affordability_included: Literal[False]
    position_fit_included: Literal[False]
    fantrax_roster_eligibility_included: Literal[False]
    partial_browser_increment: Literal[True]


class ProjectionImportLineageOut(_ContractModel):
    import_id: PositiveInt
    source: ProjectionSourceValue
    season: str
    imported_at: datetime
    content_sha256: Sha256
    profile_id: str
    profile_version: str
    profile_definition_sha256: Sha256
    projection_values_sha256: Sha256
    projection_count: PositiveInt
    assumed_scoring_type: ScoringType | None


class ScoringProfileLineageOut(_ContractModel):
    id: PositiveInt
    version: PositiveInt
    name: str
    scoring_type: ScoringType
    settings_snapshot_id: PositiveInt
    content_sha256: Sha256


class CategoryWeightOut(_ContractModel):
    category_key: CategoryKey
    source: ProjectionSourceValue
    raw_weight: float
    normalized_weight: float


class BlendLineageOut(_ContractModel):
    mode: Literal["ephemeral_identity_single_source"]
    persisted: Literal[False]
    profile_id: str
    version: PositiveInt
    content_sha256: Sha256
    result_content_sha256: Sha256
    weight_basis: Literal["user_configured"]
    manual_override_count: Literal[0]
    category_weights: Annotated[list[CategoryWeightOut], Field(min_length=9, max_length=9)]


class ScoreLineageOut(_ContractModel):
    model_version: str
    input_kind: Literal["production_blend"]
    output_layer: Literal["terminal"]
    aggregation_policy: str
    reference_policy: str
    replacement_policy: str
    scoring_profile_sha256: Sha256
    blend_profile_sha256: Sha256
    blend_result_sha256: Sha256
    content_sha256: Sha256


class LineageOut(_ContractModel):
    projection_import: ProjectionImportLineageOut
    scoring_profile: ScoringProfileLineageOut
    blend: BlendLineageOut
    score: ScoreLineageOut
    availability_model_version: None
    punt_config: None


class ReferenceOut(_ContractModel):
    count: PositiveInt
    player_ids: list[PositiveInt]
    players_sha256: Sha256
    scored_before_draft_exclusion: Literal[True]
    draft_exclusion_policy: Literal["exclude_resolved_holdings_after_full_reference_scoring"]
    resolved_drafted_player_ids: list[PositiveInt]
    excluded_drafted_player_ids: list[PositiveInt]
    drafted_player_ids_outside_reference: list[PositiveInt]
    candidate_count: NonNegativeInt


class ReplacementOut(_ContractModel):
    state: ReplacementState
    team_count: PositiveInt
    roster_size: PositiveInt
    structural_roster_count: PositiveInt
    replacement_ordinal: PositiveInt
    projected_count: PositiveInt
    structural_roster_covered: bool
    structural_roster_shortfall: NonNegativeInt
    replacement_ordinal_shortfall: NonNegativeInt
    replacement_player_id: PositiveInt | None
    replacement_total_z: float | None


class CategoryScaleOut(_ContractModel):
    category_key: CategoryKey
    kind: CategoryKind
    direction: Literal[-1, 1]
    production_fields: list[str]
    reference_mean: float
    population_sd: float
    reference_percentage: float | None
    status: ScaleStatus


class HealthPublicationOut(_ContractModel):
    refresh_id: PositiveInt
    artifact_key: Literal["reliability-observations"]
    source: str | None
    source_version: str | None


class AvailableHealthContextOut(_ContractModel):
    status: Literal["available"]
    reason: None
    season: str
    season_type: SeasonType
    window_start: date
    as_of_date: date
    publication: HealthPublicationOut
    row_source_provenance: Literal["not_recorded"]
    counting_rule: Literal["player_game_log_rows_in_window_including_zero_seconds"]
    observation_rows_sha256: Sha256
    ranking_input: Literal[False]


class UnavailableHealthContextOut(_ContractModel):
    status: Literal["unavailable"]
    reason: Literal["no_attributable_publication"]
    season: None
    season_type: None
    window_start: None
    as_of_date: None
    publication: None
    row_source_provenance: Literal["not_recorded"]
    counting_rule: Literal["player_game_log_rows_in_window_including_zero_seconds"]
    observation_rows_sha256: None
    ranking_input: Literal[False]


HealthContextOut = Annotated[
    AvailableHealthContextOut | UnavailableHealthContextOut,
    Field(discriminator="status"),
]


class ObservedHealthOut(_ContractModel):
    status: Literal["observed"]
    credited_appearances: Annotated[int, Field(gt=0)]


class NoObservationsHealthOut(_ContractModel):
    status: Literal["no_observations"]
    credited_appearances: Literal[0]


class UnknownHealthOut(_ContractModel):
    status: Literal["unknown"]
    credited_appearances: None


CandidateHealthOut = Annotated[
    ObservedHealthOut | NoObservationsHealthOut | UnknownHealthOut,
    Field(discriminator="status"),
]


class ProductionRatesOut(_ContractModel):
    points_per_game: float
    rebounds_per_game: float
    assists_per_game: float
    steals_per_game: float
    blocks_per_game: float
    turnovers_per_game: float
    three_pointers_made_per_game: float
    field_goals_made_per_game: float
    field_goals_attempted_per_game: float
    free_throws_made_per_game: float
    free_throws_attempted_per_game: float


class CategoryComponentOut(_ContractModel):
    category_key: CategoryKey
    kind: CategoryKind
    direction: Literal[-1, 1]
    production_fields: dict[str, float]
    transformed_value: float
    z_score: float


class ProductionCandidateOut(_ContractModel):
    player_id: PositiveInt
    full_name: str
    team_abbreviation: str | None
    projection_content_sha256: Sha256
    ordinal: PositiveInt
    rates_per_game: ProductionRatesOut
    components: Annotated[list[CategoryComponentOut], Field(min_length=9, max_length=9)]
    total_z: float
    value_above_replacement: float | None
    health: CandidateHealthOut


class ProductionCandidatesResponse(_ContractModel):
    draft_id: PositiveInt
    league_id: PositiveInt
    season: str
    source: ProjectionSourceValue
    source_display_name: str
    source_original_filename: str | None
    draft_status: DraftStatus
    draft_last_sequence: NonNegativeInt
    generated_at: datetime
    claim: Literal["projection_relative_production_ranking"]
    value_scope: Literal["production_only"]
    availability_included: Literal[False]
    calibration_status: Literal["not_established_for_current_selected_source"]
    source_freshness: Literal["not_established_beyond_current_import"]
    limitations: LimitationsOut
    lineage: LineageOut
    reference: ReferenceOut
    replacement: ReplacementOut
    category_scales: Annotated[list[CategoryScaleOut], Field(min_length=9, max_length=9)]
    health_context: HealthContextOut
    candidates: list[ProductionCandidateOut]


@dataclass(frozen=True, slots=True)
class _DraftSnapshot:
    league_id: int
    team_count: int
    roster_size: int
    status: DraftStatus
    last_sequence: int
    resolved_drafted_player_ids: tuple[int, ...]
    unresolved_holding_count: int


@dataclass(frozen=True, slots=True)
class _LeagueSnapshot:
    season: str
    team_count: int
    roster_size: int


@dataclass(frozen=True, slots=True)
class _ScoringProfileMetadata:
    id: int
    version: int
    name: str
    scoring_type: ScoringType
    settings_snapshot_id: int
    content_sha256: str


@dataclass(frozen=True, slots=True)
class _ProjectionDisplayMetadata:
    import_id: int
    source: ExternalSource
    display_name: str
    original_filename: str | None


@dataclass(frozen=True, slots=True)
class _HealthPublication:
    refresh_id: int
    artifact_key: str
    source: str | None
    source_version: str | None


@dataclass(frozen=True, slots=True)
class _HealthObservationSnapshot:
    status: Literal["available", "unavailable"]
    season: str | None
    season_type: SeasonType | None
    window_start: date | None
    as_of_date: date | None
    publication: _HealthPublication | None
    observation_rows_sha256: str | None
    appearances: tuple[tuple[int, int | None], ...]


@dataclass(frozen=True, slots=True)
class _HealthRow:
    log_id: int
    player_id: int
    game_id: int
    team_id: int
    nba_game_id: str
    game_date: date
    seconds_played: int | None


class _HealthEvidenceError(ValueError):
    """Published observation metadata cannot support the bounded health slot."""


class _ResponseAssemblyError(ValueError):
    """Producer outputs cannot be mapped to the approved response without invention."""


def _error(status_code: int, code: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"X-Bridge-Error": code},
    )


def _snapshot_conflict(detail: str) -> HTTPException:
    return _error(409, "production_candidates_inconsistent_snapshot", detail)


def _draft_snapshot(state: DraftStateView, draft: Draft) -> _DraftSnapshot:
    resolved_ids = tuple(
        sorted(
            {
                holding.player_id
                for participant in state.participants
                for holding in participant.holdings
                if holding.player_id is not None
            }
        )
    )
    return _DraftSnapshot(
        league_id=draft.league_id,
        team_count=draft.team_count,
        roster_size=draft.roster_size,
        status=state.status,
        last_sequence=state.last_sequence,
        resolved_drafted_player_ids=resolved_ids,
        unresolved_holding_count=state.unresolved_player_count,
    )


def _load_draft_snapshot(session: Session, draft_id: int) -> tuple[Draft, _DraftSnapshot] | None:
    draft = draft_service.load_draft(session, draft_id)
    if draft is None:
        return None
    state = draft_service.load_state(session, draft)
    return draft, _draft_snapshot(state, draft)


def _league_snapshot(league: League) -> _LeagueSnapshot | None:
    if league.team_count is None or league.roster_size is None:
        return None
    return _LeagueSnapshot(
        season=league.season,
        team_count=league.team_count,
        roster_size=league.roster_size,
    )


def _current_import_id(session: Session, *, source: ExternalSource, season: str) -> int | None:
    return session.scalar(
        select(ProjectionImport.id)
        .join(ProjectionSource, ProjectionSource.id == ProjectionImport.source_id)
        .where(
            ProjectionSource.source == source,
            ProjectionImport.season == season,
        )
        .order_by(ProjectionImport.imported_at.desc(), ProjectionImport.id.desc())
        .limit(1)
    )


def _identity_blend_profile(
    session: Session,
    *,
    scoring_profile: LeagueScoringProfile,
    release: ReleasedProjectionImport,
) -> BlendProfile:
    category_keys = tuple(
        category.key
        for category in sorted(
            scoring_profile.categories,
            key=lambda category: (category.display_order, category.key),
        )
    )
    _, profile = define_blend_profile(
        session,
        BlendCatalog(),
        league_id=scoring_profile.league_id,
        name=IDENTITY_BLEND_NAME,
        scoring_profile_id=scoring_profile.id,
        sources=(release,),
        category_weights={
            category_key: {release.source: Fraction(1)} for category_key in category_keys
        },
        manual_overrides=(),
        weight_basis=WeightBasis.USER_CONFIGURED,
    )
    return profile


def _projection_display_metadata(
    session: Session,
    *,
    release: ReleasedProjectionImport,
) -> _ProjectionDisplayMetadata:
    row = session.execute(
        select(
            ProjectionImport.id.label("import_id"),
            ProjectionSource.source,
            ProjectionSource.display_name,
            ProjectionImport.original_filename,
        )
        .join(ProjectionSource, ProjectionSource.id == ProjectionImport.source_id)
        .where(ProjectionImport.id == release.import_id)
    ).one_or_none()
    if row is None:
        raise _ResponseAssemblyError(
            f"released projection import {release.import_id} has no stored display provenance"
        )
    if row.import_id != release.import_id or row.source != release.source:
        raise _ResponseAssemblyError(
            f"stored display provenance for projection import {release.import_id} "
            "does not match its released source identity"
        )
    return _ProjectionDisplayMetadata(
        import_id=row.import_id,
        source=row.source,
        display_name=row.display_name,
        original_filename=row.original_filename,
    )


def _non_negative_int(summary: Mapping[str, object], key: str) -> int:
    value = summary.get(key)
    if type(value) is not int or value < 0:
        raise _HealthEvidenceError(
            f"published reliability summary field {key!r} must be a non-negative integer"
        )
    return value


def _summary_text(summary: Mapping[str, object], key: str) -> str:
    value = summary.get(key)
    if not isinstance(value, str) or not value:
        raise _HealthEvidenceError(
            f"published reliability summary field {key!r} must be a non-empty string"
        )
    return value


def _health_rows_sha256(
    *,
    candidate_player_ids: tuple[int, ...],
    season: str,
    season_type: SeasonType,
    window_start: date,
    as_of_date: date,
    rows: Sequence[_HealthRow],
) -> str:
    payload = {
        "algorithm": HEALTH_FINGERPRINT_ALGORITHM,
        "scope": {
            "season": season,
            "season_type": season_type.value,
            "window_start": window_start.isoformat(),
            "as_of_date": as_of_date.isoformat(),
            "candidate_player_ids": list(candidate_player_ids),
        },
        "rows": [
            {
                "log_id": row.log_id,
                "player_id": row.player_id,
                "game_id": row.game_id,
                "team_id": row.team_id,
                "nba_game_id": row.nba_game_id,
                "game_date": row.game_date.isoformat(),
                "seconds_played": row.seconds_played,
            }
            for row in rows
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _read_health_snapshot(
    session: Session,
    *,
    candidate_player_ids: Sequence[int],
) -> _HealthObservationSnapshot:
    candidate_ids = tuple(sorted(set(candidate_player_ids)))
    publication = current_refresh(
        session,
        RefreshArtifactType.SOURCE,
        artifact_key=RELIABILITY_SOURCE_KEY,
    )
    if publication is None:
        return _HealthObservationSnapshot(
            status="unavailable",
            season=None,
            season_type=None,
            window_start=None,
            as_of_date=None,
            publication=None,
            observation_rows_sha256=None,
            appearances=tuple((player_id, None) for player_id in candidate_ids),
        )

    season = publication.season
    if season is None:
        raise _HealthEvidenceError(
            f"current {RELIABILITY_SOURCE_KEY} publication is not season-scoped"
        )
    summary = publication.summary
    if not isinstance(summary, Mapping):
        raise _HealthEvidenceError(
            f"current {RELIABILITY_SOURCE_KEY} publication summary is not an object"
        )
    if summary.get("claim") != "descriptive direct observations":
        raise _HealthEvidenceError(
            f"current {RELIABILITY_SOURCE_KEY} publication has no attributable observation claim"
        )
    try:
        season_type = SeasonType(_summary_text(summary, "season_type"))
        window_start = date.fromisoformat(_summary_text(summary, "window_start"))
        as_of_date = date.fromisoformat(_summary_text(summary, "as_of_date"))
    except (TypeError, ValueError) as exc:
        raise _HealthEvidenceError(
            f"current {RELIABILITY_SOURCE_KEY} publication has an invalid observation scope: {exc}"
        ) from exc
    if window_start > as_of_date:
        raise _HealthEvidenceError(
            f"current {RELIABILITY_SOURCE_KEY} publication ends before it starts"
        )

    expected_final_games = _non_negative_int(summary, "final_games")
    expected_game_logs = _non_negative_int(summary, "player_game_logs")
    scope_filters = (
        NbaGame.season == season,
        NbaGame.season_type == season_type,
        NbaGame.status == GameStatus.FINAL,
        NbaGame.game_date.between(window_start, as_of_date),
    )
    actual_final_games = session.scalar(select(func.count(NbaGame.id)).where(*scope_filters))
    actual_game_logs = session.scalar(
        select(func.count(PlayerGameLog.id))
        .join(NbaGame, NbaGame.id == PlayerGameLog.game_id)
        .where(*scope_filters)
    )
    if actual_final_games != expected_final_games or actual_game_logs != expected_game_logs:
        raise _HealthEvidenceError(
            f"current {RELIABILITY_SOURCE_KEY} publication counts do not match its "
            f"persisted window: expected final_games={expected_final_games}, "
            f"player_game_logs={expected_game_logs}; observed final_games={actual_final_games}, "
            f"player_game_logs={actual_game_logs}"
        )

    selected_rows: tuple[_HealthRow, ...]
    if candidate_ids:
        rows = session.execute(
            select(
                PlayerGameLog.id.label("log_id"),
                PlayerGameLog.player_id,
                PlayerGameLog.game_id,
                PlayerGameLog.team_id,
                NbaGame.nba_game_id,
                NbaGame.game_date,
                PlayerGameLog.seconds_played,
            )
            .join(NbaGame, NbaGame.id == PlayerGameLog.game_id)
            .where(*scope_filters, PlayerGameLog.player_id.in_(candidate_ids))
            .order_by(
                NbaGame.game_date,
                NbaGame.nba_game_id,
                PlayerGameLog.player_id,
                PlayerGameLog.id,
            )
        ).all()
        selected_rows = tuple(
            _HealthRow(
                log_id=row.log_id,
                player_id=row.player_id,
                game_id=row.game_id,
                team_id=row.team_id,
                nba_game_id=row.nba_game_id,
                game_date=row.game_date,
                seconds_played=row.seconds_played,
            )
            for row in rows
        )
    else:
        selected_rows = ()

    counts = Counter(row.player_id for row in selected_rows)
    return _HealthObservationSnapshot(
        status="available",
        season=season,
        season_type=season_type,
        window_start=window_start,
        as_of_date=as_of_date,
        publication=_HealthPublication(
            refresh_id=publication.id,
            artifact_key=publication.artifact_key,
            source=publication.source or None,
            source_version=publication.version or None,
        ),
        observation_rows_sha256=_health_rows_sha256(
            candidate_player_ids=candidate_ids,
            season=season,
            season_type=season_type,
            window_start=window_start,
            as_of_date=as_of_date,
            rows=selected_rows,
        ),
        appearances=tuple((player_id, counts[player_id]) for player_id in candidate_ids),
    )


def _health_context_out(snapshot: _HealthObservationSnapshot) -> HealthContextOut:
    if snapshot.status == "unavailable":
        return UnavailableHealthContextOut(
            status="unavailable",
            reason="no_attributable_publication",
            season=None,
            season_type=None,
            window_start=None,
            as_of_date=None,
            publication=None,
            row_source_provenance="not_recorded",
            counting_rule=HEALTH_COUNTING_RULE,
            observation_rows_sha256=None,
            ranking_input=False,
        )
    if (
        snapshot.season is None
        or snapshot.season_type is None
        or snapshot.window_start is None
        or snapshot.as_of_date is None
        or snapshot.publication is None
        or snapshot.observation_rows_sha256 is None
    ):
        raise _ResponseAssemblyError("available health context is missing published scope")
    return AvailableHealthContextOut(
        status="available",
        reason=None,
        season=snapshot.season,
        season_type=snapshot.season_type,
        window_start=snapshot.window_start,
        as_of_date=snapshot.as_of_date,
        publication=HealthPublicationOut(
            refresh_id=snapshot.publication.refresh_id,
            artifact_key="reliability-observations",
            source=snapshot.publication.source,
            source_version=snapshot.publication.source_version,
        ),
        row_source_provenance="not_recorded",
        counting_rule=HEALTH_COUNTING_RULE,
        observation_rows_sha256=snapshot.observation_rows_sha256,
        ranking_input=False,
    )


def _candidate_health(
    snapshot: _HealthObservationSnapshot, *, player_id: int
) -> CandidateHealthOut:
    appearances = dict(snapshot.appearances).get(player_id)
    if snapshot.status == "unavailable":
        if appearances is not None:
            raise _ResponseAssemblyError("unavailable health context carried an appearance count")
        return UnknownHealthOut(status="unknown", credited_appearances=None)
    if appearances is None:
        raise _ResponseAssemblyError(
            f"available health context omitted candidate player {player_id}"
        )
    if appearances == 0:
        return NoObservationsHealthOut(status="no_observations", credited_appearances=0)
    return ObservedHealthOut(status="observed", credited_appearances=appearances)


def _player_labels(
    session: Session, *, player_ids: Sequence[int]
) -> dict[int, tuple[str, str | None]]:
    rows = session.execute(
        select(Player.id, Player.full_name, NbaTeam.abbreviation)
        .outerjoin(NbaTeam, NbaTeam.id == Player.current_team_id)
        .where(Player.id.in_(tuple(player_ids)))
    ).all()
    labels = {
        player_id: (full_name, team_abbreviation)
        for player_id, full_name, team_abbreviation in rows
    }
    if set(labels) != set(player_ids):
        missing = sorted(set(player_ids) - set(labels))
        raise _ResponseAssemblyError(
            f"canonical display metadata is missing projected player ids {missing}"
        )
    return labels


def _projection_rates(projection: BlendedProjection) -> ProductionRatesOut:
    fields: dict[str, Fraction] = {}
    for category in projection.categories:
        for field, value in category.values:
            previous = fields.setdefault(field, value)
            if previous != value:
                raise _ResponseAssemblyError(
                    f"player {projection.player_id} repeats field {field!r} with two values"
                )
    if set(fields) != set(RATE_FIELDS):
        missing = sorted(set(RATE_FIELDS) - set(fields))
        unexpected = sorted(set(fields) - set(RATE_FIELDS))
        raise _ResponseAssemblyError(
            f"player {projection.player_id} scoring-rate fields disagree with the wire contract; "
            f"missing={missing}, unexpected={unexpected}"
        )
    return ProductionRatesOut(**{field: float(fields[field]) for field in RATE_FIELDS})


def _validate_score_identity(
    *,
    score: ProductionZScoreResult,
    league: _LeagueSnapshot,
    blend_profile: BlendProfile,
    blend_result: BlendResult,
) -> None:
    if (
        score.value_scope != "production_only"
        or score.availability_included
        or score.input_kind != "production_blend"
        or score.output_layer.value != "terminal"
        or score.league_id != blend_profile.league_id
        or score.season != league.season
        or score.team_count != league.team_count
        or score.roster_size != league.roster_size
        or score.scoring_profile_id != blend_profile.scoring_profile_id
        or score.scoring_profile_sha256 != blend_profile.scoring_profile_sha256
        or score.blend_profile_id != blend_profile.profile_id
        or score.blend_profile_content_sha256 != blend_profile.content_sha256
        or score.blend_result_content_sha256 != blend_result.content_sha256
        or score.benchmark_id is not None
        or score.benchmark_input_season is not None
        or score.benchmark_input_content_sha256 is not None
    ):
        raise _ResponseAssemblyError(
            "the frozen score result does not describe the selected production blend"
        )


def _candidate_rows(
    *,
    score: ProductionZScoreResult,
    blend_result: BlendResult,
    drafted_player_ids: frozenset[int],
    labels: Mapping[int, tuple[str, str | None]],
    health: _HealthObservationSnapshot,
) -> list[ProductionCandidateOut]:
    projections = {projection.player_id: projection for projection in blend_result.projections}
    scores = {row.player_id: row for row in score.scores}
    if set(projections) != set(score.reference_player_ids) or set(scores) != set(
        score.reference_player_ids
    ):
        raise _ResponseAssemblyError(
            "blend projections, score rows, and reference player ids do not describe one cohort"
        )

    scale_order = tuple(scale.category_key for scale in score.category_scales)
    if (
        len(scale_order) != len(CANONICAL_CATEGORY_KEYS)
        or set(scale_order) != CANONICAL_CATEGORY_KEYS
    ):
        raise _ResponseAssemblyError(
            f"score category keys {scale_order!r} are not the canonical nine-category set"
        )
    scales = {scale.category_key: scale for scale in score.category_scales}
    candidates: list[ProductionCandidateOut] = []
    for scored in score.scores:
        if scored.player_id in drafted_player_ids:
            continue
        component_order = tuple(component.category_key for component in scored.category_components)
        if component_order != scale_order:
            raise _ResponseAssemblyError(
                f"player {scored.player_id} component order differs from the score scales"
            )
        full_name, team_abbreviation = labels[scored.player_id]
        projection = projections[scored.player_id]
        candidates.append(
            ProductionCandidateOut(
                player_id=scored.player_id,
                full_name=full_name,
                team_abbreviation=team_abbreviation,
                projection_content_sha256=projection.content_sha256,
                ordinal=scored.ordinal,
                rates_per_game=_projection_rates(projection),
                components=[
                    CategoryComponentOut(
                        category_key=component.category_key,
                        kind=scales[component.category_key].kind,
                        direction=scales[component.category_key].direction,
                        production_fields={
                            field: float(value) for field, value in component.production_fields
                        },
                        transformed_value=component.transformed_value,
                        z_score=component.z_score,
                    )
                    for component in scored.category_components
                ],
                total_z=scored.total_z,
                value_above_replacement=scored.value_above_replacement,
                health=_candidate_health(health, player_id=scored.player_id),
            )
        )
    return candidates


def _scoring_metadata(
    scoring_profile: LeagueScoringProfile, blend_profile: BlendProfile
) -> _ScoringProfileMetadata:
    return _ScoringProfileMetadata(
        id=scoring_profile.id,
        version=scoring_profile.version,
        name=scoring_profile.name,
        scoring_type=scoring_profile.scoring_type,
        settings_snapshot_id=scoring_profile.settings_snapshot_id,
        content_sha256=blend_profile.scoring_profile_sha256,
    )


def _assert_snapshot_stable(
    session: Session,
    *,
    draft_id: int,
    source: ExternalSource,
    initial_draft: _DraftSnapshot,
    initial_league: _LeagueSnapshot,
    initial_release: ReleasedProjectionImport,
    initial_source_metadata: _ProjectionDisplayMetadata,
    initial_blend_profile: BlendProfile,
    initial_health: _HealthObservationSnapshot,
    candidate_player_ids: Sequence[int],
) -> None:
    """Best-effort second observation; it never supplies response values."""

    session.expire_all()
    try:
        draft_read = _load_draft_snapshot(session, draft_id)
    except (DraftLogError, DraftFormatError) as exc:
        raise _snapshot_conflict(
            f"recorded draft {draft_id} became unreadable while candidates were assembled"
        ) from exc
    if draft_read is None:
        raise _snapshot_conflict(
            f"recorded draft {draft_id} disappeared while candidates were assembled"
        )
    draft, current_draft = draft_read
    if current_draft != initial_draft:
        raise _snapshot_conflict(f"recorded draft {draft_id} moved while candidates were assembled")

    league = session.get(League, draft.league_id)
    if league is None or _league_snapshot(league) != initial_league:
        raise _snapshot_conflict(
            f"league structure or season moved while draft {draft_id} candidates were assembled"
        )

    scoring_profile = current_scoring_profile(session, draft.league_id)
    if scoring_profile is None:
        raise _snapshot_conflict(
            f"active scoring profile moved while draft {draft_id} candidates were assembled"
        )
    try:
        current_release = release_projection_import(
            session,
            import_id=initial_release.import_id,
            source=source,
        )
        current_source_metadata = _projection_display_metadata(
            session,
            release=current_release,
        )
        current_blend_profile = _identity_blend_profile(
            session,
            scoring_profile=scoring_profile,
            release=current_release,
        )
        current_health = _read_health_snapshot(
            session,
            candidate_player_ids=candidate_player_ids,
        )
    except (ProjectionBlendError, _HealthEvidenceError, _ResponseAssemblyError) as exc:
        raise _snapshot_conflict(
            f"projection, source-display, scoring, or observation evidence moved while "
            f"draft {draft_id} candidates were assembled"
        ) from exc
    if (
        current_release != initial_release
        or current_source_metadata != initial_source_metadata
        or current_blend_profile != initial_blend_profile
        or current_health != initial_health
    ):
        raise _snapshot_conflict(
            f"projection, source-display, scoring, or observation evidence moved while "
            f"draft {draft_id} candidates were assembled"
        )


@router.get(
    "/{draft_id}/production-candidates",
    response_model=ProductionCandidatesResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse, "description": "Unprocessable Content"},
    },
    summary="Projection-relative production candidates for one recorded draft",
)
def get_production_candidates(
    draft_id: Annotated[int, Path(gt=0)],
    source: Annotated[
        str,
        Query(json_schema_extra={"enum": list(SUPPORTED_SOURCE_VALUES)}),
    ],
    session: SessionDep,
    request: Request,
) -> ProductionCandidatesResponse:
    require_loopback_host(
        request,
        error_code="production_candidates_local_only",
        detail="Production candidates are only served to the local machine.",
    )
    try:
        selected_source = ExternalSource(source)
    except ValueError as exc:
        raise _error(
            400,
            "production_candidates_source_unsupported",
            f"{source!r} is not a supported isolated projection-import namespace",
        ) from exc
    if selected_source not in PROJECTION_IMPORT_SOURCES:
        raise _error(
            400,
            "production_candidates_source_unsupported",
            f"{source!r} is not a supported isolated projection-import namespace",
        )

    try:
        draft_read = _load_draft_snapshot(session, draft_id)
    except (DraftLogError, DraftFormatError) as exc:
        raise _error(
            409,
            "production_candidates_draft_state_refused",
            f"recorded draft {draft_id} cannot be derived: {exc}",
        ) from exc
    if draft_read is None:
        raise _error(
            404,
            "production_candidates_draft_not_found",
            f"no recorded draft {draft_id}",
        )
    draft, draft_snapshot = draft_read
    if draft_snapshot.unresolved_holding_count:
        raise _error(
            409,
            "production_candidates_draft_identity_incomplete",
            f"recorded draft {draft_id} has {draft_snapshot.unresolved_holding_count} "
            "live holding(s) without canonical player ids; refusing to guess which projected "
            "players are already drafted",
        )

    league = session.get(League, draft.league_id)
    if league is None:
        raise _error(
            409,
            "production_candidates_draft_state_refused",
            f"recorded draft {draft_id} names missing league {draft.league_id}",
        )
    league_snapshot = _league_snapshot(league)
    if league_snapshot is None:
        raise _error(
            409,
            "production_candidates_league_structure_mismatch",
            f"league {league.id} does not state a complete team count and roster size",
        )
    if (
        league_snapshot.team_count != draft_snapshot.team_count
        or league_snapshot.roster_size != draft_snapshot.roster_size
    ):
        raise _error(
            409,
            "production_candidates_league_structure_mismatch",
            f"recorded draft {draft_id} froze {draft_snapshot.team_count} teams x "
            f"{draft_snapshot.roster_size} roster slots, while league {league.id} now states "
            f"{league_snapshot.team_count} x {league_snapshot.roster_size}; budget is not "
            "part of this comparison",
        )

    import_id = _current_import_id(
        session,
        source=selected_source,
        season=league_snapshot.season,
    )
    if import_id is None:
        raise _error(
            409,
            "production_candidates_source_not_imported",
            f"no {selected_source.value} projection import exists for season "
            f"{league_snapshot.season!r}",
        )
    scoring_profile = current_scoring_profile(session, league.id)
    if scoring_profile is None:
        raise _error(
            409,
            "production_candidates_scoring_profile_unavailable",
            f"league {league.id} has no active scoring profile",
        )

    try:
        release = release_projection_import(
            session,
            import_id=import_id,
            source=selected_source,
        )
        blend_profile = _identity_blend_profile(
            session,
            scoring_profile=scoring_profile,
            release=release,
        )
        blend_result = blend_projections(session, blend_profile)
        score = score_production_zscores(
            league=league,
            blend_profile=blend_profile,
            blend_result=blend_result,
        )
    except MissingProjectionDataError as exc:
        raise _error(
            409,
            "production_candidates_incomplete_production",
            str(exc),
        ) from exc
    except (UnknownProjectionInputError, StaleProjectionInputError) as exc:
        raise _snapshot_conflict(
            "Projection or scoring evidence moved before the candidate cohort was complete."
        ) from exc
    except (ProjectionBlendError, InvalidZScoreInputError) as exc:
        raise _error(
            409,
            "production_candidates_input_evidence_refused",
            str(exc),
        ) from exc

    try:
        _validate_score_identity(
            score=score,
            league=league_snapshot,
            blend_profile=blend_profile,
            blend_result=blend_result,
        )
        source_metadata = _projection_display_metadata(session, release=release)
        reference_ids = score.reference_player_ids
        drafted_ids = frozenset(draft_snapshot.resolved_drafted_player_ids)
        candidate_ids = tuple(
            row.player_id for row in score.scores if row.player_id not in drafted_ids
        )
        health = _read_health_snapshot(
            session,
            candidate_player_ids=candidate_ids,
        )
        labels = _player_labels(session, player_ids=reference_ids)
        candidates = _candidate_rows(
            score=score,
            blend_result=blend_result,
            drafted_player_ids=drafted_ids,
            labels=labels,
            health=health,
        )
        if tuple(candidate.player_id for candidate in candidates) != candidate_ids:
            raise _ResponseAssemblyError(
                "candidate response order differs from the scorer's undrafted ordinal order"
            )
    except _HealthEvidenceError as exc:
        raise _error(
            409,
            "production_candidates_input_evidence_refused",
            str(exc),
        ) from exc
    except _ResponseAssemblyError as exc:
        raise _error(
            409,
            "production_candidates_input_evidence_refused",
            str(exc),
        ) from exc

    _assert_snapshot_stable(
        session,
        draft_id=draft_id,
        source=selected_source,
        initial_draft=draft_snapshot,
        initial_league=league_snapshot,
        initial_release=release,
        initial_source_metadata=source_metadata,
        initial_blend_profile=blend_profile,
        initial_health=health,
        candidate_player_ids=candidate_ids,
    )

    scoring_metadata = _scoring_metadata(scoring_profile, blend_profile)
    reference_set = frozenset(reference_ids)
    excluded_ids = [player_id for player_id in reference_ids if player_id in drafted_ids]
    outside_ids = sorted(drafted_ids - reference_set)
    replacement = score.replacement
    return ProductionCandidatesResponse(
        draft_id=draft_id,
        league_id=league.id,
        season=league_snapshot.season,
        source=selected_source.value,
        source_display_name=source_metadata.display_name,
        source_original_filename=source_metadata.original_filename,
        draft_status=draft_snapshot.status,
        draft_last_sequence=draft_snapshot.last_sequence,
        generated_at=datetime.now(UTC),
        claim="projection_relative_production_ranking",
        value_scope="production_only",
        availability_included=False,
        calibration_status="not_established_for_current_selected_source",
        source_freshness="not_established_beyond_current_import",
        limitations=LimitationsOut(
            strategy_included=False,
            punt_adjustment_included=False,
            budget_or_affordability_included=False,
            position_fit_included=False,
            fantrax_roster_eligibility_included=False,
            partial_browser_increment=True,
        ),
        lineage=LineageOut(
            projection_import=ProjectionImportLineageOut(
                import_id=release.import_id,
                source=release.source.value,
                season=release.season,
                imported_at=release.imported_at,
                content_sha256=release.content_sha256,
                profile_id=release.profile_id,
                profile_version=release.profile_version,
                profile_definition_sha256=release.profile_definition_sha256,
                projection_values_sha256=release.projection_values_sha256,
                projection_count=release.projection_count,
                assumed_scoring_type=release.assumed_scoring_type,
            ),
            scoring_profile=ScoringProfileLineageOut(
                id=scoring_metadata.id,
                version=scoring_metadata.version,
                name=scoring_metadata.name,
                scoring_type=scoring_metadata.scoring_type,
                settings_snapshot_id=scoring_metadata.settings_snapshot_id,
                content_sha256=scoring_metadata.content_sha256,
            ),
            blend=BlendLineageOut(
                mode="ephemeral_identity_single_source",
                persisted=False,
                profile_id=blend_profile.profile_id,
                version=blend_profile.version,
                content_sha256=blend_profile.content_sha256,
                result_content_sha256=blend_result.content_sha256,
                weight_basis="user_configured",
                manual_override_count=0,
                category_weights=[
                    CategoryWeightOut(
                        category_key=category.category_key,
                        source=weight.source.value,
                        raw_weight=float(weight.raw_weight),
                        normalized_weight=float(weight.normalized_weight),
                    )
                    for category in blend_profile.category_weights
                    for weight in category.weights
                ],
            ),
            score=ScoreLineageOut(
                model_version=score.model_version,
                input_kind=score.input_kind,
                output_layer=score.output_layer.value,
                aggregation_policy=score.aggregation_policy,
                reference_policy=score.reference_policy,
                replacement_policy=replacement.policy,
                scoring_profile_sha256=blend_profile.scoring_profile_sha256,
                blend_profile_sha256=blend_profile.content_sha256,
                blend_result_sha256=blend_result.content_sha256,
                content_sha256=score.content_sha256,
            ),
            availability_model_version=None,
            punt_config=None,
        ),
        reference=ReferenceOut(
            count=score.reference_count,
            player_ids=list(reference_ids),
            players_sha256=score.reference_player_fingerprint,
            scored_before_draft_exclusion=True,
            draft_exclusion_policy=("exclude_resolved_holdings_after_full_reference_scoring"),
            resolved_drafted_player_ids=list(draft_snapshot.resolved_drafted_player_ids),
            excluded_drafted_player_ids=excluded_ids,
            drafted_player_ids_outside_reference=outside_ids,
            candidate_count=len(candidates),
        ),
        replacement=ReplacementOut(
            state=replacement.state,
            team_count=score.team_count,
            roster_size=score.roster_size,
            structural_roster_count=replacement.structural_roster_count,
            replacement_ordinal=replacement.required_ordinal,
            projected_count=replacement.projected_count,
            structural_roster_covered=replacement.structural_roster_covered,
            structural_roster_shortfall=replacement.structural_roster_shortfall,
            replacement_ordinal_shortfall=replacement.replacement_ordinal_shortfall,
            replacement_player_id=replacement.replacement_player_id,
            replacement_total_z=replacement.replacement_total_z,
        ),
        category_scales=[
            CategoryScaleOut(
                category_key=scale.category_key,
                kind=scale.kind,
                direction=scale.direction,
                production_fields=list(scale.production_fields),
                reference_mean=scale.reference_mean,
                population_sd=scale.population_sd,
                reference_percentage=scale.reference_percentage,
                status=scale.status,
            )
            for scale in score.category_scales
        ],
        health_context=_health_context_out(health),
        candidates=candidates,
    )
