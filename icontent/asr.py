"""Nhận dạng giọng nói tiếng Trung -> các câu có timestamp (faster-whisper, chạy local, GPU nếu có)."""
from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path

from .models import Segment
from .util import check_cancel, hf_cache_dir, log, progress, read_wav, watch_download

PUNCT_END = "。！？!?；;…"
PUNCT_SOFT = "，,、：:"


def _add_cuda_dlls() -> None:
    """Windows: cuBLAS/cuDNN cài qua pip (nvidia-*-cu12) nằm trong site-packages/nvidia/*/bin."""
    if os.name != "nt":
        return
    for sp in map(Path, sys.path):
        nv = sp / "nvidia"
        if nv.is_dir():
            for b in nv.glob("*/bin"):
                os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")
                try:
                    os.add_dll_directory(str(b))
                except OSError:
                    pass


_MODEL: dict = {}
WHISPER_REPOS = {
    "large-v3": ("Systran/faster-whisper-large-v3", 3100),
    "large-v3-turbo": ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", 1620),
    "medium": ("Systran/faster-whisper-medium", 1530),
    "small": ("Systran/faster-whisper-small", 490),
    "tiny": ("Systran/faster-whisper-tiny", 78),
}


def model_ready(model: str) -> bool:
    """Model đã tải đủ về máy chưa (chỉ xem file, không nạp thư viện). Tên lạ / đường dẫn riêng coi như có sẵn."""
    if model not in WHISPER_REPOS:
        return True
    d = hf_cache_dir() / ("models--" + WHISPER_REPOS[model][0].replace("/", "--")) / "snapshots"
    return any(d.glob("*/model.bin"))


def _ensure_model_file(model: str) -> None:
    """Tải model lần đầu ở luồng riêng để vừa báo được tiến độ vừa hủy được (lần sau tải tiếp phần còn lại)."""
    if model_ready(model):
        return
    from faster_whisper.utils import download_model

    mb = WHISPER_REPOS[model][1]
    log("asr", f"Tải mô hình nhận dạng {model} (khoảng {mb / 1000:.1f} GB), chỉ cần tải 1 lần ...")
    err: list[Exception] = []

    def run() -> None:
        try:
            download_model(model)
        except Exception as e:
            err.append(e)

    t = threading.Thread(target=run, daemon=True, name="icontent-worker-dl")
    with watch_download("asr", "Đang tải mô hình nhận dạng", mb):
        t.start()
        while t.is_alive():
            check_cancel()
            t.join(0.5)
    if err:
        raise RuntimeError(f"Không tải được mô hình {model}. Kiểm tra mạng rồi thử lại. ({str(err[0])[:200]})")


def _load_model(acfg):
    """Giữ model trong bộ nhớ giữa các video (web UI / chạy nhiều link)."""
    key = (acfg.model, acfg.device, acfg.compute_type)
    if key not in _MODEL:
        _MODEL.clear()
        _free_ai_engines()
        _MODEL[key] = _create_model(acfg)
    return _MODEL[key]


def _free_ai_engines() -> None:
    """Bộ chạy dịch, giọng đọc của Mô-đun AI còn giữ card đồ họa (chờ tắt khi rảnh): tắt luôn để Whisper có đủ chỗ."""
    try:
        from .localai import LLAMA
        from .voxtts import SERVER
        LLAMA.stop()
        SERVER.stop()
    except Exception:      # noqa: BLE001 — không tắt được thì Whisper vẫn thử nạp như trước
        pass


def release_model() -> None:
    """Trả card đồ họa cho việc nặng tiếp theo (giọng đọc nhiều thứ tiếng). Video sau nạp lại Whisper mất vài giây.
    Đo thật 11/2026 trên card 6 GB: để Whisper nằm lại thì card đầy 5,8/6 GB, giọng đọc phải để mô hình ra RAM, chậm gấp đôi."""
    if _MODEL:
        _MODEL.clear()
        import gc
        gc.collect()


def _safe_alignment() -> None:
    """faster-whisper 1.2.1: CTranslate2 đôi khi không gióng được một đoạn (nhiều chữ so với số khung âm thanh) và trả danh sách rỗng, rồi
    find_alignment vẫn lấy chỉ số trên mảng rỗng -> IndexError, mất cả lượt nhận giọng (gặp với 30 giây video Bilibili thật). Bọc lại:
    đoạn đó không có giờ từng từ, transcribe_words tự chia giờ theo chữ, các đoạn khác vẫn chính xác."""
    from faster_whisper.transcribe import WhisperModel

    orig = WhisperModel.find_alignment
    if getattr(orig, "_icontent_safe", False):
        return

    def find_alignment(self, tokenizer, text_tokens, encoder_output, num_frames, median_filter_width: int = 7):
        try:
            return orig(self, tokenizer, text_tokens, encoder_output, num_frames, median_filter_width)
        except IndexError:
            log("asr", "Một đoạn không gióng được giờ từng từ, chia giờ theo chữ cho đoạn đó")
            return [[] for _ in text_tokens]

    find_alignment._icontent_safe = True
    WhisperModel.find_alignment = find_alignment


_CJK = re.compile(r"[㐀-鿿豈-﫿぀-ヿ가-힯]")
_PUNCT = set(".,!?;:。，！？；：、…\"'“”‘’()（）《》「」")


def _spread_words(text: str, start: float, end: float) -> list[tuple[float, float, str]]:
    """Đoạn có chữ mà không có giờ từng từ: mỗi chữ Hán (hoặc mỗi từ có dấu cách) một từ, giờ chia theo số ký tự, dấu câu dính vào chữ trước."""
    toks: list[str] = []
    for part in re.findall(r"\s*[^\s]+", text):
        for ch in re.findall(r"\s*[㐀-鿿豈-﫿぀-ヿ가-힯]|\s*[^㐀-鿿豈-﫿぀-ヿ가-힯]+", part):
            if toks and all(c in _PUNCT for c in ch.strip()):
                toks[-1] += ch.strip()
            else:
                toks.append(ch)
    toks = [t for t in toks if t.strip()]
    if not toks:
        return []
    weight = [max(1, len(_CJK.findall(t)) or len(t.strip())) for t in toks]
    total, dur, at, out = sum(weight), max(0.0, end - start), start, []
    for t, w in zip(toks, weight):
        b = at + dur * w / total
        out.append((at, b, t))
        at = b
    return out


def _create_model(acfg):
    _add_cuda_dlls()
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    _ensure_model_file(acfg.model)
    import ctranslate2
    from faster_whisper import WhisperModel
    _safe_alignment()

    device = acfg.device
    if device == "auto":
        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    tries = [acfg.compute_type] if acfg.compute_type != "auto" else (
        ["float16", "int8_float16", "int8"] if device == "cuda" else ["int8"]
    )
    last = None
    for ct in tries:
        try:
            m = WhisperModel(acfg.model, device=device, compute_type=ct)
            log("asr", f"Model {acfg.model} trên {device} ({ct})")
            return m
        except Exception as e:  # GPU thiếu DLL / không hỗ trợ kiểu tính -> thử tiếp
            last = e
            log("asr", f"Không chạy được {device}/{ct}: {str(e)[:160]}")
    if device == "cuda":
        log("asr", "Chuyển sang CPU (chậm hơn nhiều)")
        return WhisperModel(acfg.model, device="cpu", compute_type="int8")
    raise RuntimeError(f"Không tải được model Whisper: {last}")


def transcribe(wav16k: str | Path, acfg) -> list[Segment]:
    return resegment(transcribe_words(wav16k, acfg), acfg)


def transcribe_words(wav16k: str | Path, acfg) -> list[tuple]:
    """-> [(start, end, word, brk)] — brk 2 = hết đoạn Whisper, 1 = ranh giới cụm từ."""
    # Đưa mảng float32 16kHz trực tiếp -> không phụ thuộc bộ giải mã PyAV của faster-whisper
    # (PyAV >= 16 bỏ tham số metadata_errors mà faster-whisper 1.2 vẫn dùng).
    audio, sr = read_wav(wav16k)
    if sr != 16000:
        raise ValueError(f"{wav16k}: cần 16kHz, nhận {sr}")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    model = _load_model(acfg)
    segments, info = model.transcribe(
        audio,
        language=acfg.language or None,
        beam_size=int(acfg.beam_size),
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        word_timestamps=True,
        condition_on_previous_text=False,   # giảm lặp/ảo giác của Whisper
        initial_prompt=acfg.initial_prompt or None,
    )
    total = len(audio) / 16000.0
    words = _words_from(segments, total)
    log("asr", f"Ngôn ngữ: {info.language} ({info.language_probability:.2f}), {len(words)} từ")
    return [(round(float(a), 3), round(float(b), 3), w, k) for a, b, w, k in words]


def _words_from(segments, total: float, offset: float = 0.0, keep=None) -> list[tuple]:
    """Đoạn của faster-whisper -> [(start, end, word, brk)]. offset: giờ bắt đầu của khúc âm thanh trong video.
    keep(s): lọc từng đoạn (nghe lại khoảng trống: bỏ đoạn Whisper "nghe" ra trong tiếng nhạc)."""
    words = []
    for s in segments:
        check_cancel()
        if total:
            progress("asr", min(1.0, (s.end + offset) / total))
        if keep is not None and not keep(s):
            continue
        if total and s.start + offset >= total - 0.15:
            # Whisper hay "nghe" ra câu sau khi tiếng đã hết (感谢观看...), với giờ kết thúc theo khung 30 giây của nó, vượt cả độ dài video
            log("asr", f"Bỏ đoạn sau khi hết tiếng: {s.text.strip()[:40]}")
            continue
        end = min(s.end + offset, total) if total else s.end + offset
        ws = [(w.start + offset, min(w.end + offset, end), w.word) for w in (s.words or [])
              if w.word.strip() and (not total or w.start + offset < total)]
        if not ws and s.text.strip():      # đoạn không gióng được giờ từng từ (xem _safe_alignment): không bỏ mất câu thoại
            ws = _spread_words(s.text, s.start + offset, end)
        for j, (a, b, w) in enumerate(ws):
            # điểm ngắt: 2 = hết đoạn Whisper, 1 = từ sau bắt đầu bằng dấu cách (ranh giới cụm từ)
            brk = 2 if j == len(ws) - 1 else (1 if ws[j + 1][2].startswith(" ") else 0)
            words.append((a, b, w, brk))
        log("asr", f"{s.start + offset:7.2f}s  {s.text.strip()[:60]}")
    return words


# Câu Whisper hay "nghe" ra trong tiếng nhạc, không phải lời thoại thật
HALLUCINATIONS = ("感谢观看", "谢谢观看", "字幕", "订阅", "点赞", "关注", "明镜", "请不吝", "Amara", "by ")
CJK = re.compile(r"[\u3400-\u9fff]")


def find_gaps(words: list[tuple], total: float, wav16k: str | Path, min_gap: float = 2.5,
              quiet_db: float = -42.0) -> list[tuple[float, float]]:
    """Khoảng dài không có từ nào mà tiếng gốc vẫn có âm thanh (nhạc nền to che lời: bộ tách giọng làm mất thoại).
    Khoảng im lặng thật (nghỉ giữa các câu, tiếng rất nhỏ) thì bỏ qua để không tốn thời gian nghe lại."""
    import numpy as np
    audio, sr = read_wav(wav16k)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if not total:
        total = len(audio) / float(sr)
    spans, cur = [], 0.0
    for w in sorted(words, key=lambda x: x[0]):
        if w[0] - cur >= min_gap:
            spans.append((cur, w[0]))
        cur = max(cur, w[1])
    if total - cur >= min_gap:
        spans.append((cur, total))
    out = []
    hop = int(0.1 * sr)
    for a, b in spans:
        seg = audio[int(a * sr):int(b * sr)].astype("float64")
        if len(seg) < hop:
            continue
        n = len(seg) // hop
        rms = np.sqrt(np.mean(seg[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
        db = 20 * np.log10(rms + 1e-12)
        if float(np.mean(db > quiet_db)) >= 0.5:      # quá nửa khoảng có tiếng
            out.append((round(a, 3), round(b, 3)))
    return out


def transcribe_gaps(wav16k: str | Path, gaps: list[tuple[float, float]], acfg, total: float = 0.0) -> list[tuple]:
    """Nghe lại các khoảng trống trên tiếng gốc (chưa tách nhạc), bộ lọc khoảng lặng nhạy hơn, chỉ giữ đoạn Whisper chắc chắn."""
    audio, sr = read_wav(wav16k)
    if sr != 16000:
        raise ValueError(f"{wav16k}: cần 16kHz, nhận {sr}")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    total = total or len(audio) / 16000.0
    model = _load_model(acfg)

    def keep(s) -> bool:
        t = s.text.strip()
        zh = (acfg.language or "zh").startswith("zh")
        units = len(CJK.findall(t)) if zh else sum(ch.isalnum() for ch in t)
        if units < 2 or any(h in t for h in HALLUCINATIONS):
            return False
        return getattr(s, "no_speech_prob", 0.0) < 0.6 and getattr(s, "avg_logprob", 0.0) > -1.0

    out = []
    for a, b in gaps:
        check_cancel()
        a0, b0 = max(0.0, a - 0.3), min(total, b + 0.3)
        clip = audio[int(a0 * 16000):int(b0 * 16000)]
        segments, _ = model.transcribe(
            clip,
            language=acfg.language or None,
            beam_size=int(acfg.beam_size),
            vad_filter=True,
            vad_parameters={"threshold": 0.25, "min_silence_duration_ms": 300},
            word_timestamps=True,
            condition_on_previous_text=False,
            initial_prompt=acfg.initial_prompt or None,
        )
        got = [w for w in _words_from(segments, total, offset=a0, keep=keep) if w[0] >= a - 0.3 and w[1] <= b + 0.3]
        log("asr", f"Nghe lại {a:.1f}s đến {b:.1f}s: " + (f"tìm thêm {len(got)} từ" if got else "không có lời"))
        out += got
    return out


STRAY_GAP = 1.5        # chữ lẻ cách chữ kế tiếp từng này giây trở lên mà không kết câu = bị đặt sai giờ
_SENT_END = set("。.！!？?，,、；;：:…")


def fix_stray_words(words: list[tuple]) -> list[tuple]:
    """Sau một đoạn im lặng (nhạc, cảnh không lời) Whisper hay đặt giờ của CHỮ ĐẦU câu mới dính vào cuối câu trước,
    cách phần còn lại của câu cả chục giây: "让 (0:05) ... 让我看不见 (0:18)". Câu ghép lại bị kéo dài từ 0:05,
    tiếng lồng và phụ đề chạy trước hình. Chữ lẻ như vậy (sát câu trước, không có dấu câu, cách chữ sau >= STRAY_GAP)
    được dời về ngay trước chữ kế tiếp. Không đổi chữ, chỉ đổi giờ."""
    ws = [tuple(w) for w in words]
    for i in range(len(ws) - 1):
        a, b, text = ws[i][0], ws[i][1], str(ws[i][2])
        brk = ws[i][3] if len(ws[i]) > 3 else 0
        t = text.strip()
        if not t or t[-1] in _SENT_END or brk or len(re.sub(r"\W", "", t)) > 2:
            continue
        if ws[i + 1][0] - b < STRAY_GAP:
            continue
        if i > 0 and a - ws[i - 1][1] > 1.0:       # đứng riêng một mình giữa khoảng lặng: có thể là tiếng thật
            continue
        nxt = ws[i + 1][0]
        dur = min(b - a, 0.3)
        ws[i] = (round(nxt - dur, 3), round(nxt, 3)) + tuple(ws[i][2:])
    return ws


def resegment(words: list[tuple], acfg) -> list[Segment]:
    """Gộp từ thành câu phụ đề.

    words: (start, end, text[, brk]) — brk 2 = hết đoạn Whisper, 1 = ranh giới cụm từ.
    Ngắt khi: dấu kết câu, hết đoạn Whisper, im lặng >= pause_split. Khi vượt max_chars/max_duration
    thì lùi về điểm ngắt mềm gần nhất (dấu phẩy, dấu cách, khoảng nghỉ ngắn) để không cắt ngang từ.
    """
    max_chars, max_dur, pause = int(acfg.max_chars), float(acfg.max_duration), float(acfg.pause_split)
    out: list[Segment] = []
    ws = [(w[0], w[1], w[2], w[3] if len(w) > 3 else 0) for w in words]

    def length(seq) -> int:
        return sum(len(x[2].strip()) for x in seq)

    def soft(seq, i) -> bool:
        tail = seq[i][2].strip()[-1:]
        gap = seq[i + 1][0] - seq[i][1] if i + 1 < len(seq) else 0.0
        return seq[i][3] >= 1 or (tail and tail in PUNCT_SOFT + PUNCT_END) or gap >= 0.2

    def emit(seq) -> None:
        if not seq:
            return
        text = " ".join("".join(w[2] for w in seq).split()).strip(PUNCT_SOFT + " ")
        if text and any(ch.isalnum() for ch in text):
            out.append(Segment(id=len(out) + 1, start=round(seq[0][0], 3), end=round(seq[-1][1], 3), text=text))

    cur: list[tuple] = []
    for w in ws:
        if cur and w[0] - cur[-1][1] >= pause:
            emit(cur)
            cur = []
        if cur and (length(cur) + len(w[2].strip()) > max_chars or w[1] - cur[0][0] > max_dur):
            k = next((i for i in range(len(cur) - 1, -1, -1) if soft(cur + [w], i)), None)
            if k is not None and length(cur[:k + 1]) >= max_chars * 0.3:
                emit(cur[:k + 1])
                cur = cur[k + 1:]
            else:
                emit(cur)
                cur = []
        cur.append(w)
        tail = w[2].strip()[-1:]
        if (tail and tail in PUNCT_END) or w[3] >= 2:
            emit(cur)
            cur = []
    emit(cur)
    return out
