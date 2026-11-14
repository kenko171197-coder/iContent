"""Segment (1 câu thoại theo timeline) + đọc/ghi JSON, SRT, ASS (5 kiểu phụ đề)."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str                     # câu gốc (tiếng Trung)
    trans: str = ""               # bản dịch
    voice: str = ""               # giọng riêng cho câu này (để trống = giọng mặc định)
    dub_start: float | None = None  # vị trí thực tế của câu lồng tiếng sau khi căn timeline
    dub_end: float | None = None
    speed: float | None = None      # hệ số tăng tốc đã áp dụng
    gender: str = ""                # male | female — đoán từ cao độ giọng gốc (chọn giọng lồng)
    ocr: str = ""                   # chữ phụ đề in sẵn trên màn hình lúc đó (OCR) — tham chiếu khi dịch
    speaker: str = ""               # người nói: S1, S2... (S1 nói nhiều nhất), xem speakers.py
    rec: str = ""                   # giọng thu tay cho câu này (file trong thư mục rec/ của job), thay cho TTS

    @property
    def dur(self) -> float:
        return max(0.0, self.end - self.start)


def save_segments(path: str | Path, segs: list[Segment]) -> None:
    Path(path).write_text(
        json.dumps([asdict(s) for s in segs], ensure_ascii=False, indent=1), encoding="utf-8"
    )


def load_segments(path: str | Path) -> list[Segment]:
    names = {f.name for f in fields(Segment)}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Segment(**{k: v for k, v in d.items() if k in names}) for d in raw]


# --------------------------------------------------------------------------- SRT

def _srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path: str | Path, items: list[tuple]) -> None:
    """items: (start, end, text[, ...])"""
    out = []
    n = 0
    for it in items:
        start, end, text = it[0], it[1], it[2]
        if not text.strip():
            continue
        n += 1
        out.append(f"{n}\n{_srt_time(start)} --> {_srt_time(end)}\n{text.strip()}\n")
    Path(path).write_text("\n".join(out), encoding="utf-8")


_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def read_srt(path: str | Path) -> list[tuple[float, float, str]]:
    text = Path(path).read_text(encoding="utf-8-sig")
    items = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = _TS.search(line)
            if m:
                g = [int(x) for x in m.groups()]
                st = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                en = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                items.append((st, en, "\n".join(lines[i + 1:]).strip()))
                break
    return items


# --------------------------------------------------------------------------- ASS

BS = "\\"   # dấu gạch ngược của thẻ ASS (\c, \kf, \N ...)
STYLES = ("classic", "cinema", "box", "tiktok", "karaoke", "pop")
STYLE_SCALE = {"tiktok": 1.2, "pop": 1.3}   # cỡ chữ so với cỡ chuẩn


def _ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(s: str) -> str:
    return s.replace(BS, BS + BS).replace("{", "(").replace("}", ")").replace("\n", BS + "N")


def ass_font_size(width: int, height: int, ecfg) -> int:
    return max(16, int(round(min(width, height) * ecfg.font_size_ratio * (1.0 if width >= height else 1.25))))


def style_font_size(width: int, height: int, ecfg) -> int:
    """Cỡ chữ thực tế của kiểu phụ đề đang chọn."""
    return int(ass_font_size(width, height, ecfg) * STYLE_SCALE.get(ecfg.get("sub_style") or "classic", 1.0))


VERTICAL_BOTTOM = 0.25      # khớp với profiles.SAFE_ZONE_9X16["bottom"]


def auto_margin_v(width: int, height: int, ecfg) -> int:
    """Khoảng cách từ đáy khung tới đáy phụ đề khi không đặt tay."""
    ratio = float(ecfg.margin_ratio)
    if height > width:
        ratio = max(ratio, VERTICAL_BOTTOM)      # khung dọc: mọi kiểu đều tránh vùng nút và mô tả của ứng dụng
    elif (ecfg.get("sub_style") or "classic") in ("tiktok", "pop"):
        ratio = max(ratio, 0.1)
    return int(round(height * ratio))


def _inline_color(c: str) -> str:
    """'&H0000E5FF' (style, AABBGGRR) -> '&H00E5FF&' (thẻ màu inline, BBGGRR)."""
    c = (c or "").upper().removeprefix("&H").rstrip("&")
    return f"&H{c[-6:]}&" if len(c) >= 6 else "&H00E5FF&"


def _weights(words: list[str]) -> list[float]:
    """Ước lượng thời lượng đọc từng âm tiết: theo số chữ cái + nghỉ ở dấu câu."""
    out = []
    for w in words:
        n = sum(ch.isalnum() for ch in w)
        tail = 2.5 if w[-1:] in ",;:" else (3.5 if w[-1:] in ".!?…" else 0.0)
        out.append(max(1.0, n * 0.6 + 1.5) + tail)
    return out


def _chunks(words: list[str], size: int, max_chars: int = 0) -> list[list[int]]:
    """Chia câu thành cụm <= size âm tiết và <= max_chars ký tự (vừa 1 dòng), ưu tiên ngắt sau dấu câu;
    tránh cụm cuối quá ngắn."""
    total_chars = sum(len(w) + 1 for w in words)
    if size <= 0 or (len(words) <= size and (not max_chars or total_chars <= max_chars)):
        return [list(range(len(words)))]
    out, cur, chars = [], [], 0
    for i, w in enumerate(words):
        if cur and max_chars and chars + len(w) > max_chars:
            out.append(cur)
            cur, chars = [], 0
        cur.append(i)
        chars += len(w) + 1
        rest = len(words) - i - 1
        if len(cur) >= size or (len(cur) >= size * 0.5 and w[-1:] in ",.;:!?…" and rest >= 2):
            out.append(cur)
            cur, chars = [], 0
    if cur:
        fits = not max_chars or sum(len(words[i]) + 1 for i in out[-1] + cur) - 1 <= max_chars if out else False
        if len(cur) <= 2 and out and fits:
            out[-1] += cur
        else:
            out.append(cur)
    return out


def overlay_events(overlays: list[dict], width: int, height: int, speed: float, default_font: str) -> list[str]:
    """Lớp chữ trên video: thẻ ASS đặt thẳng trong từng dòng, nằm trên phụ đề (layer 5)."""
    from .editing import ass_color

    out = []
    for o in overlays:
        if o.get("type") != "text":
            continue
        fs = max(10, int(round(height * float(o.get("size") or 0.08))))
        x, y = int(round(float(o["x"]) * width)), int(round(float(o["y"]) * height))
        fade = int(float(o.get("fade", 0.2)) * 1000)
        box = o.get("style") == "box"
        tags = [f"{BS}an5", f"{BS}pos({x},{y})", f"{BS}fs{fs}", f"{BS}fn{o.get('font') or default_font}", f"{BS}b{1 if o.get('bold', True) else 0}",
                f"{BS}1c&H{ass_color(o.get('color'), 'FFFFFF')}&"]
        if box:
            tags += [f"{BS}3c&H{ass_color(o.get('bg'), '000000')}&", f"{BS}bord{max(4, fs // 4)}", f"{BS}shad0"]
        else:
            tags += [f"{BS}3c&H{ass_color(o.get('outline'), '000000')}&", f"{BS}bord{max(2, fs // 12)}", f"{BS}shad{max(1, fs // 30)}"]
        if fade:
            tags.append(f"{BS}fad({fade},{fade})")
        style = "OvBox" if box else "Default"
        text = _ass_escape(str(o.get("text") or "").strip())
        out.append(f"Dialogue: 5,{_ass_time(float(o['start']) / speed)},{_ass_time(float(o['end']) / speed)},{style},,0,0,0,,{{{''.join(tags)}}}{text}")
    return out


def write_ass(path: str | Path, items: list[tuple], width: int, height: int, ecfg,
              margin_v: int | None = None, total: float | None = None, overlays: list[dict] | None = None,
              speed: float = 1.0) -> None:
    """items: (start, end, text[, speech_end]); speech_end = lúc giọng lồng đọc xong câu (chạy hiệu ứng chữ).

    classic: chữ trắng viền đen | box: nền hộp mờ | tiktok: từng cụm, âm tiết đang đọc đổi màu, cụm mới bật lên
    karaoke: tô màu dần theo lời đọc | pop: chữ hoa cỡ lớn, cụm ngắn, âm tiết đang đọc đổi màu và phóng to
    """
    style = ecfg.get("sub_style") or "classic"
    style = style if style in STYLES else "classic"
    size = ass_font_size(width, height, ecfg)
    upper = style == "pop" or bool(ecfg.get("uppercase"))
    if margin_v is None:
        margin_v = auto_margin_v(width, height, ecfg)
    margin_h = int(round(width * 0.06))
    bold = -1 if ecfg.bold else 0
    prim, sec, outc, back = ecfg.primary_color, "&H000000FF", ecfg.outline_color, "&H80000000"
    hl = ecfg.get("highlight_color") or "&H0000E5FF"
    outline, shadow, border = ecfg.outline, 1, 1
    if style == "box":
        border, outline, shadow, outc = 3, max(4, size // 4), 0, "&H50000000"
    elif style in ("tiktok", "pop"):
        size = int(size * STYLE_SCALE[style])
        outline, shadow = max(int(ecfg.outline), round(size / (10 if style == "pop" else 12))), 2
    elif style == "karaoke":
        prim, sec = hl, ecfg.primary_color          # phần đã đọc = màu nhấn, phần chưa đọc = trắng
    elif style == "cinema":
        # kiểu phụ đề phim: viền rất mỏng, bóng mềm thay vì viền đen dày
        outline, shadow, back = max(1, size // 30), max(2, size // 18), "&H78000000"
    mark_size = max(14, int(min(width, height) * 0.032))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{ecfg.font},{size},{prim},{sec},{outc},{back},{bold},0,0,0,100,100,0,0,{border},{outline},{shadow},2,{margin_h},{margin_h},{margin_v},1
Style: Mark,{ecfg.font},{mark_size},&H66FFFFFF,&H000000FF,&H99000000,&H00000000,-1,0,0,0,100,100,0,0,1,1,0,9,{margin_h // 2},{margin_h // 2},{int(height * 0.04)},1
Style: OvBox,{ecfg.font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,4,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: list[str] = []

    def dlg(st: float, en: float, text: str, name: str = "Default") -> None:
        lines.append(f"Dialogue: 0,{_ass_time(st)},{_ass_time(en)},{name},,0,0,0,,{text}")

    c_hl, c_prim = _inline_color(hl), _inline_color(prim)
    line_chars = max(8, int((width - 2 * margin_h) / (size * (0.68 if upper else 0.56))))   # ký tự vừa 1 dòng (ước lượng)
    pop_in = "{" + BS + "fscx88" + BS + "fscy88" + BS + "t(0,90," + BS + "fscx100" + BS + "fscy100)}"
    grow = BS + "fscx118" + BS + "fscy118" if style == "pop" else ""     # âm tiết đang đọc phóng to
    shrink = BS + "fscx100" + BS + "fscy100" if style == "pop" else ""
    chunk = int(ecfg.get("tiktok_chunk") or 7)
    if style == "pop":
        chunk = min(chunk, 4)
    for it in items:
        st, en, tx = it[0], it[1], it[2].strip()
        if not tx:
            continue
        if upper:
            tx = tx.upper()
        sp_en = it[3] if len(it) > 3 and it[3] else en
        sp_en = max(st + 0.2, min(sp_en, en))
        if style == "cinema":
            dlg(st, en, "{" + BS + "blur0.6}" + _ass_escape(tx))
            continue
        if style in ("classic", "box"):
            dlg(st, en, _ass_escape(tx))
            continue
        words = tx.replace("\n", " ").split()
        wts = _weights(words)
        # mốc bắt đầu từng âm tiết, trải theo trọng số trong lúc giọng lồng đang đọc
        span, tot = sp_en - st, sum(wts)
        starts, acc = [], 0.0
        for w in wts:
            starts.append(st + span * acc / tot)
            acc += w
        if style == "karaoke":
            parts = " ".join(
                "{" + BS + f"kf{max(1, round(span * w / tot * 100))}" + "}" + _ass_escape(word)
                for word, w in zip(words, wts))
            dlg(st, en, parts)
            continue
        groups = _chunks(words, chunk, line_chars)
        for gi, g in enumerate(groups):
            g_end = starts[groups[gi + 1][0]] if gi + 1 < len(groups) else en
            for k, wi in enumerate(g):
                w_st = starts[wi]
                w_en = starts[g[k + 1]] if k + 1 < len(g) else g_end
                if w_en - w_st < 0.01:
                    continue
                txt = " ".join(
                    ("{" + BS + f"c{c_hl}{grow}" + "}" + _ass_escape(words[j]) + "{" + BS + f"c{c_prim}{shrink}" + "}")
                    if j == wi else _ass_escape(words[j])
                    for j in g)
                dlg(w_st, w_en, (pop_in if k == 0 else "") + txt)
    mark = (ecfg.get("watermark_text") or "").strip()
    if mark and total:
        dlg(0, total, _ass_escape(mark), "Mark")
    lines += overlay_events(overlays or [], width, height, speed or 1.0, ecfg.font)
    Path(path).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
