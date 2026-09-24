"""Series inventory and omission semantics, independent of release admission."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import ExternalSource
from hoops_gm.db.models.projections import (
    ProjectionImport,
    ProjectionProfileVersion,
    ProjectionSource,
)
from hoops_gm.db.projection_series import (
    InvalidProjectionSeriesError,
    ProjectionSeriesNotImportedError,
    ProjectionSeriesRequiredError,
    current_projection_import_id,
    describe_series,
    projection_series_inventory,
    resolve_import_series_key,
    validate_series_key,
)

SOURCE = ExternalSource.BASKETBALL_MONSTER
SEASON = "2026-27"
WHEN = datetime(2026, 9, 18, tzinfo=UTC)


@pytest.fixture
def registered_profile(session: Session) -> ProjectionProfileVersion:
    source = ProjectionSource(source=SOURCE, display_name="Synthetic publisher")
    session.add(source)
    session.flush()
    profile = ProjectionProfileVersion(
        source_id=source.id,
        profile_id="synthetic-selection",
        profile_version="1",
        verified=False,
        verified_seasons=[],
        verification_evidence="Not an admitted import; selection fixture only.",
        definition_sha256="a" * 64,
        definition={},
    )
    session.add(profile)
    session.flush()
    return profile


def _record(
    session: Session,
    profile: ProjectionProfileVersion,
    *,
    key: str = "legacy",
    offset: int = 0,
    season: str = SEASON,
) -> ProjectionImport:
    row = ProjectionImport(
        source_id=profile.source_id,
        profile_version_id=profile.id,
        series_key=key,
        series_display_name=None if key == "legacy" else key.title(),
        season=season,
        imported_at=WHEN + timedelta(seconds=offset),
        content_sha256=f"{offset + 1:064x}",
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        profile_verified=False,
        profile_definition_sha256=profile.definition_sha256,
        profile_lineage={},
    )
    session.add(row)
    session.flush()
    return row


def test_zero_one_and_multiple_series_omission(
    session: Session, registered_profile: ProjectionProfileVersion
) -> None:
    assert current_projection_import_id(session, source=SOURCE, season=SEASON) is None
    assert (
        resolve_import_series_key(session, source=SOURCE, season=SEASON, series_key=None)
        == "legacy"
    )
    josh = _record(session, registered_profile, key="josh")
    assert current_projection_import_id(session, source=SOURCE, season=SEASON) == josh.id
    assert (
        resolve_import_series_key(session, source=SOURCE, season=SEASON, series_key=None) == "josh"
    )
    _record(session, registered_profile, key="bonus", offset=1)
    with pytest.raises(ProjectionSeriesRequiredError, match="bonus, josh"):
        current_projection_import_id(session, source=SOURCE, season=SEASON)
    with pytest.raises(ProjectionSeriesRequiredError):
        resolve_import_series_key(session, source=SOURCE, season=SEASON, series_key=None)
    assert (
        current_projection_import_id(session, source=SOURCE, season=SEASON, series_key="josh")
        == josh.id
    )


def test_legacy_is_truthfully_labelled_and_counts_toward_ambiguity(
    session: Session, registered_profile: ProjectionProfileVersion
) -> None:
    legacy = _record(session, registered_profile)
    legacy.original_filename = "josh-looking-filename.csv"
    inventory = projection_series_inventory(session, source=SOURCE, season=SEASON)
    assert inventory[0].series.key == "legacy"
    assert inventory[0].series.display_name == "Unspecified legacy series"
    assert inventory[0].series.provenance == "legacy_unspecified"
    _record(session, registered_profile, key="josh", offset=1)
    with pytest.raises(ProjectionSeriesRequiredError):
        current_projection_import_id(session, source=SOURCE, season=SEASON)
    with pytest.raises(InvalidProjectionSeriesError, match="no recorded"):
        describe_series("legacy", "Josh")


def test_latest_is_per_series_and_inventory_is_not_release_admission(
    session: Session, registered_profile: ProjectionProfileVersion
) -> None:
    _record(session, registered_profile, key="josh")
    bonus = _record(session, registered_profile, key="bonus", offset=4)
    newest_josh = _record(session, registered_profile, key="josh", offset=2)
    tie_josh = _record(session, registered_profile, key="josh", offset=3)
    tie_josh.imported_at = newest_josh.imported_at
    session.flush()
    inventory = projection_series_inventory(session, source=SOURCE, season=SEASON)
    assert [(item.series.key, item.latest_import.id) for item in inventory] == [
        ("bonus", bonus.id),
        ("josh", tie_josh.id),
    ]
    assert not tie_josh.profile_verified
    assert (
        current_projection_import_id(session, source=SOURCE, season=SEASON, series_key="josh")
        == tie_josh.id
    )


def test_explicit_unknown_scope_never_falls_back(
    session: Session, registered_profile: ProjectionProfileVersion
) -> None:
    _record(session, registered_profile, key="josh")
    for source, season, key in (
        (SOURCE, SEASON, "bonus"),
        (SOURCE, "2025-26", "josh"),
        (ExternalSource.MANUAL, SEASON, "josh"),
    ):
        with pytest.raises(ProjectionSeriesNotImportedError):
            current_projection_import_id(session, source=source, season=season, series_key=key)
    assert (
        resolve_import_series_key(session, source=SOURCE, season="2027-28", series_key=None)
        == "legacy"
    )
    assert (
        resolve_import_series_key(session, source=SOURCE, season=SEASON, series_key="new-series")
        == "new-series"
    )


@pytest.mark.parametrize(
    "key", ["", "Josh", "josh ", "../josh", "-josh", "josh\n", "é", "a" * 65, None]
)
def test_invalid_keys_are_not_coerced(key: object) -> None:
    with pytest.raises(InvalidProjectionSeriesError):
        validate_series_key(key)


def test_series_description_validation_is_pure() -> None:
    assert describe_series("josh", "Josh").provenance == "operator_declared"
    for label in (None, "", "   ", "x" * 129):
        with pytest.raises(InvalidProjectionSeriesError):
            describe_series("josh", label)
