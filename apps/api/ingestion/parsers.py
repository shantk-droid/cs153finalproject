"""File parsing — CSV/TSV/XLSX/XLS into pandas DataFrames.

Excel quirks handled:
- Skip blank rows above the header (common with title/merged-header sheets).
- Multi-sheet workbooks: pick the first sheet with >= 50 rows containing demand-like columns;
  expose all sheet names so the user can override.
- Excel datetime objects are normalized to naive timestamps (TZ stripped).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pandas as pd

DEMAND_LIKE_HEADERS = {"demand", "qty", "quantity", "units", "sales", "sold", "shipped"}


@dataclass
class ParseResult:
    df: pd.DataFrame
    sheet_names: list[str] | None
    selected_sheet: str | None


def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            try:
                df[col] = df[col].dt.tz_localize(None)
            except (TypeError, AttributeError):
                pass
    return df


def _detect_csv_separator(sample: str) -> str:
    counts = {sep: sample.count(sep) for sep in (",", "\t", ";", "|")}
    return max(counts, key=counts.get) if max(counts.values()) > 0 else ","


def parse_csv(source: BinaryIO | bytes | str) -> pd.DataFrame:
    """Parse CSV/TSV bytes/file. Auto-detects separator from the first 4KB."""
    if isinstance(source, (bytes, bytearray)):
        sample = source[:4096].decode("utf-8", errors="replace")
        sep = _detect_csv_separator(sample)
        return _strip_tz(pd.read_csv(io.BytesIO(source), sep=sep))
    if isinstance(source, str) or isinstance(source, Path):
        with open(source, "rb") as f:
            data = f.read()
        return parse_csv(data)
    data = source.read()
    return parse_csv(data)


def _looks_like_panel(df: pd.DataFrame) -> bool:
    if len(df) < 5:
        return False
    cols = {c.lower() for c in df.columns.astype(str)}
    return bool(cols & DEMAND_LIKE_HEADERS)


def _read_excel_sheet_with_blank_row_skip(buf: BinaryIO | bytes, sheet: str | int = 0, max_skip: int = 5) -> pd.DataFrame:
    """Excel files often have title rows above the header. Skip up to `max_skip` blank rows."""
    if isinstance(buf, (bytes, bytearray)):
        buf = io.BytesIO(buf)
    for skip in range(0, max_skip + 1):
        buf.seek(0) if hasattr(buf, "seek") else None
        try:
            df = pd.read_excel(buf, sheet_name=sheet, skiprows=skip, engine="openpyxl")
        except Exception:
            continue
        if not df.columns.astype(str).str.startswith("Unnamed").all():
            return _strip_tz(df)
    buf.seek(0) if hasattr(buf, "seek") else None
    return _strip_tz(pd.read_excel(buf, sheet_name=sheet, engine="openpyxl"))


def parse_xlsx(source: BinaryIO | bytes, sheet_override: str | None = None) -> ParseResult:
    """Parse XLSX bytes. If multi-sheet, pick the first 'panel-like' sheet.

    Returns the DataFrame plus the sheet name list (so the UI can show a picker).
    """
    if isinstance(source, (bytes, bytearray)):
        buf = io.BytesIO(source)
    else:
        buf = io.BytesIO(source.read())

    xls = pd.ExcelFile(buf, engine="openpyxl")
    sheet_names = list(xls.sheet_names)

    if sheet_override is not None:
        if sheet_override not in sheet_names:
            raise ValueError(f"sheet '{sheet_override}' not in {sheet_names}")
        df = _read_excel_sheet_with_blank_row_skip(io.BytesIO(buf.getvalue()), sheet_override)
        return ParseResult(df=df, sheet_names=sheet_names, selected_sheet=sheet_override)

    selected = sheet_names[0]
    for s in sheet_names:
        candidate = _read_excel_sheet_with_blank_row_skip(io.BytesIO(buf.getvalue()), s)
        if _looks_like_panel(candidate):
            selected = s
            break

    df = _read_excel_sheet_with_blank_row_skip(io.BytesIO(buf.getvalue()), selected)
    return ParseResult(df=df, sheet_names=sheet_names, selected_sheet=selected)


def parse_upload(filename: str, content: bytes, sheet_override: str | None = None) -> ParseResult:
    """Top-level entry: dispatch to csv/xlsx by file extension."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext in {"csv", "tsv", "txt"}:
        return ParseResult(df=parse_csv(content), sheet_names=None, selected_sheet=None)
    if ext in {"xlsx", "xlsm"}:
        return parse_xlsx(content, sheet_override=sheet_override)
    if ext == "xls":
        raise ValueError("Legacy .xls is not supported. Please re-save as .xlsx.")
    raise ValueError(f"Unsupported file extension: .{ext}")
