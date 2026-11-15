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
REACH_SEC = 1.0        # chữ chỉ được ghép vào câu phụ đề hiện trong vòng từng này giây quanh nó


def _near(w: tuple, e: dict, reach: float = REACH_SEC) -> bool:
    return e["start"] - reach <= (w[0] + w[1]) / 2 <= e["end"] + reach


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
            # không kéo chữ sang câu phụ đề ở cách xa nó: chữ giống nhau nhưng nói ở lúc khác thì không phải cùng câu
            if any(not _near(w, events[eb]) for w in ws[k:len(a)]) or any(not _near(w, events[ea]) for w in ws[len(a):k]):
                continue
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


def _tidy(groups: list[tuple[int | None, list[tuple]]], events: list[dict]) -> list[tuple[int | None, list[tuple]]]:
    """Dọn các mẩu lời không có phụ đề đi kèm nằm sát một câu có phụ đề, để không sinh ra câu cụt ("Lên", "Ông"):
    - cuối câu có phụ đề còn dính vài chữ không có trên màn hình, ngay sau là lời không phụ đề -> chuyển sang câu sau
      ("往墙上一挂,啥也" + "不管了" -> "往墙上一挂," + "啥也不管了");
    - mẩu 1-2 chữ không phụ đề nằm sát câu có phụ đề -> nhập vào câu đó; mẩu 1 chữ đứng trơ trọi -> bỏ (thường là
      Whisper nghe nhầm tiếng nhạc, tiếng động)."""
    gs = [(ev, list(ws)) for ev, ws in groups if ws]
    for i in range(len(gs) - 1):
        (ea, a), (eb, b) = gs[i], gs[i + 1]
        if ea is None or eb is not None or b[0][0] - a[-1][1] > 0.3:
            continue
        scr, end = _norm(events[ea]["text"]), events[ea]["end"]
        moved = 0
        while len(a) > 1 and moved < 3:
            t = _norm(a[-1][2])
            if not t or any(ch in scr for ch in t) or a[-1][0] < end - 0.5:
                break
            b.insert(0, a.pop())
            moved += 1
    out: list[tuple[int | None, list[tuple]]] = []
    i = 0
    while i < len(gs):
        ev, ws = gs[i]
        n = len(_norm("".join(w[2] for w in ws)))
        if ev is None and n <= 2:
            nxt = gs[i + 1] if i + 1 < len(gs) else None
            if nxt and nxt[0] is not None and nxt[1][0][0] - ws[-1][1] <= 0.6 and _near(ws[0], events[nxt[0]]):
                gs[i + 1] = (nxt[0], ws + nxt[1])
                i += 1
                continue
            if out and out[-1][0] is not None and ws[0][0] - out[-1][1][-1][1] <= 0.6 and _near(ws[-1], events[out[-1][0]]):
                out[-1] = (out[-1][0], out[-1][1] + ws)
                i += 1
                continue
            if n <= 1:
                i += 1
                continue
        out.append((ev, ws))
        i += 1
    return out


def _span(ws: list[tuple], e: dict) -> tuple[float, float]:
    """Giờ của câu theo lời nói, nhưng không ra ngoài lúc phụ đề hiện quá REACH_SEC (chặn chữ bị đặt sai giờ)."""
    a, b = max(ws[0][0], e["start"] - REACH_SEC), min(ws[-1][1], e["end"] + REACH_SEC)
    if b - a < 0.2:
        a, b = e["start"], e["end"]
    return round(a, 3), round(b, 3)


def fuse(words: list[tuple], events: list[dict], acfg) -> list[Segment]:
    """words: (start, end, text, brk); events: [{start, end, text}] (đã sắp theo thời gian)."""
    from .asr import fix_stray_words

    logos = _logo_texts(events)
    events = sorted((e for e in events if _norm(str(e.get("text") or "")) not in logos), key=lambda e: e["start"])
    words = fix_stray_words(words)
    if not events:
        return resegment(words, acfg)
    groups: list[tuple[int | None, list[tuple]]] = []
    for w in words:
        ev = _event_of((w[0] + w[1]) / 2, events)
        if groups and groups[-1][0] == ev:
            groups[-1][1].append(w)
        else:
            groups.append((ev, [w]))
    for _ in range(2):
        _refine(groups, events)
    groups = _tidy(groups, events)
    out: list[Segment] = []
    partial: dict[int, dict] = {}
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
        a, b = _span(ws, events[ev])
        out.append(Segment(id=0, start=a, end=b, text=text, ocr=screen))
        if len(_norm(text)) < 0.7 * len(_norm(screen)):      # chỉ nghe ra một phần câu: lấy thêm giờ theo phụ đề
            partial[id(out[-1])] = events[ev]
    out += _ocr_only(words, events, {ev for ev, _ in groups if ev is not None})
    out.sort(key=lambda s: s.start)
    for i, s in enumerate(out):
        e = partial.get(id(s))
        if e:
            s.start = round(max(min(s.start, e["start"]), out[i - 1].end if i else 0.0), 3)
            s.end = round(min(max(s.end, e["end"]), out[i + 1].start if i + 1 < len(out) else e["end"]), 3)
    for i, s in enumerate(out, 1):
        s.id = i
    return out
