"""Bắt đầu lần đầu: kết nối Gemini chỉ bằng một ô dán key, tải trước mô hình AI để video đầu tiên không phải ngồi chờ tải.

Tải trước chạy trong hàng đợi chung như một video: có tiến độ, hủy được, và không tranh mạng, GPU với video đang dựng.
"""
from __future__ import annotations

from .translate import GEMINI_AUTO, GEMINI_HOST
from .util import log, stage

GEMINI_KEY = "GEMINI_API_KEY"
GEMINI_CFG = {"provider": "openai", "model": GEMINI_AUTO, "base_url": f"https://{GEMINI_HOST}/v1beta/openai/", "api_key_env": GEMINI_KEY}


def is_gemini(tcfg) -> bool:
    return tcfg.get("provider") == "openai" and GEMINI_HOST in str(tcfg.get("base_url") or "")


def should_switch(tcfg, ready: bool) -> bool:
    """Vừa kết nối Gemini thì dùng Gemini để dịch, trừ khi đang dùng một AI khác chạy được (Claude, DeepSeek, OpenAI có key).
    Dịch offline, Google dịch hay AI chưa có key đều kém hơn Gemini nên đổi."""
    p = tcfg.get("provider")
    if is_gemini(tcfg):
        return True      # để chuẩn hóa tên model: bản cũ ghi gemini-2.5-flash, Google đã thôi cho key mới dùng
    if p in ("claude", "openai", "mcp") and ready:
        return False
    return True


def pending(cfg) -> list[dict]:
    """Mô hình còn thiếu trên máy: [{id, name, mb}]."""
    from .asr import WHISPER_REPOS, model_ready
    from .util import hf_cache_dir

    out = []
    if not model_ready(cfg.asr.model):
        out.append({"id": "asr", "name": f"Nhận dạng giọng nói ({cfg.asr.model})", "mb": WHISPER_REPOS[cfg.asr.model][1]})
    if cfg.tts.enabled and cfg.tts.engine == "vieneu" and not list(hf_cache_dir().glob("models--pnnbao-ump--VieNeu*/snapshots/*")):
        out.append({"id": "tts", "name": "Bộ giọng đọc VieNeu", "mb": 1000})
    if cfg.tts.enabled and cfg.tts.voice_mode == "auto" and cfg.tts.get("diarize", True):
        from .speakers import MODEL_MB, available, model_cached
        if available() and not model_cached():
            out.append({"id": "speakers", "name": "Nhận diện người nói", "mb": MODEL_MB})
    return out


def prefetch(cfg, only: list[str] | None = None) -> None:
    """Tải các mô hình còn thiếu. Mỗi bước dùng đúng hàm tải mà lúc dựng video sẽ gọi, nên tải xong là lần sau dùng ngay.
    only: tải đúng các nhóm này dù cài đặt hiện tại không dùng (nút "Tải lại mô hình" ở thẻ lỗi, xem fixes.py)."""
    if only:
        from .fixes import MODEL_NAMES
        todo = [{"id": k, "name": MODEL_NAMES.get(k, k), "mb": {"tts": 1000}.get(k, 300)} for k in only if k in ("asr", "tts", "speakers")]
    else:
        todo = pending(cfg)
    if not todo:
        log("models", "Mọi mô hình AI đã có trên máy")
        return
    log("models", "Tải trước: " + ", ".join(f"{x['name']} (~{x['mb']} MB)" for x in todo))
    for x in todo:
        if x["id"] == "asr":
            from .asr import _ensure_model_file
            stage("asr")
            _ensure_model_file(cfg.asr.model)
        elif x["id"] == "tts":
            from .tts import _VieNeu
            stage("tts")
            _VieNeu.get()      # tải rồi nạp sẵn: video đầu tiên đọc lời ngay
        elif x["id"] == "speakers":
            from .speakers import _get_extractor
            stage("voice")
            _get_extractor()
        log("models", f"Xong: {x['name']}")
