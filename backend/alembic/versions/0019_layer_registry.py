"""layer-purity: the ADR-008 layer registry, stored.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-25

ADR-008 / R41. Every stored quantity records which layer it belongs to. The
decision and its enforcement live in ``db/layers.py``, which refuses at import
to map a table with no layer or a foreign key running from a later layer into
an earlier one. This migration is the same fact **in the database**, so a
figure that looks wrong can be interrogated from a store alone.

The seeded rows are a **literal snapshot**, deliberately not read from
``TABLE_LAYERS``. A migration that imported the registry would silently follow
whatever the code says today, which would make the two representations one
representation wearing two hats and remove the only thing that forces a new
table's layer through review. ``test_layer_purity.py`` compares a migrated
store against ``TABLE_LAYERS`` and fails when they disagree, which is the
loudness this snapshot buys.

One new table, so every CHECK is inline in ``CREATE TABLE`` and no
``batch_alter_table`` is needed — ``gates.md`` records what happens when a
CHECK is added to an existing table on SQLite. Nothing here touches an existing
table, and the downgrade drops only what the upgrade created.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: ``(table_name, data_layer, layer_rank)`` as of this revision.
#:
#: ``market`` shares rank 4 with ``terminal`` on purpose: the flow rule refuses
#: cross-layer flow at equal rank, which is what makes an external aggregate
#: and our own rankings mutually unreachable in both directions. See the note
#: on ``LAYER_RANK`` in ``db/layers.py``.
_SEED: Sequence[tuple[str, str, int]] = (
    ("absence_split_runs", "observations", 0),
    ("absence_splits", "observations", 0),
    ("auction_value_imports", "market", 4),
    ("auction_value_source_inputs", "market", 4),
    ("auction_value_sources", "market", 4),
    ("bridge_payloads", "observations", 0),
    ("data_layer_registry", "observations", 0),
    ("draft_events", "observations", 0),
    ("draft_participants", "observations", 0),
    ("drafts", "observations", 0),
    ("fantasy_teams", "observations", 0),
    ("injury_report_entries", "observations", 0),
    ("league_deadline_calendars", "observations", 0),
    ("league_scoring_categories", "observations", 0),
    ("league_scoring_profiles", "observations", 0),
    ("league_settings_snapshots", "observations", 0),
    ("leagues", "observations", 0),
    ("matchup_category_results", "observations", 0),
    ("matchups", "observations", 0),
    ("nba_games", "observations", 0),
    ("nba_teams", "observations", 0),
    ("off_night_slates", "observations", 0),
    ("opponent_context", "observations", 0),
    ("player_external_ids", "observations", 0),
    ("player_game_logs", "observations", 0),
    ("player_participation", "observations", 0),
    ("player_season_stats", "observations", 0),
    ("players", "observations", 0),
    ("projection_imports", "projections", 1),
    ("projection_profile_versions", "projections", 1),
    ("projection_sources", "projections", 1),
    ("projections", "projections", 1),
    ("published_auction_values", "market", 4),
    ("refresh_runs", "observations", 0),
    ("roster_slots", "observations", 0),
    ("rosters", "observations", 0),
    ("scoring_periods", "observations", 0),
    ("source_games_played_assumptions", "projections", 1),
    ("team_schedule", "observations", 0),
    ("transactions", "observations", 0),
)


def upgrade() -> None:
    registry = op.create_table(
        "data_layer_registry",
        sa.Column("table_name", sa.String(length=64), nullable=False),
        sa.Column(
            "data_layer",
            sa.Enum(
                "observations",
                "projections",
                "availability",
                "valuation",
                "terminal",
                "market",
                "comparison",
                name="data_layer",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("layer_rank", sa.Integer(), nullable=False),
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
            "layer_rank >= 0", name=op.f("ck_data_layer_registry_layer_rank_non_negative")
        ),
        sa.CheckConstraint(
            "length(table_name) > 0", name=op.f("ck_data_layer_registry_table_name_not_empty")
        ),
        sa.PrimaryKeyConstraint("table_name", name=op.f("pk_data_layer_registry")),
    )

    # ``created_at``/``updated_at`` are left to their server defaults, which are
    # UTC on both dialects.
    op.bulk_insert(
        registry,
        [
            {"table_name": name, "data_layer": layer, "layer_rank": rank}
            for name, layer, rank in _SEED
        ],
    )


def downgrade() -> None:
    op.drop_table("data_layer_registry")
