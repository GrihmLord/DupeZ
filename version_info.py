# -*- coding: utf-8 -*-
#
# PyInstaller version info for DupeZ Windows executable.
#
# This file is referenced by dupez.spec to embed VS_VERSION_INFO
# into the .exe, which Windows uses for:
#   - Properties dialog (right-click -> Properties -> Details)
#   - SmartScreen / WDAC trust scoring (signed + versioned > unsigned)
#   - Application compatibility database lookups
#
# Usage in spec:  exe = EXE(..., version='version_info.py')
#
# NOTE: PyInstaller parses this file with eval(), which accepts exactly
# one expression. Do NOT add a module docstring, imports, or assignments
# above the VSVersionInfo(...) call — eval() will reject multi-statement
# input with SyntaxError.

VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(5, 2, 2, 0),
        prodvers=(5, 2, 2, 0),
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
                    StringStruct('FileVersion',      '5.2.2.0'),
                    StringStruct('InternalName',     'dupez'),
                    StringStruct('LegalCopyright',   'Copyright © 2024-2026 DupeZ. All rights reserved.'),
                    StringStruct('OriginalFilename', 'dupez.exe'),
                    StringStruct('ProductName',      'DupeZ'),
                    StringStruct('ProductVersion',   '5.2.2.0'),
                ],
            ),
        ]),
        VarFileInfo([VarStruct('Translation', [0x0409, 0x04B0])]),
    ],
)
