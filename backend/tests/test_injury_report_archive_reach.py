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

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from hoops_gm.db.models.enums import InjuryReportStatus
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.injury_report import parse_injury_report_pdf
from hoops_gm.ingest.injury_report.cohort_admissibility import outcome_keyed_field_paths

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

#: Seasons whose probed capture actually contains a `DOUBTFUL` designation.
#: 2025-26 is absent on purpose — see
#: `test_the_2025_26_probe_report_genuinely_has_no_doubtful`.
SEASONS_WITH_A_PROBED_DOUBTFUL = frozenset({"2023-24", "2024-25"})


def _parse(fixture_name: str, instant: datetime):  # type: ignore[no-untyped-def]
    return parse_injury_report_pdf(
        (FIXTURES / fixture_name).read_bytes(),
        report_timestamp=instant,
        source_url="https://example.invalid/fixture",
    )


def test_the_parametrised_sets_are_not_empty() -> None:
    """A parametrisation over an empty set collects nothing and passes vacuously.

    Added after a sibling lane found a test iterating `client.app.routes` — one
    lazy `_IncludedRouter`, so the loop ran zero times and every assertion about
    routes "passed". Same mechanism as reading `tipoff_utc` off a wrapper object
    and getting `None` 1,230 times: **a check that iterates must first assert it
    found something to iterate over.**

    Every other test in this file is parametrised over one of these two sets or
    reads `SUPPORTED_SEASONS` directly, so emptying either would silently delete
    coverage rather than fail. The counts are pinned rather than merely asserted
    non-empty, because dropping from three seasons to one is the realistic
    regression and `> 0` would not notice it.
    """
    assert len(SUPPORTED_SEASONS) == 3, sorted(SUPPORTED_SEASONS)
    assert len(SEASONS_WITH_A_PROBED_DOUBTFUL) == 2, sorted(SEASONS_WITH_A_PROBED_DOUBTFUL)
    assert set(SUPPORTED_SEASONS) > SEASONS_WITH_A_PROBED_DOUBTFUL
    for fixture_name, _ in SUPPORTED_SEASONS.values():
        assert (FIXTURES / fixture_name).exists(), fixture_name


def test_every_fixture_this_file_names_actually_parses_to_entries() -> None:
    """And the parsed results are non-empty, so no assertion runs over nothing.

    The status assertions below all count entries. A fixture that parsed to zero
    entries would make `Counter()[X] > 0` false rather than vacuous, so this is
    belt-and-braces — but the completeness test's `for` loop and the digest
    test's loop both iterate, and this pins that they have something to iterate.
    """
    for season, (fixture_name, instant) in sorted(SUPPORTED_SEASONS.items()):
        parsed = _parse(fixture_name, instant)
        assert len(parsed.entries) > 0, f"{season}: {fixture_name} parsed to zero entries"


@pytest.mark.parametrize("season", sorted(SUPPORTED_SEASONS))
def test_each_planned_sweep_season_still_parses(season: str) -> None:
    """A real report from every season the sweep will touch is readable."""
    fixture_name, instant = SUPPORTED_SEASONS[season]
    parsed = _parse(fixture_name, instant)
    assert parsed.player_entries, f"{season} fixture yielded no player entries"


@pytest.mark.parametrize("season", sorted(SUPPORTED_SEASONS))
def test_probable_is_present_in_every_planned_sweep_season(season: str) -> None:
    """`PROBABLE` exists in all three seasons — asserted from the PDF bytes.

    This is the claim the whole three-season plan rests on. Secondary sources
    state the NBA vocabulary is Out/Doubtful/Questionable/Available with no
    PROBABLE at all; if that were true, widening the cohort would fix
    `doubtful` and leave the conversion model unactivatable on `probable`
    instead.

    **It parses the committed fixture rather than reading a recorded count,
    and that distinction is the whole point of the test.** An earlier version
    asserted against `status_counts` in
    `nba-injury-report-archive-reach-probe.json` — a file this lane wrote.
    Review moved every fixture PDF out of the tree and it still passed, then
    deleted a `probable` key from the JSON while leaving the PDF untouched and
    it failed. It was a test of our own bookkeeping wearing the name of a test
    about the NBA.
    """
    fixture_name, instant = SUPPORTED_SEASONS[season]
    parsed = _parse(fixture_name, instant)
    statuses = Counter(entry.status for entry in parsed.entries)
    assert statuses[InjuryReportStatus.PROBABLE] > 0, (
        f"{season}: no PROBABLE designation in {fixture_name}"
    )


@pytest.mark.parametrize("season", sorted(SEASONS_WITH_A_PROBED_DOUBTFUL))
def test_doubtful_is_present_where_the_probe_actually_observed_it(season: str) -> None:
    """`DOUBTFUL` exists in 2023-24 and 2024-25 — from the PDF bytes, again.

    **Deliberately not all three seasons, and the reason is a correction.** The
    prose and an earlier docstring both claimed `PROBABLE` and `DOUBTFUL` were
    established for every planned sweep season. Only `PROBABLE` was ever
    asserted, and the `DOUBTFUL` half could not have been: the single 2025-26
    report this probe captured (2025-11-01) contains **zero** `doubtful`, so a
    three-season assertion would fail today.

    `DOUBTFUL` at these rates does not appear on every report, so absence in one
    capture is not evidence of absence in a season. The 2025-26 evidence for
    `doubtful` is the committed cohort manifest's 21 observations across four
    weeks, which is a different artifact under a different gate — so this test
    claims only the two seasons it can actually show.
    """
    fixture_name, instant = SUPPORTED_SEASONS[season]
    parsed = _parse(fixture_name, instant)
    statuses = Counter(entry.status for entry in parsed.entries)
    assert statuses[InjuryReportStatus.DOUBTFUL] > 0, (
        f"{season}: no DOUBTFUL designation in {fixture_name}"
    )


def test_the_2025_26_probe_report_genuinely_has_no_doubtful() -> None:
    """Pin the asymmetry above, so it cannot be quietly widened back.

    Without this, a later author sees two seasons asserted where three were
    described, assumes an oversight, and adds 2025-26 to the parametrisation.
    This states that the omission is a fact about the capture rather than a gap
    in the test, and it will fail if that ever stops being true — at which point
    widening the parametrisation is correct.
    """
    fixture_name, instant = SUPPORTED_SEASONS["2025-26"]
    parsed = _parse(fixture_name, instant)
    statuses = Counter(entry.status for entry in parsed.entries)
    assert statuses[InjuryReportStatus.DOUBTFUL] == 0
    assert statuses[InjuryReportStatus.PROBABLE] > 0


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


def test_the_recorded_probe_evidence_matches_every_committed_fixture() -> None:
    """Every fixture this file loads is traceable to a recorded live response.

    **The earlier version of this had a hole, and the reason given for it was
    false.** It skipped any fixture without a `committed_fixture` key, on the
    stated grounds that the 2025-11-01 capture predated the probe and so had no
    provenance record. It has one: the probe re-fetched that timestamp and
    recorded its SHA-256 like every other observation. The only thing missing
    was a key name, and a reviewer used the gap to truncate that fixture from
    seven pages to two with all nine tests here still green.

    So the match is now made on the **source URL**, which every observation
    carries, and any fixture that cannot be tied to a recorded response is a
    failure rather than a skip.
    """
    evidence = json.loads(PROBE_EVIDENCE.read_text(encoding="utf-8"))
    by_url = {observation["source_url"]: observation for observation in evidence["observations"]}

    expected = {name for name, _ in SUPPORTED_SEASONS.values()}
    expected.add(UNSUPPORTED_LAYOUT_FIXTURE)

    unverified: list[str] = []
    for fixture_name in sorted(expected):
        path = FIXTURES / fixture_name
        assert path.exists(), f"fixture missing: {fixture_name}"

        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        match = next(
            (obs for obs in by_url.values() if obs["sha256"] == digest),
            None,
        )
        if match is None:
            unverified.append(
                f"{fixture_name} (sha256 {digest[:16]}…) matches no recorded response"
            )

    assert not unverified, (
        "these committed fixtures have no recorded live provenance:\n  " + "\n  ".join(unverified)
    )


def test_every_committed_fixture_byte_matches_its_recorded_digest() -> None:
    """The digests are checked per fixture, so a swap cannot cancel out.

    The test above establishes that each fixture appears *somewhere* in the
    record. This one pins each fixture to the response recorded for its own
    URL, so exchanging two fixtures' bytes fails rather than satisfying the
    set-membership check twice.
    """
    evidence = json.loads(PROBE_EVIDENCE.read_text(encoding="utf-8"))
    by_fixture = {
        observation["committed_fixture"].rsplit("/", 1)[-1]: observation
        for observation in evidence["observations"]
        if "committed_fixture" in observation
    }
    # The 2025-11-01 capture predates this probe's fixture-recording pass, so it
    # carries no `committed_fixture` key. It is still recorded, by URL.
    by_fixture["nba_injury_report_2025-11-01_0530pm.pdf"] = next(
        obs
        for obs in evidence["observations"]
        if obs["source_url"].endswith("Injury-Report_2025-11-01_05PM.pdf")
    )

    expected = {name for name, _ in SUPPORTED_SEASONS.values()}
    expected.add(UNSUPPORTED_LAYOUT_FIXTURE)
    assert expected <= set(by_fixture), (
        f"no recorded response for: {sorted(expected - set(by_fixture))}"
    )

    for fixture_name in sorted(expected):
        digest = hashlib.sha256((FIXTURES / fixture_name).read_bytes()).hexdigest()
        assert digest == by_fixture[fixture_name]["sha256"], (
            f"{fixture_name} does not match the SHA-256 recorded at retrieval"
        )


def test_the_probe_evidence_publishes_designations_and_no_participation_outcome() -> None:
    """The probe artifact is on the pre-unblind disclosure surface. Pin what it carries.

    `TestTheDisclosureSurfaceIsClosed` in `test_cohort_admissibility.py` globs
    the whole `docs` tree, so this file was covered by the frozen §2 allow-list
    on the commit it landed, without anyone adding it. **That guard proves the
    absence and cannot prove the absence is meaningful.** A JSON that lost its
    `observations` array to a regeneration bug scans just as clean as one that
    correctly carries nothing.

    So the non-vacuity half is asserted here, beside the artifact it describes:
    the file does publish `status_counts`, and those are report *designations* —
    the model's input — rather than participation outcomes, its target. Keeping
    the two claims in one test is deliberate. Split apart, the negative half
    survives a change that empties the file and reads as reassurance.

    Recovered from a superseded sibling of the committed guard rather than
    landed alongside it: the sibling re-implemented the whole §2 scan with a
    staler allow-list, and two guards disagreeing about a frozen set is worse
    than one. This assertion was the only part of it not already covered.
    """
    document = json.loads(PROBE_EVIDENCE.read_text(encoding="utf-8"))

    outcome_keyed = outcome_keyed_field_paths(document, normalize_indices=True)
    assert outcome_keyed == frozenset(), sorted(outcome_keyed)

    observations = document["observations"]
    assert len(observations) >= len(SUPPORTED_SEASONS), len(observations)

    designations = {
        status for observation in observations for status in observation.get("status_counts", {})
    }
    assert {"out", "probable"} <= designations, sorted(designations)
    assert designations <= {status.value for status in InjuryReportStatus}, sorted(designations)
