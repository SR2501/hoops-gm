"""Parsing a projection CSV against a column-mapping profile.

Pure and offline: nothing here touches a database or a network, which is what
keeps the profiles' contract tests instant and keeps this module reusable
from a script, a test, or a future API endpoint without dragging a session
along. Identity *resolution* — matching a parsed name against the canonical
player crosswalk — is a separate step in ``importer.py``; this module only
turns bytes into validated, per-game-rate rows.

Every fatal validation failure is scoped to its own row. One bad number does
not lose the rest of the file — the same "one broken payload does not
brick a whole backfill" principle ``ingest/backfill.py`` applies to a
multi-thousand-request run, scaled down to a single CSV.
"""

from __future__ import annotations

import csv
import io
import math

from hoops_gm.identity.names import normalize_name
from hoops_gm.ingest.projections.models import (
    ProjectionParseResult,
    ProjectionSourceRow,
    RowIssue,
    build_raw_row,
)
from hoops_gm.ingest.projections.profiles import (
    SHOOTING_PAIRS,
    TERMINAL_HEADER_ALIASES,
    ColumnProfile,
    StatColumn,
    ValueShape,
    normalize_header,
    resolve_header,
)

__all__ = ["ProjectionProfileError", "parse_projection_csv"]

#: Tolerance for float comparisons (makes vs. attempts, GP sanity). CSV values
#: are frequently rounded to one decimal place upstream; comparing exactly
#: would flag "8.0 made, 7.95 attempted" as impossible when it is a rounding
#: artefact, not a real inconsistency.
_EPSILON = 1e-6

#: Games-played sanity bound. Generous enough to cover a full 82-game season
#: plus play-in and playoffs without inventing a games-played ceiling that
#: differs by source; this is a data-quality gate against a mis-mapped
#: column (a minutes total read as games played), not a claim about the
#: regular-season schedule length.
_MAX_PLAUSIBLE_GAMES = 100.0

_PERCENTAGE_CATEGORY_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("field_goals_made_per_game", "field_goals_attempted_per_game", "field goal"),
    ("free_throws_made_per_game", "free_throws_attempted_per_game", "free throw"),
)


class ProjectionProfileError(ValueError):
    """The file's headers do not match the profile at all.

    Raised only when the file cannot be read under this profile in
    principle — no column matches the name aliases, or the file has no
    header row. A missing *stat* column is not this: most sources omit some
    categories, and a profile is allowed to under-match without the whole
    import failing. Missing the identity columns is different, because
    without a name there is nothing to resolve or to import.
    """


def _parse_float(raw: str) -> float | None:
    text = raw.strip()
    if not text:
        return None
    value = float(text.replace(",", ""))
    if not math.isfinite(value):
        raise ValueError(f"non-finite numeric value {text!r}")
    return value


def _label_for(field_name: str) -> str:
    return field_name.replace("_per_game", "").replace("_", " ")


def parse_projection_csv(
    csv_text: str, profile: ColumnProfile, *, season: str
) -> ProjectionParseResult:
    """Parse ``csv_text`` under ``profile`` into validated per-game-rate rows.

    ``season`` is accepted but not stored on the row; profile verification
    scope is enforced by the DB-writing importer.
    """
    del season
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = list(reader.fieldnames or [])
    if not fieldnames:
        raise ProjectionProfileError("file has no header row")
    _reject_duplicate_normalized_headers(fieldnames)
    if profile.expected_headers and tuple(fieldnames) != profile.expected_headers:
        raise ProjectionProfileError(
            f"{profile.display_name} CSV header names/order drifted from profile "
            f"{profile.profile_id!r} version {profile.version!r}"
        )

    name_header = resolve_header(fieldnames, profile.name_aliases)
    external_id_header = resolve_header(fieldnames, profile.external_id_aliases)
    first_name_header = resolve_header(fieldnames, profile.first_name_aliases)
    last_name_header = resolve_header(fieldnames, profile.last_name_aliases)
    if name_header is None and (first_name_header is None or last_name_header is None):
        raise ProjectionProfileError(
            f"{profile.display_name} file has neither a recognized full-name column nor "
            "both recognized first/last-name columns; wrong profile, or source drift"
        )
    team_header = resolve_header(fieldnames, profile.team_aliases)
    position_header = resolve_header(fieldnames, profile.position_aliases)
    games_played_header = resolve_header(fieldnames, profile.games_played_aliases)

    stat_headers: dict[str, str] = {}
    for stat_column in profile.stat_columns:
        header = resolve_header(fieldnames, stat_column.aliases)
        if header is not None:
            stat_headers[stat_column.field] = header
    derived_fields = {derived.field for derived in profile.derived_stat_columns}
    missing_required = [
        field
        for field in profile.required_production_fields
        if field not in stat_headers and field not in derived_fields
    ]
    if missing_required:
        raise ProjectionProfileError(
            f"{profile.display_name} file is missing required production columns "
            f"{missing_required}; the source schema changed or the wrong profile was selected"
        )
    if not stat_headers:
        raise ProjectionProfileError(
            f"{profile.display_name} file has no recognized production columns; "
            "refusing to create all-null projections"
        )

    percentage_headers: dict[str, str] = {}
    for made_field, aliases in profile.percentage_fallback_aliases.items():
        header = resolve_header(fieldnames, aliases)
        if header is not None:
            percentage_headers[made_field] = header

    resolved_headers: dict[str, str] = {}
    if name_header:
        resolved_headers["player_name"] = name_header
    else:
        if first_name_header is None or last_name_header is None:
            raise AssertionError("component name headers were validated above")
        resolved_headers["player_first_name"] = first_name_header
        resolved_headers["player_last_name"] = last_name_header
    if external_id_header:
        resolved_headers["source_player_id"] = external_id_header
    if team_header:
        resolved_headers["team"] = team_header
    if position_header:
        resolved_headers["position"] = position_header
    if games_played_header:
        resolved_headers["assumed_games_played"] = games_played_header
    resolved_headers.update(stat_headers)

    terminal_aliases = {normalize_header(alias) for alias in TERMINAL_HEADER_ALIASES}
    ignored_terminal_headers = [
        header for header in fieldnames if normalize_header(header) in terminal_aliases
    ]
    ignored_source_headers = [
        header for header in fieldnames if header in profile.ignored_source_headers
    ]
    result = ProjectionParseResult(
        resolved_headers=resolved_headers,
        resolved_percentage_headers=percentage_headers,
        ignored_terminal_headers=ignored_terminal_headers,
        ignored_source_headers=ignored_source_headers,
    )

    candidates: list[tuple[ProjectionSourceRow, bool]] = []  # (row, fatal)

    for row_number, raw in enumerate(reader, start=2):
        try:
            raw_row = build_raw_row(fieldnames, raw)
        except ValueError as exc:
            result.total_rows += 1
            result.issues.append(RowIssue(row_number, None, str(exc), fatal=True))
            continue
        if not any(value.strip() for value in raw_row.values()):
            continue  # a fully blank trailing line is not a data row at all

        result.total_rows += 1
        row_fatal = False

        if name_header:
            name = (raw.get(name_header) or "").strip()
        else:
            first_name = (raw.get(first_name_header) or "").strip() if first_name_header else ""
            last_name = (raw.get(last_name_header) or "").strip() if last_name_header else ""
            name = " ".join(part for part in (first_name, last_name) if part)
        if not name:
            result.issues.append(
                RowIssue(row_number, "player_name", "missing player name", fatal=True)
            )
            row_fatal = True
        source_player_id = (
            (raw.get(external_id_header) or "").strip() if external_id_header else None
        )
        if external_id_header and not source_player_id:
            result.issues.append(
                RowIssue(
                    row_number,
                    "source_player_id",
                    "missing source player id",
                    fatal=True,
                )
            )
            row_fatal = True

        team = (raw.get(team_header) or "").strip() or None if team_header else None
        position = (raw.get(position_header) or "").strip() or None if position_header else None

        assumed_games_played: float | None = None
        assumed_games_played_raw: str | None = None
        if games_played_header:
            raw_gp = (raw.get(games_played_header) or "").strip()
            if raw_gp:
                assumed_games_played_raw = raw_gp
                try:
                    assumed_games_played = _parse_float(raw_gp)
                except ValueError as exc:
                    result.issues.append(
                        RowIssue(
                            row_number,
                            games_played_header,
                            f"unparsable games-played value {raw_gp!r}: {exc}",
                            fatal=True,
                        )
                    )
                    row_fatal = True
                else:
                    if assumed_games_played is not None and not (
                        0 <= assumed_games_played <= _MAX_PLAUSIBLE_GAMES
                    ):
                        result.issues.append(
                            RowIssue(
                                row_number,
                                games_played_header,
                                f"games-played value {assumed_games_played} outside the "
                                f"plausible range 0-{_MAX_PLAUSIBLE_GAMES:.0f}",
                                fatal=True,
                            )
                        )
                        row_fatal = True

        values: dict[str, float | None] = {}
        for stat_column in profile.stat_columns:
            header = stat_headers.get(stat_column.field)
            if header is None:
                values[stat_column.field] = None
                continue
            raw_value = raw.get(header) or ""
            parsed = _parse_stat_value(
                raw_value,
                stat_column=stat_column,
                assumed_games_played=assumed_games_played,
                row_number=row_number,
                header=header,
                issues=result.issues,
            )
            if isinstance(parsed, _Fatal):
                row_fatal = True
                values[stat_column.field] = None
            else:
                values[stat_column.field] = parsed

        if _derive_stat_values(
            values=values,
            profile=profile,
            row_number=row_number,
            issues=result.issues,
        ):
            row_fatal = True

        _enforce_percentage_decomposability(
            values=values,
            percentage_headers=percentage_headers,
            raw=raw,
            row_number=row_number,
            issues=result.issues,
        )
        if _check_shooting_consistency(values=values, row_number=row_number, issues=result.issues):
            row_fatal = True
        missing_required_values = [
            field for field in profile.required_production_fields if values.get(field) is None
        ]
        if missing_required_values:
            result.issues.append(
                RowIssue(
                    row_number,
                    None,
                    f"row is missing required production values {missing_required_values}",
                    fatal=True,
                )
            )
            row_fatal = True
        if not any(value is not None for value in values.values()):
            result.issues.append(
                RowIssue(
                    row_number,
                    None,
                    "row has no usable production rates; refusing an all-null projection",
                    fatal=True,
                )
            )
            row_fatal = True

        source_row = ProjectionSourceRow(
            row_number=row_number,
            player_name=name,
            source_player_id=source_player_id,
            team=team,
            position=position,
            assumed_games_played=assumed_games_played,
            assumed_games_played_raw=assumed_games_played_raw,
            raw_row=raw_row,
            **values,
        )
        candidates.append((source_row, row_fatal))

    _reject_duplicate_names(candidates, result.issues)
    _reject_duplicate_source_ids(candidates, result.issues)

    result.rows = [row for row, fatal in candidates if not fatal]
    if not result.rows:
        reasons = "; ".join(issue.message for issue in result.fatal_issues[:3])
        raise ProjectionProfileError(
            "file contains no usable projection rows" + (f": {reasons}" if reasons else "")
        )
    return result


def _reject_duplicate_normalized_headers(fieldnames: list[str]) -> None:
    by_normalized: dict[str, list[str]] = {}
    for header in fieldnames:
        by_normalized.setdefault(normalize_header(header), []).append(header)
    duplicates = [headers for headers in by_normalized.values() if len(headers) > 1]
    if duplicates:
        rendered = ", ".join(repr(headers) for headers in duplicates)
        raise ProjectionProfileError(
            f"duplicate CSV headers after normalization: {rendered}; "
            "column mapping would be ambiguous"
        )


class _Fatal:
    """Sentinel type distinguishing a fatal parse failure from a real ``None``.

    ``None`` is a legitimate stat value (the source did not publish this
    column); a value that failed to parse at all is not, and the two must
    stay distinguishable to the type checker as well as at runtime — an
    ``object()`` sentinel does not narrow back to ``float | None`` under
    ``isinstance``, and this does.
    """


_FATAL = _Fatal()


def _parse_stat_value(
    raw_value: str,
    *,
    stat_column: StatColumn,
    assumed_games_played: float | None,
    row_number: int,
    header: str,
    issues: list[RowIssue],
) -> float | _Fatal | None:
    text = raw_value.strip()
    if not text:
        return None

    try:
        value = _parse_float(text)
    except ValueError as exc:
        issues.append(
            RowIssue(
                row_number,
                stat_column.field,
                f"unparsable value {raw_value!r} for column {header!r}: {exc}",
                fatal=True,
            )
        )
        return _FATAL
    if value is None:
        return None
    if value < 0:
        issues.append(
            RowIssue(
                row_number,
                stat_column.field,
                f"negative value {value} for column {header!r}",
                fatal=True,
            )
        )
        return _FATAL

    if stat_column.shape is ValueShape.PER_GAME:
        return value

    # SEASON_TOTAL: only convertible with a real, positive games-played figure.
    if assumed_games_played is None or assumed_games_played <= 0:
        issues.append(
            RowIssue(
                row_number,
                stat_column.field,
                f"{_label_for(stat_column.field)} given as a season total but no valid "
                "games-played figure was available to convert it; left null rather than "
                "guessed",
                fatal=False,
            )
        )
        return None
    transformed = value / assumed_games_played
    if not math.isfinite(transformed):
        issues.append(
            RowIssue(
                row_number,
                stat_column.field,
                f"non-finite per-game value after converting column {header!r}",
                fatal=True,
            )
        )
        return _FATAL
    return transformed


def _derive_stat_values(
    *,
    values: dict[str, float | None],
    profile: ColumnProfile,
    row_number: int,
    issues: list[RowIssue],
) -> bool:
    """Apply profile-declared derivations only after source-unit normalization."""
    fatal = False
    for derived in profile.derived_stat_columns:
        inputs = [(values.get(field), coefficient) for field, coefficient in derived.terms]
        if any(value is None for value, _ in inputs):
            values[derived.field] = None
            continue
        result = sum(
            float(value) * coefficient for value, coefficient in inputs if value is not None
        )
        if not math.isfinite(result) or result < 0:
            fatal = True
            issues.append(
                RowIssue(
                    row_number,
                    derived.field,
                    f"derived {_label_for(derived.field)} is not a finite non-negative rate",
                    fatal=True,
                )
            )
            values[derived.field] = None
            continue
        values[derived.field] = result
    return fatal


def _enforce_percentage_decomposability(
    *,
    values: dict[str, float | None],
    percentage_headers: dict[str, str],
    raw: dict[str, str | None],
    row_number: int,
    issues: list[RowIssue],
) -> None:
    """Exclude percentage-category volume unless makes and attempts coexist.

    A lone make/attempt value is not enough to reconstruct volume-weighted
    percentage impact. A percentage plus one component could derive the other,
    but no built-in profile currently declares that transformation, so both
    components are excluded rather than success-shaping a partial ratio.
    """
    for made_field, attempted_field, label in _PERCENTAGE_CATEGORY_PAIRS:
        made = values.get(made_field)
        attempted = values.get(attempted_field)
        header = percentage_headers.get(made_field)
        raw_pct = (raw.get(header) or "").strip() if header else ""

        if made is not None and attempted is not None:
            continue

        if made is not None or attempted is not None:
            values[made_field] = None
            values[attempted_field] = None
            percentage_context = (
                f"; {header}={raw_pct!r} was present but no derivation is declared"
                if raw_pct
                else ""
            )
            issues.append(
                RowIssue(
                    row_number,
                    made_field,
                    f"incomplete {label} volume pair; both makes and attempts are required "
                    f"for a decomposable percentage category, so both were excluded"
                    f"{percentage_context}",
                    fatal=False,
                )
            )
            continue

        if not raw_pct:
            continue
        issues.append(
            RowIssue(
                row_number,
                made_field,
                f"{_label_for(made_field)} given only as a percentage ({header}={raw_pct!r}); "
                "not volume-weighted and left null — do not substitute a percentage for a rate",
                fatal=False,
            )
        )


def _check_shooting_consistency(
    *, values: dict[str, float | None], row_number: int, issues: list[RowIssue]
) -> bool:
    found = False
    for made_field, attempted_field, label in SHOOTING_PAIRS:
        made = values.get(made_field)
        attempted = values.get(attempted_field)
        if made is None or attempted is None:
            continue
        if made > attempted + _EPSILON:
            found = True
            issues.append(
                RowIssue(
                    row_number,
                    made_field,
                    f"{label} makes ({made}) exceed attempts ({attempted})",
                    fatal=True,
                )
            )
    return found


def _reject_duplicate_names(
    candidates: list[tuple[ProjectionSourceRow, bool]], issues: list[RowIssue]
) -> None:
    """Reject every row sharing a normalised name with another row in this file.

    Two rows racing for the same identity-resolution slot cannot both be
    imported blind — one of them silently overwriting the other's crosswalk
    link inside a single file is a different failure from the ordinary
    cross-source name collision the resolver already handles (two real
    people, two sources). This is the same-file case, and nothing here can
    tell which row is correct, so both go back to a human exactly like an
    unresolved identity collision does.
    """
    by_key: dict[str, list[int]] = {}
    for index, (row, fatal) in enumerate(candidates):
        if fatal:
            continue
        key = normalize_name(row.player_name).key
        by_key.setdefault(key, []).append(index)

    for indices in by_key.values():
        if len(indices) < 2:
            continue
        names = ", ".join(repr(candidates[i][0].player_name) for i in indices)
        for index in indices:
            row_number = candidates[index][0].row_number
            issues.append(
                RowIssue(
                    row_number,
                    "player_name",
                    f"duplicate player name within this file ({names}); resolve manually",
                    fatal=True,
                )
            )
            candidates[index] = (candidates[index][0], True)


def _reject_duplicate_source_ids(
    candidates: list[tuple[ProjectionSourceRow, bool]], issues: list[RowIssue]
) -> None:
    """Reject repeated vendor ids; one source id cannot identify two rows."""
    by_id: dict[str, list[int]] = {}
    for index, (row, fatal) in enumerate(candidates):
        if fatal or row.source_player_id is None:
            continue
        by_id.setdefault(row.source_player_id, []).append(index)

    for source_id, indices in by_id.items():
        if len(indices) < 2:
            continue
        for index in indices:
            row_number = candidates[index][0].row_number
            issues.append(
                RowIssue(
                    row_number,
                    "source_player_id",
                    f"duplicate source player id {source_id!r} within this file",
                    fatal=True,
                )
            )
            candidates[index] = (candidates[index][0], True)
