# رفع مشروع سفنز درايف إلى GitHub
# التشغيل: بعد إنشاء المستودع على GitHub (اسم المستودع: se_sheetsai)
# الحساب من الصور: hassancs44

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..")
Set-Location $projectRoot

$remote = "https://github.com/hassancs44/se_sheetsai.git"
$branch = "main"

Write-Host "التحقق من Git..." -ForegroundColor Cyan
if (-not (Test-Path ".git")) {
    Write-Host "المجلد ليس مستودع Git. تشغيل git init أولاً." -ForegroundColor Yellow
    git init
    git branch -M main
}

$rem = git remote get-url origin 2>$null
if (-not $rem) {
    Write-Host "إضافة المستودع البعيد: $remote" -ForegroundColor Green
    git remote add origin $remote
} else {
    Write-Host "المستودع البعيد موجود: $rem" -ForegroundColor Green
}

Write-Host "رفع الفرع main إلى GitHub..." -ForegroundColor Cyan
git push -u origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host "تم الرفع بنجاح." -ForegroundColor Green
    Write-Host "الرابط: https://github.com/hassancs44/se_sheetsai" -ForegroundColor Green
} else {
    Write-Host "فشل الرفع. تأكد من:" -ForegroundColor Red
    Write-Host "  1. إنشاء المستودع على GitHub: https://github.com/new" -ForegroundColor Yellow
    Write-Host "     الاسم: se_sheetsai (بدون تهيئة README أو .gitignore)" -ForegroundColor Yellow
    Write-Host "  2. تسجيل الدخول في Git (Git Credential Manager أو Personal Access Token)" -ForegroundColor Yellow
    exit 1
}
