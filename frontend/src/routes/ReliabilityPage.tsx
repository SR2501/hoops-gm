import { useMemo, useState } from 'react'
import { getReliabilityScorecards } from '../api/reliabilityEndpoints'
import { describeReliabilityError } from '../api/reliabilityErrors'
import type {
  CategoryConsistency,
  DistributionSummary,
  ObservedRateEvidence,
  PlayerReliabilityScorecard,
  ReliabilityScorecardsResponse,
} from '../api/reliabilityTypes'
import { useAsync } from '../api/useAsync'
import { AsyncBoundary } from '../components/AsyncBoundary'
import {
  buildReliabilityRows,
  filterReliabilityRows,
  formatNumber,
  formatRate,
  isReliabilityFilter,
  RELIABILITY_FILTER_LABELS,
  RELIABILITY_FILTERS,
  type ReliabilityFilter,
  type ReliabilityRow,
} from '../components/reliabilityScorecardsModel'

export const RELIABILITY_STALE_AFTER_MS = 5 * 60_000
export const RELIABILITY_PAGE_SIZE = 50

const CATEGORY_LABELS: Record<string, string> = {
  fg3m: '3PM',
  pts: 'PTS',
  reb: 'REB',
  ast: 'AST',
  stl: 'STL',
  blk: 'BLK',
  to: 'TO',
  fg_pct: 'FG impact',
  ft_pct: 'FT impact',
}

export function ReliabilityPage() {
  const scorecards = useAsync(getReliabilityScorecards, [], { deferInitialRequest: true })

  return (
    <article className="page reliability">
      <header className="page__header">
        <h1>Reliability</h1>
        <p className="page__lede">
          Direct availability observations and played-game production consistency, kept separate.
          These are historical descriptions, not durability grades, season games played, projected
          games, or <code>p(play)</code>.
        </p>
      </header>

      <AsyncBoundary
        state={scorecards}
        label="reliability scorecards"
        staleAfterMs={RELIABILITY_STALE_AFTER_MS}
        isEmpty={(payload) => payload.scorecards.length === 0}
        emptyMessage="The verified reliability cohort contains no player scorecards."
        describeError={describeReliabilityError}
      >
        {(payload) => <ReliabilityScorecards payload={payload} />}
      </AsyncBoundary>
    </article>
  )
}

function ReliabilityScorecards({ payload }: { payload: ReliabilityScorecardsResponse }) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<ReliabilityFilter>('all')
  const [visibleLimit, setVisibleLimit] = useState(RELIABILITY_PAGE_SIZE)
  const rows = useMemo(() => buildReliabilityRows(payload), [payload])
  const filtered = useMemo(
    () => filterReliabilityRows(rows, query, filter),
    [filter, query, rows],
  )
  const visible = filtered.slice(0, visibleLimit)
  const isSyntheticDemo =
    payload.lineage.schedule_source.startsWith('synthetic-demo:') ||
    payload.lineage.observation_source.startsWith('synthetic-demo:')

  const changeQuery = (value: string) => {
    setQuery(value)
    setVisibleLimit(RELIABILITY_PAGE_SIZE)
  }
  const changeFilter = (value: ReliabilityFilter) => {
    setFilter(value)
    setVisibleLimit(RELIABILITY_PAGE_SIZE)
  }

  return (
    <>
      <section className="reliability__overview" aria-labelledby="reliability-cohort-heading">
        <div>
          <p className="reliability__eyebrow">Evidence season</p>
          <h2 id="reliability-cohort-heading">{payload.season}</h2>
          <p>
            {payload.season_type} season · {payload.lineage.window_start} through{' '}
            {payload.lineage.as_of_date}
          </p>
        </div>
        <dl className="reliability__counts" aria-label="Reliability cohort counts">
          <div>
            <dt>Players</dt>
            <dd data-testid="cohort-scorecards">{payload.counts.scorecards}</dd>
          </div>
          <div>
            <dt>Final games</dt>
            <dd data-testid="cohort-final-games">{payload.counts.final_games}</dd>
          </div>
          <div>
            <dt>Game logs</dt>
            <dd data-testid="cohort-game-logs">{payload.counts.player_game_logs}</dd>
          </div>
          <div>
            <dt>Participation rows</dt>
            <dd data-testid="cohort-participation-rows">
              {payload.counts.participation_rows}
            </dd>
          </div>
        </dl>
      </section>

      {isSyntheticDemo ? (
        <p
          className="reliability__warning reliability__synthetic-warning"
          role="note"
          data-testid="synthetic-demo-warning"
        >
          <strong>Synthetic demo cohort.</strong> Every game, box score, and play/non-play
          observation is invented solely to exercise the interface. This is not historical
          evidence, a projection, a recommendation, calibrated availability, or <code>p(play)</code>.
        </p>
      ) : null}

      <p className="reliability__warning" role="note" data-testid="coverage-warning">
        <strong>Incomplete opportunity coverage.</strong> Rates below use only direct play and
        direct non-play observations. Missing rows are not absences, opportunity coverage is
        unknown, and these rates must not be read as season games played or predictions.
      </p>

      <p className="reliability__limitation" data-testid="roster-limitation">
        <strong>No roster fragility summary is shown.</strong> This endpoint has no fantasy-roster
        identity and defines no composite reliability number. Combining these player observations
        into a roster score here would invent both the membership and the math.
      </p>

      <section className="reliability__browser" aria-labelledby="player-evidence-heading">
        <div className="reliability__browser-header">
          <div>
            <h2 id="player-evidence-heading">Player evidence</h2>
            <p>
              Expand a player for monthly observations and production distributions from games
              played.
            </p>
          </div>
          <div className="reliability__controls">
            <label>
              <span>Search player or id</span>
              <input
                type="search"
                value={query}
                onChange={(event) => changeQuery(event.target.value)}
                placeholder="Name or player id"
              />
            </label>
            <label>
              <span>Evidence filter</span>
              <select
                value={filter}
                onChange={(event) => {
                  if (isReliabilityFilter(event.target.value)) changeFilter(event.target.value)
                }}
              >
                {RELIABILITY_FILTERS.map((value) => (
                  <option key={value} value={value}>
                    {RELIABILITY_FILTER_LABELS[value]}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <p className="reliability__result-count" role="status" data-testid="reliability-result-count">
          Showing {visible.length} of {filtered.length} matching players ({rows.length} in cohort).
        </p>

        {visible.length === 0 ? (
          <p className="state state--empty">No players match this search and evidence filter.</p>
        ) : (
          <div className="reliability__rows" data-testid="reliability-rows">
            <div className="reliability__columns" aria-hidden="true">
              <span>Player</span>
              <span>Availability evidence</span>
              <span>Back-to-back evidence</span>
              <span>Played-game production</span>
            </div>
            {visible.map((row) => (
              <ReliabilityPlayer key={row.card.player_id} row={row} />
            ))}
          </div>
        )}

        {visible.length < filtered.length ? (
          <button
            type="button"
            className="reliability__more"
            onClick={() => setVisibleLimit((current) => current + RELIABILITY_PAGE_SIZE)}
          >
            Show {Math.min(RELIABILITY_PAGE_SIZE, filtered.length - visible.length)} more
          </button>
        ) : null}
      </section>

      <Lineage payload={payload} />
    </>
  )
}

function ReliabilityPlayer({ row }: { row: ReliabilityRow }) {
  const { card } = row
  return (
    <details className="reliability-card" data-player-id={card.player_id}>
      <summary>
        <span className="reliability-card__player">
          <strong>{row.displayName}</strong>
          <small>NBA player id {card.player_id}</small>
        </span>
        <EvidenceSummary evidence={card.availability.overall} />
        <B2BSummary evidence={card.availability.back_to_back} />
        <span className="reliability-card__metric">
          <strong>{card.production.played_games} played games</strong>
          <small>
            Minutes CV {formatNumber(card.production.minutes.coefficient_of_variation, 3)}
          </small>
        </span>
      </summary>
      <div className="reliability-card__detail">
        <AvailabilityDetail card={card} />
        <ProductionDetail card={card} />
      </div>
    </details>
  )
}

function EvidenceSummary({ evidence }: { evidence: ObservedRateEvidence }) {
  return (
    <span className="reliability-card__metric">
      <strong>{formatRate(evidence.observed_play_rate)} direct-observation rate</strong>
      <small>
        {evidence.direct_play} play · {evidence.direct_non_play} non-play ·{' '}
        {evidence.explicit_unknown} explicit unknown
      </small>
    </span>
  )
}

function B2BSummary({ evidence }: { evidence: ObservedRateEvidence }) {
  return (
    <span className="reliability-card__metric">
      <strong>
        {evidence.observed_opportunities === 0
          ? 'No direct B2B play/non-play observations'
          : `${String(evidence.direct_non_play)} non-play of ${String(evidence.observed_opportunities)}`}
      </strong>
      <small>
        {evidence.direct_play} play · {evidence.direct_non_play} non-play ·{' '}
        {evidence.explicit_unknown} explicit unknown · back-to-back subset only
      </small>
    </span>
  )
}

function AvailabilityDetail({ card }: { card: PlayerReliabilityScorecard }) {
  const months = card.availability.monthly_trend
  return (
    <section aria-labelledby={`availability-${String(card.player_id)}`}>
      <h3 id={`availability-${String(card.player_id)}`}>Availability evidence</h3>
      <p>
        Each row repeats the direct-only denominator. No slope or trend direction is fitted.
      </p>
      {months.length === 0 ? (
        <p>No monthly direct observations are available.</p>
      ) : (
        <table className="table reliability-card__table">
          <thead>
            <tr>
              <th scope="col">Month</th>
              <th scope="col">Play</th>
              <th scope="col">Non-play</th>
              <th scope="col">Explicit unknown</th>
              <th scope="col">Direct-only rate</th>
            </tr>
          </thead>
          <tbody>
            {months.map((month) => (
              <tr key={month.month}>
                <th scope="row">{month.month.slice(0, 7)}</th>
                <td>{month.evidence.direct_play}</td>
                <td>{month.evidence.direct_non_play}</td>
                <td>{month.evidence.explicit_unknown}</td>
                <td>{formatRate(month.evidence.observed_play_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

function ProductionDetail({ card }: { card: PlayerReliabilityScorecard }) {
  const minutes = card.production.minutes.distribution_minutes
  return (
    <section aria-labelledby={`production-${String(card.player_id)}`}>
      <h3 id={`production-${String(card.player_id)}`}>Played-game production consistency</h3>
      <p>
        These distributions include games in which the player appeared. A non-play observation is
        never inserted as zero production.
      </p>
      <p className="reliability-card__minutes">
        <strong>Minutes:</strong> mean {formatNumber(minutes.mean)} · sample SD{' '}
        {formatNumber(minutes.sample_standard_deviation)} · observed p20-p80{' '}
        {formatRange(minutes)}
      </p>
      <table className="table reliability-card__table">
        <thead>
          <tr>
            <th scope="col">Category</th>
            <th scope="col">Unit</th>
            <th scope="col">Games</th>
            <th scope="col">Mean</th>
            <th scope="col">Sample SD</th>
            <th scope="col">Observed p20-p80</th>
            <th scope="col">Cohort baseline</th>
          </tr>
        </thead>
        <tbody>
          {card.production.categories.map((category) => (
            <CategoryRow key={category.category} category={category} />
          ))}
        </tbody>
      </table>
    </section>
  )
}

function CategoryRow({ category }: { category: CategoryConsistency }) {
  const ratio = category.ratio_baseline
  return (
    <tr>
      <th scope="row">{CATEGORY_LABELS[category.category] ?? category.category}</th>
      <td>
        {category.unit === 'count'
          ? 'Nightly count'
          : 'Volume-weighted impact (made − cohort rate × attempts)'}
      </td>
      <td>{category.distribution.observed_games}</td>
      <td>{formatNumber(category.distribution.mean, 2)}</td>
      <td>{formatNumber(category.distribution.sample_standard_deviation, 2)}</td>
      <td>{formatRange(category.distribution, 2)}</td>
      <td>
        {ratio
          ? `${String(ratio.made)}/${String(ratio.attempted)} = ${formatRate(ratio.rate)}`
          : 'Not applicable'}
      </td>
    </tr>
  )
}

function formatRange(distribution: DistributionSummary, digits = 1): string {
  return `${formatNumber(distribution.lower_percentile, digits)}–${formatNumber(
    distribution.upper_percentile,
    digits,
  )}`
}

function Lineage({ payload }: { payload: ReliabilityScorecardsResponse }) {
  return (
    <details className="reliability__lineage">
      <summary>Evidence lineage and cohort coverage</summary>
      <dl className="facts">
        <div className="facts__row">
          <dt>Schedule coverage</dt>
          <dd>
            {payload.counts.schedule_context_team_games} context rows for{' '}
            {payload.counts.scheduled_team_games} scheduled team-games
          </dd>
        </div>
        <div className="facts__row">
          <dt>Schedule cohort</dt>
          <dd>
            source <code>{payload.lineage.schedule_source}</code> · version{' '}
            <code>{payload.lineage.schedule_version}</code> · refreshed{' '}
            <code>{payload.lineage.schedule_refreshed_at}</code>
          </dd>
        </div>
        <div className="facts__row">
          <dt>Observation cohort</dt>
          <dd>
            source <code>{payload.lineage.observation_source}</code> · version{' '}
            <code>{payload.lineage.source_version}</code>
          </dd>
        </div>
        <div className="facts__row">
          <dt>Derivation</dt>
          <dd>
            source <code>{payload.lineage.derivation_source}</code> · version{' '}
            <code>{payload.lineage.derivation_version}</code> · computed{' '}
            <code>{payload.lineage.computed_at}</code>
          </dd>
        </div>
      </dl>
    </details>
  )
}
