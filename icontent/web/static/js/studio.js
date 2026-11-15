/* Trang Studio: bố cục kiểu phần mềm dựng phim.
 *   danh sách câu | trình phát | bảng thuộc tính
 *                timeline
 */
import {
  S, Tape, STAGE_LABEL, api, busy, speakerColor, clamp, clone, confirmDialog, debounce, deepMerge, defaultVoice, diff, effEngine, el, emptyState, enc,
  ensureConfig, fillVoiceSelect, fmtDur, fmtTime, genderOf, getPath, icon, loadingState, modalHead, modalStack, openModal, platformBadge, playUrl,
  pollSoon, put, queueListeners, reveal, runJob, setPath, stopAudio, toast, videoModal, voiceFits, voiceHooks, voiceLabel, words,
} from './core.js';
import { openEditor } from './editor.js';
import { itemErrorToast } from './fixes.js';
import { Inspector } from './inspector.js';
import { Player } from './player.js';
import { runChecks } from './qa.js';
import { Timeline } from './timeline.js';

const EDIT_FIELDS = ['id', 'start', 'end', 'text', 'trans', 'voice', 'speaker', 'check'];
const CHECK_TIPS = {
  ocr: 'Không nghe ra tiếng ở đây (thường do nhạc to), câu này lấy từ chữ phụ đề trên màn hình. Xem lại chữ và thời gian, đúng rồi thì bấm vào nhãn này để bỏ đánh dấu',
  nghe: 'Chỉ nghe ra tiếng, màn hình không có phụ đề lúc này. Có thể app nghe nhầm tiếng nhạc hoặc tiếng động. Nghe lại, đúng rồi thì bấm vào nhãn này để bỏ đánh dấu',
};
const HISTORY_FIELDS = [...EDIT_FIELDS, 'gender', 'ocr'];

export async function viewStudio(main, alive, id) {
  if (!id) {
    main.classList.add('view-pad');
    main.append(el('div', { class: 'page-head' }, el('div', { class: 'page-head-text' }, el('div', { class: 'eyebrow', text: 'Studio' }), el('h1', { text: 'Chưa mở video nào' }))),
      emptyState('Chọn một video để chỉnh', 'Mở một video trong Thư viện để sửa phụ đề, giọng đọc, timeline và xuất bản.',
        el('a', { class: 'btn btn-primary', href: '#/library' }, icon('grid'), 'Đến Thư viện'), 'boxed'));
    return null;
  }
  main.append(loadingState('Đang mở dự án…'));
  await ensureConfig();
  let job;
  try {
    job = await api('GET', `/api/jobs/${enc(id)}`);
  } catch (e) {
    if (e.status === 404 && S.lastStudio === id) { S.lastStudio = ''; localStorage.removeItem('ic.lastStudio'); }
    throw e;
  }
  if (!alive()) return null;
  S.lastStudio = id;
  localStorage.setItem('ic.lastStudio', id);
  main.replaceChildren();

  const st = {
    id, job, segs: [], rows: [], snap: new Map(), watchQid: null,
    handled: new Set(S.queue.filter((i) => !['queued', 'running'].includes(i.state)).map((i) => i.qid)),
    dirty: 0, userScrollAt: 0, activeIdx: -1, discard: false, runActive: false, history: [], future: [], lastHist: '',
    vals: deepMerge(clone(S.config) || {}, job.options || {}),
    pausePlayer: () => player.pause(),
  };
  S.studio = st;
  const meta = () => st.job.meta || {};
  const eff = () => st.vals;
  const langOf = () => getPath(eff(), 'translate.target_lang') || 'vi';
  const engineOf = () => effEngine(getPath(eff(), 'tts.engine') || 'vieneu', langOf());      // VieNeu chỉ đọc tiếng Việt
  const hasFile = (k) => !!(st.job.files && st.job.files[k]);
  const getBox = () => {
    const b = getPath(eff(), 'edit.blur_hardsub');
    if (b === false || b === 'false') return null;
    if (b === true || b === 'true') return getPath(eff(), 'edit.hardsub_box') || null;
    const hb = st.job.hardsub && st.job.hardsub.box;
    return Array.isArray(hb) && hb.length === 4 ? hb : null;
  };

  // ------------------------------------------------ đầu trang
  const titleEl = el('h2', { class: 'st-title' });
  const metaEl = el('div', { class: 'st-meta' });
  const scoreBtn = el('button', { class: 'score-chip', title: 'Kiểm tra trước khi đăng', onclick: () => inspector.open('qa') });
  const undoBtn = el('button', { class: 'btn btn-icon btn-ghost', title: 'Hoàn tác (Ctrl+Z)', 'aria-label': 'Hoàn tác', onclick: () => undo() }, icon('undo'));
  const redoBtn = el('button', { class: 'btn btn-icon btn-ghost', title: 'Làm lại (Ctrl+Y)', 'aria-label': 'Làm lại', onclick: () => redo() }, icon('redo'));
  const saveBtn = el('button', { class: 'btn', title: 'Lưu phụ đề (Ctrl+S)', onclick: () => busy(saveBtn, () => save()) }, icon('save'), 'Lưu');
  const updateBtn = el('button', { class: 'btn', title: 'Lưu rồi làm lại đúng những gì đã đổi: đọc lại câu đã sửa và dựng lại video', onclick: () => busy(updateBtn, () => saveAndRun(null)) }, icon('refresh'), 'Cập nhật video');
  const editorBtn = el('button', {
    class: 'btn', title: 'Dựng tiếp nhiều track: thêm chữ, hiệu ứng, chuyển cảnh, nhạc... Video mở ra đã xóa sub và lồng tiếng, phụ đề nằm trên track riêng', onclick: () => busy(editorBtn, async () => {
      if (!hasFile('final')) { toast('Làm xong video này trước rồi mới mở trình dựng được', 'info'); return; }
      await inspector.flush();      // tùy chọn vừa đổi chưa kịp lưu thì bản cho trình dựng sẽ dựng theo tùy chọn cũ
      if (st.dirty) await save(true);
      const fresh = await api('GET', `/api/jobs/${enc(id)}`);
      // có thay đổi chưa cập nhật: mở trình dựng sẽ phải cập nhật video trước, tức dựng lại bản chính và thay file trong thư mục output
      if (fresh.stale && !(await confirmDialog('Video có thay đổi chưa cập nhật', 'Trình dựng cần bản mới nhất, nên Studio566 sẽ cập nhật video trước (lồng tiếng lại câu đã sửa, dựng lại bản chính, thay file trong thư mục output) rồi mới mở. Tiếp tục?', { okText: 'Cập nhật và mở' }))) return;
      await openEditor(id);
    }),
  }, icon('scissors'), 'Trình dựng');
  const exportBtn = el('button', { class: 'btn btn-primary', onclick: () => inspector.open('publish') }, icon('export'), 'Xuất & đăng');
  // chế độ Đơn giản (mặc định): video + danh sách câu, bảng tùy chọn mở dạng ngăn kéo khi cần; Chuyên nghiệp: đủ timeline như cũ
  let mode = localStorage.getItem('ic.studioMode') === 'pro' ? 'pro' : 'simple';
  const modeBtns = {};
  const modeSeg = el('div', { class: 'seg st-mode', role: 'radiogroup', 'aria-label': 'Chế độ Studio' },
    ...[['simple', 'Đơn giản'], ['pro', 'Chuyên nghiệp']].map(([k, label]) => {
      modeBtns[k] = el('button', { type: 'button', class: 'seg-btn', role: 'radio', onclick: () => setMode(k) }, label);
      return modeBtns[k];
    }));
  function setMode(k) {
    mode = k;
    try { localStorage.setItem('ic.studioMode', k); } catch (_) { /* không lưu được cũng không sao */ }
    main.classList.toggle('studio-simple', k === 'simple');
    main.classList.remove('insp-open');
    Object.entries(modeBtns).forEach(([m, b]) => { b.classList.toggle('active', m === k); b.setAttribute('aria-checked', m === k ? 'true' : 'false'); });
    if (k === 'pro' && tl) requestAnimationFrame(() => tl.draw());
  }
  const head = el('div', { class: 'st-head' },
    el('a', { class: 'btn btn-icon btn-ghost', href: '#/library', title: 'Về Video của tôi', 'aria-label': 'Về Video của tôi' }, icon('back')),
    el('div', { class: 'st-titles' }, titleEl, metaEl),
    el('div', { class: 'st-actions' }, modeSeg, el('span', { class: 'tb-sep' }), scoreBtn, el('span', { class: 'tb-sep st-pro-only' }), undoBtn, redoBtn, el('span', { class: 'tb-sep' }), saveBtn, updateBtn, editorBtn, exportBtn));
  function renderHead() {
    const m = meta();
    titleEl.textContent = m.title || id;
    titleEl.title = m.title || id;
    put(metaEl, platformBadge(m.platform),
      m.duration ? el('span', { class: 'mono', text: fmtDur(m.duration) }) : null,
      m.width ? el('span', { class: 'mono', text: `${m.width}×${m.height}` }) : null,
      el('button', { class: 'link-btn', onclick: () => reveal(id) }, icon('folder'), 'Thư mục'));
    paintUpdate();
  }
  function paintUpdate() {
    const needs = st.dirty > 0 || st.job.stale || !hasFile('final');
    updateBtn.classList.toggle('btn-accent', needs);
    updateBtn.classList.toggle('has-dot', needs);
    undoBtn.disabled = !st.history.length;
    redoBtn.disabled = !st.future.length;
    saveBtn.disabled = !st.dirty;
  }

  // ------------------------------------------------ thanh tiến độ
  const rbTape = Tape();
  const rbMsg = el('div', { class: 'rb-msg' });
  const rbPct = el('span', { class: 'q-pct mono' });
  const rbCancel = el('button', {
    class: 'btn btn-sm btn-danger', onclick: () => busy(rbCancel, async () => {
      if (st.watchQid) { await api('POST', `/api/queue/${enc(st.watchQid)}/cancel`); toast('Đã gửi lệnh hủy', 'info'); pollSoon(); }
    }),
  }, icon('x'), 'Hủy');
  const rbClose = el('button', { class: 'btn btn-sm btn-icon btn-ghost', title: 'Ẩn', 'aria-label': 'Ẩn', hidden: true, onclick: () => { runbar.hidden = true; } }, icon('x'));
  const runbar = el('div', { class: 'runbar', hidden: true }, el('span', { class: 'tally' }), rbTape.root, el('div', { class: 'rb-mid' }, rbMsg, rbPct), rbCancel, rbClose);
  function showRun(it) {
    runbar.hidden = false;
    const s = it.state;
    runbar.dataset.state = s;
    const p = typeof it.progress === 'number' ? it.progress : null;
    rbTape.set(it.stage, s, p);
    rbPct.textContent = s === 'running' && p != null ? Math.round(p * 100) + '%' : '';
    rbMsg.textContent = s === 'queued' ? 'Đang chờ tới lượt…' : s === 'done' ? 'Hoàn tất' : s === 'cancelled' ? 'Đã hủy'
      : s === 'error' ? 'Lỗi: ' + String(it.error || it.message || '').split('\n')[0] : (it.message || STAGE_LABEL[it.stage] || 'Đang xử lý…');
    rbMsg.title = rbMsg.textContent;
    const active = s === 'queued' || s === 'running';
    rbCancel.hidden = !active;
    rbClose.hidden = active;
  }

  // ------------------------------------------------ trình phát + timeline
  const player = Player({
    id, getMeta: meta, getEff: eff, getSegs: () => st.segs, getBox, hasFile,
    onTime: (t) => { syncActive(t); if (tl) tl.draw(); },
    onSubY: (y) => inspector.setOption('edit.sub_y', y),
    onModeChange: () => { if (inspector) inspector.onPlayerMode(); },
    getRendered: () => st.job.rendered,
    getOverlaySel: () => st.ovSel,
    onOverlayPick: (i) => pickOverlay(i),
    onOverlayMove: (i, x, y) => {
      const list = overlays();
      if (!list[i]) return;
      list[i].x = x; list[i].y = y;
      commitEdit();
    },
    onPin: (t, c) => setCropPin(t, c),
  });
  st.player = player;

  // ------------------------------------------------ danh sách câu
  const list = el('div', { class: 'lines', tabindex: '-1' });
  const stats = el('div', { class: 'lines-stats' });
  const findInp = el('input', { class: 'input', placeholder: 'Tìm trong phụ đề…', 'aria-label': 'Tìm trong phụ đề', oninput: debounce(() => applyFilter(), 120) });
  const replInp = el('input', { class: 'input', placeholder: 'Thay bằng…', 'aria-label': 'Thay bằng' });
  const replBox = el('div', { class: 'repl-box', hidden: true }, replInp,
    el('button', { class: 'btn btn-sm', onclick: () => replaceAll() }, 'Thay tất cả'));
  const replToggle = el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Tìm và thay thế', 'aria-label': 'Tìm và thay thế', onclick: () => { replBox.hidden = !replBox.hidden; if (!replBox.hidden) replInp.focus(); } }, icon('edit'));
  const onlyBad = el('button', { class: 'chip', title: 'Chỉ hiện câu cần xem: đọc quá nhanh, chưa dịch, hoặc được tô vàng vì app chưa chắc chắn', onclick: () => { onlyBad.classList.toggle('active'); applyFilter(); } }, icon('alert'), 'Cần xem');
  const linesPane = el('section', { class: 'pane lines-pane' },
    el('div', { class: 'pane-head' }, stats, el('span', { class: 'grow' }), onlyBad),
    el('div', { class: 'find-row' }, el('div', { class: 'search-box' }, icon('search'), findInp), replToggle),
    replBox, list);

  const peopleOf = () => (st.job.speakers && st.job.speakers.speakers) || [];
  // ------------------------------------------------ dựng: đoạn cắt, lớp phủ. Nằm trong options của video, có hoàn tác
  const cuts = () => getPath(st.vals, 'edit.cuts') || [];
  const pins = () => getPath(st.vals, 'edit.reframe_pins') || [];
  /** kéo khung cắt trên video: khung đi theo nhân vật thì ghim vị trí cho cảnh này, khung cố định thì đổi vị trí chung */
  function setCropPin(t, c) {
    const plan = player.plan;
    if (!plan) return;
    if (plan.isStatic) {
      if (c == null) return;
      setPath(st.vals, plan.axis === 'x' ? 'edit.focus_x' : 'edit.focus_y', +((c - plan.span / 2) / Math.max(1e-6, 1 - plan.span)).toFixed(3));
      commitEdit();
      inspector.refreshReframe();
      return;
    }
    const shot = plan.shots.find((s) => t >= s.start && t < s.end) || plan.shots[plan.shots.length - 1];
    if (!shot) return;
    const had = pins().filter((p) => p[0] >= shot.start && p[0] < shot.end).length > 0;
    if (c == null && !had) { toast('Cảnh này đang do máy tự chọn', 'info', { timeout: 1500 }); return; }
    const next = pins().filter((p) => !(p[0] >= shot.start && p[0] < shot.end));
    if (c != null) {
      // khung trên trình phát đã tính lật và phóng; lưu theo toạ độ video gốc để đổi hai thứ đó về sau vẫn đúng
      let src = c;
      if (plan.axis === 'x' || plan.axis === 'y') src = (src - 0.5) / Math.max(1, parseFloat(getPath(st.vals, 'edit.zoom')) || 1) + 0.5;
      if (plan.axis === 'x' && getPath(st.vals, 'edit.flip')) src = 1 - src;
      next.push([+((shot.start + shot.end) / 2).toFixed(3), +src.toFixed(4), plan.axis]);
    }
    setPath(st.vals, 'edit.reframe_pins', next);
    commitEdit();
    inspector.refreshReframe();
    if (c != null) toast('Đã giữ khung ở vị trí này cho cả cảnh. Bấm đúp vào khung để máy tự chọn lại', 'success', { timeout: 2600 });
  }
  const overlays = () => getPath(st.vals, 'edit.overlays') || [];
  st.ovSel = -1;
  function pickOverlay(i) {
    st.ovSel = i;
    if (inspector) inspector.onEdit();
    player.refreshSub();
    if (tl) tl.draw();
  }
  function markCutRows() {
    const c = cuts();
    for (const r of st.rows) {
      const whole = c.some(([a, b]) => r.s.start >= a - 0.01 && r.s.end <= b + 0.01);
      r.root.classList.toggle('in-cut', whole);
    }
  }
  /** Sau mỗi thay đổi dựng: lưu options, vẽ lại, ghi vào lịch sử hoàn tác */
  function commitEdit(soft) {
    inspector.editChanged(soft);
    markCutRows();
    player.refreshSub();
    if (tl) tl.draw();
    refreshQa();
    pushHistory();
  }
  function mergeCuts(list) {
    const dur = meta().duration || 0;
    const sorted = list.map(([a, b]) => [Math.max(0, Math.min(a, b)), dur ? Math.min(dur, Math.max(a, b)) : Math.max(a, b)]).filter(([a, b]) => b - a >= 0.05).sort((x, y) => x[0] - y[0]);
    const out = [];
    for (const [a, b] of sorted) {
      const l = out[out.length - 1];
      if (l && a <= l[1] + 0.001) l[1] = Math.max(l[1], b); else out.push([+a.toFixed(3), +b.toFixed(3)]);
    }
    return out;
  }
  function setCuts(list) {
    const next = mergeCuts(list);
    const dur = meta().duration || 0;
    if (dur && dur - next.reduce((n, [a, b]) => n + b - a, 0) < 0.5) { toast('Đang cắt gần hết video, không còn gì để dựng', 'warn'); return false; }
    setPath(st.vals, 'edit.cuts', next);
    commitEdit();
    return true;
  }
  const editing = {
    cuts, overlays, setCuts, commitEdit, pickOverlay,
    selection: () => (tl ? tl.sel : null),
    cutSelection() {
      const s = tl && tl.sel;
      if (!s || s[1] - s[0] < 0.05) { toast('Hãy kéo trên sóng âm để chọn đoạn cần cắt', 'info'); return; }
      if (setCuts([...cuts(), [s[0], s[1]]])) { tl.clearSel(); toast('Đã cắt đoạn. Bấm Cập nhật video để áp dụng', 'success', { timeout: 2200 }); }
    },
    keepSelection() {
      const s = tl && tl.sel;
      if (!s || s[1] - s[0] < 0.5) { toast('Hãy chọn đoạn dài hơn nửa giây', 'info'); return; }
      const dur = meta().duration || 0;
      if (setCuts([...cuts(), [0, s[0]], [s[1], dur]])) { tl.clearSel(); player.seek(s[0]); toast('Chỉ giữ lại đoạn đã chọn', 'success', { timeout: 2200 }); }
    },
    async exportSelection() {
      const s = tl && tl.sel;
      if (!s || s[1] - s[0] < 0.5) { toast('Hãy chọn đoạn dài hơn nửa giây', 'info'); return; }
      await startExport([], [[s[0], s[1]]]);
      toast('Đã xếp hàng xuất clip riêng', 'info', { timeout: 2200 });
    },
    time: () => player.time(),
    seek: (t) => player.seek(t),
    selectRange(a, b) { tl.setSel(a, b); tl.reveal(a, b); player.seek(a); },
    playRange: (a, b) => player.playRange(a, b),
    async exportClips(list, profile) {
      await startExport([], list, [], profile);
      toast(list.length > 1 ? `Đã xếp hàng xuất ${list.length} clip` : 'Đã xếp hàng xuất clip riêng', 'info', { timeout: 2200 });
    },
  };

  const pickEdit = (s) => { const o = {}; for (const k of EDIT_FIELDS) o[k] = s[k]; return o; };
  const snapOf = (s) => JSON.stringify(EDIT_FIELDS.slice(1).map((k) => s[k] ?? ''));
  function maxLen(i) {
    const segs = st.segs, s = segs[i];
    const total = meta().duration || (segs.length ? segs[segs.length - 1].end : 0);
    const nxt = i + 1 < segs.length ? segs[i + 1].start : total;
    const slot = Math.max(0.3, Math.min(nxt, s.end + 0.8) - s.start - 0.05);
    const sps = parseFloat(getPath(eff(), 'tts.syllables_per_sec')) || 5;
    return Math.max(2, Math.floor(slot * sps * 1.1));
  }

  function LineRow(s, i) {
    const r = { s, i };
    const isVi = (st.job.lang || 'vi') === 'vi';
    const timeBtn = el('button', { class: 'ln-time mono', title: 'Phát đoạn này (Ctrl+Enter khi đang sửa)', onclick: () => playLine(r) });
    const zh = el('div', { class: 'ln-zh', text: s.text || '', title: 'Bấm để sửa câu gốc', onclick: () => editZh() });
    const ta = el('textarea', {
      class: 'ln-trans', rows: 1, value: s.trans || '', placeholder: '(chưa có bản dịch)', spellcheck: 'false', 'aria-label': `Bản dịch câu ${i + 1}`,
      oninput: () => { s.trans = ta.value; grow(ta); updMeta(); markDirty(); histSoon(); if (tl) tl.draw(); player.refreshSub(); },
      onkeydown: (e) => rowKeys(e, r),
      onfocus: () => setActive(r.i, false),
    });
    const g = genderOf(s.gender);
    const people = peopleOf();
    const paintSpk = (sel) => sel.style.setProperty('--spk', speakerColor(s.speaker));
    const spkSel = people.length > 1 ? el('select', {
      class: 'ln-spk', title: 'Ai nói câu này. Đổi người thì câu này đọc bằng giọng của người đó', 'aria-label': `Người nói câu ${i + 1}`,
      onchange: () => {
        s.speaker = spkSel.value;
        const p = people.find((x) => x.id === s.speaker);
        if (p && p.gender) s.gender = p.gender;
        paintSpk(spkSel);
        markDirty();
        pushHistory();
        if (tl) tl.draw();
      },
    }, people.map((p) => el('option', { value: p.id, text: p.name }))) : null;
    if (spkSel) { spkSel.value = s.speaker || people[0].id; paintSpk(spkSel); }
    const gEl = spkSel || (g ? el('span', { class: 'ln-g g-' + g, title: g === 'female' ? 'Giọng gốc: nữ' : 'Giọng gốc: nam', text: g === 'female' ? 'Nữ' : 'Nam' }) : null);
    const speed = el('span', { class: 'ln-speed mono' });
    const meter = el('span', { class: 'ln-meter' }, el('span', { class: 'ln-meter-fill' }));
    const syl = el('span', { class: 'ln-syl mono' });
    const playBtn = el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Nghe giọng lồng (Alt+Enter khi đang sửa)', 'aria-label': 'Nghe giọng lồng', onclick: () => playClip(r) }, icon('play'));
    const voiceSel = el('select', {
      class: 'input input-xs ln-voice', title: 'Giọng riêng cho câu này', 'aria-label': 'Giọng riêng cho câu này',
      onchange: () => { s.voice = voiceSel.value; markDirty(); pushHistory(); },
    });
    let filled = false;
    const fillLite = () => {
      voiceSel.replaceChildren(el('option', { value: '' }, 'Giọng chung'));
      if (s.voice) voiceSel.append(el('option', { value: s.voice }, voiceLabel(engineOf(), s.voice, langOf())));
      voiceSel.value = s.voice || '';
    };
    const fillFull = () => { filled = true; fillVoiceSelect(voiceSel, engineOf(), { current: s.voice || '', defaultLabel: 'Giọng chung', lang: langOf() }); };
    fillLite();
    voiceSel.addEventListener('pointerdown', () => { if (!filled) fillFull(); });
    voiceSel.addEventListener('focus', () => { if (!filled) fillFull(); });
    r.refreshVoices = () => { if (filled) fillFull(); else fillLite(); };
    const speakBtn = el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Đọc thử bản đang sửa bằng giọng của câu này', 'aria-label': 'Đọc thử', onclick: () => speakLine(r) }, icon('volume'));
    const retransBtn = el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Dịch lại câu này', 'aria-label': 'Dịch lại câu này', onclick: () => retranslateLine(r, retransBtn) }, icon('globe'));
    const recBtn = el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Thu giọng của bạn cho câu này', 'aria-label': 'Thu giọng của bạn', onclick: () => openRecorder(r) }, icon('mic'));
    const recChip = el('span', { class: 'ln-rec', title: 'Câu này dùng giọng bạn thu', text: 'Giọng thu', hidden: !s.rec });
    const chkChip = el('button', {
      class: 'ln-check', type: 'button', title: CHECK_TIPS[s.check] || '', text: s.check === 'ocr' ? 'Soát: chỉ có chữ' : 'Soát: chỉ có tiếng', hidden: !s.check,
      onclick: (e) => { e.stopPropagation(); s.check = ''; chkChip.hidden = true; updMeta(); markDirty(); pushHistory(); applyFilter(); },
    });
    const splitBtn = el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Tách câu tại vị trí con trỏ', 'aria-label': 'Tách câu', onclick: () => splitLine(r) }, icon('scissors'));
    const mergeBtn = el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Gộp với câu sau', 'aria-label': 'Gộp với câu sau', onclick: () => mergeLine(r) }, icon('merge'));
    const root = el('div', { class: 'ln', dataset: { id: String(s.id) }, onclick: (e) => { if (e.target === root) setActive(r.i, false); } },
      el('div', { class: 'ln-gutter' }, el('span', { class: 'ln-idx mono', text: String(i + 1) }), el('span', { class: 'ln-dirty', title: 'Chưa lưu' })),
      el('div', { class: 'ln-main' },
        el('div', { class: 'ln-top' }, timeBtn, gEl, recChip, chkChip, speed, el('span', { class: 'grow' }), playBtn),
        zh, ta,
        el('div', { class: 'ln-foot' }, meter, syl, el('span', { class: 'grow' }), el('span', { class: 'ln-tools' }, voiceSel, speakBtn, retransBtn, recBtn, splitBtn, mergeBtn))));
    Object.assign(r, { root, ta, playBtn, speakBtn, recChip, updTime, updMeta, markDirty, grow: () => grow(ta) });
    function updTime() { timeBtn.textContent = `${fmtTime(s.start)} → ${fmtTime(s.end)}`; }
    function updMeta() {
      const n = words(s.trans);
      if (isVi) {
        const m = maxLen(r.i);
        syl.textContent = `${n}/${m}`;
        syl.title = 'Số âm tiết / mức đọc kịp trong khung thời gian';
        const ratio = clamp(n / m, 0, 1);
        meter.firstChild.style.width = ratio * 100 + '%';
        meter.classList.toggle('over', n > m);
        syl.classList.toggle('over', n > m);
      } else { syl.textContent = `${n} từ`; meter.hidden = true; }
      const v = Number(s.speed);
      speed.textContent = v ? v.toFixed(2).replace('.', ',') + 'x' : '';
      speed.className = 'ln-speed mono ' + (!v ? '' : v <= 1.05 ? 'ok' : v <= 1.3 ? 'warn' : 'bad');
      speed.title = v ? 'Giọng đọc đang phải nhanh gấp từng này lần để vừa câu' : '';
      root.classList.toggle('bad', !(s.trans || '').trim() || v > 1.3);
      root.classList.toggle('chk', !!s.check);
      chkChip.hidden = !s.check;
    }
    function markDirty() { root.classList.toggle('dirty', snapOf(s) !== st.snap.get(s.id)); updateStats(); }
    function editZh() {
      if (zh.querySelector('input')) return;
      const inp = el('input', { class: 'input input-xs', value: s.text || '', spellcheck: 'false', 'aria-label': 'Sửa câu gốc' });
      const done = (commit) => {
        if (commit) { const v = inp.value.trim(); if (v !== (s.text || '')) s.check = ''; s.text = v; updMeta(); markDirty(); pushHistory(); }
        zh.textContent = s.text || '';
      };
      inp.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); done(true); } if (e.key === 'Escape') { e.preventDefault(); done(false); } });
      inp.addEventListener('blur', () => { if (inp.isConnected) done(true); });
      zh.replaceChildren(inp);
      inp.focus();
    }
    updTime();
    updMeta();
    return r;
  }
  const fieldSizing = typeof CSS !== 'undefined' && CSS.supports && CSS.supports('field-sizing', 'content');
  function grow(ta) { if (fieldSizing) return; ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px'; }

  function buildRows(resetSnap = true) {
    if (resetSnap) {
      st.segs = (st.job.segments || []).map((s) => Object.assign({}, s));
      st.snap = new Map(st.segs.map((s) => [s.id, snapOf(s)]));
      st.dubOrig = new Map(st.segs.map((s) => [s.id, { start: s.start, end: s.end, dub_start: s.dub_start, dub_end: s.dub_end, speed: s.speed }]));
      st.recs = new Map(st.segs.map((s) => [s.id, s.rec || '']));
    }
    st.rows = st.segs.map((s, i) => LineRow(s, i));
    st.rows.forEach((r) => r.root.classList.toggle('dirty', snapOf(r.s) !== st.snap.get(r.s.id)));
    st.activeIdx = -1;
    if (!st.rows.length) {
      list.replaceChildren(emptyState('Chưa có phụ đề', 'Video chưa qua bước nhận dạng, hoặc không có lời thoại.',
        el('button', { class: 'btn btn-sm', onclick: () => busy(null, () => runStage('asr')) }, icon('refresh'), 'Nhận dạng lại')));
    } else {
      list.replaceChildren(...st.rows.map((r) => r.root));
      if (!fieldSizing) requestAnimationFrame(() => st.rows.forEach((r) => grow(r.ta)));
    }
    applyFilter();
    markCutRows();
    updateStats();
    if (tl) tl.draw();
  }
  const refreshQa = debounce(() => paintScore(), 200);
  function updateStats() {
    const n = st.segs.length;
    const tr = st.segs.filter((s) => (s.trans || '').trim()).length;
    st.dirty = st.rows.filter((r) => r.root.classList.contains('dirty')).length;
    const sp = st.segs.map((s) => Number(s.speed)).filter((x) => x > 0);
    const avg = sp.length ? sp.reduce((a, b) => a + b, 0) / sp.length : 0;
    put(stats,
      el('b', { text: String(n) }), ' câu',
      tr < n ? [' · ', el('b', { text: String(tr) }), ' đã dịch'] : null,
      avg ? [' · đọc TB ', el('b', { class: 'mono', text: avg.toFixed(2).replace('.', ',') + 'x' })] : null,
      st.dirty ? el('span', { class: 'unsaved', text: ` · ${st.dirty} chưa lưu` }) : null);
    paintUpdate();
    refreshQa();
  }
  function paintScore() {
    const q = runChecks(st.job, st.segs, { dirty: st.dirty, cuts: cuts(), eff: st.vals });
    st.qa = q;
    const fileQc = st.job.qc && st.job.qc.fresh !== false ? st.job.qc.score : null;
    const score = fileQc == null ? q.score : Math.min(q.score, fileQc);      // hai phép đo: lấy điểm thấp hơn, không để hai con số mâu thuẫn
    const cls = score >= 85 ? 'ok' : score >= 60 ? 'warn' : 'bad';
    scoreBtn.className = 'score-chip ' + cls;
    put(scoreBtn, icon('shield'), el('span', { class: 'mono', text: String(score) }));
    scoreBtn.setAttribute('aria-label', `Điểm sẵn sàng đăng: ${score} trên 100`);
    if (inspector) inspector.onQa(q);
  }
  function applyFilter() {
    const q = findInp.value.trim().toLowerCase();
    const bad = onlyBad.classList.contains('active');
    for (const r of st.rows) {
      const match = !q || (r.s.text || '').toLowerCase().includes(q) || (r.s.trans || '').toLowerCase().includes(q);
      r.root.hidden = !match || (bad && !r.root.classList.contains('bad') && !r.root.classList.contains('chk'));
    }
  }
  function replaceAll() {
    const a = findInp.value, b = replInp.value;
    if (!a) { toast('Hãy nhập chữ cần tìm', 'warn'); findInp.focus(); return; }
    const re = new RegExp(a.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    let n = 0;
    for (const r of st.rows) {
      const t = r.s.trans || '';
      const next = t.replace(re, () => { n++; return b; });
      if (next !== t) { r.s.trans = next; r.ta.value = next; grow(r.ta); r.updMeta(); r.markDirty(); }
    }
    if (n) { pushHistory(); if (tl) tl.draw(); player.refreshSub(); }
    toast(n ? `Đã thay ${n} chỗ` : 'Không tìm thấy chữ này', n ? 'success' : 'info');
  }
  function setActive(i, scroll) {
    if (i === st.activeIdx) return;
    if (st.activeIdx >= 0 && st.rows[st.activeIdx]) st.rows[st.activeIdx].root.classList.remove('active');
    st.activeIdx = i;
    const r = st.rows[i];
    if (tl) tl.draw();
    if (!r) return;
    r.root.classList.add('active');
    if (scroll && !r.root.hidden) {
      const editing = list.contains(document.activeElement) && document.activeElement !== list;
      if (!editing && Date.now() - st.userScrollAt > 2500) list.scrollTo({ top: r.root.offsetTop - list.clientHeight * 0.3, behavior: 'smooth' });
    }
  }
  list.addEventListener('wheel', () => { st.userScrollAt = Date.now(); }, { passive: true });
  function syncActive(t) {
    for (let i = 0; i < st.segs.length; i++) {
      const s = st.segs[i];
      const a = s.start, b = Math.max(s.end, s.dub_end != null ? s.dub_end : s.end);
      if (t >= a && t < b) { setActive(i, player.isPlaying()); return; }
      if (a > t) return;
    }
  }
  function playLine(r) {
    stopAudio();
    const s = r.s;
    if (player.mode === 'final' && !hasFile('final')) player.setMode('preview');
    player.playRange(s.start, Math.max(s.end, s.dub_end != null ? s.dub_end : s.end));
    setActive(r.i, false);
  }
  function playClip(r) {
    if (r.root.classList.contains('dirty') && snapOf(r.s) !== st.snap.get(r.s.id)) toast('Câu này đã sửa nhưng chưa lồng lại: đang phát bản lồng cũ', 'info', { timeout: 2500 });
    playUrl(`/api/jobs/${enc(id)}/clip/${enc(r.s.id)}?v=${player.bust}`, r.playBtn);
  }
  /** Giọng thực tế sẽ đọc câu này: giọng riêng của câu, rồi giọng của người nói, rồi mặc định theo nam nữ */
  function voiceOfLine(s) {
    const v = eff();
    const engine = engineOf();
    const lang = langOf();
    const fits = (x) => voiceFits(x, engine, lang);
    if (fits(s.voice)) return s.voice;
    const mode = getPath(v, 'tts.voice_mode') || 'auto';
    if (mode === 'fixed') {
      const f = getPath(v, engine === 'edge' ? 'tts.voice' : engine === 'vox' ? 'tts.vox_voice' : 'tts.vieneu_voice');
      return fits(f) ? f : defaultVoice(engine, lang, genderOf(s.gender) || 'female');
    }
    if (mode === 'auto') {
      const p = peopleOf().find((x) => x.id === s.speaker);
      if (p && fits(p.voice || p.auto_voice)) return p.voice || p.auto_voice;
    }
    const female = genderOf(s.gender) === 'female';
    const chosen = getPath(v, female ? 'tts.female_voice' : 'tts.male_voice');
    if (fits(chosen)) return chosen;
    return defaultVoice(engine, lang, female ? 'female' : 'male');
  }
  async function speakLine(r) {
    const text = (r.s.trans || '').trim();
    if (!text) { toast('Câu này chưa có bản dịch', 'info'); return; }
    if (r.speakBtn.classList.contains('playing')) { stopAudio(); return; }
    r.speakBtn.classList.add('is-busy');
    r.speakBtn.disabled = true;
    try {
      const blob = await api('POST', '/api/tts/preview', { engine: engineOf(), voice: voiceOfLine(r.s), text, lang: langOf() }, { blob: true });
      playUrl(URL.createObjectURL(blob), r.speakBtn);
    } catch (e) { toast('Không đọc thử được: ' + e.message, 'error'); } finally {
      r.speakBtn.classList.remove('is-busy');
      r.speakBtn.disabled = false;
    }
  }
  async function retranslateLine(r, btn) {
    return busy(btn, async () => {
      if (st.dirty) await save(true);
      const res = await api('POST', `/api/jobs/${enc(id)}/lines/${enc(r.s.id)}/retranslate`);
      const old = r.s.trans || '';
      if (res.text === old) { toast('Bản dịch mới giống hệt bản cũ', 'info', { timeout: 1800 }); return; }
      r.s.trans = res.text;
      r.ta.value = res.text;
      r.grow();
      r.updMeta();
      r.markDirty();
      pushHistory();
      player.refreshSub();
      if (tl) tl.draw();
      toast('Đã dịch lại câu này', 'success', { timeout: 2200, actions: [{ label: 'Dùng bản cũ', onClick: () => { r.s.trans = old; r.ta.value = old; r.grow(); r.updMeta(); r.markDirty(); pushHistory(); player.refreshSub(); } }] });
    });
  }
  /** Thu giọng từ micro hoặc tải file âm thanh cho đúng một câu */
  function openRecorder(r) {
    const s = r.s;
    let media = null, rec = null, chunks = [], blob = null, timer = 0, started = 0, closed = false;
    const slot = Math.max(0.3, s.end - s.start);
    const status = el('div', { class: 'small muted', text: `Câu này dài ${slot.toFixed(1).replace('.', ',')} giây. Thu dài hơn sẽ được tăng tốc cho vừa.` });
    const clock = el('div', { class: 'rec-clock mono', text: '00:00.0' });
    const cleanInp = el('input', { type: 'checkbox', checked: getPath(eff(), 'tts.rec_clean') !== false });
    const cleanRow = el('label', { class: 'rec-clean small', title: 'Lọc tiếng ù, giảm ồn nền, bớt tiếng xì, cân lại âm lượng' }, cleanInp, 'Làm sạch giọng khi lưu');
    const player_ = el('audio', { controls: true, class: 'rec-audio', hidden: true });
    const startBtn = el('button', { class: 'btn btn-primary', onclick: () => startRec() }, icon('mic'), 'Bắt đầu thu');
    const stopBtn = el('button', { class: 'btn btn-danger', hidden: true, onclick: () => stopRec() }, icon('stop'), 'Dừng');
    const saveBtn = el('button', { class: 'btn btn-primary', hidden: true, onclick: () => busy(saveBtn, () => upload(blob)) }, icon('check'), 'Dùng bản thu này');
    const file = el('input', { type: 'file', accept: 'audio/*,video/*', hidden: true, onchange: () => { const f = file.files[0]; if (f) busy(fileBtn, () => upload(f)); } });
    const fileBtn = el('button', { class: 'btn', onclick: () => file.click() }, icon('upload'), 'Tải file âm thanh');
    const removeBtn = el('button', {
      class: 'btn btn-ghost', hidden: !s.rec, onclick: () => busy(removeBtn, async () => {
        await api('DELETE', `/api/jobs/${enc(id)}/lines/${enc(s.id)}/audio`);
        s.rec = '';
        st.recs.set(s.id, '');
        r.recChip.hidden = true;
        st.job.stale = true;
        paintUpdate();
        m.close();
        toast('Đã bỏ giọng thu, câu này sẽ đọc lại bằng giọng máy. Bấm Cập nhật video', 'info');
      }),
    }, icon('trash'), 'Bỏ giọng thu, dùng giọng máy');
    function stopStream() { if (media) { media.getTracks().forEach((t) => t.stop()); media = null; } clearInterval(timer); }
    async function startRec() {
      try {
        media = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      } catch (e) { toast('Không mở được micro. Hãy cho phép trình duyệt dùng micro, hoặc tải file âm thanh.', 'error'); return; }
      if (closed) { stopStream(); return; }
      chunks = [];
      blob = null;
      rec = new MediaRecorder(media);
      rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
      rec.onstop = () => {
        blob = new Blob(chunks, { type: rec.mimeType || 'audio/webm' });
        player_.src = URL.createObjectURL(blob);
        player_.hidden = false;
        saveBtn.hidden = false;
        startBtn.hidden = false;
        startBtn.replaceChildren(icon('refresh'), 'Thu lại');
        stopBtn.hidden = true;
        stopStream();
      };
      rec.start();
      started = Date.now();
      startBtn.hidden = true;
      stopBtn.hidden = false;
      saveBtn.hidden = true;
      player_.hidden = true;
      timer = setInterval(() => { clock.textContent = fmtTime((Date.now() - started) / 1000); }, 100);
    }
    function stopRec() { if (rec && rec.state !== 'inactive') rec.stop(); }
    async function upload(b) {
      if (st.dirty) await save(true);
      const res = await fetch(`/api/jobs/${enc(id)}/lines/${enc(s.id)}/audio?clean=${cleanInp.checked ? 1 : 0}`, { method: 'PUT', body: b });
      if (!res.ok) {
        let msg = `Lỗi ${res.status}`;
        try { msg = (await res.json()).detail || msg; } catch (_) { /* giữ mặc định */ }
        toast(msg, 'error');
        return;
      }
      const d = await res.json();
      s.rec = d.rec;
      st.recs.set(s.id, d.rec);
      const inJob = (st.job.segments || []).find((x) => x.id === s.id);
      if (inJob) inJob.rec = d.rec;
      r.recChip.hidden = false;
      st.job.stale = true;
      paintUpdate();
      m.close();
      toast('Đã lưu giọng của bạn cho câu này. Bấm Cập nhật video để ghép vào', 'success');
    }
    const m = openModal([
      modalHead('mic', `Thu giọng câu ${r.i + 1}`, () => m),
      el('div', { class: 'modal-body rec-body' },
        el('div', { class: 'rec-line', text: s.trans || '(chưa có bản dịch)' }), status, clock, player_, cleanRow,
        s.rec ? el('div', { class: 'small muted' }, 'Bản đang dùng: ', el('audio', { controls: true, class: 'rec-audio', src: `/api/jobs/${enc(id)}/lines/${enc(s.id)}/audio?v=${s.rec}` })) : null),
      el('div', { class: 'modal-foot' }, removeBtn, file, fileBtn, el('span', { class: 'grow' }), startBtn, stopBtn, saveBtn),
    ], { cls: 'modal-rec', onClose: () => { closed = true; stopRec(); stopStream(); } });
  }
  function rowKeys(e, r) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); playLine(r); return; }
    if (e.altKey && e.key === 'Enter') { e.preventDefault(); playClip(r); return; }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault();
      const dir = e.key === 'ArrowDown' ? 1 : -1;
      let j = r.i + dir;
      while (st.rows[j] && st.rows[j].root.hidden) j += dir;
      const n = st.rows[j];
      if (n) { n.ta.focus(); n.root.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
    }
  }
  function focusLine(i, seek) {
    const r = st.rows[i];
    if (!r) return;
    r.root.hidden = false;
    setActive(i, false);
    st.userScrollAt = 0;
    list.scrollTo({ top: r.root.offsetTop - list.clientHeight * 0.3, behavior: 'smooth' });
    if (seek) { player.pause(); player.seek(r.s.start); if (tl) tl.reveal(r.s.start, r.s.end); }
  }

  // ---- tách / gộp câu
  function splitLine(r) {
    const s = r.s;
    const text = s.trans || '';
    let pos = r.ta.selectionStart || 0;
    if (pos <= 0 || pos >= text.length) pos = Math.floor(text.length / 2);
    const cut = text.lastIndexOf(' ', pos) > 0 ? text.lastIndexOf(' ', pos) : pos;
    const ratio = text.length ? clamp(cut / text.length, 0.15, 0.85) : 0.5;
    const mid = +(s.start + (s.end - s.start) * ratio).toFixed(3);
    if (mid - s.start < 0.2 || s.end - mid < 0.2) { toast('Câu quá ngắn để tách', 'warn'); return; }
    const zh = s.text || '';
    const zhCut = Math.round(zh.length * ratio);
    const nid = Math.max(...st.segs.map((x) => x.id)) + 1;
    const ns = Object.assign({}, s, { id: nid, start: mid, text: zh.slice(zhCut), trans: text.slice(cut).trim(), dub_start: null, dub_end: null, speed: null, ocr: '', rec: '' });
    Object.assign(s, { end: mid, text: zh.slice(0, zhCut), trans: text.slice(0, cut).trim(), dub_start: null, dub_end: null, speed: null, ocr: '', rec: '' });
    st.snap.set(nid, '');
    st.segs.splice(r.i + 1, 0, ns);
    buildRows(false);
    pushHistory();
    focusLine(r.i + 1);
  }
  function mergeLine(r) {
    const s = r.s, n = st.segs[r.i + 1];
    if (!n) { toast('Đây là câu cuối', 'info'); return; }
    Object.assign(s, {
      end: n.end, text: `${s.text || ''} ${n.text || ''}`.trim(), trans: `${s.trans || ''} ${n.trans || ''}`.trim(),
      dub_start: null, dub_end: null, speed: null, ocr: '', rec: '',
    });
    st.segs.splice(r.i + 1, 1);
    buildRows(false);
    pushHistory();
    focusLine(r.i);
  }

  // ---- hoàn tác / làm lại
  const editState = () => JSON.stringify({ s: st.segs.map((x) => { const o = {}; for (const k of HISTORY_FIELDS) o[k] = x[k]; return o; }), c: cuts(), o: overlays(), p: pins(), f: [getPath(st.vals, 'edit.focus_x'), getPath(st.vals, 'edit.focus_y')] });
  function pushHistory() {
    const cur = editState();
    if (cur === st.lastHist) return;
    st.history.push(st.lastHist);
    if (st.history.length > 200) st.history.shift();
    st.future = [];
    st.lastHist = cur;
    paintUpdate();
  }
  const histSoon = debounce(pushHistory, 500);
  /** câu về đúng thời gian đã lồng thì lấy lại thông tin lồng tiếng; còn lệch thì coi như chưa lồng */
  function applyDub(s) {
    const o = st.dubOrig.get(s.id);
    const same = o && o.start === s.start && o.end === s.end;
    s.dub_start = same ? o.dub_start : null;
    s.dub_end = same ? o.dub_end : null;
    s.speed = same ? o.speed : null;
    return s;
  }
  function restore(json) {
    const old = new Map(st.segs.map((s) => [s.id, s]));
    const d = JSON.parse(json);
    st.segs = d.s.map((e) => applyDub(Object.assign({}, old.get(e.id) || {}, e, { rec: st.recs.get(e.id) || '' })));
    const pinsChanged = JSON.stringify(pins()) !== JSON.stringify(d.p || []);
    const focusNow = [getPath(st.vals, 'edit.focus_x'), getPath(st.vals, 'edit.focus_y')];
    const focusChanged = JSON.stringify(focusNow) !== JSON.stringify(d.f || focusNow);
    if (d.f) { setPath(st.vals, 'edit.focus_x', d.f[0]); setPath(st.vals, 'edit.focus_y', d.f[1]); }
    const editChanged = focusChanged || pinsChanged || JSON.stringify(cuts()) !== JSON.stringify(d.c) || JSON.stringify(overlays()) !== JSON.stringify(d.o);
    setPath(st.vals, 'edit.cuts', d.c);
    setPath(st.vals, 'edit.overlays', d.o);
    setPath(st.vals, 'edit.reframe_pins', d.p || []);
    st.lastHist = json;
    buildRows(false);
    if (editChanged) { st.ovSel = -1; inspector.editChanged(); }
    player.refreshSub();
    if (tl) tl.draw();
  }
  function undo() { pushHistory(); if (!st.history.length) return; st.future.push(st.lastHist); restore(st.history.pop()); }
  function redo() { if (!st.future.length) return; st.history.push(st.lastHist); restore(st.future.pop()); }

  // ------------------------------------------------ lưu / chạy lại
  async function save(silent) {
    const payload = st.segs.map((s) => ({ id: s.id, start: s.start, end: s.end, text: s.text || '', trans: s.trans || '', voice: s.voice || '', gender: s.gender || '', speaker: s.speaker || '', rec: s.rec || '', check: s.check || '' }));
    const sent = st.segs.map((s) => [s.id, snapOf(s)]);      // gõ thêm lúc đang gửi thì câu đó vẫn là chưa lưu
    await api('PUT', `/api/jobs/${enc(id)}/segments`, { segments: payload });
    sent.forEach(([k, v]) => st.snap.set(k, v));
    st.recs = new Map(payload.map((x) => [x.id, x.rec]));
    st.rows.forEach((r) => r.root.classList.toggle('dirty', snapOf(r.s) !== st.snap.get(r.s.id)));
    st.job.segments = st.segs.map((s) => Object.assign({}, s));
    st.job.stale = true;
    updateStats();
    if (!silent) toast('Đã lưu phụ đề', 'success', { timeout: 1800 });
  }
  async function runStage(stage, extra) {
    const r = await runJob(id, stage, extra);
    st.watchQid = r && r.qid ? r.qid : null;
    showRun({ state: 'queued', stage: null, progress: null });
    setRunActive(true);
  }
  async function saveAndRun(stage) {
    await inspector.flush();
    if (st.dirty) await save(true);
    await runStage(stage);
  }
  async function retranslate() {
    await inspector.flush();
    const ok = await confirmDialog('Dịch lại toàn bộ?', 'Toàn bộ bản dịch hiện tại, kể cả câu bạn đã sửa tay, sẽ bị thay bằng bản dịch mới, sau đó lồng tiếng và dựng lại video.', { okText: 'Dịch lại', danger: true });
    if (!ok) return;
    await busy(null, () => runStage('translate'));
  }
  async function startExport(targets, clips, profiles, clipProfile) {
    await inspector.flush();
    if (st.dirty) await save(true);
    const r = await api('POST', `/api/jobs/${enc(id)}/export`, { targets, clips: clips || [], profiles: profiles || [], clip_profile: clipProfile || '' });
    pollSoon();
    st.watchQid = r.qid;
    showRun({ state: 'queued', stage: null, progress: null });
    setRunActive(true);
  }
  function setRunActive(on) {
    const changed = st.runActive !== on;      // hàm này được gọi mỗi lần hỏi hàng đợi: vẽ lại mỗi giây sẽ làm đóng ô chọn và mất lần bấm
    st.runActive = on;
    updateBtn.disabled = on;
    updateBtn.title = on ? 'Đang có tác vụ chạy cho video này' : 'Lưu rồi làm lại đúng những gì đã đổi: đọc lại câu đã sửa và dựng lại video';
    if (inspector && changed) inspector.onRun(on);
  }
  async function reloadJob({ toFinal = false, quiet = false } = {}) {
    let j;
    try { j = await api('GET', `/api/jobs/${enc(id)}`); } catch (e) { toast('Không tải lại được dữ liệu: ' + e.message, 'error'); return; }
    if (!alive()) return;
    if (st.dirty > 0) {
      const fresh = j.segments;
      st.job = Object.assign({}, j, { segments: st.job.segments });
      if (!quiet) {
        toast('Đã có kết quả mới, nhưng bạn đang có thay đổi chưa lưu nên danh sách câu được giữ nguyên.', 'warn', {
          actions: [{ label: 'Tải bản mới (bỏ thay đổi)', onClick: () => { st.job.segments = fresh; buildRows(); } }],
        });
      }
    } else {
      const sameLines = JSON.stringify((st.job.segments || []).map((s) => s.id)) === JSON.stringify((j.segments || []).map((s) => s.id));
      if (!sameLines) { st.history = []; st.future = []; }
      st.job = j;
      const top = list.scrollTop;
      buildRows();
      list.scrollTop = top;
      st.lastHist = editState();
    }
    renderHead();
    player.setBust(Date.now());
    player.setMode(toFinal && hasFile('final') ? 'final' : player.mode, true);
    loadPeaks('dub');
    inspector.onJob();
    paintScore();
  }
  const onQueue = (items) => {
    let it = st.watchQid ? items.find((i) => i.qid === st.watchQid) : null;
    if (!it) {
      it = items.find((i) => i.job === id && (i.state === 'queued' || i.state === 'running'));
      if (it) st.watchQid = it.qid;
    }
    if (!it) { if (st.runActive) setRunActive(false); return; }
    showRun(it);
    const active = it.state === 'queued' || it.state === 'running';
    setRunActive(active);
    if (!active && !st.handled.has(it.qid)) {
      st.handled.add(it.qid);
      st.watchQid = null;
      if (it.state === 'done' && it.editor_base && !(it.targets || []).length && !(it.clips || []).length && !(it.profiles || []).length) {
        toast('Đã chuẩn bị xong video cho trình dựng', 'success');      // lượt này không đổi bản chính, chỉ cần lấy lại thông tin
        reloadJob({ quiet: true });
        setTimeout(() => { if (!st.runActive) runbar.hidden = true; }, 3500);
      } else if (it.state === 'done') {
        toast('Xong! Video đã được cập nhật.', 'success');
        reloadJob({ toFinal: true });
        setTimeout(() => { if (!st.runActive) runbar.hidden = true; }, 3500);
      } else if (it.state === 'error') {
        itemErrorToast('Tác vụ lỗi: ', it);
        reloadJob();
      } else {
        toast('Đã hủy tác vụ', 'info');
        reloadJob({ quiet: true });      // hủy ở bước sau bản chính thì bản chính đã đổi rồi: phải lấy lại thông tin thời gian, kiểm định
        setTimeout(() => { if (!st.runActive) runbar.hidden = true; }, 2200);
      }
    }
  };

  // ------------------------------------------------ bảng thuộc tính
  const inspector = Inspector({
    st, id, meta, eff, getBox, hasFile, player, retranslate, startExport, save, saveAndRun, reloadJob, editing,
    markStale: () => { st.job.stale = true; paintUpdate(); },
    focusLine: (i) => focusLine(i, true),
    refreshQa: () => refreshQa(),
    onOptionChange: () => { st.job.stale = true; paintUpdate(); refreshQa(); st.rows.forEach((r) => r.refreshVoices()); player.refreshSub(); },
  });

  // ------------------------------------------------ timeline
  const tl = Timeline({
    duration: () => meta().duration || (st.segs.length ? st.segs[st.segs.length - 1].end : 1),
    getSegs: () => st.segs, getTime: () => player.time(), getActive: () => st.activeIdx,
    onSeek: (t) => player.seek(t),
    onSelect: (i) => { setActive(i, false); const r = st.rows[i]; if (r) list.scrollTo({ top: r.root.offsetTop - list.clientHeight * 0.3, behavior: 'smooth' }); },
    onDrag: (i) => { applyDub(st.segs[i]); const r = st.rows[i]; if (r) { r.updTime(); r.updMeta(); r.markDirty(); } player.refreshSub(); },
    onCommit: () => pushHistory(),
    onOpen: (i) => { const r = st.rows[i]; if (r) { focusLine(i); r.ta.focus(); } },
    getCuts: cuts, getOverlays: overlays, getOverlaySel: () => st.ovSel, getScenes: () => st.scenes || [],
    onSelRange: () => { if (inspector) inspector.onEdit(); },
    onCutRestore: (i) => { const c = cuts().slice(); c.splice(i, 1); setCuts(c); toast('Đã khôi phục đoạn này', 'info', { timeout: 1800 }); },
    onOverlayPick: (i) => pickOverlay(i),
    onOverlayDrag: () => { player.refreshSub(); if (inspector) inspector.onEdit(true); },
    onOverlayCommit: () => commitEdit(),
    actions: { cut: () => editing.cutSelection(), keep: () => editing.keepSelection(), exportClip: () => busy(null, () => editing.exportSelection()) },
  });
  async function loadPeaks(name) {
    try { tl.setPeaks(name, await api('GET', `/api/jobs/${enc(id)}/peaks/${name}?v=${Date.now()}`)); } catch (_) { tl.setPeaks(name, null); }
  }
  // kéo để đổi chiều cao timeline
  const tlHandle = el('div', { class: 'tl-handle', title: 'Kéo để đổi chiều cao timeline' });
  const savedH = parseInt(localStorage.getItem('ic.tlH') || '0', 10);
  if (savedH) main.style.setProperty('--tl-h', clamp(savedH, 140, 460) + 'px');
  tlHandle.addEventListener('pointerdown', (e) => {
    tlHandle.setPointerCapture(e.pointerId);
    const y0 = e.clientY, h0 = tl.root.getBoundingClientRect().height;
    const move = (ev) => { main.style.setProperty('--tl-h', clamp(h0 + y0 - ev.clientY, 140, 460) + 'px'); };
    const up = () => {
      tlHandle.removeEventListener('pointermove', move);
      tlHandle.removeEventListener('pointerup', up);
      localStorage.setItem('ic.tlH', String(Math.round(tl.root.getBoundingClientRect().height)));
    };
    tlHandle.addEventListener('pointermove', move);
    tlHandle.addEventListener('pointerup', up);
  });

  // ------------------------------------------------ dựng bố cục
  // chế độ Đơn giản: bảng tùy chọn là ngăn kéo bên phải, mở khi bấm Kiểm tra, Xuất & đăng... và có nút đóng
  const inspClose = el('button', { class: 'btn btn-icon btn-ghost insp-close', title: 'Đóng', 'aria-label': 'Đóng bảng tùy chọn', onclick: () => main.classList.remove('insp-open') }, icon('x'));
  inspector.root.prepend(inspClose);
  const openInsp = inspector.open;
  inspector.open = (k) => { if (mode === 'simple') main.classList.add('insp-open'); return openInsp(k); };
  editorBtn.classList.add('st-pro-only');
  main.append(head, runbar,
    el('div', { class: 'st-body' }, linesPane, el('section', { class: 'pane pl-pane' }, player.root), inspector.root),
    tlHandle, tl.root);
  setMode(mode);
  renderHead();
  buildRows();
  st.lastHist = editState();
  inspector.onJob();
  paintScore();
  player.setMode(hasFile('final') ? 'final' : 'preview');
  loadPeaks('audio');
  loadPeaks('dub');
  api('GET', `/api/jobs/${enc(id)}/scenes`).then((r) => { st.scenes = r.times || []; tl.draw(); }).catch(() => { st.scenes = []; });
  api('GET', '/api/profiles').then((r) => { S.profiles = r.items; player.setSafeZone(r.safe_9x16); inspector.onJob(); }).catch(() => {});
  const jumpScene = (dir) => {
    // điểm chuyển cảnh trong đoạn đã cắt không tồn tại trên bản dựng, nhảy vào đó sẽ bị kéo ngược lại và kẹt
    const madeCuts = (st.job.rendered && st.job.rendered.cuts) || [];      // bản đang xem được dựng với đoạn cắt này, không phải đoạn đang sửa dở
    const list = (st.scenes || []).filter((x) => player.mode !== 'final' || !madeCuts.some(([a, b]) => x >= a && x < b));
    const now = player.time();
    const t = dir > 0 ? list.find((x) => x > now + 0.05) : [...list].reverse().find((x) => x < now - 0.05);
    if (t != null) { player.seek(t); tl.reveal(t, t); } else if (dir < 0) player.seek(0);
  };

  const inField = (t) => t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
  const onKey = (e) => {
    if (modalStack.length) return;
    const k = e.key;
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === 's') {
      e.preventDefault();
      if (st.dirty) busy(saveBtn, () => save()); else toast('Không có thay đổi nào cần lưu', 'info', { timeout: 1400 });
      return;
    }
    if (inField(e.target)) return;
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === 'z') { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === 'y') { e.preventDefault(); redo(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (k === ' ') { e.preventDefault(); stopAudio(); player.toggle(); } else if (k === 'ArrowLeft' || k === 'ArrowRight') {
      e.preventDefault();
      player.step((k === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 5 : 1));
      tl.reveal(player.time(), player.time());
    } else if (k === 'ArrowUp' || k === 'ArrowDown') {
      e.preventDefault();
      const j = clamp((st.activeIdx < 0 ? 0 : st.activeIdx + (k === 'ArrowUp' ? -1 : 1)), 0, st.rows.length - 1);
      focusLine(j, true);
    } else if (k === 'i' || k === 'I') tl.markIn();
    else if (k === 'o' || k === 'O') tl.markOut();
    else if (k === '[') jumpScene(-1);
    else if (k === ']') jumpScene(1);
    else if (k === 'Delete' || k === 'Backspace') { e.preventDefault(); editing.cutSelection(); } else if (k === 'Escape') tl.clearSel();
    else if (k === 'Enter' && st.rows[st.activeIdx]) { e.preventDefault(); st.rows[st.activeIdx].ta.focus(); } else if (k === '+' || k === '=') tl.zoomBy(1.5);
    else if (k === '-') tl.zoomBy(1 / 1.5);
    else if (k === '0') tl.fit();
    else if (k === '?') openShortcuts();
  };
  document.addEventListener('keydown', onKey);
  const vh = () => { if (S.studio !== st) return false; st.rows.forEach((r) => r.refreshVoices()); return true; };
  voiceHooks.add(vh);
  onQueue(S.queue);
  queueListeners.add(onQueue);

  st.commands = () => [
    { label: 'Lưu phụ đề', hint: 'Ctrl+S', icon: 'save', run: () => { if (st.dirty) busy(saveBtn, () => save()); else toast('Không có thay đổi nào cần lưu', 'info', { timeout: 1400 }); } },
    { label: 'Cập nhật video', icon: 'refresh', run: () => busy(updateBtn, () => saveAndRun(null)) },
    { label: 'Xuất và đăng', icon: 'export', run: () => inspector.open('publish') },
    { label: 'Dịch lại toàn bộ', icon: 'globe', run: () => retranslate() },
    { label: 'Kiểm tra trước khi đăng', icon: 'shield', run: () => inspector.open('qa') },
    { label: 'Đổi kiểu phụ đề', icon: 'sub', run: () => inspector.open('subs') },
    { label: 'Đổi giọng đọc', icon: 'mic', run: () => inspector.open('voice') },
    { label: 'Cắt đoạn, thêm chữ và ảnh lên video', icon: 'scissors', run: () => inspector.open('edit') },
    { label: 'Tự cắt khoảng lặng', icon: 'scissors', run: () => { inspector.open('edit'); } },
    { label: 'Gợi ý đoạn hay để cắt clip', icon: 'spark', run: () => { inspector.open('edit'); } },
    { label: 'Kiểm định thành phẩm', icon: 'gauge', run: () => inspector.open('qa') },
    { label: 'Xuất theo nền tảng, tạo gói đăng bài', icon: 'package', run: () => inspector.open('publish') },
    { label: 'Khung hình theo nhân vật', icon: 'target', run: () => inspector.open('picture') },
    { label: 'Mở khung hình này trong trình sửa ảnh', icon: 'image', run: () => { location.hash = `#/image/frame/${enc(id)}/${player.time().toFixed(2)}`; } },
    { label: 'Xử lý sub gốc, khung hình', icon: 'image', run: () => inspector.open('picture') },
    { label: 'Xem video thành phẩm', icon: 'play', run: () => videoModal(`/api/jobs/${enc(id)}/media/final.mp4?t=${player.bust}`, meta().title) },
    { label: 'Mở thư mục video', icon: 'folder', run: () => reveal(id) },
    { label: 'Phím tắt', hint: '?', icon: 'keyboard', run: () => openShortcuts() },
  ];
  return () => {
    queueListeners.delete(onQueue);
    voiceHooks.delete(vh);
    document.removeEventListener('keydown', onKey);
    (st.cleanups || []).forEach((f) => f());
    if (inspector.flush) inspector.flush();
    tl.destroy();
    player.destroy();
    stopAudio();
    if (S.studio === st) S.studio = null;
  };
}

export function openShortcuts() {
  const rows = [
    ['Space', 'Phát / dừng'], ['← →', 'Tua 1 giây (giữ Shift: 5 giây)'], ['↑ ↓', 'Câu trước / câu sau'], ['Enter', 'Sửa câu đang chọn'],
    ['Ctrl+Enter', 'Phát đoạn câu đang sửa'], ['Alt+Enter', 'Nghe giọng lồng của câu đang sửa'], ['Ctrl+↑ ↓', 'Chuyển câu khi đang sửa'],
    ['[ ]', 'Tới điểm chuyển cảnh trước, sau'], ['I / O', 'Đặt điểm đầu, điểm cuối đoạn tại kim phát'], ['Delete', 'Cắt bỏ đoạn đã chọn'], ['Esc', 'Bỏ chọn đoạn'],
    ['Ctrl+S', 'Lưu phụ đề'], ['Ctrl+Z / Ctrl+Y', 'Hoàn tác / làm lại'], ['+ − 0', 'Phóng to, thu nhỏ, vừa khung timeline'],
    ['Ctrl+K', 'Bảng lệnh nhanh'], ['?', 'Xem bảng này'],
  ];
  const m = openModal([
    modalHead('keyboard', 'Phím tắt', () => m),
    el('div', { class: 'modal-body' }, el('dl', { class: 'keys' }, rows.map(([k, v]) => el('div', {}, el('dt', {}, el('span', { class: 'kbd', text: k })), el('dd', { text: v }))))),
  ], { cls: 'modal-sm' });
}
