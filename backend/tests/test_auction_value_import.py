"""Sourcing and importing published auction values — ``aav-source``, Phase 8.

Layered the way ``test_projection_importer.py`` is, because the same three
levels exist: pure profiles, a pure parser, and a DB-writing importer. What is
new here is a fourth thing with no projection equivalent — the *consumption*
rule in ``hoops_gm.market.independence``, which decides whether an imported
price list may be compared against at all.

## What the fixtures are and are not

Only the FantraxHQ header contract was read from a live published page
(2026-08-21). Its metadata file records exactly what was verified and what is
synthetic. The Hashtag and Yahoo fixtures are **unverified synthetic examples**:
their semantics were established from the publishers' pages, but no byte
contract was, because neither publisher offers a machine-readable export.
``profiles.py``'s module docstring argues why that is a property of these
sources rather than a to-do.

Every player name, team and dollar value in all three fixtures is invented.
This repository redistributes none of these publishers' tables.

## What "adapter contract" means for a source with no machine-readable export

For the NBA adapters it means the recorded bytes still parse. Here it means
that plus something the projection adapters do not have to prove: that the
*claims* survive. A price of ``$0`` is a claim and an empty cell is not; an
observed average and a projected value in the same table are different claims;
a percentage in a price column is a mis-mapped column and not a price. Those
are the assertions below, because those are the failures that would produce a
confident, plausible, wrong benchmark rather than a crash.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import (
    AuctionValueDerivation,
    AuctionValueInputKind,
    AuctionValueKind,
    BasisEvidence,
    ExternalSource,
    FieldEvidence,
    MatchMethod,
    ScoringType,
)
from hoops_gm.db.models.identity import NbaTeam, Player, PlayerExternalId
from hoops_gm.db.models.market import (
    BASIS_FIELDS,
    AuctionValueImport,
    AuctionValueSource,
    AuctionValueSourceInput,
    PublishedAuctionValue,
)
from hoops_gm.db.models.projections import ProjectionImport, ProjectionProfileVersion
from hoops_gm.identity.names import normalize_name
from hoops_gm.ingest.auction_values.importer import (
    AuctionImportOutcome,
    BasisDeclaration,
    BasisIncomplete,
    import_auction_value_csv,
    register_auction_value_source,
)
from hoops_gm.ingest.auction_values.parser import (
    AuctionValueProfileError,
    parse_auction_value_csv,
)
from hoops_gm.ingest.auction_values.profiles import (
    AUCTION_VALUE_PROFILES,
    AUCTION_VALUE_SOURCES,
    AuctionSourceDescriptor,
    AuctionValueProfile,
    SourceInputDescriptor,
    ValueColumn,
    profile_for,
    source_for,
)
from hoops_gm.ingest.projections import (
    BASKETBALL_MONSTER_PROFILE,
    HASHTAG_PROFILE,
    ProjectionProfileError,
    get_or_create_projection_source,
    import_projection_csv,
)
from hoops_gm.market.independence import (
    BASIS_UNESTABLISHED,
    CIRCULAR_LINEAGE,
    DERIVATION_UNESTABLISHED,
    assess_benchmark_admissibility,
    assess_source_independence,
    imported_projection_sources,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "auction_values"
PROJECTION_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "projections"

#: Every fixture this module reads. Named once so the presence check below can
#: assert the set it expects rather than iterating whatever happens to be on
#: disk — a loop over an empty directory passes silently, which is the defect
#: class this project has caught seven times in one day.
REQUIRED_FIXTURES = (
    "fantraxhq_auction_values.csv",
    "fantraxhq_auction_values.metadata.json",
    "hashtag_auction_values.csv",
    "yahoo_draft_analysis.csv",
)


def load(name: str) -> str:
    """Read a fixture, refusing to silently treat a missing one as empty.

    ``read_text`` already raises on a missing file, so this wrapper exists for
    the *empty* case: a zero-byte fixture would parse to zero rows, and every
    "assert no rejected rows" style check downstream would pass while proving
    nothing at all.
    """
    path = FIXTURES / name
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise AssertionError(f"fixture {name} is empty, so any test reading it proves nothing")
    return text


def seed_player(
    session: Session,
    *,
    nba_id: int,
    name: str,
    team_abbreviation: str | None = None,
    position: str | None = None,
) -> Player:
    """A canonical player with an NBA crosswalk link.

    Mirrors ``test_projection_importer.seed_player``. The NBA link is not
    decoration: the auction importer resolves names against player targets and
    then maps the accepted target key through ``player_external_ids`` where
    ``source = NBA``, so a player without that link is unresolvable by design.
    """
    team_id = None
    if team_abbreviation:
        team = session.scalar(select(NbaTeam).where(NbaTeam.abbreviation == team_abbreviation))
        if team is None:
            team_count = session.scalar(select(func.count()).select_from(NbaTeam)) or 0
            team = NbaTeam(
                nba_team_id=2000 + team_count,
                abbreviation=team_abbreviation,
                name=f"{team_abbreviation} Team",
            )
            session.add(team)
            session.flush()
        team_id = team.id

    player = Player(
        full_name=name,
        normalized_name=normalize_name(name).key,
        primary_position=position,
        primary_position_source="nba:PlayerIndex" if position else None,
        primary_position_season="2026-27" if position else None,
        current_team_id=team_id,
    )
    session.add(player)
    session.flush()
    session.add(
        PlayerExternalId(
            player_id=player.id,
            source=ExternalSource.NBA,
            current_for_source=ExternalSource.NBA.value,
            external_id=str(nba_id),
            external_name=name,
            normalized_name=normalize_name(name).key,
            external_team=team_abbreviation,
            confidence=1.0,
            match_method=MatchMethod.ANCHOR_ID,
            name_evidence=FieldEvidence.AGREE,
        )
    )
    session.flush()
    return player


FIXTURE_PLAYERS = (
    (1, "Player Alpha", "BOS", "SF"),
    (2, "Player Beta", "LAL", "PG"),
    (3, "Player Gamma", "DEN", "C"),
    (4, "Player Delta", "MIA", "PG"),
    (5, "Player Epsilon", "PHX", "SG"),
    (6, "Player Zeta", "NYK", "PF"),
    (7, "Player Eta", "ORL", "SF"),
    (8, "Player Theta", "SAC", "C"),
    (9, "Player Iota", "UTA", "SG"),
    (10, "Player Kappa", "POR", "PG"),
)


@pytest.fixture
def seeded_players(session: Session) -> Session:
    for nba_id, name, team, position in FIXTURE_PLAYERS:
        seed_player(session, nba_id=nba_id, name=name, team_abbreviation=team, position=position)
    return session


def stated_basis(**overrides: object) -> BasisDeclaration:
    """A fully-stated basis, for tests whose subject is not the basis.

    Written as an explicit helper rather than a default on
    :class:`BasisDeclaration`, because the whole point of that class is that
    there is no default basis anywhere in production code.
    """
    fields: dict[str, object] = {
        "budget": Decimal("200"),
        "budget_evidence": BasisEvidence.STATED,
        "team_count": 12,
        "team_count_evidence": BasisEvidence.STATED,
        "roster_size": 13,
        "roster_size_evidence": BasisEvidence.STATED,
        "scoring_type": ScoringType.H2H_CATEGORIES,
        "scoring_type_evidence": BasisEvidence.STATED,
        "category_count": 9,
        "category_count_evidence": BasisEvidence.STATED,
    }
    fields.update(overrides)
    return BasisDeclaration(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# The fixtures exist and say what this module thinks they say
# --------------------------------------------------------------------------


def test_every_required_fixture_is_present_and_non_empty() -> None:
    """Assert the presence we expect, before anything iterates over it.

    Delete any fixture and this fails by name. That is the point: the contract
    tests below all iterate over parsed rows, and a parse of a missing or empty
    file yields an empty iteration that every ``all(...)`` and every
    ``assert not result.fatal_issues`` would happily accept.
    """
    missing = [name for name in REQUIRED_FIXTURES if not (FIXTURES / name).is_file()]
    assert not missing, f"missing auction-value fixtures: {missing}"
    empty = [name for name in REQUIRED_FIXTURES if not (FIXTURES / name).read_bytes().strip()]
    assert not empty, f"empty auction-value fixtures: {empty}"


def test_fantraxhq_metadata_separates_what_was_verified_from_what_is_synthetic() -> None:
    """The metadata file has to make both claims, not just the flattering one."""
    metadata = json.loads(load("fantraxhq_auction_values.metadata.json"))
    assert metadata["what_is_verified"], "no verified claims recorded"
    assert metadata["what_is_synthetic"], "no synthetic content declared"
    assert metadata["what_could_not_be_established"], (
        "an empty 'could not establish' list is the unexamined blank this unit exists to avoid"
    )


def test_the_two_hundred_dollar_budget_inference_does_not_survive_the_published_pool() -> None:
    """Why FantraxHQ's budget is UNESTABLISHED rather than inferred at $200.

    This is not a restatement of a sentence in the metadata — it recomputes the
    conclusion from the transcribed counts, so editing the transcription
    changes the verdict rather than leaving a stale claim behind.

    The rounding bound matters. The published values are whole dollars, so the
    sum of 156 of them carries roughly sqrt(156) x 0.289 = $3.6 of rounding
    noise. The observed gap is two orders of magnitude larger, which is what
    makes "the budget is $200 and this is rounding" untenable rather than
    merely unlikely.
    """
    metadata = json.loads(load("fantraxhq_auction_values.metadata.json"))
    transcription = metadata["transcription_of_the_published_table"]
    nonzero = transcription["nonzero_rows"]
    published_pool = transcription["nonzero_value_sum_dollars"]

    assumed_pool = 12 * 200
    gap = published_pool - assumed_pool
    rounding_bound = 3 * (nonzero**0.5) * 0.289

    assert gap > rounding_bound, (
        f"the published pool (${published_pool}) is within rounding of a 12x$200 pool "
        f"(${assumed_pool}), which would make $200 a defensible inference after all — "
        "if this ever fails, the source descriptor and the adapter page both need revisiting"
    )

    fantraxhq = source_for("fantraxhq")
    notes = (fantraxhq.notes or "").lower()
    assert "2,655" in notes, (
        "the descriptor must carry the published pool that falsified the $200 inference, "
        "not just the conclusion drawn from it"
    )
    assert "unestablished" in notes, (
        "and must say plainly that the budget is unestablished rather than inferred"
    )


# --------------------------------------------------------------------------
# The registry: every profile has a source, every source has evidence
# --------------------------------------------------------------------------


def test_the_registries_are_not_empty() -> None:
    """A check that iterates must first assert it found something to iterate.

    Every parametrised test below draws its cases from these two tuples. If
    either were emptied, pytest would collect zero cases and report success.
    """
    assert AUCTION_VALUE_PROFILES, "no auction value profiles registered"
    assert AUCTION_VALUE_SOURCES, "no auction value sources registered"
    assert len(AUCTION_VALUE_SOURCES) >= 4
    assert len(AUCTION_VALUE_PROFILES) >= 3


@pytest.mark.parametrize("profile", AUCTION_VALUE_PROFILES, ids=lambda p: p.profile_id)
def test_every_profile_names_a_registered_source(profile: AuctionValueProfile) -> None:
    assert source_for(profile.source_slug).slug == profile.source_slug
    assert profile_for(profile.profile_id) is profile


@pytest.mark.parametrize("descriptor", AUCTION_VALUE_SOURCES, ids=lambda s: s.slug)
def test_every_source_records_derivation_evidence(descriptor: AuctionSourceDescriptor) -> None:
    """Including — especially — the sources whose derivation is unknown.

    An unexamined blank and an investigated "unknown" are different claims.
    The column has a CHECK on non-empty text so the blank is inexpressible in
    the database; this asserts the seed data never tries.
    """
    assert descriptor.derivation_evidence.strip()
    for item in descriptor.inputs:
        assert item.evidence.strip()


def test_a_source_claiming_a_method_without_inputs_is_refused() -> None:
    """A method with no recorded inputs cannot be tested for circularity.

    Which would make it permanently, invisibly admissible — the failure mode
    this whole layer exists to prevent, arriving through the back door of an
    under-specified descriptor.
    """
    with pytest.raises(ValueError, match="cannot be tested for circularity"):
        AuctionSourceDescriptor(
            slug="silent",
            display_name="Silent",
            publisher_url=None,
            derivation_method=AuctionValueDerivation.Z_SCORE_BUDGET_DISTRIBUTION,
            derivation_evidence="claims a method",
            inputs=(),
        )


def test_an_input_without_a_label_is_refused() -> None:
    """A nameless input cannot be argued with.

    The registry is the source assessment as data, so an input whose label is
    blank records that a method consumes *something* without saying what — which
    reads as investigated and is not.
    """
    with pytest.raises(ValueError, match="non-empty label"):
        SourceInputDescriptor(
            input_kind=AuctionValueInputKind.PROJECTIONS,
            input_label="  ",
            our_projection_source=None,
            evidence="whatever we would have written here is unfalsifiable",
        )


def test_an_input_without_evidence_is_refused() -> None:
    with pytest.raises(ValueError, match="different claims"):
        SourceInputDescriptor(
            input_kind=AuctionValueInputKind.PROJECTIONS,
            input_label="something",
            our_projection_source=None,
            evidence="   ",
        )


def test_a_profile_mapping_one_header_to_two_kinds_is_refused() -> None:
    """One column cannot be two kinds of claim at once.

    The failure this prevents is quiet: the same dollar figure written twice
    under two kinds would look like a projected value corroborated by an
    observed one.
    """
    with pytest.raises(ValueError, match="more than one value column"):
        AuctionValueProfile(
            profile_id="ambiguous",
            version="1",
            source_slug="manual",
            display_name="Ambiguous",
            name_aliases=("player",),
            value_columns=(
                ValueColumn(kind=AuctionValueKind.PROJECTED, aliases=("value",), label="A"),
                ValueColumn(kind=AuctionValueKind.OBSERVED_MARKET, aliases=("Value",), label="B"),
            ),
            verification_evidence="test",
        )


# --------------------------------------------------------------------------
# Adapter contract: the recorded tables still parse, and still mean the same
# --------------------------------------------------------------------------


@pytest.mark.adapter_contract
class TestFantraxHqContract:
    """The one source whose table shape was read from the live page."""

    def test_header_contract_and_value_shape(self) -> None:
        csv_text = load("fantraxhq_auction_values.csv")
        assert csv_text.splitlines()[0] == "Rank,Player,Team,Position,Value"

        result = parse_auction_value_csv(csv_text, profile_for("fantraxhq-auction-values"))

        assert result.total_rows == 10
        assert result.rows, "parsed no values, so nothing below is being checked"
        assert not result.fatal_issues
        assert result.ignored_headers == ("Rank",)
        assert result.resolved_headers["player_name"] == "Player"
        assert result.resolved_headers["value:projected"] == "Value"

    def test_an_explicit_zero_is_a_published_claim_and_survives(self) -> None:
        """``$0`` means "not worth rostering". An empty cell means nothing at all.

        Collapsing them would delete 38 of the published table's 194 rows and
        the deletion would be invisible, because the remaining rows would all
        be correct.
        """
        result = parse_auction_value_csv(
            load("fantraxhq_auction_values.csv"), profile_for("fantraxhq-auction-values")
        )
        zeros = [row for row in result.rows if row.value_dollars == Decimal("0")]
        assert len(zeros) == 2
        assert {row.value_raw for row in zeros} == {"$0"}

    def test_the_source_text_is_kept_beside_the_parsed_number(self) -> None:
        """``$74`` and ``74`` parse identically and are different claims.

        A source switching notation is a signal that its table changed, and it
        is only visible if the original text survives the parse.
        """
        result = parse_auction_value_csv(
            load("fantraxhq_auction_values.csv"), profile_for("fantraxhq-auction-values")
        )
        alpha = next(row for row in result.rows if row.player_name == "Player Alpha")
        assert alpha.value_dollars == Decimal("74")
        assert alpha.value_raw == "$74"
        assert alpha.position == "SF,PF"


@pytest.mark.adapter_contract
class TestYahooContract:
    """The structural demonstration that ``value_kind`` belongs to the value."""

    def test_one_file_row_yields_two_rows_of_different_kind(self) -> None:
        csv_text = load("yahoo_draft_analysis.csv")
        result = parse_auction_value_csv(csv_text, profile_for("yahoo-draft-analysis"))

        assert result.total_rows == 5
        assert len(result.rows) == 10, "expected one observed and one projected value per row"
        observed = [r for r in result.rows if r.value_kind is AuctionValueKind.OBSERVED_MARKET]
        projected = [r for r in result.rows if r.value_kind is AuctionValueKind.PROJECTED]
        assert len(observed) == 5
        assert len(projected) == 5

    def test_the_two_kinds_disagree_and_are_not_averaged(self) -> None:
        """If these ever came back equal, something has collapsed them."""
        result = parse_auction_value_csv(
            load("yahoo_draft_analysis.csv"), profile_for("yahoo-draft-analysis")
        )
        by_player: dict[str, dict[AuctionValueKind, Decimal]] = {}
        for row in result.rows:
            by_player.setdefault(row.player_name, {})[row.value_kind] = row.value_dollars
        assert by_player, "no players parsed"
        differing = [
            name
            for name, kinds in by_player.items()
            if kinds[AuctionValueKind.OBSERVED_MARKET] != kinds[AuctionValueKind.PROJECTED]
        ]
        assert len(differing) == len(by_player)

    def test_the_percent_drafted_column_is_ignored_rather_than_priced(self) -> None:
        """A percentage read as a price is the mis-mapped-column failure.

        It would not crash. It would produce a $99 player.
        """
        result = parse_auction_value_csv(
            load("yahoo_draft_analysis.csv"), profile_for("yahoo-draft-analysis")
        )
        assert "% Drafted" in result.ignored_headers
        assert all(row.value_dollars <= Decimal("71") for row in result.rows)


@pytest.mark.adapter_contract
class TestHashtagContract:
    def test_the_fantasy_point_total_column_is_not_read_as_a_price(self) -> None:
        csv_text = load("hashtag_auction_values.csv")
        result = parse_auction_value_csv(csv_text, profile_for("hashtag-auction-values"))

        assert result.total_rows == 8
        assert len(result.rows) == 8
        assert "Total" in result.ignored_headers
        assert not result.fatal_issues


# --------------------------------------------------------------------------
# Parser: what it refuses, and why refusing beats coercing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cell", "reason"),
    [
        ("45%", "not a plain dollar amount"),
        ("12-15", "not a plain dollar amount"),
        ("cheap", "not a plain dollar amount"),
        ("-3", "negative"),
        ("9999", "exceeds"),
    ],
)
def test_an_unreadable_price_is_refused_row_by_row(cell: str, reason: str) -> None:
    """Not coerced, not defaulted, and not fatal to the rest of the file.

    An unparsable dollar figure is not an uncertain price — it is not a price.
    Substituting anything for it would manufacture market evidence.
    """
    csv_text = f"Player,Value\nPlayer Alpha,{cell}\nPlayer Beta,$20\n"
    result = parse_auction_value_csv(csv_text, profile_for("manual-auction-values"))

    assert [row.player_name for row in result.rows] == ["Player Beta"]
    assert len(result.fatal_issues) == 1
    assert reason in result.fatal_issues[0].message
    assert result.rejected_row_numbers == frozenset({2})


def test_an_empty_cell_is_not_a_price_of_zero() -> None:
    csv_text = "Player,Value\nPlayer Alpha,\nPlayer Beta,$0\n"
    result = parse_auction_value_csv(csv_text, profile_for("manual-auction-values"))

    assert [row.player_name for row in result.rows] == ["Player Beta"]
    assert result.rows[0].value_dollars == Decimal("0")
    assert "every mapped value column was empty" in result.fatal_issues[0].message


def test_a_file_with_no_value_column_is_refused_outright() -> None:
    with pytest.raises(AuctionValueProfileError, match="no value column"):
        parse_auction_value_csv(
            "Player,Team\nPlayer Alpha,BOS\n", profile_for("manual-auction-values")
        )


def test_a_file_with_no_name_column_is_refused_outright() -> None:
    with pytest.raises(AuctionValueProfileError, match="no player-name column"):
        parse_auction_value_csv("Value\n$20\n", profile_for("manual-auction-values"))


def test_an_empty_file_is_refused_rather_than_parsed_as_zero_rows() -> None:
    """The empty-set failure, at the parser's own door."""
    with pytest.raises(AuctionValueProfileError, match="no header row"):
        parse_auction_value_csv("", profile_for("manual-auction-values"))


def test_a_currency_symbol_with_no_number_is_not_a_price() -> None:
    """``$`` alone strips to nothing. It is an absent claim, not zero."""
    result = parse_auction_value_csv(
        "Player,Value\nPlayer Alpha,$\nPlayer Beta,$20\n", profile_for("manual-auction-values")
    )
    assert [row.player_name for row in result.rows] == ["Player Beta"]
    assert "every mapped value column was empty" in result.fatal_issues[0].message


def test_a_row_with_no_player_name_is_refused_and_named_as_such() -> None:
    """A price with nobody attached cannot be resolved, so it is not a benchmark."""
    result = parse_auction_value_csv(
        "Player,Value\n,$40\nPlayer Beta,$20\n", profile_for("manual-auction-values")
    )
    assert [row.player_name for row in result.rows] == ["Player Beta"]
    assert len(result.fatal_issues) == 1
    assert result.fatal_issues[0].message == (
        "row has no player name, so it cannot be resolved to a player"
    )
    assert result.fatal_issues[0].column == "Player"
    assert result.total_rows == 2, "the unusable row still counts as a row the file contained"


def test_a_source_player_id_is_recorded_without_becoming_a_crosswalk_key() -> None:
    """Kept as evidence when a publisher exposes one; never promoted.

    The manual profile is the only one with id aliases, because it is the only
    table whose columns are ours to define.
    """
    result = parse_auction_value_csv(
        "ID,Player,Value\nabc-123,Player Alpha,$40\n", profile_for("manual-auction-values")
    )
    assert result.resolved_headers["source_player_id"] == "ID"
    assert result.rows[0].source_player_id == "abc-123"


# --------------------------------------------------------------------------
# Registry validation: the guards on the seed data itself
# --------------------------------------------------------------------------


def test_an_unknown_profile_or_source_names_the_known_ones() -> None:
    """An error that lists the alternatives is the difference between a
    two-minute fix and a grep."""
    with pytest.raises(KeyError, match="hashtag-auction-values"):
        profile_for("no-such-profile")
    with pytest.raises(KeyError, match="fantraxhq"):
        source_for("no-such-source")


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"slug": "  "}, "non-empty slug"),
        ({"derivation_evidence": " "}, "requires derivation evidence"),
    ],
)
def test_a_malformed_source_descriptor_is_refused(kwargs: dict[str, str], match: str) -> None:
    fields: dict[str, object] = {
        "slug": "ok",
        "display_name": "Ok",
        "publisher_url": None,
        "derivation_method": AuctionValueDerivation.UNESTABLISHED,
        "derivation_evidence": "investigated and unknown",
    }
    fields.update(kwargs)
    with pytest.raises(ValueError, match=match):
        AuctionSourceDescriptor(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"profile_id": " "}, "non-empty identifier"),
        ({"version": " "}, "non-empty identifier"),
        ({"value_columns": ()}, "maps no value column"),
        ({"name_aliases": ()}, "requires a player-name field"),
        ({"verification_evidence": " "}, "requires verification evidence"),
    ],
)
def test_a_malformed_profile_is_refused(kwargs: dict[str, object], match: str) -> None:
    """Including the two that would produce a silently empty parse.

    A profile with no value column parses every file to zero rows, and a
    profile with no name column resolves nobody. Both would import cleanly and
    report success over nothing.
    """
    fields: dict[str, object] = {
        "profile_id": "ok",
        "version": "1",
        "source_slug": "manual",
        "display_name": "Ok",
        "name_aliases": ("player",),
        "value_columns": (
            ValueColumn(kind=AuctionValueKind.PROJECTED, aliases=("value",), label="Value"),
        ),
        "verification_evidence": "checked nothing, and says so",
    }
    fields.update(kwargs)
    with pytest.raises(ValueError, match=match):
        AuctionValueProfile(**fields)  # type: ignore[arg-type]


def test_the_registry_validator_refuses_an_empty_or_dangling_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The import-time guard, driven rather than assumed.

    It exists because a profile naming an unregistered source would import
    values whose derivation nothing records — and it would do so at import
    time, in front of nobody. Both of its arms are entered here, because a
    validator that has never rejected anything is a validator nobody has shown
    to work.
    """
    from hoops_gm.ingest.auction_values import profiles as profiles_module

    monkeypatch.setattr(profiles_module, "AUCTION_VALUE_PROFILES", ())
    with pytest.raises(RuntimeError, match="profile registry is empty"):
        profiles_module._validate_registry()

    monkeypatch.setattr(profiles_module, "AUCTION_VALUE_PROFILES", AUCTION_VALUE_PROFILES)
    monkeypatch.setattr(profiles_module, "AUCTION_VALUE_SOURCES", ())
    with pytest.raises(RuntimeError, match="source registry is empty"):
        profiles_module._validate_registry()

    monkeypatch.setattr(profiles_module, "AUCTION_VALUE_SOURCES", AUCTION_VALUE_SOURCES)
    dangling = AuctionValueProfile(
        profile_id="dangling",
        version="1",
        source_slug="nobody-registered-this",
        display_name="Dangling",
        name_aliases=("player",),
        value_columns=(
            ValueColumn(kind=AuctionValueKind.PROJECTED, aliases=("value",), label="Value"),
        ),
        verification_evidence="none",
    )
    monkeypatch.setattr(profiles_module, "AUCTION_VALUE_PROFILES", (dangling,))
    with pytest.raises(RuntimeError, match="names unregistered source"):
        profiles_module._validate_registry()


# --------------------------------------------------------------------------
# Basis: mandatory, non-defaultable, and paired with its evidence
# --------------------------------------------------------------------------


def test_basis_declaration_checks_every_field_the_schema_declares() -> None:
    """Adding a basis column to the schema must break this, not slip past it.

    ``BasisDeclaration.__post_init__`` compares its own field count against
    ``BASIS_FIELDS``. This asserts the two are in step today, so that the
    comparison is meaningful rather than vacuously true.
    """
    assert len(BASIS_FIELDS) == 5
    assert {value for value, _ in BASIS_FIELDS} == {
        "basis_budget",
        "basis_team_count",
        "basis_roster_size",
        "basis_scoring_type",
        "basis_category_count",
    }


def test_a_value_without_evidence_is_refused() -> None:
    with pytest.raises(BasisIncomplete, match="there is no default"):
        stated_basis(budget=None)


def test_an_unestablished_field_carrying_a_value_is_refused() -> None:
    """A number nobody stands behind must not be stored as if somebody does."""
    with pytest.raises(BasisIncomplete, match="must not be stored as if somebody does"):
        stated_basis(budget_evidence=BasisEvidence.UNESTABLISHED)


def test_an_inference_without_a_note_is_refused() -> None:
    with pytest.raises(BasisIncomplete, match="requires a note"):
        stated_basis(budget_evidence=BasisEvidence.INFERRED)


def test_the_fantraxhq_basis_is_expressible_exactly_as_investigated() -> None:
    """Budget unestablished; team count and roster size inferred with a note.

    This is the shape the falsification above produced, and it has to be
    expressible — a schema that could only record "known" or "blank" would have
    forced the $200 guess back in.
    """
    basis = BasisDeclaration(
        budget=None,
        budget_evidence=BasisEvidence.UNESTABLISHED,
        team_count=12,
        team_count_evidence=BasisEvidence.INFERRED,
        roster_size=13,
        roster_size_evidence=BasisEvidence.INFERRED,
        scoring_type=ScoringType.H2H_CATEGORIES,
        scoring_type_evidence=BasisEvidence.STATED,
        category_count=8,
        category_count_evidence=BasisEvidence.STATED,
        note=(
            "Page states 156 rostered players and 8 categories. 12 teams x 13 roster slots = "
            "156 exactly, so team count and roster size are inferred from that arithmetic. The "
            "published pool sums to $2,655, so no budget is inferable."
        ),
    )
    assert basis.budget is None
    assert basis.category_count == 8


# --------------------------------------------------------------------------
# Importer: what it writes, what it refuses to write
# --------------------------------------------------------------------------


def import_fantraxhq(session: Session, **overrides: Any) -> AuctionImportOutcome:
    kwargs: dict[str, Any] = {
        "profile_id": "fantraxhq-auction-values",
        "season": "2026-27",
        "as_of_date": date(2026, 8, 21),
        "csv_bytes": load("fantraxhq_auction_values.csv").encode("utf-8"),
        "basis": stated_basis(),
        "original_filename": "fantraxhq_auction_values.csv",
    }
    kwargs.update(overrides)
    return import_auction_value_csv(session, **kwargs)


def test_importing_writes_one_row_per_value_with_its_lineage(seeded_players: Session) -> None:
    session = seeded_players
    outcome = import_fantraxhq(session)

    values = session.scalars(select(PublishedAuctionValue)).all()
    assert len(values) == 10
    assert {value.data_layer for value in values} == {"market"}
    assert {value.value_kind for value in values} == {AuctionValueKind.PROJECTED}
    assert {value.season for value in values} == {"2026-27"}

    alpha = next(v for v in values if v.source_player_name == "Player Alpha")
    assert alpha.value_dollars == Decimal("74")
    assert alpha.value_raw == "$74"

    auction_import = session.scalars(select(AuctionValueImport)).one()
    assert auction_import.profile_id == "fantraxhq-auction-values"
    assert auction_import.profile_header_contract_verified is False
    assert auction_import.profile_lineage["source_slug"] == "fantraxhq"
    assert auction_import.row_count == 10
    assert auction_import.matched_count == 10
    assert auction_import.unmatched_count == 0
    assert outcome.created is True


@pytest.mark.parametrize("seed_count", [0, 1, 4, 9, 10])
def test_every_reported_count_matches_an_independent_observation(
    session: Session, seed_count: int
) -> None:
    """A count is a claim about work done, not evidence that it was done.

    ``AuctionValueImport`` carries the counters, and the importer writes both
    the counters and the rows. So asserting ``matched_count == 10`` beside
    ``len(values) == 10`` compares two literals rather than tying the report to
    the reality: an importer that wrote correct-looking counts and no rows
    passes both. The bucket-sum check has the same shape one level up, since
    every term in it comes from the same writer.

    So each counter is compared here against something the importer did not
    author: rows actually present in ``published_auction_values``, and the row
    count against the fixture's own line count read off disk. Parametrised
    across cohort sizes so the *relationship* is under test rather than one
    arithmetic coincidence — a hardcoded 10 survives a single-point check.
    """
    for nba_id, name, team, position in FIXTURE_PLAYERS[:seed_count]:
        seed_player(session, nba_id=nba_id, name=name, team_abbreviation=team, position=position)

    outcome = import_fantraxhq(session)
    auction_import = session.scalars(select(AuctionValueImport)).one()

    csv_data_rows = (
        len([line for line in load("fantraxhq_auction_values.csv").splitlines() if line.strip()])
        - 1
    )
    assert csv_data_rows == 10, "guard: the fixture changed and this test's basis moved with it"
    assert auction_import.row_count == csv_data_rows, (
        "row_count must match the file, not the importer's opinion of the file"
    )

    written = session.scalars(select(PublishedAuctionValue)).all()
    observed_players = {value.player_id for value in written}

    assert auction_import.matched_count == len(observed_players), (
        f"matched_count claims {auction_import.matched_count} players but "
        f"{len(observed_players)} distinct players actually have rows"
    )
    assert outcome.values_written == len(written), (
        f"values_written claims {outcome.values_written} but the table holds {len(written)}"
    )
    assert auction_import.matched_count == seed_count, (
        "and the observation itself must track the cohort we actually seeded"
    )
    assert (
        auction_import.matched_count
        + auction_import.needs_review_count
        + auction_import.unmatched_count
        == csv_data_rows
    ), "every row must land in exactly one bucket; none may vanish"


@pytest.mark.parametrize(
    ("fixture_name", "profile_id", "expected_data_rows"),
    [
        ("fantraxhq_auction_values.csv", "fantraxhq-auction-values", 10),
        ("hashtag_auction_values.csv", "hashtag-auction-values", 8),
        ("yahoo_draft_analysis.csv", "yahoo-draft-analysis", 5),
    ],
)
def test_row_count_tracks_the_file_and_not_a_constant(
    seeded_players: Session,
    fixture_name: str,
    profile_id: str,
    expected_data_rows: int,
) -> None:
    """Three files of three different lengths, because one length proves nothing.

    Mutation-driven: replacing ``row_count = parsed.total_rows`` with
    ``row_count = 10`` survives any check that only ever imports the ten-row
    FantraxHQ fixture, since the constant and the truth coincide there. That is
    the counter-standing-in-for-an-observation failure in its hardest-to-see
    form — the assertion is real, the value is right, and the test still cannot
    tell the two apart.

    Distinguishing them needs independent variation in the observed quantity,
    not a stronger assertion about one value. Hence three sizes.
    """
    on_disk = len([line for line in load(fixture_name).splitlines() if line.strip()]) - 1
    assert on_disk == expected_data_rows, (
        f"{fixture_name} holds {on_disk} data rows, not the {expected_data_rows} this "
        "test was written against; the fixture changed and the expectation did not"
    )

    import_auction_value_csv(
        seeded_players,
        profile_id=profile_id,
        season="2026-27",
        as_of_date=date(2026, 8, 21),
        csv_bytes=load(fixture_name).encode("utf-8"),
        basis=stated_basis(),
        original_filename=fixture_name,
    )

    auction_import = seeded_players.scalars(select(AuctionValueImport)).one()
    assert auction_import.row_count == on_disk


def test_a_player_we_cannot_resolve_is_counted_and_not_imported(session: Session) -> None:
    """Fail-closed. A benchmark attached to the wrong player is worse than none.

    Note what is seeded here: only *some* of the fixture's players exist, so
    the unresolved branch is genuinely entered rather than merely available.
    """
    seed_player(session, nba_id=1, name="Player Alpha", team_abbreviation="BOS", position="SF")
    seed_player(session, nba_id=2, name="Player Beta", team_abbreviation="LAL", position="PG")

    outcome = import_fantraxhq(session)

    written = session.scalars(select(PublishedAuctionValue)).all()
    assert {value.source_player_name for value in written} == {"Player Alpha", "Player Beta"}
    assert outcome.values_written == 2

    auction_import = session.scalars(select(AuctionValueImport)).one()
    assert auction_import.row_count == 10
    assert auction_import.matched_count == 2
    assert (
        auction_import.matched_count
        + auction_import.needs_review_count
        + (auction_import.unmatched_count)
        == 10
    ), "every row must land in exactly one resolution bucket; none may vanish"


def test_nothing_is_written_to_the_identity_crosswalk(seeded_players: Session) -> None:
    """Publishers with no opinion about identity do not get a namespace.

    Same reasoning as the separate tables: ``PlayerExternalId.source`` is an
    ``ExternalSource``, and FantraxHQ is not one. If this ever fails, someone
    has widened an identity vocabulary to admit a publisher, which is the thing
    ruling (a) refused.
    """
    session = seeded_players
    before = session.scalar(select(func.count()).select_from(PlayerExternalId))
    import_fantraxhq(session)
    after = session.scalar(select(func.count()).select_from(PlayerExternalId))
    assert before == after == len(FIXTURE_PLAYERS)


def test_reimporting_the_same_bytes_converges_rather_than_duplicating(
    seeded_players: Session,
) -> None:
    session = seeded_players
    first = import_fantraxhq(session)
    second = import_fantraxhq(session)

    assert first.created is True
    assert second.created is False
    assert session.scalar(select(func.count()).select_from(AuctionValueImport)) == 1
    assert session.scalar(select(func.count()).select_from(PublishedAuctionValue)) == 10


def test_a_different_as_of_date_is_a_different_import(seeded_players: Session) -> None:
    """Row grain is (source, player, as-of date).

    "What did source X say about player Y as of date Z" has to have one answer,
    and a later snapshot must not overwrite an earlier one — a benchmark whose
    history is destroyed cannot be defended after the fact.
    """
    session = seeded_players
    import_fantraxhq(session)
    import_fantraxhq(session, as_of_date=date(2026, 9, 30))

    assert session.scalar(select(func.count()).select_from(AuctionValueImport)) == 2
    assert session.scalar(select(func.count()).select_from(PublishedAuctionValue)) == 20
    dates = session.scalars(select(PublishedAuctionValue.as_of_date).distinct()).all()
    assert set(dates) == {date(2026, 8, 21), date(2026, 9, 30)}


def test_yahoo_stores_both_kinds_for_the_same_player_and_date(seeded_players: Session) -> None:
    """The row key is (import, player, kind), so both survive.

    A unique key of (import, player) would have silently kept whichever kind
    was written last — model output or market observation, depending on column
    order, with nothing to show which.
    """
    session = seeded_players
    import_auction_value_csv(
        session,
        profile_id="yahoo-draft-analysis",
        season="2026-27",
        as_of_date=date(2026, 8, 21),
        csv_bytes=load("yahoo_draft_analysis.csv").encode("utf-8"),
        basis=stated_basis(
            budget=None,
            budget_evidence=BasisEvidence.UNESTABLISHED,
            team_count=None,
            team_count_evidence=BasisEvidence.UNESTABLISHED,
        ),
    )
    values = session.scalars(select(PublishedAuctionValue)).all()
    assert len(values) == 10
    alpha = [v for v in values if v.source_player_name == "Player Alpha"]
    assert {v.value_kind for v in alpha} == {
        AuctionValueKind.OBSERVED_MARKET,
        AuctionValueKind.PROJECTED,
    }
    assert {v.value_dollars for v in alpha} == {Decimal("71"), Decimal("66")}


def test_registering_a_source_twice_updates_its_lineage_rather_than_duplicating(
    session: Session,
) -> None:
    """Lineage is a finding, and findings arrive late.

    Establishing that a publisher derives from a projection set we import is
    exactly the discovery the guard exists to act on, so it has to be able to
    land after the first import.
    """
    descriptor = source_for("fantraxhq")
    first = register_auction_value_source(session, descriptor)
    revised = AuctionSourceDescriptor(
        slug=descriptor.slug,
        display_name=descriptor.display_name,
        publisher_url=descriptor.publisher_url,
        derivation_method=AuctionValueDerivation.Z_SCORE_BUDGET_DISTRIBUTION,
        derivation_evidence="Later established to recompute from Hashtag's projections.",
        inputs=(
            SourceInputDescriptor(
                input_kind=AuctionValueInputKind.PROJECTIONS,
                input_label="Hashtag Basketball season projections",
                our_projection_source=ExternalSource.HASHTAG,
                evidence="Established after the first import.",
            ),
        ),
    )
    second = register_auction_value_source(session, revised)

    assert first.id == second.id
    assert session.scalar(select(func.count()).select_from(AuctionValueSource)) == 1
    inputs = session.scalars(
        select(AuctionValueSourceInput).where(AuctionValueSourceInput.source_id == second.id)
    ).all()
    assert len(inputs) == 1, "the superseded input must be removed, not accumulated"
    assert inputs[0].our_projection_source is ExternalSource.HASHTAG


def test_bytes_that_decode_as_nothing_are_refused(seeded_players: Session) -> None:
    """A file we cannot read is refused, not read as best we can.

    UTF-8, then UTF-8 with a BOM, then CP1252 — because these files come out of
    a browser via a spreadsheet, and a mojibake player name resolves to nobody
    while looking like a data problem rather than an encoding one.
    """
    with pytest.raises(ValueError, match="could not decode"):
        import_fantraxhq(seeded_players, csv_bytes=b"Player,Value\n\xff\xfe\x00\x00bad,\x81\x8d\n")


def test_a_player_with_no_nba_crosswalk_link_is_not_a_resolution_target(
    session: Session,
) -> None:
    """Why the importer's crosswalk lookup is an invariant, not a fallback.

    ``build_player_targets`` derives every target key from the NBA crosswalk,
    so a canonical player without an NBA link cannot be matched at all — it is
    excluded a step earlier than the lookup. That makes "accepted, but no
    crosswalk row" unreachable, which is why the importer raises there instead
    of skipping: a silent skip would drop a priced player out of every count
    while every count still added up.

    Asserted positively — the player exists, and is still unmatched — rather
    than by observing that nothing was written, which would also be true if the
    file had failed to parse.
    """
    orphan = Player(
        full_name="Player Alpha",
        normalized_name=normalize_name("Player Alpha").key,
    )
    session.add(orphan)
    session.flush()
    assert session.scalar(select(func.count()).select_from(Player)) == 1
    assert session.scalar(select(func.count()).select_from(PlayerExternalId)) == 0

    outcome = import_fantraxhq(session)

    auction_import = session.scalars(select(AuctionValueImport)).one()
    assert auction_import.row_count == 10
    assert auction_import.matched_count == 0
    assert auction_import.unmatched_count == 10, (
        "an unlinked player must be reported as unmatched, not quietly absent"
    )
    assert outcome.values_written == 0


def test_a_basis_field_added_to_the_schema_and_not_to_the_declaration_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assert the shape we expect, rather than the absence of one we fear.

    ``BasisDeclaration`` validates a fixed list of five pairs. If a sixth basis
    column were added to the schema, a class that simply looped over its own
    five would validate a subset and report success — the exact failure this
    project has catalogued repeatedly. So it compares its own count against
    ``BASIS_FIELDS`` and refuses when they diverge. Driven here, because a
    guard nobody has seen fire is a guard nobody has tested.
    """
    from hoops_gm.ingest.auction_values import importer as importer_module

    monkeypatch.setattr(
        importer_module, "BASIS_FIELDS", (*BASIS_FIELDS, ("basis_new", "basis_new_evidence"))
    )
    with pytest.raises(BasisIncomplete, match="would go unvalidated"):
        stated_basis()


# --------------------------------------------------------------------------
# The database refuses what the dataclass refuses
# --------------------------------------------------------------------------


def test_the_database_refuses_a_basis_value_marked_unestablished(session: Session) -> None:
    """The CHECK is what makes the pairing true; the dataclass makes it early.

    Driven through a real insert rather than read off the metadata, because a
    constraint that is declared and never violated is a constraint nobody has
    shown to work.
    """
    source_row = register_auction_value_source(session, source_for("manual"))
    session.add(
        AuctionValueImport(
            source_id=source_row.id,
            season="2026-27",
            as_of_date=date(2026, 8, 21),
            content_sha256="0" * 64,
            profile_id="manual-auction-values",
            profile_version="1",
            profile_header_contract_verified=False,
            profile_lineage={},
            basis_budget=Decimal("200"),
            basis_budget_evidence=BasisEvidence.UNESTABLISHED,
            basis_team_count=12,
            basis_team_count_evidence=BasisEvidence.STATED,
            basis_roster_size=13,
            basis_roster_size_evidence=BasisEvidence.STATED,
            basis_scoring_type=ScoringType.H2H_CATEGORIES,
            basis_scoring_type_evidence=BasisEvidence.STATED,
            basis_category_count=9,
            basis_category_count_evidence=BasisEvidence.STATED,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_the_database_refuses_an_empty_derivation_evidence(session: Session) -> None:
    """An unexamined blank must be inexpressible, not merely discouraged."""
    session.add(
        AuctionValueSource(
            slug="blank",
            display_name="Blank",
            derivation_method=AuctionValueDerivation.UNESTABLISHED,
            derivation_evidence="",
            data_layer="market",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


# --------------------------------------------------------------------------
# Independence: the refusal, proved to fire
# --------------------------------------------------------------------------


def import_projections(session: Session, source: ExternalSource) -> None:
    """Import a real projection file, so the guard tests against data we hold.

    Only Basketball Monster is wired here, and the reason is a finding rather
    than an omission: the projection importer refuses any profile that is not
    verified for the season, and Basketball Monster's is the only vendor
    profile that is. ``test_hashtag_projections_cannot_currently_be_imported``
    pins that, so the day it changes, the reason this helper is narrow becomes
    visible instead of quietly obsolete.
    """
    if source is ExternalSource.BASKETBALL_MONSTER:
        payload = (PROJECTION_FIXTURES / "basketball_monster_sample.csv").read_bytes()
        profile = BASKETBALL_MONSTER_PROFILE
    else:  # pragma: no cover - guarded by the assertion below
        raise AssertionError(f"no verified projection profile wired for {source}")
    assert payload.strip(), "projection fixture is empty, so importing it would prove nothing"
    import_projection_csv(
        session,
        source=source,
        display_name=f"{source.value} projections",
        season="2026-27",
        csv_bytes=payload,
        profile=profile,
    )
    session.flush()


def record_projection_import(session: Session, source: ExternalSource) -> ProjectionImport:
    """Record that we hold an imported file from ``source``, without a CSV.

    Used only for Hashtag, because Hashtag projections cannot be imported
    through the production path today (see the test immediately below). The
    guard under test is a query over ``projection_sources`` joined to
    ``projection_imports``, so this constructs exactly the state that query
    reads and nothing more — but it is a hand-built row, and hand-built rows
    can be shaped in ways no producer can write. It is therefore used for the
    Hashtag case alone; the headline circularity test drives a real import.
    """
    source_row = get_or_create_projection_source(
        session, source=source, display_name=f"{source.value} projections"
    )
    session.flush()
    profile_version = ProjectionProfileVersion(
        source_id=source_row.id,
        profile_id=f"{source.value}-test",
        profile_version="1",
        verified=False,
        verified_seasons=[],
        verification_evidence="Constructed by a test to represent a held import.",
        definition_sha256="0" * 64,
        definition={},
    )
    session.add(profile_version)
    session.flush()
    projection_import = ProjectionImport(
        source_id=source_row.id,
        profile_version_id=profile_version.id,
        season="2026-27",
        imported_at=datetime(2026, 8, 21, tzinfo=UTC),
        content_sha256="1" * 64,
        profile_id=profile_version.profile_id,
        profile_version=profile_version.profile_version,
        profile_verified=False,
        profile_definition_sha256=profile_version.definition_sha256,
        profile_lineage={"profile_id": profile_version.profile_id, "version": "1"},
        row_count=1,
        matched_count=1,
        needs_review_count=0,
        unmatched_count=0,
        rejected_count=0,
    )
    session.add(projection_import)
    session.flush()
    return projection_import


def test_hashtag_projections_cannot_currently_be_imported(seeded_players: Session) -> None:
    """Why the Hashtag guard test builds its state by hand.

    The projection importer refuses an unverified profile outright, and
    Hashtag's is unverified. So the "guard fires on Hashtag" case cannot be
    driven through the production path *today* — not because the guard is
    untestable, but because the upstream it depends on is closed.

    Pinned as a test rather than left as a comment, because a comment saying
    "this is unavailable" survives the day it becomes available.
    """
    with pytest.raises(ProjectionProfileError, match="not verified"):
        import_projection_csv(
            seeded_players,
            source=ExternalSource.HASHTAG,
            display_name="Hashtag projections",
            season="2026-27",
            csv_bytes=(PROJECTION_FIXTURES / "hashtag_sample.csv").read_bytes(),
            profile=HASHTAG_PROFILE,
        )


def test_imported_projection_sources_reports_what_we_hold_not_what_is_registered(
    seeded_players: Session,
) -> None:
    """ "Has at least one import" rather than "is registered", and it matters.

    Refusing on a registered source with no imported file would be refusing on
    an intention rather than on data we hold. Registering without importing is
    the case that separates the two, so it is checked explicitly — a function
    that simply returned every registered source would otherwise pass.
    """
    session = seeded_players
    assert imported_projection_sources(session) == frozenset()

    get_or_create_projection_source(
        session, source=ExternalSource.FANTASYPROS, display_name="FantasyPros"
    )
    session.flush()
    assert imported_projection_sources(session) == frozenset(), (
        "a registered source with no import must not count as one we hold"
    )

    import_projections(session, ExternalSource.BASKETBALL_MONSTER)
    assert imported_projection_sources(session) == frozenset({ExternalSource.BASKETBALL_MONSTER})


def test_basketball_monster_is_admissible_until_we_import_its_projections(
    seeded_players: Session,
) -> None:
    """The negative half of the guard, which is what makes the positive half mean something.

    Without this, a guard that refused everything unconditionally would pass
    the circularity test below.
    """
    session = seeded_players
    source_row = register_auction_value_source(session, source_for("basketball_monster"))
    findings = assess_source_independence(session, source_row)
    assert [finding.code for finding in findings] == []


def test_importing_basketball_monster_projections_makes_its_auction_values_inadmissible(
    seeded_players: Session,
) -> None:
    """The headline circularity case, driven end to end.

    BBM's dollar values are a deterministic z-score transform of the BBM
    projections. Benchmarking against them would compare our valuation with our
    own primary projection input wearing a dollar sign, so every match would be
    fake agreement and every divergence would measure two formulas rather than
    two opinions about players.
    """
    session = seeded_players
    source_row = register_auction_value_source(session, source_for("basketball_monster"))

    before = assess_source_independence(session, source_row)
    assert CIRCULAR_LINEAGE not in {f.code for f in before}

    import_projections(session, ExternalSource.BASKETBALL_MONSTER)

    after = assess_source_independence(session, source_row)
    codes = {finding.code for finding in after}
    assert CIRCULAR_LINEAGE in codes, "the guard did not fire on the case it exists for"
    circular = next(f for f in after if f.code == CIRCULAR_LINEAGE)
    assert circular.admissible is False
    assert "basketball_monster" in circular.detail
    assert "THIS IS THE GUARD WORKING, NOT A DATA ERROR" in circular.detail
    assert "Do not loosen this check" in circular.detail


def test_the_guard_fires_on_hashtag_the_day_we_import_hashtag_projections(
    seeded_players: Session,
) -> None:
    """Named in the ruling as expected behaviour, so it is asserted as such.

    Hashtag is the primary seed. This test exists so that the day someone adds
    Hashtag projections and this fires, the failure is recognisable as the
    design rather than as a regression.
    """
    session = seeded_players
    source_row = register_auction_value_source(session, source_for("hashtag_basketball"))
    assert not assess_source_independence(session, source_row)

    record_projection_import(session, ExternalSource.HASHTAG)

    findings = assess_source_independence(session, source_row)
    assert [f.code for f in findings] == [CIRCULAR_LINEAGE]
    assert findings[0].admissible is False
    assert "stop importing hashtag projections" in findings[0].detail.lower()


def test_a_source_with_no_recorded_inputs_is_a_caveat_not_a_refusal(session: Session) -> None:
    """An investigated unknown is usable, provided it is labelled.

    Distinct from circularity in both code and verdict, which is why they are
    separate findings rather than one boolean.
    """
    source_row = register_auction_value_source(session, source_for("manual"))
    findings = assess_source_independence(session, source_row)
    assert [f.code for f in findings] == [DERIVATION_UNESTABLISHED]
    assert findings[0].admissible is True
    assert "not a clean bill of health" in findings[0].detail


def test_an_unestablished_basis_blocks_benchmark_use_on_its_own(seeded_players: Session) -> None:
    """A different cause from circularity, reaching the same verdict.

    Two price lists at different budgets are different quantities that both
    look like money.
    """
    session = seeded_players
    outcome = import_fantraxhq(
        session,
        basis=stated_basis(
            budget=None,
            budget_evidence=BasisEvidence.UNESTABLISHED,
            category_count=8,
            note="8-category per the page; published pool of $2,655 rules out a $200 budget.",
        ),
    )
    verdict = assess_benchmark_admissibility(session, outcome.auction_import)

    assert verdict.admissible is False
    codes = {finding.code for finding in verdict.blocking_findings}
    assert codes == {BASIS_UNESTABLISHED}
    detail = next(f for f in verdict.findings if f.code == BASIS_UNESTABLISHED).detail
    assert "basis_budget" in detail
    assert "Model gate" in detail or "auction-values" in detail
    assert "NOT admissible" in verdict.explain()


def test_a_fully_stated_basis_from_an_independent_source_is_admissible(
    seeded_players: Session,
) -> None:
    """The whole point. If nothing ever passes, the guard is a wall, not a rule."""
    session = seeded_players
    outcome = import_fantraxhq(session)
    verdict = assess_benchmark_admissibility(session, outcome.auction_import)

    assert verdict.findings == ()
    assert verdict.admissible is True
    assert "NOT admissible" not in verdict.explain()


def test_circularity_and_an_unestablished_basis_are_reported_separately(
    seeded_players: Session,
) -> None:
    """Two causes, two findings. One boolean would have hidden a cause."""
    session = seeded_players
    record_projection_import(session, ExternalSource.HASHTAG)
    outcome = import_auction_value_csv(
        session,
        profile_id="hashtag-auction-values",
        season="2026-27",
        as_of_date=date(2026, 8, 21),
        csv_bytes=load("hashtag_auction_values.csv").encode("utf-8"),
        basis=stated_basis(
            roster_size=None,
            roster_size_evidence=BasisEvidence.UNESTABLISHED,
        ),
    )
    verdict = assess_benchmark_admissibility(session, outcome.auction_import)

    assert {f.code for f in verdict.blocking_findings} == {CIRCULAR_LINEAGE, BASIS_UNESTABLISHED}
    assert verdict.admissible is False
