"""The secret scanner still catches a real secret after being taught to ignore code.

Phase 2 loosened ``scripts/check_no_secrets.py`` so that
``user_secret_id=settings.fantrax_user_secret_id`` — an adapter passing a
credential around, which it must — stops being reported. That loosening is
exactly the sort of change that quietly turns a guard into decoration, so it
gets tests: every pattern is checked against a value that must still be caught.

The alternative, adding the credential-handling files to ``ALLOWED_PATHS``,
would have been worse. Allowlisting a whole source file blinds the scanner to a
real secret added to it later, and the files that legitimately handle
credentials are precisely where that would most likely happen.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_no_secrets.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_no_secrets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_no_secrets"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scanner() -> ModuleType:
    return _load()


def flagged(scanner: ModuleType, line: str) -> bool:
    return any(
        pattern.search(line) and not scanner.is_code_reference(line)
        for _label, pattern in scanner.PATTERNS
    )


@pytest.mark.parametrize(
    "line",
    [
        "FANTRAXUSER=abc123def456ghi789jkl",
        "FANTRAX_USER_SECRET_ID='s3cr3tvalue12345'",
        'userSecretId: "aaaabbbbccccdddd"',
        "BRIDGE_SECRET=hunter2hunter2hunter2",
        'OPENAI_API_KEY="sk-abcdefghijklmnop"',
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "AKIAIOSFODNN7EXAMPLE",
    ],
)
def test_a_real_secret_is_still_caught(scanner: ModuleType, line: str) -> None:
    assert flagged(scanner, line), f"scanner no longer catches: {line!r}"


@pytest.mark.parametrize(
    "line",
    [
        # The lines that made this change necessary.
        "        FantraxOfficialClient(store=store, user_secret_id=user_secret),",
        "        self.user_secret_id = user_secret_id",
        "    fantrax_user_secret_id: SecretStr | None = None",
        "        params[key] = self.user_secret_id",
    ],
)
def test_code_that_merely_handles_a_secret_is_not_flagged(scanner: ModuleType, line: str) -> None:
    assert not flagged(scanner, line), f"false positive on: {line!r}"


def test_a_quoted_literal_is_never_suppressed(scanner: ModuleType) -> None:
    """The suppression must not be defeatable by writing it as an assignment.

    A quoted value on the line means we cannot be confident it is code, so the
    scanner reports it. Better a false positive with an explanation than a
    missed credential.
    """
    assert flagged(scanner, 'user_secret_id = "abcdef1234567890"')
    assert flagged(scanner, "userSecretId: 'abcdef1234567890'")


def test_the_repository_is_clean(scanner: ModuleType) -> None:
    """The scan the Code gate runs, run here too.

    CI runs this script directly. Running it as a test as well means a
    developer finds out before pushing — which matters more than usual right
    now, because CI is not running at all.
    """
    assert scanner.main() == 0
