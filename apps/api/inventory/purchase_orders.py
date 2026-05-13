"""Purchase Order CRUD + status workflow.

Status machine: drafted → approved → placed → received. From any non-`received`
state you can transition to `cancelled`. All transitions write to po_status_log.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Literal

import duckdb
import pandas as pd

from apps.api.db import open_dataset


POStatus = Literal["drafted", "approved", "placed", "received", "cancelled"]
ALLOWED_FROM: dict[str, set[str]] = {
    "drafted": set(),
    "approved": {"drafted"},
    "placed": {"approved"},
    "received": {"placed"},
    "cancelled": {"drafted", "approved", "placed"},
}


@dataclass
class POLine:
    po_id: str
    sku_id: str
    qty: float
    unit_cost: float | None


@dataclass
class POStatusLogEntry:
    from_status: str | None
    to_status: str
    by_user: str | None
    at: str
    note: str | None


@dataclass
class PurchaseOrder:
    po_id: str
    supplier_id: str | None
    supplier_name: str | None
    status: POStatus
    created_at: str
    needed_by: str | None
    total_cost: float
    total_units: float
    expedite_flag: bool
    joint_replen_group: str | None
    assigned_to: str | None
    approved_by: str | None
    notes: str | None
    lines: list[POLine]
    status_log: list[POStatusLogEntry]


def _next_po_id(conn: duckdb.DuckDBPyConnection) -> str:
    year = date.today().year
    n = conn.execute(
        "SELECT COUNT(*) FROM purchase_orders WHERE po_id LIKE ?", [f"PO-{year}-%"]
    ).fetchone()[0]
    return f"PO-{year}-{n + 1:05d}"


def _supplier_lookup(conn: duckdb.DuckDBPyConnection, supplier_id: str | None) -> str | None:
    if not supplier_id:
        return None
    row = conn.execute("SELECT name FROM suppliers WHERE supplier_id = ?", [supplier_id]).fetchone()
    return row[0] if row else None


def _hydrate_po(conn: duckdb.DuckDBPyConnection, row: tuple, columns: list[str]) -> PurchaseOrder:
    d = dict(zip(columns, row))
    lines_df = conn.execute(
        "SELECT po_id, sku_id, qty, unit_cost FROM po_lines WHERE po_id = ? ORDER BY sku_id",
        [d["po_id"]],
    ).fetchdf()
    lines = [
        POLine(
            po_id=r["po_id"],
            sku_id=r["sku_id"],
            qty=float(r["qty"]),
            unit_cost=float(r["unit_cost"]) if pd.notna(r["unit_cost"]) else None,
        )
        for _, r in lines_df.iterrows()
    ]
    log_df = conn.execute(
        'SELECT from_status, to_status, by_user, "at", note FROM po_status_log WHERE po_id = ? ORDER BY "at"',
        [d["po_id"]],
    ).fetchdf()
    log = [
        POStatusLogEntry(
            from_status=r["from_status"] if pd.notna(r["from_status"]) else None,
            to_status=r["to_status"],
            by_user=r["by_user"] if pd.notna(r["by_user"]) else None,
            at=pd.Timestamp(r["at"]).isoformat(),
            note=r["note"] if pd.notna(r["note"]) else None,
        )
        for _, r in log_df.iterrows()
    ]
    return PurchaseOrder(
        po_id=d["po_id"],
        supplier_id=d["supplier_id"],
        supplier_name=_supplier_lookup(conn, d["supplier_id"]),
        status=d["status"],
        created_at=pd.Timestamp(d["created_at"]).isoformat() if d["created_at"] is not None else "",
        needed_by=d["needed_by"].isoformat() if d["needed_by"] is not None and hasattr(d["needed_by"], "isoformat") else (str(d["needed_by"]) if d["needed_by"] is not None else None),
        total_cost=float(d["total_cost"] or 0.0),
        total_units=float(d["total_units"] or 0.0),
        expedite_flag=bool(d["expedite_flag"]),
        joint_replen_group=d["joint_replen_group"],
        assigned_to=d["assigned_to"],
        approved_by=d["approved_by"],
        notes=d["notes"],
        lines=lines,
        status_log=log,
    )


def list_purchase_orders(dataset_id: str, status: str | None = None) -> list[PurchaseOrder]:
    with open_dataset(dataset_id, read_only=True) as conn:
        if status:
            df = conn.execute(
                "SELECT * FROM purchase_orders WHERE status = ? ORDER BY created_at DESC", [status]
            ).fetchdf()
        else:
            df = conn.execute("SELECT * FROM purchase_orders ORDER BY created_at DESC").fetchdf()
        if df.empty:
            return []
        cols = list(df.columns)
        return [_hydrate_po(conn, tuple(row), cols) for row in df.itertuples(index=False, name=None)]


def get_purchase_order(dataset_id: str, po_id: str) -> PurchaseOrder | None:
    with open_dataset(dataset_id, read_only=True) as conn:
        df = conn.execute("SELECT * FROM purchase_orders WHERE po_id = ?", [po_id]).fetchdf()
        if df.empty:
            return None
        cols = list(df.columns)
        return _hydrate_po(conn, tuple(df.iloc[0].tolist()), cols)


def draft_purchase_order_from_sku(
    dataset_id: str,
    sku_id: str,
    qty: float,
    notes: str | None = None,
) -> PurchaseOrder:
    """Draft a single-line PO for one SKU. Looks up supplier/cost from the panel."""
    return draft_purchase_order_multi_line(
        dataset_id,
        supplier_id=None,
        supplier_name=None,
        lines=[(sku_id, qty)],
        notes=notes,
        log_note="drafted from reorder queue",
    )


def draft_purchase_order_multi_line(
    dataset_id: str,
    *,
    supplier_id: str | None = None,
    supplier_name: str | None = None,
    lines: list[tuple[str, float]],
    expedite_flag: bool = False,
    joint_replen_group: str | None = None,
    notes: str | None = None,
    log_note: str | None = None,
) -> PurchaseOrder:
    """Draft a multi-line PO. Looks up unit_cost + supplier metadata from the panel/suppliers
    table. If supplier_id is not given, derives it from the first SKU's supplier in the panel.

    Drops any sku_id that doesn't exist in the panel (logged in the PO's notes).
    """
    if not lines:
        raise ValueError("at least one line required")

    with open_dataset(dataset_id) as conn:
        valid_lines: list[tuple[str, float, float | None]] = []
        skipped: list[str] = []
        for sku_id, qty in lines:
            sku_id = sku_id.strip().upper()
            row = conn.execute(
                "SELECT supplier, unit_cost, lead_time_days FROM panel WHERE sku_id = ? "
                "ORDER BY date DESC LIMIT 1",
                [sku_id],
            ).fetchone()
            if row is None:
                skipped.append(sku_id)
                continue
            sup_panel, uc, lt = row
            unit_cost = float(uc) if uc is not None and not pd.isna(uc) else None
            valid_lines.append((sku_id, float(qty), unit_cost))
            if supplier_id is None:
                # derive from first valid SKU
                if supplier_name is None:
                    supplier_name = sup_panel
                sup_row = conn.execute(
                    "SELECT supplier_id FROM suppliers WHERE name = ?", [sup_panel]
                ).fetchone()
                if sup_row:
                    supplier_id = sup_row[0]
        if not valid_lines:
            raise ValueError("no valid SKUs in line list")

        # default needed_by uses the first valid SKU's lead time as a proxy
        first_sku = valid_lines[0][0]
        lt_row = conn.execute(
            "SELECT lead_time_days FROM panel WHERE sku_id = ? AND lead_time_days IS NOT NULL "
            "ORDER BY date DESC LIMIT 1",
            [first_sku],
        ).fetchone()
        lt = float(lt_row[0]) if lt_row and lt_row[0] is not None else 14.0

        po_id = _next_po_id(conn)
        now = datetime.utcnow()
        needed_by = (date.today() + timedelta(days=int(lt) + 7)).isoformat()
        total_units = sum(q for _, q, _ in valid_lines)
        total_cost = sum(q * (uc or 0.0) for _, q, uc in valid_lines)

        merged_notes = notes
        if skipped:
            skip_note = f"skipped invalid SKUs: {', '.join(skipped)}"
            merged_notes = f"{notes}\n{skip_note}" if notes else skip_note

        conn.execute(
            """INSERT INTO purchase_orders
               (po_id, supplier_id, status, created_at, needed_by, total_cost, total_units,
                expedite_flag, joint_replen_group, assigned_to, approved_by, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [po_id, supplier_id, "drafted", now, needed_by, total_cost, total_units,
             bool(expedite_flag), joint_replen_group, None, None, merged_notes],
        )
        for sid, qty, unit_cost in valid_lines:
            conn.execute(
                "INSERT INTO po_lines (po_id, sku_id, qty, unit_cost) VALUES (?, ?, ?, ?)",
                [po_id, sid, qty, unit_cost],
            )
        conn.execute(
            'INSERT INTO po_status_log (po_id, from_status, to_status, by_user, "at", note) VALUES (?, ?, ?, ?, ?, ?)',
            [po_id, None, "drafted", None, now, log_note or "drafted"],
        )
        df = conn.execute("SELECT * FROM purchase_orders WHERE po_id = ?", [po_id]).fetchdf()
        cols = list(df.columns)
        return _hydrate_po(conn, tuple(df.iloc[0].tolist()), cols)


def update_purchase_order(
    dataset_id: str,
    po_id: str,
    *,
    status: POStatus | None = None,
    assigned_to: str | None = None,
    approved_by: str | None = None,
    notes: str | None = None,
    by_user: str | None = None,
    transition_note: str | None = None,
) -> PurchaseOrder:
    with open_dataset(dataset_id) as conn:
        existing_df = conn.execute("SELECT * FROM purchase_orders WHERE po_id = ?", [po_id]).fetchdf()
        if existing_df.empty:
            raise ValueError(f"PO {po_id} not found")
        existing = existing_df.iloc[0].to_dict()
        cur_status = existing["status"]

        if status and status != cur_status:
            if cur_status not in ALLOWED_FROM[status]:
                raise ValueError(
                    f"cannot transition {cur_status} → {status}. "
                    f"Allowed predecessors: {sorted(ALLOWED_FROM[status])}"
                )
            now = datetime.utcnow()
            user = by_user or assigned_to or approved_by or "anonymous"
            conn.execute(
                'INSERT INTO po_status_log (po_id, from_status, to_status, by_user, "at", note) VALUES (?, ?, ?, ?, ?, ?)',
                [po_id, cur_status, status, user, now, transition_note],
            )
            conn.execute("UPDATE purchase_orders SET status = ? WHERE po_id = ?", [status, po_id])

        if assigned_to is not None:
            conn.execute("UPDATE purchase_orders SET assigned_to = ? WHERE po_id = ?", [assigned_to or None, po_id])
        if approved_by is not None:
            conn.execute("UPDATE purchase_orders SET approved_by = ? WHERE po_id = ?", [approved_by or None, po_id])
        if notes is not None:
            conn.execute("UPDATE purchase_orders SET notes = ? WHERE po_id = ?", [notes or None, po_id])

        df = conn.execute("SELECT * FROM purchase_orders WHERE po_id = ?", [po_id]).fetchdf()
        cols = list(df.columns)
        return _hydrate_po(conn, tuple(df.iloc[0].tolist()), cols)


def delete_purchase_order(dataset_id: str, po_id: str) -> None:
    with open_dataset(dataset_id) as conn:
        conn.execute("DELETE FROM po_lines WHERE po_id = ?", [po_id])
        conn.execute("DELETE FROM po_status_log WHERE po_id = ?", [po_id])
        conn.execute("DELETE FROM purchase_orders WHERE po_id = ?", [po_id])
