import hashlib
import json
from datetime import datetime

import pandas as pd

from modules.db import get_db


AR_MONTHS = {
    1: "يناير",
    2: "فبراير",
    3: "مارس",
    4: "أبريل",
    5: "مايو",
    6: "يونيو",
    7: "يوليو",
    8: "أغسطس",
    9: "سبتمبر",
    10: "أكتوبر",
    11: "نوفمبر",
    12: "ديسمبر"
}


def compute_schema_hash(df: pd.DataFrame) -> str:
    parts = [f"{c}:{str(df[c].dtype)}" for c in df.columns]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_source_file_path(file_id):
    db = get_db()
    row = db.execute("SELECT path FROM files WHERE file_id=?", (file_id,)).fetchone()
    db.close()
    return row["path"] if row else None


def load_sources(definition: dict):
    tables = {}
    schema = {}
    sources = (definition.get("dataset") or {}).get("sources") or []
    for src in sources:
        file_id = src.get("file_id")
        if not file_id:
            continue
        path = _load_source_file_path(file_id)
        if not path:
            continue
        sheet = src.get("sheet") or None
        try:
            df = pd.read_excel(path, sheet_name=sheet if sheet else 0)
        except Exception:
            df = pd.read_excel(path)
        df.columns = [str(c).strip() for c in df.columns]
        table_name = src.get("table_name") or src.get("alias_table_name") or src.get("source_id") or file_id
        tables[table_name] = df
        schema[table_name] = {
            "columns": df.columns.tolist(),
            "hash": compute_schema_hash(df)
        }
    return tables, schema


def apply_transforms(definition: dict, tables: dict):
    transforms = (definition.get("dataset") or {}).get("transforms") or {}
    for table_name, ops in transforms.items():
        df = tables.get(table_name)
        if df is None:
            continue
        for op in ops or []:
            op_type = op.get("op")
            if op_type == "trim_all_strings":
                for col in df.columns:
                    if pd.api.types.is_string_dtype(df[col]):
                        df[col] = df[col].astype(str).str.strip()
            elif op_type == "cast":
                col = op.get("column")
                to_type = op.get("type")
                if col in df.columns and to_type:
                    if to_type == "date":
                        df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
                    elif to_type == "number":
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    elif to_type == "text":
                        df[col] = df[col].astype(str)
                    elif to_type == "bool":
                        df[col] = df[col].astype(bool)
            elif op_type == "derive_date_parts":
                col = op.get("column")
                outputs = op.get("outputs") or {}
                lang = (op.get("language") or "ar").lower()
                if col in df.columns:
                    series = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
                    if outputs.get("year"):
                        df[outputs["year"]] = series.dt.year
                    if outputs.get("month"):
                        if lang.startswith("ar"):
                            df[outputs["month"]] = series.dt.month.map(AR_MONTHS)
                        else:
                            df[outputs["month"]] = series.dt.month
                    if outputs.get("quarter"):
                        df[outputs["quarter"]] = series.dt.quarter
        tables[table_name] = df
    return tables


def _safe_num(value):
    if value is None:
        return 0.0
    try:
        return float(value)
    except Exception:
        return 0.0


def eval_expression(expr: str, df: pd.DataFrame, measures: dict):
    import ast

    def replace_columns(text):
        out = ""
        i = 0
        while i < len(text):
            if text[i] == "[":
                j = text.find("]", i + 1)
                if j == -1:
                    out += text[i]
                    i += 1
                else:
                    col = text[i + 1:j]
                    out += f'COL("{col}")'
                    i = j + 1
            else:
                out += text[i]
                i += 1
        return out

    expr = replace_columns(expr)
    tree = ast.parse(expr, mode="eval")

    def COL(name):
        return df[name] if name in df.columns else pd.Series([], dtype="float")

    def SUM(x):
        return float(x.sum()) if hasattr(x, "sum") else _safe_num(x)

    def AVG(x):
        return float(x.mean()) if hasattr(x, "mean") else _safe_num(x)

    def COUNT(x):
        return int(x.count()) if hasattr(x, "count") else 0

    def DISTINCTCOUNT(x):
        return int(x.nunique()) if hasattr(x, "nunique") else 0

    def MIN(x):
        return float(x.min()) if hasattr(x, "min") else _safe_num(x)

    def MAX(x):
        return float(x.max()) if hasattr(x, "max") else _safe_num(x)

    def DIVIDE(a, b):
        a = _safe_num(a)
        b = _safe_num(b)
        return a / b if b else 0.0

    def COALESCE(a, b):
        if a is None:
            return b
        try:
            if pd.isna(a):
                return b
        except Exception:
            pass
        return a

    allowed_funcs = {
        "COL": COL,
        "SUM": SUM,
        "AVG": AVG,
        "COUNT": COUNT,
        "DISTINCTCOUNT": DISTINCTCOUNT,
        "MIN": MIN,
        "MAX": MAX,
        "DIVIDE": DIVIDE,
        "COALESCE": COALESCE
    }

    def eval_node(node):
        if isinstance(node, ast.Expression):
            return eval_node(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in measures:
                return measures[node.id]
            raise ValueError("Unknown identifier")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Invalid function call")
            fn = allowed_funcs.get(node.func.id)
            if not fn:
                raise ValueError("Function not allowed")
            args = [eval_node(a) for a in node.args]
            return fn(*args)
        if isinstance(node, ast.BinOp):
            left = eval_node(node.left)
            right = eval_node(node.right)
            if isinstance(node.op, ast.Add):
                return _safe_num(left) + _safe_num(right)
            if isinstance(node.op, ast.Sub):
                return _safe_num(left) - _safe_num(right)
            if isinstance(node.op, ast.Mult):
                return _safe_num(left) * _safe_num(right)
            if isinstance(node.op, ast.Div):
                return _safe_num(left) / _safe_num(right) if _safe_num(right) else 0.0
            raise ValueError("Unsupported operator")
        if isinstance(node, ast.UnaryOp):
            value = eval_node(node.operand)
            if isinstance(node.op, ast.USub):
                return -_safe_num(value)
            if isinstance(node.op, ast.UAdd):
                return _safe_num(value)
        raise ValueError("Unsupported expression")

    return eval_node(tree)


def compute_measures(definition: dict, tables: dict):
    measures = {}
    for m in (definition.get("dataset") or {}).get("measures") or []:
        table = m.get("table")
        expr = m.get("expression")
        if not table or table not in tables or not expr:
            measures[m.get("id")] = 0.0
            continue
        measures[m.get("id")] = eval_expression(expr, tables[table], measures)
    return measures


def apply_filters(definition: dict, tables: dict, request_args: dict):
    filters = ((definition.get("report") or {}).get("filters") or {}).get("global") or []
    for f in filters:
        table = f.get("table")
        col = f.get("column")
        if not table or table not in tables or not col:
            continue
        df = tables[table]
        filter_id = f.get("id") or col
        if f.get("type") == "date_range":
            v_from = (request_args.get(f"{filter_id}_from") or request_args.get("from") or "").strip()
            v_to = (request_args.get(f"{filter_id}_to") or request_args.get("to") or "").strip()
            if col in df.columns:
                series = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
                if v_from:
                    d_from = pd.to_datetime(v_from, errors="coerce")
                    if pd.notna(d_from):
                        df = df[series >= d_from]
                if v_to:
                    d_to = pd.to_datetime(v_to, errors="coerce")
                    if pd.notna(d_to):
                        df = df[series <= d_to]
        else:
            raw = request_args.get(filter_id)
            if raw is None:
                raw = request_args.get(col)
            raw = (raw or "").strip()
            if raw and raw.lower() != "all":
                if col in df.columns:
                    df = df[df[col].astype(str) == raw]
        tables[table] = df
    return tables


def build_filter_options(definition: dict, tables: dict):
    filters = ((definition.get("report") or {}).get("filters") or {}).get("global") or []
    fields = ((definition.get("dataset") or {}).get("fields") or {})
    options = {}
    for f in filters:
        table = f.get("table")
        col = f.get("column")
        if not table or table not in tables or not col:
            continue
        df = tables[table]
        vals = []
        if col in df.columns:
            vals = sorted([str(x) for x in df[col].dropna().unique().tolist() if str(x).strip() != ""])
        value_map = ((fields.get(table) or {}).get(col) or {}).get("value_map") or {}
        options[f.get("id") or col] = {
            "values": vals,
            "value_map": value_map
        }
    return options


def run_visuals(definition: dict, tables: dict):
    measures = compute_measures(definition, tables)
    visuals = ((definition.get("report") or {}).get("layout") or {}).get("visuals") or []
    out = []
    for v in visuals:
        vtype = v.get("type")
        vid = v.get("id")
        title = v.get("title") or ""
        if vtype == "kpi":
            mid = v.get("measure")
            out.append({
                "id": vid,
                "type": "kpi",
                "title": title,
                "value": round(float(measures.get(mid, 0.0)), 2),
                "format": v.get("format") or ""
            })
            continue
        if vtype in ("line", "bar", "pie", "doughnut", "area"):
            x = v.get("x") or {}
            table = x.get("table")
            col = x.get("column")
            if not table or table not in tables or not col:
                out.append({"id": vid, "type": vtype, "title": title, "labels": [], "series": []})
                continue
            df = tables[table]
            if col not in df.columns:
                out.append({"id": vid, "type": vtype, "title": title, "labels": [], "series": []})
                continue
            x_vals = df[col]
            if x.get("bin") == "day":
                x_vals = pd.to_datetime(x_vals, errors="coerce", dayfirst=True).dt.strftime("%Y-%m-%d")
            labels = [str(x) for x in x_vals.dropna().unique().tolist()]
            labels = sorted(labels)
            series = []
            for y in v.get("y") or []:
                mid = y.get("measure")
                if not mid:
                    continue
                data = []
                for lbl in labels:
                    gdf = df[x_vals.astype(str) == lbl]
                    data.append(round(float(eval_expression((next((m.get("expression") for m in (definition.get("dataset") or {}).get("measures") or [] if m.get("id") == mid), "0")), gdf, measures)), 2))
                series.append({"label": y.get("label") or mid, "data": data})
            out.append({"id": vid, "type": vtype, "title": title, "labels": labels, "series": series})
            continue
        if vtype == "table":
            table = v.get("table")
            cols = v.get("columns") or []
            if not table or table not in tables:
                out.append({"id": vid, "type": "table", "title": title, "columns": [], "rows": []})
                continue
            df = tables[table]
            if cols:
                df = df[[c for c in cols if c in df.columns]]
            rows = df.head(100).fillna("").to_dict(orient="records")
            out.append({"id": vid, "type": "table", "title": title, "columns": df.columns.tolist(), "rows": rows})
            continue
        out.append({"id": vid, "type": vtype, "title": title})
    return out


def build_runtime(definition: dict, request_args: dict):
    tables, schema = load_sources(definition)
    tables = apply_transforms(definition, tables)
    filter_options = build_filter_options(definition, tables)
    tables = apply_filters(definition, tables, request_args)
    visuals = run_visuals(definition, tables)
    return {
        "schema": schema,
        "filter_options": filter_options,
        "visuals": visuals,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
