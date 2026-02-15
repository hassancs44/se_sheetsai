# Metabase Studio Embed — Implementation Report (Box Philosophy)

## Summary

Metabase is embedded inside SE_SHEETSAI as an internal tool. Users never go to Metabase directly; all access is via SE_SHEETSAI routes. Viewer mode uses signed JWT embed; Studio mode (full Metabase app UI) uses SSO bootstrap when Metabase is served under the same origin (reverse proxy).

---

## Files Changed

| File | Changes |
|------|--------|
| `app.py` | Added `make_response` import; `_can_edit_bi()`, `@app.context_processor` for `can_edit_bi`/`can_access_bi`; routes `bi_studio_new`, `bi_studio_dashboard`; `bi_index_s2` now adds `can_edit` per dashboard and logs `bi_index_view`; `bi_dashboard_view_s2` passes `can_edit`/`is_admin` and Arabic error messages; `bi_link_s2` gated by `_can_edit_bi()`; audit event `bi_permissions_updated`. |
| `modules/metabase.py` | Added `can_user_edit_bi_dashboard`, `bootstrap_metabase_session()`, `is_metabase_same_origin(request_host)`; config import for `METABASE_BASE_URL`, `METABASE_API_USER`, `METABASE_API_PASSWORD`. |
| `templates/bi_studio.html` | **New.** Arabic RTL toolbar (العودة للوحات BI, العودة للأقراص, عرض, ربط), iframe for Metabase app UI, same-origin/SSO error messages. |
| `templates/bi_index.html` | Arabic labels; buttons عرض / تحرير / ربط; "إنشاء لوحة جديدة" → `bi_studio_new`; status badges (مرتبط بملف، مرتبط بمجلد، غير مرتبط); governance indicator (تصدير ممنوع). |
| `templates/bi_dashboard_view.html` | Toolbar: العودة للوحة التحكم, العودة للوحات BI, تحرير (if can_edit), إدارة (if admin); Arabic error text. |
| `templates/layout.html` | Added "استوديو لوحات البيانات" (when `can_edit_bi`); "إدارة لوحات البيانات" for admin. |
| `docker-compose.metabase.yml` | Postgres service `metabase-db`; Metabase env: `MB_DB_*`, `MB_SITE_URL`, `MB_ENABLE_PUBLIC_SHARING=false`, `MB_ENABLE_EMBEDDING=true`, `MB_EMBEDDING_APP_SECRET`. |
| `docs/METABASE_STUDIO_IMPLEMENTATION.md` | This file. |

---

## New Routes

| Method | Path | Endpoint | Description |
|--------|------|----------|-------------|
| GET | `/bi/studio/new` | `bi_studio_new` | Open Metabase Studio to create new dashboard (BI Designer/Admin). |
| GET | `/bi/studio/dashboard/<internal_id>` | `bi_studio_dashboard` | Open Metabase Studio to edit existing dashboard (edit permission required). |
| GET | `/bi` | `bi_index` | List dashboards (existing; now with `can_edit` and `bi_index_view` audit). |
| GET | `/bi/dashboard/<internal_id>` | `bi_dashboard_view` | Viewer: signed embed (existing; now with `can_edit`/`is_admin` in template). |
| POST | `/bi/link` | `bi_link_s2` | Link dashboard to file/folder (now allowed for BI Designer/Admin, not only admin). |
| POST | `/bi/permissions` | `bi_permissions_s2` | Manage permissions (admin-only; audit event `bi_permissions_updated`). |

---

## SSO Method and Why

**Chosen:** Metabase API session bootstrap (integration account).

- **How:** When the user opens `/bi/studio/new` or `/bi/studio/dashboard/<id>`, SE_SHEETSAI calls `bootstrap_metabase_session()` which POSTs to `METABASE_BASE_URL/api/session` with `METABASE_API_USER` and `METABASE_API_PASSWORD`. Metabase returns a session ID. If the request host matches `METABASE_SITE_URL` (same origin), the response sets a cookie `metabase.SESSION` with `path=/metabase` so the iframe (loading Metabase under the same host at `/metabase/...`) sends the cookie and the user sees the full app UI without a login prompt.
- **Why:** Metabase Community does not provide built-in OIDC/SAML in the same way; the API session approach is documented and works with a single integration user. Role mapping (SE_SHEETSAI “admin”/“مدير عام” → Metabase) can be extended later via Metabase API groups if needed; for now, the integration user is a Metabase admin and Studio is restricted to BI Designer/Admin in SE_SHEETSAI.

---

## Metabase Reverse Proxy / Cookie Settings

- **Requirement:** For Studio (full Metabase app in iframe), Metabase must be served under the **same origin** as SE_SHEETSAI (e.g. `https://drive.sevens.sa/metabase/`). Otherwise the browser does not send cookies to the iframe (third-party cookie rules).
- **Recommended:** Put Metabase behind the same host with a path prefix, e.g. nginx:
  - `location /metabase/ { proxy_pass http://metabase:3000/; proxy_set_header Host $host; ... }`
  - Set `METABASE_SITE_URL=https://drive.sevens.sa/metabase` and `METABASE_BASE_URL=http://metabase:3000` (internal).
- **Cookie:** When `is_metabase_same_origin(request.host)` is true, the response sets `metabase.SESSION=<id>; Path=/metabase; Max-Age=3600; SameSite=Lax`. The iframe URL is `{{ METABASE_SITE_URL }}/app/dashboard/new` or `/app/dashboard/<metabase_id>`.
- **Local dev:** If SE_SHEETSAI is on port 5000 and Metabase on 3000, `same_origin` is false; Studio page shows an Arabic message that Metabase must be run under the same domain (reverse proxy).

---

## Permissions Mapping (SE_SHEETSAI → Metabase)

- **SE_SHEETSAI**  
  - **BI Viewer:** `can_access_bi()` — role in (`admin`, `مدير عام`, `مدير القسم`) or app `bi` in `session["apps"]`. Can only view dashboards (signed embed).  
  - **BI Designer / Admin:** `_can_edit_bi()` — role in (`admin`, `مدير عام`). Can open Studio, link dashboards, and (admin) manage permissions.  
- **Metabase:** Access to the app UI is via a single integration account used by `bootstrap_metabase_session()`. Fine-grained Metabase groups (viewer/builder/admin) can be added later via Metabase API; SE_SHEETSAI remains the source of truth for who can open Studio and which dashboards they can edit (`can_user_edit_bi_dashboard`).

---

## Box Behaviour

- All BI entry points are SE_SHEETSAI pages (Arabic): لوحات البيانات، استوديو لوحات البيانات، إدارة لوحات البيانات.
- No direct links to raw Metabase URLs; navigation uses `url_for('bi_index')`, `url_for('bi_dashboard_view', ...)`, `url_for('bi_studio_new')`, `url_for('bi_studio_dashboard', ...)`, `url_for('bi_admin')`, `url_for('dashboard')`.
- Viewer: only signed embed; no public sharing.
- Governance: enforced in SE_SHEETSAI (`enforce_governance_rules`); export/print/copy reflected in UI and embed where supported.
- Audit: every BI action logs an event: `bi_index_view`, `bi_dashboard_view`, `bi_studio_open_new`, `bi_studio_dashboard_open`, `bi_dashboard_registered`, `bi_dashboard_linked`, `bi_permissions_updated`, `bi_access_denied` (on 403).

---

## OnlyOffice and Other Logic

- OnlyOffice (editor, JWT, callbacks) and existing permission/governance logic were not modified.
- Database schema for `bi_dashboards` and `bi_permissions` is unchanged; no new migrations.

---

## Manual Acceptance Checklist

- [ ] Login → Drive works.  
- [ ] BI → لوحات البيانات list works; عرض / تحرير / ربط and إنشاء لوحة جديدة visible where allowed.  
- [ ] Viewer opens dashboard with signed embed.  
- [ ] With same-origin proxy and SSO: Studio opens Metabase app UI in iframe without Metabase login.  
- [ ] BI Designer/Admin can create and edit dashboards in Studio.  
- [ ] Viewer (no edit) cannot access Studio (403).  
- [ ] Direct Metabase URL not linked; port 3000 not exposed in production.  
- [ ] Public sharing disabled (`MB_ENABLE_PUBLIC_SHARING=false`).  
- [ ] Audit log shows BI events.  
- [ ] OnlyOffice /editor/<file_id> flow unchanged.
