@echo off
title Pintel Check - build
cd /d "%~dp0"
echo.
echo   Pintel Check - build
echo   ====================
echo.

set PYEXE=
py -3 --version >nul 2>&1 && set PYEXE=py -3
if not defined PYEXE python --version >nul 2>&1 && set PYEXE=python
if not defined PYEXE python3 --version >nul 2>&1 && set PYEXE=python3

if not defined PYEXE (
  echo   Python not found.
  echo.
   echo   Install Python 3.11+ from python.org
   echo   IMPORTANT: tick "Add Python to PATH" during install.
   echo   Do NOT use the Microsoft Store version.
  echo.
  start "" "https://www.python.org/downloads/windows/"
  goto done
)

echo   Python: %PYEXE%
%PYEXE% --version
echo.

if not exist "build.py" (
  echo   ERROR: build.py not found in this folder.
  echo   Folder: %CD%
  echo   Unpack the whole archive, not a single file.
  goto done
)

%PYEXE% build.py
echo.
echo   ---- exit code: %errorlevel% ----

:done
echo.
pause
