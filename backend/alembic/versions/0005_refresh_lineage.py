"""Refresh lineage: the schedule/projection/model cohort registry.

Adds ``refresh_runs``, the provenance registry backing
``hoops_gm.db.lineage``. It records when a schedule, projection, or model
artifact was last (re)computed at a given version, so a downstream consumer
can ask whether its claimed version is still current instead of trusting
whatever string it was handed. It does not compute anything -- see
``db/models/lineage.py`` for the boundary this deliberately does not cross.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "refresh_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "artifact_type",
            sa.Enum(
                "schedule",
                "projection",
                "model",
                name="refresh_artifact_type",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("season", sa.String(length=9), nullable=True),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_runs")),
        sa.UniqueConstraint("artifact_type", "version", name="uq_refresh_runs_type_version"),
    )
    op.create_index(
        "ix_refresh_runs_type_refreshed_at",
        "refresh_runs",
        ["artifact_type", "refreshed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_runs_type_refreshed_at", table_name="refresh_runs")
    op.drop_table("refresh_runs")
