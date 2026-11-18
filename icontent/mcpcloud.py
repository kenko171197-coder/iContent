"""AI qua MCP: kết nối tới cổng MCP trung tâm của Studio566 (Cloudflare Workers của chủ app, mã: cloudflare/studio566-mcp.js).

Mỗi máy tự đăng ký một KÊNH riêng (không cần tài khoản): nhận mã kênh, mật khẩu cho app và mật khẩu cho AI.
Studio566 gửi việc chữ vào kênh rồi chờ kết quả; Claude, ChatGPT, Grok của người dùng nối vào link MCP của kênh để
lấy việc và trả kết quả. Máy người dùng chỉ gọi ra ngoài (HTTPS), không mở cổng nào.

Địa chỉ cổng: biến môi trường STUDIO566_MCP_SERVER > translate.mcp_server trong cấu hình > icontent/_mcp_server.txt
(GitHub Actions ghi lúc đóng gói bản cài).
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .util import ROOT, check_cancel, log

UA = "Studio566-mcp"
POLL_WAIT = 20          # giây: mỗi lượt hỏi kết quả, cổng giữ kết nối chờ AI trả tới chừng này (ít lượt gọi)


class McpError(RuntimeError):
    pass


# ------------------------------------------------------------------ địa chỉ cổng, kênh lưu trên máy

def server_url(cfg_url: str = "") -> str:
    u = os.environ.get("STUDIO566_MCP_SERVER") or cfg_url
    if not u:
        try:
            u = Path(__file__).with_name("_mcp_server.txt").read_text(encoding="utf-8").strip()
        except OSError:
            u = ""
    return u.rstrip("/")


def _conf_file() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(ROOT)
    d = Path(base) / "Studio566"
    d.mkdir(parents=True, exist_ok=True)
    return d / "mcp-channel.json"


def load_conf() -> dict:
    try:
        return json.loads(_conf_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_conf(c: dict) -> None:
    _conf_file().write_text(json.dumps(c, indent=1), encoding="utf-8")


def configured() -> bool:
    c = load_conf()
    return bool(c.get("server") and c.get("id") and c.get("app_secret") and c.get("mcp_secret"))


def ai_url(c: dict | None = None) -> str:
    c = c or load_conf()
    return f"{c['server']}/mcp/{c['id']}/{c['mcp_secret']}" if c.get("id") else ""


# ------------------------------------------------------------------ gọi HTTP

def _http(method: str, url: str, body=None, timeout: float = 30.0):
    h = {"User-Agent": UA}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
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
        raise McpError(f"Không kết nối được cổng MCP: {getattr(e, 'reason', e)}") from e


def _err(code: int, data) -> str:
    return (data.get("error") if isinstance(data, dict) else "") or f"HTTP {code}"


# ------------------------------------------------------------------ kết nối / ngắt / đổi link

def connect(cfg_url: str = "") -> dict:
    """Đăng ký kênh mới trên cổng trung tâm (đã có kênh thì giữ nguyên)."""
    if configured():
        return load_conf()
    srv = server_url(cfg_url)
    if not srv:
        raise McpError("Bản Studio566 này chưa có địa chỉ cổng MCP")
    code, data = _http("POST", f"{srv}/api/register", {})
    if code != 200 or not data.get("id"):
        raise McpError(_err(code, data))
    c = {"server": srv, "id": data["id"], "app_secret": data["app_secret"], "mcp_secret": data["mcp_secret"],
         "connected_at": int(time.time())}
    save_conf(c)
    log("mcp", "Đã kết nối cổng AI qua MCP")
    return c


def _app(method: str, path: str, body=None, timeout: float = 20.0) -> dict:
    c = load_conf()
    if not c.get("id"):
        raise McpError("Chưa kết nối AI qua MCP: vào Cài đặt > Kết nối AI dịch > AI qua MCP")
    code, data = _http(method, f"{c['server']}/api/{c['id']}/{c['app_secret']}/{path}", body, timeout=timeout)
    if code == 404 and path in ("status", ""):
        raise McpError("Kênh không còn trên cổng MCP: bấm Ngắt kết nối rồi Kết nối lại")
    if code >= 300:
        raise McpError(f"Cổng MCP báo lỗi: {_err(code, data)}")
    return data


def rotate() -> dict:
    c = load_conf()
    c["mcp_secret"] = _app("POST", "rotate")["mcp_secret"]
    save_conf(c)
    return c


def disconnect() -> None:
    try:
        _app("DELETE", "", timeout=10)
    except McpError:
        pass
    try:
        _conf_file().unlink()
    except OSError:
        pass


def status() -> dict:
    """{pending, taken, ai_seen, ai_name}."""
    return _app("GET", "status")


# ------------------------------------------------------------------ chạy một việc

_gate = {"state": "idle", "video": "", "since": 0.0}
_gate_lock = threading.Lock()


def gate_reset(video: str = "") -> None:
    """Mỗi video bắt đầu chạy: chưa ai bấm gì. Hết video: về nghỉ (giao diện ẩn thông báo)."""
    with _gate_lock:
        _gate.update(state="idle", video=video, since=0.0)


def gate_state() -> dict:
    with _gate_lock:
        return dict(_gate)


def gate_answer(go: bool) -> bool:
    """Người dùng bấm Bắt đầu (go=True) hoặc Bỏ qua. Đúng một lần cho cả video: các việc MCP sau không hỏi lại."""
    with _gate_lock:
        if _gate["state"] not in ("waiting", "idle"):
            return False
        _gate["state"] = "go" if go else "skip"
        return True


def _await_go(title: str) -> None:
    """Chờ người dùng bấm Bắt đầu rồi mới gửi việc và tính giờ: không ai nhắn AI thì cũng không tự hết giờ."""
    with _gate_lock:
        st = _gate["state"]
        if st == "idle":
            _gate.update(state="waiting", since=time.time())
    if st == "go":
        return
    if st == "skip":
        raise McpError("Bạn đã chọn bỏ qua AI qua MCP cho video này")
    log("mcp", f"Cần AI qua MCP ({title}): bấm Bắt đầu trên thông báo của app, rồi mở Claude, ChatGPT hoặc Grok "
               "và nhắn \"làm việc đang chờ\". Bấm Bỏ qua để dùng cách dịch dự phòng")
    try:
        while True:
            check_cancel()
            with _gate_lock:
                st = _gate["state"]
            if st == "go":
                log("mcp", "Đã bấm Bắt đầu: gửi việc cho AI qua MCP")
                return
            if st == "skip":
                raise McpError("Bạn đã chọn bỏ qua AI qua MCP cho video này")
            time.sleep(0.4)
    except BaseException:
        with _gate_lock:
            if _gate["state"] == "waiting":
                _gate["state"] = "idle"
        raise


def run_job(system: str, user: str, schema: dict | None, title: str, wait: float = 300.0,
            work_limit: float = 900.0, poll: float = POLL_WAIT, confirm: bool = False) -> dict:
    """Gửi một việc vào kênh, chờ AI làm. Chưa AI nào nhận sau `wait` giây -> hủy việc và báo lỗi để app dùng cách dự phòng.
    AI đã nhận thì cho thêm tới `work_limit` giây. Mỗi lượt hỏi, cổng giữ kết nối tới `poll` giây chờ AI trả."""
    if confirm:
        _await_go(title)
    job = _app("POST", "jobs", {"title": title, "system": system, "user": user, "schema": schema})
    jid = job["id"]
    start = time.time()
    taken_once = False
    last_note = 0.0
    try:
        while True:
            check_cancel()
            now = time.time()
            limit = work_limit if taken_once else wait
            hold = max(0.0, min(poll, limit - (now - start)))
            try:
                st = _app("GET", f"jobs/{jid}?wait={int(hold)}", timeout=hold + 15)
            except McpError as e:      # mạng chập chờn: thử lại tới khi hết giờ
                st = {"status": "error", "error": str(e)}
                time.sleep(2)
            s = st.get("status")
            now = time.time()
            if s == "done":
                log("mcp", f"AI{(' ' + st['by']) if st.get('by') else ''} đã làm xong: {title}")
                return st.get("result") or {}
            if s == "missing":
                raise McpError("Việc trên cổng MCP bị mất (có thể đã hết hạn)")
            if s == "taken" and not taken_once:
                taken_once = True
                log("mcp", f"AI{(' ' + st['by']) if st.get('by') else ''} đang làm: {title}")
            limit = work_limit if taken_once else wait
            if now - start >= limit:
                if taken_once:
                    raise TimeoutError(f"AI nhận việc nhưng quá {int(work_limit / 60)} phút chưa trả kết quả")
                raise TimeoutError(f"Chưa có AI nào vào làm qua MCP sau {wait / 60:g} phút")
            if not taken_once and now - last_note >= 30:
                last_note = now
                log("mcp", f"Đang chờ AI qua MCP ({title}): mở Claude, ChatGPT hoặc Grok và nhắn \"làm việc đang chờ\". "
                           f"Còn {int(limit - (now - start))} giây trước khi tự chuyển sang cách dự phòng")
    except BaseException:
        try:
            _app("DELETE", f"jobs/{jid}", timeout=8)
        except Exception:      # noqa: BLE001 — dọn việc là phụ
            pass
        raise
