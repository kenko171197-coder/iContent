/* Trang Thư viện: mọi thứ đã làm (video dịch, câu chuyện, quy trình, video ghép, giọng đọc), dung lượng từng món, xóa nhiều món một lần,
   và dọn file tạm an toàn (chỉ thứ tự tạo lại được). */
import {
  S, api, busy, el, emptyState, enc, errorState, fmtAgo, fmtDur, fmtSize, icon, openModal, modalHead, playUrl, popMenu, queueListeners,
  reveal, toast, videoModal,
} from './core.js';

const KINDS = [
  ['all', 'Tất cả'], ['job', 'Video dịch'], ['story', 'Kể chuyện'], ['flow', 'Quy trình'], ['merge', 'Video ghép'], ['speech', 'Giọng đọc'],
];
const KIND = { job: ['Video dịch', 'globe'], story: ['Kể chuyện', 'film'], flow: ['Quy trình', 'layers'], merge: ['Video ghép', 'merge'], speech: ['Giọng đọc', 'mic'] };
const FLOW_ICON = { idea: 'spark', script: 'file', images: 'image', ai_write: 'brain', split: 'scissors', char_refs: 'wand', draw: 'image', voice: 'mic', music: 'music',
  render: 'film', thumbnail: 'square', editor: 'scissors', export: 'package' };
const PART_COLOR = { jobs: 'var(--amber)', stories: '#c58cff', flows: '#4fd1c5', output: 'var(--ok)', other: 'var(--tx3)', models: 'var(--info)' };
const SORTS = [['new', 'Mới nhất'], ['old', 'Cũ nhất'], ['size', 'Nặng nhất'], ['name', 'Tên A-Z']];
const strip = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D').toLowerCase();
const keyOf = (x) => `${x.kind}:${x.id}`;

export async function viewLibrary(main, alive) {
  main.classList.add('view-pad');
  let items = null, counts = {}, store = null;
  let kind = sessionStorage.getItem('ic.lib.kind') || 'all';
  let sort = sessionStorage.getItem('ic.lib.sort') || 'new';
  let selecting = false;
  const picked = new Set();

  const search = el('input', { class: 'input', placeholder: 'Tìm theo tên…', 'aria-label': 'Tìm theo tên', oninput: () => paint() });
  const tabs = el('div', { class: 'seg lb-tabs', role: 'tablist' });
  const sortSel = el('select', { class: 'input lb-sort', 'aria-label': 'Sắp xếp', onchange: () => { sort = sortSel.value; sessionStorage.setItem('ic.lib.sort', sort); paint(); } },
    SORTS.map(([v, l]) => el('option', { value: v, text: l, selected: v === sort })));
  const pickBtn = el('button', { class: 'btn btn-sm', onclick: () => { selecting = !selecting; if (!selecting) picked.clear(); paint(); } });
  const selBar = el('div', { class: 'lb-selbar', hidden: true });
  const grid = el('div', { class: 'lb-grid' });
  const storeBox = el('section', { class: 'lb-store' }, el('div', { class: 'skel', style: { height: '64px' } }));

  main.append(
    el('div', { class: 'page-head' },
      el('div', { class: 'page-head-text' }, el('div', { class: 'eyebrow', text: 'Thư viện' }), el('h1', { text: 'Mọi thứ bạn đã làm' })),
      el('div', { class: 'actions' }, el('div', { class: 'search-box' }, icon('search'), search))),
    storeBox,
    el('div', { class: 'lb-bar' }, tabs, el('span', { class: 'grow' }), sortSel, pickBtn),
    selBar, grid);
  for (let i = 0; i < 8; i++) grid.append(el('div', { class: 'skel', style: { height: '230px' } }));

  // ---------------------------------------------------------------- dung lượng
  function paintStore() {
    if (!store) return;
    const parts = (store.parts || []).filter((p) => p.bytes > 0);
    const used = parts.reduce((n, p) => n + p.bytes, 0);
    const can = (store.cleanable || []).reduce((n, g) => n + g.bytes, 0);
    const disk = store.disk;
    const bar = el('div', { class: 'lb-bar-used', role: 'img', 'aria-label': `Đang dùng ${fmtSize(used)}` },
      parts.map((p) => el('i', { title: `${p.label}: ${fmtSize(p.bytes)}`, style: { flexGrow: String(Math.max(p.bytes / Math.max(used, 1), 0.012)), background: PART_COLOR[p.id] || 'var(--tx3)' } })));
    const cleanBtn = el('button', { class: 'btn btn-sm' + (can > 5e6 ? ' btn-primary' : ''), disabled: can <= 0, onclick: () => openCleanup() }, icon('wand'), can > 0 ? `Dọn ${fmtSize(can)}` : 'Đã gọn gàng');
    storeBox.replaceChildren(
      el('div', { class: 'lb-store-main' },
        el('div', { class: 'lb-store-h' },
          el('b', { class: 'lb-used num', text: fmtSize(used) }), el('span', { class: 'dim small', text: 'Studio566 đang dùng' }),
          el('span', { class: 'grow' }),
          disk ? el('span', { class: 'small ' + (disk.free < 15e9 ? 'warn-text' : 'dim'), text: `Ổ ${disk.path.replace(/\\$/, '')} còn trống ${fmtSize(disk.free)}` }) : ''),
        bar,
        el('div', { class: 'lb-legend' }, parts.map((p) => el('span', { class: 'small' }, el('i', { style: { background: PART_COLOR[p.id] || 'var(--tx3)' } }), `${p.label} `, el('b', { class: 'num', text: fmtSize(p.bytes) }))))),
      el('div', { class: 'lb-store-act' },
        el('span', { class: 'small dim', text: can > 0 ? 'Dọn được an toàn, không mất video nào' : 'Không có file tạm nào cần dọn' }),
        cleanBtn));
  }
  async function loadStore() {
    try {
      store = await api('GET', '/api/library/storage');
      if (alive()) paintStore();
    } catch (e) { if (alive()) storeBox.replaceChildren(el('span', { class: 'small dim', text: 'Chưa tính được dung lượng: ' + e.message })); }
  }

  function openCleanup() {
    const groups = (store.cleanable || []).filter((g) => g.bytes > 0);
    const chosen = new Set(groups.map((g) => g.id));
    const total = el('b', { class: 'num' });
    const go = el('button', { class: 'btn btn-primary' }, icon('wand'), 'Dọn ngay');
    const upd = () => {
      const n = groups.filter((g) => chosen.has(g.id)).reduce((a, g) => a + g.bytes, 0);
      total.textContent = fmtSize(n);
      go.disabled = !n;
    };
    const m = openModal([
      modalHead('wand', 'Dọn dung lượng', () => m),
      el('div', { class: 'modal-body lb-clean' },
        el('p', { class: 'muted small', text: 'Chỉ xóa những thứ Studio566 tự tạo lại được. Video gốc, video đã xuất, phụ đề, bản dịch, câu chuyện, ảnh đều giữ nguyên.' }),
        groups.map((g) => el('label', { class: 'lb-group' },
          el('input', { type: 'checkbox', checked: true, onchange: (e) => { if (e.target.checked) chosen.add(g.id); else chosen.delete(g.id); upd(); } }),
          el('span', { class: 'lb-group-t' }, el('b', { text: g.label }), el('span', { class: 'small dim', text: g.detail })),
          el('span', { class: 'num small', text: fmtSize(g.bytes) })))),
      el('div', { class: 'modal-foot' }, el('span', { class: 'small dim' }, 'Giải phóng ', total), el('span', { class: 'grow' }),
        el('button', { class: 'btn btn-ghost', onclick: () => m.close() }, 'Hủy'), go),
    ], { cls: 'modal-sm' });
    upd();
    go.addEventListener('click', () => busy(go, async () => {
      const r = await api('POST', '/api/library/cleanup', { groups: [...chosen] });
      m.close();
      toast(`Đã giải phóng ${fmtSize(r.freed)}` + (r.failed ? `. ${r.failed} mục đang được mở nên chưa xóa, thử lại sau.` : ''), r.failed ? 'info' : 'success');
      await Promise.all([loadStore(), load()]);
    }));
  }

  // ---------------------------------------------------------------- danh sách
  async function load() {
    try {
      const r = await api('GET', '/api/library');
      if (!alive()) return;
      items = r.items || [];
      counts = r.counts || {};
      for (const k of [...picked]) if (!items.some((x) => keyOf(x) === k)) picked.delete(k);
      paint();
    } catch (e) {
      if (alive()) grid.replaceChildren(errorState(e.message, () => load()));
    }
  }

  function shown() {
    const q = strip(search.value.trim());
    const list = items.filter((x) => (kind === 'all' || x.kind === kind) && (!q || strip(`${x.title} ${x.original || ''} ${x.id}`).includes(q)));
    const by = {
      new: (a, b) => (b.updated || 0) - (a.updated || 0),
      old: (a, b) => (a.updated || 0) - (b.updated || 0),
      size: (a, b) => ((b.size || 0) + (b.out_size || 0)) - ((a.size || 0) + (a.out_size || 0)),
      name: (a, b) => String(a.title || '').localeCompare(String(b.title || ''), 'vi'),
    }[sort];
    return list.sort(by);
  }

  function paint() {
    if (!items) return;
    tabs.replaceChildren(...KINDS.filter(([k]) => k === 'all' || counts[k] || kind === k).map(([k, l]) => el('button', {
      type: 'button', role: 'tab', class: 'seg-btn' + (kind === k ? ' active' : ''), 'aria-selected': kind === k ? 'true' : 'false',
      onclick: () => { kind = k; sessionStorage.setItem('ic.lib.kind', k); paint(); },
    }, l, k === 'all' ? el('span', { class: 'lb-n', text: String(items.length) }) : el('span', { class: 'lb-n', text: String(counts[k] || 0) }))));
    pickBtn.replaceChildren(icon(selecting ? 'x' : 'check'), selecting ? 'Xong' : 'Chọn nhiều');
    paintSel();
    if (!items.length) {
      grid.replaceChildren(emptyState('Thư viện còn trống', 'Mọi video, câu chuyện, giọng đọc bạn làm sẽ nằm ở đây.',
        el('a', { class: 'btn btn-primary', href: '#/home' }, icon('home'), 'Chọn việc để bắt đầu'), 'boxed'));
      grid.classList.add('lb-empty');
      return;
    }
    const list = shown();
    grid.classList.toggle('lb-empty', !list.length);
    if (!list.length) {
      grid.replaceChildren(emptyState('Không tìm thấy', search.value.trim() ? `Không có mục nào khớp "${search.value.trim()}".` : 'Mục này chưa có gì.'));
      return;
    }
    grid.replaceChildren(...list.map(card));
  }

  function paintSel() {
    const sel = items.filter((x) => picked.has(keyOf(x)));
    selBar.hidden = !selecting;
    if (!selecting) return;
    const list = shown();
    const all = list.length && list.every((x) => picked.has(keyOf(x)));
    const size = sel.reduce((n, x) => n + (x.size || 0), 0);
    selBar.replaceChildren(
      el('button', { class: 'btn btn-sm btn-ghost', onclick: () => { if (all) list.forEach((x) => picked.delete(keyOf(x))); else list.forEach((x) => { if (!x.busy) picked.add(keyOf(x)); }); paint(); } },
        icon(all ? 'minus' : 'check'), all ? 'Bỏ chọn tất cả' : 'Chọn tất cả đang hiện'),
      el('span', { class: 'small', text: sel.length ? `Đã chọn ${sel.length} mục · ${fmtSize(size)}` : 'Bấm vào từng mục để chọn' }),
      el('span', { class: 'grow' }),
      el('button', { class: 'btn btn-sm btn-danger', disabled: !sel.length, onclick: () => askDelete(sel) }, icon('trash'), 'Xóa đã chọn'));
  }

  function menuFor(x) {
    const out = [];
    if (x.kind === 'job') out.push({ icon: 'sliders', label: 'Mở Studio', onClick: () => { location.hash = x.href; } });
    if (x.kind === 'story') out.push({ icon: 'film', label: 'Mở câu chuyện', onClick: () => { location.hash = x.href; } });
    if (x.kind === 'flow') out.push({ icon: 'layers', label: 'Mở quy trình', onClick: () => { location.hash = x.href; } });
    if (x.video) out.push({ icon: 'play', label: 'Xem video', onClick: () => videoModal(`${x.video}${x.video.includes('?') ? '&' : '?'}t=${Date.now()}`, x.title) });
    if (x.audio) out.push({ icon: 'play', label: 'Nghe', onClick: () => playUrl(x.audio) });
    if (x.thumb_href) out.push({ icon: 'square', label: 'Làm thumbnail', onClick: () => { location.hash = x.thumb_href; } });
    if (x.kind === 'job') out.push({ icon: 'folder', label: 'Mở thư mục', onClick: () => reveal(x.id) });
    if (x.kind === 'story') out.push({ icon: 'folder', label: 'Mở thư mục', onClick: () => api('POST', `/api/stories/${enc(x.id)}/reveal`).catch((e) => toast(e.message, 'error')) });
    if (x.kind === 'speech') out.push({ icon: 'folder', label: 'Mở thư mục giọng đọc', onClick: () => api('POST', '/api/speech/reveal').catch((e) => toast(e.message, 'error')) });
    if (x.kind === 'merge') out.push({ icon: 'merge', label: 'Trang Ghép video', onClick: () => { location.hash = '#/merge'; } });
    out.push(x.busy ? null : { icon: 'trash', label: 'Xóa', danger: true, onClick: () => askDelete([x]) });
    return out;
  }

  function card(x) {
    const [kl, ki] = KIND[x.kind] || ['', 'file'];
    const k = keyOf(x);
    const on = picked.has(k);
    const media = x.thumb ? el('img', { src: x.thumb, alt: '', loading: 'lazy', onerror: (e) => e.target.remove() })
      : x.types && x.types.length ? el('div', { class: 'hm-chain' }, x.types.slice(0, 9).map((t) => el('span', {}, icon(FLOW_ICON[t] || 'square'))))
        : el('span', { class: 'lb-ph' }, icon(ki));
    const play = x.video || x.audio ? el('button', {
      class: 'btn btn-xs btn-icon lb-play', title: x.video ? 'Xem video' : 'Nghe', 'aria-label': x.video ? 'Xem video' : 'Nghe',
      onclick: (e) => { e.stopPropagation(); if (x.video) videoModal(`${x.video}${x.video.includes('?') ? '&' : '?'}t=${Date.now()}`, x.title); else playUrl(x.audio, e.currentTarget); },
    }, icon('play')) : '';
    const menuBtn = el('button', {
      class: 'btn btn-xs btn-icon btn-ghost', title: 'Thêm', 'aria-label': 'Thêm',
      onclick: (e) => { e.stopPropagation(); popMenu(menuBtn, menuFor(x)); },
    }, icon('more'));
    const open = () => {
      if (selecting) {
        if (x.busy) { toast('Mục này đang chạy, chưa xóa được', 'info'); return; }
        if (on) picked.delete(k); else picked.add(k);
        paint();
        return;
      }
      if (x.kind === 'merge' && x.video) videoModal(x.video, x.title); else location.hash = x.href;
    };
    const size = (x.size || 0) + (x.out_size || 0);
    return el('div', {
      class: 'lb-card' + (on ? ' picked' : '') + (selecting ? ' selecting' : ''), tabindex: '0', role: selecting ? 'checkbox' : 'link',
      'aria-checked': selecting ? String(on) : undefined, 'aria-label': x.title, onclick: open,
      onkeydown: (e) => { if (e.key === 'Enter' || (selecting && e.key === ' ')) { e.preventDefault(); open(); } },
    },
    el('div', { class: 'lb-thumb' }, media,
      el('span', { class: 'hm-kind' }, icon(ki), kl),
      selecting ? el('span', { class: 'lb-check' + (on ? ' on' : '') }, on ? icon('check') : '') : '',
      x.duration ? el('span', { class: 'jc-dur mono', text: fmtDur(x.duration) }) : '',
      play),
    el('div', { class: 'lb-body' },
      el('div', { class: 'jc-title', text: x.title || kl, title: x.original && x.original !== x.title ? x.original : x.title }),
      el('div', { class: 'lb-meta' },
        el('span', { class: 'jc-status ' + (x.busy ? 'busy' : x.done ? 'done' : 'draft'), text: x.status }),
        el('span', { class: 'dim', text: fmtAgo(x.updated) })),
      el('div', { class: 'lb-meta' },
        el('span', { class: 'num dim', title: x.out_size ? `Thư mục làm việc ${fmtSize(x.size)}, video đã xuất ${fmtSize(x.out_size)}` : '', text: size ? fmtSize(size) : '' }),
        el('span', { class: 'grow' }), selecting ? '' : menuBtn)));
  }

  // ---------------------------------------------------------------- xóa
  function askDelete(list) {
    const outs = list.reduce((n, x) => n + (x.out_size || 0), 0);
    const work = list.reduce((n, x) => n + (x.size || 0), 0);
    let withOut = false;
    const freed = el('b', { class: 'num', text: fmtSize(work) });
    const ok = el('button', { class: 'btn btn-danger' }, icon('trash'), list.length > 1 ? `Xóa ${list.length} mục` : 'Xóa');
    const names = list.slice(0, 5).map((x) => el('li', { text: x.title || x.id }));
    if (list.length > 5) names.push(el('li', { class: 'dim', text: `và ${list.length - 5} mục khác` }));
    const m = openModal([
      modalHead('trash', list.length > 1 ? `Xóa ${list.length} mục?` : 'Xóa mục này?', () => m),
      el('div', { class: 'modal-body' },
        el('ul', { class: 'lb-names' }, names),
        el('p', { class: 'muted small', text: 'Xóa khỏi thư viện cùng mọi file làm việc (giọng lồng, ảnh, bản dựng). Không hoàn tác được.' }),
        outs ? el('label', { class: 'lb-group' },
          el('input', { type: 'checkbox', onchange: (e) => { withOut = e.target.checked; freed.textContent = fmtSize(work + (withOut ? outs : 0)); } }),
          el('span', { class: 'lb-group-t' }, el('b', { text: 'Xóa luôn video đã xuất' }),
            el('span', { class: 'small dim', text: 'Mặc định giữ lại video, phụ đề, ảnh bìa trong thư mục output để vẫn đăng được.' })),
          el('span', { class: 'num small', text: fmtSize(outs) })) : ''),
      el('div', { class: 'modal-foot' }, el('span', { class: 'small dim' }, 'Giải phóng ', freed), el('span', { class: 'grow' }),
        el('button', { class: 'btn btn-ghost', onclick: () => m.close() }, 'Hủy'), ok),
    ], { cls: 'modal-sm' });
    setTimeout(() => ok.focus(), 60);
    ok.addEventListener('click', () => busy(ok, async () => {
      const r = await api('POST', '/api/library/delete', { items: list.map((x) => ({ kind: x.kind, id: x.id })), outputs: withOut });
      m.close();
      for (const d of r.deleted || []) {
        picked.delete(`${d.kind}:${d.id}`);
        if (d.kind === 'job' && S.lastStudio === d.id) { S.lastStudio = ''; localStorage.removeItem('ic.lastStudio'); }
      }
      if ((r.errors || []).length) toast(`Đã xóa ${(r.deleted || []).length} mục. Chưa xóa được ${r.errors.length}: ${r.errors[0].error}`, 'info');
      else toast(`Đã xóa, giải phóng ${fmtSize(r.freed)}`, 'success');
      if (!picked.size) selecting = false;
      await Promise.all([load(), loadStore()]);
    }));
  }

  await Promise.all([load(), loadStore()]);
  // video vừa xong, vừa thêm: tải lại danh sách
  let sig = '';
  const onQ = (q) => {
    const s = q.filter((i) => i.state === 'running' || i.state === 'queued').map((i) => i.qid + i.state).join(',') + '|' + q.filter((i) => i.state === 'done').length;
    if (sig && s !== sig) { load(); loadStore(); }
    sig = s;
  };
  onQ(S.queue);
  queueListeners.add(onQ);
  return () => queueListeners.delete(onQ);
}
