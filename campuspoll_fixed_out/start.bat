@echo off
title CampusPoll - Starting...
color 0A

echo.
echo  ==========================================
echo   CampusPoll - Student Election Platform
echo  ==========================================
echo.

:: ── Check Python ──────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python is not installed or not in PATH.
    echo  Download it from https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  [OK] Python %PYVER% detected.

:: ── Create virtual environment if missing ─────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo  [SETUP] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo  [SETUP] Virtual environment created.
)

:: ── Activate virtual environment ──────────────────────────────
call venv\Scripts\activate.bat

:: ── Upgrade pip first (avoids many build errors) ──────────────
echo  [SETUP] Upgrading pip...
python -m pip install --upgrade pip --quiet

:: ── Install / update dependencies ─────────────────────────────
echo  [SETUP] Installing dependencies (first run may take a minute)...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo  [ERROR] Failed to install some dependencies.
    echo  Try running this manually to see details:
    echo.
    echo    venv\Scripts\activate
    echo    pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
echo  [OK] Dependencies installed.

:: ── FIX: Remove eventlet on Windows (causes SocketIO crash in debug mode) ──
echo  [FIX] Ensuring eventlet is not installed (incompatible with Windows debug mode)...
pip uninstall eventlet -y --quiet 2>nul
echo  [OK] eventlet removed (app uses threading mode instead).

:: ── Copy .env if missing ──────────────────────────────────────
if not exist ".env" (
    if exist ".env.example" (
        echo  [SETUP] Creating .env from .env.example...
        copy ".env.example" ".env" >nul
        echo  [INFO]  .env created. Edit it to change ADMIN_PASSWORD and SECRET_KEY.
    ) else (
        echo  [WARN]  No .env file found. App will use defaults.
    )
)

:: ── Start the app ─────────────────────────────────────────────
echo.
echo  ==========================================
echo   CampusPoll is running!
echo   Open: http://localhost:5000
echo   Stop: Press Ctrl+C
echo  ==========================================
echo.

python run.py

:: ── If app stops, pause so user can read any error ────────────
echo.
echo  [STOPPED] CampusPoll has stopped.
pause
