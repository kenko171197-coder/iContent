/* Bảng thuộc tính bên phải Studio: Phụ đề, Giọng, Hình ảnh, Âm thanh, Đăng bài, Kiểm tra. Đổi là lưu ngay vào options.json của video. */
import {
  S, api, busy, clamp, clone, confirmDialog, copyBtn, debounce, deepMerge, diff, effEngine, el, enc, fillVoiceSelect, fmtTime, genderOf, getPath, icon, modalHead, openModal,
  previewVoice, put, reveal, setPath, speakerColor, toast, videoModal, voiceHooks, voiceLabel,
} from './core.js';
import { FieldList } from './options.js';

const TABS = [
  ['subs', 'Phụ đề', 'sub'], ['edit', 'Dựng', 'scissors'], ['voice', 'Giọng', 'mic'], ['picture', 'Hình', 'image'],
  ['sound', 'Tiếng', 'wave'], ['publish', 'Đăng', 'send'], ['qa', 'Kiểm tra', 'shield'],
];

export function Inspector({ st, id, meta, getBox, hasFile, player, retranslate, startExport, focusLine, onOptionChange, refreshQa, reloadJob, markStale, save, editing }) {
  const body = el('div', { class: 'insp-body' });
  const tabBtns = {};
  const tabRow = el('div', { class: 'insp-tabs', role: 'tablist' }, TABS.map(([k, label, ic]) => {
    const b = el('button', { type: 'button', class: 'insp-tab', role: 'tab', onclick: () => open(k) }, icon(ic), el('span', { text: label }));
    tabBtns[k] = b;
    return b;
  }));
  const root = el('section', { class: 'pane insp' }, tabRow, body);
  let cur = localStorage.getItem('ic.inspTab') || 'subs';
  if (!tabBtns[cur]) cur = 'subs';
  const built = {};

  // ---- lưu tùy chọn
  let saving = Promise.resolve();
  const persist = debounce(() => {
    saving = saving.then(async () => {
      const opts = diff(st.vals, S.config) || {};
      try {
        await api('PUT', `/api/jobs/${enc(id)}/options`, { options: opts });
        st.job.options = opts;
      } catch (e) { toast('Không lưu được tùy chọn: ' + e.message, 'error'); }
    });
    return saving;
  }, 350);
  function changed() { onOptionChange(); persist(); refreshSoon(); }
  function setOption(path, v) {
    setPath(st.vals, path, v);
    changed();
    Object.values(built).forEach((b) => b && b.sync && b.sync());
  }
  const baseCfg = () => S.config;

  // ---- khung cắt khi đổi tỉ lệ khung hình
  let rfKey = '', rfTok = 0, rfBusy = false, rfError = '';
  function staticPlan(aspect) {
    const m = meta();
    const t = { '9:16': 9 / 16, '16:9': 16 / 9, '1:1': 1 }[aspect];
    const src = (m.width || 1) / (m.height || 1);
    if (!t || Math.abs(src / t - 1) < 0.02) return null;
    const axis = t < src ? 'x' : 'y';
    const span = axis === 'x' ? t / src : src / t;
    let f = parseFloat(getPath(st.vals, axis === 'x' ? 'edit.focus_x' : 'edit.focus_y'));
    if (Number.isNaN(f)) f = 0.5;
    const c = span / 2 + f * (1 - span);      // giống bộ lọc crop trong render.py, cũng đứng sau bước lật và phóng
    return { axis, span, segs: [[0, m.duration || 1, c, c]], shots: [], isStatic: true };
  }
  async function refreshReframe() {
    const aspect = getPath(st.vals, 'edit.aspect') || 'keep';
    const fit = getPath(st.vals, 'edit.fit') || 'blur';
    if (aspect === 'keep' || !['track', 'crop'].includes(fit)) { rfKey = ''; rfTok++; rfBusy = false; player.setPlan(null); paintRf(); return; }
    if (fit === 'crop') { rfKey = ''; rfTok++; rfBusy = false; player.setPlan(staticPlan(aspect)); paintRf(); return; }
    const key = JSON.stringify([aspect, getPath(st.vals, 'edit.reframe_pins') || [], !!getPath(st.vals, 'edit.flip'), getPath(st.vals, 'edit.zoom') || 1]);
    if (key === rfKey) return;
    rfKey = key;
    const tok = ++rfTok;
    rfBusy = true; rfError = '';
    paintRf();
    try {
      persist.flush();
      await saving;
      const r = await api('GET', `/api/jobs/${enc(id)}/reframe?aspect=${enc(aspect)}`);
      if (tok !== rfTok) return;
      player.setPlan(r.plan);
    } catch (e) {
      if (tok !== rfTok) return;
      rfError = e.message;
      rfKey = '';
      player.setPlan(null);
    }
    rfBusy = false;
    paintRf();
  }
  const refreshSoon = debounce(refreshReframe, 400);
  function paintRf() { if (built.picture && built.picture.paintRf) built.picture.paintRf(); }

  function open(k) {
    cur = k;
    localStorage.setItem('ic.inspTab', k);
    Object.entries(tabBtns).forEach(([t, b]) => { b.classList.toggle('active', t === k); b.setAttribute('aria-selected', t === k ? 'true' : 'false'); });
    if (!built[k]) built[k] = BUILD[k]();
    body.replaceChildren(built[k].root);
    if (built[k].onShow) built[k].onShow();
    body.scrollTop = 0;
  }

  // ------------------------------------------------ tab Phụ đề
  function tabSubs() {
    const fl = FieldList(['edit.sub_style', 'edit.font', 'edit.font_size_ratio', 'edit.primary_color', 'edit.highlight_color', 'edit.outline_color', 'edit.outline', 'edit.uppercase', 'edit.burn_subs'], st.vals, baseCfg(), changed);
    const posTxt = el('span', { class: 'muted small' });
    const resetBtn = el('button', { class: 'btn btn-xs', onclick: () => setOption('edit.sub_y', null) }, icon('undo'), 'Tự động');
    const syncPos = () => {
      const y = getPath(st.vals, 'edit.sub_y');
      const manual = y !== null && y !== undefined && y !== '';
      posTxt.textContent = manual ? `Đặt tay: ${Math.round(y * 100)}% chiều cao khung` : 'Tự động: nằm đúng vị trí sub gốc, hoặc tránh nút của TikTok';
      resetBtn.hidden = !manual;
      player.refreshSub();
    };
    const previewNote = el('div', { class: 'note' }, icon('eye'),
      el('div', { text: 'Chọn Xem trước trên trình phát để thấy phụ đề thay đổi ngay. Kéo phụ đề trên video để đổi vị trí.' }),
      el('button', { class: 'btn btn-xs', onclick: () => player.setMode('preview') }, 'Xem trước'));
    const root = el('div', {}, previewNote, fl.root, el('div', { class: 'opt-row' }, el('div', { class: 'opt-label', text: 'Vị trí phụ đề' }), el('div', { class: 'pos-row' }, posTxt, resetBtn)));
    syncPos();
    return {
      root, sync() { fl.sync(); syncPos(); },
      onShow() { previewNote.hidden = player.mode === 'preview'; },
      onMode() { previewNote.hidden = player.mode === 'preview'; },
    };
  }

  // ------------------------------------------------ tab Dựng: cắt đoạn, chữ và ảnh trên video, màu, mở đầu, kết thúc
  function tabEdit() {
    const fl = FieldList(['edit.look', 'edit.lut', 'edit.fade_in', 'edit.fade_out', 'edit.intro', 'edit.outro', 'edit.card_seconds'], st.vals, baseCfg(), () => { changed(); player.refreshSub(); });
    const cutBox = el('div', { class: 'block block-first' });
    const ovBox = el('div', { class: 'block' });
    const fmtS = (v) => v.toFixed(1).replace('.', ',') + ' giây';
    const gapSel = el('select', { class: 'input input-xs', 'aria-label': 'Khoảng lặng tối thiểu' }, [['0.8', 'từ 0,8 giây'], ['1.2', 'từ 1,2 giây'], ['2', 'từ 2 giây'], ['4', 'từ 4 giây']].map(([v, l]) => el('option', { value: v }, l)));
    function paintCuts() {
      const list = editing.cuts();
      const dur = meta().duration || 0;
      const removed = list.reduce((n, [a, b]) => n + b - a, 0);
      const sel = editing.selection();
      const hasSel = sel && sel[1] - sel[0] >= 0.05;
      const autoBtn = el('button', {
        class: 'btn btn-xs', title: 'Tìm các đoạn không có lời rồi cắt, chừa lại một chút để không bị giật', onclick: () => busy(autoBtn, async () => {
          const r = await api('POST', `/api/jobs/${enc(id)}/silence`, { min_gap: Number(gapSel.value) });
          if (!r.gaps.length) { toast('Không có khoảng lặng nào dài như vậy', 'info'); return; }
          const before = editing.cuts().length;
          if (editing.setCuts([...editing.cuts(), ...r.gaps])) toast(`Đã cắt ${r.gaps.length} khoảng lặng. Bấm Ctrl+Z nếu muốn hoàn tác`, 'success');
          void before;
        }),
      }, icon('wand'), 'Tự cắt khoảng lặng');
      put(cutBox,
        el('div', { class: 'block-head' }, el('h4', { text: 'Cắt đoạn' }), list.length ? el('button', { class: 'btn btn-xs btn-ghost', onclick: () => { editing.setCuts([]); } }, icon('undo'), 'Khôi phục hết') : null),
        el('p', { class: 'muted small', text: 'Kéo trên sóng âm ở timeline để chọn đoạn, rồi bấm Cắt đoạn hoặc phím Delete. Video gốc không bị đụng tới, khôi phục lúc nào cũng được.' }),
        el('div', { class: 'ed-stats' },
          el('div', { class: 'cast-row' }, el('span', { class: 'cast-n mono', text: fmtTime(Math.max(0, dur - removed), 0) }), el('span', { class: 'muted small', text: 'độ dài sau khi cắt' })),
          el('div', { class: 'cast-row' }, el('span', { class: 'cast-n mono', text: String(list.length) }), el('span', { class: 'muted small', text: 'đoạn đã cắt' }))),
        el('div', { class: 'btn-row' },
          el('button', { class: 'btn btn-xs', disabled: !hasSel, onclick: () => editing.cutSelection() }, icon('scissors'), hasSel ? `Cắt ${fmtS(sel[1] - sel[0])} đã chọn` : 'Cắt đoạn đã chọn'),
          el('button', { class: 'btn btn-xs', disabled: !hasSel, title: 'Xuất đoạn đã chọn thành một video riêng', onclick: () => busy(null, () => editing.exportSelection()) }, icon('export'), 'Xuất thành clip')),
        el('div', { class: 'btn-row ed-auto' }, autoBtn, gapSel),
        list.length ? el('div', { class: 'ed-cuts' }, list.map(([a, b], i) => el('div', { class: 'ed-cut' },
          el('button', { class: 'link-btn mono', title: 'Xem chỗ này', onclick: () => editing.seek(Math.max(0, a - 1)) }, `${fmtTime(a)} → ${fmtTime(b)}`),
          el('span', { class: 'dim small', text: fmtS(b - a) }), el('span', { class: 'grow' }),
          el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Khôi phục đoạn này', 'aria-label': 'Khôi phục đoạn này', onclick: () => { const c = editing.cuts().slice(); c.splice(i, 1); editing.setCuts(c); } }, icon('undo'))))) : null);
    }
    function addText() {
      const dur = meta().duration || editing.time() + 3;
      const t = Math.max(0, Math.min(editing.time(), dur - 1));
      const list = editing.overlays().slice();
      list.push({ type: 'text', text: 'Chữ của bạn', start: +t.toFixed(2), end: +Math.min(dur, t + 3).toFixed(2), x: 0.5, y: 0.2, size: (meta().height || 0) > (meta().width || 0) ? 0.042 : 0.08, color: '#FFFFFF', outline: '#000000', bold: true, style: 'plain', fade: 0.2 });
      setPath(st.vals, 'edit.overlays', list);
      if (player.mode !== 'preview') player.setMode('preview');
      editing.pickOverlay(list.length - 1);
      editing.commitEdit();
    }
    async function addImage(btn) {
      const items = (await api('GET', '/api/images')).items || [];
      const grid = el('div', { class: 'il-lib' }, items.length ? items.map((it) => el('button', {
        type: 'button', class: 'il-item', title: it.name, onclick: () => {
          const dur = meta().duration || editing.time() + 3;
          const t = Math.max(0, Math.min(editing.time(), dur - 1));
          const list = editing.overlays().slice();
          list.push({ type: 'image', path: it.path, url: it.url, start: +t.toFixed(2), end: +Math.min(dur, t + 5).toFixed(2), x: 0.8, y: 0.2, size: 0.25, opacity: 1 });
          setPath(st.vals, 'edit.overlays', list);
          if (player.mode !== 'preview') player.setMode('preview');
          editing.pickOverlay(list.length - 1);
          editing.commitEdit();
          m.close();
        },
      }, el('img', { alt: '', loading: 'lazy', src: it.url }), el('span', { class: 'small il-item-name', text: it.name }))) : el('p', { class: 'muted small', text: 'Thư viện ảnh còn trống. Tải ảnh lên, hoặc tạo trong trang Sửa ảnh.' }));
      const up = el('input', {
        type: 'file', accept: 'image/png,image/webp,image/jpeg', hidden: true, onchange: async () => {
          const f = up.files[0];
          if (!f) return;
          try {
            const r = await fetch(`/api/images?name=${enc(f.name.replace(/\.[^.]+$/, ''))}`, { method: 'PUT', body: f });
            if (!r.ok) throw new Error('Không tải được ảnh này');
            m.close();
            addImage(btn);
          } catch (e) { toast(e.message, 'error'); }
        },
      });
      const m = openModal([
        modalHead('image', 'Chọn ảnh, sticker hoặc logo', () => m),
        el('div', { class: 'modal-body' }, el('div', { class: 'btn-row' }, up, el('button', { class: 'btn btn-sm', onclick: () => up.click() }, icon('upload'), 'Tải ảnh lên'),
          el('a', { class: 'btn btn-sm', href: `#/image/frame/${enc(id)}/${editing.time().toFixed(2)}` }, icon('edit'), 'Thiết kế trong trình sửa ảnh')), grid),
      ], { cls: 'modal-wide' });
    }
    const paintSoon = debounce(() => { editing.commitEdit(true); }, 300);
    function ovEditor(o, i) {
      const upd = (k, v, soft) => { o[k] = v; player.refreshSub(); if (soft) paintSoon(); else editing.commitEdit(); };
      const num = (k, step, lbl) => el('label', { class: 'ed-num' }, el('span', { class: 'dim small', text: lbl }), el('input', {
        type: 'number', class: 'input input-xs', step, min: 0, value: o[k], onchange: (e) => {
          let v = Number(e.target.value);
          if (k === 'start') v = Math.min(v, o.end - 0.2);
          if (k === 'end') v = Math.max(v, o.start + 0.2);
          e.target.value = v;
          upd(k, v);
        },
      }));
      const slider = (k, min, max, step, lbl, fmt) => {
        const out = el('span', { class: 'mono small dim', text: fmt(o[k]) });
        const r = el('input', { type: 'range', class: 'range', min, max, step, value: o[k], oninput: () => { out.textContent = fmt(Number(r.value)); r.style.setProperty('--p', ((Number(r.value) - min) / (max - min)) * 100 + '%'); upd(k, Number(r.value), true); } });
        r.style.setProperty('--p', ((o[k] - min) / (max - min)) * 100 + '%');
        return el('div', { class: 'ed-slider' }, el('span', { class: 'small', text: lbl }), r, out);
      };
      const place = (y) => el('button', { class: 'btn btn-xs', onclick: () => { o.x = 0.5; o.y = y; editing.commitEdit(); } }, y < 0.3 ? 'Trên' : y > 0.7 ? 'Dưới' : 'Giữa');
      const kids = [];
      if (o.type === 'text') {
        kids.push(el('textarea', { class: 'input', rows: 2, value: o.text, 'aria-label': 'Nội dung chữ', oninput: (e) => upd('text', e.target.value, true), onchange: () => paintOverlays() }),
          slider('size', 0.02, 0.25, 0.005, 'Cỡ chữ', (x) => Math.round(x * 100) + '%'),
          el('div', { class: 'ed-colors' },
            el('label', { class: 'small' }, 'Chữ', el('input', { type: 'color', class: 'color-input', value: o.color || '#ffffff', oninput: (e) => upd('color', e.target.value, true) })),
            o.style === 'box'
              ? el('label', { class: 'small' }, 'Nền', el('input', { type: 'color', class: 'color-input', value: o.bg || '#000000', oninput: (e) => upd('bg', e.target.value, true) }))
              : el('label', { class: 'small' }, 'Viền', el('input', { type: 'color', class: 'color-input', value: o.outline || '#000000', oninput: (e) => upd('outline', e.target.value, true) })),
            el('button', { class: 'btn btn-xs', onclick: () => { o.style = o.style === 'box' ? 'plain' : 'box'; editing.commitEdit(); } }, o.style === 'box' ? 'Dùng viền chữ' : 'Dùng nền hộp')));
      } else {
        kids.push(slider('size', 0.05, 1, 0.01, 'Cỡ ảnh', (x) => Math.round(x * 100) + '%'), slider('opacity', 0.1, 1, 0.05, 'Độ rõ', (x) => Math.round(x * 100) + '%'));
      }
      kids.push(el('div', { class: 'ed-times' }, num('start', 0.1, 'Từ giây'), num('end', 0.1, 'Đến giây'),
        el('button', { class: 'btn btn-xs', title: 'Bắt đầu từ kim phát', onclick: () => { const t = +editing.time().toFixed(2); const len = o.end - o.start; o.start = t; o.end = +(t + len).toFixed(2); editing.commitEdit(); } }, 'Tại kim phát')),
      el('div', { class: 'btn-row' }, el('span', { class: 'small dim', text: 'Đặt vào' }), place(0.12), place(0.5), place(0.85), el('span', { class: 'grow' }),
        el('button', { class: 'btn btn-xs btn-danger', onclick: () => { const l = editing.overlays().slice(); l.splice(i, 1); setPath(st.vals, 'edit.overlays', l); st.ovSel = -1; editing.commitEdit(); } }, icon('trash'), 'Xóa')));
      return el('div', { class: 'ed-ov-edit' }, kids);
    }
    function paintOverlays() {
      const list = editing.overlays();
      const imgBtn = el('button', { class: 'btn btn-xs', onclick: () => busy(imgBtn, () => addImage(imgBtn)) }, icon('image'), 'Thêm ảnh');
      put(ovBox,
        el('div', { class: 'block-head' }, el('h4', { text: 'Chữ và ảnh' }), el('div', { class: 'btn-row ed-tight' }, el('button', { class: 'btn btn-xs', onclick: () => addText() }, icon('type'), 'Thêm chữ'), imgBtn)),
        el('p', { class: 'muted small', text: 'Tiêu đề mở đầu, lời kêu gọi, logo, sticker. Kéo trực tiếp trên video ở chế độ Xem trước, kéo khối trên timeline để đổi thời gian.' }),
        list.map((o, i) => [
          el('button', { type: 'button', class: 'ed-ov' + (i === st.ovSel ? ' active' : ''), onclick: () => { editing.pickOverlay(i === st.ovSel ? -1 : i); if (i !== st.ovSel) return; editing.seek(o.start + 0.05); } },
            icon(o.type === 'image' ? 'image' : 'type'), el('span', { class: 'ed-ov-name', text: o.type === 'image' ? String(o.path || '').split(/[\\/]/).pop() : o.text }), el('span', { class: 'dim small mono', text: `${fmtTime(o.start)} → ${fmtTime(o.end)}` })),
          i === st.ovSel ? ovEditor(o, i) : null,
        ]));
    }
    // --- gợi ý đoạn hay
    const hlBox = el('div', { class: 'block' });
    const hl = { items: null, range: '20-60', profile: localStorage.getItem('ic.clipProfile') || '' };
    const RANGES = [['10-25', '10 đến 25 giây'], ['20-60', '20 đến 60 giây'], ['45-90', '45 đến 90 giây'], ['60-180', '1 đến 3 phút']];
    const hlRange = el('select', { class: 'input input-xs', 'aria-label': 'Độ dài đoạn', onchange: () => { hl.range = hlRange.value; } }, RANGES.map(([v, l]) => el('option', { value: v }, l)));
    hlRange.value = hl.range;
    const hlProfile = el('select', {
      class: 'input input-xs', 'aria-label': 'Khung hình của clip', onchange: () => { hl.profile = hlProfile.value; localStorage.setItem('ic.clipProfile', hl.profile); },
    }, [['', 'Khung như bản chính'], ['tiktok', 'Dọc 9:16 theo nhân vật'], ['feed', 'Vuông 1:1 theo nhân vật'], ['youtube', 'Ngang 16:9']].map(([v, l]) => el('option', { value: v }, l)));
    hlProfile.value = hl.profile;
    function paintHl() {
      const findBtn = el('button', {
        class: 'btn btn-xs', onclick: () => busy(findBtn, async () => {
          const [lo, hi] = hl.range.split('-').map(Number);
          const r = await api('POST', `/api/jobs/${enc(id)}/highlights`, { min: lo, max: hi, count: 6 });
          hl.items = r.items;
          paintHl();
          if (!r.items.length) toast('Không có đoạn nào đủ dài trong khoảng này', 'info');
        }),
      }, icon('spark'), hl.items ? 'Tìm lại' : 'Tìm đoạn hay');
      const rows = (hl.items || []).map((x) => el('div', { class: 'hl-item' },
        el('button', { class: 'hl-score mono', title: 'Điểm chỉ dùng để so sánh các đoạn trong video này. Bấm để nghe đoạn', onclick: () => editing.playRange(x.start, x.end) }, String(x.score)),
        el('div', { class: 'hl-main' },
          el('div', { class: 'hl-time mono' }, `${fmtTime(x.start, 0)} → ${fmtTime(x.end, 0)}`, el('span', { class: 'dim', text: ` · ${Math.round(x.end - x.start)} giây` })),
          el('div', { class: 'hl-first', text: x.first, title: x.first }),
          x.reasons.length ? el('div', { class: 'hl-tags' }, x.reasons.map((t) => el('span', { class: 'hl-tag', text: t }))) : null,
          el('div', { class: 'hl-acts' },
            el('button', { class: 'btn btn-xs btn-ghost', onclick: () => editing.playRange(x.start, x.end) }, icon('play'), 'Nghe'),
            el('button', { class: 'btn btn-xs btn-ghost', onclick: () => editing.selectRange(x.start, x.end) }, icon('crop'), 'Chọn'),
            el('button', { class: 'btn btn-xs btn-ghost', disabled: st.runActive, onclick: () => busy(null, () => editing.exportClips([[x.start, x.end]], hl.profile)) }, icon('export'), 'Xuất')))));
      put(hlBox,
        el('div', { class: 'block-head' }, el('h4', { text: 'Gợi ý đoạn hay' }), findBtn),
        el('p', { class: 'muted small', text: 'Máy chấm theo thứ đo được: độ to của giọng, mật độ lời, nhịp chuyển cảnh, câu mở đầu, và luôn cắt đúng ranh giới câu. Đây không phải AI hiểu nội dung, nên hãy nghe lại trước khi đăng.' }),
        el('div', { class: 'hl-opts' }, hlRange, hlProfile),
        rows.length ? el('div', { class: 'hl-list' }, rows) : null,
        rows.length > 1 ? el('button', { class: 'btn btn-sm hl-all', disabled: st.runActive, onclick: () => busy(null, () => editing.exportClips(hl.items.map((x) => [x.start, x.end]), hl.profile)) }, icon('export'), `Xuất cả ${rows.length} đoạn`) : null);
    }
    const paint = () => { paintCuts(); paintOverlays(); paintHl(); };
    paint();
    return {
      root: el('div', {}, cutBox, hlBox, ovBox, el('div', { class: 'block' }, el('h4', { text: 'Màu, mở đầu và kết thúc' }), fl.root)),
      sync() { fl.sync(); }, onShow: paint, onJob: paint, onEdit: paint, onRun: paintHl,
      onEditDrag() { /* đang kéo trên timeline: không vẽ lại ô nhập để tránh mất con trỏ */ },
    };
  }

  // ------------------------------------------------ tab Giọng
  function tabVoice() {
    const fl = FieldList(['tts.enabled', 'tts.engine', 'tts.voice_mode', 'tts.vieneu_voice', 'tts.vox_voice', 'tts.voice', 'tts.male_voice', 'tts.female_voice', 'tts.max_speed', 'tts.pronounce'], st.vals, baseCfg(), changed);
    const cast = el('div', { class: 'cast' });
    const people = el('div', { class: 'block people' });
    const lang = () => getPath(st.vals, 'translate.target_lang') || 'vi';
    const engine = () => effEngine(getPath(st.vals, 'tts.engine') || 'vieneu', lang());      // VieNeu chỉ đọc tiếng Việt
    const pushPeople = debounce(async () => {
      try {
        await api('PUT', `/api/jobs/${enc(id)}/speakers`, { speakers: st.job.speakers.speakers });
        markStale();
      } catch (e) { toast('Không lưu được: ' + e.message, 'error'); }
    }, 300);
    async function detectPeople(btn) {
      const had = (st.job.speakers && st.job.speakers.speakers) || [];
      if (had.length) {
        const ok = await confirmDialog('Nghe lại toàn video?', 'Người nói của mọi câu sẽ được gán lại, các câu bạn đã đổi người bằng tay sẽ mất. Bản dịch giữ nguyên. Tên và giọng được giữ nếu vẫn nhận ra đúng người đó.', { okText: 'Nghe lại' });
        if (!ok) return null;
      }
      if (st.dirty) await save(true);
      return busy(btn, async () => {
        const r = await api('POST', `/api/jobs/${enc(id)}/speakers/detect`);
        const n = r.speakers.speakers.length;
        toast(n > 1 ? `Nghe ra ${n} người nói. Bấm Cập nhật video để mỗi người có giọng riêng.` : 'Video này chỉ có một người nói', n > 1 ? 'success' : 'info');
        await reloadJob();
        markStale();
      });
    }
    function paintPeople() {
      const list = (st.job.speakers && st.job.speakers.speakers) || [];
      const mode = getPath(st.vals, 'tts.voice_mode') || 'auto';
      people.hidden = mode !== 'auto';
      const detectBtn = el('button', { class: 'btn btn-xs', title: 'Nghe lại toàn video. Giữ nguyên bản dịch.', onclick: () => detectPeople(detectBtn) }, icon('refresh'), list.length ? 'Nghe lại' : 'Nhận diện');
      const head = el('div', { class: 'people-head' }, el('h4', { text: 'Người nói' }), el('span', { class: 'grow' }), detectBtn);
      if (!list.length) {
        put(people, head, el('p', { class: 'muted small', text: 'Video này chưa được nhận diện. Bấm Nhận diện để biết có mấy người nói, rồi cho mỗi người một giọng riêng.' }));
        return;
      }
      if (list.length === 1) {
        put(people, head, el('p', { class: 'muted small', text: 'Nghe ra một người nói trong cả video, nên chỉ cần một giọng lồng. Video một người đóng nhiều vai cũng sẽ như vậy.' }));
        return;
      }
      const rows = list.map((p) => {
        const sel = el('select', { class: 'input input-xs', 'aria-label': `Giọng của ${p.name}`, onchange: () => { p.voice = sel.value; pushPeople(); } });
        const auto = p.auto_voice ? `Tự chọn: ${voiceLabel(engine(), p.auto_voice, lang())}` : 'Tự chọn sau khi cập nhật';
        const fill = () => fillVoiceSelect(sel, engine(), { current: p.voice || '', defaultLabel: auto, lang: lang() });
        fill();
        voiceHooks.add(() => { if (!sel.isConnected) return false; fill(); return true; });
        const hear = el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Nghe thử giọng này', 'aria-label': `Nghe thử giọng của ${p.name}`, onclick: () => previewVoice(engine(), p.voice || p.auto_voice || '', hear, lang()) }, icon('play'));
        const name = el('input', { class: 'input input-xs people-name', value: p.name, spellcheck: 'false', 'aria-label': 'Tên người nói', onchange: () => { p.name = name.value.trim() || p.name; name.value = p.name; pushPeople(); document.querySelectorAll('.ln-spk option[value="' + p.id + '"]').forEach((o) => { o.textContent = p.name; }); } });
        return el('div', { class: 'people-row' },
          el('span', { class: 'people-dot', style: { background: speakerColor(p.id) } }), name,
          el('span', { class: 'dim small people-meta', text: `${p.lines} câu · ${p.gender === 'female' ? 'nữ' : p.gender === 'male' ? 'nam' : '?'}` }),
          el('div', { class: 'people-voice' }, sel, hear));
      });
      put(people, head, ...rows, el('p', { class: 'dim small', text: 'Đổi giọng xong bấm Cập nhật video: chỉ các câu của người đó được đọc lại. Câu bị nhận nhầm người thì đổi ngay ở danh sách câu bên trái.' }));
    }
    const trans = el('div', { class: 'block' },
      el('h4', { text: 'Bản dịch' }),
      el('p', { class: 'muted small', text: 'Đổi văn phong hoặc nhà cung cấp AI rồi dịch lại cả video.' }),
      FieldList(['translate.provider', 'translate.model', 'translate.style', 'translate.glossary'], st.vals, baseCfg(), changed).root,
      el('button', { class: 'btn btn-sm', onclick: () => retranslate() }, icon('globe'), 'Dịch lại toàn bộ'));
    function paint() {
      paintPeople();
      const v = st.job.voice || {};
      const m = st.segs.filter((s) => genderOf(s.gender) === 'male').length;
      const f = st.segs.filter((s) => genderOf(s.gender) === 'female').length;
      cast.hidden = ((st.job.speakers && st.job.speakers.speakers) || []).length > 1;
      put(cast,
        el('div', { class: 'cast-row' }, el('span', { class: 'cast-n mono', text: String(m) }), el('span', { class: 'muted small', text: 'câu giọng nam' })),
        el('div', { class: 'cast-row' }, el('span', { class: 'cast-n mono', text: String(f) }), el('span', { class: 'muted small', text: 'câu giọng nữ' })),
        v.f0 ? el('div', { class: 'cast-row' }, el('span', { class: 'cast-n mono', text: Math.round(v.f0) + ' Hz' }), el('span', { class: 'muted small', text: 'cao độ giọng gốc' })) : null);
    }
    paint();
    return {
      root: el('div', {}, el('div', { class: 'note note-plain' }, icon('info'), el('div', { text: 'Đổi giọng xong bấm Cập nhật video: chỉ những câu đổi giọng mới phải đọc lại.' })), cast, people, fl.root, trans),
      sync() { fl.sync(); paintPeople(); }, onShow: paint, onJob: paint,
    };
  }

  // ------------------------------------------------ tab Hình ảnh
  function tabPicture() {
    const fl = FieldList(['edit.blur_hardsub', 'edit.hardsub_mode'], st.vals, baseCfg(), (p) => { changed(); paintHs(); if (p === 'edit.hardsub_mode') player.reloadSources(); });
    const fl2 = FieldList(['edit.aspect', 'edit.fit', 'edit.flip', 'edit.zoom', 'edit.speed', 'edit.brightness', 'edit.contrast', 'edit.saturation', 'edit.watermark_text', 'edit.logo', 'edit.logo_pos', 'edit.logo_scale', 'edit.encoder', 'edit.crf'], st.vals, baseCfg(), changed);
    const hsBox = el('div', { class: 'hs' });
    const pickT = () => {
      const segs = st.segs;
      if (segs.length) { const s = segs[Math.min(segs.length - 1, Math.floor(segs.length * 0.3))]; return +((s.start + s.end) / 2).toFixed(2); }
      return +((meta().duration || 0) * 0.3).toFixed(2);
    };
    function paintHs() {
      const box = getBox();
      const W = meta().width || 16, H = meta().height || 9;
      const size = W >= H ? { width: '100%', aspectRatio: `${W}/${H}` } : { height: '220px', aspectRatio: `${W}/${H}` };
      const detBtn = el('button', { class: 'btn btn-sm', onclick: () => detect(detBtn) }, icon('scan'), 'Tự dò');
      const hs = st.job.hardsub;
      put(hsBox,
        el('div', { class: 'hs-mini', style: size }, el('img', { alt: 'Khung hình video', src: `/api/jobs/${enc(id)}/frame.jpg?t=${pickT()}` }),
          box ? el('div', { class: 'hs-rect', style: { left: box[0] * 100 + '%', top: box[1] * 100 + '%', width: box[2] * 100 + '%', height: box[3] * 100 + '%' } }) : null),
        el('div', { class: 'hs-info' },
          el('div', { class: 'small muted', text: box ? (hs && hs.hits != null && getPath(st.vals, 'edit.blur_hardsub') === 'auto' ? `Tự dò được: ${hs.hits}/${hs.frames} khung có chữ` : 'Vùng bạn đã chọn') : 'Chưa có vùng sub gốc' }),
          hs && hs.texts && hs.texts.length ? el('div', { class: 'hs-texts' }, hs.texts.slice(0, 4).map((t) => el('span', { class: 'hs-text', text: t, title: t }))) : null,
          el('div', { class: 'btn-row' }, el('button', { class: 'btn btn-sm', onclick: () => openPicker() }, icon('crop'), 'Chọn vùng'), detBtn)));
    }
    async function detect(btn) {
      return busy(btn, async () => {
        const r = await api('POST', `/api/jobs/${enc(id)}/detect-hardsub`);
        st.job.hardsub = r;
        markStale();      // vùng sub đổi thì video phải dựng lại
        paintHs();
        player.refreshSub();
        toast(r && r.box ? `Đã dò được vùng sub gốc (${r.hits}/${r.frames} khung có chữ)` : 'Không thấy sub chữ Hán in sẵn trong video', r && r.box ? 'success' : 'info');
        return r;
      });
    }
    function openPicker() {
      const W = meta().width || 1280, H = meta().height || 720, dur = meta().duration || 0;
      let box = getBox(); box = box ? box.slice() : null;
      let t = pickT();
      const hpx = Math.max(220, Math.min(window.innerHeight * 0.6, (900 * H) / W));
      const img = el('img', { class: 'pick-img', alt: '', draggable: 'false' });
      const spin = el('div', { class: 'pick-loading' }, el('span', { class: 'spinner lg' }));
      const handles = ['nw', 'ne', 'sw', 'se'].map((h) => el('span', { class: 'ph ph-' + h, dataset: { h } }));
      const rect = el('div', { class: 'pick-rect', hidden: true }, handles);
      const hint = el('div', { class: 'pick-hint', text: 'Kéo chuột để khoanh vùng sub tiếng Trung' });
      const layer = el('div', { class: 'pick-layer' }, rect);
      const stage = el('div', { class: 'pick-stage', style: { height: hpx + 'px', width: (hpx * W) / H + 'px' } }, img, layer, spin, hint);
      const tLabel = el('span', { class: 'mono', text: fmtTime(t) });
      const slider = el('input', { type: 'range', class: 'range', min: 0, max: Math.max(0.1, dur), step: 0.1, 'aria-label': 'Thời gian' });
      slider.value = String(t);
      const paintSlider = () => slider.style.setProperty('--p', (dur ? (t / dur) * 100 : 0) + '%');
      paintSlider();
      const loadFrame = () => { spin.hidden = false; img.src = `/api/jobs/${enc(id)}/frame.jpg?t=${t.toFixed(2)}`; };
      const loadSoon = debounce(loadFrame, 200);
      img.addEventListener('load', () => { spin.hidden = true; });
      img.addEventListener('error', () => { spin.hidden = true; toast('Không lấy được khung hình', 'error'); });
      slider.addEventListener('input', () => { t = parseFloat(slider.value); tLabel.textContent = fmtTime(t); paintSlider(); loadSoon(); });
      const jump = (dir) => {
        const mids = st.segs.map((s) => (s.start + s.end) / 2);
        const target = dir > 0 ? mids.find((m) => m > t + 0.05) : [...mids].reverse().find((m) => m < t - 0.05);
        if (target == null) return;
        t = +target.toFixed(2); slider.value = String(t); tLabel.textContent = fmtTime(t); paintSlider(); loadFrame();
      };
      const draw = () => {
        rect.hidden = !box;
        hint.hidden = !!box;
        if (!box) return;
        Object.assign(rect.style, { left: box[0] * 100 + '%', top: box[1] * 100 + '%', width: box[2] * 100 + '%', height: box[3] * 100 + '%' });
        rect.dataset.size = `${Math.round(box[2] * W)}×${Math.round(box[3] * H)} px`;
      };
      let drag = null;
      const norm = (e) => { const r = layer.getBoundingClientRect(); return [clamp((e.clientX - r.left) / r.width, 0, 1), clamp((e.clientY - r.top) / r.height, 0, 1)]; };
      layer.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        layer.setPointerCapture(e.pointerId);
        const [px, py] = norm(e);
        const h = e.target && e.target.dataset ? e.target.dataset.h : null;
        if (h && box) {
          const [x, y, w, hh] = box;
          drag = { mode: 'draw', ax: h.includes('w') ? x + w : x, ay: h.includes('n') ? y + hh : y };
        } else if (box && e.target === rect) {
          drag = { mode: 'move', ox: px - box[0], oy: py - box[1] };
        } else {
          drag = { mode: 'draw', ax: px, ay: py };
          box = [px, py, 0, 0];
        }
        draw();
      });
      layer.addEventListener('pointermove', (e) => {
        if (!drag) return;
        const [px, py] = norm(e);
        if (drag.mode === 'move') {
          const w = box[2], h = box[3];
          box = [clamp(px - drag.ox, 0, 1 - w), clamp(py - drag.oy, 0, 1 - h), w, h];
        } else {
          box = [Math.min(drag.ax, px), Math.min(drag.ay, py), Math.abs(px - drag.ax), Math.abs(py - drag.ay)];
        }
        draw();
      });
      const endDrag = () => { if (!drag) return; drag = null; if (box && (box[2] < 0.01 || box[3] < 0.005)) box = null; draw(); };
      layer.addEventListener('pointerup', endDrag);
      layer.addEventListener('pointercancel', endDrag);
      const useBtn = el('button', {
        class: 'btn btn-primary', onclick: () => {
          if (!box) { toast('Hãy kéo chọn một vùng trên khung hình', 'warn'); return; }
          setPath(st.vals, 'edit.hardsub_box', box.map((v) => Math.round(v * 1000) / 1000));
          setPath(st.vals, 'edit.blur_hardsub', true);
          changed();
          fl.sync();
          paintHs();
          m.close();
          toast('Đã lưu vùng sub gốc. Bấm Cập nhật video để áp dụng.', 'success');
        },
      }, icon('check'), 'Dùng vùng này');
      const m = openModal([
        modalHead('crop', 'Chọn vùng sub tiếng Trung', () => m),
        el('div', { class: 'modal-body' }, el('div', { class: 'pick-wrap' },
          el('p', { class: 'muted small', text: 'Kéo thanh thời gian tới khung có phụ đề, rồi kéo chuột khoanh vùng (kéo bên trong để di chuyển, kéo góc để đổi kích thước). Nên chừa rộng hơn chữ một chút.' }),
          stage,
          el('div', { class: 'pick-controls' },
            el('button', { class: 'btn btn-sm btn-icon btn-ghost', title: 'Câu trước', 'aria-label': 'Câu trước', onclick: () => jump(-1) }, icon('back')),
            slider,
            el('button', { class: 'btn btn-sm btn-icon btn-ghost', title: 'Câu sau', 'aria-label': 'Câu sau', onclick: () => jump(1) }, icon('next')),
            tLabel))),
        el('div', { class: 'modal-foot' }, el('button', { class: 'btn btn-ghost', onclick: () => m.close() }, 'Hủy'), useBtn),
      ], { cls: 'modal-wide' });
      loadFrame();
      draw();
    }
    paintHs();
    const rfBox = el('div', { class: 'rf-info' });
    function paintRfInfo() {
      const plan = player.plan;
      const fit = getPath(st.vals, 'edit.fit') || 'blur';
      const pinned = (getPath(st.vals, 'edit.reframe_pins') || []).filter((x) => !plan || !x[2] || x[2] === plan.axis).length;
      if (rfError && fit === 'track') { put(rfBox, el('div', { class: 'note' }, icon('alert'), el('div', { text: 'Không dò được khuôn mặt: ' + rfError }))); return; }
      if (rfBusy) { put(rfBox, el('div', { class: 'note note-plain' }, el('span', { class: 'spinner' }), el('div', { text: 'Đang dò khuôn mặt trong video, lần đầu mất vài giây…' }))); return; }
      if (!plan) { rfBox.replaceChildren(); return; }
      const toPreview = player.mode !== 'preview' ? el('button', { class: 'btn btn-xs', onclick: () => { player.setMode('preview'); paintRfInfo(); } }, 'Xem trước') : null;
      if (plan.isStatic) {
        put(rfBox, el('div', { class: 'note note-plain' }, icon('crop'), el('div', { text: 'Khung cắt đứng yên suốt video. Ở chế độ Xem trước có thể kéo khung trên video để chọn phần giữ lại.' }), toPreview));
        return;
      }
      const pct = Math.round(plan.face_ratio * 100);
      put(rfBox, el('div', { class: 'note' }, icon('target'), el('div', {},
        el('b', { text: `${plan.shots.length} cảnh, ${plan.moves} lần lia khung` }), el('br'),
        pct >= 40 ? `${pct}% thời lượng có mặt người. ` : `Chỉ ${pct}% thời lượng có mặt người, các cảnh còn lại máy bám theo chuyển động hoặc giữ giữa khung. `,
        'Ở chế độ Xem trước, kéo khung trên video để tự đặt cho từng cảnh.'), toPreview),
      pinned ? el('div', { class: 'btn-row rf-pins' }, el('span', { class: 'small muted', text: `${pinned} cảnh đang đặt tay` }), el('button', { class: 'btn btn-xs btn-ghost', onclick: () => { setPath(st.vals, 'edit.reframe_pins', []); editing.commitEdit(); refreshReframe(); } }, icon('undo'), 'Để máy tự chọn hết')) : null);
    }
    return {
      root: el('div', {}, el('div', { class: 'block block-first' }, el('h4', { text: 'Xóa sub gốc' }), fl.root, hsBox), el('div', { class: 'block' }, el('h4', { text: 'Khung hình & màu sắc' }), rfBox, fl2.root)),
      sync() { fl.sync(); fl2.sync(); }, onJob: paintHs, paintRf: paintRfInfo, onShow: paintRfInfo, onMode: paintRfInfo,
    };
  }

  // ------------------------------------------------ tab Âm thanh
  function tabSound() {
    const fl = FieldList(['audio.original_volume', 'audio.dub_volume', 'audio.duck', 'audio.separate', 'audio.music', 'audio.music_volume', 'audio.music_skip_intro', 'audio.loudnorm'], st.vals, baseCfg(), changed);
    return { root: fl.root, sync() { fl.sync(); } };
  }

  // ------------------------------------------------ tab Đăng bài
  function tabPublish() {
    const exportBox = el('div', { class: 'block block-first' });
    const coverBox = el('div', { class: 'block' });
    const kit = el('div', { class: 'block' });
    let coverLoaded = false;

    function paintKit() {
      const c = st.job.context || {};
      const p = c.publish;
      if (!p || !(p.title || p.caption || (p.hashtags && p.hashtags.length))) {
        put(kit, el('h4', { text: 'Tiêu đề & hashtag' }),
          el('p', { class: 'muted small', text: 'AI sẽ đọc cả video rồi viết sẵn tiêu đề, mô tả và hashtag. Cần kết nối AI (Claude hoặc API kiểu OpenAI) rồi dịch lại.' }),
          el('a', { class: 'btn btn-sm', href: '#/settings' }, icon('key'), 'Kết nối AI'));
        return;
      }
      const tags = (p.hashtags || []).map((h) => (String(h).startsWith('#') ? h : '#' + h)).join(' ');
      const item = (label, text, cls) => el('div', { class: 'pk-item' },
        el('div', { class: 'pk-head' }, el('span', { class: 'opt-label', text: label }), copyBtn(text)),
        el('div', { class: 'pk-text ' + (cls || ''), text }));
      const gl = Array.isArray(c.glossary) ? c.glossary.map((g) => [g.zh, g.vi]) : c.glossary && typeof c.glossary === 'object' ? Object.entries(c.glossary) : [];
      put(kit, el('div', { class: 'block-head' }, el('h4', { text: 'Tiêu đề & hashtag' }), copyBtn(() => [p.title, p.caption, tags].filter(Boolean).join('\n\n'), 'Chép tất cả')),
        p.title ? item('Tiêu đề', p.title) : null,
        p.caption ? item('Mô tả', p.caption, 'multi') : null,
        tags ? item('Hashtag', tags, 'tags') : null,
        c.summary || c.pronouns ? el('details', { class: 'ctx' }, el('summary', {}, icon('brain'), 'AI đã hiểu video thế nào'),
          c.summary ? el('p', { class: 'small', text: c.summary }) : null,
          c.pronouns ? el('p', { class: 'small' }, el('b', { text: 'Xưng hô: ' }), c.pronouns) : null,
          gl.length ? el('div', { class: 'gloss-chips' }, gl.slice(0, 24).map(([k, v]) => el('span', { class: 'gloss-chip' }, el('b', { text: k }), ' → ', String(v)))) : null) : null);
    }

    // --- ảnh bìa
    const coverState = { t: null, style: 'noi-bat', aspect: '', color: '#FFB224' };
    const titleInp = el('textarea', { class: 'input', rows: 2, placeholder: 'Tiêu đề thật ngắn, gây tò mò', 'aria-label': 'Chữ trên ảnh bìa' });
    const grid = el('div', { class: 'cover-grid' });
    const preview = el('div', { class: 'cover-preview', hidden: true });
    const styleSeg = el('div', { class: 'seg seg-inline' });
    [['noi-bat', 'Nổi bật'], ['dai-mau', 'Dải màu'], ['toi-gian', 'Tối giản']].forEach(([k, l]) => {
      const b = el('button', { type: 'button', class: 'seg-btn', onclick: () => { coverState.style = k; paintSeg(); } }, l);
      b.dataset.v = k;
      styleSeg.append(b);
    });
    const aspSeg = el('div', { class: 'seg seg-inline' });
    [['', 'Theo video'], ['9:16', '9:16'], ['16:9', '16:9'], ['1:1', '1:1']].forEach(([k, l]) => {
      const b = el('button', { type: 'button', class: 'seg-btn', onclick: () => { coverState.aspect = k; paintSeg(); } }, l);
      b.dataset.v = k;
      aspSeg.append(b);
    });
    const colorInp = el('input', { type: 'color', class: 'color-input', value: '#ffb224', 'aria-label': 'Màu nhấn của ảnh bìa', oninput: () => { coverState.color = colorInp.value.toUpperCase(); } });
    function paintSeg() {
      [...styleSeg.children].forEach((b) => b.classList.toggle('active', b.dataset.v === coverState.style));
      [...aspSeg.children].forEach((b) => b.classList.toggle('active', b.dataset.v === coverState.aspect));
    }
    const makeBtn = el('button', {
      class: 'btn btn-sm btn-primary', onclick: () => busy(makeBtn, async () => {
        if (coverState.t == null) { toast('Hãy chọn một khung hình', 'warn'); return; }
        const r = await api('POST', `/api/jobs/${enc(id)}/cover`, { t: coverState.t, title: titleInp.value, style: coverState.style, aspect: coverState.aspect, color: coverState.color });
        st.job.files.cover = true;
        showCover(r.url);
        refreshQa();
        toast('Đã tạo ảnh bìa', 'success');
      }),
    }, icon('wand'), 'Tạo ảnh bìa');
    function showCover(u) {
      preview.hidden = false;
      put(preview, el('img', { alt: 'Ảnh bìa', src: u }),
        el('div', { class: 'btn-row' },
          el('a', { class: 'btn btn-sm', href: `#/thumb/job/${enc(id)}`, title: 'Thiết kế thumbnail: chữ lớn, mũi tên, emoji, mẫu dựng sẵn, AI gợi ý chữ' }, icon('edit'), 'Sửa trong Thumbnail'),
          el('a', { class: 'btn btn-sm', href: u, download: 'cover.jpg' }, icon('download'), 'Tải ảnh bìa')));
    }
    function paintCover() {
      put(coverBox, el('h4', { text: 'Ảnh bìa' }),
        el('p', { class: 'muted small', text: 'Studio566 chấm điểm khung hình (nét, đủ sáng, có người) rồi gợi ý các khung đẹp nhất. Sub gốc được xóa tự động.' }),
        grid, el('div', { class: 'opt-row' }, el('div', { class: 'opt-label', text: 'Chữ trên ảnh' }), titleInp),
        el('div', { class: 'opt-row' }, el('div', { class: 'opt-label', text: 'Kiểu' }), styleSeg),
        el('div', { class: 'opt-row' }, el('div', { class: 'opt-label', text: 'Khung' }), aspSeg),
        el('div', { class: 'opt-row' }, el('div', { class: 'opt-inline' }, el('div', { class: 'opt-label', text: 'Màu nhấn' }), el('label', { class: 'color-pick' }, colorInp))),
        el('div', { class: 'btn-row' }, makeBtn,
          el('a', { class: 'btn btn-sm', href: `#/thumb/job/${enc(id)}`, title: 'Mở trang Thumbnail: nền là khung hình đẹp nhất, sub gốc đã xóa' }, icon('image'), 'Tự thiết kế')), preview);
      paintSeg();
    }
    async function loadCover() {
      if (coverLoaded) return;
      coverLoaded = true;
      grid.replaceChildren(...[0, 1, 2, 3, 4, 5].map(() => el('div', { class: 'skel cover-skel' })));
      const c = st.job.context && st.job.context.publish;
      try {
        const r = await api('GET', `/api/jobs/${enc(id)}/cover/candidates`);
        const cc = r.current || st.job.cover;
        coverState.t = cc ? cc.t : (r.items[0] && r.items[0].t);
        if (cc) { titleInp.value = cc.title || ''; coverState.style = cc.style || coverState.style; coverState.color = cc.color || coverState.color; colorInp.value = coverState.color.toLowerCase(); paintSeg(); }
        else if (c && c.title) titleInp.value = c.title;
        const paintGrid = () => grid.replaceChildren(...r.items.map((x) => el('button', {
          type: 'button', class: 'cover-cand' + (x.t === coverState.t ? ' active' : ''), title: `Khung ở ${fmtTime(x.t, 0)}`,
          onclick: () => { coverState.t = x.t; paintGrid(); },
        }, el('img', { alt: '', loading: 'lazy', src: `/api/jobs/${enc(id)}/frame.jpg?t=${x.t.toFixed(2)}` }))));
        paintGrid();
        if (hasFile('cover')) showCover(`/api/jobs/${enc(id)}/cover.jpg?v=${Date.now()}`);
      } catch (e) { grid.replaceChildren(el('p', { class: 'muted small', text: 'Không lấy được khung hình: ' + e.message })); coverLoaded = false; }
    }

    // --- xuất
    const chosen = new Set();
    const expBtn = el('button', {
      class: 'btn btn-primary', onclick: () => {
        // chưa chọn nền tảng mà video đã mới nhất thì không có gì phải làm, không dựng lại và không làm mất các bản đã xuất
        if (!chosen.size && hasFile('final') && !st.job.stale && !st.dirty && st.job.output) { toast('Bản chính chưa có gì thay đổi. Chọn thêm nền tảng, hoặc bấm Cập nhật video nếu muốn dựng lại.', 'info'); return; }
        busy(expBtn, async () => { await startExport([], [], [...chosen]); toast('Đã xếp hàng xuất video', 'info', { timeout: 2200 }); }).then(() => paintExport());     // busy bật lại nút nên phải vẽ lại theo trạng thái thật
      },
    }, icon('export'), 'Xuất video');
    const bundleBtn = el('button', {
      class: 'btn', title: 'Gom video, ảnh bìa, phụ đề, tiêu đề và mô tả vào một thư mục', onclick: () => busy(bundleBtn, async () => {
        if (st.job.stale || st.dirty) { toast('Video đã xuất chưa có các thay đổi mới nhất. Bấm Cập nhật video trước khi tạo gói.', 'warn'); return; }
        const r = await api('POST', `/api/jobs/${enc(id)}/bundle`, { open: true });
        toast(`Đã tạo gói đăng bài gồm ${r.files.length} file`, 'success');
      }),
    }, icon('package'), 'Tạo gói đăng bài');
    // các bản gửi về từ trình dựng: gửi lúc nào cũng được, nên hỏi lại khi quay về cửa sổ này
    let edited = st.job.edited || [];
    async function refreshEdited() {
      try {
        const r = await api('GET', `/api/jobs/${enc(id)}/edited`);
        if (JSON.stringify(r.items) !== JSON.stringify(edited)) { edited = r.items; st.job.edited = r.items; paintExport(); }
      } catch (_) { /* mất kết nối thì giữ danh sách cũ */ }
    }
    window.addEventListener('focus', refreshEdited);
    st.cleanups = (st.cleanups || []).concat(() => window.removeEventListener('focus', refreshEdited));
    function editedBlock() {
      if (!edited.length) return null;
      const size = (b) => (b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : Math.max(1, Math.round(b / 1e6)) + ' MB').replace('.', ',');
      return el('div', { class: 'edited' },
        el('h4', { text: 'Bản từ trình dựng' }),
        edited.map((x, i) => {
          const qcBtn = el('button', {
            class: 'btn btn-xs btn-ghost', title: 'Đo màn hình đen, đứng hình, đoạn câm, độ to, vỡ tiếng, chữ Trung còn sót', onclick: () => busy(qcBtn, async () => {
              const { qc } = await api('POST', `/api/jobs/${enc(id)}/edited/${enc(x.name)}/qc`);
              const need = qc.checks.filter((c) => c.level === 'bad' || c.level === 'warn');
              toast(`Điểm ${qc.score}/100` + (need.length ? `. Cần xem: ${need.map((c) => c.title).join('; ')}` : '. Mọi phép đo đều đạt'), qc.score >= 85 ? 'success' : 'warn', { timeout: 9000 });
            }),
          }, icon('gauge'), 'Kiểm định');
          return el('div', { class: 'edited-row' + (i ? '' : ' latest') },
            el('span', { class: 'edited-t mono', title: x.path, text: x.name }),
            el('span', { class: 'dim small', text: size(x.size) }),
            el('span', { class: 'edited-acts' },
              el('button', { class: 'btn btn-xs btn-ghost', onclick: () => videoModal(`/api/jobs/${enc(id)}/edited/${enc(x.name)}?t=${Math.round(x.at)}`, x.name) }, icon('play'), 'Xem'),
              qcBtn,
              el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Mở thư mục', 'aria-label': 'Mở thư mục', onclick: () => api('POST', `/api/jobs/${enc(id)}/edited/${enc(x.name)}/reveal`) }, icon('folder'))));
        }),
        el('p', { class: 'dim small', text: 'Tạo gói đăng bài sẽ kèm bản mới nhất (video_da_dung) nếu bản đó gửi về sau lần cập nhật video gần nhất. Điểm kiểm định trong gói là của bản chính.' }));
    }
    function paintExport() {
      const main = getPath(st.vals, 'edit.aspect') || 'keep';
      const m = meta();
      const mainLabel = main === 'keep' ? `khung gốc ${m.width || ''}×${m.height || ''}` : `khung ${main}`;
      const outs = st.job.output ? [st.job.output, ...(st.job.extra || [])] : [];
      expBtn.disabled = st.runActive;
      const profiles = S.profiles || [];
      const picked = profiles.filter((p) => chosen.has(p.id));
      const renders = new Set(picked.map((p) => `${p.aspect}|${p.fit}`));
      const mainFit = getPath(st.vals, 'edit.fit') || 'blur';
      if (main !== 'keep') renders.delete(`${main}|${mainFit}`);
      const dur = m.duration || 0;
      expBtn.replaceChildren(icon('export'), chosen.size ? `Xuất ${chosen.size} nền tảng` : 'Xuất video');
      put(exportBox, el('h4', { text: 'Xuất theo nền tảng' }),
        el('p', { class: 'muted small', text: `Luôn có bản chính (${mainLabel}). Chọn thêm nền tảng muốn đăng. Nền tảng cùng khung hình dùng chung một lần dựng, giọng lồng và bản xóa sub được dùng lại nên rất nhanh.` }),
        el('div', { class: 'targets' }, profiles.map((p) => el('button', {
          type: 'button', class: 'target' + (chosen.has(p.id) ? ' active' : ''),
          onclick: () => { if (chosen.has(p.id)) chosen.delete(p.id); else chosen.add(p.id); paintExport(); },
        }, icon(p.icon), el('span', { class: 'target-t' }, el('b', { text: p.name }), el('span', { class: 'dim small', text: p.note }),
          p.max_seconds && dur > p.max_seconds ? el('span', { class: 'target-warn small', text: p.over }) : null), el('span', { class: 'target-check' }, icon('check'))))),
        picked.length ? el('p', { class: 'dim small target-sum', text: renders.size ? `Dựng thêm ${renders.size} lần cho ${picked.length} nền tảng` : `Dùng lại bản chính cho ${picked.length} nền tảng, không phải dựng thêm` }) : null,
        el('div', { class: 'btn-row' }, expBtn, hasFile('final') ? bundleBtn : null,
          hasFile('final') ? el('a', { class: 'btn btn-ghost', href: `/api/jobs/${enc(id)}/media/final.mp4?t=${player.bust}`, download: '' }, icon('download'), 'Tải về') : null,
          el('button', { class: 'btn btn-ghost', onclick: () => reveal(id) }, icon('folder'), 'Thư mục')),
        outs.length ? el('div', { class: 'outs' }, outs.map((o) => el('div', { class: 'out-row mono', title: o, text: o.split(/[\\/]/).pop() }))) : null,
        editedBlock());
    }
    paintCover();
    return {
      root: el('div', {}, exportBox, coverBox, kit),
      onShow() { paintKit(); paintExport(); loadCover(); refreshEdited(); },
      onJob() { edited = st.job.edited || edited; paintKit(); paintExport(); },
      onRun() { paintExport(); },
    };
  }

  // ------------------------------------------------ tab Kiểm tra
  function tabQa() {
    const box = el('div', { class: 'qa' });
    const qcBox = el('div', { class: 'block block-first qc' });
    const LV = { bad: 'alert', warn: 'alert', info: 'info', ok: 'check' };
    const fmtSize = (b) => (b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : Math.round(b / 1e6) + ' MB').replace('.', ',');
    const fmtN = (v) => (v == null ? '–' : v.toFixed(1).replace('.', ','));
    function paintQc() {
      const q = st.job.qc;
      const runBtn = el('button', {
        class: 'btn btn-xs', disabled: st.runActive || !hasFile('final'), onclick: () => busy(runBtn, async () => {
          const r = await api('POST', `/api/jobs/${enc(id)}/qc`);
          st.job.qc = r.qc;
          paintQc();
          refreshQa();
          toast(`Điểm thành phẩm ${r.qc.score}/100`, r.qc.score >= 85 ? 'success' : 'info', { timeout: 2200 });
        }),
      }, icon('gauge'), q ? 'Kiểm định lại' : 'Kiểm định');
      const head = el('div', { class: 'block-head' }, el('h4', { text: 'Kiểm định thành phẩm' }), runBtn);
      if (!hasFile('final')) { put(qcBox, head, el('p', { class: 'muted small', text: 'Chưa có video thành phẩm. Bấm Cập nhật video, xong sẽ tự kiểm định.' })); return; }
      if (!q) { put(qcBox, head, el('p', { class: 'muted small', text: 'Đo trên chính file video đã xuất: màn hình đen, đứng hình, đoạn câm, độ to, vỡ tiếng, phụ đề che mặt, còn sót chữ Trung.' })); return; }
      const cls = q.score >= 85 ? 'ok' : q.score >= 60 ? 'warn' : 'bad';
      const need = q.checks.filter((c) => c.level !== 'ok');
      const good = q.checks.filter((c) => c.level === 'ok');
      const s = q.stats || {};
      put(qcBox, head,
        q.fresh === false ? el('div', { class: 'note' }, icon('alert'), el('div', { text: 'Video đã được dựng lại sau lần kiểm định này. Bấm Kiểm định lại để có số liệu mới.' })) : null,
        el('div', { class: 'qa-top ' + cls },
          el('div', { class: 'qa-ring', style: { '--p': q.score } }, el('span', { class: 'mono', text: String(q.score) })),
          el('div', {}, el('b', { text: q.score >= 85 ? 'Đạt chuẩn đăng' : q.score >= 60 ? 'Nên xem lại vài chỗ' : 'Cần sửa trước khi đăng' }),
            el('div', { class: 'muted small', text: need.length ? `${need.length} mục cần chú ý` : 'Mọi phép đo đều đạt' }))),
        el('div', { class: 'qc-stats' },
          el('div', {}, el('b', { class: 'mono', text: fmtN(s.lufs) }), el('span', { class: 'dim small', text: 'LUFS' })),
          el('div', {}, el('b', { class: 'mono', text: fmtN(s.peak) }), el('span', { class: 'dim small', text: 'đỉnh dB' })),
          el('div', {}, el('b', { class: 'mono', text: fmtTime(s.duration || 0, 0) }), el('span', { class: 'dim small', text: 'độ dài' })),
          el('div', {}, el('b', { class: 'mono', text: s.size ? fmtSize(s.size) : '–' }), el('span', { class: 'dim small', text: 'cỡ file' }))),
        need.map((c) => el('div', { class: 'qa-item qc-' + c.level },
          el('div', { class: 'qa-title' }, icon(LV[c.level]), el('b', { text: c.title })),
          c.detail ? el('div', { class: 'muted small', text: c.detail }) : null,
          c.at.length ? el('div', { class: 'qa-lines' }, c.at.slice(0, 16).map((t) => el('button', { class: 'qa-line mono', title: 'Xem chỗ này trên bản đã dựng', onclick: () => player.seekFinal(t) }, fmtTime(t, 0))),
            c.at.length > 16 ? el('span', { class: 'dim small', text: `+${c.at.length - 16}` }) : null) : null)),
        good.length ? el('details', { class: 'qa-passed' }, el('summary', {}, icon('check'), `${good.length} phép đo đạt`), good.map((c) => el('div', { class: 'small muted', text: c.title }))) : null);
    }
    function paint(q) {
      q = q || st.qa;
      if (!q) return;
      const cls = q.score >= 85 ? 'ok' : q.score >= 60 ? 'warn' : 'bad';
      const verdict = q.score >= 85 ? 'Sẵn sàng đăng' : q.score >= 60 ? 'Nên xem lại vài chỗ' : 'Cần sửa trước khi đăng';
      put(box,
        el('div', { class: 'qa-top ' + cls },
          el('div', { class: 'qa-ring', style: { '--p': q.score } }, el('span', { class: 'mono', text: String(q.score) })),
          el('div', {}, el('b', { text: verdict }), el('div', { class: 'muted small', text: q.issues.length ? `${q.issues.length} mục cần chú ý` : 'Không có vấn đề nào' }))),
        q.issues.map((it) => el('div', { class: 'qa-item sev-' + it.sev },
          el('div', { class: 'qa-title' }, icon(it.sev === 'info' ? 'info' : 'alert'), el('b', { text: it.title })),
          el('div', { class: 'muted small', text: it.hint }),
          it.lines.length ? el('div', { class: 'qa-lines' }, it.lines.slice(0, 24).map((i) => el('button', { class: 'qa-line mono', title: `Đến câu ${i + 1}`, onclick: () => focusLine(i) }, String(i + 1))),
            it.lines.length > 24 ? el('span', { class: 'dim small', text: `+${it.lines.length - 24}` }) : null) : null)),
        q.passed.length ? el('details', { class: 'qa-passed' }, el('summary', {}, icon('check'), `${q.passed.length} mục đã đạt`), q.passed.map((p) => el('div', { class: 'small muted', text: p }))) : null);
    }
    paint();
    paintQc();
    return {
      root: el('div', {}, qcBox, el('div', { class: 'block' }, el('h4', { text: 'Kiểm tra nội dung' }), box)),
      onQa: paint, onShow: () => { paint(); paintQc(); }, onJob: paintQc, onRun: paintQc,
    };
  }

  const BUILD = { subs: tabSubs, edit: tabEdit, voice: tabVoice, picture: tabPicture, sound: tabSound, publish: tabPublish, qa: tabQa };
  const each = (fn) => Object.values(built).forEach((b) => { if (b && b[fn]) b[fn](); });
  const api_ = {
    root, open, setOption, refreshReframe,
    onJob() { refreshReframe(); each('onJob'); if (!built[cur]) open(cur); else if (built[cur].onShow) built[cur].onShow(); },
    onPlayerMode() { each('onMode'); },
    onRun() { each('onRun'); },
    /** vẽ lại tab Dựng khi đổi lựa chọn. soft: đang kéo, không vẽ lại ô nhập */
    onEdit(soft) { if (built.edit && !soft && cur === 'edit') built.edit.onEdit(); },
    /** đoạn cắt hoặc lớp phủ vừa đổi: lưu vào options của video */
    editChanged(soft) { changed(); if (!soft && built.edit && cur === 'edit') built.edit.onEdit(); },
    /** ghi ngay tùy chọn đang chờ và đợi ghi xong: phải gọi trước khi chạy dựng video */
    async flush() { persist.flush(); await saving; },
    onQa(q) { if (built.qa) built.qa.onQa(q); },
  };
  return api_;
}
