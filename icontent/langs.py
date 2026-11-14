"""Ngôn ngữ đích (thị trường) iContent hỗ trợ: dịch, đo độ dài câu, giọng đọc, phụ đề.

Một bảng duy nhất cho mọi nơi cần biết về ngôn ngữ đích, để thêm thị trường mới chỉ phải thêm một dòng.
  unit   cách đếm độ dài câu để đọc kịp trong khe thời gian: "syllable" (tiếng Việt, mỗi âm tiết cách nhau dấu cách),
         "word" (ngôn ngữ có dấu cách giữa các từ), "char" (Thái, Nhật, Hàn, Khmer, Myanmar: đếm ký tự không kể dấu cách, dấu câu)
  rate   số đơn vị nói được mỗi giây ở nhịp người dẫn video ngắn, để giới hạn độ dài bản dịch (giọng đọc vẫn tự co giãn,
         rút gọn câu nếu không kịp). Đo 11/2026 trên giọng VoxCPM2 (56 câu, 14 thứ tiếng) rồi lấy khoảng 90% cho an toàn;
         de, it, tr, pl, nl, km, my, he chưa đo, ước theo ngôn ngữ gần
  mt     tên tiếng Trung dùng trong lời nhắn của Hy-MT2 (dịch offline); trống = dịch offline không hỗ trợ
  google mã ngôn ngữ của Google dịch (Hebrew là "iw", Filipino là "tl")
  edge   giọng Microsoft (edge-tts, qua mạng): (locale, giọng nam, giọng nữ)
  vox    có giọng đọc trên máy (VoxCPM2, xem voxtts.py). Khmer, Myanmar: VoxCPM2 có hỗ trợ nhưng chưa kiểm chứng được (Whisper nghe lại
         hai thứ tiếng này ra chữ vô nghĩa, không biết lỗi ở giọng đọc hay ở Whisper) nên dùng giọng Microsoft
"""
from __future__ import annotations

import re
import unicodedata

LANGS: dict[str, dict] = {}


def _add(code, vi, en, mt, unit, rate, google, edge, vox=True, market=""):
    LANGS[code] = {"code": code, "vi": vi, "en": en, "mt": mt, "unit": unit, "rate": rate, "google": google,
                   "edge": edge, "vox": vox, "market": market}


# thứ tự = thứ tự hiện trong giao diện: thị trường khách hay làm nhất trước
_add("vi", "Tiếng Việt", "Vietnamese", "越南语", "syllable", 5.0, "vi", ("vi-VN", "NamMinhNeural", "HoaiMyNeural"), vox=False, market="Việt Nam")
_add("en", "Tiếng Anh", "English", "英语", "word", 3.1, "en", ("en-US", "AndrewNeural", "AvaNeural"), market="Mỹ, Anh, Úc, Philippines...")
_add("id", "Tiếng Indonesia", "Indonesian", "印尼语", "word", 2.5, "id", ("id-ID", "ArdiNeural", "GadisNeural"), market="Indonesia")
_add("th", "Tiếng Thái", "Thai", "泰语", "char", 9.0, "th", ("th-TH", "NiwatNeural", "PremwadeeNeural"), market="Thái Lan")
_add("tl", "Tiếng Philippines", "Filipino (Tagalog)", "菲律宾语", "word", 2.9, "tl", ("fil-PH", "AngeloNeural", "BlessicaNeural"), market="Philippines")
_add("ms", "Tiếng Malaysia", "Malay", "马来语", "word", 3.0, "ms", ("ms-MY", "OsmanNeural", "YasminNeural"), market="Malaysia, Singapore, Brunei")
_add("es", "Tiếng Tây Ban Nha", "Spanish", "西班牙语", "word", 3.3, "es", ("es-MX", "JorgeNeural", "DaliaNeural"), market="Mỹ Latin, Tây Ban Nha, Mỹ")
_add("pt", "Tiếng Bồ Đào Nha", "Portuguese (Brazil)", "葡萄牙语", "word", 3.0, "pt", ("pt-BR", "AntonioNeural", "FranciscaNeural"), market="Brazil, Bồ Đào Nha")
_add("ja", "Tiếng Nhật", "Japanese", "日语", "char", 4.5, "ja", ("ja-JP", "KeitaNeural", "NanamiNeural"), market="Nhật Bản")
_add("ko", "Tiếng Hàn", "Korean", "韩语", "char", 5.3, "ko", ("ko-KR", "InJoonNeural", "SunHiNeural"), market="Hàn Quốc")
_add("hi", "Tiếng Hindi", "Hindi", "印地语", "word", 2.7, "hi", ("hi-IN", "MadhurNeural", "SwaraNeural"), market="Ấn Độ")
_add("ar", "Tiếng Ả Rập", "Arabic", "阿拉伯语", "word", 2.1, "ar", ("ar-SA", "HamedNeural", "ZariyahNeural"), market="Trung Đông, Bắc Phi")
_add("fr", "Tiếng Pháp", "French", "法语", "word", 4.2, "fr", ("fr-FR", "HenriNeural", "DeniseNeural"), market="Pháp, Canada, châu Phi")
_add("de", "Tiếng Đức", "German", "德语", "word", 2.6, "de", ("de-DE", "ConradNeural", "KatjaNeural"), market="Đức, Áo, Thụy Sĩ")
_add("ru", "Tiếng Nga", "Russian", "俄语", "word", 2.5, "ru", ("ru-RU", "DmitryNeural", "SvetlanaNeural"), market="Nga, Đông Âu")
_add("it", "Tiếng Ý", "Italian", "意大利语", "word", 3.1, "it", ("it-IT", "DiegoNeural", "ElsaNeural"), market="Ý")
_add("tr", "Tiếng Thổ Nhĩ Kỳ", "Turkish", "土耳其语", "word", 2.4, "tr", ("tr-TR", "AhmetNeural", "EmelNeural"), market="Thổ Nhĩ Kỳ")
_add("pl", "Tiếng Ba Lan", "Polish", "波兰语", "word", 2.5, "pl", ("pl-PL", "MarekNeural", "ZofiaNeural"), market="Ba Lan")
_add("nl", "Tiếng Hà Lan", "Dutch", "荷兰语", "word", 3.0, "nl", ("nl-NL", "MaartenNeural", "ColetteNeural"), market="Hà Lan, Bỉ")
_add("km", "Tiếng Khmer", "Khmer", "高棉语", "char", 8.0, "km", ("km-KH", "PisethNeural", "SreymomNeural"), market="Campuchia", vox=False)
_add("my", "Tiếng Myanmar", "Burmese", "缅甸语", "char", 8.0, "my", ("my-MM", "ThihaNeural", "NilarNeural"), market="Myanmar", vox=False)
_add("he", "Tiếng Do Thái", "Hebrew", "希伯来语", "word", 2.6, "iw", ("he-IL", "AvriNeural", "HilaNeural"), market="Israel")


def get(code: str) -> dict:
    """Thông tin một ngôn ngữ; mã lạ (cấu hình cũ, gõ tay) vẫn chạy với giá trị an toàn."""
    return LANGS.get(code) or {"code": code, "vi": code, "en": code, "mt": "", "unit": "word", "rate": 2.6, "google": code,
                               "edge": None, "vox": False, "market": ""}


def name_en(code: str) -> str:
    return get(code)["en"]


def name_vi(code: str) -> str:
    return get(code)["vi"]


_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)


def count_units(text: str, code: str) -> int:
    """Độ dài câu theo đơn vị đọc của ngôn ngữ đó (xem 'unit')."""
    unit = get(code)["unit"]
    if unit in ("syllable", "word"):
        return len(text.split())
    # chữ không cách từ: đếm ký tự, bỏ dấu câu, dấu cách và dấu phụ đứng riêng (dấu thanh Thái, nguyên âm kết hợp)
    return sum(1 for ch in text if not _PUNCT.match(ch) and unicodedata.category(ch) not in ("Mn", "Mc"))


def unit_words(code: str) -> str:
    """Tên đơn vị đếm để ghi trong lời nhắn cho AI dịch."""
    unit = get(code)["unit"]
    return {"syllable": "syllables (one syllable = one space-separated word)", "word": "words"}.get(unit, "characters (not counting spaces and punctuation)")


def edge_voice(code: str, gender: str) -> str:
    e = get(code)["edge"]
    if not e:
        return ""
    loc, male, female = e
    return f"{loc}-{male if gender == 'male' else female}"


def edge_locale(code: str) -> str:
    e = get(code)["edge"]
    return e[0] if e else ""


def public() -> list[dict]:
    """Danh sách cho giao diện: mã, tên tiếng Việt, thị trường, có dịch offline / giọng trên máy không."""
    return [{"code": c, "name": v["vi"], "en": v["en"], "market": v["market"], "offline_mt": bool(v["mt"]), "vox": v["vox"],
             "edge": bool(v["edge"]), "edge_locale": edge_locale(c), "edge_male": edge_voice(c, "male"), "edge_female": edge_voice(c, "female")}
            for c, v in LANGS.items()]


# câu nghe thử giọng (nút Nghe thử): ngắn, tự nhiên, đúng ngôn ngữ của giọng
SAMPLES = {
    "vi": "Xin chào, đây là giọng đọc thử của iContent Studio.",
    "en": "Hi there, this is a voice preview from iContent Studio.",
    "id": "Halo, ini contoh suara dari iContent Studio.",
    "th": "สวัสดีค่ะ นี่คือเสียงตัวอย่างจาก iContent Studio",
    "tl": "Hello, ito ang sample na boses mula sa iContent Studio.",
    "ms": "Hai, ini contoh suara daripada iContent Studio.",
    "es": "Hola, esta es una muestra de voz de iContent Studio.",
    "pt": "Olá, esta é uma amostra de voz do iContent Studio.",
    "ja": "こんにちは。これは iContent Studio の音声サンプルです。",
    "ko": "안녕하세요, iContent Studio의 음성 샘플입니다.",
    "hi": "नमस्ते, यह iContent Studio की आवाज़ का नमूना है।",
    "ar": "مرحبا، هذا نموذج صوتي من آي كونتنت ستوديو.",
    "fr": "Bonjour, ceci est un aperçu de voix d'iContent Studio.",
    "de": "Hallo, das ist eine Stimmprobe von iContent Studio.",
    "ru": "Привет, это пример голоса из iContent Studio.",
    "it": "Ciao, questo è un esempio di voce di iContent Studio.",
    "tr": "Merhaba, bu iContent Studio'dan bir ses örneğidir.",
    "pl": "Cześć, to jest próbka głosu z iContent Studio.",
    "nl": "Hallo, dit is een stemvoorbeeld van iContent Studio.",
    "km": "សួស្តី នេះជាសំឡេងគំរូពី iContent Studio។",
    "my": "မင်္ဂလာပါ၊ ဒါက iContent Studio ရဲ့ အသံနမူနာပါ။",
    "he": "שלום, זו דוגמת קול של iContent Studio.",
}


def sample(code: str) -> str:
    return SAMPLES.get(code) or SAMPLES["en"]
