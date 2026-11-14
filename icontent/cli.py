"""iContent CLI.

  python -m icontent ui                                       mở iContent Studio (web, http://127.0.0.1:8765)
  python -m icontent ui --app                                 mở như phần mềm riêng, đóng cửa sổ là tự tắt
  python -m icontent shortcut                                 tạo biểu tượng iContent Studio trên màn hình nền
  python -m icontent run <link|file|thư-mục-job> [...]      chạy toàn bộ pipeline
  python -m icontent run -f links.txt                         nhiều link (mỗi dòng 1 link)
  python -m icontent download <link> [...]                    chỉ tải
  python -m icontent voices [--lang vi]                       liệt kê giọng edge-tts
  python -m icontent doctor                                   kiểm tra môi trường
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .util import ROOT, fix_console_encoding, log


def _default_config() -> str | None:
    for p in (Path.cwd() / "config.yaml", ROOT / "config.yaml"):
        if p.exists():
            return str(p)
    return None


def _overrides(a) -> dict:
    o: dict = {}

    def put(path: str, val):
        if val is None:
            return
        d = o
        keys = path.split(".")
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = val

    put("download.cookies_file", a.cookies)
    put("download.cookies_from_browser", getattr(a, "cookies_from_browser", None))
    put("asr.model", getattr(a, "asr_model", None))
    put("translate.provider", getattr(a, "provider", None))
    put("translate.model", getattr(a, "model", None))
    put("translate.target_lang", getattr(a, "lang", None))
    put("tts.voice", getattr(a, "voice", None))
    put("tts.engine", getattr(a, "tts", None))
    put("tts.vieneu_voice", getattr(a, "vieneu_voice", None))
    put("tts.ref_audio", getattr(a, "ref_audio", None))
    if getattr(a, "vieneu_voice", None) or getattr(a, "voice", None):
        put("tts.voice_mode", "fixed")          # chỉ định giọng cụ thể -> không tự chọn nam/nữ
    put("tts.voice_mode", getattr(a, "voice_mode", None))
    put("edit.sub_style", getattr(a, "style", None))
    put("edit.watermark_text", getattr(a, "watermark", None))
    put("audio.music", getattr(a, "music", None))
    put("edit.aspect", getattr(a, "aspect", None))
    put("edit.fit", getattr(a, "fit", None))
    put("edit.speed", getattr(a, "speed", None))
    put("edit.encoder", getattr(a, "encoder", None))
    put("audio.separate", getattr(a, "separate", None))
    if getattr(a, "no_dub", False):
        put("tts.enabled", False)
    if getattr(a, "no_subs", False):
        put("edit.burn_subs", False)
    if getattr(a, "blur_hardsub", False):
        put("edit.blur_hardsub", True)
    if getattr(a, "no_hardsub", False):
        put("edit.blur_hardsub", False)
    if getattr(a, "hardsub_box", None):
        box = [float(x) for x in a.hardsub_box.split(",")]
        if len(box) != 4 or not all(0 <= v <= 1 for v in box):
            raise SystemExit("--hardsub-box cần 4 số 0-1: x,y,rộng,cao  (vd 0.05,0.62,0.9,0.08)")
        put("edit.hardsub_box", box)
        put("edit.blur_hardsub", True)
    if getattr(a, "flip", False):
        put("edit.flip", True)
    return o


def _sources(a) -> list[str]:
    srcs = list(a.src or [])
    if getattr(a, "file", None):
        for line in Path(a.file).read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                srcs.append(line)
    if not srcs:
        sys.exit("Chưa có link/file nào. Ví dụ: python -m icontent run https://www.bilibili.com/video/BV...")
    return srcs


def cmd_doctor(_a) -> int:
    import importlib
    import subprocess

    ok = True

    def line(name, good, info=""):
        nonlocal ok
        ok &= bool(good) or name.startswith("(tùy chọn)")
        print(f"  {'OK ' if good else '-- '} {name:34s} {info}")

    print("iContent doctor")
    try:
        from .util import find_ffmpeg
        ff, _ = find_ffmpeg()
        v = subprocess.run([ff, "-version"], capture_output=True, text=True).stdout.split("\n")[0]
        filt = subprocess.run([ff, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        line("ffmpeg", True, v[:60])
        line("ffmpeg có libass (burn sub)", " ass " in filt, "")
        enc = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        line("(tùy chọn) h264_nvenc", "h264_nvenc" in enc, "render bằng GPU: --encoder h264_nvenc")
    except Exception as e:
        line("ffmpeg", False, str(e)[:120])
    for mod, label in [("yt_dlp", "yt-dlp"), ("faster_whisper", "faster-whisper"), ("edge_tts", "edge-tts"),
                       ("anthropic", "anthropic SDK")]:
        try:
            m = importlib.import_module(mod)
            ver = getattr(m, "__version__", "") or getattr(getattr(m, "version", None), "__version__", "")
            line(label, True, str(ver))
        except Exception as e:
            line(label, False, str(e)[:100])
    try:
        from .asr import _add_cuda_dlls
        _add_cuda_dlls()
        import ctranslate2
        n = ctranslate2.get_cuda_device_count()
        line("(tùy chọn) CUDA cho Whisper", n > 0, f"{n} GPU")
    except Exception as e:
        line("(tùy chọn) CUDA cho Whisper", False, str(e)[:100])
    from .separate import available
    line("(tùy chọn) audio-separator", available(), 'tách nhạc nền: pip install "audio-separator[gpu]"')
    from .hardsub import available as ocr_ok
    line("(tùy chọn) OCR (rapidocr)", ocr_ok(), "tự dò + đọc sub gốc: pip install rapidocr")
    from .speakers import available as speakers_ok
    line("(tùy chọn) Nhận diện người nói", speakers_ok(), "mỗi người một giọng: pip install sherpa-onnx")
    from .offline import ready as offline_ready
    line("(tùy chọn) Dịch offline", offline_ready(), "không cần key: Studio > Cài đặt > Mô-đun AI miễn phí, bấm Tải")
    line("(tùy chọn) ANTHROPIC_API_KEY", bool(os.environ.get("ANTHROPIC_API_KEY")), "dịch bằng Claude")
    return 0 if ok else 1


def cmd_voices(a) -> int:
    print("== edge-tts (--tts edge --voice ...)")
    try:
        from .tts import list_voices
        for v in list_voices(a.lang):
            print(f"  {v['ShortName']:32s} {v['Gender']:7s} {v['Locale']}")
    except Exception as e:
        print(f"  (không lấy được: {e})")
    print('== VieNeu-TTS (--tts vieneu --vieneu-voice "...")')
    try:
        from .tts import _VieNeu
        for label, vid in _VieNeu.get().list_preset_voices():
            print(f"  {vid:20s} {label}")
    except ImportError:
        print("  (chưa cài: pip install vieneu)")
    return 0


def _need_license() -> bool:
    """Bản phát hành chưa kích hoạt: dòng lệnh cũng không chạy (giao diện thì có màn Kích hoạt)."""
    from . import license as lic
    if not lic.locked():
        return False
    st = lic.public_state()
    log("bản quyền", f"{st['message']}\n  Mã máy: {st['machine']}\n  Nhận key: {st['telegram']}\n  Rồi chạy: icontent.cmd license <key>")
    return True


def cmd_license(a) -> int:
    from . import license as lic
    if a.key:
        ok, msg = lic.install_token(" ".join(a.key))
        log("bản quyền", msg)
        if not ok:
            return 1
    st = lic.public_state()
    if not st.get("enforced"):
        log("bản quyền", st["message"])
        return 0
    exp = f"hết hạn {st['expires'][:10]}, còn {st['days_left']} ngày" if st.get("expires") and st["licensed"] else ("trọn đời" if st.get("lifetime") else "")
    log("bản quyền", f"{'Đã kích hoạt' if st['licensed'] else st['message']}{' (' + st['customer'] + ', ' + exp + ')' if st['licensed'] else ''}"
                     f"\n  Mã máy: {st['machine']}\n  Bot cấp key: {st['telegram']}")
    return 0 if st["licensed"] else 2


def cmd_download(a) -> int:
    from .config import load_config
    from .download import fetch
    if _need_license():
        return 2
    cfg = load_config(a.config, _overrides(a))
    for s in _sources(a):
        job = fetch(s, cfg)
        log("download", f"-> {job / 'source.mp4'}")
    return 0


def cmd_run(a) -> int:
    from .config import load_config
    from .pipeline import run_many
    if _need_license():
        return 2
    cfg = load_config(a.config)
    return run_many(_sources(a), cfg, a.from_stage, _overrides(a) or None)


def cmd_ui(a) -> int:
    import threading
    import webbrowser

    import uvicorn

    from . import appwin

    os.chdir(ROOT)            # đường dẫn tương đối (workspace/, output/) luôn tính từ thư mục dự án
    url = f"http://{appwin._url_host(a.host)}:{a.port}"
    if a.app and not a.child:
        if appwin.already_running(a.host, a.port):      # bấm mở lần hai: chỉ cần thêm cửa sổ
            appwin.open_window(url)
            return 0
        if appwin.port_taken(a.host, a.port):
            raise RuntimeError(f"Cổng {a.port} đang bị một chương trình khác dùng nên iContent chưa mở được. Hãy đóng chương trình đó rồi mở lại.")
        appwin.open_window(appwin.splash_url(url))      # mở ngay, không bắt người dùng nhìn màn hình trống chờ nạp thư viện
        # máy chủ chạy ở tiến trình con: chết bất thường thì tiến trình này chạy lại, cửa sổ tự kết nối lại (appwin.supervise)
        cmd = [sys.executable, "-m", "icontent", "ui", "--app", "--child", "--host", a.host, "--port", str(a.port)]
        if a.config:
            cmd += ["--config", a.config]
        return appwin.supervise(cmd)
    from .about import cli_line
    from .web.server import create_app
    log("ui", f"iContent Studio: {url}   (Ctrl+C để thoát)")
    log("ui", cli_line())
    app = create_app(a.config)
    appwin.clear_start_error()
    app.state.check_host = a.host in ("127.0.0.1", "localhost", "::1")
    server = uvicorn.Server(uvicorn.Config(app, host=a.host, port=a.port, log_level="warning", log_config=None if a.app else uvicorn.config.LOGGING_CONFIG))
    if a.app:
        appwin.stop_when_idle(app, server)
    elif not a.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    server.run()
    return 0


def cmd_release(a) -> int:
    from .release import build
    if not a.no_exe:
        log("release", "Đang đóng gói zip và file cài .exe (vài phút) ...")
    # Python kèm theo = Python gốc của chính môi trường đang chạy lệnh này (môi trường đã chạy bộ test, làm ra constraints.txt)
    r = build(a.out, pubkey=a.pubkey, free=a.free, bot=a.bot, runtime=None if a.no_python else sys.base_prefix, exe=not a.no_exe)
    for w in r["warnings"]:
        log("release", "Lưu ý: " + w)
    lines = [f"{r['path']} ({r['size'] / 1e6:.0f} MB, {r['files']} file)  SHA-256: {r['sha256']}"]
    if r.get("exe"):
        lines.append(f"{r['exe']} ({r['exe_size'] / 1e6:.0f} MB)  SHA-256: {r['exe_sha256']}")
    lines.append("Bản KHÔNG khoá bản quyền" if r["free"] else f"Khoá bản quyền: key từ @{r['bot']}")
    log("release", "\n  ".join(lines))
    return 0


def cmd_shortcut(a) -> int:
    from . import appwin
    log("ui", f"Đã tạo biểu tượng: {appwin.create_shortcut()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    from . import appwin
    windowless = appwin.windowless_setup()
    fix_console_encoding()
    from .keys import load_keys
    load_keys()
    p = argparse.ArgumentParser(prog="icontent", description="Tải video TQ -> phụ đề -> dịch -> lồng tiếng -> dựng video")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("src", nargs="*", help="link, đoạn text chia sẻ, file video, hoặc thư mục job")
        sp.add_argument("-f", "--file", help="file chứa danh sách link")
        sp.add_argument("-c", "--config", default=_default_config())
        sp.add_argument("--cookies", help="cookies.txt (Douyin cần)")
        sp.add_argument("--cookies-from-browser", help="firefox | chrome | edge")

    r = sub.add_parser("run", help="chạy toàn bộ pipeline")
    common(r)
    r.add_argument("--from", dest="from_stage", help="chạy lại từ bước: download|audio|separate|asr|translate|tts|render")
    r.add_argument("--asr-model")
    r.add_argument("--provider", choices=["claude", "openai", "offline", "google", "none"])
    r.add_argument("--model", help="model dịch")
    r.add_argument("--lang", help="ngôn ngữ đích (mặc định vi)")
    r.add_argument("--tts", choices=["edge", "vieneu"], help="engine lồng tiếng")
    r.add_argument("--voice", help="giọng edge-tts, vd vi-VN-NamMinhNeural")
    r.add_argument("--vieneu-voice", help='giọng VieNeu, vd "Thiện Minh"')
    r.add_argument("--ref-audio", help="file mẫu 3-8s để VieNeu clone giọng")
    r.add_argument("--separate", choices=["auto", "on", "off"])
    r.add_argument("--no-dub", action="store_true", help="chỉ làm phụ đề, không lồng tiếng")
    r.add_argument("--no-subs", action="store_true", help="không burn phụ đề vào video")
    r.add_argument("--voice-mode", choices=["auto", "per_line", "fixed", "clone"],
                   help="auto: chọn nam/nữ theo giọng gốc | per_line: từng câu | fixed | clone: bắt chước giọng gốc")
    r.add_argument("--style", choices=["classic", "cinema", "box", "tiktok", "karaoke", "pop"], help="kiểu phụ đề")
    r.add_argument("--watermark", help='chữ mờ góc video, vd "@kenhcuaban"')
    r.add_argument("--music", help="file nhạc nền thêm vào (tự lặp)")
    r.add_argument("--blur-hardsub", action="store_true", help="che sub gốc ở vùng hardsub_box (mặc định: tự dò)")
    r.add_argument("--no-hardsub", action="store_true", help="không che / không dò sub gốc")
    r.add_argument("--hardsub-box", help="vùng che x,y,rộng,cao theo tỉ lệ 0-1, vd 0.05,0.62,0.9,0.08")
    r.add_argument("--flip", action="store_true", help="lật ngang")
    r.add_argument("--aspect", choices=["keep", "9:16", "16:9", "1:1"])
    r.add_argument("--fit", choices=["blur", "track", "crop", "black"], help="cách đưa hình vào khung mới. track: khung đi theo nhân vật")
    r.add_argument("--speed", type=float)
    r.add_argument("--encoder", help="libx264 | h264_nvenc")
    r.set_defaults(fn=cmd_run)

    d = sub.add_parser("download", help="chỉ tải video")
    common(d)
    d.set_defaults(fn=cmd_download)

    v = sub.add_parser("voices", help="liệt kê giọng edge-tts")
    v.add_argument("--lang", default="vi")
    v.set_defaults(fn=cmd_voices)

    u = sub.add_parser("ui", help="mở iContent Studio (giao diện web)")
    u.add_argument("-c", "--config", default=_default_config())
    u.add_argument("--host", default="127.0.0.1")
    u.add_argument("--port", type=int, default=8765)
    u.add_argument("--no-browser", action="store_true")
    u.add_argument("--app", action="store_true", help="mở như phần mềm riêng, đóng cửa sổ là tự tắt")
    u.add_argument("--child", action="store_true", help=argparse.SUPPRESS)      # máy chủ do tiến trình giám sát (--app) chạy
    u.set_defaults(fn=cmd_ui)

    sc = sub.add_parser("shortcut", help="tạo biểu tượng iContent Studio trên màn hình nền")
    sc.set_defaults(fn=cmd_shortcut)

    dr = sub.add_parser("doctor", help="kiểm tra môi trường")
    dr.set_defaults(fn=cmd_doctor)

    rl = sub.add_parser("release", help="đóng gói bản phát hành gửi người dùng (file cài .exe + file zip)")
    rl.add_argument("--no-exe", action="store_true", help="chỉ làm file zip, không làm file cài .exe (không cần Inno Setup)")
    rl.add_argument("--no-python", action="store_true", help="không kèm Python vào gói (máy người dùng tự có hoặc tự cài qua winget)")
    rl.add_argument("--out", help="thư mục ghi file zip (mặc định: dist)")
    rl.add_argument("--pubkey", help="khoá công khai iContent của bot cấp key (mặc định: icontent/license_pubkey.txt)")
    rl.add_argument("--bot", default="", help="tên bot Telegram cấp key (mặc định Kichhoatkey_bot)")
    rl.add_argument("--free", action="store_true", default=True, help="bản không khoá bản quyền (mặc định trong bản fork)")
    rl.set_defaults(fn=cmd_release)

    li = sub.add_parser("license", help="xem mã máy, trạng thái bản quyền; kèm key để kích hoạt")
    li.add_argument("key", nargs="*", help="key bot gửi")
    li.set_defaults(fn=cmd_license)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        log("LỖI", str(e))
        if windowless:
            appwin.start_failed(str(e))
        return 1
