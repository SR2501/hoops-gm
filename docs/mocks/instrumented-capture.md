# Instrumented capture — running a mock with the userscript loaded

**This is not the blind mock.** `README.md` in this directory describes running a
mock *without* the tool, to gather uncontaminated market prices. This file
describes the opposite experiment: running a mock **with the userscript loaded**,
to capture what Fantrax's draft room actually puts on the wire.

The two do not substitute for each other and should not be run in the same
session. A blind mock's value is that nothing observed it; an instrumented
capture's entire purpose is to observe.

## The one thing this settles

`draft-tracker-bridge-feed` shipped a recogniser
(`backend/src/hoops_gm/draft/feed/recognise.py`) that has **never been shown a
real Fantrax draft-room payload.** Every fixture behind it was constructed from
`fantraxapi`'s source and from the `/fxpa/req` envelope described in
`docs/adapters/fantrax-private.md` — that is, from a reading of the format
rather than from the format.

State of the claim, in the only wording that is honest: **not disproved,
unestablished.** No test in the repository can move it, because a test can only
exercise the payloads we already imagined. One instrumented mock does move it,
and nothing else does.

The owner has confirmed he expects the board to track picks without manual
entry, and has not planned a degraded mode. So the distance between this
recogniser and reality is currently unmeasured, and it is measured by doing this
once.

## Before you start

- The userscript built and installed — `userscript/README.md`, `npm run build`
  in `userscript/`.
- The backend running locally and paired. The bridge endpoint is authenticated
  by a locally generated secret (ADR-010); an unpaired userscript is silently
  useless, which looks identical to a draft that has not started.
- A scratch database. Do not capture into anything you intend to keep.
- **Somewhere durable to write, chosen before you begin.** The temp directory is
  not it. `scripts/capture_draft_fixtures.py` exists only because an earlier
  hand capture kept no script; this document exists partly because I deleted 81
  probe scripts at the end of a unit and could not get them back.

## The procedure

1. **Join a mock auction or snake draft on Fantrax** — any league, any size. The
   configuration does not need to match the real one for this experiment,
   because we are capturing *shape*, not prices. (It does for the blind mock.
   See `README.md` and R39.)

2. **Open the browser devtools Network tab before the draft room finishes
   loading**, filtered to `fxpa`. The draft room issues its first reads during
   load and they are the ones most likely to carry the initial board state.

3. **Let it run.** Do not bid thoughtfully; you are not gathering market data
   here. What matters is that picks happen and that several of them happen while
   you are watching.

4. **Capture at four moments specifically**, because each is a different shape
   and a recogniser that handles one may not handle the others:
   - **Before the first pick** — an empty board. This is the case that must not
     be confused with a feed that is not working.
   - **After a pick you made.**
   - **After a pick someone else made.**
   - **After a nomination but before it clears**, if it is an auction. An
     in-flight bid is not a completed pick and the two must not read alike.

5. **Save the response bodies, not screenshots.** Right-click the `fxpa/req`
   entry → Copy → Copy response. Also copy the **request** body: the recogniser
   cannot see request URLs (see `docs/adapters/fantrax-private.md` on why it
   must identify a block by its contents), so the request is context for a human
   reader, not input to the parser.

6. **Record the wall-clock time of each capture, from a clock that is not the
   browser's.** This is the only external check available on the timestamps in
   the payload, and this project has already shipped a field that carried a `Z`
   suffix and was not UTC. A self-describing timestamp is a claim, not a fact.

## What to save, and where

Write the bodies to `docs/mocks/captures/YYYY-MM-DD-<site>/` as numbered `.json`
files in capture order, with a short `NOTES.md` giving, per file: what you had
just done, the external wall-clock time, and whether the board on screen matched
what you expected.

**Redact before committing.** Team names and the league id are fine. The session
cookie and `userSecretId` are not, and they travel in the request. `AGENTS.md`:
secrets never land in source.

## What shape to look for

The recogniser refuses a body by emitting one of these reasons. If a capture
produces one, that is the finding — write down which, and against which file:

| Reason | What it means about the payload |
|---|---|
| `envelope_unrecognised` | The outer `/fxpa/req` wrapper is not the shape `fantraxapi` describes. The most serious outcome, because everything downstream assumes it. |
| `no_record_list` | The envelope parsed, but nothing inside it looked like a list of picks. Likely a different block batched into the same response. |
| `no_seat_anchor` | A pick was found but could not be attributed to a team. **Note this is produced by two independent mechanisms** — do not assume which one fired without reading. |
| `record_names_no_player` | A pick with a seat but no identifiable player. |
| `player_external_id_unreadable` | The player is named but the id is not readable. **Fixed 2026-08-28 (#122):** such a record now arrives as an instant carrying `skipped_reason`, is surfaced on `GET`, is never applied and never joins identity matching. It no longer goes silently missing, so if this fires you should *see* it — **and seeing it is still the finding**, because it means real Fantrax ids are not readable by the recogniser, which is a different and larger problem than the surfacing bug that was fixed. Say so loudly. |
| `field_too_large_to_record` | A value exceeded its column. Real Fantrax data is the only way to find out whether our bounds are wrong. |
| `artifact_key_too_long_to_record` | The capture's own locator exceeded its column. |
| `page_error:<code>` | Fantrax returned an error inside a `200`. |

**A capture that produces no refusals is not automatically a success.** Check
that the number of picks the board shows equals the number of picks that
happened. The failure the owner named as disqualifying is *"shows me picks that
already happened or misses one"* — and a miscount produces no reason code.

## The second thing to watch for, which is mine

`capture_order_disputed` is the one refusal this unit **introduced** rather than
removed. It fires when a `(transport, external_id)` group orders differently by
`captured_at` (when the browser saw it) than by arrival (when we received it),
and it then applies **neither** reading.

That is correct when the clocks genuinely disagree. It is a live-board outage if
the userscript sets `captured_at` inconsistently — real picks would be refused
during a real draft, with no manual fallback behind them. **I could not verify
this either way**, because it needs a real capture with more than one payload per
pick. Watch for it explicitly; it is the defect I am least able to rule out.

## Replaying a capture

From `backend/` (there is no virtualenv):

    $env:PYTHONPATH="$PWD\src"

Then drive the saved body through the bridge ingest route the same way
`backend/tests/test_draft_feed.py` does, and compare `feed_status`'s counts and
its freshness figure against your `NOTES.md`. Freshness is reported, not
assumed — if it says the feed is not silent while your notes say the last pick
was six minutes ago, that is a finding.

## What this cannot tell you

A mock draft room is not guaranteed to be the same code path as a real one, and
mock participants behave differently (`README.md` records this for prices; it
applies to shape too, in that autodrafted picks may arrive in bursts that a
human-paced draft never produces). A clean instrumented mock **raises**
confidence in the recogniser. It does not establish that draft night is covered.

Burst arrival is worth capturing deliberately for exactly that reason: if a mock
autodrafts the last several rounds, keep those payloads. They are the closest
thing available to a stress case.
