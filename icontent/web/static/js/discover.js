/* Trang Khám phá: video thịnh hành và đề tài hot bên Trung Quốc, chọn rồi đưa thẳng vào hàng đợi. */
import {
  api, busy, copyBtn, el, emptyState, enc, ensureConfig, errorState, fmtAgo, fmtDur, icon, modalHead, openModal, pollSoon, put, toast,
} from './core.js';
import { RECIPES } from './home.js';

const SORTS = [['score', 'Đáng làm nhất'], ['vph', 'Lên nhanh nhất'], ['view', 'Nhiều lượt xem'], ['engage', 'Tương tác cao'], ['new', 'Mới đăng']];
const DURS = [['', 'Mọi độ dài'], ['s', 'Dưới 1 phút'], ['m', '1 đến 3 phút'], ['l', '3 đến 10 phút'], ['x', 'Trên 10 phút']];
const ORIENTS = [['', 'Mọi khung'], ['v', 'Video dọc'], ['h', 'Video ngang']];
const DUR_TEST = {
  '': () => true, s: (d) => d < 60, m: (d) => d >= 60 && d < 180, l: (d) => d >= 180 && d < 600, x: (d) => d >= 600,
};
const SOURCE_COLOR = { douyin: '#fe2c55', weibo: '#ff8200', bilibili: '#23ade5', baidu: '#4e6ef2', toutiao: '#f04142', zhihu: '#1772f6' };

/** 1234 -> "1,2 N"; 1200000 -> "1,2 Tr" */
export function fmtCount(n) {
  n = Number(n) || 0;
  const f = (v) => (v >= 100 ? String(Math.round(v)) : v.toFixed(1).replace(/\.0$/, '').replace('.', ','));
  if (n >= 1e8) return f(n / 1e8) + ' Tỉ';
  if (n >= 1e6) return f(n / 1e6) + ' Tr';
  if (n >= 1e3) return f(n / 1e3) + ' N';
  return String(n);
}
const coverSmall = (u) => (u && u.includes('hdslb.com') ? u + '@480w_300h_1c.jpg' : u);

export async function viewDiscover(main, alive) {
  await ensureConfig();
  if (!alive()) return null;
  let userRecipes = [];
  try { userRecipes = (await api('GET', '/api/presets')).presets || []; } catch (_) { /* không có cũng được */ }
  if (!alive()) return null;

  const pref = (k, d) => localStorage.getItem('ic.disc.' + k) ?? d;
  const setPref = (k, v) => localStorage.setItem('ic.disc.' + k, v);
  const st = {
    tab: pref('tab', 'videos'), cat: pref('cat', 'picks'), dur: pref('dur', ''), orient: pref('orient', ''), sort: pref('sort', 'score'),
    recipe: pref('recipe', ''), items: [], at: 0, stale: false, error: '', loading: false, vi: new Map(), selected: new Map(), saved: [],
    live: [], archive: [], showArch: false, how: '', query: '', results: null, zh: '', links: [], topics: null,
  };
  let saved = [];
  try { saved = (await api('GET', '/api/trends/saved')).items || []; } catch (_) { saved = []; }
  st.saved = saved;

  // ------------------------------------------------ dịch dần tiêu đề, xong câu nào hiện câu đó
  const viListeners = new Set();
  let viQueue = [];
  let viRunning = false;
  /** Đưa chữ cần dịch lên đầu hàng chờ. Một luồng dịch duy nhất: đổi tab không làm mất phần đang dịch */
  async function translateAll(texts) {
    const fresh = [...new Set(texts)].filter((t) => t && !st.vi.has(t));
    viQueue = [...fresh, ...viQueue.filter((t) => !fresh.includes(t))];
    if (viRunning) return;
    viRunning = true;
    try {
      while (viQueue.length && alive()) {
        const batch = viQueue.splice(0, 10);
        let r;
        try { r = await api('POST', '/api/trends/translate', { texts: batch }); } catch (_) { return; }
        if (!alive()) return;
        Object.entries(r.map || {}).forEach(([k, v]) => st.vi.set(k, v));
        if (r.how === 'none' && !Object.keys(r.map || {}).length) { st.how = 'none'; viQueue = []; paintNote(); return; }
        st.how = r.how;
        batch.filter((t) => !st.vi.has(t)).forEach((t) => st.vi.set(t, ''));      // không dịch được: không thử lại mãi
        viListeners.forEach((f) => f());
      }
    } finally { viRunning = false; }
  }

  // ------------------------------------------------ khung chung
  const searchInp = el('input', {
    class: 'input', placeholder: 'Tìm đề tài, gõ tiếng Việt hoặc tiếng Trung', 'aria-label': 'Tìm video theo đề tài',
    onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); runSearch(searchInp.value); } },
  });
  const refreshBtn = el('button', { class: 'btn', title: 'Tải lại danh sách mới nhất', onclick: () => busy(refreshBtn, () => reload(true)) }, icon('refresh'), 'Làm mới');
  const tabs = el('div', { class: 'seg seg-inline dc-tabs', role: 'tablist' });
  const TABS = [['videos', 'Video thịnh hành'], ['topics', 'Đề tài hot'], ['saved', 'Đã lưu']];
  const tabBtn = {};
  TABS.forEach(([k, label]) => {
    tabBtn[k] = el('button', { type: 'button', class: 'seg-btn', role: 'tab', onclick: () => setTab(k) }, label);
    tabs.append(tabBtn[k]);
  });
  const recipeSel = el('select', { class: 'input dc-recipe', 'aria-label': 'Công thức làm video', onchange: () => { st.recipe = recipeSel.value; setPref('recipe', st.recipe); } },
    el('option', { value: '' }, 'Cài đặt mặc định'),
    RECIPES.map((r) => el('option', { value: 'r:' + r.id }, r.name)),
    userRecipes.map((r, i) => el('option', { value: 'u:' + i }, r.name)));
  recipeSel.value = st.recipe;
  if (recipeSel.value !== st.recipe) { recipeSel.value = ''; st.recipe = ''; }
  const recipeOptions = () => {
    const v = st.recipe;
    if (v.startsWith('r:')) return (RECIPES.find((r) => r.id === v.slice(2)) || {}).options || {};
    if (v.startsWith('u:')) return (userRecipes[Number(v.slice(2))] || {}).options || {};
    return {};
  };
  const note = el('div', { class: 'dc-note' });
  const body = el('div', { class: 'dc-body' });
  const selBar = el('div', { class: 'dc-selbar', hidden: true });

  main.append(
    el('div', { class: 'page-head' },
      el('div', { class: 'page-head-text' }, el('div', { class: 'eyebrow', text: 'Khám phá' }), el('h1', { text: 'Bên Trung Quốc đang xem gì?' }),
        el('p', { text: 'Chọn video đang lên hoặc đề tài hot, bấm một nút là iContent tải về, dịch, lồng tiếng và xóa sub.' })),
      el('div', { class: 'actions' }, el('div', { class: 'search-box dc-search' }, icon('search'), searchInp), refreshBtn)),
    el('div', { class: 'dc-toolbar' }, tabs, el('span', { class: 'grow' }), el('span', { class: 'dim small', text: 'Làm theo công thức' }), recipeSel),
    note, body, selBar,
    el('p', { class: 'dim small dc-legal', text: 'Video thuộc bản quyền của tác giả. Hãy xin phép hoặc làm đúng quy định của nền tảng trước khi đăng lại.' }));

  function paintNote() {
    const items = [];
    if (st.how === 'none') items.push(el('a', { class: 'banner', href: '#/settings' }, icon('globe'), el('div', {}, el('b', { text: 'Tiêu đề đang để nguyên tiếng Trung. ' }), 'Tải Dịch offline (không cần key, Cài đặt > Mô-đun AI miễn phí) hoặc kết nối AI để đọc bằng tiếng Việt.'), el('span', { class: 'banner-go' }, 'Thiết lập', icon('next'))));
    if (st.stale && st.error) items.push(el('div', { class: 'banner banner-plain' }, icon('alert'), el('div', {}, el('b', { text: 'Đang hiện dữ liệu đã lưu. ' }), st.error)));
    put(note, ...items);
  }

  // ------------------------------------------------ làm video
  async function enqueue(videos, btn) {
    const list = Array.isArray(videos) ? videos : [videos];
    const run = async () => {
      const titles = {};
      list.forEach((v) => { titles[v.url] = st.vi.get(v.title) || v.title; });
      await api('POST', '/api/queue', { sources: list.map((v) => v.url), options: recipeOptions(), titles });
      pollSoon();
      list.forEach((v) => { v.state = v.state || 'queued'; });
      const long = list.filter((v) => v.duration > 900).length;
      toast(`Đã thêm ${list.length} video vào hàng đợi` + (long ? `. Có ${long} video dài trên 15 phút, sẽ mất khá lâu` : ''), 'success', { actions: [{ label: 'Xem tiến độ', onClick: () => { location.hash = '#/new'; } }] });
      st.selected.clear();
      paintSelBar();
      repaint();
    };
    return btn ? busy(btn, run) : run();
  }
  const isSaved = (v) => st.saved.some((x) => x.id === v.id);
  async function toggleSave(v) {
    st.saved = isSaved(v) ? st.saved.filter((x) => x.id !== v.id) : [Object.assign({}, v, { saved_at: Date.now() / 1000 }), ...st.saved];
    try { await api('PUT', '/api/trends/saved', { items: st.saved }); } catch (e) { toast('Không lưu được: ' + e.message, 'error'); }
    paintTabs();
  }

  // ------------------------------------------------ thẻ video
  function VideoCard(v, compact) {
    const vi = el('div', { class: 'dc-title', title: v.title });
    const zh = el('div', { class: 'dc-zh', text: v.title, title: v.title });
    const paintVi = () => {
      const t = st.vi.get(v.title);
      vi.textContent = t || v.title;
      zh.hidden = !t;
    };
    paintVi();
    const unsub = () => viListeners.delete(paintVi);
    viListeners.add(paintVi);
    const img = el('img', { alt: '', loading: 'lazy', referrerpolicy: 'no-referrer', src: coverSmall(v.cover), onerror: () => { img.remove(); } });
    const check = el('input', {
      type: 'checkbox', class: 'dc-check', title: 'Chọn để làm nhiều video một lúc', 'aria-label': 'Chọn video này', checked: st.selected.has(v.id),
      onclick: (e) => e.stopPropagation(),
      onchange: () => { if (check.checked) st.selected.set(v.id, v); else st.selected.delete(v.id); root.classList.toggle('selected', check.checked); paintSelBar(); },
    });
    const star = el('button', {
      class: 'btn btn-xs btn-icon btn-ghost dc-star' + (isSaved(v) ? ' on' : ''), title: 'Lưu để làm sau', 'aria-label': 'Lưu để làm sau',
      onclick: async (e) => { e.stopPropagation(); await toggleSave(v); star.classList.toggle('on', isSaved(v)); if (st.tab === 'saved') repaint(); },
    }, icon('star'));
    const done = v.state === 'done';
    const started = v.state === 'started' || v.state === 'queued';
    const make = done || (started && v.job)
      ? el('a', { class: 'btn btn-xs', href: '#/studio/' + enc(v.job || ''), onclick: (e) => e.stopPropagation() }, icon('sliders'), done ? 'Đã làm, mở Studio' : 'Đang làm dở')
      : v.state === 'queued'
        ? el('button', { class: 'btn btn-xs', disabled: true }, 'Đã xếp hàng')
        : el('button', { class: 'btn btn-xs btn-primary', onclick: (e) => { e.stopPropagation(); enqueue(v, make); } }, icon('play'), 'Làm video');
    const root = el('article', { class: 'dc-card' + (st.selected.has(v.id) ? ' selected' : ''), tabindex: '0', onclick: () => previewVideo(v), onkeydown: (e) => { if (e.key === 'Enter' && e.target === root) previewVideo(v); } },
      el('div', { class: 'dc-thumb' }, icon('film', 'jc-ph'), img, check,
        v.score != null ? el('span', { class: 'dc-score mono', title: 'Điểm đáng làm: lượt xem mỗi giờ, độ tương tác, độ dài và mức hợp lồng tiếng', text: String(v.score) }) : null,
        el('span', { class: 'jc-dur mono', text: fmtDur(v.duration) }),
        el('span', { class: 'dc-play' }, icon('play'))),
      el('div', { class: 'dc-info' }, vi, zh,
        el('div', { class: 'dc-stats' },
          el('span', { title: 'Lượt xem' }, icon('eye'), el('b', { class: 'mono', text: fmtCount(v.view) })),
          el('span', { title: 'Lượt thích' }, icon('heart'), el('span', { class: 'mono', text: fmtCount(v.like) })),
          v.vph ? el('span', { title: 'Lượt xem mỗi giờ kể từ khi đăng' }, icon('flame'), el('span', { class: 'mono', text: fmtCount(v.vph) + '/giờ' })) : null),
        compact ? null : el('div', { class: 'dc-tags' }, (v.tags || []).slice(0, 3).map((t) => el('span', { class: 'dc-tag', text: t }))),
        el('div', { class: 'dc-by dim small', title: v.author }, [v.label, v.author, v.pubdate ? fmtAgo(v.pubdate) : ''].filter(Boolean).join(' · ')),
        el('div', { class: 'dc-acts' }, make, el('span', { class: 'grow' }), star,
          el('a', { class: 'btn btn-xs btn-icon btn-ghost', href: v.url, target: '_blank', rel: 'noreferrer', title: 'Mở trên nền tảng', 'aria-label': 'Mở trên nền tảng', onclick: (e) => e.stopPropagation() }, icon('external')))));
    root.__unsub = unsub;
    return root;
  }
  function cleanupCards(box) { box.querySelectorAll('.dc-card').forEach((c) => c.__unsub && c.__unsub()); }

  function previewVideo(v) {
    const frame = el('iframe', {
      class: 'dc-frame', title: 'Xem trước video', allow: 'autoplay; fullscreen', allowfullscreen: 'true', referrerpolicy: 'no-referrer',
      src: `https://player.bilibili.com/player.html?bvid=${enc(v.id)}&autoplay=1&danmaku=0&high_quality=1`,
    });
    const makeBtn = el('button', { class: 'btn btn-primary', onclick: async () => { await enqueue(v, makeBtn); m.close(); } }, icon('play'), 'Làm video này');
    const m = openModal([
      modalHead('play', st.vi.get(v.title) || v.title, () => m),
      el('div', { class: 'modal-body' },
        el('div', { class: 'dc-preview' },
          el('div', { class: 'dc-frame-wrap' + (v.vertical ? ' tall' : '') }, frame),
          el('div', { class: 'dc-preview-side' },
            el('div', { class: 'dc-zh', text: v.title }),
            el('div', { class: 'dc-stats big' },
              el('span', {}, icon('eye'), el('b', { class: 'mono', text: fmtCount(v.view) }), ' lượt xem'),
              el('span', {}, icon('heart'), el('span', { class: 'mono', text: fmtCount(v.like) }), ' thích'),
              v.share ? el('span', {}, icon('send'), el('span', { class: 'mono', text: fmtCount(v.share) }), ' chia sẻ') : null),
            el('div', { class: 'dc-tags' }, (v.tags || []).map((t) => el('span', { class: 'dc-tag', text: t }))),
            el('p', { class: 'muted small', text: [v.label, v.author, fmtDur(v.duration), v.pubdate ? 'đăng ' + fmtAgo(v.pubdate) : ''].filter(Boolean).join(' · ') }),
            v.desc ? el('p', { class: 'dim small dc-desc', text: v.desc }) : null))),
      el('div', { class: 'modal-foot' },
        el('a', { class: 'btn btn-ghost left', href: v.url, target: '_blank', rel: 'noreferrer' }, icon('external'), 'Mở trên Bilibili'),
        el('button', { class: 'btn btn-ghost', onclick: () => m.close() }, 'Đóng'), makeBtn),
    ], { cls: 'modal-wide', onClose: () => frame.removeAttribute('src') });
  }

  // ------------------------------------------------ thanh đã chọn
  function paintSelBar() {
    const list = [...st.selected.values()];
    selBar.hidden = !list.length;
    if (!list.length) return;
    const total = list.reduce((n, v) => n + (v.duration || 0), 0);
    const go = el('button', { class: 'btn btn-primary', onclick: () => enqueue(list, go) }, icon('play'), `Làm ${list.length} video`);
    put(selBar, el('b', { text: `Đã chọn ${list.length} video` }), el('span', { class: 'muted small mono', text: fmtDur(total) }), el('span', { class: 'grow' }),
      el('button', { class: 'btn btn-ghost', onclick: () => { st.selected.clear(); paintSelBar(); repaint(); } }, 'Bỏ chọn'), go);
  }

  // ------------------------------------------------ tab Video
  const chips = el('div', { class: 'dc-chipbox' });
  const durSel = el('select', { class: 'input input-sm', 'aria-label': 'Độ dài video', onchange: () => { st.dur = durSel.value; setPref('dur', st.dur); paintGrid(); } }, DURS.map(([v, l]) => el('option', { value: v }, l)));
  const oriSel = el('select', { class: 'input input-sm', 'aria-label': 'Khung hình', onchange: () => { st.orient = oriSel.value; setPref('orient', st.orient); paintGrid(); } }, ORIENTS.map(([v, l]) => el('option', { value: v }, l)));
  const sortSel = el('select', { class: 'input input-sm', 'aria-label': 'Sắp xếp', onchange: () => { st.sort = sortSel.value; setPref('sort', st.sort); paintGrid(); } }, SORTS.map(([v, l]) => el('option', { value: v }, l)));
  durSel.value = st.dur; oriSel.value = st.orient; sortSel.value = st.sort;
  const filters = el('div', { class: 'dc-filters' }, durSel, oriSel, sortSel);
  const countEl = el('span', { class: 'dim small' });
  const grid = el('div', { class: 'dc-grid' });

  function paintChips() {
    const pick = (c, ic) => el('button', {
      type: 'button', class: 'chip' + (c.id === st.cat ? ' active' : ''), title: c.count ? `${c.count} video` : null,
      onclick: () => { st.cat = c.id; setPref('cat', c.id); paintChips(); load(false); },
    }, ic ? icon(ic) : null, c.name);
    const inArch = st.cat.startsWith('arch:');
    put(chips,
      el('div', { class: 'dc-chips' }, pick({ id: 'picks', name: 'Gợi ý cho bạn' }, 'spark'), pick({ id: 'hot', name: 'Đang hot' }, 'flame'), st.live.map((c) => pick(c)),
        el('button', {
          type: 'button', class: 'chip' + (inArch || st.showArch ? ' active' : ''), title: 'Video từng rất hot, không phải xu hướng hôm nay',
          onclick: () => { st.showArch = !st.showArch; if (!st.showArch && inArch) { st.cat = 'picks'; setPref('cat', 'picks'); load(false); } paintChips(); },
        }, icon('star'), 'Kinh điển')),
      inArch || st.showArch ? el('div', { class: 'dc-arch' },
        el('p', { class: 'dim small', text: 'Video từng rất hot, không phải xu hướng hôm nay: Bilibili đã dừng cập nhật bảng theo chuyên mục từ khoảng tháng 3/2025. Vẫn hợp để làm lại vì nội dung đã được kiểm chứng.' }),
        el('div', { class: 'dc-chips' }, st.archive.map((c) => pick(c)))) : null);
  }
  const sorted = (list) => {
    const key = { score: (v) => -v.score, vph: (v) => -v.vph, view: (v) => -v.view, engage: (v) => -v.engage, new: (v) => -v.pubdate }[st.sort] || ((v) => -v.score);
    return list.filter((v) => DUR_TEST[st.dur](v.duration) && (!st.orient || (st.orient === 'v' ? v.vertical : !v.vertical))).slice().sort((a, b) => key(a) - key(b));
  };
  function paintGrid() {
    cleanupCards(grid);
    grid.classList.remove('single');      // lần trước có thể là báo lỗi hoặc trống, khung chờ phải về dạng lưới
    if (st.loading) { grid.replaceChildren(...Array.from({ length: 12 }, () => el('div', { class: 'skel', style: { height: '310px' } }))); return; }
    if (st.error && !st.items.length) { grid.replaceChildren(errorState(st.error, () => load(true))); grid.classList.add('single'); return; }
    const list = sorted(st.items).slice(0, 100);
    countEl.textContent = `${list.length} video` + (st.at ? ` · cập nhật ${fmtAgo(st.at)}` : '');
    if (!list.length) { grid.classList.add('single'); grid.replaceChildren(emptyState('Không có video nào khớp', 'Thử bỏ bớt bộ lọc độ dài hoặc khung hình.')); return; }
    grid.replaceChildren(...list.map((v) => VideoCard(v)));
    translateAll(list.map((v) => v.title));
  }
  async function loadCategories() {
    try {
      const c = await api('GET', '/api/trends/categories');
      st.live = c.live || [];
      st.archive = c.archive || [];
      if (alive() && st.tab === 'videos') paintChips();
    } catch (_) { /* vẫn còn Gợi ý và Đang hot */ }
  }
  async function load(refresh) {
    st.loading = true;
    paintGrid();
    try {
      const r = await api('GET', `/api/trends/videos?cat=${enc(st.cat)}${refresh ? '&refresh=1' : ''}`);
      if (!alive()) return;
      Object.assign(st, { items: r.items || [], at: r.at, stale: r.stale, error: r.error || '' });
      if (!st.live.length) await loadCategories();
    } catch (e) {
      if (!alive()) return;
      Object.assign(st, { items: [], error: e.message });
    }
    st.loading = false;
    paintNote();
    paintGrid();
  }

  // ------------------------------------------------ tab Đề tài
  const topicsBox = el('div', { class: 'dc-topics' });
  function TopicRow(t) {
    const vi = el('span', { class: 'dc-t-vi' });
    const zh = el('span', { class: 'dc-t-zh', text: t.word });
    const paint = () => { const x = st.vi.get(t.word); vi.textContent = x || t.word; zh.hidden = !x; };
    paint();
    viListeners.add(paint);
    return el('button', { type: 'button', class: 'dc-t-row', title: 'Xem cách tìm video về đề tài này', onclick: () => openTopic(t) },
      el('span', { class: 'dc-t-rank mono' + (t.rank <= 3 ? ' top' : ''), text: String(t.rank) }),
      el('span', { class: 'dc-t-text' }, vi, zh),
      t.hot ? el('span', { class: 'dc-t-hot mono', text: fmtCount(t.hot) }) : null);
  }
  function paintTopics() {
    if (!st.topics) {
      topicsBox.replaceChildren(...Array.from({ length: 6 }, () => el('div', { class: 'skel', style: { height: '460px' } })));
      return;
    }
    topicsBox.replaceChildren(...st.topics.map((s) => el('section', { class: 'dc-t-col' },
      el('header', { class: 'dc-t-head' }, el('i', { style: { background: SOURCE_COLOR[s.id] || 'var(--amber)' } }), el('b', { text: s.name }), el('span', { class: 'grow' }), s.at ? el('span', { class: 'dim small', text: fmtAgo(s.at) }) : null),
      s.items.length ? el('div', { class: 'dc-t-list' }, s.items.slice(0, 20).map(TopicRow)) : el('p', { class: 'muted small dc-t-err', text: s.error || 'Không có dữ liệu' }))));
    translateAll(st.topics.flatMap((s) => s.items.slice(0, 20).map((t) => t.word)));
  }
  async function loadTopics(refresh) {
    st.topics = null;
    paintTopics();
    try {
      const r = await api('GET', `/api/trends/topics${refresh ? '?refresh=1' : ''}`);
      if (!alive()) return;
      st.topics = r.sources || [];
    } catch (e) {
      if (!alive()) return;
      topicsBox.replaceChildren(errorState(e.message, () => loadTopics(true)));
      return;
    }
    paintTopics();
  }

  // ------------------------------------------------ đề tài / tìm kiếm: kết quả + mở nền tảng + dán link
  function LinkBox(onDone) {
    const inp = el('input', { class: 'input', placeholder: 'Đã chọn được video? Dán link hoặc đoạn chia sẻ vào đây', 'aria-label': 'Link video', onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); add.click(); } } });
    const add = el('button', {
      class: 'btn btn-primary', onclick: () => busy(add, async () => {
        const src = inp.value.trim();
        if (!src) { inp.focus(); return; }
        await api('POST', '/api/queue', { sources: [src], options: recipeOptions() });
        pollSoon();
        inp.value = '';
        toast('Đã thêm vào hàng đợi', 'success', { actions: [{ label: 'Xem tiến độ', onClick: () => { location.hash = '#/new'; } }] });
        if (onDone) onDone();
      }),
    }, icon('play'), 'Làm video');
    return el('div', { class: 'dc-linkbox' }, inp, add);
  }
  const platformLinks = (links) => el('div', { class: 'dc-links' }, links.map((l) => el('a', { class: 'btn btn-sm', href: l.url, target: '_blank', rel: 'noreferrer' }, l.name, icon('external'))));

  function openTopic(t) {
    const results = el('div', { class: 'dc-grid compact' }, Array.from({ length: 4 }, () => el('div', { class: 'skel', style: { height: '240px' } })));
    const linksBox = el('div', {});
    const vi = st.vi.get(t.word);
    const m = openModal([
      modalHead('flame', vi || t.word, () => m),
      el('div', { class: 'modal-body dc-topic-body' },
        el('div', { class: 'dc-topic-word' }, el('span', { class: 'dc-zh', text: t.word }), copyBtn(t.word, 'Chép từ khóa'), t.url ? el('a', { class: 'btn btn-xs', href: t.url, target: '_blank', rel: 'noreferrer' }, 'Trang đề tài', icon('external')) : null),
        el('h4', { text: 'Tìm video về đề tài này' }),
        el('p', { class: 'muted small', text: 'Mở nền tảng để duyệt, chép link video ưng ý rồi dán vào ô dưới. Douyin cần cookie mới tải được (xem Cài đặt).' }),
        linksBox, LinkBox(() => m.close()),
        el('h4', { text: 'Có sẵn trong kho video' }), results),
    ], { cls: 'modal-wide', onClose: () => cleanupCards(results) });
    put(linksBox, el('span', { class: 'dim small', text: 'Đang tìm…' }));
    api('GET', `/api/trends/search?q=${enc(t.word)}`).then((r) => {
      put(linksBox, platformLinks(r.links || []));
      if (!(r.items || []).length) { results.classList.add('single'); results.replaceChildren(el('p', { class: 'muted small', text: 'Chưa có video nào trong kho khớp với đề tài này.' })); return; }
      results.replaceChildren(...r.items.slice(0, 12).map((v) => VideoCard(v, true)));
      translateAll(r.items.slice(0, 12).map((v) => v.title));
    }).catch((e) => { results.replaceChildren(el('p', { class: 'muted small', text: e.message })); });
  }
  async function runSearch(q) {
    q = (q || '').trim();
    if (!q) return;
    st.query = q; st.results = null;
    setTab('search');
    try {
      const r = await api('GET', `/api/trends/search?q=${enc(q)}`);
      if (!alive() || st.query !== q) return;
      Object.assign(st, { results: r.items || [], zh: r.zh || '', links: r.links || [] });
    } catch (e) {
      if (!alive()) return;
      st.results = [];
      st.links = [];
      toast(e.message, 'error');
    }
    repaint();
  }
  function paintSearch() {
    const box = el('div', {});
    if (st.results === null) {
      box.append(el('p', { class: 'muted', text: `Đang tìm "${st.query}" trong kho video, lần đầu mất khoảng nửa phút…` }), el('div', { class: 'dc-grid' }, Array.from({ length: 8 }, () => el('div', { class: 'skel', style: { height: '310px' } }))));
      return box;
    }
    box.append(
      el('div', { class: 'dc-search-head' },
        el('div', {}, el('b', { text: `${st.results.length} video` }), ` cho "${st.query}"`, st.zh && st.zh !== st.query ? [' · tìm bằng ', el('span', { class: 'dc-zh-inline', text: st.zh })] : null,
          el('div', { class: 'dim small', text: 'Tìm trong video đang thịnh hành và kho Kinh điển. Muốn rộng hơn, mở thẳng nền tảng rồi dán link về đây.' })),
        el('button', { class: 'btn btn-ghost btn-sm', onclick: () => { searchInp.value = ''; setTab('videos'); } }, icon('x'), 'Đóng')),
      platformLinks(st.links), LinkBox());
    if (st.results.length) {
      box.append(el('div', { class: 'dc-grid' }, st.results.map((v) => VideoCard(v))));
      translateAll(st.results.map((v) => v.title));
    } else box.append(emptyState('Kho chưa có video khớp', 'Bấm một nền tảng ở trên để tìm rộng hơn, hoặc thử từ khóa khác.'));
    return box;
  }

  // ------------------------------------------------ chuyển tab
  function paintTabs() {
    Object.entries(tabBtn).forEach(([k, b]) => {
      const on = k === st.tab;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      if (k === 'saved') b.textContent = st.saved.length ? `Đã lưu (${st.saved.length})` : 'Đã lưu';
    });
  }
  function repaint() {
    cleanupCards(body);
    viListeners.clear();
    paintTabs();
    if (st.tab === 'videos') {
      put(body, el('div', { class: 'dc-videohead' }, chips), el('div', { class: 'dc-filterbar' }, filters, el('span', { class: 'grow' }), countEl), grid);
      paintChips();
      paintGrid();
    } else if (st.tab === 'topics') {
      put(body, topicsBox);
      paintTopics();
    } else if (st.tab === 'search') {
      put(body, paintSearch());
    } else {
      put(body, st.saved.length ? el('div', { class: 'dc-grid' }, st.saved.map((v) => VideoCard(v))) : emptyState('Chưa lưu video nào', 'Bấm ngôi sao trên video để để dành làm sau.'));
      translateAll(st.saved.map((v) => v.title));
    }
  }
  function setTab(k) {
    st.tab = k;
    if (k !== 'search') setPref('tab', k);
    repaint();
    if (k === 'videos' && !st.items.length && !st.loading) load(false);
    if (k === 'topics' && !st.topics) loadTopics(false);
  }
  async function reload(refresh) {
    if (st.tab === 'topics') return loadTopics(refresh);
    return load(refresh);
  }

  // ------------------------------------------------ khởi động
  if (st.tab === 'search') st.tab = 'videos';
  setTab(st.tab);
  if (st.tab !== 'videos') load(false);
  return () => { viQueue = []; viListeners.clear(); };
}
