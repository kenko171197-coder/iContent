/* Trang Kể chuyện: kịch bản thành video. Mỗi cảnh một ảnh (tự có, từ thư viện, hoặc Gemini vẽ giữ đúng nhân vật), lời dẫn và phụ đề
 * tự khớp, máy quay chuyển động nhẹ. Ảnh và ảnh mẫu do máy chủ quản lý: lưu câu chuyện chỉ gửi phần chữ và thiết lập. */
import {
  S, api, busy, confirmDialog, debounce, effEngine, el, emptyState, enc, fillVoiceSelect, fmtAgo, fmtDur, icon, modalHead, openModal, pollSoon, previewVoice,
  queueListeners, toast, uploadFile, videoModal, voiceHooks,
} from './core.js';
import { editorSupport, openStoryInEditor } from './editor.js';
import { itemErrorToast } from './fixes.js';
import { myVoiceButton } from './myvoices.js';

const MOTION_LABEL = { auto: 'Tự chọn', zoom_in: 'Phóng vào', zoom_out: 'Lùi ra', pan_left: 'Lia sang trái', pan_right: 'Lia sang phải', pan_up: 'Lia lên', pan_down: 'Lia xuống', still: 'Đứng yên' };
const SUB_LABEL = { box: 'Nền hộp mờ', classic: 'Chữ viền đen', tiktok: 'TikTok (đổi màu theo lời)', pop: 'Chữ to nổi bật', karaoke: 'Karaoke' };
const ASPECT_LABEL = { '9:16': 'Dọc 9:16 (TikTok, Shorts)', '16:9': 'Ngang 16:9 (YouTube)', '1:1': 'Vuông 1:1' };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
/** Mã do giao diện tự tạo, cùng dạng máy chủ chấp nhận: không phải chờ máy chủ cấp mã rồi ghép lại theo thứ tự. */
const newId = (p) => p + [...crypto.getRandomValues(new Uint8Array(4))].map((b) => b.toString(16).padStart(2, '0')).join('');

/** Chờ một việc chạy nền của máy chủ xong. onTick(task) để hiện tiến độ. */
export async function waitTask(tid, onTick) {
  for (;;) {
    const t = await api('GET', `/api/tasks/${enc(tid)}`);
    if (t.state === 'done') return t.result;
    if (t.state === 'error') throw new Error(t.error || 'Tác vụ lỗi');
    if (onTick) onTick(t);
    await sleep(700);
  }
}

function putFile(url, file) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open('PUT', url);
    x.onload = () => {
      let j = {};
      try { j = JSON.parse(x.responseText); } catch (_) { /* bỏ qua */ }
      if (x.status >= 200 && x.status < 300) resolve(j); else reject(new Error(j.detail || `Lỗi ${x.status}`));
    };
    x.onerror = () => reject(new Error('Không gửi được file'));
    x.send(file);
  });
}

function pickFiles(accept, multiple = false) {
  return new Promise((resolve) => {
    const inp = el('input', { type: 'file', accept, hidden: true, multiple });
    let done = false;
    const finish = (files) => { if (done) return; done = true; window.removeEventListener('focus', onFocus); inp.remove(); resolve(files); };
    // bấm Hủy: trình duyệt mới báo sự kiện cancel; dự phòng bằng lúc cửa sổ được focus lại mà chưa có file
    const onFocus = () => setTimeout(() => { if (!inp.files.length) finish([]); }, 600);
    inp.onchange = () => finish([...inp.files]);
    inp.addEventListener('cancel', () => finish([]));
    document.body.append(inp);
    window.addEventListener('focus', onFocus);
    inp.click();
  });
}
const pickFile = async (accept) => (await pickFiles(accept))[0] || null;
const IMAGE_TYPES = 'image/png,image/jpeg,image/webp';

/** Mỗi ảnh thành một cảnh mới. Gửi lần lượt để giữ đúng thứ tự đã chọn. */
async function addImageScenes(sid, files, onEach) {
  let last = null;
  for (const [k, f] of files.entries()) {
    try { last = (await putFile(`/api/stories/${enc(sid)}/scenes-from-image`, f)).story; } catch (e) { toast(`${f.name}: ${e.message}`, 'error'); }
    if (onEach) onEach(k + 1, files.length);
  }
  return last;
}

/** Vẽ lại một vùng mà không làm mất ô đang gõ: ảnh vẽ xong giữa lúc đang gõ lời dẫn thì con trỏ vẫn ở nguyên chỗ cũ. */
function keepFocus(box, paint) {
  const a = document.activeElement;
  const key = a && box.contains(a) ? a.dataset.key : null;
  const sel = key && 'selectionStart' in a ? [a.selectionStart, a.selectionEnd, a.scrollTop] : null;
  paint();
  if (!key) return;
  const b = box.querySelector(`[data-key="${CSS.escape(key)}"]`);
  if (!b) return;
  b.focus({ preventScroll: true });
  if (sel) { try { b.setSelectionRange(sel[0], sel[1]); b.scrollTop = sel[2]; } catch (_) { /* ô không có con trỏ */ } }
}

/** Cảnh đang được AI vẽ, theo câu chuyện. Giữ qua các lần vẽ lại thẻ và chuyển trang: bấm vẽ lần nữa là trả tiền lần nữa. */
const drawing = new Map();
const drawingOf = (sid) => { if (!drawing.has(sid)) drawing.set(sid, new Set()); return drawing.get(sid); };
const clipping = new Map();      // câu chuyện -> cảnh đang lấy video (tải từ kho, AI làm clip); "*" là cả câu chuyện
const clippingOf = (sid) => { if (!clipping.has(sid)) clipping.set(sid, new Set()); return clipping.get(sid); };
const SRC_SHORT = { pexels: 'Pexels', pixabay: 'Pixabay', wikimedia: 'Wikimedia' };
const usd = (x) => (Math.round(x * 100) / 100).toLocaleString('vi-VN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const fileUrl = (sid, kind, name) => `/api/stories/${enc(sid)}/file/${kind}/${enc(name)}`;

export async function viewStory(main, alive, arg) {
  main.classList.add('view-pad');
  const opts = await api('GET', '/api/story/options');
  if (!alive()) return null;
  return arg ? storyEditor(main, alive, arg, opts) : storyList(main, alive, opts);
}

// ------------------------------------------------------------------ danh sách
async function storyList(main, alive, opts) {
  const { items } = await api('GET', '/api/stories');
  if (!alive()) return null;
  const newBtn = el('button', { class: 'btn btn-primary', onclick: () => newStoryDialog(opts) }, icon('plus'), 'Câu chuyện mới');
  const grid = el('div', { class: 'sy-list' });
  const paint = (list) => grid.replaceChildren(...list.map((s) => {
    const del = el('button', {
      class: 'btn btn-xs btn-icon btn-ghost', title: 'Xóa câu chuyện', 'aria-label': 'Xóa câu chuyện', onclick: async (e) => {
        e.preventDefault();
        if (!(await confirmDialog('Xóa câu chuyện?', `"${s.title}" cùng ảnh và lời dẫn sẽ bị xóa. Video đã dựng trong thư mục output vẫn còn.`, { okText: 'Xóa', danger: true }))) return;
        await busy(del, () => api('DELETE', `/api/stories/${enc(s.id)}`));
        paint((await api('GET', '/api/stories')).items);
      },
    }, icon('trash'));
    return el('a', { class: 'sy-card', href: '#/story/' + enc(s.id) },
      s.cover ? el('img', { src: fileUrl(s.id, 'img', s.cover), alt: '', loading: 'lazy' }) : el('div', { class: 'sy-card-empty' }, icon('image')),
      el('div', { class: 'sy-card-t' }, el('b', { text: s.title }), el('span', { class: 'dim small', text: `${s.scenes} cảnh · ${s.aspect} · ${fmtAgo(s.updated)}` + (s.output ? ' · đã dựng' : '') })),
      del);
  }));
  paint(items);
  main.append(...[
    el('div', { class: 'page-head' },
      el('div', { class: 'page-head-text' },
        el('div', { class: 'eyebrow', text: 'Kể chuyện' }),
        el('h1', { text: 'Video kể chuyện từ ảnh' }),
        el('p', { text: 'Viết hoặc dán kịch bản, mỗi cảnh một ảnh: ảnh tự có, ảnh trong thư viện, hoặc Gemini vẽ giữ đúng nhân vật qua mọi cảnh. Lời dẫn và phụ đề tự khớp, máy quay chuyển động nhẹ, có nhạc nền.' })),
      el('div', { class: 'actions' }, newBtn)),
    opts.image_ai ? null : el('div', { class: 'ed-note sy-note' }, icon('info'), el('span', { text: 'Chưa có key tạo ảnh nào. Vẫn làm được: dùng ảnh tự có, hoặc ở từng cảnh bấm Chép lời nhắn, dán sang ChatGPT hay Copilot trên web để vẽ miễn phí, rồi bấm Dán ảnh. Muốn Studio566 tự vẽ: Cài đặt, mục Tạo ảnh AI (Gemini, OpenAI, Meta Muse, hoặc Cloudflare có hạn mức miễn phí).' })),
    items.length ? grid : emptyState('Chưa có câu chuyện nào', 'Bấm Câu chuyện mới, viết một ý tưởng cho AI hoặc dán kịch bản của mình.', null),
  ].filter(Boolean));
  return null;
}

function newStoryDialog(opts) {
  let mode = opts.writer_ai ? 'ai' : 'script';
  const title = el('input', { class: 'input', placeholder: 'Tên câu chuyện (để trống AI sẽ đặt)' });
  const text = el('textarea', { class: 'input', rows: 9 });
  const secs = el('select', { class: 'input' }, [[30, '30 giây'], [60, '1 phút'], [90, '1 phút rưỡi'], [180, '3 phút'], [300, '5 phút']].map(([v, l]) => el('option', { value: v, selected: v === 60 }, l)));
  const aspect = el('select', { class: 'input' }, Object.entries(ASPECT_LABEL).map(([v, l]) => el('option', { value: v }, l)));
  const style = el('select', { class: 'input' }, opts.styles.map((s) => el('option', { value: s.id, selected: s.id === 'pixar' }, s.label)));
  const aiSplit = el('input', { type: 'checkbox', checked: opts.writer_ai, disabled: !opts.writer_ai });
  const segAi = el('button', { type: 'button', class: 'seg-btn', disabled: !opts.writer_ai, onclick: () => { mode = 'ai'; paint(); },
    title: opts.writer_local ? 'AI viết ngay trên máy (Mô-đun AI miễn phí), không cần key' : opts.writer_ai ? '' : 'Cần key Gemini (gói miễn phí viết được) hoặc tải Dịch offline và Vẽ ảnh offline để AI viết trên máy' },
    opts.writer_local ? 'AI viết từ ý tưởng (trên máy)' : 'AI viết từ ý tưởng');
  const segScript = el('button', { type: 'button', class: 'seg-btn', onclick: () => { mode = 'script'; paint(); } }, 'Tôi có kịch bản');
  const segImages = el('button', { type: 'button', class: 'seg-btn', onclick: () => { mode = 'images'; paint(); } }, 'Từ ảnh của tôi');
  const imagesNote = el('p', { class: 'muted small', text: 'Bấm Tạo rồi chọn nhiều ảnh cùng lúc (giữ Ctrl). Mỗi ảnh thành một cảnh theo đúng thứ tự, sau đó thêm lời dẫn cho từng cảnh nếu muốn, cảnh không có lời dài 3 giây.' });
  const lenRow = el('label', { class: 'field' }, el('span', { class: 'label', text: 'Độ dài' }), secs);
  const splitRow = el('label', { class: 'check' }, aiSplit, opts.writer_ai ? ' Nhờ AI chia cảnh, gợi ý hình và nhân vật (giữ nguyên lời)' : ' Chia cảnh theo đoạn và câu (muốn AI gợi ý hình: dán key Gemini miễn phí, hoặc tải Mô-đun AI miễn phí trong Cài đặt)');
  function paint() {
    segAi.classList.toggle('active', mode === 'ai');
    segScript.classList.toggle('active', mode === 'script');
    segImages.classList.toggle('active', mode === 'images');
    text.hidden = mode === 'images';
    imagesNote.hidden = mode !== 'images';
    text.placeholder = mode === 'ai'
      ? 'Ý tưởng câu chuyện, ví dụ: Chuyện cổ tích về cậu bé nghèo ở làng chài nhặt được vỏ ốc thần, giọng kể ấm áp cho thiếu nhi, kết thúc có hậu.'
      : 'Dán kịch bản. Mỗi đoạn văn sẽ thành ít nhất một cảnh, đoạn dài được chia theo câu.';
    lenRow.hidden = mode !== 'ai';
    splitRow.hidden = mode !== 'script';
  }
  paint();
  const ok = el('button', {
    class: 'btn btn-primary', onclick: () => busy(ok, async () => {
      const t = text.value.trim();
      let files = [];
      if (mode === 'images') {
        files = await pickFiles(IMAGE_TYPES, true);
        if (!files.length) return;
      } else if (!t) { toast(mode === 'ai' ? 'Viết ý tưởng trước' : 'Dán kịch bản trước', 'info'); return; }
      const s = await api('POST', '/api/stories', { title: title.value.trim(), aspect: aspect.value, style: style.value });
      try {
        if (mode === 'images') {
          await addImageScenes(s.id, files, (n, k) => { ok.lastChild.textContent = ` Đang thêm ảnh ${n}/${k}`; });
        } else if (mode === 'ai' || aiSplit.checked) {
          ok.lastChild.textContent = ' AI đang viết…';
          const { task } = await api('POST', `/api/stories/${enc(s.id)}/write`, mode === 'ai' ? { topic: t, seconds: Number(secs.value) } : { script: t });
          await waitTask(task);
        } else {
          await api('POST', `/api/stories/${enc(s.id)}/split`, { text: t });
        }
      } catch (e) {
        toast('Đã tạo câu chuyện nhưng chưa có cảnh: ' + e.message, 'error', { timeout: 9000 });
      }
      if (!closed) { m.close(); location.hash = '#/story/' + enc(s.id); } else toast(`Câu chuyện "${s.title}" đã sẵn sàng trong trang Kể chuyện`, 'success');
    }),
  }, icon('spark'), el('span', { text: ' Tạo' }));
  let closed = false;
  const m = openModal([
    modalHead('film', 'Câu chuyện mới', () => m),
    el('div', { class: 'modal-body sy-new' },
      el('div', { class: 'seg' }, segAi, segScript, segImages),
      title, text, imagesNote,
      el('div', { class: 'sy-row3' }, lenRow, el('label', { class: 'field' }, el('span', { class: 'label', text: 'Khung hình' }), aspect),
        el('label', { class: 'field' }, el('span', { class: 'label', text: 'Phong cách ảnh' }), style)),
      splitRow),
    el('div', { class: 'modal-foot' }, el('button', { class: 'btn btn-ghost', onclick: () => m.close() }, 'Hủy'), ok),
  ], { cls: 'modal-md', onClose: () => { closed = true; } });
  setTimeout(() => text.focus(), 50);
}

// ------------------------------------------------------------------ trình sửa câu chuyện
async function storyEditor(main, alive, sid, opts) {
  let story = await api('GET', `/api/stories/${enc(sid)}`);
  if (!alive()) return null;
  story.synced = story.updated;
  const cleanups = [];
  let saving = Promise.resolve();
  const saveNow = () => { saving = saving.then(() => api('PUT', `/api/stories/${enc(sid)}`, story).then(syncManaged).catch((e) => toast('Chưa lưu được: ' + e.message, 'error'))); return saving; };
  const save = debounce(saveNow, 600);
  const touch = () => { story.updated = Date.now() / 1000; save(); };

  /** Ảnh và ảnh mẫu lấy từ máy chủ; phần chữ đang gõ giữ nguyên. */
  const deleted = new Set();      // cảnh vừa xóa ở đây mà chưa lưu xong: lần tải lại không được đưa nó trở lại
  function syncManaged(srv) {
    const before = story.synced || 0;
    story.synced = srv.updated;      // máy chủ: cảnh nào thêm sau mốc này mà bản gửi lên không có thì là cảnh giao diện chưa biết, không xóa
    const scenes = new Map(srv.scenes.map((x) => [x.id, x]));
    let changed = false;
    for (const sc of story.scenes) {
      const s2 = scenes.get(sc.id);
      if (s2 && (s2.image !== sc.image || (s2.images || []).join() !== (sc.images || []).join())) { sc.image = s2.image; sc.images = s2.images; changed = true; }
      if (s2 && ((s2.clip || '') !== (sc.clip || '') || (s2.clips || []).join() !== (sc.clips || []).join())) { sc.clip = s2.clip || ''; sc.clips = s2.clips || []; sc.clip_meta = s2.clip_meta || {}; changed = true; }
      if (s2 && s2.broll && !sc.broll) { sc.broll = s2.broll; changed = true; }
    }
    for (const ch of story.characters) {
      const c2 = srv.characters.find((x) => x.id === ch.id);
      if (c2 && (c2.refs || []).join() !== (ch.refs || []).join()) { ch.refs = c2.refs; changed = true; }
    }
    // cảnh máy chủ vừa thêm (thêm nhiều ảnh) mà giao diện chưa có: đưa vào, nếu không lần lưu sau sẽ coi là đã bị xóa
    const mine = new Set(story.scenes.map((x) => x.id));
    for (const s2 of srv.scenes) {
      if (!mine.has(s2.id) && !deleted.has(s2.id) && (s2.created || 0) > before) { story.scenes.push(s2); changed = true; }
    }
    if (!srv.scenes.some((x) => deleted.has(x.id))) deleted.clear();
    const editedKey = (x) => (x || []).map((e) => e.path).join('|');
    const resultChanged = srv.output !== story.output || srv.rendered !== story.rendered || editedKey(srv.edited) !== editedKey(story.edited);
    story.output = srv.output;
    story.rendered = srv.rendered;
    story.edited = srv.edited || [];
    if (changed) { paintScenes(); paintChars(); }
    paintTop(resultChanged);
  }
  async function reload() {
    await saving;
    syncManaged(await api('GET', `/api/stories/${enc(sid)}`));
  }
  const ensureIds = () => saveNow();      // máy chủ phải biết cảnh, nhân vật mới trước khi gọi việc gắn với nó

  // ---------- đầu trang
  const titleInp = el('input', { class: 'input sy-title', value: story.title, 'aria-label': 'Tên câu chuyện', oninput: () => { story.title = titleInp.value; touch(); } });
  const aspectSel = el('select', { class: 'input', title: 'Khung hình', onchange: () => { story.aspect = aspectSel.value; touch(); } },
    Object.entries(ASPECT_LABEL).map(([v, l]) => el('option', { value: v, selected: v === story.aspect }, l)));
  const styleSel = el('select', { class: 'input', title: 'Phong cách ảnh khi AI vẽ', onchange: () => { story.style = styleSel.value; touch(); } },
    opts.styles.map((s) => el('option', { value: s.id, selected: s.id === story.style }, s.label)));
  const drawAllBtn = el('button', { class: 'btn', onclick: () => busy(drawAllBtn, drawAll) }, icon('wand'), el('span'));
  const renderBtn = el('button', { class: 'btn btn-primary', onclick: () => busy(renderBtn, startRender) }, icon('film'), 'Dựng video');
  const editBtn = el('button', {
    class: 'btn', title: 'Mở trong Trình dựng: mỗi cảnh một clip riêng, kéo đổi chỗ, cắt, thêm chữ, chuyển cảnh, nhạc như CapCut',
    onclick: () => busy(editBtn, async () => {
      const missing = story.scenes.filter((x) => !x.image && !x.clip).length;
      if (!story.scenes.length) { toast('Câu chuyện chưa có cảnh nào', 'info'); return; }
      if (missing) { toast(`Còn ${missing} cảnh chưa có ảnh: thêm ảnh trước rồi mở Trình dựng`, 'warn'); return; }
      const miss = await editorSupport();
      if (miss.length) { toast('Máy này chưa mở được Trình dựng: ' + miss.join('; '), 'error', { timeout: 9000 }); return; }
      await ensureIds(); await saveNow();
      await openStoryInEditor(sid);
    }),
  }, icon('scissors'), 'Trình dựng');
  const runbar = el('div', { class: 'sy-run', hidden: true });
  function paintTop(resultChanged = false) {
    const missing = story.scenes.filter((s) => !s.image && (s.text || s.prompt)).length;
    const all = drawingOf(sid).has('*');
    drawAllBtn.lastChild.textContent = all ? ' Đang vẽ…' : missing ? ` Vẽ ${missing} ảnh còn thiếu` : ' Đủ ảnh';
    drawAllBtn.disabled = all || !missing || !opts.image_ai;
    drawAllBtn.title = opts.image_ai ? 'AI vẽ các cảnh chưa có ảnh, giữ đúng nhân vật theo ảnh mẫu' : 'Cần key tạo ảnh (Cài đặt, mục Tạo ảnh AI). Không có key: dùng Chép lời nhắn và Dán ảnh ở từng cảnh';
    if (resultChanged || !resultBox.firstChild) paintResult();
  }
  // nguồn ảnh của câu chuyện
  const provSel = el('select', { class: 'input', title: 'Nguồn vẽ ảnh AI', onchange: () => { story.image_provider = provSel.value; touch(); } },
    el('option', { value: '' }, 'Nguồn ảnh: tự chọn (miễn phí trước)'),
    (opts.image_providers || []).map((p) => el('option', { value: p.id, selected: p.id === story.image_provider, disabled: p.paid && p.ready && !p.usable && p.id !== story.image_provider },
      p.name + (p.paid ? ' (trả phí)' : '') + (!p.ready ? (p.local ? ', chưa tải' : ', chưa có key') : p.paid && !p.usable ? ', đang khóa' : p.status === 'billing' ? ', key chưa bật thanh toán' : ''))));
  const provOf = () => (opts.image_providers || []).find((p) => p.id === story.image_provider) || (opts.image_providers || []).find((p) => p.ready);

  // ---------- các cảnh
  const sceneBox = el('div', { class: 'sy-scenes' });
  const addSceneBtn = el('button', { class: 'btn sy-add', onclick: () => { story.scenes.push({ id: newId('n'), text: '', prompt: '', characters: [], motion: 'auto', image: '', images: [] }); paintScenes(); touch(); } }, icon('plus'), 'Thêm cảnh');
  const addImagesBtn = el('button', {
    class: 'btn sy-add', title: 'Chọn nhiều ảnh, mỗi ảnh thành một cảnh mới ở cuối', onclick: () => busy(addImagesBtn, async () => {
      const files = await pickFiles(IMAGE_TYPES, true);
      if (!files.length) return;
      await saveNow();
      await addImageScenes(sid, files, (n, k) => { addImagesBtn.lastChild.textContent = ` Đang thêm ${n}/${k}`; });
      addImagesBtn.lastChild.textContent = ' Thêm nhiều ảnh';
      await reload();
      paintScenes();
    }),
  }, icon('image'), el('span', { text: ' Thêm nhiều ảnh' }));
  function paintScenes() {
    keepFocus(sceneBox, () => sceneBox.replaceChildren(...story.scenes.map((sc, i) => sceneCard(sc, i)), el('div', { class: 'btn-row sy-adds' }, addSceneBtn, addImagesBtn)));
    paintTop();
  }
  function sceneCard(sc, i) {
    const cm = (sc.clip && (sc.clip_meta || {})[sc.clip]) || null;
    let img;
    if (sc.clip) {
      img = el('video', { src: fileUrl(sid, 'clip', sc.clip), poster: sc.image ? fileUrl(sid, 'img', sc.image) : null, muted: true, loop: true, playsinline: true, preload: 'metadata',
        'aria-label': `Clip cảnh ${i + 1}` });
      img.muted = true;
    } else {
      img = sc.image ? el('img', { src: fileUrl(sid, 'img', sc.image), alt: `Ảnh cảnh ${i + 1}`, loading: 'lazy' }) : el('div', { class: 'sy-noimg' }, icon('image'), el('span', { text: 'Chưa có ảnh' }));
    }
    const nVar = (sc.images || []).length + (sc.clips || []).length;
    const imgBox = el('button', {
      class: 'sy-img', title: nVar > 1 ? 'Chọn lại một trong các bản đã có (ảnh và clip)' : sc.clip ? 'Clip của cảnh' : 'Ảnh của cảnh', onclick: () => variants(sc),
      onmouseenter: () => { if (img.tagName === 'VIDEO') img.play().catch(() => {}); }, onmouseleave: () => { if (img.tagName === 'VIDEO') { img.pause(); } },
    }, img,
      sc.clip ? el('span', { class: 'sy-badge sy-badge-clip', title: cm ? (cm.src === 'ai' ? 'Clip tạo bằng AI' : `${cm.title || 'Video'}${cm.author ? ' của ' + cm.author : ''} (${cm.source_name || cm.src}, ${cm.license || ''})`) : 'Video' },
        icon('film'), cm && cm.src === 'ai' ? 'AI' : cm ? (SRC_SHORT[cm.src] || 'Video') : 'Video') : null,
      nVar > 1 ? el('span', { class: 'sy-badge', text: `${nVar} bản` }) : null);
    const inFlight = drawingOf(sid).has(sc.id) || drawingOf(sid).has('*');
    const clipBusy = clippingOf(sid).has(sc.id) || clippingOf(sid).has('*');
    if (inFlight || clipBusy) imgBox.classList.add('is-busy');
    const vp = (opts.video_providers || [])[0];
    const stockBtn = el('button', {
      class: 'btn btn-xs', disabled: clipBusy, title: 'Tìm video quay thật miễn phí (Pexels, Pixabay, Wikimedia) cho cảnh này',
      onclick: () => busy(stockBtn, async () => { await ensureIds(); await saveNow(); stockPicker(sc); }),
    }, icon('search'), 'Video nền');
    const aiClipBtn = el('button', {
      class: 'btn btn-xs' + (vp && vp.usable ? '' : ' btn-ghost'), disabled: clipBusy || !(vp && vp.usable),
      title: vp && vp.usable ? `AI biến ${sc.image ? 'ảnh cảnh' : 'mô tả'} thành clip chuyển động (${vp.name}, trả phí theo giây)`
        : vp && vp.ready ? 'Trả phí: đang tắt tính năng trả phí (Cài đặt, mục Chi phí)' : 'Trả phí: cần key Gemini đã bật thanh toán (Cài đặt, mục Video nền và clip AI)',
      onclick: () => busy(aiClipBtn, async () => {
        await ensureIds(); await saveNow();
        const e = await api('GET', `/api/stories/${enc(sid)}/animate/estimate?scene=${enc(sc.id)}`);
        if (!(await confirmDialog(`AI làm clip ${e.seconds} giây cho cảnh ${i + 1}?`, `${vp.name}, ${e.resolution}: khoảng ${usd(e.usd)} USD. ${sc.image ? 'Clip đi từ ảnh cảnh nên giữ đúng nhân vật.' : 'Cảnh chưa có ảnh: AI tạo từ mô tả và ảnh mẫu nhân vật.'} Lỗi thì không tính tiền.`, { okText: 'Làm clip' }))) return;
        const { task } = await api('POST', `/api/stories/${enc(sid)}/scenes/${enc(sc.id)}/animate`);
        await runClipTask(sc.id, task, imgBox, aiClipBtn);
      }),
    }, icon('film'), 'AI làm clip');
    const imageBack = sc.clip ? el('button', {
      class: 'btn btn-xs btn-ghost', title: 'Cảnh dùng lại ảnh có máy quay chuyển động (clip vẫn giữ, chọn lại được)',
      onclick: () => busy(imageBack, async () => { syncManaged(await api('POST', `/api/stories/${enc(sid)}/scenes/${enc(sc.id)}/clip/use`, { name: '' })); }),
    }, icon('image'), 'Dùng ảnh') : null;
    const genBtn = el('button', {
      class: 'btn btn-xs', disabled: !opts.image_ai || inFlight, title: opts.image_ai ? 'AI vẽ ảnh cho cảnh này' : 'Cần key tạo ảnh (Cài đặt, mục Tạo ảnh AI)',
      onclick: () => busy(genBtn, async () => {
        const set = drawingOf(sid);
        if (set.has(sc.id) || set.has('*')) return;
        await ensureIds(); await saveNow();
        const { task } = await api('POST', `/api/stories/${enc(sid)}/scenes/${enc(sc.id)}/generate`);
        set.add(sc.id);
        imgBox.classList.add('is-busy');
        try { await waitTask(task); } finally { set.delete(sc.id); imgBox.classList.remove('is-busy'); }
        await reload();
        paintScenes();
      }),
    }, icon('wand'), inFlight ? 'Đang vẽ' : sc.image ? 'Vẽ lại' : 'AI vẽ');
    const copyBtn = el('button', {
      class: 'btn btn-xs btn-icon', title: 'Chép lời nhắn (kèm mô tả nhân vật) để dán sang ChatGPT, Copilot trên web vẽ miễn phí, rồi bấm Dán ảnh', 'aria-label': 'Chép lời nhắn',
      onclick: () => busy(copyBtn, async () => {
        await ensureIds(); await saveNow();
        const r = await api('GET', `/api/stories/${enc(sid)}/scenes/${enc(sc.id)}/prompt`);
        await navigator.clipboard.writeText(r.prompt);
        toast(r.refs.length ? `Đã chép lời nhắn. Gửi kèm ${r.refs.length} ảnh mẫu nhân vật (trong mục Nhân vật) để vẽ giống. Vẽ xong chép ảnh rồi bấm Dán ảnh.` : 'Đã chép lời nhắn. Vẽ xong, chép ảnh rồi bấm Dán ảnh ở cảnh này.', 'success', { timeout: 7000 });
      }),
    }, icon('copy'));
    const pasteBtn = el('button', {
      class: 'btn btn-xs btn-icon', title: 'Dán ảnh đã chép (từ ChatGPT, Copilot, trình duyệt...)', 'aria-label': 'Dán ảnh',
      onclick: () => busy(pasteBtn, async () => {
        let blob = null;
        try {
          for (const item of await navigator.clipboard.read()) {
            const type = item.types.find((t) => t.startsWith('image/'));
            if (type) { blob = await item.getType(type); break; }
          }
        } catch (_) { /* trình duyệt không cho đọc: hướng dẫn dùng Ctrl+V */ }
        if (!blob) { toast('Chưa có ảnh trong bộ nhớ tạm. Chuột phải vào ảnh, chọn Sao chép hình ảnh, rồi bấm lại (hoặc bấm vào cảnh và nhấn Ctrl+V).', 'info', { timeout: 7000 }); return; }
        await pasteImage(sc, blob);
      }),
    }, icon('paste'));
    const upBtn = el('button', {
      class: 'btn btn-xs', title: 'Dùng ảnh trên máy', onclick: () => busy(upBtn, async () => {
        const f = await pickFile(IMAGE_TYPES);
        if (!f) return;
        await ensureIds();
        syncManaged((await putFile(`/api/stories/${enc(sid)}/scenes/${enc(sc.id)}/image`, f)).story);
      }),
    }, icon('upload'), 'Tải ảnh');
    const libBtn = el('button', { class: 'btn btn-xs btn-icon', title: 'Chọn từ thư viện ảnh (trang Sửa ảnh)', 'aria-label': 'Thư viện ảnh', onclick: () => fromLibrary(sc) }, icon('grid'));
    const text = el('textarea', { class: 'input sy-text', rows: 3, 'data-key': sc.id + ':text', placeholder: 'Lời dẫn của cảnh (để trống: cảnh im lặng 3 giây)', value: sc.text, oninput: () => { sc.text = text.value; touch(); } });
    const prompt = el('textarea', { class: 'input', rows: 2, 'data-key': sc.id + ':prompt', placeholder: 'Mô tả hình cho AI vẽ (để trống: AI vẽ theo lời dẫn)', value: sc.prompt, oninput: () => { sc.prompt = prompt.value; touch(); } });
    const broll = el('input', { class: 'input input-sm', 'data-key': sc.id + ':broll', placeholder: 'Từ khóa tìm video nền, tiếng Anh (để trống: AI tự nghĩ)', value: sc.broll || '',
      title: 'Ví dụ: rainy city street night, old man fishing lake', oninput: () => { sc.broll = broll.value; touch(); } });
    const chips = el('div', { class: 'sy-chips' }, story.characters.map((c) => el('button', {
      type: 'button', class: 'sy-chip' + (sc.characters.includes(c.id) ? ' on' : ''), title: 'Nhân vật có trong cảnh: AI sẽ vẽ giống ảnh mẫu',
      onclick: (e) => { sc.characters = sc.characters.includes(c.id) ? sc.characters.filter((x) => x !== c.id) : [...sc.characters, c.id].slice(0, 4); e.currentTarget.classList.toggle('on'); touch(); },
    }, c.name || 'Nhân vật')));
    const motion = el('select', { class: 'input input-sm', title: 'Chuyển động máy quay', onchange: () => { sc.motion = motion.value; touch(); } },
      Object.entries(MOTION_LABEL).map(([v, l]) => el('option', { value: v, selected: v === sc.motion }, l)));
    const dur = el('input', {
      class: 'input input-sm sy-dur', type: 'number', min: 0.5, max: 60, step: 0.5, value: sc.duration || '', placeholder: 'tự động',
      title: 'Thời lượng cảnh (giây). Cảnh có lời: đây là tối thiểu, lời dài hơn thì cảnh tự dài theo. Để trống: theo lời dẫn, cảnh im lặng 3 giây.',
      'aria-label': 'Thời lượng cảnh (giây)', 'data-key': sc.id + ':dur',
      oninput: () => { const v = parseFloat(dur.value); sc.duration = v > 0 ? v : null; touch(); },
    });
    const trans = el('select', { class: 'input input-sm', title: 'Chuyển cảnh vào cảnh này', disabled: i === 0 && !(story.intro && story.intro.enabled), onchange: () => { sc.transition = trans.value; touch(); } },
      el('option', { value: '' }, 'Chuyển cảnh: chung'),
      (opts.transitions || []).map((x) => el('option', { value: x.id, selected: x.id === sc.transition }, x.label)));
    const listenBtn = el('button', {
      class: 'btn btn-xs btn-icon', title: 'Nghe thử lời dẫn', 'aria-label': 'Nghe thử lời dẫn', onclick: () => busy(listenBtn, async () => {
        if (!sc.text.trim()) { toast('Cảnh chưa có lời dẫn', 'info'); return; }
        await ensureIds(); await saveNow();
        const { task } = await api('POST', `/api/stories/${enc(sid)}/scenes/${enc(sc.id)}/listen`);
        const r = await waitTask(task);
        new Audio(r.audio).play();
      }),
    }, icon('play'));
    const move = (d) => { const j = i + d; if (j < 0 || j >= story.scenes.length) return; [story.scenes[i], story.scenes[j]] = [story.scenes[j], story.scenes[i]]; paintScenes(); touch(); };
    const del = async () => {
      if ((sc.text || sc.image) && !(await confirmDialog('Xóa cảnh?', `Cảnh ${i + 1} sẽ bị xóa khỏi câu chuyện.`, { okText: 'Xóa', danger: true }))) return;
      deleted.add(sc.id);
      story.scenes.splice(i, 1); paintScenes(); touch();
    };
    return el('div', { class: 'sy-scene', 'data-scene': sc.id, tabindex: '-1', onpaste: (e) => {
      const f = [...(e.clipboardData ? e.clipboardData.files : [])].find((x) => x.type.startsWith('image/'));
      if (f && e.target.tagName !== 'TEXTAREA' && e.target.tagName !== 'INPUT') { e.preventDefault(); busy(null, () => pasteImage(sc, f)); }
    } },
      el('div', { class: 'sy-scene-l' }, el('div', { class: 'sy-num mono', text: String(i + 1) }), imgBox, el('div', { class: 'sy-img-acts' }, genBtn, upBtn, libBtn),
        el('div', { class: 'sy-img-acts' }, stockBtn, aiClipBtn), imageBack ? el('div', { class: 'sy-img-acts' }, imageBack) : null,
        el('div', { class: 'sy-img-acts' }, copyBtn, pasteBtn, el('span', { class: 'dim small sy-free', text: 'Vẽ ngoài, dán vào' }))),
      el('div', { class: 'sy-scene-r' }, text,
        el('details', { class: 'sy-prompt', open: !!sc.prompt }, el('summary', { text: 'Mô tả hình cho AI' }), prompt, broll),
        story.characters.length ? chips : null,
        el('div', { class: 'sy-scene-foot' }, motion, trans, el('label', { class: 'sy-dur-wrap', title: 'Thời lượng cảnh (giây)' }, icon('clock'), dur), listenBtn,
          el('span', { class: 'sy-foot-tools' },
            el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Lên', 'aria-label': 'Đưa cảnh lên', disabled: i === 0, onclick: () => move(-1) }, icon('up')),
            el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Xuống', 'aria-label': 'Đưa cảnh xuống', disabled: i === story.scenes.length - 1, onclick: () => move(1) }, icon('chev')),
            el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Xóa cảnh', 'aria-label': 'Xóa cảnh', onclick: del }, icon('trash'))))));
  }
  async function pasteImage(sc, blob) {
    await ensureIds();
    syncManaged((await putFile(`/api/stories/${enc(sid)}/scenes/${enc(sc.id)}/image`, blob)).story);
    toast('Đã dán ảnh vào cảnh', 'success', { timeout: 1800 });
  }
  function variants(sc) {
    if (!(sc.images || []).length && !(sc.clips || []).length) return;
    const clipItem = (name) => {
      const meta = (sc.clip_meta || {})[name] || {};
      const v = el('video', { src: fileUrl(sid, 'clip', name), muted: true, loop: true, playsinline: true, preload: 'metadata' });
      v.muted = true;
      const del = el('button', {
        class: 'btn btn-xs btn-icon btn-ghost sy-var-del', title: 'Xóa clip này', 'aria-label': 'Xóa clip', onclick: async (e) => {
          e.stopPropagation();
          syncManaged(await api('DELETE', `/api/stories/${enc(sid)}/scenes/${enc(sc.id)}/clip/${enc(name)}`));
          m.close();
        },
      }, icon('trash'));
      return el('div', { class: 'sy-variant-wrap' }, el('button', {
        class: 'sy-variant' + (name === sc.clip ? ' on' : ''), title: meta.src === 'ai' ? 'Clip AI' : `${meta.title || ''} ${meta.author ? '· ' + meta.author : ''}`,
        onmouseenter: () => v.play().catch(() => {}), onmouseleave: () => v.pause(),
        onclick: async () => { syncManaged(await api('POST', `/api/stories/${enc(sid)}/scenes/${enc(sc.id)}/clip/use`, { name })); m.close(); },
      }, v, el('span', { class: 'sy-badge sy-badge-clip' }, icon('film'), meta.src === 'ai' ? 'AI' : (SRC_SHORT[meta.src] || 'Video'))), del);
    };
    const m = openModal([
      modalHead('image', 'Các bản của cảnh', () => m),
      el('div', { class: 'modal-body' },
        (sc.clips || []).length ? [el('h4', { class: 'sy-var-h', text: 'Clip (đang dùng clip thì ảnh chỉ làm ảnh bìa)' }), el('div', { class: 'sy-variants' }, sc.clips.map(clipItem))] : '',
        (sc.images || []).length ? [el('h4', { class: 'sy-var-h', text: (sc.clips || []).length ? 'Ảnh (bấm để dùng ảnh thay clip)' : 'Ảnh' }), el('div', { class: 'sy-variants' }, sc.images.map((name) => el('button', {
          class: 'sy-variant' + (name === sc.image && !sc.clip ? ' on' : ''), onclick: async () => {
            await api('POST', `/api/stories/${enc(sid)}/scenes/${enc(sc.id)}/image/use`, { name });
            syncManaged(await api('POST', `/api/stories/${enc(sid)}/scenes/${enc(sc.id)}/clip/use`, { name: '' }));
            m.close();
          },
        }, el('img', { src: fileUrl(sid, 'img', name), alt: '' }))))] : ''),
    ], { cls: 'modal-lg' });
  }
  async function runClipTask(scid, task, box, btn) {
    const set = clippingOf(sid);
    set.add(scid);
    if (box) box.classList.add('is-busy');
    const label = btn && btn.lastChild && btn.lastChild.nodeType === 3 ? btn.lastChild : null;
    const old = label ? label.textContent : '';
    try {
      await waitTask(task, (t) => { if (label && t.message) label.textContent = ' ' + t.message.slice(0, 40); });
      toast('Cảnh đã có clip', 'success', { timeout: 1800 });
    } finally { set.delete(scid); if (label) label.textContent = old; }
    await reload();
    paintScenes();
  }
  function stockPicker(sc) {
    const srcs = (opts.stock_sources || []).filter((x) => x.ready);
    const q = el('input', { class: 'input', value: sc.broll || '', placeholder: 'Từ khóa tiếng Anh, ví dụ: rainy city street night', 'aria-label': 'Từ khóa tìm video' });
    const srcSel = el('select', { class: 'input', 'aria-label': 'Kho video' }, el('option', { value: '' }, 'Mọi kho'),
      srcs.map((x) => el('option', { value: x.id, selected: x.id === story.stock_src }, x.name)));
    const grid = el('div', { class: 'sy-stock-grid' });
    const info = el('p', { class: 'dim small' });
    let page = 1;
    const more = el('button', { class: 'btn btn-sm', hidden: true, onclick: () => busy(more, () => go(page + 1)) }, 'Xem thêm');
    const credit = el('p', { class: 'dim small sy-stock-credit' }, 'Video từ ',
      ...(opts.stock_sources || []).flatMap((x, k) => [k ? ', ' : '', el('a', { href: x.site, target: '_blank', rel: 'noreferrer', text: x.name })]),
      '. Chỉ lấy video có giấy phép dùng thương mại; nguồn từng clip được ghi lại cạnh video xuất ra.');
    async function go(pg = 1) {
      if (pg === 1) grid.replaceChildren(el('div', { class: 'dim small', text: 'Đang tìm…' }));
      const r = await api('GET', `/api/stories/${enc(sid)}/scenes/${enc(sc.id)}/stock?q=${enc(q.value.trim())}&src=${enc(srcSel.value)}&page=${pg}`);
      page = pg;
      if (!q.value.trim() && r.query) { q.value = r.query; sc.broll = r.query; touch(); }
      info.textContent = `Cảnh dài khoảng ${Math.round(r.need)} giây. ${r.items.length ? 'Rê chuột để xem, bấm để dùng cho cảnh.' : 'Không thấy video nào: thử từ khóa ngắn hơn, cụ thể hơn.'}`;
      const cards = r.items.map((it) => {
        const v = el('video', { muted: true, loop: true, playsinline: true, preload: 'none', poster: it.thumb });
        v.muted = true;
        const tall = it.height > it.width;
        const card = el('button', {
          class: 'sy-stock' + (tall ? ' tall' : ''), title: `${it.title || ''}${it.author ? ' · ' + it.author : ''} · ${it.license}`,
          onmouseenter: () => { if (!v.src) v.src = it.preview; v.play().catch(() => {}); }, onmouseleave: () => v.pause(),
          onclick: () => busy(card, async () => {
            const { task } = await api('POST', `/api/stories/${enc(sid)}/scenes/${enc(sc.id)}/stock`, { src: it.src, id: it.id });
            m.close();
            const box = sceneBox.querySelector(`[data-scene="${sc.id}"] .sy-img`);
            await runClipTask(sc.id, task, box, null);
          }),
        }, v, el('span', { class: 'sy-stock-meta' }, el('b', { text: `${Math.round(it.duration)}s` }), ` ${Math.min(it.width, it.height)}p · ${SRC_SHORT[it.src] || it.src}`,
          it.duration + 0.5 < r.need ? el('i', { class: 'sy-stock-short', title: 'Ngắn hơn cảnh: sẽ được làm chậm hoặc lặp lại', text: ' ngắn' }) : ''));
        return card;
      });
      if (pg === 1) grid.replaceChildren(...cards); else grid.append(...cards);
      more.hidden = r.items.length < 12;
    }
    const searchBtn = el('button', { class: 'btn btn-primary', onclick: () => busy(searchBtn, () => go(1)) }, icon('search'), 'Tìm');
    q.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); searchBtn.click(); } });
    const m = openModal([
      modalHead('film', `Video nền cho cảnh ${story.scenes.indexOf(sc) + 1}`, () => m),
      el('div', { class: 'modal-body' },
        srcs.length ? '' : el('p', { class: 'small prov-warn-msg', text: 'Chưa có kho nào sẵn sàng.' }),
        el('div', { class: 'sy-stock-bar' }, q, srcSel, searchBtn), info, grid, el('div', { class: 'btn-row' }, more), credit),
    ], { cls: 'modal-lg' });
    q.focus();
    busy(searchBtn, () => go(1));
  }
  async function stockAll() {
    await ensureIds(); await saveNow();
    const missing = story.scenes.filter((x) => !x.clip).length;
    if (!missing) { toast('Cảnh nào cũng đã có clip. Muốn đổi thì bấm Video nền ở từng cảnh.', 'info'); return; }
    const { task } = await api('POST', `/api/stories/${enc(sid)}/stock`, { only_missing: true, src: story.stock_src || '' });
    const set = clippingOf(sid);
    set.add('*'); paintScenes();
    let r;
    try {
      r = await waitTask(task, (t) => { stockAllBtn.lastChild.textContent = ' ' + (t.message || 'Đang tìm…').slice(0, 46); });
    } finally { set.delete('*'); stockAllBtn.lastChild.textContent = ' Tìm video nền cho mọi cảnh'; }
    await reload(); paintScenes();
    const kept = r.kept ? ` ${r.kept} cảnh có nhân vật được giữ để vẽ (video quay thật không có nhân vật của bạn; muốn vẫn dùng thì bấm Video nền ở cảnh đó).` : '';
    if (r.failed) toast(`Có video cho ${r.done} cảnh, ${r.failed} cảnh chưa tìm được clip hợp${r.error ? ': ' + r.error : ''}.${kept}`, 'warn', { timeout: 12000 });
    else toast(`Đã có video nền cho ${r.done} cảnh.${kept}`, r.done ? 'success' : 'info', { timeout: kept ? 10000 : 4000 });
  }
  async function animateAll() {
    await ensureIds(); await saveNow();
    const e = await api('GET', `/api/stories/${enc(sid)}/animate/estimate?only_missing=true`);
    if (!e.scenes) { toast('Cảnh nào cũng đã có clip', 'info'); return; }
    const vp = (opts.video_providers || [])[0];
    if (!(await confirmDialog(`AI làm clip cho ${e.scenes} cảnh?`, `${vp ? vp.name : 'AI'}, ${e.resolution}, tổng ${e.seconds} giây: khoảng ${usd(e.usd)} USD. Mỗi cảnh tính một lần, cảnh lỗi không tính. Cảnh đã có clip (kể cả video nền) không làm lại.`, { okText: `Làm ${e.scenes} clip` }))) return;
    const { task } = await api('POST', `/api/stories/${enc(sid)}/animate`, { only_missing: true });
    const set = clippingOf(sid);
    set.add('*'); paintScenes();
    let r;
    try {
      r = await waitTask(task, (t) => { animateAllBtn.lastChild.textContent = ' ' + (t.message || 'Đang làm…').slice(0, 46); });
    } finally { set.delete('*'); animateAllBtn.lastChild.textContent = ' AI làm clip cho mọi cảnh ($)'; }
    await reload(); paintScenes();
    if (r.failed) toast(`AI làm được ${r.done} clip, ${r.failed} cảnh lỗi: ${r.error}`, 'warn', { timeout: 10000 });
    else toast(`Đã có ${r.done} clip AI`, 'success');
  }
  async function fromLibrary(sc) {
    const { items } = await api('GET', '/api/images');
    if (!items.length) { toast('Thư viện ảnh trống. Ảnh lưu ở trang Sửa ảnh sẽ hiện ở đây.', 'info'); return; }
    await ensureIds();
    const m = openModal([
      modalHead('grid', 'Chọn ảnh trong thư viện', () => m),
      el('div', { class: 'modal-body sy-variants' }, items.map((it) => el('button', {
        class: 'sy-variant', title: it.name, onclick: async () => {
          syncManaged((await api('POST', `/api/stories/${enc(sid)}/scenes/${enc(sc.id)}/image/from-library`, { name: it.name })).story);
          m.close();
        },
      }, el('img', { src: it.url, alt: it.name, loading: 'lazy' })))),
    ], { cls: 'modal-lg' });
  }
  async function drawAll() {
    const n = story.scenes.filter((s) => !s.image && (s.text || s.prompt)).length;
    const prov = provOf();
    if (prov && !prov.local && n >= 2 && !(await confirmDialog(`Vẽ ${n} ảnh bằng ${prov.name}?`, `Giá: ${prov.price}. Mỗi ảnh tính một lần, ảnh lỗi không tính.`, { okText: `Vẽ ${n} ảnh` }))) return;
    await ensureIds(); await saveNow();
    const { task } = await api('POST', `/api/stories/${enc(sid)}/generate`);
    const set = drawingOf(sid);
    set.add('*');
    paintScenes();
    let r;
    try {
      r = await waitTask(task, (t) => { drawAllBtn.lastChild.textContent = ' ' + (t.message || 'Đang vẽ…'); });
    } finally { set.delete('*'); }
    await reload();
    paintScenes();
    if (r.failed) toast(`Vẽ được ${r.done} cảnh, ${r.failed} cảnh lỗi: ${r.error}`, 'warn', { timeout: 10000 });
    else toast(`Đã vẽ ${r.done} cảnh`, 'success');
  }

  // ---------- nhân vật
  const charBox = el('div', { class: 'sy-chars' });
  function paintChars() {
    keepFocus(charBox, () => paintCharsNow());
  }
  function paintCharsNow() {
    charBox.replaceChildren(...story.characters.map((c, i) => {
      const name = el('input', { class: 'input input-sm', 'data-key': c.id + ':name', value: c.name, placeholder: 'Tên', oninput: () => { c.name = name.value; touch(); } });
      const desc = el('textarea', { class: 'input', rows: 3, 'data-key': c.id + ':desc', value: c.description, placeholder: 'Ngoại hình để AI vẽ giống nhau: tuổi, tóc, quần áo, màu sắc, chi tiết riêng. Viết tiếng Việt hay tiếng Anh đều được.', oninput: () => { c.description = desc.value; touch(); } });
      const refs = el('div', { class: 'sy-refs' }, (c.refs || []).map((r) => el('div', { class: 'sy-ref' },
        el('img', { src: fileUrl(sid, 'ref', r), alt: 'Ảnh mẫu', loading: 'lazy' }),
        el('button', {
          class: 'sy-ref-x', title: 'Bỏ ảnh mẫu này', 'aria-label': 'Bỏ ảnh mẫu', onclick: async () => { syncManaged(await api('DELETE', `/api/stories/${enc(sid)}/characters/${enc(c.id)}/ref/${enc(r)}`)); },
        }, icon('x')))));
      const upBtn = el('button', {
        class: 'btn btn-xs', title: 'Ảnh có sẵn của nhân vật (rõ mặt, đủ người càng tốt)', onclick: () => busy(upBtn, async () => {
          const f = await pickFile(IMAGE_TYPES);
          if (!f) return;
          await ensureIds();
          syncManaged((await putFile(`/api/stories/${enc(sid)}/characters/${enc(c.id)}/ref`, f)).story);
        }),
      }, icon('upload'), 'Ảnh mẫu');
      const genBtn = el('button', {
        class: 'btn btn-xs', disabled: !opts.image_ai, title: opts.image_ai ? 'Gemini vẽ ảnh mẫu theo mô tả (toàn thân và cận mặt)' : 'Cần key Gemini có bật thanh toán',
        onclick: () => busy(genBtn, async () => {
          await ensureIds(); await saveNow();
          const { task } = await api('POST', `/api/stories/${enc(sid)}/characters/${enc(c.id)}/generate`);
          await waitTask(task);
          await reload();
        }),
      }, icon('wand'), 'AI vẽ ảnh mẫu');
      const del = el('button', {
        class: 'btn btn-xs btn-icon btn-ghost', title: 'Xóa nhân vật', 'aria-label': 'Xóa nhân vật', onclick: () => {
          story.characters.splice(i, 1);
          story.scenes.forEach((s) => { s.characters = s.characters.filter((x) => x !== c.id); });
          paintChars(); paintScenes(); touch();
        },
      }, icon('trash'));
      return el('div', { class: 'sy-char' }, el('div', { class: 'sy-char-head' }, name, del), desc, refs, el('div', { class: 'btn-row' }, upBtn, genBtn));
    }), el('button', {
      class: 'btn btn-sm', onclick: () => { story.characters.push({ id: newId('c'), name: '', description: '', refs: [] }); paintChars(); paintScenes(); touch(); },
    }, icon('plus'), 'Thêm nhân vật'));
  }

  // ---------- giọng, phụ đề, nhạc
  const v = story.voice;
  v.lang = v.lang || 'vi';
  // ngôn ngữ lời dẫn: câu chuyện cho thị trường nước ngoài (AI viết kịch bản cũng viết bằng ngôn ngữ này)
  const langSel = el('select', { class: 'input', onchange: () => { v.lang = langSel.value; v.voice = ''; fillVoices(); touch(); } },
    (S.langs.length ? S.langs : [{ code: 'vi', name: 'Tiếng Việt' }]).map((l) => el('option', { value: l.code, selected: l.code === v.lang }, l.name)));
  const engSel = el('select', { class: 'input', onchange: () => { v.engine = engSel.value; v.voice = ''; fillVoices(); touch(); } },
    [['vieneu', 'VieNeu (tiếng Việt, trên máy)'], ['vox', 'Nhiều thứ tiếng (trên máy)'], ['edge', 'Microsoft (cần mạng)']].map(([k, l]) => el('option', { value: k, selected: k === v.engine }, l)));
  const engOf = () => effEngine(v.engine, v.lang);
  const voiceSel = el('select', { class: 'input', onchange: () => { v.voice = voiceSel.value; touch(); } });
  const fillVoices = () => {
    for (const o of engSel.options) o.disabled = (o.value === 'vieneu' && v.lang !== 'vi') || (o.value === 'vox' && !S.voices.vox_ready);
    if (engSel.selectedOptions[0] && engSel.selectedOptions[0].disabled) { v.engine = engOf(); engSel.value = v.engine; }
    fillVoiceSelect(voiceSel, engOf(), { current: v.voice, lang: v.lang });
  };
  fillVoices();
  const hook = () => { if (!voiceSel.isConnected) return false; fillVoices(); return true; };
  voiceHooks.add(hook);
  const speedVal = el('span', { class: 'mono small', text: `${Number(v.speed).toFixed(2)}x` });
  const speed = el('input', { type: 'range', min: 0.7, max: 1.5, step: 0.05, value: v.speed, oninput: () => { v.speed = Number(speed.value); speedVal.textContent = `${v.speed.toFixed(2)}x`; touch(); } });
  const tryBtn = el('button', { class: 'btn btn-xs btn-icon', title: 'Nghe thử giọng', 'aria-label': 'Nghe thử giọng', onclick: (e) => previewVoice(engOf(), v.voice, e.currentTarget, v.lang) }, icon('play'));
  const myBtn = myVoiceButton(engOf, (id) => { const e = v.lang === 'vi' ? 'vieneu' : 'vox'; v.engine = e; engSel.value = e; v.voice = id; fillVoices(); touch(); });
  const subOn = el('input', { type: 'checkbox', checked: story.subs.enabled, onchange: () => { story.subs.enabled = subOn.checked; touch(); } });
  const subSel = el('select', { class: 'input', onchange: () => { story.subs.style = subSel.value; touch(); } },
    opts.sub_styles.map((k) => el('option', { value: k, selected: k === story.subs.style }, SUB_LABEL[k] || k)));
  const fitSel = el('select', { class: 'input', title: 'Ảnh khác khung hình', onchange: () => { story.fit = fitSel.value; touch(); } },
    [['cover', 'Cắt cho đầy khung'], ['blur', 'Giữ cả ảnh, nền mờ']].map(([k, l]) => el('option', { value: k, selected: k === story.fit }, l)));
  // ---------- dựng: chuyển cảnh, mở đầu, kết thúc
  story.intro = story.intro || { enabled: false, text: '', sub: '' };
  story.outro = story.outro || { enabled: false, text: opts.default_outro || '', sub: '' };
  const transSel = el('select', { class: 'input', onchange: () => { story.transition = transSel.value; touch(); } },
    (opts.transitions || []).map((x) => el('option', { value: x.id, selected: x.id === (story.transition || 'fade') }, x.label)));
  const tdVal = el('span', { class: 'mono small' });
  const td = el('input', { type: 'range', min: 0.2, max: 1.5, step: 0.1, value: story.trans_dur || 0.5, oninput: () => { story.trans_dur = Number(td.value); tdVal.textContent = `${story.trans_dur.toFixed(1)}s`; touch(); } });
  tdVal.textContent = `${Number(td.value).toFixed(1)}s`;
  function cardFields(card, label, phText, phSub) {
    const on = el('input', { type: 'checkbox', checked: card.enabled, onchange: () => { card.enabled = on.checked; text.disabled = sub.disabled = !on.checked; paintScenes(); touch(); } });
    const text = el('input', { class: 'input input-sm', value: card.text, placeholder: phText, disabled: !card.enabled, 'data-key': label + ':text', oninput: () => { card.text = text.value; touch(); } });
    const sub = el('input', { class: 'input input-sm', value: card.sub, placeholder: phSub, disabled: !card.enabled, 'data-key': label + ':sub', oninput: () => { card.sub = sub.value; touch(); } });
    return el('div', { class: 'sy-card-fields' }, el('label', { class: 'check' }, on, ' ' + label), text, sub);
  }
  const musicName = el('span', { class: 'small sy-music-name' });
  const musicVol = el('input', { type: 'range', min: 0, max: 0.6, step: 0.02, value: story.music.volume, oninput: () => { story.music.volume = Number(musicVol.value); touch(); } });
  const paintMusic = () => { musicName.textContent = story.music.path ? story.music.path.split(/[\\/]/).pop() : 'Không có nhạc nền'; };
  paintMusic();
  const musicBtn = el('button', {
    class: 'btn btn-xs', onclick: () => busy(musicBtn, async () => {
      const f = await pickFile('audio/*');
      if (!f) return;
      const r = await uploadFile('music', f);
      story.music.path = r.path; paintMusic(); touch();
    }),
  }, icon('music'), 'Chọn nhạc');
  const musicClear = el('button', { class: 'btn btn-xs btn-ghost', onclick: () => { story.music.path = ''; paintMusic(); touch(); } }, 'Bỏ');
  const styleNote = el('textarea', { class: 'input', rows: 2, value: story.style_note, placeholder: 'Thêm cho phong cách ảnh, ví dụ: tông màu ấm, bối cảnh làng quê Việt Nam thập niên 90', oninput: () => { story.style_note = styleNote.value; touch(); } });

  // ---------- video nền, clip AI
  const stockAllBtn = el('button', { class: 'btn btn-sm', onclick: () => busy(stockAllBtn, stockAll) }, icon('search'), el('span', { text: ' Tìm video nền cho mọi cảnh' }));
  const animateAllBtn = el('button', { class: 'btn btn-sm', onclick: () => busy(animateAllBtn, animateAll) }, icon('film'), el('span', { text: ' AI làm clip cho mọi cảnh ($)' }));
  const stockSel = el('select', { class: 'input', title: 'Kho video nền', onchange: () => { story.stock_src = stockSel.value; touch(); } },
    el('option', { value: '' }, 'Mọi kho đã sẵn sàng'),
    (opts.stock_sources || []).map((x) => el('option', { value: x.id, selected: x.id === story.stock_src, disabled: !x.ready }, x.name + (x.ready ? '' : ' (chưa có key)'))));
  const resSel = el('select', { class: 'input', title: 'Độ nét clip AI (nét hơn thì đắt hơn)', onchange: () => { story.video_res = resSel.value; touch(); } },
    (opts.video_res || ['720p']).map((r) => {
      const vp0 = (opts.video_providers || [])[0];
      return el('option', { value: r, selected: r === (story.video_res || '720p') }, `${r}${vp0 ? ` (~${usd(vp0.price[r])} USD/giây)` : ''}`);
    }));
  const vp0 = (opts.video_providers || [])[0];
  animateAllBtn.disabled = !(vp0 && vp0.usable);
  if (!(vp0 && vp0.usable)) animateAllBtn.title = vp0 && vp0.ready ? 'Trả phí: đang tắt tính năng trả phí (Cài đặt, mục Chi phí)' : 'Trả phí: cần key Gemini đã bật thanh toán';
  resSel.disabled = animateAllBtn.disabled;
  const creditsBtn = el('button', {
    class: 'btn btn-xs btn-ghost', onclick: () => busy(creditsBtn, async () => {
      const r = await api('GET', `/api/stories/${enc(sid)}/credits`);
      if (!r.items.length) { toast('Chưa cảnh nào dùng clip', 'info'); return; }
      const m = openModal([modalHead('file', 'Nguồn các clip', () => m), el('div', { class: 'modal-body' },
        el('p', { class: 'dim small', text: 'Ghi tự động vào file .nguon.txt cạnh video khi dựng. Dán vào mô tả video nếu muốn ghi công tác giả.' }),
        el('pre', { class: 'sy-credits', text: r.text }),
        el('div', { class: 'btn-row' }, el('button', { class: 'btn btn-sm', onclick: async () => { await navigator.clipboard.writeText(r.text); toast('Đã chép', 'success', { timeout: 1500 }); } }, icon('copy'), 'Chép')))], { cls: 'modal-lg' });
    }),
  }, icon('file'), 'Nguồn clip');
  const videoPanel = el('section', { class: 'sy-panel' }, el('h4', { text: 'Video nền và clip AI' }),
    el('p', { class: 'dim small', text: 'Cảnh có clip thì dùng clip thay ảnh. Video nền: quay thật, miễn phí, giấy phép dùng thương mại. Clip AI ($): biến ảnh cảnh thành chuyển động, trả phí theo giây, chỉ dùng được khi bật tính năng trả phí.' }),
    stockSel, stockAllBtn, resSel, animateAllBtn,
    (opts.stock_sources || []).some((x) => !x.ready) ? el('a', { class: 'small', href: '#/settings', onclick: () => setTimeout(() => document.getElementById('video-nen')?.scrollIntoView({ block: 'start' }), 400), text: 'Thêm key Pexels, Pixabay miễn phí để có nhiều video dọc hơn' }) : '',
    creditsBtn);

  // ---------- kết quả
  const resultBox = el('div', { class: 'sy-result' });
  function editedList() {
    const items = story.edited || [];
    if (!items.length) return '';
    return el('div', { class: 'sy-edited' },
      el('span', { class: 'label', text: 'Bản dựng từ Trình dựng' }),
      ...items.slice(0, 5).map((it) => {
        const url = `/api/stories/${enc(sid)}/edited/${enc(it.name)}`;
        return el('div', { class: 'sy-edited-row' },
          el('span', { class: 'mono small grow', title: it.path, text: it.name }),
          el('span', { class: 'dim small', text: fmtAgo(it.at) }),
          el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Xem', 'aria-label': 'Xem bản dựng', onclick: () => videoModal(url, it.name) }, icon('play')),
          el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Mở thư mục', 'aria-label': 'Mở thư mục', onclick: () => api('POST', `${url}/reveal`) }, icon('folder')));
      }));
  }
  function paintResult() {
    if (!story.output) {
      resultBox.replaceChildren(el('p', { class: 'dim small', text: 'Chưa dựng. Đủ ảnh cho mọi cảnh thì bấm Dựng video, hoặc Trình dựng để tự sắp xếp như CapCut.' }), editedList());
      return;
    }
    const url = `/api/stories/${enc(sid)}/video?t=${Math.round(story.rendered || story.updated || 0)}`;
    resultBox.replaceChildren(
      el('video', { class: 'sy-video' + (story.aspect === '9:16' ? ' tall' : ''), src: url, controls: true, preload: 'metadata' }),
      el('div', { class: 'mono small sy-out', title: story.output, text: story.output.split(/[\\/]/).pop() }),
      el('div', { class: 'btn-row' },
        el('button', { class: 'btn btn-sm', onclick: () => videoModal(url, story.title) }, icon('full'), 'Xem lớn'),
        el('button', { class: 'btn btn-sm btn-ghost', onclick: () => api('POST', `/api/stories/${enc(sid)}/reveal`) }, icon('folder'), 'Thư mục')),
      editedList());
  }
  async function startRender() {
    await ensureIds(); await saveNow();
    await api('POST', `/api/stories/${enc(sid)}/render`);
    pollSoon();
    toast('Đã xếp hàng dựng video', 'info', { timeout: 2200 });
  }
  let watching = null;
  const onQueue = (items) => {
    const it = items.find((x) => x.story === sid && (x.state === 'queued' || x.state === 'running')) || (watching && items.find((x) => x.qid === watching));
    if (!it) { runbar.hidden = true; renderBtn.disabled = false; return; }
    const active = it.state === 'queued' || it.state === 'running';
    renderBtn.disabled = active;
    runbar.hidden = false;
    const pct = it.progress != null ? ` ${Math.round(it.progress * 100)}%` : '';
    runbar.replaceChildren(el('span', { class: 'sy-run-t', text: active ? (it.state === 'queued' ? 'Đang chờ lượt…' : `${it.stage === 'tts' ? 'Đang đọc lời dẫn' : 'Đang dựng video'}${pct}`) : it.state === 'done' ? 'Dựng xong' : (it.message || 'Lỗi') }),
      el('div', { class: 'sy-run-bar' }, el('i', { style: { width: `${Math.round((it.progress || 0) * 100)}%` } })));
    if (active) { watching = it.qid; return; }
    if (watching === it.qid) {
      watching = null;
      if (it.state === 'done') { toast('Video kể chuyện đã xong', 'success'); reload().then(paintResult); } else if (it.state === 'error') itemErrorToast('Dựng lỗi: ', it);
      setTimeout(() => { if (!watching) runbar.hidden = true; }, 4000);
    }
  };
  queueListeners.add(onQueue);
  cleanups.push(() => queueListeners.delete(onQueue), () => voiceHooks.delete(hook));
  onQueue(S.queue || []);

  const total = () => story.scenes.reduce((n, s) => n + Math.max(s.duration || 0, s.text ? Math.max(3, s.text.length / 15) : (s.duration || 3)), 0)
    + (story.intro && story.intro.enabled ? 2.8 : 0) + (story.outro && story.outro.enabled ? 3.2 : 0);
  const estimate = el('span', { class: 'dim small' });
  const paintEstimate = () => { estimate.textContent = `${story.scenes.length} cảnh, khoảng ${fmtDur(total())}`; };
  paintEstimate();
  const timer = setInterval(paintEstimate, 2000);
  cleanups.push(() => clearInterval(timer));

  main.classList.add('view-story-edit');
  main.append(
    el('div', { class: 'sy-head' },
      el('a', { class: 'btn btn-icon btn-ghost', href: '#/story', title: 'Về danh sách', 'aria-label': 'Về danh sách' }, icon('back')),
      titleInp, aspectSel, styleSel, provSel, el('span', { class: 'grow' }), estimate, drawAllBtn, editBtn, renderBtn),
    runbar,
    el('div', { class: 'sy-body' },
      sceneBox,
      el('aside', { class: 'sy-side' },
        el('section', { class: 'sy-panel' }, el('h4', { text: 'Kết quả' }), resultBox),
        videoPanel,
        el('section', { class: 'sy-panel' }, el('h4', { text: 'Nhân vật' }),
          el('p', { class: 'dim small', text: 'Mỗi nhân vật 1 đến 4 ảnh mẫu. Bật nhân vật trong từng cảnh, AI sẽ vẽ giống ảnh mẫu.' }), charBox),
        el('section', { class: 'sy-panel' }, el('h4', { text: 'Chuyển cảnh, mở đầu, kết thúc' }),
          el('label', { class: 'field' }, el('span', { class: 'label', text: 'Kiểu chuyển cảnh chung (từng cảnh chọn riêng được)' }), transSel),
          el('div', { class: 'sy-range' }, el('span', { class: 'small', text: 'Độ dài chuyển' }), td, tdVal),
          cardFields(story.intro, 'Cảnh mở đầu', 'Tiêu đề (trống: lấy tên câu chuyện)', 'Dòng phụ, ví dụ: Tập 1'),
          cardFields(story.outro, 'Cảnh kết thúc', 'Lời kêu gọi', 'Tên kênh, ví dụ: @tenkenh')),
        el('section', { class: 'sy-panel' }, el('h4', { text: 'Phong cách ảnh' }), styleNote,
          el('label', { class: 'field' }, el('span', { class: 'label', text: 'Ảnh khác khung hình' }), fitSel)),
        el('section', { class: 'sy-panel' }, el('h4', { text: 'Giọng đọc' }), langSel, engSel, el('div', { class: 'voice-pick' }, voiceSel, tryBtn, myBtn),
          el('div', { class: 'sy-range' }, el('span', { class: 'small', text: 'Tốc độ' }), speed, speedVal)),
        el('section', { class: 'sy-panel' }, el('h4', { text: 'Phụ đề và nhạc' }), el('label', { class: 'check' }, subOn, ' Hiện phụ đề'), subSel,
          el('div', { class: 'sy-music' }, musicName, musicBtn, musicClear), el('div', { class: 'sy-range' }, el('span', { class: 'small', text: 'Âm lượng nhạc' }), musicVol)))));
  paintScenes();
  paintChars();
  paintResult();
  api('GET', `/api/stories/${enc(sid)}/drawing`).then((d) => {
    const set = drawingOf(sid);
    set.clear();
    if (d.all) set.add('*');
    d.scenes.forEach((x) => set.add(x));
    const cs = clippingOf(sid);
    cs.clear();
    if (d.clips_all) cs.add('*');
    (d.clips || []).forEach((x) => cs.add(x));
    if (alive() && (d.all || d.scenes.length || cs.size)) { paintScenes(); pollDrawing(); }
  }).catch(() => {});
  async function pollDrawing() {      // đợi các lượt vẽ bắt đầu từ lần mở trước xong rồi lấy ảnh về
    while (alive() && (drawingOf(sid).size || clippingOf(sid).size)) {
      await sleep(2500);
      const d = await api('GET', `/api/stories/${enc(sid)}/drawing`).catch(() => null);
      if (!d) continue;
      const set = drawingOf(sid);
      const cs = clippingOf(sid);
      const before = set.size + cs.size;
      set.clear();
      if (d.all) set.add('*');
      d.scenes.forEach((x) => set.add(x));
      cs.clear();
      if (d.clips_all) cs.add('*');
      (d.clips || []).forEach((x) => cs.add(x));
      if (set.size + cs.size !== before) { await reload(); paintScenes(); }
    }
  }
  return () => { cleanups.forEach((f) => f()); saveNow(); };
}
