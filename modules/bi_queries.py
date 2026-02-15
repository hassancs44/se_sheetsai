"""SE_SHEETSAI — Internal BI query builder and executor.

Transforms widget query_json into safe, parameterized SQL against the
BI runtime database (SQLite for now; Postgres can be added later).
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from config import BI_RUNTIME_DB_PATH


def _runtime_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(BI_RUNTIME_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _schema_columns(schema: Any) -> set:
    """Return set of column names from dataset schema_json."""
    if not schema:
        return set()
    if isinstance(schema, dict):
        cols = schema.get("columns")
        if isinstance(cols, list):
            return {str(c.get("name", c) if isinstance(c, dict) else c).strip() for c in cols if c}
        if isinstance(cols, dict):
            return set(cols.keys())
        return set()
    if isinstance(schema, list):
        return {str(c.get("name", c) if isinstance(c, dict) else c).strip() for c in schema if c}
    return set()


def build_sql_from_query(query: Dict[str, Any], dataset_schema: Optional[Any] = None) -> Tuple[str, List[Any]]:
    """Build parameterized SQL from a widget query definition.

    If dataset_schema is provided, all dimensions/measures/filter columns must exist in schema.
    Expected query_json shape: see docs/BI_QUERY_SCHEMA.md
    """
    table = (query.get("table") or query.get("dataset") or "").strip()
    if not table:
        raise ValueError("table is required in query_json")

    schema_cols = _schema_columns(dataset_schema) if dataset_schema else None

    dims = query.get("dimensions") or []
    meas = query.get("measures") or []
    filters = query.get("filters") or []
    sort = query.get("sort") or []
    limit = int(query.get("limit") or 500)
    if limit <= 0 or limit > 5000:
        limit = 5000

    select_parts: List[str] = []
    group_by_parts: List[str] = []

    for d in dims:
        col = str(d).strip()
        if not col:
            continue
        if schema_cols is not None and col not in schema_cols:
            raise ValueError(f"dimension column '{col}' not in schema")
        quoted = f'"{col}"'
        select_parts.append(quoted)
        group_by_parts.append(quoted)

    for m in meas:
        field = (m.get("field") or m.get("column") or "").strip()
        if not field:
            continue
        if schema_cols is not None and field not in schema_cols:
            raise ValueError(f"measure column '{field}' not in schema")
        agg = (m.get("agg") or m.get("aggregation") or "sum").lower()
        if agg not in ("sum", "avg", "min", "max", "count", "count_distinct"):
            raise ValueError("unsupported aggregation")
        if agg == "count_distinct":
            select_parts.append(f'COUNT(DISTINCT "{field}") AS "{field}_cd"')
        else:
            fn = {
                "sum": "SUM",
                "avg": "AVG",
                "min": "MIN",
                "max": "MAX",
                "count": "COUNT",
            }[agg]
            select_parts.append(f'{fn}("{field}") AS "{field}_{agg}"')

    if not select_parts:
        select_parts.append("*")

    sql = f'SELECT {", ".join(select_parts)} FROM "{table}"'
    params: List[Any] = []

    if filters:
        clauses: List[str] = []
        for flt in filters:
            field = (flt.get("field") or flt.get("column") or "").strip()
            if field and schema_cols is not None and field not in schema_cols:
                raise ValueError(f"filter column '{field}' not in schema")
            op = (flt.get("op") or flt.get("operator") or "=").lower()
            if op == "eq":
                op = "="
            elif op == "ne":
                op = "!="
            elif op == "contains":
                op = "like"
            value = flt.get("value")
            if not field:
                continue
            col = f'"{field}"'
            if op == "between" and isinstance(value, list) and len(value) == 2:
                clauses.append(f"{col} BETWEEN ? AND ?")
                params.extend(value)
            elif op == "in" and isinstance(value, list) and value:
                placeholders = ",".join(["?"] * len(value))
                clauses.append(f"{col} IN ({placeholders})")
                params.extend(value)
            elif op == "like":
                clauses.append(f"{col} LIKE ?")
                params.append(f"%{value}%")
            elif op in ("=", "!=", ">", "<", ">=", "<="):
                clauses.append(f"{col} {op} ?")
                params.append(value)
            else:
                # unsupported operator – skip
                continue
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

    if group_by_parts:
        sql += " GROUP BY " + ", ".join(group_by_parts)

    if sort:
        parts: List[str] = []
        for s in sort:
            field = (s.get("field") or "").strip()
            if not field:
                continue
            direction = (s.get("direction") or "asc").upper()
            if direction not in ("ASC", "DESC"):
                direction = "ASC"
            parts.append(f'"{field}" {direction}')
        if parts:
            sql += " ORDER BY " + ", ".join(parts)

    sql += f" LIMIT {limit}"
    return sql, params


def execute_widget_query(
    widget: Dict[str, Any],
    user_context: Dict[str, Any],
    dataset_schema: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute a widget query; governance filters should be applied before calling this.

    widget is expected to contain a `query` dict. If dataset_schema is provided,
    column existence is enforced in build_sql_from_query.
    """
    query = widget.get("query") or {}
    sql, params = build_sql_from_query(query, dataset_schema)
    conn = _runtime_conn()
    try:
        cur = conn.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        columns = list(rows[0].keys()) if rows else []
        return {"columns": columns, "rows": rows}
    finally:
        conn.close()

