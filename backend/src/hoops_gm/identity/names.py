"""Name normalisation — the foundation of the crosswalk, and therefore of R7.

Every cross-source player match in this project is inferred from a name,
because **no shared identifier exists**. Verified live on 2026-08-17: Fantrax's
``getPlayerIds`` exposes ``statsIncId``, ``rotowireId`` and ``sportRadarId``,
and NBA.com exposes none of them. There is no anchor pair. That makes this
module load-bearing in a way a string utility normally is not.

What normalisation has to survive, all observed in the real payloads:

``"Last, First"`` versus ``"First Last"``
    Fantrax writes ``"Jokic, Nikola"``. ``nba_api``'s ``CommonAllPlayers``
    happens to offer ``DISPLAY_LAST_COMMA_FIRST`` in exactly that form, which
    is a convenience, not a contract — the box-score endpoints give
    ``firstName``/``familyName`` separately and the game logs give
    ``"James Harden"``. So both forms have to normalise to the same key.

Diacritics
    ``Jokić`` and ``Jokic``, ``Dončić`` and ``Doncic``, ``Šengün`` and
    ``Sengun``. Sources disagree per endpoint, not just per source.

Suffixes and punctuation
    ``Jaren Jackson Jr.`` / ``Jaren Jackson Jr`` / ``Jaren Jackson``.
    ``Scotty Pippen Jr.``. ``DaRon Holmes II``. ``Shaquille O'Neal``.
    ``Karl-Anthony Towns``. ``Nickeil Alexander-Walker``.

**Suffixes are stripped into a separate field, not discarded.** Ignoring them
merges a father and son; keeping them in the key means one source's ``Jr.``
blocks a match. Holding them apart lets the resolver use a suffix disagreement
as evidence rather than as a hard failure.

Nothing here decides a match. It produces comparable keys and leaves the
judgement — with its confidence and its recorded method — to the resolver.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

#: Generational suffixes, lower-cased and stripped of punctuation. Roman
#: numerals stop at V deliberately: beyond that they collide with real names
#: far more often than they appear as suffixes.
SUFFIXES: Final[frozenset[str]] = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})

#: Honorifics that occasionally survive into a feed and never disambiguate.
_NOISE: Final[frozenset[str]] = frozenset({"mr", "dr"})

_NON_NAME = re.compile(r"[^a-z\s]")
_WHITESPACE = re.compile(r"\s+")


def strip_accents(value: str) -> str:
    """Fold diacritics to their ASCII base characters.

    NFKD then drop combining marks. ``ø`` and ``ß`` have no combining form and
    survive this untouched, which is why the caller must not assume the result
    is pure ASCII — the subsequent character filter is what guarantees that.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


@dataclass(frozen=True)
class NormalizedName:
    """A name reduced to comparable parts, with the evidence kept separate."""

    #: Lower-cased, accent-folded, punctuation-free ``"first last"``. The
    #: matching key.
    key: str
    first: str
    last: str
    #: Generational suffix, lower-cased and without punctuation, or ``""``.
    suffix: str
    #: The string exactly as it arrived, never modified.
    raw: str

    @property
    def key_with_suffix(self) -> str:
        """The key including the suffix, for distinguishing father from son."""
        return f"{self.key} {self.suffix}".strip()

    @property
    def last_first_initial(self) -> str:
        """``"last f"`` — a deliberately weaker key for blocking candidates.

        Used to narrow the comparison set before scoring, never to accept a
        match on its own.
        """
        initial = self.first[:1]
        return f"{self.last} {initial}".strip()


def _clean_tokens(value: str) -> list[str]:
    folded = strip_accents(value).lower()
    # Apostrophes close up (``o'neal`` -> ``oneal``) while hyphens and periods
    # become separators, because ``karl-anthony`` is two tokens and ``o'neal``
    # is one word. Doing both with a single rule gets one of them wrong.
    folded = folded.replace("'", "").replace("\u2019", "")
    folded = _NON_NAME.sub(" ", folded)
    return [tok for tok in _WHITESPACE.split(folded) if tok]


def normalize_name(raw: str) -> NormalizedName:
    """Normalise a player name in either ``"Last, First"`` or ``"First Last"``.

    The comma is the only reliable signal of ordering, and it is trusted when
    present. Without one, the first token is taken as the given name — which is
    correct for every feed observed and is why ``external_name`` is retained on
    every crosswalk row: when this guess is wrong, the evidence is still there.
    """
    text = (raw or "").strip()
    if not text:
        return NormalizedName(key="", first="", last="", suffix="", raw=raw or "")

    if "," in text:
        family_part, _, given_part = text.partition(",")
        family_tokens = _clean_tokens(family_part)
        given_tokens = _clean_tokens(given_part)
        # The suffix turns up in three places, all of them real:
        # "Holmes II, DaRon" puts it on the family side, "Jokic, Nikola Jr."
        # trails it on the given side, and "Udeh, Jr., Ernest" — a genuine row
        # from CommonAllPlayers — puts it *between* the two commas, where
        # partitioning on the first comma leaves it leading the given part.
        # Missing that last one produced the key "jr ernest udeh", which
        # matches nothing.
        suffix, family_tokens = _strip_suffix(family_tokens)
        given_suffix, given_tokens = _strip_suffix(given_tokens)
        suffix = suffix or given_suffix
    else:
        tokens = _clean_tokens(text)
        suffix, tokens = _strip_suffix(tokens)
        given_tokens = tokens[:1]
        family_tokens = tokens[1:] or tokens[:1]
        if len(tokens) == 1:
            given_tokens = []
            family_tokens = tokens

    given_tokens = [t for t in given_tokens if t not in _NOISE]
    family_tokens = [t for t in family_tokens if t not in _NOISE]

    first = " ".join(given_tokens)
    last = " ".join(family_tokens)
    key = _WHITESPACE.sub(" ", f"{first} {last}").strip()
    return NormalizedName(key=key, first=first, last=last, suffix=suffix, raw=raw)


def _strip_suffix(tokens: list[str]) -> tuple[str, list[str]]:
    """Peel a generational suffix off either end of a token list.

    Both ends, because ``"Udeh, Jr., Ernest"`` leads with it while
    ``"Ernest Udeh Jr."`` trails it. Never when it is the only token: ``"V"``
    alone is a name fragment, not a suffix, and a single-token part that looks
    like a suffix is far more likely to be a surname we would otherwise delete.
    """
    if len(tokens) < 2:
        return "", tokens
    if tokens[-1] in SUFFIXES:
        return tokens[-1], tokens[:-1]
    if tokens[0] in SUFFIXES:
        return tokens[0], tokens[1:]
    return "", tokens


def normalize_key(raw: str) -> str:
    """Shorthand for ``normalize_name(raw).key``."""
    return normalize_name(raw).key


def normalize_team_abbreviation(raw: str | None) -> str:
    """Fold a team abbreviation to a comparable form.

    Fantrax and NBA.com disagree on several: Fantrax writes ``NO``, ``NY``,
    ``SA``, ``GS``, ``PHO`` and ``UTAH`` where NBA.com writes ``NOP``,
    ``NYK``, ``SAS``, ``GSW``, ``PHX`` and ``UTA``. Left unmapped, the team
    component of a match disagrees for six franchises — a fifth of the league —
    and the resolver would score correct matches down for no reason.

    Fantrax also writes ``"(N/A)"`` for a player with no current team, which is
    the majority of its payload (1,206 of 1,788 rows on 2026-08-17). That maps
    to ``""``: *unknown*, which the resolver must treat as absence of evidence
    rather than as evidence of disagreement.
    """
    if not raw:
        return ""
    text = raw.strip().upper()
    if text in {"(N/A)", "N/A", "NA", "FA", "-", "--", "TOT"}:
        return ""
    return _TEAM_ALIASES.get(text, text)


#: Non-NBA.com abbreviations seen in the wild, mapped to the NBA.com form.
_TEAM_ALIASES: Final[dict[str, str]] = {
    "NO": "NOP",
    "NOR": "NOP",
    "NY": "NYK",
    "NYC": "NYK",
    "SA": "SAS",
    "SAN": "SAS",
    "GS": "GSW",
    "GST": "GSW",
    "PHO": "PHX",
    "PHE": "PHX",
    "UTAH": "UTA",
    "UTH": "UTA",
    "WSH": "WAS",
    "WSB": "WAS",
    "BKN": "BKN",
    "BRK": "BKN",
    "CHA": "CHA",
    "CHO": "CHA",
    "LA": "LAL",
}

#: Fantrax positional labels that are not positions. ``"Tm"`` marks a team
#: entity masquerading as a player (risk R24); ``"Default"`` appears on rows
#: with no positional data at all.
NON_PLAYER_POSITIONS: Final[frozenset[str]] = frozenset({"Tm", "Team"})


def normalize_positions(raw: str | None) -> frozenset[str]:
    """Split a positional label into a set of comparable single positions.

    Sources disagree on granularity as well as spelling: Fantrax says ``PG``
    where a box score says ``G`` and a season row says ``Guard``. Comparing a
    set of coarse positions is the only comparison that is meaningful across
    all three, so ``PG`` and ``G`` both reduce to ``{"G"}`` and a match on
    position means "not contradictory" rather than "identical".
    """
    if not raw:
        return frozenset()
    text = raw.strip().upper()
    if not text:
        return frozenset()
    out: set[str] = set()
    for part in re.split(r"[/,\-\s]+", text):
        if not part:
            continue
        coarse = _POSITION_COARSE.get(part)
        if coarse:
            out.add(coarse)
    return frozenset(out)


_POSITION_COARSE: Final[dict[str, str]] = {
    "PG": "G",
    "SG": "G",
    "G": "G",
    "GUARD": "G",
    "SF": "F",
    "PF": "F",
    "F": "F",
    "FORWARD": "F",
    "C": "C",
    "CENTER": "C",
}
