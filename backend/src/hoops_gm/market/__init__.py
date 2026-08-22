"""Market layer: rules about consuming what other people published.

Storage lives in ``db/models/market.py`` and ingestion in
``ingest/auction_values/``. This package holds the rules that decide what a
stored market number may be *used for* — currently just
:mod:`hoops_gm.market.independence`, which refuses to treat a source as
independent evidence when its lineage overlaps our own projection inputs.
"""

from __future__ import annotations

from hoops_gm.market.independence import (
    BenchmarkAdmissibility,
    IndependenceFinding,
    assess_benchmark_admissibility,
    assess_source_independence,
    imported_projection_sources,
)

__all__ = [
    "BenchmarkAdmissibility",
    "IndependenceFinding",
    "assess_benchmark_admissibility",
    "assess_source_independence",
    "imported_projection_sources",
]
