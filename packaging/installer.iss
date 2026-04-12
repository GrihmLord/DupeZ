; ============================================================================
; DupeZ v5.3 — Inno Setup Installer Script
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
; BUILD (run from repo root):
;   1. Build dupez.exe first:   pyinstaller packaging\dupez.spec --noconfirm
;   2. Then compile installer:  iscc packaging\installer.iss
;   Output: dist\DupeZ_v5.4.0_Setup.exe
;
; PATH NOTE:
;   This .iss lives in packaging\, but every Source: path below
;   (dist\dupez.exe, app\firewall\*.dll, etc.) is written relative to
;   the repo root. SourceDir=.. tells Inno Setup to resolve all
;   relative paths from packaging\..  = repo root.
; ============================================================================

#define MyAppName      "DupeZ"
#define MyAppVersion   "5.4.0"
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
; 64-bit install mode — dupez.exe is a 64-bit PyInstaller bundle, so {autopf}
; must resolve to C:\Program Files (not C:\Program Files (x86)) and the
; 64-bit registry hive must be used for uninstall entries. Without these
; directives, Inno Setup defaults to 32-bit mode and installs a 64-bit
; binary into the x86 Program Files path — latent bug in v5.2.0–v5.2.3.
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
DisableProgramGroupPage=yes
; Allow user to upgrade without uninstalling first
UsePreviousAppDir=yes
; Resolve all relative Source: paths from the repo root, even though
; this .iss lives in packaging\. `..` = parent of the .iss file dir.
SourceDir=..
; Output location and naming (relative to SourceDir above)
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
; Main executables (built by build_variants.bat)
; GPU variant is the recommended default — installed as dupez.exe so
; shortcuts, registry entries, and the updater all keep working.
Source: "dist\DupeZ-GPU.exe"; DestDir: "{app}"; DestName: "dupez.exe"; Flags: ignoreversion
; Compat variant ships alongside for users with blocklisted GPUs
Source: "dist\DupeZ-Compat.exe"; DestDir: "{app}"; Flags: ignoreversion

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
; Launch after interactive install (checkbox on Finished page)
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent runascurrentuser
; Launch after silent install (auto-update path) — no checkbox, just run
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifdoesntexist runascurrentuser; Check: WizardSilent

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
// ── Force-kill DupeZ processes before file extraction ──────────────
// PyInstaller one-file exes don't register with the Windows Restart
// Manager, so CloseApplications=yes alone cannot close them. This
// PrepareToInstall hook runs taskkill /F /IM to guarantee the exe is
// unlocked before Inno tries to overwrite it.
//
// PrepareToInstall runs after the user clicks "Install" but before any
// files are touched. Returning '' means "proceed"; returning a string
// would abort with that error message.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Cmd: String;
  ResultCode: Integer;
begin
  Result := '';
  NeedsRestart := False;

  // Kill all dupez.exe instances (GPU, Compat, or legacy single-exe)
  Cmd := ExpandConstant('{sys}\taskkill.exe');
  Exec(Cmd, '/F /IM dupez.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  // ResultCode 128 = "no such process" — that's fine
  Log('PrepareToInstall: taskkill dupez.exe exited with code ' + IntToStr(ResultCode));

  // Also kill the helper process if running
  Exec(Cmd, '/F /IM dupez_helper.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('PrepareToInstall: taskkill dupez_helper.exe exited with code ' + IntToStr(ResultCode));

  // Small delay to let Windows release file handles
  Sleep(500);
end;

// ── Strip Zone.Identifier (MOTW) from all files after extraction ──
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
