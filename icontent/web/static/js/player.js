/* Trình phát trong Studio. 3 chế độ:
 *   preview: video gốc + dải đã xóa sub + phụ đề vẽ trực tiếp + giọng lồng: thấy ngay kết quả, không cần dựng lại.
 *   final:   video đã dựng.
 *   compare: kéo thanh để so sánh trước/sau.
 */
import { assToHex, clamp, el, enc, fmtTime, getPath, icon } from './core.js';

// ---- nhịp chữ, giống hệt models.py để phần xem trước khớp với video dựng ra
function weights(ws) {
  return ws.map((w) => {
    const n = [...w].filter((ch) => /[\p{L}\p{N}]/u.test(ch)).length;
    const last = w.slice(-1);
    const tail = ',;:'.includes(last) ? 2.5 : '.!?…'.includes(last) ? 3.5 : 0;
    return Math.max(1, n * 0.6 + 1.5) + tail;
  });
}
function chunks(ws, size, maxChars) {
  const total = ws.reduce((n, w) => n + w.length + 1, 0);
  if (size <= 0 || (ws.length <= size && (!maxChars || total <= maxChars))) return [ws.map((_, i) => i)];
  const out = [];
  let cur = [], chars = 0;
  ws.forEach((w, i) => {
    if (cur.length && maxChars && chars + w.length > maxChars) { out.push(cur); cur = []; chars = 0; }
    cur.push(i);
    chars += w.length + 1;
    const rest = ws.length - i - 1;
    if (cur.length >= size || (cur.length >= size * 0.5 && ',.;:!?…'.includes(w.slice(-1)) && rest >= 2)) { out.push(cur); cur = []; chars = 0; }
  });
  if (cur.length) {
    const fits = out.length ? (!maxChars || [...out[out.length - 1], ...cur].reduce((n, i) => n + ws[i].length + 1, 0) - 1 <= maxChars) : false;
    if (cur.length <= 2 && out.length && fits) out[out.length - 1].push(...cur); else out.push(cur);
  }
  return out;
}

const LOOK_CSS = {
  warm: 'sepia(.14) saturate(1.1)', cool: 'hue-rotate(-10deg) saturate(1.02)', vivid: 'contrast(1.08) saturate(1.3)',
  film: 'contrast(1.1) saturate(.82) sepia(.06)', bw: 'grayscale(1) contrast(1.1)', vintage: 'sepia(.32) saturate(.9) contrast(.95)',
  teal: 'contrast(1.06) saturate(1.08) hue-rotate(-6deg)', moody: 'contrast(1.14) brightness(.95) saturate(.78)', golden: 'sepia(.2) saturate(1.2) contrast(1.05)', bright: 'brightness(1.07) saturate(1.1)',
};
const TARGET = { '9:16': [1080, 1920], '16:9': [1920, 1080], '1:1': [1080, 1080] };

export function Player({ id, getMeta, getEff, getSegs, getBox, hasFile, onTime, onSubY, onModeChange, getRendered, getOverlaySel, onOverlayPick, onOverlayMove, onPin }) {
  const url = (name, bust) => `/api/jobs/${enc(id)}/media/${name}${bust ? '?t=' + bust : ''}`;
  const base = el('video', { class: 'pl-video', preload: 'auto', playsinline: true });
  const band = el('video', { class: 'pl-band', preload: 'auto', playsinline: true, muted: true, hidden: true });
  const after = el('video', { class: 'pl-video pl-after', preload: 'auto', playsinline: true, muted: true, hidden: true });
  const dub = new Audio();
  dub.preload = 'auto';

  const subLine = el('div', { class: 'sub-line' });
  const sub = el('div', { class: 'sub-overlay', title: 'Kéo lên xuống để đổi vị trí phụ đề · Bấm đúp để đặt lại tự động' }, subLine);
  const guide = el('div', { class: 'sub-guide', hidden: true });
  const handle = el('div', { class: 'cmp-handle', hidden: true }, el('span', { class: 'cmp-knob' }, icon('compare')));
  const labelL = el('span', { class: 'cmp-label left', hidden: true, text: 'Trước' });
  const labelR = el('span', { class: 'cmp-label right', hidden: true, text: 'Sau' });
  const ovLayer = el('div', { class: 'ov-layer' });
  const cutBadge = el('div', { class: 'pl-cut-badge', hidden: true }, icon('scissors'), 'Đoạn này đã cắt, sẽ không có trong video');
  const rfTag = el('span', { class: 'rf-tag', text: 'Phần giữ lại' });
  const rfWin = el('div', { class: 'rf-window', hidden: true }, rfTag);
  const safeEl = el('div', { class: 'safe-zone', hidden: true },
    ['top', 'bottom', 'left', 'right'].map((k) => el('i', { class: 'sz-' + k })), el('span', { class: 'sz-note', text: 'Vùng dễ bị nút che (ước lượng)' }));
  const frame = el('div', { class: 'pl-frame' }, base, band, after, rfWin, safeEl, guide, sub, ovLayer, cutBadge, handle, labelL, labelR);
  const stage = el('div', { class: 'pl-stage' }, frame);

  const playBtn = el('button', { class: 'pl-play', title: 'Phát / dừng (Space)', 'aria-label': 'Phát hoặc dừng', onclick: () => toggle() }, icon('play'));
  const timeEl = el('span', { class: 'pl-time mono' });
  const scrub = el('input', { type: 'range', class: 'range pl-scrub', min: 0, max: 1, step: 0.001, value: 0, 'aria-label': 'Thời gian' });
  const volBtn = el('button', { class: 'btn btn-icon btn-ghost', title: 'Tắt / bật tiếng', 'aria-label': 'Tắt hoặc bật tiếng', onclick: () => { P.muted = !P.muted; applyVolume(); } }, icon('volume'));
  const seg = el('div', { class: 'seg seg-inline pl-modes', role: 'radiogroup', 'aria-label': 'Chế độ xem' });
  const modes = {
    preview: el('button', { type: 'button', class: 'seg-btn', role: 'radio', title: 'Thấy ngay phụ đề và giọng lồng, không cần dựng lại', onclick: () => setMode('preview') }, 'Xem trước'),
    final: el('button', { type: 'button', class: 'seg-btn', role: 'radio', title: 'Video đã dựng', onclick: () => setMode('final') }, 'Thành phẩm'),
    compare: el('button', { type: 'button', class: 'seg-btn', role: 'radio', title: 'So sánh trước và sau', onclick: () => setMode('compare') }, 'So sánh'),
  };
  Object.values(modes).forEach((b) => seg.append(b));
  const safeBtn = el('button', { class: 'btn btn-icon btn-ghost', hidden: true, title: 'Hiện vùng thường bị nút và chữ của ứng dụng che (ước lượng, nên xem lại trong ứng dụng trước khi đăng)', 'aria-label': 'Vùng an toàn', onclick: () => { P.safeOn = !P.safeOn; paintSafe(); } }, icon('safe'));
  const fullBtn = el('button', { class: 'btn btn-icon btn-ghost', title: 'Toàn màn hình', 'aria-label': 'Toàn màn hình', onclick: () => { if (document.fullscreenElement) document.exitFullscreen(); else stage.requestFullscreen().catch(() => {}); } }, icon('full'));
  const root = el('div', { class: 'pl' }, stage,
    el('div', { class: 'pl-controls' }, playBtn, timeEl, scrub, volBtn, seg, safeBtn, fullBtn));

  const P = {
    root, mode: 'preview', bust: Date.now(), muted: false, stopAt: null, cmp: 0.5, setMode, seek, play, pause, toggle, refreshSub, layout,
    time, destroy, setBust(v) { P.bust = v; }, reloadSources, playRange, isPlaying: () => !base.paused, setPlan, seekFinal, setSafeZone, safeOn: false, step,
    get plan() { return plan; },
  };
  let plan = null;
  const speed = () => parseFloat(getPath(getEff(), 'edit.speed')) || 1;
  const cutsNow = () => getPath(getEff(), 'edit.cuts') || [];
  const rendered = () => (getRendered && getRendered()) || {};
  /** thời gian video gốc -> thời gian trên bản đã dựng (đã cắt, đổi tốc độ, thêm mở đầu) */
  function toFinal(t) {
    const r = rendered();
    let s = t, removed = 0;
    for (const [a, b] of r.cuts || []) {
      if (t >= b) removed += b - a;
      else if (t > a) { s = a; break; }
      else break;
    }
    return (s - removed) / (r.speed || speed()) + (r.intro || 0);
  }
  /** ngược lại */
  function fromFinal(ft) {
    const r = rendered();
    let s = Math.max(0, ft - (r.intro || 0)) * (r.speed || speed());
    for (const [a, b] of r.cuts || []) { if (s >= a) s += b - a; else break; }
    return s;
  }
  const cutAt = (t) => cutsNow().find(([a, b]) => t >= a - 0.001 && t < b - 0.01);
  /** thời gian theo video gốc */
  function time() { return P.mode === 'final' ? fromFinal(base.currentTime) : base.currentTime; }
  function seek(t) {
    const target = P.mode === 'final' ? toFinal(t) : t;
    try { base.currentTime = clamp(target, 0, base.duration || target); } catch (_) { /* chưa nạp xong */ }
    syncFollowers(true);
    paintTime();
    refreshSub();
    onTime(time());
  }
  /** tới một giây trên bản đã dựng (mốc từ kiểm định thành phẩm) */
  function seekFinal(ft) {
    pause();
    const go = () => {
      try { base.currentTime = clamp(ft, 0, base.duration || ft); } catch (_) { /* chưa nạp xong */ }
      paintTime();
      onTime(time());
    };
    if (P.mode === 'final') { go(); return; }
    // đi thẳng theo thời gian bản dựng: quy đổi qua thời gian gốc sẽ lạc nếu mốc nằm trong đoạn mở đầu
    setMode('final', false, fromFinal(ft));
    if (base.readyState >= 1) go(); else base.addEventListener('loadedmetadata', go, { once: true });
  }
  /** tua tương đối. Trên bản đã dựng phải tua theo thời gian của bản dựng, nếu không sẽ kẹt ở mép đoạn đã cắt */
  function step(dt) {
    if (P.mode !== 'final') { seek(Math.max(0, time() + dt)); return; }
    try { base.currentTime = clamp(base.currentTime + dt, 0, base.duration || 0); } catch (_) { /* chưa nạp xong */ }
    paintTime();
    refreshSub();
    onTime(time());
  }
  function play() { base.play().catch(() => {}); }
  function pause() { base.pause(); }
  function toggle() { if (base.paused) play(); else pause(); }
  function playRange(a, b) { P.stopAt = b; P.stopFrom = a; seek(a); play(); }

  function applyVolume() {
    const showDub = P.mode === 'preview' && hasFile('dub');
    // xem trước: tiếng gốc nhỏ lại như bản dựng (khi đã có giọng lồng)
    const ov = parseFloat(getPath(getEff(), 'audio.original_volume'));
    base.muted = P.muted;
    base.volume = showDub ? clamp(isNaN(ov) ? 0.15 : ov, 0, 1) : 1;
    dub.muted = P.muted;
    volBtn.replaceChildren(icon(P.muted ? 'mute' : 'volume'));
  }
  function reloadSources() {
    const prev = P.mode;
    const t = time();
    P.mode = '';
    setMode(prev, true, t);
  }
  function setMode(m, forceReload, keepTime) {
    const hasFinal = hasFile('final');
    if ((m === 'final' || m === 'compare') && !hasFinal) m = 'preview';
    if (m === 'compare' && (getPath(getEff(), 'edit.aspect') || 'keep') !== 'keep') m = 'final';
    const t = keepTime != null ? keepTime : P.mode ? time() : 0;
    const wasPlaying = !base.paused;
    P.mode = m;
    Object.entries(modes).forEach(([k, b]) => { const on = k === m; b.classList.toggle('active', on); b.setAttribute('aria-checked', on ? 'true' : 'false'); });
    modes.final.disabled = modes.compare.disabled = !hasFinal;
    const src = m === 'final' ? url('final.mp4', P.bust) : url('source.mp4');
    const srcChanged = base.getAttribute('src') !== src;
    if (srcChanged || forceReload) {
      base.src = src;
      base.addEventListener('loadedmetadata', () => {
        layout();
        seek(t);
        if (wasPlaying) play();
      }, { once: true });
    }
    // dải đã xóa sub (chỉ ở chế độ xem trước)
    const hsMode = getPath(getEff(), 'edit.hardsub_mode');
    const box = getBox();
    const useBand = m === 'preview' && hasFile('clean') && box && hsMode === 'inpaint';
    band.hidden = !useBand;
    if (useBand) { band.src = url('clean_band.mp4', P.bust); P.bandBox = box; } else { band.removeAttribute('src'); P.bandBox = null; }
    // giọng lồng
    if (m === 'preview' && hasFile('dub')) { if (dub.getAttribute('src') !== url('dub.wav', P.bust)) dub.src = url('dub.wav', P.bust); } else { dub.pause(); dub.removeAttribute('src'); }
    // so sánh
    const cmp = m === 'compare';
    after.hidden = handle.hidden = labelL.hidden = labelR.hidden = !cmp;
    if (cmp) { after.src = url('final.mp4', P.bust); paintCompare(); } else if (after.getAttribute('src')) { after.pause(); after.removeAttribute('src'); }
    sub.hidden = m !== 'preview';
    ovLayer.hidden = m !== 'preview';
    paintCrop();
    paintSafe();
    applyLook();
    applyVolume();
    layout();
    refreshSub();
    onModeChange(m);
  }
  /** hình nằm ở đâu trong khung: khung mới có nền mờ hoặc viền đen thì hình nằm giữa, không đầy khung */
  function videoRect() {
    if (!letterbox()) return { x: 0, y: 0, w: 1, h: 1 };
    const m = getMeta();
    const t = TARGET[getPath(getEff(), 'edit.aspect')];
    const src = (m.width || 16) / (m.height || 9), out = t[0] / t[1];
    return src > out ? { x: 0, y: (1 - out / src) / 2, w: 1, h: out / src } : { x: (1 - src / out) / 2, y: 0, w: src / out, h: 1 };
  }
  function placeBand(box) {
    const m = getMeta();
    const W = m.width || 1, H = m.height || 1;
    const v = videoRect();
    // đúng toạ độ làm tròn chẵn như clean.band_rect
    const cx = Math.floor((W * box[0]) / 2) * 2, cy = Math.floor((H * box[1]) / 2) * 2;
    const cw = Math.min(Math.max(16, Math.floor((W * box[2]) / 2) * 2), Math.floor((W - cx) / 2) * 2);
    const ch = Math.min(Math.max(8, Math.floor((H * box[3]) / 2) * 2), Math.floor((H - cy) / 2) * 2);
    const l = v.x + (cx / W) * v.w, t = v.y + (cy / H) * v.h, bw = (cw / W) * v.w, bh = (ch / H) * v.h;
    Object.assign(band.style, { left: l * 100 + '%', top: t * 100 + '%', width: bw * 100 + '%', height: bh * 100 + '%' });
    band.style.transformOrigin = `${((0.5 - l) / bw) * 100}% ${((0.5 - t) / bh) * 100}%`;      // lật và phóng quanh tâm khung, giống hình chính
  }
  function followers() { return [band.hidden ? null : band, after.hidden ? null : after].filter((v) => v && v.getAttribute('src')); }
  function syncFollowers(force) {
    const t = base.currentTime;
    for (const v of followers()) {
      const want = v === after ? toFinal(t) : t;     // bản đã dựng có thể đã cắt, thời gian khác video gốc
      if (v === after) v.playbackRate = 1 / (rendered().speed || speed() || 1);      // bản dựng đã đổi tốc độ: chạy cho khớp bản gốc
      if (force || Math.abs(v.currentTime - want) > 0.12) { try { v.currentTime = want; } catch (_) { /* chưa nạp */ } }
      if (base.paused !== v.paused) { if (base.paused) v.pause(); else v.play().catch(() => {}); }
    }
    if (P.mode === 'preview' && dub.getAttribute('src')) {
      if (force || Math.abs(dub.currentTime - t) > 0.18) { try { dub.currentTime = t; } catch (_) { /* chưa nạp */ } }
      if (base.paused !== dub.paused) { if (base.paused) dub.pause(); else dub.play().catch(() => {}); }
    }
  }

  // ---- bố cục: khung hình vừa khít vùng chứa, giữ đúng tỉ lệ
  function layout() {
    const r = stage.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const m = getMeta();
    let ar = (m.width || 16) / (m.height || 9);
    if (P.mode === 'final' && base.videoWidth) ar = base.videoWidth / base.videoHeight;
    else if (letterbox()) { const t = TARGET[getPath(getEff(), 'edit.aspect')]; ar = t[0] / t[1]; }
    let w = r.width, h = w / ar;
    if (h > r.height) { h = r.height; w = h * ar; }
    frame.style.width = Math.floor(w) + 'px';
    frame.style.height = Math.floor(h) + 'px';
    P.scale = h / (m.height || 1080);
    if (P.bandBox) placeBand(P.bandBox);
    refreshSub();
  }

  // ---- khung cắt: thấy ngay phần hình sẽ được giữ lại khi đổi tỉ lệ khung hình. Tính giống vision.pos_at
  function setPlan(p) {
    rfDrag = null;
    plan = p;
    rfWin.title = p && p.isStatic ? 'Kéo để chọn phần hình được giữ lại' : 'Kéo để đổi vị trí khung cho cảnh này · Bấm đúp để máy tự chọn lại';
    paintCrop();
    paintSafe();
    layout();
  }
  /** đổi khung với nền mờ hoặc viền đen: xem trước trong đúng khung mới, chữ và ảnh mới nằm đúng chỗ như bản dựng */
  const letterbox = () => P.mode === 'preview' && !plan && !!TARGET[getPath(getEff(), 'edit.aspect')];
  function cropAt(t) {
    for (const s of plan.segs) {
      if (t < s[1]) {
        if (s[2] === s[3] || t <= s[0]) return s[2];
        const u = Math.min(1, (t - s[0]) / Math.max(1e-6, s[1] - s[0]));
        return s[2] + (s[3] - s[2]) * u * u * (3 - 2 * u);
      }
    }
    return plan.segs.length ? plan.segs[plan.segs.length - 1][3] : 0.5;
  }
  const cropOn = () => !!plan && P.mode === 'preview';
  /** cỡ khung hình đang xem trước: khung mới nếu có khung cắt, không thì video gốc */
  function viewSize() {
    const m = getMeta();
    const W = m.width || 1080, H = m.height || 1920;
    const t = cropOn() || letterbox() ? TARGET[getPath(getEff(), 'edit.aspect')] : null;
    if (!t) return { W, H, k: P.scale || 0.3 };
    const s = Math.min(1, Math.max(720, Math.min(W, H)) / Math.min(t[0], t[1]));   // giống render.out_size
    const tw = Math.round((t[0] * s) / 2) * 2, th = Math.round((t[1] * s) / 2) * 2;
    const fh = frame.clientHeight || 1;
    return { W: tw, H: th, k: (cropOn() && plan.axis === 'y' ? fh * plan.span : fh) / th };
  }
  function placeCrop(c) {
    const sp = plan.span;
    const a = (c - sp / 2) * 100, w = sp * 100;
    const rect = plan.axis === 'x' ? { left: a + '%', top: '0', width: w + '%', height: '100%' } : { left: '0', top: a + '%', width: '100%', height: w + '%' };
    Object.assign(rfWin.style, rect);
    Object.assign(ovLayer.style, { inset: 'auto', ...rect });
    if (plan.axis === 'x') { sub.style.left = (c - sp / 2 + sp * 0.06) * 100 + '%'; sub.style.right = (1 - c - sp / 2 + sp * 0.06) * 100 + '%'; } else { sub.style.left = ''; sub.style.right = ''; }
  }
  let rfDrag = null;
  function paintCrop() {
    const on = cropOn();
    rfWin.hidden = !on;
    if (!on) {
      for (const k of ['left', 'top', 'width', 'height', 'inset']) ovLayer.style[k] = '';
      sub.style.left = sub.style.right = '';
      return;
    }
    if (!rfDrag) placeCrop(cropAt(base.currentTime));
  }
  rfWin.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || !plan) return;
    e.preventDefault();
    e.stopPropagation();
    rfWin.setPointerCapture(e.pointerId);
    rfDrag = { x0: e.clientX, y0: e.clientY, c: null, t: time(), wasPlaying: !base.paused };     // nhớ cảnh lúc bắt đầu kéo: video đang chạy có thể đã sang cảnh khác
    pause();
  });
  rfWin.addEventListener('pointermove', (e) => {
    if (!rfDrag || !plan) return;
    if (rfDrag.c == null && Math.hypot(e.clientX - rfDrag.x0, e.clientY - rfDrag.y0) < 4) return;
    const r = frame.getBoundingClientRect();
    const p = plan.axis === 'x' ? (e.clientX - r.left) / r.width : (e.clientY - r.top) / r.height;
    rfDrag.c = clamp(p, plan.span / 2, 1 - plan.span / 2);
    placeCrop(rfDrag.c);
  });
  const endRf = () => {
    if (!rfDrag) return;
    const d = rfDrag;
    rfDrag = null;
    if (d.c != null) { if (onPin) onPin(d.t, +d.c.toFixed(4)); } else if (!d.wasPlaying) play();
  };
  rfWin.addEventListener('pointerup', endRf);
  rfWin.addEventListener('pointercancel', () => { rfDrag = null; paintCrop(); });
  rfWin.addEventListener('dblclick', () => { if (onPin) onPin(time(), null); });

  // ---- vùng dễ bị nút của ứng dụng che (khung dọc)
  function setSafeZone(z) {
    if (!z) return;
    for (const k of ['top', 'bottom', 'left', 'right']) safeEl.style.setProperty('--sz-' + k, z[k] * 100 + '%');
    P.hasSafe = true;
    paintSafe();
  }
  function paintSafe() {
    const m = getMeta();
    const a = getPath(getEff(), 'edit.aspect') || 'keep';
    const can = !!P.hasSafe && (P.mode === 'final' ? base.videoHeight > base.videoWidth * 1.5
      : P.mode === 'preview' && (a === '9:16' ? !!plan || (m.height > m.width * 1.5) : a === 'keep' && m.height > m.width * 1.5));
    safeBtn.hidden = !can;
    safeBtn.classList.toggle('playing', can && P.safeOn);
    safeEl.hidden = !(can && P.safeOn);
    const host = cropOn() ? rfWin : frame;
    if (safeEl.parentNode !== host) host.append(safeEl);
  }

  // ---- màu xem trước (gần đúng, video dựng ra dùng bộ lọc ffmpeg)
  function applyLook() {
    const e = (getEff() && getEff().edit) || {};
    const parts = [];
    if (P.mode === 'preview') {
      const br = parseFloat(e.brightness) || 0, ct = parseFloat(e.contrast) || 1, sat = parseFloat(e.saturation) || 1;
      if (Math.abs(br) > 1e-3) parts.push(`brightness(${1 + br})`);
      if (Math.abs(ct - 1) > 1e-3) parts.push(`contrast(${ct})`);
      if (Math.abs(sat - 1) > 1e-3) parts.push(`saturate(${sat})`);
      if (LOOK_CSS[e.look]) parts.push(LOOK_CSS[e.look]);
    }
    const f = parts.join(' ');
    base.style.filter = f;
    band.style.filter = f;
    // lật và phóng đi trước khung cắt trong bộ lọc: xem trước phải giống vậy thì vị trí khung, chữ, ảnh mới đúng như bản dựng
    const z = P.mode === 'preview' ? Math.max(1, parseFloat(e.zoom) || 1) : 1;
    const flip = P.mode === 'preview' && !!e.flip;
    const tf = z > 1.001 || flip ? `scale(${flip ? -z : z}, ${z})` : '';
    base.style.transform = tf;
    band.style.transform = tf;
    // nền mờ hoặc viền đen: bản dựng cắt hình về đúng cỡ gốc rồi mới đặt vào khung, nên hình phóng to không được tràn ra ngoài phần của nó.
    // clip-path áp trước transform nên phải chia cho z
    const v = z > 1.001 ? videoRect() : null;
    base.style.clipPath = v && letterbox() ? `inset(${((1 - v.h / z) / 2) * 100}% ${((1 - v.w / z) / 2) * 100}%)` : '';
  }

  // ---- lớp chữ, ảnh trên video (chỉ ở chế độ xem trước)
  let ovKey = '';
  let ovDrag = null;
  function refreshOverlays() {
    if (P.mode !== 'preview') { if (ovKey) { ovLayer.replaceChildren(); ovKey = ''; } return; }
    const list = getPath(getEff(), 'edit.overlays') || [];
    const t = base.currentTime;
    const sel = getOverlaySel ? getOverlaySel() : -1;
    const { W, H, k } = viewSize();
    const vis = list.map((o, i) => [o, i]).filter(([o]) => t >= o.start && t < o.end);
    const key = JSON.stringify([vis.map(([o, i]) => [i, o]), sel, k]);
    if (key === ovKey || ovDrag) return;
    ovKey = key;
    ovLayer.replaceChildren(...vis.map(([o, i]) => {
      const base_ = { left: o.x * 100 + '%', top: o.y * 100 + '%' };
      let node;
      if (o.type === 'image') {
        node = el('img', { class: 'ov-item', draggable: 'false', alt: '', src: o.url || '', style: Object.assign(base_, { width: (o.size || 0.3) * W * k + 'px', opacity: o.opacity == null ? 1 : o.opacity }) });
      } else {
        const fs = (o.size || 0.08) * H * k;
        const box = o.style === 'box';
        node = el('div', {
          class: 'ov-item ov-text', text: o.text || '', style: Object.assign(base_, {
            fontSize: fs + 'px', fontFamily: `"${o.font || (getEff().edit || {}).font || 'Arial'}", Arial, sans-serif`, fontWeight: o.bold === false ? '400' : '700', color: o.color || '#ffffff',
            background: box ? (o.bg || '#000000') : 'transparent', padding: box ? `${fs * 0.1}px ${fs * 0.25}px` : '0',
            WebkitTextStroke: box ? '0' : `${Math.max(1, fs / 12)}px ${o.outline || '#000000'}`, paintOrder: 'stroke fill',
          }),
        });
      }
      if (i === sel) node.classList.add('selected');
      node.dataset.i = String(i);
      return node;
    }));
  }
  ovLayer.addEventListener('pointerdown', (e) => {
    const n = e.target.closest ? e.target.closest('.ov-item') : null;
    if (!n || e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const i = Number(n.dataset.i);
    if (onOverlayPick) onOverlayPick(i);
    ovDrag = { i, n, moved: false };
    ovLayer.setPointerCapture(e.pointerId);
  });
  ovLayer.addEventListener('pointermove', (e) => {
    if (!ovDrag) return;
    const r = ovLayer.getBoundingClientRect();
    const x = clamp((e.clientX - r.left) / r.width, 0, 1), y = clamp((e.clientY - r.top) / r.height, 0, 1);
    ovDrag.n.style.left = x * 100 + '%';
    ovDrag.n.style.top = y * 100 + '%';
    ovDrag.x = x; ovDrag.y = y; ovDrag.moved = true;
  });
  const endOv = () => {
    if (!ovDrag) return;
    const d = ovDrag;
    ovDrag = null;
    if (d.moved && onOverlayMove) onOverlayMove(d.i, +d.x.toFixed(3), +d.y.toFixed(3));
    ovKey = '';
    refreshOverlays();
  };
  ovLayer.addEventListener('pointerup', endOv);
  ovLayer.addEventListener('pointercancel', endOv);

  // ---- phụ đề xem trước
  function fontPx(e, W, H) {
    const ratio = parseFloat(e.font_size_ratio) || 0.05;
    const size = Math.max(16, Math.round(Math.min(W, H) * ratio * (W >= H ? 1 : 1.25)));
    return size * ({ tiktok: 1.2, pop: 1.3 }[e.sub_style] || 1);
  }
  function subCenterY(e, W, H, fs) {
    if (e.sub_y !== null && e.sub_y !== undefined && e.sub_y !== '') return parseFloat(e.sub_y);
    const box = getBox();
    if (box && e.subs_over_hardsub !== false && (e.aspect || 'keep') === 'keep' && parseFloat(e.zoom || 1) <= 1.001) return box[1] + box[3] / 2;
    let ratio = parseFloat(e.margin_ratio) || 0.07;
    if (H > W) ratio = Math.max(ratio, 0.25);      // giống models.auto_margin_v
    else if (['tiktok', 'pop'].includes(e.sub_style)) ratio = Math.max(ratio, 0.1);
    return 1 - ratio - fs / 2 / H;
  }
  /** vị trí dọc trong khung mới -> vị trí trên khung video đang hiện */
  const toFrameY = (y) => (cropOn() && plan.axis === 'y' ? cropAt(base.currentTime) - plan.span / 2 + y * plan.span : y);
  const fromFrameY = (y) => (cropOn() && plan.axis === 'y' ? (y - (cropAt(base.currentTime) - plan.span / 2)) / plan.span : y);
  let viewKey = '';
  function refreshSub() {
    const vk = `${getPath(getEff(), 'edit.aspect')}|${P.mode}|${plan ? 1 : 0}`;
    if (vk !== viewKey) { viewKey = vk; layout(); return; }     // đổi khung thì tính lại cỡ khung xem, layout sẽ gọi lại hàm này
    paintCrop();
    refreshOverlays();
    applyLook();
    const inCut = P.mode !== 'final' && !!cutAt(base.currentTime);
    cutBadge.hidden = !inCut || !base.paused;
    if (P.mode !== 'preview') return;
    const eff = getEff();
    const e = (eff && eff.edit) || {};
    const { W, H, k } = viewSize();
    const style = e.sub_style || 'classic';
    const fs = fontPx(e, W, H);
    const prim = assToHex(e.primary_color || '&H00FFFFFF');
    const hl = assToHex(e.highlight_color || '&H0000E5FF');
    const outC = assToHex(e.outline_color || '&H00000000');
    const outline = style === 'cinema' ? Math.max(1, Math.floor(fs / 30)) : style === 'tiktok' || style === 'pop' ? Math.max(parseInt(e.outline ?? 3, 10), Math.round(fs / (style === 'pop' ? 10 : 12))) : parseInt(e.outline ?? 3, 10);
    const cy = subCenterY(e, W, H, fs);
    sub.style.top = clamp(toFrameY(cy), 0, 1) * 100 + '%';
    subLine.style.fontFamily = `"${e.font || 'Arial'}", Arial, sans-serif`;
    subLine.style.fontWeight = e.bold === false ? '400' : '700';
    subLine.style.fontSize = fs * k + 'px';
    subLine.style.color = prim;
    subLine.className = 'sub-line s-' + style;
    if (style === 'box') {
      subLine.style.setProperty('--stroke', '0px');
    } else {
      subLine.style.setProperty('--stroke', Math.max(0, outline * 2 * k) + 'px');
      subLine.style.setProperty('--stroke-c', outC);
    }
    if (e.burn_subs === false) { subLine.replaceChildren(); subLine.dataset.key = ''; return; }
    const t = base.currentTime;
    const segs = getSegs();
    let cur = null, curI = -1;
    for (let i = 0; i < segs.length; i++) {
      const s = segs[i];
      if (!(s.trans || '').trim()) continue;
      const a = s.dub_start != null ? s.dub_start : s.start;
      let b = Math.max(s.dub_end != null ? s.dub_end : s.end, s.end);
      const nxt = segs.slice(i + 1).find((x) => (x.trans || '').trim());
      if (nxt) b = Math.min(b, (nxt.dub_start != null ? nxt.dub_start : nxt.start) - 0.02);
      if (t >= a && t < Math.max(a + 0.3, b)) { cur = s; curI = i; break; }
      if (a > t) break;
    }
    if (!cur) { subLine.replaceChildren(); subLine.dataset.key = ''; return; }
    const upper = style === 'pop' || !!e.uppercase;
    const text = upper ? cur.trans.toUpperCase() : cur.trans;
    if (style === 'classic' || style === 'box' || style === 'cinema') {
      if (subLine.dataset.key !== `${curI}|${text}`) { subLine.dataset.key = `${curI}|${text}`; subLine.replaceChildren(el('span', { class: 'sub-txt', text })); }
      return;
    }
    subLine.dataset.key = '';
    const a = cur.dub_start != null ? cur.dub_start : cur.start;
    const sp = Math.max(a + 0.2, Math.min(cur.dub_end != null ? cur.dub_end : cur.end, Math.max(cur.dub_end != null ? cur.dub_end : cur.end, cur.end)));
    const ws = text.split(/\s+/).filter(Boolean);
    const wts = weights(ws);
    const span = sp - a, tot = wts.reduce((x, y) => x + y, 0);
    const starts = [];
    let acc = 0;
    for (const w of wts) { starts.push(a + (span * acc) / tot); acc += w; }
    let wi = 0;
    for (let i = 0; i < starts.length; i++) if (t >= starts[i]) wi = i;
    if (style === 'karaoke') {
      subLine.replaceChildren(el('span', { class: 'sub-txt' }, ws.map((w, i) => [el('span', { style: { color: i <= wi ? hl : prim }, text: w }), i < ws.length - 1 ? ' ' : ''])));
      return;
    }
    const margin = Math.round(W * 0.06);
    const maxChars = Math.max(8, Math.floor((W - 2 * margin) / (fs * (upper ? 0.68 : 0.56))));
    const size = style === 'pop' ? Math.min(parseInt(e.tiktok_chunk || 7, 10), 4) : parseInt(e.tiktok_chunk || 7, 10);
    const gs = chunks(ws, size, maxChars);
    const g = gs.find((x) => x.includes(wi)) || gs[0];
    subLine.replaceChildren(el('span', { class: 'sub-txt' }, g.map((j, n) => [
      el('span', { class: j === wi ? 'sub-word on' : 'sub-word', style: j === wi ? { color: hl } : null, text: ws[j] }), n < g.length - 1 ? ' ' : ''])));
  }

  // ---- kéo phụ đề để đổi vị trí
  let dragSub = false;
  sub.addEventListener('pointerdown', (e) => { if (e.button !== 0) return; dragSub = true; sub.setPointerCapture(e.pointerId); guide.hidden = false; e.preventDefault(); });
  sub.addEventListener('pointermove', (e) => {
    if (!dragSub) return;
    const r = frame.getBoundingClientRect();
    const y = clamp((e.clientY - r.top) / r.height, 0.04, 0.96);
    sub.style.top = y * 100 + '%';
    guide.style.top = y * 100 + '%';
    P.dragY = y;
  });
  const endSub = () => {
    if (!dragSub) return;
    dragSub = false;
    guide.hidden = true;
    if (P.dragY != null) { onSubY(+clamp(fromFrameY(P.dragY), 0.02, 0.98).toFixed(3)); P.dragY = null; }
  };
  sub.addEventListener('pointerup', endSub);
  sub.addEventListener('pointercancel', endSub);
  sub.addEventListener('dblclick', () => onSubY(null));

  // ---- thanh so sánh
  function paintCompare() {
    const pctv = P.cmp * 100;
    after.style.clipPath = `inset(0 0 0 ${pctv}%)`;
    handle.style.left = pctv + '%';
  }
  let dragCmp = false;
  frame.addEventListener('pointerdown', (e) => {
    if (P.mode !== 'compare' || e.target === sub) return;
    dragCmp = true;
    frame.setPointerCapture(e.pointerId);
    moveCmp(e);
  });
  function moveCmp(e) { const r = frame.getBoundingClientRect(); P.cmp = clamp((e.clientX - r.left) / r.width, 0, 1); paintCompare(); }
  frame.addEventListener('pointermove', (e) => { if (dragCmp) moveCmp(e); });
  frame.addEventListener('pointerup', () => { dragCmp = false; });
  frame.addEventListener('pointercancel', () => { dragCmp = false; });
  base.addEventListener('click', () => { if (P.mode !== 'compare') toggle(); });

  // ---- vòng cập nhật
  function paintTime() {
    const d = base.duration || 0, t = base.currentTime || 0;
    timeEl.textContent = `${fmtTime(t, 1)} / ${fmtTime(d, 1)}`;
    if (document.activeElement !== scrub || !scrubbing) {
      scrub.value = d ? String(t / d) : '0';
      scrub.style.setProperty('--p', (d ? (t / d) * 100 : 0) + '%');
    }
  }
  let scrubbing = false;
  scrub.addEventListener('input', () => {
    scrubbing = true;
    const d = base.duration || 0;
    scrub.style.setProperty('--p', parseFloat(scrub.value) * 100 + '%');
    try { base.currentTime = parseFloat(scrub.value) * d; } catch (_) { /* chưa nạp */ }
    syncFollowers(true);
    refreshSub();
    onTime(time());
  });
  scrub.addEventListener('change', () => { scrubbing = false; });
  let raf = 0;
  function tick() {
    raf = requestAnimationFrame(tick);
    if (base.paused) return;
    if (P.mode !== 'final') {      // xem trước đúng như video sẽ dựng: nhảy qua đoạn đã cắt
      const c = cutAt(base.currentTime);
      if (c) {
        if (c[1] >= (base.duration || Infinity) - 0.05) { pause(); return; }
        try { base.currentTime = c[1]; } catch (_) { /* chưa nạp */ }
        syncFollowers(true);
      }
    }
    if (P.stopAt != null) {
      const t = time();
      if (t >= P.stopAt) { pause(); P.stopAt = null; } else if (t < (P.stopFrom || 0) - 0.5) P.stopAt = null;
    }
    syncFollowers(false);
    paintTime();
    refreshSub();
    onTime(time());
  }
  base.addEventListener('play', () => { playBtn.replaceChildren(icon('pause')); syncFollowers(true); });
  base.addEventListener('pause', () => { playBtn.replaceChildren(icon('play')); P.stopAt = null; syncFollowers(false); });
  base.addEventListener('seeked', () => { syncFollowers(true); paintTime(); refreshSub(); onTime(time()); });
  base.addEventListener('loadedmetadata', () => { paintTime(); layout(); paintSafe(); });
  base.addEventListener('ended', () => { playBtn.replaceChildren(icon('play')); });
  raf = requestAnimationFrame(tick);
  const ro = new ResizeObserver(layout);
  ro.observe(stage);
  function destroy() {
    ovDrag = null;
    cancelAnimationFrame(raf);
    ro.disconnect();
    for (const v of [base, band, after]) { v.pause(); v.removeAttribute('src'); v.load(); }
    dub.pause();
    dub.removeAttribute('src');
  }
  return P;
}
