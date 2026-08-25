"""ADR-008 layer purity: every rejection driven, not asserted.

The defect these guard against is circularity, which does not crash. A
composite value or a published ranking feeding back into an availability or
projection input makes the model agree with itself: every downstream figure
gets more confident and less true, with a green suite the whole way. So the
tests here are mostly *provocations* — build a flow ADR-008 forbids, and
require the mechanism to refuse it.

Two things about the shape, both taken from failures this repository has
already paid for.

**Closed sets, not spellings.** Membership comes from ``Base.metadata``: every
mapped table must be assigned, and every declared foreign key is checked. A new
table or a new key is covered on arrival rather than when somebody remembers to
widen a pattern. The store-opening census learned this the expensive way, going
from exactly complete to quietly incomplete at exit 0 because its search
pattern was one call spelling.

**Scope limits are asserted, not narrated.** ``FLOW_SCAN_LIMIT`` and
``GRAIN_LIMIT`` are pinned by :func:`test_the_scope_limits_are_stated`, because
a limitation in a docstring gets summarised away and a limitation behind an
assertion breaks a test when someone deletes it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.db.base import Base
from hoops_gm.db.layers import (
    FLOW_SCAN_LIMIT,
    GRAIN_LIMIT,
    LAYER_RANK,
    LAYERS_WITHOUT_TABLES,
    TABLE_LAYERS,
    DataLayer,
    LayerViolation,
    flow_permitted,
    layer_of,
    validate_layer_assignment,
    validate_layer_flow,
    validate_layers,
)
from hoops_gm.db.models import DataLayerRegistry

# --- the ordering itself ----------------------------------------------------


def test_every_layer_is_ranked() -> None:
    """An unranked layer would make ``flow_permitted`` raise KeyError, not refuse."""
    assert set(LAYER_RANK) == set(DataLayer)


def test_the_pipeline_order_is_the_one_adr_008_states() -> None:
    """observations -> projections -> availability -> valuation -> terminal."""
    pipeline = [
        DataLayer.OBSERVATIONS,
        DataLayer.PROJECTIONS,
        DataLayer.AVAILABILITY,
        DataLayer.VALUATION,
        DataLayer.TERMINAL,
    ]
    ranks = [LAYER_RANK[layer] for layer in pipeline]

    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks), "two pipeline layers share a rank"


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (DataLayer.OBSERVATIONS, DataLayer.PROJECTIONS),
        (DataLayer.OBSERVATIONS, DataLayer.MARKET),
        (DataLayer.PROJECTIONS, DataLayer.AVAILABILITY),
        (DataLayer.AVAILABILITY, DataLayer.VALUATION),
        (DataLayer.VALUATION, DataLayer.TERMINAL),
        (DataLayer.TERMINAL, DataLayer.COMPARISON),
        (DataLayer.MARKET, DataLayer.COMPARISON),
        # ADR-008 clause 1: aggregate only *within* a layer.
        (DataLayer.PROJECTIONS, DataLayer.PROJECTIONS),
        (DataLayer.MARKET, DataLayer.MARKET),
    ],
)
def test_forward_and_within_layer_flow_is_permitted(source: DataLayer, target: DataLayer) -> None:
    assert flow_permitted(source, target)


@pytest.mark.parametrize(
    ("source", "target", "why"),
    [
        (DataLayer.MARKET, DataLayer.PROJECTIONS, "AAV blended into a projection"),
        (DataLayer.MARKET, DataLayer.AVAILABILITY, "AAV blended into p(play)"),
        (DataLayer.MARKET, DataLayer.VALUATION, "clause 2, at any weight"),
        (
            DataLayer.MARKET,
            DataLayer.TERMINAL,
            "clause 5: the draft-day rankings are ours alone",
        ),
        (
            DataLayer.TERMINAL,
            DataLayer.MARKET,
            "R38: our own output laundered back in as market evidence",
        ),
        (DataLayer.TERMINAL, DataLayer.VALUATION, "a composite value re-entering the fusion"),
        (DataLayer.VALUATION, DataLayer.AVAILABILITY, "a fused value re-entering p(play)"),
        (DataLayer.AVAILABILITY, DataLayer.PROJECTIONS, "ADR-002: never conflate the two"),
        (DataLayer.PROJECTIONS, DataLayer.OBSERVATIONS, "a projection is not a fact"),
        (DataLayer.COMPARISON, DataLayer.TERMINAL, "the comparison feeds nothing"),
    ],
)
def test_backward_flow_is_refused(source: DataLayer, target: DataLayer, why: str) -> None:
    assert not flow_permitted(source, target), why


def test_market_and_terminal_are_mutually_unreachable() -> None:
    """Equal rank is doing the work here, and it has to work in both directions.

    They are refused for different reasons — clause 5 one way, R38 the other —
    and a single total order can express at most one of them. This is the test
    that goes red if somebody "tidies" the two onto distinct ranks.
    """
    assert LAYER_RANK[DataLayer.MARKET] == LAYER_RANK[DataLayer.TERMINAL]
    assert not flow_permitted(DataLayer.MARKET, DataLayer.TERMINAL)
    assert not flow_permitted(DataLayer.TERMINAL, DataLayer.MARKET)


# --- the assignment registry ------------------------------------------------


def test_the_live_schema_is_fully_assigned_and_flows_forward() -> None:
    """The real metadata, checked here as well as at import.

    ``db/models/__init__.py`` already calls this, so a violation is an
    ImportError and this test can never be the first thing to see it. It is
    here anyway: if the import-time call is ever removed, the guard survives as
    a test rather than vanishing silently — which is exactly how five tests
    were lost to a refactor with the suite green and the count rising.
    """
    validate_layers(Base.metadata)

    assert set(TABLE_LAYERS) == set(Base.metadata.tables)


def test_the_assignment_covers_a_schema_worth_covering() -> None:
    """A clean report over an empty metadata is the defect, not a pass."""
    assert len(TABLE_LAYERS) >= 40
    assert sum(len(table.foreign_keys) for table in Base.metadata.tables.values()) >= 60


def test_layer_of_refuses_an_unknown_table() -> None:
    with pytest.raises(LayerViolation, match="has no layer"):
        layer_of("expected_games")


def test_an_unassigned_table_is_refused() -> None:
    """The membership rule: a new table arrives unclassified and is rejected."""
    metadata = sa.MetaData()
    sa.Table("players", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("expected_games", metadata, sa.Column("id", sa.Integer, primary_key=True))

    with pytest.raises(LayerViolation, match="expected_games"):
        validate_layer_assignment(metadata)


def test_an_assignment_for_a_table_that_no_longer_exists_is_refused() -> None:
    """A registry rotting into fiction is the other way this decays.

    Checked in both directions because they fail differently: an unassigned
    table is a quantity nobody classified, a stale entry is a register that has
    stopped describing the schema and can no longer be trusted as a whole.
    """
    metadata = sa.MetaData()
    sa.Table("players", metadata, sa.Column("id", sa.Integer, primary_key=True))

    with pytest.raises(LayerViolation, match="not mapped"):
        validate_layer_assignment(metadata)


def test_empty_layers_are_still_empty() -> None:
    """Pinned so the first availability or valuation table is reviewed.

    Not a claim that these layers are unnecessary — they are the half of
    ADR-008 the schema has not reached. When ``expected-games`` lands, this
    goes red and somebody reads the flow rule with a real table in front of
    them instead of the layer quietly acquiring members nobody classified.
    """
    populated = set(TABLE_LAYERS.values())

    assert populated & LAYERS_WITHOUT_TABLES == set(), (
        f"a layer previously recorded as having no tables now has some: "
        f"{sorted(populated & LAYERS_WITHOUT_TABLES)}. Check its flows against "
        f"ADR-008, then remove it from LAYERS_WITHOUT_TABLES."
    )
    assert populated == {DataLayer.OBSERVATIONS, DataLayer.PROJECTIONS, DataLayer.MARKET}


# --- the flow check, driven against synthetic schemas -----------------------


def _two_table_metadata(referencing: str, referenced: str) -> sa.MetaData:
    """A schema where ``referencing`` holds a foreign key into ``referenced``."""
    metadata = sa.MetaData()
    sa.Table(referenced, metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table(
        referencing,
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ref_id", sa.Integer, sa.ForeignKey(f"{referenced}.id")),
    )
    return metadata


@pytest.mark.parametrize(
    ("referencing", "referenced"),
    [
        # The one this whole unit exists for: a published auction value used as
        # an input to a projection.
        ("projections", "published_auction_values"),
        # And to the observation layer, which would corrupt the facts.
        ("player_participation", "published_auction_values"),
        # A projection used as though it were an observed fact.
        ("player_game_logs", "projections"),
    ],
)
def test_a_backward_foreign_key_is_refused(referencing: str, referenced: str) -> None:
    metadata = _two_table_metadata(referencing, referenced)

    with pytest.raises(LayerViolation, match="ADR-008 forbids"):
        validate_layer_flow(metadata)


@pytest.mark.parametrize(
    ("referencing", "referenced"),
    [
        # Market rows may name a player: observations are rank 0 and everything
        # is entitled to consume them.
        ("published_auction_values", "players"),
        ("projections", "players"),
        # Within a layer.
        ("projections", "projection_imports"),
        ("auction_value_imports", "auction_value_sources"),
    ],
)
def test_a_forward_foreign_key_is_accepted(referencing: str, referenced: str) -> None:
    validate_layer_flow(_two_table_metadata(referencing, referenced))


def test_the_flow_check_names_the_column_and_both_layers() -> None:
    """A refusal has to be actionable at speed, not merely correct.

    The first question on seeing this fail is "which key, and which way round".
    An error that says only "layer violation" sends somebody hunting through
    sixty foreign keys under a bid clock.
    """
    metadata = _two_table_metadata("projections", "published_auction_values")

    with pytest.raises(LayerViolation) as caught:
        validate_layer_flow(metadata)

    message = str(caught.value)
    assert "projections.ref_id" in message
    assert "published_auction_values" in message
    assert "market into projections" in message


def test_an_unassigned_table_is_refused_by_the_flow_check_too() -> None:
    """The flow check resolves layers through ``layer_of``, so it cannot skip one.

    Worth pinning separately: a flow check that silently ignored tables it did
    not recognise would report clean on precisely the schema that had just
    grown an unclassified valuation table.
    """
    metadata = _two_table_metadata("expected_games", "published_auction_values")

    with pytest.raises(LayerViolation, match="has no layer"):
        validate_layer_flow(metadata)


# --- the two representations of a layer, kept in agreement ------------------


def _pinned_data_layer_columns() -> dict[str, str]:
    """Tables that also record their layer per row, and the literal each pins.

    Read out of ``Base.metadata`` rather than listed, so a fourth table adopting
    the pattern is covered without anybody widening this. The literal is taken
    from the table's own CHECK constraint, which is what the database actually
    enforces — reading the Python-side column default instead would compare the
    ORM against the ORM.
    """
    found: dict[str, str] = {}
    for table in Base.metadata.tables.values():
        if "data_layer" not in table.c:
            continue
        for constraint in table.constraints:
            if not isinstance(constraint, sa.CheckConstraint):
                continue
            expression = str(constraint.sqltext)
            if expression.startswith("data_layer = '") and expression.endswith("'"):
                found[table.name] = expression.split("'")[1]
    return found


def test_the_pinned_data_layer_columns_were_found_at_all() -> None:
    """Three tables carry one today; a scan finding none is broken, not clean."""
    pinned = _pinned_data_layer_columns()

    assert set(pinned) == {
        "absence_splits",
        "auction_value_sources",
        "published_auction_values",
    }


def test_data_layer_columns_agree_with_the_registry() -> None:
    """The per-row literal and the per-table assignment cannot drift apart.

    Two places recording one fact is how a fact becomes two facts. These
    columns predate the registry, so the agreement is checked rather than
    assumed — and the literals are ``'observations'`` and ``'market'``, which is
    why :class:`DataLayer` carries ``MARKET`` as a member instead of renaming
    what the database already stores.
    """
    for table_name, literal in _pinned_data_layer_columns().items():
        assert literal in set(DataLayer), f"{table_name} pins an unknown layer {literal!r}"
        assert TABLE_LAYERS[table_name] == DataLayer(literal), (
            f"{table_name} stores data_layer={literal!r} per row but TABLE_LAYERS "
            f"assigns it {TABLE_LAYERS[table_name]}"
        )


def test_the_scope_limits_are_stated() -> None:
    """Asserted, not narrated, so deleting one breaks a test.

    :data:`FLOW_SCAN_LIMIT` is the honest gap: this reads declared foreign
    keys, and a value copied between layers in Python leaves no key behind.
    :data:`GRAIN_LIMIT` is the other: a layer is assigned per table.
    """
    assert "foreign keys" in FLOW_SCAN_LIMIT
    assert "Python" in FLOW_SCAN_LIMIT
    assert "one layer per table" in GRAIN_LIMIT


# --- the stored registry ----------------------------------------------------


@pytest.fixture
def migration_url(tmp_path: Path, test_database_url: str | None) -> str:
    return test_database_url or f"sqlite:///{(tmp_path / 'layers.db').as_posix()}"


@pytest.fixture
def alembic_config(backend_dir: Path, migration_url: str) -> Config:
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    # config.attributes, not set_main_option: a URL containing '%' raises on
    # read through ConfigParser's BasicInterpolation.
    config.attributes["sqlalchemy_url"] = migration_url
    return config


@pytest.fixture(autouse=True)
def _clean_database(migration_url: str) -> Iterator[None]:
    """Leave no tables behind. A Postgres test database is reused across tests."""
    yield
    engine = create_engine(migration_url)
    try:
        Base.metadata.drop_all(engine)
        with engine.connect() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
            connection.commit()
    finally:
        engine.dispose()


def test_a_migrated_store_records_every_table_at_its_assigned_layer(
    alembic_config: Config, migration_url: str
) -> None:
    """The database's answer and the code's answer, compared row by row.

    The migration seeds a literal snapshot rather than importing
    ``TABLE_LAYERS``, so this comparison is between two independently written
    things. That is the point: a table added to the code without a migration
    fails here, which is what forces a layer assignment through review instead
    of letting it default.
    """
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        with Session(engine) as session:
            stored = {
                row.table_name: (row.data_layer, row.layer_rank)
                for row in session.query(DataLayerRegistry).all()
            }
    finally:
        engine.dispose()

    expected = {name: (layer, LAYER_RANK[layer]) for name, layer in TABLE_LAYERS.items()}

    assert stored == expected, (
        "the stored layer registry and TABLE_LAYERS disagree. If a table was "
        "added, assign its layer in db/layers.py and seed its row in a new "
        "migration; the seed is a snapshot on purpose and never imports the code."
    )


def test_the_registry_records_itself(alembic_config: Config, migration_url: str) -> None:
    """A register that omits itself is a register with one unaudited member."""
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        with Session(engine) as session:
            row = session.get(DataLayerRegistry, "data_layer_registry")
    finally:
        engine.dispose()

    assert row is not None
    assert row.data_layer == DataLayer.OBSERVATIONS


def test_a_migrated_store_refuses_an_unknown_layer(
    alembic_config: Config, migration_url: str
) -> None:
    """The CHECK, driven through raw SQL rather than the ORM.

    ``portable_enum`` emits a VARCHAR plus a CHECK precisely so a bad value
    fails in the database. The ORM's own ``validate_strings`` covers the ORM
    path and nothing else — not ``text()``, not a data migration, not a bulk
    load — so the constraint is exercised the way a bad write would actually
    arrive.
    """
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO data_layer_registry (table_name, data_layer, layer_rank) "
                    "VALUES ('expected_games', 'vibes', 2)"
                )
            )
            connection.commit()
    finally:
        engine.dispose()


def test_the_migration_downgrades_cleanly(alembic_config: Config, migration_url: str) -> None:
    """Forward-only in practice still means reversible when it has to be.

    This runs on the owner's machine mid-season; a migration that cannot be
    stepped back is an outage with no exit.
    """
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "0018")

    engine = create_engine(migration_url)
    try:
        assert "data_layer_registry" not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        with Session(engine) as session:
            assert session.query(DataLayerRegistry).count() == len(TABLE_LAYERS)
    finally:
        engine.dispose()
