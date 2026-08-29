"""Feeding the draft tracker from the bridge and the official API.

The tracker records what happened; nothing in this package decides what to do
about it. Nothing here writes to Fantrax — it is the read path, and the write
path is a different unit behind the Automation gate.

Three properties this package is built to hold, each with the failure it exists
because of:

* **Provenance per instant, not per source.** Two agreeing readings are only
  two readings if two different artifacts, on two different transports,
  produced them. See :mod:`hoops_gm.draft.feed.reconcile`.
* **Freshness on our clock, reported as a value.** A quiet feed must be able to
  say when it last heard anything. Source-supplied timestamps are displayed and
  never subtracted.
* **Fail closed and loudly.** A shape we cannot read produces zero rows and a
  visible count, never a half-read pick.
"""

from hoops_gm.draft.feed.board_dom import (
    BoardParseRefused,
    BoardPick,
    BoardReading,
    parse_draft_board,
)
from hoops_gm.draft.feed.observations import (
    InstantKind,
    InstantProvenance,
    ObservedInstant,
    RecognitionResult,
    SourceTransport,
    UnrecognisedShape,
    matching_key,
)
from hoops_gm.draft.feed.recognise import (
    BOARD_RECOGNISER,
    FIELD_ALIASES,
    SNAPSHOT_CAPTURE_SOURCES,
    RecognitionContext,
    board_artifact_key,
    board_locator,
    league_id_in,
    league_id_in_page_url,
    recognise_board_snapshot,
    recognise_bridge_payload,
    recognise_official_draft_picks,
)
from hoops_gm.draft.feed.reconcile import (
    Disagreement,
    Match,
    ReconciliationReport,
    SourceFreshness,
    SourceIndependence,
    freshness_of,
    group_by_transport,
    reconcile,
)

__all__ = [
    "BOARD_RECOGNISER",
    "FIELD_ALIASES",
    "SNAPSHOT_CAPTURE_SOURCES",
    "BoardParseRefused",
    "BoardPick",
    "BoardReading",
    "Disagreement",
    "InstantKind",
    "InstantProvenance",
    "Match",
    "ObservedInstant",
    "RecognitionContext",
    "RecognitionResult",
    "ReconciliationReport",
    "SourceFreshness",
    "SourceIndependence",
    "SourceTransport",
    "UnrecognisedShape",
    "board_artifact_key",
    "board_locator",
    "freshness_of",
    "group_by_transport",
    "league_id_in",
    "league_id_in_page_url",
    "matching_key",
    "parse_draft_board",
    "recognise_board_snapshot",
    "recognise_bridge_payload",
    "recognise_official_draft_picks",
    "reconcile",
]
