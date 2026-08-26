/**
 * The inventory of availability evidence, and the reason each piece is missing.
 *
 * This is the screen's main content, which is an unusual thing for a table of
 * absences to be. It is deliberate. The owner's stated fear is a pretty shell
 * that does not work on draft day, and the honest defence against that is not a
 * screen with fewer holes — it is a screen whose holes are labelled, so nobody
 * mistakes the shell for the building.
 *
 * Rendered as a table rather than as prose because the columns are the point: a
 * reader scanning it should be able to see at a glance which of these are
 * someone's to unblock and which are decisions nobody has made yet, without
 * reading eight paragraphs to find out.
 */

import {
  AVAILABILITY_EVIDENCE,
  EVIDENCE_STATUS_LABELS,
  tallyEvidence,
  type EvidenceItem,
} from './reliabilityModel'

export function EvidenceInventory({
  items = AVAILABILITY_EVIDENCE,
}: {
  items?: readonly EvidenceItem[]
}) {
  const tally = tallyEvidence(items)

  return (
    <>
      <p className="evidence__tally" data-testid="evidence-tally">
        <strong data-testid="evidence-tally-onscreen">{tally.onScreen}</strong> of{' '}
        <strong>{tally.total}</strong> availability quantities are on this screen.{' '}
        {tally.notExposed} are computed by the backend and carried by no route, {tally.notDefined}{' '}
        have never been defined, and {tally.blocked} is deliberately held. The table says which is
        which, and what is blocking each.
      </p>
      <table className="table evidence" data-testid="evidence-inventory">
      <caption className="evidence__caption">
        Every quantity a reliability screen is supposed to carry, and where each one
        actually is. <strong>Nothing in this table is a placeholder for a number</strong> —
        the status is the finding.
      </caption>
      <thead>
        <tr>
          <th scope="col">Quantity</th>
          <th scope="col">State, and which season it would describe</th>
          <th scope="col">What it would tell you</th>
          <th scope="col">Where it is now</th>
          <th scope="col">What is blocking it</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.id} data-testid={`evidence-${item.id}`}>
            <th scope="row" className="evidence__quantity">
              {item.quantity}
            </th>
            <td>
              <span
                className={`evidence__status evidence__status--${item.status}`}
                data-testid={`evidence-status-${item.id}`}
                data-status={item.status}
              >
                {EVIDENCE_STATUS_LABELS[item.status]}
              </span>
              <span className="evidence__season" data-testid={`evidence-season-${item.id}`}>
                {item.season}
              </span>
            </td>
            <td>{item.purpose}</td>
            <td>{item.whereItLives}</td>
            <td data-testid={`evidence-blocker-${item.id}`}>{item.blocker}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </>
  )
}
