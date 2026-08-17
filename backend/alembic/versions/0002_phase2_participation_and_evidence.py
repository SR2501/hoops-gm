"""Phase 2: participation ledger, per-field match evidence, Fantrax id sources

Three changes, two of which autogenerate got wrong and one it could not see at
all. Everything below was written by hand after applying the generated version
and inspecting the resulting SQLite schema — which is the only way any of this
was found.

**1. ``player_participation``** — the observed participation ledger. Who took
part in which game, with the raw comment kept beside the normalised reason, and
``inactive_list_available`` recording whether the source offered an inactive
list at all. Autogenerate produced this table correctly.

**2. Four per-field evidence columns on ``player_external_ids``.**
Autogenerate emitted them, but via ``batch_op.add_column`` with
``sa.Enum(create_constraint=True)``, which produced **two** CHECK constraints
per column — one named for the naming convention
(``ck_player_external_ids_name_evidence``) and one bare ``CONSTRAINT
name_evidence``, colliding with the column's own name and violating the Phase 1
rule that every constraint is deterministically named. The columns are declared
here with ``create_constraint=False`` and their CHECKs added explicitly, so
exactly one correctly named constraint exists on both dialects.

**3. Widening ``ck_player_external_ids_external_source``** for the three
Fantrax cross-reference sources. **Autogenerate does not detect this at all.**
``enum_check_constraint_names`` in ``db/base.py`` excludes enum CHECKs from
comparison by name — necessary, or every ``alembic check`` reports a spurious
removal per enum column — with the consequence that adding an enum member
produces no migration and no drift warning.

That consequence is not theoretical. The generated migration was applied and
then ``INSERT INTO player_external_ids (source) VALUES ('fantrax_sportradar')``
was **rejected** by ``ck_player_external_ids_external_source``, while the same
insert succeeded against a schema built by ``Base.metadata.create_all`` — which
is what the test suite uses. Green tests, broken production, and ``alembic
check`` reporting no drift throughout. ``test_migrations.py`` now asserts every
``ExternalSource`` member is accepted by a *migrated* database, so the next
person to add an enum member finds out here.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The value list as at revision 0001.
_EXTERNAL_SOURCE_V1 = (
    "nba",
    "fantrax",
    "fantasypros",
    "hashtag",
    "basketball_monster",
    "darko",
    "manual",
)

#: The value list this revision installs.
_EXTERNAL_SOURCE_V2 = (
    "nba",
    "fantrax",
    "fantrax_stats_inc",
    "fantrax_rotowire",
    "fantrax_sportradar",
    "fantasypros",
    "hashtag",
    "basketball_monster",
    "darko",
    "manual",
)

_EVIDENCE_VALUES = ("agree", "disagree", "unknown")
_EVIDENCE_COLUMNS = (
    "name_evidence",
    "team_evidence",
    "position_evidence",
    "suffix_evidence",
)

#: Inlined rather than imported from ``hoops_gm.db.base``. A migration that
#: imports application code stops being able to migrate an old database the
#: moment that code is renamed — the same reasoning that keeps ``UTCDateTime``
#: out of revision 0001. The two must agree; ``test_migrations.py`` proves they
#: do by running ``alembic check``.
_NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _in_list(column: str, values: Sequence[str]) -> str:
    rendered = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({rendered})"


def _string_enum(*values: str, name: str, create_constraint: bool = True) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=create_constraint,
        length=48,
    )


def _player_external_ids_before() -> sa.Table:
    """The table exactly as revision 0001 left it.

    Required by ``copy_from``: SQLite cannot ``ALTER TABLE ... DROP
    CONSTRAINT``, so changing a CHECK means rebuilding the table, and Alembic
    rebuilds from *reflection* unless given an explicit definition. SQLite
    reflection does not reliably recover named CHECK constraints, so a
    reflection-driven rebuild would silently drop the ones we are keeping.
    Stating the prior shape here is verbose and is the only way the rebuild is
    correct.
    """
    metadata = sa.MetaData(naming_convention=_NAMING_CONVENTION)
    return sa.Table(
        "player_external_ids",
        metadata,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            _string_enum(*_EXTERNAL_SOURCE_V1, name="external_source", create_constraint=False),
            nullable=False,
        ),
        sa.Column("current_for_source", sa.String(length=48), nullable=True),
        sa.Column("source_detail", sa.String(length=64), nullable=True),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("external_name", sa.String(length=128), nullable=True),
        sa.Column("normalized_name", sa.String(length=128), nullable=True),
        sa.Column("external_team", sa.String(length=16), nullable=True),
        sa.Column("external_position", sa.String(length=16), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "match_method",
            _string_enum(
                "anchor_id",
                "exact_name",
                "normalized_name",
                "name_team_position",
                "fuzzy",
                "manual_override",
                name="match_method",
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column("is_manual_override", sa.Boolean(), nullable=False),
        sa.Column("reviewed_at", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="confidence_range",
        ),
        sa.CheckConstraint(
            "current_for_source IS NULL OR current_for_source = source",
            name="current_marker_matches_source",
        ),
        sa.CheckConstraint(
            _in_list("source", _EXTERNAL_SOURCE_V1),
            name="external_source",
        ),
        sa.CheckConstraint(
            _in_list(
                "match_method",
                (
                    "anchor_id",
                    "exact_name",
                    "normalized_name",
                    "name_team_position",
                    "fuzzy",
                    "manual_override",
                ),
            ),
            name="match_method",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="fk_player_external_ids_player_id_players",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_player_external_ids"),
        sa.UniqueConstraint(
            "player_id", "current_for_source", name="uq_player_external_ids_current"
        ),
        sa.UniqueConstraint("source", "external_id", name="uq_player_external_ids_source_ext"),
        # The indexes must be declared here too. A SQLite batch rebuild
        # recreates the table from *this* definition, so an index omitted here
        # is an index silently dropped — which is exactly what happened on the
        # first attempt: all four survived `alembic upgrade` in the sense that
        # it reported success, and `alembic check` then found them missing.
        sa.Index("ix_player_external_ids_is_manual_override", "is_manual_override"),
        sa.Index("ix_player_external_ids_player_id", "player_id"),
        sa.Index("ix_player_external_ids_player_source", "player_id", "source"),
        sa.Index("ix_player_external_ids_source_norm_name", "source", "normalized_name"),
    )


def upgrade() -> None:
    op.create_table(
        "player_participation",
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column(
            "outcome",
            _string_enum(
                "played",
                "did_not_play",
                "did_not_dress",
                "not_with_team",
                "inactive",
                "unknown",
                name="participation_outcome",
            ),
            nullable=False,
        ),
        sa.Column(
            "reason",
            _string_enum(
                "coaches_decision",
                "injury_or_illness",
                "rest",
                "personal",
                "suspension",
                "g_league",
                "trade_pending",
                "conditioning",
                "not_with_team",
                "other",
                "none_given",
                name="dnp_reason",
            ),
            nullable=False,
        ),
        sa.Column("raw_comment", sa.Text(), nullable=False),
        sa.Column("seconds_played", sa.Integer(), nullable=True),
        sa.Column(
            "source",
            _string_enum(*_EXTERNAL_SOURCE_V2, name="external_source"),
            nullable=False,
        ),
        sa.Column("inactive_list_available", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["nba_games.id"],
            name=op.f("fk_player_participation_game_id_nba_games"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name=op.f("fk_player_participation_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["nba_teams.id"],
            name=op.f("fk_player_participation_team_id_nba_teams"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player_participation")),
        sa.UniqueConstraint("player_id", "game_id", name="uq_player_participation_player_game"),
    )
    with op.batch_alter_table("player_participation", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_player_participation_game_id"), ["game_id"], unique=False
        )
        batch_op.create_index(
            "ix_player_participation_game_outcome", ["game_id", "outcome"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_player_participation_player_id"), ["player_id"], unique=False
        )
        batch_op.create_index(
            "ix_player_participation_player_outcome", ["player_id", "outcome"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_player_participation_team_id"), ["team_id"], unique=False
        )

    # One batch, one table rebuild on SQLite. copy_from supplies the prior
    # shape so the rebuild preserves the constraints it is not changing.
    with op.batch_alter_table(
        "player_external_ids", schema=None, copy_from=_player_external_ids_before()
    ) as batch_op:
        for column in _EVIDENCE_COLUMNS:
            batch_op.add_column(
                sa.Column(
                    column,
                    # create_constraint=False: the CHECK is added explicitly
                    # below. Leaving the enum to emit its own produced a second,
                    # unnamed constraint alongside the conventionally named one.
                    _string_enum(*_EVIDENCE_VALUES, name=column, create_constraint=False),
                    nullable=False,
                    # Required: the column is NOT NULL and the table may hold
                    # rows. UNKNOWN is the honest default — a row written
                    # before this revision recorded no per-field evidence, and
                    # claiming agreement for it would invent the very thing
                    # these columns exist to make explicit.
                    server_default="unknown",
                )
            )
            batch_op.create_check_constraint(column, _in_list(column, _EVIDENCE_VALUES))

        batch_op.drop_constraint("external_source", type_="check")
        batch_op.create_check_constraint("external_source", _in_list("source", _EXTERNAL_SOURCE_V2))


def downgrade() -> None:
    with op.batch_alter_table(
        "player_external_ids", schema=None, copy_from=_player_external_ids_after()
    ) as batch_op:
        batch_op.drop_constraint("external_source", type_="check")
        batch_op.create_check_constraint("external_source", _in_list("source", _EXTERNAL_SOURCE_V1))
        for column in reversed(_EVIDENCE_COLUMNS):
            batch_op.drop_constraint(column, type_="check")
            batch_op.drop_column(column)

    with op.batch_alter_table("player_participation", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_player_participation_team_id"))
        batch_op.drop_index("ix_player_participation_player_outcome")
        batch_op.drop_index(batch_op.f("ix_player_participation_player_id"))
        batch_op.drop_index("ix_player_participation_game_outcome")
        batch_op.drop_index(batch_op.f("ix_player_participation_game_id"))

    op.drop_table("player_participation")


def _player_external_ids_after() -> sa.Table:
    """The table as this revision leaves it, for the downgrade rebuild."""
    table = _player_external_ids_before()
    for column in _EVIDENCE_COLUMNS:
        table.append_column(
            sa.Column(
                column,
                _string_enum(*_EVIDENCE_VALUES, name=column, create_constraint=False),
                nullable=False,
                server_default="unknown",
            )
        )
        table.append_constraint(
            sa.CheckConstraint(
                _in_list(column, _EVIDENCE_VALUES),
                name=column,
            )
        )
    # Replace the v1 source CHECK with the v2 one. Matching on the *rendered*
    # name because the naming convention has already been applied by the time a
    # constraint is attached to a table.
    for constraint in list(table.constraints):
        if getattr(constraint, "name", None) == "ck_player_external_ids_external_source":
            table.constraints.discard(constraint)
    table.append_constraint(
        sa.CheckConstraint(
            _in_list("source", _EXTERNAL_SOURCE_V2),
            name="external_source",
        )
    )
    return table
