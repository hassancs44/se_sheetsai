from datetime import datetime
from modules.db import get_db


def compute_alerts(df):
    alerts = []
    if df is None or df.empty:
        return alerts

    try:
        if "مجمل الربح" in df.columns and (df["مجمل الربح"] < 0).any():
            alerts.append({
                "level": "warn",
                "message": "تم رصد عمليات بهامش ربح سلبي."
            })
        if "الإجمالي بدون الضريبة" in df.columns and df["الإجمالي بدون الضريبة"].sum() == 0:
            alerts.append({
                "level": "info",
                "message": "لا توجد مبيعات في الفترة الحالية."
            })
    except Exception:
        pass
    return alerts


def refresh_dashboard(dashboard_id):
    return {
        "dashboard_id": dashboard_id,
        "refreshed_at": datetime.now().strftime("%Y-%m-%d %H:%M")
    }


def get_dashboard_files(dashboard_id):
    files = []
    db = get_db()
    try:
        row = db.execute(
            "SELECT file_id FROM dashboards WHERE dashboard_id=?",
            (dashboard_id,)
        ).fetchone()
        if row and row.get("file_id"):
            files.append(row["file_id"])
        try:
            extra = db.execute(
                "SELECT file_id FROM dashboard_files WHERE dashboard_id=?",
                (dashboard_id,)
            ).fetchall()
            for r in extra or []:
                fid = r.get("file_id")
                if fid and fid not in files:
                    files.append(fid)
        except Exception:
            pass
    finally:
        db.close()
    return files
