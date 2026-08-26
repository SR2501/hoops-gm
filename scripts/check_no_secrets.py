"""Enforce the Code gate rule that no secret enters source control.

Runs in CI and is runnable locally:

    python scripts/check_no_secrets.py

Deliberately dumb. It looks for the specific shapes this project's secrets
take — a Fantrax session cookie, a ``userSecretId``, a bridge secret, an API
key — plus the obvious mistake of committing ``.env`` at all. A general-purpose
scanner would find more; this one finds the things that would actually end a
season, and it has no dependencies, so it cannot rot.

**Every key pattern tolerates a closing quote before its separator**, because
JSON writes ``"userSecretId": "value"`` and the original patterns required the
key to be immediately followed by ``=`` or ``:``. They therefore matched
nothing in any JSON file — a blind spot that went unnoticed until Phase 2 added
59,000 lines of committed fixtures and someone tried to smuggle a credential
through one. Found by attacking the scanner rather than by reading it.

Exit code 1 means something matched. Read the output before assuming it is a
false positive.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Rule:
    """One secret shape, and whether a code reference may suppress it.

    ``suppressible`` is per-rule and deliberately narrow. A private-key block
    and an AWS key id are not assignments at all, so there is no "this is code
    reading a credential" reading of them and nothing may silence them.
    """

    label: str
    pattern: re.Pattern[str]
    suppressible: bool = False


#: Patterns capture the value in a ``value`` group, and whether it was quoted
#: in a ``quote`` group. Both matter: the suppression decision looks **only** at
#: the captured value, never at the rest of the line.
#:
#: Every key pattern tolerates a closing quote before its separator, because
#: JSON writes ``"userSecretId": "value"`` and the original patterns required
#: the key to be immediately followed by ``=`` or ``:``. They therefore matched
#: nothing in any JSON file — a blind spot that went unnoticed until Phase 2
#: added tens of thousands of lines of committed fixtures.
RULES: list[Rule] = [
    Rule(
        "Fantrax session cookie",
        re.compile(r"FANTRAXUSER[\"']?\s*[=:]\s*(?P<quote>[\"'])?(?P<value>[A-Za-z0-9._\-]{16,})"),
        suppressible=True,
    ),
    Rule(
        "Fantrax userSecretId",
        # Case-insensitive: the environment variable is spelled
        # FANTRAX_USER_SECRET_ID, and a case-sensitive pattern would not catch
        # it written that way in a committed file.
        re.compile(
            r"user_?secret_?id[\"']?\s*[=:]\s*(?P<quote>[\"'])?(?P<value>[A-Za-z0-9._\-]{12,})",
            re.IGNORECASE,
        ),
        suppressible=True,
    ),
    Rule(
        "assigned bridge secret",
        re.compile(r"BRIDGE_SECRET[\"']?\s*[=:]\s*(?P<quote>[\"'])?(?P<value>\S{8,})"),
        suppressible=True,
    ),
    Rule(
        "assigned API key",
        re.compile(
            r"[A-Z_]*API_KEY[\"']?\s*[=:]\s*(?P<quote>[\"'])?(?P<value>[A-Za-z0-9._\-]{12,})"
        ),
        suppressible=True,
    ),
    Rule(
        "private key block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    Rule(
        "AWS access key id",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
]

#: A captured value that is a Python name rather than a credential:
#: ``user_secret_id``, ``settings.fantrax_user_secret_id``,
#: ``secret.get_secret_value()``. Lower-case letters, underscores and dots
#: only — **no digits**, which is the whole trick. A Python name is
#: ``fantrax_user_secret_id``; a credential is ``abc123def456ghi789jkl``.
#:
#: Suppression exists so an adapter can pass a credential around without the
#: scan reporting it. It is deliberately *not* implemented by adding those
#: files to ``ALLOWED_PATHS``, because allowlisting a whole source file blinds
#: the scanner to a real secret added to it later — and the files that
#: legitimately handle credentials are exactly where that would happen.
CODE_REFERENCE = re.compile(r"^[a-z_]+(?:\.[a-z_]+)*(?:\(\s*\))?$")


def is_code_reference(value: str, *, quoted: bool = False) -> bool:
    """True when a **captured value** is a Python name, not a literal.

    Takes the value, not the line. An earlier version searched the whole line,
    so any ``name=value`` or ``key: value`` fragment anywhere on it — including
    inside a trailing comment — silenced a real credential elsewhere on the
    same line. ``FANTRAXUSER=A1B2C3D4E5F6G7H8I9J0K1L2  # rotate with:
    make_creds`` was reported before that change and missed after it. Eleven
    such lines were, which made the control weaker than the allowlist it was
    introduced to avoid.

    A quoted value is never a code reference, whatever it looks like.
    """
    if quoted:
        return False
    return bool(CODE_REFERENCE.fullmatch(value))


def scan_line(line: str) -> list[str]:
    """Labels of every secret shape found on one line.

    The single scanning path. ``main`` and the tests both call it, so a test
    cannot pass while the real scan is blind — which is precisely what happened
    when the tests reimplemented the match-and-suppress logic themselves.
    """
    found: list[str] = []
    for rule in RULES:
        for match in rule.pattern.finditer(line):
            groups = match.groupdict()
            value = groups.get("value")
            if (
                rule.suppressible
                and value is not None
                and is_code_reference(value, quoted=bool(groups.get("quote")))
            ):
                continue
            found.append(rule.label)
            break
    return found


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
            for label in scan_line(line):
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
