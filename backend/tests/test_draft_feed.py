"""What the draft feed is, and is not, evidence of.

The unit this file covers exists to answer one question: on draft night, could
the owner stop typing? That reframes what is worth asserting. "A row appeared"
is the weak version. The assertions here are about the three ways a feed can be
confidently wrong while looking fine:

* reporting corroboration it did not obtain,
* reading a payload it does not actually understand,
* showing a stale board without saying so.

Each test names the defect it excludes and, where the exclusion is not
self-evident, names the reading under which the flag would be false while the
defect was present. Where no such reading exists the test says so, because a
check that cannot fail is worse than no check: it is a check that has been
counted.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.metadata import version
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hoops_gm.db.models.bridge import BridgePayload
from hoops_gm.db.models.draft import Draft
from hoops_gm.db.models.draft_feed import DraftFeedObservation
from hoops_gm.db.models.enums import DraftToolUsage, DraftType
from hoops_gm.db.models.league import FantasyTeam, League
from hoops_gm.draft import service as draft_service
from hoops_gm.draft.feed import (
    InstantKind,
    InstantProvenance,
    ObservedInstant,
    RecognitionContext,
    SourceTransport,
    freshness_of,
    league_id_in,
    recognise_bridge_payload,
    reconcile,
)
from hoops_gm.draft.feed import service as feed_service
from hoops_gm.ingest.fantrax_official.models import FantraxDraftPick

LEAGUE = "abc123league"
NOW = datetime(2026, 10, 18, 23, 14, tzinfo=UTC)

# Real, distinct names. Numbered placeholders would be a trap here:
# ``normalize_key`` strips digits, so "Player 1" and "Player 2" both key to
# "player" and every uniqueness assertion below would pass for the wrong reason.
JOKIC = "Nikola Jokic"
EDWARDS = "Anthony Edwards"
HALIBURTON = "Tyrese Haliburton"


# --------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------


def _league(
    session: Session,
    *,
    fantrax_league_id: str | None = LEAGUE,
    draft_type: DraftType = DraftType.SNAKE,
    team_count: int = 2,
    roster_size: int = 2,
    budget: Decimal | None = None,
) -> League:
    league = League(
        fantrax_league_id=fantrax_league_id,
        name="feed mock",
        season="2026-27",
        draft_type=draft_type,
        team_count=team_count,
        roster_size=roster_size,
        auction_budget=budget,
    )
    session.add(league)
    session.flush()
    return league


def _teams(session: Session, league: League, external_ids: list[str | None]) -> list[FantasyTeam]:
    teams = []
    for index, external in enumerate(external_ids, start=1):
        team = FantasyTeam(
            league_id=league.id,
            fantrax_team_id=external,
            name=f"Seat {index}",
        )
        session.add(team)
        teams.append(team)
    session.flush()
    return teams


def _draft(
    session: Session,
    league: League,
    teams: list[FantasyTeam],
) -> Draft:
    draft = draft_service.create_draft(
        session,
        league=league,
        name="feed mock",
        tool_usage=DraftToolUsage.INSTRUMENTED,
        participants=[
            draft_service.ParticipantSpec(
                team_slot=index,
                display_name=f"Seat {index}",
                is_owner=index == 1,
                fantasy_team_id=team.id,
            )
            for index, team in enumerate(teams, start=1)
        ],
    )
    session.flush()
    return draft


def _context(
    *,
    league_id: str = LEAGUE,
    team_ids: frozenset[str] = frozenset({"t1", "t2"}),
    draft_type: DraftType = DraftType.SNAKE,
) -> RecognitionContext:
    return RecognitionContext(
        fantrax_league_id=league_id,
        team_external_ids=team_ids,
        draft_type=draft_type,
    )


def _envelope(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The ``/fxpa/req`` response envelope, as ``fantraxapi`` documents it.

    ``{"responses": [{"data": ...}]}`` is taken from the pinned dependency's own
    indexing, not from a captured Fantrax draft room. The inner block is
    therefore a plausible shape, not an observed one — see
    ``test_the_envelope_shape_still_matches_the_pinned_client``.
    """
    return {"responses": [{"data": {"draftPicks": records}}]}


def _capture(
    session: Session,
    *,
    records: list[dict[str, Any]],
    dedupe_key: str,
    league_id: str = LEAGUE,
    created_at: datetime = NOW,
    captured_at: datetime | None = None,
) -> BridgePayload:
    row = BridgePayload(
        schema_name="hoops-gm.bridge-payload.v1",
        source="fantrax",
        captured_at=captured_at or created_at,
        request_method="POST",
        request_url=f"https://www.fantrax.com/fxpa/req?leagueId={league_id}",
        response_status=200,
        response_ok=True,
        response_content_type="application/json",
        body_raw="{}",
        body_json=_envelope(records),
        dedupe_key=dedupe_key,
        raw_payload="{}",
        created_at=created_at,
    )
    session.add(row)
    session.flush()
    return row


def _instant(
    *,
    transport: SourceTransport,
    artifact_key: str,
    player_label: str,
    received_at: datetime = NOW,
    source_claimed_at: datetime | None = None,
    locator: str = "$[0]",
    overall_pick: int | None = 1,
    team_external_id: str = "t1",
    amount: Decimal | None = None,
    kind: InstantKind = InstantKind.SELECTION,
) -> ObservedInstant:
    return ObservedInstant(
        kind=kind,
        provenance=InstantProvenance(
            transport=transport,
            artifact_key=artifact_key,
            recogniser="test",
            received_at=received_at,
            source_claimed_at=source_claimed_at,
            locator=locator,
        ),
        team_external_id=team_external_id,
        player_label=player_label,
        player_external_id=None,
        overall_pick=overall_pick,
        round_number=None,
        pick_in_round=None,
        amount=amount,
    )


# --------------------------------------------------------------------------
# 1. corroboration that was never obtained
# --------------------------------------------------------------------------


def test_one_artifact_read_into_both_sides_is_not_reported_as_agreement() -> None:
    """Excludes: reporting corroboration from a single read of a single source.

    This is the defect a `frontend` probe shipped — a screen compared against an
    API, agreeing, because one field had been read into both sides. The reading
    under which ``witnessed_by_two_transports == 0`` would be false while the
    defect was present is: the report counts a match without first establishing
    that the two sides came from different bytes. So the count is asserted
    *and* the matches are asserted to have been kept, under the name that says
    what they are, rather than silently dropped.
    """
    same_bytes = "sha256:identical"
    left = [
        _instant(
            transport=SourceTransport.BRIDGE_CAPTURE,
            artifact_key=same_bytes,
            player_label=JOKIC,
        )
    ]
    right = [
        _instant(
            transport=SourceTransport.OFFICIAL_HTTP,
            artifact_key=same_bytes,
            player_label=JOKIC,
        )
    ]

    report = reconcile(left, right, now=NOW)

    assert report.independence.independent is False
    assert report.independence.reason == "same_artifact_on_both_sides"
    assert report.independence.shared_artifacts == (same_bytes,)
    assert report.witnessed_by_two_transports == 0
    assert report.agreements == ()
    # Not discarded - a consumer must be able to see that a comparison happened
    # and what it was worth, which is precisely what the failing probe could not.
    assert len(report.unwitnessed_matches) == 1
    assert report.unwitnessed_matches[0].player_label == JOKIC


def test_two_transports_on_distinct_artifacts_are_witnessed() -> None:
    """The positive control for the test above.

    Without this, ``agreements == ()`` would be satisfied by a ``reconcile``
    that never populates ``agreements`` at all, and the previous test would
    pass against a permanently broken function. This is the reading in which
    that flag is false while the defect is present, made into a test.
    """
    report = reconcile(
        [
            _instant(
                transport=SourceTransport.BRIDGE_CAPTURE,
                artifact_key="bridge-dedupe-key",
                player_label=JOKIC,
            )
        ],
        [
            _instant(
                transport=SourceTransport.OFFICIAL_HTTP,
                artifact_key="sha256:official",
                player_label=JOKIC,
            )
        ],
        now=NOW,
    )

    assert report.independence.independent is True
    assert report.witnessed_by_two_transports == 1
    assert report.unwitnessed_matches == ()


def test_both_sides_off_the_same_pipe_is_not_two_transports() -> None:
    """Excludes: two bridge captures of one board being read as corroboration.

    Distinct artifact keys, so the shared-bytes check above does not fire. The
    remaining defect is a shared *pipe*, which is a different fault with a
    different fix, and the reason string has to distinguish them or whoever is
    debugging at 7pm is sent to the wrong place.
    """
    report = reconcile(
        [
            _instant(
                transport=SourceTransport.BRIDGE_CAPTURE,
                artifact_key="capture-one",
                player_label=JOKIC,
            )
        ],
        [
            _instant(
                transport=SourceTransport.BRIDGE_CAPTURE,
                artifact_key="capture-two",
                player_label=JOKIC,
            )
        ],
        now=NOW,
    )

    assert report.independence.independent is False
    assert report.independence.reason == "same_transport_on_both_sides"
    assert report.independence.shared_artifacts == ()
    assert report.witnessed_by_two_transports == 0


def test_a_disagreement_carries_both_readings_and_no_verdict() -> None:
    """Excludes: silently resolving a contradiction by preferring one source.

    Two forms. The data form: both values are present and neither is dropped.
    The structural form: the type has no field that could hold a verdict, so a
    future edit that adds ``winner`` has to delete an assertion to do it. The
    second matters because the first would still pass if a caller resolved the
    disagreement downstream.
    """
    report = reconcile(
        [
            _instant(
                transport=SourceTransport.BRIDGE_CAPTURE,
                artifact_key="capture-one",
                player_label=JOKIC,
                overall_pick=1,
            )
        ],
        [
            _instant(
                transport=SourceTransport.OFFICIAL_HTTP,
                artifact_key="sha256:official",
                player_label=JOKIC,
                overall_pick=4,
            )
        ],
        now=NOW,
    )

    assert report.agreements == ()
    assert len(report.disagreements) == 1
    finding = report.disagreements[0]
    assert finding.field_name == "overall_pick"
    assert (finding.left_value, finding.right_value) == (1, 4)
    assert finding.left_provenance_key == "capture-one"
    assert finding.right_provenance_key == "sha256:official"

    fields = set(type(finding).__dataclass_fields__)
    assert not fields & {"winner", "preferred", "resolved_value", "correct_value"}


def test_a_missing_field_is_not_a_disagreement() -> None:
    """Excludes: burying real findings under one row per absent field.

    A source that omits ``round_number`` has not contradicted one that supplies
    it. Without this, the disagreement list on draft night would be dominated
    by the fields the official parser happens not to populate, and the single
    contradiction that mattered would be somewhere in the middle of it.
    """
    left = _instant(
        transport=SourceTransport.BRIDGE_CAPTURE,
        artifact_key="capture-one",
        player_label=JOKIC,
        overall_pick=1,
    )
    right = _instant(
        transport=SourceTransport.OFFICIAL_HTTP,
        artifact_key="sha256:official",
        player_label=JOKIC,
        overall_pick=None,
    )

    report = reconcile([left], [right], now=NOW)

    assert report.disagreements == ()
    assert report.witnessed_by_two_transports == 1


# --------------------------------------------------------------------------
# 2. reading a payload it does not understand
# --------------------------------------------------------------------------


def test_a_capture_for_another_league_is_refused() -> None:
    """Excludes: another league's draft board being recorded as this draft.

    The league id is on the URL, which the userscript preserves, and is checked
    against ``leagues.fantrax_league_id`` — a fact held in our database before
    the payload arrived. A reading in which ``rejected`` is set but the defect
    is still present would be one where instants were also returned, so the
    emptiness of ``instants`` is asserted too rather than inferred.
    """
    result = recognise_bridge_payload(
        url="https://www.fantrax.com/fxpa/req?leagueId=someoneelse",
        body_json=_envelope([{"teamId": "t1", "playerName": JOKIC}]),
        dedupe_key="k",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )

    assert result.rejected == "wrong_league"
    assert result.instants == ()


def test_a_url_that_is_not_the_rpc_endpoint_is_refused() -> None:
    """Excludes: a prefix match widening the capture surface silently.

    ``/fxpa/reqSomethingElse`` is a path Fantrax could add tomorrow. A prefix
    match would start feeding the tracker from it without anyone choosing to.
    """
    assert league_id_in("https://www.fantrax.com/fxpa/reqDraft?leagueId=abc123league") is None
    assert league_id_in("https://www.fantrax.com/fxpa/req?leagueId=abc123league") == LEAGUE

    result = recognise_bridge_payload(
        url="https://www.fantrax.com/fxpa/reqDraft?leagueId=abc123league",
        body_json=_envelope([{"teamId": "t1", "playerName": JOKIC}]),
        dedupe_key="k",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )
    assert result.rejected == "not_fxpa_req"
    assert result.instants == ()


def test_one_unknown_team_refuses_the_whole_list() -> None:
    """Excludes: a half-read list, which is the dangerous failure.

    If a guessed key name is wrong, or the block is about a different league's
    teams, some records will still resolve by coincidence. Recording those and
    dropping the rest produces a board that is *partly* right, which is far
    worse on draft night than a board that says it read nothing: partly right
    looks correct.

    The reading in which "zero instants" would be true while the defect was
    present is a recogniser that reads nothing from anything. That is excluded
    by ``test_a_list_of_known_teams_is_read``, which uses the same builder.
    """
    result = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [
                {"teamId": "t1", "playerName": JOKIC},
                {"teamId": "not-a-seat-in-this-draft", "playerName": EDWARDS},
            ]
        ),
        dedupe_key="k",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )

    assert result.instants == ()
    assert [shape.reason for shape in result.unrecognised] == ["no_seat_anchor"]
    # The keys are published so a human can see which alias was wrong.
    assert "teamId" in result.unrecognised[0].keys


def test_a_list_of_known_teams_is_read() -> None:
    """The positive control for the refusals above and for the ``rejected``
    checks: without it, every one of them is satisfied by a recogniser that
    always returns nothing."""
    result = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [
                {"teamId": "t1", "playerName": JOKIC, "overallPick": 1},
                {"teamId": "t2", "playerName": EDWARDS, "overallPick": 2},
            ]
        ),
        dedupe_key="k",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )

    assert result.rejected is None
    assert [instant.player_label for instant in result.instants] == [JOKIC, EDWARDS]
    assert [instant.overall_pick for instant in result.instants] == [1, 2]
    assert {instant.provenance.transport for instant in result.instants} == {
        SourceTransport.BRIDGE_CAPTURE
    }
    # Locators are distinct, which is what makes the row-level idempotence key
    # meaningful for two records out of one artifact.
    assert len({instant.provenance.locator for instant in result.instants}) == 2


def test_a_record_naming_no_player_refuses_the_list() -> None:
    """Excludes: a block about teams (standings, budgets) being read as picks.

    A roster-budget block keys on ``teamId`` too, and every id in it resolves.
    The seat anchor alone therefore accepts it; the naming requirement is what
    stops a list of team-budget rows from becoming a list of picks.
    """
    result = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope([{"teamId": "t1", "budgetLeft": 140}]),
        dedupe_key="k",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )

    assert result.instants == ()
    assert [shape.reason for shape in result.unrecognised] == ["record_names_no_player"]


def test_an_unreadable_envelope_is_reported_not_swallowed() -> None:
    """Excludes: a Fantrax shape change presenting as "no picks yet".

    Those two states are indistinguishable to the owner and call for opposite
    reactions. A shape change has to arrive as a visible unrecognised shape
    carrying the keys that were actually there.
    """
    result = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json={"pageData": {"draft": []}},
        dedupe_key="k",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )

    assert result.rejected == "envelope_unrecognised"
    assert result.instants == ()
    assert result.unrecognised[0].keys == ("pageData",)


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        (_context(league_id=""), "league_not_linked"),
        (_context(team_ids=frozenset()), "seats_not_linked"),
        (_context(draft_type=DraftType.UNKNOWN), "draft_type_unknown"),
    ],
)
def test_a_context_that_cannot_anchor_refuses_before_reading(
    context: RecognitionContext, expected: str
) -> None:
    """Excludes: falling back to key-name guessing when the anchor is missing.

    Each of these is a state the tool is routinely in — a mock against
    strangers has no linked seats, a league imported before the format was read
    has an unknown draft type. The permissive choice in each case is to read
    the payload anyway on the strength of the guessed key names alone, which is
    exactly the reading this refuses.
    """
    result = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope([{"teamId": "t1", "playerName": JOKIC}]),
        dedupe_key="k",
        received_at=NOW,
        captured_at=None,
        context=context,
    )
    assert result.rejected == expected
    assert result.instants == ()


# --------------------------------------------------------------------------
# 3. a stale board that does not say so
# --------------------------------------------------------------------------


def test_the_sources_own_timestamp_never_moves_the_age() -> None:
    """Excludes: a source's clock making a stale feed look live.

    ``gameEt`` is the standing example in this repository: a field that carries
    a ``Z`` and is not UTC. A draft capture's ``captured_at`` is the browser's
    claim about itself and is exactly as trustworthy. Two identical feeds whose
    only difference is that claim — one an hour ahead, one an hour behind —
    must report the same age.

    The reading in which equal ages would be true while the defect was present
    is a freshness function that ignores time entirely, which the third
    assertion excludes by pinning the actual number.
    """
    received = NOW - timedelta(seconds=90)
    ahead = _instant(
        transport=SourceTransport.BRIDGE_CAPTURE,
        artifact_key="k",
        player_label=JOKIC,
        received_at=received,
        source_claimed_at=NOW + timedelta(hours=1),
    )
    behind = _instant(
        transport=SourceTransport.BRIDGE_CAPTURE,
        artifact_key="k",
        player_label=JOKIC,
        received_at=received,
        source_claimed_at=NOW - timedelta(hours=1),
    )

    threshold = timedelta(minutes=2)
    first = freshness_of(
        [ahead], transport=SourceTransport.BRIDGE_CAPTURE, now=NOW, silence_threshold=threshold
    )
    second = freshness_of(
        [behind], transport=SourceTransport.BRIDGE_CAPTURE, now=NOW, silence_threshold=threshold
    )

    assert first.age_seconds == second.age_seconds
    assert first.last_seen_at == second.last_seen_at
    assert first.age_seconds == 90.0
    # Carried and published, so a wrong clock is visible before draft night -
    # but as a separate number that no age is computed from.
    assert first.claim_skew_seconds == pytest.approx(3690.0)
    assert second.claim_skew_seconds == pytest.approx(-3510.0)


def test_a_silent_source_says_it_has_never_been_heard_from() -> None:
    """Excludes: an unfed source rendering as a zero-second-old source.

    ``age_seconds == 0`` and ``age_seconds is None`` render identically if a
    screen formats them carelessly, so the distinction is carried by
    ``last_seen_at`` and ``silent`` together rather than by the age alone. A
    tracker that shows a five-minute-old board during a live auction without
    saying so is worse than one that admits it is blind.
    """
    fresh = freshness_of(
        [],
        transport=SourceTransport.OFFICIAL_HTTP,
        now=NOW,
        silence_threshold=timedelta(minutes=2),
    )

    assert fresh.last_seen_at is None
    assert fresh.age_seconds is None
    assert fresh.silent is True
    assert fresh.instant_count == 0
    assert fresh.silence_threshold_seconds == 120.0


def test_one_sources_freshness_is_never_computed_from_anothers() -> None:
    """Excludes: a live bridge making a dead official source look current.

    ``freshness_of`` is handed the whole instant list by ``reconcile``, so the
    filter is doing real work rather than restating an already-partitioned
    input. Without it, the official source's age would be the bridge's.
    """
    everything = [
        _instant(
            transport=SourceTransport.BRIDGE_CAPTURE,
            artifact_key="k",
            player_label=JOKIC,
            received_at=NOW,
        ),
        _instant(
            transport=SourceTransport.OFFICIAL_HTTP,
            artifact_key="sha256:old",
            player_label=EDWARDS,
            received_at=NOW - timedelta(minutes=30),
        ),
    ]

    bridge, official = (
        freshness_of(
            everything,
            transport=transport,
            now=NOW,
            silence_threshold=timedelta(minutes=2),
        )
        for transport in (SourceTransport.BRIDGE_CAPTURE, SourceTransport.OFFICIAL_HTTP)
    )

    assert bridge.age_seconds == 0.0
    assert bridge.silent is False
    assert official.age_seconds == 1800.0
    assert official.silent is True


# --------------------------------------------------------------------------
# 4. the service: storing, re-storing, applying
# --------------------------------------------------------------------------


def test_a_capture_becomes_observations_with_their_transport_recorded(session: Session) -> None:
    """Excludes: observations that cannot say which pipe produced them.

    Provenance is not decoration here. It is the only thing that lets the
    reconciliation report tell one read from two, which is the defect the whole
    first section of this file is about, and a manifest that omitted it
    reported ``witnessed: true`` forever with nothing in its output able to
    reveal the mistake.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[
            {"teamId": "t1", "playerName": JOKIC, "overallPick": 1},
            {"teamId": "t2", "playerName": EDWARDS, "overallPick": 2},
        ],
        dedupe_key="capture-one",
    )

    outcome = feed_service.ingest(session, draft)

    bridge = next(
        source for source in outcome.sources if source.transport is SourceTransport.BRIDGE_CAPTURE
    )
    assert bridge.artifacts_scanned == 1
    assert bridge.artifacts_examined == 1
    assert bridge.observations_written == 2

    rows = feed_service.load_observations(session, draft)
    assert {row.transport.value for row in rows} == {"bridge_capture"}
    assert {row.artifact_key for row in rows} == {"capture-one"}
    assert sorted(row.player_label or "" for row in rows) == sorted([JOKIC, EDWARDS])
    assert all(row.participant_id is not None for row in rows)


def test_a_busy_bridge_for_the_wrong_league_is_distinguishable_from_a_quiet_one(
    session: Session,
) -> None:
    """Excludes: "nothing arrived" and "the league id is wrong" rendering alike.

    Both produce ``artifacts_examined == 0``, and they call for opposite
    actions at 7:14pm: check the userscript, or check the configured league.
    One number cannot separate them, which is why the scanned count exists.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[{"teamId": "t1", "playerName": JOKIC}],
        dedupe_key="other-league",
        league_id="a-different-league",
    )

    busy = feed_service.ingest_bridge(session, draft, _context())
    assert (busy.artifacts_scanned, busy.artifacts_examined) == (1, 0)
    assert feed_service.load_observations(session, draft) == []

    for row in session.query(BridgePayload).all():
        session.delete(row)
    session.flush()

    quiet = feed_service.ingest_bridge(session, draft, _context())
    assert (quiet.artifacts_scanned, quiet.artifacts_examined) == (0, 0)


def test_re_ingesting_the_same_capture_writes_nothing_new(session: Session) -> None:
    """Excludes: a republishing draft board multiplying every pick.

    Fantrax resends the whole board on each pick, so this is the ordinary case
    and not an edge one. The count is asserted from the table rather than from
    the return value, because a return value of zero is also what a function
    that silently failed to write would report.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(session, records=[{"teamId": "t1", "playerName": JOKIC}], dedupe_key="capture-one")

    first = feed_service.ingest_bridge(session, draft, _context())
    second = feed_service.ingest_bridge(session, draft, _context())

    assert first.observations_written == 1
    assert second.observations_written == 0
    assert second.observations_already_present == 1
    assert len(feed_service.load_observations(session, draft)) == 1


def test_the_uniqueness_of_an_observation_is_a_database_guarantee(session: Session) -> None:
    """Excludes: idempotence that holds only because one function checks first.

    The in-Python set makes the ordinary re-ingest cheap. It is not the
    guarantee: two ingests racing would both pass it. This asserts the
    constraint underneath, so the property survives a caller that does not use
    ``_store``.
    """
    from sqlalchemy.exc import IntegrityError

    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)

    def _row() -> DraftFeedObservation:
        return DraftFeedObservation(
            draft_id=draft.id,
            transport="bridge_capture",
            artifact_key="capture-one",
            locator="responses[0].data.draftPicks[0]",
            recogniser="test",
            observed_at=NOW,
            kind="selection",
            team_external_id="t1",
            player_label=JOKIC,
        )

    session.add(_row())
    session.flush()
    session.add(_row())
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_applying_appends_through_the_ordinary_draft_log(session: Session) -> None:
    """Excludes: a machine-fed pick taking a path a typed pick does not.

    If the feed wrote ``draft_events`` directly it would bypass turn order,
    roster limits and the duplicate-player check — every rule the tracker
    already enforces — and the first evidence of that would be a corrupt board
    mid-draft. The note is asserted because it is what makes a fed pick
    identifiable after the fact.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[
            {"teamId": "t1", "playerName": JOKIC, "overallPick": 1},
            {"teamId": "t2", "playerName": EDWARDS, "overallPick": 2},
        ],
        dedupe_key="capture-one",
    )
    feed_service.ingest(session, draft)

    outcome = feed_service.apply_observations(session, draft)

    assert outcome.halted is None
    assert [event.player_label for event in outcome.applied] == [JOKIC, EDWARDS]
    events = draft_service.load_events(session, draft)
    assert [event.player_label for event in events] == [JOKIC, EDWARDS]
    assert all((event.note or "").startswith("feed:bridge_capture:") for event in events)


def test_picks_are_applied_in_the_order_the_draft_happened(session: Session) -> None:
    """Excludes: arrival order being mistaken for draft order.

    A republishing board resends the whole list, so captures arrive in an order
    that has nothing to do with the draft. An ordered draft refuses an
    out-of-turn pick, so applying in arrival order would fail on ordinary
    traffic. The capture here lists the second pick first.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[
            {"teamId": "t2", "playerName": EDWARDS, "overallPick": 2},
            {"teamId": "t1", "playerName": JOKIC, "overallPick": 1},
        ],
        dedupe_key="capture-one",
    )
    feed_service.ingest(session, draft)

    outcome = feed_service.apply_observations(session, draft)

    assert outcome.halted is None
    assert [event.player_label for event in outcome.applied] == [JOKIC, EDWARDS]


def test_an_out_of_turn_pick_halts_the_run_rather_than_being_skipped(session: Session) -> None:
    """Excludes: one misread pick silently desynchronising every later one.

    Skipping is the tempting behaviour and it is wrong: in an ordered draft
    every subsequent pick would then be attributed to the wrong seat, and the
    owner would discover it several rounds later. Halting is loud and
    recoverable.

    The reading in which ``halted`` being set would be true while the defect
    was present is one where later observations were applied anyway, so the
    later pick is asserted absent from the log as well.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    # Seat 2 is claimed to have picked first, which a snake draft refuses.
    _capture(
        session,
        records=[
            {"teamId": "t2", "playerName": JOKIC, "overallPick": 1},
            {"teamId": "t2", "playerName": EDWARDS, "overallPick": 2},
        ],
        dedupe_key="capture-one",
    )
    feed_service.ingest(session, draft)

    outcome = feed_service.apply_observations(session, draft)

    assert outcome.halted == "draft_pick_out_of_turn"
    assert outcome.applied == ()
    assert [reason for _, reason in outcome.skipped] == ["draft_pick_out_of_turn"]
    assert draft_service.load_events(session, draft) == []


def test_a_pick_already_in_the_log_is_linked_not_appended_twice(session: Session) -> None:
    """Excludes: a pick the owner typed being appended again by the feed.

    This is the case that decides whether he can stop typing *mid-draft* rather
    than only from a cold start: he will have entered some picks by hand before
    turning the feed on. The observation is linked to the sequence that already
    holds the player, so the provenance of that pick stays answerable.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    state = draft_service.record_pick(
        session,
        draft,
        participant_id=draft.participants[0].id,
        player_label=JOKIC,
    )
    typed_sequence = state.last_sequence

    _capture(
        session,
        records=[{"teamId": "t1", "playerName": JOKIC, "overallPick": 1}],
        dedupe_key="capture-one",
    )
    feed_service.ingest(session, draft)
    outcome = feed_service.apply_observations(session, draft)

    assert outcome.applied == ()
    assert [reason for _, reason in outcome.skipped] == ["already_in_log"]
    assert len(draft_service.load_events(session, draft)) == 1
    row = feed_service.load_observations(session, draft)[0]
    assert row.applied_event_sequence == typed_sequence
    assert row.skipped_reason == "already_in_log"


def test_an_auction_capture_records_the_price_exactly(session: Session) -> None:
    """Excludes: a clearing price arriving through binary floating point.

    ``draft_events.amount`` is ``Numeric(10, 2)`` and a JSON ``41.1`` becomes
    ``41.10000000000000142...`` through ``Decimal(float)``. Money does not
    round-trip through a float, and an auction budget that is off by a cent is
    a budget the owner cannot reconcile against Fantrax's own screen.
    """
    league = _league(
        session,
        draft_type=DraftType.AUCTION,
        budget=Decimal("200.00"),
    )
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[{"teamId": "t1", "playerName": JOKIC, "winningBid": 41.1}],
        dedupe_key="capture-one",
    )

    feed_service.ingest(session, draft)
    row = feed_service.load_observations(session, draft)[0]
    assert row.amount == Decimal("41.1")

    outcome = feed_service.apply_observations(session, draft)
    assert len(outcome.applied) == 1
    assert draft_service.load_events(session, draft)[0].amount == Decimal("41.10")


def test_a_draft_whose_seats_are_not_linked_is_refused_not_fed(session: Session) -> None:
    """Excludes: a mock against strangers being fed from a stranger's league.

    Most mocks have no linked seats. Without the anchor the recogniser is
    matching on guessed key names alone, so the honest answer is to refuse and
    say which fact is missing rather than to read the payload anyway.
    """
    league = _league(session)
    teams = _teams(session, league, [None, None])
    draft = _draft(session, league, teams)

    outcome = feed_service.ingest(session, draft)

    assert outcome.context_unavailable == "seats_not_linked"
    assert outcome.sources == ()
    assert feed_service.load_observations(session, draft) == []

    status = feed_service.feed_status(session, draft, now=NOW)
    assert status.context_unavailable == "seats_not_linked"
    # Still reports freshness, because "we cannot read this draft" and "we can
    # but have heard nothing" must both be visible rather than one hiding the
    # other.
    assert [fresh.silent for fresh in status.freshness] == [True, True]


def test_status_reports_freshness_before_anything_has_arrived(session: Session) -> None:
    """Excludes: an empty feed reporting as a healthy one.

    Both transports have to appear in the status even when neither has produced
    anything, or the screen has no row on which to say "blind".
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)

    status = feed_service.feed_status(session, draft, now=NOW)

    assert status.context_unavailable is None
    assert status.observation_count == 0
    assert {fresh.transport for fresh in status.freshness} == {
        SourceTransport.BRIDGE_CAPTURE,
        SourceTransport.OFFICIAL_HTTP,
    }
    assert all(fresh.silent for fresh in status.freshness)
    assert all(fresh.last_seen_at is None for fresh in status.freshness)
    assert status.reconciliation is None


def test_the_official_source_being_down_does_not_cost_the_bridge(session: Session) -> None:
    """Excludes: losing the live board because corroboration failed.

    The bridge is the primary path. An exception from the official client is
    reported as an unavailable source and never raised, because on draft night
    a missing second opinion is an inconvenience and a missing board is the end
    of the tool's usefulness.
    """

    class Broken:
        def get_draft_picks_with_provenance(
            self, league_id: str, *, max_age: timedelta | None = None
        ) -> tuple[list[FantraxDraftPick], str, datetime]:
            raise RuntimeError("fxea returned 503")

    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(session, records=[{"teamId": "t1", "playerName": JOKIC}], dedupe_key="capture-one")

    outcome = feed_service.ingest(session, draft, client=Broken())

    bridge = next(
        source for source in outcome.sources if source.transport is SourceTransport.BRIDGE_CAPTURE
    )
    official = next(
        source for source in outcome.sources if source.transport is SourceTransport.OFFICIAL_HTTP
    )
    assert bridge.observations_written == 1
    assert official.unavailable == "RuntimeError: fxea returned 503"
    assert official.observations_written == 0


def test_two_pipes_naming_one_player_produce_one_pick_and_a_witness(session: Session) -> None:
    """Excludes: corroboration being recorded as a second selection.

    This is the whole point of running two sources: the second read must make
    the first more trustworthy without touching the board. One log entry, two
    observations, and the second observation visible as corroboration rather
    than lost.
    """

    class Official:
        def get_draft_picks_with_provenance(
            self, league_id: str, *, max_age: timedelta | None = None
        ) -> tuple[list[FantraxDraftPick], str, datetime]:
            return (
                [
                    FantraxDraftPick(
                        team_id="t1",
                        player_id=None,
                        player_name=JOKIC,
                        round_number=None,
                        pick_number=None,
                        overall_pick=1,
                        auction_amount=None,
                    )
                ],
                "officialsha",
                NOW,
            )

    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[{"teamId": "t1", "playerName": JOKIC, "overallPick": 1}],
        dedupe_key="capture-one",
    )

    feed_service.ingest(session, draft, client=Official())
    rows = feed_service.load_observations(session, draft)
    assert {row.transport.value for row in rows} == {"bridge_capture", "official_http"}

    outcome = feed_service.apply_observations(session, draft)
    assert len(outcome.applied) == 1
    assert [reason for _, reason in outcome.skipped] == ["duplicate_within_run"]
    # The corroborating observation is linked to the entry it corroborates, not
    # left dangling: "which pick was this the second read of" stays answerable.
    corroboration = next(
        row for row in feed_service.load_observations(session, draft) if row.skipped_reason
    )
    assert corroboration.applied_event_sequence == outcome.applied[0].sequence
    assert len(draft_service.load_events(session, draft)) == 1

    status = feed_service.feed_status(session, draft, now=NOW)
    assert status.reconciliation is not None
    assert status.reconciliation.independence.independent is True
    assert status.reconciliation.witnessed_by_two_transports == 1


# --------------------------------------------------------------------------
# 5. the HTTP surface
# --------------------------------------------------------------------------


def test_the_feed_endpoint_publishes_freshness_and_its_limits(
    client: TestClient, session: Session
) -> None:
    """Excludes: a screen that can render a board without rendering its age.

    Everything the frontend lane needs to say "this is what I know and this is
    when I last heard anything" has to be in the response body, because a
    client that has to compute freshness itself will compute it from whatever
    timestamp is nearest to hand — which is the source's own.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    session.commit()

    response = client.get(f"/api/v1/drafts/{draft.id}/feed")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["draft_id"] == draft.id
    assert body["context_unavailable"] is None
    assert {entry["transport"] for entry in body["freshness"]} == {
        "bridge_capture",
        "official_http",
    }
    for entry in body["freshness"]:
        assert entry["silent"] is True
        assert entry["last_seen_at"] is None
        assert entry["age_seconds"] is None
        assert entry["silence_threshold_seconds"] == 120.0
    assert body["as_of"] is not None


def test_ingesting_over_http_records_and_applies(client: TestClient, session: Session) -> None:
    """The end-to-end path the owner's board actually uses.

    Asserted through HTTP rather than the service because the frontend lane
    builds against the document, and a service-level test would pass while the
    response model dropped a field the screen needs.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[
            {"teamId": "t1", "playerName": JOKIC, "overallPick": 1},
            {"teamId": "t2", "playerName": EDWARDS, "overallPick": 2},
        ],
        dedupe_key="capture-one",
    )
    session.commit()

    response = client.post(f"/api/v1/drafts/{draft.id}/feed/ingest", json={"apply": True})

    assert response.status_code == 200, response.text
    body = response.json()
    bridge = next(source for source in body["sources"] if source["transport"] == "bridge_capture")
    assert bridge["artifacts_scanned"] == 1
    assert bridge["artifacts_examined"] == 1
    assert bridge["observations_written"] == 2
    assert body["applied"]["halted"] is None
    assert [event["player_label"] for event in body["applied"]["events"]] == [JOKIC, EDWARDS]
    assert body["status"]["observation_count"] == 2

    events = client.get(f"/api/v1/drafts/{draft.id}/events").json()
    assert [event["player_label"] for event in events["events"]] == [JOKIC, EDWARDS]


def test_ingesting_without_apply_records_but_does_not_touch_the_log(
    client: TestClient, session: Session
) -> None:
    """Excludes: an ingest that cannot be run to look before it acts.

    Recording and applying are separate because the first is safe and the
    second changes a board. The default is asserted here rather than described,
    since a default that flips is not visible in any single call site.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[{"teamId": "t1", "playerName": JOKIC, "overallPick": 1}],
        dedupe_key="capture-one",
    )
    session.commit()

    body = client.post(f"/api/v1/drafts/{draft.id}/feed/ingest", json={"apply": False}).json()

    assert body["status"]["observation_count"] == 1
    assert body["applied"] is None
    assert body["status"]["pending_count"] == 1
    assert client.get(f"/api/v1/drafts/{draft.id}/events").json()["events"] == []


def test_the_feed_endpoints_refuse_an_unknown_draft(client: TestClient) -> None:
    """A stable error contract, asserted on the body and not only the code."""
    missing = client.get("/api/v1/drafts/98765/feed")
    assert missing.status_code == 404
    assert missing.json()["error"] == "draft_not_found"

    refused = client.post("/api/v1/drafts/98765/feed/ingest", json={})
    assert refused.status_code == 404
    assert refused.json()["error"] == "draft_not_found"


# --------------------------------------------------------------------------
# 6. adapter gate: drift against the pinned client
# --------------------------------------------------------------------------


def test_the_envelope_shape_still_matches_the_pinned_client() -> None:
    """Excludes: this recogniser's envelope assumption rotting silently.

    There is no captured Fantrax draft-room response in this repository, so
    there is nothing to record as a fixture of the real thing, and a synthesised
    one committed to ``tests/fixtures`` would be a hand-written mock wearing a
    recording's clothes — the manifest would have to carry a ``captured_at`` for
    something never captured. What *is* a real artifact is the pinned
    ``fantraxapi`` client, which talks to this exact endpoint. Reading the
    expressions out of its installed source is a genuine drift check against a
    third party rather than a restatement of our own constants.

    What this does not exclude: that ``getDraftPicks`` returns draft *results*
    rather than tradeable future pick assets. Nothing available here settles
    that, and no amount of envelope checking will. See
    ``docs/adapters/fantrax-official.md``.
    """
    fantraxapi = pytest.importorskip("fantraxapi.api")
    source = inspect.getsource(fantraxapi._request)

    assert version("fantraxapi") == "1.0.1", (
        "The evidence below was read from 1.0.1. A different version needs "
        "rereading rather than re-asserting."
    )

    # The three facts recognise_bridge_payload actually depends on, quoted from
    # the client rather than paraphrased.
    assert 'params={"leagueId": league_id}' in source, (
        "leagueId is no longer a query parameter, so league_id_in() can no "
        "longer attribute a capture to a league and the pre-filter is void."
    )
    assert 'response_json["responses"]' in source, (
        "The reply envelope is no longer keyed on 'responses'."
    )
    assert '[r["data"] for r in response_json["responses"]]' in source, (
        "The reply is no longer a positionally aligned list of {'data': ...} "
        "blocks, which is what makes scanning every element correct."
    )
    assert 'json_data = {"msgs":' in source, (
        "The request still batches msgs and still carries the method name in "
        "the body, which the userscript does not capture - which is why this "
        "recogniser discriminates on content and not on an RPC name."
    )
    assert '"pageError" in response_json' in source, (
        "Fantrax no longer signals errors in-band with HTTP 200, so the "
        "page_error branch in the recogniser may be dead."
    )


def test_a_logged_out_reply_is_named_rather_than_called_a_shape_change() -> None:
    """Excludes: an expired cookie presenting as a Fantrax redesign.

    Fantrax answers a logged-out request with HTTP 200 and a ``pageError``
    block — read from ``fantraxapi._request``, which checks for it *after* the
    status check for exactly this reason. Both states produce no picks. Only
    one of them is fixed by logging in again, and on draft night the owner has
    minutes, not an afternoon, to tell them apart.
    """
    result = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json={"pageError": {"code": "WARNING_NOT_LOGGED_IN", "title": "Not Logged In"}},
        dedupe_key="k",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )

    assert result.rejected == "page_error:WARNING_NOT_LOGGED_IN"
    assert result.instants == ()
    assert result.unrecognised[0].example_locator == "$.pageError"


def test_the_recogniser_reads_every_response_in_the_batch() -> None:
    """Excludes: reading ``responses[0]`` and missing the draft block.

    ``msgs`` is an array and the reply is positionally aligned with it, so the
    draft data is not reliably first. A recogniser that indexed ``[0]`` would
    work in every hand-made test and fail against a real batched call.
    """
    body = {
        "responses": [
            {"data": {"leagueInfo": {"name": "not picks"}}},
            {"data": {"draftPicks": [{"teamId": "t1", "playerName": HALIBURTON}]}},
        ]
    }

    result = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=body,
        dedupe_key="k",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )

    assert [instant.player_label for instant in result.instants] == [HALIBURTON]
    assert result.instants[0].provenance.locator.startswith("responses[1].data")
