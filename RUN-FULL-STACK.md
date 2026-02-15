# تشغيل النظام الكامل من المسار C:\py\se_sheetsai

المشروع والتطبيق وOnlyOffice وقاعدة البيانات تعمل كلها من نفس المسار. كل البيانات تُحفظ داخل مجلدات المشروع.

## المتطلبات

- Docker Desktop (مثبت ويعمل)
- PowerShell

## الخطوات

### 1) إنشاء المجلدات (مرة واحدة)

يُنشئ المجلدات المطلوبة ويصلح خطأ OnlyOffice:  
`find: '/var/www/onlyoffice/Data/certs': No such file or directory`  
بإنشاء مجلد `onlyoffice_data/certs`.

```powershell
cd C:\py\se_sheetsai
.\scripts\ensure-dirs.ps1
```

### 2) تشغيل النظام

```powershell
docker compose -f docker-compose.full-stack.yml up -d
```

أو باستخدام السكربت (ينفذ ensure-dirs ثم الـ compose):

```powershell
.\scripts\run-full-stack.ps1
```

### 3) الوصول

| الخدمة    | الرابط                |
|----------|------------------------|
| التطبيق  | http://localhost:5000  |
| OnlyOffice | http://localhost:8082 (للاستخدام الداخلي من التطبيق) |

## هيكل المجلدات تحت C:\py\se_sheetsai

بعد التشغيل ستجد:

- `state/`        — قاعدة البيانات وملفات الحالة
- `sheets/`       — ملفات الإكسل
- `uploads/`      — الملفات المرفوعة
- `versions/`     — نسخ الملفات
- `archive/`      — الأرشيف
- `logs/`         — سجلات التطبيق
- `data/`         — بيانات إضافية
- `postgres_data/` — بيانات PostgreSQL
- `onlyoffice_data/` — بيانات OnlyOffice (بما فيها `certs/` لتفادي خطأ الشهادات)
- `onlyoffice_logs/` — سجلات OnlyOffice

## أوامر مفيدة

```powershell
# عرض السجلات
docker compose -f docker-compose.full-stack.yml logs -f

# إيقاف كل الخدمات
docker compose -f docker-compose.full-stack.yml down

# إعادة البناء بعد تعديل الكود
docker compose -f docker-compose.full-stack.yml up -d --build
```

## ملف البيئة

انسخ `.env.example` إلى `.env` وعدّل إن احتجت:

```powershell
copy .env.example .env
```

عند التشغيل بـ `docker-compose.full-stack.yml`، **OnlyOffice إجباري** ويُشغّل من نفس السيرفر:

- `BASE_URL=http://app:5000` (للاستدعاء من OnlyOffice)
- `ONLYOFFICE_SERVER=http://onlyoffice:80`
- `ONLYOFFICE_REQUIRED=true` — التطبيق لا يبدأ إلا بعد جاهزية خادم OnlyOffice

لا حاجة لتغييرها في `.env` للتشغيل المحلي الكامل.
