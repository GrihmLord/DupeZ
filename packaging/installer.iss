; ============================================================================
; DupeZ v5.7.9 — Inno Setup Installer
; ============================================================================
; Produces a 64-bit upgrade-in-place installer with clean uninstall metadata,
; Start Menu/Desktop shortcuts, GPU and Compat variants, and optional
; Authenticode signing through the release pipeline.
;
; BUILD (run from repo root):
;   1. Build both variants:  packaging\build_variants.bat
;   2. Compile directly:     iscc packaging\installer.iss
;   Output: dist\DupeZ_v5.7.9_Setup.exe
;
; SourceDir=.. resolves all Source paths from the repository root.
; ============================================================================

#define MyAppName      "DupeZ"
#define MyAppVersion   "5.7.9"
#define MyAppPublisher "DupeZ"
#define MyAppURL       "https://github.com/GrihmLord/DupeZ"
#define MyAppExeName   "dupez.exe"
#define MyAppUpdater   "DupeZ_v" + MyAppVersion + "_Setup.exe"

[Setup]
; Stable App ID — never change between versions.
AppId={{7E2F9B4A-3C1D-4E8F-A5B6-D9C0E1F23456}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
AppContact=https://github.com/GrihmLord
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
SourceDir=..
OutputDir=dist
OutputBaseFilename=DupeZ_v{#MyAppVersion}_Setup
PrivilegesRequired=admin
Compression=lzma2/ultra64
SolidCompression=yes
SetupIconFile=app\resources\dupez.ico
WizardStyle=modern
WizardSizePercent=110
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} v{#MyAppVersion}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} — Network Disruption Toolkit
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}.0
VersionInfoCopyright=Copyright (C) 2024-2026 DupeZ
MinVersion=10.0

; Use Inno Setup's Restart Manager integration instead of a custom taskkill
; sweep.  The GPU installer name is dupez.exe; portable GPU and Compat names
; are included so an upgrade also handles users running either raw variant.
CloseApplications=yes
CloseApplicationsFilter=dupez.exe,DupeZ-GPU.exe,DupeZ-Compat.exe
RestartApplications=no

; Signing is performed after compilation by packaging\build_variants.bat so the
; same RFC3161/SHA-256 policy is applied to portables, versioned installer, and
; stable installer alias.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startmenu"; Description: "Create Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Recommended split/GPU variant is installed under the stable updater name.
Source: "dist\DupeZ-GPU.exe"; DestDir: "{app}"; DestName: "dupez.exe"; Flags: ignoreversion
; Compat remains available for blocklisted or problematic GPU systems.
Source: "dist\DupeZ-Compat.exe"; DestDir: "{app}"; Flags: ignoreversion

; Pinned firewall binaries used by the packaged runtime.
Source: "app\firewall\*.dll"; DestDir: "{app}\app\firewall"; Flags: ignoreversion recursesubdirs
Source: "app\firewall\*.sys"; DestDir: "{app}\app\firewall"; Flags: ignoreversion recursesubdirs
Source: "app\firewall\*.exe"; DestDir: "{app}\app\firewall"; Flags: ignoreversion recursesubdirs

; Explicit runtime data directories.
Source: "app\config\*"; DestDir: "{app}\app\config"; Flags: ignoreversion recursesubdirs
Source: "app\themes\*"; DestDir: "{app}\app\themes"; Flags: ignoreversion recursesubdirs
Source: "app\resources\*"; DestDir: "{app}\app\resources"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenu; Comment: "Launch DupeZ"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "Launch DupeZ"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenu; Comment: "Remove DupeZ"

[Run]
; Interactive install: optional launch as the original desktop user.  This is
; required for the recommended split/GPU architecture; its helper elevates only
; the privileged packet-engine process.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent runascurrentuser
; Silent updater path: relaunch after a successful replacement.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifdoesntexist runascurrentuser; Check: WizardSilent

[Registry]
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{#MyAppExeName}"; \
    ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{#MyAppExeName}"; \
    ValueType: string; ValueName: "Path"; ValueData: "{app}"; Flags: uninsdeletekey

Root: HKLM; Subkey: "SOFTWARE\{#MyAppPublisher}\{#MyAppName}"; \
    ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\{#MyAppPublisher}\{#MyAppName}"; \
    ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekey

Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{{7E2F9B4A-3C1D-4E8F-A5B6-D9C0E1F23456}_is1"; \
    ValueType: string; ValueName: "DisplayIcon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{{7E2F9B4A-3C1D-4E8F-A5B6-D9C0E1F23456}_is1"; \
    ValueType: string; ValueName: "URLInfoAbout"; ValueData: "{#MyAppURL}"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{{7E2F9B4A-3C1D-4E8F-A5B6-D9C0E1F23456}_is1"; \
    ValueType: string; ValueName: "URLUpdateInfo"; ValueData: "{#MyAppURL}/releases"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{{7E2F9B4A-3C1D-4E8F-A5B6-D9C0E1F23456}_is1"; \
    ValueType: string; ValueName: "HelpLink"; ValueData: "{#MyAppURL}/issues"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{{7E2F9B4A-3C1D-4E8F-A5B6-D9C0E1F23456}_is1"; \
    ValueType: dword; ValueName: "EstimatedSize"; ValueData: "204800"; Flags: uninsdeletevalue
