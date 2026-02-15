# Metabase Full Studio Integration — Complete Setup Guide

## ✅ Implementation Status

All components are **already implemented** in the codebase. This guide helps you configure and verify.

---

## 📋 PHASE 1 — Infrastructure (Docker + Database)

### 1️⃣ Directory Structure

```
C:\py\se_sheetsai
│
├── app.py                    ✅ (with reverse proxy /metabase/)
├── config.py                 ✅ (METABASE_* configs)
├── database.db               ✅ (SQLite)
├── docker-compose.metabase.yml ✅ (Postgres + Metabase)
├── .env                      ⚠️ (create/update)
├── templates/
│   ├── bi_studio.html        ✅ (Studio iframe)
│   ├── bi_dashboard_view.html ✅ (Viewer iframe)
│   ├── bi_index.html         ✅ (Dashboard list)
│   └── sheet_editor.html     ✅ (File editor with BI buttons)
└── modules/
    ├── metabase_sso.py       ✅ (SSO for Studio)
    └── metabase.py           ✅ (JWT embed helpers)
```

### 2️⃣ .env Configuration (CRITICAL)

**File:** `C:\py\se_sheetsai\.env`

**Add/Update:**

```env
# Metabase Integration
METABASE_ENABLED=true
METABASE_BASE_URL=http://127.0.0.1:3000
METABASE_SITE_URL=http://127.0.0.1:5000/metabase
METABASE_SECRET_KEY=se_sheetsai_super_secret_key_2026
METABASE_ADMIN_EMAIL=admin@sevens.sa
METABASE_ADMIN_PASSWORD=StrongPassword123

# Optional (fallback for SSO)
METABASE_API_USER=admin@sevens.sa
METABASE_API_PASSWORD=StrongPassword123
```

**Important:**
- `METABASE_SECRET_KEY` must match `MB_EMBEDDING_APP_SECRET` in Docker
- `METABASE_SITE_URL` must be `http://127.0.0.1:5000/metabase` (same-origin proxy)
- `METABASE_BASE_URL` is the internal Metabase URL (`http://127.0.0.1:3000`)

### 3️⃣ docker-compose.metabase.yml

**Already configured** with:

```yaml
environment:
  MB_ENABLE_EMBEDDING: "true"
  MB_ENABLE_PUBLIC_SHARING: "false"
  MB_EMBEDDING_APP_SECRET: ${METABASE_SECRET_KEY}
  MB_SITE_URL: ${METABASE_SITE_URL:-http://127.0.0.1:5000/metabase}
```

**Start Metabase:**

```bash
cd C:\py\se_sheetsai
docker compose -f docker-compose.metabase.yml down
docker compose -f docker-compose.metabase.yml up -d
```

**Verify:**

```bash
docker ps
```

You should see:
- `se_sheetsai_metabase`
- `se_sheetsai_metabase_db`

**Metabase UI:** http://127.0.0.1:3000

---

## 📋 PHASE 2 — First Metabase Setup

1. **Open:** http://127.0.0.1:3000
2. **Complete setup:**
   - Choose language
   - Create Admin account (use same email/password as `.env`: `METABASE_ADMIN_EMAIL` / `METABASE_ADMIN_PASSWORD`)
   - **Skip adding database** for now (we'll add SE_SHEETSAI database next)
   - Finish setup

---

## 📋 PHASE 3 — Connect SE_SHEETSAI Database

**Inside Metabase:**

1. **Admin → Databases → Add Database**
2. **Choose:** SQLite
3. **Database file path:** `/se_sheetsai/database.db`
   - (This path is inside the Docker container; the volume maps `.:/se_sheetsai`)
4. **Save**

**Expected:** "Connection successful" ✅

**Note:** If you're running Metabase outside Docker, use the absolute Windows path (e.g., `C:\py\se_sheetsai\database.db`).

---

## 📋 PHASE 4 — Create Real Dashboard

**Inside Metabase:**

1. **New → Question**
   - Choose your database (`database.db`)
   - Select a table (e.g., `orders`, `files`, `folders`, etc.)
   - Build chart
   - **Save**

2. **New → Dashboard**
   - Add your question
   - **Save**

**You now have a real working dashboard.**

**Note the Metabase Dashboard ID** (e.g., `1`, `2`, etc.) — you'll need it to register in SE_SHEETSAI.

---

## 📋 PHASE 5 — Enable Secure Embedding

**Inside Metabase:**

1. **Admin → Settings → Embedding**
2. **Enable:**
   - ✅ Embedding
   - ✅ Signed Embedding
3. **Embedding secret:** Set to `METABASE_SECRET_KEY` from `.env` (e.g., `se_sheetsai_super_secret_key_2026`)

**This is critical** — without this, JWT embedding won't work.

---

## 📋 PHASE 6 — Register Dashboard in SE_SHEETSAI

**Login to SE_SHEETSAI:**

1. **Go to:** http://127.0.0.1:5000
2. **Login** with your credentials
3. **Navigate:** إدارة لوحات البيانات (`/bi/admin`) — admin only
4. **Register Dashboard:**
   - **العنوان:** My Dashboard
   - **معرف لوحة Metabase:** `1` (or your dashboard ID)
   - **ربط بملف:** (optional) `FILE_xxx`
   - **ربط بمجلد:** (optional) `FOLDER_xxx`
   - **Click:** تسجيل اللوحة

**Result:** Dashboard is registered with an `internal_id` (e.g., `BI_202602101200_ABC123`).

---

## 📋 PHASE 7 — Test Viewer Mode (JWT Embed)

**URL:** http://127.0.0.1:5000/bi/dashboard/BI_202602101200_ABC123

**Expected:**
- ✅ Arabic toolbar (العودة للوحة التحكم، العودة للوحات BI، تحرير، إدارة)
- ✅ Dashboard embedded in iframe via `/metabase/embed/dashboard/<jwt>`
- ✅ No Metabase login screen
- ✅ Secure JWT token (10 min expiry)

**How it works:**
1. Flask generates JWT with `METABASE_SECRET_KEY`
2. Iframe loads `/metabase/embed/dashboard/<jwt>` (same-origin proxy)
3. Proxy forwards to Metabase `/embed/dashboard/<jwt>`
4. Metabase validates JWT and returns dashboard

---

## 📋 PHASE 8 — Test Studio Mode (Full Metabase App UI)

### 8.1 Create New Dashboard

**URL:** http://127.0.0.1:5000/bi/studio/new

**Expected:**
- ✅ Arabic toolbar (العودة للوحات BI، العودة للأقراص، إدارة BI)
- ✅ Full Metabase App UI in iframe (`/metabase/app/dashboard/new`)
- ✅ **No Metabase login screen** (SSO cookie set)
- ✅ Can create dashboards, questions, SQL, models

**How it works:**
1. Flask calls `ensure_metabase_session()` → POST to Metabase `/api/session` with admin credentials
2. Gets session token
3. Sets cookie `metabase.SESSION=<token>` with `path=/metabase`
4. Iframe loads `/metabase/app/dashboard/new` (same-origin proxy)
5. Browser sends cookie → Proxy forwards cookie → Metabase authenticates → Full UI loads

### 8.2 Edit Existing Dashboard

**URL:** http://127.0.0.1:5000/bi/studio/dashboard/BI_202602101200_ABC123

**Expected:**
- ✅ Same as above
- ✅ Iframe loads `/metabase/app/dashboard/<metabase_id>`
- ✅ Can edit dashboard, questions, SQL

---

## 📋 PHASE 9 — System Integration Flow

### Complete User Journey:

1. **Login** → http://127.0.0.1:5000
2. **Dashboard** → الأقراص
3. **BI Section** → لوحات البيانات (`/bi`)
4. **Actions:**
   - **إنشاء لوحة جديدة** → `/bi/studio/new` (Studio mode)
   - **عرض** → `/bi/dashboard/<internal_id>` (Viewer mode)
   - **تحرير** → `/bi/studio/dashboard/<internal_id>` (Studio mode)
   - **ربط** → `/bi/admin` (Link to file/folder)

### From File Editor:

**Open file** → `/editor/FILE_xxx`

**Buttons:**
- **📊 إنشاء لوحة بيانات من هذا الملف** → Creates dashboard linked to file
- **📊 عرض لوحة البيانات** → Opens viewer
- **📊 تحرير لوحة البيانات** → Opens Studio editor

---

## 🔐 Security Model

### Metabase:
- ✅ **Not directly exposed** (port 3000 not public in production)
- ✅ **Embedded only** (via Flask proxy `/metabase/`)
- ✅ **JWT protected** (viewer mode)
- ✅ **SSO protected** (Studio mode)
- ✅ **Controlled by Flask** (all access via SE_SHEETSAI routes)

### SE_SHEETSAI:
- ✅ **Controls session** (Flask login required)
- ✅ **Controls permissions** (`can_access_bi()`, `can_edit_bi()`)
- ✅ **Controls dashboard visibility** (`can_user_view_bi_dashboard()`)
- ✅ **Logs access** (audit events: `bi_dashboard_view`, `bi_studio_open_new`, etc.)
- ✅ **Applies governance** (`enforce_governance_rules()`)

---

## 🧪 Verification Checklist

### ✅ Infrastructure:
- [ ] Metabase running (`docker ps` shows containers)
- [ ] `.env` configured (all `METABASE_*` vars set)
- [ ] `METABASE_SECRET_KEY` matches Docker `MB_EMBEDDING_APP_SECRET`
- [ ] `METABASE_SITE_URL=http://127.0.0.1:5000/metabase`

### ✅ Metabase Setup:
- [ ] Admin account created (matches `.env`)
- [ ] SE_SHEETSAI database connected (`/se_sheetsai/database.db`)
- [ ] Embedding enabled (Admin → Settings → Embedding)
- [ ] Embedding secret = `METABASE_SECRET_KEY`
- [ ] At least one dashboard created

### ✅ SE_SHEETSAI Integration:
- [ ] Dashboard registered in `/bi/admin`
- [ ] Viewer works: `/bi/dashboard/<internal_id>` shows dashboard
- [ ] Studio new works: `/bi/studio/new` shows full Metabase UI (no login)
- [ ] Studio edit works: `/bi/studio/dashboard/<internal_id>` shows edit UI
- [ ] All pages Arabic RTL
- [ ] Navigation connected (no broken links)

### ✅ Security:
- [ ] Direct Metabase URL blocked (port 3000 not exposed publicly)
- [ ] Viewer requires Flask login
- [ ] Studio requires Flask login + BI Designer/Admin role
- [ ] JWT tokens expire (10 min)
- [ ] Audit logs show BI events

---

## 🚨 Troubleshooting

### Issue: "No session id in response" (SSO fails)

**Check:**
- `METABASE_ADMIN_EMAIL` and `METABASE_ADMIN_PASSWORD` in `.env` match Metabase admin account
- Metabase is running (`docker ps`)
- `METABASE_BASE_URL=http://127.0.0.1:3000` is correct

### Issue: "Embed not configured (METABASE_SECRET_KEY)"

**Check:**
- `METABASE_SECRET_KEY` in `.env` is set
- Metabase Embedding → Signed Embedding is enabled
- Embedding secret in Metabase matches `METABASE_SECRET_KEY`

### Issue: Metabase login screen appears in Studio iframe

**Check:**
- `METABASE_SITE_URL=http://127.0.0.1:5000/metabase` (not `http://127.0.0.1:3000`)
- Reverse proxy is working (`/metabase/` route exists in Flask)
- Cookie is set (`metabase.SESSION` with `path=/metabase`)
- Browser console shows cookie is sent

### Issue: "Could not build url for endpoint 'app_access_test'"

**Fixed:** Route added in running Flask app. Restart Flask if needed.

---

## 📚 Routes Reference

| Route | Endpoint | Description |
|-------|----------|-------------|
| `/bi` | `bi_index` | List dashboards |
| `/bi/dashboard/<internal_id>` | `bi_dashboard_view` | Viewer (JWT embed) |
| `/bi/studio/new` | `bi_studio_new` | Studio (create new) |
| `/bi/studio/dashboard/<internal_id>` | `bi_studio_dashboard` | Studio (edit existing) |
| `/bi/admin` | `bi_admin` | Register/link dashboards |
| `/metabase/<path>` | `metabase_proxy` | Reverse proxy (same-origin) |

---

## 🎯 Final Result

You now have:

✅ **Full BI platform** (creation + editing + SQL + dashboards)  
✅ **Secure Embedding** (JWT for viewer, SSO for Studio)  
✅ **Integrated inside SE_SHEETSAI** (no separate login)  
✅ **Production ready** (reverse proxy, same-origin, controlled access)  
✅ **Scalable** (Postgres backend, proper architecture)  
✅ **Arabic RTL UI** (all pages fully Arabic)  
✅ **Fully connected** (navigation between all pages)

**Metabase behaves exactly like OnlyOffice** — embedded, controlled, secure, and native to your system.
