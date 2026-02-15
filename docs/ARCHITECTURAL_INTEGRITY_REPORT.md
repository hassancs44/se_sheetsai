# Sevens Drive — Architectural Integrity Report

**Date:** 2026-02-14  
**Scope:** File Card features, versioning, Excel linking, permissions, audit, storage  
**Repository:** `C:\py\se_sheetsai`

---

## Phase 1 — Repository Deep Analysis

### 1.1 File Routes Map

| Route | Method | Handler | Purpose |
|-------|--------|---------|---------|
| `/folder/<folder_id>` | GET | open_folder | List files/folders in folder |
| `/file/create` | POST | create_file_route | Create blank file |
| `/file/create_onlyoffice` | POST | create_onlyoffice | Create xlsx/docx/pptx from template |
| `/create_sheet` | POST | create_sheet | Create sheet (legacy) |
| `/restore/<item_type>/<item_id>` | POST | restore_item | Restore from trash |
| `/rename/<item_type>/<item_id>` | POST | rename | Rename file/folder |
| `/move/<item_type>/<item_id>` | POST | move | Move file/folder |
| `/trash` | GET | trash_view | Trash view |
| `/trash/<item_type>/<item_id>` | POST | trash_item | Move to trash |
| `/upload` | POST | upload | Upload file |
| `/share` | POST | share_item | Share file/folder |
| `/permissions/cell` | POST | set_cell_permissions | Cell-level permissions |
| `/editor/<file_id>` | GET | open_editor | Open OnlyOffice editor |
| `/onlyoffice/callback` | POST | onlyoffice_callback | OnlyOffice save callback |
| `/file/raw/<file_id>` | GET | serve_onlyoffice_file | Raw file download |
| `/versions/<file_id>` | GET | list_versions | List file versions |
| `/versions/<file_id>/restore/<version_id>` | POST | restore_version | Restore to version |
| `/versions/<file_id>/compare` | GET | compare_versions | Compare versions |
| `/transfer/<item_type>/<item_id>` | POST | transfer | Transfer ownership |
| `/api/files/<master_id>/links` | GET/POST | api_files_links_* | Excel links CRUD |
| `/api/files/<master_id>/links/<child_id>/sync` | POST | api_files_links_sync | Manual sync |
| `/api/files/<file_id>/link-info` | GET | api_files_link_info | Link info for modal |
| `/api/files/<file_id>/sheets` | GET | api_files_sheets | List sheet names |
| `/api/files/excel-picker` | GET | api_files_excel_picker | Excel files for dropdowns |

### 1.2 Real Flow Map Per File Card Button

#### Rename
```
Frontend (dashboard.html) → POST /rename/file/<file_id> → rename() → get_allowed_actions() 
→ rename_item() [files.py] → UPDATE files SET name=? → log_audit()
```
- **Version:** ❌ No
- **Audit:** ✅ Yes (log_audit)
- **Path change:** No (only name in DB)

#### Move
```
Frontend → POST /move/file/<file_id> → move() → get_user_role() 
→ move_item() [files.py] → UPDATE files SET folder_id=? → log_audit() → evaluate_automation_rules()
```
- **Version:** ❌ No (correct)
- **Audit:** ✅ Yes
- **Path change:** No (physical path unchanged; files.path is absolute)

#### Delete (Trash)
```
Frontend → POST /trash/file/<file_id> → trash_item() → get_allowed_actions() 
→ move_to_trash() [files.py] → UPDATE files SET is_trashed=1 → log_audit()
```
- **Version:** ❌ No (correct)
- **Audit:** ✅ Yes

#### Restore from Trash
```
Frontend → POST /restore/file/<file_id> → restore_item() 
→ restore_from_trash() → UPDATE files SET is_trashed=0 → log_audit()
```
- **Version:** ❌ No (correct)

#### Share
```
Frontend → POST /share → share_item() → INSERT permissions 
→ log_event() + log_audit()
```
- **Version:** ❌ No (correct)

#### Versions (List)
```
Frontend → GET /versions/<file_id> → list_versions() [files.py] 
→ SELECT * FROM file_versions WHERE file_id=?
```

#### Version Restore
```
Frontend → POST /versions/<file_id>/restore/<version_id> → restore_version() 
→ create_version(..., "pre_restore") → shutil.copyfile(version → live) → log_audit()
```
- **Version:** ✅ Pre-restore snapshot created
- **Audit:** ✅ Yes
- **History:** Preserved (no version deletion)

#### Excel Links (Add Child, Sync, Unlink)
```
Add: POST /api/files/<master_id>/links → create_link() [excel_links.py]
     → INSERT file_links, excel_link_schema

Sync: POST /api/files/<master_id>/links/<child_id>/sync → sync_child_to_master()
     → Load child → Load master → Upsert rows → wb_master.save(master_path)
     → if rows_inserted>0 OR rows_updated>0: create_version(..., version_type="child_sync")
     → _log_sync(..., version_no) → INSERT excel_link_sync_log

Unlink: DELETE /api/files/<master_id>/links/<child_id> → unlink()
       → UPDATE file_links SET link_status='paused'
```

#### OnlyOffice Callback (Save)
```
OnlyOffice → POST /onlyoffice/callback (status=2)
→ Download file from URL → Cell permission check → create_version(autosave) 
→ Write to row["path"] → ensure_periodic_versions() 
→ UPDATE files SET updated_at=? 
→ index_file_search / classify / evaluate_automation_rules / trigger_bi_resync
→ if sheet + is_child_linked: sync_child_to_master()
→ log_audit("file_updated")
```

### 1.3 OnlyOffice Integration

- **Editor:** `/editor/<file_id>` → JWT config → OnlyOffice Document Server
- **Callback:** JWT-verified; status=2 = save
- **Flow:** Download → Temp → Diff (cell rules) → Version → Persist → Index → BI → Excel sync

### 1.4 Storage Layout

- `files.path` = absolute path (e.g. `{SHEETS_DIR}/{file_id}_{name}.xlsx`)
- **Move** updates `folder_id` only; physical path unchanged
- Excel links use `get_master_path` / `get_child_path` → `files.path` (stable on move)

---

## Phase 2 — Versioning Integrity Audit

### 2.1 Version Creation Triggers

| Trigger | Creates Version? | Correct? |
|---------|------------------|----------|
| OnlyOffice callback (status=2, content save) | ✅ Yes (autosave) | ✅ |
| Version restore (pre-restore snapshot) | ✅ Yes (pre_rollback) | ✅ |
| ensure_periodic_versions (daily/weekly) | ✅ Yes (daily/weekly) | ✅ |
| Rename | ❌ No | ✅ |
| Move | ❌ No | ✅ |
| Share | ❌ No | ✅ |
| Trash | ❌ No | ✅ |
| Restore from trash | ❌ No | ✅ |
| **Child sync → Master** | ✅ Yes (child_sync, when rows_inserted>0 OR rows_updated>0) | ✅ **FIXED** |

### 2.2 Version Data Integrity

| Field | Present in file_versions? | Populated by create_version? |
|-------|---------------------------|------------------------------|
| version_no | ✅ | ✅ (MAX+1) |
| version_type | ✅ | ✅ (autosave|daily|weekly|pre_rollback) |
| stored_path | ✅ | ✅ |
| hash | ✅ | ✅ (SHA-256) |
| size_bytes | ✅ | ✅ |
| created_at | ✅ | ✅ |
| created_by | ✅ | ✅ |
| notes | ✅ | ✅ (optional) |

**Note:** `modules/files.py` contains two `create_version` definitions (lines ~540 and ~856). The second one (with version_type, hash, etc.) is the one in use.

### 2.3 Restore Behavior

- **Pre-restore snapshot:** ✅ Created via `create_version(..., "pre_restore")`
- **Replace content:** ✅ `shutil.copyfile(version_path, live_path)`
- **History:** ✅ No version rows deleted
- **Audit:** ✅ `log_audit("restore_version", ...)`

---

## Phase 3 — Cross-Feature Conflict Testing

### 3.1 Delete + Version

- **Conflict:** None. Trash only sets `is_trashed=1`; versions remain. Restore from trash does not touch versions.

### 3.2 Move + Excel Links

- **Conflict:** None. `file_links` and `excel_link_schema` reference `file_id` only. Physical paths from `files.path` do not change on move (only `folder_id`).

### 3.3 Share + Version

- **Conflict:** None. Sharing inserts `permissions`; versioning is independent.

### 3.4 Child Sync + Master Version

- **Conflict:** ✅ **RESOLVED**
  - `sync_child_to_master()` (modules/excel_links.py:159) now calls `create_version()` after successful master write when `rows_inserted>0` or `rows_updated>0`.
  - Version type: `child_sync`; created_by: child_owner or "system"; notes: "Child {id}: +{inserted} -{updated}".
  - `version_no` stored in `excel_link_sync_log`; APIs return `version_created`, `version_no`.

### 3.5 Restore + Audit Log

- **Conflict:** None. Restore creates pre-restore version and logs audit.

### 3.6 Rename + File Path References ✅ RESOLVED

- **Fix:** `rename_item` (modules/files.py) now renames physical file and updates `files.path` when renaming a file.
- Flow: get path → construct new path from new name + extension → os.rename(old, new) → UPDATE files SET name=?, path=?.

---

## Phase 4 — Integrity Matrix

| Action | New Version? | Audit? | Permission Safe? | Lock Safe? |
|--------|--------------|--------|------------------|------------|
| Rename | ❌ | ✅ log_audit | ✅ get_allowed_actions | N/A |
| Move | ❌ | ✅ log_audit | ✅ get_user_role(editor+) | N/A |
| Trash | ❌ | ✅ log_audit | ✅ get_allowed_actions(delete) | N/A |
| Restore from trash | ❌ | ✅ log_audit | ✅ get_allowed_actions(delete) | N/A |
| Share | ❌ | ✅ log_event+log_audit | ✅ owner only | N/A |
| Cell permissions | ❌ | ✅ (on violation) | ✅ cell rules | N/A |
| OnlyOffice save | ✅ autosave | ✅ log_audit | ✅ cell rules checked | N/A |
| Version restore | ✅ pre_restore | ✅ log_audit | ✅ editor/owner | N/A |
| Child sync (callback) | ❌ | ✅ excel_link_sync_log | ✅ link validation | ✅ master lock |
| Child sync (manual) | ❌ | ✅ excel_link_sync_log | ✅ resolve_item_access | ✅ master lock |
| **Master write (via sync)** | ✅ child_sync | excel_link_sync_log + version_no | N/A | ✅ | ✅ **Fixed** |
| Add child link | ❌ | ❌ | ✅ resolve_item_access | N/A |
| Unlink child | ❌ | ❌ | ✅ resolve_item_access | N/A |
| Upload | ❌ | ✅ log_audit | ✅ folder access | N/A |
| Transfer ownership | ❌ | ✅ log_audit | ✅ owner only | N/A |

---

## Phase 5 — Unified Service Layer

### 5.1 Current State

| Concern | Centralized? | Location |
|---------|--------------|----------|
| File operations (rename, move, trash, restore) | ✅ | `modules/files.py` |
| Version creation | ✅ | `modules/files.py` create_version, ensure_periodic_versions |
| Excel sync | ✅ | `modules/excel_links.py` sync_child_to_master |
| Audit | Partial | `modules/audit.py` log_event + `modules/files.py` log_audit |
| Permissions | ✅ | `modules/permissions.py` resolve_item_access, get_allowed_actions |

### 5.2 FileService Introduced ✅

- **modules/file_service.py** — `rename`, `move`, `trash`, `restore` with permission check + audit.
- Routes `/rename`, `/move`, `/trash/<item_type>/<item_id>`, `/restore` now call FileService.
- Direct DB writes remain for: `share_item`, `onlyoffice_callback`, dashboards, BI.

**Many routes still write directly to DB:**

- `onlyoffice_callback`: `db.execute("UPDATE files SET updated_at=?")`
- `share_item`: `db.execute("INSERT INTO permissions ...")`
- `restore_version`: uses `get_db()`, `create_version`, `shutil.copyfile`
- Dashboards, BI, governance: heavy direct `db.execute` in routes

**Recommendation:** Introduce a unified `FileService` and `VersionService`; routes should call these instead of `db.execute` for file/version operations.

### 5.3 Duplicate App Blocks ✅ RESOLVED

- **Fix:** Removed second `app = Flask(__name__)` (was ~line 3190). Second block now uses first app.
- All routes register on single app instance.

---

## Phase 6 — Future-Proofing

### 6.1 Transaction Safety

- **Current:** No explicit transactions spanning file + DB operations.
- **Risk:** Partial failure (e.g. file written, DB rollback) can leave inconsistent state.
- **Recommendation:** Wrap file write + DB update in a transaction where possible; use compensating actions or saga pattern for cross-resource operations.

### 6.2 Rollback on Partial Failure

- **sync_child_to_master:** On exception, logs error but does not rollback master file. Child may have been modified (`_ensure_system_columns` + save).
- **Recommendation:** Consider writing master to temp file, then atomic rename on success.

### 6.3 Master-Level Locking ✅

- In-process: `_get_master_lock(master_file_id)` — per-master `threading.Lock`.
- Multi-worker: `_acquire_file_lock`, `_release_file_lock` — file-based lock via fcntl (Unix) / msvcrt (Windows) in excel_links.py. Lock file: `{VERSIONS_DIR}/.sync_lock_{master_file_id}`.

### 6.4 Infinite Sync Loops

- **Risk:** Child save → sync to master → if master save triggered callback → could recurse.
- **Current:** OnlyOffice callback is invoked for the **child** file only. Master is written by `sync_child_to_master` directly; OnlyOffice is not opened for master in that flow. So no callback loop.
- **Conclusion:** ✅ No infinite sync loop.

### 6.5 Race Conditions

- **Concurrent child syncs:** ✅ Mitigated by `_get_master_lock(master_file_id)`.
- **Concurrent version restore + save:** No lock. Possible race if user restores while another saves.
- **Recommendation:** Consider file-level lock during version restore.

### 6.6 Silent Failures

- **Audit:** `log_event` catches exceptions and returns False without raising — acceptable for audit.
- **Excel sync:** Exceptions are logged; callback returns `{"error": 0}` even on sync failure (sync is in try/except). User is not explicitly notified of sync failure in callback flow.
- **Recommendation:** Surface sync failures (e.g. toast) when triggered manually; for callback, consider async notification or status endpoint.

---

## Conflict Report Summary

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 1 | ~~High~~ **FIXED** | Master version created on successful child sync | `excel_links.sync_child_to_master` → `create_version` |
| 2 | ~~Medium~~ **FIXED** | Consolidated to single Flask app | app.py |
| 3 | ~~Medium~~ **FIXED** | FileService for rename/move/trash/restore | modules/file_service.py |
| 4 | ~~Low~~ **FIXED** | Rename now updates path + physical file | files.rename_item |
| 5 | ~~Low~~ **FIXED** | File-based cross-process lock for master sync | excel_links._acquire_file_lock |
| 6 | Low | Sync failure in callback not surfaced to user | onlyoffice_callback |

---

## Refactoring Plan

### Priority 1 — Master Version on Sync ✅ IMPLEMENTED

1. In `sync_child_to_master()` (modules/excel_links.py): after successful `wb_master.save(master_path)`, when `rows_inserted>0` or `rows_updated>0`:
   - Call `create_version(master_file_id, master_path, child_owner or "system", "child_sync", VERSIONS_DIR, version_type="child_sync", notes="Child {id}: +{i} -{u}")`.
2. `_log_sync()` updated to accept `version_no`; `excel_link_sync_log.version_no` via `safe_add_column`.
3. `list_links()` returns `last_version_no` per child.
4. API sync returns `version_created`, `version_no`; frontend shows "تم إنشاء نسخة للملف الرئيسي".

### Priority 2 — Consolidate App Blocks ✅ IMPLEMENTED

- Removed second `app = Flask(__name__)`; second block uses first app.

### Priority 3 — Introduce FileService ✅ IMPLEMENTED

- Created `modules/file_service.py`: `rename`, `move`, `trash`, `restore`.
- Routes `/rename`, `/move`, `/trash/<item_type>/<item_id>`, `/restore` use FileService.

### Priority 4 — Path Consistency on Rename ✅ IMPLEMENTED

- `rename_item` renames physical file and updates `files.path`.

### Priority 5 — Multi-Worker Lock ✅ IMPLEMENTED

- `_acquire_file_lock`, `_release_file_lock` in excel_links.py — file lock via fcntl/msvcrt.

---

## Backward Compatibility

- **Version creation on sync:** New versions will appear for masters. Existing behavior (no version) is extended, not broken.
- **FileService migration:** Internal refactor; API and UI unchanged.
- **App consolidation:** Must preserve all current routes; no URL changes.
- **Path/rename:** If path is updated on rename, ensure all code uses `files.path` from DB, not derived from name.

---

## Zero Regression Checklist

- [ ] Version restore still creates pre-restore snapshot
- [ ] OnlyOffice callback still creates autosave version
- [ ] Child sync still upserts correctly; master lock still held
- [ ] Rename, move, trash, restore, share still audit correctly
- [ ] Permissions still enforced on all file operations
- [ ] Excel links modal still works (add child, sync, unlink)
- [ ] Multi-child concurrent sync does not corrupt master

---

---

## Implementation Notes (Patch Summary)

- **Files changed:** `modules/excel_links.py`, `modules/files.py`, `modules/db.py`, `modules/file_service.py` (new), `app.py`, `templates/dashboard.html`, `docs/ARCHITECTURAL_INTEGRITY_REPORT.md`
- **Key functions updated:** `sync_child_to_master` (create_version, file lock), `_log_sync` (version_no), `list_links` (last_version_no), `rename_item` (path + physical rename), `restore_item`, `rename`, `move`, `trash_item` (FileService)
- **DB migrations:** `safe_add_column("excel_link_sync_log", "version_no INTEGER")`

---

*End of Report*
