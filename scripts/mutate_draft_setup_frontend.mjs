/**
 * Mutation proof for the draft-setup response and uncertain-write guards.
 *
 * Each mutation removes one boundary or invariant while the corresponding test
 * constructs the malformed response that boundary exists to reject. A mutation
 * counts only when the focused test is green before mutation, the source bytes
 * actually change, Vitest reports a failed test (not a collection/build error),
 * the original bytes are restored, and the focused test is green again.
 *
 * Do not run this concurrently with another frontend test process: the harness
 * edits frontend source in place and restores its exact bytes after every run.
 */

import { Buffer } from 'node:buffer'
import { spawnSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO = dirname(dirname(fileURLToPath(import.meta.url)))
const FRONTEND = join(REPO, 'frontend')
const SOURCES = {
  setup: join(FRONTEND, 'src', 'api', 'draftEndpoints.ts'),
  errors: join(FRONTEND, 'src', 'api', 'draftErrors.ts'),
  form: join(FRONTEND, 'src', 'components', 'DraftSetupForm.tsx'),
}
const DEFAULT_TESTS = ['src/api/draftEndpoints.test.ts']

const mutations = [
  {
    name: 'positive integer accepts zero',
    old: "return typeof value === 'number' && Number.isInteger(value) && value > 0",
    replacement: "return typeof value === 'number' && Number.isInteger(value) && value >= 0",
  },
  {
    name: 'positive integer accepts fractions',
    old: "return typeof value === 'number' && Number.isInteger(value) && value > 0",
    replacement: "return typeof value === 'number' && true && value > 0",
  },
  {
    name: 'auction budget accepts non-decimal text',
    old: '/^(?:0|[1-9]\\d*)(?:\\.\\d+)?$/.test(value)',
    replacement: 'value.length > 0',
  },
  {
    name: 'auction budget accepts zero',
    old: '/[1-9]/.test(value)',
    replacement: 'true',
  },
  {
    name: 'team non-record guard removed',
    old: '    isRecord(value) &&\n    hasExactKeys(value, DRAFT_SETUP_TEAM_KEYS) &&',
    replacement: '    true &&\n    hasExactKeys(value, DRAFT_SETUP_TEAM_KEYS) &&',
  },
  {
    name: 'team exact-field guard removed',
    old: '    hasExactKeys(value, DRAFT_SETUP_TEAM_KEYS) &&',
    replacement: '    true &&',
  },
  {
    name: 'team id positivity guard removed',
    old: '    isPositiveInteger(value.fantasy_team_id) &&',
    replacement: "    typeof value.fantasy_team_id === 'number' &&",
  },
  {
    name: 'team name type guard removed',
    old:
      '    isPositiveInteger(value.fantasy_team_id) &&\n' +
      "    typeof value.display_name === 'string' &&",
    replacement: '    isPositiveInteger(value.fantasy_team_id) &&\n    true &&',
  },
  {
    name: 'team blank-name guard removed',
    old: '    value.display_name.trim().length > 0',
    replacement: '    value.display_name.length > 0',
  },
  {
    name: 'format non-record guard removed',
    old: '    !isRecord(value) ||\n    !hasExactKeys(value, DRAFT_SETUP_FORMAT_KEYS) ||',
    replacement: '    false ||\n    !hasExactKeys(value, DRAFT_SETUP_FORMAT_KEYS) ||',
  },
  {
    name: 'format exact-field guard removed',
    old: '    !hasExactKeys(value, DRAFT_SETUP_FORMAT_KEYS) ||',
    replacement: '    false ||',
  },
  {
    name: 'format draft-type guard removed',
    old:
      "    !['auction', 'snake', 'linear'].some((draftType) => draftType === value.draft_type) ||",
    replacement: '    false ||',
  },
  {
    name: 'format team-count positivity guard removed',
    old: '    !isPositiveInteger(value.team_count) ||',
    replacement: "    typeof value.team_count !== 'number' ||",
  },
  {
    name: 'format roster-size positivity guard removed',
    old: '    !isPositiveInteger(value.roster_size) ||',
    replacement: "    typeof value.roster_size !== 'number' ||",
  },
  {
    name: 'format total-slots invariant removed',
    old: '    value.total_roster_slots !== value.team_count * value.roster_size',
    replacement: '    false',
  },
  {
    name: 'auction budget validation reduced to string type',
    old: '    ? isPositiveDecimalString(value.auction_budget)',
    replacement: "    ? typeof value.auction_budget === 'string'",
  },
  {
    name: 'ordered-format null-budget guard removed',
    old: '    : value.auction_budget === null',
    replacement: '    : true',
  },
  {
    name: 'league non-record guard removed',
    old: '    !isRecord(value) ||\n    !hasExactKeys(value, DRAFT_SETUP_LEAGUE_KEYS) ||',
    replacement: '    false ||\n    !hasExactKeys(value, DRAFT_SETUP_LEAGUE_KEYS) ||',
  },
  {
    name: 'league exact-field guard removed',
    old: '    !hasExactKeys(value, DRAFT_SETUP_LEAGUE_KEYS) ||',
    replacement: '    false ||',
  },
  {
    name: 'league id positivity guard removed',
    old: '    !isPositiveInteger(value.league_id) ||',
    replacement: "    typeof value.league_id !== 'number' ||",
  },
  {
    name: 'league name type guard removed',
    old: "    typeof value.name !== 'string' ||",
    replacement: '    false ||',
  },
  {
    name: 'league blank-name guard removed',
    old: '    value.name.trim().length === 0 ||',
    replacement: '    value.name.length === 0 ||',
  },
  {
    name: 'season type guard removed',
    old: "    typeof value.season !== 'string' ||",
    replacement: '    false ||',
  },
  {
    name: 'blank-season guard removed',
    old: '    value.season.trim().length === 0 ||',
    replacement: '    value.season.length === 0 ||',
  },
  {
    name: 'nested format guard removed',
    old: '    !isDraftSetupFormat(value.format) ||',
    replacement: '    false ||',
  },
  {
    name: 'fantasy-team array guard removed',
    old: '    !Array.isArray(value.fantasy_teams) ||',
    replacement: '    false ||',
  },
  {
    name: 'fantasy-team item guard removed',
    old: '    !value.fantasy_teams.every(isDraftSetupTeam) ||',
    replacement: '    false ||',
  },
  {
    name: 'team-count equality guard removed',
    old: '    value.fantasy_teams.length !== value.format.team_count',
    replacement: '    false',
  },
  {
    name: 'duplicate team guard removed',
    old: '  if (new Set(teamIds).size !== teamIds.length) return false',
    replacement: '  if (false) return false',
  },
  {
    name: 'owner membership guard removed',
    old:
      '  return (\n    value.owner_fantasy_team_id === null ||\n' +
      '    teamIds.some((teamId) => teamId === value.owner_fantasy_team_id)\n  )',
    replacement: '  return true',
  },
  {
    name: 'response non-record guard removed',
    old: "    !isRecord(value) ||\n    !hasExactKeys(value, ['leagues']) ||",
    replacement: "    false ||\n    !hasExactKeys(value, ['leagues']) ||",
  },
  {
    name: 'response exact-field guard removed',
    old: "    !hasExactKeys(value, ['leagues']) ||",
    replacement: '    false ||',
  },
  {
    name: 'league array guard removed',
    old: '    !Array.isArray(value.leagues) ||',
    replacement: '    false ||',
  },
  {
    name: 'league item guard removed',
    old: '    !value.leagues.every(isDraftSetupLeague)',
    replacement: '    false',
  },
  {
    name: 'duplicate league guard removed',
    old: '  return new Set(leagueIds).size === leagueIds.length',
    replacement: '  return true',
  },
  {
    name: 'timeout removed from uncertain creation outcomes',
    source: 'errors',
    tests: ['src/api/draftErrors.test.ts'],
    old: "const UNCERTAIN_CREATION_CODES = new Set(['timeout', 'unreachable', 'invalid_response'])",
    replacement:
      "const UNCERTAIN_CREATION_CODES = new Set(['unreachable', 'invalid_response'])",
  },
  {
    name: 'unreachable removed from uncertain creation outcomes',
    source: 'errors',
    tests: ['src/api/draftErrors.test.ts'],
    old: "const UNCERTAIN_CREATION_CODES = new Set(['timeout', 'unreachable', 'invalid_response'])",
    replacement: "const UNCERTAIN_CREATION_CODES = new Set(['timeout', 'invalid_response'])",
  },
  {
    name: 'invalid response removed from uncertain creation outcomes',
    source: 'errors',
    tests: ['src/api/draftErrors.test.ts'],
    old: "const UNCERTAIN_CREATION_CODES = new Set(['timeout', 'unreachable', 'invalid_response'])",
    replacement: "const UNCERTAIN_CREATION_CODES = new Set(['timeout', 'unreachable'])",
  },
  {
    name: 'uncertain creation branch removed',
    source: 'form',
    tests: ['src/routes/DraftsPage.test.tsx'],
    old: '      if (isDraftCreationOutcomeUncertain(failure)) {',
    replacement: '      if (false) {',
  },
  {
    name: 'uncertain creation lock removed',
    source: 'form',
    tests: ['src/routes/DraftsPage.test.tsx'],
    old: '        disabled={pending || creationLocked}',
    replacement: '        disabled={pending}',
  },
  {
    name: 'recorded draft refresh removed after uncertain creation',
    source: 'form',
    tests: ['src/routes/DraftsPage.test.tsx'],
    old: '        onCreationUncertain()',
    replacement: '        void onCreationUncertain',
  },
]

function runFocusedTest(testFiles) {
  const testCommand = ['npm', 'test', '--', '--run', ...testFiles]
  const command = process.platform === 'win32' ? process.env.ComSpec : testCommand[0]
  const args =
    process.platform === 'win32'
      ? ['/d', '/s', '/c', testCommand.join(' ')]
      : testCommand.slice(1)
  const result = spawnSync(command, args, {
    cwd: FRONTEND,
    encoding: 'utf8',
    maxBuffer: 10 * 1024 * 1024,
  })
  return {
    status: result.status,
    output: `${result.stdout ?? ''}${result.stderr ?? ''}${result.error?.message ?? ''}`,
  }
}

function countOccurrences(text, target) {
  let count = 0
  let offset = 0
  while ((offset = text.indexOf(target, offset)) !== -1) {
    count += 1
    offset += target.length
  }
  return count
}

function withoutAnsi(output) {
  return output.replace(/\u001b\[[0-9;?]*[A-Za-z]/g, '')
}

function passedTestCount(output) {
  return withoutAnsi(output).match(/Tests\s+(\d+) passed/)?.[1] ?? null
}

function failedTestCount(output) {
  return withoutAnsi(output).match(/Tests\s+(\d+) failed/)?.[1] ?? null
}

const sourceNames = new Set(mutations.map((mutation) => mutation.source ?? 'setup'))
const originals = new Map(
  [...sourceNames].map((sourceName) => {
    const path = SOURCES[sourceName]
    const bytes = readFileSync(path)
    const text = bytes.toString('utf8')
    return [sourceName, { path, bytes, text, newline: text.includes('\r\n') ? '\r\n' : '\n' }]
  }),
)
const suites = new Map()
for (const mutation of mutations) {
  const tests = mutation.tests ?? DEFAULT_TESTS
  suites.set(tests.join('\0'), tests)
}

console.log('=== baselines ===')
let baselinesGreen = true
for (const tests of suites.values()) {
  const baseline = runFocusedTest(tests)
  const baselinePassed = passedTestCount(baseline.output)
  if (baseline.status !== 0 || baselinePassed === null) {
    console.error(
      `BASELINE NOT GREEN for ${tests.join(', ')} (exit ${String(baseline.status)}); refusing to mutate`,
    )
    console.error(baseline.output.slice(-3000))
    baselinesGreen = false
  } else {
    console.log(`${tests.join(', ')}: ${baselinePassed} passed`)
  }
}

if (!baselinesGreen) {
  process.exitCode = 1
} else {

  let caught = 0
  let survived = 0
  let harnessFailures = 0

  for (const mutation of mutations) {
    const sourceName = mutation.source ?? 'setup'
    const source = originals.get(sourceName)
    const old = mutation.old.replaceAll('\n', source.newline)
    const replacement = mutation.replacement.replaceAll('\n', source.newline)
    const occurrences = countOccurrences(source.text, old)
    if (occurrences !== 1) {
      console.log(`[${mutation.name}] HARNESS_FAILURE(anchor count ${occurrences}, expected 1)`)
      harnessFailures += 1
      continue
    }

    const mutated = source.text.replace(old, replacement)
    const mutatedBytes = Buffer.from(mutated, 'utf8')
    if (mutatedBytes.equals(source.bytes)) {
      console.log(`[${mutation.name}] HARNESS_FAILURE(source bytes did not change)`)
      harnessFailures += 1
      continue
    }

    writeFileSync(source.path, mutatedBytes)
    try {
      const result = runFocusedTest(mutation.tests ?? DEFAULT_TESTS)
      const failed = failedTestCount(result.output)
      if (result.status === 1 && failed !== null) {
        console.log(`[${mutation.name}] CAUGHT(${failed} failed)`)
        caught += 1
      } else if (result.status === 0) {
        console.log(`[${mutation.name}] SURVIVED`)
        survived += 1
      } else {
        console.log(
          `[${mutation.name}] HARNESS_FAILURE(exit ${String(result.status)}, no failed-test count)`,
        )
        console.log(result.output.slice(-1200))
        harnessFailures += 1
      }
    } finally {
      writeFileSync(source.path, source.bytes)
    }
  }

  for (const [sourceName, source] of originals) {
    if (!readFileSync(source.path).equals(source.bytes)) {
      console.error(`HARNESS_FAILURE(${sourceName} was not restored byte-for-byte)`)
      harnessFailures += 1
    }
  }

  for (const tests of suites.values()) {
    const restored = runFocusedTest(tests)
    const restoredPassed = passedTestCount(restored.output)
    if (restored.status !== 0 || restoredPassed === null) {
      console.error(
        `HARNESS_FAILURE(restored ${tests.join(', ')} exit ${String(restored.status)})`,
      )
      console.error(restored.output.slice(-3000))
      harnessFailures += 1
    } else {
      console.log(`restored ${tests.join(', ')}: ${restoredPassed} passed`)
    }
  }

  console.log(
    `\n=== ${String(mutations.length)} mutations: ${String(caught)} caught, ` +
      `${String(survived)} survived, ${String(harnessFailures)} harness failures ===`,
  )
  process.exitCode = survived === 0 && harnessFailures === 0 ? 0 : 1
}
