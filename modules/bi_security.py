# SE_SHEETSAI — BI governance wrapper.
"""
Permission and governance for native BI:
- check_dashboard_view_permission: user must have file access to linked_file_id.
- apply_governance_to_query: remove restricted columns, inject row-level filters.
- Block export if policy forbids download.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from modules.permissions import resolve_item_access
from modules.bi_models import get_dashboard


def check_dashboard_view_permission(
    user_id: str,
    dashboard_id: str,
    *,
    department: Optional[str] = None,
    role: Optional[str] = None,
) -> bool:
    """
    Return True if the user may view this dashboard.
    Requires access to the linked file (or dashboard is owner).
    """
    row = get_dashboard(dashboard_id)
    if not row:
        return False
    if row.get("owner_user_id") == user_id:
        return True
    linked_file_id = row.get("linked_file_id")
    if not linked_file_id:
        return False
    access = resolve_item_access("file", linked_file_id, user_id, department or "")
    return bool(access.get("allowed"))


def apply_governance_to_query(
    query: Dict[str, Any],
    user_id: str,
    dashboard_row: Dict[str, Any],
    *,
    department: Optional[str] = None,
    restricted_columns: Optional[List[str]] = None,
    row_filter: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Return a copy of the query with governance applied:
    - restricted_columns removed from dimensions/measures
    - row_filter (e.g. department = X) injected into filters
    """
    restricted_columns = restricted_columns or []
    out = dict(query)
    dims = list(out.get("dimensions") or [])
    out["dimensions"] = [d for d in dims if d not in restricted_columns]
    meas = list(out.get("measures") or [])
    out["measures"] = [m for m in meas if (m.get("field") or m) not in restricted_columns]
    filters = list(out.get("filters") or [])
    if row_filter:
        filters.append(row_filter)
    out["filters"] = filters
    return out


def can_export_dashboard(
    user_id: str,
    dashboard_row: Dict[str, Any],
    *,
    department: Optional[str] = None,
) -> bool:
    """Return True if the user may export this dashboard (allow_export and file access)."""
    if not dashboard_row.get("allow_export"):
        return False
    if dashboard_row.get("owner_user_id") == user_id:
        return True
    linked_file_id = dashboard_row.get("linked_file_id")
    if not linked_file_id:
        return False
    access = resolve_item_access("file", linked_file_id, user_id, department or "")
    return bool(access.get("allowed"))
