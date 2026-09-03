/**
 * Which import produced the numbers on screen, and how well pinned each part is.
 *
 * Collapsed by default so it does not compete with the table, but on the page
 * rather than in devtools: a number whose provenance can only be recovered by
 * opening a network tab is not checkable.
 *
 * **Three digests, because they answer different questions.**
 * `content_sha256` is the CSV bytes; `profile_definition_sha256` is the parsing
 * recipe those bytes were read under; `projection_values_sha256` is over the
 * stored, normalised rates — the only one of the three that moves when a row is
 * edited in place. Shown verbatim rather than summarised, because a fingerprint
 * a reader cannot quote is one they cannot check.
 *
 * `imported_at` is shown as the raw string the backend sent. A self-describing
 * timestamp is exactly the kind of field that carries a `Z` and is not UTC, and
 * the raw string is what lets someone check the claim against the backend
 * rather than trust this component's arithmetic.
 *
 * **The audit counts are stated as a partition because they are one**, and the
 * backend asserts that on the served body rather than only claiming it in
 * prose. `projection_count` is deliberately shown apart from them: it is the
 * rows the canonical release validated and the ones this response actually
 * carries, and it equals `matched_count` only while no earlier import for the
 * same source and season contributed to the crosswalk differently. Both are
 * published rather than one derived from the other, so both are shown.
 */

import type { ProjectionLineage } from '../api/types'

interface ProjectionLineagePanelProps {
  lineage: ProjectionLineage
  /**
   * Rate rows available to the browser after the response is joined.
   *
   * This is deliberately independent of transient filters and progressive
   * mounting: lineage describes the imported cohort the browser can inspect,
   * not the subset of DOM rows mounted at this instant.
   */
  availableRateRowCount: number
}

export function ProjectionLineagePanel({
  lineage,
  availableRateRowCount,
}: ProjectionLineagePanelProps) {
  const { projection_import: imported } = lineage
  const partitionTotal =
    imported.matched_count +
    imported.needs_review_count +
    imported.unmatched_count +
    imported.rejected_count

  return (
    <details className="lineage" data-testid="projections-lineage">
      <summary className="lineage__summary">
        <span>
          Basketball Monster import <code>{imported.projection_values_sha256.slice(0, 12)}</code>
        </span>
        <span className="lineage__age" data-testid="projections-blend-state">
          {/* Rendered from `blend === null`, a fact the backend publishes, and
              not from a key this component failed to find. The two are
              different claims and only one of them is checkable. */}
          {lineage.blend === null ? 'not blended — single source' : 'blended'}
        </span>
      </summary>

      <dl className="facts lineage__facts">
        <div className="facts__row">
          <dt>Import</dt>
          <dd>
            id {imported.import_id} · <code>{imported.source}</code> · season{' '}
            <code>{imported.season}</code>
          </dd>
        </div>
        <div className="facts__row">
          <dt>Imported at</dt>
          <dd>
            <code data-testid="projections-imported-at">{imported.imported_at}</code>
            {imported.original_filename ? (
              <>
                {' '}
                from <code>{imported.original_filename}</code>
              </>
            ) : (
              ' · the import recorded no filename'
            )}
          </dd>
        </div>
        <div className="facts__row">
          <dt>CSV bytes</dt>
          <dd>
            <code>{imported.content_sha256}</code>
          </dd>
        </div>
        <div className="facts__row">
          <dt>Parsing recipe</dt>
          <dd>
            <code>{imported.profile_id}</code> v{imported.profile_version} ·{' '}
            <code>{imported.profile_definition_sha256}</code>
          </dd>
        </div>
        <div className="facts__row">
          <dt>Stored rates</dt>
          <dd>
            <code data-testid="projections-values-digest">
              {imported.projection_values_sha256}
            </code>{' '}
            — moves when a rate is edited in place while the two above still look untouched
          </dd>
        </div>
        <div className="facts__row">
          <dt>Rows</dt>
          <dd data-testid="projections-row-counts">
            {imported.projection_count} verified and carried · {availableRateRowCount} rate rows
            available to this browser
          </dd>
        </div>
        <div className="facts__row">
          <dt>Import audit</dt>
          <dd data-testid="projections-audit-counts">
            {imported.row_count} data rows in the file, partitioned into {imported.matched_count}{' '}
            matched · {imported.needs_review_count} needing review · {imported.unmatched_count}{' '}
            unmatched · {imported.rejected_count} rejected before identity resolution
            {partitionTotal === imported.row_count ? null : (
              /* The backend asserts this partition on the served body, so a
                 disagreement means the served counts are not what that test
                 pins — worth saying rather than leaving a reader to add four
                 numbers and wonder. */
              <>
                {' '}
                <strong className="projections__integrity-inline">
                  Those four sum to {partitionTotal}, not {imported.row_count}.
                </strong>
              </>
            )}
          </dd>
        </div>
        <div className="facts__row">
          <dt>Scoring format</dt>
          <dd>
            {imported.assumed_scoring_type === null
              ? 'nobody stated one — deliberately not defaulted to this league’s format, because a points-league projection read as a 9-cat one is wrong in a way no downstream check can see'
              : imported.assumed_scoring_type}
          </dd>
        </div>
        <div className="facts__row">
          <dt>Blend</dt>
          <dd>
            {lineage.blend === null
              ? 'None. No blend profile, source weighting or activation pointer is persisted anywhere, so there is nothing to blend from and no “our number” to compare against yet. This is the imported cohort as published.'
              : 'A blend is present, which this build does not expect and does not render.'}
          </dd>
        </div>
        <div className="facts__row">
          <dt>How well pinned</dt>
          <dd>
            {/* The endpoint's own guarantee stops short of the whole payload,
                and a reader entitled to "guaranteed on any 200" is entitled to
                know where the list stops. */}
            The rates and this block describe the same cohort state — the backend brackets every
            read between two runs of the canonical release and refuses if they disagree. The
            player labels are checked for membership but not for their values, so a player
            renamed mid-request is served with the newer label. The games-played assumptions are
            outside that guarantee entirely: nothing digests them, so a <em>changed</em>{' '}
            assumption is not detected. Freshness is not promised by any of it.
          </dd>
        </div>
      </dl>
    </details>
  )
}
