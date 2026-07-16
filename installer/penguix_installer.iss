; ============================================================
;  Penguix - Inno Setup installer script
;  Build a proper Windows installer (Setup.exe) around the
;  PyInstaller output  dist\Penguix.exe
;
;  HOW TO BUILD:
;    1. Build the app first:  build_exe.bat   (creates dist\Penguix.exe)
;    2. Install Inno Setup (free): https://jrsoftware.org/isdl.php
;    3. Either double-click this .iss and press F9 (Compile),
;       or run  installer\build_installer.bat
;    Output -> installer\output\Penguix-Setup-0.1.0.exe
; ============================================================

#define AppName       "Penguix"
#define AppVersion    "0.5.9"
#define AppPublisher  "Penguin Inc"
#define AppExeName    "Penguix.exe"

[Setup]
; A fixed AppId ties upgrades and uninstall together. Do NOT change it
; between versions, or Windows will treat new builds as separate apps.
AppId={{8F3A2B10-1C4D-4E6F-9A2B-7C5D9E0F1A23}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
; Per-user install so NO administrator rights are required.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=output
OutputBaseFilename=Penguix-Setup-{#AppVersion}
SetupIconFile=..\assets\penguix.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; The whole application is a single file produced by PyInstaller.
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Optional extras shipped alongside (ignored if missing).
Source: "..\docs\Penguix_User_Guide.docx"; DestDir: "{app}\docs"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{cmd}"; Parameters: "/C set ""_PYI_PARENT_PROCESS_LEVEL="" & set ""_PYI_APPLICATION_HOME_DIR="" & set ""_PYI_ARCHIVE_FILE="" & set ""_MEIPASS2="" & set ""_MEIPASS="" & start """" ""{app}\{#AppExeName}"""; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runhidden

; NOTE: Shop data lives in %APPDATA%\Penguix and is intentionally NOT removed
; on uninstall, so reinstalling keeps all products, sales and backups.
