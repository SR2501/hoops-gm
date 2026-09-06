import { describe, expect, it } from 'vitest'
import { isScheduleGrid } from '../api/endpoints'
import type { ScheduleGrid } from '../api/types'
import contract from './fixtures/schedule-grid.contract.json'

type BackendScheduleGridContract = {
  league_id: number
  season: string
  lineage: {
    schedule: {
      refresh_id: number
      version: string
      refreshed_at: string
      source_game_count: number
      resolved_game_count: number
      persisted_team_row_count: number
      unresolved_game_ids: string[]
      pending_game_ids: string[]
      pending_games: {
        nba_game_id: string
        game_date: string | null
        game_label: string
        game_sub_label: string
        game_subtype: string
        date_absence_reason: string
      }[]
    }
    scoring_period_projection: {
      refresh_id: number
      version: string
      refreshed_at: string
    }
    deadline_calendar: { id: number; version: number }
    settings_snapshot: { id: number; version: number }
  }
  teams: { team_id: number; nba_team_id: number; abbreviation: string; name: string }[]
  periods: { period_number: number; start_date: string; end_date: string; is_playoff: boolean }[]
  counts: { period_number: number; team_id: number; games: number }[]
}

type Equal<Left, Right> =
  (<Value>() => Value extends Left ? 1 : 2) extends <Value>() => Value extends Right ? 1 : 2
    ? (<Value>() => Value extends Right ? 1 : 2) extends <Value>() => Value extends Left ? 1 : 2
      ? true
      : false
    : false

// This assignment makes the committed backend specimen pass through the
// compile-time contract as well as the runtime validator used by apiFetch.
const typedContract: BackendScheduleGridContract = contract
const frontendTypeMatchesBackend: Equal<ScheduleGrid, BackendScheduleGridContract> = true

describe('the backend-owned schedule-grid contract specimen', () => {
  it('matches the frontend wire contract', () => {
    expect(frontendTypeMatchesBackend).toBe(true)
    expect(isScheduleGrid(typedContract)).toBe(true)
  })

  it('rejects unreviewed fields instead of accepting a silently widened response', () => {
    expect(isScheduleGrid({ ...typedContract, unreviewed_field: true })).toBe(false)
  })
})
