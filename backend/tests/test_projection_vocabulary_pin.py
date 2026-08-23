"""The pin behind a user-facing claim on the projections screen.

**Why this test exists, and why it lives here rather than in the frontend.**

`frontend/src/routes/ProjectionsPage.tsx` tells the reader, in the key above the
projections table:

    A `·` should not appear for Basketball Monster: its import profile requires
    every rate shown here and a games-played figure, and a row missing any of
    them is rejected rather than stored. If one appears, something upstream has
    changed.

That sentence turns an absence marker from something a reader would take for
ordinary sparseness into a signal that something is wrong. It is true today, and
it rests entirely on a property that **nothing enforced** when it was written:
Basketball Monster's ``required_production_fields`` being set-equal to
``CANONICAL_STAT_FIELDS``.

The chain, so the next reader can check it rather than trust it:

* ``CANONICAL_STAT_FIELDS`` is the published rate vocabulary —
  ``api/routes/projections.py``'s ``_rates()`` splats it into
  ``ProjectionRates``, so every member reaches the wire and the screen.
* ``parser.py`` builds ``missing_required_values`` from
  ``profile.required_production_fields`` and refuses the row when that list is
  **non-empty** — ``any``, not ``all``.
* So while the two are set-equal, every stored Basketball Monster row carries a
  value for every field the screen renders, and the screen's claim holds.

**The failure this prevents.** Add a canonical field without adding it to
Basketball Monster's required set, and it is legitimately ``NULL`` in a stored
row while ``_rates()`` still serves it. The screen renders ``·`` for it —
routine sparseness — under a key still telling the reader that seeing one means
something upstream changed. The screen becomes actively misleading, via a
one-line tuple edit, and no other test in this suite opposes it: before this
file, ``grep required_production_fields backend/tests/`` returned nothing.

``docs/governance/ownership.md`` already declares ``CANONICAL_STAT_FIELDS`` a
cross-owner seam, but it pins the vocabulary against the *wire*. This pins it
against what the profile *requires*, which is the half the copy depends on.

**If this test fails, do not delete the assertion.** Either add the new field to
Basketball Monster's ``required_production_fields`` — making the screen's claim
true again — or change the copy in ``ProjectionsPage.tsx`` and the
``AssumptionState`` docstring in ``frontend/src/components/projectionsModel.ts``
to stop claiming it. The two must move together.
"""

from __future__ import annotations

import dataclasses

import pytest

from hoops_gm.ingest.projections.profiles import (
    BASKETBALL_MONSTER_PROFILE,
    CANONICAL_STAT_FIELDS,
)


def test_basketball_monster_requires_every_published_rate_field() -> None:
    """Set-equal in both directions, asserted as sets rather than as counts.

    Counts would pass on a swap — one field dropped and another added keeps the
    length identical while changing the members, and that is precisely the edit
    a partial rename produces. Both differences are reported so a failure names
    which side drifted rather than only that something did.
    """
    canonical = set(CANONICAL_STAT_FIELDS)
    required = set(BASKETBALL_MONSTER_PROFILE.required_production_fields)

    assert canonical - required == set(), (
        "these canonical fields reach the projections wire but are not required by the "
        "Basketball Monster profile, so they can be NULL in a stored row - the "
        "projections screen's key currently tells the reader that cannot happen"
    )
    assert required - canonical == set(), (
        "the Basketball Monster profile requires fields that are not in the published "
        "rate vocabulary, so they are validated but never served"
    )


@pytest.mark.parametrize("side", ["canonical", "required"])
def test_the_pin_fails_when_either_side_drifts(side: str) -> None:
    """The mutation check, from **both** sides.

    A guard nobody has watched fail is a guard nobody has tested. Dropping a
    field from either tuple must break set-equality; asserting only the
    forward direction would let the reverse drift pass, which is the
    one-directional-comparison defect recorded in ``docs/governance/gates.md``.
    """
    canonical = set(CANONICAL_STAT_FIELDS)
    required = set(BASKETBALL_MONSTER_PROFILE.required_production_fields)

    if side == "canonical":
        # A new canonical field nobody added to the required set: the exact
        # edit that would falsify the screen's copy.
        canonical.add("double_doubles_per_game")
    else:
        mutated = dataclasses.replace(
            BASKETBALL_MONSTER_PROFILE,
            required_production_fields=tuple(
                field
                for field in BASKETBALL_MONSTER_PROFILE.required_production_fields
                if field != "steals_per_game"
            ),
        )
        required = set(mutated.required_production_fields)

    assert canonical != required, (
        f"mutating the {side} side did not break set-equality, so the assertion above "
        "would pass over a drifted vocabulary and prove nothing"
    )
