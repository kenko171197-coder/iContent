/* Trang Ghép video: nhiều video và ảnh thành một video, có chuyển cảnh, chạy qua hàng đợi chung. */
import {
  api, busy, confirmDialog, el, emptyState, enc, fmtAgo, fmtDur, icon, pollSoon, put, queueListeners, S, toast, uploadFile, videoModal,
} from './core.js';

const FITS = [['blur', 'Nền mờ'], ['black', 'Viền đen'], ['crop', 'Cắt cho đầy']];
const ASPECTS = [['', 'Theo video đầu'], ['9:16', 'Dọc 9:16'], ['16:9', 'Ngang 16:9'], ['1:1', 'Vuông 1:1']];

export async function viewMerge(main, alive) {
  const pref = (k, d) => localStorage.getItem('ic.merge.' + k) ?? d;
  const setPref = (k, v) => localStorage.setItem('ic.merge.' + k, v);
  const st = { items: [], jobs: [], transitions: {}, history: [], watch: null, nextId: 1 };

  const list = el('div', { class: 'mg-list' });
  const srcBox = el('div', { class: 'mg-sources' });
  const totalEl = el('span', { class: 'mg-total mono' });
  const nameInp = el('input', { class: 'input', placeholder: 'Tên video, ví dụ: Tổng hợp món ngon tuần này', 'aria-label': 'Tên video', value: pref('name', '') , oninput: () => setPref('name', nameInp.value) });
  const aspSel = el('select', { class: 'input', 'aria-label': 'Khung hình', onchange: () => setPref('aspect', aspSel.value) }, ASPECTS.map(([v, l]) => el('option', { value: v }, l)));
  const fitSel = el('select', { class: 'input', 'aria-label': 'Cách vừa khung', onchange: () => setPref('fit', fitSel.value) }, FITS.map(([v, l]) => el('option', { value: v }, l)));
  const transSel = el('select', { class: 'input', 'aria-label': 'Chuyển cảnh', onchange: () => { setPref('trans', transSel.value); paint(); } });
  const durInp = el('input', { type: 'number', class: 'input', min: 0.2, max: 3, step: 0.1, value: pref('dur', '0.5'), 'aria-label': 'Thời lượng chuyển cảnh', onchange: () => { setPref('dur', durInp.value); paint(); } });
  aspSel.value = pref('aspect', '');
  fitSel.value = pref('fit', 'blur');

  const fileInp = el('input', {
    type: 'file', accept: 'video/*,image/png,image/jpeg,image/webp,.mkv,.flv', multiple: true, hidden: true, onchange: async () => {
      const files = [...fileInp.files];
      fileInp.value = '';
      for (const f of files) {
        const isImage = f.type.startsWith('image/');
        try {
          toast(`Đang tải lên ${f.name}…`, 'info', { timeout: 1500 });
          const r = await uploadFile(isImage ? 'logo' : 'video', f);
          await addPath(r.path, f.name);
        } catch (e) { toast(`${f.name}: ${e.message}`, 'error'); }
      }
    },
  });
  async function addPath(path, title, thumb) {
    const info = await api('GET', `/api/media/info?path=${enc(path)}`);
    st.items.push({ uid: st.nextId++, path, title: title || info.name, thumb: thumb || '', dur: info.duration || 3, image: info.image, start: 0, end: 0, seconds: 3, width: info.width, height: info.height });
    paint();
  }

  const goBtn = el('button', { class: 'btn btn-primary btn-lg', onclick: () => busy(goBtn, start).finally(() => paint()) }, icon('merge'), 'Ghép video');
  const progress = el('div', { class: 'mg-progress', hidden: true });
  const historyBox = el('div', { class: 'mg-history' });

  main.append(
    el('div', { class: 'page-head' }, el('div', { class: 'page-head-text' }, el('div', { class: 'eyebrow', text: 'Ghép video' }), el('h1', { text: 'Ghép nhiều video thành một' }),
      el('p', { text: 'Chọn video đã làm hoặc tải file lên, sắp thứ tự, cắt đầu cuối từng đoạn. Studio566 tự đưa về cùng một khung hình.' }))),
    el('div', { class: 'mg-grid' },
      el('section', { class: 'panel mg-pick' }, el('div', { class: 'panel-head' }, icon('grid'), el('h3', { text: 'Thêm video' }), el('span', { class: 'grow' }),
        fileInp, el('button', { class: 'btn btn-sm', onclick: () => fileInp.click() }, icon('upload'), 'Tải file lên')), srcBox),
      el('section', { class: 'panel mg-main' }, el('div', { class: 'panel-head' }, icon('layers'), el('h3', { text: 'Thứ tự ghép' }), el('span', { class: 'grow' }), totalEl), list,
        el('div', { class: 'mg-opts' },
          el('label', { class: 'mg-opt grow2' }, el('span', { class: 'opt-label', text: 'Tên video' }), nameInp),
          el('label', { class: 'mg-opt' }, el('span', { class: 'opt-label', text: 'Khung hình' }), aspSel),
          el('label', { class: 'mg-opt' }, el('span', { class: 'opt-label', text: 'Vừa khung bằng' }), fitSel),
          el('label', { class: 'mg-opt' }, el('span', { class: 'opt-label', text: 'Chuyển cảnh' }), transSel),
          el('label', { class: 'mg-opt mg-opt-s' }, el('span', { class: 'opt-label', text: 'Giây' }), durInp)),
        el('div', { class: 'mg-go' }, progress, el('span', { class: 'grow' }), goBtn))),
    el('section', { class: 'mg-hist-wrap' }, el('h3', { text: 'Đã ghép' }), historyBox));

  // ------------------------------------------------ danh sách
  const itemDur = (it) => {
    if (it.image) return Number(it.seconds) || 3;
    const a = Number(it.start) || 0, b = Number(it.end) || it.dur;
    return Math.max(0, b - a);
  };
  function totalDur() {
    const sum = st.items.reduce((n, it) => n + itemDur(it), 0);
    const t = transSel.value && st.items.length > 1 ? (Number(durInp.value) || 0) * (st.items.length - 1) : 0;
    return Math.max(0, sum - t);
  }
  let dragId = null;
  const paintTotal = () => { totalEl.textContent = st.items.length ? `${st.items.length} đoạn · ${fmtDur(totalDur())}` : ''; };
  function paint() {
    paintTotal();
    goBtn.disabled = !st.items.length || !!st.watch;
    durInp.disabled = !transSel.value;
    if (!st.items.length) { put(list, emptyState('Chưa có đoạn nào', 'Bấm dấu cộng ở danh sách bên trái, hoặc tải file lên.')); return; }
    put(list, st.items.map((it, i) => {
      const durLabel = el('span', { class: 'dim mono', text: fmtDur(itemDur(it)) });
      const typed = () => { durLabel.textContent = fmtDur(itemDur(it)); paintTotal(); };
      const move = (d) => { const j = i + d; if (j < 0 || j >= st.items.length) return; const [x] = st.items.splice(i, 1); st.items.splice(j, 0, x); paint(); };
      const row = el('div', {
        class: 'mg-row', draggable: 'true',
        ondragstart: (e) => { if (e.target.tagName === 'INPUT') { e.preventDefault(); return; } dragId = it.uid; row.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; },
        ondragend: () => { dragId = null; row.classList.remove('dragging'); },
        ondragover: (e) => { e.preventDefault(); },
        ondrop: (e) => {
          e.preventDefault();
          const from = st.items.findIndex((x) => x.uid === dragId);
          if (from < 0 || from === i) return;
          const [x] = st.items.splice(from, 1);
          st.items.splice(i, 0, x);
          paint();
        },
      },
        el('span', { class: 'mg-idx mono', text: String(i + 1) }),
        el('div', { class: 'mg-thumb' }, it.thumb ? el('img', { alt: '', src: it.thumb }) : icon(it.image ? 'image' : 'film')),
        el('div', { class: 'mg-info' }, el('div', { class: 'mg-title', text: it.title, title: it.path }),
          it.image
            ? el('label', { class: 'mg-range small' }, 'Hiện', el('input', { type: 'number', class: 'input input-xs', min: 0.5, step: 0.5, value: it.seconds, 'aria-label': 'Số giây hiện ảnh', oninput: (e) => { it.seconds = Math.max(0.5, Number(e.target.value) || 3); paintTotal(); } }), 'giây')
            : el('div', { class: 'mg-range small' }, 'Từ', el('input', { type: 'number', class: 'input input-xs', min: 0, step: 0.5, value: it.start, 'aria-label': 'Giây bắt đầu', oninput: (e) => { it.start = Math.max(0, Number(e.target.value) || 0); typed(); } }),
              'đến', el('input', { type: 'number', class: 'input input-xs', min: 0, step: 0.5, value: it.end || '', placeholder: it.dur.toFixed(1), 'aria-label': 'Giây kết thúc', oninput: (e) => { it.end = Number(e.target.value) || 0; typed(); } }),
              durLabel)),
        el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Lên trên', 'aria-label': 'Lên trên', disabled: i === 0, onclick: () => move(-1) }, icon('up')),
        el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Xuống dưới', 'aria-label': 'Xuống dưới', disabled: i === st.items.length - 1, onclick: () => move(1) }, icon('chev')),
        el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Bỏ đoạn này', 'aria-label': 'Bỏ đoạn này', onclick: () => { st.items.splice(i, 1); paint(); } }, icon('x')));
      return row;
    }));
  }

  // ------------------------------------------------ nguồn: video trong thư viện
  function paintSources() {
    if (!st.jobs.length) { put(srcBox, emptyState('Thư viện còn trống', 'Làm vài video trước, hoặc tải file lên để ghép.')); return; }
    put(srcBox, st.jobs.map((j) => {
      const use = j.output ? 'final' : 'source';
      const add = (kind) => () => busy(null, async () => {
        const r = await api('GET', `/api/jobs/${enc(j.id)}/file-path?name=${kind === 'final' ? 'final.mp4' : 'source.mp4'}`);
        await addPath(r.path, (j.title_vi || j.title || j.id) + (kind === 'final' ? '' : ' (gốc)'), j.thumb);
      });
      return el('div', { class: 'mg-src' },
        el('img', { alt: '', loading: 'lazy', src: j.thumb, onerror: (e) => e.target.remove() }),
        el('div', { class: 'mg-src-info' }, el('div', { class: 'mg-title', text: j.title_vi || j.title || j.id, title: j.title }), el('div', { class: 'dim small mono', text: fmtDur(j.duration) + (use === 'final' ? ' · đã lồng tiếng' : ' · chưa xong') })),
        use === 'final' ? el('button', { class: 'btn btn-xs btn-ghost', title: 'Thêm video gốc, chưa dịch và lồng tiếng', onclick: add('source') }, 'Gốc') : null,
        el('button', { class: 'btn btn-xs btn-icon', title: 'Thêm vào danh sách', 'aria-label': 'Thêm vào danh sách', onclick: add(use) }, icon('plus')));
    }));
  }

  // ------------------------------------------------ chạy
  async function start() {
    if (!st.items.length || st.watch) return;
    const bad = st.items.find((it) => !it.image && itemDur(it) < 0.2);
    if (bad) { toast(`Đoạn "${bad.title}" quá ngắn, hãy xem lại mốc từ và đến`, 'warn'); return; }
    const r = await api('POST', '/api/merge', {
      name: nameInp.value.trim() || 'Video ghép', aspect: aspSel.value, fit: fitSel.value, transition: transSel.value, trans_dur: Number(durInp.value) || 0.5,
      items: st.items.map((it) => ({ path: it.path, title: it.title, start: it.start, end: it.end, seconds: it.seconds })),
    });
    st.watch = r.qid;
    pollSoon();
    paint();
  }
  const onQueue = (items) => {
    if (!st.watch) return;
    const it = items.find((x) => x.qid === st.watch);
    if (!it) return;
    progress.hidden = false;
    const pct = typeof it.progress === 'number' ? Math.round(it.progress * 100) : null;
    if (it.state === 'queued' || it.state === 'running') {
      put(progress, el('span', { class: 'small', text: it.state === 'queued' ? 'Đang chờ tới lượt…' : `Đang ghép${pct != null ? ' ' + pct + '%' : '…'}` }),
        el('div', { class: 'off-bar' + (pct == null ? ' busy' : '') }, el('i', { style: pct == null ? {} : { width: pct + '%' } })),
        el('button', { class: 'btn btn-xs', onclick: () => api('POST', `/api/queue/${enc(st.watch)}/cancel`).then(pollSoon) }, icon('x'), 'Hủy'));
      return;
    }
    const was = st.watch;
    st.watch = null;
    paint();
    if (it.state === 'done') {
      progress.hidden = true;
      toast('Đã ghép xong', 'success');
      loadHistory();
      st.items = [];
      paint();
    } else if (it.state === 'error') {
      put(progress, el('span', { class: 'small test-out err', text: String(it.error || it.message || 'Lỗi').split('\n')[0] }));
    } else progress.hidden = true;
    void was;
  };

  // ------------------------------------------------ đã ghép
  async function loadHistory() {
    const r = await api('GET', '/api/merges');
    if (!alive()) return;
    st.history = r.items || [];
    if (!st.history.length) { put(historyBox, el('p', { class: 'muted small', text: 'Chưa có bản ghép nào.' })); return; }
    put(historyBox, st.history.map((m) => {
      const url = `/api/merges/${enc(m.id)}/video`;
      const stBtn = el('button', {
        class: 'btn btn-sm', title: 'Đưa vào quy trình để dịch, lồng tiếng và sửa trong Studio', onclick: () => busy(stBtn, async () => {
          await api('POST', '/api/queue', { sources: [m.path], options: {}, titles: { [m.path]: m.name } });
          pollSoon();
          toast('Đã thêm vào hàng đợi', 'success', { actions: [{ label: 'Xem tiến độ', onClick: () => { location.hash = '#/new'; } }] });
        }),
      }, icon('sliders'), 'Dịch và lồng tiếng');
      return el('div', { class: 'mg-done' },
        el('button', { class: 'mg-done-thumb', title: 'Xem', onclick: () => videoModal(url, m.name) }, el('img', { alt: '', src: `/api/merges/${enc(m.id)}/thumb`, onerror: (e) => e.target.remove() }), icon('play')),
        el('div', { class: 'mg-done-info' }, el('div', { class: 'mg-title', text: m.name }),
          el('div', { class: 'dim small mono', text: `${fmtDur(m.duration)} · ${m.width}×${m.height} · ${m.clips} đoạn · ${fmtAgo(m.created)}` }),
          el('div', { class: 'dim small mg-path', text: m.path, title: m.path })),
        el('div', { class: 'btn-row' },
          el('a', { class: 'btn btn-sm', href: url, download: '' }, icon('download'), 'Tải về'), stBtn,
          el('button', {
            class: 'btn btn-sm btn-icon btn-ghost', title: 'Xóa bản ghép này', 'aria-label': 'Xóa bản ghép này', onclick: async () => {
              if (!await confirmDialog('Xóa bản ghép này?', 'File video sẽ bị xóa khỏi máy.', { okText: 'Xóa', danger: true })) return;
              try {
                await api('DELETE', `/api/merges/${enc(m.id)}`);
              } catch (e) { toast(e.message, 'error'); return; }
              loadHistory();
            },
          }, icon('trash'))));
    }));
  }

  // ------------------------------------------------ khởi động
  const [jobs, meta] = await Promise.all([api('GET', '/api/jobs'), api('GET', '/api/merge/options')]);
  if (!alive()) return null;
  st.jobs = jobs.jobs || [];
  st.transitions = meta.transitions || {};
  put(transSel, Object.entries(st.transitions).map(([k, v]) => el('option', { value: k }, v)));
  transSel.value = pref('trans', '');
  paintSources();
  paint();
  loadHistory();
  queueListeners.add(onQueue);
  const running = S.queue.find((i) => i.kind === 'merge' && (i.state === 'queued' || i.state === 'running'));
  if (running) { st.watch = running.qid; onQueue(S.queue); paint(); }
  return () => queueListeners.delete(onQueue);
}
