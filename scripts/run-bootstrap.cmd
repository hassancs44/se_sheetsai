@echo off
REM Launcher for run.ps1 — bypasses PowerShell execution policy
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
