"""Direct-evidence absence splits with complete computation cohorts.

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
        "absence_split_runs",
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
        sa.Column("evidence_version", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("schedule_version", sa.String(length=64), nullable=False),
        sa.Column("schedule_refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("skipped_one_sided_pairs", sa.Integer(), nullable=False),
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
            "result_count >= 0",
            name=op.f("ck_absence_split_runs_result_count_non_negative"),
        ),
        sa.CheckConstraint(
            "skipped_one_sided_pairs >= 0",
            name=op.f("ck_absence_split_runs_skipped_pairs_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_absence_split_runs")),
        sa.UniqueConstraint(
            "season",
            "season_type",
            "evidence_version",
            "schedule_version",
            "input_fingerprint",
            name="uq_absence_split_runs_input",
        ),
    )
    op.create_index(
        "ix_absence_split_runs_current",
        "absence_split_runs",
        ["season", "season_type", "evidence_version", "schedule_version", "id"],
    )

    op.create_table(
        "absence_splits",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("beneficiary_player_id", sa.Integer(), nullable=False),
        sa.Column("absent_player_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("games_with", sa.Integer(), nullable=False),
        sa.Column("games_without", sa.Integer(), nullable=False),
        sa.Column("observed_absence_games", sa.Integer(), nullable=False),
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
            "observed_absence_games = games_without",
            name=op.f("ck_absence_splits_all_absences_observed"),
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
            ["run_id"],
            ["absence_split_runs.id"],
            name=op.f("fk_absence_splits_run_id_absence_split_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["nba_teams.id"],
            name=op.f("fk_absence_splits_team_id_nba_teams"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_absence_splits")),
        sa.UniqueConstraint(
            "run_id",
            "beneficiary_player_id",
            "absent_player_id",
            "team_id",
            name="uq_absence_splits_run_pair",
        ),
    )
    op.create_index(
        "ix_absence_splits_absent_player",
        "absence_splits",
        ["absent_player_id"],
    )
    op.create_index(
        "ix_absence_splits_beneficiary_player",
        "absence_splits",
        ["beneficiary_player_id"],
    )
    op.create_index("ix_absence_splits_run", "absence_splits", ["run_id"])
    op.create_index("ix_absence_splits_team", "absence_splits", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_absence_splits_team", table_name="absence_splits")
    op.drop_index("ix_absence_splits_run", table_name="absence_splits")
    op.drop_index("ix_absence_splits_beneficiary_player", table_name="absence_splits")
    op.drop_index("ix_absence_splits_absent_player", table_name="absence_splits")
    op.drop_table("absence_splits")

    op.drop_index("ix_absence_split_runs_current", table_name="absence_split_runs")
    op.drop_table("absence_split_runs")
