; Inno Setup Script for AI Karaoke Studio
; Generates AIKaraokeStudio-Setup.exe

#define MyAppName "AI Karaoke Studio"
#define MyAppVersion "0.5.1"
#define MyAppPublisher "Serufim"
#define MyAppURL "https://github.com/Serufim/karaoke_machine"
#define MyAppExeName "AIKaraokeStudio.exe"
#define SourceDist "..\..\dist\AIKaraokeStudio"

[Setup]
AppId={{D377B809-543B-4261-B9D8-6F3926B98C22}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\README.md
PrivilegesRequired=lowest
OutputDir=..\..\dist\installer
OutputBaseFilename=AIKaraokeStudio-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up app cache if requested or temporary files
Type: filesandordirs; Name: "{localappdata}\AIKaraokeStudio\cache\temp"
