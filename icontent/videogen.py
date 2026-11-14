"""Tạo clip video bằng AI qua API chính thức, dùng key của chính người dùng.

  omni   Google Gemini Omni Flash (gemini-omni-1.2-flash), thay Veo 3.1 (Google tắt bản thử Veo trong Gemini API ngày 22/10/2026).
         3 đến 15 giây, có tiếng (iContent tắt tiếng clip, lời dẫn là chính). Biến ảnh cảnh thành clip chuyển động (giữ đúng nhân vật
         đã vẽ), hoặc tạo từ chữ kèm tối đa 6 ảnh mẫu nhân vật. Không có gói miễn phí: key Gemini phải bật thanh toán.
         Giá (bảng giá Google 11/2026): 360p ~0,023 USD/giây, 720p ~0,07, 1080p ~0,104.

Không điều khiển trang web của bên nào (Muse, Kling, Veo trên web...) thay người dùng: trái điều khoản, tài khoản bị khóa, hỏng khi họ đổi giao diện.
Meta Muse Video chưa có API chính thức (11/2026); bên nào mở API thì thêm vào PROVIDERS.

Chạy nền (background) rồi hỏi lại mỗi vài giây: clip mất vài phút, giữ một kết nối chờ lâu thì dễ đứt giữa chừng mà vẫn bị tính tiền.
Không gửi lại khi không chắc yêu cầu trước chưa tới nơi (giống imagegen.py).
"""
from __future__ import annotations

import base64
import json
import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://generativelanguage.googleapis.com/v1beta"
MODEL = "gemini-omni-1.2-flash"
POLL = 5.0
MAX_WAIT = 20 * 60

PROVIDERS = {
    "omni": {"name": "Google Gemini Omni Flash", "model": MODEL, "keys": ["GEMINI_API_KEY"], "min": 3, "max": 15, "refs": 6,
             "price": {"360p": 0.023, "720p": 0.07, "1080p": 0.104}, "get": "aistudio.google.com/apikey",
             "note": "Cần key Gemini đã bật thanh toán (gói miễn phí của Google không tạo video)"},
}
RESOLUTIONS = ("360p", "720p", "1080p")
DEFAULT_RES = "720p"


class VideoGenError(RuntimeError):
    pass


def _key(name: str) -> str:
    return os.environ.get(name, "").strip()


def ready(provider: str = "omni") -> bool:
    p = PROVIDERS.get(provider)
    return bool(p) and all(_key(k) for k in p["keys"])


STATUS_FILE = Path(__file__).resolve().parent.parent / "assets" / ".videogen_status.json"


def _fingerprint(prov: str) -> str:
    import hashlib
    return hashlib.sha1("|".join(os.environ.get(k, "") for k in PROVIDERS[prov]["keys"]).encode("utf-8")).hexdigest()[:12]


def _remember(prov: str, state: str, msg: str = "") -> None:
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[prov] = {"state": state, "msg": msg[:300], "at": round(time.time(), 1), "fp": _fingerprint(prov)}
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def status(prov: str) -> dict:
    try:
        st = json.loads(STATUS_FILE.read_text(encoding="utf-8")).get(prov) or {}
    except (OSError, ValueError):
        return {}
    return st if st.get("fp") == _fingerprint(prov) else {}


def usable(provider: str = "omni") -> bool:
    from .paid import allowed
    return ready(provider) and allowed()


def public() -> list[dict]:
    out = []
    for k, v in PROVIDERS.items():
        st = status(k) if ready(k) else {}
        out.append({"id": k, "name": v["name"], "ready": ready(k), "usable": usable(k), "min": v["min"], "max": v["max"], "price": v["price"], "note": v["note"],
                    "keys": v["keys"], "get": v["get"], "status": st.get("state") or "", "status_msg": st.get("msg") or ""})
    return out


def seconds_for(need: float, provider: str = "omni") -> int:
    """Độ dài clip xin tạo cho một cảnh dài need giây: làm tròn lên, trong khoảng nhà cung cấp cho phép.
    Cảnh dài hơn mức tối đa thì clip được làm chậm lại một chút hoặc lặp khi dựng (story.py)."""
    p = PROVIDERS[provider]
    return int(min(p["max"], max(p["min"], math.ceil(need - 0.05))))


def price(seconds: float, resolution: str = DEFAULT_RES, provider: str = "omni") -> float:
    return round(seconds * PROVIDERS[provider]["price"].get(resolution, PROVIDERS[provider]["price"][DEFAULT_RES]), 3)


# ------------------------------------------------------------------ gọi mạng
class _Http(Exception):
    def __init__(self, code: int, body: str):
        super().__init__(f"HTTP {code}")
        self.code, self.body = code, body


def _req(method: str, url: str, body: dict | None = None, timeout: float = 120, raw: bool = False):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"x-goog-api-key": _key("GEMINI_API_KEY"), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            return payload if raw else json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise _Http(e.code, e.read().decode("utf-8", "replace")) from None


def _err(body: str) -> dict:
    try:
        e = json.loads(body).get("error") or {}
        return e if isinstance(e, dict) else {"message": str(e)}
    except (ValueError, AttributeError):
        return {"message": body[:300]}


def friendly(code: int, body: str) -> str:
    err = _err(body)
    msg = str(err.get("message") or body)
    low = msg.lower()
    st = str(err.get("status") or err.get("code") or "")
    if "free tier" in low or "free_tier" in low or "limit: 0" in low or "billing" in low or st == "FAILED_PRECONDITION":
        return ("Key Gemini đang ở gói miễn phí: Google không cho tạo video ở gói này. Vào aistudio.google.com, mục Billing, bật thanh toán cho "
                "project của key (tính theo giây video, 720p khoảng 0,07 USD/giây) rồi thử lại.")
    if code in (401, 403) or "api key not valid" in low or st in ("PERMISSION_DENIED", "UNAUTHENTICATED"):
        return "Key Gemini không hợp lệ hoặc không có quyền tạo video. Kiểm tra lại key trong Cài đặt."
    if code == 404:
        return "Google không còn model tạo video này. Cập nhật iContent."
    if code == 429:
        return "Google đang giới hạn số video mỗi phút. Đợi một lát rồi tạo tiếp."
    if code >= 500:
        return "Máy chủ Google đang lỗi tạm thời. Thử lại sau ít phút."
    return f"Google từ chối yêu cầu tạo video: {msg[:200]}"


def _failed_msg(final: dict) -> str:
    errs = final.get("errors") or ([final["error"]] if isinstance(final.get("error"), dict) else [])
    codes = " ".join(str(e.get("code") or "") for e in errs if isinstance(e, dict))
    text = " ".join(str(e.get("message") or "") for e in errs if isinstance(e, dict))
    if "RESOURCE_EXHAUSTED" in codes:
        # đo thật 11/2026: key gói miễn phí chạy nền thì báo đúng lỗi này (chạy trực tiếp thì báo rõ "Free Tier, limit: 0")
        return ("Google từ chối vì hết hạn mức: key Gemini chưa bật thanh toán (gói miễn phí không tạo video), hoặc đã dùng hết hạn mức trong phút. "
                "Bật thanh toán ở aistudio.google.com, mục Billing, rồi thử lại. Lần này không bị tính tiền.")
    if any(w in (codes + text).lower() for w in ("safety", "blocked", "prohibited", "policy")):
        return "Google không tạo cảnh này vì bộ lọc an toàn (người nổi tiếng, trẻ em, nội dung nhạy cảm...). Sửa mô tả hoặc ảnh rồi thử lại."
    return "Google không tạo được video: " + (text[:200] or codes or "không rõ lý do")


def _find_video(node, only_output: bool = True) -> dict | None:
    """Video trong bước model_output (không nhặt nhầm ảnh, video người dùng gửi đi nếu máy chủ trả kèm lại)."""
    if only_output and isinstance(node, dict) and isinstance(node.get("steps"), list):
        outs = [s for s in node["steps"] if isinstance(s, dict) and s.get("type") == "model_output"]
        return _find_video(outs, only_output=False) if outs else None
    if isinstance(node, dict):
        if node.get("type") == "video" and (node.get("data") or node.get("uri")):
            return node
        for v in node.values():
            got = _find_video(v, only_output=False)
            if got:
                return got
    elif isinstance(node, list):
        for v in node:
            got = _find_video(v, only_output=False)
            if got:
                return got
    return None


def _download_uri(uri: str, check_cancel=None) -> bytes:
    """Giao bằng file (video lớn hơn 4 MB): chờ file sẵn sàng rồi tải."""
    base = os.environ.get("ICONTENT_GEMINI_BASE") or API
    fid = uri.rstrip("/").split("/files/")[-1].split(":")[0].split("?")[0]
    for _ in range(120):
        if check_cancel:
            check_cancel()
        try:
            meta = _req("GET", f"{base}/files/{fid}", timeout=30)
            if str(meta.get("state") or "ACTIVE").upper() in ("ACTIVE", "STATE_UNSPECIFIED"):
                break
            if str(meta.get("state")).upper() == "FAILED":
                raise VideoGenError("Google tạo xong nhưng file video bị lỗi. Tạo lại.")
        except _Http as e:
            if e.code != 404:
                raise
        time.sleep(2)
    return _req("GET", f"{base}/files/{fid}:download?alt=media", timeout=300, raw=True)


def generate(prompt: str, image: Path | None = None, refs: list[Path] | None = None, aspect: str = "9:16", seconds: int = 8,
             resolution: str = DEFAULT_RES, provider: str = "omni", report=None, check_cancel=None) -> bytes:
    """-> bytes mp4. image: ảnh cảnh làm khung đầu (biến ảnh thành clip). refs: ảnh mẫu nhân vật khi tạo từ chữ.
    report(msg): báo tiến độ. check_cancel(): ném lỗi khi người dùng dừng (Google vẫn có thể tính tiền clip đang làm dở)."""
    from .imagegen import _jpeg
    if provider not in PROVIDERS:
        raise VideoGenError("Không có nhà cung cấp video này")
    if not ready(provider):
        raise VideoGenError("Chưa có key Gemini. Vào Cài đặt, mục Kết nối AI hoặc Tạo ảnh AI, dán key Gemini (đã bật thanh toán) rồi thử lại.")
    from .paid import allowed, block
    if not allowed():
        raise VideoGenError(block("AI làm clip (Gemini Omni, tính tiền theo giây)", "Video nền miễn phí, hoặc ảnh có máy quay chuyển động"))
    p = PROVIDERS[provider]
    seconds = int(min(p["max"], max(p["min"], seconds)))
    parts: list[dict] = []
    task = None
    if image and Path(image).is_file():
        parts.append({"type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(_jpeg(Path(image), 1280)).decode("ascii")})
        task = "image_to_video"
    else:
        for r in [Path(x) for x in refs or [] if Path(x).is_file()][: p["refs"]]:
            parts.append({"type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(_jpeg(r)).decode("ascii")})
    parts.append({"type": "text", "text": prompt})
    body = {"model": p["model"], "background": True, "store": True, "input": parts,
            "response_format": {"type": "video", "aspect_ratio": "9:16" if aspect == "9:16" else "16:9",
                                "resolution": resolution if resolution in RESOLUTIONS else DEFAULT_RES, "duration": f"{seconds}s"}}
    if task:
        body["generation_config"] = {"video_config": {"task": task}}
    base = os.environ.get("ICONTENT_GEMINI_BASE") or API      # máy chủ giả trong test
    try:
        try:
            first = _req("POST", f"{base}/interactions", body, timeout=120)
        except _Http as e:
            raise VideoGenError(friendly(e.code, e.body)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise VideoGenError(f"Không gửi được yêu cầu tới Google ({str(getattr(e, 'reason', e))[:100]}). Kiểm tra mạng. "
                                "Nếu Google đã nhận thì có thể vẫn bị tính tiền lần này.") from None
        final, iid, t0, misses = first, first.get("id"), time.time(), 0
        while str(final.get("status") or "") not in ("completed", "failed", "cancelled", "incomplete"):
            if not iid:
                break
            if time.time() - t0 > MAX_WAIT:
                raise VideoGenError("Google làm clip quá 20 phút chưa xong. Thử lại sau (clip đang làm có thể vẫn bị tính tiền).")
            for _ in range(int(POLL * 2)):
                if check_cancel:
                    check_cancel()
                time.sleep(0.5)
            if report:
                report(f"Google đang làm clip {seconds} giây ({int(time.time() - t0)} giây)")
            try:
                final = _req("GET", f"{base}/interactions/{iid}", timeout=120)
                misses = 0
            except (_Http, urllib.error.URLError, TimeoutError, OSError):
                misses += 1      # hỏi lại không tốn tiền: mạng chập chờn thì cứ hỏi tiếp
                if misses > 12:
                    raise VideoGenError("Mất kết nối với Google khi đang chờ clip. Clip có thể vẫn được làm và tính tiền.") from None
        if str(final.get("status")) != "completed":
            raise VideoGenError(_failed_msg(final))
        v = _find_video(final)
        if not v:
            raise VideoGenError("Google trả lời nhưng không có video (có thể do bộ lọc an toàn). Sửa mô tả rồi thử lại.")
        data = base64.b64decode(v["data"]) if v.get("data") else _download_uri(v["uri"], check_cancel)
        if len(data) < 1000:
            raise VideoGenError("Video Google trả về bị hỏng. Tạo lại.")
    except VideoGenError as e:
        low = str(e).lower()
        if "thanh toán" in low or "miễn phí" in low:
            _remember(provider, "billing", str(e))
        raise
    _remember(provider, "ok")
    return data


def scene_prompt(story: dict, scene: dict, from_image: bool) -> str:
    """Lời nhắn cho một cảnh. Từ ảnh: tả chuyển động, giữ nguyên nhân vật, bối cảnh trong ảnh. Không lời thoại, không chữ: lời dẫn và phụ đề là của iContent."""
    what = scene.get("prompt") or scene.get("text") or ""
    shape = "vertical 9:16" if story.get("aspect") == "9:16" else "horizontal 16:9"
    if from_image:
        head = ("Animate this image into a short cinematic shot. Keep the characters, faces, clothes, art style and setting exactly as in the image. "
                "Natural subtle motion of the characters and the environment with a slow smooth camera move.")
    else:
        head = f"A short cinematic {shape} shot for one scene of a story."
    return " ".join(x for x in (head, f"Scene: {what}" if what else "", "No dialogue, no speech, no narration, no music; only soft natural ambient sound.",
                                "No text, captions, subtitles, logos or watermarks on screen.") if x)
