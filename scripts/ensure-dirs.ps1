# SE_SHEETSAI — إنشاء كل المجلدات المطلوبة تحت مسار المشروع
# يشغّل قبل: docker compose -f docker-compose.full-stack.yml up -d
# المسار: C:\py\se_sheetsai (أو أي مسار المشروع)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptDir "..")

Set-Location $projectRoot

$dirs = @(
    "state",
    "sheets",
    "uploads",
    "versions",
    "archive",
    "logs",
    "data",
    "postgres_data",
    "onlyoffice_data",
    "onlyoffice_data\certs",
    "onlyoffice_logs"
)

Write-Host "المسار: $projectRoot" -ForegroundColor Cyan
Write-Host "إنشاء المجلدات المطلوبة..." -ForegroundColor Green

foreach ($d in $dirs) {
    $fullPath = Join-Path $projectRoot $d
    if (-not (Test-Path $fullPath)) {
        New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
        Write-Host "  + $d" -ForegroundColor Green
    }
}

Write-Host "تم. يمكنك تشغيل: docker compose -f docker-compose.full-stack.yml up -d" -ForegroundColor Cyan
