/**
 * The only availability figure on the wire — and it is not ours.
 *
 * `source_games_played_assumptions` is what Basketball Monster assumed about
 * games played when it published the per-game rates beside it. It is the single
 * availability-shaped quantity this backend serves today, and this panel exists
 * to show its **shape across the cohort**, which the projections table cannot:
 * there it is one column among seventeen, read one row at a time, and the thing
 * worth seeing is the spread.
 *
 * **Why the spread is the point.** `AGENTS.md` says a 70-game player and a
 * 55-game player with identical per-game lines are not the same asset. This
 * strip is that sentence drawn: every player in the cohort, sorted, so the range
 * the source is asserting is visible in one glance rather than reconstructed
 * from sixty separate reads.
 *
 * **Three things this panel refuses to do.**
 *
 * - It does not multiply anything. A rate times an assumed games figure
 *   reconstructs the source's own season total, which is the fusion ADR-002
 *   permits only at the expected-games seam, and that seam is not built.
 * - It does not bucket. A bucket boundary is a threshold, a threshold is a
 *   judgement about who is fragile, and nobody has argued one. The bars are
 *   sixty real values in order, with no line drawn through them.
 * - It does not call this a durability measurement. We have not measured, checked
 *   or validated any of it, and the copy says so rather than implying it by
 *   putting the number on a page with our name at the top.
 */

import {
  barPercent,
  type AssumptionPoint,
  type AvailabilitySummary,
} from './reliabilityModel'
import { SeasonNote } from './SeasonNote'

interface AvailabilityAssumptionPanelProps {
  summary: AvailabilitySummary
  /** The source string the endpoint reported, shown rather than assumed. */
  source: string
  /**
   * The season the cohort was imported for, from the payload.
   *
   * Required rather than optional: the whole point of showing it is that a
   * caller cannot render this panel's numbers without saying what season they
   * are about, and an optional prop is one a caller forgets.
   */
  season: string
}

function describePoint(point: AssumptionPoint): string {
  return `${point.name ?? `player ${String(point.playerId)}`}: ${String(point.games)} games assumed`
}

export function AvailabilityAssumptionPanel({
  summary,
  source,
  season,
}: AvailabilityAssumptionPanelProps) {
  const { stated, minimum, maximum } = summary
  const lowest = stated[0] ?? null
  const highest = stated[stated.length - 1] ?? null
  const nothingStated = stated.length === 0

  return (
    <section className="assumptions" data-testid="availability-assumptions">
      <h2>What the source assumed about availability</h2>

      <p className="page__lede">
        <code>{source}</code> published a games-played assumption alongside every per-game
        rate. It is the only availability figure this backend serves.{' '}
        <strong>
          It is their assumption, not our measurement. Nothing in hoops-gm has checked it
          against a single observed game.
        </strong>{' '}
        It is shown here because it is what the availability model will eventually replace,
        so it is worth knowing what is currently standing in for one.
      </p>

      <SeasonNote season={season} testId="assumptions-split" />

      <dl className="facts assumptions__facts">
        <div className="facts__row">
          <dt>Cohort</dt>
          <dd data-testid="assumptions-cohort">
            {summary.cohortSize} player{summary.cohortSize === 1 ? '' : 's'} carrying rates ·{' '}
            {stated.length} with a stated assumption
          </dd>
        </div>
        <div className="facts__row">
          <dt>Range</dt>
          <dd data-testid="assumptions-range">
            {nothingStated ? (
              'Nothing stated, so there is no range to report. That is not a range of zero.'
            ) : (
              <>
                {minimum} to {maximum} games, across {summary.distinctValues} distinct value
                {summary.distinctValues === 1 ? '' : 's'}
                {summary.distinctValues === 1
                  ? ' — every player in this cohort carries the same figure, so the source published no availability signal here at all'
                  : ''}
              </>
            )}
          </dd>
        </div>
        <div className="facts__row">
          <dt>Not stated</dt>
          <dd data-testid="assumptions-not-stated">
            {summary.absent} absent · {summary.unreadable} unreadable · {summary.unexplained}{' '}
            unexplained.{' '}
            {summary.absent + summary.unreadable + summary.unexplained === 0
              ? 'Every player in the cohort carries one, which is what this source guarantees by construction — a row missing its games figure has no divisor and is rejected at import.'
              : 'An absent entry means the source said nothing. It is never zero games.'}
          </dd>
        </div>
        <div className="facts__row">
          <dt>Text vs number</dt>
          <dd data-testid="assumptions-divergence">
            {summary.rawDivergences.length === 0 ? (
              <>
                All {stated.length} stated assumption
                {stated.length === 1 ? '' : 's'} read back to the number beside them. This is
                checked rather than assumed: the endpoint publishes the raw text and the parsed
                value separately, and two fields describing one fact can disagree.
              </>
            ) : (
              <strong className="assumptions__divergence">
                {summary.rawDivergences.length} assumption
                {summary.rawDivergences.length === 1 ? '' : 's'} do not read back to the number
                beside them:{' '}
                {summary.rawDivergences
                  .map(
                    (divergence) =>
                      `player ${String(divergence.playerId)} sent "${divergence.raw}" but carries ${String(divergence.parsed)}`,
                  )
                  .join('; ')}
                . The parsed value is what every other screen shows.
              </strong>
            )}
          </dd>
        </div>
      </dl>

      {nothingStated ? (
        <p className="state state--empty" data-testid="assumptions-empty">
          No player in this cohort carries a stated games-played assumption, so there is nothing
          to draw. An empty strip here would be indistinguishable from a strip of zeroes, which
          is why there is a sentence instead of one.
        </p>
      ) : (
        <figure className="strip" data-testid="assumption-strip">
          <figcaption className="strip__caption">
            Every stated assumption, sorted low to high. Bars run from zero to{' '}
            <strong>{maximum}</strong>, the highest figure in this cohort — not to a season
            length, which this screen would have to import from outside the payload to know.
          </figcaption>

          {/* The bars carry their value in `data-games` so a browser probe can
              read the distribution rather than photograph it, and a `title` so a
              pointer can. They are hidden from assistive technology because
              sixty unlabelled bars are noise there; the numbers a reader needs
              are in the facts above and, per player, in the Source GP column on
              the Projections screen. */}
          <ul className="strip__bars" aria-hidden="true">
            {stated.map((point) => (
              <li
                key={point.playerId}
                className="strip__bar"
                data-testid={`assumption-bar-${String(point.playerId)}`}
                data-games={point.games}
                title={describePoint(point)}
                style={{ height: `${String(barPercent(point.games, maximum))}%` }}
              />
            ))}
          </ul>

          <p className="strip__extremes">
            <span data-testid="assumption-lowest">
              Lowest: {lowest === null ? 'none' : describePoint(lowest)}
            </span>
            <span data-testid="assumption-highest">
              Highest: {highest === null ? 'none' : describePoint(highest)}
            </span>
          </p>

          <p className="page__note">
            The gap between those two is the whole reason this project models availability
            separately. It is also, today, the source&apos;s opinion of that gap rather than
            ours.
          </p>
        </figure>
      )}
    </section>
  )
}
