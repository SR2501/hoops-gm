import { describe, expect, it } from 'vitest'
import { ApiError } from './client'
import { describeReliabilityError } from './reliabilityErrors'

describe('reliability error copy', () => {
  it('distinguishes an unpublished store from an absent endpoint', () => {
    const description = describeReliabilityError(
      new ApiError(409, 'reliability_not_published', 'no current cohort', 'req-1'),
    )

    expect(description.summary).toContain('has not been published for this store')
    expect(description.action).toContain('publish_reliability_evidence')
  })

  it('labels a superseded cohort stale and requires publication before use', () => {
    const description = describeReliabilityError(
      new ApiError(409, 'reliability_not_current', 'source fingerprint moved', 'req-2'),
    )

    expect(description.summary).toContain('must be treated as stale')
    expect(description.action).toContain('Publish reliability evidence again')
  })

  it('does not claim republishing repairs incoherent source inputs', () => {
    const description = describeReliabilityError(
      new ApiError(409, 'reliability_inputs_refused', 'conflicting evidence', 'req-3'),
    )

    expect(description.summary).toContain('cannot form a coherent reliability cohort')
    expect(description.action).toContain('publishing again alone will not fix it')
  })
})
