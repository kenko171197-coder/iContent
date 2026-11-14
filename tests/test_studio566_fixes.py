"""Kiểm thử các bản sửa của Studio566 (chạy: python -m pytest tests). Không cần mạng, không cần mô hình AI."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from icontent import align, asr, license  # noqa: E402
from icontent.tts import speakable  # noqa: E402
from icontent.util import write_wav  # noqa: E402

ACFG = SimpleNamespace(max_chars=22, max_duration=6.0, pause_split=0.6, language="zh")


def test_khong_khoa_ban_quyen(monkeypatch):
    monkeypatch.setenv("ICONTENT_LICENSE_ENFORCE", "1")
    license.reset_cache()
    assert license.enforced() is False
    assert license.locked() is False


def test_lam_sach_cau_truoc_khi_doc():
    assert speakable("Con…") == "Con."
    assert speakable("Hả?!?!") == "Hả?"
    assert speakable("Anh ấy... đi rồi") == "Anh ấy, đi rồi."
    assert speakable("Lên đây đi.") == "Lên đây đi."
    assert speakable("…") == "…"          # không còn chữ: giữ nguyên


def test_lay_sub_goc_khi_whisper_bo_trong():
    words = [(0.2, 0.5, "上来", 1), (0.5, 0.9, "吧", 2)]
    events = [
        {"start": 0.1, "end": 1.0, "text": "上来吧"},
        {"start": 5.0, "end": 7.5, "text": "奶奶不会放过你的"},   # nhạc to, Whisper không nghe ra
        {"start": 8.0, "end": 8.2, "text": "啊啊"},              # quá ngắn: bỏ
    ]
    segs = align.fuse(words, events, ACFG)
    texts = [s.text for s in segs]
    assert "奶奶不会放过你的" in texts
    assert "啊啊" not in texts
    assert [s.id for s in segs] == list(range(1, len(segs) + 1))


def test_tim_khoang_trong_co_tieng(tmp_path):
    sr = 16000
    t = np.arange(int(sr * 20)) / sr
    audio = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)   # nhạc suốt 20 giây
    audio[int(sr * 12):int(sr * 15)] = 0.0                             # 12-15s im lặng thật
    wav = tmp_path / "orig.wav"
    write_wav(wav, audio, sr)
    words = [(0.5, 1.0, "a", 2), (4.0, 4.5, "b", 2), (16.0, 16.5, "c", 2)]
    gaps = asr.find_gaps(words, 20.0, wav)
    starts = [round(a) for a, _ in gaps]
    assert 1 in starts            # 1s-4s: có nhạc, không có lời -> nghe lại
    assert 16 in starts or 17 in starts   # đoạn cuối có nhạc
    assert all(not (12.2 < (a + b) / 2 < 14.8 and b - a < 4) for a, b in gaps)   # khoảng im lặng không bị nghe lại riêng


def test_nhan_ra_ban_moi():
    from icontent import autoupdate
    rel = {"body": "File cài mới nhất.\nbuild: 0123456789abcdef0123456789abcdef01234567",
           "assets": [{"name": "Studio566-Setup-0.7.0.exe", "browser_download_url": "https://github.com/x/y/releases/download/t/S.exe"}]}
    info = autoupdate.parse_release(rel)
    assert info["commit"].startswith("0123456")
    assert info["download"].endswith(".exe")
    assert autoupdate.is_newer("0123456", "fedcba9") is True
    assert autoupdate.is_newer("0123456789", "0123456") is False
    assert autoupdate.is_newer("", "abc1234") is False
