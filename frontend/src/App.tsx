import { Route, Routes, useLocation } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { RenderErrorBoundary } from './components/RenderErrorBoundary'
import { DashboardPage } from './routes/DashboardPage'
import { NotFoundPage } from './routes/NotFoundPage'
import { SystemPage } from './routes/SystemPage'

/**
 * Route table.
 *
 * Flat and explicit. Every route the plan calls for — draft board, scorecard,
 * trade lab — is a sibling of these, added by its owning phase.
 */
export function App() {
  const location = useLocation()

  return (
    <RenderErrorBoundary resetKey={location.key}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="system" element={<SystemPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </RenderErrorBoundary>
  )
}
