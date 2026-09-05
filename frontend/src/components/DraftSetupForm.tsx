import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { createDraft } from '../api/draftEndpoints'
import {
  describeDraftCreationError,
  isDraftCreationOutcomeUncertain,
} from '../api/draftErrors'
import {
  DRAFT_TOOL_USAGES,
  type CreateDraftRequest,
  type DraftSetupLeague,
  type DraftToolUsage,
} from '../api/draftTypes'

interface DraftSetupFormProps {
  leagues: DraftSetupLeague[]
  onCreated: (draftId: number) => void
  onCreationUncertain: () => void
}

type DraftKind = 'mock' | 'real'

function formatDraftType(value: DraftSetupLeague['format']['draft_type']): string {
  if (value === 'auction') return 'Auction'
  if (value === 'snake') return 'Snake'
  return 'Linear'
}

function slotLabel(league: DraftSetupLeague): string {
  return league.format.draft_type === 'auction' ? 'Tracker slot' : 'Draft position'
}

export function DraftSetupForm({
  leagues,
  onCreated,
  onCreationUncertain,
}: DraftSetupFormProps) {
  const ids = useId()
  const [leagueId, setLeagueId] = useState('')
  const [name, setName] = useState('')
  const [draftKind, setDraftKind] = useState<DraftKind | ''>('')
  const [toolUsage, setToolUsage] = useState<DraftToolUsage | ''>('')
  const [notes, setNotes] = useState('')
  const [ownerTeamId, setOwnerTeamId] = useState('')
  const [teamSlots, setTeamSlots] = useState<Record<string, string>>({})
  const [pending, setPending] = useState(false)
  const [creationLocked, setCreationLocked] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [creationError, setCreationError] = useState<Error | null>(null)

  const selectedLeague = leagues.find((league) => String(league.league_id) === leagueId) ?? null
  const ownerEvidence =
    selectedLeague?.fantasy_teams.find(
      (team) => team.fantasy_team_id === selectedLeague.owner_fantasy_team_id,
    ) ?? null

  function selectLeague(nextLeagueId: string) {
    const league = leagues.find((candidate) => String(candidate.league_id) === nextLeagueId)
    setLeagueId(nextLeagueId)
    setOwnerTeamId(
      league?.owner_fantasy_team_id === null || league?.owner_fantasy_team_id === undefined
        ? ''
        : String(league.owner_fantasy_team_id),
    )
    setTeamSlots({})
    setValidationError(null)
    setCreationError(null)
  }

  function assignSlot(fantasyTeamId: number, value: string) {
    setTeamSlots((current) => ({ ...current, [String(fantasyTeamId)]: value }))
    setValidationError(null)
  }

  function buildRequest(): CreateDraftRequest | null {
    if (selectedLeague === null) {
      setValidationError('Choose the persisted league this draft belongs to.')
      return null
    }

    const label = name.trim()
    if (label === '') {
      setValidationError('Name the draft before creating it.')
      return null
    }
    if (draftKind === '') {
      setValidationError('Declare whether this is a mock or the real draft.')
      return null
    }
    if (toolUsage === '') {
      setValidationError('Declare how much of this tool will be visible during the draft.')
      return null
    }

    const ownerId = Number(ownerTeamId)
    if (
      !Number.isInteger(ownerId) ||
      !selectedLeague.fantasy_teams.some((team) => team.fantasy_team_id === ownerId)
    ) {
      setValidationError('Choose which persisted fantasy team is yours.')
      return null
    }

    const participants = selectedLeague.fantasy_teams.map((team) => ({
      team,
      teamSlot: Number(teamSlots[String(team.fantasy_team_id)]),
    }))
    const assignedSlots = participants.map(({ teamSlot }) => teamSlot)
    const expectedSlots = Array.from(
      { length: selectedLeague.format.team_count },
      (_, index) => index + 1,
    )
    if (
      assignedSlots.some((value) => !Number.isInteger(value)) ||
      [...assignedSlots].sort((left, right) => left - right).some(
        (value, index) => value !== expectedSlots[index],
      )
    ) {
      setValidationError(
        `Assign every team exactly one ${slotLabel(selectedLeague).toLowerCase()} from 1 to ${String(selectedLeague.format.team_count)}.`,
      )
      return null
    }

    return {
      league_id: selectedLeague.league_id,
      name: label,
      is_mock: draftKind === 'mock',
      tool_usage: toolUsage,
      source_board_profile: null,
      notes: notes.trim() === '' ? null : notes.trim(),
      participants: participants
        .map(({ team, teamSlot }) => ({
          team_slot: teamSlot,
          source_seat: null,
          display_name: team.display_name,
          is_owner: team.fantasy_team_id === ownerId,
          fantasy_team_id: team.fantasy_team_id,
        }))
        .sort((left, right) => left.team_slot - right.team_slot),
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending) return

    const request = buildRequest()
    if (request === null) return

    setPending(true)
    setValidationError(null)
    setCreationError(null)
    try {
      const created = await createDraft(request)
      onCreated(created.id)
    } catch (cause) {
      const failure = cause instanceof Error ? cause : new Error(String(cause))
      setCreationError(failure)
      if (isDraftCreationOutcomeUncertain(failure)) {
        setCreationLocked(true)
        onCreationUncertain()
      }
    } finally {
      setPending(false)
    }
  }

  const describedError = creationError ? describeDraftCreationError(creationError) : null
  const backendWording = creationError?.message ?? null
  const showBackendWording =
    backendWording !== null && backendWording !== describedError?.summary
  const errorCode = creationError instanceof ApiError ? creationError.code : null
  const requestId = creationError instanceof ApiError ? creationError.requestId : null
  const assignedSlotValues = new Set(Object.values(teamSlots).filter((value) => value !== ''))

  return (
    <form className="draft-setup__form" onSubmit={(event) => void submit(event)} noValidate>
      <fieldset
        className="draft-setup__fieldset"
        disabled={pending || creationLocked}
        aria-busy={pending}
      >
        <legend>Required setup</legend>

        <label className="draft-setup__field" htmlFor={`${ids}-league`}>
          <span>League</span>
          <select
            id={`${ids}-league`}
            value={leagueId}
            onChange={(event) => selectLeague(event.target.value)}
            required
          >
            <option value="">Choose a persisted league</option>
            {leagues.map((league) => (
              <option key={league.league_id} value={league.league_id}>
                {league.name} ({league.season})
              </option>
            ))}
          </select>
        </label>

        {selectedLeague === null ? (
          <p className="draft-setup__prompt">Choose a league to inspect its frozen setup evidence.</p>
        ) : (
          <>
            <section className="draft-setup__evidence" aria-labelledby={`${ids}-evidence-title`}>
              <h3 id={`${ids}-evidence-title`}>Persisted setup evidence</h3>
              <dl className="facts">
                <div className="facts__row">
                  <dt>Format</dt>
                  <dd>{formatDraftType(selectedLeague.format.draft_type)}</dd>
                </div>
                <div className="facts__row">
                  <dt>Teams and rosters</dt>
                  <dd>
                    {selectedLeague.format.team_count} teams x {selectedLeague.format.roster_size}{' '}
                    players = {selectedLeague.format.total_roster_slots} total slots
                  </dd>
                </div>
                <div className="facts__row">
                  <dt>Shared auction budget</dt>
                  <dd>
                    {selectedLeague.format.auction_budget === null
                      ? 'Not applicable'
                      : `$${selectedLeague.format.auction_budget} per team`}
                  </dd>
                </div>
                <div className="facts__row">
                  <dt>Persisted owner team</dt>
                  <dd>{ownerEvidence?.display_name ?? 'Not assigned'}</dd>
                </div>
              </dl>
              <p className="draft-setup__help">
                The budget is the league-frozen shared amount. There is no per-team budget editor.
                Team order below is presentation only and supplies neither a tracker slot nor a
                source-board seat.
              </p>
            </section>

            <div className="draft-setup__fields">
              <label className="draft-setup__field" htmlFor={`${ids}-name`}>
                <span>Draft name</span>
                <input
                  id={`${ids}-name`}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  maxLength={128}
                  autoComplete="off"
                  required
                />
              </label>

              <label className="draft-setup__field" htmlFor={`${ids}-owner`}>
                <span>Your fantasy team</span>
                <select
                  id={`${ids}-owner`}
                  value={ownerTeamId}
                  onChange={(event) => {
                    setOwnerTeamId(event.target.value)
                    setValidationError(null)
                  }}
                  required
                >
                  <option value="">
                    {selectedLeague.owner_fantasy_team_id === null
                      ? 'No owner is persisted - choose your team'
                      : 'Choose your team'}
                  </option>
                  {selectedLeague.fantasy_teams.map((team) => (
                    <option key={team.fantasy_team_id} value={team.fantasy_team_id}>
                      {team.display_name}
                      {team.fantasy_team_id === selectedLeague.owner_fantasy_team_id
                        ? ' (persisted owner)'
                        : ''}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <fieldset className="draft-setup__choice">
              <legend>Draft evidence</legend>
              <label>
                <input
                  type="radio"
                  name={`${ids}-draft-kind`}
                  value="mock"
                  checked={draftKind === 'mock'}
                  onChange={() => setDraftKind('mock')}
                  required
                />
                Mock draft
              </label>
              <label>
                <input
                  type="radio"
                  name={`${ids}-draft-kind`}
                  value="real"
                  checked={draftKind === 'real'}
                  onChange={() => setDraftKind('real')}
                  required
                />
                Real draft
              </label>
            </fieldset>

            <label className="draft-setup__field" htmlFor={`${ids}-tool-usage`}>
              <span>Tool usage</span>
              <select
                id={`${ids}-tool-usage`}
                value={toolUsage}
                onChange={(event) => setToolUsage(event.target.value as DraftToolUsage | '')}
                required
              >
                <option value="">Choose what will be visible while drafting</option>
                {DRAFT_TOOL_USAGES.map((usage) => (
                  <option key={usage} value={usage}>
                    {usage === 'blind'
                      ? 'Blind - no hoops-gm screen'
                      : usage === 'partial'
                        ? 'Partial - hoops-gm used for part of the draft'
                        : 'Instrumented - hoops-gm visible throughout'}
                  </option>
                ))}
              </select>
            </label>

            <fieldset className="draft-setup__slots">
              <legend>{slotLabel(selectedLeague)} assignment</legend>
              <p className="draft-setup__help">
                Assign every team explicitly. These values become immutable local participant
                slots; no Fantrax source-seat binding is inferred.
              </p>
              <div className="draft-setup__slot-list">
                {selectedLeague.fantasy_teams.map((team) => {
                  const currentSlot = teamSlots[String(team.fantasy_team_id)] ?? ''
                  return (
                    <label
                      className="draft-setup__slot"
                      key={team.fantasy_team_id}
                      htmlFor={`${ids}-slot-${String(team.fantasy_team_id)}`}
                    >
                      <span>
                        {team.display_name}
                        {String(team.fantasy_team_id) === ownerTeamId ? (
                          <small>your team</small>
                        ) : null}
                      </span>
                      <select
                        id={`${ids}-slot-${String(team.fantasy_team_id)}`}
                        value={currentSlot}
                        onChange={(event) =>
                          assignSlot(team.fantasy_team_id, event.target.value)
                        }
                        aria-label={`${slotLabel(selectedLeague)} for ${team.display_name}`}
                        required
                      >
                        <option value="">Choose</option>
                        {Array.from(
                          { length: selectedLeague.format.team_count },
                          (_, index) => String(index + 1),
                        ).map((slot) => (
                          <option
                            key={slot}
                            value={slot}
                            disabled={slot !== currentSlot && assignedSlotValues.has(slot)}
                          >
                            {slot}
                          </option>
                        ))}
                      </select>
                    </label>
                  )
                })}
              </div>
            </fieldset>

            <label className="draft-setup__field" htmlFor={`${ids}-notes`}>
              <span>Notes (optional)</span>
              <textarea
                id={`${ids}-notes`}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                rows={3}
              />
            </label>

            <p className="draft-setup__help">
              Creation opens the board. Automatic pick and budget tracking remain downstream and
              begin only when the board receives trustworthy evidence.
            </p>

            <button className="draft-setup__submit" type="submit" disabled={pending}>
              {pending ? 'Creating draft...' : 'Create draft and open board'}
            </button>
          </>
        )}
      </fieldset>

      {validationError ? (
        <p className="state state--error draft-setup__error" role="alert">
          {validationError}
        </p>
      ) : null}

      {describedError ? (
        <div className="state state--error draft-setup__error" role="alert">
          <p>{describedError.summary}</p>
          <p className="state__detail">{describedError.action}</p>
          {showBackendWording ? (
            <p className="state__meta">
              Backend said: <q>{backendWording}</q>
            </p>
          ) : null}
          {errorCode || requestId ? (
            <p className="state__meta">
              {errorCode ? (
                <>
                  Code <code>{errorCode}</code>
                </>
              ) : null}
              {errorCode && requestId ? ' - ' : null}
              {requestId ? <>Request {requestId}</> : null}
            </p>
          ) : null}
        </div>
      ) : null}
    </form>
  )
}
