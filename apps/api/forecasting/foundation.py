"""Chronos-Bolt-Small foundation-model forecaster.

CPU-only by default; the pipeline is loaded once per process via lru_cache.
The first call downloads weights (~50MB for chronos-bolt-small) — pin via env if needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

DEFAULT_MODEL_NAME = "amazon/chronos-bolt-small"
QUANTILE_LEVELS = [0.025, 0.1, 0.5, 0.9, 0.975]


@dataclass
class FoundationOutput:
    method: str
    point: np.ndarray
    quantiles: dict[float, np.ndarray]


@lru_cache(maxsize=1)
def _pipeline(model_name: str = DEFAULT_MODEL_NAME):
    """Load the Chronos-Bolt pipeline once per process (CPU)."""
    import torch
    from chronos import ChronosBoltPipeline
    try:
        return ChronosBoltPipeline.from_pretrained(
            model_name, device_map="cpu", dtype=torch.float32,
        )
    except TypeError:
        return ChronosBoltPipeline.from_pretrained(
            model_name, device_map="cpu", torch_dtype=torch.float32,
        )


def is_available() -> bool:
    """True iff chronos-forecasting + torch import cleanly. Doesn't load weights."""
    try:
        import chronos  # noqa: F401
        import torch  # noqa: F401
        return True
    except Exception:
        return False


def forecast_foundation(
    series: np.ndarray,
    horizon: int,
    model_name: str = DEFAULT_MODEL_NAME,
) -> FoundationOutput:
    """Run Chronos-Bolt on a single series and return canonical 5-quantile output.

    Args:
        series: 1-D numpy array of historical demand (most-recent last).
        horizon: forecast horizon in periods.
    """
    import torch

    pipeline = _pipeline(model_name)
    ctx = torch.tensor(np.asarray(series, dtype=float), dtype=torch.float32).unsqueeze(0)
    quantiles_tensor, _mean = pipeline.predict_quantiles(
        ctx,
        prediction_length=horizon,
        quantile_levels=QUANTILE_LEVELS,
    )
    arr = quantiles_tensor.squeeze(0).cpu().numpy()
    arr = np.maximum(0.0, arr)
    quantiles = {q: arr[:, i] for i, q in enumerate(QUANTILE_LEVELS)}
    point = quantiles[0.5]
    return FoundationOutput(method="chronos_bolt", point=point, quantiles=quantiles)
