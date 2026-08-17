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

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models.availability import PlayerParticipation
from hoops_gm.db.models.enums import (
    ExternalSource,
    FieldEvidence,
    GameStatus,
    MatchMethod,
    SeasonType,
)
from hoops_gm.db.models.identity import NbaTeam, Player, PlayerExternalId
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog
from hoops_gm.identity.names import normalize_name
from hoops_gm.identity.resolver import Resolution
from hoops_gm.ingest.nba.models import (
    GameParticipation,
    NbaGameRecord,
    NbaPlayerRecord,
    NbaTeamRecord,
    PlayerBoxScoreRecord,
)


@dataclass
class ImportCounts:
    """What an import did, so a backfill can report progress honestly."""

    created: int = 0
    updated: int = 0
    skipped: int = 0

    def __str__(self) -> str:
        return f"{self.created} created, {self.updated} updated, {self.skipped} skipped"


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

    Two properties are load-bearing and both concern *not* overwriting things.

    **A manual override is final.** If a human has adjudicated a row, an
    automated pass leaves it alone. That is the entire purpose of the flag, and
    a resolver that re-decides a human's call is worse than no resolver.

    **Only accepted matches are written by default.** A row that needs review
    belongs in the report, not in the crosswalk. Writing a low-confidence guess
    and relying on ``confidence`` to warn downstream assumes every consumer
    checks it, and the one that does not is the one that corrupts a number.

    The resolution's ``target`` is the canonical side, so its key is an NBA
    person id and the row being created maps *this* source's identifier onto
    the player that id already belongs to.
    """
    counts = ImportCounts()
    nba_links = {
        row.external_id: row.player_id
        for row in session.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.NBA)
        )
    }
    existing = {
        row.external_id: row
        for row in session.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == source)
        )
    }

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
            link = PlayerExternalId(
                source=source,
                external_id=external_id,
                current_for_source=source.value,
            )
            session.add(link)
            counts.created += 1
        else:
            counts.updated += 1

        link.player_id = player_id
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


def import_box_scores(session: Session, records: Sequence[PlayerBoxScoreRecord]) -> ImportCounts:
    counts = ImportCounts()
    games, players, teams = _lookup_maps(session)
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


def import_participation(session: Session, participation: GameParticipation) -> ImportCounts:
    """Write one game's participation ledger.

    ``inactive_list_available`` is written on **every** row of the game, not
    only the inactive ones. It is a fact about what the source offered for that
    game, and a later query asking "how many players were inactive on this
    date" needs to know whether a zero means nobody or means nothing was
    reported — the distinction ``BoxScoreSummaryV2`` erased for an entire
    season.
    """
    counts = ImportCounts()
    games, players, teams = _lookup_maps(session)
    game_id = games.get(participation.nba_game_id)
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
        player_id = players.get(str(record.nba_player_id))
        team_id = teams.get(record.nba_team_id)
        if player_id is None or team_id is None:
            counts.skipped += 1
            continue

        row = existing.get(player_id)
        if row is None:
            row = PlayerParticipation(player_id=player_id, game_id=game_id, team_id=team_id)
            session.add(row)
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


def _lookup_maps(session: Session) -> tuple[dict[str, int], dict[str, int], dict[int, int]]:
    games = {g.nba_game_id: g.id for g in session.scalars(select(NbaGame))}
    players = {
        row.external_id: row.player_id
        for row in session.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.NBA)
        )
    }
    teams = {t.nba_team_id: t.id for t in session.scalars(select(NbaTeam))}
    return games, players, teams
