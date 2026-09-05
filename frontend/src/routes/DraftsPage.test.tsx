import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DraftSetupLeague, DraftSetupResponse } from '../api/draftTypes'
import recordedDraft from '../test/fixtures/draft-auction-state.recorded.json'
import recordedDraftList from '../test/fixtures/draft-list.recorded.json'
import { requestUrl } from '../test/helpers'
import { DraftsPage } from './DraftsPage'

const AUCTION_LEAGUE = {
  league_id: 7,
  name: 'Auction league',
  season: '2026-27',
  format: {
    draft_type: 'auction',
    team_count: 2,
    roster_size: 13,
    total_roster_slots: 26,
    auction_budget: '200.00',
  },
  owner_fantasy_team_id: 72,
  fantasy_teams: [
    { fantasy_team_id: 71, display_name: 'Alpha rivals' },
    { fantasy_team_id: 72, display_name: 'Owner team' },
  ],
} satisfies DraftSetupLeague

const SNAKE_LEAGUE = {
  league_id: 8,
  name: 'Snake league',
  season: '2026-27',
  format: {
    draft_type: 'snake',
    team_count: 2,
    roster_size: 12,
    total_roster_slots: 24,
    auction_budget: null,
  },
  owner_fantasy_team_id: null,
  fantasy_teams: [
    { fantasy_team_id: 81, display_name: 'East team' },
    { fantasy_team_id: 82, display_name: 'West team' },
  ],
} satisfies DraftSetupLeague

const SETUP = { leagues: [AUCTION_LEAGUE, SNAKE_LEAGUE] } satisfies DraftSetupResponse

interface ApiPlan {
  setup?: DraftSetupResponse
  setupError?: { status: number; error: string; detail: string; requestId: string }
  setupPending?: boolean
  list?: unknown
  createError?: { status: number; error: string; detail: string; requestId: string }
  createReject?: boolean
  createdId?: number
}

function response(body: unknown, status = 200, requestId?: string): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...(requestId === undefined ? {} : { 'X-Request-ID': requestId }),
    },
  })
}

function installApi(plan: ApiPlan = {}) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = requestUrl(input)
    const method = init?.method ?? 'GET'

    if (url === '/api/v1/drafts/setup') {
      if (plan.setupPending) return new Promise<Response>(() => undefined)
      if (plan.setupError) {
        return Promise.resolve(
          response(
            {
              error: plan.setupError.error,
              detail: plan.setupError.detail,
              request_id: plan.setupError.requestId,
            },
            plan.setupError.status,
            plan.setupError.requestId,
          ),
        )
      }
      return Promise.resolve(response(plan.setup ?? SETUP))
    }

    if (url === '/api/v1/drafts' && method === 'GET') {
      return Promise.resolve(response(plan.list ?? { drafts: [] }))
    }

    if (url === '/api/v1/drafts' && method === 'POST') {
      if (plan.createReject) return Promise.reject(new TypeError('connection refused'))
      if (plan.createError) {
        return Promise.resolve(
          response(
            {
              error: plan.createError.error,
              detail: plan.createError.detail,
              request_id: plan.createError.requestId,
            },
            plan.createError.status,
            plan.createError.requestId,
          ),
        )
      }
      return Promise.resolve(response({ ...recordedDraft, id: plan.createdId ?? 41 }, 201))
    }

    return Promise.reject(new TypeError(`Unmocked request: ${url}`))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/draft']}>
      <Routes>
        <Route path="/draft" element={<DraftsPage />} />
        <Route path="/draft/:draftId" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

function postedBody(init: RequestInit | undefined): Record<string, unknown> {
  const body = init?.body
  if (typeof body !== 'string') throw new Error('Expected a JSON request body')
  return JSON.parse(body) as Record<string, unknown>
}

async function chooseAuctionSetup(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(await screen.findByLabelText('League'), String(AUCTION_LEAGUE.league_id))
  await user.type(screen.getByLabelText('Draft name'), 'September auction mock')
  await user.click(screen.getByRole('radio', { name: 'Mock draft' }))
  await user.selectOptions(screen.getByLabelText('Tool usage'), 'partial')
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Tracker slot for Alpha rivals' }),
    '2',
  )
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Tracker slot for Owner team' }),
    '1',
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('draft setup screen', () => {
  it('renders a loading state while preserving the independent recorded-drafts result', async () => {
    installApi({ setupPending: true })
    renderPage()

    expect(await screen.findByRole('status')).toHaveTextContent('Loading draft setup evidence')
    expect(
      await screen.findByText(/No drafts have been recorded in this database\./),
    ).toBeInTheDocument()
  })

  it('renders empty setup honestly and preserves the existing draft list', async () => {
    installApi({ setup: { leagues: [] }, list: recordedDraftList })
    renderPage()

    expect(
      await screen.findByText(/No persisted league can create a draft yet/),
    ).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: '[demo] Auction mock, 12-team $200' }))
      .toBeInTheDocument()
  })

  it.each([
    {
      status: 403,
      error: 'drafts_local_only',
      detail: 'Draft setup evidence is only served to the local machine.',
      requestId: 'req-local-only',
      expected: 'Recorded drafts are served to this machine only',
    },
    {
      status: 422,
      error: 'draft_setup_settings_stale',
      detail: 'Current settings carry stale season evidence.',
      requestId: 'req-stale-settings',
      expected: 'newest persisted settings describe a different league',
    },
  ])(
    'shows an actionable $status setup refusal without hiding the recorded-drafts state',
    async ({ status, error, detail, requestId, expected }) => {
      installApi({ setupError: { status, error, detail, requestId } })
      renderPage()

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent(expected)
      expect(alert).toHaveTextContent(detail)
      expect(alert).toHaveTextContent(error)
      expect(alert).toHaveTextContent(requestId)
      expect(
        await screen.findByText(/No drafts have been recorded in this database\./),
      ).toBeInTheDocument()
    },
  )

  it('creates an auction board from explicit slots without inventing budgets or source seats', async () => {
    const user = userEvent.setup()
    const fetchMock = installApi({ createdId: 91 })
    renderPage()

    await chooseAuctionSetup(user)

    expect(screen.getByText('$200.00 per team')).toBeInTheDocument()
    expect(screen.getByText('Owner team', { selector: 'dd' })).toBeInTheDocument()
    expect(screen.getByLabelText('Your fantasy team')).toHaveValue('72')
    expect(screen.getByRole('group', { name: 'Draft evidence' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Create draft and open board' }))

    expect(await screen.findByTestId('location')).toHaveTextContent('/draft/91')
    const post = fetchMock.mock.calls.find(
      ([input, init]) => requestUrl(input) === '/api/v1/drafts' && init?.method === 'POST',
    )
    expect(post).toBeDefined()
    const body = postedBody(post?.[1])
    expect(body).toEqual({
      league_id: 7,
      name: 'September auction mock',
      is_mock: true,
      tool_usage: 'partial',
      source_board_profile: null,
      notes: null,
      participants: [
        {
          team_slot: 1,
          source_seat: null,
          display_name: 'Owner team',
          is_owner: true,
          fantasy_team_id: 72,
        },
        {
          team_slot: 2,
          source_seat: null,
          display_name: 'Alpha rivals',
          is_owner: false,
          fantasy_team_id: 71,
        },
      ],
    })
    expect(body).not.toHaveProperty('auction_budget')
  })

  it('requires an explicit owner when persisted owner evidence is null and creates a snake board', async () => {
    const user = userEvent.setup()
    const fetchMock = installApi({ createdId: 92 })
    renderPage()

    await user.selectOptions(await screen.findByLabelText('League'), String(SNAKE_LEAGUE.league_id))
    await user.type(screen.getByLabelText('Draft name'), 'Snake rehearsal')
    await user.click(screen.getByRole('radio', { name: 'Real draft' }))
    await user.selectOptions(screen.getByLabelText('Tool usage'), 'blind')
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Draft position for East team' }),
      '2',
    )
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Draft position for West team' }),
      '1',
    )

    expect(screen.getByText('Not assigned', { selector: 'dd' })).toBeInTheDocument()
    expect(screen.getByLabelText('Your fantasy team')).toHaveValue('')
    await user.click(screen.getByRole('button', { name: 'Create draft and open board' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Choose which persisted fantasy team is yours.',
    )
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST'),
    ).toHaveLength(0)

    await user.selectOptions(screen.getByLabelText('Your fantasy team'), '81')
    await user.click(screen.getByRole('button', { name: 'Create draft and open board' }))

    expect(await screen.findByTestId('location')).toHaveTextContent('/draft/92')
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    const body = postedBody(post?.[1]) as unknown as {
      is_mock: boolean
      participants: { fantasy_team_id: number; team_slot: number; is_owner: boolean }[]
    }
    expect(body.is_mock).toBe(false)
    expect(body.participants).toEqual([
      {
        team_slot: 1,
        source_seat: null,
        display_name: 'West team',
        is_owner: false,
        fantasy_team_id: 82,
      },
      {
        team_slot: 2,
        source_seat: null,
        display_name: 'East team',
        is_owner: true,
        fantasy_team_id: 81,
      },
    ])
  })

  it('keeps the completed form intact and gives creation-specific guidance after a request failure', async () => {
    const user = userEvent.setup()
    const fetchMock = installApi({ createReject: true })
    renderPage()
    await chooseAuctionSetup(user)

    await user.click(screen.getByRole('button', { name: 'Create draft and open board' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('whether the draft was created is unknown')
    expect(alert).toHaveTextContent('recorded drafts list is refreshing')
    expect(alert).toHaveTextContent('reload this page')
    expect(screen.getByLabelText('Draft name')).toHaveValue('September auction mock')
    expect(screen.getByRole('button', { name: 'Create draft and open board' })).toBeDisabled()
    expect(screen.queryByTestId('location')).not.toBeInTheDocument()
    await vi.waitFor(() => {
      const listRequests = fetchMock.mock.calls.filter(
        ([input, init]) => requestUrl(input) === '/api/v1/drafts' && (init?.method ?? 'GET') === 'GET',
      )
      expect(listRequests).toHaveLength(2)
    })
  })

  it('locks and refreshes after a malformed success response could hide a committed draft', async () => {
    const user = userEvent.setup()
    const fetchMock = installApi({ createdId: 1.5 })
    renderPage()
    await chooseAuctionSetup(user)

    await user.click(screen.getByRole('button', { name: 'Create draft and open board' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('whether the draft was created is unknown')
    expect(alert).toHaveTextContent('retry here could create a duplicate')
    expect(alert).toHaveTextContent('invalid_response')
    expect(screen.getByRole('button', { name: 'Create draft and open board' })).toBeDisabled()
    await vi.waitFor(() => {
      const listRequests = fetchMock.mock.calls.filter(
        ([input, init]) => requestUrl(input) === '/api/v1/drafts' && (init?.method ?? 'GET') === 'GET',
      )
      expect(listRequests).toHaveLength(2)
    })
  })

  it('keeps backend creation refusal detail, code, and request id visible', async () => {
    const user = userEvent.setup()
    installApi({
      createError: {
        status: 422,
        error: 'draft_participants_incomplete',
        detail: 'A 2-team draft needs every team slot exactly once.',
        requestId: 'req-create-refused',
      },
    })
    renderPage()
    await chooseAuctionSetup(user)

    await user.click(screen.getByRole('button', { name: 'Create draft and open board' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('one seat per team')
    expect(alert).toHaveTextContent('A 2-team draft needs every team slot exactly once.')
    expect(alert).toHaveTextContent('draft_participants_incomplete')
    expect(alert).toHaveTextContent('req-create-refused')
  })

  it('exposes every slot picker through its native team-specific label', async () => {
    const user = userEvent.setup()
    installApi()
    renderPage()

    await user.selectOptions(await screen.findByLabelText('League'), String(AUCTION_LEAGUE.league_id))

    const slots = within(screen.getByRole('group', { name: 'Tracker slot assignment' }))
    expect(slots.getByRole('combobox', { name: 'Tracker slot for Alpha rivals' }))
      .toBeInTheDocument()
    expect(slots.getByRole('combobox', { name: 'Tracker slot for Owner team' }))
      .toBeInTheDocument()
  })

  it('keeps the required setup controls in native keyboard order', async () => {
    const user = userEvent.setup()
    installApi()
    renderPage()

    const league = await screen.findByLabelText('League')
    expect(league).toHaveProperty('tagName', 'SELECT')

    await user.tab()
    expect(league).toHaveFocus()
    await user.selectOptions(league, String(AUCTION_LEAGUE.league_id))

    await user.tab()
    expect(screen.getByLabelText('Draft name')).toHaveFocus()
    await user.tab()
    expect(screen.getByLabelText('Your fantasy team')).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('radio', { name: 'Mock draft' })).toHaveFocus()
  })
})
