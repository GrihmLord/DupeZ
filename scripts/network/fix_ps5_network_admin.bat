@echo off
echo ========================================
echo    PS5 Network Fix (Run as Administrator)
echo ========================================
echo.

echo [1/4] Clearing hosts file blocks...
echo Current hosts file entries:
type C:\Windows\System32\drivers\etc\hosts | findstr "192.168"
echo.

echo Clearing blocked entries...
powershell -Command "(Get-Content 'C:\Windows\System32\drivers\etc\hosts') | Where-Object { $_ -notmatch '192\.168\.' } | Set-Content 'C:\Windows\System32\drivers\etc\hosts'"
echo ✓ Hosts file cleared

echo.
echo [2/4] Clearing route table blocks...
route delete 192.168.1.154 >nul 2>&1
route delete 192.168.1.180 >nul 2>&1
route delete 192.168.1.181 >nul 2>&1
route delete 192.168.137.165 >nul 2>&1
route delete 192.168.137.217 >nul 2>&1
route delete 192.168.1.93 >nul 2>&1
route delete 192.168.1.96 >nul 2>&1
echo ✓ Route table cleared

echo.
echo [3/4] Clearing caches...
ipconfig /flushdns >nul 2>&1
arp -d * >nul 2>&1
echo ✓ Caches cleared

echo.
echo [4/4] Testing connectivity...
ping -n 1 192.168.1.93 >nul 2>&1
if %errorlevel%==0 (
    echo ✓ 192.168.1.93 is reachable
) else (
    echo ✗ 192.168.1.93 is not reachable
)

ping -n 1 192.168.1.96 >nul 2>&1
if %errorlevel%==0 (
    echo ✓ 192.168.1.96 is reachable
) else (
    echo ✗ 192.168.1.96 is not reachable
)

echo.
echo ========================================
echo    PS5 Network Fix Complete!
echo ========================================
echo.
echo Your PS5 should now be able to connect to the network.
echo If it still doesn't work:
echo 1. Restart your PS5
echo 2. Check your router settings
echo 3. Try WiFi instead of Ethernet
echo.
pause 