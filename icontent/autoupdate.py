"""Tự cập nhật: báo khi có bản Studio566 mới trên GitHub Release, tự cập nhật bộ tải video (yt-dlp) vài ngày một lần.

Bản mới: GitHub Actions ghi mã commit vào icontent/_build_commit.txt lúc đóng gói và vào ghi chú của Release `ban-moi-main`
(dòng "build: <mã>"). Mã khác nhau là có bản mới. Chạy từ mã nguồn (không có file đó) thì không kiểm tra.
Mọi lỗi mạng đều bỏ qua im lặng: không có mạng thì app vẫn chạy bình thường.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .util import ROOT, log

REPO = os.environ.get("STUDIO566_REPO", "kenko171197-coder/iContent")
TAG = "ban-moi-main"
RELEASE_PAGE = f"https://github.com/{REPO}/releases/tag/{TAG}"
YTDLP_EVERY = 3 * 24 * 3600          # 3 ngày
APP_CHECK_EVERY = 6 * 3600
_cache: dict = {}
_lock = threading.Lock()


def build_commit() -> str:
    f = Path(__file__).with_name("_build_commit.txt")
    try:
        return f.read_text(encoding="utf-8").strip()[:40]
    except OSError:
        return ""


def _state_file() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(ROOT)
    d = Path(base) / "Studio566"
    d.mkdir(parents=True, exist_ok=True)
    return d / "update-state.json"


def _load_state() -> dict:
    try:
        return json.loads(_state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(st: dict) -> None:
    try:
        _state_file().write_text(json.dumps(st), encoding="utf-8")
    except OSError:
        pass


def _get_json(url: str, timeout: float = 8.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Studio566-update", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_release(rel: dict) -> dict:
    """Ghi chú Release -> mã commit của bản trên mạng và link tải file cài."""
    body = str(rel.get("body") or "")
    m = re.search(r"build:\s*([0-9a-f]{7,40})", body)
    exe = next((a.get("browser_download_url") for a in rel.get("assets") or []
                if str(a.get("name", "")).lower().endswith(".exe")), "")
    return {"commit": m.group(1) if m else "", "download": exe or RELEASE_PAGE, "page": RELEASE_PAGE}


def is_newer(local: str, remote: str) -> bool:
    if not local or not remote:
        return False
    n = min(len(local), len(remote))
    return local[:n] != remote[:n]


def check_app_update(force: bool = False) -> dict:
    """{"available": bool, "download": url, "page": url}. Kết quả giữ 6 giờ."""
    local = build_commit()
    if not local:
        return {"available": False, "reason": "source"}
    with _lock:
        hit = _cache.get("app")
        if hit and not force and time.time() - hit[0] < APP_CHECK_EVERY:
            return hit[1]
    try:
        info = parse_release(_get_json(f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}"))
        res = {"available": is_newer(local, info["commit"]), "download": info["download"], "page": info["page"]}
    except Exception:      # noqa: BLE001 — không có mạng, GitHub chặn: coi như không có bản mới
        res = {"available": False, "reason": "offline"}
    with _lock:
        _cache["app"] = (time.time(), res)
    return res


def _in_installed_env() -> bool:
    """Chỉ tự cập nhật thư viện trong môi trường .venv của bản cài, không đụng Python của người phát triển."""
    return ".venv" in Path(sys.prefix).parts


def maybe_update_ytdlp(delay: float = 90.0) -> None:
    """Chạy nền sau khi mở app: quá 3 ngày chưa cập nhật yt-dlp thì cập nhật (Douyin, Bilibili hay đổi cách chặn)."""
    if not _in_installed_env() or os.environ.get("STUDIO566_NO_AUTOUPDATE"):
        return

    def run() -> None:
        time.sleep(delay)
        st = _load_state()
        if time.time() - float(st.get("ytdlp_at") or 0) < YTDLP_EVERY:
            return
        try:
            from .fixes import update_ytdlp
            r = update_ytdlp()
            log("download", "Tự cập nhật bộ tải video: " + (f"{r['old']} → {r['new']}" if r.get("changed") else f"đang là bản mới nhất ({r.get('new')})"))
        except Exception as e:      # noqa: BLE001 — không có mạng thì để lần sau
            log("download", f"Tự cập nhật bộ tải video chưa được, để lần sau: {str(e)[:160]}")
            return
        st["ytdlp_at"] = time.time()
        _save_state(st)

    threading.Thread(target=run, name="ytdlp-autoupdate", daemon=True).start()
