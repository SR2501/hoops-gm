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
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hoops_gm.db.lineage import SCHEDULE_CONTEXT_SOURCE_KEY
from hoops_gm.db.models.availability import PlayerParticipation
from hoops_gm.db.models.enums import (
    DnpReason,
    ExternalSource,
    FieldEvidence,
    MatchMethod,
    ParticipationOutcome,
    RefreshArtifactType,
)
from hoops_gm.db.models.identity import Player, PlayerExternalId
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog
from hoops_gm.identity import IdentityResolver, ResolutionReport, ResolvableRecord
from hoops_gm.ingest import importers
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.fantrax_official import parse_player_ids
from hoops_gm.ingest.importers import (
    import_box_scores,
    import_games,
    import_nba_players,
    import_participation,
    import_player_positions,
    import_resolutions,
    import_teams,
)
from hoops_gm.ingest.nba import (
    PLAYER_INDEX_POSITIONS,
    combine_game_participation,
    parse_box_score_summary_v3,
    parse_box_score_traditional_v3,
    parse_common_all_players,
    parse_league_game_finder,
    parse_player_game_logs,
    parse_player_index,
    parse_teams,
)
from hoops_gm.ingest.nba.models import GameParticipation, NbaPlayerPositionRecord

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_scoring_observation_importers_lock_the_shared_source_scope(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    def capture_lock(_session: Session, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(importers, "lock_refresh_scope", capture_lock)

    import_games(session, [])
    import_box_scores(session, [])

    assert calls == [
        {
            "artifact_type": RefreshArtifactType.SOURCE,
            "artifact_key": SCHEDULE_CONTEXT_SOURCE_KEY,
            "season": None,
        },
        {
            "artifact_type": RefreshArtifactType.SOURCE,
            "artifact_key": SCHEDULE_CONTEXT_SOURCE_KEY,
            "season": None,
        },
    ]


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


class TestPlayerPositionImport:
    """Persisting the NBA's listed position, and the identity payoff.

    The point of this importer is risk R7: the crosswalk is specified to match
    on "normalized name + team + position", and until this landed the NBA side
    of every comparison had no position at all, so `compare_positions` returned
    `UNKNOWN` for every pair in the project's history.
    """

    @pytest.fixture
    def crosswalked(self, session: Session) -> Session:
        import_teams(session, parse_teams(load("nba_static_teams.json")))
        import_nba_players(
            session, parse_common_all_players(load("nba_commonallplayers_current.json"))
        )
        return session

    def test_positions_land_on_canonical_players_with_their_lineage(
        self, crosswalked: Session
    ) -> None:
        records = parse_player_index(load("nba_playerindex_current.json"), season="2026-27")
        observed = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

        counts = import_player_positions(crosswalked, records, observed_at=observed)

        assert counts.updated > 400
        # This importer never inserts a row, so `created` must stay at zero.
        # An earlier version reported "569 created" for a step whose whole
        # design is that it creates nothing.
        assert counts.created == 0
        placed = crosswalked.scalars(
            select(Player).where(Player.primary_position.is_not(None))
        ).all()
        assert placed
        for player in placed:
            assert player.primary_position in PLAYER_INDEX_POSITIONS
            assert player.primary_position_source == "nba:PlayerIndex"
            assert player.primary_position_season == "2026-27"
            assert player.primary_position_observed_at == observed

    def test_re_running_is_idempotent(self, crosswalked: Session) -> None:
        records = parse_player_index(load("nba_playerindex_current.json"), season="2026-27")
        observed = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

        first = import_player_positions(crosswalked, records, observed_at=observed)
        before = crosswalked.scalar(
            select(func.count()).select_from(Player).where(Player.primary_position.is_not(None))
        )
        second = import_player_positions(crosswalked, records, observed_at=observed)

        assert second.created == 0
        assert second.updated == first.updated
        assert second.skipped == first.skipped
        assert (
            crosswalked.scalar(
                select(func.count()).select_from(Player).where(Player.primary_position.is_not(None))
            )
            == before
        )

    def test_a_superseded_nba_id_cannot_write_a_position(self, crosswalked: Session) -> None:
        """A retired identifier is history, not a join key.

        ``current_for_source`` exists so a superseded row stops being the one
        joins pick up. Without that filter a stale NBA person id writes an old
        season's position onto a current player and stamps it with fresh
        provenance — a lie of exactly the kind the lineage columns exist to
        prevent. The projection importer already filters this way.
        """
        player = crosswalked.scalars(select(Player)).first()
        assert player is not None
        crosswalked.add(
            PlayerExternalId(
                player_id=player.id,
                source=ExternalSource.NBA,
                current_for_source=None,  # superseded
                external_id="99000001",
                match_method=MatchMethod.ANCHOR_ID,
            )
        )
        crosswalked.flush()

        counts = import_player_positions(
            crosswalked,
            [NbaPlayerPositionRecord(nba_player_id=99000001, position="C", season="2019-20")],
            observed_at=datetime(2026, 8, 20, tzinfo=UTC),
        )

        assert counts.skipped == 1
        assert counts.updated == 0
        crosswalked.refresh(player)
        assert player.primary_position_season != "2019-20"

    def test_a_naive_observed_at_is_refused_by_the_caller_not_the_column(
        self, crosswalked: Session
    ) -> None:
        records = parse_player_index(load("nba_playerindex_current.json"), season="2026-27")

        with pytest.raises(ValueError, match="timezone-aware"):
            import_player_positions(crosswalked, records, observed_at=datetime(2026, 8, 20, 12, 0))

    def test_an_orphaned_crosswalk_link_is_loud_and_is_not_blamed_on_the_source(
        self, crosswalked: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The one guard in this lane that shipped untested, until review.

        **The state is unreachable under FK enforcement**, and that is stated
        rather than worked around: `player_external_ids.player_id` is a CASCADE
        foreign key, deleting a player removes its links, and SQLite refuses an
        insert pointing at a missing row while `PRAGMA foreign_keys` cannot be
        turned off inside an open transaction. An orphan therefore requires a
        bulk load, a restored backup or a migration that ran with enforcement
        off. So this drives the branch by making the lookup answer `None` —
        exercising *our* response to a corrupt crosswalk, not a corruption this
        test can honestly manufacture.

        What is being pinned is the exception *class*. Counting the orphan as
        `skipped` would hide a broken database inside a number that also means
        "nothing to do here"; raising `SourceContractError` was wrong the other
        way, because that class means the source changed shape and carries
        source/endpoint attributes handlers branch on and logs index by. It
        would file local corruption as NBA API drift and send the reader to the
        wrong system.
        """
        records = parse_player_index(load("nba_playerindex_current.json"), season="2026-27")
        real = next(r for r in records if r.position is not None)

        monkeypatch.setattr(crosswalked, "get", lambda *args, **kwargs: None, raising=True)

        with pytest.raises(RuntimeError, match="referential integrity") as caught:
            import_player_positions(
                crosswalked, [real], observed_at=datetime(2026, 8, 20, tzinfo=UTC)
            )
        assert not isinstance(caught.value, SourceContractError), (
            "a broken local crosswalk must not be reported as upstream drift"
        )
        assert str(real.nba_player_id) in str(caught.value)

    def test_position_provenance_is_written_as_a_complete_set_or_not_at_all(
        self, crosswalked: Session
    ) -> None:
        """The guarantee that is actually in force, and its honest limit.

        A database CHECK would be stronger and was implemented, then reverted:
        SQLite can only add one by rebuilding ``players``, and ten foreign keys
        point into that table with eight ``ON DELETE CASCADE``, so the rebuild
        deletes the crosswalk, the game logs, the participation ledger and the
        projections. The existing migration suite caught it. See revision 0016.

        What holds instead is that ``NbaPlayerPositionRecord.season`` is
        required with no default, and this importer writes all four columns in
        one block. So no *record* can express the incomplete state and no write
        through this path produces one. **Any other writer still can, including
        a plain ORM ``Player(primary_position="C")``** — not merely raw SQL —
        which is why that is stated rather than implied.
        """
        records = parse_player_index(load("nba_playerindex_current.json"), season="2026-27")
        import_player_positions(crosswalked, records, observed_at=datetime(2026, 8, 20, tzinfo=UTC))

        rows = crosswalked.scalars(select(Player)).all()
        assert rows
        for player in rows:
            stated = [
                player.primary_position,
                player.primary_position_source,
                player.primary_position_season,
                player.primary_position_observed_at,
            ]
            # All four present, or all four absent. Never a partial triple.
            assert all(v is not None for v in stated) or all(v is None for v in stated), (
                f"player {player.id} carries partial position provenance: {stated}"
            )

        # And the record type refuses to express it a step earlier.
        with pytest.raises(TypeError):
            NbaPlayerPositionRecord(nba_player_id=1, position="C")  # type: ignore[call-arg]

    def test_an_unstated_position_never_overwrites_a_known_one(self, crosswalked: Session) -> None:
        """Declining to state a position is not retracting one.

        The same distinction `inactives_available` exists for on the
        participation side: absent evidence and contradicting evidence must not
        produce the same write.
        """
        records = parse_player_index(load("nba_playerindex_current.json"), season="2026-27")
        stated = next(r for r in records if r.position is not None)
        import_player_positions(crosswalked, records, observed_at=datetime(2026, 8, 20, tzinfo=UTC))

        link = crosswalked.scalars(
            select(PlayerExternalId).where(
                PlayerExternalId.source == ExternalSource.NBA,
                PlayerExternalId.external_id == str(stated.nba_player_id),
            )
        ).one()
        player = crosswalked.get(Player, link.player_id)
        assert player is not None and player.primary_position == stated.position

        silent = replace(stated, position=None)
        counts = import_player_positions(
            crosswalked, [silent], observed_at=datetime(2026, 8, 21, tzinfo=UTC)
        )

        assert counts.skipped == 1
        crosswalked.refresh(player)
        assert player.primary_position == stated.position

    def test_an_unknown_player_is_skipped_never_invented(self, crosswalked: Session) -> None:
        """Only `import_nba_players` may introduce a canonical row.

        A position listing is an attribute of a person already established, not
        evidence that a person exists. Two independent inventors of identity is
        R7's failure mode with extra steps.
        """
        before = crosswalked.scalar(select(func.count()).select_from(Player))

        counts = import_player_positions(
            crosswalked,
            [NbaPlayerPositionRecord(nba_player_id=99999999, position="C", season="2026-27")],
            observed_at=datetime(2026, 8, 20, tzinfo=UTC),
        )

        assert counts.skipped == 1
        assert crosswalked.scalar(select(func.count()).select_from(Player)) == before

    def test_importing_before_the_crosswalk_exists_is_refused(self, session: Session) -> None:
        with pytest.raises(ValueError, match="crosswalk"):
            import_player_positions(
                session,
                [NbaPlayerPositionRecord(nba_player_id=1, position="G", season="2026-27")],
                observed_at=datetime(2026, 8, 20, tzinfo=UTC),
            )

    def test_position_disambiguates_a_real_duplicate_name_and_costs_one_borderline_big(
        self, crosswalked: Session
    ) -> None:
        """What supplying R7's third key actually did, measured rather than assumed.

        Both effects are real and both are pinned here, because the headline
        number hides them: 570 matches were accepted before and 570 after, and
        the accepted **set is not the same set**. A count would have reported
        "no change". This repository has already been bitten by exactly that
        ("never a count — the count is what let the first defect survive
        review"), so the set is compared, not its size.

        **Gained — `Johnson, Jalen`.** Fantrax carries two rows of that name:
        one on ATL listed `SF`, one with no team listed `SG`. The NBA has one,
        on ATL, listed `F`. Position agrees with the first and contradicts the
        second, which is precisely the duplicate-name disambiguation R7
        specified position to perform, working on a genuine duplicate.

        **Lost — `Tillman, Xavier`.** Fantrax says `C` with no team; the NBA
        says `F`. Same human, two defensible classifications of a borderline
        big. With team absent there is nothing to offset the 0.12 position
        penalty, so a correct match drops to 0.730 and falls under the accept
        floor.

        The second effect is a false negative introduced by this lane, and it
        is **not fixed here** — the matcher's weights belong to the identity
        lane, and `evidence.py` already records lowering the *team* penalty for
        this same reason (sources are snapshots that genuinely differ). This
        test exists so that the trade-off is a recorded, executable fact rather
        than a surprise when somebody asks where Xavier Tillman went.
        """
        positions = {
            r.nba_player_id: r.position
            for r in parse_player_index(load("nba_playerindex_current.json"), season="2026-27")
        }
        nba_players = parse_common_all_players(load("nba_commonallplayers_current.json"))
        fantrax = parse_player_ids(load("fantrax_getplayerids_nba.json"))
        sources = [
            ResolvableRecord.build(key=p.fantrax_id, name=p.name, team=p.team, position=p.position)
            for p in fantrax.players
        ]

        def accepted_pairs(*, with_position: bool) -> set[tuple[str, str]]:
            targets = [
                ResolvableRecord.build(
                    key=str(p.nba_player_id),
                    name=p.display_last_comma_first,
                    team=p.team_abbreviation,
                    position=positions.get(p.nba_player_id) if with_position else None,
                )
                for p in nba_players
            ]
            report = IdentityResolver(targets).resolve(sources)
            return {
                (r.source_record.key, r.best.target.key)
                for r in report.all_resolutions()
                if r.accepted and r.best is not None
            }

        before = accepted_pairs(with_position=False)
        after = accepted_pairs(with_position=True)

        assert len(before) == len(after), "the sizes coincide, which is the trap"
        assert before != after, "and the sets do not — so a count proves nothing here"

        # The duplicate-name case position exists to settle.
        assert ("05uiu", "1630552") in after - before
        # The borderline big it costs. Left failing-by-design, not repaired.
        assert ("05qtf", "1630214") in before - after

    def test_the_nba_side_of_the_crosswalk_can_finally_corroborate_on_position(
        self, crosswalked: Session
    ) -> None:
        """R7's third key, demonstrated end to end rather than asserted.

        Fantrax states `PG`/`SG`/`SF`/`PF`/`C`; the NBA states `G`/`F`/`C` and
        hybrids. `compare_positions` reduces both to coarse sets, so the two
        vocabularies are comparable — and before this lane the NBA side was
        `None`, which made every comparison `UNKNOWN`.
        """
        positions = {
            r.nba_player_id: r.position
            for r in parse_player_index(load("nba_playerindex_current.json"), season="2026-27")
        }
        nba_players = parse_common_all_players(load("nba_commonallplayers_current.json"))

        without = [
            ResolvableRecord.build(
                key=str(p.nba_player_id), name=p.display_last_comma_first, team=p.team_abbreviation
            )
            for p in nba_players
        ]
        with_position = [
            ResolvableRecord.build(
                key=str(p.nba_player_id),
                name=p.display_last_comma_first,
                team=p.team_abbreviation,
                position=positions.get(p.nba_player_id),
            )
            for p in nba_players
        ]

        assert all(r.position is None for r in without)
        assert sum(1 for r in with_position if r.position is not None) > 400

        fantrax = parse_player_ids(load("fantrax_getplayerids_nba.json"))
        sources = [
            ResolvableRecord.build(key=p.fantrax_id, name=p.name, team=p.team, position=p.position)
            for p in fantrax.players
        ]

        blind = IdentityResolver(without).resolve(sources)
        sighted = IdentityResolver(with_position).resolve(sources)

        def position_evidence(report: ResolutionReport) -> dict[FieldEvidence, int]:
            tally: dict[FieldEvidence, int] = {}
            for resolution in report.all_resolutions():
                if resolution.best is None:
                    continue
                verdict = resolution.best.evidence.position
                tally[verdict] = tally.get(verdict, 0) + 1
            return tally

        before = position_evidence(blind)
        after = position_evidence(sighted)

        # Every candidate pair was position-blind before, by construction.
        assert set(before) == {FieldEvidence.UNKNOWN}
        # And now the field actually carries evidence.
        assert after.get(FieldEvidence.AGREE, 0) > 400


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


class TestSupersession:
    """`current_for_source` must be clearable, or the crosswalk cannot retract.

    Nothing in the codebase ever set it to `NULL` before this. Two consequences,
    both tested here: a retracted match survived looking authoritative, and a
    re-issued identifier violated `uq_player_external_ids_current` and aborted
    the whole multi-season backfill.
    """

    @pytest.fixture
    def seeded(self, session: Session) -> Session:
        import_teams(session, parse_teams(load("nba_static_teams.json")))
        session.add_all(
            [
                Player(id=1, full_name="Nikola Jokic", normalized_name="nikola jokic"),
                Player(id=2, full_name="Luka Doncic", normalized_name="luka doncic"),
            ]
        )
        session.flush()
        session.add_all(
            [
                PlayerExternalId(
                    player_id=1,
                    source=ExternalSource.NBA,
                    current_for_source=ExternalSource.NBA.value,
                    external_id="203999",
                    match_method=MatchMethod.ANCHOR_ID,
                    confidence=1.0,
                ),
                PlayerExternalId(
                    player_id=2,
                    source=ExternalSource.NBA,
                    current_for_source=ExternalSource.NBA.value,
                    external_id="1629029",
                    match_method=MatchMethod.ANCHOR_ID,
                    confidence=1.0,
                ),
            ]
        )
        session.flush()
        return session

    def _resolve(self, pairs: list[tuple[str, str, str]]) -> ResolutionReport:
        """Resolve Fantrax records against two known NBA players."""
        targets = [
            ResolvableRecord.build(key="203999", name="Jokic, Nikola", team="DEN"),
            ResolvableRecord.build(key="1629029", name="Doncic, Luka", team="LAL"),
        ]
        sources = [
            ResolvableRecord.build(key=key, name=name, team=team) for key, name, team in pairs
        ]
        return IdentityResolver(targets).resolve(sources)

    def test_a_retracted_match_is_superseded_not_left_standing(self, seeded: Session) -> None:
        """A match the resolver no longer accepts must stop being joined.

        Left current, it keeps its old high confidence and evidence and looks
        authoritative to every Phase 3 and Phase 4 consumer.
        """
        first = self._resolve([("fx-jokic", "Nikola Jokic", "DEN")])
        import_resolutions(seeded, first.all_resolutions(), source=ExternalSource.FANTRAX)
        seeded.flush()

        def stored() -> PlayerExternalId:
            # Re-read rather than reuse a narrowed reference: asserting
            # `== "fantrax"` and later `is None` on the same attribute makes
            # mypy consider the second assertion impossible, which it is not.
            return seeded.scalars(
                select(PlayerExternalId).where(PlayerExternalId.external_id == "fx-jokic")
            ).one()

        assert stored().current_for_source == ExternalSource.FANTRAX.value

        # The same identifier now carries a name that matches nobody.
        second = self._resolve([("fx-jokic", "Someone Else Entirely", "DEN")])
        counts = import_resolutions(seeded, second.all_resolutions(), source=ExternalSource.FANTRAX)
        seeded.flush()

        row = stored()
        assert counts.superseded == 1
        assert row.current_for_source is None, "a retracted match must leave the join set"
        # Kept as history rather than deleted: the evidence for the original
        # decision is what makes it re-adjudicable.
        assert row.external_name == "Nikola Jokic"

    def test_a_reissued_identifier_does_not_abort_the_backfill(self, seeded: Session) -> None:
        """The failure mode that killed a multi-season run.

        A source re-issuing an id means the `external_id` lookup misses, a
        second row is created with the same `current_for_source`, and the flush
        violates `uq_player_external_ids_current`. `backfill.py` does not catch
        `IntegrityError`, so the whole run dies.
        """
        first = self._resolve([("fx-old-id", "Nikola Jokic", "DEN")])
        import_resolutions(seeded, first.all_resolutions(), source=ExternalSource.FANTRAX)
        seeded.flush()

        # Same player, new Fantrax identifier.
        second = self._resolve([("fx-new-id", "Nikola Jokic", "DEN")])
        counts = import_resolutions(seeded, second.all_resolutions(), source=ExternalSource.FANTRAX)
        seeded.flush()

        assert counts.created == 1
        assert counts.superseded == 1
        rows = {
            row.external_id: row
            for row in seeded.scalars(
                select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.FANTRAX)
            )
        }
        assert rows["fx-old-id"].current_for_source is None
        assert rows["fx-new-id"].current_for_source == ExternalSource.FANTRAX.value

    def test_at_most_one_current_row_per_player_per_source(self, seeded: Session) -> None:
        """The invariant `uq_player_external_ids_current` exists to protect.

        Without it the crosswalk fans out and every aggregate through it
        double-counts.
        """
        for identifier in ("fx-a", "fx-b", "fx-c"):
            report = self._resolve([(identifier, "Nikola Jokic", "DEN")])
            import_resolutions(seeded, report.all_resolutions(), source=ExternalSource.FANTRAX)
            seeded.flush()

        current = [
            row
            for row in seeded.scalars(
                select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.FANTRAX)
            )
            if row.current_for_source is not None
        ]
        assert len(current) == 1
        assert current[0].external_id == "fx-c"

    def test_a_manual_override_is_never_superseded(self, seeded: Session) -> None:
        """A human decision survives retraction as well as re-matching."""
        first = self._resolve([("fx-jokic", "Nikola Jokic", "DEN")])
        import_resolutions(seeded, first.all_resolutions(), source=ExternalSource.FANTRAX)
        seeded.flush()
        row = seeded.scalars(
            select(PlayerExternalId).where(PlayerExternalId.external_id == "fx-jokic")
        ).one()
        row.is_manual_override = True
        row.match_method = MatchMethod.MANUAL_OVERRIDE
        seeded.flush()

        second = self._resolve([("fx-jokic", "Someone Else Entirely", "DEN")])
        counts = import_resolutions(seeded, second.all_resolutions(), source=ExternalSource.FANTRAX)
        seeded.flush()
        seeded.refresh(row)

        assert counts.superseded == 0
        assert row.current_for_source == ExternalSource.FANTRAX.value
        assert row.match_method is MatchMethod.MANUAL_OVERRIDE

    def test_a_stable_match_is_not_needlessly_superseded(self, seeded: Session) -> None:
        report = self._resolve([("fx-jokic", "Nikola Jokic", "DEN")])
        import_resolutions(seeded, report.all_resolutions(), source=ExternalSource.FANTRAX)
        seeded.flush()
        counts = import_resolutions(seeded, report.all_resolutions(), source=ExternalSource.FANTRAX)
        assert counts.superseded == 0
        assert counts.updated == 1


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
