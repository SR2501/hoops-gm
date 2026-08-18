"""League deadline calendars: the versioned join of settings lineage and schedule lineage.

Adds ``league_deadline_calendars`` backing
``hoops_gm.db.models.deadline_calendar.LeagueDeadlineCalendar`` -- see that
module's docstring for the full rationale. One immutable row per
``(league_id, version)`` joining an exact settings-snapshot lineage pointer
with a denormalized schedule-refresh lineage pointer, exposing season bounds
and scoring-period boundaries while carrying every other timing rule forward
as an explicit, source-attributed unknown. ``current_for_league`` is a
portable "current marker" column (same technique as
``player_external_ids.current_for_source``): it holds the row's own
``league_id`` while active and NULL once superseded, with a plain unique
constraint rather than a dialect-specific partial index.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "league_deadline_calendars",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("current_for_league", sa.Integer(), nullable=True),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("season", sa.String(length=9), nullable=False),
        sa.Column("settings_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("settings_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("schedule_version", sa.String(length=64), nullable=False),
        sa.Column("schedule_refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("season_start_date", sa.Date(), nullable=False),
        sa.Column("season_end_date", sa.Date(), nullable=False),
        sa.Column("scoring_periods", sa.JSON(), nullable=False),
        sa.Column("unsupported_rules", sa.JSON(), nullable=False),
        sa.Column("derived_at", sa.DateTime(timezone=True), nullable=False),
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
            name=op.f("fk_league_deadline_calendars_league_id_leagues"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["settings_snapshot_id"],
            ["league_settings_snapshots.id"],
            name=op.f("fk_league_deadline_calendars_settings_snapshot_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_league_deadline_calendars")),
        sa.UniqueConstraint("league_id", "version", name="uq_league_deadline_calendars_version"),
        sa.UniqueConstraint("current_for_league", name="uq_league_deadline_calendars_current"),
        sa.UniqueConstraint(
            "league_id",
            "settings_snapshot_id",
            "schedule_version",
            name="uq_league_deadline_calendars_lineage",
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_league_deadline_calendars_version_positive")
        ),
        sa.CheckConstraint(
            "season_end_date >= season_start_date",
            name=op.f("ck_league_deadline_calendars_season_dates_ordered"),
        ),
        sa.CheckConstraint(
            "current_for_league IS NULL OR current_for_league = league_id",
            name=op.f("ck_league_deadline_calendars_current_marker_matches_league"),
        ),
    )
    op.create_index(
        "ix_league_deadline_calendars_league_id",
        "league_deadline_calendars",
        ["league_id"],
    )
    op.create_index(
        "ix_league_deadline_calendars_settings_snapshot_id",
        "league_deadline_calendars",
        ["settings_snapshot_id"],
    )
    op.create_index(
        "ix_league_deadline_calendars_season",
        "league_deadline_calendars",
        ["season"],
    )
    op.create_index(
        "ix_league_deadline_calendars_league_season",
        "league_deadline_calendars",
        ["league_id", "season"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_league_deadline_calendars_league_season", table_name="league_deadline_calendars"
    )
    op.drop_index("ix_league_deadline_calendars_season", table_name="league_deadline_calendars")
    op.drop_index(
        "ix_league_deadline_calendars_settings_snapshot_id",
        table_name="league_deadline_calendars",
    )
    op.drop_index("ix_league_deadline_calendars_league_id", table_name="league_deadline_calendars")
    op.drop_table("league_deadline_calendars")
