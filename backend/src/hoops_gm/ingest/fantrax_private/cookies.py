"""Encrypted storage for the Fantrax session cookie.

The cookie is the credential for a live account, so it is encrypted at rest and
never committed. This module is the only place that knows how to read or write
it.

**Why a file and an env-var key, rather than the cookie in ``.env``.** The
plan's ``.env`` already documents ``FANTRAX_COOKIE`` as a bootstrap value, and
a bootstrap value is exactly what it should stay. A cookie in a dotfile gets
copied into a shell history, a container env dump, a log line, a screenshot of
a terminal. Splitting it — ciphertext in ``data/``, key in ``.env`` — means
neither artefact alone is a credential, and the one that is easiest to leak
accidentally is the one that is useless on its own.

**On the re-login flow.** ``fantraxapi``'s documented route is a Selenium login
that drives a real browser. That is deliberately *not* implemented here, and
the reasoning belongs on the record rather than in a commit message:

* it needs a browser and a driver in the environment, neither of which exists
  in CI, so it could never be tested where it matters;
* it is brittle in exactly the way a login page is brittle;
* driving the site's own login form is closer to the write path than to
  ingestion, and the write path is `bridge`'s to build and `safety`'s to
  approve. A data adapter quietly growing browser automation is how a
  guardrail boundary erodes.

So what is implemented is the honest half: **detect expiry precisely and tell
the human exactly what to do.** :class:`CredentialsExpired` carries the remedy,
:func:`store_cookie` accepts a fresh value, and the procedure is documented in
``docs/adapters/fantrax-private.md``. Automating the login is a separate
decision, and it is the owner's — it changes the nature of Fantrax access,
which is on the owner-only list.
"""

from __future__ import annotations

import base64
import contextlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hoops_gm.ingest.errors import CredentialsExpired

if TYPE_CHECKING:  # pragma: no cover - typing only
    from cryptography.fernet import Fernet

SOURCE = "fantrax_private"

#: Environment variable holding the Fernet key. Never the cookie itself.
KEY_ENV_VAR = "FANTRAX_COOKIE_KEY"

#: Where the ciphertext lives, relative to the repo root. ``data/`` is already
#: git-ignored.
DEFAULT_COOKIE_PATH = Path("data") / "fantrax_cookie.enc"


class CookieStoreError(RuntimeError):
    """The cookie store is misconfigured, as distinct from the cookie being stale."""


@dataclass(frozen=True)
class CookieStore:
    """Reads and writes the encrypted Fantrax session cookie."""

    path: Path
    key: str

    @classmethod
    def from_environment(cls, *, path: Path | None = None) -> CookieStore:
        key = os.environ.get(KEY_ENV_VAR, "")
        if not key:
            raise CookieStoreError(
                f"{KEY_ENV_VAR} is not set. Generate one with:\n"
                "    python -m hoops_gm.ingest.fantrax_private.cookies --generate-key\n"
                f"then put it in .env as {KEY_ENV_VAR}=... . It is the key, not the "
                "cookie; both are needed and neither is useful alone."
            )
        return cls(path=path or DEFAULT_COOKIE_PATH, key=key)

    # -- reading -----------------------------------------------------------

    def exists(self) -> bool:
        return self.path.is_file()

    def read(self) -> str:
        """Decrypt and return the cookie.

        Raises :class:`CredentialsExpired` when there is nothing stored, because
        from the caller's point of view "no cookie" and "stale cookie" need the
        same action from the same person.
        """
        if not self.exists():
            raise CredentialsExpired(
                f"no stored Fantrax cookie at {self.path}. Follow "
                "docs/adapters/fantrax-private.md to capture one, then run "
                "`python -m hoops_gm.ingest.fantrax_private.cookies --store`",
                source=SOURCE,
            )
        fernet = self._fernet()
        try:
            decrypted: bytes = fernet.decrypt(self.path.read_bytes())
        except Exception as exc:
            raise CookieStoreError(
                f"could not decrypt {self.path}. The most likely cause is that "
                f"{KEY_ENV_VAR} changed since the cookie was stored. Store the "
                "cookie again with the current key."
            ) from exc
        return decrypted.decode("utf-8")

    # -- writing -----------------------------------------------------------

    def write(self, cookie: str) -> Path:
        """Encrypt and store a cookie, replacing any previous one."""
        value = cookie.strip()
        if not value:
            raise CookieStoreError("refusing to store an empty cookie")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self._fernet().encrypt(value.encode("utf-8")))
        # Best effort on POSIX; a no-op on Windows, where the ACL inherited
        # from the user profile directory is already the protection.
        with contextlib.suppress(OSError):  # pragma: no cover - platform dependent
            self.path.chmod(0o600)
        return self.path

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)

    # -- internals ---------------------------------------------------------

    def _fernet(self) -> Fernet:
        try:
            from cryptography.fernet import Fernet as FernetImpl
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise CookieStoreError(
                "the 'cryptography' package is required for encrypted cookie "
                "storage. Install the ingest extra: pip install -e '.[ingest]'"
            ) from exc
        try:
            return FernetImpl(self.key.encode("utf-8"))
        except Exception as exc:
            raise CookieStoreError(
                f"{KEY_ENV_VAR} is not a valid Fernet key. Generate one with "
                "`python -m hoops_gm.ingest.fantrax_private.cookies --generate-key`."
            ) from exc


def generate_key() -> str:
    """A fresh Fernet key, for ``.env``.

    Falls back to raw ``urandom`` when ``cryptography`` is absent so that the
    setup instruction works before the extra is installed. Fernet keys are
    url-safe base64 of 32 random bytes either way.
    """
    try:
        from cryptography.fernet import Fernet as FernetImpl
    except ImportError:  # pragma: no cover - dependency guard
        return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    return FernetImpl.generate_key().decode("ascii")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - operator tool
    import argparse
    import getpass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate-key", action="store_true")
    parser.add_argument("--store", action="store_true", help="prompt for a cookie and store it")
    parser.add_argument("--path", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.generate_key:
        print(f"{KEY_ENV_VAR}={generate_key()}")
        print("\nPut that line in .env. It is the key, not the cookie.")
        return 0

    if args.store:
        store = CookieStore.from_environment(path=args.path)
        # getpass so the cookie never lands in a shell history.
        cookie = getpass.getpass("Fantrax session cookie (input hidden): ")
        written = store.write(cookie)
        print(f"Stored encrypted cookie at {written}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
