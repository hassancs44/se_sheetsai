from functools import wraps
import json
from flask import session, abort
from modules.db import get_db
from modules.auth import get_user_from_excel
from config import ALLOW_DOWNLOAD_DEFAULT, ALLOW_PRINT_DEFAULT, ALLOW_COPY_DEFAULT

ROLE_ORDER = {
    "viewer": 1,
    "editor": 2,
    "owner": 3
}

def get_user_role(item_type, item_id, user, department):
    db = get_db()

    # 1️⃣ Owner
    row = db.execute(
        f"SELECT owner FROM {item_type}s WHERE {item_type}_id=?",
        (item_id,)
    ).fetchone()

    if row and row["owner"] == user:
        db.close()
        return "owner"

    # 2️⃣ User share
    p = db.execute("""
        SELECT role FROM permissions
        WHERE item_type=? AND item_id=?
        AND target_type='user' AND target_value=?
    """, (item_type, item_id, user)).fetchone()

    if p:
        db.close()
        return p["role"]

    # 3️⃣ Department share
    p = db.execute("""
        SELECT role FROM permissions
        WHERE item_type=? AND item_id=?
        AND target_type='department' AND target_value=?
    """, (item_type, item_id, department)).fetchone()

    if p:
        db.close()
        return p["role"]

    # 4️⃣ Public
    p = db.execute("""
        SELECT role FROM permissions
        WHERE item_type=? AND item_id=?
        AND target_type='public'
    """, (item_type, item_id)).fetchone()

    db.close()
    return p["role"] if p else None


def require_permission(item_type, min_role):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                abort(401)

            item_id = kwargs.get(f"{item_type}_id")
            access = resolve_item_access(
                item_type,
                item_id,
                session["user"],
                session["department"]
            )
            if not access.get("allowed"):
                abort(403)

            role = access.get("role")
            if role not in ROLE_ORDER or ROLE_ORDER[role] < ROLE_ORDER[min_role]:
                abort(403)

            return func(*args, **kwargs)
        return wrapper
    return decorator


def _get_user_info(user):
    info = get_user_from_excel(user)
    if not info:
        return None, None
    return info.get("role"), info.get("department")


def get_effective_role(user, file_id):
    role, department = _get_user_info(user)
    if not role and not department:
        return None
    return get_user_role("file", file_id, user, department)


def get_cell_rules_for_user(file_id, user):
    role, department = _get_user_info(user)
    db = get_db()
    rows = db.execute("""
        SELECT item_type, item_id, target_type, target_value, sheet_name, scope_type, scope_value, perm
        FROM cell_permissions
        WHERE item_type='file' AND item_id=?
    """, (file_id,)).fetchall()
    db.close()

    rules = []
    for r in rows:
        ttype = (r["target_type"] or "").lower()
        tvalue = (r["target_value"] or "")
        if ttype == "user" and tvalue != user:
            continue
        if ttype == "department" and tvalue != department:
            continue
        if ttype == "role" and tvalue != role:
            continue
        if ttype == "public":
            pass
        rules.append({
            "sheet_name": r["sheet_name"],
            "scope_type": r["scope_type"],
            "scope_value": r["scope_value"],
            "perm": r["perm"]
        })
    return rules


def _cell_in_scope(scope_type, scope_value, row, col_letter, col_index):
    st = (scope_type or "").lower()
    sv = (scope_value or "").upper()
    if st == "cell":
        return sv == f"{col_letter}{row}"
    if st == "column":
        return sv == col_letter
    if st == "row":
        try:
            return int(sv) == row
        except Exception:
            return False
    if st == "range":
        try:
            start, end = sv.split(":")
            s_col = "".join([c for c in start if c.isalpha()])
            s_row = int("".join([c for c in start if c.isdigit()]))
            e_col = "".join([c for c in end if c.isalpha()])
            e_row = int("".join([c for c in end if c.isdigit()]))
            return _col_to_index(s_col) <= col_index <= _col_to_index(e_col) and s_row <= row <= e_row
        except Exception:
            return False
    return False


def is_cell_edit_allowed(file_id, user, sheet, cell_or_range):
    rules = get_cell_rules_for_user(file_id, user)
    if not rules:
        return True

    cell = (cell_or_range or "").upper().strip()
    if ":" in cell:
        cell = cell.split(":")[0]
    col_letter = "".join([c for c in cell if c.isalpha()])
    try:
        row = int("".join([c for c in cell if c.isdigit()]))
    except Exception:
        return False
    col_index = _col_to_index(col_letter)

    for r in rules:
        if r.get("sheet_name") and sheet and r["sheet_name"] != sheet:
            continue
        if r.get("perm") != "edit":
            continue
        if _cell_in_scope(r["scope_type"], r["scope_value"], row, col_letter, col_index):
            return True
    return False


def filter_onlyoffice_permissions(user, file_id, base_permissions):
    role, department = _get_user_info(user)
    access = resolve_item_access("file", file_id, user, department)
    effective_role = access.get("role")

    perms = {
        "download": bool(base_permissions.get("download", ALLOW_DOWNLOAD_DEFAULT)),
        "print": bool(base_permissions.get("print", ALLOW_PRINT_DEFAULT)),
        "copy": bool(base_permissions.get("copy", ALLOW_COPY_DEFAULT)),
        "edit": bool(base_permissions.get("edit", True))
    }

    if not access.get("allowed"):
        perms.update({"download": False, "print": False, "copy": False, "edit": False})
        perms["comment"] = False
        perms["review"] = False
        perms["fillForms"] = False
        return perms

    if effective_role not in ("editor", "owner"):
        perms["edit"] = False

    policy = _get_department_policy(department) if department else {}
    if not policy.get("download", True):
        perms["download"] = False
    if not policy.get("print", True):
        perms["print"] = False
    if not policy.get("copy", True):
        perms["copy"] = False

    perms["comment"] = effective_role in ("editor", "owner")
    perms["review"] = effective_role in ("editor", "owner")
    perms["fillForms"] = effective_role in ("editor", "owner")
    return perms

from functools import wraps
from flask import session, abort
from modules.db import get_db
from datetime import datetime

ROLE_ORDER = {
    "viewer": 1,
    "editor": 2,
    "owner": 3
}

def _parse_datetime(value):
    if not value:
        return None
    v = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt)
        except Exception:
            continue
    return None

def _is_expired(expires_at):
    if not expires_at:
        return False
    exp = _parse_datetime(expires_at)
    if not exp:
        return False
    return exp < datetime.now()

def normalize_expires_at(expires_at):
    if not expires_at:
        return ""
    exp = _parse_datetime(expires_at)
    if not exp:
        return ""
    return exp.strftime("%Y-%m-%d %H:%M")

def is_share_expired(expires_at):
    return _is_expired(expires_at)

def _split_target_value(raw):
    raw = raw or ""
    if "||" not in raw:
        return raw, {}
    base, meta_str = raw.split("||", 1)
    meta = {}
    for part in (meta_str or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            meta[k.strip()] = v.strip()
        else:
            meta[part] = True
    return base, meta

def parse_target_value(raw):
    return _split_target_value(raw)

def get_share_scope(item_type, target_value):
    _, meta = _split_target_value(target_value)
    return _share_scope_from_meta(item_type, meta)

def encode_target_value(value, scope=None, external=False):
    base = value or ""
    meta = []
    if scope:
        meta.append(f"scope={scope}")
    if external:
        meta.append("external=1")
    if not meta:
        return base
    return f"{base}||{';'.join(meta)}"

def _share_scope_from_meta(item_type, meta):
    if meta and meta.get("scope"):
        return meta.get("scope")
    return "folder" if item_type == "folder" else "file"

def _match_target(target_type, target_value, user, department, user_role):
    if target_type == "user":
        return target_value == user
    if target_type == "department":
        return target_value == department
    if target_type == "role":
        return target_value == user_role
    if target_type == "public":
        return True
    if target_type == "external":
        return target_value == user
    return False

def get_user_role(item_type, item_id, user, department):
    db = get_db()

    # 1️⃣ Owner
    row = db.execute(
        f"SELECT owner FROM {item_type}s WHERE {item_type}_id=?",
        (item_id,)
    ).fetchone()

    if row and row["owner"] == user:
        db.close()
        return "owner"

    # 2️⃣ Shared (user/department/role/public/external)
    user_role, _ = _get_user_info(user)
    rows = db.execute("""
        SELECT role, expires_at, target_type, target_value
        FROM permissions
        WHERE item_type=? AND item_id=?
    """, (item_type, item_id)).fetchall()
    db.close()

    best_role = None
    for r in rows:
        if _is_expired(r["expires_at"]):
            continue
        base_value, _ = _split_target_value(r["target_value"])
        if not _match_target(r["target_type"], base_value, user, department, user_role):
            continue
        role = r["role"]
        if role not in ROLE_ORDER:
            continue
        if not best_role or ROLE_ORDER[role] > ROLE_ORDER[best_role]:
            best_role = role
    return best_role


def get_cell_permissions(file_id, sheet_name, user, department, role):
    db = get_db()
    rows = db.execute("""
        SELECT scope_type, scope_value, role, target_type, target_value
        FROM cell_permissions
        WHERE file_id=? AND (sheet_name IS NULL OR sheet_name=?)
    """, (file_id, sheet_name)).fetchall()
    db.close()

    rules = []
    for r in rows:
        if r["target_type"] == "user" and r["target_value"] != user:
            continue
        if r["target_type"] == "department" and r["target_value"] != department:
            continue
        if r["target_type"] == "role" and r["target_value"] != role:
            continue
        rules.append({
            "scope_type": r["scope_type"],
            "scope_value": r["scope_value"],
            "role": r["role"]
        })
    return rules


def is_cell_edit_allowed(rules, row, col_letter, col_index):
    for r in rules:
        if r["role"] != "editor":
            continue
        st = (r["scope_type"] or "").lower()
        sv = (r["scope_value"] or "").upper()

        if st == "column" and sv == col_letter:
            return True
        if st == "row":
            try:
                if int(sv) == row:
                    return True
            except Exception:
                continue
        if st == "range":
            # Range like A1:C10
            try:
                start, end = sv.split(":")
                s_col = "".join([c for c in start if c.isalpha()])
                s_row = int("".join([c for c in start if c.isdigit()]))
                e_col = "".join([c for c in end if c.isalpha()])
                e_row = int("".join([c for c in end if c.isdigit()]))
                if _col_to_index(s_col) <= col_index <= _col_to_index(e_col) and s_row <= row <= e_row:
                    return True
            except Exception:
                continue
    return False


def _col_to_index(col):
    n = 0
    for c in col:
        n = n * 26 + (ord(c) - 64)
    return n


def require_permission(item_type, min_role):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                abort(401)

            item_id = kwargs.get(f"{item_type}_id")
            access = resolve_item_access(
                item_type,
                item_id,
                session["user"],
                session["department"]
            )
            if not access.get("allowed"):
                abort(403)

            role = access.get("role")
            if role not in ROLE_ORDER or ROLE_ORDER[role] < ROLE_ORDER[min_role]:
                abort(403)

            return func(*args, **kwargs)
        return wrapper
    return decorator

def _get_department_policy(department):
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

def _share_allowed_by_policy(owner_department, target_type, target_value, target_department):
    policy = _get_department_policy(owner_department)
    if target_type == "public" and not policy.get("allow_public_share", True):
        return False, "public_share_blocked"
    if target_type in ("user", "department", "role", "external") and not policy.get("share_outside_department", True):
        if target_department and target_department != owner_department:
            return False, "cross_department_blocked"
        if target_type == "external":
            return False, "external_share_blocked"
    return True, ""

def _select_best_share(rows, user, department, user_role, owner_department, require_recursive=False):
    best = None
    best_role = None
    for r in rows:
        if _is_expired(r["expires_at"]):
            continue
        base_value, meta = _split_target_value(r["target_value"])
        if not _match_target(r["target_type"], base_value, user, department, user_role):
            continue
        scope = _share_scope_from_meta(r["item_type"], meta)
        if require_recursive and scope != "recursive":
            continue

        target_department = None
        if r["target_type"] == "department":
            target_department = base_value
        elif r["target_type"] in ("user", "external"):
            _, target_department = _get_user_info(base_value)
        elif r["target_type"] == "role":
            target_department = department

        allowed, _ = _share_allowed_by_policy(owner_department, r["target_type"], base_value, target_department)
        if not allowed:
            continue

        role = r["role"]
        if role not in ROLE_ORDER:
            continue
        if not best_role or ROLE_ORDER[role] > ROLE_ORDER[best_role]:
            best_role = role
            best = {
                "role": role,
                "target_type": r["target_type"],
                "target_value": base_value,
                "expires_at": r["expires_at"],
                "scope": scope,
                "owner_department": owner_department
            }
    return best

def _select_expired_share(rows, user, department, user_role, require_recursive=False):
    best = None
    best_role = None
    for r in rows:
        if not _is_expired(r["expires_at"]):
            continue
        base_value, meta = _split_target_value(r["target_value"])
        if not _match_target(r["target_type"], base_value, user, department, user_role):
            continue
        scope = _share_scope_from_meta(r["item_type"], meta)
        if require_recursive and scope != "recursive":
            continue
        role = r["role"]
        if role not in ROLE_ORDER:
            continue
        if not best_role or ROLE_ORDER[role] > ROLE_ORDER[best_role]:
            best_role = role
            best = {
                "role": role,
                "target_type": r["target_type"],
                "target_value": base_value,
                "expires_at": r["expires_at"],
                "scope": scope
            }
    return best

def _fetch_item_owner(item_type, item_id):
    db = get_db()
    if item_type == "file":
        row = db.execute("SELECT owner, folder_id, name FROM files WHERE file_id=?", (item_id,)).fetchone()
    else:
        row = db.execute("SELECT owner, parent_id, name FROM folders WHERE folder_id=?", (item_id,)).fetchone()
    db.close()
    return row

def _folder_ancestors(folder_id):
    if not folder_id:
        return []
    db = get_db()
    ancestors = []
    current = folder_id
    while current:
        row = db.execute("SELECT folder_id, parent_id FROM folders WHERE folder_id=?", (current,)).fetchone()
        if not row:
            break
        ancestors.append(row["folder_id"])
        current = row["parent_id"]
    db.close()
    return ancestors

def resolve_item_access(item_type, item_id, user, department):
    item = _fetch_item_owner(item_type, item_id)
    if not item:
        return {"allowed": False, "reason": "not_found", "role": None}

    owner = item["owner"]
    owner_role, owner_department = _get_user_info(owner)
    user_role, _ = _get_user_info(user)

    if owner == user:
        access = {
            "allowed": True,
            "role": "owner",
            "reason": "",
            "owner": owner,
            "owner_department": owner_department,
            "share": None
        }
        if item_type == "file":
            policy = _get_department_policy(department)
            ext = ((item["name"] or "").split(".")[-1] or "").lower() if item and "name" in item.keys() else ""
            if policy.get("allowed_file_types") and ext not in policy.get("allowed_file_types"):
                access["allowed"] = False
                access["reason"] = "file_type_policy"
        return access

    db = get_db()
    rows = db.execute("""
        SELECT item_type, item_id, role, expires_at, target_type, target_value
        FROM permissions
        WHERE item_type=? AND item_id=?
    """, (item_type, item_id)).fetchall()
    db.close()

    direct = _select_best_share(rows, user, department, user_role, owner_department, require_recursive=False)
    if direct:
        access = {
            "allowed": True,
            "role": direct["role"],
            "reason": "",
            "owner": owner,
            "owner_department": owner_department,
            "share": direct
        }
        if item_type == "file":
            policy = _get_department_policy(department)
            ext = ((item["name"] or "").split(".")[-1] or "").lower() if item and "name" in item.keys() else ""
            if policy.get("allowed_file_types") and ext not in policy.get("allowed_file_types"):
                access["allowed"] = False
                access["reason"] = "file_type_policy"
        return access

    # Inherited from folder tree (recursive only)
    if item_type == "file":
        folder_id = item["folder_id"] if item and "folder_id" in item.keys() else None
    else:
        folder_id = item["parent_id"] if item and "parent_id" in item.keys() else None
    for fid in _folder_ancestors(folder_id):
        db = get_db()
        frows = db.execute("""
            SELECT item_type, item_id, role, expires_at, target_type, target_value
            FROM permissions
            WHERE item_type='folder' AND item_id=?
        """, (fid,)).fetchall()
        db.close()
        inherited = _select_best_share(frows, user, department, user_role, owner_department, require_recursive=True)
        if inherited:
            access = {
                "allowed": True,
                "role": inherited["role"],
                "reason": "",
                "owner": owner,
                "owner_department": owner_department,
                "share": inherited
            }
            if item_type == "file":
                policy = _get_department_policy(department)
                ext = ((item["name"] or "").split(".")[-1] or "").lower() if item and "name" in item.keys() else ""
                if policy.get("allowed_file_types") and ext not in policy.get("allowed_file_types"):
                    access["allowed"] = False
                    access["reason"] = "file_type_policy"
            return access

    return {
        "allowed": False,
        "role": None,
        "reason": "no_permission",
        "owner": owner,
        "owner_department": owner_department,
        "share": None
    }


def can_admin_access_dashboard(user, department, access):
    if not access or access.get("allowed"):
        return False
    role, _ = _get_user_info(user)
    if role not in ("مدير عام", "admin"):
        return False
    if access.get("reason") not in ("no_permission", "file_type_policy"):
        return False
    owner_department = access.get("owner_department")
    if owner_department and owner_department != department:
        return False
    return True


def can_access_dashboard(user, dashboard_id):
    role, department = _get_user_info(user)
    db = get_db()
    dashboard = db.execute(
        "SELECT * FROM dashboards WHERE dashboard_id=?",
        (dashboard_id,)
    ).fetchone()
    if not dashboard:
        db.close()
        return False

    if role in ("مدير عام", "admin", "مدير القسم"):
        db.close()
        return True

    if "owner" in dashboard.keys() and dashboard["owner"] == user:
        db.close()
        return True
    if "created_by" in dashboard.keys() and dashboard["created_by"] == user:
        db.close()
        return True

    rows = db.execute("""
        SELECT role, expires_at, target_type, target_value
        FROM permissions
        WHERE item_type='dashboard' AND item_id=?
    """, (dashboard_id,)).fetchall()
    for r in rows:
        if _is_expired(r["expires_at"]):
            continue
        base_value, _ = _split_target_value(r["target_value"])
        if _match_target(r["target_type"], base_value, user, department, role):
            db.close()
            return True

    dash_department = dashboard["department"] if "department" in dashboard.keys() else None
    if dash_department and department and dash_department == department:
        db.close()
        return True

    db.close()

    try:
        from modules.dashboards import get_dashboard_files
    except Exception:
        return False

    file_ids = get_dashboard_files(dashboard_id)
    for fid in file_ids:
        access = resolve_item_access("file", fid, user, department)
        if access.get("allowed"):
            return True
    return False

def get_allowed_actions(user, item_type, item_id):
    role, department = _get_user_info(user)
    access = resolve_item_access(item_type, item_id, user, department)
    allowed = bool(access.get("allowed"))
    effective_role = access.get("role")

    actions = {
        "open": allowed,
        "edit": False,
        "rename": False,
        "move": False,
        "delete": False,
        "share": False,
        "transfer_ownership": False,
        "download": False,
        "print": False,
        "copy": False,
        "versions": False,
        "cell_permissions": False,
        "restore_archive": False
    }

    if not allowed or effective_role not in ROLE_ORDER:
        return actions

    if effective_role in ("editor", "owner"):
        actions["edit"] = True
        actions["rename"] = True
        actions["move"] = True
        actions["versions"] = True

    if effective_role == "owner":
        actions["delete"] = True
        actions["share"] = True
        actions["transfer_ownership"] = True
        actions["cell_permissions"] = True
        actions["restore_archive"] = True

    if item_type == "file":
        policy = _get_department_policy(department) if department else {}
        actions["download"] = bool(ALLOW_DOWNLOAD_DEFAULT) and bool(policy.get("download", True))
        actions["print"] = bool(ALLOW_PRINT_DEFAULT) and bool(policy.get("print", True))
        actions["copy"] = bool(ALLOW_COPY_DEFAULT) and bool(policy.get("copy", True))

    return actions

def find_expired_share_access(item_type, item_id, user, department):
    item = _fetch_item_owner(item_type, item_id)
    if not item:
        return None
    user_role, _ = _get_user_info(user)
    db = get_db()
    rows = db.execute("""
        SELECT item_type, item_id, role, expires_at, target_type, target_value
        FROM permissions
        WHERE item_type=? AND item_id=?
    """, (item_type, item_id)).fetchall()
    db.close()
    expired = _select_expired_share(rows, user, department, user_role, require_recursive=False)
    if expired:
        return expired

    if item_type == "file":
        folder_id = item["folder_id"] if item and "folder_id" in item.keys() else None
    else:
        folder_id = item["parent_id"] if item and "parent_id" in item.keys() else None
    for fid in _folder_ancestors(folder_id):
        db = get_db()
        frows = db.execute("""
            SELECT item_type, item_id, role, expires_at, target_type, target_value
            FROM permissions
            WHERE item_type='folder' AND item_id=?
        """, (fid,)).fetchall()
        db.close()
        expired = _select_expired_share(frows, user, department, user_role, require_recursive=True)
        if expired:
            return expired
    return None
