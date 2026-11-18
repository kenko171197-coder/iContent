"""Cấu hình: giá trị mặc định + ghi đè bằng config.yaml + ghi đè bằng tham số CLI."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "work_dir": "workspace",
    "output_dir": "output",
    "ffmpeg": "",
    "download": {
        "cookies_file": "",           # cookies.txt (Netscape) xuất từ trình duyệt — Douyin bắt buộc
        "cookies_from_browser": "",   # firefox | chrome | edge | ... (yt-dlp tự đọc cookie)
        "proxy": "",
        "max_height": 1080,
        # Lệnh ngoài cho nền tảng yt-dlp không hỗ trợ / bị hỏng. {url} {dir} {cookies} được thay thế.
        # Ví dụ: kuaishou: 'lux -o "{dir}" -O source "{url}"'
        "external": {},
    },
    "asr": {
        "model": "large-v3-turbo",    # large-v3-turbo (1,6 GB, nhanh) | large-v3 (3 GB, kỹ hơn chút) | medium | small
        "device": "auto",             # auto | cuda | cpu
        "compute_type": "auto",       # auto | float16 | int8_float16 | int8
        "language": "zh",
        "beam_size": 5,
        "initial_prompt": "以下是普通话的句子，使用简体中文和标点符号。",
        "max_chars": 22,              # ký tự Trung tối đa / câu phụ đề
        "max_duration": 6.0,          # giây tối đa / câu
        "pause_split": 0.45,          # ngắt câu khi im lặng >= x giây
        "ocr_align": True,            # video có sub Trung in sẵn: ngắt câu theo sub gốc + dùng chữ OCR khi dịch
        "gap_retry": True,            # đoạn dài chưa nghe ra lời (nhạc nền to) thì nghe lại trên tiếng gốc
    },
    "translate": {
        "provider": "claude",         # claude | openai | offline (Hy-MT trên máy qua Ollama) | google | none
        "model": "claude-opus-5-5",   # với provider openai: deepseek-chat, gemini-auto (tự chọn Flash), qwen2.5...
        "effort": "medium",           # claude: low | medium | high
        "base_url": "",               # provider openai: https://api.deepseek.com , http://localhost:11434/v1 ...
        "api_key_env": "",            # tên biến môi trường chứa API key (để trống = mặc định của SDK)
        "offline_model": "",          # model Ollama cho provider offline (trống = Hy-MT2 1.8B)
        "target_lang": "vi",
        "batch_size": 40,
        "style": "Tự nhiên, khẩu ngữ, hợp với video ngắn trên mạng xã hội.",
        "glossary": {},               # {"小米": "Xiaomi", ...}
        "shorten_retry": True,        # câu nào đọc không kịp -> nhờ LLM rút gọn rồi đọc lại
        "analyze": True,              # đọc cả video trước khi dịch: tóm tắt, xưng hô, tên riêng, tiêu đề/hashtag
        "mcp_wait": 300,              # giây chờ AI nhận việc, tính từ lúc người dùng bấm Bắt đầu
        "mcp_confirm": True,          # trước khi dùng AI qua MCP: hiện thông báo, chờ người dùng bấm Bắt đầu
        "review": True,               # dịch xong, AI đọc lại cả bản dịch một lượt: sửa xưng hô lệch, câu vô nghĩa
        "characters": "",             # nhân vật có lời do người dùng nhập, VD "Bà (nữ), Mễ Lạp (bé gái), Tang Bưu (chó, giọng nam)"
        "mcp_server": "",             # địa chỉ cổng MCP trung tâm (trống = địa chỉ gắn sẵn trong bản cài)              # provider mcp: chờ AI nhận việc chừng này giây rồi tự chuyển sang cách dịch dự phòng
    },
    "tts": {
        "enabled": True,
        "engine": "vieneu",            # vieneu (tiếng Việt, trên máy) | vox (nhiều thứ tiếng, trên máy, Mô-đun AI) | edge (online, hay bị giới hạn)
                                       # thứ tiếng khác tiếng Việt mà để vieneu: tự dùng vox nếu đã tải, không thì edge (voice.engine_for)
        # auto     : nhận diện người nói -> mỗi người một giọng (một người thì một giọng theo cao độ)
        # per_line : mỗi câu tự chọn nam/nữ (video nhiều người nói)
        # fixed    : một giọng cố định (vieneu_voice / voice)
        # clone    : VieNeu bắt chước âm sắc người nói gốc (thử nghiệm)
        "voice_mode": "auto",
        "diarize": True,                # chế độ auto: nghe ra mấy người nói, mỗi người một giọng, tách câu gộp 2 người
        "speakers": 0,                  # số nhân vật có lời trong video (người dùng nhập). 0 = app tự đoán
        "male_voice": "",               # trống = Thiện Minh (vieneu) / vi-VN-NamMinhNeural (edge)
        "female_voice": "",             # trống = Trúc Ly (vieneu) / vi-VN-HoaiMyNeural (edge)
        "pitch_split": 175.0,           # Hz: dưới ngưỡng = giọng nam. Đo 14 giọng: nam cao nhất 165, nữ thấp nhất 186
        "voice": "vi-VN-HoaiMyNeural",  # giọng edge khi voice_mode=fixed
        "vieneu_voice": "",             # giọng VieNeu khi voice_mode=fixed: "Thiện Minh", "Trúc Ly"...
        "vox_voice": "",                # giọng nhiều thứ tiếng khi voice_mode=fixed: en_f1, id_m2... (trống = giọng đầu tiên)
        "ref_audio": "",                # VieNeu: file mẫu 3-8s để clone giọng (ưu tiên hơn mọi chế độ khác)
        "fallback_voice": "",           # giọng dự phòng khi máy chủ Edge từ chối 1 câu (để trống = báo lỗi)
        "rate": "+0%",
        "syllables_per_sec": 5.0,      # tốc độ đọc ước lượng ở rate +0% (dùng để giới hạn độ dài bản dịch)
        "max_speed": 1.35,             # tăng tốc tối đa cho 1 câu trước khi cho phép tràn sang khoảng lặng
        "hard_max_speed": 1.6,
        "concurrency": 2,              # Edge giới hạn tần suất: để thấp
        "pronounce": {},               # sửa cách đọc, không đổi phụ đề: {"TikTok": "Tíc Tốc", "kg": "ki lô gam"}
        "rec_clean": True,             # giọng tự thu: lọc ù, giảm ồn, nén nhẹ, chuẩn hóa âm lượng
    },
    "audio": {
        "separate": "auto",            # auto | on | off   (tách giọng gốc, giữ nhạc nền — separate.py, ONNX; auto: video tới 10 phút)
        "separator_model": "UVR-MDX-NET-Inst_HQ_3.onnx",
        "bgm_volume": 1.0,             # âm lượng nhạc nền khi đã tách giọng
        "original_volume": 0.15,       # âm lượng tiếng gốc khi KHÔNG tách được (lồng đè)
        "dub_volume": 1.0,
        "duck": True,                  # tự hạ tiếng nền khi giọng lồng đang nói (sidechain)
        "music": "",                   # thêm nhạc nền riêng (mp3/wav), tự lặp cho đủ dài
        "music_volume": 0.12,
        "music_skip_intro": True,      # bỏ đoạn mở đầu rất nhỏ của nhạc nền, vào thẳng chỗ nhạc có tiếng
        "loudnorm": True,
    },
    "edit": {
        "burn_subs": True,
        "sub_style": "classic",        # classic | box | tiktok (nhấn từng chữ) | karaoke | pop (chữ hoa, phóng to)
        "uppercase": False,            # viết hoa toàn bộ phụ đề
        "sub_y": None,                 # tâm dòng phụ đề theo chiều dọc (0..1). Trống = tự đặt
        "highlight_color": "&H0000E5FF",  # màu nhấn chữ (ASS &HAABBGGRR) — vàng
        "tiktok_chunk": 7,             # tiktok: số âm tiết tối đa mỗi lần hiện
        "font": "Arial",
        "fontsdir": "",                # thư mục font riêng (tương đối với thư mục dự án)
        "font_size_ratio": 0.050,      # cỡ chữ = tỉ lệ * chiều cao khung hình (theo cạnh ngắn với video dọc)
        "margin_ratio": 0.07,
        "primary_color": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 3,
        "bold": True,
        "blur_hardsub": "auto",        # auto (OCR tự dò) | true (dùng hardsub_box) | false — che sub Trung in sẵn
        "hardsub_mode": "inpaint",     # inpaint (xóa hẳn chữ, sạch nhất) | blur (làm mờ) | band (dải nền tối)
        "hardsub_box": [0.05, 0.78, 0.90, 0.15],  # x, y, w, h (tỉ lệ khung hình gốc)
        "subs_over_hardsub": True,     # đặt phụ đề mới vào đúng vùng sub gốc đã che
        "flip": False,                 # lật ngang
        "zoom": 1.0,                   # 1.05 = phóng to 5% rồi cắt viền
        "speed": 1.0,                  # 1.1 = nhanh 10% (cả hình lẫn tiếng)
        "brightness": 0.0,             # -0.1..0.1
        "contrast": 1.0,
        "saturation": 1.0,             # 1.1 = màu tươi hơn
        "watermark_text": "",          # chữ mờ góc trên, vd "@kenhcuaban"
        "aspect": "keep",              # keep | 9:16 | 16:9 | 1:1
        "fit": "blur",                 # khi đổi khung: blur (nền mờ) | track (khung đi theo nhân vật) | crop (cắt cố định) | black (viền đen)
        "reframe_pins": [],            # fit=track: [[giây trong cảnh, tâm khung], ...] người dùng đặt tay cho từng cảnh
        "focus_x": 0.5,                # fit=crop: giữ phần nào theo chiều ngang (0 trái .. 1 phải)
        "focus_y": 0.5,
        "cuts": [],                    # các đoạn bỏ đi [[giây đầu, giây cuối], ...] theo thời gian video gốc
        "overlays": [],                # lớp chữ / ảnh trên video, xem editing.overlays_valid
        "look": "",                    # bộ màu, xem editing.LOOKS
        "lut": "",                     # file bộ màu .cube (LUT 3D), áp dụng sau bộ màu
        "fade_in": 0.0,                # giây mờ dần vào đầu video
        "fade_out": 0.0,               # giây mờ dần ra cuối video
        "intro": "",                   # video hoặc ảnh ghép vào đầu
        "outro": "",                   # video hoặc ảnh ghép vào cuối
        "card_seconds": 3.0,           # thời lượng khi intro/outro là ảnh
        "logo": "",                    # đường dẫn PNG
        "logo_pos": "top-right",       # top-left | top-right | bottom-left | bottom-right
        "logo_scale": 0.15,            # bề rộng logo = tỉ lệ * bề rộng video
        "encoder": "auto",             # auto (có GPU NVIDIA thì dùng) | h264_nvenc | libx264
        "crf": 23,                     # thấp hơn = nét hơn, file to hơn
        "max_bitrate": "8M",           # trần bitrate video ("" = không giới hạn)
        "preset": "medium",
        "auto_qc": True,               # dựng xong tự kiểm định thành phẩm
    },
}


ATOMIC = ("glossary", "external", "pronounce", "speaker_voices")     # dict được thay nguyên khối khi ghi đè


class Cfg(dict):
    """dict cho phép truy cập kiểu thuộc tính: cfg.asr.model"""

    def __getattr__(self, k: str) -> Any:
        try:
            v = self[k]
        except KeyError as e:
            raise AttributeError(k) from e
        return Cfg(v) if isinstance(v, dict) and not isinstance(v, Cfg) else v

    def __setattr__(self, k: str, v: Any) -> None:
        self[k] = v


def _merge(base: dict, over: dict) -> dict:
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict) and k not in ATOMIC:
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def _wrap(d: dict) -> Cfg:
    return Cfg({k: _wrap(v) if isinstance(v, dict) else v for k, v in d.items()})


def merge_dicts(base: dict, over: dict) -> dict:
    """Bản sao sâu của base đã ghi đè bởi over (các khối trong ATOMIC được thay nguyên)."""
    return _merge(copy.deepcopy(dict(base)), copy.deepcopy(dict(over or {})))


def with_overrides(cfg: dict, overrides: dict | None) -> Cfg:
    return _wrap(merge_dicts(cfg, overrides or {}))


def diff_dicts(full: dict, base: dict) -> dict:
    """Các khóa trong full khác với base (để lưu config gọn)."""
    out: dict = {}
    for k, v in full.items():
        b = base.get(k) if isinstance(base, dict) else None
        if isinstance(v, dict) and isinstance(b, dict) and k not in ATOMIC:
            d = diff_dicts(v, b)
            if d:
                out[k] = d
        elif v != b:
            out[k] = v
    return out


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> Cfg:
    data = copy.deepcopy(DEFAULTS)
    if path:
        p = Path(path)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                _merge(data, yaml.safe_load(f) or {})
        else:
            raise FileNotFoundError(f"Không thấy file config: {p}")
    if overrides:
        _merge(data, overrides)
    return _wrap(data)
