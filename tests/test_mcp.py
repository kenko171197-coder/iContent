"""AI qua MCP, chạy trọn vòng trên máy: cổng MCP thật (cloudflare/studio566-mcp.js) chạy bằng Node thay cho Cloudflare,
Studio566 gửi việc dịch, một "AI" giả gọi lay_viec / tra_ket_qua qua MCP. Bỏ qua nếu máy không có Node."""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="cần Node để chạy cổng MCP thử")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture()
def gate(tmp_path, monkeypatch):
    port = _free_port()
    proc = subprocess.Popen(["node", str(ROOT / "cloudflare" / "dev-server.mjs"), str(port), "mcp-secret-x", "app-secret-x"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from icontent import mcpcloud
    mcpcloud.save_conf({"url": f"http://127.0.0.1:{port}", "app_secret": "app-secret-x", "mcp_secret": "mcp-secret-x"})
    yield f"http://127.0.0.1:{port}/mcp/mcp-secret-x"
    proc.terminate()


def _rpc(url: str, method: str, params: dict | None = None, rid: int = 1) -> dict:
    req = urllib.request.Request(url, data=json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read())


def _fake_ai(url: str, answer, stop: threading.Event):
    """AI giả: lấy việc, dịch "giả" mỗi câu thành 'VI:<id>', trả lại. Lần trả đầu cố tình sai khuôn để thử báo lỗi."""
    _rpc(url, "initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "AI thử"}})
    first = True
    while not stop.is_set():
        try:
            text = _rpc(url, "tools/call", {"name": "lay_viec", "arguments": {}})["result"]["content"][0]["text"]
        except OSError:      # cổng thử đã tắt khi kết thúc bài test
            return
        if not text.startswith("VIỆC "):
            continue
        jid = text.split()[1]
        data = text.split("=== DỮ LIỆU ===", 1)[1].split("=== KHUÔN", 1)[0]
        if first:
            bad = _rpc(url, "tools/call", {"name": "tra_ket_qua", "arguments": {"id": jid, "ket_qua": {"sai": 1}}})["result"]
            assert bad["isError"] and "thiếu" in bad["content"][0]["text"]
            first = False
        res = answer(data)
        ok = _rpc(url, "tools/call", {"name": "tra_ket_qua", "arguments": {"id": jid, "ket_qua": json.dumps(res, ensure_ascii=False)}})["result"]
        assert not ok["isError"], ok


def test_dich_qua_mcp_tron_vong(gate):
    import re

    from icontent.config import load_config, with_overrides
    from icontent.translate import McpTranslator, SCHEMA

    cfg = with_overrides(load_config(), {"translate": {"provider": "mcp", "mcp_wait": 30}})
    ids = [3, 4, 5]

    def answer(data: str):
        return {"items": [{"id": int(i), "text": f"VI:{i}"} for i in re.findall(r'"id":\s*(\d+)', data)]}

    stop = threading.Event()
    ai = threading.Thread(target=_fake_ai, args=(gate, answer, stop), daemon=True)
    ai.start()
    tr = McpTranslator(cfg.translate)
    user = json.dumps([{"id": i, "zh": "你好"} for i in ids], ensure_ascii=False)
    got = tr.call(user, ids)
    stop.set()
    assert got == {3: "VI:3", 4: "VI:4", 5: "VI:5"}
    assert SCHEMA["type"] == "object"


def test_khong_ai_nao_vao_thi_bao_het_gio(gate):
    from icontent import mcpcloud

    t0 = time.time()
    with pytest.raises(TimeoutError):
        mcpcloud.run_job("Dịch", "x", None, title="thử hết giờ", wait=3, poll=0.5)
    assert time.time() - t0 < 10
    assert mcpcloud.status()["pending"] == 0      # việc hết giờ đã được dọn khỏi hàng chờ


def test_cai_cong_len_cloudflare_dung_trinh_tu(tmp_path, monkeypatch):
    """Không gọi Cloudflare thật: ghi lại các lệnh API mà deploy() gửi đi."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from icontent import mcpcloud

    calls = []

    def fake_cf(method, path, token, body=None, headers=None):
        calls.append((method, path, body, headers))
        if path.startswith("/accounts?"):
            return {"success": True, "result": [{"id": "acc1"}]}
        if path.endswith("/workers/subdomain") and method == "GET":
            return {"success": True, "result": {"subdomain": "ban"}}
        return {"success": True, "result": {}}

    monkeypatch.setattr(mcpcloud, "_cf", fake_cf)
    c = mcpcloud.deploy("tok")
    assert c["url"] == "https://studio566-mcp.ban.workers.dev"
    up = next(x for x in calls if x[0] == "PUT" and x[1].endswith("/scripts/studio566-mcp"))
    body = up[2].decode("utf-8", "replace")
    assert '"new_sqlite_classes": ["Queue"]' in body and '"MCP_SECRET"' in body and "export class Queue" in body
    assert up[3]["Content-Type"].startswith("multipart/form-data; boundary=")
    assert any(x[1].endswith("/scripts/studio566-mcp/subdomain") and x[2] == {"enabled": True, "previews_enabled": False} for x in calls)
    assert mcpcloud.configured() and mcpcloud.ai_url().endswith("/mcp/" + c["mcp_secret"])
    # cập nhật lần sau: không gửi lại phần tạo hàng chờ, giữ nguyên mật khẩu; đổi địa chỉ thì mật khẩu AI mới
    calls.clear()
    c2 = mcpcloud.deploy("")
    up2 = next(x for x in calls if x[0] == "PUT" and x[1].endswith("/scripts/studio566-mcp"))
    assert b"new_sqlite_classes" not in up2[2] and c2["mcp_secret"] == c["mcp_secret"]
    c3 = mcpcloud.deploy("", rotate_mcp=True)
    assert c3["mcp_secret"] != c["mcp_secret"] and c3["app_secret"] == c["app_secret"]
