"""Local-only provisioning for the browser bridge secret."""

from __future__ import annotations

import hashlib
import os
import secrets
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

PAIRING_CODE_LENGTH = 12
PAIRING_TTL_SECONDS = 600
PAIRING_MAX_FAILURES = 5
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass
class _Pairing:
    code_digest: bytes
    code: str
    expires_at: float
    failures: int = 0


class BridgePairing:
    """Thread-safe, in-memory pairing state with an atomic local secret file."""

    def __init__(self, secret_path: Path, configured_secret: str | None) -> None:
        self.secret_path = secret_path
        self._lock = threading.Lock()
        self._pairing: _Pairing | None = None
        self._secret = configured_secret or self._read_secret()

    @property
    def has_secret(self) -> bool:
        return bool(self._secret)

    @property
    def secret(self) -> str | None:
        return self._secret

    def issue_code(self, now: float | None = None) -> str:
        with self._lock:
            if self._secret:
                raise RuntimeError("bridge secret is already configured")
            current = time.monotonic() if now is None else now
            if self._pairing is not None and self._pairing.expires_at > current:
                return self._pairing.code
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(PAIRING_CODE_LENGTH))
            self._pairing = _Pairing(
                code_digest=self._digest(code),
                code=code,
                expires_at=current + PAIRING_TTL_SECONDS,
            )
            return code

    def consume_code(self, code: str, now: float | None = None) -> str:
        with self._lock:
            current = time.monotonic() if now is None else now
            pairing = self._pairing
            if pairing is None or pairing.expires_at <= current:
                self._pairing = None
                raise ValueError("pairing code is expired or invalid")
            if not secrets.compare_digest(self._digest(code), pairing.code_digest):
                pairing.failures += 1
                if pairing.failures >= PAIRING_MAX_FAILURES:
                    self._pairing = None
                raise ValueError("pairing code is expired or invalid")
            if self._secret:
                raise ValueError("bridge secret is already configured")
            secret = secrets.token_urlsafe(32)
            # Keep the code available if persistence fails. The lock makes the
            # check, write, and consume one atomic operation for concurrent
            # requests; a successful write is the commit point.
            self._write_secret(secret)
            self._pairing = None
            self._secret = secret
            return secret

    def _read_secret(self) -> str | None:
        try:
            value = self.secret_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError:
            return None
        return value or None

    def _write_secret(self, value: str) -> None:
        self.secret_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.secret_path.name}.", dir=self.secret_path.parent
        )
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.secret_path)
        except BaseException:
            with suppress(OSError):
                os.unlink(temporary)
            raise

    @staticmethod
    def _digest(value: str) -> bytes:
        return hashlib.sha256(value.encode("utf-8")).digest()
