"""Supplier scorecard aggregation + Bayesian lead-time learning + metadata derivation.

When suppliers.csv is uploaded alongside the panel, we use it directly. When
only a panel is uploaded (the typical case for real users), we derive a
supplier table heuristically from the panel data, so every downstream feature
that needs MOQ / case-pack / payment terms still has plausible values.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd


@dataclass
class SupplierScorecard:
    supplier_id: str
    name: str
    n_skus: int
    annual_revenue: float
    avg_lead_time_days: float | None
    lead_time_std_days: float | None
    leadtime_posterior_mean: float | None
    leadtime_posterior_std: float | None
    on_time_pct: float | None
    in_full_pct: float | None
    otif_pct: float | None
    n_receipts: int
    payment_terms: str | None
    moq: float | None
    case_pack: float | None
    country: str | None
    contact_email: str | None


_PAYMENT_TERMS_POOL = ["Net 30", "Net 30", "Net 30", "Net 45", "Net 60"]
_COUNTRY_POOL = ["USA", "USA", "USA", "Canada", "Mexico", "China", "Vietnam"]


def _stable_hash_int(s: str, salt: str = "") -> int:
    h = hashlib.md5((salt + s).encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def _supplier_id_from_name(name: str) -> str:
    """Deterministic supplier_id from a free-form supplier name."""
    if not name:
        return "SUP_UNKNOWN"
    cleaned = "".join(c.upper() if c.isalnum() else "_" for c in name)
    cleaned = "_".join(filter(None, cleaned.split("_")))[:24]
    h = _stable_hash_int(name)
    return f"SUP_{cleaned}_{h % 10_000:04d}"


def derive_suppliers_from_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Heuristically derive a suppliers table from a panel.

    Used when no suppliers.csv is provided. MOQ/case-pack/payment terms are
    seeded deterministically from supplier name so the table is stable across reloads.
    """
    if "supplier" not in panel.columns or panel["supplier"].isna().all():
        return pd.DataFrame(columns=[
            "supplier_id", "name", "contact_email", "country",
            "payment_terms", "default_lead_time_days", "lead_time_std_days",
            "moq", "case_pack", "notes",
        ])

    grouped = panel.dropna(subset=["supplier"]).groupby("supplier")
    rows: list[dict] = []
    for name, sub in grouped:
        if name is None or str(name).strip() == "":
            continue
        h = _stable_hash_int(str(name))
        lt_series = sub["lead_time_days"].dropna() if "lead_time_days" in sub.columns else pd.Series(dtype=float)
        lt_mean = float(lt_series.mean()) if not lt_series.empty else 14.0
        lt_std = float(lt_series.std(ddof=0)) if len(lt_series) > 1 else max(lt_mean * 0.2, 0.5)
        avg_demand = float(sub["demand"].mean()) if "demand" in sub.columns else 1.0
        moq = float([12, 24, 50, 100, 144, 288, 500][h % 7])
        case_pack = float([1, 6, 12, 24, 48][(h // 7) % 5])
        terms = _PAYMENT_TERMS_POOL[h % len(_PAYMENT_TERMS_POOL)]
        country = _COUNTRY_POOL[(h // 13) % len(_COUNTRY_POOL)]
        slug = "".join(c for c in str(name).lower() if c.isalnum() or c in "-_")[:18] or "vendor"
        rows.append({
            "supplier_id": _supplier_id_from_name(str(name)),
            "name": str(name),
            "contact_email": f"orders@{slug}.example.com",
            "country": country,
            "payment_terms": terms,
            "default_lead_time_days": round(lt_mean, 2),
            "lead_time_std_days": round(lt_std, 2),
            "moq": moq,
            "case_pack": case_pack,
            "notes": "",
        })
    return pd.DataFrame(rows)


def parse_payment_terms_days(terms: str | None) -> int:
    """Extract Net days from strings like 'Net 30', '2/10 Net 30'. Defaults to 30."""
    if not terms:
        return 30
    t = terms.lower()
    if "net" in t:
        tail = t.split("net", 1)[1].strip()
        digits = "".join(c for c in tail if c.isdigit())
        if digits:
            return int(digits[:3])
    digits = "".join(c for c in t if c.isdigit())
    return int(digits[:3]) if digits else 30


def bayesian_lead_time_posterior(
    prior_mean: float, prior_std: float, observed: list[float], prior_strength: float = 4.0
) -> tuple[float, float]:
    """Gamma-distributed lead-time with empirical Bayes update.

    Combines a prior (parameterized by mean+std) with observed lead-times via
    a normal-approximation conjugate update. Returns (posterior_mean, posterior_std).
    """
    if prior_std <= 0:
        prior_std = max(prior_mean * 0.2, 0.5)
    if not observed:
        return prior_mean, prior_std
    observed_arr = np.asarray(observed, dtype=float)
    n = len(observed_arr)
    obs_mean = float(observed_arr.mean())
    obs_var = float(observed_arr.var(ddof=0)) if n > 1 else prior_std**2

    prior_var = prior_std**2
    obs_var_eff = max(obs_var, 1e-6)

    w_prior = prior_strength / prior_var
    w_obs = n / obs_var_eff
    posterior_mean = (w_prior * prior_mean + w_obs * obs_mean) / (w_prior + w_obs)
    posterior_var = 1.0 / (w_prior + w_obs)
    return float(posterior_mean), float(math.sqrt(posterior_var))


def compute_supplier_scorecards(
    conn: duckdb.DuckDBPyConnection,
) -> list[SupplierScorecard]:
    """Aggregate scorecard metrics from suppliers + receipts + panel."""
    suppliers = conn.execute("SELECT * FROM suppliers").fetchdf()
    if suppliers.empty:
        return []

    panel_agg = conn.execute("""
        SELECT supplier, COUNT(DISTINCT sku_id) AS n_skus,
               COALESCE(SUM(demand * unit_price), 0) AS revenue_total,
               COUNT(*) AS n_rows,
               MIN(date) AS d_min, MAX(date) AS d_max
        FROM panel
        WHERE supplier IS NOT NULL
        GROUP BY supplier
    """).fetchdf()

    by_name = {row["supplier"]: row for _, row in panel_agg.iterrows()}

    receipts = conn.execute("SELECT * FROM receipts").fetchdf()
    receipts_by_supplier = receipts.groupby("supplier_id") if not receipts.empty else None

    scorecards: list[SupplierScorecard] = []
    for _, sup in suppliers.iterrows():
        rev = 0.0
        n_skus = 0
        n_rows = 0
        d_min = None
        d_max = None
        prow = by_name.get(sup["name"])
        if prow is not None:
            rev = float(prow["revenue_total"])
            n_skus = int(prow["n_skus"])
            n_rows = int(prow["n_rows"])
            d_min = prow["d_min"]
            d_max = prow["d_max"]
        annual = rev
        if d_min is not None and d_max is not None and n_rows > 0:
            try:
                span_days = max(1, (pd.Timestamp(d_max) - pd.Timestamp(d_min)).days)
                annual = rev * 365.0 / span_days
            except Exception:
                annual = rev

        on_time = None
        in_full = None
        otif = None
        n_receipts = 0
        avg_lt = None
        std_lt = None
        post_mean = None
        post_std = None
        if receipts_by_supplier is not None and sup["supplier_id"] in receipts_by_supplier.groups:
            r = receipts_by_supplier.get_group(sup["supplier_id"])
            n_receipts = int(len(r))
            actual = (pd.to_datetime(r["received_date"]) - pd.to_datetime(r["ordered_date"])).dt.days
            actual = actual.dropna()
            if not actual.empty:
                avg_lt = float(actual.mean())
                std_lt = float(actual.std(ddof=0)) if len(actual) > 1 else 0.0
                post_mean, post_std = bayesian_lead_time_posterior(
                    float(sup["default_lead_time_days"] or 14.0),
                    float(sup["lead_time_std_days"] or 2.0),
                    list(actual.astype(float)),
                )
            on_time_mask = (pd.to_datetime(r["received_date"]) <= pd.to_datetime(r["expected_date"]))
            on_time = float(on_time_mask.mean() * 100.0) if not on_time_mask.empty else None
            in_full_mask = (r["received_qty"] >= r["ordered_qty"] * 0.99)
            in_full = float(in_full_mask.mean() * 100.0) if not in_full_mask.empty else None
            otif_mask = on_time_mask & in_full_mask
            otif = float(otif_mask.mean() * 100.0) if not otif_mask.empty else None

        scorecards.append(SupplierScorecard(
            supplier_id=str(sup["supplier_id"]),
            name=str(sup["name"]),
            n_skus=n_skus,
            annual_revenue=float(annual),
            avg_lead_time_days=avg_lt,
            lead_time_std_days=std_lt,
            leadtime_posterior_mean=post_mean,
            leadtime_posterior_std=post_std,
            on_time_pct=on_time,
            in_full_pct=in_full,
            otif_pct=otif,
            n_receipts=n_receipts,
            payment_terms=str(sup["payment_terms"]) if sup["payment_terms"] is not None else None,
            moq=float(sup["moq"]) if sup["moq"] is not None and not pd.isna(sup["moq"]) else None,
            case_pack=float(sup["case_pack"]) if sup["case_pack"] is not None and not pd.isna(sup["case_pack"]) else None,
            country=str(sup["country"]) if sup["country"] is not None else None,
            contact_email=str(sup["contact_email"]) if sup["contact_email"] is not None else None,
        ))
    scorecards.sort(key=lambda s: s.annual_revenue, reverse=True)
    return scorecards


def get_supplier_detail(conn: duckdb.DuckDBPyConnection, supplier_id: str) -> dict | None:
    """Return full detail for a single supplier including receipts."""
    sup = conn.execute("SELECT * FROM suppliers WHERE supplier_id = ?", [supplier_id]).fetchone()
    if sup is None:
        return None
    cols = [d[0] for d in conn.description]
    sup_dict = dict(zip(cols, sup))
    receipts = conn.execute(
        "SELECT * FROM receipts WHERE supplier_id = ? ORDER BY received_date",
        [supplier_id]
    ).fetchdf()
    sku_count = conn.execute(
        "SELECT COUNT(DISTINCT sku_id) FROM panel WHERE supplier = ?",
        [sup_dict["name"]]
    ).fetchone()[0]

    actual_lts: list[float] = []
    if not receipts.empty:
        diffs = (pd.to_datetime(receipts["received_date"]) - pd.to_datetime(receipts["ordered_date"])).dt.days
        actual_lts = [float(d) for d in diffs.dropna().tolist()]

    post_mean = post_std = None
    if actual_lts:
        post_mean, post_std = bayesian_lead_time_posterior(
            float(sup_dict["default_lead_time_days"] or 14.0),
            float(sup_dict["lead_time_std_days"] or 2.0),
            actual_lts,
        )

    return {
        "supplier_id": sup_dict["supplier_id"],
        "name": sup_dict["name"],
        "contact_email": sup_dict["contact_email"],
        "country": sup_dict["country"],
        "payment_terms": sup_dict["payment_terms"],
        "default_lead_time_days": sup_dict["default_lead_time_days"],
        "lead_time_std_days": sup_dict["lead_time_std_days"],
        "moq": sup_dict["moq"],
        "case_pack": sup_dict["case_pack"],
        "notes": sup_dict["notes"],
        "n_skus": int(sku_count),
        "leadtime_posterior_mean": post_mean,
        "leadtime_posterior_std": post_std,
        "actual_lead_times": actual_lts,
        "receipts": [
            {
                "receipt_id": r["receipt_id"],
                "sku_id": r["sku_id"],
                "ordered_date": r["ordered_date"].isoformat() if hasattr(r["ordered_date"], "isoformat") else str(r["ordered_date"]),
                "expected_date": r["expected_date"].isoformat() if hasattr(r["expected_date"], "isoformat") else str(r["expected_date"]),
                "received_date": r["received_date"].isoformat() if hasattr(r["received_date"], "isoformat") else str(r["received_date"]),
                "ordered_qty": float(r["ordered_qty"]),
                "received_qty": float(r["received_qty"]),
            }
            for _, r in receipts.iterrows()
        ],
    }
