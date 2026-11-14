/* Điểm khởi động: router, bảng lệnh nhanh (Ctrl+K). */
import {
  $, S, api, closeAllModals, closePop, el, emptyState, enc, errorState, fmtDur, icon, loadFonts, loadStatus, loadVoices, modalStack, openModal,
  pollQueue, pollSoon, stopAudio, confirmDialog, toast, licenseHooks,
} from './core.js';
import { showLicenseGate } from './license.js';
import { startConn } from './conn.js';
import { viewAbout } from './about.js';
import { openExternal } from './fixes.js';
import { viewDiscover } from './discover.js';
import { viewNew } from './home.js';
import { viewImageLab } from './imagelab.js';
import { viewThumbnail } from './thumbnail.js';
import { viewWorkflow } from './workflow.js';
import { viewHome } from './dashboard.js';
import { viewEditor } from './editor.js';
import { viewStory } from './story.js';
import { viewVoiceover } from './voiceover.js';
import { viewLibrary } from './library.js';
import { openOnboarding } from './onboard.js';
import { viewMerge } from './merge.js';
import { viewSettings } from './settings.js';
import { openShortcuts, viewStudio } from './studio.js';

const VIEWS = { home: viewHome, new: viewNew, discover: viewDiscover, library: viewLibrary, image: viewImageLab, thumb: viewThumbnail, flow: viewWorkflow, editor: viewEditor, story: viewStory, voice: viewVoiceover, merge: viewMerge, studio: viewStudio, settings: viewSettings, about: viewAbout };
const TITLES = { home: 'Trang chủ', new: 'Dịch video', discover: 'Tìm ý tưởng', library: 'Video của tôi', image: 'Sửa ảnh', thumb: 'Ảnh bìa', flow: 'Tự động hóa', editor: 'Trình dựng nâng cao', story: 'Kể chuyện từ ảnh', voice: 'Đọc thành giọng nói', merge: 'Ghép video', studio: 'Chỉnh sửa video', settings: 'Cài đặt', about: 'Giới thiệu' };
let routeTok = 0, cleanup = null, currentHash = '', ignoreHash = false;

function parseHash() {
  const h = location.hash.replace(/^#\/?/, '');
  const parts = h.split('/');
  const name = VIEWS[parts[0]] ? parts[0] : 'home';
  let arg = '';
  if (parts.length > 1) { try { arg = decodeURIComponent(parts.slice(1).join('/')); } catch (_) { arg = parts.slice(1).join('/'); } }
  return { name, arg };
}
function setNav(name) {
  document.querySelectorAll('.rail-item[data-route]').forEach((a) => {
    const on = a.dataset.route === name;
    a.classList.toggle('active', on);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  $('#nav-studio').href = S.lastStudio ? '#/studio/' + enc(S.lastStudio) : '#/studio';
}
async function route() {
  const tok = ++routeTok;
  const alive = () => tok === routeTok;
  const { name, arg } = parseHash();
  currentHash = location.hash;
  closePop();
  closeAllModals();
  if (cleanup) { try { cleanup(); } catch (e) { console.error(e); } cleanup = null; }
  S.studio = null;
  stopAudio();
  setNav(name);
  const main = $('#main');
  main.className = 'main view-' + name;
  main.removeAttribute('style');
  main.replaceChildren();
  main.scrollTop = 0;
  document.title = TITLES[name] + ' · Studio566';
  try {
    main.classList.remove('enter');
    const c = await VIEWS[name](main, alive, arg);
    if (alive()) { cleanup = c || null; setNav(name); main.classList.add('enter'); } else if (c) c();
  } catch (e) {
    if (!alive()) return;
    console.error(e);
    main.classList.add('view-pad');
    main.replaceChildren(errorState(e.message || String(e), () => route()));
  }
}
window.addEventListener('hashchange', async () => {
  if (ignoreHash) { ignoreHash = false; return; }
  const target = location.hash;
  const st = S.studio;
  if (st && st.dirty > 0 && !st.discard && target !== currentHash) {
    ignoreHash = true;
    history.replaceState(null, '', currentHash);
    ignoreHash = false;
    const ok = await confirmDialog('Bỏ thay đổi chưa lưu?', `Bạn có ${st.dirty} câu đã sửa nhưng chưa lưu. Rời Studio sẽ mất các thay đổi này.`, { okText: 'Rời trang', cancelText: 'Ở lại', danger: true });
    if (!ok) return;
    st.discard = true;
    location.hash = target;
    return;
  }
  route();
});
window.addEventListener('beforeunload', (e) => {
  if (S.studio && S.studio.dirty > 0) { e.preventDefault(); e.returnValue = ''; }
});
window.addEventListener('resize', closePop);

// ---- bảng lệnh nhanh
let paletteOpen = false;
async function openPalette() {
  if (paletteOpen) return;
  paletteOpen = true;
  const go = (h) => () => { location.hash = h; };
  const base = [
    { label: 'Trang chủ', icon: 'home', run: go('#/home') },
    { label: 'Dịch và lồng tiếng video mới', icon: 'play', run: go('#/new') },
    { label: 'Khám phá video thịnh hành', icon: 'compass', run: go('#/discover') },
    { label: 'Thư viện', icon: 'grid', run: go('#/library') },
    { label: 'Dọn dung lượng ổ đĩa', icon: 'wand', run: go('#/library') },
    { label: 'Hướng dẫn bắt đầu (3 bước)', icon: 'book', run: () => openOnboarding() },
    {
      label: 'Tải trước mô hình AI', icon: 'download', run: async () => {
        try {
          const r = await api('POST', '/api/models/prefetch');
          toast(r.nothing ? 'Mô hình AI đã có đủ trên máy' : 'Đang tải trước mô hình AI, xem tiến độ ở Trang chủ', 'success');
          pollSoon();
        } catch (e) { toast(e.message, 'error'); }
      },
    },
    { label: 'Thumbnail cho video vừa làm', icon: 'image', run: go('#/thumb') },
    { label: 'Ghép nhiều video', icon: 'merge', run: go('#/merge') },
    { label: 'Trình dựng tự do', icon: 'scissors', run: go('#/editor') },
    { label: 'Quy trình kéo thả: ý tưởng thành video', icon: 'layers', run: go('#/flow') },
    { label: 'Video kể chuyện từ ảnh', icon: 'film', run: go('#/story') },
    { label: 'Đọc văn bản thành giọng nói', icon: 'mic', run: go('#/voice') },
    { label: 'Cài đặt', icon: 'sliders', run: go('#/settings') },
    { label: 'Kết nối AI dịch', icon: 'key', run: go('#/settings') },
    { label: 'Bản quyền: gia hạn, nhập key mới', icon: 'shield', run: go('#/settings') },
    { label: 'Giới thiệu', icon: 'info', run: go('#/about') },
    { label: 'Phím tắt', hint: '?', icon: 'keyboard', run: () => openShortcuts() },
  ];
  const fromStudio = S.studio && S.studio.commands ? S.studio.commands() : [];
  let jobs = [];
  try { jobs = (await api('GET', '/api/jobs')).jobs || []; } catch (_) { /* vẫn dùng được lệnh khác */ }
  const all = [...fromStudio, ...base, ...jobs.map((j) => ({
    label: j.title_vi || j.title || j.id, hint: fmtDur(j.duration), icon: 'film', run: go('#/studio/' + enc(j.id)),
  }))];
  let sel = 0, shown = all;
  const inp = el('input', { class: 'cmdk-input', placeholder: 'Gõ lệnh hoặc tên video…', 'aria-label': 'Tìm lệnh', spellcheck: 'false', oninput: () => { sel = 0; paint(); } });
  const list = el('div', { class: 'cmdk-list', role: 'listbox' });
  const strip = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D').toLowerCase();
  function paint() {
    const q = strip(inp.value.trim());
    shown = q ? all.filter((c) => strip(c.label).includes(q)) : all;
    list.replaceChildren(...(shown.length ? shown.slice(0, 40).map((c, i) => el('button', {
      class: 'cmdk-item' + (i === sel ? ' active' : ''), role: 'option', onclick: () => exec(c),
      onmouseenter: () => { sel = i; [...list.children].forEach((x, k) => x.classList.toggle('active', k === sel)); },
    }, icon(c.icon), el('span', { class: 'cmdk-label', text: c.label }), c.hint ? el('span', { class: 'kbd', text: c.hint }) : null)) : [emptyState('Không có kết quả', '')]));
    const cur = list.children[sel];
    if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: 'nearest' });
  }
  function exec(c) { m.close(); setTimeout(() => c.run(), 30); }
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, Math.min(shown.length, 40) - 1); paint(); } else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); } else if (e.key === 'Enter') { e.preventDefault(); if (shown[sel]) exec(shown[sel]); }
  });
  const m = openModal([el('div', { class: 'cmdk-head' }, icon('search'), inp, el('span', { class: 'kbd', text: 'Esc' })), list], { cls: 'modal-cmdk', onClose: () => { paletteOpen = false; } });
  paint();
  setTimeout(() => inp.focus(), 30);
}

document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); return; }
  if (e.key !== 'Escape') return;
  if (closePop()) return;
  const m = modalStack[modalStack.length - 1];
  if (m && m.dismissable) { e.preventDefault(); m.close(); }
});

/** Có bản Studio566 mới trên GitHub: báo một lần mỗi lần mở app, kèm nút tải bản cài. */
async function checkAppUpdate() {
  try {
    const u = await api('GET', '/api/update');
    if (!u || !u.available) return;
    toast('Có bản Studio566 mới. Tải bản cài và cài đè lên, video và cài đặt vẫn giữ nguyên.', 'info', {
      timeout: 20000,
      actions: [{ label: 'Tải bản mới', primary: true, onClick: () => openExternal(u.download || u.page) }],
    });
  } catch (_) { /* không có mạng: bỏ qua */ }
}

async function boot() {
  // trước mọi thứ, kể cả màn Kích hoạt: máy chủ phải biết cửa sổ còn mở. Nối lại được thì vẽ lại trang đang báo lỗi mất kết nối
  startConn(() => { if ($('#main .empty.error')) route(); pollSoon(); });
  if (!location.hash || location.hash === '#' || location.hash === '#/') history.replaceState(null, '', '#/home');
  $('#cmdk-btn').addEventListener('click', () => openPalette());
  // bản phát hành chưa kích hoạt: chỉ hiện màn Kích hoạt, không gọi chức năng nào (máy chủ cũng chặn)
  licenseHooks.add((st) => { S.license = st; showLicenseGate(st); });
  try { S.license = await api('GET', '/api/license'); } catch (_) { S.license = null; }
  if (S.license && S.license.locked) { showLicenseGate(S.license); return; }
  loadStatus().then(() => route());
  checkAppUpdate();
  loadFonts();
  loadVoices();
  pollQueue();
  setInterval(loadStatus, 60000);
}
boot();
