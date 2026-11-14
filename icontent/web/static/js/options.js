/* Các ô tùy chọn: định nghĩa tại FIELDS, dùng chung cho Tạo video, Studio (panel bên phải) và Cài đặt. */
import {
  S, assToHex, clone, deepMerge, diff, effEngine, el, fillVoiceSelect, getPath, hexToAss, icon, mineFits, previewVoice, same, setPath,
  toast, uploadFile, voiceHooks, voiceList,
} from './core.js';
import { myVoiceButton } from './myvoices.js';

export const SUB_STYLES = [
  ['classic', 'Cổ điển'], ['cinema', 'Phim'], ['box', 'Nền hộp'], ['tiktok', 'TikTok'], ['karaoke', 'Karaoke'], ['pop', 'Pop'],
];
const dubOn = (v) => getPath(v, 'tts.enabled') !== false;
const fixed = (v) => (getPath(v, 'tts.voice_mode') || 'auto') === 'fixed';
const eng = (v) => getPath(v, 'tts.engine') || 'vieneu';
const lang = (v) => getPath(v, 'translate.target_lang') || 'vi';
const effE = (v) => effEngine(eng(v), lang(v));      // VieNeu chỉ đọc tiếng Việt: thứ tiếng khác tự đổi bộ đọc
const prov = (v) => getPath(v, 'translate.provider') || 'claude';
const hsOn = (v) => { const b = getPath(v, 'edit.blur_hardsub'); return !(b === false || b === 'false'); };
const blurUI = (v) => (v === true || v === 'true' ? 'true' : v === false || v === 'false' ? 'false' : 'auto');
const blurVal = (s) => (s === 'true' ? true : s === 'false' ? false : 'auto');
const pct = (x) => Math.round(x * 100) + '%';

export const FIELDS = {
  'translate.target_lang': {
    label: 'Thị trường: dịch và lồng tiếng sang', type: 'select', fallback: 'vi',
    options: () => (S.langs.length ? S.langs : [{ code: 'vi', name: 'Tiếng Việt', market: 'Việt Nam' }]).map((l) => [l.code, `${l.name} · ${l.market}`]),
    hint: 'Phụ đề, giọng đọc, tiêu đề và hashtag đều theo ngôn ngữ này. Tiếng nước ngoài nên dịch bằng AI (Gemini có gói miễn phí): câu vừa khung, giọng đọc tự nhiên hơn dịch offline',
  },
  'translate.provider': {
    label: 'Dịch bằng', type: 'select', fallback: 'claude', options: [
      ['claude', 'Claude: tự nhiên nhất'], ['openai', 'API kiểu OpenAI: DeepSeek, Gemini, Ollama…'],
      ['mcp', 'AI qua MCP: Claude, ChatGPT, Grok, không cần key'],
      ['offline', 'Dịch offline trên máy: không cần key'],
      ['google', 'Google miễn phí: chỉ để thử'], ['none', 'Không dịch: chỉ phụ đề gốc'],
    ],
  },
  'translate.model': { label: 'Model', type: 'text', placeholder: 'claude-opus-5-5', showIf: (v) => ['claude', 'openai'].includes(prov(v)) },
  'translate.effort': { label: 'Mức suy nghĩ (Claude)', type: 'seg', fallback: 'medium', options: [['low', 'Nhanh'], ['medium', 'Cân bằng'], ['high', 'Kỹ']], showIf: (v) => prov(v) === 'claude' },
  'translate.analyze': { label: 'Phân tích video trước khi dịch', type: 'toggle', fallback: true, hint: 'AI đọc cả video một lượt: tóm tắt, xưng hô, tên riêng, gợi ý tiêu đề và hashtag. Dịch hay hơn, thêm một việc cho AI', showIf: (v) => ['claude', 'openai', 'mcp'].includes(prov(v)) },
  'translate.mcp_wait': { label: 'Chờ AI qua MCP nhận việc', type: 'range', min: 60, max: 900, step: 30, fallback: 300, fmt: (x) => (x % 60 ? (x / 60).toFixed(1) : x / 60) + ' phút', showIf: (v) => prov(v) === 'mcp', hint: 'Quá thời gian này mà chưa AI nào nhận việc thì tự dịch bằng dịch offline hoặc Google' },
  'translate.style': { label: 'Văn phong', type: 'text', placeholder: 'Tự nhiên, khẩu ngữ, hợp video ngắn…', showIf: (v) => prov(v) !== 'none' },
  'translate.glossary': { label: 'Thuật ngữ: luôn dịch đúng như sau', type: 'dict', keyPh: '中文', valPh: 'Bản dịch', addLabel: 'Thêm thuật ngữ', showIf: (v) => prov(v) !== 'none' },

  'tts.enabled': { label: 'Lồng tiếng', type: 'toggle', fallback: true, hint: 'Tắt: chỉ làm phụ đề, giữ tiếng gốc' },
  'tts.engine': {
    label: 'Bộ đọc', type: 'seg', fallback: 'vieneu', showIf: dubOn,
    options: [['vieneu', 'VieNeu · tiếng Việt'], ['vox', 'Nhiều thứ tiếng · trên máy'], ['edge', 'Microsoft · online']],
    // nút sáng là bộ đọc thật sự dùng: thị trường nước ngoài mà để VieNeu thì Studio566 tự dùng bộ khác
    effective: (v) => effE(v),
    optDisabled: (id, v) => (id === 'vieneu' && lang(v) !== 'vi') || (id === 'vox' && !S.voices.vox_ready),
    hint: 'VieNeu chỉ đọc tiếng Việt: lồng thứ tiếng khác thì tự dùng bộ đọc nhiều thứ tiếng (tải ở Cài đặt > Mô-đun AI) hoặc Microsoft',
  },
  'tts.voice_mode': {
    label: 'Cách chọn giọng', type: 'select', fallback: 'auto', showIf: dubOn, options: [
      ['auto', 'Tự động: mỗi người nói một giọng'], ['per_line', 'Đoán nam/nữ theo từng câu'],
      ['fixed', 'Một giọng cố định'], ['clone', 'Bắt chước giọng gốc (thử nghiệm)'],
    ],
  },
  'tts.vieneu_voice': { label: 'Giọng', type: 'voice', engine: 'vieneu', showIf: (v) => dubOn(v) && fixed(v) && effE(v) === 'vieneu' },
  'tts.vox_voice': { label: 'Giọng', type: 'voice', engine: 'vox', showIf: (v) => dubOn(v) && fixed(v) && effE(v) === 'vox' },
  'tts.voice': { label: 'Giọng', type: 'voice', engine: 'edge', showIf: (v) => dubOn(v) && fixed(v) && effE(v) === 'edge' },
  'tts.male_voice': { label: 'Giọng nam', type: 'voice', gender: 'male', resetOnEngine: true, showIf: (v) => dubOn(v) && ['auto', 'per_line'].includes(getPath(v, 'tts.voice_mode') || 'auto') },
  'tts.female_voice': { label: 'Giọng nữ', type: 'voice', gender: 'female', resetOnEngine: true, showIf: (v) => dubOn(v) && ['auto', 'per_line'].includes(getPath(v, 'tts.voice_mode') || 'auto') },
  'tts.max_speed': { label: 'Đọc nhanh tối đa', type: 'range', min: 1, max: 1.6, step: 0.05, fallback: 1.35, fmt: (x) => x.toFixed(2) + 'x', showIf: dubOn, hint: 'Câu cần đọc nhanh hơn mức này sẽ được AI rút gọn' },
  'tts.pronounce': { label: 'Từ điển phát âm', type: 'dict', keyPh: 'Chữ trong phụ đề', valPh: 'Đọc thành', addLabel: 'Thêm từ', hint: 'Sửa cách đọc mà không đổi phụ đề, ví dụ TikTok → Tíc Tốc', showIf: dubOn },

  'edit.sub_style': { label: 'Kiểu phụ đề', type: 'stylecards', fallback: 'classic' },
  'edit.burn_subs': { label: 'Gắn phụ đề vào video', type: 'toggle', fallback: true },
  'edit.font': { label: 'Font chữ', type: 'font', fallback: 'Arial' },
  'edit.font_size_ratio': { label: 'Cỡ chữ', type: 'range', min: 0.03, max: 0.09, step: 0.002, fallback: 0.05, fmt: (x) => (x * 100).toFixed(1) + '%' },
  'edit.primary_color': { label: 'Màu chữ', type: 'color', fallback: '&H00FFFFFF' },
  'edit.highlight_color': { label: 'Màu nhấn', type: 'color', fallback: '&H0000E5FF' },
  'edit.outline_color': { label: 'Màu viền', type: 'color', fallback: '&H00000000' },
  'edit.outline': { label: 'Độ dày viền', type: 'range', min: 0, max: 8, step: 1, fallback: 3, fmt: (x) => String(Math.round(x)) },
  'edit.uppercase': { label: 'Viết hoa toàn bộ', type: 'toggle', fallback: false },

  'edit.blur_hardsub': {
    label: 'Sub tiếng Trung có sẵn trong video', type: 'select', fallback: 'auto', toUI: blurUI, fromUI: blurVal, options: [
      ['auto', 'Tự dò và xử lý'], ['true', 'Luôn xử lý vùng đã chọn'], ['false', 'Giữ nguyên, không xử lý'],
    ],
  },
  'edit.hardsub_mode': { label: 'Cách xử lý', type: 'seg', fallback: 'inpaint', options: [['inpaint', 'Xóa sạch'], ['blur', 'Làm mờ'], ['band', 'Dải tối']], showIf: hsOn },
  'edit.aspect': { label: 'Khung hình', type: 'seg', fallback: 'keep', options: [['keep', 'Giữ nguyên'], ['9:16', '9:16'], ['16:9', '16:9'], ['1:1', '1:1']] },
  'edit.fit': { label: 'Khi đổi khung', type: 'seg', fallback: 'blur', options: [['blur', 'Nền mờ'], ['track', 'Theo mặt'], ['crop', 'Cắt cố định'], ['black', 'Viền đen']], showIf: (v) => (getPath(v, 'edit.aspect') || 'keep') !== 'keep' },
  'edit.focus_x': { label: 'Giữ phần nào của hình', type: 'range', min: 0, max: 1, step: 0.05, fallback: 0.5, fmt: (x) => (x < 0.45 ? 'Bên trái' : x > 0.55 ? 'Bên phải' : 'Giữa'), showIf: (v) => (getPath(v, 'edit.aspect') || 'keep') !== 'keep' && getPath(v, 'edit.fit') === 'crop' },
  'edit.look': { label: 'Bộ màu', type: 'select', fallback: '', options: [['', 'Giữ màu gốc'], ['warm', 'Ấm'], ['cool', 'Lạnh'], ['vivid', 'Rực rỡ'], ['film', 'Điện ảnh'], ['teal', 'Xanh cam Hollywood'], ['moody', 'Trầm lắng'], ['golden', 'Nắng vàng'], ['bright', 'Sáng trong'], ['vintage', 'Cổ điển'], ['bw', 'Đen trắng']] },
  'edit.lut': { label: 'File màu riêng (LUT .cube)', type: 'file', kind: 'lut', accept: '.cube', empty: 'Chưa có', hint: 'Áp dụng khi dựng, xem kết quả ở chế độ Thành phẩm' },
  'edit.fade_in': { label: 'Mờ dần vào', type: 'range', min: 0, max: 3, step: 0.1, fallback: 0, fmt: (x) => (x ? x.toFixed(1).replace('.', ',') + ' giây' : 'Không') },
  'edit.fade_out': { label: 'Mờ dần ra', type: 'range', min: 0, max: 3, step: 0.1, fallback: 0, fmt: (x) => (x ? x.toFixed(1).replace('.', ',') + ' giây' : 'Không') },
  'edit.intro': { label: 'Mở đầu (video hoặc ảnh)', type: 'file', kind: 'card', accept: 'video/*,image/png,image/jpeg,image/webp', empty: 'Chưa có' },
  'edit.outro': { label: 'Kết thúc (video hoặc ảnh)', type: 'file', kind: 'card', accept: 'video/*,image/png,image/jpeg,image/webp', empty: 'Chưa có' },
  'edit.card_seconds': { label: 'Thời lượng khi là ảnh', type: 'range', min: 1, max: 8, step: 0.5, fallback: 3, fmt: (x) => x.toFixed(1).replace('.', ',') + ' giây', showIf: (v) => !!(getPath(v, 'edit.intro') || getPath(v, 'edit.outro')) },
  'edit.flip': { label: 'Lật ngang', type: 'toggle', fallback: false },
  'edit.zoom': { label: 'Phóng to', type: 'range', min: 1, max: 1.2, step: 0.01, fallback: 1, fmt: (x) => (x <= 1.001 ? 'Không' : '+' + Math.round((x - 1) * 100) + '%') },
  'edit.speed': { label: 'Tốc độ video', type: 'range', min: 0.8, max: 1.5, step: 0.05, fallback: 1, fmt: (x) => x.toFixed(2) + 'x' },
  'edit.brightness': { label: 'Độ sáng', type: 'range', min: -0.15, max: 0.15, step: 0.01, fallback: 0, fmt: (x) => (x > 0 ? '+' : '') + Math.round(x * 100) },
  'edit.contrast': { label: 'Tương phản', type: 'range', min: 0.8, max: 1.3, step: 0.01, fallback: 1, fmt: pct },
  'edit.saturation': { label: 'Độ tươi màu', type: 'range', min: 0.6, max: 1.5, step: 0.01, fallback: 1, fmt: pct },
  'edit.watermark_text': { label: 'Chữ watermark', type: 'text', placeholder: '@kenhcuaban' },
  'edit.logo': { label: 'Logo', type: 'file', kind: 'logo', accept: 'image/png,image/webp,image/jpeg', empty: 'Chọn ảnh PNG' },
  'edit.logo_pos': { label: 'Vị trí logo', type: 'select', fallback: 'top-right', options: [['top-left', 'Trên trái'], ['top-right', 'Trên phải'], ['bottom-left', 'Dưới trái'], ['bottom-right', 'Dưới phải']], showIf: (v) => !!getPath(v, 'edit.logo') },
  'edit.logo_scale': { label: 'Cỡ logo', type: 'range', min: 0.05, max: 0.35, step: 0.01, fallback: 0.15, fmt: pct, showIf: (v) => !!getPath(v, 'edit.logo') },
  'edit.encoder': { label: 'Bộ mã hóa', type: 'seg', fallback: 'auto', options: [['auto', 'Tự chọn'], ['h264_nvenc', 'GPU NVIDIA'], ['libx264', 'CPU']] },
  'edit.crf': { label: 'Chất lượng (thấp = nét hơn)', type: 'range', min: 16, max: 32, step: 1, fallback: 23, fmt: (x) => String(Math.round(x)) },

  'audio.duck': { label: 'Tự giảm tiếng nền khi có lời', type: 'toggle', fallback: true },
  'audio.original_volume': { label: 'Âm lượng tiếng gốc', type: 'range', min: 0, max: 1, step: 0.01, fallback: 0.15, fmt: pct },
  'audio.dub_volume': { label: 'Âm lượng giọng lồng', type: 'range', min: 0.5, max: 2, step: 0.05, fallback: 1, fmt: pct },
  'audio.separate': { label: 'Tách nhạc nền khỏi giọng gốc', type: 'seg', fallback: 'auto', options: [['auto', 'Tự động'], ['on', 'Bật'], ['off', 'Tắt']] },
  'audio.music': { label: 'Nhạc nền riêng', type: 'file', kind: 'music', accept: 'audio/*', empty: 'Chọn file nhạc' },
  'audio.music_volume': { label: 'Âm lượng nhạc', type: 'range', min: 0, max: 0.6, step: 0.01, fallback: 0.12, fmt: pct, showIf: (v) => !!getPath(v, 'audio.music') },
  'audio.music_skip_intro': { label: 'Bỏ đoạn đầu quá nhỏ của nhạc', type: 'toggle', fallback: true, showIf: (v) => !!getPath(v, 'audio.music') },
  'audio.loudnorm': { label: 'Chuẩn hóa âm lượng cho mạng xã hội', type: 'toggle', fallback: true },

  'asr.model': { label: 'Model nhận dạng (Whisper)', type: 'select', fallback: 'large-v3-turbo', hint: 'Model chưa có sẽ được tải ở lần chạy đầu', options: [['large-v3-turbo', 'large-v3-turbo: nhanh, 1,6 GB (khuyên dùng)'], ['large-v3', 'large-v3: kỹ hơn chút, 3 GB'], ['medium', 'medium: 1,5 GB'], ['small', 'small: rất nhanh, 0,5 GB']] },
  'download.cookies_file': { label: 'File cookies.txt (Douyin cần)', type: 'text', placeholder: 'cookies.txt' },
  'download.cookies_from_browser': { label: 'Hoặc đọc cookie từ trình duyệt', type: 'select', fallback: '', options: [['', 'Không'], ['firefox', 'Firefox'], ['chrome', 'Chrome'], ['edge', 'Edge']] },
  'download.proxy': { label: 'Proxy', type: 'text', placeholder: 'http://127.0.0.1:7890' },
};

export const GROUPS = {
  translate: { title: 'Dịch', icon: 'globe', paths: ['translate.target_lang', 'translate.provider', 'translate.model', 'translate.analyze', 'translate.mcp_wait', 'translate.style'] },
  voice: { title: 'Giọng đọc', icon: 'mic', paths: ['tts.enabled', 'tts.engine', 'tts.voice_mode', 'tts.vieneu_voice', 'tts.vox_voice', 'tts.voice', 'tts.male_voice', 'tts.female_voice', 'tts.max_speed', 'tts.pronounce'] },
  subs: { title: 'Phụ đề', icon: 'sub', paths: ['edit.sub_style', 'edit.burn_subs', 'edit.font', 'edit.font_size_ratio', 'edit.primary_color', 'edit.highlight_color', 'edit.uppercase'] },
  picture: { title: 'Hình ảnh', icon: 'image', paths: ['edit.blur_hardsub', 'edit.hardsub_mode', 'edit.aspect', 'edit.flip', 'edit.zoom', 'edit.speed', 'edit.saturation', 'edit.watermark_text', 'edit.logo', 'edit.logo_pos', 'edit.logo_scale', 'edit.encoder'] },
  sound: { title: 'Âm thanh', icon: 'wave', paths: ['audio.duck', 'audio.original_volume', 'audio.separate', 'audio.music', 'audio.music_volume'] },
  system: { title: 'Tải video & nhận dạng', icon: 'cpu', paths: ['asr.model', 'download.cookies_file', 'download.cookies_from_browser', 'download.proxy'] },
};

function subMock(id) {
  const txt = {
    classic: ['Xin chào các bạn'],
    cinema: ['Xin chào các bạn'],
    box: [el('span', { text: 'Xin chào các bạn' })],
    tiktok: ['Xin ', el('span', { class: 'hl', text: 'chào' }), ' các bạn'],
    karaoke: [el('span', { class: 'sung', text: 'Xin chào ' }), 'các bạn'],
    pop: ['XIN ', el('span', { class: 'hl big', text: 'CHÀO' })],
  }[id] || ['Xin chào'];
  return el('div', { class: 'sub-mock sm-' + id }, el('div', { class: 'sm-text' }, txt));
}

/** Bộ điều khiển cho 1 tùy chọn. vals bị sửa trực tiếp; base để biết ô nào khác mặc định. */
export function buildControl(path, vals, base, fire) {
  const def = Object.assign({ path }, FIELDS[path]);
  const get = () => { const v = getPath(vals, path); return v === undefined || v === null ? def.fallback : v; };
  const row = el('div', { class: 'opt-row opt-' + def.type });
  const lab = el('div', { class: 'opt-label' }, def.label, el('span', { class: 'mod-dot', title: 'Khác cài đặt mặc định' }));
  const c = {
    def, row, sync() {}, refresh: null,
    mark() {
      const v = getPath(vals, path);
      row.classList.toggle('modified', v !== undefined && !same(v, getPath(base, path)));
    },
  };
  const set = (v) => { setPath(vals, path, v); c.sync(); fire(path); };

  switch (def.type) {
    case 'select': {
      const to = def.toUI || ((v) => (v == null ? '' : String(v)));
      const from = def.fromUI || ((s) => s);
      const opts = typeof def.options === 'function' ? def.options() : def.options;      // danh sách động (thị trường lấy từ máy chủ)
      const sel = el('select', { class: 'input', onchange: () => set(from(sel.value)) }, opts.map(([v, l]) => el('option', { value: v }, l)));
      c.sync = () => {
        const cur = to(get());
        sel.value = cur;
        if (sel.value !== cur && cur) { sel.append(el('option', { value: cur }, cur)); sel.value = cur; }
      };
      row.append(lab, sel);
      break;
    }
    case 'font': {
      const sel = el('select', { class: 'input', onchange: () => set(sel.value) });
      c.sync = () => {
        const cur = String(get() || 'Arial');
        const list = S.fonts.includes(cur) ? S.fonts : [cur, ...S.fonts];
        sel.replaceChildren(...list.map((f) => el('option', { value: f, style: { fontFamily: `"${f}"` } }, f)));
        sel.value = cur;
        sel.style.fontFamily = `"${cur}"`;
      };
      row.append(lab, sel);
      break;
    }
    case 'seg': {
      const to = def.toUI || ((v) => String(v));
      const from = def.fromUI || ((s) => s);
      const wrap = el('div', { class: 'seg', role: 'radiogroup' });
      const btns = def.options.map(([v, l]) => {
        const b = el('button', { type: 'button', class: 'seg-btn', role: 'radio', onclick: () => set(from(v)) }, l);
        b.dataset.v = v;
        wrap.append(b);
        return b;
      });
      c.sync = () => {
        const cur = def.effective ? def.effective(vals) : to(get());
        btns.forEach((b) => {
          const on = b.dataset.v === cur;
          b.classList.toggle('active', on);
          b.setAttribute('aria-checked', on ? 'true' : 'false');
          if (def.optDisabled) b.disabled = def.optDisabled(b.dataset.v, vals);
        });
      };
      if (def.effective) c.refresh = () => c.sync();      // đổi thị trường: nút sáng đổi theo bộ đọc thật sự dùng
      row.append(lab, wrap);
      break;
    }
    case 'toggle': {
      const inp = el('input', { type: 'checkbox', onchange: () => set(inp.checked) });
      const sw = el('label', { class: 'switch', title: def.label }, inp, el('span', { class: 'switch-track' }, el('span', { class: 'switch-thumb' })));
      c.sync = () => { inp.checked = !!get(); };
      row.append(el('div', { class: 'opt-inline' }, lab, sw));
      break;
    }
    case 'range': {
      const out = el('span', { class: 'range-val' });
      const inp = el('input', {
        type: 'range', class: 'range', min: def.min, max: def.max, step: def.step, 'aria-label': def.label,
        oninput: () => { setPath(vals, path, parseFloat(inp.value)); paint(); fire(path); },
      });
      const paint = () => {
        const v = parseFloat(inp.value);
        out.textContent = def.fmt ? def.fmt(v) : String(v);
        inp.style.setProperty('--p', ((v - def.min) / (def.max - def.min) * 100) + '%');
      };
      c.sync = () => { const v = get(); inp.value = String(v == null ? def.min : v); paint(); };
      row.append(el('div', { class: 'opt-inline' }, lab, out), inp);
      break;
    }
    case 'color': {
      const inp = el('input', { type: 'color', class: 'color-input', 'aria-label': def.label, oninput: () => { setPath(vals, path, hexToAss(inp.value)); val.textContent = inp.value.toUpperCase(); fire(path); } });
      const val = el('span', { class: 'color-val mono' });
      c.sync = () => { const h = assToHex(get()); inp.value = h.toLowerCase(); val.textContent = h; };
      row.append(el('div', { class: 'opt-inline' }, lab, el('label', { class: 'color-pick' }, inp, val)));
      break;
    }
    case 'text': {
      const inp = el('input', {
        class: 'input', type: 'text', placeholder: def.placeholder || '', spellcheck: 'false', 'aria-label': def.label,
        oninput: () => { setPath(vals, path, inp.value); fire(path); },
      });
      c.sync = () => { if (document.activeElement !== inp) { const v = get(); inp.value = v == null ? '' : String(v); } };
      row.append(lab, inp);
      break;
    }
    case 'file': {
      const name = el('span', { class: 'file-name' });
      const pick = el('input', {
        type: 'file', accept: def.accept || '', hidden: true, onchange: async () => {
          const f = pick.files[0];
          if (!f) return;
          pickBtn.disabled = true; pickBtn.classList.add('is-busy');
          try { const r = await uploadFile(def.kind, f); set(r.path); } catch (e) { toast(e.message, 'error'); } finally {
            pickBtn.disabled = false; pickBtn.classList.remove('is-busy'); pick.value = '';
          }
        },
      });
      const pickBtn = el('button', { type: 'button', class: 'btn btn-sm', onclick: () => pick.click() }, icon('upload'), 'Chọn file');
      const clearBtn = el('button', { type: 'button', class: 'btn btn-sm btn-icon btn-ghost', title: 'Bỏ file này', onclick: () => set('') }, icon('x'));
      c.sync = () => {
        const v = String(get() || '');
        name.textContent = v ? v.split(/[\\/]/).pop() : def.empty;
        name.title = v;
        name.classList.toggle('muted', !v);
        clearBtn.hidden = !v;
      };
      row.append(lab, el('div', { class: 'file-pick' }, pickBtn, name, clearBtn, pick));
      break;
    }
    case 'voice': {
      const engineOf = () => def.engine || effE(vals);
      const langOf = () => lang(vals);
      const sel = el('select', { class: 'input', onchange: () => set(sel.value) });
      const btn = el('button', {
        type: 'button', class: 'btn btn-icon', title: 'Nghe thử giọng này', 'aria-label': 'Nghe thử giọng này',
        onclick: () => {
          const e = engineOf();
          let v = sel.value;
          if (!v && def.gender) { const l = voiceList(e, langOf()).find((x) => x.gender === def.gender); v = l ? l.id : ''; }
          previewVoice(e, v, btn, langOf());
        },
      }, icon('play'));
      const mine = myVoiceButton(engineOf, (id) => { set(id); c.refresh(true); });
      let built = '', lastEng = '';
      c.refresh = (force) => {
        const e = engineOf();
        const lg = langOf();
        mine.hidden = !mineFits(e, lg);      // giọng tự thu: VieNeu (tiếng Việt) và bộ đọc nhiều thứ tiếng
        if (def.resetOnEngine && lastEng && e + lg !== lastEng) {
          const cur = getPath(vals, path);
          const list = voiceList(e, lg);
          if (cur && list.length && !list.some((x) => x.id === cur) && !String(cur).startsWith('me:')) setPath(vals, path, getPath(base, path) || '');
        }
        lastEng = e + lg;
        const k = e + '|' + lg + '|' + S.voicesVersion;
        if (force || k !== built) {
          built = k;
          fillVoiceSelect(sel, e, { gender: def.gender, current: get() || '', defaultLabel: 'Mặc định', lang: lg });
        }
      };
      c.sync = () => c.refresh(true);
      row.append(lab, el('div', { class: 'voice-pick' }, sel, btn, mine));
      break;
    }
    case 'stylecards': {
      const wrap = el('div', { class: 'style-cards' });
      const cards = SUB_STYLES.map(([id, label]) => {
        const b = el('button', { type: 'button', class: 'style-card', onclick: () => set(id) }, subMock(id), el('span', { class: 'style-name', text: label }));
        b.dataset.v = id;
        wrap.append(b);
        return b;
      });
      c.sync = () => { const cur = get() || 'classic'; cards.forEach((b) => b.classList.toggle('active', b.dataset.v === cur)); };
      row.append(lab, wrap);
      break;
    }
    case 'dict': {
      const rows = el('div', { class: 'dict-rows' });
      const collect = () => {
        const o = {};
        for (const r of rows.children) {
          const [a, b] = r.querySelectorAll('input');
          if (a.value.trim()) o[a.value.trim()] = b.value.trim();
        }
        setPath(vals, path, o);
        fire(path);
      };
      const addRow = (k = '', v = '', focus = false) => {
        const a = el('input', { class: 'input', placeholder: def.keyPh, value: k, oninput: collect });
        rows.append(el('div', { class: 'dict-row' }, a, icon('arrow'),
          el('input', { class: 'input', placeholder: def.valPh, value: v, oninput: collect }),
          el('button', { type: 'button', class: 'btn btn-sm btn-icon btn-ghost', title: 'Xóa', onclick: (e) => { e.currentTarget.parentElement.remove(); collect(); } }, icon('x'))));
        if (focus) a.focus();
      };
      c.sync = () => { rows.replaceChildren(); for (const [k, v] of Object.entries(get() || {})) addRow(k, v); };
      row.append(lab, rows, el('div', {}, el('button', { type: 'button', class: 'btn btn-sm btn-ghost', onclick: () => addRow('', '', true) }, icon('plus'), def.addLabel || 'Thêm')));
      break;
    }
    default:
      row.append(lab, el('div', { class: 'muted', text: '(?)' }));
  }
  if (def.hint) row.append(el('div', { class: 'opt-hint', text: def.hint }));
  return c;
}

/** Danh sách ô tùy chọn phẳng (panel Studio). */
export function FieldList(paths, vals, base, onChange) {
  const ctrls = [];
  const root = el('div', { class: 'opt-body' });
  const fire = (p) => {
    for (const c of ctrls) {
      c.row.hidden = !!(c.def.showIf && !c.def.showIf(vals));
      if (c.refresh) c.refresh(false);
      c.mark();
    }
    if (onChange && p) onChange(p);
  };
  for (const p of paths) {
    const c = buildControl(p, vals, base, fire);
    ctrls.push(c);
    root.append(c.row);
  }
  ctrls.forEach((c) => c.sync());
  fire();
  voiceHooks.add(() => {
    if (!root.isConnected) return root.dataset.mounted !== '1' ? true : false;
    root.dataset.mounted = '1';
    ctrls.forEach((c) => { if (c.refresh) c.refresh(true); });
    return true;
  });
  return { root, sync() { ctrls.forEach((c) => c.sync()); fire(); } };
}

/** Form có nhóm thu gọn được (ngăn kéo tùy chỉnh, Cài đặt). */
export function OptionsForm({ vals, base, groups, storeKey, onChange }) {
  const ctrls = [];
  const groupEls = [];
  const root = el('div', { class: 'opt-form' });
  const form = { root, vals, base };
  function fire(p) {
    for (const c of ctrls) {
      c.row.hidden = !!(c.def.showIf && !c.def.showIf(vals));
      if (c.refresh) c.refresh(false);
      c.mark();
    }
    for (const g of groupEls) {
      const n = g.ctrls.filter((c) => c.row.classList.contains('modified')).length;
      g.mods.textContent = n ? `${n} thay đổi` : '';
    }
    if (onChange && p !== undefined) onChange(form);
  }
  form.syncAll = () => { ctrls.forEach((c) => c.sync()); fire(''); };
  form.overrides = () => diff(vals, base) || {};
  form.reset = () => { for (const k of Object.keys(vals)) delete vals[k]; deepMerge(vals, clone(base) || {}); form.syncAll(); };
  for (const id of groups) {
    const g = GROUPS[id];
    const body = el('div', { class: 'opt-body' });
    const gc = g.paths.map((p) => { const c = buildControl(p, vals, base, fire); ctrls.push(c); body.append(c.row); return c; });
    const key = `ic.grp.${storeKey || 'x'}.${id}`;
    const mods = el('span', { class: 'opt-group-mods' });
    const det = el('details', { class: 'opt-group', open: localStorage.getItem(key) !== '0' },
      el('summary', {}, icon(g.icon), el('span', { text: g.title }), mods, icon('chev', 'chev')), body);
    det.addEventListener('toggle', () => localStorage.setItem(key, det.open ? '1' : '0'));
    groupEls.push({ ctrls: gc, mods });
    root.append(det);
  }
  ctrls.forEach((c) => c.sync());
  fire();
  voiceHooks.add(() => {
    if (!root.isConnected) return false;
    ctrls.forEach((c) => { if (c.refresh) c.refresh(true); });
    return true;
  });
  return form;
}
