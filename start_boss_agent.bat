@echo off
setlocal

cd /d "%~dp0"

if not exist "%~dp0scripts\start_boss_agent.ps1" (
    echo [BossAgent] Missing scripts\start_boss_agent.ps1
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_boss_agent.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [BossAgent] Launcher exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
