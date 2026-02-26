@echo off
title EarnView Runner
echo ==========================================
echo       EarnView Opportunity Detector
echo ==========================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Please install Python 3.10+
    pause
    exit /b
)

:: 2. Create/Activate Venv (Optional but good practice)
if not exist "venv" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
)

:: Activate logic
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

:: 3. Install Requirements (Fast check)
echo [INFO] Checking dependencies...
pip install -q -r requirements.txt
:: Make sure psutil/uvicorn are there for dev.py
pip install -q psutil uvicorn fastapi

:: 4. Run Server
echo [INFO] Starting Server...
python dev.py

pause
