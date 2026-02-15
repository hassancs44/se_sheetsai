# SE_SHEETSAI — تشغيل النظام الكامل من المسار C:\py\se_sheetsai
# التطبيق + OnlyOffice + Postgres تعمل من نفس المجلد، كل البيانات محليّة.

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $projectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "SE_SHEETSAI — النظام الكامل (Docker)" -ForegroundColor Cyan
Write-Host "المسار: $projectRoot" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# إنشاء المجلدات (بما فيها onlyoffice_data/certs لإصلاح خطأ OnlyOffice)
& (Join-Path $scriptDir "ensure-dirs.ps1")
if ($LASTEXITCODE -ne 0) { exit 1 }

# تشغيل الحاويات
Write-Host "`nتشغيل الحاويات..." -ForegroundColor Green
docker compose -f docker-compose.full-stack.yml up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "فشل تشغيل Docker Compose" -ForegroundColor Red
    exit 1
}

Write-Host "`nالتطبيق:    http://localhost:5000" -ForegroundColor Green
Write-Host "OnlyOffice: http://localhost:8082 (داخلي للتطبيق)" -ForegroundColor Green
Write-Host "`nلرؤية السجلات: docker compose -f docker-compose.full-stack.yml logs -f" -ForegroundColor Yellow
Write-Host "لإيقاف:       docker compose -f docker-compose.full-stack.yml down" -ForegroundColor Yellow
