# SE_SHEETSAI — Production Hardening

## Phase 8 Checklist

### 1. Disable Flask debug
- Set `FLASK_DEBUG=0` or do not set `FLASK_ENV=development`
- In `app.py`, ensure `app.run(debug=False)` when not in dev

### 2. Run with Gunicorn
```bash
# Install
pip install gunicorn

# Run (4 workers; bind to 0.0.0.0:5000)
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```
Or use a process manager (systemd, supervisord).

### 3. Nginx reverse proxy
- Proxy `/` → `http://127.0.0.1:5000`
- Proxy `/metabase/` → `http://127.0.0.1:3000` (or internal Metabase)
- Strip `X-Frame-Options` on `/metabase/` so embed works
- Configure HTTPS (SSL certificate)

Example (snippet):
```nginx
server {
    listen 443 ssl;
    server_name drive.example.com;
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location /metabase/ {
        proxy_pass http://127.0.0.1:3000/;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 4. HTTPS
- Use TLS 1.2+ only
- Set `METABASE_SITE_URL=https://drive.example.com/metabase`
- Set `BASE_URL=https://drive.example.com`

### 5. Metabase isolation (zero direct exposure)
- **Do not expose port 3000** publicly. In production:
  - Remove `ports: - "3000:3000"` from docker-compose, or
  - Bind to 127.0.0.1 only: `"127.0.0.1:3000:3000"`
- All user access to Metabase must go through Flask (`/metabase/` proxy).
- Users must never open `http://metabase-server:3000` directly.

### 6. Docker restart policies
- Already set in `docker-compose.yml`: `restart: unless-stopped` for postgres and metabase.

### 7. Environment variables
- Never commit `.env`. Use CI/CD or orchestration to inject env in production.
- Use strong secrets: `SECRET_KEY`, `ONLYOFFICE_JWT_SECRET`, `METABASE_SECRET_KEY`, `BI_POSTGRES_PASSWORD`, `METABASE_DB_PASSWORD`.

### 8. Health monitoring
- Poll `/health` for DB, OnlyOffice, Metabase, Postgres BI.
- Alert on `"ok": false` or failed checks.
