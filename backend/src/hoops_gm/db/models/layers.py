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
from hoops_gm.db.layers import DataLayer


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
    )

    table_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    data_layer: Mapped[DataLayer] = mapped_column(portable_enum(DataLayer, "data_layer"))
    #: How far down the pipeline the layer sits, denormalised from
    #: ``LAYER_RANK`` so that ordering — the thing the rule is actually about —
    #: is expressible in a raw query rather than only in Python. Pinned against
    #: ``LAYER_RANK`` by ``test_layer_purity.py``; equal ranks are meaningful,
    #: see the note on ``LAYER_RANK`` for why ``market`` shares one.
    layer_rank: Mapped[int] = mapped_column()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DataLayerRegistry {self.table_name}={self.data_layer}>"
