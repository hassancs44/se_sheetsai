# رفع مشروع سفنز درايف (se_sheetsai) إلى GitHub
# المستخدم: hassancs44 حسب الصور

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..")
Set-Location $projectRoot

$repoName = "se_sheetsai"
$githubUser = "hassancs44"
$repoUrl = "https://github.com/$githubUser/$repoName.git"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "رفع المشروع إلى GitHub" -ForegroundColor Cyan
Write-Host "المسار: $projectRoot" -ForegroundColor Gray
Write-Host "========================================" -ForegroundColor Cyan

# 1) التحقق من Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "خطأ: Git غير مثبت أو غير موجود في PATH" -ForegroundColor Red
    exit 1
}

# 2) حالة المستودع
$currentRemote = git remote get-url origin 2>$null
if (-not $currentRemote) {
    Write-Host "إضافة الريموت: $repoUrl" -ForegroundColor Green
    git remote add origin $repoUrl
} elseif ($currentRemote -ne $repoUrl) {
    Write-Host "تحديث الريموت إلى: $repoUrl" -ForegroundColor Yellow
    git remote set-url origin $repoUrl
}

# 3) التأكد من وجود التعديلات المضافة وعمل commit إن لزم
$status = git status --porcelain
if ($status) {
    Write-Host "`nيوجد تغييرات غير محفوظة. جاري الإضافة والـ commit..." -ForegroundColor Yellow
    git add -A
    git commit -m "Update project for GitHub"
}

# 4) إنشاء المستودع على GitHub (يحتاج مستودعاً موجوداً أو GitHub CLI)
Write-Host "`n--- إنشاء المستودع على GitHub ---" -ForegroundColor Cyan
Write-Host "إذا ظهرت رسالة 'Repository not found' فعليك إنشاء المستودع يدوياً:" -ForegroundColor Yellow
Write-Host "  1. افتح: https://github.com/new" -ForegroundColor White
Write-Host "  2. اسم المستودع: $repoName" -ForegroundColor White
Write-Host "  3. اختر Private أو Public ثم Create repository" -ForegroundColor White
Write-Host "  4. لا تضف README أو .gitignore (المشروع جاهز)" -ForegroundColor White
Write-Host "  5. شغّل هذا السكربت مرة أخرى لتنفيذ الـ push" -ForegroundColor White
Write-Host ""

# 5) الرفع
Write-Host "جاري الرفع إلى origin main..." -ForegroundColor Green
git push -u origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nتم رفع المشروع بنجاح إلى:" -ForegroundColor Green
    Write-Host "  https://github.com/$githubUser/$repoName" -ForegroundColor Cyan
} else {
    Write-Host "`nفشل الرفع. إن لم يكن المستودع موجوداً، أنشئه من الرابط أعلاه ثم شغّل:" -ForegroundColor Red
    Write-Host "  .\scripts\push-to-github.ps1" -ForegroundColor Yellow
    exit 1
}
