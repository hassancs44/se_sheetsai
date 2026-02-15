# SE_SHEETSAI — PostgreSQL + Metabase Production Setup

## Architecture

```
Host (Flask app)
    ↓ localhost:5433
Docker network: sheetsai_net
    ├── postgres (sheetsai_bi) — BI runtime + Metabase internal storage
    └── metabase — connects to postgres:5432
```

- **Flask** connects to Postgres at `localhost:5433` (host port).
- **Metabase** runs in Docker and connects to `postgres:5432` (same network).
- **SQLite is not used** for BI runtime when `BI_DB_TYPE=postgres`.

---

## 1. Update `.env`

Ensure your `.env` contains (copy from `.env.example` if needed):

```env
BI_DB_TYPE=postgres
BI_POSTGRES_HOST=localhost
BI_POSTGRES_PORT=5433
BI_POSTGRES_DB=sheetsai_bi
BI_POSTGRES_USER=sheetsai_user
BI_POSTGRES_PASSWORD=strongpassword

BI_POSTGRES_HOST_METABASE=postgres
BI_POSTGRES_PORT_METABASE=5432
```

- Flask uses `BI_POSTGRES_HOST` + `BI_POSTGRES_PORT` (localhost:5433).
- Metabase (inside Docker) uses `BI_POSTGRES_HOST_METABASE` + `BI_POSTGRES_PORT_METABASE` (postgres:5432).

---

## 2. Startup Procedure

### Stop existing containers

```bash
docker compose down
```

### Start the stack

```bash
cd C:\py\se_sheetsai
docker compose up -d
```

### Verify containers

```bash
docker ps
```

You should see:

- `sheetsai_postgres` — port 5433
- `sheetsai_metabase` — port 3000

### Check logs

```bash
docker logs sheetsai_postgres
docker logs sheetsai_metabase
```

Wait 30–60 seconds for Metabase to finish initializing (first run creates schema in `sheetsai_bi`).

### Run Flask

```bash
.\.venv\Scripts\python app.py
```

Or with Gunicorn:

```bash
.\.venv\Scripts\gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

---

## 3. Validation Steps

### Metabase

1. Open **http://localhost:3000**
2. On first run: complete setup (admin email/password — use same as `METABASE_ADMIN_EMAIL` / `METABASE_ADMIN_PASSWORD` in `.env`)
3. Confirm Metabase is using PostgreSQL (internal DB).
4. In Metabase, **Add database** should show an existing “SE_SHEETSAI Runtime” connection after you run “Create Dashboard from Excel” in the app (Flask creates it via API).

### Flask logs

When you create a dashboard from Excel, you should see:

```
metabase_api: using Postgres host=postgres port=5432 db=sheetsai_bi (Flask: localhost:5433)
bi_from_excel: using Postgres host=localhost port=5433 db=sheetsai_bi
metabase_api: created Postgres database id=...
```

### Health endpoint

```bash
curl http://127.0.0.1:5000/health
```

Expect `"postgres_bi": "ok"` when Postgres is reachable.

---

## 4. Production Hardening

- **Restart:** Both services use `restart: always`.
- **Postgres data:** Stored in Docker volume `postgres_data`.
- **Health check:** Postgres has `pg_isready` every 10s.
- **No SQLite for BI:** When `BI_DB_TYPE=postgres`, the BI runtime uses only PostgreSQL.
- **Errors:** If Postgres is unreachable, Flask logs:  
  `bi_from_excel: PostgreSQL connection failed (check BI_POSTGRES_* and that Postgres is running)`  
  and `metabase_api: create database 400 ...` if Metabase cannot add the DB.

---

## 5. Troubleshooting

| Issue | Action |
|--------|--------|
| `PostgreSQL connection failed` | Ensure `docker compose up -d` and Postgres is healthy; check `BI_POSTGRES_HOST=localhost`, `BI_POSTGRES_PORT=5433`. |
| `create database 400` | Wait for Metabase to finish startup; confirm `METABASE_ADMIN_EMAIL` / `METABASE_ADMIN_PASSWORD` and Metabase login at :3000. |
| Port 5433 in use | Change host port in `docker-compose.yml` (e.g. `"5434:5432"`) and set `BI_POSTGRES_PORT=5434` in `.env`. |

---

## 6. Expected Result

- PostgreSQL running in Docker (`sheetsai_postgres`).
- Metabase connected to PostgreSQL (internal DB = `sheetsai_bi`).
- Flask connected to PostgreSQL for BI runtime.
- SQLite not used for BI when `BI_DB_TYPE=postgres`.
- Stable, production-ready BI stack.
