"""Market layer: published auction values, and what each one actually is.

``aav-source``, Phase 8, track A. This module stores what somebody else
published, with enough provenance that disagreeing with it six weeks from now
is defensible under a bid clock. It derives nothing.

## Why this is not in ``projection_sources``

The backlog entry for ``aav-source`` says each source should be a row in
``projection_sources``. It predates ADR-008 being accepted, and three
independently checkable things say otherwise:

1. ``ProjectionSource`` carries ``CheckConstraint("source IN ('fantasypros',
   'hashtag', 'basketball_monster', 'darko', 'manual')")``. The publishers that
   actually print NBA auction values — Yahoo, FantraxHQ, RotoWire, ESPN — are
   not in that vocabulary, and most of them publish no projections at all.
   Admitting them would widen a projection-layer constraint to hold
   non-projection publishers.
2. ``ingest/projections/profiles.py`` lists ``aav``, ``auction value`` and
   ``dollar value`` in ``TERMINAL_HEADER_ALIASES`` — the projection parser was
   built to *refuse* to persist this quantity.
3. ADR-008 is Accepted, and ``plan.md`` states it without hedging: "a seeded
   AAV is market evidence, not a valuation input."

So these are separate tables at ``data_layer = 'market'``, following the
``AbsenceSplit.data_layer`` CHECK precedent. Ruled by the coordinator on
2026-08-21 as a boundary decision rather than a preference.

## What this layer is *for*

Not to be improved on. The owner's stated differentiator is not beating the
consensus — most of our numbers should mirror it — it is **explaining and
defending the places we disagree**. That inverts the usual framing of a seed
source: this is the benchmark we will be measured against, player by player,
so what matters is not coverage or freshness but that a single row can be
interrogated, angrily and at speed, and answer with its source, its date, its
scoring basis, its budget basis and what it was derived from.

Hence the row grain is ``(source, player, as-of date)`` and the source's
verbatim published text is kept beside the parsed number.

## The two failures this schema is shaped against

**Circularity manufactures fake agreement and fake disagreement in equal
measure.** Basketball Monster's auction values are a deterministic z-score
transform of the Basketball Monster projections this repository already
imports (``docs/adapters/basketball-monster-projections.md``). Benchmarking
against them would compare us to our own primary input wearing a dollar sign:
every match fake agreement, every divergence measuring the gap between two
valuation formulas rather than a difference of opinion about a player. That is
why lineage is a real table with a real join key
(:class:`AuctionValueSourceInput`) rather than prose in a doc — a doc saying
"beware circularity" is a hope, and ``hoops_gm.market.independence`` is a
mechanism.

**Two incomparable numbers that look comparable.** A $200 budget and a $260
budget produce different dollars for the same player and both look like money;
an 8-category value and a 9-category value are not the same quantity. So every
basis fact is mandatory and non-defaultable, and each carries its own
:class:`BasisEvidence`. Nothing here converts between bases: proportional
scaling and scaling only the surplus above the $1-per-slot reserve give
materially different dollars for the same player, and choosing between them is
a modelling decision that a number then rests on. That is ``auction-values``'s
call under the Model gate. This module's half of R39 is disclosure — making an
unestablished basis refuse to be consumed rather than silently comparable.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hoops_gm.db.base import Base, IntPk, TimestampMixin, UTCDateTime, portable_enum
from hoops_gm.db.models.enums import (
    AuctionValueDerivation,
    AuctionValueInputKind,
    AuctionValueKind,
    BasisEvidence,
    ExternalSource,
    ScoringType,
)

if TYPE_CHECKING:
    from hoops_gm.db.models.identity import Player

#: Every basis field pairs a value column with an evidence column. Named once
#: so the CHECK constraints, the importer and the admissibility rule cannot
#: drift apart about which fields constitute "the basis".
BASIS_FIELDS: tuple[tuple[str, str], ...] = (
    ("basis_budget", "basis_budget_evidence"),
    ("basis_team_count", "basis_team_count_evidence"),
    ("basis_roster_size", "basis_roster_size_evidence"),
    ("basis_scoring_type", "basis_scoring_type_evidence"),
    ("basis_category_count", "basis_category_count_evidence"),
)


def _basis_pairing_constraint(value_column: str, evidence_column: str) -> CheckConstraint:
    """A basis value exists if and only if its evidence is not ``unestablished``.

    Written as an explicit two-armed disjunction rather than a boolean
    equality, because SQLite and Postgres do not agree on comparing boolean
    expressions to each other and this has to mean the same thing on both.

    The point is to make the dangerous state inexpressible rather than merely
    validated: a budget of ``NULL`` recorded as ``stated`` would claim the
    source printed something we do not have, and a budget of ``200`` recorded
    as ``unestablished`` would be a number nobody stands behind.
    """
    return CheckConstraint(
        f"({evidence_column} = 'unestablished' AND {value_column} IS NULL) "
        f"OR ({evidence_column} <> 'unestablished' AND {value_column} IS NOT NULL)",
        name=f"{value_column}_evidence_pairing",
    )


class AuctionValueSource(IntPk, TimestampMixin, Base):
    """A publisher of auction dollar values, and what its numbers actually are.

    One row per publisher. Deliberately keyed by its own ``slug`` rather than
    by :class:`ExternalSource`: that vocabulary names systems that have an
    opinion about *player identity*, and most auction-value publishers do not
    appear in it. Reusing it would have meant widening a crosswalk enum to
    accommodate a market-layer concern.
    """

    __tablename__ = "auction_value_sources"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_auction_value_sources_slug"),
        CheckConstraint("length(slug) > 0", name="slug_not_empty"),
        # An unexamined blank and an investigated "unknown" are different
        # claims, and this project has been bitten repeatedly by the two being
        # indistinguishable. A source whose derivation could not be pinned down
        # is still recordable — as UNESTABLISHED — but it can never be recorded
        # *silently*, because the evidence text has to say where we looked.
        CheckConstraint("length(derivation_evidence) > 0", name="derivation_evidence_not_empty"),
        CheckConstraint("data_layer = 'market'", name="market_layer_only"),
    )

    slug: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    publisher_url: Mapped[str | None] = mapped_column(String(512))

    #: How this publisher turns something into a dollar figure.
    derivation_method: Mapped[AuctionValueDerivation] = mapped_column(
        portable_enum(AuctionValueDerivation, "auction_value_derivation")
    )
    #: What establishes ``derivation_method`` — a quote, a URL, or, for
    #: ``UNESTABLISHED``, the specific things that were checked and did not
    #: answer it. Never empty; see the CHECK above.
    derivation_evidence: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    data_layer: Mapped[str] = mapped_column(String(32), default="market", server_default="market")

    inputs: Mapped[list[AuctionValueSourceInput]] = relationship(
        back_populates="source_row", cascade="all, delete-orphan"
    )
    imports: Mapped[list[AuctionValueImport]] = relationship(
        back_populates="source_row", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AuctionValueSource {self.slug}>"


class AuctionValueSourceInput(IntPk, TimestampMixin, Base):
    """One upstream quantity a publisher's method is known to consume.

    This table is the circularity guard's join key, and it exists as a table
    rather than a JSON blob or a paragraph precisely so the guard can be a
    query. ``our_projection_source`` is the load-bearing column: it is set
    **only** when the upstream is a publisher we ourselves import projections
    from, which is the condition that makes a benchmark an echo.

    A source can legitimately have several rows — RotoWire's published
    methodology names both ADP and its own statistical projections, and those
    are different kinds of input with different independence implications.
    """

    __tablename__ = "auction_value_source_inputs"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "input_kind",
            "input_label",
            name="uq_auction_value_source_inputs_identity",
        ),
        CheckConstraint("length(input_label) > 0", name="input_label_not_empty"),
        CheckConstraint("length(evidence) > 0", name="input_evidence_not_empty"),
        Index("ix_auction_value_source_inputs_ours", "our_projection_source"),
    )

    source_id: Mapped[int] = mapped_column(
        ForeignKey("auction_value_sources.id", ondelete="CASCADE"), index=True
    )
    input_kind: Mapped[AuctionValueInputKind] = mapped_column(
        portable_enum(AuctionValueInputKind, "auction_value_input_kind")
    )
    #: The upstream named as the publisher names it, verbatim where possible
    #: ("Josh Lloyd's projection set", "Fantrax-hosted auction drafts").
    input_label: Mapped[str] = mapped_column(String(256))
    #: Set **only** when this upstream is a projection publisher we also
    #: import from. ``None`` means either "an upstream that is not ours" or
    #: "not one of our projection publishers" — both of which are compatible
    #: with independence. This is not a nullable convenience: it is the whole
    #: circularity test, and ``hoops_gm.market.independence`` reads nothing
    #: else to decide it.
    our_projection_source: Mapped[ExternalSource | None] = mapped_column(
        portable_enum(ExternalSource, "external_source")
    )
    evidence: Mapped[str] = mapped_column(Text)

    source_row: Mapped[AuctionValueSource] = relationship(back_populates="inputs")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AuctionValueSourceInput source={self.source_id} {self.input_kind}>"


class AuctionValueImport(IntPk, TimestampMixin, Base):
    """One captured snapshot of a publisher's price list, at one basis.

    Versioned rather than mutated, like ``projection_imports``: re-importing
    identical content for the same as-of date converges onto the same row, and
    a republished list creates a new one. "What did the market say on the day
    we decided" stays a query.

    ``as_of_date`` is the source's own publication or observation date, not the
    time we happened to read it. It is part of the natural key because a
    publisher revising its list is the normal case in the run-up to a draft,
    and the row grain the owner needs is ``(source, player, as-of date)``.

    **Every basis field is mandatory in the sense that matters**: the column
    may be NULL, but only when its evidence column says ``unestablished``, and
    a row in that state is refused as a benchmark by
    ``hoops_gm.market.independence``. There is no default. A basis that was
    never considered cannot be written.
    """

    __tablename__ = "auction_value_imports"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "season",
            "as_of_date",
            "content_sha256",
            name="uq_auction_value_imports_identity",
        ),
        Index("ix_auction_value_imports_source_season", "source_id", "season"),
        *(_basis_pairing_constraint(value, evidence) for value, evidence in BASIS_FIELDS),
        CheckConstraint("basis_budget IS NULL OR basis_budget > 0", name="basis_budget_positive"),
        CheckConstraint(
            "basis_team_count IS NULL OR basis_team_count > 0", name="basis_team_count_positive"
        ),
        CheckConstraint(
            "basis_roster_size IS NULL OR basis_roster_size > 0", name="basis_roster_size_positive"
        ),
        CheckConstraint(
            "basis_category_count IS NULL OR basis_category_count > 0",
            name="basis_category_count_positive",
        ),
        # An inference the reader cannot reconstruct is an assertion. The
        # FantraxHQ case is the reason: its team count is inferable only
        # because the stated "156 rostered players" decomposes as 12 x 13, and
        # a reader who is not told that cannot disagree with it.
        CheckConstraint(
            "NOT ("
            + " OR ".join(f"{evidence} = 'inferred'" for _, evidence in BASIS_FIELDS)
            + ") OR (basis_note IS NOT NULL AND length(basis_note) > 0)",
            name="inference_requires_a_note",
        ),
        CheckConstraint("row_count >= 0", name="row_count_non_negative"),
        CheckConstraint("matched_count >= 0", name="matched_count_non_negative"),
        CheckConstraint("needs_review_count >= 0", name="needs_review_count_non_negative"),
        CheckConstraint("unmatched_count >= 0", name="unmatched_count_non_negative"),
        CheckConstraint("rejected_count >= 0", name="rejected_count_non_negative"),
    )

    source_id: Mapped[int] = mapped_column(
        ForeignKey("auction_value_sources.id", ondelete="CASCADE"), index=True
    )
    season: Mapped[str] = mapped_column(String(9), index=True)
    #: The publisher's own date for this list. Distinct from ``imported_at``.
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    original_filename: Mapped[str | None] = mapped_column(String(255))

    profile_id: Mapped[str] = mapped_column(String(128))
    profile_version: Mapped[str] = mapped_column(String(64))
    #: Whether the *byte* contract was proven against real source bytes. False
    #: for every source so far and honestly so: no NBA auction-value publisher
    #: found offers a machine-readable export, so the operator transcribes an
    #: HTML table and the header spelling is our convention rather than the
    #: source's contract. What is verified for these sources is their
    #: *semantics* — kind, basis, derivation — which is where the risk lives.
    #: See ``docs/adapters/published-auction-values.md``.
    profile_header_contract_verified: Mapped[bool] = mapped_column(Boolean)
    profile_lineage: Mapped[dict[str, object]] = mapped_column(JSON)

    basis_budget: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    basis_budget_evidence: Mapped[BasisEvidence] = mapped_column(
        portable_enum(BasisEvidence, "basis_budget_evidence")
    )
    basis_team_count: Mapped[int | None] = mapped_column(Integer)
    basis_team_count_evidence: Mapped[BasisEvidence] = mapped_column(
        portable_enum(BasisEvidence, "basis_team_count_evidence")
    )
    basis_roster_size: Mapped[int | None] = mapped_column(Integer)
    basis_roster_size_evidence: Mapped[BasisEvidence] = mapped_column(
        portable_enum(BasisEvidence, "basis_roster_size_evidence")
    )
    basis_scoring_type: Mapped[ScoringType | None] = mapped_column(
        portable_enum(ScoringType, "scoring_type")
    )
    basis_scoring_type_evidence: Mapped[BasisEvidence] = mapped_column(
        portable_enum(BasisEvidence, "basis_scoring_type_evidence")
    )
    #: How many scoring categories the price list was built for.
    #:
    #: :class:`ScoringType` cannot express this — an 8-category value and a
    #: 9-category value are both ``h2h_categories``, are produced by different
    #: arithmetic over a different category set, and are not comparable. This
    #: is the live case rather than a hypothetical one: FantraxHQ states "8
    #: category leagues" on the page, our league is 9-cat, and without this
    #: column the two would have differed only in a free-text note that nothing
    #: could check.
    #:
    #: The count is the mechanically checkable part; ``basis_note`` records
    #: *which* categories, because two different 9-cat sets would also be
    #: incomparable and no integer can catch that.
    basis_category_count: Mapped[int | None] = mapped_column(Integer)
    basis_category_count_evidence: Mapped[BasisEvidence] = mapped_column(
        portable_enum(BasisEvidence, "basis_category_count_evidence")
    )
    #: Mandatory whenever any basis field is ``INFERRED``; see the CHECK.
    basis_note: Mapped[str | None] = mapped_column(Text)

    row_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    needs_review_count: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)

    source_row: Mapped[AuctionValueSource] = relationship(back_populates="imports")
    values: Mapped[list[PublishedAuctionValue]] = relationship(
        back_populates="import_row", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AuctionValueImport source={self.source_id} as_of={self.as_of_date}>"


class PublishedAuctionValue(IntPk, TimestampMixin, Base):
    """One publisher's dollar figure for one player, of one kind, on one date.

    ``value_kind`` is part of the natural key, not an attribute of the source,
    because a single publisher can print both a projected value and an observed
    average for the same player in the same row — Yahoo does. Keying without it
    would silently collapse a model's output and a market observation into
    whichever the importer happened to write second.

    ``value_raw`` keeps the publisher's own text ("$74", "74.0", "$1"). A
    disputed row then resolves without re-fetching a page that may since have
    been revised, and a units error stays visible: "$74" and "74" are the same
    parsed number and different claims about what was published.
    """

    __tablename__ = "published_auction_values"
    __table_args__ = (
        UniqueConstraint(
            "import_id",
            "player_id",
            "value_kind",
            name="uq_published_auction_values_import_player_kind",
        ),
        Index("ix_published_auction_values_player_season", "player_id", "season"),
        Index("ix_published_auction_values_player_as_of", "player_id", "as_of_date"),
        CheckConstraint("value_dollars >= 0", name="value_dollars_non_negative"),
        CheckConstraint("length(value_raw) > 0", name="value_raw_not_empty"),
        CheckConstraint("data_layer = 'market'", name="market_layer_only"),
    )

    import_id: Mapped[int] = mapped_column(
        ForeignKey("auction_value_imports.id", ondelete="CASCADE"), index=True
    )
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    #: Denormalised from the import so the owner's question — "what did source
    #: X say about player Y as of date Z" — is one indexed lookup rather than a
    #: join, the same choice ``Projection`` makes for ``season``.
    season: Mapped[str] = mapped_column(String(9), index=True)
    as_of_date: Mapped[date] = mapped_column(Date)

    value_kind: Mapped[AuctionValueKind] = mapped_column(
        portable_enum(AuctionValueKind, "auction_value_kind")
    )
    #: Numeric rather than float: this is money and it is compared.
    value_dollars: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    #: The publisher's own text for the figure, kept verbatim.
    value_raw: Mapped[str] = mapped_column(String(32))
    #: The publisher's own player identifier where its table exposes one.
    source_player_id: Mapped[str | None] = mapped_column(String(64))
    #: What the source called the player, retained as the evidence behind the
    #: crosswalk match for the same reason ``PlayerExternalId.external_name``
    #: is retained.
    source_player_name: Mapped[str] = mapped_column(String(128))

    data_layer: Mapped[str] = mapped_column(String(32), default="market", server_default="market")

    import_row: Mapped[AuctionValueImport] = relationship(back_populates="values")
    player: Mapped[Player] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<PublishedAuctionValue player={self.player_id} "
            f"{self.value_kind} {self.value_dollars}>"
        )
