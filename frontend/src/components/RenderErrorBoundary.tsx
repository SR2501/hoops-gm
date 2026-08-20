import { Component, type ErrorInfo, type ReactNode } from 'react'
import { ApiError } from '../api/client'

interface RenderErrorBoundaryProps {
  children: ReactNode
  resetKey?: unknown
  onRetry?: () => void
}

interface RenderErrorBoundaryState {
  error: Error | null
}

export class RenderErrorBoundary extends Component<
  RenderErrorBoundaryProps,
  RenderErrorBoundaryState
> {
  state: RenderErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: unknown): RenderErrorBoundaryState {
    return {
      error: error instanceof Error ? error : new Error(String(error)),
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('A dashboard view failed to render.', error, info.componentStack)
  }

  componentDidUpdate(previousProps: RenderErrorBoundaryProps) {
    if (this.state.error && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  private readonly retry = () => {
    this.props.onRetry?.()
    this.setState({ error: null })
  }

  render() {
    const { error } = this.state
    if (!error) {
      return this.props.children
    }

    const code = error instanceof ApiError ? error.code : null
    const requestId = error instanceof ApiError ? error.requestId : null

    return (
      <section className="state state--error render-error" role="alert">
        <h1>This view could not be rendered.</h1>
        <p className="state__detail">{error.message}</p>
        {code || requestId ? (
          <p className="state__meta">
            {code ? (
              <>
                Code <code>{code}</code>
              </>
            ) : null}
            {code && requestId ? ' · ' : null}
            {requestId ? <>Request {requestId}</> : null}
          </p>
        ) : null}
        <p className="state__detail">
          Try rendering the view again. If it fails repeatedly, use the request context above to
          inspect the backend logs.
        </p>
        <button type="button" onClick={this.retry}>
          Try again
        </button>
      </section>
    )
  }
}
