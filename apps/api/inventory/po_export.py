"""Export a purchase order as CSV (ERP-friendly) or X12 850 (EDI)."""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd

from apps.api.db import open_dataset
from apps.api.inventory.purchase_orders import get_purchase_order


def export_csv(dataset_id: str, po_id: str) -> tuple[str, bytes]:
    """Return (filename, bytes) for the CSV export."""
    po = get_purchase_order(dataset_id, po_id)
    if po is None:
        raise ValueError(f"PO {po_id} not found")
    rows = []
    for line in po.lines:
        rows.append({
            "po_id": po.po_id,
            "supplier_id": po.supplier_id or "",
            "supplier_name": po.supplier_name or "",
            "needed_by": po.needed_by or "",
            "sku_id": line.sku_id,
            "qty": line.qty,
            "unit_cost": line.unit_cost if line.unit_cost is not None else 0.0,
            "line_total": (line.unit_cost or 0.0) * line.qty,
            "expedite": "Y" if po.expedite_flag else "N",
            "status": po.status,
        })
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return f"{po_id}.csv", buf.getvalue().encode("utf-8")


def export_edi850(dataset_id: str, po_id: str, sender_id: str = "INVOPT", receiver_id: str = "VENDOR") -> tuple[str, bytes]:
    """Return (filename, bytes) for an X12 EDI 850 envelope."""
    po = get_purchase_order(dataset_id, po_id)
    if po is None:
        raise ValueError(f"PO {po_id} not found")
    with open_dataset(dataset_id, read_only=True) as conn:
        sup = None
        if po.supplier_id:
            row = conn.execute(
                "SELECT name, contact_email, country FROM suppliers WHERE supplier_id = ?",
                [po.supplier_id],
            ).fetchone()
            if row:
                sup = {"name": row[0], "email": row[1], "country": row[2]}

    now = datetime.utcnow()
    date_str = now.strftime("%y%m%d")
    date_full_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M")
    ctrl_num = po.po_id.replace("-", "")[-9:].zfill(9)

    pad_l = lambda s, n: (str(s) + (" " * n))[:n]
    sender_pad = pad_l(sender_id, 15)
    receiver_pad = pad_l(receiver_id, 15)

    segments: list[str] = []

    segments.append(f"ISA*00*          *00*          *ZZ*{sender_pad}*ZZ*{receiver_pad}*{date_str}*{time_str}*U*00401*{ctrl_num}*0*P*>")
    segments.append(f"GS*PO*{sender_id}*{receiver_id}*{date_full_str}*{time_str}*1*X*004010")
    segments.append(f"ST*850*0001")
    segments.append(f"BEG*00*SA*{po.po_id}**{date_full_str}")

    if sup and sup.get("email"):
        segments.append(f"REF*EM*{sup['email']}")

    if po.needed_by:
        needed = po.needed_by.replace("-", "")
        segments.append(f"DTM*002*{needed}")

    if sup:
        segments.append(f"N1*VN*{sup['name']}")
        if sup.get("country"):
            segments.append(f"N4***{sup['country']}")

    for i, line in enumerate(po.lines, start=1):
        unit_price = f"{line.unit_cost:.2f}" if line.unit_cost is not None else "0.00"
        segments.append(f"PO1*{i}*{int(round(line.qty))}*EA*{unit_price}**VP*{line.sku_id}")

    n_lines = len(po.lines)
    se_index = len(segments) + 1
    segments.append(f"CTT*{n_lines}")
    segments.append(f"SE*{se_index + 1}*0001")
    segments.append("GE*1*1")
    segments.append(f"IEA*1*{ctrl_num}")

    body = "~\n".join(segments) + "~\n"
    return f"{po_id}.edi", body.encode("utf-8")
