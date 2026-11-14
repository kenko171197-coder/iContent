"""Video nền miễn phí từ các kho có giấy phép rõ ràng, qua API chính thức của họ.

  pexels     Pexels: kho lớn, nhiều video dọc. Giấy phép Pexels: dùng miễn phí cả cho thương mại, không bắt buộc ghi nguồn. Key miễn phí.
  pixabay    Pixabay: kho lớn. Giấy phép nội dung Pixabay: như trên. Key miễn phí. Yêu cầu lưu kết quả tìm 24 giờ (có ở đây).
  wikimedia  Wikimedia Commons: không cần key. Chỉ nhận video phạm vi công cộng, CC0, CC BY (ghi tên tác giả, có trong file nguồn).
             Bỏ CC BY-SA (video làm ra cũng phải theo giấy phép đó), NC (cấm thương mại), ND (cấm sửa).

Không lấy video từ YouTube, Douyin, TikTok làm nguồn: "video free" trên đó không phải miễn phí bản quyền, kênh dễ bị gậy.
Mỗi clip tải về giữ tên tác giả, trang gốc và giấy phép (story.py ghi ra file nguồn cạnh video) để có bằng chứng khi bị khiếu nại.
Video tải về được chuẩn hóa thành mp4 H.264 30 khung, không tiếng, cạnh ngắn tối đa 1080: dựng nhanh, Trình dựng đọc được, file nhỏ.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .util import ROOT

UA = "iContent/0.6 (https://github.com/dienmoc86/icontent)"      # Wikimedia yêu cầu tên ứng dụng rõ ràng
CACHE_DIR = ROOT / "assets" / ".stock_cache"
CACHE_TTL = 24 * 3600      # Pixabay yêu cầu lưu kết quả tìm 24 giờ, không gọi lặp lại
MAX_BYTES = 400 * 1024 * 1024
MAX_SECONDS = 40           # chỉ giữ 40 giây đầu: một cảnh hiếm khi dài hơn, file nhỏ
SHORT_SIDE = 1080
MAX_WIKI_SECONDS = 300

SOURCES = {
    "pexels": {"name": "Pexels", "keys": ["PEXELS_API_KEY"], "get": "https://www.pexels.com/api/", "site": "https://www.pexels.com",
               "license": "Giấy phép Pexels: miễn phí, dùng thương mại được, không bắt buộc ghi nguồn"},
    "pixabay": {"name": "Pixabay", "keys": ["PIXABAY_API_KEY"], "get": "https://pixabay.com/api/docs/", "site": "https://pixabay.com",
                "license": "Giấy phép nội dung Pixabay: miễn phí, dùng thương mại được, không bắt buộc ghi nguồn"},
    "wikimedia": {"name": "Wikimedia Commons", "keys": [], "get": "", "site": "https://commons.wikimedia.org",
                  "license": "Phạm vi công cộng, CC0 hoặc CC BY (ghi tên tác giả)"},
}
ORDER = ("pexels", "pixabay", "wikimedia")


class StockError(RuntimeError):
    pass


def _key(name: str) -> str:
    return os.environ.get(name, "").strip()


def ready(src: str) -> bool:
    s = SOURCES.get(src)
    return bool(s) and all(_key(k) for k in s["keys"])


def public() -> list[dict]:
    return [{"id": k, "name": v["name"], "ready": ready(k), "keys": v["keys"], "get": v["get"], "license": v["license"], "site": v["site"]}
            for k, v in SOURCES.items()]


def sources(src: str = "") -> list[str]:
    """Kho sẽ tìm: kho được chọn, không thì mọi kho đã sẵn sàng (có key trước, Wikimedia sau cùng vì ít video dọc, chất lượng không đều)."""
    if src:
        if src not in SOURCES:
            raise StockError("Không có kho video này")
        if not ready(src):
            raise StockError(f"Chưa có key {SOURCES[src]['name']} (miễn phí, lấy tại {SOURCES[src]['get']}). Dán vào Cài đặt, mục Video nền miễn phí.")
        return [src]
    return [s for s in ORDER if ready(s)]


# ------------------------------------------------------------------ gọi mạng
def _get_json(url: str, headers: dict | None = None, timeout: float = 25) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        if e.code in (401, 403):
            raise StockError("Key kho video không đúng hoặc đã bị khóa. Kiểm tra lại trong Cài đặt.") from None
        if e.code == 429:
            raise StockError("Kho video đang giới hạn số lần tìm (mỗi giờ). Đợi một lát rồi tìm tiếp.") from None
        raise StockError(f"Kho video báo lỗi {e.code}: {body}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise StockError(f"Không kết nối được kho video ({str(getattr(e, 'reason', e))[:100]}). Kiểm tra mạng.") from None
    except ValueError:
        raise StockError("Kho video trả về dữ liệu không đọc được") from None


_cache_lock = threading.Lock()
_ITEMS: dict[str, dict] = {}      # "kho:mã" -> kết quả đã tìm: tải về chỉ theo mục đã tìm ra, không tải đường dẫn bất kỳ do trình duyệt gửi


def _cached(key: str, fn) -> list[dict]:
    f = CACHE_DIR / (hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + ".json")
    try:
        if time.time() - f.stat().st_mtime < CACHE_TTL:
            items = json.loads(f.read_text(encoding="utf-8"))
            _remember(items)
            return items
    except (OSError, ValueError):
        pass
    items = fn()
    with _cache_lock:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    _remember(items)
    return items


def _remember(items: list[dict]) -> None:
    with _cache_lock:
        for it in items:
            _ITEMS[f"{it['src']}:{it['id']}"] = it
        if len(_ITEMS) > 5000:
            for k in list(_ITEMS)[:1000]:
                _ITEMS.pop(k, None)


def item(src: str, iid: str) -> dict:
    it = _ITEMS.get(f"{src}:{iid}")
    if not it:
        raise KeyError("Không còn kết quả tìm này, tìm lại rồi chọn")
    return it


def _orientation(aspect: str) -> str:
    return {"9:16": "portrait", "16:9": "landscape", "1:1": "square"}.get(aspect, "landscape")


def _pexels(query: str, aspect: str, page: int) -> list[dict]:
    q = urllib.parse.urlencode({"query": query, "orientation": _orientation(aspect), "per_page": 24, "page": page, "size": "medium"})
    data = _get_json(f"https://api.pexels.com/v1/videos/search?{q}", {"Authorization": _key("PEXELS_API_KEY")})
    out = []
    for v in data.get("videos") or []:
        files = [{"w": int(f.get("width") or 0), "h": int(f.get("height") or 0), "url": f.get("link") or ""}
                 for f in v.get("video_files") or [] if f.get("quality") in ("hd", "sd", "uhd") and str(f.get("file_type") or "").endswith("mp4") and f.get("link")]
        if not files:
            continue
        small = min(files, key=lambda f: f["w"] * f["h"])
        user = v.get("user") or {}
        out.append({"src": "pexels", "id": str(v["id"]), "title": _title_from_url(v.get("url") or ""), "thumb": v.get("image") or "", "preview": small["url"],
                    "duration": float(v.get("duration") or 0), "width": int(v.get("width") or 0), "height": int(v.get("height") or 0),
                    "page": v.get("url") or "", "author": user.get("name") or "", "author_url": user.get("url") or "",
                    "license": "Pexels License", "files": files})
    return out


def _title_from_url(url: str) -> str:
    m = re.search(r"/video/([a-z0-9-]+?)-\d+/?$", url)
    return m.group(1).replace("-", " ").capitalize() if m else ""


def _pixabay(query: str, aspect: str, page: int) -> list[dict]:
    q = urllib.parse.urlencode({"key": _key("PIXABAY_API_KEY"), "q": query[:100], "per_page": 24, "page": page, "safesearch": "true", "video_type": "film"})
    data = _get_json(f"https://pixabay.com/api/videos/?{q}")
    out = []
    for v in data.get("hits") or []:
        vids = v.get("videos") or {}
        files = [{"w": int(f.get("width") or 0), "h": int(f.get("height") or 0), "url": f.get("url") or ""}
                 for k in ("large", "medium", "small", "tiny") for f in [vids.get(k) or {}] if f.get("url")]
        if not files:
            continue
        thumb = next((f.get("thumbnail") for k in ("medium", "small", "tiny") for f in [vids.get(k) or {}] if f.get("thumbnail")), "")
        big = max(files, key=lambda f: f["w"] * f["h"])
        small = min(files, key=lambda f: f["w"] * f["h"])
        out.append({"src": "pixabay", "id": str(v["id"]), "title": str(v.get("tags") or "")[:80], "thumb": thumb, "preview": small["url"],
                    "duration": float(v.get("duration") or 0), "width": big["w"], "height": big["h"], "page": v.get("pageURL") or "",
                    "author": v.get("user") or "", "author_url": f"https://pixabay.com/users/{v.get('user')}-{v.get('user_id')}/" if v.get("user") else "",
                    "license": "Pixabay Content License", "files": files})
    return out


_FREE = re.compile(r"^(public domain|pd\b|cc0|cc[- ]?zero|cc[- ]by \d|cc[- ]by$|attribution$)", re.I)


def _wiki_license_ok(lic: str) -> bool:
    """Chỉ nhận giấy phép không ràng buộc video làm ra: bỏ SA (phải chia sẻ cùng giấy phép), NC (cấm thương mại), ND (cấm sửa)."""
    lic = (lic or "").strip()
    if not lic or re.search(r"\b(SA|NC|ND)\b", lic, re.I) or "share" in lic.lower() or "gfdl" in lic.lower():
        return False
    return bool(_FREE.search(lic))


def _strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _wikimedia(query: str, aspect: str, page: int) -> list[dict]:
    q = {"action": "query", "format": "json", "formatversion": "2", "generator": "search", "gsrsearch": f"filetype:video {query}", "gsrnamespace": "6",
         "gsrlimit": "40", "gsroffset": str(40 * (page - 1)), "prop": "videoinfo", "viprop": "url|size|mime|extmetadata|derivatives",
         "viurlwidth": "480", "viextmetadatafilter": "LicenseShortName|Artist|ObjectName"}
    data = _get_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(q))
    pages = sorted((data.get("query") or {}).get("pages") or [], key=lambda p: p.get("index") or 0)
    out = []
    for p in pages:
        vi = (p.get("videoinfo") or [{}])[0]
        md = vi.get("extmetadata") or {}
        lic = _strip_html((md.get("LicenseShortName") or {}).get("value") or "")
        if not _wiki_license_ok(lic) or not vi.get("url") or not vi.get("width"):
            continue
        dur = float(vi.get("duration") or 0)
        if dur < 2 or dur > MAX_WIKI_SECONDS:      # Commons có cả phim tư liệu vài giờ: tải về hàng GB cho một cảnh vài giây
            continue
        files = [{"w": int(vi["width"]), "h": int(vi["height"]), "url": vi["url"], "bytes": int(vi.get("size") or 0)}]
        ders = [{"w": int(d.get("width") or 0), "h": int(d.get("height") or 0), "url": d.get("src") or ""}
                for d in vi.get("derivatives") or [] if "webm" in str(d.get("type") or "") and d.get("src")]
        files += ders
        small = min(ders or files, key=lambda f: f["w"] * f["h"])
        out.append({"src": "wikimedia", "id": str(p.get("pageid")), "title": _strip_html((md.get("ObjectName") or {}).get("value") or "") or p.get("title", "").removeprefix("File:"),
                    "thumb": vi.get("thumburl") or "", "preview": small["url"], "duration": dur, "width": int(vi["width"]), "height": int(vi["height"]),
                    "page": vi.get("descriptionurl") or "", "author": _strip_html((md.get("Artist") or {}).get("value") or "")[:120],
                    "author_url": "", "license": lic, "files": files})
    return out


SEARCH = {"pexels": _pexels, "pixabay": _pixabay, "wikimedia": _wikimedia}


def search(query: str, aspect: str = "9:16", src: str = "", page: int = 1) -> list[dict]:
    """Tìm ở một kho hoặc mọi kho sẵn sàng, xen kẽ kết quả. Lỗi ở một kho không làm hỏng kết quả kho khác."""
    query = re.sub(r"\s+", " ", query or "").strip()[:100]
    if not query:
        raise StockError("Nhập từ khóa tìm video (tiếng Anh tìm được nhiều nhất)")
    page = max(1, min(20, int(page or 1)))
    srcs = sources(src)
    lists, errors = [], []
    for s in srcs:
        try:
            lists.append(_cached(f"{s}|{query.lower()}|{_orientation(aspect)}|{page}", lambda s=s: SEARCH[s](query, aspect, page)))
        except StockError as e:
            errors.append(f"{SOURCES[s]['name']}: {e}")
    if errors and not any(lists):
        raise StockError("; ".join(errors))
    out = []
    for k in range(max((len(x) for x in lists), default=0)):
        out += [x[k] for x in lists if k < len(x)]
    return out


# ------------------------------------------------------------------ chọn tự động
def score(it: dict, aspect: str, need: float) -> float:
    """Điểm để tự chọn: đúng chiều khung, đủ dài, đủ nét. Kết quả đứng trước (kho xếp theo độ liên quan) được cộng thêm ở chỗ gọi."""
    w, h = it.get("width") or 1, it.get("height") or 1
    want = _orientation(aspect)
    got = "portrait" if h > w * 1.05 else "landscape" if w > h * 1.05 else "square"
    s = 3.0 if got == want else 1.0 if want == "square" or got == "square" else 0.0
    d = float(it.get("duration") or 0)
    s += 2.0 if d >= need else max(0.0, 2.0 * d / max(need, 1)) - 0.5
    s += min(1.0, min(w, h) / SHORT_SIDE)
    if d > 60:      # phim dài (tư liệu, phóng sự): hay có đoạn giới thiệu, bản đồ, logo; clip quay cảnh (B-roll) thường dưới một phút
        s -= 1.0 if d <= 180 else 2.0
    return s


def start_at(duration: float) -> float:
    """Clip dài thì bỏ phần mở đầu (tiêu đề, logo, bản đồ giới thiệu), lấy từ đoạn giữa. Clip quay cảnh ngắn thì lấy từ đầu."""
    return 0.0 if duration <= 20 else round(min(duration * 0.2, 30.0), 2)


PICK_TOP = 10      # chỉ chọn trong mười kết quả liên quan nhất: kết quả xa hơn hay lạc đề (tìm "ha long bay" ra phố Nice)


def _stem(w: str) -> str:
    w = w.lower()
    for suf in ("ies", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


_URL_WORDS = {"https", "www", "com", "org", "commons", "wikimedia", "wiki", "file", "video", "videos", "pexels", "pixabay", "users", "webm", "ogv", "mp4"}


def _terms(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[A-Za-z]{3,}", text or "") if w.lower() not in _STOP and w.lower() not in _URL_WORDS}


def overlap(it: dict, query: str) -> int:
    """Số từ của từ khóa có trong tên, nhãn của clip. Kho trả về cả kết quả chỉ khớp phần mô tả dài (tìm "nông dân ruộng lúa" ra
    video phỏng vấn của Hải quân Mỹ): tự chọn thì bắt buộc tên hoặc nhãn phải nói về đúng thứ cần tìm."""
    return len(_terms(query) & _terms(f"{it.get('title') or ''} {it.get('tags') or ''} {it.get('page') or ''}".replace("-", " ").replace("_", " ")))


def auto_pick(items: list[dict], aspect: str, need: float, used: set[str], query: str = "") -> dict | None:
    """Độ liên quan (thứ tự kho trả về, từ khóa có trong tên clip) là chính; đúng chiều khung, đủ dài, đủ nét để chọn giữa các kết quả gần nhau.
    Kết quả xen kẽ nhiều kho nên thứ hạng tính trong từng kho."""
    best, best_s = None, -1e9
    seen: dict[str, int] = {}
    for it in items:
        rank = seen.get(it["src"], 0)
        seen[it["src"]] = rank + 1
        if rank >= PICK_TOP or f"{it['src']}:{it['id']}" in used:
            continue
        hit = overlap(it, query) if query else 1
        if not hit:
            continue
        s = score(it, aspect, need) - rank * 0.4 + 0.6 * min(hit, 3)
        if s > best_s:
            best, best_s = it, s
    return best


def find_for(query: str, aspect: str, need: float, used: set[str], src: str = "") -> dict | None:
    """Tìm và chọn một clip cho cảnh. Không ra gì thì bỏ bớt từ cuối rồi tìm lại (từ khóa dài quá ít kết quả).
    Clip phải có trong tên ít nhất một từ của từ khóa đang tìm."""
    words = query.split()
    for cut in range(0, min(3, max(0, len(words) - 1)) + 1):
        q = " ".join(words[: len(words) - cut]) if cut else query
        if not q:
            break
        try:
            items = search(q, aspect, src)
        except StockError:
            if cut == 0:
                raise
            continue
        it = auto_pick(items, aspect, need, used, query=q)
        if it:
            return it
    return None


# ------------------------------------------------------------------ tải về
def best_file(it: dict, short: int = SHORT_SIDE) -> dict:
    """File nhỏ nhất mà cạnh ngắn vẫn đủ cho khung (không tải 4K khi chỉ cần 1080), không có thì file lớn nhất."""
    files = [f for f in it.get("files") or [] if f.get("url")]
    if not files:
        raise StockError("Clip này không có file tải được")
    ok = [f for f in files if min(f["w"], f["h"]) >= short]
    return min(ok, key=lambda f: f["w"] * f["h"]) if ok else max(files, key=lambda f: f["w"] * f["h"])


def _download(url: str, out: Path, check_cancel=None) -> None:
    host = urllib.parse.urlparse(url).hostname or ""
    if not url.startswith("https://") or not re.search(r"(^|\.)(pexels\.com|pixabay\.com|wikimedia\.org|vimeo\.com|vimeocdn\.com|akamaized\.net)$", host):
        raise StockError("Đường dẫn tải không thuộc kho video đã biết")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    tmp = out.with_name(out.name + ".part")
    got = 0
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            while True:
                if check_cancel:
                    check_cancel()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                got += len(chunk)
                if got > MAX_BYTES:
                    raise StockError("Clip quá lớn (trên 400 MB), chọn clip khác")
                f.write(chunk)
        tmp.replace(out)
    except urllib.error.HTTPError as e:
        raise StockError(f"Kho video không cho tải clip này (lỗi {e.code}), chọn clip khác") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise StockError(f"Tải clip bị ngắt ({str(getattr(e, 'reason', e))[:80]}). Thử lại.") from None
    finally:
        tmp.unlink(missing_ok=True)


def black_bars(src: Path, start: float = 0.0) -> str:
    """Viền đen sẵn trong clip (phim 4:3 đặt trong khung 16:9, phim màn ảnh rộng): -> bộ lọc crop bỏ viền, hoặc "" nếu không có.
    Không bỏ thì khi cắt cho đầy khung dọc, viền đen nằm lại trong video."""
    from .util import find_ffmpeg
    cmd = [find_ffmpeg()[0], "-hide_banner", "-nostats", "-ss", f"{start + 1:.2f}", "-i", str(src), "-t", "4", "-an",
           "-vf", "fps=4,cropdetect=limit=24:round=2:reset=0", "-f", "null", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return ""
    found = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", p.stderr or "")
    size = re.search(r"Stream .*Video: .*?(\d{2,5})x(\d{2,5})", p.stderr or "")
    if not found or not size:
        return ""
    w, h, x, y = map(int, found[-1])
    W, H = int(size.group(1)), int(size.group(2))
    if w < W * 0.4 or h < H * 0.4 or w * h > W * H * 0.96:      # cảnh tối cả khung (đo nhầm), hoặc viền không đáng kể
        return ""
    return f"crop={w}:{h}:{x}:{y},"


def normalize(src: Path, out: Path, max_seconds: float = MAX_SECONDS, start: float = 0.0) -> float:
    """mp4 H.264 30 khung, không tiếng, bỏ viền đen, cạnh ngắn tối đa 1080 (chẵn), từ giây start. -> thời lượng (giây)."""
    from .util import find_ffmpeg, probe
    vf = (f"{black_bars(src, start)}fps=30,scale='if(lt(iw,ih),min(iw,{SHORT_SIDE}),-2)':'if(lt(iw,ih),-2,min(ih,{SHORT_SIDE}))':flags=lanczos,"
          "setsar=1,format=yuv420p")
    tmp = out.with_name(out.stem + ".part.mp4")
    seek = ["-ss", f"{start:.2f}"] if start > 0 else []
    cmd = [find_ffmpeg()[0], "-hide_banner", "-loglevel", "error", "-y", *seek, "-i", str(src), "-t", f"{max_seconds:.2f}", "-an", "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-movflags", "+faststart", str(tmp)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if p.returncode != 0 or not tmp.is_file():
            raise StockError("Không đọc được clip này (file hỏng hoặc định dạng lạ), chọn clip khác. " + (p.stderr or "")[-200:])
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    dur = float(probe(out).get("duration") or 0)
    if dur < 0.5:
        out.unlink(missing_ok=True)
        raise StockError("Clip quá ngắn, chọn clip khác")
    return dur


def fetch(it: dict, folder: Path, name: str, check_cancel=None) -> tuple[Path, dict]:
    """Tải clip đã chọn vào folder/name (mp4 đã chuẩn hóa). -> (đường dẫn, thông tin nguồn để ghi công)."""
    f = best_file(it)
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / (name + ".download")
    out = folder / name
    try:
        _download(f["url"], raw, check_cancel)
        start = start_at(float(it.get("duration") or 0))
        dur = normalize(raw, out, start=start)
    finally:
        raw.unlink(missing_ok=True)
    meta = {"src": it["src"], "id": it["id"], "title": it.get("title") or "", "author": it.get("author") or "", "author_url": it.get("author_url") or "",
            "page": it.get("page") or "", "license": it.get("license") or "", "duration": round(dur, 3), "source_name": SOURCES[it["src"]]["name"],
            "start": start}
    return out, meta


# ------------------------------------------------------------------ từ khóa
_STOP = set("""a an the of in on at to for with and or but is are was were be been being this that these those it its his her their our your my
from by as into onto over under near very while during after before about above below up down out off one two three some any each every
scene image shot view close closeup close-up wide medium camera framing lighting light mood style illustration cinematic vertical horizontal
composition subject well framed detailed soft warm cool bright dark background foreground looking stands standing sits sitting holds holding
""".split())


def keywords(prompt: str, names: list[str] | None = None, limit: int = 4) -> str:
    """Từ khóa tìm kho từ mô tả hình tiếng Anh, khi không có AI: bỏ từ nối, từ nhiếp ảnh, tên nhân vật."""
    drop = {n.lower() for n in names or [] for n in n.split()}
    words = [w for w in re.findall(r"(?<![\w-])[A-Za-z][A-Za-z'-]+", prompt or "")
             if w.lower() not in _STOP and w.lower() not in drop and len(w) > 2 and not w.lower().endswith(("-old", "-year"))]
    seen, out = set(), []
    for w in words:
        lw = w.lower()
        if lw not in seen:
            seen.add(lw)
            out.append(lw)
        if len(out) >= limit:
            break
    return " ".join(out)
