# سفنز درايف — SE SheetsAI

نظام إدارة الملفات والمستندات مع تحرير إكسل عبر OnlyOffice.

## التشغيل المحلي (النظام الكامل من نفس المسار)

```powershell
cd C:\py\se_sheetsai
.\scripts\ensure-dirs.ps1
docker compose -f docker-compose.full-stack.yml up -d
```

التطبيق: http://localhost:5000

## المتطلبات

- Docker Desktop
- Python 3.11+ (للتشغيل بدون Docker)

## هيكل المشروع

- `app.py` — تطبيق Flask الرئيسي
- `modules/` — الوحدات (الملفات، الصلاحيات، OnlyOffice، BI، إلخ)
- `templates/` — قوالب الواجهات
- `static/` — الملفات الثابتة والشعار

راجع `RUN-FULL-STACK.md` لتشغيل النظام الكامل من المسار المحلي.
