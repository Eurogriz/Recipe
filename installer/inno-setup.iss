; Inno Setup script for Formulation Workbench
; Build with: ISCC.exe installer/inno-setup.iss
; Result: dist/FormulationWorkbench-1.0.0-setup.exe

[Setup]
AppName=Formulation Workbench
AppVersion=1.0.0
AppPublisher=Formulation Workbench Team
AppPublisherURL=https://example.com
DefaultDirName={autopf}\FormulationWorkbench
DefaultGroupName=Formulation Workbench
DisableProgramGroupPage=yes
LicenseFile=LICENSE.txt
InfoBeforeFile=docs/00-discovery/disclaimer.txt
OutputDir=dist
OutputBaseFilename=FormulationWorkbench-1.0.0-setup
Compression=lzma2/ultra64
SolidCompression=yes
; PrivilegesRequired=lowest ; No admin required (internal distribution)
UninstallDisplayIcon={app}\FormulationWorkbench.exe
SetupIconFile=resources\icon.ico

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Additional icons"
Name: "quicklaunchicon"; Description: "Create Quick Launch icon"; GroupDescription: "Additional icons"

[Files]
; Main application
Source: "dist\FormulationWorkbench\FormulationWorkbench.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\FormulationWorkbench\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Documentation
Source: "docs\user-manual.pdf"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Formulation Workbench"; Filename: "{app}\FormulationWorkbench.exe"
Name: "{group}\{cm:UninstallProgram,Formulation Workbench}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Formulation Workbench"; Filename: "{app}\FormulationWorkbench.exe"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\Formulation Workbench"; Filename: "{app}\FormulationWorkbench.exe"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\FormulationWorkbench.exe"; Description: "{cm:LaunchProgram,Formulation Workbench}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
Type: filesandordirs; Name: "{userappdata}\FormulationWorkbench"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  // Phase 5: Add pre-install checks (Windows version, .NET, etc.)
end;
