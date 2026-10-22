@echo off
title Pintel Check - collect bin
cd /d "%~dp0"
echo.
echo   Pintel Check - collect bin from MSYS2
echo   =====================================
echo.

set PYEXE=
py -3 --version >nul 2>&1 && set PYEXE=py -3
if not defined PYEXE python --version >nul 2>&1 && set PYEXE=python
if not defined PYEXE python3 --version >nul 2>&1 && set PYEXE=python3

if not defined PYEXE (
  echo   Python not found. Install from python.org
  start "" "https://www.python.org/downloads/windows/"
  goto done
)

%PYEXE% get_bin.py
echo.
echo   ---- exit code: %errorlevel% ----

:done
echo.
pause
