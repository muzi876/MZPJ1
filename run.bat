@echo off
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8000"
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload --reload-include "*.py"