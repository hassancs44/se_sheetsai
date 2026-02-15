import json
from datetime import datetime
from flask import request as flask_request
from modules.db import get_db


def _get_ip(req):
    if not req:
        return ""
    # Prefer proxy headers if present
    ip = req.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not ip:
        ip = req.headers.get("X-Real-IP", "").strip()
    if not ip:
        ip = req.remote_addr or ""
    return ip


def log_event(
    event_type,
    actor,
    request,
    item_type=None,
    item_id=None,
    item_name=None,
    context=None
):
    req = request or flask_request
    ip = _get_ip(req)
    user_agent = (req.headers.get("User-Agent") if req else "") or ""
    actor_role = ""
    try:
        actor_role = (req.session.get("role") if hasattr(req, "session") else "") or ""
    except Exception:
        actor_role = ""

    payload = {
        "event_type": event_type,
        "actor": actor,
        "actor_role": actor_role,
        "ip": ip,
        "user_agent": user_agent,
        "item_type": item_type,
        "item_id": item_id,
        "item_name": item_name,
        "context_json": json.dumps(context or {}, ensure_ascii=False),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    try:
        db = get_db()
        db.execute("""
            INSERT INTO audit_log
            (event_type, actor, actor_role, ip, user_agent, item_type, item_id, item_name, context_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            payload["event_type"],
            payload["actor"],
            payload["actor_role"],
            payload["ip"],
            payload["user_agent"],
            payload["item_type"],
            payload["item_id"],
            payload["item_name"],
            payload["context_json"],
            payload["created_at"]
        ))
        db.commit()
        db.close()
    except Exception:
        # Do not block core flows on audit failure
        return False
    return True

def log_share_access(actor, request, item_type, item_id, context=None):
    return log_event("share_access", actor, request, item_type=item_type, item_id=item_id, context=context)

def log_share_denied(actor, request, item_type, item_id, reason, context=None):
    payload = {"reason": reason}
    if context:
        payload.update(context)
    return log_event("share_denied", actor, request, item_type=item_type, item_id=item_id, context=payload)

def log_share_expired(actor, request, item_type, item_id, context=None):
    return log_event("share_expired", actor, request, item_type=item_type, item_id=item_id, context=context)
