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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Never

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from hoops_gm.ingest.errors import SourceContractError


def _require_offset_aware_timestamp(value: str) -> str:
    """Reject a deadline instant that is naive or unparseable.

    A deadline that governs a real-money-adjacent write action (trade lock,
    keeper cutoff) must be an unambiguous instant. A naive string is
    ambiguous about *whose* clock it is on, and this module never guesses --
    see the module docstring on not acquiring a plausible default.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"must be a valid ISO 8601 timestamp, got {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"must carry a UTC offset, got a naive timestamp {value!r}")
    return value


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
    model_config = ConfigDict(frozen=True, extra="forbid")

    lock_type: LineupLockType


class WaiverRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    period_days: StrictInt | None = Field(default=None, ge=0)
    processing_time_local: str | None = None
    timezone: str | None = None
    claim_mechanism: ClaimMechanism | None = None
    faab_budget: StrictFloat | None = Field(default=None, ge=0)

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
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: GamesCapScope
    limit: StrictInt = Field(ge=0)
    position: str | None = None

    @model_validator(mode="after")
    def position_matches_scope(self) -> GamesCap:
        positional = self.scope.startswith("position_")
        if positional != (self.position is not None):
            raise ValueError("position is required exactly for position-scoped caps")
        return self


class GamesCapRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    caps: tuple[GamesCap, ...] = Field(min_length=1)


class RosterLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total: StrictInt | None = Field(default=None, ge=0)
    active: StrictInt | None = Field(default=None, ge=0)
    reserve: StrictInt | None = Field(default=None, ge=0)
    injured_reserve: StrictInt | None = Field(default=None, ge=0)
    position_active: dict[str, StrictInt] = Field(default_factory=dict)
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
    model_config = ConfigDict(frozen=True, extra="forbid")

    period_number: StrictInt = Field(ge=1)
    start_at: str
    end_at: str


class ScoringPeriodRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    periods: tuple[ScoringPeriodBoundary, ...] = Field(min_length=1)


class TradeDeadlineRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    deadline_at: str

    @field_validator("deadline_at")
    @classmethod
    def _deadline_at_is_offset_aware(cls, value: str) -> str:
        return _require_offset_aware_timestamp(value)


class PlayoffRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    period_numbers: tuple[StrictInt, ...] = Field(min_length=1)


class KeeperRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: StrictBool
    max_keepers: StrictInt | None = Field(default=None, ge=0)
    deadline_at: str | None = None
    provider_options: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("deadline_at")
    @classmethod
    def _deadline_at_is_offset_aware(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_offset_aware_timestamp(value)


class ScoringFormatRules(BaseModel):
    """The league's scoring-format discriminator, verbatim from the source.

    Kept as the raw upstream string (``raw_type``, e.g.
    ``"HEAD_TO_HEAD_ROTI_MULTI_WIN"``) rather than normalized into
    ``hoops_gm.db.models.enums.ScoringType`` here: this module is the
    ingestion boundary and must not depend on ``hoops_gm.db`` (ADR-006 draws
    that line at the adapter boundary, and ``hoops_gm.scoring.profiles``
    already sits on the other side of it). The verified mapping from this raw
    string to a local enum value -- including the decision to fail closed on
    an unrecognised discriminator -- is that module's job, not this one's.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_type: str = Field(min_length=1)


class ScoringCategoryRule(BaseModel):
    """One scoring category exactly as the league's rules report it.

    ``code`` is the primary, durable mapping anchor: Fantrax's own stable
    per-category identifier (e.g. ``"INDIVIDUAL_ASSISTS"``). ``abbreviation``
    and ``display_name`` are retained as evidence/display only -- never as a
    mapping key -- because Fantrax's numeric ``id`` and its display strings
    are not guaranteed stable across payload shapes the way ``code`` is (see
    ``ingest/fantrax_official/parsers.py``, which previously conflated the
    numeric id with this field).

    ``weight`` is Fantrax's own per-category scoring weight, a distinct
    concept from ``LeagueScoringCategory.point_value`` (this project's
    points-league weight, always null for a category league). Every category
    observed in the target H2H league carries ``weight == 1.0``; a category
    with a non-unit weight is data this document still records honestly, but
    ``hoops_gm.scoring.profiles`` refuses to build a profile from it until
    weighted categories are designed (fail closed rather than silently
    dropping or misapplying the weight).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(min_length=1)
    display_name: str | None = None
    abbreviation: str = Field(min_length=1)
    weight: StrictFloat


class ScoringCategoriesRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    categories: tuple[ScoringCategoryRule, ...] = Field(min_length=1)


class LeagueSettingsDocument(BaseModel):
    """Versioned normalized settings; rules are data, not algorithm branches."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = SCHEMA_VERSION
    source_league_id: str = Field(min_length=1, max_length=64)
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
    scoring_type: SourcedSetting[ScoringFormatRules]
    scoring_categories: SourcedSetting[ScoringCategoriesRules]
    unmapped_rule_paths: tuple[str, ...] = ()

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def configuration_json(self) -> str:
        """Canonical rule content, excluding observation-specific evidence."""
        serialized = self.model_dump(mode="json")

        def setting(name: str) -> dict[str, object]:
            sourced = serialized[name]
            evidence = sorted(
                (
                    {
                        "source": item["source"],
                        "status": item["status"],
                        "source_path": item["source_path"],
                    }
                    for item in sourced["evidence"]
                ),
                key=lambda item: (
                    str(item["source"]),
                    str(item["status"]),
                    str(item["source_path"]),
                ),
            )
            return {
                "value": sourced["value"],
                "evidence": evidence,
            }

        configuration = {
            "schema_version": serialized["schema_version"],
            "source_league_id": serialized["source_league_id"],
            "source_season_year": serialized["source_season_year"],
            "source_start_date": serialized["source_start_date"],
            "source_end_date": serialized["source_end_date"],
            "lineup_lock": setting("lineup_lock"),
            "waivers": setting("waivers"),
            "games_caps": setting("games_caps"),
            "roster_limits": setting("roster_limits"),
            "scoring_periods": setting("scoring_periods"),
            "trade_deadline": setting("trade_deadline"),
            "playoffs": setting("playoffs"),
            "keepers": setting("keepers"),
            "scoring_type": setting("scoring_type"),
            "scoring_categories": setting("scoring_categories"),
            "unmapped_rule_paths": serialized["unmapped_rule_paths"],
        }
        return json.dumps(configuration, sort_keys=True, separators=(",", ":"))

    def content_sha256(self) -> str:
        return hashlib.sha256(self.configuration_json().encode("utf-8")).hexdigest()


class BridgeSettingsValues(BaseModel):
    """Explicit values exported from an existing read-only bridge capture."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lineup_lock: LineupLockRules | None = None
    waivers: WaiverRules | None = None
    games_caps: GamesCapRules | None = None
    roster_limits: RosterLimits | None = None
    scoring_periods: ScoringPeriodRules | None = None
    trade_deadline: TradeDeadlineRules | None = None
    playoffs: PlayoffRules | None = None
    keepers: KeeperRules | None = None


class BridgeLeagueSettingsPayload(BaseModel):
    """Versioned handoff shape for a manually supplied bridge capture."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    league_id: str = Field(min_length=1, max_length=64)
    season_year: int = Field(ge=2000, le=2100)
    start_date: str = Field(min_length=1)
    end_date: str = Field(min_length=1)
    observed_at: datetime
    settings: BridgeSettingsValues

    @model_validator(mode="after")
    def observation_is_timezone_aware(self) -> BridgeLeagueSettingsPayload:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return self


@dataclass(frozen=True)
class BridgeLeagueSettingsObservation:
    """Validated bridge settings plus exact capture provenance."""

    document: LeagueSettingsDocument
    observed_at: datetime
    source_payload_sha256: str


def parse_bridge_league_settings(
    payload: object,
    *,
    capture_ref: str,
    source_payload_sha256: str,
) -> BridgeLeagueSettingsObservation:
    """Validate an explicit bridge capture without reading or polling Fantrax."""
    if len(source_payload_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in source_payload_sha256
    ):
        raise ValueError("source_payload_sha256 must be a lowercase SHA-256 hex digest")
    try:
        parsed = BridgeLeagueSettingsPayload.model_validate(payload)
    except ValidationError as exc:
        raise SourceContractError(
            "bridge league-settings capture did not match schema version 1",
            source=BRIDGE_SOURCE,
            endpoint="leagueSettingsCapture",
            detail=exc.errors(include_url=False),
        ) from exc

    values = parsed.settings
    document = LeagueSettingsDocument(
        source_league_id=parsed.league_id,
        source_season_year=parsed.season_year,
        source_start_date=parsed.start_date,
        source_end_date=parsed.end_date,
        lineup_lock=_bridge_setting(
            values.lineup_lock,
            path="$.settings.lineup_lock",
            capture_ref=capture_ref,
        ),
        waivers=_bridge_setting(
            values.waivers,
            path="$.settings.waivers",
            capture_ref=capture_ref,
        ),
        games_caps=_bridge_setting(
            values.games_caps,
            path="$.settings.games_caps",
            capture_ref=capture_ref,
        ),
        roster_limits=_bridge_setting(
            values.roster_limits,
            path="$.settings.roster_limits",
            capture_ref=capture_ref,
        ),
        scoring_periods=_bridge_setting(
            values.scoring_periods,
            path="$.settings.scoring_periods",
            capture_ref=capture_ref,
        ),
        trade_deadline=_bridge_setting(
            values.trade_deadline,
            path="$.settings.trade_deadline",
            capture_ref=capture_ref,
        ),
        playoffs=_bridge_setting(
            values.playoffs,
            path="$.settings.playoffs",
            capture_ref=capture_ref,
        ),
        keepers=_bridge_setting(
            values.keepers,
            path="$.settings.keepers",
            capture_ref=capture_ref,
        ),
        # The bridge capture contract has no scoring-rules fields (see
        # BridgeSettingsValues): scoring type/categories are trusted only
        # from the verified official source, never from the read-only
        # bridge, so both are unconditionally absent here.
        scoring_type=_absent(capture_ref),
        scoring_categories=_absent(capture_ref),
    )
    return BridgeLeagueSettingsObservation(
        document=document,
        observed_at=parsed.observed_at,
        source_payload_sha256=source_payload_sha256,
    )


def load_bridge_league_settings_capture(path: Path) -> BridgeLeagueSettingsObservation:
    """Load one operator-selected JSON capture; no capture or network access occurs."""
    try:
        body = path.read_bytes()
        payload = json.loads(body.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceContractError(
            f"could not read bridge league-settings capture: {exc}",
            source=BRIDGE_SOURCE,
            endpoint="leagueSettingsCapture",
            detail={"path": str(path)},
        ) from exc
    digest = hashlib.sha256(body).hexdigest()
    return parse_bridge_league_settings(
        payload,
        capture_ref=f"{BRIDGE_SOURCE}:sha256:{digest}",
        source_payload_sha256=digest,
    )


def parse_official_league_settings(
    payload: object,
    *,
    source_league_id: str,
    capture_ref: str,
) -> LeagueSettingsDocument:
    """Normalize the settings ``getLeagueInfo`` actually exposes.

    The official response currently supplies roster limits, scoring-period
    boundaries, scoring type, and scoring categories. It does not expose the
    timing and transaction-rule concerns below in the observed NBA payload;
    those remain unknown, with an ``absent`` observation, rather than
    borrowing values from the historical baseline.
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
    scoring_type = _parse_scoring_type(payload, capture_ref=capture_ref)
    scoring_categories = _parse_scoring_categories(payload, capture_ref=capture_ref)
    return LeagueSettingsDocument(
        source_league_id=source_league_id,
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
        scoring_type=scoring_type,
        scoring_categories=scoring_categories,
        unmapped_rule_paths=_find_unmapped_rule_paths(payload),
    )


def merge_settings(
    official: LeagueSettingsDocument,
    bridge: LeagueSettingsDocument | None,
) -> LeagueSettingsDocument:
    """Fill official unknowns from existing bridge evidence, never the reverse."""

    if bridge is None:
        return official
    official_identity = (
        official.source_league_id,
        official.source_season_year,
        official.source_start_date,
        official.source_end_date,
    )
    bridge_identity = (
        bridge.source_league_id,
        bridge.source_season_year,
        bridge.source_start_date,
        bridge.source_end_date,
    )
    if official_identity != bridge_identity:
        raise ValueError(
            "cannot merge league settings from different league-season boundaries: "
            f"official={official_identity!r}, bridge={bridge_identity!r}"
        )

    return LeagueSettingsDocument(
        source_league_id=official.source_league_id,
        source_season_year=official.source_season_year,
        source_start_date=official.source_start_date,
        source_end_date=official.source_end_date,
        lineup_lock=_choose_setting(official.lineup_lock, bridge.lineup_lock),
        waivers=_merge_waivers(official.waivers, bridge.waivers),
        games_caps=_merge_games_caps(official.games_caps, bridge.games_caps),
        roster_limits=_merge_roster_limits(
            official.roster_limits,
            bridge.roster_limits,
        ),
        scoring_periods=_choose_setting(
            official.scoring_periods,
            bridge.scoring_periods,
        ),
        trade_deadline=_choose_setting(
            official.trade_deadline,
            bridge.trade_deadline,
        ),
        playoffs=_choose_setting(official.playoffs, bridge.playoffs),
        keepers=_merge_keepers(official.keepers, bridge.keepers),
        # The bridge capture contract has no scoring-rules fields (see
        # BridgeSettingsValues) and never will supply an observed value here
        # -- this is still official-priority _choose_setting for uniformity,
        # not a special case, and it means a future bridge field would slot
        # in without touching this function.
        scoring_type=_choose_setting(official.scoring_type, bridge.scoring_type),
        scoring_categories=_choose_setting(official.scoring_categories, bridge.scoring_categories),
        unmapped_rule_paths=tuple(
            sorted({*official.unmapped_rule_paths, *bridge.unmapped_rule_paths})
        ),
    )


def _merge_roster_limits(
    primary: SourcedSetting[RosterLimits],
    fallback: SourcedSetting[RosterLimits],
) -> SourcedSetting[RosterLimits]:
    if primary.value is None or fallback.value is None:
        return _choose_setting(primary, fallback)
    merged = RosterLimits(
        total=primary.value.total if primary.value.total is not None else fallback.value.total,
        active=primary.value.active if primary.value.active is not None else fallback.value.active,
        reserve=primary.value.reserve
        if primary.value.reserve is not None
        else fallback.value.reserve,
        injured_reserve=primary.value.injured_reserve
        if primary.value.injured_reserve is not None
        else fallback.value.injured_reserve,
        position_active={
            **fallback.value.position_active,
            **primary.value.position_active,
        },
        injured_reserve_eligibility=primary.value.injured_reserve_eligibility
        if primary.value.injured_reserve_eligibility is not None
        else fallback.value.injured_reserve_eligibility,
    )
    return _merged_setting(primary, fallback, merged)


def _merge_waivers(
    primary: SourcedSetting[WaiverRules],
    fallback: SourcedSetting[WaiverRules],
) -> SourcedSetting[WaiverRules]:
    if primary.value is None or fallback.value is None:
        return _choose_setting(primary, fallback)
    mechanism = (
        primary.value.claim_mechanism
        if primary.value.claim_mechanism is not None
        else fallback.value.claim_mechanism
    )
    faab_budget = primary.value.faab_budget
    if faab_budget is None and mechanism == "faab":
        faab_budget = fallback.value.faab_budget
    merged = WaiverRules(
        period_days=primary.value.period_days
        if primary.value.period_days is not None
        else fallback.value.period_days,
        processing_time_local=primary.value.processing_time_local
        if primary.value.processing_time_local is not None
        else fallback.value.processing_time_local,
        timezone=primary.value.timezone
        if primary.value.timezone is not None
        else fallback.value.timezone,
        claim_mechanism=mechanism,
        faab_budget=faab_budget,
    )
    return _merged_setting(primary, fallback, merged)


def _merge_games_caps(
    primary: SourcedSetting[GamesCapRules],
    fallback: SourcedSetting[GamesCapRules],
) -> SourcedSetting[GamesCapRules]:
    if primary.value is None or fallback.value is None:
        return _choose_setting(primary, fallback)
    keyed = {(cap.scope, cap.position): cap for cap in fallback.value.caps}
    keyed.update({(cap.scope, cap.position): cap for cap in primary.value.caps})
    merged = GamesCapRules(caps=tuple(keyed.values()))
    return _merged_setting(primary, fallback, merged)


def _merge_keepers(
    primary: SourcedSetting[KeeperRules],
    fallback: SourcedSetting[KeeperRules],
) -> SourcedSetting[KeeperRules]:
    if primary.value is None or fallback.value is None:
        return _choose_setting(primary, fallback)
    merged = KeeperRules(
        enabled=primary.value.enabled,
        max_keepers=primary.value.max_keepers
        if primary.value.max_keepers is not None
        else fallback.value.max_keepers,
        deadline_at=primary.value.deadline_at
        if primary.value.deadline_at is not None
        else fallback.value.deadline_at,
        provider_options={
            **fallback.value.provider_options,
            **primary.value.provider_options,
        },
    )
    return _merged_setting(primary, fallback, merged)


def _choose_setting[ValueT](
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
    return SourcedSetting(
        value=None,
        evidence=primary.evidence + fallback.evidence,
    )


def _bridge_setting[ValueT](
    value: ValueT | None,
    *,
    path: str,
    capture_ref: str,
) -> SourcedSetting[ValueT]:
    return SourcedSetting(
        value=value,
        evidence=(
            SettingEvidence(
                source=BRIDGE_SOURCE,
                status="observed" if value is not None else "absent",
                source_path=path,
                capture_ref=capture_ref,
            ),
        ),
    )


def _merged_setting[ValueT](
    primary: SourcedSetting[ValueT],
    fallback: SourcedSetting[ValueT],
    merged: ValueT,
) -> SourcedSetting[ValueT]:
    if merged == primary.value:
        return primary
    return SourcedSetting(
        value=merged,
        evidence=primary.evidence + fallback.evidence,
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


@dataclass(frozen=True)
class RawScoringCategory:
    """One scoring category exactly as ``scoringSystem`` reports it, pre-validation.

    Shared by this module (to populate ``LeagueSettingsDocument.scoring_categories``)
    and ``ingest/fantrax_official/parsers.py`` (to populate the adapter's own
    ``FantraxLeagueInfo.scoring_categories``) so the two callers can never
    silently drift into disagreeing about what a category's code, abbreviation
    or weight is -- there is exactly one place this payload shape is read.
    """

    code: str
    display_name: str | None
    abbreviation: str
    weight: float


def parse_scoring_category_configs(payload: dict[object, object]) -> list[RawScoringCategory] | None:
    """Extract per-category configs from ``scoringSystem.scoringCategorySettings``.

    Returns ``None`` when no such shape is present at all -- an absent
    observation, exactly like every other concern in this module. Once the
    shape *is* present, a category missing its stable ``code``, its
    ``shortName`` abbreviation, or a numeric ``weight`` fails closed with
    :class:`SourceContractError` rather than being silently dropped: a
    scoring profile missing one category (or unable to verify its weight) is
    a wrong valuation later with no way to detect it after the fact.

    Only this rich, verified shape is handled. An earlier version of the
    adapter also speculatively handled a flat top-level ``scoringCategories``
    list of strings/dicts -- that shape has never actually been observed live
    (the real payload nests a ``PLAYER``-keyed map under
    ``scoringSystem.scoringCategories`` instead, which is not the same
    thing), and an unverified alias for a payload shape that has never been
    seen is a guess wearing evidence's clothes. It has been removed rather
    than kept "just in case"; see docs/adapters/fantrax-official.md.
    """

    scoring_system = payload.get("scoringSystem")
    if not isinstance(scoring_system, dict):
        return None
    rich_settings = scoring_system.get("scoringCategorySettings")
    if not isinstance(rich_settings, list):
        return None

    raw: list[RawScoringCategory] = []
    for group in rich_settings:
        if not isinstance(group, dict):
            continue
        configs = group.get("configs")
        if not isinstance(configs, list):
            continue
        for config in configs:
            if not isinstance(config, dict):
                continue
            category = config.get("scoringCategory")
            if not isinstance(category, dict):
                continue
            code = category.get("code")
            if not isinstance(code, str) or not code:
                raise SourceContractError(
                    "scoringSystem.scoringCategorySettings[*].configs[*]"
                    ".scoringCategory.code must be a non-empty string",
                    source=OFFICIAL_SOURCE,
                    endpoint="getLeagueInfo",
                )
            abbreviation = category.get("shortName")
            if not isinstance(abbreviation, str) or not abbreviation:
                raise SourceContractError(
                    f"scoring category {code!r} has no shortName abbreviation",
                    source=OFFICIAL_SOURCE,
                    endpoint="getLeagueInfo",
                )
            weight = config.get("weight")
            if isinstance(weight, bool) or not isinstance(weight, int | float):
                raise SourceContractError(
                    f"scoring category {code!r} has no numeric weight",
                    source=OFFICIAL_SOURCE,
                    endpoint="getLeagueInfo",
                )
            name = category.get("name")
            raw.append(
                RawScoringCategory(
                    code=code,
                    display_name=name if isinstance(name, str) and name else None,
                    abbreviation=abbreviation,
                    weight=float(weight),
                )
            )
    return raw


def parse_scoring_type_raw(payload: dict[object, object]) -> str | None:
    """The scoring-format discriminator, verbatim -- a top-level ``scoringType``
    if present, else ``scoringSystem.type``. Never normalized here; see
    ``ScoringFormatRules``.
    """

    scoring_type = payload.get("scoringType")
    if isinstance(scoring_type, str) and scoring_type:
        return scoring_type
    scoring_system = payload.get("scoringSystem")
    if isinstance(scoring_system, dict):
        nested = scoring_system.get("type")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _parse_scoring_categories(
    payload: dict[object, object],
    *,
    capture_ref: str,
) -> SourcedSetting[ScoringCategoriesRules]:
    raw = parse_scoring_category_configs(payload)
    if raw is None:
        return _absent(capture_ref)
    categories = tuple(
        ScoringCategoryRule(
            code=item.code,
            display_name=item.display_name,
            abbreviation=item.abbreviation,
            weight=item.weight,
        )
        for item in raw
    )
    return SourcedSetting(
        value=ScoringCategoriesRules(categories=categories),
        evidence=(
            _observed(
                "$.scoringSystem.scoringCategorySettings[*].configs[*].scoringCategory",
                capture_ref,
            ),
        ),
    )


def _parse_scoring_type(
    payload: dict[object, object],
    *,
    capture_ref: str,
) -> SourcedSetting[ScoringFormatRules]:
    raw_type = parse_scoring_type_raw(payload)
    if raw_type is None:
        return _absent(capture_ref)
    return SourcedSetting(
        value=ScoringFormatRules(raw_type=raw_type),
        evidence=(_observed("$.scoringSystem.type", capture_ref),),
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
            for child in value:
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
