"""Real-writer series contracts, not new publishers or new CSV admission rules.

The five series_*.csv recordings were captured from unchanged public demo
scaffolding before the selector edits. They contain invented rates, not vendor
forecasts. Copy-time raw-byte verification is separate from these portable
checkout contracts, which bind the import to the exact bytes actually supplied.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import ExternalSource, FieldEvidence, MatchMethod, ScoringType
from hoops_gm.db.models.identity import Player, PlayerExternalId
from hoops_gm.db.models.projections import (
    Projection,
    ProjectionImport,
    ProjectionProfileVersion,
    ProjectionSource,
    SourceGamesPlayedAssumption,
)
from hoops_gm.db.projection_series import describe_import_series
from hoops_gm.dev.seed_projections import PLAYERS_FIXTURE
from hoops_gm.dev.seed_schedule_grid import DEFAULT_FIXTURES_DIR, load_fixture
from hoops_gm.identity.names import normalize_name
from hoops_gm.ingest.importers import import_nba_players, import_resolutions
from hoops_gm.ingest.nba.parsers import parse_common_all_players
from hoops_gm.ingest.projections import (
    BASKETBALL_MONSTER_PROFILE,
    InvalidProjectionSeriesError,
    ProjectionImportOutcome,
    ProjectionProfileError,
    ProjectionSeriesRequiredError,
    import_projection_csv,
    importer,
    parse_projection_csv,
)
from hoops_gm.projections.blending import release_projection_import

SEASON = "2026-27"
NOW = datetime(2026, 9, 1, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "projections"
SOURCE_NAME = "Synthetic publisher, not a forecast"
ONE = b"player_name,points_per_game,games_played\nSeries Alpha,20,60\n"
TWO = ONE.replace(b",20,", b",21,")
THREE = ONE.replace(b",20,", b",22,")


@pytest.fixture
def players(session: Session) -> tuple[Player, ...]:
    result = []
    for index, name in enumerate(("Series Alpha", "Series Beta", "Series Gamma"), start=1):
        player = Player(full_name=name, normalized_name=normalize_name(name).key)
        session.add(player)
        session.flush()
        session.add(
            PlayerExternalId(
                player_id=player.id,
                source=ExternalSource.NBA,
                current_for_source=ExternalSource.NBA.value,
                external_id=f"synthetic-series-{index}",
                external_name=name,
                normalized_name=normalize_name(name).key,
                confidence=1.0,
                match_method=MatchMethod.ANCHOR_ID,
                name_evidence=FieldEvidence.AGREE,
            )
        )
        result.append(player)
    session.flush()
    return tuple(result)


def _import(
    session: Session,
    *,
    series_key: str | None = None,
    series_display_name: str | None = None,
    content: bytes = ONE,
    season: str = SEASON,
    scoring_type: ScoringType | None = None,
    display_name: str = SOURCE_NAME,
) -> ProjectionImportOutcome:
    return import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name=display_name,
        season=season,
        csv_bytes=content,
        series_key=series_key,
        series_display_name=series_display_name,
        assumed_scoring_type=scoring_type,
        original_filename="synthetic-series.csv",
        raw_payload_ref="synthetic-series-original",
    )


def _state(session: Session) -> dict[str, list[tuple[Any, ...]]]:
    """Every content table touched by the importer, including mutable metadata."""
    return {
        model.__tablename__: list(
            map(tuple, session.execute(select(model.__table__).order_by(model.id)))
        )
        for model in (
            ProjectionSource,
            ProjectionProfileVersion,
            ProjectionImport,
            Projection,
            SourceGamesPlayedAssumption,
            PlayerExternalId,
        )
    }


def _cohort(session: Session, import_id: int) -> list[tuple[Any, ...]]:
    return list(
        map(
            tuple,
            session.execute(
                select(Projection.__table__, SourceGamesPlayedAssumption.__table__)
                .join(
                    SourceGamesPlayedAssumption,
                    SourceGamesPlayedAssumption.projection_id == Projection.id,
                )
                .where(Projection.projection_import_id == import_id)
                .order_by(Projection.player_id)
            ),
        )
    )


def test_zero_series_omission_is_unspecified_legacy(
    session: Session, players: tuple[Player, ...]
) -> None:
    outcome = _import(session)
    stored = outcome.projection_import
    assert outcome.counts.created == 1
    assert stored.series_key == "legacy"
    assert stored.series_display_name is None
    descriptor = describe_import_series(stored)
    assert descriptor.display_name == "Unspecified legacy series"
    assert descriptor.provenance == "legacy_unspecified"
    assert outcome.projection_source.display_name == SOURCE_NAME


def test_sole_named_omission_preserves_old_label_before_inheriting_a_new_one(
    session: Session, players: tuple[Player, ...]
) -> None:
    old = _import(session, series_key="josh", series_display_name="Original label")
    old.projection_import.imported_at = NOW
    session.flush()
    identity = (
        old.projection_import.id,
        old.projection_import.imported_at,
        old.projection_import.content_sha256,
        old.projection_import.profile_lineage,
        old.projection_import.original_filename,
        old.projection_import.raw_payload_ref,
    )
    new = _import(session, series_display_name="Revised label", content=TWO)
    new.projection_import.imported_at = NOW + timedelta(days=1)
    session.flush()
    assert new.projection_import.series_key == "josh"
    assert new.projection_import.series_display_name == "Revised label"

    replay = _import(session)
    assert not replay.import_created
    assert replay.projection_import.series_display_name == "Original label"
    assert (
        replay.projection_import.id,
        replay.projection_import.imported_at,
        replay.projection_import.content_sha256,
        replay.projection_import.profile_lineage,
        replay.projection_import.original_filename,
        replay.projection_import.raw_payload_ref,
    ) == identity
    explicit = _import(session, series_key="josh", series_display_name="Original label")
    assert explicit.projection_import.id == identity[0]
    with pytest.raises(InvalidProjectionSeriesError, match="immutable projection import"):
        _import(session, series_key="josh", series_display_name="Revised label")

    inherited = _import(session, content=THREE)
    assert inherited.import_created
    assert inherited.projection_import.series_key == "josh"
    assert inherited.projection_import.series_display_name == "Revised label"


def test_same_bytes_are_distinct_between_series_and_deduplicated_within_each(
    session: Session, players: tuple[Player, ...]
) -> None:
    josh = _import(session, series_key="josh")
    bonus = _import(session, series_key="bonus", series_display_name="Bonus display only")
    assert josh.projection_import.id != bonus.projection_import.id
    assert josh.projection_import.series_display_name == "josh"
    assert josh.projection_source.id == bonus.projection_source.id
    assert josh.projection_source.display_name == SOURCE_NAME
    assert josh.projection_import.content_sha256 == bonus.projection_import.content_sha256
    assert josh.projection_import.profile_version_id == bonus.projection_import.profile_version_id
    assert josh.projection_import.profile_lineage == bonus.projection_import.profile_lineage
    for original in (josh, bonus):
        previous_time = original.projection_import.imported_at
        replay = _import(session, series_key=original.projection_import.series_key)
        assert not replay.import_created
        assert replay.projection_import.id == original.projection_import.id
        assert replay.projection_import.imported_at == previous_time
        assert replay.counts.updated == 1
    assert len(session.scalars(select(ProjectionImport)).all()) == 2
    assert len(session.scalars(select(ProjectionProfileVersion)).all()) == 1
    assert len(session.scalars(select(ProjectionSource)).all()) == 1
    assert len(session.scalars(select(Projection)).all()) == 2
    links = session.scalars(
        select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.MANUAL)
    ).all()
    assert len(links) == 1
    assert links[0].player_id == players[0].id


@pytest.mark.parametrize("first", ["legacy", "josh"])
def test_ambiguous_omission_refuses_before_any_content_or_default_mutation(
    session: Session, players: tuple[Player, ...], first: str
) -> None:
    _import(session, series_key=first)
    _import(session, series_key="bonus")
    before = _state(session)
    with pytest.raises(ProjectionSeriesRequiredError, match="multiple recorded series"):
        _import(session, display_name="Must not be written", scoring_type=ScoringType.POINTS)
    session.flush()
    assert _state(session) == before
    # A canonical explicit declaration does not fall back to one of the above.
    third = _import(session, series_key="new-series")
    assert third.import_created
    assert third.projection_import.series_key == "new-series"
    assert third.projection_import.series_display_name == "new-series"


def test_series_omission_and_label_inheritance_do_not_cross_seasons(
    session: Session, players: tuple[Player, ...]
) -> None:
    _import(session, series_key="josh", series_display_name="Old season", season="2025-26")
    _import(session, series_key="bonus", season="2025-26")
    current = _import(session)
    assert current.projection_import.series_key == "legacy"
    explicit = _import(session, series_key="josh")
    assert explicit.projection_import.series_display_name == "josh"


@pytest.mark.parametrize(
    ("key", "label"),
    [
        ("", None),
        ("Josh", None),
        (" josh", None),
        ("josh ", None),
        ("josh\n", None),
        ("_josh", None),
        ("../josh", None),
        ("jos\u00e9", None),
        ("a" * 65, None),
        ("josh", ""),
        ("josh", " \t "),
        ("josh", "x" * 129),
        ("legacy", "Josh"),
        ("legacy", "Unspecified legacy series"),
        (None, "Josh"),
    ],
)
def test_invalid_declaration_refuses_before_registering_source_or_profile(
    session: Session, players: tuple[Player, ...], key: str | None, label: str | None
) -> None:
    before = _state(session)
    with pytest.raises(InvalidProjectionSeriesError):
        _import(session, series_key=key, series_display_name=label)
    session.flush()
    assert _state(session) == before


@pytest.mark.parametrize("label", [None, "Original label", "Revised label"])
def test_real_unique_violation_recovery_is_series_scoped_and_retains_original_label(
    session: Session,
    players: tuple[Player, ...],
    monkeypatch: pytest.MonkeyPatch,
    label: str | None,
) -> None:
    # The other series has the lower ID, so an unscoped recovery returns the
    # wrong series even though its bytes/profile/season are exactly the same.
    bonus = _import(session, series_key="bonus")
    original = _import(session, series_key="josh", series_display_name="Original label")
    original.projection_import.imported_at = NOW
    latest = _import(session, series_key="josh", series_display_name="Revised label", content=TWO)
    latest.projection_import.imported_at = NOW + timedelta(days=1)
    session.flush()
    stored = original.projection_import
    before = _state(session)
    real_scalar = session.scalar
    real_flush = session.flush
    missed = False
    violations: list[IntegrityError] = []

    def hide_first_exact_read(*args: Any, **kwargs: Any) -> Any:
        nonlocal missed
        if not missed:
            missed = True
            return None
        return real_scalar(*args, **kwargs)

    def observe_real_violation(*args: Any, **kwargs: Any) -> None:
        try:
            real_flush(*args, **kwargs)
        except IntegrityError as exc:
            violations.append(exc)
            raise

    def recover() -> tuple[ProjectionImport, bool]:
        return importer._get_or_create_projection_import(
            session,
            source=original.projection_source,
            profile_version_row=stored.profile_version_row,
            season=SEASON,
            content_sha256=stored.content_sha256,
            profile_lineage=stored.profile_lineage,
            series_key="josh",
            series_display_name=label,
        )

    with monkeypatch.context() as patch:
        patch.setattr(session, "scalar", hide_first_exact_read)
        patch.setattr(session, "flush", observe_real_violation)
        if label == "Revised label":
            with pytest.raises(InvalidProjectionSeriesError, match="immutable projection import"):
                recover()
        else:
            recovered, created = recover()
            assert not created
            assert recovered.id == stored.id != bonus.projection_import.id
            assert recovered.series_key == "josh"
            assert recovered.series_display_name == "Original label"
            assert recovered.imported_at == NOW
    assert missed
    assert len(violations) == 1, "the real insert must reach the IntegrityError recovery branch"
    assert _state(session) == before


def test_manual_overlaps_preserve_other_imports_and_provider_authority_on_replay(
    session: Session, players: tuple[Player, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    alpha, beta, gamma = players
    alias = "Unmatched synthetic alias"
    manual = PlayerExternalId(
        player_id=beta.id,
        source=ExternalSource.MANUAL,
        current_for_source=ExternalSource.MANUAL.value,
        external_id=normalize_name(alias).key,
        external_name=alias,
        normalized_name=normalize_name(alias).key,
        confidence=1.0,
        match_method=MatchMethod.MANUAL_OVERRIDE,
        is_manual_override=True,
        name_evidence=FieldEvidence.AGREE,
    )
    session.add(manual)
    session.flush()
    header = "player_name,points_per_game,games_played\n"
    josh_bytes = f"{header}{alpha.full_name},20,60\n{alias},21,61\n".encode()
    bonus_bytes = f"{header}{alias},25,62\n{gamma.full_name},26,63\n".encode()
    # MANUAL's unchanged wildcard is the real admitted older-season path.
    old_season = _import(session, series_key="josh", content=josh_bytes, season="2025-26")
    old_season.projection_import.imported_at = NOW + timedelta(days=90)
    josh = _import(session, series_key="josh", content=josh_bytes)
    josh.projection_import.imported_at = NOW
    session.flush()
    josh_rows = _cohort(session, josh.projection_import.id)
    assert len(josh_rows) == 2
    bonus = _import(session, series_key="bonus", content=bonus_bytes)
    bonus.projection_import.imported_at = NOW + timedelta(days=1)
    session.flush()
    bonus_rows = _cohort(session, bonus.projection_import.id)
    assert len(bonus_rows) == 2
    assert _cohort(session, josh.projection_import.id) == josh_rows

    josh_v2 = _import(session, series_key="josh", content=josh_bytes.replace(b",20,", b",22,"))
    josh_v2.projection_import.imported_at = NOW + timedelta(days=2)
    session.flush()
    assert _cohort(session, bonus.projection_import.id) == bonus_rows
    josh_v2_rows = _cohort(session, josh_v2.projection_import.id)
    bonus_v2 = _import(session, series_key="bonus", content=bonus_bytes.replace(b",26,", b",27,"))
    bonus_v2.projection_import.imported_at = NOW + timedelta(days=3)
    session.flush()
    assert _cohort(session, josh_v2.projection_import.id) == josh_v2_rows
    bonus_v2_rows = _cohort(session, bonus_v2.projection_import.id)
    crosswalk_before = _state(session)["player_external_ids"]
    calls = []

    def observe_crosswalk(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs["source"])
        return import_resolutions(*args, **kwargs)

    monkeypatch.setattr(importer, "import_resolutions", observe_crosswalk)
    for original, content in (
        (old_season, josh_bytes),
        (josh, josh_bytes),
        (bonus, bonus_bytes),
        (josh_v2, josh_bytes.replace(b",20,", b",22,")),
    ):
        replay = _import(
            session,
            series_key=original.projection_import.series_key,
            season=original.projection_import.season,
            content=content,
        )
        assert not replay.import_created
        assert replay.projection_import.id == original.projection_import.id
        assert replay.counts.updated == 2
        assert replay.identity_report.needs_review == []
        assert replay.identity_report.unmatched == []
        assert _cohort(session, bonus_v2.projection_import.id) == bonus_v2_rows
        assert _state(session)["player_external_ids"] == crosswalk_before
    assert calls == [], "not even the latest Josh owns the newer Bonus provider-wide crosswalk"
    _import(session, series_key="bonus", content=bonus_bytes.replace(b",26,", b",27,"))
    assert calls == [ExternalSource.MANUAL], "the actual provider-wide current import still writes"
    assert manual.is_manual_override
    assert manual.player_id == beta.id
    for outcome, expected in ((josh_v2, {alpha.id, beta.id}), (bonus_v2, {beta.id, gamma.id})):
        ids = set(
            session.scalars(
                select(Projection.player_id).where(
                    Projection.projection_import_id == outcome.projection_import.id
                )
            )
        )
        assert ids == expected
        assert (
            release_projection_import(
                session,
                import_id=outcome.projection_import.id,
                source=ExternalSource.MANUAL,
            ).projection_count
            == 2
        )


@pytest.mark.adapter_contract
@pytest.mark.parametrize(
    ("recording", "key", "expected_count"),
    [
        ("legacy", None, 60),
        ("josh", "josh", 55),
        ("bonus", "bonus", 55),
        ("josh_gp_only", "josh", 55),
        ("josh_v2", "josh", 55),
    ],
)
def test_recorded_synthetic_series_use_the_unchanged_bbm_parser_and_real_writer(
    session: Session, recording: str, key: str | None, expected_count: int
) -> None:
    import_nba_players(
        session, parse_common_all_players(load_fixture(DEFAULT_FIXTURES_DIR, PLAYERS_FIXTURE))
    )
    raw = (FIXTURES / f"series_{recording}.csv").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    result = import_projection_csv(
        session,
        source=ExternalSource.BASKETBALL_MONSTER,
        display_name=SOURCE_NAME,
        season=SEASON,
        csv_bytes=raw,
        series_key=key,
    )
    assert result.projection_import.series_key == (key or "legacy")
    assert result.projection_import.content_sha256 == digest
    assert result.projection_import.profile_id == BASKETBALL_MONSTER_PROFILE.profile_id
    assert result.projection_import.profile_version == BASKETBALL_MONSTER_PROFILE.version
    # The recorded legacy pool has 60 rows. Each named pool has 55, with 50
    # shared vendor IDs and five distinct members on either side; no resizing.
    assert result.parse_result.total_rows == result.counts.created == expected_count
    assert result.parse_result.rejected_count == 0
    assert not result.identity_report.unmatched
    assert not result.identity_report.needs_review
    release = release_projection_import(
        session, import_id=result.projection_import.id, source=ExternalSource.BASKETBALL_MONSTER
    )
    assert release.series_key == (key or "legacy")
    assert release.projection_count == expected_count


def test_series_declaration_does_not_relax_bbm_verified_season(session: Session) -> None:
    before = _state(session)
    with pytest.raises(ProjectionProfileError, match=r"not verified.*2025-26"):
        import_projection_csv(
            session,
            source=ExternalSource.BASKETBALL_MONSTER,
            display_name=SOURCE_NAME,
            season="2025-26",
            csv_bytes=(FIXTURES / "series_josh.csv").read_bytes(),
            series_key="josh",
        )
    assert _state(session) == before


def test_recorded_bbm_overlaps_new_versions_and_manual_identity_survive_old_replays(
    session: Session,
) -> None:
    import_nba_players(
        session, parse_common_all_players(load_fixture(DEFAULT_FIXTURES_DIR, PLAYERS_FIXTURE))
    )
    source = ExternalSource.BASKETBALL_MONSTER
    josh_bytes = (FIXTURES / "series_josh.csv").read_bytes()
    bonus_bytes = (FIXTURES / "series_bonus.csv").read_bytes()
    josh_rows = parse_projection_csv(
        josh_bytes.decode("utf-8"), BASKETBALL_MONSTER_PROFILE, season=SEASON
    ).rows
    bonus_rows = parse_projection_csv(
        bonus_bytes.decode("utf-8"), BASKETBALL_MONSTER_PROFILE, season=SEASON
    ).rows
    shared_ids = {row.source_player_id for row in josh_rows} & {
        row.source_player_id for row in bonus_rows
    }
    assert len(josh_rows) == len(bonus_rows) == 55
    assert len(shared_ids) == 50
    shared = next(row for row in josh_rows if row.source_player_id in shared_ids)
    player = session.scalar(
        select(Player).where(Player.normalized_name == normalize_name(shared.player_name).key)
    )
    assert player is not None
    manual = PlayerExternalId(
        player_id=player.id,
        source=source,
        current_for_source=source.value,
        external_id=shared.source_player_id,
        external_name=shared.player_name,
        normalized_name=player.normalized_name,
        confidence=1.0,
        match_method=MatchMethod.MANUAL_OVERRIDE,
        is_manual_override=True,
        name_evidence=FieldEvidence.AGREE,
    )
    session.add(manual)
    session.flush()
    manual_before = tuple(
        session.execute(
            select(PlayerExternalId.__table__).where(PlayerExternalId.id == manual.id)
        ).one()
    )

    def write(key: str, raw: bytes) -> ProjectionImportOutcome:
        result = import_projection_csv(
            session,
            source=source,
            display_name=SOURCE_NAME,
            season=SEASON,
            csv_bytes=raw,
            series_key=key,
        )
        assert result.counts.created + result.counts.updated == 55
        assert not result.identity_report.needs_review
        assert not result.identity_report.unmatched
        return result

    josh = write("josh", josh_bytes)
    josh.projection_import.imported_at = NOW
    session.flush()
    original_josh_rows = _cohort(session, josh.projection_import.id)
    bonus = write("bonus", bonus_bytes)
    bonus.projection_import.imported_at = NOW + timedelta(days=1)
    session.flush()
    assert _cohort(session, josh.projection_import.id) == original_josh_rows
    original_bonus_rows = _cohort(session, bonus.projection_import.id)
    josh_v2_bytes = (FIXTURES / "series_josh_v2.csv").read_bytes()
    josh_v2 = write("josh", josh_v2_bytes)
    josh_v2.projection_import.imported_at = NOW + timedelta(days=2)
    session.flush()
    assert _cohort(session, bonus.projection_import.id) == original_bonus_rows
    current_josh_rows = _cohort(session, josh_v2.projection_import.id)
    bonus_v2 = write("bonus", bonus_bytes + b"\n")
    bonus_v2.projection_import.imported_at = NOW + timedelta(days=3)
    session.flush()
    assert _cohort(session, josh_v2.projection_import.id) == current_josh_rows
    current_bonus_rows = _cohort(session, bonus_v2.projection_import.id)
    crosswalk_before = _state(session)["player_external_ids"]
    for original, raw in ((josh, josh_bytes), (bonus, bonus_bytes)):
        replay = write(original.projection_import.series_key, raw)
        assert not replay.import_created
        assert replay.projection_import.id == original.projection_import.id
        assert _cohort(session, josh_v2.projection_import.id) == current_josh_rows
        assert _cohort(session, bonus_v2.projection_import.id) == current_bonus_rows
        assert _state(session)["player_external_ids"] == crosswalk_before
    # Josh's own current import also cannot rewind a later provider-wide Bonus.
    write("josh", josh_v2_bytes)
    assert _cohort(session, bonus_v2.projection_import.id) == current_bonus_rows
    assert _state(session)["player_external_ids"] == crosswalk_before
    assert (
        tuple(
            session.execute(
                select(PlayerExternalId.__table__).where(PlayerExternalId.id == manual.id)
            ).one()
        )
        == manual_before
    )
    cohorts = [
        set(
            session.scalars(
                select(Projection.player_id).where(
                    Projection.projection_import_id == outcome.projection_import.id
                )
            )
        )
        for outcome in (josh_v2, bonus_v2)
    ]
    assert len(cohorts[0] & cohorts[1]) == 50
    assert len(cohorts[0] - cohorts[1]) == len(cohorts[1] - cohorts[0]) == 5
    for outcome in (josh_v2, bonus_v2):
        released = release_projection_import(
            session, import_id=outcome.projection_import.id, source=source
        )
        assert released.projection_count == 55
        assert released.series_key == outcome.projection_import.series_key
