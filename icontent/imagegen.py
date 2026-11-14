"""Tạo ảnh bằng AI qua API chính thức của từng nhà cung cấp, giữ nhân vật nhất quán bằng ảnh mẫu.

  gemini      Google Gemini (Nano Banana 2.1): giữ nhân vật tốt nhất, tối đa 4 ảnh mẫu nhân vật. Không có gói miễn phí, ~0,034 USD/ảnh.
  openai      OpenAI (ảnh của ChatGPT qua API): trả phí theo bảng giá OpenAI, nhận nhiều ảnh mẫu (endpoint edits).
  meta        Meta Muse Image: 0,01 USD/ảnh, kiểu API giống OpenAI.
  cloudflare  Cloudflare Workers AI, FLUX.1 schnell: có hạn mức miễn phí mỗi ngày, KHÔNG nhận ảnh mẫu (chỉ giữ nhân vật bằng mô tả).
  local       Vẽ ngay trên máy bằng FLUX.2 klein 4B (gói "image" của localai.py): miễn phí, không giới hạn, không cần mạng, nhận 2 ảnh mẫu.

Bản miễn phí trên web của ChatGPT, Copilot không có API: dùng nút Chép lời nhắn rồi Dán ảnh ở từng cảnh (story.js), không tự động hóa
trang web của họ (trái điều khoản, và hỏng mỗi khi họ đổi giao diện).

Gọi REST bằng thư viện chuẩn, không thêm gói. Key nằm trong Cài đặt (keys.json), mỗi key chỉ gửi tới đúng nhà cung cấp của nó.
Không thử lại khi yêu cầu có thể đã tới nơi (hết thời gian chờ, mất kết nối giữa chừng): nhà cung cấp có thể đã tính tiền lần đầu.
"""
from __future__ import annotations

import base64
import io
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/interactions"
API_REVISION = "2026-05-20"
MODEL = "gemini-nano-banana-2.1"
MAX_CHARACTER_REFS = 4
ASPECTS = ("9:16", "16:9", "1:1", "4:5", "3:4", "4:3", "3:2", "2:3")
NO_TEXT = "No text, no letters, no captions, no speech bubbles, no watermark, no logo in the image."
MAX_SIDE = 3840          # ảnh lưu lại không cần lớn hơn: video cao nhất 1920, Ken Burns phóng 2 lần

PROVIDERS = {
    "gemini": {"name": "Google Gemini", "model": MODEL, "keys": ["GEMINI_API_KEY"], "refs": 4, "price": "khoảng 0,034 USD/ảnh, không có gói miễn phí",
               "get": "aistudio.google.com/apikey"},
    "openai": {"name": "OpenAI (ChatGPT)", "model": "gpt-image-2.5-flare", "keys": ["OPENAI_API_KEY"], "refs": 4, "base": "https://api.openai.com/v1",
               "price": "trả phí theo bảng giá OpenAI (API khác gói ChatGPT miễn phí)", "get": "platform.openai.com/api-keys", "field": "image[]"},
    "meta": {"name": "Meta Muse Image", "model": "muse-image-1.0", "keys": ["META_MODEL_API_KEY"], "refs": 4, "base": "https://api.meta.ai/v1",
             "price": "0,01 USD/ảnh", "get": "dev.meta.ai", "field": "image[{i}]"},
    "cloudflare": {"name": "Cloudflare FLUX (miễn phí có hạn mức)", "model": "@cf/black-forest-labs/flux-1-schnell",
                   "keys": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"], "refs": 0,
                   "price": "miễn phí trong hạn mức hằng ngày của Cloudflare", "get": "dash.cloudflare.com"},
    "local": {"name": "Vẽ trên máy (miễn phí)", "model": "flux-2-klein-4b", "keys": [], "refs": 2, "local": True,
              "price": "miễn phí, không giới hạn số ảnh, chạy ngay trên máy", "get": ""},
}
ORDER = ("gemini", "openai", "meta", "cloudflare", "local")
# kích thước gửi đi theo khung: OpenAI chỉ nhận vài cỡ cố định; Meta dùng cỡ để định tỉ lệ khung
SIZES = {"openai": {"9:16": "1024x1536", "16:9": "1536x1024", "1:1": "1024x1024"},
         "meta": {"9:16": "1080x1920", "16:9": "1920x1080", "1:1": "1024x1024"}}


class ImageGenError(RuntimeError):
    pass


def _key(name: str) -> str:
    return os.environ.get(name, "").strip()


def ready(provider: str) -> bool:
    p = PROVIDERS.get(provider)
    if p and p.get("local"):
        from .localai import image_ready
        return image_ready()
    return bool(p) and all(_key(k) for k in p["keys"])


def is_paid(provider: str) -> bool:
    from .paid import PAID_IMAGE
    return provider in PAID_IMAGE


def usable(provider: str) -> bool:
    """Đủ key (hoặc đã tải) và không bị công tắc trả phí chặn."""
    from .paid import allowed
    return ready(provider) and (not is_paid(provider) or allowed())


def available() -> bool:
    return any(usable(p) for p in ORDER)


AUTO_ORDER = ("local", "cloudflare", "gemini", "openai", "meta")      # Tự chọn: miễn phí trước (tiêu chí của Studio566), trả phí sau


def pick(provider: str = "") -> str:
    """Nhà cung cấp sẽ dùng: cái được chọn nếu đã đủ key, không thì cái miễn phí đã sẵn sàng, rồi mới tới cái trả phí (nếu cho phép)."""
    from .paid import allowed, block
    if provider in PROVIDERS:
        if not ready(provider):
            if PROVIDERS[provider].get("local"):
                raise ImageGenError("Chưa tải Vẽ ảnh offline. Vào Cài đặt, mục Mô-đun AI miễn phí, bấm Tải (khoảng 5,3 GB) rồi vẽ lại.")
            raise ImageGenError(f"Chưa có key {PROVIDERS[provider]['name']}. Vào Cài đặt, mục Tạo ảnh AI, dán key rồi thử lại.")
        if is_paid(provider) and not allowed():
            raise ImageGenError(block(f"{PROVIDERS[provider]['name']} (vẽ ảnh tính tiền)", "Vẽ trên máy hoặc Cloudflare, chọn ở Nguồn ảnh"))
        return provider
    have = [p for p in AUTO_ORDER if usable(p)]
    good = [p for p in have if status(p).get("state") != "billing"]      # key đã biết là không vẽ được thì để sau cùng
    if have:
        return (good or have)[0]
    if any(ready(p) for p in ORDER):
        raise ImageGenError(block("nguồn vẽ ảnh tính tiền", "tải Vẽ ảnh offline ở Cài đặt, mục Mô-đun AI miễn phí, hoặc dán key Cloudflare"))
    raise ImageGenError("Chưa có cách vẽ ảnh nào (chưa tải Vẽ ảnh offline, chưa có key tạo ảnh). Tải Vẽ ảnh offline miễn phí (Cài đặt, mục Mô-đun AI miễn phí) để vẽ ngay trên máy, "
                        "hoặc dán key Cloudflare (có hạn mức miễn phí) ở mục Tạo ảnh AI.")


STATUS_FILE = Path(__file__).resolve().parent.parent / "assets" / ".imagegen_status.json"
_status_lock = __import__("threading").Lock()


def _fingerprint(prov: str) -> str:
    """Đổi key thì trạng thái cũ không còn đúng."""
    import hashlib
    raw = "|".join(os.environ.get(k, "") for k in PROVIDERS[prov]["keys"])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _remember(prov: str, state: str, msg: str = "") -> None:
    """ok: vẽ được. billing: key chưa bật thanh toán hay hết hạn mức (vẽ lại cũng không được cho tới khi người dùng sửa)."""
    with _status_lock:
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


def public() -> list[dict]:
    out = []
    for k, v in PROVIDERS.items():
        st = status(k) if ready(k) else {}
        out.append({"id": k, "name": v["name"], "refs": v["refs"], "price": v["price"], "keys": v["keys"], "get": v["get"], "ready": ready(k),
                    "local": bool(v.get("local")), "paid": is_paid(k), "usable": usable(k),
                    "status": st.get("state") or "", "status_msg": st.get("msg") or "", "status_at": st.get("at") or 0})
    return out


# ------------------------------------------------------------------ ảnh vào, ảnh ra
def normalize(data: bytes):
    """Mở ảnh bất kỳ thành RGB đúng chiều: ảnh điện thoại xoay theo EXIF, nền trong suốt thành trắng, ảnh 16-bit thu về 8-bit, ảnh động lấy
    khung đầu, ảnh quá lớn thu nhỏ. Ảnh hỏng thì ValueError."""
    from PIL import Image, ImageOps

    try:
        im = Image.open(io.BytesIO(data))
        im.seek(0)
        im.load()
    except Exception as e:
        raise ValueError("Không đọc được ảnh này (chỉ nhận PNG, JPG, WEBP còn nguyên vẹn)") from e
    im = ImageOps.exif_transpose(im)
    if im.mode in ("I;16", "I;16B", "I;16L", "I"):
        im = im.point(lambda v: v / 256).convert("L")
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        im = bg
    im = im.convert("RGB")
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    return im


def save(img: bytes, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    im = normalize(img)
    tmp = out.with_name(f"{out.stem}.{uuid.uuid4().hex[:6]}.part.png")
    try:
        im.save(tmp, "PNG", compress_level=4)
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    return out


def _jpeg(path: Path, max_side: int = 1024) -> bytes:
    """Ảnh mẫu thu nhỏ còn cạnh dài 1024: đủ để giữ nhân vật, gửi nhanh hơn nhiều so với ảnh gốc vài MB."""
    from PIL import Image
    im = normalize(Path(path).read_bytes())
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


# ------------------------------------------------------------------ gọi mạng
class _Http(Exception):
    def __init__(self, code: int, body: str):
        super().__init__(f"HTTP {code}")
        self.code, self.body = code, body


def _post(url: str, data: bytes, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise _Http(e.code, e.read().decode("utf-8", "replace")) from None


def _call(send, friendly, retries: int = 3):
    """Thử lại chỉ khi chắc chắn chưa được tính tiền: quá tải (429) và lỗi máy chủ (5xx) thì không có ảnh nào được tạo.
    Hết thời gian chờ hay mất kết nối giữa chừng thì không thử lại: yêu cầu có thể đã tới nơi và đã bị tính tiền."""
    for attempt in range(retries):
        try:
            return send()
        except _Http as e:
            msg, wait = friendly(e.code, e.body)
            if wait is not None and attempt < retries - 1:
                time.sleep(wait)
                continue
            raise ImageGenError(msg) from None
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, ConnectionRefusedError) and attempt < retries - 1:      # chưa kết nối được: chắc chắn chưa gửi gì
                time.sleep(3 * (attempt + 1))
                continue
            raise ImageGenError(f"Không kết nối được máy chủ tạo ảnh ({str(reason)[:120]}). Kiểm tra mạng hoặc VPN. "
                                "Nếu ảnh đã vẽ xong bên đó thì có thể vẫn bị tính phí lần này.") from None
        except (TimeoutError, OSError) as e:
            raise ImageGenError(f"Máy chủ tạo ảnh không trả lời kịp ({str(e)[:80]}). Không tự thử lại để tránh bị tính tiền hai lần, "
                                "hãy bấm vẽ lại.") from None
        except ValueError:
            raise ImageGenError("Máy chủ tạo ảnh trả về dữ liệu không đọc được") from None
    raise ImageGenError("Không tạo được ảnh")


def _err_json(body: str) -> dict:
    try:
        e = json.loads(body).get("error") or {}
        return e if isinstance(e, dict) else {"message": str(e)}
    except (ValueError, AttributeError):
        return {"message": body[:300]}


def _retry_delay(err: dict, default: float) -> float:
    for d in err.get("details") or []:
        v = str(d.get("retryDelay") or "") if isinstance(d, dict) else ""
        if v.endswith("s"):
            try:
                return min(30.0, float(v[:-1]) + 0.5)
            except ValueError:
                pass
    return default


# ------------------------------------------------------------------ Gemini
def _gemini_friendly(code: int, body: str):
    err = _err_json(body)
    status, msg = str(err.get("status") or ""), str(err.get("message") or body)
    low = msg.lower()
    free_tier_zero = code == 429 and ("limit: 0" in low or "free_tier" in low or "free tier" in low)
    if status == "FAILED_PRECONDITION" or "billing to be enabled" in low or free_tier_zero:
        return ("Key Gemini chưa bật thanh toán. Tạo ảnh của Google không có gói miễn phí: vào aistudio.google.com, mục Billing, "
                "bật thanh toán cho project của key rồi thử lại."), None
    if code in (401, 403) or "api key not valid" in low or status in ("PERMISSION_DENIED", "UNAUTHENTICATED"):
        return "Key Gemini không hợp lệ hoặc không có quyền tạo ảnh. Kiểm tra lại key trong Cài đặt.", None
    if code == 429:
        return "Google đang giới hạn số ảnh mỗi phút. Đợi một lát rồi vẽ tiếp.", _retry_delay(err, 8.0)
    if code == 404:
        return "Google không còn model tạo ảnh này. Cập nhật Studio566 hoặc đổi model trong config (story.image_model).", None
    if code >= 500:
        return "Máy chủ Google đang lỗi tạm thời. Thử lại sau ít phút.", 6.0
    return f"Google từ chối yêu cầu tạo ảnh: {msg[:200]}", None


def _find_image(node, only_output: bool = True) -> tuple[str, str] | None:
    """Ảnh trong phần trả lời của model. Có danh sách steps thì chỉ tìm trong bước model_output: nếu máy chủ gửi kèm lại ảnh mẫu đã gửi đi
    thì không nhặt nhầm ảnh mẫu làm ảnh vẽ ra."""
    if only_output and isinstance(node, dict) and isinstance(node.get("steps"), list):
        outs = [s for s in node["steps"] if isinstance(s, dict) and s.get("type") == "model_output"]
        if outs:
            return _find_image(outs, only_output=False)
    found = None
    if isinstance(node, dict):
        if node.get("type") == "image" and isinstance(node.get("data"), str) and len(node["data"]) > 100:
            found = (node["data"], node.get("mime_type") or "image/png")
        inline = node.get("inlineData") or node.get("inline_data")
        if isinstance(inline, dict) and isinstance(inline.get("data"), str):
            found = (inline["data"], inline.get("mimeType") or inline.get("mime_type") or "image/png")
        for v in node.values():
            got = _find_image(v, only_output=False)
            if got:
                found = got
    elif isinstance(node, list):
        for v in node:
            got = _find_image(v, only_output=False)
            if got:
                found = got
    return found


def _text_of(node, out: list[str]) -> list[str]:
    if isinstance(node, dict):
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            out.append(node["text"])
        for v in node.values():
            _text_of(v, out)
    elif isinstance(node, list):
        for v in node:
            _text_of(v, out)
    return out


def _gemini(prompt: str, refs: list[Path], aspect: str, size: str, model: str, timeout: float) -> bytes:
    body = {"model": model or MODEL,
            "input": [{"type": "text", "text": prompt}] + [{"type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(_jpeg(r)).decode("ascii")} for r in refs],
            "response_format": {"type": "image", "aspect_ratio": aspect if aspect in ASPECTS else "1:1", "image_size": size}}
    url = os.environ.get("ICONTENT_GEMINI_API") or GEMINI_API      # máy chủ giả trong test
    headers = {"x-goog-api-key": _key("GEMINI_API_KEY"), "Content-Type": "application/json", "Api-Revision": API_REVISION}
    payload = _call(lambda: _post(url, json.dumps(body).encode("utf-8"), headers, timeout), _gemini_friendly)
    got = _find_image(payload)
    if got:
        return base64.b64decode(got[0])
    said = " ".join(_text_of(payload, [])).strip()
    raise ImageGenError("Google không vẽ cảnh này" + (f": {said[:200]}" if said else " (có thể do nội dung nhạy cảm). Sửa mô tả rồi thử lại."))


# ------------------------------------------------------------------ OpenAI và Meta (cùng kiểu API images)
def _openai_like_friendly(name: str):
    def fn(code: int, body: str):
        err = _err_json(body)
        msg, kind = str(err.get("message") or body), str(err.get("code") or err.get("type") or "")
        low = (msg + " " + kind).lower()
        if "insufficient_quota" in low or "billing" in low:
            return f"Tài khoản {name} hết tiền hoặc chưa nạp tiền cho API (API tính phí riêng, khác gói miễn phí trên web).", None
        if code in (401, 403):
            return f"Key {name} không hợp lệ hoặc không có quyền tạo ảnh. Kiểm tra lại key trong Cài đặt.", None
        if "safety" in low or "moderation" in low or "content_policy" in low:
            return f"{name} từ chối vẽ cảnh này vì chính sách nội dung. Sửa mô tả rồi thử lại.", None
        if code == 429:
            return f"{name} đang giới hạn số ảnh mỗi phút. Đợi một lát rồi vẽ tiếp.", 10.0
        if code >= 500:
            return f"Máy chủ {name} đang lỗi tạm thời. Thử lại sau ít phút.", 6.0
        return f"{name} từ chối yêu cầu: {msg[:200]}", None
    return fn


def _multipart(fields: dict, files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "iContent" + uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
    for field, filename, data, mime in files:
        out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n".encode("utf-8"))
        out.write(data)
        out.write(b"\r\n")
    out.write(f"--{boundary}--\r\n".encode("utf-8"))
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def _openai_like(provider: str, prompt: str, refs: list[Path], aspect: str, model: str, timeout: float) -> bytes:
    p = PROVIDERS[provider]
    base = os.environ.get(f"ICONTENT_{provider.upper()}_API") or p["base"]      # máy chủ giả trong test
    key = _key(p["keys"][0])
    size = SIZES[provider].get(aspect, "1024x1024")
    fields = {"model": model or p["model"], "prompt": prompt, "size": size, "n": "1"}
    if provider == "meta":
        fields["response_format"] = "b64_json"
        fields["output_format"] = "png"
    if refs:
        files = [(p["field"].format(i=i), f"ref{i}.jpg", _jpeg(r), "image/jpeg") for i, r in enumerate(refs)]
        data, ctype = _multipart(fields, files)
        url = base.rstrip("/") + "/images/edits"
    else:
        body = dict(fields, n=1)
        data, ctype, url = json.dumps(body).encode("utf-8"), "application/json", base.rstrip("/") + "/images/generations"
    payload = _call(lambda: _post(url, data, {"Authorization": f"Bearer {key}", "Content-Type": ctype}, timeout), _openai_like_friendly(p["name"]))
    items = payload.get("data") or []
    b64 = items[0].get("b64_json") if items and isinstance(items[0], dict) else None
    if not b64:
        raise ImageGenError(f"{p['name']} không trả về ảnh nào. Sửa mô tả rồi thử lại.")
    return base64.b64decode(b64)


# ------------------------------------------------------------------ Cloudflare
def _cloudflare(prompt: str, timeout: float) -> bytes:
    p = PROVIDERS["cloudflare"]
    acc = _key("CLOUDFLARE_ACCOUNT_ID")
    base = os.environ.get("ICONTENT_CLOUDFLARE_API") or f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/"
    url = base + p["model"]

    def friendly(code: int, body: str):
        low = body.lower()
        if code in (401, 403):
            return "Token Cloudflare không hợp lệ hoặc thiếu quyền Workers AI, hoặc sai Account ID. Kiểm tra lại trong Cài đặt.", None
        if code == 429 or "neurons" in low or "daily" in low:
            return "Đã dùng hết hạn mức miễn phí hôm nay của Cloudflare (hoặc đang quá tải). Thử lại ngày mai hoặc dùng nguồn khác.", None
        if code >= 500:
            return "Máy chủ Cloudflare đang lỗi tạm thời. Thử lại sau ít phút.", 6.0
        return f"Cloudflare từ chối yêu cầu: {body[:200]}", None
    payload = _call(lambda: _post(url, json.dumps({"prompt": prompt[:2048], "steps": 8}).encode("utf-8"),
                                  {"Authorization": f"Bearer {_key('CLOUDFLARE_API_TOKEN')}", "Content-Type": "application/json"}, timeout), friendly)
    img = (payload.get("result") or {}).get("image") if isinstance(payload.get("result"), dict) else payload.get("image")
    if not img:
        raise ImageGenError("Cloudflare không trả về ảnh nào. Sửa mô tả rồi thử lại.")
    return base64.b64decode(img)


# ------------------------------------------------------------------ vẽ trên máy
def _local(prompt: str, refs: list[Path], aspect: str) -> bytes:
    from . import localai
    # FLUX hiểu câu khẳng định: dòng "No text, no letters..." lại làm hiện chữ trên ảnh, nên bỏ. Lời tiếng Việt dịch sang tiếng Anh nếu có Dịch offline
    text = localai.to_english(prompt.replace(NO_TEXT, "").strip())
    try:
        return localai.draw(text, refs, aspect)
    except InterruptedError:
        raise ImageGenError("Đã dừng vẽ") from None
    except RuntimeError as e:
        raise ImageGenError(str(e)) from e


# ------------------------------------------------------------------ chung
def generate(prompt: str, refs: list[Path] | None = None, aspect: str = "9:16", size: str = "1K", model: str = "",
             provider: str = "", timeout: float = 240) -> tuple[bytes, str]:
    """-> (bytes ảnh, tên nhà cung cấp đã dùng). Lỗi thì ImageGenError với lời giải thích tiếng Việt."""
    prov = pick(provider)
    cap = PROVIDERS[prov]["refs"]
    refs = [Path(r) for r in (refs or []) if Path(r).is_file()][:cap]
    try:
        if prov == "gemini":
            data = _gemini(prompt, refs, aspect, size, model if model.startswith("gemini") else "", timeout)
        elif prov == "cloudflare":
            data = _cloudflare(prompt, timeout)
        elif prov == "local":
            data = _local(prompt, refs, aspect)
        else:
            data = _openai_like(prov, prompt, refs, aspect, "", timeout)
    except ImageGenError as e:
        low = str(e).lower()
        if any(w in low for w in ("thanh toán", "hạn mức", "billing", "quota")):
            _remember(prov, "billing", str(e))      # để Cài đặt, Kể chuyện, Quy trình nói đúng: key này chưa vẽ được
        raise
    normalize(data)      # chắc chắn là ảnh thật trước khi lưu, ảnh hỏng thì báo ở đây
    _remember(prov, "ok")
    return data, prov
