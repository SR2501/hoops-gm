"""ADR-008 layer purity, made structural rather than documented.

ADR-008 orders the layers and says information flows one way only::

    observations -> projections -> availability -> valuation -> rankings/values
       (facts)      (production)    (p(play))      (fused)        (TERMINAL)

The defect this prevents is **circularity**, and circularity does not crash.
If a composite value or a published ranking feeds back into an availability or
projection input, the model starts agreeing with itself and every downstream
figure gets more confident and less true. There is no green-test signal for
that, which is why the constraint has to be a mechanism rather than a rule
somebody remembers.

## Why this is a registry rather than a convention

The instruction in the backlog is "make it inexpressible rather than merely
documented", and this repository has been bitten three times by rules that were
correct when written and decayed silently afterwards: a census that was exactly
complete until an unrelated merge, a guard keyed on a proxy question, and five
tests deleted by a refactor with the suite still green.

So the membership rule here is a **closed set** rather than a pattern over
spellings. Two closed sets, in fact, both taken from ``Base.metadata``:

* every mapped table must appear in :data:`TABLE_LAYERS`, and
* every declared foreign key is a flow, checked against :func:`flow_permitted`.

Neither is a list of doors somebody enumerated. A table that arrives without a
layer, or a foreign key that points the wrong way, fails on **arrival** — at
import of :mod:`hoops_gm.db.models`, not merely in a test somebody might not
run. That is the same shape as ``test_portability.py``'s
``_DIALECT_AWARE_MODULES`` and ``test_store_creating_readers.py``'s
``SANCTIONED_STORE_OPENERS``.

## Read the scope limits before treating this as coverage

:data:`FLOW_SCAN_LIMIT`, :data:`IMPORT_TIME_LIMIT` and :data:`GRAIN_LIMIT` are
asserted constants, not comments, for the reason
``test_store_creating_readers.SCAN_LIMIT`` is: a limitation in a docstring gets
summarised away, and a limitation pinned by an assertion breaks a test when
someone deletes it. Note that they pin *documentation* — widening a scan to
close a gap leaves the assertion untouched — which is inherent to the pattern
and is why each says what remains uncovered rather than what is covered.
"""

from __future__ import annotations

import enum
from typing import Final

from sqlalchemy import MetaData


class DataLayer(enum.StrEnum):
    """Which layer of ADR-008 a stored quantity belongs to.

    The five names come from ADR-008's decision block verbatim.
    :attr:`MARKET` and :attr:`COMPARISON` are the two the ADR's prose requires
    but its arrow diagram does not name; see :data:`LAYER_RANK` for why each is
    ranked where it is rather than folded into a neighbour.
    """

    #: Facts, and aggregates of facts computed only from other facts.
    OBSERVATIONS = "observations"
    #: Per-game production rates, with any games-played assumption stripped.
    PROJECTIONS = "projections"
    #: ``p(play)`` and everything derived to predict it.
    AVAILABILITY = "availability"
    #: Production and availability fused. ADR-002's separation, resolved.
    VALUATION = "valuation"
    #: Our own rankings and dollar values. Outputs, never inputs.
    TERMINAL = "terminal"
    #: Somebody *else's* published aggregate — AAV, consensus rank, tiers.
    #: Already terminal-grade when it arrives: it contains production, an
    #: availability assumption and a scoring-format assumption fused together,
    #: which is precisely what ADR-008 forbids blending in.
    MARKET = "market"
    #: Model-versus-market: the one place ADR-008 clause 3 permits our terminal
    #: outputs and an external aggregate to meet. Consumes both, feeds nothing.
    COMPARISON = "comparison"


#: How far down the pipeline each layer sits. **Descriptive, not the rule.**
#:
#: This exists so the store can order layers in a raw query, and for nothing
#: else. :func:`flow_permitted` does *not* consult it. An earlier revision of
#: this module made rank the flow rule — ``source is target or rank[source] <
#: rank[target]`` — and an independent review found the hole that construction
#: cannot avoid: it permitted ``valuation -> market``, ``availability ->
#: market`` and ``projections -> market``, because those ranks really are lower
#: than the market's. Every one of those is R38. A ``published_auction_values``
#: row taking a foreign key from our own fused value is our output laundered
#: back in as somebody else's evidence, and it type-checked.
#:
#: The rule ADR-008 clause 3 actually states is about **independence**:
#: divergence between our number and the market's is only a signal if the two
#: sides were computed separately. That is not "market is late in the
#: pipeline", it is "the market side consumes nothing we derived" — a statement
#: about a *set of edges*, which no single integer can encode. So the edges are
#: enumerated in :data:`PERMITTED_FLOWS` and the rank is demoted to a label.
#:
#: :attr:`DataLayer.MARKET` shares rank 4 with :attr:`DataLayer.TERMINAL`
#: because it is terminal-grade on arrival, not because the number does any
#: work. ``data_layer_registry`` pins the pairing with a CHECK so a stored rank
#: cannot disagree with its stored layer.
LAYER_RANK: Final[dict[DataLayer, int]] = {
    DataLayer.OBSERVATIONS: 0,
    DataLayer.PROJECTIONS: 1,
    DataLayer.AVAILABILITY: 2,
    DataLayer.VALUATION: 3,
    DataLayer.TERMINAL: 4,
    DataLayer.MARKET: 4,
    DataLayer.COMPARISON: 5,
}


#: Every cross-layer flow ADR-008 permits, enumerated. Same-layer flow is
#: permitted separately by :func:`flow_permitted` (clause 1, "aggregate only
#: within a layer") and is deliberately not listed here.
#:
#: Read ``(source, target)`` as "a quantity at ``source`` may be an input to
#: one at ``target``". Anything absent is refused; there is no default and no
#: arithmetic, which is the whole reason this is a set rather than a rank.
#:
#: Three groups, and the second and third are the ones that matter:
#:
#: * **Our pipeline** flows one way. Every earlier layer may feed every later
#:   one, so ADR-008's arrow diagram is reproduced exactly.
#: * **Into the market: identity only.** ``observations -> market`` is here
#:   because a published value is about a player and has to say which one.
#:   ``projections``, ``availability``, ``valuation`` and ``terminal`` are all
#:   absent, and that absence is R38 made inexpressible: nothing we derived can
#:   become part of a market row at any weight.
#: * **Out of the market: comparison only.** ``market -> comparison`` is the
#:   single outbound edge, which is ADR-008 clause 3 — compared against, never
#:   blended. ``market -> terminal`` is absent, which is clause 5: the
#:   draft-day rankings are ours alone.
#:
#: :attr:`DataLayer.COMPARISON` appears only ever as a target. That it "feeds
#: nothing" used to be an accident of it holding the highest rank; here it is a
#: property of the set, and ``test_comparison_feeds_nothing`` asserts it
#: directly rather than inferring it from an ordering.
PERMITTED_FLOWS: Final[frozenset[tuple[DataLayer, DataLayer]]] = frozenset(
    {
        # Our pipeline, in ADR-008's order.
        (DataLayer.OBSERVATIONS, DataLayer.PROJECTIONS),
        (DataLayer.OBSERVATIONS, DataLayer.AVAILABILITY),
        (DataLayer.OBSERVATIONS, DataLayer.VALUATION),
        (DataLayer.OBSERVATIONS, DataLayer.TERMINAL),
        (DataLayer.PROJECTIONS, DataLayer.AVAILABILITY),
        (DataLayer.PROJECTIONS, DataLayer.VALUATION),
        (DataLayer.PROJECTIONS, DataLayer.TERMINAL),
        (DataLayer.AVAILABILITY, DataLayer.VALUATION),
        (DataLayer.AVAILABILITY, DataLayer.TERMINAL),
        (DataLayer.VALUATION, DataLayer.TERMINAL),
        # Into the market: which player it is about, and nothing else of ours.
        # Layer granularity is too coarse to say that on its own — OBSERVATIONS
        # is the broadest layer and includes ``draft_events``, whose prices our
        # own recommendations can have moved. Narrowed per-table by
        # :data:`MARKET_IDENTITY_SOURCES`.
        (DataLayer.OBSERVATIONS, DataLayer.MARKET),
        # Everything may be compared. Comparison feeds nothing.
        (DataLayer.OBSERVATIONS, DataLayer.COMPARISON),
        (DataLayer.PROJECTIONS, DataLayer.COMPARISON),
        (DataLayer.AVAILABILITY, DataLayer.COMPARISON),
        (DataLayer.VALUATION, DataLayer.COMPARISON),
        (DataLayer.TERMINAL, DataLayer.COMPARISON),
        (DataLayer.MARKET, DataLayer.COMPARISON),
    }
)


#: The number of ordered distinct layer pairs the rule has to decide.
#:
#: Pinned, and asserted against ``len(DataLayer)``, so an eighth layer cannot
#: be added without someone deciding all fourteen of its new edges. Under the
#: old rank rule a new member silently inherited a verdict for every pair from
#: its integer; here an unlisted pair is refused, which is safe, but the pin
#: makes it *reviewed* rather than merely safe.
FLOW_MATRIX_SIZE: Final[int] = 42


#: Layers with no table yet, pinned so the first one to arrive is reviewed.
#:
#: An empty layer is not dead vocabulary — it is the half of ADR-008 this
#: schema has not reached. Recording *which* halves are empty means the day a
#: valuation table lands, ``test_empty_layers_are_still_empty`` goes red and
#: somebody looks at the flow rule with a real table in front of them, instead
#: of the layer quietly acquiring members nobody classified against the ADR.
#:
#: The invariant that makes this load-bearing rather than decorative is that
#: this set and the populated layers **partition** :class:`DataLayer`, asserted
#: in that same test. Without it the constant was inert: review gutted it to
#: ``frozenset()`` and all 44 tests still passed, because the assertion beside
#: it never mentioned the constant at all.
LAYERS_WITHOUT_TABLES: Final[frozenset[DataLayer]] = frozenset(
    {
        DataLayer.AVAILABILITY,
        DataLayer.VALUATION,
        DataLayer.TERMINAL,
        DataLayer.COMPARISON,
    }
)


#: Every mapped table, and the layer its rows belong to.
#:
#: Completeness is not asserted here, it is checked: :func:`validate_layers`
#: compares this against ``Base.metadata.tables`` in both directions and
#: :mod:`hoops_gm.db.models` calls it at import. A table added without an entry
#: raises :class:`LayerViolation` before anything can query it.
#:
#: Assignment is per table because that is the grain the schema already uses —
#: the three existing ``data_layer`` columns are each pinned to one literal by
#: a CHECK, so no table today holds rows at two layers. See :data:`GRAIN_LIMIT`.
TABLE_LAYERS: Final[dict[str, DataLayer]] = {
    # --- observations: facts, and aggregates computed only from facts --------
    # Identity and reference. Not modelled quantities, and everything is
    # entitled to consume them, which is what rank 0 means.
    "nba_teams": DataLayer.OBSERVATIONS,
    "players": DataLayer.OBSERVATIONS,
    "player_external_ids": DataLayer.OBSERVATIONS,
    # Observed NBA facts.
    "nba_games": DataLayer.OBSERVATIONS,
    "team_schedule": DataLayer.OBSERVATIONS,
    "player_game_logs": DataLayer.OBSERVATIONS,
    "player_season_stats": DataLayer.OBSERVATIONS,
    "player_participation": DataLayer.OBSERVATIONS,
    "injury_report_entries": DataLayer.OBSERVATIONS,
    # Observation-layer aggregates. `absence_splits` already carries a
    # `data_layer = 'observations'` CHECK, so this entry restates a fact the
    # database is enforcing rather than adding a new claim.
    "absence_split_runs": DataLayer.OBSERVATIONS,
    "absence_splits": DataLayer.OBSERVATIONS,
    # Schedule context now sits at PROJECTIONS — see that section for why.
    # Observed league state and configuration.
    "leagues": DataLayer.OBSERVATIONS,
    "fantasy_teams": DataLayer.OBSERVATIONS,
    "rosters": DataLayer.OBSERVATIONS,
    "roster_slots": DataLayer.OBSERVATIONS,
    "scoring_periods": DataLayer.OBSERVATIONS,
    "matchups": DataLayer.OBSERVATIONS,
    "matchup_category_results": DataLayer.OBSERVATIONS,
    "transactions": DataLayer.OBSERVATIONS,
    "league_settings_snapshots": DataLayer.OBSERVATIONS,
    "league_scoring_profiles": DataLayer.OBSERVATIONS,
    "league_scoring_categories": DataLayer.OBSERVATIONS,
    "league_deadline_calendars": DataLayer.OBSERVATIONS,
    # What a person watched happen in a draft. `draft_events.amount` is a price
    # a human saw clear, not a price anything computed — see DraftEventType.
    "drafts": DataLayer.OBSERVATIONS,
    "draft_participants": DataLayer.OBSERVATIONS,
    "draft_events": DataLayer.OBSERVATIONS,
    # What a machine read off Fantrax about a draft, with the identity of the
    # source artifact. A claim, not a pick — kept at the same layer as
    # the log it feeds because it is the same kind of thing: an observation of
    # the outside world, with nothing computed in it.
    "draft_feed_observations": DataLayer.OBSERVATIONS,
    # Unique rendered-board content readings, including valid zero-pick boards.
    "draft_source_board_readings": DataLayer.OBSERVATIONS,
    # Latest rendered-board read/refusal state. Source evidence only.
    "draft_source_board_states": DataLayer.OBSERVATIONS,
    # Raw transport and provenance.
    "bridge_payloads": DataLayer.OBSERVATIONS,
    "refresh_runs": DataLayer.OBSERVATIONS,
    # Facts about the schema itself. Rank 0 is the honest answer twice over:
    # any layer may read it, and nothing higher may write into it.
    "data_layer_registry": DataLayer.OBSERVATIONS,
    "data_layer_flows": DataLayer.OBSERVATIONS,
    # --- projections: per-game rates, games-played assumption stripped -------
    "projection_sources": DataLayer.PROJECTIONS,
    "projection_profile_versions": DataLayer.PROJECTIONS,
    "projection_imports": DataLayer.PROJECTIONS,
    "projections": DataLayer.PROJECTIONS,
    # The source's own durability guess, kept one-to-one with the projection it
    # was stripped from. Projection-layer provenance, deliberately *not*
    # availability: the availability model overrides it and never blends it.
    #
    # Open question, raised by review and escalated rather than settled here:
    # this is somebody else's availability estimate, and the argument that put
    # the auction tables at MARKET applies to it too. It stays at PROJECTIONS
    # because MARKET now accepts nothing derived from us, and this table's
    # `projection_id` foreign key would become a violation — so the two
    # findings genuinely conflict and `quant` owns which one wins. Until then,
    # note the honest limit: "never blends" is a convention here, because
    # PROJECTIONS -> AVAILABILITY is a permitted flow and an availability table
    # taking a foreign key to this one would be accepted.
    "source_games_played_assumptions": DataLayer.PROJECTIONS,
    # Schedule context. Not facts: `opponent_context.blowout_probability` is a
    # fitted probability carrying `blowout_model_version` and `training_cutoff`,
    # and `schedule_context.py` says so in its first paragraph — "the context
    # here is modelling output", "used to condition p(play) and reliability".
    # Recording that as an observation would launder a model output into
    # apparent evidence, which is the exact pattern in ADR-008's Context.
    #
    # PROJECTIONS rather than AVAILABILITY because they *condition* p(play):
    # they have to sit earlier than the thing they are an input to. This also
    # leaves the legitimate improvement expressible — conditioning blowout risk
    # on availability would be AVAILABILITY -> PROJECTIONS and correctly
    # refused, but conditioning it on projections is permitted, and at rank 0
    # neither was.
    "opponent_context": DataLayer.PROJECTIONS,
    "off_night_slates": DataLayer.PROJECTIONS,
    # --- market: what somebody else published -------------------------------
    "auction_value_sources": DataLayer.MARKET,
    "auction_value_source_inputs": DataLayer.MARKET,
    "auction_value_imports": DataLayer.MARKET,
    "published_auction_values": DataLayer.MARKET,
}


#: What the flow check does **not** see, stated because the gap is easy to
#: mistake for coverage.
#:
#: It reads **declared foreign keys**, and there are two ways a stored
#: cross-layer reference escapes that, not one:
#:
#: * A value read out of a market row in Python and written into a projection
#:   row leaves no foreign key behind.
#: * An identifier column that holds another table's key *without declaring a
#:   foreign key* is structural, stored, and still invisible. An
#:   ``expected_games.seed_published_auction_value_id INTEGER`` with no foreign
#:   key would be exactly the defect ADR-008 forbids and would pass.
#:
#: **No such column exists today, and an earlier version of this note said
#: otherwise.** It claimed ``published_auction_values.source_player_id`` and
#: ``auction_value_imports.profile_id`` were "two of the ten such columns in the
#: schema today". A fourth review checked all ten and every one is a
#: *foreign-system* identifier or a config profile name - nba_api's team and
#: game ids, Fantrax's league, team and transaction ids, parse-profile names,
#: and what an auction source called a player. Not one holds the key of another
#: mapped table. The number of columns matching the defect described above is
#: **zero**. The sentence that made this limit feel load-bearing was the one
#: part of it that was false, which is worth leaving on the record: the count
#: was reproducible and the claim it supported was not, and a reproducible
#: number is exactly what makes an unsupported claim beside it look checked.
#:
#: So :data:`NAKED_IDENTIFIER_COLUMNS` is a tripwire on *arrival*, not a
#: measurement of a live gap. It is keyed on the ``_id`` spelling, which is
#: wrong in both directions: ``seed_auction_ref`` would be missed, and all ten
#: it currently counts are false positives. It is kept because the alternative
#: - inferring which columns are references - is precisely what the absent
#: foreign key denies you.
#:
#: A third case belongs to :data:`GRAIN_LIMIT` rather than here, and is worth
#: naming because it is live: ``draft_events`` sits at ``observations`` and
#: ``draft_events.amount`` is "a price a human saw clear". If you bid your own
#: recommended number and it clears, an observations table now holds a figure
#: that came from our terminal layer, with this check's full blessing. That is
#: R38 arriving through the grain rather than through an edge, and
#: ``DraftToolUsage`` exists because the repository already knows it.
#:
#: The reason to close the structural door anyway is that it fails on arrival.
#: A new table declares its foreign keys at definition time, so the wrong
#: lineage is rejected before a single row exists - which is the only moment
#: fixing it is cheap.
FLOW_SCAN_LIMIT: Final = (
    "declared foreign keys only; an undeclared identifier column or a value copied "
    "between layers in Python leaves no key. Twelve columns ending _id carry no foreign "
    "key today, all of them foreign-system identifiers rather than references to a "
    "mapped table, so the count is a tripwire on arrival and not a live gap (count "
    "reproducible from Base.metadata; an earlier note said sixteen on an unstated "
    "heuristic and review could not reproduce it)"
)

#: The size of the gap :data:`FLOW_SCAN_LIMIT` describes, pinned so it is checked.
#:
#: A scope limit that states a number has to have the number checked, or it is
#: prose with a figure in it. This one has already gone stale once: an earlier
#: note claimed sixteen on a heuristic nobody wrote down, and review could not
#: reproduce it. ``test_the_scope_limits_are_stated`` recomputes this from
#: ``Base.metadata``, so adding or removing an undeclared identifier column
#: fails a test rather than quietly widening the gap the constant describes.
#:
#: What it counts is not what :data:`FLOW_SCAN_LIMIT` describes - see there.
#: The next external id column added (``espn_player_id``, say) turns the test
#: red with advice to consider making it a real foreign key, which will be the
#: wrong advice, and the right repair will be to bump this number. That is a
#: known cost of the spelling, accepted deliberately rather than by omission.
NAKED_IDENTIFIER_COLUMNS: Final = 12

#: What the import-time call does **not** see.
#:
#: :func:`validate_layers` reads whatever is mapped onto ``Base.metadata`` at
#: the moment ``hoops_gm.db.models`` finishes executing. ``Base.metadata`` is
#: global and stays mutable afterwards, so a model module that ``__init__.py``
#: does not import is a table the validation never meets — and importing that
#: submodule directly runs the parent package *first*, validating incomplete
#: metadata, then maps the new table with nothing left to check it.
#:
#: Found by review, closed, defeated again by a second review, closed again:
#: ``test_every_model_module_is_reached_by_importing_the_package`` imports the
#: package and then walks ``db/models/`` recursively looking for a module that
#: still has tables left to map. The two earlier versions asked how the import
#: was *spelled* — a substring, satisfied by a commented-out line; then a
#: non-recursive glob, blind to ``db/models/valuation/`` while this very
#: constant claimed subpackages were covered. Asking what importing the package
#: actually mapped is the form that cannot be worded around. The limit stated
#: here is what remains. A table mapped from outside ``db/models/`` entirely -
#: a test fixture, a plugin, a REPL - is invisible. So is a module that declares
#: its own ``DeclarativeBase``: its tables land on a different ``MetaData``,
#: which neither this check nor Alembic autogenerate reads. Both are named
#: because a third review found the previous wording stated one residual as
#: though it were the only one, which is the same false-limit shape as the
#: non-recursive glob it had just replaced.
IMPORT_TIME_LIMIT: Final = (
    "validates what is mapped when db.models finishes importing; a table mapped onto "
    "Base.metadata afterwards, by anything the package's import does not reach, is "
    "never seen, and a module declaring its own DeclarativeBase is never seen at all. "
    "Reachability is checked by importing the package and looking for "
    "tables still unmapped, not by reading how the imports are spelled: review "
    "defeated a substring check with a commented-out import, and a non-recursive "
    "glob with a subpackage this very constant then wrongly claimed was covered"
)

#: Tables the market layer may reference, despite the layer edge being wider.
#:
#: ``(OBSERVATIONS, MARKET)`` exists so a published auction value can say which
#: player it is about. Read at layer granularity it says much more than that:
#: ``OBSERVATIONS`` is the broadest layer and includes ``draft_events`` — prices
#: a human paid, which our own recommendations can have caused, which is why
#: ``DraftToolUsage`` exists — and ``absence_splits``, an aggregate we compute.
#: Seeding an AAV table from observed clearing prices is a tempting future
#: feature and it is R38 through a side door: our output returning as somebody
#: else's evidence.
#:
#: So the edge is narrowed to identity. These tables answer "which player, which
#: team" and carry no quantity anyone could blend. Every member must be a mapped
#: table at ``OBSERVATIONS``; a stale entry fails, so an exemption cannot outlive
#: its cause. Only ``players`` is referenced today.
#:
#: Each member carries a written reason, the way ``SANCTIONED_STORE_OPENERS``
#: does, and the keys of :data:`MARKET_IDENTITY_REASONS` must equal this set
#: exactly. A third review pointed out that the enforcement was an allowlist
#: guarded by a denylist of two names: nothing stopped ``player_season_stats``
#: from being added, after which a market row could be seeded from observed
#: season totals with every test green. A denylist enumerates the doors it
#: knows. Requiring a reason per member does not make a bad addition
#: impossible, but it makes it something somebody had to write a sentence to
#: justify, which is the reviewable moment.
MARKET_IDENTITY_SOURCES: Final[frozenset[str]] = frozenset(
    {
        "players",
        "nba_teams",
        "player_external_ids",
    }
)

#: Why each :data:`MARKET_IDENTITY_SOURCES` member is identity and not evidence.
#:
#: Keys must equal ``MARKET_IDENTITY_SOURCES``. The test that pins this also
#: drives the narrowing against *every* observations table that is not a
#: member, rather than three hand-picked ones, so the guard is closed over the
#: layer rather than over a list of names somebody remembered.
MARKET_IDENTITY_REASONS: Final[dict[str, str]] = {
    "players": (
        "the player roster. Names, positions and team membership; the primary key "
        "is the identity itself. Nothing here is a measurement, so a market row "
        "keyed to it learns who the price is about and nothing more."
    ),
    "nba_teams": (
        "the thirty franchises. A fixed enumeration with no per-season quantity; "
        "the same reasoning as players, one level up."
    ),
    "player_external_ids": (
        "the crosswalk between our player key and each source's. It is purely a "
        "mapping between identifiers, which is why it is the one table whose "
        "whole purpose is identity."
    ),
}

#: The grain of an assignment: one layer per table, not per column.
#:
#: True of every table today and enforced by
#: ``test_data_layer_columns_agree_with_the_registry`` for the three tables
#: that also store the layer per row. A table that genuinely needed two layers
#: would be two tables — which is exactly the ruling that produced the market
#: tables instead of widening ``projection_sources``.
GRAIN_LIMIT: Final = "one layer per table; a table needing two layers is two tables"


class LayerViolation(RuntimeError):
    """A stored quantity's layer is unassigned, unknown, or flows backwards."""


def flow_permitted(source: DataLayer, target: DataLayer) -> bool:
    """May a quantity at ``source`` be an input to one at ``target``?

    Permitted when the two are the same layer — ADR-008 clause 1, "aggregate
    only within a layer" — or when the ordered pair is listed in
    :data:`PERMITTED_FLOWS`. There is no fallback: an unlisted cross-layer pair
    is refused, so a new layer starts fully isolated rather than inheriting a
    verdict from an ordering.
    """
    return source is target or (source, target) in PERMITTED_FLOWS


def layer_of(table_name: str) -> DataLayer:
    """The layer assigned to ``table_name``, or raise."""
    try:
        return TABLE_LAYERS[table_name]
    except KeyError:
        raise LayerViolation(
            f"table {table_name!r} has no layer.\n"
            f"\n"
            f"ADR-008 requires every stored quantity to record which layer it belongs "
            f"to, because a number whose layer is unknown cannot be checked for the "
            f"one defect that matters here: a later layer feeding an earlier one, "
            f"which makes the model agree with itself without ever failing.\n"
            f"\n"
            f"What to do: add {table_name!r} to TABLE_LAYERS in "
            f"backend/src/hoops_gm/db/layers.py with the reason it sits where it does, "
            f"and seed its row in data_layer_registry with a new migration."
        ) from None


def validate_layer_assignment(metadata: MetaData) -> None:
    """Every mapped table has a layer, and every assignment names a real table.

    Both directions, because they fail differently. An unassigned table is a
    quantity nobody classified; an assignment for a table that no longer exists
    is a registry rotting into fiction, which is how the store-opening census
    went from exactly complete to quietly wrong.
    """
    # ``metadata.tables`` is keyed "schema.name" when a schema is set, while
    # ``layer_of`` and the flow check both use bare ``table.name``. Nothing sets
    # a schema today, so the two coincide — but keying on ``.name`` here keeps
    # them from diverging the day someone adds a Postgres schema, which would
    # otherwise raise "has no layer" for a table that is in TABLE_LAYERS.
    mapped = {table.name for table in metadata.tables.values()}
    assigned = set(TABLE_LAYERS)

    unassigned = sorted(mapped - assigned)
    if unassigned:
        raise LayerViolation(
            f"tables with no ADR-008 layer: {unassigned}.\n"
            f"\n"
            f"What to do: add each to TABLE_LAYERS in backend/src/hoops_gm/db/layers.py "
            f"with a comment saying why it sits where it does, then seed its row in "
            f"data_layer_registry with a new migration.\n"
            f"\n"
            f"Why this is an ImportError and not a lint: the defect it prevents is "
            f"circularity, and circularity does not crash. A ranking or a composite "
            f"value that feeds back into a projection or availability input makes the "
            f"model agree with itself, so every downstream figure gets more confident "
            f"and less true with the suite green throughout. An unclassified table is "
            f"the state in which that becomes possible, which is why it fails here "
            f"rather than being reported later. See docs/decisions/ADR-008-layer-purity.md.\n"
            f"\n"
            f"If your table genuinely has no layer, that is a finding worth raising "
            f"rather than an exemption to add - say so instead of deleting the call."
        )

    vanished = sorted(assigned - mapped)
    if vanished:
        raise LayerViolation(
            f"TABLE_LAYERS names tables that are not mapped: {vanished}.\n"
            f"\n"
            f"What to do: remove each entry from TABLE_LAYERS in "
            f"backend/src/hoops_gm/db/layers.py, and drop its data_layer_registry "
            f"rows in a new migration.\n"
            f"\n"
            f"Why a stale entry fails rather than being ignored: a register that has "
            f"stopped describing the schema cannot be trusted as a whole, and this "
            f"repository has already lost a store-opening census exactly that way - it "
            f"was complete when written and quietly wrong afterwards, at exit 0. An "
            f"exemption must not outlive its cause."
        )

    stale_identity = sorted(
        name
        for name in MARKET_IDENTITY_SOURCES
        if name not in mapped or TABLE_LAYERS[name] is not DataLayer.OBSERVATIONS
    )
    if stale_identity:
        raise LayerViolation(
            f"MARKET_IDENTITY_SOURCES names tables that are no longer mapped "
            f"observations tables: {stale_identity}.\n"
            f"\n"
            f"What to do: remove each entry from MARKET_IDENTITY_SOURCES in "
            f"backend/src/hoops_gm/db/layers.py.\n"
            f"\n"
            f"Why a stale exemption fails rather than being ignored: this set is the "
            f"only thing narrowing the observations-to-market edge to identity, and "
            f"an entry that has stopped meaning what it meant silently widens it. "
            f"An exemption must not outlive its cause."
        )


def validate_layer_flow(metadata: MetaData) -> None:
    """No declared foreign key points from a later layer into an earlier one.

    A foreign key from ``T`` to ``S`` means a row of ``T`` is defined partly by
    a row of ``S`` — ``S`` is an input to ``T``. So the check is on the layer
    of the *referenced* table against the layer of the referencing one.
    """
    violations: list[str] = []
    for table in metadata.tables.values():
        target_layer = layer_of(table.name)
        for key in table.foreign_keys:
            referenced = key.column.table.name
            source_layer = layer_of(referenced)
            if not flow_permitted(source_layer, target_layer):
                violations.append(
                    f"{table.name}.{key.parent.name} -> {referenced} "
                    f"({source_layer} into {target_layer})"
                )
            elif (
                source_layer is DataLayer.OBSERVATIONS
                and target_layer is DataLayer.MARKET
                and referenced not in MARKET_IDENTITY_SOURCES
            ):
                violations.append(
                    f"{table.name}.{key.parent.name} -> {referenced} "
                    f"(market may reference identity only, not {referenced})"
                )

    if violations:
        raise LayerViolation(
            "ADR-008 forbids these flows:\n  " + "\n  ".join(sorted(violations)) + "\n\n"
            "A later layer may not be an input to an earlier one at any weight. "
            "A foreign key from T to S means a row of T is defined partly by a row "
            "of S, so S is an input to T - check the direction before assuming the "
            "layer assignment is wrong.\n"
            "\n"
            "Why this is an ImportError and not a failing test: the defect is "
            "circularity, which produces confident, plausible, wrong numbers rather "
            "than a crash. A published ranking or an AAV reaching back into a "
            "projection or a p(play) input is the exact failure ADR-008 exists to "
            "prevent, and there is no green-test signal for it.\n"
            "\n"
            "What to do, in the order worth trying:\n"
            "  1. If the intent is to *compare* rather than to blend, the comparison "
            "belongs at DataLayer.COMPARISON, which consumes both sides and feeds "
            "nothing.\n"
            "  2. If the referenced table is misclassified, change its entry in "
            "TABLE_LAYERS in backend/src/hoops_gm/db/layers.py and seed the "
            "correction in a new migration.\n"
            "  3. If neither, the lineage is the problem and the key should not "
            "exist. That is the case this check was written for.\n"
            "\n"
            "Deleting validate_layers(Base.metadata) from db/models/__init__.py "
            "silences this. So does replacing it with a local no-op of the same "
            "name, which review showed left every gate green - both are caught by "
            "test_layer_purity.py, the second by importing the package in a "
            "subprocess rather than by reading the call site. See "
            "docs/decisions/ADR-008-layer-purity.md."
        )


def validate_layers(metadata: MetaData) -> None:
    """Assignment then flow. Called at import of :mod:`hoops_gm.db.models`."""
    validate_layer_assignment(metadata)
    validate_layer_flow(metadata)
