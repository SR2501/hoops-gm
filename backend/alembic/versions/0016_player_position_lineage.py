"""player-position-eligibility (NBA half): lineage for the listed NBA position

``players.primary_position`` has existed since 0001 and has never been written
by anything. This revision does not add it; it adds the three columns that make
writing it honest — where the value came from, which season's listing it was
read from, and when.

Why provenance rather than just the value: risk R7 specifies the identity
crosswalk to match on "normalized name + team + position", and until 2026-08-20
this project ingested no player position at all, so that third key could only
ever have been two-key. The value now comes from ``PlayerIndex``. A stored
attribute with no record of its origin cannot be refreshed deliberately, and
cannot be told apart from a later second opinion — Fantrax's stated position, a
projection CSV's — which is exactly the laundering of one source's claim into
apparent consensus that R23 and R41 are about.

All three are nullable with no server default and no backfill. Every existing
row keeps ``primary_position IS NULL``, which is true: nothing has ever
populated it. Writing a source string onto rows whose position is unknown would
assert provenance for a value that does not exist.

Additive columns only — no constraint, no index, no data migration — so this is
a plain ``add_column`` on both dialects rather than the batch rebuild 0002
needed.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "players",
        sa.Column("primary_position_source", sa.String(length=48), nullable=True),
    )
    op.add_column(
        "players",
        sa.Column("primary_position_season", sa.String(length=9), nullable=True),
    )
    op.add_column(
        "players",
        sa.Column("primary_position_observed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("players", "primary_position_observed_at")
    op.drop_column("players", "primary_position_season")
    op.drop_column("players", "primary_position_source")
