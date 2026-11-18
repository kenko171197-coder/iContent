"""Dịch phụ đề theo lô, có ngữ cảnh và giới hạn số âm tiết để đọc kịp trong timeline.

provider:
  claude  — Anthropic SDK (mặc định claude-opus-5-5), structured output JSON
  openai  — mọi API tương thích OpenAI: DeepSeek, Gemini (OpenAI endpoint), Qwen, Ollama local...
  offline — Hy-MT2 chạy trên máy (bộ chạy tải sẵn, hoặc Ollama): không key, không mạng, không phân tích ngữ cảnh (offline.py)
  google  — Google Translate miễn phí (deep-translator), không cần key, không kiểm soát độ dài
  none    — bỏ qua dịch (chỉ làm phụ đề gốc)
"""
from __future__ import annotations

import json
import math
import os
import threading
import time

from .models import Segment
from .util import check_cancel, log, progress

from . import langs as _langs

LANG_NAMES = {c: v["en"] for c, v in _langs.LANGS.items()}      # tên tiếng Anh cho lời nhắn AI (xem langs.py)

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def parse_items(data, ids: list[int] | None = None) -> dict[int, str]:
    """Đọc {"items": [{"id", "text"}]} của AI, chịu được biến thể: model đời mới thỉnh thoảng bỏ "id", đổi tên trường
    ("ID", "line_id", "translation") hoặc trả danh sách chuỗi (gặp thật 11/2026: gemini-3.7-flash, cả lô 40 câu hỏng vì thiếu "id").
    Thiếu id thì khớp theo thứ tự, chỉ khi số câu trả về đúng bằng số câu gửi đi (lệch thì không đoán)."""
    items = data.get("items") if isinstance(data, dict) else data
    if isinstance(data, dict) and items is None:
        items = next((v for v in data.values() if isinstance(v, list)), None)
    if not isinstance(items, list):
        raise ValueError("AI trả lời sai dạng (không có danh sách câu dịch)")
    ids = list(ids or [])
    by_pos = len(items) == len(ids)
    out: dict[int, str] = {}
    for k, x in enumerate(items):
        if isinstance(x, dict):
            text = next((x[f] for f in ("text", "translation", "trans", "output") if isinstance(x.get(f), str)), None)
            i = next((x[f] for f in ("id", "ID", "Id", "line_id", "index") if f in x), None)
        else:
            text, i = (x if isinstance(x, str) else None), None
        if i is None and by_pos:
            i = ids[k]
        try:
            i = int(i)
        except (TypeError, ValueError):
            continue
        if text is not None:
            out[i] = str(text).strip()
    return out


def count_units(text: str, lang: str) -> int:
    """Độ dài câu theo đơn vị đọc: âm tiết (Việt), từ (Anh, Indonesia...), ký tự (Thái, Nhật, Hàn...). Xem langs.py."""
    return _langs.count_units(text, lang)


ANALYZE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "genre": {"type": "string"},
        "narrator_gender": {"type": "string", "enum": ["male", "female", "unknown"]},
        "speakers": {"type": "string"},
        "pronouns": {"type": "string"},
        "glossary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"zh": {"type": "string"}, "vi": {"type": "string"}},
                "required": ["zh", "vi"],
                "additionalProperties": False,
            },
        },
        "publish": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "caption": {"type": "string"},
                "hashtags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "caption", "hashtags"],
            "additionalProperties": False,
        },
    },
    "required": ["summary", "genre", "narrator_gender", "speakers", "pronouns", "glossary", "publish"],
    "additionalProperties": False,
}

CAST_SCHEMA = {
    "cast": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "gender": {"type": "string", "enum": ["male", "female"]},
            },
            "required": ["name", "gender"],
            "additionalProperties": False,
        },
    },
    "line_speakers": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "who": {"type": "string"}},
            "required": ["id", "who"],
            "additionalProperties": False,
        },
    },
}

CAST_RULES = """
Also work out WHO SAYS EACH LINE. A dub voice is assigned per character, so one character must keep one voice through the whole video:
- cast: every character that speaks, as {{"name", "gender"}}. name is short, in {lang}, the way viewers would call them (Bà, Cô bé, Ông chủ quán, Chú chó, Người dẫn chuyện...). gender is the voice gender the dub should use (a talking dog or toy: pick what fits the character).{count_rule}
- line_speakers: one entry {{"id", "who"}} for EVERY line id of the transcript, who = a name from cast.
Decide mainly from the dialogue itself: who is addressed (a line starting with 奶奶 / "grandma" is said TO grandma, so not by her), who answers whom, self-reference (我奶奶, 我老婆), turn-taking, and who is on scene. Lines may carry "v": a voice group guessed from the audio. It is a weak hint only: in cartoons and AI-dubbed videos different characters often sound alike and one character shouting is often put in another group. When the dialogue makes the speaker clear, follow the dialogue."""

ANALYZE_SYSTEM = """You prepare Chinese short videos for a {lang} voice-over dub that will be posted on TikTok, Reels and YouTube Shorts for {lang} viewers.

You receive the video title and its full transcript. The transcript comes from speech recognition and can contain misheard words; when a line has a "screen" field, that is the subtitle burned into the video at that moment, read by OCR, and it is usually more accurate for names and numbers.

Read the whole transcript first, then return:
- summary: what the video is about, 1-2 sentences in {lang}.
- genre: a few words in {lang} (e.g. review đồ ăn, hài, tình cảm, phim ngắn, hướng dẫn).
- narrator_gender: the main speaker's gender if the content makes it clear (e.g. 我老公 → female, 我老婆 → male), else unknown.
- speakers: in {lang}, who speaks and to whom (narrator to viewers, a dialogue between a customer and a shop owner, ...).
- pronouns: in {lang}, the forms of address the dub must use consistently, written as concrete rules a translator can follow line by line. For Vietnamese this is the xưng hô scheme: how each speaker refers to themself and to the listener (tôi/mình/anh/em/chị/ông/cháu/mày/tao...), chosen to fit their age, relationship and tone, plus how the narrator addresses viewers (e.g. "mọi người", "các bạn").
- glossary: names, places, brands, dishes and recurring terms with the {lang} rendering to use every time. Chinese person and place names use their Sino-Vietnamese reading; brands use the name {lang} viewers know.
- publish: a post kit written for {lang} viewers: title (catchy, at most 80 characters, faithful to the content), caption (2-3 short sentences ending with a light call to action), hashtags (5-8 tags, each starting with #, in the style common on {lang} TikTok, without spaces).
Respond with JSON only."""


def build_system_prompt(tcfg, context: dict | None = None) -> str:
    lang = LANG_NAMES.get(tcfg.target_lang, tcfg.target_lang)
    unit = _langs.unit_words(tcfg.target_lang)
    rules = [
        f"You translate Mandarin Chinese short-video subtitles into {lang} for a voice-over dub.",
        "",
        "Each request gives a JSON list of subtitle lines with an id, the Chinese text and a max_len.",
        "Return exactly one translation per id, in the same order. Never merge, split, drop or add lines: "
        "the dub is placed on the video timeline line by line.",
        f"A TTS voice reads each line inside the original line's time slot. max_len is the comfortable length in {unit}; "
        f"you may go up to about 25% over it when that is what it takes to say a complete, natural sentence. Never "
        "cut a line down to a fragment that no longer makes sense on its own (\"Ôi.\", \"Quá không biết lý.\"). "
        "Drop filler (嗯, 啊, 那个, 就是, 然后) rather than translate it.",
        "Translate the MEANING in context, the way people really talk in this scene, never word for word. Read idioms "
        "and set phrases as what they mean (喝西北风 = nhịn đói, not 'uống gió Tây Bắc'). In a scolding or while "
        "hitting someone, 我让你X! is sarcastic 'cho mày X này!' (我让你贴照片! → Cho mày dán ảnh này!), not 'tao bảo mày X'. "
        "Interjections and laughter become natural spoken equivalents, never letters copied by sound.",
        "Lines may carry 'who': the character saying the line. Use it to pick the right forms of address for that "
        "character towards the person they are talking to, and keep them consistent.",
        "The Chinese comes from speech recognition and may contain misheard words; infer the intended meaning "
        "from the surrounding lines and the video title.",
        "Some lines also carry 'screen': the subtitle burned into the video at that moment, read by OCR. It is "
        "usually the more reliable source for names, numbers and wording, but it can be cut off, belong to the "
        "neighbouring line, or contain OCR mistakes. Translate what is spoken in this line ('zh'), using 'screen' "
        "to correct recognition errors.",
        "Keep forms of address and pronouns consistent for the same speakers across the whole video.",
    ]
    if tcfg.target_lang == "vi":
        rules += [
            "Chinese person and place names use their Sino-Vietnamese (Hán-Việt) reading "
            "(李明 → Lý Minh, 北京 → Bắc Kinh, 成都 → Thành Đô); brands and products use the name Vietnamese "
            "viewers know (小米 → Xiaomi, 抖音 → Douyin).",
            "Write numbers, prices and units the way they are read aloud in Vietnamese (e.g. 5块钱 → năm tệ).",
        ]
    else:
        rules += [
            f"This dub targets {lang}-speaking viewers: write natural, everyday spoken {lang} that a native narrator would say, "
            "not a word-for-word translation.",
            f"Chinese person and place names use the form {lang} viewers know: the standard romanisation (pinyin without tone marks, "
            f"e.g. 李明 → Li Ming, 成都 → Chengdu) unless the name has an established form in {lang}"
            + (" (Japanese: write Chinese names in kanji with the usual reading)" if tcfg.target_lang == "ja" else "")
            + (" (Korean: write names in Hangul by their Sino-Korean reading, e.g. 李明 → 이명)" if tcfg.target_lang == "ko" else "")
            + ". Brands and products use their international names (小米 → Xiaomi, 抖音 → Douyin/TikTok).",
            f"Write numbers, prices and units the way a {lang} narrator reads them aloud; keep Chinese currency as yuan.",
        ]
    if tcfg.style:
        rules.append(f"Tone and style: {tcfg.style}")
    gloss = {}
    if context:
        gloss.update({g["zh"]: g["vi"] for g in context.get("glossary") or [] if g.get("zh") and g.get("vi")})
    gloss.update(dict(tcfg.glossary or {}))
    if context:
        rules += ["", "Video context, from a first read of the whole video:"]
        for k, label in (("summary", "Summary"), ("speakers", "Speakers"), ("pronouns", "Forms of address to use")):
            if context.get(k):
                rules.append(f"- {label}: {context[k]}")
        rules.append("")
    if gloss:
        rules.append("Glossary (always use these translations): " + json.dumps(gloss, ensure_ascii=False))
    rules.append('Respond with JSON only: {"items": [{"id": <id>, "text": "<translation>"}]}')
    return "\n".join(rules)


def _user_msg(items: list[dict], title: str, prev: list[str], shorten: bool, nxt: list[str] | None = None) -> str:
    parts = []
    if title:
        parts.append(f"Video title: {title}")
    if prev:
        parts.append("Previous lines (already translated, for continuity):\n" + "\n".join(prev))
    if nxt:
        parts.append("Next lines (not to translate, only so you know where the conversation goes):\n" + "\n".join(nxt))
    if shorten:
        parts.append(
            "These translations are too long to be spoken in their time slots. Rewrite each one so it fits "
            "max_len while keeping the meaning and the natural spoken tone. 'current' is the too-long version."
        )
    else:
        parts.append("Translate these lines:")
    parts.append(json.dumps(items, ensure_ascii=False))
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- providers

class ClaudeTranslator:
    def __init__(self, tcfg, context: dict | None = None):
        import anthropic

        self.anthropic = anthropic
        key = os.environ.get(tcfg.api_key_env) if tcfg.api_key_env else None
        self.client = anthropic.Anthropic(api_key=key, max_retries=4) if key else anthropic.Anthropic(max_retries=4)
        self.model = tcfg.model or "claude-opus-5-5"
        self.effort = tcfg.effort or "medium"
        self.system = build_system_prompt(tcfg, context)
        self.deadline: float | None = None      # time.time() phải xong trước lúc này (bước phụ như phân tích, xem analyze_video)

    def call(self, user: str, ids: list[int] | None = None) -> dict[int, str]:
        return parse_items(self.json_call(self.system, user, SCHEMA), ids)

    def json_call(self, system: str, user: str, schema: dict, max_tokens: int = 16000) -> dict:
        a = self.anthropic
        client = self.client
        if self.deadline is not None:
            left = self.deadline - time.time()
            if left < 3:
                raise TimeoutError("hết thời gian chờ AI")
            client = self.client.with_options(timeout=left, max_retries=1)
        try:
            resp = client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",   # nếu bị từ chối nhầm, server tự chạy lại trên model dự phòng
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
            )
        except a.AuthenticationError as e:
            raise RuntimeError("Claude API key không hợp lệ / chưa đặt ANTHROPIC_API_KEY") from e
        except a.BadRequestError as e:
            raise RuntimeError(f"Claude từ chối request: {e.message}") from e
        except a.APIConnectionError as e:
            raise RuntimeError("Không kết nối được Claude API (kiểm tra mạng/proxy)") from e
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"Claude từ chối dịch lô này ({getattr(resp.stop_details, 'category', None)})")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Hết max_tokens — giảm translate.batch_size")
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)


GEMINI_HOST = "generativelanguage.googleapis.com"
GEMINI_AUTO = "gemini-auto"      # trong cấu hình: để Studio566 tự chọn model Flash
GEMINI_FALLBACK = "gemini-3.5-flash"
GEMINI_PICK_TTL = 1800
_GEMINI_PICK: dict[tuple, tuple[float, str]] = {}


def gemini_flash_models(key: str) -> list[str]:
    """Các model Flash viết chữ mà key gọi được, mới nhất trước (bỏ bản lite, ảnh, giọng)."""
    import re
    import urllib.request
    req = urllib.request.Request(f"https://{GEMINI_HOST}/v1beta/models?pageSize=300", headers={"x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=20) as r:      # noqa: S310 — địa chỉ cố định của Google
        models = json.load(r).get("models") or []
    found = []
    for m in models:
        mm = re.fullmatch(r"models/(gemini-(\d+)(?:\.(\d+))?-flash)", m.get("name") or "")
        if mm and "generateContent" in (m.get("supportedGenerationMethods") or []):
            found.append(((int(mm.group(2)), int(mm.group(3) or 0)), mm.group(1)))
    return [name for _, name in sorted(found, reverse=True)]


def pick_gemini_flash(key: str, exclude: tuple = ()) -> str:
    """Model Flash mới nhất mà trả lời nhanh. Không ghi cứng tên: Google cho model cũ nghỉ hưu với key mới (gemini-2.5-flash trả 404 từ
    11/2026), còn model vừa ra thì có lúc quá tải (gemini-3.8-flash mất 89 giây cho 3 chữ trong khi 3.5 mất 1,6 giây). Hỏi thử ba
    model mới nhất cùng lúc bằng một câu rất ngắn, lấy model mới nhất trả lời dưới 8 giây. Nhớ kết quả 30 phút."""
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    ck = (key, exclude)
    hit = _GEMINI_PICK.get(ck)
    if hit and time.time() - hit[0] < GEMINI_PICK_TTL:
        return hit[1]
    try:
        names = [n for n in gemini_flash_models(key) if n not in exclude][:3]
    except (OSError, ValueError):
        names = []
    if not names:
        return GEMINI_FALLBACK
    from openai import OpenAI
    client = OpenAI(base_url=f"https://{GEMINI_HOST}/v1beta/openai/", api_key=key, max_retries=0, timeout=15)

    def probe(name):
        t0 = time.time()
        client.chat.completions.create(model=name, messages=[{"role": "user", "content": "Reply with: ok"}], max_tokens=5,
                                       reasoning_effort="none")
        return name, time.time() - t0
    took: dict[str, float] = {}
    pool = ThreadPoolExecutor(len(names))
    futs = [pool.submit(probe, n) for n in names]
    t_start = time.time()
    pending = set(futs)
    # chờ tới khi model mới nhất trả lời, hoặc quá 5 giây mà đã có model trả lời, hoặc quá 16 giây
    while pending and time.time() - t_start < 16:
        if names[0] in took or (took and time.time() - t_start >= 5):
            break
        try:
            f = next(as_completed(pending, timeout=max(0.1, (5 if took else 16) - (time.time() - t_start))))
        except TimeoutError:
            if took:
                break
            continue
        pending.discard(f)
        try:
            n, dt = f.result()
            took[n] = dt
        except Exception:      # noqa: BLE001 — model lỗi hay quá tải: bỏ qua, xét model khác
            pass
    pool.shutdown(wait=False, cancel_futures=True)
    quick = [n for n in names if took.get(n, 99) < 8]
    choice = quick[0] if quick else (min(took, key=took.get) if took else names[-1])
    log("translate", f"Gemini: dùng {choice}" + (f" (trả lời {took[choice]:.1f}s)" if choice in took else ""))
    _GEMINI_PICK[ck] = (time.time(), choice)
    return choice


class OpenAICompatTranslator:
    def __init__(self, tcfg, context: dict | None = None):
        from openai import OpenAI

        key = os.environ.get(tcfg.api_key_env or "OPENAI_API_KEY", "ollama")
        self.key = key
        self.gemini = GEMINI_HOST in (tcfg.base_url or "")
        # Gemini: tự thử lại ở _create (đổi model khi một model treo hay đã nghỉ hưu); nhà cung cấp khác để thư viện tự thử lại như cũ
        self.client = OpenAI(base_url=tcfg.base_url or None, api_key=key, max_retries=0 if self.gemini else 4, timeout=180 if self.gemini else 600)
        # "gemini-auto": chọn model lúc gọi thật, không phải lúc tạo (tạo chỉ để kiểm tra đã có AI chưa thì phải nhanh)
        self.model = GEMINI_AUTO if self.gemini and tcfg.model in ("", GEMINI_AUTO) else tcfg.model
        self.system = build_system_prompt(tcfg, context)
        # Gemini đời mới mặc định suy nghĩ rất lâu (viết kịch bản 60 giây mất 2 phút); dịch, viết kịch bản không cần
        self.extra = {"reasoning_effort": "none"} if self.gemini else {}
        self.tried: list[str] = []
        self.deadline: float | None = None      # time.time() phải xong trước lúc này (bước phụ như phân tích, xem analyze_video)

    def _client(self):
        """Client theo hạn chờ còn lại. Hết hạn thì TimeoutError: bước phụ bỏ qua thay vì bắt khách chờ cả chục phút khi Gemini
        quá tải (đo thật 2026-11-09: ba model lần lượt quá tải rồi một model treo đủ 180 giây, phân tích mất 341 giây)."""
        if self.deadline is None:
            return self.client
        left = self.deadline - time.time()
        if left < 3:
            raise TimeoutError("hết thời gian chờ AI")
        return self.client.with_options(timeout=left, max_retries=0 if self.gemini else 1)

    def call(self, user: str, ids: list[int] | None = None) -> dict[int, str]:
        return parse_items(self.json_call(self.system, user, SCHEMA), ids)

    def _switch(self, why: str) -> bool:
        """Đổi sang model Flash khác (model hiện tại nghỉ hưu hoặc quá tải). False nếu hết model để thử."""
        if not self.gemini or len(self.tried) >= 3:
            return False
        self.tried.append(self.model)
        new = pick_gemini_flash(self.key, exclude=tuple(self.tried))
        if new in self.tried:
            return False
        log("translate", f"Gemini {self.model} {why}, chuyển sang {new}")
        self.model = new
        return True

    def _create(self, **kw):
        if not self.gemini:
            return self._client().chat.completions.create(model=self.model, **kw, **self.extra)
        from openai import APIConnectionError, APITimeoutError, BadRequestError, InternalServerError, NotFoundError, RateLimitError
        if self.model == GEMINI_AUTO:
            self.model = pick_gemini_flash(self.key)
        busy = 0
        for attempt in range(6):
            try:
                return self._client().chat.completions.create(model=self.model, **kw, **self.extra)
            except NotFoundError:
                if not self._switch("không còn cho dùng"):
                    raise
            except APITimeoutError:
                if not self._switch("không trả lời kịp"):
                    raise
            except (RateLimitError, InternalServerError, APIConnectionError):
                # quá tải, giới hạn tần suất, rớt mạng: chờ rồi thử lại; lặp lại lần nữa thì đổi model (mỗi model có hạn mức riêng)
                busy += 1
                if busy >= 4 or attempt == 5:
                    raise
                if busy >= 2:
                    self._switch("đang quá tải")      # còn model khác thì đổi, hết thì thử lại model này
                wait = min(16, 2 ** busy)
                if self.deadline is not None:
                    wait = min(wait, max(0.0, self.deadline - time.time() - 3))
                time.sleep(wait)
            except BadRequestError as e:
                if not self.extra or "reasoning" not in str(e).lower():
                    raise
                self.extra = {}      # model không nhận reasoning_effort: gọi lại không có
        return self._client().chat.completions.create(model=self.model, **kw, **self.extra)

    def json_call(self, system: str, user: str, schema: dict, max_tokens: int = 16000) -> dict:
        r = self._create(
            messages=[{"role": "system", "content": system + "\n\nJSON schema of the answer: " + json.dumps(schema)},
                      {"role": "user", "content": user}],
            response_format={"type": "json_object"},
        )
        txt = r.choices[0].message.content or "{}"
        txt = txt.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        return json.loads(txt)


class GoogleFreeTranslator:
    def __init__(self, tcfg):
        from deep_translator import GoogleTranslator

        self.gt = GoogleTranslator(source="zh-CN", target=_langs.get(tcfg.target_lang)["google"])
        self.lang = tcfg.target_lang
        self.glossary = {str(k): str(v) for k, v in (tcfg.glossary or {}).items()}

    def call(self, user: str) -> dict[int, str]:  # không dùng prompt
        raise NotImplementedError

    def translate_items(self, items: list[dict]) -> dict[int, str]:
        """Gộp nhiều câu (cách nhau bởi xuống dòng) vào 1 request để tránh giới hạn 5 request/giây."""
        import time

        out: dict[int, str] = {}
        chunk: list[dict] = []

        def flush():
            if not chunk:
                return
            res = (self.gt.translate("\n".join(it["zh"] for it in chunk)) or "").split("\n")
            res = [r.strip() for r in res if r.strip()]
            if len(res) == len(chunk):
                out.update({it["id"]: r for it, r in zip(chunk, res)})
            else:  # Google gộp/tách dòng -> dịch từng câu
                for it in chunk:
                    out[it["id"]] = (self.gt.translate(it["zh"]) or "").strip()
                    time.sleep(0.3)
            chunk.clear()
            time.sleep(0.5)

        size = 0
        for it in items:
            if size + len(it["zh"]) > 1500:
                flush()
                size = 0
            chunk.append(it)
            size += len(it["zh"]) + 1
        flush()
        return out


class OfflineTranslator:
    """Dịch từng câu độc lập. Có chữ OCR gần giống lời nhận dạng thì dịch chữ OCR: sửa được lỗi đồng âm
    (智力/智利) mà model không có cách nào tự đoán ra vì không đọc cả video như các provider AI lớn."""

    def __init__(self, tcfg):
        from . import offline

        self.mt = offline
        self.model = tcfg.get("offline_model") or offline.MODEL
        self.lang = tcfg.target_lang
        self.glossary = {str(k): str(v) for k, v in (tcfg.glossary or {}).items()}
        if not offline.start(model=self.model):
            raise RuntimeError("connection refused: chưa bật được dịch offline")

    @staticmethod
    def source(it: dict) -> str:
        from difflib import SequenceMatcher

        zh, screen = it.get("zh", ""), it.get("screen", "")
        if screen and SequenceMatcher(None, zh.replace(" ", ""), screen.replace(" ", "")).ratio() >= 0.6:
            return screen
        return zh

    def one(self, it: dict) -> str:
        src = self.source(it)
        if not src.strip():
            return ""
        mt = self.mt
        fixed = mt.address_word(src, self.lang)
        if fixed:
            return fixed
        limit = max(64, len(src) * 8)
        prompt = mt.task_prompt(src, self.lang, self.glossary)
        out = mt.clean_output(mt.generate(prompt, self.model, max_tokens=limit), self.lang)
        if mt.looks_broken(out, src, self.lang):      # lệch hiếm gặp -> chạy lại không ngẫu nhiên
            again = mt.clean_output(mt.generate(prompt, self.model, temperature=0.0, max_tokens=limit), self.lang)
            if again and (not mt.looks_broken(again, src, self.lang) or not out):
                out = again
        return out

    def translate_items(self, items: list[dict]) -> dict[int, str]:
        out = {}
        for it in items:
            check_cancel()
            out[it["id"]] = self.one(it)
        return out

    def shorten_items(self, items: list[dict]) -> dict[int, str]:
        """Nhờ dịch ngắn hơn. Chỉ nhận khi thực sự ngắn hơn và không lộ câu lệnh."""
        out = {}
        mt = self.mt
        for it in items:
            check_cancel()
            src = self.source(it)
            new = mt.clean_output(mt.generate(mt.short_prompt(src, self.lang), self.model, max_tokens=max(64, len(src) * 8)), self.lang)
            cur = it.get("current", "")
            if new and not mt.looks_broken(new, src, self.lang) and count_units(new, self.lang) < count_units(cur, self.lang):
                out[it["id"]] = new
        return out


class McpTranslator:
    """AI qua MCP: gửi việc lên cổng MCP trung tâm của Studio566 (mcpcloud.py), Claude / ChatGPT / Grok lấy việc, làm, trả kết quả.
    Không cần API key. Chưa AI nào vào làm sau translate.mcp_wait giây thì báo lỗi để app dùng cách dịch dự phòng."""

    def __init__(self, tcfg, context: dict | None = None):
        from . import mcpcloud
        if not mcpcloud.configured():
            raise RuntimeError("Chưa kết nối AI qua MCP: vào Cài đặt > Kết nối AI dịch > AI qua MCP")
        self.mc = mcpcloud
        self.system = build_system_prompt(tcfg, context)
        self.wait = float(tcfg.get("mcp_wait") or 300)
        # chỉ hỏi Bắt đầu khi app tự chạy video trong hàng chờ; người dùng tự bấm (dịch lại câu, thử kết nối) thì gửi luôn
        self.confirm = bool(tcfg.get("mcp_confirm", True)) and threading.current_thread().name == "icontent-worker"
        self.deadline: float | None = None

    def call(self, user: str, ids: list[int] | None = None) -> dict[int, str]:
        title = f"Dịch {len(ids)} câu" if ids else "Dịch phụ đề"
        return parse_items(self.json_call(self.system, user, SCHEMA, title=title), ids)

    def json_call(self, system: str, user: str, schema: dict, max_tokens: int = 16000, title: str = "") -> dict:
        wait = self.wait
        if self.deadline is not None:
            wait = max(5.0, min(wait, self.deadline - time.time()))
        if not title:
            first = system.strip().splitlines()[0] if system.strip() else "Việc chữ"
            title = first[:80]
        res = self.mc.run_job(system, user, schema, title=title, wait=wait, confirm=self.confirm)
        if not isinstance(res, dict):
            raise RuntimeError("AI qua MCP trả kết quả không đúng dạng")
        return res


def make_translator(tcfg, context: dict | None = None):
    p = tcfg.provider
    if p == "mcp":
        return McpTranslator(tcfg, context)
    if p == "claude":
        return ClaudeTranslator(tcfg, context)
    if p == "openai":
        return OpenAICompatTranslator(tcfg, context)
    if p == "offline":
        return OfflineTranslator(tcfg)
    if p == "google":
        return GoogleFreeTranslator(tcfg)
    if p == "none":
        return None
    raise ValueError(f"translate.provider không hợp lệ: {p}")


# --------------------------------------------------------------------------- orchestration

def slot_of(segs: list[Segment], i: int, total: float) -> float:
    """Khoảng thời gian câu i được phép chiếm: tới đầu câu sau (tối đa cuối câu + 0.8s)."""
    s = segs[i]
    nxt = segs[i + 1].start if i + 1 < len(segs) else total
    return max(0.3, min(nxt, s.end + 0.8) - s.start - 0.05)


def max_len_for(slot: float, cfg) -> int:
    """Độ dài tối đa (theo đơn vị của ngôn ngữ đích) để đọc kịp trong khe thời gian. Tiếng Việt dùng tts.syllables_per_sec
    (chỉnh được trong cấu hình); ngôn ngữ khác dùng tốc độ đo trong langs.py."""
    lang = cfg.translate.target_lang
    rate = float(cfg.tts.syllables_per_sec) if lang == "vi" else float(_langs.get(lang)["rate"])
    return max(2, math.floor(slot * rate * 1.1))


def _fix_names(tr, items: list[dict], got: dict[int, str]) -> dict[int, str]:
    """Dịch offline và Google dịch từng câu nên hay để nguyên pinyin (Li Shimin): đổi về Hán-Việt, đối chiếu với câu gốc.
    Các dịch vụ AI lớn đã làm việc này khi đọc cả video."""
    if tr.lang != "vi":
        return got
    from .hanviet import fix_names

    by_id = {it["id"]: it for it in items}
    out = {}
    for k, v in got.items():
        it = by_id.get(k) or {}
        text = fix_names(it.get("zh", ""), v, tr.glossary)
        if it.get("screen"):      # chữ trên màn hình có khi đúng tên hơn lời nhận dạng
            text = fix_names(it["screen"], text, tr.glossary)
        out[k] = text
    return out


def _call_checked(tr, items: list[dict], title: str, prev: list[str], shorten: bool,
                  nxt: list[str] | None = None) -> dict[int, str]:
    if isinstance(tr, GoogleFreeTranslator):
        return _fix_names(tr, items, tr.translate_items(items)) if not shorten else {}
    if isinstance(tr, OfflineTranslator):
        return _fix_names(tr, items, tr.shorten_items(items) if shorten else tr.translate_items(items))
    want = {it["id"] for it in items}
    got = tr.call(_user_msg(items, title, prev, shorten, nxt), [it["id"] for it in items])
    missing = [it for it in items if not got.get(it["id"])]
    if missing and len(missing) < len(items):
        log("translate", f"Thiếu {len(missing)} câu, dịch lại phần thiếu")
        got.update(tr.call(_user_msg(missing, title, prev, shorten, nxt), [it["id"] for it in missing]))
    return {k: v for k, v in got.items() if k in want}


def _ctx_line(s: Segment, who: dict) -> str:
    return (f"{who[s.speaker]}: " if who.get(s.speaker) else "") + s.text


def _item(s: Segment, **kw) -> dict:
    d = {"id": s.id, "zh": s.text}
    if s.ocr and s.ocr.replace(" ", "") != s.text.replace(" ", ""):
        d["screen"] = s.ocr
    d.update(kw)
    return d


ANALYZE_BUDGET = 75      # giây. Thường mất 5-15 giây; quá hạn thì dịch luôn, không có bảng xưng hô


CAST_MAX_LINES = 500     # video quá nhiều câu: không bắt AI liệt kê người nói từng câu (câu trả lời quá dài)


def analyze_video(segs: list[Segment], cfg, meta: dict, cast: bool = False, cast_count: int = 0,
                  characters: str = "") -> dict | None:
    """Đọc toàn bộ lời thoại một lượt: tóm tắt, người nói, xưng hô, bảng tên riêng, bộ tiêu đề/caption/hashtag.
    cast=True: AI còn chia nhân vật và cho biết từng câu là của ai (lồng mỗi nhân vật một giọng).
    cast_count: số nhân vật người dùng nhập (0 = để AI tự đếm)."""
    tc = cfg.translate
    if tc.provider not in ("claude", "openai", "mcp") or not tc.analyze:
        return None
    tr = make_translator(tc)
    lang = LANG_NAMES.get(tc.target_lang, tc.target_lang)
    cast = cast and 0 < len(segs) <= CAST_MAX_LINES
    lines = [_item(s, t=round(s.start, 1), **({"v": s.speaker} if cast and s.speaker else {})) for s in segs]
    schema, system = ANALYZE_SCHEMA, ANALYZE_SYSTEM
    if cast:
        schema = dict(ANALYZE_SCHEMA, properties=dict(ANALYZE_SCHEMA["properties"], **CAST_SCHEMA),
                      required=ANALYZE_SCHEMA["required"] + list(CAST_SCHEMA))
        count_rule = (f" The video has exactly {cast_count} speaking characters (the user counted them): return exactly "
                      f"{cast_count} cast entries.") if cast_count > 0 else ""
        if characters.strip():
            count_rule += (" The user who knows this video listed its speaking characters (name, and what they are): "
                           + json.dumps(characters.strip(), ensure_ascii=False)
                           + ". Use exactly these characters and these names in cast (gender as the user says), do not add "
                           "others; they are the ground truth about who is who (e.g. which one is an animal).")
        system = ANALYZE_SYSTEM.replace("\nRespond with JSON only.",
                                        CAST_RULES.replace("{count_rule}", count_rule) + "\nRespond with JSON only.")
    user = (f"Video title: {meta.get('title', '')}\n"
            + (f"Description: {meta.get('description', '')[:500]}\n" if meta.get("description") else "")
            + f"Duration: {meta.get('duration', 0):.0f}s\n\nTranscript:\n" + json.dumps(lines, ensure_ascii=False))
    log("analyze", f"Phân tích nội dung + xưng hô ({tc.provider}) ...")
    if tc.provider != "mcp":      # qua MCP: người dùng phải mở AI và nhắn, cho chờ đủ translate.mcp_wait
        tr.deadline = time.time() + ANALYZE_BUDGET      # bước phụ: AI quá tải thì bỏ qua sau ít phút, không bắt khách chờ
    if tc.provider == "mcp":
        data = tr.json_call(system.format(lang=lang), user, schema, max_tokens=16000 if cast else 8000,
                            title="Phân tích video: nhân vật, xưng hô, tiêu đề, hashtag")
    else:
        data = tr.json_call(system.format(lang=lang), user, schema, max_tokens=16000 if cast else 8000)
    log("analyze", f"{data.get('genre', '')}: {data.get('summary', '')[:120]}")
    return data


def translate_segments(segs: list[Segment], cfg, meta: dict, only: set[int] | None = None,
                       context: dict | None = None) -> list[Segment]:
    """Dịch toàn bộ, hoặc chỉ các id trong `only` (giữ nguyên câu đã sửa tay)."""
    tr = make_translator(cfg.translate, context)
    if tr is None:
        return segs
    total = float(meta.get("duration") or (segs[-1].end if segs else 0))
    title = meta.get("title", "")
    who = dict((context or {}).get("_who") or {}) if not isinstance(tr, (OfflineTranslator, GoogleFreeTranslator)) else {}
    # dịch offline đi từng câu một -> lô nhỏ để thanh tiến độ chạy đều
    bs = 5 if isinstance(tr, OfflineTranslator) else int(cfg.translate.batch_size)
    todo = [i for i, s in enumerate(segs) if only is None or s.id in only]
    for b in range(0, len(todo), bs):
        idxs = todo[b:b + bs]
        items = [_item(segs[i], max_len=max_len_for(slot_of(segs, i, total), cfg),
                       **({"who": who[segs[i].speaker]} if who.get(segs[i].speaker) else {})) for i in idxs]
        first, last = idxs[0], idxs[-1]
        prev = [_ctx_line(p, who) + f" => {p.trans}" for p in segs[max(0, first - 4):first] if p.trans]
        nxt = [_ctx_line(p, who) for p in segs[last + 1:last + 4]]
        log("translate", f"Dịch câu {b + 1}-{b + len(idxs)} / {len(todo)} ({cfg.translate.provider})")
        progress("translate", b / max(1, len(todo)))
        check_cancel()
        res = _call_checked(tr, items, title, prev, shorten=False, nxt=nxt)
        for i in idxs:
            segs[i].trans = res.get(segs[i].id, segs[i].trans)
    return segs


def shorten_segments(segs: list[Segment], targets: dict[int, int], cfg, meta: dict,
                     context: dict | None = None) -> dict[int, str]:
    """targets: {id: max_len}. Trả về {id: bản dịch ngắn hơn}."""
    tr = make_translator(cfg.translate, context)
    if tr is None or isinstance(tr, GoogleFreeTranslator) or not targets:
        return {}
    by_id = {s.id: s for s in segs}
    items = [{"id": i, "zh": by_id[i].text, "current": by_id[i].trans, "max_len": n} for i, n in targets.items()]
    if isinstance(tr, OfflineTranslator):
        for it in items:
            it.update({k: v for k, v in _item(by_id[it["id"]]).items() if k == "screen"})
    out: dict[int, str] = {}
    bs = int(cfg.translate.batch_size)
    for b in range(0, len(items), bs):
        out.update(_call_checked(tr, items[b:b + bs], meta.get("title", ""), [], shorten=True))
    return out


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}

REVIEW_SYSTEM = """You are the editor of a {lang} voice-over dub of a Chinese short video. The whole script is already translated line by line; read it from start to end like a viewer would hear it and fix what is wrong.

Each line has: id, zh (speech recognition, may contain misheard words), screen (the burned-in subtitle when it differs, usually more reliable), who (the character speaking, when known), max_len (comfortable length in {unit}) and tr (the current translation).

Fix only real problems:
- wrong meaning, a word-for-word rendering of an idiom or set phrase, a sentence that makes no sense when heard;
- forms of address / pronouns that are wrong for who is talking to whom or that change between lines without reason;
- a line cut down to a fragment, or two neighbouring lines that only make sense when read together but sound broken;
- names that do not follow the glossary.
Keep each line its own line (never move meaning between ids), keep it about max_len (at most ~25% over), keep the natural spoken tone. Do not touch lines that are fine.
Return {{"items": [...]}} with ONLY the lines you changed, each {{"id", "text"}} where text is the full new translation. Return an empty list if everything is fine.
Respond with JSON only."""

REVIEW_CHUNK = 150


def review_translation(segs: list[Segment], cfg, meta: dict, context: dict | None, ids: set[int]) -> int:
    """Dịch xong: AI đọc lại cả bản dịch một lượt, sửa câu sai nghĩa, xưng hô lệch, câu cụt. Chỉ sửa câu trong `ids`
    (câu vừa dịch, không đụng câu người dùng đã sửa tay). Trả về số câu đã sửa."""
    tc = cfg.translate
    if tc.provider not in ("claude", "openai", "mcp") or not ids:
        return 0
    tr = make_translator(tc, context)
    lang = LANG_NAMES.get(tc.target_lang, tc.target_lang)
    who = dict((context or {}).get("_who") or {})
    total = float(meta.get("duration") or (segs[-1].end if segs else 0))
    system = REVIEW_SYSTEM.format(lang=lang, unit=_langs.unit_words(tc.target_lang))
    gloss = {g["zh"]: g["vi"] for g in (context or {}).get("glossary") or [] if g.get("zh") and g.get("vi")}
    gloss.update(dict(tc.glossary or {}))
    if (context or {}).get("pronouns"):
        system += "\n\nForms of address to use: " + context["pronouns"]
    if gloss:
        system += "\nGlossary: " + json.dumps(gloss, ensure_ascii=False)
    lines = []
    for i, s in enumerate(segs):
        d = _item(s, max_len=max_len_for(slot_of(segs, i, total), cfg), tr=s.trans)
        if who.get(s.speaker):
            d["who"] = who[s.speaker]
        lines.append(d)
    changed = 0
    for b in range(0, len(lines), REVIEW_CHUNK):
        part = lines[b:b + REVIEW_CHUNK]
        if not any(x["id"] in ids for x in part):
            continue
        check_cancel()
        user = f"Video title: {meta.get('title', '')}\n\nScript:\n" + json.dumps(part, ensure_ascii=False)
        log("translate", f"AI đọc lại bản dịch câu {b + 1}-{b + len(part)} để sửa xưng hô, câu sai nghĩa ...")
        if tc.provider == "mcp":
            data = tr.json_call(system, user, REVIEW_SCHEMA, max_tokens=16000, title="Soát lại bản dịch")
        else:
            tr.deadline = time.time() + ANALYZE_BUDGET * 2
            data = tr.json_call(system, user, REVIEW_SCHEMA, max_tokens=16000)
        by_id = {s.id: s for s in segs}
        for x in (data or {}).get("items") or []:
            try:
                k, text = int(x.get("id")), str(x.get("text") or "").strip()
            except (TypeError, ValueError):
                continue
            if k in ids and k in by_id and text and text != by_id[k].trans:
                by_id[k].trans = text
                changed += 1
    log("translate", f"Soát lại xong: sửa {changed} câu" if changed else "Soát lại xong: bản dịch ổn, không phải sửa")
    return changed
