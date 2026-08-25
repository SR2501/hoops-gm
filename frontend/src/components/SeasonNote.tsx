/**
 * The season a cohort was loaded for, stated against the season evidence reads.
 *
 * **This is the `gameEt` lesson applied to a season label.** Two seasons appear
 * on the reliability screen — the cohort loaded from the API, and the season
 * durability evidence would be measured over — and a reader who conflates them
 * concludes something false about every number in front of them. A well-formed,
 * plausible season string does not explain itself, so the *relationship*
 * between the two is computed and rendered rather than left to be inferred from
 * two labels sitting near each other.
 *
 * **Why it renders beside the numbers rather than once at the top.** A reader
 * who scrolls to a panel and reads `59–79` has to be able to see from that
 * panel which season it is about. A season label three sections away is a label
 * the reader supplies from memory, which is exactly how the two get conflated.
 *
 * It lives in `components/` rather than in the route so that both panels can use
 * it without the panel importing its own page.
 */

import { describeSeasonSplit } from './reliabilityModel'

export function SeasonNote({ season, testId }: { season: string; testId: string }) {
  const split = describeSeasonSplit(season)

  return (
    <p className="season-split" data-testid={testId} data-season-kind={split.kind}>
      {split.kind === 'differs' ? (
        <>
          Cohort season <code>{split.loaded}</code>.{' '}
          <strong>This is not the season availability evidence reads ({split.evidence}).</strong>{' '}
          Nothing in this panel is a durability observation — it describes the upcoming season
          the cohort was imported for.
        </>
      ) : (
        <>
          Cohort season <code>{split.season}</code>, which <strong>is</strong> the season
          availability evidence reads. Worth stating rather than passing over: the two coincide
          only once the season has rolled over, and at that point the evidence-season decision
          needs revisiting rather than silently continuing to hold.
        </>
      )}
    </p>
  )
}
