/* Giọng của tôi: thu hoặc tải lên một đoạn giọng của chính mình, VieNeu đọc mọi văn bản bằng giọng đó (Đọc văn bản, Kể chuyện, lồng tiếng). */
import { api, busy, confirmDialog, el, enc, fmtAgo, icon, loadVoices, modalHead, openModal, playUrl, previewVoice, S, stopAudio, toast } from './core.js';

const READ_TEXT = [
  'Xin chào các bạn, mình đang thu mẫu giọng để làm video. Hôm nay trời khá đẹp, mình sẽ kể cho các bạn nghe một câu chuyện nhỏ.',
  'Ngày xưa, ở một làng quê yên bình, có một cậu bé rất chăm chỉ. Mỗi sáng, cậu dậy thật sớm, ra đồng giúp bố mẹ, rồi mới đi học.',
];
const MAX_REC = 40;

async function upload(blob, name, gender) {
  const q = new URLSearchParams({ name, gender });
  let res;
  try { res = await fetch(`/api/myvoices?${q}`, { method: 'POST', body: blob }); } catch (_) { throw new Error('Không kết nối được Studio566'); }
  if (!res.ok) {
    let msg = `Lỗi ${res.status}`;
    try { const j = await res.json(); if (j && j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch (_) { /* không phải JSON */ }
    throw new Error(msg);
  }
  return res.json();
}

/** Mở cửa sổ quản lý giọng. onPick(id): bấm "Dùng giọng này" thì chọn luôn cho trang đang mở. */
export function openMyVoices({ onPick } = {}) {
  const list = el('div', { class: 'mv-list' });
  const nameIn = el('input', { class: 'input', placeholder: 'Tên giọng, ví dụ: Giọng thầy', maxlength: 40 });
  const genderSel = el('select', { class: 'input' }, [['', 'Không nói rõ'], ['male', 'Nam'], ['female', 'Nữ']].map(([k, l]) => el('option', { value: k }, l)));
  const meter = el('i');
  const clock = el('span', { class: 'mono', text: '0:00' });
  const recBox = el('div', { class: 'mv-rec', hidden: true },
    el('div', { class: 'mv-read' }, el('span', { class: 'label', text: 'Đọc to, tự nhiên đoạn này (hoặc nói bất cứ gì, 10 đến 20 giây):' }),
      ...READ_TEXT.map((t) => el('p', { text: t }))),
    el('div', { class: 'mv-meter-row' }, el('span', { class: 'mv-dot' }), clock, el('div', { class: 'mv-meter' }, meter)));
  const take = el('div', { class: 'mv-take', hidden: true });
  let rec = null;
  let starting = false;      // đang chờ trình duyệt mở micro (hỏi quyền): bấm thêm lần nữa không mở micro thứ hai
  let closed = false;

  const recBtn = el('button', { class: 'btn btn-primary', onclick: () => { if (rec) stopRec(); else if (!starting) startRec(); } }, icon('mic'), 'Thu âm');
  const filePick = el('input', { type: 'file', accept: 'audio/*,video/*', hidden: true, onchange: () => { const f = filePick.files[0]; filePick.value = ''; if (f) showTake(f, f.name); } });
  const fileBtn = el('button', { class: 'btn', onclick: () => filePick.click() }, icon('upload'), 'Tải file ghi âm');

  async function startRec() {
    if (!navigator.mediaDevices || !window.MediaRecorder) { toast('Trình duyệt này không thu âm được. Dùng nút "Tải file ghi âm"', 'error'); return; }
    let stream;
    starting = true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
    } catch (e) {
      toast('Không mở được micro: ' + (e.name === 'NotAllowedError' ? 'chưa cho phép dùng micro (bấm biểu tượng ổ khóa trên thanh địa chỉ để cho phép)' : e.message), 'error');
      return;
    } finally {
      starting = false;
    }
    if (closed) { stream.getTracks().forEach((t) => t.stop()); return; }      // cửa sổ đã đóng trong lúc hỏi quyền: tắt micro ngay
    stopAudio();
    const type = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm'].find((t) => MediaRecorder.isTypeSupported(t)) || '';
    const mr = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const parts = [];
    const ctx = new AudioContext();
    const an = ctx.createAnalyser();
    an.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Float32Array(an.fftSize);
    const t0 = performance.now();
    rec = { mr, stream, ctx, raf: 0 };
    const tick = () => {
      an.getFloatTimeDomainData(buf);
      let s = 0;
      for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
      const db = 20 * Math.log10(Math.sqrt(s / buf.length) + 1e-6);
      meter.style.width = `${Math.max(0, Math.min(100, (db + 60) * 1.8))}%`;
      meter.classList.toggle('hot', db > -6);
      const sec = (performance.now() - t0) / 1000;
      clock.textContent = `0:${String(Math.floor(sec)).padStart(2, '0')}`;
      if (sec >= MAX_REC) { stopRec(); return; }
      rec.raf = requestAnimationFrame(tick);
    };
    mr.ondataavailable = (e) => { if (e.data.size) parts.push(e.data); };
    mr.onstop = () => {
      const blob = new Blob(parts, { type: mr.mimeType || 'audio/webm' });
      const sec = (performance.now() - t0) / 1000;
      if (sec < 4) toast('Thu hơi ngắn: nên đọc 10 đến 20 giây', 'warn');
      showTake(blob, 'Bản vừa thu');
    };
    mr.start(250);
    take.hidden = true;
    recBox.hidden = false;
    recBtn.replaceChildren(icon('stop'), 'Dừng thu');
    recBtn.classList.replace('btn-primary', 'btn-danger');
    tick();
  }

  function stopRec() {
    if (!rec) return;
    cancelAnimationFrame(rec.raf);
    try { rec.mr.stop(); } catch (_) { /* đã dừng */ }
    rec.stream.getTracks().forEach((t) => t.stop());
    rec.ctx.close();
    rec = null;
    recBox.hidden = true;
    recBtn.replaceChildren(icon('mic'), 'Thu lại');
    recBtn.classList.replace('btn-danger', 'btn-primary');
  }

  function showTake(blob, label) {
    const url = URL.createObjectURL(blob);
    const save = el('button', {
      class: 'btn btn-primary', onclick: () => busy(save, async () => {
        const v = await upload(blob, nameIn.value.trim(), genderSel.value);
        (v.warnings || []).forEach((w) => toast(w, 'warn', { timeout: 9000 }));
        toast(`Đã lưu "${v.name}": dùng ${v.dur.toFixed(1)} giây rõ nhất làm mẫu`, 'success');
        URL.revokeObjectURL(url);
        take.hidden = true;
        nameIn.value = '';
        await loadVoices();
        paint(v.id);
      }),
    }, icon('save'), 'Lưu giọng này');
    take.replaceChildren(el('span', { class: 'small dim', text: label }), el('audio', { src: url, controls: true }), save);
    take.hidden = false;
  }

  function paint(fresh = '') {
    const items = S.voices.mine || [];
    if (!items.length) {
      list.replaceChildren(el('p', { class: 'dim small', text: 'Chưa có giọng nào. Thu một đoạn ở bên dưới.' }));
      return;
    }
    list.replaceChildren(...items.map((v) => {
      const nm = el('input', {
        class: 'input input-sm', value: v.name, maxlength: 40, 'aria-label': 'Tên giọng',
        onchange: () => busy(null, async () => { await api('PUT', `/api/myvoices/${enc(v.id)}`, { name: nm.value }); await loadVoices(); }),
      });
      const sample = el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Nghe mẫu đã thu', 'aria-label': 'Nghe mẫu đã thu', onclick: () => playUrl(`/api/myvoices/${enc(v.id)}/sample?t=${v.created}`, sample) }, icon('volume'));
      const hear = el('button', { class: 'btn btn-xs', title: 'VieNeu đọc một câu bằng giọng này', onclick: () => previewVoice('vieneu', v.id, hear) }, icon('play'), 'Nghe đọc thử');
      const del = el('button', {
        class: 'btn btn-xs btn-icon btn-ghost', title: 'Xóa giọng', 'aria-label': 'Xóa giọng', onclick: () => busy(del, async () => {
          if (!await confirmDialog('Xóa giọng này?', `"${v.name}" sẽ bị xóa khỏi máy. Câu chuyện, văn bản đang chọn giọng này sẽ phải chọn giọng khác.`, { okText: 'Xóa', danger: true })) return;
          await api('DELETE', `/api/myvoices/${enc(v.id)}`);
          await loadVoices();
          paint();
        }),
      }, icon('trash'));
      const pick = onPick ? el('button', { class: 'btn btn-xs', onclick: () => { onPick(v.id); m.close(); } }, icon('check'), 'Dùng giọng này') : null;
      const meta = [v.gender === 'male' ? 'Nam' : v.gender === 'female' ? 'Nữ' : '', v.dur ? `mẫu ${Number(v.dur).toFixed(1)} giây` : '', v.created ? fmtAgo(v.created) : ''].filter(Boolean).join(' · ');
      return el('div', { class: 'mv-item' + (v.id === fresh ? ' fresh' : '') },
        el('div', { class: 'mv-item-t' }, nm, el('span', { class: 'dim small', text: meta })),
        el('div', { class: 'mv-acts' }, sample, hear, pick, del));
    }));
  }

  const m = openModal([
    modalHead('mic', 'Giọng của tôi', () => m),
    el('div', { class: 'modal-body mv-body' },
      el('p', { class: 'small dim', text: 'Thu 10 đến 20 giây giọng của bạn ở chỗ yên tĩnh. VieNeu lấy 8 giây rõ nhất làm mẫu rồi đọc mọi văn bản bằng giọng đó, chạy hẳn trên máy. '
        + 'Giọng này có trong ô chọn giọng của Đọc văn bản, Kể chuyện và lồng tiếng (bộ giọng VieNeu).' }),
      el('p', { class: 'small mv-note', text: 'Chỉ dùng giọng của chính bạn, hoặc của người đã đồng ý cho bạn dùng.' }),
      list,
      el('h4', { text: 'Thêm giọng' }),
      el('div', { class: 'mv-form' }, el('label', { class: 'field' }, el('span', { class: 'label', text: 'Tên' }), nameIn),
        el('label', { class: 'field' }, el('span', { class: 'label', text: 'Giọng' }), genderSel)),
      el('div', { class: 'btn-row' }, recBtn, fileBtn, filePick),
      recBox, take),
  ], { cls: 'modal-md', onClose: () => { closed = true; stopRec(); } });
  paint();
  loadVoices().then(() => { if (m.box.isConnected) paint(); });
  return m;
}

/** Nút nhỏ cạnh ô chọn giọng. getEngine(): bộ giọng đang chọn; onPick(id): chọn giọng vừa bấm. */
export function myVoiceButton(getEngine, onPick) {
  return el('button', {
    class: 'btn btn-xs btn-icon', title: 'Giọng của tôi: thu giọng của chính bạn', 'aria-label': 'Giọng của tôi',
    onclick: () => openMyVoices({ onPick: (id) => { if (getEngine() === 'edge') toast('Giọng của tôi đọc bằng VieNeu (tiếng Việt) hoặc bộ đọc nhiều thứ tiếng, không đọc bằng Microsoft', 'info'); onPick(id); } }),
  }, icon('mic'));
}
