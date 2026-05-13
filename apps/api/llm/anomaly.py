"""Pure-Python anomaly detection for SKU demand series.

Robust z-score (rolling median + MAD) + CUSUM. Returns structured events the
LLM explainer can ground its reasoning in. The LLM never invents an anomaly —
it only writes the explanation.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

import numpy as np
import pandas as pd

from apps.api.db import open_dataset


Severity = Literal["info", "warn", "crit"]
Direction = Literal["spike", "drop"]


@dataclass
class AnomalyEvent:
    date: str
    value: float
    direction: Direction
    magnitude_z: float
    cusum_score: float
    baseline_mean: float
    baseline_std: float
    severity: Severity

    def to_dict(self) -> dict:
        return asdict(self)


def _rolling_median(values: np.ndarray, window: int) -> np.ndarray:
    n = len(values)
    out = np.empty(n)
    half = max(1, window // 2)
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out[i] = float(np.median(values[lo:hi]))
    return out


def _rolling_mad(values: np.ndarray, medians: np.ndarray, window: int) -> np.ndarray:
    n = len(values)
    out = np.empty(n)
    half = max(1, window // 2)
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out[i] = float(np.median(np.abs(values[lo:hi] - medians[i])))
    return np.maximum(out, 1e-9)


def detect_anomalies(
    dataset_id: str,
    sku_id: str,
    *,
    anchor_date: str | None = None,
    severity_threshold: float = 2.5,
    max_events: int = 5,
) -> list[AnomalyEvent]:
    """Detect spikes/drops in a SKU's demand history.

    Algorithm:
      1. Pull the full demand series (or last 200 periods, whichever is shorter).
      2. Robust baseline: rolling median + 1.4826*MAD over a window of min(13, n/4).
      3. Robust z-score = (value - median) / (1.4826 * MAD).
      4. CUSUM with k=0.5 and h=4 (in z-units).
      5. Flag periods where |z| >= threshold or CUSUM trips.

    Returns events sorted by |z| descending. If `anchor_date` is given, returns
    only the single event closest to that date (±5 periods).
    """
    sku_id = sku_id.strip().upper()
    with open_dataset(dataset_id, read_only=True) as conn:
        df = conn.execute(
            "SELECT date, demand FROM panel WHERE sku_id = ? ORDER BY date",
            [sku_id],
        ).fetchdf()
    if df.empty:
        return []
    if len(df) < 8:
        return []

    df = df.tail(200).reset_index(drop=True)
    values = df["demand"].astype(float).to_numpy()
    n = len(values)
    window = max(5, min(13, n // 4))

    medians = _rolling_median(values, window)
    mads = _rolling_mad(values, medians, window)
    z_scores = (values - medians) / (1.4826 * mads)

    cusum_pos = np.zeros(n)
    cusum_neg = np.zeros(n)
    k = 0.5
    h = 4.0
    for i in range(1, n):
        cusum_pos[i] = max(0.0, cusum_pos[i - 1] + (z_scores[i] - k))
        cusum_neg[i] = min(0.0, cusum_neg[i - 1] + (z_scores[i] + k))

    events: list[AnomalyEvent] = []
    for i in range(n):
        z = float(z_scores[i])
        cusum_val = float(cusum_pos[i] if abs(cusum_pos[i]) > abs(cusum_neg[i]) else cusum_neg[i])
        cusum_trip = cusum_pos[i] >= h or cusum_neg[i] <= -h
        if abs(z) < severity_threshold and not cusum_trip:
            continue
        direction: Direction = "spike" if z >= 0 else "drop"
        if abs(z) > 4 or cusum_trip:
            severity: Severity = "crit"
        elif abs(z) > 3:
            severity = "warn"
        else:
            severity = "info"
        events.append(AnomalyEvent(
            date=pd.Timestamp(df["date"].iloc[i]).date().isoformat(),
            value=float(values[i]),
            direction=direction,
            magnitude_z=z,
            cusum_score=cusum_val,
            baseline_mean=float(medians[i]),
            baseline_std=float(1.4826 * mads[i]),
            severity=severity,
        ))

    if anchor_date:
        try:
            anchor = pd.Timestamp(anchor_date).date()
            events.sort(key=lambda e: abs((pd.Timestamp(e.date).date() - anchor).days))
            events = events[:1]
        except Exception:
            pass
    else:
        events.sort(key=lambda e: abs(e.magnitude_z), reverse=True)
        events = events[:max_events]

    return events
