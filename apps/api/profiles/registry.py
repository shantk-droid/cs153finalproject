"""Profile registry — versioned reference distributions per industry.

A profile defines, for each of the five panel-level metrics
(cv_demand, intermittency_rate, regime_shift_score, trend_slope_pct,
seasonality_strength), four percentiles that anchor a soft-penalty curve
plus a centroid used for auto-detection.

All profiles ship as JSON in `apps/api/profiles/data/`. They are loaded once
on first access and cached in-memory.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

METRIC_NAMES: tuple[str, ...] = (
    "cv_demand",
    "intermittency_rate",
    "regime_shift_score",
    "trend_slope_pct",
    "seasonality_strength",
)


class Band(BaseModel):
    p2: float
    p10: float
    p90: float
    p98: float


class Profile(BaseModel):
    id: str
    label: str
    description: str
    version: str
    bands: dict[str, Band]
    centroid: dict[str, float]


def _data_dir() -> Path:
    return Path(__file__).parent / "data"


@lru_cache(maxsize=1)
def _load_all() -> dict[str, Profile]:
    out: dict[str, Profile] = {}
    for p in sorted(_data_dir().glob("*.json")):
        raw = json.loads(p.read_text())
        prof = Profile.model_validate(raw)
        out[prof.id] = prof
    return out


def list_profiles() -> list[Profile]:
    return list(_load_all().values())


def get_profile(profile_id: str) -> Profile:
    profiles = _load_all()
    if profile_id not in profiles:
        raise KeyError(f"unknown profile_id={profile_id!r}; have {sorted(profiles)}")
    return profiles[profile_id]


def score_metric(value: float, band: Band) -> float:
    """Soft-penalty score in [0, 100].

    100 inside [p10, p90]; linear ramp to 50 between [p2, p10] and [p90, p98];
    decays toward 0 outside [p2, p98].
    """
    p2, p10, p90, p98 = band.p2, band.p10, band.p90, band.p98
    if p10 <= value <= p90:
        return 100.0
    if p2 <= value < p10:
        denom = p10 - p2
        return 50.0 + 50.0 * (value - p2) / denom if denom > 0 else 75.0
    if p90 < value <= p98:
        denom = p98 - p90
        return 50.0 + 50.0 * (p98 - value) / denom if denom > 0 else 75.0
    if value < p2:
        return max(0.0, 50.0 * (1 - (p2 - value) / max(abs(p2), 1e-6)))
    return max(0.0, 50.0 * (1 - (value - p98) / max(abs(p98), 1e-6)))


def match_profile(dataset_medians: dict[str, float]) -> tuple[str, float]:
    """Return `(best_profile_id, confidence)` where confidence ∈ [0, 1].

    Confidence ~= 1 when the dataset sits exactly on a profile's centroid;
    drops as the dataset moves away in standardised metric space.
    """
    profiles = list_profiles()
    if not profiles:
        raise RuntimeError("no profiles loaded")

    best_id: str | None = None
    best_dist = float("inf")
    for prof in profiles:
        dist_sq = 0.0
        for metric in METRIC_NAMES:
            val = dataset_medians.get(metric)
            if val is None:
                continue
            centroid = prof.centroid[metric]
            band = prof.bands[metric]
            scale = max(band.p98 - band.p2, 1e-6)
            dist_sq += ((val - centroid) / scale) ** 2
        if dist_sq < best_dist:
            best_dist = dist_sq
            best_id = prof.id

    assert best_id is not None
    confidence = 1.0 / (1.0 + best_dist ** 0.5)
    return best_id, confidence
