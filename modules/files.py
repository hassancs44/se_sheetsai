import os
from datetime import datetime, timedelta
from modules.db import get_db

def get_root_folders(user):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM folders WHERE owner=? AND parent_id IS NULL AND is_trashed=0",
        (user,)
    ).fetchall()
    db.close()
    return rows

def get_files_in_folder(user, folder_id=None):
    db = get_db()
    if folder_id:
        rows = db.execute(
            """SELECT f.*, c.category AS classification
               FROM files f
               LEFT JOIN file_classifications c ON f.file_id = c.file_id
               WHERE f.owner=? AND f.folder_id=? AND f.is_trashed=0""",
            (user, folder_id)
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT f.*, c.category AS classification
               FROM files f
               LEFT JOIN file_classifications c ON f.file_id = c.file_id
               WHERE f.owner=? AND f.folder_id IS NULL AND f.is_trashed=0""",
            (user,)
        ).fetchall()
    db.close()
    return rows

def create_folder(name, owner, parent_id=None):
    db = get_db()
    fid = f"FOLDER_{int(datetime.utcnow().timestamp())}"

    db.execute(
        "INSERT INTO folders (folder_id, name, owner, parent_id, created_at) VALUES (?,?,?,?,?)",
        (fid, name, owner, parent_id, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )

    db.commit()
    db.close()

    return fid

def get_folder(folder_id, owner):
        db = get_db()
        row = db.execute(
            "SELECT * FROM folders WHERE folder_id=? AND owner=?",
            (folder_id, owner)
        ).fetchone()
        db.close()
        return row

def get_child_folders(owner, parent_id):
        db = get_db()
        rows = db.execute(
            "SELECT * FROM folders WHERE owner=? AND parent_id=? AND is_trashed=0",
            (owner, parent_id)
        ).fetchall()
        db.close()
        return rows

def move_to_trash(item_type, item_id, owner):
        db = get_db()
        table = "folders" if item_type == "folder" else "files"
        db.execute(
            f"UPDATE {table} SET is_trashed=1 WHERE {table[:-1]}_id=? AND owner=?",
            (item_id, owner)
        )
        db.commit()
        db.close()

def restore_from_trash(item_type, item_id, owner):
        db = get_db()
        table = "folders" if item_type == "folder" else "files"
        db.execute(
            f"UPDATE {table} SET is_trashed=0 WHERE {table[:-1]}_id=? AND owner=?",
            (item_id, owner)
        )

        db.commit()
        db.close()

def rename_item(item_type, item_id, new_name, owner):
    db = get_db()
    if item_type == "file":
        row = db.execute("SELECT path, name FROM files WHERE file_id=? AND owner=?", (item_id, owner)).fetchone()
        if row and row["path"] and os.path.exists(row["path"]):
            old_path = row["path"]
            old_ext = os.path.splitext(old_path)[1]
            new_safe = (new_name or "").replace("/", "_").replace("\\", "_").strip()
            if not new_safe:
                db.close()
                return
            if old_ext and not new_safe.lower().endswith(old_ext.lower()):
                new_safe = (new_safe.rsplit(".", 1)[0] if "." in new_safe else new_safe) + old_ext
            dirpath = os.path.dirname(old_path)
            new_path = os.path.join(dirpath, f"{item_id}_{new_safe}")
            if old_path != new_path:
                try:
                    os.rename(old_path, new_path)
                except OSError:
                    db.close()
                    raise
            db.execute("UPDATE files SET name=?, path=? WHERE file_id=? AND owner=?", (new_safe, new_path, item_id, owner))
        else:
            db.execute("UPDATE files SET name=? WHERE file_id=? AND owner=?", (new_name, item_id, owner))
    else:
        db.execute("UPDATE folders SET name=? WHERE folder_id=? AND owner=?", (new_name, item_id, owner))
    db.commit()
    db.close()

def move_item(item_type, item_id, new_parent_id, owner):
    db = get_db()

    # ROOT
    if new_parent_id in ("", "ROOT"):
        new_parent_id = None

    # ===== تحديد الجدول والحقل =====
    table = "folders" if item_type == "folder" else "files"
    field = "parent_id" if item_type == "folder" else "folder_id"
    pk = f"{item_type}_id"  # folder_id / file_id

    # ===== جلب العنصر الحالي =====
    item = db.execute(
        f"SELECT {field} FROM {table} WHERE {pk}=? AND owner=? AND is_trashed=0",
        (item_id, owner)
    ).fetchone()

    if not item:
        db.close()
        return

    # ===== منع النقل لنفس المكان =====
    if item[field] == new_parent_id:
        db.close()
        return

    # ===== التحقق من وجود الهدف (إذا مو ROOT) =====
    if new_parent_id is not None:
        target = db.execute(
            "SELECT folder_id FROM folders WHERE folder_id=? AND owner=? AND is_trashed=0",
            (new_parent_id, owner)
        ).fetchone()
        if not target:
            db.close()
            return

    # ===== منع نقل المجلد داخل نفسه أو داخل أحد أبنائه (صح 100%) =====
    if item_type == "folder" and new_parent_id:
        parent = new_parent_id
        while parent:
            if parent == item_id:
                db.close()
                return  # نقل داخل نفسه/أحد الأبناء
            row = db.execute(
                "SELECT parent_id FROM folders WHERE folder_id=? AND owner=? AND is_trashed=0",
                (parent, owner)
            ).fetchone()
            if not row:
                break
            parent = row["parent_id"]

    # ===== تنفيذ النقل =====
    db.execute(
        f"UPDATE {table} SET {field}=? WHERE {pk}=? AND owner=?",
        (new_parent_id, item_id, owner)
    )

    db.commit()
    db.close()

def get_trashed_items(owner):
    db = get_db()
    folders = db.execute(
        "SELECT * FROM folders WHERE owner=? AND is_trashed=1",
        (owner,)
    ).fetchall()
    files = db.execute(
        "SELECT * FROM files WHERE owner=? AND is_trashed=1",
        (owner,)
    ).fetchall()
    db.close()
    return folders, files

from config import UPLOADS_DIR

def save_uploaded_file(file, owner, folder_id=None):
    fid = f"FILE_{int(datetime.utcnow().timestamp())}"
    safe_name = file.filename.replace("/", "_").replace("\\", "_")
    full_path = os.path.join(UPLOADS_DIR, f"{fid}_{safe_name}")

    file.save(full_path)

    db = get_db()
    db.execute(
        """INSERT INTO files
        (file_id, name, owner, folder_id, path, mime, file_type, created_at)
        VALUES (?,?,?,?,?,?,?,?)""",
        (
            fid,
            safe_name,
            owner,
            folder_id,
            full_path,
            file.mimetype,
            "file",
            datetime.now().strftime("%Y-%m-%d %H:%M")
        )
    )

    db.commit()
    db.close()

def get_folder_path(folder_id, owner):
    path = []
    db = get_db()

    while folder_id:
        row = db.execute(
            "SELECT folder_id, name, parent_id FROM folders WHERE folder_id=? AND owner=?",
            (folder_id, owner)
        ).fetchone()
        if not row:
            break
        path.insert(0, row)
        folder_id = row["parent_id"]

    db.close()
    return path

def create_onlyoffice_file(owner, folder_id, name, ext):
    from config import SHEETS_DIR, BASE_DIR
    import shutil

    os.makedirs(SHEETS_DIR, exist_ok=True)
    fid = f"FILE_{int(datetime.utcnow().timestamp())}"
    filename = f"{fid}_{name}.{ext}"
    path = os.path.join(SHEETS_DIR, filename)

    templates = {
        "xlsx": "blank.xlsx",
        "docx": "blank.docx",
        "pptx": "blank.pptx"
    }

    template_path = os.path.join(BASE_DIR, "templates", templates[ext])
    shutil.copyfile(template_path, path)

    file_type = "sheet" if ext == "xlsx" else "doc" if ext == "docx" else "slide"

    db = get_db()
    db.execute("""
        INSERT INTO files
        (file_id, name, owner, folder_id, path, mime, file_type, created_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (
        fid,
        f"{name}.{ext}",
        owner,
        folder_id,
        path,
        "application/octet-stream",
        file_type,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))
    db.commit()
    db.close()

    return fid

import os
import json
import shutil
import zipfile
import hashlib
from datetime import datetime
from modules.db import get_db
import pandas as pd
import re
from config import SEARCH_MAX_CHARS, ARCHIVE_DIR

def get_root_folders(user):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM folders WHERE owner=? AND parent_id IS NULL AND is_trashed=0",
        (user,)
    ).fetchall()
    db.close()
    return rows

def get_files_in_folder(user, folder_id=None):
    db = get_db()
    if folder_id:
        rows = db.execute(
            "SELECT * FROM files WHERE owner=? AND folder_id=? AND is_trashed=0",
            (user, folder_id)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM files WHERE owner=? AND folder_id IS NULL AND is_trashed=0",
            (user,)
        ).fetchall()
    db.close()
    return rows

def create_folder(name, owner, parent_id=None):
    db = get_db()
    fid = f"FOLDER_{int(datetime.utcnow().timestamp())}"

    db.execute(
        "INSERT INTO folders (folder_id, name, owner, parent_id, created_at) VALUES (?,?,?,?,?)",
        (fid, name, owner, parent_id, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )

    db.commit()
    db.close()

    return fid

def get_folder(folder_id, owner):
    db = get_db()
    row = db.execute(
        "SELECT * FROM folders WHERE folder_id=? AND owner=?",
        (folder_id, owner)
    ).fetchone()
    db.close()
    return row

def get_child_folders(owner, parent_id):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM folders WHERE owner=? AND parent_id=? AND is_trashed=0",
        (owner, parent_id)
    ).fetchall()
    db.close()
    return rows

def move_to_trash(item_type, item_id, owner):
    db = get_db()
    table = "folders" if item_type == "folder" else "files"
    db.execute(
        f"UPDATE {table} SET is_trashed=1 WHERE {table[:-1]}_id=? AND owner=?",
        (item_id, owner)
    )
    db.commit()
    db.close()

def restore_from_trash(item_type, item_id, owner):
    db = get_db()
    table = "folders" if item_type == "folder" else "files"
    db.execute(
        f"UPDATE {table} SET is_trashed=0 WHERE {table[:-1]}_id=? AND owner=?",
        (item_id, owner)
    )

    db.commit()
    db.close()

def rename_item(item_type, item_id, new_name, owner):
    db = get_db()
    if item_type == "file":
        row = db.execute("SELECT path, name FROM files WHERE file_id=? AND owner=?", (item_id, owner)).fetchone()
        if row and row["path"] and os.path.exists(row["path"]):
            old_path = row["path"]
            old_ext = os.path.splitext(old_path)[1]
            new_safe = (new_name or "").replace("/", "_").replace("\\", "_").strip()
            if not new_safe:
                db.close()
                return
            if old_ext and not new_safe.lower().endswith(old_ext.lower()):
                new_safe = (new_safe.rsplit(".", 1)[0] if "." in new_safe else new_safe) + old_ext
            dirpath = os.path.dirname(old_path)
            new_path = os.path.join(dirpath, f"{item_id}_{new_safe}")
            if old_path != new_path:
                try:
                    os.rename(old_path, new_path)
                except OSError:
                    db.close()
                    raise
            db.execute("UPDATE files SET name=?, path=? WHERE file_id=? AND owner=?", (new_safe, new_path, item_id, owner))
        else:
            db.execute("UPDATE files SET name=? WHERE file_id=? AND owner=?", (new_name, item_id, owner))
    else:
        db.execute("UPDATE folders SET name=? WHERE folder_id=? AND owner=?", (new_name, item_id, owner))
    db.commit()
    db.close()

def move_item(item_type, item_id, new_parent_id, owner):
    db = get_db()

    # ROOT
    if new_parent_id in ("", "ROOT"):
        new_parent_id = None

    # ===== تحديد الجدول والحقل =====
    table = "folders" if item_type == "folder" else "files"
    field = "parent_id" if item_type == "folder" else "folder_id"
    pk = f"{item_type}_id"  # folder_id / file_id

    # ===== جلب العنصر الحالي =====
    item = db.execute(
        f"SELECT {field} FROM {table} WHERE {pk}=? AND owner=? AND is_trashed=0",
        (item_id, owner)
    ).fetchone()

    if not item:
        db.close()
        return

    # ===== منع النقل لنفس المكان =====
    if item[field] == new_parent_id:
        db.close()
        return

    # ===== التحقق من وجود الهدف (إذا مو ROOT) =====
    if new_parent_id is not None:
        target = db.execute(
            "SELECT folder_id FROM folders WHERE folder_id=? AND owner=? AND is_trashed=0",
            (new_parent_id, owner)
        ).fetchone()
        if not target:
            db.close()
            return

    # ===== منع نقل المجلد داخل نفسه أو داخل أحد أبنائه (صح 100%) =====
    if item_type == "folder" and new_parent_id:
        parent = new_parent_id
        while parent:
            if parent == item_id:
                db.close()
                return  # نقل داخل نفسه/أحد الأبناء
            row = db.execute(
                "SELECT parent_id FROM folders WHERE folder_id=? AND owner=? AND is_trashed=0",
                (parent, owner)
            ).fetchone()
            if not row:
                break
            parent = row["parent_id"]

    # ===== تنفيذ النقل =====
    db.execute(
        f"UPDATE {table} SET {field}=? WHERE {pk}=? AND owner=?",
        (new_parent_id, item_id, owner)
    )

    db.commit()
    db.close()

def get_trashed_items(owner):
    db = get_db()
    folders = db.execute(
        "SELECT * FROM folders WHERE owner=? AND is_trashed=1",
        (owner,)
    ).fetchall()
    files = db.execute(
        "SELECT * FROM files WHERE owner=? AND is_trashed=1",
        (owner,)
    ).fetchall()
    db.close()
    return folders, files

from config import UPLOADS_DIR

def save_uploaded_file(file, owner, folder_id=None):
    fid = f"FILE_{int(datetime.utcnow().timestamp())}"
    safe_name = file.filename.replace("/", "_").replace("\\", "_")
    full_path = os.path.join(UPLOADS_DIR, f"{fid}_{safe_name}")

    file.save(full_path)

    db = get_db()
    db.execute(
        """INSERT INTO files
        (file_id, name, owner, folder_id, path, mime, file_type, created_at)
        VALUES (?,?,?,?,?,?,?,?)""",
        (
            fid,
            safe_name,
            owner,
            folder_id,
            full_path,
            file.mimetype,
            "file",
            datetime.now().strftime("%Y-%m-%d %H:%M")
        )
    )

    db.commit()
    db.close()
    return fid

def get_folder_path(folder_id, owner):
    path = []
    db = get_db()

    while folder_id:
        row = db.execute(
            "SELECT folder_id, name, parent_id FROM folders WHERE folder_id=? AND owner=?",
            (folder_id, owner)
        ).fetchone()
        if not row:
            break
        path.insert(0, row)
        folder_id = row["parent_id"]

    db.close()
    return path

def create_onlyoffice_file(owner, folder_id, name, ext):
    from config import SHEETS_DIR, BASE_DIR
    import shutil

    os.makedirs(SHEETS_DIR, exist_ok=True)
    fid = f"FILE_{int(datetime.utcnow().timestamp())}"
    filename = f"{fid}_{name}.{ext}"
    path = os.path.join(SHEETS_DIR, filename)

    templates = {
        "xlsx": "blank.xlsx",
        "docx": "blank.docx",
        "pptx": "blank.pptx"
    }

    template_path = os.path.join(BASE_DIR, "templates", templates[ext])
    shutil.copyfile(template_path, path)

    file_type = "sheet" if ext == "xlsx" else "doc" if ext == "docx" else "slide"

    db = get_db()
    db.execute("""
        INSERT INTO files
        (file_id, name, owner, folder_id, path, mime, file_type, created_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (
        fid,
        f"{name}.{ext}",
        owner,
        folder_id,
        path,
        "application/octet-stream",
        file_type,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))
    db.commit()
    db.close()

    return fid


def log_audit(actor, action, item_type, item_id, details=None, device=None, session_id=None):
    db = get_db()
    db.execute("""
        INSERT INTO audit_log
        (event_type, actor, actor_role, ip, user_agent, item_type, item_id, item_name, context_json, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        action,
        actor,
        "",
        "",
        "",
        item_type,
        item_id,
        "",
        json.dumps(details or {}, ensure_ascii=False),
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))
    db.commit()
    db.close()


def create_version(file_id, path, created_by, reason, versions_dir):
    os.makedirs(versions_dir, exist_ok=True)
    version_id = f"VER_{int(datetime.utcnow().timestamp())}"
    ext = os.path.splitext(path)[1]
    version_path = os.path.join(versions_dir, f"{file_id}_{version_id}{ext}")
    shutil.copyfile(path, version_path)

    db = get_db()
    db.execute("""
        INSERT INTO file_versions (file_id, version_id, path, created_by, created_at, reason)
        VALUES (?,?,?,?,?,?)
    """, (
        file_id,
        version_id,
        version_path,
        created_by,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        reason
    ))
    db.commit()
    db.close()
    return version_id


def extract_docx_text(path):
    try:
        with zipfile.ZipFile(path, "r") as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<[^>]+>", "", xml)
        return xml
    except Exception:
        return ""


def extract_xlsx_text(path):
    try:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    except Exception:
        return ""
    parts = []
    for name, df in sheets.items():
        df = df.fillna("")
        parts.append(str(name))
        parts.append("\n".join(["\t".join(map(str, row)) for row in df.values.tolist()]))
    return "\n".join(parts)


def extract_text_from_file(path, file_type):
    if not path:
        return ""
    if file_type == "sheet":
        return extract_xlsx_text(path)
    if file_type == "doc":
        return extract_docx_text(path)
    if file_type == "slide":
        return extract_docx_text(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def index_file_search(file_id, path, owner, department, file_type, updated_at):
    content = extract_text_from_file(path, file_type)
    content = (content or "")[:SEARCH_MAX_CHARS]
    db = get_db()
    try:
        db.execute("DELETE FROM search_index WHERE file_id=?", (file_id,))
        db.execute("""
            INSERT INTO search_index (file_id, content, owner, department, updated_at, file_type)
            VALUES (?,?,?,?,?,?)
        """, (file_id, content, owner, department, updated_at, file_type))
        db.commit()
    except Exception:
        pass
    db.close()


def classify_file(name, content):
    n = (name or "").lower()
    c = (content or "").lower()
    if "invoice" in n or "فاتورة" in c:
        return "ACCOUNTING", 0.75, "regex", "invoice keyword"
    if "quantity" in c and "price" in c:
        return "SALES", 0.65, "regex", "quantity+price pattern"
    return None, 0.0, "rule", "no match"


def save_classification(file_id, category, confidence, method, rules_hit, updated_by="system"):
    if not category:
        return
    db = get_db()
    db.execute("""
        INSERT INTO file_classifications
        (file_id, category, confidence, method, rules_hit, updated_at, updated_by)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(file_id) DO UPDATE SET
            category=excluded.category,
            confidence=excluded.confidence,
            method=excluded.method,
            rules_hit=excluded.rules_hit,
            updated_at=excluded.updated_at,
            updated_by=excluded.updated_by
    """, (
        file_id,
        category,
        confidence,
        method,
        rules_hit,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        updated_by
    ))
    db.commit()
    db.close()


def update_last_opened(file_id):
    db = get_db()
    db.execute("UPDATE files SET last_opened_at=? WHERE file_id=?", (
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        file_id
    ))
    db.commit()
    db.close()


def mark_archived(file_id, compressed=False):
    db = get_db()
    row = db.execute("SELECT path, name FROM files WHERE file_id=?", (file_id,)).fetchone()
    db.execute("""
        UPDATE files
        SET archived_at=?, compressed_at=?
        WHERE file_id=?
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        datetime.now().strftime("%Y-%m-%d %H:%M") if compressed else None,
        file_id
    ))
    db.commit()
    db.close()

    if row:
        try:
            os.makedirs(ARCHIVE_DIR, exist_ok=True)
            dst = os.path.join(ARCHIVE_DIR, f"{file_id}_{os.path.basename(row['path'])}")
            if not os.path.exists(dst):
                shutil.copyfile(row["path"], dst)
        except Exception:
            pass


def restore_from_archive(file_id):
    db = get_db()
    db.execute("""
        UPDATE files
        SET archived_at=NULL, compressed_at=NULL
        WHERE file_id=?
    """, (file_id,))
    db.commit()
    db.close()


def evaluate_automation_rules(event_type, context):
    db = get_db()
    rules = db.execute("""
        SELECT * FROM automation_rules
        WHERE trigger=? AND (is_enabled=1 OR is_active=1)
    """, (event_type,)).fetchall()
    db.close()

    for r in rules:
        try:
            conditions = json.loads((r["conditions_json"] or r["conditions"] or "{}"))
            actions = json.loads((r["actions_json"] or r["actions"] or "[]"))
        except Exception:
            continue

        if not _conditions_match(conditions, context):
            continue

        for action in actions:
            _apply_action(action, context)


def _conditions_match(conditions, context):
    for key, expected in (conditions or {}).items():
        if context.get(key) != expected:
            return False
    return True


def _apply_action(action, context):
    name = (action or {}).get("name")
    if name == "move_to_archive":
        mark_archived(context.get("file_id"), compressed=False)
    elif name == "refresh_dashboard":
        # dashboards read live from file; nothing to persist
        return
    elif name == "notify_manager":
        return
    elif name == "generate_pdf":
        return


def transfer_ownership(item_type, item_id, new_owner, actor, signature, include_children=1, reason=""):
    db = get_db()
    if item_type == "file":
        row = db.execute("SELECT owner FROM files WHERE file_id=?", (item_id,)).fetchone()
        if not row:
            db.close()
            return False
        old_owner = row["owner"]
        db.execute("UPDATE files SET owner=? WHERE file_id=?", (new_owner, item_id))
    else:
        row = db.execute("SELECT owner FROM folders WHERE folder_id=?", (item_id,)).fetchone()
        if not row:
            db.close()
            return False
        old_owner = row["owner"]
        db.execute("UPDATE folders SET owner=? WHERE folder_id=?", (new_owner, item_id))
        _transfer_folder_tree(db, item_id, new_owner)

    db.execute("""
        INSERT INTO ownership_transfers
        (item_type, item_id, from_owner, to_owner, include_children, reason, signed_token, created_at, created_by)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        item_type,
        item_id,
        old_owner,
        new_owner,
        include_children,
        reason,
        signature,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        actor
    ))
    db.commit()
    db.close()
    log_audit(actor, "ownership_transfer", item_type, item_id, {
        "old_owner": old_owner,
        "new_owner": new_owner,
        "signature": signature,
        "reason": reason,
        "include_children": include_children
    })
    return True


def _transfer_folder_tree(db, folder_id, new_owner):
    # Update child folders
    child_folders = db.execute(
        "SELECT folder_id FROM folders WHERE parent_id=?",
        (folder_id,)
    ).fetchall()
    for r in child_folders:
        db.execute("UPDATE folders SET owner=? WHERE folder_id=?", (new_owner, r["folder_id"]))
        _transfer_folder_tree(db, r["folder_id"], new_owner)

    # Update files under this folder
    db.execute("UPDATE files SET owner=? WHERE folder_id=?", (new_owner, folder_id))


def build_excel_diff(old_path, new_path):
    diff = []
    try:
        old_sheets = pd.read_excel(old_path, sheet_name=None, header=None, dtype=object)
        new_sheets = pd.read_excel(new_path, sheet_name=None, header=None, dtype=object)
    except Exception:
        return diff

    all_names = set(old_sheets.keys()) | set(new_sheets.keys())
    for name in all_names:
        old_df = old_sheets.get(name, pd.DataFrame())
        new_df = new_sheets.get(name, pd.DataFrame())
        max_rows = max(len(old_df.index), len(new_df.index))
        max_cols = max(len(old_df.columns), len(new_df.columns))

        old_df = old_df.reindex(index=range(max_rows), columns=range(max_cols))
        new_df = new_df.reindex(index=range(max_rows), columns=range(max_cols))

        for r in range(max_rows):
            for c in range(max_cols):
                old_val = old_df.iat[r, c]
                new_val = new_df.iat[r, c]
                if (pd.isna(old_val) and pd.isna(new_val)) or old_val == new_val:
                    continue
                diff.append({
                    "sheet": name,
                    "row": r + 1,
                    "col_index": c + 1,
                    "col_letter": _col_letter(c + 1),
                    "old": "" if pd.isna(old_val) else old_val,
                    "new": "" if pd.isna(new_val) else new_val
                })
    return diff


def _col_letter(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_latest_version_hash(file_id):
    """Return hash of latest version or None. Used for skip-if-unchanged logic."""
    db = get_db()
    row = db.execute(
        "SELECT hash FROM file_versions WHERE file_id=? ORDER BY version_no DESC LIMIT 1",
        (file_id,)
    ).fetchone()
    db.close()
    return (row.get("hash") or "").strip() if row else None


def _parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip()[:19], fmt)
        except Exception:
            continue
    return None


def get_file_edit_lock_info(file_id):
    """
    بعد مرور CELL_LOCK_AFTER_HOURS: الملف يُقفل للتعديل لغير المالك، ويُصدر نسخة (issued).
    Returns: dict with locked (bool), owner (str), issued_version_exists (bool), lock_time (datetime|None).
    """
    try:
        from config import CELL_LOCK_AFTER_HOURS
    except ImportError:
        CELL_LOCK_AFTER_HOURS = 12
    db = get_db()
    row = db.execute(
        "SELECT owner, created_at FROM files WHERE file_id=?",
        (file_id,)
    ).fetchone()
    if not row:
        db.close()
        return {"locked": False, "owner": None, "issued_version_exists": False, "lock_time": None}
    owner = row["owner"]
    file_created = _parse_dt(row.get("created_at"))
    first_ver = db.execute(
        "SELECT created_at FROM file_versions WHERE file_id=? ORDER BY version_no ASC LIMIT 1",
        (file_id,)
    ).fetchone()
    issued = db.execute(
        "SELECT 1 FROM file_versions WHERE file_id=? AND version_type=? LIMIT 1",
        (file_id, "issued")
    ).fetchone()
    db.close()
    first_activity = file_created
    if first_ver and first_ver.get("created_at"):
        ver_dt = _parse_dt(first_ver["created_at"])
        if ver_dt and (not first_activity or ver_dt < first_activity):
            first_activity = ver_dt
    if not first_activity:
        return {"locked": False, "owner": owner, "issued_version_exists": bool(issued), "lock_time": None}
    lock_time = first_activity + timedelta(hours=CELL_LOCK_AFTER_HOURS)
    locked = datetime.now() >= lock_time
    return {
        "locked": locked,
        "owner": owner,
        "issued_version_exists": bool(issued),
        "lock_time": lock_time,
    }


def ensure_issued_version(file_id, path, versions_dir, created_by):
    """
    بعد مرور المدة: إنشاء نسخة واحدة من نوع issued إن لم تكن موجودة.
    يُستدعى عند الحفظ من المالك بعد انقضاء مدة القفل.
    """
    info = get_file_edit_lock_info(file_id)
    if not info["locked"] or info["issued_version_exists"]:
        return None
    return create_version(
        file_id, path, created_by, "issued_after_lock",
        versions_dir, version_type="issued", notes="نسخة مصدرة بعد انقضاء مدة القفل"
    )


def create_version(file_id, path, created_by, reason, versions_dir, version_type=None, notes=None, skip_if_unchanged=False):
    """
    إنشاء نسخة جديدة. يُستدعى فقط عند تغيير المحتوى (إضافة/حذف بيانات) وليس على كل عملية حفظ.
    If skip_if_unchanged=True and content hash matches latest, return existing version_no without creating.
    """
    if skip_if_unchanged:
        try:
            new_hash = _sha256_file(path)
            latest_hash = _get_latest_version_hash(file_id)
            if new_hash and latest_hash and new_hash == latest_hash:
                db = get_db()
                row = db.execute(
                    "SELECT MAX(version_no) AS max_no FROM file_versions WHERE file_id=?",
                    (file_id,)
                ).fetchone()
                db.close()
                return int(row["max_no"] or 0)
        except Exception:
            pass

    os.makedirs(versions_dir, exist_ok=True)
    ext = os.path.splitext(path)[1]

    db = get_db()
    row = db.execute("SELECT MAX(version_no) AS max_no FROM file_versions WHERE file_id=?", (file_id,)).fetchone()
    next_no = int(row["max_no"] or 0) + 1

    version_type = version_type or (reason or "manual")
    version_path = os.path.join(versions_dir, f"{file_id}_v{next_no}{ext}")
    shutil.copyfile(path, version_path)

    size_bytes = None
    try:
        size_bytes = os.path.getsize(version_path)
    except Exception:
        size_bytes = None

    file_hash = ""
    try:
        file_hash = _sha256_file(version_path)
    except Exception:
        file_hash = ""

    db.execute("""
        INSERT INTO file_versions
        (file_id, version_no, version_type, stored_path, hash, size_bytes, created_at, created_by, notes)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        file_id,
        next_no,
        version_type,
        version_path,
        file_hash,
        size_bytes,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        created_by,
        notes
    ))
    db.commit()
    db.close()
    return next_no

def _latest_version_time(file_id, version_type):
    db = get_db()
    row = db.execute("""
        SELECT created_at FROM file_versions
        WHERE file_id=? AND version_type=?
        ORDER BY created_at DESC LIMIT 1
    """, (file_id, version_type)).fetchone()
    db.close()
    if not row or not row["created_at"]:
        return None
    try:
        return datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M")
    except Exception:
        return None

def ensure_periodic_versions(file_id, path, created_by, versions_dir):
    """Create daily/weekly versions only if content hash changed. No phantom versions."""
    now = datetime.now()

    last_daily = _latest_version_time(file_id, "daily")
    if (not last_daily or (now - last_daily).days >= 1):
        create_version(
            file_id,
            path,
            created_by,
            "daily_snapshot",
            versions_dir,
            version_type="daily",
            skip_if_unchanged=True
        )

    last_weekly = _latest_version_time(file_id, "weekly")
    if (not last_weekly or (now - last_weekly).days >= 7):
        create_version(
            file_id,
            path,
            created_by,
            "weekly_snapshot",
            versions_dir,
            version_type="weekly",
            skip_if_unchanged=True
        )


def list_versions(file_id):
    db = get_db()
    rows = db.execute("""
        SELECT version_no, version_type, stored_path, hash, size_bytes, created_at, created_by, notes
        FROM file_versions
        WHERE file_id=?
        ORDER BY version_no DESC
    """, (file_id,)).fetchall()
    db.close()
    return [dict(r) for r in rows]


def add_file_participant(file_id, user_id):
    """تسجيل مشاركة مستخدم في الملف (فتح أو تعديل)."""
    if not file_id or not user_id:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    db = get_db()
    try:
        row = db.execute(
            "SELECT first_seen_at FROM file_participants WHERE file_id=? AND user_id=?",
            (file_id, user_id)
        ).fetchone()
        if row:
            db.execute(
                "UPDATE file_participants SET last_seen_at=? WHERE file_id=? AND user_id=?",
                (now, file_id, user_id)
            )
        else:
            db.execute(
                "INSERT INTO file_participants (file_id, user_id, first_seen_at, last_seen_at) VALUES (?,?,?,?)",
                (file_id, user_id, now, now)
            )
        db.commit()
    except Exception:
        pass
    db.close()


def list_file_participants(file_id):
    """قائمة الأشخاص المشاركين في الملف (من فتح أو عدّل)."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT user_id, first_seen_at, last_seen_at FROM file_participants WHERE file_id=? ORDER BY last_seen_at DESC",
            (file_id,)
        ).fetchall()
        db.close()
        return [dict(r) for r in rows]
    except Exception:
        db.close()
        return []


def rollback_to_version(file_id, version_no, actor):
    db = get_db()
    file_row = db.execute("SELECT path FROM files WHERE file_id=?", (file_id,)).fetchone()
    version_row = db.execute("""
        SELECT stored_path FROM file_versions
        WHERE file_id=? AND version_no=?
    """, (file_id, version_no)).fetchone()
    db.close()

    if not file_row or not version_row:
        return False

    create_version(file_id, file_row["path"], actor, "pre_rollback", os.path.dirname(version_row["stored_path"]), version_type="pre_rollback")
    shutil.copyfile(version_row["stored_path"], file_row["path"])
    # updated_at kept for "last modified" UI; document.key does NOT use it (uses version_no only)
    db = get_db()
    db.execute(
        "UPDATE files SET updated_at=? WHERE file_id=?",
        (datetime.now().strftime("%Y-%m-%d %H:%M"), file_id)
    )
    db.commit()
    db.close()
    return True


def extract_text_for_index(path, file_type):
    content = extract_text_from_file(path, file_type)
    return (content or "")[:SEARCH_MAX_CHARS]


def index_item(item_type, item_id, title, content, tags, department, updated_by, updated_at):
    db = get_db()
    payload = (content or "")[:SEARCH_MAX_CHARS]
    try:
        db.execute("DELETE FROM search_index WHERE item_type=? AND item_id=?", (item_type, item_id))
        db.execute("""
            INSERT INTO search_index
            (item_type, item_id, title, content, tags, department, updated_by, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (item_type, item_id, title, payload, tags, department, updated_by, updated_at))
        db.commit()
        db.close()
        return True
    except Exception:
        # Fallback to legacy schema
        try:
            db.execute("DELETE FROM search_index WHERE file_id=?", (item_id,))
            db.execute("""
                INSERT INTO search_index (file_id, content, owner, department, updated_at, file_type)
                VALUES (?,?,?,?,?,?)
            """, (item_id, payload, updated_by, department, updated_at, item_type))
            db.commit()
        except Exception:
            pass
    db.close()
    return False


def search(query, owner=None, filters=None):
    filters = filters or {}
    db = get_db()
    params = [query]
    sql = """
        SELECT item_type, item_id, title, department, updated_by, updated_at
        FROM search_index
        WHERE search_index MATCH ?
    """
    if owner:
        # legacy schema uses owner
        sql += " AND (updated_by=? OR owner=?)"
        params.extend([owner, owner])
    if filters.get("department"):
        sql += " AND department=?"
        params.append(filters["department"])
    sql += " ORDER BY bm25(search_index) LIMIT 50"

    try:
        rows = db.execute(sql, tuple(params)).fetchall()
        db.close()
        return [dict(r) for r in rows]
    except Exception:
        # Fallback for legacy columns
        try:
            rows = db.execute("""
                SELECT file_id AS item_id, owner AS updated_by, department, updated_at, file_type AS item_type
                FROM search_index
                WHERE search_index MATCH ?
                ORDER BY bm25(search_index) LIMIT 50
            """, (query,)).fetchall()
            db.close()
            return [dict(r) for r in rows]
        except Exception:
            db.close()
            return []

