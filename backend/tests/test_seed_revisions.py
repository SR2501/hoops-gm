"""Every seed-created database identifies its model-built schema revision."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from hoops_gm.dev.seed_demo import MIN_COMPOSED_COHORT_SIZE


@pytest.mark.parametrize(
    ("module", "extra_args"),
    [
        ("hoops_gm.dev.seed_schedule_grid", []),
        ("hoops_gm.dev.seed_projections", ["--cohort-size", "7"]),
        ("hoops_gm.dev.seed_draft", []),
        ("hoops_gm.dev.seed_demo", ["--cohort-size", str(MIN_COMPOSED_COHORT_SIZE)]),
    ],
    ids=("schedule-grid", "projections", "draft", "composed-demo"),
)
def test_every_seed_created_database_reports_alembic_head(
    module: str,
    extra_args: list[str],
    tmp_path: Path,
    backend_dir: Path,
) -> None:
    database_path = tmp_path / "seed.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend_dir / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            module,
            "--database-url",
            database_url,
            *extra_args,
        ],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    expected = ScriptDirectory.from_config(config).get_current_head()
    # Otherwise an unstamped database and a missing migration tree agree on None.
    assert expected is not None
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            actual = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()

    assert actual == expected
