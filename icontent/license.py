"""Bản quyền Studio566: key do bot Telegram @Kichhoatkey_bot (dự án iKey_bot) cấp, ký Ed25519, gắn với mã máy. Kiểm hoàn toàn offline.

Key là `<payload>.<chữ ký>` (base64url). Payload là JSON kiểu iTube mà bot ký cho Studio566:
    {"app": "iContent", "license_id", "customer", "issued", "features", "fingerprint", "expires"}
chữ ký Ed25519 trên đúng các byte của payload. Máy người dùng chỉ có khoá CÔNG KHAI: kiểm được key, không tự tạo được key.

Ai khoá: bản phát hành (`icontent release`) sinh icontent/_build_info.py nhúng khoá công khai và ENFORCE=True, nên sửa config hay
biến môi trường không tắt được. Chạy từ mã nguồn (máy tác giả) thì không khoá, trừ khi đặt ICONTENT_LICENSE_ENFORCE=1 và
ICONTENT_LICENSE_PUBKEY (để thử).

Mã máy = sha256(MachineGuid của Windows | id ngẫu nhiên của lần cài)[:32]: đúng 32 ký tự 0-9a-f, dạng duy nhất bot nhận ra. Id lần cài và
key nằm ở %LOCALAPPDATA%\\iContent, ngoài thư mục cài: giải nén bản mới, cài lại vào thư mục khác trên cùng máy vẫn còn kích hoạt;
chép sang máy khác thì mã máy khác, key không chạy.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import _ed25519 as ed

APP = "iContent"
PRODUCT = "icontent"                 # mã sản phẩm trong bot: link t.me/<bot>?start=icontent_<mã máy>
DEFAULT_BOT = "Kichhoatkey_bot"
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{40,}\.[A-Za-z0-9_-]{40,}")      # giống bot: dán cả tin nhắn có key cũng nhận
FP_RE = re.compile(r"[0-9a-f]{32}")
_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_fp: str | None = None


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---------------------------------------------------------------- cấu hình nhúng lúc đóng gói
def _build_info() -> Any:
    try:
        from . import _build_info  # type: ignore[attr-defined]
        return _build_info
    except ImportError:
        return None


def enforced() -> bool:
    """Fork này đã gỡ khóa bản quyền: luôn trả False, không đọc _build_info hay biến môi trường.
    Giữ nguyên module và các API (/api/license, lệnh `license`) để giao diện và CLI cũ vẫn chạy, nhưng không bao giờ khóa."""
    return False


def public_key() -> bytes | None:
    info = _build_info()
    raw = getattr(info, "PUBLIC_KEY", "") if info is not None else ""
    raw = raw or os.environ.get("ICONTENT_LICENSE_PUBKEY", "").strip()
    try:
        key = _b64d(raw) if raw else b""
    except (ValueError, TypeError):
        return None
    return key if len(key) == 32 else None


def bot_name() -> str:
    info = _build_info()
    return (getattr(info, "TELEGRAM", "") if info is not None else "") or os.environ.get("ICONTENT_LICENSE_BOT", "") or DEFAULT_BOT


def data_dir() -> Path:
    """Nơi giữ key và id lần cài, ngoài thư mục cài đặt."""
    custom = os.environ.get("ICONTENT_LICENSE_DIR")
    if custom:
        return Path(custom)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".config")
    return Path(base) / "iContent"


# ---------------------------------------------------------------- mã máy
def _hardware_id() -> str:
    try:
        if sys.platform.startswith("win"):
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
                return str(winreg.QueryValueEx(k, "MachineGuid")[0])
        if sys.platform == "darwin":
            import subprocess
            r = subprocess.run(["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True, text=True, timeout=5)
            m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', r.stdout or "")
            if m:
                return m.group(1).strip()
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if Path(path).is_file():
                return Path(path).read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001 — không đọc được thì dùng địa chỉ card mạng, rồi id ngẫu nhiên
        pass
    node = uuid.getnode()
    return "" if (node >> 40) & 1 else f"{node:012x}"      # bit multicast: địa chỉ ngẫu nhiên, không dùng được


def _install_id() -> str:
    f = data_dir() / ".install_id"
    try:
        v = f.read_text(encoding="utf-8").strip()
        if v:
            return v
    except OSError:
        pass
    v = uuid.uuid4().hex
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(v, encoding="utf-8")
    except OSError:
        pass
    return v


def machine_fingerprint() -> str:
    """Mã máy 32 ký tự hex. Khách gửi mã này cho bot để xin key."""
    global _fp
    if _fp is None:
        _fp = hashlib.sha256(f"{_hardware_id()}|{_install_id()}".encode()).hexdigest()[:32]
    return _fp


# ---------------------------------------------------------------- kiểm key
def extract_token(text: str) -> str:
    """Khách hay dán cả tin nhắn của bot ("Key của bạn: ..."): lấy đúng phần key."""
    text = (text or "").strip()
    m = TOKEN_RE.search(text) or TOKEN_RE.search(re.sub(r"\s+", "", text))      # sau mới thử nối: key bị xuống dòng giữa chừng
    return m.group(0) if m else text


def verify_token(token: str) -> tuple[bool, dict[str, Any] | None, str]:
    """-> (đúng chữ ký và đúng phần mềm, claims, lý do nếu sai). Chưa xét máy, hạn."""
    pub = public_key()
    if not pub:
        return False, None, "Bản Studio566 này chưa gắn khoá bản quyền của tác giả. Hãy tải bản cài mới."
    token = extract_token(token)
    if token.count(".") != 1:
        return False, None, "Key sai định dạng. Hãy chép nguyên dòng key bot gửi (rất dài, có một dấu chấm ở giữa)."
    p64, s64 = token.split(".")
    try:
        payload, sig = _b64d(p64), _b64d(s64)
    except (ValueError, TypeError):
        return False, None, "Key không đọc được. Hãy chép lại nguyên dòng key bot gửi."
    if not ed.verify(pub, sig, payload):
        return False, None, "Key không đúng: có thể là key của phần mềm khác (iTube, iNew) hoặc bị chép thiếu, sửa mất một ký tự."
    try:
        claims = json.loads(payload)
        if not isinstance(claims, dict):
            raise ValueError
    except ValueError:
        return False, None, "Nội dung key không hợp lệ."
    if claims.get("app") not in (None, APP):
        return False, None, f"Đây là key của {claims.get('app')}, không phải Studio566."
    return True, claims, ""


def _expiry(claims: dict[str, Any]) -> datetime | None:
    raw = claims.get("expires")
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_left(exp: datetime | None) -> int | None:
    return None if exp is None else max(0, -int(-(exp - _now()).total_seconds() // 86400))


def _license_file() -> Path:
    return data_dir() / "license.json"


def _load_token() -> str:
    env = os.environ.get("ICONTENT_LICENSE_KEY", "").strip()
    if env:
        return env
    try:
        return str(json.loads(_license_file().read_text(encoding="utf-8")).get("token") or "").strip()
    except (OSError, ValueError, AttributeError):
        return ""


def _evaluate(token: str) -> dict[str, Any]:
    fp = machine_fingerprint()
    if not token:
        return {"licensed": False, "reason": "no_license", "claims": None, "message": "Máy này chưa kích hoạt Studio566."}
    ok, claims, err = verify_token(token)
    if not ok:
        return {"licensed": False, "reason": "invalid", "claims": None, "message": err}
    bound = claims.get("fingerprint")
    if bound and bound != fp:
        return {"licensed": False, "reason": "wrong_machine", "claims": claims,
                "message": "Key đã lưu là của một máy khác. Gửi mã máy của máy này cho bot để nhận key mới."}
    exp = _expiry(claims)
    if exp and _now() > exp:
        return {"licensed": False, "reason": "expired", "claims": claims, "_exp": exp,
                "message": f"Bản quyền đã hết hạn ngày {exp.astimezone():%d/%m/%Y}. Bấm Gia hạn qua Telegram, bot gửi key mới."}
    return {"licensed": True, "reason": "ok", "claims": claims, "_exp": exp, "message": "Bản quyền hợp lệ."}


def state(refresh: bool = False) -> dict[str, Any]:
    """Trạng thái hiện tại. Kiểm chữ ký (~0,3 giây) một lần rồi nhớ; hạn dùng thì so lại mỗi lần, app mở qua ngày hết hạn vẫn bị khoá."""
    global _cache
    with _lock:
        if not enforced():
            return {"licensed": True, "locked": False, "reason": "not_enforced", "claims": None, "enforced": False,
                    "message": "Bản chạy từ mã nguồn, không khoá bản quyền."}
        token = _load_token()
        stale = _cache is not None and _cache.get("licensed") and _cache.get("_exp") and _now() > _cache["_exp"]
        if refresh or _cache is None or _cache.get("_token") != token or stale:
            _cache = {**_evaluate(token), "_token": token}
        st = {k: v for k, v in _cache.items() if not k.startswith("_")}
        st["locked"] = not st["licensed"]
        st["enforced"] = True
        st["_exp"] = _cache.get("_exp")
        return st


def locked() -> bool:
    return bool(state().get("locked"))


def install_token(text: str) -> tuple[bool, str]:
    """Nhập key khách dán. Kiểm chữ ký, đúng phần mềm, đúng máy, còn hạn rồi mới lưu: key sai không đè mất key đang chạy."""
    ok, claims, err = verify_token(text)
    if not ok:
        return False, err
    bound = claims.get("fingerprint")
    if bound and bound != machine_fingerprint():
        return False, "Key này cấp cho máy khác (sai mã máy). Gửi đúng mã máy đang hiện ở đây cho bot để nhận key mới."
    exp = _expiry(claims)
    if exp and _now() > exp:
        return False, f"Key này đã hết hạn ngày {exp.astimezone():%d/%m/%Y}. Bấm Gia hạn qua Telegram để nhận key mới."
    f = _license_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".part")
    tmp.write_text(json.dumps({"token": extract_token(text), "installed": _now().isoformat(timespec="seconds")}), encoding="utf-8")
    os.replace(tmp, f)
    state(refresh=True)
    return True, "Đã kích hoạt Studio566."


def telegram_link(fp: str | None = None) -> str:
    return f"https://t.me/{bot_name()}?start={PRODUCT}_{fp or machine_fingerprint()}"


def public_state() -> dict[str, Any]:
    """Cho giao diện: trạng thái, mã máy, link bot kèm mã máy. Không bao giờ trả key."""
    st = state()
    claims = st.get("claims") or {}
    out = {k: st.get(k) for k in ("licensed", "locked", "reason", "message", "enforced")}
    if not st.get("enforced"):
        return out
    exp = st.get("_exp")
    out.update(machine=machine_fingerprint(), customer=claims.get("customer", ""), license_id=claims.get("license_id", ""),
               expires=exp.isoformat() if exp else None, days_left=_days_left(exp) if st["licensed"] else None,
               lifetime=bool(st["licensed"] and exp is None), bot=bot_name(), telegram=telegram_link())
    return out


def reset_cache() -> None:
    """Cho test: quên mã máy và trạng thái đã nhớ."""
    global _cache, _fp
    with _lock:
        _cache, _fp = None, None
