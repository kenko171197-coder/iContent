"""API "Cách khắc phục": nút sửa ngay trên thẻ lỗi (cookie, sửa/tải lại mô hình, cập nhật bộ tải video, thử lại)."""
from __future__ import annotations

import gc
import os
import threading
import time
import webbrowser
from urllib.parse import urlparse

from fastapi import Body, HTTPException, Request

from .. import fixes
from ..util import log

COOKIE_LIMIT = 2 * 1024 * 1024
# chỉ mở được các trang này trên trình duyệt của khách (trang lạ không lợi dụng được)
OPEN_HOSTS = ("douyin.com", "bilibili.com", "kuaishou.com", "xiaohongshu.com", "chromewebstore.google.com", "addons.mozilla.org",
              "microsoftedge.microsoft.com")


def mount(app, st) -> None:
    upd_lock = threading.Lock()

    def item(qid: str) -> dict:
        with st.lock:
            it = next((i for i in st.items if i["qid"] == qid), None)
        if it is None:
            raise HTTPException(404, "Không thấy mục trong hàng đợi")
        return it

    @app.post("/api/queue/{qid}/retry")
    def retry(qid: str):
        """Chạy lại mục lỗi/đã hủy, kể cả khi lỗi ngay bước tải (chưa có job): dùng lại đúng link và tùy chọn đã chọn."""
        it = item(qid)
        if it["state"] in ("queued", "running"):
            raise HTTPException(409, "Mục này đang chạy")
        if (it.get("kind") or "video") not in ("video", "prefetch"):
            # câu chuyện, bản ghép có trạng thái riêng: dựng lại từ trang của chúng
            raise HTTPException(409, "Mở câu chuyện (hoặc trang Ghép video) rồi bấm dựng lại ở đó")
        new = st.enqueue(it["src"], it.get("options") or {}, it.get("from_stage"), title=it.get("title") if it.get("job") else "",
                         job=it.get("job"), targets=it.get("targets"), clips=it.get("clips"), kind=it.get("kind") or "video",
                         payload=it.get("payload"), profiles=it.get("profiles"), clip_profile=it.get("clip_profile") or "",
                         editor_base=bool(it.get("editor_base")))
        with st.lock:
            if it in st.items:
                st.items.remove(it)
        return {"qid": new}

    @app.post("/api/fixes/diagnose")
    def diagnose(body: dict = Body(...)):
        return {"help": fixes.diagnose(str(body.get("text") or "")[:6000], str(body.get("src") or ""))}

    # ------------------------------------------------------------------ cookie
    @app.get("/api/fixes/cookies")
    def cookies():
        return {"sites": fixes.cookie_status(), "extensions": fixes.EXTENSIONS}

    @app.put("/api/fixes/cookies/{site}")
    async def put_cookies(site: str, request: Request):
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
            if len(data) > COOKIE_LIMIT:
                raise HTTPException(413, "File quá lớn, không phải file cookie")
        try:
            return fixes.save_cookies(site, data.decode("utf-8", errors="replace"))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/fixes/cookies/{site}/from-downloads")
    def cookies_from_downloads(site: str, body: dict = Body(...)):
        """Trình hướng dẫn hỏi vài giây một lần: khách bấm Export trong tiện ích là file vào Tải về, iContent nạp luôn."""
        try:
            since = float(body.get("since") or 0)
        except (TypeError, ValueError):
            since = 0.0
        try:
            return fixes.cookie_from_downloads(site, max(since, time.time() - 86400))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    # ------------------------------------------------------------------ hỗ trợ: kiểm tra máy, gói báo lỗi (icontent/support.py)
    @app.get("/api/support/checks")
    def support_checks():
        from .. import support
        return {"checks": support.run_checks(deep=False, in_app=True)}      # đang chạy được trong iContent thì thư viện đã nạp đủ

    @app.post("/api/support/report")
    def support_report(body: dict = Body(default={})):
        from .. import support
        p = support.make_report(support.run_checks(deep=False, in_app=True), str(body.get("note") or "")[:4000])
        if not getattr(app.state, "no_browser", False):
            support.reveal(p)
        return {"path": str(p), "name": p.name, "size": p.stat().st_size}

    @app.post("/api/support/tool")
    def support_tool():
        """Mở cửa sổ Sửa lỗi iContent (chạy riêng, bằng Python kèm trong gói)."""
        import subprocess

        from .. import support
        subprocess.Popen([str(support.runtime_python()), "-m", "icontent.support"], cwd=str(support.ROOT))
        return {"ok": True}

    @app.delete("/api/fixes/cookies/{site}")
    def del_cookies(site: str):
        try:
            fixes.delete_cookies(site)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True}

    @app.post("/api/fixes/test-link")
    def test_link(body: dict = Body(...)):
        """Đọc thử thông tin video (không tải): sau khi nạp cookie, biết ngay dùng được chưa."""
        from ..download import _extract, normalize_url, platform_of, _ytdlp_opts
        src = str(body.get("url") or "").strip()
        if not src:
            raise HTTPException(400, "Thiếu link")
        try:
            import yt_dlp
            from yt_dlp.utils import DownloadError
            url = normalize_url(src)
            plat = platform_of(url)
            opts = _ytdlp_opts(st.cfg(), plat)
            opts.pop("progress_hooks", None)
            opts["retries"] = opts["extractor_retries"] = 1
            info = _extract(yt_dlp, DownloadError, url, plat, opts)
            return {"ok": True, "title": info.get("title") or "", "duration": info.get("duration")}
        except Exception as e:      # noqa: BLE001 — trả lỗi kèm lời chỉ dẫn
            return {"ok": False, "error": str(e)[:1500], "help": fixes.diagnose(str(e), src)}

    @app.post("/api/fixes/open")
    def open_url(body: dict = Body(...)):
        """Mở trang trên trình duyệt mặc định của khách (nơi có tiện ích và cookie của họ), không phải cửa sổ iContent."""
        url = str(body.get("url") or "")
        u = urlparse(url)
        host = (u.hostname or "").lower()
        if u.scheme != "https" or not any(host == h or host.endswith("." + h) for h in OPEN_HOSTS):
            raise HTTPException(400, "Không mở trang này")
        if getattr(app.state, "no_browser", False):
            return {"ok": True, "opened": False}
        try:
            os.startfile(url)      # type: ignore[attr-defined]  # Windows: đúng trình duyệt mặc định
        except (AttributeError, OSError):
            webbrowser.open(url)
        return {"ok": True, "opened": True}

    # ------------------------------------------------------------------ mô hình
    @app.post("/api/fixes/repair-models")
    def repair_models():
        n = fixes.unsymlink_models()
        return {"fixed": n, "message": f"Đã sửa {n} file mô hình" if n else "Các file mô hình đã ở dạng đúng"}

    @app.post("/api/fixes/redownload")
    def redownload(body: dict = Body(...)):
        kind = str(body.get("model") or "tts")
        if kind not in fixes.MODEL_REPOS:
            raise HTTPException(400, "Không rõ mô hình cần tải lại")
        with st.lock:
            busy = any(i["state"] == "running" for i in st.items)
        if busy:
            raise HTTPException(409, "Đang có việc chạy trong hàng đợi. Chờ xong (hoặc hủy) rồi tải lại mô hình")
        if kind == "tts":
            from ..tts import _VieNeu
            with _VieNeu.lock:
                _VieNeu._inst = None      # nhả file mô hình đang mở (Windows không xóa được file đang mở)
                gc.collect()
                gone = fixes.remove_model_cache(kind)
        else:
            gc.collect()
            gone = fixes.remove_model_cache(kind, st.cfg().asr.model)
        log("models", f"Tải lại {fixes.MODEL_NAMES[kind]}: đã xóa {len(gone)} thư mục bộ đệm")
        qid = st.enqueue("Tải lại " + fixes.MODEL_NAMES[kind], {}, None, title="Tải lại " + fixes.MODEL_NAMES[kind], kind="prefetch",
                         payload={"only": [kind]})
        return {"qid": qid, "removed": gone}

    # ------------------------------------------------------------------ bộ tải video
    @app.post("/api/fixes/update-ytdlp")
    def update_ytdlp():
        with st.lock:
            downloading = any(i["state"] == "running" and (i.get("stage") in (None, "download")) and (i.get("kind") or "video") == "video"
                              for i in st.items)
        if downloading:
            raise HTTPException(409, "Đang có video đang tải. Chờ tải xong rồi cập nhật")
        if not upd_lock.acquire(blocking=False):
            raise HTTPException(409, "Đang cập nhật rồi")
        try:
            return fixes.update_ytdlp()
        except Exception as e:      # noqa: BLE001
            raise HTTPException(502, str(e)) from e
        finally:
            upd_lock.release()
