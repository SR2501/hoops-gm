/**
 * The draft board's stale banner must not take up layout space.
 *
 * This is a stylesheet property, so it is asserted against the stylesheet. jsdom
 * computes no layout, and the measurement that actually established the defect
 * was taken in a real browser: sampling `/draft/2` at 40ms for nine seconds gave
 * two distinct page heights, 1522 and 1601, and two distinct positions for the
 * log beneath it, 341 and 420. **Every click target on the screen moved 80px
 * down and back, twice a minute, on a screen whose entire purpose is fast and
 * accurate entry under an auction clock.** A recorder clicking inside that ~40ms
 * window hits whatever slid into the position they aimed at.
 *
 * The rule already existed and already meant to pin the banner — it used
 * `position: sticky`, which keeps an element visible while leaving it fully in
 * the layout flow. That is the specific mistake worth a regression test: the
 * declaration looks like the fix and is not, so someone tidying this later could
 * reasonably put it back.
 *
 * After the change, the same probe with the banner forced on screen: page height
 * unchanged, log position unchanged, banner present. The zero is trustworthy
 * because the banner really was there — `bannerAppeared: true` at 1460ms, and a
 * MutationObserver that recorded the insertion — rather than a measurement taken
 * of an empty screen.
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// Resolved from the vitest root rather than `import.meta.url`, which is not a
// file URL under this transform — the same trap `DraftLog.styles.test.ts`
// documents, which this walked straight into.
const stylesheet = readFileSync(resolve(process.cwd(), 'src/styles.css'), 'utf8')

/** The declarations inside one rule, by selector. Null when it is not there. */
function ruleBody(selector: string): string | null {
  const start = stylesheet.indexOf(`${selector} {`)
  if (start === -1) return null
  const end = stylesheet.indexOf('}', start)
  if (end === -1) return null
  return stylesheet.slice(start + selector.length + 2, end)
}

describe('the draft board stale banner', () => {
  const selector = '.page--draft .stale-banner'

  it('has a rule at all', () => {
    // Every assertion below reads this block. If the selector is ever renamed,
    // `ruleBody` returns null and `toContain` would throw somewhere confusing --
    // so the block's own presence is asserted first, and named.
    expect(ruleBody(selector), `no rule found for \`${selector}\` in styles.css`).not.toBeNull()
  })

  it('is taken out of the layout flow, so appearing moves nothing', () => {
    const body = ruleBody(selector)!
    expect(body).toMatch(/position:\s*fixed/)
    // The declaration this replaced. `sticky` pins the banner to the viewport
    // and still reserves its space, which is how an 80px jump survived a fix
    // whose whole subject was where this banner sits.
    expect(body).not.toMatch(/position:\s*sticky/)
  })

  it('stays inside the viewport it is pinned to', () => {
    const body = ruleBody(selector)!
    // Out of flow means it can overflow the window instead of the document, so
    // the width is capped against the viewport rather than left to the content.
    expect(body).toMatch(/max-width:\s*min\(/)
    expect(body).toMatch(/z-index:/)
  })

  it('keeps the independently loaded source warning inline instead of covering this one', () => {
    const sourceSelector = '.page--draft .source-board-loader .stale-banner'
    const body = ruleBody(sourceSelector)

    expect(body, `no rule found for \`${sourceSelector}\` in styles.css`).not.toBeNull()
    expect(body).toMatch(/position:\s*static/)
    expect(body).toMatch(/box-shadow:\s*none/)
  })
})
