@echo off
setlocal

echo [*] Removing GameRadarDaily Windows scheduled task...
schtasks /delete /tn "GameRadarDaily" /f

if %errorlevel% equ 0 (
    echo ====================================================================
    echo SUCCESS: GameRadarDaily task has been removed from Windows Scheduler.
    echo ====================================================================
) else (
    echo ====================================================================
    echo NOTICE: GameRadarDaily task was not found or already deleted.
    echo ====================================================================
)
pause
