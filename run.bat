@echo off
rem nzgeo launcher for Windows. First run installs everything (several minutes); later runs start straight away.
cd /d "%~dp0"
set PY=
for %%V in (3.13 3.12 3.11) do (if not defined PY (py -%%V -c "import sys" >nul 2>&1 && set PY=py -%%V))
if not defined PY (python -c "import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1 && set PY=python)
if not defined PY (
  echo Python 3.11 or newer is needed. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then run this again.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  echo First run: setting up ^(this can take 5-10 minutes^)...
  %PY% -m venv .venv
)
if not exist .venv\.installed (
  .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
  .venv\Scripts\python.exe -m pip install --quiet -e . || (echo Install failed. & pause & exit /b 1)
  echo done> .venv\.installed
)
echo Starting nzgeo at http://127.0.0.1:8765/  ^(close this window to stop^)
start "" /min cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8765/"
.venv\Scripts\python.exe -m nzgeo serve
pause
