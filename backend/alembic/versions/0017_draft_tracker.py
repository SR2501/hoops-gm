"""draft-tracker: the recorded draft log

Three new tables, no change to any existing one, so this revision cannot touch
a row that already exists.

``drafts`` holds one draft's identity and the format it was recorded under.
``draft_participants`` holds the seats. ``draft_events`` is the log, and it is
the only fact: no current-state column exists anywhere in this revision.
Rosters, spend, the open lot and the next pick coordinate are derived by
:mod:`hoops_gm.draft.state` on every read. A stored summary beside the log
would be a second thing that can be wrong, and nothing would ever say which of
the two was.

**Why the CHECK constraints are affordable here and were not in 0016.** All
three tables are created *with* their constraints, so no table is rebuilt.
0016's reversal — a CHECK added to the existing ``players`` table forces
SQLite's ``batch_alter_table``, which rebuilds by copy/drop/rename and cascades
into ten foreign keys, eight of them ``ON DELETE CASCADE`` — applies to
altering a referenced table, not to creating a new one. Nothing points into
these tables yet.

**The format snapshot is four plain columns, not a join.** ``draft_type``,
``team_count``, ``roster_size`` and ``auction_budget`` are copied from the
format ``draft_format_from_league`` accepted at creation and are never updated.
Reading them off ``leagues`` instead would let an edit to the league row
silently rewrite what configuration a mock recorded weeks earlier was run
under; R39 says auction prices do not transfer between configurations, so that
edit would quietly make old prices uninterpretable while still displaying them.
``ck_drafts_auction_budget_matches_format`` makes a budget without an auction —
and an auction without a budget — inexpressible rather than merely discouraged.

**``sequence`` is the ordering and ``occurred_at`` is not.** ``occurred_at`` is
nullable, carries whatever the recorder claimed, and no index sorts on it.
``uq_draft_events_draft_sequence`` is what makes the log an ordering at all,
and it is also the concurrency mechanism: two writers computing the same next
sequence collide here and one is refused, so no lock is needed on any read
(ADR-014).

**Append-only is not enforced by this schema.** There is no trigger. A portable
one would need dialect-specific SQL, which ``test_portability.py`` forbids by
design, so the guarantee lives in the service being the only writer and the API
exposing no ``PUT``/``PATCH``/``DELETE`` on an event. The weaker claim is
written down here rather than left as an unexplained absence.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "drafts",
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
        sa.Column(
            "tool_usage",
            sa.Enum(
                "blind",
                "partial",
                "instrumented",
                name="draft_tool_usage",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column(
            "draft_type",
            sa.Enum(
                "snake",
                "auction",
                "linear",
                "unknown",
                name="draft_type",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("team_count", sa.Integer(), nullable=False),
        sa.Column("roster_size", sa.Integer(), nullable=False),
        sa.Column("auction_budget", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
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
        sa.CheckConstraint(
            "(draft_type = 'auction' AND auction_budget IS NOT NULL)"
            " OR (draft_type <> 'auction' AND auction_budget IS NULL)",
            name=op.f("ck_drafts_auction_budget_matches_format"),
        ),
        sa.CheckConstraint("draft_type <> 'unknown'", name=op.f("ck_drafts_draft_type_known")),
        sa.CheckConstraint(
            "auction_budget IS NULL OR auction_budget > 0",
            name=op.f("ck_drafts_budget_positive"),
        ),
        sa.CheckConstraint("roster_size >= 1", name=op.f("ck_drafts_roster_size_positive")),
        sa.CheckConstraint("team_count >= 1", name=op.f("ck_drafts_team_count_positive")),
        sa.ForeignKeyConstraint(
            ["league_id"],
            ["leagues.id"],
            name=op.f("fk_drafts_league_id_leagues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drafts")),
    )
    with op.batch_alter_table("drafts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_drafts_is_mock"), ["is_mock"], unique=False)
        batch_op.create_index(batch_op.f("ix_drafts_league_id"), ["league_id"], unique=False)

    op.create_table(
        "draft_participants",
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("team_slot", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("owner_draft_id", sa.Integer(), nullable=True),
        sa.Column("fantasy_team_id", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
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
        # The nullable-sentinel pattern `league_scoring_profiles.active_league_id`
        # already uses: `owner_draft_id` mirrors `draft_id` for the owner's seat
        # and is NULL for everyone else, so the unique constraint below makes
        # "at most one owner seat per draft" a database guarantee.
        sa.CheckConstraint(
            "owner_draft_id IS NULL OR owner_draft_id = draft_id",
            name=op.f("ck_draft_participants_owner_sentinel_matches_draft"),
        ),
        sa.CheckConstraint("team_slot >= 1", name=op.f("ck_draft_participants_team_slot_positive")),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["drafts.id"],
            name=op.f("fk_draft_participants_draft_id_drafts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["fantasy_team_id"],
            ["fantasy_teams.id"],
            name=op.f("fk_draft_participants_fantasy_team_id_fantasy_teams"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_draft_id"],
            ["drafts.id"],
            name=op.f("fk_draft_participants_owner_draft_id_drafts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draft_participants")),
        sa.UniqueConstraint("draft_id", "team_slot", name="uq_draft_participants_draft_slot"),
        sa.UniqueConstraint("owner_draft_id", name="uq_draft_participants_owner_draft_id"),
    )
    with op.batch_alter_table("draft_participants", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_draft_participants_draft_id"), ["draft_id"], unique=False
        )

    op.create_table(
        "draft_events",
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "pick",
                "nomination",
                "bid",
                "sale",
                "void",
                "closed",
                name="draft_event_type",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("participant_id", sa.Integer(), nullable=True),
        sa.Column("player_id", sa.Integer(), nullable=True),
        sa.Column("player_label", sa.String(length=128), nullable=True),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("supersedes_sequence", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
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
        # One CHECK per event type, OR-ed. This is what stops a half-formed
        # event reaching the log through a path that is not the service: a bid
        # with no amount, a sale with no buyer, a void that also drafts someone.
        sa.CheckConstraint(
            "(event_type = 'pick' AND participant_id IS NOT NULL AND player_label IS NOT NULL"
            " AND amount IS NULL AND supersedes_sequence IS NULL)"
            " OR (event_type = 'nomination' AND participant_id IS NOT NULL"
            " AND player_label IS NOT NULL AND supersedes_sequence IS NULL)"
            " OR (event_type = 'bid' AND participant_id IS NOT NULL AND player_id IS NULL"
            " AND player_label IS NULL AND amount IS NOT NULL AND supersedes_sequence IS NULL)"
            " OR (event_type = 'sale' AND participant_id IS NOT NULL AND amount IS NOT NULL"
            " AND supersedes_sequence IS NULL)"
            " OR (event_type = 'void' AND supersedes_sequence IS NOT NULL"
            " AND participant_id IS NULL AND player_id IS NULL AND player_label IS NULL"
            " AND amount IS NULL)"
            " OR (event_type = 'closed' AND participant_id IS NULL AND player_id IS NULL"
            " AND player_label IS NULL AND amount IS NULL AND supersedes_sequence IS NULL)",
            name=op.f("ck_draft_events_event_shape_matches_type"),
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount > 0", name=op.f("ck_draft_events_amount_positive")
        ),
        # Keeping the resolution while discarding the raw name is what makes a
        # recorded pick unauditable, so it is made impossible rather than
        # discouraged.
        sa.CheckConstraint(
            "player_id IS NULL OR player_label IS NOT NULL",
            name=op.f("ck_draft_events_player_id_requires_label"),
        ),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_draft_events_sequence_positive")),
        sa.CheckConstraint(
            "supersedes_sequence IS NULL OR supersedes_sequence < sequence",
            name=op.f("ck_draft_events_supersedes_points_backwards"),
        ),
        sa.CheckConstraint(
            "supersedes_sequence IS NULL OR supersedes_sequence >= 1",
            name=op.f("ck_draft_events_supersedes_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["drafts.id"],
            name=op.f("fk_draft_events_draft_id_drafts"),
            ondelete="CASCADE",
        ),
        # RESTRICT, not CASCADE: a seat that has recorded events cannot be
        # removed out from under them. Deleting the draft still removes both.
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["draft_participants.id"],
            name=op.f("fk_draft_events_participant_id_draft_participants"),
            ondelete="RESTRICT",
        ),
        # SET NULL, not CASCADE: if a player row goes, the recorded name and the
        # price paid survive. The event is the evidence, not the player.
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name=op.f("fk_draft_events_player_id_players"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draft_events")),
        sa.UniqueConstraint("draft_id", "sequence", name="uq_draft_events_draft_sequence"),
    )
    with op.batch_alter_table("draft_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_draft_events_draft_id"), ["draft_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_draft_events_participant_id"), ["participant_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_draft_events_player_id"), ["player_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("draft_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_draft_events_player_id"))
        batch_op.drop_index(batch_op.f("ix_draft_events_participant_id"))
        batch_op.drop_index(batch_op.f("ix_draft_events_draft_id"))

    op.drop_table("draft_events")
    with op.batch_alter_table("draft_participants", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_draft_participants_draft_id"))

    op.drop_table("draft_participants")
    with op.batch_alter_table("drafts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_drafts_league_id"))
        batch_op.drop_index(batch_op.f("ix_drafts_is_mock"))

    op.drop_table("drafts")
