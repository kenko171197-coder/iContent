"""Xóa hẳn sub gốc in trong video (hardsub_mode = inpaint) — không làm mờ cả dải.

Chỉ xử lý dải phụ đề rồi lưu thành clean_band.mp4; lúc dựng video chỉ cần overlay dải này lên video gốc,
nên phần hình còn lại không bị nén thêm một lần và xử lý rất nhanh.

Cách làm:
  1. Với mỗi câu sub gốc (ocr_events.json) lấy vài mẫu 4 khung/giây, OCR 1 lần để biết vùng chữ, rồi lấy mặt nạ
     nét chữ (top-hat: nét sáng, mảnh) giao qua các mẫu: chữ đứng yên còn nền thì chuyển động -> mặt nạ ổn định,
     ôm sát nét chữ, không nháy giữa các khung.
  2. Quét toàn bộ khung hình: khung nào thực sự có chữ của câu đó thì vá (inpaint) đúng mặt nạ ấy.
     Khung không có chữ được giữ nguyên, nên không làm hỏng hình ở những đoạn không có sub.
"""
from __future__ import annotations

import json
import os
import subprocess
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .util import check_cancel, find_ffmpeg, log, progress, short_hash

VERSION = "3"
SAMPLE_FPS = 4
MIN_COVERAGE = 0.55     # tỉ lệ nét của mặt nạ phải sáng trong khung để coi là khung đó đang có chữ


def band_rect(meta: dict, box: list[float]) -> tuple[int, int, int, int]:
    """Toạ độ pixel chẵn của dải sub trên video gốc: (rộng, cao, x, y)."""
    W, H = int(meta["width"]), int(meta["height"])
    x, y, w, h = box
    cx, cy = int(W * x) // 2 * 2, int(H * y) // 2 * 2
    cw = min(max(16, int(W * w) // 2 * 2), (W - cx) // 2 * 2)
    ch = min(max(8, int(H * h) // 2 * 2), (H - cy) // 2 * 2)
    return cw, ch, cx, cy


def _kernel(k: int):
    import cv2

    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def stroke_mask(band, text_h: int, region=None):
    """Mặt nạ nét chữ: nét sáng trên nền; nếu gần như không có thì thử nét tối (chữ đen).

    Lọc thêm theo màu: phụ đề thường một màu đồng nhất, còn vật sáng trên nền (hạt, đồ vật) thì không ->
    chỉ giữ điểm gần với màu của các nét nổi bật nhất. Nhờ vậy mặt nạ không ăn sang nền nhiều chi tiết.
    """
    import cv2

    g = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    k = max(9, int(text_h * 0.55)) | 1
    se = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    tophat = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, se)
    bright = (tophat > 45) & (g > 150)
    if region is not None:
        bright &= region > 0
    if bright.mean() < 0.004:
        blackhat = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, se)
        dark = (blackhat > 60) & (g < 90)
        return (dark if region is None else dark & (region > 0)).astype(np.uint8) * 255
    strong = bright & (tophat >= np.percentile(tophat[bright], 70))
    color = np.median(band[strong], axis=0)
    near = np.abs(band.astype(np.int16) - color).max(axis=2) < 50
    return (bright & near).astype(np.uint8) * 255


def _text_regions(band) -> tuple[object, int]:
    """OCR 1 lần -> (ảnh vùng chữ 0/255, chiều cao chữ). Không đọc được chữ -> cả dải."""
    import cv2

    from .hardsub import _ocr_lines

    h, w = band.shape[:2]
    lines = _ocr_lines(np.ascontiguousarray(band), 0.5)
    if not lines:
        return np.full((h, w), 255, np.uint8), h // 2
    tx_h = int(np.median([(d["y1"] - d["y0"]) * h for d in lines]))
    pad = max(4, tx_h // 6)
    reg = np.zeros((h, w), np.uint8)
    for d in lines:
        cv2.rectangle(reg, (max(0, int(d["x0"] * w) - pad), max(0, int(d["y0"] * h) - pad)),
                      (min(w - 1, int(d["x1"] * w) + pad), min(h - 1, int(d["y1"] * h) + pad)), 255, -1)
    return reg, tx_h


def event_mask(samples: list) -> tuple[object, object] | None:
    """Từ vài mẫu của 1 câu -> (lõi nét chữ để kiểm tra khung có chữ, mặt nạ đã nới để vá viền chữ)."""
    import cv2

    if not samples:
        return None
    mid = samples[len(samples) // 2]
    reg, tx_h = _text_regions(mid)
    single = stroke_mask(mid, tx_h, reg)
    core = single
    if len(samples) > 1:
        both = single.copy()
        for s in samples:
            both = cv2.bitwise_and(both, stroke_mask(s, tx_h, reg))
        # chữ có hiệu ứng / di chuyển thì phần giao quá ít -> dùng mặt nạ của mẫu giữa
        if both.sum() > 0.4 * single.sum():
            core = both
    if core.sum() == 0:
        return None
    # nới mặt nạ để gồm cả viền chữ: nới vừa phải + mọi điểm tối đứng yên sát nét chữ (viền đen dày mỏng tùy video)
    r, ring = max(2, tx_h // 13), max(4, tx_h // 6)
    near = cv2.dilate(core, _kernel(ring * 2 + 1)) > 0
    dark = near.copy()
    for s in samples:
        dark &= cv2.cvtColor(s, cv2.COLOR_BGR2GRAY) < 85
    full = cv2.bitwise_or(cv2.dilate(core, _kernel(r * 2 + 1)), dark.astype(np.uint8) * 255)
    return core, cv2.dilate(full, _kernel(5))


def inpaint_band(band, mask):
    """Vá vùng mask. Làm ở nửa độ phân giải cho nhanh, chỉ thay đúng các điểm trong mask (viền có feather)."""
    import cv2

    h, w = band.shape[:2]
    scale = 0.5 if w > 500 else 1.0
    small = cv2.resize(band, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else band
    ms = cv2.resize(mask, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST) if scale < 1 else mask
    fill = cv2.inpaint(small, ms, 4, cv2.INPAINT_TELEA)
    if scale < 1:
        fill = cv2.resize(fill, (w, h), interpolation=cv2.INTER_CUBIC)
    a = cv2.GaussianBlur(mask, (0, 0), 1.5).astype(np.float32)[..., None] / 255.0
    return (band * (1.0 - a) + fill * a).astype(np.uint8)


def clean_frame(im, box: list[float]):
    """Xóa sub gốc trên 1 ảnh (dùng cho ảnh bìa)."""
    h, w = im.shape[:2]
    cw, ch, cx, cy = band_rect({"width": w, "height": h}, box)
    band = im[cy:cy + ch, cx:cx + cw].copy()
    res = event_mask([band])
    if res is None:
        return im
    out = im.copy()
    out[cy:cy + ch, cx:cx + cw] = inpaint_band(band, res[1])
    return out


def _source_fps(job: Path) -> float:
    import cv2

    cap = cv2.VideoCapture(str(job / "source.mp4"))
    fps = cap.get(cv2.CAP_PROP_FPS) if cap.isOpened() else 0.0
    cap.release()
    return float(fps) if 1.0 <= fps <= 240.0 else 30.0


def _read_band_cmd(ff: str, job: Path, fps: float, rect: tuple[int, int, int, int]) -> list[str]:
    cw, ch, cx, cy = rect
    return [ff, "-hide_banner", "-loglevel", "error", "-i", str(job / "source.mp4"), "-an", "-vf",
            f"fps={fps:.5f},crop={cw}:{ch}:{cx}:{cy}", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]


def _build_masks(job: Path, ff: str, rect, events: list[dict], total_s: float) -> list:
    """Đọc dải sub 4 khung/giây -> mặt nạ từng câu (nén PNG để câu nhiều vẫn ít tốn RAM)."""
    import cv2

    cw, ch = rect[:2]
    size = cw * ch * 3
    masks: list = [None] * len(events)
    pool: list[list] = [[] for _ in events]
    proc = subprocess.Popen(_read_band_cmd(ff, job, SAMPLE_FPS, rect), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    i, ev = 0, 0

    def finish(k: int) -> None:
        res = event_mask(pool[k])
        pool[k] = []
        if res is not None:
            masks[k] = (cv2.imencode(".png", res[0])[1], cv2.imencode(".png", res[1])[1])

    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            t = i / SAMPLE_FPS
            i += 1
            if i % 20 == 0:
                check_cancel()
                progress("clean", 0.25 * min(1.0, t / max(1.0, total_s)))
            while ev < len(events) and t >= events[ev]["end"]:
                finish(ev)
                ev += 1
            if ev < len(events) and t >= events[ev]["start"] and len(pool[ev]) < 6:
                pool[ev].append(np.frombuffer(buf, np.uint8).reshape(ch, cw, 3).copy())
    finally:
        proc.kill()
        proc.wait()
    while ev < len(events):
        finish(ev)
        ev += 1
    return masks


def clean_video(job: Path, meta: dict, box: list[float], events: list[dict]) -> Path | None:
    """Tạo clean_band.mp4 (dải sub đã xóa chữ). Có cache. Không có câu sub nào -> None."""
    import cv2

    if not events:
        return None
    out, key_file = job / "clean_band.mp4", job / "clean.key"
    key = short_hash(VERSION, json.dumps([round(v, 4) for v in box]),
                     json.dumps([[e["start"], e["end"]] for e in events]))
    if out.exists() and key_file.exists() and key_file.read_text() == key:
        log("clean", "Dùng lại dải sub đã xóa (cache)")
        return out
    ff, _ = find_ffmpeg()
    rect = band_rect(meta, box)
    cw, ch = rect[:2]
    size = cw * ch * 3
    total_s = float(meta.get("duration") or 1)
    fps = _source_fps(job)
    log("clean", f"Xóa sub gốc: {len(events)} câu, dải {cw}x{ch} ...")
    masks = _build_masks(job, ff, rect, events, total_s)
    ok_events = [(e, m) for e, m in zip(events, masks) if m is not None]
    if not ok_events:
        log("clean", "Không tách được nét chữ -> dùng cách làm mờ")
        return None

    tmp = job / "clean_band.tmp.mp4"
    enc = subprocess.Popen(
        [ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{cw}x{ch}",
         "-r", f"{fps:.5f}", "-i", "pipe:0", "-an", "-c:v", "libx264", "-crf", "15", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", str(tmp)],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    dec = subprocess.Popen(_read_band_cmd(ff, job, fps, rect), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    decoded: dict[int, tuple] = {}

    def get_mask(k: int):
        if k not in decoded:
            if len(decoded) > 4:
                decoded.pop(next(iter(decoded)))
            core_png, full_png = ok_events[k][1]
            decoded[k] = (cv2.imdecode(core_png, cv2.IMREAD_GRAYSCALE) > 0,
                          cv2.imdecode(full_png, cv2.IMREAD_GRAYSCALE))
        return decoded[k]

    workers = max(2, min(6, (os.cpu_count() or 4) - 2))
    pending: deque = deque()
    n, first, n_fixed, total_frames = 0, 0, 0, max(1, int(total_s * fps))
    margin = 1.0 / SAMPLE_FPS + 0.05     # sub có thể bắt đầu/kết thúc lệch tối đa 1 mẫu so với OCR

    def flush(limit: int) -> None:
        while len(pending) > limit:
            head = pending.popleft()
            data = head.result() if hasattr(head, "result") else head
            enc.stdin.write(data.tobytes())

    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            while True:
                buf = dec.stdout.read(size)
                if len(buf) < size:
                    break
                t = n / fps
                n += 1
                if n % 30 == 0:
                    check_cancel()
                    progress("clean", 0.25 + 0.75 * min(1.0, n / total_frames))
                while first < len(ok_events) and ok_events[first][0]["end"] + margin < t:
                    first += 1
                band = np.frombuffer(buf, np.uint8).reshape(ch, cw, 3)
                best, best_cov = None, MIN_COVERAGE
                k = first
                g = None
                while k < len(ok_events) and ok_events[k][0]["start"] - margin <= t:
                    if g is None:
                        g = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
                    core, _ = get_mask(k)
                    cov = float((g[core] > 150).mean()) if core.any() else 0.0
                    if cov >= best_cov:
                        best, best_cov = k, cov
                    k += 1
                if best is None:
                    pending.append(band)
                else:
                    n_fixed += 1
                    pending.append(ex.submit(inpaint_band, band, get_mask(best)[1]))
                flush(workers * 2)
            flush(0)
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError("ffmpeg không ghi được clean_band.mp4")
        tmp.replace(out)
        key_file.write_text(key)
    finally:
        dec.kill()
        dec.wait()
        if enc.poll() is None:
            enc.kill()
            enc.wait()
        tmp.unlink(missing_ok=True)
    log("clean", f"Đã xóa sub gốc trên {n_fixed}/{n} khung hình")
    return out
