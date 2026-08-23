"""Contract tests for the cross-store cohort assembly tool.

Every test here drives real SQLite files rather than mocking a connection. The
defect this module exists to prevent is a merge that *succeeds* and produces a
store whose numbers are wrong, and a mocked connection cannot exhibit that: it
agrees with whatever the test asserts. The stores are tiny, so the cost of
building genuine ones is a few milliseconds.

The fixtures are hand-built rather than recorded from the operational stores,
because the operational ledger holds 43,037 real participation rows and a
recorded slice of it is neither committable nor privacy-safe. What is recorded
from reality is the *shape*: column names, the surrogate/stable split, and the
three-games-without-tipoff case, all taken from the real 2025-26 stores.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from hoops_gm.ingest.injury_report.merge_stores import (
    IDENTITY_ANCHORS,
    MERGED_TABLES,
    OPENS_STORES_OUTSIDE_THE_CENSUS,
    RECEIPT_SUFFIX,
    RECONCILED_GAME_COLUMNS,
    STORE_RULE_ALLOWLIST_REASON,
    StoreMergeRefused,
    build_receipt,
    check_alignment,
    merge_injury_reports,
    read_only,
    receipt_path,
    store_sha256,
)

pytestmark = pytest.mark.adapter_contract

SCHEMA = """
CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY);
CREATE TABLE nba_teams (id INTEGER PRIMARY KEY, nba_team_id TEXT NOT NULL UNIQUE);
CREATE TABLE nba_games (
    id INTEGER PRIMARY KEY,
    nba_game_id TEXT NOT NULL UNIQUE,
    game_date TEXT,
    tipoff_utc TEXT,
    home_score INTEGER,
    away_score INTEGER
);
CREATE TABLE players (id INTEGER PRIMARY KEY, full_name TEXT);
CREATE TABLE player_external_ids (
    id INTEGER PRIMARY KEY,
    player_id INTEGER NOT NULL REFERENCES players(id),
    source TEXT NOT NULL,
    external_id TEXT NOT NULL
);
CREATE TABLE injury_report_entries (
    id INTEGER PRIMARY KEY,
    report_timestamp TEXT NOT NULL,
    game_id INTEGER REFERENCES nba_games(id),
    player_id INTEGER REFERENCES players(id),
    status TEXT,
    source_url TEXT
);
"""

VERSION = "0016"

#: Mirrors the real stores: the ledger's tip-offs come from BoxScoreSummaryV3
#: and three real games (0022500259/60/61) carry none, while the sweep's come
#: from ScheduleLeagueV2 and are populated for all of them. The merge must keep
#: the ledger's column rather than backfilling from the other endpoint.
#: ``(surrogate_id, nba_game_id, game_date, tipoff_utc | None, home, away)``.
GameRow = tuple[int, str, str, str | None, int, int]

GAMES: list[GameRow] = [
    (1, "0022500001", "2025-10-21", "2025-10-22T00:00:00", 101, 99),
    (2, "0022500002", "2025-10-22", "2025-10-23T00:30:00", 110, 104),
    (3, "0022500259", "2025-11-05", None, 95, 90),
]


def _build(path: Path, *, games: list[GameRow], reports: int, tipoff_for_all: bool) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(SCHEMA)
        connection.execute("INSERT INTO alembic_version VALUES (?)", (VERSION,))
        connection.executemany("INSERT INTO nba_teams VALUES (?, ?)", [(1, "1610612737")])
        rows = [
            (
                game[0],
                game[1],
                game[2],
                game[3] or ("2025-11-06T01:00:00" if tipoff_for_all else None),
                game[4],
                game[5],
            )
            for game in games
        ]
        connection.executemany("INSERT INTO nba_games VALUES (?, ?, ?, ?, ?, ?)", rows)
        connection.executemany("INSERT INTO players VALUES (?, ?)", [(1, "A Player")])
        connection.execute(
            "INSERT INTO player_external_ids VALUES (1, 1, 'nba', '203999')",
        )
        connection.executemany(
            "INSERT INTO injury_report_entries VALUES (?, ?, ?, ?, ?, ?)",
            [
                (n, f"2025-10-2{n % 9} 18:30:00.000000", 1, 1, "out", "https://x/r.pdf")
                for n in range(1, reports + 1)
            ],
        )
        connection.commit()


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    """The participation store: real tip-offs, no injury reports."""
    path = tmp_path / "hoops_gm.db"
    _build(path, games=GAMES, reports=0, tipoff_for_all=False)
    return path


@pytest.fixture
def sweep(tmp_path: Path) -> Path:
    """The report sweep: injury reports, and tip-offs from the other endpoint."""
    path = tmp_path / "throwaway-report-sweep.db"
    _build(path, games=GAMES, reports=5, tipoff_for_all=True)
    return path


class TestTheMergeProducesOneStoreHoldingBothHalves:
    def test_it_copies_the_reports_and_keeps_the_participation_tipoffs(
        self, ledger: Path, sweep: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "merged.db"

        alignment, copied = merge_injury_reports(participation_db=ledger, report_db=sweep, out=out)

        assert copied == {"injury_report_entries": 5}
        assert alignment.refusal() is None
        with read_only(out) as merged:
            assert merged.execute("SELECT COUNT(*) FROM injury_report_entries").fetchone()[0] == 5
            # The three-games case: the ledger has no tip-off for 0022500259 and
            # the sweep does. Copying it would import a ScheduleLeagueV2 instant
            # into a column the cohort reads as BoxScoreSummaryV3, which is the
            # exact provenance laundering the receipt exists to prevent.
            tipoff = merged.execute(
                "SELECT tipoff_utc FROM nba_games WHERE nba_game_id = '0022500259'"
            ).fetchone()[0]
        assert tipoff is None, "the merge backfilled a tip-off from the wrong endpoint"

    def test_only_the_declared_tables_are_merged(
        self, ledger: Path, sweep: Path, tmp_path: Path
    ) -> None:
        """A wider copy would manufacture provenance for runs that never happened."""
        assert MERGED_TABLES == ("injury_report_entries",)
        out = tmp_path / "merged.db"

        _, copied = merge_injury_reports(participation_db=ledger, report_db=sweep, out=out)

        assert set(copied) == set(MERGED_TABLES)


class TestItRefusesRatherThanProducingAWrongStore:
    def test_a_surrogate_that_means_a_different_game_is_refused(
        self, ledger: Path, sweep: Path, tmp_path: Path
    ) -> None:
        """The merge is only valid because surrogate ids agree; prove it checks."""
        with closing(sqlite3.connect(sweep)) as connection:
            connection.execute(
                "UPDATE nba_games SET nba_game_id = '0022599999' WHERE id = 2",
            )
            connection.commit()

        with pytest.raises(StoreMergeRefused, match="surrogate primary keys"):
            merge_injury_reports(
                participation_db=ledger, report_db=sweep, out=tmp_path / "merged.db"
            )
        assert not (tmp_path / "merged.db").exists()

    def test_stores_that_disagree_about_a_tipoff_are_refused(
        self, ledger: Path, sweep: Path, tmp_path: Path
    ) -> None:
        with closing(sqlite3.connect(sweep)) as connection:
            connection.execute(
                "UPDATE nba_games SET tipoff_utc = '2099-01-01T00:00:00' WHERE id = 1",
            )
            connection.commit()

        with pytest.raises(StoreMergeRefused, match=r"disagree about nba_games\.tipoff_utc"):
            merge_injury_reports(
                participation_db=ledger, report_db=sweep, out=tmp_path / "merged.db"
            )

    def test_a_comparison_over_zero_games_is_itself_a_refusal(
        self, ledger: Path, sweep: Path, tmp_path: Path
    ) -> None:
        """Columns that were never compared agree perfectly and witness nothing.

        This is the failure this repository keeps meeting, so it is driven rather
        than asserted in a docstring: empty both stores of games and the identity
        maps still "agree" (trivially, both empty), yet nothing was witnessed.
        """
        for store in (ledger, sweep):
            with closing(sqlite3.connect(store)) as connection:
                connection.execute("DELETE FROM injury_report_entries")
                connection.execute("DELETE FROM nba_games")
                connection.commit()

        with pytest.raises(StoreMergeRefused, match="zero games were actually compared"):
            merge_injury_reports(
                participation_db=ledger, report_db=sweep, out=tmp_path / "merged.db"
            )

    def test_an_existing_output_is_not_silently_replaced(
        self, ledger: Path, sweep: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "merged.db"
        out.write_bytes(b"prior work")

        with pytest.raises(StoreMergeRefused, match="already exists"):
            merge_injury_reports(participation_db=ledger, report_db=sweep, out=out)

        assert out.read_bytes() == b"prior work"

    def test_merging_into_a_populated_table_is_refused(
        self, ledger: Path, sweep: Path, tmp_path: Path
    ) -> None:
        """A second merge would double-count while looking exactly like a first."""
        with closing(sqlite3.connect(ledger)) as connection:
            connection.execute(
                "INSERT INTO injury_report_entries VALUES (900, '2025-10-21 18:30:00', "
                "1, 1, 'out', 'https://x/r.pdf')",
            )
            connection.commit()

        with pytest.raises(StoreMergeRefused, match="already holds 1 row"):
            merge_injury_reports(
                participation_db=ledger, report_db=sweep, out=tmp_path / "merged.db"
            )

    def test_an_absent_store_is_refused_rather_than_created(self, tmp_path: Path) -> None:
        """``mode=ro`` is the guard; a created-on-connect store reports a false zero.

        The refusal is raised as :class:`StoreMergeRefused` rather than surfacing
        SQLite's own ``OperationalError``, so a caller gets the path and the
        reason instead of ``unable to open database file``.
        """
        absent = tmp_path / "nowhere" / "hoops_gm.db"

        with (
            pytest.raises(StoreMergeRefused, match="Refusing to create one"),
            read_only(absent),
        ):
            pass  # pragma: no cover - the open itself is the assertion

        assert not absent.exists()


class TestTheReceiptRecordsProvenanceRatherThanAssertingIt:
    def test_the_receipt_names_stores_without_leaking_the_operators_directories(
        self, ledger: Path, sweep: Path, tmp_path: Path
    ) -> None:
        """The receipt is embedded into a committed manifest, so it must be clean.

        The first version wrote absolute paths. The operational stores live under
        the operator's home directory, so that published an account name into the
        repository. Nothing caught it: an absolute path is well-formed, correct,
        and violates no schema. This is the check that would have.
        """
        out = tmp_path / "merged.db"

        merge_injury_reports(participation_db=ledger, report_db=sweep, out=out)

        serialised = receipt_path(out).read_text(encoding="utf-8")
        for leaked in (str(tmp_path), str(ledger.parent), ledger.parent.name):
            assert leaked not in serialised, (
                f"the receipt embeds a directory path ({leaked}) and is committed "
                f"verbatim inside the cohort manifest"
            )
        receipt = json.loads(serialised)
        assert receipt["sources"]["participation_ledger"]["store"] == ledger.name
        assert receipt["sources"]["injury_report_sweep"]["store"] == sweep.name
        assert receipt["merged_store"]["store"] == out.name

    def test_it_names_both_sources_by_content_and_what_each_supplied(
        self, ledger: Path, sweep: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "merged.db"

        merge_injury_reports(participation_db=ledger, report_db=sweep, out=out)

        receipt = json.loads(receipt_path(out).read_text(encoding="utf-8"))
        assert receipt_path(out).name.endswith(RECEIPT_SUFFIX)
        sources = receipt["sources"]
        assert sources["participation_ledger"]["sha256"] == store_sha256(ledger)
        assert sources["injury_report_sweep"]["sha256"] == store_sha256(sweep)
        assert sources["participation_ledger"]["sha256"] != sources["injury_report_sweep"]["sha256"]
        # The whole point: the two halves demonstrably came from different files,
        # so the manifest's tip-off check cannot be one endpoint against itself.
        assert receipt["merged_store"]["sha256"] == store_sha256(out)
        assert receipt["copied_rows"] == {"injury_report_entries": 5}

    def test_it_carries_the_counts_that_make_agreement_falsifiable(
        self, ledger: Path, sweep: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "merged.db"

        merge_injury_reports(participation_db=ledger, report_db=sweep, out=out)

        reconciliation = json.loads(receipt_path(out).read_text(encoding="utf-8"))[
            "cross_store_nba_games_reconciliation"
        ]
        for column in RECONCILED_GAME_COLUMNS:
            assert reconciliation[column]["compared"] > 0, (
                f"{column} reports agreement over zero comparisons, which is not agreement"
            )
            assert reconciliation[column]["disagreements"] == [], (
                f"{column} disagreed across the two stores: "
                f"{reconciliation[column]['disagreements']}"
            )
        # The ledger's missing tip-off is named, not quietly dropped or reduced to
        # a count: which game lost its instant is the diagnosable part.
        assert reconciliation["tipoff_utc"]["absent_in_participation_ledger"] == ["0022500259"]
        assert reconciliation["tipoff_utc"]["compared"] == 2

    def test_the_receipt_survives_a_round_trip_through_the_generator_seam(
        self, ledger: Path, sweep: Path, tmp_path: Path
    ) -> None:
        """``build_receipt`` is what the manifest embeds, so pin it as JSON."""
        out = tmp_path / "merged.db"
        alignment, copied = merge_injury_reports(participation_db=ledger, report_db=sweep, out=out)

        rebuilt = build_receipt(alignment, copied, out)

        assert json.loads(json.dumps(rebuilt)) == rebuilt, "the receipt is not JSON-safe"
        # Two different version fields, deliberately: the receipt's own schema
        # version, and the alembic version both stores were required to share.
        assert rebuilt["schema_version_of_both_stores"] == VERSION
        assert isinstance(rebuilt["schema_version"], int)


class TestTheIdentityAnchorsAreCheckedBeforeAnyCopy:
    def test_every_declared_anchor_is_actually_compared(self, ledger: Path, sweep: Path) -> None:
        with read_only(ledger) as left, read_only(sweep) as right:
            alignment = check_alignment(
                left, right, participation_db=str(ledger), report_db=str(sweep)
            )

        for table in IDENTITY_ANCHORS:
            assert table in alignment.surrogate_maps_agree
            assert alignment.surrogate_counts[table] > 0, (
                f"{table} was declared an identity anchor but zero rows were compared"
            )
        assert "players" in alignment.surrogate_maps_agree, (
            "injury_report_entries.player_id is a surrogate too, so players must be "
            "checked even though it is anchored on player_external_ids rather than "
            "on a column of its own"
        )


def test_the_module_declares_that_it_opens_stores_outside_the_census() -> None:
    """Refusing to be invisible, since the census scan cannot see this module.

    ``test_store_creating_readers.py`` inventories store-opening sites by
    matching a literal settings-factory call. This module takes explicit paths
    and uses :func:`sqlite3.connect`, so it is genuinely absent from that
    register. Widening the scan would reclassify verdicts the audit lane owns
    and is filed separately; this constant is the cheap half, and this test is
    what stops it being deleted as redundant prose.
    """
    assert "sqlite3.connect" in OPENS_STORES_OUTSIDE_THE_CENSUS
    assert "test_store_creating_readers" in OPENS_STORES_OUTSIDE_THE_CENSUS
    assert len(OPENS_STORES_OUTSIDE_THE_CENSUS) > 200


def test_the_granted_allowlist_reason_is_the_one_actually_in_the_rule() -> None:
    """The reason at the site and the reason in the allowlist must not drift.

    Renamed from ``..._survives_until_the_rule_exists``. The rule was not on
    ``main`` when this module landed, so the coordinator's granted reason was
    parked here at the site; #90 landed the rule, it fired on this module on the
    next rebase exactly as its message promised, and the entry now exists. **A
    test whose name asserts the rule does not exist yet is itself a decayed
    check** — which is precisely the failure #90 was written up for.

    So it now does the job the wait made impossible: bind the two copies
    together. The allowlist lives in ``test_store_creating_readers.py`` and the
    explanation lives beside the code it explains, which is right for a reader
    of either — but two copies of one justification is how a stale exemption
    outlives its cause.
    """
    reason = STORE_RULE_ALLOWLIST_REASON

    assert "declared purpose" in reason
    assert "mode=ro" in reason
    # The load-bearing asymmetry: inputs are read-only, the output cannot be.
    assert "cannot create an absent file" in reason
    assert "Adjudicated" in reason, "an exemption must record that it was granted, not assumed"

    census = (Path(__file__).resolve().parent / "test_store_creating_readers.py").read_text(
        encoding="utf-8"
    )
    assert "ingest/injury_report/merge_stores.py" in census, (
        "this module opens stores by a spelling the literal-string census cannot see. "
        "It must be recorded in the AST rule's allowlist rather than invisible to it."
    )
    for claim in ("declared purpose", "mode=ro", "adjudicated", "2026-08-24"):
        assert claim in census.lower() or claim in census, (
            f"the allowlist entry has dropped {claim!r} while the reason kept at the "
            f"site still carries it, so the two justifications have drifted apart"
        )


def test_the_output_connect_is_the_only_one_that_can_create_a_store(tmp_path: Path) -> None:
    """Drive the asymmetry the allowlist reason rests on, rather than asserting it.

    The reason claims the input connects cannot create a store and only the
    output connect can. That is a claim about behaviour, and behaviour claims in
    prose are how this repository has repeatedly been wrong.

    Note what this test does *not* prove: it passes with ``mode=ro`` removed,
    because :func:`read_only`'s explicit ``is_file`` check refuses first. That
    was verified by probe, not assumed. ``mode=ro`` is covered separately by
    :func:`test_read_only_actually_opens_read_only`, and the two are kept apart
    so neither can be mistaken for evidence of the other.
    """
    missing = tmp_path / "definitely-absent.db"
    assert not missing.exists()

    with (
        pytest.raises((sqlite3.OperationalError, StoreMergeRefused, FileNotFoundError)),
        read_only(missing),
    ):
        pass

    assert not missing.exists(), (
        "read_only() created a store for an absent path, so the allowlist reason's "
        "claim that only the output connect can create one is false"
    )


def test_read_only_actually_opens_read_only(tmp_path: Path) -> None:
    """The one test that fails if ``mode=ro`` is dropped.

    Written because the absent-path test above does *not* discriminate it: the
    explicit existence check refuses first, so removing ``mode=ro`` leaves that
    test green. A guard whose removal breaks no test is a guard that will be
    removed by someone tidying up, and the allowlist reason granted to this
    module names ``mode=ro`` explicitly — so it needs to be true, and needs to
    stay true, for reasons a reader can check.

    Driving a *write* is the discriminating probe, because that is the half the
    existence check cannot cover: this module must never mutate an input store.
    """
    store = tmp_path / "real.db"
    with closing(sqlite3.connect(store)) as setup:
        setup.executescript(SCHEMA)
        setup.execute("INSERT INTO nba_teams (id, nba_team_id) VALUES (1, '1610612737')")
        setup.commit()

    with read_only(store) as connection:
        # Reading is fine.
        assert connection.execute("SELECT COUNT(*) FROM nba_teams").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match=r"readonly|read-only"):
            connection.execute("INSERT INTO nba_teams (id, nba_team_id) VALUES (2, '1610612738')")

    # And the refused write left nothing behind.
    with closing(sqlite3.connect(store)) as after:
        assert after.execute("SELECT COUNT(*) FROM nba_teams").fetchone()[0] == 1


def test_the_declaration_does_not_itself_trip_the_census_scan() -> None:
    """Disclosing must not forge an entry in the register being disclosed against.

    Written in full, the settings-factory call name is matched by the census's
    literal-string scan, which put this module into ``ENGINE_CALL_SITES`` as a
    site that opens stores through settings -- something it does not do. That is
    a false entry in an audit register, which is worse than the silence it was
    meant to fix. Driven: this reproduces the scan against the real file.
    """
    module = Path(__file__).resolve().parents[1] / "src" / "hoops_gm" / "ingest"
    source = (module / "injury_report" / "merge_stores.py").read_text(encoding="utf-8")

    matched = [
        line for line in source.splitlines() if "Database.from_settings(" in line.split("#", 1)[0]
    ]

    assert not matched, (
        "merge_stores.py now matches the store-creating-reader census scan, which "
        f"will classify it as a settings-factory call site it is not: {matched}"
    )
