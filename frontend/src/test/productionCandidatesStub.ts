/**
 * Explicitly synthetic production-candidate payloads for focused client and
 * race tests.
 *
 * This is not captured from HTTP and must never be renamed or described as a
 * recorded fixture. The recorded fixture is copied only from the backend's
 * seeded HTTP export.
 */

import type {
  ProductionCandidate,
  ProductionCandidateSource,
  ProductionCandidatesResponse,
  ProductionCategoryComponent,
  ProductionCategoryDirection,
  ProductionCategoryKey,
  ProductionCategoryKind,
  ProductionCategoryScale,
  ProductionRateField,
} from '../api/productionCandidatesTypes'
import { PROJECTION_RELEASE_SCHEMA_VERSION } from '../api/projectionSeriesTypes'
import { syntheticSeriesDescriptor } from './projectionSeriesStub'

export const SYNTHETIC_CATEGORY_ORDER: readonly ProductionCategoryKey[] = [
  'to',
  'pts',
  'fg_pct',
  'reb',
  'ast',
  'stl',
  'blk',
  'fg3m',
  'ft_pct',
]

const SEMANTICS: Record<
  ProductionCategoryKey,
  {
    kind: ProductionCategoryKind
    direction: ProductionCategoryDirection
    fields: readonly ProductionRateField[]
  }
> = {
  pts: { kind: 'counting', direction: 1, fields: ['points_per_game'] },
  reb: { kind: 'counting', direction: 1, fields: ['rebounds_per_game'] },
  ast: { kind: 'counting', direction: 1, fields: ['assists_per_game'] },
  stl: { kind: 'counting', direction: 1, fields: ['steals_per_game'] },
  blk: { kind: 'counting', direction: 1, fields: ['blocks_per_game'] },
  fg3m: {
    kind: 'counting',
    direction: 1,
    fields: ['three_pointers_made_per_game'],
  },
  to: { kind: 'counting', direction: -1, fields: ['turnovers_per_game'] },
  fg_pct: {
    kind: 'ratio',
    direction: 1,
    fields: ['field_goals_made_per_game', 'field_goals_attempted_per_game'],
  },
  ft_pct: {
    kind: 'ratio',
    direction: 1,
    fields: ['free_throws_made_per_game', 'free_throws_attempted_per_game'],
  },
}

function hash(character: string): string {
  return character.repeat(64)
}

function scales(): ProductionCategoryScale[] {
  return SYNTHETIC_CATEGORY_ORDER.map((categoryKey, index) => {
    const semantics = SEMANTICS[categoryKey]
    return {
      category_key: categoryKey,
      kind: semantics.kind,
      direction: semantics.direction,
      production_fields: [...semantics.fields],
      reference_mean: index + 0.25,
      population_sd: index + 1,
      reference_percentage:
        categoryKey === 'fg_pct' ? 0.475 : categoryKey === 'ft_pct' ? 0.79 : null,
      status: 'defined',
    }
  })
}

function components(
  productionOffset: number,
  scoreOffset: number,
): ProductionCategoryComponent[] {
  return SYNTHETIC_CATEGORY_ORDER.map((categoryKey, index) => {
    const semantics = SEMANTICS[categoryKey]
    return {
      category_key: categoryKey,
      kind: semantics.kind,
      direction: semantics.direction,
      production_fields: Object.fromEntries(
        semantics.fields.map((field, fieldIndex) => [
          field,
          productionOffset + index + fieldIndex + 0.5,
        ]),
      ),
      transformed_value: scoreOffset + index / 10,
      z_score: scoreOffset + index / 100,
    }
  })
}

function candidate({
  playerId,
  ordinal,
  fullName,
  totalZ,
  observed,
  hashCharacter,
}: {
  playerId: number
  ordinal: number
  fullName: string
  totalZ: number
  observed: boolean
  hashCharacter: string
}): ProductionCandidate {
  return {
    player_id: playerId,
    full_name: fullName,
    team_abbreviation: playerId === 101 ? 'BOS' : null,
    projection_content_sha256: hash(hashCharacter),
    ordinal,
    rates_per_game: {
      points_per_game: 24.5,
      rebounds_per_game: 7.25,
      assists_per_game: 6.5,
      steals_per_game: 1.25,
      blocks_per_game: 0.75,
      turnovers_per_game: 2.5,
      three_pointers_made_per_game: 2.75,
      field_goals_made_per_game: 8.5,
      field_goals_attempted_per_game: 17.25,
      free_throws_made_per_game: 4.75,
      free_throws_attempted_per_game: 5.5,
    },
    components:
      playerId === 101
        ? components(1, 1)
        : components(2, -1),
    total_z: totalZ,
    value_above_replacement: null,
    health: observed
      ? { status: 'observed', credited_appearances: 3 }
      : { status: 'no_observations', credited_appearances: 0 },
  }
}

export function syntheticProductionCandidates({
  draftId = 2,
  source = 'basketball_monster',
  seriesKey = 'legacy',
}: {
  draftId?: number
  source?: ProductionCandidateSource
  seriesKey?: string
} = {}): ProductionCandidatesResponse {
  const categoryScales = scales()
  return {
    draft_id: draftId,
    league_id: 2,
    season: '2026-27',
    source,
    source_display_name: `Synthetic ${source} contract stub`,
    series: syntheticSeriesDescriptor(seriesKey),
    source_original_filename: 'synthetic-production-candidates.csv',
    draft_status: 'in_progress',
    draft_last_sequence: 7,
    generated_at: '2026-09-14T02:30:00Z',
    claim: 'projection_relative_production_ranking',
    value_scope: 'production_only',
    availability_included: false,
    calibration_status: 'not_established_for_current_selected_source',
    source_freshness: 'not_established_beyond_current_import',
    limitations: {
      strategy_included: false,
      punt_adjustment_included: false,
      budget_or_affordability_included: false,
      position_fit_included: false,
      fantrax_roster_eligibility_included: false,
      partial_browser_increment: true,
    },
    lineage: {
      projection_import: {
        import_id: 11,
        source,
        series_key: seriesKey,
        release_schema_version: PROJECTION_RELEASE_SCHEMA_VERSION,
        season: '2026-27',
        imported_at: '2026-09-13T18:00:00Z',
        content_sha256: hash('a'),
        profile_id: 'synthetic-test-profile',
        profile_version: '1',
        profile_definition_sha256: hash('b'),
        projection_values_sha256: hash('c'),
        projection_count: 3,
        assumed_scoring_type: 'h2h_each_category',
      },
      scoring_profile: {
        id: 4,
        version: 2,
        name: 'Synthetic 9-cat profile',
        scoring_type: 'h2h_each_category',
        settings_snapshot_id: 9,
        content_sha256: hash('d'),
      },
      blend: {
        mode: 'ephemeral_identity_single_source',
        persisted: false,
        profile_id: 'synthetic-identity-blend',
        version: 1,
        content_sha256: hash('e'),
        result_content_sha256: hash('f'),
        weight_basis: 'user_configured',
        manual_override_count: 0,
        category_weights: categoryScales.map((scale) => ({
          category_key: scale.category_key,
          source,
          raw_weight: 1,
          normalized_weight: 1,
        })),
      },
      score: {
        model_version: 'zscore-production-v1',
        input_kind: 'production_blend',
        output_layer: 'terminal',
        aggregation_policy: 'equal_weight_sum_of_nine_directed_components_v1',
        reference_policy: 'all_complete_supplied_players_v1',
        replacement_policy: 'explicit_structure_ordinal_n_plus_one_v1',
        scoring_profile_sha256: hash('d'),
        blend_profile_sha256: hash('e'),
        blend_result_sha256: hash('f'),
        content_sha256: hash('1'),
      },
      availability_model_version: null,
      punt_config: null,
    },
    reference: {
      count: 3,
      player_ids: [101, 102, 103],
      players_sha256: hash('2'),
      scored_before_draft_exclusion: true,
      draft_exclusion_policy:
        'exclude_resolved_holdings_after_full_reference_scoring',
      resolved_drafted_player_ids: [102],
      excluded_drafted_player_ids: [102],
      drafted_player_ids_outside_reference: [],
      candidate_count: 2,
    },
    replacement: {
      state: 'unavailable_insufficient_projected_pool',
      team_count: 12,
      roster_size: 13,
      structural_roster_count: 156,
      replacement_ordinal: 157,
      projected_count: 3,
      structural_roster_covered: false,
      structural_roster_shortfall: 153,
      replacement_ordinal_shortfall: 154,
      replacement_player_id: null,
      replacement_total_z: null,
    },
    category_scales: categoryScales,
    health_context: {
      status: 'available',
      reason: null,
      season: '2025-26',
      season_type: 'regular',
      window_start: '2025-10-21',
      as_of_date: '2026-04-12',
      publication: {
        refresh_id: 8,
        artifact_key: 'reliability-observations',
        source: null,
        source_version: null,
      },
      row_source_provenance: 'not_recorded',
      counting_rule: 'player_game_log_rows_in_window_including_zero_seconds',
      observation_rows_sha256: hash('3'),
      ranking_input: false,
    },
    candidates: [
      candidate({
        playerId: 101,
        ordinal: 1,
        fullName: 'Zulu Player',
        totalZ: 4.5,
        observed: true,
        hashCharacter: '4',
      }),
      candidate({
        playerId: 103,
        ordinal: 3,
        fullName: 'Alpha Player',
        totalZ: -1.5,
        observed: false,
        hashCharacter: '5',
      }),
    ],
  }
}
