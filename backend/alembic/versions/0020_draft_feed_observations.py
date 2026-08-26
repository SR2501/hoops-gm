"""draft-tracker-bridge-feed: what a machine read, kept apart from the log.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-26

One new table, ``draft_feed_observations``, plus its ``data_layer_registry``
row. Nothing existing is altered — every CHECK is inline in ``CREATE TABLE``,
which is what ``gates.md`` requires: adding a CHECK to an existing table forces
SQLite to rebuild it and cascade into its dependants, and ``draft_events``
already has dependants.

**Why the registry row is a new migration rather than an edit to 0019.** 0019's
``_SEED`` is a frozen historical snapshot. Once the owner's store is stamped at
0019 that migration never runs again, so editing its seed changes what a
*fresh* database gets and leaves the live one untouched — the wrong half, and
silently so. ``test_layer_purity.py`` compares a migrated store against
``TABLE_LAYERS`` and goes red without this row, which is the loudness that
catches the tempting route.

**The downgrade is real, not decorative.** It drops only what this revision
created and deletes only the row it inserted. This runs on the owner's machine
mid-season; a downgrade that half-works during a draft week is an outage.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: This revision's addition to the registry, written out rather than imported
#: from ``TABLE_LAYERS`` for the same reason 0019's ``_SEED`` is: a migration
#: that read the code would follow whatever the code says today and stop being
#: the independent record that forces a new table's layer through review.
_NEW_REGISTRY_ROWS: Sequence[tuple[str, str, int]] = (
    ("draft_feed_observations", "observations", 0),
)


def upgrade() -> None:
    op.create_table(
        "draft_feed_observations",
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column(
            "transport",
            sa.Enum(
                "bridge_capture",
                "official_http",
                name="draft_feed_transport",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("artifact_key", sa.String(length=128), nullable=False),
        sa.Column("locator", sa.String(length=128), nullable=False),
        sa.Column("recogniser", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bridge_payload_id", sa.Integer(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "selection",
                "sale",
                name="draft_feed_instant_kind",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("team_external_id", sa.String(length=64), nullable=True),
        sa.Column("participant_id", sa.Integer(), nullable=True),
        sa.Column("player_label", sa.String(length=128), nullable=True),
        sa.Column("player_external_id", sa.String(length=64), nullable=True),
        sa.Column("overall_pick", sa.Integer(), nullable=True),
        sa.Column("round_number", sa.Integer(), nullable=True),
        sa.Column("pick_in_round", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("applied_event_sequence", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skipped_reason", sa.Text(), nullable=True),
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
            "amount IS NULL OR amount > 0",
            name=op.f("ck_draft_feed_observations_feed_amount_positive"),
        ),
        sa.CheckConstraint(
            "artifact_key <> ''",
            name=op.f("ck_draft_feed_observations_feed_artifact_key_present"),
        ),
        sa.CheckConstraint(
            "(applied_event_sequence IS NULL) = (applied_at IS NULL)",
            name=op.f("ck_draft_feed_observations_feed_applied_fields_agree"),
        ),
        sa.CheckConstraint(
            "applied_event_sequence IS NULL OR applied_event_sequence >= 1",
            name=op.f("ck_draft_feed_observations_feed_applied_sequence_positive"),
        ),
        sa.CheckConstraint(
            "overall_pick IS NULL OR overall_pick >= 1",
            name=op.f("ck_draft_feed_observations_feed_overall_positive"),
        ),
        sa.CheckConstraint(
            "pick_in_round IS NULL OR pick_in_round >= 1",
            name=op.f("ck_draft_feed_observations_feed_pick_in_round_positive"),
        ),
        sa.CheckConstraint(
            "player_label IS NOT NULL OR player_external_id IS NOT NULL",
            name=op.f("ck_draft_feed_observations_feed_names_a_player"),
        ),
        sa.CheckConstraint(
            "round_number IS NULL OR round_number >= 1",
            name=op.f("ck_draft_feed_observations_feed_round_positive"),
        ),
        # A selection is a coordinate and a sale is a price. A row carrying
        # both is a record read under the wrong draft format.
        sa.CheckConstraint(
            "(kind = 'sale' AND overall_pick IS NULL AND round_number IS NULL"
            " AND pick_in_round IS NULL)"
            " OR (kind = 'selection' AND amount IS NULL)",
            name=op.f("ck_draft_feed_observations_feed_shape_matches_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["bridge_payload_id"],
            ["bridge_payloads.id"],
            name=op.f("fk_draft_feed_observations_bridge_payload_id_bridge_payloads"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["drafts.id"],
            name=op.f("fk_draft_feed_observations_draft_id_drafts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["draft_participants.id"],
            name=op.f("fk_draft_feed_observations_participant_id_draft_participants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draft_feed_observations")),
        sa.UniqueConstraint(
            "draft_id",
            "transport",
            "artifact_key",
            "locator",
            name=op.f("uq_draft_feed_observations_artifact_locator"),
        ),
    )
    with op.batch_alter_table("draft_feed_observations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_draft_feed_observations_artifact_key"), ["artifact_key"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_draft_feed_observations_bridge_payload_id"),
            ["bridge_payload_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_draft_feed_observations_draft_id"), ["draft_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_draft_feed_observations_observed_at"), ["observed_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_draft_feed_observations_participant_id"),
            ["participant_id"],
            unique=False,
        )

    registry = sa.table(
        "data_layer_registry",
        sa.column("table_name", sa.String),
        sa.column("data_layer", sa.String),
        sa.column("layer_rank", sa.Integer),
    )
    op.bulk_insert(
        registry,
        [
            {"table_name": name, "data_layer": layer, "layer_rank": rank}
            for name, layer, rank in _NEW_REGISTRY_ROWS
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM data_layer_registry WHERE table_name = :name").bindparams(
            name="draft_feed_observations"
        )
    )
    op.drop_table("draft_feed_observations")
