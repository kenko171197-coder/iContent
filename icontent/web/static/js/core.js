/* iContent Studio — nền tảng dùng chung: DOM, định dạng, API, toast, modal, âm thanh, dữ liệu.
 * Vanilla JS, không framework, không CDN: chạy offline hoàn toàn. */

// ===================================================================== hằng số
export const TAPE = [
  ['download', 'Tải về'], ['hardsub', 'Dò sub'], ['asr', 'Nhận dạng'],
  ['translate', 'Dịch'], ['tts', 'Lồng tiếng'], ['render', 'Dựng video'],
];
export const STAGE_STEP = {
  download: 0, audio: 0, separate: 0, hardsub: 1, asr: 2, speakers: 2, analyze: 3, translate: 3, merge: 5,
  voice: 4, tts: 4, clean: 5, render: 5, reframe: 5, qc: 5,
};
export const STAGE_LABEL = {
  download: 'Đang tải video', audio: 'Tách âm thanh', separate: 'Tách nhạc nền', hardsub: 'Dò sub gốc',
  asr: 'Nhận dạng giọng nói', speakers: 'Nghe ai nói câu nào', merge: 'Đang ghép video', analyze: 'Phân tích ngữ cảnh', translate: 'Đang dịch', voice: 'Chọn giọng đọc',
  tts: 'Đang lồng tiếng', clean: 'Đang xóa sub gốc', reframe: 'Dò khuôn mặt', render: 'Đang dựng video', qc: 'Đang kiểm định', done: 'Hoàn tất',
};
const SPEAKER_COLORS = ['#ffb224', '#5bb3f0', '#f078a8', '#5fd18b', '#b98cf5', '#f0865b', '#4fd1c5', '#c9c36a'];
/** Màu riêng của mỗi người nói: S1, S2... */
export function speakerColor(id) {
  const n = parseInt(String(id || '').slice(1), 10);
  return SPEAKER_COLORS[(Number.isFinite(n) && n > 0 ? n - 1 : 0) % SPEAKER_COLORS.length];
}
export const STATE_LABEL = { queued: 'Đang chờ', running: 'Đang chạy', done: 'Hoàn tất', error: 'Lỗi', cancelled: 'Đã hủy' };
export const PLATFORMS = {
  douyin: ['Douyin', '#fe2c55'], bilibili: ['Bilibili', '#23ade5'], kuaishou: ['Kuaishou', '#ff6a00'],
  xiaohongshu: ['Xiaohongshu', '#ff2442'], weibo: ['Weibo', '#e6162d'], xigua: ['Xigua', '#f04142'],
  toutiao: ['Toutiao', '#f85959'], youtube: ['YouTube', '#ff0033'], tiktok: ['TikTok', '#25f4ee'],
  local: ['File máy', '#8f877a'], web: ['Web', '#a78bfa'],
};
const PREVIEW_TEXT = 'Xin chào, đây là giọng đọc thử của iContent Studio.';
export const ATOMIC = new Set(['glossary', 'external', 'pronounce']);

const ICONS = {
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2.5"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>',
  package: '<path d="M12 3l8.5 4.5v9L12 21l-8.5-4.5v-9z"/><path d="M3.5 7.5L12 12l8.5-4.5M12 12v9"/>',
  safe: '<rect x="6" y="2.5" width="12" height="19" rx="2"/><path d="M6 7h12M6 16h12M14.5 7v9" stroke-dasharray="2 2"/>',
  gauge: '<path d="M4 18a9 9 0 1 1 16 0"/><path d="M12 14l4-5"/><circle cx="12" cy="14" r="1.4"/>',
  up: '<path d="M6 15l6-6 6 6"/>',
  compass: '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
  flame: '<path d="M12 3c.5 3.5 4.5 5.5 4.5 10.5a4.5 4.5 0 0 1-9 0c0-2 1-3.2 2-4.2.3 1.4 1 2.2 2 2.7-.5-3 0-6 .5-9z"/>',
  star: '<path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9-5.2-2.8-5.2 2.8 1-5.9L3.5 9.7l5.9-.8z"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
  spark: '<path d="M12 3l1.9 4.6 4.6 1.9-4.6 1.9L12 16l-1.9-4.6-4.6-1.9 4.6-1.9z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
  grid: '<rect x="3" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  phone: '<rect x="7" y="2.5" width="10" height="19" rx="2.2"/><path d="M11 18.5h2"/>',
  monitor: '<rect x="2.5" y="4" width="19" height="12.5" rx="2"/><path d="M8 20.5h8M12 16.5v4"/>',
  square: '<rect x="4" y="4" width="16" height="16" rx="2"/>',
  play: '<path d="M7.5 4.8v14.4L19.5 12z" fill="currentColor" stroke="none"/>',
  pause: '<rect x="6.5" y="5" width="4" height="14" rx="1" fill="currentColor" stroke="none"/><rect x="13.5" y="5" width="4" height="14" rx="1" fill="currentColor" stroke="none"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor" stroke="none"/>',
  folder: '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2.5h7.5A2.5 2.5 0 0 1 21 10v7.5a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12.5A1.5 1.5 0 0 0 8.5 21h7a1.5 1.5 0 0 0 1.5-1.5L18 7M9 7V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V7"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15h-.5A1.5 1.5 0 0 1 3 13.5v-9A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5V5"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
  back: '<path d="M15 18l-6-6 6-6"/>',
  next: '<path d="M9 18l6-6-6-6"/>',
  more: '<circle cx="5" cy="12" r="1.7" fill="currentColor"/><circle cx="12" cy="12" r="1.7" fill="currentColor"/><circle cx="19" cy="12" r="1.7" fill="currentColor"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/>',
  export: '<path d="M12 15V3M7 8l5-5 5 5"/><path d="M5 14v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M5 20h14"/>',
  upload: '<path d="M12 16V5M7 10l5-5 5 5"/><path d="M5 20h14"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5v.3"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.3"/>',
  scan: '<path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16"/><path d="M7.5 14h9M7.5 10.5h6"/>',
  crop: '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
  sliders: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
  send: '<path d="M21 3L10 14"/><path d="M21 3l-7 18-4-7-7-4z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  chev: '<path d="M6 9l6 6 6-6"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  sub: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 15h4M13 15h4M7 11h2M11 11h6"/>',
  wave: '<path d="M3 12h1.5M7 8.5v7M10.5 5v14M14 8v8M17.5 6.5v11M21 12h-.5"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3M14.5 8.5l2 2"/>',
  paste: '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9.5 4V3h5v1"/><path d="M9.5 10h5M9.5 14h5"/>',
  inbox: '<path d="M3 13l3-8h12l3 8v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M3 13h5l1.5 2.5h5L16 13h5"/>',
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
  redo: '<path d="M15 14l5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h3"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  brain: '<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3 2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3 2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/>',
  music: '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9.5 2.5v3.5M14.5 2.5v3.5M9.5 18v3.5M14.5 18v3.5M2.5 9.5H6M2.5 14.5H6M18 9.5h3.5M18 14.5h3.5"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  coffee: '<path d="M4 9h13v5.5A5.5 5.5 0 0 1 11.5 20h-2A5.5 5.5 0 0 1 4 14.5z"/><path d="M17 10.5h1.2a2.8 2.8 0 0 1 0 5.6H17"/><path d="M8 3.5c-.6.9-.6 1.6 0 2.5M12 3.5c-.6.9-.6 1.6 0 2.5"/>',
  heart: '<path d="M12 20s-7.5-4.6-9-9.2C2 7.6 4.3 5 7 5c2 0 3.8 1.2 5 3 1.2-1.8 3-3 5-3 2.7 0 5 2.6 4 5.8C19.5 15.4 12 20 12 20z"/>',
  shield: '<path d="M12 3l8 3v6c0 4.5-3.3 7.8-8 9-4.7-1.2-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
  scissors: '<circle cx="6" cy="6.5" r="2.5"/><circle cx="6" cy="17.5" r="2.5"/><path d="M8 8l12 9M8 16L20 7"/>',
  merge: '<path d="M7 4v5a4 4 0 0 0 4 4h6"/><path d="M14 10l3 3-3 3"/><path d="M7 20v-3"/>',
  wand: '<path d="M5 19L16 8"/><path d="M14 6l4 4"/><path d="M19 3v3M21 4.5h-3M6 4v3M7.5 5.5h-3M19 15v3M20.5 16.5h-3"/>',
  type: '<path d="M5 7V5h14v2M12 5v14M9 19h6"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
  keyboard: '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6.5 10h.01M10 10h.01M13.5 10h.01M17 10h.01M7 14h10"/>',
  compare: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 2v20"/>',
  full: '<path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/>',
  volume: '<path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
  mute: '<path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>',
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 0 6.5 22H20v-4"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
  home: '<path d="M3.5 11L12 4l8.5 7"/><path d="M5.5 9.5V20h13V9.5"/><path d="M10 20v-5.5h4V20"/>',
};

// ===================================================================== DOM
export const $ = (sel, root = document) => root.querySelector(sel);
export const enc = encodeURIComponent;
const PROPS = new Set(['value', 'checked', 'disabled', 'selected', 'hidden', 'muted', 'readOnly', 'open']);

/** el('div', {class, text, onclick, style, dataset, ...attrs}, ...children) — không dùng innerHTML với dữ liệu ngoài */
export function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k === 'html') n.innerHTML = v;                     // CHỈ dùng cho chuỗi tĩnh (icon SVG)
      else if (k === 'style' && typeof v === 'object') {
        for (const [sk, sv] of Object.entries(v)) {
          if (sv == null) continue;
          if (sk.startsWith('--')) n.style.setProperty(sk, sv); else n.style[sk] = sv;
        }
      } else if (k === 'dataset') Object.assign(n.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
      else if (PROPS.has(k)) n[k] = v;
      else n.setAttribute(k, v === true ? '' : String(v));
    }
  }
  return add(n, kids);
}
export function add(n, kids) {
  for (const c of kids.flat(Infinity)) {
    if (c == null || c === false) continue;
    n.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return n;
}
export function put(n, ...kids) { n.replaceChildren(); return add(n, kids); }
const svg = (p) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
export const icon = (name, cls = '') => el('span', { class: 'ico ' + cls, html: svg(ICONS[name] || '') });
export function setIcon(btn, name) { const i = btn.querySelector('.ico'); if (i) i.replaceWith(icon(name)); }

export const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
export const clone = (o) => (o === undefined ? undefined : JSON.parse(JSON.stringify(o)));
export const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
export const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
export function getPath(o, path) { return path.split('.').reduce((a, k) => (a == null ? undefined : a[k]), o); }
export function setPath(o, path, v) {
  const ks = path.split('.');
  let d = o;
  for (const k of ks.slice(0, -1)) { if (!isObj(d[k])) d[k] = {}; d = d[k]; }
  d[ks[ks.length - 1]] = v;
}
export function deepMerge(t, s) {
  for (const [k, v] of Object.entries(s || {})) {
    if (isObj(v) && isObj(t[k]) && !ATOMIC.has(k)) deepMerge(t[k], v);
    else t[k] = clone(v);
  }
  return t;
}
/** phần của `a` khác `b` (undefined nếu giống hệt) */
export function diff(a, b, key) {
  if (isObj(a) && isObj(b) && !ATOMIC.has(key)) {
    const out = {};
    for (const k of Object.keys(a)) {
      const d = diff(a[k], b[k], k);
      if (d !== undefined) out[k] = d;
    }
    return Object.keys(out).length ? out : undefined;
  }
  if (a === undefined) return undefined;
  return same(a, b) ? undefined : clone(a);
}
export function countLeaves(o) { return isObj(o) ? Object.entries(o).reduce((n, [k, v]) => n + (isObj(v) && !ATOMIC.has(k) ? countLeaves(v) : 1), 0) : 0; }
export function debounce(fn, ms) {
  let t = 0, last = null;
  const d = (...a) => { clearTimeout(t); last = a; t = setTimeout(() => { const x = last; last = null; fn(...x); }, ms); };
  /** chạy ngay phần đang chờ, ví dụ trước khi bấm Cập nhật video */
  d.flush = () => { if (!last) return undefined; clearTimeout(t); const x = last; last = null; return fn(...x); };
  return d;
}

// ===================================================================== định dạng
export function fmtTime(t, dec = 1) {
  if (t == null || isNaN(t)) return '--:--';
  const k = Math.pow(10, dec);
  let n = Math.round(Math.max(0, t) * k);
  const frac = n % k; n = (n - frac) / k;
  const h = Math.floor(n / 3600), m = Math.floor((n % 3600) / 60), s = n % 60;
  const ss = String(s).padStart(2, '0') + (dec ? '.' + String(frac).padStart(dec, '0') : '');
  return (h ? h + ':' + String(m).padStart(2, '0') : String(m).padStart(2, '0')) + ':' + ss;
}
export function fmtDur(t) {
  if (t == null || isNaN(t)) return '';
  t = Math.round(t);
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  return (h ? h + ':' + String(m).padStart(2, '0') : String(m)) + ':' + String(s).padStart(2, '0');
}
/** Dung lượng dễ đọc: 820 KB, 305 MB, 1,2 GB. */
export function fmtSize(b) {
  if (!b || b < 0) return '0 MB';
  if (b < 1e6) return Math.max(1, Math.round(b / 1e3)) + ' KB';
  if (b < 1e9) return (b < 1e7 ? (b / 1e6).toFixed(1).replace('.', ',') : Math.round(b / 1e6)) + ' MB';
  return (b / 1e9).toFixed(b < 1e11 ? 1 : 0).replace('.', ',') + ' GB';
}
export function toMs(v) {
  if (v == null || v === '') return null;
  if (typeof v === 'number') return v < 1e12 ? v * 1000 : v;
  const n = Number(v);
  if (!isNaN(n)) return toMs(n);
  const d = Date.parse(v);
  return isNaN(d) ? null : d;
}
export function fmtAgo(v) {
  const ms = toMs(v);
  if (!ms) return '';
  const s = (Date.now() - ms) / 1000;
  if (s < 60) return 'vừa xong';
  if (s < 3600) return Math.floor(s / 60) + ' phút trước';
  if (s < 86400) return Math.floor(s / 3600) + ' giờ trước';
  if (s < 172800) return 'hôm qua';
  return new Date(ms).toLocaleDateString('vi-VN');
}
export function elapsed(it) {
  const a = toMs(it.started);
  if (!a) return '';
  const b = toMs(it.finished) || Date.now();
  return fmtDur(Math.max(0, (b - a) / 1000));
}
export const words = (s) => String(s || '').trim().split(/\s+/).filter(Boolean).length;
export function shortSrc(s) {
  s = String(s || '');
  const m = s.match(/https?:\/\/\S+/);
  if (m) return m[0].length > 70 ? m[0].slice(0, 67) + '…' : m[0];
  return s.length > 70 ? s.slice(0, 67) + '…' : s;
}
export function detectPlatform(line) {
  const s = String(line || '').toLowerCase();
  const map = [
    [/douyin\.com|iesdouyin\.com/, 'douyin'], [/bilibili\.com|b23\.tv/, 'bilibili'], [/kuaishou\.com|gifshow\.com/, 'kuaishou'],
    [/xiaohongshu\.com|xhslink\.com/, 'xiaohongshu'], [/weibo\.(com|cn)/, 'weibo'], [/ixigua\.com/, 'xigua'], [/toutiao\.com/, 'toutiao'],
    [/youtube\.com|youtu\.be/, 'youtube'], [/tiktok\.com/, 'tiktok'],
  ];
  for (const [re, p] of map) if (re.test(s)) return p;
  if (/^[a-z]:[\\/]|^\\\\|^\//i.test(String(line || '').trim().replace(/^"/, ''))) return 'local';
  return /https?:\/\//.test(s) ? 'web' : '';
}
export function platformBadge(p) {
  const [name, color] = PLATFORMS[p] || [p || '?', '#8f877a'];
  return el('span', { class: 'plat', style: { '--c': color }, text: name });
}
export function genderOf(g) {
  g = String(g || '').toLowerCase();
  if (g.startsWith('f') || g.startsWith('nữ') || g === 'nu') return 'female';
  if (g.startsWith('m') || g === 'nam') return 'male';
  return '';
}
/** '&H0000E5FF' (ASS, AABBGGRR) <-> '#FFE500' */
export function assToHex(c) {
  const m = String(c || '').toUpperCase().replace(/^&H/, '').replace(/&$/, '').padStart(8, '0');
  return '#' + m.slice(6, 8) + m.slice(4, 6) + m.slice(2, 4);
}
export function hexToAss(hex, alpha = '00') {
  const h = String(hex || '#FFFFFF').replace('#', '').toUpperCase().padEnd(6, 'F');
  return `&H${alpha}${h.slice(4, 6)}${h.slice(2, 4)}${h.slice(0, 2)}`;
}

// ===================================================================== API
export const licenseHooks = new Set();
export const connHooks = new Set();      // gọi khi không tới được máy chủ (conn.js)
export async function api(method, path, body, opts = {}) {
  const init = { method, headers: {} };
  if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(path, init); } catch (e) {
    connHooks.forEach((fn) => fn());      // conn.js: hiện băng "Mất kết nối" và tự nối lại
    throw new Error('Mất kết nối với iContent. Đang thử kết nối lại…');
  }
  if (!res.ok) {
    let msg = `Lỗi ${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      // bản quyền hết hạn (hoặc bị gỡ) trong lúc đang dùng: máy chủ chặn mọi chức năng, giao diện chuyển sang màn Kích hoạt
      if (res.status === 403 && j && j.license && j.license.locked) licenseHooks.forEach((fn) => fn(j.license));
      if (j && j.detail != null) {
        msg = typeof j.detail === 'string' ? j.detail
          : Array.isArray(j.detail) ? j.detail.map((d) => (d.loc ? d.loc.join('.') + ': ' : '') + (d.msg || JSON.stringify(d))).join('\n')
            : JSON.stringify(j.detail);
      }
    } catch (_) { /* không phải JSON */ }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  if (opts.blob) return res.blob();
  const ct = res.headers.get('content-type') || '';
  return ct.includes('json') ? res.json() : res.text();
}
/** Gửi file lên máy chủ local (kéo thả video, logo, nhạc). onProgress(0..1) */
export function uploadFile(kind, file, onProgress) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open('PUT', `/api/upload?kind=${enc(kind)}&name=${enc(file.name)}`);
    x.upload.onprogress = (e) => { if (onProgress && e.lengthComputable) onProgress(e.loaded / e.total); };
    x.onload = () => {
      let j = {};
      try { j = JSON.parse(x.responseText); } catch (_) { /* bỏ qua */ }
      if (x.status >= 200 && x.status < 300) resolve(j); else reject(new Error(j.detail || `Lỗi ${x.status}`));
    };
    x.onerror = () => reject(new Error('Không gửi được file'));
    x.send(file);
  });
}

// ===================================================================== toast, modal, menu
export function toast(msg, type = 'info', opts = {}) {
  const box = $('#toasts');
  const actions = opts.actions || [];
  const t = el('div', { class: `toast toast-${type}`, role: type === 'error' ? 'alert' : 'status' },
    icon(type === 'error' || type === 'warn' ? 'alert' : type === 'success' ? 'check' : 'info'),
    el('div', { class: 'toast-msg', text: msg }),
    el('button', { class: 'toast-x', title: 'Đóng', 'aria-label': 'Đóng', onclick: () => close() }, icon('x')),
    actions.length ? el('div', { class: 'toast-actions' }, actions.map((a) =>
      el('button', { class: 'btn btn-sm ' + (a.primary ? 'btn-primary' : 'btn-ghost'), onclick: () => { close(); a.onClick(); } }, a.label))) : null);
  box.append(t);
  while (box.children.length > 5) box.firstChild.remove();
  requestAnimationFrame(() => t.classList.add('show'));
  const ms = opts.timeout != null ? opts.timeout : type === 'error' ? 9000 : actions.length ? 12000 : 3800;
  let timer = setTimeout(close, ms);
  t.addEventListener('mouseenter', () => clearTimeout(timer));
  t.addEventListener('mouseleave', () => { clearTimeout(timer); timer = setTimeout(close, 2500); });
  function close() { clearTimeout(timer); t.classList.remove('show'); setTimeout(() => t.remove(), 220); }
  return close;
}
/** Báo lỗi cho người dùng. fixes.js đăng ký vào đây để gắn nút "Cách khắc phục" khi nhận ra lỗi quen (xem fixes.py). */
export const errorHooks = [];
export function showError(e, opts = {}) {
  const msg = (e && e.message) || String(e || 'Lỗi không rõ');
  if (errorHooks.length) errorHooks[0](msg, opts); else toast(msg, 'error', opts);
}
/** chạy fn, báo lỗi bằng toast; nếu có nút thì hiện trạng thái bận */
export async function busy(btn, fn) {
  if (btn) { btn.disabled = true; btn.classList.add('is-busy'); }
  try { return await fn(); } catch (e) { console.error(e); showError(e); return undefined; } finally {
    if (btn) { btn.disabled = false; btn.classList.remove('is-busy'); }
  }
}

export const modalStack = [];
export function openModal(content, { cls = '', onClose, dismissable = true, drawer = false } = {}) {
  const back = el('div', { class: 'modal-back' + (drawer ? ' drawer-back' : '') });
  const box = el('div', { class: 'modal ' + (drawer ? 'drawer ' : '') + cls, role: 'dialog', 'aria-modal': 'true' }, content);
  back.append(box);
  if (dismissable) back.addEventListener('mousedown', (e) => { if (e.target === back) m.close(); });
  $('#modal-root').append(back);
  requestAnimationFrame(() => back.classList.add('show'));
  const m = {
    box, dismissable,
    close(result) {
      const i = modalStack.indexOf(m);
      if (i < 0) return;
      modalStack.splice(i, 1);
      back.classList.remove('show');
      setTimeout(() => back.remove(), 200);
      if (onClose) onClose(result);
    },
  };
  modalStack.push(m);
  return m;
}
export function closeAllModals() { while (modalStack.length) modalStack[modalStack.length - 1].close(); }
export function modalHead(iconName, title, m, ...extra) {
  return el('div', { class: 'modal-head' }, icon(iconName), el('h3', { text: title }), extra,
    el('button', { class: 'btn btn-icon btn-ghost', title: 'Đóng', 'aria-label': 'Đóng', onclick: () => m().close() }, icon('x')));
}
export function confirmDialog(title, message, { okText = 'Đồng ý', cancelText = 'Hủy', danger = false } = {}) {
  return new Promise((resolve) => {
    let ok = false;
    const okBtn = el('button', { class: 'btn ' + (danger ? 'btn-danger' : 'btn-primary'), onclick: () => { ok = true; m.close(); } }, okText);
    const m = openModal([
      el('div', { class: 'modal-head' }, icon(danger ? 'alert' : 'info'), el('h3', { text: title })),
      el('div', { class: 'modal-body' }, el('p', { class: 'muted', text: message })),
      el('div', { class: 'modal-foot' }, el('button', { class: 'btn btn-ghost', onclick: () => m.close() }, cancelText), okBtn),
    ], { cls: 'modal-sm', onClose: () => resolve(ok) });
    setTimeout(() => okBtn.focus(), 60);
  });
}
export function promptDialog(title, label, { value = '', okText = 'Lưu', placeholder = '' } = {}) {
  return new Promise((resolve) => {
    let res = null;
    const inp = el('input', { class: 'input', value, placeholder, onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); done(); } } });
    const done = () => { res = inp.value.trim(); m.close(); };
    const m = openModal([
      el('div', { class: 'modal-head' }, icon('edit'), el('h3', { text: title })),
      el('div', { class: 'modal-body' }, el('label', { class: 'opt-label', text: label }), inp),
      el('div', { class: 'modal-foot' }, el('button', { class: 'btn btn-ghost', onclick: () => m.close() }, 'Hủy'),
        el('button', { class: 'btn btn-primary', onclick: done }, okText)),
    ], { cls: 'modal-sm', onClose: () => resolve(res) });
    setTimeout(() => { inp.focus(); inp.select(); }, 60);
  });
}
export function videoModal(url, title) {
  const v = el('video', { class: 'modal-video', controls: true, autoplay: true, playsinline: true, src: url });
  const m = openModal([
    modalHead('film', title || 'Xem video', () => m, el('a', { class: 'btn btn-sm btn-ghost', href: url, download: '' }, icon('download'), 'Tải về')),
    el('div', { class: 'modal-body center' }, v),
  ], { cls: 'modal-wide', onClose: () => v.pause() });
}

let curPop = null;
export function popMenu(anchor, items) {
  closePop();
  const r = anchor.getBoundingClientRect();
  const pop = el('div', { class: 'pop', role: 'menu' }, items.filter(Boolean).map((it) =>
    el('button', { class: it.danger ? 'danger' : '', role: 'menuitem', onclick: (e) => { e.stopPropagation(); closePop(); it.onClick(); } }, icon(it.icon), it.label)));
  pop.addEventListener('mousedown', (e) => e.stopPropagation());
  document.body.append(pop);
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  pop.style.left = clamp(r.right - pw, 8, window.innerWidth - pw - 8) + 'px';
  pop.style.top = (r.bottom + ph + 8 > window.innerHeight ? r.top - ph - 6 : r.bottom + 6) + 'px';
  curPop = pop;
  setTimeout(() => document.addEventListener('mousedown', closePop, { once: true }), 0);
}
export function closePop() { if (curPop) { curPop.remove(); curPop = null; return true; } return false; }

export async function copyText(t, note) {
  try { await navigator.clipboard.writeText(t); } catch (_) {
    const ta = el('textarea', { value: t, style: { position: 'fixed', opacity: '0', left: '-9999px' } });
    document.body.append(ta); ta.select(); document.execCommand('copy'); ta.remove();
  }
  toast(note || 'Đã sao chép', 'success', { timeout: 1600 });
}
export const copyBtn = (getText, label) => el('button', {
  class: 'btn btn-xs btn-ghost', title: 'Sao chép',
  onclick: () => copyText(typeof getText === 'function' ? getText() : getText),
}, icon('copy'), label || null);

export function emptyState(title, text, action, extraCls = '') {
  return el('div', { class: 'empty ' + extraCls }, icon('inbox', 'empty-ico'), el('h4', { text: title }), text ? el('p', { text }) : null, action || null);
}
export function errorState(msg, retry) {
  return el('div', { class: 'empty error' }, icon('alert', 'empty-ico'), el('h4', { text: 'Có lỗi xảy ra' }), el('p', { text: msg }),
    retry ? el('button', { class: 'btn btn-sm', onclick: retry }, icon('refresh'), 'Thử lại') : null);
}
export const loadingState = (text) => el('div', { class: 'loading-state' }, el('span', { class: 'spinner lg' }), el('span', { text }));

// ===================================================================== âm thanh dùng chung
export const audio = new Audio();
let audioBtn = null;
export function stopAudio() {
  audio.pause();
  if (audioBtn) { audioBtn.classList.remove('playing'); setIcon(audioBtn, 'play'); audioBtn = null; }
}
export const audioButton = () => audioBtn;
export function playUrl(url, btn) {
  if (btn && audioBtn === btn && !audio.paused) { stopAudio(); return; }
  stopAudio();
  if (S.studio && S.studio.pausePlayer) S.studio.pausePlayer();
  audio.src = url;
  audioBtn = btn || null;
  if (btn) { btn.classList.add('playing'); setIcon(btn, 'stop'); }
  audio.play().catch(() => { /* lỗi được báo qua sự kiện error */ });
}
audio.addEventListener('ended', stopAudio);
audio.addEventListener('error', () => {
  if (!audio.getAttribute('src')) return;
  toast('Chưa có file âm thanh (câu này chưa được lồng tiếng?)', 'warn');
  stopAudio();
});
const previewCache = new Map();
export function clearPreviewCache() { previewCache.clear(); }
export async function previewVoice(engine, voice, btn, lang = 'vi') {
  if (btn && audioBtn === btn && !audio.paused) { stopAudio(); return; }
  const key = engine + '|' + voice + '|' + lang;
  let url = previewCache.get(key);
  if (!url) {
    if (btn) { btn.disabled = true; btn.classList.add('is-busy'); }
    try {
      // máy chủ chọn câu mẫu đúng ngôn ngữ của giọng (langs.SAMPLES)
      const body = lang === 'vi' ? { engine, voice, text: PREVIEW_TEXT } : { engine, voice, lang };
      const blob = await api('POST', '/api/tts/preview', body, { blob: true });
      url = URL.createObjectURL(blob);
      previewCache.set(key, url);
    } catch (e) {
      toast('Không nghe thử được: ' + e.message, 'error');
      return;
    } finally {
      if (btn) { btn.disabled = false; btn.classList.remove('is-busy'); }
    }
  }
  playUrl(url, btn);
}
/** tiếng "ting" nhẹ khi video xong (có thể tắt trong Cài đặt) */
export function chime() {
  if (localStorage.getItem('ic.chime') === '0') return;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [[880, 0], [1318.5, 0.13]].forEach(([f, at]) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = 'sine'; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, ctx.currentTime + at);
      g.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + at + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + 0.55);
      o.connect(g).connect(ctx.destination);
      o.start(ctx.currentTime + at); o.stop(ctx.currentTime + at + 0.6);
    });
    setTimeout(() => ctx.close(), 1200);
  } catch (_) { /* không có âm thanh cũng không sao */ }
}

// ===================================================================== dữ liệu dùng chung
export const S = {
  config: null, defaults: null, user: null, cfgPath: '',
  voices: { vieneu: [], edge: [], vox: [], vox_ready: false, mine: [] }, voicesVersion: 0, langs: [],
  fonts: ['Arial'], status: null, queue: [], studio: null,
  lastStudio: localStorage.getItem('ic.lastStudio') || '',
};
export async function loadConfig() {
  const r = await api('GET', '/api/config');
  S.config = r.config || {};
  S.defaults = r.defaults || {};
  S.user = r.user || {};
  S.cfgPath = r.path || '';
  if (r.langs) S.langs = r.langs;
  if (r.vox_voices) { S.voices.vox = r.vox_voices; S.voices.vox_ready = !!r.vox_ready; }      // có ngay, không chờ /api/voices
  return r;
}
export async function ensureConfig() { if (!S.config) await loadConfig(); }
export const voiceHooks = new Set();
export async function loadVoices() {
  try {
    const r = await api('GET', '/api/voices');
    S.voices = { vieneu: r.vieneu || [], edge: r.edge || [], vox: r.vox || [], vox_ready: !!r.vox_ready, mine: r.mine || [] };
    if (r.langs) S.langs = r.langs;
    S.voicesVersion++;
    for (const f of [...voiceHooks]) { try { if (f() === false) voiceHooks.delete(f); } catch (e) { console.error(e); } }
  } catch (e) { console.warn('Không tải được danh sách giọng', e); }
}
export async function loadFonts() { try { S.fonts = (await api('GET', '/api/fonts')).fonts; } catch (_) { /* giữ mặc định */ } }
/** Bộ đọc thật sự dùng cho ngôn ngữ đích (giống voice.engine_for ở máy chủ): VieNeu chỉ đọc tiếng Việt. */
export function effEngine(engine, lang = 'vi') {
  const e = engine || 'vieneu';
  const voxOk = S.voices.vox_ready || !!(S.status && S.status.ai && S.status.ai.voices);
  if (e === 'vox' && !voxOk) return lang === 'vi' ? 'vieneu' : 'edge';
  if (lang !== 'vi' && e === 'vieneu') return voxOk ? 'vox' : 'edge';
  return e;
}
export function langName(code) { const l = (S.langs || []).find((x) => x.code === code); return l ? l.name : code; }
export function voiceList(engine, lang = 'vi') {
  if (engine === 'edge') {
    return S.voices.edge.filter((v) => (v.lang || 'vi') === lang).map((v) => {
      const g = genderOf(v.gender);
      const nm = String(v.id || '').replace(/^[a-z]{2,3}-[A-Z]{2}-/, '').replace(/Neural$/, '');
      return { id: v.id, gender: g, label: `${nm} (${g === 'female' ? 'nữ' : g === 'male' ? 'nam' : '?'})` };
    });
  }
  if (engine === 'vox') return (S.voices.vox || []).filter((v) => v.lang === lang).map((v) => ({ id: v.id, gender: v.gender, label: v.label }));
  return S.voices.vieneu.map((v) => ({ id: v.id, gender: genderOf(v.gender), label: v.label || v.id }));
}
/** Giọng có đọc được bằng bộ đọc này, cho ngôn ngữ này không (giống voice._fits_engine ở máy chủ). */
export function voiceFits(voice, engine, lang = 'vi') {
  const v = String(voice || '');
  if (!v) return false;
  if (v.startsWith('me:')) return mineFits(engine, lang);
  const isEdge = /-.*-.*Neural$/.test(v);
  const isVox = /^[a-z]{2}_[fm][12]$/.test(v);
  if (engine === 'edge') { const l = (S.langs || []).find((x) => x.code === lang); return isEdge && (!l || !l.edge_locale || v.startsWith(l.edge_locale + '-')); }
  if (engine === 'vox') return isVox && v.slice(0, 2) === lang;
  return !isEdge && !isVox && lang === 'vi';
}
/** Giọng mặc định theo bộ đọc, ngôn ngữ, giới tính (giống voice.default_voice ở máy chủ). */
export function defaultVoice(engine, lang = 'vi', gender = 'female') {
  const female = gender === 'female';
  if (engine === 'vox') { const v = (S.voices.vox || []).find((x) => x.lang === lang && x.id.endsWith(female ? '_f1' : '_m1')); return v ? v.id : ''; }
  if (engine === 'edge') {
    const l = (S.langs || []).find((x) => x.code === lang);
    return (l && (female ? l.edge_female : l.edge_male)) || (female ? 'vi-VN-HoaiMyNeural' : 'vi-VN-NamMinhNeural');
  }
  return female ? 'Trúc Ly' : 'Thiện Minh';
}
/** Giọng của tôi có dùng được với bộ đọc này không: VieNeu (tiếng Việt) và bộ đọc nhiều thứ tiếng (mọi ngôn ngữ) */
export const mineFits = (engine, lang = 'vi') => engine === 'vox' || (engine === 'vieneu' && lang === 'vi');
/** Giọng của tôi (mẫu tự thu) */
export function myVoiceList() {
  return (S.voices.mine || []).map((v) => ({ id: v.id, gender: genderOf(v.gender), label: v.name || 'Giọng của tôi', mine: true }));
}
export function voiceLabel(engine, id, lang = 'vi') {
  const v = [...voiceList(engine, lang), ...(engine === 'edge' ? [] : myVoiceList())].find((x) => x.id === id);
  return v ? v.label : String(id || '').startsWith('me:') ? 'Giọng của tôi (đã xóa)' : id;
}
export function fillVoiceSelect(sel, engine, { gender = '', current = '', defaultLabel = 'Mặc định', lang = 'vi' } = {}) {
  sel.replaceChildren(el('option', { value: '' }, defaultLabel));
  // giọng không đọc được bằng bộ đọc này, cho thị trường này (ví dụ giọng Việt khi lồng tiếng Indonesia): máy chủ sẽ dùng giọng mặc định
  if (current && !current.startsWith('me:') && !voiceFits(current, engine, lang)) current = '';
  const list = voiceList(engine, lang).filter((v) => !gender || v.gender === gender);
  // giọng tự thu hiện ở mọi ô, kể cả ô giọng nam hay nữ: người dùng tự biết giọng mình hợp vai nào
  const mine = mineFits(engine, lang) ? myVoiceList() : [];
  if (mine.length) sel.append(el('optgroup', { label: 'Giọng của tôi' }, mine.map((v) => el('option', { value: v.id }, v.label))));
  if (!gender && list.some((v) => v.gender)) {
    for (const [g, name] of [['male', 'Giọng nam'], ['female', 'Giọng nữ'], ['', 'Khác']]) {
      const items = list.filter((v) => v.gender === g);
      if (items.length) sel.append(el('optgroup', { label: name }, items.map((v) => el('option', { value: v.id }, v.label))));
    }
  } else {
    list.forEach((v) => sel.append(el('option', { value: v.id }, v.label)));
  }
  if (current && !list.some((v) => v.id === current) && !mine.some((v) => v.id === current)) {
    sel.append(el('option', { value: current }, current.startsWith('me:') ? 'Giọng của tôi (đã xóa)' : current + ' (tùy chỉnh)'));
  }
  sel.value = current || '';
}

export async function loadStatus() {
  try { S.status = await api('GET', '/api/status'); } catch (_) { S.status = null; }
  const dot = $('#sys-dot'), link = $('#sys-link');
  const s = S.status;
  if (!dot) return;
  if (!s) { dot.className = 'sys-dot bad'; link.title = 'Mất kết nối với iContent'; return; }
  const ready = s.translator && s.translator.ready;
  const lvl = !s.ffmpeg ? 'bad' : !ready ? 'warn' : 'ok';
  dot.className = 'sys-dot ' + lvl;
  link.title = !s.ffmpeg ? 'Thiếu FFmpeg' : !ready ? 'Chưa kết nối AI dịch: đang dùng Google miễn phí' : 'Sẵn sàng';
}

// ---- hàng đợi: hỏi lại 1s khi có việc, 5s khi rảnh
export const queueListeners = new Set();
let pollTimer = null, polling = false, pollAgain = false;
const seenDone = new Set();
let queueInit = false;
export async function pollQueue() {
  clearTimeout(pollTimer);
  if (polling) { pollAgain = true; return; }
  polling = true;
  try {
    const r = await api('GET', '/api/queue');
    S.queue = r.items || [];
    for (const fn of [...queueListeners]) { try { fn(S.queue); } catch (e) { console.error(e); } }
  } catch (e) { /* máy chủ tạm mất, thử lại sau */ }
  polling = false;
  const activeItems = S.queue.filter((i) => i.state === 'queued' || i.state === 'running');
  const n = activeItems.length;
  const onair = $('#onair');
  if (onair) {
    onair.hidden = !n;
    const c = onair.querySelector('.onair-n');
    if (c) c.textContent = n > 1 ? String(n) : '';
  }
  const run = activeItems.find((i) => i.state === 'running');
  const base = document.title.replace(/^\(\d+%\) /, '');
  document.title = run && typeof run.progress === 'number' ? `(${Math.round(run.progress * 100)}%) ${base}` : base;
  for (const i of S.queue) {
    if (!['done', 'error'].includes(i.state) || seenDone.has(i.qid)) continue;
    seenDone.add(i.qid);
    if (!queueInit) continue;
    if (i.state === 'done') chime();
    if (i.kind === 'prefetch') desktopNotify(i.state === 'done' ? 'Đã tải xong mô hình AI' : 'Tải mô hình AI bị lỗi', i.state === 'done' ? 'Máy đã sẵn sàng làm video' : (i.message || ''), '#/home');
    else desktopNotify(i.state === 'done' ? 'Video đã xong' : 'Video bị lỗi', i.title || '', i.story ? `#/story/${enc(i.story)}` : i.job ? `#/studio/${enc(i.job)}` : '#/library');
  }
  queueInit = true;
  const delay = pollAgain ? 120 : n ? 1000 : 5000;
  pollAgain = false;
  pollTimer = setTimeout(pollQueue, delay);
}
/** Thông báo của Windows (góc màn hình) khi người dùng không nhìn cửa sổ iContent. Bấm vào thì mở đúng chỗ. */
export function desktopNotify(title, body, href) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  if (document.visibilityState === 'visible' && document.hasFocus()) return;
  try {
    const n = new Notification(title, { body, icon: '/static/icon.png', tag: href || title });
    n.onclick = () => { window.focus(); if (href) location.hash = href; n.close(); };
  } catch (_) { /* trình duyệt không cho */ }
}
// xin quyền thông báo ở lần bấm đầu tiên (trình duyệt chỉ cho hỏi khi người dùng vừa bấm)
if ('Notification' in window && Notification.permission === 'default') {
  document.addEventListener('pointerdown', () => { Notification.requestPermission().catch(() => null); }, { once: true });
}
export function pollSoon() { clearTimeout(pollTimer); pollTimer = setTimeout(pollQueue, 150); }

export async function reveal(job) {
  try { await api('POST', `/api/jobs/${enc(job)}/reveal`); toast('Đã mở thư mục', 'success', { timeout: 1800 }); } catch (e) { toast(e.message, 'error'); }
}
export async function runJob(job, from_stage, extra) {
  const r = await api('POST', `/api/jobs/${enc(job)}/run`, Object.assign({ from_stage: from_stage || null }, extra || {}));
  pollSoon();
  return r;
}

// ---- thành phần hiển thị tiến độ
export function Tape() {
  const nodes = TAPE.map(([, label]) => {
    const fill = el('span', { class: 'tape-fill' });
    const root = el('div', { class: 'tape-seg' }, el('span', { class: 'tape-bar' }, fill), el('span', { class: 'tape-label', text: label }));
    return { root, fill };
  });
  const root = el('div', { class: 'tape' }, nodes.map((n) => n.root));
  return {
    root,
    set(stage, state, frac) {
      let cur = state === 'done' || stage === 'done' ? TAPE.length : stage && stage in STAGE_STEP ? STAGE_STEP[stage] : state === 'queued' ? -1 : 0;
      nodes.forEach((n, i) => {
        let c = 'tape-seg', w = 0;
        if (i < cur) { c += ' done'; w = 100; } else if (i === cur) {
          c += state === 'error' ? ' error' : state === 'cancelled' ? ' stopped' : state === 'running' ? ' active' : '';
          w = state === 'running' && typeof frac === 'number' ? clamp(frac, 0, 1) * 100 : state === 'running' ? 100 : 40;
        }
        n.root.className = c;
        n.fill.style.width = w + '%';
      });
    },
  };
}
