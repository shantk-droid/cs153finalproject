from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import duckdb

from apps.api.config import get_settings


def dataset_path(dataset_id: str) -> Path:
    base = get_settings().data_path
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{dataset_id}.duckdb"


@contextmanager
def open_dataset(dataset_id: str, read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    path = dataset_path(dataset_id)
    if read_only and not path.exists():
        raise FileNotFoundError(f"Dataset {dataset_id} does not exist")
    conn = duckdb.connect(str(path), read_only=read_only)
    try:
        yield conn
    finally:
        conn.close()


def ensure_panel_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS panel (
            sku_id VARCHAR NOT NULL,
            date DATE NOT NULL,
            demand DOUBLE NOT NULL,
            on_hand DOUBLE,
            lead_time_days DOUBLE,
            unit_cost DOUBLE,
            unit_price DOUBLE,
            supplier VARCHAR,
            category VARCHAR,
            PRIMARY KEY (sku_id, date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_panel_sku ON panel(sku_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_panel_date ON panel(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_panel_category ON panel(category)")


def ensure_supplier_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            supplier_id VARCHAR PRIMARY KEY,
            name VARCHAR,
            contact_email VARCHAR,
            country VARCHAR,
            payment_terms VARCHAR,
            default_lead_time_days DOUBLE,
            lead_time_std_days DOUBLE,
            moq DOUBLE,
            case_pack DOUBLE,
            notes VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS receipts (
            receipt_id VARCHAR PRIMARY KEY,
            sku_id VARCHAR NOT NULL,
            supplier_id VARCHAR NOT NULL,
            ordered_date DATE,
            expected_date DATE,
            received_date DATE,
            ordered_qty DOUBLE,
            received_qty DOUBLE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_receipts_sku ON receipts(sku_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_receipts_supplier ON receipts(supplier_id)")


def ensure_purchase_order_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS purchase_orders (
            po_id VARCHAR PRIMARY KEY,
            supplier_id VARCHAR,
            status VARCHAR NOT NULL,
            created_at TIMESTAMP NOT NULL,
            needed_by DATE,
            total_cost DOUBLE,
            total_units DOUBLE,
            expedite_flag BOOLEAN,
            joint_replen_group VARCHAR,
            assigned_to VARCHAR,
            approved_by VARCHAR,
            notes VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS po_lines (
            po_id VARCHAR NOT NULL,
            sku_id VARCHAR NOT NULL,
            qty DOUBLE NOT NULL,
            unit_cost DOUBLE,
            PRIMARY KEY (po_id, sku_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS po_status_log (
            po_id VARCHAR NOT NULL,
            from_status VARCHAR,
            to_status VARCHAR NOT NULL,
            by_user VARCHAR,
            "at" TIMESTAMP NOT NULL,
            note VARCHAR
        )
    """)


def ensure_all_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Initialize all tables on a fresh dataset."""
    ensure_panel_table(conn)
    ensure_supplier_tables(conn)
    ensure_purchase_order_tables(conn)
