; ============================================================================
; DupeZ v5.8.0 — Inno Setup Installer
; ============================================================================
; Produces a 64-bit upgrade-in-place installer with clean uninstall metadata,
; Start Menu/Desktop shortcuts, GPU and Compat variants, and optional
; Authenticode signing through the release pipeline.
;
; CANONICAL RELEASE BUILD (run from repo root):
;   packaging\build_variants.bat
; Direct ISCC invocation is unsupported and fails closed without the private
; native snapshot created by packaging\release_data.py.
;   Output: dist\DupeZ_v5.8.0_Setup.exe
;
; SourceDir=.. resolves all Source paths from the repository root.
; ============================================================================

#define MyAppName      "DupeZ"
#define MyAppVersion   "5.8.0"
#define MyAppPublisher "DupeZ"
#define MyAppURL       "https://github.com/GrihmLord/DupeZ"
#define MyAppExeName   "dupez.exe"
#define MyAppUpdater   "DupeZ_v" + MyAppVersion + "_Setup.exe"

#define DupeZNativeSnapshot GetEnv("DUPEZ_INSTALLER_NATIVE_SNAPSHOT")
#if DupeZNativeSnapshot == ""
  #error "DUPEZ_INSTALLER_NATIVE_SNAPSHOT is required; run packaging\build_variants.bat"
#endif

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
LicenseFile=dist\LICENSE.txt
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; WinDivert64.sys is an x64 kernel driver and cannot run under ARM64 x64 emulation.
ArchitecturesInstallIn64BitMode=x64os
ArchitecturesAllowed=x64os
; Explicitly retain Inno Setup's junction/symlink traversal mitigation for both
; elevated install and uninstall, even if a future compiler default changes.
RedirectionGuard=yes
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
; Exact-lock legal payload generated and verified before ISCC is invoked.
Source: "dist\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\SOURCE_AND_RELINK.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\license-payload.json"; DestDir: "{app}"; Flags: ignoreversion

; Fail-closed managed payload. Keep these entries synchronized with
; packaging\release-data.json; scripts\release_preflight.py rejects wildcard,
; recursive, unlisted, renamed, or misdirected installer sources.

; Pinned firewall runtime binaries must come from release_data.py's private
; snapshot of the fixed, verified native stage. Standard builds sign only the
; staged clumsy.exe; explicit unsigned builds prove the staged bytes remain
; source-exact. Never package the tracked source files directly or recurse into
; app\firewall\clumsy_src / vendored WinDivert sample utilities.
Source: "{#DupeZNativeSnapshot}\app\firewall\WinDivert.dll"; DestDir: "{app}\app\firewall"; Flags: ignoreversion
Source: "{#DupeZNativeSnapshot}\app\firewall\WinDivert64.sys"; DestDir: "{app}\app\firewall"; Flags: ignoreversion
Source: "{#DupeZNativeSnapshot}\app\firewall\clumsy.exe"; DestDir: "{app}\app\firewall"; Flags: ignoreversion
Source: "{#DupeZNativeSnapshot}\app\firewall\iup.dll"; DestDir: "{app}\app\firewall"; Flags: ignoreversion

; Runtime data is file-by-file so local cache, HMAC, source, and mutable state
; files can never be swept into a release installer.
Source: "app\assets\icon.ico"; DestDir: "{app}\app\assets"; Flags: ignoreversion
Source: "app\assets\icon_fixed.ico"; DestDir: "{app}\app\assets"; Flags: ignoreversion
Source: "app\config\dayz_duping_config.json"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "app\config\dayz_firewall.json"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "app\config\dayz_loot.json"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "app\config\dayz_markers.json"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "app\config\dayz_servers.json"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "app\config\dayz_tips_tricks.json"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "app\config\game_profiles\dayz.json"; DestDir: "{app}\app\config\game_profiles"; Flags: ignoreversion
Source: "app\config\gaming_rules.json"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "app\config\latency_config.json"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "app\config\memory_optimization.json"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "app\config\network_optimization.json"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "app\config\network_rules.json"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "app\config\profiles.json"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "app\config\settings.json"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "app\config\stability_config.json"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "app\resources\dupez.ico"; DestDir: "{app}\app\resources"; Flags: ignoreversion
Source: "app\resources\dupez.png"; DestDir: "{app}\app\resources"; Flags: ignoreversion
Source: "app\themes\dark.qss"; DestDir: "{app}\app\themes"; Flags: ignoreversion
Source: "app\themes\hacker.qss"; DestDir: "{app}\app\themes"; Flags: ignoreversion
Source: "app\themes\light.qss"; DestDir: "{app}\app\themes"; Flags: ignoreversion
Source: "app\themes\rainbow.qss"; DestDir: "{app}\app\themes"; Flags: ignoreversion

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
