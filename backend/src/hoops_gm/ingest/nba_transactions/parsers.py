"""Strict parsers for the NBA's official transaction archives."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Final

from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.nba_transactions.models import (
    GLeagueTransactionRecord,
    NbaPlayerMovementRecord,
)

SOURCE: Final = "nba_official_transactions"
NBA_PLAYER_MOVEMENT_ENDPOINT: Final = "NBAPlayerMovement"
G_LEAGUE_TRANSACTIONS_ENDPOINT: Final = "GLeagueTransactions"

NBA_PLAYER_MOVEMENT_FIELDS: Final = frozenset(
    {
        "Transaction_Type",
        "TRANSACTION_DATE",
        "TRANSACTION_DESCRIPTION",
        "TEAM_ID",
        "TEAM_SLUG",
        "PLAYER_ID",
        "PLAYER_SLUG",
        "Additional_Sort",
        "GroupSort",
    }
)
NBA_PLAYER_MOVEMENT_COLUMNS: Final = (
    ("Transaction_Type", "String"),
    ("TRANSACTION_DATE", "DateTime"),
    ("TRANSACTION_DESCRIPTION", "String"),
    ("TEAM_ID", "Decimal"),
    ("TEAM_SLUG", "String"),
    ("PLAYER_ID", "Decimal"),
    ("PLAYER_SLUG", "String"),
    ("Additional_Sort", "Decimal"),
    ("GroupSort", "String"),
)
NBA_PLAYER_MOVEMENT_TYPES: Final = frozenset(
    {"AwardOnWaivers", "ContractConverted", "Signing", "Trade", "Waive"}
)

G_LEAGUE_TRANSACTION_FIELDS: Final = frozenset(
    {
        "TEAM_ID",
        "PLAYER_ID",
        "TEAM_SLUG",
        "GROUP_SORT",
        "PLAYER_SLUG",
        "ADDITIONAL_SORT",
        "TRANSACTION_DATE",
        "TRANSACTION_TYPE",
        "TRANSACTION_DESCRIPTION",
    }
)
G_LEAGUE_TYPE_DESCRIPTIONS: Final[dict[str, frozenset[str]]] = {
    "Acquired/Assigned": frozenset(
        {"Acquired", "Acquired from Player Pool", "Acquired from Waivers", "Assigned"}
    ),
    "Call-Up/Recall": frozenset({"NBA Call-Up", "Recalled"}),
    "Drafted": frozenset({"Drafted"}),
    "Trade": frozenset({"Traded"}),
    "Two-Way Signing": frozenset({"Two-Way Signing"}),
    "Waived/Buyout": frozenset({"Buyout", "Waived", "Waivers Cleared"}),
}


def parse_nba_player_movements(payload: Any) -> list[NbaPlayerMovementRecord]:
    """Parse the dated NBA player-movement archive without deriving intervals."""
    if not isinstance(payload, dict) or set(payload) != {"NBA_Player_Movement"}:
        raise _contract_error(
            NBA_PLAYER_MOVEMENT_ENDPOINT,
            "expected exactly one top-level key named 'NBA_Player_Movement'",
        )
    envelope = payload["NBA_Player_Movement"]
    if not isinstance(envelope, dict) or set(envelope) != {"columns", "rows"}:
        raise _contract_error(
            NBA_PLAYER_MOVEMENT_ENDPOINT,
            "expected the NBA_Player_Movement object to contain exactly 'columns' and 'rows'",
        )
    _require_column_contract(envelope["columns"])
    rows = envelope["rows"]
    if not isinstance(rows, list) or not rows:
        raise _contract_error(
            NBA_PLAYER_MOVEMENT_ENDPOINT, "expected a non-empty transaction row list"
        )

    parsed: list[NbaPlayerMovementRecord] = []
    for index, row in enumerate(rows):
        _require_exact_fields(
            row,
            expected=NBA_PLAYER_MOVEMENT_FIELDS,
            endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT,
            index=index,
        )
        transaction_type = _required_text(
            row["Transaction_Type"], endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT, field="Transaction_Type"
        )
        if transaction_type not in NBA_PLAYER_MOVEMENT_TYPES:
            raise _contract_error(
                NBA_PLAYER_MOVEMENT_ENDPOINT,
                f"row {index} has unknown Transaction_Type {transaction_type!r}",
            )

        nba_player_id = _integral_number(
            row["PLAYER_ID"], endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT, field="PLAYER_ID", minimum=0
        )
        raw_player_slug = _text(
            row["PLAYER_SLUG"], endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT, field="PLAYER_SLUG"
        )
        if (nba_player_id == 0) != (raw_player_slug == ""):
            raise _contract_error(
                NBA_PLAYER_MOVEMENT_ENDPOINT,
                f"row {index} must pair PLAYER_ID 0 with a blank PLAYER_SLUG",
            )

        parsed.append(
            NbaPlayerMovementRecord(
                transaction_type=transaction_type,
                transaction_date=_strict_date(
                    row["TRANSACTION_DATE"],
                    endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT,
                    field="TRANSACTION_DATE",
                    format_string="%Y-%m-%dT00:00:00",
                ),
                transaction_description=_required_text(
                    row["TRANSACTION_DESCRIPTION"],
                    endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT,
                    field="TRANSACTION_DESCRIPTION",
                ),
                nba_team_id=_integral_number(
                    row["TEAM_ID"],
                    endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT,
                    field="TEAM_ID",
                    minimum=1,
                ),
                team_slug=_required_text(
                    row["TEAM_SLUG"], endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT, field="TEAM_SLUG"
                ),
                nba_player_id=nba_player_id or None,
                player_slug=raw_player_slug or None,
                related_team_id=_optional_positive_id(
                    row["Additional_Sort"],
                    endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT,
                    field="Additional_Sort",
                ),
                group_sort=_required_text(
                    row["GroupSort"], endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT, field="GroupSort"
                ),
            )
        )
    return parsed


def parse_g_league_transactions(payload: Any) -> list[GLeagueTransactionRecord]:
    """Parse the dated G League archive, including assignment and recall rows."""
    if not isinstance(payload, list) or not payload:
        raise _contract_error(
            G_LEAGUE_TRANSACTIONS_ENDPOINT, "expected a non-empty transaction row list"
        )

    parsed: list[GLeagueTransactionRecord] = []
    for index, row in enumerate(payload):
        _require_exact_fields(
            row,
            expected=G_LEAGUE_TRANSACTION_FIELDS,
            endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
            index=index,
        )
        transaction_type = _required_text(
            row["TRANSACTION_TYPE"],
            endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
            field="TRANSACTION_TYPE",
        )
        description = _required_text(
            row["TRANSACTION_DESCRIPTION"],
            endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
            field="TRANSACTION_DESCRIPTION",
        )
        allowed_descriptions = G_LEAGUE_TYPE_DESCRIPTIONS.get(transaction_type)
        if allowed_descriptions is None or description not in allowed_descriptions:
            raise _contract_error(
                G_LEAGUE_TRANSACTIONS_ENDPOINT,
                f"row {index} has unknown type/description pair "
                f"{(transaction_type, description)!r}",
            )

        team_id = _integral_number(
            row["TEAM_ID"],
            endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
            field="TEAM_ID",
            minimum=0,
        )
        raw_team_slug = _text(
            row["TEAM_SLUG"], endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT, field="TEAM_SLUG"
        )
        if team_id == 0 and raw_team_slug:
            raise _contract_error(
                G_LEAGUE_TRANSACTIONS_ENDPOINT,
                f"row {index} cannot pair TEAM_ID 0 with a non-blank TEAM_SLUG",
            )

        parsed.append(
            GLeagueTransactionRecord(
                transaction_type=transaction_type,
                transaction_date=_strict_date(
                    row["TRANSACTION_DATE"],
                    endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
                    field="TRANSACTION_DATE",
                    format_string="%Y-%m-%d",
                ),
                transaction_description=description,
                g_league_team_id=team_id or None,
                team_slug=raw_team_slug or None,
                nba_player_id=_integral_number(
                    row["PLAYER_ID"],
                    endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
                    field="PLAYER_ID",
                    minimum=1,
                ),
                player_slug=_required_text(
                    row["PLAYER_SLUG"],
                    endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
                    field="PLAYER_SLUG",
                ),
                related_team_id=_optional_positive_id(
                    row["ADDITIONAL_SORT"],
                    endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
                    field="ADDITIONAL_SORT",
                ),
                group_sort=_required_text(
                    row["GROUP_SORT"],
                    endpoint=G_LEAGUE_TRANSACTIONS_ENDPOINT,
                    field="GROUP_SORT",
                ),
            )
        )
    return parsed


def _require_exact_fields(row: Any, *, expected: frozenset[str], endpoint: str, index: int) -> None:
    if not isinstance(row, dict):
        raise _contract_error(endpoint, f"row {index} is not an object")
    actual = set(row)
    if actual != expected:
        raise _contract_error(
            endpoint,
            f"row {index} fields changed; missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}",
        )


def _require_column_contract(columns: Any) -> None:
    if not isinstance(columns, list):
        raise _contract_error(NBA_PLAYER_MOVEMENT_ENDPOINT, "columns must be an ordered list")
    actual: list[tuple[str, str]] = []
    for index, column in enumerate(columns):
        if not isinstance(column, dict) or set(column) != {"DataType", "Name"}:
            raise _contract_error(
                NBA_PLAYER_MOVEMENT_ENDPOINT,
                f"column {index} must contain exactly 'Name' and 'DataType'",
            )
        name = _required_text(
            column["Name"], endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT, field="columns.Name"
        )
        data_type = _required_text(
            column["DataType"],
            endpoint=NBA_PLAYER_MOVEMENT_ENDPOINT,
            field="columns.DataType",
        )
        actual.append((name, data_type))
    if tuple(actual) != NBA_PLAYER_MOVEMENT_COLUMNS:
        raise _contract_error(
            NBA_PLAYER_MOVEMENT_ENDPOINT,
            f"column contract changed; expected {NBA_PLAYER_MOVEMENT_COLUMNS!r}, "
            f"got {tuple(actual)!r}",
        )


def _strict_date(value: Any, *, endpoint: str, field: str, format_string: str) -> date:
    text = _required_text(value, endpoint=endpoint, field=field)
    try:
        parsed = datetime.strptime(text, format_string)
    except ValueError as exc:
        raise _contract_error(endpoint, f"{field} has an unrecognized value {value!r}") from exc
    if parsed.strftime(format_string) != text:
        raise _contract_error(endpoint, f"{field} has an unrecognized value {value!r}")
    return parsed.date()


def _optional_positive_id(value: Any, *, endpoint: str, field: str) -> int | None:
    parsed = _integral_number(value, endpoint=endpoint, field=field, minimum=0)
    return parsed or None


def _integral_number(value: Any, *, endpoint: str, field: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _contract_error(endpoint, f"{field} must be an integer-valued JSON number")
    number = float(value)
    if not math.isfinite(number) or not number.is_integer() or number < minimum:
        raise _contract_error(
            endpoint, f"{field} must be an integer-valued JSON number >= {minimum}"
        )
    return int(number)


def _required_text(value: Any, *, endpoint: str, field: str) -> str:
    text = _text(value, endpoint=endpoint, field=field)
    if not text:
        raise _contract_error(endpoint, f"{field} must be a non-empty string")
    return text


def _text(value: Any, *, endpoint: str, field: str) -> str:
    if not isinstance(value, str):
        raise _contract_error(endpoint, f"{field} must be a string")
    return value


def _contract_error(endpoint: str, message: str) -> SourceContractError:
    return SourceContractError(message, source=SOURCE, endpoint=endpoint)
