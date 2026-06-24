; Inno Setup script for Formulation Workbench
; Build with:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "C:\Users\eurog\Desktop\Рецепты\installer\inno-setup.iss"

[Setup]
AppName=Formulation Workbench
AppVersion=1.0.0
AppPublisher=Formulation Workbench Team
AppPublisherURL=https://example.com
DefaultDirName={autopf}\FormulationWorkbench
DefaultGroupName=Formulation Workbench
DisableProgramGroupPage=yes

; Файлы относительно папки installer
LicenseFile=LICENSE.txt
InfoBeforeFile=..\docs\00-discovery\disclaimer.txt

; Куда положить готовый setup.exe
OutputDir=..\dist
OutputBaseFilename=FormulationWorkbench-1.0.0-setup

Compression=lzma2/ultra64
SolidCompression=yes

; Если нужен setup-иконка, раскомментируйте после добавления файла
; SetupIconFile=..\resources\icon.ico

UninstallDisplayIcon={app}\FormulationWorkbench.exe

; Если хотите установку без прав администратора, используйте:
; PrivilegesRequired=lowest
; DefaultDirName={localappdata}\Programs\FormulationWorkbench

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Additional icons"
; Quick Launch устарел, но можно оставить при необходимости
Name: "quicklaunchicon"; Description: "Create Quick Launch icon"; GroupDescription: "Additional icons"

[Files]
; Основное приложение
Source: "..\dist\FormulationWorkbench\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Документация и служебные файлы
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

; Пока файла нет — строку оставляем закомментированной
; Source: "..\docs\user-manual.pdf"; DestDir: "{app}\docs"; Flags: ignoreversion

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
end;
