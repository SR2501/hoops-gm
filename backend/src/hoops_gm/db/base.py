"""Declarative base, naming conventions and shared column mixins.

Two things here are load-bearing:

**Naming convention.** Every constraint and index gets a deterministic name.
Without this, Alembic autogenerate produces unnamed constraints that SQLite
cannot drop and Postgres names differently — the exact class of divergence
ADR-001 exists to prevent.

**Portable enums.** ``portable_enum`` never emits a native database enum type.
Postgres native enums require a migration to add a value; a VARCHAR with a
CHECK constraint behaves the same on both dialects and stays readable in a
raw query.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata_obj = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Declarative base for every hoops-gm table."""

    metadata = metadata_obj


_E = TypeVar("_E", bound=enum.Enum)


def portable_enum(enum_cls: type[_E], name: str, **kwargs: Any) -> SAEnum:
    """A string-backed enum column that behaves identically on SQLite and Postgres."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=48,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
        **kwargs,
    )


class TimestampMixin:
    """``created_at`` / ``updated_at`` on every row.

    Cheap, and the first question asked of a wrong number is always "when did
    this row appear".
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class IntPk:
    """Surrogate integer primary key.

    Deliberately *not* the upstream identifier. Fantrax ids, NBA ids and
    projection-CSV name strings disagree with each other (risk R7); a source
    identifier used as a primary key makes that disagreement structural.
    External identifiers live in ``player_external_ids``.
    """

    id: Mapped[int] = mapped_column(primary_key=True)
