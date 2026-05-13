from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PolicyName = Literal["EOQ", "(Q,R)", "(s,S)", "newsvendor", "base-stock"]
SkuStatus = Literal["order_now", "at_risk", "watch", "healthy"]


class RecommendationOverrides(BaseModel):
    service_level: float | None = None
    holding_cost_rate: float | None = None
    order_cost: float | None = None
    lead_time_days_override: float | None = None
    horizon_periods: int | None = None
    policy_override: PolicyName | None = None


class Recommendation(BaseModel):
    sku_id: str
    policy_name: PolicyName
    parameters: dict
    recommended_order_qty: float
    reorder_point: float | None = None
    safety_stock: float
    expected_stockout_prob: float = Field(ge=0.0, le=1.0)
    expected_fill_rate: float = Field(ge=0.0, le=1.0)
    expected_holding_cost_annual: float
    expected_total_cost_annual: float
    abc_class: Literal["A", "B", "C"]
    xyz_class: Literal["X", "Y", "Z"]
    schedule: list[dict] | None = None
    joint_replen_group: str | None = None
    caveats: list[str] = []


class SkuTableRow(BaseModel):
    sku_id: str
    category: str | None = None
    supplier: str | None = None
    abc_class: Literal["A", "B", "C"]
    xyz_class: Literal["X", "Y", "Z"]
    last_demand: float
    on_hand: float | None = None
    days_of_cover: float | None = None
    cv_demand: float
    revenue_annual: float
    n_obs: int
    history: list[float] | None = None
    lead_time_days: float | None = None
    status: SkuStatus = "healthy"


class AggregateStats(BaseModel):
    dataset_id: str
    n_skus: int
    total_revenue_annual: float
    total_inventory_value: float | None = None
    avg_days_of_cover: float | None = None
    pct_stockout_risk_high: float | None = None
    abc_counts: dict[str, int]
    xyz_counts: dict[str, int]
    abc_xyz_heatmap: dict[str, int]
    n_skus_low_history: int
