"""Tự dò vùng phụ đề tiếng Trung in sẵn (hardsub) bằng OCR (RapidOCR, ONNX, chạy CPU).

Cách làm: lấy ~16 khung hình rải đều video -> OCR -> giữ các dòng chữ Hán -> gom theo vị trí dọc.
Dải phụ đề = dải xuất hiện ở nhiều khung VÀ nội dung thay đổi giữa các khung (loại tên kênh, logo,
watermark đứng yên). Kết quả lưu hardsub.json trong thư mục job.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .util import check_cancel, ffmpeg, imread, log, progress

import threading

_LOCK = threading.Lock()
CJK = re.compile(r"[一-鿿]")
_ENGINE = None


def available() -> bool:
    try:
        import rapidocr  # noqa: F401
        return True
    except ImportError:
        return False


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr import RapidOCR

        for name in ("RapidOCR", "rapidocr"):
            logging.getLogger(name).setLevel(logging.ERROR)
        # limit_type=max: không phóng to ảnh nhỏ (dải phụ đề 720x110 mặc định bị phóng lên ~4600x736 -> chậm 30 lần)
        _ENGINE = RapidOCR(params={"Det.limit_type": "max", "Det.limit_side_len": 960})
        for name in ("RapidOCR", "rapidocr"):
            logging.getLogger(name).setLevel(logging.ERROR)
    return _ENGINE


def grab_frame(src: Path, t: float, out: Path, width: int = 720) -> Path:
    ffmpeg(["-ss", f"{max(0.0, t):.3f}", "-i", src, "-frames:v", "1", "-vf", f"scale={width}:-2", "-strict", "unofficial", "-q:v", "3", out])
    return out


def _frames(src: Path, times: list[float], width: int = 720):
    """Sinh (i, ảnh BGR numpy) tại các mốc thời gian; đọc trực tiếp bằng OpenCV, lỗi thì dùng ffmpeg."""
    import cv2

    cap = cv2.VideoCapture(str(src))
    try:
        for i, t in enumerate(times):
            im = None
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
                ok, im = cap.read()
                if not ok:
                    im = None
            if im is None:
                tmp = src.parent / ".frames"
                tmp.mkdir(exist_ok=True)
                im = imread(grab_frame(src, t, tmp / f"f_{i:03d}.jpg", width))
            if im is None:
                continue
            h, w = im.shape[:2]
            if w > width:
                im = cv2.resize(im, (width, int(round(h * width / w))), interpolation=cv2.INTER_AREA)
            yield i, im
    finally:
        cap.release()


def _ocr_lines(im, min_score: float) -> list[dict]:
    h, w = im.shape[:2]
    with _LOCK:
        r = _engine()(im, use_cls=False)
    out = []
    if r is None or r.boxes is None:
        return out
    for box, txt, sc in zip(r.boxes, r.txts, r.scores):
        if float(sc) < min_score or len(CJK.findall(txt)) < 2:
            continue
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        out.append({"x0": float(min(xs)) / w, "x1": float(max(xs)) / w, "y0": float(min(ys)) / h,
                    "y1": float(max(ys)) / h, "text": str(txt)})
    return out


def _pct(vals: list[float], q: float) -> float:
    v = sorted(vals)
    return v[min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))]


def detect(job: Path, duration: float, n_frames: int = 16, min_score: float = 0.75, force: bool = False) -> dict:
    """Trả về {"box": [x, y, w, h] | None, "hits", "frames", "texts"} và lưu job/hardsub.json."""
    cache = job / "hardsub.json"
    if cache.exists() and not force:
        return json.loads(cache.read_text(encoding="utf-8"))
    if not available():
        raise RuntimeError("Chưa cài OCR: pip install rapidocr")
    lo, hi = min(1.0, duration * 0.05), max(duration - 1.0, duration * 0.95)
    times = [lo + (hi - lo) * (i + 0.5) / n_frames for i in range(n_frames)]
    found: list[dict] = []
    log("hardsub", f"Dò phụ đề gốc bằng OCR trên {n_frames} khung hình ...")
    for i, im in _frames(job / "source.mp4", times):
        check_cancel()
        lines = _ocr_lines(im, min_score)
        for ln in lines:
            ln["frame"] = i
        found += lines
        progress("hardsub", (i + 1) / n_frames)
    res = analyze(found, n_frames)
    cache.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if res["box"]:
        x, y, w, h = res["box"]
        log("hardsub", f"Thấy phụ đề gốc ở {res['hits']}/{n_frames} khung: x={x:.3f} y={y:.3f} w={w:.3f} h={h:.3f}")
    else:
        log("hardsub", "Không thấy phụ đề gốc in trong video")
    return res


def analyze(lines: list[dict], n_frames: int) -> dict:
    """Gom các dòng chữ theo tâm dọc; chọn dải có nhiều khung nhất mà chữ thay đổi."""
    lines = sorted(lines, key=lambda d: (d["y0"] + d["y1"]) / 2)
    clusters: list[list[dict]] = []
    for ln in lines:
        cy, hh = (ln["y0"] + ln["y1"]) / 2, ln["y1"] - ln["y0"]
        if clusters:
            c = clusters[-1]
            ccy = sum((d["y0"] + d["y1"]) / 2 for d in c) / len(c)
            if abs(cy - ccy) <= max(0.6 * hh, 0.015):
                c.append(ln)
                continue
        clusters.append([ln])

    def stats(c: list[dict]) -> tuple[int, int]:
        frames = {d["frame"] for d in c}
        texts = {re.sub(r"\W", "", d["text"]) for d in c}
        return len(frames), len(texts)

    best, best_score = None, 0.0
    for c in clusters:
        nf, nt = stats(c)
        if nf < max(2, round(n_frames * 0.2)) or nt < max(2, nf * 0.5):
            continue   # hiếm gặp hoặc chữ đứng yên (tên kênh, watermark)
        score = nf + nt * 0.5
        if score > best_score:
            best, best_score = c, score
    if not best:
        return {"box": None, "hits": 0, "frames": n_frames, "texts": []}

    # phụ đề 2 dòng: gộp cụm kề sát phía trên/dưới cũng có chữ thay đổi
    band = list(best)
    lh = _pct([d["y1"] - d["y0"] for d in best], 0.5)
    for c in clusters:
        if c is best:
            continue
        nf, nt = stats(c)
        if nf < 2 or nt < max(2, nf * 0.5):
            continue
        top, bot = min(d["y0"] for d in band), max(d["y1"] for d in band)
        ctop, cbot = _pct([d["y0"] for d in c], 0.5), _pct([d["y1"] for d in c], 0.5)
        if -0.6 * lh <= ctop - bot <= 0.6 * lh or -0.6 * lh <= top - cbot <= 0.6 * lh:
            band += c

    y0 = _pct([d["y0"] for d in band], 0.05)
    y1 = _pct([d["y1"] for d in band], 0.95)
    x0 = min(d["x0"] for d in band)
    x1 = max(d["x1"] for d in band)
    cx = (x0 + x1) / 2
    if abs(cx - 0.5) < 0.08:          # phụ đề căn giữa -> mở rộng đối xứng cho câu dài hơn
        half = max(0.5 - x0, x1 - 0.5) + 0.04
        x0, x1 = 0.5 - half, 0.5 + half
    else:
        x0, x1 = x0 - 0.03, x1 + 0.03
    pad = (y1 - y0) * 0.25 + 0.006
    y0, y1 = y0 - pad, y1 + pad
    x0, x1, y0, y1 = max(0.0, x0), min(1.0, x1), max(0.0, y0), min(1.0, y1)
    box = [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]
    texts = []
    for d in sorted(band, key=lambda d: d["frame"]):
        if d["text"] not in texts:
            texts.append(d["text"])
    return {"box": box, "hits": len({d["frame"] for d in band}), "frames": n_frames, "texts": texts[:30]}



def hardsub_mode(v) -> str:
    """edit.blur_hardsub có thể là bool hoặc chuỗi -> 'auto' | 'on' | 'off'."""
    if isinstance(v, str):
        v = v.strip().lower()
        if v == "auto":
            return "auto"
        return "on" if v in ("true", "on", "yes", "1") else "off"
    return "on" if v else "off"


def _sim(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    a, b = re.sub(r"\W", "", a), re.sub(r"\W", "", b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def ocr_timeline(job: Path, meta: dict, box: list[float], fps: int = 4) -> list[dict]:
    """Quét dải phụ đề gốc suốt video -> [{start, end, text}] (mỗi lần sub đổi = 1 câu). Lưu ocr_events.json.

    ffmpeg cắt sẵn dải phụ đề và đẩy qua pipe (nhanh); chỉ OCR khi "mặt nạ chữ sáng" trong dải thay đổi.
    """
    import subprocess

    import numpy as np

    from .util import find_ffmpeg

    cache = job / "ocr_events.json"
    key = {"box": [round(v, 4) for v in box], "fps": fps}
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("key") == key:
            return data["events"]
    W0, H0 = int(meta["width"]), int(meta["height"])
    x, y, w, h = box
    cw, ch = max(16, int(W0 * w) // 2 * 2), max(8, int(H0 * h) // 2 * 2)
    cx, cy = min(int(W0 * x), W0 - cw), min(int(H0 * y), H0 - ch)
    ow = min(720, cw)
    oh = max(8, int(round(ch * ow / cw / 2)) * 2)
    ff, _ = find_ffmpeg()
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-i", str(job / "source.mp4"), "-an", "-vf",
           f"fps={fps},crop={cw}:{ch}:{cx}:{cy},scale={ow}:{oh}", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    log("hardsub", "Quét phụ đề gốc theo thời gian (OCR) ...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = ow * oh * 3
    total = max(1, int(float(meta.get("duration") or 1) * fps))
    samples: list[tuple[float, str]] = []
    prev_mask, prev_txt, i, n_ocr = None, "", 0, 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            if i % 20 == 0:
                check_cancel()
                progress("hardsub", i / total)
            im = np.frombuffer(buf, np.uint8).reshape(oh, ow, 3)
            g = im.mean(axis=2)
            m = (g > 200).astype(np.float32)
            m = m[: oh // 4 * 4, : ow // 4 * 4].reshape(oh // 4, 4, ow // 4, 4).mean(axis=(1, 3))
            if prev_mask is not None:
                d = np.abs(m - prev_mask).mean() / max(m.mean(), prev_mask.mean(), 1e-4)
                if d < 0.25:                      # chữ không đổi -> dùng lại kết quả trước
                    samples.append((i / fps, prev_txt))
                    i += 1
                    continue
            prev_mask = m
            if m.mean() < 0.004:                  # gần như không có chữ sáng
                prev_txt = ""
            else:
                n_ocr += 1
                lines = sorted(_ocr_lines(np.ascontiguousarray(im), 0.6), key=lambda d: (round(d["y0"], 1), d["x0"]))
                prev_txt = "".join(d["text"] for d in lines).strip()
            samples.append((i / fps, prev_txt))
            i += 1
    finally:
        proc.kill()
        proc.wait()
    # gộp các mẫu liên tiếp giống nhau thành 1 câu
    events: list[dict] = []
    for t, txt in samples:
        if not txt:
            continue
        if events and t - events[-1]["end"] <= 1.0 / fps + 1e-6 and _sim(events[-1]["_last"], txt) >= 0.6:
            ev = events[-1]
            ev["end"] = t + 1.0 / fps
            ev["_last"] = txt
            ev["_texts"].append(txt)
        else:
            events.append({"start": t, "end": t + 1.0 / fps, "_last": txt, "_texts": [txt]})
    out = []
    for ev in events:
        if ev["end"] - ev["start"] < 0.3:
            continue
        texts = ev["_texts"]
        best = max(set(texts), key=lambda s: (texts.count(s), len(s)))   # bản đọc ổn định nhất
        out.append({"start": round(ev["start"], 2), "end": round(ev["end"], 2), "text": best})
    cache.write_text(json.dumps({"key": key, "events": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    log("hardsub", f"{len(out)} câu phụ đề gốc ({n_ocr} lần OCR / {len(samples)} khung)")
    return out
