"""Hồ sơ xuất theo nền tảng. Chỉ khác nhau ở khung hình và cách đưa hình vào khung, nên nhiều nền tảng cùng khung dùng chung
một lần dựng.

Về con số của nền tảng: các nguồn tra cứu cho số khác nhau và nền tảng không công bố số chính thức cho bài đăng thường, nên
ở đây chỉ giữ giới hạn mà đa số nguồn thống nhất, và mọi cảnh báo đều chỉ là gợi ý, không chặn việc xuất. (tra cứu 11/2026)
"""
from __future__ import annotations

PROFILES: dict[str, dict] = {
    "tiktok": {"name": "TikTok", "note": "Dọc 9:16, khung theo nhân vật", "icon": "phone", "edit": {"aspect": "9:16", "fit": "track"}, "max_seconds": None},
    "reels": {"name": "Reels", "note": "Instagram, Facebook. Dọc 9:16", "icon": "phone", "edit": {"aspect": "9:16", "fit": "track"}, "max_seconds": 180,
              "over": "Reels dài hơn 3 phút thường khó được đề xuất tới người chưa theo dõi"},
    "shorts": {"name": "Shorts", "note": "YouTube Shorts. Dọc 9:16", "icon": "phone", "edit": {"aspect": "9:16", "fit": "track"}, "max_seconds": 180,
               "over": "Video dài hơn 3 phút sẽ không được tính là Shorts"},
    "youtube": {"name": "YouTube", "note": "Ngang 16:9, nền mờ nếu video gốc dọc", "icon": "monitor", "edit": {"aspect": "16:9", "fit": "blur"}, "max_seconds": None},
    "feed": {"name": "Bảng tin", "note": "Facebook, Zalo. Vuông 1:1", "icon": "square", "edit": {"aspect": "1:1", "fit": "track"}, "max_seconds": None},
}

# vùng trên khung dọc thường bị nút và chữ của ứng dụng che (tỉ lệ khung hình). Các nguồn lệch nhau khá nhiều nên lấy mức
# an toàn nhất, và giao diện ghi rõ đây là ước lượng
SAFE_ZONE_9X16 = {"top": 0.115, "bottom": 0.25, "left": 0.055, "right": 0.13}


def render_key(edit) -> tuple[str, str]:
    """Hai bản có cùng khóa thì dựng ra giống hệt nhau."""
    aspect = str(edit.get("aspect") or "keep")
    return aspect, (str(edit.get("fit") or "blur") if aspect != "keep" else "")


def public() -> list[dict]:
    return [{"id": k, **{x: v[x] for x in ("name", "note", "icon", "max_seconds")}, "over": v.get("over", ""), "aspect": v["edit"]["aspect"], "fit": v["edit"]["fit"]}
            for k, v in PROFILES.items()]
