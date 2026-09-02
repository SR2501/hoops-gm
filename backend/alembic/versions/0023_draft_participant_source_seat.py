"""draft-source-board-profile: freeze rendered-board evidence at creation.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-30

Existing drafts receive neither a binding nor an evidence profile and therefore
remain evidence-only. The only profile names the recorded football snake corpus;
storage also refuses that profile on real or non-snake drafts. A portable
composite unique index enforces that one source column cannot name two
participants within a draft; the creation service owns the cross-row
complete-or-absent bijection and requires it whenever a profile is selected.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "drafts",
        sa.Column(
            "source_board_profile",
            sa.String(length=48),
            sa.CheckConstraint(
                "source_board_profile IN ('fantrax_football_snake_v1')",
                name=op.f("ck_drafts_draft_source_board_profile"),
            ),
            sa.CheckConstraint(
                "source_board_profile IS NULL OR (is_mock AND draft_type = 'snake')",
                name=op.f("ck_drafts_source_board_profile_compatible"),
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "draft_participants",
        sa.Column(
            "source_seat",
            sa.Integer(),
            sa.CheckConstraint(
                "source_seat IS NULL OR source_seat >= 1",
                name=op.f("ck_draft_participants_source_seat_positive"),
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_draft_participants_draft_source_seat",
        "draft_participants",
        ["draft_id", "source_seat"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_draft_participants_draft_source_seat",
        table_name="draft_participants",
    )
    op.drop_column("draft_participants", "source_seat")
    op.drop_column("drafts", "source_board_profile")
