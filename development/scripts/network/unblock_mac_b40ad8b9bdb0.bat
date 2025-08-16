@echo off
echo ========================================
echo    Unblock MAC Address: b40ad8b9bdb0
echo ========================================
echo.

echo [1/4] Finding IP address for MAC b40ad8b9bdb0...
for /f "tokens=1,2" %%a in ('arp -a ^| findstr "b4"') do (
    echo Found device: %%a (%%b)
    set DEVICE_IP=%%a
)

echo.
echo [2/4] Clearing hosts file blocks for this device...
powershell -Command "(Get-Content 'C:\Windows\System32\drivers\etc\hosts') | Where-Object { $_ -notmatch '192\.168\.' } | Set-Content 'C:\Windows\System32\drivers\etc\hosts'"
echo ✓ Hosts file blocks cleared

echo.
echo [3/4] Clearing route table blocks...
route delete 192.168.1.154 >nul 2>&1
route delete 192.168.1.180 >nul 2>&1
route delete 192.168.1.181 >nul 2>&1
route delete 192.168.137.165 >nul 2>&1
route delete 192.168.137.217 >nul 2>&1
route delete 192.168.1.93 >nul 2>&1
route delete 192.168.1.96 >nul 2>&1
echo ✓ Route table blocks cleared

echo.
echo [4/4] Clearing caches and testing...
ipconfig /flushdns >nul 2>&1
arp -d * >nul 2>&1
echo ✓ Caches cleared

echo.
echo Testing connectivity to common PS5 IPs:
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
echo    Unblock Complete!
echo ========================================
echo.
echo Device with MAC b40ad8b9bdb0 should now be unblocked.
echo If this is your PS5, it should now have internet access.
echo.
pause 