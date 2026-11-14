"""Mô-đun AI miễn phí chạy ngay trên máy: dịch offline và vẽ ảnh offline. Không cần key, không cần mạng khi chạy.

Người dùng bấm Tải trong Cài đặt là xong: Studio566 tự tải bộ chạy (llama.cpp, stable-diffusion.cpp, bản Vulkan: chạy trên card NVIDIA,
AMD, Intel; máy không có card thì tự chạy bằng CPU) và mô hình về thư mục ai/ cạnh Studio566. Không cần cài Ollama hay Python gì thêm.

  translate  Hy-MT2 1.8B (Tencent, Apache-2.0), 1,1 GB: dịch từng câu, xem offline.py.
  image      FLUX.2 klein 4B (Black Forest Labs, Apache-2.0) + Qwen3 4B đọc lời nhắn + VAE, khoảng 5,3 GB. Nhận ảnh mẫu nhân vật.
  voices     VoxCPM2 (OpenBMB, Apache-2.0) qua CrispASR (MIT), 2,9 GB: giọng đọc 30 thứ tiếng, xem voxtts.py.

Mọi file ghim đúng phiên bản (bản phát hành GitHub, commit Hugging Face) và kiểm SHA-256 sau khi tải: file đổi hay hỏng thì không dùng.
Tải tiếp được khi rớt mạng (file .part). Mô hình dịch đã tải bằng Ollama ở bản cũ được dùng lại, không tải lại.

Bộ chạy là tiến trình con gắn vào Job Object của Windows: Studio566 tắt (kể cả bị tắt ngang) thì chúng tắt theo, không giữ card đồ họa.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from .util import ROOT, log

AI_DIR = Path(os.environ.get("ICONTENT_AI_DIR") or ROOT / "ai")
HF = (os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")
GH = "https://github.com"
UA = "Studio566-Studio"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

FILES: dict[str, dict] = {
    "llama": {"name": "Bộ chạy dịch (llama.cpp)", "engine": True, "exe": "llama-server.exe", "dir": "engines/llama-b12223",
              "url": f"{GH}/ggml-org/llama.cpp/releases/download/b12223/llama-b12223-bin-win-vulkan-x64.zip",
              "size": 37847217, "sha256": "e46e6a4654091e423552fb1a80efe803688e340a34011751fe1d171d5347f843"},
    "sd": {"name": "Bộ chạy vẽ ảnh (stable-diffusion.cpp)", "engine": True, "exe": "sd-cli.exe", "dir": "engines/sd-fc350be",
           "url": f"{GH}/leejet/stable-diffusion.cpp/releases/download/master-1068-fc350be/sd-master-fc350be-bin-win-vulkan-x64.zip",
           "size": 29995988, "sha256": "b229d9a21858ba91975d061ccfe37fa690254a423bcf77b39e72a1d8435a8b4a"},
    "hymt": {"name": "Mô hình dịch Hy-MT2 1.8B", "repo": "tencent/Hy-MT2-1.8B-GGUF", "rev": "a0c709d9fac510f2c807aa3af52872340dc37a4a",
             "file": "Hy-MT2-1.8B-Q4_K_M.gguf", "size": 1133080448,
             "sha256": "dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699"},
    "klein": {"name": "Mô hình vẽ FLUX.2 klein 4B", "repo": "leejet/FLUX.2-klein-4B-GGUF", "rev": "3b1f5a9dc3abb32238b053aeb3d823c30afdacbd",
              "file": "flux-2-klein-4b-Q4_0.gguf", "size": 2460378560,
              "sha256": "d1023499ef3f2f82ff7c50e6778495195c1b6cc34835741778868428111f9ff4"},
    "qwen3_4b": {"name": "Bộ đọc lời nhắn Qwen3 4B", "repo": "unsloth/Qwen3-4B-GGUF", "rev": "22c9fc8a8c7700b76a1789366280a6a5a1ad1120",
                 "file": "Qwen3-4B-Q4_K_M.gguf", "size": 2497281312,
                 "sha256": "f6f851777709861056efcdad3af01da38b31223a3ba26e61a4f8bf3a2195813a"},
    "flux2_vae": {"name": "Bộ giải mã ảnh FLUX.2", "repo": "Comfy-Org/Flux-2-Klein-4B", "rev": "5b3abca5c0dc1ecd4eaf3340868d09063fc1c965",
                  "file": "split_files/vae/flux2-vae.safetensors", "size": 336211292,
                  "sha256": "868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3"},
    "crisp": {"name": "Bộ chạy giọng đọc (CrispASR)", "engine": True, "exe": "crispasr.exe", "dir": "engines/crispasr-0.8.53",
              "url": f"{GH}/CrispStrobe/CrispASR/releases/download/v0.8.53/crispasr-windows-x86_64-vulkan.zip",
              "size": 37199634, "sha256": "25b9a1e450f0831a887f5af19e51ad190514635e888e348f9039f15d08f5f57e"},
    "voxcpm2": {"name": "Mô hình giọng đọc VoxCPM2 (30 thứ tiếng)", "repo": "cstr/voxcpm2-GGUF", "rev": "fb5f9e6c592f86638e474b7076ac684e0491d854",
                "file": "voxcpm2-q8_0.gguf", "size": 2827049792,
                "sha256": "142f29c4dff1c0ad3f71d9353a03f7cbf08080bee3ab73c577c0219e4094fc4b"},
}

if os.name != "nt":
    import platform as _plat
    _is_arm = _plat.machine().lower() in ("arm64", "aarch64")
    FILES["llama"] = (
        {"name": "Bộ chạy dịch (llama.cpp Metal)", "engine": True, "exe": "llama-server", "dir": "engines/llama-b12223-mac-arm64",
         "url": f"{GH}/ggml-org/llama.cpp/releases/download/b12223/llama-b12223-bin-macos-arm64.tar.gz",
         "size": 16712197, "sha256": "66c6a8849ab5155898bb2d56e39d34b08f91a1019560a52510fbfd2ef599334e"}
        if _is_arm else
        {"name": "Bộ chạy dịch (llama.cpp macOS)", "engine": True, "exe": "llama-server", "dir": "engines/llama-b12223-mac-x64",
         "url": f"{GH}/ggml-org/llama.cpp/releases/download/b12223/llama-b12223-bin-macos-x64.tar.gz",
         "size": 12456535, "sha256": "a92aaa2a77a12dece931b784b9fe980cd89ca415618d5348935c5da20838394a"}
    )
    FILES["sd"] = {
        "name": "Bộ chạy vẽ ảnh (stable-diffusion.cpp)", "engine": True, "exe": "sd-cli", "dir": "engines/sd-fc350be-mac",
        "url": f"{GH}/leejet/stable-diffusion.cpp/releases/download/master-1068-fc350be/sd-master-fc350be-bin-Darwin-macOS-26.7.2-arm64.zip",
        "size": 38019952, "sha256": "fcf19233e70fb074fa337d19e47ad092ace43a37ab0b630dadf162ba00ca5b57",
    }
    FILES["crisp"] = (
        {"name": "Bộ chạy giọng đọc (CrispASR Metal)", "engine": True, "exe": "crispasr", "dir": "engines/crispasr-0.8.53-mac-arm64",
         "url": f"{GH}/CrispStrobe/CrispASR/releases/download/v0.8.53/crispasr-macos-arm64.tar.gz",
         "size": 18671735, "sha256": "741aa7f3dd4cd996248f590421987df0712fc964a5e129d6a69960828e119e8b"}
        if _is_arm else
        {"name": "Bộ chạy giọng đọc (CrispASR macOS)", "engine": True, "exe": "crispasr", "dir": "engines/crispasr-0.8.53-mac-x64",
         "url": f"{GH}/CrispStrobe/CrispASR/releases/download/v0.8.53/crispasr-macos-x86_64.tar.gz",
         "size": 19270474, "sha256": "31d9ffa491d7a7911756fd24a716f65bfa1ca894e9e0c53e2bf61ff0170c1e0a"}
    )

PACKS: dict[str, dict] = {
    "translate": {
        "name": "Dịch offline", "files": ["llama", "hymt"], "icon": "globe",
        "desc": "Dịch lời thoại tiếng Trung ngay trên máy: không cần key, không cần mạng, câu thoại không gửi đi đâu. "
                "Gemini quá tải hay Google chặn thì Studio566 tự dịch tiếp bằng cách này.",
        "limits": "Dịch từng câu nên chưa bằng AI lớn: chưa có xưng hô theo ngữ cảnh, tên món và tiếng lóng có thể sai, "
                  "không gợi ý tiêu đề. Nên đọc lại bản dịch trong Studio trước khi đăng.",
    },
    "image": {
        "name": "Vẽ ảnh offline", "files": ["sd", "klein", "qwen3_4b", "flux2_vae"], "icon": "image",
        "desc": "Vẽ ảnh minh họa cho Kể chuyện và Quy trình ngay trên máy, không giới hạn số ảnh, không tốn tiền. "
                "Nhận ảnh mẫu để giữ nhân vật giống nhau giữa các cảnh.",
        "limits": "Đo trên card GTX 1660 Super 6 GB: khoảng 35 giây mỗi ảnh dọc của video, có ảnh mẫu nhân vật khoảng 1 phút. "
                  "Nên có RAM từ 16 GB (máy 8 GB thì đóng bớt phần mềm khi vẽ). Không có card rời thì vẫn vẽ được bằng CPU nhưng chậm hơn nhiều. "
                  "Chữ viết trên ảnh (biển hiệu, tiêu đề) hay sai: thêm chữ bằng Thumbnail hoặc Trình dựng.",
    },
    "voices": {
        "name": "Giọng đọc nhiều thứ tiếng", "files": ["crisp", "voxcpm2"], "icon": "mic",
        "desc": "Lồng tiếng video cho thị trường nước ngoài ngay trên máy: Anh, Indonesia, Thái, Philippines, Malaysia, Tây Ban Nha, "
                "Bồ Đào Nha, Nhật, Hàn, Hindi, Ả Rập, Pháp, Đức, Nga... Mỗi thứ tiếng 4 giọng nam, nữ. Không cần mạng, không bị chặn.",
        "limits": "Đo trên card GTX 1660 Super 6 GB: mỗi giây lời đọc mất khoảng 1,5-2 giây, video 90 câu khoảng 4-5 phút. "
                  "Máy không có card rời đọc chậm hơn nhiều. Tiếng Việt vẫn dùng VieNeu (hay hơn cho tiếng Việt). "
                  "File âm thanh có dấu nước AI không nghe thấy; khi đăng nên bật nhãn nội dung AI của nền tảng.",
    },
}

# ------------------------------------------------------------------ đường dẫn, trạng thái


def path_of(fid: str) -> Path:
    f = FILES[fid]
    return AI_DIR / f["dir"] if f.get("engine") else AI_DIR / "models" / Path(f["file"]).name


def exe_of(fid: str) -> Path:
    return path_of(fid) / FILES[fid]["exe"]


def _marker(fid: str) -> Path:
    p = path_of(fid)
    return p / ".verified" if FILES[fid].get("engine") else p.with_name(p.name + ".verified")


def installed(fid: str) -> bool:
    """Đã tải xong và đã kiểm SHA-256 (ghi dấu sau khi kiểm, không băm lại 2,5 GB mỗi lần hỏi)."""
    f = FILES[fid]
    try:
        if _marker(fid).read_text(encoding="ascii").strip() != f["sha256"]:
            return False
    except OSError:
        return False
    if f.get("engine"):
        return exe_of(fid).is_file()
    p = path_of(fid)
    return p.is_file() and p.stat().st_size == f["size"]


def pack_ready(pid: str) -> bool:
    return all(installed(f) for f in PACKS[pid]["files"])


def _need(pid: str) -> int:
    return sum(FILES[f]["size"] for f in PACKS[pid]["files"] if not installed(f) and not _ollama_blob(f))


def free_bytes() -> int:
    p = AI_DIR
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return 0


def gb(n: float) -> str:
    return f"{n / 1e9:.1f}".replace(".", ",") + " GB"


# ------------------------------------------------------------------ tải về: tiếp tục được, kiểm SHA-256, hủy được

class Task:
    """Một lượt tải một gói, cho giao diện hỏi lại tiến độ."""

    def __init__(self, pid: str):
        self.pid = pid
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.running = True
        self.data = {"step": "start", "message": "Đang chuẩn bị", "progress": None, "done_mb": 0, "total_mb": 0,
                     "speed": 0.0, "eta": None, "error": "", "done": False}

    def set(self, **kw) -> None:
        with self.lock:
            self.data.update(kw)

    def view(self) -> dict:
        with self.lock:
            return dict(self.data, running=self.running)


TASKS: dict[str, Task] = {}
_tasks_lock = threading.Lock()


class DownloadError(RuntimeError):
    pass


def _url(fid: str) -> str:
    f = FILES[fid]
    return f["url"] if f.get("url") else f"{HF}/{f['repo']}/resolve/{f['rev']}/{f['file']}"


def _ollama_blob(fid: str) -> Path | None:
    """Mô hình dịch Ollama đã tải ở bản cũ là đúng file này (cùng SHA-256): dùng lại, không tải 1,1 GB nữa."""
    f = FILES[fid]
    if f.get("engine"):
        return None
    root = Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")
    p = root / "blobs" / f"sha256-{f['sha256']}"
    try:
        return p if p.is_file() and p.stat().st_size == f["size"] else None
    except OSError:
        return None


def _sha256_file(p: Path, cancel: threading.Event | None = None) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(4 << 20), b""):
            if cancel is not None and cancel.is_set():
                raise InterruptedError
            h.update(chunk)
    return h.hexdigest()


def _wait(sec: float, cancel: threading.Event) -> None:
    if cancel.wait(sec):
        raise InterruptedError


def fetch(url: str, part: Path, size: int, sha256: str, cancel: threading.Event, on_have=None, retries: int = 8) -> None:
    """Tải url vào part (tiếp tục từ chỗ đã có), băm trong lúc tải. Sai SHA-256 thì xóa và báo lỗi."""
    part.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    have = part.stat().st_size if part.exists() else 0
    if have > size:
        part.unlink()
        have = 0
    if have:
        with open(part, "rb") as fh:
            for chunk in iter(lambda: fh.read(4 << 20), b""):
                if cancel.is_set():
                    raise InterruptedError
                h.update(chunk)
    if on_have:
        on_have(have)
    fails = 0
    while have < size:
        headers = {"User-Agent": UA}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:      # noqa: S310 — địa chỉ ghim sẵn
                if have and r.status != 206:      # máy chủ không cho tải tiếp: tải lại từ đầu
                    have, h = 0, hashlib.sha256()
                with open(part, "ab" if have else "wb") as out:
                    while True:
                        if cancel.is_set():
                            raise InterruptedError
                        buf = r.read(1 << 20)
                        if not buf:
                            break
                        out.write(buf)
                        h.update(buf)
                        have += len(buf)
                        fails = 0
                        if on_have:
                            on_have(have)
            if have < size:
                raise ConnectionError("kết nối đóng sớm")
        except urllib.error.HTTPError as e:
            if e.code == 416:      # đã đủ byte
                break
            if e.code in (401, 403, 404, 410):
                raise DownloadError(f"Máy chủ báo lỗi {e.code} khi tải {url.rsplit('/', 1)[-1]}. Cập nhật Studio566 lên bản mới rồi thử lại.") from e
            fails += 1
            if fails > retries:
                raise DownloadError(f"Máy chủ tải đang lỗi ({e.code}). Thử lại sau ít phút: phần đã tải được giữ lại.") from e
            _wait(min(60, 3 * 2 ** fails), cancel)
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError, socket.timeout, OSError) as e:
            if isinstance(e, InterruptedError):
                raise
            fails += 1
            if fails > retries:
                raise DownloadError(f"Mất kết nối khi tải ({str(e)[:120]}). Kiểm tra mạng rồi bấm Tải tiếp: phần đã tải được giữ lại.") from e
            _wait(min(60, 3 * 2 ** fails), cancel)
    if have != size or h.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise DownloadError("File tải về bị hỏng (sai mã kiểm tra). Bấm Tải lại để tải lại từ đầu.")


def _place(fid: str, part: Path) -> None:
    """File đã kiểm xong -> đặt vào chỗ dùng. Bộ chạy thì giải nén ra thư mục riêng rồi mới đổi tên (không để lại thư mục dở)."""
    import tarfile
    f = FILES[fid]
    dest = path_of(fid)
    if f.get("engine"):
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        if zipfile.is_zipfile(part):
            with zipfile.ZipFile(part) as z:
                for m in z.infolist():      # không cho đường dẫn thoát ra ngoài thư mục
                    name = Path(m.filename)
                    if name.is_absolute() or ".." in name.parts:
                        raise DownloadError("Gói bộ chạy có đường dẫn lạ, không giải nén.")
                z.extractall(tmp)
        else:
            tmp.mkdir(parents=True, exist_ok=True)
            with tarfile.open(part, "r:*") as tf:
                for m in tf.getmembers():
                    name = Path(m.name)
                    if name.is_absolute() or ".." in name.parts:
                        raise DownloadError("Gói bộ chạy có đường dẫn lạ, không giải nén.")
                tf.extractall(tmp)
        inner = [p for p in tmp.iterdir()]
        if len(inner) == 1 and inner[0].is_dir() and not (tmp / f["exe"]).exists():
            tmp = inner[0]
        if not (tmp / f["exe"]).is_file() and (tmp / "bin" / f["exe"]).is_file():
            tmp = tmp / "bin"
        if not (tmp / f["exe"]).is_file():
            raise DownloadError(f"Gói bộ chạy thiếu {f['exe']}.")
        if os.name != "nt":
            try:
                (tmp / f["exe"]).chmod(0o755)
            except OSError:
                pass
        shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, dest)
        shutil.rmtree(dest.with_name(dest.name + ".tmp"), ignore_errors=True)
        part.unlink(missing_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(part, dest)
    _marker(fid).write_text(f["sha256"], encoding="ascii")


def _from_ollama(fid: str, cancel: threading.Event) -> bool:
    blob = _ollama_blob(fid)
    if not blob:
        return False
    dest = path_of(fid)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.unlink(missing_ok=True)
    try:
        os.link(blob, tmp)      # cùng ổ đĩa: không tốn thêm chỗ
    except OSError:
        shutil.copyfile(blob, tmp)
    if _sha256_file(tmp, cancel) != FILES[fid]["sha256"]:
        tmp.unlink(missing_ok=True)
        return False
    os.replace(tmp, dest)
    _marker(fid).write_text(FILES[fid]["sha256"], encoding="ascii")
    log("ai", f"Dùng lại {FILES[fid]['name']} đã tải bằng Ollama")
    return True


def _download_pack(t: Task) -> None:
    pack = PACKS[t.pid]
    todo = [f for f in pack["files"] if not installed(f)]
    for fid in list(todo):
        if _from_ollama(fid, t.cancel):
            todo.remove(fid)
    total = sum(FILES[f]["size"] for f in todo)
    if not todo:
        t.set(step="done", done=True, progress=1.0, message="Đã có đủ trên máy")
        return
    free = free_bytes()
    if free and free < total * 1.05 + 500e6:
        raise DownloadError(f"Ổ đĩa chứa Studio566 chỉ còn trống {gb(free)}, gói này cần {gb(total)}. Dọn bớt (Thư viện > Dọn file tạm) rồi thử lại.")
    t.set(total_mb=round(total / 1e6))
    base = 0
    speed_ref = [time.time(), 0, 0.0]      # mốc thời gian, số byte ở mốc, tốc độ đã làm mượt

    def on_have(have: int) -> None:
        now = time.time()
        done = base + have
        dt = now - speed_ref[0]
        if dt >= 1.0:
            inst = max(0.0, (done - speed_ref[1]) / dt)
            speed_ref[2] = inst if not speed_ref[2] else 0.7 * speed_ref[2] + 0.3 * inst
            speed_ref[0], speed_ref[1] = now, done
        sp = speed_ref[2]
        eta = (total - done) / sp if sp > 1000 else None
        t.set(progress=done / total if total else None, done_mb=round(done / 1e6), speed=round(sp / 1e6, 2),
              eta=round(eta) if eta is not None else None)

    for i, fid in enumerate(todo, 1):
        f = FILES[fid]
        t.set(step="download", message=f"Đang tải {f['name']} ({i}/{len(todo)})")
        log("ai", f"Tải {f['name']}: {_url(fid)}")
        part = (AI_DIR / "engines" / (Path(f["dir"]).name + ".zip.part")) if f.get("engine") else path_of(fid).with_name(path_of(fid).name + ".part")
        speed_ref[0], speed_ref[1] = time.time(), base + (part.stat().st_size if part.exists() else 0)
        fetch(_url(fid), part, f["size"], f["sha256"], t.cancel, on_have)
        t.set(step="verify", message=f"Đang cài {f['name']}")
        _place(fid, part)
        base += f["size"]
    t.set(step="done", done=True, progress=1.0, message="Đã tải xong", eta=None)
    log("ai", f"Đã tải xong {pack['name']}")


def _run_task(t: Task, after=None) -> None:
    try:
        _download_pack(t)
        if after:
            t.set(step="test", message="Đang chạy thử")
            msg = after()
            t.set(step="done", message=msg or "Sẵn sàng")
    except InterruptedError:
        t.set(step="", message="Đã dừng tải. Phần đã tải được giữ lại, bấm Tải tiếp để tải nốt.", progress=None, eta=None)
    except Exception as e:      # noqa: BLE001 — báo lên giao diện, không làm sập luồng
        log("ai", f"Tải {t.pid} lỗi: {e}")
        t.set(error=str(e)[:400], progress=None, eta=None)
    finally:
        t.running = False


def begin(pid: str, after=None) -> bool:
    """Bắt đầu tải gói ở luồng nền. False nếu gói đó đang tải."""
    if pid not in PACKS:
        raise KeyError(pid)
    with _tasks_lock:
        cur = TASKS.get(pid)
        if cur and cur.running:
            return False
        t = TASKS[pid] = Task(pid)
    threading.Thread(target=_run_task, args=(t, after), daemon=True, name=f"ui-ai-{pid}").start()
    return True


def cancel(pid: str) -> None:
    t = TASKS.get(pid)
    if t and t.running:
        t.cancel.set()


def remove(pid: str) -> int:
    """Xóa file của gói (file dùng chung với gói khác còn đủ thì giữ lại). Trả về số byte đã xóa."""
    t = TASKS.get(pid)
    if t and t.running:
        raise RuntimeError("Gói đang tải, bấm Dừng trước rồi xóa")
    keep = {f for q in PACKS if q != pid and pack_ready(q) for f in PACKS[q]["files"]}
    if pid == "translate":
        LLAMA.stop()
    if pid == "voices":
        from .voxtts import SERVER
        SERVER.stop()
    freed = 0
    for fid in PACKS[pid]["files"]:
        if fid in keep:
            continue
        p = path_of(fid)
        part = p.with_name(p.name + ".part")
        for x in (p, part, _marker(fid)):
            try:
                if x.is_dir():
                    freed += sum(y.stat().st_size for y in x.rglob("*") if y.is_file())
                    shutil.rmtree(x)
                elif x.exists():
                    freed += x.stat().st_size
                    x.unlink()
            except OSError as e:
                raise RuntimeError(f"Không xóa được {x.name}: file đang được dùng. Tắt Studio566, mở lại rồi xóa.") from e
    with _tasks_lock:
        TASKS.pop(pid, None)
    return freed


def status() -> dict:
    out = []
    for pid, p in PACKS.items():
        files = [{"id": f, "name": FILES[f]["name"], "mb": round(FILES[f]["size"] / 1e6), "ok": installed(f)} for f in p["files"]]
        t = TASKS.get(pid)
        out.append({"id": pid, "name": p["name"], "desc": p["desc"], "limits": p["limits"], "icon": p["icon"],
                    "ready": pack_ready(pid), "total_mb": round(sum(FILES[f]["size"] for f in p["files"]) / 1e6),
                    "need_mb": round(_need(pid) / 1e6), "reuse_ollama": any(_ollama_blob(f) and not installed(f) for f in p["files"]),
                    "files": files, "task": t.view() if t else None})
    return {"packs": out, "free_mb": round(free_bytes() / 1e6), "dir": str(AI_DIR), "devices": devices(quick=True)}


# ------------------------------------------------------------------ tiến trình con: chết theo Studio566

_JOB = None


def _job():
    """Job Object 'tắt hết khi đóng': Studio566 bị tắt ngang thì Windows tự tắt bộ chạy, không để nó giữ card đồ họa."""
    global _JOB
    if os.name != "nt":
        return None
    if _JOB is None:
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class Ext(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        h = k32.CreateJobObjectW(None, None)
        if not h:
            return None
        info = Ext()
        info.BasicLimitInformation.LimitFlags = 0x2000      # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(h, 9, ctypes.byref(info), ctypes.sizeof(info)):
            return None
        _JOB = (k32, h)
    return _JOB


def adopt(proc: subprocess.Popen) -> None:
    j = _job()
    if j is None:
        return
    k32, h = j
    try:
        k32.AssignProcessToJobObject(h, int(proc._handle))      # noqa: SLF001 — handle của Popen trên Windows
    except Exception:      # noqa: BLE001 — không gắn được thì vẫn chạy, chỉ là không tự tắt theo
        pass


def short_path(p: Path) -> str:
    """Bộ chạy đọc tham số dòng lệnh theo bảng mã ANSI: đường dẫn có dấu tiếng Việt thì đổi sang tên ngắn 8.3 của Windows."""
    s = str(p)
    if os.name != "nt" or s.isascii():
        return s
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(s, buf, 1024)
    return buf.value if 0 < n < 1024 and buf.value.isascii() else s


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _tail(p: Path, n: int = 12) -> str:
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(x for x in lines[-n:] if x.strip())


# ------------------------------------------------------------------ card đồ họa

_dev_cache: dict = {}
_DEV_RE = re.compile(r"^\s*(\w+?\d+):\s*(.+?)\s*\((\d+) MiB,\s*(\d+) MiB free\)", re.M)


def parse_devices(text: str) -> list[dict]:
    return [{"id": m[1], "name": m[2], "vram_mb": int(m[3]), "free_mb": int(m[4])} for m in _DEV_RE.finditer(text or "")]


def devices(quick: bool = False) -> list[dict] | None:
    """Card đồ họa bộ chạy thấy được (Vulkan). None: chưa biết (chưa tải bộ chạy). [] : không có card, sẽ chạy bằng CPU."""
    if "list" in _dev_cache:
        return _dev_cache["list"]
    if quick or not installed("llama"):
        return None
    try:
        r = subprocess.run([str(exe_of("llama")), "--list-devices"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=60, cwd=path_of("llama"), creationflags=NO_WINDOW)
        _dev_cache["list"] = [d for d in parse_devices(r.stdout + "\n" + r.stderr) if not d["id"].lower().startswith("cpu")]
    except (OSError, subprocess.SubprocessError):
        return None
    return _dev_cache["list"]


# ------------------------------------------------------------------ dịch: llama-server chạy khi cần, rảnh thì tắt

class LlamaServer:
    IDLE = 120      # giây không dùng thì tắt: trả card đồ họa cho nhận dạng giọng, đọc lời, vẽ ảnh

    def __init__(self):
        self.lock = threading.RLock()
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.model = ""
        self.last = 0.0
        self.adds_bos = False
        self._watch: threading.Thread | None = None

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _get(self, path: str, timeout: float = 3) -> tuple[int, dict]:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        try:
            with _local.open(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, {}

    def post(self, path: str, body: dict, timeout: float = 300) -> dict:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"})
        with _local.open(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")

    def ensure(self, model: Path, ctx: int = 4096) -> None:
        with self.lock:
            self.last = time.time()
            if self.running() and self.model == str(model):
                return
            self.stop()
            if not installed("llama"):
                raise RuntimeError("Chưa tải Dịch offline. Vào Cài đặt, mục Mô-đun AI miễn phí, bấm Tải.")
            logs = AI_DIR / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            self.port = _free_port()
            # không ép số lớp lên card (-ngl): mặc định 'auto' + --fit tự chia vừa bộ nhớ card, card nhỏ không bị tràn
            cmd = [str(exe_of("llama")), "-m", short_path(model), "--host", "127.0.0.1", "--port", str(self.port),
                   "-c", str(ctx), "-np", "1", "--no-webui"]
            with open(logs / "llama.log", "w", encoding="utf-8") as lf:
                self.proc = subprocess.Popen(cmd, cwd=path_of("llama"), stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT,
                                             creationflags=NO_WINDOW)
            adopt(self.proc)
            self.model = str(model)
            end = time.time() + 180
            while time.time() < end:
                if self.proc.poll() is not None:
                    tail = _tail(logs / "llama.log")
                    self.proc = None
                    raise RuntimeError("Bộ chạy dịch offline không khởi động được: " + (tail[-400:] or "không rõ lý do"))
                try:
                    code, _ = self._get("/health", timeout=2)
                    if code == 200:
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(0.3)
            else:
                self.stop()
                raise RuntimeError("Bộ chạy dịch offline khởi động quá lâu (hơn 3 phút). Thử lại, hoặc khởi động lại máy.")
            try:      # máy chủ tự thêm token mở đầu thì mẫu lời nhắn không được thêm lần nữa
                self.adds_bos = bool(self.post("/tokenize", {"content": "", "add_special": True}, timeout=10).get("tokens"))
            except (OSError, ValueError):
                self.adds_bos = False
            log("ai", f"Bật bộ chạy dịch offline (cổng {self.port})")
            if self._watch is None or not self._watch.is_alive():
                self._watch = threading.Thread(target=self._idle_loop, daemon=True, name="ui-ai-idle")
                self._watch.start()

    def _idle_loop(self) -> None:
        while True:
            time.sleep(10)
            with self.lock:
                if not self.running():
                    return
                if time.time() - self.last > self.IDLE:
                    log("ai", "Tắt bộ chạy dịch offline (đang rảnh)")
                    self.stop()
                    return

    def stop(self) -> None:
        with self.lock:
            p, self.proc = self.proc, None
            self.model = ""
            if p is not None and p.poll() is None:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()

    def complete(self, prompt: str, max_tokens: int = 256, temperature: float = 0.3, top_p: float = 0.6, top_k: int = 20,
                 repeat_penalty: float = 1.05, timeout: float = 300) -> str:
        with self.lock:
            self.last = time.time()
        body = {"prompt": prompt, "n_predict": max_tokens, "temperature": temperature, "top_p": top_p, "top_k": top_k,
                "repeat_penalty": repeat_penalty, "stream": False, "cache_prompt": False}
        out = self.post("/completion", body, timeout=timeout)
        with self.lock:
            self.last = time.time()
        return str(out.get("content") or "").strip()


# máy chủ chạy ngay trên máy này: không đi qua proxy hệ thống (VPN, proxy công ty), nếu không sẽ tưởng bộ chạy chưa bật
_local = urllib.request.build_opener(urllib.request.ProxyHandler({}))
LLAMA = LlamaServer()


def translate_model() -> Path:
    return path_of("hymt")


# ------------------------------------------------------------------ viết kịch bản trên máy: Qwen3 4B của gói Vẽ ảnh offline
def writer_ready() -> bool:
    """Viết kịch bản không cần key: bộ chạy llama (gói Dịch offline) + Qwen3 4B (gói Vẽ ảnh offline, vốn là bộ đọc lời nhắn của FLUX)."""
    return installed("llama") and path_of("qwen3_4b").is_file()


def chat_json(system: str, user: str, schema: dict, max_tokens: int = 6000, temperature: float = 0.7) -> dict:
    """Trả lời JSON đúng khuôn (llama-server ép theo schema). Đo 11/2026 trên GTX 1660 Super: kịch bản 5 cảnh khoảng 11 giây,
    bật bộ chạy lần đầu 17 giây. Tắt suy nghĩ (Qwen3 thinking): nhanh hơn nhiều, kịch bản ngắn không cần."""
    if not writer_ready():
        raise RuntimeError("Chưa có AI viết trên máy: cần tải cả Dịch offline và Vẽ ảnh offline (Cài đặt, mục Mô-đun AI miễn phí).")
    LLAMA.ensure(path_of("qwen3_4b"), ctx=8192)
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}},
            "chat_template_kwargs": {"enable_thinking": False}, "temperature": temperature, "top_p": 0.8, "top_k": 20, "max_tokens": max_tokens}
    with LLAMA.lock:
        LLAMA.last = time.time()
    r = LLAMA.post("/v1/chat/completions", body, timeout=900)
    with LLAMA.lock:
        LLAMA.last = time.time()
    txt = str(((r.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    try:
        return json.loads(txt)
    except ValueError:
        raise RuntimeError("AI trên máy trả lời không đúng khuôn, thử lại") from None


class LocalWriter:
    """Cùng giao diện json_call với các bộ dịch AI (translate.py), để story.py dùng như AI có key."""
    name = "AI trên máy (Qwen3 4B)"

    def json_call(self, system: str, user: str, schema: dict, max_tokens: int = 6000) -> dict:
        user += ("\n\nIMPORTANT: every field named prompt, broll and description must be written in English. "
                 "Every character named in a scene must be in the characters list.")
        return chat_json(system, user, schema, max_tokens=min(max_tokens, 8000))


# ------------------------------------------------------------------ vẽ ảnh: sd-cli mỗi ảnh một lượt

IMAGE_SIZES = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (1024, 1024), "4:5": (896, 1120), "3:4": (864, 1152),
               "4:3": (1152, 864), "3:2": (1216, 816), "2:3": (816, 1216)}
MAX_REFS = 2
_gpu = threading.Lock()      # mỗi lúc chỉ vẽ một ảnh: hai ảnh cùng lúc tràn bộ nhớ card
_STEP_RE = re.compile(r"(\d+)/(\d+)")


def image_ready() -> bool:
    return pack_ready("image")


def _sd_friendly(tail: str) -> str:
    low = tail.lower()
    if any(w in low for w in ("out of memory", "outofdevicememory", "erroroutofdevicememory", "failed to allocate", "bad_alloc")):
        return ("Không đủ bộ nhớ để vẽ (card đồ họa hoặc RAM). Đóng bớt phần mềm nặng (game, trình duyệt nhiều tab), "
                "đợi video đang dựng xong rồi vẽ lại.")
    if "vk_error_device_lost" in low or "device lost" in low:
        return "Card đồ họa bị ngắt giữa chừng (driver lỗi hoặc quá nóng). Cập nhật driver card đồ họa rồi vẽ lại."
    return "Vẽ ảnh offline lỗi: " + (tail[-300:] or "bộ chạy dừng không rõ lý do")


def draw(prompt: str, refs: list[Path] | None = None, aspect: str = "9:16", seed: int | None = None, steps: int = 4,
         size: tuple[int, int] | None = None, on_progress=None, cancel: threading.Event | None = None, timeout: float = 1800) -> bytes:
    """Vẽ một ảnh bằng FLUX.2 klein ngay trên máy -> bytes PNG. refs: ảnh mẫu nhân vật (tối đa MAX_REFS)."""
    if not image_ready():
        raise RuntimeError("Chưa tải Vẽ ảnh offline. Vào Cài đặt, mục Mô-đun AI miễn phí, bấm Tải.")
    w, h = size or IMAGE_SIZES.get(aspect, IMAGE_SIZES["9:16"])
    LLAMA.stop()      # trả card đồ họa cho bộ vẽ
    logs = AI_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    tmp = AI_DIR / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    stem = tmp / f"draw_{os.getpid()}_{threading.get_ident()}_{int(time.time() * 1000)}"
    out = stem.with_suffix(".png")
    pfile = stem.with_suffix(".txt")      # lời nhắn qua file UTF-8: dòng lệnh của bộ chạy đọc theo bảng mã ANSI, mất dấu và chữ Hán
    pfile.write_text(prompt, encoding="utf-8")
    cmd = [str(exe_of("sd")), "--diffusion-model", short_path(path_of("klein")), "--llm", short_path(path_of("qwen3_4b")),
           "--vae", short_path(path_of("flux2_vae")), "--prompt-file", short_path(pfile), "--cfg-scale", "1.0", "--steps", str(steps),
           # không ép --offload-to-cpu: auto-fit tự xếp theo bộ nhớ card còn trống (đo trên GTX 1660 6 GB: 720x1280 hai cách đều 35 giây)
           "--sampling-method", "euler", "-W", str(w), "-H", str(h), "-o", short_path(out),
           "-s", str(seed if seed is not None else int.from_bytes(os.urandom(3), "big"))]
    for r in (refs or [])[:MAX_REFS]:
        cmd += ["-r", short_path(Path(r))]
    tail: list[str] = []
    with _gpu:
        t0 = time.time()
        proc = subprocess.Popen(cmd, cwd=path_of("sd"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        adopt(proc)
        killer = threading.Event()

        def guard():      # hủy hoặc quá giờ thì tắt bộ vẽ
            while proc.poll() is None:
                if (cancel is not None and cancel.is_set()) or time.time() - t0 > timeout:
                    killer.set()
                    proc.kill()
                    return
                time.sleep(0.3)

        threading.Thread(target=guard, daemon=True, name="ui-ai-draw-guard").start()
        sampling = False
        try:
            for line in proc.stdout:
                s = line.strip()
                if not s:
                    continue
                tail.append(s)
                del tail[:-40]
                low = s.lower()
                if "sampling" in low or "denois" in low:
                    sampling = True
                m = _STEP_RE.search(s) if sampling else None
                if m and on_progress and int(m[2]) == steps:
                    on_progress(min(1.0, int(m[1]) / steps))
        finally:
            proc.wait()
            pfile.unlink(missing_ok=True)
        (logs / "sd.log").write_text("\n".join([" ".join(cmd[:1] + ["..."])] + tail), encoding="utf-8")
        if killer.is_set():
            out.unlink(missing_ok=True)
            if cancel is not None and cancel.is_set():
                raise InterruptedError
            raise RuntimeError(f"Vẽ ảnh quá lâu (hơn {int(timeout // 60)} phút) nên đã dừng. Máy không có card đồ họa rời thì vẽ rất chậm.")
        if proc.returncode != 0 or not out.is_file():
            out.unlink(missing_ok=True)
            raise RuntimeError(_sd_friendly("\n".join(tail)))
        log("ai", f"Vẽ ảnh offline {w}x{h}: {time.time() - t0:.0f} giây")
    try:
        return out.read_bytes()
    finally:
        out.unlink(missing_ok=True)


# ------------------------------------------------------------------ lời nhắn tiếng Việt -> tiếng Anh cho bộ vẽ

_VI = re.compile(r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", re.I)


def has_vietnamese(text: str) -> bool:
    return bool(_VI.search(text or ""))


def to_english(text: str) -> str:
    """Mô hình vẽ hiểu tiếng Anh tốt nhất. Có Dịch offline thì dịch phần tiếng Việt sang tiếng Anh; không có thì để nguyên."""
    if not has_vietnamese(text) or not pack_ready("translate"):
        return text
    from . import offline
    try:
        out = offline.translate_text(text, "en")
    except Exception as e:      # noqa: BLE001 — dịch lời nhắn hỏng thì vẫn vẽ bằng lời gốc
        log("ai", f"Không dịch được lời nhắn sang tiếng Anh: {e}")
        return text
    return out if out and not has_vietnamese(out) else text
