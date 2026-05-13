from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

CanonicalField = Literal[
    "sku_id", "date", "demand",
    "on_hand", "lead_time_days", "unit_cost", "unit_price",
    "supplier", "category",
]

CANONICAL_FIELDS: tuple[CanonicalField, ...] = (
    "sku_id", "date", "demand",
    "on_hand", "lead_time_days", "unit_cost", "unit_price",
    "supplier", "category",
)
REQUIRED_FIELDS: tuple[CanonicalField, ...] = ("sku_id", "date", "demand")


class ColumnDetection(BaseModel):
    name: str
    dtype: Literal["string", "integer", "float", "date", "boolean", "unknown"]
    null_pct: float
    unique_pct: float
    sample_values: list[str]


class SuggestedMappingItem(BaseModel):
    canonical: CanonicalField
    file_column: str | None
    confidence: float = Field(ge=0.0, le=1.0)


class DatasetPreview(BaseModel):
    dataset_id: str
    filename: str
    n_total_rows: int
    detected_columns: list[ColumnDetection]
    suggested_mapping: list[SuggestedMappingItem]
    sample_rows: list[dict]
    sheet_names: list[str] | None = None
    selected_sheet: str | None = None
    detected_connector: Literal["shopify"] | None = None  # NEW: set when a vendor connector auto-detected


class ColumnMapping(BaseModel):
    sku_id: str
    date: str
    demand: str
    on_hand: str | None = None
    lead_time_days: str | None = None
    unit_cost: str | None = None
    unit_price: str | None = None
    supplier: str | None = None
    category: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return self.model_dump()


class DatasetSummary(BaseModel):
    dataset_id: str
    n_rows: int
    n_skus: int
    date_min: date
    date_max: date
    frequency: Literal["D", "W", "M"] | None
    n_categories: int
    n_suppliers: int
    has_on_hand: bool
    has_lead_time: bool
    has_unit_cost: bool
    has_unit_price: bool
