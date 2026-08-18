"""Typed, source-attributed league settings at the ingestion boundary.

Fantrax exposes league rules across more than one read-only surface. The
official ``getLeagueInfo`` response is preferred, while an existing browser
bridge capture may fill a concern only when the official response did not
provide it. Historical league rules are not an input to this module.

Every concern carries evidence even when its value is unknown. This is the
difference between "the source was checked and the field was absent" and "we
never looked", and prevents a missing field from quietly acquiring a plausible
historical default.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Never

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hoops_gm.ingest.errors import SourceContractError

OFFICIAL_SOURCE = "fantrax_official"
BRIDGE_SOURCE = "fantrax_bridge"
SCHEMA_VERSION: Literal[1] = 1

SettingSource = Literal["fantrax_official", "fantrax_bridge"]
EvidenceStatus = Literal["observed", "absent"]
LineupLockType = Literal["per_player_tipoff", "daily", "weekly"]
ClaimMechanism = Literal["priority", "faab"]
GamesCapScope = Literal["week", "position_week", "season", "position_season"]


class SettingEvidence(BaseModel):
    """One source observation behind a normalized setting."""

    model_config = ConfigDict(frozen=True)

    source: SettingSource
    status: EvidenceStatus
    source_path: str | None = None
    capture_ref: str = Field(min_length=1, max_length=128)


class SourcedSetting[T](BaseModel):
    """A value and the observations that justify it."""

    model_config = ConfigDict(frozen=True)

    value: T | None = None
    evidence: tuple[SettingEvidence, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def value_and_evidence_agree(self) -> SourcedSetting[T]:
        observed = [item for item in self.evidence if item.status == "observed"]
        if self.value is None and observed:
            raise ValueError("an unknown setting cannot have observed evidence")
        if self.value is not None and not observed:
            raise ValueError("a known setting requires observed evidence")
        return self

    @property
    def is_known(self) -> bool:
        return self.value is not None


class LineupLockRules(BaseModel):
    model_config = ConfigDict(frozen=True)

    lock_type: LineupLockType


class WaiverRules(BaseModel):
    model_config = ConfigDict(frozen=True)

    period_days: int | None = Field(default=None, ge=0)
    processing_time_local: str | None = None
    timezone: str | None = None
    claim_mechanism: ClaimMechanism | None = None
    faab_budget: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def at_least_one_rule_is_known(self) -> WaiverRules:
        if all(
            value is None
            for value in (
                self.period_days,
                self.processing_time_local,
                self.timezone,
                self.claim_mechanism,
                self.faab_budget,
            )
        ):
            raise ValueError("a known waiver setting must contain at least one rule")
        if self.claim_mechanism != "faab" and self.faab_budget is not None:
            raise ValueError("a FAAB budget requires claim_mechanism='faab'")
        return self


class GamesCap(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: GamesCapScope
    limit: int = Field(ge=0)
    position: str | None = None

    @model_validator(mode="after")
    def position_matches_scope(self) -> GamesCap:
        positional = self.scope.startswith("position_")
        if positional != (self.position is not None):
            raise ValueError("position is required exactly for position-scoped caps")
        return self


class GamesCapRules(BaseModel):
    model_config = ConfigDict(frozen=True)

    caps: tuple[GamesCap, ...] = Field(min_length=1)


class RosterLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int | None = Field(default=None, ge=0)
    active: int | None = Field(default=None, ge=0)
    reserve: int | None = Field(default=None, ge=0)
    injured_reserve: int | None = Field(default=None, ge=0)
    position_active: dict[str, int] = Field(default_factory=dict)
    injured_reserve_eligibility: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def at_least_one_limit_is_known(self) -> RosterLimits:
        if (
            self.total is None
            and self.active is None
            and self.reserve is None
            and self.injured_reserve is None
            and not self.position_active
            and self.injured_reserve_eligibility is None
        ):
            raise ValueError("a known roster setting must contain at least one limit")
        if any(value < 0 for value in self.position_active.values()):
            raise ValueError("position limits must be non-negative")
        return self


class ScoringPeriodBoundary(BaseModel):
    model_config = ConfigDict(frozen=True)

    period_number: int = Field(ge=1)
    start_at: str
    end_at: str


class ScoringPeriodRules(BaseModel):
    model_config = ConfigDict(frozen=True)

    periods: tuple[ScoringPeriodBoundary, ...] = Field(min_length=1)


class TradeDeadlineRules(BaseModel):
    model_config = ConfigDict(frozen=True)

    deadline_at: str


class PlayoffRules(BaseModel):
    model_config = ConfigDict(frozen=True)

    period_numbers: tuple[int, ...] = Field(min_length=1)


class KeeperRules(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    max_keepers: int | None = Field(default=None, ge=0)
    deadline_at: str | None = None
    provider_options: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class LeagueSettingsDocument(BaseModel):
    """Versioned normalized settings; rules are data, not algorithm branches."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = SCHEMA_VERSION
    source_season_year: int = Field(ge=2000, le=2100)
    source_start_date: str
    source_end_date: str
    lineup_lock: SourcedSetting[LineupLockRules]
    waivers: SourcedSetting[WaiverRules]
    games_caps: SourcedSetting[GamesCapRules]
    roster_limits: SourcedSetting[RosterLimits]
    scoring_periods: SourcedSetting[ScoringPeriodRules]
    trade_deadline: SourcedSetting[TradeDeadlineRules]
    playoffs: SourcedSetting[PlayoffRules]
    keepers: SourcedSetting[KeeperRules]
    unmapped_rule_paths: tuple[str, ...] = ()

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def parse_official_league_settings(
    payload: object,
    *,
    capture_ref: str,
) -> LeagueSettingsDocument:
    """Normalize the settings ``getLeagueInfo`` actually exposes.

    The official response currently supplies roster limits and scoring-period
    boundaries. It does not expose the timing and transaction-rule concerns
    below in the observed NBA payload; those remain unknown, with an ``absent``
    observation, rather than borrowing values from the historical baseline.
    """

    endpoint = "getLeagueInfo"
    if not isinstance(payload, dict):
        raise SourceContractError(
            f"expected an object, got {type(payload).__name__}",
            source=OFFICIAL_SOURCE,
            endpoint=endpoint,
        )

    roster_limits = _parse_roster_limits(payload.get("rosterInfo"), capture_ref=capture_ref)
    scoring_periods = _parse_scoring_periods(payload.get("scoringPeriods"), capture_ref=capture_ref)
    return LeagueSettingsDocument(
        source_season_year=_required_positive_int(payload.get("seasonYear"), path="seasonYear"),
        source_start_date=_required_str(payload.get("startDate"), path="startDate"),
        source_end_date=_required_str(payload.get("endDate"), path="endDate"),
        lineup_lock=_absent(capture_ref),
        waivers=_absent(capture_ref),
        games_caps=_absent(capture_ref),
        roster_limits=roster_limits,
        scoring_periods=scoring_periods,
        trade_deadline=_absent(capture_ref),
        playoffs=_parse_playoff_periods(payload.get("scoringPeriods"), capture_ref=capture_ref),
        keepers=_absent(capture_ref),
        unmapped_rule_paths=_find_unmapped_rule_paths(payload),
    )


def merge_settings(
    official: LeagueSettingsDocument,
    bridge: LeagueSettingsDocument | None,
) -> LeagueSettingsDocument:
    """Fill official unknowns from existing bridge evidence, never the reverse."""

    if bridge is None:
        return official

    def choose[ValueT](
        primary: SourcedSetting[ValueT],
        fallback: SourcedSetting[ValueT],
    ) -> SourcedSetting[ValueT]:
        if primary.is_known:
            return primary
        if fallback.is_known:
            return SourcedSetting(
                value=fallback.value,
                evidence=primary.evidence + fallback.evidence,
            )
        return SourcedSetting(value=None, evidence=primary.evidence + fallback.evidence)

    return LeagueSettingsDocument(
        source_season_year=official.source_season_year,
        source_start_date=official.source_start_date,
        source_end_date=official.source_end_date,
        lineup_lock=choose(official.lineup_lock, bridge.lineup_lock),
        waivers=choose(official.waivers, bridge.waivers),
        games_caps=choose(official.games_caps, bridge.games_caps),
        roster_limits=choose(official.roster_limits, bridge.roster_limits),
        scoring_periods=choose(official.scoring_periods, bridge.scoring_periods),
        trade_deadline=choose(official.trade_deadline, bridge.trade_deadline),
        playoffs=choose(official.playoffs, bridge.playoffs),
        keepers=choose(official.keepers, bridge.keepers),
        unmapped_rule_paths=tuple(
            sorted({*official.unmapped_rule_paths, *bridge.unmapped_rule_paths})
        ),
    )


def _parse_roster_limits(
    value: object,
    *,
    capture_ref: str,
) -> SourcedSetting[RosterLimits]:
    if value is None:
        return _absent(capture_ref)
    if not isinstance(value, dict):
        raise SourceContractError(
            "rosterInfo must be an object",
            source=OFFICIAL_SOURCE,
            endpoint="getLeagueInfo",
        )

    positions: dict[str, int] = {}
    raw_positions = value.get("positionConstraints")
    if raw_positions is not None:
        if not isinstance(raw_positions, dict):
            raise SourceContractError(
                "rosterInfo.positionConstraints must be an object",
                source=OFFICIAL_SOURCE,
                endpoint="getLeagueInfo",
            )
        for code, constraint in raw_positions.items():
            if not isinstance(code, str) or not isinstance(constraint, dict):
                raise SourceContractError(
                    "roster position constraints must map strings to objects",
                    source=OFFICIAL_SOURCE,
                    endpoint="getLeagueInfo",
                )
            maximum = _optional_non_negative_int(
                constraint.get("maxActive"),
                path=f"rosterInfo.positionConstraints.{code}.maxActive",
            )
            if maximum is not None:
                positions[code] = maximum

    parsed = RosterLimits(
        total=_optional_non_negative_int(
            value.get("maxTotalPlayers"), path="rosterInfo.maxTotalPlayers"
        ),
        active=_optional_non_negative_int(
            value.get("maxTotalActivePlayers"), path="rosterInfo.maxTotalActivePlayers"
        ),
        reserve=_optional_non_negative_int(
            value.get("maxTotalReservePlayers"), path="rosterInfo.maxTotalReservePlayers"
        ),
        position_active=positions,
    )
    return SourcedSetting(
        value=parsed,
        evidence=(_observed("$.rosterInfo", capture_ref),),
    )


def _parse_scoring_periods(
    value: object,
    *,
    capture_ref: str,
) -> SourcedSetting[ScoringPeriodRules]:
    if value is None:
        return _absent(capture_ref)
    if not isinstance(value, list) or not value:
        raise SourceContractError(
            "scoringPeriods must be a non-empty array",
            source=OFFICIAL_SOURCE,
            endpoint="getLeagueInfo",
        )

    periods: list[ScoringPeriodBoundary] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise SourceContractError(
                f"scoringPeriods[{index}] must be an object",
                source=OFFICIAL_SOURCE,
                endpoint="getLeagueInfo",
            )
        number = _required_positive_int(
            item.get("number", item.get("period")),
            path=f"scoringPeriods[{index}].number",
        )
        start_at = _required_str(
            item.get("startDate", item.get("start")),
            path=f"scoringPeriods[{index}].startDate",
        )
        end_at = _required_str(
            item.get("endDate", item.get("end")),
            path=f"scoringPeriods[{index}].endDate",
        )
        periods.append(
            ScoringPeriodBoundary(
                period_number=number,
                start_at=start_at,
                end_at=end_at,
            )
        )

    if len({period.period_number for period in periods}) != len(periods):
        raise SourceContractError(
            "scoringPeriods contains duplicate period numbers",
            source=OFFICIAL_SOURCE,
            endpoint="getLeagueInfo",
        )

    return SourcedSetting(
        value=ScoringPeriodRules(periods=tuple(periods)),
        evidence=(_observed("$.scoringPeriods", capture_ref),),
    )


def _parse_playoff_periods(
    value: object,
    *,
    capture_ref: str,
) -> SourcedSetting[PlayoffRules]:
    if not isinstance(value, list):
        return _absent(capture_ref)

    periods: list[int] = []
    saw_marker = False
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        marker = item.get("isPlayoff", item.get("playoff"))
        if marker is None:
            continue
        if not isinstance(marker, bool):
            raise SourceContractError(
                f"scoringPeriods[{index}] playoff marker must be boolean",
                source=OFFICIAL_SOURCE,
                endpoint="getLeagueInfo",
            )
        saw_marker = True
        if marker:
            periods.append(
                _required_positive_int(
                    item.get("number", item.get("period")),
                    path=f"scoringPeriods[{index}].number",
                )
            )

    if not saw_marker:
        return _absent(capture_ref)
    if not periods:
        raise SourceContractError(
            "scoringPeriods has playoff markers but none are true",
            source=OFFICIAL_SOURCE,
            endpoint="getLeagueInfo",
        )
    return SourcedSetting(
        value=PlayoffRules(period_numbers=tuple(periods)),
        evidence=(_observed("$.scoringPeriods[*].isPlayoff", capture_ref),),
    )


def _find_unmapped_rule_paths(payload: dict[object, object]) -> tuple[str, ...]:
    """Surface rule-shaped keys that this parser did not normalize."""

    mapped = {
        "$.rosterInfo",
        "$.rosterInfo.positionConstraints",
        "$.rosterInfo.maxTotalPlayers",
        "$.rosterInfo.maxTotalActivePlayers",
        "$.rosterInfo.maxTotalReservePlayers",
        "$.scoringPeriods",
        "$.scoringPeriods[*].isPlayoff",
        "$.scoringPeriods[*].playoff",
    }
    needles = (
        "waiver",
        "claim",
        "faab",
        "processing",
        "lock",
        "trade",
        "deadline",
        "keeper",
        "gamecap",
        "gamescap",
        "playoff",
        "injuredreserve",
        "eligibility",
    )
    found: set[str] = set()

    def visit(value: object, path: str) -> None:
        if isinstance(value, dict):
            for raw_key, child in value.items():
                key = str(raw_key)
                child_path = f"{path}.{key}"
                lowered = key.lower().replace("_", "").replace("-", "")
                if any(needle in lowered for needle in needles):
                    found.add(child_path)
                if len(path.split(".")) < 5:
                    visit(child, child_path)
        elif isinstance(value, list) and len(path.split(".")) < 5:
            for child in value[:5]:
                visit(child, f"{path}[*]")

    visit(payload, "$")
    return tuple(sorted(path for path in found if path not in mapped))


def _observed(path: str, capture_ref: str) -> SettingEvidence:
    return SettingEvidence(
        source=OFFICIAL_SOURCE,
        status="observed",
        source_path=path,
        capture_ref=capture_ref,
    )


def _absent[ValueT](capture_ref: str) -> SourcedSetting[ValueT]:
    return SourcedSetting(
        value=None,
        evidence=(
            SettingEvidence(
                source=OFFICIAL_SOURCE,
                status="absent",
                source_path="$",
                capture_ref=capture_ref,
            ),
        ),
    )


def _optional_non_negative_int(value: object, *, path: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        _contract_error(path, "must be a non-negative integer")
    try:
        parsed = int(value) if isinstance(value, str | int) else -1
    except ValueError:
        parsed = -1
    if parsed < 0 or str(parsed) != str(value).strip():
        _contract_error(path, "must be a non-negative integer")
    return parsed


def _required_positive_int(value: object, *, path: str) -> int:
    parsed = _optional_non_negative_int(value, path=path)
    if parsed is None or parsed < 1:
        _contract_error(path, "must be a positive integer")
    return parsed


def _required_str(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _contract_error(path, "must be a non-empty string")
    return value


def _contract_error(path: str, message: str) -> Never:
    raise SourceContractError(
        f"{path} {message}",
        source=OFFICIAL_SOURCE,
        endpoint="getLeagueInfo",
    )
