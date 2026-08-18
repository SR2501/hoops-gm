"""Allow recurring absence-split fingerprints to create fresh activations.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INPUT_COLUMNS = [
    "season",
    "season_type",
    "evidence_version",
    "schedule_version",
    "input_fingerprint",
]
_SPLIT_COLUMNS = [
    "run_id",
    "beneficiary_player_id",
    "absent_player_id",
    "team_id",
    "games_with",
    "games_without",
    "observed_absence_games",
    "production_with",
    "production_without",
    "descriptive_deltas",
    "uncertainty",
    "provenance",
    "data_layer",
    "claim_type",
    "id",
    "created_at",
    "updated_at",
]
_BACKUP_TABLE = "_absence_splits_0007_backup"


def upgrade() -> None:
    rebuilds_parent = op.get_bind().dialect.name == "sqlite"
    if rebuilds_parent:
        _backup_splits()
    with op.batch_alter_table("absence_split_runs", schema=None) as batch_op:
        batch_op.drop_constraint("uq_absence_split_runs_input", type_="unique")
    if rebuilds_parent:
        _restore_splits()


def downgrade() -> None:
    columns = ", ".join(_INPUT_COLUMNS)
    op.execute(
        sa.text(
            f"DELETE FROM absence_split_runs WHERE id NOT IN "
            f"(SELECT MAX(id) FROM absence_split_runs GROUP BY {columns})"
        )
    )
    rebuilds_parent = op.get_bind().dialect.name == "sqlite"
    if rebuilds_parent:
        _backup_splits()
    with op.batch_alter_table("absence_split_runs", schema=None) as batch_op:
        batch_op.create_unique_constraint("uq_absence_split_runs_input", _INPUT_COLUMNS)
    if rebuilds_parent:
        _restore_splits()


def _backup_splits() -> None:
    columns = ", ".join(_SPLIT_COLUMNS)
    op.execute(
        sa.text(f"CREATE TABLE {_BACKUP_TABLE} AS SELECT {columns} FROM absence_splits WHERE 1 = 0")
    )
    op.execute(
        sa.text(f"INSERT INTO {_BACKUP_TABLE} ({columns}) SELECT {columns} FROM absence_splits")
    )


def _restore_splits() -> None:
    columns = ", ".join(_SPLIT_COLUMNS)
    op.execute(
        sa.text(f"INSERT INTO absence_splits ({columns}) SELECT {columns} FROM {_BACKUP_TABLE}")
    )
    op.execute(sa.text(f"DROP TABLE {_BACKUP_TABLE}"))
