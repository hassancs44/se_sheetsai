# SE_SHEETSAI — Project Map & Code-Grounded Architecture Summary

## A) Recursive Project Map (excluding __pycache__, .git, .venv, node_modules, build/cache)

```
se_sheetsai/
├── app.py                    # Core entrypoint (Flask app, 5800+ lines)
├── config.py                 # Core config (paths, OnlyOffice, BI, governance flags)
├── requirements.txt
├── .env / .env.example
├── docker-compose.yml
│
├── modules/
│   ├── auth.py               # Auth: authenticate(), get_user_from_excel() — Excel-backed
│   ├── permissions.py        # Auth/permissions: get_user_role(), resolve_item_access(),
│   │                         #   get_allowed_actions(), get_cell_permissions(),
│   │                         #   filter_onlyoffice_permissions(), department_policies
│   ├── db.py                 # DB init: init_db(), get_db() — SQLite schema + migrations
│   ├── files.py              # File storage: create_onlyoffice_file(), create_version(),
│   │                         #   build_excel_diff(), index_file_search(), mark_archived(),
│   │                         #   extract_text_from_file(), evaluate_automation_rules()
│   ├── onlyoffice.py         # OnlyOffice: inject_permissions(), apply_watermark()
│   ├── audit.py              # Audit: log_event(), log_share_access(), log_share_denied()
│   ├── sync_excel_users.py   # User sync from Excel → DB
│   ├── bi_*.py               # BI engine: bi_data, bi_dashboards, bi_engine, bi_export,
│   │                         #   bi_from_excel, bi_models, bi_pivot, bi_queries,
│   │                         #   bi_cache, bi_security, bi_sync_trigger, bi_validation
│   ├── dashboard_engine.py   # Legacy dashboard runtime
│   └── dashboards.py         # compute_alerts, refresh_dashboard
│
├── templates/                # Jinja2 HTML (folder view, editor, BI, governance)
│   ├── dashboard.html        # Folder/file grid + file cards (rename, move, share,
│   │                         #   versions, cell_permissions, BI dashboard link)
│   ├── layout.html, shared.html, login.html
│   ├── sheet_editor.html, sheet_view.html, preview.html
│   ├── bi_*.html, governance_*.html, data_panel.html
│   ├── errors/403.html, 404.html
│   └── partials/navbar.html
│
├── static/
│   ├── style.css
│   └── bi/                   # BI frontend: viewer.js, studio.js, ui/*.css, themes.json
│
├── docs/
│   ├── ARCHITECTURE.md, spec.md, SECURITY_MODEL.md
│   └── METABASE_*.md, BI_*.md, DEPLOYMENT_*.md
│
├── scripts/
│   ├── run.ps1, run.cmd, run-bootstrap.cmd
│   └── bi_smoke_test.py
│
└── logs/app.log
```

### Key Locations

| Concern | Location |
|---------|----------|
| Auth/permissions | `modules/auth.py`, `modules/permissions.py` |
| File storage | `modules/files.py` — path in `files.path`, SHEETS_DIR, UPLOADS_DIR |
| OnlyOffice editor + callback | `app.py` `/editor/<file_id>`, `/onlyoffice/callback`; `modules/onlyoffice.py` |
| Sharing | `app.py` `/share`; `modules/permissions.py` — `permissions`, `expires_at` |
| Versioning | `modules/files.py` create_version, list_versions, rollback; `file_versions` table |
| Search/indexing | `modules/files.py` index_file_search, extract_text_from_file; `search_index` FTS5 |
| Governance | `config.py` WATERMARK_ENABLED, ALLOW_DOWNLOAD; `department_policies`, `governance_policies` |

---

## B) End-to-End Flow (Code-Grounded)

### File creation (Excel/Word/PPT via OnlyOffice templates)

- Route: `POST /file/create_onlyoffice` (app.py ~3487)
- Flow: `create_onlyoffice_file(owner, folder_id, name, ext)` (files.py ~477)
  - ID: `FILE_{timestamp}`
  - Path: `SHEETS_DIR/{fid}_{name}.{ext}` (config: `sheets/`)
  - Template: `templates/blank.xlsx|docx|pptx` (shutil.copyfile)
  - DB: INSERT into `files` (file_id, name, owner, folder_id, path, mime, file_type)
  - Redirect to `/editor/<file_id>`

### OnlyOffice callback persistence

- Route: `POST /onlyoffice/callback` (app.py ~4108)
- Verify: `verify_onlyoffice_request()` — JWT
- On `status == 2`: fetch `url`, `key` (= file_id)
- Load: `SELECT path, name, owner, file_type FROM files WHERE file_id = ?`
- Download new content from OnlyOffice URL → `{path}.new`
- Cell permissions: `get_cell_permissions()`, `build_excel_diff()`; reject unauthorized edits
- Versioning: `create_version(..., "autosave", VERSIONS_DIR, version_type="autosave")`
- Persist: overwrite `row["path"]` with new content
- Metadata: `UPDATE files SET updated_at=?`
- Search: `index_file_search(file_id, path, owner, department, file_type, ...)`
- Classification: `classify_file()`, `save_classification()`
- Automation: `evaluate_automation_rules("sheet_modified"|"file_updated", ...)`
- BI: `trigger_bi_resync_for_file(file_id)`
- Audit: `log_audit(user_id, "file_updated", "file", file_id, ...)`

### Raw download/view endpoints

- `/file/raw/<file_id>` — serve_onlyoffice_file (app.py ~4057)
  - Uses ALLOW_DOWNLOAD, token/session, `resolve_item_access`
  - `send_file(row["path"], as_attachment=False)`
- `/files/<sheet_id>.xlsx` — serve_excel (app.py ~3996)
- `/uploads/<file_id>` — serve_uploaded_file (app.py ~4023)
- `/preview/<file_id>`, `/preview/raw/<file_id>` — preview (app.py ~2024, 2052)

### Storage paths (config.py)

- `SHEETS_DIR` = `{BASE_DIR}/sheets`
- `UPLOADS_DIR` = `{BASE_DIR}/uploads`
- `VERSIONS_DIR` = `{BASE_DIR}/versions` (env override)
- `ARCHIVE_DIR` = `{BASE_DIR}/archive` (env override)

### SQLite schema (modules/db.py)

- **files**: file_id, name, owner, folder_id, path, mime, file_type, is_trashed, created_at, last_opened_at, archived_at, updated_at
- **file_versions**: file_id, version_no, version_type, stored_path, hash, size_bytes, created_at, created_by, notes
- **permissions**: item_type, item_id, owner, target_type, target_value, role, expires_at
- **cell_permissions**: item_type, item_id, sheet_name, scope_type, scope_value, target_type, target_value, perm
- **department_policies**: department, policy_json (download, print, copy, etc.)
- **audit_log**, **automation_rules**, **file_classifications**, **ownership_transfers**, etc.

### Governance flags (download/print/copy restrictions)

- `config.py`: `ALLOW_DOWNLOAD`, `WATERMARK_ENABLED`, `ALLOW_DOWNLOAD_DEFAULT`, `ALLOW_PRINT_DEFAULT`, `ALLOW_COPY_DEFAULT`
- `permissions.filter_onlyoffice_permissions()` — uses `_get_department_policy(department)` for download/print/copy
- `get_allowed_actions()` — actions.download/print/copy gated by `ALLOW_*_DEFAULT` and `policy.get("download"|"print"|"copy")`

### Permission model (owner/editor/viewer + share expiry)

- `get_user_role(item_type, item_id, user, department)` — checks owner, then permissions (user/department/role/public)
- `ROLE_ORDER`: viewer=1, editor=2, owner=3
- `permissions` table: target_type (user|department|role|public), target_value, role, expires_at
- `is_share_expired()` / `_is_expired()` — share expiry
- `resolve_item_access()` — full access resolution including recursive folder inheritance
- `cell_permissions` — fine-grained cell/row/column/range edit rules

---

## C) Architecture Summary (Code-Grounded)

- **Entry**: `app.py` Flask app; `config.py` DB_PATH, ONLYOFFICE_*, SHEETS_DIR, governance flags.
- **Auth**: Excel-backed `authenticate()`; session holds user, role, department, apps.
- **Drive**: `folders` + `files`; path on disk; `get_files_in_folder`, `create_onlyoffice_file`.
- **Editor**: `/editor/<file_id>` — OnlyOffice embed with JWT; `inject_permissions` for watermark.
- **Callback**: `/onlyoffice/callback` — on save: persist file, version, index, classify, automation, BI resync, audit.
- **Governance**: department_policies (download/print/copy); `filter_onlyoffice_permissions`.
- **Sharing**: permissions table with user/department/role/public + expires_at; `resolve_item_access`.
- **Versions**: file_versions with autosave/daily/weekly; `create_version`, `rollback_to_version`.
- **Search**: FTS5 `search_index`; `index_file_search` after callback.
- **Raw serve**: `/file/raw/<file_id>` — gated by ALLOW_DOWNLOAD + access.
