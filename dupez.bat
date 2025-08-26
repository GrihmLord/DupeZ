@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM DupeZ - Unified Launcher
REM Usage:
REM   dupez.bat            -> normal mode (prefers dist exe, else source)
REM   dupez.bat --admin    -> admin mode (elevated)

cd /d "%~dp0"

set ARG=%~1
set ADMIN_MODE=
if /I "%ARG%"=="--admin" set ADMIN_MODE=1
if /I "%ARG%"=="/admin" set ADMIN_MODE=1
if /I "%ARG%"=="-admin" set ADMIN_MODE=1

REM Locate packaged exe (update target if you renamed it)
set EXE_PATH=
if exist "dist\DupeZ_izurvive\DupeZ_izurvive.exe" set EXE_PATH=dist\DupeZ_izurvive\DupeZ_izurvive.exe

if not defined EXE_PATH (
  for /f "delims=" %%F in ('dir /b /s dist\*.exe 2^>nul') do (
    set EXE_PATH=%%F
    goto :HaveExe
  )
)
:HaveExe

REM Prefer venv python for source runs if available
set VENV_PY=.venv\Scripts\python.exe

if defined ADMIN_MODE (
  echo Starting DupeZ (Admin)...
  if defined EXE_PATH (
    powershell -NoProfile -Command "Start-Process -FilePath '%CD%\%EXE_PATH%' -Verb RunAs" 2>nul
    goto :EOF
  )
  if exist "%VENV_PY%" (
    powershell -NoProfile -Command "Start-Process -FilePath '%CD%\%VENV_PY%' -ArgumentList '-m','app.main' -Verb RunAs" 2>nul
    goto :EOF
  ) else (
    powershell -NoProfile -Command "Start-Process -FilePath 'python' -ArgumentList '-m','app.main' -Verb RunAs" 2>nul
    goto :EOF
  )
) else (
  echo Starting DupeZ (Normal)...
  if defined EXE_PATH (
    start "" "%EXE_PATH%"
    goto :EOF
  )
  if exist "%VENV_PY%" (
    call ".venv\Scripts\activate.bat" 2>nul
    python -m app.main
  ) else (
    python -m app.main
  )
)

endlocal




