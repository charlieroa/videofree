@echo off
cd /d "%~dp0"
if not exist .venv (
  py -3.12 -m venv .venv
  .venv\Scripts\python -m pip install -q -r requirements.txt
)
start "" http://127.0.0.1:8031/
.venv\Scripts\python app.py
