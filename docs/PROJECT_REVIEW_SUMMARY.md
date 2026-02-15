# SE_SHEETSAI — Full Project & System Review (English Summary)

**Review date:** February 2026  
**Scope:** Complete review of `C:\py\se_sheetsai` — all files and folders.  
**Goal:** Verify the system delivers all Google Drive–like capabilities (and better, enterprise-suited) and summarize the platform.

---

## 1. Executive Summary

**SE_SHEETSAI** is an **Enterprise Intelligent Drive Platform** implemented as a single Flask application (~3,500 lines in `app.py` plus ~20 backend modules). It is designed to be **policy-driven, audit-grade, and data-aware**, going beyond Google Drive with:

- **Drive layer:** Folders, files, sharing, trash, versioning, search, in-browser editing (OnlyOffice).
- **Governance:** Department policies, cell/row/column/range permissions, share expiry, automation rules, audit log.
- **BI layer:** Native BI engine (SQLite/Postgres), dashboards from Excel, BI Studio, viewer, export, templates, resync.
- **Excel Links:** Master/child aggregation with schema, sync, and row locking.
- **Security:** Zero-download options, watermarking, JWT-secured OnlyOffice callback, server-side enforcement.

The codebase is **additive and backward-compatible**; existing endpoints and storage semantics are preserved. Gaps remain mainly in deployment (Metabase DB path), some UX (toasts, loading states), and optional hardening (health endpoint, 401/500 pages).

---

## 2. Project Structure (High Level)

| Layer | Location | Purpose |
|-------|----------|---------|
| **Entry** | `app.py`, `config.py` | Flask app, routes, config from `.env` |
| **Data** | `modules/db.py` | SQLite schema, migrations, `get_db()`, `init_db()` |
| **Auth** | `modules/auth.py` | Excel-backed auth: `authenticate()`, `get_user_from_excel()` |
| **Permissions** | `modules/permissions.py` | Roles, sharing, expiry, folder inheritance, cell permissions, department policies |
| **Files & storage** | `modules/files.py` | Folders, files, versions, archive, search index, automation, classification |
| **Editor** | `modules/onlyoffice.py` | OnlyOffice config: watermark, permissions injection |
| **Audit** | `modules/audit.py` | `log_event()`, share access/denied/expired |
| **BI** | `modules/bi_*.py` | Engine, models, queries, cache, security, pivot, export, sync, validation, from_excel |
| **Excel Links** | `modules/excel_links.py` | Master/child links, schema, sync, row locks |
| **Dashboards (legacy)** | `modules/dashboards.py`, `dashboard_engine.py` | Alerts, refresh, runtime builder |
| **Templates** | `templates/*.html` | Dashboard, folder view, shared, trash, editor, preview, BI, errors |
| **Static** | `static/` | CSS, BI viewer/studio JS, themes |
| **Docs** | `docs/*.md` | Spec, architecture, security, implementation status, deployment, troubleshooting |
| **Scripts** | `scripts/` | `run.ps1`, `run.cmd`, `run-bootstrap.cmd`, `bi_smoke_test.py` |

Storage directories (from `config.py`): `sheets/`, `uploads/`, `versions/`, `archive/`, `logs/`. Data source for users: `data/database.xlsx` (synced into DB via `sync_excel_users.py`).

---

## 3. Google Drive–Like Features: Coverage and Implementation

### 3.1 Core Drive Features

| Feature | Status | Implementation |
|---------|--------|----------------|
| **My Drive / root** | ✅ | `/dashboard` — root folders and files for owner |
| **Folders (nested)** | ✅ | `folders` table, `parent_id`, `get_child_folders()`, `/folder/<id>` |
| **Create folder** | ✅ | `POST /folder/create` |
| **Create file (doc/sheet/slide)** | ✅ | `POST /file/create_onlyoffice` — xlsx/docx/pptx from templates |
| **Upload file** | ✅ | `POST /upload` → `uploads/`, stored in `files` |
| **Rename** | ✅ | `POST /rename/<item_type>/<item_id>` — file rename also renames on disk |
| **Move** | ✅ | `POST /move/<item_type>/<item_id>` — prevents moving folder into itself/descendants |
| **Trash** | ✅ | `POST /trash/...`, `/trash` view, `get_trashed_items()` |
| **Restore from trash** | ✅ | `POST /restore/<item_type>/<item_id>` (owner only) |
| **Shared with me** | ✅ | `/shared` — items shared to user/department/role/public with expiry and access resolution |
| **Sharing** | ✅ | `POST /share` — user/department/role/public, role (viewer/editor/owner), optional `expires_at` |
| **In-browser editing** | ✅ | `/editor/<file_id>` — OnlyOffice embed; JWT config from `/api/files/<file_id>/editor-config` |
| **Preview** | ✅ | `/preview/<file_id>`, `/preview/raw/<file_id>` (with access checks) |
| **Download** | ✅ | `/file/raw/<file_id>`, `/uploads/<file_id>`, `/files/<sheet_id>.xlsx` — gated by `ALLOW_DOWNLOAD` and policy |

### 3.2 Versioning and History

| Feature | Status | Implementation |
|---------|--------|----------------|
| **Version history** | ✅ | `file_versions` table; `create_version()` on OnlyOffice callback |
| **List versions** | ✅ | `/versions/<file_id>` |
| **Rollback** | ✅ | `POST /versions/<file_id>/rollback` — `rollback_to_version()` |
| **Compare versions** | ✅ | `/versions/<file_id>/compare` |
| **Version types** | ✅ | autosave, daily, weekly, manual (schema + logic) |

### 3.3 Search

| Feature | Status | Implementation |
|---------|--------|----------------|
| **Full-text search** | ✅ | FTS5 `search_index`; `index_file_search()` after save; `search()` in files; `/api/search` |
| **Content indexing** | ✅ | Excel (pandas) and DOCX (XML) text extraction, `extract_text_for_index` / `index_item` |

### 3.4 Permissions and Security (Beyond Drive)

| Feature | Status | Implementation |
|---------|--------|----------------|
| **Owner / Editor / Viewer** | ✅ | `get_user_role()`, `resolve_item_access()`, `ROLE_ORDER` |
| **Share by user/department/public** | ✅ | `permissions` table: `target_type`, `target_value`, `role`, `expires_at` |
| **Share expiry** | ✅ | `expires_at`; `is_share_expired()`, `find_expired_share_access()`; audit on expired access |
| **Folder inheritance** | ✅ | `resolve_item_access()` walks parent folders for inherited permissions |
| **Cell/row/column/range permissions** | ✅ | `cell_permissions` table; `get_cell_permissions()`, `is_cell_edit_allowed()`; enforced in OnlyOffice callback via `build_excel_diff()` |
| **Department policies** | ✅ | `department_policies` (download/print/copy, share rules); `filter_onlyoffice_permissions()` |
| **Governance policies (BI)** | ✅ | `governance_policies` (allow_view, allow_export, allow_print, allow_copy, allow_refresh) per department |
| **Watermark** | ✅ | `onlyoffice.apply_watermark()` — user, file name, timestamp |
| **Block download** | ✅ | `ALLOW_DOWNLOAD`, `ALLOW_DOWNLOAD_DEFAULT`; raw download routes check and log blocks |

---

## 4. Enterprise-Only Features (Beyond Google Drive)

| Feature | Status | Implementation |
|---------|--------|----------------|
| **Audit log** | ✅ | `audit_log` table; `log_event()` (actor, role, IP, user_agent, item_type, item_id, context_json); used on create/edit/share/access/deny/expired |
| **Automation rules** | ✅ | `automation_rules` (trigger, conditions_json, actions_json); `evaluate_automation_rules()` on file_created/sheet_modified/file_updated |
| **File classification** | ✅ | `file_classifications`; rule-based (e.g. invoice, sales); saved on callback |
| **Ownership transfer** | ✅ | `ownership_transfers` table; `POST /transfer/<item_type>/<item_id>` with reason and optional children |
| **Archiving** | ✅ | `mark_archived()`, `restore_from_archive()`; `ARCHIVE_DAYS`/`COMPRESS_DAYS`; `run_archiving()` at startup; `/archive/restore/<file_id>` |
| **Excel Links (master/child)** | ✅ | `file_links`, `excel_link_schema`, `excel_link_sync_log`, `synced_row_locks`; API: list/link/push-schema/sync/delete; schema detection, append/upsert, row UUID, locking |
| **Native BI engine** | ✅ | `bi_engine.py` — ingest Excel to SQLite/Postgres; `bi_queries`, `bi_pivot`, `bi_models`, `bi_dashboards`, `bi_security`, `bi_cache`, `bi_export`, `bi_sync_trigger`, `bi_validation` |
| **BI: create from Excel** | ✅ | `bi_from_excel`; `POST /bi/create-from-file/<file_id>`; dataset + dashboard creation |
| **BI: Studio** | ✅ | `/bi/studio/new`, `/bi/studio/dashboard/<id>`, save, widgets, filters, themes |
| **BI: Viewer** | ✅ | `/bi/dashboard/<id>`, `/bi/dashboard/<id>/view` |
| **BI: Export** | ✅ | `/bi/export/<id>`, `/bi/export/<id>/png` |
| **BI: Versions & rollback** | ✅ | `bi_dashboard_versions`; list/rollback endpoints |
| **BI: Templates** | ✅ | `bi_dashboard_templates`; save as template endpoint |
| **BI: Resync** | ✅ | `POST /bi/resync/<id>`, `POST /bi/sync/<dataset_id>` |
| **BI access control** | ✅ | `can_access_bi()`, `can_create_edit_bi()`, `check_dashboard_view_permission()`, `get_bi_policy(department)` |
| **Admin: Rules** | ✅ | `/admin/rules` — automation rules (governance role) |
| **Admin: Audit** | ✅ | `/admin/audit` — audit log (governance role) |
| **AI endpoint** | ✅ | `POST /api/ai/ask` — stub for future AI reasoning |

---

## 5. Database Schema (Summary)

- **Identity & access:** `users` (synced from Excel), `permissions` (with `expires_at`), `cell_permissions`, `department_policies`, `governance_policies`, `access_violations`.
- **Drive:** `folders`, `files` (with `last_opened_at`, `archived_at`, `compressed_at`, `updated_at`), `file_versions`, `ownership_transfers`.
- **Intelligence:** `file_classifications`, `automation_rules`, `audit_log`, `search_index` (FTS5).
- **Legacy dashboards:** `dashboards`, `dashboard_kpis`, `dashboard_versions`, `datasets`.
- **BI (native):** `bi_dashboards`, `bi_permissions`, `bi_datasets`, `bi_sync_logs`, `bi_widgets`, `bi_dashboard_filters`, `bi_dashboard_templates`, `bi_dashboard_versions`, `bi_sales_demo`.
- **Excel Links:** `file_links`, `excel_link_schema`, `excel_link_sync_log`, `synced_row_locks`.

All sensitive operations go through `require_login()` and permission helpers; no route exposes data without access resolution.

---

## 6. Configuration (.env / config.py)

- **Flask:** `SECRET_KEY`, `BASE_URL`.
- **Database:** `DB_PATH`, `DB_FALLBACK_PATH`.
- **OnlyOffice:** `ONLYOFFICE_SERVER`, `ONLYOFFICE_JWT_SECRET`, `BASE_URL`.
- **Paths:** `SHEETS_DIR`, `UPLOADS_DIR`, `VERSIONS_DIR`, `ARCHIVE_DIR`, `LOGS_DIR`.
- **Versioning:** `ARCHIVE_DAYS`, `COMPRESS_DAYS`.
- **Governance:** `WATERMARK_ENABLED`, `ALLOW_DOWNLOAD`, `ALLOW_DOWNLOAD_DEFAULT`, `ALLOW_PRINT_DEFAULT`, `ALLOW_COPY_DEFAULT`, `DEFAULT_VERSION_POLICY` (xlsx/docx/pptx).
- **BI:** `BI_RUNTIME_ENGINE` (sqlite/postgres), `BI_RUNTIME_DB_PATH`, `BI_POSTGRES_*`, `BI_CACHE_TTL`, `BI_ALLOWED_ROLES`.
- **Search:** `SEARCH_MAX_CHARS`.

---

## 7. Gaps and Implementation Status (from docs)

- **Phase 1.3 (Metabase DB path):** Optional Metabase integration can hit path mismatch (Windows vs Docker); recommendation: use PostgreSQL for BI runtime (already in `docker-compose.yml`).
- **Phase 2 (Hard permission model):** Largely done (expiry, folder inheritance, cell permissions, governance); any remaining hardening is incremental.
- **Phase 3 (OnlyOffice):** Versioning on save and rollback exist; version diff UI and production hardening (e.g. health checks) can be extended.
- **Phase 4 (Metabase/BI):** Native BI (create from Excel, Studio, viewer) is in place; Metabase embed optional.
- **Phase 5 (UX):** 403/404 exist; 401/500 and consistent toasts/loading states noted as improvements.
- **Phase 6–8:** Employee list from Excel, deployment standardization, health endpoint and monitoring are optional next steps.

---

## 8. Alignment with spec.md

The project aligns with the stated philosophy:

- **Policy-centric:** Department and governance policies and automation rules drive behavior.
- **Data-aware:** File classification, search index, BI ingestion, and Excel Links use content and structure.
- **Event-driven:** Callback triggers versioning, indexing, classification, automation, and BI resync.
- **Audit-grade:** `audit_log` with actor, role, IP, user_agent, item, context.
- **Zero-download security:** Configurable no-download, watermark, and server-side enforcement.
- **Ownership & governance:** Ownership transfer with audit; no silent takeovers.
- **Archiving:** Active → cold → compressed with restore and audit.
- **BI/AI layer:** Native BI and `/api/ai/ask` stub for future reasoning.

Comparison table in spec (cell-level permissions, legal audit trail, policy enforcement, automation, version intelligence, BI, ownership governance) is reflected in the codebase.

---

## 9. Conclusion and Recommendations

- **Summary:** SE_SHEETSAI implements a full Google Drive–like experience (folders, files, sharing, trash, versions, search, in-browser editing, preview, download) and extends it with enterprise features: cell-level and department-level permissions, share expiry, folder inheritance, audit log, automation rules, file classification, ownership transfer, archiving, Excel Links (master/child), and a native BI stack (create from Excel, Studio, viewer, export, versions, templates, resync). The design is additive and respects the immutable endpoints and storage semantics.

- **Recommendations:**
  1. Add a `/health` endpoint and optional structured health checks for BI and DB.
  2. Add 401 and 500 error pages for consistency with 403/404.
  3. Standardize toast notifications and loading states for long operations.
  4. If using Metabase, resolve DB path (e.g. use Postgres for BI runtime as in `docker-compose.yml`).
  5. Keep `.env` and secrets out of version control; document production checklist (as in `SECURITY_MODEL.md`).

This document serves as the **full project and system review summary in English** for the path `C:\py\se_sheetsai`.
