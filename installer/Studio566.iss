; Bộ cài Windows của Studio566 (bản fork không khóa bản quyền).
; Biên dịch: ISCC /DAppVersion=0.6.2 /DStageDir=<thư mục mã nguồn> /DOutputDir=<thư mục ra> /DOutputBase=Studio566-Setup-0.6.2 Studio566.iss
; GitHub Actions (.github/workflows/build-windows.yml) tự chạy lệnh này trên máy Windows.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef StageDir
  #define StageDir ".."
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef OutputBase
  #define OutputBase "Studio566-Setup-" + AppVersion
#endif

[Setup]
AppId={{6F3C2B7E-9A41-4C55-8E0B-1C2D3E4F5A60}
AppName=Studio566
AppVersion={#AppVersion}
AppPublisher=Studio566
DefaultDirName={localappdata}\Studio566
DefaultGroupName=Studio566
DisableProgramGroupPage=yes
; cài theo người dùng: setup.ps1 không cho cài vào Program Files
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
SetupIconFile={#StageDir}\icontent\web\static\icon.ico
UninstallDisplayIcon={app}\icontent\web\static\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Excludes: ".git\*,.github\*,installer\*,dist\*,*.pyc,__pycache__\*"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Studio566"; Filename: "{app}\Studio566.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\icontent\web\static\icon.ico"
Name: "{group}\Cai dat lai Studio566"; Filename: "{app}\Cai dat Studio566.cmd"; WorkingDir: "{app}"
Name: "{group}\Go cai dat Studio566"; Filename: "{uninstallexe}"

[Run]
; Bước cài thư viện (cần mạng, lần đầu khoảng 3 GB, 5 đến 15 phút). Cài im lặng (/VERYSILENT) thì bỏ qua.
Filename: "{app}\Cai dat Studio566.cmd"; WorkingDir: "{app}"; Description: "Cai dat thu vien va mo Studio566 (can mang Internet)"; Flags: postinstall shellexec waituntilterminated skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\icontent\__pycache__"
