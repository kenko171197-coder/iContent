"""Công tắc "Cho phép tính năng trả phí" (Cài đặt). Studio566 ưu tiên cách miễn phí; việc tốn tiền chỉ chạy khi người dùng bật.

Trả phí ở đây là gọi API tính tiền theo lượt: vẽ ảnh bằng Gemini, OpenAI, Meta Muse; làm clip bằng Gemini Omni.
Miễn phí: vẽ trên máy, Cloudflare (hạn mức hằng ngày), video nền từ kho, viết kịch bản bằng Gemini gói miễn phí hoặc AI trên máy.
Dịch bằng Claude, DeepSeek... do người dùng tự chọn và tự dán key trong Kết nối AI, không thuộc công tắc này.

Chưa bật tắt lần nào: máy đã từng vẽ được bằng nguồn trả phí (người dùng đã chủ động bật thanh toán) thì coi như bật, không thì tắt.
"""
from __future__ import annotations

import json

from .util import ROOT

PREF_FILE = ROOT / "paid.json"
PAID_IMAGE = ("gemini", "openai", "meta")
FREE_IMAGE = ("local", "cloudflare")


def _read() -> dict:
    try:
        return json.loads(PREF_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _used_paid_before() -> bool:
    from . import imagegen, videogen
    return any(imagegen.status(p).get("state") == "ok" for p in PAID_IMAGE if imagegen.ready(p)) or videogen.status("omni").get("state") == "ok"


def allowed() -> bool:
    v = _read().get("allowed")
    return bool(v) if isinstance(v, bool) else _used_paid_before()


def set_allowed(on: bool) -> None:
    PREF_FILE.write_text(json.dumps({"allowed": bool(on)}), encoding="utf-8")


def status() -> dict:
    v = _read().get("allowed")
    return {"allowed": allowed(), "chosen": isinstance(v, bool)}


OFF_MSG = ("Đang tắt tính năng trả phí nên Studio566 không gọi {what}. Dùng cách miễn phí ({free}), hoặc vào Cài đặt, mục Chi phí, "
           "bật Cho phép tính năng trả phí.")


def block(what: str, free: str) -> str:
    return OFF_MSG.format(what=what, free=free)
