"""Đóng gói bản phát hành gửi cho người dùng, hai dạng cùng một nội dung:

  python -m icontent release            -> dist/iContent-Setup-<phiên bản>.exe  bấm đúp là cài (Inno Setup, installer/iContent.iss)
                                           dist/iContent-<phiên bản>.zip        giải nén rồi bấm đúp "Cai dat iContent.cmd"
                                           (+ .sha256 cho mỗi file)

Chỉ gồm mã nguồn, giao diện, Trình dựng đã build, các file cài đặt và bản Python của môi trường đóng gói (thư mục runtime\\python,
bỏ bộ test, tài liệu, thư viện đã cài). Không bao giờ có dữ liệu riêng của máy đóng gói: key, cấu hình, video, giọng đã thu, thư mục
làm việc của Trình dựng. Trước khi nén còn dò lại: file nào chứa đúng một key đang có trên máy, hay mã nguồn có chuỗi giống API key,
là dừng.

Kèm constraints.txt: đúng phiên bản thư viện của môi trường đã chạy qua bộ test. Máy người dùng cài ra y hệt, không vớ phải bản thư viện
mới hơn chưa ai thử (requirements.txt chỉ ghi "từ bản này trở lên"). Python kèm theo cũng chính là bản đã chạy bộ test: máy người dùng
không cần cài Python, không cần winget.

Không kèm ffmpeg: bản dựng sẵn là GPL, phát tán lại thì phải kèm mã nguồn. setup.ps1 tải về trên máy người dùng (winget, hoặc GitHub).
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from . import __version__
from .util import ROOT

TOP_FILES = ["Cai dat iContent.cmd", "iContent Studio.cmd", "icontent.cmd", "setup.ps1", "requirements.txt", "config.example.yaml", "README.md"]
PACKAGE = "icontent"
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
SKIP_SUFFIX = {".pyc", ".pyo", ".log", ".bak", ".part", ".copying"}
SKIP_NAMES = {"Thumbs.db", ".DS_Store", "desktop.ini", "_build_info.py"}      # _build_info.py do chính lệnh này sinh vào gói
# những thứ chỉ có trên máy đóng gói: nằm đâu trong gói cũng không được có
PRIVATE_NAMES = {"keys.json", "paid.json", "config.yaml", "presets.json", "trends_saved.json", "cookies.txt", "index.json", ".freecut-workspace.json",
                 "license.json", ".install_id"}
PUBKEY_FILE = "license_pubkey.txt"      # khoá CÔNG KHAI iContent của bot cấp key (công khai, được commit)
# chỉ dò mẫu key trong mã của chính iContent: thư viện đóng gói sẵn của Trình dựng có chuỗi ngẫu nhiên dài, dò mẫu dễ báo nhầm
KEY_PATTERNS = [re.compile(p) for p in (rb"AIza[0-9A-Za-z_\-]{35}", rb"sk-ant-[A-Za-z0-9_\-]{20,}", rb"sk-[A-Za-z0-9]{40,}", rb"hf_[A-Za-z0-9]{30,}")]
OWN_TEXT = {".py", ".js", ".css", ".html", ".json", ".yaml", ".yml", ".txt", ".md", ".ps1", ".cmd", ".tsv"}
CRLF = "\r\n"
RUNTIME = "runtime/python"      # chỗ đặt Python kèm theo trong gói; setup.ps1 tìm ở đây trước tiên
# không cần để chạy iContent hay tạo .venv: tài liệu, bộ test của Python, IDLE, file để biên dịch thư viện C, thư viện đã cài trên máy đóng gói
RUNTIME_SKIP = {"Doc", "include", "libs", "Scripts", "Tools", "NEWS.txt", "Lib/site-packages", "Lib/test", "Lib/idlelib", "Lib/turtledemo"}
OK_PYTHON = ("3.11", "3.12", "3.13")      # khớp $okVersions trong setup.ps1
INSTALLER = "installer/iContent.iss"
STORED = (".wasm", ".onnx", ".png", ".jpg", ".webp", ".woff2", ".mp3", ".gz", ".br", ".whl")      # đã nén sẵn: nén thêm chỉ tốn thời gian


def guide_text(version: str, bot: str = "") -> str:
    from .about import cli_line
    lines = [
        f"iContent Studio {version}: phần mềm miễn phí làm video tiếng Việt",
        "",
        "CÀI ĐẶT LẦN ĐẦU",
        f"Cách 1 (dễ nhất): bấm đúp file iContent-Setup-{version}.exe, bấm Tiếp cho tới khi xong.",
        "   Windows hiện \"Windows đã bảo vệ máy tính của bạn\" thì bấm \"Thông tin bổ sung\" rồi \"Vẫn chạy\".",
        "Cách 2 (bản zip):",
        "1. Giải nén file zip ra một thư mục, ví dụ D:\\iContent. Đừng chạy thẳng trong cửa sổ xem file zip.",
        "   Nên để ở ổ có nhiều chỗ trống (cần khoảng 8 GB), tránh thư mục OneDrive và Program Files.",
        "2. Bấm đúp file \"Cai dat iContent.cmd\".",
        "Cả hai cách đều cần mạng Internet, lần đầu tải thêm khoảng 3 GB, mất 5 đến 15 phút. Máy không cần cài sẵn Python.",
        "Cài xong có biểu tượng iContent Studio trên màn hình nền. Lần mở đầu có hướng dẫn từng bước.",
        "",
    ]
    if bot:
        lines += [
            "KÍCH HOẠT (miễn phí)",
            "Lần mở đầu, iContent hiện màn Kích hoạt có MÃ MÁY (32 ký tự).",
            f"1. Bấm \"Nhận key qua Telegram\": mở bot @{bot} kèm sẵn mã máy (hoặc tự gửi mã máy cho bot, chọn iContent).",
            "2. Trong bot bấm \"Yêu cầu kích hoạt\". Được duyệt, bot gửi key.",
            "3. Chép nguyên key, dán vào ô trên màn Kích hoạt, bấm Kích hoạt.",
            "Mỗi key dùng cho một máy. Cài lại, cập nhật bản mới trên cùng máy không phải xin key lại. Gia hạn: Cài đặt > Bản quyền.",
            "",
        ]
    lines += [
        "CẬP NHẬT BẢN MỚI",
        "Bản .exe: chạy file cài bản mới, nó tự cài đè đúng thư mục cũ (iContent đang mở thì tự tắt trước).",
        "Bản zip: giải nén bản mới đè lên đúng thư mục cũ (chọn Thay thế tất cả), rồi bấm đúp \"Cai dat iContent.cmd\" một lần nữa.",
        "Video, cấu hình, key, giọng đã thu đều được giữ nguyên.",
        "",
        "GỠ CÀI ĐẶT",
        "Cài bằng .exe: Cài đặt Windows > Ứng dụng > iContent Studio > Gỡ cài đặt. Trình gỡ hỏi có giữ video, cấu hình không.",
        "",
        "MÁY CẦN CÓ",
        "Windows 10 hoặc 11 bản 64-bit, RAM từ 8 GB, ổ đĩa trống từ 8 GB.",
        "Card NVIDIA (GTX 1650 trở lên) giúp dựng video nhanh hơn nhiều; không có vẫn chạy được, chậm hơn.",
        "",
        "GẶP LỖI",
        "Chụp màn hình cửa sổ cài đặt gửi cho tác giả. Đã mở được iContent thì xem Trang chủ, mục Máy đã sẵn sàng chưa.",
        "",
        cli_line(),
    ]
    return CRLF.join(lines) + CRLF      # Notepad cũ chỉ hiểu xuống dòng kiểu Windows


def frozen_requirements(python: str | None = None) -> str:
    """pip freeze của môi trường đang chạy: bỏ gói cài từ thư mục, từ git (máy khác không có)."""
    r = subprocess.run([python or sys.executable, "-m", "pip", "freeze", "--disable-pip-version-check"], capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise RuntimeError("pip freeze lỗi: " + r.stderr[-300:])
    keep = [ln.strip() for ln in r.stdout.splitlines()
            if ln.strip() and not ln.startswith(("-e", "#")) and " @ " not in ln and "==" in ln]
    head = f"# Phiên bản thư viện đã chạy qua bộ test của iContent {__version__}. setup.ps1 cài theo đúng các bản này.\n"
    return head + "\n".join(sorted(keep, key=str.lower)) + "\n"


def collect(root: Path = ROOT) -> list[tuple[Path, str]]:
    """[(file trên máy, tên trong zip)], tên trong zip tương đối với thư mục gốc của gói."""
    out: list[tuple[Path, str]] = []
    for name in TOP_FILES:
        f = root / name
        if not f.is_file():
            raise FileNotFoundError(f"Thiếu {name}")
        out.append((f, name))
    pkg = root / PACKAGE
    for dirpath, dirnames, filenames in os.walk(pkg):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in sorted(filenames):
            f = Path(dirpath) / fn
            if fn in SKIP_NAMES or f.suffix.lower() in SKIP_SUFFIX:
                continue
            out.append((f, f.relative_to(root).as_posix()))
    return out


def collect_runtime(base: Path) -> list[tuple[Path, str]]:
    """Bản Python để kèm vào gói (thư mục gốc của Python, tức sys.base_prefix của .venv): đủ để chạy và tạo .venv, bỏ phần không cần."""
    base = Path(base)
    if not (base / "python.exe").is_file() or not (base / "Lib" / "venv").is_dir() or not (base / "Lib" / "ensurepip").is_dir():
        raise RuntimeError(f"{base} không phải thư mục Python đầy đủ (cần python.exe, Lib\\venv, Lib\\ensurepip)")
    out: list[tuple[Path, str]] = []
    for dirpath, dirnames, filenames in os.walk(base):
        rel = Path(dirpath).relative_to(base).as_posix()
        rel = "" if rel == "." else rel + "/"
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and rel + d not in RUNTIME_SKIP)
        for fn in sorted(filenames):
            if rel + fn in RUNTIME_SKIP or Path(fn).suffix.lower() in (".pyc", ".pyo"):
                continue
            out.append((Path(dirpath) / fn, f"{RUNTIME}/{rel}{fn}"))
    return out


def python_version(exe: str | Path) -> str:
    r = subprocess.run([str(exe), "-c", "import sys;print('%d.%d' % sys.version_info[:2])"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def find_iscc() -> str | None:
    """Trình biên dịch Inno Setup 6 (winget install JRSoftware.InnoSetup cài theo người dùng, vào LOCALAPPDATA)."""
    cands = [shutil.which("iscc")]
    for env in ("LOCALAPPDATA", "ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(env):
            cands.append(str(Path(os.environ[env]) / ("Programs" if env == "LOCALAPPDATA" else "") / "Inno Setup 6" / "ISCC.exe"))
    return next((c for c in cands if c and Path(c).is_file()), None)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    path.with_name(path.name + ".sha256").write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return digest


def _secrets() -> list[bytes]:
    """Giá trị key thật đang có trên máy (keys.json, biến môi trường): không được nằm trong gói, dù ở file nào."""
    from .keys import ALLOWED, _read
    vals = {str(v) for v in _read().values() if v}
    vals |= {os.environ[n] for n in ALLOWED if os.environ.get(n)}
    return [v.encode() for v in vals if len(v) >= 12]


def check(files: list[tuple[Path, str]]) -> list[str]:
    """Lỗi chặn phát hành (không có nghĩa là cảnh báo): file riêng tư, key lọt vào gói."""
    problems = []
    secrets = _secrets()
    for f, arc in files:
        if Path(arc).name in PRIVATE_NAMES:
            problems.append(f"{arc}: file riêng của máy này")
            continue
        data = f.read_bytes()
        if any(s in data for s in secrets):
            problems.append(f"{arc}: có chứa một API key đang dùng trên máy này")
            continue
        own = not arc.startswith((f"{PACKAGE}/web/editor/", f"{PACKAGE}/web/static/vendor/", RUNTIME + "/"))
        if own and f.suffix.lower() in OWN_TEXT and any(p.search(data) for p in KEY_PATTERNS):
            problems.append(f"{arc}: có chuỗi giống API key")
    names = {arc for _, arc in files}
    for need in (f"{PACKAGE}/__main__.py", f"{PACKAGE}/web/static/index.html", "setup.ps1"):
        if need not in names:
            problems.append(f"thiếu {need}")
    return problems


def resolve_pubkey(pubkey: str | None, root: Path = ROOT) -> str:
    """Khoá công khai Ed25519 (base64url, 32 byte) để nhúng vào bản phát hành. "" nếu chưa có."""
    raw = (pubkey or "").strip()
    f = root / PACKAGE / PUBKEY_FILE
    if not raw and f.is_file():
        raw = next((ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")), "")
    if not raw:
        return ""
    try:
        ok = len(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))) == 32 and re.fullmatch(r"[A-Za-z0-9_-]{43}", raw)
    except ValueError:
        ok = False
    if not ok:
        raise RuntimeError("Khoá công khai không đúng dạng: phải là dòng 43 ký tự bot in ra sau lệnh python -m ikey.keygen icontent --enable")
    return raw


def build_info(pubkey: str, bot: str, version: str) -> str:
    return ('"""Sinh tự động bởi `icontent release`. Không sửa tay: bản phát hành này khoá bản quyền, key do bot Telegram cấp."""\n'
            f"PUBLIC_KEY = {pubkey!r}\nENFORCE = {bool(pubkey)}\nTELEGRAM = {bot!r}\nVERSION = {version!r}\n")


def stage(files: list[tuple[Path, str]], extra: dict[str, str], dest: Path) -> None:
    """Dàn đúng nội dung bản phát hành ra thư mục dest: file zip nén từ đây, bộ cài .exe cũng đóng gói từ đây."""
    for f, arc in files:
        out = dest / arc
        out.parent.mkdir(parents=True, exist_ok=True)
        if f.suffix.lower() in (".cmd", ".bat", ".ps1"):
            # cmd.exe và PowerShell 5.1 cần xuống dòng kiểu Windows; git trên máy khác có thể đã đổi thành \n hay \r\r\n
            out.write_bytes(re.sub(rb"\r*\n", b"\r\n", f.read_bytes()))
        else:
            shutil.copyfile(f, out)
    for name, text in extra.items():
        out = dest / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(text.encode("utf-8-sig" if name.endswith(".txt") and not name.startswith("constraints") else "utf-8"))


def _zip(src: Path, zpath: Path, base: str = "iContent/") -> None:
    tmp = zpath.with_name(zpath.name + ".part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames.sort()
            for fn in sorted(filenames):
                f = Path(dirpath) / fn
                z.write(f, base + f.relative_to(src).as_posix(), compress_type=zipfile.ZIP_STORED if f.suffix.lower() in STORED else zipfile.ZIP_DEFLATED)
    os.replace(tmp, zpath)


def _installer(iscc: str, iss: Path, src: Path, out_dir: Path, name: str) -> Path:
    """Biên dịch installer/iContent.iss trên thư mục đã dàn sẵn. Mất vài phút: nén LZMA2 vài trăm MB."""
    r = subprocess.run([iscc, "/Q", f"/DAppVersion={__version__}", f"/DStageDir={src}", f"/DOutputDir={out_dir}", f"/DOutputBase={name}", str(iss)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    exe = out_dir / f"{name}.exe"
    if r.returncode or not exe.is_file():
        raise RuntimeError("Inno Setup báo lỗi khi tạo file cài .exe:\n" + (r.stdout + r.stderr).strip()[-1500:])
    return exe


def build(out_dir: Path | None = None, root: Path = ROOT, python: str | None = None, pubkey: str | None = None,
          free: bool = True, bot: str = "", runtime: str | Path | None = None, exe: bool = False, iscc: str | None = None) -> dict:
    """free=True (mặc định trong bản fork): bản phát hành KHÔNG khoá bản quyền. free=False: bản khoá, cần khoá công khai iContent của bot (tham số hoặc icontent/license_pubkey.txt).
    runtime: thư mục Python kèm vào gói (lệnh release truyền sys.base_prefix). exe: tạo thêm bộ cài .exe bằng Inno Setup."""
    from .license import DEFAULT_BOT
    out_dir = Path(out_dir or root / "dist")
    pub = "" if free else resolve_pubkey(pubkey, root)
    if not free and not pub:
        raise RuntimeError("Chưa có khoá công khai iContent của bot cấp key. Trên VPS chạy: python -m ikey.keygen icontent --enable, "
                           f"chép dòng khoá công khai vào icontent/{PUBKEY_FILE} (hoặc --pubkey), rồi đóng gói lại. Muốn bản không khoá: --free")
    bot = (bot or DEFAULT_BOT).lstrip("@")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", bot):
        raise RuntimeError(f"Tên bot Telegram không hợp lệ: {bot}")
    files = collect(root)
    if runtime:
        # Python kèm theo phải đúng phiên bản của môi trường làm ra constraints.txt, nếu không thư viện ghim sẵn có thể không có bản cho nó
        rv, ev = python_version(Path(runtime) / "python.exe"), python_version(python or sys.executable)
        if rv not in OK_PYTHON or rv != ev:
            raise RuntimeError(f"Python kèm theo ({runtime}: {rv or '?'}) phải là 3.11 đến 3.13 và trùng môi trường đóng gói ({ev or '?'})")
        files += collect_runtime(Path(runtime))
    problems = check(files)
    if problems:
        raise RuntimeError("Không đóng gói: " + "; ".join(problems[:8]))
    iss = root / INSTALLER
    if exe:
        iscc = iscc or find_iscc()
        if not iscc:
            raise RuntimeError("Chưa có Inno Setup 6 để tạo file cài .exe. Cài bằng: winget install JRSoftware.InnoSetup  (hoặc chỉ làm zip: --no-exe)")
        if not iss.is_file():
            raise RuntimeError(f"Thiếu {INSTALLER}")
        if not runtime:
            # biểu tượng và công cụ Sửa lỗi của bản cài chạy bằng runtime\python (chạy được cả khi .venv hỏng)
            raise RuntimeError("File cài .exe cần kèm Python (bỏ --no-python), hoặc chỉ làm zip: --no-exe")
    warnings = []
    if not (root / PACKAGE / "web" / "editor" / "index.html").is_file():
        warnings.append("Chưa có Trình dựng đã build (icontent/web/editor): gói vẫn chạy, chỉ thiếu Trình dựng")
    if not runtime:
        warnings.append("Không kèm Python: máy người dùng phải có sẵn Python 3.11 đến 3.13, hoặc có winget để tự cài")
    out_dir.mkdir(parents=True, exist_ok=True)
    extra = {"constraints.txt": frozen_requirements(python), "HUONG DAN.txt": guide_text(__version__, bot if pub else "")}
    if pub:
        extra[f"{PACKAGE}/_build_info.py"] = build_info(pub, bot, __version__)
    work = out_dir / f".dan-goi-{__version__}"
    src = work / "iContent"
    shutil.rmtree(work, ignore_errors=True)
    try:
        stage(files, extra, src)
        zpath = out_dir / f"iContent-{__version__}.zip"
        _zip(src, zpath)
        result = {"path": str(zpath), "size": zpath.stat().st_size, "files": len(files) + len(extra), "sha256": _sha256(zpath),
                  "warnings": warnings, "free": not pub, "bot": bot, "python": bool(runtime)}
        if exe:
            setup = _installer(iscc, iss, src, out_dir, f"iContent-Setup-{__version__}")
            result.update(exe=str(setup), exe_size=setup.stat().st_size, exe_sha256=_sha256(setup))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return result
