"""
FileService — Centralized file operations with permission check + audit.
Routes must call FileService instead of direct DB/file writes for file card actions.
"""
from modules.files import (
    rename_item,
    move_item,
    move_to_trash,
    restore_from_trash,
    log_audit,
    get_db,
)
from modules.permissions import get_allowed_actions, get_user_role


def rename(item_type, item_id, new_name, actor, session_department=None):
    """Rename file/folder. Returns (ok, error)."""
    actions = get_allowed_actions(actor, item_type, item_id)
    if not actions.get("rename", False):
        return False, "role"
    if not new_name or not new_name.strip():
        return False, "empty_name"
    try:
        rename_item(item_type, item_id, new_name.strip(), actor)
        log_audit(actor, "rename", item_type, item_id, {"new_name": new_name.strip()})
        return True, None
    except Exception as e:
        return False, str(e)


def move(item_type, item_id, target_folder_id, actor, session_department=None):
    """Move file/folder. Returns (ok, error)."""
    role = get_user_role(item_type, item_id, actor, session_department or "")
    if role not in ("editor", "owner"):
        return False, "no_permission"
    target = target_folder_id if target_folder_id not in ("", "ROOT") else None
    try:
        move_item(item_type, item_id, target, actor)
        log_audit(actor, "move", item_type, item_id, {"target_folder": target})
        return True, None
    except Exception as e:
        return False, str(e)


def trash(item_type, item_id, actor, session_department=None):
    """Move to trash. Returns (ok, error)."""
    actions = get_allowed_actions(actor, item_type, item_id)
    if not actions.get("delete", False):
        return False, "role"
    try:
        move_to_trash(item_type, item_id, actor)
        log_audit(actor, "trash", item_type, item_id, {})
        return True, None
    except Exception as e:
        return False, str(e)


def restore(item_type, item_id, actor, session_department=None):
    """Restore from trash. Returns (ok, error)."""
    actions = get_allowed_actions(actor, item_type, item_id)
    if not actions.get("delete", False):
        return False, "role"
    try:
        restore_from_trash(item_type, item_id, actor)
        log_audit(actor, "restore", item_type, item_id, {})
        return True, None
    except Exception as e:
        return False, str(e)
