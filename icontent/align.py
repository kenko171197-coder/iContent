"""Ghép nhận dạng giọng nói (thời gian từng từ) với phụ đề gốc đọc bằng OCR.

Phụ đề in sẵn do người làm video tự gõ -> ranh giới câu chuẩn (thường mỗi câu = một lượt lời của một
người) và chữ chính xác hơn ASR. Mỗi từ ASR được gán vào câu phụ đề đang hiện lúc từ đó được nói;
các từ không có phụ đề đi kèm thì ngắt câu như bình thường.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .asr import resegment
from .models import Segment


def _event_of(mid: float, events: list[dict], tol: float = 0.25) -> int | None:
    best, best_d = None, None
    for i, e in enumerate(events):
        if e["start"] - tol <= mid <= e["end"] + tol:
            d = 0.0 if e["start"] <= mid <= e["end"] else min(abs(mid - e["start"]), abs(mid - e["end"]))
            if best_d is None or d < best_d:
                best, best_d = i, d
        elif e["start"] - tol > mid:
            break
    return best


FINAL_PARTICLES = set("吗吧呢啊呀啦嘛哦哈呗")


def _norm(s: str) -> str:
    return re.sub(r"\W", "", s)


def _sim(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _refine(groups: list[tuple[int | None, list[tuple]]], events: list[dict], reach: int = 4) -> None:
    """Sub gốc hiện sớm/muộn hơn lời nói một chút -> dời ranh giới giữa 2 câu liền nhau (±reach từ)
    sao cho chữ ASR mỗi bên khớp nhất với chữ trên màn hình của câu đó."""
    for gi in range(len(groups) - 1):
        (ea, a), (eb, b) = groups[gi], groups[gi + 1]
        if ea is None or eb is None or not a or not b:
            continue
        ta, tb = events[ea]["text"], events[eb]["text"]
        ws = a + b

        def score(k: int) -> float:
            sc = _sim("".join(w[2] for w in ws[:k]), ta) + _sim("".join(w[2] for w in ws[k:]), tb)
            if _norm(ws[k][2])[:1] in FINAL_PARTICLES:   # câu không mở đầu bằng trợ từ cuối câu (吗, 吧, 呢...)
                sc -= 0.3
            return sc

        best_k, best = len(a), score(len(a))
        for k in range(max(1, len(a) - reach), min(len(ws) - 1, len(a) + reach) + 1):
            sc = score(k)
            if sc > best + 1e-6:
                best, best_k = sc, k
        groups[gi], groups[gi + 1] = (ea, ws[:best_k]), (eb, ws[best_k:])


CJK = re.compile(r"[\u3400-\u9fff]")


def _logo_texts(events: list[dict], min_repeat: int = 3, max_chars: int = 4) -> set[str]:
    """Chữ ngắn hiện MỘT MÌNH lặp đi lặp lại nhiều lần = logo / tên kênh in trên video, không phải lời thoại.
    VD logo 丧彪 bị đọc thành 5 "câu" 丧彪 rời nhau. Câu thoại thật hiếm khi lặp nguyên văn, đứng riêng từng ấy lần."""
    count: dict[str, int] = {}
    for e in events:
        t = _norm(str(e.get("text") or ""))
        if t and len(t) <= max_chars:
            count[t] = count.get(t, 0) + 1
    return {t for t, n in count.items() if n >= min_repeat}


def _ocr_only(words: list[tuple], events: list[dict], used: set[int], min_dur: float = 0.5) -> list[Segment]:
    """Phụ đề in sẵn hiện trên màn hình mà Whisper không nghe ra chữ nào (nhạc nền to che lời):
    lấy chính chữ phụ đề làm câu thoại để vẫn dịch và lồng tiếng được, thay vì bỏ trống cả đoạn.
    Bỏ qua logo (chữ ngắn đứng một mình lặp lại nhiều lần). Câu tạo ra được đánh dấu check="ocr" để người dùng soát."""
    out = []
    logos = _logo_texts(events)
    for i, e in enumerate(events):
        if i in used or e["end"] - e["start"] < min_dur:
            continue
        text = " ".join(str(e.get("text") or "").split()).strip(" ，,、")
        if len(CJK.findall(text)) < 2 or _norm(text) in logos:
            continue
        if any(e["start"] - 0.1 <= (w[0] + w[1]) / 2 <= e["end"] + 0.1 for w in words):
            continue
        out.append(Segment(id=0, start=round(e["start"], 3), end=round(e["end"], 3), text=text, ocr=text, check="ocr"))
    return out


def fuse(words: list[tuple], events: list[dict], acfg) -> list[Segment]:
    """words: (start, end, text, brk); events: [{start, end, text}] (đã sắp theo thời gian)."""
    if not events:
        return resegment(words, acfg)
    events = sorted(events, key=lambda e: e["start"])
    groups: list[tuple[int | None, list[tuple]]] = []
    for w in words:
        ev = _event_of((w[0] + w[1]) / 2, events)
        if groups and groups[-1][0] == ev:
            groups[-1][1].append(w)
        else:
            groups.append((ev, [w]))
    for _ in range(2):
        _refine(groups, events)
    groups = [g for g in groups if g[1]]
    out: list[Segment] = []
    max_chars = int(acfg.max_chars)
    for ev, ws in groups:
        if ev is None:
            for s in resegment(ws, acfg):       # lời thoại không có phụ đề đi kèm: video có phụ đề mà câu này
                s.check = "nghe"                # không có -> có thể Whisper nghe nhầm tiếng nhạc, nên soát lại
                out.append(s)
            continue
        screen = events[ev]["text"]
        text = " ".join("".join(w[2] for w in ws).split()).strip(" ，,、")
        if not any(ch.isalnum() for ch in text):
            continue
        if len(text) > max_chars * 1.6:       # phụ đề đứng yên quá lâu -> chia nhỏ, cùng giữ chữ trên màn hình
            for s in resegment(ws, acfg):
                s.ocr = screen
                out.append(s)
            continue
        out.append(Segment(id=0, start=round(ws[0][0], 3), end=round(ws[-1][1], 3), text=text, ocr=screen))
    out += _ocr_only(words, events, {ev for ev, _ in groups if ev is not None})
    out.sort(key=lambda s: s.start)
    for i, s in enumerate(out, 1):
        s.id = i
    return out
