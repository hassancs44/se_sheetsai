# SE_SHEETSAI — Production image for DigitalOcean / Render / Any Docker host
FROM python:3.11-slim

WORKDIR /app

# =========================
# System dependencies
# =========================
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# =========================
# Python dependencies
# =========================
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# =========================
# Copy entire project
# (includes app, config, modules, templates, static, and data/ if present)
# =========================
COPY . .

# =========================
# Ensure required runtime folders exist
# =========================
RUN mkdir -p sheets uploads versions archive logs data state

# =========================
# Environment
# =========================
ENV PYTHONUNBUFFERED=1

# Render assigns PORT automatically; gunicorn.conf.py reads it
EXPOSE 5000

# =========================
# Start Gunicorn
# (gunicorn.conf.py uses PORT env variable for cloud hosts)
# =========================
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
