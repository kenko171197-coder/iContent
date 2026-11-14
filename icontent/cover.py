"""Ảnh bìa tự động: chọn khung hình đẹp nhất của video (nét, đủ sáng, có người), xóa sub gốc, đặt tiêu đề lớn."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from .util import imread, ffmpeg

ASPECTS = {"9:16": (1080, 1920), "16:9": (1280, 720), "1:1": (1080, 1080)}
STYLES = ("noi-bat", "dai-mau", "toi-gian")

# font có đủ dấu tiếng Việt, đậm, có sẵn trên Windows
_FONTS = ["seguibl.ttf", "segoeuib.ttf", "arialbd.ttf"]


def _font(size: int):
    from PIL import ImageFont

    roots = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu")]
    for root in roots:
        for name in [*_FONTS, "DejaVuSans-Bold.ttf"]:
            p = root / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def _frame_at(job: Path, t: float, width: int = 0):
    import cv2

    tmp = job / ".frames"
    tmp.mkdir(exist_ok=True)
    out = tmp / f"cover_{t:.2f}_{width}.jpg"
    if not out.exists():
        vf = ["-vf", f"scale={width}:-2"] if width else []
        ffmpeg(["-ss", f"{max(0.0, t):.3f}", "-i", job / "source.mp4", "-frames:v", "1", *vf, "-strict", "unofficial", "-q:v", "2", out])
    return imread(out)


def _skin_ratio(im) -> float:
    """Tỉ lệ điểm màu da ở vùng giữa-trên khung hình: ước lượng rẻ xem có người trong hình không."""
    import cv2

    h, w = im.shape[:2]
    roi = im[h // 8: h * 5 // 8, w // 5: w * 4 // 5]
    ycc = cv2.cvtColor(roi, cv2.COLOR_BGR2YCrCb)
    mask = (ycc[..., 1] > 138) & (ycc[..., 1] < 175) & (ycc[..., 2] > 85) & (ycc[..., 2] < 125)
    return float(mask.mean())


def score_frame(im) -> float:
    """Điểm khung hình: độ nét x độ sáng hợp lý, cộng điểm khi có người ở giữa khung."""
    import cv2

    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(g, cv2.CV_64F).var())
    mean = float(g.mean())
    light = max(0.05, 1.0 - abs(mean - 120.0) / 120.0)
    score = min(sharp, 1500.0) / 1500.0 * light
    skin = _skin_ratio(im)
    if 0.06 <= skin <= 0.6:      # quá nhiều "màu da" thường là tường/đồ vật cùng tông
        score += 0.35 * min(1.0, skin / 0.2)
    return score


def candidates(job: Path, meta: dict, n: int = 6, samples: int = 36) -> list[dict]:
    """Chọn n khung tốt nhất, rải đều theo thời lượng video. Có cache: cover_candidates.json."""
    cache = job / "cover_candidates.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            pass
    dur = float(meta.get("duration") or 0)
    if dur <= 0:
        return []
    scored: list[tuple[float, float]] = []
    for i in range(samples):
        t = round(dur * (i + 0.5) / samples, 2)
        im = _frame_at(job, t, 320)
        if im is None:
            continue
        scored.append((score_frame(im), t))
    # chia video thành n đoạn, mỗi đoạn lấy khung điểm cao nhất -> không bị trùng cảnh
    picks: list[dict] = []
    for k in range(n):
        lo, hi = dur * k / n, dur * (k + 1) / n
        group = [x for x in scored if lo <= x[1] < hi]
        if group:
            s, t = max(group)
            picks.append({"t": t, "score": round(s, 3)})
    picks.sort(key=lambda d: d["score"], reverse=True)
    cache.write_text(json.dumps(picks), encoding="utf-8")
    return picks


def _cover_crop(im, tw: int, th: int):
    """Phóng/cắt ảnh cho đầy khung, ưu tiên giữ phần trên-giữa nơi thường có mặt người."""
    import cv2

    h, w = im.shape[:2]
    s = max(tw / w, th / h)
    nw, nh = int(round(w * s)), int(round(h * s))
    r = cv2.resize(im, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    x0 = (nw - tw) // 2
    y0 = int((nh - th) * 0.3)
    return r[y0:y0 + th, x0:x0 + tw]


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit(draw, text: str, max_w: int, base: int, max_lines: int = 4):
    size = base
    while size > 24:
        font = _font(size)
        lines = _wrap(draw, text, font, max_w)
        if len(lines) <= max_lines and all(draw.textlength(ln, font=font) <= max_w for ln in lines):
            return font, lines, size
        size = int(size * 0.92)
    font = _font(size)
    return font, _wrap(draw, text, font, max_w)[:max_lines], size


def make_cover(job: Path, meta: dict, t: float, title: str, style: str = "noi-bat", aspect: str = "",
               hardsub_box: list[float] | None = None, out_name: str = "cover.jpg", color: str = "#FFB224") -> Path:
    """Dựng ảnh bìa tại mốc t với tiêu đề. aspect trống = theo tỉ lệ video gốc."""
    im = _frame_at(job, t)
    if im is None:
        raise RuntimeError("Không lấy được khung hình")
    if hardsub_box:
        from .clean import clean_frame
        im = clean_frame(im, hardsub_box)
    if aspect not in ASPECTS:
        aspect = "9:16" if int(meta.get("height") or 0) > int(meta.get("width") or 0) else "16:9"
    canvas = render_cover(im, title, style, aspect, color)
    out = job / out_name
    canvas.save(out, quality=92)
    (job / "cover.json").write_text(json.dumps({"t": t, "title": " ".join((title or "").split()).upper(), "style": style if style in STYLES else STYLES[0],
                                                "aspect": aspect, "color": color}, ensure_ascii=False), encoding="utf-8")
    return out


# chữ cần ghép nét (Thái, Ả Rập, Hindi, Khmer...) hoặc phông Segoe UI Black không có (Nhật, Hàn): Pillow ở đây không có bộ ghép chữ
# (raqm) nên vẽ sai thứ tự, sai dấu hoặc ra ô vuông. Những tiêu đề này vẽ bằng libass của ffmpeg (đã dùng cho phụ đề, đủ mọi chữ).
_COMPLEX = re.compile("[\u0590-\u06ff\u0750-\u077f\u0900-\u0dff\u0e00-\u0eff\u1000-\u109f\u1100-\u11ff\u1780-\u17ff"
                      "\u3040-\u30ff\u3130-\u318f\u4e00-\u9fff\uac00-\ud7af\ufb1d-\ufdff\ufe70-\ufeff]")


def needs_libass(text: str) -> bool:
    return bool(_COMPLEX.search(text or ""))


def _ass_color(hex_color: str) -> str:
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


_WIDE = re.compile("[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u4e00-\u9fff\uac00-\ud7af]")


def _break_lines(title: str, size: int, max_w: int) -> str:
    """Ngắt dòng bằng tay cho chữ không có dấu cách (Nhật, Trung...): libass chỉ tự xuống dòng ở dấu cách.
    Bề rộng ước lượng theo cỡ chữ ASS: chữ vuông khoảng 0,72 cỡ, chữ khác khoảng 0,4 cỡ, dấu ghép không chiếm chỗ."""
    import unicodedata

    def w(ch):
        return 0 if unicodedata.category(ch) in ("Mn", "Mc") else size * (0.72 if _WIDE.match(ch) else 0.4)
    lines, cur, cur_w = [], "", 0.0
    for tok in title.split(" "):
        tok_w = sum(w(c) for c in tok)
        sep = size * 0.25 if cur else 0
        if cur and cur_w + sep + tok_w <= max_w:
            cur, cur_w = cur + " " + tok, cur_w + sep + tok_w
            continue
        if cur:
            lines.append(cur)
            cur, cur_w = "", 0.0
        for ch in tok:      # từ dài hơn cả dòng: ngắt giữa các chữ
            if cur and cur_w + w(ch) > max_w:
                lines.append(cur)
                cur, cur_w = "", 0.0
            cur, cur_w = cur + ch, cur_w + w(ch)
    if cur:
        lines.append(cur)
    return "\\N".join(lines)


def _title_libass(canvas, title: str, style: str, color: str, tw: int, th: int):
    """Vẽ tiêu đề lên ảnh bằng libass (ffmpeg): tự ngắt dòng, tự lấy phông có chữ, ghép nét đúng, chữ phải sang trái đúng chiều."""
    import tempfile
    from PIL import Image

    from .util import ffmpeg
    short = min(tw, th)
    size = int(short * (0.165 if tw < th else 0.155))      # cỡ chữ ASS tính cả khoảng trên dưới: chữ hiện ra nhỏ hơn cỡ Pillow cùng số
    margin = int(short * 0.06)
    mv = int(th * (0.09 if tw < th else 0.08))
    if style == "dai-mau":       # dải màu sau chữ: hộp đặc màu nhấn, chữ tối (kiểu hộp của libass lấy màu viền làm màu hộp)
        st = f"{_ass_color('#14110C')},{_ass_color(color)},&H00000000,1,0,3,{max(4, size // 7)},0"
    elif style == "noi-bat":     # chữ màu nhấn viền đen dày
        st = f"{_ass_color(color)},&H00000000,&H00000000,1,0,1,{max(3, size // 12)},0"
    else:
        st = f"&H00FFFFFF,&H00000000,&H00000000,1,0,1,{max(2, size // 20)},0"
    ass = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {tw}", f"PlayResY: {th}", "WrapStyle: 0", "YCbCr Matrix: None", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV",
        f"Style: T,Segoe UI Black,{size},{st},1,{margin},{margin},{mv}", "", "[Events]", "Format: Layer, Start, End, Style, Text",
        "Dialogue: 0,0:00:00.00,0:00:01.00,T," + _break_lines(title.replace("\n", " ").replace("{", "(").replace("}", ")"), size, tw - 2 * margin),
    ])
    with tempfile.TemporaryDirectory(prefix="ic_cover_") as d:      # đường dẫn tạm không dấu: bộ lọc ass đọc đường dẫn theo cú pháp riêng
        d = Path(d)
        canvas.convert("RGB").save(d / "bg.png")
        (d / "t.ass").write_text(ass, encoding="utf-8-sig")
        # giữ RGB suốt đường đi: đổi sang YUV 4:2:0 làm lệch màu và nhòe nét chữ mảnh (Thái, Hindi)
        ffmpeg(["-i", "bg.png", "-vf", "format=rgb24,ass=t.ass", "-frames:v", 1, "-pix_fmt", "rgb24", "out.png"], cwd=d)
        return Image.open(d / "out.png").convert("RGB")


def render_cover(im, title: str, style: str = "noi-bat", aspect: str = "16:9", color: str = "#FFB224"):
    """Ảnh (BGR, numpy) -> ảnh bìa (PIL RGB) cỡ chuẩn của aspect, có tiêu đề lớn. Dùng cho video Studio và câu chuyện."""
    from PIL import Image, ImageDraw
    tw, th = ASPECTS.get(aspect, ASPECTS["16:9"])
    canvas = Image.fromarray(_cover_crop(im, tw, th)[:, :, ::-1]).convert("RGBA")
    title = " ".join((title or "").split()).upper()
    style = style if style in STYLES else STYLES[0]
    short = min(tw, th)
    margin = int(short * 0.06)
    complex_script = needs_libass(title)
    draw_probe = ImageDraw.Draw(canvas)
    font, lines, size = _fit(draw_probe, title, tw - 2 * margin, int(short * (0.125 if tw < th else 0.115)))
    lh = int(size * 1.22)
    block_h = lh * (3 if complex_script else len(lines))      # chữ libass tự ngắt dòng: dành chỗ cho khoảng 3 dòng
    if title:
        if style in ("noi-bat", "dai-mau"):      # lớp tối phía dưới để chữ nổi trên mọi nền
            grad_h = min(th, block_h + int(th * 0.28))
            alpha = np.linspace(0, 225, grad_h).astype(np.uint8)
            scrim = Image.fromarray(np.dstack([np.zeros((grad_h, tw, 3), np.uint8),
                                               np.tile(alpha[:, None], (1, tw))]), "RGBA")
            canvas.alpha_composite(scrim, (0, th - grad_h))
    if title and complex_script:
        return _title_libass(canvas, title, style, color, tw, th)
    draw = ImageDraw.Draw(canvas)
    base_y = th - block_h - int(th * (0.09 if tw < th else 0.08))
    stroke = max(2, size // 16)
    for i, ln in enumerate(lines):
        y = base_y + i * lh
        x = margin
        if style == "noi-bat":
            # dòng đầu đổi màu nhấn, các dòng sau chữ trắng viền đen
            fill = color if i == 0 else "#FFFFFF"
            draw.text((x, y), ln, font=font, fill=fill, stroke_width=stroke, stroke_fill="#000000")
        elif style == "dai-mau":
            # mỗi dòng nằm trên một dải màu, chữ tối
            w = int(draw.textlength(ln, font=font))
            pad = int(size * 0.22)
            draw.rectangle([x - pad // 2, y + int(size * 0.02), x + w + pad, y + int(size * 1.2)], fill=color)
            draw.text((x + pad // 4, y), ln, font=font, fill="#14110C")
        else:
            draw.text((x, y), ln, font=font, fill="#FFFFFF", stroke_width=max(1, stroke // 2), stroke_fill="#000000")
    return canvas.convert("RGB")
