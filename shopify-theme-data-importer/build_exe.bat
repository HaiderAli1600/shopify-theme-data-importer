@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Shopify Theme Data Importer - EXE Builder
chcp 65001 >nul

echo.
echo  ==============================================================
echo     SHOPIFY THEME DATA IMPORTER  -  EXE BUILDER   (v3.0.0)
echo     Developed by Dev Haider Ali
echo  ==============================================================
echo.
echo  Yeh script ek SINGLE .exe banati hai jis me Python aur saari
echo  libraries andar hoti hain. Jis PC par exe chalegi wahan kuch
echo  install karne ki zaroorat NAHI.
echo.
echo  Sirf IS PC par (jahan exe ban rahi hai) Python 3.10+ chahiye:
echo  https://www.python.org/downloads/  (install karte waqt
echo  "Add python.exe to PATH" par tick lagana)
echo.

REM ---------------------------------------------------------- 1) Python
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo  [X] Python nahi mila. Pehle Python install karo, phir dobara chalao.
  goto :fail
)
echo  [1/4] Python mila:
%PY% --version || goto :fail

REM ---------------------------------------------------------- 2) Build environment
echo.
echo  [2/4] Alag build environment tayar ho raha hai (.build-venv)...
if not exist ".build-venv\Scripts\python.exe" (
  %PY% -m venv .build-venv || goto :fail
)
set "VPY=.build-venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%VPY%" -m pip install -r requirements.txt pyinstaller --quiet --disable-pip-version-check || goto :fail

REM ---------------------------------------------------------- 3) Clean
echo.
echo  [3/4] Purani build saaf ho rahi hai...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "Shopify Theme Data Importer.spec" del /q "Shopify Theme Data Importer.spec"

REM ---------------------------------------------------------- 4) Build
echo.
echo  [4/4] EXE ban rahi hai (2-4 minute lag sakte hain)...
"%VPY%" -m PyInstaller --noconfirm --clean --log-level WARN ^
  --onefile --windowed ^
  --name "Shopify Theme Data Importer" ^
  --icon "assets\logo.ico" ^
  --version-file "assets\version_info.txt" ^
  --add-data "app\ui;app\ui" ^
  --collect-submodules app ^
  launcher.py || goto :fail

if not exist "dist\Shopify Theme Data Importer.exe" goto :fail

echo.
echo  ==============================================================
echo    MUKAMMAL!  EXE yahan hai:
echo    %cd%\dist\Shopify Theme Data Importer.exe
echo.
echo    Yeh ek file kisi ko bhi de sakte ho - double click se chalegi.
echo  ==============================================================
echo.
start "" explorer "dist"
pause
exit /b 0

:fail
echo.
echo  [X] Build fail ho gayi. Upar wala error message dekho.
echo      Aam masle: internet band (pip install), Python PATH me nahi,
echo      ya antivirus ne build folder block kiya.
echo.
pause
exit /b 1
