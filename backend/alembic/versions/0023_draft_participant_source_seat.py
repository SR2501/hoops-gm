"""draft-participant-source-seat: freeze rendered columns at draft creation.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-30

Existing drafts receive no binding. The nullable column therefore preserves
their evidence-only rendered-board behavior. A portable composite unique index
enforces that one source column cannot name two participants within a draft;
the creation service owns the cross-row complete-or-absent bijection.
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
