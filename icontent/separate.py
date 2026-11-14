"""Tách giọng nói khỏi nhạc nền bằng mô hình UVR MDX-Net (UVR-MDX-NET-Inst_HQ_3), chạy thẳng bằng ONNX Runtime.

Vì sao không dùng thư viện audio-separator như trước: nó kéo theo torch (vài GB) nên bộ cài không kèm, khách chọn
Tách nhạc nền: Bật là gặp lỗi "chưa cài audio-separator". Mô hình MDX-Net vốn là file ONNX; phần còn lại (STFT, cắt
đoạn chồng nhau, cửa sổ Hann) viết lại bằng numpy theo đúng cách audio-separator làm, nên kết quả như nhau mà chỉ cần
onnxruntime (đã có sẵn, dùng cho RapidOCR, sherpa-onnx, VieNeu). Mô hình 67 MB tự tải lần đầu, kiểm SHA-256.

Máy nào đã tự cài audio-separator (có GPU, muốn nhanh hơn hoặc dùng mô hình khác) thì vẫn dùng nó như cũ.
"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from .util import ROOT, check_cancel, log, note, progress

MODEL_DIR = ROOT / "models" / "uvr"
# Thông số mô hình theo bảng model_data của UVR (dim_f 3072, dim_t 2^8, n_fft 6144, compensate 1.022)
MODEL = {"file": "UVR-MDX-NET-Inst_HQ_3.onnx",
         "url": "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/UVR-MDX-NET-Inst_HQ_3.onnx",
         "size": 66759214, "sha256": "317554b07fe1ea5279a77f2b1520a41ea4b93432560c4ffd08792c30fddf9adc",
         "n_fft": 6144, "hop": 1024, "dim_f": 3072, "dim_t": 256, "compensate": 1.022}
SR = 44100
OVERLAP = 0.25
AUTO_MAX_SEC = 600      # Tự động: chỉ tách video tới 10 phút (trên CPU mất khoảng 0,6–0,8 lần thời lượng); Bật thì luôn tách
_dl_lock = threading.Lock()


class SeparateError(RuntimeError):
    pass


def available() -> bool:
    """Có tách được nhạc nền không (luôn có: onnxruntime đi kèm Studio566; mô hình tải khi cần)."""
    try:
        import onnxruntime  # noqa: F401
        return True
    except ImportError:
        return _has_audio_separator()


def _has_audio_separator() -> bool:
    try:
        import audio_separator  # noqa: F401
        return True
    except ImportError:
        return False


def model_path() -> Path:
    return MODEL_DIR / MODEL["file"]


def model_ready() -> bool:
    p = model_path()
    return p.is_file() and p.stat().st_size == MODEL["size"]


def ensure_model() -> Path:
    """Tải mô hình (67 MB) nếu chưa có. Tải tiếp được khi mất mạng giữa chừng, sai mã kiểm tra thì xóa."""
    p = model_path()
    with _dl_lock:
        if model_ready():
            return p
        from . import localai
        part = p.with_name(p.name + ".part")
        cancel = threading.Event()
        last = [-1]

        def on_have(n: int) -> None:
            check_cancel()
            pct = int(n * 100 / MODEL["size"])
            progress("separate", n / MODEL["size"] * 0.15)
            if pct != last[0] and pct % 5 == 0:
                last[0] = pct
                note(f"Tải bộ tách nhạc nền (67 MB, chỉ lần đầu): {pct}%")
        log("separate", "Tải bộ tách nhạc nền UVR MDX-Net (67 MB, chỉ lần đầu)...")
        try:
            localai.fetch(MODEL["url"], part, MODEL["size"], MODEL["sha256"], cancel, on_have=on_have, retries=4)
        except localai.DownloadError as e:
            raise SeparateError(f"Chưa tải được bộ tách nhạc nền: {e}") from e
        part.replace(p)
    return p


# ---------------------------------------------------------------------------- STFT giống torch.stft(center=True)

def _window(n_fft: int) -> np.ndarray:
    return (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n_fft) / n_fft)).astype(np.float32)      # Hann tuần hoàn


def _stft(x: np.ndarray, n_fft: int, hop: int, win: np.ndarray) -> np.ndarray:
    """x [C, L] -> phổ phức [C, F, T]."""
    pad = n_fft // 2
    xp = np.pad(x, ((0, 0), (pad, pad)), mode="reflect")
    t = 1 + (xp.shape[1] - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(t)[:, None]
    return np.fft.rfft(xp[:, idx] * win, axis=-1).transpose(0, 2, 1)


def _istft(spec: np.ndarray, n_fft: int, hop: int, win: np.ndarray, length: int) -> np.ndarray:
    """phổ phức [C, F, T] -> x [C, length], cộng chồng và chia cho tổng bình phương cửa sổ như torch.istft."""
    frames = np.fft.irfft(spec.transpose(0, 2, 1), n=n_fft, axis=-1).astype(np.float32) * win      # [C, T, n_fft]
    c, t, _ = frames.shape
    total = n_fft + hop * (t - 1)
    y = np.zeros((c, total), np.float32)
    wsum = np.zeros(total, np.float32)
    w2 = win * win
    for i in range(t):
        s = i * hop
        y[:, s:s + n_fft] += frames[:, i]
        wsum[s:s + n_fft] += w2
    pad = n_fft // 2
    y, wsum = y[:, pad:pad + length], wsum[pad:pad + length]
    return y / np.where(wsum > 1e-8, wsum, 1.0)


class _MDX:
    def __init__(self, path: Path):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.log_severity_level = 3
        self.sess = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        self.inp = self.sess.get_inputs()[0].name
        m = MODEL
        self.n_fft, self.hop, self.dim_f, self.dim_t = m["n_fft"], m["hop"], m["dim_f"], m["dim_t"]
        self.n_bins = self.n_fft // 2 + 1
        self.chunk = self.hop * (self.dim_t - 1)
        self.trim = self.n_fft // 2
        self.win = _window(self.n_fft)

    def _run(self, part: np.ndarray) -> np.ndarray:
        """part [2, chunk] -> phần nhạc nền dự đoán [2, chunk]."""
        spec = _stft(part, self.n_fft, self.hop, self.win)[:, :self.dim_f]      # [2, dim_f, T]
        x = np.stack([spec[0].real, spec[0].imag, spec[1].real, spec[1].imag])[None].astype(np.float32)
        x[:, :, :3, :] = 0
        y = self.sess.run(None, {self.inp: x})[0][0]
        full = np.zeros((2, self.n_bins, y.shape[-1]), np.complex64)
        full[0, :self.dim_f] = y[0] + 1j * y[1]
        full[1, :self.dim_f] = y[2] + 1j * y[3]
        return _istft(full, self.n_fft, self.hop, self.win, self.chunk)

    def instrumental(self, mix: np.ndarray) -> np.ndarray:
        """mix [2, L] -> nhạc nền [2, L]. Cắt đoạn chồng nhau 25 %, ghép bằng cửa sổ Hann (như audio-separator)."""
        n = mix.shape[1]
        gen = self.chunk - 2 * self.trim
        pad = gen + self.trim - (n % gen)
        m = np.concatenate([np.zeros((2, self.trim), np.float32), mix, np.zeros((2, pad), np.float32)], 1)
        step = int((1 - OVERLAP) * self.chunk)
        out = np.zeros_like(m)
        div = np.zeros(m.shape[1], np.float32)
        starts = list(range(0, m.shape[1], step))
        for k, s in enumerate(starts):
            check_cancel()
            e = min(s + self.chunk, m.shape[1])
            part = m[:, s:e]
            if part.shape[1] < self.chunk:
                part = np.concatenate([part, np.zeros((2, self.chunk - part.shape[1]), np.float32)], 1)
            w = np.hanning(e - s).astype(np.float32)
            out[:, s:e] += self._run(part)[:, :e - s] * w
            div[s:e] += w
            progress("separate", 0.15 + 0.85 * (k + 1) / len(starts))
            if k % 4 == 3 or k + 1 == len(starts):
                note(f"Tách nhạc nền: {int((k + 1) * 100 / len(starts))}%")
        out = out / np.where(div > 1e-6, div, 1.0)
        return out[:, self.trim:self.trim + n] * MODEL["compensate"]


def _read(path: Path) -> np.ndarray:
    import soundfile as sf
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if sr != SR:
        raise SeparateError(f"Âm thanh {sr} Hz, cần {SR} Hz")
    data = data.T
    if data.shape[0] == 1:
        data = np.repeat(data, 2, 0)
    return np.ascontiguousarray(data[:2])


def _write(path: Path, x: np.ndarray) -> None:
    import soundfile as sf
    tmp = path.with_name(path.stem + ".tmp.wav")
    sf.write(str(tmp), np.clip(x, -1.0, 1.0).T, SR, subtype="PCM_16")
    tmp.replace(path)


def split(audio_wav: Path, vocals: Path, bgm: Path) -> None:
    """Tách audio_wav (44,1 kHz) ra vocals.wav và bgm.wav bằng mô hình ONNX."""
    path = ensure_model()
    try:
        mdx = _MDX(path)
    except Exception as e:      # file hỏng dù đúng cỡ (ổ lỗi): xóa để lần sau tải lại
        path.unlink(missing_ok=True)
        raise SeparateError(f"Bộ tách nhạc nền bị hỏng, đã xóa để tải lại ở lần chạy sau ({str(e)[:160]})") from e
    mix = _read(audio_wav)
    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    g = 0.9 / peak if peak > 0.9 else 1.0      # mô hình được huấn luyện với đỉnh <= 0,9
    inst = mdx.instrumental(mix * g)
    voc = mix * g - inst
    # trả về đúng độ lớn của tiếng gốc (bước trộn tính âm lượng nhạc nền theo tiếng gốc); hai file cùng một hệ số
    top = max(float(np.max(np.abs(inst))), float(np.max(np.abs(voc))), 1e-9) / g
    k = (1.0 / g) * (0.99 / top if top > 0.99 else 1.0)
    _write(bgm, inst * k)
    _write(vocals, voc * k)


def _seconds(path: Path) -> float:
    try:
        import soundfile as sf
        return float(sf.info(str(path)).duration)
    except Exception:
        return 0.0


def _split_with_audio_separator(audio_wav: Path, job: Path, model: str, vocals: Path, bgm: Path) -> None:
    from audio_separator.separator import Separator
    out_dir = job / "sep"
    out_dir.mkdir(exist_ok=True)
    sep = Separator(output_dir=str(out_dir), output_format="WAV", model_file_dir=str(MODEL_DIR))
    sep.load_model(model_filename=model)
    files = [out_dir / Path(f).name for f in sep.separate(str(audio_wav))]
    voc = next((f for f in files if "vocal" in f.name.lower()), None)
    ins = next((f for f in files if "instrument" in f.name.lower()), None)
    if not (voc and ins):
        raise RuntimeError(f"audio-separator trả về file không nhận ra: {files}")
    voc.replace(vocals)
    ins.replace(bgm)


def separate(audio_wav: Path, job: Path, acfg) -> tuple[Path, Path] | None:
    """Trả (vocals.wav, bgm.wav), hoặc None khi tắt / không tách được ở chế độ Tự động (tiếng gốc được giữ nhỏ dưới giọng lồng)."""
    vocals, bgm = job / "vocals.wav", job / "bgm.wav"
    if vocals.exists() and bgm.exists():
        return vocals, bgm
    if acfg.separate == "off":
        return None
    model = getattr(acfg, "separator_model", "") or MODEL["file"]
    if acfg.separate == "auto" and not _has_audio_separator():
        sec = _seconds(audio_wav)
        if sec > AUTO_MAX_SEC:
            log("separate", f"Video dài {sec / 60:.0f} phút: bỏ tách nhạc nền cho nhanh (giữ tiếng gốc nhỏ dưới giọng lồng). "
                            "Muốn tách: Tùy chọn → Tách nhạc nền khỏi giọng gốc → Bật")
            return None
    try:
        if _has_audio_separator():
            log("separate", f"Tách giọng bằng audio-separator ({model}) ...")
            _split_with_audio_separator(audio_wav, job, model, vocals, bgm)
        else:
            log("separate", "Tách giọng gốc khỏi nhạc nền (UVR MDX-Net, chạy trên máy) ...")
            split(audio_wav, vocals, bgm)
    except Exception as e:
        from .util import Cancelled
        if isinstance(e, Cancelled):
            raise
        for f in (vocals, bgm):
            f.unlink(missing_ok=True)
        if acfg.separate == "on":
            raise SeparateError(str(e) if isinstance(e, SeparateError) else f"Không tách được nhạc nền: {e}") from e
        log("separate", f"Không tách được nhạc nền ({str(e)[:200]}) -> giữ tiếng gốc nhỏ dưới giọng lồng")
        return None
    return vocals, bgm
