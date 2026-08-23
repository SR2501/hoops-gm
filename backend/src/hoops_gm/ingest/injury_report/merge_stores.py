"""Assemble one store holding **both** halves of the injury-conversion cohort.

    python -m hoops_gm.ingest.injury_report.merge_stores \
        --participation-db  C:/Users/.../hoops-gm-data/hoops_gm.db \
        --report-db         C:/Users/.../hoops-gm-data/throwaway-report-sweep.db \
        --out               C:/Users/.../hoops-gm-data/cohort-merged.db

## Why this module has to exist

:mod:`hoops_gm.ingest.injury_report.cohort_evidence` reads **one** session. It
joins injury-report observations to ``player_participation`` inside that
session, so it presumes a single store holding both. No such store exists.
Driven 2026-08-23, read-only, against the two real stores:

===========================  =============  =====================
table                        durable ledger  injury-report sweep
===========================  =============  =====================
``player_participation``            43,037                      0
``injury_report_entries``                0                 69,922
===========================  =============  =====================

Run the generator against the **sweep** and every observation resolves, while
``participation_join`` reports ``participation_rows_in_scope: 0`` — an honest,
reproducible, wrong zero that exits 0. Run it against the **ledger** and there
are no observations to join at all. Neither failure raises. That is the false
zero this repository has already been bitten by once, and it is why the
assembly step is a committed, tested tool rather than an operator's one-off:
a manifest whose reproduction recipe cannot be re-run is the PR #30 defect that
:mod:`cohort_evidence` was written to prevent.

## Why the merge runs *into the ledger*, never the other way

The direction is not arbitrary and is the whole safety argument.

* ``nba_games.tipoff_utc`` in the ledger is **BoxScoreSummaryV3**-sourced. The
  same column in the sweep is **ScheduleLeagueV2**-sourced. Keeping the
  ledger's rows preserves the two-endpoint reconciliation that comparing the
  two stores restores, and which reading the sweep's own column destroys.
* The sweep never ingested scores: ``home_score`` and ``away_score`` are NULL
  on all 1,230 of its games, and populated on all 1,230 of the ledger's. The
  ledger's game rows are a strict information superset apart from three
  tip-offs, below.
* Three games (``0022500259``, ``0022500260``, ``0022500261``) carry a NULL
  tip-off in the ledger and a value in the sweep. Those are **deliberately not
  backfilled**. Copying them across would import ScheduleLeagueV2 instants into
  a BoxScoreSummaryV3-sourced column — precisely the conflation the tip-off
  reconciliation exists to detect — so they stay absent and the cohort excludes
  them as missing-tip-off. An excluded game is a recorded gap; a silently
  re-sourced instant is a lie with a plausible value.

## What is copied, and what deliberately is not

Only :data:`MERGED_TABLES`. ``team_schedule`` and ``refresh_runs`` are present
in the sweep and are **not** copied: the generator reads neither, and a
``refresh_runs`` row asserts that a schedule refresh happened in the store that
holds it. Copying that lineage into a store where it never ran would
manufacture a provenance claim to save nothing.

## The join hazard this refuses to repeat

``injury_report_entries.game_id`` and ``.player_id`` are **local surrogate
integers**, not source-stable ids. An independent reviewer has already joined a
local surrogate to a source-stable string across these two stores and got zero
rows and no error. So a surrogate copied between stores is only meaningful if
both stores agree on what each surrogate *means*, and :func:`check_alignment`
proves that on source-stable keys before a single row moves — then the copy
runs with ``PRAGMA foreign_keys=ON`` so a surrogate that resolves to nothing
aborts the merge rather than landing as referential garbage.

## This module opens stores, and the census cannot see it

``backend/tests/test_store_creating_readers.py`` inventories store-opening call
sites by matching a literal ``Database.from_settings`` call. This module takes
two explicit paths rather than settings, so it opens its stores through
:func:`sqlite3.connect` and **does not appear in that census**. That is stated
here, asserted by :data:`OPENS_STORES_OUTSIDE_THE_CENSUS` and pinned by a test,
rather than left for the scan to miss. Widening the scan itself would
reclassify verdicts owned by the audit lane and is filed separately; refusing
to be invisible costs nothing and is available now.

Note that this prose deliberately does **not** spell that call with its opening
parenthesis. Written in full it is itself matched by the scan, which put this
module in the census as a site that opens stores through settings — something it
does not do. A disclosure that produces a false entry in the register it is
disclosing against is worse than the silence it was meant to fix, so the
disclosure lives in a constant and a test instead.

The exposure the census exists to catch is closed here directly instead:
``mode=ro`` **refuses** an absent store rather than creating one, and every
count this module prints names the store it came from.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

#: Written beside the merged store. The generator embeds it, so the fact that
#: the cohort's tip-off instants and its injury reports came from **different**
#: stores becomes a persisted, checkable record rather than an assertion.
#:
#: This exists because of a specific, named hazard.
#: ``cohort_evidence``'s tip-off check compares ``nba_games.tipoff_utc``
#: (BoxScoreSummaryV3) against ScheduleLeagueV2, and its own ``method`` string
#: already admits the weakness: *nothing records the provenance of a persisted
#: instant*. Run the generator against the sweep store, whose ``tipoff_utc`` is
#: itself ScheduleLeagueV2-sourced, and that check compares one endpoint with
#: itself while reporting ``agreed: true, witnessed: true``. A vacuous check is
#: byte-identical to a passing one, so no reader could tell.
#:
#: The receipt is the missing provenance: it names which store each half came
#: from and carries the cross-store agreement that was actually measured.
RECEIPT_SUFFIX: Final = ".merge-receipt.json"

#: Tables copied from the report store into the participation ledger copy.
#: Deliberately minimal — see the module docstring on ``team_schedule`` and
#: ``refresh_runs``.
MERGED_TABLES: Final[tuple[str, ...]] = ("injury_report_entries",)

#: Tables whose surrogate primary keys must mean the same thing in both stores
#: before any surrogate-bearing row may be copied, and the source-stable column
#: each surrogate is checked against.
IDENTITY_ANCHORS: Final[dict[str, str]] = {
    "nba_games": "nba_game_id",
    "nba_teams": "nba_team_id",
}

#: Columns compared between the two stores' ``nba_games`` rows, keyed on the
#: source-stable ``nba_game_id`` rather than on the surrogate. A disagreement
#: here means the two stores describe different games under the same id, and no
#: merge may proceed over it.
RECONCILED_GAME_COLUMNS: Final[tuple[str, ...]] = ("tipoff_utc", "game_date")

#: Stated because the scan in ``test_store_creating_readers.py`` cannot find
#: this module, and an exposure with no written record decays into an unknown
#: one. Pinned by ``test_merge_stores.py``.
OPENS_STORES_OUTSIDE_THE_CENSUS: Final = (
    "Opens two SQLite stores via sqlite3.connect(mode=ro) and one via "
    "sqlite3.connect on the output path, none of them through the settings-based "
    "Database factory. The literal-string call census in "
    "test_store_creating_readers.py cannot see any of them; the AST import rule "
    "in the same file can, and this module is recorded in its allowlist rather "
    "than hidden from it. Read-only inputs cannot be created by opening them; "
    "the output is refused if it already exists."
)

#: The reason text for this module's entry in the AST-based store-opening rule.
#: **Adjudicated by the coordinator on 2026-08-24, requested rather than
#: discovered** — routed up for a decision instead of being added quietly.
#:
#: The rule landed on ``main`` in #90 and fired on this module on the very next
#: rebase, naming it exactly as its failure message promised. The entry now
#: exists in ``SANCTIONED_STORE_OPENERS``; this constant is the same reason kept
#: at the site, because the allowlist is in the test file and a reader of *this*
#: module should not have to go looking to learn that it is sanctioned and why.
#:
#: The ruling accepted a distinction this module forced:
#:
#:     "creates a store deliberately, as its declared purpose" is a different
#:     category from "opens a store to read it and might create one by accident."
#:
#: The rule's hazard is the second category — a reader that silently conjures an
#: empty store and then answers every question with a reproducible, meaningless
#: zero. ``mode=ro`` is the demonstrated remedy for that, and both *inputs* here
#: use it. But the *output* connect cannot be converted, because a read-only
#: writer is a contradiction: writing the merged store **is** this module's job.
#: Refusing it would make the rule mistake its own hazard and stamp a verdict on
#: a site the question does not fit, which devalues every other verdict in the
#: register.
#:
#: This is therefore a **legitimate entry, not a widening of the rule**.
STORE_RULE_ALLOWLIST_REASON: Final = (
    "merge_stores.py creates a store as its declared purpose: it writes the merged "
    "participation+report store that a single-Session manifest generator requires. "
    "Its two input connects are sqlite3.connect(mode=ro), which cannot create an "
    "absent file; only the output connect can, and that is the point of the module "
    "rather than an accident of it. The output path is refused if it already "
    "exists. Adjudicated by the coordinator 2026-08-24."
)


class StoreMergeRefused(RuntimeError):
    """The two stores may not be merged, with the reason a reader can act on."""


@dataclass(frozen=True)
class StoreAlignment:
    """Evidence that two stores agree about identity, gathered before any copy.

    Every field is a count or an explicit list rather than a bare bool, because
    "agreed" over an empty comparison is the failure mode this whole repository
    keeps rediscovering: views that all found nothing agree perfectly and
    witness nothing. :attr:`compared` is therefore reported beside
    :attr:`disagreements`, and :meth:`refusal` treats a zero comparison as a
    refusal in its own right.
    """

    participation_db: str
    report_db: str
    schema_version: str
    surrogate_maps_agree: dict[str, bool]
    surrogate_counts: dict[str, int]
    compared: dict[str, int]
    disagreements: dict[str, list[str]] = field(default_factory=dict)
    absent_in_participation: dict[str, list[str]] = field(default_factory=dict)
    absent_in_report: dict[str, list[str]] = field(default_factory=dict)

    def refusal(self) -> str | None:
        """Why these stores may not be merged, or ``None`` if they may."""
        misaligned = sorted(t for t, ok in self.surrogate_maps_agree.items() if not ok)
        if misaligned:
            return (
                f"surrogate primary keys mean different things in the two stores for "
                f"{misaligned}. Copying a surrogate-bearing row between them would "
                f"silently re-point it at a different entity."
            )
        for column, differing in sorted(self.disagreements.items()):
            if differing:
                return (
                    f"the two stores disagree about nba_games.{column} for "
                    f"{len(differing)} game(s): {differing[:5]}. They describe different "
                    f"games under one id, so no merge may proceed over it."
                )
        for column, count in sorted(self.compared.items()):
            if count == 0:
                return (
                    f"zero games were actually compared on nba_games.{column}. Columns "
                    f"that were never compared agree perfectly and witness nothing."
                )
        return None


@contextmanager
def read_only(path: str | Path) -> Iterator[sqlite3.Connection]:
    """Open a store read-only, refusing rather than creating an absent file.

    Two independent guards, and it is worth being precise about which does
    what, because an earlier version of this docstring claimed ``mode=ro`` was
    the only one *while the explicit check sat three lines below it*:

    1. The :meth:`~pathlib.Path.is_file` check below is what actually refuses an
       absent path, and it is what produces the actionable
       :class:`StoreMergeRefused` message rather than a bare
       ``OperationalError``.
    2. ``mode=ro`` is defence in depth, and not redundant. It closes the
       time-of-check/time-of-use window between that check and this connect, and
       it makes *writes* fail — this module must never mutate an input store,
       and only ``mode=ro`` enforces that. Demonstrated rather than assumed:
       a plain connect to a missing path creates the file, a ``mode=ro`` connect
       raises and creates nothing.

    A store invented here would answer every later question with a reproducible,
    meaningless zero, which is the failure this whole module exists to avoid.
    """
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise StoreMergeRefused(
            f"no database file at {resolved}\n"
            f"  Refusing to create one: an empty store invented here would answer "
            f"with a reproducible and meaningless zero."
        )
    uri = f"file:{resolved.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        yield connection


def _schema_version(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    return "" if row is None else str(row[0])


def _surrogate_map(connection: sqlite3.Connection, table: str, stable: str) -> dict[int, str]:
    return {
        int(pk): str(value) for pk, value in connection.execute(f"SELECT id, {stable} FROM {table}")
    }


def _player_surrogate_map(connection: sqlite3.Connection) -> dict[int, str]:
    """Players have no stable column of their own; the NBA external id is it."""
    return {
        int(pk): str(value)
        for pk, value in connection.execute(
            "SELECT p.id, e.external_id FROM players p "
            "JOIN player_external_ids e ON e.player_id = p.id AND e.source = 'nba'"
        )
    }


def check_alignment(
    participation: sqlite3.Connection,
    reports: sqlite3.Connection,
    *,
    participation_db: str,
    report_db: str,
) -> StoreAlignment:
    """Prove the two stores mean the same thing by every surrogate, before copying.

    Separated from :func:`merge_injury_reports` so the refusal is testable
    without materialising an output store. A guard reachable only through a
    side effect is a guard nobody exercises.
    """
    participation_version = _schema_version(participation)
    report_version = _schema_version(reports)
    if participation_version != report_version:
        raise StoreMergeRefused(
            f"schema versions differ: {participation_db} is at {participation_version!r}, "
            f"{report_db} is at {report_version!r}. Merging across a migration would copy "
            f"rows into columns that may not mean what they did when written."
        )

    agree: dict[str, bool] = {}
    counts: dict[str, int] = {}
    for table, stable in IDENTITY_ANCHORS.items():
        left = _surrogate_map(participation, table, stable)
        right = _surrogate_map(reports, table, stable)
        agree[table] = left == right
        counts[table] = len(left)
    left_players = _player_surrogate_map(participation)
    right_players = _player_surrogate_map(reports)
    agree["players"] = left_players == right_players
    counts["players"] = len(left_players)

    disagreements: dict[str, list[str]] = {}
    compared: dict[str, int] = {}
    absent_left: dict[str, list[str]] = {}
    absent_right: dict[str, list[str]] = {}
    columns = ", ".join(RECONCILED_GAME_COLUMNS)
    query = f"SELECT nba_game_id, {columns} FROM nba_games"
    left_games = {str(r[0]): r[1:] for r in participation.execute(query)}
    right_games = {str(r[0]): r[1:] for r in reports.execute(query)}
    shared = sorted(set(left_games) & set(right_games))
    for index, column in enumerate(RECONCILED_GAME_COLUMNS):
        differing: list[str] = []
        missing_left: list[str] = []
        missing_right: list[str] = []
        seen = 0
        for game_id in shared:
            left_value = left_games[game_id][index]
            right_value = right_games[game_id][index]
            # Absent on either side is *not* a disagreement. Conflating the two
            # is how "3 games differ" gets reported for three games nobody
            # could compare, and the distinction has to survive into the
            # published evidence.
            if left_value is None:
                missing_left.append(game_id)
                continue
            if right_value is None:
                missing_right.append(game_id)
                continue
            seen += 1
            if left_value != right_value:
                differing.append(game_id)
        disagreements[column] = differing
        compared[column] = seen
        absent_left[column] = missing_left
        absent_right[column] = missing_right

    return StoreAlignment(
        participation_db=participation_db,
        report_db=report_db,
        schema_version=participation_version,
        surrogate_maps_agree=agree,
        surrogate_counts=counts,
        compared=compared,
        disagreements=disagreements,
        absent_in_participation=absent_left,
        absent_in_report=absent_right,
    )


def _column_names(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]


def _copy_table(destination: sqlite3.Connection, source: sqlite3.Connection, table: str) -> int:
    """Copy one table by explicit shared column name, never by position.

    ``SELECT *`` would silently mis-map if a migration reordered columns, and
    the two stores are only *asserted* to be at the same schema version — an
    assertion about a version string, not about column order.
    """
    into = _column_names(destination, table)
    out_of = _column_names(source, table)
    missing = [c for c in into if c not in out_of]
    if missing:
        raise StoreMergeRefused(
            f"{table} in the report store is missing column(s) {missing} that the "
            f"destination requires; the two schemas are not compatible despite "
            f"claiming the same version."
        )
    existing = destination.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if existing:
        raise StoreMergeRefused(
            f"{table} already holds {existing} row(s) in the destination. Refusing to "
            f"merge into a non-empty table: the result would be indistinguishable from "
            f"a clean merge but could double-count or collide on the natural key."
        )
    quoted = ", ".join(f'"{c}"' for c in into)
    placeholders = ", ".join("?" for _ in into)
    rows = source.execute(f"SELECT {quoted} FROM {table}")
    copied = 0
    while batch := rows.fetchmany(1000):
        destination.executemany(
            f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})',
            batch,
        )
        copied += len(batch)
    return copied


def _redacted(path: str | Path) -> str:
    """A store's filename, never its directory.

    The receipt is embedded verbatim into a manifest that is **committed**, and
    the operational stores live under the operator's home directory. Writing the
    absolute path published the account name into the repository three times
    over -- caught by a privacy pass over the generated artifact, not by any
    test, because no schema is violated by a correct path.

    The filename is kept because it distinguishes the ledger from the sweep at a
    glance. Identity is carried by the sha256 beside it, which is what a reader
    would actually check, and which the directory never contributed to.
    """
    return Path(path).name


def store_sha256(path: Path) -> str:
    """Identity of a store file, so a receipt names a specific store's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def build_receipt(alignment: StoreAlignment, copied: dict[str, int], out: Path) -> dict[str, Any]:
    """The provenance record a manifest reader needs to rule out a vacuous check."""
    return {
        "kind": "injury_report_store_merge_receipt",
        "schema_version": 1,
        "merged_store": {
            "store": _redacted(out),
            "sha256": store_sha256(out),
        },
        "sources": {
            "participation_ledger": {
                "store": _redacted(alignment.participation_db),
                "sha256": store_sha256(Path(alignment.participation_db)),
                "supplies": [
                    "player_participation",
                    "nba_games.tipoff_utc (BoxScoreSummaryV3-sourced)",
                ],
            },
            "injury_report_sweep": {
                "store": _redacted(alignment.report_db),
                "sha256": store_sha256(Path(alignment.report_db)),
                "supplies": list(MERGED_TABLES),
            },
        },
        "schema_version_of_both_stores": alignment.schema_version,
        "surrogate_identity_agreement": {
            "agree": dict(sorted(alignment.surrogate_maps_agree.items())),
            "rows": dict(sorted(alignment.surrogate_counts.items())),
            "checked_on": "source-stable keys, never on the surrogate itself",
        },
        "cross_store_nba_games_reconciliation": {
            column: {
                "compared": alignment.compared.get(column, 0),
                "disagreements": alignment.disagreements.get(column, []),
                "absent_in_participation_ledger": alignment.absent_in_participation.get(column, []),
                "absent_in_injury_report_sweep": alignment.absent_in_report.get(column, []),
            }
            for column in RECONCILED_GAME_COLUMNS
        },
        "tipoff_provenance_note": (
            "The merged store's nba_games rows are the participation ledger's, whose "
            "tipoff_utc is BoxScoreSummaryV3-sourced. The injury-report sweep's own "
            "ScheduleLeagueV2-sourced tipoff_utc was NOT copied, and the three games it "
            "holds an instant for that the ledger does not were deliberately left absent "
            "rather than backfilled across endpoints. A cohort generated from this store "
            "therefore compares BoxScoreSummaryV3 against ScheduleLeagueV2 as two "
            "genuinely distinct endpoints, which a cohort generated from the sweep alone "
            "would not -- and could not report."
        ),
        "copied_rows": dict(sorted(copied.items())),
    }


def receipt_path(out: Path) -> Path:
    return out.with_name(out.name + RECEIPT_SUFFIX)


def merge_injury_reports(
    *,
    participation_db: str | Path,
    report_db: str | Path,
    out: str | Path,
    overwrite: bool = False,
) -> tuple[StoreAlignment, dict[str, int]]:
    """Materialise a merged store, or refuse with a reason.

    Returns the alignment evidence and the per-table copied counts, so a caller
    can publish both rather than merely trusting that the merge happened.
    """
    destination = Path(out).resolve()
    if destination.exists() and not overwrite:
        raise StoreMergeRefused(
            f"{destination} already exists. Refusing to overwrite a store: pass "
            f"--overwrite if replacing it is what you meant."
        )

    source_ledger = Path(participation_db).resolve()
    with read_only(source_ledger) as ledger, read_only(report_db) as reports:
        alignment = check_alignment(
            ledger,
            reports,
            participation_db=str(source_ledger),
            report_db=str(Path(report_db).resolve()),
        )
        refusal = alignment.refusal()
        if refusal is not None:
            raise StoreMergeRefused(refusal)

        destination.parent.mkdir(parents=True, exist_ok=True)
        # Copy the ledger file wholesale rather than rebuilding a schema: the
        # merged store must be the ledger in every respect except the added
        # reports, and re-deriving it from metadata would silently drop
        # anything the ORM does not model.
        shutil.copy2(source_ledger, destination)

        copied: dict[str, int] = {}
        with closing(sqlite3.connect(destination)) as merged:
            # Enforced during the copy, not merely declared: a surrogate that
            # resolves to nothing in the destination aborts the merge here
            # rather than landing as referential garbage that reads fine.
            merged.execute("PRAGMA foreign_keys=ON")
            try:
                for table in MERGED_TABLES:
                    copied[table] = _copy_table(merged, reports, table)
            except Exception:
                merged.rollback()
                merged.close()
                destination.unlink(missing_ok=True)
                raise
            merged.commit()

    receipt = build_receipt(alignment, copied, destination)
    receipt_path(destination).write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return alignment, copied


def render(alignment: StoreAlignment, copied: dict[str, int], out: Path) -> str:
    """Every count named beside the store it came from.

    That pairing, not the read-only open, is what actually closes the false
    zero: a number with no store attached cannot be attributed, and this
    repository has already spent a unit of work discovering which store a bare
    ``0`` belonged to.
    """
    lines = [
        f"participation ledger : {alignment.participation_db}",
        f"report sweep         : {alignment.report_db}",
        f"merged store         : {out}",
        f"schema version       : {alignment.schema_version}",
        "surrogate identity agreement (source-stable keys):",
    ]
    for table in sorted(alignment.surrogate_maps_agree):
        lines.append(
            f"  {table:<22} agree={alignment.surrogate_maps_agree[table]} "
            f"rows={alignment.surrogate_counts.get(table, 0)}"
        )
    lines.append("nba_games cross-store reconciliation:")
    for column in RECONCILED_GAME_COLUMNS:
        lines.append(
            f"  {column:<22} compared={alignment.compared.get(column, 0)} "
            f"disagreements={len(alignment.disagreements.get(column, []))} "
            f"absent_in_ledger={len(alignment.absent_in_participation.get(column, []))} "
            f"absent_in_sweep={len(alignment.absent_in_report.get(column, []))}"
        )
    lines.append("copied:")
    for table in sorted(copied):
        lines.append(f"  {table:<22} {copied[table]} row(s)")
    lines.append(f"receipt              : {receipt_path(out)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - operator tool
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--participation-db", required=True, help="the durable ledger")
    parser.add_argument("--report-db", required=True, help="the injury-report sweep store")
    parser.add_argument("--out", type=Path, required=True, help="merged store to create")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing output store (default: refuse)",
    )
    args = parser.parse_args(argv)

    try:
        alignment, copied = merge_injury_reports(
            participation_db=args.participation_db,
            report_db=args.report_db,
            out=args.out,
            overwrite=args.overwrite,
        )
    except StoreMergeRefused as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(render(alignment, copied, args.out.resolve()))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
