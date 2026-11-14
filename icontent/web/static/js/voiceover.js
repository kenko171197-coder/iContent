/* Trang Đọc văn bản: dán chữ, chọn giọng, ra file MP3 kèm phụ đề SRT khớp từng đoạn. Dùng cùng bộ giọng với lồng tiếng. */
import { S, api, busy, effEngine, el, emptyState, enc, ensureConfig, fillVoiceSelect, fmtAgo, fmtDur, icon, loadVoices, previewVoice, toast, voiceHooks } from './core.js';
import { myVoiceButton } from './myvoices.js';
import { waitTask } from './story.js';

const PREF = 'ic.voice.';
const pref = (k, d) => localStorage.getItem(PREF + k) ?? d;
const setPref = (k, v) => localStorage.setItem(PREF + k, v);
const MAX = 30000;

export async function viewVoiceover(main, alive) {
  main.classList.add('view-pad');
  const text = el('textarea', { class: 'input vo-text', rows: 12, maxlength: MAX, placeholder: 'Dán hoặc gõ văn bản cần đọc. Xuống dòng hai lần để nghỉ lâu hơn giữa hai đoạn.', value: pref('text', '') });
  const count = el('span', { class: 'dim small mono' });
  await ensureConfig();
  // ngôn ngữ của văn bản: tiếng Việt đọc bằng VieNeu, thứ tiếng khác bằng bộ đọc nhiều thứ tiếng (hoặc Microsoft)
  const lang = el('select', { class: 'input', onchange: () => { setPref('lang', lang.value); setPref('voice', ''); syncEngines(); fill(); } },
    (S.langs.length ? S.langs : [{ code: 'vi', name: 'Tiếng Việt' }]).map((l) => el('option', { value: l.code }, l.name)));
  lang.value = pref('lang', 'vi');
  const engine = el('select', { class: 'input', onchange: () => { setPref('engine', engine.value); setPref('voice', ''); fill(); } },
    [['vieneu', 'VieNeu (tiếng Việt, chạy trên máy)'], ['vox', 'Nhiều thứ tiếng (chạy trên máy)'], ['edge', 'Microsoft (cần mạng)']].map(([k, l]) => el('option', { value: k }, l)));
  engine.value = pref('engine', 'vieneu');
  const engineOf = () => effEngine(engine.value, lang.value);
  function syncEngines() {      // VieNeu chỉ đọc tiếng Việt; bộ đọc nhiều thứ tiếng phải tải ở Mô-đun AI
    for (const o of engine.options) o.disabled = (o.value === 'vieneu' && lang.value !== 'vi') || (o.value === 'vox' && !S.voices.vox_ready);
    if (engine.selectedOptions[0] && engine.selectedOptions[0].disabled) { engine.value = engineOf(); setPref('engine', engine.value); }
  }
  syncEngines();
  const voice = el('select', { class: 'input', onchange: () => setPref('voice', voice.value) });
  const fill = () => { syncEngines(); fillVoiceSelect(voice, engineOf(), { current: pref('voice', ''), lang: lang.value }); };
  loadVoices().then(() => { if (voice.isConnected) fill(); });
  fill();
  const hook = () => { if (!voice.isConnected) return false; fill(); return true; };
  voiceHooks.add(hook);
  const speedVal = el('span', { class: 'mono small' });
  const speed = el('input', { type: 'range', min: 0.7, max: 1.5, step: 0.05, value: pref('speed', '1'), oninput: () => { setPref('speed', speed.value); paintSpeed(); } });
  const paintSpeed = () => { speedVal.textContent = `${Number(speed.value).toFixed(2)}x`; };
  paintSpeed();
  const name = el('input', { class: 'input', placeholder: 'Tên file (để trống: lấy từ đầu văn bản)' });
  const myBtn = myVoiceButton(engineOf, (id) => {
    const e = lang.value === 'vi' ? 'vieneu' : 'vox';
    engine.value = e; setPref('engine', e); setPref('voice', id); fill();
  });
  const tryBtn = el('button', { class: 'btn btn-icon', title: 'Nghe thử giọng', 'aria-label': 'Nghe thử giọng', onclick: (e) => previewVoice(engineOf(), voice.value, e.currentTarget, lang.value) }, icon('play'));
  const bar = el('div', { class: 'sy-run', hidden: true });
  const list = el('div', { class: 'vo-list' });
  const paintCount = () => {
    const n = text.value.length;
    count.textContent = `${n.toLocaleString('vi-VN')} / ${MAX.toLocaleString('vi-VN')} ký tự, khoảng ${fmtDur(n / 15)} đọc`;
  };
  // lưu cả văn bản (tối đa 30.000 ký tự vẫn vừa bộ nhớ của trình duyệt): quay lại trang không bị mất phần sau
  text.addEventListener('input', () => { paintCount(); try { setPref('text', text.value); } catch (_) { /* bộ nhớ đầy: chỉ không lưu nháp */ } });
  paintCount();

  const makeBtn = el('button', {
    class: 'btn btn-primary', onclick: () => busy(makeBtn, async () => {
      if (!text.value.trim()) { toast('Chưa có chữ nào để đọc', 'info'); return; }
      const { task } = await api('POST', '/api/speech', { text: text.value, engine: engineOf(), voice: voice.value, speed: Number(speed.value), name: name.value.trim() });
      bar.hidden = false;
      try {
        const r = await waitTask(task, (t) => bar.replaceChildren(el('span', { class: 'sy-run-t', text: t.message || 'Đang đọc…' }),
          el('div', { class: 'sy-run-bar' }, el('i', { style: { width: `${Math.round((t.progress || 0) * 100)}%` } }))));
        toast(`Xong: ${r.name}, ${fmtDur(r.duration)}`, 'success');
        await paintList();
      } finally { bar.hidden = true; }
    }),
  }, icon('mic'), 'Tạo giọng đọc');

  async function paintList() {
    const { items } = await api('GET', '/api/speech');
    if (!alive()) return;
    if (!items.length) { list.replaceChildren(emptyState('Chưa có file nào', 'File giọng đọc tạo xong nằm trong thư mục output, mục giong_doc.', null)); return; }
    list.replaceChildren(...items.map((it) => {
      const del = el('button', {
        class: 'btn btn-xs btn-icon btn-ghost', title: 'Xóa file', 'aria-label': 'Xóa file', onclick: () => busy(del, async () => {
          await api('DELETE', `/api/speech/file/${enc(it.name)}`); await paintList();
        }),
      }, icon('trash'));
      return el('div', { class: 'vo-item' },
        el('div', { class: 'vo-item-t' }, el('b', { text: it.name }), el('span', { class: 'dim small', text: `${it.duration ? fmtDur(it.duration) + ' · ' : ''}${fmtAgo(it.at)}` }),
          it.text ? el('span', { class: 'dim small vo-snip', text: it.text }) : null),
        el('audio', { src: `/api/speech/file/${enc(it.name)}`, controls: true, preload: 'none' }),
        el('div', { class: 'vo-acts' },
          el('a', { class: 'btn btn-xs', href: `/api/speech/file/${enc(it.name)}`, download: it.name }, icon('download'), 'MP3'),
          it.srt ? el('a', { class: 'btn btn-xs', href: `/api/speech/file/${enc(it.name.replace(/\.mp3$/i, '.srt'))}`, download: '' }, icon('sub'), 'Phụ đề') : null,
          del));
    }));
  }

  main.append(
    el('div', { class: 'page-head' },
      el('div', { class: 'page-head-text' },
        el('div', { class: 'eyebrow', text: 'Đọc văn bản' }),
        el('h1', { text: 'Biến chữ thành giọng đọc' }),
        el('p', { text: 'Dán bài viết, truyện, kịch bản, chọn giọng: ra file MP3 kèm phụ đề SRT khớp từng câu, dùng ngay cho video. Giọng VieNeu chạy hẳn trên máy, đọc bao nhiêu cũng được.' })),
      el('div', { class: 'actions' }, el('button', { class: 'btn btn-ghost', onclick: () => api('POST', '/api/speech/reveal') }, icon('folder'), 'Thư mục'))),
    el('div', { class: 'vo-grid' },
      el('div', { class: 'vo-main' }, text, el('div', { class: 'vo-count' }, count)),
      el('div', { class: 'vo-side' },
        el('label', { class: 'field' }, el('span', { class: 'label', text: 'Ngôn ngữ' }), lang),
        el('label', { class: 'field' }, el('span', { class: 'label', text: 'Bộ giọng' }), engine),
        el('label', { class: 'field' }, el('span', { class: 'label', text: 'Giọng' }), el('div', { class: 'voice-pick' }, voice, tryBtn, myBtn)),
        el('label', { class: 'field' }, el('span', { class: 'label', text: 'Tốc độ đọc' }), el('div', { class: 'sy-range' }, speed, speedVal)),
        el('label', { class: 'field' }, el('span', { class: 'label', text: 'Tên file' }), name),
        makeBtn, bar)),
    el('h3', { class: 'ed-head', text: 'File đã tạo' }),
    list);
  await paintList();
  return () => voiceHooks.delete(hook);
}
