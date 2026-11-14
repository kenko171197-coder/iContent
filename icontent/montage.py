"""Ghép nhiều video/ảnh thành một video: tự đưa về cùng khung, cùng tốc độ khung, cùng định dạng tiếng, có chuyển cảnh.

Một lệnh ffmpeg, mỗi đoạn là một đầu vào riêng nên không tốn bộ nhớ như split. Dùng cho: ghép các video đã làm xong thành
bản tổng hợp, hoặc ghép nhiều file gốc rồi đưa vào Studio để dịch, lồng tiếng như một video.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .render import ASPECTS, IMAGE_EXT, _even, nvenc_available
from .util import ffmpeg, log, probe, replace_file, safe_name, stage

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".m4v", ".ts"}
TRANSITIONS = {"": "Không", "fade": "Mờ chồng", "fadeblack": "Tối dần", "slideleft": "Trượt sang trái", "wipeleft": "Quét sang trái", "circleopen": "Mở tròn", "dissolve": "Tan vào"}
IMAGE_SECONDS = 3.0
FPS = 30


def inspect(item: dict) -> dict:
    """Kiểm tra một đoạn ghép: file có thật, loại gì, dài bao nhiêu sau khi cắt đầu cuối."""
    p = Path(str(item.get("path") or ""))
    if not p.is_file():
        raise ValueError(f"Không thấy file: {p.name or '(trống)'}")
    ext = p.suffix.lower()
    if ext in IMAGE_EXT:
        dur = float(item.get("seconds") or IMAGE_SECONDS)
        if dur <= 0:
            raise ValueError(f"{p.name}: thời lượng ảnh phải lớn hơn 0")
        from PIL import Image, UnidentifiedImageError
        try:
            with Image.open(p) as im:
                w, h = im.size
        except (UnidentifiedImageError, OSError) as e:
            raise ValueError(f"{p.name}: không đọc được ảnh này") from e
        return {"path": p, "image": True, "start": 0.0, "dur": dur, "audio": False, "width": w, "height": h, "fps": FPS, "title": item.get("title") or p.stem}
    if ext not in VIDEO_EXT:
        raise ValueError(f"{p.name}: không hỗ trợ loại file này")
    try:
        info = probe(p)
    except RuntimeError as e:
        raise ValueError(f"{p.name}: không đọc được file video này, có thể file bị hỏng") from e
    if not info["has_video"]:
        raise ValueError(f"{p.name}: file không có hình")
    total = info["duration"]
    start = max(0.0, float(item.get("start") or 0))
    end = float(item.get("end") or 0) or total
    end = min(end, total) if total else end
    if end - start < 0.2:
        raise ValueError(f"{p.name}: đoạn chọn quá ngắn")
    return {"path": p, "image": False, "start": start, "dur": end - start, "audio": info["has_audio"], "width": info["width"], "height": info["height"],
            "fps": info["fps"], "title": item.get("title") or p.stem}


def target_size(clips: list[dict], aspect: str) -> tuple[int, int]:
    if aspect in ASPECTS:
        tw, th = ASPECTS[aspect]
        # không phóng to quá nguồn lớn nhất
        src = max(min(c["width"], c["height"]) for c in clips)
        k = min(1.0, max(720, src) / min(tw, th))
        return _even(tw * k), _even(th * k)
    w, h = clips[0]["width"], clips[0]["height"]
    k = min(1.0, 1920 / max(w, h))        # video đầu quá lớn thì giữ tối đa 1920
    return _even(w * k), _even(h * k)


def _hold(c: dict) -> str:
    """Hình ngắn hơn thời lượng đoạn thì giữ khung cuối, dài hơn thì cắt, để hình và tiếng luôn khớp nhau."""
    return f"tpad=stop_mode=clone:stop_duration={c['dur']:.3f},trim=duration={c['dur']:.3f},setpts=PTS-STARTPTS"


def build_graph(clips: list[dict], W: int, H: int, fit: str, transition: str, trans_dur: float, fps: int = FPS) -> tuple[str, str, str, float]:
    """-> (filter_complex, nhãn hình ra, nhãn tiếng ra, tổng thời lượng)."""
    vf: list[str] = []
    for i, c in enumerate(clips):
        src = f"[{i}:v]"
        if fit == "crop":
            vf.append(f"{src}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={fps},format=yuv420p,{_hold(c)}[v{i}]")
        elif fit == "black":
            vf.append(f"{src}scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps},format=yuv420p,{_hold(c)}[v{i}]")
        else:
            qw, qh = _even(W / 4), _even(H / 4)
            vf.append(f"{src}split=2[b{i}][f{i}]")
            vf.append(f"[b{i}]scale={qw}:{qh}:force_original_aspect_ratio=increase,crop={qw}:{qh},boxblur=8:2,scale={W}:{H}[bg{i}]")
            vf.append(f"[f{i}]scale={W}:{H}:force_original_aspect_ratio=decrease[fg{i}]")
            vf.append(f"[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={fps},format=yuv420p,{_hold(c)}[v{i}]")
    af = []
    for i, c in enumerate(clips):
        if c["audio"]:
            # tiếng ngắn hơn hình thì thêm im lặng, dài hơn thì cắt: nếu không chuyển cảnh sau sẽ lệch
            af.append(f"[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,"
                      f"apad=whole_dur={c['dur']:.3f},atrim=duration={c['dur']:.3f},asetpts=PTS-STARTPTS[a{i}]")
        else:
            af.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={c['dur']:.3f}[a{i}]")
    # không cho chuyển cảnh dài hơn nửa đoạn ngắn nhất
    t = min(max(0.0, trans_dur), min(c["dur"] for c in clips) / 2.01) if transition and len(clips) > 1 else 0.0
    if t < 0.05:
        graph = vf + af + ["".join(f"[v{i}][a{i}]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=1[vm][am]"]
        total = sum(c["dur"] for c in clips)
    else:
        graph = vf + af
        offset = 0.0
        vlast, alast = "[v0]", "[a0]"
        for i in range(1, len(clips)):
            offset += clips[i - 1]["dur"] - t
            graph.append(f"{vlast}[v{i}]xfade=transition={transition}:duration={t:.3f}:offset={offset:.3f}[x{i}]")
            graph.append(f"{alast}[a{i}]acrossfade=d={t:.3f}:c1=tri:c2=tri[ax{i}]")
            vlast, alast = f"[x{i}]", f"[ax{i}]"
        graph.append(f"{vlast}null[vm]")
        graph.append(f"{alast}anull[am]")
        total = sum(c["dur"] for c in clips) - t * (len(clips) - 1)
    return ";".join(graph), "[vm]", "[am]", total


def merge(items: list[dict], out: Path, aspect: str = "", fit: str = "blur", transition: str = "", trans_dur: float = 0.5,
          loudnorm: bool = True, crf: int = 23) -> dict:
    if len(items) < 1:
        raise ValueError("Chưa có video nào để ghép")
    if transition and transition not in TRANSITIONS:
        raise ValueError("Kiểu chuyển cảnh không hợp lệ")
    stage("merge")
    clips = [inspect(i) for i in items]
    W, H = target_size(clips, aspect)
    graph, vout, aout, total = build_graph(clips, W, H, fit, transition, trans_dur)
    if loudnorm:
        graph += f";{aout}loudnorm=I=-14:TP=-1.5:LRA=11[an]"
        aout = "[an]"
    inputs: list = []
    for c in clips:
        if c["image"]:
            inputs += ["-loop", 1, "-framerate", FPS, "-t", f"{c['dur']:.3f}", "-i", str(c["path"].resolve())]
        else:
            inputs += ["-ss", f"{c['start']:.3f}", "-t", f"{c['dur']:.3f}", "-i", str(c["path"].resolve())]
    from .render import auto_encoder
    encoder = "h264_nvenc" if nvenc_available() else auto_encoder()
    enc = ["-c:v", encoder]
    if encoder == "libx264":
        enc += ["-crf", crf, "-preset", "medium"]
    elif "videotoolbox" in encoder:
        enc += ["-q:v", "65", "-allow_sw", "1"]
    else:
        enc += ["-rc", "vbr", "-cq", crf + 3, "-preset", "p5", "-b:v", "0"]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.mp4")
    log("merge", f"Ghép {len(clips)} đoạn thành {W}x{H}, {total:.1f} giây" + (f", chuyển cảnh {TRANSITIONS[transition]}" if transition else "") + f", {encoder}")
    try:
        ffmpeg([*inputs, "-filter_complex", graph, "-map", vout, "-map", aout, "-c:a", "aac", "-b:a", "192k", "-ar", 48000,
                "-t", f"{total + 1:.3f}", *enc, "-movflags", "+faststart", tmp], progress_stage="merge", total=total)
    except BaseException:
        tmp.unlink(missing_ok=True)      # hủy hoặc lỗi: không để lại file dở trong thư mục xuất
        raise
    replace_file(tmp, out)
    info = probe(out)
    log("merge", f"Xong: {out.name}")
    return {"path": str(out.resolve()), "duration": info["duration"], "width": info["width"], "height": info["height"], "clips": len(clips)}


class MergeStore:
    """Danh sách các bản đã ghép để trang Ghép video hiện lại."""

    def __init__(self, folder: Path):
        self.dir = Path(folder)
        self.file = self.dir / "index.json"

    def items(self) -> list[dict]:
        try:
            rows = json.loads(self.file.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return []
        return [r for r in rows if Path(r.get("path", "")).exists()]

    def _write(self, rows: list[dict]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    def add(self, name: str, result: dict) -> dict:
        rec = {"id": uuid.uuid4().hex[:10], "name": name, "created": time.time(), **result}
        self.dir.mkdir(parents=True, exist_ok=True)
        thumb = self.dir / f"{rec['id']}.jpg"
        try:
            ffmpeg(["-ss", f"{min(1.0, result['duration'] / 3):.2f}", "-i", result["path"], "-frames:v", "1", "-vf", "scale=480:-2", "-strict", "unofficial", "-q:v", "4", thumb])
        except RuntimeError as e:
            log("merge", f"Không tạo được ảnh xem trước: {str(e)[:120]}")
        self._write([rec, *self.items()][:200])
        return rec

    def get(self, mid: str) -> dict | None:
        return next((r for r in self.items() if r["id"] == mid), None)

    def remove(self, mid: str) -> None:
        rec = self.get(mid)
        if rec:
            Path(rec["path"]).unlink(missing_ok=True)
            (self.dir / f"{mid}.jpg").unlink(missing_ok=True)
        self._write([r for r in self.items() if r["id"] != mid])


def run_merge(payload: dict, output_dir: Path, store: MergeStore) -> dict:
    """Chạy một lượt ghép từ hàng đợi."""
    name = safe_name(str(payload.get("name") or "ghep"), 60) or "ghep"
    out = Path(output_dir) / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
    res = merge(payload.get("items") or [], out, aspect=str(payload.get("aspect") or ""), fit=str(payload.get("fit") or "blur"),
                transition=str(payload.get("transition") or ""), trans_dur=float(payload.get("trans_dur") or 0.5))
    return store.add(str(payload.get("name") or name), res)
