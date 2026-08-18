"""Scoring profile lineage and single-active-per-league enforcement.

Backs the ``scoring-profiles`` backlog unit (docs/backlog.md) and
``hoops_gm.scoring.profiles`` -- see ``LeagueScoringProfile``'s docstring in
``db/models/league.py`` for the full rationale. Two changes to
``league_scoring_profiles``:

* ``settings_snapshot_id`` (not null): the ``league_settings_snapshots`` row
  that was current when this profile was derived, so "what rules produced
  this scoring configuration" stays answerable. ``league_scoring_profiles``
  has no rows in any known deployment of this schema (the feature was
  scaffolded in 0001 but never wired to an importer until now), so this
  column is added not-null with no backfill needed.
* ``active_league_id`` replaces the plain ``is_active`` boolean: it mirrors
  ``league_id`` while this row is the league's active profile and is
  ``NULL`` otherwise. A bare unique constraint on this one nullable column
  enforces "at most one active profile per league" at the database layer
  without a dialect-specific partial index (SQLite and Postgres both treat
  NULL as distinct in a unique constraint, so any number of inactive/retired
  versions coexist safely).

A third, unrelated change lives here too: ``league_settings_snapshots`` is
**not** empty in any known deployment (it backs the already-merged
`league-settings-ingest` unit), and this revision is also where
``hoops_gm.ingest.league_settings.LeagueSettingsDocument`` gained two new
*required* fields, ``scoring_type``/``scoring_categories``, bumping its own
``schema_version`` 1 -> 2. A pre-existing snapshot row's ``settings`` JSON has
neither key, so reading it back through the new, stricter model would raise --
breaking both the settings importer's own re-ingest dedupe (which parses the
prior snapshot to compare content) and deadline-calendar derivation (which
parses the current snapshot). ``_backfill_legacy_settings_snapshots_to_schema_v2``
rewrites every such row once here: both new fields become an explicit
*absent* observation, evidenced as ``schema_migration`` (never
``fantrax_official``/``fantrax_bridge`` -- nothing was actually observed for
these rows) with a ``capture_ref`` built from that row's own existing
provenance (its payload hash and observed-at instant), not one placeholder
string reused across every row. This module deliberately does not import
``hoops_gm.ingest.league_settings`` to build that shape (see 0001's docstring
on keeping application classes out of migrations); the handful of literal
keys this needs are reproduced directly against the same evidence contract.

Downgrading refuses to discard a real observation: ``downgrade()`` only
strips the two injected keys (and reverts ``schema_version`` to 1/``"1"``)
from rows whose evidence for both fields is *entirely* ``schema_migration``-
sourced. Any row with genuine ``fantrax_official``/``fantrax_bridge`` scoring
evidence -- i.e. a real official import that ran after this migration --
blocks the downgrade with a loud ``RuntimeError``, the same "refuse lossy
downgrade" discipline 0010 already established for schedule-context
provenance.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Mirrors ``hoops_gm.ingest.league_settings.MIGRATION_SOURCE`` by value, not
#: by import -- see the module docstring on keeping migrations independent of
#: application code that may itself be renamed or restructured later.
_MIGRATION_SOURCE = "schema_migration"
_ABSENT_STATUS = "absent"
_LEGACY_FIELDS = ("scoring_type", "scoring_categories")


def _settings_snapshots_table() -> sa.Table:
    return sa.table(
        "league_settings_snapshots",
        sa.column("id", sa.Integer()),
        sa.column("schema_version", sa.String()),
        sa.column("settings", sa.JSON()),
        sa.column("source_summary", sa.JSON()),
        sa.column("source_payload_sha256", sa.String()),
        sa.column("observed_at", sa.DateTime(timezone=True)),
    )


def _absent_evidence(capture_ref: str) -> list[dict[str, Any]]:
    return [
        {
            "source": _MIGRATION_SOURCE,
            "status": _ABSENT_STATUS,
            "source_path": None,
            "capture_ref": capture_ref,
        }
    ]


def _backfill_legacy_settings_snapshots_to_schema_v2() -> None:
    """Give every pre-existing settings snapshot the v2 document shape.

    See the module docstring for the full rationale. Idempotent: a row whose
    ``settings`` already carries both new keys (schema_version already >= 2)
    is left untouched.
    """

    connection = op.get_bind()
    snapshots = _settings_snapshots_table()
    rows = connection.execute(
        sa.select(
            snapshots.c.id,
            snapshots.c.settings,
            snapshots.c.source_summary,
            snapshots.c.source_payload_sha256,
            snapshots.c.observed_at,
        )
    ).all()

    for row in rows:
        settings = row.settings
        if all(field in settings for field in _LEGACY_FIELDS):
            continue  # already v2-shaped; nothing to backfill.

        digest_prefix = (row.source_payload_sha256 or "")[:16]
        capture_ref = f"legacy-schema-v1:{row.observed_at.isoformat()}:{digest_prefix}"[:128]
        evidence = _absent_evidence(capture_ref)

        settings = dict(settings)
        settings["schema_version"] = 2
        for field_name in _LEGACY_FIELDS:
            settings.setdefault(field_name, {"value": None, "evidence": evidence})

        source_summary = dict(row.source_summary or {})
        for field_name in _LEGACY_FIELDS:
            source_summary.setdefault(field_name, evidence)

        connection.execute(
            snapshots.update()
            .where(snapshots.c.id == row.id)
            .values(settings=settings, source_summary=source_summary, schema_version="2")
        )


def _settings_snapshot_downgrade_blockers() -> list[str]:
    connection = op.get_bind()
    snapshots = _settings_snapshots_table()
    rows = connection.execute(sa.select(snapshots.c.id, snapshots.c.settings)).all()

    genuine: list[int] = []
    for row in rows:
        settings = row.settings
        for field_name in _LEGACY_FIELDS:
            sourced = settings.get(field_name)
            if not isinstance(sourced, dict):
                continue
            evidence = sourced.get("evidence") or []
            if any(item.get("source") != _MIGRATION_SOURCE for item in evidence):
                genuine.append(row.id)
                break

    if not genuine:
        return []
    ids = ", ".join(str(i) for i in genuine)
    return [f"settings snapshot(s) with real (non-migration) scoring evidence: {ids}"]


def _revert_legacy_settings_snapshots_schema_v2_backfill() -> None:
    blockers = _settings_snapshot_downgrade_blockers()
    if blockers:
        joined = "; ".join(blockers)
        raise RuntimeError(
            "refusing lossy 0012 downgrade of league_settings_snapshots: "
            f"{joined} -- archive or explicitly remove this scoring evidence first"
        )

    connection = op.get_bind()
    snapshots = _settings_snapshots_table()
    rows = connection.execute(
        sa.select(snapshots.c.id, snapshots.c.settings, snapshots.c.source_summary)
    ).all()

    for row in rows:
        settings = row.settings
        if not any(field_name in settings for field_name in _LEGACY_FIELDS):
            continue  # already v1-shaped; nothing to revert.

        settings = dict(settings)
        for field_name in _LEGACY_FIELDS:
            settings.pop(field_name, None)
        settings["schema_version"] = 1

        source_summary = dict(row.source_summary or {})
        for field_name in _LEGACY_FIELDS:
            source_summary.pop(field_name, None)

        connection.execute(
            snapshots.update()
            .where(snapshots.c.id == row.id)
            .values(settings=settings, source_summary=source_summary, schema_version="1")
        )


def upgrade() -> None:
    with op.batch_alter_table("league_scoring_profiles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("settings_snapshot_id", sa.Integer(), nullable=False))
        batch_op.add_column(sa.Column("active_league_id", sa.Integer(), nullable=True))
        batch_op.drop_index(batch_op.f("ix_league_scoring_profiles_is_active"))
        batch_op.create_index(
            batch_op.f("ix_league_scoring_profiles_settings_snapshot_id"),
            ["settings_snapshot_id"],
            unique=False,
        )
        batch_op.create_unique_constraint(
            "uq_league_scoring_profiles_one_active", ["active_league_id"]
        )
        batch_op.create_foreign_key(
            "fk_league_scoring_profiles_settings_snapshot_id",
            "league_settings_snapshots",
            ["settings_snapshot_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_league_scoring_profiles_active_league_id_leagues"),
            "leagues",
            ["active_league_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_league_scoring_profiles_active_league_id_matches_league"),
            "active_league_id IS NULL OR active_league_id = league_id",
        )
        batch_op.drop_column("is_active")

    _backfill_legacy_settings_snapshots_to_schema_v2()


def downgrade() -> None:
    _revert_legacy_settings_snapshots_schema_v2_backfill()

    with op.batch_alter_table("league_scoring_profiles", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.drop_constraint(
            batch_op.f("ck_league_scoring_profiles_active_league_id_matches_league"),
            type_="check",
        )
        batch_op.drop_constraint(
            batch_op.f("fk_league_scoring_profiles_active_league_id_leagues"),
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_league_scoring_profiles_settings_snapshot_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint("uq_league_scoring_profiles_one_active", type_="unique")
        batch_op.drop_index(batch_op.f("ix_league_scoring_profiles_settings_snapshot_id"))
        batch_op.create_index(
            batch_op.f("ix_league_scoring_profiles_is_active"), ["is_active"], unique=False
        )
        batch_op.drop_column("active_league_id")
        batch_op.drop_column("settings_snapshot_id")
