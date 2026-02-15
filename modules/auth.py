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
    email = (email or "").strip().lower()
    # عند عدم وجود Excel (مثل Render): إرجاع بيانات المدير من متغيرات البيئة إن طُلب بريده
    if not os.path.exists(EXCEL_PATH):
        admin_email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
        if admin_email and email == admin_email:
            return {
                "email": email,
                "name": os.environ.get("ADMIN_NAME", "مدير"),
                "role": os.environ.get("ADMIN_ROLE", "admin"),
                "department": os.environ.get("ADMIN_DEPARTMENT", ""),
                "status": "نشط",
                "force_reset": 0,
                "extra_departments": [],
                "apps": [],
                "company": "",
                "branch": "",
            }
        return None
    df = pd.read_excel(EXCEL_PATH)
    if "البريد الإلكتروني" not in df.columns:
        return None
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


def _env_admin_user(email, password):
    """
    مصادقة احتياطية عند عدم وجود ملف Excel (مثل النشر على Render).
    استخدم متغيرات البيئة: ADMIN_EMAIL و ADMIN_PASSWORD
    """
    admin_email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD") or ""
    if not admin_email or not admin_password:
        return None
    if email != admin_email or password != admin_password:
        return None
    return {
        "email": email,
        "name": os.environ.get("ADMIN_NAME", "مدير"),
        "role": os.environ.get("ADMIN_ROLE", "admin"),
        "department": os.environ.get("ADMIN_DEPARTMENT", ""),
        "status": "نشط",
        "force_reset": 0,
        "extra_departments": [],
        "apps": [],
        "company": "",
        "branch": "",
    }


def authenticate(email, password):
    """
    Authenticate user against the authoritative Excel file.
    - Match البريد الإلكتروني
    - Check الحالة == نشط
    - Verify password (hashed at runtime)
    - إذا لم يوجد ملف Excel: مصادقة احتياطية عبر ADMIN_EMAIL و ADMIN_PASSWORD (للنشر على Render)
    """
    email = (email or "").strip().lower()
    if not email or not password:
        return None
    user = get_user_from_excel(email)
    if not user:
        # عند عدم وجود data/database.xlsx (مثل Render): استخدم مدير من متغيرات البيئة
        return _env_admin_user(email, password)
    if user.get("status") != "نشط":
        return None
    raw = user.get("password_raw") or ""
    if not raw:
        return None
    runtime_hash = generate_password_hash(raw)
    if not check_password_hash(runtime_hash, password):
        return None
    return user

