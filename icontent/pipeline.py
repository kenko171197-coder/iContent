"""Điều phối các bước. Mỗi bước ghi file vào workspace/<job>/ và được bỏ qua nếu đã có kết quả.

  download -> audio -> separate -> hardsub -> asr -> speakers -> translate -> tts -> clean -> render
               (tách nhạc)  (dò sub gốc)  (+OCR)  (ai nói gì)  (+phân tích) (+chọn giọng) (xóa sub gốc)

Sửa tay rồi chạy lại:
  - Web Studio (python -m icontent ui): sửa từng câu, nghe thử, lồng lại, chọn vùng che sub.
  - Sửa bản dịch / timeline trong subs.<lang>.srt (Subtitle Edit, Aegisub...) rồi chạy lại job:
    tool tự nhận file srt mới hơn và lồng tiếng lại đúng các câu đã đổi.
  - Sửa câu gốc tiếng Trung trong segments.json rồi chạy  --from translate
  - Đổi giọng 1 câu: điền "voice" trong segments.json
Tùy chọn riêng của từng video nằm trong workspace/<job>/options.json (ghi đè config.yaml).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .config import merge_dicts, with_overrides
from .download import fetch
from .models import Segment, load_segments, read_srt, save_segments, write_srt
from .util import Cancelled, check_cancel, copy_replace, emit, ffmpeg, log, safe_name, short_hash, stage

STAGES = ["download", "audio", "separate", "hardsub", "asr", "translate", "tts", "render"]


def _forced(from_stage: str | None) -> set[str]:
    if not from_stage:
        return set()
    if from_stage not in STAGES:
        raise ValueError(f"--from phải là một trong: {', '.join(STAGES)}")
    return set(STAGES[STAGES.index(from_stage):])


def job_options(job: Path) -> dict:
    p = job / "options.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_job_options(job: Path, opts: dict) -> None:
    """Không đổi gì thì không ghi: thời điểm của file này là cách biết video đã cũ hay chưa."""
    text = json.dumps(opts or {}, ensure_ascii=False, indent=1)
    p = job / "options.json"
    if not p.exists() or p.read_text(encoding="utf-8") != text:
        p.write_text(text, encoding="utf-8")


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _import_srt_edits(job: Path, segs: list[Segment], lang: str) -> list[Segment]:
    srt, seg_path = job / f"subs.{lang}.srt", job / "segments.json"
    if not (srt.exists() and seg_path.exists()) or srt.stat().st_mtime <= seg_path.stat().st_mtime + 0.5:
        return segs
    items = read_srt(srt)
    active = [s for s in segs if s.trans.strip()]
    log("edit", f"Phát hiện {srt.name} đã được sửa -> cập nhật bản dịch/timeline")
    if len(items) == len(active):
        for s, (st, en, tx) in zip(active, items):
            s.start, s.end, s.trans = round(st, 3), round(en, 3), tx.replace("\n", " ").strip()
        return segs
    # số câu thay đổi (gộp/tách) -> dựng lại danh sách, ghép câu gốc theo độ chồng thời gian
    new = []
    for i, (st, en, tx) in enumerate(items, 1):
        src = [s for s in segs if min(en, s.end) - max(st, s.start) > 0.1]
        new.append(Segment(id=i, start=round(st, 3), end=round(en, 3), text=" ".join(s.text for s in src),
                           trans=tx.replace("\n", " ").strip(), gender=src[0].gender if src else "",
                           speaker=src[0].speaker if src else "",
                           ocr=" ".join(s.ocr for s in src if s.ocr)))
    return new


def _dub_key(segs: list[Segment], cfg, clone_ref: Path | None) -> str:
    t = cfg.tts
    return short_hash(
        json.dumps([[s.id, s.start, s.end, s.trans, s.voice, s.gender, s.speaker, s.rec] for s in segs], ensure_ascii=False),
        t.engine, t.voice, t.vieneu_voice, t.ref_audio, t.rate, str(t.max_speed), str(t.hard_max_speed),
        t.voice_mode, t.male_voice, t.female_voice, str(clone_ref or ""), t.get("vox_voice") or "", cfg.translate.target_lang,
        json.dumps(t.get("pronounce") or {}, ensure_ascii=False, sort_keys=True),
        json.dumps(t.get("speaker_voices") or {}, ensure_ascii=False, sort_keys=True),
    )


def hardsub_box_for(job: Path, cfg, meta: dict, force: bool = False) -> list[float] | None:
    """Vùng sub gốc cần che theo edit.blur_hardsub: on = hardsub_box đặt sẵn, auto = OCR tự dò."""
    from . import hardsub

    mode = hardsub.hardsub_mode(cfg.edit.blur_hardsub)
    if mode == "on":
        return [float(v) for v in cfg.edit.hardsub_box]
    if mode == "auto":
        if not hardsub.available():
            if force:
                log("hardsub", "Chưa cài OCR (pip install rapidocr) -> không tự dò được phụ đề gốc")
            return None
        stage("hardsub")
        return hardsub.detect(job, float(meta.get("duration") or 0), force=force)["box"]
    return None


def output_name(meta: dict) -> str:
    return f"{meta['platform']}_{safe_name(str(meta['id']), 24)}_{safe_name(meta.get('title') or '', 50)}"


def _clean_band(job: Path, cfg, meta: dict, box: list[float] | None) -> Path | None:
    """Dải sub đã xóa chữ khi hardsub_mode=inpaint. Thiếu OCR/không có câu nào -> None (render dùng cách làm mờ)."""
    if not box or cfg.edit.get("hardsub_mode") != "inpaint":
        return None
    from . import hardsub
    if not hardsub.available():
        log("clean", "Chưa cài OCR (pip install rapidocr) -> dùng cách làm mờ thay vì xóa sub")
        return None
    from .clean import clean_video
    stage("clean")
    return clean_video(job, meta, box, hardsub.ocr_timeline(job, meta, box))


def _ensure_translator(cfg):
    """Chưa dùng được nhà cung cấp đã chọn -> ưu tiên dịch offline trên máy, không có thì Google miễn phí,
    để bản miễn phí vẫn chạy trọn vẹn. Luôn báo rõ đang dùng gì."""
    from .keys import translator_ready
    from .offline import ready

    tc = cfg.translate
    if translator_ready(tc):
        return cfg
    why = ("Chưa bật được dịch offline" if tc.provider == "offline" else "Chưa cài cổng AI qua MCP" if tc.provider == "mcp"
           else f"Chưa có API key cho {tc.provider}")
    if tc.provider in ("claude", "openai") and os.environ.get("GEMINI_API_KEY"):
        # đã có key Gemini (gói miễn phí cũng dịch được): hiểu ngữ cảnh, xưng hô, gợi ý tiêu đề, hơn hẳn dịch offline
        from .translate import GEMINI_AUTO, GEMINI_HOST
        log("translate", f"{why} -> dịch bằng Gemini (đã có key Gemini)")
        return with_overrides(cfg, {"translate": {"provider": "openai", "model": GEMINI_AUTO, "api_key_env": "GEMINI_API_KEY",
                                                  "base_url": f"https://{GEMINI_HOST}/v1beta/openai/"}})
    if tc.provider != "offline" and ready(tc.get("offline_model")):
        log("translate", f"{why} -> dịch offline trên máy (không có xưng hô theo ngữ cảnh và gợi ý tiêu đề). "
                         "Kết nối AI trong mục Cài đặt để dịch hay hơn.")
        return with_overrides(cfg, {"translate": {"provider": "offline"}})
    log("translate", f"{why} -> dịch bằng Google miễn phí (kém tự nhiên hơn, không có xưng hô theo ngữ cảnh). "
                     "Tải Dịch offline (Cài đặt > Mô-đun AI miễn phí) hoặc kết nối AI để chắc chắn dịch được.")
    return with_overrides(cfg, {"translate": {"provider": "google"}})


PROVIDER_NAMES = {"claude": "Claude", "mcp": "AI qua MCP", "offline": "dịch offline", "google": "Google dịch"}


def provider_name(tc) -> str:
    if tc.provider == "openai":
        u = str(tc.get("base_url") or "")
        return "Gemini" if "generativelanguage" in u else "DeepSeek" if "deepseek" in u else "AI tương thích OpenAI"
    return PROVIDER_NAMES.get(tc.provider, tc.provider)


class TranslateFailed(RuntimeError):
    """Mọi cách dịch đều lỗi. Lời nhắn đã là tiếng Việt, nói rõ làm gì tiếp (fixes.py nhận ra qua chữ "Không dịch được")."""


def fallback_chain(cfg) -> list:
    """Cách dịch sẽ thử lần lượt khi cách trước lỗi giữa chừng: AI đã chọn -> dịch offline trên máy (nếu đã tải) -> Google miễn phí.
    Gemini gói miễn phí hay quá tải, hết hạn mức trong ngày; Google hay chặn: không để cả video dừng ở bước dịch vì một nguồn."""
    from .offline import ready
    tc = cfg.translate
    chain = [cfg]
    if tc.provider != "offline" and ready(tc.get("offline_model")):
        chain.append(with_overrides(cfg, {"translate": {"provider": "offline"}}))
    if tc.provider != "google":
        chain.append(with_overrides(cfg, {"translate": {"provider": "google"}}))
    return chain


AI_RETRY_WAIT = 20      # giây chờ trước khi thử lại AI đang quá tải


def _transient(e: Exception) -> bool:
    """Lỗi AI kiểu tạm thời (quá tải, giới hạn tần suất, hết giờ chờ): đợi một lát thường hết. Sai key, hết tiền thì không."""
    m = (str(e) + " " + type(e).__name__).lower()
    if any(w in m for w in ("401", "403", "api key", "invalid", "insufficient", "billing", "quota exceeded", "credit")):
        return False
    return any(w in m for w in ("overload", "quá tải", "429", "503", "500", "502", "504", "rate limit", "timeout", "timed out",
                                "unavailable", "internalservererror", "apitimeouterror", "connection"))


def translate_resilient(segs, cfg, meta: dict, only: set, context: dict | None = None):
    """Dịch các câu trong `only`; cách đang dùng lỗi thì dịch tiếp các câu còn thiếu bằng cách sau. Trả về cfg đã dịch xong."""
    from .offline import ready
    from .translate import translate_segments

    chain = fallback_chain(cfg)
    errors: list[tuple[str, str]] = []
    waited = False
    for i, c in enumerate(chain):
        todo = {s.id for s in segs if s.id in only and not s.trans.strip()}
        if not todo:
            return c
        try:
            try:
                translate_segments(segs, c, meta, only=todo, context=context if i == 0 else None)
            except Cancelled:
                raise
            except Exception as e:      # noqa: BLE001
                # AI quá tải thường chỉ một lúc (gặp 2 lần trong một buổi 11/2026: cả 3 model Flash quá tải rồi một model treo):
                # chờ rồi thử lại AI một lần trước khi chuyển sang dịch offline, câu dịch AI vừa khung hơn hẳn, nhất là tiếng nước ngoài
                if waited or c.translate.provider not in ("claude", "openai") or not _transient(e):
                    raise
                waited = True
                log("translate", f"{provider_name(c.translate)} đang quá tải: chờ {AI_RETRY_WAIT} giây rồi thử lại một lần")
                for _ in range(AI_RETRY_WAIT):
                    check_cancel()
                    import time as _t
                    _t.sleep(1)
                todo = {s.id for s in segs if s.id in only and not s.trans.strip()}
                translate_segments(segs, c, meta, only=todo, context=context if i == 0 else None)
            if errors:
                log("translate", f"Đã dịch xong bằng {provider_name(c.translate)}. Nên đọc lại bản dịch trong Studio trước khi đăng.")
            return c
        except Cancelled:
            raise
        except Exception as e:      # noqa: BLE001 — thử cách sau, giữ lời giải thích của từng cách
            msg = friendly_translate_error(e, c.translate.provider)
            errors.append((provider_name(c.translate), msg))
            left = sum(1 for s in segs if s.id in only and not s.trans.strip())
            if i + 1 < len(chain):
                log("translate", f"{provider_name(c.translate)} lỗi: {msg} -> dịch tiếp {left} câu bằng {provider_name(chain[i + 1].translate)}")
            else:
                log("translate", f"{provider_name(c.translate)} lỗi: {msg}")
    head, first = errors[0]
    text = f"Không dịch được bằng {head}: {first}"
    for name, m in errors[1:]:
        text += f" Đã thử {name}: {m}"
    if not ready(cfg.translate.get("offline_model")):
        text += (" Cách chắc chắn nhất: tải Dịch offline miễn phí (khoảng 1,2 GB, Cài đặt > Mô-đun AI miễn phí), "
                 "Studio566 sẽ tự dịch ngay trên máy khi AI hay Google lỗi.")
    raise TranslateFailed(text)


def shorten_resilient(segs, targets: dict, cfg, meta: dict, context: dict | None = None) -> dict:
    """Rút gọn câu đọc không kịp. AI lỗi thì thử dịch offline (Google không rút gọn được). Hết cách thì để nguyên, không chặn video."""
    from .translate import shorten_segments
    err = None
    for i, c in enumerate(fallback_chain(cfg)):
        if c.translate.provider == "google":
            continue
        try:
            return shorten_segments(segs, targets, c, meta, context if i == 0 else None)
        except Cancelled:
            raise
        except Exception as e:      # noqa: BLE001 — thử cách sau
            err = e
            log("tts", f"Rút gọn bằng {provider_name(c.translate)} lỗi: {friendly_translate_error(e, c.translate.provider)}")
    if err is not None:
        raise err
    return {}


def friendly_translate_error(e: Exception, provider: str) -> str:
    """Lỗi dịch -> câu tiếng Việt nói rõ phải làm gì tiếp theo."""
    # Gemini (cổng tương thích OpenAI) trả lỗi dạng danh sách: thư viện openai chỉ ghi "Error code: 400", lý do thật nằm trong phần thân
    extra = ""
    resp = getattr(e, "response", None)
    try:
        extra = (getattr(resp, "text", "") or "")[:3000] if resp is not None else ""
    except Exception:      # noqa: BLE001 — phản hồi dạng luồng chưa đọc: bỏ qua
        extra = ""
    m = (str(e) + " " + extra + " " + repr(getattr(e, "body", "") or "")[:2000]).lower()
    has = lambda *ws: any(w in m for w in ws)
    if provider == "google" and has("too many requests", "429", "captcha", "request limit", "server error"):
        return ("Google đang tạm chặn máy này vì dịch nhiều. Tải Dịch offline (Cài đặt > Mô-đun AI miễn phí, không cần key) hoặc "
                "kết nối AI, rồi bấm Thử lại. Cũng có thể mở Studio và tự điền bản dịch.")
    if provider == "offline" and has("connection", "refused", "timed out", "timeout", "not found", "404", "500", "unreachable"):
        return "Dịch offline chưa chạy được. Vào Cài đặt > Mô-đun AI miễn phí, bấm Dịch thử để kiểm tra, rồi bấm Thử lại."
    if provider == "google" and has("deep_translator", "no module"):
        return "Thiếu thư viện dịch miễn phí: pip install deep-translator. Hoặc vào Cài đặt để kết nối AI."
    if has("401", "invalid x-api-key", "invalid api key", "authentication", "unauthorized", "incorrect api key",
           "api key not valid", "api_key_invalid", "valid api key", "api key không hợp lệ"):
        return "API key không đúng hoặc đã hết hạn. Vào Cài đặt, dán lại key rồi bấm Dịch thử."
    if has("402", "insufficient", "credit balance", "quota", "billing"):
        return "Tài khoản AI đã hết hạn mức hoặc hết tiền. Nạp thêm, hoặc vào Cài đặt chọn nhà cung cấp khác."
    if has("429", "rate limit", "too many requests", "overloaded"):
        return "Dịch vụ AI đang quá tải hoặc giới hạn tần suất. Đợi một lát rồi bấm Thử lại."
    if has("connection", "timed out", "timeout", "getaddrinfo", "unreachable", "refused"):
        return f"Không kết nối được tới dịch vụ dịch ({provider}). Kiểm tra mạng rồi bấm Thử lại."
    return f"Dịch lỗi ({provider}): {str(e)[:300]}"


TARGET_SUFFIX = {"9:16": "9x16", "16:9": "16x9", "1:1": "1x1"}


def options_hash(opts: dict | None) -> str:
    return short_hash(json.dumps(opts or {}, ensure_ascii=False, sort_keys=True))


def is_fresh(job: Path, name: str = "final.mp4") -> bool:
    """Bản đã dựng còn đúng với những gì đang có. Tùy chọn so theo nội dung với đúng bộ tùy chọn lúc bắt đầu dựng: tùy chọn được đọc ngay từ
    đầu lượt, sửa trong lúc đang lồng tiếng thì không vào bản này, còn so thời gian file thì tưởng là đã có. Đổi rồi đổi lại thì cũng không bị coi là cũ."""
    f = job / name
    if not f.exists():
        return False
    watch = [job / "segments.json", job / "speakers.json", job / "dub.wav", job / "hardsub.json"]
    used = (load_json(job / "render.json") or {}).get("options") if (job / "render.json").exists() else None
    if used is None:      # video dựng từ bản cũ chưa ghi lại tùy chọn
        watch.append(job / "options.json")
    elif used != options_hash(job_options(job)):
        return False
    newer = [p.stat().st_mtime for p in watch if p.exists()]
    return not newer or max(newer) <= f.stat().st_mtime + 1


_is_fresh = is_fresh


def run_job(src: str, cfg, from_stage: str | None = None, overrides: dict | None = None,
            targets: list[str] | None = None, clips: list | None = None, profiles: list[str] | None = None,
            clip_profile: str = "", editor_base: bool = False) -> Path:
    """overrides: tùy chọn riêng cho video này (lưu vào options.json của job).
    targets: các khung hình cần xuất thêm ("9:16", "16:9", "1:1").
    clips: các đoạn [[đầu, cuối], ...] (giây theo video gốc) cần xuất thành từng clip riêng.
    profiles: xuất thêm theo nền tảng (profiles.PROFILES). Nền tảng cùng khung dùng chung một lần dựng.
    clip_profile: clip dùng khung hình của nền tảng này, trống thì theo bản chính.
    editor_base: dựng thêm editor_base.mp4 cho trình dựng: như bản chính nhưng không ghi phụ đề vào hình (xem editor.py)."""
    force = _forced(from_stage)
    stage("download")
    job = fetch(src, cfg, force="download" in force)
    was_fresh = _is_fresh(job)
    meta = json.loads((job / "meta.json").read_text(encoding="utf-8"))
    emit("job", job=job.name, title=meta.get("title", ""))
    opts = job_options(job)
    if overrides:
        opts = merge_dicts(opts, overrides)
        save_job_options(job, opts)
    if opts:
        cfg = with_overrides(cfg, opts)
    log("job", f"{job.name}: {meta.get('title', '')[:70]} | {meta['width']}x{meta['height']} {meta['duration']:.1f}s")
    if not meta.get("has_audio"):
        raise RuntimeError("Video không có âm thanh — không có gì để nhận dạng/lồng tiếng")
    lang = cfg.translate.target_lang
    do_translate = cfg.translate.provider != "none"
    do_dub = bool(cfg.tts.enabled) and do_translate
    if do_translate:
        cfg = _ensure_translator(cfg)
        if lang != "vi" and cfg.translate.provider in ("offline", "google"):
            # đo thật 11/2026 (video 139 giây sang tiếng Anh): Gemini cho giọng đọc nhanh 1,09 lần, dịch offline 1,38 lần và tràn 9 giây
            log("translate", "Dịch tiếng nước ngoài bằng dịch offline/Google: câu thường dài hơn khung thời gian nên giọng phải đọc nhanh. "
                             "Kết nối AI (Gemini có gói miễn phí) để câu vừa khung, đọc tự nhiên hơn.")
    if do_dub:
        from .voice import engine_for
        eng = engine_for(cfg)
        if eng != cfg.tts.engine:
            from .langs import name_vi
            nm = name_vi(lang)
            log("tts", f"Lồng {nm[:1].lower() + nm[1:]}: dùng bộ đọc "
                       + {"vox": "nhiều thứ tiếng trên máy", "edge": "Microsoft (qua mạng)", "vieneu": "VieNeu"}.get(eng, eng)
                       + (". Tải Giọng đọc nhiều thứ tiếng (Cài đặt > Mô-đun AI miễn phí) để đọc trên máy, không lo bị chặn."
                          if eng == "edge" and lang != "vi" else ""))
            cfg = with_overrides(cfg, {"tts": {"engine": eng}})

    # ---- audio
    audio = job / "audio.wav"
    if "audio" in force or not audio.exists():
        stage("audio")
        log("audio", "Tách âm thanh ...")
        ffmpeg(["-i", "source.mp4", "-vn", "-ac", "2", "-ar", "44100", "audio.wav"], cwd=job)

    # ---- separate (chỉ cần khi lồng tiếng)
    sep = None
    tr_cfg = cfg      # cách dịch chạy được ở lượt này (AI lỗi giữa chừng thì là dịch offline): bước rút gọn dùng đúng cách đó
    if do_dub and cfg.audio.separate != "off":
        if "separate" in force:
            for f in ("vocals.wav", "bgm.wav"):
                (job / f).unlink(missing_ok=True)
        from .separate import separate
        if not ((job / "vocals.wav").exists() and (job / "bgm.wav").exists()):
            stage("separate")
        sep = separate(audio, job, cfg.audio)

    # ---- hardsub: dò vùng phụ đề gốc (để che + để OCR hỗ trợ nhận dạng)
    hs_box = hardsub_box_for(job, cfg, meta, force="hardsub" in force)

    # ---- asr (+ ghép với phụ đề gốc nếu có)
    seg_path, words_path = job / "segments.json", job / "words.json"
    if "asr" in force or not seg_path.exists():
        stage("asr")
        redo_words = from_stage in ("download", "audio", "separate", "asr") or not words_path.exists()
        if redo_words:
            from .asr import transcribe_words
            ffmpeg(["-i", (sep[0] if sep else audio).name, "-ac", "1", "-ar", "16000", "asr.wav"], cwd=job)
            log("asr", "Nhận dạng giọng nói ...")
            words = transcribe_words(job / "asr.wav", cfg.asr)
            if sep and cfg.asr.get("gap_retry", True):
                # bộ tách giọng có thể làm mất lời ở đoạn nhạc nền to: nghe lại các khoảng trống dài trên tiếng gốc
                from .asr import find_gaps, transcribe_gaps
                ffmpeg(["-i", audio.name, "-ac", "1", "-ar", "16000", "asr_orig.wav"], cwd=job)
                total = float(meta.get("duration") or 0)
                gaps = find_gaps(words, total, job / "asr_orig.wav")
                if gaps:
                    log("asr", f"{len(gaps)} đoạn dài chưa nghe ra lời mà vẫn có tiếng (thường do nhạc nền to): nghe lại trên tiếng gốc")
                    try:
                        extra = transcribe_gaps(job / "asr_orig.wav", gaps, cfg.asr, total)
                    except Cancelled:
                        raise
                    except Exception as e:      # noqa: BLE001 — bước bổ sung: lỗi thì giữ kết quả cũ
                        log("asr", f"Nghe lại lỗi, bỏ qua: {str(e)[:200]}")
                        extra = []
                    if extra:
                        words = sorted(words + [(round(float(a), 3), round(float(b), 3), w, k) for a, b, w, k in extra],
                                       key=lambda x: x[0])
            words_path.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
        words = [tuple(w) for w in json.loads(words_path.read_text(encoding="utf-8"))]
        from .asr import resegment
        segs = None
        if hs_box and cfg.asr.get("ocr_align", True):
            from . import hardsub
            if hardsub.available():
                from .align import fuse
                events = hardsub.ocr_timeline(job, meta, hs_box)
                if events:
                    segs = fuse(words, events, cfg.asr)
                    log("asr", f"Ghép với phụ đề gốc: {len(segs)} câu ({sum(1 for s in segs if s.ocr)} có chữ OCR)")
        if segs is None:
            segs = resegment(words, cfg.asr)
        if not segs:
            raise RuntimeError("Video này không có lời thoại nên không có gì để dịch và lồng tiếng (thường là video chỉ có nhạc). Hãy chọn video có người nói.")
        save_segments(seg_path, segs)
        write_srt(job / "subs.zh.srt", [(s.start, s.end, s.ocr or s.text) for s in segs])
        (job / "voice.json").unlink(missing_ok=True)
        (job / "speakers.json").unlink(missing_ok=True)
        log("asr", f"{len(segs)} câu -> subs.zh.srt")
    segs = load_segments(seg_path)

    # ---- ai nói câu nào: làm trước khi dịch vì câu gộp lời 2 người phải được tách rồi mới dịch
    voice_src = sep[0] if sep else (job / "asr.wav" if (job / "asr.wav").exists() else audio)
    use_speakers = do_dub and cfg.tts.voice_mode == "auto" and cfg.tts.get("diarize", True)
    if use_speakers and not (job / "speakers.json").exists() and not any(s.trans.strip() for s in segs):
        from . import speakers
        if speakers.available():
            stage("speakers")
            try:
                words = [tuple(w) for w in load_json(words_path) or []]
                segs, info = speakers.diarize(segs, words, voice_src)
                speakers.save(job, info)
                save_segments(seg_path, segs)
                write_srt(job / "subs.zh.srt", [(s.start, s.end, s.ocr or s.text) for s in segs])
            except Cancelled:
                raise
            except Exception as e:   # bước phụ: lỗi thì vẫn lồng tiếng một giọng như cũ
                log("speakers", f"Bỏ qua nhận diện người nói: {str(e)[:200]}")

    # ---- translate (+ phân tích nội dung: xưng hô, tên riêng, tiêu đề/hashtag)
    ctx_path = job / "context.json"
    context = load_json(ctx_path)
    if do_translate:
        before_srt = [(s.start, s.end, s.trans) for s in segs]
        segs = _import_srt_edits(job, segs, lang)
        edits_imported = before_srt != [(s.start, s.end, s.trans) for s in segs]
        if cfg.translate.provider in ("claude", "openai", "mcp") and cfg.translate.analyze and \
                ("translate" in force or context is None):
            stage("analyze")
            from .translate import analyze_video
            try:
                context = analyze_video(segs, cfg, meta)
                if context:
                    ctx_path.write_text(json.dumps(context, ensure_ascii=False, indent=1), encoding="utf-8")
            except Cancelled:
                raise
            except Exception as e:  # không chặn cả video vì bước phụ
                log("analyze", f"Bỏ qua phân tích: {e}")
        old_trans = None
        if "translate" in force:
            old_trans = {s.id: s.trans for s in segs}     # dịch lại lỗi thì trả nguyên bản cũ, kể cả câu đã sửa tay
            for s in segs:
                s.trans = ""
        missing = [s for s in segs if not s.trans.strip()]
        if missing:
            stage("translate")
            try:
                if len(missing) != len(segs):      # chỉ dịch câu còn thiếu, giữ nguyên câu đã sửa tay
                    log("translate", f"Dịch {len(missing)} câu còn thiếu")
                tr_cfg = translate_resilient(segs, cfg, meta, {s.id for s in missing}, context)
            except Cancelled:
                if old_trans is not None:
                    for s in segs:
                        s.trans = old_trans.get(s.id, s.trans)
                    save_segments(seg_path, segs)
                raise
            except Exception as e:
                if old_trans is not None:
                    for s in segs:
                        s.trans = old_trans.get(s.id, s.trans)
                # lần đầu dịch: giữ phần đã dịch để lần sau chỉ dịch tiếp các câu còn thiếu
                save_segments(seg_path, segs)
                if isinstance(e, TranslateFailed):
                    raise
                raise RuntimeError(friendly_translate_error(e, cfg.translate.provider)) from e
        if missing or edits_imported:
            save_segments(seg_path, segs)
            write_srt(job / f"subs.{lang}.srt", [(s.start, s.end, s.trans) for s in segs])

    # ---- tts (+ chọn giọng nam/nữ theo giọng gốc / clone giọng)
    dub = None
    if do_dub:
        mode = cfg.tts.voice_mode
        clone_ref = None
        if mode in ("auto", "per_line"):
            vj = load_json(job / "voice.json")
            if vj is None or vj.get("mode") != mode or "tts" in force or any(not s.gender for s in segs):
                stage("voice")
                from .voice import assign_genders
                res = assign_genders(job, segs, voice_src, cfg, hint=(context or {}).get("narrator_gender", ""))
                res["mode"] = mode
                (job / "voice.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
                save_segments(seg_path, segs)
            if mode == "auto" and (job / "speakers.json").exists():
                from . import speakers
                genders = [s.gender for s in segs]
                vmap = speakers.assign_voices(job, segs, voice_src, cfg, hint=(context or {}).get("narrator_gender", ""))
                if vmap:
                    cfg = with_overrides(cfg, {"tts": {"speaker_voices": vmap}})
                if genders != [s.gender for s in segs]:
                    save_segments(seg_path, segs)
        elif mode == "clone" and cfg.tts.engine == "vieneu" and not cfg.tts.ref_audio:
            from .voice import pick_clone_ref
            clone_ref = pick_clone_ref(job, segs, voice_src)
        dub = job / "dub.wav"
        key_file = job / "dub.key"
        key = _dub_key(segs, cfg, clone_ref)
        if "tts" in force or not dub.exists() or not key_file.exists() or key_file.read_text() != key:
            stage("tts")
            from .tts import build_dub
            _, n_failed = build_dub(segs, job, cfg, meta, clone_ref=clone_ref,
                                    shorten_fn=lambda t: shorten_resilient(segs, t, tr_cfg, meta, context))
            save_segments(seg_path, segs)
            write_srt(job / f"subs.{lang}.srt", [(s.start, s.end, s.trans) for s in segs])
            if n_failed:
                key_file.unlink(missing_ok=True)   # lần chạy sau sẽ đọc bù các câu còn thiếu
            else:
                key_file.write_text(_dub_key(segs, cfg, clone_ref))

    # ---- xóa sub gốc + render
    band = _clean_band(job, cfg, meta, hs_box)
    stage("render")
    from .render import render
    if dub is not None:
        bed, bed_is_bgm = (sep[1], True) if sep else (audio, False)
    else:
        bed, bed_is_bgm = audio, False
    only_extra = bool(targets or clips or profiles or editor_base) and from_stage is None and was_fresh and _is_fresh(job)
    if only_extra:      # chỉ xuất thêm: bản chính vẫn mới, không cần dựng lại
        log("render", "Bản chính vẫn mới, chỉ xuất thêm")
        final = job / "final.mp4"
    else:
        final = render(job, segs, meta, cfg, dub, bed, bed_is_bgm, hardsub_box=hs_box, clean_band=band)
        info = load_json(job / "render.json") or {}
        info["options"] = options_hash(opts)
        from .editor import render_signature
        info["cfg"] = render_signature(cfg)      # cả cài đặt chung: bản nền cho trình dựng chỉ dùng lại bản chính khi cùng cài đặt
        (job / "render.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")

    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{output_name(meta)}.mp4"
    # chỉ dựng bản nền cho trình dựng mà bản chính không đổi: không chép lại vài trăm MB vào output, file đó có thể đang mở trong trình phát
    if not (only_extra and editor_base and not (targets or clips or profiles)):
        copy_replace(final, dst)
        copy_replace(job / "final.srt", dst.with_suffix(".srt"))
        pub = (context or {}).get("publish") or {}
        if pub:
            txt = f"{pub.get('title', '')}\n\n{pub.get('caption', '')}\n\n{' '.join(pub.get('hashtags') or [])}\n"
            dst.with_suffix(".txt").write_text(txt, encoding="utf-8")
        if (job / "cover.jpg").exists():
            copy_replace(job / "cover.jpg", dst.with_suffix(".jpg"))

    # ---- xuất thêm các khung hình khác (TikTok / YouTube / Facebook); giữ lại srt của khung chính
    main_srt = (job / "final.srt").read_bytes()
    extra: list[str] = list((load_json(job / "output.json") or {}).get("extra") or []) if only_extra else []
    from .profiles import PROFILES, render_key

    def save_output() -> None:
        (job / "output.json").write_text(json.dumps({"video": str(dst.resolve()), "extra": extra}, ensure_ascii=False), encoding="utf-8")

    def add_extra(path: Path) -> None:
        if str(path.resolve()) not in extra:
            extra.append(str(path.resolve()))
        save_output()

    # ghi ngay từ đây và sau mỗi bản: hủy giữa chừng thì danh sách vẫn đúng (bản chính mới, không kèm bản cũ, đủ các bản đã xong)
    save_output()
    temp_outputs: list[Path] = []
    try:
        made = {render_key(cfg.edit): job / "final.mp4"}      # khung đã có sẵn thì chép, không dựng lại
        for pid in profiles or []:
            prof = PROFILES.get(pid)
            if not prof:
                continue
            check_cancel()
            k = render_key(prof["edit"])
            if k not in made:
                stage("render")
                log("render", f"Xuất bản {prof['name']}")
                render(job, segs, meta, with_overrides(cfg, {"edit": prof["edit"]}), dub, bed, bed_is_bgm, hardsub_box=hs_box, clean_band=band,
                       out_name=f"final_{pid}.mp4")
                made[k] = job / f"final_{pid}.mp4"
                temp_outputs.append(made[k])
            prof_dst = dst.with_name(f"{dst.stem}_{pid}.mp4")
            copy_replace(made[k], prof_dst)
            add_extra(prof_dst)
        for t in targets or []:
            if t not in TARGET_SUFFIX or t == cfg.edit.aspect:
                continue
            check_cancel()
            stage("render")
            log("render", f"Xuất thêm bản {t}")
            name = f"final_{TARGET_SUFFIX[t]}.mp4"
            tcfg = with_overrides(cfg, {"edit": {"aspect": t}})
            render(job, segs, meta, tcfg, dub, bed, bed_is_bgm, hardsub_box=hs_box, clean_band=band, out_name=name)
            temp_outputs.append(job / name)
            extra_dst = dst.with_name(f"{dst.stem}_{TARGET_SUFFIX[t]}.mp4")
            copy_replace(job / name, extra_dst)
            add_extra(extra_dst)
        for k, rng in enumerate(clips or [], 1):
            check_cancel()
            from .editing import complement
            a, b = float(rng[0]), float(rng[1])
            stage("render")
            log("render", f"Xuất clip {k}/{len(clips)}: {a:.1f}s đến {b:.1f}s")
            sec = lambda x: f"{x:.1f}".rstrip("0").rstrip(".").replace(".", "_")     # noqa: E731
            tag = f"clip_{sec(a)}s_{sec(b)}s"
            ccfg = with_overrides(cfg, {"edit": PROFILES[clip_profile]["edit"]}) if clip_profile in PROFILES else cfg
            render(job, segs, meta, ccfg, dub, bed, bed_is_bgm, hardsub_box=hs_box, clean_band=band, out_name=f"{tag}.mp4",
                   cuts=complement([[a, b]], float(meta.get("duration") or 0)) + list(cfg.edit.get("cuts") or []), with_cards=False)
            if clip_profile in PROFILES:
                tag += f"_{clip_profile}"
                shutil.move(job / f"{tag.rsplit('_', 1)[0]}.mp4", job / f"{tag}.mp4")
            clip_dst = dst.with_name(f"{dst.stem}_{tag}.mp4")
            copy_replace(job / f"{tag}.mp4", clip_dst)
            copy_replace(job / "final.srt", clip_dst.with_suffix(".srt"))
            (job / f"{tag}.mp4").unlink(missing_ok=True)
            add_extra(clip_dst)
        if editor_base:
            from .editor import BASE, BASE_INFO, BASE_KEY, BASE_SRT, render_signature
            check_cancel()
            stage("render")
            log("render", "Dựng bản không phụ đề cho trình dựng")
            (job / BASE_KEY).unlink(missing_ok=True)      # hủy giữa chừng thì không được tính là bản nền còn đúng
            sig = render_signature(cfg)
            main_info = load_json(job / "render.json") or {}
            # dùng lại bản chính chỉ khi chắc chắn nó không có phụ đề trên hình và dựng đúng cài đặt bây giờ. Không dựa vào cfg.edit.burn_subs:
            # vừa tắt ghi phụ đề trong Cài đặt thì cfg nói không, nhưng final.mp4 dựng từ trước vẫn có phụ đề
            if not main_info.get("sub") and main_info.get("cfg") == sig and not cfg.edit.burn_subs:
                copy_replace(final, job / BASE)      # chép thật, không hard link: final.mp4 có lúc bị ghi đè tại chỗ khi đang bị khóa
                (job / BASE_INFO).write_text(json.dumps(main_info, ensure_ascii=False), encoding="utf-8")
            else:
                render(job, segs, meta, with_overrides(cfg, {"edit": {"burn_subs": False}}), dub, bed, bed_is_bgm, hardsub_box=hs_box, clean_band=band, out_name=BASE)
            # render vừa ghi final.srt theo thời gian của bản nền (tốc độ, đoạn cắt có thể khác bản chính): giữ riêng một bản cho trình dựng
            copy_replace(job / "final.srt", job / BASE_SRT)      # chép thật: ngay dưới đây final.srt bị ghi lại tại chỗ
            (job / BASE_KEY).write_text(json.dumps({"options": options_hash(opts), "cfg": sig}), encoding="utf-8")
    finally:
        (job / "final.srt").write_bytes(main_srt)      # kể cả khi hủy: phụ đề chính không bị thay bằng phụ đề của clip
        for f in temp_outputs:      # đã có bản trong thư mục output, không giữ thêm một bản nữa cho tốn đĩa
            f.unlink(missing_ok=True)
    if cfg.edit.get("auto_qc", True) and not only_extra:
        from . import qc
        stage("qc")
        try:
            qc.run(job, cfg)
        except Cancelled:
            raise
        except Exception as e:      # bước phụ: video đã xong, kiểm định lỗi không được làm hỏng kết quả
            log("qc", f"Bỏ qua kiểm định: {str(e)[:200]}")
    stage("done")
    log("done", f"{dst}")
    return dst


def run_many(srcs: list[str], cfg, from_stage: str | None = None, overrides: dict | None = None) -> int:
    ok, fail = [], []
    for i, s in enumerate(srcs, 1):
        log("batch", f"({i}/{len(srcs)}) {s[:90]}")
        try:
            ok.append(run_job(s, cfg, from_stage, overrides))
        except (KeyboardInterrupt, Cancelled):
            raise
        except Exception as e:
            log("LỖI", f"{s[:90]}\n  {e}")
            fail.append(s)
    if len(srcs) > 1:
        log("batch", f"Xong {len(ok)}/{len(srcs)}. Lỗi: {len(fail)}")
        for s in fail:
            log("batch", f"  lỗi: {s}")
    return 0 if not fail else 1
