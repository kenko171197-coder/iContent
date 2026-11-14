"""AI qua MCP: cổng MCP của Studio566 đặt trên Cloudflare Workers (tài khoản của người dùng, gói miễn phí).

Studio566 gửi việc chữ lên cổng rồi chờ kết quả; Claude, ChatGPT, Grok nối vào địa chỉ MCP để lấy việc và trả kết quả.
Máy người dùng chỉ gọi ra ngoài (HTTPS), không mở cổng nào. Mã cổng: cloudflare/studio566-mcp.js.

Cài đặt (một lần): người dùng tạo API token Cloudflare theo mẫu "Edit Cloudflare Workers", dán vào Studio566 →
deploy() tải Worker lên, bật địa chỉ <tên>.<tài khoản>.workers.dev, tạo hai mật khẩu (cho AI, cho app) và lưu lại.
"""
from __future__ import annotations

import json
import os
import secrets
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .util import ROOT, check_cancel, log

API = "https://api.cloudflare.com/client/v4"
SCRIPT = "studio566-mcp"
WORKER_FILE = ROOT / "cloudflare" / "studio566-mcp.js"
COMPAT_DATE = "2025-09-01"
UA = "Studio566-mcp"


class McpError(RuntimeError):
    pass


# ------------------------------------------------------------------ cấu hình lưu trên máy

def _conf_file() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(ROOT)
    d = Path(base) / "Studio566"
    d.mkdir(parents=True, exist_ok=True)
    return d / "mcp-cloud.json"


def load_conf() -> dict:
    try:
        return json.loads(_conf_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_conf(c: dict) -> None:
    _conf_file().write_text(json.dumps(c, indent=1), encoding="utf-8")


def configured() -> bool:
    c = load_conf()
    return bool(c.get("url") and c.get("app_secret") and c.get("mcp_secret"))


def ai_url(c: dict | None = None) -> str:
    c = c or load_conf()
    return f"{c['url'].rstrip('/')}/mcp/{c['mcp_secret']}" if c.get("url") else ""


# ------------------------------------------------------------------ gọi HTTP

def _http(method: str, url: str, body=None, headers: dict | None = None, timeout: float = 30.0):
    h = {"User-Agent": UA, **(headers or {})}
    data = None
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
        else:
            data = json.dumps(body).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw.decode("utf-8")) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode("utf-8"))
        except ValueError:
            return e.code, {"error": raw.decode("utf-8", "replace")[:300]}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise McpError(f"Không kết nối được: {getattr(e, 'reason', e)}") from e


def _cf(method: str, path: str, token: str, body=None, headers: dict | None = None) -> dict:
    code, data = _http(method, API + path, body, {"Authorization": f"Bearer {token}", **(headers or {})}, timeout=60)
    if not isinstance(data, dict) or not data.get("success", code < 300):
        errs = data.get("errors") if isinstance(data, dict) else None
        msg = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in (errs or []) if isinstance(e, dict)) or f"HTTP {code}"
        raise McpError(msg)
    return data


def _multipart(fields: list[tuple[str, str, str, bytes]]) -> tuple[bytes, str]:
    """[(tên, tên file, content-type, dữ liệu)] -> (body, content-type)."""
    b = "----studio566" + uuid.uuid4().hex
    out = bytearray()
    for name, filename, ctype, data in fields:
        out += f"--{b}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n".encode()
        out += data + b"\r\n"
    out += f"--{b}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={b}"


# ------------------------------------------------------------------ cài cổng lên Cloudflare

def _upload(token: str, account: str, c: dict, migrate: bool) -> None:
    meta = {
        "main_module": "worker.js",
        "compatibility_date": COMPAT_DATE,
        "bindings": [
            {"type": "durable_object_namespace", "name": "QUEUE", "class_name": "Queue"},
            {"type": "secret_text", "name": "MCP_SECRET", "text": c["mcp_secret"]},
            {"type": "secret_text", "name": "APP_SECRET", "text": c["app_secret"]},
        ],
    }
    if migrate:
        meta["migrations"] = {"new_tag": "v1", "new_sqlite_classes": ["Queue"]}
    body, ctype = _multipart([
        ("metadata", "blob", "application/json", json.dumps(meta).encode()),
        ("worker.js", "worker.js", "application/javascript+module", WORKER_FILE.read_bytes()),
    ])
    _cf("PUT", f"/accounts/{account}/workers/scripts/{SCRIPT}", token, body, {"Content-Type": ctype})


def deploy(token: str, rotate_mcp: bool = False) -> dict:
    """Tải cổng lên Cloudflare (cài mới hoặc cập nhật). Trả về cấu hình đã lưu."""
    token = (token or "").strip()
    c = load_conf()
    if not token:
        token = c.get("cf_token", "")
    if not token:
        raise McpError("Chưa có API token Cloudflare")
    log("mcp", "Kiểm tra tài khoản Cloudflare ...")
    accounts = _cf("GET", "/accounts?per_page=5", token).get("result") or []
    if not accounts:
        raise McpError("Token không thấy tài khoản Cloudflare nào: tạo token theo mẫu \"Edit Cloudflare Workers\"")
    account = accounts[0]["id"]
    c.setdefault("app_secret", secrets.token_urlsafe(24))
    if rotate_mcp or not c.get("mcp_secret"):
        c["mcp_secret"] = secrets.token_urlsafe(24)
    log("mcp", "Tải cổng MCP lên Cloudflare ...")
    try:
        _upload(token, account, c, migrate=not c.get("migrated"))
    except McpError as e:
        if "migration" not in str(e).lower():
            raise
        _upload(token, account, c, migrate=False)      # đã tạo hàng chờ ở lần cài trước
    c["migrated"] = True
    # tên miền mặc định <tài khoản>.workers.dev: tài khoản mới chưa có thì tạo
    try:
        sub = (_cf("GET", f"/accounts/{account}/workers/subdomain", token).get("result") or {}).get("subdomain")
    except McpError:
        sub = None
    if not sub:
        want = "s566-" + secrets.token_hex(3)
        sub = (_cf("PUT", f"/accounts/{account}/workers/subdomain", token, {"subdomain": want}).get("result") or {}).get("subdomain") or want
    _cf("POST", f"/accounts/{account}/workers/scripts/{SCRIPT}/subdomain", token, {"enabled": True, "previews_enabled": False})
    c.update({"url": f"https://{SCRIPT}.{sub}.workers.dev", "account": account, "cf_token": token, "deployed_at": int(time.time())})
    save_conf(c)
    log("mcp", f"Đã cài cổng MCP: {c['url']}")
    return c


def forget() -> None:
    try:
        _conf_file().unlink()
    except OSError:
        pass


# ------------------------------------------------------------------ dùng cổng

def _app(method: str, path: str, body=None, timeout: float = 20.0) -> dict:
    c = load_conf()
    if not c.get("url"):
        raise McpError("Chưa cài cổng MCP: vào Cài đặt > Kết nối AI dịch > AI qua MCP")
    code, data = _http(method, f"{c['url'].rstrip('/')}/api/{c['app_secret']}/{path}", body, timeout=timeout)
    if code >= 300:
        raise McpError(f"Cổng MCP trả lỗi HTTP {code}: {str(data)[:200]}")
    return data


def status(wait_ready: float = 0.0) -> dict:
    """{pending, taken, ai_seen, ai_name}. wait_ready: vừa cài xong thì địa chỉ workers.dev có thể chưa chạy ngay, chờ tối đa chừng này giây."""
    end = time.time() + wait_ready
    while True:
        try:
            return _app("GET", "status")
        except McpError:
            if time.time() >= end:
                raise
            time.sleep(3)


def run_job(system: str, user: str, schema: dict | None, title: str, wait: float = 300.0,
            work_limit: float = 900.0, poll: float = 2.0) -> dict:
    """Gửi một việc lên cổng, chờ AI làm. Chưa AI nào nhận sau `wait` giây -> hủy việc và báo lỗi để app dùng cách dự phòng.
    AI đã nhận thì cho thêm tới `work_limit` giây."""
    job = _app("POST", "jobs", {"title": title, "system": system, "user": user, "schema": schema})
    jid = job["id"]
    start = time.time()
    taken_once = False
    last_note = 0.0
    try:
        while True:
            check_cancel()
            time.sleep(poll)
            try:
                st = _app("GET", f"jobs/{jid}")
            except McpError as e:      # mạng chập chờn: thử lại tới khi hết giờ
                st = {"status": "error", "error": str(e)}
            s = st.get("status")
            now = time.time()
            if s == "done":
                log("mcp", f"AI{(' ' + st['by']) if st.get('by') else ''} đã làm xong: {title}")
                return st.get("result") or {}
            if s == "missing":
                raise McpError("Việc trên cổng MCP bị mất (có thể đã hết hạn)")
            if s == "taken":
                if not taken_once:
                    log("mcp", f"AI{(' ' + st['by']) if st.get('by') else ''} đang làm: {title}")
                taken_once = True
                if now - start > work_limit:
                    raise TimeoutError(f"AI nhận việc nhưng quá {int(work_limit / 60)} phút chưa trả kết quả")
                continue
            # đang chờ AI nhận
            limit = work_limit if taken_once else wait
            if now - start > limit:
                raise TimeoutError(f"Chưa có AI nào vào làm qua MCP sau {wait / 60:g} phút")
            if now - last_note >= 30:
                last_note = now
                left = int(limit - (now - start))
                log("mcp", f"Đang chờ AI qua MCP ({title}): mở Claude, ChatGPT hoặc Grok và nhắn \"làm việc đang chờ\". "
                           f"Còn {left} giây trước khi tự chuyển sang cách dự phòng")
    except BaseException:
        try:
            _app("DELETE", f"jobs/{jid}", timeout=8)
        except Exception:      # noqa: BLE001 — dọn việc là phụ
            pass
        raise
