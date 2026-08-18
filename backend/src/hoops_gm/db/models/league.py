"""League: Fantrax league state — settings, teams, rosters, periods, matchups.

Two structural decisions here carry weight beyond Phase 1.

**Scoring profiles are versioned and immutable.** ``league_scoring_profiles``
carries a ``version`` and is unique on ``(league_id, name, version)``. Changing
a profile means inserting a new version, never mutating the old row. That is
the seam the plan's versioning requirement rests on: when Phase 5 stores a
valuation, it takes a foreign key to a profile *row*, and the exact configuration
that produced a number stays recoverable forever. The same applies to the punt
configs and blend profiles that arrive later — they follow this pattern.

**Ratio categories carry their numerator and denominator.** FG% is not a number
to be averaged; it is made-over-attempted, and its fantasy impact is weighted by
volume. Recording the component stat keys here is what lets the valuation engine
do that correctly instead of averaging percentages (risk R9).

**`scoring-profiles` (docs/backlog.md)** adds the derivation and activation
discipline on top of the two decisions above: ``hoops_gm.scoring.profiles``
owns turning a league's raw scoring-category evidence and its current
``LeagueSettingsSnapshot`` into rows here, and enforces "at most one active
profile per league" as a database constraint (``active_league_id``) rather
than an application convention. See that module and ``LeagueScoringProfile``'s
docstring for the mechanism.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hoops_gm.db.base import Base, IntPk, TimestampMixin, portable_enum
from hoops_gm.db.models.enums import (
    CategoryKind,
    CategoryOutcome,
    DraftType,
    MatchupStatus,
    RosterStatus,
    ScoringType,
    TransactionType,
)
from hoops_gm.db.models.stats import stat_key_sql_list

if TYPE_CHECKING:
    from hoops_gm.db.models.deadline_calendar import LeagueDeadlineCalendar
    from hoops_gm.db.models.identity import Player
    from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot


class League(IntPk, TimestampMixin, Base):
    """A fantasy league for one season."""

    __tablename__ = "leagues"
    __table_args__ = (
        UniqueConstraint("fantrax_league_id", "season", name="uq_leagues_fantrax_season"),
    )

    #: Nullable so a league can exist locally before it is linked to Fantrax —
    #: mock drafts and imported market data need somewhere to live.
    fantrax_league_id: Mapped[str | None] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    season: Mapped[str] = mapped_column(String(9), index=True)
    scoring_type: Mapped[ScoringType] = mapped_column(
        portable_enum(ScoringType, "scoring_type"), default=ScoringType.H2H_CATEGORIES
    )
    draft_type: Mapped[DraftType] = mapped_column(
        portable_enum(DraftType, "draft_type"), default=DraftType.UNKNOWN
    )
    team_count: Mapped[int | None] = mapped_column()
    roster_size: Mapped[int | None] = mapped_column()
    #: Auction only. Numeric rather than float: this is money and it is compared.
    auction_budget: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    is_active: Mapped[bool] = mapped_column(default=True)

    #: ``foreign_keys`` is required here: ``league_scoring_profiles`` carries
    #: two FKs to ``leagues.id`` (``league_id`` and the activation sentinel
    #: ``active_league_id``), and without disambiguation SQLAlchemy cannot
    #: tell which one this collection should join on.
    scoring_profiles: Mapped[list[LeagueScoringProfile]] = relationship(
        back_populates="league",
        cascade="all, delete-orphan",
        foreign_keys="LeagueScoringProfile.league_id",
    )
    fantasy_teams: Mapped[list[FantasyTeam]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )
    roster_slots: Mapped[list[RosterSlot]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )
    scoring_periods: Mapped[list[ScoringPeriod]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )
    settings_snapshots: Mapped[list[LeagueSettingsSnapshot]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )
    deadline_calendars: Mapped[list[LeagueDeadlineCalendar]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<League {self.name!r} {self.season}>"


class LeagueScoringProfile(IntPk, TimestampMixin, Base):
    """A versioned, immutable snapshot of how a league scores.

    Do not update a profile in place. Insert the next version and repoint.
    Anything that stores a computed number takes a foreign key here, which is
    how "what settings produced this valuation" stays answerable.

    ``settings_snapshot_id`` is the league-rules lineage: the
    ``LeagueSettingsSnapshot`` version that was current when this profile was
    derived. It answers "what else was true about the league's rules at the
    moment this scoring profile was built" and is what
    ``hoops_gm.scoring.profiles`` refuses to skip -- see that module for the
    stale-settings rejection this column exists to make checkable.

    **At most one active profile per league, enforced by the database, not by
    convention.** ``active_league_id`` mirrors ``league_id`` while this row is
    the league's current profile, and is ``NULL`` otherwise. A bare
    ``UniqueConstraint`` on this single nullable column is what makes "only one
    active row per league" a guarantee: SQL treats every ``NULL`` as distinct,
    so any number of superseded (inactive) versions may coexist, while at most
    one row can ever carry a given non-null league id here. This is
    deliberately not a partial/filtered unique index (``WHERE is_active``):
    that requires a dialect-specific keyword
    (``sqlite_where``/``postgresql_where``) that this codebase's own
    portability tests forbid (``test_portability.py``), so the nullable-sentinel
    column is the portable substitute. ``is_active`` is a derived Python
    property over it, not a stored column, so there is only ever one fact to
    keep consistent.
    """

    __tablename__ = "league_scoring_profiles"
    __table_args__ = (
        UniqueConstraint("league_id", "name", "version", name="uq_league_scoring_profiles_ver"),
        CheckConstraint("version >= 1", name="version_positive"),
        UniqueConstraint("active_league_id", name="uq_league_scoring_profiles_one_active"),
        CheckConstraint(
            "active_league_id IS NULL OR active_league_id = league_id",
            name="active_league_id_matches_league",
        ),
    )

    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64), default="default")
    version: Mapped[int] = mapped_column(default=1)
    scoring_type: Mapped[ScoringType] = mapped_column(
        portable_enum(ScoringType, "scoring_type"), default=ScoringType.H2H_CATEGORIES
    )
    #: The league-settings version this profile was derived from. Not
    #: nullable: a scoring profile with no rules lineage cannot answer "why
    #: does this league score this way", which is exactly the provenance gap
    #: ADR-004's source tiering exists to close elsewhere. No ``ondelete`` is
    #: given deliberately: the default (reject) behaviour is what "a cited
    #: settings snapshot cannot be deleted out from under a profile" means.
    settings_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey(
            "league_settings_snapshots.id",
            # Explicit, shortened name: the naming-convention default
            # ("fk_league_scoring_profiles_settings_snapshot_id_league_settings_snapshots")
            # is 73 characters and Postgres silently truncates past 63,
            # which test_portability.py's identifier-length check catches.
            name="fk_league_scoring_profiles_settings_snapshot_id",
        ),
        index=True,
    )
    #: See the class docstring: non-null and equal to ``league_id`` exactly
    #: while this row is the league's active profile, ``NULL`` otherwise.
    active_league_id: Mapped[int | None] = mapped_column(
        ForeignKey("leagues.id", ondelete="CASCADE")
    )
    source_note: Mapped[str | None] = mapped_column(Text)

    league: Mapped[League] = relationship(
        back_populates="scoring_profiles", foreign_keys="LeagueScoringProfile.league_id"
    )
    settings_snapshot: Mapped[LeagueSettingsSnapshot] = relationship()
    categories: Mapped[list[LeagueScoringCategory]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )

    @property
    def is_active(self) -> bool:
        return self.active_league_id is not None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LeagueScoringProfile {self.name!r} v{self.version}>"


class LeagueScoringCategory(IntPk, TimestampMixin, Base):
    """One scored category within a profile.

    ``kind`` separates counting categories from ratio categories. For a ratio,
    ``numerator_stat`` and ``denominator_stat`` name the underlying counting
    stats, so downstream code weights impact by volume rather than averaging a
    percentage.

    ``direction`` is ``-1`` for turnovers. Storing the sign rather than
    special-casing a category name means points and roto profiles slot in
    without touching the engine.
    """

    __tablename__ = "league_scoring_categories"
    __table_args__ = (
        UniqueConstraint("profile_id", "key", name="uq_league_scoring_categories_key"),
        CheckConstraint("direction IN (-1, 1)", name="direction_sign"),
        CheckConstraint(
            "(kind = 'counting' AND numerator_stat IS NULL AND denominator_stat IS NULL) "
            "OR (kind = 'ratio' AND numerator_stat IS NOT NULL "
            "AND denominator_stat IS NOT NULL)",
            name="ratio_components_present",
        ),
        # Components must name real box-score columns. Without this, a typo
        # like 'ftm_typo' is accepted and the valuation engine silently has
        # nothing to weight the category by — which is the R9 bug wearing a
        # different hat.
        CheckConstraint(
            f"numerator_stat IS NULL OR numerator_stat IN ({stat_key_sql_list()})",
            name="numerator_in_vocabulary",
        ),
        CheckConstraint(
            f"denominator_stat IS NULL OR denominator_stat IN ({stat_key_sql_list()})",
            name="denominator_in_vocabulary",
        ),
        # A known percentage category declared as COUNTING is the R9 bug
        # stated outright. An IN list rather than a LIKE pattern, because
        # SQLite's LIKE is case-insensitive and Postgres's is not, and this
        # module may not introduce a dialect divergence.
        CheckConstraint(
            "key NOT IN ('fg_pct', 'ft_pct', 'fg3_pct', 'ts_pct', 'efg_pct') OR kind = 'ratio'",
            name="percentage_keys_are_ratios",
        ),
    )

    profile_id: Mapped[int] = mapped_column(
        ForeignKey("league_scoring_profiles.id", ondelete="CASCADE"), index=True
    )
    #: Stable machine key: ``pts``, ``reb``, ``fg_pct``, ``to``.
    key: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(48))
    kind: Mapped[CategoryKind] = mapped_column(
        portable_enum(CategoryKind, "category_kind"), default=CategoryKind.COUNTING
    )
    #: ``1`` where more is better, ``-1`` where less is better (turnovers).
    direction: Mapped[int] = mapped_column(default=1)
    display_order: Mapped[int] = mapped_column(default=0)
    #: Points-league weight. Null for category leagues.
    point_value: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))

    numerator_stat: Mapped[str | None] = mapped_column(String(32))
    denominator_stat: Mapped[str | None] = mapped_column(String(32))

    profile: Mapped[LeagueScoringProfile] = relationship(back_populates="categories")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LeagueScoringCategory {self.key}>"


class FantasyTeam(IntPk, TimestampMixin, Base):
    """A team within a fantasy league."""

    __tablename__ = "fantasy_teams"
    __table_args__ = (
        UniqueConstraint("league_id", "fantrax_team_id", name="uq_fantasy_teams_fantrax"),
    )

    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    fantrax_team_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    short_name: Mapped[str | None] = mapped_column(String(32))
    owner_name: Mapped[str | None] = mapped_column(String(128))
    #: Whose team this is. Almost every view is relative to it.
    is_owner_team: Mapped[bool] = mapped_column(default=False, index=True)

    league: Mapped[League] = relationship(back_populates="fantasy_teams")
    roster_entries: Mapped[list[RosterEntry]] = relationship(
        back_populates="fantasy_team", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<FantasyTeam {self.name!r}>"


class RosterSlot(IntPk, TimestampMixin, Base):
    """A slot in the league's roster structure — the shape, not an occupant."""

    __tablename__ = "roster_slots"
    __table_args__ = (
        UniqueConstraint("league_id", "code", name="uq_roster_slots_code"),
        CheckConstraint("slot_count >= 0", name="slot_count_non_negative"),
    )

    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    #: ``PG``, ``G``, ``F``, ``C``, ``UTIL``, ``BN``, ``IR``.
    code: Mapped[str] = mapped_column(String(16))
    label: Mapped[str | None] = mapped_column(String(48))
    slot_count: Mapped[int] = mapped_column(default=1)
    display_order: Mapped[int] = mapped_column(default=0)
    #: Only starting slots accrue stats; bench and IR do not.
    is_starting: Mapped[bool] = mapped_column(default=True)
    is_injury_reserve: Mapped[bool] = mapped_column(default=False)
    #: Comma-separated NBA positions eligible for this slot, e.g. ``PG,SG``.
    eligible_positions: Mapped[str | None] = mapped_column(String(64))

    league: Mapped[League] = relationship(back_populates="roster_slots")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RosterSlot {self.code}>"


class RosterEntry(IntPk, TimestampMixin, Base):
    """A player currently on a fantasy team.

    Current state only. Daily lineup assignment across a scoring period is a
    Phase 11 concern with a different shape, and conflating the two here would
    force a rewrite then.
    """

    __tablename__ = "rosters"
    __table_args__ = (
        UniqueConstraint("fantasy_team_id", "player_id", name="uq_rosters_team_player"),
        Index("ix_rosters_player_status", "player_id", "status"),
    )

    fantasy_team_id: Mapped[int] = mapped_column(
        ForeignKey("fantasy_teams.id", ondelete="CASCADE"), index=True
    )
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    slot_code: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[RosterStatus] = mapped_column(
        portable_enum(RosterStatus, "roster_status"), default=RosterStatus.ACTIVE
    )
    acquired_on: Mapped[date | None] = mapped_column(Date)
    #: Auction price or keeper salary where the league has one.
    salary: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    fantasy_team: Mapped[FantasyTeam] = relationship(back_populates="roster_entries")
    player: Mapped[Player] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RosterEntry team={self.fantasy_team_id} player={self.player_id}>"


class ScoringPeriod(IntPk, TimestampMixin, Base):
    """One scoring period — in H2H, a fantasy week.

    This is the league-scoped calendar. The plan also lists a schedule-side
    ``week_definitions``; see ``schedule.py`` for why that was not built as a
    second table.
    """

    __tablename__ = "scoring_periods"
    __table_args__ = (
        UniqueConstraint("league_id", "period_number", name="uq_scoring_periods_number"),
        CheckConstraint("end_date >= start_date", name="period_dates_ordered"),
        Index("ix_scoring_periods_league_dates", "league_id", "start_date", "end_date"),
    )

    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    period_number: Mapped[int] = mapped_column()
    label: Mapped[str | None] = mapped_column(String(48))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    #: The weeks that decide the season. Flagged here so playoff schedule
    #: strength is a query during the draft, not a March discovery.
    is_playoff: Mapped[bool] = mapped_column(default=False, index=True)

    league: Mapped[League] = relationship(back_populates="scoring_periods")
    matchups: Mapped[list[Matchup]] = relationship(
        back_populates="scoring_period", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ScoringPeriod {self.league_id}#{self.period_number}>"


class Matchup(IntPk, TimestampMixin, Base):
    """A head-to-head matchup within a scoring period."""

    __tablename__ = "matchups"
    __table_args__ = (
        UniqueConstraint("scoring_period_id", "home_team_id", name="uq_matchups_period_home"),
        CheckConstraint("home_team_id <> away_team_id", name="distinct_fantasy_teams"),
    )

    scoring_period_id: Mapped[int] = mapped_column(
        ForeignKey("scoring_periods.id", ondelete="CASCADE"), index=True
    )
    home_team_id: Mapped[int] = mapped_column(
        ForeignKey("fantasy_teams.id", ondelete="CASCADE"), index=True
    )
    away_team_id: Mapped[int] = mapped_column(
        ForeignKey("fantasy_teams.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[MatchupStatus] = mapped_column(
        portable_enum(MatchupStatus, "matchup_status"), default=MatchupStatus.SCHEDULED
    )
    home_category_wins: Mapped[int | None] = mapped_column()
    away_category_wins: Mapped[int | None] = mapped_column()
    category_ties: Mapped[int | None] = mapped_column()

    scoring_period: Mapped[ScoringPeriod] = relationship(back_populates="matchups")
    home_team: Mapped[FantasyTeam] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[FantasyTeam] = relationship(foreign_keys=[away_team_id])
    category_results: Mapped[list[MatchupCategoryResult]] = relationship(
        back_populates="matchup", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Matchup {self.home_team_id} v {self.away_team_id}>"


class MatchupCategoryResult(IntPk, TimestampMixin, Base):
    """Per-category state of a matchup.

    ``category_key`` is stored rather than a foreign key to a scoring category,
    because a result is a historical fact and must survive the league moving to
    a new scoring profile version.

    ``kind`` is denormalised alongside it for the same reason, and it is what
    makes the ratio guarantee enforceable: the table cannot consult the profile
    to discover that ``fg_pct`` is a ratio, so it carries that fact itself and
    a CHECK requires the components to be present. Without it, Fantrax's
    matchup feed — which supplies ``.478`` directly — makes the path of least
    resistance in Phase 2 ingest a stored raw percentage with no denominator,
    which is precisely risk R9.
    """

    __tablename__ = "matchup_category_results"
    __table_args__ = (
        UniqueConstraint("matchup_id", "category_key", name="uq_matchup_cat_results_key"),
        CheckConstraint(
            "kind = 'counting' OR ("
            "home_numerator IS NOT NULL AND home_denominator IS NOT NULL "
            "AND away_numerator IS NOT NULL AND away_denominator IS NOT NULL)",
            name="ratio_components_present",
        ),
        CheckConstraint(
            "category_key NOT IN ('fg_pct', 'ft_pct', 'fg3_pct', 'ts_pct', 'efg_pct') "
            "OR kind = 'ratio'",
            name="percentage_keys_are_ratios",
        ),
    )

    matchup_id: Mapped[int] = mapped_column(
        ForeignKey("matchups.id", ondelete="CASCADE"), index=True
    )
    category_key: Mapped[str] = mapped_column(String(32))
    #: Denormalised from the scoring category that was in force at the time.
    kind: Mapped[CategoryKind] = mapped_column(
        portable_enum(CategoryKind, "category_kind"), default=CategoryKind.COUNTING
    )
    home_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    away_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    home_numerator: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    home_denominator: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    away_numerator: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    away_denominator: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    outcome: Mapped[CategoryOutcome | None] = mapped_column(
        portable_enum(CategoryOutcome, "category_outcome")
    )

    matchup: Mapped[Matchup] = relationship(back_populates="category_results")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<MatchupCategoryResult {self.matchup_id} {self.category_key}>"


class Transaction(IntPk, TimestampMixin, Base):
    """A league transaction: add, drop, waiver claim, trade leg, draft pick.

    One row per player movement rather than per transaction envelope. A trade
    is several rows sharing a ``group_key``, which keeps the table uniform and
    still lets a multi-player deal be reassembled.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("league_id", "fantrax_transaction_id", name="uq_transactions_fantrax_id"),
        Index("ix_transactions_league_date", "league_id", "occurred_on"),
        Index("ix_transactions_group", "league_id", "group_key"),
    )

    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    fantrax_transaction_id: Mapped[str | None] = mapped_column(String(64))
    #: Shared by every leg of one logical transaction.
    group_key: Mapped[str | None] = mapped_column(String(64))
    transaction_type: Mapped[TransactionType] = mapped_column(
        portable_enum(TransactionType, "transaction_type")
    )
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    player_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL"), index=True
    )
    from_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("fantasy_teams.id", ondelete="SET NULL")
    )
    to_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("fantasy_teams.id", ondelete="SET NULL")
    )
    bid_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    notes: Mapped[str | None] = mapped_column(Text)

    player: Mapped[Player | None] = relationship()
    from_team: Mapped[FantasyTeam | None] = relationship(foreign_keys=[from_team_id])
    to_team: Mapped[FantasyTeam | None] = relationship(foreign_keys=[to_team_id])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Transaction {self.transaction_type} player={self.player_id}>"
