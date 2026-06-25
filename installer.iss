; Garmin Sleep Reporter — Inno Setup スクリプト
; 配布1ファイル(Setup.exe)を作る。PyInstaller(garminsleep.spec)で dist/GarminSleepReporter/
; を生成してから、Inno Setup Compiler でこのスクリプトをコンパイルする。
;
; ビルド手順:
;   1) pip install pyinstaller
;   2) pyinstaller garminsleep.spec --noconfirm
;   3) Inno Setup (https://jrsoftware.org/isdl.php) をインストール
;   4) この installer.iss を Inno Setup Compiler で開いて Build（または iscc installer.iss）
;   → Output\GarminSleepReporter-Setup.exe が生成される
;
; 方針: 管理者権限を要求しない(PrivilegesRequired=lowest)。インストール先は
; %LocalAppData%\Programs\GarminSleepReporter（ユーザー領域＝書込可能）。
; これにより settings.json / sleep.db / output / logs / .garminconnect を
; exe フォルダにそのまま書ける（config.base_dir() が exe フォルダを指す）。

#define AppName "Garmin Sleep Reporter"
#define AppVersion "1.0.0"
#define AppExeName "GarminSleepReporter.exe"
#define AppPublisher "Garmin Sleep Reporter"

[Setup]
AppId={{DE605CC6-C818-4F3B-BA5A-9CFFC9796823}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\GarminSleepReporter
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=GarminSleepReporter-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; PyInstaller one-dir 出力（フォルダごと）を取り込む。
Source: "dist\GarminSleepReporter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; インストール完了後に設定GUIを起動（任意）。
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; アンインストール時にアプリが作った生成物も消す（ユーザー判断で残したい場合はこの行を外す）。
Type: filesandordirs; Name: "{app}\output"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\rawdata"
Type: filesandordirs; Name: "{app}\.garminconnect"
Type: files; Name: "{app}\sleep.db"
Type: files; Name: "{app}\settings.json"
