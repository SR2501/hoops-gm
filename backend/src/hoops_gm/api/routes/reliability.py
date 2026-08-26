"""Descriptive durability evidence for one season, over the wire.

``compute_reliability_scorecards`` has existed and been correct for a while
and no route carried it, so five quantities on the reliability screen were
computed and unexposed. This is that route.

**Read-only, and that shapes the whole design.** The reliability computation
is a two-step contract: ``publish_reliability_cohorts`` *writes* the exact
observation and derivation cohort a run may use, and
``compute_reliability_scorecards`` refuses anything that is not that published
cohort. A GET that published its own claim would be a write on a read, and —
worse — it could never refuse, because it would be checking its own homework.
So this route reads the claim back out of ``refresh_runs`` and refuses when
nothing has published one. ``hoops_gm.dev.publish_reliability_evidence`` is
the publisher.

**The season is the endpoint's, not the caller's** (:data:`EVIDENCE_SEASON`).
The 2026-27 season has no played games until late October, which is after
draft day, so every reliability figure that means anything before then reads
last season. Making that a query parameter would let a caller ask for a season
with no evidence and get a refusal that looks like a bug, and would let two
screens disagree about which season "durability" meant. **The season is named
in the response** rather than left to be inferred: a durability figure whose
season is ambiguous is the ``gameEt`` shape — a value that is perfectly
well-formed and means something other than what the reader assumes.

**Two measured costs, before this sits behind a poll.** On the owner's
2025-26 store (1,230 final games, 26,651 game logs, 43,037 participation
rows) one request computes 596 scorecards in **~3.1s**, because
``compute_reliability_scorecards`` re-fingerprints the entire snapshot to
prove the rows still match the published claim. That is the price of the
guarantee, not an inefficiency to be cached away, and it means this endpoint
is a page load rather than a poll. And on SQLite the lineage scope locks are
a write reservation, so those ~3s hold the database-wide writer — the same
inherited limit ``schedule_grid`` documents.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Final

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.api.deps import SessionDep
from hoops_gm.api.schemas import ErrorResponse
from hoops_gm.api.security import require_loopback_host
from hoops_gm.availability.reliability import (
    RELIABILITY_DERIVATION_KEY,
    RELIABILITY_SOURCE_KEY,
    SCHEDULE_KEY,
    PlayerReliabilityScorecard,
    RateEvidence,
    ReliabilityCohortClaim,
    ReliabilityInputError,
    ReliabilityRun,
    StaleReliabilityCohortError,
    compute_reliability_scorecards,
)
from hoops_gm.db.lineage import current_refresh
from hoops_gm.db.models.enums import RefreshArtifactType, SeasonType
from hoops_gm.db.models.identity import Player

router = APIRouter(prefix="/reliability", tags=["reliability"])

#: The season this endpoint reports durability evidence for.
#:
#: A constant rather than a query parameter, and a governance decision rather
#: than a tuning knob — see the module docstring. It goes stale the moment
#: enough 2026-27 games have been played to prefer them, which is a judgement
#: about how much evidence is enough and therefore the owner's; there is no
#: rule here that could make the change on its own, so it is written where a
#: reader will find it rather than derived from a clock.
EVIDENCE_SEASON: Final = "2025-26"


class ObservedRateEvidence(BaseModel):
    """Direct play/non-play observations. Never a completeness claim.

    ``observed_play_rate`` is *of the games we directly observed*, and the
    denominator is ``observed_opportunities``, not the team's scheduled games.
    A missing participation row is not an absence — under R35 the ledger is
    observation-only — so ``opportunity_coverage`` is always ``null`` and
    ``coverage_status`` always says the coverage is incomplete. Both fields
    are carried rather than omitted precisely so a consumer cannot mistake
    this for a games-played rate.

    **The per-observation id tuples the in-process dataclass carries are
    deliberately not on the wire.** ``RateEvidence`` holds every contributing
    ``player_game_logs`` and ``player_participation`` row id; across a full
    season cohort that is ~70,000 integers, and shipping them would make the
    response an order of magnitude larger for evidence no screen renders. The
    counts below are the same evidence at the resolution a reader uses. A
    consumer needing the individual rows should ask for a separate
    per-player evidence route rather than have this one carry them for
    everybody.
    """

    direct_play: int
    direct_non_play: int
    explicit_unknown: int
    observed_opportunities: int
    observed_play_rate: float | None
    observed_non_play_rate: float | None
    coverage_status: str
    opportunity_coverage: None = Field(
        default=None,
        description="Always null: the participation ledger cannot state how many "
        "opportunities were observed, and a number here would be invented.",
    )


class MonthlyRateEvidenceModel(BaseModel):
    """One calendar month of the same evidence. No slope or direction is fitted."""

    month: date
    evidence: ObservedRateEvidence


class AvailabilityEvidenceModel(BaseModel):
    overall: ObservedRateEvidence
    monthly_trend: list[MonthlyRateEvidenceModel]
    back_to_back: ObservedRateEvidence


class DistributionSummaryModel(BaseModel):
    """Dispersion over played games only.

    ``observed_games`` counts played games, so this says nothing about
    availability and must not be read as if it did (ADR-002). The percentile
    probabilities are echoed from the config that produced the numbers so a
    reader knows which quantiles the bounds are.
    """

    observed_games: int
    lower_percentile_probability: float
    upper_percentile_probability: float
    mean: float | None
    sample_standard_deviation: float | None
    lower_percentile: float | None
    upper_percentile: float | None


class MinutesConsistencyModel(BaseModel):
    distribution_minutes: DistributionSummaryModel
    coefficient_of_variation: float | None


class RatioBaselineModel(BaseModel):
    """The cohort made/attempted baseline a percentage category is scored against."""

    made: int
    attempted: int
    rate: float | None


class CategoryConsistencyModel(BaseModel):
    """One scoring category's game-to-game dispersion.

    ``unit`` distinguishes the two kinds and is not decoration. A counting
    category is in raw counts; a percentage category is in
    ``volume_weighted_impact`` — made minus the cohort rate times attempts —
    because a 90% free-throw shooter on one attempt has had no impact, and
    dispersion of the raw percentage would rank him as the most volatile
    player in the league. A consumer that plots the two on one axis is
    plotting two different quantities.
    """

    category: str
    unit: str
    distribution: DistributionSummaryModel
    ratio_baseline: RatioBaselineModel | None


class ProductionConsistencyModel(BaseModel):
    played_games: int
    minutes: MinutesConsistencyModel
    categories: list[CategoryConsistencyModel]


class ReliabilityLineageModel(BaseModel):
    """Exactly which cohort produced these numbers.

    Every version here is the one the run was *verified* against, not the one
    it asked for: ``compute_reliability_scorecards`` refuses a claim that no
    longer matches the persisted rows, so a 200 means these four labels
    described the store at the moment of computation.
    """

    season: str
    season_type: str
    window_start: date
    as_of_date: date
    schedule_version: str
    schedule_refreshed_at: datetime
    source_version: str
    derivation_version: str
    computed_at: datetime


class PlayerReliabilityScorecardModel(BaseModel):
    """One player's evidence, with the name needed to render it.

    ``player_name`` is resolved here rather than left to the caller because
    there is nowhere else to get it. At the time this shipped the only route
    carrying player names was ``/leagues/{league_id}/projections/current``,
    which is league-scoped, and the owner's store has zero leagues — so a
    consumer holding 596 ``player_id`` integers had no way to turn any of them
    into a person. An endpoint whose output cannot be rendered is not exposed
    in any sense that matters.

    It is ``str | None`` rather than ``str`` because the join can legitimately
    miss: a scorecard is keyed on a ``player_game_logs`` row, and nothing in
    the schema guarantees the ``players`` row still exists. A missing name is
    reported as null rather than backfilled with the id in string form, which
    would be a placeholder indistinguishable from a real name downstream.
    """

    player_id: int
    player_name: str | None
    availability: AvailabilityEvidenceModel
    production: ProductionConsistencyModel


class ReliabilityCohortCounts(BaseModel):
    """The population the scorecards were computed from.

    Carried so a reader can tell "this player has no back-to-back evidence"
    apart from "this store has almost nothing in it" without a second request.
    """

    scorecards: int
    scheduled_team_games: int
    schedule_context_team_games: int
    final_games: int
    player_game_logs: int
    participation_rows: int


class ReliabilityScorecardsResponse(BaseModel):
    """One immutable descriptive cohort.

    ``season`` is the season the evidence is *from*. It is not necessarily the
    season being played, and a consumer rendering these numbers beside a
    2026-27 roster must say so — see :data:`EVIDENCE_SEASON`.

    This is descriptive only. There is no grade, no rank, no projected games
    played and no value, by design (ADR-009): those are ``quant``'s, and a
    single composite number here would be read as a prediction the
    participation ledger cannot support.
    """

    season: str
    season_type: str
    lineage: ReliabilityLineageModel
    counts: ReliabilityCohortCounts
    scorecards: list[PlayerReliabilityScorecardModel]


def _error(status_code: int, code: str, detail: str) -> HTTPException:
    """Raise inside the app's error contract.

    ``X-Bridge-Error`` is read off the exception by ``app.py``'s handler and
    returned as ``ErrorResponse.error``; it is not a response header. The name
    is a legacy of the bridge routes that introduced the transport.
    """

    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"X-Bridge-Error": code},
    )


def published_claim(session: Session, *, season: str) -> ReliabilityCohortClaim:
    """Rebuild the claim a publisher registered, without publishing one.

    This is the one place in the codebase that reads
    ``publish_reliability_cohorts``' summary block back, and reading a
    producer's summary from a consumer is precisely how ``schedule_grid``
    once made itself permanently unavailable — it hand-rolled a reader against
    flat keys the producer never wrote. The protection there was to have one
    canonical reader; here the producer lives in ``quant``'s module and this
    reader does not, so the protection is instead an exact round-trip test:
    ``test_the_published_claim_is_read_back_exactly`` asserts that this
    function returns the identical ``ReliabilityCohortClaim`` that
    ``publish_reliability_cohorts`` returned. If the producer renames a
    summary key or changes what it stores, that test fails rather than this
    route quietly serving a claim shaped from defaults.

    Raises ``HTTPException``: this is a route-layer reader and its failures
    are route-layer refusals.
    """

    versions: dict[RefreshArtifactType, str] = {}
    summary: Mapping[str, object] | None = None
    for artifact_type, artifact_key in (
        (RefreshArtifactType.SCHEDULE, SCHEDULE_KEY),
        (RefreshArtifactType.SOURCE, RELIABILITY_SOURCE_KEY),
        (RefreshArtifactType.MODEL, RELIABILITY_DERIVATION_KEY),
    ):
        run = current_refresh(session, artifact_type, artifact_key=artifact_key, season=season)
        if run is None:
            raise _error(
                409,
                "reliability_not_published",
                f"season {season!r} has no current {artifact_type.value}:{artifact_key} cohort; "
                "publish reliability evidence for this store before reading it "
                "(python -m hoops_gm.dev.publish_reliability_evidence)",
            )
        versions[artifact_type] = run.version
        if artifact_type is RefreshArtifactType.SOURCE:
            summary = run.summary if isinstance(run.summary, Mapping) else None

    if summary is None:
        raise _error(
            409,
            "reliability_incomplete_evidence",
            f"the current {RELIABILITY_SOURCE_KEY} refresh for season {season!r} has a "
            "malformed summary: it is not an object",
        )
    try:
        season_type = SeasonType(_text(summary, "season_type"))
        window_start = date.fromisoformat(_text(summary, "window_start"))
        as_of_date = date.fromisoformat(_text(summary, "as_of_date"))
    except (KeyError, TypeError, ValueError) as exc:
        raise _error(
            409,
            "reliability_incomplete_evidence",
            f"the current {RELIABILITY_SOURCE_KEY} refresh for season {season!r} does not state "
            f"the cohort it published: {exc}",
        ) from exc

    return ReliabilityCohortClaim(
        season=season,
        season_type=season_type,
        window_start=window_start,
        as_of_date=as_of_date,
        schedule_version=versions[RefreshArtifactType.SCHEDULE],
        source_version=versions[RefreshArtifactType.SOURCE],
        derivation_version=versions[RefreshArtifactType.MODEL],
    )


def _text(summary: Mapping[str, object], key: str) -> str:
    value = summary[key]
    if not isinstance(value, str):
        raise TypeError(f"{key!r} is {type(value).__name__}, not a string")
    return value


def _rate(evidence: RateEvidence) -> ObservedRateEvidence:
    return ObservedRateEvidence(
        direct_play=evidence.direct_play,
        direct_non_play=evidence.direct_non_play,
        explicit_unknown=evidence.explicit_unknown,
        observed_opportunities=evidence.observed_opportunities,
        observed_play_rate=evidence.observed_play_rate,
        observed_non_play_rate=evidence.observed_non_play_rate,
        coverage_status=evidence.coverage_status,
        opportunity_coverage=evidence.opportunity_coverage,
    )


def _scorecard(
    card: PlayerReliabilityScorecard, names: Mapping[int, str]
) -> PlayerReliabilityScorecardModel:
    production = card.production
    return PlayerReliabilityScorecardModel(
        player_id=card.player_id,
        player_name=names.get(card.player_id),
        availability=AvailabilityEvidenceModel(
            overall=_rate(card.availability.overall),
            monthly_trend=[
                MonthlyRateEvidenceModel(month=row.month, evidence=_rate(row.evidence))
                for row in card.availability.monthly_trend
            ],
            back_to_back=_rate(card.availability.back_to_back),
        ),
        production=ProductionConsistencyModel(
            played_games=production.played_games,
            minutes=MinutesConsistencyModel(
                distribution_minutes=DistributionSummaryModel(
                    **vars(production.minutes.distribution_minutes)
                ),
                coefficient_of_variation=production.minutes.coefficient_of_variation,
            ),
            categories=[
                CategoryConsistencyModel(
                    category=category.category,
                    unit=category.unit,
                    distribution=DistributionSummaryModel(**vars(category.distribution)),
                    ratio_baseline=(
                        None
                        if category.ratio_baseline is None
                        else RatioBaselineModel(**vars(category.ratio_baseline))
                    ),
                )
                for category in production.categories
            ],
        ),
    )


def _response(run: ReliabilityRun, names: Mapping[int, str]) -> ReliabilityScorecardsResponse:
    lineage = run.lineage
    return ReliabilityScorecardsResponse(
        season=lineage.season,
        season_type=lineage.season_type.value,
        lineage=ReliabilityLineageModel(
            season=lineage.season,
            season_type=lineage.season_type.value,
            window_start=lineage.window_start,
            as_of_date=lineage.as_of_date,
            schedule_version=lineage.schedule_version,
            schedule_refreshed_at=lineage.schedule_refreshed_at,
            source_version=lineage.source_version,
            derivation_version=lineage.derivation_version,
            computed_at=lineage.computed_at,
        ),
        counts=ReliabilityCohortCounts(
            scorecards=len(run.scorecards),
            scheduled_team_games=run.scheduled_team_games,
            schedule_context_team_games=run.schedule_context_team_games,
            final_games=run.final_games,
            player_game_logs=run.player_game_logs,
            participation_rows=run.participation_rows,
        ),
        scorecards=[_scorecard(card, names) for card in run.scorecards],
    )


def _player_names(session: Session, run: ReliabilityRun) -> Mapping[int, str]:
    """Names for exactly the players in ``run``, in one query.

    Restricted to the scorecard ids rather than loading the whole ``players``
    table: the store this serves holds every NBA player ever ingested, while a
    single season's cohort is ~600 of them.
    """

    ids = {card.player_id for card in run.scorecards}
    if not ids:
        return {}
    rows = session.execute(select(Player.id, Player.full_name).where(Player.id.in_(ids))).all()
    return {player_id: full_name for player_id, full_name in rows if full_name}


@router.get(
    "/scorecards",
    response_model=ReliabilityScorecardsResponse,
    responses={
        403: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    summary="Descriptive durability evidence for the evidence season",
)
def get_reliability_scorecards(
    session: SessionDep,
    request: Request,
) -> ReliabilityScorecardsResponse:
    require_loopback_host(
        request,
        error_code="reliability_local_only",
        detail="Reliability evidence is only served to the local machine.",
    )
    claim = published_claim(session, season=EVIDENCE_SEASON)
    try:
        run = compute_reliability_scorecards(session, claim=claim)
    except StaleReliabilityCohortError as exc:
        # The published claim no longer describes the store: rows changed
        # under it, or a later publication superseded it. Distinct from
        # `reliability_inputs_refused` because the operator action differs —
        # re-publish, rather than go and look at what is missing.
        raise _error(409, "reliability_not_current", str(exc)) from exc
    except ReliabilityInputError as exc:
        # The observations themselves cannot support a coherent cohort: an
        # empty schedule, a window with no final games, a final game without
        # its exact two schedule rows, a player with both a game log and a
        # did-not-play row. Every one of these is a data defect a re-publish
        # will not fix, and the message names which.
        raise _error(409, "reliability_inputs_refused", str(exc)) from exc

    if not run.scorecards:
        # `compute_reliability_scorecards` returns an empty cohort rather than
        # refusing when the window holds games and logs but no player resolves
        # into either map. An empty list on a 200 would render as "nobody
        # missed a game", which is the one reading this endpoint must never
        # produce.
        raise _error(
            409,
            "reliability_inputs_refused",
            f"season {EVIDENCE_SEASON} published a cohort of {run.final_games} final game(s) "
            f"and {run.player_game_logs} game log(s) that produced no player scorecards",
        )

    # The computation takes lineage scope reservations, which on SQLite are
    # no-op writes. Nothing here is persisted, so release them without
    # committing.
    session.rollback()
    return _response(run, _player_names(session, run))
