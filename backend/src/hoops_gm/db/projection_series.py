"""Forecast-series identity and current-import selection, not player namespaces."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import ExternalSource
from hoops_gm.db.models.projections import ProjectionImport, ProjectionSource

LEGACY_SERIES_KEY = "legacy"
LEGACY_SERIES_DISPLAY_NAME = "Unspecified legacy series"
_SERIES_KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")

type SeriesProvenance = Literal["operator_declared", "legacy_unspecified"]


class ProjectionSeriesError(ValueError):
    """A series declaration or selection cannot be honored."""


class InvalidProjectionSeriesError(ProjectionSeriesError):
    """A supplied or stored series declaration is malformed."""


class ProjectionSeriesRequiredError(ProjectionSeriesError):
    """An omitted selection would choose between different forecast series."""


class ProjectionSeriesNotImportedError(ProjectionSeriesError):
    """The explicitly selected series has no import in this provider/season."""


@dataclass(frozen=True, slots=True)
class ProjectionSeries:
    key: str
    display_name: str
    provenance: SeriesProvenance


@dataclass(frozen=True, slots=True)
class ProjectionSeriesChoice:
    series: ProjectionSeries
    latest_import: ProjectionImport


def validate_series_key(value: object) -> str:
    """Pure validation, also usable by the no-I/O release-integrity boundary."""

    if not isinstance(value, str) or _SERIES_KEY.fullmatch(value) is None:
        raise InvalidProjectionSeriesError(
            "series_key must be 1-64 lowercase ASCII letters, digits, underscores or "
            "hyphens, starting with a letter or digit"
        )
    return value


def describe_series(key: object, display_name: object) -> ProjectionSeries:
    key = validate_series_key(key)
    if key == LEGACY_SERIES_KEY:
        if display_name is not None:
            raise InvalidProjectionSeriesError(
                "legacy imports have no recorded forecast-variant label"
            )
        return ProjectionSeries(key, LEGACY_SERIES_DISPLAY_NAME, "legacy_unspecified")
    if not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 128:
        raise InvalidProjectionSeriesError(
            "named series require a nonblank series_display_name of at most 128 characters"
        )
    return ProjectionSeries(key, display_name, "operator_declared")


def describe_import_series(projection_import: ProjectionImport) -> ProjectionSeries:
    return describe_series(projection_import.series_key, projection_import.series_display_name)


def projection_series_inventory(
    session: Session, *, source: ExternalSource, season: str
) -> tuple[ProjectionSeriesChoice, ...]:
    """List newest recorded candidates without claiming that they can release."""

    ranked = (
        select(
            ProjectionImport.id.label("import_id"),
            func.row_number()
            .over(
                partition_by=ProjectionImport.series_key,
                order_by=(ProjectionImport.imported_at.desc(), ProjectionImport.id.desc()),
            )
            .label("series_rank"),
        )
        .join(ProjectionSource, ProjectionSource.id == ProjectionImport.source_id)
        .where(ProjectionSource.source == source, ProjectionImport.season == season)
        .subquery()
    )
    rows = session.scalars(
        select(ProjectionImport)
        .join(ranked, ranked.c.import_id == ProjectionImport.id)
        .where(ranked.c.series_rank == 1)
        .order_by(ProjectionImport.series_key)
    )
    return tuple(ProjectionSeriesChoice(describe_import_series(row), row) for row in rows)


def _sole_recorded_key(session: Session, *, source: ExternalSource, season: str) -> str | None:
    keys = tuple(
        validate_series_key(key)
        for key in session.scalars(
            select(ProjectionImport.series_key)
            .join(ProjectionSource, ProjectionSource.id == ProjectionImport.source_id)
            .where(ProjectionSource.source == source, ProjectionImport.season == season)
            .distinct()
            .order_by(ProjectionImport.series_key)
        )
    )
    if len(keys) > 1:
        raise ProjectionSeriesRequiredError(
            f"{source.value} has multiple recorded series for {season}: "
            f"{', '.join(keys)}; choose an explicit series_key"
        )
    return keys[0] if keys else None


def resolve_import_series_key(
    session: Session,
    *,
    source: ExternalSource,
    season: str,
    series_key: str | None,
) -> str:
    """Resolve only the key; an omitted label must await exact-version lookup."""

    if series_key is not None:
        return validate_series_key(series_key)
    return _sole_recorded_key(session, source=source, season=season) or LEGACY_SERIES_KEY


def latest_series_import(
    session: Session, *, source_id: int, season: str, series_key: str
) -> ProjectionImport | None:
    key = validate_series_key(series_key)
    return session.scalar(
        select(ProjectionImport)
        .where(
            ProjectionImport.source_id == source_id,
            ProjectionImport.season == season,
            ProjectionImport.series_key == key,
        )
        .order_by(ProjectionImport.imported_at.desc(), ProjectionImport.id.desc())
        .limit(1)
    )


def current_projection_import_id(
    session: Session,
    *,
    source: ExternalSource,
    season: str,
    series_key: str | None = None,
) -> int | None:
    key = (
        validate_series_key(series_key)
        if series_key is not None
        else _sole_recorded_key(session, source=source, season=season)
    )
    if key is None:
        return None
    source_id = session.scalar(select(ProjectionSource.id).where(ProjectionSource.source == source))
    row = (
        latest_series_import(session, source_id=source_id, season=season, series_key=key)
        if source_id is not None
        else None
    )
    if row is None:
        raise ProjectionSeriesNotImportedError(
            f"series {key!r} has no {source.value} import for season {season}"
        )
    describe_import_series(row)
    return row.id
