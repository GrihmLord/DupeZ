@echo off
echo 🧹 CLEARING HOSTS FILE BLOCKS
echo ============================================
echo.

echo Creating backup of hosts file...
copy "C:\Windows\System32\drivers\etc\hosts" "C:\Windows\System32\drivers\etc\hosts.backup"

echo.
echo Clearing all blocks from hosts file...
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
echo ✅ Hosts file cleared successfully!
echo ✅ All PulseDrop blocks removed from hosts file
echo.
echo 🎉 Hosts file cleanup complete!
echo.
pause 