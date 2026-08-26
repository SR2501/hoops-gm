/**
 * Reliability screen probe.
 *
 * Carries three things in one payload, deliberately:
 *
 *   1. An **invariant** — the eight inventory rows and their statuses, which
 *      must read the same whatever the API says, because the inventory is
 *      static content. If this moves, the screen changed.
 *   2. A **mover** — the sixty bar values, their range, the schedule counts and
 *      the undated-game count, all of which come from the live API and must
 *      change if the season behind the demo changes. A probe returning only the
 *      invariant cannot distinguish "nothing changed" from "I am blind".
 *   3. The **ground truth for the mover**, fetched from the same origin in the
 *      same reading, so the screen's numbers are asserted against the ids the
 *      API actually served rather than against numbers copied into a brief.
 *      A stale fixture does not announce itself.
 */
;(async () => {
  const text = (node) => (node ? node.textContent.replace(/\s+/g, ' ').trim() : null)
  const byId = (id) => document.querySelector(`[data-testid="${id}"]`)

  // Wait for both async boundaries to have resolved, not just for load.
  const deadline = Date.now() + 20000
  while (Date.now() < deadline) {
    if (byId('assumption-strip') && byId('schedule-evidence')) break
    await new Promise((r) => setTimeout(r, 100))
  }

  // Row ids are `evidence-<id>`; status and season ids share that prefix, so
  // they are excluded explicitly. The first version of this used a
  // `[data-testid$=""]` suffix match, which matches nothing and reported
  // `inventoryRowCount: 0` beside eight correctly-read statuses — a blind field
  // sitting in a payload that otherwise looked right.
  const inventoryRows = [...document.querySelectorAll('[data-testid^="evidence-"]')].filter(
    (n) => n.tagName === 'TR',
  )
  const statusNodes = [...document.querySelectorAll('[data-testid^="evidence-status-"]')]
  const seasonNodes = [...document.querySelectorAll('[data-testid^="evidence-season-"]')]

  const bars = [...document.querySelectorAll('[data-testid^="assumption-bar-"]')]
  const games = bars.map((b) => Number(b.getAttribute('data-games')))
  const heights = bars.map((b) => Number.parseFloat(b.style.height))

  const [projections, schedule] = await Promise.all([
    fetch('/api/v1/leagues/1/projections/current').then((r) => r.json()),
    fetch('/api/v1/leagues/1/schedule-grid/current').then((r) => r.json()),
  ])
  const apiGames = projections.source_games_played_assumptions
    .map((a) => a.assumed_games_played)
    .filter((g) => g !== null)
  const line = schedule.lineage.schedule

  const screenMin = games.length ? Math.min(...games) : null
  const screenMax = games.length ? Math.max(...games) : null
  const apiMin = apiGames.length ? Math.min(...apiGames) : null
  const apiMax = apiGames.length ? Math.max(...apiGames) : null

  const body = document.body.textContent

  return {
    // --- invariant: the screen's own claim, independent of any payload -----
    invariant: {
      inventoryRowCount: inventoryRows.length,
      statuses: statusNodes.map((n) => n.getAttribute('data-status')),
      pPlayStatus: byId('evidence-status-p-play')?.getAttribute('data-status') ?? null,
      pPlayNamesOwnerDecision: /owner decision/i.test(text(byId('evidence-p-play')) ?? ''),
      seasonsStatedPerRow: seasonNodes.length,
      // Blocker prose, read from the rendered cell rather than from the model.
      // Added after a control "passed" for an incidental reason: eight blocker
      // strings were rewritten and the only fields that moved were
      // documentHeight and screensToScroll, because nothing here read the
      // blocker column at all. A control that fires because the page got
      // taller looks like evidence and is not.
      //
      // The claim under test: every "computed, not exposed" row must name BOTH
      // blockers, because the route alone does not unblock it. Derived from the
      // DOM so it can disagree with the model.
      notExposedBlockersNameRouteAndStore: (() => {
        const rows = Array.from(
          document.querySelectorAll('[data-testid^="evidence-status-"]'),
        ).filter((n) => n.getAttribute('data-status') === 'not-exposed')
        const ids = rows.map((n) =>
          (n.getAttribute('data-testid') ?? '').replace('evidence-status-', ''),
        )
        return ids.map((id) => {
          const prose = (text(byId(`evidence-blocker-${id}`)) ?? '').toLowerCase()
          return { id, route: prose.includes('route'), store: prose.includes('store') }
        })
      })(),
      backToBackNamesBothHalves: (() => {
        const row = text(byId('evidence-back-to-back'))?.toLowerCase() ?? ''
        return {
          calendarHalf: row.includes('build_schedule_density'),
          observedHalf: row.includes('participation'),
          // The model-free claim must not be left standing over the whole row.
          qualified: /whether he sat|sit half/.test(row),
        }
      })(),
      tallyText: text(byId('evidence-tally')),
      tallyOnScreen: text(byId('evidence-tally-onscreen')),
      seasonBandEvidence: text(byId('season-band-evidence')),
      seasonBandVisible: !!byId('season-band')?.offsetHeight,
      observedGamesSaysNotOnApi: /Not on the API/.test(text(byId('schedule-evidence-observed')) ?? ''),
      // Scope limits, asserted as absences on the rendered page.
      rendersNoProbability: !/p\(play\)\s*[:=]?\s*0?\.\d/i.test(body),
      rendersNoLetterGrade: !/\bgrade[:\s]+[A-F][+-]?\b/i.test(body),
      rendersNoDollarValue: !/\$\s*\d/.test(body),
    },

    // --- mover: everything that must track the live season -----------------
    mover: {
      barCount: bars.length,
      min: screenMin,
      max: screenMax,
      distinct: new Set(games).size,
      tallestBarPercent: heights.length ? Math.max(...heights) : null,
      shortestBarPercent: heights.length ? Math.min(...heights) : null,
      ascending: games.every((g, i) => i === 0 || games[i - 1] <= g),
      rangeText: text(byId('assumptions-range')),
      cohortText: text(byId('assumptions-cohort')),
      divergenceText: text(byId('assumptions-divergence')),
      lowest: text(byId('assumption-lowest')),
      highest: text(byId('assumption-highest')),
      scheduleSeason: text(byId('schedule-evidence-season')),
      scheduleGames: text(byId('schedule-evidence-games')),
      scheduleUndated: text(byId('schedule-evidence-undated')),
    schedulePending: text(byId('schedule-evidence-pending')),
      assumptionsSplitKind: byId('assumptions-split')?.getAttribute('data-season-kind') ?? null,
      scheduleSplitKind: byId('schedule-evidence-split')?.getAttribute('data-season-kind') ?? null,
    },

    // --- ground truth, read in the same sitting ----------------------------
    api: {
      projectionsSeason: projections.season,
      statedAssumptions: apiGames.length,
      min: apiMin,
      max: apiMax,
      distinct: new Set(apiGames).size,
      scheduleSeason: schedule.season,
      teams: schedule.teams.length,
      periods: schedule.periods.length,
      sourceGames: line.source_game_count,
      resolvedGames: line.resolved_game_count,
      teamRows: line.persisted_team_row_count,
      undated: line.pending_games.filter((g) => g.game_date === null).length,
      teamsUndecided: line.pending_game_ids.length,
    },

    // --- the comparison, so a disagreement cannot be read past -------------
    agreement: {
      barCountMatchesApi: bars.length === apiGames.length,
      minMatchesApi: screenMin === apiMin,
      maxMatchesApi: screenMax === apiMax,
      // Cardinality is not identity. `size === size` passes for {59,60} against
      // {70,80}. I have a handoff entry from 2026-08-21 titled "Cardinality,
      // which every previous fix compared its way past" and then wrote this.
      distinctMatchesApi: (() => {
        const onScreen = [...new Set(games)].sort((a, b) => a - b)
        const fromApi = [...new Set(apiGames)].sort((a, b) => a - b)
        return (
          onScreen.length === fromApi.length && onScreen.every((v, i) => v === fromApi[i])
        )
      })(),
      // Presence is not assignment. Three numbers all present would pass even
      // if published and resolved were swapped, because `.includes` asks only
      // whether the digits appear somewhere in the row. Anchor each to its label.
      scheduleCountsOnScreen: (() => {
        const row = text(byId('schedule-evidence-games')) ?? ''
        return (
          new RegExp(`${line.source_game_count}\\s+published`).test(row) &&
          new RegExp(`${line.resolved_game_count}\\s+resolved`).test(row) &&
          new RegExp(`${line.persisted_team_row_count}\\s+team-rows`).test(row)
        )
      })(),
      // Derived from the producer's semantics, not from the field this probe
      // originally read. `pending_game_ids` is teams-not-yet-decided (ADR-013);
      // undated is `pending_games[].game_date === null`. The first version of
      // this flag compared the undated row against `pending_game_ids.length`
      // and passed, because both ends of the comparison inherited one
      // misreading. An agreeing probe is not a checking probe.
      undatedOnScreen: (() => {
        const trulyUndated = line.pending_games.filter((g) => g.game_date === null).length
        const row = text(byId('schedule-evidence-undated')) ?? ''
        return trulyUndated === 0
          ? row.includes('No scheduled game is missing a date')
          : row.includes(String(trulyUndated))
      })(),
      pendingTeamsOnScreen: (() => {
        const row = text(byId('schedule-evidence-pending')) ?? ''
        return line.pending_game_ids.length === 0
          ? row.includes('both teams assigned')
          : row.includes(String(line.pending_game_ids.length))
      })(),
      // The two are different quantities, so a screen showing one number twice
      // is a finding even when both rows individually "agree".
      // This flag was added to guard the pending/undated conflation and it
      // never looked at the screen: it compared two API fields to each other.
      // It asserted `0 !== 6`, a property of the payload, and could not fail
      // for any rendering reason on the live cohort. The guard against the
      // defect was itself an instance of the defect.
      undatedAndPendingAreDistinct: (() => {
        const trulyUndated = line.pending_games.filter((g) => g.game_date === null).length
        const teamsUndecided = line.pending_game_ids.length
        // When the two quantities coincide the screen cannot be caught confusing
        // them. Say so rather than returning a true that means nothing.
        if (trulyUndated === teamsUndecided) return null
        const undatedNums = (text(byId('schedule-evidence-undated')) ?? '').match(/\d+/g) ?? []
        const pendingNums = (text(byId('schedule-evidence-pending')) ?? '').match(/\d+/g) ?? []
        return (
          !undatedNums.map(Number).includes(teamsUndecided) &&
          pendingNums.map(Number).includes(teamsUndecided)
        )
      })(),
      teamsAndPeriodsOnScreen: (() => {
        const row = text(byId('schedule-evidence-season')) ?? ''
        return (
          new RegExp(`${schedule.teams.length}\\s+teams`).test(row) &&
          new RegExp(`${schedule.periods.length}\\s+scoring periods`).test(row)
        )
      })(),
    },

    // --- laptop fit, measured with a real viewport override ----------------
    layout: {
      viewport: [window.innerWidth, window.innerHeight],
      documentHeight: document.documentElement.scrollHeight,
      screensToScroll: Number((document.documentElement.scrollHeight / window.innerHeight).toFixed(2)),
      // Was: strip.getBoundingClientRect().width <= window.innerWidth. That is a
      // normal-flow block whose border-box width is set by its containing block,
      // so it was <= innerWidth by construction and could never report the other
      // answer. The overflow it was named for is flex-item overflow one level
      // down, which shows up as scrollWidth > clientWidth on .strip__bars and
      // never as a wider rect on the <figure>. Raw numbers are carried so the
      // margin is visible rather than only the verdict.
      stripOverflow: (() => {
        const strip = byId('assumption-strip')
        if (!strip) return null
        const bars = strip.querySelector('.strip__bars')
        if (!bars) return null
        const doc = document.documentElement
        return {
          barsScrollWidth: bars.scrollWidth,
          barsClientWidth: bars.clientWidth,
          barsOverflowing: bars.scrollWidth > bars.clientWidth,
          documentScrollWidth: doc.scrollWidth,
          viewportWidth: window.innerWidth,
          pageOverflowsHorizontally: doc.scrollWidth > window.innerWidth,
        }
      })(),
    },
  }
})()
