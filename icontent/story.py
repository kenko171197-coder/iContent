"""Video kể chuyện: kịch bản -> từng cảnh có ảnh, lời dẫn, phụ đề -> một video có chuyển động máy quay và nhạc nền.

  workspace/.stories/<id>/
    story.json     câu chuyện: thiết lập, nhân vật, các cảnh
    img/           ảnh từng cảnh (tải lên hoặc Gemini vẽ), giữ cả các bản cũ để chọn lại
    ref/           ảnh mẫu nhân vật, gửi kèm khi vẽ để nhân vật giống nhau qua các cảnh
    audio/         lời dẫn từng cảnh (có cache theo nội dung)

Ảnh và ảnh mẫu do máy chủ quản lý: giao diện lưu câu chuyện không được ghi đè các trường này, vì lúc lưu có thể đang có ảnh vẽ xong
ở luồng khác (xem merge_story).
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

import numpy as np

from .util import check_cancel, ffmpeg, log, progress, read_wav, safe_name, short_hash, stage, write_wav

FPS = 30
SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}
MOTIONS = ("auto", "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "still")
AUTO_CYCLE = ("zoom_in", "pan_right", "zoom_out", "pan_left", "zoom_in", "pan_up")
STYLES = {
    "": "",
    "anime": "anime illustration, clean line art, vibrant colors, expressive faces",
    "pixar": "3D animated film still, soft cinematic lighting, expressive stylized characters",
    "watercolor": "storybook watercolor illustration, soft paper texture, gentle colors",
    "realistic": "cinematic photorealistic still, natural lighting, shallow depth of field, 35mm film",
    "comic": "comic book art, bold ink outlines, flat vivid colors",
    "ink": "traditional East Asian ink wash painting, elegant brush strokes, muted colors",
    "chibi": "cute chibi cartoon style, big heads, pastel colors, simple background",
}
STYLE_LABELS = {"": "Không chọn", "anime": "Anime", "pixar": "Hoạt hình 3D", "watercolor": "Màu nước truyện tranh thiếu nhi",
                "realistic": "Ảnh như thật, điện ảnh", "comic": "Truyện tranh", "ink": "Tranh thủy mặc cổ trang", "chibi": "Chibi dễ thương"}
SUB_STYLES = ("box", "classic", "tiktok", "pop", "karaoke")
# kiểu chuyển cảnh: tên bộ lọc xfade của ffmpeg; "none" là cắt thẳng
TRANSITIONS = {"fade": "Mờ chồng", "fadeblack": "Tối dần", "fadewhite": "Trắng dần", "dissolve": "Tan vào", "slideleft": "Trượt sang trái",
               "slideright": "Trượt sang phải", "slideup": "Trượt lên", "wipeleft": "Quét sang trái", "circleopen": "Mở tròn",
               "smoothleft": "Lướt mượt", "zoomin": "Phóng vào", "radial": "Xoay quét", "none": "Cắt thẳng"}
INTRO_DUR, OUTRO_DUR = 2.8, 3.2
DEFAULT_OUTRO = "Theo dõi kênh để xem phần tiếp theo"
ZOOM = 0.12              # phóng thêm 12% trong một cảnh: đủ thấy chuyển động mà không mất nhiều khung
TRANS = 0.5              # giây chuyển cảnh
MIN_SCENE = 2.5
PRE_SCALE = 2            # Ken Burns trên ảnh phóng 2 lần rồi thu về: bước lệch nửa điểm ảnh, chuyển động không bị giật
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_VARIANTS = 8
MAX_SCENES = 200
TEXT_LIMIT = 4000
MUSIC_DIR = Path(__file__).resolve().parent.parent / "assets" / "music"


# ------------------------------------------------------------------ lưu trữ
def _now() -> float:
    return round(time.time(), 3)


def new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def default_story(title: str = "") -> dict:
    return {
        "id": new_id("s"), "title": title or "Câu chuyện mới", "created": _now(), "updated": _now(),
        "aspect": "9:16", "style": "pixar", "style_note": "", "fit": "cover", "image_provider": "", "stock_src": "", "video_res": "720p",
        "voice": {"engine": "vieneu", "voice": "", "speed": 1.0},
        "subs": {"enabled": True, "style": "box"},
        "transition": "fade", "trans_dur": 0.5,
        "intro": {"enabled": False, "text": "", "sub": ""},
        "outro": {"enabled": False, "text": DEFAULT_OUTRO, "sub": ""},
        "music": {"path": "", "volume": 0.12},
        "characters": [], "scenes": [], "output": "",
    }


def _clean_text(v, limit: int) -> str:
    return str(v or "").replace("\r\n", "\n").strip()[:limit]


def merge_story(current: dict, incoming: dict) -> dict:
    """Áp phần người dùng sửa lên bản đang lưu. Ảnh cảnh và ảnh mẫu nhân vật luôn lấy từ bản đang lưu (máy chủ quản lý),
    nên lưu câu chuyện trong lúc Gemini đang vẽ không làm mất ảnh vừa vẽ xong."""
    out = dict(current)
    out["title"] = _clean_text(incoming.get("title"), 120) or current.get("title") or "Câu chuyện"
    if incoming.get("aspect") in SIZES:
        out["aspect"] = incoming["aspect"]
    if incoming.get("style") in STYLES:
        out["style"] = incoming["style"]
    out["style_note"] = _clean_text(incoming.get("style_note"), 400)
    if incoming.get("fit") in ("cover", "blur"):
        out["fit"] = incoming["fit"]
    from .imagegen import PROVIDERS
    if "image_provider" in incoming:
        out["image_provider"] = incoming["image_provider"] if incoming["image_provider"] in PROVIDERS else ""
    from .stock import SOURCES as STOCK
    from .videogen import RESOLUTIONS
    if "stock_src" in incoming:
        out["stock_src"] = incoming["stock_src"] if incoming["stock_src"] in STOCK else ""
    if incoming.get("video_res") in RESOLUTIONS:
        out["video_res"] = incoming["video_res"]
    v = incoming.get("voice") or {}
    try:
        speed = min(2.0, max(0.5, float(v.get("speed") or 1.0)))
    except (TypeError, ValueError):
        speed = 1.0
    from .langs import LANGS
    out["voice"] = {"engine": v.get("engine") if v.get("engine") in ("vieneu", "edge", "vox") else "vieneu", "voice": _clean_text(v.get("voice"), 80),
                    "speed": speed, "lang": v.get("lang") if v.get("lang") in LANGS else "vi"}
    sb = incoming.get("subs") or {}
    out["subs"] = {"enabled": bool(sb.get("enabled", True)), "style": sb.get("style") if sb.get("style") in SUB_STYLES else "box"}
    out["transition"] = incoming.get("transition") if incoming.get("transition") in TRANSITIONS else current.get("transition") or "fade"
    try:
        out["trans_dur"] = min(1.5, max(0.2, float(incoming.get("trans_dur") if incoming.get("trans_dur") is not None else current.get("trans_dur") or 0.5)))
    except (TypeError, ValueError):
        out["trans_dur"] = 0.5
    for key, default in (("intro", ""), ("outro", DEFAULT_OUTRO)):
        card = incoming.get(key) if isinstance(incoming.get(key), dict) else (current.get(key) or {})
        out[key] = {"enabled": bool(card.get("enabled")), "text": _clean_text(card.get("text"), 140) if "text" in card else default,
                    "sub": _clean_text(card.get("sub"), 100)}
    m = incoming.get("music") or {}
    try:
        mv = min(1.0, max(0.0, float(m.get("volume") if m.get("volume") is not None else 0.12)))
    except (TypeError, ValueError):
        mv = 0.12
    out["music"] = {"path": _music_path(m.get("path")), "volume": mv}

    old_chars = {c["id"]: c for c in current.get("characters") or []}
    chars = []
    for c in incoming.get("characters") or []:
        cid = str(c.get("id") or "")
        base = old_chars.get(cid) or {"id": cid if re.fullmatch(r"c[0-9a-f]{8}", cid) else new_id("c"), "refs": []}
        chars.append({"id": base["id"], "name": _clean_text(c.get("name"), 60) or "Nhân vật", "description": _clean_text(c.get("description"), 600),
                      "refs": list(base.get("refs") or [])})
    out["characters"] = chars
    known_chars = {c["id"] for c in chars}

    old_scenes = {s["id"]: s for s in current.get("scenes") or []}
    scenes = []
    for s in incoming.get("scenes") or []:
        sid = str(s.get("id") or "")
        base = old_scenes.get(sid) or {"id": sid if re.fullmatch(r"n[0-9a-f]{8}", sid) else new_id("n"), "image": "", "images": [], "created": _now()}
        scenes.append({
            "id": base["id"], "text": _clean_text(s.get("text"), TEXT_LIMIT), "prompt": _clean_text(s.get("prompt"), 1200),
            "broll": _clean_text(s.get("broll"), 100).replace("\n", " "),
            # clip do máy chủ quản lý như ảnh: lưu từ giao diện trong lúc đang tải, đang tạo clip không làm mất clip vừa xong
            "clip": base.get("clip") or "", "clips": list(base.get("clips") or []), "clip_meta": dict(base.get("clip_meta") or {}),
            "characters": [x for x in s.get("characters") or [] if x in known_chars][:4],
            "motion": s.get("motion") if s.get("motion") in MOTIONS else "auto",
            "duration": _duration(s.get("duration")), "transition": s.get("transition") if s.get("transition") in TRANSITIONS else "",
            "image": base.get("image") or "", "images": list(base.get("images") or []), "created": base.get("created") or 0,
        })
    # cảnh máy chủ vừa thêm (thêm nhiều ảnh, AI viết) mà giao diện chưa biết lúc gửi: giữ lại, không coi là bị xóa
    try:
        synced = float(incoming.get("synced") or 0)
    except (TypeError, ValueError):
        synced = 0.0
    seen = {x["id"] for x in scenes}
    scenes += [x for x in current.get("scenes") or [] if x["id"] not in seen and float(x.get("created") or 0) > synced]
    out["scenes"] = scenes[:MAX_SCENES]
    out["updated"] = _now()
    return out


def _duration(v) -> float | None:
    """Thời lượng người dùng đặt cho cảnh (giây). Trống là tự tính theo lời dẫn."""
    try:
        d = float(v)
    except (TypeError, ValueError):
        return None
    return round(min(60.0, max(0.5, d)), 2) if d > 0 else None


def _music_path(v) -> str:
    """Chỉ nhận nhạc nằm trong thư mục nhạc đã tải lên qua Studio566: đường dẫn bất kỳ trên máy thì không đưa cho ffmpeg đọc."""
    path = _clean_text(v, 500)
    if not path:
        return ""
    try:
        f = Path(path).resolve()
    except OSError:
        return ""
    return str(f) if f.is_file() and MUSIC_DIR.resolve() in f.parents else ""


class StoryStore:
    """Mỗi câu chuyện một thư mục. Khóa theo câu chuyện: giao diện lưu và luồng vẽ ảnh cùng ghi story.json.
    Khóa là của cả tiến trình, theo đường dẫn thật của câu chuyện: mỗi lần gọi API tạo một StoryStore mới, khóa riêng từng đối tượng sẽ
    không chặn được gì (ảnh vừa vẽ xong, đã tính tiền, bị lần lưu từ giao diện ghi đè mất)."""

    _locks: dict[str, threading.RLock] = {}
    _guard = threading.Lock()

    def __init__(self, root: Path):
        self.root = Path(root)

    def lock(self, sid: str) -> threading.RLock:
        key = str(self.folder(sid).resolve()).lower()
        with StoryStore._guard:
            return StoryStore._locks.setdefault(key, threading.RLock())

    def folder(self, sid: str) -> Path:
        if not re.fullmatch(r"s[0-9a-f]{8}", sid or ""):
            raise KeyError("Mã câu chuyện không hợp lệ")
        return self.root / sid

    def list(self) -> list[dict]:
        out = []
        if self.root.exists():
            for d in self.root.iterdir():
                f = d / "story.json"
                if f.exists():
                    try:
                        s = json.loads(f.read_text(encoding="utf-8"))
                    except ValueError:
                        continue
                    cover = next((x["image"] for x in s.get("scenes") or [] if x.get("image")), "")
                    out.append({"id": s["id"], "title": s.get("title"), "updated": s.get("updated"), "scenes": len(s.get("scenes") or []),
                                "aspect": s.get("aspect"), "cover": cover, "output": s.get("output") or ""})
        return sorted(out, key=lambda x: -(x.get("updated") or 0))

    def get(self, sid: str) -> dict:
        f = self.folder(sid) / "story.json"
        if not f.exists():
            raise KeyError("Không có câu chuyện này")
        with self.lock(sid):      # cùng khóa với lúc ghi: không đọc trúng lúc file đang được thay (Windows báo lỗi quyền)
            for attempt in range(5):
                try:
                    return json.loads(f.read_text(encoding="utf-8"))
                except (PermissionError, ValueError):
                    if attempt == 4:
                        raise
                    time.sleep(0.1 * (attempt + 1))
        raise KeyError("Không đọc được câu chuyện")

    def write(self, story: dict) -> dict:
        from .util import replace_file
        d = self.folder(story["id"])
        for sub in ("img", "ref", "audio", "clip"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        with self.lock(story["id"]):
            tmp = d / f"story.json.{uuid.uuid4().hex[:8]}.part"      # tên tạm riêng: hai lần ghi không trộn vào nhau
            try:
                tmp.write_text(json.dumps(story, ensure_ascii=False, indent=1), encoding="utf-8")
                replace_file(tmp, d / "story.json")      # tự thử lại khi có chương trình khác đang đọc file
            finally:
                tmp.unlink(missing_ok=True)
        return story

    def create(self, title: str = "") -> dict:
        return self.write(default_story(title))

    def update(self, sid: str, fn) -> dict:
        """Đọc, sửa, ghi trong khóa: hai luồng cùng sửa không làm mất phần của nhau."""
        with self.lock(sid):
            s = self.get(sid)
            fn(s)
            s["updated"] = _now()
            return self.write(s)

    def delete(self, sid: str) -> None:
        d = self.folder(sid)
        with self.lock(sid):
            if d.exists():
                shutil.rmtree(d)

    def file(self, sid: str, kind: str, name: str) -> Path:
        if kind not in ("img", "ref", "audio", "clip") or not re.fullmatch(r"[\w.-]{1,120}", name or "") or ".." in name:
            raise KeyError("Tên file không hợp lệ")
        return self.folder(sid) / kind / name


# ------------------------------------------------------------------ kịch bản
def split_script(text: str, target: int = 170, limit: int = 260) -> list[str]:
    """Chia kịch bản tự viết thành cảnh. Mỗi đoạn văn ít nhất một cảnh; đoạn dài thì gom câu thành cảnh khoảng 8 đến 14 giây lời dẫn."""
    from .speech import paragraphs, sentences
    scenes: list[str] = []
    for para in paragraphs(text):
        first = len(scenes)      # cảnh đầu của đoạn văn này: không gộp sang đoạn trước
        cur = ""
        for s in sentences(para):
            if cur and (len(cur) >= target or len(cur) + 1 + len(s) > limit):
                scenes.append(cur)
                cur = s
            else:
                cur = f"{cur} {s}".strip()
        if cur:
            if len(scenes) > first and len(cur) < 40 and len(scenes[-1]) + 1 + len(cur) <= limit:      # câu cụt cuối đoạn: gộp vào cảnh trước
                scenes[-1] = f"{scenes[-1]} {cur}"
            else:
                scenes.append(cur)
    return scenes


SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "characters": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
                                                  "required": ["name", "description"], "additionalProperties": False}},
        "scenes": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string"}, "prompt": {"type": "string"},
                                                                                 "broll": {"type": "string"},
                                                                                 "characters": {"type": "array", "items": {"type": "string"}}},
                                              "required": ["text", "prompt", "broll", "characters"], "additionalProperties": False}},
    },
    "required": ["title", "characters", "scenes"],
    "additionalProperties": False,
}

WRITER_SYSTEM = """You write short narrated story videos for {lang} social media (TikTok, YouTube Shorts, Facebook Reels).
Return JSON only, following the schema.
- title: catchy {lang} title.
- characters: every recurring character. description is in English and purely visual so an illustrator can draw the same person every time:
  age, gender, body, face, hair style and colour, clothes with colours, one or two distinctive details. No personality words.
- scenes: in story order. Each scene is 1 to 3 sentences of narration.
  text: natural spoken {lang}{diacritics}, as a storyteller would say it aloud. No stage directions, no emoji, no speaker labels.
  prompt: English description of ONE still image for that moment: setting, action, camera framing, lighting, mood. Name the characters exactly
  as in the characters list. Never ask for text, captions or speech bubbles in the image.
  broll: 2 to 4 plain English words to search free stock footage sites (Pexels, Pixabay) for a real video clip that fits this moment,
  e.g. "rainy city street night", "old man fishing lake". Concrete things and places only, no character names, no art style words.
  characters: names of characters visible in that image (subset of the list, at most 3).
Keep the story coherent with a clear hook in the first scene and a satisfying ending."""


def _writer(cfg):
    """Nhà cung cấp AI để viết kịch bản: cái đang dùng để dịch nếu là AI viết được, không thì Gemini nếu đã có key (cùng key tạo ảnh)."""
    import os

    from .keys import translator_ready
    from .translate import ClaudeTranslator, OpenAICompatTranslator
    t = cfg.translate
    if t.provider in ("claude", "openai") and translator_ready(t):
        return ClaudeTranslator(t) if t.provider == "claude" else OpenAICompatTranslator(t)
    if os.environ.get("GEMINI_API_KEY"):
        from .config import with_overrides
        g = with_overrides(cfg, {"translate": {"provider": "openai", "model": "gemini-auto", "api_key_env": "GEMINI_API_KEY",
                                               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/"}}).translate
        return OpenAICompatTranslator(g)
    from .localai import LocalWriter, writer_ready
    if writer_ready():      # không key nào: viết ngay trên máy, miễn phí
        return LocalWriter()
    raise RuntimeError("Cần AI để viết kịch bản: dán key Gemini (gói miễn phí viết được) ở Cài đặt, mục Kết nối AI, hoặc tải Dịch offline và "
                       "Vẽ ảnh offline (Mô-đun AI miễn phí) để AI viết ngay trên máy. Hoặc tự dán kịch bản, Studio566 sẽ chia cảnh không cần AI.")


def writer_ready(cfg) -> bool:
    try:
        _writer(cfg)
        return True
    except RuntimeError:
        return False


def writer_is_local(cfg) -> bool:
    from .localai import LocalWriter
    try:
        return isinstance(_writer(cfg), LocalWriter)
    except RuntimeError:
        return False


def _json_by_ai(cfg, system: str, user: str, schema: dict, max_tokens: int) -> dict:
    """Gọi AI viết; AI có key lỗi (Gemini quá tải, hết lượt, mất mạng) thì viết tiếp bằng AI trên máy nếu đã tải."""
    from .localai import LocalWriter, writer_ready as local_ready
    w = _writer(cfg)
    try:
        return w.json_call(system, user, schema, max_tokens=max_tokens)
    except Exception as e:      # noqa: BLE001
        if isinstance(w, LocalWriter) or not local_ready():
            raise
        log("story", f"AI có key lỗi ({str(e)[:100]}), viết bằng AI trên máy")
        return LocalWriter().json_call(system, user, schema, max_tokens=max_tokens)


def write_script(cfg, topic: str = "", script: str = "", seconds: int = 60, style: str = "", lang: str = "vi") -> dict:
    """topic: AI viết mới từ ý tưởng. script: AI chia kịch bản có sẵn thành cảnh, giữ nguyên lời, chỉ thêm mô tả hình và nhân vật.
    lang: ngôn ngữ lời dẫn (thị trường của câu chuyện, langs.py). Mô tả hình luôn bằng tiếng Anh cho bộ vẽ."""
    from .langs import name_en
    lname = name_en(lang)
    system = WRITER_SYSTEM.format(lang=lname, diacritics=" with full diacritics" if lang == "vi" else "")
    script = script.strip()
    if len(script) > 12000:
        raise ValueError(f"Kịch bản dài {len(script):,} ký tự, AI chỉ chia được tối đa 12.000 ký tự một lần. Bỏ chọn nhờ AI để Studio566 tự chia "
                         "cảnh, hoặc chia kịch bản thành nhiều câu chuyện.".replace(",", "."))
    _writer(cfg)      # chưa có AI nào thì báo ngay
    n = max(3, min(60, round(len(script) / 170))) if script else max(3, min(40, round(seconds / 9)))
    if script:
        user = (f"Split this {lname} script into scenes for a narrated video. Keep the narration text exactly as written, only split it "
                f"(about {n} scenes, each 1 to 3 sentences). Write the image prompts and the character list.\n\nSCRIPT:\n{script}")
    else:
        user = f"Write a story video in {lname} of about {seconds} seconds of narration (about {n} scenes) about: {topic.strip()[:2000]}"
    if style and STYLES.get(style):
        user += f"\n\nThe images will be drawn as: {STYLES[style]}."
    data = _json_by_ai(cfg, system, user, SCRIPT_SCHEMA, 12000)
    scenes = [s for s in data.get("scenes") or [] if str(s.get("text") or "").strip()]
    if not scenes:
        raise RuntimeError("AI không trả về cảnh nào, thử lại hoặc viết ý tưởng rõ hơn")
    return {"title": str(data.get("title") or "").strip(), "characters": data.get("characters") or [], "scenes": scenes}


def apply_script(story: dict, data: dict, replace: bool = True) -> None:
    """Đưa kết quả AI vào câu chuyện: tạo nhân vật theo tên, gắn nhân vật vào cảnh."""
    chars = {c["name"].strip().lower(): c for c in story.get("characters") or []}
    for c in data.get("characters") or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()[:60]
        if not name:
            continue
        if name.lower() in chars:
            if not chars[name.lower()].get("description"):
                chars[name.lower()]["description"] = str(c.get("description") or "")[:600]
            continue
        nc = {"id": new_id("c"), "name": name, "description": str(c.get("description") or "")[:600], "refs": []}
        story.setdefault("characters", []).append(nc)
        chars[name.lower()] = nc
    scenes = []
    for s in data.get("scenes") or []:
        if not isinstance(s, dict):
            continue
        names = [str(n).strip().lower() for n in s.get("characters") or [] if isinstance(n, (str, int))]
        ids = [chars[n]["id"] for n in names if n in chars][:4]
        scenes.append({"id": new_id("n"), "text": str(s.get("text") or "").strip()[:TEXT_LIMIT], "prompt": str(s.get("prompt") or "").strip()[:1200],
                       "broll": " ".join(str(s.get("broll") or "").split())[:100],
                       "characters": ids, "motion": "auto", "image": "", "images": [], "created": _now()})
    story["scenes"] = (scenes if replace else (story.get("scenes") or []) + scenes)[:MAX_SCENES]
    if data.get("title") and (replace or not story.get("title")):
        story["title"] = data["title"][:120]


# ------------------------------------------------------------------ ảnh
def scene_prompt(story: dict, scene: dict) -> tuple[str, list[Path]]:
    """Lời nhắn cho Gemini và ảnh mẫu nhân vật gửi kèm (tối đa 4, mỗi nhân vật trong cảnh ít nhất một ảnh nếu có)."""
    from .imagegen import MAX_CHARACTER_REFS, NO_TEXT
    chars = {c["id"]: c for c in story.get("characters") or []}
    present = [chars[c] for c in scene.get("characters") or [] if c in chars]
    refs: list[Path] = []
    lines = []
    root = None
    for c in present:
        mine = [r for r in c.get("refs") or []]
        if mine and len(refs) < MAX_CHARACTER_REFS:
            root = root or story["_folder"]
            refs.append(root / "ref" / mine[0])
            lines.append(f"{c['name']} must look exactly like the person in reference image {len(refs)}" + (f" ({c['description']})" if c.get("description") else "") + ".")
        elif c.get("description"):
            lines.append(f"{c['name']}: {c['description']}.")
    for c in present:      # còn chỗ thì gửi thêm ảnh mẫu thứ hai của nhân vật chính
        for r in (c.get("refs") or [])[1:]:
            if len(refs) < MAX_CHARACTER_REFS:
                refs.append(story["_folder"] / "ref" / r)
    style = ", ".join(x for x in (STYLES.get(story.get("style") or "", ""), story.get("style_note") or "") if x)
    what = scene.get("prompt") or scene.get("text") or ""
    shape = {"9:16": "vertical 9:16", "16:9": "horizontal 16:9", "1:1": "square"}.get(story.get("aspect"), "")
    prompt = " ".join(x for x in (
        f"Illustration for one scene of a story, {shape} composition with the main subject well framed." if shape else "",
        f"Art style: {style}." if style else "",
        f"Scene: {what}",
        " ".join(lines),
        "Keep characters consistent with their references: same face, hair and clothes." if refs else "",
        NO_TEXT,
    ) if x)
    return prompt, [r for r in refs if r.is_file()]


def character_prompt(story: dict, ch: dict) -> str:
    from .imagegen import NO_TEXT
    style = ", ".join(x for x in (STYLES.get(story.get("style") or "", ""), story.get("style_note") or "") if x)
    return (f"Character design reference of {ch['name']}: {ch.get('description') or ''}. Full body standing front view next to a close-up "
            f"portrait of the same character, plain light grey background, even lighting." + (f" Art style: {style}." if style else "") + f" {NO_TEXT}")


def _has_scene(store: StoryStore, sid: str, scene_id: str) -> dict:
    sc = next((x for x in store.get(sid)["scenes"] if x["id"] == scene_id), None)
    if sc is None:
        raise KeyError("Không có cảnh này (có thể vừa bị xóa)")
    return sc


def add_scene_image(store: StoryStore, sid: str, scene_id: str, data: bytes, origin: str) -> str:
    """Lưu ảnh mới cho cảnh, giữ các bản trước để chọn lại. Bản cũ quá số giữ lại thì xóa file luôn."""
    from .imagegen import save
    _has_scene(store, sid, scene_id)
    name = f"{scene_id}_{short_hash(str(time.time()), origin, str(len(data)))}.png"
    path = save(data, store.file(sid, "img", name))
    dropped: list[str] = []

    def fn(s):
        for sc in s["scenes"]:
            if sc["id"] == scene_id:
                allv = [name] + [x for x in sc.get("images") or [] if x != name]
                sc["image"], sc["images"] = name, allv[:MAX_VARIANTS]
                dropped.extend(allv[MAX_VARIANTS:])
                return
        raise KeyError("Cảnh đã bị xóa")
    try:
        store.update(sid, fn)
    except KeyError:
        path.unlink(missing_ok=True)
        raise
    for x in dropped:
        store.file(sid, "img", x).unlink(missing_ok=True)
    return name


def append_image_scene(store: StoryStore, sid: str, data: bytes) -> str:
    """Làm video từ một loạt ảnh có sẵn: mỗi ảnh thành một cảnh mới ở cuối, chưa có lời (im lặng 3 giây, thêm lời sau cũng được)."""
    scene_id = new_id("n")

    def fn(s):
        if len(s["scenes"]) >= MAX_SCENES:
            raise ValueError(f"Một câu chuyện tối đa {MAX_SCENES} cảnh")
        s["scenes"].append({"id": scene_id, "text": "", "prompt": "", "characters": [], "motion": "auto", "image": "", "images": [], "created": _now()})
    store.update(sid, fn)
    return add_scene_image(store, sid, scene_id, data, "upload")


def add_character_ref(store: StoryStore, sid: str, cid: str, data: bytes) -> str:
    """Mỗi nhân vật giữ 4 ảnh mẫu mới nhất. Ảnh đầu tiên được gửi đi trước, nên ảnh mới đưa lên đầu."""
    from .imagegen import save
    if not any(c["id"] == cid for c in store.get(sid)["characters"]):
        raise KeyError("Không có nhân vật này (có thể vừa bị xóa)")
    name = f"{cid}_{short_hash(str(time.time()), str(len(data)))}.png"
    path = save(data, store.file(sid, "ref", name))
    dropped: list[str] = []

    def fn(s):
        for c in s["characters"]:
            if c["id"] == cid:
                allr = (c.get("refs") or []) + [name]
                c["refs"] = allr[-4:]
                dropped.extend(allr[:-4])
                return
        raise KeyError("Nhân vật đã bị xóa")
    try:
        store.update(sid, fn)
    except KeyError:
        path.unlink(missing_ok=True)
        raise
    for x in dropped:
        store.file(sid, "ref", x).unlink(missing_ok=True)
    return name


def generate_scene_image(store: StoryStore, sid: str, scene_id: str, cfg, skip_if_has_image: bool = False) -> str:
    """skip_if_has_image: vẽ hàng loạt thì đọc lại câu chuyện ngay trước khi gọi, cảnh vừa có ảnh (người dùng tải lên) thì bỏ qua, không tốn tiền."""
    from . import imagegen
    s = store.get(sid)
    s["_folder"] = store.folder(sid)
    scene = next((x for x in s["scenes"] if x["id"] == scene_id), None)
    if scene is None:
        raise KeyError("Không có cảnh này")
    if skip_if_has_image and scene.get("image"):
        return ""
    if not (scene.get("prompt") or scene.get("text")):
        raise ValueError("Cảnh chưa có lời dẫn hay mô tả để vẽ")
    prompt, refs = scene_prompt(s, scene)
    model = (cfg.get("story") or {}).get("image_model") or ""
    data, _ = imagegen.generate(prompt, refs, aspect=s.get("aspect") or "9:16", model=model, provider=s.get("image_provider") or "")
    return add_scene_image(store, sid, scene_id, data, "ai")


MAX_CLIPS = 4


def add_scene_clip(store: StoryStore, sid: str, scene_id: str, src: Path, meta: dict) -> str:
    """Đưa clip (mp4 đã chuẩn hóa) vào cảnh, giữ vài bản trước để chọn lại. Cảnh chưa có ảnh thì lấy một khung của clip làm ảnh
    (cảnh mở đầu, kết thúc, ảnh bìa, thumbnail vẫn cần ảnh)."""
    _has_scene(store, sid, scene_id)
    name = f"{scene_id}_{short_hash(str(time.time()), str(meta.get('src')), str(meta.get('id')))}.mp4"
    dst = store.file(sid, "clip", name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    dropped: list[str] = []
    need_poster = [False]

    def fn(s):
        for sc in s["scenes"]:
            if sc["id"] == scene_id:
                allc = [name] + [x for x in sc.get("clips") or [] if x != name]
                sc["clip"], sc["clips"] = name, allc[:MAX_CLIPS]
                dropped.extend(allc[MAX_CLIPS:])
                cm = {k: v for k, v in (sc.get("clip_meta") or {}).items() if k in sc["clips"]}
                cm[name] = {k: meta.get(k) for k in ("src", "id", "title", "author", "author_url", "page", "license", "duration", "source_name", "provider",
                                                    "prompt", "cost", "start") if meta.get(k) not in (None, "")}
                sc["clip_meta"] = cm
                need_poster[0] = not sc.get("image")
                return
        raise KeyError("Cảnh đã bị xóa")
    try:
        store.update(sid, fn)
    except KeyError:
        dst.unlink(missing_ok=True)
        raise
    for x in dropped:
        store.file(sid, "clip", x).unlink(missing_ok=True)
    if need_poster[0]:
        try:
            add_scene_image(store, sid, scene_id, poster_frame(dst), "clip")
        except Exception:      # noqa: BLE001 — không lấy được khung ảnh thì cảnh vẫn dùng clip, chỉ thiếu ảnh bìa
            pass
    return name


def poster_frame(clip: Path, at: float = 0.6) -> bytes:
    import subprocess
    from .util import find_ffmpeg
    p = subprocess.run([find_ffmpeg()[0], "-hide_banner", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(clip), "-frames:v", "1", "-f", "image2pipe",
                        "-vcodec", "png", "-"], capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if p.returncode != 0 or len(p.stdout) < 100:
        raise ValueError("Không lấy được khung ảnh của clip")
    return p.stdout


def use_clip(store: StoryStore, sid: str, scene_id: str, name: str) -> dict:
    """name rỗng: cảnh quay lại dùng ảnh (clip vẫn giữ trong danh sách để chọn lại)."""
    def fn(s):
        for sc in s["scenes"]:
            if sc["id"] == scene_id:
                if name and name not in (sc.get("clips") or []):
                    raise KeyError("Clip này không thuộc cảnh")
                sc["clip"] = name
                return
        raise KeyError("Không có cảnh này")
    return store.update(sid, fn)


def delete_clip(store: StoryStore, sid: str, scene_id: str, name: str) -> dict:
    def fn(s):
        for sc in s["scenes"]:
            if sc["id"] == scene_id:
                sc["clips"] = [x for x in sc.get("clips") or [] if x != name]
                (sc.get("clip_meta") or {}).pop(name, None)
                if sc.get("clip") == name:
                    sc["clip"] = ""
                return
        raise KeyError("Không có cảnh này")
    out = store.update(sid, fn)
    store.file(sid, "clip", name).unlink(missing_ok=True)
    return out


def estimate_seconds(story: dict, scene: dict) -> float:
    """Cảnh sẽ dài bao nhiêu giây (để chọn clip đủ dài, xin AI tạo clip đúng độ dài) khi chưa đọc lời dẫn: theo tốc độ nói của ngôn ngữ."""
    from .langs import count_units, get
    from .speech import readable
    d = _duration(scene.get("duration")) or 0.0
    text = scene.get("text") or ""
    if not readable(text):
        return max(d, 3.0)
    v = story.get("voice") or {}
    lang = v.get("lang") or "vi"
    speed = float(v.get("speed") or 1.0)
    talk = count_units(text, lang) / max(0.5, get(lang)["rate"] * speed)
    return round(max(d, MIN_SCENE, talk + 1.3), 2)


QUERY_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"i": {"type": "integer"}, "q": {"type": "string"}}, "required": ["i", "q"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False}


def broll_queries(cfg, story: dict, scene_ids: list[str]) -> dict[str, str]:
    """Từ khóa tìm video nền cho các cảnh chưa có: nhờ AI (một lần cho cả loạt), không có AI thì rút từ mô tả hình tiếng Anh."""
    from .stock import keywords
    scenes = [sc for sc in story["scenes"] if sc["id"] in scene_ids]
    out = {sc["id"]: sc["broll"] for sc in scenes if (sc.get("broll") or "").strip()}
    todo = [sc for sc in scenes if sc["id"] not in out]
    if not todo:
        return out
    names = [c["name"] for c in story.get("characters") or []]
    try:
        lines = "\n".join(f"{k}. {(sc.get('prompt') or '')[:300]} | {(sc.get('text') or '')[:300]}" for k, sc in enumerate(todo))
        data = _json_by_ai(cfg, "You pick search keywords for free stock footage sites (Pexels, Pixabay). For each numbered scene return 2 to 4 plain "
                           "English words describing real filmable things and places that fit it (e.g. \"rainy city street night\"). "
                           "No character names, no art style words, no abstract ideas. Return JSON only.",
                           "Scenes (image description | narration):\n" + lines, QUERY_SCHEMA, 3000)
        for it in data.get("items") or []:
            k = int(it.get("i", -1))
            q = " ".join(str(it.get("q") or "").split())[:100]
            if 0 <= k < len(todo) and q:
                out[todo[k]["id"]] = q
    except Exception as e:      # noqa: BLE001 — không có AI hay AI lỗi: rút từ mô tả hình
        log("story", f"AI chưa gợi ý được từ khóa video ({str(e)[:80]}), rút từ mô tả hình")
    for sc in todo:
        if sc["id"] not in out:
            q = keywords(sc.get("prompt") or "", names)
            if not q and sc.get("text"):
                try:
                    from .localai import to_english
                    q = keywords(to_english(sc["text"][:300]), names)
                except Exception:      # noqa: BLE001
                    q = ""
            if q:
                out[sc["id"]] = q
    return out


def stock_for_scene(store: StoryStore, sid: str, scene_id: str, item: dict, check=None) -> str:
    """Tải clip đã chọn trong kho vào cảnh."""
    from .stock import fetch
    folder = store.folder(sid) / "clip"
    tmp_name = f"dl_{scene_id}_{uuid.uuid4().hex[:6]}.mp4"
    path, meta = fetch(item, folder, tmp_name, check_cancel=check)
    try:
        return add_scene_clip(store, sid, scene_id, path, meta)
    finally:
        path.unlink(missing_ok=True)


def stock_fill(store: StoryStore, sid: str, cfg, only_missing: bool = True, src: str = "", report=None, check=None,
               skip_characters: bool = True) -> dict:
    """Tự tìm và tải video nền cho các cảnh (chưa có clip). Mỗi clip một cảnh, không lặp clip giữa các cảnh.
    skip_characters: cảnh có nhân vật của câu chuyện thì để vẽ (video quay thật không có nhân vật đó, chèn người lạ vào là lệch truyện).
    Đo thật 11/2026: không bỏ qua thì cảnh "Anh Trung cầm cuốc ra đồng" nhận video một phụ nữ đang nói chuyện."""
    from .stock import StockError, find_for
    report = report or (lambda frac, msg: None)
    story = store.get(sid)
    src = src or story.get("stock_src") or ""
    todo = [sc for sc in story["scenes"] if not (only_missing and sc.get("clip"))]
    kept = [sc for sc in todo if skip_characters and sc.get("characters")]
    todo = [sc for sc in todo if sc not in kept]
    if not todo:
        return {"done": 0, "failed": 0, "kept": len(kept), "error": ""}
    report(0.0, "Tìm từ khóa cho từng cảnh")
    qs = broll_queries(cfg, story, [sc["id"] for sc in todo])

    def keep(s):
        for sc in s["scenes"]:
            if sc["id"] in qs and not (sc.get("broll") or "").strip():
                sc["broll"] = qs[sc["id"]]
    store.update(sid, keep)
    # clip đang dùng ở cảnh khác thì không lấy lại (hai cảnh cùng một clip trông như lỗi); cảnh đang tìm lại thì được chọn lại clip cũ của nó
    todo_ids = {sc["id"] for sc in todo}
    used = {f"{m.get('src')}:{m.get('id')}" for sc in story["scenes"] if sc["id"] not in todo_ids and sc.get("clip")
            for m in [(sc.get("clip_meta") or {}).get(sc["clip"]) or {}]}
    done, errors, missed = 0, [], []
    for k, sc in enumerate(todo):
        if check:
            check()
        q = qs.get(sc["id"]) or ""
        report(0.05 + 0.95 * k / len(todo), f"Cảnh {k + 1}/{len(todo)}: tìm \"{q}\"")
        if not q:
            missed.append(k + 1)
            continue
        try:
            it = find_for(q, story.get("aspect") or "9:16", estimate_seconds(story, sc), used, src)
            if not it:
                missed.append(k + 1)
                continue
            used.add(f"{it['src']}:{it['id']}")
            stock_for_scene(store, sid, sc["id"], it, check)
            done += 1
        except KeyError:
            continue      # cảnh vừa bị xóa
        except StockError as e:
            errors.append(str(e))
            if "key" in str(e).lower() or "giới hạn" in str(e):
                break
    report(1.0, "Xong")
    err = errors[0] if errors else ("Không tìm được clip hợp cho cảnh " + ", ".join(map(str, missed[:10])) + ": sửa từ khóa rồi tìm lại" if missed else "")
    return {"done": done, "failed": len(todo) - done, "kept": len(kept), "error": err}


def animate_scene(store: StoryStore, sid: str, scene_id: str, cfg, report=None, check=None) -> str:
    """AI biến ảnh cảnh thành clip chuyển động (chưa có ảnh: tạo từ mô tả, kèm ảnh mẫu nhân vật)."""
    from . import videogen
    s = store.get(sid)
    s["_folder"] = store.folder(sid)
    sc = next((x for x in s["scenes"] if x["id"] == scene_id), None)
    if sc is None:
        raise KeyError("Không có cảnh này")
    img = store.file(sid, "img", sc["image"]) if sc.get("image") else None
    img = img if img and img.is_file() else None
    if not img and not (sc.get("prompt") or sc.get("text")):
        raise ValueError("Cảnh chưa có ảnh hay mô tả để AI làm clip")
    refs = [] if img else scene_prompt(s, sc)[1]
    secs = videogen.seconds_for(estimate_seconds(s, sc))
    res = s.get("video_res") or videogen.DEFAULT_RES
    prompt = videogen.scene_prompt(s, sc, from_image=bool(img))
    data = videogen.generate(prompt, img, refs, aspect=s.get("aspect") or "9:16", seconds=secs, resolution=res,
                             report=(lambda m: report(None, m)) if report else None, check_cancel=check)
    from .stock import normalize
    folder = store.folder(sid) / "clip"
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / f"ai_{scene_id}_{uuid.uuid4().hex[:6]}.raw.mp4"
    out = raw.with_name(raw.name.replace(".raw", ""))
    raw.write_bytes(data)
    try:
        dur = normalize(raw, out)
    finally:
        raw.unlink(missing_ok=True)
    meta = {"src": "ai", "id": uuid.uuid4().hex[:8], "provider": videogen.PROVIDERS["omni"]["name"], "duration": round(dur, 3),
            "license": "Tạo bằng AI (Google Gemini Omni Flash)", "prompt": prompt[:400], "cost": videogen.price(secs, res)}
    try:
        return add_scene_clip(store, sid, scene_id, out, meta)
    finally:
        out.unlink(missing_ok=True)


def credits(story: dict) -> list[dict]:
    """Nguồn của các clip đang dùng (để ghi công, và làm bằng chứng khi bị khiếu nại bản quyền)."""
    out = []
    for i, sc in enumerate(story.get("scenes") or []):
        m = (sc.get("clip_meta") or {}).get(sc.get("clip") or "")
        if sc.get("clip") and m:
            out.append({"scene": i + 1, **m})
    return out


def credits_text(story: dict) -> str:
    lines = []
    for c in credits(story):
        if c.get("src") == "ai":
            lines.append(f"Cảnh {c['scene']}: clip tạo bằng AI ({c.get('provider') or 'AI'})")
        else:
            who = f" của {c['author']}" if c.get("author") else ""
            at = f" (đoạn từ giây {c['start']:g})" if c.get("start") else ""
            lines.append(f"Cảnh {c['scene']}: \"{c.get('title') or 'video'}\"{who}{at}, {c.get('source_name') or c.get('src')}, giấy phép {c.get('license') or ''}. "
                         f"{c.get('page') or ''}".strip())
    return "\n".join(lines)


def generate_character_ref(store: StoryStore, sid: str, cid: str, cfg) -> str:
    from . import imagegen
    s = store.get(sid)
    ch = next((c for c in s["characters"] if c["id"] == cid), None)
    if ch is None:
        raise KeyError("Không có nhân vật này")
    if not ch.get("description"):
        raise ValueError("Viết mô tả ngoại hình nhân vật trước (tuổi, tóc, quần áo...) rồi mới vẽ ảnh mẫu")
    refs = [store.file(sid, "ref", r) for r in ch.get("refs") or []][:2]      # đã có ảnh mẫu: vẽ thêm góc khác của chính người đó
    data, _ = imagegen.generate(character_prompt(s, ch), refs, aspect="1:1", model=(cfg.get("story") or {}).get("image_model") or "",
                                provider=s.get("image_provider") or "")
    return add_character_ref(store, sid, cid, data)


# ------------------------------------------------------------------ dựng video
def _motion_expr(kind: str, frames: int) -> tuple[str, str, str]:
    """(z, x, y) cho zoompan. Chuyển động nhanh dần rồi chậm dần (smoothstep) cho tự nhiên."""
    n1 = max(1, frames - 1)
    p = f"(on/{n1})"
    e = f"({p}*{p}*(3-2*{p}))"
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if kind == "zoom_in":
        return f"1+{ZOOM}*{e}", cx, cy
    if kind == "zoom_out":
        return f"1+{ZOOM}*(1-{e})", cx, cy
    if kind == "pan_right":
        return f"{1 + ZOOM}", f"(iw-iw/zoom)*{e}", cy
    if kind == "pan_left":
        return f"{1 + ZOOM}", f"(iw-iw/zoom)*(1-{e})", cy
    if kind == "pan_down":
        return f"{1 + ZOOM}", cx, f"(ih-ih/zoom)*{e}"
    if kind == "pan_up":
        return f"{1 + ZOOM}", cx, f"(ih-ih/zoom)*(1-{e})"
    return "1", "0", "0"


CLIP_STRETCH = 1.3      # clip ngắn hơn cảnh tới 30% thì làm chậm lại cho vừa (mắt không nhận ra), dài hơn nữa thì lặp lại


def _clip_chain(idx: int, W: int, H: int, fit: str, frames: int, clip_dur: float, dim: bool = False) -> str:
    """Cảnh dùng clip: phủ kín khung (hoặc nền mờ), đúng số khung của cảnh. Clip hơi ngắn thì chậm lại, ngắn nhiều thì đã được lặp từ đầu vào."""
    need = frames / FPS
    slow = need / clip_dur if clip_dur and clip_dur < need <= clip_dur * CLIP_STRETCH else 1.0
    pts = f"setpts={slow:.4f}*(PTS-STARTPTS)," if slow > 1.0 else "setpts=PTS-STARTPTS,"
    if fit == "blur":
        body = (f"[{idx}:v]{pts}fps={FPS},split=2[b{idx}][f{idx}];[b{idx}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:2[bb{idx}];"
                f"[f{idx}]scale={W}:{H}:force_original_aspect_ratio=decrease[ff{idx}];[bb{idx}][ff{idx}]overlay=(W-w)/2:(H-h)/2")
    else:
        body = f"[{idx}:v]{pts}fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}"
    if dim:
        body += ",boxblur=30:2,eq=brightness=-0.16:saturation=0.75"
    return f"{body},setsar=1,format=yuv420p,trim=end_frame={frames},setpts=PTS-STARTPTS[v{idx}]"


def _clip_input(rel: str, frames: int, clip_dur: float) -> list:
    """Clip ngắn hơn nhiều so với cảnh: lặp lại từ đầu (đầu vào lặp vô hạn, cắt đúng số khung trong bộ lọc)."""
    need = frames / FPS
    loop = clip_dur and need > clip_dur * CLIP_STRETCH
    return (["-stream_loop", "-1"] if loop else []) + ["-i", rel]


def _seg_clip(store_folder: Path, sg: dict) -> tuple[str, float] | None:
    c = sg.get("clip")
    if not c:
        return None
    f = store_folder / "clip" / c["name"]
    return (f"clip/{c['name']}", float(c.get("duration") or 0)) if f.is_file() else None


def _scene_motion(scene: dict, i: int) -> str:
    m = scene.get("motion") or "auto"
    return AUTO_CYCLE[i % len(AUTO_CYCLE)] if m == "auto" else m


def _image_chain(idx: int, W: int, H: int, fit: str, motion: str, frames: int, dim: bool = False) -> str:
    """dim: cảnh mở đầu, kết thúc: ảnh mờ và tối đi để chữ lớn đọc rõ."""
    PW, PH = W * PRE_SCALE, H * PRE_SCALE
    if fit == "blur":
        fill = (f"[{idx}:v]split=2[b{idx}][f{idx}];[b{idx}]scale={PW}:{PH}:force_original_aspect_ratio=increase,crop={PW}:{PH},boxblur=40:2[bb{idx}];"
                f"[f{idx}]scale={PW}:{PH}:force_original_aspect_ratio=decrease[ff{idx}];[bb{idx}][ff{idx}]overlay=(W-w)/2:(H-h)/2")
    else:
        fill = f"[{idx}:v]scale={PW}:{PH}:force_original_aspect_ratio=increase,crop={PW}:{PH}"
    z, x, y = _motion_expr(motion, frames)
    if dim:
        fill += ",boxblur=30:2,eq=brightness=-0.16:saturation=0.75"
    return (f"{fill},setsar=1,format=yuv420p,zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},"
            f"trim=end_frame={frames},setpts=PTS-STARTPTS,format=yuv420p[v{idx}]")


def narrate(store: StoryStore, sid: str, story: dict, on_step=None) -> list[dict]:
    """Lời dẫn từng cảnh (có cache). -> [{wav, dur, timings}] theo thứ tự cảnh; cảnh không có lời thì wav None."""
    from .speech import speech_key, synthesize
    v = story.get("voice") or {}
    engine, voice, speed = v.get("engine") or "vieneu", v.get("voice") or "", float(v.get("speed") or 1.0)
    lang = v.get("lang") or "vi"
    if engine == "vox" or (lang != "vi" and engine == "vieneu"):      # VieNeu chỉ đọc tiếng Việt (giống voice.engine_for)
        from .voxtts import ready as vox_ready
        engine = "vox" if vox_ready() else "edge" if lang != "vi" else "vieneu"
    audio_dir = store.folder(sid) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    out = []
    from .speech import readable as _readable
    todo = [sc for sc in story["scenes"] if _readable(sc.get("text", ""))]
    done = 0
    from .speech import readable
    for sc in story["scenes"]:
        check_cancel()
        text = sc.get("text", "").strip()
        if not readable(text):      # trống, hoặc chỉ "..." "***" biểu tượng cảm xúc: cảnh im lặng
            out.append({"wav": None, "dur": 0.0, "timings": []})
            continue
        wav = audio_dir / f"{sc['id']}_{speech_key(text, engine, voice, speed)}.wav"
        meta = wav.with_suffix(".json")
        if wav.exists() and meta.exists():
            timings = [tuple(t) for t in json.loads(meta.read_text(encoding="utf-8"))["timings"]]
        else:
            timings = synthesize(text, wav, engine=engine, voice=voice, speed=speed, cache=store.root / ".speech_cache", report=False)
        data, sr = read_wav(wav)
        out.append({"wav": wav, "dur": data.shape[0] / sr, "timings": timings})
        done += 1
        if on_step:
            on_step(done, len(todo))
    return out


SILENT = {"wav": None, "dur": 0.0, "timings": []}


def segments(story: dict, voices: list[dict]) -> list[dict]:
    """Các đoạn của video theo thứ tự: cảnh mở đầu (nếu bật), từng cảnh, cảnh kết thúc (nếu bật).
    Mở đầu dùng ảnh cảnh đầu làm mờ, kết thúc dùng ảnh cảnh cuối làm mờ, chữ lớn ở giữa."""
    scenes = story["scenes"]
    trans = story.get("transition") if story.get("transition") in TRANSITIONS else "fade"
    out = []
    intro, outro = story.get("intro") or {}, story.get("outro") or {}
    if intro.get("enabled") and scenes:
        out.append({"kind": "intro", "image": scenes[0].get("image"), "voice": SILENT, "min": INTRO_DUR, "trans": trans, "motion": "zoom_in",
                    "text": intro.get("text") or story.get("title") or "", "sub": intro.get("sub") or ""})
    for i, (sc, v) in enumerate(zip(scenes, voices)):
        clip = None
        if sc.get("clip"):
            m = (sc.get("clip_meta") or {}).get(sc["clip"]) or {}
            clip = {"name": sc["clip"], "duration": float(m.get("duration") or 0)}
        out.append({"kind": "scene", "id": sc.get("id"), "image": sc.get("image"), "voice": v, "min": _duration(sc.get("duration")),
                    "trans": sc.get("transition") or trans, "motion": _scene_motion(sc, i), "clip": clip})
    if outro.get("enabled") and scenes:
        out.append({"kind": "outro", "image": scenes[-1].get("image"), "voice": SILENT, "min": OUTRO_DUR, "trans": trans, "motion": "zoom_out",
                    "text": outro.get("text") or DEFAULT_OUTRO, "sub": outro.get("sub") or ""})
    return out


def _trans_len(seg: dict, story: dict) -> float:
    if story.get("_cut"):
        return 0.0      # gói cho Trình dựng: các đoạn nối thẳng, chuyển cảnh thêm trong Trình dựng
    if seg["trans"] == "none":
        return 2 / FPS      # cắt thẳng: xfade 2 khung, mắt thấy như cắt
    try:
        return min(1.5, max(0.2, float(story.get("trans_dur") or TRANS)))
    except (TypeError, ValueError):
        return TRANS


def plan_segments(story: dict, segs: list[dict]) -> list[dict]:
    """Thời điểm của từng đoạn. Lời dẫn bắt đầu sau khi chuyển cảnh vào xong, kết thúc trước khi chuyển sang đoạn sau.
    Cảnh có lời: dài theo lời, thời lượng người dùng đặt là tối thiểu (lời không bao giờ bị cắt). Cảnh im lặng: đúng thời lượng đặt, mặc định 3 giây."""
    out = []
    t = 0.0
    n = len(segs)
    for i, sg in enumerate(segs):
        td_in = _trans_len(sg, story) if i else 0.0
        td_out = _trans_len(segs[i + 1], story) if i < n - 1 else 0.0
        lead = 0.3 + td_in
        v = sg["voice"]
        if v["wav"]:
            dur = max(MIN_SCENE, lead + v["dur"] + 0.45 + (td_out if i < n - 1 else 0.8), sg.get("min") or 0)
        else:
            dur = max(sg.get("min") or 3.0, td_in + td_out + 0.5)
        frames = int(round(dur * FPS))
        dur = frames / FPS
        out.append({"start": t, "dur": dur, "frames": frames, "voice_at": t + lead, "trans_in": td_in})
        t += dur - td_out
    return out


def plan(story: dict, voices: list[dict]) -> list[dict]:
    return plan_segments(story, segments(story, voices))


def build_audio(voices: list[dict], times: list[dict], total: float, out: Path) -> Path:
    from .speech import SR
    track = np.zeros(int((total + 0.5) * SR), np.float32)
    for v, tm in zip(voices, times):
        if not v["wav"]:
            continue
        data, _ = read_wav(v["wav"])
        data = data.reshape(-1).astype(np.float32)
        a = int(tm["voice_at"] * SR)
        track[a:a + data.size] += data[: max(0, track.size - a)]
    write_wav(out, np.clip(track, -1, 1), SR)
    return out


def subtitle_items(voices: list[dict], times: list[dict], aspect: str) -> list[tuple]:
    from .speech import timed_lines
    max_chars = 30 if aspect == "9:16" else 42 if aspect == "16:9" else 34
    items = []
    for v, tm in zip(voices, times):
        lines = timed_lines(v["timings"], max_chars)
        for k, (st, en, text) in enumerate(lines):
            speech_end = tm["voice_at"] + en
            if k + 1 < len(lines) and lines[k + 1][0] - en < 0.7:      # khoảng nghỉ ngắn giữa hai đoạn: giữ dòng cũ tới dòng sau, không chớp tắt
                en = lines[k + 1][0]
            items.append((tm["voice_at"] + st, tm["voice_at"] + en, text, speech_end))
    return items


_FF_MAJOR: list[int] = []


def _ffmpeg_major() -> int:
    """Bản ffmpeg 7 trở lên mới đọc được -/filter_complex từ file; bản cũ dùng -filter_complex_script."""
    if not _FF_MAJOR:
        import subprocess
        from .util import find_ffmpeg
        try:
            first = subprocess.run([find_ffmpeg()[0], "-version"], capture_output=True, text=True, timeout=20).stdout.split("\n")[0]
            m = re.search(r"version\s+n?(\d+)\.", first)
            _FF_MAJOR.append(int(m.group(1)) if m else 7)
        except (OSError, ValueError, subprocess.SubprocessError):
            _FF_MAJOR.append(7)
    return _FF_MAJOR[0]


def card_overlays(segs: list[dict], times: list[dict], aspect: str) -> list[dict]:
    """Chữ của cảnh mở đầu và kết thúc, vẽ bằng lớp chữ ASS (cùng cách với lớp chữ trong Studio)."""
    big = {"9:16": 0.05, "16:9": 0.085, "1:1": 0.065}.get(aspect, 0.06)
    out = []
    for sg, tm in zip(segs, times):
        if sg["kind"] not in ("intro", "outro"):
            continue
        st, en = tm["start"] + tm["trans_in"] * 0.6, tm["start"] + tm["dur"] - 0.15
        if sg.get("text"):
            out.append({"type": "text", "text": sg["text"], "start": st, "end": en, "x": 0.5, "y": 0.44 if sg.get("sub") else 0.5, "size": big,
                        "bold": True, "color": "#FFFFFF", "fade": 0.35})
        if sg.get("sub"):
            out.append({"type": "text", "text": sg["sub"], "start": st + 0.25, "end": en, "x": 0.5, "y": 0.56, "size": big * 0.55, "bold": False,
                        "color": "#FFB224", "fade": 0.35})
    return out


def _has_visual(store: StoryStore, sid: str, sc: dict) -> bool:
    if sc.get("clip") and store.file(sid, "clip", sc["clip"]).exists():
        return True
    return bool(sc.get("image")) and store.file(sid, "img", sc["image"]).exists()


def _check_images(store: StoryStore, sid: str, scenes: list[dict]) -> None:
    if not scenes:
        raise ValueError("Câu chuyện chưa có cảnh nào")
    missing = [i + 1 for i, sc in enumerate(scenes) if not _has_visual(store, sid, sc)]
    if not missing:
        # mở đầu, kết thúc dùng ảnh cảnh đầu, cuối: cảnh chỉ có clip mà mất ảnh thì lấy lại một khung của clip
        for sc in (scenes[0], scenes[-1]):
            if not (sc.get("image") and store.file(sid, "img", sc["image"]).exists()) and sc.get("clip"):
                try:
                    sc["image"] = add_scene_image(store, sid, sc["id"], poster_frame(store.file(sid, "clip", sc["clip"])), "clip")
                except Exception:      # noqa: BLE001
                    pass
    if missing:
        raise ValueError("Cảnh " + ", ".join(map(str, missing[:12])) + " chưa có ảnh")


def _encoder_args() -> tuple[str, list]:
    from .render import auto_encoder, nvenc_available
    encoder = "h264_nvenc" if nvenc_available() else auto_encoder()
    if encoder == "libx264":
        return encoder, ["-c:v", encoder, "-crf", 19, "-preset", "medium"]
    if "videotoolbox" in encoder:
        return encoder, ["-c:v", encoder, "-q:v", "65", "-allow_sw", "1"]
    return encoder, ["-c:v", encoder, "-rc", "vbr", "-cq", 21, "-preset", "p5", "-b:v", "0"]


def render_story(store: StoryStore, sid: str, cfg, output_dir: Path) -> Path:
    from .config import with_overrides
    from .models import write_ass, write_srt
    from .render import _filter_path
    from .util import ROOT, replace_file

    story = store.get(sid)
    scenes = story["scenes"]
    _check_images(store, sid, scenes)
    folder = store.folder(sid)
    W, H = SIZES.get(story.get("aspect"), SIZES["9:16"])

    stage("tts")
    log("story", f"Lời dẫn cho {len(scenes)} cảnh")
    voices = narrate(store, sid, story, on_step=lambda n, k: progress("tts", n / max(1, k)))
    segs = segments(story, voices)
    times = plan_segments(story, segs)
    total = times[-1]["start"] + times[-1]["dur"]

    stage("render")
    work = folder / "render"
    work.mkdir(exist_ok=True)
    seg_voices = [sg["voice"] for sg in segs]
    narration = build_audio(seg_voices, times, total, work / "narration.wav")
    ecfg = with_overrides(cfg, {"edit": {"sub_style": (story.get("subs") or {}).get("style") or "box"}}).edit
    subs = subtitle_items(seg_voices, times, story.get("aspect"))
    sub_on = (story.get("subs") or {}).get("enabled", True) and bool(subs)
    cards = card_overlays(segs, times, story.get("aspect"))
    ass_on = sub_on or bool(cards)
    if ass_on:
        write_ass(work / "subs.ass", subs if sub_on else [], W, H, ecfg, total=total, overlays=cards)

    # đường dẫn tương đối, chạy ffmpeg trong thư mục câu chuyện: lệnh ngắn (200 cảnh với đường dẫn dài vẫn dưới giới hạn của Windows) và tên
    # thư mục có chữ tiếng Việt hay dấu nháy không phải thoát trong đồ thị bộ lọc
    inputs: list = []
    chains = []
    for i, (sg, tm) in enumerate(zip(segs, times)):
        cl = _seg_clip(folder, sg)
        if cl:
            inputs += _clip_input(cl[0], tm["frames"], cl[1])
            chains.append(_clip_chain(i, W, H, story.get("fit") or "cover", tm["frames"], cl[1], dim=sg["kind"] != "scene"))
        else:
            inputs += ["-i", f"img/{sg['image']}"]
            chains.append(_image_chain(i, W, H, story.get("fit") or "cover", sg["motion"], tm["frames"], dim=sg["kind"] != "scene"))
    n = len(segs)
    graph = ";".join(chains)
    last = "[v0]"
    for i in range(1, n):
        kind = "fade" if segs[i]["trans"] == "none" else segs[i]["trans"]
        graph += f";{last}[v{i}]xfade=transition={kind}:duration={times[i]['trans_in']:.4f}:offset={times[i]['start']:.3f}[x{i}]"
        last = f"[x{i}]"
    vchain = f"{last}"
    if ass_on:
        fd = ""
        if ecfg.get("fontsdir"):
            rel = Path(ecfg.fontsdir)
            fd = ":fontsdir=" + _filter_path(rel if rel.is_absolute() else ROOT / rel)
        graph += f";{vchain}ass=render/subs.ass{fd}[vout]"
    else:
        graph += f";{vchain}null[vout]"
    a_idx = n      # số đầu vào hình (cả mở đầu, kết thúc): tiếng đứng ngay sau
    inputs += ["-i", "render/narration.wav"]
    music = _music_path((story.get("music") or {}).get("path"))
    mvol = (story.get("music") or {}).get("volume")
    mv = 0.12 if mvol is None else float(mvol)      # 0 nghĩa là tắt nhạc, không phải "dùng mặc định"
    if music and mv > 0:
        inputs += ["-stream_loop", "-1", "-i", music]
        fade_at = max(0.0, total - 2.0)
        graph += (f";[{a_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[n1][n2];"
                  f"[{a_idx + 1}:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{total:.3f},volume={mv:.3f},afade=t=out:st={fade_at:.3f}:d=2[m0];"
                  f"[m0][n2]sidechaincompress=threshold=0.04:ratio=5:attack=30:release=500[md];"
                  f"[n1][md]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[aout]")
    else:
        graph += f";[{a_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,alimiter=limit=0.95[aout]"

    encoder, enc = _encoder_args()
    output_dir.mkdir(parents=True, exist_ok=True)
    # mã câu chuyện trong tên: hai câu chuyện cùng tên (mặc định là "Câu chuyện mới") không ghi đè video của nhau
    out = output_dir / f"kechuyen_{safe_name(story.get('title') or sid, 60).strip(' .')}_{sid[1:6]}.mp4"
    tmp = work / "out.part.mp4"
    log("story", f"Dựng {len(scenes)} cảnh" + (" kèm mở đầu" if segs[0]["kind"] == "intro" else "") + (", kết thúc" if segs[-1]["kind"] == "outro" else "")
        + f" thành {W}x{H}, {total:.1f} giây, {encoder}")
    (work / "graph.txt").write_text(graph, encoding="utf-8")
    try:
        graph_opt = "-/filter_complex" if _ffmpeg_major() >= 7 else "-filter_complex_script"
        ffmpeg([*inputs, graph_opt, "render/graph.txt", "-map", "[vout]", "-map", "[aout]", "-r", FPS, "-pix_fmt", "yuv420p",
                *enc, "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(tmp.resolve())],
               cwd=folder, progress_stage="render", total=total)
        replace_file(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    write_srt(out.with_suffix(".srt"), [(a, b, t) for a, b, t, _ in subs])
    cred = credits_text(story)
    src_file = out.with_name(out.stem + ".nguon.txt")
    if cred:
        src_file.write_text("Nguồn các clip trong video (giữ lại để làm bằng chứng khi bị khiếu nại bản quyền):\n\n" + cred + "\n", encoding="utf-8")
    else:
        src_file.unlink(missing_ok=True)

    def fn(s):
        s["output"] = str(out.resolve())
        s["rendered"] = _now()
    store.update(sid, fn)
    log("story", f"Xong: {out.name}")
    return out


# ------------------------------------------------------------------ gói cho Trình dựng (FreeCut)
EDITOR_PACK = "editor"
EDITOR_MANIFEST = "editor.json"
DUCK_DB = -10.0      # nhạc nền nhỏ đi chừng này khi có lời dẫn (Trình dựng tự làm, như sidechain khi dựng video)


def editor_signature(story: dict) -> str:
    """Những gì làm gói Trình dựng khác đi. Kiểu chuyển cảnh không có ở đây: trong gói các đoạn nối thẳng."""
    keep = {k: story.get(k) for k in ("title", "aspect", "fit", "voice", "subs", "intro", "outro", "music")}
    keep["scenes"] = [{k: sc.get(k) for k in ("id", "text", "image", "motion", "duration", "clip")} for sc in story.get("scenes") or []]
    return short_hash(json.dumps(keep, ensure_ascii=False, sort_keys=True))


def editor_pack_ready(store: StoryStore, sid: str) -> dict | None:
    """Gói đã dựng và còn khớp với câu chuyện hiện tại thì trả về bảng kê, không thì None."""
    story = store.get(sid)
    f = store.folder(sid) / EDITOR_PACK / EDITOR_MANIFEST
    try:
        m = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if m.get("sig") != editor_signature(story):
        return None
    if not all((f.parent / x["file"]).is_file() for x in m.get("segments") or []):
        return None
    music = m.get("music")
    if music and not Path(music.get("path") or "").is_file():
        return None
    return m


def _render_clip(folder: Path, sg: dict, tm: dict, W: int, H: int, fit: str, enc: list, out: Path) -> None:
    """Một đoạn: ảnh có máy quay chuyển động, kèm lời dẫn của đoạn đó (đặt đúng chỗ như trong video dựng sẵn)."""
    import os
    from .util import replace_file
    dur = tm["frames"] / FPS
    cl = _seg_clip(folder, sg)
    if cl:
        inputs = _clip_input(cl[0], tm["frames"], cl[1])
        graph = _clip_chain(0, W, H, fit, tm["frames"], cl[1], dim=sg["kind"] != "scene")
    else:
        inputs = ["-i", f"img/{sg['image']}"]
        graph = _image_chain(0, W, H, fit, sg["motion"], tm["frames"], dim=sg["kind"] != "scene")
    maps = ["-map", "[v0]"]
    wav = sg["voice"]["wav"]
    if wav:
        lead_ms = int(round((tm["voice_at"] - tm["start"]) * 1000))
        inputs += ["-i", Path(os.path.relpath(Path(wav).resolve(), folder.resolve())).as_posix()]
        graph += f";[1:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={lead_ms}:all=1,apad,atrim=0:{dur:.3f}[a]"
    else:      # đoạn im lặng vẫn có tiếng câm: trình dựng giải mã tiếng của mọi clip khi xuất, clip không có tiếng thì báo lỗi
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        graph += f";[1:a]atrim=0:{dur:.3f}[a]"
    maps += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    tmp = out.with_name(out.stem + ".part.mp4")
    try:
        ffmpeg([*inputs, "-filter_complex", graph, *maps, "-r", FPS, "-pix_fmt", "yuv420p", *enc, "-t", f"{dur:.3f}", "-movflags", "+faststart",
                str(tmp.resolve())], cwd=folder)
        replace_file(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)


def build_editor_pack(store: StoryStore, sid: str, cfg, report=None) -> dict:
    """Chuẩn bị câu chuyện để mở trong Trình dựng: mỗi đoạn (mở đầu, từng cảnh, kết thúc) là một video ngắn có máy quay chuyển động và
    lời dẫn riêng, nên trong Trình dựng kéo đổi chỗ, cắt, xóa từng cảnh được. Phụ đề theo từng cảnh, chữ mở đầu và kết thúc là lớp chữ
    sửa được, nhạc nền một track riêng. Đoạn nào không đổi thì dùng lại video đã dựng lần trước."""
    from .config import with_overrides
    from .models import auto_margin_v, style_font_size
    from .util import probe, replace_file
    report = report or (lambda frac, msg: None)
    story = store.get(sid)
    scenes = story["scenes"]
    _check_images(store, sid, scenes)
    sig = editor_signature(story)
    folder = store.folder(sid)
    W, H = SIZES.get(story.get("aspect"), SIZES["9:16"])
    fit = story.get("fit") or "cover"

    report(0.0, "Lời dẫn")
    voices = narrate(store, sid, story, on_step=lambda n, k: report(0.6 * n / max(1, k), f"Lời dẫn {n}/{k} cảnh"))
    segs = segments(story, voices)
    times = plan_segments({**story, "_cut": True}, segs)
    pack = folder / EDITOR_PACK
    pack.mkdir(exist_ok=True)
    _, enc = _encoder_args()
    sub_on = (story.get("subs") or {}).get("enabled", True)
    cards = card_overlays(segs, times, story.get("aspect"))
    items, keep = [], {EDITOR_MANIFEST}
    for i, (sg, tm) in enumerate(zip(segs, times)):
        check_cancel()
        wav = sg["voice"]["wav"]
        key = short_hash("2", sg["image"] or "", (sg.get("clip") or {}).get("name") or "", sg["motion"], str(tm["frames"]), f"{W}x{H}", fit, sg["kind"], Path(wav).name if wav else "",
                         f"{tm['voice_at'] - tm['start']:.3f}")      # "2": đoạn im lặng có tiếng câm
        name = f"{i:03d}_{sg['kind']}_{key}.mp4"
        keep.add(name)
        if not (pack / name).exists():
            _render_clip(folder, sg, tm, W, H, fit, enc, pack / name)
        report(0.6 + 0.38 * (i + 1) / len(segs), f"Dựng đoạn {i + 1}/{len(segs)}")
        st0 = tm["start"]
        it = {"kind": sg["kind"], "scene": sg.get("id"), "file": name, "start": round(st0, 4), "frames": tm["frames"], "has_audio": bool(wav),
              "cues": [], "texts": []}
        if sub_on and wav:
            for k, (a, b, text, _) in enumerate(subtitle_items([sg["voice"]], [tm], story.get("aspect"))):
                it["cues"].append({"id": f"{i}-{k}", "startSeconds": round(a - st0, 3), "endSeconds": round(b - st0, 3), "text": text})
        end = st0 + tm["dur"]
        for c in cards:
            if st0 - 1e-6 <= c["start"] < end:
                it["texts"].append({"text": c["text"], "start": round(c["start"] - st0, 3), "end": round(min(c["end"], end) - st0, 3), "y": c["y"],
                                    "size": round(c["size"] * H), "bold": c["bold"], "color": c["color"]})
        items.append(it)
    total = times[-1]["start"] + times[-1]["dur"]

    music = None
    mpath = _music_path((story.get("music") or {}).get("path"))
    mvol = (story.get("music") or {}).get("volume")
    mv = 0.12 if mvol is None else float(mvol)
    if mpath and mv > 0:
        try:
            mdur = float(probe(mpath).get("duration") or 0)
        except Exception:      # ffprobe không đọc được: bỏ nhạc, không hỏng cả gói
            mdur = 0.0
        if mdur > 0.5:
            music = {"path": mpath, "name": Path(mpath).name, "duration": round(mdur, 3), "volume_db": round(max(-60.0, 20 * float(np.log10(mv))), 1),
                     "duck_db": DUCK_DB}
    ecfg = with_overrides(cfg, {"edit": {"sub_style": (story.get("subs") or {}).get("style") or "box"}}).edit
    manifest = {"story": sid, "name": safe_name(story.get("title") or "Câu chuyện", 80), "width": W, "height": H, "fps": FPS, "duration": round(total, 4),
                "segments": items, "music": music, "sub_style": {"font_size": style_font_size(W, H, ecfg), "bottom": H - auto_margin_v(W, H, ecfg)},
                "sig": sig}
    tmp = pack / f"{EDITOR_MANIFEST}.part"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    replace_file(tmp, pack / EDITOR_MANIFEST)
    for f in pack.iterdir():      # đoạn cũ không còn dùng
        if f.is_file() and f.name not in keep:
            f.unlink(missing_ok=True)
    report(1.0, "Xong")
    return manifest

