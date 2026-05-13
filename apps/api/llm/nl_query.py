"""Natural-language → DuckDB SELECT with schema allowlist.

Defense-in-depth:
1. **Prompt**: LLM is told to emit ONLY a SELECT against named tables/columns.
2. **Validation** (this module): regex-based denylist of dangerous keywords, single-statement,
   length cap. Catches the common cases — DROP, INSERT, ATTACH, COPY, PRAGMA, read_csv()…
3. **Execution**: DuckDB connection opened with `read_only=True` (via the existing
   open_dataset helper). DuckDB's own parser rejects anything it doesn't recognize as
   read-only DML.

The LLM-emitted SQL is also returned to the caller for inspection so the agent (or a human
auditor) can sanity-check before acting on results.

Tables exposed:
  - panel: sku_id, date, demand, on_hand, lead_time_days, unit_cost, unit_price, supplier, category
  - suppliers: supplier_id, supplier_name, payment_terms_days, on_time_rate, lead_time_cv
  - skus: sku_id, category, supplier, abc_class, xyz_class (computed view; see _ensure_views)

Out of scope on purpose:
  - JOINs across foreign tables. Even on the allowlisted tables, the agent should usually
    just query `panel` — the others rarely add value.
  - Window functions. Useful but tricky to validate; not exposed in v1.
"""

from __future__ import annotations

import re

import anthropic

from apps.api.config import get_settings
from apps.api.db import open_dataset
from apps.api.llm.cost_ledger import add_spend
from apps.api.llm.router import HAIKU_INPUT_PRICE_PER_M, HAIKU_OUTPUT_PRICE_PER_M

NL_QUERY_MODEL = "claude-haiku-4-5-20251001"
NL_QUERY_MAX_TOKENS = 512
MAX_SQL_LENGTH = 2000
MAX_ROWS_RETURNED = 500

ALLOWED_TABLES = {"panel", "suppliers", "skus"}
ALLOWED_COLUMNS = {
    "sku_id", "date", "demand", "on_hand", "lead_time_days",
    "unit_cost", "unit_price", "supplier", "category",
    "supplier_id", "supplier_name", "payment_terms_days",
    "on_time_rate", "lead_time_cv",
    "abc_class", "xyz_class",
}

# Keywords or function names that MUST NOT appear anywhere in the LLM-emitted SQL.
# Lowercase comparison. Order matters here only for ease of review.
BANNED_TOKENS = {
    # DDL
    "drop", "create", "alter", "truncate", "rename", "comment",
    # DML write
    "insert", "update", "delete", "merge", "upsert", "replace",
    # Transactions
    "begin", "commit", "rollback", "savepoint", "transaction",
    # DuckDB filesystem / loading
    "attach", "detach", "copy", "pragma", "load", "install", "secret",
    "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_blob",
    "parquet_scan", "csv_scan", "json_scan",
    # Privilege / system
    "grant", "revoke", "set", "reset", "exec", "execute", "call",
    "vacuum", "analyze", "checkpoint", "force",
    # Catalog inspection (information leakage)
    "information_schema", "duckdb_settings", "duckdb_extensions",
    "duckdb_secrets", "duckdb_functions", "duckdb_databases",
}

NL_QUERY_SYSTEM = """You translate natural-language questions about an inventory dataset
into a single read-only DuckDB SELECT statement.

Schema (the ONLY tables and columns you may reference):
  panel(sku_id, date, demand, on_hand, lead_time_days, unit_cost, unit_price, supplier, category)
  suppliers(supplier_id, supplier_name, payment_terms_days, on_time_rate, lead_time_cv)
  skus(sku_id, category, supplier, abc_class, xyz_class)

Rules:
1. Emit EXACTLY ONE SELECT statement, no semicolons (or one trailing semicolon).
2. No JOINs unless absolutely necessary; prefer querying `panel` alone.
3. No CTEs, no window functions, no subqueries unless trivial.
4. Use LIMIT to cap at 500 rows. If the user asks for "top N", use ORDER BY ... LIMIT N.
5. Never reference any column or table outside the schema above.
6. If the question can't be answered with a SELECT against this schema, reply with the single
   sentence "UNANSWERABLE: <reason>" instead of SQL.

Output: just the SQL string (or the UNANSWERABLE message). No code fences, no preamble.
"""


class NlQueryValidationError(ValueError):
    """Raised when the LLM-emitted SQL fails the safety allowlist."""


def validate_sql(sql: str) -> str:
    """Return the cleaned SQL if it passes the safety checks; else raise NlQueryValidationError.

    Public for testing — the executor calls this before hitting DuckDB.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise NlQueryValidationError("empty SQL")
    sql = sql.strip()
    if sql.lower().startswith("unanswerable"):
        raise NlQueryValidationError(sql)
    if len(sql) > MAX_SQL_LENGTH:
        raise NlQueryValidationError(f"SQL too long ({len(sql)} > {MAX_SQL_LENGTH})")
    # Strip trailing semicolon if present, reject multi-statement.
    trimmed = sql.rstrip().rstrip(";").strip()
    if ";" in trimmed:
        raise NlQueryValidationError("multi-statement SQL is not allowed")

    if not trimmed.lower().startswith("select") and not trimmed.lower().startswith("with"):
        raise NlQueryValidationError("SQL must start with SELECT")
    # Reject CTEs to keep validation simple — see Rule 3.
    if trimmed.lower().startswith("with"):
        raise NlQueryValidationError("CTEs are not allowed")

    # Token denylist scan. Lowercase whole SQL, split on non-word, check for banned tokens.
    lowered = trimmed.lower()
    tokens = set(re.findall(r"\b[a-z_][a-z0-9_]*\b", lowered))
    banned_hits = tokens & BANNED_TOKENS
    if banned_hits:
        raise NlQueryValidationError(f"SQL contains banned token(s): {sorted(banned_hits)}")

    # Heuristic table-name check. Find all words after FROM/JOIN. They must be in ALLOWED_TABLES.
    referenced_tables = set(re.findall(r"\bfrom\s+([a-z_][a-z0-9_]*)", lowered))
    referenced_tables |= set(re.findall(r"\bjoin\s+([a-z_][a-z0-9_]*)", lowered))
    if not referenced_tables:
        raise NlQueryValidationError("no FROM clause found")
    bad_tables = referenced_tables - ALLOWED_TABLES
    if bad_tables:
        raise NlQueryValidationError(f"references disallowed table(s): {sorted(bad_tables)}")

    return trimmed


def generate_sql(question: str) -> tuple[str, str, float]:
    """Ask Haiku to emit SELECT for the question. Returns (sql, rationale, cost_usd).

    Rationale is the model's preamble (if any) — we strip it before validation, but pass it
    through so the agent / UI can show it. For the strict prompt above, the model usually
    emits only SQL, so rationale is often empty.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise NlQueryValidationError("ANTHROPIC_API_KEY not set; NL-to-query unavailable")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=NL_QUERY_MODEL,
        max_tokens=NL_QUERY_MAX_TOKENS,
        system=NL_QUERY_SYSTEM,
        messages=[{"role": "user", "content": question}],
    )
    in_tokens = getattr(response.usage, "input_tokens", 0) or 0
    out_tokens = getattr(response.usage, "output_tokens", 0) or 0
    cost = in_tokens * HAIKU_INPUT_PRICE_PER_M / 1e6 + out_tokens * HAIKU_OUTPUT_PRICE_PER_M / 1e6
    if cost > 0:
        add_spend(settings.data_path, cost, context="nl_query")

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    # The model is told to emit just SQL; if it accidentally wraps in fences, strip them.
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(line for line in lines if not line.startswith("```")).strip()

    rationale = ""
    sql = text
    # If there are multiple lines, treat all but the last SELECT-starting block as rationale.
    if "\n" in text and not text.lower().startswith("select"):
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.strip().lower().startswith("select"):
                rationale = "\n".join(lines[:i]).strip()
                sql = "\n".join(lines[i:]).strip()
                break
    return sql, rationale, cost


def run_nl_query(dataset_id: str, question: str) -> dict:
    """Translate `question` to SQL, validate, execute against the dataset's panel.

    Returns: {sql, rationale, rows, columns, n_rows, truncated} on success,
              {error, sql} on validation/execution failure.
    """
    try:
        sql, rationale, _cost = generate_sql(question)
    except NlQueryValidationError as e:
        return {"error": str(e), "sql": None}
    except Exception as e:
        return {"error": f"LLM error: {type(e).__name__}: {e}", "sql": None}

    try:
        validated = validate_sql(sql)
    except NlQueryValidationError as e:
        return {"error": f"validation failed: {e}", "sql": sql, "rationale": rationale}

    # Execute against the dataset. open_dataset opens DuckDB; read_only blocks writes server-side
    # even if our regex missed something.
    try:
        with open_dataset(dataset_id, read_only=True) as conn:
            df = conn.execute(validated).fetchdf()
    except Exception as e:
        return {"error": f"execution error: {type(e).__name__}: {e}", "sql": validated, "rationale": rationale}

    truncated = False
    if len(df) > MAX_ROWS_RETURNED:
        df = df.head(MAX_ROWS_RETURNED)
        truncated = True

    # Stringify date columns for JSON.
    import pandas as pd
    out_df = df.copy()
    for c in out_df.columns:
        if pd.api.types.is_datetime64_any_dtype(out_df[c]):
            out_df[c] = out_df[c].dt.strftime("%Y-%m-%d")

    return {
        "sql": validated,
        "rationale": rationale,
        "rows": [
            {k: (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)) for k, v in row.items()}
            for row in out_df.to_dict(orient="records")
        ],
        "columns": list(out_df.columns),
        "n_rows": int(len(out_df)),
        "truncated": truncated,
    }
