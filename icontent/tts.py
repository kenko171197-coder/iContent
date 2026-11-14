"""Lồng tiếng theo timeline: TTS từng câu -> co giãn cho vừa khe thời gian -> ghép thành dub.wav.

Chiến lược căn thời gian (mỗi câu có 'slot' = từ đầu câu tới đầu câu kế tiếp):
  1. Đọc ở tốc độ gốc. Nếu dài hơn slot * max_speed -> nhờ LLM rút gọn câu dịch rồi đọc lại.
  2. Nếu vẫn dài hơn slot -> đọc lại với rate edge-tts cao hơn (tự nhiên hơn atempo).
  3. Phần dư còn lại -> atempo (giữ cao độ), tổng tăng tốc không vượt hard_max_speed.
  4. Đặt câu vào timeline; nếu vẫn tràn thì đẩy câu sau lùi lại (trôi), khoảng lặng phía sau sẽ hút lại độ trôi.
"""
from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path

import numpy as np

from .models import Segment
from .translate import count_units, max_len_for, slot_of
from .util import check_cancel, ffmpeg, log, progress, read_wav, short_hash, wav_duration, watch_download, write_wav

SR = 44100
TRIM = (
    "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.02,"
    "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.06,areverse"
)


def _pct(rate: str) -> float:
    m = re.match(r"([+-]?\d+(?:\.\d+)?)%", (rate or "+0%").strip())
    return float(m.group(1)) if m else 0.0


def _rate_str(pct: float) -> str:
    p = int(round(pct))
    return f"+{p}%" if p >= 0 else f"{p}%"


def _variants(text: str, voice: str, rate: str, fallback_voice: str):
    """Các biến thể gần như không nghe ra khác biệt (âm lượng -1%, rate ±1%, dấu câu) để thử lại
    khi máy chủ Edge trả NoAudioReceived; cuối cùng là giọng dự phòng nếu có cấu hình."""
    p = _pct(rate)
    yield text, voice, rate, "+0%"
    yield text, voice, rate, "-1%"
    yield text, voice, _rate_str(p - 1), "+0%"
    yield text + "..", voice, rate, "+0%"
    yield text, voice, rate, "-2%"
    yield text.replace(",", ""), voice, _rate_str(p + 1), "+0%"
    yield text, voice, rate, "+0%"
    if fallback_voice and fallback_voice != voice:
        yield text, fallback_voice, rate, "+0%"
        yield text, fallback_voice, rate, "-1%"


async def _synth_one(text: str, voice: str, rate: str, out: Path, sem: asyncio.Semaphore, fallback_voice: str) -> None:
    """NoAudioReceived chủ yếu xuất hiện khi Edge giới hạn tần suất -> chờ tăng dần rồi thử biến thể kế."""
    import edge_tts
    from edge_tts.exceptions import NoAudioReceived

    async with sem:
        tmp = out.with_suffix(".part")
        last = None
        for k, (t, v, r, vol) in enumerate(_variants(text, voice, rate, fallback_voice)):
            check_cancel()
            if k:
                await asyncio.sleep(min(2.0 * 2 ** (k - 1), 30.0))
                check_cancel()
            try:
                await edge_tts.Communicate(t, v, rate=r, volume=vol).save(str(tmp))
                if tmp.stat().st_size < 500:
                    raise NoAudioReceived("file TTS rỗng")
                tmp.replace(out)
                if v != voice:
                    log("tts", f"Câu '{text[:30]}' dùng giọng dự phòng {v}")
                return
            except Exception as e:  # NoAudioReceived / lỗi mạng
                last = e
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"edge-tts lỗi với câu '{text[:40]}': {last}")


def synth_many(jobs: list[tuple[str, str, str, Path]], concurrency: int, fallback_voice: str = "") -> list[Path]:
    """Trả về danh sách file KHÔNG tạo được (không ném lỗi để cả video không bị hỏng vì vài câu)."""
    todo = [j for j in jobs if not j[3].exists()]
    if not todo:
        return []

    async def main():
        sem = asyncio.Semaphore(concurrency)
        return await asyncio.gather(*(_synth_one(t, v, r, o, sem, fallback_voice) for t, v, r, o in todo),
                                    return_exceptions=True)

    res = asyncio.run(main())
    check_cancel()
    failed = []
    for (t, _, _, o), r in zip(todo, res):
        if isinstance(r, BaseException):
            log("tts", f"Bỏ qua câu (TTS lỗi): {t[:50]}")
            failed.append(o)
    return failed


class _VieNeu:
    """VieNeu-TTS (local, ONNX/CPU hoặc PyTorch/GPU, Apache-2.0): không giới hạn tần suất, clone được giọng."""

    _inst = None
    lock = threading.RLock()   # web UI: nghe thử giọng có thể chạy song song với hàng đợi

    @classmethod
    def get(cls):
        with cls.lock:
            return cls._get()

    @classmethod
    def _get(cls):
        if cls._inst is None:
            from vieneu import Vieneu

            from .fixes import unsymlink_models

            log("tts", "Nạp VieNeu-TTS ...")
            unsymlink_models()      # bộ đệm cũ tải bằng symlink: ONNX Runtime không đọc được file .data đi kèm
            with watch_download("tts", "Đang tải bộ giọng đọc VieNeu"):
                try:
                    cls._inst = Vieneu()
                except Exception as e:
                    # vừa tải xong lần đầu thì file mới nằm sẵn trong bộ đệm: đổi symlink rồi nạp lại một lần
                    if "external data" not in str(e).lower() or not unsymlink_models():
                        raise
                    log("tts", "Đã sửa cách lưu file mô hình, nạp lại VieNeu-TTS ...")
                    cls._inst = Vieneu()
        return cls._inst

    @classmethod
    def synth(cls, jobs: list[tuple[str, str, str, Path]], ref_audio: str, use_ref_codes: bool = True,
              on_step=None) -> list[Path]:
        """use_ref_codes=False: chỉ lấy âm sắc từ mẫu (hợp khi mẫu là tiếng Trung, đọc ra tiếng Việt)."""
        from . import myvoice
        failed = []
        todo = [j for j in jobs if not j[3].exists()]
        if not todo:
            return failed
        if not ref_audio:      # "me:...": giọng người dùng tự thu (Giọng của tôi)
            gone = sorted({j[1] for j in todo if myvoice.is_mine(j[1]) and myvoice.path_of(j[1]) is None})
            if gone:
                raise RuntimeError("Mẫu \"Giọng của tôi\" đã bị xóa. Chọn giọng khác rồi đọc lại")
        tts = cls.get()
        for n, (text, voice, _rate, out) in enumerate(todo, 1):
            check_cancel()
            try:
                if ref_audio:
                    kw = {"ref_audio": ref_audio, "use_ref_codes": use_ref_codes}
                elif myvoice.is_mine(voice):
                    kw = {"ref_audio": str(myvoice.path_of(voice)), "use_ref_codes": True}
                else:
                    kw = {"voice": voice} if voice else {}
                with cls.lock:
                    audio = tts.infer(text, **kw)
                    tmp = out.with_name(out.stem + ".part.wav")
                    tts.save(audio, str(tmp))
                tmp.replace(out)
            except Exception as e:
                log("tts", f"VieNeu lỗi câu '{text[:40]}': {e}")
                failed.append(out)
            if on_step:
                on_step(n, len(todo))
            if n % 10 == 0:
                log("tts", f"  {n}/{len(todo)}")
        return failed


def _decoded(mp3: Path, tempo: float = 1.0) -> Path:
    """mp3 -> wav mono 44.1k đã cắt khoảng lặng đầu/cuối (+ atempo nếu cần). Có cache."""
    wav = mp3.with_name(f"{mp3.stem}_t{tempo:.3f}.wav")
    if not wav.exists():
        import uuid
        af = TRIM + (f",atempo={tempo:.4f}" if abs(tempo - 1.0) > 1e-3 else "")
        tmp = wav.with_name(f"{wav.stem}.{uuid.uuid4().hex[:6]}.part.wav")      # luồng khác thấy file thì file đã đủ, không phải đang ghi dở
        try:
            ffmpeg(["-i", mp3, "-af", af, "-ar", SR, "-ac", 1, tmp])
            tmp.replace(wav)
        except FileExistsError:
            pass
        finally:
            tmp.unlink(missing_ok=True)
    return wav


def apply_pronounce(text: str, mapping: dict | None) -> str:
    """Thay từ theo từ điển phát âm trước khi đọc (phụ đề vẫn giữ nguyên chữ gốc)."""
    if not mapping:
        return text
    keys = sorted((k for k in mapping if str(k).strip()), key=len, reverse=True)
    if not keys:
        return text
    lower = {str(k).lower(): str(mapping[k]) for k in keys}
    pat = re.compile(r"(?<!\w)(" + "|".join(re.escape(str(k)) for k in keys) + r")(?!\w)", re.IGNORECASE)
    return pat.sub(lambda m: lower.get(m.group(1).lower(), m.group(1)), text)


def speakable(text: str) -> str:
    """Làm sạch câu trước khi đọc (phụ đề giữ nguyên): câu cụt như "Con…", "Hả?!", câu có dấu ba chấm, ký hiệu lạ
    hay làm bộ đọc lỗi hoặc đọc ra tiếng lạ. Câu không còn chữ nào thì trả lại nguyên văn để bộ đọc tự xử lý."""
    t = str(text or "").replace("\u2026", "...").strip()
    t = re.sub(r"\.{2,}", ", ", t)                         # ba chấm giữa câu -> ngắt nhẹ
    t = re.sub(r"[~～*#_^|<>\[\]{}「」『』【】《》\"“”]+", " ", t)
    t = re.sub(r"([!?！？])[!?！？]+", r"\1", t)             # "?!?!" -> "?"
    t = re.sub(r"\s+", " ", t).strip(" ,，、-–—")
    if not any(ch.isalnum() for ch in t):
        return str(text or "").strip()
    if t[-1] not in ".!?。！？":
        t += "."
    return t


class _Line:
    def __init__(self, idx: int, seg: Segment, voice: str, slot: float):
        self.idx, self.seg, self.voice, self.slot = idx, seg, voice, slot
        self.pct = 0.0
        self.mp3: Path | None = None
        self.dur = 0.0
        self.base_dur = 0.0
        self.failed = False


def build_dub(segs: list[Segment], job: Path, cfg, meta: dict, shorten_fn=None,
              clone_ref: Path | None = None) -> tuple[Path, int]:
    """Trả về (dub.wav, số câu chưa đọc được). clone_ref: mẫu giọng gốc (voice_mode=clone)."""
    from .voice import voice_for

    tc = cfg.tts
    engine = tc.engine
    clips = job / "tts"
    clips.mkdir(exist_ok=True)
    total = float(meta.get("duration") or (segs[-1].end if segs else 0))
    base_pct = _pct(tc.rate) if engine == "edge" else 0.0
    max_speed, hard_max = float(tc.max_speed), float(tc.hard_max_speed)
    conc = int(tc.concurrency)
    ref, use_codes = "", True
    if engine == "vieneu":
        if tc.ref_audio:
            ref = str(Path(tc.ref_audio).resolve())
        elif clone_ref is not None:
            ref, use_codes = str(Path(clone_ref).resolve()), False
    elif engine not in ("edge", "vox"):
        raise ValueError(f"tts.engine không hợp lệ: {engine} (vieneu | vox | edge)")

    lines = [
        _Line(i, s, voice_for(s, cfg), slot_of(segs, i, total))
        for i, s in enumerate(segs) if s.trans.strip()
    ]
    default_voice = ", ".join(sorted({ln.voice for ln in lines if ln.voice})) or "giọng mặc định"
    n_synth = {"done": 0, "total": len(lines)}

    def on_step(_n, _t):
        n_synth["done"] += 1
        progress("tts", min(1.0, n_synth["done"] / max(1, n_synth["total"])))
    if not lines:
        raise RuntimeError("Không có câu dịch nào để lồng tiếng")

    pronounce = tc.get("pronounce") or {}

    def synth_and_measure(ls: list[_Line], old_state: dict | None = None) -> None:
        """old_state: {id(line): (mp3, trans, pct, dur)} để khôi phục nếu lần đọc lại bị lỗi."""
        jobs = []
        for ln in ls:
            if ln.seg.rec and (job / "rec" / ln.seg.rec).exists():
                ln.mp3 = job / "rec" / ln.seg.rec       # giọng thu tay: không cần đọc, chỉ co giãn cho vừa khe
                continue
            r = _rate_str(ln.pct)
            spoken = speakable(apply_pronounce(ln.seg.trans, pronounce))
            if engine == "edge":
                ln.mp3 = clips / f"{ln.seg.id:04d}_{short_hash(spoken, ln.voice, r)}.mp3"
            elif engine == "vox":
                ln.mp3 = clips / f"{ln.seg.id:04d}_vx_{short_hash(spoken, ln.voice)}.wav"
            else:
                ln.mp3 = clips / f"{ln.seg.id:04d}_vn_{short_hash(spoken, ln.voice, ref, str(use_codes))}.wav"
            jobs.append((spoken, ln.voice, r, ln.mp3))
        n_new = sum(1 for j in jobs if not j[3].exists())
        n_synth["done"], n_synth["total"] = 0, n_new
        if n_new:
            log("tts", f"  đọc {n_new} câu mới" + (f" ({len(jobs) - n_new} câu dùng lại từ cache)" if n_new < len(jobs) else ""))
        if engine == "edge":
            synth_many(jobs, conc, tc.fallback_voice)
        elif engine == "vox":
            from .asr import release_model
            from .voxtts import synth_many as vox_synth
            if n_new:
                release_model()      # card đồ họa nhỏ: Whisper còn nằm lại thì bộ đọc phải chạy một phần bằng RAM, chậm gấp đôi
            vox_synth(jobs, on_step)
        else:
            _VieNeu.synth(jobs, ref, use_codes, on_step)
        for ln in ls:
            if ln.mp3.exists():
                ln.dur = wav_duration(_decoded(ln.mp3))
            elif old_state and id(ln) in old_state:
                ln.mp3, ln.seg.trans, ln.pct, ln.dur = old_state[id(ln)]
            else:
                ln.failed = True

    def snapshot(ls: list[_Line]) -> dict:
        return {id(ln): (ln.mp3, ln.seg.trans, ln.pct, ln.dur) for ln in ls}

    # 1) đọc ở tốc độ gốc
    for ln in lines:
        ln.pct = base_pct
    who = ("clone " + Path(ref).name) if ref else default_voice
    log("tts", f"Lồng tiếng {len(lines)} câu bằng {engine}: {who}")
    synth_and_measure(lines)
    for attempt in (1, 2):
        # câu đọc lỗi (Edge giới hạn tần suất, VieNeu gặp câu lạ): đọc lại tối đa 2 lần trước khi chịu bỏ trống
        retry = [ln for ln in lines if ln.failed]
        if not retry:
            break
        log("tts", f"Đọc lại {len(retry)} câu bị lỗi (lần {attempt})")
        if engine == "edge":
            import time
            time.sleep(4.0 * attempt)
            conc = 1
        for ln in retry:
            ln.failed = False
        synth_and_measure(retry)
    failed = [ln for ln in lines if ln.failed]
    lines = [ln for ln in lines if not ln.failed]
    if not lines:
        raise RuntimeError("TTS lỗi toàn bộ — kiểm tra mạng hoặc đợi vài phút (Edge giới hạn tần suất)")

    # 2) câu quá dài -> rút gọn bản dịch
    too_long = [ln for ln in lines if ln.dur > ln.slot * max_speed and not ln.seg.rec]
    if too_long and shorten_fn and cfg.translate.shorten_retry:
        targets = {}
        for ln in too_long:
            cur = count_units(ln.seg.trans, cfg.translate.target_lang)
            fit = int(cur * ln.slot * max_speed / ln.dur * 0.95)
            targets[ln.seg.id] = max(2, min(fit, max_len_for(ln.slot, cfg)))
        log("tts", f"{len(too_long)} câu đọc không kịp -> rút gọn bản dịch")
        try:
            new = shorten_fn(targets)
        except Exception as e:
            log("tts", f"Rút gọn lỗi, bỏ qua: {e}")
            new = {}
        old = snapshot(too_long)
        changed = []
        for ln in too_long:
            t = new.get(ln.seg.id, "").strip()
            if t and t != ln.seg.trans:
                ln.seg.trans = t
                changed.append(ln)
        if changed:
            synth_and_measure(changed, old)
    # 2b) câu vẫn dài hơn mức tăng tốc tối đa (sẽ đẩy cả đoạn sau lệch dần): rút gọn thêm một lần, chặt hơn
    still = [ln for ln in lines if ln.dur > ln.slot * hard_max and not ln.seg.rec]
    if still and shorten_fn and cfg.translate.shorten_retry:
        targets = {}
        for ln in still:
            cur = count_units(ln.seg.trans, cfg.translate.target_lang)
            fit = int(cur * ln.slot * max_speed / ln.dur * 0.9)
            targets[ln.seg.id] = max(2, min(fit, max_len_for(ln.slot, cfg), cur - 1))
        log("tts", f"{len(still)} câu vẫn quá dài so với thời gian -> rút gọn thêm lần nữa")
        try:
            new = shorten_fn(targets)
        except Exception as e:
            log("tts", f"Rút gọn lần 2 lỗi, bỏ qua: {e}")
            new = {}
        old = snapshot(still)
        changed = []
        for ln in still:
            t = new.get(ln.seg.id, "").strip()
            if t and t != ln.seg.trans and len(t) < len(ln.seg.trans):
                ln.seg.trans = t
                changed.append(ln)
        if changed:
            synth_and_measure(changed, old)
            for ln in changed:
                if ln.failed:           # đọc lại bản ngắn lỗi: giữ bản cũ đã đọc được
                    ln.mp3, ln.seg.trans, ln.pct, ln.dur = old[id(ln)]
                    ln.failed = False
    for ln in lines:
        ln.base_dur = ln.dur

    # 3) tăng rate edge-tts cho câu còn dài
    # (VieNeu không có tham số tốc độ -> bỏ bước này, atempo ở bước 4 sẽ bù)
    faster = [ln for ln in lines if ln.dur > ln.slot * 1.03 and not ln.seg.rec] if engine == "edge" else []
    if faster:
        log("tts", f"Tăng tốc đọc {len(faster)} câu")
        old = snapshot(faster)            # lỗi thì giữ bản đọc tốc độ gốc (atempo sẽ bù)
        for ln in faster:
            need = min(ln.dur / ln.slot, max_speed)
            ln.pct = base_pct + (need - 1.0) * 100.0 + 3.0
        synth_and_measure(faster, old)

    # 4) atempo phần dư + 5) đặt vào timeline
    track = np.zeros(int((total + 2.0) * SR), dtype=np.float32)
    cursor, drift_max = 0.0, 0.0
    drifted: list[str] = []
    for ln in sorted(lines, key=lambda x: x.seg.start):
        edge_factor = ln.base_dur / ln.dur if ln.dur > 0 else 1.0
        tempo = 1.0
        if ln.dur > ln.slot * 1.02:
            tempo = min(ln.dur / ln.slot, max(1.0, hard_max / max(edge_factor, 1e-6)))
        data, _ = read_wav(_decoded(ln.mp3, tempo))
        at = max(ln.seg.start, cursor)
        a, b = int(at * SR), int(at * SR) + len(data)
        if b > len(track):
            track = np.pad(track, (0, b - len(track) + SR))
        track[a:b] += data
        ln.seg.dub_start = round(at, 3)
        ln.seg.dub_end = round(at + len(data) / SR, 3)
        ln.seg.speed = round(edge_factor * tempo, 3)
        drift_max = max(drift_max, at - ln.seg.start)
        if at - ln.seg.start > 0.6:
            drifted.append(f"{ln.seg.start:.1f}s")
        cursor = ln.seg.dub_end + 0.05

    end = max(total, cursor)
    track = track[: int(end * SR) + 1]
    out = job / "dub.wav"
    write_wav(out, track, SR)
    sp = [ln.seg.speed for ln in lines if ln.seg.speed]
    log("tts", f"dub.wav xong. Tăng tốc TB {np.mean(sp):.2f}x, max {max(sp):.2f}x, trôi tối đa {drift_max:.2f}s")
    if drifted:
        log("tts", f"CẢNH BÁO: {len(drifted)} câu đọc lệch sau hình hơn 0,6 giây (câu trước quá dài): "
                   + ", ".join(drifted[:12]) + (" ..." if len(drifted) > 12 else "")
                   + ". Rút gọn câu đứng trước các mốc này trong Studio để khớp hơn")
    if failed:
        log("tts", f"CẢNH BÁO: {len(failed)} câu chưa đọc được (Edge giới hạn) — chạy lại lệnh sau ít phút "
                   "để đọc bù, các câu đã đọc được giữ trong cache")
    if cursor > total + 0.3:
        log("tts", f"CẢNH BÁO: lồng tiếng dài hơn video {cursor - total:.1f}s — phần cuối sẽ bị cắt")
    for ln in failed:
        ln.seg.dub_start = ln.seg.dub_end = ln.seg.speed = None
    if engine == "vox":      # đọc xong cả video: trả card đồ họa cho bước dựng và cho bước nhận dạng của video sau
        from .voxtts import SERVER
        SERVER.stop()
    return out, len(failed)


def list_voices(prefix: str = "vi") -> list[dict]:
    import edge_tts

    voices = asyncio.run(edge_tts.list_voices())
    return [v for v in voices if v["Locale"].lower().startswith(prefix.lower())]
