"""Enumerated values used across the schema.

All of these are stored as strings via :func:`hoops_gm.db.base.portable_enum`,
which emits a VARCHAR plus a CHECK constraint. Adding a member requires a
migration to widen that constraint, which is the point: an unrecognised value
should be a loud failure, not a silent row.

That claim was false when this module was first written — ``create_constraint``
defaults to ``False`` and had been omitted, so no CHECK existed and an unknown
value inserted cleanly through any path that bypassed the ORM. See
``db/base.py`` for the detail.
"""

from __future__ import annotations

import enum


class ExternalSource(enum.StrEnum):
    """Systems that have their own idea of a player's identifier.

    Risk R7: these disagree, constantly, and **no two of them share a key**.
    Fantrax's ``getPlayerIds`` exposes ``statsIncId``, ``rotowireId`` and
    ``sportRadarId`` — none of which is an NBA.com identifier — so there is no
    anchor pair to match against. Every cross-source match is inferred, which
    makes ``confidence``, ``match_method`` and ``is_manual_override``
    load-bearing rather than metadata.

    An earlier version of this docstring claimed ``NBA`` and ``FANTRAX`` were a
    clean anchor pair. They are not; that was disproved by hitting the endpoint.

    Adding a member here **does** require a migration: these are stored as
    VARCHAR with a CHECK constraint, so the constraint has to be widened. Phase 2
    owns adding the Fantrax cross-reference sources above, since it owns the
    crosswalk and knows which of them are worth recording.
    """

    NBA = "nba"
    FANTRAX = "fantrax"
    #: Cross-reference identifiers that Fantrax carries for other providers.
    #: Recorded as first-class sources by Phase 2 for two reasons that pay off
    #: immediately rather than hypothetically: they de-duplicate *within*
    #: Fantrax, which contains genuine duplicate names (two "Johnson, Jalen",
    #: two "Jackson, Justin"), and they survive Fantrax rotating its own
    #: ``fantraxId`` between seasons.
    #:
    #: They are **not** a bridge to NBA.com. That was investigated as the plan
    #: suggested and the bridge does not exist: no free, stable public dataset
    #: maps a Sportradar GUID to an NBA.com person id, the open ID datasets
    #: carry Basketball-Reference/ESPN/Spotrac instead and are themselves built
    #: by name matching, and Sportradar's own mapping endpoint is behind a
    #: commercial subscription — an owner-only decision.
    FANTRAX_STATS_INC = "fantrax_stats_inc"
    FANTRAX_ROTOWIRE = "fantrax_rotowire"
    FANTRAX_SPORTRADAR = "fantrax_sportradar"
    FANTASYPROS = "fantasypros"
    HASHTAG = "hashtag"
    BASKETBALL_MONSTER = "basketball_monster"
    DARKO = "darko"
    MANUAL = "manual"


class FieldEvidence(enum.StrEnum):
    """What one field says about whether two records are the same person.

    Three values, not two, and that is the point. Phase 1 left open whether a
    single ``confidence`` float suffices or whether per-field evidence is
    needed. Phase 2 measured it and the answer is per-field: **1,206 of the
    1,788 Fantrax player rows carry ``team: "(N/A)"``**, so for two thirds of
    the payload the team says nothing at all. A scalar cannot distinguish a
    team that is unknown from a team that is known and contradicts — the first
    is an ordinary free agent and probably a correct match, the second is
    probably two different people. A human adjudicating the tail needs to know
    which, so it is stored per field.
    """

    AGREE = "agree"
    DISAGREE = "disagree"
    UNKNOWN = "unknown"


class ParticipationOutcome(enum.StrEnum):
    """What happened to one player for one of their team's games.

    The distinction between ``INACTIVE`` and ``UNKNOWN`` carries real weight.
    A player absent from every list for a game is not *known* to have been
    inactive — they may not have been on the roster, may have been on a
    G-League assignment, or the source may simply have a gap. Recording that as
    ``INACTIVE`` manufactures availability evidence out of silence, and
    availability is the quantity this entire project exists to model.
    """

    PLAYED = "played"
    DID_NOT_PLAY = "did_not_play"
    DID_NOT_DRESS = "did_not_dress"
    NOT_WITH_TEAM = "not_with_team"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class DnpReason(enum.StrEnum):
    """Normalised absence reason, derived from free text that is also kept.

    House rule: **do not trust stated DNP reasons.** "Rest" is routinely
    laundered as a minor ailment, and the vocabulary is inconsistent between
    seasons and scorers — the same 2025-26 season yielded
    ``"DNP - Coach's Decision"``, ``"DND - Injury/Illness"``,
    ``"NWT - Not With Team"`` and ``"NWT-Return to Competition
    Reconditioning"``, the last with no spaces around its hyphen.

    So this is a convenience for querying, not a fact. Unrecognised text maps
    to ``OTHER`` rather than being forced into the nearest category, and
    ``player_participation.raw_comment`` retains the original so a better
    normalisation can be re-derived. ``NONE_GIVEN`` means no reason was stated
    at all, which is different from a stated reason we did not recognise.
    """

    COACHES_DECISION = "coaches_decision"
    INJURY_OR_ILLNESS = "injury_or_illness"
    REST = "rest"
    PERSONAL = "personal"
    SUSPENSION = "suspension"
    G_LEAGUE = "g_league"
    TRADE_PENDING = "trade_pending"
    CONDITIONING = "conditioning"
    NOT_WITH_TEAM = "not_with_team"
    OTHER = "other"
    NONE_GIVEN = "none_given"


class InjuryReportStatus(enum.StrEnum):
    """The NBA's own closed vocabulary for the official injury report.

    Unlike :class:`DnpReason`, this is not free text a scorer typed — it is
    the fixed designation the league's reporting policy requires a team to
    pick (official.nba.com, verified 2026-08-17): OUT, DOUBTFUL, QUESTIONABLE,
    PROBABLE or AVAILABLE. Five values, and only five, which is why the parser
    treats anything else as :class:`~hoops_gm.ingest.errors.SourceContractError`
    rather than an ``OTHER`` bucket — an unrecognised *status* here means the
    league changed its designations, not that a scorer wrote something unusual.

    ``NOT_YET_SUBMITTED`` is not a player status at all: it is the report
    saying a team has not filed one for this slate yet. It carries no player
    name, and the importer does not manufacture one.
    """

    OUT = "out"
    DOUBTFUL = "doubtful"
    QUESTIONABLE = "questionable"
    PROBABLE = "probable"
    AVAILABLE = "available"
    NOT_YET_SUBMITTED = "not_yet_submitted"


class AuctionValueKind(enum.StrEnum):
    """Whether one published dollar figure is an estimate or an observed price.

    **Per value, not per publisher.** Yahoo's draft-analysis tool publishes a
    projected auction value *and* an observed average auction value for the
    same player in the same table, so deriving the kind from the source name
    is wrong by construction — one source emits both. Pulling that table into
    a single "value" column silently averages a model's output together with
    market observation, which are the two things this layer exists to keep
    apart.

    ``PROJECTED`` is somebody's model converted to dollars. ``OBSERVED_MARKET``
    is what somebody actually paid. Only the second is evidence about the
    market; the first is evidence about a competitor's opinion.
    """

    PROJECTED = "projected"
    OBSERVED_MARKET = "observed_market"


class BasisEvidence(enum.StrEnum):
    """How we came to know one of a published price list's basis facts.

    Three values, not two, for the same reason :class:`FieldEvidence` has
    three: a fact we looked for and could not find is a different claim from
    one the source printed, and both are different from one we worked out
    ourselves. Collapsing them loses precisely the distinction that decides
    whether a dollar figure can be compared against anything.

    The live case is FantraxHQ, whose auction table prints no budget at all.
    A budget recorded as ``INFERRED`` obliges us to say how it was inferred;
    recorded as ``UNESTABLISHED`` it stops the numbers being used as a
    benchmark until someone establishes it. Left blank it would have been
    indistinguishable from a budget nobody thought to check.
    """

    #: The source printed it. Quote it in the note or the adapter page.
    STATED = "stated"
    #: We worked it out. ``basis_note`` must say from what, so the next reader
    #: can disagree with the reasoning rather than inherit the conclusion.
    INFERRED = "inferred"
    #: We looked and could not establish it. An investigated absence, which is
    #: evidence; not a blank, which is silence.
    UNESTABLISHED = "unestablished"


class AuctionValueDerivation(enum.StrEnum):
    """The *method* a publisher used to arrive at a dollar figure.

    Kept separate from what the method consumed
    (:class:`AuctionValueInputKind`), because the two answer different
    questions and recording only the first hides the failure that matters.

    Hashtag Basketball, Basketball Monster, RotoWire and FantraxHQ all run the
    same z-score → value-above-replacement → budget-distribution arithmetic,
    over projections that appear to be independently generated at each. Their
    outputs therefore correlate strongly, and that correlation is good evidence
    they do the same maths and weak evidence they agree about players. A single
    "derived from projections" field cannot express that; two fields can.
    """

    Z_SCORE_BUDGET_DISTRIBUTION = "z_score_budget_distribution"
    EDITORIAL = "editorial"
    OBSERVED_PLATFORM_AUCTIONS = "observed_platform_auctions"
    #: Investigated and not determined. Say where you looked in
    #: ``derivation_evidence``, which is CHECK-constrained to be non-empty.
    UNESTABLISHED = "unestablished"


class AuctionValueInputKind(enum.StrEnum):
    """What kind of upstream quantity a publisher's method consumed."""

    PROJECTIONS = "projections"
    ADP = "adp"
    OBSERVED_AUCTIONS = "observed_auctions"
    EDITORIAL_JUDGEMENT = "editorial_judgement"


class MatchMethod(enum.StrEnum):
    """How an external identifier came to be attached to a canonical player."""

    ANCHOR_ID = "anchor_id"
    EXACT_NAME = "exact_name"
    NORMALIZED_NAME = "normalized_name"
    NAME_TEAM_POSITION = "name_team_position"
    FUZZY = "fuzzy"
    MANUAL_OVERRIDE = "manual_override"


class PlayerStatus(enum.StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    TWO_WAY = "two_way"
    G_LEAGUE = "g_league"
    RETIRED = "retired"
    UNKNOWN = "unknown"


class Conference(enum.StrEnum):
    EAST = "East"
    WEST = "West"


class SeasonType(enum.StrEnum):
    PRESEASON = "preseason"
    REGULAR = "regular"
    PLAY_IN = "play_in"
    PLAYOFFS = "playoffs"


class GameStatus(enum.StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINAL = "final"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"


class ScoringType(enum.StrEnum):
    H2H_CATEGORIES = "h2h_categories"
    H2H_POINTS = "h2h_points"
    H2H_EACH_CATEGORY = "h2h_each_category"
    ROTO = "roto"
    POINTS = "points"


class DraftType(enum.StrEnum):
    SNAKE = "snake"
    AUCTION = "auction"
    LINEAR = "linear"
    UNKNOWN = "unknown"


class DraftStatus(enum.StrEnum):
    """Where a recorded draft is in its own life.

    Derived from the event log rather than stored, so there is only ever one
    fact to keep consistent. ``SETUP`` means participants exist and nothing has
    been selected; ``IN_PROGRESS`` means at least one live selection;
    ``CLOSED`` means a ``closed`` event is live.

    There is deliberately no ``COMPLETE``-by-fullness value. A mock auction
    routinely ends with slots unfilled because people leave, so "every slot is
    taken" is not the same claim as "this draft is over" and merging them would
    make the second unrecoverable. Fullness is published separately as
    ``slots_filled``/``total_roster_slots``.
    """

    SETUP = "setup"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class DraftEventType(enum.StrEnum):
    """One entry in a draft's append-only log.

    The log is the source of truth and current state is derived from it. These
    six values are what a person recording a draft — snake or auction — can
    actually observe. Nothing here is a recommendation, a valuation or a price
    estimate: a ``sale`` amount is the price a human watched clear, not a price
    anything computed.

    ``VOID`` is why the log can stay append-only while still being correctable.
    A mistyped pick is not deleted and not edited; a ``void`` naming its
    sequence is appended, and derivation skips the superseded event. What
    happened *and* what we later believed about it both stay readable.
    """

    #: An ordered-draft (snake/linear) selection.
    PICK = "pick"
    #: An auction lot opened. Carries the nominated player.
    NOMINATION = "nomination"
    #: An auction bid on the open lot. The lot names the player, so a bid does
    #: not repeat it — a bid that could name a different player than its lot is
    #: a disagreement waiting to be recorded.
    BID = "bid"
    #: An auction lot cleared: this participant paid this amount.
    SALE = "sale"
    #: Supersedes an earlier event of this draft by its sequence number.
    VOID = "void"
    #: The recorder declaring the draft over.
    CLOSED = "closed"


class DraftToolUsage(enum.StrEnum):
    """Whether this project's own numbers drove the bidding in a draft.

    Required at creation with **no default**, because R38's circularity risk is
    asymmetric: defaulting to ``BLIND`` would silently launder contaminated
    evidence into the clean control group, and a default of ``INSTRUMENTED``
    would throw away the only market data that can never be accused of echoing
    us. Neither error is recoverable after the fact — the information exists
    only while the draft is being recorded (``docs/mocks/README.md``).

    This unit stores the value and never reads it. Weighting a contaminated
    corpus differently is ``aav-empirical``'s and ``opponent-calibration``'s,
    behind the Model gate.
    """

    #: The tool was not used, did not exist, or was deliberately not consulted.
    BLIND = "blind"
    #: Consulted for some decisions.
    PARTIAL = "partial"
    #: Our own values drove bidding.
    INSTRUMENTED = "instrumented"


class CategoryKind(enum.StrEnum):
    """Counting versus ratio.

    This distinction is the guard against the single most common bug in
    homebrew fantasy tools: treating FG% and FT% as raw percentages. A ratio
    category carries a numerator and a denominator stat so that impact can be
    volume-weighted downstream. A 90% free-throw shooter on one attempt is
    worthless, and the schema has to make that expressible.
    """

    COUNTING = "counting"
    RATIO = "ratio"


class RosterStatus(enum.StrEnum):
    ACTIVE = "active"
    RESERVE = "reserve"
    INJURED_RESERVE = "injured_reserve"
    MINORS = "minors"


class MatchupStatus(enum.StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    FINAL = "final"


class CategoryOutcome(enum.StrEnum):
    HOME = "home"
    AWAY = "away"
    TIE = "tie"


class TransactionType(enum.StrEnum):
    ADD = "add"
    DROP = "drop"
    WAIVER_CLAIM = "waiver_claim"
    TRADE = "trade"
    DRAFT = "draft"
    IR_MOVE = "ir_move"
    OTHER = "other"


class RefreshArtifactType(enum.StrEnum):
    """The broad lineage domains a refresh can be registered against.

    Deliberately four coarse values, not a taxonomy of every model or feed
    that will ever exist. ``schedule`` is the resolved NBA calendar,
    ``source`` identifies other upstream snapshots, and ``projection`` and
    ``model`` are quant outputs. This is the cohort key downstream consumers
    compare a claimed version against; it is not, and must not become, a place
    to encode what a version *means*.
    """

    SCHEDULE = "schedule"
    PROJECTION = "projection"
    MODEL = "model"
    SOURCE = "source"


class StatScope(enum.StrEnum):
    """Whether a season-stats row is for one team or the season total.

    A traded player has a row per team plus a combined row. Using a nullable
    ``team_id`` in the unique key would not work: SQL treats NULLs as distinct,
    so duplicate totals would slip through on both dialects.
    """

    TEAM = "team"
    TOTAL = "total"
