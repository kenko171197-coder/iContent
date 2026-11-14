"""Tải video theo link (Douyin, Bilibili, Xiaohongshu, Weibo, Kuaishou...) hoặc nhận file có sẵn.

Backend:
  1. yt-dlp  (Bilibili, Douyin*, XiaoHongShu, Weibo, Ixigua, Toutiao, iQiyi, Youku, AcFun, Huya, Douyu, Zhihu...)
     *Douyin: yt-dlp đòi cookie "tươi" -> cấu hình download.cookies_file hoặc cookies_from_browser.
  2. Lệnh ngoài tùy chọn theo nền tảng (download.external), ví dụ lux / f2 / BBDown cho nền tảng
     yt-dlp chưa hỗ trợ (Kuaishou) hoặc khi extractor đang hỏng.
"""
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .util import check_cancel, ffmpeg, find_ffmpeg, log, probe, progress, safe_name, short_hash

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".flv", ".webm", ".avi", ".m4v", ".ts"}

PLATFORMS = {
    "douyin": ("douyin.com", "iesdouyin.com"),
    "bilibili": ("bilibili.com", "b23.tv"),
    "kuaishou": ("kuaishou.com", "gifshow.com"),
    "xiaohongshu": ("xiaohongshu.com", "xhslink.com"),
    "weibo": ("weibo.com", "weibo.cn"),
    "xigua": ("ixigua.com",),
    "toutiao": ("toutiao.com",),
}
SHORT_HOSTS = ("v.douyin.com", "b23.tv", "v.kuaishou.com", "xhslink.com", "t.cn")


def extract_url(text: str) -> str:
    """Lấy link từ chuỗi chia sẻ kiểu '7.43 复制打开抖音，看看【...】 https://v.douyin.com/xxxx/ ...'."""
    m = re.search(r"https?://[^\s\u3000-\u303f\uff00-\uffef\u4e00-\u9fff\"'<>]+", text)
    return m.group(0).rstrip(".,;)") if m else text.strip()


def platform_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for name, hosts in PLATFORMS.items():
        if any(host == h or host.endswith("." + h) for h in hosts):
            return name
    return "web"


def resolve_short(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host not in SHORT_HOSTS:
        return url
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.geturl()


def normalize_url(url: str) -> str:
    url = resolve_short(extract_url(url))
    if platform_of(url) == "douyin":
        # /video/ID, /note/ID, ?modal_id=ID, iesdouyin.com/share/video/ID
        q = parse_qs(urlparse(url).query)
        vid = (q.get("modal_id") or q.get("aweme_id") or [None])[0]
        if not vid:
            m = re.search(r"/(?:video|note|slides)/(\d{8,})", url)
            vid = m.group(1) if m else None
        if vid:
            return f"https://www.douyin.com/video/{vid}"
    elif platform_of(url) == "bilibili":
        url = _bilibili_url(url)
    return url


def _bilibili_url(url: str) -> str:
    """Link Bilibili về dạng chuẩn www.bilibili.com/video/<BV|av>. Link khách dán hay có thêm đoạn ngôn ngữ (/vi/video/, /en/video/
    khi trình duyệt dịch trang) và mã theo dõi (?trackid=, ?spm_id_from=): yt-dlp không nhận ra là Bilibili, tải về trang HTML
    rồi báo "The extracted extension ('html') is unusual". Giữ ?p= (tập mấy của video nhiều phần)."""
    u = urlparse(url)
    if (u.hostname or "").lower().endswith("b23.tv"):
        return url
    q = parse_qs(u.query)
    m = re.search(r"/(?:[a-z]{2}(?:[-_][a-z]{2,4})?/)?video/(BV[0-9A-Za-z]{10}|av\d+)", u.path, re.I)
    vid = m.group(1) if m else (q.get("bvid") or [""])[0]
    if not re.fullmatch(r"BV[0-9A-Za-z]{10}|av\d+", vid or "", re.I):
        return url
    vid = ("BV" + vid[2:]) if vid[:2].lower() == "bv" else ("av" + vid[2:])
    page = (q.get("p") or [""])[0]
    return f"https://www.bilibili.com/video/{vid}/" + (f"?p={page}" if page.isdigit() and page != "1" else "")


# --------------------------------------------------------------------------- main entry

def fetch(src: str, cfg, force: bool = False) -> Path:
    """Tải/nhận nguồn, trả về thư mục job chứa source.mp4 + meta.json. force=True: tải lại."""
    work = Path(cfg.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    p = Path(src.strip().strip('"'))
    if p.is_dir() and (p / "meta.json").exists():          # chạy lại job cũ
        meta = json.loads((p / "meta.json").read_text(encoding="utf-8"))
        if not (force and str(meta.get("source", "")).startswith("http")):
            return p
        src = meta["source"]
    elif p.is_file() and p.suffix.lower() in VIDEO_EXT:
        return _from_local(p, work)

    url = normalize_url(src)
    plat = platform_of(url)
    ext_cmd = (cfg.download.external or {}).get(plat)
    if ext_cmd:
        return _from_external(url, plat, ext_cmd, work, cfg, force)
    return _from_ytdlp(url, plat, work, cfg, force)


def _clear(job: Path) -> None:
    for f in ("source.mp4", "meta.json"):
        (job / f).unlink(missing_ok=True)


def _write_meta(job: Path, meta: dict) -> None:
    info = probe(job / "source.mp4")
    meta.update({k: info[k] for k in ("duration", "width", "height", "has_audio")})
    (job / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def _to_mp4(src: Path, dst: Path) -> None:
    if src.suffix.lower() == ".mp4":
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
    else:
        ffmpeg(["-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", dst])


def _from_local(p: Path, work: Path) -> Path:
    job = work / f"local_{safe_name(p.stem, 40)}_{short_hash(str(p.resolve()), str(p.stat().st_size))[:6]}"
    job.mkdir(exist_ok=True)
    if not (job / "source.mp4").exists():
        log("download", f"Dùng file có sẵn: {p}")
        _to_mp4(p, job / "source.mp4")
    if not (job / "meta.json").exists():
        _write_meta(job, {"source": str(p.resolve()), "platform": "local", "id": p.stem, "title": p.stem, "description": ""})
    return job


def _hook(d: dict) -> None:
    check_cancel()
    if d.get("status") == "downloading":
        tot = d.get("total_bytes") or d.get("total_bytes_estimate")
        if tot:
            progress("download", d.get("downloaded_bytes", 0) / tot)


def _backoff(n: int) -> float:
    """Chờ giữa các lần thử lại: 5 lần thử liền nhau trong một giây vô ích với máy chủ đang bận (HTTP 503)."""
    return min(2.0 ** n, 20.0)


def _ytdlp_opts(cfg, plat: str = "") -> dict:
    from .fixes import cookie_file_for
    d = cfg.download
    ff, _ = find_ffmpeg(cfg.ffmpeg)
    h = int(d.max_height)
    opts = {
        # "res" của yt-dlp = cạnh ngắn -> video dọc 1080x1920 vẫn được tính là 1080p
        "format": "bv*+ba/b",
        "format_sort": [f"res:{h}", "vcodec:h264", "acodec:aac"],
        "merge_output_format": "mp4",
        "ffmpeg_location": str(Path(ff).parent),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "socket_timeout": 30,
        "retry_sleep_functions": {"http": _backoff, "fragment": _backoff, "extractor": _backoff},
        "progress_hooks": [_hook],
    }
    cookies = cookie_file_for(plat, cfg)
    if cookies:
        opts["cookiefile"] = cookies
    if d.cookies_from_browser:
        opts["cookiesfrombrowser"] = (d.cookies_from_browser,)
    if d.proxy:
        opts["proxy"] = d.proxy
    return opts


def _from_ytdlp(url: str, plat: str, work: Path, cfg, force: bool = False) -> Path:
    import yt_dlp
    from yt_dlp.utils import DownloadError

    opts = _ytdlp_opts(cfg, plat)
    info = _extract(yt_dlp, DownloadError, url, plat, opts)

    vid = str(info.get("id") or short_hash(url))
    job = work / f"{plat}_{safe_name(vid, 40)}"
    job.mkdir(exist_ok=True)
    if force:
        _clear(job)
    if not (job / "source.mp4").exists():
        log("download", f"[{plat}] {info.get('title', '')[:70]}  ({info.get('duration') or '?'}s) ...")
        opts["outtmpl"] = str(job / "dl.%(ext)s")
        for attempt in range(3):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.process_ie_result(info, download=True)
                break
            except DownloadError as e:
                if attempt == 2 or not SERVER_BUSY.search(str(e)):
                    raise
                # máy chủ video bận/chặn tạm thời: chờ rồi xin link tải mới (link cũ có hạn dùng, có khi trỏ vào máy chủ khác)
                wait = 20 * (attempt + 1)
                log("download", f"Máy chủ {plat} báo bận ({_short_err(e)}), chờ {wait} giây rồi thử lại ...")
                _sleep(wait)
                for f in job.glob("dl.*"):
                    f.unlink(missing_ok=True)
                info = _extract(yt_dlp, DownloadError, url, plat, opts)
        got = sorted((f for f in job.glob("dl.*") if f.suffix.lower() in VIDEO_EXT), key=lambda f: f.stat().st_size)
        if not got:
            raise RuntimeError("yt-dlp chạy xong nhưng không thấy file video")
        _to_mp4(got[-1], job / "source.mp4")
        for f in job.glob("dl.*"):
            f.unlink(missing_ok=True)
    if not (job / "meta.json").exists():
        _write_meta(job, {
            "source": url, "platform": plat, "id": vid,
            "title": info.get("title") or "", "description": (info.get("description") or "")[:1000],
            "uploader": info.get("uploader") or "",
        })
    return job


SERVER_BUSY = re.compile(r"HTTP Error 5\d\d|Service Unavailable|Bad Gateway|Gateway Time-?out", re.I)


def _short_err(e) -> str:
    return re.sub(r"^ERROR:\s*", "", str(e).strip().splitlines()[0])[:120]


def _sleep(sec: float) -> None:
    end = time.time() + sec
    while time.time() < end:
        check_cancel()
        time.sleep(max(0.0, min(1.0, end - time.time())))


def _extract(yt_dlp, DownloadError, url: str, plat: str, opts: dict) -> dict:
    """Đọc thông tin video (chưa tải). Lỗi quen thì đổi thành câu dễ hiểu, giao diện còn gắn thêm nút sửa (fixes.py)."""
    info = None
    for attempt in range(2):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            break
        except DownloadError as e:
            msg = str(e)
            if plat == "douyin" and "cookies" in msg.lower():
                lead = ("Douyin không nhận cookie đã nạp (cookie cũ, hoặc xuất lúc trang chưa tải xong). " if opts.get("cookiefile")
                        else "Douyin yêu cầu cookie của trình duyệt. ")
                raise RuntimeError(lead + "Trong Studio: bấm Thêm cookie Douyin ở thẻ lỗi. Dòng lệnh: --cookies cookies.txt\n"
                                   f"Chi tiết: {msg}") from e
            if attempt == 0 and SERVER_BUSY.search(msg):
                log("download", f"Máy chủ {plat} báo bận ({_short_err(e)}), chờ 15 giây rồi thử lại ...")
                _sleep(15)
                continue
            raise RuntimeError(f"yt-dlp không tải được {url}: {msg}") from e

    if info.get("_type") == "playlist":
        entries = [e for e in info.get("entries") or [] if e]
        if not entries:
            raise RuntimeError("Link là playlist rỗng")
        log("download", f"Link là playlist ({len(entries)} video) — chỉ lấy video đầu. Dùng links.txt để chạy nhiều video.")
        info = entries[0]
    if plat != "web" and str(info.get("extractor_key") or info.get("extractor") or "").lower() == "generic":
        # trang của nền tảng quen mà yt-dlp chỉ đọc như trang web thường: link không trỏ tới video (hoặc là kiểu link mới)
        raise RuntimeError(f"Không thấy video trong link này: {url}\n"
                           "Mở đúng video, bấm Chia sẻ → Sao chép liên kết rồi dán lại.")
    return info


def _from_external(url: str, plat: str, cmd_tpl: str, work: Path, cfg, force: bool = False) -> Path:
    m = re.search(r"(\d{8,}|BV[0-9A-Za-z]{10})", url)
    vid = m.group(1) if m else short_hash(url)
    job = work / f"{plat}_{vid}"
    job.mkdir(exist_ok=True)
    if force:
        _clear(job)
    if not (job / "source.mp4").exists():
        raw = job / "raw"
        raw.mkdir(exist_ok=True)
        from .fixes import cookie_file_for
        cmd = cmd_tpl.format(url=url, dir=str(raw), cookies=cookie_file_for(plat, cfg))
        log("download", f"[{plat}] lệnh ngoài: {cmd}")
        r = subprocess.run(shlex.split(cmd, posix=False), capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"Lệnh tải ngoài lỗi:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
        vids = sorted((f for f in raw.rglob("*") if f.suffix.lower() in VIDEO_EXT), key=lambda f: f.stat().st_size)
        if not vids:
            raise RuntimeError(f"Lệnh ngoài không tạo ra file video trong {raw}")
        _to_mp4(vids[-1], job / "source.mp4")
        shutil.rmtree(raw, ignore_errors=True)
    if not (job / "meta.json").exists():
        _write_meta(job, {"source": url, "platform": plat, "id": vid, "title": vid, "description": ""})
    return job
