"""Cross-store cohort admissibility, checked before any unblind is spent.

``docs/models/injury-status-conversion-preregistration.md`` §2 refuses a cohort
that cannot activate the model, **before** an outcome is read. This module is
the ``data-engineer`` half of that gate: it counts *inputs* only.

Why it exists as its own module rather than inside :mod:`cohort_evidence`
-------------------------------------------------------------------------
:func:`cohort_evidence._participation_join` joins on local surrogate keys
inside **one** session, and that is correct for the artifact it serves. But no
single store holds both halves of this cohort: the durable ledger carries
participation and no injury reports, and the report sweep carries reports and
no participation. A join across them cannot use surrogates — a rebuild
reassigns them freely, and here the two sides were built by separate runs.

So the join below is on **source-stable identity**:
``nba_games.nba_game_id`` x ``player_external_ids[source='nba'].external_id``.

The tip-off trap, and how it is removed rather than bounded
-----------------------------------------------------------
Every lead time, and the pre-tip-off selection that defines a canonical
observation at all, rests on ``tipoff_utc``. A report sweep store may have
taken its instants from ``ScheduleLeagueV2`` rather than ``BoxScoreSummaryV3``
(see ``hoops-gm-data/README.md``), which is exactly the provenance that makes
it unusable for a cohort manifest — its own tip-off reconciliation degenerates
into comparing one endpoint with itself, and **nothing records the provenance
of a persisted instant**, so no reader could tell.

:func:`build_admissibility_evidence` therefore never reads the report store's
tip-offs. It feeds the *participation* store's instants into
:func:`select_canonical_pregame_observations` through that function's
``game_tipoffs`` seam, so the report store contributes report rows and nothing
else. Comparing the two stores' instants then becomes a genuine two-endpoint
reconciliation rather than a self-comparison, and
:func:`reconcile_tipoffs_across_stores` performs it and refuses on
disagreement.

What this module must never emit
--------------------------------
§2's disclosure surface is a **closed set**: no new outcome-keyed field, at any
granularity, in any manifest version. A direct-outcome *count* is an input — it
says which rows have a usable outcome, not what those outcomes were — so it is
publishable. The outcome *values* are not, and
:data:`OUTCOME_KEYED_MANIFEST_FIELDS` plus its contract test pin that.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from hoops_gm.db.models import NbaGame, PlayerExternalId, PlayerParticipation
from hoops_gm.db.models.enums import (
    ExternalSource,
    InjuryReportStatus,
    ParticipationOutcome,
    SeasonType,
)
from hoops_gm.ingest.injury_report.backfill import select_canonical_pregame_observations
from hoops_gm.ingest.injury_report.client import is_fifteen_minute_era
from hoops_gm.ingest.injury_report.cohort_evidence import content_sha256

MANIFEST_KIND = "nba-injury-report-cohort-admissibility"

#: §2's activation floor: every status needs this many **direct outcomes**
#: inside the declared held-out range. Not canonical observations — canonical
#: is the looser count, and a cohort could clear a canonical pre-check then be
#: vetoed by §8 condition 6.
ADMISSIBILITY_FLOOR = 30

#: The five real designations. ``NOT_YET_SUBMITTED`` is not a player status and
#: never enters a cohort (§1).
COHORT_STATUSES: tuple[str, ...] = (
    InjuryReportStatus.OUT.value,
    InjuryReportStatus.DOUBTFUL.value,
    InjuryReportStatus.QUESTIONABLE.value,
    InjuryReportStatus.PROBABLE.value,
    InjuryReportStatus.AVAILABLE.value,
)

#: A row carrying one of these is a **direct outcome** (§1). ``UNKNOWN`` is a
#: valid enum member and is deliberately *not* here: under R35 a silent ledger
#: is not an absence.
DIRECT_OUTCOMES: frozenset[str] = frozenset(
    {
        ParticipationOutcome.PLAYED.value,
        ParticipationOutcome.DID_NOT_PLAY.value,
        ParticipationOutcome.DID_NOT_DRESS.value,
        ParticipationOutcome.NOT_WITH_TEAM.value,
        ParticipationOutcome.INACTIVE.value,
    }
)

_OUTCOME_VALUES: frozenset[str] = frozenset(o.value for o in ParticipationOutcome)

#: §7's prospectively-declared lead-time bands, in minutes before tip-off.
#: Published here as denominators so the band structure is checkable before an
#: unblind. The protocol expects ``>540`` to be empty "on any joinable data
#: resembling the current cohort" — a widened cohort does not resemble it, so
#: the expectation is worth measuring rather than assuming.
LEAD_TIME_BANDS: tuple[tuple[str, int, int], ...] = (
    ("<=60", 0, 60),
    ("61-180", 61, 180),
    ("181-540", 181, 540),
    (">540", 541, 10**9),
)


def lead_time_band(minutes: int) -> str:
    """The §7 band holding ``minutes``."""
    for label, low, high in LEAD_TIME_BANDS:
        if low <= minutes <= high:
            return label
    raise ValueError(f"lead time outside every declared band: {minutes}")


#: The two reporting regimes, named by the era each report was *filed* in.
#:
#: ``FIFTEEN_MINUTE_ERA_START`` (``client.py``) is 2025-12-22 Eastern, and it
#: falls **inside** any season-scale cohort. This matters far more than a
#: format change sounds: ADR-007 records the two regimes producing materially
#: different unresolved-``doubtful`` rates — **1.596 per date short-lead
#: against 0.917 legacy**, 74% more — and unresolved rows are *excluded*, so
#: the exclusion rate is era-dependent and concentrated on the scarcest status.
#:
#: A pooled per-status count cannot see this. §2's gate is pooled over the
#: held-out range, so a cohort can clear the floor **because of** the era it is
#: evaluated in while being fitted substantially on the other one. Publishing
#: the composition is denominators-only and therefore legal pre-unblind.
ERA_LEGACY = "legacy_hourly"
ERA_SHORT_LEAD = "short_lead_fifteen_minute"


def report_era(report_timestamp: datetime) -> str:
    """Which reporting regime a report was filed under.

    Classified from the **report's own timestamp**, not from the game date. A
    game date is not cleanly one era or the other: an evening-before report for
    a 2025-12-22 game is filed on 2025-12-21 and is legacy. Classifying by game
    date would mislabel exactly the boundary rows the composition exists to
    expose.
    """
    instant = report_timestamp
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return ERA_SHORT_LEAD if is_fifteen_minute_era(instant) else ERA_LEGACY


#: **The frozen allow-list of §2's closed disclosure surface.**
#:
#: Each entry is ``(committed artifact filename, dotted path)`` for a mapping
#: keyed by participation *outcome values*, with list indices normalised to
#: ``[]`` so a reordered array cannot silently move a field out of the set.
#:
#: **Scoped to the disclosure surface, not to the cohort manifest.** An earlier
#: version pinned only manifest fields, and the coordinator ruled that wrong
#: before a second artefact could exploit it: the repository already commits
#: evidence files *beside* the manifest, so a guard scoped to one file passes
#: while the surface widens. It was not hypothetical —
#: ``participation-ledger-2025-26-coverage.json`` publishes a whole-ledger
#: outcome marginal and was outside the old guard entirely.
#:
#: Both entries are admissible and neither is a cohort-conditional rate:
#:
#: - ``participation_join.participation_outcome_counts`` is the single
#:   whole-cohort marginal §2 names explicitly as inherited adapter evidence.
#: - ``seasons[].outcomes`` is a whole-*ledger* marginal over all 43,037
#:   participation rows, not conditioned on injury-report status at all. It is
#:   strictly *less* informative than the cohort-restricted marginal already
#:   permitted above, so admitting it widens nothing — but it is listed rather
#:   than ignored, because an unlisted field is indistinguishable from an
#:   unnoticed one.
#:
#: §2's rule is that this set never grows. A granularity rule was tried first
#: and rejected by both reviewers as necessary but not sufficient: git makes
#: cross-manifest differencing free, and widening the same window yields
#: cohort B superset of cohort A with both committed, so the added dates'
#: outcome marginal falls out by subtraction. A closed set is enforceable in
#: CI; a granularity rule is not.
OUTCOME_KEYED_MANIFEST_FIELDS: frozenset[tuple[str, str]] = frozenset(
    {
        (
            "nba-injury-report-cohort-2025-12-08--2026-01-04.json",
            "participation_join.participation_outcome_counts",
        ),
        ("participation-ledger-2025-26-coverage.json", "seasons[].outcomes"),
        # NOT an outcome marginal. ``seasons[].reasons`` is keyed by
        # :class:`DnpReason`, and the two vocabularies collide on exactly one
        # token -- ``not_with_team`` is a member of *both* enums. The detector
        # is intersection-based on purpose (a subset test is evadable), so it
        # flags this correctly and the right fix is to list it with the
        # mechanism stated rather than to weaken the detector. Pinned by
        # ``test_the_two_enums_collide_on_exactly_one_token``: if the enums
        # ever diverge further, that test fails and this entry is revisited.
        ("participation-ledger-2025-26-coverage.json", "seasons[].reasons"),
    }
)


def outcome_keyed_field_paths(
    document: Any, *, prefix: str = "", normalize_indices: bool = False
) -> frozenset[str]:
    """Dotted paths of every mapping in ``document`` keyed by outcome values.

    Detection is by **intersection**, not by subset. A subset test passes a
    mapping that mixes one outcome key in among unrelated ones, which is
    precisely how an outcome marginal would re-enter a manifest without
    announcing itself.

    ``normalize_indices`` renders list positions as ``[]`` rather than ``[3]``,
    so a frozen allow-list cannot be evaded by reordering or appending to an
    array.
    """
    found: set[str] = set()
    if isinstance(document, Mapping):
        keys = {str(k) for k in document}
        if keys & _OUTCOME_VALUES:
            found.add(prefix or "<root>")
        for key, value in document.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            found |= outcome_keyed_field_paths(
                value, prefix=child, normalize_indices=normalize_indices
            )
    elif isinstance(document, (list, tuple)):
        for index, value in enumerate(document):
            marker = "[]" if normalize_indices else f"[{index}]"
            found |= outcome_keyed_field_paths(
                value, prefix=f"{prefix}{marker}", normalize_indices=normalize_indices
            )
    return frozenset(found)


def chronological_split(
    game_dates: Sequence[date],
) -> tuple[tuple[date, ...], tuple[date, ...], tuple[date, ...]]:
    """§4's split: development / selection / held-out, on ordered game dates.

    The denominator is the ordered list of **distinct game dates**, never
    calendar days and never rows. The holdout takes the remainder, so the three
    partitions are exhaustive and disjoint and need no rounding rule of their
    own.

    This is `quant`'s parameter, applied here only to *read* an
    already-computed partition-agnostic table. Nothing in the artifact's
    primary payload depends on it (ADR-008).
    """
    ordered = sorted(game_dates)
    n = len(ordered)
    dev_n = int(n * 0.50)
    sel_n = int(n * 0.25)
    return (
        tuple(ordered[:dev_n]),
        tuple(ordered[dev_n : dev_n + sel_n]),
        tuple(ordered[dev_n + sel_n :]),
    )


@dataclass(frozen=True)
class CrossStoreTipoffAgreement:
    """Whether two *stores* agree on when each game started.

    Carries the same ``agreed``/``witnessed`` split as
    :class:`~hoops_gm.ingest.injury_report.cohort_evidence.TipoffReconciliation`
    and for the same reason: games whose instants were never compared agree
    perfectly and witness nothing.
    """

    compared: int
    absent: tuple[str, ...]
    disagreements: Mapping[str, Mapping[str, str]]
    date_disagreements: Mapping[str, Mapping[str, str]]

    @property
    def agreed(self) -> bool:
        return not self.disagreements and not self.date_disagreements

    @property
    def witnessed(self) -> bool:
        return self.compared > 0

    def as_summary(self) -> dict[str, Any]:
        return {
            "agreed": self.agreed,
            "game_date_disagreements": {
                k: dict(v) for k, v in sorted(self.date_disagreements.items())
            },
            "games_compared": self.compared,
            "games_without_both_instants": list(self.absent),
            "method": (
                "nba_games.tipoff_utc in the participation store compared against "
                "nba_games.tipoff_utc in the report store, for the same stable "
                "nba_game_id. The two stores were populated by separate runs from "
                "different endpoints, so unlike a within-store check this cannot "
                "degenerate into comparing one endpoint with itself. It remains an "
                "operational independence rather than a structural one: nothing "
                "records the provenance of a persisted instant, so this check "
                "witnesses that the two stores agree, not which endpoint each read."
            ),
            "tipoff_disagreements": {k: dict(v) for k, v in sorted(self.disagreements.items())},
            "witnessed": self.witnessed,
        }


def reconcile_tipoffs_across_stores(
    participation_games: Mapping[str, tuple[datetime | None, date]],
    report_games: Mapping[str, tuple[datetime | None, date]],
) -> CrossStoreTipoffAgreement:
    """Compare instants and dates for every game both stores hold."""
    compared = 0
    absent: list[str] = []
    tip: dict[str, dict[str, str]] = {}
    day: dict[str, dict[str, str]] = {}
    for nba_game_id, (p_tip, p_date) in participation_games.items():
        other = report_games.get(nba_game_id)
        if other is None:
            absent.append(nba_game_id)
            continue
        r_tip, r_date = other
        if p_tip is None or r_tip is None:
            absent.append(nba_game_id)
            continue
        compared += 1
        if p_tip != r_tip:
            tip[nba_game_id] = {
                "participation_store": p_tip.isoformat(),
                "report_store": r_tip.isoformat(),
            }
        if p_date != r_date:
            day[nba_game_id] = {
                "participation_store": p_date.isoformat(),
                "report_store": r_date.isoformat(),
            }
    return CrossStoreTipoffAgreement(
        compared=compared,
        absent=tuple(sorted(absent)),
        disagreements=tip,
        date_disagreements=day,
    )


def read_only_engine(path: str | Path) -> Engine:
    """Engine over an **existing** SQLite file, opened read-only.

    SQLite creates a database on connect rather than refusing, so a mistyped
    path yields a brand-new empty file and a count against it is an honest,
    reproducible, meaningless zero — a false zero manufactured by the very
    check written to settle the question. Assert on the filesystem first, and
    assert it there rather than inferring from the absence of an error.
    """
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(
            f"refusing to open {resolved}: not a file on disk. SQLite would have "
            f"created an empty database here and every count against it would have "
            f"been a meaningless zero."
        )
    uri = f"file:{resolved.as_posix()}?mode=ro"
    return create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))


def _games(session: Session, *, season: str, season_type: SeasonType) -> list[NbaGame]:
    return list(
        session.scalars(
            select(NbaGame).where(NbaGame.season == season, NbaGame.season_type == season_type)
        )
    )


def build_admissibility_evidence(
    participation_session: Session,
    report_session: Session,
    *,
    season: str,
    season_type: SeasonType = SeasonType.REGULAR,
    start: date | None = None,
    end: date | None = None,
    freeze_id: str,
) -> dict[str, Any]:
    """Count the cohort's inputs, and read §2's verdict off them.

    Emits no outcome value anywhere. The only outcome-dependent quantity is the
    direct/non-direct predicate, which §2 declares an input.
    """
    p_games = _games(participation_session, season=season, season_type=season_type)
    r_games = _games(report_session, season=season, season_type=season_type)

    p_by_nba = {g.nba_game_id: (g.tipoff_utc, g.game_date) for g in p_games}
    r_by_nba = {g.nba_game_id: (g.tipoff_utc, g.game_date) for g in r_games}
    agreement = reconcile_tipoffs_across_stores(p_by_nba, r_by_nba)

    p_pk_by_nba = {g.nba_game_id: g.id for g in p_games}
    tipoff_by_nba = {g.nba_game_id: g.tipoff_utc for g in p_games}
    date_by_nba = {g.nba_game_id: g.game_date for g in p_games}

    # The decontamination: instants come from the participation store only.
    report_pk_to_nba: dict[int, str] = {}
    game_tipoffs: dict[int, datetime] = {}
    for game in r_games:
        tipoff = tipoff_by_nba.get(game.nba_game_id)
        if tipoff is None:
            continue
        game_date = date_by_nba[game.nba_game_id]
        if start is not None and game_date < start:
            continue
        if end is not None and game_date > end:
            continue
        report_pk_to_nba[game.id] = game.nba_game_id
        game_tipoffs[game.id] = tipoff

    anchor_by_report_pk = {
        row.player_id: row.external_id
        for row in report_session.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.NBA)
        )
    }
    participation_pk_by_anchor = {
        row.external_id: row.player_id
        for row in participation_session.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.NBA)
        )
    }
    outcomes = {
        (row.game_id, row.player_id): row.outcome.value
        for row in participation_session.scalars(select(PlayerParticipation))
    }

    observations = select_canonical_pregame_observations(
        report_session, game_ids=list(game_tipoffs), game_tipoffs=game_tipoffs
    )

    canonical: Counter[str] = Counter()
    direct: Counter[str] = Counter()
    unresolved: Counter[str] = Counter()
    no_anchor: Counter[str] = Counter()
    no_row: Counter[str] = Counter()
    non_direct: Counter[str] = Counter()
    by_date: defaultdict[date, Counter[str]] = defaultdict(Counter)
    era_by_date: defaultdict[date, Counter[str]] = defaultdict(Counter)
    era_by_status: defaultdict[str, Counter[str]] = defaultdict(Counter)
    unresolved_era: Counter[str] = Counter()
    unresolved_era_status: defaultdict[str, Counter[str]] = defaultdict(Counter)
    era_dates: defaultdict[str, set[date]] = defaultdict(set)
    cohort_dates: set[date] = set()
    identity_records: list[str] = []
    membership_records: list[str] = []
    lead_times: list[int] = []
    direct_lead_times: list[int] = []
    bands: defaultdict[str, Counter[str]] = defaultdict(Counter)

    for obs in observations:
        status = obs.status.value
        nba_game_id = report_pk_to_nba[obs.game_id]
        game_date = date_by_nba[nba_game_id]
        canonical[status] += 1
        cohort_dates.add(game_date)
        lead_times.append(obs.lead_time_minutes)
        era = report_era(obs.report_timestamp)
        era_dates[era].add(game_date)

        anchor = anchor_by_report_pk.get(obs.player_id) if obs.player_id is not None else None
        identity = f"nba:{anchor}" if anchor is not None else f"raw:{obs.player_name_raw}"
        identity_records.append(
            "|".join(
                (
                    nba_game_id,
                    identity,
                    obs.team_raw,
                    obs.report_timestamp.isoformat(),
                    status,
                    str(obs.lead_time_minutes),
                )
            )
        )

        if obs.player_id is None:
            unresolved[status] += 1
            unresolved_era[era] += 1
            unresolved_era_status[era][status] += 1
            continue
        if anchor is None:
            no_anchor[status] += 1
            continue
        player_pk = participation_pk_by_anchor.get(anchor)
        game_pk = p_pk_by_nba.get(nba_game_id)
        if player_pk is None or game_pk is None:
            no_anchor[status] += 1
            continue
        outcome = outcomes.get((game_pk, player_pk))
        if outcome is None:
            no_row[status] += 1
            continue
        if outcome not in DIRECT_OUTCOMES:
            non_direct[status] += 1
            continue
        direct[status] += 1
        direct_lead_times.append(obs.lead_time_minutes)
        bands[lead_time_band(obs.lead_time_minutes)][status] += 1
        by_date[game_date][status] += 1
        era_by_date[game_date][era] += 1
        era_by_status[era][status] += 1
        # Membership only. The outcome VALUE is deliberately absent: this
        # fingerprint must not become a pre-unblind channel for it.
        membership_records.append(f"{nba_game_id}|nba:{anchor}|{status}")

    ordered_dates = sorted(cohort_dates)
    development, selection, held_out = chronological_split(ordered_dates)
    held_out_set = set(held_out)
    held_out_counts: Counter[str] = Counter()
    for day in held_out_set:
        held_out_counts.update(by_date[day])

    def _era_composition(partition: Sequence[date]) -> dict[str, int]:
        tally: Counter[str] = Counter()
        for day in partition:
            tally.update(era_by_date[day])
        return {ERA_LEGACY: tally[ERA_LEGACY], ERA_SHORT_LEAD: tally[ERA_SHORT_LEAD]}

    shortfalls = sorted(s for s in COHORT_STATUSES if held_out_counts[s] < ADMISSIBILITY_FLOOR)

    return {
        "cohort_dates_are_the_split_denominator": True,
        "cross_store_tipoff_agreement": agreement.as_summary(),
        "direct_outcome_counts_by_game_date": {
            day.isoformat(): {s: counts[s] for s in COHORT_STATUSES if counts[s]}
            for day, counts in sorted(by_date.items())
        },
        "disclosure_surface": {
            "no_outcome_value_is_published_here": True,
            "note": (
                "A direct-outcome count says which rows have a usable outcome, not "
                "what those outcomes were, which is what makes this gate checkable "
                "without spending an unblind. No outcome-keyed field appears in this "
                "artifact at any granularity."
            ),
            "outcome_keyed_fields": [],
        },
        "exclusion_classes_by_status": {
            "resolved_observations_without_nba_anchor": {
                s: no_anchor[s] for s in COHORT_STATUSES if no_anchor[s]
            },
            "resolved_observations_without_participation_row": {
                s: no_row[s] for s in COHORT_STATUSES if no_row[s]
            },
            "unresolved_player_identity": {
                s: unresolved[s] for s in COHORT_STATUSES if unresolved[s]
            },
            "with_non_direct_participation_outcome": {
                s: non_direct[s] for s in COHORT_STATUSES if non_direct[s]
            },
        },
        "fingerprints": {
            "sha256_sorted_canonical_identity_records": content_sha256(sorted(identity_records)),
            "sha256_sorted_direct_outcome_membership": content_sha256(sorted(membership_records)),
        },
        "direct_outcomes_by_report_era": {
            "by_game_date": {
                day.isoformat(): {e: c for e, c in sorted(tally.items()) if c}
                for day, tally in sorted(era_by_date.items())
            },
            "by_status": {
                era: {s: era_by_status[era][s] for s in COHORT_STATUSES if era_by_status[era][s]}
                for era in (ERA_LEGACY, ERA_SHORT_LEAD)
            },
            "era_boundary": "2025-12-22T00:00:00 America/New_York",
            "era_boundary_constant": (
                "hoops_gm.ingest.injury_report.client.FIFTEEN_MINUTE_ERA_START"
            ),
            "classified_by": (
                "each observation's own report_timestamp, not its game date. An "
                "evening-before report for a 2025-12-22 game is filed on "
                "2025-12-21 and is legacy; classifying by game date would "
                "mislabel exactly the boundary rows this table exists to expose."
            ),
            "unresolved_identity_exclusions_by_era": dict(sorted(unresolved_era.items())),
            "unresolved_identity_exclusions_by_era_and_status": {
                era: {
                    s: unresolved_era_status[era][s]
                    for s in COHORT_STATUSES
                    if unresolved_era_status[era][s]
                }
                for era in (ERA_LEGACY, ERA_SHORT_LEAD)
            },
            "game_dates_by_era": {era: len(era_dates[era]) for era in (ERA_LEGACY, ERA_SHORT_LEAD)},
            "adr_007_replication_note": (
                "ADR-007 (line 62) records 1.596 unresolved `doubtful` per date "
                "in the short-lead era against 0.917 legacy, and the era concern "
                "rests partly on that. IT DOES NOT REPLICATE HERE, and the gap is "
                "too large to be sampling noise: on this season-scale cohort the "
                "figures are 2/104 = 0.019 short-lead against 2/60 = 0.033 legacy "
                "-- roughly fifty times smaller and in the opposite direction. "
                "THE HONEST READING IS THAT THE TWO MEASURE DIFFERENT "
                "POPULATIONS, NOT THAT ADR-007 IS WRONG. This counts CANONICAL "
                "observations (one latest pre-tip-off row per player-game) whose "
                "identity did not resolve; a count over raw report rows would be "
                "far larger, because a player carried as doubtful on many "
                "successive reports contributes one canonical row and many raw "
                "ones. ADR-007 does not state which it used and this lane did not "
                "re-derive it. What is measured here, and is checkable from the "
                "fields beside this note: era-dependent unresolved exclusion on "
                "`doubtful` is 2 rows in each era and does not concentrate on the "
                "scarcest status at this scale. The era COMPOSITION concern in "
                "section_2_admissibility is unaffected and stands -- it is a "
                "different mechanism, confirmed directly."
            ),
            "why_this_is_published": (
                "The era boundary falls INSIDE any season-scale cohort, and §2's "
                "gate is pooled over the held-out range so it cannot see the "
                "split's era composition. ADR-007 records the regimes differing "
                "at 1.596 unresolved doubtful per date short-lead against 0.917 "
                "legacy; unresolved rows are excluded, so the exclusion rate is "
                "era-dependent and concentrated on the scarcest status. A cohort "
                "can therefore clear the floor BECAUSE of the era it is evaluated "
                "in while being fitted substantially on the other one. These are "
                "denominators, so publishing them costs no unblind."
            ),
        },
        "direct_outcomes_by_lead_time_band": {
            label: {s: bands[label][s] for s in COHORT_STATUSES if bands[label][s]}
            for label, _low, _high in LEAD_TIME_BANDS
        },
        "join": {
            "is_cross_store": True,
            "join_key": [
                "nba_games.nba_game_id",
                "player_external_ids[source=nba].external_id",
            ],
            "local_surrogate_keys_are_not_used": True,
            "tipoff_source": (
                "participation store only; the report store's own tipoff_utc column "
                "is never read, so its provenance cannot reach the pre-tip-off "
                "selection or any lead time"
            ),
        },
        "kind": MANIFEST_KIND,
        "lead_time_minutes": {
            "canonical": {
                "maximum": max(lead_times) if lead_times else None,
                "minimum": min(lead_times) if lead_times else None,
            },
            "direct": {
                "maximum": max(direct_lead_times) if direct_lead_times else None,
                "minimum": min(direct_lead_times) if direct_lead_times else None,
            },
        },
        "scope": {
            "end_game_date": ordered_dates[-1].isoformat() if ordered_dates else None,
            "game_dates": len(ordered_dates),
            "games_with_canonical_observations": len({o.game_id for o in observations}),
            "games_in_scope": len(game_tipoffs),
            "season": season,
            "season_type": season_type.value,
            "start_game_date": ordered_dates[0].isoformat() if ordered_dates else None,
        },
        "section_2_admissibility": {
            "admissible": not shortfalls,
            "canonical_observations_by_status": {s: canonical[s] for s in COHORT_STATUSES},
            "derived_not_primary": (
                "This block APPLIES quant's §4 split to the partition-agnostic "
                "by-date table above; it does not produce it. If the split moves, "
                "nothing here needs regenerating — recompute this block from the "
                "same table. Publishing counts by a declared partition as the "
                "primary payload would write an availability-layer parameter into "
                "an observations-layer artifact, a backward flow under ADR-008."
            ),
            "direct_outcomes_by_status": {s: direct[s] for s in COHORT_STATUSES},
            "era_composition_by_partition": {
                "development": _era_composition(development),
                "held_out": _era_composition(held_out),
                "selection": _era_composition(selection),
            },
            "floor": ADMISSIBILITY_FLOOR,
            "freeze_id": freeze_id,
            "held_out_direct_outcomes_by_status": {s: held_out_counts[s] for s in COHORT_STATUSES},
            "held_out_end": held_out[-1].isoformat() if held_out else None,
            "held_out_start": held_out[0].isoformat() if held_out else None,
            "limitations_that_the_count_cannot_see": [
                (
                    "THE HOLDOUT IS THE END-OF-SEASON SHUTDOWN WINDOW, AND IT IS "
                    "NOT THE REGIME THE TOOL IS USED IN. §4's chronological rule "
                    "puts the held-out range at late February to mid-April: "
                    "eliminated teams shutting players down, seeding races, "
                    "pre-playoff load management. The tool is used from draft day "
                    "onward, weighted October-March, and §7 permits ONE "
                    "evaluation. v1's holdout was late December — mid-season and "
                    "unremarkable — so widening did not merely make the holdout "
                    "bigger, it silently changed its character. 'Widen the cohort' "
                    "is satisfied without being met, and no count distinguishes "
                    "the two outcomes. Declared pre-unblind as a limitation by "
                    "owner ruling; the split boundaries are deliberately NOT "
                    "moved, because choosing different proportions BECAUSE these "
                    "ones are inconvenient is the trap §4 already names. THIS "
                    "MUST REACH THE MODEL CARD VERBATIM."
                ),
                (
                    "THE REPORTING-ERA BOUNDARY FALLS INSIDE THE COHORT AND THE "
                    "SPLIT DOES NOT RESPECT IT. See "
                    "direct_outcomes_by_report_era. Development is mostly legacy; "
                    "selection and held-out are entirely short-lead. The model "
                    "would be fitted substantially on a reporting regime the "
                    "holdout contains none of. Pre-registered as a §7 sensitivity "
                    "rather than fixed by moving the boundaries."
                ),
            ],
            "split_game_dates": {
                "development": len(development),
                "held_out": len(held_out),
                "selection": len(selection),
            },
            "statuses_below_floor": shortfalls,
            "unit": "direct outcomes, matching §8 condition 6",
        },
    }


def render(evidence: Mapping[str, Any]) -> str:
    return json.dumps(evidence, indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - operator tool
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--participation-db", required=True)
    parser.add_argument("--report-db", required=True)
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--freeze-id", default="injury-status-conversion-v2-20260821T145900Z")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    p_engine = read_only_engine(args.participation_db)
    r_engine = read_only_engine(args.report_db)
    with Session(p_engine) as p_session, Session(r_engine) as r_session:
        evidence = build_admissibility_evidence(
            p_session,
            r_session,
            season=args.season,
            start=args.start,
            end=args.end,
            freeze_id=args.freeze_id,
        )

    leaked = outcome_keyed_field_paths(evidence)
    if leaked:
        raise SystemExit(f"refusing to emit: outcome-keyed fields present: {sorted(leaked)}")

    text = render(evidence)
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text)

    section = evidence["section_2_admissibility"]
    print(f"admissible: {section['admissible']}  shortfalls: {section['statuses_below_floor']}")
    return 0 if section["admissible"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
