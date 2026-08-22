"""Typed records produced by the published-auction-value parser.

Plain frozen dataclasses, mirroring ``ingest/projections/models.py``: nothing
here is a SQLAlchemy model, so the parser stays pure and its contract tests
stay offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from hoops_gm.db.models.enums import AuctionValueKind

__all__ = [
    "AuctionValueParseResult",
    "AuctionValueRowIssue",
    "PublishedValueRow",
]


@dataclass(frozen=True)
class PublishedValueRow:
    """One dollar figure, of one kind, for one player, as one source published it.

    Note the grain: **one CSV row can produce several of these.** Yahoo's
    draft-analysis table prints a projected auction value and an observed
    average auction value side by side, and they are different claims about
    the same player. Collapsing them into one record — or deciding the kind
    from the source's name — would mix a competitor's model output with market
    observation, which is the exact confusion this whole layer exists to
    prevent.

    ``value_raw`` keeps the source's own text. ``$90`` and ``90`` parse to the
    same :class:`~decimal.Decimal` and are different claims about what was
    published, and a units mistake is only visible if the original survives.
    """

    row_number: int
    player_name: str
    value_kind: AuctionValueKind
    #: Decimal, never float. This is money and it is compared.
    value_dollars: Decimal
    value_raw: str
    source_player_id: str | None = None
    team: str | None = None
    position: str | None = None


@dataclass(frozen=True)
class AuctionValueRowIssue:
    """One thing the parser found wrong about a row, or notable about it.

    ``fatal`` rows never reach :attr:`AuctionValueParseResult.rows`. An
    unparsable dollar figure is not an uncertain price, it is not a price at
    all, and importing a guess in its place would be inventing market
    evidence — which R37 names explicitly as the thing not to do.
    """

    row_number: int
    message: str
    fatal: bool = True
    column: str | None = None


@dataclass(frozen=True)
class AuctionValueParseResult:
    """Everything one parse of one file produced, including what it refused."""

    rows: tuple[PublishedValueRow, ...] = ()
    issues: tuple[AuctionValueRowIssue, ...] = ()
    #: Header text actually matched, keyed by what it was matched as. Evidence
    #: for the adapter contract test: it records what the file said, not what
    #: the profile hoped for.
    resolved_headers: dict[str, str] = field(default_factory=dict)
    #: Headers present in the file that the profile deliberately did not map.
    ignored_headers: tuple[str, ...] = ()
    #: Data rows read from the file, before any were rejected. Distinct from
    #: ``len(rows)``, which counts *values* and can exceed the row count when a
    #: profile maps more than one value column.
    total_rows: int = 0

    @property
    def fatal_issues(self) -> tuple[AuctionValueRowIssue, ...]:
        return tuple(issue for issue in self.issues if issue.fatal)

    @property
    def rejected_row_numbers(self) -> frozenset[int]:
        """Rows carrying at least one fatal issue.

        **Not the same as rows that produced nothing.** A profile mapping two
        value columns can have one of them unreadable and still yield a value
        from the other, so a row can appear here *and* in :attr:`rows`. Use
        :attr:`fully_rejected_row_numbers` for the accounting question "did this
        row contribute anything", and this one for "did anything go wrong here".
        """
        return frozenset(issue.row_number for issue in self.fatal_issues)

    @property
    def rows_yielding_values(self) -> frozenset[int]:
        """Row numbers that produced at least one value."""
        return frozenset(row.row_number for row in self.rows)

    @property
    def fully_rejected_row_numbers(self) -> frozenset[int]:
        """Rows that produced no value at all.

        This is the count that completes the row accounting: every data row
        either yields values or lands here, and the two partition
        :attr:`total_rows`. The row-grained/value-grained distinction is easy to
        lose because on a single-value-column profile the two properties are
        equal, which is exactly the fixture shape that hides the difference.
        """
        return self.rejected_row_numbers - self.rows_yielding_values
