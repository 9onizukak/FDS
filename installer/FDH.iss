#define AppName "FDH"
#ifndef AppVersion
  #error AppVersion must be supplied by build-windows.ps1
#endif

[Setup]
AppId={{B48D3A5C-7C10-42CE-9639-7F05A446B392}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=FDH
DefaultDirName={localappdata}\Programs\FDH
DefaultGroupName=FDH
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=FDH-Setup-{#AppVersion}
SetupIconFile=..\unz\assets\moph-logo.ico
UninstallDisplayIcon={app}\FDH.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\FDH\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\release\README-TH.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\FDH"; Filename: "{app}\FDH.exe"; WorkingDir: "{app}"
Name: "{group}\FDH - Instructions"; Filename: "{app}\README-TH.txt"
Name: "{autodesktop}\FDH"; Filename: "{app}\FDH.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\FDH.exe"; Description: "Launch FDH"; Flags: nowait postinstall skipifsilent
