; Bộ cài Windows của Studio566.
; Biên dịch: ISCC /DAppVersion=0.7.0 /DStageDir=<thư mục mã nguồn> /DOutputDir=<thư mục ra> /DOutputBase=Studio566-Setup-0.7.0 Studio566.iss
; GitHub Actions (.github/workflows/build-windows.yml) tự chạy lệnh này trên máy Windows.
; Sau khi chép file, bộ cài chạy ẩn setup.ps1 (tải Python, thư viện, ffmpeg) và hiện tiến trình ngay trong cửa sổ cài đặt.

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
AppVerName=Studio566 {#AppVersion}
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
UninstallDisplayName=Studio566
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "vi"; MessagesFile: "compiler:Default.isl"

[Messages]
SetupAppTitle=Cài đặt
SetupWindowTitle=Cài đặt %1
ButtonBack=< &Quay lại
ButtonNext=&Tiếp >
ButtonInstall=&Cài đặt
ButtonCancel=Hủy
ButtonFinish=&Xong
ButtonBrowse=&Chọn...
WelcomeLabel1=Chào mừng đến với Studio566
WelcomeLabel2=Bộ cài sẽ đặt Studio566 {#AppVersion} lên máy của bạn.%n%nLần đầu cần mạng Internet để tải thêm khoảng 3 GB thư viện, mất 5 đến 15 phút.
WizardSelectDir=Chọn nơi cài
SelectDirDesc=Studio566 sẽ được cài vào đâu?
SelectDirLabel3=Studio566 sẽ được cài vào thư mục dưới đây.
SelectDirBrowseLabel=Bấm Tiếp để tiếp tục. Muốn chọn thư mục khác thì bấm Chọn. Không chọn Program Files hay thư mục OneDrive.
WizardReady=Sẵn sàng cài đặt
ReadyLabel1=Đã sẵn sàng cài Studio566 lên máy của bạn.
ReadyLabel2a=Bấm Cài đặt để bắt đầu.
WizardInstalling=Đang cài đặt
InstallingLabel=Đang chép file của Studio566...
FinishedHeadingLabel=Cài đặt xong
FinishedLabelNoIcons=Studio566 đã sẵn sàng.
FinishedLabel=Studio566 đã sẵn sàng. Mở bằng biểu tượng Studio566 trên màn hình nền.
ClickFinish=Bấm Xong để đóng bộ cài.
ExitSetupTitle=Thoát cài đặt
ExitSetupMessage=Chưa cài xong. Thoát bây giờ thì lần sau phải chạy lại bộ cài.%n%nVẫn thoát?
StatusClosingApplications=Đang đóng Studio566 đang mở...

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Excludes: ".git\*,.github\*,installer\*,dist\*,tests\*,*.pyc,__pycache__\*,setup-status.txt,setup-log.txt"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Studio566"; Filename: "{app}\Studio566.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\icontent\web\static\icon.ico"
Name: "{group}\Cai dat lai Studio566"; Filename: "{app}\Cai dat Studio566.cmd"; WorkingDir: "{app}"
Name: "{group}\Go cai dat Studio566"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\Studio566.cmd"; WorkingDir: "{app}"; Description: "Mở Studio566"; Flags: postinstall shellexec nowait skipifsilent; Check: SetupSucceeded

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\icontent\__pycache__"
Type: files; Name: "{app}\setup-status.txt"
Type: files; Name: "{app}\setup-log.txt"

[Code]
var
  SetupOk: Boolean;

function SetupSucceeded(): Boolean;
begin
  Result := SetupOk;
end;

function StepName(N: Integer): String;
begin
  case N of
    1: Result := 'Kiểm tra máy và chuẩn bị Python';
    2: Result := 'Tải thư viện AI (phần lâu nhất)';
    3: Result := 'Tải bộ xử lý video (FFmpeg)';
    4: Result := 'Chuẩn bị cấu hình';
    5: Result := 'Tạo biểu tượng trên màn hình nền';
  else
    Result := 'Đang chuẩn bị';
  end;
end;

procedure RunLibrarySetup();
var
  Page: TOutputProgressWizardPage;
  Lines: TArrayOfString;
  StatusFile, Params, Msg, Detail: String;
  ResultCode, N, Tick: Integer;
  Done: Boolean;
begin
  SetupOk := False;
  StatusFile := ExpandConstant('{app}\setup-status.txt');
  DeleteFile(StatusFile);
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\setup.ps1') + '" -NoLaunch -StatusFile "' + StatusFile + '"';
  if not Exec('powershell.exe', Params, ExpandConstant('{app}'), SW_HIDE, ewNoWait, ResultCode) then
  begin
    MsgBox('Không chạy được bước cài thư viện. Hãy mở "Cai dat Studio566.cmd" trong thư mục cài để cài tiếp.', mbError, MB_OK);
    exit;
  end;
  Page := CreateOutputProgressPage('Đang chuẩn bị thư viện', 'Lần đầu cần mạng Internet, khoảng 5 đến 15 phút. Bạn cứ làm việc khác.');
  Page.SetProgress(0, 50);
  Page.Show;
  try
    Done := False;
    Tick := 0;
    N := 1;
    Msg := '';
    while not Done do
    begin
      Sleep(250);
      Tick := Tick + 1;
      if LoadStringsFromFile(StatusFile, Lines) and (GetArrayLength(Lines) >= 1) then
      begin
        if Lines[0] = 'DONE' then
        begin
          Done := True;
          SetupOk := True;
        end
        else if Lines[0] = 'FAIL' then
        begin
          Done := True;
          if GetArrayLength(Lines) >= 2 then Msg := Lines[1];
        end
        else
        begin
          N := StrToIntDef(Lines[0], N);
          Detail := '';
          if GetArrayLength(Lines) >= 3 then Detail := Lines[2];
          Page.SetText('Bước ' + IntToStr(N) + '/5 · ' + StepName(N), Detail);
        end;
      end;
      { thanh tiến trình: mỗi bước một khúc, nhích dần trong bước để thấy máy vẫn đang chạy }
      Page.SetProgress((N - 1) * 10 + (Tick div 8) mod 10, 50);
      if Tick > 4 * 60 * 90 then
      begin
        Done := True;
        Msg := 'Quá 90 phút chưa xong, thường do mạng rất chậm.';
      end;
    end;
  finally
    Page.Hide;
  end;
  if not SetupOk then
    MsgBox('Cài thư viện chưa xong.' + #13#10 + Msg + #13#10#13#10 +
      'Kiểm tra mạng rồi mở "Cai dat Studio566.cmd" trong thư mục cài để cài tiếp, phần đã tải không phải tải lại.' + #13#10 +
      'Nhật ký chi tiết: ' + ExpandConstant('{app}\setup-log.txt'), mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if WizardSilent then
      SetupOk := False
    else
      RunLibrarySetup();
  end;
end;
