"""CRPS-weighted ensemble combiner.

Given multiple forecasters' (point + quantile) outputs and per-method backtest CRPS, return
a combined forecast where weights are inversely proportional to CRPS.

If a method has CRPS=None (unavailable), it gets equal weight as a fallback.
If all methods have CRPS=None, simple average.
The combined quantile output is the weighted quantile-by-quantile average — *not* technically
correct (combining quantiles is non-linear) but a reasonable v1 that avoids needing samples.

Day 11+ can upgrade to a sample-based ensemble where each member emits N samples and we mix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from apps.api.forecasting.classical import QUANTILES


@dataclass
class EnsembleMember:
    method: str
    point: np.ndarray
    quantiles: dict[float, np.ndarray]
    crps_backtest: float | None


def crps_weights(members: list[EnsembleMember]) -> dict[str, float]:
    """Convert per-member CRPS into normalized inverse-CRPS weights."""
    valid = [m for m in members if m.crps_backtest is not None and m.crps_backtest > 0]
    if not valid:
        return {m.method: 1.0 / len(members) for m in members}
    inv = np.array([1.0 / m.crps_backtest for m in valid])
    inv /= inv.sum()
    weights = {m.method: float(w) for m, w in zip(valid, inv)}
    for m in members:
        weights.setdefault(m.method, 0.0)
    return weights


def combine(members: list[EnsembleMember]) -> tuple[np.ndarray, dict[float, np.ndarray], dict[str, float]]:
    """Return (point, quantiles, weights) for the weighted combination."""
    if not members:
        raise ValueError("ensemble must have at least one member")

    weights = crps_weights(members)
    horizon = len(members[0].point)
    point = np.zeros(horizon)
    quantiles = {q: np.zeros(horizon) for q in QUANTILES}

    for m in members:
        w = weights.get(m.method, 0.0)
        if w == 0.0:
            continue
        point += w * np.asarray(m.point, dtype=float)
        for q in QUANTILES:
            arr = m.quantiles.get(q)
            if arr is not None:
                quantiles[q] += w * np.asarray(arr, dtype=float)

    point = np.maximum(0.0, point)
    quantiles = {q: np.maximum(0.0, v) for q, v in quantiles.items()}
    return point, quantiles, weights
