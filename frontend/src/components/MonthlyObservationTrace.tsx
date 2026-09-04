import type { MonthlyRateEvidence } from '../api/reliabilityTypes'
import { formatRate } from './reliabilityScorecardsModel'

export const MONTHLY_OBSERVATION_TRACE_LIMITATION =
  "This visual traces the endpoint's published monthly direct-observation play rate. Months stay in published order; duplicate or out-of-order rows are refused, not repaired here. This is not a fitted trend or slope, season-GP projection, reliability grade, availability model, p(play), or production measure."

export function MonthlyObservationTrace({
  months,
}: {
  months: readonly MonthlyRateEvidence[]
}) {
  if (months.length === 0) {
    return <p>No monthly direct observations are available.</p>
  }

  return (
    <div className="monthly-observation-trace">
      <p className="monthly-observation-trace__limitation">
        {MONTHLY_OBSERVATION_TRACE_LIMITATION}
      </p>
      <ol
        className="monthly-observation-trace__list"
        aria-label="Monthly direct-observation play-rate trace"
      >
        {months.map((month) => {
          const rate = month.evidence.observed_play_rate
          return (
            <li className="monthly-observation-trace__row" key={month.month}>
              <time dateTime={month.month}>{month.month.slice(0, 7)}</time>
              <span
                className={
                  rate === null
                    ? 'monthly-observation-trace__track monthly-observation-trace__track--unavailable'
                    : 'monthly-observation-trace__track'
                }
                aria-hidden="true"
              >
                {rate === null ? null : (
                  <span
                    className="monthly-observation-trace__fill"
                    style={{ inlineSize: `${String(rate * 100)}%` }}
                  />
                )}
              </span>
              <strong className="monthly-observation-trace__rate">{formatRate(rate)}</strong>
              <span className="monthly-observation-trace__denominator">
                {month.evidence.direct_play} direct play + {month.evidence.direct_non_play} direct
                non-play = denominator {month.evidence.observed_opportunities}
              </span>
              <span className="monthly-observation-trace__unknown">
                {month.evidence.explicit_unknown} explicit unknown (outside direct denominator)
              </span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
