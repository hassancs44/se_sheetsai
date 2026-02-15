"""SE_SHEETSAI — Internal BI pivot engine.

Computes server-side pivot tables for pivot widgets using pandas.
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from modules.bi_queries import execute_widget_query


def run_pivot(widget: Dict[str, Any], user_context: Dict[str, Any]) -> Dict[str, Any]:
    """Run a pivot for the given widget.

    widget.query is expected to include:
      - rows: list of dimension field names
      - cols: list of dimension field names
      - value: {"field": "...", "agg": "sum" | "avg" | ...}
    plus the normal query parts used by execute_widget_query.
    """
    base_result = execute_widget_query(widget, user_context)
    data = base_result.get("rows") or []
    if not data:
        return {"columns": [], "rows": []}

    q = widget.get("query") or {}
    rows = q.get("rows") or []
    cols = q.get("cols") or []
    val = q.get("value") or {}
    value_field = val.get("field")
    agg = val.get("agg") or val.get("aggregation") or "sum"

    df = pd.DataFrame(data)
    if value_field not in df.columns:
        return {"columns": list(df.columns), "rows": df.to_dict(orient="records")}

    table = pd.pivot_table(
        df,
        values=value_field,
        index=rows or None,
        columns=cols or None,
        aggfunc=agg,
        fill_value=0,
    )
    table = table.reset_index()
    return {
        "columns": list(table.columns),
        "rows": table.to_dict(orient="records"),
    }

