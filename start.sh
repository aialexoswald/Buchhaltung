#!/bin/sh
# Startet die Buchhaltung (macOS / Linux). Beim ersten Start wird alles eingerichtet.
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
  python3 -m venv .venv || exit 1
  .venv/bin/pip install -q -r requirements.txt || exit 1
fi
exec .venv/bin/python -m buchhaltung "$@"
