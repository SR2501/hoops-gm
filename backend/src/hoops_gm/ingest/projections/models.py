"""Typed records produced by the projection CSV parser.

Plain frozen dataclasses, mirroring ``ingest/nba/models.py``: nothing here is a
SQLAlchemy model, so the parser stays pure and its contract tests stay
offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ProjectionParseResult",
    "ProjectionSourceRow",
    "RowIssue",
    "build_raw_row",
]


@dataclass(frozen=True)
class ProjectionSourceRow:
    """One player's parsed and normalised row from a projection CSV.

    Every numeric field is a **per-game rate**, already divided by the row's
    games-played figure when the source published a season total (ADR-002).
    ``assumed_games_played`` is carried alongside for provenance, never
    folded back into a rate — the importer writes it to
    ``source_games_played_assumptions``, a separate table, precisely so nothing
    downstream can reach it while reading a rate.
    """

    row_number: int
    player_name: str
    #: Stable identifier supplied by the projection vendor, when its contract
    #: exposes one. Used as the source crosswalk key instead of a name-derived
    #: surrogate; it never replaces the NBA id as the canonical anchor.
    source_player_id: str | None = None
    team: str | None = None
    position: str | None = None

    #: The games-played figure this row's per-game rates were computed
    #: against, when the source stated one. Not an expected-games number —
    #: that is the availability model's job, a later phase.
    assumed_games_played: float | None = None
    #: The source's own text for the games-played figure, kept verbatim.
    assumed_games_played_raw: str | None = None

    minutes_per_game: float | None = None
    points_per_game: float | None = None
    offensive_rebounds_per_game: float | None = None
    defensive_rebounds_per_game: float | None = None
    rebounds_per_game: float | None = None
    assists_per_game: float | None = None
    steals_per_game: float | None = None
    blocks_per_game: float | None = None
    turnovers_per_game: float | None = None
    personal_fouls_per_game: float | None = None
    field_goals_made_per_game: float | None = None
    field_goals_attempted_per_game: float | None = None
    three_pointers_made_per_game: float | None = None
    three_pointers_attempted_per_game: float | None = None
    free_throws_made_per_game: float | None = None
    free_throws_attempted_per_game: float | None = None

    #: The row exactly as the CSV gave it, keyed by the *raw* header text.
    #: Preserved so a disputed number can be traced back to what the source
    #: actually published, before any column-mapping or per-game conversion.
    raw_row: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RowIssue:
    """One thing the parser found wrong (or merely notable) about a row.

    ``fatal`` rows are excluded from :attr:`ProjectionParseResult.rows`
    entirely — an unparsable number or a missing name is not a per-game rate
    that is merely uncertain, it is not a rate at all, and importing it would
    be inventing data. A non-fatal issue is a warning: the row is still
    imported, but something about it deserves a human's attention (a
    percentage-only source that could not be volume-weighted, a makes/
    attempts pair that does not reconcile with a published percentage).
    """

    row_number: int
    field: str | None
    message: str
    fatal: bool


@dataclass
class ProjectionParseResult:
    """Everything one CSV parse produced, including what it refused to import."""

    #: Rows that passed validation, in file order.
    rows: list[ProjectionSourceRow] = field(default_factory=list)
    issues: list[RowIssue] = field(default_factory=list)
    #: The header each canonical field actually resolved to, for a source
    #: whose header spelling was not the profile's first alias. Useful when a
    #: contract test or a human wants to know *why* a column was read the way
    #: it was.
    resolved_headers: dict[str, str] = field(default_factory=dict)
    #: Higher-layer aggregate headers present in the file and deliberately
    #: ignored under ADR-008. Values remain only in the transient raw row; no
    #: projection-layer model persists them.
    ignored_terminal_headers: list[str] = field(default_factory=list)
    #: Profile-declared source columns intentionally outside the projection
    #: contract (for example comments and non-9-cat counters).
    ignored_source_headers: list[str] = field(default_factory=list)
    #: Percentage observations that cannot themselves enter a projection.
    #: Kept separate from ``resolved_headers`` because they do not resolve to
    #: a stored canonical rate; lineage records their explicit exclusion.
    resolved_percentage_headers: dict[str, str] = field(default_factory=dict)
    #: Every data row the file contained, including rejected ones.
    total_rows: int = 0

    @property
    def fatal_issues(self) -> list[RowIssue]:
        return [issue for issue in self.issues if issue.fatal]

    @property
    def warnings(self) -> list[RowIssue]:
        return [issue for issue in self.issues if not issue.fatal]

    @property
    def rejected_count(self) -> int:
        """Distinct rows carrying at least one fatal issue.

        Not ``len(fatal_issues)``: one row can fail validation for two
        reasons (an unparsable number *and* an out-of-range games-played
        figure), and counting issues rather than rows would overstate how
        many rows were actually lost.
        """
        return len({issue.row_number for issue in self.fatal_issues})


def build_raw_row(fieldnames: list[str], values: dict[str, Any]) -> dict[str, str]:
    """Coerce a ``csv.DictReader`` row to transient parse evidence.

    ``DictReader`` maps missing trailing columns to ``None``. Extra columns are
    structurally invalid and must not be silently discarded: doing so can make
    shifted values look like valid production, so this helper rejects the
    ``None`` rest key before coercion. The row is deliberately not persisted on
    ``Projection``: terminal Rank/AAV/composite fields may be present in the
    same CSV and accepted ADR-008 forbids attaching them to the projection
    layer. Durable raw evidence belongs behind
    ``ProjectionImport.raw_payload_ref``.
    """
    if None in values:
        raise ValueError("row has more fields than the CSV header")
    return {name: "" if values.get(name) is None else str(values.get(name)) for name in fieldnames}
