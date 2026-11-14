"""API cho Mô-đun AI miễn phí (localai.py): xem gói, tải (tiếp tục được), dừng, xóa, chạy thử."""
from __future__ import annotations

import threading
import time

from fastapi import HTTPException
from fastapi.responses import FileResponse

TEST_PROMPT = ("A cozy Vietnamese street food stall at dusk, warm paper lanterns, a smiling vendor cooking a bowl of pho, steam rising, "
               "cinematic photo, soft light, shallow depth of field")
_test_lock = threading.Lock()


def _test_image_path():
    from ..localai import AI_DIR
    return AI_DIR / "test.png"


def _test_audio_path():
    from ..localai import AI_DIR
    return AI_DIR / "test.wav"


def test_pack(pid: str) -> str:
    """Chạy thử ngay trên máy này: dịch một câu, hoặc vẽ một ảnh nhỏ. Trả về lời báo kết quả."""
    from .. import localai
    if pid == "translate":
        from ..offline import self_test
        return self_test(None)
    if pid == "voices":
        from .. import voxtts
        p = _test_audio_path()
        p.unlink(missing_ok=True)
        t0 = time.time()
        failed = voxtts.synth_many([("Hi everyone! This is the multilingual voice of iContent Studio, ready to dub your videos.", "en_f1", "", p)])
        if failed or not p.is_file():
            raise RuntimeError("Bộ đọc nhiều thứ tiếng chưa đọc được. Xem nhật ký ở thư mục ai/logs/voices.log")
        return f"Đọc thử xong trong {time.time() - t0:.0f} giây (gồm cả lúc bật bộ đọc lần đầu)."
    if not _test_lock.acquire(blocking=False):
        raise RuntimeError("Đang vẽ thử, đợi xong đã")
    try:
        t0 = time.time()
        data = localai.draw(TEST_PROMPT, aspect="1:1", size=(512, 512), seed=7)
        p = _test_image_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return f"Vẽ thử xong trong {time.time() - t0:.0f} giây (ảnh nhỏ 512x512; ảnh dọc 720x1280 của video lâu hơn khoảng 3 lần)."
    finally:
        _test_lock.release()


def mount(app, st) -> None:
    from .. import localai

    def _pack(pid: str) -> str:
        if pid not in localai.PACKS:
            raise HTTPException(404, "Không có gói này")
        return pid

    @app.get("/api/ai/packs")
    def ai_packs():
        return localai.status()

    @app.get("/api/ai/devices")
    def ai_devices():
        return {"devices": localai.devices()}

    @app.post("/api/ai/packs/{pid}/download")
    def ai_download(pid: str):
        _pack(pid)
        if not localai.begin(pid, after=lambda: test_pack(pid)):
            raise HTTPException(409, "Gói này đang tải")
        return {"ok": True}

    @app.post("/api/ai/packs/{pid}/cancel")
    def ai_cancel(pid: str):
        localai.cancel(_pack(pid))
        return {"ok": True}

    @app.delete("/api/ai/packs/{pid}")
    def ai_remove(pid: str):
        try:
            freed = localai.remove(_pack(pid))
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from e
        st._cache.pop("status", None)
        return {"ok": True, "freed_mb": round(freed / 1e6)}

    @app.post("/api/ai/packs/{pid}/test")
    def ai_test(pid: str):
        _pack(pid)
        if not localai.pack_ready(pid):
            raise HTTPException(409, "Gói chưa tải xong")
        try:
            msg = test_pack(pid)
        except Exception as e:      # noqa: BLE001 — báo đúng lời giải thích tiếng Việt
            raise HTTPException(502, str(e)[:500]) from e
        return {"message": msg, "image": f"/api/ai/test-image?t={int(time.time())}" if pid == "image" else "",
                "audio": f"/api/ai/test-audio?t={int(time.time())}" if pid == "voices" else ""}

    @app.get("/api/ai/test-audio")
    def ai_test_audio():
        p = _test_audio_path()
        if not p.is_file():
            raise HTTPException(404, "Chưa đọc thử")
        return FileResponse(p, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @app.get("/api/ai/test-image")
    def ai_test_image():
        p = _test_image_path()
        if not p.is_file():
            raise HTTPException(404, "Chưa vẽ thử")
        return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-store"})
