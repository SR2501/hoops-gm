import { describe, expect, it } from 'vitest'
import { ApiError } from './client'
import {
  describeDraftCreationError,
  isDraftCreationOutcomeUncertain,
} from './draftErrors'

function apiError(code: string): ApiError {
  return new ApiError(0, code, `failure: ${code}`, null)
}

describe('draft creation uncertainty', () => {
  it.each(['timeout', 'unreachable', 'invalid_response'])(
    'treats %s as potentially committed',
    (code) => {
      const error = apiError(code)

      expect(isDraftCreationOutcomeUncertain(error)).toBe(true)
      expect(describeDraftCreationError(error).action).toContain('could create a duplicate')
    },
  )

  it.each(['draft_name_required', 'server_error'])(
    'does not lock creation after a definitive %s response',
    (code) => {
      expect(isDraftCreationOutcomeUncertain(apiError(code))).toBe(false)
    },
  )
})
