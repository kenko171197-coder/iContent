"""Dựng video cuối bằng một lệnh ffmpeg: che sub cũ, lật, zoom, chỉnh màu, đổi khung, burn sub (4 kiểu),
watermark, logo, tốc độ, trộn tiếng (ducking: tự hạ nền khi giọng lồng nói) + nhạc nền riêng."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .editing import (LOOKS, audio_cut_filter, kept_duration, map_items, normalize_cuts, overlays_valid, scale_cuts,
                      split_tail, video_cut_filter)
from .models import Segment, auto_margin_v, style_font_size, write_ass, write_srt
from .util import FFMPEG_STALL_SECONDS, ROOT, ffmpeg, find_ffmpeg, log, probe, replace_file

ASPECTS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}


_NVENC: bool | None = None
_VIDEOTOOLBOX: bool | None = None


def nvenc_available() -> bool:
    """ffmpeg có h264_nvenc VÀ card thực sự chạy được (thử mã hóa 1 khung)."""
    global _NVENC
    if _NVENC is None:
        import subprocess

        try:
            ff, _ = find_ffmpeg()
            r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
                                "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True, timeout=30)
            _NVENC = r.returncode == 0
        except Exception:
            _NVENC = False
    return _NVENC


def videotoolbox_available() -> bool:
    """macOS: thử mã hóa phần cứng bằng Apple VideoToolbox (h264_videotoolbox)."""
    global _VIDEOTOOLBOX
    if os.name == "nt":
        return False
    if _VIDEOTOOLBOX is None:
        import subprocess
        import sys

        if sys.platform != "darwin":
            _VIDEOTOOLBOX = False
            return False
        try:
            ff, _ = find_ffmpeg()
            r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
                                "-c:v", "h264_videotoolbox", "-b:v", "2M", "-f", "null", "-"], capture_output=True, timeout=30)
            _VIDEOTOOLBOX = r.returncode == 0
        except Exception:
            _VIDEOTOOLBOX = False
    return _VIDEOTOOLBOX


def auto_encoder() -> str:
    if nvenc_available():
        return "h264_nvenc"
    if videotoolbox_available():
        return "h264_videotoolbox"
    return "libx264"


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def out_size(w: int, h: int, ecfg) -> tuple[int, int]:
    if ecfg.aspect in ASPECTS:
        tw, th = ASPECTS[ecfg.aspect]
        # không phóng to quá nguồn: giữ cạnh ngắn của khung đích <= cạnh ngắn nguồn (tối thiểu 720)
        scale = min(1.0, max(720, min(w, h)) / min(tw, th))
        return _even(tw * scale), _even(th * scale)
    return _even(w), _even(h)


def _bitrate_cap(limit: str, source: Path, duration: float) -> float:
    """Trần bitrate (Mbps): không vượt cấu hình, và không quá 1,3 lần video gốc vì nén lại không thêm được
    chi tiết nào; tối thiểu 3 Mbps để chữ phụ đề vẫn nét trên nguồn chất lượng thấp."""
    s = limit.upper().rstrip("B")
    top = float(s[:-1]) / (1000 if s[-1] == "K" else 1) if s[-1] in "KM" else float(s) / 1e6
    if duration > 0 and source.exists():
        src = source.stat().st_size * 8 / duration / 1e6
        top = min(top, max(3.0, src * 1.3))
    return top


def sub_items(segs: list[Segment], speed: float, use_trans: bool) -> list[tuple[float, float, str, float]]:
    """-> (start, end, text, speech_end) theo thời gian của video thành phẩm (đã chia cho speed)."""
    items = []
    for i, s in enumerate(segs):
        text = s.trans if use_trans else s.text
        if not text.strip():
            continue
        if use_trans and s.dub_start is not None:
            st, en = s.dub_start, max(s.dub_end or s.end, s.end)
            sp_en = s.dub_end or s.end
        else:
            st, en = s.start, s.end
            sp_en = s.end
        # không chồng lên câu sau
        nxt = next((x for x in segs[i + 1:] if (x.trans if use_trans else x.text).strip()), None)
        if nxt is not None:
            nst = nxt.dub_start if (use_trans and nxt.dub_start is not None) else nxt.start
            en = min(en, nst - 0.02)
        en = max(st + 0.3, en)
        items.append((st / speed, en / speed, text, min(sp_en, en) / speed))
    return items


def _num(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _card_info(path_str: str, seconds: float) -> dict | None:
    """Thông tin một đoạn intro/outro: video hay ảnh, dài bao nhiêu, có tiếng không. Thiếu file thì bỏ qua và báo."""
    p = Path(path_str)
    if not p.exists():
        log("render", f"Không thấy file {p.name} -> bỏ qua")
        return None
    if p.suffix.lower() in IMAGE_EXT:
        return {"path": p, "image": True, "dur": max(0.5, float(seconds)), "audio": False}
    info = probe(p)
    if not info["has_video"]:
        log("render", f"{p.name} không có hình -> bỏ qua")
        return None
    return {"path": p, "image": False, "dur": info["duration"], "audio": info["has_audio"]}


def valid_cube(p: Path) -> bool:
    """File .cube dùng được: có khai báo cỡ LUT 3D trong phần đầu, cỡ nằm trong giới hạn của ffmpeg."""
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for _, line in zip(range(60), f):
                parts = line.split()
                if len(parts) == 2 and parts[0].upper() == "LUT_3D_SIZE":
                    return 2 <= int(parts[1]) <= 256
    except (OSError, ValueError):
        return False
    return False


def _filter_path(p: Path) -> str:
    """Đường dẫn đặt trong tham số bộ lọc ffmpeg. Có hai lớp phân tích nên phải thoát hai lần: lớp giá trị tham số
    rồi lớp đồ thị bộ lọc. Dấu nháy trong tên thư mục (D:\\Tool's\\) không xử lý được bằng cách bọc trong nháy."""
    value = "".join("\\" + ch if ch in "\\:'" else ch for ch in p.as_posix())
    return "".join("\\" + ch if ch in "\\'[],;" else ch for ch in value)


def _reframe(job: Path, meta: dict, e, W: int, H: int, name: str) -> tuple[str, Path] | None:
    """Bộ lọc khung cắt đi theo nhân vật, hoặc None nếu không làm được thì để nơi gọi dùng cách đưa khung khác."""
    from . import vision

    if not vision.available():
        log("reframe", "Thiếu OpenCV hoặc model dò mặt -> dùng nền mờ")
        return None
    try:
        scan = vision.scan_faces(job, meta)
        times = vision.scenes(job)
    except Exception as ex:
        if type(ex).__name__ == "Cancelled":
            raise
        log("reframe", f"Không dò được khuôn mặt ({str(ex)[:120]}) -> dùng nền mờ")
        return None
    w, h = int(meta["width"]), int(meta["height"])
    plan = vision.reframe_plan(scan, times, float(meta.get("duration") or 0), w, h, W, H, pins=e.get("reframe_pins"),
                               flip=bool(e.flip), zoom=_num(e.zoom, 1.0))
    if plan is None:
        return None
    cmd = job / f"reframe_{Path(name).stem}.txt"
    first = vision.write_commands(plan, cmd, probe(job / "source.mp4")["fps"], w, h)
    log("reframe", f"Khung theo nhân vật: {len(plan['shots'])} cảnh, {plan['moves']} lần lia, {round(plan['face_ratio'] * 100)}% khung có mặt người")
    return vision.reframe_filter(plan, cmd.name, first, W, H), cmd


def render(job: Path, segs: list[Segment], meta: dict, cfg, dub: Path | None, bed: Path | None, bed_is_bgm: bool,
           hardsub_box: list[float] | None = None, clean_band: Path | None = None,
           out_name: str = "final.mp4", cuts: list | None = None, with_cards: bool = True) -> Path:
    """hardsub_box: vùng sub gốc cần che (None = không che). clean_band: dải sub đã xóa chữ (clean.py).
    cuts: đoạn bỏ đi, mặc định lấy từ edit.cuts. with_cards=False: không ghép intro/outro (khi xuất clip riêng)."""
    e, a = cfg.edit, cfg.audio
    started = time.time()
    w, h = int(meta["width"]), int(meta["height"])
    W, H = out_size(w, h, e)
    speed = float(e.speed or 1.0)
    duration = float(meta.get("duration") or 0)
    cuts = normalize_cuts(e.get("cuts") if cuts is None else cuts, duration)
    overlays = overlays_valid(e.get("overlays"))
    fade_in, fade_out = max(0.0, _num(e.get("fade_in"), 0.0)), max(0.0, _num(e.get("fade_out"), 0.0))
    card_s = _num(e.get("card_seconds"), 3.0)
    intro = _card_info(e.get("intro"), card_s) if with_cards and e.get("intro") else None
    outro = _card_info(e.get("outro"), card_s) if with_cards and e.get("outro") else None
    kept = kept_duration(cuts, duration) if duration else 0.0

    inputs: list[str] = ["-i", "source.mp4"]
    idx = 1
    bed_i = dub_i = logo_i = music_i = clean_i = None
    if clean_band is not None and hardsub_box:
        inputs += ["-i", clean_band.name]
        clean_i, idx = idx, idx + 1
    if bed is not None:
        inputs += ["-i", bed.name]
        bed_i, idx = idx, idx + 1
    if dub is not None:
        inputs += ["-i", dub.name]
        dub_i, idx = idx, idx + 1
    if e.logo:
        if Path(e.logo).exists():
            inputs += ["-i", str(Path(e.logo).resolve())]
            logo_i, idx = idx, idx + 1
        else:
            log("render", f"Không thấy file logo {Path(e.logo).name} -> bỏ qua")
    if a.get("music"):
        mp = Path(a.music)
        if mp.exists():
            skip = 0.0
            if a.get("music_skip_intro", True):
                from .highlights import music_offset
                skip = music_offset(mp)
                if skip:
                    log("render", f"Nhạc nền: bỏ {skip:.1f} giây mở đầu quá nhỏ")
            # lặp từ đầu file nhưng vào từ chỗ nhạc có tiếng: lặp lại lần sau vẫn đủ cả bài
            inputs += ["-stream_loop", "-1", *(["-ss", f"{skip:.2f}"] if skip else []), "-i", str(mp.resolve())]
            music_i, idx = idx, idx + 1
        else:
            log("render", f"Không thấy file nhạc {mp} — bỏ qua")

    # ---- ảnh trên video + intro/outro: mỗi cái một đầu vào
    image_ov: list[tuple[int, dict]] = []
    for o in overlays:
        if o["type"] == "image":
            ip = Path(o["path"])
            if not ip.exists():
                log("render", f"Không thấy ảnh {ip.name} -> bỏ qua lớp này")
                continue
            inputs += ["-i", str(ip.resolve())]
            image_ov.append((idx, o))
            idx += 1
    for card in (intro, outro):
        if card:
            if card["image"]:
                inputs += ["-loop", "1", "-framerate", "30", "-t", f"{card['dur']:.3f}", "-i", str(card["path"].resolve())]
            else:
                inputs += ["-i", str(card["path"].resolve())]
            card["i"] = idx
            idx += 1

    vf: list[str] = []
    cur = "[0:v]"

    def step(filt: str) -> None:
        nonlocal cur
        tag = f"[v{len(vf)}]"
        vf.append(f"{cur}{filt}{tag}")
        cur = tag

    if clean_i is not None:
        from .clean import band_rect
        _, _, bx, by = band_rect(meta, hardsub_box)
        n = len(vf)
        vf.append(f"{cur}[{clean_i}:v]overlay={bx}:{by}:eof_action=pass[cl{n}]")
        cur = f"[cl{n}]"
    elif hardsub_box:
        x, y, bw, bh = hardsub_box
        bx, by = _even(w * x), _even(h * y)
        bwp, bhp = min(_even(w * bw), w - bx), min(_even(h * bh), h - by)
        if e.get("hardsub_mode") == "band":
            step(f"drawbox=x={bx}:y={by}:w={bwp}:h={bhp}:color=black@0.72:t=fill")
        else:
            n = len(vf)
            vf.append(f"{cur}split=2[hs{n}a][hs{n}b]")
            r = max(2, min(bwp, bhp) // 5)
            vf.append(f"[hs{n}b]crop={bwp}:{bhp}:{bx}:{by},boxblur={r}:3:{max(1, r // 2)}:3[hs{n}c]")
            vf.append(f"[hs{n}a][hs{n}c]overlay={bx}:{by}[hs{n}]")
            cur = f"[hs{n}]"
    if e.flip:
        step("hflip")
    z = float(e.zoom or 1.0)
    if z > 1.001:
        # cắt về đúng cỡ gốc: tính bằng iw/z thì làm tròn có thể hụt 1-2 điểm ảnh, khung cắt phía sau không còn lọt (zoom 1,02 từng làm hỏng cả lượt dựng)
        step(f"scale=iw*{z:.4f}:ih*{z:.4f},crop={w}:{h}")
    br, ct, sat = _num(e.get("brightness"), 0.0), _num(e.get("contrast"), 1.0), _num(e.get("saturation"), 1.0)
    if abs(br) > 1e-3 or abs(ct - 1) > 1e-3 or abs(sat - 1) > 1e-3:
        step(f"eq=brightness={br:.3f}:contrast={ct:.3f}:saturation={sat:.3f}")
    look = str(e.get("look") or "")
    if look in LOOKS:
        step(LOOKS[look])
    lut = Path(str(e.get("lut") or ""))
    if e.get("lut"):
        if valid_cube(lut):
            step(f"lut3d=file={_filter_path(lut.resolve())}")
        else:
            log("render", f"File màu {lut.name} không dùng được -> bỏ qua")
    fit = str(e.get("fit") or "blur")
    track = _reframe(job, meta, e, W, H, out_name) if e.aspect in ASPECTS and fit == "track" else None
    if e.aspect in ASPECTS and fit == "track" and not track:
        fit = "blur"
    if track:
        step(track[0])
    elif e.aspect in ASPECTS and fit == "crop":
        fx, fy = min(1.0, max(0.0, _num(e.get("focus_x"), 0.5))), min(1.0, max(0.0, _num(e.get("focus_y"), 0.5)))
        step(f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:(iw-{W})*{fx:.3f}:(ih-{H})*{fy:.3f}")
    elif e.aspect in ASPECTS and fit == "black":
        step(f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black")
    elif e.aspect in ASPECTS:
        n = len(vf)
        vf.append(f"{cur}split=2[ar{n}a][ar{n}b]")
        qw, qh = _even(W / 4), _even(H / 4)      # nền mờ làm ở 1/4 độ phân giải: nhìn như nhau, nhanh hơn nhiều
        vf.append(f"[ar{n}b]scale={qw}:{qh}:force_original_aspect_ratio=increase,crop={qw}:{qh},boxblur=8:2,"
                  f"scale={W}:{H}[ar{n}bg]")
        vf.append(f"[ar{n}a]scale={W}:{H}:force_original_aspect_ratio=decrease[ar{n}fg]")
        vf.append(f"[ar{n}bg][ar{n}fg]overlay=(W-w)/2:(H-h)/2[ar{n}]")
        cur = f"[ar{n}]"
    else:
        step(f"scale={W}:{H}")

    # phụ đề (thời gian đã chia cho speed -> burn sau bước đổi tốc độ)
    use_trans = any(s.trans.strip() for s in segs)
    items = sub_items(segs, speed, use_trans)
    cuts_out = scale_cuts(cuts, speed)                  # đoạn cắt theo thời gian sau khi đổi tốc độ
    intro_len = intro["dur"] if intro else 0.0
    srt_items = map_items(items, cuts_out)
    srt_tmp = job / f"{Path(out_name).stem}.srt.part"      # chỉ thay final.srt khi video dựng xong, xem đoạn ffmpeg bên dưới
    write_srt(srt_tmp, [(i[0] + intro_len, i[1] + intro_len, i[2]) for i in srt_items])
    if abs(speed - 1.0) > 1e-3:
        step(f"setpts=PTS/{speed:.4f}")
    has_mark = bool((e.get("watermark_text") or "").strip())
    has_text_ov = any(o["type"] == "text" for o in overlays)
    margin_v = None
    fs = style_font_size(W, H, e)
    sub_y = e.get("sub_y")
    if sub_y not in (None, ""):
        # vị trí người dùng kéo trong Studio: tâm dòng chữ theo tỉ lệ chiều cao khung
        margin_v = max(0, min(H - fs, int(H * (1.0 - _num(sub_y, 0.8)) - fs / 2)))
    elif hardsub_box and e.subs_over_hardsub and e.aspect not in ASPECTS and float(e.zoom or 1) <= 1.001:
        # đặt phụ đề mới vào giữa vùng sub gốc đã che (khung hình không đổi nên toạ độ giữ nguyên)
        _, by_, _, bh_ = hardsub_box
        margin_v = max(0, int(H - (by_ + bh_) * H + (bh_ * H - fs) / 2))
    margin_v_used = margin_v
    if (e.burn_subs and items) or has_mark or has_text_ov:
        write_ass(job / "subs.ass", items if e.burn_subs else [], W, H, e, margin_v, total=duration / speed,
                  overlays=overlays, speed=speed)
        fd = ""
        if e.fontsdir:
            rel = Path(e.fontsdir)
            fdir = rel if rel.is_absolute() else ROOT / rel
            fd = ":fontsdir=" + _filter_path(fdir)
        step(f"ass=subs.ass{fd}")
    if logo_i is not None:
        lw = _even(W * float(e.logo_scale))
        m = _even(min(W, H) * 0.03)
        pos = {
            "top-left": f"{m}:{m}", "top-right": f"W-w-{m}:{m}",
            "bottom-left": f"{m}:H-h-{m}", "bottom-right": f"W-w-{m}:H-h-{m}",
        }.get(e.logo_pos, f"W-w-{m}:{m}")
        vf.append(f"[{logo_i}:v]scale={lw}:-1[lg]")
        n = len(vf)
        vf.append(f"{cur}[lg]overlay={pos}[lo{n}]")
        cur = f"[lo{n}]"
    for k, (ii, o) in enumerate(image_ov):
        iw = _even(W * float(o["size"]))
        op = min(1.0, max(0.0, _num(o.get("opacity"), 1.0)))
        alpha = f",colorchannelmixer=aa={op:.3f}" if op < 0.999 else ""
        st, en = float(o["start"]) / speed, float(o["end"]) / speed
        vf.append(f"[{ii}:v]format=rgba,scale={iw}:-2{alpha}[ovi{k}]")
        n = len(vf)
        vf.append(f"{cur}[ovi{k}]overlay=x={float(o['x']) * W:.1f}-overlay_w/2:y={float(o['y']) * H:.1f}-overlay_h/2:"
                  f"enable='between(t,{st:.3f},{en:.3f})'[ov{n}]")
        cur = f"[ov{n}]"
    step("format=yuv420p")
    body_dur = (kept / speed) if duration else 0.0
    inner_cuts, last_keep = split_tail(cuts_out, duration / speed if duration else 0.0)
    if cuts:
        step(video_cut_filter(inner_cuts, last_keep))
    if fade_in > 0:
        step(f"fade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0 and body_dur:
        step(f"fade=t=out:st={max(0.0, body_dur - fade_out):.3f}:d={fade_out:.3f}")
    vout = cur

    # ---- audio
    af: list[str] = []
    mix_in: list[str] = []
    duck = bool(a.get("duck", True)) and dub_i is not None
    if dub_i is not None:
        af.append(f"[{dub_i}:a]aresample=48000,volume={a.dub_volume}" + (",asplit=3[dub][dsc1][dsc2]" if duck else "[dub]"))
    if bed_i is not None:
        vol = a.bgm_volume if bed_is_bgm else (a.original_volume if dub_i is not None else 1.0)
        af.append(f"[{bed_i}:a]aresample=48000,volume={vol}[bed0]")
        if duck:
            # nền đã tách nhạc: hạ nhẹ (~9 dB); nền là tiếng gốc còn giọng Trung: hạ mạnh (~15 dB)
            ratio, thr = (2.5, 0.02) if bed_is_bgm else (8, 0.015)
            af.append(f"[bed0][dsc1]sidechaincompress=threshold={thr}:ratio={ratio}:attack=15:release=350[bed]")
        else:
            af.append("[bed0]anull[bed]")
        mix_in.append("[bed]")
    elif duck:
        af.append("[dsc1]anullsink")
    if music_i is not None:
        af.append(f"[{music_i}:a]aresample=48000,volume={_num(a.get('music_volume'), 0.12)}[mus0]")
        if duck:
            af.append("[mus0][dsc2]sidechaincompress=threshold=0.02:ratio=3:attack=15:release=400[mus]")
        else:
            af.append("[mus0]anull[mus]")
        mix_in.append("[mus]")
    elif duck:
        af.append("[dsc2]anullsink")
    if dub_i is not None:
        mix_in.append("[dub]")
    aout = None
    if mix_in:
        if len(mix_in) > 1:
            # duration=first: theo độ dài nền (= video); nếu không có nền thì theo giọng lồng
            af.append(f"{''.join(mix_in)}amix=inputs={len(mix_in)}:duration=first:normalize=0[mx]")
            last = "[mx]"
        else:
            last = mix_in[0]
        chain = []
        if abs(speed - 1.0) > 1e-3:
            chain.append(f"atempo={speed:.4f}")
        if body_dur:
            chain.append(f"atrim=end={last_keep:.3f}")     # nhạc lặp, giọng lồng dài hơn: cắt theo độ dài video
        if inner_cuts:
            chain.append(audio_cut_filter(inner_cuts))
        if fade_in > 0:
            chain.append(f"afade=t=in:st=0:d={fade_in:.3f}")
        if fade_out > 0 and body_dur:
            chain.append(f"afade=t=out:st={max(0.0, body_dur - fade_out):.3f}:d={fade_out:.3f}")
        cards = bool(intro or outro)
        if a.loudnorm and not cards:
            chain.append("loudnorm=I=-14:TP=-1.5:LRA=11")
        if chain:
            af.append(f"{last}{','.join(chain)}[aout]")
            aout = "[aout]"
        else:
            aout = last

    # ---- ghép intro/outro ngay trong lệnh này, không mã hóa hai lần
    if intro or outro:
        fps = probe(job / "source.mp4")["fps"]
        parts: list[tuple[str, str]] = []

        def card_part(card: dict, tag: str) -> tuple[str, str]:
            vf.append(f"[{card['i']}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,"
                      f"setsar=1,fps={fps:.3f},format=yuv420p,trim=duration={card['dur']:.3f},setpts=PTS-STARTPTS[cv{tag}]")
            if card["audio"]:
                af.append(f"[{card['i']}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=duration={card['dur']:.3f},asetpts=PTS-STARTPTS[ca{tag}]")
            else:
                af.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={card['dur']:.3f}[ca{tag}]")
            return f"[cv{tag}]", f"[ca{tag}]"

        if intro:
            parts.append(card_part(intro, "i"))
        vf.append(f"{vout}setsar=1,fps={fps:.3f}[vbody]")
        if aout:
            af.append(f"{aout}aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[abody]")
        else:
            af.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={body_dur:.3f}[abody]")
        parts.append(("[vbody]", "[abody]"))
        if outro:
            parts.append(card_part(outro, "o"))
        vf.append("".join(v + x for v, x in parts) + f"concat=n={len(parts)}:v=1:a=1[vcat][acat]")
        vout = "[vcat]"
        if a.loudnorm:
            af.append("[acat]loudnorm=I=-14:TP=-1.5:LRA=11[aout2]")
            aout = "[aout2]"
        else:
            aout = "[acat]"

    graph = ";".join(vf + af)
    (job / "filter_graph.txt").write_text(graph, encoding="utf-8")  # để debug
    encoder = e.encoder
    if encoder == "auto":
        encoder = auto_encoder()
    enc = ["-c:v", encoder]
    if encoder == "libx264":
        enc += ["-crf", e.crf, "-preset", e.preset]
    elif "nvenc" in encoder:
        # NVENC cùng số CQ tốn bit hơn x264 ở cùng CRF -> cộng thêm để chất lượng và dung lượng tương đương
        enc += ["-rc", "vbr", "-cq", int(e.crf) + 3, "-preset", "p5", "-b:v", "0"]
    elif "videotoolbox" in encoder:
        enc += ["-q:v", "65", "-allow_sw", "1"]
    if e.max_bitrate:
        cap = _bitrate_cap(str(e.max_bitrate), job / "source.mp4", duration)
        enc += ["-maxrate", f"{cap:.2f}M", "-bufsize", f"{cap * 2:.2f}M"]
    args = [*inputs, "-filter_complex", graph, "-map", vout]
    if aout:
        args += ["-map", aout, "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    out_dur = (body_dur + intro_len + (outro["dur"] if outro else 0.0)) if duration else None
    if out_dur:
        args += ["-t", f"{out_dur + 1:.3f}"]     # bộ lọc đã tự kết thúc đúng lúc, đây chỉ là chốt an toàn
    tmp_name = f"{Path(out_name).stem}.part.mp4"       # hủy hoặc lỗi giữa chừng không được phá bản đang tốt
    args += [*enc, "-movflags", "+faststart", tmp_name]
    style = e.get("sub_style") or "classic"
    how = ", đã xóa sub gốc" if clean_i is not None else ", che sub gốc" if hardsub_box else ""
    extras = "".join([f", cắt {len(cuts)} đoạn" if cuts else "", f", {len(overlays)} lớp phủ" if overlays else "",
                      f", màu {look}" if look in LOOKS else "", ", có intro" if intro else "", ", có outro" if outro else ""])
    log("render", f"Render {W}x{H}, {encoder}, phụ đề {style if e.burn_subs else 'tắt'}"
                  f"{how}{', speed ' + str(speed) if speed != 1 else ''}{extras} ...")
    # đoạn cắt dài: ffmpeg đang giải mã rồi bỏ khung, không có khung ra nên nhìn như đứng yên. Tính dư cho máy yếu (1x)
    stall = FFMPEG_STALL_SECONDS + (max((b - a for a, b in cuts_out), default=0.0))
    try:
        ffmpeg(args, cwd=job, progress_stage="render", total=out_dur, stall_seconds=stall)
        replace_file(job / tmp_name, job / out_name)
        replace_file(srt_tmp, job / "final.srt")
        if out_name in ("final.mp4", "editor_base.mp4"):
            # thời điểm của bản dựng tính từ lúc bắt đầu: sửa gì trong lúc đang dựng thì bản này vẫn được coi là cũ
            os.utime(job / out_name, (started, started))
    finally:
        (job / tmp_name).unlink(missing_ok=True)
        srt_tmp.unlink(missing_ok=True)
        if track:
            track[1].unlink(missing_ok=True)
    if out_name in ("final.mp4", "editor_base.mp4"):     # Studio cần biết bản đã dựng được cắt thế nào để khớp thời gian với video gốc
        bottom = H - (margin_v_used if margin_v_used is not None else auto_margin_v(W, H, e))
        # bản nền cho trình dựng không ghi phụ đề, nhưng trình dựng vẫn cần cỡ chữ và vị trí để đặt track phụ đề cho khớp
        with_sub = bool(items) and (e.burn_subs or out_name != "final.mp4")
        (job / ("render.json" if out_name == "final.mp4" else "editor_base.render.json")).write_text(json.dumps({
            "cuts": cuts, "speed": speed, "intro": intro_len, "outro": outro["dur"] if outro else 0.0, "out_dur": out_dur, "fade_in": fade_in, "fade_out": fade_out,
            "sub": {"w": W, "h": H, "fs": fs, "bottom": bottom, "one_line": (e.get("sub_style") or "classic") in ("tiktok", "pop")} if with_sub else None,
        }, ensure_ascii=False), encoding="utf-8")
    return job / out_name
