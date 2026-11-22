@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe python -m venv .venv
.venv\Scripts\python -m pip install -q -r requirements.txt
start "Live Clipper server" .venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8765
timeout /t 2 >nul
start "" http://127.0.0.1:8765
