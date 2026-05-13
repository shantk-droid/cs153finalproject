export interface MethodologyEntry {
  title: string;
  formula: string;
  inputs: string[];
  assumptions: string[];
  references?: string[];
}

export const METHODOLOGY: Record<string, MethodologyEntry> = {
  service_level: {
    title: "Service level (cycle service level)",
    formula: "α = P(demand during lead time ≤ inventory position at order)",
    inputs: [
      "Demand distribution (mean μ_D, std σ_D)",
      "Lead time distribution (mean μ_L, std σ_L)",
      "Reorder point R = μ_LTD + z_α × σ_LTD where z_α = Φ⁻¹(α)",
    ],
    assumptions: [
      "Lead-time demand is approximately normal (LTD = ∑_t demand_t over L periods)",
      "Demand and lead time are independent",
    ],
  },
  reorder_point: {
    title: "Reorder point (ROP)",
    formula: "R = μ_LTD + z_α × σ_LTD",
    inputs: [
      "Mean lead-time demand μ_LTD = μ_L × μ_D",
      "Lead-time demand std σ_LTD = √(μ_L × σ_D² + μ_D² × σ_L²) (Hadley & Whitin)",
      "z_α = Φ⁻¹(service level)",
    ],
    assumptions: [
      "Continuous review (place order the moment inventory drops to R)",
      "Independent demand and lead time",
    ],
  },
  safety_stock: {
    title: "Safety stock",
    formula: "SS = z_α × σ_LTD",
    inputs: [
      "Service level → z_α via inverse normal CDF",
      "Lead-time demand std σ_LTD",
    ],
    assumptions: [
      "Higher service level → more safety stock; tradeoff is holding cost vs stockout cost.",
    ],
  },
  eoq: {
    title: "Economic Order Quantity (EOQ)",
    formula: "Q* = √(2 × D × S / H)",
    inputs: [
      "D = annual demand",
      "S = ordering cost per order",
      "H = holding cost per unit per year",
    ],
    assumptions: [
      "Constant demand, instantaneous replenishment, no quantity discounts.",
      "EOQ is the deterministic floor; (Q,R) and (s,S) handle stochastic demand.",
    ],
  },
  newsvendor: {
    title: "Newsvendor (single-period)",
    formula: "Q* = F⁻¹(Cu / (Cu + Co))",
    inputs: [
      "Cu = underage cost (lost margin) = price − cost",
      "Co = overage cost (holding/disposal) = cost − salvage",
      "F⁻¹ = inverse demand CDF",
    ],
    assumptions: [
      "Single-period, no carryover. Used for perishables and one-shot orders.",
    ],
  },
  fill_rate: {
    title: "Fill rate (β)",
    formula: "β = 1 − E[unsatisfied demand per cycle] / E[demand per cycle]",
    inputs: [
      "LTD samples → unsatisfied = max(0, LTD − inventory_at_order)",
      "Cycle demand = D × T_cycle",
    ],
    assumptions: [
      "Cycle service level (α) ≠ fill rate (β). β is usually higher than α.",
    ],
  },
  cv: {
    title: "Coefficient of Variation (CV)",
    formula: "CV = σ / μ",
    inputs: ["Demand mean μ", "Demand std σ"],
    assumptions: [
      "CV > 0.5 → \"Z\" class (high volatility), 0.25–0.5 → \"Y\", < 0.25 → \"X\".",
    ],
  },
  days_of_cover: {
    title: "Days of cover",
    formula: "DoC = on_hand / mean_demand_per_day",
    inputs: ["Current on-hand inventory", "Recent average daily demand"],
    assumptions: [
      "Used as quick proxy for stockout risk; doesn't account for in-transit POs.",
    ],
  },
  cash_to_cash: {
    title: "Cash-to-cash cycle",
    formula: "C2C = DIO + DSO − DPO",
    inputs: [
      "DIO = inventory $ / annual COGS × 365",
      "DSO = receivables / revenue × 365",
      "DPO = payables / purchases × 365 (here: weighted avg of supplier payment terms)",
    ],
    assumptions: [
      "DSO = 0 in this view (no AR data). Real DSO would be added if AR ingested.",
      "Lower C2C = better liquidity. Negative C2C means suppliers finance your inventory.",
    ],
  },
  otif: {
    title: "OTIF (On-Time, In-Full)",
    formula: "OTIF = P(received_date ≤ expected_date AND received_qty ≥ ordered_qty × 0.99)",
    inputs: ["Receipt history per supplier"],
    assumptions: [
      "0.99× threshold for in-full to allow tiny shrinkage tolerance.",
      "<75% OTIF → flagged in insights tile.",
    ],
  },
  expedite: {
    title: "Expediting breakeven",
    formula: "Expedite if stockout_cost > air_freight_cost",
    inputs: [
      "Stockout cost = stockout_prob × demand × unit_price × lead_time",
      "Air freight estimate ≈ 0.5 × unit_cost (configurable)",
    ],
    assumptions: [
      "Conservative: only flag when stockout_prob > 30% AND revenue_at_risk exceeds breakeven.",
    ],
  },
  abc_xyz: {
    title: "ABC × XYZ classification",
    formula: "ABC by revenue Pareto · XYZ by demand CV",
    inputs: [
      "ABC: A=top 80% cumulative revenue, B=next 15%, C=remaining 5%",
      "XYZ: X=CV<0.25, Y=0.25≤CV<0.5, Z=CV≥0.5",
    ],
    assumptions: [
      "AX = high revenue, predictable → tight (s,S) policy.",
      "CZ = low revenue, lumpy → review for discontinuation.",
    ],
  },
};
