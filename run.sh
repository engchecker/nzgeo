#!/usr/bin/env bash
# nzgeo launcher for Mac and Linux. First run installs everything (several minutes); later runs start straight away.
set -e
cd "$(dirname "$0")"
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then echo "Python 3.11 or newer is needed. Install it from https://www.python.org/downloads/ then run this again."; exit 1; fi
if [ ! -x .venv/bin/python ]; then echo "First run: setting up (this can take 5-10 minutes)..."; "$PY" -m venv .venv; fi
if [ ! -f .venv/.installed ]; then .venv/bin/python -m pip install --quiet --upgrade pip && .venv/bin/python -m pip install --quiet -e . && touch .venv/.installed; fi
echo "Starting nzgeo at http://127.0.0.1:8765/  (close this window to stop)"
( sleep 4; (open http://127.0.0.1:8765/ || xdg-open http://127.0.0.1:8765/) >/dev/null 2>&1 ) &
exec .venv/bin/python -m nzgeo serve
