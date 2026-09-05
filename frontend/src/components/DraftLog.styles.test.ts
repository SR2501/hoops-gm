/**
 * A guard on one styling decision, because measuring it once is not a mitigation.
 *
 * A withdrawn log entry has to recede — it is no longer in force — but the badge
 * that says *why* it receded is the single marker separating "this was recorded"
 * from "this no longer counts", and it is what a recorder scans for straight
 * after a correction. This screen originally dimmed the whole row with
 * `opacity: 0.55`, which took the badge down with it: measured in a browser it
 * came out at 3.83:1 against the panel at 10.3px, below AA and the least legible
 * element on the screen carrying the most consequential distinction on it.
 * Applying the de-emphasis as colour instead put the badge at 9.33:1 at
 * 11.25px/600, with the struck description at 6.72:1.
 *
 * jsdom does not cascade a real stylesheet, so those ratios cannot be re-measured
 * here — they were driven in a browser and are recorded in docs/handoff.md. What
 * *can* be guarded is the structural cause: `opacity` on the row is a dimming a
 * child cannot opt out of, so the rule must not reintroduce it. That is the
 * mechanism; the ratios are the evidence for why it exists.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// Resolved from the vitest root rather than `import.meta.url`, which is not a
// file URL under this transform. A wrong path would throw here rather than
// yielding an empty string, and the first test below pins the length anyway.
const stylesheetPath = resolve(process.cwd(), 'src/styles.css')
const stylesheet = readFileSync(stylesheetPath, 'utf8')

/** Body of every rule whose selector list mentions `needle`, in source order. */
function ruleBodiesMentioning(needle: string): string[] {
  const bodies: string[] = []
  const pattern = /([^{}]+)\{([^{}]*)\}/g
  let match: RegExpExecArray | null
  while ((match = pattern.exec(stylesheet)) !== null) {
    if (match[1]!.includes(needle)) bodies.push(match[2]!)
  }
  return bodies
}

describe('the withdrawn-entry styling', () => {
  it('has rules to examine at all, so the assertions below are not vacuous', () => {
    // The failure this exists to prevent: the selector gets renamed, every
    // search finds nothing, and a test over an empty set reports success.
    expect(stylesheet.length).toBeGreaterThan(1000)
    expect(ruleBodiesMentioning('.log__entry--voided').length).toBeGreaterThanOrEqual(3)
  })

  it('never dims the whole row, because a child cannot escape a parent opacity', () => {
    const bodies = ruleBodiesMentioning('.log__entry--voided')
    const dimming = bodies.filter((body) => /(^|[;{\s])opacity\s*:/.test(body))

    expect(bodies.length).toBeGreaterThan(0)
    expect(dimming).toEqual([])
  })

  it('still marks a withdrawn entry as struck through, so it reads as withdrawn', () => {
    // The badge being legible must not have been bought by dropping the
    // de-emphasis altogether: both claims have to hold at once.
    const struck = ruleBodiesMentioning('.log__entry--voided .log__what')

    expect(struck.length).toBeGreaterThan(0)
    expect(struck.some((body) => body.includes('line-through'))).toBe(true)
    expect(struck.some((body) => body.includes('--text-muted'))).toBe(true)
  })

  it('gives the badge its own weight and size rather than inheriting the muted text', () => {
    const badge = ruleBodiesMentioning('.log__entry--voided .log__badge')

    expect(badge).toHaveLength(1)
    expect(badge[0]).toMatch(/font-weight:\s*600/)
    expect(badge[0]).toMatch(/font-size:/)
    // It must not be recoloured to the muted text it sits beside — the amber is
    // what makes it findable.
    expect(badge[0]).not.toMatch(/--text-muted/)
  })
})

describe('the draft correction affordance hierarchy', () => {
  it('keeps Try to void quieter than the guaranteed Undo at rest', () => {
    const sure = ruleBodiesMentioning('.log__undo--sure')
    const maybe = ruleBodiesMentioning('.log__undo--maybe').find((body) =>
      body.includes('background: transparent'),
    )

    expect(sure.some((body) => body.includes('background: var(--accent)'))).toBe(true)
    expect(sure.some((body) => /font-weight:\s*600/.test(body))).toBe(true)
    expect(maybe, 'no resting rule found for `.log__undo--maybe`').toBeDefined()
    expect(maybe).toMatch(/border:\s*1px dashed var\(--border\)/)
    expect(maybe).toMatch(/color:\s*var\(--text-muted\)/)
    expect(maybe).not.toMatch(/font-weight:/)
    expect(maybe).not.toMatch(/background:\s*var\(--accent\)/)
  })

  it('proves Try to void is interactive on hover and keyboard focus without changing its size', () => {
    const hover = ruleBodiesMentioning('.log__undo--maybe:not(:disabled):hover')
    const focus = ruleBodiesMentioning('.log__undo--maybe:not(:disabled):focus-visible')

    expect(hover).toHaveLength(1)
    expect(focus).toEqual(hover)
    expect(hover[0]).toMatch(/background:\s*var\(--bg-raised\)/)
    expect(hover[0]).toMatch(/border-color:\s*var\(--accent\)/)
    expect(hover[0]).toMatch(/border-style:\s*solid/)
    expect(hover[0]).toMatch(/color:\s*var\(--text\)/)
    expect(hover[0]).not.toMatch(/padding:|margin:|font-size:|font-weight:/)
  })

  it('gives a press its own immediate state without moving neighbouring controls', () => {
    const active = ruleBodiesMentioning('.log__undo--maybe:not(:disabled):active')

    expect(active).toHaveLength(1)
    expect(active[0]).toMatch(/background:\s*color-mix\(/)
    expect(active[0]).toMatch(/border-color:\s*var\(--accent\)/)
    expect(active[0]).toMatch(/color:\s*var\(--accent\)/)
    expect(active[0]).toMatch(/transform:\s*translateY\(1px\)/)
    expect(active[0]).not.toMatch(/padding:|margin:|width:|height:|font-size:|font-weight:/)
  })
})
