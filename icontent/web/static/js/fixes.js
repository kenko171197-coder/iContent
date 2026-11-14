/* Cách khắc phục: khung chỉ dẫn trên thẻ lỗi, nút sửa ngay, trình hướng dẫn nạp cookie, chép thông tin lỗi gửi tác giả.
   Máy chủ nhận ra lỗi (icontent/fixes.py) và gửi kèm {code, title, why, steps, actions}; file này chỉ vẽ và chạy các nút. */
import {
  S, STAGE_LABEL, api, busy, confirmDialog, el, enc, errorHooks, fmtAgo, icon, modalHead, openModal, pollSoon, toast,
} from './core.js';
import { openAiPack } from './localai.js';

const SITE_NAMES = { douyin: 'Douyin', bilibili: 'Bilibili', kuaishou: 'Kuaishou', xiaohongshu: 'Xiaohongshu' };
const SITE_HOME = { douyin: 'https://www.douyin.com/', bilibili: 'https://www.bilibili.com/', kuaishou: 'https://www.kuaishou.com/', xiaohongshu: 'https://www.xiaohongshu.com/explore' };
const SITE_FILE = { douyin: 'www.douyin.com_cookies.txt', bilibili: 'www.bilibili.com_cookies.txt', kuaishou: 'www.kuaishou.com_cookies.txt', xiaohongshu: 'www.xiaohongshu.com_cookies.txt' };
const EXT = {
  chrome: 'https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc',
  firefox: 'https://addons.mozilla.org/firefox/addon/get-cookies-txt-locally/',
};
// nút cần một mục trong hàng đợi (thử lại đúng video đó); lỗi hiện bằng thông báo nổi thì bỏ
const NEED_ITEM = new Set(['retry', 'pick_file']);

/** Bỏ tên người dùng Windows và mã bí mật trước khi khách gửi thông tin lỗi cho người khác (giống fixes.anonymize). */
export function anonymize(t) {
  return String(t || '')
    .replace(/([a-z]:[\\/]+users[\\/]+)[^\\/\s"']+/gi, '$1…')
    .replace(/(api[_-]?key|token|sessdata|s_v_web_id|authorization)(["'=: ]+)[^\s"'&]+/gi, '$1$2…');
}

/** Mở trang trên trình duyệt mặc định của khách (có tiện ích và cookie của họ), không phải cửa sổ iContent. */
export async function openExternal(url) {
  try { await api('POST', '/api/fixes/open', { url }); } catch (e) { toast(e.message, 'error'); }
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (_) {
    const ta = el('textarea', { style: { position: 'fixed', opacity: '0' } }, text);
    document.body.append(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
    ta.remove();
    return ok;
  }
}

export async function copyReport(ctx = {}) {
  const it = ctx.item || {};
  const h = ctx.help || it.help;
  const lines = [
    `iContent ${(S.status && S.status.version) || ''} · ${new Date().toLocaleString('vi-VN')}`,
    h ? `Lỗi: ${h.title}` : '',
    it.src || ctx.src ? `Link: ${it.src || ctx.src}` : '',
    it.stage ? `Bước: ${STAGE_LABEL[it.stage] || it.stage}` : '',
    '', 'Chi tiết:', String(ctx.error || it.error || '').trim(),
  ];
  const logs = Array.isArray(it.logs) ? it.logs.slice(-40) : [];
  if (logs.length) lines.push('', 'Nhật ký (40 dòng cuối):', ...logs);
  const ok = await copyText(anonymize(lines.filter((x, i) => x !== '' || i > 3).join('\n')));
  toast(ok ? 'Đã chép thông tin lỗi (đã bỏ tên máy). Dán vào Zalo/Telegram gửi cho tác giả.' : 'Không chép được, hãy mở Chi tiết lỗi rồi bôi đen để chép', ok ? 'success' : 'warn', { timeout: 6000 });
}

/** Gói báo lỗi (zip ra màn hình nền): kết quả kiểm tra máy + nhật ký, đã bỏ key, cookie, tên máy. */
export async function supportPack(note = '') {
  toast('Đang tạo gói báo lỗi…', 'info', { timeout: 20000 });
  const r = await api('POST', '/api/support/report', { note });
  toast(`Đã lưu ${r.name} ra màn hình nền. Gửi file này cho người hỗ trợ qua Zalo hoặc Telegram.`, 'success', { timeout: 12000 });
  return r;
}

async function retryItem(it) {
  if (!it || !it.qid) return;
  await api('POST', `/api/queue/${enc(it.qid)}/retry`);
  toast('Đã thêm lại vào hàng đợi', 'success');
  pollSoon();
}

/** Chạy một nút trong lời chỉ dẫn. ctx: {item, error, help, close} */
export async function runAction(a, ctx = {}) {
  const it = ctx.item;
  switch (a.id) {
    case 'retry': return ctx.retry ? ctx.retry() : retryItem(it);
    case 'pick_file':
      if (location.hash.startsWith('#/new')) {
        document.querySelector('.drop')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        window.dispatchEvent(new CustomEvent('ic:pick-file'));
      } else {
        location.hash = '#/new';
        toast('Bấm Chọn file (hoặc kéo video vào ô Dán link) để dùng video đã tải sẵn trên máy', 'info', { timeout: 7000 });
      }
      return undefined;
    case 'cookies':
      if (ctx.close) ctx.close();
      return cookieWizard(a.site || 'douyin', { url: it && it.src, renew: !!a.renew, onDone: it ? () => (ctx.retry ? ctx.retry() : retryItem(it)) : null });
    case 'repair_models': {
      const r = await api('POST', '/api/fixes/repair-models');
      toast(r.message + (it ? '. Bấm Thử lại.' : '. Làm lại thao tác vừa lỗi.'), 'success', { timeout: 7000 });
      return undefined;
    }
    case 'redownload': {
      const name = { tts: 'bộ giọng đọc VieNeu (khoảng 1 GB)', asr: 'mô hình nhận dạng giọng nói', speakers: 'mô hình nhận diện người nói' }[a.model] || 'mô hình';
      const ok = await confirmDialog('Tải lại mô hình?', `iContent xóa bản ${name} đang hỏng trên máy rồi tải lại trong hàng đợi. Cần mạng ổn định. Tải xong bấm Thử lại.`, { okText: 'Tải lại' });
      if (!ok) return undefined;
      await api('POST', '/api/fixes/redownload', { model: a.model || 'tts' });
      toast('Đã thêm việc tải lại vào hàng đợi (xem ở trang Tạo video)', 'success', { timeout: 7000 });
      pollSoon();
      return undefined;
    }
    case 'update_ytdlp': {
      toast('Đang cập nhật bộ tải video, khoảng 10–30 giây…', 'info', { timeout: 30000 });
      const r = await api('POST', '/api/fixes/update-ytdlp');
      toast(r.changed ? `Đã cập nhật bộ tải video ${r.old} → ${r.new}. Bấm Thử lại.` : `Bộ tải video đã là bản mới nhất (${r.new}).`, 'success', { timeout: 8000 });
      return undefined;
    }
    case 'ai_pack':
      if (ctx.close) ctx.close();
      openAiPack(a.pack || 'translate', { onReady: () => toast(it ? 'Đã sẵn sàng. Bấm Thử lại để làm tiếp video.' : 'Đã sẵn sàng. Làm lại thao tác vừa lỗi.', 'success', { timeout: 9000 }) });
      return undefined;
    case 'open':
      if (a.href && /^https:\/\//.test(a.href)) { window.open(a.href, '_blank', 'noopener'); return undefined; }      // trang ngoài (Billing của Google)
      if (ctx.close) ctx.close();
      if (a.focus && location.hash === a.href) { document.getElementById(a.focus)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); return undefined; }
      if (a.focus) { try { sessionStorage.setItem('ic.settings.focus', a.focus); } catch (_) { /* vẫn mở trang */ } }
      if (a.href) location.hash = a.href;
      return undefined;
    case 'copy_report': return copyReport(ctx);
    case 'support_pack': return supportPack();
    default: return undefined;
  }
}

function actionButtons(h, ctx) {
  const it = ctx.item;
  // câu chuyện, bản ghép: dựng lại ở trang của chúng (máy chủ cũng từ chối thử lại thẳng từ hàng đợi)
  const queueRetry = it && (!it.kind || it.kind === 'video' || it.kind === 'prefetch' || it.job);
  const acts = (h.actions || []).filter((a) => queueRetry || !NEED_ITEM.has(a.id));
  // lỗi chưa có cách sửa sẵn: gói báo lỗi (nhật ký + kiểm tra máy) giúp người hỗ trợ tìm ra nguyên nhân
  if (acts.some((a) => a.id === 'copy_report')) acts.push({ id: 'support_pack', label: 'Tạo gói báo lỗi' });
  return acts.map((a) => {
    const b = el('button', {
      class: 'btn btn-sm ' + (a.primary ? 'btn-primary' : a.id === 'copy_report' || a.id === 'support_pack' ? 'btn-ghost' : ''),
      onclick: () => busy(b, () => runAction(a, ctx)),
    }, icon({ retry: 'refresh', cookies: 'key', repair_models: 'wand', redownload: 'download', update_ytdlp: 'refresh', pick_file: 'upload', copy_report: 'copy', support_pack: 'package', open: 'folder', ai_pack: 'download' }[a.id] || 'next'), a.label);
    return b;
  });
}

/** Khung chỉ dẫn gắn trong thẻ lỗi. */
export function HelpPanel(h, ctx = {}) {
  if (!h) return null;
  return el('div', { class: 'fix-box' },
    el('div', { class: 'fix-why', text: h.why }),
    h.steps && h.steps.length ? el('ol', { class: 'fix-steps' }, h.steps.map((s) => el('li', { text: s }))) : null,
    el('div', { class: 'fix-actions' }, actionButtons(h, ctx)));
}

/** Lời chỉ dẫn dạng hộp thoại (cho lỗi hiện bằng thông báo nổi). */
export function openHelp(h, ctx = {}) {
  let m;
  const c = { ...ctx, help: h, close: () => m.close() };
  m = openModal([
    modalHead('alert', h.title, () => m),
    el('div', { class: 'modal-body' }, HelpPanel(h, c),
      ctx.error ? el('details', { class: 'q-err fix-raw' }, el('summary', {}, 'Chi tiết lỗi'), el('pre', { class: 'logbox err', text: ctx.error })) : null),
  ], { cls: 'fix-modal' });
  return m;
}

/** Thông báo lỗi của một mục hàng đợi (Studio, Kể chuyện): có lời chỉ dẫn thì kèm nút Cách khắc phục. */
export function itemErrorToast(prefix, it) {
  if (!it.help) { toast(prefix + String(it.error || it.message || '').split('\n')[0], 'error', { timeout: 9000 }); return; }
  // lỗi cookie: nút làm mới ngay trên thông báo, khỏi mở thẻ Cách khắc phục trước
  const quick = (it.help.actions || []).find((a) => a.primary && a.id === 'cookies');
  toast(prefix + it.help.title, 'error', {
    timeout: 16000,
    actions: [
      quick ? { label: quick.label, primary: true, onClick: () => runAction(quick, { item: it, error: it.error, help: it.help }) } : null,
      { label: 'Cách khắc phục', primary: !quick, onClick: () => openHelp(it.help, { item: it, error: it.error }) },
    ].filter(Boolean),
  });
}

// lỗi hiện bằng thông báo nổi (busy(), chờ tác vụ nền...): hỏi máy chủ có nhận ra không, có thì thêm nút Cách khắc phục
errorHooks.push(async (msg, opts) => {
  let h = null;
  try { h = (await api('POST', '/api/fixes/diagnose', { text: msg })).help; } catch (_) { h = null; }
  if (!h) { toast(msg, 'error', opts); return; }
  toast(h.title, 'error', { ...opts, timeout: 16000, actions: [{ label: 'Cách khắc phục', primary: true, onClick: () => openHelp(h, { error: msg }) }] });
});

// ------------------------------------------------------------------ nạp cookie
/** Hướng dẫn từng bước xuất cookie từ trình duyệt rồi kéo thả vào. opts: {url: link vừa lỗi để thử ngay, onDone} */
export function cookieWizard(site = 'douyin', opts = {}) {
  const name = SITE_NAMES[site] || site;
  let m;
  let saved = false;
  const status = el('div', { class: 'cw-status', role: 'status', hidden: true });
  const setStatus = (kind, ...kids) => { status.hidden = false; status.className = 'cw-status ' + kind; status.replaceChildren(icon(kind === 'ok' ? 'check' : kind === 'bad' ? 'alert' : 'clock'), el('div', {}, kids)); };

  const pick = el('input', { type: 'file', accept: '.txt,.json,text/plain,application/json', hidden: true, onchange: () => { if (pick.files[0]) useFile(pick.files[0]); pick.value = ''; } });
  const paste = el('textarea', { class: 'input cw-paste', rows: 3, spellcheck: 'false', placeholder: 'Hoặc dán nội dung cookie vào đây (bấm Copy trong tiện ích rồi Ctrl+V)' });
  const saveBtn = el('button', { class: 'btn btn-primary', onclick: () => busy(saveBtn, () => save(paste.value)) }, icon('save'), 'Lưu cookie');
  const zone = el('div', { class: 'cw-zone', tabindex: '0', role: 'button', 'aria-label': 'Chọn file cookie', onclick: () => pick.click(), onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick.click(); } } },
    icon('upload'), el('div', {}, el('b', { text: 'Thả file cookie vào đây' }), el('div', { class: 'dim small', text: `hoặc bấm để chọn file ${SITE_FILE[site] || 'cookies.txt'} trong thư mục Tải về` })), pick);
  for (const ev of ['dragenter', 'dragover']) zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add('over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('over'));
  zone.addEventListener('drop', (e) => { e.preventDefault(); zone.classList.remove('over'); const f = e.dataTransfer.files[0]; if (f) useFile(f); });

  async function useFile(f) {
    if (f.size > 2 * 1024 * 1024) { setStatus('bad', 'File quá lớn, không phải file cookie'); return; }
    await busy(null, async () => save(await f.text()));
  }
  async function save(text) {
    if (!String(text || '').trim()) { setStatus('bad', 'Chưa có nội dung cookie'); return; }
    let r;
    try {
      const res = await fetch(`/api/fixes/cookies/${enc(site)}`, { method: 'PUT', headers: { 'Content-Type': 'text/plain; charset=utf-8' }, body: text });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof j.detail === 'string' ? j.detail : `Lỗi ${res.status}`);
      r = j;
    } catch (e) { setStatus('bad', e.message); return; }
    await afterSave(r);
  }
  // khách bấm Export trong tiện ích: file vào thư mục Tải về, iContent tự nạp (không phải kéo thả). Chỉ file mới từ lúc mở hộp này.
  const opened = Date.now() / 1000;
  let since = opened;      // chỉ nhận file sửa sau mốc này: file đã nạp rồi không nạp lại
  let watching = true;
  let warned = '';
  let checking = false;
  async function watchDownloads() {
    if (!watching || checking || !document.body.contains(status)) return;
    checking = true;
    try {
      const r = await api('POST', `/api/fixes/cookies/${enc(site)}/from-downloads`, { since });
      if (r.found) { watching = false; await afterSave(r, r.file); } else if (r.wrong && r.wrong !== warned) { warned = r.wrong; setStatus('warn', r.message); }
    } catch (_) { /* thử lại lần sau */ }
    checking = false;
  }
  const timer = setInterval(() => { if (!document.body.contains(status) && Date.now() / 1000 - opened > 3) { clearInterval(timer); return; } watchDownloads(); }, 2500);
  async function afterSave(r, file = '') {
    saved = true;
    since = Date.now() / 1000 + 1;
    watching = !r.key_ok;      // đã có cookie đủ: thôi dò; thiếu cookie chính thì khách sẽ xuất lại, dò tiếp
    paste.value = '';
    const warn = r.key_ok ? '' : ` Thiếu cookie ${r.key}: có thể trang chưa tải xong lúc xuất. Nếu lát nữa vẫn lỗi, mở lại ${name}, lướt 1–2 video rồi xuất lại.`;
    const from = file ? `Đã tự nhận file ${file} trong thư mục Tải về. ` : '';
    if (!opts.url) { setStatus(r.key_ok ? 'ok' : 'warn', from + `Đã lưu ${r.count} cookie ${name}.` + warn); paintFoot(); return; }
    setStatus('wait', from + `Đã lưu ${r.count} cookie. Đang thử đọc video…`);
    const t = await api('POST', '/api/fixes/test-link', { url: opts.url }).catch((e) => ({ ok: false, error: e.message }));
    if (t.ok) {
      setStatus('ok', el('b', { text: 'Cookie dùng được. ' }), `Đọc được video “${t.title || 'không tên'}”. Đang thử tải lại…`);
      if (opts.onDone) await opts.onDone();
      setTimeout(() => m.close(), 1400);
    } else if (t.help && /^douyin_cookie/.test(t.help.code || '')) {
      // vừa xuất mà vẫn bị từ chối: không nói "cookie cũ" (khách vừa làm xong), chỉ cách xuất lại cho đúng
      const upd = el('button', { class: 'btn btn-sm', onclick: () => busy(upd, () => runAction({ id: 'update_ytdlp' })) }, icon('download'), 'Cập nhật bộ tải video');
      setStatus('bad', el('b', { text: 'Cookie vừa xuất vẫn chưa dùng được. ' }),
        `Thường do bấm Export khi trang ${name} chưa tải xong hoặc còn ô xác minh. Trên trang ${name}: lướt thêm 1–2 video (có ô kéo thì kéo cho xong), rồi bấm Export lại, iContent vẫn đang chờ file. Làm lại vẫn lỗi thì bấm `,
        el('b', { text: 'Cập nhật bộ tải video' }), ' rồi Export lại.', el('div', { class: 'cw-btns', style: { marginTop: '8px' } }, upd));
      watching = true; warned = '';
    } else {
      setStatus('bad', el('b', { text: (t.help && t.help.title) || 'Chưa đọc được video.' }), ' ', (t.help && t.help.why) || String(t.error || '').split('\n')[0], warn);
      watching = true; warned = '';      // xuất lại là tự nhận tiếp
    }
    paintFoot();
  }

  const step = (n, title, ...body) => el('li', { class: 'cw-step' }, el('span', { class: 'cw-n num', text: String(n) }), el('div', { class: 'cw-body' }, el('div', { class: 'cw-t', text: title }), body));
  const linkBtn = (label, url, ic = 'external') => el('button', { class: 'btn btn-sm', onclick: () => openExternal(url) }, icon(ic), label);
  const foot = el('div', { class: 'modal-foot' });
  async function paintFoot() {
    let st = null;
    try { st = (await api('GET', '/api/fixes/cookies')).sites[site]; } catch (_) { st = null; }
    const del = st && st.has ? el('button', {
      class: 'btn btn-ghost', onclick: async () => {
        if (!await confirmDialog(`Xóa cookie ${name}?`, `Video ${name} sẽ không tải được cho tới khi nạp cookie mới.`, { okText: 'Xóa', danger: true })) return;
        await busy(null, () => api('DELETE', `/api/fixes/cookies/${enc(site)}`));
        status.hidden = true; paintFoot();
      },
    }, icon('trash'), 'Xóa cookie đã lưu') : null;
    const info = st && st.has ? el('span', { class: 'dim small cw-have', text: `Đang có ${st.count} cookie, nạp ${fmtAgo(st.saved * 1000)}` }) : null;
    foot.replaceChildren(del || '', info || '', el('span', { class: 'grow' }), el('button', { class: 'btn btn-ghost', onclick: () => m.close() }, saved ? 'Xong' : 'Đóng'), saveBtn);
  }

  const host = (SITE_HOME[site] || '').replace(/^https:\/\/(www\.)?|\/.*$/g, '');
  const fullSteps = () => el('ol', { class: 'cw-steps' },
    step(1, 'Cài tiện ích miễn phí “Get cookies.txt LOCALLY” cho trình duyệt bạn hay dùng',
      el('div', { class: 'cw-btns' }, linkBtn('Chrome, Cốc Cốc, Edge', EXT.chrome), linkBtn('Firefox', EXT.firefox)),
      el('div', { class: 'dim small', text: 'Bấm “Thêm vào Chrome” (Edge: “Nhận”, nếu được hỏi thì chọn Cho phép tiện ích từ cửa hàng khác).' })),
    step(2, `Mở ${name} trên chính trình duyệt đó, chờ trang hiện video rồi lướt qua 1–2 video`,
      el('div', { class: 'cw-btns' }, linkBtn(`Mở ${host}`, SITE_HOME[site], 'globe')),
      el('div', { class: 'dim small', text: 'Không cần đăng nhập: hiện hộp đăng nhập thì bấm dấu X. Có ô kéo xác minh thì kéo cho xong.' })),
    step(3, 'Bấm biểu tượng tiện ích trên thanh công cụ, chọn Get cookies.txt LOCALLY, rồi bấm Export',
      el('div', { class: 'dim small', text: `Biểu tượng hình mảnh ghép cạnh thanh địa chỉ. Trình duyệt lưu file ${SITE_FILE[site] || 'cookies.txt'} vào thư mục Tải về, iContent tự nhận ngay, không phải làm gì thêm.` })),
    step(4, 'Không thấy tự nhận? Kéo file đó thả vào ô bên dưới', zone, paste));
  // làm mới (đã cài tiện ích từ lần trước): mở sẵn trang, chỉ còn lướt video và bấm Export
  const renewSteps = () => el('div', {},
    el('ol', { class: 'cw-steps' },
      step(1, `iContent vừa mở ${host} trên trình duyệt. Chờ trang hiện video rồi lướt qua 1–2 video`,
        el('div', { class: 'cw-btns' }, linkBtn(`Mở lại ${host}`, SITE_HOME[site], 'globe')),
        el('div', { class: 'dim small', text: 'Có ô kéo xác minh thì kéo cho xong; hiện hộp đăng nhập thì bấm dấu X. Tiện ích nằm ở trình duyệt khác thì mở trang trên trình duyệt đó.' })),
      step(2, 'Bấm biểu tượng tiện ích Get cookies.txt LOCALLY rồi bấm Export',
        el('div', { class: 'dim small', text: 'iContent tự nhận file trong thư mục Tải về' + (opts.url ? ' và tự thử lại video.' : '.') }))),
    el('details', { class: 'cw-more' }, el('summary', { text: 'Chưa có tiện ích, hoặc không tự nhận được? Xem đủ các bước' }), fullSteps()));

  m = openModal([
    modalHead('key', opts.renew ? `Làm mới cookie ${name}` : `Thêm cookie ${name}`, () => m),
    el('div', { class: 'modal-body cw' },
      opts.renew
        ? el('p', { class: 'cw-lead' }, `${name} thay cookie định kỳ nên cookie cũ không dùng được nữa. Làm mới mất khoảng 30 giây, `, el('b', { text: 'không cần đăng nhập.' }))
        : el('p', { class: 'cw-lead' }, `${name} chỉ cho tải video khi có cookie, là mẩu dữ liệu trình duyệt tự lưu khi bạn mở trang. `,
          el('b', { text: 'Không cần đăng nhập, không lộ mật khẩu.' }), ' Làm một lần, dùng được nhiều ngày.'),
      opts.renew ? renewSteps() : fullSteps(),
      status,
      el('p', { class: 'dim small cw-privacy' }, icon('shield'), `Cookie chỉ lưu trên máy này (thư mục cookies của iContent), chỉ giữ cookie của ${name}, không gửi đi đâu.`)),
    foot,
  ], { cls: 'cw-modal' });
  paintFoot();
  if (opts.renew && SITE_HOME[site]) openExternal(SITE_HOME[site]).catch(() => {});
  return m;
}

/** Ô "Cookie tải video" trong Cài đặt. */
export async function cookiePanel() {
  const list = el('div', { class: 'ck-list' });
  async function paint() {
    let sites = {};
    try { sites = (await api('GET', '/api/fixes/cookies')).sites || {}; } catch (_) { sites = {}; }
    list.replaceChildren(...['douyin', 'bilibili'].map((k) => {
      const s = sites[k] || {};
      return el('div', { class: 'ck-row' },
        el('div', { class: 'ck-name' }, el('b', { text: SITE_NAMES[k] }),
          el('div', { class: 'dim small', text: k === 'douyin' ? 'Bắt buộc để tải video Douyin' : 'Không bắt buộc. Thử khi Bilibili hay chặn (lỗi 403, 503)' })),
        s.has ? el('span', { class: 'pill ok', text: `Đã nạp ${fmtAgo(s.saved * 1000)}` }) : el('span', { class: 'pill', text: 'Chưa có' }),
        el('button', { class: 'btn btn-sm', onclick: () => { const w = cookieWizard(k); const close = w.close; w.close = (r) => { close(r); paint(); }; } }, icon('key'), s.has ? 'Nạp lại' : 'Nạp cookie'));
    }));
  }
  await paint();
  return list;
}

const MARK = { ok: 'check', warn: 'alert', bad: 'alert', info: 'info' };

/** Kết quả kiểm tra máy (icontent/support.py) trong một hộp thoại. */
export async function checkMachine() {
  const r = await api('GET', '/api/support/checks');
  const rows = (r.checks || []).map((c) => el('div', { class: `sp-row ${c.state}` },
    el('span', { class: 'sp-ic' }, icon(MARK[c.state] || 'info')),
    el('div', {}, el('b', { text: c.title }), el('div', { class: 'dim small', text: c.detail }),
      c.help && c.state !== 'ok' ? el('div', { class: 'small sp-help', text: c.help }) : null,
      c.fix ? el('div', { class: 'small sp-help' }, `Cách sửa: mở công cụ Sửa lỗi iContent (menu Start), bấm ${c.fix.label}.`) : null)));
  const bad = (r.checks || []).filter((c) => c.state === 'bad').length;
  let m;
  m = openModal([
    modalHead('scan', bad ? `Kiểm tra máy: ${bad} mục cần sửa` : 'Kiểm tra máy: ổn', () => m),
    el('div', { class: 'modal-body sp-list' }, rows),
    el('div', { class: 'modal-foot' }, el('span', { class: 'grow' }),
      el('button', { class: 'btn', onclick: () => { m.close(); supportPack(); } }, icon('package'), 'Tạo gói báo lỗi'),
      el('button', { class: 'btn btn-primary', onclick: () => m.close() }, 'Đóng')),
  ], { cls: 'sp-modal' });
  return m;
}

/** Ô "Sửa lỗi nhanh" trong Cài đặt: cùng các nút với thẻ lỗi, để tác giả hướng dẫn khách qua điện thoại. */
export function toolsPanel() {
  const row = (label, desc, a) => {
    const b = el('button', { class: 'btn btn-sm', onclick: () => busy(b, () => (a.run ? a.run() : runAction(a, {}))) }, icon(a.icon), label);
    return el('div', { class: 'ck-row' }, el('div', { class: 'ck-name' }, el('b', { text: label }), el('div', { class: 'dim small', text: desc })), b);
  };
  return el('div', { class: 'ck-list' },
    row('Kiểm tra máy', 'Xem thư viện, ffmpeg, ổ đĩa, mạng, cookie... có vấn đề gì không', { icon: 'scan', run: checkMachine }),
    row('Tạo gói báo lỗi', 'Gói nhật ký và kết quả kiểm tra ra màn hình nền để gửi người hỗ trợ (đã bỏ key, cookie, tên máy)', { icon: 'package', run: () => supportPack() }),
    row('Mở công cụ Sửa lỗi', 'Cửa sổ riêng, có cả trong menu Start: dùng được khi iContent không mở được', { icon: 'wand', run: () => api('POST', '/api/support/tool') }),
    row('Cập nhật bộ tải video', 'Khi Douyin, Bilibili... đổi trang và link đúng mà vẫn không tải được', { id: 'update_ytdlp', icon: 'refresh' }),
    row('Sửa file mô hình', 'Khi giọng đọc báo lỗi ONNXRuntime, External data path', { id: 'repair_models', icon: 'wand' }),
    row('Tải lại bộ giọng đọc', 'Khi file giọng VieNeu bị hỏng do tải dở (khoảng 1 GB)', { id: 'redownload', model: 'tts', icon: 'download' }));
}
