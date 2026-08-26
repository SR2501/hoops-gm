"""What a feed source claimed, kept separately from what the draft log says.

One table, and the separation is the whole design. ``draft_events`` is the
log — what the owner accepts as having happened. ``draft_feed_observations`` is
what a machine *read*, with the identity of the bytes it read it from. A row
here is not a pick; it is a claim, and it stays a claim even after it has been
admitted into the log.

**Why not write straight into ``draft_events``.** Three reasons, each concrete.
A claim can be wrong — the recogniser's key names are unverified guesses
(``draft/feed/recognise.py``), and an unverified guess writing directly into an
append-only log means the only correction path is a ``void`` event for every
mistake. Two sources can disagree, and a disagreement is a finding to look at
rather than something to resolve by preferring the newer source; there is
nowhere in ``draft_events`` to put "the bridge says Jokić went for $61 and the
official API says $16". And a captured board republishes the whole draft on
every pick, so the same claim arrives dozens of times — an append-only log has
no way to express "I have heard this before" but a unique constraint does.

**``applied_event_sequence`` is the join between the two.** It is set when this
observation caused an event to be appended to the log, and it is what makes the
ingest idempotent across re-runs: an observation already applied is not applied
twice, and one not yet applied is still visible as a pending claim.

**Freshness lives on ``observed_at``, which is our clock.** ``source_claimed_at``
is whatever the source said about itself and no age is ever computed from it.
AGENTS.md records why in the general case (``gameEt`` carries a ``Z`` and is
Eastern time, five hours off its own sibling field); the specific case here is
that a userscript's ``captured_at`` comes off the owner's browser clock, and a
draft board that trusts a client clock can be told it is current by the very
thing that has stopped updating.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hoops_gm.db.base import Base, IntPk, TimestampMixin, UTCDateTime, portable_enum
from hoops_gm.db.models.enums import DraftFeedInstantKind, DraftFeedTransport

if TYPE_CHECKING:
    from hoops_gm.db.models.draft import Draft, DraftParticipant


class DraftFeedObservation(IntPk, TimestampMixin, Base):
    """One source's claim that one thing happened in one draft.

    The unique constraint is ``(draft_id, transport, artifact_key, locator)``.
    Each part earns its place:

    * ``artifact_key`` is the identity of the **bytes**. For a bridge capture it
      is the userscript's ``dedupe_key`` (``METHOD:hash(url):hash(body)``), so
      the same response stored twice into two ``bridge_payloads`` rows produces
      one key. Keying on ``bridge_payload_id`` instead would let a duplicated
      capture look like a second, corroborating read — the precise defect the
      independence guard exists to catch, reintroduced one layer down.
    * ``locator`` distinguishes the many records inside one artifact
      (``responses[0].data.picks[7]``). Without it a batch response could
      contribute exactly one row.
    * ``transport`` is included even though ``artifact_key`` is already
      near-unique, because the two key spaces are different (a dedupe key and a
      SHA-256) and a collision between them should be impossible by
      construction rather than by luck.
    * ``draft_id`` scopes it, so replaying the same captures into a second
      recorded draft is a supported thing to do rather than a constraint
      violation.

    What this does **not** deduplicate: the same pick seen in two genuinely
    different captures. Those are two rows on purpose. They are two readings,
    and collapsing them here would destroy the evidence that a claim was seen
    more than once.
    """

    __tablename__ = "draft_feed_observations"
    __table_args__ = (
        UniqueConstraint(
            "draft_id",
            "transport",
            "artifact_key",
            "locator",
            name="uq_draft_feed_observations_artifact_locator",
        ),
        CheckConstraint("amount IS NULL OR amount > 0", name="feed_amount_positive"),
        CheckConstraint("artifact_key <> ''", name="feed_artifact_key_present"),
        CheckConstraint(
            "player_label IS NOT NULL OR player_external_id IS NOT NULL",
            name="feed_names_a_player",
        ),
        # Mirrors the kind's own meaning at the storage layer: a selection is a
        # coordinate and a sale is a price. A row carrying both is a record read
        # under the wrong draft format, and the format is snapshotted on
        # ``drafts`` precisely so that is knowable.
        CheckConstraint(
            "(kind = 'sale' AND overall_pick IS NULL AND round_number IS NULL"
            " AND pick_in_round IS NULL)"
            " OR (kind = 'selection' AND amount IS NULL)",
            name="feed_shape_matches_kind",
        ),
        CheckConstraint("overall_pick IS NULL OR overall_pick >= 1", name="feed_overall_positive"),
        CheckConstraint("round_number IS NULL OR round_number >= 1", name="feed_round_positive"),
        CheckConstraint(
            "pick_in_round IS NULL OR pick_in_round >= 1", name="feed_pick_in_round_positive"
        ),
        CheckConstraint(
            "applied_event_sequence IS NULL OR applied_event_sequence >= 1",
            name="feed_applied_sequence_positive",
        ),
        CheckConstraint(
            "(applied_event_sequence IS NULL) = (applied_at IS NULL)",
            name="feed_applied_fields_agree",
        ),
    )

    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id", ondelete="CASCADE"), index=True)

    # --- provenance: which read produced this claim -------------------------
    transport: Mapped[DraftFeedTransport] = mapped_column(
        portable_enum(DraftFeedTransport, "draft_feed_transport")
    )
    #: Identity of the exact bytes. See the class docstring.
    artifact_key: Mapped[str] = mapped_column(String(128), index=True)
    #: Where inside those bytes this claim was found. A path, not a copy.
    locator: Mapped[str] = mapped_column(String(128))
    #: Which recogniser read it, by name and version, so "why did the board
    #: think that" has an answer that is a name rather than a reconstruction.
    recogniser: Mapped[str] = mapped_column(String(64))
    #: **Our** clock: when this claim entered our system. The only value any
    #: freshness figure is computed from.
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    #: The source's claim about itself. Displayed, never subtracted.
    source_claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    #: Optional link back to the stored capture, for a bridge observation. Kept
    #: as a convenience for looking at the raw payload and deliberately *not*
    #: used as the deduplication key.
    bridge_payload_id: Mapped[int | None] = mapped_column(
        ForeignKey("bridge_payloads.id", ondelete="SET NULL"), index=True
    )

    # --- the claim itself ---------------------------------------------------
    kind: Mapped[DraftFeedInstantKind] = mapped_column(
        portable_enum(DraftFeedInstantKind, "draft_feed_instant_kind")
    )
    #: Fantrax's team id, verbatim. Resolution to one of our seats is
    #: ``participant_id`` and is done against ``fantasy_teams.fantrax_team_id``,
    #: never inferred from the payload.
    team_external_id: Mapped[str | None] = mapped_column(String(64))
    #: ``RESTRICT``: a seat with observations attached cannot be removed out
    #: from under them. Deleting the draft still cascades to both.
    participant_id: Mapped[int | None] = mapped_column(
        ForeignKey("draft_participants.id", ondelete="RESTRICT"), index=True
    )
    #: The name the source published, verbatim — the same trade
    #: ``draft_events.player_label`` makes, for the same reason.
    player_label: Mapped[str | None] = mapped_column(String(128))
    player_external_id: Mapped[str | None] = mapped_column(String(64))
    overall_pick: Mapped[int | None] = mapped_column()
    round_number: Mapped[int | None] = mapped_column()
    pick_in_round: Mapped[int | None] = mapped_column()
    #: An observed clearing price. Never a computed one.
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    # --- what we did about it -----------------------------------------------
    #: The ``draft_events.sequence`` this observation corresponds to in the
    #: log — whether this observation *caused* that entry or merely matched one
    #: already there. ``skipped_reason`` distinguishes the two. Stored as the
    #: sequence rather than as a foreign key to ``draft_events.id`` because the
    #: sequence is the log's own identity (``draft.state`` orders on it and
    #: nothing else) and because a void supersedes *a sequence*.
    applied_event_sequence: Mapped[int | None] = mapped_column()
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    #: Why an admitted observation was not applied — already in the log, no
    #: resolvable seat, a disagreement held open. Free text, published on the
    #: status endpoint, because an observation that silently never becomes an
    #: event is indistinguishable from one that was never read.
    skipped_reason: Mapped[str | None] = mapped_column(Text)

    draft: Mapped[Draft] = relationship()
    participant: Mapped[DraftParticipant | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<DraftFeedObservation {self.transport.value} {self.kind.value} {self.player_label!r}>"
        )
