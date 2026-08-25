"""The layer registry, stored so a wrong number can be interrogated in SQL.

ADR-008 requires that every stored quantity records which layer it belongs to.
:data:`hoops_gm.db.layers.TABLE_LAYERS` is where that decision lives and where
it is enforced; this table is the same fact **in the database**, so the
question "what layer is this number?" is answerable from a store alone, without
the source tree that produced it.

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
    every other table here there is no upstream identifier to disagree with —
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
