"""Sửa lỗi Studio566: kiểm tra máy, sửa những lỗi hay gặp sau khi cài, và tạo gói báo lỗi gửi người hỗ trợ.

Chạy được cả khi Studio566 không mở được (thư viện cài dở, ffmpeg thiếu, cổng bị chiếm, phần mềm diệt virus xóa file...), nên
file này CHỈ dùng thư viện chuẩn của Python và được chạy bằng bản Python kèm trong gói (runtime\\python), không cần .venv:

    runtime\\python\\pythonw.exe -m icontent.support        (biểu tượng "Sửa lỗi Studio566" trong menu Start)

Giao diện là một trang web nhỏ (máy chủ http.server của Python ở 127.0.0.1:8766) mở trong cửa sổ Edge/Chrome. Trong Studio566
(Cài đặt → Hỗ trợ) các API /api/support/* gọi lại đúng các hàm ở đây.
"""
from __future__ import annotations

import ctypes
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "web" / "static"
WORK = ROOT / "workspace"
APP_PORT = 8765
PORT = 8766
START_ERROR = WORK / "start-error.txt"      # cli.py ghi lỗi khởi động vào đây (chạy bằng pythonw thì không có dòng lệnh để xem)
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
NEW_CONSOLE = 0x00000010 if os.name == "nt" else 0

# thư viện Studio566 cần để mở được; thiếu cái nào thì phần cài thư viện chưa xong (hoặc bị phần mềm diệt virus xóa)
CORE_MODULES = ["fastapi", "uvicorn", "yaml", "numpy", "yt_dlp", "edge_tts", "faster_whisper", "onnxruntime", "PIL",
                "sherpa_onnx", "rapidocr"]
# trang Studio566 cần tới; trả lời mã gì cũng được (403, 404 vẫn là đi tới nơi), chỉ lỗi mạng mới tính là không vào được
SITES = [
    ("pypi", "Tải thư viện (pypi.org)", "https://pypi.org/simple/pip/", True),
    ("github", "Tải ffmpeg (github.com)", "https://api.github.com/", True),
    ("hf", "Tải mô hình AI (huggingface.co)", "https://huggingface.co/", False),
    ("bilibili", "Bilibili", "https://www.bilibili.com/", False),
    ("douyin", "Douyin", "https://www.douyin.com/", False),
    ("gemini", "Gemini (dịch, viết bằng AI)", "https://generativelanguage.googleapis.com/", False),
    ("edge_tts", "Giọng đọc Microsoft", "https://speech.platform.bing.com/", False),
]


def _run(cmd: list[str], timeout: float = 60, **kw) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          creationflags=NO_WINDOW, env=env, **kw)


def _item(cid: str, title: str, state: str, detail: str = "", fix: dict | None = None, help: str = "") -> dict:
    return {"id": cid, "title": title, "state": state, "detail": detail, "fix": fix, "help": help}


FIX_SETUP = {"id": "setup", "label": "Cài lại thư viện"}
FIX_VCREDIST = {"id": "vcredist", "label": "Cài bộ chạy Microsoft"}
FIX_KILL = {"id": "kill", "label": "Tắt Studio566 bị treo"}


# ============================================================================ các bước kiểm tra

def venv_python(windowless: bool = False) -> Path:
    if os.name != "nt":
        return ROOT / ".venv" / "bin" / "python3"
    return ROOT / ".venv" / "Scripts" / ("pythonw.exe" if windowless else "python.exe")


def runtime_python(windowless: bool = True) -> Path:
    """Python kèm trong gói (bản phát hành); máy lập trình không có thì dùng Python đang chạy file này."""
    if os.name != "nt":
        p_mac = ROOT / "runtime" / "python" / "bin" / "python3"
        return p_mac if p_mac.is_file() else Path(sys.executable)
    p = ROOT / "runtime" / "python" / ("pythonw.exe" if windowless else "python.exe")
    if p.is_file():
        return p
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if windowless and w.is_file() else exe


def check_files() -> dict:
    need = ["icontent/__main__.py", "icontent/web/static/index.html", "icontent/web/server.py", "setup.ps1"]
    miss = [n for n in need if not (ROOT / n).is_file()]
    if miss:
        return _item("files", "File của Studio566", "bad", "Thiếu: " + ", ".join(miss),
                     help="Thường do phần mềm diệt virus xóa nhầm. Mở phần mềm diệt virus, khôi phục file trong mục cách ly "
                          "(Quarantine) và thêm thư mục Studio566 vào danh sách loại trừ, rồi chạy lại file cài Studio566.")
    return _item("files", "File của Studio566", "ok", str(ROOT))


def check_folder() -> dict:
    p = str(ROOT).lower()
    try:
        free = shutil.disk_usage(ROOT).free / 1e9
    except OSError:
        free = -1
    probe = WORK / f".thu-ghi-{os.getpid()}.tmp"
    try:
        WORK.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        writable = True
    except OSError:
        writable = False
    if not writable:
        return _item("folder", "Thư mục cài đặt", "bad", f"Không ghi được file vào {WORK}",
                     help="Windows đang chặn ghi (thường là Bảo vệ khỏi mã độc tống tiền / Controlled folder access, hoặc "
                          "phần mềm diệt virus). Cài Studio566 vào ổ D:\\Studio566, hoặc cho phép Studio566 trong Windows Security.")
    if 0 <= free < 2:
        return _item("folder", "Thư mục cài đặt", "bad", f"Ổ đĩa chỉ còn {free:.1f} GB trống",
                     help="Studio566 cần vài GB để cài thư viện và làm video. Xóa bớt file hoặc dọn Thư viện trong Studio566.")
    if "onedrive" in p:
        return _item("folder", "Thư mục cài đặt", "warn", f"{ROOT} nằm trong OneDrive",
                     help="OneDrive đồng bộ và có khi tạm cất file đi, làm Studio566 lỗi bất chợt. Nên cài lại vào D:\\Studio566.")
    if 0 <= free < 10:
        return _item("folder", "Thư mục cài đặt", "warn", f"Ổ đĩa còn {free:.1f} GB trống, hơi ít để làm video")
    return _item("folder", "Thư mục cài đặt", "ok", f"{ROOT} · còn {free:.0f} GB trống" if free >= 0 else str(ROOT))


def check_windows() -> dict:
    ram = _ram_gb()
    if sys.platform == "darwin":
        ver = platform.mac_ver()[0] or platform.release()
        arch = "Chip Apple" if platform.machine().lower() in ("arm64", "aarch64") else "Chip Intel"
        detail = f"macOS {ver} ({arch})" + (f" · RAM {ram:.0f} GB" if ram else "")
        if 0 < ram < 7.5:
            return _item("windows", "Máy tính", "warn", detail, help="Dưới 8 GB RAM: làm video dài có thể chậm. Đóng bớt chương trình khác khi làm.")
        return _item("windows", "Máy tính", "ok", detail)
    try:
        build = sys.getwindowsversion().build
    except AttributeError:
        build = 0
    name = "Windows 11" if build >= 22000 else f"Windows {platform.release()}"
    detail = f"{name} (bản {build}) · RAM {ram:.0f} GB" if ram else f"{name} (bản {build})"
    if platform.machine().lower() not in ("amd64", "x86_64"):
        return _item("windows", "Máy tính", "bad", detail + f" · {platform.machine()}", help="Studio566 cần Windows 64-bit.")
    if 0 < build < 17763:
        return _item("windows", "Máy tính", "warn", detail, help="Windows quá cũ. Cập nhật Windows 10 bản 1809 trở lên.")
    if 0 < ram < 7.5:
        return _item("windows", "Máy tính", "warn", detail, help="Dưới 8 GB RAM: làm video dài có thể chậm hoặc tự dừng. Đóng bớt chương trình khác khi làm.")
    return _item("windows", "Máy tính", "ok", detail)


def _ram_gb() -> float:
    if sys.platform == "darwin":
        try:
            r = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            return int(r.stdout.strip()) / 1024 ** 3
        except (OSError, ValueError, subprocess.SubprocessError):
            return 0.0
    if os.name != "nt":
        return 0.0

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MS()
    m.dwLength = ctypes.sizeof(MS)
    try:
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    except OSError:
        return 0.0
    return m.ullTotalPhys / 1024 ** 3


def vcredist_ok() -> bool:
    """Bộ chạy Visual C++ của Microsoft (msvcp140.dll...): onnxruntime, ctranslate2, OpenCV cần nó. Python chỉ kèm vcruntime140,
    máy mới cài Windows hay thiếu msvcp140 và lỗi ra "DLL load failed while importing ..."."""
    if os.name != "nt":
        return True
    sysdir = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    return all((sysdir / f).is_file() for f in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"))


def check_vcredist() -> dict:
    if vcredist_ok():
        return _item("vcredist", "Bộ chạy Microsoft Visual C++", "ok", "Đã có")
    return _item("vcredist", "Bộ chạy Microsoft Visual C++", "bad", "Máy thiếu bộ chạy Visual C++ (msvcp140.dll)", FIX_VCREDIST,
                 "Thư viện AI cần bộ này của Microsoft. Bấm Cài bộ chạy Microsoft, Windows hỏi quyền thì bấm Có.")


def check_venv(deep: bool = True) -> dict:
    py = venv_python()
    if not py.is_file():
        return _item("venv", "Thư viện của Studio566", "bad", "Chưa cài thư viện (không có thư mục .venv)", FIX_SETUP,
                     "Phần cài thư viện chưa chạy xong, thường do mạng chập chờn lúc cài. Bấm Cài lại thư viện và để mạng ổn định.")
    if not deep:
        return _item("venv", "Thư viện của Studio566", "ok", "Đã cài")
    code = ("import importlib,json,traceback\nbad=[]\n"
            f"for m in {CORE_MODULES!r}:\n"
            "    try: importlib.import_module(m)\n"
            "    except BaseException as e: bad.append([m, type(e).__name__ + ': ' + str(e)[:400]])\n"
            "if not bad:\n"
            "    try: import icontent.web.server\n"
            "    except BaseException as e: bad.append(['icontent', traceback.format_exc()[-900:]])\n"
            "print('@@' + json.dumps(bad))\n")
    try:
        r = _run([str(py), "-X", "utf8", "-c", code], timeout=300, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return _item("venv", "Thư viện của Studio566", "warn", "Nạp thư viện quá 5 phút",
                     help="Máy đang rất chậm, hoặc phần mềm diệt virus đang quét từng file. Thêm thư mục Studio566 vào danh sách loại trừ.")
    except OSError as e:
        return _item("venv", "Thư viện của Studio566", "bad", f"Không chạy được Python của Studio566: {e}", FIX_SETUP,
                     "File Python trong .venv bị hỏng hoặc bị phần mềm diệt virus chặn. Bấm Cài lại thư viện.")
    m = re.search(r"@@(\[.*\])", r.stdout)
    if not m:
        tail = (r.stderr or r.stdout).strip()[-600:]
        return _item("venv", "Thư viện của Studio566", "bad", f"Python của Studio566 không chạy (mã {r.returncode}). {tail}", FIX_SETUP,
                     "Bấm Cài lại thư viện. Vẫn vậy thì gửi gói báo lỗi.")
    bad = json.loads(m.group(1))
    if not bad:
        return _item("venv", "Thư viện của Studio566", "ok", "Nạp đủ thư viện")
    text = "\n".join(f"{n}: {e}" for n, e in bad)
    if re.search(r"DLL load failed|_ctypes|WinError 126|specified module could not be found", text, re.I):
        fix = FIX_VCREDIST if not vcredist_ok() else FIX_SETUP
        return _item("venv", "Thư viện của Studio566", "bad", text[:900], fix,
                     "Windows không nạp được thư viện AI: máy thiếu bộ chạy Visual C++, hoặc phần mềm diệt virus đã chặn/xóa "
                     "một file .dll. Bấm nút sửa; vẫn lỗi thì thêm thư mục Studio566 vào danh sách loại trừ của phần mềm diệt virus "
                     "rồi bấm Cài lại thư viện.")
    return _item("venv", "Thư viện của Studio566", "bad", text[:900], FIX_SETUP,
                 "Thư viện cài chưa đủ hoặc bị hỏng. Bấm Cài lại thư viện (chỉ tải phần còn thiếu).")


def find_ffmpeg() -> str:
    cfg = ROOT / "config.yaml"
    dirs: list[Path] = []
    if cfg.is_file():
        m = re.search(r"(?m)^ffmpeg:\s*['\"]?([^'\"#\r\n]+)", cfg.read_text(encoding="utf-8", errors="replace"))
        if m and m.group(1).strip():
            p = Path(m.group(1).strip())
            dirs.append(p if p.is_dir() else p.parent)
    exe_sfx = ".exe" if os.name == "nt" else ""
    dirs += [ROOT / "tools" / "ffmpeg", ROOT / "tools" / "ffmpeg" / "bin"]
    if sys.platform == "darwin":
        dirs += [Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    for d in dirs:
        if (d / f"ffmpeg{exe_sfx}").is_file() and (d / f"ffprobe{exe_sfx}").is_file():
            return str(d / f"ffmpeg{exe_sfx}")
    f = shutil.which("ffmpeg")
    if f and shutil.which("ffprobe"):
        return f
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for f in Path(local, "Microsoft", "WinGet", "Packages").glob("Gyan.FFmpeg*/*/bin/ffmpeg.exe"):
            if f.with_name("ffprobe.exe").is_file():
                return str(f)
    return ""


def check_ffmpeg() -> dict:
    ff = find_ffmpeg()
    if not ff:
        return _item("ffmpeg", "ffmpeg (dựng video)", "bad", "Chưa có ffmpeg", FIX_SETUP,
                     "Bấm Cài lại thư viện: trình cài tự tải ffmpeg (khoảng 100 MB).")
    try:
        r = _run([ff, "-hide_banner", "-version"], timeout=30)
        line = (r.stdout.splitlines() or [""])[0]
        if r.returncode != 0 or "ffmpeg version" not in line:
            raise OSError((r.stderr or r.stdout).strip()[:300] or f"mã {r.returncode}")
    except (OSError, subprocess.SubprocessError) as e:
        return _item("ffmpeg", "ffmpeg (dựng video)", "bad", f"ffmpeg không chạy: {e}", FIX_SETUP,
                     "File ffmpeg hỏng hoặc bị phần mềm diệt virus chặn. Bấm Cài lại thư viện.")
    return _item("ffmpeg", "ffmpeg (dựng video)", "ok", "Bản " + (line.split() + ["", "", "?"])[2].split("-")[0])


def browser_path() -> str:
    if sys.platform == "darwin":
        for p in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ):
            if Path(p).is_file():
                return p
    bases = [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")]
    for rel in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
        for b in bases:
            if b and (Path(b) / rel).is_file():
                return str(Path(b) / rel)
    return shutil.which("msedge") or shutil.which("chrome") or ""


def check_browser() -> dict:
    b = browser_path()
    if not b:
        return _item("browser", "Cửa sổ Studio566 (Edge/Chrome)", "warn", "Không thấy Edge hay Chrome",
                     help="Studio566 sẽ mở trong trình duyệt mặc định. Nên cài Microsoft Edge hoặc Google Chrome để có cửa sổ riêng.")
    return _item("browser", "Cửa sổ Studio566 (Edge/Chrome)", "ok", "Edge" if "msedge" in b.lower() else "Chrome")


def app_alive(port: int = APP_PORT, timeout: float = 2.0) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # không đi qua proxy/VPN: đây là chính máy này
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/about", timeout=timeout) as r:
            return r.status == 200
    except Exception:      # noqa: BLE001
        return False


def port_owner(port: int) -> int:
    """PID đang giữ cổng (netstat), 0 nếu không ai giữ."""
    if os.name != "nt":
        return 0
    try:
        r = _run(["netstat", "-ano", "-p", "TCP"], timeout=20)
    except (OSError, subprocess.SubprocessError):
        return 0
    for ln in r.stdout.splitlines():
        f = ln.split()
        if len(f) >= 5 and f[1].endswith(f":{port}") and f[3].upper() == "LISTENING":
            try:
                return int(f[4])
            except ValueError:
                pass
    return 0


def process_path(pid: int) -> str:
    if os.name != "nt" or not pid:
        return ""
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.c_ulong(1024)
        return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally:
        k32.CloseHandle(h)


def _ours(path: str) -> bool:
    try:
        return bool(path) and Path(path).resolve().is_relative_to(ROOT.resolve())
    except (OSError, ValueError):
        return False


def check_port() -> dict:
    if app_alive():
        return _item("port", "Studio566 đang chạy", "ok", f"Cổng {APP_PORT} trả lời bình thường")
    pid = port_owner(APP_PORT)
    if not pid:
        return _item("port", "Cổng của Studio566", "ok", f"Cổng {APP_PORT} đang trống (Studio566 chưa mở)")
    path = process_path(pid)
    if _ours(path):
        return _item("port", "Cổng của Studio566", "bad", f"Một Studio566 cũ bị treo đang giữ cổng {APP_PORT}", FIX_KILL,
                     "Bấm Tắt Studio566 bị treo rồi mở lại Studio566.")
    if Path(path).name.lower().startswith("python"):
        return _item("port", "Cổng của Studio566", "bad", f"Một chương trình Python khác đang giữ cổng {APP_PORT}: {path}",
                     help="Có thể là Studio566 cài ở thư mục khác vẫn đang chạy. Tắt nó (hoặc khởi động lại máy) rồi mở lại Studio566.")
    return _item("port", "Cổng của Studio566", "bad", f"Cổng {APP_PORT} đang bị chương trình khác dùng: {Path(path).name or f'PID {pid}'}",
                 help="Tắt chương trình đó (hoặc khởi động lại máy) rồi mở lại Studio566.")


def check_start_error() -> dict | None:
    """Lỗi lúc mở Studio566 gần nhất (cli.py ghi lại vì chạy bằng pythonw không có dòng lệnh)."""
    if not START_ERROR.is_file():
        return None
    try:
        age = time.time() - START_ERROR.stat().st_mtime
        text = START_ERROR.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if age > 3 * 86400 or not text:
        return None
    when = "vừa xong" if age < 120 else f"{age / 60:.0f} phút trước" if age < 7200 else f"{age / 3600:.0f} giờ trước"
    return _item("start", "Lỗi khi mở Studio566", "bad", f"{when}: {text[:900]}",
                 help="Các mục bên dưới cho biết nguyên nhân. Sửa xong bấm Mở Studio566.")


def check_network() -> list[dict]:
    proxy = urllib.request.getproxies()

    def one(site):
        key, name, url, needed = site
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Studio566-support"})
        t = time.time()
        try:
            with urllib.request.urlopen(req, timeout=12):
                pass
            return key, name, needed, "", time.time() - t
        except urllib.error.HTTPError:      # máy chủ đã trả lời: mạng đi tới nơi
            return key, name, needed, "", time.time() - t
        except Exception as e:      # noqa: BLE001
            reason = getattr(e, "reason", e)
            return key, name, needed, f"{type(reason).__name__}: {reason}"[:200], time.time() - t

    with ThreadPoolExecutor(len(SITES)) as ex:
        res = list(ex.map(one, SITES))
    bad = [r for r in res if r[3]]
    if not bad:
        slow = [r[1] for r in res if r[4] > 5]
        return [_item("net", "Mạng", "warn" if slow else "ok", ("Chậm: " + ", ".join(slow)) if slow else "Vào được các trang Studio566 cần")]
    cert = [r for r in bad if re.search(r"CERTIFICATE|SSL", r[3], re.I)]
    if cert:
        return [_item("net", "Mạng", "bad", "Lỗi chứng chỉ khi vào: " + ", ".join(r[1] for r in cert),
                      help="Phần mềm diệt virus (Kaspersky, ESET, Avast...) đang quét kết nối HTTPS, hoặc giờ trên máy bị sai. "
                           "Chỉnh lại ngày giờ Windows, tắt tính năng quét HTTPS/SSL của phần mềm diệt virus rồi thử lại.")]
    need = [r for r in bad if r[2]]
    names = ", ".join(f"{r[1]} ({r[3][:60]})" for r in bad)
    tip = "Kiểm tra mạng, tắt VPN/proxy rồi thử lại." + (" Máy đang đặt proxy: " + ", ".join(sorted(proxy)) + "." if proxy else "")
    if len(bad) == len(res):
        return [_item("net", "Mạng", "bad", "Không vào được trang nào", help="Máy đang mất mạng hoặc tường lửa chặn Python. " + tip)]
    return [_item("net", "Mạng", "bad" if need else "warn", "Không vào được: " + names, help=tip)]


def check_douyin_cookie() -> dict:
    p = ROOT / "cookies" / "douyin.txt"
    title = "Cookie Douyin"
    if not p.is_file():
        return _item("douyin", title, "info", "Chưa nạp (chỉ cần khi tải video Douyin)")
    names, key_exp = set(), 0
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        f = ln.removeprefix("#HttpOnly_").split("\t")
        if len(f) >= 7 and not ln.startswith("# "):
            names.add(f[5])
            if f[5] == "s_v_web_id":
                key_exp = int(float(f[4] or 0))
    days = (time.time() - p.stat().st_mtime) / 86400
    detail = f"{len(names)} cookie, nạp {days:.0f} ngày trước" if days >= 1 else f"{len(names)} cookie, nạp hôm nay"
    if "s_v_web_id" not in names:
        return _item("douyin", title, "warn", detail + ", thiếu s_v_web_id",
                     help="File cookie xuất lúc trang Douyin chưa tải xong. Trong Studio566: Cài đặt → Cookie tải video → Nạp lại.")
    if key_exp and key_exp < time.time():
        return _item("douyin", title, "warn", detail + ", đã hết hạn", help="Nạp lại cookie Douyin trong Studio566: Cài đặt → Cookie tải video.")
    return _item("douyin", title, "ok", detail)


def run_checks(deep: bool = True, network: bool = True, in_app: bool = False) -> list[dict]:
    """Toàn bộ bước kiểm tra, xếp theo thứ tự nên sửa. deep: thử nạp thư viện (5–60 giây).
    in_app: gọi từ trong Studio566 đang chạy (bỏ bước cổng: chính nó đang giữ cổng, có khi là cổng khác 8765)."""
    out: list[dict] = []
    s = check_start_error()
    if s:
        out.append(s)
    out += [check_files(), check_folder(), check_windows(), check_vcredist(), check_venv(deep), check_ffmpeg(),
            check_browser()] + ([] if in_app else [check_port()])
    if network:
        out += check_network()
    out.append(check_douyin_cookie())
    return out


# ============================================================================ sửa

def kill_app() -> int:
    """Tắt mọi tiến trình Python của Studio566 (trừ chính công cụ này). Trả về số tiến trình đã tắt."""
    if os.name != "nt":
        return 0
    try:
        r = _run(["tasklist", "/fo", "csv", "/nh", "/fi", "IMAGENAME eq python*"], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 0
    me = {os.getpid(), os.getppid()}
    n = 0
    for ln in r.stdout.splitlines():
        f = [x.strip('"') for x in ln.split('","')]
        if len(f) < 2 or not f[1].isdigit():
            continue
        pid = int(f[1])
        if pid in me or not _ours(process_path(pid)):
            continue
        try:
            _run(["taskkill", "/pid", str(pid), "/t", "/f"], timeout=30)
            n += 1
        except (OSError, subprocess.SubprocessError):
            pass
    return n


def run_setup() -> str:
    """Chạy lại setup.ps1 trong một cửa sổ dòng lệnh để khách thấy tiến độ. setup.ps1 chỉ tải phần còn thiếu."""
    ps = ROOT / "setup.ps1"
    if not ps.is_file():
        raise RuntimeError("Thiếu file setup.ps1. Hãy chạy lại file cài Studio566.")
    kill_app()      # thư viện đang được Studio566 dùng thì không thay được
    # cmd /S /K "...": bỏ đúng cặp nháy ngoài cùng; chcp 65001 để chữ Việt PowerShell in ra không bị lỗi
    # (tiêu đề và câu cuối có dấu hiện đúng: đã thử thật trên cửa sổ dòng lệnh Windows 11)
    line = (f'cmd /S /K "chcp 65001 >nul & title Cài lại thư viện Studio566 & powershell -NoProfile -ExecutionPolicy Bypass '
            f'-File "{ps}" -NoShortcut -NoLaunch & echo. & echo Xong. Đóng cửa sổ này rồi bấm Kiểm tra lại trong cửa sổ Sửa lỗi Studio566."')
    subprocess.Popen(line, cwd=str(ROOT), creationflags=NEW_CONSOLE)
    return "Đang cài lại trong cửa sổ đen vừa mở (5–15 phút). Cứ để máy tự chạy, xong thì bấm Kiểm tra lại."


VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"


def install_vcredist() -> str:
    """Tải bộ cài Visual C++ chính thức của Microsoft rồi chạy (Windows hỏi quyền quản trị)."""
    dest = Path(os.environ.get("TEMP") or WORK) / "Studio566-vc_redist.x64.exe"
    with urllib.request.urlopen(urllib.request.Request(VCREDIST_URL, headers={"User-Agent": "Studio566-support"}), timeout=60) as r:
        data = r.read()
    if len(data) < 5_000_000 or data[:2] != b"MZ":
        raise RuntimeError("Tải bộ cài Microsoft không đúng. Thử lại sau, hoặc tải tay tại " + VCREDIST_URL)
    dest.write_bytes(data)
    os.startfile(str(dest), "runas", "/install /passive /norestart")      # noqa: S606 — bộ cài cần quyền quản trị
    return "Đã mở bộ cài của Microsoft. Bấm Có khi Windows hỏi, chờ chạy xong rồi bấm Kiểm tra lại."


def open_app() -> str:
    subprocess.Popen([str(runtime_python()), "-m", "icontent.start"], cwd=str(ROOT), creationflags=NO_WINDOW)
    return "Đang mở Studio566…"


def reset_window() -> str:
    """Xóa hồ sơ cửa sổ Studio566 (Edge/Chrome ở chế độ ứng dụng): cửa sổ trắng, kẹt cỡ cửa sổ, kẹt trang cũ."""
    d = Path(os.environ.get("LOCALAPPDATA") or ROOT) / "iContent" / "window"
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
    return "Đã làm mới cửa sổ Studio566. Bấm Mở Studio566."


FIXES = {"setup": run_setup, "vcredist": install_vcredist, "kill": lambda: f"Đã tắt {kill_app()} tiến trình. Bấm Mở Studio566.",
         "open_app": open_app, "reset_window": reset_window}


# ============================================================================ gói báo lỗi

def _home_variants() -> list[str]:
    h = os.path.expanduser("~")
    return [h, h.replace("\\", "/"), h.replace("\\", "\\\\")] if h and h != "~" else []


def _secret_values() -> list[str]:
    vals = []
    for f in (ROOT / "keys.json",):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            vals += [str(v) for v in data.values() if isinstance(v, str) and len(v) >= 8]
        except (OSError, ValueError, AttributeError):
            pass
    vals += [v for k, v in os.environ.items() if re.search(r"KEY|TOKEN|SECRET", k) and len(v) >= 8]
    return sorted(set(vals), key=len, reverse=True)


SECRET_RES = [
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), "AIza…"),
    (re.compile(r"sk-(?:ant-|proj-)?[0-9A-Za-z_\-]{16,}"), "sk-…"),
    (re.compile(r"\b(?:gsk|hf|xai|pplx)_[0-9A-Za-z]{16,}"), "…key…"),
    (re.compile(r"\b\d{8,10}:[0-9A-Za-z_\-]{30,}\b"), "…token…"),
    (re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|password|sessdata|s_v_web_id|ttwid|sessionid|authorization|bearer|key)"
                r"(\s*[\"']?\s*[=:]\s*[\"']?|\s+)([A-Za-z0-9._\-+/]{12,})"), r"\1\2…"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "<email>"),
]


def redact(text: str, secrets: list[str] | None = None) -> str:
    """Bỏ key, token, email, tên người dùng Windows, tên máy trước khi khách gửi file cho người khác."""
    t = str(text or "")
    for v in secrets if secrets is not None else _secret_values():
        t = t.replace(v, "…key…")
    for rx, rep in SECRET_RES:
        t = rx.sub(rep, t)
    for h in _home_variants():
        t = re.sub(re.escape(h), "%USERPROFILE%", t, flags=re.I)
    for name in (os.environ.get("USERNAME"), os.environ.get("COMPUTERNAME")):
        if name and len(name) >= 3:
            t = re.sub(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", "<may>", t, flags=re.I)
    return t


def _tail(p: Path, limit: int) -> str:
    try:
        with p.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - limit))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def setup_logs(n: int = 3) -> list[Path]:
    """Nhật ký của trình cài Studio566 (Inno Setup ghi vào %TEMP%\\Setup Log <ngày> #<số>.txt)."""
    tmp = Path(os.environ.get("TEMP") or "")
    if not tmp.is_dir():
        return []
    out = []
    for p in sorted(tmp.glob("Setup Log *.txt"), key=lambda p: p.stat().st_mtime, reverse=True)[:40]:
        try:
            with p.open("rb") as fh:
                head = fh.read(8000).decode("utf-8", errors="replace")
        except OSError:
            continue
        if "Studio566" in head or "iContent" in head:
            out.append(p)
            if len(out) >= n:
                break
    return out


def _desktop() -> Path:
    if os.name == "nt":
        buf = ctypes.create_unicode_buffer(1024)
        try:
            ctypes.OleDLL("shell32").SHGetFolderPathW(None, 0x10, None, 0, buf)
            if buf.value and Path(buf.value).is_dir():
                return Path(buf.value)
        except OSError:
            pass
    return WORK


def _version() -> str:
    try:      # file mất (phần mềm diệt virus xóa) thì vẫn phải tạo được gói báo lỗi
        text = (Path(__file__).resolve().parent / "__init__.py").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "?"
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else "?"


def _gpu() -> str:
    try:
        r = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                  "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name + ' | driver ' + $_.DriverVersion }"], timeout=25)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def make_report(checks: list[dict] | None = None, note: str = "", out_dir: Path | None = None) -> Path:
    """Gói báo lỗi (zip) trên màn hình nền: kết quả kiểm tra, nhật ký Studio566 và trình cài, cấu hình đã bỏ key, danh sách thư viện.
    Không có: key, cookie, video, tên người dùng, tên máy."""
    checks = checks if checks is not None else run_checks()
    secrets = _secret_values()
    stamp = time.strftime("%Y%m%d-%H%M")
    lines = [f"Studio566 {_version()} · {time.strftime('%d/%m/%Y %H:%M')}", f"Thư mục: {ROOT}", f"Python công cụ: {sys.version.split()[0]}", ""]
    if note.strip():
        lines += ["Khách mô tả:", note.strip(), ""]
    mark = {"ok": "OK  ", "warn": "CHÚ Ý", "bad": "LỖI ", "info": "--  "}
    for c in checks:
        lines.append(f"[{mark.get(c['state'], c['state'])}] {c['title']}: {c['detail']}")
        if c.get("help") and c["state"] in ("bad", "warn"):
            lines.append(f"        → {c['help']}")
    gpu = _gpu()
    if gpu:
        lines += ["", "Card đồ họa:", gpu]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("kiem-tra.txt", redact("\n".join(lines), secrets))
        for name, limit in (("studio.log", 3_000_000), ("studio.log.old", 1_000_000), ("start-error.txt", 50_000)):
            p = WORK / name
            if p.is_file():
                z.writestr(f"nhat-ky/{name}", redact(_tail(p, limit), secrets))
        for i, p in enumerate(setup_logs()):
            z.writestr(f"cai-dat/setup-{i + 1}.txt", redact(_tail(p, 2_000_000), secrets))
        cfg = ROOT / "config.yaml"
        if cfg.is_file():
            z.writestr("config.yaml", redact(cfg.read_text(encoding="utf-8", errors="replace"), secrets))
        if venv_python().is_file():
            try:
                r = _run([str(venv_python()), "-m", "pip", "list", "--format=freeze", "--disable-pip-version-check"], timeout=90, cwd=str(ROOT))
                z.writestr("thu-vien.txt", r.stdout or r.stderr)
            except (OSError, subprocess.SubprocessError) as e:
                z.writestr("thu-vien.txt", f"Không chạy được pip: {e}")
        listing = []
        for d in (ROOT, ROOT / "tools", ROOT / ".venv", ROOT / "runtime"):
            if d.is_dir():
                listing += [f"{d.relative_to(ROOT) if d != ROOT else '.'}/{p.name}{'/' if p.is_dir() else ''}" for p in sorted(d.iterdir())]
        z.writestr("thu-muc.txt", redact("\n".join(listing), secrets))
    out = Path(out_dir or os.environ.get("ICONTENT_REPORT_DIR") or _desktop()) / f"Studio566-goi-bao-loi-{stamp}.zip"
    out.write_bytes(buf.getvalue())
    return out


def reveal(p: Path) -> None:
    if os.name == "nt":
        subprocess.Popen(["explorer", f"/select,{p}"])


# ============================================================================ giao diện (http.server)

class _State:
    last_ping = 0.0
    visited = False
    checks: list[dict] = []
    reason = ""
    lock = threading.Lock()


def _page() -> bytes:
    return PAGE.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "iContentSupport"

    def log_message(self, *a):      # noqa: D401 — không in ra (chạy bằng pythonw thì không có chỗ in)
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if ctype.startswith("image/"):
            self.send_header("Access-Control-Allow-Origin", "*")      # màn hình chờ (file://) dò xem công cụ đã chạy chưa
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):      # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/static/icon.png", "/handoff.png"):
            if path == "/handoff.png" and not _State.reason:
                self._send(404, b"{}")
                return
            self._send(200, (STATIC / "icon.png").read_bytes(), "image/png")
            return
        if not self._host_ok():
            self._send(403, b"{}")
            return
        _State.last_ping = time.time()
        if path == "/":
            _State.visited = True
            self._send(200, _page(), "text/html; charset=utf-8")
        elif path == "/api/info":
            self._json({"version": _version(), "root": str(ROOT), "reason": _State.reason})
        elif path == "/api/ping":
            self._json({"ok": True})
        else:
            self._send(404, b"{}")

    def do_POST(self):      # noqa: N802
        # trang khác trên mạng không gửi được header tự đặt mà không qua hỏi CORS: chặn được trang lạ bấm hộ nút sửa
        if not self._host_ok() or self.headers.get("X-Studio566") != "1":
            self._send(403, b"{}")
            return
        _State.last_ping = time.time()
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(min(n, 100_000)) or b"{}") if n else {}
        path = self.path.split("?")[0]
        try:
            if path == "/api/checks":
                with _State.lock:
                    _State.checks = run_checks(deep=bool(body.get("deep", True)))
                self._json({"checks": _State.checks})
            elif path.startswith("/api/fix/"):
                fn = FIXES.get(path.rsplit("/", 1)[1])
                if not fn:
                    self._json({"error": "Không có cách sửa này"}, 404)
                    return
                self._json({"message": fn()})
            elif path == "/api/report":
                p = make_report(_State.checks or None, str(body.get("note") or "")[:4000])
                reveal(p)
                self._json({"path": str(p), "name": p.name, "size": p.stat().st_size})
            elif path == "/api/bye":
                _State.last_ping = 0.0
                self._json({"ok": True})
            else:
                self._send(404, b"{}")
        except Exception as e:      # noqa: BLE001 — hiện nguyên câu cho khách
            self._json({"error": str(e)[:600]}, 500)


def open_window(url: str) -> None:
    exe = browser_path()
    if not exe:
        webbrowser.open(url)
        return
    data = Path(os.environ.get("LOCALAPPDATA") or ROOT) / "iContent" / "support-window"
    subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={data}", "--window-size=980,860", "--no-first-run",
                      "--no-default-browser-check", "--disable-extensions"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def serve(reason: str = "", open_ui: bool = True, idle: float = 90.0, wait_first: float = 600.0) -> int:
    """Chạy giao diện Sửa lỗi. reason: vì sao được mở tự động (Studio566 không mở được). Tắt khi trang đóng (không hỏi thăm idle giây)."""
    _State.reason = reason
    srv = None
    for port in (PORT, 0):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            if port == PORT and _support_alive():      # đã có cửa sổ Sửa lỗi đang chạy: chỉ mở thêm cửa sổ
                if open_ui:
                    open_window(f"http://127.0.0.1:{PORT}/")
                return 0
    if srv is None:
        return 1
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    t0 = time.time()
    if open_ui:
        if reason:
            time.sleep(3)      # màn hình chờ của Studio566 (nếu còn mở) tự chuyển sang trang này; không thấy ai vào thì mở cửa sổ mới
        if not _State.visited:
            open_window(url)
    while True:
        time.sleep(2)
        now = time.time()
        if _State.visited and now - _State.last_ping > idle:
            break
        if not _State.visited and now - t0 > wait_first:
            break
    srv.shutdown()
    return 0


def _support_alive() -> bool:
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f"http://127.0.0.1:{PORT}/api/ping", timeout=2) as r:
            return r.status == 200
    except Exception:      # noqa: BLE001
        return False


PAGE = r"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sửa lỗi · Studio566</title><link rel="icon" href="/static/icon.png">
<style>
:root{--bg:#0b0a09;--card:#161411;--line:rgba(255,244,228,.09);--txt:#f5f1ea;--dim:#a39b8f;--acc:#ffb432;--ok:#5fcf8a;--warn:#ffb432;--bad:#ff6b5e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.55 "Segoe UI",system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:28px 24px 40px}
header{display:flex;gap:14px;align-items:center;margin-bottom:6px}header img{width:44px;height:44px;flex:none}
header>div{min-width:0}#ver{overflow-wrap:anywhere}
h1{font-size:20px;margin:0}.dim{color:var(--dim)}.small{font-size:12.5px}
.lead{margin:6px 0 20px;color:var(--dim)}
.banner{border:1px solid rgba(255,107,94,.35);background:rgba(255,107,94,.08);border-radius:10px;padding:12px 14px;margin-bottom:16px}
.list{border:1px solid var(--line);border-radius:12px;background:var(--card);overflow:hidden}
.row{display:grid;grid-template-columns:22px 1fr auto;gap:12px;padding:13px 16px;border-top:1px solid var(--line);align-items:start}
.row:first-child{border-top:0}.row b{font-weight:600}.det{color:var(--dim);font-size:13px;white-space:pre-wrap;word-break:break-word}
.help{margin-top:6px;font-size:13px;color:#e8dcc8}
.dot{width:18px;height:18px;border-radius:50%;margin-top:2px;display:grid;place-items:center;font-size:12px;font-weight:700;color:#0b0a09}
.ok .dot{background:var(--ok)}.warn .dot{background:var(--warn)}.bad .dot{background:var(--bad)}.info .dot{background:#5b554d}.wait .dot{background:#3a352f;animation:p 1s infinite alternate}
@keyframes p{to{opacity:.4}}
button{font:inherit;border-radius:8px;border:1px solid var(--line);background:#24201b;color:var(--txt);padding:7px 14px;cursor:pointer;white-space:nowrap}
button:hover{border-color:rgba(255,180,50,.5)}button.pri{background:var(--acc);color:#1a1206;border-color:var(--acc);font-weight:600}
button:disabled{opacity:.5;cursor:default}
.bar{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}
.card{border:1px solid var(--line);border-radius:12px;background:var(--card);padding:16px;margin-top:18px}
textarea{width:100%;min-height:64px;background:#0f0d0b;color:var(--txt);border:1px solid var(--line);border-radius:8px;padding:8px;font:inherit}
.msg{margin-top:10px;font-size:13px}.msg.ok{color:var(--ok)}.msg.bad{color:var(--bad)}
code{background:#0f0d0b;padding:1px 5px;border-radius:5px}
@media (max-width:600px){.row{grid-template-columns:22px 1fr}.row button{grid-column:2}}
</style></head><body><main>
<header><img src="/static/icon.png" alt=""><div><h1>Sửa lỗi Studio566</h1><div class="dim small" id="ver"></div></div></header>
<p class="lead">Công cụ này kiểm tra máy, sửa các lỗi hay gặp sau khi cài, và tạo gói báo lỗi để gửi người hỗ trợ. Chạy được cả khi Studio566 không mở được.</p>
<div id="banner"></div>
<div class="list" id="list"></div>
<div class="bar">
  <button class="pri" id="again">Kiểm tra lại</button>
  <button id="open">Mở Studio566</button>
  <button id="reset" title="Khi cửa sổ Studio566 trắng trơn, kẹt trang cũ, hoặc mở ra rồi tắt ngay">Làm mới cửa sổ Studio566</button>
</div>
<div class="card">
  <b>Vẫn chưa được? Gửi gói báo lỗi</b>
  <p class="dim small" style="margin:4px 0 10px">Gói gồm kết quả kiểm tra và nhật ký của Studio566. Đã tự bỏ key, cookie, email, tên người dùng và tên máy; không có video của bạn.
  Gửi file này cho người hỗ trợ qua Zalo hoặc Telegram.</p>
  <textarea id="note" placeholder="Mô tả ngắn (không bắt buộc): bấm vào đâu thì lỗi, thấy thông báo gì..."></textarea>
  <div class="bar" style="margin-bottom:0"><button class="pri" id="report">Tạo gói báo lỗi</button></div>
  <div class="msg" id="rmsg"></div>
</div>
</main>
<script>
const $ = (id) => document.getElementById(id);
const post = async (url, body) => {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Studio566': '1'}, body: JSON.stringify(body || {})});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || ('Lỗi ' + r.status));
  return j;
};
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const SIGN = {ok: '✓', warn: '!', bad: '✕', info: '·', wait: ''};
const RANK = {bad: 0, warn: 1, info: 2, ok: 3};
function paint(checks) {
  // mục cần sửa lên đầu (giữ thứ tự nên sửa trong từng nhóm)
  checks = checks.map((c, i) => [c, i]).sort((a, b) => (RANK[a[0].state] - RANK[b[0].state]) || (a[1] - b[1])).map((x) => x[0]);
  $('list').innerHTML = checks.map((c, i) => `<div class="row ${c.state}"><div class="dot">${SIGN[c.state] || ''}</div>
    <div><b>${esc(c.title)}</b><div class="det">${esc(c.detail)}</div>${c.help && c.state !== 'ok' ? `<div class="help">${esc(c.help)}</div>` : ''}</div>
    <div>${c.fix ? `<button class="${c.state === 'bad' ? 'pri' : ''}" data-fix="${esc(c.fix.id)}">${esc(c.fix.label)}</button>` : ''}</div></div>`).join('');
  const bad = checks.filter((c) => c.state === 'bad').length;
  return bad;
}
async function check() {
  $('again').disabled = true;
  $('list').innerHTML = '<div class="row wait"><div class="dot"></div><div><b>Đang kiểm tra máy…</b><div class="det">Thử nạp thư viện và vào mạng, mất 10–60 giây.</div></div><div></div></div>';
  try {
    const r = await post('/api/checks', {deep: true});
    const bad = paint(r.checks);
    if (!bad && !info.reason) $('banner').innerHTML = '';
    if (!bad && info.reason) $('banner').innerHTML = '<div class="banner" style="border-color:rgba(95,207,138,.35);background:rgba(95,207,138,.08)">Không thấy lỗi nào bây giờ. Bấm <b>Mở Studio566</b> để thử lại; vẫn không mở được thì tạo gói báo lỗi bên dưới.</div>';
  } catch (e) { $('list').innerHTML = `<div class="row bad"><div class="dot">✕</div><div><b>Không kiểm tra được</b><div class="det">${esc(e.message)}</div></div><div></div></div>`; }
  $('again').disabled = false;
}
document.addEventListener('click', async (e) => {
  const b = e.target.closest('button[data-fix]');
  if (!b) return;
  b.disabled = true;
  try { const r = await post('/api/fix/' + b.dataset.fix); b.textContent = 'Đã làm'; b.insertAdjacentHTML('afterend', `<div class="det" style="margin-top:6px">${esc(r.message)}</div>`); }
  catch (err) { b.disabled = false; b.insertAdjacentHTML('afterend', `<div class="det" style="color:var(--bad);margin-top:6px">${esc(err.message)}</div>`); }
});
const simple = (id, url) => $(id).onclick = async () => {
  $(id).disabled = true;
  try { const r = await post(url); $('rmsg').className = 'msg ok'; $('rmsg').textContent = r.message; } catch (e) { $('rmsg').className = 'msg bad'; $('rmsg').textContent = e.message; }
  setTimeout(() => { $(id).disabled = false; }, 2500);
};
simple('open', '/api/fix/open_app'); simple('reset', '/api/fix/reset_window');
$('again').onclick = check;
$('report').onclick = async () => {
  $('report').disabled = true; $('rmsg').className = 'msg'; $('rmsg').textContent = 'Đang tạo gói báo lỗi…';
  try {
    const r = await post('/api/report', {note: $('note').value});
    $('rmsg').className = 'msg ok';
    $('rmsg').innerHTML = `Đã lưu <code>${esc(r.name)}</code> (${Math.max(1, Math.round(r.size / 1024))} KB) ra màn hình nền và mở thư mục chứa nó. Gửi file này cho người hỗ trợ.`;
  } catch (e) { $('rmsg').className = 'msg bad'; $('rmsg').textContent = e.message; }
  $('report').disabled = false;
};
let info = {};
(async () => {
  try { info = await (await fetch('/api/info')).json(); } catch (_) { info = {}; }
  $('ver').textContent = `Studio566 ${info.version || ''} · ${info.root || ''}`;
  if (info.reason) $('banner').innerHTML = '<div class="banner"><b>Studio566 chưa mở được.</b> Đang kiểm tra xem vì sao. Mục nào có nút thì bấm để sửa, xong bấm <b>Mở Studio566</b>.</div>';
  check();
})();
setInterval(() => fetch('/api/ping').catch(() => {}), 10000);
addEventListener('pagehide', () => fetch('/api/bye', {method: 'POST', headers: {'X-Studio566': '1'}, keepalive: true}).catch(() => {}));
</script></body></html>"""


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="icontent.support", description="Sửa lỗi Studio566")
    p.add_argument("--reason", default="")
    p.add_argument("--report", action="store_true", help="chỉ tạo gói báo lỗi rồi thoát")
    p.add_argument("--check", action="store_true", help="in kết quả kiểm tra rồi thoát")
    a = p.parse_args(argv)
    if a.check or a.report:
        if sys.stdout:
            sys.stdout.reconfigure(encoding="utf-8")
        checks = run_checks()
        for c in checks:
            print(f"[{c['state']:4}] {c['title']}: {c['detail']}" + (f"\n        → {c['help']}" if c.get("help") and c["state"] != "ok" else ""))
        if a.report:
            print("Gói báo lỗi:", make_report(checks))
        return 0
    return serve(a.reason)


if __name__ == "__main__":
    sys.exit(main())
