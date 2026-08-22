"""Parsing a published auction-value table against a profile.

Pure and offline: nothing here touches a database or a network. Identity
resolution — matching a parsed name against the canonical player crosswalk — is
a separate step in ``importer.py``.

Two things this module does that the projection parser does not need to.

**One input row can yield several output rows.** Yahoo prints an observed
average cost and a projected value side by side. The parser emits one
:class:`PublishedValueRow` per (row, value column), each carrying its own
:class:`AuctionValueKind`, because they are different claims and averaging them
would blend market observation into model output.

**Money is parsed as :class:`~decimal.Decimal`, and the source's own text is
kept.** ``$90`` and ``90`` produce the same number and are different claims
about what was published; if a source ever switches notation, the parsed
number alone would not show it.

Every fatal failure is scoped to its own row and value. One unreadable price
does not lose the rest of the file.
"""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal, InvalidOperation

from hoops_gm.ingest.auction_values.models import (
    AuctionValueParseResult,
    AuctionValueRowIssue,
    PublishedValueRow,
)
from hoops_gm.ingest.auction_values.profiles import (
    AuctionValueProfile,
    resolve_auction_header,
)

__all__ = ["AuctionValueProfileError", "parse_auction_value_csv"]

#: Nobody's auction value is a thousand dollars. This is a mis-mapped-column
#: guard (a rank or a fantasy-point total read as a price), not a claim about
#: any league's budget — a $260 league's top price is still well under this.
_MAX_PLAUSIBLE_DOLLARS = Decimal("1000")

#: Characters a published price may carry around the number itself. ``%`` is
#: deliberately absent: a percentage in a price column is a mis-mapped column,
#: not a price with decoration, and must be rejected rather than stripped.
_MONEY_STRIP = re.compile(r"[\s$,]")

#: Text a source uses to mean "no price", as opposed to a price of zero.
#: FantraxHQ publishes an explicit ``$0`` for unrostered players, which is a
#: real claim; an empty cell or a dash is the absence of a claim, and the two
#: must not collapse.
_MISSING_TOKENS = frozenset({"", "-", "--", "—", "n/a", "na", "null", "none"})


class AuctionValueProfileError(ValueError):
    """The file cannot be read under this profile in principle.

    Raised when the file has no header row, no player-name column, or none of
    the profile's value columns. A missing *optional* column (team, position,
    a second value column) is not this — sources differ and a profile is
    allowed to under-match. Missing the name or every price is different: there
    is then nothing to resolve, or nothing to import.
    """


def _parse_money(raw: str) -> Decimal | None:
    """Parse a published price, or ``None`` when the source stated no price.

    Rejects rather than coerces anything that is not plainly a decimal amount.
    A ``%`` sign, a range ("12-15"), or letters mean the column is not what the
    profile thinks it is, and guessing would manufacture market evidence.
    """
    text = raw.strip()
    if text.lower() in _MISSING_TOKENS:
        return None
    stripped = _MONEY_STRIP.sub("", text)
    if not stripped:
        return None
    if not re.fullmatch(r"-?\d+(\.\d+)?", stripped):
        raise ValueError(f"{raw!r} is not a plain dollar amount")
    try:
        value = Decimal(stripped)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the regex
        raise ValueError(f"{raw!r} is not a plain dollar amount") from exc
    if value < 0:
        raise ValueError(f"{raw!r} is a negative price")
    if value > _MAX_PLAUSIBLE_DOLLARS:
        raise ValueError(
            f"{raw!r} exceeds ${_MAX_PLAUSIBLE_DOLLARS}, which no auction budget reaches; "
            "the column is probably not a price"
        )
    return value


def parse_auction_value_csv(csv_text: str, profile: AuctionValueProfile) -> AuctionValueParseResult:
    """Parse ``csv_text`` under ``profile`` into published dollar values."""
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = list(reader.fieldnames or [])
    if not fieldnames:
        raise AuctionValueProfileError(
            f"{profile.display_name}: the file has no header row, so no column can be mapped"
        )

    name_header = resolve_auction_header(fieldnames, profile.name_aliases)
    if name_header is None:
        raise AuctionValueProfileError(
            f"{profile.display_name}: no player-name column among {fieldnames!r}; "
            f"expected one of {list(profile.name_aliases)!r}"
        )

    id_header = resolve_auction_header(fieldnames, profile.external_id_aliases)
    team_header = resolve_auction_header(fieldnames, profile.team_aliases)
    position_header = resolve_auction_header(fieldnames, profile.position_aliases)

    matched_value_columns = [
        (column, header)
        for column in profile.value_columns
        if (header := resolve_auction_header(fieldnames, column.aliases)) is not None
    ]
    if not matched_value_columns:
        wanted = sorted({alias for column in profile.value_columns for alias in column.aliases})
        raise AuctionValueProfileError(
            f"{profile.display_name}: no value column among {fieldnames!r}; "
            f"expected one of {wanted!r}"
        )

    resolved: dict[str, str] = {"player_name": name_header}
    if id_header:
        resolved["source_player_id"] = id_header
    if team_header:
        resolved["team"] = team_header
    if position_header:
        resolved["position"] = position_header
    for column, header in matched_value_columns:
        resolved[f"value:{column.kind.value}"] = header

    mapped = {name_header, id_header, team_header, position_header} | {
        header for _, header in matched_value_columns
    }
    ignored = tuple(header for header in fieldnames if header not in mapped)

    rows: list[PublishedValueRow] = []
    issues: list[AuctionValueRowIssue] = []
    total_rows = 0

    for row_number, raw_row in enumerate(reader, start=2):
        total_rows += 1
        player_name = (raw_row.get(name_header) or "").strip()
        if not player_name:
            issues.append(
                AuctionValueRowIssue(
                    row_number=row_number,
                    message="row has no player name, so it cannot be resolved to a player",
                    column=name_header,
                )
            )
            continue

        source_player_id = (raw_row.get(id_header) or "").strip() if id_header else ""
        team = (raw_row.get(team_header) or "").strip() if team_header else ""
        position = (raw_row.get(position_header) or "").strip() if position_header else ""

        produced_for_row = 0
        for column, header in matched_value_columns:
            raw_value = raw_row.get(header) or ""
            try:
                value = _parse_money(raw_value)
            except ValueError as exc:
                issues.append(
                    AuctionValueRowIssue(
                        row_number=row_number,
                        message=f"{player_name}: {column.label} is unreadable — {exc}",
                        column=header,
                    )
                )
                continue
            if value is None:
                continue
            produced_for_row += 1
            rows.append(
                PublishedValueRow(
                    row_number=row_number,
                    player_name=player_name,
                    value_kind=column.kind,
                    value_dollars=value,
                    value_raw=raw_value.strip(),
                    source_player_id=source_player_id or None,
                    team=team or None,
                    position=position or None,
                )
            )

        if produced_for_row == 0 and not any(
            issue.row_number == row_number for issue in issues if issue.fatal
        ):
            issues.append(
                AuctionValueRowIssue(
                    row_number=row_number,
                    message=f"{player_name}: every mapped value column was empty",
                )
            )

    return AuctionValueParseResult(
        rows=tuple(rows),
        issues=tuple(issues),
        resolved_headers=resolved,
        ignored_headers=ignored,
        total_rows=total_rows,
    )
