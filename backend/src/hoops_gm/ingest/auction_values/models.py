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

    ``value_raw`` keeps the source's own text. ``$74`` and ``74`` parse to the
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
        return frozenset(issue.row_number for issue in self.fatal_issues)
