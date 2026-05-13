import type { Recommendation, SkuStatus } from "@/lib/types";

/**
 * Derive a triage status from a Recommendation, used on the SKU detail page.
 *
 * The forecasts list endpoint already returns `SkuTableRow.status` (computed by the
 * lightweight days-of-cover heuristic). This helper covers the SKU detail case where
 * we have a full Recommendation but no row, deriving the same enum off policy fields.
 */
export function derivePresentationStatus(rec: Recommendation): SkuStatus {
  const onHand = (rec.parameters && (rec.parameters as Record<string, unknown>)["on_hand_now"]) as
    | number
    | undefined;
  const reorder = rec.reorder_point;
  const stockoutProb = rec.expected_stockout_prob;
  const fillRate = rec.expected_fill_rate;

  if (typeof onHand === "number" && onHand <= 0) return "order_now";
  if (reorder != null && typeof onHand === "number" && onHand <= reorder) return "order_now";
  if (stockoutProb >= 0.10) return "at_risk";
  if (fillRate < 0.95) return "watch";
  return "healthy";
}
