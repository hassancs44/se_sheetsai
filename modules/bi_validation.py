"""SE_SHEETSAI — Strict query_json validation before SQL execution.

Validates dataset existence, column existence in schema, allowed aggregations,
and filter operators. Call validate_query_json() before execute_widget_query.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

ALLOWED_AGGREGATIONS = frozenset({"sum", "avg", "count", "min", "max"})
ALLOWED_FILTER_OPS = frozenset({"eq", "=", "between", "contains", "gt", "lt", "gte", "lte", "in", "like", "!=", "ne"})


def _schema_columns(schema: Any) -> Set[str]:
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


def validate_query_json(query_json: Any, dataset_schema: Any = None) -> None:
    """Validate query_json structure and column existence.

    Args:
        query_json: The widget query dict (dataset/table, dimensions, measures, filters, sort, limit).
        dataset_schema: Optional schema for the dataset (from bi_datasets.schema_json).
            If None, only structural validation is done; column existence is not checked.

    Raises:
        ValueError: If query structure is invalid or columns are not in schema.
    """
    if not isinstance(query_json, dict):
        raise ValueError("Invalid query structure: query must be a dict")

    dataset = (query_json.get("table") or query_json.get("dataset") or "").strip()
    if not dataset:
        raise ValueError("Invalid query structure: dataset is required")

    schema_cols = _schema_columns(dataset_schema) if dataset_schema else None

    # dimensions
    dims = query_json.get("dimensions")
    if dims is not None and not isinstance(dims, list):
        raise ValueError("Invalid query structure: dimensions must be a list")
    for d in (dims or []):
        col = (d.get("name") if isinstance(d, dict) else d) or ""
        col = str(col).strip()
        if not col:
            continue
        if schema_cols is not None and col not in schema_cols:
            raise ValueError(f"Invalid query structure: dimension column '{col}' not in schema")

    # measures
    meas = query_json.get("measures")
    if meas is not None and not isinstance(meas, list):
        raise ValueError("Invalid query structure: measures must be a list")
    for m in (meas or []):
        if not isinstance(m, dict):
            raise ValueError("Invalid query structure: each measure must be {column, agg}")
        col = (m.get("field") or m.get("column") or "").strip()
        if not col:
            raise ValueError("Invalid query structure: measure must have column or field")
        if schema_cols is not None and col not in schema_cols:
            raise ValueError(f"Invalid query structure: measure column '{col}' not in schema")
        agg = (m.get("agg") or m.get("aggregation") or "sum").lower()
        if agg not in ALLOWED_AGGREGATIONS and agg not in ("count_distinct",):
            raise ValueError(f"Invalid query structure: aggregation '{agg}' not allowed (sum, avg, count, min, max)")

    # filters
    filters = query_json.get("filters")
    if filters is not None and not isinstance(filters, list):
        raise ValueError("Invalid query structure: filters must be a list")
    for f in (filters or []):
        if not isinstance(f, dict):
            continue
        col = (f.get("column") or f.get("field") or "").strip()
        if not col:
            raise ValueError("Invalid query structure: filter must have column or field")
        if schema_cols is not None and col not in schema_cols:
            raise ValueError(f"Invalid query structure: filter column '{col}' not in schema")
        op = (f.get("op") or f.get("operator") or "eq").lower()
        if op not in ALLOWED_FILTER_OPS:
            raise ValueError(f"Invalid query structure: filter op '{op}' not allowed (eq, between, contains, gt, lt, in)")

    # sort
    sort = query_json.get("sort")
    if sort is not None and not isinstance(sort, list):
        raise ValueError("Invalid query structure: sort must be a list")
    for s in (sort or []):
        if not isinstance(s, dict):
            continue
        col = (s.get("field") or s.get("column") or "").strip()
        if schema_cols is not None and col and col not in schema_cols:
            raise ValueError(f"Invalid query structure: sort column '{col}' not in schema")

    # limit
    limit = query_json.get("limit")
    if limit is not None:
        try:
            limit_val = int(limit)
            if limit_val < 0 or limit_val > 5000:
                raise ValueError("Invalid query structure: limit must be between 0 and 5000")
        except TypeError:
            raise ValueError("Invalid query structure: limit must be a number")


def get_schema_for_table(table_name: str, datasets: List[Dict[str, Any]]) -> Any:
    """Return schema_json for the given table name from a list of dataset rows."""
    for ds in datasets or []:
        out = ds.get("output_table_name") or ds.get("table_name") or ""
        if (out or "").strip() == (table_name or "").strip():
            raw = ds.get("schema_json")
            if isinstance(raw, str):
                try:
                    import json
                    return json.loads(raw or "{}")
                except Exception:
                    return {}
            return raw or {}
    return None
