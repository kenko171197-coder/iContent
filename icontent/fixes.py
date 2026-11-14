"""Gặp lỗi thì chỉ cách sửa.

Nhận ra các lỗi hay gặp ở máy khách (Douyin cần cookie, link không phải trang video, máy chủ bên kia bận, bộ mô hình AI hỏng,
mất mạng, ổ đầy...) rồi trả về cho giao diện: tên lỗi dễ hiểu, vì sao, các bước làm và nút "sửa ngay".

Đồng thời sửa tận gốc hai chuyện môi trường:
- Cookie theo từng trang (cookies/<trang>.txt), nạp qua trình hướng dẫn kéo thả file thay vì bắt khách sửa config.yaml.
- Bộ đệm mô hình Hugging Face dạng symlink: máy bật Developer Mode (hoặc chạy quyền admin) thì thư mục snapshots chứa
  symlink trỏ vào blobs. ONNX Runtime 1.2x+ kiểm tra file dữ liệu ngoài (.data) phải nằm cùng thư mục với file .onnx
  sau khi giải symlink, nên báo "External data path ... escapes model directory" và không nạp được giọng VieNeu.
  Máy không tạo được symlink (như máy dựng bản phát hành) thì HF chép file thật nên không gặp.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from .util import ROOT, hf_cache_dir, log

# ============================================================================ cookie theo trang

COOKIE_DIR = ROOT / "cookies"
SITES = {
    # key: cookie mà trang tự đặt khi mở bằng trình duyệt thật; thiếu nó thì gần như chắc chắn xuất nhầm hoặc trang chưa tải xong
    "douyin": {"name": "Douyin", "domain": "douyin.com", "home": "https://www.douyin.com/", "key": "s_v_web_id"},
    "bilibili": {"name": "Bilibili", "domain": "bilibili.com", "home": "https://www.bilibili.com/", "key": "buvid3"},
    "kuaishou": {"name": "Kuaishou", "domain": "kuaishou.com", "home": "https://www.kuaishou.com/", "key": "did"},
    "xiaohongshu": {"name": "Xiaohongshu", "domain": "xiaohongshu.com", "home": "https://www.xiaohongshu.com/explore", "key": "a1"},
}
EXTENSIONS = {
    "chrome": "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc",
    "firefox": "https://addons.mozilla.org/firefox/addon/get-cookies-txt-locally/",
}
NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n# Tạo bởi Studio566. Chỉ chứa cookie của một trang, không chia sẻ file này cho người khác.\n\n"


def cookie_path(site: str) -> Path:
    if site not in SITES:
        raise ValueError(f"Trang không hỗ trợ cookie: {site}")
    return COOKIE_DIR / f"{site}.txt"


def cookie_file_for(plat: str, cfg=None) -> str:
    """File cookie dùng khi tải từ nền tảng plat: file nạp qua giao diện, không có thì download.cookies_file trong config."""
    if plat in SITES and cookie_path(plat).is_file():
        return str(cookie_path(plat))
    return str(cfg.download.cookies_file or "") if cfg is not None else ""


def _site_of_domain(domain: str, site: str) -> bool:
    d = domain.lstrip(".").lower()
    want = SITES[site]["domain"]
    return d == want or d.endswith("." + want)


def parse_cookies(text: str, site: str) -> list[dict]:
    """Nhận 3 kiểu khách hay có: file Netscape (cookies.txt), JSON (Cookie-Editor, Get cookies.txt LOCALLY bản JSON),
    hoặc chuỗi "a=1; b=2" chép từ trình duyệt. Chỉ giữ cookie của đúng trang (file "Export All Cookies" có cả trang khác)."""
    text = (text or "").lstrip("﻿").strip()
    out: list[dict] = []
    if not text:
        return out
    if text[0] in "[{":
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict):
            data = data.get("cookies") or data.get("Cookies") or []
        if isinstance(data, list):
            for c in data:
                if not isinstance(c, dict) or not c.get("name"):
                    continue
                dom = str(c.get("domain") or c.get("host") or "")
                if not dom or not _site_of_domain(dom, site):
                    continue
                exp = c.get("expirationDate") or c.get("expires") or c.get("expiry") or 0
                try:
                    exp = int(float(exp))
                except (TypeError, ValueError):
                    exp = 0
                if c.get("hostOnly") is False and not dom.startswith("."):
                    dom = "." + dom
                out.append({"domain": dom, "path": str(c.get("path") or "/"), "secure": bool(c.get("secure")),
                            "expires": max(exp, 0), "name": str(c["name"]), "value": str(c.get("value") or "")})
            return out
    lines = text.splitlines()
    if any(ln.count("\t") >= 6 for ln in lines):
        for ln in lines:
            if ln.startswith("#HttpOnly_"):
                ln = ln[len("#HttpOnly_"):]
            if not ln.strip() or ln.startswith("#"):
                continue
            f = ln.rstrip("\r\n").split("\t")
            if len(f) < 7 or not _site_of_domain(f[0], site):
                continue
            try:
                exp = int(float(f[4] or 0))
            except ValueError:
                exp = 0
            out.append({"domain": f[0], "path": f[2] or "/", "secure": f[3].upper() == "TRUE", "expires": max(exp, 0),
                        "name": f[5], "value": "\t".join(f[6:])})
        return out
    # chuỗi header "Cookie: a=1; b=2"
    s = re.sub(r"^\s*cookie\s*:\s*", "", text, flags=re.I)
    dom = "." + SITES[site]["domain"]
    for part in s.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()
            if k and not re.search(r"\s", k):
                out.append({"domain": dom, "path": "/", "secure": False, "expires": 0, "name": k, "value": v.strip()})
    return out


def save_cookies(site: str, text: str) -> dict:
    """Kiểm tra rồi lưu cookie của một trang. Lỗi thì ValueError với lời dễ hiểu (giao diện hiện nguyên câu)."""
    info = SITES.get(site)
    if not info:
        raise ValueError("Trang này chưa hỗ trợ nạp cookie")
    cookies = parse_cookies(text, site)
    if not cookies:
        others = cookie_domains(text)
        if others:
            raise ValueError(f"File này là cookie của {', '.join(others[:2])}, không phải {info['domain']}: lúc bấm Export bạn đang "
                             f"đứng ở trang khác. Chuyển sang tab {info['domain']} (chờ trang hiện video) rồi bấm Export lại")
        raise ValueError(f"Không thấy cookie nào của {info['domain']} trong file này. Hãy mở {info['domain']} trên trình duyệt, "
                         f"chờ trang hiện video rồi bấm Export trong tiện ích ngay trên trang đó")
    now = time.time()
    live = [c for c in cookies if not c["expires"] or c["expires"] > now]
    if not live:
        raise ValueError("Cookie trong file đã hết hạn hết. Mở lại trang trên trình duyệt rồi xuất cookie mới")
    seen: dict[tuple, dict] = {}
    for c in live:
        seen[(c["domain"], c["path"], c["name"])] = c
    rows = []
    for c in seen.values():
        dom = c["domain"]
        rows.append("\t".join([dom, "TRUE" if dom.startswith(".") else "FALSE", c["path"], "TRUE" if c["secure"] else "FALSE",
                               str(int(c["expires"])), c["name"], c["value"].replace("\n", "")]))
    p = cookie_path(site)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(NETSCAPE_HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    tmp.replace(p)
    names = {c["name"] for c in seen.values()}
    log("cookies", f"Đã lưu {len(rows)} cookie của {info['name']}")
    return {"site": site, "count": len(rows), "key_ok": info["key"] in names, "key": info["key"]}


def cookie_domains(text: str) -> list[str]:
    """Các trang có cookie trong file (để nói rõ khi khách xuất nhầm trang), trang nhiều cookie nhất trước."""
    text = (text or "").lstrip("\ufeff").strip()
    doms: list[str] = []
    if text[:1] and text[:1] in "[{":
        try:
            data = json.loads(text)
            data = (data.get("cookies") or data.get("Cookies") or []) if isinstance(data, dict) else data
            doms = [str(c.get("domain") or c.get("host") or "") for c in data if isinstance(c, dict)]
        except (ValueError, AttributeError):
            doms = []
    else:
        doms = [ln.removeprefix("#HttpOnly_").split("\t")[0] for ln in text.splitlines() if ln.count("\t") >= 6]
    count: dict[str, int] = {}
    for d in doms:
        d = d.strip().lstrip(".").lower()
        parts = d.split(".")
        base = ".".join(parts[-3:] if len(parts) > 2 and len(parts[-1]) == 2 and len(parts[-2]) <= 3 else parts[-2:])
        if base:
            count[base] = count.get(base, 0) + 1
    return sorted(count, key=lambda k: -count[k])


def downloads_dir() -> Path:
    """Thư mục Tải về thật của khách (có thể đã chuyển sang ổ khác), không đoán theo tên."""
    if os.name == "nt":
        import ctypes
        import uuid
        from ctypes import wintypes
        guid = ctypes.create_string_buffer(uuid.UUID("374DE290-123F-4565-9164-39C4925E467B").bytes_le, 16)      # FOLDERID_Downloads
        out = ctypes.c_wchar_p()
        try:
            if ctypes.windll.shell32.SHGetKnownFolderPath(guid, 0, None, ctypes.byref(out)) == 0 and out.value:
                p = Path(out.value)
                ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(out, wintypes.LPVOID))
                return p
        except (OSError, AttributeError):
            pass
    return Path.home() / "Downloads"


def cookie_from_downloads(site: str, since: float, folder: Path | None = None) -> dict:
    """Khách vừa bấm Export trong tiện ích: trình duyệt lưu file cookie vào Tải về. Tìm file cookie mới nhất (sửa sau since) có cookie
    của trang này rồi nạp luôn, khách khỏi phải kéo thả. Chỉ đọc file tên có chữ "cookie", nhỏ hơn 2 MB."""
    info = SITES.get(site)
    if not info:
        raise ValueError("Trang này chưa hỗ trợ nạp cookie")
    d = folder or downloads_dir()
    try:
        files = [f for f in d.iterdir() if f.is_file() and "cookie" in f.name.lower() and f.suffix.lower() in (".txt", ".json")]
    except OSError:
        return {"found": False}
    files = [f for f in files if f.stat().st_mtime >= since - 1 and f.stat().st_size < 2 * 1024 * 1024]
    wrong = ""
    for f in sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)[:6]:
        text = f.read_text(encoding="utf-8", errors="replace")
        if parse_cookies(text, site):
            return {"found": True, "file": f.name, **save_cookies(site, text)}
        wrong = wrong or f.name
    if wrong:
        doms = cookie_domains((d / wrong).read_text(encoding="utf-8", errors="replace"))
        return {"found": False, "wrong": wrong, "domains": doms[:2],
                "message": f"Vừa thấy file {wrong} nhưng đó là cookie của {', '.join(doms[:2]) or 'trang khác'}. "
                           f"Chuyển sang tab {info['domain']} rồi bấm Export lại"}
    return {"found": False}


def delete_cookies(site: str) -> None:
    cookie_path(site).unlink(missing_ok=True)


def cookie_status() -> dict:
    out = {}
    for site, info in SITES.items():
        p = cookie_path(site)
        st = {"name": info["name"], "has": p.is_file(), "home": info["home"]}
        if st["has"]:
            rows = parse_cookies(p.read_text(encoding="utf-8", errors="replace"), site)
            st.update(count=len(rows), saved=p.stat().st_mtime, key_ok=info["key"] in {c["name"] for c in rows})
        out[site] = st
    return out


# ============================================================================ bộ đệm mô hình

def unsymlink_models(cache: Path | None = None) -> int:
    """Đổi symlink trong snapshots của các mô hình ONNX thành file thật (hard link vào blob: không tốn thêm chỗ; ổ không
    hỗ trợ hard link thì chép). Trả về số file đã đổi. Chạy nhanh, gọi trước mỗi lần nạp mô hình cũng được."""
    root = Path(cache) if cache else hf_cache_dir()
    if not root.is_dir():
        return 0
    n = 0
    for repo in root.glob("models--*"):
        snaps = repo / "snapshots"
        if not snaps.is_dir():
            continue
        try:
            files = list(snaps.rglob("*"))
        except OSError:
            continue
        links = [p for p in files if p.is_symlink()]
        if not links or not any(p.suffix.lower() in (".onnx", ".data", ".ort") for p in files):
            continue
        for p in links:
            try:
                if _materialize(p):
                    n += 1
            except OSError as e:
                log("models", f"Không đổi được {p.name}: {e}")
    if n:
        log("models", f"Đã đổi {n} file mô hình dạng lối tắt (symlink) thành file thật")
    return n


def _materialize(p: Path) -> bool:
    target = Path(os.path.realpath(p))
    if target == p or not target.is_file():
        return False      # lối tắt hỏng: để Hugging Face tải lại
    tmp = p.with_name(p.name + ".ic-tmp")
    tmp.unlink(missing_ok=True)
    try:
        os.link(target, tmp)
    except OSError:
        shutil.copy2(target, tmp)
    p.unlink()
    os.replace(tmp, p)
    return True


MODEL_REPOS = {
    # tên thư mục trong bộ đệm Hugging Face của từng nhóm mô hình (để "Tải lại" đúng phần hỏng)
    "tts": ("models--pnnbao-ump--VieNeu*", "models--OpenMOSS-Team--MOSS-Audio-Tokenizer*"),
    "asr": (),      # theo cỡ Whisper đang chọn, xem remove_model_cache
    "speakers": ("models--csukuangfj--sherpa-onnx-pyannote*", "models--csukuangfj--speaker-embedding*"),
}
MODEL_NAMES = {"tts": "Bộ giọng đọc VieNeu", "asr": "Nhận dạng giọng nói (Whisper)", "speakers": "Nhận diện người nói"}


def remove_model_cache(kind: str, asr_model: str = "") -> list[str]:
    """Xóa bộ đệm của một nhóm mô hình để tải lại từ đầu. Trả về tên các thư mục đã xóa.
    Whisper chỉ xóa đúng cỡ đang dùng (máy có thể giữ thêm bản 3 GB khác, tải lại rất lâu)."""
    if kind not in MODEL_REPOS:
        raise ValueError(f"Không rõ mô hình: {kind}")
    pats = MODEL_REPOS[kind]
    if kind == "asr":
        from .asr import WHISPER_REPOS
        repo = WHISPER_REPOS.get(asr_model, ("",))[0]
        pats = ("models--" + repo.replace("/", "--"),) if repo else ()
    root = hf_cache_dir()
    gone = []
    for pat in pats:
        for d in root.glob(pat):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
                gone.append(d.name)
    return gone


def model_kind_of(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ("vieneu", "moss_audio", "moss-audio", "giọng đọc", "[tts]")):
        return "tts"
    if any(k in t for k in ("whisper", "ctranslate", "model.bin", "[asr]", "large-v", "medium", "nhận dạng")):
        return "asr"
    if any(k in t for k in ("sherpa", "speaker", "người nói", "segmentation")):
        return "speakers"
    return "tts"


# ============================================================================ nhận ra lỗi

PLAT_NAMES = {"douyin": "Douyin", "bilibili": "Bilibili", "kuaishou": "Kuaishou", "xiaohongshu": "Xiaohongshu",
              "weibo": "Weibo", "xigua": "Xigua", "toutiao": "Toutiao"}

A_RETRY = {"id": "retry", "label": "Thử lại"}
A_FILE = {"id": "pick_file", "label": "Dùng file video có sẵn"}
A_YTDLP = {"id": "update_ytdlp", "label": "Cập nhật bộ tải video"}
A_REPORT = {"id": "copy_report", "label": "Chép thông tin lỗi"}


def _rules():
    """(mẫu lỗi, hàm tạo lời chỉ dẫn). Mẫu đầu tiên khớp được dùng. ctx: site (tên trang), plat, has_cookie."""
    return [
        (r"Không dịch được bằng|Google đang tạm chặn máy này|Dịch offline chưa chạy được|Chưa tải Dịch offline", _translate_failed),
        (r"Chưa có key tạo ảnh nào|Chưa có cách vẽ ảnh nào|Chưa tải Vẽ ảnh offline", _image_none),
        (r"Chưa tải Giọng đọc nhiều thứ tiếng|Bộ đọc nhiều thứ tiếng (không khởi động|khởi động quá lâu)", _voices_pack),
        (r"Đang tắt tính năng trả phí", lambda c: {
            "code": "paid_off", "title": "Việc này tính tiền, đang bị khóa",
            "why": "Studio566 ưu tiên cách miễn phí: các việc gọi AI tính tiền (vẽ ảnh bằng Gemini, OpenAI, Meta Muse; AI làm clip) chỉ chạy khi bạn bật.",
            "steps": ["Dùng cách miễn phí: nguồn ảnh Tự chọn hoặc Vẽ trên máy; Video nền thay cho clip AI.",
                      "Muốn dùng bản trả phí: Cài đặt, mục Chi phí, bật Cho phép tính năng trả phí. Mỗi lần tốn tiền Studio566 vẫn báo giá và hỏi trước."],
            "actions": [{"id": "open", "label": "Mở mục Chi phí", "href": "#/settings", "focus": "chi-phi", "primary": True}]}),
        (r"gói miễn phí không tạo video|Google không cho tạo video ở gói này", lambda c: {
            "code": "video_billing", "title": "Key Gemini chưa làm được clip AI",
            "why": "Tạo video của Google (Gemini Omni) không có gói miễn phí. Key đang dùng là gói miễn phí nên Google từ chối, lần này không bị tính tiền.",
            "steps": ["Mở aistudio.google.com, mục Billing, bật thanh toán cho project của key (khoảng 0,07 USD mỗi giây clip ở 720p).",
                      "Hoặc dùng Video nền miễn phí: bấm Tìm video nền cho mọi cảnh, Studio566 lấy video quay thật từ kho có giấy phép.",
                      "Bật thanh toán xong bấm lại AI làm clip."],
            "actions": [{"id": "open", "label": "Mở trang Billing", "href": "https://aistudio.google.com/usage?tab=billing", "primary": True},
                        {"id": "open", "label": "Cài đặt video nền", "href": "#/settings", "focus": "video-nen"}]}),
        (r"Chưa có key (Pexels|Pixabay)", lambda c: {
            "code": "stock_key", "title": "Cần key miễn phí của kho video",
            "why": "Pexels và Pixabay cho dùng video miễn phí nhưng cần key (đăng ký một phút, không mất tiền). Wikimedia Commons thì không cần key.",
            "steps": ["Mở Cài đặt, mục Video nền miễn phí, bấm link lấy key, đăng ký rồi dán key vào và bấm Lưu.",
                      "Chưa muốn đăng ký: chọn kho Wikimedia Commons (ít video dọc hơn) hoặc Mọi kho đã sẵn sàng."],
            "actions": [{"id": "open", "label": "Mở Cài đặt video nền", "href": "#/settings", "focus": "video-nen", "primary": True}]}),
        (r"(?i)douyin.*cookie|fresh cookies", _douyin_cookie),
        (r"Chưa tải được bộ tách nhạc nền|Bộ tách nhạc nền bị hỏng|Không tách được nhạc nền|audio\.separate=on nhưng chưa cài", lambda c: {
            "code": "separate", "title": "Chưa tách được nhạc nền",
            "why": "Lần đầu tách nhạc nền, Studio566 cần tải bộ tách (67 MB). Lần này tải hoặc chạy không được, "
                   "hay gặp khi mất mạng, bị chặn GitHub, hoặc dùng bản Studio566 cũ (bản cũ cần cài thêm thư viện riêng).",
            "steps": ["Kiểm tra mạng rồi bấm Thử lại: phần đã tải được giữ lại, tải tiếp chứ không tải lại từ đầu.",
                      "Cần làm gấp: mở Tùy chọn → Âm thanh → Tách nhạc nền khỏi giọng gốc, chọn Tự động hoặc Tắt rồi Thử lại. "
                      "Video vẫn lồng tiếng bình thường, tiếng gốc được giữ nhỏ dưới giọng lồng.",
                      "Đang dùng bản cũ: cài bản Studio566 mới nhất (cài đè, giữ nguyên video và cài đặt)."],
            "actions": [dict(A_RETRY, primary=True)]}),
        (r"(?i)external data path|escapes model directory", lambda c: {
            "code": "model_symlink", "title": "Bộ giọng đọc cần sửa lại cách lưu file",
            "why": "Windows trên máy này lưu file mô hình dạng lối tắt (symlink), bản ONNX Runtime mới không chịu đọc kiểu đó. "
                   "Bản Studio566 này đã tự sửa khi nạp giọng, bấm Sửa ngay để chắc chắn.",
            "steps": ["Bấm Sửa ngay: Studio566 đổi các lối tắt thành file thật (vài giây, không phải tải lại).",
                      "Xong bấm Thử lại (lỗi ở trang khác thì bấm lại nút vừa báo lỗi)."],
            "actions": [{"id": "repair_models", "label": "Sửa ngay", "primary": True}, A_RETRY]}),
        (r"(?i)INVALID_PROTOBUF|protobuf parsing failed|NO_SUCHFILE|load model from .* failed|"
         r"safetensors_rust|HeaderTooLarge|BadZipFile|file is not a zip|unable to open file.*model", lambda c: {
            "code": "model_broken", "title": f"File mô hình bị hỏng ({MODEL_NAMES[c['model']]})",
            "why": "Lần tải trước bị ngắt giữa chừng (mất mạng, tắt máy) nên file trên ổ không đầy đủ.",
            "steps": ["Bấm Tải lại mô hình: Studio566 xóa bản hỏng và tải bản mới trong hàng đợi (có thanh tiến độ).",
                      "Tải xong bấm Thử lại (lỗi ở trang khác thì bấm lại nút vừa báo lỗi)."],
            "actions": [{"id": "redownload", "label": "Tải lại mô hình", "primary": True, "model": c["model"]}, A_RETRY]}),
        (r"(?i)huggingface\.co|LocalEntryNotFound|couldn't connect to .*hugging|cas-bridge|xethub|hf_xet|không tải được mô hình", lambda c: {
            "code": "model_download", "title": "Không tải được mô hình AI",
            "why": "Lần đầu dùng, Studio566 phải tải mô hình từ huggingface.co nhưng kết nối bị chặn hoặc chập chờn.",
            "steps": ["Kiểm tra mạng, tắt VPN/1.1.1.1/proxy nếu đang bật (hoặc ngược lại: bật VPN nếu nhà mạng chặn).",
                      "Bấm Tải lại mô hình, chờ thanh tiến độ trong hàng đợi chạy hết rồi làm lại việc vừa lỗi."],
            "actions": [{"id": "redownload", "label": "Tải lại mô hình", "primary": True, "model": c["model"]}, A_RETRY]}),
        (r"(?i)extracted extension \('?html'?\)|unsupported url|is not a valid url|không thấy video trong link", lambda c: {
            "code": "link_not_video", "title": "Link này không phải trang của một video",
            "why": "Studio566 mở link nhưng chỉ thấy trang web, không thấy video. Hay gặp khi link bị thêm phần phụ "
                   "(ngôn ngữ /vi/, mã theo dõi) hoặc là link trang chủ, kênh, tìm kiếm.",
            "steps": ["Bản này đã tự bỏ phần phụ của link Bilibili: bấm Thử lại trước.",
                      "Vẫn lỗi: mở đúng video, bấm Chia sẻ → Sao chép liên kết rồi dán lại. Link Bilibili đúng có dạng bilibili.com/video/BV…",
                      "Link đúng mà vẫn lỗi: bấm Cập nhật bộ tải video."],
            "actions": [dict(A_RETRY, primary=True), A_YTDLP, A_FILE]}),
        (r"(?i)HTTP Error 5\d\d|máy chủ \S+ báo bận", lambda c: {
            "code": "server_busy", "title": f"Máy chủ {c['site']} đang bận hoặc tạm chặn",
            "why": f"Lỗi nằm phía {c['site']} (mã 5xx), không phải do máy bạn. Studio566 đã tự thử lại vài lần. Thường hết sau vài phút.",
            "steps": ["Đợi 2–5 phút rồi bấm Thử lại.",
                      "Vẫn lỗi: tắt VPN/1.1.1.1 hoặc đổi mạng (Wi-Fi khác, phát 4G từ điện thoại) rồi thử lại.",
                      "Cần gấp: tải video về máy bằng cách khác rồi kéo file vào ô Dán link."],
            "actions": [dict(A_RETRY, primary=True), A_FILE]}),
        (r"(?i)HTTP Error 404|视频不见了|啊叻|video (is )?(unavailable|private|removed|deleted)|has been removed|不存在|private video", lambda c: {
            "code": "video_gone", "title": "Video không còn hoặc đã bị ẩn",
            "why": "Người đăng đã xóa, ẩn video, hoặc video chỉ cho thành viên xem.",
            "steps": ["Mở link trên trình duyệt: không xem được thì không tải được.", "Xem được mà vẫn lỗi: bấm Thử lại."],
            "actions": [A_RETRY, A_FILE]}),
        (r"(?i)HTTP Error 403|geo.?restrict|not available in your (country|region)|该视频.*地区", lambda c: {
            "code": "blocked", "title": f"{c['site']} chặn tải từ mạng của bạn",
            "why": "Trang từ chối yêu cầu (mã 403): có thể do vùng mạng, do cần cookie, hoặc bộ tải video đã cũ.",
            "steps": ["Bấm Cập nhật bộ tải video rồi Thử lại.",
                      f"Vẫn lỗi: nạp cookie {c['site']} (Cài đặt → Cookie tải video) hoặc thử đổi mạng/VPN."],
            "actions": [dict(A_YTDLP, primary=True), A_RETRY]
                       + ([{"id": "cookies", "label": f"Thêm cookie {c['site']}", "site": c["plat"]}] if c["plat"] in SITES else [])}),
        (r"(?i)getaddrinfo|name or service not known|failed to resolve|temporary failure in name resolution|timed? ?out|"
         r"connection (reset|refused|aborted)|network is unreachable|newconnectionerror|remotedisconnected|max retries exceeded|"
         r"ssl: |certificate verify failed|WinError 10060|WinError 10054|WinError 11001|không kết nối", lambda c: {
            "code": "network", "title": "Mất kết nối mạng",
            "why": "Studio566 không kết nối được tới máy chủ cần dùng.",
            "steps": ["Kiểm tra mạng (mở thử một trang web).", "Đang bật VPN/1.1.1.1/proxy thì thử tắt, hoặc đổi mạng khác.",
                      "Có mạng lại thì bấm Thử lại."],
            "actions": [dict(A_RETRY, primary=True)]}),
        (r"(?i)unable to (extract|download (json|webpage|api))|failed to parse json|extractor error|ExtractorError|"
         r"No video formats found|Requested format is not available", lambda c: {
            "code": "extractor", "title": "Bộ tải video cần cập nhật",
            "why": f"{c['site']} vừa đổi cách hiển thị video nên bộ tải (yt-dlp) bản hiện tại không đọc được nữa.",
            "steps": ["Bấm Cập nhật bộ tải video (khoảng 10–30 giây, cần mạng).", "Xong bấm Thử lại."],
            "actions": [dict(A_YTDLP, primary=True), A_RETRY, A_FILE]}),
        (r"(?i)no space left|not enough space|errno 28|WinError 112|disk full|ổ (đĩa )?đầy", lambda c: {
            "code": "disk_full", "title": "Ổ đĩa đã đầy",
            "why": "Video và file tạm cần chỗ trống, ổ chứa Studio566 không còn đủ.",
            "steps": ["Mở Thư viện → Dọn dung lượng để xóa file tạm an toàn.", "Xóa bớt video cũ không cần nữa rồi bấm Thử lại."],
            "actions": [{"id": "open", "label": "Mở Thư viện", "href": "#/library", "primary": True}, A_RETRY]}),
        (r"(?i)không tìm thấy ffmpeg|ffmpeg (is )?not (installed|found)", lambda c: {
            "code": "ffmpeg", "title": "Máy chưa có ffmpeg (bộ xử lý video)",
            "why": "ffmpeg được cài cùng Studio566 nhưng trên máy này đã bị thiếu hoặc bị xóa.",
            "steps": ["Chạy lại file cài Studio566-Setup, chọn đúng thư mục cũ: bộ cài tự tải ffmpeg, giữ nguyên video và cài đặt.",
                      "Hoặc mở PowerShell gõ: winget install Gyan.FFmpeg, rồi tắt mở lại Studio566."],
            "actions": [A_REPORT]}),
        (r"(?i)cuda out of memory|CUBLAS_STATUS_ALLOC_FAILED|out of memory|cudaErrorMemoryAllocation|bad_alloc|MemoryError", lambda c: {
            "code": "memory", "title": "Hết bộ nhớ (RAM hoặc card đồ họa)",
            "why": "Video dài hoặc nhiều chương trình đang mở cùng lúc làm máy hết bộ nhớ.",
            "steps": ["Tắt bớt chương trình nặng (game, trình duyệt nhiều tab, phần mềm dựng phim).", "Bấm Thử lại.",
                      "Vẫn lỗi: cắt video thành đoạn ngắn hơn rồi chạy từng đoạn."],
            "actions": [dict(A_RETRY, primary=True)]}),
        (r"(?i)WinError 32|being used by another process|permission denied|WinError 5\b|access is denied", lambda c: {
            "code": "file_locked", "title": "File đang bị chương trình khác giữ",
            "why": "Một chương trình khác (trình xem video, phần mềm dựng, diệt virus, OneDrive) đang mở file Studio566 cần ghi.",
            "steps": ["Đóng trình xem video hoặc phần mềm đang mở file đó.", "Bấm Thử lại."],
            "actions": [dict(A_RETRY, primary=True)]}),
    ]


A_AI_SETTINGS = {"id": "open", "label": "Mở Mô-đun AI", "href": "#/settings", "focus": "mo-dun-ai"}


def _translate_failed(c: dict) -> dict:
    from .offline import ready
    if not ready():
        return {
            "code": "translate_failed", "title": "Không tự dịch được: nên tải Dịch offline",
            "why": "AI dịch (Gemini, Claude...) đang quá tải, hết hạn mức hoặc sai key, và Google dịch miễn phí cũng đang chặn. "
                   "Dịch offline chạy ngay trên máy nên không gặp các lỗi này, không cần key.",
            "steps": ["Bấm Tải Dịch offline (khoảng 1,2 GB, chỉ tải một lần, có thanh tiến độ).",
                      "Tải xong bấm Thử lại: Studio566 dịch tiếp đúng các câu còn thiếu, câu đã dịch giữ nguyên.",
                      "Cần gấp: mở video trong Studio và tự điền bản dịch."],
            "actions": [{"id": "ai_pack", "label": "Tải Dịch offline", "pack": "translate", "primary": True}, A_RETRY]}
    return {
        "code": "translate_failed", "title": "Không tự dịch được",
        "why": "Cả AI dịch, dịch offline trên máy và Google dịch đều báo lỗi. Chi tiết của từng cách nằm ở dòng lỗi bên dưới.",
        "steps": ["Bấm Thử lại: Studio566 dịch tiếp các câu còn thiếu.",
                  "Vẫn lỗi: mở Cài đặt > Mô-đun AI miễn phí, bấm Dịch thử để xem dịch offline có chạy trên máy này không.",
                  "Cần gấp: mở video trong Studio và tự điền bản dịch."],
        "actions": [dict(A_RETRY, primary=True), A_AI_SETTINGS]}


def _image_none(c: dict) -> dict:
    return {
        "code": "image_none", "title": "Chưa có cách vẽ ảnh",
        "why": "Vẽ ảnh cần key AI vẽ ảnh (Gemini, OpenAI... đều trả phí) hoặc gói Vẽ ảnh offline miễn phí chạy ngay trên máy.",
        "steps": ["Bấm Tải Vẽ ảnh offline (khoảng 5,3 GB, chỉ tải một lần). Máy có card đồ họa từ 4 GB thì vẽ nhanh.",
                  "Tải xong chọn nguồn ảnh Vẽ trên máy (miễn phí), hoặc để Tự chọn, rồi bấm vẽ lại."],
        "actions": [{"id": "ai_pack", "label": "Tải Vẽ ảnh offline", "pack": "image", "primary": True}, A_AI_SETTINGS]}


def _voices_pack(c: dict) -> dict:
    from .voxtts import ready
    if ready():
        return {
            "code": "voices_engine", "title": "Bộ đọc nhiều thứ tiếng chưa chạy được",
            "why": "Gói giọng đã tải nhưng bộ đọc không bật lên được trên máy này (thường do driver card đồ họa cũ hoặc thiếu RAM).",
            "steps": ["Đóng bớt phần mềm nặng rồi bấm Thử lại.", "Cập nhật driver card đồ họa (NVIDIA, AMD, Intel) rồi khởi động lại máy.",
                      "Cần gấp: chọn bộ đọc Microsoft · online trong tùy chọn Giọng đọc."],
            "actions": [dict(A_RETRY, primary=True), A_AI_SETTINGS]}
    return {
        "code": "voices_pack", "title": "Cần tải Giọng đọc nhiều thứ tiếng",
        "why": "Lồng tiếng nước ngoài trên máy cần gói giọng 30 thứ tiếng (khoảng 2,9 GB, tải một lần).",
        "steps": ["Bấm Tải giọng nhiều thứ tiếng, chờ thanh tiến độ chạy hết.", "Xong bấm Thử lại.",
                  "Chưa muốn tải: chọn bộ đọc Microsoft · online trong tùy chọn Giọng đọc (cần mạng, có khi bị chặn)."],
        "actions": [{"id": "ai_pack", "label": "Tải giọng nhiều thứ tiếng", "pack": "voices", "primary": True}, A_RETRY]}


def _douyin_cookie(c: dict) -> dict:
    if c.get("has_cookie"):
        return {
            "code": "douyin_cookie_old", "title": "Cookie Douyin đã cũ, cần xuất lại",
            "why": "Douyin đổi cookie định kỳ. Cookie đã nạp không còn dùng được, hoặc được xuất khi trang chưa tải xong "
                   "hay còn đang hiện ô xác minh.",
            "steps": ["Bấm Làm mới cookie: Studio566 mở douyin.com trên trình duyệt. Chờ trang hiện video, lướt qua 1–2 video. "
                      "Có ô kéo xác minh thì kéo cho xong; hiện hộp đăng nhập thì bấm dấu X (không cần đăng nhập).",
                      "Bấm biểu tượng tiện ích Get cookies.txt LOCALLY rồi bấm Export: Studio566 tự nhận file và tự thử lại video.",
                      "Vẫn lỗi với cookie mới: bấm Cập nhật bộ tải video (Douyin vừa đổi cách trang chạy), rồi Thử lại."],
            "actions": [{"id": "cookies", "label": "Làm mới cookie", "primary": True, "site": "douyin", "renew": True}, A_YTDLP, A_RETRY]}
    return {
        "code": "douyin_cookie", "title": "Douyin cần cookie của trình duyệt",
        "why": "Douyin chỉ cho tải khi có cookie, là mẩu dữ liệu trình duyệt tự lưu lúc bạn mở douyin.com. "
               "Không cần đăng nhập, làm một lần dùng được nhiều ngày.",
        "steps": ["Bấm Thêm cookie Douyin và làm theo các bước (khoảng 2 phút, chỉ lần đầu phải cài tiện ích).",
                  "Bấm Export trong tiện ích là Studio566 tự nhận file, rồi tự thử lại video."],
        "actions": [{"id": "cookies", "label": "Thêm cookie Douyin", "primary": True, "site": "douyin"}, A_RETRY]}


def diagnose(text: str, src: str = "", stage: str | None = None) -> dict | None:
    """Lời chỉ dẫn cho một lỗi, None nếu không nhận ra (giao diện chỉ hiện lỗi gốc và nút Chép thông tin lỗi)."""
    t = str(text or "")
    if not t.strip():
        return None
    plat = ""
    if src:
        try:
            from .download import extract_url, platform_of
            plat = platform_of(extract_url(src))
        except Exception:
            plat = ""
    if plat in ("", "web"):
        m = re.search(r"(douyin|bilibili|kuaishou|xiaohongshu|weibo|ixigua|toutiao)", t, re.I)
        plat = {"ixigua": "xigua"}.get(m.group(1).lower(), m.group(1).lower()) if m else plat
    ctx = {"plat": plat, "site": PLAT_NAMES.get(plat, "trang video"), "model": model_kind_of(t),
           "has_cookie": plat in SITES and cookie_path(plat).is_file()}
    for pat, make in _rules():
        if re.search(pat, t):
            h = make(ctx)
            h.setdefault("actions", [])
            if not any(a["id"] == "copy_report" for a in h["actions"]):
                h["actions"].append(A_REPORT)
            return h
    return None


def anonymize(text: str) -> str:
    """Bỏ tên người dùng Windows khỏi đường dẫn trước khi khách gửi thông tin lỗi cho người khác."""
    t = re.sub(r"(?i)([a-z]:[\\/]+users[\\/]+)[^\\/\s\"']+", r"\1…", str(text or ""))
    return re.sub(r"(?i)(api[_-]?key|token|sessdata|s_v_web_id|authorization)([\"'=: ]+)[^\s\"'&]+", r"\1\2…", t)


# ============================================================================ cập nhật bộ tải video

def update_ytdlp(timeout: int = 240) -> dict:
    """pip install -U yt-dlp vào đúng môi trường đang chạy, rồi bỏ bản cũ khỏi bộ nhớ để lần tải sau dùng bản mới
    (download.py chỉ import yt_dlp bên trong hàm)."""
    import subprocess
    import sys

    def ver() -> str:
        r = subprocess.run([py, "-c", "import yt_dlp.version as v; print(v.__version__)"], capture_output=True, text=True, timeout=60)
        return r.stdout.strip()

    py = sys.executable
    if py.lower().endswith("pythonw.exe") and Path(py[:-5] + ".exe").exists():
        py = py[:-5] + ".exe"
    old = ver()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([py, "-m", "pip", "install", "-U", "--disable-pip-version-check", "--no-input", "yt-dlp"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=flags)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-3:]
        raise RuntimeError("Không cập nhật được bộ tải video: " + " ".join(tail)[-400:])
    new = ver()
    for name in [m for m in sys.modules if m == "yt_dlp" or m.startswith("yt_dlp.")]:
        sys.modules.pop(name, None)
    log("download", f"yt-dlp {old} → {new}")
    return {"old": old, "new": new, "changed": old != new}
