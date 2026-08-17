"""Enumerated values used across the schema.

All of these are stored as strings via :func:`hoops_gm.db.base.portable_enum`.
Adding a member requires a migration to widen the CHECK constraint, which is
the point: an unrecognised value should be a loud failure, not a silent row.
"""

from __future__ import annotations

import enum


class ExternalSource(enum.StrEnum):
    """Systems that have their own idea of a player's identifier.

    Risk R7: these disagree, constantly. ``NBA`` and ``FANTRAX`` are the anchor
    pair; everything else is matched against that anchor with a confidence
    score. Projection providers are listed individually because a name string
    from one CSV is not interchangeable with a name string from another.
    """

    NBA = "nba"
    FANTRAX = "fantrax"
    FANTASYPROS = "fantasypros"
    HASHTAG = "hashtag"
    BASKETBALL_MONSTER = "basketball_monster"
    DARKO = "darko"
    MANUAL = "manual"


class MatchMethod(enum.StrEnum):
    """How an external identifier came to be attached to a canonical player."""

    ANCHOR_ID = "anchor_id"
    EXACT_NAME = "exact_name"
    NORMALIZED_NAME = "normalized_name"
    NAME_TEAM_POSITION = "name_team_position"
    FUZZY = "fuzzy"
    MANUAL_OVERRIDE = "manual_override"


class PlayerStatus(enum.StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    TWO_WAY = "two_way"
    G_LEAGUE = "g_league"
    RETIRED = "retired"
    UNKNOWN = "unknown"


class Conference(enum.StrEnum):
    EAST = "East"
    WEST = "West"


class SeasonType(enum.StrEnum):
    PRESEASON = "preseason"
    REGULAR = "regular"
    PLAY_IN = "play_in"
    PLAYOFFS = "playoffs"


class GameStatus(enum.StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINAL = "final"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"


class ScoringType(enum.StrEnum):
    H2H_CATEGORIES = "h2h_categories"
    H2H_POINTS = "h2h_points"
    H2H_EACH_CATEGORY = "h2h_each_category"
    ROTO = "roto"
    POINTS = "points"


class DraftType(enum.StrEnum):
    SNAKE = "snake"
    AUCTION = "auction"
    LINEAR = "linear"
    UNKNOWN = "unknown"


class CategoryKind(enum.StrEnum):
    """Counting versus ratio.

    This distinction is the guard against the single most common bug in
    homebrew fantasy tools: treating FG% and FT% as raw percentages. A ratio
    category carries a numerator and a denominator stat so that impact can be
    volume-weighted downstream. A 90% free-throw shooter on one attempt is
    worthless, and the schema has to make that expressible.
    """

    COUNTING = "counting"
    RATIO = "ratio"


class RosterStatus(enum.StrEnum):
    ACTIVE = "active"
    RESERVE = "reserve"
    INJURED_RESERVE = "injured_reserve"
    MINORS = "minors"


class MatchupStatus(enum.StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    FINAL = "final"


class CategoryOutcome(enum.StrEnum):
    HOME = "home"
    AWAY = "away"
    TIE = "tie"


class TransactionType(enum.StrEnum):
    ADD = "add"
    DROP = "drop"
    WAIVER_CLAIM = "waiver_claim"
    TRADE = "trade"
    DRAFT = "draft"
    IR_MOVE = "ir_move"
    OTHER = "other"


class StatScope(enum.StrEnum):
    """Whether a season-stats row is for one team or the season total.

    A traded player has a row per team plus a combined row. Using a nullable
    ``team_id`` in the unique key would not work: SQL treats NULLs as distinct,
    so duplicate totals would slip through on both dialects.
    """

    TEAM = "team"
    TOTAL = "total"
