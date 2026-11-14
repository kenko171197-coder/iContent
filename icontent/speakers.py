"""Nhận diện người nói: nghe ra video có mấy người, câu nào của ai, rồi mỗi người một giọng lồng cố định.

Cách làm: đã có mốc thời gian từng từ từ bước nhận dạng -> cắt lời thành từng cụm ngắn, lấy "dấu giọng" mỗi cụm
(CAM++ của 3D-Speaker, 28 MB, chạy CPU) rồi gom cụm. Cách này chính xác hơn hẳn bộ diarization tích hợp của
sherpa-onnx (tự đoán lại ranh giới) khi thử trên hội thoại 3 người: 100% so với 77%.

Câu Whisper gộp lời 2 người ("cho anh 10 vạn | chê ít à") được tách đôi ngay ở chỗ đổi người. Vì vậy bước này chạy
TRƯỚC khi dịch. Video đã dịch thì chỉ gắn nhãn, không tách, để không mất bản dịch đã sửa tay.

Ngưỡng 0,6 (khoảng cách cosin) đã thử: tách đúng 3 người kể cả có nhạc nền -8 dB, và không tách nhầm một người lồng
tiếng hai vai (cả 2 đều là lỗi nghe rất khó chịu khi xem video).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from .models import Segment
from .util import check_cancel, log, progress, read_wav, watch_download

REPO = "csukuangfj/speaker-embedding-models"
MODEL_FILE = "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
MODEL_MB = 28
THRESHOLD = 0.6        # khoảng cách cosin gom chung một người
MIN_EMBED = 0.7        # cụm lời ngắn hơn (giây) không đủ tin để gom, chỉ đối chiếu với người đã có
MIN_TURN = 0.5         # lượt lời ngắn hơn không tách thành câu riêng
MAX_SPEAKERS = 8
PUNCT = "，,、。.！!？?；;：: "
# giọng dễ phân biệt được xếp trước; phần còn lại của danh sách VieNeu nối tiếp sau
VIENEU_ORDER = {"male": ["Thiện Minh", "Hải Đăng", "Quang Sơn", "Minh Đức", "Thái Sơn"],
                "female": ["Trúc Ly", "Mai Anh", "Ngọc Huyền", "Thùy Dung", "Ngọc Trân"]}

_extractor = None


def available() -> bool:
    try:
        import sherpa_onnx  # noqa: F401
        return True
    except ImportError:
        return False


def model_cached() -> bool:
    from .util import hf_cache_dir

    return any(hf_cache_dir().glob(f"models--{REPO.replace('/', '--')}/snapshots/*/{MODEL_FILE}"))


def _get_extractor():
    global _extractor
    if _extractor is None:
        import sherpa_onnx
        from huggingface_hub import hf_hub_download

        try:     # đã có thì không hỏi mạng: chạy được khi không có internet
            path = hf_hub_download(REPO, MODEL_FILE, local_files_only=True)
        except Exception:
            with watch_download("speakers", "Đang tải mô hình nhận diện người nói", MODEL_MB):
                path = hf_hub_download(REPO, MODEL_FILE)
        _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=path, num_threads=4))
    return _extractor


def _embed(audio: np.ndarray, sr: int, a: float, b: float) -> np.ndarray | None:
    chunk = audio[int(a * sr):int(b * sr)]
    if len(chunk) < int(0.3 * sr):
        return None
    ex = _get_extractor()
    st = ex.create_stream()
    st.accept_waveform(sr, chunk.astype(np.float32))
    st.input_finished()
    if not ex.is_ready(st):
        return None
    v = np.array(ex.compute(st), dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else None


def _units(segs: list[Segment], words: list[tuple] | None) -> list[dict]:
    """Cắt mỗi câu thành các cụm lời theo dấu cách / dấu câu / khoảng nghỉ trong kết quả Whisper."""
    units: list[dict] = []
    ws = words or []
    k = 0
    for i, s in enumerate(segs):
        inner: list[tuple] = []
        while k < len(ws) and (ws[k][0] + ws[k][1]) / 2 < s.start - 0.05:
            k += 1
        j = k
        while j < len(ws) and (ws[j][0] + ws[j][1]) / 2 <= s.end + 0.05:
            inner.append(ws[j])
            j += 1
        k = j
        if not inner:
            units.append({"seg": i, "start": s.start, "end": s.end, "words": []})
            continue
        cur: list[tuple] = [inner[0]]
        for prev, w in zip(inner, inner[1:]):
            brk = len(prev) > 3 and prev[3] >= 1
            if brk or prev[2].strip()[-1:] in PUNCT or w[0] - prev[1] >= 0.2:
                units.append({"seg": i, "start": cur[0][0], "end": cur[-1][1], "words": cur})
                cur = []
            cur.append(w)
        units.append({"seg": i, "start": cur[0][0], "end": cur[-1][1], "words": cur})
    return _join_short(units)


def _join_short(units: list[dict]) -> list[dict]:
    """Cụm rất ngắn liền sát cụm kế trong cùng câu thì nhập lại: đủ dài mới lấy được dấu giọng đáng tin."""
    out: list[dict] = []
    for u in units:
        p = out[-1] if out else None
        if p and p["seg"] == u["seg"] and p["end"] - p["start"] < MIN_EMBED and u["start"] - p["end"] < 0.12:
            p["end"], p["words"] = u["end"], p["words"] + u["words"]
        else:
            out.append(dict(u))
    return out


def _cluster(vecs: np.ndarray, durs: np.ndarray) -> np.ndarray:
    """Gom cụm trung bình theo cosin, rồi nhập các nhóm quá ít lời vào nhóm gần nhất."""
    if len(vecs) < 2:
        return np.zeros(len(vecs), dtype=int)
    from scipy.cluster.hierarchy import fcluster, linkage

    lab = fcluster(linkage(vecs, "average", metric="cosine"), THRESHOLD, "distance") - 1
    total = float(durs.sum())
    while True:
        ids = np.unique(lab)
        if len(ids) < 2:
            break
        secs = {c: float(durs[lab == c].sum()) for c in ids}
        small = min(ids, key=lambda c: secs[c])
        if secs[small] >= max(3.0, total * 0.03) and len(ids) <= MAX_SPEAKERS:
            break
        cent = {c: vecs[lab == c].mean(axis=0) for c in ids}
        other = max((c for c in ids if c != small), key=lambda c: float(cent[c] @ cent[small]))
        lab[lab == small] = other
    return np.unique(lab, return_inverse=True)[1]


def _text_of(ws: list[tuple]) -> str:
    return " ".join("".join(w[2] for w in ws).split()).strip(PUNCT)


def _apply_labels(segs: list[Segment], units: list[dict], split: bool) -> list[Segment]:
    """Gắn nhãn cho từng câu; split=True thì tách câu có nhiều người, bỏ các lượt quá ngắn (dễ là nhận nhầm)."""
    by_seg: dict[int, list[dict]] = {}
    for u in units:
        by_seg.setdefault(u["seg"], []).append(u)
    out: list[Segment] = []
    for i, s in enumerate(segs):
        us = by_seg.get(i, [])
        runs: list[dict] = []
        for u in us:
            if runs and runs[-1]["spk"] == u["spk"]:
                runs[-1]["end"], runs[-1]["words"] = u["end"], runs[-1]["words"] + u["words"]
            else:
                runs.append({"spk": u["spk"], "start": u["start"], "end": u["end"], "words": list(u["words"])})
        k = 0
        while len(runs) > 1 and k < len(runs):     # lượt ngắn nhập vào lượt bên cạnh
            r = runs[k]
            if r["end"] - r["start"] >= MIN_TURN and len(_text_of(r["words"])) >= 2:
                k += 1
                continue
            t = k - 1 if k > 0 else k + 1
            a, b = min(k, t), max(k, t)
            keep = runs[t]["spk"]
            runs[a:b + 1] = [{"spk": keep, "start": runs[a]["start"], "end": runs[b]["end"],
                              "words": runs[a]["words"] + runs[b]["words"]}]
            k = 0
        if not runs:
            out.append(s)
            continue
        if len(runs) == 1 or not split or not all(r["words"] for r in runs):
            best = max({r["spk"] for r in runs}, key=lambda c: sum(r["end"] - r["start"] for r in runs if r["spk"] == c))
            s.speaker = best
            out.append(s)
            continue
        for n, r in enumerate(runs):
            start = s.start if n == 0 else r["start"]
            end = s.end if n == len(runs) - 1 else r["end"]
            out.append(Segment(id=0, start=round(start, 3), end=round(end, 3), text=_text_of(r["words"]), speaker=r["spk"]))
    for n, s in enumerate(out, 1):
        s.id = n if split else s.id
    return out


def diarize(segs: list[Segment], words: list[tuple] | None, wav: Path, split: bool = True) -> tuple[list[Segment], dict]:
    """-> (danh sách câu đã gắn s.speaker, {"speakers": [...]}). Không ghi file."""
    audio, sr = read_wav(wav)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    units = _units(segs, words if split else None)
    vecs: list[np.ndarray] = []
    strong: list[dict] = []
    for n, u in enumerate(units):
        if n % 8 == 0:
            check_cancel()
            progress("speakers", n / max(1, len(units)))
        u["vec"] = _embed(audio, sr, u["start"], u["end"])
        if u["vec"] is not None and u["end"] - u["start"] >= MIN_EMBED:
            strong.append(u)
            vecs.append(u["vec"])
    if not strong:     # toàn câu rất ngắn: không đủ căn cứ, coi như một người
        for s in segs:
            s.speaker = "S1"
        return segs, _summary(segs)
    lab = _cluster(np.stack(vecs), np.array([u["end"] - u["start"] for u in strong]))
    for u, c in zip(strong, lab):
        u["cl"] = int(c)
    cent = {c: np.mean([u["vec"] for u in strong if u["cl"] == c], axis=0) for c in set(int(x) for x in lab)}
    cent = {c: v / max(1e-9, float(np.linalg.norm(v))) for c, v in cent.items()}
    # cụm ngắn: lấy người gần nhất nếu đủ giống, không thì theo cụm liền trước
    prev = next(u["cl"] for u in strong)
    for u in units:
        if "cl" not in u:
            if u["vec"] is not None:
                best = max(cent, key=lambda c: float(cent[c] @ u["vec"]))
                u["cl"] = best if float(cent[best] @ u["vec"]) >= 0.25 else prev
            else:
                u["cl"] = prev
        prev = u["cl"]
    # đánh số theo thời lượng nói: S1 là người nói nhiều nhất
    secs: dict[int, float] = {}
    for u in units:
        secs[u["cl"]] = secs.get(u["cl"], 0.0) + u["end"] - u["start"]
    rank = {c: f"S{i}" for i, c in enumerate(sorted(secs, key=lambda c: -secs[c]), 1)}
    for u in units:
        u["spk"] = rank[u["cl"]]
    before = len(segs)
    out = _apply_labels(segs, units, split)
    info = _summary(out)
    n = len(info["speakers"])
    log("speakers", f"Nghe ra {n} người nói" + (f", tách thêm {len(out) - before} câu ở chỗ đổi người" if len(out) > before else ""))
    return out, info


def _summary(segs: list[Segment], old: dict | None = None) -> dict:
    """Danh sách người nói theo dữ liệu hiện tại, giữ tên và giọng đã đặt tay."""
    known = {x["id"]: x for x in (old or {}).get("speakers", [])}
    stats: dict[str, dict] = {}
    for s in segs:
        if s.speaker:
            d = stats.setdefault(s.speaker, {"lines": 0, "seconds": 0.0})
            d["lines"] += 1
            d["seconds"] += s.dur
    out = []
    for i, sid in enumerate(sorted(stats, key=lambda k: -stats[k]["seconds"]), 1):
        prev = known.get(sid, {})
        out.append({"id": sid, "name": prev.get("name") or f"Người {sid[1:] if sid[1:].isdigit() else i}",
                    "voice": prev.get("voice", ""), "gender": prev.get("gender", ""),
                    "auto_voice": prev.get("auto_voice", ""), "f0": prev.get("f0"),
                    "lines": stats[sid]["lines"], "seconds": round(stats[sid]["seconds"], 1)})
    return {"speakers": out}


def carry_over(info: dict, segs: list[Segment], old_labels: dict[int, str], old: dict | None) -> dict:
    """Sau khi nhận diện lại: người mới trùng phần lớn câu với người cũ thì nhận lại tên, giọng, giới tính của người đó.
    Số thứ tự S1, S2 có thể đổi nên phải so theo câu, không so theo mã."""
    known = {p["id"]: p for p in (old or {}).get("speakers", [])}
    taken: set[str] = set()
    for p in info["speakers"]:
        mine = [s.id for s in segs if s.speaker == p["id"]]
        count: dict[str, int] = {}
        for sid in mine:
            o = old_labels.get(sid)
            if o in known and o not in taken:
                count[o] = count.get(o, 0) + 1
        if not count:
            continue
        best = max(count, key=lambda k: count[k])
        if count[best] * 2 < len(mine):
            continue
        taken.add(best)
        was = known[best]
        for k in ("voice", "gender", "f0", "auto_voice"):
            p[k] = was.get(k, p.get(k))
        if not re.fullmatch(r"Người \d+", was.get("name") or ""):    # tên mặc định thì để theo số mới
            p["name"] = was["name"]
    return info


def load(job: Path) -> dict | None:
    p = job / "speakers.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save(job: Path, info: dict) -> None:
    (job / "speakers.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")


def _pool(cfg, gender: str, need: int) -> list[str]:
    """Giọng ứng viên cho một giới tính, giọng đã chọn trong cài đặt đứng đầu.
    Edge chỉ có 1 giọng Việt mỗi giới tính nên người thứ hai cùng giới sẽ dùng chung giọng."""
    from .voice import _fits_engine, default_voice, vieneu_voices

    t = cfg.tts
    engine = t.engine
    lang = cfg.translate.target_lang
    chosen = t.male_voice if gender == "male" else t.female_voice
    first = chosen if chosen and _fits_engine(chosen, engine, lang) else default_voice(engine, lang, gender)
    pool = [first] if first else []
    if engine == "vox":      # mỗi thứ tiếng có 2 giọng mỗi giới tính: người thứ hai cùng giới có giọng riêng
        from .voxtts import voices
        return pool + [v["id"] for v in voices(lang) if v["gender"] == gender and v["id"] not in pool]
    if engine != "vieneu":
        return pool
    pool += [n for n in VIENEU_ORDER[gender] if n not in pool]
    if len(pool) < need:      # hiếm: nhiều người cùng giới hơn danh sách ưu tiên -> mới phải nạp VieNeu để xem hết
        try:
            pool += [v["id"] for v in vieneu_voices() if v["gender"] == gender and v["id"] not in pool]
        except Exception as e:
            log("speakers", f"Chưa đọc được danh sách giọng: {str(e)[:120]}")
    return pool


def assign_voices(job: Path, segs: list[Segment], wav: Path, cfg, hint: str = "") -> dict[str, str]:
    """Xác định nam/nữ từng người theo cao độ, chia giọng không trùng nhau, cập nhật speakers.json + s.gender.
    Trả về {speaker: giọng}. Giọng đặt tay trong Studio luôn được ưu tiên."""
    from .voice import analyze_pitch, gender_of, nearest_gender

    info = _summary(segs, load(job))
    people = info["speakers"]
    if not people:
        return {}
    split = float(cfg.tts.pitch_split)
    if any(not p.get("gender") for p in people):
        pitch = analyze_pitch(wav, segs)
        for k, p in enumerate(people):
            vals = [pitch["lines"].get(s.id) for s in segs if s.speaker == p["id"]]
            vals = [v for v in vals if v]
            p["f0"] = round(float(np.median(vals)), 1) if vals else None
            # gợi ý từ nội dung chỉ nói về người kể chính, nên chỉ áp cho người nói nhiều nhất
            said = hint if k == 0 and hint in ("male", "female") else ""
            p["gender"] = gender_of(p["f0"], split) or said or nearest_gender(p["f0"], split) \
                or nearest_gender(pitch["global"], split) or "male"
    used = {p["voice"] for p in people if p["voice"]}
    count = {g: sum(1 for p in people if p["gender"] == g) for g in {p["gender"] for p in people}}
    pools = {g: _pool(cfg, g, n) for g, n in count.items()}
    for p in people:      # người nói nhiều nhất được chọn trước
        p["auto_voice"] = ""
        if p["voice"]:
            continue
        pool = pools[p["gender"]]
        pick = next((v for v in pool if v not in used), pool[0] if pool else "")
        p["auto_voice"] = pick
        used.add(pick)
    by_id = {p["id"]: p for p in people}
    for s in segs:
        if s.speaker in by_id:
            s.gender = by_id[s.speaker]["gender"]
    if info != load(job):        # ghi lại file giống hệt sẽ làm Studio tưởng video có thay đổi mới
        save(job, info)
    who = ", ".join(f"{p['name']} ({'nữ' if p['gender'] == 'female' else 'nam'}): {p['voice'] or p['auto_voice']}" for p in people)
    log("voice", who)
    return {p["id"]: p["voice"] or p["auto_voice"] for p in people}


def voice_map(job: Path) -> dict[str, str]:
    return {p["id"]: p.get("voice") or p.get("auto_voice") or "" for p in (load(job) or {}).get("speakers", [])}
