@echo off
echo.
echo ========================================
echo    PS5 INTERNET RESTORATION TOOL
echo ========================================
echo.
echo This tool will restore your PS5's internet access
echo by clearing all PulseDrop-related blocks.
echo.
echo WARNING: This tool requires administrator privileges.
echo.
pause

echo.
echo Starting PS5 internet restoration...
echo.

python restore_ps5_internet.py

echo.
echo ========================================
echo    RESTORATION COMPLETE
echo ========================================
echo.
echo If your PS5 still doesn't have internet:
echo 1. Restart your PS5
echo 2. Restart your router  
echo 3. Check your router's DHCP settings
echo.
pause 