"""Giọng của tôi: mẫu giọng người dùng tự thu hoặc tải lên, để VieNeu đọc bằng chính giọng đó.

Mã giọng có dạng "me:v1a2b3c4d". Mẫu lưu ở assets/voices (không đưa lên git): <mã>.wav là đoạn đã làm sạch, <mã>.json là tên, giới tính, độ dài.
Mỗi lần thu lại là một mã mới, nên cache giọng đọc theo mã không bao giờ trả về giọng cũ."""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

import numpy as np

from .util import ROOT, ffmpeg, read_wav, write_wav

DIR = ROOT / "assets" / "voices"
PREFIX = "me:"
SR = 44100
MAX_CLIP = 8.0           # VieNeu chỉ nghe 8 giây đầu của mẫu
MIN_SPEECH = 3.0         # dưới 3 giây có tiếng nói thì giọng nhại ra không giống
MAX_UPLOAD = 25 * 1024 * 1024
MAX_SOURCE = 600.0       # file dài hơn 10 phút: chỉ đọc 10 phút đầu
FRAME = 0.02
_ID = re.compile(r"v[0-9a-f]{8}")


def is_mine(voice: str | None) -> bool:
    return bool(voice) and str(voice).startswith(PREFIX)


def _vid(voice: str) -> str | None:
    v = str(voice or "")
    v = v[len(PREFIX):] if v.startswith(PREFIX) else v
    return v if _ID.fullmatch(v) else None


def path_of(voice: str) -> Path | None:
    """Đường dẫn mẫu giọng của mã "me:..."; None nếu mã sai hoặc mẫu đã bị xóa."""
    v = _vid(voice)
    if not v:
        return None
    f = DIR / f"{v}.wav"
    return f if f.is_file() else None


def list_voices() -> list[dict]:
    out = []
    if not DIR.is_dir():
        return out
    for meta in DIR.glob("v*.json"):
        v = meta.stem
        if not _ID.fullmatch(v) or not (DIR / f"{v}.wav").is_file():
            continue
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": PREFIX + v, "name": info.get("name") or "Giọng của tôi", "gender": info.get("gender") or "",
                    "dur": info.get("dur") or 0, "created": info.get("created") or 0, "warnings": info.get("warnings") or []})
    return sorted(out, key=lambda x: x["created"])


def _frames_db(x: np.ndarray) -> np.ndarray:
    n = int(FRAME * SR)
    k = x.size // n
    if k == 0:
        return np.full(1, -120.0)
    rms = np.sqrt(np.mean(x[: k * n].reshape(k, n) ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-7))


def pick_clip(x: np.ndarray) -> tuple[np.ndarray, dict]:
    """Từ bản thu (mono, 44.1 kHz) chọn đoạn tối đa 8 giây nhiều tiếng nói nhất, cắt ở chỗ lặng, chỉnh âm lượng.
    Trả về (đoạn, thông tin: số giây có tiếng, độ ồn, cảnh báo)."""
    db = _frames_db(x)
    floor = float(np.percentile(db, 10))
    peak = float(np.percentile(db, 97))
    thr = max(-50.0, floor + 8.0, peak - 30.0)
    voiced = db > thr
    speech = float(voiced.sum() * FRAME)
    if speech < MIN_SPEECH:
        raise ValueError(f"Mẫu chỉ có khoảng {speech:.1f} giây tiếng nói. Cần ít nhất {MIN_SPEECH:.0f} giây, tốt nhất 6 đến 10 giây đọc liền mạch")
    win = int(MAX_CLIP / FRAME)
    if voiced.size <= win:
        a, b = 0, voiced.size
    else:
        csum = np.concatenate([[0], np.cumsum(voiced)])
        counts = csum[win:] - csum[:-win]
        a = int(np.argmax(counts))
        b = a + win
    # cắt ở chỗ lặng gần nhất bên trong khung (không cắt giữa chữ), rồi bỏ khoảng lặng hai đầu
    def quiet_near(i: int, step: int, limit: int) -> int:
        for k in range(limit):
            j = i + step * k
            if 0 <= j < voiced.size and not voiced[j]:
                return j
        return i
    if a > 0:
        a = quiet_near(a, 1, 40)
    if b < voiced.size:
        b = quiet_near(b - 1, -1, 40) + 1
    idx = np.flatnonzero(voiced[a:b])
    if idx.size:
        a, b = a + max(0, int(idx[0]) - 5), a + min(b - a, int(idx[-1]) + 6)      # chừa 0,1 giây trước và sau tiếng nói
    # đếm tiếng nói trong đúng đoạn giữ lại: file dài có tiếng rải rác thì tổng cả file đủ mà đoạn 8 giây vẫn gần như im lặng
    speech = float(voiced[a:b].sum() * FRAME)
    if speech < MIN_SPEECH:
        raise ValueError(f"Tiếng nói rải rác quá: 8 giây nhiều tiếng nhất chỉ có khoảng {speech:.1f} giây nói. "
                         "Thu một đoạn đọc liền mạch 10 đến 20 giây")
    n = int(FRAME * SR)
    clip = x[a * n: b * n].astype(np.float32)
    voiced_rms = float(np.sqrt(np.mean(clip[np.repeat(voiced[a:b], n)[: clip.size]] ** 2))) if clip.size else 0.0
    gain = 10 ** (-20 / 20) / max(voiced_rms, 1e-6)      # tiếng nói khoảng -20 dBFS
    clip = clip * min(gain, 30.0)
    pk = float(np.max(np.abs(clip))) if clip.size else 0.0
    if pk > 0.95:
        clip *= 0.95 / pk
    fade = min(int(0.03 * SR), clip.size // 4)
    if fade:
        ramp = np.linspace(0, 1, fade, dtype=np.float32)
        clip[:fade] *= ramp
        clip[-fade:] *= ramp[::-1]
    snr = peak - floor
    clipped = float(np.mean(np.abs(x) > 0.985))
    warnings = []
    if speech < 5.0:
        warnings.append("Mẫu hơi ngắn: thu 6 đến 10 giây đọc liền mạch thì giọng giống hơn")
    if snr < 22:
        warnings.append("Nền khá ồn: thu ở chỗ yên tĩnh, để micro gần miệng thì giọng rõ hơn")
    if clipped > 0.002:
        warnings.append("Tiếng bị rè vì thu quá to: để micro xa hơn một chút")
    return clip, {"speech": round(speech, 1), "snr": round(snr, 1), "dur": round(clip.size / SR, 2), "warnings": warnings}


def add(data: bytes, name: str = "", gender: str = "") -> dict:
    """Bản thu (webm, ogg, mp3, m4a, wav, cả video) -> mẫu giọng mới."""
    if not data:
        raise ValueError("File trống")
    if len(data) > MAX_UPLOAD:
        raise ValueError("File quá lớn: chỉ cần 10 đến 30 giây đọc rõ ràng")
    DIR.mkdir(parents=True, exist_ok=True)
    v = "v" + uuid.uuid4().hex[:8]
    src = DIR / f".{v}.src"
    raw = DIR / f".{v}.raw.wav"
    try:
        src.write_bytes(data)
        try:
            ffmpeg(["-i", src, "-t", MAX_SOURCE, "-vn", "-ac", 1, "-ar", SR, "-af", "highpass=f=70", "-c:a", "pcm_s16le", raw])
        except Exception as e:
            raise ValueError("Không đọc được tiếng trong file này. Dùng file ghi âm (mp3, m4a, wav, webm) hoặc thu trực tiếp") from e
        x, _ = read_wav(raw)
        clip, info = pick_clip(np.asarray(x, np.float32).reshape(-1))
        write_wav(DIR / f"{v}.part.wav", clip, SR)
        (DIR / f"{v}.part.wav").replace(DIR / f"{v}.wav")
        meta = {"name": (str(name or "").strip()[:40] or "Giọng của tôi"), "gender": gender if gender in ("male", "female") else "",
                "created": round(time.time(), 3), **info}
        (DIR / f"{v}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return {"id": PREFIX + v, **meta}
    finally:
        for f in (src, raw, DIR / f"{v}.part.wav"):
            f.unlink(missing_ok=True)


def rename(voice: str, name: str) -> dict:
    v = _vid(voice)
    meta = DIR / f"{v}.json" if v else None
    if not meta or not meta.is_file():
        raise FileNotFoundError("Không có giọng này")
    info = json.loads(meta.read_text(encoding="utf-8"))
    info["name"] = str(name or "").strip()[:40] or info.get("name") or "Giọng của tôi"
    meta.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return {"id": PREFIX + v, **info}


def delete(voice: str) -> bool:
    v = _vid(voice)
    if not v:
        return False
    found = False
    for f in (DIR / f"{v}.wav", DIR / f"{v}.json"):
        if f.exists():
            f.unlink()
            found = True
    return found
