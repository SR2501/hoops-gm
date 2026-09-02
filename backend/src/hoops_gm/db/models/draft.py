"""Draft: what happened in one draft, as an ordered append-only log.

Three tables and one idea. ``drafts`` is the identity and the immutable
configuration a draft was recorded under, ``draft_participants`` are the seats,
and ``draft_events`` is the log. **Current state is not stored anywhere.** The
board, each roster, each participant's spend, the open auction lot and the next
pick coordinate are all derived from the log by
:mod:`hoops_gm.draft.state`, every time they are asked for.

Four decisions here carry weight, and each is checkable.

**The configuration is snapshotted, not derived on read.** ``draft_type``,
``team_count``, ``roster_size`` and ``auction_budget`` are copied onto the
draft row at creation, after
:func:`hoops_gm.draft.formats.draft_format_from_league` has accepted them. They
are never updated. Deriving them on read instead would mean an edit to the
``leagues`` row silently rewriting what configuration a mock recorded three
weeks ago was run under — and R39 is explicit that auction prices do not
transfer between configurations, so that edit would quietly corrupt the only
thing that makes the prices interpretable. The read contract publishes the
snapshot *and* reports drift against the current league row, rather than
choosing between them.

**Order is the ``sequence`` column, never a timestamp.** ``occurred_at`` is
whatever the recorder claimed, is nullable because a person pasting results
afterwards does not know it, and is not used to order anything. A
self-describing timestamp is exactly the field this project has already been
burned by (AGENTS.md: ``gameEt`` carries a ``Z`` and is Eastern), and an
ordering that a client's clock can permute is not an ordering.

**Corrections are appended, never applied.** There is no update path and no
delete path for an event. A mistake is superseded by a ``void`` event naming
its sequence. That is what lets a read derive state from a snapshot of the log
without taking a lock (ADR-014): everything at or below a given sequence is
immutable, so ``last_sequence`` is a complete version token.

**Append-only is enforced by construction and by API surface, not by the
database.** ``hoops_gm.draft.service`` contains the only writer and it only
inserts; ``api/routes/drafts.py`` exposes no ``PUT``/``PATCH``/``DELETE`` on an
event, and ``test_draft_tracker.py`` asserts that. Nothing stops a psql session
or a future ORM call from issuing an ``UPDATE``. A portable database-level
guarantee would need a trigger written twice, once per dialect, which
``test_portability.py`` forbids by design. The weaker claim is stated here
rather than left as an unexplained absence — the same trade, for the same
reason, as the position columns in migration 0016.

**What this module deliberately does not hold.** No recommendation, no
valuation, no dollar estimate, no inflation state, no ``p(play)``, and no
positional slot assignment. A ``sale`` amount is an observed clearing price,
not a computed one. Assigning a drafted player to a named roster slot (PG, G,
UTIL) needs Fantrax positional eligibility, and
``player-position-eligibility`` has landed only its NBA-listing half, so this
unit counts slots against ``roster_size`` and stops there.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hoops_gm.db.base import Base, IntPk, TimestampMixin, UTCDateTime, portable_enum
from hoops_gm.db.models.enums import (
    DraftEventType,
    DraftSourceBoardProfile,
    DraftToolUsage,
    DraftType,
)

if TYPE_CHECKING:
    from hoops_gm.db.models.identity import Player
    from hoops_gm.db.models.league import FantasyTeam, League


class Draft(IntPk, TimestampMixin, Base):
    """One recorded draft — a mock, or the real thing — and its frozen shape.

    ``league_id`` is required and is where the shape came from.
    ``leagues.fantrax_league_id`` is nullable precisely so a mock configuration
    can exist locally without being a Fantrax league (see ``league.py``), so a
    12-team $200 mock on a site we have no account with gets its own league row
    and its own draft rather than being crammed into the real league's numbers.
    """

    __tablename__ = "drafts"
    __table_args__ = (
        CheckConstraint("team_count >= 1", name="team_count_positive"),
        CheckConstraint("roster_size >= 1", name="roster_size_positive"),
        # Mirrors `draft_format_from_league`'s fail-closed rule at the storage
        # layer: a budget belongs to an auction and only to an auction. A
        # recorded draft whose format is unknown is inexpressible rather than
        # merely discouraged.
        CheckConstraint(
            "(draft_type = 'auction' AND auction_budget IS NOT NULL)"
            " OR (draft_type <> 'auction' AND auction_budget IS NULL)",
            name="auction_budget_matches_format",
        ),
        CheckConstraint("auction_budget IS NULL OR auction_budget > 0", name="budget_positive"),
        CheckConstraint("draft_type <> 'unknown'", name="draft_type_known"),
        CheckConstraint(
            "source_board_profile IS NULL OR (is_mock AND draft_type = 'snake')",
            name="source_board_profile_compatible",
        ),
    )

    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    #: Recorded, never inferred. A real draft and a mock are different evidence
    #: (R38) and the difference is not recoverable later.
    is_mock: Mapped[bool] = mapped_column(default=True, index=True)
    #: No default, on purpose. See :class:`DraftToolUsage`.
    tool_usage: Mapped[DraftToolUsage] = mapped_column(
        portable_enum(DraftToolUsage, "draft_tool_usage")
    )
    #: The frozen format snapshot. Written once at creation, never updated.
    draft_type: Mapped[DraftType] = mapped_column(portable_enum(DraftType, "draft_type"))
    #: Exact evidence corpus authorising rendered-board observations to enter
    #: the event pipeline. Null means evidence-only, even when source seats are
    #: bound. This is immutable configuration and has no update surface.
    source_board_profile: Mapped[DraftSourceBoardProfile | None] = mapped_column(
        portable_enum(DraftSourceBoardProfile, "draft_source_board_profile")
    )
    team_count: Mapped[int] = mapped_column()
    roster_size: Mapped[int] = mapped_column()
    auction_budget: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    #: Free text from the recorder — site, engagement level, anything the
    #: template asks for that has no column. Never parsed by this unit.
    notes: Mapped[str | None] = mapped_column(Text)

    league: Mapped[League] = relationship()
    participants: Mapped[list[DraftParticipant]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="DraftParticipant.team_slot",
        # `draft_participants` carries two FKs to `drafts.id` — `draft_id` and
        # the owner sentinel — and without this SQLAlchemy cannot tell which
        # one the collection joins on. Same disambiguation, same reason, as
        # `League.scoring_profiles`.
        foreign_keys="DraftParticipant.draft_id",
    )
    events: Mapped[list[DraftEvent]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="DraftEvent.sequence",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Draft {self.name!r} {self.draft_type.value}>"


class DraftParticipant(IntPk, TimestampMixin, Base):
    """One seat in a draft.

    ``team_slot`` is the one-indexed local participant order. Legacy/manual
    ordered drafts also use it as pick order. A draft created with a complete
    ``source_seat`` binding instead resolves the rendered board's ordered
    columns through that frozen mapping; the two ordinals are deliberately
    distinct.

    ``owner_draft_id`` is the nullable-sentinel pattern this codebase already
    uses for ``league_scoring_profiles.active_league_id``: it mirrors
    ``draft_id`` for the owner's own seat and is ``NULL`` for everyone else, so
    a plain unique constraint makes "at most one owner seat per draft" a
    database guarantee rather than an application convention. ``is_owner`` is a
    derived property over it, so there is only one fact to keep consistent.
    """

    __tablename__ = "draft_participants"
    __table_args__ = (
        UniqueConstraint("draft_id", "team_slot", name="uq_draft_participants_draft_slot"),
        UniqueConstraint("owner_draft_id", name="uq_draft_participants_owner_draft_id"),
        Index(
            "uq_draft_participants_draft_source_seat",
            "draft_id",
            "source_seat",
            unique=True,
        ),
        CheckConstraint("team_slot >= 1", name="team_slot_positive"),
        CheckConstraint("source_seat IS NULL OR source_seat >= 1", name="source_seat_positive"),
        CheckConstraint(
            "owner_draft_id IS NULL OR owner_draft_id = draft_id",
            name="owner_sentinel_matches_draft",
        ),
    )

    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id", ondelete="CASCADE"), index=True)
    team_slot: Mapped[int] = mapped_column()
    #: Optional frozen binding from the rendered board's one-indexed column to
    #: this participant. Distinct from ``team_slot``: source column order can be
    #: rotated relative to the local participant order.
    source_seat: Mapped[int | None] = mapped_column()
    display_name: Mapped[str] = mapped_column(String(128))
    #: Set only for the owner's seat. See the class docstring.
    owner_draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id", ondelete="CASCADE"))
    #: Optional link to a real Fantrax team. Absent for a mock against
    #: strangers, which is most of them.
    fantasy_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("fantasy_teams.id", ondelete="SET NULL")
    )

    draft: Mapped[Draft] = relationship(back_populates="participants", foreign_keys=[draft_id])
    fantasy_team: Mapped[FantasyTeam | None] = relationship()

    @property
    def is_owner(self) -> bool:
        return self.owner_draft_id is not None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DraftParticipant slot={self.team_slot} {self.display_name!r}>"


class DraftEvent(IntPk, TimestampMixin, Base):
    """One immutable entry in a draft's log.

    The per-type shape checks below are what stop a half-formed event reaching
    the log through a path that is not the service — a ``bid`` with no amount,
    a ``sale`` with no buyer, a ``void`` that also claims to draft someone.
    They are cheap here because this table is created with them; adding a CHECK
    to an *existing* referenced table is the operation that would rebuild it on
    SQLite and cascade into its dependants (migration 0016).

    ``player_label`` is the name the recorder actually saw, kept verbatim and
    required whenever an event names a player. ``player_id`` is the resolution
    of that name and is nullable, because a mock on a site we do not ingest
    will contain names the crosswalk has never seen, and refusing those would
    lose the pick rather than record it honestly. Resolution can be attached
    later; the raw claim cannot be reconstructed later. The
    ``player_id_requires_label`` constraint makes it impossible to keep the
    resolution while discarding the claim it was resolved from.
    """

    __tablename__ = "draft_events"
    __table_args__ = (
        UniqueConstraint("draft_id", "sequence", name="uq_draft_events_draft_sequence"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint("amount IS NULL OR amount > 0", name="amount_positive"),
        # A void points strictly backwards. Without the second half, an event
        # could supersede itself or something not yet recorded.
        CheckConstraint(
            "supersedes_sequence IS NULL OR supersedes_sequence >= 1",
            name="supersedes_positive",
        ),
        CheckConstraint(
            "supersedes_sequence IS NULL OR supersedes_sequence < sequence",
            name="supersedes_points_backwards",
        ),
        CheckConstraint(
            "player_id IS NULL OR player_label IS NOT NULL",
            name="player_id_requires_label",
        ),
        CheckConstraint(
            "(event_type = 'pick' AND participant_id IS NOT NULL AND player_label IS NOT NULL"
            " AND amount IS NULL AND supersedes_sequence IS NULL)"
            " OR (event_type = 'nomination' AND participant_id IS NOT NULL"
            " AND player_label IS NOT NULL AND supersedes_sequence IS NULL)"
            " OR (event_type = 'bid' AND participant_id IS NOT NULL AND player_id IS NULL"
            " AND player_label IS NULL AND amount IS NOT NULL AND supersedes_sequence IS NULL)"
            " OR (event_type = 'sale' AND participant_id IS NOT NULL AND amount IS NOT NULL"
            " AND supersedes_sequence IS NULL)"
            " OR (event_type = 'void' AND supersedes_sequence IS NOT NULL"
            " AND participant_id IS NULL AND player_id IS NULL AND player_label IS NULL"
            " AND amount IS NULL)"
            " OR (event_type = 'closed' AND participant_id IS NULL AND player_id IS NULL"
            " AND player_label IS NULL AND amount IS NULL AND supersedes_sequence IS NULL)",
            name="event_shape_matches_type",
        ),
    )

    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id", ondelete="CASCADE"), index=True)
    #: One-indexed, contiguous, assigned by the service. The only ordering.
    sequence: Mapped[int] = mapped_column()
    event_type: Mapped[DraftEventType] = mapped_column(
        portable_enum(DraftEventType, "draft_event_type")
    )
    #: ``RESTRICT``: a seat that has recorded events cannot be removed out from
    #: under them. Deleting the draft still cascades to both.
    participant_id: Mapped[int | None] = mapped_column(
        ForeignKey("draft_participants.id", ondelete="RESTRICT"), index=True
    )
    #: ``SET NULL``: if a player row goes, the recorded name survives.
    player_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL"), index=True
    )
    player_label: Mapped[str | None] = mapped_column(String(128))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    supersedes_sequence: Mapped[int | None] = mapped_column()
    #: The recorder's claim about when this happened. Never used for ordering.
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    note: Mapped[str | None] = mapped_column(Text)

    draft: Mapped[Draft] = relationship(back_populates="events")
    participant: Mapped[DraftParticipant | None] = relationship()
    player: Mapped[Player | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DraftEvent #{self.sequence} {self.event_type.value}>"
