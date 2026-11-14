/* Trang Sửa ảnh: nhúng miniPaint (MIT, static/vendor/minipaint) và nối với Studio566.
 * Nhận ảnh: tệp trên máy, khung hình trong video (đã xóa sub gốc), ảnh bìa, thư viện ảnh.
 * Trả ảnh: lưu làm ảnh bìa của video, lưu vào thư viện ảnh (làm logo, sticker), tải về máy.
 * Lưu kèm bản nhiều lớp để lần sau mở lại vẫn sửa được từng lớp.
 *
 * Địa chỉ:  #/image | #/image/cover/<job> | #/image/frame/<job>/<giây> | #/image/file/<tên> */
import {
  api, busy, clamp, confirmDialog, debounce, el, enc, fmtDur, fmtTime, icon, loadingState, modalHead, openModal, promptDialog, put, toast,
} from './core.js';

const FRAME_URL = '/static/vendor/minipaint/index.html';

/** Mở ảnh thành tài liệu mới đúng kích thước ảnh, dùng đường load_json chính thức của miniPaint. */
async function openAsDocument(win, url, name) {
  const img = await new Promise((res, rej) => {
    const i = new Image();
    i.onload = () => res(i);
    i.onerror = () => rej(new Error('Không mở được ảnh này'));
    i.src = url;
  });
  const cv = document.createElement('canvas');
  cv.width = img.naturalWidth;
  cv.height = img.naturalHeight;
  cv.getContext('2d').drawImage(img, 0, 0);
  const tpl = JSON.parse(win.FileSave.export_as_json());
  const base = tpl.layers[0] || {};
  const layer = Object.assign({}, base, {
    id: 1, parent_id: 0, name, type: 'image', link: null, x: 0, y: 0, width: img.naturalWidth, height: img.naturalHeight,
    width_original: img.naturalWidth, height_original: img.naturalHeight, visible: true, is_vector: false, opacity: 100, order: 1, composition: 'source-over',
    rotate: 0, params: {}, status: null, color: null, filters: [], render_function: null, data: '',
  });
  const doc = {
    info: Object.assign({}, tpl.info, { width: img.naturalWidth, height: img.naturalHeight, layer_active: 1, guides: [] }),
    user_fonts: {}, layers: [layer], data: [{ id: 1, data: cv.toDataURL('image/png') }],
  };
  await win.FileOpen.load_json(doc);
  fitView(win);
}

/** Sau khi đổi tài liệu: vẽ lại khung và thu phóng vừa màn hình (ảnh dọc 1080x1920 không thì tràn ra ngoài). */
function fitView(win) {
  win.dispatchEvent(new Event('resize'));
  const b = win.document.getElementById('zoom_fit');
  if (b) setTimeout(() => b.click(), 60);
}

function flatten(win, type, quality) {
  const dim = win.Layers.get_dimensions();
  const cv = document.createElement('canvas');
  cv.width = dim.width;
  cv.height = dim.height;
  const ctx = cv.getContext('2d');
  win.Layers.convert_layers_to_canvas(ctx, null, false);
  return new Promise((res, rej) => cv.toBlob((b) => (b ? res(b) : rej(new Error('Không xuất được ảnh'))), type, quality));
}

export async function viewImageLab(main, alive, arg) {
  const parts = String(arg || '').split('/').filter(Boolean);
  const mode = parts[0] || '';
  const ctx = { mode, job: '', jobTitle: '', file: '', t: 0, dirty: false };
  if (mode === 'cover' || mode === 'frame') ctx.job = parts[1] || '';
  if (mode === 'frame') ctx.t = parseFloat(parts[2]) || 0;
  if (mode === 'file') ctx.file = parts.slice(1).join('/');
  if (ctx.job) {
    try { ctx.jobTitle = (await api('GET', `/api/jobs/${enc(ctx.job)}`)).meta.title || ctx.job; } catch (_) { ctx.job = ''; }
    if (!alive()) return null;
  }

  const frame = el('iframe', { class: 'il-frame', title: 'Trình sửa ảnh miniPaint', src: FRAME_URL });
  const spinner = el('div', { class: 'il-loading' }, loadingState('Đang mở trình sửa ảnh…'));
  const label = el('div', { class: 'il-label dim small' });
  const fileInp = el('input', { type: 'file', accept: 'image/*', hidden: true, onchange: () => { const f = fileInp.files[0]; if (f) openFile(f); fileInp.value = ''; } });
  const openBtn = el('button', { class: 'btn btn-sm', onclick: () => fileInp.click() }, icon('upload'), 'Mở ảnh');
  const frameBtn = el('button', { class: 'btn btn-sm', onclick: () => pickFrame() }, icon('film'), 'Khung hình video');
  const libBtn = el('button', { class: 'btn btn-sm', onclick: () => openLibrary() }, icon('image'), 'Thư viện ảnh');
  const coverBtn = el('button', { class: 'btn btn-sm btn-primary', hidden: !ctx.job, title: 'Dùng ảnh này làm ảnh bìa của video', onclick: () => busy(coverBtn, saveCover) }, icon('check'), 'Lưu làm ảnh bìa');
  const saveBtn = el('button', { class: 'btn btn-sm' + (ctx.job ? '' : ' btn-primary'), title: 'Lưu để dùng làm logo, sticker, lớp phủ trong video', onclick: () => busy(saveBtn, saveToLibrary) }, icon('save'), 'Lưu vào thư viện');
  const dlBtn = el('button', { class: 'btn btn-sm btn-icon', title: 'Tải về máy (PNG)', 'aria-label': 'Tải về máy', onclick: () => busy(dlBtn, download) }, icon('download'));
  const backLink = ctx.job ? el('a', { class: 'btn btn-sm btn-icon btn-ghost', href: '#/studio/' + enc(ctx.job), title: 'Về Studio', 'aria-label': 'Về Studio' }, icon('back')) : null;
  main.append(
    el('div', { class: 'il-bar' }, backLink, icon('image'), el('b', { text: 'Sửa ảnh' }), label, el('span', { class: 'grow' }),
      fileInp, openBtn, frameBtn, libBtn, el('span', { class: 'tb-sep' }), coverBtn, saveBtn, dlBtn),
    el('div', { class: 'il-stage' }, frame, spinner));

  function paintLabel() {
    label.textContent = ctx.job ? `${ctx.mode === 'cover' ? 'Ảnh bìa' : 'Khung hình'} của: ${ctx.jobTitle}` : ctx.file ? ctx.file : 'Ảnh mới';
  }
  paintLabel();
  const win = () => frame.contentWindow;

  async function ready() {
    return new Promise((res) => {
      const start = Date.now();
      const check = () => {
        if (!alive()) return;
        const w = win();
        if (w && w.Layers && w.FileOpen && w.FileSave && w.AppConfig && w.AppConfig.layer) { res(true); return; }
        if (Date.now() - start > 20000) { res(false); return; }
        setTimeout(check, 100);
      };
      frame.addEventListener('load', check, { once: true });
    });
  }
  async function openUrl(url, name) {
    try {
      await openAsDocument(win(), url, name);
    } catch (e) {
      toast(e.message || 'Không mở được ảnh này', 'error');
    }
  }
  async function loadProject(url) {
    const r = await fetch(url);
    if (!r.ok) return false;
    await win().FileOpen.load_json(await r.json());
    fitView(win());
    return true;
  }
  function openFile(f) {
    const u = URL.createObjectURL(f);
    ctx.file = f.name;
    paintLabel();
    openUrl(u, f.name).finally(() => setTimeout(() => URL.revokeObjectURL(u), 3000));
  }

  // ------------------------------------------------ khung hình trong video, đã xóa sub gốc
  async function pickFrame() {
    const jobs = (await api('GET', '/api/jobs')).jobs || [];
    if (!jobs.length) { toast('Chưa có video nào trong Thư viện', 'info'); return; }
    let cur = jobs.find((j) => j.id === ctx.job) || jobs[0];
    let t = ctx.t || Math.min(1.5, (cur.duration || 3) / 3);
    const sel = el('select', { class: 'input', 'aria-label': 'Chọn video', onchange: () => { cur = jobs.find((j) => j.id === sel.value); t = Math.min(1.5, (cur.duration || 3) / 3); paintSlider(); load(); } },
      jobs.map((j) => el('option', { value: j.id }, `${j.title_vi || j.title || j.id} (${fmtDur(j.duration)})`)));
    sel.value = cur.id;
    const clean = el('input', { type: 'checkbox', checked: true, onchange: () => load() });
    const img = el('img', { class: 'il-pick-img', alt: 'Khung hình' });
    const tLabel = el('span', { class: 'mono' });
    const slider = el('input', { type: 'range', class: 'range', min: 0, step: 0.1, 'aria-label': 'Thời gian', oninput: () => { t = parseFloat(slider.value); paintSlider(); loadSoon(); } });
    const url = () => `/api/jobs/${enc(cur.id)}/frame.jpg?t=${t.toFixed(2)}${clean.checked ? '&clean=1' : ''}`;
    function paintSlider() {
      slider.max = String(Math.max(0.1, cur.duration || 0));
      slider.value = String(t);
      slider.style.setProperty('--p', (cur.duration ? (t / cur.duration) * 100 : 0) + '%');
      tLabel.textContent = fmtTime(t);
    }
    const load = () => { img.src = url(); };
    const loadSoon = debounce(load, 180);
    img.addEventListener('error', () => toast('Không lấy được khung hình', 'error'));
    const useBtn = el('button', {
      class: 'btn btn-primary', onclick: () => busy(useBtn, async () => {
        ctx.job = cur.id; ctx.jobTitle = cur.title_vi || cur.title; ctx.mode = 'frame'; ctx.t = t;
        coverBtn.hidden = false;
        paintLabel();
        await openUrl(url(), `Khung ${fmtTime(t)}`);
        m.close();
      }),
    }, icon('check'), 'Sửa khung này');
    const m = openModal([
      modalHead('film', 'Lấy khung hình từ video', () => m),
      el('div', { class: 'modal-body il-pick' }, sel,
        el('div', { class: 'il-pick-view' }, img),
        el('div', { class: 'pick-controls' }, slider, tLabel),
        el('label', { class: 'il-check small' }, clean, 'Xóa sub gốc trên khung này')),
      el('div', { class: 'modal-foot' }, el('button', { class: 'btn btn-ghost', onclick: () => m.close() }, 'Hủy'), useBtn),
    ], { cls: 'modal-wide' });
    paintSlider();
    load();
  }

  // ------------------------------------------------ thư viện ảnh
  async function openLibrary() {
    const grid = el('div', { class: 'il-lib' });
    let m = null;
    async function paint() {
      const items = (await api('GET', '/api/images')).items || [];
      if (!items.length) { put(grid, el('p', { class: 'muted small', text: 'Chưa có ảnh nào. Bấm Lưu vào thư viện để giữ ảnh đang sửa.' })); return; }
      put(grid, items.map((it) => {
        const del = el('button', {
          class: 'btn btn-xs btn-icon btn-ghost il-del', title: 'Xóa ảnh này', 'aria-label': 'Xóa ảnh này', onclick: async (e) => {
            e.stopPropagation();
            if (!await confirmDialog('Xóa ảnh này?', it.name, { okText: 'Xóa', danger: true })) return;
            await api('DELETE', `/api/images/${enc(it.name)}`);
            paint();
          },
        }, icon('trash'));
        const open = async () => {
          ctx.file = it.name; ctx.mode = 'file'; paintLabel();
          m.close();
          if (it.project) { try { if (await loadProject(`/api/images/${enc(it.name)}/project`)) return; } catch (_) { /* mở dạng ảnh phẳng */ } }
          await openUrl(it.url, it.name);
        };
        return el('button', { type: 'button', class: 'il-item', title: it.name, onclick: open }, el('img', { alt: '', loading: 'lazy', src: it.url }), el('span', { class: 'small il-item-name', text: it.name }), del);
      }));
    }
    m = openModal([modalHead('image', 'Thư viện ảnh', () => m), el('div', { class: 'modal-body' }, el('p', { class: 'muted small', text: 'Ảnh ở đây dùng được làm logo và lớp phủ trong video. Ảnh lưu từ trang này mở lại vẫn sửa được từng lớp.' }), grid)], { cls: 'modal-wide' });
    await paint();
  }

  // ------------------------------------------------ lưu
  async function send(path, blob, type) {
    const r = await fetch(path, { method: 'PUT', headers: { 'Content-Type': type }, body: blob });
    if (!r.ok) {
      let msg = `Lỗi ${r.status}`;
      try { msg = (await r.json()).detail || msg; } catch (_) { /* giữ mặc định */ }
      throw new Error(msg);
    }
    return r.json();
  }
  async function saveCover() {
    const blob = await flatten(win(), 'image/jpeg', 0.93);
    await send(`/api/jobs/${enc(ctx.job)}/cover/upload`, blob, 'image/jpeg');
    await send(`/api/jobs/${enc(ctx.job)}/cover/project`, win().FileSave.export_as_json(), 'application/json');
    toast('Đã lưu làm ảnh bìa của video', 'success', { actions: [{ label: 'Về Studio', onClick: () => { location.hash = '#/studio/' + enc(ctx.job); } }] });
  }
  async function saveToLibrary() {
    const guess = (ctx.file || 'anh').replace(/\.[^.]+$/, '');
    const name = await promptDialog('Lưu vào thư viện ảnh', 'Tên ảnh', { value: guess, okText: 'Lưu' });
    if (!name) return;
    const blob = await flatten(win(), 'image/png');
    const sameFile = ctx.file && name === guess && ctx.mode === 'file';
    const r = await send(`/api/images?name=${enc(name)}${sameFile ? '&overwrite=1' : ''}`, blob, 'image/png');
    await send(`/api/images/${enc(r.name)}/project`, win().FileSave.export_as_json(), 'application/json');
    ctx.file = r.name;
    paintLabel();
    toast('Đã lưu vào thư viện ảnh', 'success');
  }
  async function download() {
    const blob = await flatten(win(), 'image/png');
    const a = el('a', { href: URL.createObjectURL(blob), download: (ctx.file || 'anh').replace(/\.[^.]+$/, '') + '.png' });
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 3000);
  }

  // ------------------------------------------------ khởi động
  const ok = await ready();
  if (!alive()) return null;
  spinner.hidden = true;
  if (!ok) { toast('Không mở được trình sửa ảnh', 'error'); return null; }
  if (mode === 'cover' && ctx.job) {
    let done = false;
    try { done = await loadProject(`/api/jobs/${enc(ctx.job)}/cover/project`); } catch (_) { done = false; }
    if (!done) await openUrl(`/api/jobs/${enc(ctx.job)}/cover.jpg?v=${Date.now()}`, 'Ảnh bìa');
  } else if (mode === 'frame' && ctx.job) {
    await openUrl(`/api/jobs/${enc(ctx.job)}/frame.jpg?t=${clamp(ctx.t, 0, 1e6).toFixed(2)}&clean=1`, `Khung ${fmtTime(ctx.t)}`);
  } else if (mode === 'file' && ctx.file) {
    let done = false;
    try { done = await loadProject(`/api/images/${enc(ctx.file)}/project`); } catch (_) { done = false; }
    if (!done) await openUrl(`/api/images/${enc(ctx.file)}`, ctx.file);
  }
  return null;
}
