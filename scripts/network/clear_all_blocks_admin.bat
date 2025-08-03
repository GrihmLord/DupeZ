@echo off
echo 🚫 COMPREHENSIVE BLOCK CLEARANCE
echo ============================================
echo This script will clear ALL blocks affecting your PS5s
echo.
echo WARNING: Run as Administrator!
echo.

echo 🔥 Clearing firewall rules...
netsh advfirewall firewall delete rule name="*PulseDrop*"
netsh advfirewall firewall delete rule name="*Enterprise*"
netsh advfirewall firewall delete rule name="*NetCut*"
netsh advfirewall firewall delete rule name="*Block*"
netsh advfirewall firewall delete rule name="*PS5*"
netsh advfirewall firewall delete rule name="*PlayStation*"
netsh advfirewall firewall delete rule name="*Sony*"
netsh advfirewall firewall delete rule name="*Gaming*"

echo.
echo 🧹 Clearing hosts file blocks...
copy "C:\Windows\System32\drivers\etc\hosts" "C:\Windows\System32\drivers\etc\hosts.backup"
echo # Copyright (c) 1993-2009 Microsoft Corp. > "C:\Windows\System32\drivers\etc\hosts"
echo # >> "C:\Windows\System32\drivers\etc\hosts"
echo # This is a sample HOSTS file used by Microsoft TCP/IP for Windows. >> "C:\Windows\System32\drivers\etc\hosts"
echo # >> "C:\Windows\System32\drivers\etc\hosts"
echo # This file contains the mappings of IP addresses to host names. Each >> "C:\Windows\System32\drivers\etc\hosts"
echo # entry should be kept on an individual line. The IP address should >> "C:\Windows\System32\drivers\etc\hosts"
echo # be placed in the first column followed by the corresponding host name. >> "C:\Windows\System32\drivers\etc\hosts"
echo # The IP address and the host name should be separated by at least one >> "C:\Windows\System32\drivers\etc\hosts"
echo # space. >> "C:\Windows\System32\drivers\etc\hosts"
echo # >> "C:\Windows\System32\drivers\etc\hosts"
echo # Additionally, comments (such as these) may be inserted on individual >> "C:\Windows\System32\drivers\etc\hosts"
echo # lines or following the machine name denoted by a '#' symbol. >> "C:\Windows\System32\drivers\etc\hosts"
echo # >> "C:\Windows\System32\drivers\etc\hosts"
echo # For example: >> "C:\Windows\System32\drivers\etc\hosts"
echo # >> "C:\Windows\System32\drivers\etc\hosts"
echo #      102.54.94.97     rhino.acme.com          # source server >> "C:\Windows\System32\drivers\etc\hosts"
echo #       38.25.63.10     x.acme.com              # x client host >> "C:\Windows\System32\drivers\etc\hosts"
echo # >> "C:\Windows\System32\drivers\etc\hosts"
echo # localhost name resolution is handled within DNS itself. >> "C:\Windows\System32\drivers\etc\hosts"
echo #       127.0.0.1       localhost >> "C:\Windows\System32\drivers\etc\hosts"
echo #       ::1             localhost >> "C:\Windows\System32\drivers\etc\hosts"

echo.
echo 🛣️ Clearing route blocks...
route delete 192.168.1.154
route delete 192.168.1.180
route delete 192.168.1.181
route delete 192.168.137.1
route delete 192.168.137.165
route delete 192.168.137.217

echo.
echo 🌐 Clearing network caches...
ipconfig /flushdns
arp -d *

echo.
echo 🔄 Resetting network adapters...
netsh winsock reset
netsh int ip reset

echo.
echo ✅ All blocks cleared successfully!
echo.
echo 🎮 Your PS5s should now have internet access!
echo.
echo If they still don't work:
echo 1. Restart your PS5s
echo 2. Restart your router
echo 3. Check Ethernet cables
echo.
pause 