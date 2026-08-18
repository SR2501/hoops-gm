"""Schedule context tables for quant-owned conditioning features.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "opponent_context",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("season", sa.String(length=9), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("team_schedule_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("opponent_team_id", sa.Integer(), nullable=False),
        sa.Column("is_home", sa.Boolean(), nullable=False),
        sa.Column("pace_possessions", sa.Float(), nullable=False),
        sa.Column("pace_window_games", sa.Integer(), nullable=False),
        sa.Column("category_defence", sa.JSON(), nullable=False),
        sa.Column("defence_window_games", sa.Integer(), nullable=False),
        sa.Column("blowout_probability", sa.Float(), nullable=False),
        sa.Column("garbage_time_suppression", sa.Float(), nullable=False),
        sa.Column("training_cutoff", sa.Date(), nullable=True),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
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
            ["team_schedule_id"],
            ["team_schedule.id"],
            name=op.f("fk_opponent_context_team_schedule_id_team_schedule"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["nba_teams.id"],
            name=op.f("fk_opponent_context_team_id_nba_teams"),
        ),
        sa.ForeignKeyConstraint(
            ["opponent_team_id"],
            ["nba_teams.id"],
            name=op.f("fk_opponent_context_opponent_team_id_nba_teams"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opponent_context")),
        sa.UniqueConstraint(
            "team_schedule_id", "model_version", name="uq_opponent_context_schedule_version"
        ),
    )
    op.create_index("ix_opponent_context_game_date", "opponent_context", ["game_date"])
    op.create_index("ix_opponent_context_model_version", "opponent_context", ["model_version"])
    op.create_index("ix_opponent_context_team_date", "opponent_context", ["team_id", "game_date"])
    op.create_index("ix_opponent_context_team_schedule", "opponent_context", ["team_schedule_id"])

    op.create_table(
        "off_night_slates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("season", sa.String(length=9), nullable=False),
        sa.Column("slate_date", sa.Date(), nullable=False),
        sa.Column("scheduled_game_count", sa.Integer(), nullable=False),
        sa.Column("scheduled_team_count", sa.Integer(), nullable=False),
        sa.Column("is_off_night", sa.Boolean(), nullable=False),
        sa.Column("light_slate_percentile", sa.Float(), nullable=True),
        sa.Column("threshold_games", sa.Integer(), nullable=True),
        sa.Column("threshold_percentile", sa.Float(), nullable=True),
        sa.Column("streaming_window_score", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_off_night_slates")),
        sa.UniqueConstraint("slate_date", "model_version", name="uq_off_night_slates_date_version"),
    )
    op.create_index("ix_off_night_slates_model_version", "off_night_slates", ["model_version"])
    op.create_index("ix_off_night_slates_slate_date", "off_night_slates", ["slate_date"])


def downgrade() -> None:
    op.drop_index("ix_off_night_slates_slate_date", table_name="off_night_slates")
    op.drop_index("ix_off_night_slates_model_version", table_name="off_night_slates")
    op.drop_table("off_night_slates")

    op.drop_index("ix_opponent_context_team_schedule", table_name="opponent_context")
    op.drop_index("ix_opponent_context_team_date", table_name="opponent_context")
    op.drop_index("ix_opponent_context_model_version", table_name="opponent_context")
    op.drop_index("ix_opponent_context_game_date", table_name="opponent_context")
    op.drop_table("opponent_context")
