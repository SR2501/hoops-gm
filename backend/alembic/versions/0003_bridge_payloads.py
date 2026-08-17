"""Authenticated raw browser-bridge payload storage.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bridge_payloads",
        sa.Column("schema", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_method", sa.Text(), nullable=False),
        sa.Column("request_url", sa.Text(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_ok", sa.Boolean(), nullable=False),
        sa.Column("response_content_type", sa.Text(), nullable=True),
        sa.Column("body_raw", sa.Text(), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=True),
        sa.Column("body_parse_error", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("raw_payload", sa.Text(), nullable=False),
        sa.Column("replay_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_replayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_replay_error", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bridge_payloads")),
    )
    op.create_index("ix_bridge_payloads_captured_at", "bridge_payloads", ["captured_at"])
    op.create_index("ix_bridge_payloads_dedupe_key", "bridge_payloads", ["dedupe_key"])


def downgrade() -> None:
    op.drop_index("ix_bridge_payloads_dedupe_key", table_name="bridge_payloads")
    op.drop_index("ix_bridge_payloads_captured_at", table_name="bridge_payloads")
    op.drop_table("bridge_payloads")
