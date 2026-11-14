"""Đổi tên riêng còn để pinyin sang Hán-Việt. Dịch offline và Google hay trả "Li Shimin" thay vì "Lý Thế Dân", vì chúng dịch từng
câu và không có bước đọc cả video như các dịch vụ AI lớn.

Cách làm: tìm cụm từ viết hoa trong bản dịch, thử khớp với các chữ Hán đứng cạnh nhau trong câu gốc. Khớp thì đổi. Quy tắc phải chặt, vì
đổi nhầm một câu tiếng Việt bình thường còn tệ hơn để sót một cái tên:
  - từ không dấu (Li, Shimin) so với pinyin không dấu, được phép gồm nhiều âm tiết
  - từ có dấu (Chén, Hạo) chỉ khớp khi đúng từng dấu với pinyin có thanh hoặc với âm Hán-Việt. Nếu bỏ dấu ra so thì "Xin chào" thành 新潮,
    "Đang đi" thành 当地, "Cái này" thành 才
  - mọi âm trong tên đều phải viết hoa, nên từ thường đứng sau không bị nuốt vào tên
  - phải có ít nhất một âm còn là pinyin; toàn âm Hán-Việt thì đã đúng, chữ Hán còn sót một mình không đổi
  - một âm tiết rất dễ trùng từ thường ("Fan", "Sun", "You"), chỉ đổi khi đó là họ và có ngữ cảnh rõ: ông Zhao, 赵总, 老王

Âm Hán-Việt trong data/hanviet.tsv do người viết, không lấy từ trường kVietnamese của Unihan vì trường đó lẫn âm Nôm (徐 ra "chờ",
强 ra "càng"). Gặp chữ không có trong bảng thì giữ nguyên pinyin: để nguyên còn hơn đoán sai tên người.
"""
from __future__ import annotations

import re
import threading
import unicodedata
from pathlib import Path

DATA = Path(__file__).parent / "data" / "hanviet.tsv"

# họ hai chữ, địa danh, nhân vật quen thuộc: cách đọc đã thành quen, không suy ra được từ từng chữ (重庆 không đọc Trọng Khánh)
WORDS = {
    "诸葛": "Gia Cát", "欧阳": "Âu Dương", "司马": "Tư Mã", "上官": "Thượng Quan", "东方": "Đông Phương", "独孤": "Độc Cô", "慕容": "Mộ Dung", "皇甫": "Hoàng Phủ",
    "令狐": "Lệnh Hồ", "南宫": "Nam Cung", "夏侯": "Hạ Hầu", "公孙": "Công Tôn", "尉迟": "Uất Trì", "司徒": "Tư Đồ", "诸葛亮": "Gia Cát Lượng",
    "北京": "Bắc Kinh", "上海": "Thượng Hải", "天津": "Thiên Tân", "重庆": "Trùng Khánh", "广州": "Quảng Châu", "深圳": "Thâm Quyến", "杭州": "Hàng Châu", "南京": "Nam Kinh",
    "苏州": "Tô Châu", "西安": "Tây An", "武汉": "Vũ Hán", "成都": "Thành Đô", "长沙": "Trường Sa", "郑州": "Trịnh Châu", "青岛": "Thanh Đảo", "大连": "Đại Liên",
    "沈阳": "Thẩm Dương", "哈尔滨": "Cáp Nhĩ Tân", "昆明": "Côn Minh", "贵阳": "Quý Dương", "南宁": "Nam Ninh", "桂林": "Quế Lâm", "厦门": "Hạ Môn", "福州": "Phúc Châu",
    "合肥": "Hợp Phì", "济南": "Tế Nam", "太原": "Thái Nguyên", "石家庄": "Thạch Gia Trang", "兰州": "Lan Châu", "香港": "Hồng Kông", "澳门": "Ma Cao", "台湾": "Đài Loan",
    "台北": "Đài Bắc", "河南": "Hà Nam", "河北": "Hà Bắc", "山东": "Sơn Đông", "山西": "Sơn Tây", "陕西": "Thiểm Tây", "四川": "Tứ Xuyên", "云南": "Vân Nam", "贵州": "Quý Châu",
    "广东": "Quảng Đông", "广西": "Quảng Tây", "湖南": "Hồ Nam", "湖北": "Hồ Bắc", "江苏": "Giang Tô", "浙江": "Chiết Giang", "安徽": "An Huy", "福建": "Phúc Kiến", "江西": "Giang Tây",
    "海南": "Hải Nam", "吉林": "Cát Lâm", "辽宁": "Liêu Ninh", "黑龙江": "Hắc Long Giang", "甘肃": "Cam Túc", "青海": "Thanh Hải", "宁夏": "Ninh Hạ", "内蒙古": "Nội Mông",
    "新疆": "Tân Cương", "西藏": "Tây Tạng", "中国": "Trung Quốc", "长安": "Trường An", "洛阳": "Lạc Dương", "开封": "Khai Phong", "敦煌": "Đôn Hoàng", "少林": "Thiếu Lâm", "武当": "Võ Đang",
    "曹操": "Tào Tháo", "刘备": "Lưu Bị", "关羽": "Quan Vũ", "张飞": "Trương Phi", "孙悟空": "Tôn Ngộ Không", "猪八戒": "Trư Bát Giới", "沙僧": "Sa Tăng", "唐僧": "Đường Tăng",
    "李世民": "Lý Thế Dân", "武则天": "Võ Tắc Thiên", "秦始皇": "Tần Thủy Hoàng", "毛泽东": "Mao Trạch Đông", "孔子": "Khổng Tử", "老子": "Lão Tử", "孟子": "Mạnh Tử", "李白": "Lý Bạch",
    "杜甫": "Đỗ Phủ", "苏轼": "Tô Thức", "成龙": "Thành Long", "李小龙": "Lý Tiểu Long", "周星驰": "Châu Tinh Trì", "周杰伦": "Châu Kiệt Luân", "刘德华": "Lưu Đức Hoa", "张学友": "Trương Học Hữu",
    "马云": "Mã Vân", "包青天": "Bao Thanh Thiên", "周润发": "Châu Nhuận Phát",
}
# tên tiếng Anh mà model hay dùng cho người nổi tiếng. Chỉ đổi khi câu gốc đúng là người đó
ENGLISH = {"Andy Lau": "刘德华", "Jackie Chan": "成龙", "Jet Li": "李连杰", "Bruce Lee": "李小龙", "Stephen Chow": "周星驰", "Jack Ma": "马云", "Jay Chou": "周杰伦", "Chow Yun-fat": "周润发",
           "Chow Yun Fat": "周润发", "Tony Leung": "梁朝伟", "Donnie Yen": "甄子丹"}
WORDS.update({"李连杰": "Lý Liên Kiệt", "梁朝伟": "Lương Triều Vỹ", "甄子丹": "Chân Tử Đan"})
# thương hiệu người Việt đã quen gọi bằng pinyin: đọc Hán-Việt ("Tiểu Mễ") sẽ không ai hiểu
KEEP = {"xiaomi", "huawei", "taobao", "douyin", "weibo", "baidu", "alibaba", "pinduoduo", "meituan", "bilibili", "kuaishou", "xiaohongshu", "weixin", "wechat", "alipay", "zhifubao", "jingdong",
        "didi", "moutai", "haier", "geely", "chery", "wuling", "yangwang", "tencent", "shein", "temu", "oppo", "vivo", "honor", "lenovo", "dongfeng", "nio", "xpeng", "liauto", "tmall", "ctrip", "tiktok"}
# tên nước ngoài được câu gốc phiên âm: 安娜 là Anna, không phải "An Na". Chỉ xét khi viết liền một từ, vì "Li Na" (李娜) vẫn phải đổi
FOREIGN = {"anna", "anne", "lisa", "lina", "mina", "nina", "tina", "sara", "maria", "mali", "nana", "lili", "lucy", "lucas", "dina", "kala", "mila"}
_LATIN = "A-Za-z\u00c0-\u024f\u1e00-\u1eff"
_WORD = re.compile(rf"[{_LATIN}]+(?:['’][{_LATIN}]+)*|[\u4e00-\u9fff]")      # Chang'an là một từ, pinyin dùng dấu nháy để tách âm
SURNAMES = set("李王张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖萧田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付傅方白邹孟熊秦邱丘江尹薛闫阎段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤康易乔赖文施洪辛柳凌欧司裴骆蓝甘牛关岳庞樊兰殷鲁葛翟聂倪章鲍温季涂齐童耿管蒙华柯左申祝宁项时安苗谷米穆颜盛卓舒屈阮姬虞柴包霍窦伍褚娄尤纪连詹邢燕卫楚梅")
TITLES_VI = {"ông", "bà", "anh", "chị", "cô", "chú", "bác", "cậu", "thầy", "sếp", "tổng", "đốc", "họ", "nhà", "tộc", "lão", "tiểu", "em", "cháu", "dì", "mợ", "thím", "ngài"}
TITLES_ZH = ("总", "老师", "先生", "女士", "小姐", "经理", "董事", "师傅", "医生", "主任", "老板", "队长", "局长", "导演", "律师", "教授", "同学", "警官", "阿姨", "大爷", "大哥", "大姐", "部长", "院长",
             "校长", "村长", "书记", "将军", "公子", "夫人", "太太", "姑娘", "少爷", "家", "哥", "姐", "叔", "伯", "爷")
MAX_WORDS = 5

_lock = threading.Lock()
_table: dict[str, tuple[str, list[str], list[str]]] | None = None


def _load() -> dict[str, tuple[str, list[str], list[str]]]:
    """chữ -> (âm Hán-Việt, các pinyin không dấu, các pinyin có dấu thanh)"""
    global _table
    with _lock:
        if _table is None:
            t: dict[str, tuple[str, list[str], list[str]]] = {}
            if DATA.exists():
                for line in DATA.read_text(encoding="utf-8").splitlines():
                    if line and not line.startswith("#"):
                        c, r, plain, tone = line.split("\t")
                        t[c] = (r, plain.split("|"), tone.split("|"))
            _table = t
    return _table


def _is_han(w: str) -> bool:
    return "\u4e00" <= w[0] <= "\u9fff"


def _letters(s: str) -> str:
    """Từ không dấu -> dạng so với pinyin. Pinyin viết v (Lv) quy về u."""
    return s.lower().replace("v", "u")


def _word_end(word: str, zh: str, i: int) -> list[tuple[int, bool]]:
    """Một từ khớp với những chữ Hán nào bắt đầu từ vị trí i. -> [(vị trí kết thúc, có phải pinyin không)]."""
    if i >= len(zh):
        return []
    if _is_han(word):       # chữ Hán còn sót trong bản dịch ("范 Xian")
        return [(i + 1, False)] if word == zh[i] else []
    table = _load()
    entry = table.get(zh[i])
    word = word.replace("'", "").replace("’", "")
    low = unicodedata.normalize("NFC", word).lower()
    out: list[tuple[int, bool]] = []
    if entry and entry[0] and low == entry[0].lower():
        out.append((i + 1, False))
    if not word.isascii():
        if entry and low in entry[2]:
            out.append((i + 1, True))
        return out

    def walk(j: int, rest: str) -> None:
        if not rest:
            out.append((j, True))
            return
        if j < len(zh) and zh[j] in table:
            for py in table[zh[j]][1]:
                if rest.startswith(py):
                    walk(j + 1, rest[len(py):])

    walk(i, _letters(word))
    return out


def _align(words: list[str], zh: str, i: int) -> tuple[int, bool] | None:
    """Các từ liên tiếp khớp với các chữ Hán liên tiếp. -> (vị trí kết thúc, có từ nào còn là pinyin không)."""
    if not words:
        return i, False
    for end, is_pinyin in _word_end(words[0], zh, i):
        rest = _align(words[1:], zh, end)
        if rest:
            return rest[0], is_pinyin or rest[1]
    return None


def _surname_in_context(zh: str, i: int, prev_word: str) -> bool:
    """Một âm tiết: chỉ tin khi đó là họ và có dấu hiệu rõ đang gọi người."""
    if zh[i] not in SURNAMES:
        return False
    if prev_word.lower() in TITLES_VI:
        return True
    return (i > 0 and zh[i - 1] in "老小阿") or zh[i + 1:].startswith(TITLES_ZH)


def reading(name: str) -> str:
    """Chữ Hán -> Hán-Việt viết hoa từng âm. Trống nếu có chữ chưa có âm trong bảng."""
    if name in WORDS:
        return WORDS[name]
    table = _load()
    out: list[str] = []
    i = 0
    while i < len(name):
        hit = next((name[i:j] for j in range(min(len(name), i + 4), i + 1, -1) if name[i:j] in WORDS), None)
        if hit:
            out.append(WORDS[hit])
            i += len(hit)
            continue
        if name[i] not in table or not table[name[i]][0]:
            return ""
        out.append(table[name[i]][0])
        i += 1
    return " ".join(out)


def _convert(words: list[str], zh: str, glossary: dict[str, str] | None, prev_word: str = "") -> tuple[int, str] | None:
    """Thử cụm dài nhất bắt đầu từ từ đầu tiên. -> (số từ được đổi, Hán-Việt)."""
    if not (words[0][0].isupper() or _is_han(words[0])):
        return None
    for k in range(min(len(words), MAX_WORDS), 0, -1):
        part = words[:k]
        # mọi âm đều viết hoa; chữ Hán sót chỉ tính khi đứng trước một âm La-tinh ("范 Xian"), không ăn sang chữ phía sau tên
        if _is_han(part[-1]) or any(not (w[0].isupper() or _is_han(w)) for w in part):
            continue
        joined = "".join(part).replace("'", "").replace("’", "")
        if joined.isascii() and (_letters(joined) in KEEP or (k == 1 and _letters(joined) in FOREIGN)):
            return None
        unknown = False
        for i in range(len(zh)):
            got = _align(part, zh, i)
            if not got or not got[1]:
                continue
            end = got[0]
            if end - i == 1 and not _surname_in_context(zh, i, prev_word):
                continue
            name = zh[i:end]
            vi = (glossary or {}).get(name) or reading(name)
            if vi:
                return k, vi
            unknown = True
        # tên viết hoa có chữ chưa có âm: giữ nguyên cả tên, không đổi nửa vời kiểu "Phó Cảnh Shen". Phần đuôi là chữ Hán sót thì thử bớt
        if unknown and part[-1][0].isupper():
            return None
    return None


def fix_names(zh: str, text: str, glossary: dict[str, str] | None = None) -> str:
    """Đổi các tên còn để pinyin trong bản dịch tiếng Việt, đối chiếu với câu gốc."""
    if not zh or not text or not _load():
        return text
    for en, han in ENGLISH.items():
        if en in text and han in zh and reading(han):
            text = text.replace(en, reading(han))
    spans = [(m.start(), m.end(), m.group(0)) for m in _WORD.finditer(text)]
    out: list[str] = []
    pos = 0
    i = 0
    while i < len(spans):
        # các từ liền nhau, chỉ cách bởi khoảng trắng, gạch nối hoặc nháy, mới có thể thuộc cùng một tên
        run = [spans[i][2]]
        j = i + 1
        while j < len(spans) and len(run) < MAX_WORDS and text[spans[j - 1][1]:spans[j][0]] in (" ", "-", "'", "’", ""):
            run.append(spans[j][2])
            j += 1
        got = _convert(run, zh, glossary, spans[i - 1][2] if i else "")
        if not got:
            i += 1
            continue
        k, vi = got
        start, end = spans[i][0], spans[i + k - 1][1]
        before, after = text[start - 1:start], text[end:end + 1]
        out += [text[pos:start], " " if before.isalpha() else "", vi, " " if after.isalpha() else ""]      # "yêu范 Xian" sau khi đổi không được dính vào chữ bên cạnh
        pos = end
        i += k
    out.append(text[pos:])
    return "".join(out)
