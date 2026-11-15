/* Trang Tạo video: dán link / kéo thả file, chọn công thức, theo dõi hàng đợi. */
import {
  S, STAGE_LABEL, STATE_LABEL, Tape, api, busy, clone, confirmDialog, countLeaves, deepMerge, detectPlatform, diff, el, elapsed,
  enc, ensureConfig, fmtAgo, fmtDur, getPath, icon, langName, loadStatus, modalHead, openModal, platformBadge, pollSoon, promptDialog, queueListeners, reveal,
  runJob, same, setPath, shortSrc, toast, uploadFile, videoModal, copyText,
} from './core.js';
import { HelpPanel } from './fixes.js';
import { openAiPack } from './localai.js';
import { OptionsForm } from './options.js';

export const RECIPES = [
  {
    id: 'tiktok', name: 'TikTok dọc', desc: 'Khung 9:16 theo nhân vật, chữ nhấn từng âm tiết', icon: 'phone',
    options: { edit: { aspect: '9:16', fit: 'track', sub_style: 'tiktok' } },
  },
  {
    id: 'pop', name: 'Review sôi động', desc: 'Chữ hoa cỡ lớn, phóng to theo lời', icon: 'spark',
    options: { edit: { sub_style: 'pop' } },
  },
  {
    id: 'drama', name: 'Phim ngắn', desc: 'Mỗi nhân vật một giọng riêng, phụ đề kiểu phim', icon: 'film',
    options: { tts: { voice_mode: 'auto' }, edit: { sub_style: 'cinema' } },
  },
  {
    id: 'youtube', name: 'YouTube ngang', desc: 'Khung 16:9, phụ đề nền hộp', icon: 'monitor',
    options: { edit: { aspect: '16:9', fit: 'blur', sub_style: 'box' } },
  },
  {
    id: 'subs', name: 'Chỉ phụ đề', desc: 'Giữ tiếng gốc, không lồng tiếng', icon: 'sub',
    options: { tts: { enabled: false } },
  },
];

const mmss = (x) => { const t = Math.max(0, Math.round(Number(x) || 0)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`; };

/** Đọc nhật ký của một video, rút ra những điều người dùng nên biết ngay: đang chờ AI qua MCP, đoạn nghi thiếu lời, câu chưa đọc được. */
export function notesFromLogs(logs, state) {
  const L = Array.isArray(logs) ? logs : [];
  const out = [];
  let lastMcp = '';
  for (const l of L) if (l.startsWith('[mcp]')) lastMcp = l;
  if (state === 'running' && lastMcp.includes('Đang chờ AI qua MCP')) {
    out.push({ kind: 'wait', text: 'Đang chờ AI làm việc: mở Claude, ChatGPT hoặc Grok và nhắn "làm việc đang chờ".' });
  }
  const miss = [];
  let found = 0;
  for (const l of L) {
    const m = l.match(/^\[asr\] Nghe lại ([\d.]+)s đến ([\d.]+)s: (.*)$/);
    if (m) { if (m[3].startsWith('không có lời')) miss.push(`${mmss(m[1])}–${mmss(m[2])}`); else found += 1; }
  }
  if (found) out.push({ kind: 'ok', text: `Đã nghe lại ${found} đoạn nhạc nền to và tìm thêm được lời thoại.` });
  if (miss.length) out.push({ kind: 'warn', text: `Đoạn ${miss.slice(0, 4).join(', ')}${miss.length > 4 ? '…' : ''} có tiếng nhưng chưa nghe ra lời (thường do nhạc nền to). Nên xem lại đoạn này trong Studio.` });
  for (const l of L) {
    const m = l.match(/^\[asr\] (\d+) câu nên soát lại/);
    if (m) out.push({ kind: 'warn', text: `${m[1]} câu app chưa chắc chắn, được tô vàng trong Studio. Mở Studio, bấm nút Cần xem để soát nhanh.` });
  }
  for (const l of L) {
    let m = l.match(/^\[tts\] CẢNH BÁO: (\d+) câu chưa đọc được/);
    if (m) out.push({ kind: 'warn', text: `${m[1]} câu chưa đọc được (có phụ đề nhưng không có tiếng). Mở Studio, bấm Đọc lại ở các câu đó.` });
    m = l.match(/^\[tts\] CẢNH BÁO: (\d+) câu đọc lệch sau hình hơn 0,6 giây \(câu trước quá dài\): (.+?)(?:\.\s|\s\.\.\.|$)/);
    if (m) out.push({ kind: 'warn', text: `${m[1]} câu đọc chậm hơn hình (ở ${m[2].split(', ').slice(0, 4).join(', ')}). Rút gọn câu đứng trước các mốc này trong Studio.` });
  }
  return out;
}

function summaryOf(v) {
  const style = { classic: 'Cổ điển', cinema: 'Phim', box: 'Nền hộp', tiktok: 'TikTok', karaoke: 'Karaoke', pop: 'Pop' }[getPath(v, 'edit.sub_style')] || 'Cổ điển';
  const mode = { inpaint: 'xóa sạch', blur: 'làm mờ', band: 'dải tối' }[getPath(v, 'edit.hardsub_mode')] || 'xóa sạch';
  const hs = getPath(v, 'edit.blur_hardsub');
  const tts = getPath(v, 'tts.enabled') === false ? 'Không lồng tiếng'
    : { auto: 'Mỗi người một giọng', per_line: 'Giọng theo từng câu', fixed: 'Một giọng cố định', clone: 'Bắt chước giọng gốc' }[getPath(v, 'tts.voice_mode')] || 'Giọng tự chọn';
  const aspect = getPath(v, 'edit.aspect');
  const lang = getPath(v, 'translate.target_lang') || 'vi';
  return [
    ...(lang !== 'vi' ? [['globe', langName(lang)]] : []),
    ['mic', tts], ['sub', 'Phụ đề ' + style],
    ['scan', hs === false || hs === 'false' ? 'Giữ sub gốc' : 'Sub gốc: ' + mode],
    ['crop', aspect && aspect !== 'keep' ? 'Khung ' + aspect : 'Giữ khung gốc'],
  ];
}

export function QueueCard(it0) {
  const img = el('img', { alt: '' });
  const thumb = el('div', { class: 'q-thumb' }, icon('film', 'q-thumb-ph'), img);
  img.addEventListener('load', () => thumb.classList.add('has-img'));
  img.addEventListener('error', () => thumb.classList.remove('has-img'));
  const title = el('div', { class: 'q-title' });
  const sub = el('div', { class: 'q-sub' });
  const badge = el('span', { class: 'state' });
  const time = el('span', { class: 'q-time mono', title: 'Thời gian chạy' });
  const tape = Tape();
  const pct = el('span', { class: 'q-pct mono' });
  const msg = el('div', { class: 'q-msg' });
  const helpBox = el('div', { class: 'q-help', hidden: true });
  const notesBox = el('div', { class: 'q-notes', hidden: true });
  let lastNotes = '';
  const errPre = el('pre', { class: 'logbox err' });
  const errBox = el('details', { class: 'q-err', hidden: true }, el('summary', {}, 'Chi tiết lỗi'), errPre);
  const logPre = el('pre', { class: 'logbox' });
  const logBox = el('details', { class: 'q-log' }, el('summary', {}, 'Xem nhật ký'), logPre);
  const actions = el('div', { class: 'q-actions' });
  const root = el('div', { class: 'q-card' }, thumb,
    el('div', { class: 'q-main' },
      el('div', { class: 'q-top' }, el('div', { class: 'q-titles' }, title, sub), el('div', { class: 'q-right' }, time, badge)),
      tape.root,
      el('div', { class: 'q-status' }, msg, pct),
      notesBox,
      helpBox,
      errBox,
      el('div', { class: 'q-foot' }, logBox, actions)));
  let lastKey = null, lastThumb = '', lastLog = null, lastHelp = '';
  const card = { root, item: it0, update };
  // nút trong khung Cách khắc phục luôn dùng bản mới nhất của mục (nhật ký để chép gửi tác giả)
  const helpCtx = { get item() { return card.item; }, retry: () => retryIt(card.item) };

  /** Chạy lại mục lỗi: lượt xuất thêm thử lại đúng lượt đó; lỗi ngay bước tải (chưa có job) thì xếp lại đúng link và tùy chọn cũ. */
  async function retryIt(it) {
    if (!it.job) {
      await api('POST', `/api/queue/${enc(it.qid)}/retry`);
      pollSoon();
    } else {
      // lượt xuất thêm phải thử lại đúng lượt đó: chạy lại bản chính sẽ không ra clip nào và làm mất danh sách đã xuất
      const isExport = [it.targets, it.clips, it.profiles].some((x) => x && x.length);
      if (it.editor_base && !isExport) { await api('POST', `/api/editor/jobs/${enc(it.job)}/prepare`); pollSoon(); } else if (isExport) { await api('POST', `/api/jobs/${enc(it.job)}/export`, { targets: it.targets || [], clips: it.clips || [], profiles: it.profiles || [], clip_profile: it.clip_profile || '' }); pollSoon(); } else await runJob(it.job, it.from_stage || null);
    }
    toast('Đã thêm lại vào hàng đợi', 'success');
  }
  if (it0.kind === 'merge' || it0.kind === 'prefetch') tape.root.hidden = true;

  function buildActions(it) {
    const out = [];
    const active = it.state === 'queued' || it.state === 'running';
    if (active) {
      const b = el('button', {
        class: 'btn btn-sm btn-danger', onclick: () => busy(b, async () => {
          await api('POST', `/api/queue/${enc(it.qid)}/cancel`);
          toast('Đã gửi lệnh hủy', 'info');
          pollSoon();
        }),
      }, icon('x'), 'Hủy');
      out.push(b);
    }
    if (it.state === 'done' && it.kind === 'merge') out.push(el('a', { class: 'btn btn-sm btn-primary', href: '#/merge' }, icon('merge'), 'Xem bản ghép'));
    if (it.kind === 'story' && it.story) out.push(el('a', { class: 'btn btn-sm' + (it.state === 'done' ? ' btn-primary' : ''), href: '#/story/' + enc(it.story) }, icon('film'), 'Mở câu chuyện'));
    if (it.state === 'done' && it.job) {
      out.push(el('a', { class: 'btn btn-sm btn-primary', href: '#/studio/' + enc(it.job) }, icon('sliders'), 'Mở Studio'));
      out.push(el('button', { class: 'btn btn-sm', onclick: () => videoModal(`/api/jobs/${enc(it.job)}/media/final.mp4?t=${Date.now()}`, it.title) }, icon('play'), 'Xem'));
      out.push(el('button', { class: 'btn btn-sm btn-ghost', onclick: () => reveal(it.job) }, icon('folder'), 'Thư mục'));
    }
    const ended = it.state === 'error' || it.state === 'cancelled';
    // khung Cách khắc phục đã có nút Thử lại thì không lặp lại ở đây
    const helpRetry = it.state === 'error' && it.help && (it.help.actions || []).some((a) => a.id === 'retry');
    if (ended && (it.job || !it.kind || it.kind === 'video' || it.kind === 'prefetch') && !helpRetry) {
      const b = el('button', { class: 'btn btn-sm', onclick: () => busy(b, () => retryIt(it)) }, icon('refresh'), 'Thử lại');
      out.push(b);
    }
    if (ended && it.job) {
      out.push(el('a', { class: 'btn btn-sm btn-ghost', href: '#/studio/' + enc(it.job) }, icon('sliders'), 'Studio'));
      if (it.state === 'error' && String(it.error || '').includes('Cài đặt')) out.unshift(el('a', { class: 'btn btn-sm btn-primary', href: '#/settings' }, icon('key'), 'Kết nối AI'));
    }
    if (!active) {
      const b = el('button', {
        class: 'btn btn-sm btn-icon btn-ghost', title: 'Xóa khỏi hàng đợi', 'aria-label': 'Xóa khỏi hàng đợi',
        onclick: () => busy(b, async () => { await api('DELETE', `/api/queue/${enc(it.qid)}`); root.remove(); pollSoon(); }),
      }, icon('trash'));
      out.push(b);
    }
    return out;
  }

  function update(it) {
    card.item = it;
    const st = it.state;
    root.dataset.state = st;
    title.textContent = it.title || shortSrc(it.src) || it.job || 'Video';
    title.title = it.title || it.src || '';
    sub.textContent = it.title && it.title !== it.src ? shortSrc(it.src) : '';
    badge.textContent = STATE_LABEL[st] || st;
    badge.className = 'state st-' + st;
    time.textContent = elapsed(it);
    const p = typeof it.progress === 'number' ? it.progress : null;
    tape.set(it.stage, st, p);
    pct.textContent = st === 'running' && p != null ? Math.round(p * 100) + '%' : '';
    if (st === 'error') {
      msg.className = 'q-msg err wrap' + (it.help ? ' q-help-title' : '');
      // nhận ra lỗi thì hiện tên lỗi dễ hiểu, lỗi gốc nằm trong Chi tiết lỗi
      msg.textContent = it.help ? it.help.title : String(it.error || it.message || 'Lỗi không rõ').split('\n')[0];
    } else {
      msg.className = 'q-msg';
      msg.textContent = st === 'queued' ? 'Đang chờ tới lượt…' : st === 'done' ? (it.output ? 'Đã xuất: ' + it.output : 'Hoàn tất')
        : st === 'cancelled' ? 'Đã hủy' : (it.message || STAGE_LABEL[it.stage] || 'Đang xử lý…');
    }
    msg.title = msg.textContent;
    errBox.hidden = !(st === 'error' && it.error);
    const hk = st === 'error' && it.help ? JSON.stringify(it.help) : '';
    if (hk !== lastHelp) { lastHelp = hk; helpBox.replaceChildren(hk ? HelpPanel(it.help, helpCtx) : ''); helpBox.hidden = !hk; }
    if (st === 'error' && it.error && errPre.textContent !== it.error) errPre.textContent = it.error;
    const ready = it.job && !(st === 'running' && (!it.stage || it.stage === 'download')) && st !== 'queued';
    if (ready) {
      const u = `/api/jobs/${enc(it.job)}/thumb.jpg?s=${st === 'done' ? 'd' : 'r'}`;
      if (u !== lastThumb) { lastThumb = u; img.src = u; }
    }
    const notes = notesFromLogs(it.logs, st);
    const nk = JSON.stringify(notes);
    if (nk !== lastNotes) {
      lastNotes = nk;
      notesBox.hidden = !notes.length;
      notesBox.replaceChildren(...notes.map((n) => el('div', { class: 'q-note q-note-' + n.kind },
        icon(n.kind === 'warn' ? 'alert' : n.kind === 'ok' ? 'check' : 'clock'), el('span', { text: n.text }),
        n.kind === 'wait' ? el('button', { class: 'btn btn-xs', onclick: () => copyText('làm việc đang chờ', 'Đã chép câu nhắn, dán vào AI') }, icon('copy'), 'Chép câu nhắn') : null)));
    }
    const lg = (Array.isArray(it.logs) ? it.logs : []).slice(-200).join('\n');
    if (lg !== lastLog) {
      const atBottom = logPre.scrollTop + logPre.clientHeight >= logPre.scrollHeight - 24;
      logPre.textContent = lg || '(chưa có nhật ký)';
      if (atBottom) logPre.scrollTop = logPre.scrollHeight;
      lastLog = lg;
    }
    const key = st + '|' + (it.job || '') + '|' + (it.help ? it.help.code : '');
    if (key !== lastKey) { lastKey = key; actions.replaceChildren(...buildActions(it)); }
  }
  update(it0);
  return card;
}

export async function viewNew(main, alive) {
  await ensureConfig();
  if (!alive()) return null;
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('ic.newOptions') || '{}') || {}; } catch (_) { saved = {}; }
  let userRecipes = [];
  try { userRecipes = (await api('GET', '/api/presets')).presets || []; } catch (_) { /* không có cũng được */ }
  if (!alive()) return null;
  const vals = deepMerge(clone(S.config), saved);
  const overrides = () => diff(vals, S.config) || {};
  const persist = () => {
    localStorage.setItem('ic.newOptions', JSON.stringify(overrides()));
    paintSummary();
    paintRecipes();
    paintGo();
  };

  // ------------------------------------------------ ô nhập
  const ta = el('textarea', {
    class: 'drop-input', rows: 4, spellcheck: 'false', 'aria-label': 'Link video',
    placeholder: 'Dán link hoặc nguyên đoạn chia sẻ, mỗi dòng một video\nhttps://www.bilibili.com/video/BV1xx411c7XX\n7.43 复制打开抖音，看看【…】 https://v.douyin.com/…',
    oninput: () => updSources(),
    onkeydown: (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); start(); } },
  });
  const detected = el('div', { class: 'detected' });
  const startBtn = el('button', { class: 'btn btn-primary btn-lg', onclick: () => start() }, icon('play'), 'Bắt đầu');
  const pasteBtn = el('button', {
    class: 'btn btn-ghost', title: 'Dán từ clipboard', onclick: async () => {
      try {
        const t = await navigator.clipboard.readText();
        if (t) { ta.value = (ta.value.trim() ? ta.value.trimEnd() + '\n' : '') + t.trim(); updSources(); ta.focus(); }
      } catch (_) { toast('Trình duyệt không cho đọc clipboard, hãy nhấn Ctrl+V vào ô nhập', 'warn'); }
    },
  }, icon('paste'), 'Dán');
  const filePick = el('input', { type: 'file', accept: 'video/*,.mkv,.flv', multiple: true, hidden: true, onchange: () => { addFiles([...filePick.files]); filePick.value = ''; } });
  const fileBtn = el('button', { class: 'btn btn-ghost', title: 'Chọn video trên máy', onclick: () => filePick.click() }, icon('upload'), 'Chọn file');
  // nút "Dùng file video có sẵn" trên thẻ lỗi (fixes.js) mở hộp chọn file của trang này
  const onPick = () => { if (!alive()) { window.removeEventListener('ic:pick-file', onPick); return; } filePick.click(); };
  window.addEventListener('ic:pick-file', onPick);
  const uploads = el('div', { class: 'uploads' });
  // thị trường: dịch và lồng tiếng sang ngôn ngữ nào (lưu cho các lượt sau như mọi tùy chọn của trang này)
  const langSel = el('select', {
    class: 'input input-sm lang-pick', title: 'Dịch và lồng tiếng sang', 'aria-label': 'Dịch và lồng tiếng sang',
    onchange: () => { setPath(vals, 'translate.target_lang', langSel.value); persist(); },
  }, (S.langs.length ? S.langs : [{ code: 'vi', name: 'Tiếng Việt' }]).map((l) => el('option', { value: l.code }, l.name)));
  langSel.value = getPath(vals, 'translate.target_lang') || 'vi';
  const langPick = el('label', { class: 'lang-wrap' }, icon('globe'), el('span', { class: 'small muted', text: 'Lồng tiếng sang' }), langSel);

  const drop = el('div', { class: 'drop' },
    ta, uploads,
    el('div', { class: 'drop-foot' }, detected, el('span', { class: 'grow' }), filePick, fileBtn, pasteBtn),
    el('div', { class: 'drop-veil' }, icon('upload'), el('span', { text: 'Thả video vào đây' })));
  drop.addEventListener('dragover', (e) => { if ([...e.dataTransfer.types].includes('Files')) { e.preventDefault(); drop.classList.add('over'); } });
  drop.addEventListener('dragleave', (e) => { if (!drop.contains(e.relatedTarget)) drop.classList.remove('over'); });
  drop.addEventListener('drop', (e) => {
    drop.classList.remove('over');
    const files = [...e.dataTransfer.files].filter((f) => f.type.startsWith('video/') || /\.(mkv|flv|mov|avi|webm|mp4|m4v)$/i.test(f.name));
    if (e.dataTransfer.files.length) e.preventDefault();
    if (files.length) addFiles(files); else if (e.dataTransfer.files.length) toast('Chỉ nhận file video', 'warn');
  });
  async function addFiles(files) {
    for (const f of files) {
      const bar = el('span', { class: 'up-bar' });
      const row = el('div', { class: 'up-row' }, icon('file'), el('span', { class: 'up-name', text: f.name }), el('span', { class: 'up-track' }, bar));
      uploads.append(row);
      try {
        const r = await uploadFile('video', f, (x) => { bar.style.width = Math.round(x * 100) + '%'; });
        ta.value = (ta.value.trim() ? ta.value.trimEnd() + '\n' : '') + r.path;
        updSources();
      } catch (e) { toast(`${f.name}: ${e.message}`, 'error'); }
      row.remove();
    }
  }
  function sources() { return ta.value.split(/\r?\n/).map((x) => x.trim().replace(/^"(.*)"$/, '$1')).filter(Boolean); }
  function updSources() {
    const src = sources();
    const counts = {};
    for (const s of src) { const p = detectPlatform(s) || 'web'; counts[p] = (counts[p] || 0) + 1; }
    detected.replaceChildren(...Object.entries(counts).map(([p, n]) => el('span', { class: 'det' }, platformBadge(p), n > 1 ? el('span', { class: 'muted small', text: '×' + n }) : null)));
    if (!src.length) detected.append(el('span', { class: 'muted small', text: 'Douyin, Bilibili, Kuaishou, Xiaohongshu, Weibo, Xigua… hoặc kéo thả file video' }));
    startBtn.replaceChildren(icon('play'), src.length > 1 ? `Bắt đầu ${src.length} video` : 'Bắt đầu làm video');
    paintGo();
  }
  async function start() {
    const src = sources();
    if (!src.length) { toast('Hãy dán ít nhất một link hoặc chọn file', 'warn'); ta.focus(); return; }
    await busy(startBtn, async () => {
      const r = await api('POST', '/api/queue', { sources: src, options: overrides(), from_stage: null });
      toast(`Đã thêm ${(r && r.qids && r.qids.length) || src.length} video vào hàng đợi`, 'success');
      ta.value = '';
      updSources();
      pollSoon();
    });
    updSources();
  }

  // ------------------------------------------------ công thức
  const recipeRow = el('div', { class: 'recipes' });
  const applied = (r) => {
    const flat = (o, pre = '') => Object.entries(o).flatMap(([k, v]) => (v && typeof v === 'object' && !Array.isArray(v) ? flat(v, pre + k + '.') : [[pre + k, v]]));
    return flat(r.options || {}).every(([k, v]) => same(getPath(vals, k), v));
  };
  function applyRecipe(r) {
    const on = applied(r);
    if (on) {
      const flat = (o, pre = '') => Object.entries(o).flatMap(([k, v]) => (v && typeof v === 'object' && !Array.isArray(v) ? flat(v, pre + k + '.') : [[pre + k, v]]));
      for (const [k] of flat(r.options)) setPath(vals, k, clone(getPath(S.config, k)));
    } else {
      deepMerge(vals, clone(r.options));
    }
    persist();
  }
  function paintRecipes() {
    const card = (r, user) => el('button', { type: 'button', class: 'recipe' + (applied(r) ? ' active' : ''), onclick: () => applyRecipe(r) },
      el('span', { class: 'recipe-top' }, icon(r.icon || 'book'), el('span', { class: 'recipe-name', text: r.name }),
        user ? el('span', {
          class: 'recipe-x', role: 'button', title: 'Xóa công thức này', 'aria-label': 'Xóa công thức này', onclick: async (e) => {
            e.stopPropagation();
            if (!await confirmDialog('Xóa công thức?', `Xóa công thức "${r.name}".`, { okText: 'Xóa', danger: true })) return;
            userRecipes = userRecipes.filter((x) => x !== r);
            busy(null, async () => { await api('PUT', '/api/presets', { presets: userRecipes }); paintRecipes(); });
          },
        }, icon('x')) : null),
      el('span', { class: 'recipe-desc', text: r.desc || 'Công thức của bạn' }));
    recipeRow.replaceChildren(
      ...RECIPES.map((r) => card(r, false)),
      ...userRecipes.map((r) => card(r, true)),
      el('button', {
        type: 'button', class: 'recipe recipe-add', title: 'Lưu tùy chọn hiện tại thành công thức', onclick: async () => {
          const o = overrides();
          if (!countLeaves(o)) { toast('Hãy chọn hoặc tùy chỉnh trước, rồi lưu lại thành công thức', 'info'); return; }
          const name = await promptDialog('Lưu công thức', 'Tên công thức', { placeholder: 'Ví dụ: Kênh review đồ ăn' });
          if (!name) return;
          userRecipes = [...userRecipes.filter((x) => x.name !== name), { name, options: o, icon: 'book' }];
          busy(null, async () => { await api('PUT', '/api/presets', { presets: userRecipes }); paintRecipes(); toast('Đã lưu công thức', 'success'); });
        },
      }, icon('plus'), el('span', { text: 'Lưu công thức' })));
  }
  const summary = el('div', { class: 'summary' });
  function paintSummary() {
    summary.replaceChildren(...summaryOf(vals).map(([ic, t]) => el('span', { class: 'sum-chip' }, icon(ic), t)));
  }
  // tùy chọn chi tiết gập vào "Tùy chỉnh nâng cao", chỉ dựng khi mở lần đầu
  let advForm = null;
  const advBody = el('div', { class: 'nv-adv-body' });
  const adv = el('details', {
    class: 'nv-adv', ontoggle: () => {
      if (!adv.open || advForm) return;
      advForm = OptionsForm({ vals, base: S.config, groups: ['translate', 'voice', 'subs', 'picture', 'sound'], storeKey: 'new', onChange: persist });
      advBody.replaceChildren(
        el('p', { class: 'muted small', text: 'Chỉ áp dụng cho các video bạn sắp thêm. Muốn đổi lâu dài thì vào Cài đặt.' }),
        advForm.root,
        el('div', { class: 'nv-adv-foot' }, el('button', { class: 'btn btn-sm btn-ghost', onclick: () => { advForm.reset(); persist(); } }, icon('undo'), 'Về cài đặt chung')));
    },
  }, el('summary', { class: 'nv-adv-sum' }, icon('sliders'), el('span', { class: 'nv-adv-t', text: 'Tùy chỉnh nâng cao' }), summary, icon('chev', 'nv-adv-chev')), advBody);

  // bước 3: tóm tắt và nút bắt đầu
  const goInfo = el('div', { class: 'nv-go-info' });
  function paintGo() {
    const n = sources().length;
    const rec = [...RECIPES, ...userRecipes].filter((r) => applied(r)).map((r) => r.name);
    const lang = langName(getPath(vals, 'translate.target_lang') || 'vi');
    goInfo.replaceChildren(
      el('b', { text: n ? `${n} video` : 'Chưa có video nào' }),
      el('span', { class: 'dim', text: ` · Lồng tiếng ${lang}` + (rec.length ? ` · ${rec.join(', ')}` : ' · Theo cài đặt chung') }));
    step1.classList.toggle('done', n > 0);
    step3.classList.toggle('ready', n > 0);
  }
  const stepHead = (n, title, sub) => el('div', { class: 'nv-step-head' }, el('span', { class: 'nv-n' }, el('span', { text: String(n) }), icon('check')),
    el('div', { class: 'nv-step-t' }, el('h2', { text: title }), sub ? el('p', { class: 'dim small', text: sub }) : null));
  const step1 = el('section', { class: 'nv-step' });
  const step3 = el('section', { class: 'nv-step nv-step-go' });
  function openOptions() {
    const form = OptionsForm({ vals, base: S.config, groups: ['translate', 'voice', 'subs', 'picture', 'sound'], storeKey: 'new', onChange: persist });
    const m = openModal([
      modalHead('sliders', 'Tùy chỉnh cho lượt này', () => m),
      el('div', { class: 'modal-body' }, el('p', { class: 'muted small', text: 'Chỉ áp dụng cho các video bạn sắp thêm. Muốn đổi lâu dài thì vào Cài đặt.' }), form.root),
      el('div', { class: 'modal-foot' },
        el('div', { class: 'left' }, el('button', { class: 'btn btn-ghost', onclick: () => { form.reset(); persist(); } }, icon('undo'), 'Về cài đặt chung')),
        el('button', { class: 'btn btn-primary', onclick: () => m.close() }, 'Xong')),
    ], { drawer: true });
  }

  // ------------------------------------------------ hàng đợi + gần đây
  const qList = el('div', { class: 'queue-list' });
  const qHead = el('div', { class: 'section-head' }, el('h2', { text: 'Đang xử lý' }), el('span', { class: 'grow' }));
  const clearBtn = el('button', {
    class: 'btn btn-sm btn-ghost', hidden: true, onclick: () => busy(clearBtn, async () => {
      const fin = S.queue.filter((i) => ['done', 'error', 'cancelled'].includes(i.state));
      for (const i of fin) { try { await api('DELETE', `/api/queue/${enc(i.qid)}`); } catch (_) { /* bỏ qua */ } }
      pollSoon();
    }),
  }, icon('trash'), 'Dọn mục đã xong');
  qHead.append(clearBtn);
  const qWrap = el('section', { class: 'q-wrap', hidden: true }, qHead, qList);
  const cards = new Map();
  function renderQueue(items) {
    const seen = new Set();
    items.forEach((it, i) => {
      let c = cards.get(it.qid);
      if (!c) { c = QueueCard(it); cards.set(it.qid, c); } else c.update(it);
      seen.add(it.qid);
      if (qList.children[i] !== c.root) qList.insertBefore(c.root, qList.children[i] || null);
    });
    for (const [q, c] of cards) if (!seen.has(q)) { c.root.remove(); cards.delete(q); }
    qWrap.hidden = !items.length;
    clearBtn.hidden = !items.some((i) => ['done', 'error', 'cancelled'].includes(i.state));
  }

  const recent = el('section', { class: 'recent', hidden: true });
  async function loadRecent() {
    try {
      const jobs = (await api('GET', '/api/jobs')).jobs || [];
      if (!alive()) return;
      recent.hidden = !jobs.length;
      recent.replaceChildren(
        el('div', { class: 'section-head' }, el('h2', { text: 'Gần đây' }), el('span', { class: 'grow' }), el('a', { class: 'btn btn-sm btn-ghost', href: '#/library' }, 'Xem tất cả', icon('next'))),
        el('div', { class: 'recent-row' }, jobs.slice(0, 6).map((j) => el('a', { class: 'recent-card', href: '#/studio/' + enc(j.id), title: j.title },
          el('span', { class: 'recent-thumb' }, el('img', { alt: '', loading: 'lazy', src: j.thumb }), j.duration ? el('span', { class: 'jc-dur mono', text: fmtDur(j.duration) }) : null),
          el('span', { class: 'recent-title', text: j.title_vi || j.title }),
          el('span', { class: 'dim small', text: fmtAgo(j.created) })))));
    } catch (_) { /* không ảnh hưởng trang */ }
  }

  // ------------------------------------------------ cảnh báo chưa kết nối AI
  const tr = S.status && S.status.translator;
  const offlineBtn = (label) => el('button', { class: 'btn btn-sm btn-primary', onclick: (e) => { e.preventDefault(); openAiPack('translate', { onReady: () => loadStatus() }); } }, icon('download'), label);
  let aiBanner = null;
  if (tr && !tr.ready) {
    aiBanner = el('div', { class: 'banner banner-plain' }, icon('key'),
      el('div', {}, el('b', { text: 'Chưa có cách dịch chắc chắn. ' }), 'Google dịch miễn phí hay chặn. Tải Dịch offline (1,2 GB, không cần key, dịch ngay trên máy), hoặc kết nối AI để dịch tự nhiên, đúng xưng hô nhất.'),
      el('div', { class: 'banner-acts' }, offlineBtn('Tải Dịch offline'), el('a', { class: 'btn btn-sm', href: '#/settings' }, 'Kết nối AI')));
  } else if (tr && tr.chosen_ready && S.status && !S.status.offline && localStorage.getItem('ic.hide.offlinehint') !== '1') {
    const hide = el('button', { class: 'btn btn-xs btn-ghost', title: 'Ẩn gợi ý này', 'aria-label': 'Ẩn gợi ý này', onclick: () => { try { localStorage.setItem('ic.hide.offlinehint', '1'); } catch (_) { /* bỏ qua */ } aiBanner.remove(); } }, icon('x'));
    aiBanner = el('div', { class: 'banner banner-plain' }, icon('globe'),
      el('div', {}, el('b', { text: 'Dự phòng khi AI quá tải. ' }), 'Gemini gói miễn phí hay quá tải hoặc hết lượt trong ngày. Có Dịch offline (1,2 GB) thì Studio566 tự dịch tiếp ngay trên máy, video không bị dừng.'),
      el('div', { class: 'banner-acts' }, offlineBtn('Tải Dịch offline'), hide));
  }

  const dl = (S.status && S.status.downloads) || [];
  const dlBanner = dl.length ? el('div', { class: 'banner banner-plain' }, icon('download'),
    el('div', {}, el('b', { text: `Lần chạy đầu sẽ tải khoảng ${(dl.reduce((n, x) => n + x.mb, 0) / 1000).toFixed(1).replace('.', ',')} GB mô hình AI. ` }),
      'Chỉ tải một lần, hãy giữ kết nối mạng: ', dl.map((x) => x.name).join(', '), '.')) : null;

  main.append(
    el('div', { class: 'home' },
      el('header', { class: 'hero' },
        el('div', { class: 'eyebrow', text: 'Dịch & lồng tiếng video Trung Quốc' }),
        el('h1', { text: 'Dịch video trong 3 bước' }),
        el('p', { class: 'hero-sub', text: 'Tự tải video, xóa sub Trung, nhận dạng lời thoại, dịch đúng ngữ cảnh, lồng tiếng Việt hoặc tiếng nước ngoài (Anh, Indonesia, Thái...) khớp từng câu và dựng thành video sẵn sàng đăng.' })),
      aiBanner,
      dlBanner,
      el('div', { class: 'nv-steps' },
        (step1.append(stepHead(1, 'Chọn video', 'Dán link hoặc kéo thả file, mỗi dòng một video'), drop), step1),
        el('section', { class: 'nv-step' }, stepHead(2, 'Chọn kiểu video', 'Bấm một công thức: Studio566 tự đặt khung hình, phụ đề và giọng đọc cho hợp'),
          el('div', { class: 'nv-lang' }, langPick), recipeRow, adv),
        (step3.append(stepHead(3, 'Bắt đầu'), el('div', { class: 'nv-go' }, goInfo, el('span', { class: 'grow' }),
          el('span', { class: 'dim small nv-kbd', text: 'Ctrl + Enter' }), startBtn)), step3)),
      qWrap,
      recent));
  updSources();
  paintRecipes();
  paintSummary();
  paintGo();
  renderQueue(S.queue);
  loadRecent();
  let doneCount = S.queue.filter((i) => i.state === 'done').length;
  const onQ = (items) => {
    renderQueue(items);
    const n = items.filter((i) => i.state === 'done').length;
    if (n !== doneCount) { doneCount = n; loadRecent(); }
  };
  queueListeners.add(onQ);
  setTimeout(() => ta.focus(), 50);
  const tick = setInterval(() => { for (const c of cards.values()) if (c.item.state === 'running') c.update(c.item); }, 1000);
  // link dán ở Trang chủ: điền sẵn vào ô nhập
  const pre = sessionStorage.getItem('s566.prefill');
  if (pre) { sessionStorage.removeItem('s566.prefill'); ta.value = pre; updSources(); setTimeout(() => ta.focus(), 30); }
  return () => { queueListeners.delete(onQ); clearInterval(tick); };
}
