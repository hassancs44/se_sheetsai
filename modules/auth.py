import os
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash
from config import BASE_DIR

EXCEL_PATH = os.path.join(BASE_DIR, "data", "database.xlsx")


def _normalize_csv(value):
    raw = str(value or "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def get_user_from_excel(email):
    if not os.path.exists(EXCEL_PATH):
        return None
    df = pd.read_excel(EXCEL_PATH)
    if "البريد الإلكتروني" not in df.columns:
        return None
    email = (email or "").strip().lower()
    row = df[df["البريد الإلكتروني"].astype(str).str.lower() == email]
    if row.empty:
        return None
    r = row.iloc[0]
    return {
        "email": email,
        "name": str(r.get("الاسم", "")).strip(),
        "role": str(r.get("الصلاحية", "")).strip(),
        "department": str(r.get("القسم", "")).strip(),
        "status": str(r.get("الحالة", "")).strip(),
        "force_reset": 1 if str(r.get("force_reset", "")).strip() == "1" else 0,
        "extra_departments": _normalize_csv(r.get("الأقسام الأخرى", "")),
        "apps": _normalize_csv(r.get("apps", "")),
        "company": str(r.get("الشركة", "")).strip(),
        "branch": str(r.get("الفرع", "")).strip(),
        "password_raw": str(r.get("كلمة المرور", "")).strip()
    }


def authenticate(email, password):
    """
    Authenticate user against the authoritative Excel file.
    - Match البريد الإلكتروني
    - Check الحالة == نشط
    - Verify password (hashed at runtime)
    """
    email = (email or "").strip().lower()
    if not email or not password:
        return None
    user = get_user_from_excel(email)
    if not user:
        return None
    if user.get("status") != "نشط":
        return None
    raw = user.get("password_raw") or ""
    if not raw:
        return None
    runtime_hash = generate_password_hash(raw)
    if not check_password_hash(runtime_hash, password):
        return None
    return user

