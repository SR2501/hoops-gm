/**
 * Browser probe harness — drive a real browser over CDP and read the result.
 *
 * jsdom answers *what the component renders*. It cannot answer *what the
 * served page looks like*, and this repository has already shipped one defect
 * that only a real browser could see: the recording panel's entire text
 * content was `Sale Bid Nomination PLAYER SEAT <seats> PRICE Record`, which
 * every unit test was perfectly happy with because every unit test asserted
 * behaviour and none asserted that a reader could learn the behaviour.
 *
 * ## The rule this harness exists to enforce
 *
 * **A measurement that cannot fail is worth nothing.** A probe that reads
 * element *position* returns a number on broken and fixed code alike if the
 * defect changed document *height*; a scan for `could not|cannot|failed`
 * returns true on two working screens because it matches legitimate copy.
 * Both happened here, and both looked like verification.
 *
 * So `--differs-from` encodes the control as an **exit code** rather than as
 * advice in a comment. The workflow it is built for:
 *
 *     # on the code you believe is broken
 *     node scripts/browser_probe.mjs <url> probe.js --save before.json
 *     git checkout <fix>            # or apply the change
 *     node scripts/browser_probe.mjs <url> probe.js --differs-from before.json
 *
 * The second run **exits 1 if the two readings are identical**. A probe that
 * reads the same on both is not evidence about either, and this refuses to let
 * that outcome look like a pass.
 *
 * It deliberately does not check *which way* the reading moved. That is the
 * probe author's claim to make, and a harness that scored direction would be
 * asserting it knew what "fixed" looks like.
 *
 * ## Write probes that count, not probes that scan
 *
 * Assert the **presence** of what should exist, counted. `guidePoints: 4` fails
 * loudly at 0; `hasNoConfusingText: true` is satisfied by a page that rendered
 * nothing at all.
 *
 * And a substring cannot distinguish a *quantity*. Checking whether the seats
 * panel "mentioned" a nominated player returned **true** — because the panel
 * prints the nominee's name against the high bidder as the live-bid caveat,
 * which is textually identical to a holding and is a different thing. The count
 * (`selections_made`) separates them; the substring cannot, in either
 * direction.
 *
 * ## Four environment facts, each of which cost real time
 *
 * 1. **`PUT /json/new?<url>`, not GET.** Modern Chromium rejects the GET form.
 * 2. **Wait on `Page.loadEventFired`, not a sleep** — and then still wait for
 *    *your own* element, because React renders after load.
 * 3. **Headless defaults to a 454px-tall viewport.** Any "does it fit on a
 *    laptop" judgement taken without `Emulation.setDeviceMetricsOverride` is
 *    meaningless. This sets 1440x900 by default.
 * 4. **`PUT /json/close/<id>` answers with the plain string `Target is
 *    closing`, not JSON.** Parsing it unconditionally throws *after* the
 *    measurement has already printed correctly, and on Windows that surfaced as
 *    a libuv assertion and exit code `-1073740791`. **A correct measurement
 *    with a catastrophic exit code is the exact inverse of the truncation trap**
 *    — one throws away good data, the other trusts bad data — and both are
 *    failures to read the exit code as a claim about the thing you care about.
 * 5. **Never call `process.exit()` while the CDP WebSocket is still closing.**
 *    Same libuv assertion, same `-1073740791`, and it replaces whatever exit
 *    code you meant to return. This harness therefore sets `process.exitCode`
 *    and lets the loop drain.
 *
 *    Recorded at length because of *where* it was found: fact 4 above was
 *    already written in this header when the bug bit the `--differs-from`
 *    refusal path, printing the correct message and then returning
 *    `-1073740791` instead of `1`. **The documented trap survived on the one
 *    path that is exercised least** — the failure path — and a caller keying on
 *    the exit code would have read the control's refusal as neither a pass nor
 *    a fail. Writing a trap down does not clear it from your own code, and the
 *    branch that reports failure is the branch nobody runs twice.
 *
 * ## Reading the DOM synchronously after a click reads the *pre-render* state
 *
 * React has not re-rendered yet. Driven, with a control, on the draft board:
 * clicking the `Bid` mode from `Sale` removes the player field, and the reads
 * disagree —
 *
 *     playerFieldBeforeClick:                 true
 *     playerFieldReadSynchronouslyAfterClick: true      <- stale
 *     playerFieldAfterRender:                 false
 *     raceReproduced:                         true
 *
 * The control matters here specifically. An earlier attempt to re-measure this
 * used a transition where the mode clicked was **already active**, so no state
 * changed, both reads agreed, and the agreement was mistaken for evidence that
 * the synchronous read was safe. **A re-measurement that does not change the
 * thing being measured is not a control** — it is the same non-falsifiable
 * reading the rule at the top forbids, wearing the costume of diligence.
 *
 * ## Usage
 *
 *     node scripts/browser_probe.mjs <url> <probe-file.js> [flags]
 *
 *       --save <file>           write the JSON result to <file>
 *       --differs-from <file>   exit 1 if the result equals the saved one
 *       --width / --height      viewport, default 1440x900
 *       --port                  CDP port, default 9222
 *
 * The probe file is evaluated as an expression with `awaitPromise`, so it
 * should be an async IIFE returning a JSON-serialisable value.
 *
 * Start a browser first; this never launches or kills one, because the owner's
 * demo browser must not be a casualty of a probe run:
 *
 *     msedge --headless=new --remote-debugging-port=9222 \
 *            --user-data-dir=<a temp dir OUTSIDE the repo>
 */

import { readFile, writeFile } from 'node:fs/promises'

function parseArgs(argv) {
  const positional = []
  const flags = {}
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg.startsWith('--')) {
      flags[arg.slice(2)] = argv[i + 1]
      i += 1
    } else {
      positional.push(arg)
    }
  }
  return { positional, flags }
}

const { positional, flags } = parseArgs(process.argv.slice(2))
const [url, probePath] = positional

if (!url || !probePath) {
  console.error('usage: node scripts/browser_probe.mjs <url> <probe-file.js> [flags]')
  console.error('       see the header of this file for the flags and the control workflow')
  process.exit(2)
}

const port = flags.port ?? process.env.CDP_PORT ?? '9222'
const width = Number(flags.width ?? 1440)
const height = Number(flags.height ?? 900)

async function cdpHttp(method, path) {
  const response = await fetch(`http://127.0.0.1:${port}${path}`, { method })
  const text = await response.text()
  if (!response.ok) throw new Error(`${method} ${path} -> ${response.status} ${text}`)
  // `/json/close` answers `Target is closing`, which is not JSON. Parsing it
  // unconditionally throws after the measurement has already succeeded.
  try {
    return text ? JSON.parse(text) : null
  } catch {
    return text
  }
}

const expression = await readFile(probePath, 'utf8')

let target
try {
  // PUT, not GET: the GET form is rejected by modern Chromium.
  target = await cdpHttp('PUT', `/json/new?${encodeURIComponent(url)}`)
} catch (cause) {
  console.error(`Could not open a tab on CDP port ${port}. Is a browser running with`)
  console.error(`--remote-debugging-port=${port}? This harness never starts one itself.`)
  console.error(String(cause))
  process.exit(2)
}

const socket = new WebSocket(target.webSocketDebuggerUrl)
let nextId = 0
const pending = new Map()
const oneShot = new Map()

socket.addEventListener('message', (message) => {
  const payload = JSON.parse(message.data)
  if (payload.id !== undefined) {
    const waiter = pending.get(payload.id)
    pending.delete(payload.id)
    if (payload.error) waiter.reject(new Error(JSON.stringify(payload.error)))
    else waiter.resolve(payload.result)
    return
  }
  const listener = oneShot.get(payload.method)
  if (listener) {
    oneShot.delete(payload.method)
    listener(payload.params)
  }
})

function send(method, params = {}) {
  const id = (nextId += 1)
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    socket.send(JSON.stringify({ id, method, params }))
  })
}

function once(method) {
  return new Promise((resolve) => oneShot.set(method, resolve))
}

await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true })
  socket.addEventListener('error', reject, { once: true })
})

const loaded = once('Page.loadEventFired')
await send('Page.enable')
await send('Runtime.enable')
// Without this the viewport is 454px tall and every geometry reading is a
// statement about a window nobody has.
await send('Emulation.setDeviceMetricsOverride', {
  width,
  height,
  deviceScaleFactor: 1,
  mobile: false,
})
await send('Page.navigate', { url })
await loaded

const evaluated = await send('Runtime.evaluate', {
  expression,
  awaitPromise: true,
  returnByValue: true,
})

socket.close()
await cdpHttp('PUT', `/json/close/${target.id}`)
// Give the socket handle a tick to finish closing. Exiting into a closing
// libuv handle trips an assertion on Windows and replaces the exit code.
await new Promise((resolve) => setTimeout(resolve, 50))

if (evaluated.exceptionDetails) {
  console.error('The probe threw:')
  console.error(JSON.stringify(evaluated.exceptionDetails, null, 2))
  process.exitCode = 2
} else {
  const rendered = JSON.stringify(evaluated.result.value, null, 2)
  console.log(rendered)

  if (flags.save) {
    await writeFile(flags.save, `${rendered}\n`, 'utf8')
    console.error(`saved: ${flags.save}`)
  }

  if (flags['differs-from']) {
    const baseline = (await readFile(flags['differs-from'], 'utf8')).trim()
    if (baseline === rendered.trim()) {
      console.error('')
      console.error(`CONTROL FAILED: this reading is identical to ${flags['differs-from']}.`)
      console.error('The probe reads the same on both states, so it is evidence about neither.')
      console.error('Measure something the change actually moves before trusting this probe.')
      // `process.exitCode`, never `process.exit()` — see fact 5 in the header.
      // This is the branch where that bug lived, and it is the branch a caller
      // keying on the exit code most needs to be correct.
      process.exitCode = 1
    } else {
      console.error(`control passed: differs from ${flags['differs-from']}`)
    }
  }
}
