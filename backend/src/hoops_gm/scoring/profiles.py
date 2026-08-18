"""Deriving and activating a league's scoring profile from its rules.

Turns the raw scoring-category evidence a source (currently only Fantrax)
reports into rows in ``league_scoring_profiles``/``league_scoring_categories``
(see ``db/models/league.py`` for the schema those tables enforce), and owns
the activation lifecycle on top of it.

**Where this sits and what it deliberately does not do.** This module
produces *configuration*, not a statistical estimate: a category vocabulary,
a direction sign, and — for percentage categories — the counting stats that
make volume-weighting possible downstream. It does not compute a projection,
a z-score, a G-score, an auction price, or anything ADR-002 calls
"production." Per-game production and expected-games-played stay exactly as
separate as ADR-002 requires; nothing here touches either. It also never
takes a ranking, an AAV, or any other synthesized market aggregate as an
input — ADR-008 forbids a terminal aggregate re-entering an earlier layer,
and a scoring profile is upstream of every one of them. The only things a
profile is allowed to be built from are a league's own stated rules
(``LeagueSettingsSnapshot``) and its own stated scoring categories.

**Fails closed.** An abbreviation this module does not recognise raises
:class:`UnsupportedCategoryError` rather than silently dropping the category
or guessing at its meaning — a scoring profile missing a category is a wrong
valuation later, and there is no way to detect that after the fact once the
profile has been persisted and consumed.

**Versioned and immutable, activated explicitly.** :func:`build_scoring_profile`
never activates the row it creates; every profile starts inactive; a caller
must call :func:`activate_scoring_profile_version` to make it current, on its
own or in the same transaction. That keeps profile *creation* (which can be
retried, previewed or abandoned) separate from profile *activation* (which
changes what every subsequent read sees), and is what makes A → B → A
re-activation a plain, non-special-cased repeat of the same call.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import CategoryKind, ScoringType
from hoops_gm.db.models.league import League, LeagueScoringCategory, LeagueScoringProfile
from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot


class UnsupportedCategoryError(ValueError):
    """A source reported a scoring category this vocabulary cannot express.

    Raised instead of skipping the category or guessing at a mapping. A
    scoring profile silently missing a category is indistinguishable from a
    correct one until a valuation built on it is already wrong, which is
    exactly the failure mode "fail closed" exists to prevent here.
    """


@dataclass(frozen=True)
class SourceCategory:
    """One scoring category as a source reports it, before mapping.

    Deliberately not the adapter's own ``FantraxScoringCategory`` — this
    module stays decoupled from any one source's parsing (ADR-006 draws that
    line at the adapter boundary), and ``abbreviation`` is the only field this
    module trusts as a mapping anchor. Fantrax's own ``key`` is not: the
    adapter documents it as preferring an internal numeric id over any stable
    code, which makes it useless as a cross-league vocabulary anchor.
    """

    abbreviation: str
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


#: The canonical 9-category H2H vocabulary, keyed by our own stable key (not
#: any source's abbreviation). Ratio categories name their component counting
#: stats explicitly -- see ``LeagueScoringCategory``'s docstring and R9 in
#: docs/plan.md for why FG%/FT% must never be stored or averaged as raw
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

#: Abbreviation → canonical key, restricted to exactly what has been observed
#: live in a captured Fantrax payload (``fantrax_getleagueinfo_settings_sanitized.json``):
#: AST, BLK, PTS, REB, ST, 3PTM, TO, FG%, FT%. Deliberately not padded out
#: with plausible-looking aliases ("STL", "3PM") that have never actually been
#: seen -- an unverified alias is a guess wearing evidence's clothes, and a
#: guess that turns out wrong here silently mis-scores a whole category.
#: Extend this table only against new observed evidence, per house rules.
_FANTRAX_ABBREVIATION_TO_KEY: Mapping[str, str] = {
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "ST": "stl",
    "BLK": "blk",
    "3PTM": "fg3m",
    "TO": "to",
    "FG%": "fg_pct",
    "FT%": "ft_pct",
}


def map_source_categories(
    source_categories: Sequence[SourceCategory],
) -> list[CategoryDefinition]:
    """Map source-reported categories to the canonical vocabulary, in order.

    Order is preserved because it becomes ``display_order`` downstream, and
    "category order" is part of this unit's own acceptance surface, not an
    incidental detail.

    Raises :class:`UnsupportedCategoryError` on the first abbreviation with no
    known mapping (fail closed) and :class:`ValueError` if two source
    categories map to the same canonical key (a source contract violation,
    not an unsupported category -- the vocabulary understood both, the
    *source* sent a duplicate).
    """

    mapped: list[CategoryDefinition] = []
    seen_keys: set[str] = set()
    for source in source_categories:
        key = _FANTRAX_ABBREVIATION_TO_KEY.get(source.abbreviation)
        if key is None:
            raise UnsupportedCategoryError(
                f"unsupported scoring category abbreviation: {source.abbreviation!r}"
            )
        if key in seen_keys:
            raise ValueError(
                f"duplicate scoring category after mapping: {key!r} "
                f"(from abbreviation {source.abbreviation!r})"
            )
        seen_keys.add(key)
        mapped.append(NINE_CATEGORY_DEFINITIONS[key])
    return mapped


def build_scoring_profile(
    session: Session,
    *,
    league: League,
    settings_snapshot: LeagueSettingsSnapshot,
    source_categories: Sequence[SourceCategory],
    name: str = "default",
    scoring_type: ScoringType = ScoringType.H2H_CATEGORIES,
) -> LeagueScoringProfile:
    """Derive and persist the next version of a league's scoring profile.

    Never activates the row it creates -- see the module docstring. Fails
    closed rather than persisting anything on any of the following:

    * ``settings_snapshot`` belongs to a different league than ``league``
      (exact league binding -- a profile's rules lineage must be provably
      about the same league it scores, not merely a plausible-looking one).
    * ``settings_snapshot`` is not that league's *current* (highest-version)
      settings snapshot. A profile derived from a superseded settings
      version would silently misrepresent "what the league's rules are now,"
      which is exactly the staleness ``db/lineage.py``'s cohort-checking
      exists to catch elsewhere in this codebase; this is the same discipline
      applied to scoring-profile derivation specifically.
    * ``source_categories`` contains an abbreviation this vocabulary cannot
      map, or a duplicate after mapping -- see :func:`map_source_categories`.
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

    definitions = map_source_categories(source_categories)

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

    Two-phase deactivate-then-activate: first null out whatever profile is
    currently active for ``profile.league_id`` (if any), flush, then set
    ``profile.active_league_id``. Doing this in two flushes rather than one
    assignment keeps ``uq_league_scoring_profiles_one_active`` satisfied at
    every intermediate point, including when ``profile`` is already the
    active one (a no-op deactivate-then-reactivate of itself) and when
    reactivating a previously-superseded version (A -> B -> A): there is no
    special case for either, because activation is always "deactivate
    whatever is active, then activate this one."
    """

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
