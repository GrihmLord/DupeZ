@echo off
echo ========================================
echo DupeZ iZurvive Map Integration Rebuild
echo ========================================
echo.

echo [1/5] Installing WebEngine dependencies...
pip install -r requirements_webengine.txt

echo.
echo [2/5] Cleaning previous build...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "__pycache__" rmdir /s /q "__pycache__"
if exist "*.spec" del "*.spec"

echo.
echo [3/5] Building application with iZurvive...
pyinstaller --onefile --windowed --icon=app/assets/icon.ico --name=DupeZ_izurvive app/main.py

echo.
echo [4/5] Copying additional files...
if not exist "dist\DupeZ_izurvive" mkdir "dist\DupeZ_izurvive"
xcopy "app\assets" "dist\DupeZ_izurvive\app\assets" /E /I /Y
xcopy "app\config" "dist\DupeZ_izurvive\app\config" /E /I /Y

echo.
echo [5/5] Build complete!
echo.
echo The new DupeZ application with iZurvive integration is ready!
echo Location: dist\DupeZ_izurvive.exe
echo.
echo Features:
echo - Full iZurvive DayZ map integration
echo - Interactive map controls
echo - GPS coordinate system
echo - Marker management
echo - Export/Import functionality
echo.
pause
