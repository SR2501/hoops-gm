"""What the participation ledger actually holds, and which store it was read from.

**Every count this module produces is attached to the store it came from, and
that is not a formatting nicety — it is the whole point of the module.** On
2026-08-22 two reports about `player_participation` sat on `main` at the same
time: one said 43,037 rows, the other said 0. Both were correct. They had
queried two different SQLite files that share the basename ``hoops_gm.db``,
because :func:`hoops_gm.core.config.Settings._resolve_relative_sqlite_path`
anchors the default relative path to *each checkout's own repo root*, so every
worktree resolves ``sqlite:///./hoops_gm.db`` to a different file. Neither
report named the path it read, so neither could be checked and the two could
not be reconciled without re-deriving both.

:class:`LedgerCoverage` makes that specific mistake inexpressible: there is no
public way to obtain a count from this module without also obtaining the
:class:`StoreIdentity` it was measured from. They are fields of one frozen
record, produced by one function, rendered together.

**Scope: this is substrate, not a model.** Everything here is a descriptive
count of rows that exist in a table. Nothing is fitted, nothing is projected,
and no draft, lineup or trade decision rests on any number returned from here —
``p(play)`` and everything derived from it are `quant`'s, gated separately by
the Model gate. What this module *is* for is answering the question that has to
be settled before any of that work can honestly start: is the ledger populated,
from which store, and where are its holes.

**An unobserved game is reported, not omitted.** The distinction between "he
did not play" and "we have no observation" is the one the whole availability
thesis rests on, so a ``final`` game carrying no participation rows is counted
as :attr:`SeasonCoverage.games_unobserved` and its dates are listed. A coverage
report that silently skipped those would read as complete precisely when it was
not.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Column, MetaData, String, Table, func, inspect, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from hoops_gm.db.models.availability import PlayerParticipation
from hoops_gm.db.models.enums import GameStatus
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog
from hoops_gm.db.session import render_store_url

__all__ = [
    "LedgerCoverage",
    "LedgerSchemaMissing",
    "SeasonCoverage",
    "StoreIdentity",
    "measure_coverage",
]

#: Tables without which no coverage statement can be made at all.
_REQUIRED_TABLES = ("nba_games", "player_participation")


class LedgerSchemaMissing(RuntimeError):
    """The configured store has no participation schema to measure.

    Raised in preference to letting a bare ``no such table`` propagate. The
    two are the same fact, but this one names the store, and an operator
    running a coverage check is asking a question about a *specific database* —
    an unnamed traceback is what turns "you are pointed at the wrong file" into
    an afternoon. It is also the single most likely first experience of this
    tool, because a fresh worktree resolves the default relative SQLite URL to
    its own empty file.
    """

    def __init__(self, store: StoreIdentity, missing: Sequence[str]) -> None:
        self.store = store
        self.missing = tuple(missing)
        super().__init__(
            f"no participation schema in {store.describe()}: "
            f"missing {', '.join(self.missing)}. "
            f"Run `alembic upgrade head` against it, or set DATABASE_URL to the "
            f"store that holds the ledger."
        )


#: Dates listed individually for an unobserved-game report. Beyond this the
#: report says how many were suppressed rather than printing a season.
_MAX_LISTED_GAP_DATES = 25


@dataclass(frozen=True, slots=True)
class StoreIdentity:
    """Which database a set of counts was read from.

    ``url`` is rendered with the password hidden, so this record is safe to
    print into a log, a CI summary or a handoff entry. ``local_path`` is the
    resolved absolute path when the store is a local file, and it is the field
    that would have settled the 2026-08-22 contradiction on sight.
    """

    url: str
    dialect: str
    local_path: str | None
    alembic_revision: str | None

    @classmethod
    def of(cls, engine: Engine) -> StoreIdentity:
        """Describe the store behind ``engine``, without exposing a password."""
        safe_url, local_path = render_store_url(engine.url)
        return cls(
            url=safe_url,
            dialect=engine.dialect.name,
            local_path=local_path,
            alembic_revision=_alembic_revision(engine),
        )

    def describe(self) -> str:
        """One line naming the store, for a header above any count."""
        where = self.local_path or self.url
        revision = self.alembic_revision or "no alembic_version row"
        return f"{where}  [{self.dialect}, schema {revision}]"


@dataclass(frozen=True, slots=True)
class SeasonCoverage:
    """Ledger coverage for one season, in the store named by the parent record."""

    season: str
    games_total: int
    games_final: int
    games_observed: int
    games_unobserved: int
    unobserved_dates: tuple[str, ...]
    unobserved_dates_suppressed: int
    rows: int
    distinct_players: int
    box_score_rows: int
    outcomes: dict[str, int]
    reasons: dict[str, int]
    rows_with_inactive_list: int

    @property
    def observed_fraction(self) -> float:
        """Share of ``final`` games carrying at least one participation row."""
        if self.games_final == 0:
            return 0.0
        return self.games_observed / self.games_final

    @property
    def is_complete(self) -> bool:
        """True when every ``final`` game in this season has been observed."""
        return self.games_final > 0 and self.games_unobserved == 0


@dataclass(frozen=True, slots=True)
class LedgerCoverage:
    """Participation-ledger coverage, inseparable from the store it was read from.

    Construct via :func:`measure_coverage`. There is deliberately no path to a
    count in this module that does not carry :attr:`store` alongside it.
    """

    store: StoreIdentity
    seasons: tuple[SeasonCoverage, ...] = field(default_factory=tuple)
    #: Distinct players across the whole ledger. Deliberately measured rather
    #: than summed from :attr:`seasons`: a player appearing in two seasons is
    #: one player here and two there, and summing would double count him.
    distinct_players: int = 0

    @property
    def rows(self) -> int:
        return sum(season.rows for season in self.seasons)

    @property
    def games_observed(self) -> int:
        return sum(season.games_observed for season in self.seasons)

    @property
    def games_unobserved(self) -> int:
        return sum(season.games_unobserved for season in self.seasons)

    @property
    def games_final(self) -> int:
        return sum(season.games_final for season in self.seasons)

    @property
    def is_populated(self) -> bool:
        """True when the ledger holds at least one participation row."""
        return self.rows > 0

    def render(self) -> str:
        """A human-readable report whose first line is always the store."""
        lines = [
            "Participation ledger coverage",
            f"  store: {self.store.describe()}",
            "",
        ]
        if not self.seasons:
            lines.append("  NO PARTICIPATION ROWS, AND NO GAMES, IN THIS STORE.")
            return "\n".join(lines)

        for season in self.seasons:
            lines.append(f"  {season.season}")
            lines.append(
                f"    games        : {season.games_observed} observed / "
                f"{season.games_final} final ({season.observed_fraction:.1%})"
                f" of {season.games_total} total"
            )
            if season.games_unobserved:
                listed = ", ".join(season.unobserved_dates)
                suffix = (
                    f" (+{season.unobserved_dates_suppressed} more)"
                    if season.unobserved_dates_suppressed
                    else ""
                )
                lines.append(
                    f"    UNOBSERVED   : {season.games_unobserved} final games "
                    f"with no participation row: {listed}{suffix}"
                )
            lines.append(
                f"    rows         : {season.rows} over "
                f"{season.distinct_players} players "
                f"({season.box_score_rows} box scores)"
            )
            lines.append(
                f"    inactive list: offered by the source for "
                f"{season.rows_with_inactive_list} of {season.rows} rows"
            )
            lines.append("")

        lines.append(
            f"  TOTAL: {self.rows} rows, {self.distinct_players} distinct players, "
            f"{self.games_observed}/{self.games_final} final games observed"
        )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Outcome-safe JSON form, store included, for attaching as evidence.

        Outcome and reason marginals remain available on the in-memory
        :class:`SeasonCoverage` for private audits. They are deliberately absent
        from public serialization while the injury-status conversion protocol
        remains blinded. There is no opt-in flag.
        """
        return {
            "store": asdict(self.store),
            "seasons": [
                {
                    "season": season.season,
                    "games_total": season.games_total,
                    "games_final": season.games_final,
                    "games_observed": season.games_observed,
                    "games_unobserved": season.games_unobserved,
                    "unobserved_dates": list(season.unobserved_dates),
                    "unobserved_dates_suppressed": season.unobserved_dates_suppressed,
                    "rows": season.rows,
                    "distinct_players": season.distinct_players,
                    "box_score_rows": season.box_score_rows,
                    "rows_with_inactive_list": season.rows_with_inactive_list,
                }
                for season in self.seasons
            ],
            "totals": {
                "rows": self.rows,
                "distinct_players": self.distinct_players,
                "games_final": self.games_final,
                "games_observed": self.games_observed,
                "games_unobserved": self.games_unobserved,
                "is_populated": self.is_populated,
            },
        }


#: Minimal Core description of Alembic's stamp table. Declared here rather than
#: reached for with raw driver SQL, so the read goes through SQLAlchemy like
#: every other query (ADR-001) and cannot hide a dialect difference.
_ALEMBIC_VERSION = Table(
    "alembic_version", MetaData(), Column("version_num", String(32), nullable=False)
)


def _alembic_revision(engine: Engine) -> str | None:
    """The applied migration revision, or None when the table is absent.

    Absence is reported as ``None`` rather than raising: a store with no
    ``alembic_version`` is a real and interesting state (an unmigrated or
    hand-built file), and the caller should be told which it is.
    """
    if not inspect(engine).has_table("alembic_version"):
        return None
    with engine.connect() as connection:
        row = connection.execute(select(_ALEMBIC_VERSION.c.version_num)).first()
    if row is None:
        return None
    return str(row[0])


def _count_by(session: Session, column: Any, season: str) -> dict[str, int]:
    """Counts of ``column`` for one season, largest first."""
    stmt = (
        select(column, func.count())
        .join(NbaGame, PlayerParticipation.game_id == NbaGame.id)
        .where(NbaGame.season == season)
        .group_by(column)
        .order_by(func.count().desc())
    )
    return {str(value): int(count) for value, count in session.execute(stmt)}


def measure_coverage(session: Session, *, seasons: Sequence[str] | None = None) -> LedgerCoverage:
    """Measure the participation ledger in the store behind ``session``.

    The store identity is taken from the session's own bind rather than from a
    caller-supplied label, so the path reported is necessarily the path read.
    A label passed in by hand is exactly the thing that was wrong on
    2026-08-22.
    """
    bind = session.get_bind()
    if not isinstance(bind, Engine):  # pragma: no cover - defensive
        raise TypeError("measure_coverage needs a session bound to an Engine")
    store = StoreIdentity.of(bind)

    # Assert the tables are present rather than inferring their state from a
    # query that happens not to raise. An absence check that succeeds
    # identically whether or not the thing existed proves nothing.
    present = set(inspect(bind).get_table_names())
    missing = [name for name in _REQUIRED_TABLES if name not in present]
    if missing:
        raise LedgerSchemaMissing(store, missing)

    if seasons is None:
        season_rows = session.execute(
            select(NbaGame.season).distinct().order_by(NbaGame.season)
        ).all()
        seasons = [str(row[0]) for row in season_rows]

    measured: list[SeasonCoverage] = []
    for season in seasons:
        measured.append(_measure_one_season(session, season))

    distinct_players = int(
        session.execute(
            select(func.count(func.distinct(PlayerParticipation.player_id)))
        ).scalar_one()
    )

    return LedgerCoverage(
        store=store,
        seasons=tuple(measured),
        distinct_players=distinct_players,
    )


def _measure_one_season(session: Session, season: str) -> SeasonCoverage:
    games_total = int(
        session.execute(
            select(func.count()).select_from(NbaGame).where(NbaGame.season == season)
        ).scalar_one()
    )

    final_games = select(NbaGame.id).where(
        NbaGame.season == season, NbaGame.status == GameStatus.FINAL
    )
    games_final = int(
        session.execute(select(func.count()).select_from(final_games.subquery())).scalar_one()
    )

    observed_game_ids = select(PlayerParticipation.game_id).distinct()
    games_observed = int(
        session.execute(
            select(func.count()).select_from(
                final_games.where(NbaGame.id.in_(observed_game_ids)).subquery()
            )
        ).scalar_one()
    )

    # Listed explicitly: a gap the report does not name is a gap nobody chases.
    gap_rows = session.execute(
        select(NbaGame.game_date)
        .where(
            NbaGame.season == season,
            NbaGame.status == GameStatus.FINAL,
            NbaGame.id.not_in(observed_game_ids),
        )
        .order_by(NbaGame.game_date)
    ).all()
    gap_dates = [_render_date(row[0]) for row in gap_rows]

    rows = int(
        session.execute(
            select(func.count())
            .select_from(PlayerParticipation)
            .join(NbaGame, PlayerParticipation.game_id == NbaGame.id)
            .where(NbaGame.season == season)
        ).scalar_one()
    )
    distinct_players = int(
        session.execute(
            select(func.count(func.distinct(PlayerParticipation.player_id)))
            .select_from(PlayerParticipation)
            .join(NbaGame, PlayerParticipation.game_id == NbaGame.id)
            .where(NbaGame.season == season)
        ).scalar_one()
    )
    box_score_rows = int(
        session.execute(
            select(func.count())
            .select_from(PlayerGameLog)
            .join(NbaGame, PlayerGameLog.game_id == NbaGame.id)
            .where(NbaGame.season == season)
        ).scalar_one()
    )
    rows_with_inactive_list = int(
        session.execute(
            select(func.count())
            .select_from(PlayerParticipation)
            .join(NbaGame, PlayerParticipation.game_id == NbaGame.id)
            .where(NbaGame.season == season, PlayerParticipation.inactive_list_available.is_(True))
        ).scalar_one()
    )

    return SeasonCoverage(
        season=season,
        games_total=games_total,
        games_final=games_final,
        games_observed=games_observed,
        games_unobserved=games_final - games_observed,
        unobserved_dates=tuple(gap_dates[:_MAX_LISTED_GAP_DATES]),
        unobserved_dates_suppressed=max(0, len(gap_dates) - _MAX_LISTED_GAP_DATES),
        rows=rows,
        distinct_players=distinct_players,
        box_score_rows=box_score_rows,
        outcomes=_count_by(session, PlayerParticipation.outcome, season),
        reasons=_count_by(session, PlayerParticipation.reason, season),
        rows_with_inactive_list=rows_with_inactive_list,
    )


def _render_date(value: object) -> str:
    """Render a game date, tolerating a driver that returns a string."""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - operator tool
    """``python -m hoops_gm.availability.coverage``."""
    import argparse

    from hoops_gm.core.config import get_settings
    from hoops_gm.db.session import Database, absent_store_refusal

    parser = argparse.ArgumentParser(
        description=(
            "Report participation-ledger coverage for the configured store. "
            "The store's resolved path is printed with every count; set "
            "DATABASE_URL to point this at a store other than this checkout's."
        )
    )
    parser.add_argument("--season", action="append", dest="seasons", default=None)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args(argv)

    settings = get_settings()

    # Refuse before connecting. Not because an invented store would report a
    # false zero — driven 2026-08-23, an absent path yields an *unmigrated*
    # file that fails loudly on the first query — but because the resulting
    # error blames the schema when the fault is the path, and because a report
    # should not litter the filesystem with the subject it was asked about.
    refusal = absent_store_refusal(settings.database_url)
    if refusal is not None:
        print(refusal)
        return 2

    database = Database.from_settings(settings)
    try:
        with database.session() as session:
            coverage = measure_coverage(session, seasons=args.seasons)
    except LedgerSchemaMissing as exc:
        print(f"ERROR: {exc}")
        return 2
    except SQLAlchemyError as exc:
        # Unreachable is *not* empty, and without this they were the same
        # signal: an uncaught exception exits 1, which is this tool's
        # documented code for "reachable but empty". Driven against a
        # nonexistent Postgres database, which refuses rather than creating
        # one — so a server-backed store cannot invent a false zero, but it
        # could still report one through the exit code.
        safe_url, _ = render_store_url(make_url(settings.database_url))
        print(f"ERROR: could not read {safe_url}: {exc}")
        return 2
    finally:
        database.dispose()

    print(json.dumps(coverage.to_dict(), indent=2) if args.json else coverage.render())
    # Exit 1 means the store was read and holds nothing — never that it could
    # not be read. See the SQLAlchemyError branch above.
    return 0 if coverage.is_populated else 1


if __name__ == "__main__":  # pragma: no cover - operator tool
    raise SystemExit(main())
