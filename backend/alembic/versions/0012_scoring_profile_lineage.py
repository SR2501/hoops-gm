"""Scoring profile lineage and single-active-per-league enforcement.

Backs the ``scoring-profiles`` backlog unit (docs/backlog.md) and
``hoops_gm.scoring.profiles`` -- see ``LeagueScoringProfile``'s docstring in
``db/models/league.py`` for the full rationale. Two changes to
``league_scoring_profiles``:

* ``settings_snapshot_id`` (not null): the ``league_settings_snapshots`` row
  that was current when this profile was derived, so "what rules produced
  this scoring configuration" stays answerable. ``league_scoring_profiles``
  has no rows in any known deployment of this schema (the feature was
  scaffolded in 0001 but never wired to an importer until now), so this
  column is added not-null with no backfill needed.
* ``active_league_id`` replaces the plain ``is_active`` boolean: it mirrors
  ``league_id`` while this row is the league's active profile and is
  ``NULL`` otherwise. A bare unique constraint on this one nullable column
  enforces "at most one active profile per league" at the database layer
  without a dialect-specific partial index (SQLite and Postgres both treat
  NULL as distinct in a unique constraint, so any number of inactive/retired
  versions coexist safely).

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("league_scoring_profiles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("settings_snapshot_id", sa.Integer(), nullable=False))
        batch_op.add_column(sa.Column("active_league_id", sa.Integer(), nullable=True))
        batch_op.drop_index(batch_op.f("ix_league_scoring_profiles_is_active"))
        batch_op.create_index(
            batch_op.f("ix_league_scoring_profiles_settings_snapshot_id"),
            ["settings_snapshot_id"],
            unique=False,
        )
        batch_op.create_unique_constraint(
            "uq_league_scoring_profiles_one_active", ["active_league_id"]
        )
        batch_op.create_foreign_key(
            "fk_league_scoring_profiles_settings_snapshot_id",
            "league_settings_snapshots",
            ["settings_snapshot_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_league_scoring_profiles_active_league_id_leagues"),
            "leagues",
            ["active_league_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_league_scoring_profiles_active_league_id_matches_league"),
            "active_league_id IS NULL OR active_league_id = league_id",
        )
        batch_op.drop_column("is_active")


def downgrade() -> None:
    with op.batch_alter_table("league_scoring_profiles", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.drop_constraint(
            batch_op.f("ck_league_scoring_profiles_active_league_id_matches_league"),
            type_="check",
        )
        batch_op.drop_constraint(
            batch_op.f("fk_league_scoring_profiles_active_league_id_leagues"),
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_league_scoring_profiles_settings_snapshot_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint("uq_league_scoring_profiles_one_active", type_="unique")
        batch_op.drop_index(batch_op.f("ix_league_scoring_profiles_settings_snapshot_id"))
        batch_op.create_index(
            batch_op.f("ix_league_scoring_profiles_is_active"), ["is_active"], unique=False
        )
        batch_op.drop_column("active_league_id")
        batch_op.drop_column("settings_snapshot_id")
