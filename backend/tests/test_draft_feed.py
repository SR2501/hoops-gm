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

import ast
import inspect
import json
import subprocess
import textwrap
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Integer, Numeric, String
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.db.models.bridge import BridgePayload
from hoops_gm.db.models.draft import Draft
from hoops_gm.db.models.draft_feed import DraftFeedObservation
from hoops_gm.db.models.enums import DraftFeedTransport, DraftToolUsage, DraftType
from hoops_gm.db.models.league import FantasyTeam, League
from hoops_gm.draft import service as draft_service
from hoops_gm.draft.feed import (
    InstantKind,
    InstantProvenance,
    ObservedInstant,
    RecognitionContext,
    RecognitionResult,
    SourceTransport,
    freshness_of,
    league_id_in,
    recognise_bridge_payload,
    recognise_official_draft_picks,
    reconcile,
)
from hoops_gm.draft.feed import service as feed_service
from hoops_gm.draft.feed.observations import matching_key
from hoops_gm.draft.feed.recognise import (
    MAX_AMOUNT,
    MAX_ARTIFACT_KEY_CHARS,
    MAX_COORDINATE,
    MAX_EXTERNAL_ID_CHARS,
    MAX_LABEL_CHARS,
    MAX_LOCATOR_CHARS,
    _as_amount,
    _as_int,
    _as_text,
    _player_label,
)
from hoops_gm.identity.names import normalize_key
from hoops_gm.ingest.fantrax_official.models import FantraxDraftPick
from hoops_gm.ingest.fantrax_official.parsers import parse_draft_picks

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
    source: str = "xhr",
) -> BridgePayload:
    row = BridgePayload(
        schema_name="hoops-gm.bridge-payload.v1",
        source=source,
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


def _snapshot(
    session: Session,
    *,
    dedupe_key: str,
    league_id: str = LEAGUE,
    source: str = "rendered-view",
    view: str = "draft",
    created_at: datetime = NOW,
) -> BridgePayload:
    """A page-snapshot capture, exactly as the userscript stores one.

    ``source`` is one of the labels ``userscript/src/capture.js`` applies to
    rendered HTML, and the URL is the *page* URL rather than ``/fxpa/req``,
    because that is what ``capturePageSnapshot`` records. ``body_json`` is
    ``None`` with ``body_parse_error`` set, which is what a ``JSON.parse`` of
    HTML produces.
    """
    row = BridgePayload(
        schema_name="hoops-gm.bridge-payload.v1",
        source=source,
        captured_at=created_at,
        request_method="GET",
        request_url=f"https://www.fantrax.com/fantasy/league/{league_id}/{view}",
        response_status=200,
        response_ok=True,
        response_content_type="text/html",
        body_raw="<html><body>draft board</body></html>",
        body_json=None,
        body_parse_error="Unexpected token < in JSON at position 0",
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
        body_json=_envelope([{"teamId": "t1", "playerName": JOKIC, "overallPick": 1}]),
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
        body_json=_envelope([{"teamId": "t1", "playerName": JOKIC, "overallPick": 1}]),
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
                {"teamId": "t1", "playerName": JOKIC, "overallPick": 1},
                {"teamId": "not-a-seat-in-this-draft", "playerName": EDWARDS, "overallPick": 2},
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

    **The ``budgetLeft`` case alone did not exclude this defect.** An
    independent review pointed out that a team object's most ordinary field is
    its *name*, and ``name``/``shortName``/``displayName`` were player-label
    aliases — so a ``draftOrder`` or standings block, the likeliest list in any
    draft-room batch, satisfied both the seat anchor and the naming requirement
    and was read as a full board of picks attributed to the right seats. A
    reading in which the old flag was true while the defect was present is
    exactly this test's old body: a team record carrying no name key at all.
    Both shapes are now checked, and they are the shapes that defeated it.
    """
    for record in (
        {"teamId": "t1", "budgetLeft": 140},
        {"teamId": "t1", "name": "Team Rocket"},
        {"teamId": "t1", "shortName": "ROCK"},
        {"teamId": "t1", "displayName": "Team Rocket", "rank": 3},
    ):
        result = recognise_bridge_payload(
            url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
            body_json=_envelope([record]),
            dedupe_key="k",
            received_at=NOW,
            captured_at=None,
            context=_context(),
        )

        assert result.instants == (), record
        assert [shape.reason for shape in result.unrecognised] == ["record_names_no_player"], record


def test_lists_that_pair_a_seat_with_a_player_but_are_not_the_pick_log() -> None:
    """Excludes: reading a roster, a bid history or a claim list as the board.

    "Every record resolves to a seat and names a player" is a *shape*, and an
    independent review demonstrated four distinct lists in a draft room with
    that exact shape, each of which this module read as the pick log. They are
    not equally harmful and the difference is worth naming:

    * a **keeper roster** at draft open contains players nobody drafted, and
      ``apply_observations`` would have turned every one into a real
      ``draft_events`` entry;
    * a **bid history** contains the same player repeatedly, and the first bid
      would have been credited as the clearing price;
    * a **claim list** and an **on-the-clock block** invent picks outright.

    Each refusal below is asserted with its own reason string rather than
    "something was refused", because a single guard that happened to catch all
    four would be indistinguishable from four guards that each catch one, and
    only the second is what is written here.

    The reading in which these flags are true while the defect is present: a
    recogniser that refuses *everything* passes this test perfectly. That is why
    :func:`test_a_real_looking_pick_log_is_still_accepted` sits immediately
    below and is not optional.
    """
    cases: list[tuple[DraftType, str, list[dict[str, Any]]]] = [
        (
            DraftType.SNAKE,
            "record_missing_draft_coordinate",
            [
                # A keeper roster: seat, player, no position in the draft.
                {"teamId": "t1", "playerId": "p1", "playerName": JOKIC},
                {"teamId": "t2", "playerId": "p2", "playerName": EDWARDS},
            ],
        ),
        (
            DraftType.AUCTION,
            "record_missing_draft_coordinate",
            [
                # The same roster in an auction: no price, so not a sale.
                {"teamId": "t1", "playerId": "p1", "playerName": JOKIC},
                {"teamId": "t2", "playerId": "p2", "playerName": EDWARDS},
            ],
        ),
        (
            DraftType.AUCTION,
            "duplicate_player_in_list",
            [
                # A bid history. ``bid`` is an amount alias, so this satisfies
                # the coordinate rule and only the duplicate rule stops it —
                # which is the point: under auction it is the last line of
                # defence against the opening bid being read as the sale price.
                {"teamId": "t1", "playerId": "p9", "playerName": HALIBURTON, "bid": 12},
                {"teamId": "t2", "playerId": "p9", "playerName": HALIBURTON, "bid": 14},
                {"teamId": "t1", "playerId": "p9", "playerName": HALIBURTON, "bid": 17},
            ],
        ),
        (
            DraftType.SNAKE,
            "player_identity_is_the_seat",
            [
                # A team block whose own id is echoed under a player-shaped key
                # — the residual case the narrowed name aliases cannot exclude.
                {"teamId": "t1", "playerId": "t1", "name": "Team Rocket", "overallPick": 1},
                {"teamId": "t2", "playerId": "t2", "name": "Slam Dunkers", "overallPick": 2},
            ],
        ),
    ]
    for draft_type, expected, records in cases:
        result = recognise_bridge_payload(
            url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
            body_json=_envelope(records),
            dedupe_key="k",
            received_at=NOW,
            captured_at=None,
            context=_context(draft_type=draft_type),
        )
        assert result.instants == (), expected
        assert [shape.reason for shape in result.unrecognised] == [expected], records


def test_a_real_looking_pick_log_is_still_accepted() -> None:
    """The positive control for every refusal above.

    Without this, "refuse everything" satisfies the whole family of guard tests
    in this module — which is exactly the failure mode that let two defects
    through a suite where every test named a defect. A snake pick log and an
    auction sale log, each carrying the coordinate its kind is defined by, must
    still be read.
    """
    snake = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [
                {"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "overallPick": 1},
                {"teamId": "t2", "playerId": "p2", "playerName": EDWARDS, "overallPick": 2},
            ]
        ),
        dedupe_key="k",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )
    assert [instant.player_label for instant in snake.instants] == [JOKIC, EDWARDS]

    auction = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [
                {"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "winningBid": 61},
                {"teamId": "t2", "playerId": "p2", "playerName": EDWARDS, "winningBid": 44},
            ]
        ),
        dedupe_key="k",
        received_at=NOW,
        captured_at=None,
        context=_context(draft_type=DraftType.AUCTION),
    )
    assert [instant.player_label for instant in auction.instants] == [JOKIC, EDWARDS]
    assert [instant.amount for instant in auction.instants] == [Decimal("61"), Decimal("44")]


def test_an_ambiguous_name_still_labels_a_record_a_player_key_identified() -> None:
    """The other half of the split above, and the reason it is a split.

    Narrowing the aliases could have been done by deleting ``name`` outright.
    That would have cost a real capability: if Fantrax names the player under
    ``name`` *and* supplies ``playerId``, the record is unambiguously about a
    player and the board should show the name rather than an id. Acceptance
    keys on the unambiguous field; display may then use the ambiguous one.

    Excludes: the fix for the team-block defect silently downgrading readable
    picks to id-only rows. A reading in which this passes while that defect is
    present would need ``player_label`` to be non-empty without the ambiguous
    key being consulted — impossible here, since ``name`` is the only name
    present.
    """
    result = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [{"teamId": "t1", "playerId": "p-jokic", "name": JOKIC, "overallPick": 1}]
        ),
        dedupe_key="k",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )

    assert [instant.player_label for instant in result.instants] == [JOKIC]
    assert [instant.player_external_id for instant in result.instants] == ["p-jokic"]


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
        body_json=_envelope([{"teamId": "t1", "playerName": JOKIC, "overallPick": 1}]),
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


def test_a_bridge_still_capturing_between_picks_is_not_called_silent() -> None:
    """Excludes: the freshness indicator crying wolf through ordinary play.

    A snake draft spends minutes at a time on one deliberation. Judging
    ``silent`` on the newest *pick* means the bridge reports silent through
    every one of them, so by the fourth round the owner has learned the
    indicator is noise — and it is the single thing on the screen that has to
    be believed the one time it is real. "Nothing new has happened" and "the
    pipe has stopped" are different facts and are now carried by different
    fields.

    The reading in which ``silent=False`` would be true while the defect it
    guards against (*a dead bridge reported as live*) is present would need a
    ``bridge_payloads`` row appearing with a recent ``created_at`` while the
    userscript is not running. Nothing else writes that table — the only path
    is ``POST /bridge/payloads``. The paired assertion below pins the other
    direction: contact older than the threshold still reads silent.
    """
    stale_pick = [
        _instant(
            transport=SourceTransport.BRIDGE_CAPTURE,
            artifact_key="k",
            player_label=JOKIC,
            received_at=NOW - timedelta(minutes=6),
        )
    ]

    without_contact = freshness_of(
        stale_pick,
        transport=SourceTransport.BRIDGE_CAPTURE,
        now=NOW,
        silence_threshold=timedelta(minutes=2),
    )
    assert without_contact.silent is True
    assert without_contact.contact_is_known is False

    still_capturing = freshness_of(
        stale_pick,
        transport=SourceTransport.BRIDGE_CAPTURE,
        now=NOW,
        silence_threshold=timedelta(minutes=2),
        contact_at=NOW - timedelta(seconds=20),
    )
    assert still_capturing.silent is False
    assert still_capturing.contact_is_known is True
    assert still_capturing.contact_age_seconds == 20.0

    # And the boundary the suppression must not cross: contact may quieten the
    # indicator for a source that has been read successfully at least once, and
    # never for one that has produced nothing. Same recent contact, no instants
    # — still silent. Without this the whole flag inverts in the case it exists
    # for, because a capture landing is not the same fact as a pick being read.
    never_read_anything = freshness_of(
        [],
        transport=SourceTransport.BRIDGE_CAPTURE,
        now=NOW,
        silence_threshold=timedelta(minutes=2),
        contact_at=NOW - timedelta(seconds=20),
    )
    assert never_read_anything.silent is True
    assert never_read_anything.instant_count == 0
    assert never_read_anything.contact_is_known is True
    assert never_read_anything.contact_age_seconds == 20.0
    # The pick clock is unchanged, so "no new pick for six minutes" is still
    # readable. The fix adds a fact; it does not overwrite one.
    assert still_capturing.age_seconds == 360.0

    gone_quiet = freshness_of(
        stale_pick,
        transport=SourceTransport.BRIDGE_CAPTURE,
        now=NOW,
        silence_threshold=timedelta(minutes=2),
        contact_at=NOW - timedelta(minutes=5),
    )
    assert gone_quiet.silent is True


def test_status_reads_the_bridges_proof_of_life_from_its_own_captures(
    session: Session,
) -> None:
    """The end-to-end half of the test above: the contact time is real.

    Excludes: the contact clock being wired to something that is not evidence
    of the bridge running — the status request's own ``now``, say, which would
    make every source permanently live. The capture here is deliberately for a
    *different* endpoint and carries no picks, because that is the ordinary
    case between selections: the userscript is polling, Fantrax is answering,
    and no pick has landed.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)

    blind = feed_service.feed_status(session, draft, now=NOW)
    bridge_before = next(
        item for item in blind.freshness if item.transport is SourceTransport.BRIDGE_CAPTURE
    )
    assert bridge_before.contact_is_known is False
    assert bridge_before.silent is True

    _capture(
        session,
        records=[],
        dedupe_key="heartbeat",
        created_at=NOW - timedelta(seconds=30),
    )

    status = feed_service.feed_status(session, draft, now=NOW)
    bridge = next(
        item for item in status.freshness if item.transport is SourceTransport.BRIDGE_CAPTURE
    )
    official = next(
        item for item in status.freshness if item.transport is SourceTransport.OFFICIAL_HTTP
    )

    assert bridge.contact_is_known is True
    assert bridge.contact_age_seconds == 30.0
    # Contact is published, and it does NOT rescue the silence flag. This feed
    # has read zero picks, so it is blind and says so. Judging ``silent`` on
    # contact alone was a real defect here: the service-worker case (Fantrax
    # serves the draft room from ``fx-sw.js``, the userscript captures only
    # page HTML, the recogniser reads nothing) still lands captures, so a feed
    # that had never seen a single pick reported ``silent=False``. A board
    # frozen at pick 4 under a green light is worse than no board.
    assert bridge.last_seen_at is None  # no pick has ever arrived
    assert bridge.silent is True
    # The official source has no recorded poll and does not borrow the
    # bridge's. Reporting it live on the strength of another pipe's traffic is
    # precisely the one-read-as-two mistake this package exists to avoid.
    assert official.contact_is_known is False
    assert official.silent is True


def test_proof_of_life_ignores_captures_that_are_not_proof_of_this_feed(
    session: Session,
) -> None:
    """Excludes: contact set by a row that is genuine but proves nothing.

    The threat is not a forged ``bridge_payloads`` row — nothing but the bridge
    endpoint writes that table. It is a **real** row that is not evidence of the
    property ``contact_at`` claims, which is "the userscript is reaching this
    league's data endpoint". Four such rows, each of which a substring match on
    the league id accepted:

    * a page snapshot, which proves the userscript is alive but not that the
      RPC endpoint is being read — the service-worker case exactly;
    * a neighbouring league whose id merely *contains* ours as a prefix;
    * our id appearing in an unrelated query parameter of another call;
    * a capture whose source label the userscript never emits.

    Each is asserted individually, because a check that only excluded one of
    them would pass a test that presented them together.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)

    def contact_known() -> bool:
        status = feed_service.feed_status(session, draft, now=NOW)
        bridge = next(
            item for item in status.freshness if item.transport is SourceTransport.BRIDGE_CAPTURE
        )
        return bridge.contact_is_known

    def store(*, url: str, source: str, key: str) -> None:
        session.add(
            BridgePayload(
                schema_name="hoops-gm.bridge-payload.v1",
                source=source,
                captured_at=NOW,
                request_method="POST",
                request_url=url,
                response_status=200,
                response_ok=True,
                response_content_type="application/json",
                body_raw="{}",
                body_json=_envelope([]),
                dedupe_key=key,
                raw_payload="{}",
                created_at=NOW,
            )
        )
        session.flush()

    assert contact_known() is False

    store(
        url=f"https://www.fantrax.com/fantasy/league/{LEAGUE}/livedraft",
        source="rendered-view",
        key="snapshot",
    )
    assert contact_known() is False, "an HTML snapshot is not proof the RPC feed is being read"

    store(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}9999",
        source="xhr",
        key="neighbour",
    )
    assert contact_known() is False, "a league id with ours as a prefix is a different league"

    store(
        url=f"https://www.fantrax.com/fxpa/req?leagueId=zzz999&ref={LEAGUE}",
        source="xhr",
        key="query-collision",
    )
    assert contact_known() is False, "our id in an unrelated parameter is a coincidence"

    store(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        source="some-source-we-have-never-seen",
        key="unknown-source",
    )
    assert contact_known() is False, "an unrecognised capture source is not known to be an RPC body"

    # ...and the row that genuinely is proof does set it, so the four refusals
    # above are discrimination rather than a lookup that never returns anything.
    store(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        source="xhr",
        key="real-rpc",
    )
    assert contact_known() is True


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
        records=[{"overallPick": 1, "teamId": "t1", "playerName": JOKIC}],
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


def test_a_draft_room_captured_only_as_html_is_reported_rather_than_skipped(
    session: Session,
) -> None:
    """Excludes: a captured draft room that reads on the screen as no capture.

    The defect: the bridge is capturing this league's draft continuously, but
    only as ``rendered-view`` HTML, because Fantrax served the room from its
    service worker and page script never saw the JSON. Those snapshots are
    stored under the *page* URL, so ``league_id_in`` returns ``None`` and the
    league pre-filter skips them before anything counts them. The owner sees
    ``examined: 0`` and goes to check a userscript that is working perfectly.

    The reading in which ``snapshots_for_this_league == 0`` would be false and
    the defect present: a snapshot for this league stored under a page URL and
    silently skipped — which is exactly the state this test constructs, and
    which produced no visible number at all before this counter existed.

    This used to assert that nothing reads the snapshot's contents. ADR-020 made
    that false: the board recogniser now reads rendered HTML as source-coordinate
    evidence, while still never presenting it as the unobserved RPC body. These
    fixtures contain no board, so this test asserts their existence and named
    refusal remain visible.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _snapshot(session, dedupe_key="snap-1", view="draft")
    _snapshot(session, dedupe_key="snap-2", view="draft", source="manual-export")

    outcome = feed_service.ingest_bridge(session, draft, _context())

    assert outcome.artifacts_examined == 0
    assert outcome.artifacts_scanned == 2
    assert outcome.snapshots_for_this_league == 2
    assert feed_service.load_observations(session, draft) == []
    joined = " ".join(outcome.notes)
    assert "snapshot" in joined
    assert "service worker" in joined


def test_a_snapshot_for_another_league_is_not_counted_as_this_drafts(
    session: Session,
) -> None:
    """Positive control for the counter above.

    Excludes: a counter that increments on any snapshot at all, which would
    report "your draft room is being captured as HTML" to an owner whose bridge
    is in fact sitting on somebody else's league. That reading is the mirror of
    the defect the previous test excludes and would be just as expensive: it
    sends him to the service-worker explanation when the real fault is the
    configured league id.

    A raw RPC capture for this league is included alongside, so this also fails
    if the snapshot branch has swallowed the ordinary path.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _snapshot(session, dedupe_key="snap-elsewhere", league_id="a-different-league")
    _capture(
        session,
        records=[{"teamId": "t1", "playerName": JOKIC, "overallPick": 1}],
        dedupe_key="real-rpc",
    )

    outcome = feed_service.ingest_bridge(session, draft, _context())

    assert outcome.snapshots_for_this_league == 0
    assert outcome.artifacts_examined == 1
    assert outcome.observations_written == 1


def test_a_snapshot_of_this_league_is_not_mistaken_for_an_rpc_body(
    session: Session,
) -> None:
    """Excludes: rendered HTML being read as though it were the JSON response.

    The userscript README is explicit that a rendered view "is never normalized
    or presented as the JSON response the userscript could not observe". This
    pins the backend to the same boundary: a snapshot contributes nothing to
    ``instants_recognised`` and writes no observation, however many of them
    arrive. A recogniser that learned to scrape the HTML would fail here, which
    is the intent — that would be a new source needing its own evidence, not a
    quiet widening of this one.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    for index in range(5):
        _snapshot(session, dedupe_key=f"snap-{index}")

    outcome = feed_service.ingest_bridge(session, draft, _context())

    assert outcome.instants_recognised == 0
    assert outcome.observations_written == 0
    assert outcome.rejected == {}
    assert outcome.snapshots_for_this_league == 5


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
    _capture(
        session,
        records=[{"teamId": "t1", "playerName": JOKIC, "overallPick": 1}],
        dedupe_key="capture-one",
    )

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


def test_the_observation_that_halted_the_run_is_still_pending_afterwards(
    session: Session,
) -> None:
    """Excludes: a halt burning the very observation it halted on.

    Halting is only the *recoverable* choice if the row survives it. Nothing in
    this package ever clears ``skipped_reason``, so setting it on the halting
    branch removed the row from ``pending`` forever: the owner resolves the
    ordering by hand, re-runs, and the pick that triggered the halt is gone —
    not applied, not pending — while ``pending_count == 0`` tells the screen
    there is nothing outstanding. That is a skip with extra steps and a louder
    log line, which is exactly what halting was chosen over.

    A reading in which ``halted`` is set while the defect is present is the
    previous behaviour, which passed
    ``test_an_out_of_turn_pick_halts_the_run_rather_than_being_skipped``
    unchanged: that test asserts nothing survives the halt. So this asserts the
    surviving row directly, both on the observation and on the count the status
    endpoint publishes.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[{"teamId": "t2", "playerName": JOKIC, "overallPick": 1}],
        dedupe_key="capture-one",
    )
    feed_service.ingest(session, draft)

    assert feed_service.apply_observations(session, draft).halted == "draft_pick_out_of_turn"

    row = feed_service.load_observations(session, draft)[0]
    assert row.skipped_reason is None
    assert row.applied_event_sequence is None
    assert feed_service.feed_status(session, draft, now=NOW).pending_count == 1

    # And it is genuinely re-appliable: give seat 1 its pick by hand and the
    # halted observation lands on the next run instead of being lost.
    draft_service.record_pick(
        session,
        draft,
        participant_id=draft.participants[0].id,
        player_label=EDWARDS,
    )
    again = feed_service.apply_observations(session, draft)
    assert again.halted is None
    assert [event.player_label for event in again.applied] == [JOKIC]


def test_a_permanent_halt_is_visible_to_a_client_that_only_polls(
    session: Session,
) -> None:
    """Excludes: a stuck feed and a queued one looking identical on the screen.

    ``halted`` is returned on the ingest response only, and a live board polls
    ``GET /drafts/{id}/feed``. Leaving the halting row pending (correctly) means
    that endpoint shows ``pending_count == 1`` — indistinguishable from an
    ordinary backlog waiting for the next apply. On an unresolvable ordering
    problem the run re-halts every time and the board quietly stops advancing
    while the status endpoint reports a healthy-looking queue.

    A reading in which the flag is true while the defect is present: asserting
    only ``pending_count == 1`` after a halt, which is what the test above does
    and which passed throughout. So this asserts ``blocked`` names the reason,
    that it *stays* named across repeated runs, and — the part that stops this
    becoming F3 in a second field — that it **clears** once the row applies.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[{"teamId": "t2", "playerName": JOKIC, "overallPick": 1}],
        dedupe_key="capture-one",
    )
    feed_service.ingest(session, draft)

    for _ in range(3):
        assert feed_service.apply_observations(session, draft).halted == "draft_pick_out_of_turn"
        status = feed_service.feed_status(session, draft, now=NOW)
        assert status.pending_count == 1
        assert status.blocked == ("draft_pick_out_of_turn",)

    # Resolve the ordering: the row applies, and the blocked reason goes with
    # it. A sticky value here would be the halting defect wearing a new name.
    draft_service.record_pick(
        session,
        draft,
        participant_id=draft.participants[0].id,
        player_label=EDWARDS,
    )
    assert feed_service.apply_observations(session, draft).halted is None
    healthy = feed_service.feed_status(session, draft, now=NOW)
    assert healthy.blocked == ()
    assert healthy.pending_count == 0


def test_a_closed_draft_with_a_backlog_says_so_rather_than_looking_queued(
    session: Session,
) -> None:
    """Excludes: the likeliest permanent halt there is, showing as a live queue.

    The end of draft night is not an exotic state. The owner closes the draft,
    the userscript keeps capturing, ``ingest`` keeps writing observations, and
    every apply run returns ``draft_closed`` before it can touch a row. The
    status endpoint then shows a pending backlog with no reason — exactly the
    "stuck, or merely queued?" question ``blocked_reason`` was added to answer,
    unanswered in the one case most likely to occur.

    A reading in which the flag is true while the defect is present: asserting
    ``halted == "draft_closed"`` on the ingest response, which was already true
    and which a polling board never sees. So this asserts the reason reaches
    ``feed_status``, which is the only surface a live screen reads.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    draft_service.record_close(session, draft)

    _capture(
        session,
        records=[{"teamId": "t1", "playerName": JOKIC, "overallPick": 1}],
        dedupe_key="after-the-bell",
    )
    feed_service.ingest(session, draft)

    outcome = feed_service.apply_observations(session, draft)
    assert outcome.halted == "draft_closed"
    status = feed_service.feed_status(session, draft, now=NOW)
    assert status.pending_count == 1
    assert status.blocked == ("draft_closed",)


def test_a_reopened_draft_does_not_keep_reporting_itself_closed(session: Session) -> None:
    """Excludes: ``draft_closed`` outliving the close it describes.

    The close is voidable — ``draft.service.record_void`` exists precisely so a
    draft closed by mistake at 11pm can be reopened. ``draft_closed`` is stamped
    on every pending row by ``apply_observations``, which is reachable only from
    ``POST /drafts/{id}/feed/ingest`` with ``apply=true``. A live screen polls
    ``GET /drafts/{id}/feed``, which never runs it. So without a status filter on
    the read side, a reopened draft reports the one string that means
    "permanently halted", for ever, on a draft that is live again.

    This defect did not pre-exist: it was introduced by the fix that added the
    stamp, which removed one stale reason by manufacturing another. A review
    demonstrated it by deleting the stamp loop and watching the false reading
    disappear.

    A reading in which the flag is true while the defect is present: asserting
    only that ``blocked == ("draft_closed",)`` *while* closed, which is correct
    behaviour and holds either way. The load-bearing assertion is the one after
    the void, with no intervening ``apply_observations`` — because an apply run
    would clear the stamp itself and hide exactly the gap being tested.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[{"teamId": "t2", "playerName": JOKIC, "overallPick": 1}],
        dedupe_key="out-of-turn",
    )
    feed_service.ingest(session, draft)

    assert feed_service.apply_observations(session, draft).halted == "draft_pick_out_of_turn"
    assert feed_service.feed_status(session, draft, now=NOW).blocked == ("draft_pick_out_of_turn",)

    state = draft_service.record_close(session, draft)
    assert feed_service.apply_observations(session, draft).halted == "draft_closed"
    closed = feed_service.feed_status(session, draft, now=NOW)
    assert closed.pending_count == 1
    assert closed.blocked == ("draft_closed",)

    # Reopen, and read the status the way a polling board does: without an
    # apply run in between.
    draft_service.record_void(session, draft, supersedes_sequence=state.last_sequence)
    reopened = feed_service.feed_status(session, draft, now=NOW)
    assert reopened.pending_count == 1
    assert reopened.blocked == ()


def test_a_reason_from_the_live_draft_does_not_outlive_it(session: Session) -> None:
    """Excludes: a stale halt reason presented as a current one.

    ``blocked_reason`` is cleared at the start of every apply run so it is
    always a fact about the most recent one. Here a real out-of-turn halt is
    recorded, the blocking observation is then resolved, and the reason must be
    gone — a *past* reason presented as a current one is the stale-reason defect
    this field was extracted from ``skipped_reason`` to avoid.

    A reading in which the flag is true while the defect is present: asserting
    only that ``blocked`` is non-empty at the first step, which holds for a
    stale value too. So this pins the transition to empty on a run that
    succeeds.

    **Note what this does not pin.** An earlier version asserted the close
    transition instead, and a review showed that assertion was satisfied by the
    stamp loop rather than by the clear it was written for: moving the clear
    below the closed-draft return left all 59 tests passing. The clear's
    position is genuinely not load-bearing, so no test here claims it is.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[{"teamId": "t2", "playerName": JOKIC, "overallPick": 2}],
        dedupe_key="out-of-turn",
    )
    feed_service.ingest(session, draft)

    assert feed_service.apply_observations(session, draft).halted == "draft_pick_out_of_turn"
    assert feed_service.feed_status(session, draft, now=NOW).blocked == ("draft_pick_out_of_turn",)

    # The pick that was missing arrives, so the run that was blocked succeeds.
    _capture(
        session,
        records=[{"teamId": "t1", "playerName": EDWARDS, "overallPick": 1}],
        dedupe_key="the-missing-one",
    )
    feed_service.ingest(session, draft)
    assert feed_service.apply_observations(session, draft).halted is None

    after = feed_service.feed_status(session, draft, now=NOW)
    assert after.pending_count == 0
    assert after.blocked == ()


def test_a_coordinate_the_reader_cannot_parse_does_not_satisfy_the_rule() -> None:
    """Excludes: the gate admitting a record the sort cannot order.

    Two reviews moved this line. ``_has_draft_coordinate`` first tested
    presence, so ``{"round": "N/A"}`` passed "every record carries the
    coordinate its kind is defined by" and produced an instant with every
    ordinal ``None``. Tightening it to parseability fixed that and left the
    nearer case: ``{"round": 1, "pick": "N/A"}`` parses, but ``_apply_order``
    needs ``overall_pick`` or *both* round and pick-in-round, so it still fell
    into the arrival-order bucket the sort exists to avoid.

    A reading in which the flag is true while the defect is present: asserting
    only that the unparseable records are refused, which was already true after
    the previous fix and says nothing about the half-ordinal record. So the
    third case below is the one that carries this test, and the positive
    control is a *fully* ordered record — deliberately not ``{"round": 1}``,
    which this rule now refuses and which the previous version of this test
    used as its control.
    """
    result = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "round": "N/A"}]
        ),
        dedupe_key="unparseable-round",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )
    assert result.instants == ()
    assert [shape.reason for shape in result.unrecognised] == ["record_missing_draft_coordinate"]

    # The auction half of the same defect: a price that is not a number.
    priced = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "winningBid": "-"}]
        ),
        dedupe_key="unparseable-price",
        received_at=NOW,
        captured_at=None,
        context=_context(draft_type=DraftType.AUCTION),
    )
    assert priced.instants == ()
    assert [shape.reason for shape in priced.unrecognised] == ["record_missing_draft_coordinate"]

    # A round with no usable pick-in-round parses but does not order. Refused,
    # so the failure is a named unreadable-payload count rather than a halt on
    # ``draft_pick_out_of_turn``, which blames the turn order for a payload
    # problem.
    half = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "round": 1, "pick": "N/A"}]
        ),
        dedupe_key="half-ordinal",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )
    assert half.instants == ()
    assert [shape.reason for shape in half.unrecognised] == ["record_missing_draft_coordinate"]

    # Positive control: a record the sort can actually order is accepted, so
    # the rule above is not "refuse everything that mentions a round".
    ok = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "round": 1, "pick": 1}]
        ),
        dedupe_key="readable-round",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )
    assert [instant.player_label for instant in ok.instants] == [JOKIC]

    # Second positive control, the other orderable shape.
    overall = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "overallPick": 1}]
        ),
        dedupe_key="readable-overall",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )
    assert [instant.player_label for instant in overall.instants] == [JOKIC]


def test_a_coordinate_that_is_not_an_exact_position_is_refused_by_name() -> None:
    """Excludes: the gate reporting a coordinate the payload never claimed.

    A third review found ``_has_draft_coordinate`` was only ever as strict as
    :func:`~hoops_gm.draft.feed.recognise._as_int`, which used a bare ``int()``.
    ``overallPick: 1.9`` therefore produced **one instant at pick 1 with no
    unrecognised shape** — not a refusal, and not the payload's own claim
    either, but a position this module invented by truncation. ``0`` and
    negatives parsed too, and were caught only by the database CHECK, arriving
    as a generic ``observations_rejected`` rather than as the named count this
    gate exists to produce.

    A reading in which the flag is true while the defect is present: asserting
    only ``instants == ()``. Storage refuses ``0`` anyway, so a test that
    checked no pick *survived* would have passed before this fix on the ``0``
    case and told us nothing. **The assertion that carries this test is the
    reason string**, which distinguishes "refused here, by name" from "refused
    two layers down, anonymously". The ``1.9`` case has no such fallback at
    all: it was stored.

    The positive control is ``2.0`` — an integral float, which is how JSON
    routinely delivers a whole number — so this is not "refuse every number
    that is not an int".
    """
    for label, pick in (("fractional", 1.9), ("zero", 0), ("negative", -2)):
        result = recognise_bridge_payload(
            url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
            body_json=_envelope(
                [{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "overallPick": pick}]
            ),
            dedupe_key=f"coordinate-{label}",
            received_at=NOW,
            captured_at=None,
            context=_context(),
        )
        assert result.instants == (), label
        assert [shape.reason for shape in result.unrecognised] == [
            "record_missing_draft_coordinate"
        ], label

    integral = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "overallPick": 2.0}]
        ),
        dedupe_key="coordinate-integral-float",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )
    assert [instant.overall_pick for instant in integral.instants] == [2]


def test_a_non_finite_price_is_refused_rather_than_raising_or_being_believed() -> None:
    """Excludes: an arbitrary captured value escaping the reader as an exception.

    ``_as_amount`` promises "a Decimal or ``None``". ``Decimal("NaN")``
    constructs successfully, so it passes the ``try`` and then raises
    ``InvalidOperation`` on the ``> 0`` comparison one line outside it. A
    review put ``"winningBid": "NaN"`` in a payload and recognition raised —
    so the newest capture did not yield "zero records and a visible count", it
    failed the ingest request that carried it.

    ``Infinity`` is the case that review missed, and it is the worse one: it
    never raises. It compares greater than zero, was returned as a **valid
    price**, and would be carried to a ``Numeric(10, 2)`` column as a real
    clearing price. A test written only against ``NaN`` would be satisfied by
    catching ``InvalidOperation`` somewhere upstream and would leave
    ``Infinity`` believed — so both are asserted here, and asserting the
    *outcome* rather than the absence of an exception is what makes the
    ``Infinity`` case visible at all.

    The positive control is a real bid, so this is not "refuse every price".
    """
    for label, bid in (("nan", "NaN"), ("lower-nan", "nan"), ("inf", "Infinity")):
        result = recognise_bridge_payload(
            url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
            body_json=_envelope(
                [{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "winningBid": bid}]
            ),
            dedupe_key=f"price-{label}",
            received_at=NOW,
            captured_at=None,
            context=_context(draft_type=DraftType.AUCTION),
        )
        assert result.instants == (), label
        assert [shape.reason for shape in result.unrecognised] == [
            "record_missing_draft_coordinate"
        ], label

    real = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "winningBid": "41.10"}]
        ),
        dedupe_key="price-real",
        received_at=NOW,
        captured_at=None,
        context=_context(draft_type=DraftType.AUCTION),
    )
    assert [instant.amount for instant in real.instants] == [Decimal("41.10")]


def test_a_price_the_column_cannot_hold_is_refused_rather_than_silently_altered(
    session: Session,
) -> None:
    """Excludes: a price that passes every check and is stored as a different number.

    ``is_finite()`` was the previous fix and it is not the same question as
    "can ``Numeric(10, 2)`` hold this". A review measured both survivors
    against the real model: ``1E+30`` stores and reloads as
    ``1000000000000000019884624838656.00``, and ``0.001`` passes the
    ``amount > 0`` CHECK, stores, and **reloads as** ``0.00``.

    The second is the one that matters at 7:14pm. It is not an error the owner
    can see: it is a player he watched sell, on the board, at no price, on the
    source that carries the prices. Nothing about that row is malformed.

    Rounding into range was rejected as the fix. This module reads prices; a
    price it altered to fit would be a number it invented, and the whole point
    of the amount gate is that an auction sale is *defined* by what it cost.

    The two positive controls are the exact column bounds — one cent and
    ``99999999.99`` — so this is not "refuse anything unusual".
    """
    for label, bid in (
        ("too-large", "1E+30"),
        ("sub-cent", "0.001"),
        ("sub-cent-tail", "41.105"),
        ("one-over-column-max", "100000000.00"),
    ):
        result = recognise_bridge_payload(
            url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
            body_json=_envelope(
                [{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "winningBid": bid}]
            ),
            dedupe_key=f"unrepresentable-{label}",
            received_at=NOW,
            captured_at=None,
            context=_context(draft_type=DraftType.AUCTION),
        )
        assert result.instants == (), label
        assert [shape.reason for shape in result.unrecognised] == [
            "record_missing_draft_coordinate"
        ], label

    for label, bid in (("cent", "0.01"), ("column-max", "99999999.99")):
        kept = recognise_bridge_payload(
            url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
            body_json=_envelope(
                [{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "winningBid": bid}]
            ),
            dedupe_key=f"representable-{label}",
            received_at=NOW,
            captured_at=None,
            context=_context(draft_type=DraftType.AUCTION),
        )
        assert [instant.amount for instant in kept.instants] == [Decimal(bid)], label

    # Asserted against storage, not only the recogniser, because the defect was
    # only ever visible after a round trip: the recogniser returned a Decimal
    # that looked perfectly reasonable and the column changed it.
    league = _league(session, draft_type=DraftType.AUCTION, budget=Decimal("200.00"))
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "winningBid": "0.001"}],
        dedupe_key="sub-cent-ingest",
    )
    outcome = feed_service.ingest(session, draft).sources[0]
    assert outcome.instants_recognised == 0
    assert [shape.reason for shape in outcome.unrecognised] == [
        "record_missing_draft_coordinate"
    ], outcome.unrecognised
    assert feed_service.load_observations(session, draft) == []


def test_a_coordinate_too_large_to_bind_is_refused_not_left_to_kill_the_ingest(
    session: Session,
) -> None:
    """Excludes: one unreadable record destroying every observation beside it.

    JSON ``1e100`` has ``float.is_integer() == True``, so the exactness rule
    added by the previous round admits it, and ``int()`` makes it a 101-digit
    integer. That does not fail as a refused row — it raises ``OverflowError``
    when SQLAlchemy binds it. ``_store`` catches ``IntegrityError`` and nothing
    else, so the exception escapes and the **whole ingest** fails, discarding
    every good pick captured in the same run.

    That is the difference this test is about. A refused record costs one row
    and reports itself; an unbindable record costs the batch. During a live
    draft those are not the same failure at all.

    The bound is the storage engine's, not a guess about draft sizes. An
    earlier version of this docstring said "signed 64 bits, which both SQLite
    and Postgres share", and that was wrong in the half that mattered:
    SQLAlchemy's ``Integer`` compiles to Postgres ``INTEGER``, which is signed
    **32** bits, while SQLite stores a 64-bit value happily. So the guard was
    set two billion times too wide and every local run agreed with it. It is
    now derived by compiling the column under the Postgres dialect — see
    ``test_every_bounded_column_this_path_writes_has_a_guard_derived_from_it``.

    A real coordinate is four digits at the very most, so nothing legitimate is
    anywhere near it — and :data:`MAX_COORDINATE` itself is asserted as accepted
    below to prove the rule is a bound and not a ceiling on plausibility.

    The good record travels in the **same capture** as the bad one. Put in a
    separate capture it would prove only that a later ingest works, which is
    not the claim.
    """
    league = _league(session, draft_type=DraftType.SNAKE)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[
            {"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "overallPick": 1e100},
            {"teamId": "t2", "playerId": "p2", "playerName": EDWARDS, "overallPick": 2},
        ],
        dedupe_key="oversized-coordinate",
    )

    outcome = feed_service.ingest(session, draft).sources[0]

    # The list is refused as a list — that is this module's admission rule and
    # not what is under test here. What is under test is that a value which
    # previously raised now produces an outcome at all.
    assert outcome.instants_recognised == 0
    assert [shape.reason for shape in outcome.unrecognised] == [
        "record_missing_draft_coordinate"
    ], outcome.unrecognised

    assert _as_int(MAX_COORDINATE) == MAX_COORDINATE
    assert _as_int(MAX_COORDINATE + 1) is None
    assert _as_int(1e100) is None


def test_a_decimal_coordinate_is_not_truncated_into_a_position() -> None:
    """Excludes: the previous round's own fix, applied to only one numeric type.

    The exactness rule was written as ``isinstance(value, float) and not
    value.is_integer()``. ``int(Decimal("1.9"))`` is also ``1``, so a
    ``Decimal`` walked straight past it and produced ``overall_pick == 1`` with
    ``unrecognised == ()`` — the identical defect, surviving inside its own fix.

    **Reachability, measured rather than asserted.** The first version of this
    test tried to drive a ``Decimal`` through a captured payload and could not:
    ``body_json`` is a JSON column, and the insert fails with *"Object of type
    Decimal is not JSON serializable"* before recognition is ever reached. That
    is a stronger statement than the prose it replaced — the bridge path cannot
    carry a ``Decimal`` at all, because the storage layer refuses to hold one.

    The guard is kept regardless: the parameter is annotated ``Any``, the
    official adapter builds its records in Python rather than from JSON, and
    the cost of being wrong about reachability is a pick silently placed at a
    position no source claimed. It is asserted at the level it is reachable at.

    The control is ``Decimal("2.0")`` — integral, and still accepted — so this
    is a test of exactness and not of the type.
    """
    assert _as_int(Decimal("1.9")) is None
    assert _as_int(Decimal("0.5")) is None
    assert _as_int(Decimal("2.0")) == 2
    assert _as_int(Decimal("2")) == 2


def test_text_longer_than_its_column_is_dropped_rather_than_stored_or_truncated(
    session: Session,
) -> None:
    """Excludes: a value that stores cleanly on SQLite and raises on Postgres.

    This one is not from a review. It is the previous finding's mechanism
    applied to the other kind of column: ``_as_text`` was unbounded, and
    ``player_label`` is ``String(128)``. **SQLite ignores a ``VARCHAR`` length
    entirely**, so an over-long name stores without complaint in every test in
    this file, and Postgres raises ``DataError`` — which, like the
    ``OverflowError`` above, is outside the ``IntegrityError`` that ``_store``
    handles and therefore costs the whole ingest.

    A defect that is invisible on the development engine and fatal on the
    deployment one is exactly what ADR-001's "every access goes through
    SQLAlchemy" is meant to keep out, and the suite could not have found it:
    the Postgres CI job runs these same tests, and none of them used a long
    string.

    **Dropped, not truncated.** A name cut to 128 characters is still a name
    and would be stored as one; the pick would show under a plausible wrong
    label. Dropping leaves the record identified by its id, which is what
    actually resolves the player, and leaves the board honest about not having
    read the name.

    Asserted at exactly the boundary in both directions, so this is a length
    rule rather than a rejection of unusual input.
    """
    assert _as_text("X" * 128, limit=MAX_LABEL_CHARS) == "X" * 128
    assert _as_text("X" * 129, limit=MAX_LABEL_CHARS) is None
    assert _as_text("X" * 64, limit=MAX_EXTERNAL_ID_CHARS) == "X" * 64
    assert _as_text("X" * 65, limit=MAX_EXTERNAL_ID_CHARS) is None

    league = _league(session, draft_type=DraftType.SNAKE)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[
            {
                "teamId": "t1",
                "playerId": "p1",
                "playerName": "N" * 5000,
                "overallPick": 1,
            }
        ],
        dedupe_key="overlong-label",
    )
    outcome = feed_service.ingest(session, draft).sources[0]

    # The record is still a pick — it has a seat, an id and a coordinate — so it
    # is stored. What must not survive is the 5000-character string.
    assert outcome.instants_recognised == 1
    rows = feed_service.load_observations(session, draft)
    assert [row.player_external_id for row in rows] == ["p1"]
    assert [row.player_label for row in rows] == [None]


def test_a_path_or_key_too_long_for_its_column_is_refused_by_name(session: Session) -> None:
    """Excludes: a whole-ingest failure caused by bookkeeping, not by a record.

    Two values reach ``String(128)`` columns without ever being a field of a
    record, so no amount of tightening the field coercers touches them:

    * ``locator`` is the path the walk took, **built from the payload's own key
      names**. Six levels of realistic Fantrax naming reaches 128 characters
      without trying, so this is not an exotic input — it is a plausible one.
    * ``artifact_key`` is the capture's ``dedupe_key``, and
      ``bridge_payloads.dedupe_key`` is ``TEXT``. The two columns are in two
      tables owned by two units and **neither is wrong on its own**; the defect
      exists only in the join between them, which is why reading either model
      alone would not reveal it.

    Both are refused rather than truncated, and for ``locator`` that choice is
    load-bearing: it is a third of the idempotency key ``(transport,
    artifact_key, locator)``. Two distinct paths truncated to the same 128
    characters collapse into one row, and the second pick is dropped as a
    duplicate — a pick **missing** from the board, with nothing reported.

    The controls are values one character inside each bound, so this is a
    length rule and not a refusal of deep payloads as such.
    """
    deep: dict[str, object] = {
        "draftPickRecords": [
            {"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "overallPick": 1}
        ]
    }
    for key in (
        "playerSelectionDisplayRecords",
        "currentDraftBoardSelectionRecords",
        "draftRoomDisplayStateForCurrentUser",
    ):
        deep = {key: deep}

    result = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json={"responses": [{"data": deep}]},
        dedupe_key="deep-locator",
        received_at=NOW,
        captured_at=None,
        context=_context(draft_type=DraftType.SNAKE),
    )
    # The record itself is entirely valid — seat, player, coordinate — so the
    # locator rule is the only thing that can refuse it. Without that, this
    # list is accepted and its rows carry a 137-character locator.
    assert result.instants == ()
    assert [shape.reason for shape in result.unrecognised] == ["locator_too_long_to_record"]
    assert len(result.unrecognised[0].example_locator) > MAX_LOCATOR_CHARS

    over_long_key = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "overallPick": 1}]
        ),
        dedupe_key="k" * 129,
        received_at=NOW,
        captured_at=None,
        context=_context(draft_type=DraftType.SNAKE),
    )
    assert over_long_key.instants == ()
    assert over_long_key.rejected == "artifact_key_too_long_to_record"

    # Control: the same payload with a key one character inside the bound is
    # read normally, and stores — so the rule is the length and nothing else.
    league = _league(session, draft_type=DraftType.SNAKE)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "overallPick": 1}],
        dedupe_key="k" * 128,
    )
    outcome = feed_service.ingest(session, draft).sources[0]
    assert outcome.instants_recognised == 1
    rows = feed_service.load_observations(session, draft)
    assert [len(row.artifact_key) for row in rows] == [128]
    assert all(len(row.locator) <= 128 for row in rows)


def test_every_bounded_column_this_path_writes_has_a_guard_derived_from_it() -> None:
    """Excludes: the *class* of defect five consecutive findings belonged to.

    Rounds five to seven each found the same shape — a value the coercer
    accepted that the column could not hold — in a different column: a price
    (``Numeric(10, 2)``), a coordinate, a name (``String(128)``), a walk path
    and a capture key (``String(128)`` each). Fixing them one at a time is how
    an eighth gets found later, on Postgres, during a draft. So this test
    enumerates the table instead.

    Two things are asserted, and the second is the one that earns its keep:

    1. every bound **equals** the column it claims to describe, computed from
       the model rather than written down twice — so narrowing a column
       without narrowing its guard is red;
    2. every column whose *storage* is bounded is **either** guarded **or**
       explicitly listed as not payload-derived — so *adding* a column is red
       until someone decides which it is. That is the half that catches the
       defect nobody has found yet.

    **The second half is not theoretical: it has now fired twice, and the
    second time it fired on this test's own scope.** First it flagged
    ``skipped_reason``, which is ``Text`` — and ``Text`` subclasses ``String``
    with ``length is None``, so the class hierarchy says "bounded" where the
    model says "unbounded". Then a review showed the enumeration was **only**
    over ``String``: appending an unlisted ``Integer`` or ``Numeric`` column
    left it green, and the ``Integer`` bound beside it was a *written-down
    constant* rather than a derived one — and it was wrong.

    ``MAX_COORDINATE`` said ``2**63 - 1``, justified in a comment claiming
    "SQLite and Postgres both cap a bound integer at signed 64 bits, and that
    is not readable off the model". SQLAlchemy's ``Integer`` compiles to
    Postgres ``INTEGER``, which is signed **32** bits, so everything from
    ``2147483648`` up passed the guard and overflowed on the engine ADR-001
    exists to protect — invisibly in SQLite, which stores it. And it *is*
    readable off the model, by compiling the column type under the Postgres
    dialect, which is what this test now does. **The claim that a fact was
    underivable was what stopped anyone deriving it.**

    **What this does not cover, stated plainly.** It checks that a bound exists
    and matches, not that the coercers are wired to it — a guard could be
    correct here and uncalled. The call sites are covered by the mutation of
    each rule separately; nothing covers both at once. It also cannot see
    columns written by other units, and it reads the *declared* type, so a
    column whose Postgres type is set by a dialect-specific variant would need
    reading here rather than assumed.
    """
    # Postgres integer widths, keyed by the DDL this model compiles to. The
    # bound has to be the *storage engine's*, and SQLite's is wider — which is
    # exactly why the wrong one survived every local run.
    postgres_integer_max = {"SMALLINT": 2**15 - 1, "INTEGER": 2**31 - 1, "BIGINT": 2**63 - 1}
    # ``postgresql.dialect`` is untyped in SQLAlchemy's stubs; the ignore is on
    # the construction only, not on anything this test concludes from it.
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]

    bounded = {
        "artifact_key": MAX_ARTIFACT_KEY_CHARS,
        "locator": MAX_LOCATOR_CHARS,
        "team_external_id": MAX_EXTERNAL_ID_CHARS,
        "player_external_id": MAX_EXTERNAL_ID_CHARS,
        "player_label": MAX_LABEL_CHARS,
        "source_seat_label": MAX_LABEL_CHARS,
    }
    # Values this module generates itself from a closed set, or that the
    # database assigns, so no payload can widen them. Listed rather than
    # skipped, so a new column cannot join them by accident.
    self_generated = {
        "transport",
        "recogniser",
        "kind",
        "id",
        "draft_id",
        "bridge_payload_id",
        "participant_id",
        # Generated by board-column enumeration, not parsed from a payload
        # integer. Its practical bound is the number of columns materialised.
        "source_seat",
        "applied_event_sequence",
    }
    # Payload-derived integers, and the guard each is bound by.
    coordinates = {"overall_pick", "round_number", "pick_in_round"}

    columns = DraftFeedObservation.__table__.columns
    for name, bound in bounded.items():
        column_type = columns[name].type
        assert isinstance(column_type, String)
        assert column_type.length == bound, name

    for column in columns:
        # ``Text`` subclasses ``String`` with ``length is None`` — unbounded, so
        # not a hazard of this kind. This distinction is drawn on the model's own
        # ``length`` rather than on the Python class, because the class hierarchy
        # says the opposite of what matters here.
        if isinstance(column.type, String) and column.type.length is not None:
            assert column.name in bounded or column.name in self_generated, (
                f"{column.name} is a bounded text column with no guard and no "
                f"declaration that it is not payload-derived"
            )
        # ``Integer`` and ``Numeric`` are bounded by the engine rather than by a
        # length, which is why the ``String``-only version of this loop could not
        # see them. ``Boolean``/``DateTime``/``Enum`` carry no payload-set width.
        # They are siblings, not subclasses — ``issubclass(Integer, Numeric)`` is
        # ``False`` — so neither branch needs to exclude the other.
        if isinstance(column.type, Integer):
            assert column.name in coordinates or column.name in self_generated, (
                f"{column.name} is an integer column with no coordinate guard and "
                f"no declaration that it is not payload-derived"
            )
        if isinstance(column.type, Numeric):
            assert column.name == "amount" or column.name in self_generated, (
                f"{column.name} is a numeric column with no guard and no "
                f"declaration that it is not payload-derived"
            )

    amount = columns["amount"].type
    assert isinstance(amount, Numeric)
    assert amount.precision is not None and amount.scale is not None
    largest = Decimal(10) ** (amount.precision - amount.scale) - Decimal(10) ** -amount.scale
    assert largest == MAX_AMOUNT, (amount.precision, amount.scale)

    # Derived, not restated: compile each coordinate column under the Postgres
    # dialect and read the width off the DDL.
    for name in coordinates:
        ddl_type = columns[name].type.compile(dialect)
        assert ddl_type in postgres_integer_max, (name, ddl_type)
        assert postgres_integer_max[ddl_type] == MAX_COORDINATE, (name, ddl_type)


def test_an_unreadable_explicit_name_is_not_replaced_by_an_ambiguous_one(
    session: Session,
) -> None:
    """Excludes: a refused field being *substituted* rather than simply lost.

    ``_as_text`` answers ``None`` for two different situations — the key was
    absent, and the key was present and unusable — and :func:`_player_label`
    treated both as "look somewhere else". A review supplied a 129-character
    ``playerName`` beside ``"name": "Seat One"``. The explicit name was refused
    (correctly), the fallback fired (incorrectly), and the pick was applied
    with ``player_label='Seat One'``: **the seat's own name on the board as the
    player taken**, with ``unrecognised == ()`` and nothing anywhere reporting
    a problem.

    The bad outcome here is not the lost name. It is that a *different* value
    was presented with the confidence of a read one, drawn from a key this
    module already classifies as ambiguous precisely because team objects carry
    it. A blank where a name should be is a question the owner can ask; a
    wrong name is one he has no reason to.

    So the rule is now about presence, not usability: an explicit player-name
    key that exists decides the answer whether or not it can be read. The
    controls below matter as much as the assertion — a genuinely absent
    ``playerName`` must still fall through, or this fix would have removed the
    feature instead of the defect.
    """
    long_name = "X" * (MAX_LABEL_CHARS + 1)

    # The defect: present-but-refused, with an ambiguous alias standing by.
    assert _player_label({"playerName": long_name, "name": "Seat One"}) is None
    # The feature, still working: absent explicit key, ambiguous alias used.
    assert _player_label({"playerId": "p1", "name": "Luka Doncic"}) == "Luka Doncic"
    # Readable explicit key still wins over the alias.
    assert _player_label({"playerName": JOKIC, "name": "Seat One"}) == JOKIC
    # And the substitution cannot reappear one alias along.
    assert _player_label({"name": long_name, "shortName": "Seat One"}) is None

    league = _league(session, draft_type=DraftType.SNAKE)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[
            {
                "teamId": "t1",
                "playerId": "p-jokic",
                "playerName": long_name,
                "name": "Seat One",
                "overallPick": 1,
            }
        ],
        dedupe_key="substituted-name",
    )

    outcome = feed_service.ingest(session, draft).sources[0]

    # Still a recorded pick — the record identifies a player by id, so refusing
    # it outright would lose a pick the source did report.
    assert outcome.instants_recognised == 1
    rows = feed_service.load_observations(session, draft)
    assert [row.player_label for row in rows] == [None]
    assert [row.player_external_id for row in rows] == ["p-jokic"]


def test_the_official_path_applies_the_same_field_bounds_as_the_bridge_path() -> None:
    """Excludes: the round-4 recogniser asymmetry, one layer further down.

    Round four closed a difference in how the two recognisers **admitted a
    list**. This is a difference in how they **read a field**, and it survived
    three subsequent rounds because each of them re-read admission.

    ``recognise_official_draft_picks`` copied ``overall_pick``,
    ``round_number``, ``pick_number``, ``player_name`` and ``player_id``
    straight out of :class:`FantraxDraftPick` into the instant. Being *typed*
    was mistaken for being *bounded*: ``int | None`` is a Python ``int``, which
    is arbitrary precision, and ``str | None`` has no length. So every guard
    the previous two rounds added existed on one path only, and the official
    source is the one that carries the prices.

    Measured before the fix: ``overall_pick=int(1e100)`` was recognised and
    raised ``OverflowError`` at flush — the whole ingest, not the row. A
    129-character ``player_name`` and a 65-character ``player_id`` were stored
    intact on SQLite and would have raised ``DataError`` on Postgres.

    **Two of these were not in the review's report.** ``overall_pick=0`` and
    ``overall_pick=-5`` were also copied through, where the bridge path refuses
    both as not one-indexed. They were found by running the neighbours of the
    reported input, and they are the reason this test asserts a rule rather
    than the three values someone happened to send.

    **What this does not fix, and it is upstream of here.**
    ``parse_draft_picks`` converts with a bare ``int()``, so ``overallPick:
    1.9`` has already become ``1`` before this function sees it. Re-coercing
    cannot recover a truncation that happened earlier — the value arriving here
    is a perfectly valid ``1``. That defect lives in
    ``hoops_gm.ingest.fantrax_official.parsers``, which this lane does not own,
    and is recorded in ``docs/handoff.md`` rather than patched here.
    """

    def official(**kwargs: Any) -> RecognitionResult:
        base: dict[str, Any] = {
            "team_id": "t1",
            "player_id": "p-jokic",
            "player_name": JOKIC,
            "overall_pick": 1,
        }
        base.update(kwargs)
        return recognise_official_draft_picks(
            [FantraxDraftPick(**base)],
            artifact_key="sha256:test",
            received_at=NOW,
            context=_context(),
        )

    # A coordinate too wide for the column no longer reaches the bind.
    result = official(overall_pick=int(1e100))
    assert [instant.overall_pick for instant in result.instants] == [None]
    assert [shape.reason for shape in result.unrecognised] == ["field_too_large_to_record"]
    assert result.unrecognised[0].keys == ("overall_pick",)

    # Neighbours the review did not report: the coordinate is one-indexed here
    # too, not merely on the bridge path.
    for bad in (0, -5, MAX_COORDINATE + 1):
        assert [i.overall_pick for i in official(overall_pick=bad).instants] == [None], bad
    assert [i.overall_pick for i in official(overall_pick=MAX_COORDINATE).instants] == [
        MAX_COORDINATE
    ]

    # Text is bounded by the same columns as the bridge path.
    over_name = official(player_name="N" * (MAX_LABEL_CHARS + 1))
    assert [instant.player_label for instant in over_name.instants] == [None]
    assert [shape.reason for shape in over_name.unrecognised] == ["field_too_large_to_record"]

    over_id = official(player_id="p" * (MAX_EXTERNAL_ID_CHARS + 1))
    assert [instant.player_external_id for instant in over_id.instants] == [None]

    # Losing *both* identifiers no longer discards the record. It becomes an
    # instant that names nobody and says why -- the official mirror of
    # ``draft-feed-unreadable-id-surfacing``. Dropping it left a record the
    # source published for one of our seats visible on ``POST`` and nowhere on
    # ``GET``, which a live board polls.
    both = official(
        player_id="p" * (MAX_EXTERNAL_ID_CHARS + 1),
        player_name="N" * (MAX_LABEL_CHARS + 1),
    )
    assert [instant.skipped_reason for instant in both.instants] == [
        "player_external_id_unreadable"
    ]
    assert both.recognised_count == 0, "a record we could not identify is not a reading"
    assert [instant.player_label for instant in both.instants] == [None]
    assert [instant.player_external_id for instant in both.instants] == [None]
    assert "record_names_no_player" in [shape.reason for shape in both.unrecognised]

    # A record naming nobody *at all* is a different fact from one whose names
    # we refused, and gets a different reason: it may simply be an unmade pick.
    nobody = official(player_id=None, player_name=None)
    assert [instant.skipped_reason for instant in nobody.instants] == ["record_names_no_player"]

    # An over-long team id cannot anchor, and says so by name.
    unanchored = official(team_id="t" * (MAX_EXTERNAL_ID_CHARS + 1))
    assert unanchored.instants == ()
    assert [shape.reason for shape in unanchored.unrecognised] == ["no_seat_anchor"]

    # Control: a healthy pick is untouched and reports nothing.
    healthy = official()
    assert [instant.overall_pick for instant in healthy.instants] == [1]
    assert [instant.player_label for instant in healthy.instants] == [JOKIC]
    assert healthy.unrecognised == ()


def test_a_capacity_refusal_survives_an_accepted_sibling_list(
    session: Session,
) -> None:
    """Excludes: a *missing pick* being reported as nothing at all.

    ``locator_too_long_to_record`` exists because ``locator`` is a third of the
    idempotency key, so a truncated path silently collapses two picks into one
    row. But every refusal was reported through one channel, gated on ``if not
    accepted_here`` — sensible for a shape refusal, since a draft-room block is
    full of lists that are simply not the pick log, and wrong for this one.

    Measured before the fix: a deep list alone produced
    ``locator_too_long_to_record``; **the same deep list beside one shallow
    accepted list produced ``unrecognised == []`` and ``rejected == None``.**
    One accepted sibling was enough to silence it. The refusal built to prevent
    a silently dropped pick was itself silently dropped.

    The distinction now drawn is which side the fault is on. A shape refusal
    says "this list is not the pick log" — noise, once something was accepted.
    A capacity refusal says "this may well be the pick log and *this module*
    cannot write down where it found it" — never noise, because the reason has
    nothing to do with the list.

    The control below is the noise case: two lists where one is accepted and
    the other is merely a different collection must still report only the
    accepted one, or this fix would have traded a silent loss for a screen
    nobody reads.
    """
    deep = (
        "draftRoomDisplayStateForCurrentUser.currentDraftBoardSelectionRecords"
        ".playerSelectionDisplayRecords.draftPickRecords"
    )
    shallow_records = [
        {"teamId": "t1", "playerId": "p-jokic", "playerName": JOKIC, "overallPick": 1}
    ]
    deep_records = [
        {"teamId": "t2", "playerId": "p-edwards", "playerName": EDWARDS, "overallPick": 2}
    ]

    def read(block: dict[str, Any]) -> RecognitionResult:
        return recognise_bridge_payload(
            url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
            body_json={"responses": [{"data": block}]},
            dedupe_key="k",
            received_at=NOW,
            captured_at=None,
            context=_context(),
        )

    def nest(path: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        block: dict[str, Any] = {}
        cursor = block
        parts = path.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = records
        return block

    alone = read(nest(deep, deep_records))
    assert [shape.reason for shape in alone.unrecognised] == ["locator_too_long_to_record"]

    together = nest(deep, deep_records)
    together["picks"] = shallow_records
    both = read(together)

    assert len(both.instants) == 1, "the shallow list is still read"
    assert "locator_too_long_to_record" in [shape.reason for shape in both.unrecognised], (
        "an accepted sibling must not silence a refusal caused by our own column"
    )

    # Control: a shape refusal beside an accepted list is still suppressed, so
    # this is a rule about the *kind* of refusal and not "report everything".
    noisy = {
        "picks": shallow_records,
        "standings": [{"teamId": "t1", "wins": 3}, {"teamId": "t2", "wins": 1}],
    }
    quiet = read(noisy)
    assert len(quiet.instants) == 1
    assert quiet.unrecognised == (), quiet.unrecognised


def test_a_numeric_string_is_read_by_json_grammar_not_python_grammar() -> None:
    """Excludes: this reader *inventing* a number from a string.

    ``int()`` and ``Decimal()`` implement Python's literal grammar, which is
    wider than anything a JSON producer emits, and the extra width is accepted
    silently rather than raised. Measured on this module before the fix:

    * ``"1_0"`` read as ``10`` — PEP 515 underscore separators;
    * ``"١٢"`` read as ``12`` — ``int()`` accepts any Unicode ``Nd`` digit;
    * ``"_10"``, ``"1__0"``, ``"10_"`` read as ``10`` by ``Decimal``, and one of
      them was **applied as a completed sale at 10.00** with nothing reported.

    None of those is a misreading of a price or a position. Each is a number
    this module made up from a string, then presented with the same confidence
    as one it read — which is the single failure this package is shaped to
    avoid. Refusing them costs a real payload nothing: a JSON *number* arrives
    as ``int`` or ``float`` and never reaches the string branch at all.

    **The grammars are deliberately narrow.** No currency symbol, no thousands
    separator, no leading ``+``, no exponent. Widening any of them should mean
    somebody has *seen* Fantrax emit it — which is a different state of
    knowledge from supposing that it might, and the difference is the whole of
    this module's method.

    ``"1e2"`` is the interesting refusal: it is not wrong as arithmetic, it
    round-trips to ``100.00`` cleanly. It is refused because a bid field
    carrying scientific notation is a shape nobody has observed, and reading it
    anyway is guessing.
    """
    for invented in (
        "1_0",
        "\u0661\u0662",  # Arabic-Indic digits: int() reads these as 12
        "_10",
        "1__0",
        "10_",
        "+12",
        "0x10",
        "1e2",
        "\uff11\uff12",  # fullwidth digits, likewise
    ):
        assert _as_int(invented) is None, invented
        assert _as_amount(invented) is None, invented

    # Controls: the forms a JSON payload actually produces are all still read,
    # or this would be a test of refusal rather than of grammar.
    assert _as_int("12") == 12
    assert _as_int(" 12 ") == 12
    assert _as_int(12) == 12
    assert _as_int(12.0) == 12
    assert _as_amount("12.50") == Decimal("12.50")
    assert _as_amount(" 12.50 ") == Decimal("12.50")
    assert _as_amount(41.10) == Decimal("41.10")
    assert _as_amount(41) == Decimal("41")

    # Width is refused before conversion, so neither constructor is handed an
    # unbounded string to parse.
    assert _as_int("9" * 5000) is None
    assert _as_amount("9" * 5000) is None


def test_a_priced_keeper_roster_is_a_known_gap_on_the_auction_path(
    session: Session,
) -> None:
    """**Pins a gap rather than a guarantee.** Read the assertion, not the name.

    ``record_missing_draft_coordinate`` excludes a keeper roster under
    ``SELECTION``, because a roster row carries no ordinal. Under ``SALE`` it
    very largely does not: the amount aliases include ``salary``, and ``salary``
    is the defining field of a keeper roster row in an auction league. A priced
    keeper roster and an auction sale log are **the same tuple**, so no
    structural rule in this module can separate them.

    This test asserts the gap is real and reachable end to end, so that nobody
    reinstates the claim — which an earlier docstring made — that this rule
    excludes keepers on the auction path. If someone later finds a genuine
    discriminator, this test should fail and be deleted along with the fix.

    **Not disproved, unestablished:** no real Fantrax auction payload has ever
    been seen, so whether ``salary`` even appears in one is unknown. The gap is
    named from the alias list, which is checkable; its frequency is not.
    """
    league = _league(session, draft_type=DraftType.AUCTION, budget=Decimal("200.00"))
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[
            {"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "salary": 30},
            {"teamId": "t2", "playerId": "p2", "playerName": EDWARDS, "salary": 22},
        ],
        dedupe_key="keeper-roster",
    )
    outcome = feed_service.ingest(session, draft).sources[0]

    # The gap, stated as an assertion: these are keepers and they are read as
    # sales. Nothing in this module currently prevents it.
    assert outcome.instants_recognised == 2
    assert outcome.unrecognised == ()
    assert [row.amount for row in feed_service.load_observations(session, draft)] == [
        Decimal("30.00"),
        Decimal("22.00"),
    ]

    # "End to end" in the docstring above means the log, not just recognition.
    # A review pointed out the claim stopped at the recogniser, so an apply-layer
    # guard added later would have falsified it with no red test. It does not
    # stop there: these become real ``draft_events``.
    applied = feed_service.apply_observations(session, draft)
    assert applied.halted is None
    assert [event.player_label for event in applied.applied] == [JOKIC, EDWARDS]
    assert [event.kind for event in applied.applied] == [InstantKind.SALE, InstantKind.SALE]

    # And the gap is now *reported*, not merely pinned here. A review asked
    # where this limit was visible to someone who is not reading the suite; the
    # honest answer was "nowhere", because every other channel reports a clean
    # read on exactly these rows. Those three assertions are the reason the
    # note has to exist, so they are made here rather than described.
    assert outcome.fields_dropped == ()
    assert outcome.coerced_to_kind == 0
    assert any("keeper" in note for note in outcome.notes), outcome.notes


def test_the_auction_keeper_note_is_conditioned_on_facts_not_on_a_guess(
    session: Session,
) -> None:
    """Excludes: a note that fires on every scan, and so carries no information.

    The note is not a classifier — a priced keeper row and a sale row are the
    same tuple, so nothing here can mark *which* rows are suspect. It is a
    statement about what this feed cannot know, conditioned on one fact it does
    hold: this scan produced at least one sale.

    **The assertion that carries this test is the second one**, an auction
    league that read nothing. A note appended unconditionally would sit on the
    board all draft night saying a feed that has read no sales might have
    misread a keeper as one, and a caveat that is always present is read as
    furniture.

    The snake case below is a *weaker* check than it looks and is kept
    deliberately, labelled. It cannot currently fail: ``_kind_for`` derives one
    kind per scan from the draft type, so a snake context yields no ``SALE``
    instants by construction and the note's own condition is unreachable there.
    An earlier version of this test claimed the snake case was load-bearing; a
    mutation dropping the draft-type clause from the condition **survived the
    whole suite** and proved otherwise, which is why that clause is now gone.
    What the snake case still guards is the day someone makes kind per-record:
    on that day this assertion starts doing work, and it is cheaper to leave it
    than to rediscover the coupling.
    """
    snake = _league(session, fantrax_league_id="LG-SNAKE", draft_type=DraftType.SNAKE)
    snake_teams = _teams(session, snake, ["t1", "t2"])
    snake_draft = _draft(session, snake, snake_teams)
    assert snake.fantrax_league_id is not None
    _capture(
        session,
        records=[{"teamId": "t1", "playerId": "p1", "playerName": JOKIC, "overallPick": 1}],
        dedupe_key="snake-board",
        league_id=snake.fantrax_league_id,
    )
    snake_outcome = feed_service.ingest(session, snake_draft).sources[0]
    assert snake_outcome.instants_recognised == 1
    assert not any("keeper" in note for note in snake_outcome.notes), snake_outcome.notes

    # The condition is "sales were read", not "the league is an auction", so an
    # auction that read nothing must stay silent. This is the discriminating
    # case: it is the one a mutation can actually break.
    quiet = _league(
        session,
        fantrax_league_id="LG-QUIET",
        draft_type=DraftType.AUCTION,
        budget=Decimal("200.00"),
    )
    quiet_teams = _teams(session, quiet, ["t1", "t2"])
    quiet_draft = _draft(session, quiet, quiet_teams)
    quiet_outcome = feed_service.ingest(session, quiet_draft).sources[0]
    assert quiet_outcome.instants_recognised == 0
    assert not any("keeper" in note for note in quiet_outcome.notes), quiet_outcome.notes


def test_the_official_path_has_no_coordinate_rule_and_reports_the_loss_by_name(
    session: Session,
) -> None:
    """Excludes: reasoning about the bridge's coordinate rule applied to both.

    Three docstrings in this package argued that the format-snapshot disaster —
    an auction log read under a snake snapshot, every price stripped — *cannot
    reach an instant*, because ``record_missing_draft_coordinate`` refuses the
    list first. That holds for ``recognise_bridge_payload``.
    ``recognise_official_draft_picks`` has no such rule: no ``_accept_list``, no
    ``_has_draft_coordinate``. On the official source the case is reachable, and
    a docstring built on the opposite told the owner to ignore it.

    A reading in which the flag is true while the defect is present: asserting
    ``every_instant_coerced`` is ``True`` here, which it also is for a perfectly
    healthy auction and therefore excludes nothing. The discriminating
    assertion is ``fields_dropped``, because the *direction* of the loss is what
    separates "ordinals discarded from an auction, expected" from "every price
    discarded from a draft we think is a snake, which has no prices to carry".
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    _draft(session, league, teams)  # snake, per the league

    priced = [
        FantraxDraftPick(
            team_id="t1",
            round_number=None,
            pick_number=None,
            overall_pick=None,
            player_id="p-jokic",
            player_name=JOKIC,
            auction_amount=41.10,
        ),
        FantraxDraftPick(
            team_id="t2",
            round_number=None,
            pick_number=None,
            overall_pick=None,
            player_id="p-edwards",
            player_name=EDWARDS,
            auction_amount=22.00,
        ),
    ]
    official = recognise_official_draft_picks(
        priced,
        artifact_key="sha256:test",
        received_at=NOW,
        context=_context(),  # snake
    )

    # Reachable: instants exist, every price is gone, nothing was refused.
    assert len(official.instants) == 2
    assert official.unrecognised == ()
    assert [instant.amount for instant in official.instants] == [None, None]
    assert official.coerced_to_kind == 2
    # The discriminating fact, and the one a screen can act on.
    assert official.fields_dropped == ("amount",)

    # The same content on the bridge path *is* refused — which is what made the
    # deleted claim true there and only there.
    bridge = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [
                {"teamId": "t1", "playerId": "p-jokic", "playerName": JOKIC, "winningBid": 41.10},
                {
                    "teamId": "t2",
                    "playerId": "p-edwards",
                    "playerName": EDWARDS,
                    "winningBid": 22.00,
                },
            ]
        ),
        dedupe_key="priced-under-snake",
        received_at=NOW,
        captured_at=None,
        context=_context(),  # snake
    )
    assert bridge.instants == ()
    assert [shape.reason for shape in bridge.unrecognised] == ["record_missing_draft_coordinate"]

    # Positive control: a healthy snake on the official path drops nothing, so
    # ``fields_dropped`` is not "always populated". ``parse_draft_picks`` reads
    # ``auction_amount`` only from amount/bid/salary, so a real snake has none.
    healthy = recognise_official_draft_picks(
        [
            FantraxDraftPick(
                team_id="t1",
                round_number=1,
                pick_number=1,
                overall_pick=1,
                player_id="p-jokic",
                player_name=JOKIC,
                auction_amount=None,
            )
        ],
        artifact_key="sha256:test",
        received_at=NOW,
        context=_context(),
    )
    assert healthy.fields_dropped == ()
    assert healthy.coerced_to_kind == 0

    # Second control, the benign direction: a correctly-recorded auction drops
    # ordinals. Same flag, opposite meaning — which is the whole argument for
    # publishing the names rather than the count.
    auction = recognise_official_draft_picks(
        [
            FantraxDraftPick(
                team_id="t1",
                round_number=1,
                pick_number=1,
                overall_pick=1,
                player_id="p-jokic",
                player_name=JOKIC,
                auction_amount=41.10,
            )
        ],
        artifact_key="sha256:test",
        received_at=NOW,
        context=_context(draft_type=DraftType.AUCTION),
    )
    assert auction.fields_dropped == ("overall_pick", "pick_in_round", "round_number")
    assert auction.coerced_to_kind == 1


def test_a_field_dropped_from_all_of_them_is_reported_apart_from_one_stray(
    session: Session,
) -> None:
    """Excludes: "one record was odd" and "all of them were" reading identically.

    ``coerced_to_kind`` is a count, and a count of 1 among 3 and a count of 3
    among 3 are different facts about a feed. ``every_instant_coerced``
    separates them. A reading in which the bare count is true while that
    distinction is lost: any non-zero value at all, which is why the count is
    not the flag and the rate is.

    **What this deliberately does not claim.** An earlier version of this test
    asserted the flag was the signature of *our own format snapshot being
    wrong* — an auction recorded as snake, every price stripped, the board
    quietly priceless. An independent review falsified that in both directions
    and the third case below pins the falsification, so the causal claim cannot
    be reintroduced without a red test.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)  # snake

    _capture(
        session,
        records=[
            {"teamId": "t1", "playerName": JOKIC, "overallPick": 1, "winningBid": 61},
            {"teamId": "t2", "playerName": EDWARDS, "overallPick": 2, "winningBid": 44},
        ],
        dedupe_key="all-priced",
    )
    total = feed_service.ingest(session, draft).sources[0]
    assert total.instants_recognised == 2
    assert total.coerced_to_kind == 2
    assert total.every_instant_coerced is True
    # The names survive the service layer, not just the recogniser — this is the
    # only field that says which way the loss went, so it has to reach the
    # outcome a screen reads.
    assert total.fields_dropped == ("amount",)

    # The benign case: one stray field among several clean records. Same
    # counter, non-zero, and deliberately *not* flagged.
    league2 = _league(session, fantrax_league_id="league-two")
    teams2 = _teams(session, league2, ["t1", "t2"])
    draft2 = _draft(session, league2, teams2)
    _capture(
        session,
        records=[
            {"teamId": "t1", "playerName": JOKIC, "overallPick": 1, "salary": 3},
            {"teamId": "t2", "playerName": EDWARDS, "overallPick": 2},
            {"teamId": "t1", "playerName": HALIBURTON, "overallPick": 3},
        ],
        dedupe_key="one-stray",
        league_id="league-two",
    )
    sporadic = feed_service.ingest(session, draft2).sources[0]
    assert sporadic.instants_recognised == 3
    assert sporadic.coerced_to_kind == 1
    assert sporadic.every_instant_coerced is False
    assert sporadic.fields_dropped == ("amount",)

    # The falsification, pinned. A *correctly* recorded auction whose records
    # carry ordinals alongside the price — which is what the official adapter
    # produces as a matter of course — is totally coerced and entirely healthy.
    # Nothing is lost: the amount, which is what SALE is defined by, survives.
    # So the flag cannot mean "the board may be lying".
    league3 = _league(
        session,
        fantrax_league_id="league-three",
        draft_type=DraftType.AUCTION,
        budget=Decimal("200.00"),
    )
    teams3 = _teams(session, league3, ["t1", "t2"])
    draft3 = _draft(session, league3, teams3)
    _capture(
        session,
        records=[
            {"teamId": "t1", "playerName": JOKIC, "overallPick": 1, "winningBid": 61},
            {"teamId": "t2", "playerName": EDWARDS, "overallPick": 2, "winningBid": 44},
        ],
        dedupe_key="healthy-auction",
        league_id="league-three",
    )
    healthy_auction = feed_service.ingest(session, draft3).sources[0]
    assert healthy_auction.instants_recognised == 2
    assert healthy_auction.every_instant_coerced is True
    # Same flag as the first case, opposite meaning, and only this tells them
    # apart: there the amount was discarded, here the ordinals were.
    assert healthy_auction.fields_dropped == ("overall_pick",)
    stored = feed_service.load_observations(session, draft3)
    assert [row.amount for row in stored] == [Decimal("61.00"), Decimal("44.00")]


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


def test_a_snake_pick_carrying_a_price_is_stored_without_the_price(session: Session) -> None:
    """Excludes: one impossible field aborting the flush and losing the run.

    ``draft_feed_observations`` carries a CHECK tying ``kind`` to the fields it
    permits: a ``selection`` may not carry ``amount``, a ``sale`` may not carry
    round/pick coordinates. ``salary`` is one of our own ``amount`` aliases, so
    a snake-league payload that happens to carry a contract figure produced
    ``kind=selection`` *with* an amount — a CHECK violation, raised on the
    single flush that covered the whole artifact, so the endpoint returned 500
    and stored **zero** observations from either source. The recogniser now
    conforms each record to the kind the draft's own snapshotted format
    dictates, and counts the loss rather than hiding it.

    A reading in which "the row was stored" is true while the defect is present
    would need the CHECK to be absent, so the CHECK itself is asserted
    separately by ``test_the_kind_split_is_a_database_guarantee``.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[{"teamId": "t1", "playerName": JOKIC, "overallPick": 1, "salary": 55.5}],
        dedupe_key="capture-one",
    )

    outcome = feed_service.ingest(session, draft)

    row = feed_service.load_observations(session, draft)[0]
    assert row.kind is InstantKind.SELECTION
    assert row.amount is None
    assert row.overall_pick == 1
    bridge = next(
        source for source in outcome.sources if source.transport is SourceTransport.BRIDGE_CAPTURE
    )
    assert (bridge.observations_written, bridge.observations_rejected) == (1, 0)
    # The loss is published rather than swallowed: a non-zero count here says
    # the source is sending a shape we only partly understand.
    assert bridge.coerced_to_kind == 1


def test_an_auction_sale_carrying_ordinals_is_stored_without_them(session: Session) -> None:
    """Excludes: the official source's ordinary shape killing every ingest.

    ``parse_draft_picks`` populates round, pick and overall *and* the auction
    amount from the same row unconditionally. In an auction league that is
    ``kind=sale`` carrying draft coordinates — the other half of the CHECK — so
    the corroborating source violated it not as an edge case but as a matter of
    course, on its first successful call of the season.
    """
    league = _league(session, draft_type=DraftType.AUCTION, budget=Decimal("200.00"))
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)

    result = recognise_official_draft_picks(
        [
            FantraxDraftPick(
                team_id="t1",
                round_number=1,
                pick_number=1,
                overall_pick=1,
                player_id="p-jokic",
                player_name=JOKIC,
                auction_amount=41.10,
            )
        ],
        artifact_key="sha256:test",
        received_at=NOW,
        context=_context(draft_type=DraftType.AUCTION),
    )

    assert result.coerced_to_kind == 1
    instant = result.instants[0]
    assert instant.kind is InstantKind.SALE
    assert instant.amount == Decimal("41.10")
    assert (instant.overall_pick, instant.round_number, instant.pick_in_round) == (
        None,
        None,
        None,
    )
    # And it survives the CHECK, which is the part that was failing.
    written, already, rejected, unreadable = feed_service._store(
        session,
        draft,
        result,
        participants={"t1": draft.participants[0].id},
        existing=set(),
    )
    assert (written, already, rejected, unreadable) == (1, 0, 0, 0)


def test_the_kind_split_is_a_database_guarantee(session: Session) -> None:
    """The positive control for the two tests above.

    They assert that conformed rows *store*. If the CHECK did not exist, both
    would pass with the recogniser's coercion removed, because there would be
    nothing left to violate. This asserts the constraint is real, so the two
    above are testing a conformance that matters.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    session.add(
        DraftFeedObservation(
            draft_id=draft.id,
            transport=DraftFeedTransport.BRIDGE_CAPTURE,
            artifact_key="a",
            locator="l",
            recogniser="test",
            observed_at=NOW,
            kind=InstantKind.SELECTION,
            team_external_id="t1",
            player_label=JOKIC,
            amount=Decimal("41.10"),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_one_unstorable_row_does_not_cost_the_rest_of_the_run(session: Session) -> None:
    """Excludes: a single bad record returning 500 and storing nothing.

    The two shapes above are conformed now, but the *class* of failure is the
    point and it will recur the next time Fantrax sends something unforeseen.
    One savepoint per row means a record the database refuses is counted and
    skipped while every other observation of the run still lands. Mid-draft the
    difference is a board missing one pick versus a board showing none.

    The refusal is forced directly rather than through a payload, because every
    payload shape we currently know how to produce is conformed — which is the
    fix working, and would leave this untested if it were the only route in.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)

    good = _instant(
        transport=SourceTransport.BRIDGE_CAPTURE,
        artifact_key="artifact-a",
        player_label=JOKIC,
        locator="a[0]",
    )
    bad = ObservedInstant(
        kind=InstantKind.SELECTION,
        provenance=InstantProvenance(
            transport=SourceTransport.BRIDGE_CAPTURE,
            artifact_key="artifact-a",
            recogniser="test",
            received_at=NOW,
            locator="a[1]",
        ),
        team_external_id="t1",
        player_label=EDWARDS,
        amount=Decimal("41.10"),
    )
    also_good = _instant(
        transport=SourceTransport.BRIDGE_CAPTURE,
        artifact_key="artifact-a",
        player_label=HALIBURTON,
        locator="a[2]",
    )

    written, already, rejected, _unreadable = feed_service._store(
        session,
        draft,
        RecognitionResult(instants=(good, bad, also_good)),
        participants={"t1": draft.participants[0].id},
        existing=set(),
    )

    assert (written, already, rejected) == (2, 0, 1)
    stored = sorted(
        row.player_label or "" for row in feed_service.load_observations(session, draft)
    )
    assert stored == sorted([JOKIC, HALIBURTON])


def test_a_draft_whose_seats_are_not_linked_still_refuses_rpc_identity(
    session: Session,
) -> None:
    """The board may run without identity while RPC attribution still refuses.

    Most mocks have no linked seats. Board source coordinates need no participant
    anchor, but an RPC team id does, so an empty identity set remains a named
    recogniser refusal rather than a permissive default.
    """
    league = _league(session)
    teams = _teams(session, league, [None, None])
    draft = _draft(session, league, teams)

    outcome = feed_service.ingest(session, draft)

    assert outcome.context_unavailable is None
    assert len(outcome.sources) == 2
    assert feed_service.load_observations(session, draft) == []

    status = feed_service.feed_status(session, draft, now=NOW)
    assert status.context_unavailable is None
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
    _capture(
        session,
        records=[{"teamId": "t1", "playerName": JOKIC, "overallPick": 1}],
        dedupe_key="capture-one",
    )

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


def test_a_pick_only_one_source_saw_is_listed_even_without_a_name(
    client: TestClient, session: Session
) -> None:
    """Excludes: a one-sided reading rendering as "nothing to report".

    ``only_bridge`` and ``only_official`` exist to make one-sided readings
    visible — a pick one source has and the other does not is the single most
    useful thing a reconciliation can surface mid-draft. The response built
    those lists with ``if instant.player_label``, which silently dropped every
    instant identified by ``playerId`` alone. That is a supported state:
    ``matching_key`` *prefers* the external id, and a record carrying
    ``playerId`` with no player-specific name key is accepted. So the report
    could hold a one-sided pick while the document rendered ``[]``, and the
    screen would say the two sources agreed completely.

    A reading in which the old flag (``only_bridge == []``) was true while the
    defect was present is exactly that: one-sided, id-only. The list now names
    the row by whatever it has, never by dropping it.
    """
    league = _league(session)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[{"overallPick": 1, "teamId": "t1", "playerId": "p-jokic"}],
        dedupe_key="capture-one",
    )
    session.commit()

    client.post(f"/api/v1/drafts/{draft.id}/feed/ingest", json={"apply": False})
    body = client.get(f"/api/v1/drafts/{draft.id}/feed").json()

    assert body["observation_count"] == 1
    reconciliation = body["reconciliation"]
    assert reconciliation["only_bridge"] == ["player id p-jokic"]
    assert reconciliation["only_official"] == []


def test_the_feed_endpoints_refuse_an_unknown_draft(client: TestClient) -> None:
    """A stable error contract, asserted on the body and not only the code."""
    source_board = client.get("/api/v1/drafts/98765/source-board")
    assert source_board.status_code == 404
    assert source_board.json()["error"] == "draft_not_found"

    missing = client.get("/api/v1/drafts/98765/feed")
    assert missing.status_code == 404
    assert missing.json()["error"] == "draft_not_found"

    refused = client.post("/api/v1/drafts/98765/feed/ingest", json={})
    assert refused.status_code == 404
    assert refused.json()["error"] == "draft_not_found"


# --------------------------------------------------------------------------
# 6. adapter gate: drift against the pinned client
# --------------------------------------------------------------------------


@pytest.mark.adapter_contract
def test_the_recorded_getdraftpicks_payload_runs_the_whole_official_chain() -> None:
    """The Adapter gate's recorded-fixture half, discharged on the official path.

    A real captured response now exists — league ``b2gyornvms4606iv``,
    2026-08-28, ``{"currentDraftPicks":[]}`` under HTTP 200 — so the recogniser
    can finally be pointed at recorded bytes rather than at a hand-built
    envelope. This runs the whole chain: fixture file -> ``parse_draft_picks``
    -> :func:`recognise_official_draft_picks`.

    **It is a weak test and saying so is the point.** The payload is empty, so
    the only thing it can prove is that the chain executes end to end on real
    bytes and reports nothing. It cannot exercise a single per-record field
    name, because no populated row has ever been observed on this path. The
    companion alarm below is what stops that gap being forgotten.
    """
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "fantrax_getdraftpicks_completed_snake_empty.json"
    )
    payload = json.loads(fixture.read_text(encoding="utf-8"))

    picks = parse_draft_picks(payload)
    assert picks == []

    result = recognise_official_draft_picks(
        picks,
        artifact_key="sha256:b5811c858f69d6f11a9f6e0d5a878d9622edd21fe1d6f202a9d2bf5cfb915fca",
        received_at=NOW,
        context=_context(),
    )

    assert result.rejected is None, (
        "an empty official payload is silence, not a refusal; the feed is "
        "built to report it as a silent source"
    )
    assert result.instants == ()
    assert result.unrecognised == ()


@pytest.mark.adapter_contract
def test_no_populated_fantrax_draft_payload_exists_yet() -> None:
    """The narrowed claim, stated so it can still go red.

    **What this test used to say, and why it had to change.** It asserted that
    *no* draft payload had ever been recorded, and it fired on 2026-08-28 when
    one was: a real ``getDraftPicks`` response, with a genuine ``captured_at``
    from an actual read. Its own message said to point a recogniser at the
    fixture and delete it, and the first half of that is done immediately
    above.

    **It was not deleted, because only half the claim expired.** A real
    response has been observed. A real response *containing a pick* has not —
    the endpoint returned an empty list for a league whose 216-pick draft was
    already complete. Every per-record field name in ``parse_draft_picks``
    (``teamId``, ``playerId``, ``round``, ``overallPick``, ``amount``) is still
    a guess, and deleting this test would have retired the alarm at exactly the
    moment its remaining half became the interesting one. Withdrawing a claim
    that has become *narrower* is not the same as withdrawing one that has
    become false.

    Still keyed on the manifest, for the original reason — an entry is what
    carries ``source`` and ``endpoint``. But it now reads the recorded bytes
    rather than trusting the entry, because a fixture's own manifest row is not
    evidence about the fixture's contents.
    """
    fixtures_dir = Path(__file__).resolve().parent / "fixtures"
    manifest = json.loads((fixtures_dir / "manifest.json").read_text(encoding="utf-8"))

    draft_entries = sorted(
        name
        for name, entry in manifest.items()
        if "draft" in str(entry.get("endpoint", "")).lower()
        or "draft" in str(entry.get("source", "")).lower()
    )
    assert draft_entries == ["fantrax_getdraftpicks_completed_snake_empty.json"], (
        f"{draft_entries} is not the set of recorded draft payloads this test "
        "knows about. A new one must be read by hand before this assertion is "
        "widened to admit it."
    )

    for name in draft_entries:
        payload = json.loads((fixtures_dir / name).read_text(encoding="utf-8"))
        picks = parse_draft_picks(payload)
        assert picks == [], (
            f"{name} now contains {len(picks)} pick(s). **This is the outcome "
            "the project has been waiting for.** Read the rows by hand, confirm "
            "whether they are selections that happened or tradeable future pick "
            "assets, replace the per-record field-name guesses in "
            "hoops_gm.ingest.fantrax_official.parsers with observed names, and "
            "delete this test - its remaining claim has now expired too. "
            f"First pick: {picks[0]!r}"
        )


@pytest.mark.adapter_contract
def test_a_refused_player_identity_is_recorded_rather_than_dropped() -> None:
    """Contract: what the recogniser does with a record it cannot identify.

    Adapter-marked because it pins a decision about an *external* payload
    shape — specifically, that a record supplying ``playerId`` in a form this
    reader refuses is neither admitted as a pick nor discarded. It runs
    offline against a constructed envelope, which is all that is available
    (see :func:`test_no_recorded_fantrax_draft_payload_exists_yet`), and it
    asserts the two properties a real payload would have to preserve:

    * the refused record produces an instant, so the loss reaches storage and
      therefore ``GET``, rather than only the ``POST`` response's counters;
    * that instant names nobody, so it cannot be matched to a player, and it
      is not counted as a reading — ``recognised_count`` stays at the number
      of records this reader actually understood.

    The control is the other half: the healthy record beside it is untouched
    and keeps its own locator. A fix that refused the whole list on one bad
    row would pass the first assertion and fail this.
    """
    result = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [
                {
                    "teamId": "t1",
                    "playerId": "p-jokic",
                    "playerName": JOKIC,
                    "overallPick": 1,
                },
                {
                    "teamId": "t2",
                    "playerId": ["not", "a", "string"],
                    "playerName": EDWARDS,
                    "overallPick": 2,
                },
            ]
        ),
        dedupe_key="adapter-contract",
        received_at=NOW,
        captured_at=NOW,
        context=_context(),
    )

    assert result.rejected is None
    assert result.recognised_count == 1
    assert [instant.skipped_reason for instant in result.instants] == [
        None,
        "player_external_id_unreadable",
    ]

    refused = result.instants[1]
    assert (refused.player_label, refused.player_external_id) == (None, None)
    assert refused.team_external_id == "t2"
    assert matching_key(refused) is None

    healthy = result.instants[0]
    assert healthy.player_label == JOKIC
    assert healthy.provenance.locator.endswith("[0]")
    assert refused.provenance.locator.endswith("[1]")

    assert [(shape.reason, shape.occurrences) for shape in result.unrecognised] == [
        ("player_external_id_unreadable", 1)
    ]


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


def test_an_error_alongside_a_well_formed_batch_is_still_an_error() -> None:
    """Excludes: a logged-out reply being read as data because it also parsed.

    The ``pageError`` check started inside the branch taken only when
    ``responses`` was *not* a list, so a reply carrying an error **and** a
    well-formed batch had its error ignored entirely — we would read whatever
    the list happened to hold and report nothing wrong. ``fantraxapi``'s own
    ``_request`` checks ``"pageError" in response_json`` unconditionally, so the
    pinned client treats that reply as an error and we did not.

    A reading in which the old flag was true while the defect was present is
    precisely this payload: ``test_a_logged_out_reply_is_named_rather_than_
    called_a_shape_change`` passes throughout, because its body has no
    ``responses`` key at all. Being logged out is the one rejection the owner
    can act on in thirty seconds; reading a stale or partial list instead is a
    board that looks fine and is not.
    """
    result = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json={
            "pageError": {"code": "WARNING_NOT_LOGGED_IN", "title": "Not Logged In"},
            "responses": [{"data": {"draftPicks": [{"teamId": "t1", "playerName": JOKIC}]}}],
        },
        dedupe_key="k",
        received_at=NOW,
        captured_at=None,
        context=_context(),
    )

    assert result.rejected == "page_error:WARNING_NOT_LOGGED_IN"
    assert result.instants == ()


def test_the_recogniser_reads_every_response_in_the_batch() -> None:
    """Excludes: reading ``responses[0]`` and missing the draft block.

    ``msgs`` is an array and the reply is positionally aligned with it, so the
    draft data is not reliably first. A recogniser that indexed ``[0]`` would
    work in every hand-made test and fail against a real batched call.
    """
    body = {
        "responses": [
            {"data": {"leagueInfo": {"name": "not picks"}}},
            {
                "data": {
                    "draftPicks": [{"teamId": "t1", "playerName": HALIBURTON, "overallPick": 3}]
                }
            },
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


def test_the_official_coercers_do_not_survive_the_parser_that_feeds_them() -> None:
    """Excludes: believing round 7 closed the read-a-field asymmetry.

    **This test documents a defect that is not fixed, and is deliberately
    written to fail when it is.** The fix belongs in
    ``hoops_gm.ingest.fantrax_official.parsers``, which this unit does not own.

    Round 7 routed every field in ``recognise_official_draft_picks`` through the
    same coercers as the bridge path. That is real, and it is bounded: the
    coercers see values that ``parse_draft_picks`` has *already* converted with
    a bare ``int()``/``float()`` and selected with a truthy ``or`` chain. By the
    time they run, a fractional ordinal is an exact ``int`` and an invented
    amount is an ordinary ``float`` — in range, correctly typed, and wrong.

    So the asymmetry is closed at the typed-dataclass layer and open across the
    raw source, and the discriminator is that the *bridge* reader, given the
    identical raw record, refuses it. Each case below asserts that difference,
    which is why a reader cannot dismiss this as the two paths being allowed to
    differ: they differ **on the same bytes**.

    When the parser is fixed, this test fails, and it should — the assertion to
    change is the ``official`` side, and the bridge side is already right.
    """
    raw_cases: list[tuple[str, dict[str, object], DraftType, object]] = [
        # A fractional ordinal truncates to a position the payload never claimed,
        # colliding with whoever really holds that pick.
        ("fractional ordinal", {"overallPick": 1.9}, DraftType.SNAKE, 1),
        # Python's literal grammar, applied to a JSON string.
        ("python-grammar ordinal", {"overallPick": "1_0"}, DraftType.SNAKE, 10),
        # ``0`` is falsy, so a real zero is discarded for a sibling key.
        ("zero ordinal falls through", {"overallPick": 0, "overall": 3}, DraftType.SNAKE, 3),
    ]

    for label, extra, draft_type, expected_ordinal in raw_cases:
        record: dict[str, object] = {
            "teamId": "t1",
            "playerId": "p1",
            "playerName": JOKIC,
            **extra,
        }
        context = _context(draft_type=draft_type)

        official = recognise_official_draft_picks(
            parse_draft_picks({"draftPicks": [record]}),
            artifact_key="sha256:seam",
            received_at=NOW,
            context=context,
        )
        bridge = recognise_bridge_payload(
            url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
            body_json={"responses": [{"data": {"draftPicks": [record]}}]},
            dedupe_key="seam",
            received_at=NOW,
            captured_at=None,
            context=context,
        )

        assert [i.overall_pick for i in official.instants] == [expected_ordinal], label
        assert official.unrecognised == (), label
        assert bridge.instants == (), label
        assert [shape.reason for shape in bridge.unrecognised] == [
            "record_missing_draft_coordinate"
        ], label


def test_an_auction_amount_the_payload_set_to_zero_is_not_replaced_by_a_sibling_bid() -> None:
    """Excludes: believing a stored price came from the field that names it.

    The same generator as the test above, on the field that carries money. A
    payload saying ``amount: 0`` — a keeper at no cost, an unsold nomination —
    is falsy, so ``parse_draft_picks`` moves on and reports the ``bid``
    instead. The board then shows a player sold for ten dollars that the source
    said cost nothing, with every channel reporting a clean read.

    Fixing this is upstream; asserting it here is what makes it visible.
    """
    record: dict[str, object] = {
        "teamId": "t1",
        "playerId": "p1",
        "playerName": JOKIC,
        "amount": 0,
        "bid": 10,
    }
    context = _context(draft_type=DraftType.AUCTION)

    official = recognise_official_draft_picks(
        parse_draft_picks({"draftPicks": [record]}),
        artifact_key="sha256:seam",
        received_at=NOW,
        context=context,
    )

    assert [instant.amount for instant in official.instants] == [Decimal("10.0")]
    assert official.unrecognised == ()


def test_a_malformed_official_container_is_indistinguishable_from_an_empty_draft() -> None:
    """Excludes: reading "no picks" as "the draft has not started".

    On draft night these two mean opposite things and call for opposite
    actions. An empty ``draftPicks`` list means nobody has picked yet and the
    owner should wait; a missing key or a non-list means this reader did not
    understand the response and the owner should look at the feed. Both arrive
    here as zero picks, no rejection, and no unrecognised shape.

    The bridge path has ``_accept_list`` and reports a named refusal for these.
    The official path has no equivalent because ``parse_draft_picks`` returns
    ``[]`` for all of them, and ``[]`` carries no reason. Upstream again, and
    asserted here so it cannot be believed closed.
    """
    shapes: list[tuple[str, object]] = [
        ("genuinely empty", {"draftPicks": []}),
        ("key absent", {"unexpected": []}),
        ("not a list", {"draftPicks": {}}),
        ("row is not an object", {"draftPicks": [None]}),
    ]

    outcomes = set()
    for label, payload in shapes:
        result = recognise_official_draft_picks(
            parse_draft_picks(payload),
            artifact_key="sha256:seam",
            received_at=NOW,
            context=_context(),
        )
        outcomes.add((len(result.instants), result.rejected, result.unrecognised))
        assert result.instants == (), label

    # One outcome for four inputs is the defect: nothing downstream can tell
    # them apart, because nothing upstream kept the difference.
    assert outcomes == {(0, None, ())}


def test_every_bound_is_asserted_where_no_other_cause_can_produce_the_refusal() -> None:
    """Excludes: a guard that is correct, matches its column, and is never called.

    **This test exists because the checks that were supposed to cover these
    bounds were satisfied by the wrong cause.** The enumeration test proves each
    ``MAX_*`` constant equals the column it describes; the per-rule mutations
    prove particular coercions are wired. Neither covers *both*, and the gap was
    recorded as a could-not-verify rather than measured -- wrongly, because it
    was measurable.

    Measuring it meant leaving every constant correct, so the enumeration test
    stays green by construction, and widening only the ``limit=`` actually
    passed at one production call site at a time. Six of nine sites turned the
    behaviour suite red. **Three did not**, and they failed for one reason:

        ``no_seat_anchor`` is produced by *two* independent mechanisms -- the
        bound refusing the text, and the resulting text simply not being a
        configured seat.

    The existing assertion used an over-long team id that was *also* not a
    configured seat, so both mechanisms were live and the outcome was the same
    either way. Widening the bound to ten million kept it green.

    So the rule this test applies, which is the project's review rule turned on
    its own tests: **name the defect the assertion excludes, then name a reading
    in which the assertion holds and the defect is present.** Here that reading
    is "the id was never bounded, and was rejected for being an unknown seat".
    The fix is to remove the alternative cause -- **configure the over-long id
    as a real seat** -- so that anchoring at all can only mean the bound is gone.

    Measured with the two limits widened and the constants left correct:
    the official path anchored, reported nothing, and carried a **65-character
    id into a ``String(64)`` column** -- silently truncated on SQLite and a
    ``DataError`` outside ``IntegrityError`` on Postgres, which is the whole
    ingest rather than the row. That is the ADR-001 divergence class, and no
    test in the suite used a string long enough to expose it.
    """
    long_team = "t" * (MAX_EXTERNAL_ID_CHARS + 1)
    long_label = "N" * (MAX_LABEL_CHARS + 1)

    # The seat is genuinely configured, so "unknown seat" cannot explain a
    # refusal. Only the bound can.
    context = _context(team_ids=frozenset({long_team, "t1"}))

    official = recognise_official_draft_picks(
        [
            FantraxDraftPick(
                team_id=long_team,
                player_id="p-jokic",
                player_name=JOKIC,
                overall_pick=1,
            )
        ],
        artifact_key="sha256:bound",
        received_at=NOW,
        context=context,
    )
    assert official.instants == ()
    assert [shape.reason for shape in official.unrecognised] == ["no_seat_anchor"]

    bridge = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [
                {
                    "teamId": long_team,
                    "playerId": "p-jokic",
                    "playerName": JOKIC,
                    "overallPick": 1,
                }
            ]
        ),
        dedupe_key="bound",
        received_at=NOW,
        captured_at=None,
        context=context,
    )
    assert bridge.instants == ()
    assert [shape.reason for shape in bridge.unrecognised] == ["no_seat_anchor"]

    # The third site: ``_player_identity`` falls back to the label when no
    # external id is present. An over-long label must not become an identity,
    # and the alternative cause here is "the record named nobody at all", so the
    # discriminating record names a player *only* through the over-long label.
    unidentified = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope([{"teamId": "t1", "playerName": long_label, "overallPick": 1}]),
        dedupe_key="bound-label",
        received_at=NOW,
        captured_at=None,
        context=context,
    )
    assert unidentified.instants == ()
    assert "record_names_no_player" in [shape.reason for shape in unidentified.unrecognised]

    # Control: the same three records at exactly the bound are accepted, so the
    # assertions above are refusing on width and not on the shape of the record.
    at_bound_team = "t" * MAX_EXTERNAL_ID_CHARS
    healthy = recognise_bridge_payload(
        url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        body_json=_envelope(
            [
                {
                    "teamId": at_bound_team,
                    "playerName": "N" * MAX_LABEL_CHARS,
                    "overallPick": 1,
                }
            ]
        ),
        dedupe_key="bound-ok",
        received_at=NOW,
        captured_at=None,
        context=_context(team_ids=frozenset({at_bound_team})),
    )
    assert len(healthy.instants) == 1
    assert healthy.unrecognised == ()
    assert healthy.instants[0].team_external_id == at_bound_team


# ---------------------------------------------------------------------------
# Round nine: a second reading is only corroboration if it agrees.
# ---------------------------------------------------------------------------


def _auction_draft(session: Session) -> Draft:
    league = _league(session, draft_type=DraftType.AUCTION, budget=Decimal("200.00"))
    teams = _teams(session, league, ["t1", "t2"])
    return _draft(session, league, teams)


def _official_saying(team_id: str, amount: float | None, *, sha: str = "officialsha") -> Any:
    """An official client naming one player, with no coordinate.

    ``sha`` is a parameter because the ingest path dedupes on the artifact
    key: two readings that returned the same sha would be *one* stored
    observation, and a test that varied the values while holding the sha
    constant would be asserting about a row that was never written. That is
    the "compared a source with itself" defect this project has already
    shipped once, so the knob is explicit rather than defaulted-and-forgotten.
    """

    class _Official:
        def get_draft_picks_with_provenance(
            self, league_id: str, *, max_age: timedelta | None = None
        ) -> tuple[list[FantraxDraftPick], str, datetime]:
            return (
                [
                    FantraxDraftPick(
                        team_id=team_id,
                        player_id=None,
                        player_name=JOKIC,
                        round_number=None,
                        pick_number=None,
                        overall_pick=None,
                        auction_amount=amount,
                    )
                ],
                sha,
                NOW,
            )

    return _Official()


def _bridge_naming(
    session: Session,
    team_id: str,
    amount: float,
    *,
    key: str,
    label: str,
    player_id: object | None = None,
) -> None:
    """One bridge capture naming a player, optionally with the source's id.

    ``player_id`` is typed ``object`` because the interesting inputs are the
    ones a payload can supply and this module cannot read -- an over-long
    string, a list, a bool -- and typing it ``str`` here would make those
    unwritable in the very tests that exist to drive them.
    """
    record: dict[str, Any] = {
        "teamId": team_id,
        "playerName": label,
        "overallPick": 1,
        "amount": amount,
    }
    if player_id is not None:
        record["playerId"] = player_id
    _capture(session, records=[record], dedupe_key=key)


def _official_naming(team_id: str, amount: float, *, player_id: str, label: str) -> Any:
    """An official client naming one player *with* the source's own id.

    Separate from :func:`_official_saying` because that one hardcodes
    ``player_id=None``: a cross-source identity conflict cannot be driven with
    a helper that never supplies an identity, and reusing it would have made
    the test pass by never reaching the code it names.
    """

    class _Official:
        def get_draft_picks_with_provenance(
            self, league_id: str, *, max_age: timedelta | None = None
        ) -> tuple[list[FantraxDraftPick], str, datetime]:
            return (
                [
                    FantraxDraftPick(
                        team_id=team_id,
                        player_id=player_id,
                        player_name=label,
                        round_number=None,
                        pick_number=None,
                        overall_pick=None,
                        auction_amount=amount,
                    )
                ],
                f"officialsha-{player_id}-{label}",
                NOW,
            )

    return _Official()


def _bridge_saying(session: Session, team_id: str, amount: float) -> None:
    _capture(
        session,
        records=[{"teamId": team_id, "playerName": JOKIC, "overallPick": 1, "amount": amount}],
        dedupe_key=f"r9-{team_id}-{amount}",
    )


def test_two_sources_naming_different_buyers_put_nobody_on_the_board(
    session: Session,
) -> None:
    """Excludes: a disagreement being applied as though it were corroboration.

    Reading in which the flag is false and the defect is present: none that I
    can construct. The board is asserted empty for *both* seats, so a fix that
    merely applied the other reading fails this too — the assertion is about
    refusing to choose, not about which one was chosen.
    """
    draft = _auction_draft(session)
    _bridge_saying(session, "t1", 50)
    feed_service.ingest(session, draft, client=_official_saying("t2", 50))

    outcome = feed_service.apply_observations(session, draft)
    assert outcome.applied == ()

    state = draft_service.load_state(session, draft)
    assert [len(seat.holdings) for seat in state.participants] == [0, 0]

    rows = feed_service.load_observations(session, draft)
    assert all(row.blocked_reason is not None for row in rows)
    # The reason names the field, both readings, and which source produced
    # each. A reason of "they disagree" would be true and useless at 7:14pm.
    reason = rows[0].blocked_reason
    assert reason is not None
    assert reason.startswith("sources_disagree:participant_id:")
    assert "bridge_capture" in reason
    assert "official_http" in reason


def test_two_sources_naming_different_prices_put_nobody_on_the_board(
    session: Session,
) -> None:
    """Excludes: a price disagreement being resolved by whichever sorted first.

    The owner's league is an auction, so the price *is* the fact. A pick
    recorded at the wrong price is not a lesser error than one recorded
    against the wrong seat.
    """
    draft = _auction_draft(session)
    _bridge_saying(session, "t1", 50)
    feed_service.ingest(session, draft, client=_official_saying("t1", 10))

    outcome = feed_service.apply_observations(session, draft)
    assert outcome.applied == ()

    state = draft_service.load_state(session, draft)
    assert [len(seat.holdings) for seat in state.participants] == [0, 0]

    reason = feed_service.load_observations(session, draft)[0].blocked_reason
    assert reason is not None
    assert reason.startswith("sources_disagree:amount:")
    assert "50.00" in reason and "10.00" in reason


def test_a_source_silent_on_price_has_not_contradicted_one_that_supplies_it(
    session: Session,
) -> None:
    """Excludes: the refusal being so broad it strands ordinary picks.

    This is the reading in which blocking is *wrong*. The official source
    omits the amount; that is absence, not disagreement, and a check that
    cannot tell them apart would block every pick the two sources describe at
    different levels of detail — which is most of them.
    """
    draft = _auction_draft(session)
    _bridge_saying(session, "t1", 50)
    feed_service.ingest(session, draft, client=_official_saying("t1", None))

    outcome = feed_service.apply_observations(session, draft)
    assert len(outcome.applied) == 1
    assert [reason for _, reason in outcome.skipped] == ["duplicate_within_run"]

    state = draft_service.load_state(session, draft)
    assert [holding.player_label for holding in state.participants[0].holdings] == [JOKIC]
    assert state.participants[0].holdings[0].price == Decimal("50.00")


def test_two_sources_that_agree_still_apply_once_and_corroborate(
    session: Session,
) -> None:
    """Excludes: the disagreement check breaking the corroboration path.

    The regression guard for the fix itself. Running two sources is only worth
    anything if agreement still produces one pick and one witness.
    """
    draft = _auction_draft(session)
    _bridge_saying(session, "t1", 50)
    feed_service.ingest(session, draft, client=_official_saying("t1", 50))

    outcome = feed_service.apply_observations(session, draft)
    assert len(outcome.applied) == 1
    assert [reason for _, reason in outcome.skipped] == ["duplicate_within_run"]

    rows = feed_service.load_observations(session, draft)
    assert all(row.blocked_reason is None for row in rows)
    corroboration = next(row for row in rows if row.skipped_reason == "duplicate_within_run")
    assert corroboration.applied_event_sequence == outcome.applied[0].sequence


def test_a_feed_contradicting_what_the_owner_typed_is_a_disagreement_not_a_duplicate(
    session: Session,
) -> None:
    """Excludes: the log being treated as a name to match rather than a reading.

    Found by running the neighbours of the reported case rather than the
    reported case. The review's finding was two *feed* sources disagreeing;
    this is a feed source disagreeing with the log, and before the fix it was
    filed ``already_in_log`` — which reports the collision and throws away the
    contradiction inside it.

    That matters more than the reported case, not less: the owner typing a
    pick is the fallback he uses when the feed looks wrong, so this is exactly
    the moment he is already suspicious and the tool tells him everything
    agrees.
    """
    draft = _auction_draft(session)
    seat_one = next(seat for seat in draft.participants if seat.team_slot == 1)
    draft_service.record_sale(
        session,
        draft,
        participant_id=seat_one.id,
        amount=Decimal("50.00"),
        player_label=JOKIC,
        note="the owner typed it",
    )

    _bridge_saying(session, "t2", 50)
    feed_service.ingest(session, draft, client=_official_saying("t2", 50))

    outcome = feed_service.apply_observations(session, draft)
    assert outcome.applied == ()
    assert [reason for _, reason in outcome.skipped] == []

    rows = feed_service.load_observations(session, draft)
    assert all(row.blocked_reason is not None for row in rows)
    reason = rows[0].blocked_reason
    assert reason is not None
    assert reason.startswith("sources_disagree:participant_id:")
    assert ":log=" in reason

    # What the owner typed is untouched. The feed does not get to move a pick
    # it disagrees about, and "blocked" must not read as "reverted".
    state = draft_service.load_state(session, draft)
    assert [holding.player_label for holding in state.participants[0].holdings] == [JOKIC]
    assert state.participants[1].holdings == ()


def test_a_blocked_contradiction_is_reported_on_the_polled_status(
    session: Session,
) -> None:
    """Excludes: the refusal being invisible to the screen that must show it.

    A pick that silently fails to appear is the failure this whole unit exists
    to avoid: the owner cannot tell "nobody has bought him yet" from "we
    refused to say". ``blocked`` is on the *polled* status because a live
    board polls; returning it only on the ingest response would show it to the
    userscript and never to him.
    """
    draft = _auction_draft(session)
    _bridge_saying(session, "t1", 50)
    feed_service.ingest(session, draft, client=_official_saying("t2", 50))
    feed_service.apply_observations(session, draft)

    status = feed_service.feed_status(session, draft)
    assert status.pending_count > 0
    assert any(reason.startswith("sources_disagree:") for reason in status.blocked)


def test_a_contradiction_clears_when_the_sources_stop_disagreeing(
    session: Session,
) -> None:
    """Excludes: a blocked pick being burnt permanently.

    ``skipped_reason`` is never cleared by anything in this package, so
    recording the contradiction there would mean the row could never apply
    again even once the disagreement was resolved -- and the row would also
    leave ``pending_count``, so the screen would report nothing outstanding.
    ``blocked_reason`` is recomputed every run, which is the whole reason the
    refusal is written there.
    """
    draft = _auction_draft(session)
    _bridge_saying(session, "t1", 50)
    feed_service.ingest(session, draft, client=_official_saying("t2", 50))
    assert feed_service.apply_observations(session, draft).applied == ()

    # The disagreeing official reading is superseded by one that agrees. A
    # distinct sha is essential: the same sha would dedupe to the same stored
    # observation and this test would pass without a second reading existing.
    feed_service.ingest(session, draft, client=_official_saying("t1", 50, sha="officialsha2"))
    outcome = feed_service.apply_observations(session, draft)

    assert len(outcome.applied) == 1
    state = draft_service.load_state(session, draft)
    assert [holding.player_label for holding in state.participants[0].holdings] == [JOKIC]


def test_the_blocking_facts_are_exactly_what_the_board_is_told() -> None:
    """Excludes: a fact reaching the board that no source ever had to agree on.

    Derived from the call site rather than from a list someone maintained.
    ``_BOARD_FACTS`` says which readings must agree before a pick is applied;
    this reads the *actual arguments* ``apply_observations`` passes to
    ``record_sale``/``record_pick`` and requires every ``row.`` attribute among
    them to be either compared or explicitly declared not-comparable.

    So adding an argument is **red until someone classifies it**, which is the
    only property here that survives me not being the next person to touch it.
    The round-eight guard of this shape caught a real defect on its first run,
    which is the only reason I trust this one.

    Name the defect it excludes, then the reading in which it is false and the
    defect present: the flag is false only if a new ``row.X`` is passed to the
    draft service *and* is classified. Classification is a deliberate act with
    a written reason, so the failure mode left is someone classifying wrongly
    on purpose -- which no check catches and this one does not claim to.
    """
    source = textwrap.dedent(inspect.getsource(feed_service.apply_observations))
    tree = ast.parse(source)

    #: Local bindings that carry payload into the draft service. A rename must
    #: be added here deliberately. The first version of this walk read ``row``
    #: alone; refactoring the two optional fields onto an ``_Admitted`` record
    #: would have left it reading one argument and passing vacuously, so the
    #: base name is now part of what the test checks rather than part of what
    #: it assumes.
    payload_bases = {"row", "admitted"}

    recorded_attrs: set[str] = set()
    seen_bases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in {"record_sale", "record_pick"}:
            continue
        # Arguments only. Walking the whole call would collect the callee
        # (``draft_service.record_sale``) as an attribute access too.
        for passed in [*node.args, *(keyword.value for keyword in node.keywords)]:
            for argument in ast.walk(passed):
                if isinstance(argument, ast.Attribute) and isinstance(argument.value, ast.Name):
                    seen_bases.add(argument.value.id)
                    if argument.value.id in payload_bases:
                        recorded_attrs.add(argument.attr)

    # A positive control on the extractor itself. If this is empty the walk
    # found nothing and every assertion below is vacuously true -- which is
    # exactly the "the experiment did not happen" reading that has been
    # mistaken for a result twice on this branch.
    assert recorded_attrs, "extractor found no payload arguments; the walk is broken, not the code"
    assert "participant_id" in recorded_attrs

    undeclared_bases = seen_bases - payload_bases
    assert not undeclared_bases, (
        f"{sorted(undeclared_bases)} carry attributes into record_sale/record_pick but are not "
        "declared payload bases. Add them to payload_bases, or this test stops reading them."
    )

    compared = {observation_field for observation_field, _ in feed_service._BOARD_FACTS}

    #: Passed to the board but deliberately not required to agree, with the
    #: reason each one is safe. Anything not here and not in ``_BOARD_FACTS``
    #: fails this test.
    declared_not_comparable = {
        # The grouping key itself. Two labels that normalise to one key are
        # *meant* to be the same player -- accents, punctuation, "Jr." -- and
        # refusing on a verbatim difference would block precisely the case
        # normalisation exists to allow.
        "player_label",
        # Provenance. These are *required* to differ: two readings from one
        # transport with one artifact key are one reading. Comparing them
        # would flag every corroboration as a contradiction.
        "transport",
        "artifact_key",
    }

    unclassified = recorded_attrs - compared - declared_not_comparable
    assert not unclassified, (
        f"{sorted(unclassified)} reach the board but are neither compared in _BOARD_FACTS "
        "nor declared not-comparable. Decide which, and write down why."
    )

    # And the converse: a compared field that no longer reaches the board is a
    # bound on nothing, which reads as protection and is not.
    stale = compared - recorded_attrs
    assert not stale, f"{sorted(stale)} are compared but no longer passed to the board"


def test_the_official_source_is_not_wired_into_the_running_app() -> None:
    """Excludes: the parser seam reaching the board without anyone deciding to.

    ``docs/handoff.md`` records that ``parse_draft_picks`` normalises values
    the bridge recogniser refuses -- ``{"amount": 0, "bid": 10}`` becomes a $10
    sale, ``{"overallPick": 1.9}`` becomes pick 1. Three tests in this file pin
    that. The reason it is not a live defect is **not** that the bridge gates
    it: an official observation reaches the board with no bridge capture
    present at all. It is that nothing constructs the official client, so
    ``_draft_pick_source`` returns ``None`` on every request.

    That is a wiring fact, and wiring facts change quietly. This asserts the
    only occurrence of ``fantrax_official_client`` in the tree is the read in
    the route -- so the commit that arms the seam is the commit that turns this
    red, and whoever writes it is told what they have just made reachable.

    Reading in which the flag is false and the defect is present: someone
    constructs a client and attaches it under a *different* attribute name.
    This does not exclude that, and says so rather than implying otherwise.

    Scoped to ``backend/src`` deliberately, and the first run taught me why:
    unscoped it matched its own failure message and this docstring, four hits
    for one wiring fact. Test code that attaches a stub to ``app.state`` is
    also not production wiring, so ``src`` is both the scope that works and
    the scope that is meant.
    """
    repo_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        ["git", "grep", "-n", "fantrax_official_client", "--", "backend/src"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    # ``git grep`` exits 1 for "no matches". Zero matches would mean the read
    # itself is gone and this test is asserting about nothing.
    assert completed.returncode == 0, "no occurrences at all; this guard is measuring nothing"

    occurrences = [line for line in completed.stdout.splitlines() if line.strip()]
    assert len(occurrences) == 1, (
        "fantrax_official_client is now referenced in more than one place:\n"
        + "\n".join(occurrences)
        + "\n\nIf this is the commit that wires the official client into the app, read "
        "test_the_official_coercers_do_not_survive_the_parser_that_feeds_them first: "
        "the official path records values the bridge path refuses, and wiring it makes "
        "those reachable on the board."
    )
    assert "getattr(request.app.state" in occurrences[0]


# ---------------------------------------------------------------------------
# Round ten: the payload carries two identity signals and they must agree.
# ---------------------------------------------------------------------------


def test_one_player_id_relabelled_by_one_source_is_a_correction_not_a_conflict(
    session: Session,
) -> None:
    """Excludes: one player reaching the board twice and being paid for twice.

    This is the *agreeing* case, which is why it matters. The two readings name
    the same seat and the same price, so nothing disagrees, nothing is skipped
    and no channel reports a problem -- and before the identity guard the board
    held the player under both labels and the seat's ``remaining_budget`` read
    ``100.00`` where ``150.00`` was correct. Every bid the owner reasons about
    after that is computed from a bank wrong by the price of a player.

    The guard's first form blocked both readings, which stopped the double
    debit and replaced it with a player the feed could **never** record: the
    stale reading stayed pending and kept contradicting, so republishing the
    correct one changed nothing. The owner has no manual fallback, so that is a
    loss and not merely a visible one.

    A source correcting itself is therefore a correction. The newest reading per
    transport wins, the stale *key* is blocked so it cannot apply as a second
    player, and the reason names what replaced it.

    Reading in which the flag is false and the defect is present: two labels for
    one player arriving with **no** external id. There is no signal to detect
    that with, and this does not claim to.
    """
    draft = _auction_draft(session)
    _bridge_naming(session, "t1", 50, key="r10-a", label="Nikola Jokic", player_id="p123")
    _bridge_naming(session, "t1", 50, key="r10-b", label="The Joker", player_id="p123")
    feed_service.ingest(session, draft, client=None)

    outcome = feed_service.apply_observations(session, draft)
    assert len(outcome.applied) == 1

    state = draft_service.load_state(session, draft)
    assert [len(seat.holdings) for seat in state.participants] == [1, 0]
    # The budget assertion is the point. A fix that deduplicated the display
    # while still debiting twice passes every other check here.
    assert [seat.remaining_budget for seat in state.participants] == [
        Decimal("150.00"),
        Decimal("200.00"),
    ]

    rows = feed_service.load_observations(session, draft)
    reasons = [row.blocked_reason for row in rows]
    assert reasons.count(None) == 1
    stale = next(reason for reason in reasons if reason is not None)
    # Tied to what actually reached the board rather than to a fixed direction.
    # Which capture the fixture happens to order last is not the property under
    # test, and asserting it would let this pass while the wrong reading won.
    live_key = normalize_key(state.participants[0].holdings[0].player_label)
    superseded_key = next(key for key in ("nikola jokic", "the joker") if key != live_key)
    assert stale == f"identity_superseded:p123:{superseded_key}->{live_key}"


def test_two_sources_disagreeing_about_a_player_id_still_block(session: Session) -> None:
    """Excludes: the supersession above swallowing a genuine cross-source conflict.

    Newest-per-transport is a *within-source* collapse. Applied across sources
    it would become the "prefer the newer source" preference this package
    refuses to make everywhere else -- and it would do so silently, since the
    loser leaves no row.

    Reading in which the flag is false and the defect is present: none for two
    transports. It says nothing about three, where the newest two agreeing
    against an older third is a case no fixture exists for.
    """
    draft = _auction_draft(session)
    _bridge_naming(session, "t1", 50, key="r11-x", label="The Joker", player_id="p9")
    feed_service.ingest(
        session, draft, client=_official_naming("t1", 50, player_id="p9", label="Nikola Jokic")
    )

    outcome = feed_service.apply_observations(session, draft)
    assert outcome.applied == ()

    state = draft_service.load_state(session, draft)
    assert [len(seat.holdings) for seat in state.participants] == [0, 0]

    rows = feed_service.load_observations(session, draft)
    assert all(
        (row.blocked_reason or "").startswith("identity_conflict:one_player_id_many_labels:p9:")
        for row in rows
    )


def test_a_supplied_but_unreadable_player_id_refuses_the_capture(session: Session) -> None:
    """Excludes: *supplied but refused* being stored as *never supplied*.

    ``_player_identity`` fell back to the label through :func:`_as_text`, whose
    own docstring names a falling-back caller as the unsafe one. Driven before
    the fix: two captures carrying the same 5,000-character ``playerId`` under
    two labels both applied, the seat held one player twice and
    ``remaining_budget`` read ``100.00`` where ``150.00`` was correct, with
    nothing blocked, nothing skipped, and ``fields_dropped`` naming only the
    ordinal. The identity guard could not fire because the evidence it needed
    had already been erased.

    Refusing the capture loses a scan. That is the trade this module makes
    everywhere: a blank board you can diagnose beats a populated one quietly
    lying, and the next capture is seconds away.

    Reading in which the flag is false and the defect is present: an id that is
    readable but *wrong* -- a source publishing one player's id against another
    player's name. Nothing here detects that.
    """
    draft = _auction_draft(session)
    _bridge_naming(session, "t1", 50, key="r11-a", label="Nikola Jokic", player_id="x" * 5000)
    _bridge_naming(session, "t1", 50, key="r11-b", label="The Joker", player_id="x" * 5000)
    result = feed_service.ingest(session, draft, client=None)

    bridge = next(
        source for source in result.sources if source.transport is DraftFeedTransport.BRIDGE_CAPTURE
    )
    assert bridge.instants_recognised == 0
    assert bridge.observations_written == 0
    # The reason names the field. "unrecognised" alone would be true and
    # useless with a clock running.
    assert any(shape.reason == "player_external_id_unreadable" for shape in bridge.unrecognised)

    outcome = feed_service.apply_observations(session, draft)
    assert outcome.applied == ()
    state = draft_service.load_state(session, draft)
    assert [seat.remaining_budget for seat in state.participants] == [
        Decimal("200.00"),
        Decimal("200.00"),
    ]


def test_a_readable_numeric_player_id_is_not_treated_as_unreadable(session: Session) -> None:
    """Control: the refusal above must not fire on an ordinary id.

    Without this, a fix that refused every capture carrying a ``playerId``
    would pass the test above while feeding nothing to the board at all -- and
    a board that never fills looks exactly like a draft that has not started.
    ``123`` is the case that matters, because a JSON number is what a real feed
    is most likely to send.
    """
    draft = _auction_draft(session)
    _bridge_naming(session, "t1", 50, key="r11-c", label="Nikola Jokic", player_id=123)
    feed_service.ingest(session, draft, client=None)

    outcome = feed_service.apply_observations(session, draft)
    assert len(outcome.applied) == 1
    rows = feed_service.load_observations(session, draft)
    assert [row.player_external_id for row in rows] == ["123"]


def test_two_player_ids_under_one_label_are_refused_not_deduplicated(
    session: Session,
) -> None:
    """Excludes: two different players collapsing into one, losing a pick.

    ``normalize_key`` erases digits and generational suffixes, so
    ``"Gary Payton II"`` keys to ``"gary payton"``. Before this fix the first
    reading applied and the second was filed ``duplicate_within_run`` -- **a
    pick that happened, reported as nothing**, which is the same shape as a
    truncated locator collapsing two rows into one.

    Reading in which the flag is false and the defect is present: two distinct
    players normalising together where the payload supplies **no** ids. Nothing
    in the payload distinguishes them then, and this refuses on the signal that
    exists rather than pretending to a better one.
    """
    draft = _auction_draft(session)
    _bridge_naming(session, "t1", 50, key="r10-c", label="Gary Payton", player_id="p1")
    _bridge_naming(session, "t2", 10, key="r10-d", label="Gary Payton II", player_id="p2")
    feed_service.ingest(session, draft, client=None)

    outcome = feed_service.apply_observations(session, draft)
    assert outcome.applied == ()

    state = draft_service.load_state(session, draft)
    assert [len(seat.holdings) for seat in state.participants] == [0, 0]

    rows = feed_service.load_observations(session, draft)
    reason = rows[0].blocked_reason
    assert reason is not None
    assert reason.startswith("identity_conflict:one_label_many_player_ids:gary payton:")
    assert "p1" in reason and "p2" in reason


def test_one_id_under_one_label_still_applies_once(session: Session) -> None:
    """Control: the refusal above must not fire on the ordinary case.

    Without this, a fix that blocked *any* key carrying an external id would
    pass both tests above while feeding nothing to the board at all -- which is
    the failure the owner cannot see, because a board that never fills looks
    identical to a draft that has not started.
    """
    draft = _auction_draft(session)
    _bridge_naming(session, "t1", 50, key="r10-e", label="Nikola Jokic", player_id="p123")
    _bridge_naming(session, "t1", 50, key="r10-f", label="Nikola Jokic", player_id="p123")
    feed_service.ingest(session, draft, client=None)

    outcome = feed_service.apply_observations(session, draft)
    assert len(outcome.applied) == 1

    state = draft_service.load_state(session, draft)
    assert [len(seat.holdings) for seat in state.participants] == [1, 0]
    assert state.participants[0].remaining_budget == Decimal("150.00")


def test_an_absent_player_id_cannot_conflict(session: Session) -> None:
    """Control: absence is not disagreement, applied to identity.

    A row carrying no external id must not conflict with one that does, for the
    same reason a source silent on price has not contradicted one that supplies
    it. Without this the mixed case -- bridge records carrying ``playerId``,
    official records not -- would block every player on the board.
    """
    draft = _auction_draft(session)
    _bridge_naming(session, "t1", 50, key="r10-g", label="Nikola Jokic", player_id="p123")
    _bridge_naming(session, "t1", 50, key="r10-h", label="Nikola Jokic")
    feed_service.ingest(session, draft, client=None)

    outcome = feed_service.apply_observations(session, draft)
    assert len(outcome.applied) == 1

    rows = feed_service.load_observations(session, draft)
    assert [row.blocked_reason for row in rows] == [None, None]


# ---------------------------------------------------------------------------
# Round twelve: the pending set is not the board, and one bad row is not a bad
# board.
# ---------------------------------------------------------------------------


def test_a_correction_arriving_after_the_pick_applied_does_not_draft_him_twice(
    session: Session,
) -> None:
    """Excludes: one player, bought once, appearing twice and debited twice.

    Round ten stopped this *within* a run and round eleven taught the same pass
    to read a relabelling as a correction. Both reason only over rows still
    pending. On draft night ingest-and-apply runs between picks, so the reading
    a later capture corrects has already applied -- and then neither check sees
    anything to disagree with.

    Driven before the fix: ``p123`` applied as "The Joker" at $50, republished
    as "Nikola Jokic", both applied at sequences 1 and 2, and the seat's
    ``remaining_budget`` read ``100.00`` where ``150.00`` was correct -- with
    ``pending_count=0``, ``blocked=()`` and ``skipped=()``. Every channel the
    owner can see reported a clean board while it held one player twice.

    **Reading in which this passes and the defect is present:** none that I can
    construct for the budget assertion. ``remaining_budget`` is derived from the
    log by :mod:`hoops_gm.draft.state`, not from anything this module writes, so
    150.00 cannot be produced by a second sale having been recorded. The
    ``blocked_reason`` assertion is the weaker half and is here to pin the
    *reason*, not the outcome.
    """
    draft = _auction_draft(session)

    _bridge_naming(session, "t1", 50.0, key="r12-a1", label="The Joker", player_id="p123")
    feed_service.ingest(session, draft, client=None)
    assert len(feed_service.apply_observations(session, draft).applied) == 1

    _bridge_naming(session, "t1", 50.0, key="r12-a2", label=JOKIC, player_id="p123")
    feed_service.ingest(session, draft, client=None)
    second = feed_service.apply_observations(session, draft)

    assert second.applied == ()
    state = draft_service.load_state(session, draft)
    seat = state.participants[0]
    assert [holding.player_label for holding in seat.holdings] == ["The Joker"]
    assert seat.remaining_budget == Decimal("150.00")

    rows = feed_service.load_observations(session, draft)
    assert rows[1].applied_event_sequence is None
    expected = f"identity_already_applied:p123:the joker->{normalize_key(JOKIC)}"
    assert rows[1].blocked_reason == expected


def test_a_second_player_sharing_a_name_with_an_applied_pick_is_not_deduplicated(
    session: Session,
) -> None:
    """Excludes: a pick that happened being filed as one we already had.

    ``normalize_key`` erases generational suffixes, so two genuinely different
    players can share a key. Round ten refused that pair within a run. Across
    the apply boundary the second one reached ``already_in_log`` instead --
    and **nothing in this package ever clears ``skipped_reason``**, so the pick
    was gone permanently while the status screen called it a duplicate.

    The assertion that carries this is ``skipped_reason is None``. Blocking is
    recoverable and skipping is not, so "refused" and "burnt" are the two
    states worth telling apart here; asserting only that it did not apply would
    be satisfied by the defect.

    **Reading in which this passes and the defect is present:** if the second
    reading were refused for some *other* reason before identity was consulted
    -- a seat or price disagreement, say -- ``skipped_reason`` would also be
    ``None``. The two readings are therefore given the same seat and the same
    amount, so nothing but identity can separate them, and the reason is
    asserted exactly.
    """
    draft = _auction_draft(session)

    _bridge_naming(session, "t1", 50.0, key="r12-b1", label="Gary Payton", player_id="p1")
    feed_service.ingest(session, draft, client=None)
    assert len(feed_service.apply_observations(session, draft).applied) == 1

    _bridge_naming(session, "t1", 50.0, key="r12-b2", label="Gary Payton", player_id="p2")
    feed_service.ingest(session, draft, client=None)
    feed_service.apply_observations(session, draft)

    rows = feed_service.load_observations(session, draft)
    second = rows[1]
    assert second.skipped_reason is None
    assert second.applied_event_sequence is None
    assert second.blocked_reason == "identity_conflict:one_label_many_player_ids:gary payton:p1|p2"

    status = feed_service.feed_status(session, draft)
    assert status.pending_count == 1
    assert status.skipped == ()


def test_two_captures_at_one_instant_elect_the_one_published_later(session: Session) -> None:
    """Excludes: the stale reading winning a tie and the correction being
    labelled as the thing it corrected.

    Bridge payloads are selected newest-first so ``scan_limit`` keeps a recent
    window. Writing observations in that order gave the newest payload the
    lowest observation id, and observation id is the tie-break both identity
    supersession and the newest-per-transport collapse fall back on when
    ``observed_at`` ties -- which production SQLite produces on its own for two
    captures inside the same second.

    Driven before the fix: publication order "The Joker"/t1/$50 then
    "Nikola Jokic"/t2/$10 put The Joker on seat one at $50 -- **wrong buyer and
    wrong price** -- and blocked the true reading as ``identity_superseded``,
    which reads on the status screen exactly like a correction being handled.

    **Reading in which this passes and the defect is present:** if the two
    captures did not actually tie, the ``observed_at`` comparison would order
    them correctly and the tie-break would never be consulted. So the tie is
    asserted directly before the outcome is.
    """
    draft = _auction_draft(session)

    _bridge_naming(session, "t1", 50.0, key="r12-c1", label="The Joker", player_id="p123")
    _bridge_naming(session, "t2", 10.0, key="r12-c2", label=JOKIC, player_id="p123")

    payloads = session.query(BridgePayload).order_by(BridgePayload.id).all()
    assert [payload.dedupe_key for payload in payloads] == ["r12-c1", "r12-c2"]
    assert payloads[0].created_at == payloads[1].created_at, "the tie this test is about is absent"

    feed_service.ingest(session, draft, client=None)
    feed_service.apply_observations(session, draft)

    state = draft_service.load_state(session, draft)
    holdings = {
        participant.participant.id: [
            (holding.player_label, holding.price) for holding in participant.holdings
        ]
        for participant in state.participants
    }
    assert holdings[state.participants[0].participant.id] == []
    assert holdings[state.participants[1].participant.id] == [(JOKIC, Decimal("10.00"))]


def test_one_unreadable_record_does_not_discard_the_healthy_board(session: Session) -> None:
    """Excludes: a whole republished board being thrown away for one bad row.

    Round eleven refused the entire capture when any record carried an
    unreadable ``playerId``. **Fantrax republishes the full pick list on every
    pick**, so a single malformed historical row is in every subsequent capture
    and the feed never recovers -- "the next capture is seconds away" is not a
    mitigation when the next capture contains the same row.

    Driven before the fix: ``observations_written=0`` on both captures, no
    stored rows, an empty board, and a status of ``pending=0 blocked=()
    skipped=()`` that is byte-identical to a draft which has not started.

    The dropped row is reported rather than merely omitted, because a missing
    pick reported as nothing is the failure this module exists to prevent.
    **Reporting it was not enough**, and that is
    ``draft-feed-unreadable-id-surfacing``: the count below reaches the ``POST``
    ingest response only, and a live board polls ``GET``. The row is now stored
    with a ``skipped_reason``, so both channels say it. This test still owns the
    original property -- the healthy record is untouched -- and the surfacing
    itself is asserted where it belongs, on the status endpoint.
    """
    records: list[dict[str, Any]] = [
        {
            "teamId": "t1",
            "playerName": "Broken",
            "overallPick": 1,
            "amount": 5.0,
            "playerId": "x" * (MAX_EXTERNAL_ID_CHARS + 1),
        },
        {
            "teamId": "t2",
            "playerName": "Healthy Two",
            "overallPick": 2,
            "amount": 7.0,
            "playerId": "p2",
        },
    ]
    draft = _auction_draft(session)
    _capture(session, records=records, dedupe_key="r12-d1")

    outcome = feed_service.ingest(session, draft, client=None)
    bridge = next(
        source for source in outcome.sources if source.transport is SourceTransport.BRIDGE_CAPTURE
    )
    assert bridge.instants_recognised == 1, "the unreadable record is not a reading"
    assert bridge.observations_written == 2
    assert bridge.observations_skipped == 1
    assert [shape.reason for shape in bridge.unrecognised] == ["player_external_id_unreadable"]
    assert bridge.unrecognised[0].occurrences == 1

    feed_service.apply_observations(session, draft)
    state = draft_service.load_state(session, draft)
    assert [
        holding.player_label
        for participant in state.participants
        for holding in participant.holdings
    ] == ["Healthy Two"]


def test_a_board_of_only_unreadable_records_is_still_refused(session: Session) -> None:
    """Excludes: an unreadable list counting as an accepted, empty pick log and
    silencing every other list in the same block.

    Dropping unreadable rows is right *because* the surviving rows are evidence
    the list was a pick log. With no survivors there is no such evidence -- and
    "accepted" is not an inert word here. ``accepted_here`` suppresses the shape
    refusals of every other candidate list in the entry, which is the defect the
    comment above ``capacity_refusals`` already describes: *one shallow accepted
    list silencing exactly that about a deep one, a missing pick reported as
    nothing, defeated by the channel it reports on.* An all-unreadable list
    accepted as empty does that to whichever list actually was the board.

    **This assertion was wrong the first time and the mutation control caught
    it.** It originally asserted ``observations_written == 0`` and the reason
    string, both of which the caller still produces with the refusal deleted --
    the reason simply arrives through the dropped-record channel instead. The
    check passed while naming a defect it did not exclude. What discriminates is
    the sibling list's refusal still being reported, so that is what is asserted.
    """
    draft = _auction_draft(session)
    unreadable = [
        {
            "teamId": "t1",
            "playerName": "Broken One",
            "overallPick": 1,
            "amount": 5.0,
            "playerId": "x" * (MAX_EXTERNAL_ID_CHARS + 1),
        },
    ]
    row = BridgePayload(
        schema_name="hoops-gm.bridge-payload.v1",
        source="xhr",
        captured_at=NOW,
        request_method="POST",
        request_url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
        response_status=200,
        response_ok=True,
        response_content_type="application/json",
        body_raw="{}",
        # The non-pick list is first so it is the refusal that would be reported
        # if anything is reported at all; the unreadable board follows it.
        body_json={
            "responses": [
                {
                    "data": {
                        "standings": [{"teamId": "not-a-seat", "playerName": "X", "amount": 1.0}],
                        "draftPicks": unreadable,
                    }
                }
            ]
        },
        dedupe_key="r12-e1",
        raw_payload="{}",
        created_at=NOW,
    )
    session.add(row)
    session.flush()

    outcome = feed_service.ingest(session, draft, client=None)
    bridge = next(
        source for source in outcome.sources if source.transport is SourceTransport.BRIDGE_CAPTURE
    )
    assert bridge.observations_written == 0
    reasons = {shape.reason for shape in bridge.unrecognised}
    assert "no_seat_anchor" in reasons, (
        f"reasons were {reasons}; the unreadable list was treated as an accepted "
        "board and suppressed the other list's refusal"
    )


def test_dropping_a_record_does_not_renumber_the_ones_beside_it(session: Session) -> None:
    """Excludes: the same pick storing twice the day its bad neighbour heals.

    ``locator`` is a third of the ``(transport, artifact_key, locator)``
    identity this feed dedupes on. If admitted records were numbered among the
    survivors rather than by their true position, a healthy pick's locator
    would change as soon as the malformed row above it became readable, and the
    feed would store it a second time as a new observation.

    This is not a hypothetical: it is a defect I introduced writing the fix
    above and caught before running it, which is why it is pinned rather than
    reasoned about.

    The unreadable record is now stored too, carrying a ``skipped_reason``, so
    the property is stronger than when the row was dropped: the two locators
    must be *distinct and true*. If the refusal reused the survivor's slot the
    two rows would collide on the unique constraint, and one of the pair would
    be lost to whichever write lost the race.
    """
    draft = _auction_draft(session)
    _capture(
        session,
        records=[
            {
                "teamId": "t1",
                "playerName": "Broken",
                "overallPick": 1,
                "amount": 5.0,
                "playerId": "x" * (MAX_EXTERNAL_ID_CHARS + 1),
            },
            {
                "teamId": "t2",
                "playerName": "Healthy Two",
                "overallPick": 2,
                "amount": 7.0,
                "playerId": "p2",
            },
        ],
        dedupe_key="r12-f1",
    )
    feed_service.ingest(session, draft, client=None)

    rows = feed_service.load_observations(session, draft)
    by_locator = {row.locator: row for row in rows}
    assert len(by_locator) == 2, "two records must occupy two locators"
    survivor = next(row for row in rows if row.player_label == "Healthy Two")
    refused = next(row for row in rows if row.skipped_reason)
    assert survivor.locator.endswith("[1]"), (
        f"locator {survivor.locator!r} numbers the survivor as if the refused "
        "record had never been there"
    )
    assert refused.locator.endswith("[0]")


def test_a_falling_back_reader_never_uses_the_storing_coercer() -> None:
    """Excludes: the round-eleven defect being reintroduced by a new call site.

    ``_as_text`` documents its own unsafe caller -- "safe for a caller that
    stores the result and unsafe for one that falls back to another key. Those
    callers use ``_read_text``" -- and ``_player_identity`` was that caller for
    as long as it existed. Nothing executable connected the rule to the call
    site, so the rule was true, written in the right place, and unenforced.

    Both findings of round eleven had that shape, which is why this is a check
    rather than a third fix: **a rule this repository has already written down
    and does not enforce is the failure mode, not any particular field.**

    Two properties, because one alone is satisfiable without the other:

    * No ``_as_text`` call may be a non-final operand of an ``or``. That is the
      fallback form the docstring names, and it is the form the defect took.
    * ``_player_identity`` and ``_player_label`` must both read their explicit
      key through ``_read_text``. They are siblings with one discipline and one
      of them drifted; naming the pair is what makes the drift visible rather
      than requiring someone to notice it.

    **Reading in which this passes and the defect is present:** a *new* falling
    back reader written as ``x = _as_text(...)`` followed by ``if x is None:``
    and a second key. This does not do dataflow analysis and would not see it.
    That is a real hole and it is narrower than the one it closes -- the
    ``or`` form is what both existing readers were written in.
    """
    source = (
        Path(__file__).resolve().parents[1] / "src" / "hoops_gm" / "draft" / "feed" / "recognise.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))

    fallbacks = [
        operand.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
        for operand in node.values[:-1]
        if isinstance(operand, ast.Call)
        and isinstance(operand.func, ast.Name)
        and operand.func.id == "_as_text"
    ]
    assert fallbacks == [], (
        f"_as_text used as an `or` fallback at lines {fallbacks}. It collapses "
        "'absent' and 'present but refused' into one answer; a caller that "
        "falls back to another key must use _read_text and handle _Unreadable. "
        "See _as_text's own docstring, and the round-eleven entry in "
        "docs/handoff.md for what this cost."
    )

    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for name in ("_player_identity", "_player_label"):
        assert name in functions, f"{name} was renamed; this guard now checks nothing"
        called = {
            child.func.id
            for child in ast.walk(functions[name])
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        assert "_read_text" in called, (
            f"{name} reads a payload key without _read_text. Both identity "
            "readers fall back to a second key, so both must be able to tell "
            "'refused' from 'absent' -- one of them drifted once already."
        )


def _naming_record(team: str, label: str, amount: float, player_id: str) -> dict[str, Any]:
    """One draft-pick record, with the capture timing left to the caller.

    ``_bridge_naming`` writes its own capture and so cannot vary ``captured_at``
    against ``created_at``, which is the whole subject of the tests below.
    """
    return {
        "teamId": team,
        "playerName": label,
        "overallPick": 1,
        "amount": amount,
        "playerId": player_id,
    }


def test_a_correction_delivered_before_the_reading_it_corrects_is_not_applied(
    session: Session,
) -> None:
    """Excludes: delivery order deciding which reading is current.

    ``observed_at`` is our clock at the moment a capture reached the backend.
    Every ordering decision in this package was made on it -- identity
    supersession, the newest-per-transport collapse, reconciliation's
    newest-per-key -- and that is correct for freshness and wrong for
    supersession. ``userscript/src/capture.js`` posts captures without a global
    queue, so two published a second apart can be delivered in either order.

    Driven before the fix: a correction published at t+1 but delivered first
    put the *stale* reading on the board -- The Joker, seat one, $50, when the
    truth was Nikola Jokic, seat two, $10 -- and blocked the true reading as
    ``identity_superseded``, which on the status screen reads exactly like a
    correction being handled properly.

    The fix does not resolve the disagreement by preferring the source's own
    clock, which is the browser's and self-describing. It refuses, and names
    the refusal, leaving the player visibly absent rather than confidently
    attached to the wrong seat.

    **Reading in which this passes and the defect is present:** if the two
    captures were delivered in publication order, publication and arrival would
    agree, nothing would be disputed, and the assertion below would be
    satisfied by a package that had never learned the difference. So the
    inversion is asserted directly, on the stored rows, before the outcome is.
    """
    draft = _auction_draft(session)

    _capture(
        session,
        records=[_naming_record("t1", "The Joker", 50.0, "p123")],
        dedupe_key="published-old",
        captured_at=NOW,
        created_at=NOW + timedelta(seconds=1),
    )
    _capture(
        session,
        records=[_naming_record("t2", JOKIC, 10.0, "p123")],
        dedupe_key="published-new",
        captured_at=NOW + timedelta(seconds=1),
        created_at=NOW,
    )

    feed_service.ingest(session, draft, client=None)
    rows = feed_service.load_observations(session, draft)
    arrival = [row.artifact_key for row in sorted(rows, key=lambda r: (r.observed_at, r.id))]
    published = [
        row.artifact_key
        for row in sorted(rows, key=lambda r: (r.source_claimed_at or r.observed_at, r.id))
    ]
    assert arrival != published, "the delivery inversion this test is about is absent"

    feed_service.apply_observations(session, draft)
    status = feed_service.feed_status(session, draft)

    state = draft_service.load_state(session, draft)
    holdings = [
        [(holding.player_label, holding.price) for holding in participant.holdings]
        for participant in state.participants
    ]
    assert holdings == [[], []], "a disputed ordering put somebody on the board"
    assert status.blocked == ("capture_order_disputed:p123:the joker|nikola jokic",)


def test_captures_delivered_in_publication_order_are_not_disputed(session: Session) -> None:
    """Excludes: the ordering refusal firing on an ordinary draft.

    The over-refusal control for the test above. ``capture_order_disputed``
    blocks a key outright, so a version of it that fired whenever two captures
    named one player would empty the board -- and **a board that never fills
    looks exactly like a draft that has not started**, which is the failure
    this module exists to prevent. A fix that blocked everything would pass the
    test above while being worse than the defect.

    Two captures, published and delivered in the same order, correcting a
    label. The correction must land.
    """
    draft = _auction_draft(session)

    _capture(
        session,
        records=[_naming_record("t1", "The Joker", 50.0, "p123")],
        dedupe_key="in-order-old",
        captured_at=NOW,
        created_at=NOW,
    )
    _capture(
        session,
        records=[_naming_record("t1", JOKIC, 50.0, "p123")],
        dedupe_key="in-order-new",
        captured_at=NOW + timedelta(seconds=1),
        created_at=NOW + timedelta(seconds=1),
    )

    feed_service.ingest(session, draft, client=None)
    feed_service.apply_observations(session, draft)
    status = feed_service.feed_status(session, draft)

    assert not any(reason.startswith("capture_order_disputed") for reason in status.blocked)
    state = draft_service.load_state(session, draft)
    holdings = [
        [(holding.player_label, holding.price) for holding in participant.holdings]
        for participant in state.participants
    ]
    assert holdings == [[(JOKIC, Decimal("50.00"))], []]


def test_a_stored_instant_carries_its_storage_order(session: Session) -> None:
    """Excludes: two passes answering "which reading is current" differently.

    ``InstantProvenance`` carried no sequence, so every consumer working on
    instants -- ``_newest_per_key``, ``freshness_of`` -- tie-broke on
    ``received_at`` alone and silently kept whichever tied reading it saw
    first, while the apply path, which works on rows and *has* the id, kept the
    last. Two captures inside one second tie under production SQLite's
    ``CURRENT_TIMESTAMP`` without any fixture help, so the disagreement is
    reachable on an ordinary draft night rather than only under a contrived
    clock.

    **Reading in which this passes and the defect is present:** asserting only
    that ``sequence`` is populated would be satisfied by a field that nothing
    consults -- the "a guard can be correct and uncalled" gap this PR has
    already hit once. So the collapse itself is exercised: two tied readings
    are reconciled and the one stored *last* must be the one that survives.
    """
    draft = _auction_draft(session)

    _bridge_naming(session, "t1", 50.0, key="tie-first", label=JOKIC, player_id="p123")
    _bridge_naming(session, "t2", 10.0, key="tie-second", label=JOKIC, player_id="p123")
    feed_service.ingest(session, draft, client=None)

    rows = feed_service.load_observations(session, draft)
    assert rows[0].observed_at == rows[1].observed_at, "the tie this test is about is absent"
    instants = [feed_service._to_instant(row) for row in rows]
    assert [instant.provenance.sequence for instant in instants] == [rows[0].id, rows[1].id]

    from hoops_gm.draft.feed.reconcile import _newest_per_key

    latest = _newest_per_key(instants)
    assert len(latest) == 1
    surviving = next(iter(latest.values()))
    assert surviving.provenance.sequence == rows[1].id
    assert surviving.team_external_id == "t2"
    assert surviving.amount == Decimal("10.00")


# ---------------------------------------------------------------------------
# draft-feed-unreadable-id-surfacing: a record dropped at ingest and invisible
# on the endpoint a live board polls.
# ---------------------------------------------------------------------------


UNREADABLE_ID = "p" * (MAX_EXTERNAL_ID_CHARS + 1)


def _short_a_player(session: Session) -> Draft:
    """Two captured picks, one of which carries a ``playerId`` we cannot read.

    The list is admitted, because the *other* record satisfies every admission
    rule -- so this is established to be a pick log and the board is
    established to be short exactly one row of it. That distinction is what
    makes storing the unreadable record an observation rather than an
    invention; see :func:`~hoops_gm.draft.feed.recognise._accept_list`.

    The readable record is pick **one** deliberately. With the unreadable
    record first, a snake board halts on ``draft_pick_out_of_turn`` rather than
    applying anything -- correct behaviour, and a *different* symptom from the
    one this file is about. The reproduction in ``docs/backlog.md`` is a board
    that applied a pick and is silently short another, so the fixture has to
    reach that state rather than a loud halt.
    """
    league = _league(session, draft_type=DraftType.SNAKE)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[
            {"teamId": "t1", "playerId": "p-jokic", "playerName": JOKIC, "overallPick": 1},
            {"teamId": "t2", "playerId": UNREADABLE_ID, "playerName": EDWARDS, "overallPick": 2},
        ],
        dedupe_key="short-a-player",
    )
    return draft


def test_a_record_whose_player_id_cannot_be_read_reaches_the_status_endpoint(
    session: Session,
) -> None:
    """Excludes: a captured pick counted at ingest and reported as nothing.

    The owner was asked what would make him abandon the tool mid-auction and
    answered *"it loses track of the draft - shows me picks that already
    happened or misses one"*. This is that failure exactly, and it was driven
    at PR #104 head ``7a66d4e``::

        POST -> written 1, unrecognised [('player_external_id_unreadable', 1)]
        GET  -> observations 1  applied 1  pending 0  blocked ()  skipped ()
                freshness bridge_capture silent: False

    Two records captured, one player on the board, **and every channel a live
    screen polls reading clean**. ``unrecognised`` reached the ``POST``
    response only; ``FeedStatus`` carried no such field, and a board polls
    ``GET``.

    **Reading under which this test passes while the defect is present:** the
    assertion is not "``observation_count`` went up", which a row stored for
    any reason would satisfy. It is that the *reason* survives to ``GET``
    under the name of the field that could not be read, so a fix which stored
    the row without saying why -- or which said why only on the ingest
    response -- still fails here.
    """
    draft = _short_a_player(session)

    outcome = feed_service.ingest(session, draft).sources[0]
    assert [(shape.reason, shape.occurrences) for shape in outcome.unrecognised] == [
        ("player_external_id_unreadable", 1)
    ], "the ingest-side report is the precondition of this test, not its subject"

    feed_service.apply_observations(session, draft)
    status = feed_service.feed_status(session, draft)

    assert dict(status.skipped) == {"player_external_id_unreadable": 1}
    assert status.observation_count == 2
    assert status.applied_count == 1
    assert status.pending_count == 0


def test_an_unreadable_record_is_never_applied_and_never_pending(session: Session) -> None:
    """Excludes: surfacing the record by making it an application candidate.

    ``blocked_reason`` was the cheap route and it is wrong for this: a blocked
    row is still pending, so it is retried on every apply run and would land
    the moment anything narrowed the block. An id that cannot be read is not
    going to become readable, so the correct state is permanent.

    Also excludes the *other* cheap route -- ``player_external_id=None`` on an
    ordinary applicable row -- which round eleven forbade because it makes
    "supplied and refused" indistinguishable from "never supplied". The
    distinction survives here in ``skipped_reason``, which names the field.
    """
    draft = _short_a_player(session)
    feed_service.ingest(session, draft)
    feed_service.apply_observations(session, draft)

    rows = feed_service.load_observations(session, draft)
    unreadable = [row for row in rows if row.skipped_reason == "player_external_id_unreadable"]
    assert len(unreadable) == 1
    row = unreadable[0]
    assert row.applied_event_sequence is None
    assert row.blocked_reason is None
    assert row.player_external_id is None, "an id we could not read must not be stored as one"
    assert row.player_label is None, (
        "a name on a record whose identity we refused is a claim we cannot make, "
        "and withholding it is what keeps the row out of identity matching"
    )
    assert row.team_external_id == "t2", "the seat was readable and is diagnostic"

    # A second apply run must not resurrect it.
    again = feed_service.apply_observations(session, draft)
    assert all(event.observation_id != row.id for event in again.applied)
    assert all(observation_id != row.id for observation_id, _reason in again.skipped)
    assert feed_service.feed_status(session, draft).pending_count == 0


def test_an_unreadable_record_does_not_join_identity_matching(session: Session) -> None:
    """Excludes: a record we could not identify being matched to a player.

    A skipped row still carries whatever the payload said, and the explicit
    ``playerName`` here is readable. If that label reached
    :func:`~hoops_gm.draft.feed.observations.matching_key`, the row would
    become a one-sided reading of Jokic in the reconciliation report -- a claim
    about a player, made out of a record whose own identity field this module
    refused. It would also count toward ``instant_count``, and
    ``freshness_of`` lets contact suppress ``silent`` only for a transport that
    has produced at least one instant, so a feed that had read *no* picks could
    report itself not silent on the strength of a record it could not read.

    That second half is the assertion that would have caught the round-thirteen
    transcript's ``freshness bridge_capture silent: False``.
    """
    league = _league(session, draft_type=DraftType.SNAKE)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[
            {"teamId": "t1", "playerId": "p-jokic", "playerName": JOKIC, "overallPick": 1},
            {"teamId": "t2", "playerId": UNREADABLE_ID, "playerName": EDWARDS, "overallPick": 2},
        ],
        dedupe_key="not-a-player-claim",
    )
    feed_service.ingest(session, draft)

    status = feed_service.feed_status(session, draft)
    assert status.reconciliation is not None
    assert [instant.player_label for instant in status.reconciliation.only_left] == [JOKIC], (
        "the refused record must not appear as a reading about Anthony Edwards"
    )
    bridge = next(
        entry for entry in status.freshness if entry.transport is SourceTransport.BRIDGE_CAPTURE
    )
    assert bridge.instant_count == 1


def test_a_record_with_no_readable_identity_at_all_is_still_surfaced(session: Session) -> None:
    """Excludes: the same silence returning when there is no name to fall back on.

    The previous tests all leave a readable ``playerName`` on the unreadable
    record, so a fix that only stored rows which still named *something* would
    pass them. This record names nothing this module will accept: the id is
    over the column and the only name key present is ``name``, which
    :data:`AMBIGUOUS_NAME_ALIASES` classifies as a key a *team* object also
    carries -- and :func:`_player_label`'s fallback to it is documented as safe
    only once ``_player_identity`` has succeeded, which here it has not.

    So the row names no player, which is what the ``feed_names_a_player``
    CHECK forbade. Migration ``0021`` admits it **only** when a
    ``skipped_reason`` says why, which keeps the invariant that anything
    applicable names a player.
    """
    league = _league(session, draft_type=DraftType.SNAKE)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[
            {"teamId": "t1", "playerId": "p-jokic", "playerName": JOKIC, "overallPick": 1},
            {"teamId": "t2", "playerId": UNREADABLE_ID, "name": "Seat Two", "overallPick": 2},
        ],
        dedupe_key="no-identity-at-all",
    )

    outcome = feed_service.ingest(session, draft).sources[0]
    assert outcome.observations_rejected == 0, (
        "a row the storage layer refuses is the silence this unit exists to remove"
    )

    status = feed_service.feed_status(session, draft)
    assert dict(status.skipped) == {"player_external_id_unreadable": 1}

    rows = feed_service.load_observations(session, draft)
    orphan = next(row for row in rows if row.skipped_reason)
    assert orphan.player_label is None, (
        "'name' is ambiguous and the record never established it was about a player"
    )
    assert orphan.player_external_id is None


def test_the_status_document_itself_reports_the_missing_pick(
    client: TestClient, session: Session
) -> None:
    """Excludes: the fix stopping one layer short of the screen.

    The defect this unit closes is stated in ``docs/backlog.md`` as a property
    of ``_status_out``, not of ``feed_status``: *"``unrecognised`` reaches only
    the ``POST`` response; ``_status_out`` carries no such field"*. Every other
    test here asserts against the service, and a service-level assertion stays
    green while the response model drops the field the screen reads -- which is
    the same defect, one layer out.

    So this one goes through HTTP and asserts the two documents *together*:
    ``POST`` names the block's keys, which is what a five-minute fix needs, and
    ``GET`` names the loss, which is what a board polling every few seconds
    needs. Before this change the second half was empty.
    """
    league = _league(session, draft_type=DraftType.SNAKE)
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[
            {"teamId": "t1", "playerId": "p-jokic", "playerName": JOKIC, "overallPick": 1},
            {"teamId": "t2", "playerId": UNREADABLE_ID, "playerName": EDWARDS, "overallPick": 2},
        ],
        dedupe_key="http-surfacing",
    )
    session.commit()

    ingest = client.post(f"/api/v1/drafts/{draft.id}/feed/ingest", json={"apply": True})
    assert ingest.status_code == 200, ingest.text
    body = ingest.json()
    bridge = next(source for source in body["sources"] if source["transport"] == "bridge_capture")
    assert bridge["observations_written"] == 2
    assert bridge["observations_skipped"] == 1
    assert bridge["instants_recognised"] == 1
    assert [shape["reason"] for shape in bridge["unrecognised"]] == [
        "player_external_id_unreadable"
    ]

    status = client.get(f"/api/v1/drafts/{draft.id}/feed")
    assert status.status_code == 200, status.text
    document = status.json()
    assert document["skipped"] == {"player_external_id_unreadable": 1}
    assert document["observation_count"] == 2
    assert document["applied_count"] == 1
    assert document["pending_count"] == 0
    assert document["blocked"] == []

    # The board really is short a player, which is what the report is about.
    events = client.get(f"/api/v1/drafts/{draft.id}/events").json()
    assert [event["player_label"] for event in events["events"]] == [JOKIC]


def test_the_official_path_surfaces_a_refused_identity_too(session: Session) -> None:
    """Excludes: the fix holding on one path only.

    Round eight of this unit found three docstrings arguing from a rule that
    existed on the bridge path alone. ``recognise_official_draft_picks``
    reaches the same end state by a different route -- ``_as_text`` refuses the
    over-long ``player_id``, ``player_name`` is absent, and the record was
    dropped at ``if not (player_external_id or player_label)`` with the loss
    counted only on the ``POST`` response.
    """
    draft = _auction_draft(session)

    class _Official:
        def get_draft_picks_with_provenance(
            self, league_id: str, *, max_age: timedelta | None = None
        ) -> tuple[list[FantraxDraftPick], str, datetime]:
            return (
                [
                    FantraxDraftPick(
                        team_id="t1",
                        player_id=UNREADABLE_ID,
                        player_name=None,
                        round_number=None,
                        pick_number=None,
                        overall_pick=None,
                        auction_amount=50.0,
                    ),
                    FantraxDraftPick(
                        team_id="t2",
                        player_id="p-edwards",
                        player_name=EDWARDS,
                        round_number=None,
                        pick_number=None,
                        overall_pick=None,
                        auction_amount=10.0,
                    ),
                ],
                "officialsha-unreadable",
                NOW,
            )

    feed_service.ingest(session, draft, client=_Official())
    feed_service.apply_observations(session, draft)

    status = feed_service.feed_status(session, draft)
    assert dict(status.skipped) == {"player_external_id_unreadable": 1}
    assert status.observation_count == 2


# ---------------------------------------------------------------------------
# Round ten: the burn, driven rather than reasoned about.
# ---------------------------------------------------------------------------


def test_a_sale_past_the_assumed_budget_is_applied_rather_than_burned(session: Session) -> None:
    """Excludes: a real pick vanishing because our budget scalar is wrong.

    **The two questions are different, and only one of them was ever answered.**
    That a sale above the assumed budget now *derives* is injection, and
    ``test_draft_tracker`` covers it. This test covers reversion on the path the
    owner's draft actually runs on: a capture, ingested, applied. That path had
    a second consequence nobody had driven — it was established by grep and by
    reading, which is exactly the "unexamined inheritance" this repository keeps
    finding defects in.

    **The consequence.** ``apply_observations`` files a ``DraftLogError`` into
    ``row.skipped_reason`` (service.py, the ``except DraftLogError`` branch),
    and ``pending`` is filtered on ``skipped_reason IS NULL``. Nothing in the
    package assigns ``skipped_reason = None`` anywhere. So a refusal did not
    merely skip the row for this run — it **burned it permanently**, and
    re-ingesting the identical capture deduped against the burned row instead of
    retrying it. The pick was unrecoverable short of typing it by hand, which is
    precisely the thing the feed exists to stop him doing.

    ``t1`` here clears 150 and then 120 against a 200 scalar. Both are real
    sales; the scalar is the thing that is wrong.
    """
    league = _league(session, draft_type=DraftType.AUCTION, budget=Decimal("200.00"))
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[
            {"teamId": "t1", "playerName": JOKIC, "winningBid": 150},
            {"teamId": "t1", "playerName": EDWARDS, "winningBid": 120},
        ],
        dedupe_key="over-assumed-budget",
    )
    feed_service.ingest(session, draft)

    outcome = feed_service.apply_observations(session, draft)

    # Both reached the board. Before this change the second raised
    # ``draft_budget_exceeded`` and never got as far as ``board.add``.
    assert outcome.halted is None
    assert [event.player_label for event in outcome.applied] == [JOKIC, EDWARDS]
    assert [event.player_label for event in draft_service.load_events(session, draft)] == [
        JOKIC,
        EDWARDS,
    ]

    # And no row was burned, which is the half that could not be undone.
    rows = feed_service.load_observations(session, draft)
    assert [row.skipped_reason for row in rows] == [None, None]
    assert all(row.applied_event_sequence is not None for row in rows)

    # The tool reports its own wrong assumption instead of hiding a real draft.
    state = draft_service.load_state(session, draft)
    seat = {each.participant.team_slot: each for each in state.participants}[1]
    assert seat.spent == Decimal("270.00")
    assert seat.remaining_budget == Decimal("-70.00")
    assert seat.over_assumed_budget is True

    # A second run is a no-op rather than a second pick: the rows are linked,
    # not re-applied. Asserted because "not burned" and "not duplicated" are
    # different properties and this change could have traded one for the other.
    again = feed_service.apply_observations(session, draft)
    assert list(again.applied) == []
    assert len(draft_service.load_events(session, draft)) == 2


def test_a_refusal_that_survives_still_burns_its_row_permanently(session: Session) -> None:
    """The mechanism the test above escapes, driven so it is not taken on trust.

    Without this, ``[None, None]`` up there is consistent with two very
    different worlds: one where ``draft_budget_exceeded`` stopped reaching the
    burn, and one where the burn never worked at all. Only the second is
    excluded here, and it is excluded by watching a *different*, still-live
    refusal burn a row and stay burned across a re-ingest.

    ``draft_roster_full`` is the vehicle: ``roster_size`` is 2, so ``t1``'s
    third purchase cannot be recorded. That refusal is correct and stays — it
    is a fact about a format the draft was created with, not about a scalar we
    guessed.

    **This is also a live defect, and it is not mine to fix here.** The burn is
    permanent for every surviving refusal, so a row skipped for a reason the
    owner then resolves by hand never returns to ``pending``. Route B removed
    the worst input to it. Filed rather than fixed.
    """
    league = _league(
        session,
        fantrax_league_id="LG-BURN",
        draft_type=DraftType.AUCTION,
        budget=Decimal("500.00"),
    )
    teams = _teams(session, league, ["t1", "t2"])
    draft = _draft(session, league, teams)
    _capture(
        session,
        records=[
            {"teamId": "t1", "playerName": JOKIC, "winningBid": 10},
            {"teamId": "t1", "playerName": EDWARDS, "winningBid": 10},
            {"teamId": "t1", "playerName": HALIBURTON, "winningBid": 10},
        ],
        dedupe_key="roster-full-burn",
        league_id="LG-BURN",
    )
    feed_service.ingest(session, draft)

    outcome = feed_service.apply_observations(session, draft)
    assert [event.player_label for event in outcome.applied] == [JOKIC, EDWARDS]

    burned = [row for row in feed_service.load_observations(session, draft) if row.player_label]
    third = next(row for row in burned if row.player_label == HALIBURTON)
    assert third.skipped_reason is not None
    assert third.skipped_reason.startswith("draft_roster_full")
    assert third.applied_event_sequence is None

    # The permanence. Re-ingesting the identical capture and re-applying does
    # not retry it, because ``pending`` filters on ``skipped_reason IS NULL``
    # and nothing ever sets it back to ``None``.
    feed_service.ingest(session, draft)
    retry = feed_service.apply_observations(session, draft)
    assert list(retry.applied) == []
    still = next(
        row
        for row in feed_service.load_observations(session, draft)
        if row.player_label == HALIBURTON
    )
    assert still.skipped_reason is not None, (
        "If this is None the burn has been fixed elsewhere and the test above "
        "no longer excludes what it claims to."
    )
    assert still.applied_event_sequence is None
