# -*- coding: utf-8 -*-
#
# PyInstaller version info for DupeZ Windows executable.
#
# Embeds file/product version, company, copyright, and description
# into the PE resource table so Windows Explorer's Properties dialog
# and Task Manager show accurate metadata. This is also what:
#   - SmartScreen / WDAC trust scoring (signed + versioned > unsigned)
#   - Registry uninstall entries
#   - crash reporters
# read to identify the binary.
#
# IMPORTANT: the VSVersionInfo(...) expression must be a single
# expression tree. Do not put `from PyInstaller... import *`
# above the VSVersionInfo(...) call — eval() will reject multi-statement
# input with SyntaxError.

VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(5, 6, 2, 0),
        prodvers=(5, 6, 2, 0),
        mask=0x3F,
        flags=0x0,
        OS=0x40004,          # VOS_NT_WINDOWS32
        fileType=0x1,        # VFT_APP
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringTable(
                '040904B0',  # lang=US-English, charset=Unicode
                [
                    StringStruct('CompanyName',      'DupeZ'),
                    StringStruct('FileDescription',  'DupeZ — Network Packet Interception Utility'),
                    StringStruct('FileVersion',      '5.6.2.0'),
                    StringStruct('InternalName',     'dupez'),
                    StringStruct('LegalCopyright',   'Copyright © 2024-2026 DupeZ. All rights reserved.'),
                    StringStruct('OriginalFilename', 'dupez.exe'),
                    StringStruct('ProductName',      'DupeZ'),
                    StringStruct('ProductVersion',   '5.6.2.0'),
                ],
            ),
        ]),
        VarFileInfo([VarStruct('Translation', [0x0409, 0x04B0])]),
    ],
)
