@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" start_web.py
) else (
  python start_web.py
)
if errorlevel 1 pause
