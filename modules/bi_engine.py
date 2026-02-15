# SE_SHEETSAI — BI Engine: ingestion + runtime connection.
"""
- ingest_file_to_datasets(file_id, excel_path): hash Excel, compare with bi_datasets;
  if changed: read all sheets with pandas, normalize columns, infer types,
  write to SQLite (BI_RUNTIME_DB_PATH) or Postgres (when BI_RUNTIME_ENGINE=postgres).
- get_bi_connection(): SQLite or Postgres connection for runtime (used by bi_queries when postgres).
- test_bi_connection(): health check.
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

try:
    from config import (
        BI_RUNTIME_ENGINE,
        BI_RUNTIME_DB_PATH,
        BI_POSTGRES_HOST,
        BI_POSTGRES_PORT,
        BI_POSTGRES_DB,
        BI_POSTGRES_USER,
        BI_POSTGRES_PASSWORD,
    )
except ImportError:
    BI_RUNTIME_ENGINE = os.getenv("BI_RUNTIME_ENGINE", "sqlite").lower()
    BI_RUNTIME_DB_PATH = os.getenv("BI_RUNTIME_DB_PATH", "")
    BI_POSTGRES_HOST = os.getenv("BI_POSTGRES_HOST", "localhost")
    BI_POSTGRES_PORT = int(os.getenv("BI_POSTGRES_PORT", "5433"))
    BI_POSTGRES_DB = os.getenv("BI_POSTGRES_DB", "sheetsai_bi")
    BI_POSTGRES_USER = os.getenv("BI_POSTGRES_USER", "sheetsai_user")
    BI_POSTGRES_PASSWORD = os.getenv("BI_POSTGRES_PASSWORD", "strongpassword")

try:
    import pandas as pd
except ImportError:
    pd = None


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_column_name(name: str) -> str:
    s = str(name).strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^\w]", "_", s)
    s = s.strip("_") or "col"
    return s


def _infer_type(series: "pd.Series") -> str:
    if pd is None:
        return "text"
    if pd.api.types.is_integer_dtype(series.dtype):
        return "integer"
    if pd.api.types.is_float_dtype(series.dtype):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "date"
    return "text"


def _read_excel_all_sheets(excel_path: str) -> List[Tuple[str, "pd.DataFrame"]]:
    if not pd:
        raise RuntimeError("pandas is required for BI ingestion")
    if not os.path.isfile(excel_path):
        raise FileNotFoundError(excel_path)
    xl = pd.ExcelFile(excel_path, engine="openpyxl")
    out = []
    for i, sheet_name in enumerate(xl.sheet_names):
        df = pd.read_excel(xl, sheet_name=sheet_name, engine="openpyxl")
        df = df.dropna(how="all").dropna(axis=1, how="all")
        if df.empty or len(df.columns) == 0:
            continue
        if df.columns.dtype == "int64":
            df.columns = [f"col_{j+1}" for j in range(len(df.columns))]
        new_cols = []
        for c in df.columns:
            n = _normalize_column_name(str(c))
            if n in new_cols:
                n = f"{n}_{len(new_cols)}"
            new_cols.append(n)
        df.columns = new_cols
        for col in df.columns:
            if df[col].dtype == object:
                try:
                    df[col] = pd.to_numeric(df[col])
                except (ValueError, TypeError):
                    pass
        out.append((sheet_name, df))
    return out


def _schema_json_from_df(df: "pd.DataFrame") -> List[Dict[str, str]]:
    return [{"name": c, "type": _infer_type(df[c])} for c in df.columns]


def _write_sqlite(file_id: str, sheets: List[Tuple[str, "pd.DataFrame"]]) -> List[Tuple[str, str, int, List[Dict[str, str]]]]:
    """Write each sheet to table dataset_<file_id>_sheet<N>. Return list of (table_name, sheet_name, row_count, schema_json)."""
    safe_id = re.sub(r"[^\w]", "_", (file_id or "file")[:64])
    os.makedirs(os.path.dirname(BI_RUNTIME_DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(BI_RUNTIME_DB_PATH)
    result = []
    for i, (sheet_name, df) in enumerate(sheets):
        table_name = f"dataset_{safe_id}_sheet{i}"
        schema_list = _schema_json_from_df(df)
        col_types = []
        for c in df.columns:
            t = _infer_type(df[c])
            if t == "integer":
                col_types.append(f'"{c}" INTEGER')
            elif t == "float":
                col_types.append(f'"{c}" REAL')
            elif t == "date":
                col_types.append(f'"{c}" TEXT')
            else:
                col_types.append(f'"{c}" TEXT')
        conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        conn.execute(f'CREATE TABLE "{table_name}" ({", ".join(col_types)})')
        cols_quoted = ", ".join(f'"{c}"' for c in df.columns)
        placeholders = ", ".join(["?"] * len(df.columns))
        for _, row in df.iterrows():
            # Convert pandas Timestamp/NaT/datetime to string/None for SQLite compatibility
            row_values = []
            for val in row:
                if pd is not None and pd.isna(val):
                    row_values.append(None)
                elif pd is not None:
                    # Handle pandas Timestamp
                    try:
                        if isinstance(val, pd.Timestamp):
                            row_values.append(val.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(val) else None)
                            continue
                    except Exception:
                        pass
                # Handle Python datetime objects
                if hasattr(val, 'strftime') and hasattr(val, 'year'):
                    try:
                        row_values.append(val.strftime("%Y-%m-%d %H:%M:%S") if val is not None else None)
                        continue
                    except Exception:
                        pass
                # Default: use value as-is
                row_values.append(val)
            conn.execute(
                f'INSERT INTO "{table_name}" ({cols_quoted}) VALUES ({placeholders})',
                tuple(row_values),
            )
        result.append((table_name, sheet_name, len(df), schema_list))
    conn.commit()
    conn.close()
    return result


def _write_postgres(file_id: str, sheets: List[Tuple[str, "pd.DataFrame"]]) -> List[Tuple[str, str, int, List[Dict[str, str]]]]:
    """Create schema dataset_<file_id>, one table per sheet. Return list of (table_name, sheet_name, row_count, schema_json)."""
    try:
        import psycopg2
        from psycopg2 import sql as pg_sql
    except ImportError:
        raise RuntimeError("psycopg2 is required for BI Postgres. pip install psycopg2-binary")
    conn = get_bi_connection()
    safe_id = re.sub(r"[^\w]", "_", (file_id or "file")[:64]).lower()
    schema_name = f"dataset_{safe_id}"
    result = []
    try:
        with conn.cursor() as cur:
            cur.execute(pg_sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(pg_sql.Identifier(schema_name)))
            for i, (sheet_name, df) in enumerate(sheets):
                table_name = f"dataset_{safe_id}_sheet{i}"
                schema_list = _schema_json_from_df(df)
                type_map = {"integer": "BIGINT", "float": "DOUBLE PRECISION", "date": "TIMESTAMP", "text": "TEXT"}
                col_defs = [f'"{c}" {type_map.get(_infer_type(df[c]), "TEXT")}' for c in df.columns]
                cur.execute(pg_sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                    pg_sql.Identifier(schema_name), pg_sql.Identifier(table_name)
                ))
                create_sql = f'CREATE TABLE "{schema_name}"."{table_name}" ({", ".join(col_defs)})'
                cur.execute(create_sql)
                tuples = [tuple(row) for row in df.itertuples(index=False, name=None)]
                if tuples:
                    cols = ", ".join([f'"{c}"' for c in df.columns])
                    placeholders = ", ".join(["%s"] * len(df.columns))
                    insert_sql = f'INSERT INTO "{schema_name}"."{table_name}" ({cols}) VALUES ({placeholders})'
                    for t in tuples:
                        cur.execute(insert_sql, t)
                result.append((table_name, sheet_name, len(df), schema_list))
        conn.commit()
    finally:
        conn.close()
    return result


def ingest_file_to_datasets(file_id: str, excel_path: str) -> Dict[str, Any]:
    """
    Ingest Excel into BI runtime DB and bi_datasets.
    - Compute SHA-256 of file; if hash matches existing bi_datasets for this file, skip.
    - Else: read all sheets, normalize columns, infer types, write to runtime DB.
    - Upsert bi_datasets, mark dashboards stale then clear needs_refresh.
    Return: {"skipped": bool, "summary": str, "datasets": [{"table_name", "sheet_name", "row_count", "schema": [{name, type}]}]}
    """
    from modules.db import get_db
    from modules.bi_models import upsert_dataset, mark_dashboards_stale_for_file

    if not os.path.isfile(excel_path):
        raise FileNotFoundError(excel_path)

    file_hash = _file_hash(excel_path)
    db = get_db()
    existing = db.execute(
        "SELECT id, ingestion_hash FROM bi_datasets WHERE source_file_id = ?",
        (file_id,),
    ).fetchall()
    db.close()

    for row in existing:
        if (row.get("ingestion_hash") or getattr(row, "ingestion_hash", None)) == file_hash:
            logging.info("bi_engine: skip ingestion (unchanged hash) file_id=%s", file_id)
            datasets = []
            db = get_db()
            rows = db.execute(
                "SELECT name, output_table_name, schema_json, row_count FROM bi_datasets WHERE source_file_id = ?",
                (file_id,),
            ).fetchall()
            db.close()
            for r in rows:
                r = dict(r)
                schema = []
                try:
                    raw = json.loads(r.get("schema_json") or "{}")
                    schema = raw.get("columns", raw) if isinstance(raw, dict) else raw
                    if not isinstance(schema, list):
                        schema = []
                except Exception:
                    pass
                datasets.append({
                    "table_name": r.get("output_table_name"),
                    "sheet_name": r.get("name"),
                    "row_count": r.get("row_count") or 0,
                    "schema": schema,
                })
            return {"skipped": True, "summary": "unchanged", "datasets": datasets}

    sheets = _read_excel_all_sheets(excel_path)
    if not sheets:
        raise ValueError("Excel has no readable sheets with data")

    if BI_RUNTIME_ENGINE == "postgres":
        written = _write_postgres(file_id, sheets)
    else:
        written = _write_sqlite(file_id, sheets)

    engine_type = BI_RUNTIME_ENGINE if BI_RUNTIME_ENGINE == "postgres" else "sqlite"
    for table_name, sheet_name, row_count, schema_list in written:
        schema_dict = [{"name": s["name"], "type": s["type"]} for s in schema_list]
        upsert_dataset(
            file_id=file_id,
            sheet_name=sheet_name,
            table_name=table_name,
            engine_type=engine_type,
            schema={"columns": schema_dict},
            row_count=row_count,
            ingestion_hash=file_hash,
            status="ready",
        )

    mark_dashboards_stale_for_file(file_id)
    db = get_db()
    db.execute(
        "UPDATE bi_dashboards SET needs_refresh = 0, updated_at = datetime('now') WHERE linked_file_id = ?",
        (file_id,),
    )
    db.commit()
    db.close()

    datasets = [
        {"table_name": t, "sheet_name": s, "row_count": n, "schema": sch}
        for t, s, n, sch in written
    ]
    logging.info("bi_engine: ingested file_id=%s tables=%s", file_id, [d["table_name"] for d in datasets])
    try:
        from modules.audit import log_event
        log_event("bi_dataset_ingested", None, None, item_type="bi_dataset", item_id=file_id, context={"file_id": file_id, "sheets": len(datasets)})
    except Exception:
        pass
    return {"skipped": False, "summary": f"ingested {len(datasets)} sheets", "datasets": datasets}


def get_bi_connection():
    """
    Return a connection to the BI runtime DB.
    - If BI_RUNTIME_ENGINE == "sqlite": return sqlite3.Connection (caller must close).
    - If BI_RUNTIME_ENGINE == "postgres": return psycopg2 connection.
    """
    if BI_RUNTIME_ENGINE == "postgres":
        try:
            import psycopg2
        except ImportError:
            raise RuntimeError("psycopg2 is required. pip install psycopg2-binary")
        return psycopg2.connect(
            host=BI_POSTGRES_HOST,
            port=BI_POSTGRES_PORT,
            dbname=BI_POSTGRES_DB,
            user=BI_POSTGRES_USER,
            password=BI_POSTGRES_PASSWORD,
        )
    return sqlite3.connect(BI_RUNTIME_DB_PATH)


def test_bi_connection() -> bool:
    """Test BI runtime connection (SQLite or Postgres)."""
    try:
        conn = get_bi_connection()
        if BI_RUNTIME_ENGINE == "postgres":
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        else:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
        conn.close()
        return True
    except Exception as e:
        logging.warning("BI connection test failed: %s", e)
        return False
