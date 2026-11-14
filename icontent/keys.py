"""API key nhập trong Studio: lưu cục bộ ở keys.json (không commit, không gửi đi đâu ngoài chính nhà cung cấp đó).

Thứ tự ưu tiên: biến môi trường (setx ...) > keys.json. Khi ghi đè hay nạp lại, giá trị được đưa vào os.environ
để SDK tự đọc như bình thường.
"""
from __future__ import annotations

import json
import os
import time

from .util import ROOT

KEYS_FILE = ROOT / "keys.json"
ALLOWED = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY",
           "META_MODEL_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID",      # 3 cái này: tạo ảnh (imagegen.py)
           "PEXELS_API_KEY", "PIXABAY_API_KEY")      # video nền miễn phí (stock.py)
_from_file: set[str] = set()


def _read() -> dict:
    try:
        return json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def load_keys() -> None:
    """Đưa key đã lưu vào môi trường (không đè biến người dùng đã đặt)."""
    for name, value in _read().items():
        if name in ALLOWED and value and not os.environ.get(name):
            os.environ[name] = str(value)
            _from_file.add(name)


def set_key(name: str, value: str) -> None:
    if name not in ALLOWED:
        raise ValueError(f"Không hỗ trợ khóa {name}")
    value = (value or "").strip()
    data = _read()
    if value:
        data[name] = value
        os.environ[name] = value
        _from_file.add(name)
    else:
        data.pop(name, None)
        if name in _from_file:
            os.environ.pop(name, None)
            _from_file.discard(name)
    KEYS_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")


def key_status() -> dict:
    """Không bao giờ trả về key đầy đủ: chỉ có/không + 4 ký tự cuối để nhận ra."""
    out = {}
    for name in ALLOWED:
        v = os.environ.get(name) or ""
        out[name] = {"set": bool(v), "hint": ("…" + v[-4:]) if len(v) >= 8 else "",
                     "source": "" if not v else "file" if name in _from_file else "env"}
    return out


def _is_local(url: str) -> bool:
    return any(h in (url or "") for h in ("localhost", "127.0.0.1", "0.0.0.0"))


def translator_ready(tcfg) -> bool:
    """Đã đủ điều kiện gọi nhà cung cấp dịch đang chọn chưa (Google/none và máy chủ local không cần key)."""
    p = tcfg.provider
    if p in ("google", "none"):
        return True
    if p == "offline":
        from .offline import ready
        return ready(tcfg.get("offline_model"))
    if p == "mcp":
        from .mcpcloud import configured
        return configured()
    if p == "claude":
        return bool(os.environ.get(tcfg.get("api_key_env") or "ANTHROPIC_API_KEY"))
    if p == "openai":
        if _is_local(tcfg.get("base_url") or ""):
            return True
        return bool(os.environ.get(tcfg.get("api_key_env") or "OPENAI_API_KEY"))
    return True


def test_translator(tcfg) -> str:
    """Gọi thử 1 câu rất ngắn để biết key/model dùng được. Trả về bản dịch, lỗi thì raise."""
    from .translate import make_translator

    if tcfg.provider == "mcp":
        from . import mcpcloud
        st = mcpcloud.status()
        seen = int(st.get("ai_seen") or 0)
        who = f"{st.get('ai_name') or 'AI'} vào lần cuối " + time.strftime("%H:%M %d/%m", time.localtime(seen / 1000)) if seen else "chưa có AI nào nối vào"
        return f"Cổng MCP chạy tốt ({who}, {st.get('pending', 0)} việc đang chờ)"
    tr = make_translator(tcfg)
    if hasattr(tr, "one"):
        return tr.one({"id": 1, "zh": "你好，朋友们"})
    if not hasattr(tr, "json_call"):
        return ""
    schema = {
        "type": "object", "properties": {"text": {"type": "string"}},
        "required": ["text"], "additionalProperties": False,
    }
    res = tr.json_call("Dịch sang tiếng Việt. Trả JSON {\"text\": bản dịch}.", "你好，朋友们", schema, max_tokens=400)
    return str(res.get("text", ""))
