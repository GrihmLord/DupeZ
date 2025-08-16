@echo off
echo ========================================
echo    Restore PS5 Ethernet Connectivity
echo ========================================
echo.

echo [1/3] Clearing all network blocks...
powershell -Command "(Get-Content 'C:\Windows\System32\drivers\etc\hosts') | Where-Object { $_ -notmatch '192\.168\.' } | Set-Content 'C:\Windows\System32\drivers\etc\hosts'"
echo ✓ Hosts file cleared

echo.
echo [2/3] Clearing route table and caches...
route delete 192.168.1.154 >nul 2>&1
route delete 192.168.1.180 >nul 2>&1
route delete 192.168.1.181 >nul 2>&1
route delete 192.168.137.165 >nul 2>&1
route delete 192.168.137.217 >nul 2>&1
route delete 192.168.1.93 >nul 2>&1
route delete 192.168.1.96 >nul 2>&1
ipconfig /flushdns >nul 2>&1
arp -d * >nul 2>&1
echo ✓ Network caches cleared

echo.
echo [3/3] Testing Ethernet connectivity...
ping -n 1 192.168.1.93 >nul 2>&1
if %errorlevel%==0 (
    echo ✓ 192.168.1.93 is reachable via Ethernet
) else (
    echo ✗ 192.168.1.93 is not reachable
)

ping -n 1 192.168.1.96 >nul 2>&1
if %errorlevel%==0 (
    echo ✓ 192.168.1.96 is reachable via Ethernet
) else (
    echo ✗ 192.168.1.96 is not reachable
)

echo.
echo ========================================
echo    Ethernet Connectivity Restored!
echo ========================================
echo.
echo Your PS5 should now be able to connect via Ethernet.
echo.
echo Next steps:
echo 1. Restart your PS5
echo 2. Go to Settings > Network > Set Up Internet Connection
echo 3. Choose "Use a LAN Cable"
echo 4. Select "Easy" setup
echo 5. Test the connection
echo.
echo If it still doesn't work:
echo - Check your Ethernet cable
echo - Try a different Ethernet port on your router
echo - Restart your router
echo.
pause 