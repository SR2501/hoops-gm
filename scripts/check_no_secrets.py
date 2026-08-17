"""Enforce the Code gate rule that no secret enters source control.

Runs in CI and is runnable locally:

    python scripts/check_no_secrets.py

Deliberately dumb. It looks for the specific shapes this project's secrets
take — a Fantrax session cookie, a ``userSecretId``, a bridge secret, an API
key — plus the obvious mistake of committing ``.env`` at all. A general-purpose
scanner would find more; this one finds the things that would actually end a
season, and it has no dependencies, so it cannot rot.

Exit code 1 means something matched. Read the output before assuming it is a
false positive.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Files that legitimately describe the shape of a secret without holding one.
ALLOWED_PATHS = {
    ".env.example",
    ".gitignore",
    "scripts/check_no_secrets.py",
    # Contains one deliberately secret-shaped string per pattern, asserting
    # that each is still caught. Without this entry the scanner reports its own
    # test suite, which is both correct and useless.
    "backend/tests/test_secret_scan.py",
}

SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".woff",
    ".woff2",
}

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "Fantrax session cookie",
        re.compile(r"FANTRAXUSER\s*[=:]\s*['\"]?[A-Za-z0-9._\-]{16,}"),
    ),
    (
        "Fantrax userSecretId",
        # Case-insensitive: the environment variable is spelled
        # FANTRAX_USER_SECRET_ID, and the original case-sensitive pattern would
        # not have caught it written that way in a committed file.
        re.compile(r"user_?secret_?id\s*[=:]\s*['\"]?[A-Za-z0-9._\-]{12,}", re.IGNORECASE),
    ),
    (
        "assigned bridge secret",
        re.compile(r"BRIDGE_SECRET\s*[=:]\s*['\"]?\S{8,}"),
    ),
    (
        "assigned API key",
        re.compile(r"[A-Z_]*API_KEY\s*[=:]\s*['\"]?[A-Za-z0-9._\-]{12,}"),
    ),
    (
        "private key block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "AWS access key id",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
]

#: A right-hand side that is obviously *code reading* a secret rather than a
#: literal secret. ``user_secret_id=settings.fantrax_user_secret_id`` and
#: ``user_secret_id=secret.get_secret_value()`` are the shapes that appear all
#: over an adapter that has to pass a credential around, and every one of them
#: matched the ``userSecretId`` pattern above.
#:
#: Suppressed here rather than by adding the files to ``ALLOWED_PATHS``,
#: because allowlisting a whole source file blinds the scanner to a real secret
#: added to it later — and the files that legitimately handle credentials are
#: exactly the files where that would most likely happen.
#:
#: **Lower-case letters, underscores and dots only — no digits.** That is the
#: whole trick, and it was arrived at by watching a looser version swallow
#: ``BRIDGE_SECRET=hunter2hunter2hunter2``. A Python name is
#: ``fantrax_user_secret_id``; a credential is ``abc123def456ghi789jkl``.
#: Requiring the right-hand side to be digit-free keeps every real token shape
#: reportable while dropping the false positives, and a token that happens to
#: contain no digits at all is a narrow enough gap to accept knowingly.
CODE_REFERENCE = re.compile(
    r"""
    [=:]\s*
    [a-z_]+                 # a snake_case name
    (?:\.[a-z_]+)*          # optionally attribute access
    (?:\(\s*\))?            # optionally a no-argument call
    \s*(?:$|[,)\]}#])       # and nothing else of substance after it
    """,
    re.VERBOSE,
)


def is_code_reference(line: str) -> bool:
    """True when the line assigns from an expression, not from a literal."""
    # A quoted value anywhere outside a comment means we cannot be confident,
    # so we do not suppress. Better a false positive with an explanation than a
    # missed credential.
    outside_comment = line.split("#", 1)[0]
    if "'" in outside_comment or '"' in outside_comment:
        return False
    return bool(CODE_REFERENCE.search(line))


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [REPO_ROOT / line for line in result.stdout.splitlines() if line]


def main() -> int:
    files = tracked_files()
    findings: list[str] = []

    for path in files:
        relative = path.relative_to(REPO_ROOT).as_posix()

        if (relative == ".env" or relative.startswith(".env.")) and relative != ".env.example":
            findings.append(f"{relative}: an environment file is tracked by git")
            continue

        if relative in ALLOWED_PATHS or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if not path.is_file():
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for lineno, line in enumerate(content.splitlines(), start=1):
            for label, pattern in PATTERNS:
                if pattern.search(line) and not is_code_reference(line):
                    findings.append(f"{relative}:{lineno}: possible {label}")

    if findings:
        print("Code gate failed - possible secret in source control:\n", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\nIf this is a false positive, add the path to ALLOWED_PATHS with a "
            "comment saying why.",
            file=sys.stderr,
        )
        return 1

    print(f"No secrets found in {len(files)} tracked files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
