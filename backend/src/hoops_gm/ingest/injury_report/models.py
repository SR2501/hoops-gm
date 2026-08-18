"""Typed records parsed from the NBA official injury report PDF.

Plain frozen dataclasses so the parser stays pure and the contract tests stay
offline and instant. Nothing here is a SQLAlchemy model or touches a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from hoops_gm.db.models.enums import InjuryReportStatus

#: Re-exported so an adapter never has to reach into the database package for a
#: vocabulary, while the vocabulary itself lives in exactly one place — the
#: place whose CHECK constraint enforces it.
__all__ = [
    "InjuryReportEntryRecord",
    "InjuryReportParseResult",
    "InjuryReportStatus",
]


@dataclass(frozen=True)
class InjuryReportEntryRecord:
    """One player's designation on one report page, plus its raw evidence.

    Every ``*_raw`` field is exactly what the PDF printed, kept alongside any
    interpretation for the same reason ``player_participation.raw_comment`` is
    never dropped: a normalisation that turns out wrong must be re-derivable
    from the original text rather than lost with the row that used it.
    """

    report_timestamp: datetime
    game_date: date
    game_time_raw: str
    matchup_raw: str
    team_raw: str
    player_name_raw: str
    status_raw: str
    status: InjuryReportStatus
    reason_raw: str = ""


@dataclass(frozen=True)
class InjuryReportParseResult:
    """Everything one PDF capture said.

    ``entries`` includes ``NOT_YET_SUBMITTED`` marker rows, which name no
    player at all — a team's report simply had not been filed as of this
    capture. ``player_entries`` excludes them.
    """

    report_timestamp: datetime
    source_url: str
    entries: tuple[InjuryReportEntryRecord, ...] = field(default_factory=tuple)

    @property
    def player_entries(self) -> tuple[InjuryReportEntryRecord, ...]:
        """Entries that name an actual player, excluding unsubmitted markers."""
        return tuple(
            e for e in self.entries if e.status is not InjuryReportStatus.NOT_YET_SUBMITTED
        )
