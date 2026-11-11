@echo off
REM Exe banaye baghair tool chalao (Python chahiye). Testing / development ke liye.
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( echo Python nahi mila. & pause & exit /b 1 )
%PY% -m pip install -r requirements.txt --quiet --disable-pip-version-check
start "" %PY% launcher.py
