@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
if /I "%~1"=="--help" goto inspect
if /I "%~1"=="--check" goto inspect
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
call npm ci --omit=dev
if errorlevel 1 goto failed
".venv\Scripts\python.exe" scripts\download_local_models.py
if errorlevel 1 goto failed
node download-models.cjs
if errorlevel 1 goto failed
".venv\Scripts\python.exe" launch.py %*
if errorlevel 1 goto failed
exit /b 0
:inspect
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" launch.py %*
) else (
  python launch.py %*
)
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Startup failed. See the error above. A previous server may still be running.
pause
exit /b 1
