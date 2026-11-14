"""Gợi ý đoạn đáng cắt thành clip ngắn, chỉ dựa trên thứ đo được: độ to của tiếng, mật độ lời, nhịp chuyển cảnh, câu mở đầu.

Không phải AI hiểu nội dung, nên giao diện phải nói rõ vì sao mỗi đoạn được chọn thay vì đưa một con số bí ẩn. Đoạn luôn bắt
đầu và kết thúc đúng ranh giới câu nên không bao giờ cắt ngang lời. Khi có API key có thể nhờ AI chấm lại sau.
"""
from __future__ import annotations

import re
import wave
from pathlib import Path

import numpy as np

from .models import Segment

WINDOW = 0.25    # giây cho mỗi điểm đo độ to

# câu mở đầu làm người xem muốn nghe tiếp: câu hỏi, điều bất ngờ
HOOK_ZH = re.compile(r"[?？!！]|为什么|为啥|怎么|凭什么|难道|竟然|居然|原来|没想到|想不到|到底|千万|秘密|真相|第一次|最后")
HOOK_VI = re.compile(r"[?!]|tại sao|vì sao|sao lại|làm sao|thế nào|không ngờ|hóa ra|thật ra|thật sự|bí mật|sự thật|lần đầu|cuối cùng", re.I)
# câu bắt đầu bằng từ nối thì tách ra khỏi câu trước sẽ không ai hiểu
JOIN_ZH = re.compile(r"^(但是|可是|不过|然后|所以|因为|而且|而|并且|于是|那么|那|就|还有|另外|其实)")
JOIN_VI = re.compile(r"^(nhưng|mà|và|rồi|thế là|vì vậy|vì thế|cho nên|nên|do đó|còn|ngoài ra)\b", re.I)
END_MARK = re.compile(r"[。！？!?.…\"”』」]\s*$")


def loudness_curve(path: Path, window: float = WINDOW) -> np.ndarray:
    """Độ to (dB) theo từng khoảng thời gian. Đọc dần từng đoạn để video dài không ngốn RAM."""
    out = []
    with wave.open(str(path), "rb") as w:
        sr, ch = w.getframerate(), w.getnchannels()
        if w.getsampwidth() != 2:
            raise ValueError("chỉ hỗ trợ WAV PCM16")
        n = max(1, int(sr * window))
        while True:
            raw = w.readframes(n)
            if len(raw) < 2 * ch:
                break
            x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
            out.append(20 * np.log10(max(rms, 1e-5)))
    return np.array(out, dtype=np.float32)


def _text(s: Segment) -> str:
    return (s.text or "").strip()


def _trans(s: Segment) -> str:
    return (s.trans or "").strip()


def _head(s: Segment) -> float:
    """Điểm bắt đầu có tiếng của câu: giọng lồng có thể vào sớm hơn lời gốc."""
    return min(s.start, s.dub_start) if s.dub_start is not None else s.start


def _tail(s: Segment) -> float:
    """Điểm hết tiếng của câu: giọng lồng hay đọc dài hơn lời gốc, cắt theo lời gốc sẽ mất đoạn cuối câu tiếng Việt."""
    return max(s.end, s.dub_end) if s.dub_end is not None else s.end


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def suggest(segs: list[Segment], duration: float, loud: np.ndarray | None, scene_times: list[float], cuts: list | None = None,
            min_len: float = 20.0, max_len: float = 60.0, count: int = 6, window: float = WINDOW) -> list[dict]:
    """-> [{start, end, score, reasons, first, last, lines}], đoạn tốt nhất trước, không chồng lên nhau."""
    items = sorted((s for s in segs if s.end > s.start and (_text(s) or _trans(s))), key=_head)
    if not items or duration <= 0:
        return []
    has_loud = loud is not None and len(loud) > 4
    base = float(np.median(loud)) if has_loud else 0.0
    cuts = cuts or []
    cands = []
    n = len(items)
    for i in range(n):
        st, en = _head(items[i]), 0.0
        for j in range(i, n):
            en = max(en, _tail(items[j]))
            length = en - st
            if length > max_len:
                break
            if length < min_len:
                continue
            if any(_overlap(st, en, a, b) > 0.2 * length for a, b in cuts):
                continue
            cands.append(_score(items, i, j, st, en, duration, loud if has_loud else None, base, scene_times, window))
    if not cands:
        return []
    cands.sort(key=lambda c: -c["raw"])
    picked: list[dict] = []
    for c in cands:
        if all(_overlap(c["start"], c["end"], p["start"], p["end"]) < 0.15 * (c["end"] - c["start"]) for p in picked):
            picked.append(c)
            if len(picked) >= count:
                break
    # đổi về thang 0..100 để dễ đọc, nhưng chỉ có ý nghĩa so sánh trong cùng một video
    for p in picked:
        p["score"] = int(round(min(100.0, max(0.0, p.pop("raw") * 100))))
    return picked


def _score(items: list[Segment], i: int, j: int, st: float, en: float, duration: float, loud: np.ndarray | None, base: float, scene_times: list[float], window: float) -> dict:
    win = items[i:j + 1]
    length = en - st
    first, last = win[0], win[-1]
    reasons: list[str] = []
    s = 0.0

    # mật độ lời: nhiều lời thì lồng tiếng mới đáng giá
    talk = sum(x.end - x.start for x in win) / length
    s += 0.22 * min(1.0, talk / 0.85)
    if talk >= 0.8:
        reasons.append(f"Nói liên tục {round(talk * 100)}% thời lượng")

    # độ to so với cả video
    if loud is not None:
        a, b = int(st / window), max(int(st / window) + 1, int(en / window))
        part = loud[a:b]
        if part.size:
            lift = float(np.mean(part)) - base
            s += 0.22 * max(0.0, min(1.0, 0.5 + lift / 8))
            if lift >= 1.5:
                reasons.append(f"Giọng to hơn mức trung bình {lift:.1f} dB".replace(".", ","))
            head = part[: max(1, int(3 / window))]
            if float(np.mean(head)) - base >= 2.0:
                s += 0.05
                reasons.append("Mở đầu mạnh")

    # nhịp chuyển cảnh: hình đổi đều thì giữ được mắt người xem. Quá nhanh là cắt loạn, quá chậm là nhàm
    shots = sum(1 for t in scene_times if st < t < en)
    per_min = shots / max(1e-6, length) * 60
    s += 0.14 * max(0.0, min(1.0, per_min / 12)) if per_min <= 40 else 0.07
    if 8 <= per_min <= 40:
        reasons.append(f"Nhịp hình nhanh, {round(per_min)} cảnh mỗi phút")

    # câu mở đầu
    zh1, vi1 = _text(first), _trans(first)
    if HOOK_ZH.search(zh1) or HOOK_VI.search(vi1):
        s += 0.15
        reasons.append("Câu đầu gây tò mò")
    if JOIN_ZH.search(zh1) or JOIN_VI.search(vi1):
        s -= 0.15

    # ranh giới sạch: trước và sau đoạn có khoảng nghỉ, câu cuối kết thúc trọn vẹn
    # đầu và cuối video luôn là ranh giới sạch vì không có lời nào bị cắt ngang
    gap_before = st - _tail(items[i - 1]) if i > 0 else 9.0
    gap_after = _head(items[j + 1]) - en if j + 1 < len(items) else 9.0
    if gap_before < -0.05 or gap_after < -0.05:      # câu kề bên vẫn đang đọc: clip sẽ dính nửa câu của nó
        s -= 0.12
    if gap_before >= 0.25:
        s += 0.08
    if gap_after >= 0.25:
        s += 0.08
    if END_MARK.search(_trans(last) or _text(last)):
        s += 0.06
        if gap_after >= 0.25:
            reasons.append("Kết thúc trọn ý")

    # ưu tiên đoạn gần phía đầu một chút: bối cảnh còn mới
    s += 0.04 * (1 - st / max(1e-6, duration))
    # chỉ hiện vài lý do: lý do người xem cảm nhận được đứng trước
    order = ("Câu đầu", "Mở đầu", "Giọng", "Kết thúc", "Nhịp", "Nói")
    reasons.sort(key=lambda r: next((k for k, x in enumerate(order) if r.startswith(x)), len(order)))
    return {"start": round(st, 3), "end": round(en, 3), "raw": s, "reasons": reasons[:4], "lines": len(win),
            "first": vi1 or zh1, "last": _trans(last) or _text(last)}


def music_offset(path: Path, window: float = 0.5, max_skip: float = 45.0) -> float:
    """Nhạc nền hay có đoạn mở đầu rất nhỏ: tìm chỗ nhạc thật sự vào để không phí phần đầu video. Không tìm thấy thì 0."""
    from .util import find_ffmpeg
    import subprocess
    import tempfile

    exe, _ = find_ffmpeg()
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "m.wav"
        r = subprocess.run([exe, "-hide_banner", "-nostdin", "-loglevel", "error", "-t", "150", "-i", str(path), "-ac", "1", "-ar", "8000", "-y", str(wav)],
                           capture_output=True)
        if r.returncode != 0 or not wav.exists():
            return 0.0
        curve = loudness_curve(wav, window)
    if len(curve) < 6:
        return 0.0
    level = float(np.percentile(curve, 70))
    for k, v in enumerate(curve):
        if v >= level - 8:      # cách mức nhạc chính dưới 8 dB thì coi như đã vào
            t = k * window
            return round(t, 2) if 0.5 <= t <= max_skip else 0.0
    return 0.0
