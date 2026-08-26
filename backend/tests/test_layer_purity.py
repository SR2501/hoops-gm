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
import hashlib
import importlib.util
import itertools
import re
import subprocess
import sys
import textwrap
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.db import layers, models
from hoops_gm.db.base import Base
from hoops_gm.db.layers import (
    FLOW_MATRIX_SIZE,
    FLOW_SCAN_LIMIT,
    GRAIN_LIMIT,
    IMPORT_TIME_LIMIT,
    LAYER_RANK,
    LAYERS_WITHOUT_TABLES,
    MARKET_IDENTITY_REASONS,
    MARKET_IDENTITY_SOURCES,
    NAKED_IDENTIFIER_COLUMNS,
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
from hoops_gm.db.models import DataLayerFlow, DataLayerRegistry

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


def _metadata_for(names: Iterable[str]) -> sa.MetaData:
    """A metadata carrying exactly ``names``, one trivial table each."""
    metadata = sa.MetaData()
    for name in names:
        sa.Table(name, metadata, sa.Column("id", sa.Integer, primary_key=True))
    return metadata


def _with_table_layers(replacement: dict[str, DataLayer], call: Callable[[], None]) -> None:
    """Run ``call`` with ``TABLE_LAYERS`` temporarily holding ``replacement``.

    Restores in a ``finally`` and by mutation rather than rebinding, because
    every other module holds the same dict object by reference.
    """
    original = dict(TABLE_LAYERS)
    TABLE_LAYERS.clear()
    TABLE_LAYERS.update(replacement)
    try:
        call()
    finally:
        TABLE_LAYERS.clear()
        TABLE_LAYERS.update(original)


@pytest.mark.parametrize("how", ["unmapped", "moved to another layer"])
def test_a_stale_market_identity_exemption_is_refused(
    how: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exemption set may not outlive its cause, driven on both disjuncts.

    :data:`MARKET_IDENTITY_SOURCES` is the only thing narrowing the
    observations-to-market edge from 29 tables to identity. Its docstring
    claimed a stale entry fails at import, and a third review found **no test
    drove that branch at all**: the constant appeared in this file only in set
    assertions about its contents. Replacing the generator with an empty list
    left all 62 tests, ruff and mypy green. That is the exact defect class this
    unit exists to prevent, written into the unit itself.

    Both arms, because the two disjuncts at the raise site are independently
    deletable. An entry can go stale by the table disappearing, or by the table
    surviving and being reclassified - the second is the quieter one, because
    the schema still contains the name and only its meaning has moved.

    The unmapped arm has to remove the entry from ``TABLE_LAYERS`` as well.
    Otherwise the *vanished* check fires first and this passes while proving a
    different branch.
    """
    if how == "unmapped":
        monkeypatch.delitem(TABLE_LAYERS, "players")
        metadata = _metadata_for(TABLE_LAYERS)
    else:
        monkeypatch.setitem(TABLE_LAYERS, "players", DataLayer.VALUATION)
        metadata = _metadata_for(TABLE_LAYERS)

    with pytest.raises(LayerViolation, match="no longer mapped observations tables") as caught:
        validate_layer_assignment(metadata)

    message = str(caught.value)
    assert "players" in message
    assert "MARKET_IDENTITY_SOURCES" in message
    assert "db/layers.py" in message


_NON_IDENTITY_OBSERVATIONS = sorted(
    name
    for name, layer in TABLE_LAYERS.items()
    if layer is DataLayer.OBSERVATIONS and name not in MARKET_IDENTITY_SOURCES
)


def test_the_non_identity_probe_set_is_worth_probing() -> None:
    """A clean sweep over an empty domain is not a pass.

    The parametrisation below is derived, so if the derivation ever yields
    nothing - a renamed layer, an emptied ``TABLE_LAYERS`` - pytest reports
    zero cases and stays green. Count the domain before believing the sweep.
    """
    assert len(_NON_IDENTITY_OBSERVATIONS) > 20, (
        f"only {len(_NON_IDENTITY_OBSERVATIONS)} non-identity observations tables "
        f"found; the derivation is wrong and the sweep below proves nothing"
    )


@pytest.mark.parametrize("referenced", _NON_IDENTITY_OBSERVATIONS)
def test_the_market_may_not_reference_an_observation_that_is_not_identity(
    referenced: str,
) -> None:
    """The narrowing, driven rather than asserted about the constant.

    Seeding an auction value table from observed clearing prices is a plausible
    future feature and type-checks today. Under the layer edge alone it was
    accepted; each of these is now refused.

    Parametrised over **every** observations table outside
    :data:`MARKET_IDENTITY_SOURCES`, not over a hand-picked three. A third
    review defeated the hand-picked version by adding ``player_season_stats``
    to the allowlist: 62 tests, ruff and mypy stayed green while a market row
    became seedable from observed season totals. Three probes plus a two-name
    denylist is exactly the "enumerate the doors you currently know" shape this
    repository keeps getting caught by. Deriving the probes from the layer
    closes the set: a new observations table is probed the day it is added, and
    moving one into the allowlist deletes its own probe, which is visible in
    the collected test count.
    """
    with pytest.raises(LayerViolation, match="identity only"):
        validate_layer_flow(_two_table_metadata("published_auction_values", referenced))


def test_every_market_identity_exemption_carries_a_written_reason() -> None:
    """An exemption nobody had to justify is an exemption nobody reviewed.

    The pattern is ``SANCTIONED_STORE_OPENERS``: a reason per entry, and the
    key sets must match exactly, so an entry cannot be added without writing
    why and cannot be removed while leaving its justification behind. This does
    not make a wrong addition impossible - nothing in a test can read whether a
    sentence is true - but it makes it a thing somebody wrote a claim to
    support, which is the moment review has something to disagree with.
    """
    assert set(MARKET_IDENTITY_REASONS) == set(MARKET_IDENTITY_SOURCES), (
        f"MARKET_IDENTITY_REASONS and MARKET_IDENTITY_SOURCES disagree: "
        f"{sorted(set(MARKET_IDENTITY_REASONS) ^ set(MARKET_IDENTITY_SOURCES))}. "
        f"Every exemption from the observations-to-market narrowing needs a "
        f"written reason in backend/src/hoops_gm/db/layers.py, and a reason "
        f"must not outlive the exemption it justified."
    )
    for name, reason in MARKET_IDENTITY_REASONS.items():
        assert len(reason) > 60, (
            f"the reason given for exempting {name!r} is too short to be a "
            f"reason. Say what the table holds and why none of it is a "
            f"quantity a market row could be seeded from."
        )


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
    refused, which is the safe default - the pin is what makes it a *reviewed*
    default rather than an unnoticed one.

    **The falsifying reading, and why it lands safe.** Name the defect this
    excludes - "a layer arrives and its edges are never reviewed" - then name a
    reading in which the assertion passes and the defect is present: add
    ``SOURCE_PROJECTIONS``, read the failure message, and do the mechanical
    half of what it says by editing ``42`` to ``56`` without touching
    ``PERMITTED_FLOWS``. Green, fourteen edges undecided. The message even
    volunteers that edit, which is the shape worth distrusting: a guard that
    tells you how to silence it.

    What saves it is not this pin. It is that ``flow_permitted`` is an
    allowlist, so **an enum member cannot add a permission** - every undecided
    edge is refused, and the first declared foreign key crossing it raises at
    import. The residual defect is over-refusal, which is loud and immediate,
    not a wrong number. That asymmetry is the reason an explicit
    ``REFUSED_FLOWS`` with a written reason per edge was considered and not
    built: it would convert fourteen silencing keystrokes into fourteen
    authored lines a reviewer can see, but it buys no safety the allowlist
    default does not already give, and twenty-five refusal reasons that mostly
    read "backwards" is documentation nobody rereads.
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

    # Bare names, not the ``metadata.tables`` keys. Those are "schema.name"
    # when a schema is set, and ``validate_layer_assignment`` deliberately
    # keys on ``.name`` for that reason. Comparing the qualified keys here
    # would undo that care one line below the call that takes it: the day
    # someone sets a Postgres schema the validator keeps working exactly as
    # designed and this fails for a reason unrelated to layer purity.
    assert set(TABLE_LAYERS) == {table.name for table in Base.metadata.tables.values()}


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


def _tables_with_a_data_layer_column() -> set[str]:
    """Every table carrying a ``data_layer`` column, by column not by CHECK."""
    return {table.name for table in Base.metadata.tables.values() if "data_layer" in table.c}


def _pinned_data_layer_columns() -> dict[str, str]:
    """Tables that also record their layer per row, and the literal each pins.

    Read out of ``Base.metadata`` rather than listed, so a fourth table adopting
    the pattern is covered without anybody widening this. The literal is taken
    from the table's own CHECK constraint, which is what the database actually
    enforces - reading the Python-side column default instead would compare the
    ORM against the ORM.

    Recognition is a *spelling*: ``data_layer = '<value>'``. That is a real
    limit and it is why :func:`test_the_pinned_data_layer_columns_were_found_at_all`
    closes the set over columns instead. A third review found the divergence
    was already live - ``data_layer_registry`` has a ``data_layer`` column and
    is silently outside this scan - and that a future table pinning its layer
    with ``data_layer IN ('terminal')`` would be invisible to the agreement
    check that exists to catch exactly that drift.

    **The match is a full match, and a fourth review is why.** The first
    version tested ``startswith("data_layer = '")`` and ``endswith("'")``, then
    took ``split("'")[1]``. ``data_layer = 'observations' OR data_layer =
    'market'`` satisfies both ends and parses to ``observations``, so the table
    would be reported as *readable and pinned to one layer* while the database
    accepted two. That is strictly worse than the ``IN ('terminal')`` case this
    scan was hardened for, because that one at least falls into ``unreadable``
    and fails loudly: a false positive means ``GRAIN_LIMIT``'s "one layer per
    table" is violated with the very check that exists to detect the drift
    reporting agreement. Anything that is not exactly one pinned literal must
    fall out of ``found`` and be caught as unreadable.
    """
    found: dict[str, str] = {}
    for table in Base.metadata.tables.values():
        if "data_layer" not in table.c:
            continue
        for constraint in table.constraints:
            if not isinstance(constraint, sa.CheckConstraint):
                continue
            match = re.fullmatch(r"data_layer = '([a-z_]+)'", str(constraint.sqltext).strip())
            if match is not None:
                found[table.name] = match.group(1)
    return found


#: The one table with a ``data_layer`` column that pins no single literal.
#:
#: ``data_layer_registry`` stores one row *per* layer, so its column is the
#: subject of the table rather than a constant pinned by a CHECK. It is named
#: here so the closed-set assertion below has to account for it explicitly
#: rather than the scan quietly not seeing it.
_DATA_LAYER_COLUMN_WITHOUT_A_PINNED_LITERAL = "data_layer_registry"


def test_the_pinned_data_layer_columns_were_found_at_all() -> None:
    """Closed over columns, so a CHECK this parser cannot read is a failure.

    The previous version hard-coded the three table names and asked the CHECK
    parser for the same three, which is a scan agreeing with a list. A third
    review showed the two had already diverged: ``data_layer_registry`` carries
    a ``data_layer`` column and the parser does not see it, so the "a fourth
    table adopting the pattern is covered without anybody widening this" claim
    in the helper's docstring was false when written.

    The membership rule is now the closed set - *every* table with a
    ``data_layer`` column - and anything the parser cannot read has to be named
    as a deliberate exclusion. A table pinning its layer as
    ``data_layer IN ('terminal')`` now fails here instead of silently sitting
    outside :func:`test_data_layer_columns_agree_with_the_registry`.
    """
    pinned = _pinned_data_layer_columns()
    have_column = _tables_with_a_data_layer_column()

    assert have_column, "no table has a data_layer column; the scan is broken, not clean"

    unreadable = sorted(have_column - set(pinned) - {_DATA_LAYER_COLUMN_WITHOUT_A_PINNED_LITERAL})
    assert set(pinned) | {_DATA_LAYER_COLUMN_WITHOUT_A_PINNED_LITERAL} == have_column, (
        f"these tables have a data_layer column that the CHECK parser could not "
        f"read: {unreadable}.\n"
        f"\n"
        f"The parser recognises only `data_layer = '<value>'`. A table pinning "
        f"its layer some other way - `IN ('terminal')`, or an enum - stores a "
        f"per-row layer that test_data_layer_columns_agree_with_the_registry "
        f"never compares against TABLE_LAYERS, so the per-row and per-table "
        f"answers can drift apart silently. Either write the CHECK in the form "
        f"the parser reads, or widen _pinned_data_layer_columns in "
        f"backend/tests/test_layer_purity.py deliberately."
    )

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

    These pin documentation rather than behaviour - widening a scan to close a
    gap would leave the assertion untouched. That is inherent to the pattern,
    and it is why each constant names what remains uncovered.

    **This test excludes deletion, not falsification, and the difference is
    worth stating because it is the sharper failure.** Name the defect the
    substring assertions exclude - "a scope limit was quietly removed" - then
    name a reading in which they pass and the defect is present: rewrite
    ``FLOW_SCAN_LIMIT`` to say that it *closes* over undeclared identifier
    columns and Python-level copying. Every required substring is still there;
    the sentence now means the reverse. So the assertion below proves the words
    are present, never that they are true. Only the count and the reader do
    that.

    The one number any of them states is checked rather than read, because a
    scope limit carrying a stale figure is worse than one carrying none: an
    earlier version of :data:`FLOW_SCAN_LIMIT` said sixteen on a heuristic
    nobody wrote down and review could not reproduce it.

    ``NAKED_IDENTIFIER_COLUMNS`` has its own falsifying reading, and it is not
    the same one. It is closed under the ``_id`` *spelling*, not under
    "undeclared reference": a column called ``seed_auction_ref`` holding
    another table's key would leave the count at ten while widening the gap the
    count describes. That is the open-set shape this repository keeps getting
    bitten by, and it is irreducible here - identifying a reference that
    declares no foreign key is exactly what the absent key denies you. It is
    why :data:`FLOW_SCAN_LIMIT` states prose *and* a number rather than
    trusting the number alone.
    """
    assert "foreign keys" in FLOW_SCAN_LIMIT
    assert "undeclared identifier column" in FLOW_SCAN_LIMIT
    assert "Python" in FLOW_SCAN_LIMIT
    assert "tripwire on arrival and not a live gap" in FLOW_SCAN_LIMIT, (
        "FLOW_SCAN_LIMIT has stopped saying that the ten columns it counts are "
        "foreign-system identifiers rather than live instances of the defect it "
        "describes. An earlier version claimed two of them were live instances; a "
        "fourth review checked all ten and none is. Do not reinstate that claim "
        "without checking the columns again - a reproducible count sitting beside "
        "an unsupported sentence is what made the sentence look checked."
    )
    assert "when db.models finishes importing" in IMPORT_TIME_LIMIT
    assert "not by reading how the imports are spelled" in IMPORT_TIME_LIMIT
    assert "DeclarativeBase" in IMPORT_TIME_LIMIT
    assert "one layer per table" in GRAIN_LIMIT

    naked = sorted(
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.name.endswith("_id") and not column.foreign_keys
    )

    assert len(naked) == NAKED_IDENTIFIER_COLUMNS, (
        f"FLOW_SCAN_LIMIT describes a gap of {NAKED_IDENTIFIER_COLUMNS} undeclared "
        f"identifier columns and the schema now has {len(naked)}:\n  "
        + "\n  ".join(naked)
        + "\n\nUpdate NAKED_IDENTIFIER_COLUMNS and the wording of FLOW_SCAN_LIMIT "
        "in backend/src/hoops_gm/db/layers.py together. If you added one, check "
        "first whether it should be a real foreign key: a column holding another "
        "table's key without declaring it is a cross-layer reference this whole "
        "unit cannot see, which is the gap the constant exists to admit to."
    )


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

    This asserts the property over every refusal path rather than spot-
    checking one, because the one that goes stale is the one nobody read - and
    the count is closed against the ``raise`` sites in ``layers.py``, so a new
    refusal cannot be added without being driven here.
    """
    unassigned = sa.MetaData()
    sa.Table("expected_games", unassigned, sa.Column("id", sa.Integer, primary_key=True))

    stale = sa.MetaData()
    for name in TABLE_LAYERS:
        sa.Table(name, stale, sa.Column("id", sa.Integer, primary_key=True))
    stale.remove(stale.tables["players"])

    stale_identity_layers = dict(TABLE_LAYERS)
    stale_identity_layers["players"] = DataLayer.VALUATION

    messages: dict[str, str] = {}
    refusals: tuple[tuple[str, Callable[[], object]], ...] = (
        ("unassigned table", lambda: validate_layer_assignment(unassigned)),
        ("stale entry", lambda: validate_layer_assignment(stale)),
        (
            "stale identity exemption",
            lambda: _with_table_layers(
                stale_identity_layers,
                lambda: validate_layer_assignment(_metadata_for(TABLE_LAYERS)),
            ),
        ),
        (
            "backwards flow",
            lambda: validate_layer_flow(
                _two_table_metadata("projections", "published_auction_values")
            ),
        ),
        ("unknown table", lambda: layer_of("expected_games")),
    )
    for label, call in refusals:
        with pytest.raises(LayerViolation) as caught:
            call()
        messages[label] = str(caught.value)

    # Closed over the raise sites, not over the ones somebody remembered.
    # Review found this test covering three of five, which is the shape where
    # a message goes stale precisely because it was the one nobody drove.
    raise_sites = sum(
        isinstance(node, ast.Raise)
        for node in ast.walk(ast.parse(Path(layers.__file__).read_text(encoding="utf-8")))
    )
    assert len(refusals) == raise_sites, (
        f"layers.py has {raise_sites} raise sites and this test drives "
        f"{len(refusals)}. Add the new refusal to `refusals` above. The point of "
        f"this test is that the message a lane actually meets has been read by "
        f"somebody, and an undriven refusal is the one that will not have been."
    )

    for label, message in messages.items():
        assert "db/layers.py" in message, f"{label} does not say which file to edit"

    for label, message in messages.items():
        if label == "unknown table":
            # layer_of is called by the flow check, so its message is a
            # diagnostic inside a larger refusal rather than an instruction of
            # its own; it names the file and stops there.
            continue
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
    # saw none of these. That gap is reported rather than widened here:
    # broadening a shared scan would fail other lanes' code mid-freeze.
    for label, message in messages.items():
        outside_ascii = sorted({character for character in message if ord(character) > 127})
        assert outside_ascii == [], (
            f"the {label} refusal contains {[hex(ord(c)) for c in outside_ascii]}, "
            f"which a cp1252 console garbles. This message is the whole interface "
            f"for a lane meeting the rule mid-rebase; use ASCII in it."
        )


def test_the_model_and_migration_agree_on_the_layer_rank_check(
    backend_dir: Path, alembic_config: Config, migration_url: str
) -> None:
    """One constraint, written twice on purpose, so it has to be compared.

    ``models/layers.py`` builds the expression from ``LAYER_RANK``; ``0019``
    carries it as a literal. That duplication is the review gate - the same
    reasoning that keeps the seed rows literal - but a gate nobody checks is
    just drift with extra steps.

    It needs its own test because neither existing test sees a divergence:
    Alembic does not compare CHECK constraints, so ``test_models_and_migrations
    _agree`` is silent, and the migrated-store tests exercise the migration's
    copy only. Review drove exactly this: weakening the model's constraint to
    ``layer_rank >= 0`` left every test green, which means a store built from
    ``Base.metadata.create_all`` would accept rows the migrated one refuses.

    Read off ``__table__`` rather than from :func:`_layer_rank_pairs`. A first
    version called the helper and compared *that* to the migration, which still
    passed when the constraint stopped using the helper - it was checking that
    two strings agreed, not that the table carried either of them.

    **And then read the migrated store, not the literal beside ``upgrade()``.**
    A fourth review caught this test committing on the migration side the exact
    error the paragraph above congratulates it for avoiding on the model side.
    Comparing against ``_load_0019(backend_dir)._LAYER_RANK_PAIRS`` proves the
    model agrees with a *string in the migration module*, never that
    ``upgrade()`` passed that string to ``CheckConstraint`` unmodified.
    Appending ``+ " OR data_layer = 'market'"`` at the call site left the
    literal untouched and the suite green, while the migrated store accepted a
    ``market`` row at any rank that the models-created store refuses - the
    precise inversion of the guarantee in the message below. Alembic does not
    compare CHECKs, and the behavioural probe uses one row that both
    expressions reject.

    So the primary comparison is against the constraint ``sa.inspect`` reads
    back from the database the migration built. The literal comparison stays as
    a secondary check: it is cheap, and it distinguishes "the call site was
    edited" from "the literal was edited", which are different repairs.
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

    command.upgrade(alembic_config, "head")
    engine = create_engine(migration_url)
    try:
        migrated = {
            constraint["name"]: str(constraint["sqltext"])
            for constraint in sa.inspect(engine).get_check_constraints("data_layer_registry")
            if constraint["name"] is not None
        }
    finally:
        engine.dispose()

    assert name in migrated, (
        f"the migrated store has no {name} constraint; found {sorted(migrated)}. "
        f"Migration 0019 declares it, so either upgrade() stopped applying it or the "
        f"constraint was renamed on one side only."
    )
    assert _normalised_check(migrated[name]) == _normalised_check(checks[name]), (
        "the layer/rank CHECK on the mapped table and in the store migration 0019 "
        "actually builds have diverged. A database created from the models would then "
        "accept rows a migrated database refuses, and the registry's whole promise is "
        "that the store answers correctly without the source tree.\n"
        f"\nmodels:  {checks[name]}\nmigrated: {migrated[name]}"
    )
    assert checks[name] == _load_0019(backend_dir)._LAYER_RANK_PAIRS, (
        "the mapped table's CHECK and migration 0019's _LAYER_RANK_PAIRS literal have "
        "diverged, even though the migrated store agrees with the model. That means "
        "upgrade() is no longer passing the literal through unmodified - repair the "
        "call site in 0019, not this test."
    )
    for layer, rank in LAYER_RANK.items():
        assert f"data_layer = '{layer.value}' AND layer_rank = {rank}" in checks[name]


def test_validate_layers_refuses_a_backwards_foreign_key() -> None:
    """A market table seeded into an availability table, refused by the function.

    Named for what it drives. An earlier name said "makes the package fail to
    import", which was the claim this repository actually cares about and not
    the claim this test establishes: the child imports the package (which
    succeeds - the shipped schema is clean), *then* maps a violating table and
    calls ``validate_layers`` explicitly. The non-zero exit comes from that
    call. Review pointed out that the name was doing the work the test was not,
    which is how a suite ends up looking like it covers something it does not.
    :func:`test_importing_the_package_is_what_refuses_a_violation` is the one
    that drives the import, on both halves.

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


@pytest.mark.parametrize(
    ("label", "injection", "needles"),
    [
        (
            "assignment",
            'del layers.TABLE_LAYERS["players"]',
            ("players",),
        ),
        (
            "assignment-only",
            'layers.TABLE_LAYERS["retired_table"] = layers.DataLayer.OBSERVATIONS',
            ("retired_table", "not mapped"),
        ),
        (
            "flow",
            'layers.TABLE_LAYERS["team_schedule"] = layers.DataLayer.TERMINAL',
            ("team_schedule", "opponent_context"),
        ),
    ],
)
def test_importing_the_package_is_what_refuses_a_violation(
    label: str, injection: str, needles: tuple[str, ...]
) -> None:
    """The headline claim, driven against the package rather than the function.

    :func:`test_validate_layers_refuses_a_backwards_foreign_key`
    imports the package and then calls ``validate_layers`` itself, so it proves
    the *function* refuses. That is not the claim. The claim is that **importing
    the package** refuses, and review showed those come apart: replacing the
    import of ``validate_layers`` in ``db/models/__init__.py`` with a local
    no-op of the same name left every gate green - 57 tests, ruff and mypy -
    while the package imported a violating schema without complaint. The AST
    test could not see it, because the call site still reads exactly right.

    So this asks the package. It injects the violation into ``TABLE_LAYERS``
    **before** ``db.models`` is imported, then imports the package and nothing
    else. Whatever the call site is spelled as, either the import raises or
    this fails.

    Parametrised over **both halves** because a third review defeated the
    single-arm version. ``validate_layers`` calls assignment then flow, and
    rebinding the name to ``validate_layer_assignment`` alone - which mypy
    accepts, the signatures being identical, and which ruff's own autofix will
    format for you - left the flow check never running at import with all 62
    tests green. An assignment-only injection cannot see that; the flow arm
    can.

    The flow arm reassigns ``team_schedule`` rather than ``players``. Sending
    ``players`` to a later layer looks like the obvious injection and is the
    wrong one: ``players`` is in :data:`MARKET_IDENTITY_SOURCES`, so the stale-
    identity branch of the *assignment* check fires first and the test would
    pass while proving the half it was written to stop proving.
    ``team_schedule`` is in no exemption set, and ``opponent_context
    .team_schedule_id`` makes it an input to a projection.

    **Three arms, not two, and the third is the mirror of the second.** A
    fourth review pointed out that the two-arm version was symmetrical only in
    appearance. Deleting ``validate_layer_assignment(metadata)`` from
    ``validate_layers`` - the exact reverse of the round-three mutation, and a
    *plausible* edit, since "the flow check already raises for an unassigned
    table" is true - left both original arms green. It is true because
    ``validate_layer_flow`` resolves every table through ``layer_of``, which
    raises ``has no layer`` for the ``del`` the first arm performs. So the
    first arm never needed the assignment half at all.

    What stops running under that edit are the two branches only
    ``validate_layer_assignment`` has: the **vanished** check and the
    **stale market-identity** check - the latter being the branch round three
    added precisely because nothing drove it. The third arm is keyed on the
    first of those: a ``TABLE_LAYERS`` entry naming a table that is not mapped
    is structurally unreachable for ``validate_layer_flow``, which iterates the
    foreign keys of *mapped* tables and so can never encounter it.
    """
    program = textwrap.dedent(
        f"""
        import hoops_gm.db.layers as layers

        {injection}

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
        f"importing db.models with a {label} violation succeeded. The package "
        f"is not enforcing ADR-008 at import, whatever its call site says - "
        f"check that db/models/__init__.py calls the real "
        f"hoops_gm.db.layers.validate_layers, has not shadowed it, and has not "
        f"rebound the name to only one of the two halves.\n"
        f"stdout={completed.stdout!r}"
    )
    assert "NO VIOLATION RAISED" not in completed.stdout
    assert "LayerViolation" in completed.stderr, (
        f"the import failed for some reason other than a layer violation, so "
        f"this test is no longer evidence of anything.\nstderr={completed.stderr!r}"
    )
    for needle in needles:
        assert needle in completed.stderr, (
            f"the {label} refusal does not name {needle!r}, so it fired for "
            f"some other reason.\nstderr={completed.stderr!r}"
        )


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
            # Skip only the package's own __init__.py - importing it is the
            # thing under test. An earlier version skipped every path whose
            # stem started with "_", and Path("valuation/__init__.py").stem is
            # "__init__", so it skipped every subpackage __init__ (making the
            # branch just below dead code) and every _-prefixed module. Both
            # are places a table can be defined, which is the same false-limit
            # shape as the non-recursive glob this scan replaced.
            if path == package_dir / "__init__.py" or path.stem == "__main__":
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
#:
#: A **digest**, not a count. A count has a single number to update, and the
#: failure message for a stale count inevitably names updating it - which
#: silences the guard while leaving the defect fully present, undetectably and
#: permanently, because no test can observe the owner's stamped store. The
#: cardinality is kept in the message for readability only; the assertion is on
#: the content. 41 rows at the time of writing.
_SEED_DIGEST_AT_0019 = "e239b1382b702fe84d276b5740a13ebcd7ad2d1aaba9c8f7d51b5141ee4bb4d7"

#: Edges migration ``0019`` seeded, pinned for the same reason as the rows.
#: 17 edges at the time of writing.
_FLOW_DIGEST_AT_0019 = "5e6c8cae24d8ea63b3538c3bd8fc8959e5b65b9f9d1ebf668837d346ca6db7e0"


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


def _normalised_check(expression: str) -> str:
    """A CHECK expression comparable across dialects.

    Postgres reads a constraint back with its own rendering: ``::text`` casts on
    every literal, its own parenthesisation, and collapsed whitespace. SQLite
    returns roughly what was written. Comparing raw text would make this a
    portability test wearing a layer-purity test's name, and it would fail on
    the Postgres CI job for a reason that has nothing to do with drift.

    So strip the parts the dialect chose and keep the parts the author chose.
    This is deliberately lossy in one direction only: it can make two different
    expressions compare equal, never two identical ones compare unequal, so a
    real divergence still fails.
    """
    stripped = re.sub(r"::\w+", "", expression)
    stripped = stripped.replace("(", " ").replace(")", " ")
    return " ".join(stripped.split())


@pytest.fixture
def migration_url(tmp_path: Path, test_database_url: str | None) -> str:
    return test_database_url or f"sqlite:///{(tmp_path / 'layers.db').as_posix()}"


@pytest.fixture
def alembic_config(backend_dir: Path, migration_url: str, _clean_database: None) -> Config:
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    # config.attributes, not set_main_option: a URL containing '%' raises on
    # read through ConfigParser's BasicInterpolation.
    config.attributes["sqlalchemy_url"] = migration_url
    return config


@pytest.fixture
def _clean_database(migration_url: str) -> Iterator[None]:
    """Start from an empty store. A Postgres test database is reused across tests.

    Drops *before* rather than after, matching ``conftest.py``'s established
    convention. The difference matters when ``TEST_DATABASE_URL`` points at a
    database another lane is also using: a teardown drop is the operation that
    reaches into somebody else's run, and it also leaves nothing to inspect when
    a test fails. Dropping on the way in gives the same isolation without
    either.

    Requested through :func:`alembic_config` rather than ``autouse``. As an
    autouse fixture it ran before all 65 tests in this module, including the
    fifty-odd that are pure set arithmetic and open no connection - sixty-five
    connect-and-drop cycles for five tests that need one, and, worse, running
    any single test from this file with ``TEST_DATABASE_URL`` set wiped that
    database even when the test never touched it. Every database test here
    takes ``alembic_config``, and
    :func:`test_no_database_test_escapes_the_clean_fixture` closes that set.
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


def test_no_database_test_escapes_the_clean_fixture() -> None:
    """``_clean_database`` is reached through ``alembic_config``, so pin that.

    The fixture stopped being ``autouse`` so it would not wipe a shared
    Postgres database on behalf of fifty tests that never connect. The cost of
    that is a way to get it wrong: a new test that talks to the store without
    the clean would pass or fail depending on what ran before it.

    **Closed over the effect, not over a parameter name.** The first version
    looked for tests taking ``migration_url`` without ``alembic_config``, which
    is a guard keyed on a spelling - this repository's named recurring defect -
    and a fourth review pointed out how short the escape route is. The
    ``migration_url`` fixture is itself two lines (``test_database_url`` or a
    tmp path), so the obvious thing a new author writes is to inline it and
    never mention the name at all. ``offenders`` would be empty and the store
    would be touched dirty.

    So this asks what the body *does*: any ``test_``-prefixed function that
    calls ``create_engine``, ``Session`` or ``command.upgrade`` anywhere inside
    it must request ``alembic_config`` or ``_clean_database``. That set is
    derived from the syntax tree rather than from a convention, and it covers
    the inlined-URL case the parameter check could not see.

    ``ast.AsyncFunctionDef`` is walked too, and keyword-only parameters are
    counted, both of which the first version missed.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    touches_the_store = {"create_engine", "Session", "upgrade", "downgrade"}
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.name.startswith("test_"):
            continue
        parameters = {
            argument.arg
            for argument in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            )
        }
        if parameters & {"alembic_config", "_clean_database"}:
            continue
        called = {
            inner.func.id if isinstance(inner.func, ast.Name) else inner.func.attr
            for inner in ast.walk(node)
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name | ast.Attribute)
        }
        if called & touches_the_store or "migration_url" in parameters:
            offenders.append(node.name)

    assert offenders == [], (
        f"these tests reach the store without alembic_config or _clean_database: "
        f"{offenders}.\n"
        f"\n"
        f"_clean_database is reached through alembic_config, so they touch a store "
        f"that was not emptied first and their result depends on what ran before - "
        f"which against a shared TEST_DATABASE_URL means they depend on another "
        f"lane. Add alembic_config to the signature, or request _clean_database "
        f"explicitly.\n"
        f"\n"
        f"This is keyed on what the body calls ({sorted(touches_the_store)}), not on "
        f"whether it takes migration_url, because inlining that fixture's two lines "
        f"is the obvious way to end up here by accident."
    )


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

    **Pinned by digest, not by cardinality, and a fourth review is why.** The
    first version asserted ``len(seed) == 41``, and its own failure message
    named the remedy and the escape hatch in the same breath. Appending a row
    and changing ``41`` to ``42`` is two keystroke-level edits, satisfies every
    assertion here, and the migrated-store tests cannot see it because they
    upgrade from an **empty** database where both routes are indistinguishable.

    That failure is **silent, not safe**, which is what makes it worse than the
    other counted pins in this unit. ``FLOW_MATRIX_SIZE`` lands safe because
    ``flow_permitted`` is an allowlist and an enum member cannot add a
    permission. The seed is not an allowlist; it is data. No test in this
    repository can observe the owner's stamped store, so after that edit no
    gate - now or ever - distinguishes a store that received the row from one
    that did not, and the registry's stated purpose of answering from a store
    alone is defeated permanently and invisibly for the one store it exists to
    serve.

    A digest has no single number to update. Replacing it means replacing a
    hash wholesale, which nobody does by accident and which reads in a diff as
    exactly what it is: a claim that recorded history was wrong.
    """
    seed = _load_0019(backend_dir)._SEED

    digest = hashlib.sha256(repr(seed).encode()).hexdigest()
    assert digest == _SEED_DIGEST_AT_0019, (
        f"migration 0019's seed is not the snapshot it was; sha256 is {digest}, "
        f"not {_SEED_DIGEST_AT_0019} ({len(seed)} rows). 0019 is already applied on "
        f"the owner's store and will not run again, so a row added, removed or "
        f"reordered here never reaches it - the store keeps the old set forever "
        f"and nothing else in this suite can see the difference, because every "
        f"migrated-store test upgrades from an empty database where the two routes "
        f"look identical.\n"
        f"\n"
        f"What to do: add a new migration that inserts the row. Only replace this "
        f"digest if you are deliberately correcting the historical record, and say "
        f"so in the commit message."
    )
    assert len({name for name, _, _ in seed}) == len(seed), "0019 seeds a table twice"
    for name, layer, rank in seed:
        assert layer in set(DataLayer), f"0019 seeds {name} at unknown layer {layer!r}"
        assert LAYER_RANK[DataLayer(layer)] == rank, (
            f"0019 seeds {name} at {layer!r} with rank {rank}, which is not that "
            f"layer's rank. The CHECK added in 0019 would reject this row."
        )

    flows = _load_0019(backend_dir)._FLOW_SEED

    flow_digest = hashlib.sha256(repr(flows).encode()).hexdigest()
    assert flow_digest == _FLOW_DIGEST_AT_0019, (
        f"migration 0019's flow seed is not the snapshot it was; sha256 is "
        f"{flow_digest}, not {_FLOW_DIGEST_AT_0019} ({len(flows)} edges). The same "
        f"reasoning as the rows above: 0019 will not run again on the owner's "
        f"store, so an edge added here never reaches it, and no test can see the "
        f"difference. Add a new migration.\n"
        f"\n"
        f"If you are changing the *rule* rather than correcting history, note that "
        f"test_a_migrated_store_records_the_permitted_edges compares PERMITTED_FLOWS "
        f"against the migrated store rather than against this literal, precisely so "
        f"a later migration may legitimately change it."
    )
    assert len(set(flows)) == len(flows), "0019 seeds an edge twice"
    for source, target in flows:
        assert source != target, (
            f"0019 seeds the self-edge {source!r}, which the CHECK rejects. "
            f"Same-layer flow is always permitted and needs no row."
        )


def test_a_migrated_store_records_the_permitted_edges(
    alembic_config: Config, migration_url: str
) -> None:
    """The store's answer and the code's answer to "was this allowed?", compared.

    The registry alone leaves only a rank comparison expressible in SQL, and
    this unit rejected the rank comparison precisely because it permits
    ``valuation -> market``, ``availability -> market`` and
    ``projections -> market`` - each of them R38. A third review pointed out
    that the caveat lived in a Python docstring, which is exactly what somebody
    querying the store at 11:59pm does not have; ``market`` and ``terminal``
    also share rank 4, so even ordering by rank is ambiguous. So the edges are
    stored, and this is what holds them to the rule.

    **Read against the migrated store, not against 0019's literal.** An earlier
    draft of this compared ``_FLOW_SEED`` to :data:`PERMITTED_FLOWS` directly,
    and I caught it before it landed: that version forbids a future ``0020``
    from ever adding or retiring an edge, because 0019's literal is frozen
    history and would then disagree with the code forever. It would have fired
    with a message instructing the reader to add the migration they had just
    added. Reading the store is both the correct check under drift and the
    stricter one - dropping the bulk insert while keeping the literal is
    invisible to a test that reads the literal.

    :func:`test_the_0019_seed_is_a_frozen_snapshot` pins 0019's shape as
    history; agreement with the rule lives here.
    """
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        with Session(engine) as session:
            stored = {
                (row.source_layer, row.target_layer) for row in session.query(DataLayerFlow).all()
            }

        stored_only = sorted((s.value, t.value) for s, t in stored - set(PERMITTED_FLOWS))
        permitted_only = sorted((s.value, t.value) for s, t in set(PERMITTED_FLOWS) - stored)
        assert stored == set(PERMITTED_FLOWS), (
            f"the migrated store's edge set and PERMITTED_FLOWS disagree.\n"
            f"  stored but not permitted: {stored_only}\n"
            f"  permitted but not stored: {permitted_only}\n"
            f"\n"
            f"A store whose edge set disagrees with the code answers 'was this "
            f"number allowed to depend on that one?' differently depending on "
            f"where you ask, which is worse than not storing it at all. If you "
            f"changed PERMITTED_FLOWS in backend/src/hoops_gm/db/layers.py, add "
            f"a migration inserting or deleting the row - do not edit 0019, "
            f"which is already stamped on the owner's store and will not run "
            f"again. See ADR-008."
        )

        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO data_layer_flows (source_layer, target_layer) "
                    "VALUES ('projections', 'projections')"
                )
            )
            connection.commit()
    finally:
        engine.dispose()


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
    path and nothing else - not ``text()``, not a data migration, not a bulk
    load - so the constraint is exercised the way a bad write would actually
    arrive.

    Two assertions, because the behavioural one alone was not evidence for the
    claim in this test's name. A third review pointed out that
    ``('expected_games', 'vibes', 2)`` is *also* rejected by
    ``ck_data_layer_registry_layer_rank_matches_layer`` - no disjunct matches
    ``'vibes'`` - and ``pytest.raises(IntegrityError)`` cannot say which CHECK
    fired, so dropping ``create_constraint=True`` from the enum left this
    green. No row can separate them either: every unknown layer value fails
    the rank CHECK by construction. So the existence of the enum CHECK is
    asserted structurally, against the store the migration actually built,
    which is the thing that disappears when the flag is dropped.

    A fourth review extended it to ``data_layer_flows``. The reasoning that
    made the registry's structural assertion necessary applies identically
    there and was nowhere written down, so replacing ``_layer_enum`` with a
    plain ``String`` on ``source_layer`` and ``target_layer`` left the suite
    green while the store's flow table accepted layers that do not exist -
    and unlike the registry, that table has **no rank CHECK to fall back on**,
    so nothing at all would reject them. ``models/layers.py`` argues the flow
    table is what someone actually queries at 11:59pm; a table answering that
    question must not hold a value the vocabulary has no name for.
    """
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        names = {
            constraint["name"]
            for constraint in sa.inspect(engine).get_check_constraints("data_layer_registry")
            if constraint["name"] is not None
        }
        assert "ck_data_layer_registry_data_layer" in names, (
            f"the migrated store has no enum CHECK on data_layer; found {sorted(names)}. "
            f"Without it any string is a layer, and the only thing rejecting 'vibes' "
            f"is the rank CHECK, which is a different guarantee."
        )

        flow_names = {
            constraint["name"]
            for constraint in sa.inspect(engine).get_check_constraints("data_layer_flows")
            if constraint["name"] is not None
        }
        for column in ("source_layer", "target_layer"):
            assert f"ck_data_layer_flows_{column}" in flow_names, (
                f"the migrated store has no enum CHECK on data_layer_flows.{column}; "
                f"found {sorted(flow_names)}. Without it any string is a layer, and "
                f"data_layer_flows has no rank CHECK to reject it by accident the way "
                f"data_layer_registry does - so nothing would."
            )

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
