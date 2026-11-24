@echo off
setlocal
cd /d "%~dp0"

echo [*] Registering GameRadarDaily Windows scheduled task at 03:00 daily...
schtasks /create /tn "GameRadarDaily" /tr "\"%~dp0run.bat\" daily" /sc daily /st 03:00 /f

if %errorlevel% equ 0 (
    echo ====================================================================
    echo SUCCESS: GameRadarDaily task registered to run every day at 03:00.
    echo Note: The task will execute only when this PC is on and you are logged in.
    echo To remove this schedule at any time, run schedule_remove.bat.
    echo ====================================================================
) else (
    echo ====================================================================
    echo ERROR: Failed to register scheduled task.
    echo ====================================================================
)
pause
