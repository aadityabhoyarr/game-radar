@echo off
setlocal enabledelayedexpansion

:: Game Radar Windows Launch Script
cd /d "%~dp0"
set PYTHONUTF8=1
chcp 65001 >nul

:: Argument parsing
set MODE=standard
set HEADLESS=0

if /i "%~1"=="full" (
    set MODE=full
) else if /i "%~1"=="daily" (
    set MODE=daily
    set HEADLESS=1
) else if /i "%~1"=="report" (
    set MODE=report
) else if /i "%~1"=="dashboard" (
    set MODE=dashboard
) else if /i "%~1"=="selftest" (
    set MODE=selftest
)

:: Locate Python
set PYTHON_CMD=
py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py -3
) else (
    python --version >nul 2>&1
    if %errorlevel% equ 0 (
        set PYTHON_CMD=python
    )
)

if "%PYTHON_CMD%"=="" (
    echo ====================================================================
    echo ERROR: Python is not installed or not in PATH!
    echo ====================================================================
    echo Please follow these steps to install Python:
    echo 1. Download Python 3.10 or newer from: https://www.python.org/downloads/
    echo 2. Run the installer and MUST CHECK: "Add Python to PATH"
    echo 3. Re-run this script after installation.
    echo ====================================================================
    pause
    exit /b 1
)

:: Check Python version (>= 3.10)
%PYTHON_CMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo ====================================================================
    echo ERROR: Python 3.10 or newer is required!
    echo ====================================================================
    echo Your installed Python is older than 3.10.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo ====================================================================
    pause
    exit /b 1
)

:: Initialize .venv if missing
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [*] Creating virtual environment .venv...
    %PYTHON_CMD% -m venv "%~dp0.venv"
    if !errorlevel! neq 0 (
        echo ERROR: Failed to create virtual environment!
        pause
        exit /b 1
    )
)

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "VENV_PIP=%~dp0.venv\Scripts\pip.exe"

:: Install or update requirements only if changed
set NEED_PIP=0
if not exist "%~dp0.venv\.req_stamp" (
    set NEED_PIP=1
) else (
    fc /b "%~dp0requirements.txt" "%~dp0.venv\.req_stamp" >nul 2>&1
    if %errorlevel% neq 0 set NEED_PIP=1
)

if %NEED_PIP% equ 1 (
    echo [*] Installing / Updating dependencies from requirements.txt...
    "%VENV_PIP%" install -r "%~dp0requirements.txt"
    if %errorlevel% neq 0 (
        echo ERROR: Failed to install requirements!
        pause
        exit /b 1
    )
    copy /y "%~dp0requirements.txt" "%~dp0.venv\.req_stamp" >nul
)

:: Direct sub-commands
if "%MODE%"=="report" (
    "%VENV_PYTHON%" -m radar report
    exit /b %errorlevel%
)

if "%MODE%"=="dashboard" (
    echo [*] Starting Game Radar Dashboard...
    "%VENV_PYTHON%" -m radar dashboard
    exit /b %errorlevel%
)

if "%MODE%"=="selftest" (
    echo [*] Running Game Radar Self-Test Suite...
    "%VENV_PYTHON%" -m radar selftest
    exit /b %errorlevel%
)

:: Standard / Full / Daily execution
if not exist "%~dp0logs" mkdir "%~dp0logs"
set "LOG_TS="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd_HHmm'"`) do set "LOG_TS=%%I"
if "!LOG_TS!"=="" set "LOG_TS=run_active"
set "LOG_FILE=%~dp0logs\run_!LOG_TS!.log"

echo [*] Starting Game Radar Pipeline in %MODE% mode...
echo [*] Logging to: !LOG_FILE!

"%VENV_PYTHON%" -m radar run --mode %MODE% --log-file "!LOG_FILE!"
set PIPELINE_EXIT=%errorlevel%

if %PIPELINE_EXIT% neq 0 (
    echo [!] Pipeline terminated with error code %PIPELINE_EXIT%.
    if %HEADLESS% equ 0 pause
    exit /b %PIPELINE_EXIT%
)

:: Post-run actions for interactive runs
if %HEADLESS% equ 0 (
    echo [*] Launching Dashboard server in background...
    start "" "%VENV_PYTHON%" -m radar dashboard
    
    timeout /t 2 >nul
    if exist "%~dp0reports\latest.html" (
        start "" "%~dp0reports\latest.html"
    )
    start "" "http://127.0.0.1:8765"

    echo ====================================================================
    echo Game Radar scan completed successfully!
    echo Reports available in: %~dp0reports\
    echo - HTML: %~dp0reports\latest.html
    echo - TXT:  %~dp0reports\latest.txt
    echo - CSV:  %~dp0reports\latest.csv
    echo ====================================================================
    pause
)

exit /b 0
