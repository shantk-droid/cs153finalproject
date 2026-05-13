"""Shopify orders-export connector.

Shopify Admin > Orders > Export emits a wide CSV with one row per *line item*. We detect it
by the presence of the canonical "Lineitem sku" + "Created at" + "Financial Status" columns,
then transform to the inventory panel format (one row per sku × date with rolled-up demand).

Out-of-scope on purpose:
- Webhook ingestion (would need OAuth + storage; this is CSV-only)
- Multi-location inventory (Shopify CSV is location-aware via "Location" column, but most
  small merchants run a single location; we sum across locations for v1)
- Refunds/returns (rows with `Refunded Amount > 0` are partially excluded — we use
  Financial Status filter, which catches cancelled+voided but not partial refunds)
"""

from __future__ import annotations

import pandas as pd

# Columns that must all be present for us to confidently classify a CSV as Shopify orders.
# Picked to be unique to Shopify's export (the "Lineitem" prefix is very distinctive).
SHOPIFY_REQUIRED_COLS = {"Lineitem sku", "Lineitem quantity", "Created at", "Financial Status"}

# Columns we'd love to have but can fall back without.
SHOPIFY_OPTIONAL_COLS = {"Lineitem price", "Lineitem name", "Lineitem variant title"}

# Financial Status values that mean "don't count this as demand".
EXCLUDED_FINANCIAL_STATUSES = {"voided", "refunded", "cancelled", "canceled"}


def detect_shopify(df: pd.DataFrame) -> bool:
    """Return True if df looks like a Shopify orders export.

    Matching is by column-name set, not heuristic — Shopify's columns are stable and
    unambiguous. False positives would be expensive (transforming a non-Shopify file
    would silently produce bad data) so we keep the bar high.
    """
    if df is None or df.empty:
        return False
    cols = set(df.columns)
    return SHOPIFY_REQUIRED_COLS.issubset(cols)


def transform_shopify_to_panel(df: pd.DataFrame) -> pd.DataFrame:
    """Roll up Shopify line-item rows into the canonical SKU panel.

    Returns a DataFrame with columns sku_id, date, demand, unit_price, supplier, category
    — the same canonical schema other ingestion paths produce. Dates are normalized to
    midnight UTC; unit_price is the volume-weighted mean of Lineitem price across the day.

    Filters applied:
    - Drop rows where Financial Status ∈ EXCLUDED_FINANCIAL_STATUSES
    - Drop rows where Lineitem sku is empty/null (orphan line items, like shipping fees)
    - Drop rows where Lineitem quantity is non-positive (refunds appear as negatives)
    """
    if not detect_shopify(df):
        raise ValueError("input does not look like a Shopify orders export")

    work = df.copy()

    # Filter excluded statuses (case-insensitive)
    if "Financial Status" in work.columns:
        status_lower = work["Financial Status"].astype(str).str.strip().str.lower()
        work = work[~status_lower.isin(EXCLUDED_FINANCIAL_STATUSES)]

    # Drop empty SKUs (e.g., shipping line items, custom products without SKU)
    work = work[work["Lineitem sku"].notna() & (work["Lineitem sku"].astype(str).str.strip() != "")]

    # Drop non-positive quantities (refunds/returns)
    work["Lineitem quantity"] = pd.to_numeric(work["Lineitem quantity"], errors="coerce")
    work = work[work["Lineitem quantity"] > 0]

    if work.empty:
        # Surface as empty panel; the upload route will catch this with a 400.
        return pd.DataFrame(columns=["sku_id", "date", "demand", "unit_price", "supplier", "category"])

    # Normalize the date — Shopify uses "2026-05-13 14:23:00 -0700" format with TZ
    work["_date"] = pd.to_datetime(work["Created at"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    work = work.dropna(subset=["_date"])
    work["sku_id"] = work["Lineitem sku"].astype(str).str.strip()

    # Group: sku × date → sum(quantity), weighted-mean(price)
    work["Lineitem price"] = pd.to_numeric(work.get("Lineitem price"), errors="coerce")
    work["_price_x_qty"] = work["Lineitem price"].fillna(0) * work["Lineitem quantity"]

    grouped = work.groupby(["sku_id", "_date"], dropna=False).agg(
        demand=("Lineitem quantity", "sum"),
        _price_qty_sum=("_price_x_qty", "sum"),
        _qty_sum=("Lineitem quantity", "sum"),
    ).reset_index()
    grouped["unit_price"] = (grouped["_price_qty_sum"] / grouped["_qty_sum"]).round(4)
    grouped = grouped[["sku_id", "_date", "demand", "unit_price"]].rename(columns={"_date": "date"})

    # Lineitem name → category fallback (use the product name as a coarse category).
    if "Lineitem name" in work.columns:
        name_per_sku = work.groupby("sku_id")["Lineitem name"].first()
        grouped["category"] = grouped["sku_id"].map(name_per_sku)
    else:
        grouped["category"] = None

    # Shopify has no per-line supplier column on the orders export, so we mark all rows
    # as supplier "shopify" — the user can override post-confirm if they want.
    grouped["supplier"] = "shopify"

    grouped["date"] = pd.to_datetime(grouped["date"])
    return grouped[["sku_id", "date", "demand", "unit_price", "supplier", "category"]]


def shopify_suggested_mapping() -> dict[str, str]:
    """When we've already transformed to canonical columns, the suggested mapping is the
    identity. Surfaced by the upload route so the ColumnMapper UI auto-fills without
    making the user click through 9 dropdowns."""
    return {
        "sku_id": "sku_id",
        "date": "date",
        "demand": "demand",
        "unit_price": "unit_price",
        "supplier": "supplier",
        "category": "category",
    }


def generate_sample_shopify_csv(n_skus: int = 12, n_days: int = 60, seed: int = 7) -> pd.DataFrame:
    """Synthesize a Shopify-like orders export for demo + tests. Returns a DataFrame ready
    to be written as CSV — has all SHOPIFY_REQUIRED_COLS plus realistic optional ones.

    Distribution: intermittent demand (some days zero), seasonal weekday spike. ~500 line
    items across 12 SKUs and 60 days. Used by `apps/api/ingestion/sample_data/`.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    products = [
        ("COFFEE-DARK-12OZ", "Dark Roast Coffee — 12oz", 14.99),
        ("COFFEE-LIGHT-12OZ", "Light Roast Coffee — 12oz", 14.99),
        ("BEANS-SINGLE-1LB", "Single-Origin Beans — 1lb", 22.50),
        ("MUG-CERAMIC-12OZ", "Ceramic Mug — 12oz", 16.00),
        ("MUG-TRAVEL-16OZ", "Travel Mug — 16oz", 28.00),
        ("FILTER-100PK", "Paper Filters — 100ct", 8.50),
        ("KETTLE-GOOSENECK", "Gooseneck Kettle", 89.99),
        ("GRINDER-MANUAL", "Manual Burr Grinder", 65.00),
        ("CARAFE-GLASS", "Glass Carafe", 32.00),
        ("ESPRESSO-12OZ", "Espresso Blend — 12oz", 16.99),
        ("DECAF-12OZ", "Decaf Roast — 12oz", 14.99),
        ("COLD-BREW-32OZ", "Cold Brew Concentrate — 32oz", 18.50),
    ][:n_skus]

    rows: list[dict] = []
    order_id = 1000
    start = pd.Timestamp("2026-01-01")
    for d in range(n_days):
        date = start + pd.Timedelta(days=d)
        # Weekday spike — Sat+Sun get more orders
        weekday_mult = 1.5 if date.weekday() >= 5 else 1.0
        for sku, name, price in products:
            # Intermittent demand: 60% chance of any sale that day
            if rng.random() > 0.6 * weekday_mult:
                continue
            qty = int(rng.integers(1, 5))
            # 5% chance the order ends up cancelled — exercises the filter
            status = "cancelled" if rng.random() < 0.05 else "paid"
            rows.append({
                "Name": f"#{order_id}",
                "Created at": date.strftime("%Y-%m-%d %H:%M:%S -0800"),
                "Financial Status": status,
                "Lineitem quantity": qty,
                "Lineitem name": name,
                "Lineitem sku": sku,
                "Lineitem price": price,
                "Currency": "USD",
            })
            order_id += 1
    return pd.DataFrame(rows)


if __name__ == "__main__":
    # Usage: python -m apps.api.ingestion.connectors.shopify > sample.csv
    df = generate_sample_shopify_csv()
    import sys
    df.to_csv(sys.stdout, index=False)
