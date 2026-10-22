@echo off
title Pintel Check - setup
cd /d "%~dp0"
echo.
echo   Pintel Check - setup
echo   ====================
echo.

set PYEXE=
py -3 --version >nul 2>&1 && set PYEXE=py -3
if not defined PYEXE python --version >nul 2>&1 && set PYEXE=python
if not defined PYEXE python3 --version >nul 2>&1 && set PYEXE=python3

if not defined PYEXE (
  echo   Python not found.
  echo   Install Python 3.11+ from python.org
   echo   IMPORTANT: tick "Add Python to PATH" during install.
  start "" "https://www.python.org/downloads/windows/"
  goto done
)

if not exist "setup_check.py" (
  echo   ERROR: setup_check.py not found. Folder: %CD%
  goto done
)

%PYEXE% setup_check.py
echo.
echo   ---- exit code: %errorlevel% ----

:done
echo.
pause
