"""Operator command for the draft-day preseason news snapshot."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from hoops_gm.core.config import get_settings
from hoops_gm.db.session import Database, absent_store_refusal
from hoops_gm.ingest.preseason_news.client import PreseasonNewsClient
from hoops_gm.ingest.preseason_news.report import write_preseason_news_report
from hoops_gm.ingest.preseason_news.resolver import resolve_preseason_news
from hoops_gm.ingest.rawstore import RawPayloadStore

DEFAULT_RAW_ROOT = Path("data") / "raw"
DEFAULT_REPORT_PATH = Path("data") / "reports" / "preseason_news.json"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args(argv)

    settings = get_settings()
    if (refusal := absent_store_refusal(settings.database_url)) is not None:
        parser.error(refusal)

    snapshot = PreseasonNewsClient(store=RawPayloadStore(DEFAULT_RAW_ROOT)).latest()
    database = Database.from_settings(settings)
    try:
        with database.session() as session:
            resolution = resolve_preseason_news(session, snapshot.feed.items)
    finally:
        database.dispose()

    write_preseason_news_report(args.output, snapshot=snapshot, resolution=resolution)
    print(f"preseason news: {len(resolution.resolved)} resolved")
    print(f"unresolved     : {len(resolution.unresolved)}")
    print(f"report         : {args.output}")
    return 0 if not resolution.unresolved else 2
