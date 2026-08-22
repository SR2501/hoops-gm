"""Published auction-value sources: what they are, and how to read their tables.

Two different things live here, deliberately.

:class:`AuctionSourceDescriptor` records **what a publisher's numbers are** —
the method, and separately the inputs that method consumes. It is the seed data
for ``auction_value_sources`` and ``auction_value_source_inputs``, and it is
what ``hoops_gm.market.independence`` queries. Keeping method and inputs apart
looks redundant until you notice that Hashtag, Basketball Monster, RotoWire and
FantraxHQ all run the same z-score → value-above-replacement → budget-
distribution arithmetic over *independently generated* projections. Their
outputs correlate strongly, and a single "derived from projections" field would
have read that correlation as agreement about players when it is agreement
about arithmetic.

:class:`AuctionValueProfile` records **how to read a file** — which header
means what. Ordinary column mapping.

## Why no profile here is byte-verified, and why that is not the same failure

``ingest/projections/profiles.py`` marks its vendor profiles unverified because
nobody had downloaded the vendor's CSV yet. Here the situation is structurally
different and will not improve: **no NBA auction-value publisher found offers a
machine-readable export at all.** Hashtag, FantraxHQ, Yahoo and RotoWire all
render an HTML table; the operator selects it, and the header spelling that
lands in the CSV is a product of that copy, not a contract the source
publishes. Pinning an exact byte contract would be pinning our own clipboard.

So ``header_contract_verified`` is ``False`` everywhere below and honestly so,
and the profiles match on aliases rather than an exact header sequence. What
*is* verified for these sources is their semantics — what the number means,
what basis it was computed at, what it derives from — which is where the risk
actually lives, and which is recorded per source and per import instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from hoops_gm.db.models.enums import (
    AuctionValueDerivation,
    AuctionValueInputKind,
    AuctionValueKind,
    ExternalSource,
)
from hoops_gm.ingest.projections.profiles import normalize_header, resolve_header

__all__ = [
    "AUCTION_VALUE_PROFILES",
    "AUCTION_VALUE_SOURCES",
    "AuctionSourceDescriptor",
    "AuctionValueProfile",
    "SourceInputDescriptor",
    "ValueColumn",
    "profile_for",
    "resolve_auction_header",
    "source_for",
]


@dataclass(frozen=True)
class ValueColumn:
    """One column of dollar figures, and what kind of claim it makes.

    ``kind`` lives here rather than on the source because a single publisher
    can print both kinds in one table. Yahoo does exactly that, and it is the
    reason ``published_auction_values.value_kind`` is part of the row key.
    """

    kind: AuctionValueKind
    aliases: tuple[str, ...]
    #: What the source calls this column, for error messages and the adapter
    #: page. Not used for matching.
    label: str


@dataclass(frozen=True)
class SourceInputDescriptor:
    """One upstream quantity a publisher's method is known to consume."""

    input_kind: AuctionValueInputKind
    input_label: str
    #: Set **only** when this upstream is a projection publisher we ourselves
    #: import from. That is the entire circularity test — see
    #: ``hoops_gm.market.independence``.
    our_projection_source: ExternalSource | None
    #: Why we believe this. Never empty; the column has a CHECK.
    evidence: str

    def __post_init__(self) -> None:
        if not self.input_label.strip():
            raise ValueError("a source input requires a non-empty label")
        if not self.evidence.strip():
            raise ValueError(
                f"input {self.input_label!r} requires evidence: an unexamined blank and an "
                "investigated 'unknown' are different claims and must not look the same"
            )


@dataclass(frozen=True)
class AuctionSourceDescriptor:
    """A publisher of auction dollar values, and what its numbers actually are."""

    slug: str
    display_name: str
    publisher_url: str | None
    derivation_method: AuctionValueDerivation
    derivation_evidence: str
    inputs: tuple[SourceInputDescriptor, ...] = ()
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.slug.strip():
            raise ValueError("an auction value source requires a non-empty slug")
        if not self.derivation_evidence.strip():
            raise ValueError(f"{self.slug} requires derivation evidence, including for 'unknown'")
        if self.derivation_method is not AuctionValueDerivation.UNESTABLISHED and not self.inputs:
            raise ValueError(
                f"{self.slug} claims a known derivation method but names no inputs; a method "
                "with no recorded inputs cannot be tested for circularity"
            )


@dataclass(frozen=True)
class AuctionValueProfile:
    """A source's table shape: which headers mean what."""

    profile_id: str
    version: str
    source_slug: str
    display_name: str
    value_columns: tuple[ValueColumn, ...]
    name_aliases: tuple[str, ...] = ()
    external_id_aliases: tuple[str, ...] = ()
    team_aliases: tuple[str, ...] = ()
    position_aliases: tuple[str, ...] = ()
    #: Headers the source publishes that this profile deliberately does not
    #: map. Recorded as evidence, never persisted as values: ``Rank`` is a
    #: terminal aggregate under ADR-008 and re-importing it here would smuggle
    #: one in beside the price it is not.
    ignored_source_headers: tuple[str, ...] = ()
    #: Whether the *byte* contract was proven against a real machine-readable
    #: export from the source. ``False`` everywhere; see the module docstring
    #: for why that is a property of these publishers rather than a to-do.
    header_contract_verified: bool = False
    #: What has been established about this source's semantics, and when.
    verification_evidence: str = ""

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.version.strip():
            raise ValueError("auction value profiles require a non-empty identifier and version")
        if not self.value_columns:
            raise ValueError(f"{self.display_name} maps no value column, so it can import nothing")
        if not self.name_aliases:
            raise ValueError(f"{self.display_name} requires a player-name field")
        if not self.verification_evidence.strip():
            raise ValueError(
                f"{self.display_name} requires verification evidence stating what was checked "
                "and what was not"
            )
        seen: set[str] = set()
        for column in self.value_columns:
            for alias in column.aliases:
                normalized = normalize_header(alias)
                if normalized in seen:
                    raise ValueError(
                        f"{self.display_name} maps header {alias!r} to more than one value "
                        "column; one column cannot be two kinds of claim at once"
                    )
                seen.add(normalized)

    def lineage(self) -> dict[str, object]:
        """Immutable record of the mapping this import was read under."""
        return {
            "profile_id": self.profile_id,
            "version": self.version,
            "source_slug": self.source_slug,
            "header_contract_verified": self.header_contract_verified,
            "verification_evidence": self.verification_evidence,
            "value_columns": [
                {"kind": column.kind.value, "label": column.label, "aliases": list(column.aliases)}
                for column in self.value_columns
            ],
            "ignored_source_headers": list(self.ignored_source_headers),
        }


# --------------------------------------------------------------------------
# Source registry
# --------------------------------------------------------------------------

HASHTAG_SOURCE = AuctionSourceDescriptor(
    slug="hashtag_basketball",
    display_name="Hashtag Basketball",
    publisher_url="https://hashtagbasketball.com/fantasy-basketball-auction-values",
    derivation_method=AuctionValueDerivation.Z_SCORE_BUDGET_DISTRIBUTION,
    derivation_evidence=(
        "Established 2026-08-21 from the publisher's own auction-values page, which exposes "
        "budget, team count, roster size and category selection as inputs and recomputes the "
        "dollar column from its own projection set when they change. The page states the "
        "values are generated from Hashtag's projections; a separate points-league page exists, "
        "so the category format of this table is unambiguous rather than assumed."
    ),
    inputs=(
        SourceInputDescriptor(
            input_kind=AuctionValueInputKind.PROJECTIONS,
            input_label="Hashtag Basketball season projections",
            our_projection_source=ExternalSource.HASHTAG,
            evidence=(
                "The auction page recomputes from the same projection set the site publishes "
                "on its projections page. Linked to ExternalSource.HASHTAG deliberately: if we "
                "ever import Hashtag projections, this source stops being independent evidence "
                "and the independence guard will say so."
            ),
        ),
    ),
    notes=(
        "Primary seed. Chosen because its basis is configurable: we can generate at our own "
        "9-category, 12-team, 13-roster, $200 settings and record a STATED basis, rather than "
        "importing at someone else's basis and converting — which would be a modelling act "
        "this unit is not permitted to perform."
    ),
)

YAHOO_SOURCE = AuctionSourceDescriptor(
    slug="yahoo_draft_analysis",
    display_name="Yahoo Fantasy draft analysis",
    publisher_url="https://basketball.fantasysports.yahoo.com/nba/draftanalysis",
    derivation_method=AuctionValueDerivation.OBSERVED_PLATFORM_AUCTIONS,
    derivation_evidence=(
        "The page presents an average auction cost alongside a projected value, described as "
        "drawn from drafts completed on the platform. Established 2026-08-21 that the two "
        "columns are different quantities; NOT established: the draft count behind the "
        "average, the date window, the league-size mix, or what filtering is applied. Those "
        "are recorded per import as UNESTABLISHED rather than left blank."
    ),
    inputs=(
        SourceInputDescriptor(
            input_kind=AuctionValueInputKind.OBSERVED_AUCTIONS,
            input_label="Auction drafts completed on Yahoo Fantasy",
            our_projection_source=None,
            evidence=(
                "The observed column aggregates real drafts on Yahoo's own platform, which is "
                "not a projection source we import. This is the only free source found that "
                "publishes anything genuinely observed rather than modelled."
            ),
        ),
        SourceInputDescriptor(
            input_kind=AuctionValueInputKind.PROJECTIONS,
            input_label="Yahoo's own projected auction value",
            our_projection_source=None,
            evidence=(
                "The same table carries a projected value beside the observed average. We do "
                "not import Yahoo projections, so this input does not make the source "
                "circular — but the two columns are still different claims and are stored as "
                "separate rows with different value_kind."
            ),
        ),
    ),
    notes=(
        "Second seed, for the observed series. Its window and league-size mix are "
        "unestablished, which is recorded rather than papered over: an observed average from "
        "an unknown mix of league sizes is not comparable to a 12-team price without knowing "
        "the mix."
    ),
)

FANTRAXHQ_SOURCE = AuctionSourceDescriptor(
    slug="fantraxhq",
    display_name="FantraxHQ auction values",
    publisher_url="https://fantraxhq.com/2025-26-fantasy-basketball-auction-values/",
    derivation_method=AuctionValueDerivation.EDITORIAL,
    derivation_evidence=(
        "Established 2026-08-21 by reading the article: it is written by a FantraxHQ analyst "
        "from his own projections, and is editorial content published by Fantrax's own media "
        "arm. It is NOT an aggregate of prices paid in Fantrax auctions, which is the natural "
        "assumption from the domain name and is wrong — recorded here because that assumption "
        "would have made this the most valuable source in the set instead of the least."
    ),
    inputs=(
        SourceInputDescriptor(
            input_kind=AuctionValueInputKind.EDITORIAL_JUDGEMENT,
            input_label="FantraxHQ analyst's own projections and judgement",
            our_projection_source=None,
            evidence=(
                "The article attributes the values to the author's projections. No methodology "
                "is published, so the arithmetic behind them could not be established; the "
                "author's projections are not a set we import."
            ),
        ),
    ),
    notes=(
        "8-category, which our 9-category league is not, and the published table's own "
        "arithmetic contradicts the usual $200/12-team assumption: its 156 non-zero rows sum "
        "to $2,655, 10.6% above a 12x$200 pool. Budget is therefore UNESTABLISHED, not $200."
    ),
)

BASKETBALL_MONSTER_SOURCE = AuctionSourceDescriptor(
    slug="basketball_monster",
    display_name="Basketball Monster auction values",
    publisher_url="https://basketballmonster.com/",
    derivation_method=AuctionValueDerivation.Z_SCORE_BUDGET_DISTRIBUTION,
    derivation_evidence=(
        "Basketball Monster's dollar values are a deterministic z-score transform of the "
        "Basketball Monster projections, computed in the same tool from the same rows: change "
        "the projection and the value moves with it. Established 2026-08-21."
    ),
    inputs=(
        SourceInputDescriptor(
            input_kind=AuctionValueInputKind.PROJECTIONS,
            input_label="Basketball Monster season projections",
            our_projection_source=ExternalSource.BASKETBALL_MONSTER,
            evidence=(
                "docs/adapters/basketball-monster-projections.md records a verified paid "
                "export of exactly these projections, already an input to our own blend. The "
                "link is what makes the circularity mechanical rather than a warning in a doc."
            ),
        ),
    ),
    notes=(
        "Registered as a source so the independence guard has something real to refuse, and it "
        "does: with Basketball Monster projections imported, this source is refused as a "
        "benchmark, proved end-to-end through the ordinary projection CSV path.\n"
        "        Note the limit of that claim. There is no basketball_monster *profile*, so no "
        "auction-value file can be imported under this source and no auction_value_imports row "
        "for it can exist in a real database. The refusal is therefore reachable at the source "
        "level — which is where independence is assessed — and not through the import path. "
        "Hashtag is the case that would arise from an ordinary import, and even that awaits a "
        "verified Hashtag projection profile, because import_projection_csv refuses an "
        "unverified profile and only Basketball Monster is verified today.\n"
        "        Not a benchmark regardless: measuring our disagreement against it would "
        "compare us to our own primary projection input with a dollar sign on it, and every "
        "match would be fake agreement."
    ),
)

MANUAL_SOURCE = AuctionSourceDescriptor(
    slug="manual",
    display_name="Manually entered auction values",
    publisher_url=None,
    derivation_method=AuctionValueDerivation.UNESTABLISHED,
    derivation_evidence=(
        "Escape hatch for a list the owner types or pastes from somewhere without a profile. "
        "Its derivation is unestablished by construction — nothing about the file says where "
        "the numbers came from — which is why it carries UNESTABLISHED rather than a guess.\n"
        "        The independence guard refuses it, and the mechanism is worth naming "
        "precisely, because an earlier version of this sentence was false. The guard does not "
        "read derivation_method at all; it reads recorded lineage. This source declares no "
        "inputs, and unrecorded lineage is a refusal rather than a caveat, so manual imports "
        "are stored and displayable but never admissible as independent evidence. Previously "
        "the guard cleared it — the overlap test examined an empty set and found no overlap — "
        "so this paragraph described a refusal that was not happening."
    ),
)

AUCTION_VALUE_SOURCES: tuple[AuctionSourceDescriptor, ...] = (
    HASHTAG_SOURCE,
    YAHOO_SOURCE,
    FANTRAXHQ_SOURCE,
    BASKETBALL_MONSTER_SOURCE,
    MANUAL_SOURCE,
)


# --------------------------------------------------------------------------
# Profiles
# --------------------------------------------------------------------------

FANTRAXHQ_PROFILE = AuctionValueProfile(
    profile_id="fantraxhq-auction-values",
    version="1",
    source_slug=FANTRAXHQ_SOURCE.slug,
    display_name="FantraxHQ auction values",
    name_aliases=("player", "name", "player name"),
    team_aliases=("team", "tm"),
    position_aliases=("position", "pos", "positions"),
    value_columns=(
        ValueColumn(
            kind=AuctionValueKind.PROJECTED,
            aliases=("value", "auction value", "$", "price"),
            label="Value",
        ),
    ),
    ignored_source_headers=("rank",),
    header_contract_verified=False,
    verification_evidence=(
        "Column labels Rank / Player / Team / Position / Value, dollar-prefixed integer values "
        "with no decimals anywhere, 'First Last' names and comma-separated multi-position cells "
        "were read directly from the published page on 2026-08-21, not inherited from a "
        "summary. The page prints 'The prices are optimized for 8-category leagues with 156 "
        "rostered players' and prints no budget anywhere. NOT verified: any machine-readable "
        "export, because none exists — the operator transcribes the HTML table, so the header "
        "spelling in the CSV is our convention and the aliases above are matched loosely on "
        "purpose."
    ),
)

HASHTAG_AUCTION_PROFILE = AuctionValueProfile(
    profile_id="hashtag-auction-values",
    version="1",
    source_slug=HASHTAG_SOURCE.slug,
    display_name="Hashtag Basketball auction values",
    name_aliases=("player", "name", "player name"),
    team_aliases=("team", "tm"),
    position_aliases=("position", "pos", "positions"),
    value_columns=(
        ValueColumn(
            kind=AuctionValueKind.PROJECTED,
            aliases=("value", "auction value", "$", "price", "salary"),
            label="Value",
        ),
    ),
    ignored_source_headers=("rank", "total", "notes"),
    header_contract_verified=False,
    verification_evidence=(
        "Semantics established 2026-08-21 from the publisher's page: the dollar column is "
        "generated from Hashtag's own projections at a basis the reader chooses, and a "
        "separate points-league page exists so this table's category format is stated rather "
        "than assumed. NOT verified: the header text of a transcribed table, and the specific "
        "column labels of any one operator's copy — hence loose aliases. Whoever imports must "
        "record the settings they generated at; the importer refuses to default them."
    ),
)

YAHOO_DRAFT_ANALYSIS_PROFILE = AuctionValueProfile(
    profile_id="yahoo-draft-analysis",
    version="1",
    source_slug=YAHOO_SOURCE.slug,
    display_name="Yahoo Fantasy draft analysis",
    name_aliases=("player", "name", "player name"),
    team_aliases=("team", "tm"),
    position_aliases=("position", "pos", "positions"),
    value_columns=(
        ValueColumn(
            kind=AuctionValueKind.OBSERVED_MARKET,
            aliases=("avg cost", "average cost", "avg auction cost", "avg salary"),
            label="Avg Cost",
        ),
        ValueColumn(
            kind=AuctionValueKind.PROJECTED,
            aliases=("proj cost", "projected cost", "projected value", "auction value"),
            label="Proj Cost",
        ),
    ),
    ignored_source_headers=("rank", "adp", "avg pick", "% drafted", "pct drafted"),
    header_contract_verified=False,
    verification_evidence=(
        "Semantics established 2026-08-21: the page presents an observed average auction cost "
        "and a projected value as two columns of the same table. This profile is the "
        "structural demonstration that value_kind belongs to the value and not to the "
        "publisher — one file row here produces two rows of different kind. NOT verified: any "
        "byte contract (the page is login-gated and must not be scraped), the draft count, the "
        "date window, or the league-size mix behind the observed column."
    ),
)

MANUAL_AUCTION_PROFILE = AuctionValueProfile(
    profile_id="manual-auction-values",
    version="1",
    source_slug=MANUAL_SOURCE.slug,
    display_name="Manually entered auction values",
    name_aliases=("player", "name", "player name"),
    external_id_aliases=("id", "player id", "source id"),
    team_aliases=("team", "tm"),
    position_aliases=("position", "pos", "positions"),
    value_columns=(
        ValueColumn(
            kind=AuctionValueKind.PROJECTED,
            aliases=("value", "auction value", "$", "price", "aav"),
            label="Value",
        ),
    ),
    ignored_source_headers=("rank", "notes"),
    header_contract_verified=False,
    verification_evidence=(
        "Owner-controlled schema, so its column meanings are ours by definition and there is "
        "no external contract to verify. Everything about where the numbers came from is "
        "unestablished, which is what its source descriptor records."
    ),
)

AUCTION_VALUE_PROFILES: tuple[AuctionValueProfile, ...] = (
    HASHTAG_AUCTION_PROFILE,
    YAHOO_DRAFT_ANALYSIS_PROFILE,
    FANTRAXHQ_PROFILE,
    MANUAL_AUCTION_PROFILE,
)

_PROFILES_BY_ID: dict[str, AuctionValueProfile] = {
    profile.profile_id: profile for profile in AUCTION_VALUE_PROFILES
}
_SOURCES_BY_SLUG: dict[str, AuctionSourceDescriptor] = {
    source.slug: source for source in AUCTION_VALUE_SOURCES
}


def profile_for(profile_id: str) -> AuctionValueProfile:
    """The profile registered under ``profile_id``."""
    try:
        return _PROFILES_BY_ID[profile_id]
    except KeyError:
        known = ", ".join(sorted(_PROFILES_BY_ID))
        raise KeyError(f"unknown auction value profile {profile_id!r}; known: {known}") from None


def source_for(slug: str) -> AuctionSourceDescriptor:
    """The source descriptor registered under ``slug``."""
    try:
        return _SOURCES_BY_SLUG[slug]
    except KeyError:
        known = ", ".join(sorted(_SOURCES_BY_SLUG))
        raise KeyError(f"unknown auction value source {slug!r}; known: {known}") from None


def _validate_registry() -> None:
    """Every profile must name a registered source. Checked at import time.

    A profile pointing at a slug with no descriptor would import values whose
    derivation nothing records — the precise state this module exists to make
    impossible — and it would do so silently, at the moment of import, in front
    of nobody.
    """
    if not AUCTION_VALUE_PROFILES:
        raise RuntimeError("the auction value profile registry is empty")
    if not AUCTION_VALUE_SOURCES:
        raise RuntimeError("the auction value source registry is empty")
    for profile in AUCTION_VALUE_PROFILES:
        if profile.source_slug not in _SOURCES_BY_SLUG:
            raise RuntimeError(
                f"profile {profile.profile_id!r} names unregistered source {profile.source_slug!r}"
            )


_validate_registry()


def resolve_auction_header(fieldnames: list[str], aliases: tuple[str, ...]) -> str | None:
    """The first actual header matching any alias, or ``None``.

    Shares ``ingest.projections.profiles.resolve_header`` on purpose: folding
    header case, spacing and punctuation is a text concern rather than a layer
    concern, and an operator's spelling variance should behave identically in
    both importers. No data crosses between the layers by doing this.
    """
    return resolve_header(fieldnames, aliases)
