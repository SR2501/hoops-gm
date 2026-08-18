"""Extend schedule-context provenance and keyed refresh lineage.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REFRESH_ARTIFACT_TYPES_V1 = ("schedule", "projection", "model")
_REFRESH_ARTIFACT_TYPES_V2 = (*_REFRESH_ARTIFACT_TYPES_V1, "source")


def _in_list(column: str, values: Sequence[str]) -> str:
    rendered = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({rendered})"


def upgrade() -> None:
    # A temporary server default lets this remain a single safe ALTER on populated
    # databases. Existing schedule lineage gets its explicit stable key before the
    # default is removed; every other pre-0010 stream retains the legacy default key.
    op.add_column(
        "refresh_runs",
        sa.Column(
            "artifact_key",
            sa.String(length=64),
            server_default=sa.text("'default'"),
            nullable=False,
        ),
    )
    op.add_column(
        "refresh_runs",
        sa.Column(
            "season_key",
            sa.String(length=9),
            server_default=sa.text("'*'"),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE refresh_runs SET artifact_key = 'nba-schedule' WHERE artifact_type = 'schedule'"
        )
    )
    op.execute(sa.text("UPDATE refresh_runs SET season_key = season WHERE season IS NOT NULL"))
    with op.batch_alter_table("refresh_runs", schema=None) as batch_op:
        batch_op.alter_column(
            "artifact_key",
            existing_type=sa.String(length=64),
            server_default=None,
            existing_nullable=False,
        )
        batch_op.alter_column(
            "season_key",
            existing_type=sa.String(length=9),
            server_default=None,
            existing_nullable=False,
        )
        batch_op.drop_index("ix_refresh_runs_type_refreshed_at")
        batch_op.drop_constraint("uq_refresh_runs_type_version", type_="unique")
        batch_op.drop_constraint(
            batch_op.f("ck_refresh_runs_refresh_artifact_type"),
            type_="check",
        )
        batch_op.create_check_constraint(
            "refresh_artifact_type",
            _in_list("artifact_type", _REFRESH_ARTIFACT_TYPES_V2),
        )
        batch_op.create_unique_constraint(
            "uq_refresh_runs_type_key_version_season",
            ["artifact_type", "artifact_key", "version", "season_key"],
        )
        batch_op.create_check_constraint(
            "season_key_matches_season",
            "season_key = COALESCE(season, '*')",
        )
        batch_op.create_index(
            "ix_refresh_runs_current",
            ["artifact_type", "artifact_key", "season", "refreshed_at"],
        )

    op.add_column(
        "opponent_context",
        sa.Column(
            "source_version",
            sa.String(length=64),
            server_default=sa.text("'legacy-unbound'"),
            nullable=False,
        ),
    )
    with op.batch_alter_table("opponent_context", schema=None) as batch_op:
        batch_op.alter_column(
            "source_version",
            existing_type=sa.String(length=64),
            server_default=None,
            existing_nullable=False,
        )
        batch_op.alter_column(
            "garbage_time_suppression",
            existing_type=sa.Float(),
            nullable=True,
            existing_nullable=False,
        )
        batch_op.drop_constraint("uq_opponent_context_schedule_version", type_="unique")
        batch_op.create_unique_constraint(
            "uq_opponent_context_schedule_version",
            ["team_schedule_id", "model_version", "schedule_version", "source_version"],
        )
        batch_op.create_check_constraint(
            "blowout_probability_range",
            "blowout_probability >= 0 AND blowout_probability <= 1",
        )
        batch_op.create_check_constraint(
            "garbage_suppression_nonnegative",
            "garbage_time_suppression IS NULL OR garbage_time_suppression >= 0",
        )
        batch_op.create_check_constraint(
            "pace_window_nonnegative",
            "pace_window_games >= 0",
        )
        batch_op.create_check_constraint(
            "defence_window_nonnegative",
            "defence_window_games >= 0",
        )
        batch_op.create_check_constraint(
            "different_opponent",
            "team_id <> opponent_team_id",
        )

    op.add_column(
        "off_night_slates",
        sa.Column(
            "source_version",
            sa.String(length=64),
            server_default=sa.text("'legacy-unbound'"),
            nullable=False,
        ),
    )
    op.add_column(
        "off_night_slates",
        sa.Column(
            "input_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    with op.batch_alter_table("off_night_slates", schema=None) as batch_op:
        batch_op.alter_column(
            "source_version",
            existing_type=sa.String(length=64),
            server_default=None,
            existing_nullable=False,
        )
        batch_op.alter_column(
            "input_snapshot",
            existing_type=sa.JSON(),
            server_default=None,
            existing_nullable=False,
        )
        batch_op.drop_constraint("uq_off_night_slates_date_version", type_="unique")
        batch_op.create_unique_constraint(
            "uq_off_night_slates_date_version",
            ["slate_date", "model_version", "schedule_version", "source_version"],
        )
        batch_op.create_index(
            "ix_off_night_slates_source_version",
            ["source_version"],
        )
        batch_op.create_check_constraint(
            "light_slate_percentile_range",
            "light_slate_percentile IS NULL OR "
            "(light_slate_percentile >= 0 AND light_slate_percentile <= 1)",
        )
        batch_op.create_check_constraint(
            "threshold_percentile_range",
            "threshold_percentile IS NULL OR "
            "(threshold_percentile >= 0 AND threshold_percentile <= 1)",
        )
        batch_op.create_check_constraint(
            "scheduled_games_nonnegative",
            "scheduled_game_count >= 0",
        )
        batch_op.create_check_constraint(
            "scheduled_teams_nonnegative",
            "scheduled_team_count >= 0",
        )
        batch_op.create_check_constraint(
            "threshold_games_nonnegative",
            "threshold_games IS NULL OR threshold_games >= 0",
        )


def _downgrade_blockers() -> list[str]:
    connection = op.get_bind()
    checks = (
        (
            "source refresh lineage",
            "SELECT COUNT(*) FROM refresh_runs WHERE artifact_type = 'source'",
        ),
        (
            "keyed non-schedule lineage",
            "SELECT COUNT(*) FROM refresh_runs "
            "WHERE artifact_type <> 'schedule' AND artifact_key <> 'default'",
        ),
        (
            "keyed schedule lineage outside nba-schedule",
            "SELECT COUNT(*) FROM refresh_runs "
            "WHERE artifact_type = 'schedule' AND artifact_key <> 'nba-schedule'",
        ),
        (
            "lineage versions that collide under the 0005 key",
            "SELECT COUNT(*) FROM ("
            "SELECT 1 FROM refresh_runs GROUP BY artifact_type, version HAVING COUNT(*) > 1"
            ") AS lineage_collisions",
        ),
        (
            "opponent context with 0010-only provenance",
            "SELECT COUNT(*) FROM opponent_context "
            "WHERE source_version <> 'legacy-unbound' OR garbage_time_suppression IS NULL",
        ),
        (
            "opponent context that collides under the 0005 key",
            "SELECT COUNT(*) FROM ("
            "SELECT 1 FROM opponent_context "
            "GROUP BY team_schedule_id, model_version, schedule_version HAVING COUNT(*) > 1"
            ") AS opponent_collisions",
        ),
        (
            "off-night context with 0010-only provenance",
            "SELECT COUNT(*) FROM off_night_slates WHERE source_version <> 'legacy-unbound'",
        ),
        (
            "off-night context that collides under the 0005 key",
            "SELECT COUNT(*) FROM ("
            "SELECT 1 FROM off_night_slates "
            "GROUP BY slate_date, model_version, schedule_version HAVING COUNT(*) > 1"
            ") AS slate_collisions",
        ),
    )
    return [
        label
        for label, statement in checks
        if connection.scalar(sa.text(statement)) not in (None, 0)
    ]


def downgrade() -> None:
    blockers = _downgrade_blockers()
    if blockers:
        joined = ", ".join(blockers)
        raise RuntimeError(
            "refusing lossy 0010 downgrade; archive or explicitly remove incompatible "
            f"history first: {joined}"
        )

    with op.batch_alter_table("off_night_slates", schema=None) as batch_op:
        batch_op.drop_index("ix_off_night_slates_source_version")
        batch_op.drop_constraint(
            batch_op.f("ck_off_night_slates_threshold_games_nonnegative"),
            type_="check",
        )
        batch_op.drop_constraint(
            batch_op.f("ck_off_night_slates_scheduled_teams_nonnegative"),
            type_="check",
        )
        batch_op.drop_constraint(
            batch_op.f("ck_off_night_slates_scheduled_games_nonnegative"),
            type_="check",
        )
        batch_op.drop_constraint(
            batch_op.f("ck_off_night_slates_threshold_percentile_range"),
            type_="check",
        )
        batch_op.drop_constraint(
            batch_op.f("ck_off_night_slates_light_slate_percentile_range"),
            type_="check",
        )
        batch_op.drop_constraint("uq_off_night_slates_date_version", type_="unique")
        batch_op.create_unique_constraint(
            "uq_off_night_slates_date_version",
            ["slate_date", "model_version", "schedule_version"],
        )
        batch_op.drop_column("input_snapshot")
        batch_op.drop_column("source_version")

    with op.batch_alter_table("opponent_context", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("ck_opponent_context_different_opponent"),
            type_="check",
        )
        batch_op.drop_constraint(
            batch_op.f("ck_opponent_context_defence_window_nonnegative"),
            type_="check",
        )
        batch_op.drop_constraint(
            batch_op.f("ck_opponent_context_pace_window_nonnegative"),
            type_="check",
        )
        batch_op.drop_constraint(
            batch_op.f("ck_opponent_context_garbage_suppression_nonnegative"),
            type_="check",
        )
        batch_op.drop_constraint(
            batch_op.f("ck_opponent_context_blowout_probability_range"),
            type_="check",
        )
        batch_op.drop_constraint("uq_opponent_context_schedule_version", type_="unique")
        batch_op.create_unique_constraint(
            "uq_opponent_context_schedule_version",
            ["team_schedule_id", "model_version", "schedule_version"],
        )
        batch_op.alter_column(
            "garbage_time_suppression",
            existing_type=sa.Float(),
            nullable=False,
            existing_nullable=True,
        )
        batch_op.drop_column("source_version")

    with op.batch_alter_table("refresh_runs", schema=None) as batch_op:
        batch_op.drop_index("ix_refresh_runs_current")
        batch_op.drop_constraint(
            batch_op.f("ck_refresh_runs_season_key_matches_season"),
            type_="check",
        )
        batch_op.drop_constraint(
            "uq_refresh_runs_type_key_version_season",
            type_="unique",
        )
        batch_op.drop_constraint(
            batch_op.f("ck_refresh_runs_refresh_artifact_type"),
            type_="check",
        )
        batch_op.create_check_constraint(
            "refresh_artifact_type",
            _in_list("artifact_type", _REFRESH_ARTIFACT_TYPES_V1),
        )
        batch_op.create_unique_constraint(
            "uq_refresh_runs_type_version",
            ["artifact_type", "version"],
        )
        batch_op.create_index(
            "ix_refresh_runs_type_refreshed_at",
            ["artifact_type", "refreshed_at"],
        )
        batch_op.drop_column("season_key")
        batch_op.drop_column("artifact_key")
