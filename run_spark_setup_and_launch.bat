@echo off
setlocal

set "REPO_ROOT=%~dp0"
set "POWERSHELL_SCRIPT=%REPO_ROOT%run_spark_setup_and_launch.ps1"

if not exist "%POWERSHELL_SCRIPT%" (
    echo Could not find "%POWERSHELL_SCRIPT%"
    pause
    exit /b 1
)

cd /d "%REPO_ROOT%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%POWERSHELL_SCRIPT%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Setup failed with exit code %EXIT_CODE%.
    pause
    exit /b %EXIT_CODE%
)

echo.
echo Setup completed.
pause
exit /b 0
