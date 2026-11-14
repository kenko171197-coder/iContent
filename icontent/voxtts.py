"""Giọng đọc nhiều thứ tiếng chạy trên máy: VoxCPM2 (OpenBMB, Apache-2.0) qua máy chủ CrispASR (MIT, bản Vulkan).

Gói "voices" của Mô-đun AI miễn phí (localai.py). 30 thứ tiếng; Studio566 có sẵn thư viện giọng cho các thị trường trong langs.py.

Giữ giọng: chỉ tả giọng bằng lời thì mỗi câu một người khác (đo CAM++ giữa các câu 0,3-0,8). Vì vậy mỗi giọng có một đoạn mẫu
(icontent/data/voices/<id>.mp3 + .txt, tạo sẵn bằng VoxCPM2 voice design, đã cho Whisper nghe lại đúng lời), mọi câu đều bắt chước
đúng đoạn mẫu đó: độ giống giữa các câu 0,68-0,93. Đoạn mẫu là giọng tổng hợp, không phải người thật.

Gắn nhãn AI: CrispASR luôn gắn dấu nước AI không nghe thấy và chứng chỉ C2PA vào file. Vì đoạn mẫu là giọng tổng hợp, Studio566
xin bỏ câu thông báo đọc thành tiếng ở đầu mỗi câu (spoken_disclaimer) và nhận trách nhiệm ghi nhãn: gói đăng bài nhắc khách
bật nhãn "nội dung AI" khi đăng (TikTok, YouTube đều yêu cầu).

Đo trên GTX 1660 Super 6 GB (Vulkan, Q8_0): mỗi giây âm thanh mất khoảng 1,5-2 giây; độ rõ lời Whisper nghe lại sai 0-6%.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .util import ROOT, check_cancel, log

DATA = ROOT / "icontent" / "data" / "voices"
IDLE = 180      # giây không đọc thì tắt máy chủ: trả card đồ họa cho việc khác
CONSENT = "Synthetic voice made with VoxCPM2 voice design for Studio566, not a real person"
MARKING = "Studio566 shows an AI-content label to the user and asks them to enable the platform AI label when posting"

STYLES = {"f1": ("female", "Nữ trẻ, sôi nổi"), "f2": ("female", "Nữ, ấm áp kể chuyện"),
          "m1": ("male", "Nam trẻ, năng động"), "m2": ("male", "Nam trầm, thuyết minh")}
NAMES = {
    "en": ("Emma", "Grace", "Jake", "Robert"), "id": ("Putri", "Sari", "Rizky", "Budi"), "th": ("Ploy", "Nok", "Ton", "Somchai"),
    "tl": ("Angel", "Maria", "Paolo", "Jose"), "ms": ("Aisyah", "Nurul", "Hafiz", "Azman"), "es": ("Sofía", "Lucía", "Diego", "Javier"),
    "pt": ("Ana", "Beatriz", "Lucas", "Rafael"), "ja": ("Yui", "Akiko", "Haruto", "Takeshi"), "ko": ("Jiwoo", "Eunji", "Minho", "Jinwoo"),
    "hi": ("Ananya", "Priya", "Arjun", "Rajesh"), "ar": ("Layla", "Mariam", "Omar", "Khalid"), "fr": ("Chloé", "Camille", "Hugo", "Laurent"),
    "de": ("Lena", "Sabine", "Jonas", "Thomas"), "ru": ("Anya", "Irina", "Artem", "Sergei"), "it": ("Giulia", "Francesca", "Marco", "Roberto"),
    "tr": ("Elif", "Zeynep", "Emre", "Mehmet"), "pl": ("Ola", "Anna", "Kuba", "Piotr"), "nl": ("Sanne", "Esther", "Daan", "Pieter"),
    "he": ("Noa", "Yael", "Itay", "Avi"),
}
_ORDER = ("f1", "f2", "m1", "m2")


def voices(lang: str | None = None) -> list[dict]:
    """Thư viện giọng đóng gói sẵn: [{id, lang, gender, name, style, label}]. Chỉ giọng có đủ đoạn mẫu."""
    out = []
    for code, names in NAMES.items():
        if lang and code != lang:
            continue
        for sid, name in zip(_ORDER, names):
            vid = f"{code}_{sid}"
            if not (DATA / f"{vid}.mp3").is_file():
                continue
            g, style = STYLES[sid]
            out.append({"id": vid, "lang": code, "gender": g, "name": name, "style": style, "label": f"{name} · {style}"})
    return out


def is_vox(voice: str) -> bool:
    v = voice or ""
    return len(v) >= 5 and v[-3] == "_" and v[-2:] in _ORDER and v[:-3] in NAMES


def lang_of(voice: str) -> str:
    return voice[:-3] if is_vox(voice) else ""


def default_voice(lang: str, gender: str) -> str:
    sid = "f1" if gender == "female" else "m1"
    vid = f"{lang}_{sid}"
    return vid if (DATA / f"{vid}.mp3").is_file() else ""


def ready() -> bool:
    from .localai import pack_ready
    return pack_ready("voices")


# ------------------------------------------------------------------ đoạn mẫu -> thư mục giọng của máy chủ

def voice_dir() -> Path:
    from .localai import AI_DIR
    return AI_DIR / "voices"


def _prepare(vid: str) -> None:
    """mp3 đóng gói -> wav 24 kHz + .txt trong thư mục giọng của máy chủ (CrispASR đọc <tên>.wav và <tên>.txt)."""
    from .util import ffmpeg
    d = voice_dir()
    d.mkdir(parents=True, exist_ok=True)
    wav, txt = d / f"{vid}.wav", d / f"{vid}.txt"
    src = DATA / f"{vid}.mp3"
    if not src.is_file():
        raise RuntimeError(f"Không có giọng {vid}")
    if not wav.is_file() or wav.stat().st_mtime < src.stat().st_mtime:
        tmp = d / f"{vid}.part.wav"
        ffmpeg(["-i", src, "-ac", 1, "-ar", 24000, tmp])
        tmp.replace(wav)
    t = (DATA / f"{vid}.txt").read_text(encoding="utf-8").strip()
    if not txt.is_file() or txt.read_text(encoding="utf-8").strip() != t:
        txt.write_text(t, encoding="utf-8")


def prepare_mine(vid: str, ref: Path, text: str = "") -> str:
    """Giọng của tôi (myvoice.py) dùng cho thứ tiếng khác: chép mẫu vào thư mục giọng dưới tên riêng. Người dùng đã thu giọng chính mình."""
    from .util import ffmpeg
    name = "me_" + hashlib.sha1(vid.encode()).hexdigest()[:10]
    d = voice_dir()
    d.mkdir(parents=True, exist_ok=True)
    wav = d / f"{name}.wav"
    if not wav.is_file() or wav.stat().st_mtime < ref.stat().st_mtime:
        tmp = d / f"{name}.part.wav"
        ffmpeg(["-i", ref, "-ac", 1, "-ar", 24000, tmp])
        tmp.replace(wav)
    (d / f"{name}.txt").write_text(text, encoding="utf-8") if text else (d / f"{name}.txt").unlink(missing_ok=True)
    return name


# ------------------------------------------------------------------ máy chủ CrispASR

class VoxServer:
    def __init__(self):
        self.lock = threading.RLock()
        self.speak = threading.Lock()      # mỗi lúc một câu: máy chủ chỉ có một phiên mô hình
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.last = 0.0
        self._watch: threading.Thread | None = None

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def ensure(self) -> None:
        from . import localai as L
        with self.lock:
            self.last = time.time()
            if self.running():
                return
            if not ready():
                raise RuntimeError("Chưa tải Giọng đọc nhiều thứ tiếng. Vào Cài đặt, mục Mô-đun AI miễn phí, bấm Tải.")
            L.LLAMA.stop()      # nhường card đồ họa
            logs = L.AI_DIR / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            voice_dir().mkdir(parents=True, exist_ok=True)
            self.port = L._free_port()
            cmd = [str(L.exe_of("crisp")), "--server", "--backend", "voxcpm2-tts", "-m", L.short_path(L.path_of("voxcpm2")),
                   "--host", "127.0.0.1", "--port", str(self.port), "--voice-dir", L.short_path(voice_dir()),
                   "--accept-marking-responsibility"]
            with open(logs / "voices.log", "w", encoding="utf-8") as lf:
                self.proc = subprocess.Popen(cmd, cwd=L.path_of("crisp"), stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT,
                                             creationflags=L.NO_WINDOW)
            L.adopt(self.proc)
            end = time.time() + 240
            while time.time() < end:
                if self.proc.poll() is not None:
                    tail = L._tail(logs / "voices.log")
                    self.proc = None
                    raise RuntimeError("Bộ đọc nhiều thứ tiếng không khởi động được: " + (tail[-400:] or "không rõ lý do"))
                try:
                    with L._local.open(f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                        if r.status == 200:
                            break
                except (OSError, ValueError):
                    pass
                time.sleep(0.4)
            else:
                self.stop()
                raise RuntimeError("Bộ đọc nhiều thứ tiếng khởi động quá lâu (hơn 4 phút). Thử lại, hoặc khởi động lại máy.")
            log("tts", f"Bật bộ đọc nhiều thứ tiếng (cổng {self.port})")
            if self._watch is None or not self._watch.is_alive():
                self._watch = threading.Thread(target=self._idle_loop, daemon=True, name="ui-vox-idle")
                self._watch.start()

    def _idle_loop(self) -> None:
        while True:
            time.sleep(10)
            with self.lock:
                if not self.running():
                    return
                if time.time() - self.last > IDLE and not self.speak.locked():
                    log("tts", "Tắt bộ đọc nhiều thứ tiếng (đang rảnh)")
                    self.stop()
                    return

    def stop(self) -> None:
        with self.lock:
            p, self.proc = self.proc, None
            if p is not None and p.poll() is None:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()

    def say(self, text: str, voice: str, seed: int, timeout: float = 600) -> bytes:
        """Đọc một câu bằng giọng (tên trong thư mục giọng) -> bytes WAV."""
        from .localai import _local
        self.ensure()
        body = {"input": text, "voice": voice, "seed": int(seed) or 1, "response_format": "wav",
                "consent_attestation": CONSENT, "spoken_disclaimer": False, "marking_attestation": MARKING}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/audio/speech", json.dumps(body).encode("utf-8"),
                                     {"Content-Type": "application/json"})
        with self.speak:
            try:
                with _local.open(req, timeout=timeout) as r:
                    data = r.read()
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                raise RuntimeError(f"Bộ đọc từ chối câu này ({e.code}): {detail}") from e
            finally:
                with self.lock:
                    self.last = time.time()
        if len(data) < 1000:
            raise RuntimeError("Bộ đọc trả về âm thanh rỗng")
        return data


SERVER = VoxServer()


def seed_for(text: str, voice: str) -> int:
    """Cùng câu, cùng giọng thì đọc ra giống nhau (đọc lại không đổi giọng điệu), câu khác thì khác."""
    return int(hashlib.sha1(f"{voice}|{text}".encode("utf-8")).hexdigest()[:7], 16) + 1


def synth_many(jobs: list[tuple[str, str, str, Path]], on_step=None) -> list[Path]:
    """jobs: [(text, voice, _rate, out.wav)] giống edge/VieNeu. voice: id thư viện (en_f1) hoặc 'me:...' (Giọng của tôi).
    Trả về danh sách file lỗi."""
    from . import myvoice
    failed = []
    todo = [j for j in jobs if not j[3].exists()]
    if not todo:
        return failed
    names: dict[str, str] = {}
    for _t, v, _r, _o in todo:
        if v in names:
            continue
        if myvoice.is_mine(v):
            ref = myvoice.path_of(v)
            if ref is None:
                raise RuntimeError("Mẫu \"Giọng của tôi\" đã bị xóa. Chọn giọng khác rồi đọc lại")
            names[v] = prepare_mine(v, ref)
        else:
            _prepare(v)
            names[v] = v
    for n, (text, voice, _rate, out) in enumerate(todo, 1):
        check_cancel()
        try:
            data = SERVER.say(text, names[voice], seed_for(text, voice))
            tmp = out.with_name(out.stem + ".part.wav")
            tmp.write_bytes(data)
            tmp.replace(out)
        except Exception as e:      # noqa: BLE001 — một câu lỗi không làm hỏng cả video
            if type(e).__name__ == "Cancelled":
                raise
            log("tts", f"Bộ đọc nhiều thứ tiếng lỗi câu '{text[:40]}': {str(e)[:200]}")
            failed.append(out)
        if on_step:
            on_step(n, len(todo))
        if n % 10 == 0:
            log("tts", f"  {n}/{len(todo)}")
    return failed
