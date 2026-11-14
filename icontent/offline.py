"""Dịch offline: model Hy-MT2 1.8B (Tencent, Apache-2.0) chạy ngay trên máy.

Không cần API key, không cần mạng khi dịch, câu thoại không rời khỏi máy. Model 1,1 GB, cần khoảng 1,3 GB VRAM
(không có card đồ họa thì chạy bằng CPU, chậm hơn).

Từ 0.4.0 chạy bằng bộ chạy llama.cpp do iContent tự tải (localai.py, gói "translate"): không phải cài Ollama.
Máy đã cài Ollama và tải model này từ bản cũ vẫn dùng được (và gói mới dùng lại đúng file đó, không tải lại).

Ghi chú đã kiểm chứng (trên Ollama 0.40):
  - Mẫu hội thoại tự sinh cho GGUF này bị hỏng (làm mất câu cần dịch) -> phải gọi raw với đúng mẫu của hãng.
  - temperature 0.3 ổn định hơn mức 0.7 hãng gợi ý: bớt hẳn lỗi dịch nhầm tên món.
  - Không mồi bằng các câu vừa dịch (kể cả qua mẫu "tham khảo"): model chép lại câu cũ vào câu mới.
  - Không kèm câu bên cạnh cho câu ngắn: 3/10 câu bị dịch lẫn cả câu bên cạnh. Câu chỉ có một từ xưng hô thì tra bảng.
  - Bản 7B (4,6 GB) không dùng được: tràn VRAM 6 GB và kết quả lẫn ký tự rác. qwen3:4b không dịch tốt hơn 1.8B
    (sót chữ Trung, sai tên món) và không đủ sức chọn đoạn hay để cắt clip (tự bịa số liệu).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .util import log

MODEL = "hf.co/tencent/Hy-MT2-1.8B-GGUF:Q4_K_M"
MODEL_MB = 1130
_BOS, _USER, _ASST = "<｜hy_begin▁of▁sentence｜>", "<｜hy_User｜>", "<｜hy_Assistant｜>"
_start_lock = threading.Lock()


def host() -> str:
    h = (os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434").strip().rstrip("/")
    h = h.replace("0.0.0.0", "127.0.0.1")
    return h if h.startswith("http") else "http://" + h


# Ollama chạy trên chính máy này: không đi qua proxy hệ thống (hay gặp khi bật VPN), nếu không sẽ tưởng Ollama chưa chạy
_local = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _call(path: str, body: dict | None = None, timeout: float = 5.0) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(host() + path, data, {"Content-Type": "application/json"})
    with _local.open(req, timeout=timeout) as r:
        return json.load(r)


def find_exe() -> str | None:
    """Trình cài của Ollama cập nhật PATH nhưng cửa sổ đang mở chưa thấy -> tìm cả chỗ cài mặc định."""
    p = shutil.which("ollama")
    if p:
        return p
    local = os.environ.get("LOCALAPPDATA")
    if local:
        f = Path(local, "Programs", "Ollama", "ollama.exe")
        if f.exists():
            return str(f)
    return None


def is_running() -> bool:
    try:
        return bool(_call("/api/version", timeout=1.5).get("version"))
    except (OSError, ValueError):
        return False


def start(wait: float = 30.0, model: str | None = None) -> bool:
    """Bật dịch vụ Ollama nếu đang tắt (chạy ẩn, không mở cửa sổ). Bộ chạy của iContent tự bật khi dịch câu đầu tiên."""
    if builtin(model):
        return True
    if is_running():
        return True
    exe = find_exe()
    if not exe:
        return False
    with _start_lock:
        if is_running():
            return True
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if os.name == "nt" else 0
        subprocess.Popen([exe, "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags)
        end = time.time() + wait
        while time.time() < end:
            if is_running():
                return True
            time.sleep(0.4)
    return False


def _models_dir() -> Path:
    custom = os.environ.get("OLLAMA_MODELS")
    return Path(custom) if custom else Path.home() / ".ollama" / "models"


def has_model(model: str | None = None) -> bool:
    """Đọc thẳng manifest trên đĩa để biết đã tải chưa, không cần bật dịch vụ."""
    name, _, tag = (model or MODEL).partition(":")
    parts = name.split("/")
    if len(parts) == 1:
        parts = ["registry.ollama.ai", "library", parts[0]]
    elif len(parts) == 2:
        parts = ["registry.ollama.ai", *parts]
    return _models_dir().joinpath("manifests", *parts, tag or "latest").exists()


def builtin(model: str | None = None) -> bool:
    """Dùng bộ chạy của iContent: model mặc định và gói Dịch offline đã tải. Tên model Ollama khác thì đi qua Ollama."""
    from . import localai
    return (not model or model == MODEL) and localai.pack_ready("translate")


def ready(model: str | None = None) -> bool:
    return builtin(model) or (bool(find_exe() or is_running()) and has_model(model))


def status(model: str | None = None) -> dict:
    from . import localai
    return {"installed": builtin(model) or bool(find_exe()) or is_running(), "running": localai.LLAMA.running() or is_running(),
            "model": model or MODEL, "has_model": builtin(model) or has_model(model), "ready": ready(model), "builtin": builtin(model),
            "ollama": bool(find_exe()), "model_mb": MODEL_MB}


def generate(prompt: str, model: str | None = None, temperature: float = 0.3, max_tokens: int = 256,
             timeout: float = 300.0) -> str:
    if builtin(model):
        from . import localai
        localai.LLAMA.ensure(localai.translate_model())
        head = "" if localai.LLAMA.adds_bos else _BOS
        return localai.LLAMA.complete(head + _USER + prompt + _ASST, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
    body = {"model": model or MODEL, "stream": False, "raw": True, "keep_alive": "45s",
            "prompt": _BOS + _USER + prompt + _ASST,
            "options": {"temperature": temperature, "top_p": 0.6, "top_k": 20, "repeat_penalty": 1.05,
                        "num_ctx": 2048, "num_predict": max_tokens}}
    return (_call("/api/generate", body, timeout=timeout).get("response") or "").strip()


def translate_text(text: str, lang: str, model: str | None = None) -> str:
    """Dịch một đoạn bất kỳ (không phải tiếng Trung), ví dụ lời nhắn vẽ ảnh tiếng Việt -> tiếng Anh."""
    names = {"en": "English", "vi": "Vietnamese", "zh": "Chinese"}
    prompt = f"Translate the following segment into {names.get(lang, lang)}, without additional explanation.\n\n{text}"
    return clean_output(generate(prompt, model, temperature=0.2, max_tokens=max(96, len(text) * 2)), lang)


# --------------------------------------------------------------------------- dịch

from .langs import LANGS as _LANGS

MT_LANG = {c: v["mt"] for c, v in _LANGS.items() if v["mt"]}      # tên tiếng Trung trong mẫu lời nhắn của Hy-MT2
_CJK = re.compile(r"[一-鿿]")
_LEAK = re.compile(r"(phong cách|kết quả dịch|văn bản|đầu ra)", re.IGNORECASE)
_VAN_WORDS = {
    "một trăm": "một triệu", "năm mươi": "năm trăm nghìn", "ba mươi": "ba trăm nghìn", "hai mươi": "hai trăm nghìn",
    "mười": "một trăm nghìn", "chín": "chín mươi nghìn", "tám": "tám mươi nghìn", "bảy": "bảy mươi nghìn",
    "sáu": "sáu mươi nghìn", "năm": "năm mươi nghìn", "bốn": "bốn mươi nghìn", "ba": "ba mươi nghìn",
    "hai": "hai mươi nghìn", "một": "mười nghìn",
}
_VAN_RE = re.compile(r"(?<!\w)(" + "|".join(_VAN_WORDS) + r")\s+vạn(?!\w)", re.IGNORECASE)
_VAN_NUM = re.compile(r"(?<![\d.,])(\d+)\s*vạn(?!\w)", re.IGNORECASE)


def vi_numbers(text: str) -> str:
    """Model hay giữ đơn vị 万 thành "vạn" -> đổi về cách nói người Việt quen: mười vạn = một trăm nghìn."""
    def num(m: re.Match) -> str:
        n = int(m.group(1)) * 10
        return f"{n // 1000} triệu" if n >= 1000 and n % 1000 == 0 else f"{n} nghìn"

    return _VAN_NUM.sub(num, _VAN_RE.sub(lambda m: _VAN_WORDS[m.group(1).lower()], text))


# câu chỉ có một từ gọi nhau: dịch rời thì ra nghĩa từ điển (老板 -> "Chủ doanh nghiệp"), trong khi đây là lời gọi
ADDRESS_VI = {"老板": "Ông chủ ơi", "兄弟": "Anh bạn ơi", "大哥": "Đại ca", "哥": "Anh ơi", "姐": "Chị ơi", "大姐": "Chị ơi",
              "妈": "Mẹ ơi", "爸": "Bố ơi", "老公": "Anh ơi", "老婆": "Em ơi", "师傅": "Bác ơi", "帅哥": "Anh đẹp trai ơi",
              "美女": "Người đẹp ơi", "小姐": "Cô ơi", "先生": "Thưa anh", "老师": "Thưa thầy"}


def address_word(text: str, lang: str) -> str:
    if lang != "vi":
        return ""
    return ADDRESS_VI.get(re.sub(r"[\W_]+", "", text), "")


def task_prompt(text: str, lang: str, glossary: dict | None = None) -> str:
    name = MT_LANG.get(lang, lang)
    used = {k: v for k, v in (glossary or {}).items() if k and v and k in text}
    head = ""
    if used:     # chỉ đưa thuật ngữ thực sự có trong câu, đưa dư model sẽ chép vào câu không liên quan
        head = "参考下面的翻译：\n" + "".join(f"{k} 翻译成 {v}\n" for k, v in used.items()) + "\n"
    return f"{head}将以下文本翻译为{name}，注意只需要输出翻译后的结果，不要额外解释：\n\n{text}"


def short_prompt(text: str, lang: str) -> str:
    return (f"请将以下文本翻译为{MT_LANG.get(lang, lang)}。\n"
            f"注意翻译的风格要严格符合【简短、口语化】，只需要输出翻译后的结果。\n\n{text}")


def clean_output(text: str, lang: str) -> str:
    t = text.strip().strip('"“”').strip()
    t = re.sub(r"\s*\n+\s*", " ", t)
    return vi_numbers(t) if lang == "vi" else t


_KANA = re.compile(r"[぀-ヿ]")


def looks_broken(out: str, src: str, lang: str = "vi") -> bool:
    """Bản dịch còn chữ Trung, lộ câu lệnh, hoặc dài bất thường so với câu gốc.
    Tiếng Nhật được dùng chữ Hán: chỉ coi là sót tiếng Trung khi có chữ Hán mà không có chữ kana nào."""
    cjk = bool(_CJK.search(out or ""))
    if lang == "ja":
        cjk = cjk and not _KANA.search(out)
    leak = bool(_LEAK.search(out or "")) if lang == "vi" else False
    return not out or cjk or leak or len(out) > max(90, len(src) * 9)


# --------------------------------------------------------------------------- cài đặt: tải gói "translate" (localai.py)

SAMPLE = "你好，朋友们"


def self_test(model: str | None = None) -> str:
    """Dịch thử một câu sau khi tải: chắc chắn bộ chạy bật được trên máy này và model trả lời đúng."""
    out = clean_output(generate(task_prompt(SAMPLE, "vi"), model, max_tokens=64, timeout=240), "vi")
    if looks_broken(out, SAMPLE):
        raise RuntimeError(f"Model trả về kết quả lạ: {out[:120]}")
    log("offline", f"Dịch offline sẵn sàng: {out}")
    return f"Sẵn sàng. Dịch thử: “{out}”"


def begin_setup(model: str | None = None) -> bool:
    """Tải gói Dịch offline ở luồng nền rồi dịch thử. False nếu đang tải."""
    from . import localai
    return localai.begin("translate", after=lambda: self_test(None))
