@echo off
echo 🔧 Fixing PS5 Network Issues - CE-109503-8
echo ============================================
echo.

echo 🧹 Removing all PulseDrop firewall rules...
netsh advfirewall firewall delete rule name="PulseDropEnterprise_Block_In_192.168.137.1"
netsh advfirewall firewall delete rule name="PulseDropEnterprise_Block_Out_192.168.137.1"
netsh advfirewall firewall delete rule name="PulseDropEnterprise_Block_In_192.168.1.180"
netsh advfirewall firewall delete rule name="PulseDropEnterprise_Block_Out_192.168.1.180"
netsh advfirewall firewall delete rule name="PulseDropEnterprise_Block_In_192.168.1.154"
netsh advfirewall firewall delete rule name="PulseDropEnterprise_Block_Out_192.168.1.154"
netsh advfirewall firewall delete rule name="PulseDropEnterprise_Block_In_192.168.1.181"
netsh advfirewall firewall delete rule name="PulseDropEnterprise_Block_Out_192.168.1.181"
netsh advfirewall firewall delete rule name="PulseDropEnterprise_192.168.137.217_icmp"
netsh advfirewall firewall delete rule name="PulseDropEnterprise_192.168.137.217_udp"
netsh advfirewall firewall delete rule name="PulseDropEnterprise_192.168.137.217_tcp"
netsh advfirewall firewall delete rule name="PulseDropEnterprise_192.168.137.217_in"
netsh advfirewall firewall delete rule name="PulseDropEnterprise_192.168.137.217_out"

echo.
echo 🔄 Flushing DNS cache...
ipconfig /flushdns

echo.
echo 🔄 Releasing and renewing IP addresses...
ipconfig /release
ipconfig /renew

echo.
echo 🔄 Resetting network adapters...
netsh winsock reset
netsh int ip reset

echo.
echo ✅ Network cleanup completed!
echo.
echo 🎮 Now try connecting your PS5 again.
echo    It should be able to obtain an IP address now.
echo.
pause 