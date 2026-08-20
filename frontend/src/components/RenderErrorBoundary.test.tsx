import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { RenderErrorBoundary } from './RenderErrorBoundary'

describe('RenderErrorBoundary', () => {
  it('shows actionable request context and can recover from a render exception', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let shouldThrow = true

    function FragileView() {
      if (shouldThrow) {
        throw new ApiError(
          500,
          'render_contract_error',
          'A response escaped its render guard.',
          'req-render',
        )
      }
      return <p>Recovered view</p>
    }

    render(
      <RenderErrorBoundary
        onRetry={() => {
          shouldThrow = false
        }}
      >
        <FragileView />
      </RenderErrorBoundary>,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('This view could not be rendered.')
    expect(screen.getByRole('alert')).toHaveTextContent('Code render_contract_error')
    expect(screen.getByRole('alert')).toHaveTextContent('Request req-render')
    expect(consoleError).toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(screen.getByText('Recovered view')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
