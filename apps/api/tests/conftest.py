from __future__ import annotations

import os

# lightgbm + macOS libomp + threaded TestClient = occasional segfaults under pytest.
# Forcing single-threaded OMP at import time avoids the issue without affecting production.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

# Disable rate limits in tests so per-IP counters don't bleed across the TestClient session.
os.environ.setdefault("RATELIMIT_DISABLED", "1")

from pathlib import Path

import pandas as pd
import pytest

from apps.api.synthetic import template_retail_stable


@pytest.fixture
def sample_panel() -> pd.DataFrame:
    return template_retail_stable(seed=7)


@pytest.fixture
def sample_csv_bytes(sample_panel: pd.DataFrame) -> bytes:
    return sample_panel.to_csv(index=False).encode("utf-8")


@pytest.fixture
def sample_xlsx_bytes(sample_panel: pd.DataFrame, tmp_path: Path) -> bytes:
    p = tmp_path / "sample.xlsx"
    sample_panel.to_excel(p, index=False)
    return p.read_bytes()


@pytest.fixture
def renamed_csv_bytes(sample_panel: pd.DataFrame) -> bytes:
    """A CSV with non-canonical headers, to exercise column auto-detect."""
    df = sample_panel.rename(columns={
        "sku_id": "Item ID",
        "date": "Day",
        "demand": "Units Sold",
        "on_hand": "Stock On Hand",
        "lead_time_days": "LT (days)",
        "unit_cost": "Cost",
        "unit_price": "Sell Price",
        "supplier": "Vendor",
        "category": "Department",
    })
    return df.to_csv(index=False).encode("utf-8")


@pytest.fixture
def csv_with_duplicates(sample_panel: pd.DataFrame) -> bytes:
    df = pd.concat([sample_panel, sample_panel.head(50)], ignore_index=True)
    return df.to_csv(index=False).encode("utf-8")


@pytest.fixture
def csv_with_bad_dates(sample_panel: pd.DataFrame) -> bytes:
    df = sample_panel.copy()
    df.loc[df.index[:10], "date"] = "not-a-date"
    return df.to_csv(index=False).encode("utf-8")


@pytest.fixture
def csv_with_negative_demand(sample_panel: pd.DataFrame) -> bytes:
    df = sample_panel.copy()
    df.loc[df.index[:30], "demand"] = -5
    return df.to_csv(index=False).encode("utf-8")


@pytest.fixture
def csv_with_demand_spikes(sample_panel: pd.DataFrame) -> bytes:
    df = sample_panel.copy()
    rolling_median = df.groupby("sku_id")["demand"].transform(lambda s: s.rolling(90, min_periods=10).median())
    target_idx = rolling_median[rolling_median > 0].index[:20]
    df.loc[target_idx, "demand"] = (rolling_median.loc[target_idx] * 50).fillna(1000)
    return df.to_csv(index=False).encode("utf-8")
