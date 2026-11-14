"""Máy tự nhìn video, chạy hẳn trên máy: không cần mạng, không cần GPU.

  detect_scenes   các điểm chuyển cảnh
  scan_faces      khuôn mặt theo thời gian (model YuNet 232 KB, giấy phép MIT, nằm trong icontent/data)
  reframe_plan    đường đi của khung cắt khi đổi tỉ lệ khung hình (ví dụ video ngang sang 9:16)

Khung cắt đi theo kiểu người quay phim: đứng yên khi nhân vật còn ở vùng giữa, chỉ lia khi nhân vật rời hẳn vùng đó, lia
nhanh có gia tốc rồi lại đứng yên. Không bám theo từng khung, vì crop chỉ dịch được theo số nguyên điểm ảnh nên trôi chậm
sẽ thấy hình giật từng nấc, và mỗi lần người trong hình nhúc nhích là cả khung rung theo.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from .util import check_cancel, find_ffmpeg, log, progress, replace_file, run_lines

MODEL = Path(__file__).parent / "data" / "face_detection_yunet_2023mar.onnx"
SCAN_FPS = 4.0
SCAN_SIDE = 480          # cạnh dài khi dò mặt. YuNet bắt tốt mặt từ khoảng 10 đến 300 điểm ảnh
MIN_FACE = 0.02          # mặt nhỏ hơn tỉ lệ này của chiều rộng thường là nhận nhầm
SCENE_THRESHOLD = 0.3
MIN_SHOT = 0.4           # giây. Chớp sáng tạo ra nhiều điểm cắt sát nhau, chỉ giữ điểm đầu tiên
DEAD_ZONE = 0.18         # nhân vật lệch quá tỉ lệ này của khung cắt thì mới lia. Đo trên video thật: 0,14 làm lia theo cả cái lắc đầu
MIN_HOLD = 2.5           # giây đứng yên tối thiểu giữa hai lần lia, tránh đảo qua đảo lại khi hai người thay nhau nói
PERSIST = 6              # số mẫu liên tiếp (1,5 giây) nhân vật phải ở ngoài vùng giữa thì mới lia
GLIDE_SPEED = 1.1        # lia bao nhiêu lần bề rộng khung cắt trong một giây
GLIDE_MIN, GLIDE_MAX = 0.45, 1.4


def available() -> bool:
    try:
        import cv2
    except ImportError:
        return False
    return MODEL.exists() and hasattr(cv2, "FaceDetectorYN")


def _key(src: Path) -> str:
    s = src.stat()
    return f"{s.st_size}:{int(s.st_mtime)}"


def _save(path: Path, data: dict) -> None:
    tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    replace_file(tmp, path)


@contextmanager
def _hold(job: Path):
    """Chờ khóa nhưng vẫn hủy được: máy chủ có thể đang dò cho trang Studio, người dùng bấm Hủy thì không được kẹt lại."""
    lock = _job_lock(job)
    while not lock.acquire(timeout=0.5):
        check_cancel()
    try:
        yield
    finally:
        lock.release()


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _job_lock(job: Path) -> threading.Lock:
    """Hai yêu cầu cùng lúc cho một video thì người sau đợi kết quả của người trước, không giải mã lại từ đầu."""
    with _locks_guard:
        return _locks.setdefault(str(job), threading.Lock())


def _load(path: Path, key: str):
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return d if d.get("key") == key else None


# --------------------------------------------------------------------------- chuyển cảnh

_PTS = re.compile(r"pts_time:([0-9.]+)")


def detect_scenes(src: Path, threshold: float = SCENE_THRESHOLD) -> list[float]:
    """Các mốc (giây) mà hình đổi hẳn. Dùng chỉ số scene của ffmpeg trên bản thu nhỏ nên rất nhanh."""
    exe, _ = find_ffmpeg()
    cmd = [exe, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(src), "-an", "-sn",
           "-vf", f"scale=320:-2,select='gt(scene,{threshold})',metadata=print:file=-", "-f", "null", "-"]
    out: list[float] = []
    for line in run_lines(cmd):
        m = _PTS.search(line)
        if m:
            t = float(m.group(1))
            if not out or t - out[-1] >= MIN_SHOT:
                out.append(round(t, 3))
    return out


def scenes(job: Path, force: bool = False) -> list[float]:
    """Điểm chuyển cảnh của video gốc, tính một lần rồi lưu lại."""
    src = job / "source.mp4"
    cache = job / "scenes.json"
    key = _key(src)
    with _hold(job):
        d = None if force else _load(cache, key)
        if d is None:
            d = {"key": key, "times": detect_scenes(src)}
            _save(cache, d)
    return d["times"]


# --------------------------------------------------------------------------- khuôn mặt

def _detector(w: int, h: int):
    import cv2

    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)      # thông báo kỹ thuật không có ích gì với người dùng
    except AttributeError:
        pass
    # nạp từ bộ nhớ: OpenCV không đọc được file model khi thư mục cài có dấu tiếng Việt (đo được thật)
    data = np.frombuffer(MODEL.read_bytes(), np.uint8)
    return cv2.FaceDetectorYN.create("onnx", data, np.array([], np.uint8), (w, h), 0.6, 0.3, 30)


def faces_in(det, img, w: int, h: int) -> list[list[float]]:
    """-> [[tâm x, tâm y, rộng, cao, điểm tin cậy], ...] theo tỉ lệ khung hình."""
    _, found = det.detect(img)
    if found is None:
        return []
    out = []
    for f in found:
        fw, fh = float(f[2]) / w, float(f[3]) / h
        if fw < MIN_FACE:
            continue
        out.append([round((float(f[0]) + float(f[2]) / 2) / w, 4), round((float(f[1]) + float(f[3]) / 2) / h, 4),
                    round(fw, 4), round(fh, 4), round(float(f[14]), 3)])
    return out


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def scan_faces(job: Path, meta: dict, force: bool = False) -> dict:
    """Lấy mẫu 4 khung/giây: ghi vị trí mặt, và tâm chuyển động để có chỗ dựa ở những cảnh không có người."""
    with _hold(job):
        return _scan_faces(job, meta, force)


def _scan_faces(job: Path, meta: dict, force: bool) -> dict:
    import cv2

    src = job / "source.mp4"
    cache = job / "faces.json"
    key = _key(src)
    d = None if force else _load(cache, key)
    if d is not None:
        return d
    W, H = int(meta["width"]), int(meta["height"])
    k = min(1.0, SCAN_SIDE / max(W, H))
    w, h = _even(W * k), _even(H * k)
    det = _detector(w, h)
    exe, _ = find_ffmpeg()
    log("reframe", "Đang dò khuôn mặt để khung hình đi theo nhân vật ...")
    proc = subprocess.Popen([exe, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(src), "-an", "-sn",
                             "-vf", f"fps={SCAN_FPS},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = w * h * 3
    total = max(1.0, float(meta.get("duration") or 0) * SCAN_FPS)
    faces, motion = [], []
    prev = None
    n = 0
    mw, mh = 64, max(8, int(64 * h / w))
    # bỏ dải dưới cùng: phụ đề in sẵn đổi liên tục, sẽ bị hiểu nhầm là chỗ có chuyển động
    motion_rows = int(mh * 0.72)
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            img = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            found = faces_in(det, img, w, h)
            if found:
                faces.append([n, found])
            small = cv2.cvtColor(cv2.resize(img, (mw, mh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
            if prev is not None:
                mask = cv2.absdiff(small, prev)[:motion_rows] > 22
                e = float(mask.mean())
                if 0.01 < e < 0.6:      # lớn hơn nữa là chuyển cảnh, không phải chuyển động
                    ys, xs = np.nonzero(mask)
                    motion.append([n, round(float(xs.mean()) / mw, 4), round(float(ys.mean()) / mh, 4), round(e, 3)])
            prev = small
            n += 1
            if n % 16 == 0:
                check_cancel()
                progress("reframe", min(0.99, n / total))
        rc = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    # không lưu kết quả dở dang: nếu lưu thì các lần sau sẽ tin là phần còn lại của video không có ai
    if rc != 0 or n == 0:
        raise RuntimeError(f"Không đọc được video để dò khuôn mặt (ffmpeg trả về {rc}, đọc được {n} khung)")
    d = {"key": key, "fps": SCAN_FPS, "n": n, "faces": faces, "motion": motion}
    _save(cache, d)
    return d


# --------------------------------------------------------------------------- đường đi của khung cắt

def _frame_target(faces: list[list[float]], prev: float | None, axis: str, span: float) -> float | None:
    """Tâm khung cắt mong muốn ở một khung hình. Ưu tiên mặt lớn, rõ, và gần chỗ đang nhìn. Nếu người thứ hai đủ quan
    trọng và cả hai cùng lọt khung thì lấy khung bao cả hai."""
    if not faces:
        return None
    ci, si = (0, 2) if axis == "x" else (1, 3)

    def weight(f):
        w = f[2] * f[3] * f[4]
        return w * 1.6 if prev is not None and abs(f[ci] - prev) < span * 0.35 else w

    ranked = sorted(faces, key=weight, reverse=True)
    top = weight(ranked[0])
    lo, hi = ranked[0][ci] - ranked[0][si] / 2, ranked[0][ci] + ranked[0][si] / 2
    for f in ranked[1:]:
        if weight(f) < top * 0.35:
            break
        nlo, nhi = min(lo, f[ci] - f[si] / 2), max(hi, f[ci] + f[si] / 2)
        if nhi - nlo <= span * 0.85:
            lo, hi = nlo, nhi
    c = (lo + hi) / 2
    if axis == "y":
        c += (hi - lo) * 0.35       # khung đứng: để đầu nằm ở phần trên, không phải chính giữa
    return c


def _median5(v: list[float]) -> list[float]:
    """Bỏ các lần nhận nhầm chỉ xuất hiện một hai khung."""
    return [float(np.median(v[max(0, i - 2):i + 3])) for i in range(len(v))]


def _shot_segments(a: float, b: float, times: list[float], targets: list[float], span: float, lo: float, hi: float) -> tuple[list[list[float]], int]:
    """Một cảnh -> các đoạn [t0, t1, p0, p1]: đứng yên (p0 = p1) xen kẽ lia. Lia đúng một đoạn liên tục, không nhảy."""
    f = [min(hi, max(lo, x)) for x in _median5(targets)]
    pos = float(np.median(f[:6]))
    dead = span * DEAD_ZONE
    segs: list[list[float]] = []
    cur = a
    moves = 0
    i = 0
    n = len(f)
    while i < n:
        if abs(f[i] - pos) <= dead or times[i] < cur + (MIN_HOLD if moves else 0.0):
            i += 1
            continue
        ahead = f[i:i + PERSIST]
        goal = float(np.median(ahead))
        # chỉ thoáng qua thì không đáng lia: phải ở hẳn về một phía gần như suốt khoảng này
        stay = sum(1 for x in ahead if (x - pos) * (goal - pos) > 0 and abs(x - pos) > dead * 0.75)
        if abs(goal - pos) <= dead or stay < len(ahead) - 1:
            i += 1
            continue
        length = min(GLIDE_MAX, max(GLIDE_MIN, abs(goal - pos) / span / GLIDE_SPEED))
        t0 = max(cur, times[i] - 0.1)
        t1 = t0 + length
        if t1 >= b:      # không kịp lia xong trước khi hết cảnh
            break
        if t0 > cur:
            segs.append([round(cur, 3), round(t0, 3), round(pos, 4), round(pos, 4)])
        segs.append([round(t0, 3), round(t1, 3), round(pos, 4), round(goal, 4)])
        moves += 1
        pos, cur = goal, t1
        while i < n and times[i] < t1:
            i += 1
    segs.append([round(cur, 3), round(b, 3), round(pos, 4), round(pos, 4)])
    return segs, moves


def reframe_plan(scan: dict, scene_times: list[float], duration: float, src_w: int, src_h: int, out_w: int, out_h: int,
                 pins: list | None = None, flip: bool = False, zoom: float = 1.0) -> dict | None:
    """Tính đường đi của khung cắt. None nếu tỉ lệ đã khớp, không cần cắt.

    pins: [[giây bất kỳ trong cảnh, tâm khung, trục], ...] do người dùng đặt tay, cảnh đó giữ yên đúng vị trí này. Toạ độ
    theo video gốc. Ghim của trục khác bị bỏ qua vì không còn ý nghĩa (đổi 9:16 sang 16:9). flip, zoom: các bước đứng trước
    khung cắt trong bộ lọc, làm vị trí nhân vật đổi theo. Cảnh không có mặt và không có chuyển động thì để giữa khung."""
    ar_src, ar_out = src_w / src_h, out_w / out_h
    if abs(ar_src / ar_out - 1) < 0.02 or duration <= 0:
        return None
    axis = "x" if ar_out < ar_src else "y"
    full = src_w if axis == "x" else src_h
    crop = _even(src_h * ar_out) if axis == "x" else _even(src_w / ar_out)
    crop = min(crop, full)
    span = crop / full
    lo, hi = span / 2, 1 - span / 2
    z = max(1.0, float(zoom or 1.0))

    def place(c: float) -> float:
        if flip and axis == "x":
            c = 1 - c
        return (c - 0.5) * z + 0.5

    def face_view(f: list[float]) -> list[float] | None:
        cx, cy = f[0], f[1]
        if flip:
            cx = 1 - cx
        cx, cy = (cx - 0.5) * z + 0.5, (cy - 0.5) * z + 0.5
        return None if not (0 <= cx <= 1 and 0 <= cy <= 1) else [cx, cy, f[2] * z, f[3] * z, f[4]]

    fps = float(scan.get("fps") or SCAN_FPS)
    face_map = {int(i): fs for i, fs in scan.get("faces") or []}
    motion_map = {int(m[0]): m for m in scan.get("motion") or []}
    edges = [0.0, *[t for t in scene_times if 0 < t < duration], duration]
    pin_list = [(float(p[0]), float(p[1])) for p in pins or [] if isinstance(p, (list, tuple)) and len(p) >= 2 and (len(p) < 3 or p[2] == axis)]
    default = min(hi, max(lo, 0.5))
    segs: list[list[float]] = []
    moves = with_face = samples = 0
    shots: list[dict] = []
    for a, b in zip(edges, edges[1:]):
        if b - a <= 0:
            continue
        pinned = next((p for p in pin_list if a <= p[0] < b), None)
        idx = range(int(math.ceil(a * fps)), int(math.floor(b * fps)) + 1)
        times, targets = [], []
        prev = None
        for i in idx:
            view = [v for v in (face_view(f) for f in face_map.get(i, [])) if v]
            c = _frame_target(view, prev, axis, span)
            samples += 1
            if c is not None:
                with_face += 1
                prev = c
                times.append(i / fps)
                targets.append(c)
        how = "face"
        if pinned:
            pos = min(hi, max(lo, place(pinned[1])))
            segs.append([round(a, 3), round(b, 3), round(pos, 4), round(pos, 4)])
            shots.append({"start": round(a, 3), "end": round(b, 3), "how": "pin"})
            continue
        if not targets:
            ms = [motion_map[i] for i in idx if i in motion_map]
            if len(ms) >= max(2, len(idx) * 0.3):
                mv = [(1 - m[1] if flip else m[1]) if axis == "x" else m[2] for m in ms]
                pos = min(hi, max(lo, (float(np.median(mv)) - 0.5) * z + 0.5))
                how = "motion"
            else:
                pos = default
                how = "center"
            segs.append([round(a, 3), round(b, 3), round(pos, 4), round(pos, 4)])
            shots.append({"start": round(a, 3), "end": round(b, 3), "how": how})
            continue
        seg, m = _shot_segments(a, b, times, targets, span, lo, hi)
        segs += seg
        moves += m
        shots.append({"start": round(a, 3), "end": round(b, 3), "how": how})
    return {"axis": axis, "crop": [crop, src_h] if axis == "x" else [src_w, crop], "span": round(span, 5), "segs": segs, "shots": shots,
            "moves": moves, "face_ratio": round(with_face / samples, 3) if samples else 0.0}


def pos_at(plan: dict, t: float) -> float:
    """Tâm khung cắt ở giây t. Trang Studio có hàm giống hệt để xem trước (player.js)."""
    segs = plan["segs"]
    for s in segs:
        if t < s[1]:
            if s[2] == s[3] or t <= s[0]:
                return s[2]
            u = min(1.0, (t - s[0]) / max(1e-6, s[1] - s[0]))
            return s[2] + (s[3] - s[2]) * u * u * (3 - 2 * u)
    return segs[-1][3]


def _offset(plan: dict, c: float, src_w: int, src_h: int) -> int:
    full, crop = (src_w, plan["crop"][0]) if plan["axis"] == "x" else (src_h, plan["crop"][1])
    return max(0, min(full - crop, int(round((c - plan["span"] / 2) * full))))


def write_commands(plan: dict, path: Path, fps: float, src_w: int, src_h: int) -> int:
    """Viết lệnh dịch khung cắt cho bộ lọc sendcmd: đoạn đứng yên một lệnh, đoạn lia một lệnh mỗi khung. -> vị trí đầu."""
    fps = max(1.0, min(120.0, float(fps or 30.0)))
    axis = plan["axis"]
    lines = []
    last = None
    first = None

    def add(t: float, c: float) -> None:
        nonlocal last, first
        px = _offset(plan, c, src_w, src_h)
        if first is None:
            first = px
        if px != last:
            lines.append(f"{t:.3f} crop@rf {axis} {px};")
            last = px

    for s in plan["segs"]:
        add(s[0], s[2])
        if s[2] != s[3]:
            k = 1
            while s[0] + k / fps < s[1]:
                t = s[0] + k / fps
                add(t, pos_at({"segs": [s]}, t))
                k += 1
            add(s[1], s[3])
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return first or 0


def reframe_filter(plan: dict, cmd_file: str, start: int, out_w: int, out_h: int) -> str:
    """Cắt ở độ phân giải gốc rồi mới phóng: nhanh hơn nhiều so với phóng to rồi cắt mà chất lượng như nhau.
    Khung cắt có tên riêng vì sendcmd chỉ gửi cho bộ lọc đầu tiên khớp tên, trong đồ thị còn nhiều bộ crop khác."""
    cw, ch = plan["crop"]
    x, y = (start, 0) if plan["axis"] == "x" else (0, start)
    return f"sendcmd=f={cmd_file},crop@rf={cw}:{ch}:{x}:{y},scale={out_w}:{out_h}:flags=lanczos,setsar=1"
