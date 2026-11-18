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
import urllib.error
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
    proc = subprocess.Popen(["node", str(ROOT / "cloudflare" / "dev-server.mjs"), str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("STUDIO566_MCP_SERVER", f"http://127.0.0.1:{port}")
    from icontent import mcpcloud
    c = mcpcloud.connect()
    yield mcpcloud.ai_url(c)
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
    from icontent import mcpcloud
    mcpcloud.gate_reset("thử")
    mcpcloud.gate_answer(True)          # người dùng đã bấm Bắt đầu

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


def test_ket_noi_doi_dia_chi_ngat(gate):
    from icontent import mcpcloud

    assert mcpcloud.configured() and "/mcp/" in gate
    assert _rpc(gate, "ping")["result"] == {}
    c2 = mcpcloud.rotate()
    new = mcpcloud.ai_url(c2)
    assert new != gate
    with pytest.raises(urllib.error.HTTPError):
        _rpc(gate, "ping")             # địa chỉ cũ hết dùng
    assert _rpc(new, "ping")["result"] == {}
    mcpcloud.disconnect()
    assert not mcpcloud.configured()
    with pytest.raises(urllib.error.HTTPError):
        _rpc(new, "ping")              # kênh đã bị xóa trên cổng
