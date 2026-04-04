@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=python"

if exist "%ROOT%.venv\Scripts\python.exe" (
    set "PYTHON=%ROOT%.venv\Scripts\python.exe"
)

"%PYTHON%" "%ROOT%watch_pico_cdc_debug.py" %*
set "EXITCODE=%ERRORLEVEL%"

echo.
pause
exit /b %EXITCODE%
