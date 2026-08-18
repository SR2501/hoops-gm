"""Deriving and activating a league's scoring profile from its rules.

Turns a league's own current, versioned settings snapshot into rows in
``league_scoring_profiles``/``league_scoring_categories`` (see
``db/models/league.py`` for the schema those tables enforce), and owns the
activation lifecycle on top of it.

**The snapshot is the only source of scoring rules.** :func:`build_scoring_profile`
takes no caller-supplied category list or scoring-type argument. Both are
parsed from ``settings_snapshot.settings`` -- the same
``hoops_gm.ingest.league_settings.LeagueSettingsDocument`` the league-settings
importer already validated and persisted -- via
:meth:`~hoops_gm.ingest.league_settings.LeagueSettingsDocument.model_validate`.
An earlier version of this module accepted an arbitrary ``source_categories``
sequence from the caller while separately citing ``settings_snapshot_id`` for
lineage: nothing tied the persisted categories to the cited snapshot's actual
rules, so the lineage was decorative rather than load-bearing. There is now
exactly one way scoring rules reach a profile, and it is the snapshot's own
validated content.

**Where this sits and what it deliberately does not do.** This module
produces *configuration*, not a statistical estimate: a category vocabulary,
a direction sign, and — for percentage categories — the counting stats that
make volume-weighting possible downstream. It does not compute a projection,
a z-score, a G-score, an auction price, or anything ADR-002 calls
"production." Per-game production and expected-games-played stay exactly as
separate as ADR-002 requires; nothing here touches either. It also never
takes a ranking, an AAV, or any other synthesized market aggregate as an
input — ADR-008 forbids a terminal aggregate re-entering an earlier layer,
and a scoring profile is upstream of every one of them. The only thing a
profile is allowed to be built from is a league's own stated rules.

**Fails closed.** A category ``code`` this module does not recognise raises
:class:`UnsupportedCategoryError`; a non-unit category weight raises
:class:`NonUnitCategoryWeightError`; an unrecognised scoring-format
discriminator raises :class:`UnsupportedScoringFormatError`. None of these
silently drop the offending concern or guess at its meaning — a scoring
profile missing a category, misweighting one, or misreading the league's
format is a wrong valuation later, with no way to detect it after the fact
once the profile has been persisted and consumed.

**Versioned and immutable, activated explicitly.** :func:`build_scoring_profile`
never activates the row it creates; every profile starts inactive; a caller
must call :func:`activate_scoring_profile_version` to make it current, on its
own or in the same transaction. That keeps profile *creation* (which can be
retried, previewed or abandoned) separate from profile *activation* (which
changes what every subsequent read sees), and is what makes A → B → A
re-activation a plain, non-special-cased repeat of the same call.

**Idempotent by content, scoped to the same snapshot row.** Deriving twice
from the *same* settings-snapshot row is a no-op: the second call returns the
first call's profile rather than creating an indistinguishable new version --
see :func:`build_scoring_profile`. Deriving from a *different* snapshot row
whose canonical rules content happens to match an earlier profile's content
(scoring type, ordered categories, their directions/kinds/ratio
components/weights, and the settings document's own content hash) does
**not** reuse that earlier row -- it always mints a new, distinct profile
version, because the earlier row cites a snapshot that is no longer current
and :func:`activate_scoring_profile_version` correctly refuses to activate a
profile whose cited snapshot has been superseded. Reusing it across snapshots
would produce a profile that can never be activated again, an unescapable
dead end for exactly the A -> B -> A case this idempotency exists to serve.
So A -> B -> A produces three distinct, successively activatable profile
versions -- the third sharing its category/scoring-type content with the
first, but citing the third (current) snapshot, not the first snapshot's row.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hoops_gm.db.lineage import content_fingerprint
from hoops_gm.db.models.enums import CategoryKind, ScoringType
from hoops_gm.db.models.league import League, LeagueScoringCategory, LeagueScoringProfile
from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot
from hoops_gm.ingest.league_settings import LeagueSettingsDocument


class UnsupportedCategoryError(ValueError):
    """A source reported a scoring category this vocabulary cannot express.

    Raised instead of skipping the category or guessing at a mapping. A
    scoring profile silently missing a category is indistinguishable from a
    correct one until a valuation built on it is already wrong, which is
    exactly the failure mode "fail closed" exists to prevent here.
    """


class UnsupportedScoringFormatError(ValueError):
    """The settings snapshot reports a scoring-format discriminator this
    codebase has not verified a mapping for.

    Raised instead of defaulting to a plausible-looking format. Which
    category-vs-aggregate scoring rules apply is not guessable from the
    category vocabulary alone -- see :data:`_FANTRAX_SCORING_TYPE_TO_LOCAL`
    for the one discriminator currently verified.
    """


class NonUnitCategoryWeightError(ValueError):
    """A source category carries a Fantrax ``weight`` other than ``1.0``.

    Fantrax's own per-category ``weight`` is a distinct concept from this
    project's points-league ``LeagueScoringCategory.point_value`` (null for
    every category league). Every category observed live in the target H2H
    league carries ``weight == 1.0``; weighted-category scoring has not been
    designed for this vocabulary. Rather than silently drop a non-unit weight
    (data loss) or misapply it as ``point_value`` (unverified semantics),
    building a profile from one fails closed until weighted categories are
    designed.
    """


@dataclass(frozen=True)
class SourceCategory:
    """One scoring category as the settings snapshot's document reports it.

    ``code`` is the primary mapping anchor: Fantrax's own stable per-category
    identifier (e.g. ``"INDIVIDUAL_ASSISTS"``), verified against the captured
    fixture. ``abbreviation`` is retained as evidence/display only, never as a
    mapping key -- Fantrax's display strings and numeric ids are not
    guaranteed stable the way ``code`` is (see
    ``ingest/fantrax_official/parsers.py``, which previously conflated the
    numeric id with the mapping key).
    """

    code: str
    abbreviation: str
    weight: float = 1.0
    name: str | None = None


@dataclass(frozen=True)
class CategoryDefinition:
    """A canonical category: what it is called, how it is scored, and how."""

    key: str
    label: str
    kind: CategoryKind
    direction: int = 1
    numerator_stat: str | None = None
    denominator_stat: str | None = None
    #: Always ``1.0`` in this vocabulary today -- the slot a future weighted-
    #: category design would populate. See :class:`NonUnitCategoryWeightError`.
    weight: float = 1.0


#: The canonical 9-category H2H vocabulary, keyed by our own stable key (not
#: any source's code or abbreviation). Ratio categories name their component
#: counting stats explicitly -- see ``LeagueScoringCategory``'s docstring and
#: R9 in docs/plan.md for why FG%/FT% must never be stored or averaged as raw
#: percentages: a 90% shooter on one attempt is worthless, and only the
#: made/attempted pair lets a valuation weight it by volume.
NINE_CATEGORY_DEFINITIONS: Mapping[str, CategoryDefinition] = {
    "pts": CategoryDefinition("pts", "PTS", CategoryKind.COUNTING),
    "reb": CategoryDefinition("reb", "REB", CategoryKind.COUNTING),
    "ast": CategoryDefinition("ast", "AST", CategoryKind.COUNTING),
    "stl": CategoryDefinition("stl", "STL", CategoryKind.COUNTING),
    "blk": CategoryDefinition("blk", "BLK", CategoryKind.COUNTING),
    "fg3m": CategoryDefinition("fg3m", "3PTM", CategoryKind.COUNTING),
    # Turnovers score in the opposite direction of every other counting
    # category here. The sign lives in the data, not in a special case.
    "to": CategoryDefinition("to", "TO", CategoryKind.COUNTING, direction=-1),
    "fg_pct": CategoryDefinition(
        "fg_pct",
        "FG%",
        CategoryKind.RATIO,
        numerator_stat="field_goals_made",
        denominator_stat="field_goals_attempted",
    ),
    "ft_pct": CategoryDefinition(
        "ft_pct",
        "FT%",
        CategoryKind.RATIO,
        numerator_stat="free_throws_made",
        denominator_stat="free_throws_attempted",
    ),
}

#: Fantrax ``code`` -> canonical key, restricted to exactly what has been
#: observed live in a captured Fantrax payload
#: (``fantrax_getleagueinfo_settings_sanitized.json``):
#: INDIVIDUAL_{ASSISTS,BLOCKS,POINTS,REBOUNDS,STEALS,THREE_POINTERS_MADE,
#: TURNOVERS,FIELD_GOAL_PERCENTAGE,FREE_THROW_PERCENTAGE}. Deliberately not
#: padded out with plausible-looking codes that have never actually been
#: seen -- an unverified alias is a guess wearing evidence's clothes, and a
#: guess that turns out wrong here silently mis-scores a whole category.
#: Extend this table only against new observed evidence, per house rules.
_FANTRAX_CODE_TO_KEY: Mapping[str, str] = {
    "INDIVIDUAL_POINTS": "pts",
    "INDIVIDUAL_REBOUNDS": "reb",
    "INDIVIDUAL_ASSISTS": "ast",
    "INDIVIDUAL_STEALS": "stl",
    "INDIVIDUAL_BLOCKS": "blk",
    "INDIVIDUAL_THREE_POINTERS_MADE": "fg3m",
    "INDIVIDUAL_TURNOVERS": "to",
    "INDIVIDUAL_FIELD_GOAL_PERCENTAGE": "fg_pct",
    "INDIVIDUAL_FREE_THROW_PERCENTAGE": "ft_pct",
}

#: Fantrax's raw ``scoringSystem.type`` discriminator -> the local
#: ``ScoringType`` enum, restricted to exactly the one value observed live in
#: the captured fixture. ``HEAD_TO_HEAD_ROTI_MULTI_WIN`` is mapped to
#: ``H2H_EACH_CATEGORY`` (every category scored as its own independent
#: win/loss/tie -- "multi win" per matchup, matching the "MULTI_WIN" segment
#: of the discriminator, as opposed to an aggregate single win/loss/tie),
#: which also matches this league's own historical rules baseline
#: (docs/league/2025-26-rules-baseline.md: "H2H each category"). This is the
#: best currently available evidence, not a confirmed reading of Fantrax's
#: own API documentation; the "ROTI" segment's meaning specifically remains
#: unconfirmed -- see docs/adapters/fantrax-official.md. Extend this table
#: only against new observed evidence.
_FANTRAX_SCORING_TYPE_TO_LOCAL: Mapping[str, ScoringType] = {
    "HEAD_TO_HEAD_ROTI_MULTI_WIN": ScoringType.H2H_EACH_CATEGORY,
}


def map_source_categories(
    source_categories: Sequence[SourceCategory],
) -> list[CategoryDefinition]:
    """Map source-reported categories to the canonical vocabulary, in order.

    Order is preserved because it becomes ``display_order`` downstream, and
    "category order" is part of this unit's own acceptance surface, not an
    incidental detail.

    Raises :class:`NonUnitCategoryWeightError` on the first category whose
    ``weight`` is not exactly ``1.0`` (checked before the mapping lookup, so a
    non-unit weight on an otherwise-recognised category still fails closed
    rather than silently mapping through), :class:`UnsupportedCategoryError`
    on the first ``code`` with no known mapping, and :class:`ValueError` if
    two source categories map to the same canonical key (a source contract
    violation, not an unsupported category -- the vocabulary understood both,
    the *source* sent a duplicate).
    """

    mapped: list[CategoryDefinition] = []
    seen_keys: set[str] = set()
    for source in source_categories:
        if source.weight != 1.0:
            raise NonUnitCategoryWeightError(
                f"unsupported non-unit scoring category weight for {source.code!r}: "
                f"{source.weight!r} (weighted categories are not yet designed)"
            )
        key = _FANTRAX_CODE_TO_KEY.get(source.code)
        if key is None:
            raise UnsupportedCategoryError(f"unsupported scoring category code: {source.code!r}")
        if key in seen_keys:
            raise ValueError(
                f"duplicate scoring category after mapping: {key!r} (from code {source.code!r})"
            )
        seen_keys.add(key)
        mapped.append(NINE_CATEGORY_DEFINITIONS[key])
    return mapped


def _map_scoring_type(raw_type: str) -> ScoringType:
    """Map a source's raw scoring-format discriminator, failing closed."""

    mapped = _FANTRAX_SCORING_TYPE_TO_LOCAL.get(raw_type)
    if mapped is None:
        raise UnsupportedScoringFormatError(
            f"unsupported scoring-format discriminator: {raw_type!r}"
        )
    return mapped


def _settings_document(settings_snapshot: LeagueSettingsSnapshot) -> LeagueSettingsDocument:
    return LeagueSettingsDocument.model_validate(settings_snapshot.settings)


def _source_categories_from_document(document: LeagueSettingsDocument) -> list[SourceCategory]:
    categories = document.scoring_categories.value
    if categories is None:
        raise ValueError("settings snapshot reports no scoring categories")
    return [
        SourceCategory(
            code=category.code,
            abbreviation=category.abbreviation,
            weight=category.weight,
            name=category.display_name,
        )
        for category in categories.categories
    ]


def _scoring_type_from_document(document: LeagueSettingsDocument) -> ScoringType:
    scoring_format = document.scoring_type.value
    if scoring_format is None:
        raise ValueError("settings snapshot reports no scoring type")
    return _map_scoring_type(scoring_format.raw_type)


def _profile_fingerprint(
    *,
    scoring_type: ScoringType,
    settings_content_sha256: str,
    definitions: Sequence[CategoryDefinition],
) -> str:
    """A content fingerprint over exactly the parts that make two profiles
    indistinguishable in substance: scoring type, category ordering, codes,
    directions, ratio components, weights, and the settings document's own
    content hash (which itself excludes observation-specific evidence such as
    capture refs -- see ``LeagueSettingsDocument.configuration_json``). Two
    different snapshot *rows* -- different ids, different raw capture
    metadata -- can still fingerprint identically here if their normalized
    rules content matches.

    That equality is used only as a *consistency* check, never as a reuse
    key across snapshot rows on its own -- see ``build_scoring_profile``'s
    docstring for why a same-content match against a different (superseded)
    snapshot row must still mint a new, distinct profile version rather than
    returning the old row.
    """

    parts = [scoring_type.value, settings_content_sha256]
    for definition in definitions:
        parts.extend(
            [
                definition.key,
                str(definition.direction),
                definition.kind.value,
                definition.numerator_stat or "",
                definition.denominator_stat or "",
                repr(definition.weight),
            ]
        )
    return content_fingerprint(parts)


def _fingerprint_of_existing_profile(profile: LeagueScoringProfile) -> str:
    document = _settings_document(profile.settings_snapshot)
    ordered = sorted(profile.categories, key=lambda category: category.display_order)
    definitions = [
        CategoryDefinition(
            key=category.key,
            label=category.label,
            kind=category.kind,
            direction=category.direction,
            numerator_stat=category.numerator_stat,
            denominator_stat=category.denominator_stat,
        )
        for category in ordered
    ]
    return _profile_fingerprint(
        scoring_type=profile.scoring_type,
        settings_content_sha256=document.content_sha256(),
        definitions=definitions,
    )


def build_scoring_profile(
    session: Session,
    *,
    league: League,
    settings_snapshot: LeagueSettingsSnapshot,
    name: str = "default",
) -> LeagueScoringProfile:
    """Derive and persist a league's scoring profile from its own settings.

    Never activates the row it returns -- see the module docstring. Fails
    closed rather than persisting anything new on any of the following:

    * ``settings_snapshot`` belongs to a different league than ``league``
      (exact league binding -- a profile's rules lineage must be provably
      about the same league it scores, not merely a plausible-looking one).
    * ``settings_snapshot`` is not that league's *current* (highest-version)
      settings snapshot. A profile derived from a superseded settings
      version would silently misrepresent "what the league's rules are now,"
      which is exactly the staleness ``db/lineage.py``'s cohort-checking
      exists to catch elsewhere in this codebase; this is the same discipline
      applied to scoring-profile derivation specifically.
    * ``settings_snapshot``'s own validated document reports no scoring type
      or no scoring categories (an ``absent`` observation -- the settings
      importer has not actually seen this league's scoring rules yet).
    * The document's categories contain a ``code`` this vocabulary cannot
      map, a duplicate after mapping, or a non-unit ``weight`` -- see
      :func:`map_source_categories`.
    * The document's scoring-format discriminator has no verified mapping --
      see :func:`_map_scoring_type`.

    If an existing profile for ``(league, name)`` was already derived from
    this *exact* ``settings_snapshot`` row (same id) and still has the same
    canonical content that row would produce, that existing profile is
    returned unchanged rather than creating an indistinguishable new
    version -- a plain re-run against unchanged settings is a no-op. That is
    the only case reused: a same-content match against a *different*
    snapshot row (even a byte-identical, canonicalized-content match) always
    mints a new profile version instead, because reusing the old row would
    leave it citing a superseded ``settings_snapshot_id`` --
    ``activate_scoring_profile_version`` correctly refuses to activate a
    profile whose snapshot is no longer current, so returning the old row
    would silently produce a profile that can never be activated again. A
    fresh version citing the new (current) snapshot has no such problem, and
    still shares its predecessor's content -- concretely, deriving from A,
    then B, then a snapshot whose rules content matches A again (A -> B -> A)
    produces three distinct, successively activatable profile versions, the
    third sharing its category/scoring-type content with the first. Repointing
    an existing row's ``settings_snapshot_id`` instead was considered and
    rejected: it would rewrite that row's historical lineage, silently
    changing what "this profile was derived from settings snapshot N" meant
    for a row that already existed before N was current.
    """

    if settings_snapshot.league_id != league.id:
        raise ValueError(
            "settings snapshot belongs to a different league: "
            f"snapshot.league_id={settings_snapshot.league_id!r}, league.id={league.id!r}"
        )

    current_version = session.scalar(
        select(func.max(LeagueSettingsSnapshot.version)).where(
            LeagueSettingsSnapshot.league_id == league.id
        )
    )
    if current_version is None or settings_snapshot.version != current_version:
        raise ValueError(
            "settings snapshot is stale: "
            f"snapshot is version {settings_snapshot.version!r}, "
            f"current is version {current_version!r} for league {league.id!r}"
        )

    document = _settings_document(settings_snapshot)
    scoring_type = _scoring_type_from_document(document)
    source_categories = _source_categories_from_document(document)
    definitions = map_source_categories(source_categories)

    fingerprint = _profile_fingerprint(
        scoring_type=scoring_type,
        settings_content_sha256=document.content_sha256(),
        definitions=definitions,
    )
    existing_profiles = session.scalars(
        select(LeagueScoringProfile).where(
            LeagueScoringProfile.league_id == league.id,
            LeagueScoringProfile.name == name,
            LeagueScoringProfile.settings_snapshot_id == settings_snapshot.id,
        )
    ).all()
    for existing in existing_profiles:
        if _fingerprint_of_existing_profile(existing) == fingerprint:
            return existing

    next_version = (
        session.scalar(
            select(func.max(LeagueScoringProfile.version)).where(
                LeagueScoringProfile.league_id == league.id,
                LeagueScoringProfile.name == name,
            )
        )
        or 0
    ) + 1

    profile = LeagueScoringProfile(
        league_id=league.id,
        name=name,
        version=next_version,
        scoring_type=scoring_type,
        settings_snapshot_id=settings_snapshot.id,
    )
    session.add(profile)
    session.flush()

    session.add_all(
        LeagueScoringCategory(
            profile_id=profile.id,
            key=definition.key,
            label=definition.label,
            kind=definition.kind,
            direction=definition.direction,
            display_order=order,
            numerator_stat=definition.numerator_stat,
            denominator_stat=definition.denominator_stat,
        )
        for order, definition in enumerate(definitions, start=1)
    )
    session.flush()
    return profile


def activate_scoring_profile_version(
    session: Session, profile: LeagueScoringProfile
) -> LeagueScoringProfile:
    """Make ``profile`` the league's active scoring profile.

    Revalidates, before touching whatever profile is currently active, that:

    * ``profile.settings_snapshot.league_id`` still matches ``profile.league_id``
      (exact league binding -- the same discipline :func:`build_scoring_profile`
      applies at creation time, re-checked at activation time because a
      profile row's settings-snapshot relationship is data, not something
      the ORM guarantees stays valid between creation and activation).
    * ``profile.settings_snapshot`` is still the league's *current* settings
      snapshot (not stale -- activating a profile derived from settings the
      league has since moved on from would make a superseded rules version
      newly authoritative for every subsequent read).
    * ``profile.categories`` is non-empty (a profile with no categories --
      however it came to exist, including by direct ORM manipulation that
      bypassed :func:`build_scoring_profile` entirely -- has nothing to
      activate).

    Any of these raising leaves whatever was previously active untouched: the
    checks run before the previously-active profile is looked up or
    deactivated, so a failed activation never gets partway through.

    Once past the checks, this is a two-phase deactivate-then-activate: first
    null out whatever profile is currently active for ``profile.league_id``
    (if any and it is a *different* row), flush, then set
    ``profile.active_league_id``. Doing this in two flushes rather than one
    assignment keeps ``uq_league_scoring_profiles_one_active`` satisfied at
    every intermediate point when reactivating a previously-superseded
    version (A -> B -> A), a genuinely different row that must be nulled out
    before this one can take the unique slot. Activating a profile that is
    *already* the active one is a true no-op: the deactivate step is skipped
    entirely (there is nothing to null out that would not immediately be
    re-set to the same row), leaving a single redundant assignment and flush
    rather than an actual deactivate-then-reactivate cycle.
    """

    if profile.settings_snapshot.league_id != profile.league_id:
        raise ValueError(
            "cannot activate: profile's settings snapshot belongs to a different league "
            f"(snapshot.league_id={profile.settings_snapshot.league_id!r}, "
            f"profile.league_id={profile.league_id!r})"
        )

    current_version = session.scalar(
        select(func.max(LeagueSettingsSnapshot.version)).where(
            LeagueSettingsSnapshot.league_id == profile.league_id
        )
    )
    if current_version is None or profile.settings_snapshot.version != current_version:
        raise ValueError(
            "cannot activate: profile's settings snapshot is stale "
            f"(snapshot is version {profile.settings_snapshot.version!r}, "
            f"current is version {current_version!r} for league {profile.league_id!r})"
        )

    if len(profile.categories) == 0:
        raise ValueError("cannot activate a scoring profile with no scoring categories")

    previously_active = session.scalar(
        select(LeagueScoringProfile).where(
            LeagueScoringProfile.active_league_id == profile.league_id
        )
    )
    if previously_active is not None and previously_active.id != profile.id:
        previously_active.active_league_id = None
        session.flush()

    profile.active_league_id = profile.league_id
    session.flush()
    return profile


def current_scoring_profile(session: Session, league_id: int) -> LeagueScoringProfile | None:
    """The league's single active scoring profile, or ``None`` if none is active.

    This is the canonical selector: at most one row can ever satisfy this
    query, enforced by ``uq_league_scoring_profiles_one_active`` at the
    database layer (see ``LeagueScoringProfile``'s docstring), so there is no
    ordering or tie-breaking logic to get wrong here.
    """

    return session.scalar(
        select(LeagueScoringProfile).where(LeagueScoringProfile.active_league_id == league_id)
    )
