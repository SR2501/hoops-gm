"""The NBA official injury report: raw per-report status history.

**This is the observed record only**, in exactly the sense
``db.models.availability`` already establishes for ``player_participation``:
ingest owns what the report said, and the empirical conversion of a status to
an actual play rate (``injury-status-conversion``, ``docs/backlog.md``) is a
modelled quantity that belongs to `quant` in a later phase. Nothing here
computes ``p(play)``.

**One row per report per player, not one row per player.** The report is
published the evening before a game and updated through game day, and a
player's designation genuinely changes between captures — "Questionable" at
5pm becomes "Out" at game time, and that trajectory is exactly what
``injury-status-conversion`` needs to model. Overwriting a player's row on
each new capture would destroy the one thing this table exists to keep:
history. ``report_timestamp`` is therefore part of the natural key, not merely
a column.

**``game_date`` is also part of the natural key, not merely a column.** One
report capture's "rolling window" genuinely names the same player on the same
team twice, once per calendar date, when that team plays a back-to-back the
very next night — the same masthead lists both games. Without ``game_date``
in the key, the second night's row collided with the first night's under
``(report_timestamp, team_raw, player_name_raw)`` alone and silently
overwrote it as an ordinary update, destroying one of the two distinct
player-games this row is supposed to distinguish. This was found by
independent review before it corrupted any evidence relied upon downstream.

**Deliberately not versioned like ``opponent_context``/``off_night_slates``.**
ADR-009 draws the line between ``schedule-ingest`` (data-engineer, ingested
fact, Adapter gate) and ``schedule-context`` (quant, modelled output, Model
gate + ``model_version``/``schedule_version`` cascade). This table is the
injury-report analogue of ``team_schedule``, not of ``opponent_context``: it
carries no model version because it asserts nothing beyond what the league
published. A future model consuming this table is where that cascade applies,
not here.

**``import_schema_version`` distinguishes rows written under the fixed
natural key from rows that predate it.** Migration 0013 fixed a real
back-to-back collision (see above); any row whose *last write* predates
migration 0014 cannot be trusted to be free of that collision after the
fact — the overwrite, if it happened, already destroyed the evidence that
would prove it. Those rows are stamped ``LEGACY_EVIDENCE_SCHEMA_VERSION``
(``1``); every row the fixed importer creates or updates from migration
0014 onward is stamped ``CURRENT_EVIDENCE_SCHEMA_VERSION`` (``2``). A
canonical-observation query defaults to excluding version-1 rows rather
than silently trusting them — see
``injury_report.backfill.select_canonical_pregame_observations``.

**``player_id`` and ``game_id`` are best-effort and nullable.** The report
names a player by "Last, First" text and a game by a two-team tricode
matchup, not by any id this project controls. Resolution follows the same
name+team evidence approach as the rest of the crosswalk (``hoops_gm.identity
.names``), but an unresolved link must not become a fabricated one, and the
raw text is retained on every row regardless of whether it resolved — the same
reason ``player_participation.raw_comment`` is never dropped.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import Date, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hoops_gm.db.base import Base, IntPk, TimestampMixin, UTCDateTime, portable_enum
from hoops_gm.db.models.enums import ExternalSource, InjuryReportStatus

if TYPE_CHECKING:
    from hoops_gm.db.models.identity import NbaTeam, Player
    from hoops_gm.db.models.stats import NbaGame

#: The evidence-schema version a row was *last written under*. ``1`` is any
#: row whose most recent write predates migration 0014 — practically, any
#: row that has never been re-imported by the natural-key-fixed importer
#: (migration 0013 + the corresponding ``import_injury_report_entries``
#: fix). Those rows cannot be algorithmically distinguished after the fact
#: from a row that genuinely never collided under the old 3-column key —
#: the collision, if one happened, already silently overwrote its victim
#: before this column existed to say so. ``2`` (:data:`CURRENT_EVIDENCE_SCHEMA_VERSION`)
#: is written by every row the fixed importer creates or touches going
#: forward. A canonical-observation query defaults to excluding version-1
#: rows for exactly this reason — see
#: ``injury_report.backfill.select_canonical_pregame_observations``.
LEGACY_EVIDENCE_SCHEMA_VERSION: Final = 1
CURRENT_EVIDENCE_SCHEMA_VERSION: Final = 2


class InjuryReportEntry(IntPk, TimestampMixin, Base):
    """One player's designation on one captured NBA official injury report."""

    __tablename__ = "injury_report_entries"
    __table_args__ = (
        # The natural key of one report capture: the same report published at
        # the same timestamp names the same player for the same team on the
        # same game date at most once. This is what makes re-ingesting an
        # already-captured report an idempotent no-op rather than a
        # duplicate. ``game_date`` is part of this key, not merely
        # ``(report_timestamp, team_raw, player_name_raw)`` — a single report
        # capture's "rolling window" genuinely lists the same player on the
        # same team twice when that team plays a back-to-back covered by one
        # masthead (verified live: a report's window spans two calendar game
        # dates). Without ``game_date`` in the key, the second night's row for
        # that player silently overwrote the first night's as an ordinary
        # "update", destroying one of the two distinct player-games under the
        # same key. Found by independent review of the historical-backfill
        # PR before any evidence relying on it was trusted.
        UniqueConstraint(
            "report_timestamp",
            "team_raw",
            "player_name_raw",
            "game_date",
            name="uq_injury_report_entries_report_team_player_date",
        ),
        Index("ix_injury_report_entries_player_report", "player_id", "report_timestamp"),
    )

    #: When the NBA published this capture of the report (its own "Injury
    #: Report: MM/DD/YY HH:MM (AM|PM)" masthead, converted from the Eastern
    #: wall clock it is printed in). Part of the natural key: a re-fetch of
    #: the identical published report must not create a second row, but a
    #: later capture of a *different* report timestamp is real history.
    report_timestamp: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    game_date: Mapped[date] = mapped_column(Date, index=True)
    #: The report's own "Game Time" column, exactly as printed
    #: (``"05:00 (ET)"``). Not parsed into an instant: the report states a
    #: scheduled tip-off, not a fact this ingest is positioned to correct
    #: against ``nba_games.tipoff_utc``, and collapsing the two would let a
    #: postponement or a schedule change silently overwrite what the report
    #: actually said.
    game_time_raw: Mapped[str] = mapped_column(String(32))
    #: The two-tricode "Matchup" column, e.g. ``"SAC@MIL"`` (away@home).
    matchup_raw: Mapped[str] = mapped_column(String(16))
    #: The report's own "Team" column, e.g. ``"Sacramento Kings"`` — a full
    #: name, not a tricode, and part of the natural key precisely because two
    #: teams in the same matchup could otherwise collide on player name alone.
    team_raw: Mapped[str] = mapped_column(String(64))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("nba_teams.id"), index=True)
    #: Best-effort link to the specific game, resolved from the matchup
    #: tricodes plus ``game_date`` against already-ingested schedule facts.
    #: ``NULL`` when the game has not been ingested yet or the matchup could
    #: not be resolved to two known teams; never guessed.
    game_id: Mapped[int | None] = mapped_column(
        ForeignKey("nba_games.id", ondelete="SET NULL"), index=True
    )
    #: "Last, First" exactly as the report printed it. Retained regardless of
    #: whether ``player_id`` resolved, for the same reason
    #: ``player_external_ids.external_name`` is retained: it is the evidence a
    #: disputed or later match is checked against.
    player_name_raw: Mapped[str] = mapped_column(String(128))
    #: Best-effort crosswalk link. ``NULL`` for an unresolved name — including
    #: every ``NOT_YET_SUBMITTED`` row, which names no player at all — and a
    #: null here is not evidence the player does not exist.
    player_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL"), index=True
    )
    #: The "Current Status" column, exactly as printed (``"Out"``,
    #: ``"Available"``, ...).
    status_raw: Mapped[str] = mapped_column(String(32))
    status: Mapped[InjuryReportStatus] = mapped_column(
        portable_enum(InjuryReportStatus, "injury_report_status")
    )
    #: The "Reason" column, exactly as printed, including a wrapped multi-line
    #: reason rejoined with spaces. House rule: do not trust a stated reason —
    #: this is retained as evidence, not treated as a fact about the injury.
    reason_raw: Mapped[str] = mapped_column(Text, default="")

    source: Mapped[ExternalSource] = mapped_column(
        portable_enum(ExternalSource, "external_source"), default=ExternalSource.NBA
    )
    #: The exact PDF URL this row was captured from, so a disputed row can be
    #: traced back to the raw capture in ``RawPayloadStore``.
    source_url: Mapped[str] = mapped_column(String(255))
    #: See :data:`CURRENT_EVIDENCE_SCHEMA_VERSION` / :data:`LEGACY_EVIDENCE_SCHEMA_VERSION`.
    #: Migration 0014 stamps every row that existed before it ran with ``1``;
    #: the importer always writes ``CURRENT_EVIDENCE_SCHEMA_VERSION`` on
    #: every create *and* every update from this point forward, so a legacy
    #: row is automatically upgraded the next time a real re-import touches
    #: it under the fixed key.
    import_schema_version: Mapped[int] = mapped_column(
        SmallInteger,
        default=CURRENT_EVIDENCE_SCHEMA_VERSION,
        server_default=str(CURRENT_EVIDENCE_SCHEMA_VERSION),
    )

    team: Mapped[NbaTeam | None] = relationship(foreign_keys=[team_id])
    game: Mapped[NbaGame | None] = relationship(foreign_keys=[game_id])
    player: Mapped[Player | None] = relationship(foreign_keys=[player_id])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<InjuryReportEntry {self.player_name_raw!r} {self.status_raw!r} "
            f"@{self.report_timestamp.isoformat()}>"
        )
