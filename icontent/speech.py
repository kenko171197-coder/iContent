"""Đọc văn bản thành giọng nói: chia thành từng đoạn ngắn, đọc từng đoạn, ghép lại kèm khoảng nghỉ theo dấu câu.

Vì đọc từng đoạn nên biết chính xác mỗi đoạn bắt đầu và kết thúc lúc nào: phụ đề khớp tiếng, không phải đoán theo số chữ như khi
chỉ có một file âm thanh. Dùng cho trang Đọc văn bản và cho lời dẫn của video kể chuyện.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from .util import check_cancel, progress, read_wav, short_hash, write_wav

SR = 44100
MAX_CHUNK = 220          # ký tự mỗi lần đọc: dài quá thì giọng đọc hay đọc sai nhịp ở cuối câu
PAUSE_AFTER = {".": 0.34, "!": 0.34, "?": 0.34, "…": 0.4, ";": 0.2, ":": 0.2, ",": 0.12}
PARAGRAPH_PAUSE = 0.55
ENGINES = ("vieneu", "edge", "vox")      # vox: nhiều thứ tiếng trên máy (voxtts.py), giọng en_f1, id_m2...
DEFAULT_VOICE = {"vieneu": "", "edge": "vi-VN-HoaiMyNeural"}

# chỉ hết câu khi sau dấu câu là khoảng trắng hoặc hết đoạn: "1.500.000", "TP.HCM", "10.30", địa chỉ web không bị cắt
_SENT_END = re.compile(r"(?<=[.!?…])[\"'”’)\]]*\s+")
_READABLE = re.compile(r"[^\W_]", re.UNICODE)      # chữ cái hoặc chữ số, kể cả tiếng Việt


def readable(text: str) -> bool:
    """Có gì để đọc không: "...", "***", "---", toàn biểu tượng cảm xúc thì không (gửi đi chỉ làm bộ giọng báo lỗi)."""
    return bool(_READABLE.search(text or ""))


def paragraphs(text: str) -> list[str]:
    """Đoạn văn cách nhau bằng dòng trống. Xuống dòng đơn (văn bản chép từ PDF, web bị ngắt dòng cứng) chỉ là khoảng trắng."""
    out = []
    for block in re.split(r"\r?\n\s*\r?\n", text or ""):
        one = re.sub(r"\s*\r?\n\s*", " ", block).strip()
        if one:
            out.append(one)
    return out


def sentences(para: str) -> list[str]:
    """Tách câu mà không thêm, bớt ký tự nào: nối các câu lại bằng khoảng trắng là ra đúng đoạn văn."""
    out, start = [], 0
    for m in _SENT_END.finditer(para):
        piece = para[start:m.start() + len(m.group(0).rstrip())].strip()
        if piece:
            out.append(piece)
        start = m.end()
    tail = para[start:].strip()
    if tail:
        out.append(tail)
    return out


def _split_long(s: str, limit: int) -> list[str]:
    """Câu dài hơn giới hạn: tách ở dấu phẩy, chấm phẩy, rồi mới tới khoảng trắng."""
    s = s.strip()
    if len(s) <= limit:
        return [s] if s else []
    for sep in (";", ",", " "):
        parts = [p.strip() for p in re.split(rf"(?<={re.escape(sep)})\s+" if sep != " " else r"\s+", s) if p.strip()]
        if len(parts) > 1:
            out, cur = [], ""
            for p in parts:
                if cur and len(cur) + 1 + len(p) > limit:
                    out.append(cur)
                    cur = p
                else:
                    cur = f"{cur} {p}".strip()
            if cur:
                out.append(cur)
            return [y for x in out for y in _split_long(x, limit)] if any(len(x) > limit for x in out) and sep != " " else out
    return [s[i:i + limit] for i in range(0, len(s), limit)]


def chunks(text: str, limit: int = MAX_CHUNK) -> list[tuple[str, float]]:
    """-> [(đoạn, khoảng nghỉ sau nó)]. Giữ ranh giới đoạn văn: nghỉ dài hơn giữa hai đoạn."""
    out: list[tuple[str, float]] = []
    paras = paragraphs(text)
    for pi, para in enumerate(paras):
        merged: list[str] = []
        for s in sentences(para):      # câu quá ngắn ("Ừ.", "Vâng!") đọc riêng nghe cụt: gộp với câu sau
            if merged and len(merged[-1]) < 24 and len(merged[-1]) + 1 + len(s) <= limit:
                merged[-1] = f"{merged[-1]} {s}"
            else:
                merged.append(s)
        pieces = [p for s in merged for p in _split_long(s, limit) if readable(p)]
        for k, p in enumerate(pieces):
            last = p.rstrip("\"'”’)] ")[-1:] if p.strip() else ""
            pause = PAUSE_AFTER.get(last, 0.1)
            if k == len(pieces) - 1 and pi < len(paras) - 1:
                pause = max(pause, PARAGRAPH_PAUSE)
            out.append((p, pause))
    return out


def display_pieces(text: str, max_chars: int) -> list[str]:
    """Cắt một đoạn đã đọc thành các dòng phụ đề vừa màn hình. Chia đều độ dài các dòng thay vì lấp đầy dòng đầu: tránh dòng cuối còn
    trơ một hai chữ, và tránh cắt ngang cụm như "Ấn / Độ". Ưu tiên cắt ngay sau dấu câu."""
    words = text.split()
    n = len(words)
    if n == 0:
        return []
    if len(text) <= max_chars:
        return [" ".join(words)]
    lens = [len(w) for w in words]
    k = max(2, -(-len(" ".join(words)) // max_chars))
    target = len(" ".join(words)) / k
    INF = float("inf")
    best = [INF] * (n + 1)      # best[i]: chi phí tốt nhất để xếp words[:i]
    cut = [0] * (n + 1)
    best[0] = 0.0
    for i in range(1, n + 1):
        width = -1
        for j in range(i - 1, -1, -1):      # dòng là words[j:i]
            width += lens[j] + 1
            if width > max_chars and j < i - 1:
                break
            cost = (width - target) ** 2 + target * target * 0.6      # mỗi dòng thêm là một lần mắt phải đọc lại: ít dòng hơn thì tốt hơn
            if i < n and words[i - 1][-1:] in ",.;:!?…":
                cost -= target * target * 0.35      # thưởng cho chỗ cắt ngay sau dấu câu
            if i < n and words[i - 1][:1].isupper() and words[i][:1].isupper():
                cost += target * target      # không tách hai chữ viết hoa liền nhau: thường là một tên riêng
            if best[j] + cost < best[i]:
                best[i], cut[i] = best[j] + cost, j
    out, i = [], n
    while i > 0:
        out.append(" ".join(words[cut[i]:i]))
        i = cut[i]
    return out[::-1]


def timed_lines(timings: list[tuple[float, float, str]], max_chars: int) -> list[tuple[float, float, str]]:
    """Từ thời gian từng đoạn đọc ra từng dòng phụ đề: chia thời gian của đoạn theo số chữ của dòng."""
    lines = []
    for st, en, text in timings:
        parts = display_pieces(text, max_chars) or [text]
        total = sum(len(p) for p in parts) or 1
        t = st
        for p in parts:
            d = (en - st) * len(p) / total
            lines.append((t, t + d, p))
            t += d
    return lines


def _rate(speed: float) -> str:
    p = int(round((speed - 1.0) * 100))
    return f"+{p}%" if p >= 0 else f"{p}%"


_NOT_SPOKEN = re.compile(r"[^\w\s.,!?…;:'\"“”‘’()%/+\-]+", re.UNICODE)


def speakable(text: str) -> str:
    """Chữ đưa cho bộ giọng: bỏ biểu tượng cảm xúc, dấu sao, mũi tên... (phụ đề vẫn giữ nguyên chữ gốc)."""
    return re.sub(r"\s+", " ", _NOT_SPOKEN.sub(" ", text)).strip() or text


def _render_piece(text: str, engine: str, voice: str, speed: float, cache: Path, ref_audio: str = "") -> Path:
    """Một đoạn -> wav mono đã cắt khoảng lặng đầu cuối. Có cache theo nội dung nên đọc lại câu không đổi thì không tốn gì."""
    from .tts import _decoded

    text = speakable(text)
    key = short_hash(engine, voice, f"{speed:.2f}", ref_audio, text) if engine == "edge" else short_hash(engine, voice, ref_audio, text)
    if engine == "edge":
        raw = cache / f"e_{key}.mp3"
        if not raw.exists():
            from .tts import synth_many
            failed = synth_many([(text, voice or DEFAULT_VOICE["edge"], _rate(speed), raw)], 1)
            if failed:
                raise RuntimeError("Giọng Edge (Microsoft) không đọc được: mất mạng, hoặc Microsoft đang giới hạn vì đọc quá nhiều. "
                                   "Kiểm tra mạng, thử lại sau ít phút, hoặc chọn bộ giọng VieNeu (chạy trên máy)")
        return _decoded(raw, 1.0)
    if engine == "vox":
        raw = cache / f"x_{key}.wav"
        if not raw.exists():
            from .voxtts import synth_many as vox_synth
            if vox_synth([(text, voice, "", raw)]):
                raise RuntimeError(f"Bộ đọc nhiều thứ tiếng không đọc được đoạn: {text[:50]}")
        return _decoded(raw, speed if abs(speed - 1.0) > 0.01 else 1.0)
    raw = cache / f"v_{key}.wav"
    if not raw.exists():
        from .tts import _VieNeu
        failed = _VieNeu.synth([(text, voice, "+0%", raw)], ref_audio)
        if failed:
            raise RuntimeError(f"VieNeu không đọc được đoạn: {text[:50]}")
    return _decoded(raw, speed if abs(speed - 1.0) > 0.01 else 1.0)      # VieNeu không có tốc độ đọc: co giãn giữ cao độ


def synthesize(text: str, out_wav: Path, engine: str = "vieneu", voice: str = "", speed: float = 1.0, cache: Path | None = None,
               ref_audio: str = "", lead: float = 0.0, tail: float = 0.0, on_step=None, report: bool = True) -> list[tuple[float, float, str]]:
    """Đọc cả văn bản ra out_wav. Trả về [(bắt đầu, kết thúc, đoạn)] theo giây trong file đó. lead/tail: khoảng lặng thêm ở đầu, cuối."""
    if engine not in ENGINES:
        raise ValueError(f"Không có bộ giọng {engine}")
    from .myvoice import is_mine
    if engine == "edge" and is_mine(voice):      # giọng tự thu: VieNeu hoặc bộ đọc nhiều thứ tiếng, Microsoft không đọc được
        voice = ""
    if engine == "vox":
        from .voxtts import default_voice, is_vox, ready
        if not ready():
            raise RuntimeError("Chưa tải Giọng đọc nhiều thứ tiếng. Vào Cài đặt, mục Mô-đun AI miễn phí, bấm Tải.")
        if not voice or not (is_vox(voice) or is_mine(voice)):
            voice = default_voice("en", "female")
    speed = min(2.0, max(0.5, float(speed or 1.0)))
    cache = cache or out_wav.parent / ".speech_cache"
    cache.mkdir(parents=True, exist_ok=True)
    parts = chunks(text)
    if not parts:
        raise ValueError("Không có chữ nào đọc được (chỉ có dấu câu hoặc biểu tượng)")
    if engine == "edge":      # máy chủ Edge chậm từng câu nhưng cho đọc song song vài câu: gọi trước cả loạt
        from .tts import synth_many
        jobs = {}
        for p, _ in parts:      # câu lặp lại chỉ đọc một lần: hai luồng cùng ghi một file là hỏng file
            said = speakable(p)
            f = cache / f"e_{short_hash(engine, voice, f'{speed:.2f}', ref_audio, said)}.mp3"
            jobs[f] = (said, voice or DEFAULT_VOICE["edge"], _rate(speed), f)
        synth_many(list(jobs.values()), 3)      # câu nào hỏng sẽ được thử lại và báo lỗi rõ ở bước dưới
    track: list[np.ndarray] = [np.zeros(int(lead * SR), np.float32)]
    t = lead
    timings = []
    for n, (piece, pause) in enumerate(parts, 1):
        check_cancel()
        wav = _render_piece(piece, engine, voice, speed, cache, ref_audio)
        data, sr = read_wav(wav)
        if sr != SR:
            raise RuntimeError(f"File giọng đọc sai tần số mẫu {sr}")
        data = data.astype(np.float32).reshape(-1)
        timings.append((round(t, 3), round(t + data.size / SR, 3), piece))
        track.append(data)
        track.append(np.zeros(int(pause * SR), np.float32))
        t += data.size / SR + int(pause * SR) / SR
        if on_step:
            on_step(n, len(parts))
        if report:      # câu chuyện tự báo tiến độ theo cảnh, không để hai kiểu tiến độ giành nhau
            progress("tts", n / len(parts))
    track[-1] = np.zeros(int(tail * SR), np.float32)      # bỏ khoảng nghỉ sau đoạn cuối, thay bằng đuôi yêu cầu
    from .editing import normalize_voice
    audio = normalize_voice(np.concatenate(track), SR)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_wav.with_name(out_wav.stem + ".part.wav")
    write_wav(tmp, audio, SR)
    tmp.replace(out_wav)
    out_wav.with_suffix(".json").write_text(json.dumps({"timings": timings, "engine": engine, "voice": voice, "speed": speed}, ensure_ascii=False),
                                            encoding="utf-8")
    return timings


def prune_cache(cache: Path, max_mb: int = 1500) -> None:
    """Cache đọc từng đoạn lớn dần theo thời gian: quá giới hạn thì xóa file ít dùng gần đây nhất."""
    try:
        files = [(f.stat().st_atime, f.stat().st_size, f) for f in cache.iterdir() if f.is_file()]
    except OSError:
        return
    total = sum(x[1] for x in files)
    for _, size, f in sorted(files):
        if total <= max_mb * 1024 * 1024:
            break
        try:
            f.unlink()
            total -= size
        except OSError:
            pass


def speech_key(text: str, engine: str, voice: str, speed: float, ref_audio: str = "") -> str:
    return short_hash(engine, voice, f"{float(speed or 1):.2f}", ref_audio, text)
