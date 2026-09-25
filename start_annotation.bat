@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo Installa uv e poi esegui uv sync mentre sei online.
  pause
  exit /b 1
)
set "package_path=%~1"
if not defined package_path set /p "package_path=Percorso SQLite senza virgolette (vuoto per il database principale): "
if not defined package_path goto master
if not exist "%package_path%" (
  echo Pacchetto inesistente: controlla il percorso.
  pause
  exit /b 1
)
for %%I in ("%package_path%") do set "package_path=%%~fI"
uv run --offline --frozen streamlit run app.py -- --storage "%package_path%"
goto done
:master
uv run --offline --frozen streamlit run app.py
:done
if errorlevel 1 pause
