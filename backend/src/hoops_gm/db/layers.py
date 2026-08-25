"""ADR-008 layer purity, made structural rather than documented.

ADR-008 orders the layers and says information flows one way only::

    observations -> projections -> availability -> valuation -> rankings/values
       (facts)      (production)    (p(play))      (fused)        (TERMINAL)

The defect this prevents is **circularity**, and circularity does not crash.
If a composite value or a published ranking feeds back into an availability or
projection input, the model starts agreeing with itself and every downstream
figure gets more confident and less true. There is no green-test signal for
that, which is why the constraint has to be a mechanism rather than a rule
somebody remembers.

## Why this is a registry rather than a convention

The instruction in the backlog is "make it inexpressible rather than merely
documented", and this repository has been bitten three times by rules that were
correct when written and decayed silently afterwards: a census that was exactly
complete until an unrelated merge, a guard keyed on a proxy question, and five
tests deleted by a refactor with the suite still green.

So the membership rule here is a **closed set** rather than a pattern over
spellings. Two closed sets, in fact, both taken from ``Base.metadata``:

* every mapped table must appear in :data:`TABLE_LAYERS`, and
* every declared foreign key is a flow, checked against :func:`flow_permitted`.

Neither is a list of doors somebody enumerated. A table that arrives without a
layer, or a foreign key that points the wrong way, fails on **arrival** — at
import of :mod:`hoops_gm.db.models`, not merely in a test somebody might not
run. That is the same shape as ``test_portability.py``'s
``_DIALECT_AWARE_MODULES`` and ``test_store_creating_readers.py``'s
``SANCTIONED_STORE_OPENERS``.

## Read the scope limits before treating this as coverage

:data:`FLOW_SCAN_LIMIT` and :data:`GRAIN_LIMIT` are asserted constants, not
comments, for the reason ``test_store_creating_readers.SCAN_LIMIT`` is: a
limitation in a docstring gets summarised away, and a limitation pinned by an
assertion breaks a test when someone deletes it.
"""

from __future__ import annotations

import enum
from typing import Final

from sqlalchemy import MetaData


class DataLayer(enum.StrEnum):
    """Which layer of ADR-008 a stored quantity belongs to.

    The five names come from ADR-008's decision block verbatim.
    :attr:`MARKET` and :attr:`COMPARISON` are the two the ADR's prose requires
    but its arrow diagram does not name; see :data:`LAYER_RANK` for why each is
    ranked where it is rather than folded into a neighbour.
    """

    #: Facts, and aggregates of facts computed only from other facts.
    OBSERVATIONS = "observations"
    #: Per-game production rates, with any games-played assumption stripped.
    PROJECTIONS = "projections"
    #: ``p(play)`` and everything derived to predict it.
    AVAILABILITY = "availability"
    #: Production and availability fused. ADR-002's separation, resolved.
    VALUATION = "valuation"
    #: Our own rankings and dollar values. Outputs, never inputs.
    TERMINAL = "terminal"
    #: Somebody *else's* published aggregate — AAV, consensus rank, tiers.
    #: Already terminal-grade when it arrives: it contains production, an
    #: availability assumption and a scoring-format assumption fused together,
    #: which is precisely what ADR-008 forbids blending in.
    MARKET = "market"
    #: Model-versus-market: the one place ADR-008 clause 3 permits our terminal
    #: outputs and an external aggregate to meet. Consumes both, feeds nothing.
    COMPARISON = "comparison"


#: How far down the pipeline each layer sits. Lower may flow into higher.
#:
#: :attr:`DataLayer.MARKET` shares rank 4 with :attr:`DataLayer.TERMINAL`
#: rather than sitting above or below it, and the equal rank is load-bearing
#: because :func:`flow_permitted` rejects *cross-layer* flow at equal rank.
#: Both directions have to be impossible and they are impossible for different
#: reasons:
#:
#: * ``market -> terminal`` is ADR-008 clause 5 — "the draft-day rankings are
#:   ours alone", computed end-to-end with no external ranking in the lineage.
#: * ``terminal -> market`` is R38 — writing our own values into the market
#:   tables launders our output back in as somebody else's evidence, which is
#:   the failure ``DraftToolUsage`` exists to record and ``market.independence``
#:   exists to detect.
#:
#: A single total order cannot express "mutually unreachable"; a rank plus the
#: same-layer exception can, without inventing a partial-order framework.
LAYER_RANK: Final[dict[DataLayer, int]] = {
    DataLayer.OBSERVATIONS: 0,
    DataLayer.PROJECTIONS: 1,
    DataLayer.AVAILABILITY: 2,
    DataLayer.VALUATION: 3,
    DataLayer.TERMINAL: 4,
    DataLayer.MARKET: 4,
    DataLayer.COMPARISON: 5,
}


#: Layers with no table yet, pinned so the first one to arrive is reviewed.
#:
#: An empty layer is not dead vocabulary — it is the half of ADR-008 this
#: schema has not reached. Recording *which* halves are empty means the day a
#: valuation table lands, ``test_empty_layers_are_still_empty`` goes red and
#: somebody looks at the flow rule with a real table in front of them, instead
#: of the layer quietly acquiring members nobody classified against the ADR.
LAYERS_WITHOUT_TABLES: Final[frozenset[DataLayer]] = frozenset(
    {
        DataLayer.AVAILABILITY,
        DataLayer.VALUATION,
        DataLayer.TERMINAL,
        DataLayer.COMPARISON,
    }
)


#: Every mapped table, and the layer its rows belong to.
#:
#: Completeness is not asserted here, it is checked: :func:`validate_layers`
#: compares this against ``Base.metadata.tables`` in both directions and
#: :mod:`hoops_gm.db.models` calls it at import. A table added without an entry
#: raises :class:`LayerViolation` before anything can query it.
#:
#: Assignment is per table because that is the grain the schema already uses —
#: the three existing ``data_layer`` columns are each pinned to one literal by
#: a CHECK, so no table today holds rows at two layers. See :data:`GRAIN_LIMIT`.
TABLE_LAYERS: Final[dict[str, DataLayer]] = {
    # --- observations: facts, and aggregates computed only from facts --------
    # Identity and reference. Not modelled quantities, and everything is
    # entitled to consume them, which is what rank 0 means.
    "nba_teams": DataLayer.OBSERVATIONS,
    "players": DataLayer.OBSERVATIONS,
    "player_external_ids": DataLayer.OBSERVATIONS,
    # Observed NBA facts.
    "nba_games": DataLayer.OBSERVATIONS,
    "team_schedule": DataLayer.OBSERVATIONS,
    "player_game_logs": DataLayer.OBSERVATIONS,
    "player_season_stats": DataLayer.OBSERVATIONS,
    "player_participation": DataLayer.OBSERVATIONS,
    "injury_report_entries": DataLayer.OBSERVATIONS,
    # Observation-layer aggregates. `absence_splits` already carries a
    # `data_layer = 'observations'` CHECK, so this entry restates a fact the
    # database is enforcing rather than adding a new claim.
    "absence_split_runs": DataLayer.OBSERVATIONS,
    "absence_splits": DataLayer.OBSERVATIONS,
    # Schedule context. Derived, but derived from the schedule and from
    # completed games only — no projection, no p(play). ADR-008 clause 1
    # permits aggregating within a layer, and that is what these are.
    "opponent_context": DataLayer.OBSERVATIONS,
    "off_night_slates": DataLayer.OBSERVATIONS,
    # Observed league state and configuration.
    "leagues": DataLayer.OBSERVATIONS,
    "fantasy_teams": DataLayer.OBSERVATIONS,
    "rosters": DataLayer.OBSERVATIONS,
    "roster_slots": DataLayer.OBSERVATIONS,
    "scoring_periods": DataLayer.OBSERVATIONS,
    "matchups": DataLayer.OBSERVATIONS,
    "matchup_category_results": DataLayer.OBSERVATIONS,
    "transactions": DataLayer.OBSERVATIONS,
    "league_settings_snapshots": DataLayer.OBSERVATIONS,
    "league_scoring_profiles": DataLayer.OBSERVATIONS,
    "league_scoring_categories": DataLayer.OBSERVATIONS,
    "league_deadline_calendars": DataLayer.OBSERVATIONS,
    # What a person watched happen in a draft. `draft_events.amount` is a price
    # a human saw clear, not a price anything computed — see DraftEventType.
    "drafts": DataLayer.OBSERVATIONS,
    "draft_participants": DataLayer.OBSERVATIONS,
    "draft_events": DataLayer.OBSERVATIONS,
    # Raw transport and provenance.
    "bridge_payloads": DataLayer.OBSERVATIONS,
    "refresh_runs": DataLayer.OBSERVATIONS,
    # Facts about the schema itself. Rank 0 is the honest answer twice over:
    # any layer may read it, and nothing higher may write into it.
    "data_layer_registry": DataLayer.OBSERVATIONS,
    # --- projections: per-game rates, games-played assumption stripped -------
    "projection_sources": DataLayer.PROJECTIONS,
    "projection_profile_versions": DataLayer.PROJECTIONS,
    "projection_imports": DataLayer.PROJECTIONS,
    "projections": DataLayer.PROJECTIONS,
    # The source's own durability guess, kept one-to-one with the projection it
    # was stripped from. Projection-layer provenance, deliberately *not*
    # availability: the availability model overrides it and never blends it.
    "source_games_played_assumptions": DataLayer.PROJECTIONS,
    # --- market: what somebody else published -------------------------------
    "auction_value_sources": DataLayer.MARKET,
    "auction_value_source_inputs": DataLayer.MARKET,
    "auction_value_imports": DataLayer.MARKET,
    "published_auction_values": DataLayer.MARKET,
}


#: What the flow check does **not** see, stated because the gap is easy to
#: mistake for coverage.
#:
#: It reads declared foreign keys. A value read out of a market row in Python
#: and written into a projection row leaves no foreign key behind and is
#: invisible here. That is a real exposure and naming it is the point: this
#: closes the *structural* door, where a table's shape says it consumes another
#: table, and it is silent about arithmetic.
#:
#: The reason to close the structural door anyway is that it fails on arrival.
#: A new table declares its foreign keys at definition time, so the wrong
#: lineage is rejected before a single row exists — which is the only moment
#: fixing it is cheap.
FLOW_SCAN_LIMIT: Final = (
    "checks declared foreign keys; a value copied between layers in Python leaves no key"
)

#: The grain of an assignment: one layer per table, not per column.
#:
#: True of every table today and enforced by
#: ``test_data_layer_columns_agree_with_the_registry`` for the three tables
#: that also store the layer per row. A table that genuinely needed two layers
#: would be two tables — which is exactly the ruling that produced the market
#: tables instead of widening ``projection_sources``.
GRAIN_LIMIT: Final = "one layer per table; a table needing two layers is two tables"


class LayerViolation(RuntimeError):
    """A stored quantity's layer is unassigned, unknown, or flows backwards."""


def flow_permitted(source: DataLayer, target: DataLayer) -> bool:
    """May a quantity at ``source`` be an input to one at ``target``?

    Permitted when the two are the same layer — ADR-008 clause 1, "aggregate
    only within a layer" — or when ``source`` is strictly earlier in the
    pipeline. Cross-layer flow at equal rank is refused, which is what keeps
    :attr:`DataLayer.MARKET` and :attr:`DataLayer.TERMINAL` mutually
    unreachable in both directions.
    """
    return source is target or LAYER_RANK[source] < LAYER_RANK[target]


def layer_of(table_name: str) -> DataLayer:
    """The layer assigned to ``table_name``, or raise."""
    try:
        return TABLE_LAYERS[table_name]
    except KeyError:
        raise LayerViolation(
            f"table {table_name!r} has no layer. Every stored quantity records which "
            f"layer it belongs to (ADR-008); add it to TABLE_LAYERS in db/layers.py "
            f"with the reason it sits where it does, and seed its row in "
            f"data_layer_registry with a migration."
        ) from None


def validate_layer_assignment(metadata: MetaData) -> None:
    """Every mapped table has a layer, and every assignment names a real table.

    Both directions, because they fail differently. An unassigned table is a
    quantity nobody classified; an assignment for a table that no longer exists
    is a registry rotting into fiction, which is how the store-opening census
    went from exactly complete to quietly wrong.
    """
    mapped = set(metadata.tables)
    assigned = set(TABLE_LAYERS)

    unassigned = sorted(mapped - assigned)
    if unassigned:
        raise LayerViolation(
            f"tables with no ADR-008 layer: {unassigned}. Add each to TABLE_LAYERS "
            f"in db/layers.py, then seed its row in data_layer_registry."
        )

    vanished = sorted(assigned - mapped)
    if vanished:
        raise LayerViolation(
            f"TABLE_LAYERS names tables that are not mapped: {vanished}. "
            f"Remove them, and drop their data_layer_registry rows in a migration."
        )


def validate_layer_flow(metadata: MetaData) -> None:
    """No declared foreign key points from a later layer into an earlier one.

    A foreign key from ``T`` to ``S`` means a row of ``T`` is defined partly by
    a row of ``S`` — ``S`` is an input to ``T``. So the check is on the layer
    of the *referenced* table against the layer of the referencing one.
    """
    violations: list[str] = []
    for table in metadata.tables.values():
        target_layer = layer_of(table.name)
        for key in table.foreign_keys:
            referenced = key.column.table.name
            source_layer = layer_of(referenced)
            if not flow_permitted(source_layer, target_layer):
                violations.append(
                    f"{table.name}.{key.parent.name} -> {referenced} "
                    f"({source_layer} into {target_layer})"
                )

    if violations:
        raise LayerViolation(
            "ADR-008 forbids these flows: "
            + "; ".join(sorted(violations))
            + ". A later layer may not be an input to an earlier one at any weight. "
            "If the intent is to compare rather than to blend, the comparison belongs "
            "at DataLayer.COMPARISON, which consumes both sides and feeds nothing."
        )


def validate_layers(metadata: MetaData) -> None:
    """Assignment then flow. Called at import of :mod:`hoops_gm.db.models`."""
    validate_layer_assignment(metadata)
    validate_layer_flow(metadata)
