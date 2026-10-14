@echo off
rem One-click local start for the MarketPulse dashboard (loopback only).
chcp 65001 >nul
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
  echo [setup] venv not found - creating it and installing dependencies...
  python -m venv venv || (echo [error] failed to create venv - is python on PATH? & pause & exit /b 1)
  venv\Scripts\python.exe -m pip install -r requirements.txt || (echo [error] pip install failed & pause & exit /b 1)
)

venv\Scripts\python.exe start_local.py %*
if errorlevel 1 pause
