# SE_SHEETSAI — Deploy to DigitalOcean

This guide prepares the project for deployment on DigitalOcean (Droplet or App Platform).

---

## 1. What Was Prepared

| Item | Purpose |
|------|---------|
| `Dockerfile` | Build production image (Python 3.11, Gunicorn) |
| `docker-compose.production.yml` | App + PostgreSQL; persistent volumes for sheets, uploads, versions, archive, logs, DB |
| `.dockerignore` | Exclude .env, .venv, local DBs, docs from image |
| `.env.production.example` | Template for production env vars |
| `gunicorn.conf.py` | Gunicorn config when running without Docker |
| `GET /health` | Health check for load balancer (returns 200/503 + DB status) |
| `config.py` | `DB_PATH` / `DB_FALLBACK_PATH` overridable via env for persistent storage |

---

## 2. Option A — Docker on a Droplet (Recommended)

### 2.1 Create Droplet

1. DigitalOcean → **Create** → **Droplets**.
2. **Image:** Ubuntu 22.04 LTS.
3. **Plan:** Basic, Regular (e.g. 2 GB RAM / 1 vCPU minimum for app + Postgres).
4. **Datacenter:** Choose nearest region.
5. **Authentication:** SSH key (recommended) or password.
6. Create Droplet and note the IP.

### 2.2 Initial Server Setup

```bash
ssh root@YOUR_DROPLET_IP

# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin

# Optional: create app user (recommended)
adduser appuser
usermod -aG docker appuser
```

### 2.3 Deploy the Application

**Option 2.3a — Deploy from Git (recommended)**

```bash
cd /opt
git clone YOUR_REPO_URL se_sheetsai
cd se_sheetsai
```

If you don't use Git, upload the project (e.g. `scp -r` or SFTP) to `/opt/se_sheetsai`.

**Option 2.3b — Create .env**

```bash
cd /opt/se_sheetsai
cp .env.production.example .env
nano .env
```

Set at least:

- `SECRET_KEY` — long random string (e.g. `openssl rand -hex 32`)
- `BASE_URL` — `https://your-domain.com` (or `http://YOUR_DROPLET_IP` for testing)
- `ONLYOFFICE_JWT_SECRET` — must match the OnlyOffice container (same value used by the `onlyoffice` service)
- `ONLYOFFICE_SERVER` — if you use the OnlyOffice service in this compose: `http://onlyoffice:80` (default). If you use an external OnlyOffice: its URL (e.g. `https://onlyoffice.your-domain.com`). Leave empty only if you do not use in-browser editing.
- `BI_POSTGRES_PASSWORD` — strong password for PostgreSQL

**Option 2.3c — Run with Docker Compose**

```bash
docker compose -f docker-compose.production.yml up -d --build
docker compose -f docker-compose.production.yml ps
```

**Option 2.3d — Initialize database and users**

The app runs `init_db()` on startup. User data comes from `data/database.xlsx`. The `sheetsai_data_excel` volume is mounted at `/app/data`; put your Excel file there (e.g. copy into the running container or mount a host folder):

```bash
# From host (after placing database.xlsx in ./data/):
docker cp ./data/database.xlsx sheetsai_app:/app/data/database.xlsx
# Or use a bind mount in docker-compose: - ./data:/app/data
```

If `data/database.xlsx` is missing, the app still runs; add users later via Excel sync or direct DB.

### 2.4 Firewall

```bash
ufw allow 22
ufw allow 80
ufw allow 443
ufw enable
ufw status
```

Do **not** expose port 5000 publicly if you put Nginx in front (see below).

### 2.5 Nginx + SSL (HTTPS)

Install Nginx and use Let's Encrypt:

```bash
apt install -y nginx certbot python3-certbot-nginx
certbot --nginx -d your-domain.com
```

Nginx site config (e.g. `/etc/nginx/sites-available/sheetsai`):

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
        proxy_send_timeout 120s;
    }

    location /health {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }
}
```

Enable and reload:

```bash
ln -s /etc/nginx/sites-available/sheetsai /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

Set in `.env`: `BASE_URL=https://your-domain.com`.

### 2.6 OnlyOffice

OnlyOffice Document Server must be reachable by the app:

- **Same Droplet:** Run OnlyOffice in another container and set `ONLYOFFICE_SERVER=http://onlyoffice:80` (and configure OnlyOffice to accept your app’s JWT).
- **Separate Droplet/domain:** Set `ONLYOFFICE_SERVER=https://onlyoffice.your-domain.com` and use the same JWT secret on both sides.

If you don’t need in-browser editing yet, you can leave `ONLYOFFICE_SERVER` empty; the rest of the app will work.

---

## 3. Option B — DigitalOcean App Platform

1. Push the project to GitHub/GitLab.
2. DigitalOcean → **Apps** → **Create App** → connect repo.
3. **Source:** branch and path where `Dockerfile` and `app.py` live.
4. **Type:** Dockerfile (App Platform will build from `Dockerfile`).
5. **Resources:** e.g. 1 GB RAM, 1 vCPU.
6. **Environment variables:** Add all from `.env.production.example` (no `.env` file in repo). Set:
   - `SECRET_KEY`, `BASE_URL`, `ONLYOFFICE_SERVER`, `ONLYOFFICE_JWT_SECRET`
   - For Postgres: add a **Database** component (PostgreSQL 15), then set `BI_POSTGRES_HOST`, `BI_POSTGRES_PORT`, `BI_POSTGRES_DB`, `BI_POSTGRES_USER`, `BI_POSTGRES_PASSWORD` from the DB connection string.
7. **HTTP Port:** 5000.
8. **Health check path:** `/health`.
9. Deploy. For persistent storage (sheets, uploads, DB), use App Platform’s **Volumes** and set `DB_PATH`, `SHEETS_DIR`, etc. to paths inside the mounted volume (see their docs for mount paths).

---

## 4. Environment Variables Summary

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Flask secret (long random string) |
| `BASE_URL` | Yes | Public URL of the app (e.g. https://your-domain.com) |
| `ONLYOFFICE_JWT_SECRET` | Yes | Must match OnlyOffice Document Server |
| `ONLYOFFICE_SERVER` | No* | OnlyOffice URL (empty if not used) |
| `BI_POSTGRES_PASSWORD` | Yes (if Postgres) | PostgreSQL password |
| `DB_PATH` | No | Set in docker-compose to `/app/state/database.db` |
| `BI_RUNTIME_ENGINE` | No | `postgres` in production |
| `BI_POSTGRES_HOST` | No | `postgres` in Docker Compose |

\* Required if you use in-browser editing.

---

## 5. Health Check

- **URL:** `GET /health`
- **Response:** `200` + `{"status":"ok","database":"ok"}` or `503` + `{"status":"degraded","database":"error"}` if DB is down.
- Use this in load balancers and monitoring.

---

## 6. Post-Deploy Checklist

- [ ] `BASE_URL` and `ONLYOFFICE_SERVER` (if used) point to correct URLs.
- [ ] HTTPS enabled (Nginx + Certbot or App Platform).
- [ ] `data/database.xlsx` present if you rely on Excel user sync.
- [ ] OnlyOffice (if used) has same `ONLYOFFICE_JWT_SECRET` and accepts requests from `BASE_URL`.
- [ ] Backups: consider DigitalOcean Volumes snapshots or `pg_dump` for Postgres and copying `sheets`, `uploads`, `versions`, and `/app/state` (SQLite).

---

## 7. Useful Commands

```bash
# Logs
docker compose -f docker-compose.production.yml logs -f app

# Restart
docker compose -f docker-compose.production.yml restart app

# Stop
docker compose -f docker-compose.production.yml down

# Rebuild after code change
docker compose -f docker-compose.production.yml up -d --build
```

This completes the preparation for deploying SE_SHEETSAI to DigitalOcean.
