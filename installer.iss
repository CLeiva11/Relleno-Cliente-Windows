[Setup]
AppId={{E91A903A-1ACD-45D4-B1EA-EC4DDC3EAAD2}
AppName=Relleno Cliente
AppVersion=0.4.4
DefaultDirName={localappdata}\Programs\RellenoCliente
DefaultGroupName=Relleno Cliente
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=RellenoCliente-Setup-0.4.4
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\RellenoCliente.exe
ArchitecturesAllowed=x64compatible
CloseApplications=force
RestartApplications=no

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
Filename: "{app}\RellenoCliente.exe"; Parameters: "--resume-agent"; Flags: runhidden waituntilterminated
Filename: "{app}\RellenoCliente.exe"; Description: "Configurar centro y cámaras"; Flags: nowait postinstall skipifsilent

[Code]
// El servicio en segundo plano no tiene ventana y bloquea los archivos al
// actualizar: se cierra antes de copiar y [Run] lo vuelve a iniciar.
procedure StopRellenoCliente();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM RellenoCliente.exe', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRellenoCliente();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopRellenoCliente();
  Result := True;
end;
