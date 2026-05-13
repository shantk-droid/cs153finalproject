from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Severity(str, Enum):
    hard = "hard"
    soft = "soft"
    info = "info"


class Assertion(BaseModel):
    code: str
    severity: Severity
    field: str | None
    message: str
    offending_examples: list[dict]
    offending_row_count: int
    skus_affected: int | None = None


ComponentName = Literal[
    "completeness",
    "plausibility",
    "distribution_profile",
    "history_depth",
    "stationarity",
]


class ComponentScore(BaseModel):
    name: ComponentName
    score: float | None = Field(default=None, ge=0.0, le=100.0,
                                description="0–100. None means component is deferred.")
    weight: float = Field(ge=0.0, le=1.0)
    notes: list[str] = []


class ProfileInfo(BaseModel):
    profile_id: str
    label: str
    auto_detected: bool = False
    match_confidence: float | None = None


class DataQualityReport(BaseModel):
    dataset_id: str
    composite_score: float | None = Field(default=None, ge=0.0, le=100.0,
                                          description="Weighted average of available components, renormalized.")
    components: list[ComponentScore]
    assertions: list[Assertion]
    n_rows: int
    n_skus: int
    skus_low_history: list[str] = []
    skus_with_business_logic_issues: list[str] = []
    profile: ProfileInfo | None = Field(
        default=None,
        description="Reference profile this report was scored against.",
    )
    flagged_metrics: dict[str, int] = Field(
        default_factory=dict,
        description="Per-metric count of SKU values outside the profile's [p10, p90] band — informational.",
    )
    explanations: dict[str, str] | None = Field(
        default=None,
        description="Per-assertion-code plain-English explanation (LLM-generated). "
                    "Populated when `?explain=true` is requested on /quality.",
    )
