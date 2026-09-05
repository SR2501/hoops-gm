"""Read-only league evidence for constructing a draft creation request."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models.league import FantasyTeam, League
from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot
from hoops_gm.draft.formats import DraftFormat, DraftFormatError, draft_format_from_league
from hoops_gm.draft.state import DraftLogError
from hoops_gm.ingest.league_settings import LeagueSettingsDocument


@dataclass(frozen=True, slots=True)
class DraftSetupTeam:
    """One persisted team a caller may explicitly bind to a draft seat."""

    fantasy_team_id: int
    display_name: str


@dataclass(frozen=True, slots=True)
class DraftSetupLeague:
    """Validated facts needed before calling ``create_draft``."""

    league_id: int
    name: str
    season: str
    format: DraftFormat
    owner_fantasy_team_id: int | None
    fantasy_teams: tuple[DraftSetupTeam, ...]


def list_draft_setup_leagues(session: Session) -> tuple[DraftSetupLeague, ...]:
    """Return every persisted league only when its setup evidence is coherent.

    Array order is deterministic display order, not a source-seat or draft-slot
    binding. The caller must still assign ``team_slot`` and may only assign
    ``source_seat`` from separate, explicit board evidence.
    """

    leagues = session.scalars(select(League).order_by(League.id)).all()
    teams_by_league: dict[int, list[FantasyTeam]] = defaultdict(list)
    team_rows = session.scalars(select(FantasyTeam).order_by(FantasyTeam.league_id, FantasyTeam.id))
    for team in team_rows:
        teams_by_league[team.league_id].append(team)

    current_settings: dict[int, LeagueSettingsSnapshot] = {}
    snapshots = session.scalars(
        select(LeagueSettingsSnapshot).order_by(
            LeagueSettingsSnapshot.league_id,
            LeagueSettingsSnapshot.version.desc(),
            LeagueSettingsSnapshot.id.desc(),
        )
    )
    for snapshot in snapshots:
        current_settings.setdefault(snapshot.league_id, snapshot)

    result: list[DraftSetupLeague] = []
    for league in leagues:
        try:
            draft_format = draft_format_from_league(league)
        except DraftFormatError as error:
            raise DraftLogError(
                "draft_format_invalid",
                f"League {league.id} does not describe a draft that can be recorded: {error}",
            ) from error

        settings_snapshot = current_settings.get(league.id)
        if settings_snapshot is not None:
            _validate_current_settings(league, settings_snapshot)

        teams = sorted(
            teams_by_league[league.id],
            key=lambda team: (team.name.casefold(), team.name, team.id),
        )
        if len(teams) != draft_format.team_count:
            raise DraftLogError(
                "draft_participants_incomplete",
                f"A {draft_format.team_count}-team draft for league {league.id} needs exactly "
                f"{draft_format.team_count} stored fantasy teams; got {len(teams)}.",
            )

        for team in teams:
            if not team.name.strip():
                raise DraftLogError(
                    "draft_participant_name_required",
                    f"Fantasy team {team.id} in league {league.id} needs a display name.",
                )

        owner_teams = [team for team in teams if team.is_owner_team]
        if len(owner_teams) > 1:
            raise DraftLogError(
                "draft_multiple_owner_seats",
                f"League {league.id} has {len(owner_teams)} stored fantasy teams marked as "
                "the owner's; at most one may seed a draft seat.",
            )

        result.append(
            DraftSetupLeague(
                league_id=league.id,
                name=league.name,
                season=league.season,
                format=draft_format,
                owner_fantasy_team_id=owner_teams[0].id if owner_teams else None,
                fantasy_teams=tuple(
                    DraftSetupTeam(fantasy_team_id=team.id, display_name=team.name)
                    for team in teams
                ),
            )
        )
    return tuple(result)


def _validate_current_settings(league: League, snapshot: LeagueSettingsSnapshot) -> None:
    try:
        document = LeagueSettingsDocument.model_validate(snapshot.settings)
    except ValidationError as error:
        raise DraftLogError(
            "draft_setup_settings_invalid",
            f"League {league.id} current settings snapshot {snapshot.id} is malformed.",
        ) from error

    if snapshot.schema_version != str(document.schema_version):
        raise DraftLogError(
            "draft_setup_settings_invalid",
            f"League {league.id} current settings snapshot {snapshot.id} declares schema "
            f"{snapshot.schema_version!r} but contains schema {document.schema_version!r}.",
        )

    expected_season = f"{document.source_season_year}-{str(document.source_season_year + 1)[-2:]}"
    observed_roster_size = (
        document.roster_limits.value.total if document.roster_limits.value is not None else None
    )
    mismatches: list[str] = []
    if document.source_league_id != league.fantrax_league_id:
        mismatches.append("source league identity")
    if expected_season != league.season:
        mismatches.append("season")
    if observed_roster_size is not None and observed_roster_size != league.roster_size:
        mismatches.append(
            f"roster size ({observed_roster_size} in settings, {league.roster_size} persisted)"
        )
    if mismatches:
        raise DraftLogError(
            "draft_setup_settings_stale",
            f"League {league.id} current settings snapshot {snapshot.id} contradicts "
            f"persisted league fields: {', '.join(mismatches)}.",
        )
