@echo off
echo ========================================
echo    PS5 Connection Restoration Script
echo ========================================
echo.

echo [1/6] Clearing Windows Firewall rules...
netsh advfirewall firewall delete rule name="*PS5*" >nul 2>&1
netsh advfirewall firewall delete rule name="*PulseDrop*" >nul 2>&1
echo ✓ Firewall rules cleared

echo.
echo [2/6] Clearing route table blocks...
route delete 192.168.1.154 >nul 2>&1
route delete 192.168.1.180 >nul 2>&1
route delete 192.168.1.181 >nul 2>&1
route delete 192.168.137.165 >nul 2>&1
route delete 192.168.137.217 >nul 2>&1
route delete 192.168.1.93 >nul 2>&1
route delete 192.168.1.96 >nul 2>&1
echo ✓ Route table blocks cleared

echo.
echo [3/6] Clearing hosts file blocks...
echo Creating backup of hosts file...
copy "C:\Windows\System32\drivers\etc\hosts" "C:\Windows\System32\drivers\etc\hosts.backup" >nul 2>&1

echo Clearing hosts file entries...
powershell -Command "(Get-Content 'C:\Windows\System32\drivers\etc\hosts') | Where-Object { $_ -notmatch '192\.168\.' } | Set-Content 'C:\Windows\System32\drivers\etc\hosts'"
echo ✓ Hosts file blocks cleared

echo.
echo [4/6] Clearing DNS cache...
ipconfig /flushdns >nul 2>&1
echo ✓ DNS cache cleared

echo.
echo [5/6] Clearing ARP cache...
arp -d * >nul 2>&1
echo ✓ ARP cache cleared

echo.
echo [6/6] Testing PS5 connectivity...
echo.
echo Testing common PS5 IP addresses:
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
echo    Restoration Complete!
echo ========================================
echo.
echo All blocks have been cleared. Your PS5 should now have internet access.
echo.
echo If your PS5 still doesn't have internet:
echo 1. Restart your PS5
echo 2. Check your router settings
echo 3. Try connecting via WiFi instead of Ethernet
echo.
pause 