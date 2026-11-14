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
    words = []
    total = len(audio) / 16000.0
    for s in segments:
        check_cancel()
        progress("asr", s.end / total if total else None)
        if total and s.start >= total - 0.15:
            # Whisper hay "nghe" ra câu sau khi tiếng đã hết (感谢观看...), với giờ kết thúc theo khung 30 giây của nó, vượt cả độ dài video
            log("asr", f"Bỏ đoạn sau khi hết tiếng: {s.text.strip()[:40]}")
            continue
        end = min(s.end, total) if total else s.end
        ws = [(w.start, min(w.end, end), w.word) for w in (s.words or []) if w.word.strip() and (not total or w.start < total)]
        if not ws and s.text.strip():      # đoạn không gióng được giờ từng từ (xem _safe_alignment): không bỏ mất câu thoại
            ws = _spread_words(s.text, s.start, end)
        for j, (a, b, w) in enumerate(ws):
            # điểm ngắt: 2 = hết đoạn Whisper, 1 = từ sau bắt đầu bằng dấu cách (ranh giới cụm từ)
            brk = 2 if j == len(ws) - 1 else (1 if ws[j + 1][2].startswith(" ") else 0)
            words.append((a, b, w, brk))
        log("asr", f"{s.start:7.2f}s  {s.text.strip()[:60]}")
    log("asr", f"Ngôn ngữ: {info.language} ({info.language_probability:.2f}), {len(words)} từ")
    return [(round(float(a), 3), round(float(b), 3), w, k) for a, b, w, k in words]


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
