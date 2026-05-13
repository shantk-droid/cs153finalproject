import type { Insight } from "@/components/InsightsPanel";
import type { Forecast, Recommendation, SkuTableRow, SupplierScorecard } from "@/lib/types";

/**
 * Generate heuristic actionable insights for a SKU panel.
 *
 * Pure function over the panel rows — deterministic, no LLM call.
 * Optional Phase C can add LLM enrichment of the same panel later.
 */
export function deriveForecastInsights(rows: SkuTableRow[]): Insight[] {
  if (!rows.length) return [];
  const insights: Insight[] = [];

  const orderNow = rows.filter((r) => r.status === "order_now");
  const orderNowA = orderNow.filter((r) => r.abc_class === "A");
  if (orderNow.length) {
    insights.push({
      tone: "warn",
      text:
        `${orderNow.length} SKU${orderNow.length === 1 ? "" : "s"} need ordering this week. ` +
        (orderNowA.length
          ? `Of these, ${orderNowA.length} are A-class — prioritize these first.`
          : "All are B/C-class — bundle into a weekly batch order to keep ordering costs low."),
    });
  }

  const atRisk = rows.filter((r) => r.status === "at_risk");
  if (atRisk.length) {
    const supplierCounts = new Map<string, number>();
    atRisk.forEach((r) => {
      if (!r.supplier) return;
      supplierCounts.set(r.supplier, (supplierCounts.get(r.supplier) ?? 0) + 1);
    });
    const dominant = Array.from(supplierCounts.entries()).sort((a, b) => b[1] - a[1])[0];
    insights.push({
      tone: "warn",
      text:
        `${atRisk.length} SKU${atRisk.length === 1 ? "" : "s"} at stockout risk in the next 4 weeks. ` +
        (dominant && dominant[1] >= 2
          ? `${dominant[1]} ride on ${dominant[0]} — check that supplier's lead-time variance.`
          : "Consider raising service level or shortening lead time."),
    });
  }

  const aClass = rows.filter((r) => r.abc_class === "A");
  if (aClass.length) {
    const aHealthy = aClass.filter((r) => r.status === "healthy").length;
    const aPct = (aHealthy / aClass.length) * 100;
    if (aPct >= 80) {
      insights.push({
        tone: "good",
        text:
          `A-class is ${aPct.toFixed(0)}% healthy (${aHealthy}/${aClass.length}). ` +
          "Top-revenue SKUs are well covered.",
      });
    } else if (aPct < 60) {
      insights.push({
        tone: "warn",
        text:
          `Only ${aPct.toFixed(0)}% of A-class SKUs are healthy. ` +
          "These drive most revenue — investigate the at-risk ones first.",
      });
    }
  }

  const lumpy = rows.filter((r) => r.xyz_class === "Z");
  if (lumpy.length / rows.length > 0.3) {
    const pct = (lumpy.length / rows.length) * 100;
    insights.push({
      tone: "info",
      text:
        `${pct.toFixed(0)}% of SKUs are Z-class (highly variable demand). ` +
        "Forecasts on these have wide intervals by design — consider inventory pooling or service-level targeting per class.",
    });
  }

  return insights.slice(0, 4);
}

/**
 * Compact panel summary used as context for LLM enrichment. Numeric fields only —
 * no row-level data — so the prompt stays small and cache keys are stable.
 */
export function summarizePanel(rows: SkuTableRow[]): Record<string, unknown> {
  const total = rows.length;
  const byStatus = {
    order_now: rows.filter((r) => r.status === "order_now").length,
    at_risk: rows.filter((r) => r.status === "at_risk").length,
    watch: rows.filter((r) => r.status === "watch").length,
    healthy: rows.filter((r) => r.status === "healthy").length,
  };
  const byAbc = {
    A: rows.filter((r) => r.abc_class === "A").length,
    B: rows.filter((r) => r.abc_class === "B").length,
    C: rows.filter((r) => r.abc_class === "C").length,
  };
  const byXyz = {
    X: rows.filter((r) => r.xyz_class === "X").length,
    Y: rows.filter((r) => r.xyz_class === "Y").length,
    Z: rows.filter((r) => r.xyz_class === "Z").length,
  };

  // Top categories by count, top suppliers by SKU coverage
  const catCounts = new Map<string, number>();
  const supCounts = new Map<string, number>();
  rows.forEach((r) => {
    if (r.category) catCounts.set(r.category, (catCounts.get(r.category) ?? 0) + 1);
    if (r.supplier) supCounts.set(r.supplier, (supCounts.get(r.supplier) ?? 0) + 1);
  });
  const topCats = Array.from(catCounts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([name, n]) => ({ name, n_skus: n }));
  const topSups = Array.from(supCounts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([name, n]) => ({ name, n_skus: n }));

  const totalRevenue = Math.round(rows.reduce((acc, r) => acc + (r.revenue_annual ?? 0), 0));
  const totalOnHand = Math.round(rows.reduce((acc, r) => acc + (r.on_hand ?? 0), 0));

  return {
    n_skus: total,
    by_status: byStatus,
    by_abc: byAbc,
    by_xyz: byXyz,
    top_categories: topCats,
    top_suppliers: topSups,
    total_revenue_annual: totalRevenue,
    total_on_hand_units: totalOnHand,
  };
}

export function deriveSupplierInsights(s: SupplierScorecard[]): Insight[] {
  if (!s.length) return [];
  const insights: Insight[] = [];

  const withSigma = s.filter((x) => x.lead_time_std_days != null && x.avg_lead_time_days != null);
  if (withSigma.length) {
    const top = [...withSigma].sort((a, b) => (b.lead_time_std_days ?? 0) - (a.lead_time_std_days ?? 0))[0];
    if ((top.lead_time_std_days ?? 0) > 0) {
      insights.push({
        tone: "warn",
        text:
          `Lead-time variance on ${top.name} is the highest in your panel — ${(top.lead_time_std_days ?? 0).toFixed(1)} day std on a ${(top.avg_lead_time_days ?? 0).toFixed(1)} day mean. Widen safety stock on its SKUs.`,
      });
    }
  }

  const withOtif = s.filter((x) => x.otif_pct != null && x.annual_revenue > 0);
  if (withOtif.length) {
    const lowOtif = [...withOtif].sort((a, b) => (a.otif_pct ?? 0) - (b.otif_pct ?? 0))[0];
    if ((lowOtif.otif_pct ?? 100) < 90) {
      const totalRev = s.reduce((acc, x) => acc + x.annual_revenue, 0);
      const sharePct = totalRev > 0 ? (lowOtif.annual_revenue / totalRev) * 100 : 0;
      insights.push({
        tone: "warn",
        text:
          `${lowOtif.name} has the slowest OTIF (${(lowOtif.otif_pct ?? 0).toFixed(0)}%) and ships ${sharePct.toFixed(0)}% of your annual revenue. Consider a backup or expediting clauses.`,
      });
    }
  }

  const totalRev = s.reduce((acc, x) => acc + x.annual_revenue, 0);
  if (totalRev > 0) {
    const dominant = [...s].sort((a, b) => b.annual_revenue - a.annual_revenue)[0];
    const share = (dominant.annual_revenue / totalRev) * 100;
    if (share > 35) {
      insights.push({
        tone: "info",
        text: `${dominant.name} accounts for ${share.toFixed(0)}% of revenue — single-supplier risk. Diversification or a contracted backup is worth pricing out.`,
      });
    }
  }

  return insights.slice(0, 4);
}

export function summarizeSuppliers(s: SupplierScorecard[]): Record<string, unknown> {
  return {
    n_suppliers: s.length,
    total_revenue_annual: Math.round(s.reduce((a, x) => a + x.annual_revenue, 0)),
    suppliers: s.slice(0, 12).map((x) => ({
      name: x.name,
      country: x.country,
      n_skus: x.n_skus,
      annual_revenue: Math.round(x.annual_revenue),
      avg_lead_time_days: x.avg_lead_time_days,
      lead_time_std_days: x.lead_time_std_days,
      otif_pct: x.otif_pct,
      on_time_pct: x.on_time_pct,
      in_full_pct: x.in_full_pct,
      payment_terms: x.payment_terms,
    })),
  };
}

export function deriveSkuHeuristics(
  forecast: Forecast,
  rec: Recommendation,
  history: { date: string; demand: number }[],
): Insight[] {
  const insights: Insight[] = [];
  const last7 = history.slice(-7).reduce((a, h) => a + (h.demand ?? 0), 0);
  const next7 = forecast.point.slice(0, 7).reduce((a, b) => a + b, 0);
  const stockouts = (rec.schedule ?? []).filter((e) => e.action === "stockout").length;

  if (stockouts > 0) {
    insights.push({
      tone: "warn",
      text: `${stockouts} stockout period${stockouts === 1 ? "" : "s"} projected in the schedule horizon — consider raising service level or expediting next order.`,
    });
  }
  if (next7 > last7 * 1.2) {
    insights.push({
      tone: "info",
      text: `Forecast next 7 days (${Math.round(next7)} u) is ${Math.round(((next7 - last7) / Math.max(1, last7)) * 100)}% higher than last 7 days (${Math.round(last7)} u).`,
    });
  } else if (next7 < last7 * 0.8 && last7 > 0) {
    insights.push({
      tone: "info",
      text: `Forecast next 7 days (${Math.round(next7)} u) is ${Math.round(((last7 - next7) / Math.max(1, last7)) * 100)}% lower than last 7 days (${Math.round(last7)} u).`,
    });
  }
  if (rec.expected_fill_rate < 0.95) {
    insights.push({
      tone: "warn",
      text: `Fill rate ${(rec.expected_fill_rate * 100).toFixed(1)}% is below 95% target — driven by stockout cycle risk and lead-time variance.`,
    });
  }
  return insights.slice(0, 3);
}

export function summarizeSku(
  forecast: Forecast,
  rec: Recommendation,
  history: { date: string; demand: number }[],
  meta: { sku_id: string; category: string | null; abc?: string; xyz?: string } | null,
): Record<string, unknown> {
  const last7 = history.slice(-7).reduce((a, h) => a + (h.demand ?? 0), 0);
  const last28 = history.slice(-28).reduce((a, h) => a + (h.demand ?? 0), 0);
  const next7 = forecast.point.slice(0, 7).reduce((a, b) => a + b, 0);
  const stockouts = (rec.schedule ?? []).filter((e) => e.action === "stockout").length;
  const onHand =
    (rec.parameters && (rec.parameters as Record<string, unknown>)["on_hand_now"]) ??
    null;
  return {
    sku_id: meta?.sku_id ?? rec.sku_id,
    category: meta?.category ?? null,
    abc: meta?.abc ?? rec.abc_class,
    xyz: meta?.xyz ?? rec.xyz_class,
    method: forecast.method,
    pattern: forecast.diagnostics.characterization,
    n_obs: forecast.diagnostics.n_obs,
    last_7_units: Math.round(last7),
    last_28_units: Math.round(last28),
    forecast_next_7_units: Math.round(next7),
    on_hand: onHand,
    reorder_point: rec.reorder_point,
    expected_stockout_prob: rec.expected_stockout_prob,
    expected_fill_rate: rec.expected_fill_rate,
    expected_total_cost_annual: Math.round(rec.expected_total_cost_annual),
    policy_name: rec.policy_name,
    projected_stockouts_in_horizon: stockouts,
    horizon_periods: forecast.horizon_periods,
    frequency: forecast.frequency,
    mape_backtest: forecast.diagnostics.mape_backtest,
    train_cutoff: forecast.audit?.train_cutoff_date ?? null,
  };
}
