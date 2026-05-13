import type {
  AggregateStats,
  ColumnMapping,
  DataQualityReport,
  DatasetMetadata,
  DatasetPreview,
  DatasetSummary,
  Forecast,
  ForecastDecomposition,
  LlmInsight,
  ProfileListEntry,
  Recommendation,
  RecommendationOverrides,
  ScenarioResponse,
  SkuNarrative,
  SkuStatus,
  SkuTableRow,
} from "@/lib/types";

export interface HeuristicInsightInput {
  tone: string;
  text: string;
}

const BASE = "/api";

async function jsonOr<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail: unknown = await r.text();
    try {
      detail = JSON.parse(detail as string);
    } catch {
      // not JSON, leave as text
    }
    const err = new Error(`API ${r.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`) as Error & {
      status?: number;
      detail?: unknown;
    };
    err.status = r.status;
    err.detail = detail;
    throw err;
  }
  return r.json();
}

export async function uploadDataset(file: File, sheetOverride?: string): Promise<DatasetPreview> {
  const fd = new FormData();
  fd.append("file", file);
  if (sheetOverride) fd.append("sheet_override", sheetOverride);
  const r = await fetch(`${BASE}/datasets/upload`, { method: "POST", body: fd });
  return jsonOr<DatasetPreview>(r);
}

export async function confirmDataset(
  datasetId: string,
  mapping: ColumnMapping,
  profileId: string = "auto",
): Promise<DatasetSummary> {
  const params = new URLSearchParams();
  params.set("profile_id", profileId);
  const r = await fetch(`${BASE}/datasets/${datasetId}/confirm?${params}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(mapping),
  });
  return jsonOr<DatasetSummary>(r);
}

export async function listProfiles(): Promise<{ profiles: ProfileListEntry[] }> {
  const r = await fetch(`${BASE}/datasets/profiles`);
  return jsonOr<{ profiles: ProfileListEntry[] }>(r);
}

export async function getDatasetMetadata(datasetId: string): Promise<DatasetMetadata> {
  const r = await fetch(`${BASE}/datasets/${datasetId}/metadata`);
  return jsonOr<DatasetMetadata>(r);
}

export async function patchDatasetMetadata(
  datasetId: string,
  profileId: string,
): Promise<DatasetMetadata> {
  const r = await fetch(`${BASE}/datasets/${datasetId}/metadata`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ profile_id: profileId }),
  });
  return jsonOr<DatasetMetadata>(r);
}

export async function fetchQualityReport(datasetId: string): Promise<DataQualityReport> {
  const r = await fetch(`${BASE}/datasets/${datasetId}/quality`);
  return jsonOr<DataQualityReport>(r);
}

export async function fetchDatasetSummary(datasetId: string): Promise<DatasetSummary> {
  const r = await fetch(`${BASE}/datasets/${datasetId}`);
  return jsonOr<DatasetSummary>(r);
}

export interface SkuListQuery {
  limit?: number;
  offset?: number;
  category?: string;
  supplier?: string;
  abc?: "A" | "B" | "C";
  xyz?: "X" | "Y" | "Z";
  status?: SkuStatus;
  sort_by?: "sku_id" | "revenue_annual" | "cv_demand" | "last_demand" | "days_of_cover" | "status";
  sort_dir?: "asc" | "desc";
  include_history?: boolean;
  history_periods?: number;
}

export async function listSkus(datasetId: string, q: SkuListQuery = {}): Promise<SkuTableRow[]> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v !== undefined && v !== null) params.set(k, String(v));
  }
  const r = await fetch(`${BASE}/datasets/${datasetId}/skus?${params}`);
  return jsonOr<SkuTableRow[]>(r);
}

export async function fetchAggregateStats(datasetId: string): Promise<AggregateStats> {
  const r = await fetch(`${BASE}/datasets/${datasetId}/aggregate_stats`);
  return jsonOr<AggregateStats>(r);
}

export async function fetchForecast(datasetId: string, skuId: string, horizon = 12): Promise<Forecast> {
  const r = await fetch(
    `${BASE}/datasets/${datasetId}/skus/${encodeURIComponent(skuId)}/forecast?horizon=${horizon}`,
    { method: "POST" },
  );
  return jsonOr<Forecast>(r);
}

export async function fetchRecommendation(
  datasetId: string,
  skuId: string,
  overrides: RecommendationOverrides = {},
): Promise<Recommendation> {
  const r = await fetch(
    `${BASE}/datasets/${datasetId}/skus/${encodeURIComponent(skuId)}/recommend`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(overrides),
    },
  );
  return jsonOr<Recommendation>(r);
}

export async function runScenario(
  datasetId: string,
  skuId: string,
  overrides: RecommendationOverrides,
): Promise<ScenarioResponse> {
  const r = await fetch(
    `${BASE}/datasets/${datasetId}/skus/${encodeURIComponent(skuId)}/scenario`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(overrides),
    },
  );
  return jsonOr<ScenarioResponse>(r);
}

export async function fetchDecomposition(
  datasetId: string,
  skuId: string,
  signal?: AbortSignal,
): Promise<ForecastDecomposition> {
  const r = await fetch(
    `${BASE}/datasets/${datasetId}/skus/${encodeURIComponent(skuId)}/decompose`,
    { method: "POST", signal },
  );
  return jsonOr<ForecastDecomposition>(r);
}

export async function fetchPanelInsights(
  datasetId: string,
  summary: Record<string, unknown>,
  heuristics: HeuristicInsightInput[],
  signal?: AbortSignal,
): Promise<{ insights: LlmInsight[] }> {
  const r = await fetch(`${BASE}/datasets/${datasetId}/insights/panel`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ summary, heuristics }),
    signal,
  });
  return jsonOr<{ insights: LlmInsight[] }>(r);
}

export async function fetchSupplierInsights(
  datasetId: string,
  summary: Record<string, unknown>,
  heuristics: HeuristicInsightInput[],
  signal?: AbortSignal,
): Promise<{ insights: LlmInsight[] }> {
  const r = await fetch(`${BASE}/datasets/${datasetId}/insights/suppliers`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ summary, heuristics }),
    signal,
  });
  return jsonOr<{ insights: LlmInsight[] }>(r);
}

export async function fetchSkuNarrative(
  datasetId: string,
  skuId: string,
  sku: Record<string, unknown>,
  heuristics: HeuristicInsightInput[],
  signal?: AbortSignal,
): Promise<{ narrative: SkuNarrative | null }> {
  const r = await fetch(
    `${BASE}/datasets/${datasetId}/skus/${encodeURIComponent(skuId)}/insights`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ sku, heuristics }),
      signal,
    },
  );
  return jsonOr<{ narrative: SkuNarrative | null }>(r);
}

export function downloadCsv(filename: string, rows: Record<string, unknown>[]): void {
  if (rows.length === 0) return;
  const headers = Object.keys(rows[0]);
  const escape = (v: unknown): string => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [
    headers.join(","),
    ...rows.map((r) => headers.map((h) => escape(r[h])).join(",")),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
