"""Descriptive teammate with/without production evidence.

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
        "absence_splits",
        sa.Column("beneficiary_player_id", sa.Integer(), nullable=False),
        sa.Column("absent_player_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.String(length=9), nullable=False),
        sa.Column(
            "season_type",
            sa.Enum(
                "preseason",
                "regular",
                "play_in",
                "playoffs",
                name="season_type",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("games_with", sa.Integer(), nullable=False),
        sa.Column("games_without", sa.Integer(), nullable=False),
        sa.Column("explicit_absence_games", sa.Integer(), nullable=False),
        sa.Column("inferred_absence_games", sa.Integer(), nullable=False),
        sa.Column("excluded_unknown_games", sa.Integer(), nullable=False),
        sa.Column("production_with", sa.JSON(), nullable=False),
        sa.Column("production_without", sa.JSON(), nullable=False),
        sa.Column("descriptive_deltas", sa.JSON(), nullable=False),
        sa.Column("uncertainty", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column(
            "data_layer",
            sa.String(length=32),
            server_default="observations",
            nullable=False,
        ),
        sa.Column(
            "claim_type",
            sa.String(length=32),
            server_default="descriptive",
            nullable=False,
        ),
        sa.Column("membership_method", sa.String(length=64), nullable=False),
        sa.Column("evidence_version", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("schedule_version", sa.String(length=64), nullable=False),
        sa.Column("schedule_refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint(
            "explicit_absence_games + inferred_absence_games = games_without",
            name=op.f("ck_absence_splits_absence_provenance_counts_match"),
        ),
        sa.CheckConstraint(
            "claim_type = 'descriptive'",
            name=op.f("ck_absence_splits_descriptive_claim_only"),
        ),
        sa.CheckConstraint(
            "beneficiary_player_id <> absent_player_id",
            name=op.f("ck_absence_splits_distinct_players"),
        ),
        sa.CheckConstraint(
            "games_with > 0",
            name=op.f("ck_absence_splits_games_with_positive"),
        ),
        sa.CheckConstraint(
            "games_without > 0",
            name=op.f("ck_absence_splits_games_without_positive"),
        ),
        sa.CheckConstraint(
            "data_layer = 'observations'",
            name=op.f("ck_absence_splits_observation_layer_only"),
        ),
        sa.ForeignKeyConstraint(
            ["absent_player_id"],
            ["players.id"],
            name=op.f("fk_absence_splits_absent_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["beneficiary_player_id"],
            ["players.id"],
            name=op.f("fk_absence_splits_beneficiary_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["nba_teams.id"],
            name=op.f("fk_absence_splits_team_id_nba_teams"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_absence_splits")),
        sa.UniqueConstraint(
            "beneficiary_player_id",
            "absent_player_id",
            "team_id",
            "season",
            "season_type",
            "evidence_version",
            "input_fingerprint",
            name="uq_absence_splits_pair_evidence",
        ),
    )
    op.create_index(
        "ix_absence_splits_absent_season",
        "absence_splits",
        ["absent_player_id", "season"],
    )
    op.create_index(
        "ix_absence_splits_beneficiary_season",
        "absence_splits",
        ["beneficiary_player_id", "season"],
    )
    op.create_index(
        "ix_absence_splits_evidence_version",
        "absence_splits",
        ["evidence_version"],
    )
    op.create_index(
        "ix_absence_splits_schedule_version",
        "absence_splits",
        ["schedule_version"],
    )
    op.create_index(
        "ix_absence_splits_team_season",
        "absence_splits",
        ["team_id", "season"],
    )


def downgrade() -> None:
    op.drop_index("ix_absence_splits_team_season", table_name="absence_splits")
    op.drop_index("ix_absence_splits_schedule_version", table_name="absence_splits")
    op.drop_index("ix_absence_splits_evidence_version", table_name="absence_splits")
    op.drop_index("ix_absence_splits_beneficiary_season", table_name="absence_splits")
    op.drop_index("ix_absence_splits_absent_season", table_name="absence_splits")
    op.drop_table("absence_splits")
