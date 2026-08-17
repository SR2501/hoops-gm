"""Typed records returned by the Fantrax official adapter's parsers.

Plain frozen dataclasses, deliberately not SQLAlchemy models. A parser that
returns ORM objects cannot be tested without a database, and the whole point of
the Adapter gate is that the contract test is offline and instant.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FantraxPlayer:
    """One player row from ``getPlayerIds``.

    Every cross-reference identifier is optional because every one of them is
    genuinely missing sometimes. Measured on the live payload, 2026-08-17:
    ``sportRadarId`` on 1,438 of 1,788 rows, ``rotowireId`` on 1,723,
    ``statsIncId`` on only 851. A parser that assumed any of them was present
    would drop between 4% and 52% of the league.
    """

    fantrax_id: str
    #: Exactly as Fantrax wrote it, ``"Last, First"``.
    name: str
    #: Fantrax's abbreviation, or ``""`` where Fantrax said ``"(N/A)"``.
    team: str
    position: str
    stats_inc_id: str | None = None
    rotowire_id: str | None = None
    sport_radar_id: str | None = None


@dataclass(frozen=True)
class FantraxTeamEntity:
    """A non-player row that ``getPlayerIds`` mixes in with the players.

    Risk R24. Thirty of these appear in the payload — one per franchise —
    carrying ``position: "Tm"`` and a ``#`` in the identifier, e.g.
    ``40220#3020``. A naive importer creates thirty garbage player rows named
    "Team" and then matches them against each other forever.

    They are parsed rather than discarded because "we saw 30 team rows" is a
    fact worth asserting in a contract test, and because a change in that count
    is a signal about the payload.
    """

    fantrax_id: str
    team_name: str
    team_short_name: str


@dataclass(frozen=True)
class FantraxPlayerIds:
    """The whole ``getPlayerIds`` payload, separated into what it actually is."""

    players: list[FantraxPlayer] = field(default_factory=list)
    team_entities: list[FantraxTeamEntity] = field(default_factory=list)
    #: Rows that are neither, kept so an unrecognised third kind of row shows
    #: up as a number in a test rather than vanishing.
    unclassified: list[str] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return len(self.players) + len(self.team_entities) + len(self.unclassified)


@dataclass(frozen=True)
class FantraxAdpEntry:
    """One row from ``getAdp``."""

    fantrax_id: str
    name: str
    position: str
    adp: float


@dataclass(frozen=True)
class FantraxLeagueTeam:
    """A fantasy team within a league, from ``getLeagueInfo``."""

    team_id: str
    name: str
    short_name: str | None = None
    owner_name: str | None = None


@dataclass(frozen=True)
class FantraxScoringCategory:
    """A scoring category as the league defines it.

    Retained verbatim. The plan's nine-category vocabulary is our own; whether
    Fantrax agrees with it is a mapping question that belongs in this adapter,
    and the mapping can only be written against what the league really returns.
    """

    key: str
    name: str | None = None
    abbreviation: str | None = None


@dataclass(frozen=True)
class FantraxLeagueInfo:
    """League settings from ``getLeagueInfo``."""

    league_id: str
    league_name: str | None
    sport: str | None
    scoring_type: str | None
    draft_type: str | None
    roster_size: int | None
    teams: list[FantraxLeagueTeam] = field(default_factory=list)
    scoring_categories: list[FantraxScoringCategory] = field(default_factory=list)
    #: Keys present in the payload that this parser does not interpret. A
    #: league setting we silently ignore is a setting the draft engine will get
    #: wrong, so it is surfaced rather than dropped.
    unmapped_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class FantraxDraftPick:
    """One pick from ``getDraftPicks``."""

    team_id: str
    round_number: int | None = None
    pick_number: int | None = None
    overall_pick: int | None = None
    player_id: str | None = None
    player_name: str | None = None
    #: Auction leagues carry a price and snake leagues do not. Both formats are
    #: first-class in this project, so neither shape may be assumed.
    auction_amount: float | None = None
