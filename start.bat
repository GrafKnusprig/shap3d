@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys, pygame; raise SystemExit(sys.version_info[:2] != (3, 12))" >nul 2>&1
    if errorlevel 1 call "%~dp0install.bat"
) else (
    echo First-time setup is needed. Starting install.bat...
    call "%~dp0install.bat"
)
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" "%~dp0shap3d.py"
if errorlevel 1 (
    echo.
    echo The game stopped because of an error.
    pause
)
