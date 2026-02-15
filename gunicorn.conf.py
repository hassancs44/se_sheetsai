# Gunicorn config for production (used when running: gunicorn -c gunicorn.conf.py app:app)
import os

bind = "0.0.0.0:5000"
workers = int(os.getenv("GUNICORN_WORKERS", "4"))
threads = 2
timeout = 120
keepalive = 5
worker_tmp_dir = "/dev/shm"  # use RAM disk if available (Linux)

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
