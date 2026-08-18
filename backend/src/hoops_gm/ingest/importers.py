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
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.lineage import content_fingerprint, record_refresh
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
from hoops_gm.db.models.league import League
from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog
from hoops_gm.identity.names import normalize_name
from hoops_gm.identity.resolver import Resolution
from hoops_gm.ingest.league_settings import LeagueSettingsDocument
from hoops_gm.ingest.nba.models import (
    GameParticipation,
    NbaGameRecord,
    NbaPlayerRecord,
    NbaTeamRecord,
    PlayerBoxScoreRecord,
)
from hoops_gm.ingest.nba.schedule import ScheduleGameRecord


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


def import_schedule(session: Session, records: Sequence[ScheduleGameRecord]) -> ImportCounts:
    """Write resolved games and their two per-team schedule rows idempotently."""
    counts = import_games(session, [record.game for record in records])
    teams = {team.nba_team_id: team.id for team in session.scalars(select(NbaTeam))}
    games = {game.nba_game_id: game for game in session.scalars(select(NbaGame))}
    existing = {
        (entry.game_id, entry.team_id): entry
        for entry in session.scalars(select(TeamScheduleEntry))
    }

    for record in records:
        game = games.get(record.game.nba_game_id)
        home_id = teams.get(record.home_nba_team_id)
        away_id = teams.get(record.away_nba_team_id)
        if game is None or home_id is None or away_id is None:
            counts.skipped += 1
            continue
        for team_id, opponent_id, is_home in (
            (home_id, away_id, True),
            (away_id, home_id, False),
        ):
            entry = existing.get((game.id, team_id))
            if entry is None:
                session.add(
                    TeamScheduleEntry(
                        season=record.game.season,
                        season_type=SeasonType.REGULAR,
                        game_id=game.id,
                        team_id=team_id,
                        opponent_team_id=opponent_id,
                        game_date=record.game.game_date,
                        is_home=is_home,
                    )
                )
                counts.created += 1
            else:
                entry.season = record.game.season
                entry.season_type = SeasonType.REGULAR
                entry.opponent_team_id = opponent_id
                entry.game_date = record.game.game_date
                entry.is_home = is_home
                counts.updated += 1
    session.flush()
    _register_schedule_refresh(session, records)
    session.flush()
    return counts


def _register_schedule_refresh(session: Session, records: Sequence[ScheduleGameRecord]) -> None:
    """Stamp a schedule refresh cohort from the season(s) just imported.

    The version is a content fingerprint over the current ``team_schedule``
    rows for each season touched, so a re-import that changes nothing
    converges on the same version rather than advancing "current" for no
    reason — the same idempotency guarantee ``import_schedule`` already gives
    its own rows, applied one level up to the refresh registry
    ``schedule-context`` consumers (``quant``) key their own
    ``schedule_version`` stamps against. See ``hoops_gm.db.lineage``.
    """
    seasons = {record.game.season for record in records}
    for season in sorted(seasons):
        rows = session.scalars(
            select(TeamScheduleEntry)
            .where(TeamScheduleEntry.season == season)
            .order_by(TeamScheduleEntry.game_id, TeamScheduleEntry.team_id)
        ).all()
        if not rows:
            continue
        fingerprint_parts = [
            f"{row.game_id}:{row.team_id}:{row.opponent_team_id}:"
            f"{row.game_date.isoformat()}:{row.is_home}"
            for row in rows
        ]
        version = content_fingerprint(fingerprint_parts)
        record_refresh(
            session,
            artifact_type=RefreshArtifactType.SCHEDULE,
            version=version,
            source="nba_api:ScheduleLeagueV2",
            season=season,
            summary={"team_schedule_rows": len(rows)},
        )


def import_box_scores(session: Session, records: Sequence[PlayerBoxScoreRecord]) -> ImportCounts:
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
