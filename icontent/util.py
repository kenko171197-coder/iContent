"""Tiện ích chung: log + sự kiện tiến độ (cho web UI), hủy job, tìm/chạy ffmpeg, đọc/ghi WAV."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
from contextlib import contextmanager
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
# thông báo kỹ thuật của Hugging Face không có ích gì với người dùng
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")


# --------------------------------------------------------------------------- sự kiện / hủy

_listeners: list = []
_cancel = threading.Event()


class Cancelled(Exception):
    """Người dùng bấm Hủy."""


def add_listener(fn) -> None:
    """fn(kind, data): kind = log | stage | progress."""
    _listeners.append(fn)


def remove_listener(fn) -> None:
    if fn in _listeners:
        _listeners.remove(fn)


def emit(kind: str, **data) -> None:
    for fn in list(_listeners):
        try:
            fn(kind, data)
        except Exception:
            pass


def log(stage: str, msg: str) -> None:
    print(f"[{stage}] {msg}", flush=True)
    emit("log", stage=stage, msg=msg)


def note(msg: str) -> None:
    """Cập nhật dòng trạng thái trên giao diện, không ghi vào nhật ký (dùng cho thông báo đổi liên tục)."""
    emit("note", msg=msg)


def hf_cache_dir() -> Path:
    home = os.environ.get("HF_HOME")
    return Path(os.environ.get("HF_HUB_CACHE") or (Path(home) / "hub" if home else Path.home() / ".cache" / "huggingface" / "hub"))


def _dir_mb(p: Path) -> float:
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / 1e6


def _hook_hf_progress(got: list[float]):
    """Nghe số byte đã tải từ huggingface_hub, vì đo thư mục không được: hf_xet chỉ ghi file ra đĩa từng đợt lớn.

    Đây là API nội bộ của thư viện nên luôn bọc an toàn: nếu thư viện đổi thì chỉ mất số MB chính xác
    (vẫn còn đo theo đĩa), không làm hỏng việc tải. Trả về hàm khôi phục.
    """
    undo = []
    http = [0.0]
    groups: dict[int, float] = {}

    def total() -> None:
        got[0] = http[0] + sum(groups.values())

    try:      # tải qua Xet (mặc định với các model lớn)
        from huggingface_hub.utils import _xet_progress_reporting as xp

        orig_xet = xp.XetDownloadProgressReporter.update_progress

        def update_progress(self, group_report, *a, **k):
            try:
                groups[id(self)] = float(max(group_report.total_transfer_bytes_completed,
                                             group_report.total_bytes_completed))
                total()
            except AttributeError:
                pass
            return orig_xet(self, group_report, *a, **k)

        xp.XetDownloadProgressReporter.update_progress = update_progress
        undo.append(lambda: setattr(xp.XetDownloadProgressReporter, "update_progress", orig_xet))
    except Exception:
        pass
    try:      # tải HTTP thường: có thanh tiến độ theo byte (kể cả khi không có console)
        import huggingface_hub.file_download as fd
        from huggingface_hub.utils import tqdm as hf_tqdm

        orig_http = fd.http_get

        def http_get(*a, **k):
            orig_update = hf_tqdm.update

            def update(self, n=1):
                if n and (getattr(self, "total", 0) or 0) >= 1_000_000:
                    http[0] += n
                    total()
                return orig_update(self, n)

            hf_tqdm.update = update
            try:
                return orig_http(*a, **k)
            finally:
                hf_tqdm.update = orig_update

        fd.http_get = http_get
        undo.append(lambda: setattr(fd, "http_get", orig_http))
    except Exception:
        pass

    def restore() -> None:
        for fn in undo:
            fn()
    return restore


@contextmanager
def watch_download(stage_name: str, label: str, total_mb: float | None = None):
    """Trong lúc thư viện tự tải model: báo tiến độ để màn hình không trông như bị treo."""
    base = hf_cache_dir()
    start = _dir_mb(base)
    got = [0.0]
    restore = _hook_hf_progress(got)
    done = threading.Event()

    def run() -> None:
        while not done.wait(1.0):
            mb = max(got[0] / 1e6, _dir_mb(base) - start)
            if total_mb:
                progress(stage_name, min(0.99, mb / total_mb))
                note(f"{label}: {mb:.0f}/{total_mb:.0f} MB (chỉ tải lần đầu)")
            elif mb >= 3:
                note(f"{label}: đã tải {mb:.0f} MB (chỉ tải lần đầu)")

    t = threading.Thread(target=run, daemon=True, name="icontent-worker-watch")
    t.start()
    try:
        yield
    finally:
        done.set()
        restore()


def stage(name: str) -> None:
    """Báo bắt đầu một bước của pipeline."""
    emit("stage", stage=name)
    check_cancel()


def progress(stage_name: str, frac: float | None) -> None:
    emit("progress", stage=stage_name, frac=None if frac is None else max(0.0, min(1.0, float(frac))))


def request_cancel() -> None:
    _cancel.set()


def reset_cancel() -> None:
    _cancel.clear()


def check_cancel() -> None:
    # thao tác trên giao diện (nghe lại, tự dò...) chạy ở luồng khác, không liên quan tới video vừa bị hủy
    if _cancel.is_set() and not threading.current_thread().name.startswith(("AnyIO", "MainThread", "ui-")):
        raise Cancelled("Đã hủy")


def fix_console_encoding() -> None:
    """Console Windows (cp1258...) không in được chữ Trung -> ép UTF-8."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def short_hash(*parts: str) -> str:
    return hashlib.sha1("␟".join(parts).encode("utf-8")).hexdigest()[:10]


def safe_name(s: str, max_len: int = 60) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:max_len].rstrip(" .") or "video"


# --------------------------------------------------------------------------- ffmpeg

_FF: tuple[str, str] | None = None


def find_ffmpeg(configured: str = "") -> tuple[str, str]:
    """Trả về (ffmpeg, ffprobe). Thứ tự: config -> tools/ffmpeg -> PATH -> winget."""
    global _FF
    if _FF:
        return _FF
    exe = ".exe" if os.name == "nt" else ""
    dirs: list[Path] = []
    if configured:
        p = Path(configured)
        dirs.append(p if p.is_dir() else p.parent)
    dirs += [ROOT / "tools" / "ffmpeg", ROOT / "tools" / "ffmpeg" / "bin"]
    if sys.platform == "darwin":
        dirs += [Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    for d in dirs:
        if (d / f"ffmpeg{exe}").exists() and (d / f"ffprobe{exe}").exists():
            _FF = (str(d / f"ffmpeg{exe}"), str(d / f"ffprobe{exe}"))
            return _FF
    f, p = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if f and p:
        _FF = (f, p)
        return _FF
    # winget (Gyan.FFmpeg) cài vào đây nhưng PATH chỉ cập nhật sau khi mở lại terminal
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for f in Path(local, "Microsoft", "WinGet", "Packages").glob("Gyan.FFmpeg*/*/bin/ffmpeg.exe"):
            p = f.with_name("ffprobe.exe")
            if p.exists():
                _FF = (str(f), str(p))
                return _FF
    raise RuntimeError(
        "Không tìm thấy ffmpeg. Cài bằng:  winget install Gyan.FFmpeg  "
        "(hoặc chép ffmpeg.exe + ffprobe.exe vào tools/ffmpeg/, hoặc đặt 'ffmpeg:' trong config.yaml)"
    )


FFMPEG_STALL_SECONDS = 180


def replace_file(src: Path, dst: Path) -> None:
    """Thay file đích. Windows không cho thay khi trình duyệt đang đọc file đó (đang xem video): thử lại vài lần,
    cuối cùng chép đè nội dung, cách này được phép vì máy chủ mở file cho phép ghi chung."""
    src, dst = Path(src), Path(dst)
    for _ in range(6):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            time.sleep(0.4)
    shutil.copyfile(src, dst)
    src.unlink(missing_ok=True)


def ffmpeg(args: list[str], cwd: str | Path | None = None, progress_stage: str | None = None,
           total: float | None = None, stall_seconds: float | None = None) -> None:
    """Chạy ffmpeg; có progress_stage + total (giây) thì báo tiến độ và cho phép hủy giữa chừng."""
    exe, _ = find_ffmpeg()
    if not (progress_stage and total):
        cmd = [exe, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg lỗi ({r.returncode}):\n{' '.join(cmd)}\n{r.stderr[-3000:]}")
        return
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y", *map(str, args)]
    err: list[str] = []
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace")
    t = threading.Thread(target=lambda: err.extend(proc.stderr), daemon=True)
    t.start()
    seen = {"at": time.time(), "pos": None, "stalled": False, "done": False}
    limit = stall_seconds or FFMPEG_STALL_SECONDS

    def watch():
        # ffmpeg có thể bế tắc mà không thoát: không để người dùng chờ vô hạn
        while not seen["done"]:
            time.sleep(1)
            if _cancel.is_set():
                proc.kill()
                return
            if time.time() - seen["at"] > limit:
                seen["stalled"] = True
                proc.kill()
                return

    threading.Thread(target=watch, daemon=True, name="ffmpeg-watch").start()
    try:
        for line in proc.stdout:
            if line.startswith("out_time_us="):
                val = line.split("=", 1)[1].strip()
                if val != seen["pos"]:
                    seen["pos"], seen["at"] = val, time.time()
                try:
                    progress(progress_stage, int(val) / 1e6 / total)
                except ValueError:
                    pass
            if _cancel.is_set():
                proc.kill()
                raise Cancelled("Đã hủy")
    finally:
        seen["done"] = True
        proc.wait()
        t.join(timeout=2)
    if _cancel.is_set():
        raise Cancelled("Đã hủy")
    if seen["stalled"]:
        raise RuntimeError(f"Dựng video bị treo: ffmpeg không chạy tiếp trong {int(limit)} giây nên đã dừng lại. "
                           "Hãy thử lại, nếu vẫn lỗi hãy gửi nhật ký cho người hỗ trợ.")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg lỗi ({proc.returncode}):\n{' '.join(cmd)}\n{''.join(err)[-3000:]}")


def run_lines(cmd: list[str], merge_stderr: bool = True):
    """Chạy lệnh, sinh từng dòng đầu ra. Hủy được cả khi lệnh lâu không in gì. Lệnh lỗi thì báo lỗi, không để nơi gọi tưởng
    là kết quả đầy đủ. Việc của giao diện (luồng ui-) không bị nút Hủy của video đang chạy làm ảnh hưởng."""
    cancellable = not threading.current_thread().name.startswith(("AnyIO", "MainThread", "ui-"))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT if merge_stderr else subprocess.DEVNULL, text=True,
                            encoding="utf-8", errors="replace")
    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(0.5):
            if cancellable and _cancel.is_set():
                proc.kill()
                return

    threading.Thread(target=watch, daemon=True, name="ffmpeg-watch").start()
    tail: list[str] = []
    try:
        for line in proc.stdout:
            tail.append(line)
            del tail[:-5]
            yield line
        rc = proc.wait()
    finally:
        stop.set()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    if cancellable and _cancel.is_set():
        raise Cancelled("Đã hủy")
    if rc != 0:
        raise RuntimeError(f"ffmpeg lỗi ({rc}): {''.join(tail)[-400:]}")


def copy_replace(src: Path, dst: Path) -> None:
    """Chép qua file tạm rồi thay. Đứt giữa chừng không để lại file hỏng, và file cũ đang có hard link (gói đăng bài đã tạo)
    giữ nguyên nội dung thay vì bị ghi đè theo. Ngoại lệ: file đang bị chương trình khác giữ thì replace_file phải ghi đè tại chỗ."""
    src, dst = Path(src), Path(dst)
    tmp = dst.with_name(dst.name + ".copying")
    try:
        shutil.copy2(src, tmp)
        replace_file(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def imread(path: str | Path):
    """cv2.imread trả về None khi đường dẫn có dấu tiếng Việt (đo được thật): đọc byte rồi giải mã."""
    import cv2

    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None      # file rỗng làm imdecode báo lỗi thay vì trả về None
    except (OSError, ValueError, cv2.error):
        return None


def probe(path: str | Path) -> dict:
    _, exe = find_ffmpeg()
    r = subprocess.run(
        [exe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe lỗi với {path}: {r.stderr}")
    info = json.loads(r.stdout)
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    w, h = (int(v["width"]), int(v["height"])) if v else (0, 0)
    # video quay dọc trên điện thoại có thể lưu rotate trong side data
    rot = 0
    if v:
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        rot = int((v.get("tags") or {}).get("rotate", rot))
    if abs(rot) in (90, 270):
        w, h = h, w
    fps = 30.0
    if v:
        try:
            n, d = str(v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/")
            fps = float(n) / float(d) or 30.0
        except (ValueError, ZeroDivisionError):
            fps = 30.0
    return {
        "duration": float(info.get("format", {}).get("duration", 0) or 0),
        "fps": fps,
        "width": w,
        "height": h,
        "has_audio": a is not None,
        "has_video": v is not None,
    }


# --------------------------------------------------------------------------- wav

def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Đọc WAV PCM16 -> float32 (mono: shape (n,), nhiều kênh: (n, ch))."""
    with wave.open(str(path), "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: chỉ hỗ trợ PCM16")
        data = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch)
    return data, sr


def write_wav(path: str | Path, data: np.ndarray, sr: int) -> None:
    data = np.clip(data, -1.0, 1.0)
    ch = 1 if data.ndim == 1 else data.shape[1]
    with wave.open(path if hasattr(path, "write") else str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((data * 32767.0).astype("<i2").tobytes())


def wav_duration(path: str | Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())
