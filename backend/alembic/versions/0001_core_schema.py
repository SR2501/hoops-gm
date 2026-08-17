"""core schema: identity, stats, league, schedule

The first migration. Creates the four entity groups Phase 1 owns:

* **Identity** — ``nba_teams``, ``players``, ``player_external_ids``
* **Stats** — ``nba_games``, ``player_game_logs``, ``player_season_stats``
* **League** — ``leagues``, ``league_scoring_profiles``,
  ``league_scoring_categories``, ``fantasy_teams``, ``roster_slots``,
  ``rosters``, ``scoring_periods``, ``matchups``,
  ``matchup_category_results``, ``transactions``
* **Schedule** — ``team_schedule``

The Availability, Contingent value, Projections, Valuation, Draft, Decisions
and Bridge groups are deliberately absent; they belong to later phases and
their owning agents.

Enums render as VARCHAR **plus a CHECK constraint** — note the
``create_constraint=True`` on every ``sa.Enum`` below. It is not decoration.
That argument defaults to ``False``, and the first version of this migration
omitted it, so the schema had 18 enum columns and no enum CHECKs at all while
three docstrings claimed the opposite. An unknown value inserted cleanly
through any path that bypassed the ORM, and adding an enum member required no
migration because there was no constraint to widen.

Timestamps are plain ``sa.DateTime(timezone=True)`` here rather than the
application's ``UTCDateTime``. The two produce identical DDL; ``UTCDateTime``
only adds bind and result behaviour. Keeping application classes out of
migrations means renaming one cannot break the ability to migrate an old
database.

This migration was regenerated rather than followed by a corrective one. It
had not been merged or applied anywhere, and a second migration performing a
SQLite batch table-rebuild would have been permanent complexity in the history
of a schema that was never released. Anyone holding a database created by the
earlier version must drop it and re-run; there is no data to preserve.

Revision ID: 0001
Revises:
Create Date: 2026-08-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "leagues",
        sa.Column("fantrax_league_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("season", sa.String(length=9), nullable=False),
        sa.Column(
            "scoring_type",
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
        sa.Column("team_count", sa.Integer(), nullable=True),
        sa.Column("roster_size", sa.Integer(), nullable=True),
        sa.Column("auction_budget", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leagues")),
        sa.UniqueConstraint("fantrax_league_id", "season", name="uq_leagues_fantrax_season"),
    )
    with op.batch_alter_table("leagues", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_leagues_fantrax_league_id"), ["fantrax_league_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_leagues_season"), ["season"], unique=False)

    op.create_table(
        "nba_teams",
        sa.Column("nba_team_id", sa.Integer(), nullable=False),
        sa.Column("abbreviation", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("city", sa.String(length=64), nullable=True),
        sa.Column(
            "conference",
            sa.Enum(
                "East",
                "West",
                name="conference",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=True,
        ),
        sa.Column("division", sa.String(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nba_teams")),
    )
    with op.batch_alter_table("nba_teams", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_nba_teams_abbreviation"), ["abbreviation"], unique=True
        )
        batch_op.create_index(batch_op.f("ix_nba_teams_nba_team_id"), ["nba_team_id"], unique=True)

    op.create_table(
        "fantasy_teams",
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("fantrax_team_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("short_name", sa.String(length=32), nullable=True),
        sa.Column("owner_name", sa.String(length=128), nullable=True),
        sa.Column("is_owner_team", sa.Boolean(), nullable=False),
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
            ["league_id"],
            ["leagues.id"],
            name=op.f("fk_fantasy_teams_league_id_leagues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fantasy_teams")),
        sa.UniqueConstraint("league_id", "fantrax_team_id", name="uq_fantasy_teams_fantrax"),
    )
    with op.batch_alter_table("fantasy_teams", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_fantasy_teams_is_owner_team"), ["is_owner_team"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_fantasy_teams_league_id"), ["league_id"], unique=False)

    op.create_table(
        "league_scoring_profiles",
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "scoring_type",
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
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
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
            "version >= 1", name=op.f("ck_league_scoring_profiles_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["league_id"],
            ["leagues.id"],
            name=op.f("fk_league_scoring_profiles_league_id_leagues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_league_scoring_profiles")),
        sa.UniqueConstraint("league_id", "name", "version", name="uq_league_scoring_profiles_ver"),
    )
    with op.batch_alter_table("league_scoring_profiles", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_league_scoring_profiles_is_active"), ["is_active"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_league_scoring_profiles_league_id"), ["league_id"], unique=False
        )

    op.create_table(
        "nba_games",
        sa.Column("season", sa.String(length=9), nullable=False),
        sa.Column(
            "season_type",
            sa.Enum(
                "preseason",
                "regular",
                "play_in",
                "playoffs",
                name="season_type",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("nba_game_id", sa.String(length=32), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("tipoff_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "scheduled",
                "live",
                "final",
                "postponed",
                "cancelled",
                name="game_status",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("home_team_id", sa.Integer(), nullable=False),
        sa.Column("away_team_id", sa.Integer(), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
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
            "home_team_id <> away_team_id", name=op.f("ck_nba_games_distinct_teams")
        ),
        sa.ForeignKeyConstraint(
            ["away_team_id"], ["nba_teams.id"], name=op.f("fk_nba_games_away_team_id_nba_teams")
        ),
        sa.ForeignKeyConstraint(
            ["home_team_id"], ["nba_teams.id"], name=op.f("fk_nba_games_home_team_id_nba_teams")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nba_games")),
    )
    with op.batch_alter_table("nba_games", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_nba_games_away_team_id"), ["away_team_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_nba_games_game_date"), ["game_date"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_nba_games_home_team_id"), ["home_team_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_nba_games_nba_game_id"), ["nba_game_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_nba_games_season"), ["season"], unique=False)
        batch_op.create_index("ix_nba_games_season_date", ["season", "game_date"], unique=False)

    op.create_table(
        "players",
        sa.Column("full_name", sa.String(length=128), nullable=False),
        sa.Column("normalized_name", sa.String(length=128), nullable=False),
        sa.Column("first_name", sa.String(length=64), nullable=True),
        sa.Column("last_name", sa.String(length=64), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("height_inches", sa.Integer(), nullable=True),
        sa.Column("weight_pounds", sa.Integer(), nullable=True),
        sa.Column("primary_position", sa.String(length=16), nullable=True),
        sa.Column("rookie_season", sa.String(length=9), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "inactive",
                "two_way",
                "g_league",
                "retired",
                "unknown",
                name="player_status",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("current_team_id", sa.Integer(), nullable=True),
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
            ["current_team_id"],
            ["nba_teams.id"],
            name=op.f("fk_players_current_team_id_nba_teams"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_players")),
    )
    with op.batch_alter_table("players", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_players_current_team_id"), ["current_team_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_players_full_name"), ["full_name"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_players_normalized_name"), ["normalized_name"], unique=False
        )

    op.create_table(
        "roster_slots",
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=48), nullable=True),
        sa.Column("slot_count", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("is_starting", sa.Boolean(), nullable=False),
        sa.Column("is_injury_reserve", sa.Boolean(), nullable=False),
        sa.Column("eligible_positions", sa.String(length=64), nullable=True),
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
        sa.CheckConstraint("slot_count >= 0", name=op.f("ck_roster_slots_slot_count_non_negative")),
        sa.ForeignKeyConstraint(
            ["league_id"],
            ["leagues.id"],
            name=op.f("fk_roster_slots_league_id_leagues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roster_slots")),
        sa.UniqueConstraint("league_id", "code", name="uq_roster_slots_code"),
    )
    with op.batch_alter_table("roster_slots", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_roster_slots_league_id"), ["league_id"], unique=False)

    op.create_table(
        "scoring_periods",
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("period_number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=48), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_playoff", sa.Boolean(), nullable=False),
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
            "end_date >= start_date", name=op.f("ck_scoring_periods_period_dates_ordered")
        ),
        sa.ForeignKeyConstraint(
            ["league_id"],
            ["leagues.id"],
            name=op.f("fk_scoring_periods_league_id_leagues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scoring_periods")),
        sa.UniqueConstraint("league_id", "period_number", name="uq_scoring_periods_number"),
    )
    with op.batch_alter_table("scoring_periods", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_scoring_periods_is_playoff"), ["is_playoff"], unique=False
        )
        batch_op.create_index(
            "ix_scoring_periods_league_dates", ["league_id", "start_date", "end_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_scoring_periods_league_id"), ["league_id"], unique=False
        )

    op.create_table(
        "league_scoring_categories",
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=48), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "counting",
                "ratio",
                name="category_kind",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("direction", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("point_value", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("numerator_stat", sa.String(length=32), nullable=True),
        sa.Column("denominator_stat", sa.String(length=32), nullable=True),
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
            "(kind = 'counting' AND numerator_stat IS NULL AND denominator_stat IS NULL) OR (kind = 'ratio' AND numerator_stat IS NOT NULL AND denominator_stat IS NOT NULL)",
            name=op.f("ck_league_scoring_categories_ratio_components_present"),
        ),
        sa.CheckConstraint(
            "denominator_stat IS NULL OR denominator_stat IN ('assists', 'blocks', 'defensive_rebounds', 'field_goals_attempted', 'field_goals_made', 'free_throws_attempted', 'free_throws_made', 'offensive_rebounds', 'personal_fouls', 'plus_minus', 'points', 'rebounds', 'seconds_played', 'steals', 'three_pointers_attempted', 'three_pointers_made', 'turnovers')",
            name=op.f("ck_league_scoring_categories_denominator_in_vocabulary"),
        ),
        sa.CheckConstraint(
            "key NOT IN ('fg_pct', 'ft_pct', 'fg3_pct', 'ts_pct', 'efg_pct') OR kind = 'ratio'",
            name=op.f("ck_league_scoring_categories_percentage_keys_are_ratios"),
        ),
        sa.CheckConstraint(
            "numerator_stat IS NULL OR numerator_stat IN ('assists', 'blocks', 'defensive_rebounds', 'field_goals_attempted', 'field_goals_made', 'free_throws_attempted', 'free_throws_made', 'offensive_rebounds', 'personal_fouls', 'plus_minus', 'points', 'rebounds', 'seconds_played', 'steals', 'three_pointers_attempted', 'three_pointers_made', 'turnovers')",
            name=op.f("ck_league_scoring_categories_numerator_in_vocabulary"),
        ),
        sa.CheckConstraint(
            "direction IN (-1, 1)", name=op.f("ck_league_scoring_categories_direction_sign")
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["league_scoring_profiles.id"],
            name=op.f("fk_league_scoring_categories_profile_id_league_scoring_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_league_scoring_categories")),
        sa.UniqueConstraint("profile_id", "key", name="uq_league_scoring_categories_key"),
    )
    with op.batch_alter_table("league_scoring_categories", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_league_scoring_categories_profile_id"), ["profile_id"], unique=False
        )

    op.create_table(
        "matchups",
        sa.Column("scoring_period_id", sa.Integer(), nullable=False),
        sa.Column("home_team_id", sa.Integer(), nullable=False),
        sa.Column("away_team_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "scheduled",
                "in_progress",
                "final",
                name="matchup_status",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("home_category_wins", sa.Integer(), nullable=True),
        sa.Column("away_category_wins", sa.Integer(), nullable=True),
        sa.Column("category_ties", sa.Integer(), nullable=True),
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
            "home_team_id <> away_team_id", name=op.f("ck_matchups_distinct_fantasy_teams")
        ),
        sa.ForeignKeyConstraint(
            ["away_team_id"],
            ["fantasy_teams.id"],
            name=op.f("fk_matchups_away_team_id_fantasy_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["home_team_id"],
            ["fantasy_teams.id"],
            name=op.f("fk_matchups_home_team_id_fantasy_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scoring_period_id"],
            ["scoring_periods.id"],
            name=op.f("fk_matchups_scoring_period_id_scoring_periods"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_matchups")),
        sa.UniqueConstraint("scoring_period_id", "home_team_id", name="uq_matchups_period_home"),
    )
    with op.batch_alter_table("matchups", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_matchups_away_team_id"), ["away_team_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_matchups_home_team_id"), ["home_team_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_matchups_scoring_period_id"), ["scoring_period_id"], unique=False
        )

    op.create_table(
        "player_external_ids",
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "nba",
                "fantrax",
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
        sa.Column("current_for_source", sa.String(length=48), nullable=True),
        sa.Column("source_detail", sa.String(length=64), nullable=True),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("external_name", sa.String(length=128), nullable=True),
        sa.Column("normalized_name", sa.String(length=128), nullable=True),
        sa.Column("external_team", sa.String(length=16), nullable=True),
        sa.Column("external_position", sa.String(length=16), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "match_method",
            sa.Enum(
                "anchor_id",
                "exact_name",
                "normalized_name",
                "name_team_position",
                "fuzzy",
                "manual_override",
                name="match_method",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("is_manual_override", sa.Boolean(), nullable=False),
        sa.Column("reviewed_at", sa.Date(), nullable=True),
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
            "confidence >= 0.0 AND confidence <= 1.0",
            name=op.f("ck_player_external_ids_confidence_range"),
        ),
        sa.CheckConstraint(
            "current_for_source IS NULL OR current_for_source = source",
            name=op.f("ck_player_external_ids_current_marker_matches_source"),
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name=op.f("fk_player_external_ids_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player_external_ids")),
        sa.UniqueConstraint(
            "player_id", "current_for_source", name="uq_player_external_ids_current"
        ),
        sa.UniqueConstraint("source", "external_id", name="uq_player_external_ids_source_ext"),
    )
    with op.batch_alter_table("player_external_ids", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_player_external_ids_is_manual_override"),
            ["is_manual_override"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_player_external_ids_player_id"), ["player_id"], unique=False
        )
        batch_op.create_index(
            "ix_player_external_ids_player_source", ["player_id", "source"], unique=False
        )
        batch_op.create_index(
            "ix_player_external_ids_source_norm_name", ["source", "normalized_name"], unique=False
        )

    op.create_table(
        "player_game_logs",
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("started", sa.Boolean(), nullable=True),
        sa.Column("seconds_played", sa.Integer(), nullable=True),
        sa.Column("field_goals_made", sa.Integer(), nullable=True),
        sa.Column("field_goals_attempted", sa.Integer(), nullable=True),
        sa.Column("three_pointers_made", sa.Integer(), nullable=True),
        sa.Column("three_pointers_attempted", sa.Integer(), nullable=True),
        sa.Column("free_throws_made", sa.Integer(), nullable=True),
        sa.Column("free_throws_attempted", sa.Integer(), nullable=True),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.Column("offensive_rebounds", sa.Integer(), nullable=True),
        sa.Column("defensive_rebounds", sa.Integer(), nullable=True),
        sa.Column("rebounds", sa.Integer(), nullable=True),
        sa.Column("assists", sa.Integer(), nullable=True),
        sa.Column("steals", sa.Integer(), nullable=True),
        sa.Column("blocks", sa.Integer(), nullable=True),
        sa.Column("turnovers", sa.Integer(), nullable=True),
        sa.Column("personal_fouls", sa.Integer(), nullable=True),
        sa.Column("plus_minus", sa.Integer(), nullable=True),
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
            ["game_id"],
            ["nba_games.id"],
            name=op.f("fk_player_game_logs_game_id_nba_games"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name=op.f("fk_player_game_logs_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["nba_teams.id"], name=op.f("fk_player_game_logs_team_id_nba_teams")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player_game_logs")),
        sa.UniqueConstraint("player_id", "game_id", name="uq_player_game_logs_player_game"),
    )
    with op.batch_alter_table("player_game_logs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_player_game_logs_game_id"), ["game_id"], unique=False)
        batch_op.create_index("ix_player_game_logs_game_team", ["game_id", "team_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_player_game_logs_player_id"), ["player_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_player_game_logs_team_id"), ["team_id"], unique=False)

    op.create_table(
        "player_season_stats",
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.String(length=9), nullable=False),
        sa.Column(
            "season_type",
            sa.Enum(
                "preseason",
                "regular",
                "play_in",
                "playoffs",
                name="season_type",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column(
            "scope",
            sa.Enum(
                "team",
                "total",
                name="stat_scope",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("team_key", sa.String(length=8), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("games_played", sa.Integer(), nullable=True),
        sa.Column("games_started", sa.Integer(), nullable=True),
        sa.Column("team_games", sa.Integer(), nullable=True),
        sa.Column("seconds_played", sa.Integer(), nullable=True),
        sa.Column("field_goals_made", sa.Integer(), nullable=True),
        sa.Column("field_goals_attempted", sa.Integer(), nullable=True),
        sa.Column("three_pointers_made", sa.Integer(), nullable=True),
        sa.Column("three_pointers_attempted", sa.Integer(), nullable=True),
        sa.Column("free_throws_made", sa.Integer(), nullable=True),
        sa.Column("free_throws_attempted", sa.Integer(), nullable=True),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.Column("offensive_rebounds", sa.Integer(), nullable=True),
        sa.Column("defensive_rebounds", sa.Integer(), nullable=True),
        sa.Column("rebounds", sa.Integer(), nullable=True),
        sa.Column("assists", sa.Integer(), nullable=True),
        sa.Column("steals", sa.Integer(), nullable=True),
        sa.Column("blocks", sa.Integer(), nullable=True),
        sa.Column("turnovers", sa.Integer(), nullable=True),
        sa.Column("personal_fouls", sa.Integer(), nullable=True),
        sa.Column("plus_minus", sa.Integer(), nullable=True),
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
            "(scope = 'team' AND team_id IS NOT NULL AND team_key <> 'TOT') OR (scope = 'total' AND team_id IS NULL AND team_key = 'TOT')",
            name=op.f("ck_player_season_stats_scope_team_consistency"),
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name=op.f("fk_player_season_stats_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["nba_teams.id"], name=op.f("fk_player_season_stats_team_id_nba_teams")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player_season_stats")),
        sa.UniqueConstraint(
            "player_id", "season", "season_type", "team_key", name="uq_player_season_stats_identity"
        ),
    )
    with op.batch_alter_table("player_season_stats", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_player_season_stats_player_id"), ["player_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_player_season_stats_season"), ["season"], unique=False)
        batch_op.create_index(
            "ix_player_season_stats_season_scope", ["season", "scope"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_player_season_stats_team_id"), ["team_id"], unique=False
        )

    op.create_table(
        "rosters",
        sa.Column("fantasy_team_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("slot_code", sa.String(length=16), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "reserve",
                "injured_reserve",
                "minors",
                name="roster_status",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("acquired_on", sa.Date(), nullable=True),
        sa.Column("salary", sa.Numeric(precision=10, scale=2), nullable=True),
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
            ["fantasy_team_id"],
            ["fantasy_teams.id"],
            name=op.f("fk_rosters_fantasy_team_id_fantasy_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name=op.f("fk_rosters_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rosters")),
        sa.UniqueConstraint("fantasy_team_id", "player_id", name="uq_rosters_team_player"),
    )
    with op.batch_alter_table("rosters", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_rosters_fantasy_team_id"), ["fantasy_team_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_rosters_player_id"), ["player_id"], unique=False)
        batch_op.create_index("ix_rosters_player_status", ["player_id", "status"], unique=False)

    op.create_table(
        "team_schedule",
        sa.Column("season", sa.String(length=9), nullable=False),
        sa.Column(
            "season_type",
            sa.Enum(
                "preseason",
                "regular",
                "play_in",
                "playoffs",
                name="season_type",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("opponent_team_id", sa.Integer(), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("is_home", sa.Boolean(), nullable=False),
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
            "team_id <> opponent_team_id", name=op.f("ck_team_schedule_distinct_schedule_teams")
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["nba_games.id"],
            name=op.f("fk_team_schedule_game_id_nba_games"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["opponent_team_id"],
            ["nba_teams.id"],
            name=op.f("fk_team_schedule_opponent_team_id_nba_teams"),
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["nba_teams.id"], name=op.f("fk_team_schedule_team_id_nba_teams")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_schedule")),
        sa.UniqueConstraint("game_id", "team_id", name="uq_team_schedule_game_team"),
    )
    with op.batch_alter_table("team_schedule", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_team_schedule_game_date"), ["game_date"], unique=False)
        batch_op.create_index(batch_op.f("ix_team_schedule_game_id"), ["game_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_team_schedule_opponent_team_id"), ["opponent_team_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_team_schedule_season"), ["season"], unique=False)
        batch_op.create_index("ix_team_schedule_season_date", ["season", "game_date"], unique=False)
        batch_op.create_index("ix_team_schedule_team_date", ["team_id", "game_date"], unique=False)
        batch_op.create_index(batch_op.f("ix_team_schedule_team_id"), ["team_id"], unique=False)

    op.create_table(
        "transactions",
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("fantrax_transaction_id", sa.String(length=64), nullable=True),
        sa.Column("group_key", sa.String(length=64), nullable=True),
        sa.Column(
            "transaction_type",
            sa.Enum(
                "add",
                "drop",
                "waiver_claim",
                "trade",
                "draft",
                "ir_move",
                "other",
                name="transaction_type",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=True),
        sa.Column("from_team_id", sa.Integer(), nullable=True),
        sa.Column("to_team_id", sa.Integer(), nullable=True),
        sa.Column("bid_amount", sa.Numeric(precision=10, scale=2), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["from_team_id"],
            ["fantasy_teams.id"],
            name=op.f("fk_transactions_from_team_id_fantasy_teams"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["league_id"],
            ["leagues.id"],
            name=op.f("fk_transactions_league_id_leagues"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name=op.f("fk_transactions_player_id_players"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["to_team_id"],
            ["fantasy_teams.id"],
            name=op.f("fk_transactions_to_team_id_fantasy_teams"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
        sa.UniqueConstraint(
            "league_id", "fantrax_transaction_id", name="uq_transactions_fantrax_id"
        ),
    )
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.create_index("ix_transactions_group", ["league_id", "group_key"], unique=False)
        batch_op.create_index(
            "ix_transactions_league_date", ["league_id", "occurred_on"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_transactions_league_id"), ["league_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_transactions_occurred_on"), ["occurred_on"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_transactions_player_id"), ["player_id"], unique=False)

    op.create_table(
        "matchup_category_results",
        sa.Column("matchup_id", sa.Integer(), nullable=False),
        sa.Column("category_key", sa.String(length=32), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "counting",
                "ratio",
                name="category_kind",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("home_value", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("away_value", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("home_numerator", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("home_denominator", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("away_numerator", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("away_denominator", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                "home",
                "away",
                "tie",
                name="category_outcome",
                native_enum=False,
                create_constraint=True,
                length=48,
            ),
            nullable=True,
        ),
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
            "category_key NOT IN ('fg_pct', 'ft_pct', 'fg3_pct', 'ts_pct', 'efg_pct') OR kind = 'ratio'",
            name=op.f("ck_matchup_category_results_percentage_keys_are_ratios"),
        ),
        sa.CheckConstraint(
            "kind = 'counting' OR (home_numerator IS NOT NULL AND home_denominator IS NOT NULL AND away_numerator IS NOT NULL AND away_denominator IS NOT NULL)",
            name=op.f("ck_matchup_category_results_ratio_components_present"),
        ),
        sa.ForeignKeyConstraint(
            ["matchup_id"],
            ["matchups.id"],
            name=op.f("fk_matchup_category_results_matchup_id_matchups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_matchup_category_results")),
        sa.UniqueConstraint("matchup_id", "category_key", name="uq_matchup_cat_results_key"),
    )
    with op.batch_alter_table("matchup_category_results", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_matchup_category_results_matchup_id"), ["matchup_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("matchup_category_results", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_matchup_category_results_matchup_id"))

    op.drop_table("matchup_category_results")
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_transactions_player_id"))
        batch_op.drop_index(batch_op.f("ix_transactions_occurred_on"))
        batch_op.drop_index(batch_op.f("ix_transactions_league_id"))
        batch_op.drop_index("ix_transactions_league_date")
        batch_op.drop_index("ix_transactions_group")

    op.drop_table("transactions")
    with op.batch_alter_table("team_schedule", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_team_schedule_team_id"))
        batch_op.drop_index("ix_team_schedule_team_date")
        batch_op.drop_index("ix_team_schedule_season_date")
        batch_op.drop_index(batch_op.f("ix_team_schedule_season"))
        batch_op.drop_index(batch_op.f("ix_team_schedule_opponent_team_id"))
        batch_op.drop_index(batch_op.f("ix_team_schedule_game_id"))
        batch_op.drop_index(batch_op.f("ix_team_schedule_game_date"))

    op.drop_table("team_schedule")
    with op.batch_alter_table("rosters", schema=None) as batch_op:
        batch_op.drop_index("ix_rosters_player_status")
        batch_op.drop_index(batch_op.f("ix_rosters_player_id"))
        batch_op.drop_index(batch_op.f("ix_rosters_fantasy_team_id"))

    op.drop_table("rosters")
    with op.batch_alter_table("player_season_stats", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_player_season_stats_team_id"))
        batch_op.drop_index("ix_player_season_stats_season_scope")
        batch_op.drop_index(batch_op.f("ix_player_season_stats_season"))
        batch_op.drop_index(batch_op.f("ix_player_season_stats_player_id"))

    op.drop_table("player_season_stats")
    with op.batch_alter_table("player_game_logs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_player_game_logs_team_id"))
        batch_op.drop_index(batch_op.f("ix_player_game_logs_player_id"))
        batch_op.drop_index("ix_player_game_logs_game_team")
        batch_op.drop_index(batch_op.f("ix_player_game_logs_game_id"))

    op.drop_table("player_game_logs")
    with op.batch_alter_table("player_external_ids", schema=None) as batch_op:
        batch_op.drop_index("ix_player_external_ids_source_norm_name")
        batch_op.drop_index("ix_player_external_ids_player_source")
        batch_op.drop_index(batch_op.f("ix_player_external_ids_player_id"))
        batch_op.drop_index(batch_op.f("ix_player_external_ids_is_manual_override"))

    op.drop_table("player_external_ids")
    with op.batch_alter_table("matchups", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_matchups_scoring_period_id"))
        batch_op.drop_index(batch_op.f("ix_matchups_home_team_id"))
        batch_op.drop_index(batch_op.f("ix_matchups_away_team_id"))

    op.drop_table("matchups")
    with op.batch_alter_table("league_scoring_categories", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_league_scoring_categories_profile_id"))

    op.drop_table("league_scoring_categories")
    with op.batch_alter_table("scoring_periods", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_scoring_periods_league_id"))
        batch_op.drop_index("ix_scoring_periods_league_dates")
        batch_op.drop_index(batch_op.f("ix_scoring_periods_is_playoff"))

    op.drop_table("scoring_periods")
    with op.batch_alter_table("roster_slots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_roster_slots_league_id"))

    op.drop_table("roster_slots")
    with op.batch_alter_table("players", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_players_normalized_name"))
        batch_op.drop_index(batch_op.f("ix_players_full_name"))
        batch_op.drop_index(batch_op.f("ix_players_current_team_id"))

    op.drop_table("players")
    with op.batch_alter_table("nba_games", schema=None) as batch_op:
        batch_op.drop_index("ix_nba_games_season_date")
        batch_op.drop_index(batch_op.f("ix_nba_games_season"))
        batch_op.drop_index(batch_op.f("ix_nba_games_nba_game_id"))
        batch_op.drop_index(batch_op.f("ix_nba_games_home_team_id"))
        batch_op.drop_index(batch_op.f("ix_nba_games_game_date"))
        batch_op.drop_index(batch_op.f("ix_nba_games_away_team_id"))

    op.drop_table("nba_games")
    with op.batch_alter_table("league_scoring_profiles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_league_scoring_profiles_league_id"))
        batch_op.drop_index(batch_op.f("ix_league_scoring_profiles_is_active"))

    op.drop_table("league_scoring_profiles")
    with op.batch_alter_table("fantasy_teams", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_fantasy_teams_league_id"))
        batch_op.drop_index(batch_op.f("ix_fantasy_teams_is_owner_team"))

    op.drop_table("fantasy_teams")
    with op.batch_alter_table("nba_teams", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_nba_teams_nba_team_id"))
        batch_op.drop_index(batch_op.f("ix_nba_teams_abbreviation"))

    op.drop_table("nba_teams")
    with op.batch_alter_table("leagues", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_leagues_season"))
        batch_op.drop_index(batch_op.f("ix_leagues_fantrax_league_id"))

    op.drop_table("leagues")
