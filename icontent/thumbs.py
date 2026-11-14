"""Thumbnail cho video vừa làm: nguồn (câu chuyện của Kể chuyện, video của Studio), ảnh nền đề cử, lưu thumbnail vào đúng video,
AI gợi ý chữ, thumbnail tự động cho Quy trình.

Trình sửa (js/thumbnail.js) vẽ bằng canvas trong trình duyệt rồi gửi ảnh hoàn chỉnh về đây; bản thiết kế (các lớp) lưu kèm để mở lại sửa tiếp.
"""
from __future__ import annotations

import io
import json
import shutil
import time
from pathlib import Path
from urllib.parse import quote

from .cover import ASPECTS, STYLES, render_cover
from .util import log, replace_file

PROJECT = "thumb_project.json"
MAX_BYTES = 30 * 1024 * 1024

SUGGEST_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"main": {"type": "string"}, "sub": {"type": "string"}},
                                                         "required": ["main", "sub"]}}},
    "required": ["items"],
}
SUGGEST_SYSTEM = """You write thumbnail text for Vietnamese short videos (YouTube, TikTok, Facebook). Return JSON only.
Give 6 options. main: 2 to 6 Vietnamese words with full diacritics, punchy, curiosity or emotion, no hashtags, no emoji, no quotes,
no clickbait lies (must match the content). sub: optional 1 to 4 word label (like a tag or episode), may be empty.
Vary the angle: question, surprising fact, emotion, number, warning, promise."""


# ------------------------------------------------------------------ nguồn
def story_sources(store) -> list[dict]:
    out = []
    for s in store.list():
        try:
            full = store.get(s["id"])
        except KeyError:
            continue
        imgs = [sc.get("image") for sc in full.get("scenes") or [] if sc.get("image")]
        if not imgs:
            continue
        sid = full["id"]
        out.append({"kind": "story", "id": sid, "title": full.get("title") or "Câu chuyện", "aspect": full.get("aspect") or "9:16",
                    "updated": full.get("rendered") or full.get("updated") or 0, "video": bool(full.get("output") and Path(full["output"]).is_file()),
                    "preview": f"/api/stories/{quote(sid, safe='')}/file/img/{quote(imgs[0], safe='')}",
                    "thumb": (store.folder(sid) / "thumb.jpg").is_file()})
    return out


def job_sources(st) -> list[dict]:
    out = []
    w = st.work()
    if not w.exists():
        return out
    for p in w.iterdir():
        if not (p.is_dir() and (p / "meta.json").exists() and (p / "source.mp4").exists()):
            continue
        try:
            j = st.job_summary(p, set())
        except Exception:      # noqa: BLE001 — một video hỏng không làm hỏng cả danh sách
            continue
        aspect = "9:16" if (j.get("height") or 0) > (j.get("width") or 0) else "16:9"
        try:
            title = job_text(p)[0]      # tiếng Việt khi có, không hiện tiêu đề tiếng Trung
        except Exception:      # noqa: BLE001
            title = ""
        out.append({"kind": "job", "id": j["id"], "title": title or j.get("title_vi") or j.get("title") or j["id"], "aspect": aspect,
                    "updated": (p / "final.mp4").stat().st_mtime if (p / "final.mp4").exists() else j.get("created") or 0,
                    "video": bool(j.get("output")), "preview": j["thumb"], "thumb": (p / "cover.jpg").is_file(),
                    "duration": j.get("duration") or 0})
    return out


def story_backgrounds(store, sid: str) -> list[dict]:
    """Ảnh nền đề cử của câu chuyện: ảnh từng cảnh (nét hơn khung cắt từ video, không có phụ đề), cả các bản vẽ trước."""
    s = store.get(sid)
    q = quote(sid, safe="")
    out = []
    for i, sc in enumerate(s.get("scenes") or [], 1):
        names = [sc["image"]] if sc.get("image") else []
        names += [n for n in sc.get("images") or [] if n not in names]
        for k, n in enumerate(names[:3]):
            if store.file(sid, "img", n).exists():
                out.append({"url": f"/api/stories/{q}/file/img/{quote(n, safe='')}", "label": f"Cảnh {i}" + (f" bản {k + 1}" if k else "")})
    return out


def job_backgrounds(job: Path) -> list[dict]:
    """Khung hình đẹp nhất của video (nét, đủ sáng, có người), đã xóa sub gốc."""
    from .cover import candidates
    from .pipeline import load_json
    q = quote(job.name, safe="")
    return [{"url": f"/api/jobs/{q}/frame.jpg?t={c['t']:.2f}&clean=1", "label": f"{int(c['t']) // 60}:{int(c['t']) % 60:02d}", "t": c["t"]}
            for c in candidates(job, load_json(job / "meta.json") or {}, n=8)]


# ------------------------------------------------------------------ lưu
def _check_image(data: bytes):
    from PIL import Image, UnidentifiedImageError
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Ảnh rỗng hoặc quá lớn")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError(f"Không đọc được ảnh: {e}") from None
    return im.convert("RGB")


def _save_jpeg(im, dst: Path) -> None:
    """JPEG dưới 2 MB (giới hạn ảnh bìa của YouTube): giảm chất lượng dần nếu cần."""
    tmp = dst.with_name(dst.name + ".part")
    for q in (92, 86, 80, 72):
        im.save(tmp, "JPEG", quality=q, optimize=True)
        if tmp.stat().st_size <= 2 * 1024 * 1024:
            break
    replace_file(tmp, dst)


def save_story_thumb(store, sid: str, data: bytes, aspect: str) -> Path:
    im = _check_image(data)
    folder = store.folder(sid)
    dst = folder / "thumb.jpg"
    _save_jpeg(im, dst)
    if aspect in ASPECTS:
        shutil.copy2(dst, folder / f"thumb_{aspect.replace(':', 'x')}.jpg")
    s = store.get(sid)
    shown = dst
    for e in s.get("edited") or []:      # cả các bản gửi về từ Trình dựng
        p = Path(e.get("path") or "")
        if p.is_file():
            shutil.copy2(dst, p.with_suffix(".jpg"))
            shown = p.with_suffix(".jpg")
    out = Path(s.get("output") or "")
    if out.is_file():      # đặt cạnh video đã dựng, cùng tên: kéo cả hai lên nền tảng là xong
        shutil.copy2(dst, out.with_suffix(".jpg"))
        shown = out.with_suffix(".jpg")
    store.update(sid, lambda x: x.update(thumb={"aspect": aspect, "at": round(time.time(), 3), "w": im.width, "h": im.height}))
    return shown


def save_job_thumb(job: Path, data: bytes, aspect: str) -> Path:
    from .pipeline import load_json
    im = _check_image(data)
    dst = job / "cover.jpg"
    _save_jpeg(im, dst)
    old = load_json(job / "cover.json") or {}
    (job / "cover.json").write_text(json.dumps({**old, "edited": True, "aspect": aspect or old.get("aspect", "")}, ensure_ascii=False), encoding="utf-8")
    output = load_json(job / "output.json") or {}
    if output.get("video") and Path(output["video"]).exists():
        shutil.copy2(dst, Path(output["video"]).with_suffix(".jpg"))
    return dst


def project_path(folder: Path) -> Path:
    return folder / PROJECT


def save_project(folder: Path, doc: dict) -> None:
    raw = json.dumps(doc, ensure_ascii=False)
    if len(raw) > 2_000_000:
        raise ValueError("Bản thiết kế quá lớn")
    tmp = folder / (PROJECT + ".part")
    tmp.write_text(raw, encoding="utf-8")
    replace_file(tmp, folder / PROJECT)


def load_project(folder: Path) -> dict | None:
    try:
        return json.loads((folder / PROJECT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ AI gợi ý chữ
def suggest_texts(cfg, title: str, content: str) -> list[dict]:
    from .story import _json_by_ai
    user = f"Video title: {title.strip()[:200]}\n\nWhat the video says (Vietnamese):\n{content.strip()[:3000]}"
    data = _json_by_ai(cfg, SUGGEST_SYSTEM, user, SUGGEST_SCHEMA, 2000)
    out = []
    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        main = " ".join(str(it.get("main") or "").replace('"', "").split())[:60]
        if main:
            out.append({"main": main, "sub": " ".join(str(it.get("sub") or "").split())[:30]})
    if not out:
        raise RuntimeError("AI không gợi ý được, thử lại")
    return out[:8]


def story_text(store, sid: str) -> tuple[str, str]:
    s = store.get(sid)
    return s.get("title") or "", "\n".join(sc.get("text") or "" for sc in s.get("scenes") or [])[:3000]


def job_text(job: Path) -> tuple[str, str]:
    from .models import load_segments
    from .pipeline import load_json
    import re
    meta = load_json(job / "meta.json") or {}
    pub = ((load_json(job / "context.json") or {}).get("publish") or {}).get("title") or ""
    segs = load_segments(job / "segments.json") if (job / "segments.json").exists() else []
    lines = [s.trans or s.text for s in segs][:80]
    title = pub or meta.get("title") or ""
    if not pub and re.search(r"[぀-ヿ㐀-鿿]", title):
        # chưa có tiêu đề tiếng Việt (dịch offline không gợi ý tiêu đề): lấy câu dịch đầu tiên đủ dài, thumbnail không hiện chữ Trung
        vi = next((s.trans.strip() for s in segs if s.trans and len(s.trans.split()) >= 4), "")
        title = " ".join(vi.split()[:8]).rstrip(".,!?…;:") if vi else ""
    return title, "\n".join(lines)[:3000]


# ------------------------------------------------------------------ tự động (Quy trình)
def auto_story_thumb(store, sid: str, aspect: str = "", style: str = "noi-bat", title: str = "", color: str = "#FFB224") -> Path:
    """Thumbnail không cần mở trình sửa: ảnh cảnh đầu (hoặc cảnh có nhân vật), tiêu đề lớn. Mở trang Thumbnail để sửa tiếp."""
    from .util import imread
    s = store.get(sid)
    scenes = [sc for sc in s.get("scenes") or [] if sc.get("image") and store.file(sid, "img", sc["image"]).exists()]
    if not scenes:
        raise ValueError("Câu chuyện chưa có ảnh cảnh nào để làm thumbnail")
    pick = next((sc for sc in scenes if sc.get("characters")), scenes[0])
    im = imread(store.file(sid, "img", pick["image"]))
    if im is None:
        raise RuntimeError("Không đọc được ảnh cảnh")
    aspect = aspect if aspect in ASPECTS else (s.get("aspect") if s.get("aspect") in ASPECTS else "16:9")
    pic = render_cover(im, title or s.get("title") or "", style if style in STYLES else "noi-bat", aspect, color)
    buf = io.BytesIO()
    pic.save(buf, "JPEG", quality=92)
    log("thumb", f"Thumbnail tự động {aspect} cho '{s.get('title')}'")
    return save_story_thumb(store, sid, buf.getvalue(), aspect)
