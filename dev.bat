@echo off
cd /d "%~dp0"
title VN Script Studio

echo.
echo Starting VN Script Studio...
echo If this window closes with errors, read the lines above.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" -KeepOpen %*
set ERR=%ERRORLEVEL%

if %ERR% neq 0 (
  echo.
  echo [FAILED] exit code %ERR%
  echo Copy the error text above if you need help.
  echo.
)

echo.
pause