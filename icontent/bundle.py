"""Gói đăng bài: gom mọi thứ cần để đăng một video vào một thư mục gọn gàng, gửi cho ai cũng hiểu.

  <tên video>_goi_dang/
    video.mp4            bản chính
    video_tiktok.mp4     các bản theo nền tảng, clip đã xuất
    anh_bia.jpg
    phu_de.srt
    thong_tin.txt        tiêu đề, mô tả, hashtag, số liệu kiểm định

Video dùng hard link khi được nên không tốn thêm dung lượng đĩa; pipeline luôn thay file bằng file mới (util.copy_replace)
nên gói đã tạo không bị đổi nội dung theo. Phụ đề và ảnh bìa được ghi đè tại chỗ nên phải chép thật.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        return {}


def _place(src: Path, dst: Path) -> None:
    dst.unlink(missing_ok=True)
    if src.suffix.lower() == ".mp4":
        try:
            os.link(src, dst)
            return
        except OSError:      # khác ổ đĩa, hoặc ổ không hỗ trợ
            pass
    shutil.copy2(src, dst)


def _info_text(meta: dict, context: dict, qc: dict) -> str:
    pub = context.get("publish") or {}
    tags = " ".join(h if str(h).startswith("#") else f"#{h}" for h in pub.get("hashtags") or [])
    parts = []
    if pub.get("title"):
        parts.append(f"TIÊU ĐỀ\n{pub['title']}")
    else:
        parts.append(f"TIÊU ĐỀ GỐC\n{meta.get('title') or ''}\n(Chưa có tiêu đề tiếng Việt. Kết nối AI trong Cài đặt rồi dịch lại để có gợi ý.)")
    if pub.get("caption"):
        parts.append(f"MÔ TẢ\n{pub['caption']}")
    if tags:
        parts.append(f"HASHTAG\n{tags}")
    facts = [f"Độ dài: {float(meta.get('duration') or 0):.0f} giây (video gốc)"]
    if qc.get("score") is not None:
        facts.append(f"Điểm kiểm định: {qc['score']}/100")
        stats = qc.get("stats") or {}
        if stats.get("lufs") is not None:
            facts.append(f"Độ to: {stats['lufs']:.1f} LUFS, đỉnh {stats.get('peak') or 0:.1f} dB".replace(".", ","))
        need = [c["title"] for c in qc.get("checks") or [] if c.get("level") in ("bad", "warn")]
        if need:
            facts.append("Nên xem lại: " + "; ".join(need))
    if meta.get("url"):
        facts.append(f"Nguồn: {meta['url']}")
    parts.append("THÔNG TIN\n" + "\n".join(facts))
    return "\n\n".join(parts) + "\n"


def make(job: Path) -> dict:
    """-> {folder, files}. Gọi lại thì cập nhật đúng các file đã có trong gói."""
    output = _load(job / "output.json")
    video = Path(output["video"]) if output.get("video") else None
    if not video or not video.exists():
        raise FileNotFoundError("Chưa có video đã xuất. Hãy bấm Cập nhật video trước.")
    folder = video.parent / f"{video.stem}_goi_dang"
    folder.mkdir(parents=True, exist_ok=True)
    # gói mới thay hẳn gói cũ: không để sót bản của lần trước. Chỉ đụng tới file do chính nó tạo ra. Đổi tên trước, có file đang được mở thì trả
    # lại nguyên trạng rồi báo, không để gói cũ bị xóa dở
    moved: list[tuple[Path, Path]] = []
    try:
        for old in list(folder.glob("video*.*")) + [folder / x for x in ("anh_bia.jpg", "phu_de.srt", "thong_tin.txt")]:
            if old.exists():
                tmp = old.with_name(old.name + ".cu")
                os.replace(old, tmp)
                moved.append((tmp, old))
    except OSError:
        for tmp, old in moved:
            os.replace(tmp, old)
        raise
    files: list[str] = []

    def add(src: Path, name: str) -> None:
        _place(src, folder / name)
        files.append(name)

    add(video, "video.mp4")
    for x in output.get("extra") or []:
        p = Path(x)
        if p.exists():
            tail = p.stem[len(video.stem):].lstrip("_") if p.stem.startswith(video.stem) else p.stem
            add(p, f"video_{tail}{p.suffix}")
    from .editor import latest_edited
    edited = latest_edited(job)
    if edited:      # bản mới nhất gửi về từ trình dựng
        add(edited, f"video_da_dung{edited.suffix}")
    if (job / "cover.jpg").exists():
        add(job / "cover.jpg", "anh_bia.jpg")
    if (job / "final.srt").exists():
        add(job / "final.srt", "phu_de.srt")
    from .qc import cached
    qc = cached(job) or {}
    text = _info_text(_load(job / "meta.json"), _load(job / "context.json"), qc if qc.get("fresh") else {})      # số của bản dựng cũ thì không ghi
    (folder / "thong_tin.txt").write_text(text, encoding="utf-8")
    files.append("thong_tin.txt")
    for tmp, _ in moved:
        tmp.unlink(missing_ok=True)
    return {"folder": str(folder.resolve()), "files": files}
