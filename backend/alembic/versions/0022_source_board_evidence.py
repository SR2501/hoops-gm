"""source-board-evidence: preserve rendered coordinates without attribution.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-29

Board observations gain the source's column ordinal and mutable label. Explicit
successful-reading rows preserve content identity and occupied-slot summaries,
including valid zero-pick boards. A small per-draft state table records the
latest newly stored board and the latest refusal/contact so ``no reading``,
``refused`` and ``available`` cannot collapse into the same empty response.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("draft_feed_observations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_seat", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_seat_label", sa.String(length=128), nullable=True))

    op.create_table(
        "draft_source_board_readings",
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("bridge_payload_id", sa.Integer(), nullable=False),
        sa.Column("artifact_key", sa.String(length=128), nullable=False),
        sa.Column("recogniser", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("layout", sa.String(length=16), nullable=False),
        sa.Column("seat_count", sa.Integer(), nullable=False),
        sa.Column("round_count", sa.Integer(), nullable=False),
        sa.Column("picks_made", sa.Integer(), nullable=False),
        sa.Column("seat_labels", sa.JSON(), nullable=False),
        sa.Column("occupied_slots", sa.JSON(), nullable=False),
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "picks_made >= 0",
            name=op.f("ck_draft_source_board_readings_picks_nonnegative"),
        ),
        sa.CheckConstraint(
            "round_count >= 1",
            name=op.f("ck_draft_source_board_readings_rounds_positive"),
        ),
        sa.CheckConstraint(
            "seat_count >= 1",
            name=op.f("ck_draft_source_board_readings_seats_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["bridge_payload_id"],
            ["bridge_payloads.id"],
            name="fk_board_reading_bridge_payload",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["drafts.id"],
            name=op.f("fk_draft_source_board_readings_draft_id_drafts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draft_source_board_readings")),
        sa.UniqueConstraint(
            "draft_id",
            "artifact_key",
            name=op.f("uq_draft_source_board_readings_draft_artifact"),
        ),
    )
    with op.batch_alter_table("draft_source_board_readings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_draft_source_board_readings_artifact_key"),
            ["artifact_key"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_draft_source_board_readings_bridge_payload_id"),
            ["bridge_payload_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_draft_source_board_readings_draft_id"),
            ["draft_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_draft_source_board_readings_observed_at"),
            ["observed_at"],
            unique=False,
        )

    op.create_table(
        "draft_source_board_states",
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("latest_bridge_payload_id", sa.Integer(), nullable=False),
        sa.Column("artifact_key", sa.String(length=128), nullable=True),
        sa.Column("recogniser", sa.String(length=64), nullable=False),
        sa.Column("board_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contact_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refusal_reason", sa.Text(), nullable=True),
        sa.Column("layout", sa.String(length=16), nullable=True),
        sa.Column("seat_count", sa.Integer(), nullable=True),
        sa.Column("round_count", sa.Integer(), nullable=True),
        sa.Column("picks_made", sa.Integer(), nullable=True),
        sa.Column("seat_labels", sa.JSON(), nullable=True),
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
        sa.CheckConstraint(
            "picks_made IS NULL OR picks_made >= 0",
            name=op.f("ck_draft_source_board_states_source_board_picks_nonnegative"),
        ),
        sa.CheckConstraint(
            "round_count IS NULL OR round_count >= 1",
            name=op.f("ck_draft_source_board_states_source_board_rounds_positive"),
        ),
        sa.CheckConstraint(
            "seat_count IS NULL OR seat_count >= 1",
            name=op.f("ck_draft_source_board_states_source_board_seats_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["latest_bridge_payload_id"],
            ["bridge_payloads.id"],
            name="fk_board_state_latest_bridge_payload",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["drafts.id"],
            name=op.f("fk_draft_source_board_states_draft_id_drafts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("draft_id", name=op.f("pk_draft_source_board_states")),
    )
    with op.batch_alter_table("draft_source_board_states", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_draft_source_board_states_artifact_key"),
            ["artifact_key"],
            unique=False,
        )

    registry = sa.table(
        "data_layer_registry",
        sa.column("table_name", sa.String),
        sa.column("data_layer", sa.String),
        sa.column("layer_rank", sa.Integer),
    )
    op.bulk_insert(
        registry,
        [
            {
                "table_name": "draft_source_board_readings",
                "data_layer": "observations",
                "layer_rank": 0,
            },
            {
                "table_name": "draft_source_board_states",
                "data_layer": "observations",
                "layer_rank": 0,
            },
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM data_layer_registry WHERE table_name IN "
            "('draft_source_board_readings', 'draft_source_board_states')"
        )
    )
    op.drop_table("draft_source_board_states")
    op.drop_table("draft_source_board_readings")
    with op.batch_alter_table("draft_feed_observations", schema=None) as batch_op:
        batch_op.drop_column("source_seat_label")
        batch_op.drop_column("source_seat")
