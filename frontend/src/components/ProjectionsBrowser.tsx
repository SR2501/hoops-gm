import { useMemo, useState } from 'react'
import { ProjectionsTable } from './ProjectionsTable'
import {
  projectionTeamOptions,
  selectProjectionRows,
  type ProjectionSort,
  type ProjectionSortKey,
  type ProjectionTeamFilter,
  type ProjectionsModel,
} from './projectionsModel'

const ALL_TEAMS = ''
const MISSING_TEAM = '__missing_team_label__'
export const PROJECTION_PAGE_SIZE = 100

function teamFilter(selection: string): ProjectionTeamFilter {
  if (selection === ALL_TEAMS) return { kind: 'all' }
  if (selection === MISSING_TEAM) return { kind: 'missing' }
  return { kind: 'team', abbreviation: selection }
}

export function ProjectionsBrowser({ model }: { model: ProjectionsModel }) {
  const [searchQuery, setSearchQuery] = useState('')
  const [teamSelection, setTeamSelection] = useState(ALL_TEAMS)
  const [sort, setSort] = useState<ProjectionSort | null>(null)
  const [visibleLimit, setVisibleLimit] = useState(PROJECTION_PAGE_SIZE)

  const teams = useMemo(() => projectionTeamOptions(model.rows), [model.rows])
  const effectiveTeamSelection =
    teamSelection === ALL_TEAMS ||
    (teamSelection === MISSING_TEAM
      ? teams.hasMissingLabel
      : teams.abbreviations.includes(teamSelection))
      ? teamSelection
      : ALL_TEAMS
  const rows = useMemo(
    () =>
      selectProjectionRows(model.rows, {
        searchQuery,
        teamFilter: teamFilter(effectiveTeamSelection),
        sort,
      }),
    [effectiveTeamSelection, model.rows, searchQuery, sort],
  )
  const visibleRows = rows.slice(0, visibleLimit)

  const controlsActive =
    searchQuery !== '' ||
    effectiveTeamSelection !== ALL_TEAMS ||
    sort !== null ||
    visibleLimit > PROJECTION_PAGE_SIZE

  function changeSort(key: ProjectionSortKey) {
    setVisibleLimit(PROJECTION_PAGE_SIZE)
    setSort((current) => ({
      key,
      direction:
        current?.key === key && current.direction === 'ascending' ? 'descending' : 'ascending',
    }))
  }

  function reset() {
    setSearchQuery('')
    setTeamSelection(ALL_TEAMS)
    setSort(null)
    setVisibleLimit(PROJECTION_PAGE_SIZE)
  }

  return (
    <section className="projections__browser" aria-label="Projection table browser">
      <div className="projections__controls">
        <label>
          <span>Search players</span>
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => {
              setSearchQuery(event.target.value)
              setVisibleLimit(PROJECTION_PAGE_SIZE)
            }}
            placeholder="Player name"
            aria-controls="projections-table"
          />
        </label>

        <label>
          <span>NBA team</span>
          <select
            value={effectiveTeamSelection}
            onChange={(event) => {
              setTeamSelection(event.target.value)
              setVisibleLimit(PROJECTION_PAGE_SIZE)
            }}
            aria-controls="projections-table"
          >
            <option value={ALL_TEAMS}>All NBA teams</option>
            {teams.abbreviations.map((abbreviation) => (
              <option key={abbreviation} value={abbreviation}>
                {abbreviation}
              </option>
            ))}
            {teams.hasMissingLabel ? (
              <option value={MISSING_TEAM}>No NBA team label</option>
            ) : null}
          </select>
        </label>

        <button type="button" onClick={reset} disabled={!controlsActive}>
          Reset view
        </button>

        <p className="projections__result-count" role="status" aria-live="polite">
          Showing {visibleRows.length} of {rows.length} matches from {model.rows.length} imported
          players
        </p>

        {visibleRows.length < rows.length ? (
          <button
            type="button"
            onClick={() => setVisibleLimit((current) => current + PROJECTION_PAGE_SIZE)}
          >
            Show more players
          </button>
        ) : null}
      </div>

      <ProjectionsTable model={model} rows={visibleRows} sort={sort} onSort={changeSort} />
    </section>
  )
}
