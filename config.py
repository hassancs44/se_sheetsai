import hashlib
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ===== Flask =====
SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_ME")

# ===== Database =====
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "database.db"))
DB_FALLBACK_PATH = os.getenv("DB_FALLBACK_PATH", os.path.join(BASE_DIR, "database_runtime.db"))

# ===== OnlyOffice =====
ONLYOFFICE_SERVER = os.getenv("ONLYOFFICE_SERVER", "http://localhost:8082")
ONLYOFFICE_JWT_SECRET = os.getenv("ONLYOFFICE_JWT_SECRET", "ONLYOFFICE_SECRET")
ONLYOFFICE_JWT_ALG = "HS256"
BASE_URL = os.getenv("BASE_URL", "http://host.docker.internal:5000")

# ===== Paths =====
SHEETS_DIR = os.path.join(BASE_DIR, "sheets")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
VERSIONS_DIR = os.getenv("VERSIONS_DIR", os.path.join(BASE_DIR, "versions"))
ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", os.path.join(BASE_DIR, "archive"))

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(VERSIONS_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

# ===== Versioning =====
ARCHIVE_DAYS = int(os.getenv("ARCHIVE_DAYS", "180"))
COMPRESS_DAYS = int(os.getenv("COMPRESS_DAYS", "365"))

# ===== Search =====
SEARCH_MAX_CHARS = int(os.getenv("SEARCH_MAX_CHARS", "200000"))

# ===== Enterprise Drive Extensions =====
WATERMARK_ENABLED = os.getenv("WATERMARK_ENABLED", "true").lower() == "true"
ALLOW_DOWNLOAD = os.getenv("ALLOW_DOWNLOAD", "false").lower() == "true"
ALLOW_DOWNLOAD_DEFAULT = os.getenv("ALLOW_DOWNLOAD_DEFAULT", "false").lower() == "true"
ALLOW_PRINT_DEFAULT = os.getenv("ALLOW_PRINT_DEFAULT", "false").lower() == "true"
ALLOW_COPY_DEFAULT = os.getenv("ALLOW_COPY_DEFAULT", "false").lower() == "true"
DEFAULT_VERSION_POLICY = {
    "xlsx": os.getenv("VERSION_POLICY_XLSX", "autosave"),
    "docx": os.getenv("VERSION_POLICY_DOCX", "autosave"),
    "pptx": os.getenv("VERSION_POLICY_PPTX", "autosave")
}

# ===== Internal BI Runtime (Native BI Engine) =====
BI_RUNTIME_ENGINE = os.getenv("BI_RUNTIME_ENGINE", "sqlite").lower()  # "postgres" | "sqlite"
BI_RUNTIME_DB_PATH = os.getenv(
    "BI_RUNTIME_DB_PATH",
    os.path.join(BASE_DIR, "bi_runtime.db"),
)

# Optional PostgreSQL runtime for BI when BI_RUNTIME_ENGINE=postgres
BI_POSTGRES_HOST = os.getenv("BI_POSTGRES_HOST", "localhost")
BI_POSTGRES_PORT = int(os.getenv("BI_POSTGRES_PORT", "5433"))
BI_POSTGRES_DB = os.getenv("BI_POSTGRES_DB", "sheetsai_bi")
BI_POSTGRES_USER = os.getenv("BI_POSTGRES_USER", "sheetsai_user")
BI_POSTGRES_PASSWORD = os.getenv("BI_POSTGRES_PASSWORD", "strongpassword")


def get_bi_postgres_connection_string():
    """Build Postgres connection string for BI runtime (Flask on host)."""
    return "postgresql://{user}:{password}@{host}:{port}/{dbname}".format(
        user=BI_POSTGRES_USER,
        password=BI_POSTGRES_PASSWORD,
        host=BI_POSTGRES_HOST,
        port=BI_POSTGRES_PORT,
        dbname=BI_POSTGRES_DB,
    )


BI_CACHE_TTL = int(os.getenv("BI_CACHE_TTL", "45"))  # seconds

# BI permission: roles allowed to create/edit/resync/delete dashboards (comma-separated)
BI_ALLOWED_ROLES = [r.strip() for r in os.getenv("BI_ALLOWED_ROLES", "admin,مدير عام,مدير القسم,تحليل البيانات").split(",") if r.strip()]

# ===== File edit lock (no delete/edit by non-owner after period) =====
# بعد مرور هذه الساعات: يُمنع غير المالك من التعديل/الحذف، ويُصدر نسخة للملف، والمالك فقط يعدل
CELL_LOCK_AFTER_HOURS = int(os.getenv("CELL_LOCK_AFTER_HOURS", "12"))