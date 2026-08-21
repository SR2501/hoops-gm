"""Writing parsed records into the database.

Kept apart from both transport and parsing. An importer needs a database and a
parser must not, which is what keeps the contract tests offline and instant.

Every function here is **idempotent**. A backfill is thousands of throttled
requests over tens of minutes; it will be interrupted, and re-running it must
converge rather than duplicate. Idempotency is by natural key —
``nba_team_id``, ``nba_game_id``, ``(player, game)`` — never by "delete
everything and reload", which would throw away manual identity overrides.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from hoops_gm.db.lineage import (
    NBA_SCHEDULE_ARTIFACT_KEY,
    SCHEDULE_COMPLETENESS_SUMMARY_KEY,
    SCHEDULE_CONTEXT_SOURCE_KEY,
    ScheduleCompleteness,
    lock_league_settings_scope,
    lock_refresh_scope,
    record_refresh,
    schedule_content_version,
)
from hoops_gm.db.models.availability import PlayerParticipation
from hoops_gm.db.models.enums import (
    ExternalSource,
    FieldEvidence,
    GameStatus,
    MatchMethod,
    RefreshArtifactType,
    SeasonType,
)
from hoops_gm.db.models.identity import NbaTeam, Player, PlayerExternalId
from hoops_gm.db.models.injury_report import CURRENT_EVIDENCE_SCHEMA_VERSION, InjuryReportEntry
from hoops_gm.db.models.league import League
from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog
from hoops_gm.identity.names import normalize_name
from hoops_gm.identity.resolver import Resolution
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.injury_report.models import InjuryReportEntryRecord
from hoops_gm.ingest.league_settings import LeagueSettingsDocument
from hoops_gm.ingest.nba.models import (
    GameParticipation,
    NbaGameRecord,
    NbaPlayerRecord,
    NbaTeamRecord,
    PlayerBoxScoreRecord,
)
from hoops_gm.ingest.nba.schedule import ENDPOINT as SCHEDULE_ENDPOINT
from hoops_gm.ingest.nba.schedule import SOURCE as SCHEDULE_SOURCE
from hoops_gm.ingest.nba.schedule import ScheduleParseResult


@dataclass
class ImportCounts:
    """What an import did, so a backfill can report progress honestly."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    #: Rows retired from the current-join set but kept as history.
    superseded: int = 0

    def __str__(self) -> str:
        base = f"{self.created} created, {self.updated} updated, {self.skipped} skipped"
        return f"{base}, {self.superseded} superseded" if self.superseded else base


# --------------------------------------------------------------------------
# League settings
# --------------------------------------------------------------------------


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def import_league_settings(
    session: Session,
    *,
    league: League,
    document: LeagueSettingsDocument,
    source_payload_sha256: str,
    observed_at: datetime,
) -> ImportCounts:
    """Persist a new immutable settings version, or skip an identical document."""
    if league.fantrax_league_id is None:
        raise ValueError(
            "target league must be linked to a Fantrax league id before settings import"
        )
    if league.fantrax_league_id != document.source_league_id:
        raise ValueError(
            "league settings identity mismatch: "
            f"source leagueId={document.source_league_id!r}, "
            f"target leagueId={league.fantrax_league_id!r}"
        )
    expected_season = f"{document.source_season_year}-{str(document.source_season_year + 1)[-2:]}"
    if league.season != expected_season:
        raise ValueError(
            "league settings season mismatch: "
            f"source seasonYear={document.source_season_year} means {expected_season}, "
            f"target league is {league.season}"
        )
    if not _SHA256_RE.fullmatch(source_payload_sha256):
        raise ValueError("source_payload_sha256 must be a lowercase SHA-256 hex digest")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    if document.unmapped_rule_paths:
        raise ValueError(
            "cannot persist settings with unhandled rule-shaped paths: "
            f"{document.unmapped_rule_paths}"
        )

    lock_league_settings_scope(session, league_id=league.id, season=league.season)
    serialized = document.model_dump(mode="json")
    existing = list(
        session.scalars(
            select(LeagueSettingsSnapshot)
            .where(LeagueSettingsSnapshot.league_id == league.id)
            .order_by(LeagueSettingsSnapshot.version)
        )
    )
    if existing:
        prior = LeagueSettingsDocument.model_validate(existing[-1].settings)
        if prior.content_sha256() == document.content_sha256():
            return ImportCounts(skipped=1)

    sourced_fields = (
        "lineup_lock",
        "waivers",
        "games_caps",
        "roster_limits",
        "scoring_periods",
        "trade_deadline",
        "playoffs",
        "keepers",
        "scoring_type",
        "scoring_categories",
    )
    source_summary = {field: serialized[field]["evidence"] for field in sourced_fields}
    next_version = existing[-1].version + 1 if existing else 1
    session.add(
        LeagueSettingsSnapshot(
            league_id=league.id,
            version=next_version,
            schema_version=str(document.schema_version),
            settings=serialized,
            source_summary=source_summary,
            source_payload_sha256=source_payload_sha256,
            observed_at=observed_at,
        )
    )
    session.flush()
    return ImportCounts(created=1)


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def import_teams(session: Session, records: Sequence[NbaTeamRecord]) -> ImportCounts:
    counts = ImportCounts()
    existing = {t.nba_team_id: t for t in session.scalars(select(NbaTeam))}
    for record in records:
        team = existing.get(record.nba_team_id)
        if team is None:
            session.add(
                NbaTeam(
                    nba_team_id=record.nba_team_id,
                    abbreviation=record.abbreviation,
                    name=record.full_name,
                    city=record.city,
                )
            )
            counts.created += 1
        else:
            team.abbreviation = record.abbreviation
            team.name = record.full_name
            team.city = record.city
            counts.updated += 1
    session.flush()
    return counts


def import_nba_players(session: Session, records: Sequence[NbaPlayerRecord]) -> ImportCounts:
    """Create canonical players from the NBA list and record their NBA ids.

    NBA.com is treated as the source that gets to introduce a canonical row,
    because every stat in this project is keyed to an NBA person id. That is a
    choice about provenance, not a claim that NBA.com is authoritative about
    people — a Fantrax player with no NBA row is a real player who has not
    appeared in the NBA, and the resolver reports them rather than inventing a
    canonical row for them.

    The ``nba`` external id is recorded with ``match_method=ANCHOR_ID`` and
    ``confidence=1.0``, and that is the **only** place in this project where
    that claim is true: it is not a cross-source inference, it is the identifier
    the row was created from.
    """
    counts = ImportCounts()
    teams = {t.nba_team_id: t.id for t in session.scalars(select(NbaTeam))}
    existing = {
        row.external_id: row
        for row in session.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.NBA)
        )
    }

    for record in records:
        key = str(record.nba_player_id)
        normalized = normalize_name(record.display_last_comma_first)
        link = existing.get(key)

        if link is None:
            player = Player(
                full_name=record.display_first_last or record.display_last_comma_first,
                normalized_name=normalized.key,
                first_name=normalized.first or None,
                last_name=normalized.last or None,
                current_team_id=teams.get(record.team_id) if record.team_id else None,
            )
            session.add(player)
            session.flush()
            session.add(
                PlayerExternalId(
                    player_id=player.id,
                    source=ExternalSource.NBA,
                    current_for_source=ExternalSource.NBA.value,
                    external_id=key,
                    external_name=record.display_last_comma_first,
                    normalized_name=normalized.key,
                    external_team=record.team_abbreviation,
                    confidence=1.0,
                    match_method=MatchMethod.ANCHOR_ID,
                    name_evidence=FieldEvidence.AGREE,
                )
            )
            counts.created += 1
        else:
            player = session.get(Player, link.player_id)  # type: ignore[assignment]
            if player is not None:
                player.full_name = record.display_first_last or player.full_name
                player.normalized_name = normalized.key
                if record.team_id:
                    player.current_team_id = teams.get(record.team_id)
            link.external_name = record.display_last_comma_first
            link.normalized_name = normalized.key
            link.external_team = record.team_abbreviation
            counts.updated += 1

    session.flush()
    return counts


def import_resolutions(
    session: Session,
    resolutions: Iterable[Resolution],
    *,
    source: ExternalSource,
    accepted_only: bool = True,
) -> ImportCounts:
    """Write accepted crosswalk matches as ``player_external_ids`` rows.

    Three properties are load-bearing, and all three concern *not* silently
    keeping something stale.

    **A manual override is final.** If a human has adjudicated a row, an
    automated pass leaves it alone entirely — including superseding it. That is
    the whole purpose of the flag, and a resolver that re-decides a human's
    call is worse than no resolver.

    **Only accepted matches become current.** A row that needs review belongs
    in the report, not in the crosswalk. Writing a low-confidence guess and
    relying on ``confidence`` to warn downstream assumes every consumer checks
    it, and the one that does not is the one that corrupts a number.

    **A match that is no longer accepted is superseded, not left standing.**
    ``current_for_source`` is set to ``NULL``, which retains the row as history
    while removing it from every join. Without this the crosswalk was
    append-only in the worst sense: a match the resolver had since *retracted*
    survived with its old high confidence and evidence, looking authoritative
    to every consumer, and there was no code path anywhere that could ever
    clear the flag.

    Supersession also prevents an abort. When a source re-issues an identifier
    for a player who already has a current row, the lookup keyed on
    ``external_id`` misses, a second row is created with the same
    ``current_for_source``, and the flush violates
    ``uq_player_external_ids_current`` — killing a multi-season backfill
    mid-run. Fantrax reissuing identifiers is not hypothetical; identifier
    instability is the premise of R7.

    Pass **all** resolutions, not only the accepted ones, so retraction can be
    detected. ``accepted_only`` still governs what is *written*.
    """
    counts = ImportCounts()
    nba_links = {
        row.external_id: row.player_id
        for row in session.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.NBA)
        )
    }
    rows_for_source = list(
        session.scalars(select(PlayerExternalId).where(PlayerExternalId.source == source))
    )
    existing = {row.external_id: row for row in rows_for_source}
    #: The one current row per player, which is what the unique constraint
    #: protects and therefore what a new row can collide with.
    current_by_player = {
        row.player_id: row for row in rows_for_source if row.current_for_source is not None
    }

    resolutions = list(resolutions)

    # Pass 1: supersede. Done before anything is written, and flushed, so that
    # a re-issued identifier frees the slot its predecessor occupied before the
    # replacement is inserted.
    for resolution in resolutions:
        row = existing.get(resolution.source_record.key)
        if row is None or row.is_manual_override or row.current_for_source is None:
            continue
        if resolution.accepted:
            continue
        row.current_for_source = None
        current_by_player.pop(row.player_id, None)
        counts.superseded += 1

    for resolution in resolutions:
        if not resolution.accepted or resolution.best is None:
            continue
        player_id = nba_links.get(resolution.best.target.key)
        if player_id is None:
            continue
        incumbent = current_by_player.get(player_id)
        if (
            incumbent is not None
            and incumbent.external_id != resolution.source_record.key
            and not incumbent.is_manual_override
        ):
            incumbent.current_for_source = None
            current_by_player.pop(player_id, None)
            counts.superseded += 1

    session.flush()

    # Pass 2: write.
    for resolution in resolutions:
        if accepted_only and not resolution.accepted:
            counts.skipped += 1
            continue
        if resolution.best is None:
            counts.skipped += 1
            continue

        player_id = nba_links.get(resolution.best.target.key)
        if player_id is None:
            # The canonical side is not in the database. Skipped rather than
            # created: inventing a player from the far side of an inferred
            # match is how a crosswalk grows phantom people.
            counts.skipped += 1
            continue

        external_id = resolution.source_record.key
        evidence = resolution.evidence
        link = existing.get(external_id)

        if link is not None and link.is_manual_override:
            counts.skipped += 1
            continue

        if link is None:
            link = PlayerExternalId(source=source, external_id=external_id)
            session.add(link)
            existing[external_id] = link
            counts.created += 1
        else:
            counts.updated += 1

        link.player_id = player_id
        link.current_for_source = source.value
        current_by_player[player_id] = link
        link.external_name = resolution.source_record.raw_name
        link.normalized_name = resolution.source_record.normalized.key
        link.external_team = resolution.source_record.team
        link.external_position = resolution.source_record.position
        link.confidence = resolution.confidence
        link.match_method = MatchMethod(resolution.match_method)
        link.name_evidence = evidence.name
        link.team_evidence = evidence.team
        link.position_evidence = evidence.position
        link.suffix_evidence = evidence.suffix

    session.flush()
    return counts


# --------------------------------------------------------------------------
# Games, box scores, participation
# --------------------------------------------------------------------------


def import_games(session: Session, records: Sequence[NbaGameRecord]) -> ImportCounts:
    lock_refresh_scope(
        session,
        artifact_type=RefreshArtifactType.SOURCE,
        artifact_key=SCHEDULE_CONTEXT_SOURCE_KEY,
        season=None,
    )
    counts = ImportCounts()
    teams = {t.nba_team_id: t.id for t in session.scalars(select(NbaTeam))}
    existing = {g.nba_game_id: g for g in session.scalars(select(NbaGame))}

    for record in records:
        home = teams.get(record.home_team_id)
        away = teams.get(record.away_team_id)
        if home is None or away is None:
            counts.skipped += 1
            continue

        game = existing.get(record.nba_game_id)
        if game is None:
            game = NbaGame(
                nba_game_id=record.nba_game_id,
                season=record.season,
                season_type=SeasonType(record.season_type),
                game_date=record.game_date,
                home_team_id=home,
                away_team_id=away,
            )
            session.add(game)
            counts.created += 1
        else:
            counts.updated += 1

        game.home_score = record.home_score
        game.away_score = record.away_score
        # Only ever set from a source that gave one. LeagueGameFinder supplies
        # a local date and no instant, and a midnight guess here would feed
        # back-to-back and rest-day detection with fiction.
        if record.tipoff_utc is not None:
            game.tipoff_utc = record.tipoff_utc
        if record.home_score is not None and record.away_score is not None:
            game.status = GameStatus.FINAL

    session.flush()
    return counts


def import_schedule(session: Session, parsed: ScheduleParseResult) -> ImportCounts:
    """Write one parsed season's schedule and register its refresh cohort.

    Takes the whole :class:`ScheduleParseResult`, not just its games, because
    the completeness evidence lives on the result: how many regular-season
    games the source reported, how many resolved to real teams, and which game
    IDs did not. Without that the importer can persist a partial slate and
    register it as a complete cohort, which is the silent-degradation failure
    the Adapter gate exists to prevent — the schedule is the denominator of
    every expected-games number downstream.

    **Fail closed.** Nothing is registered, and the caller's transaction is
    left to roll back, when any of the following holds:

    * the source reported game IDs whose teams are still TBD;
    * the source's own game count disagrees with the resolved count;
    * a referenced NBA team is not present in the database;
    * a persisted ``nba_games`` row disagrees with the parsed source about the
      game's season, season type, Eastern date, or which teams played;
    * the rows actually persisted for the season are not exactly two per
      parsed game, on the right dates, with the right home/away orientation —
      including when rows for that season sit *outside* the parsed cohort.

    Those last two checks are deliberately performed by reading back what was
    written rather than by trusting the write path, because "the importer
    thinks it wrote 2,460 rows" and "2,460 correct rows are in the table" are
    different claims and only the second one matters to a consumer.

    **Nothing is deleted here.** An out-of-cohort row for this season is
    inconsistent evidence, and inconsistent evidence is refused, not silently
    reconciled: deleting it would cascade into ``quant``'s derived
    ``opponent_context`` and cannot be undone by re-running the import. The
    refusal leaves both the extra row and the operator's options intact.
    """

    season = parsed.season
    lock_refresh_scope(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        season=season,
    )
    _require_complete_schedule_source(parsed)

    teams = {team.nba_team_id: team.id for team in session.scalars(select(NbaTeam))}
    _require_known_teams(parsed, teams=teams)

    # The final exact-cohort check necessarily runs after writes. Keep those
    # writes inside a savepoint so a caller may catch SourceContractError and
    # still safely commit unrelated outer-transaction work.
    with session.begin_nested():
        return _persist_schedule_cohort(session, parsed, teams=teams)


def _persist_schedule_cohort(
    session: Session,
    parsed: ScheduleParseResult,
    *,
    teams: dict[int, int],
) -> ImportCounts:
    season = parsed.season
    counts = import_games(session, [record.game for record in parsed.games])
    games = _require_persisted_game_identity(session, parsed, teams=teams)

    expected: dict[tuple[int, int], tuple[int, date, bool]] = {}
    for record in parsed.games:
        game_id = games[record.game.nba_game_id]
        home_id = teams[record.home_nba_team_id]
        away_id = teams[record.away_nba_team_id]
        expected[(game_id, home_id)] = (away_id, record.game.game_date, True)
        expected[(game_id, away_id)] = (home_id, record.game.game_date, False)

    existing = {
        (entry.game_id, entry.team_id): entry
        for entry in session.scalars(
            select(TeamScheduleEntry).where(
                TeamScheduleEntry.game_id.in_({game_id for game_id, _ in expected})
            )
        )
    }

    for (game_id, team_id), (opponent_id, game_date, is_home) in expected.items():
        entry = existing.get((game_id, team_id))
        if entry is None:
            session.add(
                TeamScheduleEntry(
                    season=season,
                    season_type=SeasonType.REGULAR,
                    game_id=game_id,
                    team_id=team_id,
                    opponent_team_id=opponent_id,
                    game_date=game_date,
                    is_home=is_home,
                )
            )
            counts.created += 1
        else:
            entry.season = season
            entry.season_type = SeasonType.REGULAR
            entry.opponent_team_id = opponent_id
            entry.game_date = game_date
            entry.is_home = is_home
            counts.updated += 1

    session.flush()

    persisted_team_row_count = _require_exact_persisted_schedule(session, parsed)
    _register_schedule_refresh(
        session,
        parsed,
        persisted_team_row_count=persisted_team_row_count,
    )
    session.flush()
    return counts


def _require_complete_schedule_source(parsed: ScheduleParseResult) -> None:
    """Refuse a source cohort that does not account for every game it reported.

    Accounting for a game means classifying it, not resolving it. Under
    ADR-013 a game the source published with its team identities explicitly
    absent is *pending* and is recorded rather than refused; only a game the
    source claims to have assigned, and which does not resolve, still refuses.
    """

    season = parsed.season
    if parsed.unresolved_game_ids:
        shown = ", ".join(parsed.unresolved_game_ids[:5])
        raise _schedule_contract(
            f"season {season} reports {len(parsed.unresolved_game_ids)} game(s) whose teams the "
            f"source named but did not identify ({shown}); a schedule cohort is only registered "
            "once every game the source claims to have assigned resolves. This is not the "
            "not-yet-drawn case, which is recorded as pending"
        )
    if not parsed.games:
        raise _schedule_contract(
            f"season {season} parsed to zero regular-season games; refusing to register an "
            "empty schedule cohort"
        )
    pending_ids = parsed.pending_game_ids
    resolved_ids = [record.game.nba_game_id for record in parsed.games]
    if parsed.source_game_count != len(parsed.games) + len(pending_ids):
        raise _schedule_contract(
            f"season {season} source reported {parsed.source_game_count} regular-season games "
            f"but {len(parsed.games)} resolved and {len(pending_ids)} are pending"
        )
    if set(pending_ids) & set(resolved_ids):
        raise _schedule_contract(
            f"season {season} parse result reports the same game as both resolved and pending: "
            f"{sorted(set(pending_ids) & set(resolved_ids))}"
        )
    wrong_season = sorted(
        {record.game.season for record in parsed.games if record.game.season != season}
    )
    if wrong_season:
        raise _schedule_contract(f"season {season} parse result contains games for {wrong_season}")
    game_ids = resolved_ids + list(pending_ids)
    if len(set(game_ids)) != len(game_ids):
        raise _schedule_contract(f"season {season} parse result contains duplicate game IDs")


def _require_known_teams(parsed: ScheduleParseResult, *, teams: dict[int, int]) -> None:
    """Refuse a cohort referencing NBA teams that are not in the database.

    ``import_games`` skips a game whose teams are unknown, which is the right
    behaviour for a bulk backfill and the wrong behaviour here: a skipped game
    is two missing ``team_schedule`` rows, and a schedule missing two rows is
    still a perfectly plausible-looking schedule.
    """

    missing_teams = sorted(
        {
            nba_team_id
            for record in parsed.games
            for nba_team_id in (record.home_nba_team_id, record.away_nba_team_id)
            if nba_team_id not in teams
        }
    )
    if missing_teams:
        raise _schedule_contract(
            f"season {parsed.season} references NBA team id(s) {missing_teams} that "
            "are not in the database; import teams before the schedule"
        )


def _require_persisted_game_identity(
    session: Session, parsed: ScheduleParseResult, *, teams: dict[int, int]
) -> dict[str, int]:
    """Require every persisted ``nba_games`` row to match the parsed source.

    ``import_games`` deliberately does not rewrite a game's core identity: it
    keys on ``nba_game_id`` and, for an existing row, only refreshes scores,
    tip-off and status. That is right for a box-score backfill — a later
    source must not be able to move a game to a different date or a different
    pair of teams — but it means a pre-existing row that contradicts the
    schedule survives the import untouched, and ``team_schedule`` would then
    be written against a game ``nba_games`` describes differently.

    Two tables silently disagreeing about who played whom, and when, is worse
    than either being missing, so a contradiction is refused here rather than
    reconciled. Returns the ``nba_game_id`` → surrogate id map the caller
    needs, so the read is not repeated.
    """

    nba_team_ids = {row_id: nba_team_id for nba_team_id, row_id in teams.items()}
    persisted = {
        game.nba_game_id: game
        for game in session.scalars(
            select(NbaGame).where(
                NbaGame.nba_game_id.in_(record.game.nba_game_id for record in parsed.games)
            )
        )
    }

    missing: list[str] = []
    contradictions: list[str] = []
    for record in parsed.games:
        game = persisted.get(record.game.nba_game_id)
        if game is None:
            missing.append(record.game.nba_game_id)
            continue
        observed = (
            game.season,
            game.season_type,
            game.game_date,
            nba_team_ids.get(game.home_team_id),
            nba_team_ids.get(game.away_team_id),
        )
        wanted = (
            record.game.season,
            SeasonType(record.game.season_type),
            record.game.game_date,
            record.home_nba_team_id,
            record.away_nba_team_id,
        )
        if observed != wanted:
            contradictions.append(f"{record.game.nba_game_id}: {observed} != {wanted}")

    if missing:
        raise _schedule_contract(
            f"season {parsed.season} has {len(missing)} parsed game(s) with no persisted "
            f"nba_games row ({', '.join(sorted(missing)[:5])})"
        )
    if contradictions:
        raise _schedule_contract(
            f"season {parsed.season} has {len(contradictions)} persisted nba_games row(s) that "
            "contradict the parsed schedule on (season, season_type, date, home, away): "
            f"{'; '.join(sorted(contradictions)[:3])}"
        )
    return {nba_game_id: game.id for nba_game_id, game in persisted.items()}


def _require_exact_persisted_schedule(session: Session, parsed: ScheduleParseResult) -> int:
    """Read the cohort back and require it to equal the parsed source exactly.

    Compared on stable NBA identifiers, so the check means "the right games
    between the right teams on the right dates", not "the right number of
    rows". Rows for this season's regular-season scope that the parsed cohort
    does not contain fail here too, and are deliberately *not* deleted: a
    cancelled or rescheduled fixture is a real editorial question, and
    ``opponent_context.team_schedule_id`` cascades, so quietly resolving it
    here would destroy ``quant``'s derived rows on the strength of one
    possibly-truncated payload. Returns the persisted row count for the
    refresh summary.
    """

    expected: set[tuple[str, int, int, date, bool]] = {
        (record.game.nba_game_id, team_id, opponent_id, record.game.game_date, is_home)
        for record in parsed.games
        for team_id, opponent_id, is_home in (
            (record.home_nba_team_id, record.away_nba_team_id, True),
            (record.away_nba_team_id, record.home_nba_team_id, False),
        )
    }

    team = aliased(NbaTeam)
    opponent = aliased(NbaTeam)
    observed_rows = session.execute(
        select(
            NbaGame.nba_game_id,
            team.nba_team_id,
            opponent.nba_team_id,
            TeamScheduleEntry.game_date,
            TeamScheduleEntry.is_home,
        )
        .join(NbaGame, NbaGame.id == TeamScheduleEntry.game_id)
        .join(team, team.id == TeamScheduleEntry.team_id)
        .join(opponent, opponent.id == TeamScheduleEntry.opponent_team_id)
        .where(
            TeamScheduleEntry.season == parsed.season,
            TeamScheduleEntry.season_type == SeasonType.REGULAR,
        )
    ).all()
    observed = {
        (nba_game_id, team_nba_id, opponent_nba_id, game_date, bool(is_home))
        for nba_game_id, team_nba_id, opponent_nba_id, game_date, is_home in observed_rows
    }
    if len(observed_rows) != len(observed):
        raise _schedule_contract(
            f"season {parsed.season} persisted {len(observed_rows)} schedule rows that are not "
            "distinct on (game, team, opponent, date, home)"
        )
    if observed != expected:
        missing = sorted(str(row) for row in expected - observed)[:3]
        extra = sorted(str(row) for row in observed - expected)[:3]
        raise _schedule_contract(
            f"season {parsed.season} persisted schedule does not match the parsed cohort: "
            f"expected {len(expected)} rows for {len(parsed.games)} games, found "
            f"{len(observed_rows)}; missing={missing}, unexpected={extra}"
        )
    return len(observed_rows)


def _register_schedule_refresh(
    session: Session,
    parsed: ScheduleParseResult,
    *,
    persisted_team_row_count: int,
) -> None:
    """Stamp the schedule refresh cohort for the season just imported.

    The version is ``schedule_content_version`` over the persisted
    ``team_schedule`` rows — the same function ``check_cohort`` recomputes
    with, so a registered version and a validated version can never be
    computed two different ways. A re-import that changes nothing converges on
    the same version rather than advancing "current" for no reason, the same
    idempotency guarantee ``import_schedule`` already gives its own rows,
    applied one level up to the registry ``schedule-context`` consumers
    (``quant``) key their ``schedule_version`` stamps against. See
    ``hoops_gm.db.lineage``.

    **The version does not cover the pending set, and cannot.** It is computed
    from persisted ``team_schedule`` rows, and a pending game has none — it
    has no teams, so there is nothing to persist. Two refreshes differing only
    in which games are pending therefore share a version. Verified rather than
    reasoned to: the demo seed's 10-source cohort and its 12-source, 2-pending
    successor both fingerprint to ``9bcac1c60490b41a``.

    Two consequences. A consumer must not cache the pending set keyed on the
    schedule version alone — read it from the completeness block of the
    refresh it is holding. And ``verify_refresh`` cannot detect a forged
    pending list, because there is no persisted artifact to recompute it from;
    it remains able to detect a forged *resolved* cohort, which is the case
    the completeness contract was written for. The hole closes for each game
    as the bracket is drawn, because that is precisely when rows appear.

    **A third face of the same root cause, worth knowing here:**
    ``record_refresh`` is idempotent on ``(type, key, version, season)`` and
    overwrites ``summary`` in place on a hit. Because the version does not
    move with the pending set, two imports differing only in which games are
    pending collide on one row and the later summary replaces the earlier.
    That is the right outcome — the newer observation of the source wins —
    but it means the *history* of the pending set is not kept anywhere, and a
    consumer holding an older block cannot tell it has been superseded by
    comparing versions. Only ``refreshed_at`` moves.
    """

    completeness = ScheduleCompleteness(
        season=parsed.season,
        season_type=SeasonType.REGULAR,
        source_game_count=parsed.source_game_count,
        resolved_game_count=len(parsed.games),
        unresolved_game_ids=parsed.unresolved_game_ids,
        persisted_team_row_count=persisted_team_row_count,
        pending_games=parsed.pending_games,
    )
    version = schedule_content_version(
        session,
        season=parsed.season,
        season_type=SeasonType.REGULAR,
    )
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version=version,
        source="nba_api:ScheduleLeagueV2",
        season=parsed.season,
        summary={
            # Kept flat as well as inside the completeness block: existing
            # readers of the refresh summary predate the block.
            "team_schedule_rows": persisted_team_row_count,
            SCHEDULE_COMPLETENESS_SUMMARY_KEY: completeness.as_summary(),
        },
    )


def _schedule_contract(message: str) -> SourceContractError:
    """The schedule source's completeness contract was not met.

    ``SourceContractError`` rather than a persistence-specific exception: every
    condition raised here means the payload we were handed does not describe a
    complete season, which is upstream drift and must be as loud as a parser
    rejecting a changed field (ADR-006).
    """

    return SourceContractError(
        message,
        source=SCHEDULE_SOURCE,
        endpoint=SCHEDULE_ENDPOINT,
    )


def import_box_scores(session: Session, records: Sequence[PlayerBoxScoreRecord]) -> ImportCounts:
    lock_refresh_scope(
        session,
        artifact_type=RefreshArtifactType.SOURCE,
        artifact_key=SCHEDULE_CONTEXT_SOURCE_KEY,
        season=None,
    )
    counts = ImportCounts()
    maps = LookupMaps.load(session)
    games, players, teams = maps.games, maps.players, maps.teams
    existing = {(row.player_id, row.game_id): row for row in session.scalars(select(PlayerGameLog))}

    for record in records:
        game_id = games.get(record.nba_game_id)
        player_id = players.get(str(record.nba_player_id))
        team_id = teams.get(record.nba_team_id)
        if game_id is None or player_id is None or team_id is None:
            counts.skipped += 1
            continue

        log = existing.get((player_id, game_id))
        if log is None:
            log = PlayerGameLog(player_id=player_id, game_id=game_id, team_id=team_id)
            session.add(log)
            counts.created += 1
        else:
            counts.updated += 1

        log.team_id = team_id
        log.started = record.started
        log.seconds_played = record.seconds_played
        log.field_goals_made = record.field_goals_made
        log.field_goals_attempted = record.field_goals_attempted
        log.three_pointers_made = record.three_pointers_made
        log.three_pointers_attempted = record.three_pointers_attempted
        log.free_throws_made = record.free_throws_made
        log.free_throws_attempted = record.free_throws_attempted
        log.points = record.points
        log.offensive_rebounds = record.offensive_rebounds
        log.defensive_rebounds = record.defensive_rebounds
        log.rebounds = record.rebounds
        log.assists = record.assists
        log.steals = record.steals
        log.blocks = record.blocks
        log.turnovers = record.turnovers
        log.personal_fouls = record.personal_fouls
        log.plus_minus = record.plus_minus

    session.flush()
    return counts


@dataclass(frozen=True)
class LookupMaps:
    """Natural-key → surrogate-key maps, built once and reused.

    The participation backfill calls :func:`import_participation` once per
    game — up to 1,230 times for a season. Rebuilding these inside it loaded
    every game, every NBA external id and every team on each call: roughly
    7,700 ORM objects per game, about 9.5 million instantiations per season,
    and worse across a multi-season run because the games table keeps growing.
    """

    games: dict[str, int]
    players: dict[str, int]
    teams: dict[int, int]

    @classmethod
    def load(cls, session: Session) -> LookupMaps:
        return cls(
            games={g.nba_game_id: g.id for g in session.scalars(select(NbaGame))},
            players={
                row.external_id: row.player_id
                for row in session.scalars(
                    select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.NBA)
                )
            },
            teams={t.nba_team_id: t.id for t in session.scalars(select(NbaTeam))},
        )


def import_participation(
    session: Session,
    participation: GameParticipation,
    *,
    lookups: LookupMaps | None = None,
) -> ImportCounts:
    """Write one game's participation ledger.

    ``inactive_list_available`` is written on **every** row of the game, not
    only the inactive ones. It is a fact about what the source offered for that
    game, and a later query asking "how many players were inactive on this
    date" needs to know whether a zero means nobody or means nothing was
    reported — the distinction ``BoxScoreSummaryV2`` erased for an entire
    season.

    Pass ``lookups`` when importing many games; see :class:`LookupMaps`.
    """
    counts = ImportCounts()
    maps = lookups or LookupMaps.load(session)
    game_id = maps.games.get(participation.nba_game_id)
    if game_id is None:
        counts.skipped += len(participation.records)
        return counts

    existing = {
        row.player_id: row
        for row in session.scalars(
            select(PlayerParticipation).where(PlayerParticipation.game_id == game_id)
        )
    }

    for record in participation.records:
        player_id = maps.players.get(str(record.nba_player_id))
        team_id = maps.teams.get(record.nba_team_id)
        if player_id is None or team_id is None:
            counts.skipped += 1
            continue

        row = existing.get(player_id)
        if row is None:
            row = PlayerParticipation(player_id=player_id, game_id=game_id, team_id=team_id)
            session.add(row)
            existing[player_id] = row
            counts.created += 1
        else:
            counts.updated += 1

        row.team_id = team_id
        row.outcome = record.outcome
        row.reason = record.reason
        row.raw_comment = record.raw_comment
        row.seconds_played = record.seconds_played
        row.source = ExternalSource.NBA
        row.inactive_list_available = participation.inactives_available

    session.flush()
    return counts


# --------------------------------------------------------------------------
# Injury report
# --------------------------------------------------------------------------


def import_injury_report_entries(
    session: Session,
    entries: Sequence[InjuryReportEntryRecord],
    *,
    source_url: str,
) -> ImportCounts:
    """Write one report capture's entries idempotently, by natural key.

    ``(report_timestamp, team_raw, player_name_raw, game_date)`` identifies a
    row: an identical capture re-ingested twice converges rather than
    duplicates, and a later capture at a *different* timestamp is genuine
    history, never an overwrite of an earlier one — see
    ``db.models.injury_report`` on why the timestamp is part of the key
    rather than a mere column. ``game_date`` is part of the key for the same
    reason: one report capture's rolling window genuinely lists the same
    player on the same team twice, once per calendar date, when that team
    plays a back-to-back the very next night. Dropping ``game_date`` from the
    key let the second night's row silently overwrite the first night's as an
    ordinary "update" — found by independent review before any evidence
    relying on this table was trusted.

    ``team_id``, ``game_id`` and ``player_id`` are resolved best-effort and
    left ``NULL`` on any ambiguity, never guessed. Team resolves the report's
    own free-text ``team_raw`` (e.g. ``"Sacramento Kings"``) directly against
    ``nba_teams.name``, which ``import_teams`` populates from the exact same
    "City Nickname" string the stats API's own ``full_name`` field uses — an
    unambiguous match that needs no other row for context. That resolution is
    then cross-verified against the matchup's own tricode pair
    (``matchup_raw``, e.g. ``"SAC@MIL"``): the resolved team's abbreviation
    must be one of the two, or the row is left unresolved. This deliberately
    does **not** infer which tricode is "this" row's team from the order rows
    happen to appear in the ``entries`` sequence — a caller importing a
    partial subset of a report (e.g. only one team's rows because the other
    team's report had not been filed yet) or a re-ordered sequence would
    otherwise see appearance order disagree with the report's actual
    away-then-home structure and resolve a team to its opponent. Game
    resolves from the same verified tricode pair.

    ``source_url`` is set only when a row is first created. A later capture
    that converges on the identical natural key (two different requested
    instants resolving to the same masthead) never overwrites the original
    discovery URL with an unrelated later request's URL — provenance is
    "where this row was first observed", not "the most recent request that
    happened to touch it".

    The "existing row" lookup is scoped to the distinct ``report_timestamp``
    values actually present in ``entries`` (normally exactly one — a single
    fetch is a single report capture), not a full-table reload: this import
    is called once per fetched candidate during a historical backfill, and
    reloading the entire (ever-growing) table on every call would make a
    multi-date backfill's cost grow with the table's total size rather than
    with the size of the one capture being imported.
    """
    counts = ImportCounts()
    teams = list(session.scalars(select(NbaTeam)))
    teams_by_abbr = {t.abbreviation: t.id for t in teams}
    team_abbr_by_id = {t.id: t.abbreviation for t in teams}
    teams_by_name: dict[str, list[int]] = {}
    for t in teams:
        teams_by_name.setdefault(t.name, []).append(t.id)
    games_by_key = {
        (g.home_team_id, g.away_team_id, g.game_date): g.id
        for g in session.scalars(select(NbaGame))
    }
    players_by_norm: dict[str, list[int]] = {}
    player_team: dict[int, int | None] = {}
    for player in session.scalars(select(Player)):
        players_by_norm.setdefault(player.normalized_name, []).append(player.id)
        player_team[player.id] = player.current_team_id

    report_timestamps = {record.report_timestamp for record in entries}
    existing: dict[tuple[datetime, str, str, date], InjuryReportEntry] = {}
    if report_timestamps:
        existing_stmt = select(InjuryReportEntry).where(
            InjuryReportEntry.report_timestamp.in_(report_timestamps)
        )
        existing = {
            (row.report_timestamp, row.team_raw, row.player_name_raw, row.game_date): row
            for row in session.scalars(existing_stmt)
        }

    for record in entries:
        team_id = _resolve_team_id(record, teams_by_name, team_abbr_by_id)
        game_id = _resolve_game_id(record, teams_by_abbr, games_by_key)
        player_id = _resolve_player_id(record, team_id, player_team, players_by_norm)

        key = (
            record.report_timestamp,
            record.team_raw,
            record.player_name_raw,
            record.game_date,
        )
        row = existing.get(key)
        if row is None:
            row = InjuryReportEntry(
                report_timestamp=record.report_timestamp,
                team_raw=record.team_raw,
                player_name_raw=record.player_name_raw,
                game_date=record.game_date,
                source_url=source_url,
            )
            session.add(row)
            existing[key] = row
            counts.created += 1
        else:
            counts.updated += 1

        row.game_time_raw = record.game_time_raw
        row.matchup_raw = record.matchup_raw
        row.team_id = team_id
        row.game_id = game_id
        row.player_id = player_id
        row.status_raw = record.status_raw
        row.status = record.status
        row.reason_raw = record.reason_raw
        row.source = ExternalSource.NBA
        # Only this validated importer writes CURRENT. The model/database
        # default is deliberately LEGACY so omitted direct or raw inserts
        # cannot acquire trusted provenance by accident. Written on every
        # create and update so a genuine re-import promotes the exact row it
        # has validated under the fixed natural key.
        row.import_schema_version = CURRENT_EVIDENCE_SCHEMA_VERSION

    session.flush()
    return counts


def _matchup_tricodes(matchup_raw: str) -> tuple[str, str] | None:
    """``"SAC@MIL"`` -> ``("SAC", "MIL")`` (away, home), or ``None`` if malformed."""
    away, sep, home = matchup_raw.partition("@")
    if not sep or not away or not home:
        return None
    return away, home


def _resolve_team_id(
    record: InjuryReportEntryRecord,
    teams_by_name: dict[str, list[int]],
    team_abbr_by_id: dict[int, str],
) -> int | None:
    """Resolve ``team_raw`` to a team, verified against the matchup tricode.

    Matches the report's free-text ``team_raw`` (e.g. ``"Sacramento Kings"``)
    directly against ``nba_teams.name`` — a name+city string, not an
    order-dependent heuristic — then cross-checks that the resolved team's
    own abbreviation is actually one of the two tricodes in ``matchup_raw``.
    Left ``NULL`` if the name does not match exactly one team, or if the
    matched team is not part of this row's own matchup: either case means the
    row's evidence disagrees with itself, and a guess would be worse than no
    link at all.
    """
    candidates = teams_by_name.get(record.team_raw, [])
    if len(candidates) != 1:
        return None
    team_id = candidates[0]
    tricodes = _matchup_tricodes(record.matchup_raw)
    if tricodes is None or team_abbr_by_id.get(team_id) not in tricodes:
        return None
    return team_id


def _resolve_game_id(
    record: InjuryReportEntryRecord,
    teams_by_abbr: dict[str, int],
    games_by_key: dict[tuple[int, int, date], int],
) -> int | None:
    tricodes = _matchup_tricodes(record.matchup_raw)
    if tricodes is None:
        return None
    away_tri, home_tri = tricodes
    away_id = teams_by_abbr.get(away_tri)
    home_id = teams_by_abbr.get(home_tri)
    if away_id is None or home_id is None:
        return None
    return games_by_key.get((home_id, away_id, record.game_date))


def _resolve_player_id(
    record: InjuryReportEntryRecord,
    team_id: int | None,
    player_team: dict[int, int | None],
    players_by_norm: dict[str, list[int]],
) -> int | None:
    if not record.player_name_raw:
        return None
    candidates = players_by_norm.get(normalize_name(record.player_name_raw).key, [])
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1 and team_id is not None:
        # Disambiguate by current team. Only accept a match that is unique
        # after narrowing — an unresolved ambiguity is left NULL rather than
        # guessed, per R7.
        on_team = [pid for pid in candidates if player_team.get(pid) == team_id]
        if len(on_team) == 1:
            return on_team[0]
    return None
