/**
 * The ADR-002 detector, shared by the synthetic and the recorded table tests.
 *
 * **Why text nodes rather than `container.textContent`.** The first version of
 * this check concatenated the whole subtree and asked whether the product's
 * string form appeared in it. On a one-row payload that worked; against the
 * real 60-row cohort it reported 200-odd violations, none of them real. A
 * table's `textContent` runs adjacent cells together with no separator, so
 * `12.34` beside `5.67` becomes `12.345.67` and contains `345` — a substring
 * that exists only at a boundary between two cells and is not a rendered
 * number at all.
 *
 * That is worth recording rather than quietly fixing, because the failure mode
 * was the *opposite* of the one usually worried about: the check was too
 * sensitive, and a check that cries wolf on a correct screen gets deleted or
 * loosened by whoever meets it next, which is how a guard stops guarding. A
 * number cannot span two text nodes, so walking them removes the junction
 * entirely rather than compensating for it.
 *
 * **Why numeric comparison rather than string matching.** A total rendered via
 * `toLocaleString()` is `1,924.5` and a naive string check for `1924.5` misses
 * it — and `toLocaleString` is exactly what someone adding a season-total
 * column would reach for on a four-figure number. Parsing every rendered token
 * back to a number and comparing with a rounding tolerance catches the value
 * however it was formatted.
 */

import { PROJECTION_RATE_FIELDS } from '../api/types'
import type { ProjectionsModel } from '../components/projectionsModel'

/** Every number rendered anywhere in the subtree, however it was formatted. */
export function renderedNumbers(container: HTMLElement): number[] {
  const walker = container.ownerDocument.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  const found: number[] = []

  let node = walker.nextNode()
  while (node !== null) {
    const text = node.textContent ?? ''
    for (const token of text.match(/\d[\d,]*(?:\.\d+)?/g) ?? []) {
      const parsed = Number(token.replace(/,/g, ''))
      if (Number.isFinite(parsed)) found.push(parsed)
    }
    node = walker.nextNode()
  }

  return found
}

/**
 * The smallest product worth testing for.
 *
 * Below this a "total" is indistinguishable from an ordinary rendered quantity
 * — a per-game rate, a games-played assumption, a row count — and asserting on
 * it would produce collisions rather than findings. Every real seasonal total
 * on this screen's data is far above it: the smallest rate that matters times
 * the smallest plausible games assumption still clears three figures.
 */
const MEANINGFUL_TOTAL = 100

/**
 * `rate × assumed_games_played` for every stated assumption in the model.
 *
 * **This is the one product that can be named, and naming it is the limit of
 * what a DOM test can do.** The prohibition is rate × *any* count: a per-week
 * figure, a rest-of-season figure or a games-remaining number would each be
 * the same ADR-002 fusion and none of them is derivable from this payload. The
 * load-bearing defence is structural — `AssumptionState` is a discriminated
 * union, so a games figure is never a bare number beside a rate — and this is
 * a backstop for the single case that trap is most likely to be sprung in.
 */
export function forbiddenProducts(model: ProjectionsModel): { label: string; value: number }[] {
  const products: { label: string; value: number }[] = []

  for (const row of model.rows) {
    if (row.assumption.kind !== 'stated') continue
    for (const field of PROJECTION_RATE_FIELDS) {
      const rate = row.rates[field]
      if (rate === null) continue
      const value = rate * row.assumption.games
      if (value >= MEANINGFUL_TOTAL) {
        products.push({ label: `player ${String(row.playerId)} ${field}`, value })
      }
    }
  }

  return products
}

/**
 * Whether a rendered number is the product, at any plausible rounding.
 *
 * Half a unit covers rounding to whole numbers, which is the coarsest form a
 * season total would sensibly be shown in, and the relative term keeps that
 * honest for four-figure values.
 */
function matches(rendered: number, product: number): boolean {
  return Math.abs(rendered - product) <= 0.5 + Math.abs(product) * 1e-6
}

/** Labels of every forbidden product that appears on screen. Empty is correct. */
export function detectForbiddenProducts(
  container: HTMLElement,
  model: ProjectionsModel,
): string[] {
  const rendered = renderedNumbers(container)
  return forbiddenProducts(model)
    .filter((product) => rendered.some((value) => matches(value, product.value)))
    .map((product) => `${product.label} → ${String(product.value)}`)
}
