/* Trang Thumbnail: thiết kế ảnh thumbnail cho video vừa làm (câu chuyện của Kể chuyện, video của Studio).
 * Nền lấy từ ảnh từng cảnh hoặc khung hình đẹp nhất (đã xóa sub gốc), các lớp chữ, mũi tên, vòng tròn, emoji, logo kéo thả trên canvas.
 * Mẫu dựng sẵn, AI gợi ý chữ, xem thử cỡ hiện trên điện thoại, vùng bị giao diện nền tảng che. Lưu xong ảnh nằm cạnh video, cùng tên.
 * Địa chỉ: #/thumb | #/thumb/<story|job>/<mã> */
import { S, api, busy, el, emptyState, enc, fmtAgo, icon, modalHead, openModal, toast } from './core.js';

const SIZES = { '16:9': [1280, 720], '9:16': [1080, 1920], '1:1': [1080, 1080] };
const ASPECT_LABEL = { '16:9': 'YouTube 16:9', '9:16': 'TikTok, Shorts 9:16', '1:1': 'Vuông 1:1' };
const MAIN_FONT = 'Be Vietnam Pro';
const WEIGHTS = [['600', 'Đậm vừa'], ['700', 'Đậm'], ['800', 'Rất đậm']];
const EMOJI = ['😱', '🔥', '😂', '❤️', '👉', '⚠️', '✅', '❌', '💰', '⭐', '🤯', '👀'];
const uid = () => 'l' + Math.random().toString(36).slice(2, 9);

// ------------------------------------------------------------------ mẫu
function textLayer(o) {
  return {
    id: uid(), type: 'text', role: '', text: '', x: 0.5, y: 0.5, size: 0.13, font: MAIN_FONT, weight: '800', color: '#FFFFFF', color2: '',
    stroke: 0.12, strokeColor: '#000000', shadow: 0.35, box: '', boxAlpha: 0.85, upper: true, rot: 0, maxw: 0.9, lh: 1.08, align: 'center', ...o,
  };
}
const TEMPLATES = [
  { id: 'vang', name: 'Vàng nổi bật', make: (t, s, a) => ({
    bg: { vignette: 0.45, scrim: 0.35 },
    layers: [textLayer({ role: 'main', text: t, x: a === '9:16' ? 0.5 : 0.36, y: a === '9:16' ? 0.62 : 0.66, size: a === '9:16' ? 0.15 : 0.16, color: '#FFE01B', maxw: a === '9:16' ? 0.9 : 0.66, rot: -3, align: a === '9:16' ? 'center' : 'left' }),
      ...(s ? [textLayer({ role: 'sub', text: s, x: a === '9:16' ? 0.5 : 0.2, y: a === '9:16' ? 0.45 : 0.18, size: 0.065, color: '#FFFFFF', box: '#E5242B', stroke: 0, shadow: 0.2, rot: -3, maxw: 0.6 })] : [])] }) },
  { id: 'haimau', name: 'Hai màu', make: (t, s, a) => {
    const w = t.split(/\s+/);
    const cut = Math.max(1, Math.ceil(w.length / 2));
    return { bg: { vignette: 0.4, scrim: 0.45 },
      layers: [textLayer({ role: 'main', text: w.slice(0, cut).join(' '), x: 0.5, y: a === '9:16' ? 0.6 : 0.6, size: a === '9:16' ? 0.14 : 0.15, color: '#FFFFFF' }),
        textLayer({ role: 'main2', text: w.slice(cut).join(' ') || s, x: 0.5, y: a === '9:16' ? 0.7 : 0.8, size: a === '9:16' ? 0.14 : 0.15, color: '#FFB224' })] };
  } },
  { id: 'nhan', name: 'Nhãn đỏ', make: (t, s, a) => ({
    bg: { vignette: 0.35, scrim: 0.3 },
    layers: [textLayer({ role: 'sub', text: s || 'MỚI', x: a === '9:16' ? 0.5 : 0.17, y: a === '9:16' ? 0.18 : 0.15, size: 0.07, box: '#E5242B', stroke: 0, shadow: 0.1, maxw: 0.5 }),
      textLayer({ role: 'main', text: t, x: 0.5, y: a === '9:16' ? 0.68 : 0.72, size: a === '9:16' ? 0.13 : 0.14, color: '#FFFFFF', stroke: 0.14 })] }) },
  { id: 'hop', name: 'Hộp đen', make: (t, s, a) => ({
    bg: { vignette: 0.2, scrim: 0 },
    layers: [textLayer({ role: 'main', text: t, x: 0.5, y: a === '9:16' ? 0.66 : 0.76, size: a === '9:16' ? 0.11 : 0.12, color: '#FFFFFF', box: '#0B0B0B', boxAlpha: 0.78, stroke: 0, shadow: 0, maxw: 0.86 }),
      ...(s ? [textLayer({ role: 'sub', text: s, x: 0.5, y: a === '9:16' ? 0.56 : 0.56, size: 0.06, color: '#14110C', box: '#FFB224', boxAlpha: 1, stroke: 0, shadow: 0, maxw: 0.6 })] : [])] }) },
  { id: 'toigian', name: 'Tối giản', make: (t, s, a) => ({
    bg: { vignette: 0.25, scrim: 0 },
    layers: [textLayer({ role: 'main', text: t, x: 0.5, y: a === '9:16' ? 0.16 : 0.18, size: a === '9:16' ? 0.1 : 0.11, weight: '700', upper: false, stroke: 0, shadow: 0.6, maxw: 0.86 })] }) },
  { id: 'soc', name: 'Gây chú ý', make: (t, s, a) => ({
    bg: { vignette: 0.5, scrim: 0.25 },
    layers: [textLayer({ role: 'main', text: t, x: a === '9:16' ? 0.5 : 0.34, y: a === '9:16' ? 0.7 : 0.7, size: a === '9:16' ? 0.15 : 0.16, color: '#FFFFFF', color2: '#FFE01B', stroke: 0.14, strokeColor: '#C1121F', maxw: a === '9:16' ? 0.9 : 0.62, align: a === '9:16' ? 'center' : 'left', rot: -2 }),
      { id: uid(), type: 'shape', shape: 'circle', x: a === '9:16' ? 0.5 : 0.72, y: a === '9:16' ? 0.33 : 0.42, w: a === '9:16' ? 0.42 : 0.26, h: a === '9:16' ? 0.42 : 0.26, color: '#E5242B', thick: 0.07, rot: 0 },
      { id: uid(), type: 'shape', shape: 'arrow', x: a === '9:16' ? 0.24 : 0.57, y: a === '9:16' ? 0.48 : 0.47, w: 0.2, h: 0.12, color: '#E5242B', thick: 0.3, rot: a === '9:16' ? -40 : -20 }] }) },
];

function newDoc(aspect, src) {
  return { v: 1, aspect, bg: { src: src || '', zoom: 1, fx: 0.5, fy: 0.42, bright: 0, contrast: 0.08, sat: 0.15, blur: 0, vignette: 0.4, scrim: 0.3, flip: false }, layers: [] };
}

// ------------------------------------------------------------------ vẽ
const imgCache = new Map();
function getImg(url, onload) {
  if (!url) return null;
  let it = imgCache.get(url);
  if (!it) {
    it = new Image();
    it.decoding = 'async';
    it.onload = () => onload && onload();
    it.src = url;
    imgCache.set(url, it);
  }
  return it.complete && it.naturalWidth ? it : null;
}

function fontOf(L, px) { return `${L.italic ? 'italic ' : ''}${L.weight || '800'} ${px}px "${L.font || MAIN_FONT}", "Segoe UI", sans-serif`; }

function wrap(ctx, text, maxW) {
  const out = [];
  for (const para of String(text || '').split('\n')) {
    let cur = '';
    // chữ Trung, Nhật không có dấu cách, hoặc một từ quá dài: cắt theo từng ký tự, không để tràn khung
    const words = para.split(/\s+/).filter(Boolean).flatMap((w) => (ctx.measureText(w).width > maxW ? [...w] : [w]));
    for (const w of words) {
      const glue = cur && /[぀-ヿ㐀-鿿]/.test(w + cur.slice(-1)) ? '' : ' ';
      const t = cur ? cur + glue + w : w;
      if (!cur || ctx.measureText(t).width <= maxW) cur = t; else { out.push(cur); cur = w; }
    }
    out.push(cur);
  }
  return out;
}

/** Khung (theo tọa độ cục bộ, gốc ở tâm lớp) và hàm vẽ của một lớp. */
function measure(ctx, L, W, H) {
  const U = Math.min(W, H);
  if (L.type === 'text') {
    const px = Math.max(6, L.size * U);
    ctx.font = fontOf(L, px);
    const txt = L.upper ? String(L.text || '').toLocaleUpperCase('vi') : String(L.text || '');
    const lines = wrap(ctx, txt, L.maxw * W);
    const lh = px * (L.lh || 1.08);
    const widths = lines.map((ln) => ctx.measureText(ln).width);
    const pad = L.box ? px * 0.32 : px * 0.08;
    const w = Math.max(10, ...widths) + pad * 2;
    const h = lines.length * lh + pad * 2 - (lh - px) * 0.4;
    return { w, h, px, lines, lh, widths, pad };
  }
  if (L.type === 'image') {
    const im = getImg(L.src);
    const w = L.w * W;
    const h = im ? w * im.naturalHeight / im.naturalWidth : w;
    return { w, h };
  }
  if (L.shape === 'emoji') return { w: L.h * U * 1.15, h: L.h * U * 1.15 };
  return { w: L.w * U, h: L.h * U };
}

function drawLayer(ctx, L, W, H, redraw) {
  const m = measure(ctx, L, W, H);
  ctx.save();
  ctx.translate(L.x * W, L.y * H);
  ctx.rotate((L.rot || 0) * Math.PI / 180);
  ctx.globalAlpha = L.opacity == null ? 1 : L.opacity;
  if (L.type === 'text') {
    const { px, lines, lh, widths, pad } = m;
    ctx.font = fontOf(L, px);
    ctx.textBaseline = 'middle';
    const top = -m.h / 2 + pad + px * 0.5;
    const xOf = (w) => (L.align === 'left' ? -m.w / 2 + pad : L.align === 'right' ? m.w / 2 - pad - w : -w / 2);
    if (L.box) {
      ctx.save();
      ctx.globalAlpha *= L.boxAlpha == null ? 0.85 : L.boxAlpha;
      ctx.fillStyle = L.box;
      ctx.beginPath();
      ctx.roundRect(-m.w / 2, -m.h / 2, m.w, m.h, px * 0.18);
      ctx.fill();
      ctx.restore();
    }
    lines.forEach((ln, i) => {
      const y = top + i * lh;
      const x = xOf(widths[i]);
      if (L.stroke > 0) {
        ctx.save();
        if (L.shadow > 0) { ctx.shadowColor = 'rgba(0,0,0,0.65)'; ctx.shadowBlur = px * 0.25 * L.shadow; ctx.shadowOffsetY = px * 0.06 * L.shadow; }
        ctx.lineJoin = 'round';
        ctx.miterLimit = 2;
        ctx.lineWidth = L.stroke * px;
        ctx.strokeStyle = L.strokeColor || '#000';
        ctx.strokeText(ln, x, y);
        ctx.restore();
      }
      ctx.save();
      if (L.shadow > 0 && !(L.stroke > 0)) { ctx.shadowColor = 'rgba(0,0,0,0.7)'; ctx.shadowBlur = px * 0.3 * L.shadow; ctx.shadowOffsetY = px * 0.05 * L.shadow; }
      if (L.color2) {
        const g = ctx.createLinearGradient(0, y - px / 2, 0, y + px / 2);
        g.addColorStop(0, L.color);
        g.addColorStop(1, L.color2);
        ctx.fillStyle = g;
      } else ctx.fillStyle = L.color || '#fff';
      ctx.fillText(ln, x, y);
      ctx.restore();
    });
  } else if (L.type === 'image') {
    const im = getImg(L.src, redraw);
    if (im) {
      ctx.shadowColor = 'rgba(0,0,0,0.45)';
      ctx.shadowBlur = m.w * 0.04;
      ctx.drawImage(im, -m.w / 2, -m.h / 2, m.w, m.h);
    }
  } else {
    const { w, h } = m;
    const U = Math.min(W, H);
    ctx.strokeStyle = L.color;
    ctx.fillStyle = L.color;
    ctx.shadowColor = 'rgba(0,0,0,0.5)';
    ctx.shadowBlur = U * 0.012;
    if (L.shape === 'circle') {
      ctx.lineWidth = Math.max(2, L.thick * Math.min(w, h));
      ctx.beginPath();
      ctx.ellipse(0, 0, Math.max(1, w / 2 - ctx.lineWidth / 2), Math.max(1, h / 2 - ctx.lineWidth / 2), 0, 0, Math.PI * 2);
      ctx.stroke();
    } else if (L.shape === 'rect') {
      ctx.lineWidth = Math.max(2, L.thick * Math.min(w, h));
      ctx.beginPath();
      ctx.roundRect(-w / 2 + ctx.lineWidth / 2, -h / 2 + ctx.lineWidth / 2, w - ctx.lineWidth, h - ctx.lineWidth, Math.min(w, h) * 0.08);
      ctx.stroke();
    } else if (L.shape === 'arrow') {
      const t = Math.max(0.12, L.thick || 0.3) * h;
      const head = Math.min(w * 0.45, h);
      ctx.beginPath();
      ctx.moveTo(-w / 2, -t / 2);
      ctx.lineTo(w / 2 - head, -t / 2);
      ctx.lineTo(w / 2 - head, -h / 2);
      ctx.lineTo(w / 2, 0);
      ctx.lineTo(w / 2 - head, h / 2);
      ctx.lineTo(w / 2 - head, t / 2);
      ctx.lineTo(-w / 2, t / 2);
      ctx.closePath();
      ctx.lineJoin = 'round';
      ctx.lineWidth = U * 0.008;
      ctx.strokeStyle = '#FFFFFF';
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.stroke();
    } else if (L.shape === 'emoji') {
      ctx.shadowBlur = 0;
      ctx.font = `${h * 0.85}px "Segoe UI Emoji", "Apple Color Emoji", sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(L.text || '🔥', 0, h * 0.04);
    }
  }
  ctx.restore();
  return m;
}

function drawBg(ctx, doc, W, H, redraw) {
  const b = doc.bg;
  ctx.fillStyle = '#16130F';
  ctx.fillRect(0, 0, W, H);
  const im = getImg(b.src, redraw);
  if (im) {
    const s = Math.max(W / im.naturalWidth, H / im.naturalHeight) * (b.zoom || 1);
    const dw = im.naturalWidth * s;
    const dh = im.naturalHeight * s;
    let x = W / 2 - b.fx * dw;
    let y = H / 2 - b.fy * dh;
    x = Math.min(0, Math.max(W - dw, x));
    y = Math.min(0, Math.max(H - dh, y));
    ctx.save();
    ctx.filter = `brightness(${1 + (b.bright || 0)}) contrast(${1 + (b.contrast || 0)}) saturate(${1 + (b.sat || 0)})${b.blur ? ` blur(${(b.blur * W / 100).toFixed(1)}px)` : ''}`;
    if (b.flip) { ctx.translate(W, 0); ctx.scale(-1, 1); x = W - x - dw; }
    ctx.drawImage(im, x, y, dw, dh);
    ctx.restore();
  }
  if (b.scrim > 0) {
    const g = ctx.createLinearGradient(0, H * 0.4, 0, H);
    g.addColorStop(0, 'rgba(0,0,0,0)');
    g.addColorStop(1, `rgba(0,0,0,${Math.min(0.9, b.scrim)})`);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
  }
  if (b.vignette > 0) {
    const r = Math.hypot(W, H) / 2;
    const g = ctx.createRadialGradient(W / 2, H / 2, r * 0.35, W / 2, H / 2, r);
    g.addColorStop(0, 'rgba(0,0,0,0)');
    g.addColorStop(1, `rgba(0,0,0,${Math.min(0.95, b.vignette)})`);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
  }
}

function renderDoc(ctx, doc, W, H, redraw) {
  drawBg(ctx, doc, W, H, redraw);
  const boxes = new Map();
  for (const L of doc.layers) boxes.set(L.id, drawLayer(ctx, L, W, H, redraw));
  return boxes;
}

/** Vùng giao diện nền tảng che mất (nút, mô tả, thời lượng). */
function drawSafe(ctx, aspect, W, H) {
  ctx.save();
  ctx.fillStyle = 'rgba(229, 36, 43, 0.22)';
  ctx.strokeStyle = 'rgba(229, 36, 43, 0.7)';
  ctx.setLineDash([6, 5]);
  const zones = aspect === '9:16' ? [[0.86, 0.3, 0.14, 0.52], [0, 0.8, 1, 0.2], [0, 0, 1, 0.07]]
    : aspect === '16:9' ? [[0.82, 0.84, 0.18, 0.16]] : [[0, 0.86, 1, 0.14]];
  for (const [x, y, w, h] of zones) { ctx.fillRect(x * W, y * H, w * W, h * H); ctx.strokeRect(x * W, y * H, w * W, h * H); }
  ctx.restore();
}

async function fontsReady(doc) {
  const fams = new Set(doc.layers.filter((l) => l.type === 'text').map((l) => `${l.weight || '800'} 40px "${l.font || MAIN_FONT}"`));
  await Promise.all([...fams].map((f) => document.fonts.load(f, 'ẮẰẲẴẶÂẤẦ Đđ ơư').catch(() => null)));
}

async function loadAll(doc) {
  const urls = [doc.bg.src, ...doc.layers.filter((l) => l.type === 'image').map((l) => l.src)].filter(Boolean);
  await Promise.all(urls.map((u) => new Promise((res) => { const im = getImg(u, res); if (im) res(); else setTimeout(res, 8000); })));
  await fontsReady(doc);
}

export async function renderFull(doc) {
  const [W, H] = SIZES[doc.aspect] || SIZES['16:9'];
  await loadAll(doc);
  const c = document.createElement('canvas');
  c.width = W;
  c.height = H;
  renderDoc(c.getContext('2d'), doc, W, H);
  return c;
}

// ------------------------------------------------------------------ trang
export async function viewThumbnail(main, alive, arg) {
  main.classList.add('view-thumb');
  const [kind0, id0] = (arg || '').split('/');
  const { items: sources } = await api('GET', '/api/thumbs/sources');
  if (!alive()) return null;
  if (!kind0) {
    if (!sources.length) {
      main.classList.add('view-pad');
      main.append(emptyState('Chưa có video nào để làm thumbnail', 'Làm một video ở Tạo video hoặc Kể chuyện, rồi quay lại đây. Thumbnail lưu cạnh video, cùng tên.',
        el('div', { class: 'btn-row' }, el('a', { class: 'btn btn-primary', href: '#/story' }, icon('film'), 'Kể chuyện'), el('a', { class: 'btn', href: '#/new' }, icon('play'), 'Tạo video'))));
      return null;
    }
    location.replace(`#/thumb/${sources[0].kind}/${enc(sources[0].id)}`);
    return null;
  }
  const info = await api('GET', `/api/thumbs/${kind0}/${enc(id0)}`);
  if (!alive()) return null;
  await document.fonts.load(`800 40px "${MAIN_FONT}"`, 'Đ').catch(() => null);

  // ---------- trạng thái
  let doc = info.project && info.project.v === 1 ? info.project : null;
  const firstBg = (info.backgrounds[0] || {}).url || '';
  if (!doc) {
    doc = newDoc(SIZES[info.aspect] ? info.aspect : '16:9', firstBg);
    Object.assign(doc, applyTemplate(doc, TEMPLATES[0], info.title, ''));
  }
  let sel = null;      // id lớp đang chọn
  let showSafe = true;
  let dirty = false;
  const hist = [JSON.stringify(doc)];
  let hpos = 0;
  let histTimer = 0;
  function commit(now = false) {
    dirty = true;
    clearTimeout(histTimer);
    const push = () => {
      const s = JSON.stringify(doc);
      if (s === hist[hpos]) return;
      hist.splice(hpos + 1);
      hist.push(s);
      if (hist.length > 80) hist.shift();
      hpos = hist.length - 1;
    };
    if (now) push(); else histTimer = setTimeout(push, 350);
  }
  function undo(step) {
    const n = hpos + step;
    if (n < 0 || n >= hist.length) return;
    hpos = n;
    const aspectBefore = doc.aspect;
    doc = JSON.parse(hist[hpos]);
    if (!doc.layers.some((l) => l.id === sel)) sel = null;
    if (doc.aspect !== aspectBefore) {      // hoàn tác cả việc đổi khung: vẽ lại đúng cỡ, nút khung đúng
      [...aspSeg.children].forEach((b) => b.classList.toggle('active', b.dataset.v === doc.aspect));
      fit();
    }
    paintAll();
  }
  const layerOf = (id) => doc.layers.find((l) => l.id === id);

  // ---------- canvas
  const cv = el('canvas', { class: 'th-canvas' });
  const ctx = cv.getContext('2d');
  const stage = el('div', { class: 'th-stage' }, cv);
  let boxes = new Map();
  let scale = 1;
  let raf = 0;
  const redraw = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; draw(); }); };
  function fit() {
    const [W, H] = SIZES[doc.aspect];
    const r = stage.getBoundingClientRect();
    const s = Math.min((r.width - 24) / W, (r.height - 24) / H);
    scale = Math.max(0.05, s);
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(W * scale * dpr);
    cv.height = Math.round(H * scale * dpr);
    cv.style.width = `${Math.round(W * scale)}px`;
    cv.style.height = `${Math.round(H * scale)}px`;
    redraw();
  }
  function draw() {
    const [W, H] = SIZES[doc.aspect];
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(scale * dpr, 0, 0, scale * dpr, 0, 0);
    boxes = renderDoc(ctx, doc, W, H, redraw);
    if (showSafe) drawSafe(ctx, doc.aspect, W, H);
    const L = layerOf(sel);
    if (L && boxes.get(L.id)) {
      const m = boxes.get(L.id);
      ctx.save();
      ctx.translate(L.x * W, L.y * H);
      ctx.rotate((L.rot || 0) * Math.PI / 180);
      ctx.lineWidth = 2 / scale;
      ctx.strokeStyle = '#FFB224';
      ctx.setLineDash([8 / scale, 6 / scale]);
      ctx.strokeRect(-m.w / 2, -m.h / 2, m.w, m.h);
      ctx.setLineDash([]);
      const hs = 9 / scale;
      ctx.fillStyle = '#FFB224';
      ctx.fillRect(m.w / 2 - hs / 2, m.h / 2 - hs / 2, hs, hs);      // kéo để phóng to, thu nhỏ
      ctx.beginPath();
      ctx.moveTo(0, -m.h / 2);
      ctx.lineTo(0, -m.h / 2 - 26 / scale);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(0, -m.h / 2 - 30 / scale, 6 / scale, 0, Math.PI * 2);      // kéo để xoay
      ctx.fill();
      ctx.restore();
    }
    paintMini();
  }

  // ---------- chuột: chọn, kéo, phóng, xoay, kéo nền
  function local(L, px, py) {
    const [W, H] = SIZES[doc.aspect];
    const a = -(L.rot || 0) * Math.PI / 180;
    const dx = px - L.x * W;
    const dy = py - L.y * H;
    return [dx * Math.cos(a) - dy * Math.sin(a), dx * Math.sin(a) + dy * Math.cos(a)];
  }
  function pointer(e) {
    const r = cv.getBoundingClientRect();
    return [(e.clientX - r.left) / scale, (e.clientY - r.top) / scale];
  }
  let drag = null;
  cv.addEventListener('pointerdown', (e) => {
    cv.setPointerCapture(e.pointerId);
    const [px, py] = pointer(e);
    const [W, H] = SIZES[doc.aspect];
    const cur = layerOf(sel);
    if (cur && boxes.get(cur.id)) {
      const m = boxes.get(cur.id);
      const [lx, ly] = local(cur, px, py);
      const tol = 14 / scale;
      if (Math.abs(lx - m.w / 2) < tol && Math.abs(ly - m.h / 2) < tol) { drag = { mode: 'scale', L: cur, start: Math.hypot(lx, ly), orig: { ...cur } }; return; }
      if (Math.hypot(lx, ly + m.h / 2 + 30 / scale) < tol) { drag = { mode: 'rot', L: cur }; return; }
    }
    const hit = [...doc.layers].reverse().find((L) => {
      const m = boxes.get(L.id);
      if (!m) return false;
      const [lx, ly] = local(L, px, py);
      return Math.abs(lx) <= m.w / 2 && Math.abs(ly) <= m.h / 2;
    });
    if (hit) {
      sel = hit.id;
      drag = { mode: 'move', L: hit, ox: px - hit.x * W, oy: py - hit.y * H };
    } else {
      sel = null;
      drag = { mode: 'bg', sx: px, sy: py, fx: doc.bg.fx, fy: doc.bg.fy };
    }
    paintInspector();
    redraw();
  });
  cv.addEventListener('pointermove', (e) => {
    const [px, py] = pointer(e);
    const [W, H] = SIZES[doc.aspect];
    if (!drag) {
      const cur = layerOf(sel);
      let c = 'default';
      if (cur && boxes.get(cur.id)) {
        const m = boxes.get(cur.id);
        const [lx, ly] = local(cur, px, py);
        if (Math.abs(lx - m.w / 2) < 14 / scale && Math.abs(ly - m.h / 2) < 14 / scale) c = 'nwse-resize';
        else if (Math.hypot(lx, ly + m.h / 2 + 30 / scale) < 14 / scale) c = 'grab';
        else if (Math.abs(lx) <= m.w / 2 && Math.abs(ly) <= m.h / 2) c = 'move';
      }
      cv.style.cursor = c;
      return;
    }
    const L = drag.L;
    if (drag.mode === 'move') {
      let nx = (px - drag.ox) / W;
      let ny = (py - drag.oy) / H;
      if (Math.abs(nx - 0.5) < 0.012) nx = 0.5;      // hút vào giữa
      if (Math.abs(ny - 0.5) < 0.012) ny = 0.5;
      L.x = Math.round(nx * 1000) / 1000;
      L.y = Math.round(ny * 1000) / 1000;
    } else if (drag.mode === 'scale') {
      const [lx, ly] = local(L, px, py);
      const k = Math.max(0.15, Math.min(6, Math.hypot(lx, ly) / Math.max(1, drag.start)));
      if (L.type === 'text') L.size = Math.max(0.02, Math.min(0.5, drag.orig.size * k));
      else if (L.type === 'image') L.w = Math.max(0.03, Math.min(2, drag.orig.w * k));
      else { L.w = Math.max(0.02, drag.orig.w * k); L.h = Math.max(0.02, drag.orig.h * k); }
    } else if (drag.mode === 'rot') {
      let a = Math.atan2(py - L.y * H, px - L.x * W) * 180 / Math.PI + 90;
      if (a > 180) a -= 360;
      if (Math.abs(a) < 3) a = 0;
      L.rot = Math.round(a);
    } else if (drag.mode === 'bg') {
      const im = getImg(doc.bg.src);
      if (im) {
        const s = Math.max(W / im.naturalWidth, H / im.naturalHeight) * (doc.bg.zoom || 1);
        doc.bg.fx = Math.max(0, Math.min(1, drag.fx - (px - drag.sx) / (im.naturalWidth * s) * (doc.bg.flip ? -1 : 1)));
        doc.bg.fy = Math.max(0, Math.min(1, drag.fy - (py - drag.sy) / (im.naturalHeight * s)));
      }
    }
    redraw();
  });
  cv.addEventListener('pointerup', () => {
    if (drag) { drag = null; commit(true); paintInspector(); }
  });
  cv.addEventListener('wheel', (e) => {
    if (sel) return;
    e.preventDefault();
    doc.bg.zoom = Math.max(1, Math.min(4, (doc.bg.zoom || 1) * (e.deltaY < 0 ? 1.06 : 1 / 1.06)));
    commit();
    redraw();
    paintInspector();
  }, { passive: false });
  cv.addEventListener('dblclick', () => { const t = inspector.querySelector('textarea'); if (t) { t.focus(); t.select(); } });

  const keyHandler = (e) => {
    if (!main.isConnected) return;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !typing) { e.preventDefault(); undo(e.shiftKey ? 1 : -1); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y' && !typing) { e.preventDefault(); undo(1); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); saveBtn.click(); return; }
    if (typing) return;
    const L = layerOf(sel);
    if (!L) return;
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); removeLayer(L.id); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'd') { e.preventDefault(); duplicate(L); return; }
    if (e.key === 'Escape') { sel = null; paintInspector(); redraw(); return; }
    const step = e.shiftKey ? 0.02 : 0.003;
    const mv = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
    if (mv) { e.preventDefault(); L.x += mv[0]; L.y += mv[1]; commit(); redraw(); }
  };
  document.addEventListener('keydown', keyHandler);

  // ---------- lớp
  function addLayer(L) { doc.layers.push(L); sel = L.id; commit(true); paintAll(); }
  function removeLayer(id) { doc.layers = doc.layers.filter((l) => l.id !== id); if (sel === id) sel = null; commit(true); paintAll(); }
  function duplicate(L) { addLayer({ ...JSON.parse(JSON.stringify(L)), id: uid(), x: Math.min(0.95, L.x + 0.03), y: Math.min(0.95, L.y + 0.03) }); }
  function reorder(L, d) {
    const i = doc.layers.indexOf(L);
    const j = Math.max(0, Math.min(doc.layers.length - 1, i + d));
    doc.layers.splice(i, 1);
    doc.layers.splice(j, 0, L);
    commit(true);
    paintAll();
  }

  // ---------- thanh công cụ
  const tool = (ic, label, fn, title) => el('button', { class: 'btn btn-sm', title: title || label, onclick: fn }, icon(ic), label);
  const emojiBtn = tool('star', 'Emoji', (e) => {
    const pop = el('div', { class: 'th-emoji' }, EMOJI.map((em) => el('button', { class: 'th-emoji-b', onclick: () => { pop.remove(); addLayer({ id: uid(), type: 'shape', shape: 'emoji', text: em, x: 0.8, y: 0.25, w: 0.18, h: 0.18, color: '#fff', rot: 0 }); } }, em)));
    e.currentTarget.after(pop);
    setTimeout(() => document.addEventListener('pointerdown', function off(ev) { if (!pop.contains(ev.target)) { pop.remove(); document.removeEventListener('pointerdown', off); } }), 0);
  });
  const safeBtn = el('button', { class: 'btn btn-sm active', title: 'Hiện vùng bị nút và mô tả của nền tảng che (chỉ để xem, không có trong ảnh)', onclick: () => { showSafe = !showSafe; safeBtn.classList.toggle('active', showSafe); redraw(); } }, icon('eye'), 'Vùng che');
  const toolbar = el('div', { class: 'th-tools' },
    tool('type', 'Chữ', () => addLayer(textLayer({ text: 'CHỮ MỚI', y: 0.3, size: 0.1, color: '#FFFFFF' }))),
    tool('arrow', 'Mũi tên', () => addLayer({ id: uid(), type: 'shape', shape: 'arrow', x: 0.5, y: 0.5, w: 0.22, h: 0.13, color: '#E5242B', thick: 0.32, rot: 0 })),
    tool('target', 'Vòng tròn', () => addLayer({ id: uid(), type: 'shape', shape: 'circle', x: 0.5, y: 0.45, w: 0.3, h: 0.3, color: '#E5242B', thick: 0.06, rot: 0 })),
    tool('square', 'Khung', () => addLayer({ id: uid(), type: 'shape', shape: 'rect', x: 0.5, y: 0.45, w: 0.36, h: 0.24, color: '#FFE01B', thick: 0.05, rot: 0 })),
    emojiBtn,
    tool('image', 'Logo, ảnh', () => pickLibrary()),
    el('span', { class: 'grow' }),
    el('button', { class: 'btn btn-sm btn-icon', title: 'Hoàn tác (Ctrl+Z)', 'aria-label': 'Hoàn tác', onclick: () => undo(-1) }, icon('undo')),
    el('button', { class: 'btn btn-sm btn-icon', title: 'Làm lại (Ctrl+Y)', 'aria-label': 'Làm lại', onclick: () => undo(1) }, icon('redo')),
    safeBtn);

  async function pickLibrary() {
    const items = (await api('GET', '/api/images')).items || [];
    let m;
    const up = el('input', { type: 'file', accept: 'image/*', hidden: true, onchange: () => busy(null, async () => { const f = up.files[0]; if (!f) return; const r = await uploadBg(f); m.close(); addImageLayer(r.url); }) });
    const grid = el('div', { class: 'th-lib' }, items.length ? items.map((it) => el('button', { class: 'th-lib-it', title: it.name, onclick: () => { m.close(); addImageLayer(it.url); } }, el('img', { src: it.url, alt: '' })))
      : el('p', { class: 'dim small', text: 'Thư viện ảnh trống. Tải một ảnh logo hoặc sticker (nên là PNG nền trong suốt).' }));
    m = openModal([modalHead('image', 'Thêm logo hoặc ảnh', () => m), el('div', { class: 'modal-body' }, el('div', { class: 'btn-row' }, el('button', { class: 'btn btn-sm', onclick: () => up.click() }, icon('upload'), 'Tải ảnh từ máy'), up), grid)], { cls: 'modal-md' });
  }
  function addImageLayer(url) { addLayer({ id: uid(), type: 'image', src: url, x: 0.82, y: 0.2, w: 0.22, rot: 0 }); }
  async function uploadBg(file) {
    const res = await fetch('/api/thumb-bg', { method: 'PUT', body: file });
    if (!res.ok) { let msg = `Lỗi ${res.status}`; try { msg = (await res.json()).detail || msg; } catch (_) { /* */ } throw new Error(msg); }
    return res.json();
  }

  // ---------- bảng trái: video, ảnh nền, khung hình
  const srcSel = el('select', { class: 'input', 'aria-label': 'Video', onchange: () => { location.hash = `#/thumb/${srcSel.value}`; } },
    sources.map((s) => el('option', { value: `${s.kind}/${s.id}`, selected: s.kind === kind0 && s.id === id0 }, `${s.kind === 'story' ? 'Kể chuyện' : 'Video'}: ${s.title}`)));
  const aspSeg = el('div', { class: 'seg th-asp' }, Object.keys(SIZES).map((a) => el('button', {
    type: 'button', class: 'seg-btn' + (a === doc.aspect ? ' active' : ''), 'data-v': a, title: ASPECT_LABEL[a],
    onclick: () => { doc.aspect = a; commit(true); [...aspSeg.children].forEach((b) => b.classList.toggle('active', b.dataset.v === a)); fit(); paintTemplates(); },
  }, a)));
  const bgGrid = el('div', { class: 'th-bgs' });
  function paintBgs() {
    bgGrid.replaceChildren(...info.backgrounds.map((b) => el('button', {
      class: 'th-bg' + (b.url === doc.bg.src ? ' active' : ''), title: b.label,
      onclick: () => { doc.bg.src = b.url; doc.bg.fx = 0.5; doc.bg.fy = 0.42; doc.bg.zoom = 1; commit(true); paintBgs(); redraw(); paintTemplates(); },
    }, el('img', { src: b.url, alt: b.label, loading: 'lazy' }), el('span', { text: b.label }))));
  }
  const bgUp = el('input', { type: 'file', accept: 'image/*', hidden: true, onchange: () => busy(null, async () => {
    const f = bgUp.files[0];
    bgUp.value = '';
    if (!f) return;
    const r = await uploadBg(f);
    info.backgrounds.unshift({ url: r.url, label: 'Ảnh của tôi' });
    doc.bg.src = r.url;
    commit(true);
    paintBgs();
    redraw();
  }) });
  let frameRow = null;
  if (kind0 === 'job' && info.duration) {      // chọn khung bất kỳ trong video (đã xóa sub gốc)
    const tIn = el('input', { type: 'range', min: 0, max: Math.max(1, Math.floor(info.duration)), step: 0.5, value: 0 });
    const tLab = el('span', { class: 'mono small', text: '0:00' });
    const useBtn = el('button', { class: 'btn btn-xs', onclick: () => {
      const url = `/api/jobs/${enc(id0)}/frame.jpg?t=${Number(tIn.value).toFixed(2)}&clean=1`;
      info.backgrounds.unshift({ url, label: tLab.textContent });
      doc.bg.src = url;
      commit(true);
      paintBgs();
      redraw();
    } }, 'Dùng khung này');
    tIn.oninput = () => { const t = Number(tIn.value); tLab.textContent = `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`; };
    frameRow = el('div', { class: 'th-frame' }, el('span', { class: 'label', text: 'Khung khác trong video' }), el('div', { class: 'th-frame-row' }, tIn, tLab, useBtn));
  }
  const left = el('aside', { class: 'th-left' },
    el('label', { class: 'field' }, el('span', { class: 'label', text: 'Video' }), srcSel),
    el('label', { class: 'field' }, el('span', { class: 'label', text: 'Khung ảnh' }), aspSeg),
    el('div', { class: 'th-sec' }, el('span', { class: 'label', text: kind0 === 'story' ? 'Ảnh nền: ảnh từng cảnh' : 'Ảnh nền: khung hình đẹp nhất' }), bgGrid,
      el('div', { class: 'btn-row' }, el('button', { class: 'btn btn-xs', onclick: () => bgUp.click() }, icon('upload'), 'Ảnh từ máy'), bgUp)),
    frameRow || '');

  // ---------- bảng phải: mẫu, AI gợi ý, thuộc tính
  const tplBox = el('div', { class: 'th-tpls' });
  function mainText() {
    const m = doc.layers.find((l) => l.role === 'main') || doc.layers.find((l) => l.type === 'text');
    const m2 = doc.layers.find((l) => l.role === 'main2');
    return [m ? m.text : info.title, m2 ? m2.text : ''].filter(Boolean).join(' ');
  }
  const subText = () => (doc.layers.find((l) => l.role === 'sub') || {}).text || '';
  function paintTemplates() {
    const [W, H] = SIZES[doc.aspect];
    const tw = 132;
    tplBox.replaceChildren(...TEMPLATES.map((t) => {
      const c = el('canvas', { width: tw * 2, height: Math.round(tw * 2 * H / W) });
      const b = el('button', { class: 'th-tpl', title: `Mẫu ${t.name}`, onclick: () => { Object.assign(doc, applyTemplate(doc, t, mainText(), subText())); sel = null; commit(true); paintAll(); } }, c, el('span', { text: t.name }));
      const preview = { ...doc, ...applyTemplate(doc, t, mainText(), subText()) };
      const g = c.getContext('2d');
      g.scale(c.width / W, c.height / H);
      renderDoc(g, preview, W, H, () => paintTemplates());
      return b;
    }));
  }
  const sugBox = el('div', { class: 'th-sugs' });
  const sugBtn = el('button', { class: 'btn btn-sm', title: 'AI đọc nội dung video, gợi ý 6 câu chữ ngắn, gây tò mò', onclick: () => busy(sugBtn, async () => {
    sugBox.replaceChildren(el('span', { class: 'dim small', text: 'AI đang đọc nội dung video…' }));
    try {
      const { items } = await api('POST', `/api/thumbs/${kind0}/${enc(id0)}/suggest`);
      sugBox.replaceChildren(...items.map((it) => el('button', { class: 'th-sug', title: 'Dùng chữ này', onclick: () => {
        const m = doc.layers.find((l) => l.role === 'main') || doc.layers.find((l) => l.type === 'text');
        const m2 = doc.layers.find((l) => l.role === 'main2');
        if (m2) {
          const w = it.main.split(/\s+/);
          const cut = Math.max(1, Math.ceil(w.length / 2));
          m.text = w.slice(0, cut).join(' ');
          m2.text = w.slice(cut).join(' ');
        } else if (m) m.text = it.main; else doc.layers.push(textLayer({ role: 'main', text: it.main, y: 0.7 }));
        const s = doc.layers.find((l) => l.role === 'sub');
        if (s && it.sub) s.text = it.sub;
        commit(true);
        paintAll();
      } }, el('b', { text: it.main }), it.sub ? el('span', { text: it.sub }) : '')));
    } catch (e) { sugBox.replaceChildren(); throw e; }
  }) }, icon('spark'), 'AI gợi ý chữ');
  const inspector = el('div', { class: 'th-insp' });

  const field = (label, input) => el('label', { class: 'field th-f' }, el('span', { class: 'label', text: label }), input);
  function range(obj, key, min, max, step, label, fmt = (v) => v) {
    const out = el('span', { class: 'mono small', text: fmt(Number(obj[key] || 0)) });
    const r = el('input', { type: 'range', min, max, step, value: obj[key] || 0, oninput: () => { obj[key] = Number(r.value); out.textContent = fmt(obj[key]); commit(); redraw(); } });
    return el('div', { class: 'th-range' }, el('span', { class: 'small', text: label }), r, out);
  }
  function color(obj, key, label, allowEmpty = false) {
    const inp = el('input', { type: 'color', class: 'color-input', value: obj[key] || '#ffffff', oninput: () => { obj[key] = inp.value.toUpperCase(); if (off) off.checked = true; commit(); redraw(); } });
    const off = allowEmpty ? el('input', { type: 'checkbox', checked: !!obj[key], title: 'Bật', onchange: () => { obj[key] = off.checked ? inp.value.toUpperCase() : ''; commit(); redraw(); } }) : null;
    return el('label', { class: 'th-color' }, off || '', inp, el('span', { class: 'small', text: label }));
  }
  function paintInspector() {
    const L = layerOf(sel);
    if (!L) {
      const b = doc.bg;
      inspector.replaceChildren(el('h4', { text: 'Ảnh nền' }), el('p', { class: 'dim small', text: 'Kéo trên ảnh để dời, lăn chuột để phóng to. Bấm vào chữ, hình để sửa.' }),
        range(b, 'zoom', 1, 4, 0.05, 'Phóng to', (v) => `${v.toFixed(2)}x`),
        range(b, 'bright', -0.5, 0.6, 0.02, 'Độ sáng', (v) => `${Math.round(v * 100)}`),
        range(b, 'contrast', -0.4, 0.8, 0.02, 'Tương phản', (v) => `${Math.round(v * 100)}`),
        range(b, 'sat', -1, 1, 0.02, 'Màu đậm', (v) => `${Math.round(v * 100)}`),
        range(b, 'blur', 0, 2, 0.05, 'Làm mờ', (v) => v.toFixed(2)),
        range(b, 'vignette', 0, 0.9, 0.02, 'Tối viền', (v) => `${Math.round(v * 100)}`),
        range(b, 'scrim', 0, 0.9, 0.02, 'Tối phía dưới', (v) => `${Math.round(v * 100)}`),
        el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: !!b.flip, onchange: (e) => { b.flip = e.target.checked; commit(true); redraw(); } }), ' Lật ngang ảnh nền'));
      return;
    }
    const common = el('div', { class: 'btn-row th-lacts' },
      el('button', { class: 'btn btn-xs btn-icon', title: 'Đưa lên trên', 'aria-label': 'Đưa lên trên', onclick: () => reorder(L, 1) }, icon('up')),
      el('button', { class: 'btn btn-xs btn-icon', title: 'Đưa xuống dưới', 'aria-label': 'Đưa xuống dưới', onclick: () => reorder(L, -1) }, icon('chev')),
      el('button', { class: 'btn btn-xs', title: 'Nhân đôi (Ctrl+D)', onclick: () => duplicate(L) }, icon('copy'), 'Nhân đôi'),
      el('span', { class: 'grow' }),
      el('button', { class: 'btn btn-xs btn-danger', title: 'Xóa (Delete)', onclick: () => removeLayer(L.id) }, icon('trash'), 'Xóa'));
    if (L.type === 'text') {
      const ta = el('textarea', { class: 'input', rows: 3, value: L.text, oninput: () => { L.text = ta.value; commit(); redraw(); } });
      const fontSel = el('select', { class: 'input', onchange: () => { L.font = fontSel.value; document.fonts.load(fontOf(L, 40), 'Đ').finally(redraw); commit(true); } },
        [MAIN_FONT, ...(S.fonts || [])].filter((f, i, a) => a.indexOf(f) === i).map((f) => el('option', { value: f, selected: f === L.font }, f)));
      const wSel = el('select', { class: 'input', onchange: () => { L.weight = wSel.value; document.fonts.load(fontOf(L, 40), 'Đ').finally(redraw); commit(true); } },
        WEIGHTS.map(([v, l]) => el('option', { value: v, selected: v === L.weight }, l)));
      const alignSeg = el('div', { class: 'seg' }, [['left', 'Trái'], ['center', 'Giữa'], ['right', 'Phải']].map(([v, l]) => el('button', { type: 'button', class: 'seg-btn' + (L.align === v ? ' active' : ''), onclick: () => { L.align = v; commit(true); paintInspector(); redraw(); } }, l)));
      inspector.replaceChildren(el('h4', { text: 'Chữ' }), ta,
        el('div', { class: 'th-two' }, field('Phông', fontSel), field('Độ đậm', wSel)),
        range(L, 'size', 0.03, 0.4, 0.005, 'Cỡ chữ', (v) => `${Math.round(v * 100)}`),
        range(L, 'maxw', 0.2, 1, 0.01, 'Rộng tối đa', (v) => `${Math.round(v * 100)}%`),
        el('div', { class: 'th-colors' }, color(L, 'color', 'Màu chữ'), color(L, 'color2', 'Chuyển màu', true), color(L, 'strokeColor', 'Màu viền'), color(L, 'box', 'Nền hộp', true)),
        range(L, 'stroke', 0, 0.3, 0.01, 'Viền', (v) => `${Math.round(v * 100)}`),
        range(L, 'shadow', 0, 1, 0.05, 'Bóng đổ', (v) => `${Math.round(v * 100)}`),
        L.box ? range(L, 'boxAlpha', 0.2, 1, 0.02, 'Độ đậm hộp', (v) => `${Math.round(v * 100)}%`) : '',
        range(L, 'rot', -30, 30, 1, 'Xoay', (v) => `${v}°`),
        range(L, 'lh', 0.85, 1.6, 0.01, 'Giãn dòng', (v) => v.toFixed(2)),
        el('div', { class: 'th-two' }, alignSeg, el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: !!L.upper, onchange: (e) => { L.upper = e.target.checked; commit(true); redraw(); } }), ' CHỮ HOA')),
        common);
    } else if (L.type === 'image') {
      inspector.replaceChildren(el('h4', { text: 'Ảnh, logo' }), range(L, 'w', 0.03, 1.2, 0.01, 'Cỡ', (v) => `${Math.round(v * 100)}%`),
        range(L, 'rot', -45, 45, 1, 'Xoay', (v) => `${v}°`), range(L, 'opacity', 0.1, 1, 0.02, 'Độ rõ', (v) => `${Math.round((v || 1) * 100)}%`), common);
    } else {
      const name = { arrow: 'Mũi tên', circle: 'Vòng tròn', rect: 'Khung', emoji: 'Emoji' }[L.shape];
      inspector.replaceChildren(el('h4', { text: name }),
        L.shape === 'emoji' ? range(L, 'h', 0.05, 0.6, 0.01, 'Cỡ', (v) => `${Math.round(v * 100)}`) : color(L, 'color', 'Màu'),
        L.shape !== 'emoji' ? range(L, 'w', 0.05, 1, 0.01, 'Rộng', (v) => `${Math.round(v * 100)}`) : '',
        L.shape !== 'emoji' ? range(L, 'h', 0.03, 1, 0.01, 'Cao', (v) => `${Math.round(v * 100)}`) : '',
        L.shape !== 'emoji' ? range(L, 'thick', 0.02, 0.6, 0.01, 'Độ dày', (v) => `${Math.round(v * 100)}`) : '',
        range(L, 'rot', -180, 180, 1, 'Xoay', (v) => `${v}°`), common);
    }
  }

  // ---------- xem thử cỡ trên điện thoại
  const mini = el('canvas', { class: 'th-mini' });
  const miniCap = el('span', { class: 'dim small' });
  function paintMini() {
    const [W, H] = SIZES[doc.aspect];
    const w = doc.aspect === '9:16' ? 110 : doc.aspect === '1:1' ? 150 : 236;      // cỡ thật trên lưới video của ứng dụng điện thoại
    const h = Math.round(w * H / W);
    const dpr = window.devicePixelRatio || 1;
    mini.width = w * dpr;
    mini.height = h * dpr;
    mini.style.width = `${w}px`;
    mini.style.height = `${h}px`;
    const g = mini.getContext('2d');
    g.setTransform(w * dpr / W, 0, 0, h * dpr / H, 0, 0);
    renderDoc(g, doc, W, H);
    miniCap.textContent = doc.aspect === '16:9' ? 'Cỡ hiện ở trang chủ YouTube trên điện thoại' : 'Cỡ hiện trong lưới video TikTok, Reels';
  }

  // ---------- lưu
  let savedInfo = info.image;
  const status = el('span', { class: 'dim small th-status', text: savedInfo ? 'Đã có thumbnail' : 'Chưa lưu' });
  const saveBtn = el('button', { class: 'btn btn-primary', title: 'Lưu thumbnail cạnh video (Ctrl+S)', onclick: () => busy(saveBtn, async () => {
    const c = await renderFull(doc);
    const blob = await new Promise((res) => c.toBlob(res, 'image/jpeg', 0.93));
    const res = await fetch(`/api/thumbs/${kind0}/${enc(id0)}?aspect=${enc(doc.aspect)}`, { method: 'PUT', body: blob });
    if (!res.ok) { let msg = `Lỗi ${res.status}`; try { msg = (await res.json()).detail || msg; } catch (_) { /* */ } throw new Error(msg); }
    const r = await res.json();
    await api('PUT', `/api/thumbs/${kind0}/${enc(id0)}/project`, doc);
    dirty = false;
    savedInfo = r.url;
    status.textContent = 'Đã lưu ' + fmtAgo(Date.now() / 1000);
    toast('Đã lưu thumbnail cạnh video, cùng tên: ' + r.path.split(/[\\/]/).pop(), 'success', { timeout: 5000 });
  }) }, icon('save'), 'Lưu thumbnail');
  const dlBtn = el('button', { class: 'btn', title: 'Tải ảnh về máy', onclick: () => busy(dlBtn, async () => {
    const c = await renderFull(doc);
    const blob = await new Promise((res) => c.toBlob(res, 'image/jpeg', 0.93));
    const a = el('a', { href: URL.createObjectURL(blob), download: `thumbnail_${(info.title || 'video').replace(/[\\/:*?"<>|]+/g, ' ').slice(0, 50)}_${doc.aspect.replace(':', 'x')}.jpg` });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }) }, icon('download'), 'Tải về');

  function paintAll() { paintInspector(); paintBgs(); paintTemplates(); redraw(); }

  main.append(
    el('div', { class: 'th-head' }, icon('image'), el('b', { text: 'Thumbnail' }), el('span', { class: 'dim th-title', text: info.title }),
      el('span', { class: 'grow' }), status, dlBtn, saveBtn),
    el('div', { class: 'th-body' },
      left,
      el('section', { class: 'th-center' }, toolbar, stage, el('div', { class: 'th-minirow' }, mini, miniCap)),
      el('aside', { class: 'th-right' },
        el('div', { class: 'th-sec' }, el('h4', { text: 'Mẫu' }), tplBox),
        el('div', { class: 'th-sec' }, el('div', { class: 'th-sugh' }, el('h4', { text: 'Chữ' }), sugBtn), sugBox),
        el('div', { class: 'th-sec' }, inspector))));
  const ro = new ResizeObserver(() => fit());
  ro.observe(stage);
  paintAll();
  fit();
  const before = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } };
  window.addEventListener('beforeunload', before);
  return () => { ro.disconnect(); document.removeEventListener('keydown', keyHandler); window.removeEventListener('beforeunload', before); };
}

function applyTemplate(doc, t, main, sub) {
  const made = t.make(String(main || '').trim() || 'TIÊU ĐỀ', String(sub || '').trim(), doc.aspect);
  const keep = doc.layers.filter((l) => l.type === 'image' || (l.type === 'shape' && l.shape === 'emoji'));      // logo, emoji người dùng thêm thì giữ
  return { bg: { ...doc.bg, ...made.bg }, layers: [...made.layers, ...keep] };
}
