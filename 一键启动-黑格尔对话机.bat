@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo   Hegel Dialogue App - One Click Full Stack Launcher
echo ============================================================
echo.

set "PYTHON_EXE="
set "PYTHON_ARGS="
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
    set "PYTHON_ARGS="
    set "PATH=%~dp0.venv\Scripts;%PATH%"
)
if not defined PYTHON_EXE (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=python"
        set "PYTHON_ARGS="
    )
)
if not defined PYTHON_EXE (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -c "import sys" >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON_EXE=py"
            set "PYTHON_ARGS=-3"
        )
    )
)
if not defined PYTHON_EXE (
    for %%P in (
        "E:\Project Tools\Miniconda3\python.exe"
        "%USERPROFILE%\Miniconda3\python.exe"
        "%LOCALAPPDATA%\Miniconda3\python.exe"
        "C:\ProgramData\Miniconda3\python.exe"
        "C:\ProgramData\miniconda3\python.exe"
        "C:\Program Files\Python312\python.exe"
        "C:\Program Files\Python311\python.exe"
    ) do (
        if exist %%~P (
            set "PYTHON_EXE=%%~P"
            set "PYTHON_ARGS="
            goto :python_found
        )
    )
)

if not defined PYTHON_EXE (
    echo [FAILED] Python not found.
    echo Try one of these:
    echo   - Install Python and check "Add python.exe to PATH"
    echo   - Install Miniconda (detected path example: E:\Project Tools\Miniconda3)
    echo   - Or create project venv: python -m venv .venv
    pause
    exit /b 1
)

:python_found
echo [INFO] Using Python: %PYTHON_EXE% %PYTHON_ARGS%
"%PYTHON_EXE%" %PYTHON_ARGS% --version >nul 2>nul
if errorlevel 1 (
    echo [FAILED] Python is not runnable: %PYTHON_EXE% %PYTHON_ARGS%
    pause
    exit /b 1
)

echo [1/4] Checking dependencies...
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import streamlit,fastapi,uvicorn" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing dependencies from requirements.txt ...
    "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [FAILED] Dependency installation failed.
        pause
        exit /b 1
    )
)

set "API_PORT=8000"
set "WEB_PORT=8501"

echo [2/4] Starting FastAPI on http://127.0.0.1:%API_PORT% ...
start "Hegel-FastAPI" cmd /c ""%PYTHON_EXE%" %PYTHON_ARGS% -m uvicorn fastapi_app:app --host 127.0.0.1 --port %API_PORT%"

echo [3/4] Opening browser...
timeout /t 5 /nobreak >nul
start "" "http://localhost:%WEB_PORT%"

echo [4/4] Starting Streamlit on http://localhost:%WEB_PORT% ...
echo Keep this window open while using the app.
echo If browser does not open automatically, open: http://localhost:%WEB_PORT%
echo.
"%PYTHON_EXE%" %PYTHON_ARGS% -m streamlit run app_streamlit.py --server.headless true --server.port %WEB_PORT%
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
    echo.
    echo [FAILED] Streamlit exited with code %EXITCODE%.
    pause
)
exit /b %EXITCODE%
