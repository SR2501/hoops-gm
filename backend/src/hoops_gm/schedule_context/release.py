"""Load the exact schedule-context model artifact that passed the Model gate."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from importlib.resources import files
from typing import Any

from hoops_gm.schedule_context.blowout import BlowoutModel, blowout_model_version

RELEASED_BLOWOUT_MODEL_VERSION = "e273cfbe4b599b16"
_RELEASE_FILES = {
    RELEASED_BLOWOUT_MODEL_VERSION: (
        "schedule_context_blowout_v2.json",
        "a31d77d5fc07494d6f7ab0bf2ee73fdfc84cd391ed1a5f931e66e115bc564b31",
    ),
}


class UnreleasedBlowoutModelError(ValueError):
    """A caller requested a model version that did not pass the Model gate."""


@dataclass(frozen=True)
class BlowoutRelease:
    evidence_version: str
    model: BlowoutModel
    training_source_fingerprint: str
    holdout_source_fingerprint: str
    held_out_examples: int


def _decode_release_artifact(raw_artifact: bytes) -> tuple[dict[str, Any], str]:
    payload: dict[str, Any] = json.loads(raw_artifact)
    canonical_artifact = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return payload, sha256(canonical_artifact).hexdigest()


def load_blowout_release(
    model_version: str = RELEASED_BLOWOUT_MODEL_VERSION,
) -> BlowoutRelease:
    """Load one allowlisted, packaged release; arbitrary fitted models are rejected."""

    release_file = _RELEASE_FILES.get(model_version)
    if release_file is None:
        raise UnreleasedBlowoutModelError(
            f"blowout model {model_version!r} is not in the production release registry"
        )
    filename, expected_digest = release_file
    resource = files("hoops_gm.schedule_context.releases").joinpath(filename)
    raw_artifact = resource.read_bytes()
    payload, actual_digest = _decode_release_artifact(raw_artifact)
    if actual_digest != expected_digest:
        raise RuntimeError("packaged blowout release artifact does not match its pinned digest")
    final = payload["final"]
    raw_model = final["model"]
    model = BlowoutModel(
        training_cutoff=date.fromisoformat(raw_model["training_cutoff"]),
        window_games=raw_model["window_games"],
        minimum_history_games=raw_model["minimum_history_games"],
        blowout_margin=raw_model["blowout_margin"],
        bin_edges=tuple(raw_model["bin_edges"]),
        probabilities=tuple(raw_model["probabilities"]),
        training_examples=raw_model["training_examples"],
        training_blowout_rate=raw_model["training_blowout_rate"],
        source_version=raw_model["source_version"],
        version=raw_model["version"],
    )
    if model.version != model_version:
        raise RuntimeError(
            f"release registry key {model_version} does not match artifact model {model.version}"
        )
    derived_version = blowout_model_version(
        source_version=model.source_version,
        training_cutoff=model.training_cutoff,
        window_games=model.window_games,
        minimum_history_games=model.minimum_history_games,
        blowout_margin=model.blowout_margin,
        bin_edges=model.bin_edges,
        probabilities=model.probabilities,
    )
    if model.version != derived_version:
        raise RuntimeError("released model version does not match its fitted parameters")
    source_cohorts = final["source_cohorts"]
    training_fingerprint = source_cohorts["training"]["fingerprint"]
    holdout_fingerprint = source_cohorts["held_out"]["fingerprint"]
    if model.source_version != training_fingerprint:
        raise RuntimeError("released model is not bound to its declared training fingerprint")
    return BlowoutRelease(
        evidence_version=payload["evidence_version"],
        model=model,
        training_source_fingerprint=training_fingerprint,
        holdout_source_fingerprint=holdout_fingerprint,
        held_out_examples=final["backtest"]["held_out_examples"],
    )
