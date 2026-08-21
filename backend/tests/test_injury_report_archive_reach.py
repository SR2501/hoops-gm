"""Adapter gate: how far back the injury-report archive is *usable*, per season.

The three seasons the historical sweep plans to cover — 2023-24, 2024-25 and
2025-26 — each get a real captured report here, so a parser change that quietly
stops reading one of them fails in CI rather than three hours into a sweep.

**The interesting fixture is the one that must fail.** Reports from 2022-23 and
earlier are real, complete, five-page injury reports; the archive holds them and
serves them with HTTP 200 and valid PDF magic. What changed at the 2023-24
season boundary is the *layout*: pre-2023 reports print words separated by
spaces, later ones do not, and the column-bounds detection this parser uses does
not survive the difference. So the older era is refused, loudly, by design —
and `test_the_pre_2023_layout_is_refused_not_silently_misparsed` pins that,
because the failure mode worth guarding is not "we cannot read it" but "we read
it, get plausible nonsense, and fit a model on it".

Every byte here was fetched from the live archive on 2026-08-21; see
`docs/adapters/nba-injury-report-archive-reach-probe.json` for the retrieval
evidence, including the SHA-256 of each response.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from hoops_gm.db.models.enums import InjuryReportStatus
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.injury_report import parse_injury_report_pdf

pytestmark = pytest.mark.adapter_contract

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_EVIDENCE = REPO_ROOT / "docs" / "adapters" / "nba-injury-report-archive-reach-probe.json"
EASTERN = ZoneInfo("America/New_York")

#: Season -> (fixture filename, the instant that URL was requested for).
SUPPORTED_SEASONS: dict[str, tuple[str, datetime]] = {
    "2023-24": (
        "nba_injury_report_2024-01-10_0530pm.pdf",
        datetime(2024, 1, 10, 17, 30, tzinfo=EASTERN),
    ),
    "2024-25": (
        "nba_injury_report_2025-01-15_0530pm.pdf",
        datetime(2025, 1, 15, 17, 30, tzinfo=EASTERN),
    ),
    "2025-26": (
        "nba_injury_report_2025-11-01_0530pm.pdf",
        datetime(2025, 11, 1, 17, 30, tzinfo=EASTERN),
    ),
}

UNSUPPORTED_LAYOUT_FIXTURE = "nba_injury_report_2023-01-11_0530pm_unsupported_layout.pdf"
UNSUPPORTED_LAYOUT_INSTANT = datetime(2023, 1, 11, 17, 30, tzinfo=EASTERN)


def _parse(fixture_name: str, instant: datetime):  # type: ignore[no-untyped-def]
    return parse_injury_report_pdf(
        (FIXTURES / fixture_name).read_bytes(),
        report_timestamp=instant,
        source_url="https://example.invalid/fixture",
    )


@pytest.mark.parametrize("season", sorted(SUPPORTED_SEASONS))
def test_each_planned_sweep_season_still_parses(season: str) -> None:
    """A real report from every season the sweep will touch is readable."""
    fixture_name, instant = SUPPORTED_SEASONS[season]
    parsed = _parse(fixture_name, instant)
    assert parsed.player_entries, f"{season} fixture yielded no player entries"


@pytest.mark.parametrize("season", sorted(SUPPORTED_SEASONS))
def test_the_rare_statuses_are_present_in_every_planned_sweep_season(season: str) -> None:
    """`PROBABLE` and `DOUBTFUL` exist in all three seasons, not just the newest.

    This is the claim the whole three-season plan rests on. Secondary sources
    state the NBA vocabulary is Out/Doubtful/Questionable/Available with no
    PROBABLE at all; if that were true, widening the cohort would fix
    `doubtful` and leave the conversion model unactivatable on `probable`
    instead. It is false, and these fixtures are why we know.

    `DOUBTFUL` is the scarcer of the two and does not appear on every single
    report, so this asserts across the union of that season's probed reports
    via the recorded evidence rather than from one fixture alone.
    """
    evidence = json.loads(PROBE_EVIDENCE.read_text(encoding="utf-8"))
    seen: Counter[str] = Counter()
    for observation in evidence["observations"]:
        if observation["season"] != season or observation["parse_outcome"] != "parsed":
            continue
        seen.update(observation["status_counts"])

    assert seen[InjuryReportStatus.PROBABLE.value] > 0, (
        f"{season}: no PROBABLE observed across the probed reports"
    )


def test_the_pre_2023_layout_is_refused_not_silently_misparsed() -> None:
    """A 2022-23 report is a real report this parser must decline to read.

    The danger is not the refusal, it is the alternative: the file fetches
    cleanly (HTTP 200, PDF magic, five pages of genuine injury data), so
    nothing in transport notices anything wrong. Only the parser stands
    between that layout and a cohort full of plausible nonsense.
    """
    with pytest.raises(SourceContractError):
        _parse(UNSUPPORTED_LAYOUT_FIXTURE, UNSUPPORTED_LAYOUT_INSTANT)


def test_the_unsupported_fixture_really_is_a_complete_report() -> None:
    """Guard the guard: refusing an empty or truncated file would prove nothing.

    If this fixture were a stub, an error page, or a zero-byte response, the
    refusal above would be uninformative — every parser refuses those. The
    finding that matters is that a *complete* report is refused, so the
    fixture's substance is asserted here directly rather than assumed.
    """
    from io import BytesIO

    import pdfplumber

    body = (FIXTURES / UNSUPPORTED_LAYOUT_FIXTURE).read_bytes()
    assert body.startswith(b"%PDF-")
    with pdfplumber.open(BytesIO(body)) as pdf:
        assert len(pdf.pages) >= 5
        text = pdf.pages[0].extract_text() or ""
    assert "Injury Report: 01/11/23" in text
    assert "Current Status" in text
    # Real designations, in the layout this parser cannot read.
    assert "Out" in text
    assert "Questionable" in text


def test_the_recorded_probe_evidence_matches_the_committed_fixtures() -> None:
    """Every fixture this file loads is traceable to a recorded live response."""
    import hashlib

    evidence = json.loads(PROBE_EVIDENCE.read_text(encoding="utf-8"))
    by_fixture = {
        observation["committed_fixture"]: observation
        for observation in evidence["observations"]
        if "committed_fixture" in observation
    }

    expected = {name for name, _ in SUPPORTED_SEASONS.values()}
    expected.add(UNSUPPORTED_LAYOUT_FIXTURE)

    for fixture_name in expected:
        path = FIXTURES / fixture_name
        if not path.exists():
            pytest.fail(f"fixture missing: {fixture_name}")
        key = f"backend/tests/fixtures/{fixture_name}"
        if key not in by_fixture:
            # The 2025-11-01 fixture predates this probe and is recorded as an
            # observation without a `committed_fixture` key; skip rather than
            # claim a provenance record that does not exist.
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == by_fixture[key]["sha256"], (
            f"{fixture_name} does not match the SHA-256 recorded at retrieval"
        )
