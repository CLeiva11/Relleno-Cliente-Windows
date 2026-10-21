[Setup]
AppId={{E91A903A-1ACD-45D4-B1EA-EC4DDC3EAAD2}
AppName=Relleno Cliente
AppVersion=0.3.0
DefaultDirName={localappdata}\Programs\RellenoCliente
DefaultGroupName=Relleno Cliente
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=RellenoCliente-Setup-0.3.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\RellenoCliente.exe
ArchitecturesAllowed=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"

[Files]
Source: "dist\RellenoCliente\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Relleno Cliente"; Filename: "{app}\RellenoCliente.exe"
Name: "{userdesktop}\Relleno Cliente"; Filename: "{app}\RellenoCliente.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\RellenoCliente.exe"; Parameters: "--resume-anpr"; Flags: runhidden waituntilterminated
Filename: "{app}\RellenoCliente.exe"; Description: "Configurar centro y cámaras"; Flags: nowait postinstall skipifsilent
