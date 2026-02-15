# رفع المشروع إلى GitHub

## الخطوة 1: إنشاء المستودع (مرة واحدة)

1. افتح: **https://github.com/new**
2. **Repository name:** `se_sheetsai`
3. اختر **Private** أو **Public**
4. **لا** تضف README أو .gitignore أو رخصة (المشروع جاهز)
5. اضغط **Create repository**

## الخطوة 2: الرفع من PowerShell

من مجلد المشروع نفّذ:

```powershell
cd C:\py\se_sheetsai
.\scripts\push-to-github.ps1
```

أو يدوياً:

```powershell
cd C:\py\se_sheetsai
git remote set-url origin https://github.com/hassancs44/se_sheetsai.git
git push -u origin main
```

إذا طُلب منك تسجيل الدخول، استخدم حساب **hassancs44** أو Personal Access Token بدل كلمة المرور.

## الرابط بعد الرفع

https://github.com/hassancs44/se_sheetsai
