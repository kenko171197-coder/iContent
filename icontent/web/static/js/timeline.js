/* Timeline nhiều track vẽ bằng canvas: thước thời gian, sóng âm gốc, sóng âm giọng lồng, khối phụ đề, lớp phủ.
 * Kéo trên sóng âm để chọn đoạn. Đoạn đã cắt vẫn hiện (gạch chéo) vì đây là dựng không phá gốc.
 * Mọi thời gian ở đây là thời gian của video gốc. */
import { clamp, el, fmtTime, icon, speakerColor } from './core.js';

const C = {
  bg: '#0c0e12', track: '#13161c', trackAlt: '#101318', line: '#232833', tick: '#454b58', label: '#8f97a5',
  zh: '#5f93cc', zhDim: 'rgba(111,168,232,.10)', dub: '#ff6b4a', dubDim: 'rgba(255,107,74,.10)',
  block: '#22262f', blockHi: '#2e333e', blockEdge: '#3a404c', blockText: '#e6e9ef', on: '#ff6b4a', onText: '#1b0f0b',
  warn: '#ffc24b', bad: '#ff4f7b', head: '#ff4f7b', view: 'rgba(225,232,245,.16)',
  cut: 'rgba(8,10,14,.72)', cutLine: 'rgba(255,79,123,.55)', sel: 'rgba(255,107,74,.20)', selEdge: '#ff6b4a',
  ovText: '#3a5f8a', ovImage: '#6a4a8a', ovOn: '#ff6b4a', scene: 'rgba(225,232,245,.2)',
};
const GUTTER = 72, RULER = 24, OVERVIEW = 12, MIN_DUR = 0.2, EDGE = 7;
const TICKS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];

export function Timeline({ duration, getSegs, getTime, getActive, onSeek, onSelect, onDrag, onCommit, onOpen, getCuts, getOverlays, getOverlaySel, getScenes, onSelRange, onCutRestore, onOverlayPick, onOverlayDrag, onOverlayCommit, actions }) {
  const canvas = el('canvas', { class: 'tl-canvas', tabindex: '0', 'aria-label': 'Timeline. Dùng danh sách câu bên trái để sửa bằng bàn phím.' });
  const zoomLabel = el('span', { class: 'tl-zoom mono' });
  const hint = el('span', { class: 'tl-hint', text: 'Kéo trên sóng âm để chọn đoạn, tự hít vào điểm chuyển cảnh và đầu câu (giữ Alt để tắt) · Ctrl + lăn chuột để phóng to' });
  const selInfo = el('span', { class: 'tl-sel mono', hidden: true });
  const cutBtn = el('button', { class: 'btn btn-xs btn-accent', title: 'Cắt bỏ đoạn đã chọn (Delete)', disabled: true, onclick: () => actions.cut() }, icon('scissors'), 'Cắt đoạn');
  const keepBtn = el('button', { class: 'btn btn-xs', title: 'Chỉ giữ đoạn đã chọn, cắt hết phần còn lại', disabled: true, onclick: () => actions.keep() }, 'Chỉ giữ đoạn này');
  const clipBtn = el('button', { class: 'btn btn-xs', title: 'Xuất đoạn đã chọn thành một video riêng', disabled: true, onclick: () => actions.exportClip() }, icon('export'), 'Xuất clip');
  const root = el('div', { class: 'tl' },
    el('div', { class: 'tl-bar' }, icon('layers'), el('span', { class: 'tl-name', text: 'Timeline' }),
      el('button', { class: 'btn btn-xs', title: 'Đặt điểm đầu đoạn tại kim phát (phím I)', onclick: () => markIn() }, 'Điểm đầu'),
      el('button', { class: 'btn btn-xs', title: 'Đặt điểm cuối đoạn tại kim phát (phím O)', onclick: () => markOut() }, 'Điểm cuối'),
      cutBtn, keepBtn, clipBtn, selInfo, hint, el('span', { class: 'grow' }),
      el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Thu nhỏ (−)', 'aria-label': 'Thu nhỏ', onclick: () => zoom(1 / 1.5) }, icon('minus')),
      zoomLabel,
      el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Phóng to (+)', 'aria-label': 'Phóng to', onclick: () => zoom(1.5) }, icon('plus')),
      el('button', { class: 'btn btn-xs btn-ghost', title: 'Xem cả video (0)', onclick: () => fit() }, 'Vừa khung')),
    canvas);

  const ctx = canvas.getContext('2d');
  const T = {
    root, pps: 0, sx: 0, w: 0, h: 0, dpr: 1, peaks: { audio: null, dub: null }, hover: -1, hoverEdge: '', drag: null,
    follow: true, raf: 0, draw: requestDraw, setPeaks, fit, zoomBy: zoom, reveal, destroy, sel: null, markIn, markOut, setSel, clearSel,
  };
  const dur = () => Math.max(1, duration());
  const tracks = () => {
    const top = RULER, total = T.h - RULER - OVERVIEW;
    const hasOv = (getOverlays() || []).length > 0;
    const wave = Math.max(hasOv ? 22 : 26, Math.floor(total * (hasOv ? 0.24 : 0.3)));
    const rest = total - 2 * wave;
    if (!hasOv) return { zh: [top, wave], dub: [top + wave, wave], sub: [top + 2 * wave, rest], ov: null };
    const ovH = Math.max(22, Math.floor(rest * 0.4));
    return { zh: [top, wave], dub: [top + wave, wave], sub: [top + 2 * wave, rest - ovH], ov: [top + 2 * wave + rest - ovH, ovH] };
  };
  function setSel(a, b) {
    T.sel = a == null ? null : [Math.min(a, b), Math.max(a, b)];
    const on = !!T.sel && T.sel[1] - T.sel[0] > 0.05;
    cutBtn.disabled = keepBtn.disabled = clipBtn.disabled = !on;
    selInfo.hidden = !T.sel;
    hint.hidden = !!T.sel;
    if (T.sel) selInfo.textContent = `${fmtTime(T.sel[0])} → ${fmtTime(T.sel[1])} (${(T.sel[1] - T.sel[0]).toFixed(1).replace('.', ',')} giây)`;
    if (onSelRange) onSelRange(T.sel);
    requestDraw();
  }
  function clearSel() { setSel(null); }
  function markIn() { const t = getTime(); setSel(t, T.sel && T.sel[1] > t ? T.sel[1] : Math.min(dur(), t + 1)); }
  function markOut() { const t = getTime(); setSel(T.sel && T.sel[0] < t ? T.sel[0] : Math.max(0, t - 1), t); }
  const x2t = (x) => (x - GUTTER + T.sx) / T.pps;
  const t2x = (t) => GUTTER + t * T.pps - T.sx;
  const minPps = () => (T.w - GUTTER - 8) / dur();
  function clampScroll() { T.sx = clamp(T.sx, 0, Math.max(0, dur() * T.pps - (T.w - GUTTER - 8))); }
  function fit() { T.pps = minPps(); T.sx = 0; paintZoom(); requestDraw(); }
  function zoom(f, atX) {
    const ax = atX != null ? atX : clamp(t2x(getTime()), GUTTER, T.w);
    const t = x2t(ax);
    T.pps = clamp(T.pps * f, minPps(), 400);
    T.sx = t * T.pps - (ax - GUTTER);
    clampScroll(); paintZoom(); requestDraw();
  }
  function paintZoom() { const r = T.pps / Math.max(1e-6, minPps()); zoomLabel.textContent = r < 1.05 ? 'Vừa' : Math.round(r * 100) + '%'; }
  /** đưa một đoạn thời gian vào khung nhìn */
  function reveal(a, b) {
    const left = T.sx / T.pps, right = (T.sx + T.w - GUTTER - 8) / T.pps;
    if (a < left || b > right) { T.sx = a * T.pps - (T.w - GUTTER) * 0.2; clampScroll(); requestDraw(); }
  }
  function setPeaks(name, data) {
    if (!data || !data.peaks || !data.peaks.length) { T.peaks[name] = null; requestDraw(); return; }
    T.peaks[name] = { rate: data.rate, v: Uint8Array.from(data.peaks) };
    requestDraw();
  }
  function requestDraw() { if (!T.raf) T.raf = requestAnimationFrame(draw); }

  function drawWave(name, band, color) {
    const p = T.peaks[name];
    const [y, h] = band;
    if (!p) {
      ctx.fillStyle = C.label; ctx.font = '11px "Be Vietnam Pro",sans-serif'; ctx.textBaseline = 'middle';
      ctx.fillText(name === 'dub' ? 'Chưa có giọng lồng' : 'Chưa có âm thanh', GUTTER + 10, y + h / 2);
      return;
    }
    const mid = y + h / 2, amp = h / 2 - 3;
    ctx.fillStyle = color;
    const start = Math.floor(GUTTER), end = Math.min(T.w, t2x(dur()));
    const perPx = p.rate / T.pps;
    for (let x = start; x < end; x += 2) {
      const i0 = Math.floor(x2t(x) * p.rate);
      const i1 = Math.max(i0 + 1, Math.floor(i0 + perPx * 2));
      let m = 0;
      const stop = Math.min(i1, p.v.length);
      for (let i = Math.max(0, i0); i < stop; i++) if (p.v[i] > m) m = p.v[i];
      const a = Math.max(0.5, (m / 255) * amp);
      ctx.fillRect(x, mid - a, 1.4, a * 2);
    }
  }
  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, Math.min(r, w / 2, h / 2));
  }
  function draw() {
    T.raf = 0;
    const { w, h, dpr } = T;
    if (!w) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = C.bg; ctx.fillRect(0, 0, w, h);
    const tr = tracks();
    const segs = getSegs();
    const act = getActive();
    ctx.fillStyle = C.track; ctx.fillRect(GUTTER, tr.zh[0], w - GUTTER, tr.zh[1]);
    ctx.fillStyle = C.trackAlt; ctx.fillRect(GUTTER, tr.dub[0], w - GUTTER, tr.dub[1]);
    ctx.fillStyle = C.track; ctx.fillRect(GUTTER, tr.sub[0], w - GUTTER, tr.sub[1]);

    // vùng có lời trên hai track âm thanh
    ctx.save();
    ctx.beginPath(); ctx.rect(GUTTER, 0, w - GUTTER, h); ctx.clip();
    for (const s of segs) {
      const a = t2x(s.start), b = t2x(s.end);
      if (b >= GUTTER && a <= w) { ctx.fillStyle = C.zhDim; ctx.fillRect(a, tr.zh[0], b - a, tr.zh[1]); }
      if (s.dub_start != null) {
        const c = t2x(s.dub_start), d = t2x(s.dub_end != null ? s.dub_end : s.end);
        if (d >= GUTTER && c <= w) { ctx.fillStyle = C.dubDim; ctx.fillRect(c, tr.dub[0], d - c, tr.dub[1]); }
      }
    }
    drawWave('audio', tr.zh, C.zh);
    drawWave('dub', tr.dub, C.dub);

    // điểm chuyển cảnh: vạch mảnh trên hai track âm thanh
    ctx.fillStyle = C.scene;
    for (const t of getScenes ? getScenes() : []) {
      const x = t2x(t);
      if (x < GUTTER || x > w) continue;
      ctx.fillRect(x, tr.zh[0], 1, tr.sub[0] - tr.zh[0]);
      ctx.beginPath(); ctx.moveTo(x - 3, tr.zh[0]); ctx.lineTo(x + 4, tr.zh[0]); ctx.lineTo(x + 0.5, tr.zh[0] + 5); ctx.closePath(); ctx.fill();
    }

    // khối phụ đề
    const [sy, sh] = tr.sub;
    const by = sy + 5, bh = Math.max(20, sh - 10);
    ctx.textBaseline = 'middle';
    ctx.font = '500 12px "Be Vietnam Pro",sans-serif';
    const manySpeakers = new Set(segs.map((s) => s.speaker).filter(Boolean)).size > 1;
    segs.forEach((s, i) => {
      const a = t2x(s.start), b = t2x(s.end);
      if (b < GUTTER || a > w) return;
      const on = i === act, hov = i === T.hover;
      roundRect(a + 0.5, by, Math.max(2, b - a - 1), bh, 5);
      ctx.fillStyle = on ? C.on : hov ? C.blockHi : C.block;
      ctx.fill();
      if (manySpeakers && s.speaker) { ctx.fillStyle = speakerColor(s.speaker); ctx.fillRect(a + 1.5, by + 3, 3, Math.max(2, bh - 6)); }
      const fast = Number(s.speed) > 1.3;
      if (!(s.trans || '').trim()) { ctx.strokeStyle = C.bad; ctx.setLineDash([3, 3]); ctx.lineWidth = 1; ctx.stroke(); ctx.setLineDash([]); } else if (!on) { ctx.strokeStyle = C.blockEdge; ctx.lineWidth = 1; ctx.stroke(); }
      if (fast) { ctx.fillStyle = Number(s.speed) > 1.5 ? C.bad : C.warn; ctx.fillRect(a + 3, by + bh - 4, Math.max(2, b - a - 7), 2); }
      if (b - a > 26) {
        ctx.save();
        ctx.beginPath(); ctx.rect(a + 6, by, b - a - 12, bh); ctx.clip();
        ctx.fillStyle = on ? C.onText : C.blockText;
        ctx.fillText(s.trans || s.text || '', a + 7, by + bh / 2 + 0.5);
        ctx.restore();
      }
      if ((on || hov) && b - a > 16) {  // tay cầm hai đầu
        ctx.fillStyle = on ? 'rgba(26,18,4,.55)' : C.label;
        ctx.fillRect(a + 3, by + bh / 2 - 6, 2, 12);
        ctx.fillRect(b - 5, by + bh / 2 - 6, 2, 12);
      }
    });

    // lớp phủ
    if (tr.ov) {
      const [oy0, oh] = tr.ov;
      ctx.fillStyle = C.trackAlt; ctx.fillRect(GUTTER, oy0, w - GUTTER, oh);
      const curOv = getOverlaySel ? getOverlaySel() : -1;
      (getOverlays() || []).forEach((o, i) => {
        const a = t2x(o.start), b = t2x(o.end);
        if (b < GUTTER || a > w) return;
        const on = i === curOv;
        roundRect(a + 0.5, oy0 + 3, Math.max(3, b - a - 1), oh - 6, 4);
        ctx.fillStyle = on ? C.ovOn : o.type === 'image' ? C.ovImage : C.ovText;
        ctx.fill();
        if (b - a > 22) {
          ctx.save();
          ctx.beginPath(); ctx.rect(a + 5, oy0, b - a - 10, oh); ctx.clip();
          ctx.fillStyle = on ? C.onText : '#fff';
          ctx.font = '500 11px "Be Vietnam Pro",sans-serif';
          ctx.fillText(o.type === 'image' ? 'Ảnh' : String(o.text || ''), a + 6, oy0 + oh / 2 + 0.5);
          ctx.restore();
        }
      });
    }

    // đoạn đã cắt: phủ tối và gạch chéo trên mọi track
    const bottom = h - OVERVIEW;
    for (const [ca, cb] of getCuts ? getCuts() : []) {
      const a = t2x(ca), b = t2x(cb);
      if (b < GUTTER || a > w) continue;
      ctx.fillStyle = C.cut; ctx.fillRect(a, RULER, b - a, bottom - RULER);
      ctx.save();
      ctx.beginPath(); ctx.rect(a, RULER, b - a, bottom - RULER); ctx.clip();
      ctx.strokeStyle = C.cutLine; ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x0 = a - (bottom - RULER); x0 < b; x0 += 12) { ctx.moveTo(x0, bottom); ctx.lineTo(x0 + (bottom - RULER), RULER); }
      ctx.stroke();
      ctx.restore();
      ctx.fillStyle = C.bad; ctx.fillRect(a, RULER, 1.5, bottom - RULER); ctx.fillRect(b - 1.5, RULER, 1.5, bottom - RULER);
    }
    // đoạn đang chọn
    if (T.sel) {
      const a = t2x(T.sel[0]), b = t2x(T.sel[1]);
      ctx.fillStyle = C.sel; ctx.fillRect(a, RULER, b - a, bottom - RULER);
      ctx.fillStyle = C.selEdge; ctx.fillRect(a - 0.5, RULER, 1.5, bottom - RULER); ctx.fillRect(b - 0.5, RULER, 1.5, bottom - RULER);
    }

    // thước thời gian
    ctx.fillStyle = C.bg; ctx.fillRect(GUTTER, 0, w - GUTTER, RULER);
    const step = TICKS.find((k) => k * T.pps >= 70) || 600;
    const first = Math.floor(x2t(GUTTER) / step) * step;
    ctx.fillStyle = C.label; ctx.font = '10.5px "JetBrains Mono",monospace'; ctx.textBaseline = 'middle';
    for (let t = Math.max(0, first); t <= dur() + 1e-6; t += step) {
      const x = t2x(t);
      ctx.fillStyle = C.tick; ctx.fillRect(x, RULER - 7, 1, 7);
      ctx.fillStyle = C.line; ctx.fillRect(x, RULER, 1, h - RULER - OVERVIEW);
      ctx.fillStyle = C.label; ctx.fillText(fmtTime(t, step < 1 ? 1 : 0), x + 4, 10);
      for (let k = 1; k < 5; k++) { ctx.fillStyle = C.line; ctx.fillRect(t2x(t + (step * k) / 5), RULER - 3, 1, 3); }
    }
    ctx.restore();

    // tên track
    ctx.fillStyle = C.bg; ctx.fillRect(0, 0, GUTTER, h);
    ctx.font = '600 11px "Be Vietnam Pro",sans-serif'; ctx.textBaseline = 'middle';
    [['Tiếng gốc', tr.zh, C.zh], ['Giọng lồng', tr.dub, C.dub], ['Phụ đề', tr.sub, C.blockText], ...(tr.ov ? [['Lớp phủ', tr.ov, C.ovOn]] : [])].forEach(([n, b, c]) => {
      ctx.fillStyle = c; ctx.fillRect(10, b[0] + b[1] / 2 - 5, 3, 10);
      ctx.fillStyle = C.label; ctx.fillText(n.split(' ')[0], 18, b[0] + b[1] / 2 - (n.includes(' ') ? 6 : 0));
      if (n.includes(' ')) ctx.fillText(n.split(' ')[1], 18, b[0] + b[1] / 2 + 7);
    });
    ctx.fillStyle = C.line;
    ctx.fillRect(GUTTER - 1, 0, 1, h - OVERVIEW);
    for (const b of [tr.zh, tr.dub, tr.sub, tr.ov].filter(Boolean)) ctx.fillRect(0, b[0], w, 1);

    // dải tổng quan + khung nhìn
    const oy = h - OVERVIEW;
    ctx.fillStyle = C.trackAlt; ctx.fillRect(0, oy, w, OVERVIEW);
    const ow = w - GUTTER - 8;
    segs.forEach((s) => { ctx.fillStyle = C.blockEdge; ctx.fillRect(GUTTER + (s.start / dur()) * ow, oy + 4, Math.max(1, ((s.end - s.start) / dur()) * ow), 4); });
    for (const [ca, cb] of getCuts ? getCuts() : []) { ctx.fillStyle = C.bad; ctx.fillRect(GUTTER + (ca / dur()) * ow, oy + 2, Math.max(1, ((cb - ca) / dur()) * ow), 2); }
    const vx = GUTTER + (T.sx / (dur() * T.pps)) * ow, vw = Math.min(ow, (ow / (dur() * T.pps)) * ow);
    ctx.fillStyle = C.view; ctx.fillRect(vx, oy + 1, Math.max(8, vw), OVERVIEW - 2);

    // kim phát
    const t = getTime();
    const x = t2x(t);
    if (x >= GUTTER - 1 && x <= w) {
      ctx.fillStyle = C.head;
      ctx.fillRect(x - 0.75, 0, 1.5, h - OVERVIEW);
      ctx.beginPath(); ctx.moveTo(x - 5, 0); ctx.lineTo(x + 5, 0); ctx.lineTo(x + 5, 7); ctx.lineTo(x, 13); ctx.lineTo(x - 5, 7); ctx.closePath(); ctx.fill();
    }
    ctx.fillStyle = C.head; ctx.fillRect(GUTTER + (clamp(t, 0, dur()) / dur()) * ow - 0.5, oy, 1, OVERVIEW);
  }

  // ---- tìm khối dưới con trỏ
  function hit(x, y) {
    const tr = tracks();
    if (y < tr.sub[0] || y > tr.sub[0] + tr.sub[1] || x < GUTTER) return null;
    const segs = getSegs();
    for (let i = 0; i < segs.length; i++) {
      const a = t2x(segs[i].start), b = t2x(segs[i].end);
      if (x >= a - 3 && x <= b + 3) {
        const edge = b - a > 18 ? (x - a < EDGE ? 'start' : b - x < EDGE ? 'end' : '') : '';
        return { i, edge };
      }
    }
    return null;
  }
  const pos = (e) => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  /** hít vào điểm chuyển cảnh và ranh giới câu khi kéo chọn đoạn */
  function snap(t, e) {
    if (e.altKey) return t;
    let best = t, gap = 7 / T.pps;
    const near = (c) => { const d = Math.abs(c - t); if (d < gap) { gap = d; best = c; } };
    for (const c of getScenes ? getScenes() : []) near(c);
    for (const s of getSegs()) { near(s.start); near(s.end); }
    return best;
  }
  function hitOverlay(x, y) {
    const tr = tracks();
    if (!tr.ov || y < tr.ov[0] || y > tr.ov[0] + tr.ov[1] || x < GUTTER) return null;
    const list = getOverlays() || [];
    for (let i = list.length - 1; i >= 0; i--) {
      const a = t2x(list[i].start), b = t2x(list[i].end);
      if (x >= a - 2 && x <= b + 2) return { i, edge: b - a > 18 ? (x - a < EDGE ? 'start' : b - x < EDGE ? 'end' : '') : '' };
    }
    return null;
  }
  const inWaves = (y) => { const tr = tracks(); return y >= tr.zh[0] && y < tr.sub[0]; };
  function cutAtX(x) {
    const t = x2t(x);
    const list = getCuts ? getCuts() : [];
    for (let i = 0; i < list.length; i++) if (t >= list[i][0] && t <= list[i][1]) return i;
    return -1;
  }

  canvas.addEventListener('pointermove', (e) => {
    const [x, y] = pos(e);
    const d = T.drag;
    if (!d) {
      const h = hit(x, y);
      const hi = h ? h.i : -1;
      if (hi !== T.hover) { T.hover = hi; requestDraw(); }
      const ho = hitOverlay(x, y);
      canvas.style.cursor = ho ? (ho.edge ? 'ew-resize' : 'grab') : h ? (h.edge ? 'ew-resize' : 'grab') : y < RULER ? 'col-resize' : y > T.h - OVERVIEW ? 'pointer' : inWaves(y) ? 'text' : 'default';
      canvas.title = x >= GUTTER && y >= RULER && y < T.h - OVERVIEW && cutAtX(x) >= 0 ? 'Đoạn đã cắt. Bấm đúp để khôi phục' : '';
      return;
    }
    if (d.type === 'seek') { onSeek(clamp(x2t(Math.max(x, GUTTER)), 0, dur())); return; }
    if (d.type === 'overview') { scrollOverview(x); return; }
    if (d.type === 'range') {
      if (Math.abs(x - d.x0) > 3 && !d.moved) { d.moved = true; d.t0 = snap(d.t0, e); }
      if (d.moved) setSel(clamp(d.t0, 0, dur()), clamp(snap(x2t(Math.max(x, GUTTER)), e), 0, dur()));
      return;
    }
    if (d.type === 'ov') {
      const o = (getOverlays() || [])[d.i];
      if (!o) return;
      const dt = (x - d.x0) / T.pps;
      if (d.edge === 'start') o.start = +clamp(d.start + dt, 0, o.end - MIN_DUR).toFixed(2);
      else if (d.edge === 'end') o.end = +clamp(d.end + dt, o.start + MIN_DUR, dur()).toFixed(2);
      else {
        const len = d.end - d.start;
        o.start = +clamp(d.start + dt, 0, dur() - len).toFixed(2);
        o.end = +(o.start + len).toFixed(2);
      }
      d.moved = true;
      if (onOverlayDrag) onOverlayDrag(d.i);
      requestDraw();
      return;
    }
    const segs = getSegs(), s = segs[d.i];
    const dt = (x - d.x0) / T.pps;
    const lo = d.i > 0 ? segs[d.i - 1].end : 0;
    const hi = d.i + 1 < segs.length ? segs[d.i + 1].start : dur();
    if (d.edge === 'start') s.start = +clamp(d.start + dt, lo, s.end - MIN_DUR).toFixed(3);
    else if (d.edge === 'end') s.end = +clamp(d.end + dt, s.start + MIN_DUR, hi).toFixed(3);
    else {
      const len = d.end - d.start;
      s.start = +clamp(d.start + dt, lo, hi - len).toFixed(3);
      s.end = +(s.start + len).toFixed(3);
    }
    d.moved = true;
    onDrag(d.i);
    requestDraw();
  });
  function scrollOverview(x) {
    const ow = T.w - GUTTER - 8;
    T.sx = ((x - GUTTER) / ow) * dur() * T.pps - (T.w - GUTTER) / 2;
    clampScroll(); requestDraw();
  }
  canvas.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    canvas.setPointerCapture(e.pointerId);
    const [x, y] = pos(e);
    if (y > T.h - OVERVIEW) { T.drag = { type: 'overview' }; scrollOverview(x); return; }
    const ho = hitOverlay(x, y);
    if (ho) {
      const o = getOverlays()[ho.i];
      T.drag = { type: 'ov', i: ho.i, edge: ho.edge, x0: x, start: o.start, end: o.end, moved: false };
      if (onOverlayPick) onOverlayPick(ho.i);
      requestDraw();
      return;
    }
    if (x >= GUTTER && inWaves(y)) {
      T.drag = { type: 'range', x0: x, t0: x2t(x), moved: false };
      return;
    }
    const h = hit(x, y);
    if (h) {
      const s = getSegs()[h.i];
      T.drag = { type: 'block', i: h.i, edge: h.edge, x0: x, start: s.start, end: s.end, moved: false };
      canvas.style.cursor = h.edge ? 'ew-resize' : 'grabbing';
      onSelect(h.i);
      return;
    }
    T.drag = { type: 'seek' };
    onSeek(clamp(x2t(Math.max(x, GUTTER)), 0, dur()));
  });
  const endDrag = () => {
    const d = T.drag;
    T.drag = null;
    if (d && d.type === 'block' && d.moved) onCommit(d.i);
    if (d && d.type === 'ov' && d.moved && onOverlayCommit) onOverlayCommit(d.i);
    if (d && d.type === 'range' && !d.moved) { clearSel(); onSeek(clamp(d.t0, 0, dur())); }
    canvas.style.cursor = 'default';
    requestDraw();
  };
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);
  canvas.addEventListener('pointerleave', () => { if (!T.drag && T.hover !== -1) { T.hover = -1; requestDraw(); } });
  canvas.addEventListener('dblclick', (e) => {
    const [x, y] = pos(e);
    const c = x >= GUTTER && y >= RULER && y < T.h - OVERVIEW ? cutAtX(x) : -1;
    if (c >= 0 && onCutRestore) { onCutRestore(c); return; }
    const h = hit(x, y);
    if (h) onOpen(h.i);
  });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) { const [x] = pos(e); zoom(e.deltaY < 0 ? 1.25 : 0.8, Math.max(x, GUTTER)); return; }
    T.sx += (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY) * 1.2;
    clampScroll(); requestDraw();
  }, { passive: false });

  const ro = new ResizeObserver(() => {
    const r = canvas.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const was = T.pps && Math.abs(T.pps - minPps()) < 1e-6;
    T.dpr = window.devicePixelRatio || 1;
    T.w = r.width; T.h = r.height;
    canvas.width = Math.round(r.width * T.dpr);
    canvas.height = Math.round(r.height * T.dpr);
    if (!T.pps || was || T.pps < minPps()) T.pps = minPps();
    clampScroll(); paintZoom(); draw();
  });
  ro.observe(canvas);
  function destroy() { ro.disconnect(); if (T.raf) cancelAnimationFrame(T.raf); }
  return T;
}
