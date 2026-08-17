"""Fantrax private-league reads via ``fantraxapi``.

Pinned exactly (``fantraxapi==1.0.1``) because it wraps undocumented internal
infrastructure. See :mod:`hoops_gm.ingest.fantrax_private.client` for what this
adapter claims and — importantly — what it does not.
"""

from hoops_gm.ingest.fantrax_private.client import (
    COOKIE_NAME,
    DEFAULT_MIN_INTERVAL_SECONDS,
    RELOGIN_INSTRUCTIONS,
    FantraxPrivateClient,
    build_session,
)
from hoops_gm.ingest.fantrax_private.cookies import (
    DEFAULT_COOKIE_PATH,
    KEY_ENV_VAR,
    SOURCE,
    CookieStore,
    CookieStoreError,
    generate_key,
)

__all__ = [
    "COOKIE_NAME",
    "DEFAULT_COOKIE_PATH",
    "DEFAULT_MIN_INTERVAL_SECONDS",
    "KEY_ENV_VAR",
    "RELOGIN_INSTRUCTIONS",
    "SOURCE",
    "CookieStore",
    "CookieStoreError",
    "FantraxPrivateClient",
    "build_session",
    "generate_key",
]
