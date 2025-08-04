@echo off
echo ========================================
echo PS5 NETWORK RESTORATION SCRIPT
echo ========================================
echo.
echo This script will clear any remaining blocks
echo and prepare your network for PS5 connection.
echo.

REM Clear any remaining PS5 blocks
echo [1/4] Clearing remaining PS5 blocks...
netsh advfirewall firewall delete rule name="PS5*" >nul 2>&1
echo Firewall rules cleared.

REM Clear DNS and network caches
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
echo PS5 RESTORATION COMPLETE
echo ========================================
echo.
echo Your network is now ready for PS5 connection.
echo Please follow the PS5 setup instructions provided.
echo.
pause
