"""Per-source column-mapping profiles for the projection CSV importer.

A profile states, once, how one source's CSV maps onto the canonical fields
the parser produces. Nothing here talks to a database or a network — profiles
are data, and the parser that reads them is a pure function, so both stay
testable offline (the same reason ``ingest/nba/parsers.py`` never imports
SQLAlchemy).

**The FantasyPros / Hashtag / Basketball Monster profiles below are
best-effort, not verified live captures.** Every other adapter in this
project earns its column mapping against a fixture pulled from the real
endpoint (`ingest/record_fixtures.py`); these three sources sit behind a
Patreon paywall, a paid subscription, or an authenticated export, so nobody
has actually downloaded one of their files to check the header spelling
against. The aliases below are a reasonable guess at common 9-cat export
conventions and are deliberately generous (several spellings per field) so a
close-but-not-identical real header still resolves — but "the importer runs"
is not the same claim as "the mapping is correct", and the first real file
run through one of these three should be checked by hand against
``resolved_headers`` before anything downstream trusts it. Say so here rather
than silently asserting a confidence nobody has earned.

``MANUAL_PROFILE`` carries no such uncertainty: it expects the canonical field
names directly (a spreadsheet the owner builds or converts by hand), and is
the profile to reach for whenever a vendor mapping has not been confirmed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from hoops_gm.db.models.enums import ExternalSource

__all__ = [
    "BASKETBALL_MONSTER_PROFILE",
    "CANONICAL_STAT_FIELDS",
    "FANTASYPROS_PROFILE",
    "HASHTAG_PROFILE",
    "MANUAL_PROFILE",
    "PROFILES_BY_SOURCE",
    "ColumnProfile",
    "StatColumn",
    "ValueShape",
    "normalize_header",
    "resolve_header",
]


class ValueShape(StrEnum):
    """Whether a numeric column already reports a per-game rate or a season total.

    Treating a season total as a per-game rate (or the reverse) is silently
    wrong by exactly the games-played factor ADR-002 exists to keep visible.
    The profile states which shape a column is in once, rather than leaving
    it to be rediscovered — or missed — per source at parse time.
    """

    PER_GAME = "per_game"
    SEASON_TOTAL = "season_total"


@dataclass(frozen=True)
class StatColumn:
    """One canonical stat, and where to find it in a specific source's CSV."""

    #: Canonical field name — one of :data:`CANONICAL_STAT_FIELDS`.
    field: str
    #: Candidate header spellings, tried in order. Matching is
    #: case-insensitive and tolerant of surrounding whitespace and
    #: underscore/space variance (:func:`normalize_header`).
    aliases: tuple[str, ...]
    shape: ValueShape = ValueShape.PER_GAME


#: Every per-game rate field a projection row can carry. Mirrors the columns
#: on ``db.models.projections.Projection`` exactly; ``test_projections.py``
#: asserts the two stay in step, the same discipline
#: ``stats.BOX_SCORE_STAT_KEYS`` uses for the box-score schema.
CANONICAL_STAT_FIELDS: tuple[str, ...] = (
    "minutes_per_game",
    "points_per_game",
    "offensive_rebounds_per_game",
    "defensive_rebounds_per_game",
    "rebounds_per_game",
    "assists_per_game",
    "steals_per_game",
    "blocks_per_game",
    "turnovers_per_game",
    "personal_fouls_per_game",
    "field_goals_made_per_game",
    "field_goals_attempted_per_game",
    "three_pointers_made_per_game",
    "three_pointers_attempted_per_game",
    "free_throws_made_per_game",
    "free_throws_attempted_per_game",
)

#: Made/attempted pairs whose *only* legitimate source is volume, never a
#: percentage. Used by the parser to decide when a percentage-only column is
#: a dead end worth a warning rather than a silent gap.
SHOOTING_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("field_goals_made_per_game", "field_goals_attempted_per_game", "field goal"),
    ("three_pointers_made_per_game", "three_pointers_attempted_per_game", "three-point"),
    ("free_throws_made_per_game", "free_throws_attempted_per_game", "free throw"),
)


@dataclass(frozen=True)
class ColumnProfile:
    """A source's CSV shape: which headers mean what, and how they're scaled."""

    source: ExternalSource
    display_name: str
    name_aliases: tuple[str, ...]
    team_aliases: tuple[str, ...] = ()
    position_aliases: tuple[str, ...] = ()
    games_played_aliases: tuple[str, ...] = ()
    stat_columns: tuple[StatColumn, ...] = field(default_factory=tuple)
    #: Percentage-only fallback headers, keyed by the made-field they cannot
    #: substitute for (e.g. ``"field_goals_made_per_game"`` ->
    #: ``("fg%", "fg pct")``). Present only so the parser can recognise "the
    #: source gave a percentage, not volume" and warn rather than silently
    #: import nothing with no explanation.
    percentage_fallback_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: Whether this mapping has been checked against a real downloaded file.
    #: ``False`` for every vendor profile below; see the module docstring.
    verified: bool = False


_WS_OR_UNDERSCORE = re.compile(r"[\s_]+")
_NON_ALNUM = re.compile(r"[^a-z0-9%]+")


def normalize_header(value: str) -> str:
    """Fold header spelling variance: case, whitespace, underscores, punctuation.

    ``%`` is kept — it is the one character that changes a header's meaning
    outright ("FG" versus "FG%"), so folding it away would make the
    percentage-fallback detection blind to the exact distinction it exists to
    catch.
    """
    lowered = value.strip().lower()
    collapsed = _WS_OR_UNDERSCORE.sub(" ", lowered)
    return _NON_ALNUM.sub("", collapsed.replace(" ", ""))


def resolve_header(fieldnames: list[str], aliases: tuple[str, ...]) -> str | None:
    """The first actual CSV header matching any alias, or ``None``."""
    if not aliases:
        return None
    normalized_fields = {normalize_header(name): name for name in fieldnames}
    for alias in aliases:
        match = normalized_fields.get(normalize_header(alias))
        if match is not None:
            return match
    return None


# --------------------------------------------------------------------------
# Built-in profiles
# --------------------------------------------------------------------------

MANUAL_PROFILE = ColumnProfile(
    source=ExternalSource.MANUAL,
    display_name="Manual / generic",
    name_aliases=("player_name", "player", "name"),
    team_aliases=("team",),
    position_aliases=("position", "pos"),
    games_played_aliases=("games_played", "gp"),
    stat_columns=tuple(
        StatColumn(field=canonical, aliases=(canonical,)) for canonical in CANONICAL_STAT_FIELDS
    ),
    verified=True,
)

FANTASYPROS_PROFILE = ColumnProfile(
    source=ExternalSource.FANTASYPROS,
    display_name="FantasyPros",
    name_aliases=("player", "player name"),
    team_aliases=("team",),
    position_aliases=("pos", "position"),
    games_played_aliases=("gp", "games played"),
    stat_columns=(
        StatColumn("minutes_per_game", ("min", "mpg", "minutes")),
        StatColumn("points_per_game", ("pts",)),
        StatColumn("rebounds_per_game", ("treb", "reb", "rebounds")),
        StatColumn("assists_per_game", ("ast",)),
        StatColumn("steals_per_game", ("st", "stl")),
        StatColumn("blocks_per_game", ("blk",)),
        StatColumn("turnovers_per_game", ("to", "tov")),
        StatColumn("three_pointers_made_per_game", ("3pm",)),
    ),
    # FantasyPros' free 9-cat export publishes FG%/FT% without makes or
    # attempts, so those two categories cannot be volume-weighted from it —
    # the parser reports this rather than treating the percentage as a rate.
    percentage_fallback_aliases={
        "field_goals_made_per_game": ("fg%", "fg pct"),
        "free_throws_made_per_game": ("ft%", "ft pct"),
    },
    verified=False,
)

HASHTAG_PROFILE = ColumnProfile(
    source=ExternalSource.HASHTAG,
    display_name="Hashtag Basketball",
    name_aliases=("player", "name"),
    team_aliases=("team",),
    position_aliases=("pos", "position"),
    games_played_aliases=("gp", "games"),
    stat_columns=(
        StatColumn("minutes_per_game", ("mpg", "min")),
        StatColumn("points_per_game", ("pts",)),
        StatColumn("offensive_rebounds_per_game", ("oreb", "orb")),
        StatColumn("defensive_rebounds_per_game", ("dreb", "drb")),
        StatColumn("rebounds_per_game", ("reb", "trb")),
        StatColumn("assists_per_game", ("ast",)),
        StatColumn("steals_per_game", ("stl", "st")),
        StatColumn("blocks_per_game", ("blk",)),
        StatColumn("turnovers_per_game", ("to", "tov")),
        StatColumn("field_goals_made_per_game", ("fgm",)),
        StatColumn("field_goals_attempted_per_game", ("fga",)),
        StatColumn("three_pointers_made_per_game", ("3pm", "3ptm")),
        StatColumn("three_pointers_attempted_per_game", ("3pa", "3pta")),
        StatColumn("free_throws_made_per_game", ("ftm",)),
        StatColumn("free_throws_attempted_per_game", ("fta",)),
    ),
    percentage_fallback_aliases={
        "field_goals_made_per_game": ("fg%",),
        "free_throws_made_per_game": ("ft%",),
    },
    verified=False,
)

BASKETBALL_MONSTER_PROFILE = ColumnProfile(
    source=ExternalSource.BASKETBALL_MONSTER,
    display_name="Basketball Monster",
    name_aliases=("player", "name"),
    team_aliases=("team", "tm"),
    position_aliases=("pos", "position"),
    games_played_aliases=("gp", "g"),
    stat_columns=(
        StatColumn("minutes_per_game", ("min", "mpg")),
        StatColumn("points_per_game", ("pts",)),
        StatColumn("rebounds_per_game", ("reb", "trb")),
        StatColumn("assists_per_game", ("ast",)),
        StatColumn("steals_per_game", ("stl",)),
        StatColumn("blocks_per_game", ("blk",)),
        StatColumn("turnovers_per_game", ("to", "tov")),
        StatColumn("field_goals_made_per_game", ("fgm",)),
        StatColumn("field_goals_attempted_per_game", ("fga",)),
        StatColumn("three_pointers_made_per_game", ("3pm",)),
        StatColumn("three_pointers_attempted_per_game", ("3pa",)),
        StatColumn("free_throws_made_per_game", ("ftm",)),
        StatColumn("free_throws_attempted_per_game", ("fta",)),
    ),
    percentage_fallback_aliases={
        "field_goals_made_per_game": ("fg%",),
        "free_throws_made_per_game": ("ft%",),
    },
    verified=False,
)

PROFILES_BY_SOURCE: dict[ExternalSource, ColumnProfile] = {
    ExternalSource.MANUAL: MANUAL_PROFILE,
    ExternalSource.FANTASYPROS: FANTASYPROS_PROFILE,
    ExternalSource.HASHTAG: HASHTAG_PROFILE,
    ExternalSource.BASKETBALL_MONSTER: BASKETBALL_MONSTER_PROFILE,
}
