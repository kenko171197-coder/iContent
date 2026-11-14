"""Kiểm định thành phẩm: đo trên chính file video đã xuất, không đoán từ cấu hình.

  Tệp        có đủ hình và tiếng, định dạng phát được ở mọi nơi, độ dài đúng như đã dựng, hình và tiếng dài bằng nhau
  Hình       đoạn đen, đoạn đứng hình
  Tiếng      đoạn câm, độ to (LUFS), đỉnh tiếng (có vỡ tiếng không)
  Nội dung   phụ đề che mặt người, còn sót chữ Trung trên hình

Mọi kết quả đều có mốc thời gian để bấm tới xem. Các phép dựa trên nhận dạng ảnh chỉ là ước lượng và được ghi rõ như vậy.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .models import read_srt, style_font_size
from .util import check_cancel, find_ffmpeg, log, run_lines

TARGET_LUFS = -14.0
BLACK_MIN, FREEZE_MIN, SILENCE_MIN = 0.4, 3.0, 1.5
PENALTY = {"bad": 25, "warn": 8, "info": 0, "ok": 0}
VERSION = 2


# --------------------------------------------------------------------------- đo

_NUM = r"(-?[0-9.]+|-?inf|nan)"


def _f(s: str) -> float | None:
    try:
        v = float(s)
    except ValueError:
        return None
    return None if v != v or v in (float("inf"), float("-inf")) else v


def parse_log(text: str) -> dict:
    """Đọc nhật ký của các bộ lọc đo. Tách riêng để kiểm thử được mà không cần chạy ffmpeg."""
    num = r"(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)"      # ffmpeg có khi in 2.08333e-05
    black = [(float(a), float(b)) for a, b in re.findall(rf"black_start:{num} black_end:{num}", text)]
    freeze: list[list[float]] = []
    for kind, val in re.findall(rf"freezedetect\.freeze_(start|end): ?{num}", text):
        if kind == "start":
            freeze.append([float(val), None])
        elif freeze and freeze[-1][1] is None:
            freeze[-1][1] = float(val)
    silence: list[list[float]] = []
    for kind, val in re.findall(rf"silence_(start|end): ?{num}", text):
        if kind == "start":
            silence.append([max(0.0, float(val)), None])
        elif silence and silence[-1][1] is None:
            silence[-1][1] = float(val)
    # ebur128 in bảng tóm tắt ở cuối, lấy lần xuất hiện cuối cùng
    block = text[text.rfind("Summary:"):] if "Summary:" in text else ""
    m_i = re.search(rf"I:\s*{_NUM} LUFS", block)
    m_lra = re.search(rf"LRA:\s*{_NUM} LU", block)
    m_tp = re.search(rf"Peak:\s*{_NUM} dBFS", block)
    return {
        "black": black, "freeze": freeze, "silence": silence,
        "lufs": _f(m_i.group(1)) if m_i else None, "lra": _f(m_lra.group(1)) if m_lra else None, "peak": _f(m_tp.group(1)) if m_tp else None,
    }


def measure(path: Path, timeout_scale: float = 1.0) -> dict:
    """Một lượt giải mã toàn bộ file, thu nhỏ hình để nhanh. Các bộ lọc đo in kết quả vào nhật ký."""
    exe, _ = find_ffmpeg()
    cmd = [exe, "-hide_banner", "-nostdin", "-nostats", "-loglevel", "info", "-i", str(path), "-map", "0:v:0", "-map", "0:a:0?",
           "-vf", f"scale=320:-2,blackdetect=d={BLACK_MIN}:pix_th=0.10,freezedetect=n=-58dB:d={FREEZE_MIN},metadata=print:file=-",
           "-af", f"silencedetect=n=-45dB:d={SILENCE_MIN},ebur128=peak=true:framelog=quiet", "-f", "null", "-"]
    # ffmpeg lỗi thì báo lỗi: nếu không, kết quả rỗng sẽ được hiểu là video không có vấn đề gì
    lines = [ln for ln in run_lines(cmd) if any(k in ln for k in ("black_start", "freeze_", "silence_", "LUFS", "LRA:", "Peak:", "Summary:"))]
    return parse_log("".join(lines))


def _rate(s) -> float:
    """"30000/1001" -> 29,97. File hỏng hoặc không rõ thì 0."""
    try:
        a, _, b = str(s).partition("/")
        return float(a) / float(b or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def stream_info(path: Path) -> dict:
    _, exe = find_ffmpeg()
    r = subprocess.run([exe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"Không đọc được file video: {r.stderr[-200:]}")
    d = json.loads(r.stdout)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    with open(path, "rb") as f:
        head = f.read(1 << 16)
    moov, mdat = head.find(b"moov"), head.find(b"mdat")
    dur = float(d.get("format", {}).get("duration") or 0)
    return {
        "duration": dur, "size": int(d.get("format", {}).get("size") or path.stat().st_size),
        "video": {"codec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"), "w": int(v.get("width") or 0), "h": int(v.get("height") or 0),
                  "dur": float(v.get("duration") or dur), "fps": _rate(v.get("avg_frame_rate") or v.get("r_frame_rate"))} if v else None,
        "audio": {"codec": a.get("codec_name"), "dur": float(a.get("duration") or dur), "rate": int(a.get("sample_rate") or 0)} if a else None,
        "faststart": moov >= 0 and (mdat < 0 or moov < mdat),
    }


def _sample_times(items: list[float], n: int) -> list[float]:
    if len(items) <= n:
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def _wrapped_lines(text: str, fs: float, width: int, one_line: bool = False) -> int:
    """Ước lượng số dòng khi phụ đề tự xuống dòng, theo cùng công thức mà phần viết ASS dùng để ngắt cụm.
    Kiểu tiktok, pop hiện từng cụm vừa một dòng nên luôn là một dòng."""
    if one_line:
        return 1
    per_line = max(8.0, (width * 0.88) / (fs * 0.56))
    return max(1, int(len(text) / per_line + 0.999))


def scan_subs_over_faces(path: Path, srt: Path, sub: dict, count: int = 24) -> dict:
    """Lấy khung ở giữa từng câu phụ đề, dò mặt, xem dải chữ có đè lên mặt không.
    Mặt bị chữ che nhiều có thể không dò ra, nên con số thật có thể cao hơn: chỉ dùng để cảnh báo."""
    from . import hardsub, vision

    if not vision.available() or not srt.exists() or not sub:
        return {"checked": 0, "hits": []}
    items = read_srt(srt)
    if not items:
        return {"checked": 0, "hits": []}
    picks = _sample_times(items, count)
    times = [(a + b) / 2 for a, b, _ in picks]
    W, H = int(sub["w"]), int(sub["h"])
    scan_w = min(480, W)
    scan_h = vision._even(H * scan_w / W)
    det = vision._detector(scan_w, scan_h)
    hits = []
    seen = 0
    import cv2
    for i, im in hardsub._frames(path, times, scan_w):
        check_cancel()
        seen += 1
        if im.shape[0] != scan_h or im.shape[1] != scan_w:
            im = cv2.resize(im, (scan_w, scan_h))
        n = _wrapped_lines(picks[i][2], sub["fs"], W, bool(sub.get("one_line")))
        y1 = sub["bottom"] / H
        y0 = y1 - n * 1.3 * sub["fs"] / H
        for f in vision.faces_in(det, im, scan_w, scan_h):
            fy0, fy1 = f[1] - f[3] / 2, f[1] + f[3] / 2
            over = max(0.0, min(fy1, y1) - max(fy0, y0)) / max(1e-6, f[3])
            if over >= 0.35 and f[4] >= 0.7:
                hits.append(round(times[i], 2))
                break
    return {"checked": seen, "hits": hits}      # số khung đọc được thật, không phải số khung định đọc


def scan_hanzi(path: Path, duration: float, count: int = 12) -> dict:
    """Đọc thử vài khung xem còn chữ Hán trên hình không: logo, tiêu đề gốc, hoặc sub gốc chưa xóa hết."""
    from . import hardsub

    if not hardsub.available() or duration <= 0:
        return {"checked": 0, "hits": []}
    times = [round(duration * (i + 0.5) / count, 2) for i in range(count)]
    hits = []
    seen = 0
    for i, im in hardsub._frames(path, times, 720):
        check_cancel()
        seen += 1
        for ln in hardsub._ocr_lines(im, 0.8):
            hits.append({"t": times[i], "text": ln["text"][:40], "y": round((ln["y0"] + ln["y1"]) / 2, 3)})
    return {"checked": seen, "hits": hits}


# --------------------------------------------------------------------------- chấm

def _spans(spans: list, fade_in: float, fade_out: float, total: float, intro: float = 0.0, outro: float = 0.0, edge: float = 0.05) -> list[list[float]]:
    """Chỉ xét phần thân video: mở đầu và kết thúc là ảnh tĩnh hoặc không tiếng là cố ý, mờ dần tính từ mép phần thân."""
    start, end = intro, total - outro
    out = []
    for a, b in spans:
        if b is None:
            b = total
        a, b = max(a, start), min(b, end)
        if b - a <= edge:
            continue
        if a <= start + fade_in + edge and b <= start + fade_in + 0.6:
            continue
        if total and a >= end - fade_out - 0.6 and b >= end - edge:
            continue
        out.append([round(a, 2), round(b, 2)])
    return out


def _fmt_s(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")


def evaluate(info: dict, m: dict, ctx: dict, faces: dict | None = None, hanzi: dict | None = None) -> dict:
    """info: stream_info. m: measure. ctx: {expected, fade_in, fade_out, dub}. Không đụng tới file, để kiểm thử dễ."""
    checks: list[dict] = []

    def add(cid: str, level: str, title: str, detail: str = "", at: list | None = None) -> None:
        checks.append({"id": cid, "level": level, "title": title, "detail": detail, "at": at or []})

    v, a = info.get("video"), info.get("audio")
    total = float(info.get("duration") or 0)
    if not v:
        add("file", "bad", "File không có hình")
    elif v["codec"] != "h264" or v["pix_fmt"] != "yuv420p":
        add("file", "warn", f"Định dạng {v['codec']} {v['pix_fmt']} có thể không phát được ở mọi nơi", "Nền tảng mạng xã hội chuộng H.264 và yuv420p")
    else:
        add("file", "ok", f"Định dạng chuẩn: H.264, {v['w']}×{v['h']}")
    if not a:
        add("audio", "bad" if ctx.get("dub") else "warn", "Video không có tiếng")
    if not info.get("faststart"):
        add("faststart", "warn", "File chưa tối ưu để phát ngay khi tải", "Xuất lại bằng Studio566 sẽ tự sửa")
    exp = ctx.get("expected")
    if exp:
        diff = abs(total - float(exp))
        if diff > 1.0:
            add("duration", "bad", f"Độ dài lệch {_fmt_s(diff)} giây so với bản dựng", f"Phải là {_fmt_s(exp)} giây, thực tế {_fmt_s(total)} giây. Hãy dựng lại.")
        elif diff > 0.3:
            add("duration", "warn", f"Độ dài lệch {_fmt_s(diff)} giây so với bản dựng")
        else:
            add("duration", "ok", f"Độ dài đúng như đã dựng ({_fmt_s(total)} giây)")
    if v and a:
        gap = abs(v["dur"] - a["dur"])
        if gap > 1.0:
            add("sync", "bad", f"Hình và tiếng dài lệch nhau {_fmt_s(gap)} giây")
        elif gap > 0.3:
            add("sync", "warn", f"Hình và tiếng dài lệch nhau {_fmt_s(gap)} giây")
        else:
            add("sync", "ok", "Hình và tiếng dài bằng nhau")

    fi, fo = float(ctx.get("fade_in") or 0), float(ctx.get("fade_out") or 0)
    cards = (float(ctx.get("intro") or 0), float(ctx.get("outro") or 0))
    black = _spans(m.get("black") or [], fi, fo, total, *cards)
    if black:
        # đoạn đen ngắn thường là nhịp chuyển cảnh của chính video gốc: chỉ ghi nhận, không trừ điểm
        longest_black = max(b - s for s, b in black)
        add("black", "warn" if longest_black >= 2 else "info", f"{len(black)} đoạn màn hình đen (dài nhất {_fmt_s(longest_black)} giây)",
            "Thường do đoạn cắt hoặc video gốc. Bấm mốc thời gian để xem.", [b[0] for b in black])
    else:
        add("black", "ok", "Không có đoạn màn hình đen")
    freeze = _spans(m.get("freeze") or [], fi, fo, total, *cards)
    if freeze:
        longest = max(b - s for s, b in freeze)
        add("freeze", "warn" if longest >= 6 else "info", f"{len(freeze)} đoạn hình đứng yên (dài nhất {_fmt_s(longest)} giây)",
            "Có thể là cảnh tĩnh của video gốc. Nếu không cố ý, hãy cắt bớt.", [b[0] for b in freeze])
    else:
        add("freeze", "ok", "Hình không bị đứng")
    if a:
        silence = _spans(m.get("silence") or [], fi, fo, total, *cards)
        long_silence = [s for s in silence if s[1] - s[0] >= 4]
        if long_silence:
            add("silence", "warn", f"{len(long_silence)} đoạn câm trên 4 giây", "Người xem dễ thoát ở đây. Có thể dùng Tự cắt khoảng lặng.", [s[0] for s in long_silence])
        elif silence:
            add("silence", "info", f"{len(silence)} khoảng lặng ngắn", "", [s[0] for s in silence])
        else:
            add("silence", "ok", "Không có đoạn câm")
        lufs, peak = m.get("lufs"), m.get("peak")
        if lufs is None:
            add("loud", "warn", "Không đo được độ to của tiếng")
        else:
            off = lufs - TARGET_LUFS
            txt = f"{_fmt_s(lufs)} LUFS"
            if abs(off) <= 2:
                add("loud", "ok", f"Độ to chuẩn mạng xã hội ({txt})")
            elif abs(off) <= 4:
                add("loud", "warn", f"Tiếng hơi {'to' if off > 0 else 'nhỏ'} ({txt})", f"Chuẩn phổ biến khoảng {TARGET_LUFS:.0f} LUFS. Bật Chuẩn hóa âm lượng trong tab Tiếng.")
            else:
                add("loud", "bad", f"Tiếng quá {'to' if off > 0 else 'nhỏ'} ({txt})", f"Chuẩn phổ biến khoảng {TARGET_LUFS:.0f} LUFS. Bật Chuẩn hóa âm lượng trong tab Tiếng.")
        if peak is not None:
            if peak >= -0.1:
                add("peak", "bad", f"Tiếng bị vỡ (đỉnh {_fmt_s(peak)} dB)", "Giảm âm lượng giọng lồng hoặc bật Chuẩn hóa âm lượng")
            elif peak > -1.0:
                add("peak", "warn", f"Đỉnh tiếng sát ngưỡng ({_fmt_s(peak)} dB)", "Nền tảng nén lại có thể làm vỡ tiếng. Nên để dưới -1 dB.")
            else:
                add("peak", "ok", f"Đỉnh tiếng an toàn ({_fmt_s(peak)} dB)")
    if faces and faces.get("checked"):
        hits, n = faces.get("hits") or [], faces["checked"]
        if len(hits) >= max(2, n * 0.3):
            add("faces", "warn", f"Phụ đề có vẻ che mặt người ở {len(hits)}/{n} câu kiểm tra", "Ước lượng bằng nhận dạng khuôn mặt. Kéo phụ đề xuống thấp hơn trong chế độ Xem trước.", hits)
        elif hits:
            add("faces", "info", f"Phụ đề đè lên mặt người ở {len(hits)}/{n} câu kiểm tra", "Ước lượng bằng nhận dạng khuôn mặt.", hits)
        else:
            add("faces", "ok", f"Phụ đề không che mặt người ({n} câu kiểm tra)")
    if hanzi and hanzi.get("checked"):
        hits, n = hanzi.get("hits") or [], hanzi["checked"]
        frames = sorted({h["t"] for h in hits})
        if frames:
            sample = "; ".join(list(dict.fromkeys(h["text"][:16] for h in hits))[:3])
            add("hanzi", "warn" if len(frames) >= n * 0.25 else "info", f"Còn chữ Trung trên hình ở {len(frames)}/{n} khung kiểm tra",
                f"Đọc được: {sample}. Có thể là logo hoặc tiêu đề gốc.", frames)
        else:
            add("hanzi", "ok", f"Không còn chữ Trung trên hình ({n} khung kiểm tra)")

    score = 100
    for c in checks:
        score -= PENALTY.get(c["level"], 0)
    order = {"bad": 0, "warn": 1, "info": 2, "ok": 3}
    checks.sort(key=lambda c: order.get(c["level"], 9))
    return {"score": max(0, score), "checks": checks,
            "stats": {"duration": total, "size": info.get("size"), "lufs": m.get("lufs"), "peak": m.get("peak"), "lra": m.get("lra")}}


# --------------------------------------------------------------------------- chạy cho một video

def _key(path: Path) -> str:
    s = path.stat()
    return f"{VERSION}:{s.st_size}:{int(s.st_mtime)}"


def cached(job: Path) -> dict | None:
    """Kết quả đã lưu, kèm fresh=False nếu video đã được dựng lại sau đó."""
    f, q = job / "final.mp4", job / "qc.json"
    if not (f.exists() and q.exists()):
        return None
    try:
        d = json.loads(q.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    d["fresh"] = d.get("key") == _key(f)
    return d


def run(job: Path, cfg, deep: bool = True) -> dict:
    """Kiểm định final.mp4 rồi lưu qc.json."""
    path = job / "final.mp4"
    if not path.exists():
        raise FileNotFoundError("Chưa có video thành phẩm")
    log("qc", "Đang kiểm định thành phẩm ...")
    key = _key(path)      # lấy trước khi đo: video bị dựng lại trong lúc đo thì kết quả này phải bị coi là cũ
    rendered = {}
    if (job / "render.json").exists():
        try:
            rendered = json.loads((job / "render.json").read_text(encoding="utf-8"))
        except ValueError:
            rendered = {}
    info = stream_info(path)
    m = measure(path)
    faces = hanzi = None
    if deep:
        try:
            faces = scan_subs_over_faces(path, job / "final.srt", rendered.get("sub") or {})
        except Exception as e:      # phép phụ: lỗi thì bỏ qua phép này, không mất các kết quả khác
            if type(e).__name__ == "Cancelled":
                raise
            log("qc", f"Bỏ qua kiểm tra phụ đề che mặt: {str(e)[:120]}")
        try:
            # video tiếng Nhật: phụ đề mới có chữ Hán là đúng, dò chữ Trung trên hình sẽ báo nhầm
            hanzi = scan_hanzi(path, info["duration"]) if cfg.translate.target_lang != "ja" else None
        except Exception as e:
            if type(e).__name__ == "Cancelled":
                raise
            log("qc", f"Bỏ qua kiểm tra chữ Trung: {str(e)[:120]}")
    ctx = {"expected": rendered.get("out_dur"), "fade_in": rendered.get("fade_in"), "fade_out": rendered.get("fade_out"),
           "intro": rendered.get("intro"), "outro": rendered.get("outro"),
           "dub": (job / "dub.wav").exists() and bool(cfg.tts.enabled)}
    res = evaluate(info, m, ctx, faces, hanzi)
    res["key"] = key
    (job / "qc.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    bad = sum(c["level"] in ("bad", "warn") for c in res["checks"])
    log("qc", f"Điểm thành phẩm {res['score']}/100, {bad} mục cần xem")
    res["fresh"] = key == _key(path)
    return res


def check_file(path: Path, ctx: dict | None = None) -> dict:
    """Kiểm định một file bất kỳ, không có thông tin về cách dựng. Không dò phụ đề che mặt vì không biết phụ đề nằm đâu."""
    info = stream_info(path)
    if path.suffix.lower() not in (".mp4", ".mov", ".m4v"):
        info["faststart"] = True      # WebM, MKV không có hộp moov: phép đo này chỉ có nghĩa với MP4, MOV
    m = measure(path)
    hanzi = None
    # OpenCV không mở được đường dẫn có chữ tiếng Việt, khi đó việc chụp khung hình dùng tạm thư mục .frames cạnh video (ở đây là thư mục output)
    frames = path.parent / ".frames"
    had_frames = frames.exists()
    try:
        hanzi = scan_hanzi(path, info["duration"])
    except Exception as e:
        if type(e).__name__ == "Cancelled":
            raise
        log("qc", f"Bỏ qua kiểm tra chữ Trung: {str(e)[:120]}")
    finally:
        if not had_frames:
            shutil.rmtree(frames, ignore_errors=True)
    return evaluate(info, m, ctx or {}, None, hanzi)


__all__ = ["run", "cached", "check_file", "measure", "parse_log", "evaluate", "stream_info", "style_font_size"]
