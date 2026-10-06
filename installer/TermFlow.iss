#define AppName "TermFlow"
#ifndef AppVersion
  #define AppVersion "1.1.7"
#endif
#define AppPublisher "nastasiamql-arch"
#define AppExe "TermFlow.exe"

[Setup]
AppId={{035EB9A1-D69B-47B7-8A93-0199DF2536A2}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\TermFlow
DefaultGroupName=TermFlow
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=output
OutputBaseFilename=TermFlow-Setup-x64
UninstallDisplayName=TermFlow
UninstallDisplayIcon={app}\{#AppExe}
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
WizardStyle=modern

[Files]
Source: "..\dist\TermFlow.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\TermFlow"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\TermFlow"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch TermFlow"; Flags: postinstall nowait skipifsilent

[Code]
var RemoveUserData: Boolean;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  RemoveUserData := False;
  if not UninstallSilent then
    RemoveUserData := (MsgBox('Remove TermFlow settings, custom prompts, and history too?', mbConfirmation, MB_YESNO) = IDYES);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if (CurUninstallStep = usUninstall) and RemoveUserData then begin
    Exec(ExpandConstant('{app}\TermFlow.exe'), '--remove-user-data', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    DelTree(ExpandConstant('{userappdata}\TermFlow'), True, True, True);
  end;
end;

