# SE_SHEETSAI — Build analysis dataset from Excel for Metabase
"""
Maps each Excel file to deterministic tables in PostgreSQL runtime DB.
Metabase connects to PostgreSQL; Studio builds questions/dashboards from these tables.
PostgreSQL: one schema per file (bi_file_<file_id>), tables with _source_file_id, _last_sync_at.

NO SQLite. Production-grade PostgreSQL only.
"""
import os
import re
import logging
from datetime import datetime, timezone

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import psycopg2
    from psycopg2 import sql as pg_sql
    from psycopg2.extras import execute_values
except ImportError:
    psycopg2 = None

from modules.bi_engine import get_bi_connection


def normalize_columns(df):
    """Normalize column names: trim, replace spaces with underscore, ensure valid identifiers."""
    if df is None or df.empty:
        return df
    new_cols = []
    for c in df.columns:
        s = str(c).strip()
        s = re.sub(r"\s+", "_", s)
        s = re.sub(r"[^\w]", "_", s)
        s = s.strip("_") or f"col_{len(new_cols)}"
        if s in new_cols:
            s = f"{s}_{len(new_cols)}"
        new_cols.append(s)
    df = df.copy()
    df.columns = new_cols
    return df


def _pg_schema_name(file_id):
    """Safe schema name: bi_file_<file_id_safe>."""
    file_id_safe = re.sub(r"[^\w]", "_", (file_id or "file")[:64])
    return f"bi_file_{file_id_safe}".lower()


def _read_excel_to_dfs(excel_path, file_id, dataset_key_prefix=None):
    """
    Read Excel into list of (table_name, df). Handles retry, hidden sheets, auto-headers.
    Returns (prefix, list of (table_name, df)).
    
    Requires:
    - At least 1 column
    - At least 1 data row
    """
    if not pd:
        raise RuntimeError("pandas is required for bi_from_excel")
    if not os.path.isfile(excel_path):
        raise FileNotFoundError(f"Excel file not found: {excel_path}")
    file_id_safe = re.sub(r"[^\w]", "_", (file_id or "file")[:64])
    prefix = dataset_key_prefix or f"excel_{file_id_safe}"
    dfs = []

    retry_delays = [0.4, 0.8, 1.2]
    xl = None
    for delay in retry_delays:
        try:
            import time
            if delay > 0:
                time.sleep(delay)
            xl = pd.ExcelFile(excel_path, engine="openpyxl")
            break
        except Exception as e:
            logging.warning("bi_from_excel: retry %s (delay %.1fs): %s", excel_path, delay, e)
            if delay == retry_delays[-1]:
                raise RuntimeError(f"Could not open Excel file after retries: {e}")

    if not xl:
        raise RuntimeError("Could not open Excel file")

    logging.info("bi_from_excel: workbook has %d sheets: %s", len(xl.sheet_names), xl.sheet_names)

    for i, sheet_name in enumerate(xl.sheet_names):
        try:
            df = pd.read_excel(xl, sheet_name=sheet_name, engine="openpyxl")
        except Exception as e:
            logging.warning("bi_from_excel: sheet %s: %s", sheet_name, e)
            continue
        
        # Remove empty rows and columns
        df = df.dropna(how="all").dropna(axis=1, how="all")
        
        if df is None or df.empty:
            logging.info("bi_from_excel: sheet %s is empty after cleanup, skipping", sheet_name)
            continue
        
        # Require at least 1 column
        if len(df.columns) == 0:
            logging.warning("bi_from_excel: sheet %s has no columns, skipping", sheet_name)
            continue
        
        # Require at least 1 data row
        if len(df) == 0:
            logging.warning("bi_from_excel: sheet %s has no data rows, skipping", sheet_name)
            continue
        
        # Auto-detect headers if columns are numeric
        if df.columns.dtype == "int64" and all(isinstance(c, int) for c in df.columns):
            df.columns = [f"col_{j+1}" for j in range(len(df.columns))]
        
        df = normalize_columns(df)
        
        # Try to convert object columns to numeric where possible
        for col in df.columns:
            if df[col].dtype == object:
                try:
                    df[col] = pd.to_numeric(df[col])
                except (ValueError, TypeError):
                    pass
        
        table_name = f"{prefix}__sheet_{i}"
        dfs.append((table_name, df))
        logging.info("bi_from_excel: sheet '%s' -> table '%s' (shape: %s)", sheet_name, table_name, df.shape)

    if not dfs:
        raise ValueError(
            "The Excel file has no readable sheets with data. "
            "Ensure at least one sheet has at least 1 column and 1 data row, then save the file."
        )
    return prefix, dfs


def _pg_type(dtype):
    """Map pandas dtype to PostgreSQL type."""
    if pd.api.types.is_integer_dtype(dtype):
        return "BIGINT"
    if pd.api.types.is_float_dtype(dtype):
        return "DOUBLE PRECISION"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "TIMESTAMP"
    return "TEXT"


def _write_postgres(prefix, dfs, file_id):
    """
    Write to PostgreSQL using psycopg2. Schema: bi_file_<file_id>, one table per sheet.
    Adds metadata columns: _source_file_id, _last_sync_at.
    """
    if not psycopg2:
        raise RuntimeError("psycopg2 is required. pip install psycopg2-binary")
    conn = get_bi_connection()
    schema = _pg_schema_name(file_id)
    last_sync = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    table_names = []
    try:
        with conn.cursor() as cur:
            cur.execute(pg_sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(pg_sql.Identifier(schema)))
            for table_name, df in dfs:
                df = df.copy()
                df["_source_file_id"] = file_id or ""
                df["_last_sync_at"] = last_sync
                cols = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
                df.columns = cols
                table_name_safe = re.sub(r"[^\w]", "_", table_name)
                quoted_table = '"' + table_name_safe.replace('"', '""') + '"'
                quoted_schema = '"' + schema.replace('"', '""') + '"'
                full_name = f"{quoted_schema}.{quoted_table}"
                cur.execute(f"DROP TABLE IF EXISTS {full_name} CASCADE")
                col_defs = [f'"{c}" {_pg_type(df[c].dtype)}' for c in df.columns]
                cur.execute(f"CREATE TABLE {full_name} (" + ", ".join(col_defs) + ")")
                tuples = [tuple(row) for row in df.itertuples(index=False, name=None)]
                if tuples:
                    insert_sql = f'INSERT INTO {full_name} (' + ", ".join([f'"{c}"' for c in df.columns]) + ") VALUES %s"
                    execute_values(cur, insert_sql, tuples, page_size=1000)
                table_names.append(table_name_safe)
                logging.info("bi_from_excel: created table %s.%s (shape: %s, engine: postgres)", schema, table_name_safe, df.shape)
        conn.commit()
    finally:
        conn.close()
    logging.info("bi_from_excel: using postgres engine (schema=%s)", schema)
    return table_names


def build_runtime_tables_from_excel(excel_path, runtime_db_path, file_id, dataset_key_prefix=None):
    """
    Read Excel file (all sheets), normalize columns, write to PostgreSQL runtime DB.
    Returns (dataset_key, list of table names).
    
    Args:
        excel_path: Path to Excel file
        runtime_db_path: Ignored (kept for compatibility). PostgreSQL is always used.
        file_id: File identifier for schema naming
        dataset_key_prefix: Optional prefix for dataset key
        
    Returns:
        (dataset_key, list of table names)
        
    Raises:
        RuntimeError: If PostgreSQL connection fails or Excel has no valid data
        ValueError: If Excel file has no readable sheets with data
    """
    prefix, dfs = _read_excel_to_dfs(excel_path, file_id, dataset_key_prefix)
    table_names = _write_postgres(prefix, dfs, file_id)
    logging.info("bi_from_excel: created %d tables: %s", len(table_names), table_names)
    return prefix, table_names


def write_tables(df_list, runtime_db_path, dataset_key):
    """
    Write a list of (table_name, DataFrame) to PostgreSQL runtime DB.
    Legacy function - use build_runtime_tables_from_excel for new code.
    """
    if not pd:
        raise RuntimeError("pandas is required for bi_from_excel")
    if not psycopg2:
        raise RuntimeError("psycopg2 is required. pip install psycopg2-binary")
    conn = get_bi_connection()
    table_names = []
    try:
        with conn.cursor() as cur:
            for table_name, df in df_list:
                if df is not None and not df.empty:
                    df = normalize_columns(df)
                    table_name_safe = re.sub(r"[^\w]", "_", table_name)
                    cur.execute(f'DROP TABLE IF EXISTS "{table_name_safe}" CASCADE')
                    col_defs = [f'"{c}" {_pg_type(df[c].dtype)}' for c in df.columns]
                    cur.execute(f'CREATE TABLE "{table_name_safe}" (' + ", ".join(col_defs) + ")")
                    tuples = [tuple(row) for row in df.itertuples(index=False, name=None)]
                    if tuples:
                        insert_sql = f'INSERT INTO "{table_name_safe}" (' + ", ".join([f'"{c}"' for c in df.columns]) + ") VALUES %s"
                        execute_values(cur, insert_sql, tuples, page_size=1000)
                    table_names.append(table_name_safe)
        conn.commit()
    finally:
        conn.close()
    return table_names


def get_bi_postgres_schema_for_file(file_id):
    """Return PostgreSQL schema name for a file (for Metabase schema filter)."""
    return _pg_schema_name(file_id)
