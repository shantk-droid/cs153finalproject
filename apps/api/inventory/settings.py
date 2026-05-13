"""Per-dataset settings persistence.

Users can override service level, holding cost rate, and order cost defaults at the dataset
level. Stored as a JSON sidecar at `data/datasets/{dataset_id}.settings.json`. Read by the
recommend orchestrator before applying any per-call overrides.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from apps.api.config import get_settings


class DatasetSettings(BaseModel):
    service_level: float = Field(default=0.95, ge=0.5, le=0.999)
    holding_cost_rate: float = Field(default=0.25, ge=0.0, le=1.0)
    order_cost: float = Field(default=50.0, ge=0.0)
    review_period_days: int = Field(default=14, ge=1, le=365)
    notes: str | None = None


def _settings_path(dataset_id: str) -> Path:
    base = get_settings().data_path
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{dataset_id}.settings.json"


def load_dataset_settings(dataset_id: str) -> DatasetSettings:
    """Return persisted settings, or defaults if not yet saved."""
    path = _settings_path(dataset_id)
    if not path.exists():
        return DatasetSettings()
    try:
        return DatasetSettings.model_validate_json(path.read_text())
    except Exception:
        return DatasetSettings()


def save_dataset_settings(dataset_id: str, settings: DatasetSettings) -> None:
    path = _settings_path(dataset_id)
    path.write_text(settings.model_dump_json(indent=2))
