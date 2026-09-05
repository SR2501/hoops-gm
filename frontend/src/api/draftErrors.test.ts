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

  it('treats an empty server error from the development proxy as potentially committed', () => {
    const error = new ApiError(500, 'http_error', 'Internal Server Error', null, null)

    expect(isDraftCreationOutcomeUncertain(error)).toBe(true)
    expect(describeDraftCreationError(error).action).toContain('could create a duplicate')
  })

  it('keeps a structured generic HTTP failure distinct from an empty proxy failure', () => {
    const error = new ApiError(500, 'http_error', 'Internal Server Error', null, {
      proxy: 'identified',
    })

    expect(isDraftCreationOutcomeUncertain(error)).toBe(false)
  })
})
