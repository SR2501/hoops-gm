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

**Scope limits are asserted, not narrated.** ``FLOW_SCAN_LIMIT``,
``IMPORT_TIME_LIMIT`` and ``GRAIN_LIMIT`` are pinned by
:func:`test_the_scope_limits_are_stated`, because a limitation in a docstring
gets summarised away and a limitation behind an assertion breaks a test when
someone deletes it.

**Several of these exist because an independent review broke the first
version.** It gutted ``validate_layers`` to a no-op and watched all 44 tests
pass; it emptied ``LAYERS_WITHOUT_TABLES`` and watched all 44 pass; and it found
that the rank-based flow rule permitted ``valuation -> market``, which is R38.
Where a test below says what review drove, that is why it is there.
"""

from __future__ import annotations

import ast
import importlib.util
import itertools
import subprocess
import sys
import textwrap
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.db import models
from hoops_gm.db.base import Base
from hoops_gm.db.layers import (
    FLOW_MATRIX_SIZE,
    FLOW_SCAN_LIMIT,
    GRAIN_LIMIT,
    IMPORT_TIME_LIMIT,
    LAYER_RANK,
    LAYERS_WITHOUT_TABLES,
    MARKET_IDENTITY_SOURCES,
    PERMITTED_FLOWS,
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
    """observations -> projections -> availability -> valuation -> terminal.

    :data:`LAYER_RANK` is descriptive — :func:`flow_permitted` does not consult
    it — so this pins the *label*, and the flow tests below pin the rule. Both
    are worth having: a rank that disagreed with the edges would mislead
    anybody reading ``data_layer_registry.layer_rank`` in a raw query, which is
    the one thing that column exists for.
    """
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

    for earlier, later in itertools.pairwise(pipeline):
        assert flow_permitted(earlier, later)
        assert not flow_permitted(later, earlier)


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
        # The three review found open under the old rank rule. Each is R38
        # through a different door, and each type-checked when the rule was
        # `rank[source] < rank[target]` — the market's rank really is higher.
        (
            DataLayer.VALUATION,
            DataLayer.MARKET,
            "R38: a fused value of ours recorded as market evidence",
        ),
        (
            DataLayer.AVAILABILITY,
            DataLayer.MARKET,
            "clause 3: divergence is only a signal if the sides are independent",
        ),
        (
            DataLayer.PROJECTIONS,
            DataLayer.MARKET,
            "clause 3: our projection is not part of what somebody else published",
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
    """Refused in both directions, for different reasons.

    ``market -> terminal`` is clause 5, the draft-day rankings are ours alone;
    ``terminal -> market`` is R38. An earlier revision achieved this by giving
    the two an equal rank and refusing cross-layer flow at equal rank, which
    worked for this pair and quietly permitted ``valuation -> market``. The
    edge set states both refusals without implying anything about the rest.
    """
    assert not flow_permitted(DataLayer.MARKET, DataLayer.TERMINAL)
    assert not flow_permitted(DataLayer.TERMINAL, DataLayer.MARKET)


def test_the_market_consumes_nothing_we_derived() -> None:
    """ADR-008 clause 3, stated as the closed set it actually is.

    "Compared against, never blended in" is a claim about independence: our
    number and the market's mean something together only because neither was
    computed from the other. So the market side may consume identity — a
    published value has to say which player it is about — and nothing else of
    ours, at any weight. This is the finding an independent review raised
    against the rank construction, and the assertion is written over *every*
    layer rather than the four that exist today so a new one cannot slip in.

    The layer edge alone is not enough to say "identity", which a second review
    demonstrated: ``OBSERVATIONS`` is 29 tables, and permitting the layer
    permits ``draft_events`` — prices our own recommendations can have moved —
    and ``absence_splits``, which we compute. So the tables are asserted too.
    """
    inbound = {source for source, target in PERMITTED_FLOWS if target is DataLayer.MARKET}

    assert inbound == {DataLayer.OBSERVATIONS}, (
        f"the market layer accepts {sorted(inbound)}. Anything beyond observations "
        f"destroys the independence ADR-008 clause 3 relies on."
    )

    observations = {name for name, layer in TABLE_LAYERS.items() if layer is DataLayer.OBSERVATIONS}
    assert observations > MARKET_IDENTITY_SOURCES, (
        "MARKET_IDENTITY_SOURCES must be a strict subset of the observations "
        "tables; if it ever equals them the narrowing has stopped narrowing."
    )
    assert not (MARKET_IDENTITY_SOURCES & {"draft_events", "absence_splits"}), (
        "draft_events holds prices our own recommendations can have caused and "
        "absence_splits is an aggregate we compute. Neither is identity, and "
        "letting the market reference either is R38 through a side door."
    )


@pytest.mark.parametrize("referenced", ["draft_events", "absence_splits", "player_game_logs"])
def test_the_market_may_not_reference_an_observation_that_is_not_identity(
    referenced: str,
) -> None:
    """The narrowing, driven rather than asserted about the constant.

    Seeding an auction value table from observed clearing prices is a plausible
    future feature and type-checks today. Under the layer edge alone it was
    accepted; each of these is now refused.
    """
    with pytest.raises(LayerViolation, match="identity only"):
        validate_layer_flow(_two_table_metadata("published_auction_values", referenced))


def test_the_market_may_still_say_which_player_it_is_about() -> None:
    """The narrowing must not break the case the edge exists for."""
    validate_layer_flow(_two_table_metadata("published_auction_values", "players"))


def test_comparison_feeds_nothing() -> None:
    """A property of the edge set, not a side effect of holding the top rank.

    Under the old rank rule this held only because ``comparison`` was the
    highest number; an eighth layer above it would have silently opened
    ``comparison -> <new>``. Here it is stated, so it survives a new member.
    """
    outbound = {target for source, target in PERMITTED_FLOWS if source is DataLayer.COMPARISON}

    assert outbound == set()


def test_the_flow_matrix_is_completely_decided() -> None:
    """Every ordered pair of distinct layers has a verdict, and the size is pinned.

    ``FLOW_MATRIX_SIZE`` is the ``SCAN_LIMIT`` pattern applied to the rule
    itself: an eighth layer changes the count and turns this red, so nobody can
    add one without deciding its fourteen new edges. An unlisted pair is
    refused, which is the safe default — the pin is what makes it a *reviewed*
    default rather than an unnoticed one.
    """
    pairs = [(a, b) for a in DataLayer for b in DataLayer if a is not b]

    assert len(pairs) == FLOW_MATRIX_SIZE, (
        f"the layer vocabulary changed: {len(pairs)} ordered pairs, not "
        f"{FLOW_MATRIX_SIZE}. Decide each new edge in PERMITTED_FLOWS, then "
        f"update FLOW_MATRIX_SIZE."
    )
    assert set(pairs) >= PERMITTED_FLOWS, "PERMITTED_FLOWS lists a same-layer pair"

    permitted = {pair for pair in pairs if flow_permitted(*pair)}
    assert permitted == set(PERMITTED_FLOWS)

    for layer in DataLayer:
        assert flow_permitted(layer, layer), "ADR-008 clause 1: aggregate within a layer"


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
    """A clean report over an empty metadata is the defect, not a pass.

    Read this as a floor on the *scan*, not on the enforcement. Review counted
    how many of those foreign keys are actually cross-layer: **5 of 62** at
    ``f3e2c53``, four of them identity references. The other 57 are within-layer
    and permitted unconditionally by ADR-008 clause 1. So this asserts that the
    check is looking at a real schema, not that sixty relationships are being
    constrained — the guard constrains almost nothing that exists today and is
    here to fail on arrival when ``expected-games`` and the valuation chain land.
    """
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

    # The invariant that makes the constant load-bearing rather than decorative.
    # Without it, review gutted LAYERS_WITHOUT_TABLES to frozenset() and all 44
    # tests still passed: the two assertions above are both satisfied by an
    # empty set. This one is not, and it also forces an eighth DataLayer member
    # to be classified as populated or empty rather than described by neither.
    assert populated | LAYERS_WITHOUT_TABLES == set(DataLayer), (
        f"LAYERS_WITHOUT_TABLES has stopped describing which layers are empty: "
        f"{sorted(set(DataLayer) - (populated | LAYERS_WITHOUT_TABLES))} is in "
        f"neither set."
    )
    assert populated & LAYERS_WITHOUT_TABLES == set()


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

    :data:`FLOW_SCAN_LIMIT` is the honest gap in the flow check: declared
    foreign keys only, so an undeclared identifier column or a value copied in
    Python leaves no key behind. :data:`IMPORT_TIME_LIMIT` is the gap in *when*
    the check runs. :data:`GRAIN_LIMIT` is the gap in what an assignment
    covers: one layer per table.

    These pin documentation rather than behaviour — widening a scan to close a
    gap would leave the assertion untouched. That is inherent to the pattern,
    and it is why each constant names what remains uncovered.
    """
    assert "foreign keys" in FLOW_SCAN_LIMIT
    assert "undeclared identifier column" in FLOW_SCAN_LIMIT
    assert "Python" in FLOW_SCAN_LIMIT
    assert "when db.models finishes importing" in IMPORT_TIME_LIMIT
    assert "not by reading how the imports are spelled" in IMPORT_TIME_LIMIT
    assert "one layer per table" in GRAIN_LIMIT


# --- the enforcement point itself -------------------------------------------


def _models_package_source() -> str:
    return (Path(models.__file__).resolve()).read_text(encoding="utf-8")


def test_the_package_still_calls_the_validator_at_import() -> None:
    """The one line whose deletion disarms everything, pinned.

    ``validate_layers`` is what the enforcement point calls, and review drove
    the two ways that goes quiet: gut the function and all tests pass, or delete
    the call and nothing fails at all. The subprocess test below closes the
    first. This closes the second, and it has to be a source assertion — the
    call runs at import, so by the time any test observes the module it has
    already either happened or not, with no trace either way.

    Parsed rather than grepped. The first version of this test asked whether
    ``"validate_layers(Base.metadata)"`` appeared in the file, and a mutation
    that commented the line out passed it: the substring was still there, inside
    a ``#``. Asking the AST for a module-level call is the closed-set version of
    the same question, and it cannot be satisfied by text that does not run.
    """
    tree = ast.parse(_models_package_source())
    called = {
        node.value.func.id
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    }

    assert "validate_layers" in called, (
        "db/models/__init__.py no longer calls validate_layers at module level. "
        "ADR-008 asks for this to be inexpressible rather than documented; "
        "without the call a backwards foreign key is merely a failing test "
        "somebody can skip, and a commented-out call is not a call."
    )


def test_every_refusal_says_what_to_do_and_why_the_rule_exists() -> None:
    """The failure message is the entire user interface for this guard.

    Three other lanes will meet this check on their next rebase, mid-conflict,
    having read none of the reasoning. A rule whose purpose is invisible at the
    moment it fires gets deleted by somebody acting reasonably — so every
    refusal has to name the file to edit, the ADR, and the reason the rule is
    an ImportError rather than a lint.

    This asserts the property over all three refusal paths rather than spot-
    checking one, because the one that goes stale is the one nobody read.
    """
    unassigned = sa.MetaData()
    sa.Table("expected_games", unassigned, sa.Column("id", sa.Integer, primary_key=True))

    stale = sa.MetaData()
    for name in TABLE_LAYERS:
        sa.Table(name, stale, sa.Column("id", sa.Integer, primary_key=True))
    stale.remove(stale.tables["players"])

    messages: dict[str, str] = {}
    refusals: tuple[tuple[str, Callable[[], None]], ...] = (
        ("unassigned table", lambda: validate_layer_assignment(unassigned)),
        ("stale entry", lambda: validate_layer_assignment(stale)),
        (
            "backwards flow",
            lambda: validate_layer_flow(
                _two_table_metadata("projections", "published_auction_values")
            ),
        ),
    )
    for label, call in refusals:
        with pytest.raises(LayerViolation) as caught:
            call()
        messages[label] = str(caught.value)

    for label, message in messages.items():
        assert "db/layers.py" in message, f"{label} does not say which file to edit"
        assert "What to do" in message, f"{label} does not say what to do"

    assert "ADR-008" in messages["backwards flow"]
    assert "circularity" in messages["backwards flow"]
    assert "circularity" in messages["unassigned table"]
    # The stale-entry path is the one that fails an exemption outliving its
    # cause, so it has to explain that rather than just naming the tables.
    assert "census" in messages["stale entry"]

    # A refusal is only a user interface if it arrives legible. These reach
    # their reader through stderr on a Windows console during a rebase, and
    # cp1252 renders a non-ASCII character as mojibake. The repository already
    # has a guard for this in test_console_encoding.py, but its domain is
    # assert messages, print and sys.exit - it does not walk `raise`, so it
    # saw none of these three. That gap is reported rather than widened here:
    # broadening a shared scan would fail other lanes' code mid-freeze.
    for label, message in messages.items():
        outside_ascii = sorted({character for character in message if ord(character) > 127})
        assert outside_ascii == [], (
            f"the {label} refusal contains {[hex(ord(c)) for c in outside_ascii]}, "
            f"which a cp1252 console garbles. This message is the whole interface "
            f"for a lane meeting the rule mid-rebase; use ASCII in it."
        )


def test_the_model_and_migration_agree_on_the_layer_rank_check(backend_dir: Path) -> None:
    """One constraint, written twice on purpose, so it has to be compared.

    ``models/layers.py`` builds the expression from ``LAYER_RANK``; ``0019``
    carries it as a literal. That duplication is the review gate — the same
    reasoning that keeps the seed rows literal — but a gate nobody checks is
    just drift with extra steps.

    It needs its own test because neither existing test sees a divergence:
    Alembic does not compare CHECK constraints, so ``test_models_and_migrations
    _agree`` is silent, and the migrated-store tests exercise the migration's
    copy only. Review drove exactly this: weakening the model's constraint to
    ``layer_rank >= 0`` left every test green, which means a store built from
    ``Base.metadata.create_all`` would accept rows the migrated one refuses.

    Read off ``__table__`` rather than from :func:`_layer_rank_pairs`. A first
    version called the helper and compared *that* to the migration, which still
    passed when the constraint stopped using the helper — it was checking that
    two strings agreed, not that the table carried either of them.
    """
    table = Base.metadata.tables["data_layer_registry"]
    checks = {
        str(constraint.name): str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    name = "ck_data_layer_registry_layer_rank_matches_layer"

    assert name in checks, (
        f"the mapped table has no {name} constraint. Its constraints are "
        f"{sorted(checks)}. Without it a models-created store accepts a row whose "
        f"rank contradicts its layer."
    )
    assert checks[name] == _load_0019(backend_dir)._LAYER_RANK_PAIRS, (
        "the layer/rank CHECK on the mapped table and in migration 0019 have "
        "diverged. A database created from the models would then accept rows a "
        "migrated database refuses, and the registry's whole promise is that the "
        "store answers correctly without the source tree."
    )
    for layer, rank in LAYER_RANK.items():
        assert f"data_layer = '{layer.value}' AND layer_rank = {rank}" in checks[name]


def test_a_backwards_foreign_key_makes_the_package_fail_to_import() -> None:
    """The claim "you cannot write it and still have a program", driven.

    Runs in a subprocess because the failure being asserted is an ImportError
    for a module this test session has already imported successfully; in-process
    there is nothing left to fail. The child maps a violating table onto
    ``Base.metadata`` and re-runs the validator the package runs, which is the
    same call on the same metadata the real import path uses.
    """
    program = textwrap.dedent(
        """
        import sqlalchemy as sa
        from sqlalchemy.orm import Mapped, mapped_column

        from hoops_gm.db.base import Base
        from hoops_gm.db.layers import TABLE_LAYERS, DataLayer, validate_layers

        class ExpectedGames(Base):
            __tablename__ = "expected_games"
            id: Mapped[int] = mapped_column(primary_key=True)
            seed_aav_id: Mapped[int] = mapped_column(
                sa.ForeignKey("published_auction_values.id")
            )

        TABLE_LAYERS["expected_games"] = DataLayer.AVAILABILITY
        validate_layers(Base.metadata)
        print("NO VIOLATION RAISED")
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", f"import hoops_gm.db.models\n{program}"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0, (
        f"a market table seeded into an availability table was accepted. "
        f"stdout={completed.stdout!r}"
    )
    assert "NO VIOLATION RAISED" not in completed.stdout
    assert "LayerViolation" in completed.stderr
    assert "published_auction_values" in completed.stderr


def test_importing_the_package_is_what_refuses_a_violation() -> None:
    """The headline claim, driven against the package rather than the function.

    :func:`test_a_backwards_foreign_key_makes_the_package_fail_to_import`
    imports the package and then calls ``validate_layers`` itself, so it proves
    the *function* refuses. That is not the claim. The claim is that **importing
    the package** refuses, and review showed those come apart: replacing the
    import of ``validate_layers`` in ``db/models/__init__.py`` with a local
    no-op of the same name left every gate green — 57 tests, ruff and mypy —
    while the package imported a violating schema without complaint. The AST
    test could not see it, because the call site still reads exactly right.

    So this asks the package. It injects the violation by removing an entry
    from ``TABLE_LAYERS`` **before** ``db.models`` is imported, which is the
    cheapest violation that needs no schema of its own, and then imports the
    package and nothing else. Whatever the call site is spelled as, either the
    import raises or this fails.
    """
    program = textwrap.dedent(
        """
        import hoops_gm.db.layers as layers

        del layers.TABLE_LAYERS["players"]

        import hoops_gm.db.models  # noqa: E402

        print("NO VIOLATION RAISED")
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0, (
        f"importing db.models with an unassigned table succeeded. The package "
        f"is not enforcing ADR-008 at import, whatever its call site says - "
        f"check that db/models/__init__.py calls the real "
        f"hoops_gm.db.layers.validate_layers and has not shadowed it.\n"
        f"stdout={completed.stdout!r}"
    )
    assert "NO VIOLATION RAISED" not in completed.stdout
    assert "LayerViolation" in completed.stderr, (
        f"the import failed for some reason other than a layer violation, so "
        f"this test is no longer evidence of anything.\nstderr={completed.stderr!r}"
    )
    assert "players" in completed.stderr


def test_every_model_module_is_reached_by_importing_the_package() -> None:
    """Close the set over the filesystem, and read the artefact not the spelling.

    :func:`validate_layers` sees whatever is mapped when the package finishes
    importing, so a model module missing from ``__init__.py`` is a table the
    check never meets — and importing that submodule directly runs the parent
    package first, validating incomplete metadata, then maps the table with
    nothing left to check it.

    Two earlier versions of this test were defeated in review, both by asking
    about the *spelling* of the import rather than its *effect*:

    - A substring test for ``from hoops_gm.db.models.<name> import`` is
      satisfied by that line commented out. This is the same defect the AST
      test for the call site exists to fix, and it survived here.
    - A non-recursive ``glob("*.py")`` cannot see ``db/models/valuation/``, a
      very likely real directory given the layers this ADR is about, while
      :data:`IMPORT_TIME_LIMIT` claimed the residual gap was modules *outside*
      ``db/models/``. A false limit statement is worse than a missing one.

    So this asks the only question that cannot be worded around: after
    importing the package and nothing else, is there any module on disk that
    still has tables left to map? Importing an already-imported module is a
    no-op via ``sys.modules``, so a module the package reached contributes
    nothing here and one it missed contributes its tables. Comments, aliases,
    re-exports, star imports and subpackages all come out in the wash.

    Runs in a subprocess because it deliberately maps stray tables onto
    ``Base.metadata``, which would leak into every later test in the session.
    """
    program = textwrap.dedent(
        """
        import importlib
        import pathlib

        import hoops_gm.db.models
        from hoops_gm.db.base import Base

        package_dir = pathlib.Path(hoops_gm.db.models.__file__).resolve().parent
        reached = set(Base.metadata.tables)
        scanned = 0

        for path in sorted(package_dir.rglob("*.py")):
            if path == package_dir / "__init__.py" or path.stem.startswith("_"):
                continue
            relative = path.relative_to(package_dir)
            parts = relative.parts[:-1] if path.name == "__init__.py" else (
                *relative.parts[:-1],
                path.stem,
            )
            if not parts:
                continue
            scanned += 1
            importlib.import_module("hoops_gm.db.models." + ".".join(parts))
            stray = sorted(set(Base.metadata.tables) - reached)
            if stray:
                print("STRAY " + ".".join(parts) + " " + ",".join(stray))
                reached |= set(stray)

        print("SCANNED", scanned)
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, (
        f"scanning db/models/ for unreached modules failed outright.\n"
        f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}"
    )

    stray = [line for line in completed.stdout.splitlines() if line.startswith("STRAY ")]
    scanned = [line for line in completed.stdout.splitlines() if line.startswith("SCANNED ")]

    assert scanned and int(scanned[0].split()[1]) > 0, (
        f"no model modules found; this scan is broken, not clean. stdout={completed.stdout!r}"
    )
    assert stray == [], (
        f"model modules whose tables importing the package does not map: {stray}. "
        f"Import each from db/models/__init__.py. Until then validate_layers "
        f"never sees those tables, so they are outside ADR-008 entirely, and "
        f"they silently never get a migration either."
    )


# --- the stored registry ----------------------------------------------------

#: Rows migration ``0019`` seeded, as a historical fact rather than a mirror.
#:
#: Pinned here rather than derived from ``TABLE_LAYERS`` because the two are
#: allowed to diverge the moment a ``0020`` adds a table: the code tracks the
#: schema, the seed records what ``0019`` did. See
#: :func:`test_the_0019_seed_is_a_frozen_snapshot`.
_SEED_ROWS_AT_0019 = 40


def _load_0019(backend_dir: Path) -> ModuleType:
    """Import migration ``0019`` by path.

    ``alembic/versions`` is not an importable package and ``0019_layer_registry``
    is not a valid identifier, so this goes through the loader directly rather
    than ``import_module``.
    """
    path = backend_dir / "alembic" / "versions" / "0019_layer_registry.py"
    spec = importlib.util.spec_from_file_location("migration_0019", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    """Start from an empty store. A Postgres test database is reused across tests.

    Drops *before* rather than after, matching ``conftest.py``'s established
    convention. The difference matters when ``TEST_DATABASE_URL`` points at a
    database another lane is also using: a teardown drop is the operation that
    reaches into somebody else's run, and it also leaves nothing to inspect when
    a test fails. Dropping on the way in gives the same isolation without
    either.
    """
    engine = create_engine(migration_url)
    try:
        Base.metadata.drop_all(engine)
        with engine.connect() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
            connection.commit()
    finally:
        engine.dispose()
    yield


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


def test_the_0019_seed_is_a_frozen_snapshot(backend_dir: Path) -> None:
    """The count is pinned so the tempting fix to a drift failure goes red.

    Found by review. When a new table lands,
    ``test_a_migrated_store_records_every_table_at_its_assigned_layer`` fails,
    and there are two ways to make it pass: add a new migration inserting the
    row, or add a line to ``0019``'s seed. Both are green **from an empty
    database**, which is the only place that test looks — but the owner's store
    is stamped at ``0019`` and will never run it again, so only the first fixes
    the store the registry exists to be interrogated from.

    So the seed's shape is pinned here as a historical fact. Editing it breaks
    this test and the failure says which route to take.
    """
    seed = _load_0019(backend_dir)._SEED

    assert len(seed) == _SEED_ROWS_AT_0019, (
        f"migration 0019's seed has {len(seed)} rows, not {_SEED_ROWS_AT_0019}. "
        f"0019 is already applied on the owner's store and will not run again, "
        f"so a row added here never reaches it. Add a new migration instead, and "
        f"only change this number if you are correcting the historical record."
    )
    assert len({name for name, _, _ in seed}) == len(seed), "0019 seeds a table twice"
    for name, layer, rank in seed:
        assert layer in set(DataLayer), f"0019 seeds {name} at unknown layer {layer!r}"
        assert LAYER_RANK[DataLayer(layer)] == rank, (
            f"0019 seeds {name} at {layer!r} with rank {rank}, which is not that "
            f"layer's rank. The CHECK added in 0019 would reject this row."
        )


def test_a_migrated_store_refuses_a_rank_that_disagrees_with_its_layer(
    alembic_config: Config, migration_url: str
) -> None:
    """The layer and the rank are one fact stored twice, pinned by CHECK.

    Raised by review: ``layer_rank`` exists so a raw query can order layers
    without importing Python, and before this constraint the only rule was
    ``>= 0`` — so ``('expected_games', 'terminal', 0)`` was accepted. A store
    that can disagree with itself is no use at the moment it is being consulted,
    which is the moment this table exists for.
    """
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO data_layer_registry (table_name, data_layer, layer_rank) "
                    "VALUES ('expected_games', 'terminal', 0)"
                )
            )
            connection.commit()
    finally:
        engine.dispose()


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
