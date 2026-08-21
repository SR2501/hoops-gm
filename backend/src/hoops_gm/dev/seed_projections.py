"""Seed a local database so the projections endpoint can answer 200.

**The numbers in this cohort are invented.** Nothing derived from it is a
projection anyone should look at, and a fixture captured from the screen it
drives proves *shape* and nothing else — not column width, not long names, not
real cohort size, not a real distribution. Only the player names are real, and
they are real for one reason: the identity crosswalk has to have something to
resolve, and a seed that bypassed the resolver would prove the endpoint works
against data the producer would never have written.

**Why this exists.** ``GET /api/v1/leagues/{id}/projections/current`` has never
returned 200 outside pytest. It fails closed on an unimported source, which is
correct and means "it answers ``projections_source_not_imported``" says nothing
about whether it can ever answer anything else — the exact state the schedule
grid was in before ``seed_schedule_grid``, where an endpoint was permanently
unavailable and nobody noticed.

**Why the committed Basketball Monster fixture cannot do this job.**
``tests/fixtures/projections/basketball_monster_sample.csv`` holds two rows
named *Player Alpha* and *Player Gamma*. Its own metadata says why: *"All paid
player rows and private paths were removed. The committed rows are synthetic."*
Those names match no player in ``nba_playerindex_current.json``, so the importer
accepts zero resolutions, writes zero ``projections`` rows, and
``blending.release_projection_import`` then raises ``MissingProjectionDataError``.
Seeding that file through the real importer produces **a new refusal, not a
200**. The fixture is Adapter-gate evidence of Basketball Monster's column
contract and it is doing that job correctly; it is not evidence of anything on
this path, because it never becomes a row.

## How the demo CSV is built, and why there is no committed CSV

The CSV is generated **in memory, at seed time**, from the canonical players
this same run just imported — not from a checked-in file. Two consequences,
both deliberate:

* **Resolution succeeds by construction rather than by luck.** The names are
  taken from ``players.first_name``/``players.last_name``, which are
  ``normalize_name``'s own output, so the projection row's normalised key is
  identical to its target's by definition rather than by two fixtures happening
  to agree. Only players whose normalised name is unique in the database are
  used, so :data:`~hoops_gm.identity.resolver.UNIQUE_NAME_BONUS` applies and
  each row lands at exactly ``AUTO_ACCEPT_CONFIDENCE``. Basketball Monster's
  contract carries no team and no position column, so a name is the only
  evidence available and that bonus is the whole margin.
* **There is no artefact to mistake for a recording.** A committed CSV full of
  real NBA names would sit in a tree next to real captures and read as one. The
  provenance of this cohort is code that names its inputs, in a module under
  ``dev/``, which cannot be mistaken for something a source sent.

The bytes still go through :func:`~hoops_gm.ingest.projections.importer.import_projection_csv`
unmodified, under the committed Basketball Monster profile and its exact header
order — the same production writer, the same profile verification, the same
byte-hash lineage. ``seed_schedule_grid``'s standard, applied to a second
importer.

Run it::

    cd backend
    python -m hoops_gm.dev.seed_projections --database-url sqlite:///./projections_demo.db
    DATABASE_URL=sqlite:///./projections_demo.db python -m hoops_gm
    curl "http://127.0.0.1:8000/api/v1/leagues/1/projections/current"

It composes :func:`~hoops_gm.dev.seed_schedule_grid.seed_schedule_grid` first,
so one command produces a database both screens can be driven against, and so
the league the projections route reads — and its season, which must match the
profile's verified season — is created by the same guarded path. That also
inherits ``require_safe_demo_target``: this refuses to run against a database
holding any league it did not create.

Re-running converges. The generated CSV is deterministic, so its SHA-256 is
stable and the importer resolves onto the same ``projection_imports`` row rather
than minting a new version.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import traceback
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from hoops_gm.core.config import Settings
from hoops_gm.db.models.enums import ExternalSource, ScoringType
from hoops_gm.db.models.identity import Player
from hoops_gm.db.session import Database
from hoops_gm.dev.seed_schedule_grid import (
    DEFAULT_FIXTURES_DIR,
    SEASON,
    DemoSeedRefused,
    create_schema_only_on_a_fresh_database,
    load_fixture,
    redacted_url,
    seed_schedule_grid,
)
from hoops_gm.ingest.importers import import_nba_players, import_player_positions
from hoops_gm.ingest.nba.parsers import parse_common_all_players, parse_player_index
from hoops_gm.ingest.projections.importer import import_projection_csv
from hoops_gm.ingest.projections.profiles import (
    BASKETBALL_MONSTER_2026_27_HEADERS,
    BASKETBALL_MONSTER_PROFILE,
)

PLAYERS_FIXTURE = "nba_commonallplayers_current.json"
POSITIONS_FIXTURE = "nba_playerindex_current.json"

#: How many players the demo cohort carries. Large enough that a screen has
#: something to scroll and sort, small enough that the seed stays quick. It is
#: **not** a realistic league-wide cohort and a fixture captured from it must
#: not be read as evidence about one.
DEMO_COHORT_SIZE = 60

#: Fixed so the settings snapshot and position provenance carry the same
#: timestamps on every run.
SEEDED_AT = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

#: The filename recorded on the import. Deliberately not shaped like a path to
#: a real export: ``original_filename`` is the field a reader would use to tell
#: a seeded cohort from the owner's own file, so it says what it is.
DEMO_FILENAME = "synthetic-projections-demo.csv"

DEMO_DISPLAY_NAME = "Basketball Monster (synthetic demo cohort)"


@dataclass(frozen=True)
class ProjectionsSeedResult:
    """What the seed put in the database, for the caller to assert against."""

    league_id: int
    season: str
    schedule_version: str
    players_created: int
    positions_written: int
    cohort_size: int
    content_sha256: str
    projections_written: int
    identities_accepted: int
    identities_unresolved: int


def _synthetic_season_line(person_id: int, games: int) -> dict[str, object]:
    """Invented season totals for one player, derived from their person id.

    Deterministic so the generated file's bytes — and therefore the import's
    content hash — are stable across runs. Spread across a plausible range so a
    screen shows variation rather than sixty identical rows, and internally
    consistent so the importer's real validation actually runs: makes never
    exceed attempts, nothing is negative, nothing is non-finite.

    **These are not projections.** They are numbers chosen to exercise a
    contract. The spread is arithmetic on an identifier and carries no
    information about any player.
    """

    # A stable per-player offset in [0, 1). `person_id` is a real NBA
    # identifier, so this is deterministic without being meaningful.
    spread = (person_id % 97) / 97.0

    minutes = round(games * (18.0 + 18.0 * spread), 1)
    fga = round(games * (6.0 + 12.0 * spread), 1)
    fgm = round(fga * (0.42 + 0.08 * spread), 1)
    fta = round(games * (1.5 + 5.0 * spread), 1)
    ftm = round(fta * (0.72 + 0.15 * spread), 1)
    tpa = round(fga * (0.20 + 0.30 * spread), 1)
    tpm = round(tpa * (0.33 + 0.08 * spread), 1)
    return {
        "games": games,
        "minutes": minutes,
        "field_goals_attempted": fga,
        "field_goals": fgm,
        "free_throws_attempted": fta,
        "free_throws": ftm,
        "threes": tpm,
        "threes_attempted": tpa,
        "offensive_rebounds": round(games * (0.4 + 2.4 * spread), 1),
        "defensive_rebounds": round(games * (1.8 + 6.0 * spread), 1),
        "assists": round(games * (0.8 + 6.5 * spread), 1),
        "blocks": round(games * (0.1 + 1.4 * spread), 1),
        "steals": round(games * (0.3 + 1.4 * spread), 1),
        "turnovers": round(games * (0.5 + 3.0 * spread), 1),
        "fouls": round(games * (1.1 + 2.0 * spread), 1),
        "technicals": 0,
        "double_doubles": 0,
        "triple_doubles": 0,
        "comments": "synthetic demo row, not a projection",
    }


def unique_named_players(session: Session, *, limit: int) -> list[Player]:
    """Canonical players whose normalised name is unique, ordered by id.

    Uniqueness is the load-bearing filter, not a tidiness one. Basketball
    Monster's contract publishes no team and no position column, so a name is
    the only evidence the resolver has: a unique name scores 0.70 and is
    promoted by ``UNIQUE_NAME_BONUS`` to exactly ``AUTO_ACCEPT_CONFIDENCE``,
    while a name shared with another canonical player is refused as *ambiguous*
    and produces no projection row at all. Selecting for uniqueness is what
    makes this seed reach a 200 by construction rather than by luck.

    **It selects nothing out against today's fixture, and that is worth
    knowing.** All 580 players in ``nba_commonallplayers_current.json``
    normalise to 580 distinct keys, so this filter is currently defensive
    rather than active — a mutation flipping ``== 1`` to ``>= 1`` cannot be
    caught by any test that merely seeds from the fixture. It is exercised
    directly instead, in
    ``test_the_uniqueness_filter_excludes_a_shared_name``. Same-named players
    do occur in the NBA; this snapshot happens to contain none.

    Ordered by ``Player.id`` so the generated cohort — and therefore the
    import's content hash — is the same on every run against the same fixtures.
    """

    players = list(
        session.scalars(
            select(Player).where(Player.first_name.is_not(None), Player.last_name.is_not(None))
        )
    )
    name_counts = Counter(player.normalized_name for player in players)
    return sorted(
        (player for player in players if name_counts[player.normalized_name] == 1),
        key=lambda player: player.id,
    )[:limit]


def build_demo_csv(players: list[Player]) -> bytes:
    """Render one demo cohort in Basketball Monster's exact committed header order.

    The header tuple is imported from the profile rather than restated, so this
    cannot drift into writing a file the verified profile would reject — which
    would be a seed proving the endpoint works against a shape the real importer
    refuses.

    Names come from ``first_name``/``last_name``, which are ``normalize_name``'s
    own output for the canonical row. That is what makes the resolver's name key
    identical on both sides by definition.
    """

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(BASKETBALL_MONSTER_2026_27_HEADERS),
        lineterminator="\n",
    )
    writer.writeheader()
    for index, player in enumerate(players):
        # Between 58 and 79, varying per player so the cohort carries a real
        # spread of games-played assumptions rather than one repeated value.
        # It is the importer's divisor, never a multiplier — see ADR-002.
        games = 58 + (player.id * 7 + index) % 22
        row: dict[str, object] = {
            # Not a Basketball Monster identifier and not shaped like one. This
            # is the source crosswalk key, and a reader inspecting
            # `player_external_ids` should be able to tell at a glance that this
            # row came from a seed rather than from a paid export.
            "player_id": f"synthetic-demo-{player.id}",
            "last_name": player.last_name,
            "first_name": player.first_name,
        }
        row.update(_synthetic_season_line(player.id, games))
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def seed_projections(
    session: Session,
    *,
    fixtures_dir: Path = DEFAULT_FIXTURES_DIR,
    cohort_size: int = DEMO_COHORT_SIZE,
) -> ProjectionsSeedResult:
    """Bring one database to the state the projections endpoint requires.

    Order is load-bearing. The schedule grid seed runs first because it creates
    the league the projections route reads and the ``nba_teams`` rows player
    imports join to, and because it composes the settings and schedule writers
    in the canonical lock order. Players are imported before positions because
    ``import_player_positions`` refuses to invent a canonical row. The demo CSV
    is generated after both, from the players that now exist.
    """

    schedule = seed_schedule_grid(session, fixtures_dir=fixtures_dir)

    players = import_nba_players(
        session, parse_common_all_players(load_fixture(fixtures_dir, PLAYERS_FIXTURE))
    )
    positions = import_player_positions(
        session,
        parse_player_index(load_fixture(fixtures_dir, POSITIONS_FIXTURE), season=SEASON),
        observed_at=SEEDED_AT,
    )

    cohort = unique_named_players(session, limit=cohort_size)
    if not cohort:
        raise DemoSeedRefused(
            "no canonical player has a unique normalised name, so no projection row could "
            "resolve. The player fixtures did not import as expected; nothing was seeded."
        )

    csv_bytes = build_demo_csv(cohort)
    outcome = import_projection_csv(
        session,
        source=ExternalSource.BASKETBALL_MONSTER,
        display_name=DEMO_DISPLAY_NAME,
        season=SEASON,
        csv_bytes=csv_bytes,
        original_filename=DEMO_FILENAME,
        assumed_scoring_type=ScoringType.H2H_CATEGORIES,
        profile=BASKETBALL_MONSTER_PROFILE,
    )

    written = outcome.counts.created + outcome.counts.updated
    if written == 0:
        raise DemoSeedRefused(
            f"the demo cohort of {len(cohort)} row(s) resolved to no player, so the "
            "projections endpoint would still refuse. Nothing about this seed is useful "
            "in that state, so it fails rather than reporting success."
        )

    return ProjectionsSeedResult(
        league_id=schedule.league_id,
        season=SEASON,
        schedule_version=schedule.schedule_version,
        players_created=players.created,
        positions_written=positions.created + positions.updated,
        cohort_size=len(cohort),
        content_sha256=outcome.projection_import.content_sha256,
        projections_written=written,
        identities_accepted=len(outcome.identity_report.accepted),
        identities_unresolved=(
            len(outcome.identity_report.needs_review) + len(outcome.identity_report.unmatched)
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--database-url",
        default="sqlite:///./projections_demo.db",
        help="SQLAlchemy URL to seed. Defaults to a throwaway local SQLite file.",
    )
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=DEFAULT_FIXTURES_DIR,
        help="where the committed NBA fixtures live",
    )
    parser.add_argument(
        "--cohort-size",
        type=int,
        default=DEMO_COHORT_SIZE,
        help=(
            f"how many players the synthetic cohort carries. Default {DEMO_COHORT_SIZE}. "
            "Not a realistic league-wide cohort at any value."
        ),
    )
    args = parser.parse_args(argv)

    settings = Settings(database_url=args.database_url)
    database = Database.from_settings(settings)
    try:
        create_schema_only_on_a_fresh_database(database)
        with database.session() as session:
            result = seed_projections(
                session,
                fixtures_dir=args.fixtures_dir,
                cohort_size=args.cohort_size,
            )
    except DemoSeedRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        traceback.print_exc()
        print("database error; nothing was seeded", file=sys.stderr)
        return 4
    finally:
        database.dispose()

    print(
        json.dumps(
            {
                "database_url": redacted_url(args.database_url),
                "league_id": result.league_id,
                "season": result.season,
                "schedule_version": result.schedule_version,
                "players_created": result.players_created,
                "positions_written": result.positions_written,
                "cohort_size": result.cohort_size,
                "content_sha256": result.content_sha256,
                "projections_written": result.projections_written,
                "identities_accepted": result.identities_accepted,
                "identities_unresolved": result.identities_unresolved,
            },
            indent=2,
        )
    )
    print(
        "\nThe projection numbers in this database are invented. Nothing derived from them "
        "is a projection anyone should look at, and a fixture captured from the screen they "
        "drive proves shape and nothing else.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
