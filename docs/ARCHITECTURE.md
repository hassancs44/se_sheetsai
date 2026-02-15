## SE_SHEETSAI — Integrated Enterprise Drive, Governance, and BI Platform

### 1. System Overview

SE_SHEETSAI is a single, tightly integrated Flask application that combines:

- **Enterprise drive** (files/folders, sharing, versioning)
- **Governance and audit** (policies, violations, automation rules)
- **Embedded analytics / BI** (native dashboards + Metabase)

Everything runs as **one system**, not as separate apps:

- Entry point: `app.py`
- Core DB schema and migrations: `modules/db.py`
- Permissions and access checks: `modules/permissions.py`, `modules/auth.py`
- BI / Metabase integration: `modules/bi_dashboards.py`, `modules/bi_data.py`, `modules/metabase_embed.py`, `docs/METABASE_BI_INTEGRATION.md`

The SQLite database is the runtime **source of truth** for users, roles, folders/files, permissions, dashboards, BI demo data, and governance metadata. Excel is used as an upstream source for users but not as the live state.

---

### 2. Core Architectural Principles

**Single Source of Truth**

- Implemented by the schema in `modules/db.py`:
  - `users`, `folders`, `files`, `permissions`, `dashboards`, `dashboard_kpis`, `datasets`, `audit_log`, `governance_policies`, `access_violations`, `automation_rules`, `department_policies`, `file_versions`, `file_classifications`, `ownership_transfers`, and `bi_sales_demo`.
- Excel users are synchronized into `users` on startup (`modules/sync_excel_users.py`), then the DB is authoritative.

**Server-Side Enforcement**

- All routes in `app.py`:
  - Call `require_login()` to enforce session existence.
  - Use helpers from `modules/permissions.py` and `modules.auth.py` to gate actions:
    - `get_user_role`, `resolve_item_access`, `get_allowed_actions`, `find_expired_share_access`, etc.
  - File, folder, share, trash, preview, OnlyOffice, Power BI, and BI routes all enforce access **before** rendering.

**Governed Integration**

- External engines (OnlyOffice, Power BI, Metabase) are always called through:
  - A server-side route
  - With the current session and permissions already validated
  - Under governance/audit logging (`modules.audit`).

**Additive, Non-Breaking Expansion**

- New capabilities (dashboard studio, governance, Metabase BI) are added as new modules, routes, and templates but:
  - Reuse `require_login()` and the same permission helpers.
  - Do not change the existing login model or drive semantics.

---

### 3. Authentication & Session Model

- **Login**:
  - Implemented in `app.py` (`/login` route).
  - Uses `modules.auth.authenticate()` with Excel-backed user lookup (`get_user_from_excel()`).
- **Session context**:
  - After login, `session` is populated with:
    - `user`, `email`, `name`
    - `role` (e.g. `admin`, `مدير عام`, `مدير القسم`, `موظف`, `المواردالبشريه`)
    - `department`, `branch`, `company`
    - `apps` (list from Excel, e.g. `"drive"`, `"bi"`, ...)
  - `@app.context_processor` exposes:
    - `session_email`, `session_name`, `session_role`, `session_department`, `session_branch`, `session_company`, `session_apps`
    - Helper booleans: `can_data_panel`, `can_dashboard_studio`, `can_governance`, `can_access_app`, and **`can_access_bi`**.
- **Auth contract**:
  - No route that touches files, dashboards, or BI is reachable without `require_login()` and a valid session.

---

### 4. Drive & Governance Layer

- **Drive** (`/dashboard`, `/folder/<id>`, `/upload`, `/trash`, `/shared`, etc.):
  - Folder and file models: tables `folders` and `files` in `modules/db.py`.
  - All operations are validated by `modules/permissions.py` + `modules/auth.py`.
  - Sharing is modeled via `permissions` and resolved per request.
  - Actions are logged in `audit_log` via `modules.audit.log_event`.

- **Governance**:
  - Policy and telemetry tables in `modules/db.py`:
    - `governance_policies`, `access_violations`, `automation_rules`, `department_policies`, `audit_log`.
  - Routes in `app.py`:
    - `/governance`, `/governance/dashboards`, `/governance/datasets`, `/governance/policies`, `/governance/violations`, `/governance/audit`, and `/admin/*` variants.
  - Only privileged roles (`admin`, `مدير عام`) can access governance UIs, enforced by `has_governance_access()`.

---

### 5. BI Data & Access Layer

**BI Data (`bi_sales_demo`)**

- Schema in `modules/db.py` (`_init_db()`):

  - `bi_sales_demo(id, sale_date, branch, department, amount, category)`.

- Seeded via `modules/bi_data.ensure_bi_sales_demo()`:
  - Called from `app.py` after `init_db()` and `seed_first_dashboard()`.
  - Inserts demo rows if the table has fewer than 30 rows.

**BI Access Control**

- Central helper in `app.py`:

  - `can_access_bi()`:
    - Returns `True` if:
      - `role` in `("admin", "مدير عام", "مدير القسم")`, **or**
      - `"bi"` is present in `session["apps"]`.
  - Exposed to templates as `can_access_bi` via `@app.context_processor`.

- This is enforced on all **BI entry points**:
  - `GET /data-panel` (BI Hub)
  - `GET /bi/<slug>` (Metabase dashboards)
  - Navigation visibility (sidebar) is driven by `can_access_bi`, but server checks are always present.

---

### 6. Embedded BI (Metabase)

**Docker & Connectivity**

- `docker-compose.metabase.yml`:
  - Service `metabase` on port `3000`.
  - Persistent volume `metabase-data`.
  - Project root mounted at `/se_sheetsai`.
- Metabase DB connection:
  - Inside Metabase UI, SQLite path is `/se_sheetsai/database_runtime.db` (or `database.db`).

**Config & Modes**

- Config values in `config.py` + `.env`:
  - `METABASE_ENABLED`
  - `METABASE_BASE_URL`
  - `METABASE_SITE_URL` (optional)
  - `METABASE_SECRET_KEY` (for signed embed).

- Implementation module: `modules/metabase_embed.py`:
  - `build_signed_embed_url(dashboard_id, params, exp_minutes)`:
    - Builds a JWT with:
      - `resource: {"dashboard": id}`
      - `params` (filters; merged defaults + session context)
      - `exp` (short-lived UNIX timestamp)
    - Signs with `METABASE_SECRET_KEY` (HS256; `jwt` library).
  - `get_embed_url(dashboard_config, session_params)`:
    - If `mode == "signed"` and `METABASE_SECRET_KEY` is set → use signed embed URL.
    - Otherwise → fall back to `public_url` from the dashboard config.

**Public vs Signed Embed**

- **Public embed**:
  - Uses URLs from Metabase’s “Public sharing” feature.
  - Still gated by `can_access_bi()` on the Flask side.
- **Signed embed**:
  - Used when `mode == "signed"` and a secret is provided.
  - Supports runtime filters (e.g. department, branch).

---

### 7. BI Dashboard Registry

- Implemented in `modules/bi_dashboards.py`:

  - `BI_DASHBOARDS`: central mapping of logical slugs to dashboards, e.g.:
    - `sales-demo`, `ops-kpis`, etc.
    - Each entry defines:
      - `title`
      - `slug`
      - `mode` (`"public"` or `"signed"`)
      - `public_url` (for public embedding)
      - `metabase_dashboard_id` (for signed embedding)
      - `default_params` (baseline filter parameters)

  - Access helpers:
    - `get_bi_dashboard(slug)`
    - `list_bi_dashboards()`

This registry keeps BI configuration out of route functions and templates; routes only work with slugs and configs.

---

### 8. Routing & Pages

**Data Panel (BI Hub): `GET /data-panel`**

- Implemented in `app.py`:
  - Requires `require_login()` and `can_access_bi()`.
  - Applies BI policy via `get_bi_policy(department)`; denies if `allow_view` is `False`.
  - Loads:
    - Published app dashboards from `dashboards` table (filtered with `can_access_dashboard()`).
    - `metabase_dashboards = list_bi_dashboards()` when `METABASE_ENABLED`.
  - Renders `templates/data_panel.html`:
    - “Metabase Analytics” section with cards linking to `/bi/<slug>`.
    - “لوحات البيانات (التطبيق)” for internal dashboards.

**Native Dashboard View: `GET /data-panel/<dashboard_id>`**

- Existing runtime for in-app dashboards (Power BI / runtime builder).
- Guarded by:
  - `require_login()`
  - `has_data_panel_access()` (role-based)
  - `get_bi_policy()` (department-level BI policy)
  - `can_access_dashboard()` (per-dashboard ACL).

**Metabase Viewer: `GET /bi/<slug>`**

- Implemented in `app.py`:
  - Requires `require_login()` + `can_access_bi()`.
  - Checks `METABASE_ENABLED`; 404 if disabled.
  - Loads config via `get_bi_dashboard(slug)`; 404 if missing.
  - Builds `session_params` (e.g. `department`, `branch` from session).
  - Calls `get_embed_url()` to obtain iframe URL (public or signed).
  - Renders `templates/bi_embed.html`:
    - Toolbar with:
      - “← البوابة” (`/data-panel`)
      - “لوحة التحكم” (`/dashboard`)
      - Dashboard title.
    - iframe or an error message if misconfigured.

**BI Admin: `GET /bi/admin`**

- Implemented in `app.py`:
  - Requires `require_login()` and `role == "admin"`.
  - Renders `templates/bi_admin.html`:
    - Step-by-step setup (Docker, Metabase DB, public/signed embedding).
    - List of all dashboards from `list_bi_dashboards()` with per-entry status.

---

### 9. Navigation & Frontend Contract

- Global layout: `templates/layout.html`:
  - Sidebar links:
    - Always:
      - `/dashboard` (Drive)
      - `/shared`
      - `/trash`
    - If `can_access_bi`:
      - `/data-panel` (“BI / Data Panel”)
    - If `role in ("admin", "مدير عام")`:
      - Governance section (`/governance`, `/governance/*`)
      - `/dashboard-studio`
    - If `role == "admin"`:
      - `/bi/admin` (“BI Admin”)
    - Apps:
      - `/apps/<app>` for each entry in `session["apps"]`.
  - Logout: `/logout`.

- The frontend:
  - Never constructs embed URLs itself.
  - Never decides access; it only renders links/buttons that the backend has already authorized via context.
  - Cannot bypass server checks; `/data-panel` and `/bi/<slug>` perform full validation.

---

### 10. End-to-End Flow (BI Example)

1. **Login**:
   - User authenticates via `/login`.
   - Session is populated with role and apps (e.g. `admin`, `apps=["drive","bi"]`).
2. **Navigation**:
   - Sidebar shows “BI / Data Panel” if `can_access_bi` is `True`.
3. **Open Data Panel**:
   - `GET /data-panel`:
     - Checks login + `can_access_bi` + department BI policy.
     - Returns app dashboards + Metabase dashboards list.
4. **Choose BI dashboard**:
   - Click a Metabase card → `GET /bi/<slug>`.
   - Backend:
     - Validates `can_access_bi`.
     - Loads registry entry.
     - Generates signed/public embed URL.
   - Template renders iframe with navigation chrome.
5. **Audit and governance**:
   - All significant actions are logged via `modules.audit`.
   - BI access violations are recorded in `access_violations`.

---

### 11. Integrity Guarantees

Because of this design:

- **BI cannot be accessed independently**:
  - There is no “naked” Metabase link in the app; all entry points go through `/data-panel` or `/bi/<slug>` with guards.
- **Dashboards cannot bypass permissions**:
  - Per-dashboard and per-department policies apply before any embed is rendered.
- **Drive, governance, and analytics share the same enforcement model**:
  - Session + helpers in `modules/permissions.py` and `app.py` define “who can do what” everywhere.
- **New features are additive**:
  - Metabase integration reused the existing identity, governance, and logging stack without changing their semantics.

This file is the high-level map. For Metabase-specific setup commands and step-by-step instructions, see `docs/METABASE_BI_INTEGRATION.md`.

