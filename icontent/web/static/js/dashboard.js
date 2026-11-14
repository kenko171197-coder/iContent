/* Trang chủ: chọn việc cần làm, xem việc đang chạy, mọi thứ vừa làm (video dịch, câu chuyện, quy trình, giọng đọc) và máy đã sẵn sàng chưa. */
import { S, api, busy, el, fmtAgo, icon, playUrl, pollSoon, toast } from './core.js';
import { renewBanner } from './license.js';
import { openMyVoices } from './myvoices.js';
import { maybeWhatsNew, onboarded, openOnboarding } from './onboard.js';

const TASKS = [
  { icon: 'spark', title: 'Truyện AI từ ý tưởng', desc: 'Một câu ý tưởng thành video kể chuyện: AI viết, vẽ, đọc, dựng, làm thumbnail.', tag: 'AI viết và vẽ', flow: 'ai_story' },
  { icon: 'image', title: 'Video từ ảnh của tôi', desc: 'Ảnh và lời dẫn của bạn thành video có máy quay chuyển động, phụ đề, nhạc.', tag: 'Miễn phí', flow: 'my_images' },
  { icon: 'film', title: 'Kể chuyện từng cảnh', desc: 'Tự tay sắp từng cảnh, nhân vật giữ đúng mặt, chuyển cảnh, mở đầu, kết thúc.', tag: 'Chỉnh chi tiết', href: '#/story' },
  { icon: 'mic', title: 'Đọc thành giọng nói', desc: 'Dán chữ ra file MP3 và phụ đề SRT. Có cả giọng của chính bạn.', tag: 'Miễn phí, trên máy', href: '#/voice' },
  { icon: 'square', title: 'Ảnh bìa', desc: 'Ảnh bìa cho video vừa làm: mẫu sẵn, chữ lớn, mũi tên, AI gợi ý chữ.', tag: 'Kéo thả', href: '#/thumb' },
  { icon: 'scissors', title: 'Dựng tự do như CapCut', desc: 'Cắt ghép, thêm chữ, chuyển cảnh, nhạc trên trục thời gian, ngay trên máy.', tag: 'Trình dựng', href: '#/editor' },
  { icon: 'compass', title: 'Tìm video thịnh hành', desc: 'Video đang lên ở Trung Quốc, xem trước, chọn rồi dịch một lần nhiều video.', tag: 'Ý tưởng nội dung', href: '#/discover' },
];
const KIND = { job: ['Video dịch', 'globe'], story: ['Kể chuyện', 'film'], flow: ['Quy trình', 'layers'], speech: ['Giọng đọc', 'mic'] };
const FLOW_ICON = { idea: 'spark', script: 'file', images: 'image', ai_write: 'brain', split: 'scissors', char_refs: 'wand', draw: 'image', voice: 'mic', music: 'music',
  render: 'film', thumbnail: 'square', editor: 'scissors', export: 'package' };

function greeting() {
  const h = new Date().getHours();
  return h < 11 ? 'Chào buổi sáng' : h < 14 ? 'Chào buổi trưa' : h < 18 ? 'Chào buổi chiều' : 'Chào buổi tối';
}

export async function viewHome(main, alive) {
  main.classList.add('view-pad');
  let [home, status] = await Promise.all([api('GET', '/api/home'), api('GET', '/api/status').catch(() => ({}))]);
  if (!alive()) return null;
  let filter = 'all';

  const startFlow = (tpl, btn) => busy(btn, async () => {
    const w = await api('POST', '/api/workflows', { template: tpl });
    location.hash = `#/flow/${encodeURIComponent(w.id)}`;
  });
  const tasks = el('div', { class: 'hm-tasks' }, TASKS.map((t) => {
    const card = el(t.href ? 'a' : 'button', { class: 'hm-task', href: t.href || undefined, onclick: t.flow ? (e) => startFlow(t.flow, e.currentTarget) : undefined },
      el('span', { class: 'hm-task-ic' }, icon(t.icon)),
      el('span', { class: 'hm-task-t' }, el('b', { text: t.title }), el('span', { class: 'dim small', text: t.desc })),
      el('span', { class: 'hm-tag', text: t.tag }));
    return card;
  }));

  // ---------- ô dán link to: việc chính của app
  const linkInp = el('input', {
    type: 'text', class: 'hm-link', spellcheck: 'false', 'aria-label': 'Link video',
    placeholder: 'Dán link Douyin, Bilibili, Xiaohongshu, Weibo vào đây…',
    onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); go(); } },
  });
  function go() {
    const v = linkInp.value.trim();
    if (v) sessionStorage.setItem('s566.prefill', v);
    location.hash = '#/new';
  }
  const quick = el('section', { class: 'hm-quick' },
    el('div', { class: 'hm-quick-t' }, el('h2', { text: 'Dịch và lồng tiếng video Trung Quốc' }),
      el('span', { class: 'dim', text: 'Ra video tiếng Việt có phụ đề, giọng đọc khớp từng câu, sub gốc được xóa sạch.' })),
    el('div', { class: 'hm-quick-row' },
      el('label', { class: 'hm-link-box' }, icon('paste'), linkInp),
      el('button', { class: 'btn btn-primary btn-lg hm-go', onclick: () => go() }, 'Bắt đầu', icon('arrow'))),
    el('div', { class: 'hm-quick-alt dim small' }, 'hoặc ',
      el('a', { href: '#/new', class: 'hm-quick-file' }, icon('upload'), 'chọn file video trên máy'),
      ' · dán nhiều link cùng lúc ở trang ', el('a', { href: '#/new', text: 'Dịch video' })));

  // ---------- đang chạy
  const runBox = el('section', { class: 'hm-run' });
  function paintRunning() {
    const rs = home.running || [];
    runBox.hidden = !rs.length;
    runBox.replaceChildren(el('h3', { class: 'ed-head', text: 'Đang chạy' }), ...rs.map((r) => el('a', { class: 'hm-run-it', href: r.href },
      el('span', { class: 'hm-run-dot' + (r.state === 'queued' ? ' wait' : '') }),
      el('span', { class: 'hm-run-t' }, el('b', { text: r.title || 'Việc đang chạy' }), el('span', { class: 'dim small', text: r.state === 'queued' ? 'Đang chờ lượt' : (r.message || '') })),
      el('span', { class: 'hm-run-bar' }, el('i', { style: { width: `${Math.round((r.progress || 0) * 100)}%` } })),
      el('span', { class: 'mono small', text: r.progress != null ? `${Math.round(r.progress * 100)}%` : '' }))));
  }

  // ---------- gần đây
  const chips = el('div', { class: 'seg hm-chips' });
  const grid = el('div', { class: 'hm-recent' });
  function paintRecent() {
    const c = home.counts || {};
    chips.replaceChildren(...[['all', 'Tất cả'], ['job', 'Video dịch'], ['story', 'Kể chuyện'], ['flow', 'Quy trình'], ['speech', 'Giọng đọc']]
      .filter(([k]) => k === 'all' || c[k])
      .map(([k, l]) => el('button', { type: 'button', class: 'seg-btn' + (filter === k ? ' active' : ''), onclick: () => { filter = k; paintRecent(); } }, l + (k !== 'all' ? ` ${c[k]}` : ''))));
    const items = (home.items || []).filter((x) => filter === 'all' || x.kind === filter);
    if (!items.length) {
      grid.replaceChildren(el('div', { class: 'hm-empty' }, icon('inbox'), el('b', { text: 'Chưa có gì ở đây' }), el('span', { class: 'dim small', text: 'Chọn một việc ở trên để bắt đầu. Mọi thứ bạn làm sẽ hiện ở đây.' })));
      return;
    }
    grid.replaceChildren(...items.map((x) => {
      const [kl, ki] = KIND[x.kind] || ['', 'file'];
      const play = x.audio ? el('button', { class: 'btn btn-xs btn-icon hm-play', title: 'Nghe', 'aria-label': 'Nghe', onclick: (e) => { e.preventDefault(); playUrl(x.audio, e.currentTarget); } }, icon('play')) : '';
      return el('a', { class: 'hm-item', href: x.href },
        el('div', { class: 'hm-thumb' + (x.thumb ? '' : ' empty') },
          x.thumb ? el('img', { src: x.thumb, alt: '', loading: 'lazy' })
            : x.types && x.types.length ? el('div', { class: 'hm-chain' }, x.types.slice(0, 9).map((t) => el('span', {}, icon(FLOW_ICON[t] || 'square')))) : icon(ki),
          play,
          el('span', { class: 'hm-kind' }, icon(ki), kl)),
        el('div', { class: 'hm-item-t' }, el('b', { text: x.title || kl }),
          el('span', { class: 'small ' + (x.done ? 'hm-ok' : 'dim'), text: x.status }), el('span', { class: 'dim small', text: fmtAgo(x.updated) })));
    }));
  }

  // ---------- máy đã sẵn sàng chưa
  const ready = el('aside', { class: 'hm-ready' });
  function checks() {
    const s = status || {};
    const out = [];
    const tr = s.translator || {};
    out.push(s.ffmpeg ? ['ok', 'Xử lý video', 'FFmpeg đã có'] : ['bad', 'Xử lý video', 'Thiếu FFmpeg: chạy lại trình cài Studio566', '#/settings']);
    out.push(s.nvenc ? ['ok', 'Card đồ họa', `${home.gpu || 'NVIDIA'}: dựng video nhanh bằng NVENC${s.cuda ? ', nhận giọng bằng CUDA' : ''}`]
      : ['warn', 'Card đồ họa', 'Không có NVENC: vẫn dựng được bằng CPU, chậm hơn']);
    const dl = s.downloads || [];
    const fetching = (home.running || []).some((r) => r.prefetch);
    out.push(dl.length ? ['warn', 'Mô hình AI trên máy', fetching ? 'Đang tải trước, xem tiến độ ở mục Đang chạy'
      : `Chưa tải: ${dl.map((d) => `${d.name} (~${d.mb >= 1000 ? (d.mb / 1000).toFixed(1).replace('.', ',') + ' GB' : d.mb + ' MB'})`).join(', ')}. Tải trước để video đầu tiên chạy ngay.`, fetching ? '' : 'prefetch', 'Tải trước']
      : ['ok', 'Mô hình AI trên máy', 'Nhận giọng, giọng đọc VieNeu đã sẵn']);
    const provName = { claude: 'Claude', openai: tr.model && String(tr.model).startsWith('gemini') ? 'Gemini' : 'AI tương thích OpenAI', offline: 'dịch offline', google: 'Google dịch', ollama: 'Ollama' }[tr.provider] || tr.provider;
    out.push(tr.chosen_ready ? ['ok', 'AI dịch, viết kịch bản', `Đang dùng ${provName}`]
      : (s.keys || {}).gemini ? ['ok', 'AI dịch, viết kịch bản', `Dùng Gemini (đã có key): dịch theo ngữ cảnh, viết kịch bản, gợi ý chữ thumbnail${tr.provider && tr.provider !== 'openai' ? `. ${provName} chưa có key nên tạm thay bằng Gemini` : ''}`]
        : ['warn', 'AI dịch, viết kịch bản', 'Chưa kết nối AI: dịch offline, chưa viết kịch bản được. Key Gemini miễn phí là đủ.', '#/settings', 'Kết nối AI']);
    const provs = home.image_providers || [];
    const good = provs.find((p) => p.ready && p.status !== 'billing');
    const billing = provs.find((p) => p.ready && p.status === 'billing');
    if (good) out.push(['ok', 'AI vẽ ảnh', `${good.name}${good.status === 'ok' ? ' đã vẽ được' : ' đã có key'}`]);
    else if (billing) out.push(['warn', 'AI vẽ ảnh', `Key ${billing.name} chưa vẽ được: gói miễn phí không có hạn mức vẽ ảnh. Bật thanh toán, hoặc thêm Cloudflare (miễn phí), hoặc chép lời nhắn sang ChatGPT rồi dán ảnh về.`, billing.id === 'gemini' ? 'https://aistudio.google.com/usage?tab=billing' : '#/settings', billing.id === 'gemini' ? 'Bật thanh toán' : 'Cài đặt']);
    else out.push(['warn', 'AI vẽ ảnh', 'Chưa có key vẽ ảnh. Vẫn làm được: tự tải ảnh, hoặc chép lời nhắn sang ChatGPT, Copilot rồi dán ảnh về.', '#/settings', 'Thêm key']);
    out.push(home.my_voices ? ['ok', 'Giọng của tôi', `${home.my_voices} giọng tự thu`] : ['off', 'Giọng của tôi', 'Thu 10 giây giọng của bạn để đọc mọi văn bản bằng chính giọng đó', 'myvoice', 'Thu giọng']);
    out.push(home.editor ? ['ok', 'Trình dựng', 'Sẵn sàng'] : ['warn', 'Trình dựng', 'Bản cài này chưa có trình dựng']);
    if (home.disk) out.push(home.disk.free_gb >= 15 ? ['ok', 'Ổ đĩa', `Còn trống ${home.disk.free_gb} GB ở ổ ${home.disk.path}`] : ['warn', 'Ổ đĩa', `Chỉ còn ${home.disk.free_gb} GB ở ổ ${home.disk.path}: mỗi video cần vài trăm MB đến vài GB`, '#/library', 'Dọn thư viện']);
    return out;
  }
  function paintReady() {
    const list = checks();
    const ok = list.filter((x) => x[0] === 'ok').length;
    const pct = ok / list.length;
    const ring = el('div', { class: 'hm-ring', style: { '--p': `${Math.round(pct * 360)}deg` } }, el('span', { text: `${ok}/${list.length}` }));
    ready.replaceChildren(
      el('div', { class: 'hm-ready-h' }, ring, el('div', {}, el('b', { text: ok === list.length ? 'Máy đã sẵn sàng' : 'Máy gần sẵn sàng' }), el('span', { class: 'dim small', text: 'Mục màu vàng vẫn dùng được, chỉ thiếu tính năng' }))),
      ...list.map(([state, title, detail, href, label]) => el('div', { class: `hm-check ${state}` },
        el('span', { class: 'hm-check-ic' }, icon(state === 'ok' ? 'check' : state === 'bad' ? 'x' : state === 'off' ? 'plus' : 'alert')),
        el('div', { class: 'hm-check-t' }, el('b', { text: title }), el('span', { class: 'small dim', text: detail }),
          href ? (href === 'myvoice' ? el('button', { class: 'btn btn-xs', onclick: () => openMyVoices() }, icon('mic'), label)
            : href === 'prefetch' ? prefetchBtn(label)
              : el('a', { class: 'btn btn-xs', href, target: href.startsWith('http') ? '_blank' : undefined, rel: 'noopener' }, label || 'Mở')) : ''))));
  }
  function prefetchBtn(label) {
    const b = el('button', {
      class: 'btn btn-xs', onclick: () => busy(b, async () => {
        const r = await api('POST', '/api/models/prefetch');
        if (r.nothing) { toast('Mô hình đã có đủ', 'success'); return; }
        pollSoon();
        home = await api('GET', '/api/home');
        paintRunning();
        paintReady();
      }),
    }, icon('download'), label);
    return b;
  }

  main.append(
    renewBanner(S.license) || '',
    el('div', { class: 'hm-hero' },
      el('div', { class: 'hm-hero-row' },
        el('h1', { text: `${greeting()}, hôm nay làm video gì?` }),
        el('button', { class: 'btn btn-sm btn-ghost', onclick: () => openOnboarding() }, icon('book'), 'Hướng dẫn 3 bước')),
      el('p', { class: 'dim', text: 'Dán link là bắt đầu. Mọi thứ chạy ngay trên máy của bạn, video không tải lên đâu cả.' })),
    quick,
    el('h3', { class: 'ed-head hm-sec', text: 'Làm video theo cách khác' }),
    tasks,
    el('div', { class: 'hm-cols' },
      el('div', { class: 'hm-main' }, runBox, el('div', { class: 'hm-recent-h' }, el('h3', { class: 'ed-head', text: 'Gần đây' }), chips), grid),
      ready));
  paintRunning();
  paintRecent();
  paintReady();
  maybeWhatsNew(home.first_run);
  if (!onboarded() && home.first_run) openOnboarding();
  // việc đang chạy: cập nhật tiến độ
  let timer = 0;
  const tick = async () => {
    if (!main.isConnected) return;
    try {
      const h = await api('GET', '/api/home');
      const wasRunning = (home.running || []).length;
      home = h;
      paintRunning();
      if (wasRunning !== (h.running || []).length) {
        paintRecent();
        status = await api('GET', '/api/status').catch(() => status);      // vừa tải xong mô hình: mục sẵn sàng đổi
        if (main.isConnected) paintReady();
      }
    } catch (_) { /* máy chủ bận: lần sau */ }
    timer = setTimeout(tick, (home.running || []).length ? 2000 : 8000);
  };
  timer = setTimeout(tick, (home.running || []).length ? 2000 : 8000);
  return () => clearTimeout(timer);
}
