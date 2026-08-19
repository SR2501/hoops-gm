"""Add import_schema_version to injury_report_entries; stamp existing rows legacy.

Migration 0013 fixed a real natural-key collision (a back-to-back's second
night silently overwriting the first as an ordinary "update"). Any row whose
*last write* predates this migration cannot be algorithmically proven free of
that collision after the fact — the overwrite, if it happened, already
destroyed the very evidence that would show it did. This migration adds
``import_schema_version`` and stamps every row that already exists as ``1``
(legacy, unverified); the importer writes ``2`` (current) on every create and
update from this point forward, so a legacy row is upgraded automatically the
next time a real re-import touches it under the fixed key. See
``db.models.injury_report`` and
``injury_report.backfill.select_canonical_pregame_observations``, which
defaults to excluding version-1 rows.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-19

Note: originally cut as revision 0013 (down_revision 0012); renumbered to
0014 (down_revision 0013) after PR #22 merged to main and claimed 0012 for
``0012_scoring_profile_lineage``, which pushed this PR's natural-key fix
migration from 0012 to 0013. See docs/handoff.md for the rebase entry.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY = 1
_CURRENT = 2


def upgrade() -> None:
    with op.batch_alter_table("injury_report_entries", schema=None) as batch_op:
        # Added nullable first so the ALTER never fails against rows that
        # already exist, then backfilled and tightened to NOT NULL — the
        # standard "add nullable, backfill, tighten" sequence this project's
        # other migrations already use for a new non-null column on a
        # populated table.
        batch_op.add_column(
            sa.Column(
                "import_schema_version",
                sa.SmallInteger(),
                nullable=True,
            )
        )

    op.execute(
        sa.text(
            "UPDATE injury_report_entries SET import_schema_version = :legacy "
            "WHERE import_schema_version IS NULL"
        ).bindparams(legacy=_LEGACY)
    )

    with op.batch_alter_table("injury_report_entries", schema=None) as batch_op:
        batch_op.alter_column(
            "import_schema_version",
            existing_type=sa.SmallInteger(),
            nullable=False,
            server_default=str(_CURRENT),
        )


def downgrade() -> None:
    with op.batch_alter_table("injury_report_entries", schema=None) as batch_op:
        batch_op.drop_column("import_schema_version")
