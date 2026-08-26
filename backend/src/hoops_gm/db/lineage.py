"""Cohort lineage service: recording refreshes and validating claimed versions.

Plain functions over a ``Session`` rather than a class — there is no state
here beyond what is in the database, the same shape ``ingest/importers.py``
already uses for idempotent writes.

**What this is not.** It does not decide which schedule, projection, or model
version *should* be current, does not compute p(play) or opponent quality, and
does not implement strength-of-schedule convergence (ADR-011). It only
registers what producers say they refreshed and reports, mechanically,
whether a caller's claimed version still matches. That decision — and the
formulation of any future model or projection — stays with the owning
specialist agent (``data-engineer`` for schedule facts, ``quant`` for
projections and models) under the Adapter/Model gates.

One exception to "only what producers say", and it is deliberate: for the NBA
schedule the registry can and does recompute the claim's baseline from the
persisted ``team_schedule`` rows (``schedule_content_version``). That is still
not a modelling judgement — it is the difference between trusting a label and
checking it against the facts it claims to describe, which is exactly the
mislabelled-field failure mode AGENTS.md's house rules call out.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session, aliased

from hoops_gm.db.models.enums import RefreshArtifactType, SeasonType
from hoops_gm.db.models.identity import NbaTeam
from hoops_gm.db.models.lineage import RefreshRun
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.db.session import acquire_transaction_lock

CohortStatus = Literal["current", "stale", "unknown"]
NBA_SCHEDULE_ARTIFACT_KEY = "nba-schedule"
SCHEDULE_CONTEXT_SOURCE_KEY = "schedule-context-observations"

#: Summary key under which a schedule refresh records what the source said and
#: what was actually persisted. Its presence is what marks a refresh as
#: verifiable against ``team_schedule``; rows without it are legacy or manual
#: registrations and are compared by version string alone.
SCHEDULE_COMPLETENESS_SUMMARY_KEY = "schedule_completeness"

#: Why a pending game carries no date. Closed on purpose: an unrecognised
#: value is a finding, not a variation, because a consumer keys behaviour on
#: these — ``not_offered`` means wait, ``unreadable`` means investigate.
_DATE_ABSENCE_REASONS: frozenset[str] = frozenset(
    {"not_offered", "unreadable", "irreconcilable", "implausible"}
)

#: Identifies the serialisation below. Bumping it deliberately invalidates
#: every previously registered schedule version, because a fingerprint is only
#: meaningful relative to the exact bytes it was computed over.
SCHEDULE_CONTENT_ALGORITHM = "team-schedule-content-v2"


class LineageSourceConflict(ValueError):
    """Two producers claim one artifact version under different sources.

    A ``ValueError`` subclass so the existing ``except ValueError`` handlers
    around lineage verification keep working; distinct so a caller that can
    genuinely reconcile two producers is able to catch just this.
    """


class _SeasonNotSpecified:
    pass


_SEASON_NOT_SPECIFIED = _SeasonNotSpecified()


def content_fingerprint(parts: Iterable[str]) -> str:
    """A short, deterministic fingerprint over an ordered sequence of strings.

    Used to derive a ``version`` label that is stable across re-runs which
    change nothing and changes whenever the underlying facts do — the same
    idempotency-by-natural-key discipline ``ingest/importers.py`` already
    applies to individual rows, applied one level up to "what does the whole
    artifact currently look like". Not a security boundary; truncated to 16
    hex characters purely to keep the label short and comparable by eye.
    """

    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:16]


# --------------------------------------------------------------------------
# Schedule cohort content
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PendingScheduleGame:
    """A game the source published with its team identities explicitly absent.

    Not a parse failure. ``ScheduleLeagueV2`` publishes the Emirates NBA Cup
    knockout fixtures before group play decides who plays in them, with
    ``teamId`` zero and every one of ``teamName``, ``teamCity``,
    ``teamTricode`` and ``teamSlug`` null. That is the source stating the
    bracket is undetermined, not the source failing to tell us something
    (ADR-013).

    Defined here rather than beside the parser because it is part of what a
    refresh row *records*, and ``db`` may not import ``ingest``. The labels
    are carried because ADR-013's "what would flip this" turns on them:
    pending only means "not yet decided" while the pending set stays
    structurally explicable, and neither a consumer nor the live smoke can
    check that against a bare list of game ids.

    **It carries no team, by definition.** A consumer may say the scoring
    period containing ``game_date`` is provisional; it may not attribute the
    game to a team, because that is the one thing the source withheld.

    ``game_date`` is ``None`` when the source's own time fields do not
    reconcile or are absent — "we do not know when", stated rather than
    guessed. A consumer must then treat the game as belonging to no known
    period rather than dropping it, because the game is still published.

    ``date_absence_reason`` says *why*. The four causes, what each one means
    for a consumer, and why they must not be collapsed are stated once in
    ADR-013's nullable-date contract; the classifier's own reasoning for
    drawing them where it does lives in
    :func:`hoops_gm.ingest.nba.schedule._pending_game_date`. The invariant
    this dataclass enforces, and the only one worth repeating here, is that
    ``game_date is None`` **iff** ``date_absence_reason`` is non-empty — the
    two halves of one fact, which must never disagree on the wire or in
    memory.
    """

    nba_game_id: str
    game_date: date | None
    game_label: str
    game_sub_label: str
    game_subtype: str
    date_absence_reason: str = ""

    def __post_init__(self) -> None:
        # The producer must not be able to construct what the reader refuses.
        # `_pending_games` enforces this iff on read-back; without it here the
        # producer type is strictly wider than the reader accepts, and
        # `as_summary()` could serialise a block that can never be read again.
        if (self.game_date is None) != bool(self.date_absence_reason):
            raise ValueError(
                f"{self.nba_game_id}: game_date "
                f"{'absent' if self.game_date is None else 'present'} with "
                f"date_absence_reason {self.date_absence_reason!r}"
            )


@dataclass(frozen=True)
class ScheduleCompleteness:
    """What the schedule source reported and what was actually persisted.

    Recorded on the refresh row so "why is this the current schedule cohort"
    is answerable from the database alone: the exact scope, the source's own
    game count, how many of those resolved to real teams, which game IDs the
    source has not yet assigned teams to, which did not resolve, and how many
    ``team_schedule`` rows exist for exactly that scope.

    Field names are the unambiguous ones on purpose.
    ``persisted_team_row_count`` counts *rows* (two per game), not games, and
    the two are easy to confuse in a hurry when the only thing distinguishing
    a correct season from a half-imported one is whether a number is 1,230 or
    2,460.

    **``pending_game_ids`` and ``unresolved_game_ids`` are not synonyms.**
    Under ADR-013 a pending game is one the source published with its team
    identities explicitly absent — an undrawn Emirates NBA Cup bracket — and
    it is recorded rather than refused. An unresolved game is a resolution
    *failure* and is still refused, so this list is empty on every registered
    refresh. The invariant is
    ``source_game_count == resolved_game_count + len(pending_game_ids)``.

    ``pending_games`` carries the same set with the date and labels a consumer
    needs to say *which* period is provisional, and to check ADR-013's
    flip condition that the pending set stays structurally explicable. It is
    cross-checked against ``pending_game_ids`` rather than derived from it at
    read time, so the two cannot silently disagree.
    """

    season: str
    season_type: SeasonType
    source_game_count: int
    resolved_game_count: int
    unresolved_game_ids: tuple[str, ...]
    persisted_team_row_count: int
    pending_games: tuple[PendingScheduleGame, ...] = ()

    @property
    def pending_game_ids(self) -> tuple[str, ...]:
        return tuple(game.nba_game_id for game in self.pending_games)

    def as_summary(self) -> dict[str, object]:
        return {
            "season": self.season,
            "season_type": self.season_type.value,
            "source_game_count": self.source_game_count,
            "resolved_game_count": self.resolved_game_count,
            "unresolved_game_ids": list(self.unresolved_game_ids),
            "pending_game_ids": list(self.pending_game_ids),
            "pending_games": [
                {
                    "nba_game_id": game.nba_game_id,
                    "game_date": game.game_date.isoformat() if game.game_date is not None else None,
                    "game_label": game.game_label,
                    "game_sub_label": game.game_sub_label,
                    "game_subtype": game.game_subtype,
                    "date_absence_reason": game.date_absence_reason,
                }
                for game in self.pending_games
            ],
            "persisted_team_row_count": self.persisted_team_row_count,
        }


def _pending_games(raw: Mapping[str, object]) -> tuple[PendingScheduleGame, ...]:
    """Read the pending block, treating its absence as "no pending games".

    A completeness block written before ADR-013 has no pending keys, and that
    is not missing information: the contract it was written under required
    ``source_game_count == resolved_game_count``, so its pending set was
    necessarily empty. Reading it as ``()`` recovers exactly what it claimed.
    A block that *does* carry the keys is held to them, in both directions —
    the ids and the records must name the same games in the same order, so a
    reader can use either without checking which one is stale.
    """

    key = SCHEDULE_COMPLETENESS_SUMMARY_KEY
    has_ids = "pending_game_ids" in raw
    has_records = "pending_games" in raw
    if not has_ids and not has_records:
        return ()
    if not has_ids or not has_records:
        present, missing = (
            ("pending_game_ids", "pending_games")
            if has_ids
            else ("pending_games", "pending_game_ids")
        )
        raise ValueError(f"{key} records {present} without {missing}")

    ids = raw["pending_game_ids"]
    records = raw["pending_games"]
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        raise ValueError(f"{key}.pending_game_ids is not a list of strings")
    if not isinstance(records, list):
        raise ValueError(f"{key}.pending_games is not a list")

    parsed: list[PendingScheduleGame] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError(f"{key}.pending_games contains a non-object")
        try:
            nba_game_id = record["nba_game_id"]
            game_date = record["game_date"]
            labels = tuple(
                record[field] for field in ("game_label", "game_sub_label", "game_subtype")
            )
        except KeyError as exc:
            raise ValueError(f"{key}.pending_games entry is missing {exc.args[0]!r}") from exc
        if not isinstance(nba_game_id, str) or not isinstance(game_date, str | None):
            raise ValueError(f"{key}.pending_games entry has a non-string id or date")
        if not all(isinstance(label, str) for label in labels):
            raise ValueError(f"{key}.pending_games entry has a non-string label")
        # Absent key reads as "". The strict cross-check below then holds: an
        # absent date with no reason is refused.
        #
        # **This is not "no producer could write it", which would be false.**
        # An intermediate commit on this branch emitted `game_date: null` with
        # no reason key at all, so a database seeded from that commit holds a
        # block this reader refuses — and `schedule_completeness` raising is
        # not degradable, it makes the schedule-grid read path a hard error.
        # The bound is that no such commit was ever merged, so this can only
        # affect a developer's own throwaway database, and the remedy is to
        # re-import. Stated rather than asserted away, because the next reader
        # deserves the real bound instead of a claim of impossibility.
        absence_reason = record.get("date_absence_reason", "")
        if not isinstance(absence_reason, str):
            raise ValueError(f"{key}.pending_games entry has a non-string date_absence_reason")
        if absence_reason and absence_reason not in _DATE_ABSENCE_REASONS:
            raise ValueError(
                f"{key}.pending_games entry has an unknown date_absence_reason "
                f"{absence_reason!r}; expected one of {sorted(_DATE_ABSENCE_REASONS)}"
            )
        if (parsed_date_is_absent := game_date is None) != bool(absence_reason):
            # A reason without an absence, or an absence without a reason,
            # means the two halves of the same fact disagree — and a consumer
            # reading only one of them would be told something the other
            # denies.
            raise ValueError(
                f"{key}.pending_games entry has game_date "
                f"{'absent' if parsed_date_is_absent else 'present'} but "
                f"date_absence_reason {absence_reason!r}"
            )
        try:
            parsed_date = date.fromisoformat(game_date) if game_date is not None else None
        except ValueError as exc:
            raise ValueError(f"{key}.pending_games entry has an unparseable date") from exc
        parsed.append(
            PendingScheduleGame(
                nba_game_id=nba_game_id,
                game_date=parsed_date,
                game_label=str(labels[0]),
                game_sub_label=str(labels[1]),
                game_subtype=str(labels[2]),
                date_absence_reason=absence_reason,
            )
        )

    if [game.nba_game_id for game in parsed] != list(ids):
        raise ValueError(
            f"{key}.pending_game_ids and .pending_games name different games: "
            f"{list(ids)} != {[game.nba_game_id for game in parsed]}"
        )
    if len(set(ids)) != len(ids):
        raise ValueError(f"{key}.pending_game_ids contains duplicates")
    return tuple(parsed)


def schedule_completeness(summary: Mapping[str, object]) -> ScheduleCompleteness | None:
    """Read back the completeness block, or ``None`` for a legacy/manual row.

    Absent block means "this refresh predates the completeness contract, or a
    human registered it by hand" — those keep the original byte-comparison
    behaviour. A block that is *present* is a claim of verifiability, and is
    held to it: malformed shape, a non-integer or negative count, leftover
    unresolved game IDs, or counts that cannot describe the same import all
    raise rather than silently degrading to the weaker string comparison.
    Degrading quietly would turn an unverifiable refresh into a
    verified-looking one, which is the exact direction of failure this seam
    exists to close.
    """

    if SCHEDULE_COMPLETENESS_SUMMARY_KEY not in summary:
        return None
    raw = summary[SCHEDULE_COMPLETENESS_SUMMARY_KEY]
    if not isinstance(raw, Mapping):
        raise ValueError(f"{SCHEDULE_COMPLETENESS_SUMMARY_KEY} is not an object")
    try:
        season = raw["season"]
        season_type = raw["season_type"]
        source_game_count = raw["source_game_count"]
        resolved_game_count = raw["resolved_game_count"]
        unresolved = raw["unresolved_game_ids"]
        persisted_team_row_count = raw["persisted_team_row_count"]
    except KeyError as exc:
        raise ValueError(f"{SCHEDULE_COMPLETENESS_SUMMARY_KEY} is missing {exc.args[0]!r}") from exc
    if not isinstance(season, str) or not isinstance(season_type, str):
        raise ValueError(f"{SCHEDULE_COMPLETENESS_SUMMARY_KEY} has a non-string scope")
    if not isinstance(unresolved, list) or not all(isinstance(item, str) for item in unresolved):
        raise ValueError(f"{SCHEDULE_COMPLETENESS_SUMMARY_KEY}.unresolved_game_ids is not a list")
    pending = _pending_games(raw)
    counts = (source_game_count, resolved_game_count, persisted_team_row_count)
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in counts):
        raise ValueError(f"{SCHEDULE_COMPLETENESS_SUMMARY_KEY} has a non-integer count")
    if any(value < 0 for value in counts):
        raise ValueError(f"{SCHEDULE_COMPLETENESS_SUMMARY_KEY} has a negative count")
    if source_game_count == resolved_game_count == persisted_team_row_count == 0:
        raise ValueError(
            f"{SCHEDULE_COMPLETENESS_SUMMARY_KEY} reports an impossible all-zero refresh; "
            "a registered schedule refresh must contain at least one source game"
        )
    if resolved_game_count == 0:
        # Not subsumed by the all-zero check above, and this is exactly what
        # ADR-013 loosened by accident: once `source == resolved + pending`,
        # a block declaring *every* game pending satisfies the arithmetic with
        # zero resolved games and zero persisted rows, and `verify_refresh`
        # then fingerprints an empty cohort against itself and answers
        # "current". `_require_complete_schedule_source` refuses an empty
        # parse, so no producer can write this; a stored block claiming it was
        # written by something else.
        raise ValueError(
            f"{SCHEDULE_COMPLETENESS_SUMMARY_KEY} reports {source_game_count} source game(s) of "
            "which none resolved; a registered schedule refresh always persists at least one "
            "resolved game, so this block was not written by the importer"
        )
    # Ordered before the blanket unresolved refusal deliberately. Both describe
    # a block that must not exist, but this one names *which* game is
    # double-classified, and the general refusal below is strictly stronger —
    # placed after it, this could never fire. A reviewer proved exactly that by
    # tracing the branch, which is the shape `gates.md` names: correct code
    # made unreachable by the guard above it.
    if overlap := sorted({game.nba_game_id for game in pending} & set(unresolved)):
        raise ValueError(
            f"{SCHEDULE_COMPLETENESS_SUMMARY_KEY} records the same game as pending and "
            f"unresolved: {overlap}"
        )
    if unresolved:
        raise ValueError(
            f"{SCHEDULE_COMPLETENESS_SUMMARY_KEY} records {len(unresolved)} unresolved game id(s); "
            "a refresh is only registered once every game the source claims to have assigned "
            "resolves; a game the source has not assigned yet belongs in pending_game_ids"
        )
    if source_game_count != resolved_game_count + len(pending):
        raise ValueError(
            f"{SCHEDULE_COMPLETENESS_SUMMARY_KEY} reports {source_game_count} source game(s) but "
            f"{resolved_game_count} resolved and {len(pending)} pending"
        )
    if persisted_team_row_count != 2 * resolved_game_count:
        raise ValueError(
            f"{SCHEDULE_COMPLETENESS_SUMMARY_KEY} reports {persisted_team_row_count} persisted "
            f"team row(s) for {resolved_game_count} game(s); team_schedule holds exactly two "
            "rows per game"
        )
    return ScheduleCompleteness(
        season=season,
        season_type=SeasonType(season_type),
        source_game_count=int(source_game_count),
        resolved_game_count=int(resolved_game_count),
        unresolved_game_ids=tuple(str(item) for item in unresolved),
        persisted_team_row_count=int(persisted_team_row_count),
        pending_games=pending,
    )


def schedule_content_parts(
    session: Session,
    *,
    season: str,
    season_type: SeasonType = SeasonType.REGULAR,
) -> list[str]:
    """The exact serialised content of one persisted schedule cohort.

    Every content-bearing field is included — season, season type, the stable
    ``nba_game_id``, both teams' stable ``nba_team_id``, the Eastern game date
    and the home flag — and nothing else. **Surrogate primary keys are
    deliberately excluded**: they differ between two databases holding
    identical schedules, and worse, they stay constant while the facts under
    them change, so a fingerprint built from them can report "unchanged" for a
    schedule that has been rewritten.

    Sorting happens in Python over the rendered strings rather than in SQL, so
    the result does not depend on the database's collation — the same cohort
    must fingerprint identically on SQLite and PostgreSQL (ADR-001).
    """

    team = aliased(NbaTeam)
    opponent = aliased(NbaTeam)
    game_home = aliased(NbaTeam)
    game_away = aliased(NbaTeam)
    rows = session.execute(
        select(
            NbaGame.nba_game_id,
            NbaGame.season,
            NbaGame.season_type,
            NbaGame.game_date,
            team.nba_team_id,
            opponent.nba_team_id,
            game_home.nba_team_id,
            game_away.nba_team_id,
            TeamScheduleEntry.game_date,
            TeamScheduleEntry.is_home,
        )
        .join(NbaGame, NbaGame.id == TeamScheduleEntry.game_id)
        .join(team, team.id == TeamScheduleEntry.team_id)
        .join(opponent, opponent.id == TeamScheduleEntry.opponent_team_id)
        .join(game_home, game_home.id == NbaGame.home_team_id)
        .join(game_away, game_away.id == NbaGame.away_team_id)
        .where(
            TeamScheduleEntry.season == season,
            TeamScheduleEntry.season_type == season_type,
        )
    ).all()
    body: list[str] = []
    for (
        nba_game_id,
        game_season,
        game_season_type,
        nba_game_date,
        team_nba_id,
        opponent_nba_id,
        home_nba_id,
        away_nba_id,
        schedule_game_date,
        is_home,
    ) in rows:
        expected_team, expected_opponent = (
            (home_nba_id, away_nba_id) if is_home else (away_nba_id, home_nba_id)
        )
        contradictions: list[str] = []
        if game_season != season:
            contradictions.append(f"season {game_season!r} != {season!r}")
        if game_season_type != season_type:
            contradictions.append(
                f"season_type {game_season_type.value!r} != {season_type.value!r}"
            )
        if nba_game_date != schedule_game_date:
            contradictions.append(
                f"game_date {nba_game_date.isoformat()} != {schedule_game_date.isoformat()}"
            )
        if (team_nba_id, opponent_nba_id) != (expected_team, expected_opponent):
            contradictions.append(
                "home/away identity "
                f"{team_nba_id}/{opponent_nba_id} != {expected_team}/{expected_opponent}"
            )
        if contradictions:
            raise ValueError(
                f"nba_games identity for game {nba_game_id!r} contradicts team_schedule: "
                + "; ".join(contradictions)
            )
        body.append(
            "|".join(
                (
                    season,
                    season_type.value,
                    nba_game_id,
                    str(team_nba_id),
                    str(opponent_nba_id),
                    schedule_game_date.isoformat(),
                    "1" if is_home else "0",
                )
            )
        )
    body.sort()
    header = "|".join((SCHEDULE_CONTENT_ALGORITHM, season, season_type.value, str(len(body))))
    return [header, *body]


def schedule_content_version(
    session: Session,
    *,
    season: str,
    season_type: SeasonType = SeasonType.REGULAR,
) -> str:
    """The version label one persisted schedule cohort currently supports.

    This is the single definition of "what version is this schedule". The
    importer stamps it when it registers a refresh and ``check_cohort``
    recomputes it when validating a claim, so a claim can only be reported
    ``"current"`` while the rows still hash to the registered label. Two calls
    against unchanged rows return the same string; any content change — even
    one that leaves the row count identical — returns a different one.
    """

    return content_fingerprint(
        schedule_content_parts(session, season=season, season_type=season_type)
    )


def record_refresh(
    session: Session,
    *,
    artifact_type: RefreshArtifactType,
    artifact_key: str = "default",
    version: str,
    source: str,
    season: str | None = None,
    summary: Mapping[str, object] | None = None,
    refreshed_at: datetime | None = None,
) -> RefreshRun:
    """Register that an artifact was (re)computed at ``version``.

    Idempotent by ``(artifact_type, artifact_key, version, season)``. The
    non-null ``season_key`` keeps unscoped rows unique on both SQLite and
    Postgres. The default key preserves the original contract for existing
    callers. Does not commit; callers manage their own transaction boundary.
    """

    lock_refresh_scope(
        session,
        artifact_type=artifact_type,
        artifact_key=artifact_key,
        season=season,
    )
    when = refreshed_at if refreshed_at is not None else datetime.now(UTC)
    season_key = season if season is not None else "*"
    existing = session.scalar(
        select(RefreshRun).where(
            RefreshRun.artifact_type == artifact_type,
            RefreshRun.artifact_key == artifact_key,
            RefreshRun.version == version,
            RefreshRun.season_key == season_key,
        )
    )
    if existing is not None:
        if existing.source != source:
            # Two producers claim the same content fingerprint under different
            # sources, and this row is the one that answers "where did this
            # artifact come from". Overwriting in place — which is what this
            # did until 2026-08-26 — keeps one row and reports whichever
            # producer ran last, with no trace that the other ever wrote.
            #
            # This was invisible while every caller passed a per-artifact
            # constant. `import_schedule` gained a `source=` parameter for the
            # reliability publisher, which made two values possible for the
            # SCHEDULE artifact, and an independent review drove the collision:
            # a real `ScheduleLeagueV2` import followed by a derived publish
            # relabelled the real cohort as derived, because identical rows
            # hash identically and `version` does not include `source`.
            #
            # Refused rather than reconciled. A second row would make
            # `current_refresh` ambiguous, and picking a winner here would be
            # this function inventing a provenance answer it does not have.
            raise LineageSourceConflict(
                f"{artifact_type.value}:{artifact_key} version {version} for season "
                f"{season_key} is already recorded as coming from {existing.source!r}; "
                f"{source!r} claims the same content. Refusing to relabel: the recorded "
                "source is the only answer to where these rows came from."
            )
        existing.refreshed_at = when
        if summary is not None:
            existing.summary = dict(summary)
        session.flush()
        return existing

    run = RefreshRun(
        artifact_type=artifact_type,
        artifact_key=artifact_key,
        version=version,
        season=season,
        season_key=season_key,
        source=source,
        summary=dict(summary) if summary is not None else {},
        refreshed_at=when,
    )
    session.add(run)
    session.flush()
    return run


def lock_refresh_scope(
    session: Session,
    *,
    artifact_type: RefreshArtifactType,
    artifact_key: str,
    season: str | None,
) -> None:
    """Serialize publishers and consumers of one exact lineage scope.

    PostgreSQL holds a transaction-level advisory lock, including when no row
    exists for a newly introduced scope. SQLite reserves its database-wide
    writer through a no-op update. A producer must go through ``record_refresh``
    and a strict consumer must call this before reading inputs; together those
    rules prevent a cohort from advancing between a consumer's final check and
    commit.

    **Order matters as much as coverage.** The canonical acquisition order is
    league-settings, then the NBA schedule, then any per-league derived scope
    (scoring-period projection, context, models). On PostgreSQL these are real
    blocking locks held to commit, so two callers taking the same pair in
    opposite orders deadlock with ``40P01`` — and *anything composing two
    production writers inherits their lock order and must respect the global
    one*, which is easy to violate without ever calling this function. That is
    not hypothetical: a developer seeding tool once composed ``import_schedule``
    before ``import_league_settings`` and inverted the pair, and a static
    enumeration of every call site here declared the ordering sound while
    runtime instrumentation found the inversion immediately.
    """

    season_filter = RefreshRun.season.is_(None) if season is None else RefreshRun.season == season
    filters = (
        RefreshRun.artifact_type == artifact_type,
        RefreshRun.artifact_key == artifact_key,
        season_filter,
    )
    acquire_transaction_lock(
        session,
        scope_key=f"{artifact_type.value}\x00{artifact_key}\x00{season or '*'}",
        write_reservation=(
            update(RefreshRun).where(*filters).values(refreshed_at=RefreshRun.refreshed_at)
        ),
    )


def league_settings_artifact_key(league_id: int) -> str:
    """The lock-only lineage scope for one league's versioned settings."""

    return f"league-settings:{league_id}"


def projection_source_artifact_key(source: str) -> str:
    """The lock-only lineage scope for one projection publisher's imports."""

    return f"projection-source:{source}"


def lock_projection_source_scope(session: Session, *, source: str, season: str) -> None:
    """Serialize two importers of the same projection source and season.

    **Last in the canonical order** — see :func:`lock_refresh_scope`. This is a
    per-source derived scope, so anything composing a projection import with a
    settings or schedule writer must take those first. ``import_projection_csv``
    takes no other transaction lock, so today it is a leaf.

    Replaces a ``SELECT ... FOR UPDATE`` on the ``projection_sources`` row that
    was inert on SQLite (R58), for two independent reasons: pysqlite emits
    ``BEGIN`` before DML and not before a ``SELECT``, and on a repeat import of
    an already-registered source no DML had been emitted at that point — the
    ORM issues no ``UPDATE`` when ``display_name`` is unchanged, which is
    exactly what running the same import twice looks like; and SQLAlchemy's
    SQLite dialect renders no ``FOR UPDATE`` text at all. The in-process
    ``threading.Lock`` in the importer still separates threads and does nothing
    between processes.

    It lives here rather than in ``ingest/projections/`` so ``db/lineage.py``
    stays the only module reaching ``acquire_transaction_lock``. Two lock-order
    tests monkeypatch that name *on this module*, and a second importer of the
    primitive would blind both recorders while leaving them green —
    ``test_lineage_locks_are_acquired_through_exactly_one_import`` pins it, and
    caught this change doing exactly that.

    Registering no ``refresh_runs`` row is deliberate: this is a lock scope, not
    a claim that a projection refresh has been published. ``quant`` owns
    registering projection refreshes when those exist.
    """

    lock_refresh_scope(
        session,
        artifact_type=RefreshArtifactType.PROJECTION,
        artifact_key=projection_source_artifact_key(source),
        season=season,
    )


def lock_league_settings_scope(session: Session, *, league_id: int, season: str) -> None:
    """Serialize settings writers with calendar derivation and projection readers.

    **First in the canonical order** — see :func:`lock_refresh_scope`. Any caller
    that will also touch the NBA schedule scope, directly or through a writer it
    composes, must take this one before that one.
    """

    lock_refresh_scope(
        session,
        artifact_type=RefreshArtifactType.SOURCE,
        artifact_key=league_settings_artifact_key(league_id),
        season=season,
    )


def current_refresh(
    session: Session,
    artifact_type: RefreshArtifactType,
    *,
    artifact_key: str = "default",
    season: str | _SeasonNotSpecified | None = _SEASON_NOT_SPECIFIED,
) -> RefreshRun | None:
    """The latest row for one artifact type/key and optional season.

    ``None`` means no producer has ever registered a refresh for this
    scope. Omitting ``season`` searches all seasons; passing ``None`` matches
    only unscoped rows.
    """

    filters = [
        RefreshRun.artifact_type == artifact_type,
        RefreshRun.artifact_key == artifact_key,
    ]
    if not isinstance(season, _SeasonNotSpecified):
        filters.append(
            RefreshRun.season.is_(None) if season is None else RefreshRun.season == season
        )
    return session.scalar(
        select(RefreshRun)
        .where(*filters)
        .order_by(RefreshRun.refreshed_at.desc(), RefreshRun.id.desc())
        .limit(1)
    )


@dataclass(frozen=True)
class CohortCheck:
    """The verdict for one claimed version against the current registry."""

    artifact_type: RefreshArtifactType
    claimed_version: str
    status: CohortStatus
    current_version: str | None
    current_refreshed_at: datetime | None


@dataclass(frozen=True)
class RefreshVerification:
    """Whether one registered refresh still describes its persisted artifact.

    ``observed_content_version`` is diagnostic evidence, never a current
    version. Only a producer can make a version current by successfully
    registering it; a verifier must not promote an out-of-band row mutation
    merely because a caller submits the resulting hash.
    """

    registered_version: str
    observed_content_version: str | None
    current_version: str | None
    is_current: bool


def verify_refresh(session: Session, run: RefreshRun) -> RefreshVerification:
    """Verify that ``run`` still describes its persisted artifact.

    For the canonical ``nba-schedule`` refresh registered with completeness
    metadata, that is the fingerprint recomputed from the persisted
    ``team_schedule`` rows — not the label stored on the row. The registered
    label is current only when those values match. If they differ,
    ``current_version`` is ``None``: the observed hash is unregistered evidence,
    not a newly current version. Rows without completeness metadata (legacy
    imports and manual registrations), derived schedule-typed streams under
    other artifact keys, and every non-schedule artifact retain the original
    byte-comparison contract, because there is nothing this module can honestly
    recompute them from.

    **Fail closed on inconsistent evidence.** A completeness block that
    contradicts itself or the refresh row it sits on is not weaker evidence,
    it is wrong evidence, and it raises rather than falling back to the stored
    label. That covers the block's own internal arithmetic (see
    ``schedule_completeness``), a block scoped to a different season than the
    refresh row, and the one case where a forged block could otherwise pass:
    metadata claiming a large persisted cohort while the stored version is in
    fact the fingerprint of a smaller — or empty — one.
    """

    if (
        run.artifact_type is not RefreshArtifactType.SCHEDULE
        or run.artifact_key != NBA_SCHEDULE_ARTIFACT_KEY
    ):
        return RefreshVerification(run.version, None, run.version, True)
    completeness = schedule_completeness(run.summary)
    if completeness is None:
        return RefreshVerification(run.version, None, run.version, True)
    if run.season != completeness.season:
        raise ValueError(
            f"{SCHEDULE_COMPLETENESS_SUMMARY_KEY} is scoped to season "
            f"{completeness.season!r} but the refresh row is scoped to {run.season!r}"
        )
    parts = schedule_content_parts(
        session,
        season=completeness.season,
        season_type=completeness.season_type,
    )
    version = content_fingerprint(parts)
    # ``parts`` is one scope header followed by one line per persisted row, and
    # the row count is inside that header — so a cohort whose size no longer
    # matches the metadata cannot fingerprint back to the stored label. If it
    # somehow does, the metadata was never describing this cohort at all.
    persisted_rows = len(parts) - 1
    if persisted_rows != completeness.persisted_team_row_count:
        raise ValueError(
            f"{SCHEDULE_COMPLETENESS_SUMMARY_KEY} claims "
            f"{completeness.persisted_team_row_count} persisted team row(s) for season "
            f"{completeness.season}, but persisted content fingerprints {persisted_rows}"
        )
    is_current = version == run.version
    return RefreshVerification(
        registered_version=run.version,
        observed_content_version=version,
        current_version=run.version if is_current else None,
        is_current=is_current,
    )


def effective_current_version(session: Session, run: RefreshRun) -> str | None:
    """Return the registered current version, or ``None`` when verification fails.

    New consumers should use :func:`verify_refresh` for the explicit result
    contract. This compatibility helper deliberately never returns an
    unregistered observed content hash.
    """

    return verify_refresh(session, run).current_version


def _check_claimed_run(
    session: Session,
    *,
    artifact_type: RefreshArtifactType,
    claimed_version: str,
    run: RefreshRun | None,
) -> CohortCheck:
    if run is None:
        return CohortCheck(artifact_type, claimed_version, "unknown", None, None)
    verification = verify_refresh(session, run)
    if not verification.is_current:
        return CohortCheck(artifact_type, claimed_version, "stale", None, None)
    status: CohortStatus = "current" if verification.current_version == claimed_version else "stale"
    return CohortCheck(
        artifact_type,
        claimed_version,
        status,
        verification.current_version,
        run.refreshed_at,
    )


def check_refresh_claim(
    session: Session,
    *,
    artifact_type: RefreshArtifactType,
    artifact_key: str,
    claimed_version: str,
    season: str | None,
) -> CohortCheck:
    """Check one exact keyed, season-scoped claim through canonical verification."""

    run = current_refresh(
        session,
        artifact_type,
        artifact_key=artifact_key,
        season=season,
    )
    return _check_claimed_run(
        session,
        artifact_type=artifact_type,
        claimed_version=claimed_version,
        run=run,
    )


def check_cohort(
    session: Session,
    *,
    schedule_version: str | None = None,
    model_version: str | None = None,
    projection_version: str | None = None,
) -> list[CohortCheck]:
    """Compare claimed version strings against the current registered refresh.

    Only the artifact types actually supplied are checked — omitting a field
    means the caller is not asserting anything about it, not that it is
    automatically accepted. This reports per artifact whether the claim is
    ``"current"``, ``"stale"`` (registered, but superseded by a later
    refresh, or no longer describing the persisted facts), or ``"unknown"``
    (nothing has ever been registered for that artifact type, so there is no
    baseline to compare against). It does not decide whether a mismatch is
    fatal; that policy belongs to the caller (e.g. ``quant`` refusing to
    persist a valuation computed against a stale schedule cohort).

    The schedule comparison is made against ``effective_current_version``,
    which recomputes the cohort fingerprint from ``team_schedule`` for a
    refresh that carries completeness metadata. This is the same function
    ``import_schedule`` stamps with, so the two cannot drift apart. A refresh
    whose completeness metadata contradicts itself or its own scope raises
    instead of returning a verdict — an unanswerable question is reported as
    unanswerable, not as ``"stale"``.
    """

    claims: tuple[tuple[RefreshArtifactType, str, str | None], ...] = (
        (RefreshArtifactType.SCHEDULE, NBA_SCHEDULE_ARTIFACT_KEY, schedule_version),
        (RefreshArtifactType.MODEL, "default", model_version),
        (RefreshArtifactType.PROJECTION, "default", projection_version),
    )
    results: list[CohortCheck] = []
    for artifact_type, artifact_key, claimed in claims:
        if claimed is None:
            continue
        current = current_refresh(session, artifact_type, artifact_key=artifact_key)
        # Rows registered before keyed lineage landed remain under ``default``.
        # Read them only when no producer has published the keyed stream.
        if current is None and artifact_key != "default":
            current = current_refresh(session, artifact_type)
        results.append(
            _check_claimed_run(
                session,
                artifact_type=artifact_type,
                claimed_version=claimed,
                run=current,
            )
        )
    return results
