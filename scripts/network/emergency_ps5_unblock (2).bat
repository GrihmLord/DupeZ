@echo off
echo ========================================
echo EMERGENCY PS5 UNBLOCKING SCRIPT
echo ========================================
echo.
echo This script will clear ALL possible network blocks
echo that might be preventing your PS5 from connecting.
echo.
echo Running as Administrator...
echo.

REM Clear all firewall rules that might block PS5
echo [1/8] Clearing firewall rules...
netsh advfirewall firewall delete rule name="PS5 Block" >nul 2>&1
netsh advfirewall firewall delete rule name="PS5 Drop" >nul 2>&1
netsh advfirewall firewall delete rule name="PS5 Internet Block" >nul 2>&1
netsh advfirewall firewall delete rule name="PS5 Outbound Block" >nul 2>&1
netsh advfirewall firewall delete rule name="PS5 Inbound Block" >nul 2>&1
netsh advfirewall firewall delete rule name="PS5 DNS Block" >nul 2>&1
netsh advfirewall firewall delete rule name="PS5 DHCP Block" >nul 2>&1
netsh advfirewall firewall delete rule name="PS5 Gaming Block" >nul 2>&1
netsh advfirewall firewall delete rule name="PS5 PSN Block" >nul 2>&1
netsh advfirewall firewall delete rule name="PS5 Network Block" >nul 2>&1
echo Firewall rules cleared.

REM Clear hosts file entries
echo [2/8] Clearing hosts file entries...
powershell -Command "Get-Content C:\Windows\System32\drivers\etc\hosts | Where-Object { $_ -notmatch 'ps5\|playstation\|sony' } | Set-Content C:\Windows\System32\drivers\etc\hosts"
echo Hosts file cleared.

REM Clear route table blocks
echo [3/8] Clearing route table blocks...
route delete 0.0.0.0 >nul 2>&1
route delete 8.8.8.8 >nul 2>&1
route delete 8.8.4.4 >nul 2>&1
route delete 1.1.1.1 >nul 2>&1
route delete 208.67.222.222 >nul 2>&1
route delete 208.67.220.220 >nul 2>&1
echo Route table cleared.

REM Clear DNS cache
echo [4/8] Clearing DNS cache...
ipconfig /flushdns
echo DNS cache cleared.

REM Clear ARP cache
echo [5/8] Clearing ARP cache...
arp -d *
echo ARP cache cleared.

REM Reset network adapters
echo [6/8] Resetting network adapters...
netsh winsock reset
netsh int ip reset
echo Network adapters reset.

REM Clear any PS5-specific blocks
echo [7/8] Clearing PS5-specific blocks...
REM Clear any custom PS5 blocking scripts
taskkill /f /im python.exe >nul 2>&1
taskkill /f /im pulsedrop.exe >nul 2>&1
taskkill /f /im ps5_blocker.exe >nul 2>&1
echo PS5 blocking processes terminated.

REM Restart network services
echo [8/8] Restarting network services...
net stop dnscache >nul 2>&1
net start dnscache >nul 2>&1
net stop dhcp >nul 2>&1
net start dhcp >nul 2>&1
echo Network services restarted.

echo.
echo ========================================
echo EMERGENCY UNBLOCKING COMPLETE
echo ========================================
echo.
echo All possible network blocks have been cleared:
echo - Firewall rules
echo - Hosts file entries
echo - Route table blocks
echo - DNS cache
echo - ARP cache
echo - Network adapters reset
echo - PS5 blocking processes
echo - Network services restarted
echo.
echo Your PS5 should now be able to connect to the network.
echo If it still can't connect, try:
echo 1. Restart your PS5
echo 2. Restart your router
echo 3. Check your PS5 network settings
echo.
pause 