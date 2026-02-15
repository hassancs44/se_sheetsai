# SE_SHEETSAI — Production image for DigitalOcean (and any Docker host)
FROM python:3.11-slim

WORKDIR /app

# System deps for pandas/openpyxl (optional, reduces runtime issues)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Application
COPY config.py .
COPY app.py .
COPY modules ./modules
COPY templates ./templates
COPY static ./static

# Create dirs that app expects (volumes override in production)
RUN mkdir -p sheets uploads versions archive logs data state

ENV PYTHONUNBUFFERED=1
EXPOSE 5000

# Gunicorn: bind 0.0.0.0 for Docker, 4 workers (tune per droplet size)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--threads", "2", "--timeout", "120", "app:app"]
