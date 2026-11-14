"""Studio566 — web UI chạy local (FastAPI).

  python -m icontent ui            -> http://127.0.0.1:8765

Một luồng nền xử lý hàng đợi tuần tự (GPU chỉ có một); model Whisper/VieNeu được giữ trong bộ nhớ giữa
các video. Log/tiến độ của pipeline đi qua util.add_listener.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote, urlparse

import numpy as np
import yaml
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .. import __version__, editor
from .. import license as license_mod
from ..about import about as about_info
from ..config import DEFAULTS, diff_dicts, load_config, with_overrides
from ..keys import ALLOWED as KEY_NAMES, key_status, load_keys, set_key, test_translator, translator_ready
from ..models import Segment, load_segments, save_segments, write_srt
from ..pipeline import STAGES, friendly_translate_error, is_fresh, job_options, load_json, run_job, save_job_options
from ..util import (ROOT, Cancelled, add_listener, ffmpeg, find_ffmpeg, log, read_wav, request_cancel,
                    reset_cancel, safe_name, short_hash, write_wav)

STATIC = Path(__file__).parent / "static"
# gọi được cả khi chưa kích hoạt: màn Kích hoạt cần chúng; ui/ping, ui/bye: trang còn mở hay đã đóng (appwin.stop_when_idle)
LICENSE_OPEN = {"/api/license", "/api/about", "/api/ui/ping", "/api/ui/bye"}


def qc_cached(p: Path) -> dict | None:
    from ..qc import cached
    return cached(p)


MEDIA = {"source.mp4", "final.mp4", "dub.wav", "audio.wav", "bgm.wav", "vocals.wav", "clean_band.mp4"}
MEDIA_RE = re.compile(r"^final_\w+\.mp4$")
EDITOR_LIVE_SECONDS = 90      # trình duyệt chỉ cho cửa sổ nền chạy hẹn giờ một lần mỗi phút nên phải dư
REC_NAME = re.compile(r"\d+_[0-9a-f]+\.wav")
PRESETS_FILE = ROOT / "presets.json"
SAVED_FILE = ROOT / "trends_saved.json"
IMAGES_DIR = ROOT / "assets" / "images"
MAX_IMAGE = 40 * 1024 * 1024
UPLOAD_EXT = {
    "video": {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".m4v"},
    "logo": {".png", ".webp", ".jpg", ".jpeg"},
    "music": {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"},
    "card": {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".png", ".webp", ".jpg", ".jpeg"},
    "lut": {".cube"},
}
# font Windows đã kiểm tra có đủ dấu tiếng Việt (Arial Black, Impact, Georgia, Trebuchet thì không)
FONT_CHOICES = [("Arial", "arialbd.ttf"), ("Segoe UI", "segoeui.ttf"), ("Segoe UI Semibold", "seguisb.ttf"),
                ("Segoe UI Black", "seguibl.ttf"), ("Bahnschrift", "bahnschrift.ttf"), ("Tahoma", "tahoma.ttf"),
                ("Verdana", "verdana.ttf"), ("Calibri", "calibri.ttf"), ("Cambria", "cambria.ttc"),
                ("Times New Roman", "times.ttf")]
TARGETS = ("9:16", "16:9", "1:1")


def _pending_downloads(cfg) -> list[dict]:
    """Các mô hình AI chưa có trên máy (sẽ tự tải ở lần chạy đầu, hoặc bấm Tải trước)."""
    from ..onboard import pending
    return pending(cfg)


def is_local_origin(origin: str) -> bool:
    return (urlparse(origin).hostname or "") in ("127.0.0.1", "localhost", "::1")


class _NoCacheStatic(StaticFiles):
    """Trình duyệt luôn hỏi lại file giao diện -> cập nhật Studio566 là thấy ngay, không cần xóa cache."""

    async def get_response(self, path, scope):
        r = await super().get_response(path, scope)
        r.headers["Cache-Control"] = "no-cache"
        return r


class Studio:
    def __init__(self, config_path: str | None):
        self.config_path = Path(config_path) if config_path else ROOT / "config.yaml"
        self.items: list[dict] = []
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.current: dict | None = None
        self._cache: dict = {}
        add_listener(self._on_event)
        threading.Thread(target=self._worker, daemon=True, name="icontent-worker").start()

    # ------------------------------------------------------------------ config
    def cfg(self):
        return load_config(self.config_path if self.config_path.exists() else None)

    def work(self) -> Path:
        w = Path(self.cfg().work_dir)
        return w if w.is_absolute() else ROOT / w

    def job_dir(self, jid: str) -> Path:
        if not jid or any(c in jid for c in "/\\") or jid.startswith("."):
            raise HTTPException(400, "Mã job không hợp lệ")
        p = self.work() / jid
        if not (p / "meta.json").exists():
            raise HTTPException(404, f"Không thấy job {jid}")
        return p

    # ------------------------------------------------------------------ queue
    def enqueue(self, src: str, options: dict | None, from_stage: str | None, title: str = "", job: str | None = None,
                targets: list[str] | None = None, clips: list | None = None, kind: str = "video", payload: dict | None = None,
                profiles: list[str] | None = None, clip_profile: str = "", editor_base: bool = False) -> str:
        if from_stage and from_stage not in STAGES:
            raise HTTPException(400, f"from_stage phải là một trong {STAGES}")
        it = {"qid": uuid.uuid4().hex[:10], "src": src, "title": title or src, "job": job, "state": "queued",
              "stage": None, "progress": None, "message": "Đang chờ ...", "error": None, "logs": [],
              "created": time.time(), "started": None, "finished": None, "from_stage": from_stage,
              "output": None, "options": options or {}, "targets": targets or [], "clips": clips or [], "kind": kind, "payload": payload,
              "profiles": profiles or [], "clip_profile": clip_profile, "editor_base": editor_base}
        with self.lock:
            self.items.insert(0, it)
            del self.items[150:]
        self.wake.set()
        return it["qid"]

    def busy_jobs(self) -> set[str]:
        with self.lock:
            return {i["job"] for i in self.items if i["job"] and i["state"] in ("queued", "running")}

    def _on_event(self, kind: str, data: dict) -> None:
        it = self.current
        if it is None or threading.current_thread().name.startswith(("AnyIO", "MainThread", "ui-")):
            return      # việc của giao diện (nạp giọng, nghe thử, ảnh bìa...) không chen vào video đang chạy
        with self.lock:
            if kind == "note":
                it["message"] = data["msg"]
            elif kind == "log":
                line = f"[{data['stage']}] {data['msg']}"
                it["logs"].append(line)
                del it["logs"][:-300]
                it["message"] = data["msg"].split("\n")[0][:200]
            elif kind == "stage":
                it["stage"], it["progress"] = data["stage"], None
            elif kind == "progress":
                it["progress"] = data["frac"]
            elif kind == "job":
                it["job"], it["title"] = data["job"], data.get("title") or it["title"]

    def _next(self) -> dict | None:
        with self.lock:
            for it in reversed(self.items):          # cũ nhất trước
                if it["state"] == "queued":
                    it["state"], it["started"] = "running", time.time()
                    return it
        return None

    def _worker(self) -> None:
        while True:
            it = self._next()
            if it is None:
                self.wake.wait(2)
                self.wake.clear()
                continue
            reset_cancel()
            self.current = it
            try:
                if it.get("kind") == "story":
                    from .content_api import run_story_job
                    out = run_story_job(self, it["payload"])
                elif it.get("kind") == "merge":
                    from ..montage import MergeStore, run_merge
                    cfg = self.cfg()
                    rec = run_merge(it["payload"], Path(cfg.output_dir), MergeStore(self.work() / ".merges"))
                    out = rec["path"]
                elif it.get("kind") == "prefetch":
                    from ..onboard import prefetch
                    prefetch(self.cfg(), **(it.get("payload") or {}))
                    out = None
                else:
                    out = run_job(it["src"], self.cfg(), it["from_stage"], it["options"] or None, it.get("targets") or None, it.get("clips") or None,
                                  it.get("profiles") or None, it.get("clip_profile") or "", bool(it.get("editor_base")))
                with self.lock:
                    it.update(state="done", output=str(Path(out).resolve()) if out else None, progress=1.0, stage="done",
                              message="Hoàn tất")
            except Cancelled:
                with self.lock:
                    it.update(state="cancelled", message="Đã hủy", progress=None)
            except Exception as e:  # lỗi của 1 video không làm sập worker
                from ..fixes import diagnose
                try:
                    hint = diagnose(str(e), it.get("src") or "", it.get("stage"))
                except Exception:      # chỉ dẫn hỏng không được làm mất lỗi gốc
                    hint = None
                with self.lock:
                    it.update(state="error", error=str(e)[-4000:], message=str(e).split("\n")[0][:200], help=hint)
                log("LỖI", str(e))
            finally:
                it["finished"] = time.time()
                self.current = None
                reset_cancel()

    def cancel(self, qid: str) -> None:
        with self.lock:
            it = next((i for i in self.items if i["qid"] == qid), None)
            if it is None:
                raise HTTPException(404, "Không thấy mục trong hàng đợi")
            if it["state"] == "queued":
                it.update(state="cancelled", message="Đã hủy", finished=time.time())
            elif it["state"] == "running":
                request_cancel()
                it["message"] = "Đang hủy ..."

    # ------------------------------------------------------------------ jobs
    def job_summary(self, p: Path, busy: set[str]) -> dict:
        meta = load_json(p / "meta.json") or {}
        lang = self.cfg().translate.target_lang
        n = 0
        if (p / "segments.json").exists():
            try:
                n = len(json.loads((p / "segments.json").read_text(encoding="utf-8")))
            except Exception:
                n = 0
        out = (load_json(p / "output.json") or {}).get("video")
        pub = ((load_json(p / "context.json") or {}).get("publish") or {}).get("title")
        return {
            "id": p.name, "title": meta.get("title") or p.name, "title_vi": pub or "", "platform": meta.get("platform", ""),
            "duration": meta.get("duration", 0), "width": meta.get("width", 0), "height": meta.get("height", 0),
            "created": (p / "meta.json").stat().st_mtime,
            "stages": {"download": (p / "source.mp4").exists(), "asr": (p / "segments.json").exists(),
                       "translate": (p / f"subs.{lang}.srt").exists(), "tts": (p / "dub.wav").exists(),
                       "render": (p / "final.mp4").exists()},
            "n_segments": n, "output": out if out and Path(out).exists() else None,
            "thumb": f"/api/jobs/{p.name}/thumb.jpg", "busy": p.name in busy,
        }

    def job_detail(self, p: Path) -> dict:
        opts = job_options(p)
        eff = with_overrides(self.cfg(), opts)
        segs = load_segments(p / "segments.json") if (p / "segments.json").exists() else []
        output = load_json(p / "output.json") or {}
        out = output.get("video")
        final = p / "final.mp4"
        stale = final.exists() and not is_fresh(p)
        return {
            "id": p.name, "meta": load_json(p / "meta.json"), "options": opts, "effective": eff,
            "cover": load_json(p / "cover.json"), "stale": stale,
            "extra": [x for x in output.get("extra") or [] if Path(x).exists()],
            "edited": editor.edited_items(p),
            "context": load_json(p / "context.json"), "hardsub": load_json(p / "hardsub.json"),
            "voice": load_json(p / "voice.json"), "speakers": load_json(p / "speakers.json"), "rendered": load_json(p / "render.json"),
            "qc": qc_cached(p),
            "segments": [asdict(s) for s in segs],
            "files": {"source": (p / "source.mp4").exists(), "final": final.exists(),
                      "dub": (p / "dub.wav").exists(), "audio": (p / "audio.wav").exists(),
                      "clean": (p / "clean_band.mp4").exists(), "cover": (p / "cover.jpg").exists()},
            "output": out if out and Path(out).exists() else None, "lang": eff.translate.target_lang,
            "busy": p.name in self.busy_jobs(),
        }


def create_app(config_path: str | None = None) -> FastAPI:
    load_keys()
    st = Studio(config_path)
    boot_id = uuid.uuid4().hex[:10]
    app = FastAPI(title="Studio566", version=__version__)
    app.state.studio = st
    from .. import autoupdate
    autoupdate.maybe_update_ytdlp()

    @app.get("/api/update")
    def get_update():
        return autoupdate.check_app_update()

    @app.middleware("http")
    async def same_origin_only(request: Request, call_next):
        """Trang web lạ đang mở trong trình duyệt không được ra lệnh cho Studio566 chạy trên máy (xóa video, ghi file...)."""
        if getattr(app.state, "check_host", False):
            # trang lạ trỏ tên miền của nó về 127.0.0.1 thì Origin vẫn trùng Host: phải kiểm tra chính Host
            host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
            if host not in ("127.0.0.1", "localhost", "::1", editor.HOST):
                return JSONResponse({"detail": "Tên máy không hợp lệ"}, status_code=403)
        if editor.is_editor_host(request.headers.get("host")):
            if not request.url.path.startswith("/api/"):
                return editor.static_response(request.url.path)      # trình dựng có origin riêng
            if not request.url.path.startswith("/api/editor/"):
                # trình dựng kèm vài trăm thư viện: lỡ có lỗ hổng thì cũng chỉ chạm được phần dành cho nó, không đọc được API key hay xóa video
                return JSONResponse({"detail": "Trình dựng không dùng API này"}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path != "/api/ui/bye":
            # còn trang đang mở, xem appwin.stop_when_idle. Phải tính trước khi chặn bản quyền: màn Kích hoạt cũng là trang đang mở
            # (khách sang Telegram xin key vài phút, máy chủ từng tưởng không còn ai và tự tắt, dán key thì báo mất kết nối)
            app.state.last_seen = time.time()
        if request.url.path.startswith("/api/") and request.url.path not in LICENSE_OPEN and license_mod.locked():
            # khoá ở máy chủ, không chỉ ở giao diện: chưa kích hoạt thì không gọi được chức năng nào, kể cả từ trình dựng
            return JSONResponse({"detail": license_mod.state()["message"], "license": license_mod.public_state()}, status_code=403)
        origin = request.headers.get("origin")
        if origin and request.method not in ("GET", "HEAD", "OPTIONS"):
            host = urlparse(origin).netloc
            if host != request.headers.get("host") and not is_local_origin(origin):
                return JSONResponse({"detail": "Yêu cầu từ trang web khác bị từ chối"}, status_code=403)
        return await call_next(request)

    app.mount("/static", _NoCacheStatic(directory=STATIC), name="static")
    from ..tts import _VieNeu
    tts_lock = _VieNeu.lock

    @app.get("/api/ui/ping")
    def ui_ping():
        """Trang còn mở (js/keepalive.js hỏi thăm từ luồng nền, trình duyệt không hãm như trang bị thu nhỏ). boot đổi nghĩa là
        máy chủ vừa chạy lại (appwin.supervise): trang báo cho khách, vẽ lại trang đang lỗi, không tải lại (giữ việc chưa lưu)."""
        return {"ok": True, "boot": boot_id}

    @app.post("/api/ui/bye")
    def ui_bye():
        """Trang vừa đóng hoặc tải lại (pagehide). Không còn trang nào hỏi thăm tiếp thì tắt sớm, xem appwin.stop_when_idle."""
        app.state.bye = time.time()
        return Response(status_code=204)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    # ------------------------------------------------------------------ status / config
    @app.get("/api/status")
    def status():
        if "status" not in st._cache:
            s = {"version": __version__, "ffmpeg": False, "nvenc": False, "libass": False, "cuda": False}
            try:
                ff, _ = find_ffmpeg()
                s["ffmpeg"] = True
                enc = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
                filt = subprocess.run([ff, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
                s["nvenc"], s["libass"] = "h264_nvenc" in enc, " ass " in filt
            except Exception:
                pass
            try:
                from ..asr import _add_cuda_dlls
                _add_cuda_dlls()
                import ctranslate2
                s["cuda"] = ctranslate2.get_cuda_device_count() > 0
            except Exception:
                pass
            from ..hardsub import available as ocr_ok
            from ..separate import available as sep_ok
            from ..speakers import available as speakers_ok
            s["ocr"], s["separator"], s["speakers"] = ocr_ok(), sep_ok(), speakers_ok()
            st._cache["status"] = s
        s = dict(st._cache["status"])
        s["keys"] = {"anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
                     "openai": bool(os.environ.get("OPENAI_API_KEY")),
                     "deepseek": bool(os.environ.get("DEEPSEEK_API_KEY")),
                     "gemini": bool(os.environ.get("GEMINI_API_KEY"))}
        tc = st.cfg().translate
        from ..offline import ready as offline_ready
        chosen = translator_ready(tc)
        s["offline"] = offline_ready(tc.get("offline_model"))
        from ..localai import pack_ready
        s["ai"] = {"translate": pack_ready("translate"), "image": pack_ready("image"), "voices": pack_ready("voices")}
        s["translator"] = {"provider": tc.provider, "ready": chosen or s["offline"], "chosen_ready": chosen, "model": tc.model}
        s["downloads"] = _pending_downloads(st.cfg())
        s["hints"] = {
            "ffmpeg": "winget install Gyan.FFmpeg",
            "nvenc": "Cần card NVIDIA — render nhanh hơn nhiều",
            "cuda": "Whisper chạy GPU (pip install nvidia-cublas-cu12 nvidia-cudnn-cu12)",
            "ocr": "Tự dò & đọc sub gốc: pip install rapidocr",
            "separator": 'Tách nhạc nền khỏi giọng gốc: pip install "audio-separator[gpu]"',
            "anthropic": "setx ANTHROPIC_API_KEY sk-ant-... rồi mở lại Studio",
            "openai": "setx OPENAI_API_KEY ... (OpenAI / tương thích)",
            "deepseek": "setx DEEPSEEK_API_KEY ... (provider openai + base_url https://api.deepseek.com)",
        }
        s["config_path"] = str(st.config_path)
        return s

    @app.get("/api/config")
    def get_config():
        user = {}
        if st.config_path.exists():
            user = yaml.safe_load(st.config_path.read_text(encoding="utf-8")) or {}
        from .. import voxtts
        from ..langs import public as langs_public
        # thư viện giọng nhiều thứ tiếng nằm sẵn trên đĩa, gửi luôn: /api/voices lần đầu phải nạp VieNeu, mất vài giây
        return {"config": st.cfg(), "defaults": DEFAULTS, "user": user, "path": str(st.config_path), "langs": langs_public(),
                "vox_voices": voxtts.voices(), "vox_ready": voxtts.ready()}

    @app.put("/api/config")
    def put_config(body: dict = Body(...)):
        user = body.get("user")
        if not isinstance(user, dict):
            raise HTTPException(400, "user phải là object")
        user = diff_dicts(with_overrides(DEFAULTS, user), DEFAULTS)
        try:
            load_config(None, user)
        except Exception as e:
            raise HTTPException(400, f"Cấu hình không hợp lệ: {e}")
        p = st.config_path
        bak = p.with_suffix(".yaml.bak")
        if p.exists() and not bak.exists():
            shutil.copy2(p, bak)          # giữ bản gốc (có chú thích) lần đầu ghi đè
        p.write_text("# Ghi bởi Studio566. Bản trước: config.yaml.bak\n"
                     + yaml.safe_dump(user, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return {"ok": True}

    # ------------------------------------------------------------------ giới thiệu, font, công thức
    @app.get("/api/about")
    def get_about():
        return about_info()

    @app.get("/api/fonts")
    def fonts():
        root = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        return {"fonts": [name for name, fn in FONT_CHOICES if (root / fn).exists()] or ["Arial"]}

    @app.get("/api/presets")
    def get_presets():
        return {"presets": load_json(PRESETS_FILE) or []}

    @app.put("/api/presets")
    def put_presets(body: dict = Body(...)):
        items = body.get("presets")
        if not isinstance(items, list) or not all(isinstance(i, dict) and i.get("name") for i in items):
            raise HTTPException(400, "presets phải là danh sách có tên")
        for i in items:
            try:
                with_overrides(st.cfg(), i.get("options") or {})
            except Exception as e:
                raise HTTPException(400, f"Công thức {i.get('name')} không hợp lệ: {e}")
        PRESETS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"ok": True}

    # ------------------------------------------------------------------ kết nối AI dịch
    @app.get("/api/keys")
    def get_keys():
        return {"keys": key_status(), "names": list(KEY_NAMES)}

    @app.put("/api/keys")
    def put_key(body: dict = Body(...)):
        name = body.get("name")
        if name not in KEY_NAMES:
            raise HTTPException(400, f"Khóa phải là một trong {KEY_NAMES}")
        set_key(name, str(body.get("value") or ""))
        return {"keys": key_status()}

    @app.post("/api/keys/test")
    def test_key(body: dict = Body(default={})):
        """Dịch thử 1 câu ngắn bằng cấu hình đang nhập (chưa cần lưu)."""
        cfg = with_overrides(st.cfg(), {"translate": {k: body[k] for k in ("provider", "model", "base_url", "api_key_env")
                                                      if k in body}})
        if not translator_ready(cfg.translate):
            raise HTTPException(400, "Chưa cài cổng MCP" if cfg.translate.provider == "mcp" else "Chưa có API key cho nhà cung cấp này")
        try:
            return {"ok": True, "sample": test_translator(cfg.translate)}
        except Exception as e:
            raise HTTPException(502, friendly_translate_error(e, cfg.translate.provider))

    # ------------------------------------------------------------------ AI qua MCP (cổng trên Cloudflare Workers)
    @app.get("/api/mcp")
    def mcp_get():
        from .. import mcpcloud
        c = mcpcloud.load_conf()
        out = {"configured": mcpcloud.configured(), "ai_url": mcpcloud.ai_url(c), "url": c.get("url", ""),
               "deployed_at": c.get("deployed_at", 0), "has_token": bool(c.get("cf_token"))}
        if out["configured"]:
            try:
                out["status"] = mcpcloud.status()
            except Exception as e:      # noqa: BLE001
                out["error"] = str(e)[:200]
        return out

    @app.post("/api/mcp/deploy")
    def mcp_deploy(body: dict = Body(default={})):
        """Cài hoặc cập nhật cổng lên Cloudflare. rotate: đổi mật khẩu cho AI (địa chỉ MCP mới, phải dán lại vào các app AI)."""
        from .. import mcpcloud
        try:
            c = mcpcloud.deploy(str(body.get("token") or ""), rotate_mcp=bool(body.get("rotate")))
            st_ = mcpcloud.status(wait_ready=45)
        except mcpcloud.McpError as e:
            raise HTTPException(400, f"Chưa cài được cổng MCP: {e}")
        return {"ok": True, "ai_url": mcpcloud.ai_url(c), "url": c["url"], "status": st_}

    @app.delete("/api/mcp")
    def mcp_forget():
        from .. import mcpcloud
        mcpcloud.forget()
        return {"ok": True}

    # ------------------------------------------------------------------ bản quyền (đã tắt, API giữ cho giao diện cũ)
    @app.get("/api/license")
    def license_get():
        return license_mod.public_state()

    @app.post("/api/license")
    def license_install(body: dict = Body(...)):
        text = str(body.get("key") or "")
        if not text.strip():
            raise HTTPException(400, "Chưa dán key")
        if len(text) > 5000:
            raise HTTPException(400, "Đoạn dán quá dài: chỉ chép dòng key bot gửi")
        ok, msg = license_mod.install_token(text)
        if not ok:
            raise HTTPException(400, msg)
        return {**license_mod.public_state(), "ok": True, "detail": msg}

    # ------------------------------------------------------------------ bắt đầu lần đầu
    def _write_user_config(user: dict) -> None:
        user = diff_dicts(with_overrides(DEFAULTS, user), DEFAULTS)
        load_config(None, user)      # lỗi thì dừng ở đây, không ghi file hỏng
        p = st.config_path
        bak = p.with_suffix(".yaml.bak")
        if p.exists() and not bak.exists():
            shutil.copy2(p, bak)
        p.write_text("# Ghi bởi Studio566. Bản trước: config.yaml.bak\n"
                     + yaml.safe_dump(user, allow_unicode=True, sort_keys=False), encoding="utf-8")

    @app.post("/api/onboard/gemini")
    def onboard_gemini(body: dict = Body(...)):
        """Dán key Gemini: dịch thử một câu bằng chính key đó, được thì lưu key và dùng Gemini để dịch. Sai key thì không lưu gì."""
        from .. import onboard
        key = str(body.get("key") or "").strip().strip('"').strip("'")
        if len(key) < 30 or len(key) > 200 or any(c.isspace() for c in key):
            raise HTTPException(400, "Key chưa đúng: key Gemini dài khoảng 39 ký tự, thường bắt đầu bằng AIza. Hãy bấm nút chép (Copy) ở trang Google rồi dán lại.")
        tcfg = with_overrides(st.cfg(), {"translate": onboard.GEMINI_CFG}).translate
        old = os.environ.get(onboard.GEMINI_KEY)
        os.environ[onboard.GEMINI_KEY] = key      # thử trước, chưa ghi vào keys.json
        try:
            sample = test_translator(tcfg)
        except Exception as e:
            msg = friendly_translate_error(e, "openai")
            if msg.startswith("API key không đúng"):      # đang ở ô dán key: chỉ cách sửa ngay tại đây, không bảo vào Cài đặt
                msg = "Google báo key này không đúng. Ở trang lấy key, bấm nút chép (Copy) cạnh key rồi dán lại vào đây. Key thường bắt đầu bằng AIza."
            raise HTTPException(400, msg) from None
        finally:
            if old is None:
                os.environ.pop(onboard.GEMINI_KEY, None)
            else:
                os.environ[onboard.GEMINI_KEY] = old
        set_key(onboard.GEMINI_KEY, key)
        cur = st.cfg().translate
        switched = onboard.should_switch(cur, translator_ready(cur))
        if switched:
            user = yaml.safe_load(st.config_path.read_text(encoding="utf-8")) if st.config_path.exists() else {}
            user = user or {}
            user["translate"] = {**(user.get("translate") or {}), **onboard.GEMINI_CFG}
            _write_user_config(user)
        st._cache.pop("status", None)
        return {"ok": True, "sample": sample, "switched": switched, "keys": key_status()}

    @app.post("/api/models/prefetch")
    def models_prefetch():
        """Tải trước mô hình AI còn thiếu, qua hàng đợi chung."""
        with st.lock:
            cur = next((i for i in st.items if i.get("kind") == "prefetch" and i["state"] in ("queued", "running")), None)
        if cur:
            return {"qid": cur["qid"], "already": True}
        todo = _pending_downloads(st.cfg())
        if not todo:
            return {"qid": None, "nothing": True}
        mb = sum(x["mb"] for x in todo)
        return {"qid": st.enqueue("prefetch", None, None, title=f"Tải trước mô hình AI (~{mb / 1000:.1f} GB)".replace(".", ","), kind="prefetch")}

    # ------------------------------------------------------------------ dịch offline: giữ cho giao diện cũ, nay là gói "translate" của localai
    @app.get("/api/offline")
    def offline_status():
        from .. import localai, offline
        t = localai.TASKS.get("translate")
        return {**offline.status(st.cfg().translate.get("offline_model")),
                "setup": t.view() if t else {"running": False, "error": "", "done": False, "message": ""}}

    @app.post("/api/offline/setup")
    def offline_setup():
        from .. import offline
        if not offline.begin_setup(st.cfg().translate.get("offline_model")):
            raise HTTPException(409, "Đang tải rồi")
        return {"ok": True}

    @app.post("/api/offline/cancel")
    def offline_cancel():
        from .. import localai
        localai.cancel("translate")
        return {"ok": True}

    # ------------------------------------------------------------------ khám phá: thịnh hành, đề tài hot
    def _trends():
        from ..trends import TitleTranslator, Trends
        with st.lock:
            if "trends" not in st._cache:
                d = st.work() / ".trends"
                st._cache["titles"] = TitleTranslator(d / "tieu_de_vi.json")
                st._cache["trends"] = Trends(d)
            tr = st._cache["trends"]
            tr.proxy = st.cfg().download.proxy or ""       # đổi proxy trong Cài đặt là có tác dụng ngay
            return tr, st._cache["titles"]

    def _mark_jobs(items: list[dict]) -> list[dict]:
        """Video nào đã làm thì trang Khám phá hiện nút mở Studio thay vì làm lại."""
        w = st.work()
        out = []
        for v in items:
            d = dict(v)
            jid = f"{v.get('platform')}_{safe_name(str(v.get('id')), 40)}"
            if (w / jid / "final.mp4").exists():
                d.update(state="done", job=jid)
            elif (w / jid / "meta.json").exists():
                d.update(state="started", job=jid)
            out.append(d)
        return out

    @app.get("/api/trends/categories")
    def trend_categories():
        from ..trends import CATEGORIES
        tr, _ = _trends()
        return {"live": tr.categories(), "archive": [{"id": "arch:" + c, "name": n} for c, n, _ in CATEGORIES]}

    @app.get("/api/trends/videos")
    def trend_videos(cat: str = "picks", refresh: int = 0):
        tr, _ = _trends()
        r = tr.videos(cat, bool(refresh))
        return {**r, "items": _mark_jobs(r["items"])}

    @app.get("/api/trends/topics")
    def trend_topics(refresh: int = 0):
        from ..trends import TOPIC_SOURCES
        tr, _ = _trends()
        return {"sources": [{"id": i, "name": n, **tr.topics(i, bool(refresh))} for i, n in TOPIC_SOURCES]}

    @app.post("/api/trends/translate")
    def trend_translate(body: dict = Body(...)):
        texts = [str(t) for t in body.get("texts") or [] if str(t).strip()][:30]
        _, tt = _trends()
        try:
            found, how = tt.translate(texts, st.cfg().translate)
        except Exception as e:      # chỉ là phần phụ: không dịch được thì vẫn đọc được tiếng Trung
            log("ui", f"Không dịch được tiêu đề: {str(e)[:160]}")
            found, how = tt.known(texts), "none"
        return {"map": found, "how": how}

    @app.get("/api/trends/search")
    def trend_search(q: str):
        from ..trends import has_cjk, search_links, to_chinese
        q = q.strip()[:80]
        if not q:
            raise HTTPException(400, "Chưa nhập từ khóa")
        tr, tt = _trends()
        try:
            zh = q if has_cjk(q) else to_chinese(q, st.cfg().translate)
        except Exception as e:
            log("ui", f"Không dịch được từ khóa: {str(e)[:160]}")
            zh = ""
        return {"items": _mark_jobs(tr.search(q, zh, tt.cache)), "zh": zh, "links": search_links(zh or q)}

    @app.get("/api/trends/saved")
    def trend_saved():
        return {"items": _mark_jobs(load_json(SAVED_FILE) or [])}

    @app.put("/api/trends/saved")
    def trend_saved_put(body: dict = Body(...)):
        items = body.get("items")
        if not isinstance(items, list) or not all(isinstance(i, dict) and i.get("id") and i.get("url") for i in items):
            raise HTTPException(400, "items phải là danh sách video")
        keep = [{k: v for k, v in i.items() if k not in ("state", "job")} for i in items[:500]]
        SAVED_FILE.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"ok": True}

    # ------------------------------------------------------------------ thư viện ảnh (logo, sticker, lớp phủ)
    @app.get("/api/images")
    def images():
        items = []
        if IMAGES_DIR.exists():
            for f in sorted(IMAGES_DIR.glob("*.png"), key=lambda x: -x.stat().st_mtime):
                items.append({"name": f.name, "url": f"/api/images/{quote(f.name)}?v={int(f.stat().st_mtime)}", "path": str(f),
                              "project": f.with_suffix(".layers.json").exists()})
        return {"items": items}

    @app.put("/api/images")
    async def image_put(request: Request, name: str = "anh", overwrite: int = 0):
        """overwrite=1: trình sửa ảnh lưu đè đúng ảnh đang mở. Còn lại không đè: ảnh cũ có thể đang dùng trong video khác."""
        im = await _read_image(request)
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        stem = safe_name(name, 60) or "anh"
        dest = IMAGES_DIR / f"{stem}.png"
        n = 2
        while dest.exists() and not overwrite:
            dest = IMAGES_DIR / f"{stem}_{n}.png"
            n += 1
        if overwrite:
            dest.with_suffix(".layers.json").unlink(missing_ok=True)
        im.convert("RGBA").save(dest)
        return {"name": dest.name, "path": str(dest), "url": f"/api/images/{quote(dest.name)}?v={int(dest.stat().st_mtime)}", "width": im.width, "height": im.height}

    @app.get("/api/images/{name}")
    def image_get(name: str):
        f = _image_path(name)
        if not f.exists():
            raise HTTPException(404, "Không có ảnh này")
        return FileResponse(f, media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.delete("/api/images/{name}")
    def image_del(name: str):
        f = _image_path(name)
        f.unlink(missing_ok=True)
        f.with_suffix(".layers.json").unlink(missing_ok=True)
        return {"ok": True}

    @app.put("/api/images/{name}/project")
    async def image_project_put(name: str, request: Request):
        f = _image_path(name)
        if not f.exists():
            raise HTTPException(404, "Không có ảnh này")
        f.with_suffix(".layers.json").write_bytes(await request.body())
        return {"ok": True}

    @app.get("/api/images/{name}/project")
    def image_project_get(name: str):
        f = _image_path(name).with_suffix(".layers.json")
        if not f.exists():
            raise HTTPException(404, "Chưa có bản nhiều lớp")
        return FileResponse(f, media_type="application/json", headers={"Cache-Control": "no-cache"})

    # ------------------------------------------------------------------ tải file lên (kéo thả video, logo, nhạc)
    @app.put("/api/upload")
    async def upload(request: Request, kind: str, name: str):
        if kind not in UPLOAD_EXT:
            raise HTTPException(400, "Loại file không hợp lệ")
        src = Path(name)
        ext = src.suffix.lower()
        if ext not in UPLOAD_EXT[kind]:
            raise HTTPException(400, f"Không hỗ trợ file {ext or name}")
        folder = (st.work() / "_uploads") if kind == "video" else ROOT / "assets" / kind
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{safe_name(src.stem, 80)}{ext}"
        n = 1
        while dest.exists():
            dest = folder / f"{safe_name(src.stem, 80)}_{n}{ext}"
            n += 1
        tmp = dest.with_name(dest.name + ".part")
        try:
            with open(tmp, "wb") as f:
                async for chunk in request.stream():
                    f.write(chunk)
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
        return {"path": str(dest), "name": dest.name}

    # ------------------------------------------------------------------ voices / preview
    @app.get("/api/voices")
    def voices():
        from ..myvoice import list_voices as my_voices
        from .. import langs, voxtts
        extra = {"vox": voxtts.voices(), "vox_ready": voxtts.ready(), "langs": langs.public()}      # rẻ, đổi khi tải gói: không cache
        if "voices" not in st._cache:
            from ..voice import edge_voices_all, vieneu_voices
            res = {"vieneu": [], "edge": []}
            try:
                with tts_lock:
                    res["vieneu"] = vieneu_voices()
            except Exception as e:
                log("ui", f"Không nạp được VieNeu: {e}")
            try:
                res["edge"] = edge_voices_all()      # giọng Microsoft mọi thị trường, mỗi giọng có "lang"
            except Exception:
                pass
            if not res["vieneu"] and not res["edge"]:
                return {**res, **extra, "mine": my_voices()}
            st._cache["voices"] = res
        return {**st._cache["voices"], **extra, "mine": my_voices()}      # giọng tự thu đổi thường xuyên: không cache

    @app.post("/api/tts/preview")
    def tts_preview(body: dict = Body(...)):
        from .. import langs, voxtts
        engine = body.get("engine") or "vieneu"
        voice = (body.get("voice") or "").strip()
        lang = str(body.get("lang") or (voxtts.lang_of(voice) if engine == "vox" else "") or "vi")
        if engine == "edge" and voice.count("-") >= 2:      # giọng Microsoft: đọc câu mẫu đúng ngôn ngữ của giọng
            lang = next((c for c in langs.LANGS if langs.edge_locale(c) and voice.startswith(langs.edge_locale(c) + "-")), lang)
        text = (body.get("text") or langs.sample(lang)).strip()[:300]
        d = st.work() / "_preview"
        d.mkdir(parents=True, exist_ok=True)
        if engine == "edge":
            from ..tts import synth_many
            from ..voice import default_voice
            out = d / f"edge_{short_hash(text, voice)}.mp3"
            if not out.exists():
                failed = synth_many([(text, voice or default_voice("edge", lang, "female"), "+0%", out)], 1)
                if failed:
                    raise HTTPException(502, "Edge TTS từ chối (giới hạn tần suất) — thử lại sau")
            return FileResponse(out, media_type="audio/mpeg")
        if engine == "vox":
            if not voxtts.ready():
                raise HTTPException(409, "Chưa tải Giọng đọc nhiều thứ tiếng. Vào Cài đặt, mục Mô-đun AI miễn phí, bấm Tải.")
            v = voice or voxtts.default_voice(lang, "female")
            out = d / f"vox_{short_hash(text, v)}.wav"
            if not out.exists():
                try:
                    failed = voxtts.synth_many([(text, v, "", out)])
                except RuntimeError as e:
                    raise HTTPException(502, str(e)) from e
                if failed:
                    raise HTTPException(502, "Bộ đọc nhiều thứ tiếng chưa đọc được câu này. Xem Cài đặt > Mô-đun AI, bấm Nghe thử.")
            return FileResponse(out, media_type="audio/wav")
        out = d / f"vn_{short_hash(text, voice)}.wav"
        if not out.exists():
            from ..myvoice import is_mine, path_of
            from ..tts import _VieNeu
            if is_mine(voice):
                ref = path_of(voice)
                if ref is None:
                    raise HTTPException(404, "Mẫu giọng này đã bị xóa")
                kw = {"ref_audio": str(ref), "use_ref_codes": True}
            else:
                kw = {"voice": voice} if voice else {}
            tmp = out.with_name(out.stem + ".part.wav")
            with tts_lock:
                tts = _VieNeu.get()
                audio = tts.infer(text, **kw)
                tts.save(audio, str(tmp))
            tmp.replace(out)
        return FileResponse(out, media_type="audio/wav")

    # ------------------------------------------------------------------ queue
    @app.get("/api/queue")
    def queue():
        with st.lock:
            items = [{k: v for k, v in i.items() if k not in ("options", "payload")} for i in st.items]
            return {"items": json.loads(json.dumps(items))}

    @app.post("/api/queue")
    def add_queue(body: dict = Body(...)):
        srcs = [s.strip() for s in body.get("sources") or [] if str(s).strip()]
        if not srcs:
            raise HTTPException(400, "Chưa có link nào")
        opts = body.get("options") or {}
        if not isinstance(opts, dict):
            raise HTTPException(400, "options phải là object")
        titles = body.get("titles") if isinstance(body.get("titles"), dict) else {}
        return {"qids": [st.enqueue(s, opts, body.get("from_stage"), title=str(titles.get(s) or "")) for s in srcs]}

    @app.post("/api/queue/{qid}/cancel")
    def cancel(qid: str):
        st.cancel(qid)
        return {"ok": True}

    @app.delete("/api/queue/{qid}")
    def remove(qid: str):
        with st.lock:
            it = next((i for i in st.items if i["qid"] == qid), None)
            if it is None:
                raise HTTPException(404, "Không thấy mục")
            if it["state"] == "running":
                raise HTTPException(409, "Đang chạy — hãy hủy trước")
            st.items.remove(it)
        return {"ok": True}

    # ------------------------------------------------------------------ jobs
    @app.get("/api/jobs")
    def jobs():
        w = st.work()
        busy = st.busy_jobs()
        out = []
        if w.exists():
            for p in w.iterdir():
                if p.is_dir() and (p / "meta.json").exists():
                    try:
                        out.append(st.job_summary(p, busy))
                    except Exception:
                        continue
        out.sort(key=lambda j: j["created"], reverse=True)
        return {"jobs": out}

    @app.get("/api/jobs/{jid}")
    def job(jid: str):
        return st.job_detail(st.job_dir(jid))

    @app.put("/api/jobs/{jid}/segments")
    def put_segments(jid: str, body: dict = Body(...)):
        p = st.job_dir(jid)
        if jid in st.busy_jobs():
            raise HTTPException(409, "Video đang được xử lý — đợi xong rồi lưu")
        incoming = body.get("segments")
        if not isinstance(incoming, list):
            raise HTTPException(400, "segments phải là danh sách")
        old = {s.id: s for s in load_segments(p / "segments.json")} if (p / "segments.json").exists() else {}
        new: list[Segment] = []
        for d in incoming:
            try:
                sid = int(d["id"])
                base = old.get(sid) or Segment(id=sid, start=0, end=0, text="")
                s = Segment(**asdict(base))
                s.start = round(float(d.get("start", s.start)), 3)
                s.end = round(float(d.get("end", s.end)), 3)
                s.text = str(d.get("text", s.text))
                s.trans = str(d.get("trans", s.trans)).replace("\n", " ").strip()
                s.voice = str(d.get("voice") or "")
                s.gender = str(d.get("gender", s.gender) or "")
                s.speaker = str(d.get("speaker", s.speaker) or "")
                # tên file do chính máy chủ đặt. Không tin giá trị gửi lên vì nó được ghép vào đường dẫn để đọc và xóa file
                rec = str(d.get("rec", s.rec) or "")
                s.rec = rec if not rec or REC_NAME.fullmatch(rec) else s.rec
            except (KeyError, TypeError, ValueError) as e:
                raise HTTPException(400, f"Câu không hợp lệ: {d} ({e})")
            if s.end <= s.start:
                raise HTTPException(400, f"Câu {sid}: thời gian kết thúc phải sau bắt đầu")
            new.append(s)
        new.sort(key=lambda s: s.start)
        lang = with_overrides(st.cfg(), job_options(p)).translate.target_lang
        # ghi srt trước, segments sau -> pipeline không coi srt là "được sửa tay" và nhập lại
        write_srt(p / f"subs.{lang}.srt", [(s.start, s.end, s.trans) for s in new])
        write_srt(p / "subs.zh.srt", [(s.start, s.end, s.ocr or s.text) for s in new])
        time.sleep(0.01)
        save_segments(p / "segments.json", new)
        return {"ok": True, "n": len(new)}

    # ---- lồng tiếng từng câu: giọng thu tay, dịch lại
    def _line(p: Path, sid: int) -> tuple[list[Segment], Segment]:
        segs = load_segments(p / "segments.json") if (p / "segments.json").exists() else []
        s = next((x for x in segs if x.id == sid), None)
        if s is None:
            raise HTTPException(404, "Không có câu này")
        return segs, s

    @app.put("/api/jobs/{jid}/lines/{sid}/audio")
    async def line_audio_put(jid: str, sid: int, request: Request, clean: str = ""):
        """Giọng thu từ micro, hoặc file âm thanh tải lên, cho đúng một câu. clean=0: giữ nguyên, chỉ chuẩn hóa âm lượng."""
        p = st.job_dir(jid)
        if jid in st.busy_jobs():
            raise HTTPException(409, "Video đang được xử lý — đợi xong rồi thu")
        segs, s = _line(p, sid)
        data = await request.body()
        if not data:
            raise HTTPException(400, "Chưa có âm thanh")
        if len(data) > 100 * 1024 * 1024:
            raise HTTPException(413, "File âm thanh quá lớn")
        d = p / "rec"
        d.mkdir(exist_ok=True)
        name = f"{sid:04d}_{short_hash(str(len(data)), str(time.time()))}.wav"
        tmp = d / (name + ".upload")
        tmp.write_bytes(data)
        try:
            from ..editing import VOICE_CLEAN, VOICE_LOUDNORM, normalize_voice
            use_clean = clean != "0" if clean else bool(st.cfg().tts.get("rec_clean", True))
            ffmpeg(["-i", tmp, "-vn", "-ac", 1, "-ar", 44100, "-af", VOICE_CLEAN if use_clean else VOICE_LOUDNORM, d / name])
            if use_clean:
                wav, rate = read_wav(d / name)
                write_wav(d / name, normalize_voice(wav, rate), rate)
        except RuntimeError as e:
            raise HTTPException(400, f"Không đọc được file âm thanh này: {str(e)[-200:]}")
        finally:
            tmp.unlink(missing_ok=True)
        if s.rec:
            (d / Path(s.rec).name).unlink(missing_ok=True)
        s.rec = name
        save_segments(p / "segments.json", segs)
        return {"rec": name}

    @app.get("/api/jobs/{jid}/lines/{sid}/audio")
    def line_audio_get(jid: str, sid: int):
        p = st.job_dir(jid)
        _, s = _line(p, sid)
        f = p / "rec" / Path(s.rec).name if s.rec else None
        if not f or not f.exists():
            raise HTTPException(404, "Câu này chưa có giọng thu")
        return FileResponse(f, media_type="audio/wav", headers={"Cache-Control": "no-cache"})

    @app.delete("/api/jobs/{jid}/lines/{sid}/audio")
    def line_audio_del(jid: str, sid: int):
        p = st.job_dir(jid)
        if jid in st.busy_jobs():
            raise HTTPException(409, "Video đang được xử lý")
        segs, s = _line(p, sid)
        if s.rec:
            (p / "rec" / Path(s.rec).name).unlink(missing_ok=True)
            s.rec = ""
            save_segments(p / "segments.json", segs)
        return {"ok": True}

    @app.post("/api/jobs/{jid}/lines/{sid}/retranslate")
    def line_retranslate(jid: str, sid: int):
        """Dịch lại đúng một câu, trả về để người dùng xem. Chưa ghi vào video."""
        from ..pipeline import _ensure_translator
        from ..translate import _call_checked, _item, make_translator, max_len_for, slot_of
        p = st.job_dir(jid)
        segs, s = _line(p, sid)
        cfg = with_overrides(st.cfg(), job_options(p))
        if cfg.translate.provider == "none":
            cfg = with_overrides(cfg, {"translate": {"provider": "claude"}})
        cfg = _ensure_translator(cfg)
        meta = load_json(p / "meta.json") or {}
        i = segs.index(s)
        total = float(meta.get("duration") or 0)
        from ..pipeline import fallback_chain
        first = None
        prev = [f"{x.text} => {x.trans}" for x in segs[max(0, i - 4):i] if x.trans]
        for c in fallback_chain(cfg):      # AI đã chọn lỗi (quá tải, hết hạn mức) -> dịch offline -> Google
            try:
                tr = make_translator(c.translate, load_json(p / "context.json") if c is cfg else None)
                res = _call_checked(tr, [_item(s, max_len=max_len_for(slot_of(segs, i, total), c))], meta.get("title", ""), prev, False)
            except Exception as e:      # noqa: BLE001 — thử cách sau
                first = first or friendly_translate_error(e, c.translate.provider)
                continue
            text = (res.get(sid) or "").strip()
            if text:
                return {"text": text, "provider": c.translate.provider}
        raise HTTPException(502, first or "Không dịch được câu này")

    # ---- dựng thông minh: chuyển cảnh, khung theo nhân vật, gợi ý đoạn hay, kiểm định, gói đăng bài
    @app.get("/api/profiles")
    def profiles():
        from ..profiles import SAFE_ZONE_9X16, public
        return {"items": public(), "safe_9x16": SAFE_ZONE_9X16}

    @app.get("/api/jobs/{jid}/scenes")
    def job_scenes(jid: str):
        from .. import vision
        p = st.job_dir(jid)
        return {"times": vision.scenes(p)}

    @app.get("/api/jobs/{jid}/reframe")
    def job_reframe(jid: str, aspect: str = "9:16"):
        """Đường đi của khung cắt để xem trước trên video gốc. Lần đầu mất vài giây để dò mặt, sau đó dùng lại."""
        from .. import vision
        from ..render import ASPECTS
        p = st.job_dir(jid)
        if aspect not in ASPECTS:
            raise HTTPException(400, "Khung hình không hợp lệ")
        if not vision.available():
            raise HTTPException(400, "Thiếu thư viện OpenCV hoặc model dò khuôn mặt")
        meta = load_json(p / "meta.json") or {}
        e = with_overrides(st.cfg(), job_options(p)).edit
        w, h = ASPECTS[aspect]
        # giống hệt lúc dựng, kể cả lật và phóng: trình phát cũng áp dụng hai bước đó khi xem trước
        plan = vision.reframe_plan(vision.scan_faces(p, meta), vision.scenes(p), float(meta.get("duration") or 0),
                                   int(meta["width"]), int(meta["height"]), w, h, pins=e.get("reframe_pins"), flip=bool(e.flip), zoom=float(e.zoom or 1.0))
        return {"plan": plan}

    @app.post("/api/jobs/{jid}/highlights")
    def job_highlights(jid: str, body: dict = Body(default={})):
        """Gợi ý các đoạn đáng cắt thành clip. Chỉ tính toán, chưa cắt gì."""
        from .. import highlights, vision
        p = st.job_dir(jid)
        if not (p / "segments.json").exists():
            raise HTTPException(400, "Video chưa qua bước nhận dạng lời")
        try:
            lo, hi = max(5.0, float(body.get("min") or 20)), float(body.get("max") or 60)
            count = min(12, max(1, int(body.get("count") or 6)))
        except (TypeError, ValueError):
            raise HTTPException(400, "Độ dài không hợp lệ")
        if hi <= lo:
            raise HTTPException(400, "Độ dài không hợp lệ")
        meta = load_json(p / "meta.json") or {}
        dur = float(meta.get("duration") or 0)
        wav = p / "audio.wav"
        loud = highlights.loudness_curve(wav) if wav.exists() else None
        e = with_overrides(st.cfg(), job_options(p)).edit
        from ..editing import normalize_cuts
        items = highlights.suggest(load_segments(p / "segments.json"), dur, loud, vision.scenes(p), cuts=normalize_cuts(e.get("cuts"), dur),
                                   min_len=lo, max_len=hi, count=count)
        return {"items": items}

    @app.get("/api/jobs/{jid}/qc")
    def job_qc(jid: str):
        return {"qc": qc_cached(st.job_dir(jid))}

    @app.post("/api/jobs/{jid}/qc")
    def job_qc_run(jid: str):
        from .. import qc
        p = st.job_dir(jid)
        if jid in st.busy_jobs():
            raise HTTPException(409, "Video đang được xử lý, đợi xong rồi kiểm định")
        try:
            return {"qc": qc.run(p, with_overrides(st.cfg(), job_options(p)))}
        except FileNotFoundError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/jobs/{jid}/bundle")
    def job_bundle(jid: str, body: dict = Body(default={})):
        from .. import bundle
        p = st.job_dir(jid)
        if jid in st.busy_jobs():
            raise HTTPException(409, "Video đang được xử lý, đợi xong rồi tạo gói")
        try:
            res = bundle.make(p)
        except FileNotFoundError as e:
            raise HTTPException(400, str(e))
        except PermissionError:
            raise HTTPException(409, "Có file trong gói đang được mở (trình phát video chẳng hạn). Đóng file đó rồi tạo lại.")
        if body.get("open"):
            if os.name == "nt":
                os.startfile(res["folder"])  # noqa: S606 — mở thư mục local cho người dùng
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(res["folder"])])
        return res

    @app.post("/api/jobs/{jid}/silence")
    def silence(jid: str, body: dict = Body(default={})):
        """Gợi ý các đoạn không có lời để cắt. Chỉ tính toán, chưa cắt gì."""
        from ..editing import silence_gaps
        p = st.job_dir(jid)
        meta = load_json(p / "meta.json") or {}
        segs = load_segments(p / "segments.json") if (p / "segments.json").exists() else []
        try:
            gap = max(0.3, float(body.get("min_gap") or 0.8))
        except (TypeError, ValueError):
            gap = 0.8
        return {"gaps": silence_gaps(segs, float(meta.get("duration") or 0), min_gap=gap)}

    @app.post("/api/jobs/{jid}/speakers/detect")
    def detect_speakers(jid: str):
        """Nghe lại xem có mấy người nói. Giữ nguyên bản dịch (chỉ gắn nhãn, không tách câu)."""
        from .. import speakers
        p = st.job_dir(jid)
        if jid in st.busy_jobs():
            raise HTTPException(409, "Video đang được xử lý")
        if not speakers.available():
            raise HTTPException(400, "Thiếu thư viện nhận diện: pip install sherpa-onnx")
        if not (p / "segments.json").exists():
            raise HTTPException(400, "Video chưa qua bước nhận dạng")
        segs = load_segments(p / "segments.json")
        wav = next((f for f in (p / "vocals.wav", p / "asr.wav", p / "audio.wav") if f.exists()), None)
        if wav is None:
            raise HTTPException(400, "Không thấy file âm thanh của video")
        old_labels = {s.id: s.speaker for s in segs}
        segs, info = speakers.diarize(segs, None, wav, split=False)
        speakers.save(p, speakers.carry_over(info, segs, old_labels, speakers.load(p)))
        eff = with_overrides(st.cfg(), job_options(p))
        hint = (load_json(p / "context.json") or {}).get("narrator_gender", "")
        speakers.assign_voices(p, segs, wav, eff, hint=hint)     # hiện ngay nam/nữ và giọng, không đợi cập nhật video
        info = speakers.load(p)
        save_segments(p / "segments.json", segs)
        return {"speakers": info, "segments": [asdict(s) for s in segs]}

    @app.put("/api/jobs/{jid}/speakers")
    def put_speakers(jid: str, body: dict = Body(...)):
        """Đổi tên, đổi giọng từng người nói."""
        from .. import speakers
        p = st.job_dir(jid)
        info = speakers.load(p) or {"speakers": []}
        incoming = {str(x.get("id")): x for x in body.get("speakers") or [] if isinstance(x, dict)}
        for sp in info["speakers"]:
            x = incoming.get(sp["id"])
            if x:
                sp["name"] = str(x.get("name") or sp["name"]).strip()[:40] or sp["name"]
                sp["voice"] = str(x.get("voice") or "")
        speakers.save(p, info)
        return info

    @app.put("/api/jobs/{jid}/options")
    def put_options(jid: str, body: dict = Body(...)):
        p = st.job_dir(jid)
        opts = body.get("options")
        if not isinstance(opts, dict):
            raise HTTPException(400, "options phải là object")
        try:
            eff = with_overrides(st.cfg(), opts)
            from ..editing import normalize_cuts
            normalize_cuts(eff.edit.get("cuts"), float((load_json(p / "meta.json") or {}).get("duration") or 0))
        except Exception as e:
            raise HTTPException(400, f"Tùy chọn không hợp lệ: {e}")
        save_job_options(p, opts)
        return {"ok": True}

    @app.post("/api/jobs/{jid}/run")
    def run(jid: str, body: dict = Body(default={})):
        p = st.job_dir(jid)
        if jid in st.busy_jobs():
            raise HTTPException(409, "Video này đang trong hàng đợi")
        meta = load_json(p / "meta.json") or {}
        opts = body.get("options") or None
        if opts is not None and not isinstance(opts, dict):
            raise HTTPException(400, "options phải là object")
        qid = st.enqueue(str(p), opts, body.get("from_stage") or None, title=meta.get("title", ""), job=jid)
        return {"qid": qid}

    @app.post("/api/jobs/{jid}/export")
    def export(jid: str, body: dict = Body(default={})):
        """Xuất thêm các khung hình khác, hoặc từng đoạn thành clip riêng (giọng lồng và dải đã xóa sub được dùng lại)."""
        p = st.job_dir(jid)
        if jid in st.busy_jobs():
            raise HTTPException(409, "Video này đang trong hàng đợi")
        targets = [t for t in body.get("targets") or [] if t in TARGETS]
        from ..profiles import PROFILES
        wanted = [x for x in body.get("profiles") or [] if x in PROFILES]
        clip_profile = body.get("clip_profile") if body.get("clip_profile") in PROFILES else ""
        meta = load_json(p / "meta.json") or {}
        dur = float(meta.get("duration") or 0)
        clips = []
        for c in body.get("clips") or []:
            try:
                a, b = float(c[0]), float(c[1])
            except (TypeError, ValueError, IndexError):
                raise HTTPException(400, "Đoạn cần xuất không hợp lệ")
            a, b = max(0.0, a), min(b, dur) if dur else b
            if b - a < 0.5:
                raise HTTPException(400, "Đoạn cần xuất phải dài ít nhất 0,5 giây")
            clips.append([round(a, 3), round(b, 3)])
        qid = st.enqueue(str(p), None, None, title=meta.get("title", ""), job=jid, targets=targets, clips=clips, profiles=wanted, clip_profile=clip_profile)
        return {"qid": qid}

    # ---- ghép nhiều video
    def _merges():
        from ..montage import MergeStore
        return MergeStore(st.work() / ".merges")

    @app.get("/api/merge/options")
    def merge_options():
        from ..montage import TRANSITIONS
        return {"transitions": TRANSITIONS}

    @app.post("/api/merge")
    def merge_start(body: dict = Body(...)):
        from ..montage import TRANSITIONS, inspect
        items = body.get("items")
        if not isinstance(items, list) or not items:
            raise HTTPException(400, "Chưa có video nào để ghép")
        if (body.get("transition") or "") not in TRANSITIONS:
            raise HTTPException(400, "Kiểu chuyển cảnh không hợp lệ")
        for it in items:
            try:
                inspect(it)     # báo lỗi ngay thay vì xếp hàng rồi mới hỏng
            except ValueError as e:
                raise HTTPException(400, str(e))
        name = str(body.get("name") or "Video ghép").strip()[:80]
        return {"qid": st.enqueue(name, None, None, title=f"Ghép: {name}", kind="merge", payload={**body, "name": name})}

    @app.get("/api/merges")
    def merges():
        return {"items": _merges().items()}

    @app.get("/api/merges/{mid}/video")
    def merge_video(mid: str):
        rec = _merges().get(mid)
        if not rec:
            raise HTTPException(404, "Không có bản ghép này")
        return FileResponse(rec["path"], media_type="video/mp4", filename=Path(rec["path"]).name)

    @app.get("/api/merges/{mid}/thumb")
    def merge_thumb(mid: str):
        f = st.work() / ".merges" / f"{safe_name(mid, 20)}.jpg"
        if not f.exists():
            raise HTTPException(404, "Chưa có ảnh")
        return FileResponse(f, media_type="image/jpeg")

    @app.delete("/api/merges/{mid}")
    def merge_delete(mid: str):
        try:
            _merges().remove(mid)
        except PermissionError:
            raise HTTPException(409, "File đang được mở. Đóng trình xem hoặc đợi một lát rồi xóa lại.")
        return {"ok": True}

    @app.get("/api/media/info")
    def media_info(path: str):
        """Thông tin file vừa tải lên hoặc video trong thư viện."""
        from ..montage import inspect
        try:
            c = inspect({"path": path})
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"name": c["path"].name, "image": c["image"], "duration": c["dur"], "width": c["width"], "height": c["height"], "audio": c["audio"]}

    @app.get("/api/jobs/{jid}/file-path")
    def job_file_path(jid: str, name: str):
        if name not in ("final.mp4", "source.mp4"):
            raise HTTPException(400, "Không có file này")
        f = st.job_dir(jid) / name
        if not f.exists():
            raise HTTPException(404, "Video này chưa có file đó")
        return {"path": str(f.resolve())}

    # ---- sóng âm cho timeline
    @app.get("/api/jobs/{jid}/peaks/{name}")
    def peaks(jid: str, name: str):
        p = st.job_dir(jid)
        if name not in ("audio", "dub"):
            raise HTTPException(404, "Không có track này")
        wav = p / f"{name}.wav"
        if not wav.exists():
            return {"rate": 100, "peaks": []}     # chưa lồng tiếng: timeline hiện dòng "Chưa có giọng lồng"
        cache, stamp = p / f".peaks_{name}.json", f"2:{wav.stat().st_mtime}"
        old = load_json(cache)
        if old and old.get("stamp") == stamp:
            return {"rate": old["rate"], "peaks": old["peaks"]}
        import numpy as np

        data, sr = read_wav(wav)
        if data.ndim > 1:
            data = data.mean(axis=1)
        dur = len(data) / sr
        rate = 100 if dur < 900 else 25 if dur < 3600 else 10      # số điểm mỗi giây
        hop = max(1, sr // rate)
        n = len(data) // hop
        vals = np.sqrt((data[:n * hop].reshape(n, hop) ** 2).mean(axis=1)) if n else np.zeros(0)
        top = float(np.percentile(vals, 99.5)) if n else 0.0
        vals = np.clip(vals / top, 0, 1) if top > 1e-4 else vals * 0
        out = (vals * 255).astype(np.uint8).tolist()
        cache.write_text(json.dumps({"stamp": stamp, "rate": rate, "peaks": out}), encoding="utf-8")
        return {"rate": rate, "peaks": out}

    # ---- ảnh bìa
    def _hardsub_box(p: Path):
        from ..hardsub import hardsub_mode
        eff = with_overrides(st.cfg(), job_options(p))
        mode = hardsub_mode(eff.edit.blur_hardsub)
        if mode == "on":
            return [float(v) for v in eff.edit.hardsub_box]
        return (load_json(p / "hardsub.json") or {}).get("box") if mode == "auto" else None

    @app.get("/api/jobs/{jid}/cover/candidates")
    def cover_candidates(jid: str):
        from ..cover import candidates
        p = st.job_dir(jid)
        items = candidates(p, load_json(p / "meta.json") or {})
        return {"items": items, "current": load_json(p / "cover.json")}

    @app.post("/api/jobs/{jid}/cover")
    def make_cover(jid: str, body: dict = Body(...)):
        from ..cover import make_cover as mk
        p = st.job_dir(jid)
        meta = load_json(p / "meta.json") or {}
        try:
            mk(p, meta, float(body.get("t") or 0), str(body.get("title") or ""), str(body.get("style") or ""),
               str(body.get("aspect") or ""), _hardsub_box(p), color=str(body.get("color") or "#FFB224"))
        except Exception as e:
            raise HTTPException(500, f"Không tạo được ảnh bìa: {e}")
        (p / "cover_layers.json").unlink(missing_ok=True)    # bản thiết kế cũ không còn khớp với ảnh bìa mới
        output = load_json(p / "output.json") or {}
        if output.get("video") and Path(output["video"]).exists():      # cập nhật luôn bản đi kèm video đã xuất
            shutil.copy2(p / "cover.jpg", Path(output["video"]).with_suffix(".jpg"))
        return {"url": f"/api/jobs/{jid}/cover.jpg?v={int(time.time() * 1000)}"}

    @app.get("/api/jobs/{jid}/cover.jpg")
    def cover_file(jid: str):
        p = st.job_dir(jid)
        if not (p / "cover.jpg").exists():
            raise HTTPException(404, "Chưa có ảnh bìa")
        return FileResponse(p / "cover.jpg", media_type="image/jpeg", headers={"Cache-Control": "no-cache"})

    async def _read_image(request: Request):
        """Đọc ảnh từ thân yêu cầu; chỉ nhận ảnh thật, chống ghi file lạ vào máy."""
        from PIL import Image, UnidentifiedImageError
        data = await request.body()
        if not data or len(data) > MAX_IMAGE:
            raise HTTPException(413 if data else 400, "Ảnh rỗng hoặc quá lớn (tối đa 40 MB)")
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
        except (UnidentifiedImageError, OSError) as e:
            raise HTTPException(400, f"Không đọc được ảnh: {e}")
        return im

    def _image_path(name: str) -> Path:
        n = Path(name).name
        if n != name or not n.lower().endswith(".png"):
            raise HTTPException(400, "Tên ảnh không hợp lệ")
        return IMAGES_DIR / n

    @app.put("/api/jobs/{jid}/cover/upload")
    async def cover_upload(jid: str, request: Request):
        """Ảnh bìa đã sửa trong trình sửa ảnh."""
        p = st.job_dir(jid)
        im = await _read_image(request)
        im.convert("RGB").save(p / "cover.jpg", quality=92)
        old = load_json(p / "cover.json") or {}
        (p / "cover.json").write_text(json.dumps({**old, "edited": True}, ensure_ascii=False), encoding="utf-8")
        output = load_json(p / "output.json") or {}
        if output.get("video") and Path(output["video"]).exists():
            shutil.copy2(p / "cover.jpg", Path(output["video"]).with_suffix(".jpg"))
        return {"url": f"/api/jobs/{jid}/cover.jpg?v={int(time.time() * 1000)}", "width": im.width, "height": im.height}

    @app.put("/api/jobs/{jid}/cover/project")
    async def cover_project_put(jid: str, request: Request):
        p = st.job_dir(jid)
        (p / "cover_layers.json").write_bytes(await request.body())
        return {"ok": True}

    @app.get("/api/jobs/{jid}/cover/project")
    def cover_project_get(jid: str):
        f = st.job_dir(jid) / "cover_layers.json"
        if not f.exists():
            raise HTTPException(404, "Chưa có bản nhiều lớp")
        return FileResponse(f, media_type="application/json", headers={"Cache-Control": "no-cache"})

    @app.post("/api/jobs/{jid}/detect-hardsub")
    def detect_hardsub(jid: str):
        from ..hardsub import available, detect
        if not available():
            raise HTTPException(400, "Chưa cài OCR: pip install rapidocr")
        p = st.job_dir(jid)
        meta = load_json(p / "meta.json") or {}
        return detect(p, float(meta.get("duration") or 0), force=True)

    @app.get("/api/jobs/{jid}/frame.jpg")
    def frame(jid: str, t: float = 0.0, clean: int = 0):
        p = st.job_dir(jid)
        d = p / ".frames"
        d.mkdir(exist_ok=True)
        if clean and _hardsub_box(p):     # khung để sửa ảnh: xóa luôn sub gốc
            out = d / f"ui_{t:.2f}_clean.jpg"
            if not out.exists():
                import cv2
                from ..clean import clean_frame
                raw = d / f"ui_{t:.2f}_raw.jpg"
                ffmpeg(["-ss", f"{max(0.0, t):.3f}", "-i", p / "source.mp4", "-frames:v", "1", "-strict", "unofficial", "-q:v", "2", raw])
                im = cv2.imdecode(np.fromfile(str(raw), dtype=np.uint8), cv2.IMREAD_COLOR)
                if im is None:
                    raise HTTPException(500, "Không lấy được khung hình")
                ok, buf = cv2.imencode(".jpg", clean_frame(im, _hardsub_box(p)), [cv2.IMWRITE_JPEG_QUALITY, 94])
                if not ok:
                    raise HTTPException(500, "Không lưu được khung hình")
                out.write_bytes(buf.tobytes())
            return FileResponse(out, media_type="image/jpeg")
        files = sorted(d.glob("ui_*.jpg"), key=lambda f: f.stat().st_mtime)
        for f in files[:-60]:
            f.unlink(missing_ok=True)
        out = d / f"ui_{t:.2f}.jpg"
        if not out.exists():
            ffmpeg(["-ss", f"{max(0.0, t):.3f}", "-i", p / "source.mp4", "-frames:v", "1",
                    "-vf", "scale='min(1080,iw)':-2", "-strict", "unofficial", "-q:v", "3", out])
        return FileResponse(out, media_type="image/jpeg")

    @app.get("/api/jobs/{jid}/thumb.jpg")
    def thumb(jid: str):
        p = st.job_dir(jid)
        out = p / "thumb.jpg"
        if not out.exists():
            if not (p / "source.mp4").exists():
                raise HTTPException(404, "Chưa có video")
            meta = load_json(p / "meta.json") or {}
            t = min(1.5, float(meta.get("duration") or 3) / 3)
            ffmpeg(["-ss", f"{t:.2f}", "-i", p / "source.mp4", "-frames:v", "1", "-vf", "scale=480:-2", "-strict", "unofficial", "-q:v", "4", out])
        return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    from .content_api import mount as mount_content
    mount_content(app, st)      # Đọc văn bản, Kể chuyện
    from .fixes_api import mount as mount_fixes
    mount_fixes(app, st)        # Cách khắc phục: cookie, sửa mô hình, cập nhật bộ tải video, thử lại
    from .localai_api import mount as mount_localai
    mount_localai(app, st)      # Mô-đun AI miễn phí: dịch, vẽ ảnh ngay trên máy

    # ------------------------------------------------------------------ trình dựng tự do (xem editor.py)
    editor_live: dict[str, float] = {}      # video đang mở trong cửa sổ trình dựng nào: mở hai cửa sổ cùng một dự án thì bản lưu sau đè bản trước

    @app.get("/api/editor/status")
    def editor_status():
        return {"available": editor.available()}

    @app.post("/api/editor/open")
    def editor_open(request: Request, body: dict = Body(default={})):
        """Mở cửa sổ trình dựng ở đúng máy này. Giao diện không tự mở được: cửa sổ ứng dụng mở link mới thành cửa sổ trình duyệt có thanh địa chỉ."""
        if not editor.available():
            raise HTTPException(503, "Bản cài này chưa có trình dựng")
        jid = str(body.get("job") or "")
        sid = str(body.get("story") or "")
        if sid:
            try:
                story_store().get(sid)
            except KeyError:
                raise HTTPException(404, "Không có câu chuyện này") from None
            jid = ""
        live_key = f"story:{sid}" if sid else jid      # cửa sổ trình dựng báo về bằng khóa này (xem heartbeat)
        if jid:
            st.job_dir(jid)
        if live_key and time.time() - editor_live.get(live_key, 0) < EDITOR_LIVE_SECONDS:
            return {"already_open": True}
        from .. import appwin
        url = editor.window_url(request.headers.get("host"), jid, bool(body.get("fresh")), story=sid)
        appwin.open_window(url, maximized=True)
        if live_key:
            # tính là đang mở trong 20 giây tới: bấm hai lần liên tiếp thì cửa sổ đầu chưa kịp báo về. Không giữ lâu hơn: đóng ngay ở bước
            # chọn thư mục thì cửa sổ chưa bao giờ báo về, giữ lâu sẽ báo nhầm là đang mở
            editor_live[live_key] = time.time() - EDITOR_LIVE_SECONDS + 20
        return {"url": url}

    @app.post("/api/editor/heartbeat")
    def editor_heartbeat(body: dict = Body(default={})):
        """Cửa sổ trình dựng còn mở. Gọi /api/ là đủ để Studio566 không tự tắt (xem middleware), job chỉ để chặn mở trùng."""
        jid = str(body.get("job") or "")
        if jid:
            if body.get("closing"):
                editor_live.pop(jid, None)
            else:
                editor_live[jid] = time.time()
        return {"ok": True}

    @app.get("/api/editor/jobs/{jid}")
    def editor_job(jid: str):
        """ready: dựng xong bản nền. preparing: đang dựng hoặc video đang có việc khác. missing: chưa có, hãy gọi prepare. failed: lần trước lỗi hoặc bị hủy."""
        p = st.job_dir(jid)
        with st.lock:
            mine = [dict(i) for i in st.items if i["job"] == jid]      # mới nhất trước
        fresh = editor.base_fresh(p, with_overrides(st.cfg(), job_options(p)))
        active = next((i for i in mine if i["state"] in ("queued", "running")), None)
        # lượt dựng bản nền đã xong phần bản nền, chỉ còn kiểm định bản chính: không bắt trình dựng chờ thêm
        if active and not (active.get("editor_base") and fresh):
            return {"state": "preparing", "stage": active["stage"], "progress": active["progress"], "message": active["message"]}
        if fresh:
            try:
                return {"state": "ready", "project": editor.project_info(p)}
            except RuntimeError as e:      # ffprobe không đọc được bản nền
                return {"state": "failed", "message": f"Video nền hỏng, hãy dựng lại: {str(e)[:160]}"}
        # chỉ báo lỗi khi lượt gần nhất của video này là lượt dựng bản nền và nó hỏng: lỗi cũ hơn đã có lượt khác chạy xong sau đó
        last = mine[0] if mine else None
        if last and last.get("editor_base") and last["state"] in ("error", "cancelled"):
            return {"state": "failed", "message": last.get("message") or "Không dựng được video nền"}
        return {"state": "missing"}

    @app.post("/api/editor/jobs/{jid}/prepare")
    def editor_prepare(jid: str):
        p = st.job_dir(jid)
        if jid in st.busy_jobs():
            return {"state": "preparing"}
        if editor.base_fresh(p, with_overrides(st.cfg(), job_options(p))):
            return {"state": "ready"}      # đã có, không dựng lại (bấm Thử lại khi lỗi nằm ở bước nạp vào trình dựng)
        meta = load_json(p / "meta.json") or {}
        return {"state": "preparing", "qid": st.enqueue(str(p), None, None, title=meta.get("title", ""), job=jid, editor_base=True)}

    @app.get("/api/editor/jobs/{jid}/video/{name}")
    def editor_video(jid: str, name: str):
        f = st.job_dir(jid) / editor.BASE
        if not f.exists():
            raise HTTPException(404, "Chưa có video nền")
        return FileResponse(f, media_type="video/mp4", headers={"Cache-Control": "no-store"})

    def story_store():
        from ..story import StoryStore
        return StoryStore(st.work() / ".stories")

    @app.put("/api/editor/result")
    async def editor_result(request: Request, job: str = "", name: str = "", story: str = ""):
        """Nhận video dựng xong từ trình dựng. Đọc từng phần: video có thể vài GB. Viết ra file tạm trước để gửi hỏng giữa chừng không để lại file dở."""
        ext = Path(name).suffix.lower()
        if ext not in editor.RESULT_EXT:
            raise HTTPException(400, "Chỉ nhận video MP4, WebM, MOV hoặc MKV")
        p = st.job_dir(job) if job and not story else None
        if p is not None and not (p / "meta.json").exists():
            raise HTTPException(404, "Không thấy video gốc của dự án này trong Studio566")
        sstore = story_store() if story else None
        if sstore is not None:
            try:
                s0 = sstore.get(story)
            except KeyError:
                raise HTTPException(404, "Không thấy câu chuyện của dự án này trong Studio566") from None
            name = f"kechuyen_{safe_name(s0.get('title') or story, 60).strip(' .')}_{story[1:6]}_dung{ext}"
        out_dir = Path(st.cfg().output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = editor.reserve_result(out_dir, p, name, ext)
        tmp = dst.with_name(f"{dst.name}.{uuid.uuid4().hex[:8]}.part")
        size = 0
        done = False
        try:
            with open(tmp, "wb") as f:
                async for chunk in request.stream():
                    f.write(chunk)
                    size += len(chunk)
            if size == 0:
                raise HTTPException(400, "File gửi về bị rỗng")
            # luồng của AnyIO: việc ở đây không chen vào dòng trạng thái của video đang chạy trong hàng đợi (xem Studio._on_event)
            await run_in_threadpool(editor.finish_result, tmp, dst)
            done = True
        finally:
            tmp.unlink(missing_ok=True)
            if not done:
                dst.unlink(missing_ok=True)      # bỏ chỗ đã giữ
        if p is not None:
            editor.record_result(p, dst)
        if sstore is not None:
            item = {"name": dst.name, "path": str(dst.resolve()), "at": round(time.time(), 3), "size": size}

            def remember(s_):
                s_["edited"] = [item] + [x for x in s_.get("edited") or [] if x.get("path") != item["path"]][:19]
            try:
                sstore.update(story, remember)
            except KeyError:
                pass      # câu chuyện vừa bị xóa: video vẫn nằm trong output
        return {"path": str(dst.resolve()), "name": dst.name, "size": size}

    @app.get("/api/jobs/{jid}/edited")
    def edited_list(jid: str):
        return {"items": editor.edited_items(st.job_dir(jid))}

    def _edited(jid: str, name: str) -> Path:
        f = editor.edited_by_name(st.job_dir(jid), name)
        if f is None:
            raise HTTPException(404, "Không có bản dựng này")
        return f

    @app.post("/api/jobs/{jid}/edited/{name}/qc")
    def edited_qc(jid: str, name: str):
        """Kiểm định bản gửi về từ trình dựng. Không so với render.json: bản này đã được dựng lại nên độ dài và phụ đề có thể khác bản chính."""
        from .. import qc
        f = _edited(jid, name)
        return {"qc": qc.check_file(f, {"dub": (st.job_dir(jid) / "dub.wav").exists()})}

    @app.get("/api/jobs/{jid}/edited/{name}")
    def edited_file(jid: str, name: str):
        f = _edited(jid, name)
        return FileResponse(f, media_type={".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}.get(f.suffix.lower(), "video/mp4"),
                            headers={"Cache-Control": "no-cache"})

    @app.post("/api/jobs/{jid}/edited/{name}/reveal")
    def edited_reveal(jid: str, name: str):
        f = _edited(jid, name)
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(f)])      # noqa: S603, S607
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(f)])
        return {"ok": True}

    @app.get("/api/jobs/{jid}/media/{name}")
    def media(jid: str, name: str):
        p = st.job_dir(jid)
        if (name not in MEDIA and not MEDIA_RE.match(name)) or not (p / name).exists():
            raise HTTPException(404, "Không có file")
        mt = "video/mp4" if name.endswith(".mp4") else "audio/wav"
        return FileResponse(p / name, media_type=mt, headers={"Cache-Control": "no-cache"})

    @app.get("/api/jobs/{jid}/clip/{sid}")
    def clip(jid: str, sid: int):
        """Đúng đoạn giọng lồng của câu sid như trong video thành phẩm (cắt từ dub.wav)."""
        p = st.job_dir(jid)
        segs = {s.id: s for s in load_segments(p / "segments.json")}
        s = segs.get(sid)
        if s is None or s.dub_start is None or not (p / "dub.wav").exists():
            raise HTTPException(404, "Câu này chưa được lồng tiếng")
        key = ("dub", jid, (p / "dub.wav").stat().st_mtime)
        if st._cache.get("dub_key") != key:
            st._cache["dub"], st._cache["dub_key"] = read_wav(p / "dub.wav"), key
        data, sr = st._cache["dub"]
        a, b = int(s.dub_start * sr), int((s.dub_end or s.dub_start) * sr)
        buf = io.BytesIO()
        write_wav(buf, data[a:b], sr)
        return Response(buf.getvalue(), media_type="audio/wav", headers={"Cache-Control": "no-cache"})

    @app.delete("/api/jobs/{jid}")
    def delete_job(jid: str):
        p = st.job_dir(jid)
        if jid in st.busy_jobs():
            raise HTTPException(409, "Video đang được xử lý")
        shutil.rmtree(p, ignore_errors=True)
        return {"ok": True}

    @app.post("/api/jobs/{jid}/reveal")
    def reveal(jid: str):
        p = st.job_dir(jid)
        out = (load_json(p / "output.json") or {}).get("video")
        if os.name == "nt":
            if out and Path(out).exists():
                subprocess.Popen(["explorer", "/select,", str(Path(out))])
            else:
                os.startfile(str(p))  # noqa: S606 — mở thư mục local cho người dùng
        elif sys.platform == "darwin":
            if out and Path(out).exists():
                subprocess.Popen(["open", "-R", str(Path(out))])
            else:
                subprocess.Popen(["open", str(p)])
        return {"ok": True}

    return app
