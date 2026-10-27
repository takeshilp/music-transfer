; One setup.exe from the PyInstaller folder dist\MusicTransfer. Built by build.ps1; saved as UTF-8 with BOM (Cyrillic).
#define AppName "Music Transfer"
#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=<music_transfer.__version__> (build.ps1 does)
#endif
#define AppExe "MusicTransfer.exe"

[Setup]
; AppId must never change: Windows finds the installed copy by it (upgrades, uninstall)
AppId={{68035768-4C0A-4445-A2DD-FCB75FB17763}
AppName={#AppName}
AppVersion={#AppVersion}
; per-user, no admin: {autopf} is %LOCALAPPDATA%\Programs, where the app may write its config.json
PrivilegesRequired=lowest
DefaultDirName={autopf}\Music Transfer
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; follow AppName on upgrades instead of keeping the Start-menu folder of the first install
UsePreviousGroup=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=MusicTransfer-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\MusicTransfer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; the owner's Spotify client ID, so friends only press «Войти»; an upgrade keeps the one already there
Source: "config.json"; DestDir: "{app}"; Flags: onlyifdoesntexist skipifsourcedoesntexist

[InstallDelete]
; shortcuts of versions before 0.2.2, when the app was called «Перенос плейлистов»
Type: files; Name: "{autodesktop}\Перенос плейлистов.lnk"
Type: filesandordirs; Name: "{autoprograms}\Перенос плейлистов"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; the app's own update (update.install): silent, so the line above is skipped; start the new version
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: IsUpdate

[Code]
function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;

[UninstallDelete]
; written by the app itself after a Spotify login; logins in %APPDATA%\music-transfer stay
Type: files; Name: "{app}\config.json"
