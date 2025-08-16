@echo off
echo ========================================
echo PS5 WIFI CONNECTIVITY FIX SCRIPT
echo ========================================
echo.
echo This script will reset network settings
echo and prepare for PS5 WiFi connection.
echo.

REM Reset WiFi adapters
echo [1/4] Resetting WiFi adapters...
netsh wlan reset
echo WiFi adapters reset.

REM Clear network caches
echo [2/4] Clearing network caches...
ipconfig /flushdns
ipconfig /release
ipconfig /renew
echo Network caches cleared.

REM Reset network adapters
echo [3/4] Resetting network adapters...
netsh winsock reset
netsh int ip reset
echo Network adapters reset.

REM Restart network services
echo [4/4] Restarting network services...
net stop dnscache >nul 2>&1
net start dnscache >nul 2>&1
echo Network services restarted.

echo.
echo ========================================
echo WIFI FIX COMPLETE
echo ========================================
echo.
echo Your network is now ready for PS5 WiFi connection.
echo Please configure PS5 to use WiFi or Ethernet as needed.
echo.
pause
