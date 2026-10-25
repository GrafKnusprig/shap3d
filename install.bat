@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON_CMD="
set "PYTHON_INSTALLER=%TEMP%\python-3.12.10-amd64.exe"
set "PYTHON_FALLBACK=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

echo Checking for Python 3.12...
py -3.12 -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3.12"

if not defined PYTHON_CMD (
    python -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD if exist "%PYTHON_FALLBACK%" (
    "%PYTHON_FALLBACK%" -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD="%PYTHON_FALLBACK%""
)

if defined PYTHON_CMD goto python_ready

echo Python 3.12 was not found. Trying to install it with winget...
where winget >nul 2>&1
if not errorlevel 1 (
    winget install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
    if exist "%PYTHON_FALLBACK%" (
        "%PYTHON_FALLBACK%" -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD="%PYTHON_FALLBACK%""
    )
    if not defined PYTHON_CMD (
        py -3.12 -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=py -3.12"
    )
)

if defined PYTHON_CMD goto python_ready

echo Downloading the official Python 3.12.10 installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile '%PYTHON_INSTALLER%'"
if errorlevel 1 goto install_failed

start /wait "" "%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 TargetDir="%LOCALAPPDATA%\Programs\Python\Python312" Include_launcher=1 Include_pip=1 PrependPath=0 Include_test=0
if not exist "%PYTHON_FALLBACK%" goto install_failed
"%PYTHON_FALLBACK%" -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))" >nul 2>&1
if errorlevel 1 goto install_failed
set "PYTHON_CMD="%PYTHON_FALLBACK%""

:python_ready
echo Using Python 3.12.

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))" >nul 2>&1
    if errorlevel 1 (
        echo Recreating the project environment for Python 3.12...
        rmdir /s /q ".venv"
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the project environment...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto install_failed
)

echo Installing Pygame...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto install_failed
".venv\Scripts\python.exe" -m pip install pygame
if errorlevel 1 goto install_failed

echo.
echo Setup is complete. Double-click start.bat to play.
pause
exit /b 0

:install_failed
echo.
echo Setup could not finish. Check your internet connection and try again.
echo If Python installation failed, install Python 3.12 from https://www.python.org/downloads/
pause
exit /b 1
