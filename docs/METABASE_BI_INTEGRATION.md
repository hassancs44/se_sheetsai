# SE_SHEETSAI — Metabase Embedded BI Integration

## Summary

- **Docker**: `docker-compose.metabase.yml` — Metabase on port 3000 with project folder mounted at `/se_sheetsai`.
- **Config**: `.env` and `config.py` — `METABASE_ENABLED`, `METABASE_BASE_URL`, `METABASE_SECRET_KEY` (optional, for signed embed).
- **BI access**: `can_access_bi()` — allowed if role is `admin`, `مدير عام`, or `مدير القسم`, **or** if `"bi"` is in `session["apps"]`. Enforced on `/data-panel` and `/bi/<slug>`.
- **Routes**: `/data-panel` (BI Hub), `/bi/<slug>` (embed), `/bi/admin` (admin only).

---

## One-command run (Metabase)

```bash
docker compose -f docker-compose.metabase.yml up -d
```

Then open **http://127.0.0.1:3000**, complete first-time setup, and add SQLite database:

- **Database file path**: `/se_sheetsai/database_runtime.db` (or `/se_sheetsai/database.db`)

---

## Environment variables (.env)

```env
METABASE_ENABLED=true
METABASE_BASE_URL=http://127.0.0.1:3000
# METABASE_SITE_URL=http://127.0.0.1:3000
# For signed embed (from Metabase Admin → Settings → Embedding):
# METABASE_SECRET_KEY=your_secret_key_here
```

---

## BI dashboard mapping

Edit **`modules/bi_dashboards.py`**:

- **Public embed**: set `public_url` to the Metabase public dashboard URL (from Sharing → Enable public link).
- **Signed embed**: set `mode` to `"signed"`, `metabase_dashboard_id` to the dashboard ID, and `METABASE_SECRET_KEY` in `.env`.

---

## Routes

| Route | Auth | BI guard | Description |
|-------|------|----------|-------------|
| `GET /data-panel` | login | `can_access_bi` | BI Hub: app dashboards + Metabase section |
| `GET /data-panel/<dashboard_id>` | login | `has_data_panel_access` | Existing app dashboard view |
| `GET /bi/<slug>` | login | `can_access_bi` | Metabase embed (iframe) |
| `GET /bi/admin` | login | role == `admin` | BI admin / setup instructions |

---

## End-to-end testing flow

1. **Start Metabase**: `docker compose -f docker-compose.metabase.yml up -d`
2. **Start Flask**: `python app.py`
3. **Login**: http://127.0.0.1:5000 → login with e.g. `admin@sevens.sa` / `a123`
4. **Navigation**: Sidebar shows "BI / Data Panel" if `can_access_bi` (admin or app `bi`).
5. **Data Panel**: Open **Data Panel** → see "Metabase Analytics" and app dashboards.
6. **Metabase setup**: http://127.0.0.1:3000 → add SQLite DB `/se_sheetsai/database_runtime.db` → create dashboard "Sales Demo" on `bi_sales_demo` → enable public sharing → copy URL.
7. **Wire to Flask**: In `modules/bi_dashboards.py`, set `"sales-demo"` → `"public_url": "http://127.0.0.1:3000/public/dashboard/<uuid>"`
8. **Embed**: From Data Panel click "Sales Demo" → dashboard opens in iframe at `/bi/sales-demo`.
9. **Permission test**: Login as user with role `موظف` and no `bi` in apps → BI link hidden; direct `/bi/sales-demo` returns 403.

---

## Files added/updated

- `docker-compose.metabase.yml` — Metabase service + volume + mount `.:/se_sheetsai`
- `config.py` — Metabase env vars
- `.env` — Metabase placeholders
- `modules/bi_dashboards.py` — `BI_DASHBOARDS` mapping
- `modules/bi_data.py` — `ensure_bi_sales_demo()` for `bi_sales_demo` table
- `modules/metabase_embed.py` — `get_embed_url()`, `build_signed_embed_url()`
- `modules/db.py` — `bi_sales_demo` table in `_init_db`
- `app.py` — `can_access_bi()`, imports, `ensure_bi_sales_demo()` after init, `/data-panel` guard + Metabase list, `/bi/<slug>`, `/bi/admin`
- `templates/layout.html` — BI / Data Panel link with `can_access_bi`, Shared/Trash, BI Admin for admin
- `templates/partials/navbar.html` — reusable nav partial
- `templates/data_panel.html` — Metabase Analytics section, links to `/bi/<slug>`
- `templates/bi_embed.html` — iframe embed page
- `templates/bi_admin.html` — BI admin instructions
