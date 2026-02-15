# Architectural Navigation Fix – Infinite Reload Loop Elimination

## Versioning Lifecycle Fix (Phase 2)

### Root Cause: Phantom Versions
- Callback created a new version on every save, even when content was unchanged.
- `ensure_periodic_versions` created daily/weekly versions regardless of content change.
- `version_no` incremented without hash comparison → `document.key` changed → OnlyOffice fired `onOutdatedVersion` → infinite loop.

### Fixes Applied

1. **create_version** (`modules/files.py`): Added `skip_if_unchanged=True` parameter. When set, computes hash of source file and compares with latest version; if same, returns existing `version_no` without creating a new row.

2. **Callback** (`app.py`): Before creating version or updating metadata:
   - Compute hash of new content (temp_path) and hash of current main file.
   - If hashes match → skip create_version, skip updated_at, skip index_item, skip ensure_periodic_versions, skip BI sync, skip Excel Links sync. Only remove temp file and return `{"error": 0}`.
   - If different → proceed with full save flow.

3. **ensure_periodic_versions** (`modules/files.py`): Calls `create_version(..., skip_if_unchanged=True)` for daily/weekly snapshots. No phantom daily/weekly versions when content unchanged.

### Hard Requirements Met
- `document.key` depends ONLY on `file_id` + `version_no`.
- `version_no` increments ONLY if content hash changed.
- `updated_at` does NOT affect `document.key`.
- Callback compares hash before creating version and updating metadata.
- No metadata updates when content unchanged (including after logout, when callback may fire without session).

---

## Summary

This document describes the architectural fixes applied to eliminate:
- Infinite Reload Loop
- Redirect Loop
- Callback-triggered Navigation Loop

## Root Cause

1. **document.key** previously depended on `updated_at`, which changed during schema/metadata operations.
2. **onOutdatedVersion / onRequestRefreshFile** handlers used `window.location.reload()`, causing full page reload.
3. Reload → same logic → key/version mismatch → OnlyOffice fires again → reload → infinite loop.
4. Schema auto-update in link-info caused metadata churn during editor usage.

## Hard Requirements Met

| Requirement | Implementation |
|-------------|----------------|
| document.key depends only on version_no | `doc_key = f"{file_id}_v{version_no}"` (no updated_at) |
| No reload inside onOutdatedVersion | Use `docEditor.refreshFile(config)` instead of `window.location.reload()` |
| No metadata update during editor load | open_editor does NOT call update_schema_from_master, update_last_opened, or any schema update |
| No redirect unless strictly deterministic | All redirects are conditional on login/session/access; no unstable redirects |
| Callback must not trigger navigation | OnlyOffice callback returns JSON only; no redirects |
| Dashboard must not auto-redirect to editor | Dashboard only links to editor on user click |
| Editor must not auto-redirect to dashboard unless session invalid | Only redirect to login when session invalid; login then goes to dashboard |

## Changes Applied

### 1. document.key Stabilization (`app.py`)

- Key format: `{file_id}_v{version_no}`
- Key changes only when: actual file content changes (save, restore, sync), i.e. when `version_no` changes.
- Schema metadata changes do NOT affect key.

### 2. Editor Config Helper and API (`app.py`)

- Added `_build_editor_config_for_file(file_id, f, access, session)` – centralizes config building.
- Added `GET /api/files/<file_id>/editor-config` – returns fresh editor config JSON for `refreshFile()`.
- `open_editor` uses the same helper; no duplication.

### 3. No Reload in Version-Change Handlers (`sheet_editor.html`)

- `onOutdatedVersion` and `onRequestRefreshFile` call `doRefreshFile()`.
- `doRefreshFile()` fetches `/api/files/{file_id}/editor-config` and calls `docEditor.refreshFile(config)`.
- No `window.location.reload()` – avoids infinite loop.
- If fetch fails, handler does nothing (suppress to avoid loop).

### 4. No Schema Update During Link-Info Load (`app.py`)

- Removed auto-call to `update_schema_from_master()` from `/api/files/<file_id>/link-info`.
- Schema updates only on explicit actions: Set Master, Push Schema, Create Link.

### 5. Callback Cleanup (`app.py`)

- Removed duplicate `enqueue_refresh_for_file()` call in OnlyOffice callback.
- Callback updates `files.updated_at` only on actual save – does not affect `document.key`.

### 6. No Metadata Update During Editor Load

- `open_editor` does NOT call: `update_schema_from_master`, `update_last_opened`, or any schema/Excel Links update.
- Editor load path is read-only for metadata.

## Preserved Behavior

- SSOT, Excel Links, immutable rows, schema hash enforcement, versioning, audit logging – unchanged.
- OnlyOffice callback flow – unchanged (still saves, creates versions, updates `updated_at`).
- Redirects: login → dashboard, rollback → editor, create file → dashboard (or referrer).

## Verification

1. Open editor for a file – no reload loop.
2. Perform Excel Links actions (Push Schema, Create Link) – no editor reload.
3. Restore version – OnlyOffice may fire `onRequestRefreshFile`; handler uses `refreshFile()` once.
4. Callback saves file – no navigation, no redirect.
