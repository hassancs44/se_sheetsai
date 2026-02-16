from flask import Flask, render_template, request, redirect, session, url_for, send_file, abort, flash, jsonify
from datetime import datetime, timedelta, timezone
import os, logging, jwt, re, requests, uuid, sqlite3, threading
from modules.files import (
    get_folder_path,
    create_version,
    ensure_periodic_versions,
    list_versions as list_versions_db,
    rollback_to_version,
    build_excel_diff,
    extract_text_for_index,
    index_item,
    search as search_index,
    mark_archived,
    restore_from_archive,
    transfer_ownership,
    evaluate_automation_rules,
    _sha256_file,
    _get_latest_version_hash,
    get_file_edit_lock_info,
    ensure_issued_version,
    add_file_participant,
    list_file_participants,
)
from modules.dashboards import compute_alerts, refresh_dashboard
from modules.dashboard_engine import build_runtime
import pandas as pd
import json

# ================= CONFIG =================
from config import (
    SECRET_KEY,
    ONLYOFFICE_SERVER,
    ONLYOFFICE_JWT_SECRET,
    ONLYOFFICE_JWT_ALG,
    SHEETS_DIR,
    LOGS_DIR,
    BASE_URL,
    VERSIONS_DIR,
    ARCHIVE_DAYS,
    COMPRESS_DAYS,
    ALLOW_DOWNLOAD,
    WATERMARK_ENABLED,
)


# ================= MODULES =================
from modules.db import init_db, get_db
from modules.auth import authenticate, get_user_from_excel
from modules.audit import log_event, log_share_access, log_share_denied, log_share_expired
from modules.onlyoffice import inject_permissions
from modules.bi_dashboards import get_bi_dashboard, list_bi_dashboards
from modules.bi_models import (
    get_dashboard as _get_dashboard_row,
    create_dashboard_from_file,
    get_widgets_for_dashboard,
    duplicate_dashboard,
    save_dashboard_version,
    get_dashboard_versions,
    rollback_dashboard_to_version,
    save_dashboard_as_template,
    get_dashboard_filters,
)
from modules.bi_security import check_dashboard_view_permission

# ================= APP =================
app = Flask(__name__)
app.secret_key = SECRET_KEY


@app.errorhandler(403)
def forbidden(e):
    return render_template("errors/403.html"), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404


os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(SHEETS_DIR, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(LOGS_DIR, "app.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

APP_RUN_ID = datetime.now().strftime("%Y%m%d%H%M%S")

# ================= INIT =================
init_db()

# مزامنة المستخدمين من Excel تُنفَّذ مرة واحدة فقط (بقفل ملف) لتجنب database is locked مع عدة workers
_excel_sync_done = False

def _run_excel_sync_once():
    global _excel_sync_done
    if _excel_sync_done:
        return
    import tempfile
    lock_path = os.path.join(tempfile.gettempdir(), "se_sheetsai_excel_sync.lock")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        _excel_sync_done = True
        return
    try:
        from modules.sync_excel_users import sync_users_from_excel
        sync_users_from_excel()
    except Exception as e:
        logging.warning("sync_users_from_excel: %s", e)
    finally:
        try:
            os.close(fd)
        except Exception:
            pass
        # نترك ملف القفل دون حذف حتى لا يعيد worker آخر المزامنة
    _excel_sync_done = True

_run_excel_sync_once()

# ================= HELPERS =================

def seed_first_dashboard():
    db = get_db()

    # منع التكرار
    exists = db.execute(
        "SELECT 1 FROM dashboards WHERE dashboard_id = ?",
        ("DASH_CLOUD_01",)
    ).fetchone()

    if exists:
        db.close()
        return

    # لوحة البيانات
    db.execute("""
        INSERT INTO dashboards
        (dashboard_id, name, description, file_id, sheet_name, department, created_at)
        VALUES (?,?,?,?,?,?,?)
    """, (
        "DASH_CLOUD_01",
        "لوحة غيمة سحب",
        "تحليل مبيعات غيمة سحب",
        "FILE_1770117419",
        "Sheet1",
        "SALES",
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    # KPIs
    kpis = [
        ("إجمالي الكمية", "الكمية", "sum", "number"),
        ("إجمالي المبيعات", "الإجمالي شامل الضريبة", "sum", "currency"),
        ("مجمل الربح", "مجمل الربح", "sum", "currency")
    ]

    for label, col, agg, fmt in kpis:
        db.execute("""
            INSERT INTO dashboard_kpis
            (dashboard_id, label, column_name, agg, format, created_at)
            VALUES (?,?,?,?,?,?)
        """, (
            "DASH_CLOUD_01",
            label,
            col,
            agg,
            fmt,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ))

    db.commit()
    db.close()

seed_first_dashboard()


def run_archiving():
    db = get_db()
    rows = db.execute("""
        SELECT file_id, last_opened_at, archived_at
        FROM files
        WHERE is_trashed=0
    """).fetchall()
    db.close()

    now = datetime.now()
    for r in rows:
        if r["archived_at"] or not r["last_opened_at"]:
            continue
        try:
            last_opened = datetime.strptime(r["last_opened_at"], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        days = (now - last_opened).days
        if days >= ARCHIVE_DAYS:
            compressed = days >= COMPRESS_DAYS
            mark_archived(r["file_id"], compressed=compressed)


run_archiving()

def require_login():
    return "user" in session


def get_user_department(username):
    """Return department for a user from Excel auth source."""
    info = get_user_from_excel(username)
    return info.get("department") if info else None


def log_download_blocked(actor, item_id, reason, item_type="file"):
    """Log when download is blocked by policy."""
    log_event("download_blocked", actor or "", request, item_type=item_type, item_id=item_id, context={"reason": reason, "route": request.path})


def log_action_denied(actor, item_type, item_id, action, reason):
    """Log when an action is denied due to permissions."""
    log_event("action_denied", actor or "", request, item_type=item_type, item_id=item_id, context={"action": action, "reason": reason, "route": request.path})


def row_to_dict(row):
    try:
        return dict(row)
    except Exception:
        return row


def has_dashboard_studio_access():
    return session.get("role") in {
        "مدير عام",
        "admin",
        "BI Analyst"
    }


def has_data_panel_access():
    return session.get("role") in {
        "مدير عام",
        "admin",
        "مدير القسم"
    }


def can_access_bi():
    """BI/Data Panel access: role in admin/مدير عام/مدير القسم OR app gate 'bi' in session['apps']."""
    role = session.get("role")
    apps = session.get("apps") or []
    if role in ("admin", "مدير عام", "مدير القسم"):
        return True
    return "bi" in apps


def can_create_edit_bi():
    """BI create/edit/resync/delete: role must be in BI_ALLOWED_ROLES (config)."""
    try:
        from config import BI_ALLOWED_ROLES
    except ImportError:
        BI_ALLOWED_ROLES = ["admin", "مدير عام", "مدير القسم", "تحليل البيانات"]
    role = session.get("role")
    return role in BI_ALLOWED_ROLES if role else False


def get_bi_dashboard_row(internal_id):
    """Return dashboard row by internal_id (native BI engine)."""
    return _get_dashboard_row(internal_id)


def list_bi_dashboards_for_user(user_id, department=None, role=None):
    """List dashboards the user can access (owner or file access)."""
    db = get_db()
    rows = db.execute("SELECT * FROM bi_dashboards ORDER BY created_at DESC").fetchall()
    db.close()
    rows = [dict(r) for r in rows]
    return [r for r in rows if check_dashboard_view_permission(user_id, r["internal_id"], department=department, role=role)]


def can_user_view_bi_dashboard(user_id, internal_id, department=None, role=None):
    """True if user may view this dashboard (via linked file access)."""
    return check_dashboard_view_permission(user_id, internal_id, department=department, role=role)


def has_governance_access():
    return session.get("role") in {
        "مدير عام",
        "admin"
    }


def get_bi_policy(department):
    default = {
        "allow_view": True,
        "allow_export": False,
        "allow_print": False,
        "allow_copy": False,
        "allow_refresh": False
    }
    try:
        db = get_db()
        row = db.execute("""
            SELECT allow_view, allow_export, allow_print, allow_copy, allow_refresh
            FROM governance_policies
            WHERE department=?
            ORDER BY id DESC
            LIMIT 1
        """, (department or "",)).fetchone()
        db.close()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            logging.debug("get_bi_policy: governance_policies missing, using default: %s", e)
            return default
        raise
    if not row:
        return default
    return {
        "allow_view": bool(row["allow_view"]),
        "allow_export": bool(row["allow_export"]),
        "allow_print": bool(row["allow_print"]),
        "allow_copy": bool(row["allow_copy"]),
        "allow_refresh": bool(row["allow_refresh"])
    }


def log_access_violation(action, target_type, target_id, reason):
    try:
        db = get_db()
        db.execute("""
            INSERT INTO access_violations
            (user, action, target_type, target_id, reason, created_at)
            VALUES (?,?,?,?,?,?)
        """, (
            session.get("user"),
            action,
            target_type,
            target_id,
            reason,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ))
        db.commit()
        db.close()
    except Exception:
        pass


def can_access_app(app_name: str) -> bool:
    apps = session.get("apps") or []
    return app_name in apps


@app.context_processor
def inject_identity_context():
    return {
        "role": session.get("role"),
        "apps": session.get("apps") or [],
        "email": session.get("email") or session.get("user"),
        "session_email": session.get("email") or session.get("user"),
        "session_name": session.get("name"),
        "session_role": session.get("role"),
        "session_department": session.get("department"),
        "session_branch": session.get("branch"),
        "session_company": session.get("company"),
        "session_apps": session.get("apps") or [],
        "can_data_panel": has_data_panel_access() if "user" in session else False,
        "can_access_bi": can_access_bi() if "user" in session else False,
        "can_edit_bi": has_dashboard_studio_access() if "user" in session else False,
        "can_dashboard_studio": has_dashboard_studio_access() if "user" in session else False,
        "can_access_app": can_access_app
    }


def enqueue_refresh_for_file(file_id, trigger_type="on_change"):
    # BI dataset refresh: stub until bi_datasets sync is wired (native BI)
    pass


def get_department_policy(department):
    db = get_db()
    row = db.execute("""
        SELECT policy_json FROM department_policies
        WHERE department=?
        ORDER BY id DESC
        LIMIT 1
    """, (department,)).fetchone()
    db.close()
    if not row:
        return {
            "download": True,
            "print": True,
            "copy": True,
            "allowed_file_types": [],
            "share_outside_department": True,
            "allow_public_share": True,
            "pdf_download_only": False
        }
    try:
        policy = json.loads(row["policy_json"] or "{}")
    except Exception:
        policy = {}
    return {
        "download": bool(policy.get("download", True)),
        "print": bool(policy.get("print", True)),
        "copy": bool(policy.get("copy", True)),
        "allowed_file_types": policy.get("allowed_file_types", []),
        "share_outside_department": bool(policy.get("share_outside_department", True)),
        "allow_public_share": bool(policy.get("allow_public_share", True)),
        "pdf_download_only": bool(policy.get("pdf_download_only", False))
    }

def safe_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r'[\\/:*?"<>|]', "-", name)
    return name[:80]


def create_blank_excel(path, title):
    import pandas as pd
    cols = [f"COL_{i}" for i in range(1, 21)]
    df = pd.DataFrame(columns=cols)
    meta = pd.DataFrame([
        {"key": "title", "value": title},
        {"key": "created_at", "value": datetime.now().strftime("%Y-%m-%d %H:%M")}
    ])
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Data")
        meta.to_excel(w, index=False, sheet_name="Meta")

import time

def generate_onlyoffice_token(payload):
    payload["iat"] = int(time.time())
    payload["exp"] = int(time.time()) + 3600
    return jwt.encode(payload, ONLYOFFICE_JWT_SECRET, algorithm=ONLYOFFICE_JWT_ALG)


def generate_file_access_token(file_id, user_id):
    payload = {
        "file_id": file_id,
        "user_id": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600
    }
    return jwt.encode(payload, ONLYOFFICE_JWT_SECRET, algorithm=ONLYOFFICE_JWT_ALG)


def verify_file_access_token(token, file_id):
    try:
        decoded = jwt.decode(token, ONLYOFFICE_JWT_SECRET, algorithms=[ONLYOFFICE_JWT_ALG], leeway=120)
        if decoded.get("file_id") != file_id:
            return None
        return decoded
    except Exception:
        return None


def generate_preview_token(file_id, user_id):
    payload = {
        "file_id": file_id,
        "user_id": user_id,
        "scope": "preview",
        "iat": int(time.time()),
        "exp": int(time.time()) + 1800
    }
    return jwt.encode(payload, ONLYOFFICE_JWT_SECRET, algorithm=ONLYOFFICE_JWT_ALG)


def verify_preview_token(token, file_id):
    try:
        decoded = jwt.decode(token, ONLYOFFICE_JWT_SECRET, algorithms=[ONLYOFFICE_JWT_ALG], leeway=120)
        if decoded.get("file_id") != file_id or decoded.get("scope") != "preview":
            return None
        return decoded
    except Exception:
        return None


# ================= SESSION GUARD =================
@app.before_request
def check_restart():

    # ===== مسارات عامة (لا تحتاج تسجيل دخول) =====
    public_paths = (
        "/",
        "/login",
        "/logout",
        "/static/",
    )

    # ===== استثناء OnlyOffice =====
    if request.path.startswith((
        "/file/raw/",
        "/onlyoffice/",
        "/static/"
    )):
        return

    # ===== السماح بالمسارات العامة =====
    if request.path in public_paths:
        return

    # ===== التحقق من الجلسة =====
    if "user" not in session:
        return redirect(url_for("login"))

    # ===== تحديث الهوية من Excel (مصدر الحقيقة) =====
    info = get_user_from_excel(session.get("user"))
    if not info or info.get("status") != "نشط":
        session.clear()
        return redirect(url_for("login"))
    session["email"] = info.get("email")
    session["user"] = info.get("email")
    session["name"] = info.get("name")
    session["role"] = info.get("role")
    session["department"] = info.get("department")
    session["extra_departments"] = info.get("extra_departments") or []
    session["apps"] = info.get("apps") or []
    session["company"] = info.get("company")
    session["branch"] = info.get("branch")
    session["force_reset"] = info.get("force_reset", 0)


    if "_run" not in session:
        session["_run"] = APP_RUN_ID
    elif session["_run"] != APP_RUN_ID:
        session.clear()
        return redirect(url_for("login"))



# ================= ROUTES =================
@app.route("/health", methods=["GET"])
def health():
    """Health check for load balancers and monitoring (no auth required)."""
    try:
        db = get_db()
        db.execute("SELECT 1")
        db.close()
        db_ok = True
    except Exception:
        db_ok = False
    status = 200 if db_ok else 503
    return jsonify({"status": "ok" if db_ok else "degraded", "database": "ok" if db_ok else "error"}), status


@app.route("/", methods=["GET"])
def login_root():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if require_login():
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "").strip()

        user = authenticate(u, p)
        if not user:
            return render_template("login.html", error="بيانات الدخول غير صحيحة")

        session["user"] = user["email"]
        session["email"] = user["email"]
        session["name"] = user["name"]
        session["role"] = user["role"]
        session["department"] = user["department"]
        session["extra_departments"] = user.get("extra_departments") or []
        session["apps"] = user.get("apps") or []
        session["company"] = user.get("company")
        session["branch"] = user.get("branch")
        session["force_reset"] = user.get("force_reset", 0)

        logging.info(f"LOGIN {u}")

        return redirect(url_for("dashboard"))

    return render_template("login.html", error="")

from modules.files import (
    get_root_folders,
    get_files_in_folder,
    get_child_folders,
    get_folder,
    move_to_trash,
    restore_from_trash
)


@app.route("/dashboard")
def dashboard():
    if not require_login():
        return redirect(url_for("login"))

    folders = get_root_folders(session["user"])
    files = get_files_in_folder(session["user"])
    folders = [row_to_dict(f) for f in folders]
    files = [row_to_dict(f) for f in files]
    for f in folders:
        f["allowed_actions"] = get_allowed_actions(session["user"], "folder", f.get("folder_id"))
    for f in files:
        f["allowed_actions"] = get_allowed_actions(session["user"], "file", f.get("file_id"))

    return render_template(
        "dashboard.html",
        folders=folders,
        files=files,
        name=session["name"],
        username=session["user"],
        department=session["department"],
        role=session["role"],
        perm_role="owner",
        page_can_edit=True,
        current_folder_actions=None,
        current_folder=None,
        path=[],
    )


from modules.files import create_folder

@app.route("/folder/create", methods=["POST"])
def create_folder_route():
    if not require_login():
        return redirect(url_for("login"))

    name = safe_name(request.form.get("name"))
    parent_id = request.form.get("parent_id")
    if parent_id == "ROOT":
        parent_id = None

    if not name:
        return redirect(request.referrer or url_for("dashboard"))

    create_folder(
        name=name,
        owner=session["user"],
        parent_id=parent_id
    )

    logging.info(f"CREATE_FOLDER {name} by {session['user']}")
    log_event("create_folder", session["user"], request, item_type="folder", item_id=None, item_name=name, context={"parent_id": parent_id})

    return redirect(request.referrer or url_for("dashboard"))

@app.route("/file/create", methods=["POST"])
def create_file_route():
    if not require_login():
        return redirect(url_for("login"))

    name = safe_name(request.form.get("name"))
    parent_id = request.form.get("parent_id")

    if parent_id == "ROOT":
        parent_id = None

    if not name:
        return redirect(request.referrer or url_for("dashboard"))

    fid = f"FILE_{int(datetime.now().timestamp() * 1000)}"
    path = os.path.join("uploads", f"{fid}_{name}.txt")

    with open(path, "w", encoding="utf-8") as f:
        f.write("")

    db = get_db()
    db.execute(
        """INSERT INTO files (file_id, name, owner, folder_id, path, mime, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (
            fid,
            name,
            session["user"],
            parent_id,
            path,
            "text/plain",
            datetime.now().strftime("%Y-%m-%d %H:%M")
        )
    )
    db.commit()
    db.close()

    logging.info(f"CREATE_FILE {name} by {session['user']}")
    log_event("create_file", session["user"], request, item_type="file", item_id=fid, item_name=name, context={"folder_id": parent_id})
    return redirect(request.referrer or url_for("dashboard"))

from modules.files import create_onlyoffice_file

@app.route("/file/create_onlyoffice", methods=["POST"])
def create_onlyoffice():
    if not require_login():
        return redirect(url_for("login"))

    name = safe_name(request.form.get("name"))
    ext = request.form.get("ext")
    folder_id = request.form.get("folder_id")
    if folder_id == "ROOT" or folder_id == "":
        folder_id = None

    if ext not in ("xlsx", "docx", "pptx") or not name:
        abort(400)

    fid = create_onlyoffice_file(
        owner=session["user"],
        folder_id=folder_id,
        name=name,
        ext=ext
    )

    db = get_db()
    row = db.execute("SELECT path, file_type FROM files WHERE file_id=?", (fid,)).fetchone()
    db.close()
    if row:
        content = extract_text_for_index(row["path"], row["file_type"])
        index_item("file", fid, f"{name}.{ext}", content, "", session.get("department"), session["user"], datetime.now().strftime("%Y-%m-%d %H:%M"))

    evaluate_automation_rules("file_created", {
        "file_id": fid,
        "file_type": "sheet" if ext == "xlsx" else "doc" if ext == "docx" else "slide",
        "folder_id": folder_id,
        "department": session.get("department")
    })

    log_event("create_onlyoffice", session["user"], request, item_type="file", item_id=fid, item_name=f"{name}.{ext}", context={"folder_id": folder_id})
    return redirect(request.referrer or url_for("dashboard"))

from modules.permissions import (
    require_permission,
    get_user_role,
    get_effective_role,
    get_cell_rules_for_user,
    is_cell_edit_allowed,
    resolve_item_access,
    can_access_dashboard,
    can_admin_access_dashboard,
    get_allowed_actions,
    normalize_expires_at,
    encode_target_value,
    parse_target_value,
    get_share_scope,
    is_share_expired,
    find_expired_share_access
)

@app.route("/folder/<folder_id>")
def open_folder(folder_id):

    if not require_login():
        return redirect(url_for("login"))

    access = resolve_item_access("folder", folder_id, session["user"], session["department"])
    if not access.get("allowed"):
        expired = find_expired_share_access("folder", folder_id, session["user"], session["department"])
        if expired:
            log_share_expired(session["user"], request, "folder", folder_id, context=expired)
        else:
            log_share_denied(session["user"], request, "folder", folder_id, access.get("reason", "no_permission"))
        abort(403)

    db = get_db()
    folder = db.execute("SELECT * FROM folders WHERE folder_id=?", (folder_id,)).fetchone()
    db.close()
    if not folder:
        return "Not found", 404

    if folder["owner"] == session["user"]:
        folders = get_child_folders(session["user"], folder_id)
        files = get_files_in_folder(session["user"], folder_id)
        path = get_folder_path(folder_id, session["user"])
    else:
        db = get_db()
        all_folders = db.execute(
            "SELECT * FROM folders WHERE parent_id=? AND is_trashed=0",
            (folder_id,)
        ).fetchall()
        all_files = db.execute(
            """SELECT f.*, c.category AS classification
               FROM files f
               LEFT JOIN file_classifications c ON f.file_id = c.file_id
               WHERE f.folder_id=? AND f.is_trashed=0""",
            (folder_id,)
        ).fetchall()
        db.close()

        folders = []
        for f in all_folders:
            f_access = resolve_item_access("folder", f["folder_id"], session["user"], session["department"])
            if f_access.get("allowed"):
                folders.append(f)

        files = []
        for f in all_files:
            f_access = resolve_item_access("file", f["file_id"], session["user"], session["department"])
            if f_access.get("allowed"):
                files.append(f)

        # Build path without owner filter
        path = []
        current = folder_id
        db = get_db()
        while current:
            row = db.execute(
                "SELECT folder_id, name, parent_id FROM folders WHERE folder_id=?",
                (current,)
            ).fetchone()
            if not row:
                break
            path.insert(0, row)
            current = row["parent_id"]
        db.close()

        log_share_access(session["user"], request, "folder", folder_id, context={
            "role": access.get("role"),
            "scope": access.get("share", {}).get("scope"),
            "expires_at": access.get("share", {}).get("expires_at")
        })

    folders = [row_to_dict(f) for f in folders]
    files = [row_to_dict(f) for f in files]
    for f in folders:
        f["allowed_actions"] = get_allowed_actions(session["user"], "folder", f.get("folder_id"))
    for f in files:
        f["allowed_actions"] = get_allowed_actions(session["user"], "file", f.get("file_id"))
    current_folder_actions = get_allowed_actions(session["user"], "folder", folder_id)

    # Dashboards linked to this folder (BI)
    db = get_db()
    rows = db.execute(
        "SELECT internal_id, title FROM bi_dashboards WHERE linked_folder_id = ?",
        (folder_id,),
    ).fetchall()
    db.close()
    folder_dashboards = [dict(r) for r in rows]
    folder_dashboards = [
        d
        for d in folder_dashboards
        if can_user_view_bi_dashboard(
            session["user"],
            d["internal_id"],
            department=session.get("department"),
            role=session.get("role"),
        )
    ]

    return render_template(
        "dashboard.html",
        folders=folders,
        files=files,
        current_folder=folder,
        path=path,
        username=session["user"],
        name=session["name"],
        role=session["role"],
        department=session["department"],
        perm_role=access.get("role"),
        page_can_edit=current_folder_actions.get("edit", False),
        current_folder_actions=current_folder_actions,
        folder_dashboards=folder_dashboards,
    )

@app.route("/restore/<item_type>/<item_id>", methods=["POST"])
def restore_item(item_type, item_id):
    if not require_login():
        return redirect(url_for("login"))

    role = get_user_role(
        item_type,
        item_id,
        session["user"],
        session["department"]
    )

    if role != "owner":
        return "Only owner can restore", 403

    restore_from_trash(item_type, item_id, session["user"])
    log_event("restore", session["user"], request, item_type=item_type, item_id=item_id, context={})
    return redirect(url_for("dashboard"))

from modules.files import rename_item

@app.route("/rename/<item_type>/<item_id>", methods=["POST"])
def rename(item_type, item_id):
    if not require_login():
        return redirect(url_for("login"))

    role = get_user_role(
        item_type,
        item_id,
        session["user"],
        session["department"]
    )

    if role not in ("editor", "owner"):
        return "No permission to rename", 403

    new_name = safe_name(request.form.get("name"))
    if new_name:
        rename_item(item_type, item_id, new_name, session["user"])
        log_event("rename", session["user"], request, item_type=item_type, item_id=item_id, item_name=new_name, context={})

    return redirect(request.referrer or url_for("dashboard"))


from modules.files import move_item

@app.route("/move/<item_type>/<item_id>", methods=["POST"])
def move(item_type, item_id):
    if not require_login():
        return redirect(url_for("login"))

    actions = get_allowed_actions(session["user"], item_type, item_id)
    if not actions.get("move", False):
        log_action_denied(session["user"], item_type, item_id, "move", "role")
        return "Forbidden: role", 403

    target = request.form.get("target_folder")

    if target == "ROOT" or target == "":
        target = None

    move_item(item_type, item_id, target, session["user"])
    log_event("move", session["user"], request, item_type=item_type, item_id=item_id, context={"target": target})
    if item_type == "file":
        evaluate_automation_rules("file_moved", {
            "file_id": item_id,
            "folder_id": target,
            "department": session.get("department")
        })
    return redirect(request.referrer or url_for("dashboard"))


from modules.files import get_trashed_items

@app.route("/trash")
def trash_view():
    if not require_login():
        return redirect(url_for("login"))

    log_event("trash_view", session["user"], request, item_type="trash", item_id="home", context={})

    folders, files = get_trashed_items(session["user"])
    return render_template(
        "trash.html",
        folders=folders,
        files=files,
        username=session["user"]
    )

# ================= TRASH (MOVE TO TRASH) =================
@app.route("/trash/<item_type>/<item_id>", methods=["POST"])
def trash_item(item_type, item_id):
    if not require_login():
        return redirect(url_for("login"))

    role = get_user_role(
        item_type,
        item_id,
        session["user"],
        session["department"]
    )

    if role != "owner":
        return "Only owner can delete", 403

    move_to_trash(item_type, item_id, session["user"])
    logging.info(f"TRASH {item_type}:{item_id} by {session['user']}")
    log_event("trash", session["user"], request, item_type=item_type, item_id=item_id, context={})
    return redirect(request.referrer or url_for("dashboard"))

from modules.files import save_uploaded_file

@app.route("/upload", methods=["POST"])
def upload():
    if not require_login():
        return redirect(url_for("login"))

    folder_id = request.form.get("folder_id")

    # 🔐 تحقق من الصلاحية
    if folder_id:
        role = get_user_role(
            "folder",
            folder_id,
            session["user"],
            session["department"]
        )
        if role not in ("editor", "owner"):
            abort(403)

    f = request.files.get("file")
    if not f or f.filename == "":
        return redirect(request.referrer or url_for("dashboard"))

    fid = save_uploaded_file(
        f,
        owner=session["user"],
        folder_id=folder_id if folder_id else None
    )

    logging.info(f"UPLOAD {f.filename} by {session['user']}")
    log_event("upload", session["user"], request, item_type="file", item_id=fid, item_name=f.filename, context={"folder_id": folder_id})

    db = get_db()
    row = db.execute("SELECT path, file_type FROM files WHERE file_id=?", (fid,)).fetchone()
    db.close()
    if row:
        content = extract_text_for_index(row["path"], row["file_type"])
        index_item("file", fid, f.filename, content, "", session.get("department"), session["user"], datetime.now().strftime("%Y-%m-%d %H:%M"))
        evaluate_automation_rules("file_created", {
            "file_id": fid,
            "file_type": row["file_type"],
            "folder_id": folder_id,
            "department": session.get("department")
        })
    return redirect(request.referrer or url_for("dashboard"))



@app.route("/create_sheet", methods=["POST"])
def create_sheet():
    if not require_login():
        return redirect(url_for("login"))

    name = safe_name(request.form.get("sheet_name"))
    if not name:
        return redirect(url_for("dashboard"))

    sheet_id = f"SHEET_{int(datetime.now(timezone.utc).timestamp())}"
    filename = f"{sheet_id}__{name}.xlsx"
    path = os.path.join(SHEETS_DIR, filename)

    create_blank_excel(path, name)

    db = get_db()
    db.execute(
        "INSERT INTO sheets (sheet_id, sheet_name, owner, file_path, created_at) VALUES (?,?,?,?,?)",
        (sheet_id, name, session["user"], path, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    db.commit()
    db.close()

    logging.info(f"CREATE_SHEET {sheet_id}")
    return redirect(url_for("dashboard"))

@app.route("/sheet/<sheet_id>")
def view_sheet(sheet_id):
    if not require_login():
        return redirect(url_for("login"))

    db = get_db()
    sheet = db.execute(
        "SELECT * FROM sheets WHERE sheet_id = ?",
        (sheet_id,)
    ).fetchone()
    db.close()

    if not sheet or sheet["owner"] != session["user"]:
        return "Access denied", 403

    return render_template("sheet_view.html", **sheet)

def _build_editor_config_for_file(file_id, f, access, session):
    """Build OnlyOffice editor config. Used by open_editor and editor-config API.
    document.key = file_id_v{version_no}_{nonce} — nonce forces fresh DocumentServer session on each open (fixes hang after logout/login).
    بعد مرور CELL_LOCK_AFTER_HOURS: فقط المالك يعدل؛ غير المالك عرض فقط."""
    role = access.get("role")
    try:
        from modules.excel_links import is_master_file
        if is_master_file(file_id):
            mode = "view"
        else:
            mode = "edit" if role in ("editor", "owner") else "view"
    except Exception:
        mode = "edit" if role in ("editor", "owner") else "view"
    # قفل التعديل بعد المدة: فقط المالك يعدل
    lock_info = get_file_edit_lock_info(file_id)
    if lock_info.get("locked") and lock_info.get("owner") and session.get("user") != lock_info["owner"]:
        mode = "view"
    ext = f["name"].split(".")[-1].lower()
    doc_type_map = {
        "xlsx": "spreadsheet", "xls": "spreadsheet",
        "docx": "text", "doc": "text",
        "pptx": "presentation", "ppt": "presentation"
    }
    access_token = generate_file_access_token(file_id, session["user"])
    file_url = f"{BASE_URL}/file/raw/{file_id}?token={access_token}"
    db = get_db()
    ver = db.execute(
        "SELECT MAX(version_no) AS max_v FROM file_versions WHERE file_id=?",
        (file_id,)
    ).fetchone()
    version_no = int(ver["max_v"] or 0)
    nonce = uuid.uuid4().hex[:8]
    doc_key = f"{file_id}_v{version_no}_{nonce}"
    db.close()
    payload = {
        "document": {
            "fileType": ext,
            "key": doc_key,
            "title": f["name"],
            "url": file_url,
            "permissions": {"download": False, "print": False, "copy": False, "edit": mode == "edit"}
        },
        "editorConfig": {
            "mode": mode,
            "lang": "ar",
            "callbackUrl": f"{BASE_URL}/onlyoffice/callback",
            "user": {"id": session["user"], "name": (session.get("name") or session.get("user") or "")},
            "customization": {"download": False, "print": False, "about": False, "help": False}
        }
    }
    token = generate_onlyoffice_token(payload)
    config = {
        "documentType": doc_type_map.get(ext, "text"),
        "document": payload["document"],
        "editorConfig": payload["editorConfig"],
        "token": token
    }
    return inject_permissions(config, session["user"], file_id, f["name"])


@app.route("/api/files/<file_id>/save-state")
def api_files_save_state(file_id):
    """Returns last_saved_at and version_no for Safe Exit polling."""
    if not require_login():
        return jsonify({"error": "unauthorized"}), 401
    access = resolve_item_access("file", file_id, session["user"], session["department"])
    if not access.get("allowed"):
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    row = db.execute(
        "SELECT updated_at FROM files WHERE file_id = ?", (file_id,)
    ).fetchone()
    ver = db.execute(
        "SELECT MAX(version_no) AS max_v FROM file_versions WHERE file_id = ?",
        (file_id,)
    ).fetchone() if row else None
    db.close()
    if not row:
        return jsonify({"error": "not_found"}), 404
    return jsonify({
        "last_saved_at": row["updated_at"] or "",
        "version_no": int(ver["max_v"] or 0) if ver else 0
    })


@app.route("/api/files/<file_id>/editor-config")
def api_files_editor_config(file_id):
    """Returns fresh editor config for refreshFile(). No reload, no redirect."""
    if not require_login():
        return jsonify({"error": "unauthorized"}), 401
    db = get_db()
    f = db.execute("SELECT * FROM files WHERE file_id = ?", (file_id,)).fetchone()
    db.close()
    if not f:
        return jsonify({"error": "not_found"}), 404
    f = dict(f)
    access = resolve_item_access("file", file_id, session["user"], session["department"])
    if not access.get("allowed"):
        return jsonify({"error": "forbidden"}), 403
    config = _build_editor_config_for_file(file_id, f, access, session)
    return jsonify(config)


@app.route("/api/files/<file_id>/participants")
def api_files_participants(file_id):
    """قائمة الأشخاص المشاركين في الملف (من فتح أو عدّل)."""
    if not require_login():
        return jsonify({"error": "unauthorized"}), 401
    access = resolve_item_access("file", file_id, session["user"], session["department"])
    if not access.get("allowed"):
        return jsonify({"error": "forbidden"}), 403
    participants = list_file_participants(file_id)
    out = []
    for p in participants:
        uid = p.get("user_id") or ""
        info = get_user_from_excel(uid) if uid else {}
        out.append({
            "user_id": uid,
            "name": info.get("name") or uid,
            "first_seen_at": p.get("first_seen_at") or "",
            "last_seen_at": p.get("last_seen_at") or "",
        })
    return jsonify({"participants": out})


@app.route("/editor/<file_id>")
def open_editor(file_id):
    if not require_login():
        return redirect(url_for("login"))

    try:
        db = get_db()
        f = db.execute(
            "SELECT * FROM files WHERE file_id = ?",
            (file_id,)
        ).fetchone()
        db.close()

        if not f:
            abort(404)

        access = resolve_item_access("file", file_id, session["user"], session["department"])
        if not access.get("allowed"):
            expired = find_expired_share_access("file", file_id, session["user"], session["department"])
            if expired:
                log_share_expired(session["user"], request, "file", file_id, context=expired)
            else:
                log_share_denied(session["user"], request, "file", file_id, access.get("reason", "no_permission"))
            abort(403)

        f = dict(f)
        # عند عدم وجود OnlyOffice (مثل Render المجاني): عرض صفحة توضيحية بدل كسر الصفحة
        if not (ONLYOFFICE_SERVER or "").strip():
            return render_template(
                "sheet_editor.html",
                sheet_name=f.get("name") or file_id,
                onlyoffice_server="",
                config=None,
                watermark_text="",
                file_id=file_id,
                file_dashboard=None,
                folder_id=f.get("folder_id"),
                can_access_bi=can_access_bi(),
                initial_last_saved_at=f.get("updated_at") or "",
                editor_unavailable=True,
            )

        try:
            config = _build_editor_config_for_file(file_id, f, access, session)
        except Exception as cfg_err:
            logging.warning("_build_editor_config_for_file %s: %s", file_id, cfg_err)
            return render_template(
                "sheet_editor.html",
                sheet_name=f.get("name") or file_id,
                onlyoffice_server=ONLYOFFICE_SERVER or "",
                config=None,
                watermark_text="",
                file_id=file_id,
                file_dashboard=None,
                folder_id=f.get("folder_id"),
                can_access_bi=can_access_bi(),
                initial_last_saved_at=f.get("updated_at") or "",
                editor_unavailable=True,
            )

        if access.get("owner") != session["user"]:
            log_share_access(session["user"], request, "file", file_id, context={
                "role": access.get("role"),
                "scope": access.get("share", {}).get("scope"),
                "expires_at": access.get("share", {}).get("expires_at"),
                "target_type": access.get("share", {}).get("target_type"),
                "target_value": access.get("share", {}).get("target_value")
            })

        add_file_participant(file_id, session["user"])
        log_event("file_opened", session["user"], request, item_type="file", item_id=file_id, item_name=f.get("name", ""), context={
            "role": access.get("role")
        })
        watermark_text = f"{session.get('user', '')} | {f.get('name', '')}" if WATERMARK_ENABLED else ""
        db = get_db()
        row = db.execute(
            "SELECT internal_id, title FROM bi_dashboards WHERE linked_file_id = ?",
            (file_id,),
        ).fetchone()
        db.close()
        file_dashboard = None
        if row:
            row = dict(row)
            if can_user_view_bi_dashboard(
                session["user"],
                row["internal_id"],
                department=session.get("department"),
                role=session.get("role"),
            ):
                file_dashboard = row
        return render_template(
            "sheet_editor.html",
            sheet_name=f.get("name", ""),
            onlyoffice_server=ONLYOFFICE_SERVER,
            config=config,
            watermark_text=watermark_text,
            file_id=file_id,
            file_dashboard=file_dashboard,
            folder_id=f.get("folder_id"),
            can_access_bi=can_access_bi(),
            initial_last_saved_at=f.get("updated_at") or "",
            editor_unavailable=False,
        )
    except Exception as e:
        logging.exception("open_editor %s: %s", file_id, e)
        raise

@app.route("/files/<sheet_id>.xlsx")
def serve_excel(sheet_id):
    if not require_login():
        abort(401)
    if "user" in session:
        log_download_blocked(session.get("user"), sheet_id, "raw_sheet_blocked", item_type="sheet")
        abort(403)

    role = get_user_role(
        "sheet",
        sheet_id,
        session["user"],
        session["department"]
    )

    if role is None:
        abort(403)

    db = get_db()
    sheet = db.execute(
        "SELECT * FROM sheets WHERE sheet_id = ?",
        (sheet_id,)
    ).fetchone()
    db.close()

    return send_file(sheet["file_path"], as_attachment=False)

@app.route("/uploads/<file_id>")
def serve_uploaded_file(file_id):

    abort(403)


def verify_onlyoffice_request():
    token = None

    if request.args.get("token"):
        token = request.args.get("token")

    elif request.json and request.json.get("token"):
        token = request.json.get("token")

    elif request.json and request.json.get("payload", {}).get("token"):
        token = request.json["payload"]["token"]

    if not token:
        return False

    try:
        jwt.decode(
            token,
            ONLYOFFICE_JWT_SECRET,
            algorithms=[ONLYOFFICE_JWT_ALG],
            leeway=120  # 2 minutes leeway for Docker/host time drift
        )
        return True
    except Exception as e:
        logging.warning(f"ONLYOFFICE JWT FAIL: {e}")
        return False


@app.route("/file/raw/<file_id>")
def serve_onlyoffice_file(file_id):
    # OnlyOffice فقط — لا يُسمح بالتحميل إلا عبر token صالح
    token = request.args.get("token", "")
    token_payload = verify_file_access_token(token, file_id) if token else None
    if "user" in session:
        log_download_blocked(session.get("user"), file_id, "session_raw_blocked")
        abort(403, description="Download is disabled by policy")
    if token and not token_payload:
        log_download_blocked("anonymous", file_id, "invalid_or_expired_token")
        abort(403, description="Invalid or expired token")
    if not ALLOW_DOWNLOAD and not token_payload:
        log_download_blocked("anonymous", file_id, "missing_or_invalid_token")
        abort(403, description="Download is disabled by policy")

    access_user = (token_payload or {}).get("user_id") or session.get("user")
    if not access_user:
        log_download_blocked("anonymous", file_id, "missing_token_user")
        abort(403, description="Download is disabled by policy")
    access_department = get_user_department(access_user) or session.get("department")

    access = resolve_item_access("file", file_id, access_user, access_department)
    if not access.get("allowed"):
        log_download_blocked(access_user, file_id, access.get("reason", "no_permission"))
        expired = find_expired_share_access("file", file_id, access_user, access_department)
        if expired:
            log_share_expired(access_user, request, "file", file_id, context=expired)
        else:
            log_share_denied(access_user, request, "file", file_id, access.get("reason", "no_permission"), context={
                "raw_access": True
            })
        abort(403, description="Download is disabled by policy")

    if access.get("owner") != access_user:
        log_share_access(access_user, request, "file", file_id, context={
            "raw_access": True,
            "role": access.get("role"),
            "scope": access.get("share", {}).get("scope")
        })
    db = get_db()
    row = db.execute(
        "SELECT path, name FROM files WHERE file_id = ?",
        (file_id,)
    ).fetchone()
    db.close()

    if not row:
        abort(404)

    return send_file(
        row["path"],
        as_attachment=False,
        download_name=row["name"]
    )

@app.route("/onlyoffice/callback", methods=["POST"])
def onlyoffice_callback():
    if not verify_onlyoffice_request():
        logging.warning("ONLYOFFICE CALLBACK VERIFICATION FAILED")
        return {"error": 1}

    data = request.json or {}
    status = data.get("status")
    if status not in (2, 6):
        logging.info("ONLYOFFICE CALLBACK status=%s (expected 2 or 6 for save)", status)
        return {"error": 0}

    logging.info("ONLYOFFICE CALLBACK status=%s saving document", status)
    if status in (2, 6):
        file_url = data.get("url")
        key = data.get("key")

        if not file_url or not key:
            return {"error": 0}

        # Extract file_id: url in callback points to Document Server (not our /file/raw).
        # Key format: {file_id}_v{version_no}_{nonce} (e.g. FILE_1771136186_v1_a1b2c3d4)
        m = re.search(r"/file/raw/([^/?]+)", str(file_url or ""))
        if m:
            file_id = m.group(1)
        else:
            # url is from Document Server; extract file_id from key
            km = re.match(r"^(.+)_v\d+_[a-f0-9]{8}$", str(key or ""))
            file_id = km.group(1) if km else key

        # Master file: reject direct save; only sync from children may write
        try:
            from modules.excel_links import is_master_file
            if is_master_file(file_id):
                return {"error": 1}
        except Exception:
            pass

        db = get_db()
        row = db.execute(
            "SELECT path, name, owner, file_type FROM files WHERE file_id = ?",
            (file_id,)
        ).fetchone()
        db.close()

        if not row:
            return {"error": 0}

        user_id = None
        if data.get("users"):
            try:
                user_id = data.get("users")[0]
            except Exception:
                user_id = None
        if not user_id and data.get("actions"):
            try:
                user_id = data.get("actions")[0].get("userid")
            except Exception:
                user_id = None
        if user_id:
            add_file_participant(file_id, user_id)
        owner = row["owner"]
        lock_info = get_file_edit_lock_info(file_id)
        if lock_info.get("locked") and owner and user_id != owner:
            logging.info("ONLYOFFICE CALLBACK: file %s locked for non-owner %s", file_id, user_id)
            return {"error": 1}

        r = requests.get(file_url, timeout=60)
        if r.status_code != 200:
            logging.warning("ONLYOFFICE CALLBACK download failed file_id=%s status=%s url=%s", file_id, r.status_code, (file_url or "")[:120])
            return {"error": 0}

        temp_path = f"{row['path']}.new"
        with open(temp_path, "wb") as f:
            f.write(r.content)

        # Cell-level permissions for spreadsheets
        diff = []
        if row["file_type"] == "sheet":
            diff = build_excel_diff(row["path"], temp_path)
        if row["file_type"] == "sheet" and user_id:
            rules = get_cell_rules_for_user(file_id, user_id)
            if rules:
                for d in diff:
                    if not is_cell_edit_allowed(file_id, user_id, d.get("sheet"), f"{d.get('col_letter')}{d.get('row')}"):
                        log_event(
                            "cell_violation",
                            user_id,
                            request,
                            item_type="file",
                            item_id=file_id,
                            item_name=row["name"],
                            context={"sheet": d.get("sheet"), "cell": f"{d.get('col_letter')}{d.get('row')}"}
                        )
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass
                        return {"error": 1}

        # Always write file on status=2/6 — Never skip. Hash check only for version creation.
        with open(row["path"], "wb") as f:
            f.write(r.content)
        try:
            os.remove(temp_path)
        except Exception:
            pass

        # إصدار نسخة فقط عند تغيير المحتوى (إضافة/حذف بيانات)، وليس على كل عملية حفظ
        content_changed = True
        try:
            hash_new = _sha256_file(row["path"])
            hash_main = _get_latest_version_hash(file_id)
            if hash_new and hash_main and hash_new == hash_main:
                content_changed = False
        except Exception:
            pass

        if content_changed:
            if lock_info.get("locked") and user_id == owner and not lock_info.get("issued_version_exists"):
                ensure_issued_version(file_id, row["path"], VERSIONS_DIR, user_id or owner)
            if user_id:
                create_version(file_id, row["path"], user_id, "autosave", VERSIONS_DIR, version_type="autosave", skip_if_unchanged=True)
            ensure_periodic_versions(file_id, row["path"], user_id or row["owner"], VERSIONS_DIR)
            db = get_db()
            db.execute("UPDATE files SET updated_at=? WHERE file_id=?", (
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                file_id
            ))
            db.commit()
            db.close()
            enqueue_refresh_for_file(file_id, trigger_type="on_change")
            content = extract_text_for_index(row["path"], row["file_type"])
            index_item("file", file_id, row["name"], content, "", "", user_id or row["owner"], datetime.now().strftime("%Y-%m-%d %H:%M"))
            if user_id:
                log_event("file_updated", user_id, request, item_type="file", item_id=file_id, item_name=row["name"], context={"file_type": row["file_type"]})
            if diff:
                log_event("cell_diff", user_id or row["owner"], request, item_type="file", item_id=file_id, item_name=row["name"], context={"changes": len(diff)})
            evaluate_automation_rules(
                "sheet_modified" if row["file_type"] == "sheet" else "file_updated",
                {"file_id": file_id, "file_type": row["file_type"], "department": session.get("department")}
            )
            try:
                from modules.bi_sync_trigger import trigger_bi_resync_for_file
                trigger_bi_resync_for_file(file_id)
            except Exception:
                pass
            if row["file_type"] == "sheet":
                try:
                    from modules.excel_links import is_child_linked, sync_child_to_master
                    if is_child_linked(file_id):
                        sync_child_to_master(file_id, triggered_by="callback")
                except Exception as e:
                    logging.warning("excel_links sync after callback failed: %s", e)

    return {"error": 0}


@app.route("/share", methods=["POST"])
def share_item():
    if not require_login():
        return redirect(url_for("login"))

    item_type = request.form.get("item_type")
    item_id = request.form.get("item_id")
    target_type = request.form.get("target_type")  # user | department | public
    target_value = request.form.get("target_value")
    role = request.form.get("role")
    expires_at = request.form.get("expires_at")
    share_scope = request.form.get("share_scope") or ""

    if item_type not in ("file", "folder") or not item_id:
        abort(400)

    actions = get_allowed_actions(session["user"], item_type, item_id)
    if not actions.get("share", False):
        log_action_denied(session["user"], item_type, item_id, "share", "role")
        abort(403)

    if role not in ("viewer", "editor"):
        abort(400)

    if item_type == "file":
        share_scope = "file"
    elif share_scope not in ("folder", "recursive"):
        share_scope = "folder"

    policy = get_department_policy(session.get("department"))
    if target_type == "public" and not policy.get("allow_public_share", True):
        abort(403)
    if target_type == "department" and not policy.get("share_outside_department", True):
        if target_value and target_value != session.get("department"):
            abort(403)
    if target_type == "user" and not policy.get("share_outside_department", True):
        info = get_user_from_excel(target_value)
        if info and info.get("department") != session.get("department"):
            abort(403)
    if target_type == "external" and not policy.get("share_outside_department", True):
        abort(403)
    if target_type == "role" and not target_value:
        abort(400)

    if target_type not in ("user", "department", "public", "role", "external"):
        abort(400)

    if target_type != "public" and not target_value:
        abort(400)

    expires_at = normalize_expires_at(expires_at)
    if target_type == "public":
        target_value = ""

    target_value = encode_target_value(target_value, scope=share_scope, external=(target_type == "external"))

    db = get_db()
    db.execute("""
        INSERT INTO permissions
        (item_type, item_id, owner, target_type, target_value, role, expires_at, created_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (
        item_type,
        item_id,
        session["user"],
        target_type,
        target_value,
        role,
        expires_at,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))
    db.commit()
    db.close()

    log_event("share", session["user"], request, item_type=item_type, item_id=item_id, context={
        "target_type": target_type,
        "target_value": target_value,
        "role": role,
        "expires_at": expires_at,
        "scope": share_scope
    })
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/permissions/cell", methods=["POST"])
def set_cell_permissions():
    if not require_login():
        return redirect(url_for("login"))

    item_type = request.form.get("item_type", "file")
    item_id = request.form.get("item_id")
    target_type = request.form.get("target_type")
    target_value = request.form.get("target_value")
    sheet_name = request.form.get("sheet_name")
    scope_type = request.form.get("scope_type")
    scope_value = request.form.get("scope_value")
    perm = request.form.get("perm", "view")

    if not item_id or not scope_type or not scope_value or not target_type:
        return redirect(request.referrer or url_for("dashboard"))

    role = get_user_role(item_type, item_id, session["user"], session["department"])
    if role != "owner":
        abort(403)

    db = get_db()
    db.execute("""
        INSERT INTO cell_permissions
        (item_type, item_id, target_type, target_value, sheet_name, scope_type, scope_value, perm, created_at, created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        item_type,
        item_id,
        target_type,
        target_value,
        sheet_name,
        scope_type,
        scope_value,
        perm,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        session["user"]
    ))
    db.commit()
    db.close()

    log_event(
        "cell_permission",
        session["user"],
        request,
        item_type=item_type,
        item_id=item_id,
        context={
            "target_type": target_type,
            "target_value": target_value,
            "sheet_name": sheet_name,
            "scope_type": scope_type,
            "scope_value": scope_value,
            "perm": perm
        }
    )
    return redirect(request.referrer or url_for("dashboard"))

@app.route("/shared")
def shared_view():
    if not require_login():
        return redirect(url_for("login"))

    log_event("shared_view", session["user"], request, item_type="share", item_id="shared", context={})

    db = get_db()

    # العناصر التي تمت مشاركتها مع المستخدم
    rows = db.execute("""
        SELECT p.item_type, p.item_id, p.role, p.target_type, p.target_value, p.expires_at, p.owner,
               f.name AS file_name, f.created_at AS file_created,
               d.name AS folder_name, d.created_at AS folder_created
        FROM permissions p
        LEFT JOIN files f
            ON p.item_type = 'file' AND p.item_id = f.file_id
        LEFT JOIN folders d
            ON p.item_type = 'folder' AND p.item_id = d.folder_id
        WHERE p.owner != ?
        ORDER BY p.created_at DESC
    """, (
        session["user"],
    )).fetchall()

    db.close()

    folders = []
    files = []

    for r in rows:
        base_value, _ = parse_target_value(r["target_value"])
        if r["target_type"] == "user" and base_value != session["user"]:
            continue
        if r["target_type"] == "department" and base_value != session["department"]:
            continue
        if r["target_type"] == "role" and base_value != session.get("role"):
            continue
        if r["target_type"] == "external" and base_value != session["user"]:
            continue
        if r["target_type"] not in ("user", "department", "role", "public", "external"):
            continue
        if is_share_expired(r["expires_at"]):
            continue

        access = resolve_item_access(r["item_type"], r["item_id"], session["user"], session["department"])
        if not access.get("allowed"):
            continue
        if access.get("owner") == session["user"]:
            continue

        scope = access.get("share", {}).get("scope") if access.get("share") else get_share_scope(r["item_type"], r["target_value"])
        expires = access.get("share", {}).get("expires_at") if access.get("share") else r["expires_at"]

        if r["item_type"] == "folder" and r["folder_name"]:
            folders.append({
                "folder_id": r["item_id"],
                "name": r["folder_name"],
                "created_at": r["folder_created"],
                "role": access.get("role"),
                "scope": scope,
                "expires_at": expires,
                "owner": r["owner"]
            })
        elif r["item_type"] == "file" and r["file_name"]:
            files.append({
                "file_id": r["item_id"],
                "name": r["file_name"],
                "created_at": r["file_created"],
                "role": access.get("role"),
                "scope": scope,
                "expires_at": expires,
                "owner": r["owner"]
            })

    folders = [row_to_dict(f) for f in folders]
    files = [row_to_dict(f) for f in files]
    for f in folders:
        f["allowed_actions"] = get_allowed_actions(session["user"], "folder", f.get("folder_id"))
    for f in files:
        f["allowed_actions"] = get_allowed_actions(session["user"], "file", f.get("file_id"))

    return render_template(
        "shared.html",
        folders=folders,
        files=files,
        username=session["user"],
        name=session["name"],
        department=session["department"],
        role=session["role"]
    )


@app.route("/api/search")
def api_search():
    if not require_login():
        return {"results": []}

    q = (request.args.get("q") or "").strip()
    if not q:
        return {"results": []}

    results = search_index(
        q,
        owner=session["user"],
        filters={
            "department": (request.args.get("department") or "").strip()
        }
    )
    return {"results": results}


# ----- Excel Links (Master/Child aggregation) -----
@app.route("/api/files/<master_id>/links", methods=["GET"])
def api_files_links_list(master_id):
    if not require_login():
        abort(401)
    access = resolve_item_access("file", master_id, session["user"], session.get("department"))
    if not access.get("allowed") or access.get("role") not in ("editor", "owner"):
        abort(403)
    try:
        from modules.excel_links import list_links, get_schema, get_sync_logs
        links = list_links(master_id)
        schema = get_schema(master_id)
        logs = get_sync_logs(master_id, limit=10)
        return {"ok": True, "links": links, "schema": schema, "sync_logs": logs}
    except Exception as e:
        logging.exception("api_files_links_list: %s", e)
        return {"ok": False, "error": str(e)}, 500


@app.route("/api/files/<master_id>/links", methods=["POST"])
def api_files_links_create(master_id):
    if not require_login():
        abort(401)
    access = resolve_item_access("file", master_id, session["user"], session.get("department"))
    if not access.get("allowed") or access.get("role") not in ("editor", "owner"):
        abort(403)
    data = request.get_json(silent=True) or {}
    child_file_id = (data.get("child_file_id") or "").strip()
    sheet_name = (data.get("sheet_name") or "Sheet1").strip()
    header_mode = (data.get("header_mode") or "auto").strip().lower()
    if header_mode not in ("auto", "row1", "row2", "row3"):
        header_mode = "auto"
    columns_json = data.get("columns_json")
    sync_mode = (data.get("sync_mode") or "append").strip().lower()
    if sync_mode not in ("append", "upsert"):
        sync_mode = "append"
    if not child_file_id:
        return {"ok": False, "error": "child_file_id required"}, 400
    if child_file_id == master_id:
        return {"ok": False, "error": "لا يمكن ربط الملف بنفسه"}, 400
    child_access = resolve_item_access("file", child_file_id, session["user"], session.get("department"))
    if not child_access.get("allowed"):
        abort(403)
    try:
        from modules.excel_links import create_link, detect_master_headers, get_master_path, propagate_master_schema_to_child
        header_row_index = 1
        if columns_json is None:
            path = get_master_path(master_id)
            if not path:
                return {"ok": False, "error": "Master file not found"}, 404
            detected = detect_master_headers(path, sheet_name, header_mode)
            if not detected.get("ok") or not detected.get("business_columns"):
                return {
                    "ok": False,
                    "error": detected.get("warning", "No headers found. Put headers in Row 1 or choose the correct sheet.")
                }, 400
            columns_json = json.dumps(detected["business_columns"])
            header_row_index = detected.get("header_row_index", 1)
        else:
            cols = json.loads(columns_json) if isinstance(columns_json, str) else (columns_json or [])
            if not cols or (len(cols) == 1 and cols[0].startswith("_")):
                return {"ok": False, "error": "No headers found. Put headers in Row 1 or choose the correct sheet."}, 400
        create_link(
            master_file_id=master_id,
            child_file_id=child_file_id,
            child_owner_user_id=session.get("user"),
            child_owner_email=session.get("user"),
            sheet_name=sheet_name,
            columns_json=columns_json,
            sync_mode=sync_mode,
            header_row_index=header_row_index
        )
        propagate_master_schema_to_child(master_id, child_file_id)
        return {"ok": True}
    except Exception as e:
        logging.exception("api_files_links_create: %s", e)
        err = str(e)
        if "UNIQUE" in err or "IntegrityError" in err:
            err = "الربط موجود مسبقاً. إذا كان معلقاً، تم إعادة تفعيله."
        return {"ok": False, "error": err}, 500


@app.route("/api/files/<master_id>/links/push-schema", methods=["POST"])
def api_files_links_push_schema(master_id):
    """Push master schema to all active child files. Use after changing master column structure."""
    if not require_login():
        abort(401)
    access = resolve_item_access("file", master_id, session["user"], session.get("department"))
    if not access.get("allowed") or access.get("role") not in ("editor", "owner"):
        abort(403)
    try:
        from modules.excel_links import propagate_master_schema_to_all_children
        out = propagate_master_schema_to_all_children(master_id)
        return {"ok": True, "results": out.get("results", [])}
    except Exception as e:
        logging.exception("api_files_links_push_schema: %s", e)
        return {"ok": False, "error": str(e)}, 500


@app.route("/api/files/<master_id>/links/<child_id>/sync", methods=["POST"])
def api_files_links_sync(master_id, child_id):
    if not require_login():
        abort(401)
    access = resolve_item_access("file", master_id, session["user"], session.get("department"))
    if not access.get("allowed") or access.get("role") not in ("editor", "owner"):
        abort(403)
    try:
        from modules.excel_links import sync_child_to_master, get_link_by_child
        link = get_link_by_child(child_id)
        if not link or link["master_file_id"] != master_id:
            return {"ok": False, "error": "Link not found"}, 404
        result = sync_child_to_master(child_id, triggered_by="manual")
        if result.get("ok"):
            return {
                "ok": True,
                "rows_inserted": result.get("rows_inserted", 0),
                "rows_updated": result.get("rows_updated", 0),
                "version_created": result.get("version_created", False),
                "version_no": result.get("version_no")
            }
        return {"ok": False, "error": result.get("error", "sync failed")}, 500
    except Exception as e:
        logging.exception("api_files_links_sync: %s", e)
        return {"ok": False, "error": str(e)}, 500


@app.route("/api/files/<master_id>/links/<child_id>", methods=["DELETE"])
def api_files_links_delete(master_id, child_id):
    if not require_login():
        abort(401)
    access = resolve_item_access("file", master_id, session["user"], session.get("department"))
    if not access.get("allowed") or access.get("role") not in ("editor", "owner"):
        abort(403)
    try:
        from modules.excel_links import unlink, get_link_by_child
        link = get_link_by_child(child_id)
        if not link or link["master_file_id"] != master_id:
            return {"ok": False, "error": "Link not found"}, 404
        unlink(master_id, child_id)
        return {"ok": True}
    except Exception as e:
        logging.exception("api_files_links_delete: %s", e)
        return {"ok": False, "error": str(e)}, 500


@app.route("/api/files/excel-picker")
def api_files_excel_picker():
    """List Excel files for Excel Links modal dropdowns (exclude=file_id to skip one)."""
    if not require_login():
        return jsonify({"ok": False, "error": "unauthorized", "files": []}), 401
    exclude = request.args.get("exclude", "")
    try:
        db = get_db()
        rows = db.execute("""
            SELECT file_id, name FROM files
            WHERE owner = ? AND is_trashed = 0
            AND (file_type = 'sheet' OR path LIKE '%.xlsx' OR path LIKE '%.xls' OR name LIKE '%.xlsx' OR name LIKE '%.xls')
            ORDER BY name
        """, (session["user"],)).fetchall()
        db.close()
        files = [{"file_id": r["file_id"], "name": r["name"] or r["file_id"]} for r in rows if r["file_id"] != exclude]
        return {"ok": True, "files": files}
    except Exception as e:
        logging.exception("api_files_excel_picker: %s", e)
        return jsonify({"ok": False, "error": str(e), "files": []}), 500


@app.route("/api/files/<file_id>/sheets")
def api_files_sheets(file_id):
    """List sheet names in an Excel file (for Excel Links modal)."""
    if not require_login():
        return jsonify({"ok": False, "error": "unauthorized", "sheets": []}), 401
    access = resolve_item_access("file", file_id, session["user"], session.get("department"))
    if not access.get("allowed"):
        return jsonify({"ok": False, "error": "forbidden", "sheets": []}), 403
    try:
        from modules.excel_links import get_file_sheets
        sheets = get_file_sheets(file_id)
        return {"ok": True, "sheets": sheets if sheets else ["Sheet1"]}
    except Exception as e:
        logging.exception("api_files_sheets: %s", e)
        return jsonify({"ok": False, "error": str(e), "sheets": ["Sheet1"]}), 500


@app.route("/api/files/<file_id>/link-info")
def api_files_link_info(file_id):
    """Returns master or children link info for a file (for Excel Links modal)."""
    if not require_login():
        abort(401)
    access = resolve_item_access("file", file_id, session["user"], session.get("department"))
    if not access.get("allowed"):
        abort(403)
    try:
        from modules.excel_links import get_link_by_child, list_links, get_child_master, get_schema
        as_child = get_link_by_child(file_id)
        as_master = list_links(file_id) if access.get("role") in ("editor", "owner") else []
        master_of = get_child_master(file_id)
        schema = None
        if len(as_master) > 0:
            schema = get_schema(file_id)
            # Do NOT auto-call update_schema_from_master here - it must run only on explicit
            # "Push schema" / "Set Master" / "Create Link". Auto-update during link-info can cause
            # metadata churn that triggers OnlyOffice version-change and infinite reload loop.
        return {
            "ok": True,
            "is_child": as_child is not None,
            "child_link": as_child,
            "is_master": len(as_master) > 0,
            "children": as_master,
            "master_of": master_of,
            "schema": schema
        }
    except Exception as e:
        logging.exception("api_files_link_info: %s", e)
        return {"ok": False, "error": str(e)}, 500


@app.route("/api/files/<file_id>/links/schema-preview")
def api_files_links_schema_preview(file_id):
    """Preview detected schema (business + system columns). header_mode: auto|row1|row2|row3."""
    if not require_login():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    access = resolve_item_access("file", file_id, session["user"], session.get("department"))
    if not access.get("allowed"):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    sheet_name = (request.args.get("sheet_name") or "Sheet1").strip()
    header_mode = (request.args.get("header_mode") or "auto").strip().lower()
    if header_mode not in ("auto", "row1", "row2", "row3"):
        header_mode = "auto"
    try:
        from modules.excel_links import detect_master_headers, get_master_path, get_child_path
        path = get_master_path(file_id) or get_child_path(file_id)[0]
        if not path:
            return jsonify({"ok": False, "error": "File not found", "business_columns": [], "warning": "File path not found"}), 404
        detected = detect_master_headers(path, sheet_name, header_mode)
        if detected.get("ok"):
            return {
                "ok": True,
                "sheet_name": detected.get("sheet_name", sheet_name),
                "header_row_index": detected.get("header_row_index", 1),
                "business_columns": detected.get("business_columns", []),
                "system_columns": detected.get("system_columns", []),
                "canonical_columns": detected.get("canonical_columns", []),
                "preview_rows": detected.get("preview_rows", []),
                "warning": detected.get("warning"),
            }
        return jsonify({
            "ok": False,
            "error": detected.get("warning", "No headers found"),
            "business_columns": [],
            "system_columns": detected.get("system_columns", []),
            "warning": detected.get("warning"),
        }), 400
    except Exception as e:
        logging.exception("api_files_links_schema_preview: %s", e)
        return jsonify({"ok": False, "error": str(e), "business_columns": []}), 500


@app.route("/api/dashboards", methods=["POST"])
def api_dashboards_create():
    if not require_login():
        abort(403)
    if not has_dashboard_studio_access():
        abort(403)
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip()
    definition = payload.get("definition_json")
    if isinstance(definition, str):
        try:
            definition = json.loads(definition)
        except Exception:
            definition = {}
    if not isinstance(definition, dict):
        definition = {}
    if not name:
        abort(400)
    dashboard_id = generate_dashboard_id()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    db = get_db()
    db.execute("""
        INSERT INTO dashboards
        (dashboard_id, name, description, department, owner, status, definition_json, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        dashboard_id, name, description, session.get("department"), session.get("user"),
        "draft", json.dumps(definition, ensure_ascii=False), now, now
    ))
    version_id = f"VER_{uuid.uuid4().hex[:10].upper()}"
    db.execute("""
        INSERT INTO dashboard_versions
        (version_id, dashboard_id, created_by, created_at, reason, definition_json_snapshot)
        VALUES (?,?,?,?,?,?)
    """, (
        version_id, dashboard_id, session.get("user"), now, "manual",
        json.dumps(definition, ensure_ascii=False)
    ))
    db.commit()
    db.close()
    log_event("dashboard_created", session["user"], request, item_type="dashboard", item_id=dashboard_id, context={})
    return {"ok": True, "dashboard_id": dashboard_id}


@app.route("/api/dashboards/<dashboard_id>")
def api_dashboards_read(dashboard_id):
    if not require_login():
        abort(403)
    if not can_access_dashboard(session["user"], dashboard_id):
        abort(403)
    db = get_db()
    dashboard = db.execute(
        "SELECT * FROM dashboards WHERE dashboard_id = ?",
        (dashboard_id,)
    ).fetchone()
    if dashboard:
        dashboard = dict(dashboard)
    if dashboard:
        dashboard = dict(dashboard)
    db.close()
    if not dashboard:
        abort(404)
    d = dict(dashboard)
    try:
        d["definition_json"] = json.loads(d.get("definition_json") or "{}")
    except Exception:
        d["definition_json"] = {}
    return d


@app.route("/api/dashboards/<dashboard_id>", methods=["PUT"])
def api_dashboards_update(dashboard_id):
    if not require_login():
        abort(403)
    if not has_dashboard_studio_access():
        abort(403)
    if not can_access_dashboard(session["user"], dashboard_id):
        abort(403)
    payload = request.get_json(silent=True) or {}
    definition = payload.get("definition_json")
    if isinstance(definition, str):
        try:
            definition = json.loads(definition)
        except Exception:
            definition = {}
    if not isinstance(definition, dict):
        definition = {}
    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    db = get_db()
    db.execute("""
        UPDATE dashboards
        SET name=COALESCE(?, name),
            description=COALESCE(?, description),
            definition_json=?,
            updated_at=?
        WHERE dashboard_id=?
    """, (
        name if name else None,
        description if description else None,
        json.dumps(definition, ensure_ascii=False),
        now,
        dashboard_id
    ))
    version_id = f"VER_{uuid.uuid4().hex[:10].upper()}"
    db.execute("""
        INSERT INTO dashboard_versions
        (version_id, dashboard_id, created_by, created_at, reason, definition_json_snapshot)
        VALUES (?,?,?,?,?,?)
    """, (
        version_id, dashboard_id, session.get("user"), now, "manual",
        json.dumps(definition, ensure_ascii=False)
    ))
    db.commit()
    db.close()
    log_event("dashboard_updated", session["user"], request, item_type="dashboard", item_id=dashboard_id, context={})
    return {"ok": True}


@app.route("/api/dashboards/<dashboard_id>/publish", methods=["POST"])
def api_dashboards_publish(dashboard_id):
    if not require_login():
        abort(403)
    if not has_dashboard_studio_access():
        abort(403)
    if not can_access_dashboard(session["user"], dashboard_id):
        abort(403)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    db = get_db()
    db.execute(
        "UPDATE dashboards SET status='published', published_at=?, updated_at=? WHERE dashboard_id=?",
        (now, now, dashboard_id)
    )
    db.commit()
    db.close()
    log_event("dashboard_published", session["user"], request, item_type="dashboard", item_id=dashboard_id, context={})
    return {"ok": True}


@app.route("/api/dashboards/<dashboard_id>/refresh", methods=["POST"])
def api_dashboards_refresh(dashboard_id):
    if not require_login():
        abort(403)
    if not can_access_dashboard(session["user"], dashboard_id):
        abort(403)
    db = get_db()
    dashboard = db.execute(
        "SELECT * FROM dashboards WHERE dashboard_id = ?",
        (dashboard_id,)
    ).fetchone()
    db.close()
    if not dashboard:
        abort(404)
    return {"ok": True, "dashboard_id": dashboard_id}


@app.route("/api/dashboards/<dashboard_id>/repair", methods=["POST"])
def api_dashboards_repair(dashboard_id):
    if not require_login():
        abort(403)
    if not has_dashboard_studio_access():
        abort(403)
    if not can_access_dashboard(session["user"], dashboard_id):
        abort(403)
    payload = request.get_json(silent=True) or {}
    definition = payload.get("definition_json")
    if isinstance(definition, str):
        try:
            definition = json.loads(definition)
        except Exception:
            definition = {}
    if not isinstance(definition, dict):
        definition = {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    db = get_db()
    db.execute(
        "UPDATE dashboards SET definition_json=?, updated_at=? WHERE dashboard_id=?",
        (json.dumps(definition, ensure_ascii=False), now, dashboard_id)
    )
    version_id = f"VER_{uuid.uuid4().hex[:10].upper()}"
    db.execute("""
        INSERT INTO dashboard_versions
        (version_id, dashboard_id, created_by, created_at, reason, definition_json_snapshot)
        VALUES (?,?,?,?,?,?)
    """, (
        version_id, dashboard_id, session.get("user"), now, "repair",
        json.dumps(definition, ensure_ascii=False)
    ))
    db.commit()
    db.close()
    log_event("mapping_repaired", session["user"], request, item_type="dashboard", item_id=dashboard_id, context={})
    return {"ok": True}






    user = get_user_from_excel(username)
    db = get_db()
    dashboard = db.execute(
        "SELECT * FROM dashboards WHERE dashboard_id = ?",
        (dashboard_id,)
    ).fetchone()
    db.close()
    if not user or not dashboard:
        abort(404)
    try:
        definition = json.loads(dashboard.get("definition_json") or "{}")
    except Exception:
        definition = {}
    try:
        config = build_embed_config(
            dashboard_id=dashboard_id,
            definition=definition,
            user_context={
                "email": user["email"],
                "role": user["role"],
                "department": user["department"],
                "extra_departments": user.get("extra_departments") or [],
                "branch": user.get("branch"),
                "company": user.get("company")
            },
            mode="view"
        )
    except Exception as exc:
        log_access_violation("rls_test_failed", "dashboard", dashboard_id, str(exc))
        return {"ok": False, "error": str(exc)}, 400
    log_event(
        "rls_test",
        session["user"],
        request,
        item_type="dashboard",
        item_id=dashboard_id,
        context={"test_user": username}
    )
    return config


@app.route("/api/schema/preview")
def api_schema_preview():
    if not require_login():
        abort(403)
    file_id = (request.args.get("file_id") or "").strip()
    sheet = (request.args.get("sheet") or "").strip() or None
    if not file_id:
        abort(400)
    db = get_db()
    row = db.execute("SELECT path FROM files WHERE file_id=?", (file_id,)).fetchone()
    db.close()
    if not row:
        abort(404)
    try:
        df = pd.read_excel(row["path"], sheet_name=sheet if sheet else 0)
    except Exception:
        df = pd.read_excel(row["path"])
    df.columns = [str(c).strip() for c in df.columns]
    preview = df.head(20).fillna("").to_dict(orient="records")
    types = {c: str(df[c].dtype) for c in df.columns}
    return {"columns": df.columns.tolist(), "types": types, "preview": preview}


@app.route("/api/model/join/validate", methods=["POST"])
def api_model_join_validate():
    if not require_login():
        abort(403)
    payload = request.get_json(silent=True) or {}
    if not payload:
        abort(400)
    return {"ok": True}


@app.route("/api/visual/run", methods=["POST"])
def api_visual_run():
    if not require_login():
        abort(403)
    payload = request.get_json(silent=True) or {}
    definition = payload.get("definition_json") or {}
    if isinstance(definition, str):
        try:
            definition = json.loads(definition)
        except Exception:
            definition = {}
    if not isinstance(definition, dict):
        definition = {}
    runtime = build_runtime(definition, payload.get("filters") or {})
    return {"ok": True, "runtime": runtime}


@app.route("/versions/<file_id>")
def versions_list(file_id):
    if not require_login():
        return redirect(url_for("login"))

    role = get_user_role("file", file_id, session["user"], session["department"])
    if role is None:
        abort(403)
    return {"versions": list_versions_db(file_id)}


@app.route("/versions/<file_id>/rollback", methods=["POST"])
def versions_rollback(file_id):
    if not require_login():
        return redirect(url_for("login"))

    role = get_user_role("file", file_id, session["user"], session["department"])
    if role not in ("editor", "owner"):
        abort(403)

    version_no = request.form.get("version_no")
    if not version_no:
        abort(400)
    try:
        version_no = int(version_no)
    except Exception:
        abort(400)

    ok = rollback_to_version(file_id, version_no, session["user"])
    if not ok:
        abort(404)

    log_event(
        "rollback",
        session["user"],
        request,
        item_type="file",
        item_id=file_id,
        context={"version_no": version_no}
    )
    try:
        from modules.bi_sync_trigger import trigger_bi_resync_for_file
        trigger_bi_resync_for_file(file_id)
    except Exception:
        pass
    # Redirect to editor so user lands on fresh config with new document.key
    return redirect(url_for("open_editor", file_id=file_id))


@app.route("/versions/<file_id>/compare")
def versions_compare(file_id):
    if not require_login():
        return redirect(url_for("login"))
    role = get_user_role("file", file_id, session["user"], session["department"])
    if role is None:
        abort(403)

    v1 = request.args.get("from")
    v2 = request.args.get("to")
    if not v1 or not v2:
        abort(400)
    try:
        v1 = int(v1)
        v2 = int(v2)
    except Exception:
        abort(400)

    db = get_db()
    row = db.execute("SELECT file_type FROM files WHERE file_id=?", (file_id,)).fetchone()
    p1 = db.execute("SELECT stored_path FROM file_versions WHERE file_id=? AND version_no=?", (file_id, v1)).fetchone()
    p2 = db.execute("SELECT stored_path FROM file_versions WHERE file_id=? AND version_no=?", (file_id, v2)).fetchone()
    db.close()
    if not row or not p1 or not p2:
        abort(404)

    if row["file_type"] == "sheet":
        diff = build_excel_diff(p1["stored_path"], p2["stored_path"])
        return {"type": "sheet", "diff": diff}
    import difflib
    t1 = extract_text_for_index(p1["stored_path"], row["file_type"])
    t2 = extract_text_for_index(p2["stored_path"], row["file_type"])
    diff = "\n".join(difflib.ndiff(t1.splitlines(), t2.splitlines()))
    return {"type": "text", "diff": diff}


@app.route("/preview/<file_id>")
def preview(file_id):
    if not require_login():
        return redirect(url_for("login"))
    access = resolve_item_access("file", file_id, session["user"], session["department"])
    if not access.get("allowed"):
        expired = find_expired_share_access("file", file_id, session["user"], session["department"])
        if expired:
            log_share_expired(session["user"], request, "file", file_id, context=expired)
        else:
            log_share_denied(session["user"], request, "file", file_id, access.get("reason", "no_permission"), context={
                "preview": True
            })
        abort(403)
    if access.get("owner") != session["user"]:
        log_share_access(session["user"], request, "file", file_id, context={
            "preview": True,
            "role": access.get("role"),
            "scope": access.get("share", {}).get("scope")
        })
    log_event("preview_file", session["user"], request, item_type="file", item_id=file_id, context={
        "preview": True
    })
    token = generate_preview_token(file_id, session["user"])
    file_url = f"/preview/raw/{file_id}?token={token}"
    return render_template("preview.html", file_url=file_url)


@app.route("/preview/raw/<file_id>")
def preview_raw(file_id):
    token = request.args.get("token", "")
    payload = verify_preview_token(token, file_id)
    if "user" in session:
        log_download_blocked(session.get("user"), file_id, "session_preview_blocked")
        abort(403, description="Download is disabled by policy")
    if not payload:
        log_download_blocked("anonymous", file_id, "missing_or_invalid_token")
        abort(403, description="Download is disabled by policy")
    access_user = payload.get("user_id")
    access_department = get_user_department(access_user)
    access = resolve_item_access("file", file_id, access_user, access_department)
    if not access.get("allowed"):
        log_download_blocked(access_user, file_id, "preview_access_blocked")
        log_share_denied(access_user, request, "file", file_id, "raw_preview_blocked", context={
            "preview": True
        })
        abort(403, description="Download is disabled by policy")
    db = get_db()
    row = db.execute("SELECT path, name FROM files WHERE file_id=?", (file_id,)).fetchone()
    db.close()
    if not row:
        abort(404)
    return send_file(row["path"], as_attachment=False, download_name=row["name"])


@app.route("/archive/restore/<file_id>", methods=["POST"])
def restore_archive(file_id):
    if not require_login():
        return redirect(url_for("login"))
    actions = get_allowed_actions(session["user"], "file", file_id)
    if not actions.get("restore_archive", False):
        log_action_denied(session["user"], "file", file_id, "restore_archive", "role")
        abort(403)
    restore_from_archive(file_id)
    log_event("archive_restore", session["user"], request, item_type="file", item_id=file_id, context={})
    return {"ok": True}


@app.route("/transfer/<item_type>/<item_id>", methods=["POST"])
def transfer(item_type, item_id):
    if not require_login():
        return redirect(url_for("login"))
    actions = get_allowed_actions(session["user"], item_type, item_id)
    if not actions.get("transfer_ownership", False):
        log_action_denied(session["user"], item_type, item_id, "transfer_ownership", "role")
        abort(403)

    new_owner = request.form.get("new_owner")
    signature = request.form.get("signature", "")
    reason = request.form.get("reason", "")
    include_children = 1 if request.form.get("include_children", "1") == "1" else 0
    if not new_owner:
        abort(400)

    ok = transfer_ownership(item_type, item_id, new_owner, session["user"], signature, include_children=include_children, reason=reason)
    if not ok:
        abort(404)
    log_event("ownership_transfer", session["user"], request, item_type=item_type, item_id=item_id, context={"new_owner": new_owner})
    return {"ok": True}


def generate_dashboard_id():
    return f"DASH_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6].upper()}"


def build_default_definition(file_id, sheet_name, name, description):
    return {
        "version": 1,
        "locale": "ar-SA",
        "timezone": "Asia/Riyadh",
        "dataset": {
            "mode": "embedded",
            "sources": [
                {
                    "source_id": "SRC_1",
                    "type": "excel",
                    "file_id": file_id,
                    "sheet": sheet_name or "Sheet1",
                    "range": "AUTO",
                    "table_name": "Sales",
                    "refresh": {"mode": "manual"}
                }
            ],
            "transforms": {},
            "model": {"relationships": []},
            "fields": {},
            "measures": []
        },
        "report": {
            "filters": {"global": []},
            "layout": {
                "grid": {"cols": 12, "rowHeight": 20, "gap": 12},
                "visuals": []
            },
            "interactions": {"cross_filter": True}
        },
        "meta": {
            "name": name,
            "description": description
        }
    }

@app.route("/data-panel")
def data_panel_home():
    if not require_login():
        return redirect(url_for("login"))
    if not can_access_bi():
        log_access_violation("data_panel_denied", "dashboard", "home", "bi_access_denied")
        return redirect(url_for("dashboard") + "?msg=bi_denied")
    policy = get_bi_policy(session.get("department"))
    if not policy.get("allow_view"):
        log_access_violation("data_panel_denied", "dashboard", "home", "bi_policy_view_denied")
        abort(403)

    log_event("data_panel_home", session["user"], request, item_type="dashboard", item_id="home", context={})

    dashboards = list_bi_dashboards_for_user(session["user"], session.get("department"), session.get("role"))

    return render_template(
        "data_panel.html",
        dashboards=dashboards,
        user_name=session.get("name"),
        role=session.get("role")
    )

@app.route("/data-panel/new", methods=["GET", "POST"])
def data_panel_new():
    if not require_login():
        return redirect(url_for("login"))
    if not has_dashboard_studio_access():
        abort(403)
    return redirect(url_for("dashboard_studio_create"))

@app.route("/data-panel/<dashboard_id>/edit")
def data_panel_edit(dashboard_id):
    if not require_login():
        return redirect(url_for("login"))
    if not has_dashboard_studio_access():
        abort(403)
    return redirect(url_for("dashboard_studio_edit", dashboard_id=dashboard_id))

@app.route("/data-panel/<dashboard_id>")
def data_panel_view(dashboard_id):
    if not require_login():
        return redirect(url_for("login"))

    user_id = session.get("user")
    role = session.get("role")
    department = session.get("department")

    if dashboard_id == "new":
        logging.info("data_panel_view: dashboard_id=new -> 404")
        abort(404)

    # BI access: role in admin/مدير عام/مدير القسم OR "bi" in apps (same as data-panel home)
    if not can_access_bi():
        logging.warning(
            "data_panel_view: 403 bi_access_denied | user=%s role=%s department=%s dashboard_id=%s",
            user_id, role, department, dashboard_id
        )
        log_access_violation("data_panel_denied", "dashboard", dashboard_id, "bi_access_denied")
        abort(403)

    policy = get_bi_policy(department)
    if not policy.get("allow_view"):
        logging.warning(
            "data_panel_view: 403 bi_policy_view_denied | user=%s department=%s dashboard_id=%s",
            user_id, department, dashboard_id
        )
        log_access_violation("data_panel_denied", "dashboard", dashboard_id, "bi_policy_view_denied")
        abort(403)

    db = get_db()
    dashboards = db.execute(
        "SELECT * FROM dashboards WHERE status='published' ORDER BY created_at DESC"
    ).fetchall()
    dashboard = db.execute(
        "SELECT * FROM dashboards WHERE dashboard_id = ?",
        (dashboard_id,)
    ).fetchone()

    if not dashboard:
        db.close()
        logging.info("data_panel_view: 404 dashboard not found | dashboard_id=%s", dashboard_id)
        abort(404)
    if dashboard.get("status") != "published":
        db.close()
        logging.info(
            "data_panel_view: 404 dashboard not published | dashboard_id=%s status=%s",
            dashboard_id, dashboard.get("status")
        )
        abort(404)

    if not can_access_dashboard(user_id, dashboard_id):
        logging.warning(
            "data_panel_view: 403 dashboard_access_denied | user=%s role=%s department=%s dashboard_id=%s file_id=%s",
            user_id, role, department, dashboard_id, dashboard.get("file_id")
        )
        log_event(
            "dashboard_access_denied",
            user_id,
            request,
            item_type="dashboard",
            item_id=dashboard_id,
            context={"reason": "permission_resolution_failed"}
        )
        db.close()
        abort(403)

    dashboard = dict(dashboard)
    definition_json = dashboard.get("definition_json")
    if definition_json:
        try:
            definition = json.loads(definition_json)
        except Exception:
            definition = None
        if definition:
            for src in (definition.get("dataset") or {}).get("sources") or []:
                file_id = src.get("file_id")
                if not file_id:
                    continue
                access = resolve_item_access("file", file_id, user_id, department)
                if not access.get("allowed"):
                    logging.warning(
                        "data_panel_view: 403 linked_file_denied | user=%s dashboard_id=%s file_id=%s",
                        user_id, dashboard_id, file_id
                    )
                    db.close()
                    abort(403)
            db.close()
            runtime = build_runtime(definition, request.args)
            schema_mismatch = []
            for src in (definition.get("dataset") or {}).get("sources") or []:
                table_name = src.get("table_name") or src.get("alias_table_name") or src.get("source_id")
                expected = src.get("schema_hash")
                actual = (runtime.get("schema") or {}).get(table_name, {}).get("hash")
                if expected and actual and expected != actual:
                    schema_mismatch.append({
                        "table": table_name,
                        "expected": expected,
                        "actual": actual
                    })
            db = get_db()
            db.execute(
                "UPDATE dashboards SET last_run_at=?, last_run_status=? WHERE dashboard_id=?",
                (datetime.now().strftime("%Y-%m-%d %H:%M"), "ok", dashboard_id)
            )
            db.commit()
            db.close()
            return render_template(
                "dashboard_runtime.html",
                dashboards=dashboards,
                dashboard=dashboard,
                definition=definition,
                runtime=runtime,
                schema_mismatch=schema_mismatch,
                user_name=session.get("name"),
                role=session.get("role"),
                filters=request.args
            )

    file = db.execute(
        "SELECT path FROM files WHERE file_id = ?",
        (dashboard["file_id"],)
    ).fetchone()

    kpis_db = db.execute(
        "SELECT * FROM dashboard_kpis WHERE dashboard_id = ?",
        (dashboard_id,)
    ).fetchall()

    db.close()

    access = resolve_item_access("file", dashboard["file_id"], session["user"], session["department"])
    if access.get("allowed") and access.get("owner") != session["user"]:
        log_share_access(session["user"], request, "file", dashboard["file_id"], context={
            "dashboard_id": dashboard_id,
            "role": access.get("role"),
            "scope": access.get("share", {}).get("scope")
        })
    log_event("dashboard_opened", session["user"], request, item_type="dashboard", item_id=dashboard_id, context={
        "file_id": dashboard["file_id"]
    })
    log_event("dashboard_view", session["user"], request, item_type="dashboard", item_id=dashboard_id, context={
        "file_id": dashboard["file_id"]
    })

    sheet_name = dashboard["sheet_name"] if "sheet_name" in dashboard.keys() else None
    try:
        df = pd.read_excel(file["path"], sheet_name=sheet_name if sheet_name else 0)
    except Exception:
        df = pd.read_excel(file["path"])

    df.columns = [str(c).strip() for c in df.columns]

    # ===== تجهيز أنواع الأعمدة =====
    # التاريخ
    if "التاريخ" in df.columns:
        df["التاريخ"] = pd.to_datetime(df["التاريخ"], errors="coerce", dayfirst=True)

    # أرقام
    num_cols = [
        "الكمية",
        "الإجمالي شامل الضريبة",
        "الإجمالي بدون الضريبة",
        "اجمالي التكلفة",
        "مجمل الربح",
        "السعر",
        "متوسط التكلفة"
    ]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # نصوص
    text_cols = [
        "الفرع", "المنتج", "الفئة", "الحجم", "نوع العملية",
        "الشهر", "الفصول الأربعة", "التاريخ الهجري", "المنتج بدون كود", "تبديل أو جديد"
    ]
    for c in text_cols:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()

    # ===== فلترة (GET params) =====
    def arg(name, default=""):
        return (request.args.get(name, default) or "").strip()

    def norm_text(value):
        return (value or "").strip().lower()

    def normalize_season(value):
        v = norm_text(value)
        mapping = {
            "winter": "winter",
            "spring": "spring",
            "summer": "summer",
            "autumn": "autumn",
            "fall": "autumn",
            "الشتاء": "winter",
            "شتاء": "winter",
            "الربيع": "spring",
            "ربيع": "spring",
            "الصيف": "summer",
            "صيف": "summer",
            "الخريف": "autumn",
            "خريف": "autumn"
        }
        return mapping.get(v, v)

    def normalize_change_type(value):
        v = norm_text(value)
        mapping = {
            "new": "new",
            "جديد": "new",
            "جديدة": "new",
            "replacement": "replacement",
            "تبديل": "replacement",
            "بديل": "replacement",
            "استبدال": "replacement"
        }
        return mapping.get(v, v)

    def month_to_number(value):
        v = norm_text(value)
        if not v:
            return None
        if v.isdigit():
            try:
                num = int(v)
            except ValueError:
                return None
            return num if 1 <= num <= 12 else None
        mapping = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
            "يناير": 1,
            "فبراير": 2,
            "مارس": 3,
            "أبريل": 4,
            "ابريل": 4,
            "مايو": 5,
            "يونيو": 6,
            "يوليو": 7,
            "أغسطس": 8,
            "اغسطس": 8,
            "سبتمبر": 9,
            "أكتوبر": 10,
            "اكتوبر": 10,
            "نوفمبر": 11,
            "ديسمبر": 12
        }
        return mapping.get(v)

    def season_from_month(month_num):
        if month_num in (12, 1, 2):
            return "winter"
        if month_num in (3, 4, 5):
            return "spring"
        if month_num in (6, 7, 8):
            return "summer"
        if month_num in (9, 10, 11):
            return "autumn"
        return None

    # قيم الفلاتر
    f_branch = arg("branch")
    f_cat = arg("category")
    f_size = arg("size")
    f_op = arg("op")
    f_month = norm_text(arg("month"))
    if not f_month:
        f_month = "all"
    f_season = normalize_season(arg("season") or arg("quarter"))
    if not f_season:
        f_season = "all"
    f_change_type = normalize_change_type(arg("change_type") or arg("switch"))
    if not f_change_type:
        f_change_type = "all"
    f_product = arg("product")  # search contains
    d_from = arg("from")
    d_to = arg("to")

    fdf = df.copy()

    # Date range
    if "التاريخ" in fdf.columns:
        if d_from:
            dfrom_dt = pd.to_datetime(d_from, errors="coerce")
            if pd.notna(dfrom_dt):
                fdf = fdf[fdf["التاريخ"] >= dfrom_dt]
        if d_to:
            dto_dt = pd.to_datetime(d_to, errors="coerce")
            if pd.notna(dto_dt):
                fdf = fdf[fdf["التاريخ"] <= dto_dt]

    # Equals filters
    if f_branch and "الفرع" in fdf.columns:
        fdf = fdf[fdf["الفرع"] == f_branch]
    if f_cat and "الفئة" in fdf.columns:
        fdf = fdf[fdf["الفئة"] == f_cat]
    if f_size and "الحجم" in fdf.columns:
        fdf = fdf[fdf["الحجم"] == f_size]
    if f_op and "نوع العملية" in fdf.columns:
        fdf = fdf[fdf["نوع العملية"] == f_op]
    if f_month != "all":
        month_num = month_to_number(f_month)
        if month_num and "التاريخ" in fdf.columns and pd.api.types.is_datetime64_any_dtype(fdf["التاريخ"]):
            fdf = fdf[fdf["التاريخ"].dt.month == month_num]
        elif "الشهر" in fdf.columns:
            month_series = fdf["الشهر"].astype(str).str.strip()
            if month_num:
                month_nums = month_series.apply(month_to_number)
                fdf = fdf[month_nums == month_num]
            else:
                fdf = fdf[month_series.str.lower() == f_month]
    if f_season != "all":
        season_col = None
        if "Season" in fdf.columns:
            season_col = "Season"
        elif "الفصول الأربعة" in fdf.columns:
            season_col = "الفصول الأربعة"
        if season_col:
            season_series = fdf[season_col].astype(str).apply(normalize_season)
            fdf = fdf[season_series == f_season]
        elif "التاريخ" in fdf.columns and pd.api.types.is_datetime64_any_dtype(fdf["التاريخ"]):
            season_series = fdf["التاريخ"].dt.month.apply(season_from_month)
            fdf = fdf[season_series == f_season]
        elif "الشهر" in fdf.columns:
            month_nums = fdf["الشهر"].astype(str).apply(month_to_number)
            season_series = month_nums.apply(season_from_month)
            fdf = fdf[season_series == f_season]
    if f_change_type != "all":
        change_col = None
        if "change_type" in fdf.columns:
            change_col = "change_type"
        elif "Change Type" in fdf.columns:
            change_col = "Change Type"
        elif "تبديل أو جديد" in fdf.columns:
            change_col = "تبديل أو جديد"
        if change_col:
            change_series = fdf[change_col].astype(str).apply(normalize_change_type)
            fdf = fdf[change_series == f_change_type]

    # Product contains
    if f_product:
        colp = "المنتج بدون كود" if "المنتج بدون كود" in fdf.columns else ("المنتج" if "المنتج" in fdf.columns else None)
        if colp:
            fdf = fdf[fdf[colp].str.contains(f_product, na=False)]

    # ===== KPIs (موسّعة + احترافية) =====
    def nsum(col):
        if col in fdf.columns:
            return float(fdf[col].fillna(0).sum())
        return 0.0

    def navg(col):
        if col in fdf.columns:
            s = fdf[col].dropna()
            return float(s.mean()) if len(s) else 0.0
        return 0.0

    total_qty = nsum("الكمية")
    total_sales_inc = nsum("الإجمالي شامل الضريبة")
    total_sales_ex = nsum("الإجمالي بدون الضريبة")
    total_cost = nsum("اجمالي التكلفة")
    gross_profit = nsum("مجمل الربح")
    tx_count = int(len(fdf.index))

    margin = (gross_profit / total_sales_ex * 100) if total_sales_ex else 0.0
    avg_price = navg("السعر")
    avg_cost = navg("متوسط التكلفة")

    # KPIs من DB (اللي أنت مسويها) + KPIs إضافية ثابتة
    kpi_results = []

    # KPIs من DB (تظل شغالة)
    for k in kpis_db:
        col = str(k["column_name"]).strip()
        if col not in fdf.columns:
            value = 0
        else:
            s = pd.to_numeric(fdf[col], errors="coerce")
            if k["agg"] == "sum":
                value = float(s.fillna(0).sum())
            elif k["agg"] == "avg":
                value = float(s.dropna().mean()) if s.dropna().shape[0] else 0
            else:
                value = int(s.dropna().shape[0])

        kpi_results.append({
            "label": k["label"],
            "value": round(value, 2),
            "format": k["format"]
        })

    # KPIs إضافية احترافية
    kpi_results_extra = [
        {"label": "عدد العمليات", "value": tx_count, "format": "number"},
        {"label": "إجمالي المبيعات (شامل)", "value": round(total_sales_inc, 2), "format": "currency"},
        {"label": "إجمالي المبيعات (بدون)", "value": round(total_sales_ex, 2), "format": "currency"},
        {"label": "إجمالي التكلفة", "value": round(total_cost, 2), "format": "currency"},
        {"label": "مجمل الربح", "value": round(gross_profit, 2), "format": "currency"},
        {"label": "هامش الربح %", "value": round(margin, 2), "format": "percent"},
        {"label": "متوسط السعر", "value": round(avg_price, 2), "format": "currency"},
        {"label": "متوسط التكلفة", "value": round(avg_cost, 2), "format": "currency"},
    ]

    # ===== Options للفلاتر (من البيانات الأصلية) =====
    def uniq(col):
        if col in df.columns:
            return sorted([x for x in df[col].dropna().astype(str).unique().tolist() if x.strip() != ""])
        return []

    filter_options = {
        "branches": uniq("الفرع"),
        "categories": uniq("الفئة"),
        "sizes": uniq("الحجم"),
        "ops": uniq("نوع العملية"),
        "months": uniq("الشهر"),
        "quarters": uniq("الفصول الأربعة"),
        "switches": uniq("تبديل أو جديد"),
    }

    # ===== Charts (كثيرة ومفيدة) =====
    charts = {}

    # 1) Trend يومي/شهري (مبيعات + ربح)
    if "التاريخ" in fdf.columns and pd.api.types.is_datetime64_any_dtype(fdf["التاريخ"]):
        t = fdf.dropna(subset=["التاريخ"]).copy()
        if len(t):
            t["day"] = t["التاريخ"].dt.strftime("%Y-%m-%d")
            daily = t.groupby("day")[["الإجمالي بدون الضريبة", "مجمل الربح"]].sum().reset_index()
            charts["trend_labels"] = daily["day"].tolist()
            charts["trend_sales"] = daily["الإجمالي بدون الضريبة"].fillna(0).round(2).tolist()
            charts["trend_profit"] = daily["مجمل الربح"].fillna(0).round(2).tolist()
        else:
            charts["trend_labels"], charts["trend_sales"], charts["trend_profit"] = [], [], []
    else:
        charts["trend_labels"], charts["trend_sales"], charts["trend_profit"] = [], [], []

    # 2) أفضل 10 منتجات (مبيعات)
    prod_col = "المنتج بدون كود" if "المنتج بدون كود" in fdf.columns else ("المنتج" if "المنتج" in fdf.columns else None)
    if prod_col and "الإجمالي بدون الضريبة" in fdf.columns:
        p = fdf.groupby(prod_col)["الإجمالي بدون الضريبة"].sum().reset_index()
        p = p.sort_values("الإجمالي بدون الضريبة", ascending=False).head(10)
        charts["top_products_labels"] = p[prod_col].tolist()
        charts["top_products_values"] = p["الإجمالي بدون الضريبة"].fillna(0).round(2).tolist()
    else:
        charts["top_products_labels"], charts["top_products_values"] = [], []

    # 3) الفروع (مبيعات)
    if "الفرع" in fdf.columns and "الإجمالي بدون الضريبة" in fdf.columns:
        b = fdf.groupby("الفرع")["الإجمالي بدون الضريبة"].sum().reset_index()
        b = b.sort_values("الإجمالي بدون الضريبة", ascending=False).head(10)
        charts["branches_labels"] = b["الفرع"].tolist()
        charts["branches_values"] = b["الإجمالي بدون الضريبة"].fillna(0).round(2).tolist()
    else:
        charts["branches_labels"], charts["branches_values"] = [], []

    # 4) الفئات (مبيعات)
    if "الفئة" in fdf.columns and "الإجمالي بدون الضريبة" in fdf.columns:
        c = fdf.groupby("الفئة")["الإجمالي بدون الضريبة"].sum().reset_index()
        c = c.sort_values("الإجمالي بدون الضريبة", ascending=False).head(8)
        charts["cats_labels"] = c["الفئة"].tolist()
        charts["cats_values"] = c["الإجمالي بدون الضريبة"].fillna(0).round(2).tolist()
    else:
        charts["cats_labels"], charts["cats_values"] = [], []

    # 5) توزيع الأحجام (كمية)
    if "الحجم" in fdf.columns and "الكمية" in fdf.columns:
        s = fdf.groupby("الحجم")["الكمية"].sum().reset_index()
        s = s.sort_values("الكمية", ascending=False)
        charts["sizes_labels"] = s["الحجم"].tolist()
        charts["sizes_values"] = s["الكمية"].fillna(0).round(2).tolist()
    else:
        charts["sizes_labels"], charts["sizes_values"] = [], []

    # 6) نوع العملية (كمية/مبيعات)
    if "نوع العملية" in fdf.columns:
        if "الكمية" in fdf.columns:
            o1 = fdf.groupby("نوع العملية")["الكمية"].sum().reset_index()
            charts["ops_labels"] = o1["نوع العملية"].tolist()
            charts["ops_values"] = o1["الكمية"].fillna(0).round(2).tolist()
        else:
            charts["ops_labels"], charts["ops_values"] = [], []
    else:
        charts["ops_labels"], charts["ops_values"] = [], []

    # 7) هامش الربح حسب الفئة
    if "الفئة" in fdf.columns and "الإجمالي بدون الضريبة" in fdf.columns and "مجمل الربح" in fdf.columns:
        mc = fdf.groupby("الفئة")[["الإجمالي بدون الضريبة","مجمل الربح"]].sum().reset_index()
        mc["margin"] = mc.apply(lambda r: (r["مجمل الربح"]/r["الإجمالي بدون الضريبة"]*100) if r["الإجمالي بدون الضريبة"] else 0, axis=1)
        mc = mc.sort_values("margin", ascending=False).head(8)
        charts["margin_labels"] = mc["الفئة"].tolist()
        charts["margin_values"] = mc["margin"].fillna(0).round(2).tolist()
    else:
        charts["margin_labels"], charts["margin_values"] = [], []

    # ===== جدول (آخر 50 عملية بعد الفلترة) =====
    table_cols = [c for c in [
        "التاريخ","الفرع","المنتج بدون كود","الكمية",
        "الإجمالي شامل الضريبة","الإجمالي بدون الضريبة",
        "اجمالي التكلفة","مجمل الربح","الفئة","الحجم","نوع العملية","الشهر","الفصول الأربعة","تبديل أو جديد"
    ] if c in fdf.columns]

    tdf = fdf.copy()
    if "التاريخ" in tdf.columns and pd.api.types.is_datetime64_any_dtype(tdf["التاريخ"]):
        tdf = tdf.sort_values("التاريخ", ascending=False)

    table_rows = tdf[table_cols].head(50).fillna("").to_dict(orient="records")
    alerts = compute_alerts(fdf)

    return render_template(
        "dashboard_view.html",
        dashboards=dashboards,
        dashboard=dashboard,
        # KPIs: دمج (DB + Extra)
        kpis=kpi_results + kpi_results_extra,
        # charts
        charts_json=json.dumps(charts, ensure_ascii=False),
        # table
        table_cols=table_cols,
        table_rows=table_rows,
        alerts=alerts,
        # filters
        filters={
            "branch": f_branch, "category": f_cat, "size": f_size, "op": f_op,
            "month": f_month, "season": f_season, "quarter": f_season,
            "change_type": f_change_type, "switch": f_change_type,
            "product": f_product, "from": d_from, "to": d_to
        },
        filter_options=filter_options,
        user_name=session.get("name"),
        role=session.get("role")
    )


@app.route("/bi", endpoint="bi_index")
def bi_index():
    """BI dashboards list - redirect to data panel home."""
    if not require_login():
        return redirect(url_for("login"))
    return redirect(url_for("data_panel_home"))


@app.route("/bi/studio/new", endpoint="bi_studio_new")
def bi_studio_new():
    """BI studio create - redirect to data panel new."""
    if not require_login():
        return redirect(url_for("login"))
    return redirect(url_for("data_panel_new"))


@app.route("/bi/admin", endpoint="bi_admin")
def bi_admin():
    """BI admin - redirect to governance or data panel."""
    if not require_login():
        return redirect(url_for("login"))
    return redirect(url_for("data_panel_home"))


# ----- Native BI routes (explicit endpoints for template url_for) -----

@app.route("/bi/create-from-file/<file_id>", methods=["POST"], endpoint="bi_create_from_file_s2")
def bi_create_from_file_s2(file_id):
    """Create a BI dashboard from an Excel file."""
    if not require_login():
        return redirect(url_for("login"))
    if not can_create_edit_bi():
        abort(403)
    access = resolve_item_access("file", file_id, session["user"], session.get("department"))
    if not access.get("allowed"):
        flash("لا تملك صلاحية الوصول لهذا الملف.")
        return redirect(request.referrer or url_for("dashboard"))
    db = get_db()
    row = db.execute("SELECT path, name FROM files WHERE file_id = ? AND is_trashed = 0", (file_id,)).fetchone()
    db.close()
    if not row:
        flash("الملف غير موجود.")
        return redirect(request.referrer or url_for("dashboard"))
    row = dict(row)
    try:
        internal_id = create_dashboard_from_file(
            file_id=file_id,
            owner_user_id=session["user"],
            title=row.get("name") or f"لوحة {file_id}",
            description="",
        )
        try:
            from modules.bi_sync_trigger import trigger_bi_resync_for_file
            trigger_bi_resync_for_file(file_id)
        except Exception as e:
            logging.warning("bi_create_from_file_s2: trigger resync failed: %s", e)
        log_event("bi_dashboard_create", session["user"], request, item_type="dashboard", item_id=internal_id, context={"file_id": file_id})
        return redirect(url_for("bi_studio_dashboard", internal_id=internal_id))
    except Exception as e:
        logging.exception("bi_create_from_file_s2: %s", e)
        flash("فشل إنشاء لوحة البيانات: " + str(e)[:200])
        return redirect(request.referrer or url_for("dashboard"))


@app.route("/bi/dashboard/<internal_id>", endpoint="bi_open_s2")
def bi_open_s2_route(internal_id):
    """View a BI dashboard (alias bi_open_s2)."""
    return _render_bi_dashboard_view(internal_id)


@app.route("/bi/dashboard/<internal_id>/view", endpoint="bi_dashboard_view")
def bi_dashboard_view_route(internal_id):
    """View a BI dashboard."""
    return _render_bi_dashboard_view(internal_id)


def _render_bi_dashboard_view(internal_id):
    """View a BI dashboard."""
    if not require_login():
        return redirect(url_for("login"))
    if not can_access_bi():
        abort(403)
    row = _get_dashboard_row(internal_id)
    if not row:
        abort(404)
    if not can_user_view_bi_dashboard(session["user"], internal_id, session.get("department"), session.get("role")):
        abort(403)
    from modules.dashboard_engine import build_runtime
    from modules.bi_security import can_export_dashboard
    layout = json.loads(row.get("layout_json") or "{}")
    layout_items = (layout.get("grid") or {}).get("items") or {}
    widgets = get_widgets_for_dashboard(internal_id)
    filters_list = get_dashboard_filters(internal_id)
    theme = json.loads(row.get("theme_json") or "{}")
    theme_mode = theme.get("mode") or "light"
    policy = get_bi_policy(session.get("department"))
    return render_template(
        "bi_dashboard_view.html",
        internal_id=internal_id,
        title=row.get("title") or internal_id,
        theme_mode=theme_mode,
        can_export=bool(row.get("allow_export")) and can_export_dashboard(session["user"], row, department=session.get("department")),
        no_print=not (policy.get("allow_print") or row.get("owner_user_id") == session["user"]),
        no_copy=not (policy.get("allow_copy") or row.get("owner_user_id") == session["user"]),
        dashboard_filters=filters_list,
        can_edit=can_create_edit_bi() and row.get("owner_user_id") == session["user"],
        is_admin=session.get("role") in ("admin", "مدير عام"),
        layout_items=layout_items,
        widgets=widgets,
    )


@app.route("/bi/studio/dashboard/<internal_id>", endpoint="bi_studio_dashboard")
def bi_studio_dashboard_route(internal_id):
    """Edit a BI dashboard in studio."""
    if not require_login():
        return redirect(url_for("login"))
    if not can_create_edit_bi():
        abort(403)
    row = _get_dashboard_row(internal_id)
    if not row:
        abort(404)
    if row.get("owner_user_id") != session["user"] and session.get("role") not in ("admin", "مدير عام"):
        abort(403)
    return render_template(
        "bi_studio.html",
        internal_id=internal_id,
        title=row.get("title") or internal_id,
    )


@app.route("/bi/export/<dash_id>", endpoint="bi_export")
def bi_export_route(dash_id):
    """Export dashboard (CSV/XLSX/PDF stub)."""
    if not require_login():
        abort(403)
    row = _get_dashboard_row(dash_id)
    if not row:
        abort(404)
    if not can_user_view_bi_dashboard(session["user"], dash_id, session.get("department"), session.get("role")):
        abort(403)
    fmt = request.args.get("format", "csv")
    if fmt == "csv":
        return redirect(url_for("bi_dashboard_view", internal_id=dash_id))
    if fmt == "xlsx":
        return redirect(url_for("bi_dashboard_view", internal_id=dash_id))
    if fmt == "pdf":
        return redirect(url_for("bi_dashboard_view", internal_id=dash_id))
    return redirect(url_for("bi_dashboard_view", internal_id=dash_id))


@app.route("/bi/duplicate/<dash_id>", methods=["POST"], endpoint="bi_duplicate")
def bi_duplicate_route(dash_id):
    """Duplicate a BI dashboard."""
    if not require_login():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not can_create_edit_bi():
        return jsonify({"ok": False, "error": "forbidden"}), 403
    row = _get_dashboard_row(dash_id)
    if not row:
        return jsonify({"ok": False, "error": "not found"}), 404
    file_id = row.get("linked_file_id") or ""
    try:
        new_id = duplicate_dashboard(dash_id, file_id, session["user"], None)
        return jsonify({"ok": True, "url": url_for("bi_studio_dashboard", internal_id=new_id)})
    except Exception as e:
        logging.exception("bi_duplicate: %s", e)
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/bi/export/<dash_id>/png", methods=["POST"], endpoint="bi_export_png")
def bi_export_png_route(dash_id):
    """Export dashboard as PNG (stub)."""
    if not require_login():
        return jsonify({"error": "unauthorized"}), 401
    row = _get_dashboard_row(dash_id)
    if not row:
        return jsonify({"error": "not found"}), 404
    if not can_user_view_bi_dashboard(session["user"], dash_id, session.get("department"), session.get("role")):
        return jsonify({"error": "forbidden"}), 403
    try:
        data = request.get_json() or {}
        img_b64 = (data.get("image") or "").split(",")[-1] if isinstance(data.get("image"), str) else None
        if not img_b64:
            return jsonify({"error": "no image"}), 400
        import base64
        raw = base64.b64decode(img_b64)
        from flask import Response
        return Response(raw, mimetype="image/png", headers={"Content-Disposition": "attachment; filename=dashboard.png"})
    except Exception as e:
        return jsonify({"error": str(e)[:100]}), 500


@app.route("/bi/studio/dashboard/<internal_id>/save", methods=["POST"], endpoint="bi_studio_save")
def bi_studio_save_route(internal_id):
    """Save BI dashboard layout/widgets."""
    if not require_login():
        return jsonify({"ok": False}), 401
    if not can_create_edit_bi():
        return jsonify({"ok": False}), 403
    row = _get_dashboard_row(internal_id)
    if not row:
        return jsonify({"ok": False}), 404
    if row.get("owner_user_id") != session["user"] and session.get("role") not in ("admin", "مدير عام"):
        return jsonify({"ok": False}), 403
    try:
        from modules.bi_models import update_dashboard_layout, replace_widgets_for_dashboard
        data = request.get_json() or {}
        layout = data.get("layout") or {}
        widgets = data.get("widgets") or []
        update_dashboard_layout(internal_id, layout, data.get("filters") or [], status=data.get("status"))
        replace_widgets_for_dashboard(internal_id, widgets)
        save_dashboard_version(internal_id, layout, widgets, session["user"])
        return jsonify({"ok": True})
    except Exception as e:
        logging.exception("bi_studio_save: %s", e)
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/bi/dashboard/<internal_id>/versions", endpoint="bi_dashboard_versions")
def bi_dashboard_versions_route(internal_id):
    """List dashboard versions (API)."""
    if not require_login():
        return jsonify({"versions": []})
    row = _get_dashboard_row(internal_id)
    if not row:
        return jsonify({"versions": []})
    if not can_user_view_bi_dashboard(session["user"], internal_id, session.get("department"), session.get("role")):
        return jsonify({"versions": []})
    versions = get_dashboard_versions(internal_id)
    return jsonify({"versions": [{"id": v.get("id"), "version_no": v.get("version_no"), "created_at": v.get("created_at")} for v in versions]})


@app.route("/bi/dashboard/<internal_id>/rollback", methods=["POST"], endpoint="bi_dashboard_rollback")
def bi_dashboard_rollback_route(internal_id):
    """Rollback dashboard to a version."""
    if not require_login():
        return jsonify({"ok": False}), 401
    if not can_create_edit_bi():
        return jsonify({"ok": False}), 403
    row = _get_dashboard_row(internal_id)
    if not row:
        return jsonify({"ok": False}), 404
    if row.get("owner_user_id") != session["user"] and session.get("role") not in ("admin", "مدير عام"):
        return jsonify({"ok": False}), 403
    try:
        data = request.get_json() or {}
        version_id = data.get("version_id") or data.get("versionId")
        if not version_id:
            return jsonify({"ok": False, "error": "version_id required"}), 400
        rollback_dashboard_to_version(internal_id, int(version_id))
        return jsonify({"ok": True})
    except Exception as e:
        logging.exception("bi_dashboard_rollback: %s", e)
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/bi/template/save", methods=["POST"], endpoint="bi_template_save")
def bi_template_save_route():
    """Save dashboard as template."""
    if not require_login():
        return jsonify({"ok": False}), 401
    if not can_create_edit_bi():
        return jsonify({"ok": False}), 403
    try:
        data = request.get_json() or {}
        dash_id = data.get("dashboard_id") or data.get("dashboardId")
        name = data.get("name") or "Template"
        if not dash_id:
            return jsonify({"ok": False, "error": "dashboard_id required"}), 400
        row = _get_dashboard_row(dash_id)
        if not row:
            return jsonify({"ok": False}), 404
        tid = save_dashboard_as_template(dash_id, name, session["user"])
        return jsonify({"ok": True, "template_id": tid})
    except Exception as e:
        logging.exception("bi_template_save: %s", e)
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/bi/resync/<internal_id>", methods=["POST"], endpoint="bi_resync_s2")
def bi_resync_s2_route(internal_id):
    """Resync BI dashboard data from linked file."""
    if not require_login():
        return redirect(url_for("login"))
    if not can_create_edit_bi():
        abort(403)
    row = _get_dashboard_row(internal_id)
    if not row:
        abort(404)
    if row.get("owner_user_id") != session["user"] and session.get("role") not in ("admin", "مدير عام"):
        abort(403)
    file_id = row.get("linked_file_id")
    if file_id:
        try:
            from modules.bi_sync_trigger import trigger_bi_resync_for_file
            trigger_bi_resync_for_file(file_id)
            flash("جاري تحديث البيانات...")
        except Exception as e:
            logging.warning("bi_resync_s2: %s", e)
            flash("فشل التحديث: " + str(e)[:100])
    return redirect(request.referrer or url_for("bi_studio_dashboard", internal_id=internal_id))


@app.route("/dashboard-studio/create", methods=["GET", "POST"], endpoint="dashboard_studio_create")
def dashboard_studio_create_route():
    """Create new dashboard from file picker (stub -> redirect)."""
    if not require_login():
        return redirect(url_for("login"))
    if not can_create_edit_bi():
        abort(403)
    return redirect(url_for("data_panel_home"))


@app.route("/dashboard-studio/<dashboard_id>/edit", endpoint="dashboard_studio_edit")
def dashboard_studio_edit_route(dashboard_id):
    """Edit dashboard in studio (by internal_id)."""
    if not require_login():
        return redirect(url_for("login"))
    if not can_create_edit_bi():
        abort(403)
    return redirect(url_for("bi_studio_dashboard", internal_id=dashboard_id))


@app.route("/bi/sync/<int:dataset_id>", methods=["POST"])
def bi_sync_dataset(dataset_id):
    """Trigger dataset sync (stub). Admin or extraction layer can wire this later."""
    if not require_login():
        abort(403)
    if session.get("role") not in ("admin", "مدير عام"):
        abort(403)
    db = get_db()
    row = db.execute("SELECT id, name FROM bi_datasets WHERE id = ?", (dataset_id,)).fetchone()
    db.close()
    if not row:
        return {"ok": False, "error": "dataset not found"}, 404
    # Stub: no actual sync; wire to extract_excel_to_analytics_db or similar when ready
    log_event("bi_sync_triggered", session["user"], request, item_type="bi_dataset", item_id=str(dataset_id), context={"name": row["name"]})
    return {"ok": True, "message": "sync triggered (stub)"}


@app.route("/admin/rules", methods=["GET", "POST"])
def rules_admin():
    if not require_login():
        return redirect(url_for("login"))
    if not has_governance_access():
        abort(403)

    if request.method == "POST":
        db = get_db()
        db.execute("""
            INSERT INTO automation_rules
            (name, is_enabled, priority, trigger, conditions_json, actions_json, created_at, created_by)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            request.form.get("name"),
            1 if request.form.get("is_enabled") == "1" else 0,
            int(request.form.get("priority") or 0),
            request.form.get("trigger"),
            request.form.get("conditions_json"),
            request.form.get("actions_json"),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            session["user"]
        ))
        db.commit()
        db.close()
        log_event("automation_rule_create", session["user"], request, item_type="rule", item_id=None)

    db = get_db()
    rules = db.execute("SELECT * FROM automation_rules ORDER BY priority DESC, id DESC").fetchall()
    db.close()
    return render_template("rules_admin.html", rules=rules, user_name=session.get("name"))


@app.route("/admin/audit")
def audit_admin():
    if not require_login():
        return redirect(url_for("login"))
    if not has_governance_access():
        abort(403)

    db = get_db()
    rows = db.execute("""
        SELECT event_type, actor, actor_role, ip, user_agent, item_type, item_id, item_name, context_json, created_at
        FROM audit_log
        ORDER BY created_at DESC
        LIMIT 200
    """).fetchall()
    db.close()
    return render_template("audit_admin.html", rows=rows, user_name=session.get("name"))


@app.route("/api/ai/ask", methods=["POST"])
def ai_ask():
    if not require_login():
        abort(401)
    payload = request.json or {}
    file_id = payload.get("file_id")
    share_context = {}
    if file_id:
        access = resolve_item_access("file", file_id, session["user"], session["department"])
        if not access.get("allowed"):
            expired = find_expired_share_access("file", file_id, session["user"], session["department"])
            if expired:
                log_share_expired(session["user"], request, "file", file_id, context=expired)
            else:
                log_share_denied(session["user"], request, "file", file_id, access.get("reason", "no_permission"), context={
                    "ai_request": True
                })
            abort(403)
        share_context = {
            "role": access.get("role"),
            "scope": access.get("share", {}).get("scope"),
            "expires_at": access.get("share", {}).get("expires_at"),
            "target_type": access.get("share", {}).get("target_type"),
            "target_value": access.get("share", {}).get("target_value")
        }
    log_event("ai_request", session["user"], request, item_type="file" if file_id else None, item_id=file_id, context={
        "share_context": share_context
    })
    # Structure only (no AI processing yet)
    return {"answer": "AI assistant is not configured yet.", "ok": True}



@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def validate_routes():
    """Optional: print all registered endpoints for route audit (run with DEBUG_ROUTES=1)."""
    import os
    if os.getenv("DEBUG_ROUTES"):
        for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
            if not rule.rule.startswith("/static"):
                print(f"  {rule.endpoint} -> {rule.rule} {rule.methods or ''}")


if __name__ == "__main__":
    validate_routes()
    app.run(host="0.0.0.0", port=5000, debug=True)
