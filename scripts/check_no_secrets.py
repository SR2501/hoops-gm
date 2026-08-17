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
        re.compile(r"user_?[Ss]ecret_?[Ii]d\s*[=:]\s*['\"]?[A-Za-z0-9._\-]{12,}"),
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
                if pattern.search(line):
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
