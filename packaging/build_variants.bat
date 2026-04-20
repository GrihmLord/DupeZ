@echo off
setlocal

:: ── Run from repo root regardless of where this .bat lives ──────────
:: This script lives in packaging\. All downstream commands expect
:: repo root as cwd (requirements.txt, dist\, build\ dirs).
pushd "%~dp0.."

:: ── DupeZ variant build pipeline ────────────────────────────────────
:: Produces both user-facing builds:
::
::   dist\DupeZ-GPU.exe     — asInvoker, split-arch, GPU map
::   dist\DupeZ-Compat.exe  — requireAdministrator, inproc, legacy
::
:: Run from the repo root:
::     build_variants.bat
::
:: Prereqs: python, PyInstaller, everything in requirements.txt.

set "DUPEZ_VERSION=5.6.3"

echo ============================================
echo  DupeZ v%DUPEZ_VERSION% -- Variant Build
echo ============================================
echo.

:: ── 1. Prereqs ──────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

echo Installing dependencies...
pip install -r requirements.txt

:: ── 2. Clean stale artifacts ────────────────────────────────────────
:: Kill any running DupeZ instances so their .exe files unlock.
taskkill /f /im DupeZ-GPU.exe    >nul 2>&1
taskkill /f /im DupeZ-Compat.exe >nul 2>&1
:: Note: no separate dupez_helper.exe is built — the elevated helper is
:: DupeZ-GPU.exe re-invoked with `--role helper`. The kill above handles
:: both the GUI and any lingering helper child.

:: Force-delete with verification. del /q silently no-ops on locked
:: files, which historically caused PyInstaller's os.remove(self.name)
:: to fail later in the build with WinError 5 (Access is denied).
:: Defender real-time scanning is the usual culprit holding the handle
:: after a fresh build; add dist\ + build\ to Defender exclusions to
:: avoid this entirely (see release.md / build runbook).
call :force_delete "dist\DupeZ-GPU.exe"
if errorlevel 1 (
    echo.
    echo BUILD FAILED — pre-build cleanup could not free dist\DupeZ-GPU.exe.
    exit /b 1
)
call :force_delete "dist\DupeZ-Compat.exe"
if errorlevel 1 (
    echo.
    echo BUILD FAILED — pre-build cleanup could not free dist\DupeZ-Compat.exe.
    exit /b 1
)
if exist "build\DupeZ-GPU"       rmdir /s /q "build\DupeZ-GPU"
if exist "build\DupeZ-Compat"    rmdir /s /q "build\DupeZ-Compat"

:: ── 3. Build GPU variant (asInvoker + split) ────────────────────────
echo.
echo [1/3] Building DupeZ-GPU.exe ...
python -m PyInstaller packaging\dupez_gpu.spec --noconfirm
if errorlevel 1 (
    echo.
    echo BUILD FAILED — DupeZ-GPU PyInstaller returned an error.
    pause
    exit /b 1
)
if not exist "dist\DupeZ-GPU.exe" (
    echo.
    echo BUILD FAILED — dist\DupeZ-GPU.exe not produced.
    pause
    exit /b 1
)
echo       DupeZ-GPU.exe built successfully.

:: ── 4. Build Compat variant (requireAdministrator + inproc) ─────────
:: Belt-and-suspenders: ensure DupeZ-Compat.exe is gone after GPU build
:: completes. Defender often re-scans dist\ between builds and re-locks
:: the previous Compat artifact even if the startup clean succeeded.
call :force_delete "dist\DupeZ-Compat.exe"
if errorlevel 1 (
    echo.
    echo BUILD FAILED — could not free dist\DupeZ-Compat.exe before Compat build.
    echo Not proceeding — PyInstaller would hit WinError 5 on os.remove.
    exit /b 1
)

echo.
echo [2/3] Building DupeZ-Compat.exe ...
python -m PyInstaller packaging\dupez_compat.spec --noconfirm
if errorlevel 1 (
    echo.
    echo BUILD FAILED — DupeZ-Compat PyInstaller returned an error.
    pause
    exit /b 1
)
if not exist "dist\DupeZ-Compat.exe" (
    echo.
    echo BUILD FAILED — dist\DupeZ-Compat.exe not produced.
    pause
    exit /b 1
)
echo       DupeZ-Compat.exe built successfully.

:: ── 5. Strip MOTW from raw exes ─────────────────────────────────────
echo.
echo [3/3] Stripping Mark-of-the-Web from build output...
powershell -NoProfile -Command "Get-ChildItem 'dist' -Recurse | ForEach-Object { Unblock-File $_.FullName -ErrorAction SilentlyContinue }"
echo       MOTW stripped from dist\ contents.

echo.
echo ============================================
echo  VARIANT BUILD COMPLETE
echo ============================================
echo.
echo   dist\DupeZ-GPU.exe     ^(asInvoker, split, GPU map — RECOMMENDED^)
echo   dist\DupeZ-Compat.exe  ^(requireAdministrator, inproc, legacy^)
echo.
echo  Ship BOTH on the release page. GPU is the default download;
echo  Compat is offered for users on blocklisted GPUs or environments
echo  where Chromium's GPU process will not initialize.
echo.

popd
endlocal
exit /b 0

:: ── Subroutine: force_delete ────────────────────────────────────────
:: Usage: call :force_delete "path\to\file"
:: Frees the target path so PyInstaller can write a fresh .exe.
::
:: Strategy — rename first, delete second:
::   1. Rename the stale file to a .stale-NNNN sibling. On Windows,
::      rename succeeds even when delete is blocked, because AV
::      (MsMpEng.exe) opens files with FILE_SHARE_DELETE — which
::      permits rename, just not unlink. After rename the target
::      path is free and PyInstaller can write to it unobstructed.
::   2. Best-effort delete the renamed file. If AV still has the
::      handle, we leave a .stale-NNNN artifact in dist\ and move on —
::      the next build sweeps them up at the top of this subroutine.
::   3. If rename itself fails (rare — means the holder opened WITHOUT
::      FILE_SHARE_DELETE, e.g. a live DupeZ instance the taskkill
::      missed), fall back to the 10x delete-retry loop.
::
:: Required because cmd's `del /q` silently no-ops on locked files,
:: which caused PyInstaller's os.remove(self.name) to fail with
:: WinError 5 late in the Compat build. Add-MpPreference exclusions
:: do NOT close existing Defender handles, they only prevent new
:: scans — so retry-delete alone could not recover from a stale
:: artifact that was already being scanned when the script started.
:force_delete
set "_FD_TARGET=%~1"

:: Sweep any leftover .stale-NNNN from a prior aborted run.
:: Best-effort — a held .stale survives to the next build.
for %%F in ("%_FD_TARGET%.stale-*") do del /f /q "%%F" >nul 2>&1

if not exist "%_FD_TARGET%" exit /b 0

:: Attempt 1 — rename out of the way (usually wins vs AV handles).
set "_FD_STALE=%_FD_TARGET%.stale-%RANDOM%%RANDOM%"
move /y "%_FD_TARGET%" "%_FD_STALE%" >nul 2>&1
if not exist "%_FD_TARGET%" (
    :: Rename succeeded — path is free. Best-effort delete the stale.
    del /f /q "%_FD_STALE%" >nul 2>&1
    exit /b 0
)

:: Attempt 2 — delete-retry fallback (rare path; holder opened
:: without FILE_SHARE_DELETE, so neither rename nor delete will work
:: until the handle closes. Retry gives AV a chance to finish).
set "_FD_TRIES=0"
:force_delete_retry
del /f /q "%_FD_TARGET%" >nul 2>&1
if not exist "%_FD_TARGET%" exit /b 0
set /a _FD_TRIES+=1
if %_FD_TRIES% GEQ 10 (
    echo.
    echo BUILD FAILED — cannot free "%_FD_TARGET%" after rename + 10 delete retries.
    echo A process has the file open without FILE_SHARE_DELETE — neither
    echo rename nor delete will work until the holder closes. Usual culprits:
    echo   - A live DupeZ instance the taskkill at script start missed
    echo   - Explorer preview pane ^(close the dist\ folder window^)
    echo   - An aggressive AV other than Defender
    echo Reboot if you cannot identify the holder, then re-run the build.
    exit /b 1
)
powershell -NoProfile -Command "Start-Sleep -Milliseconds 1000" >nul 2>&1
goto :force_delete_retry
