# SE_SHEETSAI — Windows Deployment Guide

## Prerequisites

- Windows 10/11 or Windows Server
- Python 3.8+ (tested with Python 3.14)
- Docker Desktop for Windows
- Git (optional, for version control)

## Quick Start

### 1. Clone/Extract Project

```powershell
cd C:\se_sheetsai
# Or extract to your preferred location
```

### 2. Create Python Virtual Environment

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

### 3. Install Python Dependencies

```powershell
pip install -r requirements.txt
```

**Required packages:**
- flask
- pandas
- openpyxl (for Excel reading)
- pyjwt
- python-dotenv
- requests
- sqlite3 (built-in)

### 4. Configure Environment

Copy `.env.example` to `.env` and set required variables:

```powershell
copy .env.example .env
notepad .env
```

**Minimum required variables:**

```env
SECRET_KEY=your-secret-key-here
ONLYOFFICE_SERVER=http://localhost:8082
ONLYOFFICE_JWT_SECRET=your-jwt-secret
METABASE_BASE_URL=http://127.0.0.1:3000
METABASE_SITE_URL=http://127.0.0.1:5000/metabase
METABASE_SECRET_KEY=your-metabase-secret-key
METABASE_ADMIN_EMAIL=admin@sevens.sa
METABASE_ADMIN_PASSWORD=StrongPassword123
BI_RUNTIME_DB_PATH=C:\py\se_sheetsai\database_runtime.db
METABASE_RUNTIME_DB_PATH=/se_sheetsai/database_runtime.db
```

### 5. Start Docker Services

```powershell
docker compose -f docker-compose.metabase.yml up -d
```

This starts:
- Metabase (port 3000)
- PostgreSQL for Metabase metadata (internal)

**Wait 30-60 seconds** for Metabase to initialize.

### 6. Initialize Database

```powershell
.\.venv\Scripts\python -c "from modules.db import init_db; init_db()"
```

### 7. Run Flask Application

```powershell
.\.venv\Scripts\python app.py
```

App runs on `http://127.0.0.1:5000`

## First-Time Setup

### Metabase Initial Setup

1. Visit `http://127.0.0.1:3000` (one-time only, for admin setup)
2. Create admin account:
   - Email: `admin@sevens.sa` (must match `.env`)
   - Password: `StrongPassword123` (must match `.env`)
3. Complete setup wizard
4. **Important:** After setup, users should **never** visit `http://127.0.0.1:3000` directly. All access is via SE_SHEETSAI routes (`/bi/*`).

### OnlyOffice Setup

OnlyOffice Document Server must be running separately:

- Default: `http://localhost:8082`
- Or set `ONLYOFFICE_SERVER` in `.env`

## Production Deployment

### Windows Service (Optional)

Use `nssm` (Non-Sucking Service Manager) to run Flask as a Windows service:

```powershell
nssm install SE_SHEETSAI "C:\se_sheetsai\.venv\Scripts\python.exe" "C:\se_sheetsai\app.py"
nssm start SE_SHEETSAI
```

### Firewall Rules

- Allow port 5000 (Flask app)
- **Do NOT expose port 3000** (Metabase) publicly
- Only expose port 5000, route `/metabase/*` through Flask reverse proxy

### Reverse Proxy (IIS/Nginx)

If using IIS or Nginx:

- Proxy `/metabase/*` → `http://127.0.0.1:3000/*`
- Ensure `X-Frame-Options` and CSP headers are stripped
- Set `MB_SITE_URL` in Metabase Docker to your public URL

## Troubleshooting

### "METABASE_ADMIN_EMAIL/PASSWORD not set"

- Check `.env` file exists and variables are set
- Restart Flask app after changing `.env`

### "Cannot open <nil> as an InputStream" (Metabase)

- Ensure `METABASE_RUNTIME_DB_PATH` is set correctly
- If Metabase is in Docker, use Docker path (e.g., `/se_sheetsai/database_runtime.db`)
- Ensure SQLite file exists and is readable by Metabase container

### OnlyOffice callback fails with "iat not yet valid"

- Fixed in Phase 1: JWT verification now uses 120s leeway
- If still failing, check system clock sync

### Excel file "No readable sheets"

- Ensure Excel file has at least one sheet with headers and data rows
- Check file is not locked by another process
- Retry logic (3 attempts) should handle temporary locks

## Commands Reference

```powershell
# Start services
docker compose -f docker-compose.metabase.yml up -d

# Stop services
docker compose -f docker-compose.metabase.yml down

# View logs
docker compose -f docker-compose.metabase.yml logs -f metabase

# Restart Flask
# Ctrl+C to stop, then:
.\.venv\Scripts\python app.py

# Check health
curl http://127.0.0.1:5000/health
```

## Next Steps

- See `docs/TROUBLESHOOTING.md` for detailed error resolution
- See `docs/SECURITY_MODEL.md` for permission configuration
- See `docs/ARCHITECTURE.md` for system design
