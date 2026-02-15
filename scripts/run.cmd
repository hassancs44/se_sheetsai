@echo off
REM SE_SHEETSAI — Auto Bootstrap Script (CMD)
REM Loads .env, starts Docker, waits for services, installs requirements, starts Flask

setlocal enabledelayedexpansion

cd /d "%~dp0\.."

echo ========================================
echo SE_SHEETSAI — Auto Bootstrap
echo ========================================

REM Load .env (basic parsing)
if exist .env (
    echo Loading .env...
    for /f "tokens=1,* delims==" %%a in (.env) do (
        set "line=%%a"
        if not "!line:~0,1!"=="#" (
            set "%%a=%%b"
        )
    )
) else (
    echo WARNING: .env file not found
)

REM Check Docker
echo.
echo Checking Docker...
docker --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker is not installed or not in PATH
    exit /b 1
)

REM Start Docker Compose
echo.
echo Starting Docker Compose...
docker compose up -d
if errorlevel 1 (
    echo ERROR: Docker Compose failed
    exit /b 1
)

REM Wait for Postgres to be healthy
echo.
echo Waiting for PostgreSQL to be healthy...
set /a waited=0
set /a maxWait=120
set postgresHealthy=0

:waitPostgres
docker inspect --format="{{.State.Health.Status}}" sheetsai_postgres >nul 2>&1
if errorlevel 1 goto checkPostgresTimeout
for /f %%i in ('docker inspect --format="{{.State.Health.Status}}" sheetsai_postgres 2^>nul') do set health=%%i
if "!health!"=="healthy" (
    set postgresHealthy=1
    goto postgresReady
)
:checkPostgresTimeout
if !waited! geq !maxWait! goto postgresTimeout
timeout /t 2 /nobreak >nul
set /a waited+=2
echo|set /p="."
goto waitPostgres

:postgresTimeout
echo.
echo ERROR: PostgreSQL did not become healthy within !maxWait! seconds
echo Check logs: docker logs sheetsai_postgres
exit /b 1

:postgresReady
echo.
echo PostgreSQL is healthy

REM Wait for Metabase to respond
echo.
echo Waiting for Metabase to respond...
set /a waited=0
set /a maxWait=180
set metabaseReady=0

:waitMetabase
curl -s http://127.0.0.1:3000/api/health >nul 2>&1
if not errorlevel 1 (
    set metabaseReady=1
    goto metabaseReady
)
if !waited! geq !maxWait! goto metabaseTimeout
timeout /t 3 /nobreak >nul
set /a waited+=3
echo|set /p="."
goto waitMetabase

:metabaseTimeout
echo.
echo WARNING: Metabase did not respond within !maxWait! seconds
echo It may still be starting. Check logs: docker logs sheetsai_metabase
goto metabaseContinue

:metabaseReady
echo.
echo Metabase is responding

:metabaseContinue
REM Install Python requirements
echo.
echo Installing Python requirements...
if exist requirements.txt (
    python -m pip install -q -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install requirements
        exit /b 1
    )
    echo Requirements installed
) else (
    echo WARNING: requirements.txt not found
)

REM Bootstrap Metabase (first-time setup + login + register Postgres DB)
if !metabaseReady! equ 1 (
    echo.
    echo Bootstrapping Metabase (setup + login + register DB)...
    python scripts\bootstrap_metabase_standalone.py
    if errorlevel 1 (
        echo ERROR: Metabase bootstrap failed
        exit /b 1
    )
    echo Metabase bootstrap complete

    echo.
    echo Configuring Metabase embedding (API)...
    python scripts\configure_metabase_embedding.py
    if errorlevel 1 (
        echo ERROR: Metabase embedding configuration failed
        exit /b 1
    )
    echo Metabase embedding configured
)

REM Start Flask
echo.
echo ========================================
echo Starting Flask application...
echo ========================================
echo Flask will run at: http://127.0.0.1:5000
echo Metabase will run at: http://127.0.0.1:3000
echo.
echo Press Ctrl+C to stop
echo.

python app.py
