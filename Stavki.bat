@echo off
cd /d "%~dp0"
title Stavki - do not close while you use the program
echo Stavki: starting. The program window opens in your browser by itself.
echo To stop the program, close this black window.
echo.
set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY python --version >nul 2>&1 && set PY=python
if not defined PY (
  echo Python not found. Send a screenshot of this window to Claude.
  pause
  exit /b 1
)
%PY% -c "import playwright" >nul 2>&1 || %PY% -m pip install --user playwright

:update
echo Checking for a new version on GitHub...
if exist stavki_new.py del stavki_new.py
%PY% -c "import urllib.request;urllib.request.urlretrieve('https://raw.githubusercontent.com/gggvip0000-cell/stavki/main/stavki.py?t=%RANDOM%%RANDOM%','stavki_new.py')" >nul 2>&1
if exist stavki_new.py (
  %PY% -m py_compile stavki_new.py >nul 2>&1 && move /y stavki_new.py stavki.py >nul
)
if exist stavki_new.py del stavki_new.py
if not exist stavki.py (
  echo Could not download the program. Check the internet and start Stavki.bat again.
  pause
  exit /b 1
)

:run
%PY% stavki.py
if %errorlevel%==3 goto update
echo.
echo The program stopped. Send a screenshot of this window to Claude if it was not you who stopped it.
pause
