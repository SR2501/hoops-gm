"""Typed records parsed out of ``nba_api`` responses.

Plain frozen dataclasses so the parsers stay pure and the contract tests stay
offline. Nothing here is a SQLAlchemy model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from hoops_gm.db.models.enums import DnpReason, ParticipationOutcome

#: Re-exported so an adapter never has to reach into the database package for a
#: vocabulary, while the vocabulary itself lives in exactly one place — the
#: place whose CHECK constraints enforce it. Two copies of an enum is two
#: vocabularies waiting to disagree.
__all__ = [
    "DnpReason",
    "GameParticipation",
    "NbaGameRecord",
    "NbaPlayerPositionRecord",
    "NbaPlayerRecord",
    "NbaTeamRecord",
    "ParticipationOutcome",
    "PlayerBoxScoreRecord",
    "PlayerParticipationRecord",
]


@dataclass(frozen=True)
class NbaTeamRecord:
    nba_team_id: int
    abbreviation: str
    full_name: str
    city: str | None = None
    nickname: str | None = None


@dataclass(frozen=True)
class NbaGameRecord:
    """One game, from the team-agnostic point of view."""

    nba_game_id: str
    season: str
    season_type: str
    game_date: date
    home_team_id: int
    away_team_id: int
    home_score: int | None = None
    away_score: int | None = None
    #: Tip-off as a UTC instant, when the source gave one. ``LeagueGameFinder``
    #: gives only a local date; ``BoxScoreSummaryV3`` gives ``gameTimeUTC``.
    #: Back-to-back and rest-day detection need the instant, so a game known
    #: only from the game finder is deliberately left with ``None`` rather than
    #: a midnight guess.
    tipoff_utc: datetime | None = None
    status: str | None = None


@dataclass(frozen=True)
class PlayerBoxScoreRecord:
    """One player's line for one game."""

    nba_player_id: int
    nba_game_id: str
    nba_team_id: int
    player_name: str
    seconds_played: int | None = None
    field_goals_made: int | None = None
    field_goals_attempted: int | None = None
    three_pointers_made: int | None = None
    three_pointers_attempted: int | None = None
    free_throws_made: int | None = None
    free_throws_attempted: int | None = None
    points: int | None = None
    offensive_rebounds: int | None = None
    defensive_rebounds: int | None = None
    rebounds: int | None = None
    assists: int | None = None
    steals: int | None = None
    blocks: int | None = None
    turnovers: int | None = None
    personal_fouls: int | None = None
    plus_minus: int | None = None
    started: bool | None = None


@dataclass(frozen=True)
class PlayerParticipationRecord:
    """Whether a player took part in a game, and what was said about it.

    ``raw_comment`` is preserved verbatim alongside ``reason``. The
    normalisation will be wrong at first and will need re-deriving from the
    original text; a normalised code with the evidence thrown away cannot be
    re-derived at all.
    """

    nba_player_id: int
    nba_game_id: str
    nba_team_id: int
    outcome: ParticipationOutcome
    reason: DnpReason
    #: Exactly the text the source gave, including its inconsistent spacing.
    raw_comment: str
    player_name: str | None = None
    seconds_played: int | None = None


@dataclass(frozen=True)
class GameParticipation:
    """Everything one game says about who took part.

    ``inactives_available`` records whether the source *offered* an inactive
    list at all, which is not the same as offering an empty one. Without that
    flag, "nobody was inactive" and "this endpoint no longer tells us" are the
    same row — and they were, silently, for the whole of the 2025-26 season on
    ``BoxScoreSummaryV2``.
    """

    nba_game_id: str
    records: list[PlayerParticipationRecord] = field(default_factory=list)
    inactives_available: bool = False

    @property
    def inactive_count(self) -> int:
        return sum(1 for r in self.records if r.outcome is ParticipationOutcome.INACTIVE)

    @property
    def played_count(self) -> int:
        return sum(1 for r in self.records if r.outcome is ParticipationOutcome.PLAYED)


@dataclass(frozen=True)
class NbaPlayerRecord:
    """A player from ``CommonAllPlayers`` — the NBA side of the crosswalk."""

    nba_player_id: int
    #: ``"Last, First"``, which is the same shape Fantrax uses. Convenient, and
    #: not a contract: other endpoints give the parts separately.
    display_last_comma_first: str
    display_first_last: str
    is_active_roster: bool
    from_year: str | None = None
    to_year: str | None = None
    team_id: int | None = None
    team_abbreviation: str | None = None
    player_slug: str | None = None


@dataclass(frozen=True)
class NbaPlayerPositionRecord:
    """One player's **listed NBA position**, from ``PlayerIndex``.

    This is a fact about the player — the position the NBA lists him at — and
    is deliberately a different type from anything per-game. The distinction is
    the whole reason this record exists, so it is worth stating precisely.

    **What this is not.** ``BoxScoreTraditionalV3.position`` is a *starting
    lineup slot*: emitted for exactly five players per team per game, always in
    the sequence ``F,F,C,G,G``, blank for everyone else. It answers "which slot
    did he start in tonight", and a distribution over it is forced to 2F:2G:1C
    for any cohort whatsoever. Before 2026-08-20 it was the only
    position-shaped field this project ingested, which is why risk R7 specified
    the identity crosswalk to match on a position key that did not exist.

    **What this is not, part two.** It is *not* Fantrax position eligibility,
    and cannot be turned into it by any derivation. Fantrax eligibility is a
    policy decision by a third party — it changes through a season, never
    decreases, and Fantrax is not obliged to follow any published rule. A
    number computed from NBA game data and presented as eligibility would be a
    prediction of another company's undocumented behaviour wearing the clothes
    of a fact. See ``docs/backlog.md``, ``player-position-eligibility``.

    ``position`` is ``None`` when the source states no position. That is a real
    and observed condition — six 2026-27 rows, all players whose ``FROM_YEAR``
    is 2026 — and it is preserved rather than guessed at, because an invented
    position would corroborate an identity match on evidence nobody supplied.
    """

    nba_player_id: int
    #: Verbatim from the source: ``"G"``, ``"F-C"``, … or ``None`` if unstated.
    #: **Coarse.** The source vocabulary contains no ``PG``/``SG``/``SF``/``PF``
    #: distinction at all, on this endpoint or on any sibling checked.
    position: str | None
    first_name: str | None = None
    last_name: str | None = None
    team_id: int | None = None
    team_abbreviation: str | None = None
    #: The season the listing was requested for. Position is stable but not
    #: immutable, and a stored attribute with no idea which season it describes
    #: cannot be refreshed deliberately.
    season: str | None = None
