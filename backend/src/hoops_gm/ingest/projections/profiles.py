"""Per-source column-mapping profiles for the projection CSV importer.

A profile states, once, how one source's CSV maps onto the canonical fields
the parser produces. Nothing here talks to a database or a network — profiles
are data, and the parser that reads them is a pure function, so both stay
testable offline (the same reason ``ingest/nba/parsers.py`` never imports
SQLAlchemy).

FantasyPros remains an unverified parse-preview example. The other three profiles
are verified to *different strengths*, and :class:`VerificationStrength` puts that
distinction in the **value** rather than in prose. It used to live only in prose:
``verified=True`` meant "hash-pinned to an immutable file" for Basketball Monster
and "observed against a live page" for Hashtag, and a consumer reading the field
could not tell which. That is the ``gameEt`` shape — a self-describing value that
is well-formed, type-correct and quietly means two things — so the strength is now
a value a consumer can compare, and ``verified`` is *derived* from it. There is no
way to obtain the strong form by accident, because there is no way to be verified
without naming which kind of verification you mean.

Only evidence hashes and exact structural contracts live here; paid rows and
private paths never enter the repository.

Both vendor profiles intentionally accept one exact header sequence rather than
layering guessed aliases over a proven contract.

``MANUAL_PROFILE`` carries no such uncertainty: it expects the canonical field
names directly (a spreadsheet the owner builds or converts by hand), and is
the profile to reach for whenever a vendor mapping has not been confirmed.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from hoops_gm.db.models.enums import ExternalSource

__all__ = [
    "BASKETBALL_MONSTER_2026_27_HEADERS",
    "BASKETBALL_MONSTER_PROFILE",
    "CANONICAL_STAT_FIELDS",
    "FANTASYPROS_PROFILE",
    "HASHTAG_2026_27_HEADERS",
    "HASHTAG_PROFILE",
    "MANUAL_PROFILE",
    "PROFILES_BY_SOURCE",
    "PROJECTION_IMPORT_SOURCES",
    "TERMINAL_HEADER_ALIASES",
    "ColumnProfile",
    "CompositeShootingColumn",
    "DerivedStatColumn",
    "StatColumn",
    "ValueShape",
    "VerificationStrength",
    "normalize_header",
    "resolve_header",
]


class ValueShape(StrEnum):
    """Whether a numeric column already reports a per-game rate or a season total.

    Treating a season total as a per-game rate (or the reverse) is silently
    wrong by exactly the games-played factor ADR-002 exists to keep visible.
    The profile states which shape a column is in once, rather than leaving
    it to be rediscovered — or missed — per source at parse time.
    """

    PER_GAME = "per_game"
    SEASON_TOTAL = "season_total"


@dataclass(frozen=True)
class StatColumn:
    """One canonical stat, and where to find it in a specific source's CSV."""

    #: Canonical field name — one of :data:`CANONICAL_STAT_FIELDS`.
    field: str
    #: Candidate header spellings, tried in order. Matching is
    #: case-insensitive and tolerant of surrounding whitespace and
    #: underscore/space variance (:func:`normalize_header`).
    aliases: tuple[str, ...]
    #: Explicit source unit. There is deliberately no default: an ambiguous
    #: header such as ``PTS`` cannot become a per-game rate by omission.
    shape: ValueShape


@dataclass(frozen=True)
class DerivedStatColumn:
    """A canonical rate derived from already-normalised canonical rates."""

    field: str
    #: ``(canonical input field, coefficient)`` terms in a linear combination.
    terms: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class CompositeShootingColumn:
    """One source column carrying a percentage *and* its makes/attempts.

    Hashtag Basketball renders a shooting category as a single cell —
    ``0.573 (10.5/18.3)`` — so the volume that makes a percentage category
    weightable is present, but nested inside the column that looks like a
    bare percentage. Read as a percentage the cell is a dead end; read as a
    composite it yields both canonical volume fields.

    This exists because the alternative is the single most common bug in
    homebrew fantasy tools (``AGENTS.md``): treating FG%/FT% as a rate and
    pricing a 90%-on-one-attempt shooter identically to a 90%-on-eight.
    Before this type, ``HASHTAG_PROFILE`` routed both of its shooting columns
    through :attr:`ColumnProfile.percentage_fallback_aliases`, whose whole
    meaning is "the source published no volume" — a true statement about the
    *header* and a false one about the *cell*.

    ``stated_percentage`` is never imported as a rate. It is retained only so
    the parser can reconcile it against ``made / attempted`` and fail loudly
    when a paste has been mangled, which is the one independent check this
    format affords.
    """

    made_field: str
    attempted_field: str
    aliases: tuple[str, ...]
    shape: ValueShape
    #: Human label used in issue messages ("field goal", "free throw").
    label: str


class VerificationStrength(StrEnum):
    """*How* a profile was checked, not merely *whether* it was.

    ``verified: bool`` answered the second question and was routinely read as
    answering the first. Basketball Monster's ``True`` is pinned to the sha256
    of an immutable file; Hashtag's ``True`` is an observation of a live page
    that can change tomorrow. One name, two guarantees, and a downstream
    consumer that wanted only the strong one had to encode that preference as a
    comment. It is now expressible as a comparison.

    The three members are not a ranking with a single axis. They differ in
    *what could go wrong next*, which is the only property a consumer can act
    on.
    """

    #: Pinned to the hash of an immutable artifact the owner holds. Excludes
    #: silent vendor drift: if the file changes, the hash stops matching and
    #: the mismatch is mechanical.
    #:
    #: It does **not** exclude the file having been wrong when it was hashed.
    #: A hash proves the bytes have not moved, never that they were ever right.
    HASH_PINNED = "hash_pinned"

    #: Observed against a live source that publishes no artifact to pin.
    #: Excludes the profile having been written from a *guess* about the
    #: source's shape - the contract was read off the real thing.
    #:
    #: It does **not** exclude drift after the observation date, because there
    #: is nothing to re-hash. Only a live smoke test can notice, so a profile
    #: at this strength without one is asserting a date, not a contract.
    LIVE_CONTRACT_OBSERVED = "live_contract_observed"

    #: The schema is defined by this repository rather than observed from a
    #: vendor, so its units are a decision and not a reading. Excludes the
    #: whole class of unit-misinterpretation defects by construction: there is
    #: no external party whose meaning could differ from ours.
    #:
    #: It does **not** exclude the *file the owner hands us* disagreeing with
    #: the schema. It verifies the contract we publish, not the data pasted
    #: into it.
    OWNER_DEFINED_SCHEMA = "owner_defined_schema"


#: Every per-game rate field a projection row can carry. Mirrors the columns
#: on ``db.models.projections.Projection`` exactly; ``test_projections.py``
#: asserts the two stay in step, the same discipline
#: ``stats.BOX_SCORE_STAT_KEYS`` uses for the box-score schema.
CANONICAL_STAT_FIELDS: tuple[str, ...] = (
    "minutes_per_game",
    "points_per_game",
    "offensive_rebounds_per_game",
    "defensive_rebounds_per_game",
    "rebounds_per_game",
    "assists_per_game",
    "steals_per_game",
    "blocks_per_game",
    "turnovers_per_game",
    "personal_fouls_per_game",
    "field_goals_made_per_game",
    "field_goals_attempted_per_game",
    "three_pointers_made_per_game",
    "three_pointers_attempted_per_game",
    "free_throws_made_per_game",
    "free_throws_attempted_per_game",
)

#: Made/attempted pairs whose *only* legitimate source is volume, never a
#: percentage. Used by the parser to decide when a percentage-only column is
#: a dead end worth a warning rather than a silent gap.
SHOOTING_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("field_goals_made_per_game", "field_goals_attempted_per_game", "field goal"),
    ("three_pointers_made_per_game", "three_pointers_attempted_per_game", "three-point"),
    ("free_throws_made_per_game", "free_throws_attempted_per_game", "free throw"),
)

#: Terminal or already-fused quantities forbidden by accepted ADR-008. A source
#: may place these beside legitimate per-game rates, but the parser records
#: their headers only as ignored evidence and never maps or persists the values
#: as projection-layer inputs.
TERMINAL_HEADER_ALIASES: tuple[str, ...] = (
    "rank",
    "ranking",
    "r#",
    "overall rank",
    "ros rank",
    "rest of season rank",
    "tier",
    "adp",
    "average draft position",
    "aav",
    "auction value",
    "dollar value",
    "composite",
    "composite value",
    "fantasy value",
    "total",
    "expected games",
    "expected_games",
)

PROJECTION_IMPORT_SOURCES: frozenset[ExternalSource] = frozenset(
    {
        ExternalSource.FANTASYPROS,
        ExternalSource.HASHTAG,
        ExternalSource.BASKETBALL_MONSTER,
        ExternalSource.DARKO,
        ExternalSource.MANUAL,
    }
)


@dataclass(frozen=True)
class ColumnProfile:
    """A source's CSV shape: which headers mean what, and how they're scaled."""

    profile_id: str
    version: str
    source: ExternalSource
    display_name: str
    name_aliases: tuple[str, ...] = ()
    external_id_aliases: tuple[str, ...] = ()
    first_name_aliases: tuple[str, ...] = ()
    last_name_aliases: tuple[str, ...] = ()
    team_aliases: tuple[str, ...] = ()
    position_aliases: tuple[str, ...] = ()
    games_played_aliases: tuple[str, ...] = ()
    stat_columns: tuple[StatColumn, ...] = field(default_factory=tuple)
    derived_stat_columns: tuple[DerivedStatColumn, ...] = field(default_factory=tuple)
    #: Source columns carrying ``percentage (makes/attempts)`` in one cell.
    #: Each supplies two canonical volume fields; see
    #: :class:`CompositeShootingColumn`.
    composite_shooting_columns: tuple[CompositeShootingColumn, ...] = field(default_factory=tuple)
    #: Canonical production fields whose headers form this source profile's
    #: minimum schema signature. Vendor exports must expose all of them; the
    #: generic manual profile instead accepts any one recognized production
    #: field.
    required_production_fields: tuple[str, ...] = ()
    #: Percentage-only fallback headers, keyed by the made-field they cannot
    #: substitute for (e.g. ``"field_goals_made_per_game"`` ->
    #: ``("fg%", "fg pct")``). Present only so the parser can recognise "the
    #: source gave a percentage, not volume" and warn rather than silently
    #: import nothing with no explanation.
    percentage_fallback_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: Exact source header sequence when evidence proves a closed CSV contract.
    #: Empty for looser/manual profiles.
    expected_headers: tuple[str, ...] = ()
    #: Source fields deliberately excluded from projection quantities.
    ignored_source_headers: tuple[str, ...] = ()
    #: How this mapping was checked, or ``None`` if it has not been. Naming a
    #: strength is the *only* way to be verified: there is no boolean to set,
    #: so the strong form cannot be reached by accident or by default.
    verification: VerificationStrength | None = None
    #: Exact seasons covered by the evidence. ``"*"`` is reserved for the
    #: owner-controlled canonical manual schema, whose units are encoded in its
    #: column names rather than inferred from an external export.
    verified_seasons: tuple[str, ...] = ()
    verification_evidence: str | None = None

    @property
    def verified(self) -> bool:
        """Whether this profile may import production at *any* strength.

        Derived, never stored. The gate that gates importing legitimately
        accepts all three strengths, so it wants this question; a consumer
        deciding how much to *trust* a number wants :attr:`verification` and
        should not be able to get here by mistake.
        """
        return self.verification is not None

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.version.strip():
            raise ValueError("projection profiles require a non-empty identifier and version")
        if not self.name_aliases and not (self.first_name_aliases and self.last_name_aliases):
            raise ValueError(
                f"{self.display_name} requires a full-name field or both first/last-name fields"
            )
        if self.source not in PROJECTION_IMPORT_SOURCES:
            raise ValueError(
                f"{self.source.value} is not an isolated projection-provider namespace"
            )
        if self.verification is not None and (
            not self.verified_seasons
            or not self.verification_evidence
            or not self.verification_evidence.strip()
        ):
            raise ValueError(
                f"{self.display_name} marks itself verified without season scope and evidence"
            )
        if self.verification is None and self.verified_seasons:
            raise ValueError(
                f"{self.display_name} declares verified seasons without a verification strength"
            )
        if (
            self.verification is VerificationStrength.OWNER_DEFINED_SCHEMA
            and self.source is not ExternalSource.MANUAL
        ):
            raise ValueError(
                f"{self.display_name} claims an owner-defined schema for external source "
                f"{self.source.value}; a vendor's shape is observed, never defined here"
            )
        if "*" in self.verified_seasons and not (
            self.source is ExternalSource.MANUAL and self.profile_id == "manual-canonical"
        ):
            raise ValueError(
                "wildcard season verification is reserved for the manual-canonical profile"
            )

        terminal_aliases = {normalize_header(alias) for alias in TERMINAL_HEADER_ALIASES}
        mapped_aliases = {
            "player name": self.name_aliases,
            "source player id": self.external_id_aliases,
            "player first name": self.first_name_aliases,
            "player last name": self.last_name_aliases,
            "team": self.team_aliases,
            "position": self.position_aliases,
            "games played": self.games_played_aliases,
        }
        mapped_aliases.update(
            {f"production field {column.field}": column.aliases for column in self.stat_columns}
        )
        mapped_aliases.update(
            {
                f"composite shooting {column.made_field}": column.aliases
                for column in self.composite_shooting_columns
            }
        )
        mapped_aliases.update(
            {
                f"percentage fallback {field}": aliases
                for field, aliases in self.percentage_fallback_aliases.items()
            }
        )
        for role, aliases in mapped_aliases.items():
            forbidden = [alias for alias in aliases if normalize_header(alias) in terminal_aliases]
            if forbidden:
                raise ValueError(
                    f"{self.display_name} profile maps terminal columns {forbidden} "
                    f"as {role}; ADR-008 permits terminal columns only as ignored evidence"
                )

        fields = [column.field for column in self.stat_columns]
        composite_fields: list[str] = []
        known_pairs = {(made, attempted) for made, attempted, _ in SHOOTING_PAIRS}
        for composite in self.composite_shooting_columns:
            if (composite.made_field, composite.attempted_field) not in known_pairs:
                raise ValueError(
                    f"{self.display_name} declares composite shooting column "
                    f"{composite.made_field}/{composite.attempted_field}, which is not a "
                    "recognised makes/attempts pair"
                )
            composite_fields.extend((composite.made_field, composite.attempted_field))
        if len(composite_fields) != len(set(composite_fields)):
            raise ValueError(
                f"{self.display_name} profile decomposes a production field more than once"
            )
        composite_overlap = set(fields) & set(composite_fields)
        if composite_overlap:
            raise ValueError(
                f"{self.display_name} profile both maps and decomposes production fields: "
                f"{composite_overlap}"
            )
        # A composite column *supplies* the volume that a percentage fallback
        # declares missing. Declaring both for one field would mean the profile
        # asserts the source did and did not publish volume for the same
        # category, and the parser would have to pick — so it is refused here.
        fallback_conflict = set(self.percentage_fallback_aliases) & set(composite_fields)
        if fallback_conflict:
            raise ValueError(
                f"{self.display_name} declares {fallback_conflict} as both a composite "
                "shooting column and a percentage-only fallback"
            )
        fields.extend(composite_fields)
        if len(fields) != len(set(fields)):
            raise ValueError(f"{self.display_name} profile maps a production field more than once")
        derived_fields = [column.field for column in self.derived_stat_columns]
        if len(derived_fields) != len(set(derived_fields)):
            raise ValueError(
                f"{self.display_name} profile derives a production field more than once"
            )
        overlap = set(fields) & set(derived_fields)
        if overlap:
            raise ValueError(
                f"{self.display_name} profile both maps and derives production fields: {overlap}"
            )
        unknown = (set(fields) | set(derived_fields)) - set(CANONICAL_STAT_FIELDS)
        if unknown:
            raise ValueError(
                f"{self.display_name} profile maps unknown production fields: {unknown}"
            )
        missing = set(self.required_production_fields) - (set(fields) | set(derived_fields))
        if missing:
            raise ValueError(
                f"{self.display_name} profile requires fields it does not map: {missing}"
            )
        for derived in self.derived_stat_columns:
            if not derived.terms:
                raise ValueError(
                    f"{self.display_name} derived field {derived.field} has no input terms"
                )
            unknown_inputs = {term_field for term_field, _ in derived.terms} - set(fields)
            if unknown_inputs:
                raise ValueError(
                    f"{self.display_name} derives {derived.field} from unmapped fields: "
                    f"{unknown_inputs}"
                )
            if any(not math.isfinite(coefficient) for _, coefficient in derived.terms):
                raise ValueError(
                    f"{self.display_name} derives {derived.field} with a non-finite coefficient"
                )

        if self.expected_headers:
            if len(self.expected_headers) != len(set(self.expected_headers)):
                raise ValueError(f"{self.display_name} exact header contract contains duplicates")
            normalized_expected = [normalize_header(header) for header in self.expected_headers]
            if len(normalized_expected) != len(set(normalized_expected)):
                raise ValueError(
                    f"{self.display_name} exact header contract collides after normalization"
                )
            expected = list(self.expected_headers)
            unresolved_roles = [
                role
                for role, aliases in mapped_aliases.items()
                if aliases and resolve_header(expected, aliases) is None
            ]
            if unresolved_roles:
                raise ValueError(
                    f"{self.display_name} exact header contract omits mapped roles: "
                    f"{unresolved_roles}"
                )
            absent_ignored = [
                header
                for header in self.ignored_source_headers
                if header not in self.expected_headers
            ]
            if absent_ignored:
                raise ValueError(
                    f"{self.display_name} ignores headers absent from its exact contract: "
                    f"{absent_ignored}"
                )

        mapped_normalized = {
            normalize_header(alias) for aliases in mapped_aliases.values() for alias in aliases
        }
        ignored_overlap = [
            header
            for header in self.ignored_source_headers
            if normalize_header(header) in mapped_normalized
        ]
        if ignored_overlap:
            raise ValueError(
                f"{self.display_name} both maps and ignores source headers: {ignored_overlap}"
            )


_WS_OR_UNDERSCORE = re.compile(r"[\s_]+")
_NON_ALNUM = re.compile(r"[^a-z0-9%]+")


def normalize_header(value: str) -> str:
    """Fold header spelling variance: case, whitespace, underscores, punctuation.

    ``%`` is kept — it is the one character that changes a header's meaning
    outright ("FG" versus "FG%"), so folding it away would make the
    percentage-fallback detection blind to the exact distinction it exists to
    catch.
    """
    lowered = value.strip().lower()
    collapsed = _WS_OR_UNDERSCORE.sub(" ", lowered)
    return _NON_ALNUM.sub("", collapsed.replace(" ", ""))


def resolve_header(fieldnames: list[str], aliases: tuple[str, ...]) -> str | None:
    """The first actual CSV header matching any alias, or ``None``."""
    if not aliases:
        return None
    normalized_fields = {normalize_header(name): name for name in fieldnames}
    for alias in aliases:
        match = normalized_fields.get(normalize_header(alias))
        if match is not None:
            return match
    return None


# --------------------------------------------------------------------------
# Built-in profiles
# --------------------------------------------------------------------------

MANUAL_PROFILE = ColumnProfile(
    profile_id="manual-canonical",
    version="2",
    source=ExternalSource.MANUAL,
    display_name="Manual / generic",
    name_aliases=("player_name", "player", "name"),
    team_aliases=("team",),
    position_aliases=("position", "pos"),
    games_played_aliases=("games_played", "gp"),
    stat_columns=tuple(
        StatColumn(field=canonical, aliases=(canonical,), shape=ValueShape.PER_GAME)
        for canonical in CANONICAL_STAT_FIELDS
    ),
    verification=VerificationStrength.OWNER_DEFINED_SCHEMA,
    verified_seasons=("*",),
    verification_evidence=(
        "owner-controlled hoops-gm canonical schema v1; per-game units are explicit in headers. "
        "This is not an observation of anything external: the schema is defined here, so there "
        "is no vendor whose meaning could drift from ours. It says nothing about whether a "
        "given hand-built file actually conforms."
    ),
)

FANTASYPROS_PROFILE = ColumnProfile(
    profile_id="fantasypros-unverified-example",
    version="2",
    source=ExternalSource.FANTASYPROS,
    display_name="FantasyPros",
    name_aliases=("player", "player name"),
    team_aliases=("team",),
    position_aliases=("pos", "position"),
    games_played_aliases=("gp", "games played"),
    stat_columns=(
        StatColumn("minutes_per_game", ("min", "mpg", "minutes"), ValueShape.PER_GAME),
        StatColumn("points_per_game", ("pts",), ValueShape.PER_GAME),
        StatColumn("rebounds_per_game", ("treb", "reb", "rebounds"), ValueShape.PER_GAME),
        StatColumn("assists_per_game", ("ast",), ValueShape.PER_GAME),
        StatColumn("steals_per_game", ("st", "stl"), ValueShape.PER_GAME),
        StatColumn("blocks_per_game", ("blk",), ValueShape.PER_GAME),
        StatColumn("turnovers_per_game", ("to", "tov"), ValueShape.PER_GAME),
        StatColumn("three_pointers_made_per_game", ("3pm",), ValueShape.PER_GAME),
    ),
    required_production_fields=(
        "points_per_game",
        "rebounds_per_game",
        "assists_per_game",
    ),
    # FantasyPros' free 9-cat export publishes FG%/FT% without makes or
    # attempts, so those two categories cannot be volume-weighted from it —
    # the parser reports this rather than treating the percentage as a rate.
    percentage_fallback_aliases={
        "field_goals_made_per_game": ("fg%", "fg pct"),
        "free_throws_made_per_game": ("ft%", "ft pct"),
    },
    # Deliberately no ``verification``: this profile is a parse-preview example
    # whose aliases were guessed, never read off a real FantasyPros export.
)

#: The exact header sequence Hashtag Basketball's projections table renders in
#: its **default** configuration, observed live on 2026-08-26.
#:
#: This is pinned exactly, and the reason is the opposite of the usual one.
#: Hashtag's column set is not a vendor contract at all — it is *browser state*.
#: The page carries 16 category checkboxes and a ``DDRANK`` selector; the
#: default checked set is exactly the nine categories below, but ``CBFGM``,
#: ``CBFTM``, ``CBOREB``, ``CBDREB``, ``CB3PP``, ``CBATO`` and ``CBDD`` are all
#: available and unchecked. A copy-paste carries the *values* and none of the
#: configuration that produced them.
#:
#: So an exact pin is the only honest contract: a paste taken under a different
#: configuration is refused loudly rather than mapped on a best-effort basis
#: into a projection that silently means something else.
HASHTAG_2026_27_HEADERS: tuple[str, ...] = (
    "R#",
    "PLAYER",
    "ADP",
    "POS",
    "TEAM",
    "GP",
    "MPG",
    "FG%",
    "FT%",
    "3PM",
    "PTS",
    "TREB",
    "AST",
    "STL",
    "BLK",
    "TO",
    "TOTAL",
)

HASHTAG_PROFILE = ColumnProfile(
    profile_id="hashtag-2026-27",
    version="3",
    source=ExternalSource.HASHTAG,
    display_name="Hashtag Basketball 2026-27",
    name_aliases=("player",),
    team_aliases=("team",),
    position_aliases=("pos",),
    games_played_aliases=("gp",),
    stat_columns=(
        StatColumn("minutes_per_game", ("mpg",), ValueShape.PER_GAME),
        StatColumn("points_per_game", ("pts",), ValueShape.PER_GAME),
        StatColumn("rebounds_per_game", ("treb",), ValueShape.PER_GAME),
        StatColumn("assists_per_game", ("ast",), ValueShape.PER_GAME),
        StatColumn("steals_per_game", ("stl",), ValueShape.PER_GAME),
        StatColumn("blocks_per_game", ("blk",), ValueShape.PER_GAME),
        StatColumn("turnovers_per_game", ("to",), ValueShape.PER_GAME),
        StatColumn("three_pointers_made_per_game", ("3pm",), ValueShape.PER_GAME),
    ),
    # FG% and FT% cells read "0.573 (10.5/18.3)": the volume is present, nested
    # inside the percentage column. Version 1 of this profile declared both as
    # percentage-only fallbacks and therefore discarded every shooting volume
    # the source publishes.
    composite_shooting_columns=(
        CompositeShootingColumn(
            made_field="field_goals_made_per_game",
            attempted_field="field_goals_attempted_per_game",
            aliases=("fg%",),
            shape=ValueShape.PER_GAME,
            label="field goal",
        ),
        CompositeShootingColumn(
            made_field="free_throws_made_per_game",
            attempted_field="free_throws_attempted_per_game",
            aliases=("ft%",),
            shape=ValueShape.PER_GAME,
            label="free throw",
        ),
    ),
    required_production_fields=(
        "points_per_game",
        "rebounds_per_game",
        "assists_per_game",
        "steals_per_game",
        "blocks_per_game",
        "turnovers_per_game",
        "three_pointers_made_per_game",
        "field_goals_made_per_game",
        "field_goals_attempted_per_game",
        "free_throws_made_per_game",
        "free_throws_attempted_per_game",
    ),
    expected_headers=HASHTAG_2026_27_HEADERS,
    verification=VerificationStrength.LIVE_CONTRACT_OBSERVED,
    verified_seasons=("2026-27",),
    verification_evidence=(
        "live-page contract observed 2026-08-26 at "
        "hashtagbasketball.com/fantasy-basketball-projections: 17-header default "
        "configuration, composite 'pct (makes/attempts)' shooting cells, and 429 of "
        "429 rows reconciling on FG%=FGM/FGA, FT%=FTM/FTA and PTS=2*FGM+3PM+FTM "
        "within display-rounding bounds. The source publishes no export, so there is "
        "no artifact to hash and nothing can detect drift after this date except the "
        "live smoke test in tests/test_live_smoke.py."
    ),
)

BASKETBALL_MONSTER_2026_27_HEADERS: tuple[str, ...] = (
    "player_id",
    "last_name",
    "first_name",
    "games",
    "minutes",
    "field_goals_attempted",
    "field_goals",
    "free_throws_attempted",
    "free_throws",
    "threes",
    "threes_attempted",
    "offensive_rebounds",
    "defensive_rebounds",
    "assists",
    "blocks",
    "steals",
    "turnovers",
    "fouls",
    "technicals",
    "double_doubles",
    "triple_doubles",
    "comments",
)

BASKETBALL_MONSTER_PROFILE = ColumnProfile(
    profile_id="basketball-monster-2026-27",
    version="2",
    source=ExternalSource.BASKETBALL_MONSTER,
    display_name="Basketball Monster 2026-27",
    external_id_aliases=("player_id",),
    first_name_aliases=("first_name",),
    last_name_aliases=("last_name",),
    games_played_aliases=("games",),
    stat_columns=(
        StatColumn("minutes_per_game", ("minutes",), ValueShape.SEASON_TOTAL),
        StatColumn(
            "field_goals_attempted_per_game",
            ("field_goals_attempted",),
            ValueShape.SEASON_TOTAL,
        ),
        StatColumn("field_goals_made_per_game", ("field_goals",), ValueShape.SEASON_TOTAL),
        StatColumn(
            "free_throws_attempted_per_game",
            ("free_throws_attempted",),
            ValueShape.SEASON_TOTAL,
        ),
        StatColumn("free_throws_made_per_game", ("free_throws",), ValueShape.SEASON_TOTAL),
        StatColumn("three_pointers_made_per_game", ("threes",), ValueShape.SEASON_TOTAL),
        StatColumn(
            "three_pointers_attempted_per_game",
            ("threes_attempted",),
            ValueShape.SEASON_TOTAL,
        ),
        StatColumn(
            "offensive_rebounds_per_game",
            ("offensive_rebounds",),
            ValueShape.SEASON_TOTAL,
        ),
        StatColumn(
            "defensive_rebounds_per_game",
            ("defensive_rebounds",),
            ValueShape.SEASON_TOTAL,
        ),
        StatColumn("assists_per_game", ("assists",), ValueShape.SEASON_TOTAL),
        StatColumn("blocks_per_game", ("blocks",), ValueShape.SEASON_TOTAL),
        StatColumn("steals_per_game", ("steals",), ValueShape.SEASON_TOTAL),
        StatColumn("turnovers_per_game", ("turnovers",), ValueShape.SEASON_TOTAL),
        StatColumn("personal_fouls_per_game", ("fouls",), ValueShape.SEASON_TOTAL),
    ),
    derived_stat_columns=(
        DerivedStatColumn(
            "points_per_game",
            (
                ("field_goals_made_per_game", 2.0),
                ("three_pointers_made_per_game", 1.0),
                ("free_throws_made_per_game", 1.0),
            ),
        ),
        DerivedStatColumn(
            "rebounds_per_game",
            (
                ("offensive_rebounds_per_game", 1.0),
                ("defensive_rebounds_per_game", 1.0),
            ),
        ),
    ),
    required_production_fields=(
        "minutes_per_game",
        "points_per_game",
        "offensive_rebounds_per_game",
        "defensive_rebounds_per_game",
        "rebounds_per_game",
        "assists_per_game",
        "steals_per_game",
        "blocks_per_game",
        "turnovers_per_game",
        "personal_fouls_per_game",
        "field_goals_made_per_game",
        "field_goals_attempted_per_game",
        "three_pointers_made_per_game",
        "three_pointers_attempted_per_game",
        "free_throws_made_per_game",
        "free_throws_attempted_per_game",
    ),
    expected_headers=BASKETBALL_MONSTER_2026_27_HEADERS,
    ignored_source_headers=("technicals", "double_doubles", "triple_doubles", "comments"),
    verification=VerificationStrength.HASH_PINNED,
    verified_seasons=("2026-27",),
    verification_evidence=(
        "private paid export sha256 "
        "FA13AD188E8ACADD410DFEAE7FF296A25078842E22CE17046CF19DFBCA9D3ABD; "
        "semantic screenshot sha256 "
        "3BA42FD80072E8C35C191C38BA19EB0C8A8BE4182D484FEFD73A31D1ED36C29B; "
        "13/13 visible quantities reconciled at source rounding on 2026-08-19"
    ),
)

PROFILES_BY_SOURCE: Mapping[ExternalSource, ColumnProfile] = MappingProxyType(
    {
        ExternalSource.MANUAL: MANUAL_PROFILE,
        ExternalSource.FANTASYPROS: FANTASYPROS_PROFILE,
        ExternalSource.HASHTAG: HASHTAG_PROFILE,
        ExternalSource.BASKETBALL_MONSTER: BASKETBALL_MONSTER_PROFILE,
    }
)
