#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -q -r requirements.txt
fi
( sleep 2; (open http://127.0.0.1:8031/ || xdg-open http://127.0.0.1:8031/) >/dev/null 2>&1 ) &
.venv/bin/python app.py
