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
 * sensitive, and a check that cries wolf on a correct screen gets loosened by
 * whoever meets it next — in the direction that makes it vacuous. A number
 * cannot span two text nodes, so walking them removes the junction entirely
 * rather than compensating for it.
 *
 * **Why numeric comparison rather than string matching.** A total rendered via
 * `toLocaleString()` is `1,924.5` and a naive string check for `1924.5` misses
 * it — and `toLocaleString` is exactly what someone adding a season-total
 * column would reach for on a four-figure number. Parsing every rendered token
 * back to a number and comparing with a rounding tolerance catches the value
 * however it was formatted.
 *
 * **Why there is no magnitude floor, which is the correction that matters.**
 * This module previously discarded every product below 100, justified by "the
 * smallest rate that matters times the smallest plausible games assumption
 * still clears three figures". Both reviewers measured that against the
 * committed fixture and it is false: **278 of 960 real products fall below
 * 100, including 60 of 60 for steals and 60 of 60 for blocks.** A `Season STL`
 * or `Season BLK` column — two of the nine categories, and exactly the "adds it
 * on purpose believing it useful" mutation this guard exists for — would have
 * rendered the forbidden product for every player while the detector returned
 * `[]`.
 *
 * The floor existed to stop a product colliding with an ordinary rendered rate.
 * That problem is real, and a magnitude cutoff is the wrong answer to it: for
 * steals and blocks the season total genuinely lives in the same numeric range
 * as other per-game rates, so no threshold separates them. **The right question
 * is not "is this number big?" but "is this number one the screen was already
 * going to show?"** So a product is flagged when it appears on screen *and* is
 * not accounted for by any legitimately rendered quantity. See
 * `legitimateValues`, and `discriminableProductCount` for what that costs.
 */

import { PROJECTION_RATE_FIELDS } from '../api/types'
import type { ProjectionsModel } from '../components/projectionsModel'
import { formatRate } from '../components/projectionsModel'

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
 * Every numeric quantity the screen is *entitled* to render, from this payload.
 *
 * A product matching one of these is a coincidence rather than a finding — the
 * value was going to be on screen regardless. A product matching a rendered
 * number that is **not** in this set had to be computed, which is what ADR-002
 * forbids.
 *
 * Rates go through `formatRate` and back, so the set holds what is actually
 * displayed (`8.60`) as well as the stored value (`8.5999…`): the detector
 * compares against the screen, not against the model.
 */
function legitimateValues(model: ProjectionsModel): number[] {
  const values: number[] = []

  for (const row of model.rows) {
    values.push(row.playerId)
    for (const field of PROJECTION_RATE_FIELDS) {
      const rate = row.rates[field]
      if (rate === null) continue
      values.push(rate, Number(formatRate(rate)))
    }
    if (row.assumption.kind === 'stated') values.push(row.assumption.games)
  }

  const { projection_import: imported } = model.lineage
  values.push(
    imported.import_id,
    imported.projection_count,
    imported.row_count,
    imported.matched_count,
    imported.needs_review_count,
    imported.unmatched_count,
    imported.rejected_count,
    model.rows.length,
  )

  return values
}

/**
 * `rate × assumed_games_played` for every stated assumption in the model.
 *
 * **This is the one product that can be named, and naming it is the limit of
 * what a DOM test can do.** The prohibition is rate × *any* count: a per-week
 * figure, a rest-of-season figure or a games-remaining number would each be
 * the same ADR-002 fusion, and none is derivable from this payload. The
 * load-bearing defence is structural — `AssumptionState` is a discriminated
 * union, so a games figure is never a bare number beside a rate — and this is
 * a backstop for the single case that trap is most likely to be sprung in.
 *
 * **It is also scoped to the region it is handed.** Every caller passes a
 * container rendering `ProjectionsTable`, so a season total added to the
 * lineage panel, the integrity banner or the page key would not be seen.
 * `tableColumnHeaders` covers the table's own shape; nothing covers the other
 * regions, and that is stated rather than left to be found.
 */
export function forbiddenProducts(model: ProjectionsModel): { label: string; value: number }[] {
  const products: { label: string; value: number }[] = []

  for (const row of model.rows) {
    if (row.assumption.kind !== 'stated') continue
    for (const field of PROJECTION_RATE_FIELDS) {
      const rate = row.rates[field]
      if (rate === null) continue
      products.push({
        label: `player ${String(row.playerId)} ${field}`,
        value: rate * row.assumption.games,
      })
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
  const legitimate = legitimateValues(model)

  return forbiddenProducts(model)
    .filter((product) => {
      // Accounted for by something the screen was always going to show, so its
      // presence is not evidence anybody computed it.
      if (legitimate.some((value) => matches(value, product.value))) return false
      return rendered.some((value) => matches(value, product.value))
    })
    .map((product) => `${product.label} → ${String(product.value)}`)
}

/**
 * How many products the detector can actually discriminate, **per field**.
 *
 * The coincidence exclusion is not free: a product that happens to equal a
 * legitimately rendered value is invisible, and for steals and blocks — whose
 * season totals share a numeric range with other per-game rates — that happens
 * more often than for points.
 *
 * Exposed so a test can assert coverage per field rather than in aggregate. An
 * aggregate count is exactly what let the previous magnitude floor hide two
 * entire categories while looking well-exercised, so the shape of this return
 * value is the lesson from that finding.
 */
export function discriminableProductCount(model: ProjectionsModel): Record<string, number> {
  const legitimate = legitimateValues(model)
  const counts: Record<string, number> = {}

  for (const field of PROJECTION_RATE_FIELDS) {
    counts[field] = 0
  }
  for (const row of model.rows) {
    if (row.assumption.kind !== 'stated') continue
    const { games } = row.assumption
    for (const field of PROJECTION_RATE_FIELDS) {
      const rate = row.rates[field]
      if (rate === null) continue
      if (!legitimate.some((value) => matches(value, rate * games))) {
        counts[field] = (counts[field] ?? 0) + 1
      }
    }
  }

  return counts
}

/**
 * The table's column headers, so an *added* column fails regardless of what it
 * holds.
 *
 * Independent of the product detector, deliberately. The detector asks "is this
 * specific forbidden value on screen"; this asks "has a column appeared that
 * nobody agreed to", which catches a rest-of-season or per-week column the
 * detector cannot compute and therefore cannot look for.
 */
export function tableColumnHeaders(container: HTMLElement): string[] {
  return [...container.querySelectorAll('thead th')].map((th) => th.textContent?.trim() ?? '')
}
