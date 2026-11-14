"""Mở iContent như một phần mềm riêng: cửa sổ không có thanh địa chỉ và tab, biểu tượng riêng trên thanh tác vụ, đóng cửa
sổ là phần mềm tự tắt (nếu không còn video đang xử lý). Dùng Edge hoặc Chrome có sẵn trên máy ở chế độ ứng dụng, nên không
phải đóng gói thêm cả một trình duyệt.
"""
from __future__ import annotations

import http.client
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import quote

from .util import ROOT, log

# Khi nào tự tắt. Trước đây: 3 phút không có trang hỏi thăm và PowerShell không thấy tiến trình cửa sổ. Khách gặp nhiều lần cảnh
# cửa sổ còn mở mà máy chủ đã tắt ("Không kết nối được iContent"): màn Kích hoạt không được tính là hỏi thăm, trang thu nhỏ bị
# trình duyệt hãm/cho ngủ, và PowerShell trên nhiều máy chậm, bị chặn hoặc bị gỡ. Nay chỉ tắt sớm khi trang báo đã đóng.
IDLE_CLOSED = 20        # giây: trang báo đã đóng (pagehide) và không còn trang nào khác hỏi thăm
IDLE_GRACE = 1800       # giây: không trang nào hỏi thăm (trình duyệt bị tắt ngang, không kịp báo) và không thấy cửa sổ
TITLE_MARKS = ("iContent Studio", "Trình dựng · iContent")      # tiêu đề trang: "<trang> · iContent Studio", cửa sổ trình dựng


def windowless_setup() -> bool:
    """Chạy bằng pythonw: không có cửa sổ dòng lệnh. Ghi nhật ký ra file, và không để ffmpeg nháy cửa sổ đen mỗi lần chạy."""
    if sys.stdout is not None and sys.stderr is not None:
        return False
    d = ROOT / "workspace"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "studio.log"
    if f.exists() and f.stat().st_size > 5_000_000:
        try:
            f.replace(d / "studio.log.old")
        except OSError:      # đang có một iContent khác giữ file: để lần sau xoay vòng, không được làm hỏng việc mở cửa sổ
            pass
    sys.stdout = sys.stderr = open(f, "a", encoding="utf-8", buffering=1)      # noqa: SIM115 — mở suốt đời chương trình
    try:
        import faulthandler
        faulthandler.enable(sys.stderr)      # máy chủ chết vì lỗi tầng C (thiếu RAM, driver card đồ họa): còn dấu vết trong nhật ký
    except (OSError, ValueError, RuntimeError):
        pass
    if os.name == "nt":
        original = subprocess.Popen.__init__

        def init(self, *a, **k):
            k["creationflags"] = k.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
            original(self, *a, **k)

        subprocess.Popen.__init__ = init
    return True


def show_error(msg: str) -> None:
    """Không có dòng lệnh thì lỗi lúc khởi động phải hiện thành hộp thoại, nếu không người dùng chẳng thấy gì."""
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg[:900], "iContent Studio", 0x10)
    elif sys.platform == "darwin":
        safe = msg[:600].replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'display dialog "{safe}" with title "iContent Studio" buttons {{"Đóng"}} default button 1 with icon stop'], check=False)


def start_failed(msg: str) -> None:
    """Lỗi khi mở iContent bằng biểu tượng (pythonw, không có dòng lệnh): ghi lại cho công cụ Sửa lỗi đọc, rồi báo khách.
    Mở qua biểu tượng mới (icontent.start, có ICONTENT_LAUNCHER) thì không hiện hộp thoại: biểu tượng tự mở cửa sổ Sửa lỗi."""
    from .support import START_ERROR
    try:
        START_ERROR.parent.mkdir(parents=True, exist_ok=True)
        START_ERROR.write_text(msg, encoding="utf-8")
    except OSError:
        pass
    if os.environ.get("ICONTENT_LAUNCHER"):
        return
    if os.name == "nt":
        import ctypes
        ask = msg[:800] + "\n\nMở công cụ Sửa lỗi iContent để xem vì sao và sửa?"
        if ctypes.windll.user32.MessageBoxW(0, ask, "iContent Studio", 0x10 | 0x4) == 6:      # MB_YESNO, bấm Có
            from .support import runtime_python
            subprocess.Popen([str(runtime_python()), "-m", "icontent.support", "--reason", "loi"], cwd=str(ROOT))
    elif sys.platform == "darwin":
        show_error(msg)


def clear_start_error() -> None:
    from .support import START_ERROR
    START_ERROR.unlink(missing_ok=True)


def browser_path() -> str | None:
    if sys.platform == "darwin":
        for p in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ):
            if Path(p).is_file():
                return p
    bases = [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")]
    for rel in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
        for b in bases:
            if b and (Path(b) / rel).exists():
                return str(Path(b) / rel)
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("google-chrome")


def open_window(url: str, maximized: bool = False) -> bool:
    """Mở cửa sổ ứng dụng. Hồ sơ trình duyệt riêng để nhớ cỡ cửa sổ và quyền micro. Tắt tiện ích: đã gặp thật trường hợp tiện
    ích cài sẵn trên máy (VPN) tự mở thêm cửa sổ chào mừng khi gặp hồ sơ mới."""
    exe = browser_path()
    if not exe:
        webbrowser.open(url)
        return False
    data = Path(os.environ.get("LOCALAPPDATA") or ROOT) / "iContent" / "window"
    subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={data}", "--start-maximized" if maximized else "--window-size=1440,900",
                      "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--force-dark-mode"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def splash_url(url: str) -> str:
    """Màn hình chờ là file tĩnh, mở được ngay trong lúc máy chủ còn đang nạp thư viện (mất vài giây), rồi tự chuyển vào."""
    page = Path(__file__).parent / "web" / "static" / "splash.html"
    return f"{page.as_uri()}?to={quote(url, safe='')}"


def already_running(host: str, port: int) -> bool:
    """Đã có iContent chạy ở cổng này chưa. Bấm mở lần hai thì chỉ mở thêm cửa sổ, không chạy thêm máy chủ."""
    # không đi qua proxy hệ thống (hay gặp khi bật VPN): đó là máy này, đi qua proxy sẽ tưởng là không có ai
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://{_url_host(host)}:{port}/api/about", timeout=2) as r:
            return r.status == 200
    except (OSError, http.client.HTTPException):      # chương trình khác giữ cổng, trả lời không phải HTTP
        return False


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def port_taken(host: str, port: int) -> bool:
    """Cổng đang bị chương trình khác giữ. Phải kiểm tra trước, vì uvicorn gặp lỗi này thì thoát ngang, không qua except."""
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


WINDOW_MARK = "iContent\\window"


def titled_windows(marks: tuple[str, ...] = TITLE_MARKS) -> list[str]:
    """Tiêu đề các cửa sổ đang hiện (kể cả thu nhỏ) có một trong các chữ marks. Cửa sổ ứng dụng của Edge/Chrome lấy tiêu đề trang làm tiêu đề
    cửa sổ, trang ngủ thì tiêu đề vẫn còn. Gọi thẳng Windows qua ctypes: vài mili giây, không cần PowerShell."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if any(m in buf.value for m in marks):
                    found.append(buf.value)
        return True

    user32.EnumWindows(visit, 0)
    return found


def window_process_open() -> bool:
    """Còn tiến trình trình duyệt dùng hồ sơ cửa sổ iContent không (cách cũ, qua PowerShell: chậm, có máy bị chặn)."""
    if os.name != "nt":
        try:
            r = subprocess.run(["pgrep", "-f", "iContent/window"], capture_output=True, text=True, timeout=10)
            return r.returncode == 0 and bool(r.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            return False
    script = ("$n=@(Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' OR Name='chrome.exe'\" | "
              f"Where-Object {{ $_.CommandLine -like '*{WINDOW_MARK}*' }}).Count;$n")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=60)
        return int(r.stdout.strip() or 0) > 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def window_open() -> bool:
    """Cửa sổ iContent còn mở không. Trình duyệt có thể cho trang ngủ khi cửa sổ thu nhỏ lâu: khi đó trang không hỏi thăm nữa
    nhưng cửa sổ vẫn còn và có thể còn câu chưa lưu, không được tắt phần mềm. Nghi ngờ thì coi như còn mở: để máy chủ chạy
    thêm chẳng hại gì, tắt nhầm thì khách mất việc đang làm."""
    try:
        if titled_windows():
            return True
    except Exception as e:      # noqa: BLE001
        log("ui", f"Không đọc được danh sách cửa sổ: {e}")
    return window_process_open()


def stop_when_idle(app, server, grace: float = IDLE_GRACE, tick: float = 10.0, has_window=window_open,
                   closed_grace: float = IDLE_CLOSED) -> None:
    """Đóng cửa sổ thì tự tắt. Còn video đang xử lý thì làm xong rồi mới tắt.
    Tắt sớm (closed_grace) chỉ khi trang báo đã đóng (POST /api/ui/bye lúc pagehide) và sau đó không còn trang nào hỏi thăm.
    Không có lời báo (trình duyệt bị tắt ngang, trang ngủ) thì đợi grace giây. Cả hai trường hợp đều hỏi lại has_window()."""

    def run() -> None:
        last_tick = time.time()
        app.state.last_seen = last_tick
        while not server.should_exit:
            time.sleep(tick)
            now = time.time()
            if now - last_tick > max(60.0, tick * 6):      # máy vừa ngủ dậy: chưa kịp hỏi thăm, không phải đã đóng cửa sổ
                app.state.last_seen = now
            last_tick = now
            if busy(app):
                app.state.last_seen = now
                continue
            idle = now - app.state.last_seen
            closed = getattr(app.state, "bye", 0.0) >= app.state.last_seen
            if idle > grace or (closed and idle > closed_grace):
                if has_window():
                    app.state.last_seen = now      # còn cửa sổ: lời báo đóng (nếu có) là của trang khác, đợi lại từ đầu
                    continue
                why = "trang báo đã đóng" if closed else f"{idle / 60:.0f} phút không có trang nào hỏi thăm"
                log("ui", f"Cửa sổ đã đóng ({why}), tắt iContent Studio")
                server.should_exit = True

    threading.Thread(target=run, daemon=True, name="ui-idle-stop").start()


def supervise(cmd: list[str], min_up: float = 60.0, max_restarts: int = 3, window: float = 900.0, pause: float = 4.0) -> int:
    """Chạy máy chủ ở tiến trình con, chết bất thường (lỗi tầng C, thiếu RAM, bị phần mềm khác tắt ngang) thì chạy lại: cửa sổ
    đang mở tự kết nối lại (js/main.js) thay vì kẹt ở "Không kết nối được iContent".
    Không chạy lại khi: con tự tắt êm (mã 0: đã đóng cửa sổ), con chết ngay lúc khởi động (lỗi cấu hình: chạy lại cũng vậy, con
    đã tự hiện hộp thoại báo lỗi), hoặc đã chạy lại max_restarts lần trong window giây."""
    restarts: list[float] = []
    while True:
        t0 = time.time()
        try:
            code = subprocess.call(cmd)
        except KeyboardInterrupt:
            return 130
        up = time.time() - t0
        if code == 0:
            return 0
        restarts = [t for t in restarts if t0 - t < window]
        if up < min_up or len(restarts) >= max_restarts:
            log("ui", f"Máy chủ iContent dừng (mã {code}) sau {up:.0f} giây, không tự chạy lại")
            return code or 1
        restarts.append(t0)
        log("ui", f"Máy chủ iContent dừng bất thường (mã {code}) sau {up:.0f} giây, chạy lại sau {pause:.0f} giây "
                  f"(lần {len(restarts)}/{max_restarts})")
        time.sleep(pause)


def busy(app) -> bool:
    st = app.state.studio
    with st.lock:
        if any(i["state"] in ("queued", "running") for i in st.items):
            return True
    from . import localai
    return any(t.running for t in list(localai.TASKS.values()))      # đang tải mô-đun AI (vài GB) thì không tự tắt


def _write_lnk(path: Path, target: Path, args: str, workdir: Path, icon: Path, desc: str) -> None:
    """Ghi file .lnk bằng IShellLinkW. Không dùng WScript.Shell: nó chỉ hiểu bảng mã ANSI nên chữ tiếng Việt thành dấu ? và
    hỏng ngay (đo được thật với D:\\Công cụ\\). Gọi thẳng bằng ctypes nên cũng không có chuyện thoát dấu nháy trong tên thư mục."""
    import ctypes
    import uuid

    def guid(s: str):
        return ctypes.create_string_buffer(uuid.UUID(s).bytes_le, 16)

    def method(obj, index: int, *types):
        table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *types)(table[index])

    ole32 = ctypes.OleDLL("ole32")
    try:
        ole32.CoInitialize(None)
    except OSError:      # luồng đã khởi tạo COM kiểu khác: vẫn dùng được
        pass
    link, store = ctypes.c_void_p(), ctypes.c_void_p()
    ole32.CoCreateInstance(guid("00021401-0000-0000-C000-000000000046"), None, 1, guid("000214F9-0000-0000-C000-000000000046"), ctypes.byref(link))
    text = ctypes.c_wchar_p
    method(link, 20, text)(link, str(target))              # SetPath
    method(link, 11, text)(link, args)                     # SetArguments
    method(link, 9, text)(link, str(workdir))              # SetWorkingDirectory
    method(link, 17, text, ctypes.c_int)(link, str(icon), 0)      # SetIconLocation
    method(link, 7, text)(link, desc)                      # SetDescription
    method(link, 0, ctypes.c_void_p, ctypes.c_void_p)(link, guid("0000010B-0000-0000-C000-000000000046"), ctypes.byref(store))      # QueryInterface IPersistFile
    method(store, 6, text, ctypes.c_int)(store, str(path), 1)     # Save
    for obj in (store, link):
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents[2])(obj)
    if not path.exists():
        raise RuntimeError(f"Không ghi được biểu tượng tại {path}")


def desktop_dir() -> Path:
    if os.name != "nt":
        return Path.home() / "Desktop"
    import ctypes

    buf = ctypes.create_unicode_buffer(1024)
    ctypes.OleDLL("shell32").SHGetFolderPathW(None, 0x10, None, 0, buf)      # CSIDL_DESKTOPDIRECTORY, tự theo OneDrive nếu có
    return Path(buf.value)


def _write_mac_app(app_dir: Path, workdir: Path) -> Path:
    """Tạo gói ứng dụng chuẩn macOS (iContent Studio.app) mở thẳng phòng thu không hiện cửa sổ Terminal."""
    contents = app_dir / "Contents"
    macos = contents / "MacOS"
    res = contents / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        '  <key>CFBundleExecutable</key><string>iContent Studio</string>\n'
        '  <key>CFBundleIdentifier</key><string>vn.icontent.studio</string>\n'
        '  <key>CFBundleName</key><string>iContent Studio</string>\n'
        '  <key>CFBundleDisplayName</key><string>iContent Studio</string>\n'
        '  <key>CFBundlePackageType</key><string>APPL</string>\n'
        '  <key>CFBundleShortVersionString</key><string>1.0</string>\n'
        '  <key>LSMinimumSystemVersion</key><string>12.0</string>\n'
        '  <key>NSHighResolutionCapable</key><true/>\n'
        '</dict>\n</plist>\n'
    )
    (contents / "Info.plist").write_text(plist, encoding="utf-8")
    launcher = macos / "iContent Studio"
    script = (
        "#!/bin/bash\n"
        'export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"\n'
        "export PYTHONIOENCODING=utf-8\n"
        "export PYTHONUTF8=1\n"
        f'cd "{workdir}" || exit 1\n'
        'if [ -x "runtime/python/bin/python3" ]; then\n'
        '  exec "runtime/python/bin/python3" -m icontent.start "$@"\n'
        'elif [ -x ".venv/bin/python3" ]; then\n'
        '  exec ".venv/bin/python3" -m icontent ui --app "$@"\n'
        'else\n'
        '  exec python3 -m icontent ui --app "$@"\n'
        'fi\n'
    )
    launcher.write_text(script, encoding="utf-8", newline="\n")
    try:
        launcher.chmod(0o755)
    except OSError:
        pass
    icon_png = workdir / "icontent" / "web" / "static" / "icon.png"
    if icon_png.is_file():
        shutil.copyfile(icon_png, res / "icon.png")
    return app_dir


def create_shortcut(folder: Path | None = None) -> Path:
    """Tạo biểu tượng iContent Studio, mặc định trên màn hình nền."""
    if sys.platform == "darwin" and os.name != "nt":
        target_dir = Path(folder or desktop_dir())
        return _write_mac_app(target_dir / "iContent Studio.app", ROOT)
    # qua icontent.start (Python kèm trong gói): iContent không lên được thì tự mở cửa sổ Sửa lỗi thay vì im lặng
    rt = ROOT / "runtime" / "python" / "pythonw.exe"
    py, args = (rt, "-m icontent.start") if rt.exists() else (ROOT / ".venv" / "Scripts" / "pythonw.exe", "-m icontent ui --app")
    if not py.exists():
        py = Path(sys.executable)
    out = Path(folder or desktop_dir()) / "iContent Studio.lnk"
    _write_lnk(out, py, args, ROOT, ROOT / "icontent" / "web" / "static" / "icon.ico", "iContent Studio")
    return out


def create_support_shortcut(folder: Path) -> Path:
    """Biểu tượng Sửa lỗi iContent (menu Start): chạy bằng Python kèm trong gói nên mở được cả khi thư viện của iContent hỏng."""
    from .support import runtime_python
    out = Path(folder) / "Sửa lỗi iContent.lnk"
    _write_lnk(out, runtime_python(), "-m icontent.support", ROOT, ROOT / "icontent" / "web" / "static" / "icon.ico", "Sửa lỗi iContent")
    return out
