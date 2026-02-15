# SE_SHEETSAI — Auto Bootstrap Script (PowerShell)
# Loads .env, starts Docker, waits for services, installs requirements, starts Flask

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "SE_SHEETSAI — Auto Bootstrap" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Load .env
if (Test-Path ".env") {
    Write-Host "Loading .env..." -ForegroundColor Green
    Get-Content .env | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
} else {
    Write-Host "WARNING: .env file not found" -ForegroundColor Yellow
}

# Check Docker
Write-Host "`nChecking Docker..." -ForegroundColor Green
try {
    docker --version | Out-Null
} catch {
    Write-Host "ERROR: Docker is not installed or not in PATH" -ForegroundColor Red
    exit 1
}

# Start Docker Compose
Write-Host "`nStarting Docker Compose..." -ForegroundColor Green
docker compose up -d

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker Compose failed" -ForegroundColor Red
    exit 1
}

# Wait for Postgres to be healthy
Write-Host "`nWaiting for PostgreSQL to be healthy..." -ForegroundColor Green
$maxWait = 120
$waited = 0
$postgresHealthy = $false

while ($waited -lt $maxWait) {
    $health = docker inspect --format='{{.State.Health.Status}}' sheetsai_postgres 2>$null
    if ($health -eq "healthy") {
        $postgresHealthy = $true
        break
    }
    Start-Sleep -Seconds 2
    $waited += 2
    Write-Host "." -NoNewline -ForegroundColor Gray
}

Write-Host ""

if (-not $postgresHealthy) {
    Write-Host "ERROR: PostgreSQL did not become healthy within $maxWait seconds" -ForegroundColor Red
    Write-Host "Check logs: docker logs sheetsai_postgres" -ForegroundColor Yellow
    exit 1
}

Write-Host "PostgreSQL is healthy" -ForegroundColor Green

# Wait for Metabase to respond
Write-Host "`nWaiting for Metabase to respond..." -ForegroundColor Green
$maxWait = 180
$waited = 0
$metabaseReady = $false

while ($waited -lt $maxWait) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:3000/api/health" -TimeoutSec 5 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            $metabaseReady = $true
            break
        }
    } catch {
        # Continue waiting
    }
    Start-Sleep -Seconds 3
    $waited += 3
    Write-Host "." -NoNewline -ForegroundColor Gray
}

Write-Host ""

if (-not $metabaseReady) {
    Write-Host "WARNING: Metabase did not respond within $maxWait seconds" -ForegroundColor Yellow
    Write-Host "It may still be starting. Check logs: docker logs sheetsai_metabase" -ForegroundColor Yellow
} else {
    Write-Host "Metabase is responding" -ForegroundColor Green
}

# Install Python requirements
Write-Host "`nInstalling Python requirements..." -ForegroundColor Green
if (Test-Path "requirements.txt") {
    python -m pip install -q -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to install requirements" -ForegroundColor Red
        exit 1
    }
    Write-Host "Requirements installed" -ForegroundColor Green
} else {
    Write-Host "WARNING: requirements.txt not found" -ForegroundColor Yellow
}

# Bootstrap Metabase (first-time setup + login + register Postgres DB)
if ($metabaseReady) {
    Write-Host "`nBootstrapping Metabase (setup + login + register DB)..." -ForegroundColor Green
    python scripts/bootstrap_metabase_standalone.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Metabase bootstrap failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "Metabase bootstrap complete" -ForegroundColor Green

    # Configure embedding (enable embedding, signed embedding, set secret) via API
    Write-Host "`nConfiguring Metabase embedding (API)..." -ForegroundColor Green
    python scripts/configure_metabase_embedding.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Metabase embedding configuration failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "Metabase embedding configured" -ForegroundColor Green
}

# Verify PostgreSQL connection
Write-Host "`nVerifying PostgreSQL connection..." -ForegroundColor Green
try {
    $env:PGPASSWORD = "strongpassword"
    $result = & psql -h localhost -p 5433 -U sheetsai_user -d sheetsai_bi -c "SELECT 1;" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "PostgreSQL connection verified" -ForegroundColor Green
    } else {
        Write-Host "WARNING: PostgreSQL connection test failed" -ForegroundColor Yellow
    }
} catch {
    Write-Host "WARNING: psql not available, skipping connection test" -ForegroundColor Yellow
}

# Start Flask
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Starting Flask application..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Flask will run at: http://127.0.0.1:5000" -ForegroundColor Green
Write-Host "Metabase will run at: http://127.0.0.1:3000" -ForegroundColor Green
Write-Host "`nPress Ctrl+C to stop" -ForegroundColor Yellow
Write-Host ""

python app.py
