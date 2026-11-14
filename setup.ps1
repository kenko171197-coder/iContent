# Cài đặt Studio566 trên Windows. Khách chỉ cần bấm đúp file "Cai dat Studio566.cmd".
# Dùng tay: powershell -ExecutionPolicy Bypass -File setup.ps1 [-NoShortcut] [-NoLaunch] [-StatusFile <file>]
# -StatusFile: bộ cài .exe chạy ẩn script này và đọc file trạng thái để hiện thanh tiến trình (dòng 1: số bước | DONE | FAIL,
# dòng 2: tên bước hoặc câu lỗi, dòng 3: đang làm gì). Toàn bộ chữ in ra được ghi vào setup-log.txt cạnh script.
param([switch]$NoShortcut, [switch]$NoLaunch, [string]$StatusFile = "")
$ErrorActionPreference = "Stop"
function Write-Status([string]$a, [string]$b = "", [string]$c = "") {
    if (-not $StatusFile) { return }
    try {
        $tmp = "$StatusFile.tmp"
        [IO.File]::WriteAllText($tmp, "$a`r`n$b`r`n$c`r`n", (New-Object Text.UTF8Encoding $true))
        Move-Item -LiteralPath $tmp -Destination $StatusFile -Force
    } catch {}
}
$script:CurStep = "1"; $script:CurText = ""
if ($StatusFile) { try { Start-Transcript -LiteralPath (Join-Path $PSScriptRoot "setup-log.txt") -Force | Out-Null } catch {} }
# lỗi nào cũng chỉ in đúng câu tiếng Việt cho người dùng, không kèm số dòng, đoạn mã của PowerShell
trap {
    Write-Host ""
    Write-Host "LỖI: $($_.Exception.Message)" -ForegroundColor Red
    Write-Status "FAIL" "$($_.Exception.Message)"
    if ($StatusFile) { try { Stop-Transcript | Out-Null } catch {} }
    exit 1
}
Set-Location -LiteralPath $PSScriptRoot
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$env:PYTHONIOENCODING = "utf-8"      # đường dẫn có dấu in ra ống dẫn sẽ làm Python báo lỗi nếu còn dùng bảng mã cũ của Windows
$env:PYTHONUTF8 = "1"

function Step($n, $text) {
    Write-Host ""; Write-Host "[$n/5] $text" -ForegroundColor Yellow
    $script:CurStep = "$n"; $script:CurText = $text
    Write-Status "$n" $text ""
}

# Lệnh ngoài ghi cảnh báo ra stderr là chuyện thường. Với Stop, PowerShell 5.1 coi đó là lỗi và dừng cả script,
# nên chỉ xét mã thoát của chính lệnh đó. Out-Host: để log hiện ra màn hình; nếu không, log thành giá trị trả về của hàm,
# trộn với mã thoát, và phép so sánh phía sau luôn tưởng là lỗi.
function Invoke-Native($exe, [string[]]$arguments) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $exe @arguments 2>&1 | ForEach-Object {
            $line = "$_"
            if ($StatusFile -and $line -match '^\s*(Collecting|Downloading|Installing|Building|Successfully)') {
                Write-Status $script:CurStep $script:CurText ($line.Trim() -replace '\s+', ' ').Substring(0, [Math]::Min(110, ($line.Trim() -replace '\s+', ' ').Length))
            }
            $line
        } | Out-Host
        return $LASTEXITCODE
    } finally { $ErrorActionPreference = $old }
}

function Get-PythonVersion($exe, [string[]]$prefix) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        $v = & $exe @prefix -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0) { return "$v".Trim() }
    } catch {} finally { $ErrorActionPreference = $old }
    return ""
}

# yt-dlp mới cần từ 3.11, thư viện nhận dạng và lồng tiếng chưa có bản dựng sẵn cho phiên bản mới hơn 3.13
$okVersions = @("3.13", "3.12", "3.11")

function Find-Python {
    # bản phát hành kèm sẵn Python (đúng bản đã chạy qua bộ test, thư mục runtime\python): không phụ thuộc Python trên máy,
    # không cần winget, không gặp Python giả của Microsoft Store
    if ($PSScriptRoot) {
        $bundled = Join-Path $PSScriptRoot "runtime\python\python.exe"
        if ((Test-Path -LiteralPath $bundled) -and ($okVersions -contains (Get-PythonVersion $bundled @()))) { return @{ Exe = $bundled; Args = @() } }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in $okVersions) { if ((Get-PythonVersion "py" @("-$v")) -eq $v) { return @{ Exe = "py"; Args = @("-$v") } } }
    }
    $candidates = @()
    if (Get-Command python -ErrorAction SilentlyContinue) { $candidates += "python" }
    $candidates += "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
    foreach ($c in $candidates) {
        if ($c -eq "python" -or (Test-Path -LiteralPath $c)) {
            # trả về mảng một phần tử sẽ bị PowerShell mở thành chuỗi, $python[0] chỉ còn một ký tự: dùng bảng băm
            if ($okVersions -contains (Get-PythonVersion $c @())) { return @{ Exe = $c; Args = @() } }
        }
    }
    return $null
}

# phiên bản Python lúc tạo .venv (ghi trong pyvenv.cfg). Python gốc đổi phiên bản (bản cài mới kèm Python mới hơn) thì .venv chạy
# Python mới với thư viện biên dịch cho bản cũ: phải tạo lại
function Get-VenvVersion {
    $cfg = Join-Path $PSScriptRoot ".venv\pyvenv.cfg"
    if (Test-Path -LiteralPath $cfg) {
        foreach ($ln in Get-Content -LiteralPath $cfg) { if ($ln -match '^\s*version(_info)?\s*=\s*(\d+\.\d+)') { return $Matches[2] } }
    }
    return ""
}

# máy không có winget (Windows 10 chưa cập nhật, máy công ty) hoặc winget lỗi: tải thẳng đúng bản ffmpeg winget cài (Gyan, đặt trên
# GitHub, nhanh hơn trang gyan.dev nhiều) vào tools\ffmpeg, chỗ Studio566 tìm đầu tiên
function Install-FfmpegDirect {
    $ProgressPreference = "SilentlyContinue"      # thanh tiến độ của PowerShell 5.1 làm tải chậm đi hàng chục lần
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/GyanD/codexffmpeg/releases/latest" -UseBasicParsing -Headers @{ "User-Agent" = "Studio566-setup" }
    $asset = @($rel.assets | Where-Object { $_.name -like "*-essentials_build.zip" })[0]
    if (-not $asset) { throw "Không tìm thấy bản ffmpeg để tải." }
    $tools = Join-Path $PSScriptRoot "tools"
    $zip = Join-Path $tools "ffmpeg-tai-ve.zip"
    $tmp = Join-Path $tools "ffmpeg-giai-nen"
    New-Item -ItemType Directory -Force -Path $tools | Out-Null
    Write-Host "Đang tải ffmpeg $($rel.tag_name) ($([math]::Round($asset.size / 1MB)) MB) ..."
    try {
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force }
        Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
        $bin = Get-ChildItem -LiteralPath $tmp -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
        if (-not $bin -or -not (Test-Path -LiteralPath (Join-Path $bin.DirectoryName "ffprobe.exe"))) { throw "File tải về thiếu ffmpeg.exe hoặc ffprobe.exe." }
        $dest = Join-Path $tools "ffmpeg"
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Copy-Item -LiteralPath $bin.FullName, (Join-Path $bin.DirectoryName "ffprobe.exe") -Destination $dest -Force
    } finally {
        Remove-Item -LiteralPath $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Cài đặt Studio566" -ForegroundColor Green
Write-Host "Cần mạng Internet. Lần đầu mất khoảng 5 đến 15 phút, tải khoảng 3 GB."

Step 1 "Kiểm tra máy và Python"
# lỗi hay gặp nhất ở máy người dùng: bấm đúp ngay trong cửa sổ xem file zip (Windows chỉ giải nén tạm vào Temp rồi xóa),
# cài vào Program Files (không ghi được), ổ gần đầy, thư mục OneDrive (đồng bộ vài GB mô hình, video lên mạng)
$here = $PSScriptRoot
if (($env:TEMP -and $here.StartsWith($env:TEMP, [StringComparison]::OrdinalIgnoreCase)) -or $here -match '\\Temp\d*_[^\\]*\.zip') {
    throw "Đang chạy ngay trong file zip. Hãy giải nén ra một thư mục (chuột phải vào file zip, chọn Giải nén tất cả / Extract All), rồi bấm đúp file cài đặt trong thư mục đó."
}
foreach ($pf in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
    if ($pf -and $here.StartsWith($pf, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Thư mục Program Files không cho phần mềm tự ghi file. Hãy chép thư mục Studio566 ra ổ D hoặc thư mục Documents rồi cài lại."
    }
}
if (-not [Environment]::Is64BitOperatingSystem) { throw "Studio566 cần Windows bản 64-bit." }
if ($env:OneDrive -and $here.StartsWith($env:OneDrive, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host "Lưu ý: thư mục này nằm trong OneDrive, mô hình AI và video (vài GB) sẽ bị đồng bộ lên mạng. Nên chuyển Studio566 ra ngoài OneDrive." -ForegroundColor Yellow
}
$freeGB = $null
try { $freeGB = [math]::Round((Get-Item -LiteralPath $here).PSDrive.Free / 1GB, 1) } catch {}
if ($null -ne $freeGB) {
    $drive = (Get-Item -LiteralPath $here).PSDrive.Name
    if ($freeGB -lt 4) { throw "Ổ ${drive}: chỉ còn $freeGB GB trống, Studio566 cần khoảng 8 GB. Hãy dọn bớt, hoặc đặt thư mục Studio566 ở ổ khác rồi cài lại." }
    if ($freeGB -lt 8) { Write-Host "Lưu ý: ổ ${drive}: còn $freeGB GB trống. Cài được, nhưng mỗi video cần thêm vài trăm MB." -ForegroundColor Yellow }
}
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
# môi trường cũ hỏng (Python gốc đã gỡ, tạo dở, chép từ máy khác, sai phiên bản) thì tạo lại, nếu không pip sẽ lỗi mãi
if (Test-Path -LiteralPath $venvPy) {
    $venvVer = Get-PythonVersion $venvPy @()
    $venvOk = ($okVersions -contains $venvVer) -and ((Get-VenvVersion) -in @("", $venvVer))
    if ($venvOk) { $venvOk = (Invoke-Native $venvPy @("-m", "pip", "--version")) -eq 0 }
    if (-not $venvOk) {
        Write-Host "Môi trường Python cũ không dùng được, đang tạo lại ..."
        Remove-Item -LiteralPath (Join-Path $PSScriptRoot ".venv") -Recurse -Force
    }
}
if (-not (Test-Path -LiteralPath $venvPy)) {
    $python = Find-Python
    if (-not $python) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw "Máy chưa có Python 3.11 đến 3.13. Hãy cài Python 3.13 từ python.org rồi cài lại."
        }
        Write-Host "Chưa có Python phù hợp, đang cài Python 3.13 ..."
        [void](Invoke-Native "winget" @("install", "--id", "Python.Python.3.13", "-e", "--silent", "--accept-source-agreements", "--accept-package-agreements"))
        $python = Find-Python
        if (-not $python) { throw "Cài Python chưa xong. Hãy cài Python 3.13 từ python.org rồi cài lại." }
    }
    $venvArgs = @($python.Args) + @("-m", "venv", ".venv")
    if ((Invoke-Native $python.Exe $venvArgs) -ne 0 -or -not (Test-Path -LiteralPath $venvPy)) { throw "Không tạo được môi trường Python trong thư mục này." }
}
Write-Host "Dùng: $(& $venvPy --version)"

Step 2 "Cài thư viện"
[void](Invoke-Native $venvPy @("-m", "pip", "install", "--upgrade", "pip", "--quiet", "--disable-pip-version-check"))
# constraints.txt (có trong bản phát hành): đúng phiên bản thư viện đã chạy qua bộ test. Không cài được (máy dùng Python khác chẳng hạn)
# thì thử lại theo requirements.txt như trước
$pipArgs = @("-m", "pip", "install", "-r", "requirements.txt", "--disable-pip-version-check")
# chạy từ bộ cài .exe: pip in tiến độ tải từng dòng "Progress X of Y", bộ cài đọc để vẽ thanh tiến độ (cửa sổ dòng lệnh thì không cần)
if ($env:ICONTENT_INSTALLER -eq "1") { $pipArgs += @("--progress-bar", "raw") }
$locked = Test-Path -LiteralPath "constraints.txt"
$code = Invoke-Native $venvPy ($pipArgs + $(if ($locked) { @("-c", "constraints.txt") } else { @() }))
if ($code -ne 0 -and $locked) {
    Write-Host "Chưa cài được đúng phiên bản đã thử, thử lại với phiên bản mới nhất ..." -ForegroundColor Yellow
    $code = Invoke-Native $venvPy $pipArgs
}
if ($code -ne 0) {
    throw "Cài thư viện chưa xong, thường do mạng chập chờn. Hãy cài lại, phần đã tải sẽ không phải tải lại."
}

Step 3 "Kiểm tra ffmpeg"
# hỏi chính Studio566: nó biết cả chỗ winget cài vào, nơi PATH chưa cập nhật cho tới khi mở lại cửa sổ
$ffCheck = @("-c", "from icontent.util import find_ffmpeg; find_ffmpeg()")
if ((Invoke-Native $venvPy $ffCheck) -ne 0) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Đang cài ffmpeg ..."
        [void](Invoke-Native "winget" @("install", "--id", "Gyan.FFmpeg", "-e", "--silent", "--accept-source-agreements", "--accept-package-agreements"))
    }
    if ((Invoke-Native $venvPy $ffCheck) -ne 0) {
        try { Install-FfmpegDirect } catch { Write-Host "Tải ffmpeg lỗi: $($_.Exception.Message)" -ForegroundColor Yellow }
    }
    if ((Invoke-Native $venvPy $ffCheck) -ne 0) {
        throw "Cài ffmpeg chưa xong, thường do mạng. Hãy chạy lại, hoặc tải ffmpeg tại ffmpeg.org rồi chép ffmpeg.exe và ffprobe.exe vào thư mục tools\ffmpeg."
    }
}

Step 4 "Chuẩn bị cấu hình"
if (-not (Test-Path -LiteralPath "config.yaml")) { Copy-Item -LiteralPath "config.example.yaml" -Destination "config.yaml" }
[void](Invoke-Native $venvPy @("-m", "icontent", "doctor"))

Step 5 "Tạo biểu tượng"
if ($NoShortcut) {
    Write-Host "Bỏ qua theo yêu cầu."
} elseif ((Invoke-Native $venvPy @("-m", "icontent", "shortcut")) -ne 0) {
    Write-Host "Không tạo được biểu tượng màn hình nền. Vẫn mở được bằng file Studio566.cmd."
}

Write-Host ""
if ($NoShortcut) { Write-Host "Xong. Mở Studio566 bằng file Studio566.cmd trong thư mục này." -ForegroundColor Green }
else { Write-Host "Xong. Từ giờ mở bằng biểu tượng Studio566 trên màn hình nền." -ForegroundColor Green }
Write-Host "Lần mở đầu có hướng dẫn 3 bước: kết nối AI miễn phí, tải trước mô hình nhận giọng và giọng đọc (khoảng 2,6 GB), làm video đầu tiên."
Write-Status "DONE" "Xong"
if ($StatusFile) { try { Stop-Transcript | Out-Null } catch {} }
if (-not $NoLaunch) { Start-Process -FilePath (Join-Path $PSScriptRoot "Studio566.cmd") -WindowStyle Hidden }
