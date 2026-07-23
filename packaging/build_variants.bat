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
:: Prereqs: a repository-local .venv with 64-bit Python 3.11.9 and pip.

set "DUPEZ_VERSION=5.7.9"
set "DUPEZ_BOOTSTRAP_PYTHON=%CD%\.venv\Scripts\python.exe"
set "DUPEZ_BUILD_VENV=%CD%\.build-venv"
set "DUPEZ_PYTHON=%DUPEZ_BUILD_VENV%\Scripts\python.exe"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PIP_REQUIRE_VIRTUALENV=true"

echo ============================================
echo  DupeZ v%DUPEZ_VERSION% -- Variant Build
echo ============================================
echo.

:: ── 1. Prereqs ──────────────────────────────────────────────────────
if not exist "%DUPEZ_BOOTSTRAP_PYTHON%" (
    echo ERROR: Repository bootstrap interpreter not found:
    echo        %DUPEZ_BOOTSTRAP_PYTHON%
    echo Create .venv with 64-bit Python 3.11.9 and rerun this script.
    pause
    exit /b 1
)

"%DUPEZ_BOOTSTRAP_PYTHON%" -I -S -c "import struct, sys; raise SystemExit(0 if sys.version_info[:3] == (3, 11, 9) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 (
    echo ERROR: Release builds require 64-bit Python 3.11.9.
    pause
    exit /b 1
)

if exist "%DUPEZ_BUILD_VENV%" rmdir /s /q "%DUPEZ_BUILD_VENV%"
if exist "%DUPEZ_BUILD_VENV%" (
    echo ERROR: Could not remove stale build environment:
    echo        %DUPEZ_BUILD_VENV%
    exit /b 1
)

echo Creating clean build-only virtual environment...
"%DUPEZ_BOOTSTRAP_PYTHON%" -I -S -m venv "%DUPEZ_BUILD_VENV%"
if errorlevel 1 exit /b 1
if not exist "%DUPEZ_PYTHON%" (
    echo ERROR: Build interpreter was not created:
    echo        %DUPEZ_PYTHON%
    exit /b 1
)

"%DUPEZ_PYTHON%" -I --version
if errorlevel 1 exit /b 1

echo Installing hash-pinned build tooling...
"%DUPEZ_PYTHON%" -I -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes -r packaging\requirements-build-locked.txt
if errorlevel 1 exit /b 1

echo Installing hash-pinned production dependencies...
"%DUPEZ_PYTHON%" -I -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes -r requirements-locked.txt
if errorlevel 1 exit /b 1

echo Verifying hermetic build imports...
"%DUPEZ_PYTHON%" -I -c "import PyInstaller; import PyQt6.sip; from PyQt6 import QtCore, QtWidgets, QtWebEngineWidgets"
if errorlevel 1 (
    echo ERROR: Required build/runtime imports failed inside .build-venv.
    echo        Refusing to build with an incomplete or mixed Python environment.
    pause
    exit /b 1
)

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
:: Endpoint protection may briefly hold a fresh artifact. Keep protection
:: enabled; the cleanup path below waits, renames, and retries safely.
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
echo [1/5] Building DupeZ-GPU.exe ...
"%DUPEZ_PYTHON%" -I -m PyInstaller packaging\dupez_gpu.spec --noconfirm
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
echo       Verifying frozen runtime imports...
"dist\DupeZ-GPU.exe" --verify-runtime-imports
if errorlevel 1 (
    echo.
    echo BUILD FAILED - DupeZ-GPU.exe cannot import its bundled Qt runtime.
    echo The executable is not releasable.
    pause
    exit /b 1
)
echo       Frozen runtime imports verified.

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
echo [2/5] Building DupeZ-Compat.exe ...
"%DUPEZ_PYTHON%" -I -m PyInstaller packaging\dupez_compat.spec --noconfirm
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
echo       Verifying frozen dependency boundary...
"%DUPEZ_PYTHON%" scripts\release_preflight.py ^
    --frozen-artifact dist\DupeZ-GPU.exe ^
    --frozen-artifact dist\DupeZ-Compat.exe
if errorlevel 1 (
    echo.
    echo BUILD FAILED - portable executables contain forbidden optional dependencies.
    pause
    exit /b 1
)
echo       Frozen dependency boundary verified.

:: ── 5. Authenticode sign portable executables ───────────────────────
:: Microsoft SignTool guidance requires explicit SHA-256 file digest
:: (/fd) and RFC3161 timestamp digest (/td). Timestamping keeps signatures
:: valid after certificate expiry and helps SmartScreen reputation attach to
:: the publisher instead of only to a one-off file hash.
echo.
echo [Signing] Authenticode signing portable executables...

set "_SIGNTOOL="
where signtool >nul 2>&1 && set "_SIGNTOOL=signtool"
if not defined _SIGNTOOL (
    echo       signtool not found -- portable executables will remain unsigned.
    echo       To enable: install Windows SDK and set DUPEZ_SIGN_CERT.
    goto :skip_authenticode_portables
)
if "%DUPEZ_SIGN_CERT%"=="" (
    echo       DUPEZ_SIGN_CERT not set -- portable executables will remain unsigned.
    echo       To enable: set DUPEZ_SIGN_CERT=path\to\certificate.pfx
    goto :skip_authenticode_portables
)

call :sign_file "dist\DupeZ-GPU.exe"
if errorlevel 1 exit /b 1
call :sign_file "dist\DupeZ-Compat.exe"
if errorlevel 1 exit /b 1

:skip_authenticode_portables

:: ── 6. Strip MOTW from raw exes ─────────────────────────────────────
echo.
echo [3/5] Stripping Mark-of-the-Web from build output...
powershell -NoProfile -Command "Get-ChildItem 'dist' -Recurse | ForEach-Object { Unblock-File $_.FullName -ErrorAction SilentlyContinue }"
echo       MOTW stripped from dist\ contents.

:: ── 7. Build Inno Setup installer (v5.6.5) ──────────────────────────
:: Up to v5.6.4, build_variants.bat only emitted the two portable
:: exes; the installer had to be built separately via build.bat or a
:: manual `iscc packaging\installer.iss` invocation. That bit two
:: releases in a row (v5.6.3 + v5.6.4) when the operator forgot the
:: second step. Now folded in — single-command release.
::
:: installer.iss already bundles DupeZ-GPU.exe (as dupez.exe) and
:: DupeZ-Compat.exe alongside config / themes / dlls, so we just need
:: the GPU + Compat builds above to exist (verified in steps 3-4) and
:: ISCC on PATH or at the well-known install path.
echo.
echo [4/5] Building Inno Setup installer...

:: Locate ISCC.exe — try PATH first, then the Inno Setup 6 default
:: install dir. Allow override via env DUPEZ_ISCC for non-standard
:: installs. ISCC isn't always added to PATH by the installer GUI.
set "_ISCC="
where iscc >nul 2>&1 && set "_ISCC=iscc"
if not defined _ISCC if defined DUPEZ_ISCC if exist "%DUPEZ_ISCC%" set "_ISCC=%DUPEZ_ISCC%"
if not defined _ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "_ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined _ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "_ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not defined _ISCC (
    echo       Inno Setup ^(ISCC.exe^) not found — skipping installer build.
    echo       Install from https://jrsoftware.org/isdl.php and re-run,
    echo       or set DUPEZ_ISCC to the full path of ISCC.exe.
    goto :skip_installer
)

echo       Using ISCC: %_ISCC%
"%_ISCC%" packaging\installer.iss
if errorlevel 1 (
    echo.
    echo       WARNING: Installer build failed — ISCC returned an error.
    echo       Portable exes are still valid; ship without installer if needed.
    goto :skip_installer
)

set "DUPEZ_INSTALLER=DupeZ_v%DUPEZ_VERSION%_Setup.exe"
if not exist "dist\%DUPEZ_INSTALLER%" (
    echo       WARNING: dist\%DUPEZ_INSTALLER% not produced despite ISCC success.
    goto :skip_installer
)
echo       Installer built: dist\%DUPEZ_INSTALLER%
call :sign_file "dist\%DUPEZ_INSTALLER%"
if errorlevel 1 exit /b 1

:: Emit versionless alias for the stable GitHub-releases-latest URL.
:: The landing page Download Installer button points at
:: https://github.com/GrihmLord/DupeZ/releases/latest/download/DupeZ_Setup.exe
:: so this alias MUST exist on every release or the button 404s. Bit us
:: between v5.6.2 and v5.6.3.
copy /Y "dist\%DUPEZ_INSTALLER%" "dist\DupeZ_Setup.exe" >nul
if errorlevel 1 (
    echo       WARNING: Failed to create versionless alias dist\DupeZ_Setup.exe
) else (
    echo       Versionless alias: dist\DupeZ_Setup.exe ^(landing-page download target^)
    call :sign_file "dist\DupeZ_Setup.exe"
    if errorlevel 1 exit /b 1
)

:skip_installer

:: ── 8. Sign update manifest (v5.6.6+) ───────────────────────────────
:: The auto-updater (app/core/updater.py) fail-closes unless each
:: release ships TWO sidecar files alongside DupeZ_Setup.exe:
::
::   DupeZ_Setup.exe.manifest.json   — Ed25519-signed metadata
::   DupeZ_Setup.exe.manifest.sig    — 72-byte signature envelope
::
:: Without these, clients get "signed manifest not available" and
:: fall back to manual install. Bit users v5.6.2-v5.6.5 because the
:: signer was never wired in. Now folded in: if DUPEZ_SIGN_PRIVKEY
:: points at the Ed25519 private key PEM, we sign automatically.
::
:: Privkey storage: KEEP OUT OF THE REPO. Recommended location:
::   C:\DupeZ-keys\dupez-update-priv.pem (ACL'd to signer only)
:: Generate once: python scripts\sign-release.py --gen-key ...
:: Then add the pubkey to app/core/update_verify.TRUSTED_PUBKEYS_PEM
:: and ship that client release BEFORE signing any update with the
:: matching privkey. See app/core/update_verify.py docstring.
echo.
echo [Signing] Signing update manifest...

:: Never let a previous release's valid-looking sidecars survive this build.
:: The dist preflight verifies signature, version, filename, size, and hash,
:: but deleting first also makes an unsigned local build fail visibly instead
:: of appearing to carry current updater metadata.
del /Q "dist\DupeZ_Setup.exe.manifest.json" >nul 2>&1
del /Q "dist\DupeZ_Setup.exe.manifest.sig" >nul 2>&1
if exist "dist\DupeZ_Setup.exe.manifest.json" (
    echo       ERROR: Could not remove stale update manifest.
    exit /b 1
)
if exist "dist\DupeZ_Setup.exe.manifest.sig" (
    echo       ERROR: Could not remove stale update signature.
    exit /b 1
)

if "%DUPEZ_SIGN_PRIVKEY%"=="" (
    echo       DUPEZ_SIGN_PRIVKEY not set — skipping manifest signing.
    echo       Auto-update will fail-closed for clients on this release.
    echo       To enable: set DUPEZ_SIGN_PRIVKEY=path\to\dupez-update-priv.pem
    goto :skip_sign_manifest
)

if not exist "%DUPEZ_SIGN_PRIVKEY%" (
    echo       WARNING: DUPEZ_SIGN_PRIVKEY points at "%DUPEZ_SIGN_PRIVKEY%"
    echo       but the file does not exist. Skipping manifest signing.
    goto :skip_sign_manifest
)

if not exist "dist\DupeZ_Setup.exe" (
    echo       WARNING: dist\DupeZ_Setup.exe not present — cannot sign.
    goto :skip_sign_manifest
)

"%DUPEZ_PYTHON%" scripts\sign-release.py --sign ^
    --priv "%DUPEZ_SIGN_PRIVKEY%" ^
    --installer "dist\DupeZ_Setup.exe" ^
    --version "%DUPEZ_VERSION%"
if errorlevel 1 (
    echo       WARNING: sign-release.py returned an error.
    echo       Auto-update will fail-closed for this release.
    goto :skip_sign_manifest
)

if exist "dist\DupeZ_Setup.exe.manifest.json" (
    echo       Signed manifest: dist\DupeZ_Setup.exe.manifest.json
)
if exist "dist\DupeZ_Setup.exe.manifest.sig" (
    echo       Signature:       dist\DupeZ_Setup.exe.manifest.sig
)

:skip_sign_manifest

"%DUPEZ_PYTHON%" scripts\sbom.py --out dist\DupeZ.sbom.json --product-version "%DUPEZ_VERSION%"
if errorlevel 1 exit /b 1
"%DUPEZ_PYTHON%" scripts\vex.py --out dist\DupeZ.vex.json --product-version "%DUPEZ_VERSION%"
if errorlevel 1 exit /b 1
copy /y packaging\binary-provenance.json dist\binary-provenance.json >nul
if errorlevel 1 exit /b 1

:: ── 9. Final report ─────────────────────────────────────────────────
echo.
echo [5/5] Build summary
echo ============================================
echo  VARIANT BUILD COMPLETE
echo ============================================
echo.
echo   dist\DupeZ-GPU.exe                       ^(asInvoker, split, GPU map — RECOMMENDED^)
echo   dist\DupeZ-Compat.exe                    ^(requireAdministrator, inproc, legacy^)
if exist "dist\DupeZ_v%DUPEZ_VERSION%_Setup.exe" (
    echo   dist\DupeZ_v%DUPEZ_VERSION%_Setup.exe           ^(Inno Setup installer^)
    echo   dist\DupeZ_Setup.exe                     ^(stable versionless alias for landing page^)
) else (
    echo   ^(installer skipped — see warnings above^)
)
if exist "dist\DupeZ_Setup.exe.manifest.json" (
    echo   dist\DupeZ_Setup.exe.manifest.json       ^(signed update manifest^)
    echo   dist\DupeZ_Setup.exe.manifest.sig        ^(Ed25519 signature envelope^)
)
echo.
echo  Ship ALL of the above on the release page. The two .manifest.*
echo  files are REQUIRED for auto-update to work — without them, clients
echo  fail-closed with "signed manifest not available." The versionless
echo  alias keeps the landing-page Download URL stable across releases.
echo.

popd
endlocal
exit /b 0

:: ── Subroutine: sign_file ───────────────────────────────────────────
:: Usage: call :sign_file "dist\artifact.exe"
:: Signs only when signtool and DUPEZ_SIGN_CERT are configured.
:sign_file
set "_SIGN_TARGET=%~1"
if not exist "%_SIGN_TARGET%" exit /b 0
if not defined _SIGNTOOL exit /b 0
if "%DUPEZ_SIGN_CERT%"=="" exit /b 0
echo       Signing %_SIGN_TARGET% ...
if "%DUPEZ_SIGN_PASS%"=="" (
    "%_SIGNTOOL%" sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /f "%DUPEZ_SIGN_CERT%" "%_SIGN_TARGET%"
) else (
    "%_SIGNTOOL%" sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /f "%DUPEZ_SIGN_CERT%" /p "%DUPEZ_SIGN_PASS%" "%_SIGN_TARGET%"
)
if errorlevel 1 (
    echo       ERROR: Authenticode signing failed for %_SIGN_TARGET%.
    exit /b 1
)
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
:: WinError 5 late in the Compat build. The rename/retry strategy avoids
:: weakening endpoint protection while still recovering stale artifacts.
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
