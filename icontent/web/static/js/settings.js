/* Trang Cài đặt: kết nối AI dịch, tình trạng hệ thống, tùy chọn mặc định. */
import {
  S, api, busy, clearPreviewCache, clone, confirmDialog, countLeaves, diff, el, errorState, icon, loadConfig, loadStatus, setPath, toast,
} from './core.js';
import { cookiePanel, toolsPanel } from './fixes.js';
import { aiPacks } from './localai.js';
import { licensePanel } from './license.js';
import { OptionsForm } from './options.js';

const PROVIDERS = [
  { id: 'claude', name: 'Claude', sub: 'Dịch tự nhiên nhất, hiểu ngữ cảnh', key: 'ANTHROPIC_API_KEY', get: 'console.anthropic.com', cfg: { provider: 'claude', model: 'claude-opus-5-5', base_url: '', api_key_env: '' } },
  { id: 'gemini', name: 'Gemini', sub: 'Google, có gói miễn phí', key: 'GEMINI_API_KEY', get: 'aistudio.google.com', cfg: { provider: 'openai', model: 'gemini-auto', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/', api_key_env: 'GEMINI_API_KEY' } },
  { id: 'deepseek', name: 'DeepSeek', sub: 'Rẻ, giỏi tiếng Trung', key: 'DEEPSEEK_API_KEY', get: 'platform.deepseek.com', cfg: { provider: 'openai', model: 'deepseek-chat', base_url: 'https://api.deepseek.com', api_key_env: 'DEEPSEEK_API_KEY' } },
  { id: 'offline', name: 'Dịch offline', sub: 'Ngay trên máy, không cần key', key: '', get: '', cfg: { provider: 'offline', model: '', base_url: '', api_key_env: '' } },
  { id: 'ollama', name: 'Ollama', sub: 'Tự chọn model AI chạy trên máy', key: '', get: 'ollama.com', cfg: { provider: 'openai', model: 'qwen2.5', base_url: 'http://localhost:11434/v1', api_key_env: '' } },
  { id: 'google', name: 'Google dịch', sub: 'Miễn phí, kém tự nhiên, dễ bị chặn', key: '', get: '', cfg: { provider: 'google', model: '', base_url: '', api_key_env: '' } },
];

function providerOf(t) {
  if (!t) return 'claude';
  if (t.provider === 'claude') return 'claude';
  if (t.provider === 'google') return 'google';
  if (t.provider === 'offline') return 'offline';
  const u = t.base_url || '';
  if (u.includes('generativelanguage')) return 'gemini';
  if (u.includes('deepseek')) return 'deepseek';
  if (u.includes('localhost') || u.includes('127.0.0.1')) return 'ollama';
  return 'custom';
}

const HEALTH = [
  ['FFmpeg', (s) => s.ffmpeg, 'Bắt buộc. Cài bằng: winget install Gyan.FFmpeg', true],
  ['Dựng video bằng GPU (NVENC)', (s) => s.nvenc, 'Không bắt buộc. Có card NVIDIA sẽ dựng nhanh hơn nhiều'],
  ['Nhận dạng bằng GPU (CUDA)', (s) => s.cuda, 'Không bắt buộc. Không có thì chạy bằng CPU, chậm hơn'],
  ['Đọc và xóa sub gốc (OCR)', (s) => s.ocr, 'Cần để tự dò và xóa sub Trung. Cài: pip install rapidocr'],
  ['Nhận diện người nói', (s) => s.speakers, 'Để mỗi người một giọng. Cài: pip install sherpa-onnx'],
  ['Dịch offline', (s) => s.offline, 'Không bắt buộc. Tải ở mục Mô-đun AI miễn phí phía trên'],
  ['Vẽ ảnh offline', (s) => s.ai && s.ai.image, 'Không bắt buộc. Tải ở mục Mô-đun AI miễn phí phía trên'],
  ['Tách nhạc nền', (s) => s.separator, 'Không bắt buộc. Cài: pip install "audio-separator[gpu]"'],
];

export async function viewSettings(main, alive) {
  const [cfg, status, keys, licState] = await Promise.all([loadConfig(), api('GET', '/api/status').catch(() => null), api('GET', '/api/keys').catch(() => null),
    api('GET', '/api/license').catch(() => null)]);
  if (!alive()) return null;
  const lic = licensePanel(licState);
  S.status = status || S.status;
  const vals = clone(cfg.config) || {};
  const base = cfg.defaults || {};
  let savedSig = JSON.stringify(diff(vals, base) || {});
  let ready = false;

  // ------------------------------------------------ kết nối AI
  let selected = providerOf(vals.translate);
  let keyState = (keys && keys.keys) || {};
  const provRow = el('div', { class: 'prov-row', role: 'radiogroup', 'aria-label': 'Nhà cung cấp dịch' });
  const provDetail = el('div', { class: 'prov-detail' });
  function paintProviders() {
    provRow.replaceChildren(...PROVIDERS.map((p) => el('button', {
      type: 'button', class: 'prov' + (selected === p.id ? ' active' : ''), role: 'radio', 'aria-checked': selected === p.id ? 'true' : 'false',
      onclick: () => {
        selected = p.id;
        for (const [k, v] of Object.entries(p.cfg)) setPath(vals, 'translate.' + k, v);
        form.syncAll();
        paintProviders();
        updDirty();
      },
    }, el('b', { text: p.name }), el('span', { class: 'dim small', text: p.sub }),
      p.key && keyState[p.key] && keyState[p.key].set ? el('span', { class: 'prov-ok' }, icon('check'), 'Đã có key') : null)));
    const p = PROVIDERS.find((x) => x.id === selected);
    if (!p) { provDetail.replaceChildren(el('p', { class: 'muted small', text: 'Đang dùng cấu hình API tùy chỉnh trong config.yaml.' })); return; }
    const out = el('span', { class: 'test-out small' });
    const testBtn = el('button', {
      class: 'btn btn-sm', onclick: () => busy(testBtn, async () => {
        out.className = 'test-out small muted';
        out.textContent = 'Đang dịch thử “你好，朋友们”…';
        try {
          const r = await api('POST', '/api/keys/test', Object.assign({}, p.cfg, { model: (vals.translate && vals.translate.model) || p.cfg.model }));
          out.className = 'test-out small ok';
          out.textContent = `Kết nối tốt. Bản dịch thử: “${r.sample}”`;
        } catch (e) {
          out.className = 'test-out small err';
          out.textContent = e.message;
        }
      }),
    }, icon('send'), 'Dịch thử');
    const kids = [];
    if (p.key) {
      const st = keyState[p.key] || {};
      const inp = el('input', { class: 'input', type: 'password', autocomplete: 'off', spellcheck: 'false', placeholder: st.set ? `Đang dùng key ${st.hint || ''}` : 'Dán API key vào đây', 'aria-label': `API key của ${p.name}` });
      const saveKey = el('button', {
        class: 'btn btn-sm btn-primary', onclick: () => busy(saveKey, async () => {
          const r = await api('PUT', '/api/keys', { name: p.key, value: inp.value });
          keyState = r.keys;
          inp.value = '';
          toast('Đã lưu API key trên máy này', 'success');
          paintProviders();
          loadStatus();
        }),
      }, icon('key'), 'Lưu key');
      kids.push(el('div', { class: 'key-row' }, inp, saveKey, testBtn),
        el('p', { class: 'dim small' }, 'Lấy key tại ', el('a', { href: 'https://' + p.get, target: '_blank', rel: 'noreferrer', text: p.get }),
          '. Key chỉ lưu trên máy này (keys.json) và chỉ gửi tới chính nhà cung cấp đó.',
          st.source === 'env' ? ' Hiện đang đọc từ biến môi trường.' : ''));
    } else if (p.id === 'offline') {
      kids.push(aiPacks({ only: 'translate', onReady: () => loadStatus() }),
        el('p', { class: 'dim small', text: 'Khi chưa có key, hoặc AI đã chọn lỗi giữa chừng (quá tải, hết hạn mức), Studio566 tự dịch tiếp bằng cách này thay vì Google.' }));
    } else if (p.id === 'ollama') {
      kids.push(el('div', { class: 'key-row' }, testBtn), el('p', { class: 'dim small' }, 'Cài từ ', el('a', { href: 'https://ollama.com', target: '_blank', rel: 'noreferrer', text: 'ollama.com' }), ', rồi chạy: ollama pull qwen2.5. Câu thoại không rời khỏi máy của bạn.'));
    } else {
      kids.push(el('p', { class: 'dim small', text: 'Không cần key. Bản dịch sát chữ hơn, không có xưng hô theo ngữ cảnh và không có gợi ý tiêu đề, hashtag. Google có thể tạm chặn nếu dịch nhiều.' }));
    }
    kids.push(out);
    provDetail.replaceChildren(...kids);
  }

  // ------------------------------------------------ tình trạng
  const healthList = el('div', { class: 'health' }, HEALTH.map(([name, test, hint, required]) => {
    const ok = status ? !!test(status) : false;
    return el('div', { class: 'health-item' },
      el('span', { class: 'hi-ico ' + (ok ? 'ok' : required ? 'bad' : 'no') }, icon(ok ? 'check' : required ? 'alert' : 'minus')),
      el('div', {}, el('div', { class: 'hi-name', text: name }), ok ? null : el('div', { class: 'dim small', text: hint })));
  }));

  const ckBox = el('div', { class: 'ck-list' });
  cookiePanel().then((n) => ckBox.replaceWith(n)).catch(() => ckBox.replaceChildren(errorState('Không đọc được cookie đã nạp')));

  // ------------------------------------------------ form
  const msg = el('span', { class: 'msg' });
  const form = OptionsForm({ vals, base, groups: ['translate', 'voice', 'subs', 'picture', 'sound', 'system'], storeKey: 'settings', onChange: () => { if (ready) { updDirty(); selected = providerOf(vals.translate); paintProviders(); } } });
  const saveBtn = el('button', {
    class: 'btn btn-primary', onclick: () => busy(saveBtn, async () => {
      const user = diff(vals, base) || {};
      await api('PUT', '/api/config', { user });
      savedSig = JSON.stringify(user);
      await loadConfig();
      clearPreviewCache();
      loadStatus();
      updDirty();
      toast('Đã lưu cài đặt chung', 'success');
    }),
  }, icon('save'), 'Lưu cài đặt');
  const resetBtn = el('button', {
    class: 'btn btn-ghost', onclick: async () => {
      const ok = await confirmDialog('Khôi phục mặc định?', 'Mọi cài đặt trên form sẽ về giá trị mặc định của Studio566 (chưa lưu cho tới khi bấm Lưu cài đặt).', { okText: 'Khôi phục' });
      if (ok) { form.reset(); updDirty(); paintProviders(); }
    },
  }, icon('undo'), 'Về mặc định');
  function updDirty() {
    const sig = JSON.stringify(diff(vals, base) || {});
    const dirty = sig !== savedSig;
    msg.className = 'msg' + (dirty ? ' unsaved' : '');
    const n = countLeaves(diff(vals, base) || {});
    msg.textContent = dirty ? 'Có thay đổi chưa lưu' : n ? `${n} mục khác mặc định` : 'Đang dùng giá trị mặc định';
    saveBtn.disabled = !dirty;
  }
  const chime = el('input', { type: 'checkbox', checked: localStorage.getItem('ic.chime') !== '0', onchange: () => localStorage.setItem('ic.chime', chime.checked ? '1' : '0') });

  // ------------------------------------------------ tạo ảnh AI (Kể chuyện): mỗi nguồn một key, chỉ gửi tới đúng nguồn đó
  const KEY_LABEL = { CLOUDFLARE_API_TOKEN: 'API token (quyền Workers AI)', CLOUDFLARE_ACCOUNT_ID: 'Account ID' };
  const imgBox = el('div', { class: 'img-provs' });
  async function paintImageProviders() {
    let provs = [];
    try { provs = (await api('GET', '/api/story/options')).image_providers || []; } catch (_) { /* máy chủ cũ */ }
    imgBox.replaceChildren(...provs.map((p) => {
      if (p.local) {
        return el('div', { class: 'img-prov' + (p.ready ? ' ready' : '') },
          el('div', { class: 'img-prov-head' }, el('b', { text: p.name }), p.ready ? el('span', { class: 'prov-ok' }, icon('check'), 'Đã tải') : null),
          el('p', { class: 'dim small', text: `${p.price}. Giữ nhân vật bằng tối đa ${p.refs} ảnh mẫu. Không cần key.` }),
          p.ready ? null : el('button', { class: 'btn btn-sm', onclick: () => document.getElementById('mo-dun-ai')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }, icon('download'), 'Tải ở mục Mô-đun AI miễn phí'));
      }
      const rows = p.keys.map((k) => {
        const st = keyState[k] || {};
        const inp = el('input', { class: 'input', type: k === 'CLOUDFLARE_ACCOUNT_ID' ? 'text' : 'password', autocomplete: 'off', spellcheck: 'false',
          placeholder: st.set ? `Đang dùng ${st.hint || ''}` : (KEY_LABEL[k] || 'Dán API key vào đây'), 'aria-label': `${KEY_LABEL[k] || 'API key'} của ${p.name}` });
        const save = el('button', {
          class: 'btn btn-sm', onclick: () => busy(save, async () => {
            const removing = !inp.value.trim();
            const r = await api('PUT', '/api/keys', { name: k, value: inp.value });
            keyState = r.keys;
            inp.value = '';
            toast(removing ? 'Đã xóa key này khỏi máy' : 'Đã lưu trên máy này', 'success');
            paintImageProviders();
            paintProviders();
          }),
        }, icon('key'), 'Lưu');
        return el('div', { class: 'key-row' }, inp, save);
      });
      // trạng thái thật của lần vẽ gần nhất: key gói miễn phí của Gemini có key nhưng không vẽ được ảnh nào
      const billing = p.ready && p.status === 'billing';
      const badge = !p.ready ? (p.paid ? el('span', { class: 'dim small', text: 'Trả phí' }) : null)
        : p.paid && !p.usable ? el('span', { class: 'prov-warn', title: 'Bật ở mục Chi phí phía trên' }, icon('shield'), 'Trả phí, đang khóa')
        : billing ? el('span', { class: 'prov-warn', title: p.status_msg }, icon('alert'), 'Chưa vẽ được')
        : el('span', { class: 'prov-ok' }, icon('check'), p.status === 'ok' ? 'Đã vẽ được' : 'Có key');
      return el('div', { class: 'img-prov' + (p.ready && !billing ? ' ready' : '') + (billing ? ' billing' : '') },
        el('div', { class: 'img-prov-head' }, el('b', { text: p.name }), badge),
        billing ? el('p', { class: 'small prov-warn-msg' }, p.status_msg || 'Lần vẽ gần nhất bị từ chối vì key chưa bật thanh toán.',
          p.id === 'gemini' ? el('a', { href: 'https://aistudio.google.com/usage?tab=billing', target: '_blank', rel: 'noreferrer', text: ' Mở trang Billing' }) : '') : '',
        el('p', { class: 'dim small' }, `${p.price}. ${p.refs ? `Giữ nhân vật bằng tối đa ${p.refs} ảnh mẫu.` : 'Không nhận ảnh mẫu, chỉ giữ nhân vật bằng mô tả.'} Lấy key tại `,
          el('a', { href: 'https://' + p.get, target: '_blank', rel: 'noreferrer', text: p.get }), '.'),
        ...rows);
    }), el('p', { class: 'dim small img-prov-note', text: 'ChatGPT và Copilot bản miễn phí trên web không có API. Ở từng cảnh trong Kể chuyện, bấm Chép lời nhắn, dán sang đó để vẽ, chép ảnh rồi bấm Dán ảnh. Key chỉ lưu trên máy này (keys.json).' }));
  }
  paintImageProviders();

  // ------------------------------------------------ video nền miễn phí (kho có giấy phép) và clip AI
  const vidBox = el('div', { class: 'img-provs' });
  async function paintVideoSources() {
    let o = {};
    try { o = await api('GET', '/api/story/options'); } catch (_) { return; }
    const keyRow = (k, name) => {
      const st = keyState[k] || {};
      const inp = el('input', { class: 'input', type: 'password', autocomplete: 'off', spellcheck: 'false',
        placeholder: st.set ? `Đang dùng ${st.hint || ''}` : 'Dán API key (miễn phí) vào đây', 'aria-label': `API key của ${name}` });
      const save = el('button', {
        class: 'btn btn-sm', onclick: () => busy(save, async () => {
          const removing = !inp.value.trim();
          keyState = (await api('PUT', '/api/keys', { name: k, value: inp.value })).keys;
          inp.value = '';
          toast(removing ? 'Đã xóa key này khỏi máy' : 'Đã lưu trên máy này', 'success');
          paintVideoSources();
        }),
      }, icon('key'), 'Lưu');
      return el('div', { class: 'key-row' }, inp, save);
    };
    const stock = (o.stock_sources || []).map((src) => el('div', { class: 'img-prov' + (src.ready ? ' ready' : '') },
      el('div', { class: 'img-prov-head' }, el('b', { text: src.name }), src.ready ? el('span', { class: 'prov-ok' }, icon('check'), src.keys.length ? 'Có key' : 'Không cần key') : null),
      el('p', { class: 'dim small' }, src.license + '.',
        src.get ? [' Lấy key miễn phí tại ', el('a', { href: src.get, target: '_blank', rel: 'noreferrer', text: src.get.replace(/^https:\/\//, '').replace(/\/$/, '') }), ' (đăng ký 1 phút).'] : ' Dùng được ngay, ít video dọc hơn hai kho kia.'),
      ...src.keys.map((k) => keyRow(k, src.name))));
    const ai = (o.video_providers || []).map((v) => {
      const billing = v.ready && v.status === 'billing';
      return el('div', { class: 'img-prov' + (v.ready && !billing ? ' ready' : '') + (billing ? ' billing' : '') },
        el('div', { class: 'img-prov-head' }, el('b', { text: v.name }), !v.ready ? el('span', { class: 'dim small', text: 'Trả phí' })
          : !v.usable ? el('span', { class: 'prov-warn', title: 'Bật ở mục Chi phí' }, icon('shield'), 'Trả phí, đang khóa')
          : billing ? el('span', { class: 'prov-warn', title: v.status_msg }, icon('alert'), 'Chưa tạo được')
          : el('span', { class: 'prov-ok' }, icon('check'), v.status === 'ok' ? 'Đã tạo được' : 'Có key Gemini')),
        billing ? el('p', { class: 'small prov-warn-msg' }, v.status_msg, el('a', { href: 'https://aistudio.google.com/usage?tab=billing', target: '_blank', rel: 'noreferrer', text: ' Mở trang Billing' })) : '',
        el('p', { class: 'dim small', text: `Biến ảnh cảnh thành clip ${v.min}–${v.max} giây, giữ đúng nhân vật. Giá khoảng ${String(v.price['360p']).replace('.', ',')} USD/giây (360p), ${String(v.price['720p']).replace('.', ',')} (720p), ${String(v.price['1080p']).replace('.', ',')} (1080p). ${v.note}. Dùng chung key Gemini ở mục Kết nối AI dịch hoặc Tạo ảnh AI.` }));
    });
    vidBox.replaceChildren(...stock, ...ai, el('p', { class: 'dim small img-prov-note', text: 'Studio566 chỉ lấy video từ kho có giấy phép rõ ràng và lưu nguồn từng clip cạnh video xuất ra (file .nguon.txt). Không lấy video YouTube, Douyin, TikTok làm nguồn: "video free" trên đó không phải miễn phí bản quyền. Meta Muse chưa có API làm video chính thức nên chưa cắm được.' }));
  }
  paintVideoSources();

  // ------------------------------------------------ chi phí: Studio566 ưu tiên miễn phí, việc tính tiền chỉ chạy khi người dùng bật
  const paidBox = el('div', { class: 'paid-box' });
  async function paintPaid() {
    let o = {};
    try { o = await api('GET', '/api/story/options'); } catch (_) { return; }
    const p = o.paid || { allowed: false };
    const sw = el('input', {
      type: 'checkbox', checked: p.allowed, onchange: () => busy(null, async () => {
        await api('PUT', '/api/paid', { allowed: sw.checked });
        toast(sw.checked ? 'Đã bật tính năng trả phí. Mỗi lần tốn tiền Studio566 vẫn báo giá và hỏi trước.' : 'Đã tắt tính năng trả phí: Studio566 chỉ dùng cách miễn phí.', 'success', { timeout: 5000 });
        paintPaid(); paintImageProviders(); paintVideoSources();
      }),
    });
    paidBox.replaceChildren(
      el('div', { class: 'opt-inline' }, el('div', { class: 'opt-label', text: 'Cho phép tính năng trả phí' }), el('label', { class: 'switch' }, sw, el('span', { class: 'switch-track' }, el('span', { class: 'switch-thumb' })))),
      el('p', { class: 'dim small', text: p.allowed
        ? 'Đang bật: được vẽ ảnh bằng Gemini, OpenAI, Meta Muse và AI làm clip (Gemini Omni). Tự chọn vẫn dùng cách miễn phí trước; mỗi lần tốn tiền đều báo giá và hỏi lại.'
        : 'Đang tắt: Studio566 chỉ dùng cách miễn phí. Vẽ trên máy hoặc Cloudflare, video nền từ kho miễn phí, AI viết bằng Gemini gói miễn phí hoặc AI trên máy, giọng đọc trên máy. Nút trả phí bị khóa, không lo bấm nhầm mất tiền.' }));
  }
  paintPaid();

  main.append(
    el('div', { class: 'page-head' }, el('div', { class: 'page-head-text' }, el('div', { class: 'eyebrow', text: 'Cài đặt' }), el('h1', { text: 'Thiết lập Studio566' }),
      el('p', { text: 'Áp dụng cho mọi video mới. Từng video vẫn có thể chỉnh riêng trong Studio.' }))),
    el('section', { class: 'panel ai-panel' },
      el('div', { class: 'panel-head' }, icon('key'), el('h3', { text: 'Kết nối AI dịch' }), status && status.translator && status.translator.chosen_ready ? el('span', { class: 'pill ok', text: 'Đã kết nối' }) : status && status.translator && status.translator.ready ? el('span', { class: 'pill ok', text: 'Đang dùng dịch offline' }) : el('span', { class: 'pill warn', text: 'Chưa kết nối' })),
      provRow, provDetail),
    el('section', { class: 'panel ai-panel', id: 'mo-dun-ai' },
      el('div', { class: 'panel-head' }, icon('cpu'), el('h3', { text: 'Mô-đun AI miễn phí (chạy trên máy)' })),
      el('p', { class: 'dim small aip-intro', text: 'Tải một lần, sau đó dịch và vẽ ảnh ngay trên máy: không cần key, không cần mạng, không giới hạn, không tốn tiền. Chạy được cả khi Gemini quá tải hay Google chặn.' }),
      aiPacks({ onReady: () => { loadStatus(); paintImageProviders(); } })),
    el('section', { class: 'panel ai-panel', id: 'chi-phi' },
      el('div', { class: 'panel-head' }, icon('shield'), el('h3', { text: 'Chi phí: ưu tiên miễn phí' })), paidBox),
    el('section', { class: 'panel ai-panel' },
      el('div', { class: 'panel-head' }, icon('image'), el('h3', { text: 'Tạo ảnh AI (Kể chuyện)' })), imgBox),
    el('section', { class: 'panel ai-panel', id: 'video-nen' },
      el('div', { class: 'panel-head' }, icon('film'), el('h3', { text: 'Video nền miễn phí và clip AI (Kể chuyện)' })), vidBox),
    el('div', { class: 'set-grid' },
      el('div', { class: 'panel set-form' }, form.root, el('div', { class: 'save-bar' }, msg, resetBtn, saveBtn)),
      el('aside', { class: 'set-side' },
        lic ? el('div', { class: 'panel', id: 'ban-quyen' }, el('div', { class: 'panel-head' }, icon('shield'), el('h3', { text: 'Bản quyền' })), lic) : '',
        el('div', { class: 'panel' }, el('div', { class: 'panel-head' }, icon('cpu'), el('h3', { text: 'Máy của bạn' })), status ? healthList : errorState('Không đọc được tình trạng hệ thống')),
        el('div', { class: 'panel', id: 'cookie' }, el('div', { class: 'panel-head' }, icon('key'), el('h3', { text: 'Cookie tải video' })), ckBox),
        el('div', { class: 'panel', id: 'sua-loi' }, el('div', { class: 'panel-head' }, icon('wand'), el('h3', { text: 'Sửa lỗi nhanh' })), toolsPanel()),
        el('div', { class: 'panel' }, el('div', { class: 'panel-head' }, icon('sliders'), el('h3', { text: 'Khác' })),
          el('div', { class: 'opt-inline' }, el('div', { class: 'opt-label', text: 'Chuông báo khi video xong' }), el('label', { class: 'switch' }, chime, el('span', { class: 'switch-track' }, el('span', { class: 'switch-thumb' })))),
          el('p', { class: 'dim small', style: { marginTop: '12px' } }, 'File cấu hình: ', el('span', { class: 'mono', text: cfg.path || S.cfgPath || 'config.yaml' })),
          el('a', { class: 'btn btn-sm', href: '#/about' }, icon('info'), 'Giới thiệu')))));
  paintProviders();
  ready = true;
  updDirty();
  let focus = '';
  try { focus = sessionStorage.getItem('ic.settings.focus') || ''; sessionStorage.removeItem('ic.settings.focus'); } catch (_) { focus = ''; }
  if (focus) setTimeout(() => document.getElementById(focus)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80);
  return null;
}
