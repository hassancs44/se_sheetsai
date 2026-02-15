import os
import pandas as pd
from datetime import datetime
from modules.db import get_db
from werkzeug.security import generate_password_hash
from config import BASE_DIR

EXCEL_PATH = os.path.join(BASE_DIR, "data", "database.xlsx")

def sync_users_from_excel():
    df = pd.read_excel(EXCEL_PATH)

    db = get_db()
    cur = db.cursor()

    for _, r in df.iterrows():
        username = str(r["البريد الإلكتروني"]).strip().lower()
        if not username:
            continue

        cur.execute("SELECT id FROM users WHERE username=?", (username,))
        exists = cur.fetchone()

        password = str(r["كلمة المرور"]).strip()
        password_hash = generate_password_hash(password) if password else None

        data = (
            username,
            password_hash,
            r["الاسم"],
            r["الصلاحية"],
            r["القسم"],
            r.get("الأقسام الأخرى", ""),
            r.get("الشركة", ""),
            r.get("الفرع", ""),
            r.get("apps", ""),
            1 if str(r["الحالة"]).strip() == "نشط" else 0,
            1 if str(r.get("force_reset", "")).strip() == "1" else 0,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        )

        if exists:
            cur.execute("""
                UPDATE users SET
                password=?, name=?, role=?, department=?, extra_departments=?,
                company=?, branch=?, apps=?, is_active=?, force_reset=?
                WHERE username=?
            """, (
                password_hash,
                r["الاسم"],
                r["الصلاحية"],
                r["القسم"],
                r.get("الأقسام الأخرى", ""),
                r.get("الشركة", ""),
                r.get("الفرع", ""),
                r.get("apps", ""),
                1 if str(r["الحالة"]).strip() == "نشط" else 0,
                1 if str(r.get("force_reset", "")).strip() == "1" else 0,
                username
            ))
        else:
            cur.execute("""
                INSERT INTO users
                (username,password,name,role,department,extra_departments,
                 company,branch,apps,is_active,force_reset,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, data)

    db.commit()
    db.close()

import pandas as pd
from datetime import datetime
from modules.db import get_db, use_fallback_db
from werkzeug.security import generate_password_hash

EXCEL_PATH = os.path.join(BASE_DIR, "data", "database.xlsx")

def sync_users_from_excel():
    if not os.path.exists(EXCEL_PATH):
        return
    df = pd.read_excel(EXCEL_PATH)
    try:
        db = get_db()
        cur = db.cursor()
    except Exception:
        use_fallback_db()
        db = get_db()
        cur = db.cursor()

    for _, r in df.iterrows():
        username = str(r.get("البريد الإلكتروني", "")).strip().lower()
        if not username:
            continue

        cur.execute("SELECT id FROM users WHERE username=?", (username,))
        exists = cur.fetchone()

        password = str(r.get("كلمة المرور", "")).strip()
        password_hash = generate_password_hash(password) if password else None

        data = (
            username,
            password_hash,
            r.get("الاسم", ""),
            r.get("الصلاحية", ""),
            r.get("القسم", ""),
            r.get("الأقسام الأخرى", ""),
            r.get("الشركة", ""),
            r.get("الفرع", ""),
            r.get("apps", ""),
            1 if str(r.get("الحالة", "")).strip() == "نشط" else 0,
            1 if str(r.get("force_reset", "")).strip() == "1" else 0,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        )

        if exists:
            cur.execute("""
                UPDATE users SET
                password=?, name=?, role=?, department=?, extra_departments=?,
                company=?, branch=?, apps=?, is_active=?, force_reset=?
                WHERE username=?
            """, (
                password_hash,
                r.get("الاسم", ""),
                r.get("الصلاحية", ""),
                r.get("القسم", ""),
                r.get("الأقسام الأخرى", ""),
                r.get("الشركة", ""),
                r.get("الفرع", ""),
                r.get("apps", ""),
                1 if str(r.get("الحالة", "")).strip() == "نشط" else 0,
                1 if str(r.get("force_reset", "")).strip() == "1" else 0,
                username
            ))
        else:
            cur.execute("""
                INSERT INTO users
                (username,password,name,role,department,extra_departments,
                 company,branch,apps,is_active,force_reset,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, data)

    try:
        db.commit()
    except Exception as e:
        if "disk i/o" in str(e).lower():
            db.close()
            use_fallback_db()
            db = get_db()
            cur = db.cursor()
            for _, r in df.iterrows():
                username = str(r.get("البريد الإلكتروني", "")).strip().lower()
                if not username:
                    continue

                cur.execute("SELECT id FROM users WHERE username=?", (username,))
                exists = cur.fetchone()

                password = str(r.get("كلمة المرور", "")).strip()
                password_hash = generate_password_hash(password) if password else None

                data = (
                    username,
                    password_hash,
                    r.get("الاسم", ""),
                    r.get("الصلاحية", ""),
                    r.get("القسم", ""),
                    r.get("الأقسام الأخرى", ""),
                    r.get("الشركة", ""),
                    r.get("الفرع", ""),
                    r.get("apps", ""),
                    1 if str(r.get("الحالة", "")).strip() == "نشط" else 0,
                    1 if str(r.get("force_reset", "")).strip() == "1" else 0,
                    datetime.now().strftime("%Y-%m-%d %H:%M")
                )

                if exists:
                    cur.execute("""
                        UPDATE users SET
                        password=?, name=?, role=?, department=?, extra_departments=?,
                        company=?, branch=?, apps=?, is_active=?, force_reset=?
                        WHERE username=?
                    """, (
                        password_hash,
                        r.get("الاسم", ""),
                        r.get("الصلاحية", ""),
                        r.get("القسم", ""),
                        r.get("الأقسام الأخرى", ""),
                        r.get("الشركة", ""),
                        r.get("الفرع", ""),
                        r.get("apps", ""),
                        1 if str(r.get("الحالة", "")).strip() == "نشط" else 0,
                        1 if str(r.get("force_reset", "")).strip() == "1" else 0,
                        username
                    ))
                else:
                    cur.execute("""
                        INSERT INTO users
                        (username,password,name,role,department,extra_departments,
                         company,branch,apps,is_active,force_reset,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """, data)
            db.commit()
        else:
            db.close()
            raise
    db.close()
