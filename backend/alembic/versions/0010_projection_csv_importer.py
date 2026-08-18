"""Phase 5: csv-importer — projection import/normalisation/versioning boundary

Five new tables, no changes to existing ones, so this is a straightforward
``create_table`` migration rather than the batch-rebuild gymnastics 0002
needed for an in-place ALTER. Autogenerate handled it cleanly, the same as
0004.

``projection_sources`` / ``projection_profile_versions`` /
``projection_imports`` / ``projections`` /
``source_games_played_assumptions`` implement only the ``csv-importer``
backlog item: a versioned, idempotent import of per-game production rates,
with immutable profile recipes and each source's embedded games-played
assumption captured separately (ADR-002). Blending, the baseline model and
``expected-games`` fusion are later backlog items and are not part of this
revision.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projection_sources",
        sa.Column(
            "source",
            sa.Enum(
                "nba",
                "fantrax",
                "fantrax_stats_inc",
                "fantrax_rotowire",
                "fantrax_sportradar",
                "fantasypros",
                "hashtag",
                "basketball_monster",
                "darko",
                "manual",
                name="external_source",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('fantasypros', 'hashtag', 'basketball_monster', 'darko', 'manual')",
            name=op.f("ck_projection_sources_projection_provider_namespace"),
        ),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column(
            "assumed_scoring_type",
            sa.Enum(
                "h2h_categories",
                "h2h_points",
                "h2h_each_category",
                "roto",
                "points",
                name="scoring_type",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=True,
        ),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projection_sources")),
        sa.UniqueConstraint("source", name="uq_projection_sources_source"),
    )
    op.create_index(
        op.f("ix_projection_sources_source"), "projection_sources", ["source"], unique=False
    )

    op.create_table(
        "projection_profile_versions",
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.String(length=128), nullable=False),
        sa.Column("profile_version", sa.String(length=64), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("verified_seasons", sa.JSON(), nullable=False),
        sa.Column("verification_evidence", sa.Text(), nullable=False),
        sa.Column("definition_sha256", sa.String(length=64), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["projection_sources.id"],
            name=op.f("fk_projection_profile_versions_source_id_projection_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projection_profile_versions")),
        sa.UniqueConstraint(
            "source_id",
            "profile_id",
            "profile_version",
            name="uq_projection_profile_versions_identity",
        ),
    )
    op.create_index(
        op.f("ix_projection_profile_versions_definition_sha256"),
        "projection_profile_versions",
        ["definition_sha256"],
        unique=False,
    )
    op.create_index(
        op.f("ix_projection_profile_versions_source_id"),
        "projection_profile_versions",
        ["source_id"],
        unique=False,
    )

    op.create_table(
        "projection_imports",
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("profile_version_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.String(length=9), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("profile_id", sa.String(length=128), nullable=False),
        sa.Column("profile_version", sa.String(length=64), nullable=False),
        sa.Column("profile_verified", sa.Boolean(), nullable=False),
        sa.Column("profile_definition_sha256", sa.String(length=64), nullable=False),
        sa.Column("profile_lineage", sa.JSON(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("matched_count", sa.Integer(), nullable=False),
        sa.Column("needs_review_count", sa.Integer(), nullable=False),
        sa.Column("unmatched_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column(
            "assumed_scoring_type",
            sa.Enum(
                "h2h_categories",
                "h2h_points",
                "h2h_each_category",
                "roto",
                "points",
                name="scoring_type",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=True,
        ),
        sa.Column("raw_payload_ref", sa.String(length=255), nullable=True),
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
            "matched_count >= 0", name=op.f("ck_projection_imports_matched_count_non_negative")
        ),
        sa.CheckConstraint(
            "needs_review_count >= 0",
            name=op.f("ck_projection_imports_needs_review_count_non_negative"),
        ),
        sa.CheckConstraint(
            "rejected_count >= 0", name=op.f("ck_projection_imports_rejected_count_non_negative")
        ),
        sa.CheckConstraint(
            "row_count >= 0", name=op.f("ck_projection_imports_row_count_non_negative")
        ),
        sa.CheckConstraint(
            "unmatched_count >= 0",
            name=op.f("ck_projection_imports_unmatched_count_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_version_id"],
            ["projection_profile_versions.id"],
            name="fk_projection_imports_profile_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["projection_sources.id"],
            name=op.f("fk_projection_imports_source_id_projection_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projection_imports")),
        sa.UniqueConstraint(
            "source_id",
            "season",
            "content_sha256",
            "profile_version_id",
            name="uq_projection_imports_identity",
        ),
    )
    op.create_index(
        op.f("ix_projection_imports_content_sha256"),
        "projection_imports",
        ["content_sha256"],
        unique=False,
    )
    op.create_index(
        op.f("ix_projection_imports_profile_version_id"),
        "projection_imports",
        ["profile_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_projection_imports_season"), "projection_imports", ["season"], unique=False
    )
    op.create_index(
        op.f("ix_projection_imports_source_id"),
        "projection_imports",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_projection_imports_source_season",
        "projection_imports",
        ["source_id", "season"],
        unique=False,
    )

    op.create_table(
        "projections",
        sa.Column("projection_import_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.String(length=9), nullable=False),
        sa.Column("minutes_per_game", sa.Float(), nullable=True),
        sa.Column("points_per_game", sa.Float(), nullable=True),
        sa.Column("offensive_rebounds_per_game", sa.Float(), nullable=True),
        sa.Column("defensive_rebounds_per_game", sa.Float(), nullable=True),
        sa.Column("rebounds_per_game", sa.Float(), nullable=True),
        sa.Column("assists_per_game", sa.Float(), nullable=True),
        sa.Column("steals_per_game", sa.Float(), nullable=True),
        sa.Column("blocks_per_game", sa.Float(), nullable=True),
        sa.Column("turnovers_per_game", sa.Float(), nullable=True),
        sa.Column("personal_fouls_per_game", sa.Float(), nullable=True),
        sa.Column("field_goals_made_per_game", sa.Float(), nullable=True),
        sa.Column("field_goals_attempted_per_game", sa.Float(), nullable=True),
        sa.Column("three_pointers_made_per_game", sa.Float(), nullable=True),
        sa.Column("three_pointers_attempted_per_game", sa.Float(), nullable=True),
        sa.Column("free_throws_made_per_game", sa.Float(), nullable=True),
        sa.Column("free_throws_attempted_per_game", sa.Float(), nullable=True),
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
            "field_goals_made_per_game IS NULL OR field_goals_attempted_per_game IS NULL "
            "OR field_goals_made_per_game <= field_goals_attempted_per_game + 0.001",
            name=op.f("ck_projections_fg_made_within_attempted"),
        ),
        sa.CheckConstraint(
            "(field_goals_made_per_game IS NULL AND "
            "field_goals_attempted_per_game IS NULL) OR "
            "(field_goals_made_per_game IS NOT NULL AND "
            "field_goals_attempted_per_game IS NOT NULL)",
            name=op.f("ck_projections_fg_volume_pair_complete"),
        ),
        sa.CheckConstraint(
            "free_throws_made_per_game IS NULL OR free_throws_attempted_per_game IS NULL "
            "OR free_throws_made_per_game <= free_throws_attempted_per_game + 0.001",
            name=op.f("ck_projections_ft_made_within_attempted"),
        ),
        sa.CheckConstraint(
            "(free_throws_made_per_game IS NULL AND "
            "free_throws_attempted_per_game IS NULL) OR "
            "(free_throws_made_per_game IS NOT NULL AND "
            "free_throws_attempted_per_game IS NOT NULL)",
            name=op.f("ck_projections_ft_volume_pair_complete"),
        ),
        sa.CheckConstraint(
            "three_pointers_made_per_game IS NULL OR three_pointers_attempted_per_game IS NULL "
            "OR three_pointers_made_per_game <= three_pointers_attempted_per_game + 0.001",
            name=op.f("ck_projections_fg3_made_within_attempted"),
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name=op.f("fk_projections_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["projection_import_id"],
            ["projection_imports.id"],
            name=op.f("fk_projections_projection_import_id_projection_imports"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projections")),
        sa.UniqueConstraint(
            "projection_import_id", "player_id", name="uq_projections_import_player"
        ),
    )
    op.create_index(op.f("ix_projections_player_id"), "projections", ["player_id"], unique=False)
    op.create_index(
        "ix_projections_player_season", "projections", ["player_id", "season"], unique=False
    )
    op.create_index(
        op.f("ix_projections_projection_import_id"),
        "projections",
        ["projection_import_id"],
        unique=False,
    )
    op.create_index(op.f("ix_projections_season"), "projections", ["season"], unique=False)

    op.create_table(
        "source_games_played_assumptions",
        sa.Column("projection_id", sa.Integer(), nullable=False),
        sa.Column("assumed_games_played", sa.Float(), nullable=True),
        sa.Column("assumed_games_played_raw", sa.String(length=32), nullable=True),
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
            "assumed_games_played IS NULL "
            "OR (assumed_games_played >= 0 AND assumed_games_played <= 100)",
            name=op.f("ck_source_games_played_assumptions_assumed_games_played_range"),
        ),
        sa.ForeignKeyConstraint(
            ["projection_id"],
            ["projections.id"],
            name=op.f("fk_source_games_played_assumptions_projection_id_projections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_games_played_assumptions")),
        sa.UniqueConstraint("projection_id", name="uq_source_games_played_assumptions_projection"),
    )


def downgrade() -> None:
    op.drop_table("source_games_played_assumptions")

    op.drop_index(op.f("ix_projections_season"), table_name="projections")
    op.drop_index(op.f("ix_projections_projection_import_id"), table_name="projections")
    op.drop_index("ix_projections_player_season", table_name="projections")
    op.drop_index(op.f("ix_projections_player_id"), table_name="projections")
    op.drop_table("projections")

    op.drop_index("ix_projection_imports_source_season", table_name="projection_imports")
    op.drop_index(op.f("ix_projection_imports_source_id"), table_name="projection_imports")
    op.drop_index(op.f("ix_projection_imports_season"), table_name="projection_imports")
    op.drop_index(op.f("ix_projection_imports_profile_version_id"), table_name="projection_imports")
    op.drop_index(op.f("ix_projection_imports_content_sha256"), table_name="projection_imports")
    op.drop_table("projection_imports")

    op.drop_index(
        op.f("ix_projection_profile_versions_source_id"),
        table_name="projection_profile_versions",
    )
    op.drop_index(
        op.f("ix_projection_profile_versions_definition_sha256"),
        table_name="projection_profile_versions",
    )
    op.drop_table("projection_profile_versions")

    op.drop_index(op.f("ix_projection_sources_source"), table_name="projection_sources")
    op.drop_table("projection_sources")
