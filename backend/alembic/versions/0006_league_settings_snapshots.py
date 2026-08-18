"""League settings snapshots: the versioned, source-attributed rules boundary.

Adds ``league_settings_snapshots`` backing
``hoops_gm.db.models.league_settings.LeagueSettingsSnapshot`` -- see that
module's docstring for the full rationale. In short: one immutable row per
``(league_id, version)`` carrying the normalized settings document, per-field
source provenance, a hash of the raw upstream payload, and when the data was
observed. Absent-from-source fields are represented as JSON ``null`` inside
``settings`` by the caller, never filled from a historical baseline and never
enforced by a constraint here, because that is a document-shape guarantee the
typed ingestion boundary owns, not something a database CHECK can express.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "league_settings_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("source_summary", sa.JSON(), nullable=False),
        sa.Column("source_payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["league_id"],
            ["leagues.id"],
            name=op.f("fk_league_settings_snapshots_league_id_leagues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_league_settings_snapshots")),
        sa.UniqueConstraint("league_id", "version", name="uq_league_settings_snapshots_version"),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_league_settings_snapshots_version_positive")
        ),
        sa.CheckConstraint(
            "length(source_payload_sha256) = 64",
            name=op.f("ck_league_settings_snapshots_source_payload_sha256_length"),
        ),
    )
    op.create_index(
        "ix_league_settings_snapshots_league_id", "league_settings_snapshots", ["league_id"]
    )
    op.create_index(
        "ix_league_settings_snapshots_league_observed_at",
        "league_settings_snapshots",
        ["league_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_league_settings_snapshots_league_observed_at",
        table_name="league_settings_snapshots",
    )
    op.drop_index("ix_league_settings_snapshots_league_id", table_name="league_settings_snapshots")
    op.drop_table("league_settings_snapshots")
