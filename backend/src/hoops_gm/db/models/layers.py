"""The layer registry, stored so a wrong number can be interrogated in SQL.

ADR-008 requires that every stored quantity records which layer it belongs to.
:data:`hoops_gm.db.layers.TABLE_LAYERS` is where that decision lives and where
it is enforced; this table is the same fact **in the database**, so the
question "what layer is this number?" is answerable from a store alone, without
the source tree that produced it. :class:`DataLayerFlow` stores the companion
fact - which flows are permitted - because the registry alone leaves only a
rank comparison expressible in SQL, and this unit found a rank comparison to be
wrong.

That is not a redundancy for its own sake. The first move when a figure looks
wrong at 11:59pm is to open the store, and a fact that only exists in Python is
not available at that moment. Three tables already record their layer per row
by CHECK-pinned column (``absence_splits``, ``auction_value_sources``,
``published_auction_values``); this extends the same answer to the rest without
adding a constant-valued column to thirty-odd tables.

**Seeded by migration, not at runtime.** ``layer-purity``'s whole point is that
a layer assignment is a decision somebody makes, so a new table's row arrives
through a reviewed data migration. ``test_layer_purity.py`` compares a migrated
store against ``TABLE_LAYERS`` and fails when the two disagree.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from hoops_gm.db.base import Base, TimestampMixin, portable_enum
from hoops_gm.db.layers import LAYER_RANK, DataLayer


def _layer_rank_pairs() -> str:
    """The seven ``(layer, rank)`` pairs, as a CHECK expression.

    Built from :data:`LAYER_RANK` rather than typed out, so the constraint
    cannot fall behind the vocabulary it constrains. Migration ``0019`` carries
    the same expression as a literal — that duplication is the review gate, and
    it is the same reasoning that keeps the seed rows literal.
    """
    return " OR ".join(
        f"(data_layer = '{layer.value}' AND layer_rank = {rank})"
        for layer, rank in sorted(LAYER_RANK.items(), key=lambda item: (item[1], item[0].value))
    )


class DataLayerRegistry(TimestampMixin, Base):
    """One row per mapped table: which ADR-008 layer its rows belong to.

    The primary key is the table name rather than a surrogate integer. Unlike
    every other table here there is no upstream identifier to disagree with -
    the table name *is* the identity, and a surrogate key would permit two rows
    claiming different layers for one table.
    """

    __tablename__ = "data_layer_registry"
    __table_args__ = (
        CheckConstraint("layer_rank >= 0", name="layer_rank_non_negative"),
        CheckConstraint("length(table_name) > 0", name="table_name_not_empty"),
        CheckConstraint(_layer_rank_pairs(), name="layer_rank_matches_layer"),
    )

    table_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    data_layer: Mapped[DataLayer] = mapped_column(portable_enum(DataLayer, "data_layer"))
    #: How far down the pipeline the layer sits, denormalised from
    #: ``LAYER_RANK`` so a raw query can order layers without importing Python.
    #:
    #: Descriptive only. The flow rule is ``PERMITTED_FLOWS``, an explicit edge
    #: set, because the market layer consumes nothing we derived and no single
    #: integer can say that. Read this column as a label, not as the rule.
    #:
    #: ``ck_..._layer_rank_matches_layer`` pins the pairing, so a row cannot
    #: store a layer and a rank that disagree — previously the only constraint
    #: was ``>= 0``, and ``('expected_games', 'terminal', 0)`` was accepted by
    #: the database, which undermines the one guarantee this table exists for.
    layer_rank: Mapped[int] = mapped_column()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DataLayerRegistry {self.table_name}={self.data_layer}>"


class DataLayerFlow(TimestampMixin, Base):
    """One row per permitted ``(source, target)`` edge: the flow rule, stored.

    :class:`DataLayerRegistry` answers "what layer is this number?". Without
    this table the store cannot answer the question that actually matters -
    "was this number allowed to depend on that one?" - and a third review
    showed the consequence is worse than a gap. The only rule expressible in
    SQL from the registry alone is a rank comparison, and a rank comparison is
    exactly what this unit rejected: it permits ``valuation -> market``,
    ``availability -> market`` and ``projections -> market``, each of them R38.
    Somebody at 11:59pm with the store and no source tree, writing
    ``WHERE src.layer_rank < tgt.layer_rank``, got the discredited answer, and
    the warning against doing so lived in a Python docstring - which is
    precisely what that person does not have. ``market`` and ``terminal`` also
    share rank 4, so even ``ORDER BY layer_rank`` is ambiguous.

    So the edges are stored. A same-layer flow is always permitted and has no
    row; the CHECK forbids one, so the table cannot be read as though a missing
    self-edge meant a refusal.

    Seeded by migration as a literal snapshot, for the same reason the registry
    is: importing :data:`PERMITTED_FLOWS` would make two representations into
    one wearing two hats, and remove the only thing that forces a new edge
    through review.
    """

    __tablename__ = "data_layer_flows"
    __table_args__ = (
        CheckConstraint("source_layer <> target_layer", name="flow_is_between_two_layers"),
    )

    source_layer: Mapped[DataLayer] = mapped_column(
        portable_enum(DataLayer, "source_layer"), primary_key=True
    )
    target_layer: Mapped[DataLayer] = mapped_column(
        portable_enum(DataLayer, "target_layer"), primary_key=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DataLayerFlow {self.source_layer}->{self.target_layer}>"
