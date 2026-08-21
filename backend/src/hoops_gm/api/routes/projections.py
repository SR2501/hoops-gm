"""The current imported per-game projection cohort for one league's season.

Descriptive only. This route reports the per-game production rates one
projection source published, exactly as the importer decomposed them, plus the
lineage that produced them. It ranks nothing, values nothing, fuses nothing
with availability, and computes no aggregate — those are ``quant``'s behind the
Model gate (ADR-002, ADR-008) and are deliberately absent. **The only arithmetic
in this module is ``len()``.**

**Where the evidence comes from.** Currency, profile verification and row
validity are *not* re-derived here.
:func:`hoops_gm.projections.blending.release_projection_import` owns the single
definition of "is this import fit to be consumed" — it checks the profile is
verified for the season, that the import's immutable profile lineage is
self-consistent, that the import is the current one for its source and season,
and that every stored rate is finite and non-negative with intact shooting
pairs. It also digests the rows it validated. This route consumes that function
and adds no second verifier, because a second verifier can only ever drift from
the one the rest of the pipeline trusts.

**What this route does not serve, and why.** It serves the *imported* cohort,
not a blended one. ``hoops_gm.projections.blending`` computes a blend from a
:class:`~hoops_gm.projections.blending.BlendCatalog`, and that catalog is an
explicitly caller-owned in-memory value — the accepted schema has no blend
tables, by design, because adding them is an architecture decision rather than
a side effect. There is therefore no persisted blend, no persisted profile and
no persisted source weights for any HTTP request to read. Serving a blend here
would mean this route constructing a profile itself, which is choosing weights,
which is a number a decision rests on. ``blend`` is present in the lineage block
and is always ``null`` today, so a consumer reads the absence instead of
inferring it from a missing key.

**ADR-002 is visible in the response shape.** The source's own games-played
assumption is carried in its own top-level array, never inside a projection
object, mirroring the table separation
(``source_games_played_assumptions`` is one-to-one with ``projections`` rather
than a column on it) so nothing can pick up a durability guess while reading a
rate. It is published so a screen can *show* what the source assumed and that
our availability model will override it. It is never fused here.

**Two operational limits worth knowing before this sits behind a dashboard
poll.** This read locks the importer's own ``projection_sources`` row for the
whole request, so a concurrent ``import_projection_csv`` for the same source
blocks until it finishes; on SQLite that lock is the database-wide write
reservation, so a slow poll delays *any* writer, and a writer that loses the
race gets ``database is locked`` rather than waiting. And a refusal's code does
not reach the server log: the middleware records ``status_code`` only, so five
of the eight refusals read identically as ``409`` to an operator. The second is
inherited and app-wide rather than introduced here, and is tracked as
``error-code-observability`` in ``docs/backlog.md``.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.api.deps import SessionDep
from hoops_gm.api.schemas import ErrorResponse
from hoops_gm.api.security import require_loopback_host
from hoops_gm.db.models.enums import ExternalSource, ScoringType
from hoops_gm.db.models.identity import NbaTeam, Player
from hoops_gm.db.models.league import League
from hoops_gm.db.models.projections import (
    Projection,
    ProjectionImport,
    ProjectionSource,
    SourceGamesPlayedAssumption,
)
from hoops_gm.ingest.projections.profiles import CANONICAL_STAT_FIELDS, PROJECTION_IMPORT_SOURCES
from hoops_gm.projections.blending import (
    MissingProjectionDataError,
    ProjectionBlendError,
    ReleasedProjectionImport,
    StaleProjectionInputError,
    UnknownProjectionInputError,
    release_projection_import,
)

router = APIRouter(prefix="/leagues/{league_id}/projections", tags=["projections"])

#: The project's projection source. A caller may ask for another registered CSV
#: source, but the default is the one the owner actually buys (AGENTS.md: this
#: project does not rebuild Basketball Monster).
DEFAULT_PROJECTION_SOURCE = ExternalSource.BASKETBALL_MONSTER


class ProjectionImportLineage(BaseModel):
    """The exact import the rates below were read from.

    Every fingerprint the importer and the canonical release produce is carried
    verbatim rather than summarised. ``content_sha256`` is the CSV bytes,
    ``profile_definition_sha256`` is the parsing recipe those bytes were read
    under, and ``projection_values_sha256`` is a digest over the *stored,
    normalised rates* — the one that changes when a row is edited in place while
    the file hash and the mapping lineage still look untouched.

    The five row counts are the import's own audit trail and **partition** the
    file: ``row_count`` is every data row it contained, ``rejected_count`` is
    what the parser refused before identity resolution ran, and the other three
    partition what survived by resolution outcome. That is asserted rather than
    asserted-in-prose — ``test_the_audit_counts_actually_partition_the_file``
    drives an import where the terms are genuinely different and checks the sum
    on the served body, because a screen that renders five numbers a docstring
    calls a partition invites a reader to add them up.

    ``projection_count`` is separate and is what this response actually carries:
    the rows the canonical release validated. It equals ``matched_count`` only
    while no earlier import for the same source and season contributed rows to
    the crosswalk differently. Both are published rather than one being derived
    from the other.

    **Do not multiply these rates by anything.** See
    :class:`SourceGamesPlayedClaim`.
    """

    import_id: int
    source: ExternalSource
    season: str
    imported_at: datetime
    content_sha256: str
    profile_id: str
    profile_version: str
    profile_definition_sha256: str
    projection_values_sha256: str
    projection_count: int
    #: The scoring format the source's published numbers assume, when the source
    #: or the import stated one. ``None`` means nobody stated it — never
    #: defaulted to this league's format, because a points-league projection
    #: consumed as a 9-cat one is wrong in a way no downstream check can see.
    #:
    #: **Which of the two origins won is deliberately not carried**, and that is
    #: a real gap rather than an oversight. ``release_projection_import`` resolves
    #: it (the import's own value, else the source's standing registration) and
    #: publishing the winner's origin here would mean restating that precedence
    #: rule in a second place, free to drift from the one that produced the
    #: value. The project's own standard elsewhere — ``scoring-profile`` cites
    #: which of two source fields won — is met by the producer recording it, not
    #: by this route re-deriving it. A consumer needing the distinction should
    #: ask for the canonical release to carry it.
    assumed_scoring_type: ScoringType | None
    original_filename: str | None
    row_count: int
    matched_count: int
    needs_review_count: int
    unmatched_count: int
    rejected_count: int


class ProjectionLineage(BaseModel):
    """What produced this response.

    ``blend`` is typed and always ``null``. See the module docstring: blend
    profiles, their source weights and their activation state are caller-owned
    in-memory values with no persistence, so there is nothing for an HTTP
    request to read. The key exists so a consumer can render "not blended"
    from a fact rather than from a key it did not find.
    """

    projection_import: ProjectionImportLineage
    blend: None = None


class ProjectionPlayer(BaseModel):
    """One player appearing in ``projections``, with the labels a screen needs.

    ``team_abbreviation`` and ``primary_position`` are the canonical player
    record's current values, not the projection source's opinion of them, and
    they are read outside any lineage scope — ``players`` and ``nba_teams`` have
    no lineage scope to take. So a player traded or relabelled between the rates
    statement and this one would be labelled from the newer state. What cannot
    change is which player a ``player_id`` denotes: it is our own surrogate key
    and no writer repoints it. The residual risk is therefore a fresher label on
    the right player, never a rate attributed to the wrong one.
    """

    player_id: int
    full_name: str
    team_abbreviation: str | None
    primary_position: str | None


class ProjectionRates(BaseModel):
    """One player's per-game production rates, exactly as stored.

    Per-game only (ADR-002). Nothing here is a season total and nothing here is
    an expected-games number. Percentage categories are absent by construction:
    makes and attempts are published separately and a shooting percentage is
    never precomputed, because a percentage without its volume is the single
    most common bug in homebrew fantasy tools.

    Every field is present on every row; ``null`` means the source did not
    publish that quantity, and is never a zero.
    """

    player_id: int
    minutes_per_game: float | None
    points_per_game: float | None
    offensive_rebounds_per_game: float | None
    defensive_rebounds_per_game: float | None
    rebounds_per_game: float | None
    assists_per_game: float | None
    steals_per_game: float | None
    blocks_per_game: float | None
    turnovers_per_game: float | None
    personal_fouls_per_game: float | None
    field_goals_made_per_game: float | None
    field_goals_attempted_per_game: float | None
    three_pointers_made_per_game: float | None
    three_pointers_attempted_per_game: float | None
    free_throws_made_per_game: float | None
    free_throws_attempted_per_game: float | None


class SourceGamesPlayedClaim(BaseModel):
    """What the source assumed about one player's availability.

    **Not a projection of games played, and not ours.** ADR-002 keeps this in a
    separate table so nothing reads a rate and picks up a durability guess by
    accident; this response keeps it in a separate array for the same reason. It
    exists to be overridden by the availability model, never blended with it.

    **Do not multiply a rate by this number.** It is not merely *a* games-played
    figure — for a season-total source like Basketball Monster it is the exact
    divisor the importer used to produce the per-game rates beside it, so the
    product reconstructs the source's published seasonal total to the float. The
    decomposition ADR-002 mandates is therefore perfectly reversible at the wire
    by a two-line join, and doing that join is the fusion ADR-002 permits only at
    ``expected-games``, which does not exist yet. A client may **display** the
    assumption — showing "the source assumed 70 games, we will replace that" is
    the product thesis in one line — and must not compute with it.

    ``assumed_games_played_raw`` is the source's own text ("70", "68 GP") kept
    verbatim, so a consumer can show what was actually published rather than a
    re-rendered number.
    """

    player_id: int
    assumed_games_played: float | None
    assumed_games_played_raw: str | None


class CurrentProjectionsResponse(BaseModel):
    """The current imported cohort plus what a screen needs to label and trust it.

    **Guaranteed on any 200**, or the request is refused instead:

    * ``players`` and ``projections`` describe exactly the same set of
      ``player_id`` values, each exactly once, both ordered by ``player_id``. A
      partially-labelled cohort is impossible rather than merely unlikely.
    * ``len(projections) == lineage.projection_import.projection_count`` — the
      rows carried here are the rows the canonical release verified and
      digested, not a differently-sized second read of the same table.

    ``source_games_played_assumptions`` is deliberately **not** dense: only
    players whose source stated an assumption appear, and it may be empty. A
    consumer must join it by ``player_id`` and treat a missing entry as "the
    source said nothing", never as zero.
    """

    league_id: int
    season: str
    source: ExternalSource
    lineage: ProjectionLineage
    players: list[ProjectionPlayer]
    projections: list[ProjectionRates]
    source_games_played_assumptions: list[SourceGamesPlayedClaim]


def _error(status_code: int, code: str, detail: str) -> HTTPException:
    """Raise inside the app's error contract.

    ``X-Bridge-Error`` is **not** a response header. ``app.py``'s handler reads
    it off the exception and returns the code in ``ErrorResponse.error``; the
    only header on the way out is ``X-Request-ID``. The name is a legacy of the
    bridge routes that introduced this transport.
    """

    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"X-Bridge-Error": code},
    )


def _projection_source_id(session: Session, *, source: ExternalSource) -> int | None:
    """The registered source row id, or ``None`` if it has never been registered.

    **This route takes no lock, and that is a decision rather than an omission.**

    An earlier version took ``projection_sources`` ``FOR UPDATE`` — the
    importer's own first row lock — and claimed both dialects therefore
    serialized. That claim was false on SQLite, where pysqlite emits ``BEGIN``
    only before DML and SQLAlchemy drops ``FOR UPDATE`` entirely, so a read-only
    session held nothing: review drove a concurrent writer straight through it
    and produced a 200 whose rates were post-write beside a pre-write
    ``projection_values_sha256``.

    The obvious repair was to add SQLite's write reservation. It works, and it
    was rejected on the second look, because of what it costs the person this
    tool is for: it makes every read a *writer* on the development database, so
    an open dashboard tab can make a hand-run ``import_projection_csv`` fail with
    ``database is locked``. It also mutates ``updated_at`` through
    ``TimestampMixin``'s ``onupdate`` — a read endpoint writing to the row it
    reads, held harmless only by a rollback nobody would notice deleting — and
    on PostgreSQL it stalls an import for the whole request while labelling
    players and serialising a model.

    So the guarantee is *observed* instead of *assumed*:
    :func:`_assert_cohort_is_stable` brackets every read between two runs of the
    canonical release and refuses if anything moved. A concurrent import can
    make this endpoint answer 409, and cannot make it answer 200 with a lineage
    block that does not describe the rates beside it. That is the smaller
    construction, it behaves identically on both dialects, and — unlike the
    lock — it is the mechanism the tests actually exercise.

    The trade in one line: **a lock prevents the race and blocks the owner's
    import; the digest detects it and asks the caller to retry.** For a
    single-user local tool where the writer is a person at a keyboard, the
    second is the right way round.
    """

    return session.scalar(select(ProjectionSource.id).where(ProjectionSource.source == source))


def _current_import_candidate(session: Session, *, source_id: int, season: str) -> int | None:
    """Propose the import this response should describe.

    Deliberately a *selector*, not a verifier. It proposes the newest import for
    one source and season; ``release_projection_import`` is the arbiter and
    rejects the proposal with ``StaleProjectionInputError`` if it disagrees. So
    if the canonical definition of "current" ever changes underneath this
    function, the endpoint fails closed with ``projections_not_current`` rather
    than serving an import the rest of the pipeline considers superseded.
    """

    return session.scalar(
        select(ProjectionImport.id)
        .where(
            ProjectionImport.source_id == source_id,
            ProjectionImport.season == season,
        )
        .order_by(ProjectionImport.imported_at.desc(), ProjectionImport.id.desc())
        .limit(1)
    )


def _released_import(
    session: Session, *, import_id: int, source: ExternalSource
) -> ReleasedProjectionImport:
    """Run the canonical release, mapping each refusal to its own code.

    Three outcomes, because they call for three different operator actions.

    ``projections_not_current`` — the import this response would have described
    is no longer the one on record. **Four raise sites, one fact.** Two are
    here: superseded by a newer import for the same source and season
    (``StaleProjectionInputError``), or removed outright between the selector
    and the release (``UnknownProjectionInputError``). A third is the audit read
    in the handler, which can miss the row for the same reason. A fourth —
    ``release_projection_import`` refusing an import that belongs to a different
    source — is mapped here and is unreachable, because the source id is
    resolved through ``uq_projection_sources_source`` and the candidate is
    filtered by it. An earlier version of this paragraph said "two ways" and
    "nothing else shares this code"; review enumerated the sites and both
    clauses were wrong. Every reachable one asks the caller for the same thing:
    re-request.

    ``projections_incomplete`` — the import exists and is current but carries no
    usable rows, which for a real CSV means every row failed identity
    resolution. The fix is in the crosswalk, not the file.
    ``MissingProjectionDataError``'s other raiser, a repeated ``player_id``
    within one import, is made inexpressible by
    ``uq_projections_import_player``, so the copy is safe for every reachable
    case.

    ``projections_incomplete_evidence`` — every other way the canonical release
    refuses. **The enumeration below was driven end to end in review, not read
    off the source, and the previous version of it was short by two:**

    1. ``profile_verified`` false on the import row;
    2. ``verified`` false on its profile-version row (same message, different row);
    3. the import's season outside the profile's verified season scope;
    4. immutable profile lineage that contradicts itself;
    5. a stored rate that is negative;
    6. a stored rate that is non-finite;
    7. a half-present made/attempted pair — **reachable only for three-pointers**,
       because ``projections`` has ``fg_volume_pair_complete`` and
       ``ft_volume_pair_complete`` CHECK constraints and no
       ``fg3_volume_pair_complete``;
    8. a ``projections`` row whose denormalised ``season`` disagrees with its
       import's.

    A ninth, "makes greater than attempts", is in the family by type and
    unreachable in practice: all three ``*_made_within_attempted`` CHECKs block
    it at the same ``+0.001`` tolerance the validator uses.

    **It stays one code**, under ``architect``'s rule that a family splits when
    two members imply different operator actions. Member 8 is the one that
    tests the rule — it looks like data repair rather than re-import — but
    re-importing the same bytes rewrites the whole row cohort through
    ``_import_projection_rows``, so its remedy converges with the rest at
    *produce a good import*. Splitting would also mean this route re-deriving
    which member fired, which is exactly the second verifier this module refuses
    to be.

    A consumer must render a summary true of every member and must **not**
    substring-match ``detail``, which is free-form English with interpolated ids
    rather than a contract surface. This is also the code any future
    ``ProjectionBlendError`` subclass lands on — deliberately, so a new refusal
    is a typed 409 rather than an untyped 500, and
    ``test_the_blending_error_family_is_pinned`` fails when the subclass set
    changes so that convergence is decided rather than inherited.
    """

    try:
        return release_projection_import(session, import_id=import_id, source=source)
    except (UnknownProjectionInputError, StaleProjectionInputError) as exc:
        raise _error(409, "projections_not_current", str(exc)) from exc
    except MissingProjectionDataError as exc:
        raise _error(409, "projections_incomplete", str(exc)) from exc
    except ProjectionBlendError as exc:
        raise _error(409, "projections_incomplete_evidence", str(exc)) from exc


def _projection_rows(session: Session, *, import_id: int) -> list[Projection]:
    """Load the rows this response carries.

    Same predicate and same ordering as the canonical release's own row load, in
    the same session and transaction. It is tempting to argue that SQLAlchemy's
    identity map therefore hands back the very objects the release digested, and
    an earlier version of this docstring did. **It does not follow:** the
    identity map holds weak references and ``release_projection_import`` discards
    the rows it loaded, so they are collectible and this query can re-fetch
    changed values under unchanged primary keys. Whether the rows moved is
    therefore established rather than argued — see
    :func:`_assert_cohort_is_stable`.
    """

    return list(
        session.scalars(
            select(Projection)
            .where(Projection.projection_import_id == import_id)
            .order_by(Projection.player_id)
        )
    )


def _assert_cohort_is_stable(
    session: Session,
    *,
    rows: list[Projection],
    released: ReleasedProjectionImport,
    source: ExternalSource,
) -> None:
    """Refuse a body that does not match the lineage block beside it.

    The failure this guards against is the one this whole module exists to
    close: a 200 whose ``projection_values_sha256`` describes one cohort while
    the rates beside it are another.

    **How it observes that, without becoming a second verifier.** It runs the
    canonical release a second time, after the rows have been read, and compares
    the two immutable lineage records whole. If anything the release attests to
    moved across the read — the digest over the normalised rates, the row count,
    the currency of the import, the profile lineage — the two records differ and
    the request is refused. Recomputing the digest here instead would mean
    re-implementing "normalised rates", which is a second definition of the exact
    thing the digest exists to pin; invoking the one canonical function twice is
    not.

    **What it can and cannot observe.** It cannot see a change made and exactly
    reverted between the two releases. It also costs a second row load and
    digest, which is the price of not trusting the lock — and the SQLite half of
    that lock was false until review drove it, so the price is worth paying.
    """

    if len(rows) != released.projection_count:
        raise _error(
            409,
            "projections_inconsistent_cohort",
            f"projection import {released.import_id} was released with "
            f"{released.projection_count} verified row(s) but {len(rows)} were read for this "
            "response; refusing to serve rates that contradict their own lineage block",
        )
    recheck = _released_import(session, import_id=released.import_id, source=source)
    if recheck != released:
        raise _error(
            409,
            "projections_inconsistent_cohort",
            f"projection import {released.import_id} was released as "
            f"{released.projection_values_sha256} but re-released as "
            f"{recheck.projection_values_sha256} after its rows were read; the cohort moved "
            "under this request and its lineage block would not describe the rates beside it",
        )


def _projection_players(session: Session, rows: list[Projection]) -> list[ProjectionPlayer]:
    """Label exactly the players the rates already contain, or refuse.

    The player set is taken from ``rows`` rather than by re-querying the
    projection cohort, so there is one definition of "who is in this response"
    and it is the one that produced the numbers.

    The set equality is then enforced rather than assumed. A short label list
    would render as unlabelled rows — a partially-labelled cohort that still
    looks like an answer — which is worse than a refusal. ``projections.player_id``
    is a foreign key with SQLite enforcement switched on, so this should be
    unreachable; it is driven directly against this function rather than through
    the route, because a guard nobody has made fire is an untested assertion.
    """

    player_ids = sorted({row.player_id for row in rows})
    players = [
        ProjectionPlayer(
            player_id=player_id,
            full_name=full_name,
            team_abbreviation=abbreviation,
            primary_position=primary_position,
        )
        for player_id, full_name, primary_position, abbreviation in session.execute(
            select(Player.id, Player.full_name, Player.primary_position, NbaTeam.abbreviation)
            .outerjoin(NbaTeam, Player.current_team_id == NbaTeam.id)
            .where(Player.id.in_(player_ids))
            .order_by(Player.id)
        )
    ]
    if [player.player_id for player in players] != player_ids:
        raise _error(
            409,
            "projections_inconsistent_cohort",
            "the cohort carries rates for players "
            f"{sorted(set(player_ids) - {player.player_id for player in players})} that have no "
            "player row",
        )
    return players


def _games_played_claims(session: Session, rows: list[Projection]) -> list[SourceGamesPlayedClaim]:
    """The source's own availability assumptions, for the rows in this cohort.

    Sparse on purpose: a source that published only rates has no row here, and
    inventing one to fill the shape is precisely what ADR-002 forbids.
    """

    projection_ids = [row.id for row in rows]
    player_id_by_projection = {row.id: row.player_id for row in rows}
    claims = [
        SourceGamesPlayedClaim(
            player_id=player_id_by_projection[projection_id],
            assumed_games_played=assumed_games_played,
            assumed_games_played_raw=assumed_games_played_raw,
        )
        for projection_id, assumed_games_played, assumed_games_played_raw in session.execute(
            select(
                SourceGamesPlayedAssumption.projection_id,
                SourceGamesPlayedAssumption.assumed_games_played,
                SourceGamesPlayedAssumption.assumed_games_played_raw,
            )
            .where(SourceGamesPlayedAssumption.projection_id.in_(projection_ids))
            .order_by(SourceGamesPlayedAssumption.projection_id)
        )
    ]
    return sorted(claims, key=lambda claim: claim.player_id)


def _rates(row: Projection) -> ProjectionRates:
    """Copy one row's canonical per-game fields into the response model.

    Driven by ``CANONICAL_STAT_FIELDS`` rather than a hand-written argument list
    so a field added to the schema and the profile registry cannot be silently
    missing from the API. ``test_projections_api`` asserts the two agree.
    """

    return ProjectionRates(
        player_id=row.player_id,
        **{field: getattr(row, field) for field in CANONICAL_STAT_FIELDS},
    )


@router.get(
    "/current",
    response_model=CurrentProjectionsResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
    summary="The current imported per-game projection cohort for one league's season",
)
def get_current_projections(
    league_id: int,
    session: SessionDep,
    request: Request,
    source: ExternalSource = Query(
        default=DEFAULT_PROJECTION_SOURCE,
        description="Registered projection CSV source to read. Defaults to Basketball Monster.",
    ),
) -> CurrentProjectionsResponse:
    require_loopback_host(
        request,
        error_code="projections_local_only",
        detail="Imported projections are only served to the local machine.",
    )
    if source not in PROJECTION_IMPORT_SOURCES:
        # `ExternalSource` is one vocabulary for two jobs: projection publishers
        # and identity-anchor namespaces. `nba` and `fantrax` are valid enum
        # members and will pass FastAPI's 422 validation, so the narrower
        # membership question has to be asked here and answered distinguishably.
        raise _error(
            400,
            "projections_source_unsupported",
            f"{source.value!r} is an identity-anchor namespace, not a projection CSV source",
        )

    league = session.get(League, league_id)
    if league is None:
        raise _error(404, "projections_league_not_found", f"no league {league_id}")
    response_league_id = league.id
    response_season = league.season

    # No lock is taken; see `_projection_source_id`. Correctness comes from
    # bracketing every read below between two runs of the canonical release,
    # which observes a cohort that moved rather than assuming one cannot.
    source_id = _projection_source_id(session, source=source)
    if source_id is None:
        raise _error(
            409,
            "projections_source_not_imported",
            f"{source.value} has never been registered as a projection source; import a "
            f"{source.value} CSV for season {response_season!r} first",
        )

    import_id = _current_import_candidate(session, source_id=source_id, season=response_season)
    if import_id is None:
        raise _error(
            409,
            "projections_source_not_imported",
            f"no {source.value} projection import exists for season {response_season!r}",
        )

    # --- everything between this release and the one in `_assert_cohort_is_stable`
    # --- is bracketed: if any of it moved, the request is refused rather than served.
    released = _released_import(session, import_id=import_id, source=source)
    rows = _projection_rows(session, import_id=import_id)
    players = _projection_players(session, rows)
    claims = _games_played_claims(session, rows)
    # An explicit column read rather than `session.get`, deliberately.
    # `release_projection_import` has already put this row in the identity map,
    # so `session.get` would answer from memory and could never observe the row
    # going away — a refusal branch that reads correctly and can never fire,
    # which is the defect class this repository keeps finding. This is a real
    # query, and `test_an_import_that_disappears_mid_request_is_refused` drives
    # it with a real committed delete.
    audit = session.execute(
        select(
            ProjectionImport.original_filename,
            ProjectionImport.row_count,
            ProjectionImport.matched_count,
            ProjectionImport.needs_review_count,
            ProjectionImport.unmatched_count,
            ProjectionImport.rejected_count,
        ).where(ProjectionImport.id == import_id)
    ).first()
    if audit is None:
        # Same code as a superseded import because the caller's action is
        # identical — re-request. With no lock this is reachable, not defensive.
        raise _error(
            409,
            "projections_not_current",
            f"projection import {import_id} disappeared while it was being read",
        )
    _assert_cohort_is_stable(session, rows=rows, released=released, source=source)
    # --- end of the bracketed region.

    return CurrentProjectionsResponse(
        league_id=response_league_id,
        season=response_season,
        source=source,
        lineage=ProjectionLineage(
            projection_import=ProjectionImportLineage(
                import_id=released.import_id,
                source=released.source,
                season=released.season,
                imported_at=released.imported_at,
                content_sha256=released.content_sha256,
                profile_id=released.profile_id,
                profile_version=released.profile_version,
                profile_definition_sha256=released.profile_definition_sha256,
                projection_values_sha256=released.projection_values_sha256,
                projection_count=released.projection_count,
                assumed_scoring_type=released.assumed_scoring_type,
                original_filename=audit[0],
                row_count=audit[1],
                matched_count=audit[2],
                needs_review_count=audit[3],
                unmatched_count=audit[4],
                rejected_count=audit[5],
            ),
        ),
        players=players,
        projections=[_rates(row) for row in rows],
        source_games_played_assumptions=claims,
    )
