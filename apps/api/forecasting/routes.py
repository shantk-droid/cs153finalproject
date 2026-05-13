"""FastAPI router for SKU-keyed forecast endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from apps.api.db import dataset_path
from apps.api.forecasting.decompose import decompose_sku
from apps.api.forecasting.forecast import ForecastError, forecast_sku
from apps.api.forecasting.schemas import Forecast

router = APIRouter(prefix="/datasets", tags=["forecasting"])


@router.post(
    "/{dataset_id}/skus/{sku_id}/forecast",
    response_model=Forecast,
    description="Run a forecast for a single SKU. Horizon defaults to 12 periods.",
)
async def post_forecast(
    dataset_id: str,
    sku_id: str,
    horizon: int = Query(default=12, ge=1, le=104),
    n_backtest_folds: int = Query(default=3, ge=1, le=8),
) -> Forecast:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    try:
        return forecast_sku(dataset_id, sku_id, horizon=horizon, n_backtest_folds=n_backtest_folds)
    except ForecastError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post(
    "/{dataset_id}/skus/{sku_id}/decompose",
    description="STL-style decomposition (observed / trend / seasonal / residual) for one SKU.",
)
async def post_decompose(dataset_id: str, sku_id: str) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    try:
        return decompose_sku(dataset_id, sku_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
