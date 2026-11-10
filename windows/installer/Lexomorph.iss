; Inno Setup script for Lexomorph (Windows; formerly SuperDictate Next).
;
; Builds a per-user installer: the app writes only to %LOCALAPPDATA% and
; needs no driver or service, so requiring an admin prompt would buy
; nothing and would break installing on a locked-down work machine.
;
; Compile after `build.ps1` has produced dist\Lexomorph\:
;   & "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\Lexomorph.iss
;
; Lexomorph is a NEW application as far as Windows is concerned (new AppId,
; new install directory, new data directory, new autostart value). The old
; SuperDictate installation is removed by this installer; its data is not:
; Lexomorph copies %LOCALAPPDATA%\SuperDictate on its first launch
; (superdictate/paths.py, migrate_legacy_directory) and the original stays
; where it is, as the way back.

#define AppName        "Lexomorph"
#define AppVersion     "1.0.1"
#define AppPublisher   "Lexomorph (formerly SuperDictate Next)"
#define AppURL         "https://github.com/shohart/SuperDictate-Next"
#define AppExeName     "Lexomorph.exe"
; Must match superdictate.system.APP_USER_MODEL_ID, or the taskbar treats a
; pinned shortcut and the running window as two different applications.
#define AppUserModelID "local.Lexomorph"
; Must match superdictate.paths.APP_NAME and system._RUN_VALUE.
#define DataDirName    "Lexomorph"
#define RunValueName   "Lexomorph"

; The previous product. Its AppId is what its uninstall entry is keyed by:
; HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\<AppId>_is1.
#define OldAppId       "{2271EBB1-D4F4-4FCA-949C-F03C760A700A}"
#define OldName        "SuperDictate"
#define OldExeName     "SuperDictate.exe"

[Setup]
; A NEW AppId, deliberately (the old one is #OldAppId): Windows must see two
; products, so this installer never "upgrades" the old files in place.
AppId={{3E10F31A-EE8D-4609-9EC8-3197BA47854B}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
UninstallDisplayName={#AppName}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription={#AppName} setup
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=Lexomorph-Setup-{#AppVersion}
SetupIconFile=..\assets\Lexomorph.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Per-user: nothing here touches HKLM, Program Files or a service.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The speech model is ~640 MB and is downloaded on first run, so the
; installer itself stays small.
MinVersion=10.0.17763

[Languages]
; English is the base (and the fallback when the Windows display language
; has no translation); Russian is picked for a Russian system.
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "{cm:AutoStartDescription}"; \
    GroupDescription: "{cm:AutoStartGroup}"

[CustomMessages]
english.AutoStartGroup=Startup:
english.AutoStartDescription=Start Lexomorph when I sign in to Windows
english.LaunchApp=Launch Lexomorph
english.MigrationTitle=Lexomorph (formerly SuperDictate Next)
english.MigrationSubtitle=Moving from SuperDictate
english.MigrationIntro=SuperDictate Next is now called Lexomorph. Lexomorph is installed as a new application, with its own program folder, start-up entry and data folder.
english.MigrationData=Your settings, history, vocabulary, sync sign-in and downloaded speech models are copied to the new Lexomorph folder the first time Lexomorph starts. The original SuperDictate data folder is left untouched, so you can go back to it at any time.
english.MigrationRemoveOld=The installed copy of SuperDictate was found. Setup will close it and remove it (its program files, shortcuts and start-up entry) before installing Lexomorph. Your data is not deleted.
english.UninstallDataQuestion=Delete the Lexomorph settings, history and downloaded speech models (about 640 MB)?%n%n%1
english.UninstallOldDataQuestion=An older SuperDictate data folder was found. It is the backup that Lexomorph copied from. Delete it too?%n%n%1
russian.AutoStartGroup=Автозапуск:
russian.AutoStartDescription=Запускать Lexomorph при входе в Windows
russian.LaunchApp=Запустить Lexomorph
russian.MigrationTitle=Lexomorph (ранее SuperDictate Next)
russian.MigrationSubtitle=Переход с SuperDictate
russian.MigrationIntro=SuperDictate Next теперь называется Lexomorph. Lexomorph устанавливается как новое приложение: со своей папкой, записью автозапуска и каталогом данных.
russian.MigrationData=Настройки, история, словарь, вход в синхронизацию и скачанные модели распознавания будут скопированы в новый каталог Lexomorph при первом запуске. Исходный каталог данных SuperDictate остаётся нетронутым, к нему можно вернуться в любой момент.
russian.MigrationRemoveOld=Найдена установленная копия SuperDictate. Перед установкой Lexomorph программа установки закроет и удалит её (файлы, ярлыки и запись автозапуска). Ваши данные не удаляются.
russian.UninstallDataQuestion=Удалить настройки, историю и скачанные модели распознавания Lexomorph (около 640 МБ)?%n%n%1
russian.UninstallOldDataQuestion=Найден прежний каталог данных SuperDictate. Это резервная копия, из которой Lexomorph копировал данные. Удалить и его?%n%n%1

[Files]
Source: "..\dist\Lexomorph\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; The shortcuts of the previous product (its own uninstaller removes them
; too; this covers an uninstaller that could not run).
Type: files; Name: "{autodesktop}\{#OldName}.lnk"
Type: files; Name: "{userdesktop}\{#OldName}.lnk"
Type: files; Name: "{autodesktop}\D1CT.lnk"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    AppUserModelID: "{#AppUserModelID}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Registry]
; --minimized so an autostarted copy goes straight to the tray instead of
; throwing its control panel at you every login.
;
; This entry must stay the only one that touches the value "Lexomorph". An
; earlier script created the Run value and then, a few lines down, listed
; "deletevalue" for the very same name: entries are processed in order, so
; the value was removed again right after it was written. The deletions
; below are for the OLD names only.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#RunValueName}"; \
    ValueData: """{app}\{#AppExeName}"" --minimized"; \
    Flags: uninsdeletevalue; Tasks: autostart
; Start-up entries of the previous names (SuperDictate, D1CT). They point
; at executables that are about to be removed and would fail at every login.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: none; ValueName: "{#OldName}"; Flags: deletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: none; ValueName: "D1CT"; Flags: deletevalue

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchApp}"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; The app lives in the tray; a running copy would keep its files locked.
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#AppExeName} /F /T"; \
    Flags: runhidden; RunOnceId: "StopLexomorph"

[Code]
const
  SHCNE_ASSOCCHANGED = $08000000;
  SHCNF_IDLIST       = $0000;
  OldUninstallKey    = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#OldAppId}_is1';

var
  MigrationPage: TOutputMsgWizardPage;
  OldUninstallCommand: String;
  OldDataFolder: String;

procedure SHChangeNotify(EventId: LongInt; Flags: Cardinal;
                         Item1, Item2: LongInt);
  external 'SHChangeNotify@shell32.dll stdcall';

// -- the previous product ---------------------------------------------------

// The command that silently uninstalls SuperDictate, or '' if it is not
// installed. A per-user install lives under HKCU; a machine-wide one under
// HKLM, which only an elevated setup may remove.
function FindOldUninstallCommand(): String;
var
  Command: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, OldUninstallKey, 'UninstallString', Command) then
    Result := Command
  else if IsAdmin and
          RegQueryStringValue(HKLM, OldUninstallKey, 'UninstallString', Command) then
    Result := Command;
end;

procedure KillByImage(const Image: String);
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{cmd}'), '/C taskkill /IM ' + Image + ' /F /T', '',
       SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure StopRunningCopies();
begin
  KillByImage('{#AppExeName}');
  KillByImage('{#OldExeName}');
  KillByImage('SuperDictateOvHost.exe');
  KillByImage('SuperDictateOnnxHost.exe');
  KillByImage('superdictate-llm-host.exe');
  KillByImage('LexomorphOvHost.exe');
  KillByImage('LexomorphOnnxHost.exe');
  KillByImage('lexomorph-llm-host.exe');
end;

// Runs the old uninstaller silently. The old script asked, at the end,
// whether to delete {localappdata}\Dictation (a folder that has nothing to
// do with its own data), and a silent run answers that question "yes". The
// folder is moved aside for the duration so that answer deletes nothing.
// Its real data folder, {localappdata}\SuperDictate, is not touched by it.
procedure RemoveOldInstallation();
var
  Command, Parameters, Hold, Dictation: String;
  ResultCode: Integer;
  Held: Boolean;
begin
  Command := RemoveQuotes(Trim(OldUninstallCommand));
  // The registry value is the quoted path of unins000.exe, possibly followed
  // by switches; the executable is the first quoted part.
  if (Length(OldUninstallCommand) > 0) and (OldUninstallCommand[1] = '"') then
  begin
    Command := Copy(OldUninstallCommand, 2, Length(OldUninstallCommand));
    Command := Copy(Command, 1, Pos('"', Command) - 1);
  end;
  if not FileExists(Command) then
    Exit;

  Dictation := ExpandConstant('{localappdata}\Dictation');
  Hold := Dictation + '.held-by-lexomorph-setup';
  Held := DirExists(Dictation) and not DirExists(Hold) and RenameFile(Dictation, Hold);
  try
    Parameters := '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART';
    Exec(Command, Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  finally
    if Held and DirExists(Hold) and not DirExists(Dictation) then
      RenameFile(Hold, Dictation);
  end;
end;

// Whatever the old uninstaller left behind (it cannot remove a file that
// was open) and the entries it never knew about. Data folders stay.
procedure RemoveOldLeftovers();
var
  Folder: String;
begin
  Folder := ExpandConstant('{userprograms}\{#OldName}');
  if DirExists(Folder) then
    DelTree(Folder, True, True, True);
  Folder := ExpandConstant('{userprograms}\D1CT');
  if DirExists(Folder) then
    DelTree(Folder, True, True, True);
  // The install directory, not the data directory: {autopf}\SuperDictate
  // against {localappdata}\SuperDictate.
  Folder := ExpandConstant('{autopf}\{#OldName}');
  if DirExists(Folder) and FileExists(Folder + '\{#OldExeName}') then
    DelTree(Folder, True, True, True);
  Folder := ExpandConstant('{localappdata}\Programs\D1CT');
  if DirExists(Folder) then
    DelTree(Folder, True, True, True);
end;

// -- wizard -----------------------------------------------------------------

procedure InitializeWizard();
begin
  OldUninstallCommand := FindOldUninstallCommand();
  OldDataFolder := ExpandConstant('{localappdata}\{#OldName}');
  MigrationPage := CreateOutputMsgPage(wpWelcome,
    CustomMessage('MigrationTitle'), CustomMessage('MigrationSubtitle'),
    CustomMessage('MigrationIntro') + #13#10#13#10 + CustomMessage('MigrationData'));
  if OldUninstallCommand <> '' then
    MigrationPage.MsgLabel.Caption := MigrationPage.MsgLabel.Caption + #13#10#13#10 +
      CustomMessage('MigrationRemoveOld');
end;

// Only people who have the previous product (or its data) need the page.
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (MigrationPage <> nil) and (PageID = MigrationPage.ID) then
    Result := (OldUninstallCommand = '') and not DirExists(OldDataFolder);
end;

// A copy running in the tray holds its own files open, so an upgrade
// either fails to replace them or defers the replacement to a reboot.
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningCopies();
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    // Before our files are written, so the two installs never overlap.
    if OldUninstallCommand <> '' then
      RemoveOldInstallation();
    RemoveOldLeftovers();
  end;
  if CurStep = ssPostInstall then
    // Explorer caches the icon it has seen for an executable.
    SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, 0, 0);
end;

// -- uninstall --------------------------------------------------------------

// Settings, history and the 640 MB model cache live outside the install
// directory. Leaving them behind by default means a reinstall does not
// re-download the model; the user is asked, so a real uninstall can be
// complete. A silent uninstall never deletes data (a suppressed question
// would otherwise be answered "yes").
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir, OldDir: String;
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
  begin
    DataDir := ExpandConstant('{localappdata}\{#DataDirName}');
    if DirExists(DataDir) then
      if MsgBox(FmtMessage(CustomMessage('UninstallDataQuestion'), [DataDir]),
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);

    OldDir := ExpandConstant('{localappdata}\{#OldName}');
    if DirExists(OldDir) then
      if MsgBox(FmtMessage(CustomMessage('UninstallOldDataQuestion'), [OldDir]),
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(OldDir, True, True, True);
  end;
end;
