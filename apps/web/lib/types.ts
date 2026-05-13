// Shared TypeScript types — mirrored from apps/api/ingestion/schemas.py + assertions/schemas.py.
// In v2 we'll generate these from the FastAPI OpenAPI schema. For Day 2, hand-typed.

export const CANONICAL_FIELDS = [
  "sku_id",
  "date",
  "demand",
  "on_hand",
  "lead_time_days",
  "unit_cost",
  "unit_price",
  "supplier",
  "category",
] as const;

export type CanonicalField = (typeof CANONICAL_FIELDS)[number];

export const REQUIRED_FIELDS = ["sku_id", "date", "demand"] as const satisfies readonly CanonicalField[];

export const FIELD_LABEL: Record<CanonicalField, string> = {
  sku_id: "SKU ID",
  date: "Date",
  demand: "Demand / Sales",
  on_hand: "On Hand",
  lead_time_days: "Lead Time (days)",
  unit_cost: "Unit Cost",
  unit_price: "Unit Price",
  supplier: "Supplier",
  category: "Category",
};

export type DType = "string" | "integer" | "float" | "date" | "boolean" | "unknown";

export interface ColumnDetection {
  name: string;
  dtype: DType;
  null_pct: number;
  unique_pct: number;
  sample_values: string[];
}

export interface SuggestedMappingItem {
  canonical: CanonicalField;
  file_column: string | null;
  confidence: number;
}

export interface DatasetPreview {
  dataset_id: string;
  filename: string;
  n_total_rows: number;
  detected_columns: ColumnDetection[];
  suggested_mapping: SuggestedMappingItem[];
  sample_rows: Record<string, unknown>[];
  sheet_names: string[] | null;
  selected_sheet: string | null;
  detected_connector: "shopify" | null;
}

export type ColumnMapping = Partial<Record<CanonicalField, string>> & {
  sku_id: string;
  date: string;
  demand: string;
};

export interface DatasetSummary {
  dataset_id: string;
  n_rows: number;
  n_skus: number;
  date_min: string;
  date_max: string;
  frequency: "D" | "W" | "M" | null;
  n_categories: number;
  n_suppliers: number;
  has_on_hand: boolean;
  has_lead_time: boolean;
  has_unit_cost: boolean;
  has_unit_price: boolean;
}

export type Severity = "hard" | "soft" | "info";

export interface Assertion {
  code: string;
  severity: Severity;
  field: string | null;
  message: string;
  offending_examples: Record<string, unknown>[];
  offending_row_count: number;
  skus_affected: number | null;
}

export type ComponentName =
  | "completeness"
  | "plausibility"
  | "distribution_profile"
  | "history_depth"
  | "stationarity";

export interface ComponentScore {
  name: ComponentName;
  score: number | null;
  weight: number;
  notes: string[];
}

export interface ProfileInfo {
  profile_id: string;
  label: string;
  auto_detected: boolean;
  match_confidence: number | null;
}

export interface DataQualityReport {
  dataset_id: string;
  composite_score: number | null;
  components: ComponentScore[];
  assertions: Assertion[];
  n_rows: number;
  n_skus: number;
  skus_low_history: string[];
  skus_with_business_logic_issues: string[];
  profile?: ProfileInfo | null;
  flagged_metrics?: Record<string, number>;
}

export interface ProfileListEntry {
  id: string;
  label: string;
  description: string;
  version: string;
}

export interface DatasetMetadata {
  dataset_id: string;
  profile_id: string;
  profile_auto_detected: boolean;
  match_confidence: number | null;
  created_at: string;
}

// --- Day 4 inventory + Day 3 forecasting types ---

export type AbcClass = "A" | "B" | "C";
export type XyzClass = "X" | "Y" | "Z";
export type SkuStatus = "order_now" | "at_risk" | "watch" | "healthy";

export interface SkuTableRow {
  sku_id: string;
  category: string | null;
  supplier: string | null;
  abc_class: AbcClass;
  xyz_class: XyzClass;
  last_demand: number;
  on_hand: number | null;
  days_of_cover: number | null;
  cv_demand: number;
  revenue_annual: number;
  n_obs: number;
  history?: number[] | null;
  lead_time_days?: number | null;
  status: SkuStatus;
}

export interface AggregateStats {
  dataset_id: string;
  n_skus: number;
  total_revenue_annual: number;
  total_inventory_value: number | null;
  avg_days_of_cover: number | null;
  pct_stockout_risk_high: number | null;
  abc_counts: Record<AbcClass, number>;
  xyz_counts: Record<XyzClass, number>;
  abc_xyz_heatmap: Record<string, number>;
  n_skus_low_history: number;
}

export type ForecastMethod =
  | "ets" | "arima" | "seasonal_naive" | "croston" | "tsb"
  | "ml_lgb" | "chronos_bolt" | "ensemble" | "negbin_bayes";

export type Pattern = "smooth" | "seasonal" | "intermittent" | "lumpy" | "trending_new" | "promo_driven";

export interface ForecastDiagnostics {
  n_obs: number;
  characterization: Pattern;
  mape_backtest: number | null;
  smape_backtest: number | null;
  mase_backtest: number | null;
  crps_backtest: number | null;
  bias_backtest: number | null;
  pinball_q95_backtest: number | null;
  n_backtest_folds: number;
  prior_weight: number;
}

export interface ConformalCoverage {
  horizon: number;
  nominal: number;
  empirical: number | null;
  n_residuals: number;
}

export interface ForecastAudit {
  forecast_generated_at: string;
  train_cutoff_date: string | null;
  ensemble_weights: Record<string, number>;
  ensemble_method_version: string;
}

export interface Forecast {
  sku_id: string;
  method: ForecastMethod;
  horizon_periods: number;
  frequency: "D" | "W" | "M";
  point: number[];
  quantiles: Record<string, number[]>;
  distribution_params: Record<string, unknown> | null;
  diagnostics: ForecastDiagnostics;
  caveats: string[];
  forecast_dates: string[];
  conformal_coverage?: ConformalCoverage[];
  audit?: ForecastAudit | null;
}

export interface ScenarioResponse {
  base: Recommendation;
  scenario: Recommendation;
  deltas: Record<string, number>;
}

// --- LLM-enriched insights ---

export type InsightTone = "info" | "warn" | "good";

export interface LlmInsight {
  tone: InsightTone;
  text: string;
  source: "heuristic" | "llm";
}

export interface SkuNarrative {
  paragraph: string;
  bullets: LlmInsight[];
  source: "heuristic" | "llm";
}

export type PolicyName = "EOQ" | "(Q,R)" | "(s,S)" | "newsvendor" | "base-stock";

export interface ScheduleEntry {
  period_idx: number;
  date: string;
  action: "order" | "no_op" | "delivery" | "stockout";
  qty: number;
  expected_on_hand_after_demand: number;
  expected_on_hand_after_delivery: number;
  expected_arrival: string | null;
  reason: string | null;
}

export interface Recommendation {
  sku_id: string;
  policy_name: PolicyName;
  parameters: Record<string, number | string>;
  recommended_order_qty: number;
  reorder_point: number | null;
  safety_stock: number;
  expected_stockout_prob: number;
  expected_fill_rate: number;
  expected_holding_cost_annual: number;
  expected_total_cost_annual: number;
  abc_class: AbcClass;
  xyz_class: XyzClass;
  schedule: ScheduleEntry[] | null;
  joint_replen_group: string | null;
  caveats: string[];
}

export interface RecommendationOverrides {
  service_level?: number;
  holding_cost_rate?: number;
  order_cost?: number;
  lead_time_days_override?: number;
  horizon_periods?: number;
  policy_override?: PolicyName;
}

// --- Phase 2 reorder + supplier types ---

export type POStatus = "drafted" | "approved" | "placed" | "received" | "cancelled";

export interface ReorderQueueItem {
  sku_id: string;
  category: string | null;
  supplier_name: string | null;
  supplier_id: string | null;
  on_hand: number | null;
  reorder_point: number | null;
  recommended_qty: number;
  recommended_qty_raw: number;
  unit_cost: number | null;
  total_cost: number;
  projected_stockout_date: string | null;
  days_of_cover: number | null;
  stockout_prob: number;
  revenue_at_risk: number;
  score: number;
  expedite_flag: boolean;
  expedite_breakeven: number | null;
  joint_replen_group: string | null;
  moq: number | null;
  case_pack: number | null;
  abc_class: AbcClass;
  xyz_class: XyzClass;
}

export interface POLine {
  po_id: string;
  sku_id: string;
  qty: number;
  unit_cost: number | null;
}

export interface POStatusLogEntry {
  from_status: POStatus | null;
  to_status: POStatus;
  by_user: string | null;
  at: string;
  note: string | null;
}

export interface PurchaseOrder {
  po_id: string;
  supplier_id: string | null;
  supplier_name: string | null;
  status: POStatus;
  created_at: string;
  needed_by: string | null;
  total_cost: number;
  total_units: number;
  expedite_flag: boolean;
  joint_replen_group: string | null;
  assigned_to: string | null;
  approved_by: string | null;
  notes: string | null;
  lines: POLine[];
  status_log: POStatusLogEntry[];
}

export interface SupplierScorecard {
  supplier_id: string;
  name: string;
  n_skus: number;
  annual_revenue: number;
  avg_lead_time_days: number | null;
  lead_time_std_days: number | null;
  leadtime_posterior_mean: number | null;
  leadtime_posterior_std: number | null;
  on_time_pct: number | null;
  in_full_pct: number | null;
  otif_pct: number | null;
  n_receipts: number;
  payment_terms: string | null;
  moq: number | null;
  case_pack: number | null;
  country: string | null;
  contact_email: string | null;
}

export interface ReceiptRow {
  receipt_id: string;
  sku_id: string;
  ordered_date: string;
  expected_date: string;
  received_date: string;
  ordered_qty: number;
  received_qty: number;
}

export interface SupplierDetail {
  supplier_id: string;
  name: string;
  contact_email: string | null;
  country: string | null;
  payment_terms: string | null;
  default_lead_time_days: number | null;
  lead_time_std_days: number | null;
  moq: number | null;
  case_pack: number | null;
  notes: string | null;
  n_skus: number;
  leadtime_posterior_mean: number | null;
  leadtime_posterior_std: number | null;
  actual_lead_times: number[];
  receipts: ReceiptRow[];
}

export interface FrontierPoint {
  service_level: number;
  recommended_order_qty: number;
  reorder_point: number | null;
  safety_stock: number;
  expected_fill_rate: number;
  expected_holding_cost_annual: number;
  expected_total_cost_annual: number;
  inventory_value: number;
}

export interface FrontierResult {
  sku_id: string;
  policy_name: PolicyName;
  unit_cost: number;
  unit_price: number;
  baseline_service_level: number;
  points: FrontierPoint[];
  newsvendor: {
    optimal_qty: number;
    critical_ratio: number;
    underage_cost: number;
    overage_cost: number;
  } | null;
}

export interface StressTestRequest {
  lead_time_multiplier: number;
  demand_multiplier: number;
  service_level: number | null;
  n_simulations: number | null;
}

export interface StressTestImpactedSku {
  sku_id: string;
  baseline_stockout_prob: number;
  shock_stockout_prob: number;
  baseline_revenue_at_risk: number;
  shock_revenue_at_risk: number;
  delta_revenue_at_risk: number;
  baseline_recommended_qty: number;
  shock_recommended_qty: number;
}

export interface StressTestResult {
  baseline_total_revenue_at_risk: number;
  shock_total_revenue_at_risk: number;
  delta_total_revenue_at_risk: number;
  baseline_n_at_risk: number;
  shock_n_at_risk: number;
  var_95: number;
  cvar_95: number;
  top_impacted: StressTestImpactedSku[];
}

export interface WorkingCapital {
  inventory_value: number;
  annual_cogs: number;
  dio_days: number | null;
  dpo_days: number | null;
  cash_to_cash_days: number | null;
  payable_outstanding: number;
  by_supplier: Array<{
    supplier_id: string;
    supplier_name: string;
    inventory_value: number;
    payment_terms_days: number;
    payable_outstanding: number;
  }>;
}

export interface ABCMigration {
  sku_id: string;
  from_abc: AbcClass;
  to_abc: AbcClass;
  from_xyz: XyzClass;
  to_xyz: XyzClass;
}

export interface ModelLeaderboardEntry {
  method: ForecastMethod | string;
  available: boolean;
  selected: boolean;
  mape: number | null;
  smape: number | null;
  mase: number | null;
  crps: number | null;
  notes: string | null;
}

export interface ForecastDecomposition {
  dates: string[];
  observed: number[];
  trend: number[];
  seasonal: number[];
  residual: number[];
  calendar_lift: number[] | null;
  seasonal_period: number;
}

// --- Agentic features ---

export interface AnomalyEvent {
  date: string;
  value: number;
  direction: "spike" | "drop";
  magnitude_z: number;
  cusum_score: number;
  baseline_mean: number;
  baseline_std: number;
  severity: "info" | "warn" | "crit";
}

export interface AgentToolCallRecord {
  name: string;
  arguments: Record<string, unknown>;
  result: unknown;
  duration_ms: number;
  error: string | null;
}

export interface AnomalyExplainResponse {
  sku_id: string;
  detected: AnomalyEvent[];
  explanation: string;
  chart_spec: Record<string, unknown>;
  tool_calls: AgentToolCallRecord[];
  fallback: boolean;
  error: string | null;
}

export interface AutoPlanLine {
  sku_id: string;
  qty: number;
  unit_cost: number | null;
  rationale: string;
}

export interface AutoPlanDraft {
  supplier_id: string | null;
  supplier_name: string;
  lines: AutoPlanLine[];
  expedite: boolean;
  joint_replen_group: string | null;
  rationale: string;
  total_cost: number;
}

export interface AutoPlanResponse {
  summary: string;
  draft_pos: AutoPlanDraft[];
  fallback: boolean;
  error: string | null;
  dropped_lines?: string[];
  tool_calls?: AgentToolCallRecord[];
}

export interface AutoPlanAcceptResponse {
  created_po_ids: string[];
  errors: Array<{ supplier_name: string | null; error: string }>;
}
