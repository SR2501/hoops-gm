"""Injury report entries: raw per-report status history for NBA players.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-17
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
        "injury_report_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("game_time_raw", sa.String(length=32), nullable=False),
        sa.Column("matchup_raw", sa.String(length=16), nullable=False),
        sa.Column("team_raw", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("player_name_raw", sa.String(length=128), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=True),
        sa.Column("status_raw", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "out",
                "doubtful",
                "questionable",
                "probable",
                "available",
                "not_yet_submitted",
                name="injury_report_status",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("reason_raw", sa.Text(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "nba",
                "fantrax",
                "fantrax_stats_inc",
                "fantrax_rotowire",
                "fantrax_sportradar",
                "fantasypros",
                "hashtag",
                "basketball_monster",
                "darko",
                "manual",
                name="external_source",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("source_url", sa.String(length=255), nullable=False),
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
            ["team_id"],
            ["nba_teams.id"],
            name=op.f("fk_injury_report_entries_team_id_nba_teams"),
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["nba_games.id"],
            name=op.f("fk_injury_report_entries_game_id_nba_games"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name=op.f("fk_injury_report_entries_player_id_players"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_injury_report_entries")),
        sa.UniqueConstraint(
            "report_timestamp",
            "team_raw",
            "player_name_raw",
            name="uq_injury_report_entries_report_team_player",
        ),
    )
    op.create_index("ix_injury_report_entries_game_date", "injury_report_entries", ["game_date"])
    op.create_index("ix_injury_report_entries_game_id", "injury_report_entries", ["game_id"])
    op.create_index("ix_injury_report_entries_player_id", "injury_report_entries", ["player_id"])
    op.create_index(
        "ix_injury_report_entries_player_report",
        "injury_report_entries",
        ["player_id", "report_timestamp"],
    )
    op.create_index(
        "ix_injury_report_entries_report_timestamp",
        "injury_report_entries",
        ["report_timestamp"],
    )
    op.create_index("ix_injury_report_entries_team_id", "injury_report_entries", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_injury_report_entries_team_id", table_name="injury_report_entries")
    op.drop_index("ix_injury_report_entries_report_timestamp", table_name="injury_report_entries")
    op.drop_index("ix_injury_report_entries_player_report", table_name="injury_report_entries")
    op.drop_index("ix_injury_report_entries_player_id", table_name="injury_report_entries")
    op.drop_index("ix_injury_report_entries_game_id", table_name="injury_report_entries")
    op.drop_index("ix_injury_report_entries_game_date", table_name="injury_report_entries")
    op.drop_table("injury_report_entries")
