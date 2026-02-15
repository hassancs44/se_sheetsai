# SE_SHEETSAI — Trigger BI resync when Excel file is saved (e.g. from OnlyOffice callback)
"""
Background thread: ingest file into native BI runtime (bi_engine.ingest_file_to_datasets).
No Metabase; no external API.
"""
import os
import logging
import threading
from datetime import datetime


def _bi_resync_background(file_id):
    """Background thread: ingest Excel into BI runtime for all dashboards linked to this file."""
    try:
        from modules.db import get_db
        from modules.bi_engine import ingest_file_to_datasets

        db = get_db()
        dashboards = db.execute(
            "SELECT internal_id FROM bi_dashboards WHERE linked_file_id = ?",
            (file_id,),
        ).fetchall()
        f = db.execute("SELECT path FROM files WHERE file_id = ? AND is_trashed = 0", (file_id,)).fetchone()
        db.close()
        if not dashboards:
            return
        if not f:
            return
        f = dict(f) if f else {}
        if not f.get("path") or not os.path.isfile(f["path"]):
            return
        excel_path = f["path"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        started = datetime.utcnow().isoformat() + "Z"
        try:
            ingest_file_to_datasets(file_id, excel_path)
            db = get_db()
            for d in dashboards:
                d = dict(d)
                db.execute(
                    "INSERT INTO bi_sync_logs (internal_id, file_id, triggered_by, started_at, finished_at, status, created_at) VALUES (?, ?, 'onlyoffice_save', ?, ?, 'success', ?)",
                    (d["internal_id"], file_id, started, datetime.utcnow().isoformat() + "Z", now),
                )
            db.commit()
            db.close()
            logging.info("bi_resync_background: ingested file_id=%s", file_id)
        except Exception as e:
            logging.exception("bi_resync_background: file_id=%s: %s", file_id, e)
            try:
                db = get_db()
                for d in dashboards:
                    d = dict(d)
                    db.execute(
                        "INSERT INTO bi_sync_logs (internal_id, file_id, triggered_by, started_at, finished_at, status, error_message, created_at) VALUES (?, ?, 'onlyoffice_save', ?, ?, 'failed', ?, ?)",
                        (d["internal_id"], file_id, started, datetime.utcnow().isoformat() + "Z", str(e)[:500], now),
                    )
                db.commit()
                db.close()
            except Exception:
                pass
    except Exception as e:
        logging.exception("bi_resync_background: %s", e)


def trigger_bi_resync_for_file(file_id):
    """Trigger background BI ingestion when Excel file is saved and has linked dashboard(s)."""
    threading.Thread(target=_bi_resync_background, args=(file_id,), daemon=True).start()
