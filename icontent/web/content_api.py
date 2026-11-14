"""API cho phần làm content: Đọc văn bản (giọng đọc từ chữ) và Kể chuyện (video từ ảnh, nhân vật nhất quán bằng Gemini).

Việc nhẹ và cần trả lời nhanh (vẽ một ảnh, đọc thử một cảnh, AI viết kịch bản, đọc văn bản) chạy ở luồng nền riêng có tiến độ (Tasks),
không phải xếp hàng sau một video đang dựng mười phút. Dựng video kể chuyện thì nặng nên vào hàng đợi chung như mọi video khác.
Luồng nền đặt tên bắt đầu bằng "ui-" để không chen vào dòng trạng thái của video đang chạy trong hàng đợi (Studio._on_event).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import Body, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .. import story as story_mod
from ..util import ROOT, find_ffmpeg, safe_name

MAX_UPLOAD = 25 * 1024 * 1024
MAX_SPEECH_CHARS = 30000


class Tasks:
    """Việc chạy nền: {id: {state, progress, message, result, error}}. Giữ 200 việc gần nhất."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.lock = threading.Lock()

    def start(self, kind: str, fn, label: str = "") -> str:
        tid = uuid.uuid4().hex[:10]
        it = {"id": tid, "kind": kind, "label": label, "state": "running", "progress": None, "message": "", "result": None, "error": None,
              "started": time.time()}
        with self.lock:
            self.items[tid] = it
            for old in sorted(self.items, key=lambda k: self.items[k]["started"])[:-200]:
                self.items.pop(old, None)

        def report(frac=None, msg=None):
            with self.lock:
                if frac is not None:
                    it["progress"] = max(0.0, min(1.0, float(frac)))
                if msg is not None:
                    it["message"] = str(msg)[:200]

        def run():
            try:
                res = fn(report)
                with self.lock:
                    it.update(state="done", result=res, progress=1.0)
            except Exception as e:      # mọi lỗi phải về được giao diện, không chết lặng trong luồng nền
                with self.lock:
                    it.update(state="error", error=str(e)[:600] or type(e).__name__)
        threading.Thread(target=run, daemon=True, name=f"ui-task-{kind}").start()
        return tid

    def get(self, tid: str) -> dict:
        with self.lock:
            it = self.items.get(tid)
            if it is None:
                raise KeyError(tid)
            return json.loads(json.dumps(it, default=str))


def _not_found(e: Exception) -> HTTPException:
    return HTTPException(404, (e.args[0] if e.args else "") or "Không tìm thấy")


async def _read_body(request: Request, limit: int = MAX_UPLOAD) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > limit:
            raise HTTPException(413, "File quá lớn (tối đa 25 MB)")
    if not data:
        raise HTTPException(400, "File rỗng")
    return bytes(data)


async def _image_job(fn, *args):
    """Giải mã, xoay, thu nhỏ, lưu ảnh tốn vài giây với ảnh điện thoại: chạy ở luồng phụ, máy chủ vẫn trả lời các yêu cầu khác."""
    try:
        return await run_in_threadpool(fn, *args)
    except KeyError as e:
        raise _not_found(e) from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


def mount(app, st) -> None:
    """Gắn các API vào app. st là Studio (cấu hình, hàng đợi)."""
    tasks = Tasks()
    app.state.tasks = tasks
    drawing: set[str] = set()      # "câu chuyện:cảnh" đang được vẽ: bấm lần nữa không gọi API trả phí lần nữa
    drawing_lock = threading.Lock()

    def store() -> story_mod.StoryStore:
        return story_mod.StoryStore(st.work() / ".stories")

    def claim(keys: list[str]) -> None:
        with drawing_lock:
            busy = [k for k in keys if k in drawing]
            if busy:
                raise HTTPException(409, "Ảnh này đang được vẽ, đợi xong rồi hãy vẽ lại")
            drawing.update(keys)

    def release(keys: list[str]) -> None:
        with drawing_lock:
            drawing.difference_update(keys)

    def speech_dir() -> Path:
        return Path(st.cfg().output_dir) / "giong_doc"

    @app.get("/api/tasks/{tid}")
    def task_get(tid: str):
        try:
            return tasks.get(tid)
        except KeyError:
            raise HTTPException(404, "Không có tác vụ này") from None

    # ------------------------------------------------------------------ Đọc văn bản
    @app.post("/api/speech")
    def speech_make(body: dict = Body(...)):
        from ..speech import synthesize
        text = str(body.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "Chưa có chữ nào để đọc")
        if len(text) > MAX_SPEECH_CHARS:
            raise HTTPException(400, f"Dài quá: tối đa {MAX_SPEECH_CHARS:,} ký tự một lần".replace(",", "."))
        engine = body.get("engine") if body.get("engine") in ("vieneu", "edge", "vox") else "vieneu"
        voice = str(body.get("voice") or "")[:80]
        try:
            speed = min(2.0, max(0.5, float(body.get("speed") or 1.0)))
        except (TypeError, ValueError):
            speed = 1.0
        name = safe_name(str(body.get("name") or "") or text[:40], 60).strip(" .") or "giong_doc"      # tên kiểu ../.. không thành file ẩn
        folder = speech_dir()

        def job(report):
            folder.mkdir(parents=True, exist_ok=True)
            work = st.work() / ".speech"
            work.mkdir(parents=True, exist_ok=True)
            wav = work / f"{uuid.uuid4().hex[:10]}.wav"
            try:
                return finish(wav, synthesize(text, wav, engine=engine, voice=voice, speed=speed, cache=work / "cache",
                                              on_step=lambda n, k: report(n / k * 0.95, f"Đã đọc {n}/{k} đoạn")), report)
            finally:      # file làm việc vài trăm MB: không để lại dù lỗi ở bước nào
                wav.unlink(missing_ok=True)
                wav.with_suffix(".json").unlink(missing_ok=True)
                from ..speech import prune_cache
                prune_cache(work / "cache")

        def finish(wav, timings, report):
            out = folder / f"{name}.mp3"
            k = 2
            while out.exists():
                out = folder / f"{name}_{k}.mp3"
                k += 1
            report(0.97, "Đang lưu file")
            r = subprocess.run([find_ffmpeg()[0], "-v", "error", "-nostdin", "-y", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "192k", str(out)],
                               capture_output=True)
            if r.returncode != 0:
                raise RuntimeError("Không lưu được MP3: " + r.stderr.decode("utf-8", "replace")[-200:])
            from ..models import write_srt
            from ..speech import timed_lines
            write_srt(out.with_suffix(".srt"), timed_lines(timings, 42))
            dur = timings[-1][1] if timings else 0.0
            out.with_suffix(".json").write_text(json.dumps({"text": text[:2000], "engine": engine, "voice": voice, "speed": speed, "duration": dur},
                                                           ensure_ascii=False), encoding="utf-8")
            return {"name": out.name, "duration": dur}
        return {"task": tasks.start("speech", job, name)}

    @app.get("/api/speech")
    def speech_list():
        folder = speech_dir()
        items = []
        if folder.exists():
            for f in sorted(folder.glob("*.mp3"), key=lambda x: -x.stat().st_mtime)[:100]:
                meta = {}
                try:
                    meta = json.loads(f.with_suffix(".json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
                items.append({"name": f.name, "size": f.stat().st_size, "at": f.stat().st_mtime, "duration": meta.get("duration"),
                              "text": (meta.get("text") or "")[:160], "srt": f.with_suffix(".srt").exists()})
        return {"items": items, "folder": str(folder)}

    def _speech_file(name: str) -> Path:
        f = (speech_dir() / name).resolve()
        if f.parent != speech_dir().resolve() or f.suffix.lower() not in (".mp3", ".srt") or not f.exists():
            raise HTTPException(404, "Không có file này")
        return f

    @app.get("/api/speech/file/{name}")
    def speech_file(name: str):
        f = _speech_file(name)
        return FileResponse(f, media_type="audio/mpeg" if f.suffix == ".mp3" else "text/plain; charset=utf-8", filename=f.name)

    @app.delete("/api/speech/file/{name}")
    def speech_delete(name: str):
        f = _speech_file(name)
        for x in (f, f.with_suffix(".srt"), f.with_suffix(".json")):
            x.unlink(missing_ok=True)
        return {"ok": True}

    @app.post("/api/speech/reveal")
    def speech_reveal():
        folder = speech_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(folder)  # noqa: S606 — mở thư mục local cho người dùng
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        return {"ok": True}

    # ------------------------------------------------------------------ Giọng của tôi (mẫu giọng tự thu cho VieNeu)
    @app.get("/api/myvoices")
    def myvoices_list():
        from .. import myvoice
        return {"items": myvoice.list_voices()}

    @app.post("/api/myvoices")
    async def myvoices_add(request: Request, name: str = "", gender: str = ""):
        from .. import myvoice
        data = await _read_body(request)
        try:
            return await run_in_threadpool(myvoice.add, data, name, gender)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.put("/api/myvoices/{vid}")
    def myvoices_rename(vid: str, body: dict = Body(...)):
        from .. import myvoice
        try:
            return myvoice.rename(vid, str(body.get("name") or ""))
        except FileNotFoundError as e:
            raise _not_found(e) from None

    @app.delete("/api/myvoices/{vid}")
    def myvoices_delete(vid: str):
        from .. import myvoice
        if not myvoice.delete(vid):
            raise HTTPException(404, "Không có giọng này")
        return {"ok": True}

    @app.get("/api/myvoices/{vid}/sample")
    def myvoices_sample(vid: str):
        from .. import myvoice
        f = myvoice.path_of(vid)
        if f is None:
            raise HTTPException(404, "Không có giọng này")
        return FileResponse(f, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------------ Kể chuyện
    @app.get("/api/story/options")
    def story_options():
        from .. import imagegen, videogen
        from .. import paid as paid_mod
        from .. import stock as stock_mod
        return {
            "styles": [{"id": k, "label": v} for k, v in story_mod.STYLE_LABELS.items()],
            "motions": list(story_mod.MOTIONS), "sub_styles": list(story_mod.SUB_STYLES), "aspects": list(story_mod.SIZES),
            "transitions": [{"id": k, "label": v} for k, v in story_mod.TRANSITIONS.items()], "default_outro": story_mod.DEFAULT_OUTRO,
            "image_ai": imagegen.available(), "image_providers": imagegen.public(),
            "stock_sources": stock_mod.public(), "video_providers": videogen.public(), "video_res": list(videogen.RESOLUTIONS),
            "writer_ai": story_mod.writer_ready(st.cfg()), "writer_local": story_mod.writer_is_local(st.cfg()),
            "paid": paid_mod.status(),
        }

    @app.put("/api/paid")
    def paid_put(body: dict = Body(...)):
        """Công tắc Cho phép tính năng trả phí (Cài đặt, mục Chi phí)."""
        from .. import paid as paid_mod
        paid_mod.set_allowed(bool(body.get("allowed")))
        return paid_mod.status()

    @app.get("/api/stories")
    def stories():
        return {"items": store().list()}

    @app.post("/api/stories")
    def story_create(body: dict = Body(default={})):
        s = store().create(str(body.get("title") or "")[:120])
        if body.get("aspect") in story_mod.SIZES or body.get("style") in story_mod.STYLES:
            def fn(x):
                if body.get("aspect") in story_mod.SIZES:
                    x["aspect"] = body["aspect"]
                if body.get("style") in story_mod.STYLES:
                    x["style"] = body["style"]
            s = store().update(s["id"], fn)
        return s

    def _get(sid: str) -> dict:
        try:
            return store().get(sid)
        except KeyError as e:
            raise _not_found(e) from None

    @app.get("/api/stories/{sid}")
    def story_get(sid: str):
        return _get(sid)

    @app.put("/api/stories/{sid}")
    def story_put(sid: str, body: dict = Body(...)):
        s = store()
        _get(sid)
        with s.lock(sid):
            return s.write(story_mod.merge_story(s.get(sid), body))

    @app.delete("/api/stories/{sid}")
    def story_delete(sid: str):
        _get(sid)
        store().delete(sid)
        return {"ok": True}

    @app.get("/api/stories/{sid}/file/{kind}/{name}")
    def story_file(sid: str, kind: str, name: str):
        try:
            f = store().file(sid, kind, name)
        except KeyError as e:
            raise _not_found(e) from None
        if not f.exists():
            raise HTTPException(404, "Không có file này")
        types = {".png": "image/png", ".jpg": "image/jpeg", ".wav": "audio/wav", ".mp3": "audio/mpeg", ".mp4": "video/mp4"}
        return FileResponse(f, media_type=types.get(f.suffix.lower(), "application/octet-stream"), headers={"Cache-Control": "max-age=86400"})

    @app.post("/api/stories/{sid}/split")
    def story_split(sid: str, body: dict = Body(...)):
        """Chia kịch bản tự viết thành cảnh, không cần AI."""
        _get(sid)
        texts = story_mod.split_script(str(body.get("text") or ""))
        if not texts:
            raise HTTPException(400, "Chưa có kịch bản")

        def fn(s):
            new = [{"id": story_mod.new_id("n"), "text": t, "prompt": "", "characters": [], "motion": "auto", "image": "", "images": [], "created": story_mod._now()}
                   for t in texts]
            s["scenes"] = new if body.get("replace", True) else s["scenes"] + new
        return store().update(sid, fn)

    @app.post("/api/stories/{sid}/write")
    def story_write(sid: str, body: dict = Body(...)):
        """AI viết từ ý tưởng, hoặc AI chia kịch bản có sẵn và gợi ý hình, nhân vật."""
        s0 = _get(sid)
        topic, script = str(body.get("topic") or "").strip(), str(body.get("script") or "").strip()
        if not topic and not script:
            raise HTTPException(400, "Viết ý tưởng hoặc dán kịch bản trước")
        try:
            seconds = min(600, max(20, int(body.get("seconds") or 60)))
        except (TypeError, ValueError):
            seconds = 60
        cfg = st.cfg()
        try:
            story_mod._writer(cfg)      # báo ngay nếu chưa có AI nào, không đợi luồng nền
        except RuntimeError as e:
            raise HTTPException(400, str(e)) from None
        if script and len(script) > 12000:
            raise HTTPException(400, f"Kịch bản dài {len(script):,} ký tự, AI chỉ chia được tối đa 12.000 ký tự một lần. Bỏ chọn nhờ AI để iContent tự chia cảnh.".replace(",", "."))

        def job(report):
            report(None, "AI đang viết kịch bản")
            data = story_mod.write_script(cfg, topic=topic, script=script, seconds=seconds, style=s0.get("style") or "",
                                          lang=(s0.get("voice") or {}).get("lang") or "vi")
            return store().update(sid, lambda s: story_mod.apply_script(s, data, replace=bool(body.get("replace", True))))["id"]
        return {"task": tasks.start("write", job, "Viết kịch bản")}

    @app.put("/api/stories/{sid}/scenes/{scid}/image")
    async def scene_upload(sid: str, scid: str, request: Request):
        _get(sid)
        data = await _read_body(request)
        name = await _image_job(story_mod.add_scene_image, store(), sid, scid, data, "upload")
        return {"image": name, "story": store().get(sid)}

    @app.put("/api/stories/{sid}/scenes-from-image")
    async def scene_new_from_image(sid: str, request: Request):
        _get(sid)
        data = await _read_body(request)
        await _image_job(story_mod.append_image_scene, store(), sid, data)
        return {"story": store().get(sid)}

    @app.get("/api/stories/{sid}/scenes/{scid}/prompt")
    def scene_prompt_text(sid: str, scid: str):
        """Lời nhắn đầy đủ (kèm mô tả nhân vật) để dán sang ChatGPT, Copilot trên web khi không dùng API."""
        s = _get(sid)
        s["_folder"] = store().folder(sid)
        sc = next((x for x in s["scenes"] if x["id"] == scid), None)
        if sc is None:
            raise HTTPException(404, "Không có cảnh này")
        prompt, refs = story_mod.scene_prompt(s, sc)
        return {"prompt": prompt, "refs": [f"/api/stories/{sid}/file/ref/{r.name}" for r in refs]}

    @app.post("/api/stories/{sid}/scenes/{scid}/image/from-library")
    def scene_from_library(sid: str, scid: str, body: dict = Body(...)):
        """Dùng ảnh trong Thư viện ảnh (trang Sửa ảnh) cho cảnh."""
        from .server import IMAGES_DIR
        name = Path(str(body.get("name") or "")).name
        f = IMAGES_DIR / name
        if not name or not f.is_file():
            raise HTTPException(404, "Không có ảnh này trong thư viện")
        try:
            return {"image": story_mod.add_scene_image(store(), sid, scid, f.read_bytes(), "library"), "story": store().get(sid)}
        except KeyError as e:
            raise _not_found(e) from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/stories/{sid}/scenes/{scid}/image/use")
    def scene_use(sid: str, scid: str, body: dict = Body(...)):
        name = str(body.get("name") or "")

        def fn(s):
            for sc in s["scenes"]:
                if sc["id"] == scid:
                    if name not in (sc.get("images") or []):
                        raise KeyError("Ảnh này không thuộc cảnh")
                    sc["image"] = name
                    return
            raise KeyError("Không có cảnh này")
        try:
            return store().update(sid, fn)
        except KeyError as e:
            raise _not_found(e) from None

    @app.post("/api/stories/{sid}/scenes/{scid}/generate")
    def scene_generate(sid: str, scid: str):
        _get(sid)
        cfg = st.cfg()
        keys = [f"{sid}:{scid}", f"{sid}:*"]
        with drawing_lock:      # đang vẽ hàng loạt cả câu chuyện, hoặc đang vẽ đúng cảnh này
            if any(k in drawing for k in keys):
                raise HTTPException(409, "Cảnh này đang được vẽ, đợi xong rồi hãy vẽ lại")
            drawing.add(keys[0])

        def job(report):
            report(None, "AI đang vẽ")
            try:
                return story_mod.generate_scene_image(store(), sid, scid, cfg)
            finally:
                release([keys[0]])
        return {"task": tasks.start("image", job, "Vẽ ảnh cảnh")}

    @app.post("/api/stories/{sid}/generate")
    def story_generate_all(sid: str):
        """Vẽ mọi cảnh chưa có ảnh. Lần lượt từng cảnh: Google giới hạn số ảnh mỗi phút, và lỗi ở một cảnh không được làm mất các cảnh khác."""
        s = _get(sid)
        empty = [sc for sc in s["scenes"] if not sc.get("image")]
        todo = [sc["id"] for sc in empty if sc.get("text") or sc.get("prompt")]
        if not empty:
            raise HTTPException(400, "Cảnh nào cũng đã có ảnh")
        if not todo:
            raise HTTPException(400, "Các cảnh chưa có ảnh đều chưa có lời dẫn hay mô tả để vẽ")
        cfg = st.cfg()
        with drawing_lock:
            if f"{sid}:*" in drawing or any(f"{sid}:{x}" in drawing for x in todo):
                raise HTTPException(409, "Đang vẽ ảnh cho câu chuyện này, đợi xong rồi hãy bấm lại")
            drawing.add(f"{sid}:*")

        def job(report):
            done, skipped, errors = 0, 0, []
            try:
                for k, scid in enumerate(todo):
                    report(k / len(todo), f"Đang vẽ cảnh {k + 1}/{len(todo)}")
                    try:
                        # đọc lại ngay trước khi gọi: cảnh vừa được tải ảnh lên thì bỏ qua, không trả tiền vẽ đè lên ảnh của người dùng
                        if story_mod.generate_scene_image(store(), sid, scid, cfg, skip_if_has_image=True):
                            done += 1
                        else:
                            skipped += 1
                    except KeyError:
                        skipped += 1      # cảnh vừa bị xóa
                    except Exception as e:
                        errors.append(str(e))
                        low = str(e).lower()
                        if "key" in low or "thanh toán" in low or "hạn mức" in low or "nạp tiền" in low:      # cảnh nào cũng sẽ lỗi như nhau
                            break
            finally:
                release([f"{sid}:*"])
            if not done and errors:
                raise RuntimeError(errors[0])
            return {"done": done, "failed": len(todo) - done - skipped, "error": errors[0] if errors else ""}
        return {"task": tasks.start("images", job, "Vẽ ảnh các cảnh")}

    # ------------------------------------------------------------------ video nền miễn phí, clip AI
    @app.get("/api/stories/{sid}/scenes/{scid}/stock")
    def scene_stock_search(sid: str, scid: str, q: str = "", src: str = "", page: int = 1):
        from .. import stock as stock_mod
        s = _get(sid)
        sc = next((x for x in s["scenes"] if x["id"] == scid), None)
        if sc is None:
            raise HTTPException(404, "Không có cảnh này")
        query = q.strip() or (sc.get("broll") or "").strip()
        if not query:
            query = story_mod.broll_queries(st.cfg(), s, [scid]).get(scid, "")
        try:
            items = stock_mod.search(query, s.get("aspect") or "9:16", src, page)
        except stock_mod.StockError as e:
            raise HTTPException(400, str(e)) from None
        need = story_mod.estimate_seconds(s, sc)
        return {"query": query, "need": need, "items": [{k: v for k, v in it.items() if k != "files"} for it in items],
                "sources": stock_mod.public()}

    def _paid_ok() -> None:
        from .. import paid as paid_mod
        if not paid_mod.allowed():
            raise HTTPException(400, paid_mod.block("AI làm clip (Gemini Omni, tính tiền theo giây)", "Video nền miễn phí, hoặc ảnh có máy quay chuyển động"))

    def _scene_claim(sid: str, scid: str) -> list[str]:
        keys = [f"{sid}:v:{scid}"]
        with drawing_lock:
            if f"{sid}:v:*" in drawing or keys[0] in drawing:
                raise HTTPException(409, "Cảnh này đang lấy video, đợi xong rồi hãy bấm lại")
            drawing.update(keys)
        return keys

    @app.post("/api/stories/{sid}/scenes/{scid}/stock")
    def scene_stock_pick(sid: str, scid: str, body: dict = Body(...)):
        from .. import stock as stock_mod
        _get(sid)
        try:
            it = stock_mod.item(str(body.get("src") or ""), str(body.get("id") or ""))
        except KeyError as e:
            raise _not_found(e) from None
        keys = _scene_claim(sid, scid)

        def job(report):
            report(None, f"Tải clip từ {stock_mod.SOURCES[it['src']]['name']}")
            try:
                return story_mod.stock_for_scene(store(), sid, scid, it)
            finally:
                release(keys)
        return {"task": tasks.start("stock", job, "Tải video nền")}

    @app.post("/api/stories/{sid}/stock")
    def story_stock_all(sid: str, body: dict = Body(default={})):
        from .. import stock as stock_mod
        s = _get(sid)
        if not s["scenes"]:
            raise HTTPException(400, "Câu chuyện chưa có cảnh nào")
        src = str(body.get("src") or s.get("stock_src") or "")
        try:
            stock_mod.sources(src)
        except stock_mod.StockError as e:
            raise HTTPException(400, str(e)) from None
        only_missing = bool(body.get("only_missing", True))
        with drawing_lock:
            if any(k.startswith(f"{sid}:v:") for k in drawing):
                raise HTTPException(409, "Đang lấy video cho câu chuyện này, đợi xong rồi hãy bấm lại")
            drawing.add(f"{sid}:v:*")
        cfg = st.cfg()

        def job(report):
            try:
                r = story_mod.stock_fill(store(), sid, cfg, only_missing=only_missing, src=src, report=report,
                                         skip_characters=bool(body.get("skip_characters", True)))
            finally:
                release([f"{sid}:v:*"])
            if not r["done"] and r["error"]:
                raise RuntimeError(r["error"])
            return r
        return {"task": tasks.start("stock-all", job, "Tìm video nền")}

    @app.post("/api/stories/{sid}/scenes/{scid}/animate")
    def scene_animate(sid: str, scid: str):
        from .. import videogen
        _get(sid)
        if not videogen.ready("omni"):
            raise HTTPException(400, "Chưa có key Gemini (đã bật thanh toán). Dán key trong Cài đặt rồi thử lại.")
        _paid_ok()
        cfg = st.cfg()
        keys = _scene_claim(sid, scid)

        def job(report):
            report(None, "Gửi cảnh cho Google")
            try:
                return story_mod.animate_scene(store(), sid, scid, cfg, report=report)
            finally:
                release(keys)
        return {"task": tasks.start("animate", job, "AI làm clip")}

    @app.get("/api/stories/{sid}/animate/estimate")
    def story_animate_estimate(sid: str, only_missing: bool = True, scene: str = ""):
        from .. import videogen
        s = _get(sid)
        res = s.get("video_res") or videogen.DEFAULT_RES
        if scene:
            todo = [sc for sc in s["scenes"] if sc["id"] == scene]
        else:
            todo = [sc for sc in s["scenes"] if not (only_missing and sc.get("clip")) and (sc.get("image") or sc.get("prompt") or sc.get("text"))]
        secs = [videogen.seconds_for(story_mod.estimate_seconds(s, sc)) for sc in todo]
        return {"scenes": len(todo), "seconds": sum(secs), "resolution": res, "usd": round(sum(videogen.price(x, res) for x in secs), 2),
                "ready": videogen.ready("omni"), "status": videogen.status("omni").get("state") or ""}

    @app.post("/api/stories/{sid}/animate")
    def story_animate_all(sid: str, body: dict = Body(default={})):
        """AI làm clip cho các cảnh (chưa có clip). Lần lượt từng cảnh, lỗi key, thanh toán thì dừng ngay (cảnh nào cũng sẽ lỗi như nhau)."""
        from .. import videogen
        s = _get(sid)
        if not videogen.ready("omni"):
            raise HTTPException(400, "Chưa có key Gemini (đã bật thanh toán). Dán key trong Cài đặt rồi thử lại.")
        _paid_ok()
        only_missing = bool(body.get("only_missing", True))
        todo = [sc["id"] for sc in s["scenes"] if not (only_missing and sc.get("clip")) and (sc.get("image") or sc.get("prompt") or sc.get("text"))]
        if not todo:
            raise HTTPException(400, "Cảnh nào cũng đã có clip")
        with drawing_lock:
            if any(k.startswith(f"{sid}:v:") for k in drawing):
                raise HTTPException(409, "Đang lấy video cho câu chuyện này, đợi xong rồi hãy bấm lại")
            drawing.add(f"{sid}:v:*")
        cfg = st.cfg()

        def job(report):
            done, errors = 0, []
            try:
                for k, scid in enumerate(todo):
                    report(k / len(todo), f"AI làm clip cảnh {k + 1}/{len(todo)}")
                    try:
                        story_mod.animate_scene(store(), sid, scid, cfg, report=lambda f, m, k=k: report(None, f"Cảnh {k + 1}/{len(todo)}: {m}"))
                        done += 1
                    except KeyError:
                        continue
                    except Exception as e:      # noqa: BLE001
                        errors.append(str(e))
                        low = str(e).lower()
                        if "key" in low or "thanh toán" in low or "miễn phí" in low or "hạn mức" in low:
                            break
            finally:
                release([f"{sid}:v:*"])
            if not done and errors:
                raise RuntimeError(errors[0])
            return {"done": done, "failed": len(todo) - done, "error": errors[0] if errors else ""}
        return {"task": tasks.start("animate-all", job, "AI làm clip các cảnh")}

    @app.post("/api/stories/{sid}/scenes/{scid}/clip/use")
    def scene_clip_use(sid: str, scid: str, body: dict = Body(...)):
        try:
            return story_mod.use_clip(store(), sid, scid, str(body.get("name") or ""))
        except KeyError as e:
            raise _not_found(e) from None

    @app.delete("/api/stories/{sid}/scenes/{scid}/clip/{name}")
    def scene_clip_delete(sid: str, scid: str, name: str):
        try:
            store().file(sid, "clip", name)
            return story_mod.delete_clip(store(), sid, scid, name)
        except KeyError as e:
            raise _not_found(e) from None

    @app.get("/api/stories/{sid}/credits")
    def story_credits(sid: str):
        s = _get(sid)
        return {"items": story_mod.credits(s), "text": story_mod.credits_text(s)}

    @app.get("/api/stories/{sid}/drawing")
    def story_drawing(sid: str):
        """Cảnh nào đang được vẽ: quay lại trang câu chuyện vẫn thấy nút đang bận, không bấm vẽ lần nữa."""
        with drawing_lock:
            mine = [k.split(":", 1)[1] for k in drawing if k.startswith(sid + ":")]
        clips = [x[2:] for x in mine if x.startswith("v:")]
        mine = [x for x in mine if not x.startswith("v:") and not x.startswith("c:")]
        return {"all": "*" in mine, "scenes": [x for x in mine if x != "*"], "clips_all": "*" in clips, "clips": [x for x in clips if x != "*"]}

    @app.put("/api/stories/{sid}/characters/{cid}/ref")
    async def character_upload(sid: str, cid: str, request: Request):
        _get(sid)
        data = await _read_body(request)
        ref = await _image_job(story_mod.add_character_ref, store(), sid, cid, data)
        return {"ref": ref, "story": store().get(sid)}

    @app.delete("/api/stories/{sid}/characters/{cid}/ref/{name}")
    def character_ref_delete(sid: str, cid: str, name: str):
        def fn(s):
            for c in s["characters"]:
                if c["id"] == cid:
                    c["refs"] = [r for r in c.get("refs") or [] if r != name]
                    return
            raise KeyError("Không có nhân vật này")
        try:
            out = store().update(sid, fn)
            store().file(sid, "ref", name).unlink(missing_ok=True)
            return out
        except KeyError as e:
            raise _not_found(e) from None

    @app.post("/api/stories/{sid}/characters/{cid}/generate")
    def character_generate(sid: str, cid: str):
        _get(sid)
        cfg = st.cfg()
        claim([f"{sid}:c:{cid}"])

        def job(report):
            report(None, "AI đang vẽ ảnh mẫu nhân vật")
            try:
                return story_mod.generate_character_ref(store(), sid, cid, cfg)
            finally:
                release([f"{sid}:c:{cid}"])
        return {"task": tasks.start("character", job, "Vẽ ảnh mẫu nhân vật")}

    @app.post("/api/stories/{sid}/scenes/{scid}/listen")
    def scene_listen(sid: str, scid: str):
        s = _get(sid)
        sc = next((x for x in s["scenes"] if x["id"] == scid), None)
        if sc is None or not sc.get("text", "").strip():
            raise HTTPException(400, "Cảnh chưa có lời dẫn")

        def job(report):
            one = dict(s, scenes=[sc])
            v = story_mod.narrate(store(), sid, one)[0]
            return {"audio": f"/api/stories/{sid}/file/audio/{v['wav'].name}", "duration": v["dur"]}
        return {"task": tasks.start("listen", job, "Đọc thử cảnh")}

    @app.post("/api/stories/{sid}/render")
    def story_render(sid: str):
        s = _get(sid)
        missing = [i + 1 for i, sc in enumerate(s["scenes"]) if not sc.get("image")]
        if not s["scenes"]:
            raise HTTPException(400, "Câu chuyện chưa có cảnh nào")
        if missing:
            raise HTTPException(400, "Cảnh " + ", ".join(map(str, missing[:12])) + " chưa có ảnh")
        with st.lock:
            if any(i.get("story") == sid and i["state"] in ("queued", "running") for i in st.items):
                raise HTTPException(409, "Câu chuyện này đang được dựng")
        qid = st.enqueue(f"story:{sid}", None, None, title=s.get("title") or "Kể chuyện", kind="story", payload={"sid": sid})
        with st.lock:      # giao diện cần biết lượt này của câu chuyện nào (payload không được gửi ra ngoài)
            next(i for i in st.items if i["qid"] == qid)["story"] = sid
        return {"qid": qid}

    @app.post("/api/stories/{sid}/reveal")
    def story_reveal(sid: str):
        s = _get(sid)
        out = Path(s.get("output") or "")
        if os.name == "nt":
            if out.is_file():
                subprocess.Popen(["explorer", "/select,", str(out)])      # noqa: S603, S607
            else:
                os.startfile(store().folder(sid))  # noqa: S606
        elif sys.platform == "darwin":
            if out.is_file():
                subprocess.Popen(["open", "-R", str(out)])
            else:
                subprocess.Popen(["open", str(store().folder(sid))])
        return {"ok": True}

    @app.get("/api/stories/{sid}/video")
    def story_video(sid: str):
        s = _get(sid)
        out = Path(s.get("output") or "")
        if not out.is_file():
            raise HTTPException(404, "Chưa dựng video")
        return FileResponse(out, media_type="video/mp4", headers={"Cache-Control": "no-cache"})

    # bản gửi về từ Trình dựng
    def _edited(sid: str, name: str) -> Path:
        s = _get(sid)
        it = next((x for x in s.get("edited") or [] if x.get("name") == name), None)
        f = Path(it["path"]) if it else None
        if f is None or not f.is_file():
            raise HTTPException(404, "Không có bản dựng này")
        return f

    @app.get("/api/stories/{sid}/edited/{name}")
    def story_edited_file(sid: str, name: str):
        f = _edited(sid, name)
        return FileResponse(f, media_type={".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}.get(f.suffix.lower(), "video/mp4"),
                            headers={"Cache-Control": "no-cache"})

    @app.post("/api/stories/{sid}/edited/{name}/reveal")
    def story_edited_reveal(sid: str, name: str):
        f = _edited(sid, name)
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(f)])      # noqa: S603, S607
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(f)])
        return {"ok": True}

    # ------------------------------------------------------------------ Trang chủ
    gpu_cache: dict[str, str] = {}

    def gpu_name() -> str:
        if "name" not in gpu_cache:
            try:
                r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True, timeout=8)
                gpu_cache["name"] = r.stdout.strip().splitlines()[0].replace(", ", " · ") if r.returncode == 0 and r.stdout.strip() else ""
            except (OSError, subprocess.SubprocessError, IndexError):
                gpu_cache["name"] = ""
            if not gpu_cache["name"] and sys.platform == "darwin":
                try:
                    r = subprocess.run(["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=5)
                    if r.returncode == 0 and r.stdout.strip():
                        gpu_cache["name"] = r.stdout.strip()
                except (OSError, subprocess.SubprocessError):
                    pass
        return gpu_cache["name"]

    def _merges():
        from ..montage import MergeStore
        return MergeStore(st.work() / ".merges")

    def _collect(limit: int | None = 40, sizes: bool = False) -> list[dict]:
        """Mọi thứ đã làm, mới nhất trước. limit: số mục tối đa của mỗi loại (Trang chủ chỉ cần ít). sizes: kèm dung lượng (Thư viện)."""
        from .. import library as lib
        q = lambda x: quote(str(x), safe="")      # noqa: E731
        out_dir = Path(st.cfg().output_dir)
        cut = (lambda xs: xs[:limit]) if limit else (lambda xs: xs)
        items = []
        for s in cut(store().list()):
            it = {"kind": "story", "id": s["id"], "title": s.get("title") or "Câu chuyện", "updated": s.get("updated") or 0,
                  "thumb": f"/api/stories/{q(s['id'])}/file/img/{q(s['cover'])}" if s.get("cover") else "",
                  "status": "Đã dựng video" if s.get("output") else f"{s.get('scenes') or 0} cảnh", "done": bool(s.get("output")),
                  "href": f"#/story/{q(s['id'])}"}
            if sizes:
                full = {}
                try:
                    full = store().get(s["id"])
                except (KeyError, ValueError, OSError):
                    pass
                outs = lib.story_outputs(full, out_dir)
                it.update(size=lib.tree_size(store().folder(s["id"])), out_size=sum(lib.tree_size(f) for f in outs), outputs=len(outs),
                          video=f"/api/stories/{q(s['id'])}/video" if s.get("output") and Path(s["output"]).is_file() else "",
                          thumb_href=f"#/thumb/story/{q(s['id'])}")
            items.append(it)
        w = st.work()
        if w.exists():
            busy = st.busy_jobs()
            jobs = cut(sorted(lib.job_dirs(w), key=lambda p: -(p / "meta.json").stat().st_mtime))
            for p in jobs:
                try:
                    j = st.job_summary(p, busy)
                except Exception:      # noqa: BLE001 — một video hỏng không làm hỏng trang chủ
                    continue
                title = j.get("title_vi") or ""
                if not title:
                    try:
                        title = thumbs_mod.job_text(p)[0]
                    except Exception:      # noqa: BLE001
                        title = ""
                done = bool(j.get("output"))
                updated = max((p / f).stat().st_mtime for f in ("meta.json", "final.mp4", "segments.json") if (p / f).exists())
                it = {"kind": "job", "id": j["id"], "title": title or j.get("title") or j["id"], "updated": updated, "thumb": j["thumb"],
                      "status": "Đang xử lý" if j.get("busy") else ("Đã xuất video" if done else "Chưa xong"), "done": done,
                      "href": f"#/studio/{q(j['id'])}", "busy": bool(j.get("busy"))}
                if sizes:
                    outs = lib.job_outputs(p, out_dir)
                    it.update(size=lib.tree_size(p), out_size=sum(lib.tree_size(f) for f in outs), outputs=len(outs),
                              video=f"/api/jobs/{q(j['id'])}/media/final.mp4" if (p / "final.mp4").exists() else "",
                              thumb_href=f"#/thumb/job/{q(j['id'])}", duration=j.get("duration") or 0, platform=j.get("platform") or "",
                              original=j.get("title") or "")
                items.append(it)
        for f in cut(wstore().list()):
            it = {"kind": "flow", "id": f["id"], "title": f["name"], "updated": f["updated"], "thumb": "", "types": f["types"],
                  "status": {"done": "Chạy xong", "error": "Lỗi lần chạy trước", "stopped": "Đã dừng", "running": "Đang chạy"}.get(f["state"], f"{f['nodes']} khối"),
                  "done": f["state"] == "done", "href": f"#/flow/{q(f['id'])}", "busy": f["id"] in runs and runs[f["id"]].state == "running"}
            if sizes:
                it["size"] = lib.tree_size(wstore().path(f["id"])) + lib.tree_size(wstore().files(f["id"]))
            items.append(it)
        sd = speech_dir()
        if sd.exists():
            for f in cut(sorted(sd.glob("*.mp3"), key=lambda x: -x.stat().st_mtime)):
                it = {"kind": "speech", "id": f.name, "title": f.stem, "updated": f.stat().st_mtime, "thumb": "", "status": "Giọng đọc MP3",
                      "done": True, "href": "#/voice", "audio": f"/api/speech/file/{q(f.name)}"}
                if sizes:
                    it["size"] = sum(x.stat().st_size for x in (f, f.with_suffix(".srt"), f.with_suffix(".json")) if x.exists())
                items.append(it)
        if sizes:      # Trang chủ không hiện bản ghép (đã có trang Ghép video); Thư viện thì phải đủ để dọn được
            for m in _merges().items():
                p = Path(m["path"])
                items.append({"kind": "merge", "id": m["id"], "title": m.get("name") or p.stem, "updated": m.get("created") or 0,
                              "thumb": f"/api/merges/{q(m['id'])}/thumb", "status": "Video ghép", "done": True, "href": "#/merge",
                              "video": f"/api/merges/{q(m['id'])}/video", "size": lib.tree_size(p), "duration": m.get("duration") or 0})
        items.sort(key=lambda x: -(x.get("updated") or 0))
        return items

    @app.get("/api/home")
    def home():
        import shutil as _sh
        from .. import editor as ed
        from .. import imagegen
        from .. import myvoice
        q = lambda x: quote(str(x), safe="")      # noqa: E731
        items = _collect(40)
        w = st.work()
        running = []
        with st.lock:
            for it in st.items:
                if it["state"] in ("queued", "running"):
                    running.append({"kind": "queue", "prefetch": it.get("kind") == "prefetch", "title": it.get("title") or "", "state": it["state"], "progress": it.get("progress"),
                                    "message": it.get("message") or "", "href": f"#/story/{q(it['story'])}" if it.get("story") else (f"#/studio/{q(it['job'])}" if it.get("job") else ("#/home" if it.get("kind") == "prefetch" else "#/library"))})
        for wid, r in list(runs.items()):
            snap = r.snapshot()
            if snap["state"] == "running":
                ns = list(snap["nodes"].values())
                done_n = sum(1 for x in ns if x["state"] == "done")
                cur = next((x for x in ns if x["state"] == "running"), {})
                running.append({"kind": "flow", "title": next((f["name"] for f in wstore().list() if f["id"] == wid), "Quy trình"), "state": "running",
                                "progress": done_n / max(1, len(ns)), "message": cur.get("message") or f"Xong {done_n}/{len(ns)} khối", "href": f"#/flow/{q(wid)}"})
        try:
            du = _sh.disk_usage(w if w.exists() else ROOT)
            disk = {"free_gb": round(du.free / 1e9, 1), "total_gb": round(du.total / 1e9, 1), "path": str((w if w.exists() else ROOT).resolve().anchor)}
        except OSError:
            disk = None
        return {"items": items[:24], "counts": {k: sum(1 for x in items if x["kind"] == k) for k in ("job", "story", "flow", "speech")},
                "running": running, "image_providers": imagegen.public(), "editor": ed.available(), "gpu": gpu_name(), "disk": disk,
                "my_voices": len(myvoice.list_voices()), "first_run": not items}

    # ------------------------------------------------------------------ Thư viện: xem, xóa, dọn dung lượng
    from .. import library as lib_mod
    models_size: dict[str, tuple[float, int]] = {}

    def busy_stories() -> set[str]:
        """Câu chuyện không được dọn hay xóa lúc này: đang chờ hoặc đang dựng, đang đóng gói cho Trình dựng. Quy trình đang chạy có thể đang
        vẽ, dựng hay đóng gói bất kỳ câu chuyện nào của nó: khi đó coi mọi câu chuyện là bận."""
        if any(r.state == "running" for r in list(runs.values())):
            return {d.name for d in (st.work() / ".stories").iterdir()} if (st.work() / ".stories").is_dir() else set()
        with st.lock:
            out = {i["story"] for i in st.items if i.get("story") and i["state"] in ("queued", "running")}
        for sid in list(packing):
            t, _ = _pack_task(sid)
            if t and t["state"] == "running":
                out.add(sid)
        return out

    def _disk() -> dict | None:
        import shutil as _sh
        w = st.work()
        try:
            du = _sh.disk_usage(w if w.exists() else ROOT)
            return {"free": du.free, "total": du.total, "path": str((w if w.exists() else ROOT).resolve().anchor)}
        except OSError:
            return None

    @app.get("/api/library")
    def library():
        items = _collect(None, sizes=True)
        return {"items": items, "counts": {k: sum(1 for x in items if x["kind"] == k) for k in ("job", "story", "flow", "merge", "speech")},
                "output_dir": str(Path(st.cfg().output_dir).resolve())}

    @app.get("/api/library/storage")
    def library_storage():
        from ..util import hf_cache_dir
        cfg = st.cfg()
        hf = hf_cache_dir()
        # mô hình AI vài GB, ít khi đổi: tính lại sau 10 phút
        at, size = models_size.get("hf", (0.0, -1))
        parts = lib_mod.storage(st.work(), Path(cfg.output_dir), None)
        if time.time() - at > 600 or size < 0:
            size = lib_mod.tree_size(hf) if hf.is_dir() else 0
            models_size["hf"] = (time.time(), size)
        if size:
            parts.append({"id": "models", "label": "Mô hình AI (dùng chung)", "bytes": size})
        plan = lib_mod.cleanup_plan(st.work(), Path(cfg.output_dir), st.busy_jobs(), busy_stories())
        return {"parts": parts, "cleanable": lib_mod.plan_summary(plan), "disk": _disk()}

    @app.post("/api/library/cleanup")
    def library_cleanup(body: dict = Body(default={})):
        groups = [g for g in body.get("groups") or [] if g in lib_mod.GROUPS]
        if not groups:
            raise HTTPException(400, "Chưa chọn mục nào để dọn")
        plan = lib_mod.cleanup_plan(st.work(), Path(st.cfg().output_dir), st.busy_jobs(), busy_stories())
        freed = failed = 0
        for g in groups:
            f, n = lib_mod.remove_paths(plan[g])
            freed, failed = freed + f, failed + n
        return {"freed": freed, "failed": failed, "disk": _disk()}

    @app.post("/api/library/delete")
    def library_delete(body: dict = Body(...)):
        """Xóa nhiều mục một lần. outputs: xóa luôn video đã xuất trong thư mục output (mặc định giữ lại)."""
        items = body.get("items")
        if not isinstance(items, list) or not items:
            raise HTTPException(400, "Chưa chọn mục nào")
        with_outputs = bool(body.get("outputs"))
        out_dir = Path(st.cfg().output_dir)
        bjobs, bstories = st.busy_jobs(), busy_stories()
        freed, done, errors = 0, [], []
        for it in items[:500]:
            kind, iid = str((it or {}).get("kind") or ""), str((it or {}).get("id") or "")
            try:
                if kind == "job":
                    p = st.job_dir(iid)
                    if iid in bjobs:
                        raise RuntimeError("đang xử lý")
                    paths = [p] + (lib_mod.job_outputs(p, out_dir) if with_outputs else [])
                elif kind == "story":
                    _get(iid)
                    if iid in bstories:
                        raise RuntimeError("đang dựng")
                    paths = [store().folder(iid)] + (lib_mod.story_outputs(store().get(iid), out_dir) if with_outputs else [])
                elif kind == "flow":
                    _wf(iid)
                    r = runs.get(iid)
                    if r and r.state == "running":
                        raise RuntimeError("đang chạy")
                    paths = [wstore().path(iid), wstore().files(iid)]
                elif kind == "speech":
                    f = _speech_file(iid)
                    paths = [f, f.with_suffix(".srt"), f.with_suffix(".json")]
                elif kind == "merge":
                    rec = _merges().get(iid)
                    if not rec:
                        raise RuntimeError("không còn")
                    size = lib_mod.tree_size(Path(rec["path"]))
                    try:
                        _merges().remove(iid)
                    except PermissionError:
                        raise RuntimeError("file đang được mở") from None
                    freed += size
                    done.append({"kind": kind, "id": iid})
                    continue
                else:
                    raise RuntimeError("không rõ loại")
            except HTTPException as e:
                errors.append({"kind": kind, "id": iid, "error": str(e.detail)})
                continue
            except RuntimeError as e:
                errors.append({"kind": kind, "id": iid, "error": str(e)})
                continue
            if kind == "story":
                with store().lock(iid):
                    f, n = lib_mod.remove_paths(paths)
            else:
                f, n = lib_mod.remove_paths(paths)
            freed += f
            if n:
                errors.append({"kind": kind, "id": iid, "error": "một vài file đang được mở, chưa xóa hết"})
            else:
                done.append({"kind": kind, "id": iid})
        return {"freed": freed, "deleted": done, "errors": errors, "disk": _disk()}

    # ------------------------------------------------------------------ Quy trình kéo thả
    from .. import workflow as wf_mod
    runs: dict[str, wf_mod.Run] = {}
    runs_lock = threading.Lock()

    def wstore() -> wf_mod.WorkflowStore:
        return wf_mod.WorkflowStore(st.work() / ".workflows")

    def _wf(wid: str) -> dict:
        try:
            return wstore().get(wid)
        except KeyError as e:
            raise _not_found(e) from None

    def _wf_out(w: dict) -> dict:
        r = runs.get(w["id"])
        return {**{k: v for k, v in w.items() if k != "memo"}, "problems": wf_mod.problems(w), "run": r.snapshot() if r else w.get("last")}

    @app.get("/api/workflow/nodes")
    def wf_nodes():
        from .. import imagegen
        return {**wf_mod.public_nodes(), "music": wf_mod.music_files(), "image_providers": imagegen.public()}

    @app.get("/api/workflows")
    def wf_list():
        return {"items": wstore().list()}

    @app.post("/api/workflows")
    def wf_create(body: dict = Body(default={})):
        tid = str(body.get("template") or "blank")
        # bấm thử một mẫu rồi quay ra bấm lại: mở lại bản chưa đụng tới của mẫu đó, không tạo thêm bản trùng
        same = next((x for x in wstore().list() if x["template"] == tid and not x["touched"] and not x["state"]), None)
        if same and not body.get("name"):
            return _wf_out(_wf(same["id"]))
        w = wf_mod.from_template(tid, str(body.get("name") or "")[:80])
        return _wf_out(wstore().write(w))

    @app.get("/api/workflows/{wid}")
    def wf_get(wid: str):
        return _wf_out(_wf(wid))

    @app.put("/api/workflows/{wid}")
    def wf_put(wid: str, body: dict = Body(...)):
        cur = _wf(wid)
        r = runs.get(wid)
        if r and r.state == "running" and len(body.get("nodes") or []) != len(cur["nodes"]):
            raise HTTPException(409, "Quy trình đang chạy: dừng lại rồi mới thêm, bớt khối")

        def apply(x):      # trong khóa: không đè lên bộ nhớ chạy, kết quả mà luồng chạy vừa ghi
            new = wf_mod.clean_graph(x, body)
            x.clear()
            x.update(new)
        return _wf_out(wstore().update(wid, apply))

    @app.delete("/api/workflows/{wid}")
    def wf_delete(wid: str):
        _wf(wid)
        r = runs.get(wid)
        if r and r.state == "running":
            raise HTTPException(409, "Quy trình đang chạy: dừng lại trước")
        wstore().delete(wid)
        return {"ok": True}

    @app.post("/api/workflows/{wid}/run")
    def wf_run(wid: str, request: Request, body: dict = Body(default={})):
        w = _wf(wid)
        with runs_lock:
            r = runs.get(wid)
            if r and r.state == "running":
                raise HTTPException(409, "Quy trình đang chạy")
            try:
                wf_mod.order(w)
            except ValueError as e:
                raise HTTPException(400, str(e)) from None
            if not w["nodes"]:
                raise HTTPException(400, "Quy trình chưa có khối nào: kéo khối từ bảng bên trái vào")
            bad = wf_mod.problems(w)
            if bad:
                return {"problems": bad}
            est = wf_mod.estimate(w, store(), wstore())
            if est["images"] and not body.get("confirm"):
                return {"confirm": est}      # có khối vẽ ảnh trả phí: hỏi người dùng kèm số ảnh, giá
            run = wf_mod.Run(w)
            runs[wid] = run
        host = request.headers.get("host")

        def open_editor(sid: str):
            from .. import appwin, editor as ed
            if not ed.available():
                raise RuntimeError("Bản cài này chưa có Trình dựng")
            appwin.open_window(ed.window_url(host, story=sid), maximized=True)

        def render(sid: str, report):
            """Dựng qua hàng đợi chung như nút Dựng video của Kể chuyện: đang có lượt dựng câu chuyện này thì đợi lượt đó, không chạy song song."""
            s0 = story_mod.StoryStore(st.work() / ".stories").get(sid)
            with st.lock:
                it = next((i for i in st.items if i.get("story") == sid and i["state"] in ("queued", "running")), None)
                qid = it["qid"] if it else None
            if not qid:
                qid = st.enqueue(f"story:{sid}", None, None, title=s0.get("title") or "Kể chuyện", kind="story", payload={"sid": sid})
                with st.lock:
                    next(i for i in st.items if i["qid"] == qid)["story"] = sid
            while True:
                with st.lock:
                    it = dict(next((i for i in st.items if i["qid"] == qid), {"state": "error", "message": "Lượt dựng bị xóa khỏi hàng đợi"}))
                if it["state"] == "done":
                    break
                if it["state"] in ("error", "cancelled"):
                    raise RuntimeError(it.get("error") or it.get("message") or "Dựng video lỗi")
                if run.stop.is_set():
                    try:
                        st.cancel(qid)
                    except Exception:      # noqa: BLE001 — lượt dựng vừa xong hay vừa bị xóa: vẫn dừng
                        pass
                    raise wf_mod.Stopped()
                msg = "Đang chờ lượt dựng (hàng đợi đang bận)" if it["state"] == "queued" else (it.get("message") or "Đang dựng video")
                report(it.get("progress"), msg)
                time.sleep(0.7)
            out = story_mod.StoryStore(st.work() / ".stories").get(sid).get("output") or ""
            if not Path(out).is_file():
                raise RuntimeError("Dựng xong nhưng không thấy file video")
            return out

        def go():
            try:
                wf_mod.execute(w, run, store(), st, wstore(), open_editor=open_editor, render=render)
                run.state = "done"
            except wf_mod.Stopped:
                run.state, run.error = "stopped", "Đã dừng"
            except Exception as e:      # noqa: BLE001 — mọi lỗi phải về giao diện
                run.state, run.error = "error", str(e)[:500] or type(e).__name__
            snap = run.snapshot()
            try:
                wstore().update(wid, lambda x: x.update(last=snap))
            except KeyError:
                pass      # quy trình vừa bị xóa
        threading.Thread(target=go, daemon=True, name=f"ui-workflow-{wid}").start()
        return {"run": run.snapshot()}

    @app.get("/api/workflows/{wid}/run")
    def wf_run_state(wid: str):
        r = runs.get(wid)
        return {"run": r.snapshot() if r else _wf(wid).get("last")}

    @app.post("/api/workflows/{wid}/stop")
    def wf_stop(wid: str):
        r = runs.get(wid)
        if r and r.state == "running":
            r.stop.set()
        return {"ok": True}

    @app.put("/api/workflows/{wid}/files")
    async def wf_upload(wid: str, request: Request):
        _wf(wid)
        data = await _read_body(request)
        try:
            return {"name": await run_in_threadpool(wf_mod.save_upload, wstore(), wid, data)}
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.get("/api/workflows/{wid}/files/{name}")
    def wf_file(wid: str, name: str):
        _wf(wid)
        f = wstore().files(wid) / name
        if not wf_mod.FILE_RE.fullmatch(name) or not f.is_file():
            raise HTTPException(404, "Không có ảnh này")
        return FileResponse(f, headers={"Cache-Control": "max-age=86400"})

    @app.post("/api/workflows/{wid}/nodes/{nid}/reveal")
    def wf_reveal(wid: str, nid: str):
        """Mở thư mục xuất của khối Xuất bộ đăng bài (chỉ thư mục nằm trong output)."""
        r = runs.get(wid)
        snap = r.snapshot() if r else (_wf(wid).get("last") or {})
        folder = Path((((snap.get("nodes") or {}).get(nid) or {}).get("preview") or {}).get("folder") or "")
        out = Path(st.cfg().output_dir).resolve()
        if not folder.is_dir() or out not in folder.resolve().parents:
            raise HTTPException(404, "Chưa có thư mục xuất")
        if os.name == "nt":
            os.startfile(folder)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        return {"ok": True}

    # ------------------------------------------------------------------ Thumbnail (trang thay cho Sửa ảnh)
    from .. import thumbs as thumbs_mod

    def _thumb_target(kind: str, tid: str) -> tuple[Path, dict]:
        """Thư mục lưu thumbnail và thông tin của video nguồn."""
        if kind == "story":
            s = _get(tid)
            return store().folder(tid), {"title": s.get("title") or "", "aspect": s.get("aspect") or "9:16",
                                         "video": f"/api/stories/{quote(tid, safe='')}/video" if s.get("output") and Path(s["output"]).is_file() else None}
        if kind == "job":
            from ..pipeline import load_json
            p = st.job_dir(tid)
            if not (p / "meta.json").exists():
                raise HTTPException(404, "Không có video này")
            meta = load_json(p / "meta.json") or {}
            title, _ = thumbs_mod.job_text(p)
            return p, {"title": title, "aspect": "9:16" if (meta.get("height") or 0) > (meta.get("width") or 0) else "16:9",
                       "video": f"/api/jobs/{quote(tid, safe='')}/media/final.mp4" if (p / "final.mp4").exists() else None,
                       "duration": meta.get("duration") or 0}
        raise HTTPException(404, "Không rõ loại video")

    @app.get("/api/thumbs/sources")
    def thumbs_sources():
        items = thumbs_mod.story_sources(store()) + thumbs_mod.job_sources(st)
        items.sort(key=lambda x: x.get("updated") or 0, reverse=True)
        return {"items": items}

    @app.get("/api/thumbs/{kind}/{tid}")
    def thumbs_get(kind: str, tid: str):
        folder, info = _thumb_target(kind, tid)
        bgs = thumbs_mod.story_backgrounds(store(), tid) if kind == "story" else thumbs_mod.job_backgrounds(folder)
        img = folder / ("thumb.jpg" if kind == "story" else "cover.jpg")
        q = f"/api/thumbs/{kind}/{quote(tid, safe='')}"
        return {**info, "kind": kind, "id": tid, "backgrounds": bgs, "project": thumbs_mod.load_project(folder),
                "image": f"{q}/image?v={int(img.stat().st_mtime)}" if img.is_file() else None}

    @app.get("/api/thumbs/{kind}/{tid}/image")
    def thumbs_image(kind: str, tid: str):
        folder, _ = _thumb_target(kind, tid)
        img = folder / ("thumb.jpg" if kind == "story" else "cover.jpg")
        if not img.is_file():
            raise HTTPException(404, "Chưa có thumbnail")
        return FileResponse(img, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})

    @app.put("/api/thumbs/{kind}/{tid}")
    async def thumbs_save(kind: str, tid: str, request: Request, aspect: str = ""):
        folder, _ = _thumb_target(kind, tid)
        data = await _read_body(request)
        try:
            if kind == "story":
                dst = await run_in_threadpool(thumbs_mod.save_story_thumb, store(), tid, data, aspect)
            else:
                dst = await run_in_threadpool(thumbs_mod.save_job_thumb, folder, data, aspect)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return {"path": str(dst.resolve()), "url": f"/api/thumbs/{kind}/{quote(tid, safe='')}/image?v={int(time.time() * 1000)}"}

    @app.put("/api/thumbs/{kind}/{tid}/project")
    def thumbs_project(kind: str, tid: str, body: dict = Body(...)):
        folder, _ = _thumb_target(kind, tid)
        try:
            thumbs_mod.save_project(folder, body)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return {"ok": True}

    @app.post("/api/thumbs/{kind}/{tid}/suggest")
    def thumbs_suggest(kind: str, tid: str):
        folder, _ = _thumb_target(kind, tid)
        title, text = thumbs_mod.story_text(store(), tid) if kind == "story" else thumbs_mod.job_text(folder)
        try:
            return {"items": thumbs_mod.suggest_texts(st.cfg(), title, text)}
        except RuntimeError as e:      # chưa kết nối AI, hoặc AI trả rỗng
            raise HTTPException(400, str(e)) from None

    THUMB_BG = re.compile(r"[0-9a-f]{16}\.jpg")

    @app.put("/api/thumb-bg")
    async def thumbs_bg_upload(request: Request):
        """Ảnh nền tự tải lên: lưu lại để mở bản thiết kế lần sau vẫn có ảnh."""
        import hashlib
        data = await _read_body(request)
        try:
            im = thumbs_mod._check_image(data)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        d = st.work() / ".thumbs"
        d.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha1(data).hexdigest()[:16] + ".jpg"
        if not (d / name).exists():
            im.thumbnail((3840, 3840))
            im.save(d / name, "JPEG", quality=93)
        return {"url": f"/api/thumb-bg/{name}"}

    @app.get("/api/thumb-bg/{name}")
    def thumbs_bg(name: str):
        f = st.work() / ".thumbs" / name
        if not THUMB_BG.fullmatch(name) or not f.is_file():
            raise HTTPException(404, "Không có ảnh này")
        return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})

    # ------------------------------------------------------------------ mở câu chuyện trong Trình dựng (cửa sổ editor.localhost chỉ gọi được /api/editor/)
    packing: dict[str, tuple[str, str]] = {}      # câu chuyện -> (tác vụ chuẩn bị gói gần nhất, chữ ký câu chuyện lúc bắt đầu)
    packing_lock = threading.Lock()      # hai lần bấm gần nhau không chạy hai lượt dựng cùng một thư mục gói
    PACK_FILE = re.compile(r"\d{3}_(intro|scene|outro)_[0-9a-f]{10}\.mp4")

    def _pack_project(sid: str, m: dict) -> dict:
        q = quote(sid, safe="")
        out = {k: v for k, v in m.items() if k not in ("music", "sig")}
        out["segments"] = [{**x, "url": f"/api/editor/stories/{q}/file/{quote(x['file'], safe='')}"} for x in m["segments"]]
        music = m.get("music")
        out["music"] = {**{k: v for k, v in music.items() if k != "path"}, "url": f"/api/editor/stories/{q}/music/{quote(music['name'], safe='')}"} if music else None
        return out

    def _pack_task(sid: str) -> tuple[dict | None, str]:
        tid, sig = packing.get(sid) or ("", "")
        if not tid:
            return None, ""
        try:
            return tasks.get(tid), sig
        except KeyError:
            return None, ""

    @app.get("/api/editor/stories/{sid}")
    def editor_story(sid: str):
        """ready: gói đã có và khớp câu chuyện. preparing: đang đọc lời, dựng từng đoạn. missing: hãy gọi prepare.
        failed: lần chuẩn bị gần nhất lỗi, với đúng bản câu chuyện này. Đã sửa câu chuyện sau lần lỗi thì là missing: thử lại với bản mới."""
        s = _get(sid)
        t, sig = _pack_task(sid)
        if t and t["state"] == "running":
            return {"state": "preparing", "progress": t["progress"], "message": t["message"] or "Đang chuẩn bị"}
        m = story_mod.editor_pack_ready(store(), sid)
        if m:
            return {"state": "ready", "project": _pack_project(sid, m)}
        if t and t["state"] == "error" and sig == story_mod.editor_signature(s):
            return {"state": "failed", "message": t["error"] or "Không chuẩn bị được câu chuyện"}
        return {"state": "missing"}

    @app.post("/api/editor/stories/{sid}/prepare")
    def editor_story_prepare(sid: str):
        s = _get(sid)
        with packing_lock:
            t, _ = _pack_task(sid)
            if t and t["state"] == "running":
                return {"state": "preparing"}
            if story_mod.editor_pack_ready(store(), sid):
                return {"state": "ready"}

            def job(report):
                return {"duration": story_mod.build_editor_pack(store(), sid, st.cfg(), report=report)["duration"]}
            packing[sid] = (tasks.start("story-editor", job, sid), story_mod.editor_signature(s))
        return {"state": "preparing"}

    @app.get("/api/editor/stories/{sid}/file/{name}")
    def editor_story_file(sid: str, name: str):
        _get(sid)
        f = store().folder(sid) / story_mod.EDITOR_PACK / name
        if not PACK_FILE.fullmatch(name) or not f.is_file():
            raise HTTPException(404, "Không có đoạn này")
        return FileResponse(f, media_type="video/mp4", headers={"Cache-Control": "no-store"})

    @app.get("/api/editor/stories/{sid}/music/{name}")
    def editor_story_music(sid: str, name: str):
        _get(sid)      # câu chuyện không có: 404, không phải lỗi 500
        m = story_mod.editor_pack_ready(store(), sid)
        music = (m or {}).get("music")
        path = story_mod._music_path(music.get("path")) if music else ""      # chỉ nhạc trong thư mục nhạc của iContent
        if not path or music.get("name") != name:
            raise HTTPException(404, "Không có nhạc này")
        return FileResponse(path, headers={"Cache-Control": "no-store"})


def run_story_job(st, payload: dict) -> Path:
    """Hàng đợi chung gọi khi tới lượt dựng một video kể chuyện."""
    cfg = st.cfg()
    return story_mod.render_story(story_mod.StoryStore(st.work() / ".stories"), payload["sid"], cfg, Path(cfg.output_dir))


__all__ = ["mount", "run_story_job", "Tasks", "ROOT"]
