#!/usr/bin/env python3
"""
Clear all blocks from hosts file
"""

import os
import shutil

def clear_hosts_file():
    """Clear all blocks from hosts file"""
    hosts_file = r"C:\Windows\System32\drivers\etc\hosts"
    backup_file = r"C:\Windows\System32\drivers\etc\hosts.backup"
    
    try:
        # Create backup
        if os.path.exists(hosts_file):
            shutil.copy2(hosts_file, backup_file)
            print("✅ Created backup of hosts file")
        
        # Write clean hosts file
        clean_content = """# Copyright (c) 1993-2009 Microsoft Corp.
#
# This is a sample HOSTS file used by Microsoft TCP/IP for Windows.
#
# This file contains the mappings of IP addresses to host names. Each
# entry should be kept on an individual line. The IP address should
# be placed in the first column followed by the corresponding host name.
# The IP address and the host name should be separated by at least one
# space.
#
# Additionally, comments (such as these) may be inserted on individual
# lines or following the machine name denoted by a '#' symbol.
#
# For example:
#
#      102.54.94.97     rhino.acme.com          # source server
#       38.25.63.10     x.acme.com              # x client host

# localhost name resolution is handled within DNS itself.
#       127.0.0.1       localhost
#       ::1             localhost
"""
        
        with open(hosts_file, 'w') as f:
            f.write(clean_content)
        
        print("✅ Hosts file cleared successfully")
        print("✅ All PulseDrop blocks removed from hosts file")
        
    except PermissionError:
        print("❌ Permission denied - run as administrator")
        return False
    except Exception as e:
        print(f"❌ Error clearing hosts file: {e}")
        return False
    
    return True

if __name__ == "__main__":
    print("🧹 CLEARING HOSTS FILE BLOCKS")
    print("=" * 50)
    clear_hosts_file()
    print("\n🎉 Hosts file cleanup complete!") 