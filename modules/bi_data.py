# SE_SHEETSAI — BI demo data for Metabase (SQLite)
# Creates and seeds bi_sales_demo for charts in Metabase.
from datetime import datetime, timedelta
import random
from modules.db import get_db


def ensure_bi_sales_demo():
    """Create bi_sales_demo table if missing and seed with 30+ rows if empty."""
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM bi_sales_demo")
    n = cur.fetchone()[0]
    if n >= 30:
        db.close()
        return
    branches = ["الرياض", "جدة", "الدمام", "مكة", "المدينة"]
    departments = ["مبيعات", "عمليات", "موارد بشرية", "مالية", "تسويق"]
    categories = ["منتجات", "خدمات", "اشتراكات", "صيانة"]
    base = datetime.now() - timedelta(days=180)
    for i in range(35):
        sale_date = (base + timedelta(days=random.randint(0, 180))).strftime("%Y-%m-%d")
        branch = random.choice(branches)
        department = random.choice(departments)
        amount = round(random.uniform(500, 50000), 2)
        category = random.choice(categories)
        cur.execute(
            """INSERT INTO bi_sales_demo (sale_date, branch, department, amount, category)
               VALUES (?, ?, ?, ?, ?)""",
            (sale_date, branch, department, amount, category),
        )
    db.commit()
    db.close()
