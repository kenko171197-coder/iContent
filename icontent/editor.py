"""Trình dựng tự do: FreeCut (giấy phép MIT) đã build sẵn trong web/editor, xem third_party/freecut/.

FreeCut dùng đường dẫn tuyệt đối khắp nơi và có service worker chiếm cả origin, nên không ở chung origin với giao diện Studio566
mà ở editor.localhost, trên cùng máy chủ và cùng cổng. Chromium luôn trỏ *.localhost về máy này và coi là secure context, nên
trình dựng có đủ WebGPU, WebCodecs, File System Access, và /api/ gọi thẳng được, không cần CORS.

Đường đi của một video:
  Studio bấm mở -> cửa sổ trình dựng tự hỏi /api/editor/jobs/<id> -> Studio566 dựng editor_base.mp4 (giữ xóa sub, cắt, đổi khung,
  lồng tiếng, không ghi phụ đề vào hình) -> trình dựng tạo dự án: video một track, phụ đề (final.srt) một track sửa được
  -> dựng xong bấm Gửi về Studio566 -> file nằm trong thư mục output, ghi vào edited.json của video.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from fastapi.responses import FileResponse, Response

from .util import find_ffmpeg, safe_name

HOST = "editor.localhost"
DIST = Path(__file__).parent / "web" / "editor"
BASE = "editor_base.mp4"
BASE_KEY = "editor_base.json"
BASE_SRT = "editor_base.srt"            # phụ đề đúng theo thời gian của chính bản nền
BASE_INFO = "editor_base.render.json"   # cỡ chữ, vị trí phụ đề nếu bản nền có ghi phụ đề
EDITED = "edited.json"
RESULT_EXT = {".mp4", ".webm", ".mov", ".mkv"}
KEEP_EDITED = 20        # chỉ là danh sách để hiện, file vẫn nằm trong thư mục output

# hỏi lại bằng tệp trên đĩa, không dùng mimetypes: trên Windows nó đọc từ registry, máy nào cũng khác và có máy trả .js là text/plain
TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json",
    ".wasm": "application/wasm", ".webmanifest": "application/manifest+json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
    ".webp": "image/webp", ".woff2": "font/woff2", ".woff": "font/woff", ".txt": "text/plain; charset=utf-8", ".onnx": "application/octet-stream",
}
ISOLATION = {"Cross-Origin-Opener-Policy": "same-origin", "Cross-Origin-Embedder-Policy": "credentialless", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY"}


def available() -> bool:
    return (DIST / "index.html").is_file()


def is_editor_host(host_header: str | None) -> bool:
    return (host_header or "").rsplit(":", 1)[0] == HOST


def window_url(host_header: str | None, job: str = "", fresh: bool = False, story: str = "") -> str:
    """Giữ nguyên cổng Studio566 đang chạy. story: mở một câu chuyện của Kể chuyện thay cho một video."""
    tail = (host_header or "").rsplit(":", 1)
    port = tail[1] if len(tail) == 2 and tail[1].isdigit() else "8765"
    if story:
        q = f"?icontent_story={quote(story, safe='')}" + ("&fresh=1" if fresh else "")
    else:
        q = f"?icontent={quote(job, safe='')}" + ("&fresh=1" if fresh else "") if job else ""
    return f"http://{HOST}:{port}/projects{q}"


def static_response(url_path: str) -> Response:
    """Đường dẫn không phải file là một trang của FreeCut (/projects, /editor/...): trả index.html để bộ định tuyến của nó xử lý.
    File thiếu thì báo 404, không trả html: trình duyệt sẽ hiểu nhầm thành script hỏng và báo lỗi khó hiểu."""
    rel = url_path.lstrip("/")
    root = DIST.resolve()
    f = (root / rel).resolve()
    inside = f == root or root in f.parents
    if rel and inside and f.is_file():
        cache = "public, max-age=31536000, immutable" if rel.startswith("assets/") else "no-cache"
        return FileResponse(f, media_type=TYPES.get(f.suffix.lower(), "application/octet-stream"), headers={"Cache-Control": cache, **ISOLATION})
    if (rel and not inside) or "." in PurePosixPath(rel).name or not available():
        return Response("Không có file", status_code=404, headers=ISOLATION)
    return FileResponse(root / "index.html", media_type=TYPES[".html"], headers={"Cache-Control": "no-cache", **ISOLATION})


def _load(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (ValueError, OSError):
        return {}
    return d if isinstance(d, dict) else {}


def render_signature(cfg) -> str:
    """Dấu của các cài đặt có ảnh hưởng tới hình và tiếng, gồm cả cài đặt chung. options.json chỉ là phần khác với cài đặt chung, nên đổi trong
    Cài đặt (tắt ghi phụ đề, đổi tốc độ...) thì options.json không đổi mà video ra đã khác."""
    from .util import short_hash
    return short_hash(json.dumps({"edit": dict(cfg.edit), "audio": dict(cfg.audio)}, ensure_ascii=False, sort_keys=True, default=str))


def base_fresh(job: Path, cfg=None) -> bool:
    """Bản nền còn đúng không. is_fresh một mình chưa đủ: nó so tùy chọn với render.json của final.mp4, nên dựng lại bản chính với tùy
    chọn mới rồi thì bản nền cũ cũng được tính là mới. Vì vậy bản nền giữ riêng tùy chọn của nó, và dấu cài đặt lúc dựng.
    cfg: cài đặt đang có hiệu lực của video này (cài đặt chung + options.json)."""
    from .pipeline import is_fresh, job_options, options_hash
    if not is_fresh(job, BASE) or not (job / BASE_SRT).exists():
        return False
    key = _load(job / BASE_KEY)
    if key.get("options") != options_hash(job_options(job)):
        return False
    return cfg is None or key.get("cfg") == render_signature(cfg)


_SRT_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")


def parse_srt(path: Path) -> list[dict]:
    if not path.exists():
        return []
    cues: list[dict] = []
    for block in re.split(r"\r?\n\s*\r?\n", path.read_text(encoding="utf-8-sig", errors="replace").strip()):
        lines = block.splitlines()
        for i, ln in enumerate(lines):
            m = _SRT_TIME.search(ln)
            if m:
                g = m.groups()
                start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3].ljust(3, "0")) / 1000
                end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7].ljust(3, "0")) / 1000
                text = "\n".join(lines[i + 1:]).strip()
                if text and end > start:
                    cues.append({"id": f"cue-{len(cues) + 1}", "startSeconds": start, "endSeconds": end, "text": text})
                break
    return cues


def _title(job: Path) -> str:
    pub = (_load(job / "context.json").get("publish") or {})
    return str(pub.get("title") or _load(job / "meta.json").get("title") or job.name)


def _sub_style(job: Path) -> dict | None:
    """Cỡ chữ và vị trí phụ đề theo đúng khung của bản nền. Không có thì trình dựng dùng mặc định của nó."""
    sub = _load(job / BASE_INFO).get("sub") or {}
    if not (sub.get("fs") and sub.get("bottom")):
        return None
    return {"font_size": int(sub["fs"]), "bottom": int(sub["bottom"])}


def project_info(job: Path) -> dict:
    """Những gì trình dựng cần để tự xếp dự án."""
    from .qc import stream_info
    info = stream_info(job / BASE)
    v = info.get("video") or {}
    title = safe_name(_title(job), 80)
    name = f"{safe_name(_title(job), 60)}.mp4"
    return {
        "job": job.name, "name": title, "width": int(v.get("w") or 0), "height": int(v.get("h") or 0), "fps": float(v.get("fps") or 30),
        "duration": float(info.get("duration") or 0), "file_name": name,
        "video_url": f"/api/editor/jobs/{quote(job.name, safe='')}/video/{quote(name, safe='')}",
        "subs": parse_srt(job / BASE_SRT), "sub_style": _sub_style(job),
    }


def reserve_result(out_dir: Path, job: Path | None, name: str, ext: str) -> Path:
    """Giữ chỗ một tên chưa có (tạo file rỗng một cách nguyên tử): hai cửa sổ gửi cùng lúc không bao giờ được cùng một tên.
    Không ghi đè: mỗi lần gửi về là một bản, bản trước vẫn còn."""
    if job is not None:
        from .pipeline import output_name
        stem = f"{output_name(_load(job / 'meta.json'))}_dung"
    else:
        stem = safe_name(Path(name).stem, 80)
    n = 1
    while True:
        out = out_dir / (f"{stem}{ext}" if n == 1 else f"{stem}_{n}{ext}")
        try:
            os.close(os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return out
        except FileExistsError:
            n += 1


def finish_result(tmp: Path, dst: Path) -> None:
    """Trình dựng ghi phần chỉ mục moov ở cuối file: nền tảng và trình phát phải tải hết mới xem được. Chuyển lên đầu, không mã hóa lại nên chỉ mất
    vài giây. Hỏng thì vẫn giữ nguyên bản đã nhận: video xuất xong rồi, không được mất chỉ vì bước phụ này."""
    if dst.suffix.lower() in (".mp4", ".mov"):
        ok = dst.with_name(dst.stem + ".fast" + dst.suffix)
        try:
            exe, _ = find_ffmpeg()
            r = subprocess.run([exe, "-v", "error", "-nostdin", "-y", "-i", str(tmp), "-map", "0", "-c", "copy", "-movflags", "+faststart", str(ok)], capture_output=True, timeout=1800)
            if r.returncode == 0 and ok.stat().st_size > 0:
                os.replace(ok, dst)
                return
            print(f"[editor] Không tối ưu được file gửi về: {r.stderr[-200:]!r}", flush=True)
        except (OSError, subprocess.SubprocessError, RuntimeError) as e:
            print(f"[editor] Không tối ưu được file gửi về: {str(e)[:200]}", flush=True)
        finally:
            ok.unlink(missing_ok=True)
    os.replace(tmp, dst)


def record_result(job: Path, path: Path) -> list[dict]:
    items = _load(job / EDITED).get("items") or []
    items.insert(0, {"path": str(path.resolve()), "name": path.name, "size": path.stat().st_size, "at": time.time()})
    del items[KEEP_EDITED:]
    (job / EDITED).write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return items


def edited_items(job: Path) -> list[dict]:
    """Bản nào đã bị xóa khỏi thư mục output thì không hiện nữa."""
    return [x for x in _load(job / EDITED).get("items") or [] if x.get("path") and Path(x["path"]).exists()]


def edited_by_name(job: Path, name: str) -> Path | None:
    """Tìm theo tên, không theo vị trí: danh sách trên giao diện có thể cũ hơn, vị trí 0 lúc đó đã là bản khác."""
    return next((Path(x["path"]) for x in edited_items(job) if x.get("name") == name), None)


def latest_edited(job: Path) -> Path | None:
    """Bản mới nhất, chỉ khi nó được gửi về sau lần dựng bản chính gần nhất: dựng lại bản chính rồi thì bản cũ từ trình dựng không còn đúng
    với phụ đề, ảnh bìa, điểm kiểm định trong gói nữa."""
    items = edited_items(job)
    if not items:
        return None
    final = job / "final.mp4"
    if final.exists() and float(items[0].get("at") or 0) < final.stat().st_mtime:
        return None
    return Path(items[0]["path"])
