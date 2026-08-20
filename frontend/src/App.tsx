import type { ReactNode } from 'react'
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
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route
          index
          element={
            <RouteBoundary>
              <DashboardPage />
            </RouteBoundary>
          }
        />
        <Route
          path="system"
          element={
            <RouteBoundary>
              <SystemPage />
            </RouteBoundary>
          }
        />
        <Route
          path="*"
          element={
            <RouteBoundary>
              <NotFoundPage />
            </RouteBoundary>
          }
        />
      </Route>
    </Routes>
  )
}

function RouteBoundary({ children }: { children: ReactNode }) {
  const location = useLocation()
  return <RenderErrorBoundary resetKey={location.key}>{children}</RenderErrorBoundary>
}
