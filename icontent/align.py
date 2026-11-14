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
            out += resegment(ws, acfg)          # lời thoại không có phụ đề đi kèm
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
    out.sort(key=lambda s: s.start)
    for i, s in enumerate(out, 1):
        s.id = i
    return out
