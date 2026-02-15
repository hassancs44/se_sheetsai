# سفنز درايف — Sevens Drive

نظام إدارة الملفات والمستندات الداخلي مع تحرير عبر OnlyOffice، نسخ، مشاركة، وحوكمة.

## التشغيل المحلي (النظام الكامل من نفس المسار)

```powershell
cd C:\py\se_sheetsai
.\scripts\ensure-dirs.ps1
docker compose -f docker-compose.full-stack.yml up -d
```

التطبيق: http://localhost:5000

راجع [RUN-FULL-STACK.md](RUN-FULL-STACK.md) للتفاصيل.

## المتطلبات

- Python 3.11+
- Docker (للمحرر OnlyOffice والتشغيل الكامل)
- ملف `.env` (انظر `.env.example`)

## رفع المشروع إلى GitHub

1. أنشئ مستودعاً جديداً على GitHub: https://github.com/new  
   الاسم: `se_sheetsai` — **لا تضف** README أو .gitignore (المشروع جاهز للرفع).

2. نفّذ من PowerShell:
```powershell
cd C:\py\se_sheetsai
.\scripts\push-to-github.ps1
```

أو يدوياً:
```powershell
git push -u origin main
```

(تسجيل الدخول عبر Git Credential Manager أو Personal Access Token عند الطلب.)
