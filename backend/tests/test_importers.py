"""Importers: parsed records into the database.

Two properties matter more than the mapping itself, and both are about *not*
losing something:

* **idempotency** — a backfill is thousands of throttled requests over tens of
  minutes and will be interrupted; re-running it must converge, not duplicate;
* **a manual override is final** — a human correction must survive the next
  automated pass, which is the entire purpose of the flag.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hoops_gm.db.models.availability import PlayerParticipation
from hoops_gm.db.models.enums import (
    DnpReason,
    ExternalSource,
    FieldEvidence,
    MatchMethod,
    ParticipationOutcome,
)
from hoops_gm.db.models.identity import Player, PlayerExternalId
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog
from hoops_gm.identity import IdentityResolver, ResolutionReport, ResolvableRecord
from hoops_gm.ingest.fantrax_official import parse_player_ids
from hoops_gm.ingest.importers import (
    import_box_scores,
    import_games,
    import_nba_players,
    import_participation,
    import_resolutions,
    import_teams,
)
from hoops_gm.ingest.nba import (
    combine_game_participation,
    parse_box_score_summary_v3,
    parse_box_score_traditional_v3,
    parse_common_all_players,
    parse_league_game_finder,
    parse_player_game_logs,
    parse_teams,
)
from hoops_gm.ingest.nba.models import GameParticipation

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def loaded(session: Session) -> Session:
    """A session with teams, players and one season's games and box scores."""
    import_teams(session, parse_teams(load("nba_static_teams.json")))
    import_nba_players(session, parse_common_all_players(load("nba_commonallplayers_current.json")))
    import_games(
        session,
        parse_league_game_finder(load("nba_leaguegamefinder_trimmed.json"), season="2024-25"),
    )
    return session


class TestTeamImport:
    def test_teams_are_created_then_updated_not_duplicated(self, session: Session) -> None:
        records = parse_teams(load("nba_static_teams.json"))
        first = import_teams(session, records)
        second = import_teams(session, records)
        assert first.created == 30
        assert second.created == 0
        assert second.updated == 30


class TestPlayerImport:
    def test_players_and_their_nba_ids_are_created(self, session: Session) -> None:
        import_teams(session, parse_teams(load("nba_static_teams.json")))
        records = parse_common_all_players(load("nba_commonallplayers_current.json"))
        counts = import_nba_players(session, records)
        assert counts.created == len(records)
        assert session.scalar(select(func.count()).select_from(Player)) == len(records)

    def test_re_running_does_not_duplicate(self, session: Session) -> None:
        import_teams(session, parse_teams(load("nba_static_teams.json")))
        records = parse_common_all_players(load("nba_commonallplayers_current.json"))
        import_nba_players(session, records)
        before = session.scalar(select(func.count()).select_from(Player))
        counts = import_nba_players(session, records)
        assert counts.created == 0
        assert session.scalar(select(func.count()).select_from(Player)) == before

    def test_the_nba_id_is_the_only_anchor_claim_in_the_project(self, session: Session) -> None:
        """``ANCHOR_ID`` is true here and nowhere else.

        This row is not a cross-source inference — it is the identifier the
        canonical player was created from. Every *other* source's row is
        inferred, because no shared key exists (R23).
        """
        import_teams(session, parse_teams(load("nba_static_teams.json")))
        import_nba_players(
            session, parse_common_all_players(load("nba_commonallplayers_current.json"))
        )
        links = session.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.NBA)
        ).all()
        assert links
        for link in links:
            assert link.match_method is MatchMethod.ANCHOR_ID
            assert link.confidence == 1.0
            assert link.current_for_source == ExternalSource.NBA.value

    def test_players_get_a_normalized_name_for_the_resolver(self, session: Session) -> None:
        import_teams(session, parse_teams(load("nba_static_teams.json")))
        import_nba_players(
            session, parse_common_all_players(load("nba_commonallplayers_current.json"))
        )
        players = session.scalars(select(Player)).all()
        assert all(p.normalized_name for p in players)
        assert all(p.normalized_name == p.normalized_name.lower() for p in players)


class TestCrosswalkImport:
    @pytest.fixture
    def resolutions(self, loaded: Session) -> ResolutionReport:
        fantrax = parse_player_ids(load("fantrax_getplayerids_nba.json"))
        nba = parse_common_all_players(load("nba_commonallplayers_current.json"))
        targets = [
            ResolvableRecord.build(
                key=str(p.nba_player_id),
                name=p.display_last_comma_first,
                team=p.team_abbreviation,
            )
            for p in nba
        ]
        sources = [
            ResolvableRecord.build(key=p.fantrax_id, name=p.name, team=p.team, position=p.position)
            for p in fantrax.players
        ]
        return IdentityResolver(targets).resolve(sources)

    def test_accepted_matches_become_crosswalk_rows(
        self, loaded: Session, resolutions: ResolutionReport
    ) -> None:
        counts = import_resolutions(loaded, resolutions.accepted, source=ExternalSource.FANTRAX)
        assert counts.created > 300
        rows = loaded.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.FANTRAX)
        ).all()
        assert len(rows) == counts.created

    def test_every_written_row_carries_its_per_field_evidence(
        self, loaded: Session, resolutions: ResolutionReport
    ) -> None:
        """The point of the design: a disputed match is re-adjudicable from the
        row itself, without re-running anything."""
        import_resolutions(loaded, resolutions.accepted, source=ExternalSource.FANTRAX)
        rows = loaded.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.FANTRAX)
        ).all()
        for row in rows:
            assert row.name_evidence is FieldEvidence.AGREE
            assert row.team_evidence in set(FieldEvidence)
            assert 0.0 <= row.confidence <= 1.0
            assert row.match_method is not MatchMethod.ANCHOR_ID
            assert row.external_name

    def test_rows_needing_review_are_not_written(
        self, loaded: Session, resolutions: ResolutionReport
    ) -> None:
        """They belong in the report, not the crosswalk.

        Writing a guess and relying on ``confidence`` to warn downstream
        assumes every consumer checks it, and the one that does not is the one
        that corrupts a number.
        """
        import_resolutions(loaded, resolutions.all_resolutions(), source=ExternalSource.FANTRAX)
        written = {
            row.external_id
            for row in loaded.scalars(
                select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.FANTRAX)
            )
        }
        for resolution in resolutions.needs_review:
            assert resolution.source_record.key not in written

    def test_a_manual_override_survives_a_re_run(
        self, loaded: Session, resolutions: ResolutionReport
    ) -> None:
        """The resolver's stop sign. A resolver that re-decides a human's call
        is worse than no resolver."""
        import_resolutions(loaded, resolutions.accepted, source=ExternalSource.FANTRAX)
        loaded.flush()

        row = loaded.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.FANTRAX)
        ).first()
        assert row is not None
        # A player with no Fantrax row yet: re-pointing at one that already has
        # one would hit uq_player_external_ids_current, which is the constraint
        # under test elsewhere and would obscure what this test is about.
        claimed = set(
            loaded.scalars(
                select(PlayerExternalId.player_id).where(
                    PlayerExternalId.source == ExternalSource.FANTRAX
                )
            )
        )
        other = loaded.scalars(select(Player).where(Player.id.notin_(claimed))).first()
        assert other is not None

        row.player_id = other.id
        row.is_manual_override = True
        row.confidence = 1.0
        row.match_method = MatchMethod.MANUAL_OVERRIDE
        row.notes = "corrected by hand"
        loaded.flush()

        import_resolutions(loaded, resolutions.accepted, source=ExternalSource.FANTRAX)
        loaded.flush()
        loaded.refresh(row)

        assert row.player_id == other.id
        assert row.is_manual_override is True
        assert row.match_method is MatchMethod.MANUAL_OVERRIDE
        assert row.notes == "corrected by hand"

    def test_re_running_updates_rather_than_duplicating(
        self, loaded: Session, resolutions: ResolutionReport
    ) -> None:
        first = import_resolutions(loaded, resolutions.accepted, source=ExternalSource.FANTRAX)
        second = import_resolutions(loaded, resolutions.accepted, source=ExternalSource.FANTRAX)
        assert second.created == 0
        assert second.updated == first.created

    def test_a_source_with_no_canonical_player_is_skipped_not_invented(
        self, session: Session
    ) -> None:
        """Creating a player from the far side of an inferred match is how a
        crosswalk grows phantom people."""
        import_teams(session, parse_teams(load("nba_static_teams.json")))
        resolver = IdentityResolver([ResolvableRecord.build(key="999999", name="Nobody, Real")])
        report = resolver.resolve([ResolvableRecord.build(key="fx1", name="Real Nobody")])
        counts = import_resolutions(session, report.accepted, source=ExternalSource.FANTRAX)
        assert counts.created == 0
        assert counts.skipped == 1
        assert session.scalar(select(func.count()).select_from(Player)) == 0


class TestGameAndBoxScoreImport:
    def test_games_import_and_are_idempotent(self, session: Session) -> None:
        import_teams(session, parse_teams(load("nba_static_teams.json")))
        records = parse_league_game_finder(
            load("nba_leaguegamefinder_trimmed.json"), season="2024-25"
        )
        first = import_games(session, records)
        second = import_games(session, records)
        assert first.created == len(records)
        assert second.created == 0

    def test_a_tipoff_is_only_written_when_a_source_supplied_one(self, loaded: Session) -> None:
        """``LeagueGameFinder`` gives a local date and no instant. A midnight
        guess here would feed rest-day and back-to-back detection with
        fiction."""
        games = loaded.scalars(select(NbaGame)).all()
        assert games
        assert all(g.tipoff_utc is None for g in games)

    def test_a_later_source_can_supply_the_tipoff(self, loaded: Session) -> None:
        from dataclasses import replace

        records = parse_league_game_finder(
            load("nba_leaguegamefinder_trimmed.json"), season="2024-25"
        )
        moment = datetime(2024, 12, 1, 20, 30, tzinfo=UTC)
        import_games(loaded, [replace(records[0], tipoff_utc=moment)])
        loaded.flush()
        game = loaded.scalars(
            select(NbaGame).where(NbaGame.nba_game_id == records[0].nba_game_id)
        ).one()
        assert game.tipoff_utc == moment

    def test_box_scores_import_for_known_games_and_players(self, loaded: Session) -> None:
        logs = parse_player_game_logs(load("nba_playergamelogs_trimmed.json"))
        counts = import_box_scores(loaded, logs)
        # The fixtures are trimmed and from different seasons, so most rows
        # legitimately have no matching game. What matters is that unmatched
        # rows are skipped rather than inserted with a dangling key.
        assert counts.created + counts.skipped == len(logs)
        stored = loaded.scalars(select(PlayerGameLog)).all()
        assert len(stored) == counts.created


class TestParticipationImport:
    @pytest.fixture
    def game_ready(self, session: Session) -> Session:
        """A session containing the one game the participation fixtures cover."""
        from dataclasses import replace

        import_teams(session, parse_teams(load("nba_static_teams.json")))
        import_nba_players(
            session, parse_common_all_players(load("nba_commonallplayers_current.json"))
        )
        summary_game, _ = parse_box_score_summary_v3(
            load("nba_boxscoresummaryv3_0022500560_midseason.json")
        )
        assert summary_game is not None
        import_games(session, [replace(summary_game, season="2025-26")])
        return session

    def _combined(self) -> GameParticipation:
        _, dressed = parse_box_score_traditional_v3(
            load("nba_boxscoretraditionalv3_0022500560_midseason.json")
        )
        _, summary = parse_box_score_summary_v3(
            load("nba_boxscoresummaryv3_0022500560_midseason.json")
        )
        return combine_game_participation(dressed, summary)

    def test_participation_rows_are_written(self, game_ready: Session) -> None:
        counts = import_participation(game_ready, self._combined())
        assert counts.created > 0
        rows = game_ready.scalars(select(PlayerParticipation)).all()
        assert len(rows) == counts.created

    def test_absences_keep_the_source_words_verbatim(self, game_ready: Session) -> None:
        import_participation(game_ready, self._combined())
        absences = game_ready.scalars(
            select(PlayerParticipation).where(
                PlayerParticipation.outcome.in_(
                    [
                        ParticipationOutcome.DID_NOT_PLAY,
                        ParticipationOutcome.DID_NOT_DRESS,
                        ParticipationOutcome.NOT_WITH_TEAM,
                    ]
                )
            )
        ).all()
        assert absences
        for row in absences:
            assert row.raw_comment.strip()

    def test_inactive_rows_state_no_reason_rather_than_guessing_injury(
        self, game_ready: Session
    ) -> None:
        """Most inactives are injuries. "Most" is exactly the assumption that
        turns into a fabricated training label for the availability model."""
        import_participation(game_ready, self._combined())
        inactive = game_ready.scalars(
            select(PlayerParticipation).where(
                PlayerParticipation.outcome == ParticipationOutcome.INACTIVE
            )
        ).all()
        assert inactive
        for row in inactive:
            assert row.reason is DnpReason.NONE_GIVEN
            assert row.raw_comment == ""

    def test_the_availability_of_the_inactive_list_is_recorded_on_every_row(
        self, game_ready: Session
    ) -> None:
        """So a later query can tell "nobody was inactive" from "nothing was
        reported" — the distinction ``BoxScoreSummaryV2`` erased for a whole
        season."""
        import_participation(game_ready, self._combined())
        rows = game_ready.scalars(select(PlayerParticipation)).all()
        assert rows
        assert all(row.inactive_list_available is True for row in rows)

    def test_a_player_who_played_has_minutes_and_one_who_did_not_has_none(
        self, game_ready: Session
    ) -> None:
        """Zero and absent are different claims, and availability modelling
        depends on the difference."""
        import_participation(game_ready, self._combined())
        played = game_ready.scalars(
            select(PlayerParticipation).where(
                PlayerParticipation.outcome == ParticipationOutcome.PLAYED
            )
        ).all()
        inactive = game_ready.scalars(
            select(PlayerParticipation).where(
                PlayerParticipation.outcome == ParticipationOutcome.INACTIVE
            )
        ).all()
        assert played and all(row.seconds_played for row in played)
        assert inactive and all(row.seconds_played is None for row in inactive)

    def test_re_importing_the_same_game_does_not_duplicate(self, game_ready: Session) -> None:
        first = import_participation(game_ready, self._combined())
        second = import_participation(game_ready, self._combined())
        assert second.created == 0
        assert second.updated == first.created

    def test_a_game_that_is_not_in_the_database_is_skipped_wholesale(
        self, session: Session
    ) -> None:
        counts = import_participation(session, self._combined())
        assert counts.created == 0
        assert counts.skipped > 0
