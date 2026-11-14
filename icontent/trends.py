"""Khám phá: video thịnh hành và đề tài hot bên Trung Quốc để chọn làm video.

Chỉ đọc các bảng xếp hạng công khai, không cần đăng nhập. Nguồn nào từ chối thì báo rõ và dùng bản đã lưu nếu có,
không tìm cách lách. Đã đo trên máy thật (11/2026):
  - Thịnh hành thật: Bilibili popular (tuổi trung vị 1 ngày, có đủ lượt xem, thích...) và ranking rid=0. Chuyên mục được
    chia theo trường phân loại của từng video.
  - Đóng băng: ranking theo rid khác 0 dừng ở khoảng 3/2025 (tuổi trung vị 585 ngày). Vẫn dùng làm kho "Kinh điển",
    luôn ghi rõ để không nhầm là xu hướng hôm nay.
  - Từ khóa hot: Douyin, Weibo, Baidu, Toutiao, Zhihu, Bilibili.
  - Bị từ chối (HTTP 412): API tìm kiếm và API chi tiết video của Bilibili. Vì vậy "tìm kiếm" ở đây là tìm trong kho
    video thịnh hành đã tải, kèm liên kết mở trang tìm kiếm của từng nền tảng.
  - Douyin chỉ có đề tài: danh sách video của họ cần chữ ký, không gọi được bằng yêu cầu thường.

Dữ liệu được lưu tạm ở workspace/.trends để mở lại không phải tải và không gọi dồn dập vào máy chủ của họ.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from .download import UA

VIDEO_TTL = 15 * 60
TOPIC_TTL = 5 * 60
ARCHIVE_TTL = 7 * 86400     # kho Kinh điển không còn thay đổi
LIVE_PAGES = 20             # popular: mỗi trang 50 video
PACE = 0.6             # giây tối thiểu giữa hai lần gọi cùng một máy chủ
_CJK = re.compile(r"[一-鿿]")

# kho Kinh điển: id, nhãn, rid. Bảng theo chuyên mục của Bilibili đã dừng cập nhật từ khoảng 3/2025
CATEGORIES = [
    ("food", "Ẩm thực", 211), ("life", "Đời sống", 160), ("animal", "Thú cưng", 217),
    ("funny", "Hài, chế", 119), ("ent", "Giải trí", 5), ("film", "Phim", 181), ("know", "Kiến thức", 36),
    ("tech", "Công nghệ", 188), ("car", "Ô tô", 223), ("sport", "Thể thao", 234), ("fashion", "Thời trang", 155),
    ("dance", "Nhảy", 129), ("music", "Âm nhạc", 3), ("game", "Game", 4), ("anime", "Hoạt hình", 1),
]
CAT_RID = {c: r for c, _, r in CATEGORIES}
WEAK_FOR_DUB = {"music", "game", "anime", "dance"}                   # ít lời thoại hoặc khó lồng tiếng
WEAK_PARENTS = {"音乐", "游戏", "舞蹈", "鬼畜", "动画", "二次元"}
GOOD_PARENTS = {"小剧场", "美食", "三农", "动物", "生活兴趣", "旅游出行", "汽车", "知识"}
WEAK_TITLE = re.compile(r"\bMV\b|Music Video|单曲|翻唱|手书|\bPV\b|\bAMV\b|\bMAD\b|直播回放|时政", re.IGNORECASE)
PARENT_VI = {"小剧场": "Phim ngắn", "美食": "Ẩm thực", "三农": "Nông thôn", "动物": "Thú cưng", "生活兴趣": "Sở thích", "旅游出行": "Du lịch",
             "汽车": "Ô tô", "知识": "Kiến thức", "影视": "Phim", "娱乐": "Giải trí", "音乐": "Âm nhạc", "游戏": "Game", "舞蹈": "Nhảy",
             "鬼畜": "Chế", "动画": "Hoạt hình", "二次元": "Anime", "户外潮流": "Ngoài trời", "科技": "Công nghệ", "科技数码": "Công nghệ",
             "人工智能": "AI", "时尚": "Thời trang", "时尚美妆": "Thời trang", "运动": "Thể thao", "体育运动": "Thể thao", "生活": "Đời sống",
             "其他": "Khác", "资讯": "Tin tức", "情感": "Tình cảm", "家装房产": "Nhà cửa", "亲子": "Gia đình", "健康": "Sức khỏe",
             "绘画": "Vẽ", "手工": "Thủ công", "vlog": "Vlog", "健身": "Thể hình", "医疗保健": "Sức khỏe", "生活经验": "Mẹo vặt", "神秘学": "Bí ẩn", "公益": "Thiện nguyện", "校园学习": "Học đường", "职业职场": "Công việc"}

TOPIC_SOURCES = [("douyin", "Douyin"), ("weibo", "Weibo"), ("bilibili", "Bilibili"), ("baidu", "Baidu"),
                 ("toutiao", "Toutiao"), ("zhihu", "Zhihu")]


class SourceError(RuntimeError):
    """Nguồn không dùng được lúc này. Câu thông báo đã viết sẵn cho người dùng."""


# --------------------------------------------------------------------------- lấy dữ liệu

_last_call: dict[str, float] = {}
_pace_lock = threading.Lock()


def _get_json(url: str, referer: str = "", proxy: str = "", timeout: float = 15.0) -> dict:
    host = url.split("/")[2]
    with _pace_lock:
        wait = PACE - (time.time() - _last_call.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.time()
    headers = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(*([urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []))
    try:
        with opener.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise SourceError(f"{host} đang từ chối truy cập (mã {e.code}). Đợi một lát rồi thử lại.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SourceError(f"Không kết nối được {host}. Kiểm tra mạng rồi thử lại.") from e
    except ValueError as e:
        raise SourceError(f"{host} trả về dữ liệu không đọc được.") from e


# --------------------------------------------------------------------------- video

def _https(u: str) -> str:
    u = str(u or "")
    return "https:" + u[5:] if u.startswith("http:") else "https:" + u if u.startswith("//") else u


def score_video(v: dict, cat: str = "", now: float | None = None) -> None:
    """Thêm các chỉ số giúp chọn: lượt xem mỗi giờ, độ tương tác, điểm "đáng làm" 0-100 và lý do."""
    now = now or time.time()
    view, dur = max(1, int(v.get("view") or 0)), float(v.get("duration") or 0)
    hours = max(1.0, (now - float(v.get("pubdate") or now)) / 3600)
    vph = view / hours
    eng = (v.get("like", 0) + 2 * v.get("coin", 0) + v.get("favorite", 0) + 2 * v.get("share", 0)) / view
    # video ngắn lồng tiếng nhanh và đăng được ngay; quá dài tốn thời gian xử lý
    fit = 1.0 if 30 <= dur <= 300 else 0.7 if 300 < dur <= 600 else 0.5 if dur < 30 else 0.3 if dur <= 1800 else 0.1
    raw = 0.45 * min(1.0, math.log10(vph + 1) / 5) + 0.25 * min(1.0, eng / 0.25) + 0.30 * fit
    parent = v.get("parent") or ""
    weak = cat in WEAK_FOR_DUB or parent in WEAK_PARENTS or bool(WEAK_TITLE.search(f"{v.get('title', '')} {v.get('category', '')}"))
    if weak:
        raw *= 0.55
    elif parent in GOOD_PARENTS or cat in ("food", "animal", "life"):
        raw = min(1.0, raw * 1.1)
    v["vph"] = round(vph)
    v["engage"] = round(eng, 3)
    v["score"] = round(raw * 100)
    tags = []
    if vph >= 20000:
        tags.append("Lên rất nhanh")
    elif vph >= 5000:
        tags.append("Đang lên")
    if eng >= 0.2:
        tags.append("Tương tác cao")
    if 30 <= dur <= 180:
        tags.append("Ngắn, làm nhanh")
    if v.get("vertical"):
        tags.append("Video dọc")
    v["tags"] = tags


def normalize_bili(item: dict, cat: str = "", now: float | None = None) -> dict | None:
    bvid = item.get("bvid")
    if not bvid or item.get("is_ogv"):        # phim bộ có bản quyền riêng của Bilibili, không phải video người dùng
        return None
    st = item.get("stat") or {}
    dim = item.get("dimension") or {}
    w, h = int(dim.get("width") or 0), int(dim.get("height") or 0)
    if dim.get("rotate"):
        w, h = h, w
    v = {
        "id": bvid, "platform": "bilibili", "url": f"https://www.bilibili.com/video/{bvid}",
        "title": str(item.get("title") or ""), "desc": str(item.get("desc") or "")[:300],
        "cover": _https(item.get("pic")), "duration": int(item.get("duration") or 0),
        "pubdate": int(item.get("pubdate") or 0), "author": str((item.get("owner") or {}).get("name") or ""),
        "category": str(item.get("tnamev2") or item.get("tname") or ""), "cat": cat,
        "parent": str(item.get("pid_name_v2") or ""), "label": PARENT_VI.get(str(item.get("pid_name_v2") or ""), ""),
        "view": int(st.get("view") or 0), "like": int(st.get("like") or 0), "coin": int(st.get("coin") or 0),
        "favorite": int(st.get("favorite") or 0), "share": int(st.get("share") or 0),
        "reply": int(st.get("reply") or 0), "danmaku": int(st.get("danmaku") or 0),
        "vertical": h > w > 0, "parts": int(item.get("videos") or 1),
    }
    score_video(v, cat, now)
    return v


def fetch_live(proxy: str = "") -> list[dict]:
    """Video đang thịnh hành: danh sách popular nhiều trang + bảng toàn site. Trang sau lỗi thì giữ các trang đã có."""
    raw: list[dict] = []
    for pn in range(1, LIVE_PAGES + 1):
        try:
            r = _get_json(f"https://api.bilibili.com/x/web-interface/popular?ps=50&pn={pn}", "https://www.bilibili.com", proxy)
        except SourceError:
            if raw:
                break
            raise
        if r.get("code") != 0:
            if raw:
                break
            raise SourceError(f"Bilibili từ chối danh sách thịnh hành (mã {r.get('code')}).")
        data = r.get("data") or {}
        raw += data.get("list") or []
        if data.get("no_more") or not data.get("list"):
            break
    try:
        r = _get_json("https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all", "https://www.bilibili.com", proxy)
        raw += ((r.get("data") or {}).get("list")) or [] if r.get("code") == 0 else []
    except SourceError:
        pass
    seen: dict[str, dict] = {}
    for i in raw:
        v = normalize_bili(i, "")
        if v:
            seen.setdefault(v["id"], v)
    return list(seen.values())


def fetch_archive(cat: str, proxy: str = "") -> list[dict]:
    if cat not in CAT_RID:
        raise SourceError("Chuyên mục không hợp lệ.")
    r = _get_json(f"https://api.bilibili.com/x/web-interface/ranking/v2?rid={CAT_RID[cat]}&type=all", "https://www.bilibili.com", proxy)
    if r.get("code") != 0:
        raise SourceError(f"Bilibili từ chối bảng xếp hạng (mã {r.get('code')}).")
    return [v for v in (normalize_bili(i, cat) for i in ((r.get("data") or {}).get("list")) or []) if v]


# --------------------------------------------------------------------------- đề tài hot

def parse_hot_number(s) -> int:
    """'1223 万热度' -> 12230000; 81412 -> 81412."""
    if isinstance(s, (int, float)):
        return int(s)
    m = re.search(r"([\d.]+)\s*(亿|万)?", str(s or ""))
    if not m:
        return 0
    n = float(m.group(1))
    return int(n * {"亿": 100_000_000, "万": 10_000}.get(m.group(2) or "", 1))


def parse_douyin(d: dict) -> list[dict]:
    out = []
    for w in (d.get("data") or {}).get("word_list") or []:
        word = str(w.get("word") or "").strip()
        if word:
            sid = w.get("sentence_id")
            out.append({"word": word, "hot": parse_hot_number(w.get("hot_value")), "videos": w.get("video_count") or 0,
                        "url": f"https://www.douyin.com/hot/{sid}" if sid else ""})
    return out


def parse_weibo(d: dict) -> list[dict]:
    out = []
    for w in (d.get("data") or {}).get("realtime") or []:
        word = str(w.get("word") or "").strip()
        if word and not w.get("is_ad"):
            out.append({"word": word, "hot": parse_hot_number(w.get("num")), "label": str(w.get("flag_desc") or ""),
                        "url": "https://s.weibo.com/weibo?q=" + quote(w.get("word_scheme") or f"#{word}#")})
    return out


def parse_bilibili(d: dict) -> list[dict]:
    out = []
    for w in d.get("list") or []:
        word = str(w.get("show_name") or w.get("keyword") or "").strip()
        if word:
            out.append({"word": word, "hot": parse_hot_number(w.get("heat_score")),
                        "url": "https://search.bilibili.com/all?keyword=" + quote(str(w.get("keyword") or word))})
    return out


def parse_baidu(d: dict) -> list[dict]:
    out = []
    for card in (d.get("data") or {}).get("cards") or []:
        for block in card.get("content") or []:
            for w in block.get("content") or [block]:
                word = str(w.get("word") or "").strip()
                if word and not w.get("isTop"):
                    out.append({"word": word, "hot": parse_hot_number(w.get("hotScore")), "url": str(w.get("url") or "")})
    return out


def parse_toutiao(d: dict) -> list[dict]:
    out = []
    for w in d.get("data") or []:
        word = str(w.get("Title") or "").strip()
        if word:
            out.append({"word": word, "hot": parse_hot_number(w.get("HotValue")), "label": str(w.get("LabelDesc") or ""),
                        "url": str(w.get("Url") or "").split("?")[0]})
    return out


def parse_zhihu(d: dict) -> list[dict]:
    out = []
    for w in d.get("data") or []:
        t = w.get("target") or {}
        word = str(t.get("title") or t.get("title_area", {}).get("text") or "").strip()
        qid = t.get("id")
        if word:
            out.append({"word": word, "hot": parse_hot_number(w.get("detail_text")),
                        "url": f"https://www.zhihu.com/question/{qid}" if qid else ""})
    return out


TOPIC_API = {
    "douyin": ("https://www.douyin.com/aweme/v1/web/hot/search/list/?device_platform=webapp&aid=6383", "https://www.douyin.com", parse_douyin),
    "weibo": ("https://weibo.com/ajax/side/hotSearch", "https://weibo.com", parse_weibo),
    "bilibili": ("https://s.search.bilibili.com/main/hotword?limit=30", "https://www.bilibili.com", parse_bilibili),
    "baidu": ("https://top.baidu.com/api/board?platform=wise&tab=realtime", "https://top.baidu.com", parse_baidu),
    "toutiao": ("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc", "https://www.toutiao.com", parse_toutiao),
    "zhihu": ("https://api.zhihu.com/topstory/hot-list?limit=30", "https://www.zhihu.com", parse_zhihu),
}


def fetch_topics(source: str, proxy: str = "") -> list[dict]:
    if source not in TOPIC_API:
        raise SourceError("Nguồn không hợp lệ.")
    url, ref, parse = TOPIC_API[source]
    items = parse(_get_json(url, ref, proxy))
    if not items:
        raise SourceError(f"{source} không trả về đề tài nào lúc này.")
    for i, it in enumerate(items[:30], 1):
        it["rank"], it["source"] = i, source
    return items[:30]


def search_links(word: str) -> list[dict]:
    """Mở trang tìm kiếm của từng nền tảng: duyệt ở đó, chép link video rồi dán vào iContent."""
    q = quote(word)
    return [
        {"id": "bilibili", "name": "Bilibili", "url": f"https://search.bilibili.com/all?keyword={q}"},
        {"id": "douyin", "name": "Douyin", "url": f"https://www.douyin.com/search/{q}?type=video"},
        {"id": "kuaishou", "name": "Kuaishou", "url": f"https://www.kuaishou.com/search/video?searchKey={q}"},
        {"id": "xiaohongshu", "name": "Xiaohongshu", "url": f"https://www.xiaohongshu.com/search_result?keyword={q}"},
        {"id": "weibo", "name": "Weibo", "url": f"https://s.weibo.com/video?q={q}"},
    ]


# --------------------------------------------------------------------------- tìm trong kho

def has_cjk(s: str) -> bool:
    return bool(_CJK.search(s or ""))


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\W+", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())


def match_score(query: str, v: dict, vi_title: str = "") -> float:
    """Câu truy vấn nằm nguyên trong tiêu đề: điểm cao nhất. Không thì so từng cặp chữ: 美食视频 vẫn khớp 街头美食."""
    if not query.strip():
        return 0.0
    q = query.lower().strip()
    title = (v.get("title") or "").lower()
    if q in title:
        return 3.0
    if q in (vi_title or "").lower():
        return 2.5
    rest = f"{v.get('desc', '')} {v.get('author', '')} {v.get('category', '')}".lower()
    if q in rest:
        return 1.5
    if not has_cjk(q):
        return 0.0
    # 可爱的猫 -> 可爱 + 猫. Tiếng Trung đặt danh từ chính ở cuối nên phần cuối được tính nặng hơn: tìm mèo phải ra mèo
    parts = [p for p in re.split(r"[的了是和与在及、\s]+", q) if p]
    if len(parts) > 1:
        weights = [len(p) for p in parts[:-1]] + [max(3, 2 * len(parts[-1]))]
        got = sum(w for p, w in zip(parts, weights) if p in title)
        if got:
            return 1.2 + got / sum(weights)
    # không có chữ ngăn cách (街头食物): so từng cặp chữ, khớp từ 1/3 trở lên là liên quan
    grams = _bigrams(q)
    hit = len(grams & _bigrams(title))
    return hit / len(grams) if grams and hit / len(grams) >= 1 / 3 else 0.0


# --------------------------------------------------------------------------- kho có cache

class Trends:
    def __init__(self, cache_dir: Path, proxy: str = ""):
        self.dir = Path(cache_dir)
        self.proxy = proxy
        self.lock = threading.Lock()
        self.mem: dict[str, dict] = {}

    def _path(self, key: str) -> Path:
        return self.dir / (re.sub(r"\W+", "_", key) + ".json")

    def _load(self, key: str) -> dict | None:
        if key in self.mem:
            return self.mem[key]
        try:
            self.mem[key] = json.loads(self._path(key).read_text(encoding="utf-8"))
            return self.mem[key]
        except (FileNotFoundError, ValueError):
            return None

    def _save(self, key: str, data) -> dict:
        rec = {"at": time.time(), "data": data}
        self.mem[key] = rec
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path(key).with_suffix(".part")
        tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path(key))
        return rec

    def _cached(self, key: str, ttl: float, fetch, refresh: bool = False) -> dict:
        """-> {items, at, stale, error}. Lỗi mà còn bản cũ thì trả bản cũ kèm câu báo lỗi."""
        with self.lock:
            old = self._load(key)
            if old and not refresh and time.time() - old["at"] < ttl:
                return {"items": old["data"], "at": old["at"], "stale": False, "error": ""}
            try:
                rec = self._save(key, fetch())
                return {"items": rec["data"], "at": rec["at"], "stale": False, "error": ""}
            except Exception as e:   # noqa: BLE001  nguồn ngoài có thể trả về bất cứ thứ gì: chỉ hỏng nguồn đó thôi
                msg = str(e) if isinstance(e, SourceError) else "Nguồn này vừa trả về dữ liệu không đọc được. Đợi một lát rồi thử lại."
                if old:
                    return {"items": old["data"], "at": old["at"], "stale": True, "error": msg}
                return {"items": [], "at": 0, "stale": False, "error": msg}

    def live(self, refresh: bool = False) -> dict:
        return self._cached("videos_live", VIDEO_TTL, lambda: fetch_live(self.proxy), refresh)

    def videos(self, cat: str, refresh: bool = False) -> dict:
        """cat: picks (đáng làm nhất), hot (đúng thứ tự Bilibili), arch:<id> (kho Kinh điển), còn lại là tên chuyên mục."""
        if cat.startswith("arch:"):
            key = cat[5:]
            return self._cached(f"videos_arch_{key}", ARCHIVE_TTL, lambda: fetch_archive(key, self.proxy), refresh)
        r = self.live(refresh)
        items = r["items"]
        if cat == "picks":
            items = sorted(items, key=lambda v: -v["score"])[:60]
        elif cat != "hot":
            items = [v for v in items if v.get("parent") == cat]
        return {**r, "items": items}

    def categories(self) -> list[dict]:
        """Chuyên mục đang có trong danh sách thịnh hành: hợp lồng tiếng xếp trước, chuyên mục quá ít video thì bỏ."""
        count: dict[str, int] = {}
        for v in self.live()["items"]:
            p = v.get("parent")
            if p:
                count[p] = count.get(p, 0) + 1
        keys = [k for k in count if count[k] >= 3]
        keys.sort(key=lambda k: (0 if k in GOOD_PARENTS else 2 if k in WEAK_PARENTS else 1, -count[k]))
        return [{"id": k, "name": PARENT_VI.get(k, k), "count": count[k]} for k in keys]

    def topics(self, source: str, refresh: bool = False) -> dict:
        return self._cached(f"topics_{source}", TOPIC_TTL, lambda: fetch_topics(source, self.proxy), refresh)

    def warehouse(self) -> list[dict]:
        """Video đang thịnh hành + kho Kinh điển (tải bù mục còn thiếu, có giãn cách)."""
        seen: dict[str, dict] = {}
        for v in self.live()["items"]:
            seen.setdefault(v["id"], v)
        for c, _, _ in CATEGORIES:
            for v in self.videos("arch:" + c)["items"]:
                seen.setdefault(v["id"], v)
        return list(seen.values())

    def search(self, query: str, query_zh: str = "", vi_titles: dict | None = None, limit: int = 60) -> list[dict]:
        vi_titles = vi_titles or {}
        scored = []
        for v in self.warehouse():
            vi = vi_titles.get(v["title"], "")
            s = max(match_score(query, v, vi), match_score(query_zh, v, vi) if query_zh else 0.0)
            if s > 0:
                scored.append((s, v))
        scored.sort(key=lambda x: (-x[0], -x[1]["view"]))
        return [v for _, v in scored[:limit]]


# --------------------------------------------------------------------------- dịch tiêu đề

class TitleTranslator:
    """Dịch tiêu đề và đề tài, nhớ kết quả vào đĩa để lần sau hiện ngay."""

    def __init__(self, cache_file: Path):
        self.file = Path(cache_file)
        self.lock = threading.Lock()
        self.cache: dict[str, str] = {}
        try:
            self.cache = json.loads(self.file.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            pass

    def known(self, texts: list[str]) -> dict[str, str]:
        with self.lock:
            return {t: self.cache[t] for t in texts if t in self.cache}

    def _save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".part")
        tmp.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.file)

    def translate(self, texts: list[str], tcfg) -> tuple[dict[str, str], str]:
        """-> ({gốc: tiếng Việt}, cách đã dùng). Không có cách dịch nào thì trả rỗng, không báo lỗi."""
        out = self.known(texts)
        todo = [t for t in dict.fromkeys(texts) if t not in out and t.strip()]
        if not todo:
            return out, "cache"
        how, fresh = _translate_any(todo, tcfg)
        if fresh:
            with self.lock:
                self.cache.update(fresh)
                self._save()
            out.update(fresh)
        return out, how


def _translate_any(todo: list[str], tcfg) -> tuple[str, dict[str, str]]:
    from . import offline
    from .keys import translator_ready

    model = tcfg.get("offline_model")
    if offline.ready(model) and offline.start():
        got = {}
        for t in todo:
            res = offline.clean_output(offline.generate(offline.task_prompt(t, "vi"), model, max_tokens=max(64, len(t) * 8)), "vi")
            if res and not offline.looks_broken(res, t):
                got[t] = res
        return "offline", got
    if tcfg.provider in ("claude", "openai") and translator_ready(tcfg):
        from .translate import make_translator

        tr = make_translator(tcfg)
        schema = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "string"}}},
                  "required": ["items"], "additionalProperties": False}
        sys_p = ("Translate each Chinese video title or trending topic into short natural Vietnamese. Return JSON "
                 '{"items": [...]} with exactly one translation per input, same order.')
        res = tr.json_call(sys_p, json.dumps(todo, ensure_ascii=False), schema, max_tokens=4000).get("items") or []
        return tcfg.provider, {a: str(b).strip() for a, b in zip(todo, res) if str(b).strip()}
    return "none", {}


def to_chinese(query: str, tcfg) -> str:
    """Từ khóa tiếng Việt -> tiếng Trung để tìm. Không có cách dịch thì trả rỗng."""
    from . import offline
    from .keys import translator_ready

    if has_cjk(query):
        return query
    model = tcfg.get("offline_model")
    if offline.ready(model) and offline.start():
        res = offline.generate(f"将以下文本翻译为中文，注意只需要输出翻译后的结果，不要额外解释：\n\n{query}", model, max_tokens=48)
        res = res.strip().strip("。.!！\"“”")
        return res if has_cjk(res) else ""
    if tcfg.provider in ("claude", "openai") and translator_ready(tcfg):
        from .translate import make_translator

        schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}
        res = make_translator(tcfg).json_call("Translate the search keyword into Simplified Chinese. Return JSON {\"text\": ...}.", query, schema, max_tokens=200)
        return str(res.get("text") or "").strip()
    return ""
