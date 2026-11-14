"""Quy trình kéo thả: các khối (Ý tưởng, AI viết kịch bản, Vẽ ảnh, Giọng đọc, Dựng video, Thumbnail, Xuất...) nối với nhau thành một dây chuyền,
bấm Chạy là chạy hết từ đầu đến cuối.

Mỗi khối là một bước có sẵn của Studio566 (story.py, thumbs.py...), nên câu chuyện tạo ra vẫn mở được ở Kể chuyện để sửa tay. Dữ liệu chạy qua dây:
text (ý tưởng, kịch bản), images (ảnh của tôi), story (mã câu chuyện), video (đường dẫn), image (đường dẫn thumbnail).

Chạy lại không tốn thêm: AI viết kịch bản nhớ kết quả theo nội dung đầu vào, vẽ ảnh bỏ qua cảnh đã có ảnh, dựng video bỏ qua nếu câu chuyện
không đổi. Khối trả phí (vẽ ảnh) phải được người dùng đồng ý kèm ước tính giá trước khi chạy.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import story as sm
from .util import log, replace_file, safe_name, short_hash

MAX_NODES = 60
FILE_RE = re.compile(r"[0-9a-f]{16}\.(jpg|png|webp)")
MUSIC_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def _p(key, label, type_, default=None, **kw):
    return {"key": key, "label": label, "type": type_, "default": default, **kw}


ASPECTS = [["9:16", "Dọc 9:16 (TikTok, Shorts)"], ["16:9", "Ngang 16:9 (YouTube)"], ["1:1", "Vuông 1:1"]]
STYLE_OPTS = [[k, v] for k, v in sm.STYLE_LABELS.items()]
SUB_OPTS = [["box", "Hộp mờ"], ["classic", "Viền đen"], ["tiktok", "TikTok"], ["pop", "Nổi bật"], ["karaoke", "Karaoke"]]
PROVIDER_OPTS = [["", "Tự chọn (miễn phí trước)"], ["local", "Vẽ trên máy (miễn phí)"], ["gemini", "Google Gemini (trả phí)"], ["openai", "OpenAI (trả phí)"], ["meta", "Meta Muse (trả phí)"],
                 ["cloudflare", "Cloudflare (miễn phí có hạn mức)"]]

NODES: dict[str, dict] = {
    "idea": {"label": "Ý tưởng", "group": "Đầu vào", "icon": "spark", "inputs": [], "outputs": [["text", "text"]],
             "help": "Một hai câu ý tưởng. Nối sang AI viết kịch bản.",
             "params": [_p("text", "Ý tưởng", "textarea", "", placeholder="Ví dụ: chú cá vàng nhỏ tìm đường về biển, bài học về lòng dũng cảm"),
                        _p("seconds", "Độ dài video", "select", 60, options=[[30, "30 giây"], [60, "1 phút"], [90, "1 phút 30"], [120, "2 phút"], [180, "3 phút"]])]},
    "script": {"label": "Kịch bản có sẵn", "group": "Đầu vào", "icon": "file", "inputs": [], "outputs": [["text", "text"]],
               "help": "Dán lời dẫn. Nối sang Chia cảnh (miễn phí) hoặc AI viết kịch bản (AI chia cảnh, gợi ý hình, giữ nguyên lời).",
               "params": [_p("text", "Kịch bản", "textarea", "", placeholder="Mỗi đoạn văn ít nhất một cảnh")]},
    "images": {"label": "Ảnh của tôi", "group": "Đầu vào", "icon": "image", "inputs": [], "outputs": [["images", "images"]],
               "help": "Mỗi ảnh một cảnh, đúng thứ tự. Nối sang Chia cảnh.",
               "params": [_p("files", "Ảnh", "files", [])]},
    "ai_write": {"label": "AI viết kịch bản", "group": "Kịch bản", "icon": "brain", "inputs": [["text", "text", True]], "outputs": [["story", "story"]],
                 "help": "Từ ý tưởng: AI viết lời dẫn, chia cảnh, mô tả hình, lập nhân vật. Từ kịch bản: AI chia cảnh, giữ nguyên lời. Dùng AI trong Cài đặt hoặc key Gemini.",
                 "params": [_p("aspect", "Khung hình", "select", "9:16", options=ASPECTS), _p("style", "Phong cách ảnh", "select", "pixar", options=STYLE_OPTS)]},
    "split": {"label": "Chia cảnh", "group": "Kịch bản", "icon": "scissors", "inputs": [["text", "text", False], ["images", "images", False]],
              "outputs": [["story", "story"]],
              "help": "Không cần AI, miễn phí. Kịch bản chia theo đoạn và câu; có ảnh thì ảnh thứ n vào cảnh thứ n.",
              "params": [_p("aspect", "Khung hình", "select", "9:16", options=ASPECTS), _p("style", "Phong cách ảnh", "select", "", options=STYLE_OPTS)]},
    "char_refs": {"label": "Ảnh mẫu nhân vật", "group": "Hình ảnh", "icon": "wand", "inputs": [["story", "story", True]], "outputs": [["story", "story"]], "paid": True,
                  "help": "AI vẽ ảnh mẫu cho nhân vật chưa có, để các cảnh vẽ sau giữ đúng mặt, quần áo. Trả phí theo nguồn ảnh.",
                  "params": [_p("provider", "Nguồn vẽ", "select", "", options=PROVIDER_OPTS)]},
    "draw": {"label": "Vẽ ảnh từng cảnh", "group": "Hình ảnh", "icon": "image", "inputs": [["story", "story", True]], "outputs": [["story", "story"]], "paid": True,
             "help": "AI vẽ cảnh chưa có ảnh, giữ nhân vật theo ảnh mẫu. Cảnh đã có ảnh không vẽ lại. Trả phí theo nguồn ảnh.",
             "params": [_p("provider", "Nguồn vẽ", "select", "", options=PROVIDER_OPTS)]},
    "stock": {"label": "Video nền miễn phí", "group": "Hình ảnh", "icon": "search", "inputs": [["story", "story", True]], "outputs": [["story", "story"]],
              "help": "Tự tìm video quay thật hợp với từng cảnh trong kho miễn phí có giấy phép thương mại (Pexels, Pixabay, Wikimedia) và tải về. "
                      "Cảnh có video thì dùng video thay ảnh. Nguồn từng clip được ghi lại cạnh video xuất ra.",
              "params": [_p("src", "Kho video", "select", "", options=[["", "Mọi kho đã sẵn sàng"], ["pexels", "Pexels (key miễn phí)"],
                                                                       ["pixabay", "Pixabay (key miễn phí)"], ["wikimedia", "Wikimedia Commons (không cần key)"]]),
                         _p("only_missing", "Chỉ cảnh chưa có clip", "checkbox", True),
                         _p("skip_characters", "Cảnh có nhân vật để vẽ (không chèn người lạ)", "checkbox", True)]},
    "animate": {"label": "AI làm clip từ ảnh", "group": "Hình ảnh", "icon": "film", "inputs": [["story", "story", True]], "outputs": [["story", "story"]], "paid": True,
                "help": "Google Gemini Omni biến ảnh từng cảnh thành clip chuyển động 3 đến 15 giây, giữ đúng nhân vật đã vẽ. "
                        "Cần key Gemini đã bật thanh toán, khoảng 0,07 USD mỗi giây ở 720p. Cảnh đã có clip không làm lại.",
                "params": [_p("res", "Độ nét", "select", "720p", options=[["360p", "360p (~0,023 USD/giây)"], ["720p", "720p (~0,07 USD/giây)"],
                                                                         ["1080p", "1080p (~0,104 USD/giây)"]])]},
    "voice": {"label": "Giọng đọc", "group": "Âm thanh", "icon": "mic", "inputs": [["story", "story", True]], "outputs": [["story", "story"]],
              "help": "Đọc lời dẫn từng cảnh. Có cả Giọng của tôi.",
              "params": [_p("engine", "Bộ giọng", "select", "vieneu", options=[["vieneu", "VieNeu (trên máy)"], ["edge", "Edge (cần mạng)"]]),
                         _p("voice", "Giọng", "voice", ""), _p("speed", "Tốc độ", "range", 1.0, min=0.7, max=1.5, step=0.05)]},
    "music": {"label": "Nhạc nền", "group": "Âm thanh", "icon": "music", "inputs": [["story", "story", True]], "outputs": [["story", "story"]],
              "help": "Nhạc nhỏ đi khi có lời dẫn.",
              "params": [_p("music", "Nhạc", "music", ""), _p("volume", "Âm lượng", "range", 0.12, min=0, max=0.6, step=0.01)]},
    "render": {"label": "Dựng video", "group": "Dựng", "icon": "film", "inputs": [["story", "story", True]], "outputs": [["video", "video"]],
               "help": "Ảnh có máy quay chuyển động, chuyển cảnh, phụ đề, mở đầu, kết thúc.",
               "params": [_p("transition", "Chuyển cảnh", "select", "fade", options=[[k, v] for k, v in sm.TRANSITIONS.items()]),
                          _p("subs", "Phụ đề", "select", "box", options=[["", "Tắt"], *SUB_OPTS]),
                          _p("intro", "Cảnh mở đầu (tiêu đề)", "checkbox", True), _p("intro_sub", "Dòng phụ mở đầu", "text", "", placeholder="Ví dụ: Tập 1"),
                          _p("outro", "Cảnh kết thúc", "checkbox", True), _p("outro_text", "Lời kêu gọi", "text", sm.DEFAULT_OUTRO),
                          _p("outro_sub", "Tên kênh", "text", "", placeholder="@tenkenh")]},
    "thumbnail": {"label": "Thumbnail", "group": "Đầu ra", "icon": "image", "inputs": [["story", "story", True]], "outputs": [["image", "image"]],
                  "help": "Ảnh cảnh có nhân vật, tiêu đề lớn. Mở trang Thumbnail để sửa tiếp.",
                  "params": [_p("aspect", "Khung", "select", "", options=[["", "Theo video"], *ASPECTS]),
                             _p("style", "Kiểu", "select", "noi-bat", options=[["noi-bat", "Nổi bật"], ["dai-mau", "Dải màu"], ["toi-gian", "Tối giản"]]),
                             _p("text", "Chữ (trống: tên câu chuyện)", "text", "")]},
    "editor": {"label": "Mở Trình dựng", "group": "Đầu ra", "icon": "scissors", "inputs": [["story", "story", True]], "outputs": [],
               "help": "Mở câu chuyện trong Trình dựng để tự sắp xếp như CapCut (mở cửa sổ mới).", "params": []},
    "export": {"label": "Xuất bộ đăng bài", "group": "Đầu ra", "icon": "package", "inputs": [["video", "video", True], ["image", "image", False]], "outputs": [],
               "help": "Gom video, thumbnail và mô tả vào một thư mục trong output, sẵn để đăng.", "params": []},
}

TEMPLATES = [
    {"id": "ai_story", "name": "Truyện AI từ ý tưởng", "desc": "Ý tưởng → AI viết → ảnh mẫu nhân vật → vẽ cảnh → giọng → nhạc → dựng → thumbnail → xuất",
     "chain": ["idea", "ai_write", "char_refs", "draw", "voice", "music", "render", "thumbnail", "export"]},
    {"id": "my_images", "name": "Video từ ảnh của tôi", "desc": "Ảnh của tôi + kịch bản → chia cảnh → giọng → nhạc → dựng → thumbnail → xuất. Miễn phí.",
     "chain": ["images", "split", "voice", "music", "render", "thumbnail", "export"], "extra": [["script", "split", 0]]},
    {"id": "script_ai_images", "name": "Kịch bản có sẵn, AI vẽ", "desc": "Kịch bản → AI chia cảnh và gợi ý hình → vẽ cảnh → giọng → dựng → thumbnail",
     "chain": ["script", "ai_write", "draw", "voice", "render", "thumbnail", "export"]},
    {"id": "director", "name": "Tổng đạo diễn AI (miễn phí)",
     "desc": "Ý tưởng → AI viết → video quay thật cho từng cảnh → cảnh thiếu thì vẽ → giọng → nhạc → dựng → thumbnail → xuất. "
             "Không tốn tiền khi dùng Gemini gói miễn phí hoặc Mô-đun AI miễn phí.",
     "chain": ["idea", "ai_write", "stock", "draw", "voice", "music", "render", "thumbnail", "export"]},
    {"id": "animated", "name": "Truyện có chuyển động bằng clip AI (trả phí)",
     "desc": "Ý tưởng → AI viết → ảnh mẫu nhân vật → vẽ cảnh → AI làm clip chuyển động → giọng → nhạc → dựng → xuất. "
             "Cần bật tính năng trả phí và key Gemini đã bật thanh toán (khoảng 0,07 USD mỗi giây clip).",
     "chain": ["idea", "ai_write", "char_refs", "draw", "animate", "voice", "music", "render", "thumbnail", "export"]},
    {"id": "blank", "name": "Trống", "desc": "Tự kéo khối từ bảng bên trái", "chain": []},
]


def public_nodes() -> dict:
    return {"nodes": NODES, "templates": [{k: v for k, v in t.items() if k in ("id", "name", "desc")} for t in TEMPLATES]}


def _defaults(ntype: str) -> dict:
    return {p["key"]: p["default"] for p in NODES[ntype]["params"]}


def from_template(tid: str, name: str = "") -> dict:
    t = next((x for x in TEMPLATES if x["id"] == tid), TEMPLATES[-1])
    nodes, edges = [], []
    for i, ntype in enumerate(t["chain"]):
        row, col = divmod(i, 4)      # mỗi hàng 4 khối, đọc từ trái sang phải như chữ: vừa màn hình mà chữ trong khối vẫn đọc được
        nid = f"k{i + 1}"
        nodes.append({"id": nid, "type": ntype, "x": 60 + col * 300, "y": 340 + row * 360, "params": _defaults(ntype)})
        # mỗi đầu vào nối với khối gần nhất phía trước có đúng loại dữ liệu (Thumbnail lấy câu chuyện, Xuất lấy video và thumbnail)
        for pin, (_, kind, _req) in enumerate(NODES[ntype]["inputs"]):
            src = next((m for m in reversed(nodes[:-1]) if any(o[1] == kind for o in NODES[m["type"]]["outputs"])), None)
            if src is not None:
                oi = next(k for k, o in enumerate(NODES[src["type"]]["outputs"]) if o[1] == kind)
                edges.append({"id": f"e{len(edges) + 1}", "from": src["id"], "out": oi, "to": nid, "in": pin})
    for j, (ntype, to_type, out_i) in enumerate(t.get("extra") or []):
        target = next(n for n in nodes if n["type"] == to_type)
        nid = f"x{j + 1}"
        nodes.append({"id": nid, "type": ntype, "x": target["x"] - 150, "y": target["y"] - 300, "params": _defaults(ntype)})
        kind = NODES[ntype]["outputs"][out_i][1]
        pin = next(k for k, p in enumerate(NODES[to_type]["inputs"]) if p[1] == kind)
        edges.append({"id": f"ex{j + 1}", "from": nid, "out": out_i, "to": target["id"], "in": pin})
    return {"id": "w" + uuid.uuid4().hex[:8], "name": name or t["name"], "nodes": nodes, "edges": edges, "memo": {}, "last": None,
            "template": t["id"], "touched": False, "created": round(time.time(), 3), "updated": round(time.time(), 3)}


# ------------------------------------------------------------------ lưu trữ
class WorkflowStore:
    _locks: dict[str, threading.RLock] = {}
    _guard = threading.Lock()

    def __init__(self, root: Path):
        self.root = Path(root)

    def _lock(self, wid: str) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault(str((self.root / wid).resolve()), threading.RLock())

    def path(self, wid: str) -> Path:
        if not re.fullmatch(r"w[0-9a-f]{8}", wid or ""):
            raise KeyError("Không có quy trình này")
        return self.root / f"{wid}.json"

    def files(self, wid: str) -> Path:
        self.path(wid)
        return self.root / wid

    def list(self) -> list[dict]:
        out = []
        if self.root.is_dir():
            for f in self.root.glob("w*.json"):
                try:
                    w = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                last = w.get("last") or {}
                out.append({"id": w["id"], "name": w.get("name") or "Quy trình", "updated": w.get("updated") or 0, "nodes": len(w.get("nodes") or []),
                            "types": [n["type"] for n in w.get("nodes") or []][:12], "state": last.get("state") or "", "at": last.get("at") or 0,
                            "template": w.get("template") or "", "touched": bool(w.get("touched", True))})
        return sorted(out, key=lambda x: -x["updated"])

    def get(self, wid: str) -> dict:
        p = self.path(wid)
        with self._lock(wid):
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise KeyError("Không có quy trình này") from None

    def write(self, w: dict) -> dict:
        p = self.path(w["id"])
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock(w["id"]):
            w["updated"] = round(time.time(), 3)
            tmp = p.with_name(f"{p.name}.{uuid.uuid4().hex[:6]}.part")
            tmp.write_text(json.dumps(w, ensure_ascii=False), encoding="utf-8")
            replace_file(tmp, p)
        return w

    def update(self, wid: str, fn) -> dict:
        """Đọc, sửa, ghi trong cùng một khóa: giao diện tự lưu trong lúc quy trình đang chạy không xóa mất bộ nhớ chạy hay kết quả."""
        with self._lock(wid):
            w = self.get(wid)
            fn(w)
            return self.write(w)

    def delete(self, wid: str) -> None:
        self.path(wid).unlink(missing_ok=True)
        shutil.rmtree(self.root / wid, ignore_errors=True)


def clean_graph(current: dict, incoming: dict) -> dict:
    """Áp phần giao diện gửi lên (tên, khối, dây) lên bản đang lưu. Kết quả chạy và bộ nhớ chạy (memo) do máy chủ giữ."""
    out = dict(current)
    out["name"] = str(incoming.get("name") or current.get("name") or "Quy trình").strip()[:80]
    nodes, seen = [], set()
    for n in (incoming.get("nodes") or [])[:MAX_NODES]:
        nid, ntype = str(n.get("id") or ""), n.get("type")
        if ntype not in NODES or not re.fullmatch(r"[a-z]\w{0,15}", nid) or nid in seen:
            continue
        seen.add(nid)
        params = _defaults(ntype)
        for p in NODES[ntype]["params"]:
            v = (n.get("params") or {}).get(p["key"], p["default"])
            if p["type"] in ("text", "textarea", "voice", "music"):
                v = str(v or "")[:12000 if p["type"] == "textarea" else 300]
            elif p["type"] == "checkbox":
                v = bool(v)
            elif p["type"] == "range":
                try:
                    v = min(p["max"], max(p["min"], float(v)))
                except (TypeError, ValueError):
                    v = p["default"]
            elif p["type"] == "select":
                ok = [o[0] for o in p["options"]]
                v = v if v in ok else (int(v) if str(v).isdigit() and int(v) in ok else p["default"])
            elif p["type"] == "files":
                v = [f for f in (v or []) if isinstance(f, str) and FILE_RE.fullmatch(f)][:200]
            params[p["key"]] = v
        try:
            x, y = float(n.get("x") or 0), float(n.get("y") or 0)
        except (TypeError, ValueError):
            x = y = 0.0
        nodes.append({"id": nid, "type": ntype, "x": round(max(-5000, min(20000, x)), 1), "y": round(max(-5000, min(20000, y)), 1), "params": params})
    by_id = {n["id"]: n for n in nodes}
    edges, taken = [], set()
    for e in incoming.get("edges") or []:
        a, b = by_id.get(e.get("from")), by_id.get(e.get("to"))
        try:
            oi, ii = int(e.get("out") or 0), int(e.get("in") or 0)
        except (TypeError, ValueError):
            continue
        if not a or not b or a is b or not 0 <= oi < len(NODES[a["type"]]["outputs"]) or not 0 <= ii < len(NODES[b["type"]]["inputs"]):
            continue
        if NODES[a["type"]]["outputs"][oi][1] != NODES[b["type"]]["inputs"][ii][1] or (b["id"], ii) in taken:
            continue      # sai kiểu dữ liệu, hoặc đầu vào đã có dây (mỗi đầu vào một dây)
        taken.add((b["id"], ii))
        eid = str(e.get("id") or "")
        eid = eid if re.fullmatch(r"[A-Za-z0-9_-]{1,20}", eid) and eid not in {x["id"] for x in edges} else f"e{len(edges) + 1}x{uuid.uuid4().hex[:4]}"
        edges.append({"id": eid, "from": a["id"], "out": oi, "to": b["id"], "in": ii})
    out["nodes"], out["edges"] = nodes, edges
    out["touched"] = True      # người dùng đã sửa: bấm lại mẫu thì tạo quy trình mới, không mở lại cái này
    return out


# ------------------------------------------------------------------ kiểm tra, thứ tự chạy
def order(w: dict) -> list[dict]:
    """Thứ tự chạy (khối nguồn trước). Có vòng lặp thì báo lỗi."""
    nodes = {n["id"]: n for n in w["nodes"]}
    indeg = {nid: 0 for nid in nodes}
    nxt: dict[str, list[str]] = {nid: [] for nid in nodes}
    for e in w["edges"]:
        indeg[e["to"]] += 1
        nxt[e["from"]].append(e["to"])
    ready = sorted((nid for nid, d in indeg.items() if d == 0), key=lambda k: (nodes[k]["x"], nodes[k]["y"]))
    out = []
    while ready:
        nid = ready.pop(0)
        out.append(nodes[nid])
        for m in nxt[nid]:
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
    if len(out) != len(nodes):
        raise ValueError("Các khối nối thành vòng tròn: bỏ bớt một dây")
    return out


def problems(w: dict) -> dict[str, str]:
    """Khối nào chưa chạy được và vì sao (thiếu dây vào, thiếu nội dung)."""
    have = {(e["to"], e["in"]) for e in w["edges"]}
    out = {}
    for n in w["nodes"]:
        spec = NODES[n["type"]]
        missing = [p for i, p in enumerate(spec["inputs"]) if p[2] and (n["id"], i) not in have]
        if missing:
            out[n["id"]] = "Chưa nối đầu vào: " + ", ".join(KIND_LABEL[p[1]] for p in missing)
        elif n["type"] == "split" and not any((n["id"], i) in have for i in range(2)):
            out[n["id"]] = "Nối Kịch bản hoặc Ảnh của tôi vào đây"
        elif n["type"] in ("idea", "script") and not str(n["params"].get("text") or "").strip():
            out[n["id"]] = "Chưa viết nội dung"
        elif n["type"] == "images" and not n["params"].get("files"):
            out[n["id"]] = "Chưa chọn ảnh"
        elif (msg := _paid_problem(n)):
            out[n["id"]] = msg
    return out


def _paid_problem(n: dict) -> str:
    """Khối tính tiền khi đang tắt tính năng trả phí (Cài đặt, mục Chi phí): báo trước khi chạy, không chạy tới giữa chừng mới lỗi."""
    from . import imagegen, videogen
    from .paid import allowed
    off = "Đang tắt tính năng trả phí: bật ở Cài đặt, mục Chi phí, hoặc bỏ khối này"
    if n["type"] == "animate":
        if not allowed():
            return off
        if not videogen.ready("omni"):
            return "Cần key Gemini đã bật thanh toán (Cài đặt, mục Kết nối AI hoặc Tạo ảnh AI)"
    if n["type"] in ("draw", "char_refs") and imagegen.is_paid(n["params"].get("provider") or "") and not allowed():
        return "Nguồn vẽ này tính tiền mà đang tắt tính năng trả phí: chọn Tự chọn hoặc Vẽ trên máy, hoặc bật ở Cài đặt, mục Chi phí"
    return ""


KIND_LABEL = {"text": "chữ", "images": "ảnh", "story": "câu chuyện", "video": "video", "image": "thumbnail"}


def _idea_value(n: dict) -> dict:
    return {"text": str(n["params"].get("text") or "").strip(), "seconds": int(n["params"].get("seconds") or 60), "kind": "idea"}


def _script_value(n: dict) -> dict:
    return {"text": str(n["params"].get("text") or "").strip(), "kind": "script"}


def _images_value(n: dict, folder: Path) -> dict:
    return {"files": [str(folder / f) for f in n["params"].get("files") or [] if (folder / f).is_file()]}


def _ai_write_key(src: dict, p: dict) -> str:
    return short_hash("ai_write", json.dumps(src, ensure_ascii=False, sort_keys=True), p.get("style") or "", p.get("aspect") or "")


def _split_key(text: str, files: list[str], p: dict) -> str:
    return short_hash("split", text, *files, p.get("style") or "", p.get("aspect") or "")


def _producer(nid: str, by_id: dict, edges: list) -> dict | None:
    """Khối tạo ra câu chuyện mà khối này nhận (AI viết kịch bản hoặc Chia cảnh), đi ngược theo dây câu chuyện."""
    seen = set()
    cur = nid
    while cur and cur not in seen:
        seen.add(cur)
        n = by_id[cur]
        if n["type"] in ("ai_write", "split"):
            return n
        e = next((x for x in edges if x["to"] == cur and NODES[n["type"]]["inputs"][x["in"]][1] == "story"), None)
        if not e:
            return None
        cur = e["from"]
    return None


def _producer_inputs(prod: dict, by_id: dict, edges: list, folder: Path) -> dict:
    """Giá trị đầu vào của khối tạo câu chuyện, tính từ khối Ý tưởng, Kịch bản, Ảnh (các khối này không gọi gì bên ngoài)."""
    out = {}
    for e in edges:
        if e["to"] != prod["id"]:
            continue
        src = by_id[e["from"]]
        name = NODES[prod["type"]]["inputs"][e["in"]][0]
        if src["type"] == "idea":
            out[name] = _idea_value(src)
        elif src["type"] == "script":
            out[name] = _script_value(src)
        elif src["type"] == "images":
            out[name] = _images_value(src, folder)
    return out


def _expected_key(prod: dict, ins: dict) -> str:
    if prod["type"] == "ai_write":
        return _ai_write_key(ins.get("text") or {}, prod["params"])
    return _split_key((ins.get("text") or {}).get("text") or "", (ins.get("images") or {}).get("files") or [], prod["params"])


def estimate(w: dict, store, wstore=None) -> dict:
    """Số ảnh trả phí ước tính và giá, để hỏi người dùng trước khi chạy.
    Câu chuyện của lần chạy trước chỉ được tính là có sẵn khi đầu vào của nó không đổi: đổi ý tưởng thì lúc chạy sẽ ra câu chuyện mới,
    vẽ lại từ đầu, nên phải hỏi lại."""
    from . import imagegen
    prices = {p["id"]: p for p in imagegen.public()}
    memo = w.get("memo") or {}
    edges = w["edges"]
    by_id = {n["id"]: n for n in w["nodes"]}
    folder = wstore.files(w["id"]) if wstore else Path(".")
    total, lines = 0, []
    chain_provider: dict[str, str] = {}      # khối tạo câu chuyện -> nguồn ảnh khối trả phí trước đã ghi vào câu chuyện
    for n in order(w):
        if not NODES[n["type"]].get("paid"):
            continue
        prod = _producer(n["id"], by_id, edges)
        ins = _producer_inputs(prod, by_id, edges, folder) if prod else {}
        s = None
        m = memo.get(prod["id"]) if prod else None
        if prod and m and m.get("sid") and m.get("key") == _expected_key(prod, ins):
            try:
                s = store.get(m["sid"])
            except KeyError:
                s = None
        if n["type"] == "animate":
            from . import videogen
            res = n["params"].get("res") or videogen.DEFAULT_RES
            if s:
                todo = [sc for sc in s["scenes"] if not sc.get("clip")]
                secs = sum(videogen.seconds_for(sm.estimate_seconds(s, sc)) for sc in todo)
                k = len(todo)
            else:
                src = ins.get("text") or {}
                talk = int(src.get("seconds") or 60) if src.get("kind") == "idea" else max(10, round(len(src.get("text") or "") / 15))
                k = max(3, min(40, round(talk / 9)))
                secs = max(talk + k, k * 4)      # mỗi cảnh dài theo lời dẫn cộng chút nghỉ, tối thiểu vài giây
            if not k:
                continue
            ok = videogen.ready("omni")
            total += k
            lines.append({"node": n["id"], "label": NODES[n["type"]]["label"], "images": k, "unit": "clip", "provider": "omni" if ok else "",
                          "provider_name": videogen.PROVIDERS["omni"]["name"] if ok else "chưa có key Gemini",
                          "price": f"khoảng {videogen.price(secs, res):.2f} USD cho {secs} giây {res}".replace(".", ","),
                          "billing": videogen.status("omni").get("state") == "billing"})
            continue
        if n["type"] == "draw":
            if s:
                k = sum(1 for sc in s["scenes"] if not sc.get("image"))
            elif prod and prod["type"] == "split":
                text = (ins.get("text") or {}).get("text") or ""
                files = (ins.get("images") or {}).get("files") or []
                k = max(0, max(len(sm.split_script(text)) if text.strip() else 0, len(files)) - len(files))
            else:
                src = ins.get("text") or {}
                k = max(3, min(40, round(int(src.get("seconds") or 60) / 9))) if src.get("kind") == "idea" else max(3, round(len(src.get("text") or "") / 170))
        else:
            if s:
                k = sum(1 for c in s["characters"] if not c.get("refs") and c.get("description"))
            else:
                k = 0 if prod and prod["type"] == "split" else 2      # chia cảnh không tạo nhân vật; AI thường viết 1 đến 3 nhân vật
        key = prod["id"] if prod else n["id"]
        if n["params"].get("provider"):      # khối trả phí ghi nguồn ảnh vào câu chuyện, khối sau "tự chọn" sẽ dùng đúng nguồn đó
            chain_provider[key] = n["params"]["provider"]
        want = chain_provider.get(key) or (s or {}).get("image_provider") or ""
        if not k:
            continue
        try:
            prov = imagegen.pick(want)
        except imagegen.ImageGenError:
            prov = ""      # chưa có key: khối vẽ ảnh sẽ báo lỗi rõ ràng khi tới lượt, không chặn ở bước ước tính
        if not prov:
            lines.append({"node": n["id"], "label": NODES[n["type"]]["label"], "images": k, "provider": "", "provider_name": "chưa có key tạo ảnh", "price": ""})
            continue
        if prov == "local":
            continue      # vẽ trên máy: miễn phí, không cần hỏi
        total += k
        lines.append({"node": n["id"], "label": NODES[n["type"]]["label"], "images": k, "provider": prov,
                      "provider_name": (prices.get(prov) or {}).get("name") or prov, "price": (prices.get(prov) or {}).get("price") or "",
                      "billing": (prices.get(prov) or {}).get("status") == "billing"})
    return {"images": total, "lines": lines}


# ------------------------------------------------------------------ chạy
class Stopped(Exception):
    pass


class Run:
    """Một lượt chạy: trạng thái từng khối cho giao diện xem."""

    def __init__(self, w: dict):
        self.wid = w["id"]
        self.state = "running"
        self.error = ""
        self.at = round(time.time(), 3)
        self.nodes = {n["id"]: {"state": "waiting", "message": "", "progress": None, "preview": None} for n in w["nodes"]}
        self.stop = threading.Event()
        self.lock = threading.Lock()

    def set(self, nid, **kw):
        with self.lock:
            self.nodes[nid].update(kw)

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps({"state": self.state, "error": self.error, "at": self.at, "nodes": self.nodes}, default=str))


def _q(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


def _story_preview(store, sid: str, images: bool = False) -> dict:
    s = store.get(sid)
    pv = {"story": sid, "title": s.get("title") or "", "scenes": len(s["scenes"]), "characters": [c["name"] for c in s.get("characters") or []][:6]}
    if images:
        imgs = [sc["image"] for sc in s["scenes"] if sc.get("image")]
        pv["images"] = [f"/api/stories/{_q(sid)}/file/img/{_q(n)}" for n in imgs[:8]]
        pv["have"] = len(imgs)
    return pv


def execute(w: dict, run: Run, store, st, wstore, open_editor=None, render=None) -> None:
    """Chạy cả quy trình. Lỗi ở một khối thì dừng, các khối sau ghi là chưa chạy."""
    cfg = st.cfg()
    seq = order(w)
    bad = problems(w)
    if bad:
        for nid, msg in bad.items():
            run.set(nid, state="error", message=msg)
        raise ValueError("Có khối chưa sẵn sàng: " + "; ".join(f"{_label(w, k)}: {v}" for k, v in bad.items()))
    values: dict[tuple[str, int], object] = {}
    memo = w.setdefault("memo", {})
    by_id = {n["id"]: n for n in w["nodes"]}

    def remember(nid, data):
        memo[nid] = data
        wstore.update(w["id"], lambda x: x.setdefault("memo", {}).update({nid: data}))

    for n in seq:
        if run.stop.is_set():
            raise Stopped()
        ins = {}
        for e in w["edges"]:
            if e["to"] == n["id"] and (e["from"], e["out"]) in values:
                ins[NODES[n["type"]]["inputs"][e["in"]][0]] = values[(e["from"], e["out"])]
        run.set(n["id"], state="running", message="Đang chạy", progress=None)
        t0 = time.time()

        def report(frac=None, msg=None, nid=n["id"]):
            if run.stop.is_set():
                raise Stopped()
            kw = {}
            if frac is not None:
                kw["progress"] = max(0.0, min(1.0, float(frac)))
            if msg:
                kw["message"] = str(msg)[:160]
            run.set(nid, **kw)
        try:
            outs, preview = RUNNERS[n["type"]](n, ins, report, ctx={"cfg": cfg, "store": store, "st": st, "w": w, "memo": memo, "remember": remember,
                                                                 "wstore": wstore, "by_id": by_id, "open_editor": open_editor, "render": render})
        except Stopped:
            run.set(n["id"], state="stopped", message="Đã dừng")
            raise
        except Exception as e:
            run.set(n["id"], state="error", message=str(e)[:400] or type(e).__name__)
            raise
        for i, v in enumerate(outs):
            values[(n["id"], i)] = v
        run.set(n["id"], state="done", progress=1.0, message=f"Xong sau {time.time() - t0:.0f} giây", preview=preview)


def _label(w, nid) -> str:
    n = next((x for x in w["nodes"] if x["id"] == nid), None)
    return NODES[n["type"]]["label"] if n else nid


# ------------------------------------------------------------------ từng khối
def _run_idea(n, ins, report, ctx):
    v = _idea_value(n)
    return [v], {"text": v["text"][:140]}


def _run_script(n, ins, report, ctx):
    v = _script_value(n)
    return [v], {"text": v["text"][:140], "chars": len(v["text"])}


def _run_images(n, ins, report, ctx):
    v = _images_value(n, ctx["wstore"].files(ctx["w"]["id"]))
    if not v["files"]:
        raise ValueError("Chưa có ảnh nào (ảnh đã bị xóa?)")
    return [v], {"images": [f"/api/workflows/{_q(ctx['w']['id'])}/files/{_q(Path(f).name)}" for f in v["files"][:8]], "count": len(v["files"])}


def _new_story(store, title, params) -> dict:
    s = store.create(title or "Câu chuyện")
    s = store.update(s["id"], lambda x: x.update(aspect=params.get("aspect") if params.get("aspect") in sm.SIZES else "9:16",
                                               style=params.get("style") if params.get("style") in sm.STYLES else ""))
    return s


def _reuse(ctx, nid, key) -> str:
    """Câu chuyện đã tạo lần trước với đúng đầu vào này (không gọi AI lại, không tạo câu chuyện trùng)."""
    m = ctx["memo"].get(nid) or {}
    if m.get("key") == key and m.get("sid"):
        try:
            ctx["store"].get(m["sid"])
            return m["sid"]
        except KeyError:
            pass
    return ""


def _run_ai_write(n, ins, report, ctx):
    src = ins["text"]
    p = n["params"]
    key = _ai_write_key(src, p)
    sid = _reuse(ctx, n["id"], key)
    store = ctx["store"]
    if sid:
        report(1, "Dùng lại kịch bản đã viết (đầu vào không đổi)")
        return [{"sid": sid}], {**_story_preview(store, sid), "reused": True}
    report(None, "AI đang viết kịch bản")
    if src.get("kind") == "script":
        data = sm.write_script(ctx["cfg"], script=src["text"], style=p.get("style") or "")
    else:
        data = sm.write_script(ctx["cfg"], topic=src["text"], seconds=int(src.get("seconds") or 60), style=p.get("style") or "")
    s = _new_story(store, data.get("title") or src["text"][:60], p)
    store.update(s["id"], lambda x: sm.apply_script(x, data, replace=True))
    ctx["remember"](n["id"], {"key": key, "sid": s["id"]})
    return [{"sid": s["id"]}], _story_preview(store, s["id"])


def _run_split(n, ins, report, ctx):
    p = n["params"]
    text = (ins.get("text") or {}).get("text") or ""
    files = (ins.get("images") or {}).get("files") or []
    key = _split_key(text, files, p)
    store = ctx["store"]
    sid = _reuse(ctx, n["id"], key)
    if sid:
        report(1, "Dùng lại câu chuyện đã chia (đầu vào không đổi)")
        return [{"sid": sid}], {**_story_preview(store, sid, images=True), "reused": True}
    parts = sm.split_script(text) if text.strip() else []
    k = max(len(parts), len(files))
    if not k:
        raise ValueError("Không có kịch bản hay ảnh nào để chia cảnh")
    title = (parts[0][:60] if parts else "Video từ ảnh của tôi")
    s = _new_story(store, title, p)
    scenes = [{"id": sm.new_id("n"), "text": parts[i] if i < len(parts) else "", "prompt": "", "characters": [], "motion": "auto",
               "image": "", "images": [], "created": time.time()} for i in range(min(k, sm.MAX_SCENES))]
    store.update(s["id"], lambda x: x.update(scenes=scenes))
    for i, f in enumerate(files[: len(scenes)]):
        report(i / max(1, len(files)), f"Thêm ảnh {i + 1}/{len(files)}")
        sm.add_scene_image(store, s["id"], scenes[i]["id"], Path(f).read_bytes(), "upload")
    ctx["remember"](n["id"], {"key": key, "sid": s["id"]})
    return [{"sid": s["id"]}], _story_preview(store, s["id"], images=True)


def _run_char_refs(n, ins, report, ctx):
    store, sid = ctx["store"], ins["story"]["sid"]
    s = store.get(sid)
    todo = [c for c in s.get("characters") or [] if not c.get("refs")]
    prov = n["params"].get("provider") or ""
    if prov:
        store.update(sid, lambda x: x.update(image_provider=prov))
    for i, c in enumerate(todo):
        if not c.get("description"):
            continue      # chưa có mô tả thì không vẽ được ảnh mẫu, cảnh vẫn vẽ theo mô tả trong lời nhắn
        report(i / max(1, len(todo)), f"Vẽ ảnh mẫu {c['name']} ({i + 1}/{len(todo)})")
        sm.generate_character_ref(store, sid, c["id"], ctx["cfg"])
    s = store.get(sid)
    refs = [(c["name"], c["refs"][0]) for c in s.get("characters") or [] if c.get("refs")]
    return [{"sid": sid}], {"drawn": len(todo), "images": [f"/api/stories/{_q(sid)}/file/ref/{_q(r)}" for _, r in refs[:6]],
                            "names": [nm for nm, _ in refs[:6]]}


def _run_draw(n, ins, report, ctx):
    store, sid = ctx["store"], ins["story"]["sid"]
    prov = n["params"].get("provider") or ""
    if prov:
        store.update(sid, lambda x: x.update(image_provider=prov))
    s = store.get(sid)
    todo = [sc for sc in s["scenes"] if not sc.get("image")]
    for i, sc in enumerate(todo):
        report(i / max(1, len(todo)), f"Vẽ cảnh {i + 1}/{len(todo)}")
        if sc.get("prompt") or sc.get("text"):
            sm.generate_scene_image(store, sid, sc["id"], ctx["cfg"], skip_if_has_image=True)
    s = store.get(sid)
    left = [i + 1 for i, sc in enumerate(s["scenes"]) if not sc.get("image")]
    if left:
        raise ValueError("Cảnh " + ", ".join(map(str, left[:10])) + " chưa có ảnh (cảnh không có lời và mô tả thì không vẽ được)")
    return [{"sid": sid}], {**_story_preview(store, sid, images=True), "drawn": len(todo)}


def _run_stock(n, ins, report, ctx):
    store, sid = ctx["store"], ins["story"]["sid"]
    src = n["params"].get("src") or ""
    if src:
        store.update(sid, lambda x: x.update(stock_src=src))
    r = sm.stock_fill(store, sid, ctx["cfg"], only_missing=bool(n["params"].get("only_missing", True)), src=src, report=report, check=lambda: report(),
                      skip_characters=bool(n["params"].get("skip_characters", True)))
    s = store.get(sid)
    left = [i + 1 for i, sc in enumerate(s["scenes"]) if not sc.get("clip") and not sc.get("image")]
    if left and not _later(ctx, n["id"], "draw"):      # có khối Vẽ ảnh phía sau thì cảnh thiếu sẽ được vẽ
        raise ValueError("Cảnh " + ", ".join(map(str, left[:10])) + " chưa có video hay ảnh" + (f" ({r['error']})" if r.get("error") else "")
                         + ". Sửa từ khóa ở cảnh đó trong Kể chuyện, hoặc nối thêm khối Vẽ ảnh từng cảnh trước khối này.")
    return [{"sid": sid}], {**_story_preview(store, sid, images=True), "clips": r["done"], "note": r.get("error") or ""}


def _later(ctx, nid: str, ntype: str) -> bool:
    """Có khối loại ntype nằm phía sau khối nid (theo dây nối) không."""
    w = ctx.get("w") or {}
    by_id = {x["id"]: x for x in w.get("nodes") or []}
    seen, todo = set(), [nid]
    while todo:
        cur = todo.pop()
        for e in w.get("edges") or []:
            if e["from"] == cur and e["to"] not in seen:
                seen.add(e["to"])
                if (by_id.get(e["to"]) or {}).get("type") == ntype:
                    return True
                todo.append(e["to"])
    return False


def _run_animate(n, ins, report, ctx):
    from . import videogen
    store, sid = ctx["store"], ins["story"]["sid"]
    res = n["params"].get("res") or videogen.DEFAULT_RES
    store.update(sid, lambda x: x.update(video_res=res if res in videogen.RESOLUTIONS else videogen.DEFAULT_RES))
    s = store.get(sid)
    todo = [sc for sc in s["scenes"] if not sc.get("clip")]
    done = 0
    for i, sc in enumerate(todo):
        report(i / max(1, len(todo)), f"AI làm clip cảnh {i + 1}/{len(todo)}")
        sm.animate_scene(store, sid, sc["id"], ctx["cfg"], report=lambda f, m, i=i: report(i / max(1, len(todo)), f"Cảnh {i + 1}/{len(todo)}: {m}"),
                         check=lambda: report())
        done += 1
    return [{"sid": sid}], {**_story_preview(store, sid, images=True), "clips": done}


def _run_voice(n, ins, report, ctx):
    store, sid = ctx["store"], ins["story"]["sid"]
    p = n["params"]
    store.update(sid, lambda x: x.update(voice={"engine": p.get("engine") or "vieneu", "voice": p.get("voice") or "", "speed": float(p.get("speed") or 1.0)}))
    s = store.get(sid)
    voices = sm.narrate(store, sid, s, on_step=lambda k, total: report(k / max(1, total), f"Đọc cảnh {k}/{total}"))
    secs = sum(v["dur"] for v in voices)
    return [{"sid": sid}], {"seconds": round(secs, 1), "scenes": sum(1 for v in voices if v["wav"])}


def _run_music(n, ins, report, ctx):
    store, sid = ctx["store"], ins["story"]["sid"]
    name = str(n["params"].get("music") or "")
    path = sm._music_path(str(sm.MUSIC_DIR / name)) if name else ""
    store.update(sid, lambda x: x.update(music={"path": path, "volume": float(n["params"].get("volume") or 0)}))
    return [{"sid": sid}], {"music": Path(path).name if path else "Không có nhạc"}


def _run_render(n, ins, report, ctx):
    from .util import probe
    store, sid = ctx["store"], ins["story"]["sid"]
    p = n["params"]

    def setup(x):
        x["transition"] = p.get("transition") if p.get("transition") in sm.TRANSITIONS else "fade"
        x["subs"] = {"enabled": bool(p.get("subs")), "style": p.get("subs") if p.get("subs") in sm.SUB_STYLES else "box"}
        x["intro"] = {"enabled": bool(p.get("intro")), "text": (x.get("intro") or {}).get("text") or "", "sub": str(p.get("intro_sub") or "")}
        x["outro"] = {"enabled": bool(p.get("outro")), "text": str(p.get("outro_text") or sm.DEFAULT_OUTRO), "sub": str(p.get("outro_sub") or "")}
    s = store.update(sid, setup)
    key = render_key(s)
    m = ctx["memo"].get(n["id"]) or {}
    out = Path(s.get("output") or "")
    if m.get("key") == key and out.is_file() and m.get("path") == str(out):
        report(1, "Dùng lại video đã dựng (câu chuyện không đổi)")
    else:
        report(None, "Đang dựng video")
        if ctx.get("render"):      # qua hàng đợi chung của Studio566: không dựng song song với video khác, không trùng lượt dựng của Kể chuyện
            out = Path(ctx["render"](sid, report))
        else:
            out = sm.render_story(store, sid, ctx["cfg"], Path(ctx["cfg"].output_dir))
        ctx["remember"](n["id"], {"key": render_key(store.get(sid)), "path": str(out)})
    dur = float(probe(out).get("duration") or 0)
    return [{"path": str(out), "sid": sid}], {"video": f"/api/stories/{_q(sid)}/video?t={int(out.stat().st_mtime)}", "duration": round(dur, 1),
                                               "name": out.name, "story": sid}


def render_key(s: dict) -> str:
    """Những gì làm video kể chuyện khác đi, kể cả kiểu chuyển cảnh riêng từng cảnh và thời lượng chuyển."""
    return short_hash("render", sm.editor_signature(s), str(s.get("transition")), str(s.get("trans_dur")), json.dumps(s.get("subs"), sort_keys=True),
                      json.dumps([sc.get("transition") or "" for sc in s.get("scenes") or []]))


def _run_thumbnail(n, ins, report, ctx):
    from .thumbs import auto_story_thumb
    store, sid = ctx["store"], ins["story"]["sid"]
    p = n["params"]
    folder = store.folder(sid)
    from .thumbs import load_project
    if load_project(folder):      # đã tự thiết kế ở trang Thumbnail: không ghi đè bằng bản tự động
        dst = folder / "thumb.jpg"
        report(1, "Giữ thumbnail đã thiết kế ở trang Thumbnail")
    else:
        auto_story_thumb(store, sid, p.get("aspect") or "", p.get("style") or "noi-bat", p.get("text") or "")
        dst = folder / "thumb.jpg"
    return [{"path": str(dst), "sid": sid}], {"image": f"/api/thumbs/story/{_q(sid)}/image?v={int(dst.stat().st_mtime)}", "story": sid}


def _run_editor(n, ins, report, ctx):
    sid = ins["story"]["sid"]
    opener = ctx.get("open_editor")
    if not opener:
        raise RuntimeError("Không mở được Trình dựng từ đây")
    opener(sid)
    return [], {"story": sid, "opened": True}


def _run_export(n, ins, report, ctx):
    from .util import probe
    video = Path(ins["video"]["path"])
    if not video.is_file():
        raise ValueError("Không thấy video để xuất")
    sid = ins["video"].get("sid") or ""
    s = ctx["store"].get(sid) if sid else {}
    title = (s.get("title") if s else "") or video.stem
    base = safe_name(title, 60).strip(" .") or "video"
    folder = Path(ctx["cfg"].output_dir) / "dang_bai" / (f"{base}_{sid[1:6]}" if sid else base)      # mã câu chuyện: hai video cùng tên không ghi đè nhau
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.iterdir():      # bản xuất trước của chính câu chuyện này
        if old.is_file() and (old.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv") or old.name == "thumbnail.jpg"):
            old.unlink(missing_ok=True)
    shutil.copy2(video, folder / f"{base}{video.suffix}")
    thumb = Path((ins.get("image") or {}).get("path") or "")
    if thumb.is_file():
        shutil.copy2(thumb, folder / "thumbnail.jpg")
    lines = [title, ""]
    if s:
        first = " ".join(sc.get("text") or "" for sc in s["scenes"][:2]).strip()
        if first:
            lines += [first[:300], ""]
    lines += ["#kechuyen #truyenhay #xuhuong"]
    stock = [c for c in (sm.credits(s) if s else []) if c.get("src") != "ai"]
    if stock:      # giấy phép CC BY bắt buộc ghi tên tác giả; Pexels, Pixabay không bắt buộc nhưng ghi công vẫn tốt, và là bằng chứng khi bị khiếu nại
        lines += ["", "Video nền:"] + [f"- {c.get('title') or 'video'}" + (f" của {c['author']}" if c.get("author") else "")
                                      + f" ({c.get('source_name') or c.get('src')}, {c.get('license') or ''})" for c in stock]
    (folder / "mo_ta.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    src_note = video.with_name(video.stem + ".nguon.txt")
    (folder / "nguon_video.txt").unlink(missing_ok=True)
    if src_note.is_file():
        shutil.copy2(src_note, folder / "nguon_video.txt")
    dur = float(probe(video).get("duration") or 0)
    log("workflow", f"Xuất bộ đăng bài: {folder}")
    return [], {"folder": str(folder), "files": sorted(f.name for f in folder.iterdir()), "duration": round(dur, 1)}


RUNNERS = {"idea": _run_idea, "script": _run_script, "images": _run_images, "ai_write": _run_ai_write, "split": _run_split,
           "char_refs": _run_char_refs, "draw": _run_draw, "stock": _run_stock, "animate": _run_animate, "voice": _run_voice, "music": _run_music, "render": _run_render,
           "thumbnail": _run_thumbnail, "editor": _run_editor, "export": _run_export}


def music_files() -> list[str]:
    d = sm.MUSIC_DIR
    return sorted(f.name for f in d.iterdir() if f.is_file() and f.suffix.lower() in MUSIC_EXT) if d.is_dir() else []


def save_upload(wstore, wid: str, data: bytes) -> str:
    """Ảnh của khối Ảnh của tôi: chuẩn hóa (xoay theo EXIF, thu nhỏ), lưu theo nội dung."""
    import hashlib
    from .imagegen import normalize
    im = normalize(data)
    folder = wstore.files(wid)
    folder.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(data).hexdigest()[:16] + ".jpg"
    if not (folder / name).exists():
        im.convert("RGB").save(folder / name, "JPEG", quality=93)
    return name

