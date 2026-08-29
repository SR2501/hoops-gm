import type {
  SourceBoardColumn,
  SourceBoardRegression,
  SourceBoardResponse,
  SourceBoardSnapshot,
} from '../api/draftTypes'

export interface SourceBoardColumnModel {
  sourceSeat: number
  mutableLabel: string | null
  picks: SourceBoardColumn['picks']
}

export interface SourceBoardEvidenceModel {
  response: SourceBoardResponse
  board: SourceBoardSnapshot | null
  columns: SourceBoardColumnModel[]
  regressions: SourceBoardRegression[]
  boardAge: string | null
  contactAge: string | null
}

/** Human-readable duration without converting the server's age into a new clock. */
export function describeSourceAge(seconds: number | null): string | null {
  if (seconds === null) return null
  const wholeSeconds = Math.max(0, Math.floor(seconds))
  if (wholeSeconds < 1) return 'less than 1 second'
  if (wholeSeconds < 60) {
    return `${String(wholeSeconds)} ${wholeSeconds === 1 ? 'second' : 'seconds'}`
  }

  const wholeMinutes = Math.floor(wholeSeconds / 60)
  const remainingSeconds = wholeSeconds % 60
  if (wholeMinutes < 60) {
    return remainingSeconds === 0
      ? `${String(wholeMinutes)} ${wholeMinutes === 1 ? 'minute' : 'minutes'}`
      : `${String(wholeMinutes)}m ${String(remainingSeconds)}s`
  }

  const wholeHours = Math.floor(wholeMinutes / 60)
  const remainingMinutes = wholeMinutes % 60
  return remainingMinutes === 0
    ? `${String(wholeHours)} ${wholeHours === 1 ? 'hour' : 'hours'}`
    : `${String(wholeHours)}h ${String(remainingMinutes)}m`
}

export function buildSourceBoardEvidenceModel(
  response: SourceBoardResponse,
): SourceBoardEvidenceModel {
  const board = response.board
  const columns =
    board?.columns
      .slice()
      .sort((left, right) => left.source_seat - right.source_seat)
      .map((column) => ({
        sourceSeat: column.source_seat,
        mutableLabel: column.mutable_label,
        picks: column.picks
          .slice()
          .sort(
            (left, right) =>
              left.round_number - right.round_number ||
              left.pick_in_round - right.pick_in_round,
          ),
      })) ?? []

  return {
    response,
    board,
    columns,
    regressions: response.regressions.slice().sort(
      (left, right) =>
        left.source_seat - right.source_seat ||
        left.round_number - right.round_number ||
        left.pick_in_round - right.pick_in_round,
    ),
    boardAge: describeSourceAge(response.board_age_seconds),
    contactAge: describeSourceAge(response.contact_age_seconds),
  }
}
