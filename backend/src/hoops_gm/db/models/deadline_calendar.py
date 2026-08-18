"""League deadline calendars: the versioned join of settings lineage and schedule lineage.

`deadline-model` (docs/backlog.md) was originally scoped to *compute* every
future deadline from ingested settings — lineup lock, waiver cutoffs, a
games-cap threshold, the trade deadline, playoff roster deadlines, keeper
cutoffs. `league-settings-ingest` already discovered, against the real
``getLeagueInfo`` endpoint, that Fantrax's official surface supplies only
roster limits and scoring-period boundaries; every other timing rule is
absent from every source observed so far and can only become known through
the existing, source-attributed read-only bridge capture (see
``hoops_gm.ingest.league_settings``'s module docstring) — never from
``docs/league/2025-26-rules-baseline.md``, which is explicitly historical
reference only.

So this table is not the deadline calculator the backlog originally
envisioned. It is the smallest honest calendar contract buildable today: one
immutable, versioned row per league joining an exact
:class:`~hoops_gm.db.models.league_settings.LeagueSettingsSnapshot` with an
exact schedule refresh cohort (``hoops_gm.db.lineage``'s ``RefreshRun`` with
``artifact_type=SCHEDULE``), exposing the two concerns those two sources
actually verify — season bounds and scoring-period boundaries, each carried as
a real timezone-aware instant rather than a naive reinterpretation — while
carrying every other timing rule forward as an explicit unknown with its
evidence trail intact.

**Not a second ``league.ScoringPeriod``.** That table is already, by its own
docstring, "the league-scoped calendar" — deliberately singular so a
schedule-side week table can never disagree with it. This table does not
compete for that role: ``scoring_periods`` here is not a second source of
truth, it is a verbatim, versioned pass-through of whatever
``LeagueSettingsSnapshot.settings.scoring_periods`` already said (which is
itself already JSON, not a second set of typed columns) plus the schedule
lineage it was joined against. ``ScoringPeriod`` has no writer yet — grep
finds no importer — and widening its ``Date`` columns to carry a
timezone-aware instant (the settings payload's boundaries cross a DST
transition inside a single season) is a separate, later decision for whoever
first wires up its population, not something this table's existence
prejudges.

**The override seam.** The only legitimate path for trade deadline, waiver
timing, lineup locks, playoff flags or keeper deadlines to become known is
the existing bridge capture at the settings-ingest boundary. This table adds
no second override path of its own: ``unsupported_rules`` is a verbatim copy
of the settings snapshot's own ``SourcedSetting`` value/evidence pairs, never
a value invented at this layer.

**Immutable, versioned, and independently activatable.** Same discipline as
``LeagueSettingsSnapshot``: deriving again over unchanged lineage returns the
existing row (see ``hoops_gm.calendar.deadline_calendar``); new lineage opens
the next ``version``. ``current_for_league`` is the same portable "current
marker" technique as ``PlayerExternalId.current_for_source``
(identity.py) — it holds the row's own ``league_id`` while active and
``NULL`` once superseded, with a plain unique constraint rather than a
partial/dialect-specific index, so a league has at most one current calendar
and A -> B -> A activation is just repointing the marker (subject to the
lineage-currency re-check described in the service module).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, Date, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hoops_gm.db.base import Base, IntPk, TimestampMixin, UTCDateTime

if TYPE_CHECKING:
    from hoops_gm.db.models.league import League
    from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot


class LeagueDeadlineCalendar(IntPk, TimestampMixin, Base):
    """One immutable, versioned calendar derived from exact settings + schedule lineage.

    ``scoring_periods`` is a JSON list of
    ``{period_number, start_at, end_at, is_playoff}``, ``start_at``/``end_at``
    copied verbatim (as parsed, timezone-aware ISO strings) from the settings
    snapshot's own scoring-period boundaries and ``is_playoff`` set from the
    settings' playoff period numbers when known, or left ``None`` — never
    ``False`` — when the source never supplied a playoff marker. No period
    count or cadence is assumed: an All-Star combined week, or any other
    non-uniform gap the source actually reported, passes through unchanged.

    ``unsupported_rules`` carries ``lineup_lock``, ``waivers``,
    ``trade_deadline``, ``keepers`` and ``playoffs`` as their raw
    ``{value, evidence}`` pairs from the settings document — "unsupported"
    describes what the primary official source structurally does not expose,
    not that the value is necessarily unknown, since a bridge-sourced value
    already flows through the settings snapshot this table joins against.

    Never updated in place: new lineage (a new settings version or a new
    schedule refresh) is the next ``version`` row.
    """

    __tablename__ = "league_deadline_calendars"
    __table_args__ = (
        UniqueConstraint("league_id", "version", name="uq_league_deadline_calendars_version"),
        UniqueConstraint("current_for_league", name="uq_league_deadline_calendars_current"),
        UniqueConstraint(
            "league_id",
            "settings_snapshot_id",
            "schedule_version",
            name="uq_league_deadline_calendars_lineage",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("season_end_date >= season_start_date", name="season_dates_ordered"),
        CheckConstraint(
            "current_for_league IS NULL OR current_for_league = league_id",
            name="current_marker_matches_league",
        ),
        Index("ix_league_deadline_calendars_league_season", "league_id", "season"),
    )

    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    #: Monotonically assigned by the deriving service, starting at 1.
    version: Mapped[int] = mapped_column(default=1)
    #: Holds this row's own ``league_id`` while it is the league's current
    #: calendar, ``NULL`` once superseded or never activated. See the module
    #: docstring for why this is a plain unique column rather than a partial
    #: index.
    current_for_league: Mapped[int | None] = mapped_column()
    #: Names the shape of ``scoring_periods``/``unsupported_rules``,
    #: independent of ``version`` — see ``LeagueSettingsSnapshot`` for the
    #: same distinction.
    schema_version: Mapped[str] = mapped_column(String(32))
    season: Mapped[str] = mapped_column(String(9), index=True)

    settings_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey(
            "league_settings_snapshots.id",
            ondelete="CASCADE",
            # Explicit, shortened name: the naming convention's generated
            # name exceeds Postgres's 63-character identifier limit for this
            # table/column/referent combination — see test_portability.py.
            name="fk_league_deadline_calendars_settings_snapshot_id",
        ),
        index=True,
    )
    #: Denormalized for a cheap "what lineage is this" read without a join.
    settings_snapshot_version: Mapped[int] = mapped_column()
    #: The schedule refresh cohort's own content fingerprint
    #: (``hoops_gm.db.lineage``). No foreign key to ``refresh_runs``: that
    #: registry is a global, league-independent artifact log, not a child of
    #: any one league, so this table denormalizes exactly what it needs —
    #: same technique as ``AbsenceSplitComputationRun`` (availability.py).
    schedule_version: Mapped[str] = mapped_column(String(64))
    schedule_refreshed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    #: Verbatim from the settings document's ``source_start_date``/
    #: ``source_end_date`` — plain calendar dates, never a time or timezone,
    #: because the source never supplies one for these two fields.
    season_start_date: Mapped[date] = mapped_column(Date)
    season_end_date: Mapped[date] = mapped_column(Date)
    #: ``list[{period_number, start_at, end_at, is_playoff}]`` — see the class
    #: docstring.
    scoring_periods: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    #: ``{lineup_lock, waivers, trade_deadline, keepers, playoffs}`` — see the
    #: class docstring.
    unsupported_rules: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)

    #: When this row was derived — distinct from ``created_at`` in the same
    #: way ``LeagueSettingsSnapshot.observed_at`` is distinct from it: a
    #: backfill could derive an old lineage's calendar long after the fact.
    derived_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    league: Mapped[League] = relationship(back_populates="deadline_calendars")
    settings_snapshot: Mapped[LeagueSettingsSnapshot] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LeagueDeadlineCalendar league={self.league_id} v{self.version}>"
