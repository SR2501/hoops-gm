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
    """Call the scanner's own single scanning path.

    Deliberately not a reimplementation of match-and-suppress. The previous
    version of this helper did exactly that, and it is why every test here
    passed while the real scan was missing eleven credential shapes: the tests
    were asserting against a copy of the logic rather than the logic.
    """
    return bool(scanner.scan_line(line))


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
        # JSON. **This is the shape that got through**, and it had nothing to
        # do with the code-reference change: every key pattern required the key
        # to be immediately followed by `=` or `:`, and JSON puts a closing
        # quote in between. The scanner had never been able to see a secret in
        # any JSON file — unnoticed until Phase 2 committed 59,000 lines of
        # fixtures and someone tried to smuggle a credential through one.
        '  "userSecretId": "a1b2c3d4e5f6g7h8",',
        '  "FANTRAXUSER": "s3ss10nc00k13v4lu3",',
        '   "user_secret_id" : "abcdef1234567890"  ,',
        '  "BRIDGE_SECRET": "hunter2hunter2hunter2",',
        '  "OPENAI_API_KEY": "sk-abcdefghijklmnop",',
        # YAML, and a credential interpolated into a query string.
        "  userSecretId: abcdef1234567890",
        'url = f"https://x/y?userSecretId=abcdef1234567890&sport=NBA"',
    ],
)
def test_a_secret_smuggled_into_structured_data_is_caught(scanner: ModuleType, line: str) -> None:
    """Found by attacking the scanner rather than by reading it.

    I predicted this case was safe, reasoning that ``is_code_reference`` can
    never fire on a JSON line because every line is quoted. The reasoning was
    correct and completely irrelevant: the **patterns themselves** never
    matched JSON, so the suppression was never reached. Being right about the
    mechanism I had changed said nothing about the mechanism I had not.
    """
    assert flagged(scanner, line), f"credential smuggled past the scanner: {line!r}"


@pytest.mark.parametrize(
    "line",
    [
        # **The regression.** Suppression was applied to the whole line, so any
        # `name=value` or `key: value` fragment anywhere on it — including
        # inside a trailing comment — silenced a real credential elsewhere on
        # the same line. Every one of these was reported before the suppression
        # was introduced and missed after it, which made the control weaker
        # than the allowlist it was meant to avoid.
        "FANTRAXUSER=A1B2C3D4E5F6G7H8I9J0K1L2  # rotate with: make_creds",
        "FANTRAX_USER_SECRET_ID=A1B2C3D4E5F6G7H8  # owner: steve",
        "aws_key=AKIAIOSFODNN7EXAMPLE, region=us_east",
        "key = -----BEGIN PRIVATE KEY----- , mode=inline",
        "OPENAI_API_KEY=sk1234567890abcdef  # set by: bootstrap",
        "userSecretId=A1B2C3D4E5F6G7H8, sport=nba",
        "BRIDGE_SECRET=hunter2hunter2  # see: runbook",
        "FANTRAXUSER=A1B2C3D4E5F6G7H8I9J0K1L2 ; note: rotate",
        "cookie=FANTRAXUSER=A1B2C3D4E5F6G7H8I9J0 and mode=live",
        "  # FANTRAX_USER_SECRET_ID=A1B2C3D4E5F6G7H8 (old value, kind: legacy)",
        "AKIAIOSFODNN7EXAMPLE  # region: us_east",
    ],
)
def test_a_second_assignment_on_the_line_cannot_silence_a_secret(
    scanner: ModuleType, line: str
) -> None:
    """Suppression is anchored to the matched value, never to the line.

    Note the second case: the case-sensitivity gap closed earlier was closed
    only for a bare line. A trailing comment reopened it.
    """
    assert flagged(scanner, line), f"a second assignment silenced a real secret: {line!r}"


@pytest.mark.parametrize(
    "line",
    [
        "key = -----BEGIN PRIVATE KEY----- , mode=inline",
        "AKIAIOSFODNN7EXAMPLE  # region: us_east",
        "-----BEGIN OPENSSH PRIVATE KEY-----  # from: vault",
    ],
)
def test_non_assignment_patterns_can_never_be_suppressed(scanner: ModuleType, line: str) -> None:
    """A private-key block and an AWS key id are not assignments.

    There is no "this is code reading a credential" reading of either, so
    nothing may silence them. Suppression is opt-in per rule.
    """
    assert flagged(scanner, line)


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


def test_a_credential_planted_in_a_committed_fixture_is_caught(
    scanner: ModuleType,
) -> None:
    """End to end, against a real tracked file, not a string in a list.

    The line-level tests above would all have passed while the scanner was
    blind to JSON, because they were written against the shapes I already had
    in mind. This one plants a credential in a file `git ls-files` actually
    reports and runs the real entry point — the only version of the test that
    could have failed for the right reason.

    The fixture is restored in a `finally`, so a failure here does not leave a
    fake credential in the working tree.
    """
    fixture = REPO_ROOT / "backend" / "tests" / "fixtures" / "nba_static_teams.json"
    original = fixture.read_text(encoding="utf-8")
    planted = original[:1] + '\n  "userSecretId": "a1b2c3d4e5f6g7h8",' + original[1:]
    try:
        fixture.write_text(planted, encoding="utf-8")
        assert scanner.main() == 1, (
            "a credential committed inside a JSON fixture was not detected; "
            "the fixtures are the tens of thousands of lines nobody reads"
        )
    finally:
        fixture.write_text(original, encoding="utf-8")

    assert scanner.main() == 0, "the fixture was not restored cleanly"
