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
:: Prereqs: a repository-local .venv with 64-bit Python 3.13.17 and pip.

set "DUPEZ_VERSION=5.8.0"
set "DUPEZ_INSTALLER=DupeZ_v%DUPEZ_VERSION%_Setup.exe"
if not defined DUPEZ_PORTABLE_ONLY set "DUPEZ_PORTABLE_ONLY=0"
if not "%DUPEZ_PORTABLE_ONLY%"=="0" if not "%DUPEZ_PORTABLE_ONLY%"=="1" (
    echo ERROR: DUPEZ_PORTABLE_ONLY must be either 0 or 1.
    exit /b 1
)
if not defined DUPEZ_ALLOW_UNSIGNED set "DUPEZ_ALLOW_UNSIGNED=0"
if not "%DUPEZ_ALLOW_UNSIGNED%"=="0" if not "%DUPEZ_ALLOW_UNSIGNED%"=="1" (
    echo ERROR: DUPEZ_ALLOW_UNSIGNED must be either 0 or 1.
    exit /b 1
)
set "DUPEZ_RELEASE_MODE=standard-authenticode"
if "%DUPEZ_PORTABLE_ONLY%"=="1" set "DUPEZ_RELEASE_MODE=explicit-unsigned"
if "%DUPEZ_ALLOW_UNSIGNED%"=="1" set "DUPEZ_RELEASE_MODE=explicit-unsigned"
set "DUPEZ_RELEASE_NATIVE_STAGE=%CD%\build\release-native"
set "DUPEZ_SIGN_RELEASE_UNSIGNED_ARG="
if "%DUPEZ_ALLOW_UNSIGNED%"=="1" set "DUPEZ_SIGN_RELEASE_UNSIGNED_ARG=--allow-unsigned"
if not defined DUPEZ_BOOTSTRAP_PYTHON set "DUPEZ_BOOTSTRAP_PYTHON=%CD%\.venv\Scripts\python.exe"
set "DUPEZ_BUILD_VENV=%CD%\.release-venv"
set "DUPEZ_PYTHON=%DUPEZ_BUILD_VENV%\Scripts\python.exe"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PYTHONHASHSEED=0"
:: ZIP-based Windows launchers cannot represent timestamps before 1980.
set "SOURCE_DATE_EPOCH=315532800"
set "PIP_REQUIRE_VIRTUALENV=true"
set "DUPEZ_AUTHENTICODE_STATUS=UNSIGNED"
if not defined DUPEZ_SIGN_TIMESTAMP_URL set "DUPEZ_SIGN_TIMESTAMP_URL=http://timestamp.digicert.com"

echo ============================================
echo  DupeZ v%DUPEZ_VERSION% -- Variant Build
echo ============================================
echo.

:: ── 1. Prereqs ──────────────────────────────────────────────────────
if not exist "%DUPEZ_BOOTSTRAP_PYTHON%" (
    echo ERROR: Repository bootstrap interpreter not found:
    echo        %DUPEZ_BOOTSTRAP_PYTHON%
    echo Create .venv with 64-bit Python 3.13.17 and rerun this script.
    exit /b 1
)

"%DUPEZ_BOOTSTRAP_PYTHON%" -I -S -c "import struct, sys; raise SystemExit(0 if sys.version_info[:3] == (3, 13, 17) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 (
    echo ERROR: Release builds require 64-bit Python 3.13.17.
    exit /b 1
)

:: Resolve Authenticode prerequisites before preparing or consuming any
:: staged native payload. Standard distribution builds fail closed here;
:: explicit unsigned builds retain the portable CI path without a certificate.
set "_SIGNTOOL="
if defined DUPEZ_SIGNTOOL if exist "%DUPEZ_SIGNTOOL%" set "_SIGNTOOL=%DUPEZ_SIGNTOOL%"
if "%DUPEZ_RELEASE_MODE%"=="standard-authenticode" (
    if not defined _SIGNTOOL (
        echo ERROR: Standard distribution builds require Windows SDK SignTool.
        echo        Install the manifest-pinned SDK tool or set DUPEZ_SIGNTOOL
        echo        to that exact Program Files path.
        exit /b 1
    )
    if not defined DUPEZ_SIGN_CERT (
        echo ERROR: Standard distribution builds require DUPEZ_SIGN_CERT.
        exit /b 1
    )
    if not exist "%DUPEZ_SIGN_CERT%" (
        echo ERROR: DUPEZ_SIGN_CERT points at a missing certificate file:
        echo        %DUPEZ_SIGN_CERT%
        exit /b 1
    )
)

if exist "%DUPEZ_BUILD_VENV%" rmdir /s /q "%DUPEZ_BUILD_VENV%"
call :force_remove_dir "%DUPEZ_BUILD_VENV%"
if errorlevel 1 exit /b 1

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
    echo ERROR: Required build/runtime imports failed inside .release-venv.
    echo        Refusing to build with an incomplete or mixed Python environment.
    exit /b 1
)

echo Verifying owner-controlled license/IP distribution evidence...
"%DUPEZ_PYTHON%" -I scripts\release_preflight.py --license-distribution
if errorlevel 1 (
    echo ERROR: Distribution build blocked by unresolved license/IP decisions.
    echo        Update packaging\license-policy.json only with owner evidence.
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
for %%F in ("dist\%DUPEZ_INSTALLER%" "dist\DupeZ_Setup.exe" "dist\DupeZ_Setup.exe.manifest.json" "dist\DupeZ_Setup.exe.manifest.sig" "dist\DupeZ.sbom.json" "dist\DupeZ.vex.json" "dist\DupeZ.vulnerability-review.json" "dist\binary-provenance.json" "dist\LICENSE.txt" "dist\SOURCE_AND_RELINK.txt" "dist\THIRD_PARTY_NOTICES.txt" "dist\license-payload.json" "dist\DupeZ-v%DUPEZ_VERSION%-source.zip") do (
    call :force_delete "%%~F"
    if errorlevel 1 (
        echo.
        echo BUILD FAILED — pre-build cleanup could not free %%~F.
        exit /b 1
    )
)
if exist "build\DupeZ-GPU"       rmdir /s /q "build\DupeZ-GPU"
if exist "build\DupeZ-Compat"    rmdir /s /q "build\DupeZ-Compat"

:: Prepare the fixed, exact-source native stage used by both variant specs.
:: Only the staged Clumsy copy may change, and only for standard Authenticode
:: distribution builds; tracked upstream bytes are never signed in place.
echo.
echo [Native] Preparing verified native release stage...
"%DUPEZ_PYTHON%" -I packaging\release_data.py prepare
if errorlevel 1 (
    echo ERROR: Native release stage preparation failed.
    exit /b 1
)
if not exist "%DUPEZ_RELEASE_NATIVE_STAGE%\app\firewall\clumsy.exe" (
    echo ERROR: Prepared native stage is missing app\firewall\clumsy.exe.
    exit /b 1
)

if not "%DUPEZ_RELEASE_MODE%"=="standard-authenticode" goto :finalize_native_stage
call :sign_file "%DUPEZ_RELEASE_NATIVE_STAGE%\app\firewall\clumsy.exe"
if errorlevel 1 exit /b 1
if not "%DUPEZ_LAST_SIGNED%"=="1" (
    echo ERROR: Standard staged Clumsy signing did not complete.
    exit /b 1
)

:finalize_native_stage
"%DUPEZ_PYTHON%" -I packaging\release_data.py finalize --mode "%DUPEZ_RELEASE_MODE%"
if errorlevel 1 (
    echo ERROR: Native release stage finalization failed.
    exit /b 1
)
"%DUPEZ_PYTHON%" -I packaging\release_data.py verify --mode "%DUPEZ_RELEASE_MODE%"
if errorlevel 1 (
    echo ERROR: Native release stage verification failed.
    exit /b 1
)

:: ── 3. Build GPU variant (asInvoker + split) ────────────────────────
echo.
echo [1/5] Building DupeZ-GPU.exe ...
"%DUPEZ_PYTHON%" -I -m PyInstaller packaging\dupez_gpu.spec --noconfirm
if errorlevel 1 (
    echo.
    echo BUILD FAILED — DupeZ-GPU PyInstaller returned an error.
    exit /b 1
)
if not exist "dist\DupeZ-GPU.exe" (
    echo.
    echo BUILD FAILED — dist\DupeZ-GPU.exe not produced.
    exit /b 1
)
echo       DupeZ-GPU.exe built successfully.
echo       Verifying frozen runtime imports...
set "DUPEZ_VERIFY_REPORT=%TEMP%\dupez-verify-%RANDOM%-%RANDOM%.json"
del /Q "%DUPEZ_VERIFY_REPORT%" >nul 2>&1
"dist\DupeZ-GPU.exe" --verify-runtime-imports
if errorlevel 1 (
    echo.
    echo BUILD FAILED - DupeZ-GPU.exe cannot import its bundled Qt runtime.
    if exist "%DUPEZ_VERIFY_REPORT%" type "%DUPEZ_VERIFY_REPORT%"
    del /Q "%DUPEZ_VERIFY_REPORT%" >nul 2>&1
    set "DUPEZ_VERIFY_REPORT="
    echo The executable is not releasable.
    exit /b 1
)
del /Q "%DUPEZ_VERIFY_REPORT%" >nul 2>&1
set "DUPEZ_VERIFY_REPORT="
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
    exit /b 1
)
if not exist "dist\DupeZ-Compat.exe" (
    echo.
    echo BUILD FAILED — dist\DupeZ-Compat.exe not produced.
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

if not defined _SIGNTOOL (
    set "DUPEZ_AUTHENTICODE_STATUS=UNSIGNED ^(SignTool unavailable^)"
    echo       signtool not found -- portable executables will remain unsigned.
    echo       To enable: install Windows SDK and set DUPEZ_SIGN_CERT.
    goto :skip_authenticode_portables
)
if "%DUPEZ_SIGN_CERT%"=="" (
    set "DUPEZ_AUTHENTICODE_STATUS=UNSIGNED ^(certificate not configured^)"
    echo       DUPEZ_SIGN_CERT not set -- portable executables will remain unsigned.
    echo       To enable: set DUPEZ_SIGN_CERT=path\to\certificate.pfx
    goto :skip_authenticode_portables
)

call :sign_file "dist\DupeZ-GPU.exe"
if errorlevel 1 exit /b 1
call :sign_file "dist\DupeZ-Compat.exe"
if errorlevel 1 exit /b 1
if "%DUPEZ_LAST_SIGNED%"=="1" set "DUPEZ_AUTHENTICODE_STATUS=SIGNED ^(portable executables^)"

:skip_authenticode_portables

:: ── 6. Strip MOTW from raw exes ─────────────────────────────────────
echo.
echo [3/5] Stripping Mark-of-the-Web from build output...
powershell -NoProfile -Command "Get-ChildItem 'dist' -Recurse | ForEach-Object { Unblock-File $_.FullName -ErrorAction SilentlyContinue }"
echo       MOTW stripped from dist\ contents.

:: Build the exact-lock legal payload before compiling the installer so every
:: installed copy receives the project license, source/relink information, and
:: consolidated third-party notices. The generator fails on lock/version
:: drift, missing upstream license files, reparse points, or stale output.
echo.
echo [Legal] Building deterministic license and notice payload...
"%DUPEZ_PYTHON%" -I scripts\license_payload.py ^
    --version "%DUPEZ_VERSION%" ^
    --dist dist
if errorlevel 1 (
    echo.
    echo BUILD FAILED - deterministic license payload generation failed.
    exit /b 1
)
"%DUPEZ_PYTHON%" -I scripts\license_payload.py ^
    --version "%DUPEZ_VERSION%" ^
    --dist dist ^
    --verify
if errorlevel 1 (
    echo.
    echo BUILD FAILED - deterministic license payload verification failed.
    exit /b 1
)
echo       License and notice payload verified.

:: ── 7. Build Inno Setup installer (v5.6.5) ──────────────────────────
:: Up to v5.6.4, build_variants.bat only emitted the two portable
:: exes; the installer had to be built separately via build.bat or a
:: manual `iscc packaging\installer.iss` invocation. That bit two
:: releases in a row (v5.6.3 + v5.6.4) when the operator forgot the
:: second step. It is now part of this artifact-generation command.
::
:: installer.iss already bundles DupeZ-GPU.exe (as dupez.exe) and
:: DupeZ-Compat.exe alongside config / themes / dlls, so we just need
:: the GPU + Compat builds above to exist (verified in steps 3-4) and
:: the exact manifest-pinned ISCC Program Files path.
echo.
echo [4/5] Building Inno Setup installer...

if "%DUPEZ_PORTABLE_ONLY%"=="1" (
    echo       DUPEZ_PORTABLE_ONLY=1 — installer intentionally omitted.
    goto :skip_installer
)

:: The finalizer resolves and verifies the pinned absolute compiler before
:: entering this build. Never fall back to PATH or an ambient newest install.
set "_ISCC="
if defined DUPEZ_ISCC if exist "%DUPEZ_ISCC%" set "_ISCC=%DUPEZ_ISCC%"

if not defined _ISCC (
    echo       ERROR: Inno Setup ^(ISCC.exe^) not found.
    echo       Run scripts\finalize_release.ps1 so the pinned compiler is verified,
    echo       or set DUPEZ_ISCC to that exact verified absolute path.
    exit /b 1
)

echo       Using ISCC: %_ISCC%
"%DUPEZ_PYTHON%" -I packaging\compile_installer.py --mode "%DUPEZ_RELEASE_MODE%" --iscc "%_ISCC%"
if errorlevel 1 (
    echo.
    echo       ERROR: Installer build failed — ISCC returned an error.
    exit /b 1
)

if not exist "dist\%DUPEZ_INSTALLER%" (
    echo       ERROR: dist\%DUPEZ_INSTALLER% not produced despite ISCC success.
    exit /b 1
)
echo       Installer built: dist\%DUPEZ_INSTALLER%
call :sign_file "dist\%DUPEZ_INSTALLER%"
if errorlevel 1 exit /b 1
if "%DUPEZ_LAST_SIGNED%"=="1" set "DUPEZ_AUTHENTICODE_STATUS=SIGNED ^(portable executables and installer^)"

:: Emit the versionless alias after signing so it is byte-identical to the
:: versioned installer and carries the exact same signature and timestamp.
:: The landing page Download Installer button points at
:: https://github.com/GrihmLord/DupeZ/releases/latest/download/DupeZ_Setup.exe
:: so this alias MUST exist on every release or the button 404s. Bit us
:: between v5.6.2 and v5.6.3.
copy /Y "dist\%DUPEZ_INSTALLER%" "dist\DupeZ_Setup.exe" >nul
if errorlevel 1 (
    echo       ERROR: Failed to create versionless alias dist\DupeZ_Setup.exe
    exit /b 1
) else (
    echo       Versionless alias: dist\DupeZ_Setup.exe ^(landing-page download target^)
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
:: signer was never wired in. Non-portable artifact generation now requires
:: DUPEZ_SIGN_PRIVKEY to point at the trusted Ed25519 private key PEM.
::
:: Privkey storage: KEEP OUT OF THE REPO. Recommended location:
::   C:\DupeZ-keys\dupez-update-priv.pem (ACL'd to signer only)
:: Generate once: python scripts\sign-release.py --gen-key ...
:: Then add the pubkey to app/core/update_verify.TRUSTED_PUBKEYS_PEM
:: and ship that client release BEFORE signing any update with the
:: matching privkey. See app/core/update_verify.py docstring.
echo.
echo [Signing] Signing update manifest...

if "%DUPEZ_PORTABLE_ONLY%"=="1" (
    echo       Update manifest intentionally omitted in portable-only mode.
    goto :skip_sign_manifest
)

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

if not defined DUPEZ_SIGN_PRIVKEY (
    echo       ERROR: DUPEZ_SIGN_PRIVKEY is required for non-portable builds.
    echo       Set it to the trusted Ed25519 update-signing private key PEM.
    exit /b 1
)

if not exist "%DUPEZ_SIGN_PRIVKEY%" (
    echo       ERROR: DUPEZ_SIGN_PRIVKEY points at a missing file:
    echo       %DUPEZ_SIGN_PRIVKEY%
    exit /b 1
)

if not exist "dist\DupeZ_Setup.exe" (
    echo       ERROR: dist\DupeZ_Setup.exe is missing; cannot sign updater metadata.
    exit /b 1
)

"%DUPEZ_PYTHON%" scripts\sign-release.py --sign ^
    --priv "%DUPEZ_SIGN_PRIVKEY%" ^
    --installer "dist\DupeZ_Setup.exe" ^
    --version "%DUPEZ_VERSION%" %DUPEZ_SIGN_RELEASE_UNSIGNED_ARG%
if errorlevel 1 (
    echo       ERROR: sign-release.py failed; updater metadata is not valid.
    exit /b 1
)

if not exist "dist\DupeZ_Setup.exe.manifest.json" (
    echo       ERROR: sign-release.py did not create the update manifest.
    exit /b 1
)
if not exist "dist\DupeZ_Setup.exe.manifest.sig" (
    echo       ERROR: sign-release.py did not create the update signature.
    exit /b 1
)
echo       Signed manifest: dist\DupeZ_Setup.exe.manifest.json
echo       Signature:       dist\DupeZ_Setup.exe.manifest.sig

:skip_sign_manifest

"%DUPEZ_PYTHON%" scripts\sbom.py --out dist\DupeZ.sbom.json --product-version "%DUPEZ_VERSION%"
if errorlevel 1 exit /b 1
"%DUPEZ_PYTHON%" scripts\vulnerability_review.py --out dist\DupeZ.vulnerability-review.json
set "_VULNERABILITY_REVIEW_EXIT=%ERRORLEVEL%"
if "%_VULNERABILITY_REVIEW_EXIT%"=="1" (
    "%DUPEZ_PYTHON%" scripts\vex.py --review dist\DupeZ.vulnerability-review.json --out dist\DupeZ.vex.json --product-version "%DUPEZ_VERSION%"
    if errorlevel 1 exit /b 1
    echo ERROR: Active dependency advisories were reviewed and recorded in OpenVEX.
    echo        The release remains blocked until every finding is resolved.
    exit /b 1
)
if not "%_VULNERABILITY_REVIEW_EXIT%"=="0" (
    echo ERROR: Vulnerability review generation failed.
    exit /b 1
)
if exist "dist\DupeZ.vex.json" (
    echo ERROR: A zero-finding review must not produce dist\DupeZ.vex.json.
    exit /b 1
)
"%DUPEZ_PYTHON%" -I packaging\release_data.py emit-provenance ^
    --mode "%DUPEZ_RELEASE_MODE%" ^
    --out dist\binary-provenance.json
if errorlevel 1 (
    echo ERROR: Measured distribution binary provenance emission failed.
    exit /b 1
)

:: ── 9. Final report ─────────────────────────────────────────────────
echo.
echo [5/5] Build summary
echo ============================================
if "%DUPEZ_PORTABLE_ONLY%"=="1" (
    echo  PORTABLE ARTIFACT GENERATION COMPLETE
) else (
    echo  DISTRIBUTION ARTIFACT GENERATION COMPLETE
)
echo ============================================
echo.
echo   dist\DupeZ-GPU.exe                       ^(asInvoker, split, GPU map — RECOMMENDED^)
echo   dist\DupeZ-Compat.exe                    ^(requireAdministrator, inproc, legacy^)
if "%DUPEZ_PORTABLE_ONLY%"=="1" (
    echo   Installer and updater sidecars intentionally omitted.
    echo   Portable-only output is CI evidence, not a distribution candidate.
) else (
    echo   dist\DupeZ_v%DUPEZ_VERSION%_Setup.exe           ^(Inno Setup installer^)
    echo   dist\DupeZ_Setup.exe                     ^(stable versionless alias for landing page^)
    echo   dist\DupeZ_Setup.exe.manifest.json       ^(signed update manifest^)
    echo   dist\DupeZ_Setup.exe.manifest.sig        ^(Ed25519 signature envelope^)
    echo   dist\LICENSE.txt                          ^(project distribution terms^)
    echo   dist\SOURCE_AND_RELINK.txt                ^(source and rebuild route^)
    echo   dist\THIRD_PARTY_NOTICES.txt              ^(exact-lock third-party terms^)
    echo   dist\license-payload.json                 ^(hash-bound legal inventory^)
)
echo.
echo  Authenticode status: %DUPEZ_AUTHENTICODE_STATUS%
echo  Native release mode: %DUPEZ_RELEASE_MODE%
if "%DUPEZ_RELEASE_MODE%"=="standard-authenticode" (
    echo  Nested child status: the staged app\firewall\clumsy.exe copy was
    echo  Authenticode-signed, measured, and verified before both variants.
    echo  Tracked upstream native bytes remain unchanged.
) else (
    echo  Nested child status: the staged app\firewall\clumsy.exe copy is
    echo  source-exact and verified unsigned by explicit release policy.
)
if "%DUPEZ_PORTABLE_ONLY%"=="1" (
    echo  No release staging is permitted for portable-only output.
) else (
    echo  Signed updater sidecars, SBOM, clean lock-bound vulnerability review,
    echo  and binary provenance were generated for the distribution artifacts.
)
echo  Artifact generation is not release approval.
echo  Mandatory gates remain: distribution preflight, frozen runtime validation,
echo  manual validation, draft staging, and staged-download hash verification.
echo.

popd
endlocal
exit /b 0

:: ── Subroutine: sign_file ───────────────────────────────────────────
:: Usage: call :sign_file "dist\artifact.exe"
:: Signs only when signtool and DUPEZ_SIGN_CERT are configured.
:sign_file
set "_SIGN_TARGET=%~1"
set "DUPEZ_LAST_SIGNED=0"
if not exist "%_SIGN_TARGET%" exit /b 0
if not defined _SIGNTOOL exit /b 0
if "%DUPEZ_SIGN_CERT%"=="" exit /b 0
"%DUPEZ_PYTHON%" -I packaging\release_data.py verify-tool --name signtool --path "%_SIGNTOOL%"
if errorlevel 1 (
    echo       ERROR: Pinned SignTool verification failed for %_SIGN_TARGET%.
    exit /b 1
)
echo       Signing %_SIGN_TARGET% ...
if "%DUPEZ_SIGN_PASS%"=="" (
    "%_SIGNTOOL%" sign /tr "%DUPEZ_SIGN_TIMESTAMP_URL%" /td sha256 /fd sha256 /f "%DUPEZ_SIGN_CERT%" "%_SIGN_TARGET%"
) else (
    "%_SIGNTOOL%" sign /tr "%DUPEZ_SIGN_TIMESTAMP_URL%" /td sha256 /fd sha256 /f "%DUPEZ_SIGN_CERT%" /p "%DUPEZ_SIGN_PASS%" "%_SIGN_TARGET%"
)
if errorlevel 1 (
    echo       ERROR: Authenticode signing failed for %_SIGN_TARGET%.
    exit /b 1
)
set "DUPEZ_LAST_SIGNED=1"
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

:: ── Subroutine: force_remove_dir ───────────────────────────────────
:: Usage: call :force_remove_dir "path\to\directory"
:: Frees the target directory path even when transient file locks block delete.
:force_remove_dir
set "_FRD_TARGET=%~1"
if not exist "%_FRD_TARGET%" exit /b 0

:: Attempt 1 — rename out of the way so the canonical path is free.
set "_FRD_STALE=%_FRD_TARGET%.stale-%RANDOM%%RANDOM%"
move /y "%_FRD_TARGET%" "%_FRD_STALE%" >nul 2>&1
if not exist "%_FRD_TARGET%" (
    rmdir /s /q "%_FRD_STALE%" >nul 2>&1
    exit /b 0
)

:: Attempt 2 — direct remove retries on the original path.
set "_FRD_TRIES=0"
:force_remove_dir_retry
rmdir /s /q "%_FRD_TARGET%" >nul 2>&1
if not exist "%_FRD_TARGET%" exit /b 0
set /a _FRD_TRIES+=1
if %_FRD_TRIES% GEQ 10 (
    echo.
    echo ERROR: Could not remove stale build environment:
    echo        %_FRD_TARGET%
    echo A process is holding files in this directory.
    echo Close Python/PyInstaller sessions and retry.
    exit /b 1
)
powershell -NoProfile -Command "Start-Sleep -Milliseconds 1000" >nul 2>&1
goto :force_remove_dir_retry
