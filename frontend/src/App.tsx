import { Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { DashboardPage } from './routes/DashboardPage'
import { DraftPage } from './routes/DraftPage'
import { DraftsPage } from './routes/DraftsPage'
import { NotFoundPage } from './routes/NotFoundPage'
import { ProjectionsPage } from './routes/ProjectionsPage'
import { ReliabilityPage } from './routes/ReliabilityPage'
import { SchedulePage } from './routes/SchedulePage'
import { SystemPage } from './routes/SystemPage'

/**
 * Route table.
 *
 * Flat and explicit. Every route the plan calls for — draft board, scorecard,
 * trade lab — is a sibling of these, added by its owning phase.
 */
export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="schedule" element={<SchedulePage />} />
        <Route path="projections" element={<ProjectionsPage />} />
        <Route path="reliability" element={<ReliabilityPage />} />
        <Route path="draft" element={<DraftsPage />} />
        <Route path="draft/:draftId" element={<DraftPage />} />
        <Route path="system" element={<SystemPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
