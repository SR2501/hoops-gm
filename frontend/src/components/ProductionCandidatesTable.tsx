import { Fragment, useState } from 'react'
import { productionSourceLabel } from '../api/productionCandidatesLabels'
import type {
  ProductionCandidate,
  ProductionCandidatesResponse,
  ProductionCategoryKey,
  ProductionCategoryScale,
  ProductionRateField,
} from '../api/productionCandidatesTypes'

const CATEGORY_LABELS: Record<ProductionCategoryKey, string> = {
  pts: 'PTS',
  reb: 'REB',
  ast: 'AST',
  stl: 'STL',
  blk: 'BLK',
  fg3m: 'FG3M',
  to: 'TO',
  fg_pct: 'FG impact',
  ft_pct: 'FT impact',
}

const RATE_LABELS: Record<ProductionRateField, string> = {
  points_per_game: 'Points per game',
  rebounds_per_game: 'Rebounds per game',
  assists_per_game: 'Assists per game',
  steals_per_game: 'Steals per game',
  blocks_per_game: 'Blocks per game',
  turnovers_per_game: 'Turnovers per game',
  three_pointers_made_per_game: 'Three-pointers made per game',
  field_goals_made_per_game: 'Field goals made per game',
  field_goals_attempted_per_game: 'Field goals attempted per game',
  free_throws_made_per_game: 'Free throws made per game',
  free_throws_attempted_per_game: 'Free throws attempted per game',
}

const SIMPLE_RATE_FIELDS: readonly ProductionRateField[] = [
  'points_per_game',
  'rebounds_per_game',
  'assists_per_game',
  'steals_per_game',
  'blocks_per_game',
  'three_pointers_made_per_game',
  'turnovers_per_game',
]

export function ProductionCandidatesTable({
  payload,
}: {
  payload: ProductionCandidatesResponse
}) {
  const [expandedPlayers, setExpandedPlayers] = useState<ReadonlySet<number>>(
    () => new Set(),
  )

  function togglePlayer(playerId: number) {
    setExpandedPlayers((current) => {
      const next = new Set(current)
      if (next.has(playerId)) {
        next.delete(playerId)
      } else {
        next.add(playerId)
      }
      return next
    })
  }

  return (
    <>
      <section
        className="production-candidates__scope"
        aria-labelledby="production-candidates-scope-heading"
        data-testid="production-candidates-scope"
      >
        <div className="production-candidates__scope-heading">
          <h2 id="production-candidates-scope-heading">
            Production-only · relative to the selected {productionSourceLabel(payload.source)} pool
          </h2>
          <dl
            className="production-candidates__source-provenance"
            data-testid="production-source-provenance"
          >
            <div>
              <dt>Stored source label</dt>
              <dd>{payload.source_display_name}</dd>
            </div>
            <div>
              <dt>Original filename</dt>
              <dd>
                {payload.source_original_filename === null ? (
                  <span className="production-candidates__unavailable">Not recorded</span>
                ) : (
                  <code>{payload.source_original_filename}</code>
                )}
              </dd>
            </div>
          </dl>
          <p>
            Source projections are passed through an explicit single-source identity blend and
            the production scorer. They are not independently produced forecasts, season values,
            expected games, market prices, or availability-adjusted rankings. The stored publisher
            label and filename are display metadata, not independently verified publisher identity,
            authenticity proof, a source classifier, or numeric fingerprint inputs.
          </p>
        </div>

        <dl className="production-candidates__context">
          <div>
            <dt>Source release</dt>
            <dd>
              <code>{payload.source}</code> · season {payload.season} · import{' '}
              {payload.lineage.projection_import.import_id}
            </dd>
            <dd>
              Admitted{' '}
              <time dateTime={payload.lineage.projection_import.imported_at}>
                {payload.lineage.projection_import.imported_at}
              </time>
            </dd>
            <dd>
              Profile <code>{payload.lineage.projection_import.profile_id}</code> v
              {payload.lineage.projection_import.profile_version}
            </dd>
            <dd>
              Response generated <time dateTime={payload.generated_at}>{payload.generated_at}</time>
            </dd>
          </div>
          <div>
            <dt>Scoring release</dt>
            <dd>
              Model <code>{payload.lineage.score.model_version}</code>
            </dd>
            <dd>
              {payload.lineage.scoring_profile.name} · profile{' '}
              {payload.lineage.scoring_profile.id} v{payload.lineage.scoring_profile.version}
            </dd>
          </div>
          <div>
            <dt>Reference and draft</dt>
            <dd data-testid="production-reference-counts">
              {payload.reference.count} scored before draft exclusion ·{' '}
              {payload.reference.excluded_drafted_player_ids.length} excluded ·{' '}
              {payload.reference.candidate_count} candidates
            </dd>
            <dd>
              Draft {payload.draft_id} · {payload.draft_status} · revision{' '}
              {payload.draft_last_sequence}
            </dd>
          </div>
          <div data-testid="production-replacement-context">
            <dt>Replacement context</dt>
            <dd>
              {payload.replacement.team_count} × {payload.replacement.roster_size} ={' '}
              {payload.replacement.structural_roster_count} structural slots · replacement ordinal{' '}
              {payload.replacement.replacement_ordinal}
            </dd>
            <dd>
              Structural shortfall {payload.replacement.structural_roster_shortfall} · replacement
              ordinal shortfall {payload.replacement.replacement_ordinal_shortfall}
            </dd>
          </div>
        </dl>
      </section>

      <div
        className="production-candidates__warning"
        role="note"
        data-testid="production-calibration-warning"
      >
        <strong>Descriptive use only.</strong> Calibration is{' '}
        <code>{payload.calibration_status}</code>. The import timestamp{' '}
        <time dateTime={payload.lineage.projection_import.imported_at}>
          {payload.lineage.projection_import.imported_at}
        </time>{' '}
        says when this application admitted the file; it is not a vendor as-of timestamp or
        freshness validation. Frozen retrospective carry-forward evidence does not calibrate the
        currently selected vendor forecast.
      </div>

      <ReplacementNotice payload={payload} />
      <HealthContextNotice payload={payload} />

      <div
        className="production-candidates__table-scroll"
        role="region"
        aria-label="Production-only candidate ranking"
        tabIndex={0}
      >
        <table className="table production-candidates__table" data-testid="production-candidates-table">
          <caption>
            Server-ordered production scores. Category components are already directed by the
            scorer; the browser does not sort, rescore, or reverse turnovers.
          </caption>
          <thead>
            <tr>
              <th scope="col" className="production-candidates__rank-head">
                Ordinal
              </th>
              <th scope="col" className="production-candidates__player-head">
                Player
              </th>
              <th scope="col" className="production-candidates__total-head">
                Total z
              </th>
              {payload.category_scales.map((scale) => (
                <th
                  scope="col"
                  key={scale.category_key}
                  title={componentHeadingTitle(scale)}
                >
                  {CATEGORY_LABELS[scale.category_key]} z
                </th>
              ))}
              <th scope="col">Historical rows</th>
              <th scope="col">VOR</th>
              <th scope="col">Evidence</th>
            </tr>
          </thead>
          <tbody>
            {payload.candidates.length === 0 ? (
              <tr>
                <td
                  colSpan={payload.category_scales.length + 6}
                  className="production-candidates__empty"
                >
                  The full reference pool was scored, but no undrafted candidates remain.
                </td>
              </tr>
            ) : (
              payload.candidates.map((candidate) => {
                const expanded = expandedPlayers.has(candidate.player_id)
                const detailId = `production-candidate-evidence-${String(candidate.player_id)}`
                return (
                  <Fragment key={candidate.player_id}>
                    <tr
                      className="production-candidates__candidate"
                      data-testid={`production-candidate-${String(candidate.player_id)}`}
                    >
                      <td className="production-candidates__rank">{candidate.ordinal}</td>
                      <th scope="row" className="production-candidates__player">
                        <span>{candidate.full_name}</span>
                        <small>
                          {candidate.team_abbreviation === null
                            ? 'No NBA team label'
                            : `${candidate.team_abbreviation} · NBA team label only`}
                        </small>
                      </th>
                      <td className="production-candidates__score production-candidates__score--total">
                        {formatScore(candidate.total_z)}
                      </td>
                      {candidate.components.map((component) => (
                        <td
                          className="production-candidates__score"
                          key={component.category_key}
                          data-category-key={component.category_key}
                        >
                          {formatScore(component.z_score)}
                        </td>
                      ))}
                      <td>
                        <CandidateHealthSummary candidate={candidate} payload={payload} />
                      </td>
                      <td
                        className={
                          candidate.value_above_replacement === null
                            ? 'production-candidates__unavailable'
                            : 'production-candidates__score'
                        }
                      >
                        {candidate.value_above_replacement === null
                          ? 'Unavailable'
                          : formatScore(candidate.value_above_replacement)}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="production-candidates__evidence-toggle"
                          aria-expanded={expanded}
                          aria-controls={detailId}
                          onClick={() => togglePlayer(candidate.player_id)}
                        >
                          {expanded ? 'Hide evidence' : 'Why'}
                        </button>
                      </td>
                    </tr>
                    {expanded ? (
                      <tr className="production-candidates__detail-row">
                        <td colSpan={payload.category_scales.length + 6}>
                          <CandidateEvidence
                            candidate={candidate}
                            payload={payload}
                            id={detailId}
                          />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <LineageAndLimitations payload={payload} />
    </>
  )
}

function ReplacementNotice({ payload }: { payload: ProductionCandidatesResponse }) {
  const { replacement } = payload
  return (
    <p
      className={
        replacement.state === 'available'
          ? 'production-candidates__notice'
          : 'production-candidates__notice production-candidates__notice--unavailable'
      }
      role="status"
      data-testid="production-replacement-notice"
    >
      <strong>
        Replacement{' '}
        {replacement.state === 'available'
          ? `is player ${String(replacement.replacement_player_id)} at ordinal ${String(
              replacement.replacement_ordinal,
            )}.`
          : `is unavailable: the selected pool does not reach required ordinal ${String(
              replacement.replacement_ordinal,
            )}.`}
      </strong>{' '}
      Projected pool {replacement.projected_count}; structural shortfall{' '}
      {replacement.structural_roster_shortfall}; replacement ordinal shortfall{' '}
      {replacement.replacement_ordinal_shortfall}. A structural replacement would still not prove
      free-agent membership.
    </p>
  )
}

function HealthContextNotice({ payload }: { payload: ProductionCandidatesResponse }) {
  const context = payload.health_context
  if (context.status === 'unavailable') {
    return (
      <p
        className="production-candidates__notice production-candidates__notice--unknown"
        role="status"
        data-testid="production-health-context"
      >
        <strong>Historical observations are unknown.</strong> No attributable publication defines
        a season and window, so candidate counts are null rather than zero. Every candidate remains
        in the production ranking, and this says nothing about health or fitness.
      </p>
    )
  }

  return (
    <p
      className="production-candidates__notice production-candidates__notice--observations"
      role="note"
      data-testid="production-health-context"
    >
      <strong>Separate historical facts:</strong> credited game-log rows in {context.season}{' '}
      {context.season_type}, {context.window_start} through {context.as_of_date}, including
      zero-second credited rows. A zero means no rows in this declared window, not healthy, no
      career history, a season availability rate, or a forecast. Row-level source provenance is{' '}
      <code>{context.row_source_provenance}</code>; publication metadata is not row-level source
      proof.
    </p>
  )
}

function CandidateHealthSummary({
  candidate,
  payload,
}: {
  candidate: ProductionCandidate
  payload: ProductionCandidatesResponse
}) {
  if (candidate.health.status === 'unknown') {
    return (
      <span className="production-candidates__health production-candidates__health--unknown">
        Unknown
      </span>
    )
  }
  if (candidate.health.status === 'no_observations') {
    return (
      <span className="production-candidates__health production-candidates__health--none">
        0 in declared window
      </span>
    )
  }
  return (
    <span className="production-candidates__health production-candidates__health--observed">
      {candidate.health.credited_appearances} credited{' '}
      {candidate.health.credited_appearances === 1 ? 'row' : 'rows'}
      {payload.health_context.status === 'available'
        ? ` · ${payload.health_context.season}`
        : ''}
    </span>
  )
}

function CandidateEvidence({
  candidate,
  payload,
  id,
}: {
  candidate: ProductionCandidate
  payload: ProductionCandidatesResponse
  id: string
}) {
  return (
    <section
      className="production-candidates__evidence"
      id={id}
      aria-label={`Evidence for ${candidate.full_name}`}
    >
      <div>
        <h3>Source rates per game</h3>
        <dl className="production-candidates__rates">
          {SIMPLE_RATE_FIELDS.map((field) => (
            <div key={field}>
              <dt>{RATE_LABELS[field]}</dt>
              <dd>{formatRate(candidate.rates_per_game[field])}</dd>
            </div>
          ))}
          <div>
            <dt>Field goals made / attempted per game</dt>
            <dd>
              {formatRate(candidate.rates_per_game.field_goals_made_per_game)} /{' '}
              {formatRate(candidate.rates_per_game.field_goals_attempted_per_game)}
            </dd>
          </div>
          <div>
            <dt>Free throws made / attempted per game</dt>
            <dd>
              {formatRate(candidate.rates_per_game.free_throws_made_per_game)} /{' '}
              {formatRate(candidate.rates_per_game.free_throws_attempted_per_game)}
            </dd>
          </div>
        </dl>
        <p className="production-candidates__evidence-note">
          Makes and attempts are shown as scoring inputs. No candidate raw-percentage comparison is
          computed here; FG and FT components use the scorer&apos;s published volume impact.
        </p>
      </div>

      <div>
        <h3>Nine directed components</h3>
        <div className="production-candidates__component-scroll">
          <table className="table production-candidates__component-table">
            <thead>
              <tr>
                <th scope="col">Category</th>
                <th scope="col">Kind</th>
                <th scope="col">Direction</th>
                <th scope="col">Published inputs</th>
                <th scope="col">Transformed value</th>
                <th scope="col">Directed z</th>
              </tr>
            </thead>
            <tbody>
              {candidate.components.map((component) => {
                const scale = payload.category_scales.find(
                  (candidateScale) =>
                    candidateScale.category_key === component.category_key,
                )
                return (
                  <tr key={component.category_key}>
                    <th scope="row">
                      {CATEGORY_LABELS[component.category_key]}{' '}
                      <code>{component.category_key}</code>
                    </th>
                    <td>{component.kind}</td>
                    <td>{component.direction === 1 ? '+1' : '−1'} from scorer</td>
                    <td>
                      {scale?.production_fields.map((field, index) => (
                        <span key={field} className="production-candidates__input">
                          {index > 0 ? ' · ' : ''}
                          <code>{field}</code>{' '}
                          {formatPublishedField(component.production_fields, field)}
                        </span>
                      ))}
                    </td>
                    <td>{formatScore(component.transformed_value)}</td>
                    <td>{formatScore(component.z_score)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h3>Historical observation fact</h3>
        <CandidateHealthDetail candidate={candidate} payload={payload} />
      </div>

      <div>
        <h3>Player/source identity</h3>
        <dl className="facts">
          <div className="facts__row">
            <dt>Player record</dt>
            <dd>{candidate.player_id}</dd>
          </div>
          <div className="facts__row">
            <dt>Projection row</dt>
            <dd>
              <code>{candidate.projection_content_sha256}</code>
            </dd>
          </div>
          <div className="facts__row">
            <dt>Response generated</dt>
            <dd>
              <time dateTime={payload.generated_at}>{payload.generated_at}</time>
            </dd>
          </div>
        </dl>
      </div>
    </section>
  )
}

function CandidateHealthDetail({
  candidate,
  payload,
}: {
  candidate: ProductionCandidate
  payload: ProductionCandidatesResponse
}) {
  const context = payload.health_context
  if (candidate.health.status === 'unknown' || context.status === 'unavailable') {
    return (
      <p>
        Unknown because no attributable publication defines the observation window. Count is null,
        this is not zero, and the ranking did not use health.
      </p>
    )
  }

  const publicationSource = context.publication.source ?? 'not recorded'
  const publicationVersion = context.publication.source_version ?? 'not recorded'
  return (
    <>
      <p>
        {candidate.health.credited_appearances} credited game-log{' '}
        {candidate.health.credited_appearances === 1 ? 'row' : 'rows'} in the declared{' '}
        {context.season} {context.season_type} window ({context.window_start} through{' '}
        {context.as_of_date}). Zero-second credited rows count.
      </p>
      <p>
        Publication <code>{context.publication.artifact_key}</code> · metadata source{' '}
        <code>{publicationSource}</code> · metadata version <code>{publicationVersion}</code>.
        Row-level source provenance remains <code>{context.row_source_provenance}</code>; the
        publication metadata does not prove where this player row originated.
      </p>
    </>
  )
}

function LineageAndLimitations({ payload }: { payload: ProductionCandidatesResponse }) {
  const { lineage } = payload
  return (
    <details className="production-candidates__lineage">
      <summary>Full lineage, category scales, and explicit limitations</summary>
      <div className="production-candidates__lineage-grid">
        <section>
          <h3>Source and blend</h3>
          <dl className="facts">
            <Fact label="Import content" value={lineage.projection_import.content_sha256} />
            <Fact
              label="Projection values"
              value={lineage.projection_import.projection_values_sha256}
            />
            <Fact
              label="Import profile definition"
              value={lineage.projection_import.profile_definition_sha256}
            />
            <Fact
              label="Blend identity"
              value={`${lineage.blend.mode}; persisted ${String(lineage.blend.persisted)}; profile ${lineage.blend.profile_id} v${String(lineage.blend.version)}`}
            />
            <Fact label="Blend profile content" value={lineage.blend.content_sha256} />
            <Fact label="Blend result" value={lineage.blend.result_content_sha256} />
          </dl>
        </section>
        <section>
          <h3>Scorer and reference</h3>
          <dl className="facts">
            <Fact label="Scoring profile" value={lineage.scoring_profile.content_sha256} />
            <Fact label="Score content" value={lineage.score.content_sha256} />
            <Fact
              label="Score contract"
              value={`${lineage.score.input_kind} → ${lineage.score.output_layer}`}
            />
            <Fact label="Aggregation policy" value={lineage.score.aggregation_policy} />
            <Fact label="Reference policy" value={lineage.score.reference_policy} />
            <Fact label="Replacement policy" value={lineage.score.replacement_policy} />
            <Fact label="Reference players" value={payload.reference.players_sha256} />
          </dl>
        </section>
      </div>

      <div className="production-candidates__component-scroll">
        <table className="table production-candidates__scale-table">
          <caption>
            Scale and identity weight arrays in the active scoring profile&apos;s published order.
          </caption>
          <thead>
            <tr>
              <th scope="col">Category</th>
              <th scope="col">Kind</th>
              <th scope="col">Direction</th>
              <th scope="col">Production fields</th>
              <th scope="col">Reference mean</th>
              <th scope="col">Population SD</th>
              <th scope="col">Reference percentage</th>
              <th scope="col">Status</th>
              <th scope="col">Source weight</th>
            </tr>
          </thead>
          <tbody>
            {payload.category_scales.map((scale, index) => {
              const weight = lineage.blend.category_weights[index]
              return (
                <tr key={scale.category_key}>
                  <th scope="row">
                    {CATEGORY_LABELS[scale.category_key]} <code>{scale.category_key}</code>
                  </th>
                  <td>{scale.kind}</td>
                  <td>{scale.direction === 1 ? '+1' : '−1'}</td>
                  <td>{scale.production_fields.join(' · ')}</td>
                  <td>{formatScore(scale.reference_mean)}</td>
                  <td>{formatScore(scale.population_sd)}</td>
                  <td>
                    {scale.reference_percentage === null
                      ? 'Not applicable'
                      : formatRate(scale.reference_percentage)}
                  </td>
                  <td>{scale.status}</td>
                  <td>
                    {weight === undefined
                      ? 'Contract mismatch'
                      : `${weight.source}: ${formatRate(weight.normalized_weight)}`}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <section>
        <h3>Explicitly outside this response</h3>
        <ul className="production-candidates__limitations" data-testid="production-limitations">
          <li>Strategy included: {yesNo(payload.limitations.strategy_included)}</li>
          <li>Punt adjustment included: {yesNo(payload.limitations.punt_adjustment_included)}</li>
          <li>
            Budget or affordability included:{' '}
            {yesNo(payload.limitations.budget_or_affordability_included)}
          </li>
          <li>Position fit included: {yesNo(payload.limitations.position_fit_included)}</li>
          <li>
            Fantrax roster eligibility included:{' '}
            {yesNo(payload.limitations.fantrax_roster_eligibility_included)}
          </li>
          <li>Partial browser increment: {yesNo(payload.limitations.partial_browser_increment)}</li>
          <li>
            Availability model: <code>none</code>; punt configuration: <code>none</code>
          </li>
          <li>
            Source freshness: <code>{payload.source_freshness}</code>
          </li>
        </ul>
      </section>
    </details>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="facts__row">
      <dt>{label}</dt>
      <dd>
        <code>{value}</code>
      </dd>
    </div>
  )
}

function componentHeadingTitle(scale: ProductionCategoryScale): string {
  const direction = scale.direction === 1 ? '+1' : '−1'
  return `${scale.category_key}; ${scale.kind}; direction ${direction}; ${scale.status}`
}

function formatScore(value: number): string {
  return (Object.is(value, -0) ? 0 : value).toFixed(3)
}

function formatRate(value: number): string {
  return value.toFixed(3)
}

function formatPublishedField(
  fields: Record<string, number>,
  field: string,
): string {
  const value = fields[field]
  return value === undefined ? 'Unavailable' : formatRate(value)
}

function yesNo(value: boolean): string {
  return value ? 'yes' : 'no'
}
