@echo off
rem Startet die Buchhaltung (Windows). Beim ersten Start wird alles eingerichtet.
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\pip install -q -r requirements.txt
)
.venv\Scripts\python -m buchhaltung %*
pause
