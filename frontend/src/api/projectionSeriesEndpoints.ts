import { apiFetch, type RequestOptions, type ResponseContract } from './client'
import {
  PRODUCTION_CANDIDATE_SOURCES,
  type ProductionCandidateSource,
} from './productionCandidatesTypes'
import {
  DEFAULT_PROJECTION_SOURCE,
  type DraftProjectionSeriesCatalog,
  type ProjectionSeriesCatalog,
  type ProjectionSeriesDescriptor,
} from './projectionSeriesTypes'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  return Object.keys(value).length === expected.length &&
    expected.every((key) => Object.hasOwn(value, key))
}

function isNonblank(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

function isId(value: unknown): boolean {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

function isHash(value: unknown): boolean {
  return typeof value === 'string' && value.length === 64 && /^[0-9a-f]{64}$/.test(value)
}

export function isProjectionSource(value: unknown): value is ProductionCandidateSource {
  return (PRODUCTION_CANDIDATE_SOURCES as readonly unknown[]).includes(value)
}

export function isProjectionSeriesKey(value: unknown): value is string {
  return typeof value === 'string' && /^[a-z0-9][a-z0-9_-]{0,63}$/.exec(value)?.[0] === value
}

function hasSeriesFields(value: Record<string, unknown>): boolean {
  if (
    !isProjectionSeriesKey(value.key) ||
    !isNonblank(value.display_name) ||
    [...value.display_name].length > 128
  ) return false

  return value.key === 'legacy'
    ? value.display_name === 'Unspecified legacy series' && value.provenance === 'legacy_unspecified'
    : value.provenance === 'operator_declared'
}

export function isProjectionSeriesDescriptor(value: unknown): value is ProjectionSeriesDescriptor {
  return isRecord(value) &&
    hasExactKeys(value, ['key', 'display_name', 'provenance']) &&
    hasSeriesFields(value)
}

function isLatestImport(value: unknown): boolean {
  return isRecord(value) &&
    hasExactKeys(value, [
      'import_id', 'imported_at', 'content_sha256', 'profile_id', 'profile_version',
      'profile_definition_sha256', 'original_filename',
    ]) &&
    isId(value.import_id) &&
    typeof value.imported_at === 'string' &&
    !Number.isNaN(Date.parse(value.imported_at)) &&
    isHash(value.content_sha256) &&
    isNonblank(value.profile_id) &&
    isNonblank(value.profile_version) &&
    isHash(value.profile_definition_sha256) &&
    (value.original_filename === null || typeof value.original_filename === 'string')
}

function isEntry(value: unknown): value is ProjectionSeriesCatalog['series'][number] {
  return isRecord(value) &&
    hasExactKeys(value, ['key', 'display_name', 'provenance', 'latest_import']) &&
    hasSeriesFields(value) &&
    isLatestImport(value.latest_import)
}

const CATALOG_KEYS = [
  'league_id', 'season', 'source', 'source_display_name', 'selection_required', 'series',
] as const

function hasCatalogFields(value: Record<string, unknown>): boolean {
  return isId(value.league_id) &&
    isNonblank(value.season) &&
    isProjectionSource(value.source) &&
    (value.source_display_name === null || isNonblank(value.source_display_name)) &&
    Array.isArray(value.series) &&
    value.series.every(isEntry) &&
    // Strictly increasing ASCII keys also rule out duplicates without hiding them.
    value.series.every((entry, index, entries) =>
      index === 0 || entries[index - 1]!.key < entry.key,
    ) &&
    value.selection_required === (value.series.length > 1)
}

export function isProjectionSeriesCatalog(value: unknown): value is ProjectionSeriesCatalog {
  return isRecord(value) && hasExactKeys(value, CATALOG_KEYS) && hasCatalogFields(value)
}

export function isDraftProjectionSeriesCatalog(
  value: unknown,
): value is DraftProjectionSeriesCatalog {
  return isRecord(value) &&
    hasExactKeys(value, [...CATALOG_KEYS, 'draft_id']) &&
    isId(value.draft_id) &&
    hasCatalogFields(value)
}

export function getProjectionSeries(
  leagueId: number,
  options: RequestOptions & { source?: ProductionCandidateSource } = {},
): Promise<ProjectionSeriesCatalog> {
  const source = options.source ?? DEFAULT_PROJECTION_SOURCE
  const contract = {
    isSuccess: (value: unknown): value is ProjectionSeriesCatalog =>
      isProjectionSeriesCatalog(value) && value.league_id === leagueId && value.source === source,
    invalidResponseDetail:
      'The projection-series inventory did not match the requested league/source contract.',
  } satisfies ResponseContract<ProjectionSeriesCatalog>
  const query = new URLSearchParams({ source })
  return apiFetch(
    `/api/v1/leagues/${String(leagueId)}/projections/series?${query.toString()}`,
    contract,
    options,
  )
}

export function getDraftProjectionSeries(
  draftId: number,
  source: ProductionCandidateSource,
  options?: RequestOptions,
): Promise<DraftProjectionSeriesCatalog> {
  const contract = {
    isSuccess: (value: unknown): value is DraftProjectionSeriesCatalog =>
      isDraftProjectionSeriesCatalog(value) && value.draft_id === draftId && value.source === source,
    invalidResponseDetail:
      'The projection-series inventory did not match the requested draft/source contract.',
  } satisfies ResponseContract<DraftProjectionSeriesCatalog>
  const query = new URLSearchParams({ source })
  return apiFetch(
    `/api/v1/drafts/${String(draftId)}/projection-series?${query.toString()}`,
    contract,
    options,
  )
}
