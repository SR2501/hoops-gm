"""Read-only HTTP adapters for recorded series inventory and explicit selection."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import ExternalSource
from hoops_gm.db.models.league import League
from hoops_gm.db.models.projections import ProjectionSource
from hoops_gm.db.projection_series import (
    InvalidProjectionSeriesError,
    ProjectionSeries,
    ProjectionSeriesNotImportedError,
    ProjectionSeriesRequiredError,
    SeriesProvenance,
    current_projection_import_id,
    projection_series_inventory,
    validate_series_key,
)

type ProjectionReleaseSchema = Literal["projection-import-release-series-v1"]
type SelectionSurface = Literal["projections", "production_candidates"]
NonEmpty = Annotated[str, Field(min_length=1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def series_query_key(
    request: Request,
    series_key: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=64,
            pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$",
            description=(
                "Explicit forecast-series key, not a publisher or import version. "
                "Omission is compatible only when one series is recorded."
            ),
        ),
    ] = None,
) -> str | None:
    supplied = request.query_params.getlist("series_key")
    if len(supplied) > 1:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("query", "series_key"),
                    "msg": "series_key must be supplied exactly once",
                    "input": supplied,
                }
            ]
        )
    if series_key is not None:
        try:
            return validate_series_key(series_key)
        except InvalidProjectionSeriesError as exc:
            raise RequestValidationError(
                [
                    {
                        "type": "value_error",
                        "loc": ("query", "series_key"),
                        "msg": str(exc),
                        "input": series_key,
                    }
                ]
            ) from exc
    return None


SeriesKeyDep = Annotated[str | None, Depends(series_query_key)]


class ProjectionSeriesDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Annotated[str, Field(min_length=1, max_length=64)]
    display_name: Annotated[str, Field(min_length=1, max_length=128)]
    provenance: SeriesProvenance


def series_descriptor_out(series: ProjectionSeries) -> ProjectionSeriesDescriptor:
    return ProjectionSeriesDescriptor(
        key=series.key, display_name=series.display_name, provenance=series.provenance
    )


class LatestSeriesImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_id: Annotated[int, Field(gt=0)]
    imported_at: datetime
    content_sha256: Sha256
    profile_id: NonEmpty
    profile_version: NonEmpty
    profile_definition_sha256: Sha256
    original_filename: str | None


class ProjectionSeriesEntry(ProjectionSeriesDescriptor):
    latest_import: LatestSeriesImport


class ProjectionSeriesCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    league_id: Annotated[int, Field(gt=0)]
    season: NonEmpty
    source: ExternalSource
    source_display_name: NonEmpty | None
    selection_required: bool
    series: list[ProjectionSeriesEntry]


class DraftProjectionSeriesCatalog(ProjectionSeriesCatalog):
    draft_id: Annotated[int, Field(gt=0)]


def _error(code: str, detail: str, *, status: int = 409) -> HTTPException:
    return HTTPException(status, detail=detail, headers={"X-Bridge-Error": code})


def select_current_import(
    session: Session,
    *,
    source: ExternalSource,
    season: str,
    series_key: str | None,
    surface: SelectionSurface,
) -> int | None:
    try:
        return current_projection_import_id(
            session, source=source, season=season, series_key=series_key
        )
    except ProjectionSeriesRequiredError as exc:
        raise _error(f"{surface}_series_required", str(exc)) from exc
    except ProjectionSeriesNotImportedError as exc:
        raise _error(f"{surface}_series_not_imported", str(exc), status=404) from exc
    except InvalidProjectionSeriesError as exc:
        code = (
            "projections_incomplete_evidence"
            if surface == "projections"
            else "production_candidates_input_evidence_refused"
        )
        raise _error(code, f"Invalid recorded series declaration: {exc}") from exc


def series_catalog(
    session: Session, *, league: League, source: ExternalSource
) -> ProjectionSeriesCatalog:
    """Inventory records candidates, including those canonical release may refuse."""

    try:
        choices = projection_series_inventory(session, source=source, season=league.season)
        label = session.scalar(
            select(ProjectionSource.display_name).where(ProjectionSource.source == source)
        )
        return ProjectionSeriesCatalog(
            league_id=league.id,
            season=league.season,
            source=source,
            source_display_name=label,
            selection_required=len(choices) > 1,
            series=[
                ProjectionSeriesEntry(
                    **series_descriptor_out(choice.series).model_dump(),
                    latest_import=LatestSeriesImport(
                        import_id=choice.latest_import.id,
                        imported_at=choice.latest_import.imported_at,
                        content_sha256=choice.latest_import.content_sha256,
                        profile_id=choice.latest_import.profile_id,
                        profile_version=choice.latest_import.profile_version,
                        profile_definition_sha256=choice.latest_import.profile_definition_sha256,
                        original_filename=choice.latest_import.original_filename,
                    ),
                )
                for choice in choices
            ],
        )
    except (InvalidProjectionSeriesError, ValidationError) as exc:
        raise _error("projection_series_incomplete_evidence", str(exc)) from exc
