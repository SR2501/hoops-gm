"""Declarative base, naming conventions and shared column types.

Three things here are load-bearing.

**Naming convention.** Every constraint and index gets a deterministic name.
Without this, Alembic autogenerate produces unnamed constraints that SQLite
cannot drop and Postgres names differently — the exact class of divergence
ADR-001 exists to prevent.

**Portable enums.** ``portable_enum`` never emits a native database enum type.
Postgres native enums require a migration to add a value; a VARCHAR plus a
CHECK constraint behaves the same on both dialects and stays readable in a raw
query.

``create_constraint=True`` is the whole point of that sentence, and it
defaults to **False** in SQLAlchemy 1.4 and later. The first version of this
module omitted it, so the schema carried 17 enum columns and zero enum CHECK
constraints while three separate docstrings claimed otherwise. A raw ``text()``
insert of an unknown value was accepted, and reading that row back through the
ORM then raised ``LookupError`` on every query touching the table — a bad
write became an unreadable table much later. Python-side ``validate_strings``
covers the ORM path and nothing else: not ``text()``, not a data migration,
not a bulk load, not anything opening the database file directly.

**UTC datetimes.** See :class:`UTCDateTime`.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import DateTime as SADateTime
from sqlalchemy import Dialect, MetaData, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

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
    """A string-backed enum column that behaves identically on SQLite and Postgres.

    ``create_constraint=True`` is mandatory and must not be removed: without it
    the "unrecognised values fail loudly" guarantee is a comment rather than a
    constraint. ``test_portability.py`` asserts every enum column has a CHECK.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=48,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
        **kwargs,
    )


class UTCDateTime(TypeDecorator[datetime]):
    """A timezone-aware datetime that is actually timezone-aware on SQLite.

    ``DateTime(timezone=True)`` is a Postgres-only guarantee. SQLite has no
    native datetime type, so the driver stores an ISO string and **silently
    discards the offset**: a 7:30pm Eastern tip-off written as ``23:30+00:00``
    read back as a naive ``19:30``. Four hours wrong, from the identical write
    that is correct on Postgres.

    That is not a cosmetic difference here. Rest days and back-to-back
    detection are computed from ``nba_games.tipoff_utc``, and both are named
    inputs to the availability model — the thing this whole project is for.
    The same divergence hits ``created_at``/``updated_at`` on every table, so
    comparing a row's timestamp against an aware ``datetime.now(UTC)`` raises
    ``TypeError`` on one dialect and works on the other.

    So: converted to UTC on the way in, re-attached as UTC on the way out.
    Naive input is rejected rather than assumed to be UTC, because assuming is
    how the four-hour error happens in the first place.
    """

    impl = SADateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        return dialect.type_descriptor(SADateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "naive datetime rejected: attach a timezone before storing. "
                "Assuming UTC is how a local wall-clock time silently becomes "
                "a UTC instant several hours away."
            )
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            # SQLite dropped the offset. Everything stored is UTC by construction.
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class TimestampMixin:
    """``created_at`` / ``updated_at`` on every row.

    Cheap, and the first question asked of a wrong number is always "when did
    this row appear".

    ``func.now()`` is UTC on both dialects — SQLite's ``CURRENT_TIMESTAMP`` is
    UTC, and Postgres stores an instant — so :class:`UTCDateTime` re-attaching
    UTC on read is correct for server-generated values too.
    """

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
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


def enum_check_constraint_names(metadata: MetaData) -> set[str]:
    """Names of the CHECK constraints SQLAlchemy generates for enum columns.

    Autogenerate treats these asymmetrically: it reflects them from the
    database but skips them on the metadata side, because they carry an
    internal ``_create_rule``. Left alone, every comparison reports one
    spurious "removed check constraint" per enum column, ``alembic check``
    can never be green again, and the drift detection that actually matters —
    a model changed without a migration — drowns in noise.

    So they are excluded from comparison by name. What proves they exist is
    ``test_database_guarantees.py``, which inserts an unknown value through raw
    SQL and requires the database to refuse it. That is the right place for the
    check: it tests the constraint's effect rather than its presence in a diff.
    """
    return {
        f"ck_{table.name}_{column.type.name}"
        for table in metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, SAEnum) and column.type.create_constraint and column.type.name
    }
