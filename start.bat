@echo off
wt -d "%~dp0backend" cmd /k "uv run python -m fastapi dev main.py"; new-tab -d "%~dp0frontend" cmd /k "npm run dev -- --open"