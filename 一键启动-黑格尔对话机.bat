@echo off
setlocal EnableExtensions
cd /d "%~dp0"

:: Project root = this script's folder (moving the folder keeps paths valid).
:: If you use a project-local venv, prepending it helps when conda is not on PATH.
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PATH=%~dp0.venv\Scripts;%PATH%"
)

:: Detection of conda / system Python is done in start-hegel-app.ps1 (no fixed drive letters).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-hegel-app.ps1"
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo.
  echo Launcher failed with code %EXITCODE%.
  pause
)
exit /b %EXITCODE%
