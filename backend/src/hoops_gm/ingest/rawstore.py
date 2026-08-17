"""Raw payload capture, which doubles as the response cache.

Two requirements that look separate turn out to be the same mechanism:

* **Preserve raw payloads before normalising**, so that when a number turns out
  to be wrong the original bytes can be replayed rather than guessed at.
* **Cache responses**, so a multi-season backfill can be re-run after a crash
  without asking ``stats.nba.com`` for two thousand box scores it already gave
  us.

Building those as two systems means two things that can disagree about what was
received. They are one store here: every fetch writes the bytes, and a fetch
that finds a recent enough write returns it instead of going out.

**Bytes on disk, not in the database.** A single ``PlayerGameLogs`` season
response is 26,000 rows; a season backfill is thousands of box scores. Those
belong in files under ``data/`` (already git-ignored), not in rows that every
``SELECT *`` and every backup has to carry. A per-source append-only JSONL index
makes the store auditable — "what did this endpoint return, and when" is a
``grep`` — without a migration or a table that can drift out of step with the
files it describes.

Lookup does not read the index. The path itself encodes source, endpoint and a
hash of the request parameters, so finding the newest capture for a request is
a listing of one small directory rather than a scan of a file that grows all
backfill long.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

#: Characters allowed in a path segment derived from a source or endpoint name.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: Basic ISO-8601, chosen because it sorts lexicographically in timestamp order
#: and contains nothing Windows objects to in a filename.
_STAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"


def _safe(segment: str) -> str:
    cleaned = _UNSAFE.sub("-", segment).strip("-")
    if not cleaned:
        raise ValueError(f"path segment {segment!r} is empty once sanitised")
    return cleaned


def canonical_params(params: dict[str, Any] | None) -> str:
    """A stable text form of request parameters.

    Sorted keys and no whitespace, so that the same logical request produces
    the same cache key regardless of how the caller happened to order a dict.
    """
    return json.dumps(params or {}, sort_keys=True, separators=(",", ":"), default=str)


def request_key(params: dict[str, Any] | None) -> str:
    """Short stable hash of request parameters, used as a directory name."""
    return hashlib.sha256(canonical_params(params).encode("utf-8")).hexdigest()[:16]


#: Parameter names whose values must never be written to the index.
#:
#: The index is append-only plaintext, deliberately greppable, kept forever by
#: design (ADR-006), and never touched by :meth:`RawPayloadStore.prune`. It is
#: also the artefact you would zip up to diagnose a payload problem. A live
#: ``userSecretId`` written there ends up in the same ``data/`` directory as
#: the Fantrax cookie we went to the trouble of encrypting — which makes the
#: encryption theatre.
#:
#: Matched case-insensitively as a substring, so ``userSecretId``,
#: ``user_secret_id`` and ``USER_SECRET_ID`` are all covered without having to
#: enumerate every spelling an upstream might use.
SECRET_PARAM_MARKERS: Final[tuple[str, ...]] = (
    "secret",
    "token",
    "cookie",
    "password",
    "passwd",
    "apikey",
    "api_key",
    "auth",
    "credential",
    "session",
)

REDACTED: Final = "<redacted>"


def redact_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Replace credential-shaped parameter values for logging and indexing.

    **Only for display.** :func:`request_key` hashes the *real* parameters, so
    redaction never changes cache identity — two requests differing only in a
    secret still hash differently, and a capture is still found by the request
    that produced it.
    """
    if not params:
        return params
    redacted: dict[str, Any] = {}
    for key, value in params.items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in SECRET_PARAM_MARKERS):
            redacted[key] = REDACTED
        else:
            redacted[key] = value
    return redacted


@dataclass(frozen=True)
class RawPayloadRef:
    """A capture on disk, plus what is known about how it was obtained."""

    source: str
    endpoint: str
    request_key: str
    fetched_at: datetime
    path: Path
    #: Digest prefix, as embedded in the filename. Enough to tell two captures
    #: apart; not enough to verify one, which is what :meth:`sha256` is for.
    digest_prefix: str
    byte_size: int
    #: Full digest of the uncompressed body. Known when the capture is written;
    #: ``None`` when a reference was reconstructed from a path, because the
    #: filename only carries a prefix and claiming otherwise would be a lie in
    #: the one place whose whole job is knowing what was actually received.
    content_sha256: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    #: The parameters as given, retained so a capture is self-describing.
    params: dict[str, Any] | None = None

    @property
    def age(self) -> timedelta:
        return datetime.now(UTC) - self.fetched_at

    def sha256(self) -> str:
        """Digest of the uncompressed body, computed from the file."""
        if self.content_sha256 is not None:
            return self.content_sha256
        return hashlib.sha256(self.read_bytes()).hexdigest()

    def read_bytes(self) -> bytes:
        with gzip.open(self.path, "rb") as handle:
            return handle.read()

    def read_text(self, encoding: str = "utf-8") -> str:
        return self.read_bytes().decode(encoding)

    def read_json(self) -> Any:
        return json.loads(self.read_text())


class RawPayloadStore:
    """Append-only store of exactly what each source returned.

    Nothing here mutates or deletes a capture. Pruning is a separate,
    deliberate act (:meth:`prune`), never a side effect of writing — the whole
    value of the store is that it still holds the payload from before the thing
    that broke.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # -- writing -----------------------------------------------------------

    def put(
        self,
        *,
        source: str,
        endpoint: str,
        params: dict[str, Any] | None,
        body: bytes,
        http_status: int | None = None,
        content_type: str | None = None,
        fetched_at: datetime | None = None,
    ) -> RawPayloadRef:
        """Write a capture and return a reference to it."""
        moment = fetched_at or datetime.now(UTC)
        if moment.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware")
        moment = moment.astimezone(UTC)

        key = request_key(params)
        digest = hashlib.sha256(body).hexdigest()
        directory = self._key_dir(source, endpoint, key)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{moment.strftime(_STAMP_FORMAT)}-{digest[:12]}.json.gz"

        # mtime=0 so an identical payload compresses to identical bytes; that
        # makes "did this response actually change" a file comparison. The
        # underlying handle is closed explicitly — passing ``path.open("wb")``
        # straight to GzipFile leaks it, because GzipFile closes only the
        # compressor and not a fileobj it was handed.
        with (
            path.open("wb") as handle,
            gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as compressor,
        ):
            compressor.write(body)

        ref = RawPayloadRef(
            source=source,
            endpoint=endpoint,
            request_key=key,
            fetched_at=moment,
            path=path,
            digest_prefix=digest[:12],
            content_sha256=digest,
            byte_size=len(body),
            http_status=http_status,
            content_type=content_type,
            params=params,
        )
        self._append_index(ref)
        return ref

    # -- reading -----------------------------------------------------------

    def latest(
        self, *, source: str, endpoint: str, params: dict[str, Any] | None
    ) -> RawPayloadRef | None:
        """The most recent capture for this exact request, if any."""
        key = request_key(params)
        directory = self._key_dir(source, endpoint, key)
        if not directory.is_dir():
            return None
        captures = sorted(directory.glob("*.json.gz"))
        if not captures:
            return None
        return self._ref_from_path(
            source=source, endpoint=endpoint, key=key, path=captures[-1], params=params
        )

    def fresh(
        self,
        *,
        source: str,
        endpoint: str,
        params: dict[str, Any] | None,
        max_age: timedelta,
        now: datetime | None = None,
    ) -> RawPayloadRef | None:
        """The most recent capture, if it is younger than ``max_age``.

        ``max_age`` of zero or less always misses, which is how a caller asks
        for a guaranteed live fetch without a separate flag.
        """
        if max_age <= timedelta(0):
            return None
        ref = self.latest(source=source, endpoint=endpoint, params=params)
        if ref is None:
            return None
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        return ref if (moment - ref.fetched_at) <= max_age else None

    def history(
        self, *, source: str, endpoint: str, params: dict[str, Any] | None
    ) -> list[RawPayloadRef]:
        """Every capture for a request, oldest first."""
        key = request_key(params)
        directory = self._key_dir(source, endpoint, key)
        if not directory.is_dir():
            return []
        return [
            self._ref_from_path(source=source, endpoint=endpoint, key=key, path=path, params=params)
            for path in sorted(directory.glob("*.json.gz"))
        ]

    def index_entries(self, source: str) -> list[dict[str, Any]]:
        """The audit index for a source, oldest first."""
        path = self._index_path(source)
        if not path.is_file():
            return []
        entries: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries

    # -- maintenance -------------------------------------------------------

    def prune(
        self, *, source: str, endpoint: str, params: dict[str, Any] | None, keep: int = 3
    ) -> int:
        """Delete all but the newest ``keep`` captures for a request.

        Explicit and never automatic. Returns the number removed.
        """
        if keep < 1:
            raise ValueError("keep must be at least 1")
        captures = self.history(source=source, endpoint=endpoint, params=params)
        doomed = captures[:-keep] if len(captures) > keep else []
        for ref in doomed:
            ref.path.unlink()
        return len(doomed)

    # -- internals ---------------------------------------------------------

    def _key_dir(self, source: str, endpoint: str, key: str) -> Path:
        return self.root / _safe(source) / _safe(endpoint) / key

    def _index_path(self, source: str) -> Path:
        return self.root / _safe(source) / "index.jsonl"

    def _append_index(self, ref: RawPayloadRef) -> None:
        path = self._index_path(ref.source)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "fetched_at": ref.fetched_at.isoformat(),
            "endpoint": ref.endpoint,
            "request_key": ref.request_key,
            # Redacted. The index is plaintext, append-only, never pruned, and
            # the thing you would send someone to diagnose a problem.
            # `request_key` above hashes the real parameters, so cache identity
            # is unaffected.
            "params": redact_params(ref.params),
            "http_status": ref.http_status,
            "content_type": ref.content_type,
            "byte_size": ref.byte_size,
            "content_sha256": ref.content_sha256,
            "path": ref.path.relative_to(self.root).as_posix(),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")

    def _ref_from_path(
        self,
        *,
        source: str,
        endpoint: str,
        key: str,
        path: Path,
        params: dict[str, Any] | None,
    ) -> RawPayloadRef:
        stamp, _, digest = path.name.removesuffix(".json.gz").partition("-")
        fetched_at = datetime.strptime(stamp, _STAMP_FORMAT).replace(tzinfo=UTC)
        return RawPayloadRef(
            source=source,
            endpoint=endpoint,
            request_key=key,
            fetched_at=fetched_at,
            path=path,
            digest_prefix=digest,
            byte_size=path.stat().st_size,
            params=params,
        )
