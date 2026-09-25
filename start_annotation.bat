@echo off
cd /d "%~dp0"
uv run --offline --frozen streamlit run scripts/annotation/app.py
if errorlevel 1 pause
