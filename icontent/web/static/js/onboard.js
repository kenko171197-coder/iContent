/* Hướng dẫn lần đầu: 3 bước dắt tay người mới (kết nối AI miễn phí, chuẩn bị máy, làm video đầu tiên), và "Có gì mới" sau khi cập nhật. */
import { S, api, busy, el, fmtSize, icon, loadStatus, modalHead, openModal, pollSoon, queueListeners, toast } from './core.js';
import { openMyVoices } from './myvoices.js';

const DONE_KEY = 'ic.onboarded';
const VERSION_KEY = 'ic.version';
const GEMINI_KEY_URL = 'https://aistudio.google.com/apikey';
export const onboarded = () => localStorage.getItem(DONE_KEY) === '1';

export function openOnboarding({ step = 0 } = {}) {
  let cur = Math.max(0, Math.min(2, step));
  let status = S.status || {};
  const unsub = new Set();
  const body = el('div', { class: 'ob-body' });
  const dots = el('div', { class: 'ob-dots', 'aria-hidden': 'true' });
  const backBtn = el('button', { class: 'btn btn-ghost', onclick: () => go(cur - 1) }, icon('back'), 'Quay lại');
  const nextBtn = el('button', { class: 'btn btn-primary', onclick: () => (cur === 2 ? m.close() : go(cur + 1)) });
  const later = el('button', { class: 'btn btn-ghost', onclick: () => m.close() }, 'Để sau');
  const m = openModal([
    modalHead('book', 'Bắt đầu với iContent', () => m),
    dots, body,
    el('div', { class: 'modal-foot' }, later, el('span', { class: 'grow' }), backBtn, nextBtn),
  ], {
    cls: 'modal-ob',
    onClose: () => { localStorage.setItem(DONE_KEY, '1'); unsub.forEach((f) => f()); },
  });
  const STEPS = [stepAI, stepMachine, stepFirst];
  const TITLES = ['Kết nối AI', 'Chuẩn bị máy', 'Video đầu tiên'];

  function go(i) {
    cur = Math.max(0, Math.min(2, i));
    unsub.forEach((f) => f());
    unsub.clear();
    dots.replaceChildren(...TITLES.map((t, k) => el('button', { type: 'button', class: 'ob-dot' + (k === cur ? ' on' : k < cur ? ' done' : ''), onclick: () => go(k) },
      el('span', { class: 'ob-dot-n', text: String(k + 1) }), t)));
    body.replaceChildren(STEPS[cur]());
    backBtn.hidden = cur === 0;
    nextBtn.replaceChildren(...(cur === 2 ? [icon('check'), 'Xong'] : ['Tiếp', icon('next')]));
  }

  // ---------------------------------------------------------------- bước 1: AI
  function stepAI() {
    const box = el('div', { class: 'ob-step' });
    const has = !!(status.keys && status.keys.gemini);
    const tr = status.translator || {};
    const other = tr.chosen_ready && tr.provider === 'claude';
    const intro = [
      el('h2', { text: 'Kết nối AI miễn phí' }),
      el('p', { class: 'muted', text: 'Gemini của Google có gói miễn phí, không cần thẻ ngân hàng. Có AI thì iContent dịch theo ngữ cảnh, có xưng hô, viết được kịch bản kể chuyện, gợi ý tiêu đề và chữ cho thumbnail.' }),
    ];
    if (has || other) {
      box.append(...intro, el('div', { class: 'ob-ok' }, icon('check'),
        el('div', {}, el('b', { text: other ? 'Đã kết nối Claude' : 'Đã kết nối Gemini' }), el('span', { class: 'small dim', text: 'Bấm Tiếp để sang bước sau. Muốn đổi key: vào Cài đặt.' }))));
      return box;
    }
    const inp = el('input', { class: 'input', type: 'password', autocomplete: 'off', spellcheck: 'false', placeholder: 'Dán key vào đây (AIza…)', 'aria-label': 'Key Gemini' });
    const out = el('div', { class: 'ob-out', hidden: true });
    const paste = el('button', {
      class: 'btn', title: 'Dán từ bộ nhớ tạm', onclick: async () => {
        try { inp.value = (await navigator.clipboard.readText()).trim(); } catch (_) { inp.focus(); toast('Bấm vào ô rồi nhấn Ctrl+V để dán', 'info'); }
      },
    }, icon('paste'), 'Dán');
    const connect = el('button', {
      class: 'btn btn-primary', onclick: () => busy(connect, async () => {
        out.hidden = false;
        out.className = 'ob-out';
        out.replaceChildren(el('span', { class: 'spinner' }), 'Đang dịch thử một câu bằng key này…');
        try {
          const r = await api('POST', '/api/onboard/gemini', { key: inp.value });
          inp.value = '';
          await loadStatus();
          status = S.status || status;
          out.className = 'ob-out ok';
          out.replaceChildren(icon('check'), el('span', {}, el('b', { text: 'Kết nối tốt. ' }), `Dịch thử “你好，朋友们”: “${r.sample}”` + (r.switched ? '. Từ giờ video được dịch bằng Gemini.' : '.')));
          setTimeout(() => { if (cur === 0 && box.isConnected) go(1); }, 1600);
        } catch (e) {
          out.className = 'ob-out err';
          out.replaceChildren(icon('alert'), el('span', { text: e.message }));
        }
      }),
    }, icon('key'), 'Kết nối');
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') connect.click(); });
    box.append(...intro,
      el('ol', { class: 'ob-steps' },
        el('li', {}, 'Mở trang lấy key, đăng nhập bằng tài khoản Gmail. ',
          el('a', { class: 'btn btn-sm', href: GEMINI_KEY_URL, target: '_blank', rel: 'noreferrer' }, icon('external'), 'Mở trang lấy key')),
        el('li', {}, 'Bấm ', el('b', { text: 'Create API key' }), ' (Tạo khóa API). Hiện ra key thì bấm nút chép.'),
        el('li', {}, 'Quay lại đây, dán key rồi bấm Kết nối.')),
      el('div', { class: 'key-row' }, inp, paste, connect),
      out,
      el('p', { class: 'small dim', text: 'Key chỉ lưu trên máy này và chỉ gửi tới Google. Gói miễn phí dịch và viết được; riêng vẽ ảnh bằng AI cần bật thanh toán, không bắt buộc.' }),
      el('p', { class: 'small dim', text: 'Chưa muốn kết nối? Bấm Tiếp: iContent vẫn dịch được bằng cách miễn phí, kém tự nhiên hơn.' }));
    setTimeout(() => inp.focus(), 80);
    return box;
  }

  // ---------------------------------------------------------------- bước 2: máy
  function stepMachine() {
    const box = el('div', { class: 'ob-step' });
    const dl = status.downloads || [];
    const total = dl.reduce((n, d) => n + (d.mb || 0), 0) * 1e6;
    const models = el('div', { class: 'ob-card' });
    function paintModels(q) {
      const it = (q || S.queue || []).find((i) => i.kind === 'prefetch' && (i.state === 'queued' || i.state === 'running'));
      const doneIt = (q || S.queue || []).find((i) => i.kind === 'prefetch' && i.state === 'done');
      if (!dl.length || (doneIt && !it)) {
        models.replaceChildren(el('span', { class: 'ob-card-ic ok' }, icon('check')),
          el('div', { class: 'ob-card-t' }, el('b', { text: 'Mô hình AI đã có đủ trên máy' }), el('span', { class: 'small dim', text: 'Nhận giọng nói và đọc lời tiếng Việt chạy ngay, không cần mạng.' })));
        return;
      }
      if (it) {
        const pct = typeof it.progress === 'number' ? Math.round(it.progress * 100) : null;
        models.replaceChildren(el('span', { class: 'ob-card-ic' }, icon('download')),
          el('div', { class: 'ob-card-t' }, el('b', { text: it.state === 'queued' ? 'Đang chờ tới lượt tải' : 'Đang tải mô hình AI' }),
            el('span', { class: 'small dim', text: it.message || 'Có thể sang bước sau, tải vẫn chạy nền.' }),
            el('div', { class: 'hm-run-bar' }, el('i', { style: { width: (pct == null ? 8 : pct) + '%' } }))));
        return;
      }
      const start = el('button', {
        class: 'btn btn-sm btn-primary', onclick: () => busy(start, async () => {
          const r = await api('POST', '/api/models/prefetch');
          if (r.nothing) { toast('Mô hình đã có đủ', 'success'); return; }
          pollSoon();
          toast('Đang tải trong nền, xem tiến độ ở Trang chủ', 'success');
        }),
      }, icon('download'), `Tải trước ngay (${fmtSize(total)})`);
      models.replaceChildren(el('span', { class: 'ob-card-ic' }, icon('cpu')),
        el('div', { class: 'ob-card-t' }, el('b', { text: 'Tải trước mô hình AI chạy trên máy' }),
          el('span', { class: 'small dim', text: `${dl.map((d) => d.name).join(', ')}. Tải một lần, dùng mãi. Không tải trước thì video đầu tiên sẽ tự tải, phải chờ lâu hơn.` }),
          start));
    }
    paintModels();
    const onQ = (q) => { if (box.isConnected) paintModels(q); };
    queueListeners.add(onQ);
    unsub.add(() => queueListeners.delete(onQ));

    const mine = (S.voices && S.voices.mine) || [];
    const voice = el('div', { class: 'ob-card' },
      el('span', { class: 'ob-card-ic' + (mine.length ? ' ok' : '') }, icon(mine.length ? 'check' : 'mic')),
      el('div', { class: 'ob-card-t' },
        el('b', { text: mine.length ? `Đã có ${mine.length} giọng của bạn` : 'Giọng của chính bạn (không bắt buộc)' }),
        el('span', { class: 'small dim', text: 'Thu khoảng 10 giây đọc một đoạn bất kỳ. iContent đọc mọi văn bản, lồng tiếng video bằng chính giọng đó.' }),
        el('button', { class: 'btn btn-sm', onclick: () => openMyVoices() }, icon('mic'), mine.length ? 'Quản lý giọng' : 'Thu giọng')));
    const gpu = el('div', { class: 'ob-card' },
      el('span', { class: 'ob-card-ic' + (status.nvenc ? ' ok' : '') }, icon(status.nvenc ? 'check' : 'monitor')),
      el('div', { class: 'ob-card-t' },
        el('b', { text: status.nvenc ? 'Có card đồ họa NVIDIA' : 'Không thấy card NVIDIA' }),
        el('span', { class: 'small dim', text: status.nvenc ? `Dựng video bằng NVENC${status.cuda ? ', nhận giọng bằng CUDA' : ''}: nhanh hơn chạy CPU nhiều lần.` : 'Vẫn làm được mọi việc bằng CPU, chỉ chậm hơn. Video 3 phút mất khoảng 10 đến 20 phút.' })));
    box.append(el('h2', { text: 'Chuẩn bị máy' }),
      el('p', { class: 'muted', text: 'Nhận giọng nói, đọc lời tiếng Việt, dựng video đều chạy ngay trên máy của bạn. Video không tải lên đâu cả.' }),
      models, voice, gpu);
    return box;
  }

  // ---------------------------------------------------------------- bước 3: video đầu tiên
  function stepFirst() {
    const startFlow = (tpl, btn) => busy(btn, async () => {
      const w = await api('POST', '/api/workflows', { template: tpl });
      m.close();
      location.hash = `#/flow/${encodeURIComponent(w.id)}`;
    });
    const pick = (ic, title, desc, how, run) => {
      const b = el('button', { type: 'button', class: 'ob-pick', onclick: (e) => run(e.currentTarget) },
        el('span', { class: 'hm-task-ic' }, icon(ic)),
        el('span', { class: 'ob-pick-t' }, el('b', { text: title }), el('span', { class: 'small dim', text: desc }), el('span', { class: 'small ob-how', text: how })),
        icon('next'));
      return b;
    };
    const nav = (h) => () => { m.close(); location.hash = h; };
    return el('div', { class: 'ob-step' },
      el('h2', { text: 'Làm video đầu tiên' }),
      el('p', { class: 'muted', text: 'Chọn một việc, iContent dẫn tiếp từng bước. Mọi thứ bạn làm đều nằm trong Thư viện.' }),
      el('div', { class: 'ob-picks' },
        pick('globe', 'Dịch và lồng tiếng một video', 'Video Douyin, Bilibili, Kuaishou ra tiếng Việt có phụ đề, giọng đọc khớp từng câu.', 'Cách làm: dán link vào ô, bấm Bắt đầu.', nav('#/new')),
        pick('spark', 'Truyện AI từ một câu ý tưởng', 'AI viết kịch bản, vẽ ảnh, đọc lời, dựng video và làm thumbnail.', 'Cách làm: gõ ý tưởng vào khối đầu tiên, bấm Chạy.', (b) => startFlow('ai_story', b)),
        pick('mic', 'Đọc văn bản thành giọng nói', 'Dán chữ, ra file MP3 và phụ đề SRT. Không cần mạng.', 'Cách làm: dán chữ, chọn giọng, bấm Đọc.', nav('#/voice'))),
      el('div', { class: 'ob-tips' },
        el('span', {}, el('span', { class: 'kbd', text: 'Ctrl K' }), ' tìm nhanh mọi lệnh và video'),
        el('span', {}, icon('home'), ' Trang chủ cho biết máy đã sẵn sàng chưa'),
        el('span', {}, icon('clock'), ' Video xong sẽ báo ở góc màn hình')));
  }

  go(cur);
  return m;
}

// ---------------------------------------------------------------- có gì mới
/** Gọi ở Trang chủ. Lần đầu mở bản này: người mới thì chỉ ghi nhớ phiên bản, người đã dùng bản cũ thì xem những gì mới. */
export async function maybeWhatsNew(firstRun) {
  const ver = (S.status && S.status.version) || '';
  if (!ver) return;
  const seen = localStorage.getItem(VERSION_KEY);
  localStorage.setItem(VERSION_KEY, ver);
  if (seen === ver || (!seen && firstRun)) return;
  let about;
  try { about = await api('GET', '/api/about'); } catch (_) { return; }
  const ch = (about.changes || []).filter((c) => !seen || newer(c.version, seen));
  if (!ch.length) return;
  const m = openModal([
    modalHead('spark', `iContent ${ver}: có gì mới`, () => m),
    el('div', { class: 'modal-body ob-news' }, ch.map((c) => el('section', {},
      el('h4', { text: `Bản ${c.version}` + (c.date ? ` · ${c.date}` : '') }),
      el('ul', {}, c.items.map((t) => el('li', { text: t })))))),
    el('div', { class: 'modal-foot' }, el('span', { class: 'grow' }), el('button', { class: 'btn btn-primary', onclick: () => m.close() }, 'Dùng thử ngay')),
  ], { cls: 'modal-sm' });
}

function newer(a, b) {
  const pa = String(a).split('.').map(Number), pb = String(b).split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d) return d > 0;
  }
  return false;
}
