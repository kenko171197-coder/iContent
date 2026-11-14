"""Chọn giọng lồng: danh sách giọng (kèm giới tính), đoán nam/nữ từ cao độ giọng gốc, lấy mẫu clone giọng.

Cao độ (F0) ước lượng bằng tự tương quan chuẩn hóa trên khung 40ms (numpy thuần, không cần thư viện ngoài).
Giọng nam thường 85-165 Hz, nữ 185-260 Hz -> so trung vị với tts.pitch_split. Chỉ là đoán: giọng nam rất cao
(diễn thuyết hăng say, nhân vật trẻ con) đo được trên 200 Hz, nên Studio luôn cho đổi giọng từng người.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .models import Segment
from .util import log, read_wav, write_wav

DEFAULTS = {
    "vieneu": {"male": "Thiện Minh", "female": "Trúc Ly"},
    "edge": {"male": "vi-VN-NamMinhNeural", "female": "vi-VN-HoaiMyNeural"},
}


# --------------------------------------------------------------------------- danh sách giọng

def vieneu_voices() -> list[dict]:
    """[{id, label, gender, region, style}] — nhãn VieNeu dạng '⭐ Trúc Ly — Nữ · Bắc · Phong cách tự nhiên'."""
    from .tts import _VieNeu

    out = []
    for label, vid in _VieNeu.get().list_preset_voices():
        parts = [p.strip() for p in label.split("—", 1)[-1].split("·")]
        g = parts[0].lower() if parts else ""
        out.append({
            "id": vid, "label": label.replace("⭐", "").strip(), "star": "⭐" in label,
            "gender": "female" if g.startswith("nữ") else ("male" if g.startswith("nam") else ""),
            "region": parts[1] if len(parts) > 1 else "", "style": parts[2] if len(parts) > 2 else "",
        })
    return out


def edge_voices(prefix: str = "vi") -> list[dict]:
    from .tts import list_voices

    return [{"id": v["ShortName"], "gender": v["Gender"].lower(), "locale": v["Locale"]} for v in list_voices(prefix)]


def edge_voices_all() -> list[dict]:
    """Giọng Microsoft cho mọi ngôn ngữ đích trong langs.py (một lần gọi mạng), kèm mã ngôn ngữ iContent."""
    from . import langs
    from .tts import list_voices

    by_loc = {langs.edge_locale(c): c for c in langs.LANGS if langs.edge_locale(c)}
    out = []
    for v in list_voices(""):
        code = by_loc.get(v["Locale"])
        if code:
            out.append({"id": v["ShortName"], "gender": v["Gender"].lower(), "locale": v["Locale"], "lang": code})
    return out


# --------------------------------------------------------------------------- bộ đọc theo ngôn ngữ

def engine_for(cfg) -> str:
    """Bộ đọc thật sự dùng cho ngôn ngữ đích. VieNeu chỉ đọc tiếng Việt: thứ tiếng khác dùng bộ đọc nhiều thứ tiếng trên máy
    (nếu đã tải), không thì giọng Microsoft qua mạng."""
    from .voxtts import ready as vox_ready
    lang = cfg.translate.target_lang
    e = cfg.tts.engine
    if e == "vox" and not vox_ready():
        return "edge" if lang != "vi" else "vieneu"
    if lang != "vi" and e == "vieneu":
        return "vox" if vox_ready() else "edge"
    return e


def default_voice(engine: str, lang: str, gender: str) -> str:
    from . import langs, voxtts
    if engine == "vox":
        return voxtts.default_voice(lang, gender)
    if engine == "edge":
        return langs.edge_voice(lang, gender) or DEFAULTS["edge"].get(gender, "")
    return DEFAULTS.get(engine, {}).get(gender, "")


# --------------------------------------------------------------------------- cao độ

def _f0_frames(x: np.ndarray, sr: int, fmin: float = 70.0, fmax: float = 400.0) -> np.ndarray:
    """F0 từng khung (Hz), 0 = không hữu thanh."""
    n, hop = int(0.04 * sr), int(0.01 * sr)
    if len(x) < n:
        return np.zeros(0, dtype=np.float32)
    nfr = 1 + (len(x) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(nfr)[:, None]
    fr = x[idx].astype(np.float32)
    fr -= fr.mean(axis=1, keepdims=True)
    rms = np.sqrt((fr ** 2).mean(axis=1))
    loud = rms > max(1e-3, 0.25 * np.percentile(rms, 90))
    fr = fr * np.hanning(n).astype(np.float32)[None, :]
    nfft = 1 << (2 * n - 1).bit_length()
    spec = np.fft.rfft(fr, nfft, axis=1)
    ac = np.fft.irfft(np.abs(spec) ** 2, nfft, axis=1)[:, :n]
    ac /= np.maximum(ac[:, :1], 1e-9)
    kmin, kmax = int(sr / fmax), min(n - 1, int(sr / fmin))
    seg = ac[:, kmin:kmax]
    best = seg.max(axis=1)
    # chống lỗi quãng tám: chọn độ trễ NHỎ nhất có đỉnh >= 90% đỉnh lớn nhất
    ok = seg >= (best[:, None] * 0.9)
    peak = np.zeros_like(ok)
    peak[:, 1:-1] = (seg[:, 1:-1] >= seg[:, :-2]) & (seg[:, 1:-1] >= seg[:, 2:])
    cand = ok & peak
    has = cand.any(axis=1)
    k = np.where(has, cand.argmax(axis=1), seg.argmax(axis=1)) + kmin
    f0 = sr / np.maximum(k, 1)
    voiced = loud & (best > 0.5)
    return np.where(voiced, f0, 0.0).astype(np.float32)


def analyze_pitch(wav: Path, segs: list[Segment]) -> dict:
    """{"global": Hz|None, "lines": {id: Hz|None}}"""
    x, sr = read_wav(wav)
    if x.ndim > 1:
        x = x.mean(axis=1)
    lines: dict[int, float | None] = {}
    allv = []
    for s in segs:
        a, b = int(s.start * sr), int(s.end * sr)
        f = _f0_frames(x[a:b], sr)
        v = f[f > 0]
        lines[s.id] = float(np.median(v)) if len(v) >= 8 else None
        allv.append(v)
    allf = np.concatenate(allv) if allv else np.zeros(0)
    return {"global": float(np.median(allf)) if len(allf) >= 30 else None, "lines": lines}


def gender_of(f0: float | None, split: float) -> str:
    if not f0:
        return ""
    if f0 < split - 8:
        return "male"
    if f0 > split + 8:
        return "female"
    return ""


def nearest_gender(f0: float | None, split: float) -> str:
    """Như gender_of nhưng trong vùng lưng chừng thì chọn bên gần hơn, thay vì không trả lời."""
    return gender_of(f0, split) or ("" if not f0 else "male" if f0 < split else "female")


def assign_genders(job: Path, segs: list[Segment], wav: Path, cfg, hint: str = "") -> dict:
    """Ghi s.gender cho từng câu; trả về {"global": male|female, "f0": Hz, ...}. Lưu voice.json.

    hint: giới tính người kể đoán từ nội dung (bước phân tích của LLM) — dùng khi cao độ không rõ.
    """
    split = float(cfg.tts.pitch_split)
    p = analyze_pitch(wav, segs)
    g = gender_of(p["global"], split) or (hint if hint in ("male", "female") else "") \
        or nearest_gender(p["global"], split) or "male"
    per_line = cfg.tts.voice_mode == "per_line"
    prev = g
    for s in segs:
        if not per_line:
            s.gender = g
            continue
        lg = gender_of(p["lines"].get(s.id), split)
        s.gender = lg or prev          # câu không rõ cao độ -> theo câu trước
        prev = s.gender
    n_f = sum(1 for s in segs if s.gender == "female")
    res = {"global": g, "f0": p["global"], "female_lines": n_f, "male_lines": len(segs) - n_f,
           "lines": {str(k): v for k, v in p["lines"].items()}}
    (job / "voice.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    f0s = f"{p['global']:.0f} Hz" if p["global"] else "không rõ"
    if per_line:
        log("voice", f"Cao độ TB {f0s} -> {res['male_lines']} câu giọng nam, {n_f} câu giọng nữ")
    else:
        log("voice", f"Cao độ giọng gốc {f0s} -> giọng {'nữ' if g == 'female' else 'nam'}")
    return res


def _fits_engine(voice: str, engine: str, lang: str = "vi") -> bool:
    """Giọng có đọc được bằng bộ đọc này, cho ngôn ngữ này không. Đổi bộ đọc hay đổi thị trường mà giữ giọng cũ thì đọc không được.
    Edge: vi-VN-HoaiMyNeural (đúng vùng của ngôn ngữ). Nhiều thứ tiếng: en_f1 (đúng ngôn ngữ). VieNeu: tên người, chỉ tiếng Việt.
    Giọng của tôi (me:...): VieNeu (tiếng Việt) và bộ đọc nhiều thứ tiếng (mọi ngôn ngữ)."""
    from . import langs, voxtts
    is_edge = voice.endswith("Neural") and voice.count("-") >= 2
    if voice.startswith("me:"):
        return engine == "vox" or (engine == "vieneu" and lang == "vi")
    if engine == "edge":
        loc = langs.edge_locale(lang)
        return is_edge and (not loc or voice.startswith(loc + "-"))
    if engine == "vox":
        return voxtts.is_vox(voice) and voxtts.lang_of(voice) == lang
    return not is_edge and not voxtts.is_vox(voice) and lang == "vi"


def voice_for(seg: Segment, cfg) -> str:
    """Giọng lồng thực tế của một câu (ưu tiên giọng gán tay cho câu đó)."""
    t = cfg.tts
    eng = t.engine
    lang = cfg.translate.target_lang
    if seg.voice and _fits_engine(seg.voice, eng, lang):
        return seg.voice
    if t.voice_mode == "auto" and seg.speaker:
        v = (t.get("speaker_voices") or {}).get(seg.speaker)
        if v and _fits_engine(v, eng, lang):
            return v
    if t.voice_mode in ("auto", "per_line"):
        g = seg.gender or "male"
        chosen = t.male_voice if g == "male" else t.female_voice
        return chosen if chosen and _fits_engine(chosen, eng, lang) else default_voice(eng, lang, g)
    fixed = t.vieneu_voice if eng == "vieneu" else t.get("vox_voice") if eng == "vox" else t.voice
    return fixed if fixed and _fits_engine(fixed, eng, lang) else default_voice(eng, lang, seg.gender or "female")


# --------------------------------------------------------------------------- mẫu clone giọng

def pick_clone_ref(job: Path, segs: list[Segment], src_wav: Path, min_len: float = 5.0, max_len: float = 9.0) -> Path | None:
    """Ghép các câu liền nhau (khoảng nghỉ ngắn) thành mẫu 5-9s rõ tiếng nhất để VieNeu bắt chước âm sắc."""
    out = job / "clone_ref.wav"
    if out.exists():
        return out
    x, sr = read_wav(src_wav)
    if x.ndim > 1:
        x = x.mean(axis=1)
    best, best_score = None, -1.0
    for i in range(len(segs)):
        st, en, j = segs[i].start, segs[i].end, i
        while en - st < min_len and j + 1 < len(segs) and segs[j + 1].start - en < 0.6:
            j += 1
            en = segs[j].end
        if en - st < min_len * 0.8:
            continue
        en = min(en, st + max_len)
        chunk = x[int(st * sr):int(en * sr)]
        if len(chunk) == 0:
            continue
        rms = np.sqrt(np.mean(chunk ** 2))
        voiced = np.mean(_f0_frames(chunk, sr) > 0)
        score = voiced * 2 + min(rms * 10, 1.0)
        if score > best_score:
            best, best_score = chunk, score
    if best is None:
        return None
    peak = np.max(np.abs(best)) or 1.0
    write_wav(out, best / peak * 0.9, sr)
    log("voice", f"Mẫu clone giọng: {len(best) / sr:.1f}s -> {out.name}")
    return out
