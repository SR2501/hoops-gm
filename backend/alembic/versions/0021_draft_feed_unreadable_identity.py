"""draft-feed-unreadable-id-surfacing: record the records we cannot identify.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-27

One CHECK is widened on ``draft_feed_observations``:
``feed_names_a_player`` gains ``OR skipped_reason IS NOT NULL``.

**What this permits, stated as narrowly as it is.** A row that names no player
is admitted *only* while it carries a ``skipped_reason``. The apply pass filters
``pending`` on ``skipped_reason IS NULL``, so such a row can never be an
application candidate, and the invariant the original CHECK was protecting —
anything that can become a ``draft_events`` entry names a player — is unchanged.
What changes is that a record whose ``player_external_id`` was present and
unreadable is now *recorded* rather than dropped.

**Why that is worth a migration.** Dropped, it was counted only in the ``POST``
ingest response's ``unrecognised``; ``GET /drafts/{id}/feed`` carries no such
field and a live board polls ``GET``. Driven at PR #104 head ``7a66d4e``, a
two-record capture produced one player on the board, ``pending 0 blocked ()
skipped ()`` and ``silent: False`` — a pick that happened, reported as nothing,
with every channel reading clean. That is the failure the owner named as
disqualifying. See ``draft-feed-unreadable-id-surfacing`` in ``docs/backlog.md``.

**Batch mode, and what that costs here.** Widening a CHECK on SQLite means
rebuilding the table, which ``0020``'s docstring flags as the reason its own
constraints were inline. The cost of a rebuild is that dependants must be
recreated; ``draft_feed_observations`` has none — nothing declares a foreign key
*to* it (its three FKs all point outward) — so the rebuild is contained to this
table and its five indexes, which ``batch_alter_table`` recreates from the
reflected schema. On Postgres this compiles to ``DROP CONSTRAINT`` /
``ADD CONSTRAINT`` and no rebuild happens at all.

**The downgrade is real, not decorative**, and it is the one direction that can
fail on data: rows written under the wider rule that name no player violate the
narrower one. They are deleted first, and only those — the ``WHERE`` names both
halves of the condition so a row naming a player is never touched. Deleting is
correct rather than destructive here: such a row records a refusal, carries no
claim about the draft, and is rewritten from the stored capture on the next
ingest.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "feed_names_a_player"

_NARROW = "player_label IS NOT NULL OR player_external_id IS NOT NULL"
_WIDE = f"{_NARROW} OR skipped_reason IS NOT NULL"


def upgrade() -> None:
    with op.batch_alter_table("draft_feed_observations", schema=None) as batch_op:
        # Bare names on both calls. The metadata naming convention expands them
        # to ``ck_draft_feed_observations_feed_names_a_player``, and passing the
        # expanded form gets it expanded a second time.
        batch_op.drop_constraint(_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(_CONSTRAINT, sa.text(_WIDE))


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM draft_feed_observations"
            " WHERE player_label IS NULL AND player_external_id IS NULL"
        )
    )
    with op.batch_alter_table("draft_feed_observations", schema=None) as batch_op:
        batch_op.drop_constraint(_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(_CONSTRAINT, sa.text(_NARROW))
