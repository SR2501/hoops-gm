"""Explicit forecast series, preserving the complete populated import subtree.

SQLite's parent-table rebuild cascades into both descendant cohorts. Stage and
restore their complete rows inside a physical transaction, with FKs always on.
The revision-local import definition preserves the 0023 constraints, not a
reflection-dependent subset or a later application's ORM definition.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHILDREN = ("projections", "source_games_played_assumptions")
_KEY_CHECK = "length(series_key) BETWEEN 1 AND 64"
_LABEL_CHECK = (
    "(series_key = 'legacy' AND series_display_name IS NULL) OR "
    "(series_key <> 'legacy' AND series_display_name IS NOT NULL "
    "AND length(trim(series_display_name)) > 0 "
    "AND length(series_display_name) <= 128)"
)
_SCORING_CHECK = (
    "assumed_scoring_type IN "
    "('h2h_categories', 'h2h_points', 'h2h_each_category', 'roto', 'points')"
)
_KEY_NAME = "ck_projection_imports_series_key_length"
_LABEL_NAME = "ck_projection_imports_series_declaration"
_INDEX_NAME = "ix_projection_imports_source_series_season"


def _imports(*, has_series: bool) -> sa.Table:
    metadata = sa.MetaData()
    sa.Table("projection_sources", metadata, sa.Column("id", sa.Integer()))
    sa.Table("projection_profile_versions", metadata, sa.Column("id", sa.Integer()))
    table = sa.Table(
        "projection_imports",
        metadata,
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("profile_version_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.String(9), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("profile_id", sa.String(128), nullable=False),
        sa.Column("profile_version", sa.String(64), nullable=False),
        sa.Column("profile_verified", sa.Boolean(), nullable=False),
        sa.Column("profile_definition_sha256", sa.String(64), nullable=False),
        sa.Column("profile_lineage", sa.JSON(), nullable=False),
        sa.Column("original_filename", sa.String(255)),
        *(
            sa.Column(name, sa.Integer(), nullable=False)
            for name in (
                "row_count",
                "matched_count",
                "needs_review_count",
                "unmatched_count",
                "rejected_count",
            )
        ),
        sa.Column("assumed_scoring_type", sa.String(48)),
        sa.Column("raw_payload_ref", sa.String(255)),
        sa.Column("notes", sa.Text()),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_projection_imports"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["projection_sources.id"],
            name="fk_projection_imports_source_id_projection_sources",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_version_id"],
            ["projection_profile_versions.id"],
            name="fk_projection_imports_profile_version",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(_SCORING_CHECK, name="ck_projection_imports_scoring_type"),
    )
    for column in (
        "row_count",
        "matched_count",
        "needs_review_count",
        "unmatched_count",
        "rejected_count",
    ):
        table.append_constraint(
            sa.CheckConstraint(
                f"{column} >= 0", name=f"ck_projection_imports_{column}_non_negative"
            )
        )
    if has_series:
        table.append_column(
            sa.Column("series_key", sa.String(64), nullable=False, server_default="legacy")
        )
        table.append_column(sa.Column("series_display_name", sa.String(128)))
        table.append_constraint(sa.CheckConstraint(_KEY_CHECK, name=_KEY_NAME))
        table.append_constraint(sa.CheckConstraint(_LABEL_CHECK, name=_LABEL_NAME))
        sa.Index(_INDEX_NAME, table.c.source_id, table.c.series_key, table.c.season)
    table.append_constraint(
        sa.UniqueConstraint(
            "source_id",
            *(("series_key",) if has_series else ()),
            "season",
            "content_sha256",
            "profile_version_id",
            name="uq_projection_imports_identity",
        )
    )
    for name in ("source_id", "season", "content_sha256", "profile_version_id"):
        sa.Index(f"ix_projection_imports_{name}", table.c[name])
    sa.Index("ix_projection_imports_source_season", table.c.source_id, table.c.season)
    return table


def _verify_descendants(connection: Connection) -> None:
    inspector = sa.inspect(connection)
    edges = [
        (table, fk["referred_table"], fk.get("options", {}).get("ondelete", "").upper())
        for table in inspector.get_table_names()
        for fk in inspector.get_foreign_keys(table)
    ]
    reached = {"projection_imports"}
    while True:
        expanded = reached | {table for table, parent, _ in edges if parent in reached}
        if expanded == reached:
            break
        reached = expanded
    expected = {
        ("projections", "projection_imports", "CASCADE"),
        ("source_games_played_assumptions", "projections", "CASCADE"),
    }
    actual = {(table, parent, action) for table, parent, action in edges if parent in reached}
    if actual != expected or reached != {"projection_imports", *_CHILDREN}:
        raise RuntimeError("0024 refuses an unexpected projection-import FK descendant closure")


def _stage_children(connection: Connection) -> dict[str, tuple[str, ...]]:
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
        raise RuntimeError("0024 requires SQLite foreign-key enforcement")
    # pysqlite's legacy mode begins for DML, not DDL. Keep the rebuild and
    # restoration in Alembic's transaction rather than relying on DDL to begin it.
    op.execute(sa.text("UPDATE projection_imports SET id = id WHERE 1 = 0"))
    inspector = sa.inspect(connection)
    columns = {
        table: tuple(column["name"] for column in inspector.get_columns(table))
        for table in _CHILDREN
    }
    for table in _CHILDREN:
        op.execute(
            sa.text(f'CREATE TEMPORARY TABLE "_series_0024_{table}" AS SELECT * FROM "{table}"')
        )
    return columns


def _restore_children(connection: Connection, columns: dict[str, tuple[str, ...]]) -> None:
    for table in _CHILDREN:
        names = ", ".join(f'"{name}"' for name in columns[table])
        op.execute(
            sa.text(f'INSERT INTO "{table}" ({names}) SELECT {names} FROM "_series_0024_{table}"')
        )
        for left, right in ((f"_series_0024_{table}", table), (table, f"_series_0024_{table}")):
            mismatch = connection.execute(
                sa.text(f'SELECT {names} FROM "{left}" EXCEPT SELECT {names} FROM "{right}"')
            ).first()
            if mismatch is not None:
                raise RuntimeError(f"0024 failed to preserve complete {table} rows")
    if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("0024 foreign-key verification failed")
    for table in _CHILDREN:
        op.execute(sa.text(f'DROP TABLE "_series_0024_{table}"'))


def _migrate(*, upgrading: bool) -> None:
    connection = op.get_bind()
    _verify_descendants(connection)
    sqlite = connection.dialect.name == "sqlite"
    columns = _stage_children(connection) if sqlite else None
    with op.batch_alter_table(
        "projection_imports",
        copy_from=_imports(has_series=not upgrading),
        recreate="always" if sqlite else "never",
    ) as batch:
        batch.drop_constraint("uq_projection_imports_identity", type_="unique")
        if upgrading:
            batch.add_column(
                sa.Column("series_key", sa.String(64), nullable=False, server_default="legacy")
            )
            batch.add_column(sa.Column("series_display_name", sa.String(128)))
            batch.create_check_constraint(op.f(_KEY_NAME), _KEY_CHECK)
            batch.create_check_constraint(op.f(_LABEL_NAME), _LABEL_CHECK)
            batch.create_unique_constraint(
                "uq_projection_imports_identity",
                ["source_id", "series_key", "season", "content_sha256", "profile_version_id"],
            )
            batch.create_index(_INDEX_NAME, ["source_id", "series_key", "season"])
        else:
            batch.drop_index(_INDEX_NAME)
            batch.drop_constraint(op.f(_KEY_NAME), type_="check")
            batch.drop_constraint(op.f(_LABEL_NAME), type_="check")
            batch.drop_column("series_display_name")
            batch.drop_column("series_key")
            batch.create_unique_constraint(
                "uq_projection_imports_identity",
                ["source_id", "season", "content_sha256", "profile_version_id"],
            )
    if columns is not None:
        _restore_children(connection, columns)


def upgrade() -> None:
    _migrate(upgrading=True)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT id FROM projection_imports WHERE series_key <> 'legacy' LIMIT 1"))
        .first()
        is not None
    ):
        raise RuntimeError("0024 downgrade would discard explicitly declared projection series")
    _migrate(upgrading=False)
