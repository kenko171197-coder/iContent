"""Thư viện: dung lượng của mọi thứ đã làm, và dọn file tạm mà không mất gì của người dùng.

Chỉ dọn thứ tạo lại được, theo ba nhóm:
- leftover: bản xuất thêm còn sót trong thư mục làm việc (final_<khung>.mp4). Bản cũ của Studio566 quên xóa chúng sau khi đã chép sang
  thư mục output. Chỉ xóa khi output đang có bản cùng cỡ, không thì đó có thể là bản duy nhất.
- editor: bản nền cho Trình dựng (editor_base.* của video dịch, thư mục editor của câu chuyện). Mở lại trong Trình dựng thì tự dựng lại;
  dự án đã mở trong Trình dựng giữ bản riêng của nó (FreeCut chép video vào kho của nó khi nhập).
- temp: ảnh khung hình xem trước (.frames), giọng nghe thử (_preview), file dựng tạm của câu chuyện (render), file chép dở bị bỏ lại.
Video đang ở trong hàng đợi, câu chuyện đang dựng hay đang đóng gói thì không đụng tới.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

LEFTOVER_PREFIX = "final_"
EDITOR_FILES = ("editor_base.mp4", "editor_base.json", "editor_base.srt", "editor_base.render.json")
TEMP_SUFFIXES = (".copying", ".cu", ".part")
TEMP_MIN_AGE = 3600      # file tạm mới hơn thế này có thể đang được ghi
GROUPS = {
    "leftover": ("Bản xuất còn sót trong thư mục làm việc", "Đã có bản giống hệt trong thư mục output. Không mất gì."),
    "editor": ("Bản nền cho Trình dựng", "Mở video trong Trình dựng sẽ tự dựng lại (khoảng 1 phút). Dự án đã mở trong Trình dựng vẫn giữ nguyên."),
    "temp": ("Ảnh xem trước và file tạm", "Ảnh khung hình, giọng nghe thử, file dựng dở. Tự tạo lại khi cần."),
}


def tree_size(p: Path) -> int:
    """Tổng dung lượng một file hoặc cả thư mục (không theo lối tắt). File đang bị khóa, mất quyền đọc thì bỏ qua."""
    p = Path(p)
    try:
        if p.is_file():
            return p.stat().st_size
    except OSError:
        return 0
    total, stack = 0, [p]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _inside(path: Path, folder: Path) -> bool:
    try:
        return Path(folder).resolve() in Path(path).resolve().parents
    except OSError:
        return False


def job_dirs(work: Path) -> list[Path]:
    if not work.is_dir():
        return []
    return [p for p in work.iterdir() if p.is_dir() and not p.name.startswith((".", "_")) and (p / "meta.json").exists()]


def job_outputs(job: Path, output_dir: Path) -> list[Path]:
    """Các file trong thư mục output thuộc về video này: bản chính, bản xuất thêm, kèm phụ đề, ảnh bìa, chữ đăng bài cùng tên, gói đăng bài.
    Chỉ những gì nằm trong thư mục output: output.json bị sửa tay cũng không làm xóa nhầm chỗ khác."""
    out = _load(job / "output.json")
    files: list[Path] = []
    for x in [out.get("video"), *(out.get("extra") or [])]:
        if not x:
            continue
        v = Path(x)
        if not _inside(v, output_dir):
            continue
        for f in (v, v.with_suffix(".srt"), v.with_suffix(".jpg"), v.with_suffix(".txt")):
            if f.is_file() and f not in files:
                files.append(f)
        pack = v.with_name(f"{v.stem}_goi_dang")
        if pack.is_dir() and pack not in files:
            files.append(pack)
    return files


def story_outputs(story: dict, output_dir: Path) -> list[Path]:
    files: list[Path] = []
    paths = [story.get("output")] + [x.get("path") for x in story.get("edited") or []]
    for x in paths:
        if not x:
            continue
        v = Path(x)
        if not _inside(v, output_dir):
            continue
        for f in (v, v.with_suffix(".srt"), v.with_suffix(".jpg")):
            if f.is_file() and f not in files:
                files.append(f)
    return files


def remove_paths(paths: list[Path]) -> tuple[int, int]:
    """Xóa từng file, thư mục. -> (số byte đã giải phóng, số mục không xóa được vì đang mở)."""
    freed = failed = 0
    for p in paths:
        size = tree_size(p)
        try:
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
            else:
                continue
            freed += size
        except OSError:
            failed += 1
            if p.is_dir():      # xóa được một phần: tính phần đã mất đi
                freed += max(0, size - tree_size(p))
    return freed, failed


def _old_temp(folder: Path, now: float) -> list[Path]:
    out = []
    try:
        for f in folder.iterdir():
            if f.is_file() and f.name.endswith(TEMP_SUFFIXES):
                try:
                    if now - f.stat().st_mtime > TEMP_MIN_AGE:
                        out.append(f)
                except OSError:
                    pass
    except OSError:
        pass
    return out


def cleanup_plan(work: Path, output_dir: Path, busy_jobs: set[str], busy_stories: set[str]) -> dict[str, list[Path]]:
    """Nhóm -> các file, thư mục sẽ xóa. Chỉ đọc, chưa xóa gì."""
    now = time.time()
    plan: dict[str, list[Path]] = {k: [] for k in GROUPS}
    for job in job_dirs(work):
        if job.name in busy_jobs:
            continue
        main = Path(_load(job / "output.json").get("video") or "")
        for f in job.glob(f"{LEFTOVER_PREFIX}*.mp4"):
            twin = main.with_name(f"{main.stem}_{f.stem[len(LEFTOVER_PREFIX):]}.mp4") if main.name else None
            try:
                if twin and twin.is_file() and twin.stat().st_size == f.stat().st_size:
                    plan["leftover"].append(f)
            except OSError:
                pass
        plan["editor"] += [job / n for n in EDITOR_FILES if (job / n).is_file()]
        if (job / ".frames").is_dir():
            plan["temp"].append(job / ".frames")
        plan["temp"] += _old_temp(job, now)
    stories = work / ".stories"
    if stories.is_dir():
        for d in stories.iterdir():
            if not d.is_dir() or d.name in busy_stories:
                continue
            if (d / "editor").is_dir():
                plan["editor"].append(d / "editor")
            if (d / "render").is_dir():
                plan["temp"].append(d / "render")
            plan["temp"] += _old_temp(d, now)
    for d in (work / "_preview", Path(output_dir) / ".frames"):
        if d.is_dir():
            plan["temp"].append(d)
    if Path(output_dir).is_dir():
        plan["temp"] += _old_temp(Path(output_dir), now)
    return plan


def plan_summary(plan: dict[str, list[Path]]) -> list[dict]:
    out = []
    for k, (label, detail) in GROUPS.items():
        paths = plan.get(k) or []
        out.append({"id": k, "label": label, "detail": detail, "bytes": sum(tree_size(p) for p in paths), "count": len(paths)})
    return out


def storage(work: Path, output_dir: Path, models_dir: Path | None) -> list[dict]:
    """Ổ đĩa đang dùng cho những gì. Mô hình AI nằm ở thư mục chung của Hugging Face nên tính riêng."""
    jobs = sum(tree_size(p) for p in job_dirs(work))
    parts = [
        {"id": "jobs", "label": "Video dịch (thư mục làm việc)", "bytes": jobs},
        {"id": "stories", "label": "Kể chuyện", "bytes": tree_size(work / ".stories") if (work / ".stories").is_dir() else 0},
        {"id": "flows", "label": "Quy trình", "bytes": tree_size(work / ".workflows") if (work / ".workflows").is_dir() else 0},
        {"id": "output", "label": "Video đã xuất (thư mục output)", "bytes": tree_size(output_dir) if Path(output_dir).is_dir() else 0},
    ]
    if work.is_dir():
        known = jobs + parts[1]["bytes"] + parts[2]["bytes"]
        rest = tree_size(work) - known
        if _inside(output_dir, work):      # output nằm trong thư mục làm việc: không tính hai lần
            rest -= parts[3]["bytes"]
        parts.append({"id": "other", "label": "Bộ nhớ đệm khác", "bytes": max(0, rest)})
    if models_dir and Path(models_dir).is_dir():
        parts.append({"id": "models", "label": "Mô hình AI (dùng chung)", "bytes": tree_size(models_dir)})
    return parts
