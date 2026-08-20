"""Multi-season backfill, and the crosswalk build.

    python -m hoops_gm.ingest.backfill crosswalk
    python -m hoops_gm.ingest.backfill season 2024-25 --with-participation

## Why it is shaped this way

A season's production comes from **two** requests — ``LeagueGameFinder`` and
``PlayerGameLogs``, the latter returning every player-game in the season in one
response — while the participation facts need **two per game**, because only
the per-game endpoints carry DNP comments and inactive lists. That is roughly
2,460 requests per season at 1.1 seconds each: about three quarters of an hour.

Three consequences, all deliberate:

* **Participation is opt-in** (``--with-participation``). Production and
  availability are separated everywhere else in this project; separating how
  they are fetched follows, and it means a quick stats backfill does not
  require a 45-minute commitment.
* **Every response is cached**, and a completed game's box score never
  expires, so an interrupted backfill resumes instead of restarting.
* **A per-game failure does not abort the run.** One unparseable game out of
  1,230 must not cost the other 1,229; failures are counted and reported at the
  end, loudly, with the game ids. Silently continuing would be the wrong
  trade — reporting them is what makes continuing acceptable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.calendar import (
    activate_deadline_calendar,
    derive_deadline_calendar,
    project_scoring_periods,
)
from hoops_gm.core.config import Settings, get_settings
from hoops_gm.db.models.enums import ExternalSource
from hoops_gm.db.models.league import League, LeagueScoringProfile
from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot
from hoops_gm.db.session import Database
from hoops_gm.identity import IdentityResolver, ResolvableRecord, render_summary, to_csv
from hoops_gm.identity.report import partition
from hoops_gm.identity.resolver import Resolution
from hoops_gm.ingest.errors import SourceContractError, SourceError
from hoops_gm.ingest.fantrax_official import FantraxOfficialClient
from hoops_gm.ingest.importers import (
    ImportCounts,
    LookupMaps,
    import_box_scores,
    import_games,
    import_league_settings,
    import_nba_players,
    import_participation,
    import_resolutions,
    import_teams,
)
from hoops_gm.ingest.league_settings import (
    BridgeLeagueSettingsObservation,
    load_bridge_league_settings_capture,
    merge_settings,
)
from hoops_gm.ingest.nba import (
    NbaGameRecord,
    NbaStatsClient,
    PlayerBoxScoreRecord,
    combine_game_participation,
    parse_box_score_summary_v3,
    parse_box_score_traditional_v3,
    parse_common_all_players,
    parse_league_game_finder,
    parse_player_game_logs,
    parse_teams,
)
from hoops_gm.ingest.rawstore import RawPayloadStore
from hoops_gm.scoring.profiles import activate_scoring_profile_version, build_scoring_profile

DEFAULT_RAW_ROOT = Path("data") / "raw"
DEFAULT_REPORT_DIR = Path("data") / "reports"


@dataclass
class BackfillResult:
    """What a run did, including what it could not do."""

    steps: dict[str, ImportCounts] = field(default_factory=dict)
    failures: list[tuple[str, str]] = field(default_factory=list)

    def render(self) -> str:
        lines = [f"  {name:24s} {counts}" for name, counts in self.steps.items()]
        if self.failures:
            lines.append("")
            lines.append(f"  {len(self.failures)} FAILURES:")
            lines.extend(f"    {what}: {why}" for what, why in self.failures[:20])
            if len(self.failures) > 20:
                lines.append(f"    ... and {len(self.failures) - 20} more")
        return "\n".join(lines)


def build_clients(settings: Settings | None = None) -> tuple[NbaStatsClient, FantraxOfficialClient]:
    settings = settings or get_settings()
    store = RawPayloadStore(DEFAULT_RAW_ROOT)
    # Unwrapped on its own line rather than inline. `SecretStr` exists so a
    # credential cannot be printed by accident, and the moment it is unwrapped
    # is worth being able to see at a glance.
    configured = settings.fantrax_user_secret_id
    user_secret = configured.get_secret_value() if configured else None
    return (
        NbaStatsClient(store=store),
        FantraxOfficialClient(store=store, user_secret_id=user_secret),
    )


# --------------------------------------------------------------------------
# League settings
# --------------------------------------------------------------------------


def ingest_official_league_settings(
    session: Session,
    *,
    fantrax: FantraxOfficialClient,
    league: League,
    fantrax_league_id: str,
    bridge: BridgeLeagueSettingsObservation | None = None,
) -> ImportCounts:
    """Fetch and persist one official snapshot; season mismatch fails loudly."""
    if league.fantrax_league_id is None:
        raise ValueError("target league must be linked to Fantrax before settings ingest")
    if league.fantrax_league_id != fantrax_league_id:
        raise ValueError(
            "requested Fantrax league does not match target league: "
            f"requested={fantrax_league_id!r}, linked={league.fantrax_league_id!r}"
        )
    info = fantrax.get_league_info(fantrax_league_id)
    if info.settings is None:
        raise RuntimeError("getLeagueInfo parser returned no settings document")
    if info.source_payload_sha256 is None:
        raise RuntimeError("getLeagueInfo transport returned no raw payload digest")
    if info.source_observed_at is None:
        raise RuntimeError("getLeagueInfo transport returned no observation timestamp")
    document = info.settings
    source_payload_sha256 = info.source_payload_sha256
    observed_at = info.source_observed_at
    if bridge is not None:
        document = merge_settings(document, bridge.document)
        source_payload_sha256 = hashlib.sha256(
            json.dumps(
                {
                    "fantrax_bridge": bridge.source_payload_sha256,
                    "fantrax_official": info.source_payload_sha256,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        observed_at = max(observed_at, bridge.observed_at)
    return import_league_settings(
        session,
        league=league,
        document=document,
        source_payload_sha256=source_payload_sha256,
        observed_at=observed_at,
    )


def derive_scoring_profile(
    session: Session,
    *,
    league: League,
    name: str = "default",
    activate: bool = False,
) -> LeagueScoringProfile:
    """Derive a league's scoring profile from its current settings snapshot.

    This is the production seam between an already-ingested settings snapshot
    (``ingest_official_league_settings`` above) and
    ``hoops_gm.scoring.profiles.build_scoring_profile``: it looks up the
    league's current (highest-version) ``LeagueSettingsSnapshot`` and derives
    from it, rather than requiring an operator to look that up by hand.

    Never activates the derived profile unless ``activate=True`` is passed
    explicitly -- creating a profile is safe to run repeatedly (it is
    idempotent by content; see ``build_scoring_profile``), but making it the
    league's active profile changes what every subsequent read sees, and
    that is not something a routine re-derivation should do as a side
    effect.
    """
    current_snapshot = session.scalar(
        select(LeagueSettingsSnapshot)
        .where(LeagueSettingsSnapshot.league_id == league.id)
        .order_by(LeagueSettingsSnapshot.version.desc())
        .limit(1)
    )
    if current_snapshot is None:
        raise ValueError(
            f"league {league.id!r} has no settings snapshot to derive a scoring profile from "
            "-- run league-settings ingest first"
        )
    profile = build_scoring_profile(
        session,
        league=league,
        settings_snapshot=current_snapshot,
        name=name,
    )
    if activate:
        activate_scoring_profile_version(session, profile)
    return profile


# --------------------------------------------------------------------------
# Crosswalk
# --------------------------------------------------------------------------


def build_crosswalk(
    session: Session,
    *,
    nba: NbaStatsClient,
    fantrax: FantraxOfficialClient,
    season: str,
    report_dir: Path | None = None,
) -> BackfillResult:
    """Build the NBA↔Fantrax crosswalk and write the report for the tail.

    ``season`` must be the **current** season. Against a historical one every
    player who moved in the offseason produces a spurious team disagreement —
    which, before it was understood, dropped Giannis Antetokounmpo, Luguentz
    Dort and Naz Reid out of the crosswalk entirely.
    """
    result = BackfillResult()

    result.steps["nba teams"] = import_teams(session, parse_teams(nba.static_teams()))

    nba_players = parse_common_all_players(nba.common_all_players(season=season, only_current=True))
    result.steps["nba players"] = import_nba_players(session, nba_players)

    fantrax_players = fantrax.get_player_ids()

    # NBA is the canonical side: every stat in this project keys to an NBA
    # person id, so a Fantrax row is resolved *onto* an NBA player.
    targets = [
        ResolvableRecord.build(
            key=str(p.nba_player_id),
            name=p.display_last_comma_first,
            team=p.team_abbreviation,
        )
        for p in nba_players
    ]
    sources = [
        ResolvableRecord.build(key=p.fantrax_id, name=p.name, team=p.team, position=p.position)
        for p in fantrax_players.players
    ]
    report = IdentityResolver(targets).resolve(sources)

    result.steps["fantrax crosswalk"] = import_resolutions(
        session,
        # All resolutions, not only the accepted ones: a match the resolver has
        # since retracted must be superseded, and that cannot be detected from
        # the accepted set alone.
        report.all_resolutions(),
        source=ExternalSource.FANTRAX,
    )

    # The three cross-reference identifiers ride along on an accepted match.
    # They bridge to nothing outside Fantrax — that was checked — but they
    # de-duplicate within it and they survive Fantrax rotating its own id.
    by_fantrax_id = {p.fantrax_id: p for p in fantrax_players.players}
    for source, attribute in (
        (ExternalSource.FANTRAX_SPORTRADAR, "sport_radar_id"),
        (ExternalSource.FANTRAX_STATS_INC, "stats_inc_id"),
        (ExternalSource.FANTRAX_ROTOWIRE, "rotowire_id"),
    ):
        aliased = [
            _with_key(resolution, value)
            for resolution in report.all_resolutions()
            if (player := by_fantrax_id.get(resolution.source_record.key)) is not None
            and (value := getattr(player, attribute))
        ]
        result.steps[f"{source.value}"] = import_resolutions(session, aliased, source=source)

    destination = report_dir or DEFAULT_REPORT_DIR
    destination.mkdir(parents=True, exist_ok=True)
    ambiguous, low_confidence, no_candidate = partition(report)
    path = destination / "unmatched_players.csv"
    path.write_text(to_csv([*ambiguous, *low_confidence, *no_candidate]), encoding="utf-8")

    print(render_summary(report, source_label="fantrax players -> nba"))
    print(f"\n  unmatched report: {path}")
    return result


def _with_key(resolution: Resolution, key: str) -> Resolution:
    """A copy of a resolution keyed by an alternative source identifier."""
    return replace(resolution, source_record=replace(resolution.source_record, key=key))


# --------------------------------------------------------------------------
# NBA identity anchors
# --------------------------------------------------------------------------


def backfill_nba_identity(
    session: Session,
    *,
    nba: NbaStatsClient,
    season: str,
    progress: Callable[[str], None] = print,
) -> BackfillResult:
    """Import the NBA-side identity anchors every other ingest step depends on.

    Teams and canonical NBA player ids have to exist before games, box scores or
    participation can be attached to anything. This was previously an
    undocumented interactive snippet, which meant the first step of regenerating
    a cohort was the one step no committed command described.
    """
    result = BackfillResult()
    result.steps["teams"] = import_teams(session, parse_teams(nba.static_teams()))
    progress(f"  teams: {result.steps['teams']}")
    result.steps["nba players"] = import_nba_players(
        session,
        parse_common_all_players(nba.common_all_players(season=season, only_current=False)),
    )
    progress(f"  nba players: {result.steps['nba players']}")
    return result


# --------------------------------------------------------------------------
# Season
# --------------------------------------------------------------------------


def backfill_season(
    session: Session,
    *,
    nba: NbaStatsClient,
    season: str,
    season_type: str = "Regular Season",
    with_participation: bool = False,
    start: date | None = None,
    end: date | None = None,
    limit_games: int | None = None,
    progress: Callable[[str], None] = print,
) -> BackfillResult:
    """Backfill one season's games, box scores and — optionally — participation."""
    result = BackfillResult()
    parsed_season_type = _league_game_finder_season_type(season_type)

    games = parse_league_game_finder(
        nba.league_game_finder(season=season, season_type=season_type),
        season=season,
        season_type=parsed_season_type,
    )
    logs = parse_player_game_logs(nba.player_game_logs(season=season, season_type=season_type))
    _require_matching_season_game_ids(games, logs, season=season, season_type=season_type)

    result.steps["games"] = import_games(session, games)
    progress(f"  games: {result.steps['games']}")

    result.steps["box scores"] = import_box_scores(session, logs)
    progress(f"  box scores: {result.steps['box scores']}")

    if not with_participation:
        return result

    selected = _participation_games_in_scope(
        games,
        start=start,
        end=end,
        limit_games=limit_games,
    )
    totals = ImportCounts()
    progress(
        f"  participation: {len(selected)} games at ~2 requests each; "
        f"expect roughly {len(selected) * 2 * 1.1 / 60:.0f} minutes"
    )

    # Built once. Inside the loop this reloaded every game, every NBA external
    # id and every team per game — roughly 7,700 ORM objects each, ~9.5 million
    # per season, and worse across a multi-season run as the games table grows.
    lookups = LookupMaps.load(session)

    for index, game in enumerate(selected, start=1):
        try:
            _, dressed = parse_box_score_traditional_v3(nba.box_score_traditional(game.nba_game_id))
            summary_game, summary = parse_box_score_summary_v3(
                nba.box_score_summary(game.nba_game_id)
            )
            summary_game = _validate_summary_game_identity(game, summary_game)
            # ``LeagueGameFinder`` gives a local date and no instant;
            # ``BoxScoreSummaryV3`` gives ``gameTimeUTC``. Rest-day and
            # back-to-back detection need the instant, so it is written back
            # while the per-game endpoint is being fetched anyway.
            if summary_game.tipoff_utc is not None:
                import_games(session, [replace(game, tipoff_utc=summary_game.tipoff_utc)])
            counts = import_participation(
                session, combine_game_participation(dressed, summary), lookups=lookups
            )
            totals.created += counts.created
            totals.updated += counts.updated
            totals.skipped += counts.skipped
        except SourceError as exc:
            # One bad game must not cost the other 1,229. Counted and named at
            # the end rather than swallowed.
            result.failures.append((game.nba_game_id, str(exc)))

        if index % 100 == 0:
            progress(f"    {index}/{len(selected)} games — {totals}")
        session.commit()

    result.steps["participation"] = totals
    return result


def _validate_summary_game_identity(
    schedule_game: NbaGameRecord,
    summary_game: NbaGameRecord | None,
) -> NbaGameRecord:
    """Fail when the independent per-game endpoint contradicts schedule identity."""
    if summary_game is None:
        raise SourceContractError(
            f"BoxScoreSummaryV3 lacks home/away identity for game {schedule_game.nba_game_id}",
            source="nba_stats",
            endpoint="BoxScoreSummaryV3",
        )
    fields = (
        "nba_game_id",
        "game_date",
        "home_team_id",
        "away_team_id",
        "home_score",
        "away_score",
    )
    conflicts = [
        f"{field}={getattr(schedule_game, field)!r}/{getattr(summary_game, field)!r}"
        for field in fields
        if getattr(schedule_game, field) != getattr(summary_game, field)
    ]
    if conflicts:
        raise SourceContractError(
            f"BoxScoreSummaryV3 contradicts LeagueGameFinder for "
            f"{schedule_game.nba_game_id}: {', '.join(conflicts)}",
            source="nba_stats",
            endpoint="BoxScoreSummaryV3",
        )
    return summary_game


def _require_matching_season_game_ids(
    games: Sequence[NbaGameRecord],
    logs: Sequence[PlayerBoxScoreRecord],
    *,
    season: str,
    season_type: str,
) -> None:
    """Require both whole-season sources to name exactly the same games."""

    schedule_ids = {game.nba_game_id for game in games}
    player_log_ids = {log.nba_game_id for log in logs}
    if schedule_ids == player_log_ids and schedule_ids:
        return

    schedule_only = sorted(schedule_ids - player_log_ids)
    player_log_only = sorted(player_log_ids - schedule_ids)
    raise SourceContractError(
        f"{season} {season_type} game identity mismatch: "
        f"LeagueGameFinder={len(schedule_ids)}, PlayerGameLogs={len(player_log_ids)}, "
        f"schedule_only={schedule_only[:10]}, player_log_only={player_log_only[:10]}",
        source="nba_stats",
        endpoint="LeagueGameFinder+PlayerGameLogs",
    )


def _league_game_finder_season_type(season_type: str) -> str:
    """Map the two supported source labels without treating every other value as playoffs."""
    parsed = {
        "Regular Season": "regular",
        "Playoffs": "playoffs",
    }.get(season_type)
    if parsed is None:
        raise ValueError(
            f"unsupported NBA season type {season_type!r}; expected 'Regular Season' or 'Playoffs'"
        )
    return parsed


def _participation_games_in_scope(
    games: Sequence[NbaGameRecord],
    *,
    start: date | None,
    end: date | None,
    limit_games: int | None,
) -> list[NbaGameRecord]:
    """Select a bounded participation window without changing season-wide production ingest."""
    if start is not None and end is not None and start > end:
        raise ValueError(f"participation start date {start} is after end date {end}")
    if limit_games is not None and limit_games < 0:
        raise ValueError("limit_games must be non-negative")

    selected = [
        game
        for game in games
        if (start is None or game.game_date >= start) and (end is None or game.game_date <= end)
    ]
    return selected[:limit_games] if limit_games is not None else selected


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - operator tool
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    crosswalk = subparsers.add_parser("crosswalk", help="build the NBA/Fantrax crosswalk")
    crosswalk.add_argument("--season", default="2026-27", help="the CURRENT season")

    nba_identity = subparsers.add_parser(
        "nba-identity",
        help="import NBA teams and canonical NBA player ids (run before any season backfill)",
    )
    nba_identity.add_argument("--season", default="2026-27", help="CommonAllPlayers season")

    season = subparsers.add_parser("season", help="backfill one season")
    season.add_argument("season", help="e.g. 2024-25")
    season.add_argument(
        "--season-type",
        choices=("Regular Season", "Playoffs"),
        default="Regular Season",
    )
    season.add_argument("--with-participation", action="store_true")
    season.add_argument("--start", type=date.fromisoformat, default=None)
    season.add_argument("--end", type=date.fromisoformat, default=None)
    season.add_argument("--limit-games", type=int, default=None)

    league_settings = subparsers.add_parser(
        "league-settings",
        help="ingest getLeagueInfo with no userSecretId",
    )
    league_settings.add_argument("league_id", type=int, help="local leagues.id")
    league_settings.add_argument("fantrax_league_id", help="non-secret Fantrax leagueId")
    league_settings.add_argument(
        "--bridge-capture",
        type=Path,
        default=None,
        help="explicit local bridge settings JSON; never captured automatically",
    )

    scoring_profile = subparsers.add_parser(
        "scoring-profile",
        help="derive a league's scoring profile from its current settings snapshot",
    )
    scoring_profile.add_argument("league_id", type=int, help="local leagues.id")
    scoring_profile.add_argument("--name", default="default")
    scoring_profile.add_argument(
        "--activate",
        action="store_true",
        help="also make this the league's active profile (opt-in only; not automatic)",
    )
    scoring_periods = subparsers.add_parser(
        "scoring-periods",
        help="project an active deadline calendar into date-based scoring periods",
    )
    scoring_periods.add_argument("league_id", type=int, help="local leagues.id")
    scoring_periods.add_argument(
        "--derive-and-activate",
        action="store_true",
        help="explicitly derive and activate current settings/schedule lineage first",
    )

    args = parser.parse_args(argv)

    settings = get_settings()
    database = Database.from_settings(settings)
    if args.command == "league-settings":
        # This endpoint was verified without credentials; do not attach a
        # configured userSecretId to a request that does not need one.
        official = FantraxOfficialClient(store=RawPayloadStore(DEFAULT_RAW_ROOT))
        bridge = (
            load_bridge_league_settings_capture(args.bridge_capture)
            if args.bridge_capture is not None
            else None
        )
        with database.session() as session:
            league = session.get(League, args.league_id)
            if league is None:
                parser.error(f"no league exists with id {args.league_id}")
            counts = ingest_official_league_settings(
                session,
                fantrax=official,
                league=league,
                fantrax_league_id=args.fantrax_league_id,
                bridge=bridge,
            )
        print(f"\n  league settings          {counts}")
        return 0

    if args.command == "scoring-profile":
        with database.session() as session:
            league = session.get(League, args.league_id)
            if league is None:
                parser.error(f"no league exists with id {args.league_id}")
            profile = derive_scoring_profile(
                session,
                league=league,
                name=args.name,
                activate=args.activate,
            )
        activation_note = " (activated)" if args.activate else " (not activated -- pass --activate)"
        print(f"\n  scoring profile          v{profile.version}{activation_note}")
        return 0

    if args.command == "scoring-periods":
        with database.session() as session:
            league = session.get(League, args.league_id)
            if league is None:
                parser.error(f"no league exists with id {args.league_id}")
            if args.derive_and_activate:
                calendar = derive_deadline_calendar(session, league).calendar
                activate_deadline_calendar(session, league, calendar.version)
            projection_result = project_scoring_periods(session, league)
        print(
            "\n  scoring periods          "
            f"{projection_result.created} created, {projection_result.replaced} replaced, "
            f"projection {projection_result.lineage.projection_version}"
        )
        return 0

    nba, fantrax = build_clients(settings)

    with database.session() as session:
        if args.command == "crosswalk":
            result = build_crosswalk(session, nba=nba, fantrax=fantrax, season=args.season)
        elif args.command == "nba-identity":
            result = backfill_nba_identity(session, nba=nba, season=args.season)
        else:
            result = backfill_season(
                session,
                nba=nba,
                season=args.season,
                season_type=args.season_type,
                with_participation=args.with_participation,
                start=args.start,
                end=args.end,
                limit_games=args.limit_games,
            )

    print("\n" + result.render())
    if result.failures:
        print(
            f"\n{len(result.failures)} games failed. That is not fine — read the "
            "errors above before trusting the availability ledger for this season.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
