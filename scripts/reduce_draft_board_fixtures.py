"""Reduce real Fantrax draft-room captures into the committed board fixtures.

## Why this exists in the repository

``backend/tests/fixtures/fantrax_draft_board_*.html`` each open with a comment
claiming to be *a reduction of a real capture, not an invention*. ADR-006 turns
on that distinction: a fixture built from someone's reading of a format proves
only that the parser agrees with the reading, whereas one recorded off the wire
can disagree with us. But the claim itself was, until this file existed, prose —
and prose about how an artifact was made is precisely the kind of assertion this
project keeps finding to be false after somebody cites it.

So the recipe is here. It does not run in CI and cannot: its input is 49
payloads from the owner's real league, held outside this repository because they
carry his team names, his leaguemates and his league id. What it gives is a
reproducible, auditable answer to "what exactly was changed" that does not
depend on trusting a comment.

## What it does and does not change

Kept byte-for-byte: every element, every class token, every Angular ``<!---->``
placeholder, the leading space inside ``<mark> 12-7</mark>``, and the nesting.
The parser's whole job is reading that structure, so altering it would make the
fixture prove something about a document Fantrax never served.

Removed, as chrome no element of the parse reads: everything outside the board
table and the chat aside; per-render attributes (``aria-describedby``,
``cdk-describedby-host``, ``mattooltip*``, ``anchorid``); and Angular CDK's
``role="tooltip"`` text nodes, which carry team names.

Replaced with placeholders: fantasy team names, player names, Fantrax scorer
ids, the league id, and pro-team slugs.

Deliberately **not** replaced: Fantrax's own ``Mock Drafter N`` placeholder for
a seat whose owner has not joined the room. It is not the owner's data, and
keeping it preserves a real behaviour the fixtures are used to test — a seat's
displayed name changes mid-session, so a name is a label and only the column
ordinal is a stable identity.

## Running it

There is no virtualenv in this checkout. From the repository root::

    python scripts/reduce_draft_board_fixtures.py --captures <path-to-captures>

``--captures`` is a directory of ``*.json`` bridge-payload envelopes. Nothing is
written unless every leak check passes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "backend" / "tests" / "fixtures"

HDR_ITEM = re.compile(r'<div class="league-draft-board__header__item[^"]*">.*?</h4></div>', re.S)
HDR_NAME = re.compile(r"<h4><span[^>]*>\s*(.*?)\s*</span>", re.S)
SCORER_NAME = re.compile(r'(<div class="scorer__info__name"><a[^>]*>)([^<]*)(</a>)')
HEADSHOT = re.compile(r"(headshots/[A-Za-z0-9]+/hs)([0-9A-Za-z#]+)(_)")
SPORTSTEAM = re.compile(r"(logos/sportsteam/[a-z]+/)([a-z0-9-]+)(_logo)")
PRO_TEAM_CODE = re.compile(
    r'(<span class="mat-mdc-tooltip-trigger[^"]*">\s*-\s*<!---->\s*)([A-Z]{2,4})(\s*</span>)'
)
CHAT_NAME = re.compile(r'(<div class="chat-message__name[^"]*">)(.*?)(</div>)', re.S)
CHAT_TEXT = re.compile(r'(<div class="chat-message__text[^"]*">)(.*?)(</div>)', re.S)
CDK_TOOLTIP = re.compile(r'<div id="cdk-describedby-message[^"]*" role="tooltip">.*?</div>', re.S)
NOISE_ATTR = re.compile(
    r"\s(?:aria-describedby|cdk-describedby-host|mattooltip|mattooltipshowdelay"
    r'|mattooltipposition|mattooltipclass|anchorid)="[^"]*"'
)
TITLE_ATTR = re.compile(r'\stitle="[^"]*"')
CHAT_COORDINATES = re.compile(r"drafted\s*-\s*\d+-\d+\s*\[\d+\]")
LEAGUE_ID_IN_URL = re.compile(r"/fantasy/league/([A-Za-z0-9]+)")
FANTRAX_PLACEHOLDER = re.compile(r"^Mock Drafter \d+$")

NEUTRAL_LEAGUE = "demoleague0000fx"
TRUNCATION_MARKER = "<!-- hoops-gm bridge: truncated at 250000 chars -->"
SHELL = (
    '<body class="theme--dark"><app-root ng-version="20.3.7" class="fx-layout">'
    '<app-league-draft class="draft ng-star-inserted">{inner}</app-league-draft>'
    "</app-root></body>"
)
HEADER_NOTE = """<!--
hoops-gm test fixture. THIS IS A REDUCTION OF A REAL CAPTURE, NOT AN INVENTION.

Source: a live 12-team, 18-round Fantrax snake draft room, captured by
userscript/src/capture.js on 2026-08-28 as a `{source}` snapshot. Reduced by
scripts/reduce_draft_board_fixtures.py, which documents exactly what it keeps
and what it replaces; the markup below is otherwise the Angular output Fantrax
served, unaltered in structure.

ADR-006 turns on this distinction. A fixture assembled from a reading of a
format can only ever confirm the reading. This one was recorded off the wire,
so it is able to disagree with us -- and it did: it is what established that
the board renders all 216 cells before a single pick is made.

What it still cannot prove is that a future Fantrax build looks like this one.
Nothing in the DOM announces its own version.

Ground truth, watched by the owner: {truth}
-->
"""


class Leak(RuntimeError):
    """An identifying value survived reduction. Nothing is written."""


def load_envelopes(captures: Path) -> dict[str, dict[str, object]]:
    envelopes: dict[str, dict[str, object]] = {}
    for path in sorted(captures.glob("*.json")):
        envelopes[path.name[:4]] = json.loads(path.read_text(encoding="utf-8"))
    if not envelopes:
        raise SystemExit(f"no *.json capture envelopes under {captures}")
    return envelopes


def header_names(html: str) -> list[str]:
    names = []
    for block in HDR_ITEM.findall(html):
        match = HDR_NAME.search(block)
        if match:
            names.append(match.group(1).strip())
    return names


def build_maps(envelopes: dict[str, dict[str, object]], anchor: str) -> dict[str, dict[str, str]]:
    """Placeholders for every identifying value, stable across all fixtures.

    Teams are numbered by their column in the *finished* board, so ``Seat 07
    Club`` really is column 7 wherever it appears.
    """
    ordered = header_names(str(envelopes[anchor]["body_raw"]))
    teams: set[str] = set()
    players: set[str] = set()
    ids: set[str] = set()
    slugs: set[str] = set()
    leagues: set[str] = set()
    for envelope in envelopes.values():
        raw = str(envelope["body_raw"])
        teams.update(header_names(raw))
        players.update(name.strip() for _, name, _ in SCORER_NAME.findall(raw) if name.strip())
        ids.update(value for _, value, _ in HEADSHOT.findall(raw))
        slugs.update(value for _, value, _ in SPORTSTEAM.findall(raw))
        leagues.update(LEAGUE_ID_IN_URL.findall(str(envelope.get("request_url", ""))))
    team_map = {name: f"Seat {i:02d} Club" for i, name in enumerate(ordered, start=1)}
    extras = sorted(
        name for name in teams if name not in team_map and not FANTRAX_PLACEHOLDER.match(name)
    )
    team_map.update({name: f"Other Club {i:02d}" for i, name in enumerate(extras, start=1)})
    return {
        "teams": team_map,
        "players": {
            name: (
                f"P. Player{i:03d}"
                if re.match(r"^[A-Z]\.\s", name)
                else f"Player{i:03d} Surname{i:03d}"
            )
            for i, name in enumerate(sorted(players), start=1)
        },
        "ids": {value: f"zz{i:03d}" for i, value in enumerate(sorted(ids), start=1)},
        "slugs": {
            value: f"club-{i:02d}-placeholder" for i, value in enumerate(sorted(slugs), start=1)
        },
        "leagues": dict.fromkeys(sorted(leagues), NEUTRAL_LEAGUE),
    }


def neutralise(html: str, maps: dict[str, dict[str, str]]) -> str:
    html = CDK_TOOLTIP.sub("", html)
    html = NOISE_ATTR.sub("", html)
    html = TITLE_ATTR.sub(' title=""', html)
    for real, placeholder in maps["leagues"].items():
        html = html.replace(real, placeholder)
    html = HEADSHOT.sub(
        lambda m: m.group(1) + maps["ids"].get(m.group(2), "zz000") + m.group(3), html
    )
    html = SPORTSTEAM.sub(
        lambda m: m.group(1) + maps["slugs"].get(m.group(2), "club-00-placeholder") + m.group(3),
        html,
    )
    html = SCORER_NAME.sub(
        lambda m: m.group(1) + maps["players"].get(m.group(2).strip(), "P. Player000") + m.group(3),
        html,
    )
    html = PRO_TEAM_CODE.sub(lambda m: m.group(1) + "ZZZ" + m.group(3), html)

    def replace_header(block: str) -> str:
        match = HDR_NAME.search(block)
        if match is None:
            return block
        real = match.group(1).strip()
        if real not in maps["teams"]:
            return block  # a Fantrax "Mock Drafter N" placeholder; kept on purpose
        return block.replace(real, maps["teams"][real], 1)

    html = HDR_ITEM.sub(lambda m: replace_header(m.group(0)), html)

    def replace_chat(match: re.Match[str]) -> str:
        # Keep the coordinates: "drafted - 16-4 [184]" is Fantrax's own
        # arithmetic and is what corroborates the parser's overall numbering
        # from outside the parser. Only the team is identifying.
        coordinates = CHAT_COORDINATES.search(match.group(2))
        label = f"Seat XX Club {coordinates.group(0)}" if coordinates else "Seat XX Club"
        return match.group(1) + label + match.group(3)

    html = CHAT_NAME.sub(replace_chat, html)
    return CHAT_TEXT.sub(lambda m: m.group(1) + "chat text removed" + m.group(3), html)


def assert_no_leak(html: str, label: str, maps: dict[str, dict[str, str]]) -> None:
    """Two checks, because neither alone is sufficient.

    Position-aware re-extraction is the primary one: pull the values back out
    of the reduced markup with the same expressions that found them, and
    require none to be real. A raw substring scan cannot do that job here —
    team-defence scorer names are two-letter pro-team codes such as ``NE``,
    which match inside unrelated words and report a leak that is not there.

    A substring scan still runs for the high-entropy values, where a false
    positive is impossible and a *missed position* would not be: a league id or
    a scorer id appearing somewhere these expressions do not look.
    """
    found: list[str] = []
    real_teams = set(maps["teams"])
    found += [
        f"player name {name!r}"
        for _, name, _ in SCORER_NAME.findall(html)
        if name.strip() in maps["players"]
    ]
    found += [f"team header {n!r}" for n in header_names(html) if n in real_teams]
    found += [f"scorer id {v}" for _, v, _ in HEADSHOT.findall(html) if v in maps["ids"]]
    found += [f"pro-team slug {v}" for _, v, _ in SPORTSTEAM.findall(html) if v in maps["slugs"]]
    found += [f"league id {v}" for v in maps["leagues"] if v in html]
    found += [
        f"team name {n!r} in free text"
        for n in real_teams
        if len(n) > 3 and re.search(rf"\b{re.escape(n)}\b", html)
    ]
    if found:
        raise Leak(f"{label}: {sorted(set(found))[:10]}")


def board_and_chat(raw: str, *, with_chat: bool) -> tuple[str, str]:
    start = raw.find("<league-draft-board-table")
    end = raw.find("</league-draft-board-table>")
    if start < 0 or end < 0:
        raise SystemExit("capture holds no closed <league-draft-board-table>")
    board = raw[start : end + len("</league-draft-board-table>")]
    if not with_chat:
        return board, ""
    aside = raw.find("<aside")
    if aside < 0:
        return board, ""
    chat = raw[aside:]
    if chat.endswith(TRUNCATION_MARKER):
        chat = chat[: -len(TRUNCATION_MARKER)]
    return board, chat[:60000]


def emit(
    name: str,
    envelope: dict[str, object],
    maps: dict[str, dict[str, str]],
    *,
    with_chat: bool,
    truth: str,
    cut: int | None = None,
) -> None:
    board, chat = board_and_chat(str(envelope["body_raw"]), with_chat=with_chat)
    inner = board + chat
    if cut is not None:
        # Reproduce capture.js exactly: slice at an arbitrary character and
        # append the marker. The cut lands mid-tag, which is why the marker is
        # not a parseable comment in real captures either.
        inner = inner[:cut] + TRUNCATION_MARKER
    html = neutralise(SHELL.format(inner=inner), maps)
    assert_no_leak(html, name, maps)
    document = HEADER_NOTE.format(source=envelope["source"], truth=truth) + html + "\n"
    (FIXTURE_DIR / name).write_text(document, encoding="utf-8", newline="\n")
    print(f"wrote {name}: {len(document):,} bytes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--captures",
        required=True,
        type=Path,
        help="directory of bridge-payload *.json envelopes, held outside this repository",
    )
    args = parser.parse_args()

    envelopes = load_envelopes(args.captures)
    maps = build_maps(envelopes, anchor="0049")
    print(
        f"placeholders: {len(maps['teams'])} teams, {len(maps['players'])} players, "
        f"{len(maps['ids'])} scorer ids, {len(maps['slugs'])} pro-team slugs"
    )

    emit(
        "fantrax_draft_board_predraft.html",
        envelopes["0008"],
        maps,
        with_chat=True,
        truth="the draft had not started; the 12x18 grid renders in full with zero picks made.",
    )
    emit(
        "fantrax_draft_board_early.html",
        envelopes["0017"],
        maps,
        with_chat=True,
        truth="7 picks made, all in round 1, seats 1 to 7.",
    )
    emit(
        "fantrax_draft_board_complete.html",
        envelopes["0049"],
        maps,
        with_chat=True,
        truth="the finished draft: 216 picks, 18 rounds x 12 teams, every cell filled.",
    )
    emit(
        "fantrax_draft_board_truncated.html",
        envelopes["0049"],
        maps,
        with_chat=False,
        truth=(
            "the same finished 216-pick draft, cut mid-grid to reproduce capture.js's "
            "AUTO_SNAPSHOT_MAX_CHARS truncation. A parser must refuse this rather than "
            "report the picks that happened to survive the cut."
        ),
        cut=120000,
    )

    raw = str(envelopes["0007"]["body_raw"])
    start = raw.find("<app-league-home")
    stub = raw[start : start + 1500]
    stub = stub[: stub.rfind("><") + 1] + "</app-league-home>"
    html = neutralise(SHELL.format(inner=stub), maps)
    assert_no_leak(html, "fantrax_draft_board_absent.html", maps)
    (FIXTURE_DIR / "fantrax_draft_board_absent.html").write_text(
        HEADER_NOTE.format(
            source=envelopes["0007"]["source"],
            truth=(
                "not the draft room at all: the league home page. There is no board "
                "element, which is a different fact from a board holding zero picks."
            ),
        )
        + html
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("wrote fantrax_draft_board_absent.html")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Leak as leak:
        print(f"REFUSED, nothing written -- {leak}", file=sys.stderr)
        sys.exit(2)
