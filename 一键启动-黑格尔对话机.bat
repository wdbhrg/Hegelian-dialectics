@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: Try to find conda and activate it (check E:\Miniconda3 first)
if exist "E:\Miniconda3\Scripts\activate.bat" (
    call "E:\Miniconda3\Scripts\activate.bat" hegel 2>nul || call "E:\Miniconda3\Scripts\activate.bat" base 2>nul
) else if exist "%UserProfile%\miniconda3\Scripts\activate.bat" (
    call "%UserProfile%\miniconda3\Scripts\activate.bat" hegel 2>nul || call "%UserProfile%\miniconda3\Scripts\activate.bat" base 2>nul
) else if exist "%UserProfile%\anaconda3\Scripts\activate.bat" (
    call "%UserProfile%\anaconda3\Scripts\activate.bat" hegel 2>nul || call "%UserProfile%\anaconda3\Scripts\activate.bat" base 2>nul
)

:: Also try to set PATH directly if python is not found
where python >nul 2>nul
if errorlevel 1 (
    if exist "E:\Miniconda3\python.exe" (
        set "PATH=E:\Miniconda3;E:\Miniconda3\Scripts;%PATH%"
    ) else if exist "%UserProfile%\miniconda3\python.exe" (
        set "PATH=%UserProfile%\miniconda3;%UserProfile%\miniconda3\Scripts;%PATH%"
    ) else if exist "%UserProfile%\anaconda3\python.exe" (
        set "PATH=%UserProfile%\anaconda3;%UserProfile%\anaconda3\Scripts;%PATH%"
    )
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "& {& '%~dp0start-hegel-app.ps1'}"
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo.
  echo Launcher failed with code %EXITCODE%.
  pause
)
exit /b %EXITCODE%
