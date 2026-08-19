"""Fix injury_report_entries natural key: add game_date to prevent B2B collision.

The natural key ``(report_timestamp, team_raw, player_name_raw)`` collides
when a single report capture's rolling window names the same player on the
same team twice — once per calendar game date — because that team plays a
back-to-back the very next night and the same masthead covers both games.
Without ``game_date`` in the key, the second night's row silently overwrote
the first night's as an ordinary "update", destroying one of the two distinct
player-games. Found by independent review of the historical-backfill PR
before any evidence relying on it was trusted; see
``docs/adapters/nba-injury-report.md`` and ``db.models.injury_report``.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-18

Note: originally cut as revision 0011 (down_revision 0010); renumbered to
0012 (down_revision 0011) after PR #20 merged to main and claimed 0011 for
``0011_league_deadline_calendars``; renumbered again to 0013 (down_revision
0012) after PR #22 merged to main and claimed 0012 for
``0012_scoring_profile_lineage``. See docs/handoff.md for both rebase
entries.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_CONSTRAINT = "uq_injury_report_entries_report_team_player"
_NEW_CONSTRAINT = "uq_injury_report_entries_report_team_player_date"


def upgrade() -> None:
    # SQLite cannot ALTER a table's constraints in place; batch mode recreates
    # the table under the hood (the same approach every other constraint
    # change in this project's SQLite-compatible migrations uses).
    with op.batch_alter_table("injury_report_entries", schema=None) as batch_op:
        batch_op.drop_constraint(_OLD_CONSTRAINT, type_="unique")
        batch_op.create_unique_constraint(
            _NEW_CONSTRAINT,
            ["report_timestamp", "team_raw", "player_name_raw", "game_date"],
        )


def downgrade() -> None:
    # Deliberately does not attempt to re-collapse any rows a back-to-back
    # split apart under the new key — that would be a genuine, silent data
    # loss the upgrade exists to prevent. A downgrade only restores the old,
    # narrower constraint; if two rows now differ only by game_date, the old
    # constraint cannot be re-added without first resolving that conflict by
    # hand, which is the correct place for a human to intervene, not a
    # migration acting alone.
    with op.batch_alter_table("injury_report_entries", schema=None) as batch_op:
        batch_op.drop_constraint(_NEW_CONSTRAINT, type_="unique")
        batch_op.create_unique_constraint(
            _OLD_CONSTRAINT,
            ["report_timestamp", "team_raw", "player_name_raw"],
        )
