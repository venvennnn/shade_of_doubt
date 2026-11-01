export type RuntimeInfo = {
  app: string;
  pipeline_version: string;
  consent_version: string;
  consent_text: string;
  retention_days: number;
  youcam_configured: boolean;
  pricing_configured: boolean;
  unit_cost_per_task: number | null;
  pricing_error: { code: string; message: string; remediation?: string } | null;
  concerns: string[];
  minimum_valid_variants: number;
  user_daily_unit_cap: number;
  global_daily_unit_cap: number;
  auth_configured: boolean;
  storage_backend: string | null;
  score_direction: { value: string; meaning: string; source: string; limitations: string[] };
  pipeline: Record<string, unknown>;
};

export type Validation = {
  ok: boolean;
  failed: string[];
  checks: { name: string; status: string; detail: string; heuristic: string }[];
  disclaimer: string;
  face: { x: number; y: number; width: number; height: number } | null;
};

export type AssetRecord = {
  id: string;
  kind: string;
  sha256: string;
  width: number;
  height: number;
  validation: Validation;
};

export type Product = {
  id: string;
  name: string;
  source_url: string;
  image_rights: string;
  price: string | null;
  currency: string | null;
  ingredient_label: string | null;
  source_observed_at: string;
  confirmed: boolean;
  mappings: {
    concern: string;
    support_note: string;
    source_url: string;
    reviewer_confirmed: boolean;
  }[];
};

export type Plan = {
  task_count: number;
  estimated_units: number;
  unit_cost_per_task: number;
  charge_note: string;
  tasks: { role: string; key: string; factor: string; params: Record<string, unknown> }[];
  score_only: boolean;
  minimum_valid_variants: number;
  fresh_call: string;
  tier: string;
};

export type ScoreCell = {
  concern: string;
  variant_id: string;
  variant_key: string;
  factor: string;
  delta: number | null;
  unavailable_reason: string | null;
  ui_delta: number | null;
  ui_unavailable_reason: string | null;
  raw_score: number | null;
  ui_score: number | null;
  baseline_raw_score: number | null;
  baseline_ui_score: number | null;
};

export type RankedProduct = {
  rank: number;
  product_id: string;
  name: string;
  source_url: string;
  price: string | null;
  currency: string | null;
  match: number;
  score_tie: boolean;
  contributions: { concern: string; contribution: number; support_note: string }[];
};

export type ExperimentResult = {
  id: string;
  status: string;
  stage: string;
  stage_label: string;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  counts: Record<string, number>;
  summary: {
    label: string;
    statement: string;
    note?: string;
    valid_decision_variants?: number;
    valid_score_variants?: number;
    counts?: Record<string, number>;
  };
  config: {
    concerns: string[];
    factors: string[];
    priorities: Record<string, number>;
    top_k: number;
    minimum_valid_variants: number;
    score_direction: { value: string; meaning: string; source: string };
    catalogue_product_ids: string[];
    guided: boolean;
    pipeline: Record<string, unknown>;
  };
  variants: VariantView[];
  sensitivity: {
    cells: ScoreCell[];
    ranges: { concern: string; min_delta: number | null; max_delta: number | null; max_abs_delta: number | null; observed_range: number | null; n: number; points: { variant_id: string; variant_key: string; delta: number }[] }[];
    derivatives: { concern: string; kind: string; value: number | null; unit: string; unavailable_reason: string | null; label: string; note?: string }[];
  };
  ranking: {
    formula: Record<string, unknown>;
    baseline: { eligible: boolean; reason?: string | null; ordered: RankedProduct[]; margin: number | null; top_k?: string[] } | null;
    variants: {
      variant_id: string;
      variant_key: string;
      ranking: { eligible: boolean; ordered: RankedProduct[]; margin: number | null };
      comparison: {
        comparable: boolean;
        top_one_changed?: boolean;
        top_k_overlap_count?: number;
        top_k_jaccard?: number | null;
        top_k?: number;
        displacements?: { product_id: string; baseline_rank: number | null; variant_rank: number | null; displacement: number | null }[];
        baseline_margin?: number | null;
        variant_margin?: number | null;
        reason?: string;
      };
    }[];
  };
  recaptures: {
    id: string;
    condition: string;
    note: string;
    status: string;
    asset_id: string;
    provider_task_id: string | null;
    created_at: string;
    concerns: { concern: string; recapture_delta: number | null; unavailable_reason: string | null; synthetic_max_abs_delta: number | null; synthetic_points: number[] }[];
  }[];
  limitations: string[];
};

export type VariantView = {
  id: string;
  role: string;
  key: string;
  factor: string;
  status: string;
  params: Record<string, unknown>;
  pipeline_version: string;
  colour_conversion: string;
  resize_method: string;
  encode_method: string;
  crop_bounds: Record<string, number> | null;
  clipping_fraction: number | null;
  sha256: string | null;
  width: number | null;
  height: number | null;
  asset_id: string | null;
  rejection_reason: string | null;
  unit_state: string;
  scores: Record<string, { raw_score: number | null; ui_score: number | null; raw_available: boolean; unavailable_reason: string | null; overlay_asset_id: string | null }>;
  provider: {
    provider_task_id: string | null;
    status: string;
    error_code: string | null;
    error_message: string | null;
    poll_count: number;
    schema_version: string | null;
    submitted_at: string | null;
    completed_at: string | null;
    metadata: Record<string, unknown> | null;
  } | null;
};

export const VARIANT_LABELS: Record<string, string> = {
  baseline: "Original",
  exposure_low: "Lower exposure",
  exposure_high: "Higher exposure",
  colour_warm: "Warmer gain",
  colour_cool: "Cooler gain",
  framing_left: "Frame left",
  framing_right: "Frame right",
};

export function variantLabel(key: string) {
  return VARIANT_LABELS[key] || key;
}
