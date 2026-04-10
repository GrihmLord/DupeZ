; ============================================================================
; DupeZ v5.2 — Inno Setup Installer Script
; ============================================================================
; This installer makes DupeZ show up in Windows "Installed Apps" / "Add or
; Remove Programs", supports clean uninstall, and creates Start Menu +
; Desktop shortcuts so users never have to hunt for the exe.
;
; WHY AN INSTALLER:
;   Windows Application Control (WDAC) and SmartScreen treat .exe files
;   downloaded from the internet as untrusted (Mark-of-the-Web / MOTW).
;   A proper installer:
;     1. Strips MOTW from all extracted files automatically
;     2. Installs into a trusted path (Program Files)
;     3. Creates clean shortcuts (no MOTW inheritance)
;     4. Registers in Add/Remove Programs with version, publisher, icon
;     5. When code-signed, passes SmartScreen immediately
;
; BUILD:
;   1. Build dupez.exe first:   pyinstaller dupez.spec --noconfirm
;   2. Then compile installer:  iscc installer.iss
;   Output: dist\DupeZ_v5.2.3_Setup.exe
; ============================================================================

#define MyAppName      "DupeZ"
#define MyAppVersion   "5.2.3"
#define MyAppPublisher "DupeZ"
#define MyAppURL       "https://github.com/GrihmLord/DupeZ"
#define MyAppExeName   "dupez.exe"
#define MyAppUpdater   "DupeZ_v" + MyAppVersion + "_Setup.exe"

[Setup]
; Unique App ID — DO NOT CHANGE between versions (enables upgrade-in-place)
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
DisableProgramGroupPage=yes
; Allow user to upgrade without uninstalling first
UsePreviousAppDir=yes
; Output location and naming
OutputDir=dist
OutputBaseFilename=DupeZ_v{#MyAppVersion}_Setup
; Require admin (DupeZ needs admin for WinDivert)
PrivilegesRequired=admin
; Compression — LZMA2/ultra for smallest installer
Compression=lzma2/ultra64
SolidCompression=yes
; Visual
SetupIconFile=app\resources\dupez.ico
WizardStyle=modern
WizardSizePercent=110
; Uninstaller — this is what makes it show in "Installed Apps"
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} v{#MyAppVersion}
; Version info embedded in the installer exe itself
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} — Network Disruption Toolkit
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}.0
VersionInfoCopyright=Copyright (C) 2024-2026 DupeZ
; Min Windows version: Windows 10
MinVersion=10.0
; Close running instances before upgrading
CloseApplications=yes
CloseApplicationsFilter=dupez.exe
RestartApplications=no
; Sign the installer if signtool is configured
; SignTool=signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /a $f

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startmenu";   Description: "Create Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Main executable (built by PyInstaller)
Source: "dist\dupez.exe"; DestDir: "{app}"; Flags: ignoreversion

; Bundled firewall binaries (WinDivert, clumsy)
Source: "app\firewall\*.dll"; DestDir: "{app}\app\firewall"; Flags: ignoreversion recursesubdirs
Source: "app\firewall\*.sys"; DestDir: "{app}\app\firewall"; Flags: ignoreversion recursesubdirs
Source: "app\firewall\*.exe"; DestDir: "{app}\app\firewall"; Flags: ignoreversion recursesubdirs

; Config, themes, assets
Source: "app\config\*";     DestDir: "{app}\app\config";     Flags: ignoreversion recursesubdirs
Source: "app\themes\*";     DestDir: "{app}\app\themes";     Flags: ignoreversion recursesubdirs
Source: "app\resources\*";  DestDir: "{app}\app\resources";  Flags: ignoreversion recursesubdirs

[Icons]
; Start menu shortcut
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenu; Comment: "Launch DupeZ"
; Desktop shortcut (checked by default so users find it easily)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "Launch DupeZ"
; Uninstaller in start menu
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenu; Comment: "Remove DupeZ"

[Run]
; Option to launch after install
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent runascurrentuser

[Registry]
; ── App Paths — lets Windows find dupez.exe by name ──
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{#MyAppExeName}"; \
    ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{#MyAppExeName}"; \
    ValueType: string; ValueName: "Path"; ValueData: "{app}"; Flags: uninsdeletekey

; ── DupeZ own registry keys ──
Root: HKLM; Subkey: "SOFTWARE\{#MyAppPublisher}\{#MyAppName}"; \
    ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\{#MyAppPublisher}\{#MyAppName}"; \
    ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekey

; ── Uninstall metadata — enriches the "Installed Apps" entry ──
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

[Code]
// Strip Zone.Identifier (MOTW) from all files after extraction.
procedure RemoveMOTW(const Dir: String);
var
  FindRec: TFindRec;
  FilePath: String;
begin
  if FindFirst(Dir + '\*', FindRec) then begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then begin
          FilePath := Dir + '\' + FindRec.Name;
          if FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
            RemoveMOTW(FilePath)
          else
            DeleteFile(FilePath + ':Zone.Identifier');
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

// Post-install hook: strip MOTW from everything we just wrote to {app}.
// Runs after all files are copied but before the "Finished" page.
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RemoveMOTW(ExpandConstant('{app}'));
end;
