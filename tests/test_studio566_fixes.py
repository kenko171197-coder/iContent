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


# ---------- 1.0.2: dữ liệu thật của video 丧彪 (2 lần Whisper nghe khác nhau, cùng một bảng phụ đề OCR)
import json as _json
from pathlib import Path as _Path

_DATA = _Path(__file__).parent / "data"


def _sangbieu(name):
    words = [tuple(w) for w in _json.loads((_DATA / f"{name}.json").read_text(encoding="utf-8"))]
    events = _json.loads((_DATA / "sangbieu_ocr.json").read_text(encoding="utf-8"))["events"]
    return align.fuse(words, events, ACFG)


def _find(segs, part):
    return next(s for s in segs if part in s.text)


def test_chu_dau_cau_bi_dat_sai_gio_duoc_doi_ve():
    from icontent.asr import fix_stray_words
    ws = fix_stray_words([(4.83, 5.01, "经,", 0), (5.27, 5.45, "让", 0), (18.41, 18.57, "让", 0), (18.57, 18.75, "我", 0)])
    assert ws[1][:3] == (18.23, 18.41, "让")
    keep = [(1.0, 1.3, "好。", 0), (1.4, 1.7, "走", 2), (9.0, 9.3, "来", 0)]      # hết câu / hết đoạn: không dời
    assert fix_stray_words(keep) == keep
    alone = [(1.0, 1.3, "好", 2), (4.0, 4.3, "嗯", 0), (9.0, 9.3, "来", 0)]       # đứng riêng giữa khoảng lặng: không dời
    assert fix_stray_words(alone) == alone


def test_video_sangbieu_khong_con_cau_chay_truoc_hinh():
    for name in ("sangbieu_words", "sangbieu_words_lan1"):
        segs = _sangbieu(name)
        assert max(s.end - s.start for s in segs) < 4.0, name          # trước đây có câu dài 14-15 giây
        assert all(b.start >= a.end - 0.05 for a, b in zip(segs, segs[1:])), name   # không câu nào chồng câu nào
        assert not [s.text for s in segs if s.text in ("丧彪", "发", "老", "哟")], name   # hết logo và câu cụt 1 chữ
    segs = _sangbieu("sangbieu_words")
    assert 17.9 <= _find(segs, "看不见").start <= 18.5      # trước: 0:05
    assert 107.0 <= _find(segs, "干啥的").start <= 107.5    # trước: 1:32
    assert 132.0 <= _find(segs, "诈骗").start <= 132.7      # trước: 2:06
    assert 167.9 <= _find(segs, "给我起来").start <= 168.4  # trước: 2:39
    assert _find(segs, "老头子").text == "老头子" and _find(segs, "不管了").text.startswith("啥也")
    s = _find(segs, "什么神经")
    assert s.text.startswith("发") and s.start <= 3.1       # nghe ra nửa câu: lấy thêm giờ theo phụ đề


def test_gom_nguoi_noi_theo_so_nhan_vat():
    import numpy as np
    from icontent import speakers
    rng = np.random.default_rng(7)
    base = np.eye(6)[:3]                                    # 3 nhân vật thật
    vecs, truth = [], []
    for k in range(3):
        for mood in (0.0, 0.9):                             # mỗi người có 2 kiểu giọng: nói thường và quát
            for _ in range(6):
                v = base[k] + mood * np.eye(6)[3 + k] + rng.normal(0, 0.05, 6)
                vecs.append(v / np.linalg.norm(v)); truth.append(k)
    vecs, durs = np.stack(vecs), np.full(len(vecs), 1.5)
    lab = speakers._cluster(vecs, durs, count=3)
    assert len(set(lab)) == 3
    assert all(len({lab[i] for i in range(len(truth)) if truth[i] == k}) == 1 for k in range(3))   # một người một nhóm


def test_cau_khong_chac_giu_nguoi_cua_cau_ben_canh():
    import numpy as np
    from icontent import speakers
    cent = {0: np.array([1.0, 0, 0]), 1: np.array([0, 1.0, 0])}
    noise = np.array([0.5, 0.5, 0.70710678])                # không giống hẳn ai (tiếng nhạc)
    units = [{"start": 0, "end": 2, "cl": 0, "vec": cent[0]},
             {"start": 2.1, "end": 2.6, "vec": noise},       # câu ngắn không chắc -> theo câu trước
             {"start": 3.0, "end": 3.5, "vec": np.array([0.05, 0.99, 0.1])},   # giống hẳn người 2 -> người 2
             {"start": 20.0, "end": 21.0, "vec": None},      # không lấy được dấu giọng, sát câu sau -> theo câu sau
             {"start": 21.2, "end": 23, "cl": 1, "vec": cent[1]}]
    speakers._settle(units, cent)
    assert [u["cl"] for u in units] == [0, 0, 1, 1, 1]
    units = [{"start": 0, "end": 2, "cl": 0, "vec": cent[0]}, {"start": 2.1, "end": 3.0, "cl": 1, "vec": noise},
             {"start": 3.2, "end": 5, "cl": 0, "vec": cent[0]}]
    speakers._smooth(units, cent)                           # bà - ? - bà
    assert [u["cl"] for u in units] == [0, 0, 0]
