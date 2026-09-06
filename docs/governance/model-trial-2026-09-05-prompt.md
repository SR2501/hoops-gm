# Arm prompt — identical for all five arms

Recorded here so a reader can confirm every arm got the same words. Nothing in
it names ADR-016, the reservation prose, or the existence of a trap.

---

Build the backlog item `adr-index-consistency-test` in this repository.

Read `docs/backlog.md` and find the item's own section — it is the authority on
what this task is, and it constrains the design in ways this prompt does not
repeat. Read `docs/decisions/` before you write anything.

The established shape for this kind of work here is a stdlib-only script under
`scripts/` with a test under `backend/tests/`. `scripts/backlog_graph.py` with
`backend/tests/test_backlog_graph.py`, and `scripts/check_doc_terminators.py`,
are the closest existing siblings — follow their conventions.

Your work must pass the Code gate:

- `cd backend; ruff check .`
- `cd backend; ruff format --check .`
- `ruff check scripts` and `ruff format --check scripts` from the repo root
- `cd backend; mypy`
- `cd backend; pytest`

Do not commit, do not push, do not open a pull request. Leave your work in the
working tree.

When you are done, reply with a short report: what you built, what your check
does and does not cover, and anything you found while doing it that you could
not verify. That last part is mandatory and "nothing" is rarely the honest
answer.
