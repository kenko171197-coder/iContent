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


def test_logo_khong_thanh_cau_thoai():
    """Video 丧彪: logo kênh bị OCR đọc thành chữ 丧彪 đứng riêng nhiều lần -> không được thành câu thoại."""
    words = [(0.0, 0.3, "丧", 0), (0.3, 0.7, "彪,", 0), (0.9, 1.6, "别闹。", 2),      # chủ nhân gọi tên con chó thật
             (179.0, 179.4, "气死我了", 2), (190.1, 191.9, "我们不能辜负二舅的努力", 2)]
    events = [
        {"start": 0.25, "end": 1.75, "text": "丧彪別闹"},
        {"start": 21.25, "end": 22.75, "text": "丧彪"},
        {"start": 61.25, "end": 62.0, "text": "丧彪"},
        {"start": 64.5, "end": 66.25, "text": "丧彪你不是狗吗"},       # nhạc to, câu thật có chữ khác đi kèm
        {"start": 104.75, "end": 106.25, "text": "丧彪"},
        {"start": 178.0, "end": 179.75, "text": "哎呦气死我了"},
        {"start": 183.0, "end": 184.5, "text": "丧彪"},
        {"start": 185.0, "end": 186.5, "text": "二舅还在跑呢"},
        {"start": 186.5, "end": 187.0, "text": "丧彪"},
        {"start": 189.25, "end": 192.0, "text": "我们不能辜负二舅的努力"},
    ]
    segs = align.fuse(words, events, ACFG)
    texts = [s.text for s in segs]
    assert "丧彪" not in texts                       # logo bị bỏ
    assert "丧彪你不是狗吗" in texts                  # câu thật có tên con chó vẫn giữ
    s = next(s for s in segs if s.text == "二舅还在跑呢")
    assert (s.start, s.end, s.check) == (185.0, 186.5, "ocr")   # đúng giờ phụ đề, được đánh dấu để soát
    assert all(not x.check for x in segs if x.text != "二舅还在跑呢" and x.text != "丧彪你不是狗吗")


def test_cau_chi_nghe_ra_tieng_duoc_danh_dau():
    words = [(0.2, 0.9, "上来吧", 2), (10.0, 10.6, "什么", 2)]       # 10s: màn hình không có phụ đề
    events = [{"start": 0.1, "end": 1.0, "text": "上来吧"}]
    segs = align.fuse(words, events, ACFG)
    assert [(s.text, s.check) for s in segs] == [("上来吧", ""), ("什么", "nghe")]
