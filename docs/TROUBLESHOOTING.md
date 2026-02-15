# SE_SHEETSAI — Troubleshooting Guide

## Common Errors and Solutions

### 1. OnlyOffice Callback: "JWT iat not yet valid"

**Symptoms:**
- Editing Excel file in OnlyOffice
- Pressing Save
- Error in logs: `ONLYOFFICE CALLBACK VERIFICATION FAILED`
- File not actually saved

**Cause:**
- Docker container time differs from host time
- JWT `iat` (issued at) validation fails

**Solution (Fixed in Phase 1):**
- JWT verification now uses `leeway=120` (2 minutes)
- If still failing:
  1. Check system clock sync: `w32tm /query /status`
  2. Ensure Docker Desktop time sync is enabled
  3. Restart Docker Desktop

**Verification:**
```powershell
# Check Flask logs for "ONLYOFFICE CALLBACK VERIFICATION FAILED"
# Should not appear after fix
```

---

### 2. BI Creation: "No readable sheets in Excel file"

**Symptoms:**
- Clicking "Create Dashboard from this Excel"
- Error: "No readable sheets in Excel file"
- Stack trace or generic error

**Causes:**
- Excel file is empty (no sheets)
- All sheets are hidden/very hidden
- File is still being written (locked)
- No headers or data rows

**Solution (Fixed in Phase 1):**
- Retry logic: 3 attempts with delays (0.4s, 0.8s, 1.2s)
- Skips hidden/empty sheets
- Auto-generates headers if missing
- Clear error message if truly no readable sheets

**Manual Fix:**
1. Open Excel file
2. Ensure at least one sheet is visible (not hidden)
3. Ensure sheet has headers (row 1) and at least one data row
4. Save file
5. Close Excel
6. Retry BI creation

**Verification:**
```powershell
# Check logs for:
# "bi_from_excel: workbook has X sheets: [...]"
# "bi_from_excel: created X tables: [...]"
```

---

### 3. Metabase API: "Cannot open <nil> as an InputStream"

**Symptoms:**
- Creating dashboard from Excel
- Error: "Cannot open <nil> as an InputStream"
- Metabase API call fails

**Causes:**
- `METABASE_RUNTIME_DB_PATH` not set or incorrect
- SQLite file path is Windows path (`C:\...`) but Metabase is in Docker
- SQLite file doesn't exist yet
- Metabase cannot access the file (permissions/volume mount)

**Solution:**

**Option A: Use PostgreSQL (Recommended)**

1. Update `docker-compose.metabase.yml` to include Postgres for runtime BI data:
```yaml
services:
  bi-runtime-db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: bi_runtime
      POSTGRES_USER: bi_user
      POSTGRES_PASSWORD: ${BI_DB_PASSWORD:-bi_secret}
    volumes:
      - bi-runtime-data:/var/lib/postgresql/data
```

2. Update `.env`:
```env
BI_DB_TYPE=postgres
BI_DB_HOST=localhost
BI_DB_PORT=5433
BI_DB_NAME=bi_runtime
BI_DB_USER=bi_user
BI_DB_PASSWORD=bi_secret
```

3. Update `modules/bi_from_excel.py` to use Postgres instead of SQLite

**Option B: Fix SQLite Path (If keeping SQLite)**

1. Ensure Docker volume mount includes SQLite file location:
```yaml
volumes:
  - .:/se_sheetsai
```

2. Set `.env`:
```env
BI_RUNTIME_DB_PATH=C:\py\se_sheetsai\database_runtime.db
METABASE_RUNTIME_DB_PATH=/se_sheetsai/database_runtime.db
```

3. Verify file exists:
```powershell
Test-Path C:\py\se_sheetsai\database_runtime.db
```

**Verification:**
```powershell
# Check Metabase can list databases:
curl -H "X-Metabase-Session: <session>" http://127.0.0.1:3000/api/database
```

---

### 4. "METABASE_ADMIN_EMAIL/PASSWORD not set"

**Symptoms:**
- BI creation fails
- Logs show: "metabase_api: METABASE_ADMIN_EMAIL/PASSWORD not set"

**Solution:**
1. Check `.env` file exists in project root
2. Ensure variables are set:
```env
METABASE_ADMIN_EMAIL=admin@sevens.sa
METABASE_ADMIN_PASSWORD=StrongPassword123
```
3. Restart Flask app (`.env` is loaded at startup)
4. Verify Metabase admin account exists with these credentials

**Verification:**
```powershell
# Test login manually:
curl -X POST http://127.0.0.1:3000/api/session \
  -H "Content-Type: application/json" \
  -d '{"username":"admin@sevens.sa","password":"StrongPassword123"}'
```

---

### 5. Dashboard Not Linked / metabase_dashboard_id not set

**Symptoms:**
- BI dashboard record exists in `bi_dashboards` table
- But `metabase_dashboard_id` is NULL
- "View Dashboard" shows error

**Cause:**
- Dashboard creation pipeline failed partway through
- Manual BI record created without Metabase dashboard

**Solution:**
- Use "Create Dashboard from Excel" button (full pipeline)
- Or manually link via `/bi/admin` (if implemented)
- Or delete broken record and recreate

**Prevention (Fixed in Phase 1):**
- Full pipeline now creates Metabase dashboard atomically
- If any step fails, entire operation rolls back

---

### 6. Permission Denied (403) on BI Routes

**Symptoms:**
- `/bi/*` routes return 403
- "You don't have permission" message

**Causes:**
- User role doesn't include BI access
- `can_access_bi()` returns False
- Department policy restricts BI

**Solution:**
1. Check user role in `users` table:
```sql
SELECT username, role, apps FROM users WHERE username = 'user@example.com';
```
2. Ensure `apps` column includes `bi` (e.g., `drive,sheets,bi`)
3. Or grant BI role via admin panel

**Verification:**
```python
# In Flask shell:
from modules.permissions import can_access_bi
can_access_bi('user@example.com')
```

---

### 7. OnlyOffice Editor Doesn't Load

**Symptoms:**
- Clicking "Edit" on Excel file
- OnlyOffice editor blank or error

**Causes:**
- OnlyOffice Document Server not running
- `ONLYOFFICE_SERVER` incorrect in `.env`
- CORS/network issue

**Solution:**
1. Check OnlyOffice is running:
```powershell
curl http://localhost:8082/healthcheck
```
2. Verify `.env`:
```env
ONLYOFFICE_SERVER=http://localhost:8082
```
3. Check browser console for CORS errors
4. Ensure `BASE_URL` in `config.py` matches your Flask URL

---

### 8. Database Locked (SQLite)

**Symptoms:**
- "database is locked" errors
- Concurrent access issues

**Solution:**
- SQLite doesn't handle high concurrency well
- Consider migrating to PostgreSQL for production
- Or ensure single-threaded Flask (not recommended)

**Quick Fix:**
- Increase SQLite timeout in `modules/db.py`:
```python
conn = sqlite3.connect(ACTIVE_DB_PATH, timeout=30)
```

---

## Log Locations

- Flask logs: `logs/app.log`
- Docker logs: `docker compose -f docker-compose.metabase.yml logs`
- OnlyOffice logs: Check OnlyOffice Document Server logs

## Debug Mode

Enable Flask debug logging:

```python
# In app.py, add:
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Health Check Endpoint

```powershell
curl http://127.0.0.1:5000/health
```

Returns:
- DB status
- OnlyOffice reachable
- Metabase reachable

(To be implemented in Phase 8)

---

## Getting Help

1. Check logs: `logs/app.log`
2. Check Docker logs: `docker compose logs`
3. Verify `.env` configuration
4. Test individual components (OnlyOffice, Metabase) separately
5. Review `docs/ARCHITECTURE.md` for system design
