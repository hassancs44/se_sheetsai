# SE_SHEETSAI — Full System Analysis & Metabase “Box” Integration

## PART 1 — Project Analysis

### Directory layout

- **app.py** — Main Flask app: auth, Drive (dashboard, folder, file), OnlyOffice editor, data-panel, BI routes, governance, API.
- **config.py** — SECRET_KEY, DB paths, OnlyOffice (ONLYOFFICE_SERVER, JWT, BASE_URL), paths (UPLOADS, VERSIONS, ARCHIVE), enterprise flags (WATERMARK, ALLOW_DOWNLOAD, etc.), Metabase (METABASE_*).
- **modules/** — db (init_db, get_db, schema), auth, audit, files, permissions, onlyoffice, metabase, metabase_embed, bi_dashboards, bi_data, dashboards, dashboard_engine, sync_excel_users.
- **templates/** — layout.html (sidebar nav), dashboard.html (Drive + folder view + BI folder_dashboards), sheet_editor.html (OnlyOffice iframe + file_dashboard link), data_panel.html, bi_index.html, bi_dashboard_view.html, bi_admin.html, governance_*, etc.
- **static/** — style.css, assets.
- **Database** — SQLite (database.db / database_runtime fallback). Tables: users, folders, files, permissions, dashboards, dashboard_kpis, dashboard_versions, file_versions, audit_log, cell_permissions, governance_policies, department_policies, bi_dashboards, bi_permissions, bi_datasets, etc.

### OnlyOffice integration (the “box” model)

1. **Route** — `GET /editor/<file_id>`.
2. **Permission** — `resolve_item_access("file", file_id, user, department)`; if not allowed → 403; role determines edit vs view.
3. **File link** — File record from `files`; document URL is `BASE_URL/file/raw/<file_id>?token=<access_token>` (JWT for raw download).
4. **JWT** — `generate_onlyoffice_token(payload)` (document + editorConfig + permissions); OnlyOffice server validates JWT.
5. **Callback** — `POST /onlyoffice/callback` for save/status; verify_onlyoffice_request().
6. **Governance** — `inject_permissions(config, user, file_id, file_name)` applies watermark and download/print/copy from config/department policy.
7. **UI** — `sheet_editor.html` extends layout.html; single iframe loads OnlyOffice; no raw OnlyOffice URL exposed.
8. **Session** — Session holds user, role, department, apps; used for all access checks.

So: **SE_SHEETSAI is a controlled box**. OnlyOffice is a tool inside the box. The box controls access, visibility, governance, auditing, and linking to files/folders.

### Permission flow

- **resolve_item_access(item_type, item_id, user, department)** — Owner check, then permissions table (user/department/public, expires_at), then inherited folder shares. Returns allowed, role, owner, share.
- **can_access_dashboard(user, dashboard_id)** — For `dashboards` table: admin/مدير عام/مدير القسم, owner, permissions table, department match, or access via linked file (get_dashboard_files + resolve_item_access).
- **can_access_bi()** — Session: role in (admin, مدير عام, مدير القسم) or `"bi"` in session["apps"]. Used for data-panel and BI routes.
- **get_bi_policy(department)** — governance_policies (allow_view, allow_export, …); default allow_view=True if table missing.

### Data-panel and 403 (PART 2)

- **Route** — `GET /data-panel/<dashboard_id>` is registered **twice** in app.py. The **second** registration wins (Flask last-decorated): `data_panel_view_dup` (~line 4750).
- **Checks (in order)** — require_login → dashboard_id != "new" (else 404) → **can_access_bi()** → **get_bi_policy(department).allow_view** → load from **dashboards** table → if not found, **check bi_dashboards by internal_id**: if found and **can_user_view_bi_dashboard**, **redirect to /bi/dashboard/<id>** → else 404 → status == 'published' → **can_access_dashboard(user, dashboard_id)** → linked file access (definition sources) → then render (dashboard_runtime or Excel dashboard_view).
- **Root cause of 403** — Previously the active handler used `has_data_panel_access()` (stricter). It was replaced with `can_access_bi()` and get_bi_policy; duplicate block was aligned. Additional fix: when the ID is not in `dashboards`, it is now resolved from **bi_dashboards** and, if the user has permission, redirected to `/bi/dashboard/<id>` so one URL pattern works for both internal and Metabase dashboards.
- **Result** — 403 only when truly unauthorized (no BI access, policy deny, or no dashboard/file permission). 404 when dashboard does not exist in either table. 200 when allowed. Redirect to embedded Metabase when ID is in bi_dashboards and user can view.

---

## PART 3 — Metabase Re-Architecture (Enterprise “Box”)

Metabase is integrated like OnlyOffice: inside the same layout, same auth, same permission and governance model.

### modules/metabase.py (enterprise API)

- **generate_signed_embed_jwt(user, dashboard_id, params, exp_seconds)** — Signed JWT for Metabase embed (same as generate_metabase_embed_jwt with user context).
- **get_embed_url(internal_id, params, user_id, department, role)** — Resolves internal_id → bi_dashboards → metabase_dashboard_id, builds JWT and full iframe URL; returns (url, error). Caller must check permission first.
- **can_user_view_dashboard(user_id, internal_dashboard_id, department, role)** — Alias for can_user_view_bi_dashboard.
- **can_user_view_bi_dashboard(...)** — Owner, bi_permissions (user/role/department, view|edit|admin), or linked file/folder via resolve_item_access.
- **enforce_governance_rules(user_id, internal_id, department)** — Returns { allow_export, allow_download, allow_print, allow_copy } from bi_dashboards flags and governance_policies (department). Used to reflect policy in UI and future embed options.

### Database

- **bi_dashboards** — internal_id, title, metabase_dashboard_id, linked_file_id, linked_folder_id, owner_user_id, allow_export, allow_download, allow_filter, created_at.
- **bi_permissions** — dashboard_id (FK to bi_dashboards.id), subject_type, subject_id, permission, expires_at.
- **bi_datasets** — name, source_file_id, output_table_name, extract_mode, last_sync_at (sync stubs in metabase.py).

### Routes (internal only — box philosophy)

- **GET /bi** — List dashboards (list_bi_dashboards_for_user); requires can_access_bi(). No direct Metabase UI.
- **GET /bi/dashboard/<internal_id>** — Only way to view a Metabase dashboard: session → internal registry (bi_dashboards) → permission (owner / bi_permissions / linked file-folder) → governance → short-lived JWT → embed in iframe → **audit** (log_event `bi_dashboard_view` with user, dashboard_id, linked_file_id, linked_folder_id).
- **GET /bi/<slug>** — Redirects to /bi (no public slug-based embed; internal_id only).
- **GET/POST /bi/admin** — Register/link dashboards (admin only).
- **POST /bi/link** — Link dashboard to file/folder (admin).
- **POST /bi/permissions** — Manage bi_permissions (admin).
- **POST /bi/sync/<dataset_id>** — Stub (admin).

The **running** Flask app (second instance in app.py) registers these same routes so /bi and /bi/dashboard/<id> work without exposing Metabase directly.

### Templates

- **layout.html** — “BI / Data Panel”, “BI / Dashboards”, “BI Admin” (when can_access_bi / admin).
- **bi_index.html** — List of dashboards → links to /bi/dashboard/<internal_id>.
- **bi_dashboard_view.html** — Toolbar (BI, data-panel, Drive) + iframe(embed_url); governance passed for future UI/embed restrictions.
- **bi_admin.html** — Register dashboard, list bi_dashboards, bi_datasets.
- **dashboard.html** — Folder view: folder_dashboards (linked to folder) → /bi/dashboard/<id>.
- **sheet_editor.html** — file_dashboard link → /bi/dashboard/<id> when file is linked.

### Governance & audit

- Signed embedding only (METABASE_SECRET_KEY = MB_EMBEDDING_APP_SECRET in Docker). Metabase does not manage users; the box does.
- Short-lived JWT (e.g. 10 min); Flask builds and signs; Metabase trusts the signed embed only.
- enforce_governance_rules() combines bi_dashboards flags and governance_policies; if department policy blocks export/print/copy, those are reflected (governance originates from SE_SHEETSAI).
- **Every dashboard view** is logged: `log_event("bi_dashboard_view", user, request, item_type="bi_dashboard", item_id=internal_id, context={metabase_dashboard_id, linked_file_id, linked_folder_id})`. Same philosophy as OnlyOffice callback + audit.

---

## PART 4 — What Was Not Changed

- OnlyOffice routes, onlyoffice.py, inject_permissions, callback, and sheet_editor flow are unchanged.
- Permission framework (resolve_item_access, can_access_dashboard, get_allowed_actions) unchanged.
- Project layout and existing templates (except BI and governance labels) unchanged.
- No hardcoded secrets; config/env only.
- Power BI remnants removed: build_default_definition now uses "metabase" instead of "powerbi"; governance UI labels changed from "Power BI" to "BI".

---

## PART 5 — Confirmations

- **OnlyOffice** — Unchanged; /editor/<file_id> still uses resolve_item_access, JWT, callback, layout, and inject_permissions.
- **/data-panel** — Home uses can_access_bi(); view uses can_access_bi(), get_bi_policy, then dashboards table or bi_dashboards redirect; 403 only when unauthorized; 404 when not found; 200 when allowed.
- **Permissions** — BI uses can_user_view_dashboard (ownership, bi_permissions, linked file/folder); data-panel uses can_access_dashboard for definition dashboards and redirects to BI for Metabase IDs when permitted.
- **Power BI** — No remaining code references; default definition and governance labels use BI/Metabase wording.

---

## Files Modified (Summary)

| File | Change |
|------|--------|
| app.py | data_panel_view_dup: when dashboard not in dashboards, check bi_dashboards and redirect to /bi/dashboard/<id> if permitted; build_default_definition powerbi → metabase; import metabase (generate_signed_embed_jwt, can_user_view_dashboard, get_embed_url, enforce_governance_rules); bi_dashboard_view passes governance to template. |
| modules/metabase.py | Rebuilt: generate_signed_embed_jwt, get_embed_url, can_user_view_dashboard, enforce_governance_rules; kept can_user_view_bi_dashboard, get_bi_dashboard_row, list_bi_dashboards_for_user, stubs. |
| templates/governance_home.html | "حوكمة Power BI" → "حوكمة BI". |
| templates/governance_policies.html | "سياسات Power BI" → "سياسات BI". |
| docker-compose.metabase.yml | MB_EMBEDDING_APP_SECRET from METABASE_SECRET_KEY. |
| docs/ARCHITECTURE_METABASE_BOX.md | New: full analysis and Metabase box integration. |
