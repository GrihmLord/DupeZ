@echo off
:: fix_webengine.bat — repair QtWebEngine install for DupeZ
::
:: Root cause this fixes: PyQt6 and PyQt6-WebEngine were installed at
:: different minor versions (or the Qt6 runtime wheels drifted), so
:: QtWebEngineCore.dll fails to load and DupeZ falls back to a
:: placeholder map. We wipe every PyQt6/Qt6 wheel and reinstall them
:: all pinned to the same version in a single resolver pass.

setlocal ENABLEDELAYEDEXPANSION

echo.
echo === DupeZ QtWebEngine repair ===
echo.

:: Use the same python that runs dupez.py so we hit the right env.
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] python not on PATH. Open a shell where `python dupez.py` works and re-run.
    pause
    exit /b 1
)

echo [1/4] Uninstalling all existing PyQt6/Qt6 wheels (system + user site) ...
python -m pip uninstall -y PyQt6 PyQt6-Qt6 PyQt6-sip PyQt6-WebEngine PyQt6-WebEngine-Qt6 >nul 2>&1
python -m pip uninstall -y PyQt6 PyQt6-Qt6 PyQt6-sip PyQt6-WebEngine PyQt6-WebEngine-Qt6 >nul 2>&1

echo [2/4] Clearing pip cache for PyQt6 wheels ...
python -m pip cache remove "PyQt6*" >nul 2>&1

echo [3/4] Installing matched PyQt6 + PyQt6-WebEngine (single resolver pass) ...
:: Pin to 6.7.* (LTS-ish, wheels reliable on Windows). If you prefer
:: the 6.11 line you are already on, change both pins to 6.11.* — the
:: key thing is that BOTH packages resolve in a single pip call so
:: their Qt6 runtime wheels match.
python -m pip install --upgrade --force-reinstall "PyQt6==6.7.*" "PyQt6-WebEngine==6.7.*"
if errorlevel 1 (
    echo.
    echo [ERROR] pip install failed. Scroll up for the real error.
    pause
    exit /b 1
)

echo [4/4] Verifying QtWebEngine can actually import ...
python -c "from PyQt6.QtWebEngineCore import QWebEngineProfile; from PyQt6.QtWebEngineWidgets import QWebEngineView; print('OK:', QWebEngineView)"
if errorlevel 1 (
    echo.
    echo [FAIL] QtWebEngine still will not import. The line above is the real reason.
    echo        Common causes:
    echo          - Another Qt6 install on PATH is shadowing the wheel DLLs.
    echo            Check:  where Qt6Core.dll
    echo          - Antivirus quarantined QtWebEngineProcess.exe.
    echo          - Running from a venv that does not have the wheels.
    pause
    exit /b 1
)

echo.
echo === DONE. Start DupeZ with `python dupez.py` and the iZurvive map should load. ===
echo.
pause
endlocal
