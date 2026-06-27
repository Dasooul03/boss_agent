@echo off
setlocal

cd /d "%~dp0"

if not exist "%~dp0scripts\start_job_seeker.ps1" (
    echo [Job Seeker] Missing scripts\start_job_seeker.ps1
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_job_seeker.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [Job Seeker] Launcher exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
