"""Append-only check, v7.

v5 fixed the REFERENCE: compare against `git merge-base origin/main HEAD`, not
`origin/main`. A branch's file stops being a superset of main's the moment main
appends, which has nothing to do with whether the branch edited anything. The
merge-base is the last tree both agree on, hence the only content this branch
could have edited.

v6 fixed the ARTIFACT: compare blob to blob, not blob to working tree. With
core.autocrlf=true and no .gitattributes, every checked-out text file is CRLF in
the working tree and LF in the committed blob, so a working-tree read reports a
containment failure that git will never see.

v7 fixed the CONTRACT, and this one was found by the author of v5 and v6 after
the file was lifted verbatim into the repository. As a personal probe it was
correct, because whoever ran it read the output. As a committed tool it had no
gate behaviour at all:

  * There was no exit path anywhere in the file. A real containment breach
    printed ``CONTAINMENT : False`` and exited 0. Driven in a scratch repo
    before this rewrite.
  * The truncated-control verdict was a hardcoded string. ``"True and VACUOUS"``
    printed whatever the computed value was, so a breach rendered
    ``False   True and VACUOUS`` -- the label contradicting the value beside it.
  * ``base[:200]`` silently becomes the base itself when the base is 200 bytes
    or shorter, so the negative control degenerates into a second run of the
    positive check. Harmless at 1.8 MB, fatal the first time this is pointed at
    a new append-only file, which a generic name invites.

So the controls now gate rather than merely print, an un-runnable control is a
failure rather than a skip, and every label is derived. There is no flag to
switch the controls off: the docstring says both negative controls stay, and a
flag that makes them optional is that instruction being reachable-around by
running the tool the obvious way.

Usage::

    python scripts/check_append_only.py [path ...]

Defaults to ``docs/handoff.md``. Exit 0 if every named file is an append-only
extension of its merge-base blob and both controls behaved; exit 1 otherwise.
"""

import subprocess
import sys

DEFAULT_PATHS = ["docs/handoff.md"]

#: A prefix shorter than this is not a distinguishable control -- see v7 note.
TRUNCATED_CONTROL_BYTES = 200

#: One carriage return. Counted rather than searched for as ``\r\n``, because a
#: lone ``\r`` in a text document is the same defect wearing a different shape.
CR = bytes([13])


def blob(ref: str, path: str) -> bytes:
    return subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, check=True).stdout


def merge_base() -> str:
    return subprocess.run(
        ["git", "merge-base", "origin/main", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def check(path: str, base_ref: str) -> list[str]:
    """Return a list of failure descriptions; empty means this file is clean."""
    failures: list[str] = []
    try:
        base = blob(base_ref, path)
        head = blob("HEAD", path)
    except subprocess.CalledProcessError:
        # A missing path fails rather than skipping, for the same reason an
        # un-runnable control does: a check that silently examines nothing is
        # indistinguishable from one that examined something and was happy.
        print(f"{path}")
        print(f"  CANNOT READ - not present at {base_ref} and/or at HEAD")
        return [f"{path}: could not be read at the merge-base or at HEAD"]

    contained = head.startswith(base)
    print(f"{path}")
    print(f"  base bytes        : {len(base)}")
    print(f"  head bytes        : {len(head)}")
    print(f"  appended          : +{len(head) - len(base)}")
    print(f"  CONTAINMENT       : {contained}")
    base_cr = base.count(CR)
    head_cr = head.count(CR)
    print(f"  CR in base blob   : {base_cr}")
    print(f"  CR in head blob   : {head_cr}")
    if not contained:
        failures.append(f"{path}: base blob is not a byte-prefix of HEAD blob")

    # An append may not *introduce* CRLF. Deliberately a delta rather than
    # "contains no CRLF": docs/handoff.md already carries 149 from 2026-08-28
    # and, the file being append-only, they may not be removable at all. A gate
    # that is red on main from the day it lands is one everybody learns to route
    # around, and the claim that is both true and checkable is that this change
    # added none.
    #
    # Neither existing gate can see this. CONTAINMENT passes, because CRLF in
    # the appended region leaves the prefix untouched. check_doc_terminators.py
    # passes, because it asks only whether the last byte is a newline. Both are
    # right about what they check and both have a domain narrower than the
    # hazard. Two instances landed on 2026-08-28, the second from the same lane
    # as the first, and every gate was green for both.
    added_cr = head_cr - base_cr
    print(f"  CR added by HEAD  : {added_cr}   expected 0")
    if added_cr > 0:
        failures.append(
            f"{path}: HEAD adds {added_cr} CR byte(s) to a region the base keeps pure-LF. "
            f"Write the append in bytes with LF endings - do NOT round-trip the file "
            f"through read_text()/write_text() or Get-Content/Set-Content, which will "
            f"rewrite the base's {base_cr} as well and turn this into a CONTAINMENT failure"
        )

    # Control. A counter that has never been shown to move is not evidence that
    # nothing moved -- and this one is easy to get wrong, because reading a blob
    # through a shell pipeline on Windows silently normalises the bytes being
    # counted.
    seeded_delta = (head + b"\r\n").count(CR) - base_cr
    print(f"  NEG seeded CR     : {seeded_delta}   expected {added_cr + 1}")
    if seeded_delta != added_cr + 1:
        failures.append(
            f"{path}: CR counter did not move under a seeded CRLF; instrument is broken"
        )

    # Control one. Flipping a bit in the base must break containment; if it does
    # not, the comparison is not comparing what it claims to.
    flipped = bytearray(base)
    if flipped:
        flipped[len(flipped) // 2] ^= 0x01
    flip = head.startswith(bytes(flipped))
    print(f"  NEG one-byte flip : {flip}   expected False")
    if flip:
        failures.append(f"{path}: one-byte-flip control did not fail; instrument is broken")

    # Control two. A short prefix must still be contained -- and must be
    # recognisably vacuous, which is why both lengths print.
    if len(base) <= TRUNCATED_CONTROL_BYTES:
        print(
            f"  NEG truncated base: CANNOT RUN - base is {len(base)} bytes, so a "
            f"{TRUNCATED_CONTROL_BYTES}-byte prefix IS the base and this control "
            f"would re-run CONTAINMENT under another name"
        )
        failures.append(f"{path}: truncated-base control could not run")
    else:
        trunc_ok = head.startswith(base[:TRUNCATED_CONTROL_BYTES])
        print(f"  NEG truncated base: {trunc_ok}   expected True, and VACUOUS")
        print(f"                      {TRUNCATED_CONTROL_BYTES} bytes vs base {len(base)}")
        if not trunc_ok:
            failures.append(f"{path}: truncated-base control did not pass")

    return failures


def main() -> None:
    paths = sys.argv[1:] or DEFAULT_PATHS
    base_ref = merge_base()
    print(f"merge-base        : {base_ref}")
    failures: list[str] = []
    for path in paths:
        failures.extend(check(path, base_ref))
    if failures:
        print("FAIL:")
        for failure in failures:
            print(f"  {failure}")
        raise SystemExit(1)
    print("OK")


if __name__ == "__main__":
    main()
