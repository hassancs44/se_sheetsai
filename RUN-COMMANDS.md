# أوامر التشغيل النهائية — OnlyOffice إجباري

تشغيل النظام الكامل (التطبيق + OnlyOffice + Postgres) من السيرفر بشكل نهائي.

---

## 1) مرة واحدة: إنشاء المجلدات

من **PowerShell** في مجلد المشروع:

```powershell
cd C:\py\se_sheetsai
.\scripts\ensure-dirs.ps1
```

---

## 2) تشغيل الـ Stack

```powershell
cd C:\py\se_sheetsai
docker compose -f docker-compose.full-stack.yml up -d
```

انتظر حتى تظهر رسالة أن الحاويات تعمل. المرة الأولى قد تستغرق دقائق (تحميل صورة OnlyOffice وبناء التطبيق).

---

## 3) التحقق

```powershell
docker compose -f docker-compose.full-stack.yml ps
```

يجب أن ترى ثلاث خدمات: **app**، **onlyoffice**، **postgres** بحالة **running**.

| الخدمة   | الرابط (من المتصفح)        |
|----------|----------------------------|
| التطبيق  | http://localhost:5000      |
| OnlyOffice | http://localhost:8083 (للاستخدام الداخلي من التطبيق) |

---

## 4) إيقاف التشغيل

```powershell
cd C:\py\se_sheetsai
docker compose -f docker-compose.full-stack.yml down
```

---

## 5) إعادة البناء بعد تعديل الكود

```powershell
cd C:\py\se_sheetsai
docker compose -f docker-compose.full-stack.yml up -d --build
```

---

## إذا كان المنفذ 8083 مستخدماً

عدّل في `docker-compose.full-stack.yml` سطر OnlyOffice من `"8083:80"` إلى منفذ آخر (مثلاً `"8084:80"`). التطبيق يتصل بـ OnlyOffice داخلياً عبر `http://onlyoffice:80` ولا يتأثر بتغيير المنفذ على الجهاز.

## ملف البيئة

تأكد من وجود `.env` (انسخ من `.env.example` إن لم يكن موجوداً) وأن `ONLYOFFICE_JWT_SECRET` مضبوط. في الـ full-stack لا حاجة لضبط `ONLYOFFICE_SERVER` يدوياً — يُضبط تلقائياً داخل Docker.
