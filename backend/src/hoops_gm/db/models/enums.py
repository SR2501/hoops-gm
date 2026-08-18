"""Enumerated values used across the schema.

All of these are stored as strings via :func:`hoops_gm.db.base.portable_enum`,
which emits a VARCHAR plus a CHECK constraint. Adding a member requires a
migration to widen that constraint, which is the point: an unrecognised value
should be a loud failure, not a silent row.

That claim was false when this module was first written — ``create_constraint``
defaults to ``False`` and had been omitted, so no CHECK existed and an unknown
value inserted cleanly through any path that bypassed the ORM. See
``db/base.py`` for the detail.
"""

from __future__ import annotations

import enum


class ExternalSource(enum.StrEnum):
    """Systems that have their own idea of a player's identifier.

    Risk R7: these disagree, constantly, and **no two of them share a key**.
    Fantrax's ``getPlayerIds`` exposes ``statsIncId``, ``rotowireId`` and
    ``sportRadarId`` — none of which is an NBA.com identifier — so there is no
    anchor pair to match against. Every cross-source match is inferred, which
    makes ``confidence``, ``match_method`` and ``is_manual_override``
    load-bearing rather than metadata.

    An earlier version of this docstring claimed ``NBA`` and ``FANTRAX`` were a
    clean anchor pair. They are not; that was disproved by hitting the endpoint.

    Adding a member here **does** require a migration: these are stored as
    VARCHAR with a CHECK constraint, so the constraint has to be widened. Phase 2
    owns adding the Fantrax cross-reference sources above, since it owns the
    crosswalk and knows which of them are worth recording.
    """

    NBA = "nba"
    FANTRAX = "fantrax"
    #: Cross-reference identifiers that Fantrax carries for other providers.
    #: Recorded as first-class sources by Phase 2 for two reasons that pay off
    #: immediately rather than hypothetically: they de-duplicate *within*
    #: Fantrax, which contains genuine duplicate names (two "Johnson, Jalen",
    #: two "Jackson, Justin"), and they survive Fantrax rotating its own
    #: ``fantraxId`` between seasons.
    #:
    #: They are **not** a bridge to NBA.com. That was investigated as the plan
    #: suggested and the bridge does not exist: no free, stable public dataset
    #: maps a Sportradar GUID to an NBA.com person id, the open ID datasets
    #: carry Basketball-Reference/ESPN/Spotrac instead and are themselves built
    #: by name matching, and Sportradar's own mapping endpoint is behind a
    #: commercial subscription — an owner-only decision.
    FANTRAX_STATS_INC = "fantrax_stats_inc"
    FANTRAX_ROTOWIRE = "fantrax_rotowire"
    FANTRAX_SPORTRADAR = "fantrax_sportradar"
    FANTASYPROS = "fantasypros"
    HASHTAG = "hashtag"
    BASKETBALL_MONSTER = "basketball_monster"
    DARKO = "darko"
    MANUAL = "manual"


class FieldEvidence(enum.StrEnum):
    """What one field says about whether two records are the same person.

    Three values, not two, and that is the point. Phase 1 left open whether a
    single ``confidence`` float suffices or whether per-field evidence is
    needed. Phase 2 measured it and the answer is per-field: **1,206 of the
    1,788 Fantrax player rows carry ``team: "(N/A)"``**, so for two thirds of
    the payload the team says nothing at all. A scalar cannot distinguish a
    team that is unknown from a team that is known and contradicts — the first
    is an ordinary free agent and probably a correct match, the second is
    probably two different people. A human adjudicating the tail needs to know
    which, so it is stored per field.
    """

    AGREE = "agree"
    DISAGREE = "disagree"
    UNKNOWN = "unknown"


class ParticipationOutcome(enum.StrEnum):
    """What happened to one player for one of their team's games.

    The distinction between ``INACTIVE`` and ``UNKNOWN`` carries real weight.
    A player absent from every list for a game is not *known* to have been
    inactive — they may not have been on the roster, may have been on a
    G-League assignment, or the source may simply have a gap. Recording that as
    ``INACTIVE`` manufactures availability evidence out of silence, and
    availability is the quantity this entire project exists to model.
    """

    PLAYED = "played"
    DID_NOT_PLAY = "did_not_play"
    DID_NOT_DRESS = "did_not_dress"
    NOT_WITH_TEAM = "not_with_team"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class DnpReason(enum.StrEnum):
    """Normalised absence reason, derived from free text that is also kept.

    House rule: **do not trust stated DNP reasons.** "Rest" is routinely
    laundered as a minor ailment, and the vocabulary is inconsistent between
    seasons and scorers — the same 2025-26 season yielded
    ``"DNP - Coach's Decision"``, ``"DND - Injury/Illness"``,
    ``"NWT - Not With Team"`` and ``"NWT-Return to Competition
    Reconditioning"``, the last with no spaces around its hyphen.

    So this is a convenience for querying, not a fact. Unrecognised text maps
    to ``OTHER`` rather than being forced into the nearest category, and
    ``player_participation.raw_comment`` retains the original so a better
    normalisation can be re-derived. ``NONE_GIVEN`` means no reason was stated
    at all, which is different from a stated reason we did not recognise.
    """

    COACHES_DECISION = "coaches_decision"
    INJURY_OR_ILLNESS = "injury_or_illness"
    REST = "rest"
    PERSONAL = "personal"
    SUSPENSION = "suspension"
    G_LEAGUE = "g_league"
    TRADE_PENDING = "trade_pending"
    CONDITIONING = "conditioning"
    NOT_WITH_TEAM = "not_with_team"
    OTHER = "other"
    NONE_GIVEN = "none_given"


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


class RefreshArtifactType(enum.StrEnum):
    """The broad lineage domains a refresh can be registered against.

    Deliberately three coarse values, not a taxonomy of every model or feed
    that will ever exist. ``schedule`` is ``data-engineer``'s ingest facts,
    ``projection`` and ``model`` are ``quant``'s later Phase 5 outputs. This is
    the cohort key downstream consumers compare a claimed version against; it
    is not, and must not become, a place to encode what a version *means*.
    """

    SCHEDULE = "schedule"
    PROJECTION = "projection"
    MODEL = "model"


class StatScope(enum.StrEnum):
    """Whether a season-stats row is for one team or the season total.

    A traded player has a row per team plus a combined row. Using a nullable
    ``team_id`` in the unique key would not work: SQL treats NULLs as distinct,
    so duplicate totals would slip through on both dialects.
    """

    TEAM = "team"
    TOTAL = "total"
