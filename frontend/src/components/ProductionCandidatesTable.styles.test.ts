import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const stylesheet = readFileSync(resolve(process.cwd(), 'src/styles.css'), 'utf8').replace(
  /\r\n/g,
  '\n',
)

function ruleBody(selector: string): string | null {
  const start = stylesheet.indexOf(`${selector} {`)
  if (start === -1) return null
  const end = stylesheet.indexOf('}', start)
  if (end === -1) return null
  return stylesheet.slice(start + selector.length + 2, end)
}

describe('production-candidate table styling', () => {
  it('contains horizontal overflow inside the evidence table region', () => {
    const body = ruleBody('.production-candidates__table-scroll')

    expect(body).not.toBeNull()
    expect(body).toMatch(/overflow:\s*auto/)
    expect(body).toMatch(/max-width:\s*100%/)
  })

  it('keeps ordinal and player identity visible while category columns scroll', () => {
    const rank = ruleBody(
      '.production-candidates__rank-head,\n.production-candidates__rank',
    )
    const player = ruleBody(
      '.production-candidates__player-head,\n.production-candidates__player',
    )

    expect(rank).not.toBeNull()
    expect(rank).toMatch(/position:\s*sticky/)
    expect(rank).toMatch(/left:\s*0/)
    expect(player).not.toBeNull()
    expect(player).toMatch(/position:\s*sticky/)
    expect(player).toMatch(/left:\s*4\.5rem/)
  })

  it('does not style a positive observation count as healthy green', () => {
    const observed = ruleBody('.production-candidates__health--observed')

    expect(observed).not.toBeNull()
    expect(observed).toMatch(/color:\s*var\(--pending\)/)
    expect(observed).not.toMatch(/--ok/)
  })

  it('gives stored source metadata a prominent, wrapping evidence band', () => {
    const provenance = ruleBody('.production-candidates__source-provenance')
    const values = ruleBody('.production-candidates__source-provenance dd')

    expect(provenance).not.toBeNull()
    expect(provenance).toMatch(/display:\s*grid/)
    expect(provenance).toMatch(/border-block:\s*1px solid var\(--border\)/)
    expect(values).not.toBeNull()
    expect(values).toMatch(/overflow-wrap:\s*anywhere/)
    expect(values).toMatch(/font-weight:\s*700/)
  })
})
