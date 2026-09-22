/**
 * Genuine HTTP response bytes copied natively from the owner's frontend-http
 * capture under session d46e1efa-c5df-4003-a999-0f94f6b61d73, directory
 * files/projection-series-candidate. Manifest: 2026-09-18T20:55:48.663058+00:00.
 * Fresh Alembic-0024 synthetic store; real writers/producers; no services or
 * private inputs. Normal seed captured before later Josh/Bonus imports.
 *
 * Each JSON file is exact response.content + LF, not rebuilt from these types.
 * Named series are overlapping 55-player cohorts, with nonuniform differences.
 * This helper validates, but never repairs or retags, a recorded response.
 * Transport/render evidence only, not independent scientific carry-forward.
 */
import { isCurrentProjections } from '../api/endpoints'
import { isProductionCandidatesResponse } from '../api/productionCandidatesEndpoints'
import {
  isDraftProjectionSeriesCatalog,
  isProjectionSeriesCatalog,
} from '../api/projectionSeriesEndpoints'
import legacyProjections from './fixtures/projections-current.series-release.recorded.json'
import joshProjections from './fixtures/projections-current.josh.recorded.json'
import bonusProjections from './fixtures/projections-current.bonus.recorded.json'
import legacyCandidates from './fixtures/draft-production-candidates.series-release.recorded.json'
import joshCandidates from './fixtures/draft-production-candidates.josh.recorded.json'
import bonusCandidates from './fixtures/draft-production-candidates.bonus.recorded.json'
import leagueCatalog from './fixtures/league-projection-series.recorded.json'
import draftCatalog from './fixtures/draft-projection-series.recorded.json'
import singleCatalog from './fixtures/projection-series-single.recorded.json'

function checked<T>(value: unknown, guard: (value: unknown) => value is T): T {
  if (!guard(value)) throw new Error('The genuine series HTTP recording does not satisfy the client contract.')
  return value
}

export const projectionRecordings = {
  legacy: checked(legacyProjections, isCurrentProjections),
  josh: checked(joshProjections, isCurrentProjections),
  bonus: checked(bonusProjections, isCurrentProjections),
}
export const candidateRecordings = {
  legacy: checked(legacyCandidates, isProductionCandidatesResponse),
  josh: checked(joshCandidates, isProductionCandidatesResponse),
  bonus: checked(bonusCandidates, isProductionCandidatesResponse),
}
export const recordedLeagueCatalog = checked(leagueCatalog, isProjectionSeriesCatalog)
export const recordedDraftCatalog = checked(draftCatalog, isDraftProjectionSeriesCatalog)
export const recordedSingleCatalog = checked(singleCatalog, isDraftProjectionSeriesCatalog)
