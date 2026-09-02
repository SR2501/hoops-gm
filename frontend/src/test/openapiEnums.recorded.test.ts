/**
 * Every closed vocabulary this frontend declares, against the OpenAPI document
 * the backend actually serves.
 *
 * ## Why this file exists
 *
 * `DraftToolUsage` declared `'blind' | 'assisted' | 'tool_led'`. The served
 * enum is `blind, partial, instrumented`. **Two of three values were wrong
 * while 362 tests were green**, and no amount of care in review would reliably
 * have caught it, because:
 *
 * - every committed fixture carries `blind`, the one value both spellings
 *   share, so no recording contradicted it;
 * - `DraftPage` renders the field verbatim, so even a `partial` draft would
 *   have *displayed* correctly;
 * - a union too narrow on the **receiving** side is invisible until a value
 *   outside it arrives, and TypeScript checks assignability against the
 *   declaration, never against the producer.
 *
 * It surfaced only from a `422` on a write, which is not a path the dashboard
 * takes. Fixing that instance would have left the generator in place — *nothing
 * compared any declared union to the enum it mirrors* — so this file is the
 * generator's fix. It found a **second** live drift immediately: `DraftType`
 * omitted `unknown`, which matters more, because `draftBoardModel.ts` decides
 * whether a board is an auction from that field.
 *
 * ## The part that stops this becoming the same defect one level up
 *
 * A test listing the enums somebody remembered is exactly the failure it is
 * written to prevent. So the document's enums are partitioned: every schema
 * enum must be **either** compared below **or** named in `NOT_MODELLED` with a
 * reason. A new backend enum belongs to neither and fails
 * `partitions every enum in the document`. That assertion is the load-bearing
 * one; the per-enum comparisons are what it makes exhaustive.
 *
 * ## What this cannot check
 *
 * The recording is a snapshot. It is captured from a local backend at a known
 * commit and re-capturing it is a manual act, so this catches a **frontend**
 * union drifting from the document, and catches a **backend** enum change only
 * once somebody re-records. That is a real limit rather than a formality: the
 * `tool_usage` drift would have been caught the moment the fixture was
 * refreshed, and not before. Narrowing it means generating the document in CI
 * from the backend package, which is a cross-owner change rather than a test.
 */

import { describe, expect, it } from 'vitest'
import {
  DRAFT_EVENT_TYPES,
  DRAFT_SOURCE_BOARD_PROFILES,
  DRAFT_STATUSES,
  DRAFT_TOOL_USAGES,
  DRAFT_TYPES,
} from '../api/draftTypes'
import openapi from './fixtures/openapi.recorded.json'

/** Ten seconds. Pure JSON comparison, no DOM, no network, no timers. */
const TIMEOUT_MS = 10_000

interface OpenApiDocument {
  openapi: string
  components: {
    schemas: Record<
      string,
      {
        enum?: unknown[]
        properties?: Record<string, unknown>
        required?: string[]
        additionalProperties?: boolean
      }
    >
  }
}

const document = openapi as unknown as OpenApiDocument

/** Schema name → the frontend array that mirrors it. */
const MIRRORED: Record<string, readonly string[]> = {
  DraftType: DRAFT_TYPES,
  DraftStatus: DRAFT_STATUSES,
  DraftToolUsage: DRAFT_TOOL_USAGES,
  DraftEventType: DRAFT_EVENT_TYPES,
  DraftSourceBoardProfile: DRAFT_SOURCE_BOARD_PROFILES,
}

/**
 * Enums the frontend deliberately does not model, each with the reason.
 *
 * A reason rather than a bare list, because "we chose not to" and "nobody has
 * looked at this yet" are different states and only one of them is safe to
 * leave alone.
 */
const NOT_MODELLED: Record<string, string> = {
  ExternalSource:
    'Carried as a bare `string` on `CurrentProjections.source` and displayed, never branched on. A narrow union here would refuse a payload the backend considers valid the moment a source is registered, and the failure would read as a contract error rather than as this build being out of date.',
  ScoringType:
    'Carried as `assumed_scoring_type: string | null` and compared with `includes("categories")` rather than by equality, deliberately: the check that matters is "is this a category format", and it must stay true for a value this build has never seen. See `leagueCategoryModel.ts`.',
  RefreshArtifactType:
    'Belongs to the lineage endpoints, which no screen consumes yet. Unmodelled because unused, not because it was considered and rejected.',
}

function schemaEnum(name: string): string[] {
  const schema = document.components.schemas[name]
  if (schema?.enum === undefined) {
    throw new Error(`${name} is not an enum in the recorded document`)
  }
  return schema.enum.map(String)
}

function everyEnumInDocument(): string[] {
  return Object.entries(document.components.schemas)
    .filter(([, schema]) => Array.isArray(schema.enum))
    .map(([name]) => name)
    .sort()
}

describe('the recorded OpenAPI document', () => {
  it(
    'is the document this backend serves, not an empty object that would pass everything',
    () => {
      // The precondition for every assertion below. A fixture that failed to
      // capture would make each comparison vacuously pass against an absent
      // enum, so the shape is checked before it is used.
      expect(document.openapi).toMatch(/^3\./)
      expect(Object.keys(document.components.schemas).length).toBeGreaterThan(50)
      expect(everyEnumInDocument().length).toBeGreaterThan(0)
    },
    TIMEOUT_MS,
  )

  it(
    'partitions every enum in the document into mirrored or deliberately unmodelled',
    () => {
      // The assertion that makes the rest exhaustive. A new backend enum is in
      // neither set and fails here, which is the only thing standing between
      // this file and the "list the ones somebody remembered" defect it exists
      // to prevent.
      const accounted = [...Object.keys(MIRRORED), ...Object.keys(NOT_MODELLED)].sort()
      expect(everyEnumInDocument()).toEqual(accounted)
    },
    TIMEOUT_MS,
  )

  it(
    'has a stated reason for every enum the frontend does not model',
    () => {
      for (const [name, reason] of Object.entries(NOT_MODELLED)) {
        expect(reason.length, `${name} has no reason`).toBeGreaterThan(40)
      }
    },
    TIMEOUT_MS,
  )

  it(
    'publishes the additive draft and feed fields with closed skip-detail objects',
    () => {
      const schemas = document.components.schemas
      expect(schemas.DraftStateResponse?.required).toContain('source_board_profile')
      expect(schemas.DraftSummary?.required).toContain('source_board_profile')
      expect(schemas.ParticipantOut?.required).toContain('source_seat')

      expect(Object.keys(schemas.ParticipantSkippedOut?.properties ?? {}).sort()).toEqual([
        'participant_id',
        'reasons',
        'team_slot',
        'total',
      ])
      expect(schemas.ParticipantSkippedOut?.additionalProperties).toBe(false)

      expect(Object.keys(schemas.FeedStatusResponse?.properties ?? {}).sort()).toEqual([
        'applied_count',
        'as_of',
        'blocked',
        'board_regressions',
        'context_unavailable',
        'draft_id',
        'freshness',
        'last_sequence',
        'observation_count',
        'pending_count',
        'reconciliation',
        'retryable',
        'skipped',
        'skipped_by_participant',
        'unattributed_skipped',
      ])
      expect(schemas.FeedStatusResponse?.additionalProperties).toBe(false)
    },
    TIMEOUT_MS,
  )
})

describe('every mirrored union', () => {
  for (const [name, declared] of Object.entries(MIRRORED)) {
    it(
      `${name} declares exactly the values the backend publishes`,
      () => {
        // Set equality in both directions, not a length check and not a subset.
        // A union that is too *wide* accepts a value the backend will never
        // send and lets dead branches accumulate; one that is too *narrow* is
        // the `tool_usage` defect, and is invisible on the read path. Both are
        // failures and only one of them is the one anybody worries about.
        expect([...declared].sort()).toEqual(schemaEnum(name).sort())
      },
      TIMEOUT_MS,
    )
  }

  it(
    'declares no duplicate value, which set comparison alone would not notice',
    () => {
      for (const [name, declared] of Object.entries(MIRRORED)) {
        expect(new Set(declared).size, `${name} repeats a value`).toBe(declared.length)
      }
    },
    TIMEOUT_MS,
  )

  it(
    'still names the two values this sweep actually corrected',
    () => {
      // Named individually and on purpose. The comparisons above are generic
      // and would go green again if someone "fixed" a future mismatch by
      // editing the fixture instead of the union; these two are the worked
      // examples the file's docstring rests on, and a reader meeting a failure
      // here is being told the recording moved rather than the code.
      expect(DRAFT_TOOL_USAGES).toContain('partial')
      expect(DRAFT_TOOL_USAGES).not.toContain('assisted')
      expect(DRAFT_TOOL_USAGES).not.toContain('tool_led')
      expect(DRAFT_TYPES).toContain('unknown')
    },
    TIMEOUT_MS,
  )
})
