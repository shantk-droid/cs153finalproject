from __future__ import annotations

import numpy as np
import pandas as pd

from apps.api.forecasting.characterize import characterize_series


def test_short_series_is_trending_new():
    s = pd.Series([1.0] * 5)
    assert characterize_series(s, "W") == "trending_new"


def test_high_zero_pct_is_lumpy():
    s = pd.Series([0.0] * 50 + [10.0] * 5)
    assert characterize_series(s, "W") == "lumpy"


def test_moderate_zero_pct_is_intermittent():
    rng = np.random.default_rng(0)
    s = pd.Series(rng.choice([0.0, 1.0, 2.0, 3.0, 4.0], size=100, p=[0.5, 0.2, 0.1, 0.1, 0.1]))
    assert characterize_series(s, "W") == "intermittent"


def test_seasonal_series_detected():
    season = np.tile(np.array([10.0, 20.0, 30.0, 40.0, 30.0, 20.0, 10.0]), 20)
    s = pd.Series(season)
    assert characterize_series(s, "D") == "seasonal"


def test_smooth_series_default():
    rng = np.random.default_rng(1)
    s = pd.Series(50.0 + rng.normal(0, 1, size=100))
    assert characterize_series(s, "W") == "smooth"
