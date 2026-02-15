"""SE_SHEETSAI — Internal BI Engine models.

SQLite-layer CRUD helpers for dashboards, widgets, and datasets.
All other BI modules should call into this layer instead of issuing
raw SQL directly, to keep the schema and behaviour consistent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from modules.db import get_db


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ----- Dataclasses for type clarity (optional at call site) -----


@dataclass
class BIDataset:
    id: Optional[int]
    file_id: str
    sheet_name: str
    table_name: str
    engine_type: str  # "sqlite" | "postgres"
    schema: Dict[str, Any]
    row_count: int
    ingestion_hash: Optional[str]
    last_ingested_at: Optional[str]
    status: str  # "ready" | "stale" | "error"


# ----- Dataset helpers -----


def upsert_dataset(
    *,
    file_id: str,
    sheet_name: str,
    table_name: str,
    engine_type: str,
    schema: Dict[str, Any],
    row_count: int,
    ingestion_hash: Optional[str],
    status: str = "ready",
) -> None:
    """Create or update a BI dataset row."""
    db = get_db()
    cur = db.execute(
        """
        SELECT id FROM bi_datasets
        WHERE source_file_id = ? AND name = ?
        """,
        (file_id, sheet_name),
    )
    row = cur.fetchone()
    schema_json = json.dumps(schema or {})
    now = _now()
    if row:
        db.execute(
            """
            UPDATE bi_datasets
            SET output_table_name = ?,
                engine_type = ?,
                schema_json = ?,
                row_count = ?,
                ingestion_hash = ?,
                last_ingested_at = ?,
                status = ?
            WHERE id = ?
            """,
            (
                table_name,
                engine_type,
                schema_json,
                row_count,
                ingestion_hash,
                now,
                status,
                row["id"],
            ),
        )
    else:
        db.execute(
            """
            INSERT INTO bi_datasets
            (name, source_file_id, output_table_name, extract_mode,
             last_sync_at, created_at, engine_type, schema_json,
             row_count, last_ingested_at, ingestion_hash, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                sheet_name,
                file_id,
                table_name,
                "full",
                now,
                now,
                engine_type,
                schema_json,
                row_count,
                now,
                ingestion_hash,
                status,
            ),
        )
    db.commit()
    db.close()


def list_datasets_for_file(file_id: str) -> List[Dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        """
        SELECT *
        FROM bi_datasets
        WHERE source_file_id = ?
        ORDER BY id DESC
        """,
        (file_id,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


# ----- Dashboard + widgets -----


def create_dashboard_from_file(
    *,
    file_id: str,
    owner_user_id: str,
    title: str,
    description: str = "",
) -> str:
    """Create a new dashboard internal to a given file and return internal_id."""
    from uuid import uuid4

    internal_id = f"DASH_{datetime.now().strftime('%Y%m%d%H%M')}_{uuid4().hex[:6].upper()}"
    db = get_db()
    db.execute(
        """
        INSERT INTO bi_dashboards
        (internal_id, title, linked_file_id, owner_user_id,
         allow_export, allow_download, allow_filter,
         created_at, updated_at, layout_json, filters_json,
         status, needs_refresh)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            internal_id,
            title,
            file_id,
            owner_user_id,
            0,
            0,
            1,
            _now(),
            _now(),
            json.dumps({"grid": []}),
            json.dumps([]),
            "draft",
            0,
        ),
    )
    db.commit()
    db.close()
    return internal_id


def get_dashboard(internal_id: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    row = db.execute(
        "SELECT * FROM bi_dashboards WHERE internal_id = ?",
        (internal_id,),
    ).fetchone()
    db.close()
    return dict(row) if row else None


def update_dashboard_layout(
    internal_id: str,
    layout: Dict[str, Any],
    filters: Any,
    status: Optional[str] = None,
    theme: Optional[Dict[str, Any]] = None,
) -> None:
    db = get_db()
    theme_json = json.dumps(theme or {}) if theme is not None else None
    if theme_json is not None:
        try:
            db.execute(
                """
                UPDATE bi_dashboards
                SET layout_json = ?, filters_json = ?, theme_json = ?, updated_at = ?, status = COALESCE(?, status)
                WHERE internal_id = ?
                """,
                (json.dumps(layout or {}), json.dumps(filters or []), theme_json, _now(), status, internal_id),
            )
        except Exception:
            db.execute(
                """
                UPDATE bi_dashboards
                SET layout_json = ?, filters_json = ?, updated_at = ?, status = COALESCE(?, status)
                WHERE internal_id = ?
                """,
                (json.dumps(layout or {}), json.dumps(filters or []), _now(), status, internal_id),
            )
    else:
        db.execute(
            """
            UPDATE bi_dashboards
            SET layout_json = ?, filters_json = ?, updated_at = ?, status = COALESCE(?, status)
            WHERE internal_id = ?
            """,
            (json.dumps(layout or {}), json.dumps(filters or []), _now(), status, internal_id),
        )
    db.commit()
    db.close()


def mark_dashboards_stale_for_file(file_id: str) -> None:
    """Mark dashboards linked to a file as needing refresh."""
    db = get_db()
    db.execute(
        """
        UPDATE bi_dashboards
        SET needs_refresh = 1, updated_at = ?
        WHERE linked_file_id = ?
        """,
        (_now(), file_id),
    )
    db.commit()
    db.close()


def list_dashboards_for_user(user_id: str, department: Optional[str], role: Optional[str]) -> List[Dict[str, Any]]:
    """Simple list for now: all dashboards where user is owner.

    Later we can extend this to use bi_permissions.
    """
    db = get_db()
    rows = db.execute(
        """
        SELECT * FROM bi_dashboards
        WHERE owner_user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def replace_widgets_for_dashboard(internal_id: str, widgets: List[Dict[str, Any]]) -> None:
    """Replace all widgets for a dashboard with the provided list."""
    db = get_db()
    db.execute("DELETE FROM bi_widgets WHERE dashboard_internal_id = ?", (internal_id,))
    now = _now()
    for w in widgets:
        qj = json.dumps(w.get("query") or {})
        cj = json.dumps(w.get("config") or {})
        ij = json.dumps(w.get("interaction_json") or w.get("interaction") or {})
        try:
            db.execute(
                """
                INSERT INTO bi_widgets
                (widget_id, dashboard_internal_id, type, title,
                 query_json, config_json, interaction_json, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (w.get("widget_id"), internal_id, w.get("type"), w.get("title") or "", qj, cj, ij, now, now),
            )
        except Exception:
            db.execute(
                """
                INSERT INTO bi_widgets
                (widget_id, dashboard_internal_id, type, title,
                 query_json, config_json, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (w.get("widget_id"), internal_id, w.get("type"), w.get("title") or "", qj, cj, now, now),
            )
    db.commit()
    db.close()


def get_widgets_for_dashboard(internal_id: str) -> List[Dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        """
        SELECT *
        FROM bi_widgets
        WHERE dashboard_internal_id = ?
        ORDER BY id
        """,
        (internal_id,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_dashboard_filters(internal_id: str) -> List[Dict[str, Any]]:
    """Return filter definitions for a dashboard (bi_dashboard_filters)."""
    db = get_db()
    try:
        rows = db.execute(
            """
            SELECT * FROM bi_dashboard_filters
            WHERE dashboard_internal_id = ?
            ORDER BY filter_key
            """,
            (internal_id,),
        ).fetchall()
    except Exception:
        rows = []
    db.close()
    return [dict(r) for r in rows]


def duplicate_dashboard(
    source_internal_id: str,
    owner_user_id: str,
    new_title: Optional[str] = None,
    file_id: Optional[str] = None,
) -> str:
    """Clone dashboard, widgets, layout, theme, and filters. Returns new internal_id."""
    from uuid import uuid4

    row = get_dashboard(source_internal_id)
    if not row:
        raise ValueError("Dashboard not found")
    file_id = file_id or row.get("linked_file_id") or ""
    new_id = f"DASH_{datetime.now().strftime('%Y%m%d%H%M')}_{uuid4().hex[:6].upper()}"
    now = _now()
    db = get_db()
    layout_json = row.get("layout_json") or "{}"
    filters_json = row.get("filters_json") or "[]"
    theme_json = row.get("theme_json") or "{}"
    if isinstance(layout_json, dict):
        layout_json = json.dumps(layout_json)
    if isinstance(filters_json, dict):
        filters_json = json.dumps(filters_json)
    if isinstance(theme_json, dict):
        theme_json = json.dumps(theme_json)
    title = new_title or (str(row.get("title") or "") + " (نسخة)")
    try:
        db.execute(
            """
            INSERT INTO bi_dashboards
            (internal_id, title, linked_file_id, owner_user_id, allow_export, allow_download, allow_filter,
             created_at, updated_at, layout_json, filters_json, theme_json, status, needs_refresh)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (new_id, title, file_id, owner_user_id, row.get("allow_export") or 0, row.get("allow_download") or 0, row.get("allow_filter") or 1, now, now, layout_json, filters_json, theme_json, "draft", 0),
        )
    except Exception:
        db.execute(
            """
            INSERT INTO bi_dashboards
            (internal_id, title, linked_file_id, owner_user_id, allow_export, allow_download, allow_filter,
             created_at, updated_at, layout_json, filters_json, status, needs_refresh)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (new_id, title, file_id, owner_user_id, row.get("allow_export") or 0, row.get("allow_download") or 0, row.get("allow_filter") or 1, now, now, layout_json, filters_json, "draft", 0),
        )
    widgets = get_widgets_for_dashboard(source_internal_id)
    for w in widgets:
        wid = w.get("widget_id") or w.get("id")
        qj = w.get("query_json") if isinstance(w.get("query_json"), str) else json.dumps(w.get("query") or w.get("query_json") or {})
        cj = w.get("config_json") if isinstance(w.get("config_json"), str) else json.dumps(w.get("config") or w.get("config_json") or {})
        ij = w.get("interaction_json")
        if not isinstance(ij, str):
            ij = json.dumps(w.get("interaction") or ij or {})
        try:
            db.execute(
                """INSERT INTO bi_widgets (widget_id, dashboard_internal_id, type, title, query_json, config_json, interaction_json, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (wid, new_id, w.get("type") or "kpi", w.get("title") or "", qj, cj, ij, now, now),
            )
        except Exception:
            db.execute(
                """INSERT INTO bi_widgets (widget_id, dashboard_internal_id, type, title, query_json, config_json, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (wid, new_id, w.get("type") or "kpi", w.get("title") or "", qj, cj, now, now),
            )
    filters_list = get_dashboard_filters(source_internal_id)
    for f in filters_list:
        fkey = f.get("filter_key")
        ftype = f.get("filter_type")
        flabel = f.get("label")
        fconfig = f.get("config_json") if isinstance(f.get("config_json"), str) else json.dumps(f.get("config_json") or {})
        try:
            db.execute(
                """INSERT INTO bi_dashboard_filters (dashboard_internal_id, filter_key, filter_type, label, config_json, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (new_id, fkey, ftype, flabel, fconfig, now),
            )
        except Exception:
            pass
    db.commit()
    db.close()
    return new_id


def save_dashboard_as_template(dashboard_internal_id: str, name: str, user_id: str) -> int:
    """Save current dashboard layout+widgets as a reusable template. Returns template id."""
    row = get_dashboard(dashboard_internal_id)
    if not row:
        raise ValueError("Dashboard not found")
    widgets = get_widgets_for_dashboard(dashboard_internal_id)
    layout_json = row.get("layout_json") or {}
    theme_json = row.get("theme_json") or {}
    widgets_json = [{"widget_id": w.get("widget_id"), "type": w.get("type"), "title": w.get("title"), "query_json": w.get("query_json"), "config_json": w.get("config_json")} for w in widgets]
    now = _now()
    db = get_db()
    db.execute(
        """INSERT INTO bi_dashboard_templates (name, layout_json, widgets_json, theme_json, created_at, created_by)
           VALUES (?,?,?,?,?,?)""",
        (name, json.dumps(layout_json), json.dumps(widgets_json), json.dumps(theme_json), now, user_id),
    )
    tid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    db.close()
    return tid


def list_templates() -> List[Dict[str, Any]]:
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM bi_dashboard_templates ORDER BY id DESC").fetchall()
    except Exception:
        rows = []
    db.close()
    return [dict(r) for r in rows]


def create_dashboard_from_template(
    template_id: int,
    file_id: str,
    owner_user_id: str,
    title: Optional[str] = None,
) -> str:
    """Create a new dashboard from a template. Returns internal_id."""
    db = get_db()
    row = db.execute("SELECT * FROM bi_dashboard_templates WHERE id = ?", (template_id,)).fetchone()
    if not row:
        db.close()
        raise ValueError("Template not found")
    row = dict(row)
    from uuid import uuid4
    new_id = f"DASH_{datetime.now().strftime('%Y%m%d%H%M')}_{uuid4().hex[:6].upper()}"
    now = _now()
    layout_json = row.get("layout_json") or "{}"
    theme_json = row.get("theme_json") or "{}"
    widgets_json = row.get("widgets_json") or "[]"
    if isinstance(layout_json, dict):
        layout_json = json.dumps(layout_json)
    if isinstance(theme_json, dict):
        theme_json = json.dumps(theme_json)
    if isinstance(widgets_json, list):
        widgets_json = json.dumps(widgets_json)
    dash_title = title or row.get("name") or "Dashboard"
    db.execute(
        """INSERT INTO bi_dashboards (internal_id, title, linked_file_id, owner_user_id, allow_export, allow_download, allow_filter, created_at, updated_at, layout_json, filters_json, theme_json, status, needs_refresh)
           VALUES (?,?,?,?,0,0,1,?,?,?,?,?,?,0)""",
        (new_id, dash_title, file_id, owner_user_id, 0, 0, 1, now, now, layout_json, "[]", theme_json, "draft", 0),
    )
    layout = json.loads(layout_json)
    widgets_list = json.loads(widgets_json)
    for w in widgets_list:
        wid = w.get("widget_id") or ("w" + str(len(widgets_list)))
        qj = w.get("query_json") if isinstance(w.get("query_json"), str) else json.dumps(w.get("query") or w.get("query_json") or {})
        cj = w.get("config_json") if isinstance(w.get("config_json"), str) else json.dumps(w.get("config") or w.get("config_json") or {})
        try:
            db.execute(
                """INSERT INTO bi_widgets (widget_id, dashboard_internal_id, type, title, query_json, config_json, interaction_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (wid, new_id, w.get("type") or "kpi", w.get("title") or "", qj, cj, "{}", now, now),
            )
        except Exception:
            db.execute(
                """INSERT INTO bi_widgets (widget_id, dashboard_internal_id, type, title, query_json, config_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)""",
                (wid, new_id, w.get("type") or "kpi", w.get("title") or "", qj, cj, now, now),
            )
    update_dashboard_layout(new_id, layout, [], status="draft", theme=json.loads(theme_json) if isinstance(theme_json, str) else theme_json)
    db.commit()
    db.close()
    return new_id


def save_dashboard_version(dashboard_internal_id: str, layout: Dict[str, Any], widgets: List[Dict[str, Any]], user_id: str) -> int:
    db = get_db()
    r = db.execute("SELECT COALESCE(MAX(version_no), 0) + 1 FROM bi_dashboard_versions WHERE dashboard_internal_id = ?", (dashboard_internal_id,)).fetchone()
    vno = r[0] if r else 1
    now = _now()
    db.execute(
        """INSERT INTO bi_dashboard_versions (dashboard_internal_id, layout_json, widgets_json, version_no, created_at, created_by) VALUES (?,?,?,?,?,?)""",
        (dashboard_internal_id, json.dumps(layout), json.dumps(widgets), vno, now, user_id),
    )
    vid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    db.close()
    return vid


def get_dashboard_versions(dashboard_internal_id: str) -> List[Dict[str, Any]]:
    db = get_db()
    try:
        rows = db.execute(
            """SELECT * FROM bi_dashboard_versions WHERE dashboard_internal_id = ? ORDER BY version_no DESC LIMIT 50""",
            (dashboard_internal_id,),
        ).fetchall()
    except Exception:
        rows = []
    db.close()
    return [dict(r) for r in rows]


def rollback_dashboard_to_version(dashboard_internal_id: str, version_id: int) -> None:
    db = get_db()
    row = db.execute("SELECT * FROM bi_dashboard_versions WHERE id = ? AND dashboard_internal_id = ?", (version_id, dashboard_internal_id)).fetchone()
    if not row:
        db.close()
        raise ValueError("Version not found")
    row = dict(row)
    db.close()
    layout = json.loads(row.get("layout_json") or "{}")
    widgets_raw = json.loads(row.get("widgets_json") or "[]")
    widgets = []
    for w in widgets_raw:
        q = w.get("query_json") or w.get("query")
        c = w.get("config_json") or w.get("config")
        if isinstance(q, str):
            try:
                q = json.loads(q)
            except Exception:
                q = {}
        if isinstance(c, str):
            try:
                c = json.loads(c)
            except Exception:
                c = {}
        widgets.append({
            "widget_id": w.get("widget_id") or w.get("id"),
            "type": w.get("type") or "kpi",
            "title": w.get("title") or "",
            "query": q,
            "config": c,
        })
    update_dashboard_layout(dashboard_internal_id, layout, [])
    replace_widgets_for_dashboard(dashboard_internal_id, widgets)

