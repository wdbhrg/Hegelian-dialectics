@echo off
:: Only stages the three launcher files below — never data/, uploads/, caches, or IDE history.
setlocal EnableExtensions
cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
  if exist "%ProgramFiles%\Git\cmd\git.exe" set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
)
where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] git not found. Install Git for Windows and ensure it is on PATH, or reinstall with "Git from the command line".
  pause
  exit /b 1
)

git status
echo.
git add -- "一键启动-黑格尔对话机.bat" "start-hegel-app.ps1" "push-launcher-updates.bat"
if errorlevel 1 (
  echo [ERROR] git add failed.
  pause
  exit /b 1
)

git diff --cached --quiet
if not errorlevel 1 (
  echo Nothing new to commit for launcher files.
  git status
  pause
  exit /b 0
)

git commit -m "Launcher: portable paths, Conda discovery, Windows Python checks"
if errorlevel 1 (
  echo [ERROR] git commit failed.
  pause
  exit /b 1
)

git push origin main
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
  echo.
  echo [ERROR] git push failed ^(code %EC%^). Check GitHub auth ^(PAT / SSH^).
  pause
  exit /b %EC%
)

echo.
echo Push completed.
pause
exit /b 0
