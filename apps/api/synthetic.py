"""Synthetic SKU panel + supplier metadata + receipt history generator.

Produces:
- panel: canonical-schema DataFrame (matches docs/CLAUDE.md schema)
- suppliers: supplier scorecard metadata (MOQ, case_pack, payment terms, etc.)
- receipts: historical PO receipt events (used for OTIF + Bayesian lead-time learning)

The realistic supplier names + categories make every downstream feature
(Reorder Queue, Supplier Scorecard, Stress Test) render plausibly.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

CANONICAL_COLUMNS = [
    "sku_id", "date", "demand", "on_hand",
    "lead_time_days", "unit_cost", "unit_price", "supplier", "category",
]

SUPPLIERS_COLUMNS = [
    "supplier_id", "name", "contact_email", "country",
    "payment_terms", "default_lead_time_days", "lead_time_std_days",
    "moq", "case_pack", "notes",
]

RECEIPTS_COLUMNS = [
    "receipt_id", "sku_id", "supplier_id",
    "ordered_date", "expected_date", "received_date",
    "ordered_qty", "received_qty",
]

FREQ_TO_PERIODS_PER_YEAR = {"D": 365, "W": 52, "M": 12}
FREQ_TO_PANDAS = {"D": "D", "W": "W-MON", "M": "MS"}
FREQ_TO_SEASONAL_PERIOD = {"D": 7, "W": 52, "M": 12}

_SUPPLIER_FIRSTS = [
    "Northwind", "Pacific", "Atlas", "Cascade", "Maple Valley", "Granite State",
    "Harbor", "Summit", "Evergreen", "Ironwood", "Stonebridge", "Cedar Creek",
    "Goldleaf", "Birchwood", "Sterling", "Heritage", "Riverside", "Sunbelt",
    "Lakeshore", "Highland", "Crestline", "Foothill", "Westwind", "Eastpoint",
    "Crown", "Vanguard", "Pioneer", "Beacon", "Acme", "Apex",
    "Meridian", "Cornerstone", "Bluefield", "Greystone", "Redwood",
]

_SUPPLIER_BUSINESS = {
    "FOOD": ["Foods", "Provisions", "Pantry", "Kitchens", "Harvest", "Grocers"],
    "BEV":  ["Beverages", "Roasters", "Brewers", "Drinks", "Bottling"],
    "APPAREL": ["Apparel", "Garments", "Textiles", "Outfitters", "Threads"],
    "ELEC": ["Electronics", "Components", "Devices", "Tech", "Systems"],
    "HOME": ["Home Goods", "Houseware", "Living", "Interiors"],
    "BEAUTY": ["Beauty", "Cosmetics", "Wellness", "Care"],
    "GENERAL": ["Distribution", "Trading", "Industries", "Enterprises", "Group"],
}

_SUPPLIER_SUFFIX = ["LLC", "Inc.", "Corp.", "Co.", "Ltd.", "Holdings", ""]

_COUNTRIES = ["USA", "USA", "USA", "USA", "Canada", "Mexico", "Vietnam", "China", "Italy", "Germany"]

_PAYMENT_TERMS = ["Net 30", "Net 30", "Net 30", "Net 45", "Net 60", "2/10 Net 30"]

_CATEGORY_SETS: dict[str, list[tuple[str, str]]] = {
    "retail_stable": [
        ("Beverages", "BEV"),
        ("Snacks", "FOOD"),
        ("Personal Care", "BEAUTY"),
        ("Household", "HOME"),
    ],
    "coffee_perishable": [
        ("Coffee Beans", "BEV"),
        ("Tea", "BEV"),
        ("Pastries", "FOOD"),
    ],
    "ecommerce_lumpy": [
        ("Apparel", "APPAREL"),
        ("Electronics", "ELEC"),
        ("Home Goods", "HOME"),
        ("Beauty", "BEAUTY"),
        ("Sporting Goods", "GENERAL"),
        ("Toys", "GENERAL"),
    ],
    "b2b_industrial": [
        ("Industrial Components", "GENERAL"),
        ("Fasteners", "GENERAL"),
        ("Bearings", "GENERAL"),
        ("Lubricants", "GENERAL"),
    ],
    "pharma_steady": [
        ("Prescription", "GENERAL"),
        ("OTC", "GENERAL"),
        ("Medical Devices", "ELEC"),
        ("Vitamins", "BEAUTY"),
    ],
    "spare_parts_mro": [
        ("Replacement Parts", "GENERAL"),
        ("Service Items", "GENERAL"),
        ("Filters", "GENERAL"),
        ("Belts & Hoses", "GENERAL"),
    ],
}


def _negbin_from_mean_var(mean: np.ndarray, dispersion: float, rng: np.random.Generator) -> np.ndarray:
    """Sample NegBin given mean and dispersion `r` (Var = mean + mean^2 / r)."""
    mean = np.maximum(mean, 1e-9)
    p = dispersion / (dispersion + mean)
    return rng.negative_binomial(dispersion, p)


def _build_supplier_pool(rng: np.random.Generator, n_suppliers: int, category_kinds: list[str]) -> list[dict]:
    pool: list[dict] = []
    used_names: set[str] = set()
    firsts = list(_SUPPLIER_FIRSTS)
    rng.shuffle(firsts)
    for i in range(n_suppliers):
        kind = category_kinds[i % len(category_kinds)] if category_kinds else "GENERAL"
        biz_choices = _SUPPLIER_BUSINESS.get(kind, _SUPPLIER_BUSINESS["GENERAL"])
        if rng.random() < 0.20:
            biz_choices = _SUPPLIER_BUSINESS["GENERAL"]
        first = firsts[i % len(firsts)]
        for _ in range(6):
            biz = rng.choice(biz_choices)
            suffix = rng.choice(_SUPPLIER_SUFFIX)
            name = f"{first} {biz} {suffix}".strip()
            if name not in used_names:
                break
        used_names.add(name)

        slug = first.upper().replace(" ", "")[:8] + "_" + str(biz).upper().replace(" ", "")[:3]
        supplier_id = f"SUP_{slug}_{i:02d}"

        moq = float(rng.choice([12, 24, 50, 100, 144, 288, 500]))
        case_pack = float(rng.choice([1, 6, 12, 24, 48]))

        pool.append(dict(
            supplier_id=supplier_id,
            name=name,
            contact_email=f"orders@{first.lower().replace(' ', '')}.example.com",
            country=str(rng.choice(_COUNTRIES)),
            payment_terms=str(rng.choice(_PAYMENT_TERMS)),
            moq=moq,
            case_pack=case_pack,
        ))
    return pool


def generate_synthetic(
    n_skus: int = 100,
    n_periods: int = 104,
    frequency: str = "W",
    seasonality_strength: float = 0.3,
    trend_slope: float = 0.0,
    intermittency_rate: float = 0.0,
    lead_time_mean_days: float = 14.0,
    lead_time_cv: float = 0.2,
    n_suppliers: int = 5,
    n_categories: int = 4,
    base_demand_min: float = 5.0,
    base_demand_max: float = 80.0,
    dispersion: float = 4.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate a synthetic SKU panel (canonical columns only).

    For supplier metadata + receipts use `generate_synthetic_full`.
    """
    panel, _, _ = generate_synthetic_full(
        n_skus=n_skus,
        n_periods=n_periods,
        frequency=frequency,
        seasonality_strength=seasonality_strength,
        trend_slope=trend_slope,
        intermittency_rate=intermittency_rate,
        lead_time_mean_days=lead_time_mean_days,
        lead_time_cv=lead_time_cv,
        n_suppliers=n_suppliers,
        n_categories=n_categories,
        base_demand_min=base_demand_min,
        base_demand_max=base_demand_max,
        dispersion=dispersion,
        n_receipts_per_sku=0,
        seed=seed,
    )
    return panel


def generate_synthetic_full(
    template_name: str | None = None,
    n_skus: int = 100,
    n_periods: int = 104,
    frequency: str = "W",
    seasonality_strength: float = 0.3,
    trend_slope: float = 0.0,
    intermittency_rate: float = 0.0,
    lead_time_mean_days: float = 14.0,
    lead_time_cv: float = 0.2,
    n_suppliers: int = 5,
    n_categories: int = 4,
    base_demand_min: float = 5.0,
    base_demand_max: float = 80.0,
    dispersion: float = 4.0,
    n_receipts_per_sku: int = 4,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Generate a synthetic SKU panel, supplier metadata, and historical receipts."""
    if frequency not in FREQ_TO_PERIODS_PER_YEAR:
        raise ValueError(f"frequency must be one of {list(FREQ_TO_PERIODS_PER_YEAR)}")
    if not (0.0 <= intermittency_rate <= 1.0):
        raise ValueError("intermittency_rate must be in [0, 1]")

    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n_periods, freq=FREQ_TO_PANDAS[frequency])

    sku_ids = [f"SKU-{i:05d}" for i in range(n_skus)]

    cat_set = _CATEGORY_SETS.get(template_name)
    if cat_set is None or len(cat_set) < n_categories:
        existing = list(cat_set) if cat_set else []
        for c in range(n_categories - len(existing)):
            existing.append((f"Category {c+1}", "GENERAL"))
        cat_set = existing[:n_categories]

    category_names = [c[0] for c in cat_set]
    category_kinds = [c[1] for c in cat_set]
    n_categories_eff = len(category_names)

    supplier_pool = _build_supplier_pool(rng, n_suppliers, category_kinds)

    sku_category_idx = rng.integers(0, n_categories_eff, size=n_skus)
    sku_category = [category_names[i] for i in sku_category_idx]
    sku_supplier_idx = rng.integers(0, n_suppliers, size=n_skus)

    sku_base = rng.uniform(base_demand_min, base_demand_max, size=n_skus)
    sku_phase = rng.uniform(0, 2 * np.pi, size=n_skus)
    sku_intermittency = np.clip(rng.normal(intermittency_rate, 0.05, size=n_skus), 0.0, 0.99)
    sku_unit_cost = rng.uniform(2.0, 30.0, size=n_skus).round(2)
    sku_markup = rng.uniform(1.2, 2.5, size=n_skus)
    sku_unit_price = (sku_unit_cost * sku_markup).round(2)

    period_idx = np.arange(n_periods)
    seasonal_period = FREQ_TO_SEASONAL_PERIOD[frequency]
    season_factor = np.array([
        1.0 + seasonality_strength * np.sin(2 * np.pi * period_idx / seasonal_period + phase)
        for phase in sku_phase
    ])
    trend_factor = np.exp(trend_slope * period_idx)[None, :]
    base = sku_base[:, None] * season_factor * trend_factor

    demand = _negbin_from_mean_var(base, dispersion, rng)

    if intermittency_rate > 0:
        zero_mask = rng.uniform(size=demand.shape) < sku_intermittency[:, None]
        demand = np.where(zero_mask, 0, demand)

    shape_lt = 1.0 / (lead_time_cv ** 2)
    for sup in supplier_pool:
        scale = lead_time_mean_days / shape_lt
        mean_lt = float(rng.gamma(shape=shape_lt, scale=scale))
        sup["default_lead_time_days"] = round(mean_lt, 2)
        sup["lead_time_std_days"] = round(mean_lt * lead_time_cv, 2)
        sup["notes"] = ""

    panel_rows: list[dict] = []
    for i, sku in enumerate(sku_ids):
        sup = supplier_pool[sku_supplier_idx[i]]
        cat = sku_category[i]
        cost = sku_unit_cost[i]
        price = sku_unit_price[i]
        on_hand_avg = float(np.mean(demand[i]) * 4)
        for j, dt in enumerate(dates):
            panel_rows.append({
                "sku_id": sku,
                "date": dt.date(),
                "demand": float(demand[i, j]),
                "on_hand": on_hand_avg if j == n_periods - 1 else None,
                "lead_time_days": sup["default_lead_time_days"],
                "unit_cost": float(cost),
                "unit_price": float(price),
                "supplier": sup["name"],
                "category": cat,
            })

    panel_df = pd.DataFrame(panel_rows, columns=CANONICAL_COLUMNS)
    panel_df["date"] = pd.to_datetime(panel_df["date"])

    suppliers_df = pd.DataFrame(supplier_pool)[SUPPLIERS_COLUMNS]

    panel_first = dates[0]
    panel_last = dates[-1]
    panel_span_days = max(1, (panel_last - panel_first).days)
    receipt_rows: list[dict] = []
    rcount = 0
    for i, sku in enumerate(sku_ids):
        sup = supplier_pool[sku_supplier_idx[i]]
        sup_id = sup["supplier_id"]
        mean_lt = float(sup["default_lead_time_days"])
        std_lt = max(float(sup["lead_time_std_days"]), 0.5)
        avg_demand = max(float(np.mean(demand[i])), 0.5)
        case_pack = max(float(sup["case_pack"]), 1.0)
        moq = float(sup["moq"])
        for k in range(n_receipts_per_sku):
            base_offset = int(panel_span_days * (k + 1) / (n_receipts_per_sku + 1))
            jitter = int(rng.integers(-3, 4))
            offset_days = max(0, min(panel_span_days - 1, base_offset + jitter))
            received_date = panel_first + pd.Timedelta(days=offset_days)
            actual_lt = max(1.0, float(rng.normal(mean_lt, std_lt)))
            ordered_date = received_date - pd.Timedelta(days=actual_lt)
            expected_date = ordered_date + pd.Timedelta(days=mean_lt)
            qty = max(1.0, float(rng.normal(avg_demand * 8, avg_demand * 2)))
            qty = round(qty / case_pack) * case_pack
            qty = max(qty, moq)
            received = qty if rng.random() > 0.07 else qty * float(rng.uniform(0.85, 0.99))
            rcount += 1
            receipt_rows.append({
                "receipt_id": f"RCP-{rcount:06d}",
                "sku_id": sku,
                "supplier_id": sup_id,
                "ordered_date": ordered_date.date(),
                "expected_date": expected_date.date(),
                "received_date": received_date.date(),
                "ordered_qty": float(qty),
                "received_qty": float(received),
            })

    receipts_df = pd.DataFrame(receipt_rows, columns=RECEIPTS_COLUMNS)

    return panel_df, suppliers_df, receipts_df


@dataclass(frozen=True)
class Template:
    name: str
    kwargs: dict


TEMPLATES: dict[str, Template] = {
    "retail_stable": Template(
        name="retail_stable",
        # Target retail_m5 centroid: cv≈1.85, intermittency≈0.62, seasonality≈0.32
        kwargs=dict(
            template_name="retail_stable",
            n_skus=200, n_periods=104, frequency="W",
            seasonality_strength=0.5, trend_slope=0.001,
            intermittency_rate=0.45,
            lead_time_mean_days=10, lead_time_cv=0.15,
            n_suppliers=6, n_categories=4,
            base_demand_min=20, base_demand_max=120, dispersion=1.3,
            n_receipts_per_sku=4,
        ),
    ),
    "coffee_perishable": Template(
        name="coffee_perishable",
        kwargs=dict(
            template_name="coffee_perishable",
            n_skus=80, n_periods=180, frequency="D",
            seasonality_strength=0.4, trend_slope=0.0,
            intermittency_rate=0.10,
            lead_time_mean_days=3, lead_time_cv=0.3,
            n_suppliers=3, n_categories=3,
            base_demand_min=10, base_demand_max=60, dispersion=2.0,
            n_receipts_per_sku=6,
        ),
    ),
    "ecommerce_lumpy": Template(
        name="ecommerce_lumpy",
        # Target ecommerce_fashion centroid: cv≈2.4, intermittency≈0.45, seasonality≈0.55
        kwargs=dict(
            template_name="ecommerce_lumpy",
            n_skus=300, n_periods=104, frequency="W",
            seasonality_strength=0.6, trend_slope=0.003,
            intermittency_rate=0.40,
            lead_time_mean_days=21, lead_time_cv=0.4,
            n_suppliers=10, n_categories=6,
            base_demand_min=2, base_demand_max=40, dispersion=0.5,
            n_receipts_per_sku=4,
        ),
    ),
    "b2b_industrial": Template(
        name="b2b_industrial",
        # Target b2b_industrial centroid: cv≈1.4, intermittency≈0.55, seasonality≈0.18
        kwargs=dict(
            template_name="b2b_industrial",
            n_skus=150, n_periods=104, frequency="W",
            seasonality_strength=0.15, trend_slope=0.0005,
            intermittency_rate=0.50,
            lead_time_mean_days=18, lead_time_cv=0.3,
            n_suppliers=5, n_categories=4,
            base_demand_min=10, base_demand_max=80, dispersion=1.5,
            n_receipts_per_sku=4,
        ),
    ),
    "pharma_steady": Template(
        name="pharma_steady",
        # Target pharma_medical centroid: cv≈0.65, intermittency≈0.12, seasonality≈0.30
        kwargs=dict(
            template_name="pharma_steady",
            n_skus=120, n_periods=104, frequency="W",
            seasonality_strength=0.30, trend_slope=0.0005,
            intermittency_rate=0.10,
            lead_time_mean_days=14, lead_time_cv=0.15,
            n_suppliers=4, n_categories=4,
            base_demand_min=40, base_demand_max=160, dispersion=4.0,
            n_receipts_per_sku=4,
        ),
    ),
    "spare_parts_mro": Template(
        name="spare_parts_mro",
        # Target spare_parts_mro centroid: cv≈3.5, intermittency≈0.85, seasonality≈0.10
        kwargs=dict(
            template_name="spare_parts_mro",
            n_skus=180, n_periods=104, frequency="W",
            seasonality_strength=0.08, trend_slope=0.0,
            intermittency_rate=0.80,
            lead_time_mean_days=28, lead_time_cv=0.5,
            n_suppliers=8, n_categories=4,
            base_demand_min=2, base_demand_max=20, dispersion=0.7,
            n_receipts_per_sku=3,
        ),
    ),
}


def template_retail_stable(seed: int = 42) -> pd.DataFrame:
    panel, _, _ = generate_synthetic_full(seed=seed, **TEMPLATES["retail_stable"].kwargs)
    return panel


def template_coffee_perishable(seed: int = 42) -> pd.DataFrame:
    panel, _, _ = generate_synthetic_full(seed=seed, **TEMPLATES["coffee_perishable"].kwargs)
    return panel


def template_ecommerce_lumpy(seed: int = 42) -> pd.DataFrame:
    panel, _, _ = generate_synthetic_full(seed=seed, **TEMPLATES["ecommerce_lumpy"].kwargs)
    return panel


def generate_template_full(template: str, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if template not in TEMPLATES:
        raise ValueError(f"unknown template {template!r}; known: {list(TEMPLATES)}")
    return generate_synthetic_full(seed=seed, **TEMPLATES[template].kwargs)


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic SKU panel + sidecars.")
    parser.add_argument("--template", choices=list(TEMPLATES), required=True)
    parser.add_argument("--out", required=True, help="Output CSV path for panel.")
    parser.add_argument("--out-suppliers", default=None, help="Optional output path for suppliers CSV.")
    parser.add_argument("--out-receipts", default=None, help="Optional output path for receipts CSV.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    panel, suppliers, receipts = generate_synthetic_full(seed=args.seed, **TEMPLATES[args.template].kwargs)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(out_path, index=False)
    print(f"Wrote {len(panel):,} rows to {out_path}")

    if args.out_suppliers:
        sp = Path(args.out_suppliers)
        sp.parent.mkdir(parents=True, exist_ok=True)
        suppliers.to_csv(sp, index=False)
        print(f"Wrote {len(suppliers):,} supplier rows to {sp}")
    else:
        sp = out_path.with_name(out_path.stem + ".suppliers.csv")
        suppliers.to_csv(sp, index=False)
        print(f"Wrote {len(suppliers):,} supplier rows to {sp}")

    if args.out_receipts:
        rp = Path(args.out_receipts)
        rp.parent.mkdir(parents=True, exist_ok=True)
        receipts.to_csv(rp, index=False)
        print(f"Wrote {len(receipts):,} receipt rows to {rp}")
    else:
        rp = out_path.with_name(out_path.stem + ".receipts.csv")
        receipts.to_csv(rp, index=False)
        print(f"Wrote {len(receipts):,} receipt rows to {rp}")


if __name__ == "__main__":
    _cli()
