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

**There is deliberately no all-or-none CHECK constraint, and that is a reversal
made by executing rather than reasoning.** Review proposed one — the four
position columns are conceptually all-or-none, and ``projections``' volume-pair
CHECKs are the established precedent for making a bad state inexpressible. It
was implemented, and the existing migration suite went red: SQLite cannot add a
CHECK in place, so it requires ``batch_alter_table``, which rebuilds the table
by creating a copy, dropping the original and renaming. **Ten foreign keys point
into ``players`` and eight of them are ``ON DELETE CASCADE``** — including
``player_external_ids`` (the crosswalk itself), ``player_game_logs``,
``player_participation`` and ``projections``. Dropping the original table
cascades into all of them. ``test_absence_split_activation_migration_allows_
recurring_fingerprints`` caught it as one surviving row where it expected one,
and the same rebuild would have silently deleted a season of ingested data on
any real database.

So the invariant is held one level up instead, where it costs nothing:
``NbaPlayerPositionRecord.season`` is required with no default, and
``import_player_positions`` writes all four columns together or none. That is
weaker than a constraint, and **weaker than "only raw SQL could break it"** —
a plain ORM ``Player(primary_position="C")`` with no source, season or
observed-at is accepted, verified by execution. Nothing in the database
defends this; the importer and the required ``season`` are the whole guard.
The trade is recorded here rather than left as an unexplained absence. A
constraint would need a safe rebuild of the most-referenced table in the
schema, which is not a change to make in passing.

Additive columns only — no constraint, no index, no data migration — so this is
a plain ``add_column`` on both dialects rather than the batch rebuild 0002
needed, and it cannot touch a dependent row.

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
    # Bare drops, not batch mode, for the same cascade reason as the upgrade.
    # SQLite has supported DROP COLUMN since 3.35 (2021); this project requires
    # Python >= 3.12, whose bundled SQLite is far newer.
    op.drop_column("players", "primary_position_observed_at")
    op.drop_column("players", "primary_position_season")
    op.drop_column("players", "primary_position_source")
