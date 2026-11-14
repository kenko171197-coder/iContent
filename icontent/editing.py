"""Dựng không phá file gốc: các đoạn bị cắt, lớp chữ/ảnh, bộ màu chỉ là thông tin trong options.json của video,
được áp dụng lúc render. Studio luôn làm việc theo thời gian của video gốc.

Cắt bằng select/aselect trong cùng một lệnh ffmpeg (một lần mã hóa, không giảm chất lượng). Không dùng split + trim +
concat vì split giữ khung hình trong bộ nhớ cho các nhánh chưa tới lượt, video dài sẽ ngốn RAM.
"""
from __future__ import annotations

from .models import Segment

MIN_CUT = 0.05       # đoạn ngắn hơn (giây) coi như không có
MIN_KEEP = 0.5       # phải còn lại ít nhất từng này giây video

# bộ màu: bộ lọc ffmpeg. Trang Studio có CSS xem trước tương ứng (player.js)
LOOKS = {
    "warm": "colorbalance=rs=.06:gs=.01:bs=-.06:rm=.04:bm=-.04,eq=saturation=1.08",
    "cool": "colorbalance=rs=-.05:bs=.07:rm=-.03:bm=.04,eq=saturation=1.02",
    "vivid": "eq=contrast=1.08:saturation=1.3",
    "film": "eq=contrast=1.1:saturation=.82,colorbalance=rs=.03:bs=-.05:rh=.04:bh=-.03",
    "bw": "hue=s=0,eq=contrast=1.1",
    "vintage": "curves=preset=vintage,eq=saturation=.92",
    "teal": "colorbalance=rs=-.08:gs=-.02:bs=.1:rh=.1:gh=.02:bh=-.08,eq=contrast=1.06:saturation=1.08",
    "moody": "eq=contrast=1.14:brightness=-.03:saturation=.78,colorbalance=bs=.05:rh=.03",
    "bright": "eq=brightness=.03:contrast=1.02:saturation=1.1,curves=all='0/0 0.5/0.56 1/1'",
    "golden": "colorbalance=rs=.1:gs=.04:bs=-.1:rh=.05:bh=-.05,eq=contrast=1.05:saturation=1.12",
}

# giọng tự thu: lọc tiếng ù, giảm ồn nền, cổng hạ nền ở khoảng nghỉ, nén rất nhẹ. Đo trên giọng thật có thêm nhiễu: tỉ lệ
# giọng/nền tăng khoảng 11 dB. Không dùng loudnorm ở chuỗi này: loudnorm một lượt và nén mạnh kéo nền ồn lên ở khoảng nghỉ,
# làm mất gần hết tác dụng (đo được chỉ còn 2 dB), nên âm lượng được chỉnh bằng gain cố định sau đó, xem normalize_voice
# afftdn làm trễ tiếng đúng 25 ms (đo bằng tương quan chéo) nên phải cắt bù ngay sau nó, nếu không giọng thu lệch nhịp so với hình
VOICE_CLEAN = ("highpass=f=80,highpass=f=80,afftdn=nr=20:nf=-40:tn=1,atrim=start=0.025,asetpts=PTS-STARTPTS,"
               "agate=threshold=0.02:ratio=4:attack=8:release=220:range=0.08,acompressor=threshold=-20dB:ratio=2:attack=10:release=150")
VOICE_LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
VOICE_LEVEL_DB = -20.0       # mức RMS của phần có giọng, tương đương khoảng -16 LUFS
VOICE_PEAK_DB = -1.5


def normalize_voice(data, sr: int):
    """Chỉnh âm lượng bằng một hệ số duy nhất, nên khoảng nghỉ vẫn nhỏ đúng tỉ lệ so với giọng. Đo mức trên phần to nhất của
    bản thu để khoảng nghỉ không kéo sai con số."""
    import numpy as np

    x = np.asarray(data, dtype=np.float32)
    peak = float(np.abs(x).max()) if x.size else 0.0
    if peak < 1e-4:
        return x
    n = max(1, int(sr * 0.05))
    k = x.size // n
    if k >= 4:
        w = np.sqrt(np.mean(x[:k * n].reshape(k, n) ** 2, axis=1))
        level = float(np.sqrt(np.mean(np.sort(w)[k // 2:] ** 2)))
    else:
        level = float(np.sqrt(np.mean(x ** 2)))
    gain = min(10 ** (VOICE_LEVEL_DB / 20) / max(level, 1e-5), 10 ** (VOICE_PEAK_DB / 20) / peak)
    return x * gain


def normalize_cuts(cuts, duration: float) -> list[list[float]]:
    """Sắp xếp, gộp đoạn chồng nhau, cắt theo độ dài video, bỏ đoạn quá ngắn. Dữ liệu hỏng thì bỏ qua."""
    out: list[list[float]] = []
    items = []
    for c in cuts or []:
        try:
            a, b = float(c[0]), float(c[1])
        except (TypeError, ValueError, IndexError):
            continue
        items.append((min(a, b), max(a, b)))
    for a, b in sorted(items):
        a, b = max(0.0, a), b if not duration else min(b, duration)
        if b - a < MIN_CUT:
            continue
        if out and a <= out[-1][1] + 1e-3:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([round(a, 3), round(b, 3)])
    if duration and duration - sum(b - a for a, b in out) < MIN_KEEP:
        raise ValueError("Đang cắt gần hết video, không còn gì để dựng. Hãy khôi phục bớt đoạn đã cắt.")
    return out


def kept_ranges(cuts: list[list[float]], duration: float) -> list[tuple[float, float]]:
    out, cur = [], 0.0
    for a, b in cuts:
        if a > cur:
            out.append((cur, a))
        cur = max(cur, b)
    if duration > cur:
        out.append((cur, duration))
    return out


def kept_duration(cuts: list[list[float]], duration: float) -> float:
    return duration - sum(b - a for a, b in cuts)


def complement(ranges, duration: float) -> list[list[float]]:
    """Giữ đúng các đoạn trong ranges = cắt mọi phần còn lại. Dùng để xuất một đoạn thành clip riêng."""
    keep = normalize_cuts(ranges, 0.0)
    return [[round(a, 3), round(b, 3)] for a, b in kept_ranges(keep, duration)]


def map_time(t: float, cuts: list[list[float]]) -> float | None:
    """Thời gian gốc -> thời gian sau khi cắt. None nếu t nằm trong đoạn bị cắt."""
    removed = 0.0
    for a, b in cuts:
        if t < a:
            break
        if t < b:
            return None
        removed += b - a
    return t - removed


def map_range(st: float, en: float, cuts: list[list[float]]) -> tuple[float, float] | None:
    """Khoảng thời gian gốc -> khoảng sau khi cắt, bỏ phần bị cắt. None nếu bị cắt hết."""
    kept = 0.0
    start = None
    removed = 0.0
    prev = 0.0
    for a, b in [*cuts, [float("inf"), float("inf")]]:
        lo, hi = max(st, prev), min(en, a)
        if hi > lo:
            if start is None:
                start = lo - removed
            kept += hi - lo
        removed += 0 if a == float("inf") else b - a
        prev = b
    return None if start is None else (start, start + kept)


def map_items(items: list[tuple], cuts: list[list[float]]) -> list[tuple]:
    """Phụ đề (start, end, text, speech_end) theo video đã cắt: câu bị cắt hết thì bỏ, cắt một phần thì co lại."""
    if not cuts:
        return items
    out = []
    for it in items:
        r = map_range(it[0], it[1], cuts)
        if r is None or r[1] - r[0] < 0.05:
            continue
        sp = map_range(it[0], it[3], cuts) if len(it) > 3 and it[3] else None
        out.append((r[0], r[1], it[2], sp[1] if sp else r[1]))
    return out


def _kept_expr(cuts: list[list[float]]) -> str:
    return "not(" + "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in cuts) + ")"


def split_tail(cuts: list[list[float]], duration: float) -> tuple[list[list[float]], float]:
    """Đoạn cắt chạm cuối video không được xử lý bằng select: select vứt hết khung cuối nhưng bộ lọc không báo hết,
    -t đóng luồng hình trước còn luồng tiếng chờ mãi, ffmpeg treo vĩnh viễn (đã gặp thật). Thay vào đó dùng trim để bộ lọc
    tự kết thúc ở điểm giữ cuối cùng. -> (đoạn cắt bên trong, thời điểm kết thúc)."""
    if cuts and cuts[-1][1] >= duration - 0.01:
        return cuts[:-1], cuts[-1][0]
    return cuts, duration


EXPR_CHUNK = 40      # ffmpeg từ chối biểu thức quá dài: đo được hỏng từ khoảng 98 đoạn cắt trong một biểu thức
AUDIO_FRAME = 64     # aselect giữ nguyên cả khung tiếng: khung 1,3 ms thì mỗi điểm cắt lệch không đáng kể so với hình


def _chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def video_cut_filter(inner: list[list[float]], end: float) -> str:
    """Giữ nguyên nhịp khung hình gốc (kể cả video tốc độ khung thay đổi): dời PTS theo tổng đã cắt trước đó.

    Nhiều đoạn thì chia thành nhiều bộ lọc nối tiếp. Dời PTS phải làm từ đoạn cuối về đoạn đầu: khung sau một nhóm đoạn
    cắt không bao giờ lùi quá điểm đầu của nhóm, nên mốc của các nhóm trước vẫn đúng."""
    parts = [f"trim=end={end:.3f}"]
    groups = _chunks(inner, EXPR_CHUNK)
    parts += [f"select='{_kept_expr(g)}'" for g in groups]
    for g in reversed(groups):
        shift = "+".join(f"gte(T,{b:.3f})*{b - a:.3f}" for a, b in g)
        parts.append(f"setpts='(T-({shift}))/TB'")
    return ",".join(parts)


def audio_cut_filter(inner: list[list[float]]) -> str:
    selects = ",".join(f"aselect='{_kept_expr(g)}'" for g in _chunks(inner, EXPR_CHUNK))
    return f"asetnsamples=n={AUDIO_FRAME}:p=0,{selects},asetpts=N/SR/TB"


def scale_cuts(cuts: list[list[float]], speed: float) -> list[list[float]]:
    return [[a / speed, b / speed] for a, b in cuts]


def silence_gaps(segs: list[Segment], duration: float, min_gap: float = 0.8, keep: float = 0.2) -> list[list[float]]:
    """Gợi ý đoạn thừa: khoảng không có lời (kể cả phần giọng lồng đọc lố sang) dài hơn min_gap, chừa lại keep mỗi bên."""
    spans = []
    for s in segs:
        a, b = s.start, s.end
        if s.dub_start is not None:
            a = min(a, s.dub_start)
        if s.dub_end is not None:
            b = max(b, s.dub_end)
        spans.append((a, b))
    spans.sort()
    out, cur = [], 0.0
    for a, b in spans:
        if a - cur >= min_gap + 2 * keep:
            out.append([round(cur + keep, 3) if cur > 0 else 0.0, round(a - keep, 3)])
        cur = max(cur, b)
    if duration - cur >= min_gap + keep:
        out.append([round(cur + keep, 3), round(duration, 3)])
    return out


def overlays_valid(overlays) -> list[dict]:
    """Bỏ lớp phủ hỏng, đảm bảo có đủ trường. Toạ độ là tỉ lệ khung hình (tâm lớp)."""
    out = []
    for o in overlays or []:
        if not isinstance(o, dict) or o.get("type") not in ("text", "image"):
            continue
        try:
            st, en = float(o.get("start", 0)), float(o.get("end", 0))
            x, y = float(o.get("x", 0.5)), float(o.get("y", 0.5))
            size = float(o.get("size") or (0.08 if o["type"] == "text" else 0.3))
        except (TypeError, ValueError):
            continue
        if en - st < 0.05:
            continue
        if o["type"] == "text" and not str(o.get("text") or "").strip():
            continue
        if o["type"] == "image" and not o.get("path"):
            continue
        out.append({**o, "start": st, "end": en, "x": min(1.0, max(0.0, x)), "y": min(1.0, max(0.0, y)), "size": max(0.01, size)})
    return out


def ass_color(hex_color: str, default: str = "FFFFFF") -> str:
    """'#RRGGBB' -> 'BBGGRR' của ASS."""
    h = str(hex_color or "").lstrip("#")
    if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
        h = default
    return (h[4:6] + h[2:4] + h[0:2]).upper()
