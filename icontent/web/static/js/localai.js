/* Mô-đun AI miễn phí chạy trên máy (localai.py): Dịch offline, Vẽ ảnh offline.
   Một thẻ cho mỗi gói: tải (tiếp tục được khi rớt mạng), dừng, chạy thử, xóa. Dùng ở Cài đặt, khung Cách khắc phục và Trang chủ. */
import { api, busy, confirmDialog, el, icon, loadStatus, modalHead, openModal, put, toast } from './core.js';

const num = (n) => Math.round(n).toLocaleString('vi-VN');
export const gbText = (mb) => (mb >= 1000 ? (mb / 1000).toFixed(1).replace('.', ',') + ' GB' : num(mb) + ' MB');
function etaText(s) {
  if (s == null) return '';
  if (s < 60) return 'còn chưa tới 1 phút';
  if (s < 3600) return `còn khoảng ${Math.round(s / 60)} phút`;
  return `còn khoảng ${Math.floor(s / 3600)} giờ ${Math.round((s % 3600) / 60)} phút`;
}

function deviceNote(pack, devs) {
  if (pack.id !== 'image' && pack.id !== 'voices') return null;
  const what = pack.id === 'image' ? 'vẽ' : 'đọc';
  if (devs == null) return pack.ready ? null : el('p', { class: 'dim small', text: `Tải xong, Studio566 tự ${what} thử để biết máy này ${what} nhanh hay chậm.` });
  if (!devs.length) return el('p', { class: 'small prov-warn-msg', text: `Không thấy card đồ họa nào dùng được: sẽ ${what} bằng CPU, chậm hơn nhiều. Cập nhật driver card đồ họa nếu máy có card rời.` });
  const best = devs.slice().sort((a, b) => b.vram_mb - a.vram_mb)[0];
  const gb = (best.vram_mb / 1024).toFixed(0);
  return el('p', { class: 'dim small', text: `Card đồ họa: ${best.name} (${gb} GB).` + (best.vram_mb < 3500 ? ' Card dưới 4 GB: vẽ được nhưng chậm.' : '') });
}

/** Thẻ một gói. pack: một mục trong /api/ai/packs. refresh(): hỏi lại máy chủ. */
function packCard(pack, ctx) {
  const t = pack.task;
  const running = t && t.running;
  const head = el('div', { class: 'aip-head' }, el('span', { class: 'aip-ico' }, icon(pack.icon || 'cpu')),
    el('div', { class: 'aip-title' }, el('b', { text: pack.name }), el('span', { class: 'dim small', text: gbText(pack.total_mb) })),
    pack.ready ? el('span', { class: 'prov-ok' }, icon('check'), 'Đã sẵn sàng') : running ? el('span', { class: 'pill', text: 'Đang tải' }) : null);
  const kids = [head, el('p', { class: 'small', text: pack.desc })];

  if (running) {
    const pct = t.progress == null ? null : Math.round(t.progress * 100);
    const stop = el('button', { class: 'btn btn-xs', onclick: () => busy(stop, async () => { await api('POST', `/api/ai/packs/${pack.id}/cancel`); ctx.refresh(); }) }, icon('x'), 'Dừng');
    const line = t.step === 'download' && t.total_mb
      ? `${num(t.done_mb)} / ${num(t.total_mb)} MB` + (t.speed ? ` · ${String(t.speed).replace('.', ',')} MB/giây` : '') + (t.eta != null ? ` · ${etaText(t.eta)}` : '')
      : '';
    kids.push(el('div', { class: 'off-line' }, el('span', { class: 'grow small', text: t.message || 'Đang tải' }), stop),
      el('div', { class: 'off-bar' + (pct == null ? ' busy' : ''), role: 'progressbar', 'aria-valuenow': pct == null ? null : pct }, el('i', { style: pct == null ? {} : { width: pct + '%' } })),
      line ? el('p', { class: 'dim small mono', text: line }) : null,
      el('p', { class: 'dim small', text: 'Có thể đóng trang này, làm việc khác: Studio566 vẫn tải tiếp. Rớt mạng thì bấm Tải tiếp, không phải tải lại từ đầu.' }));
    return el('div', { class: 'aip-card running' }, kids);
  }

  if (pack.ready) {
    const out = el('div', { class: 'aip-test' });
    if (t && t.done && t.message && t.message !== 'Đã tải xong') out.append(el('p', { class: 'small ok-text', text: t.message }));
    if (pack.id === 'image' && t && t.done) out.append(el('img', { class: 'aip-img', src: `/api/ai/test-image?t=${Date.now()}`, alt: 'Ảnh vẽ thử' }));
    if (pack.id === 'voices' && t && t.done) out.append(el('audio', { class: 'aip-audio', controls: true, src: `/api/ai/test-audio?t=${Date.now()}` }));
    const testBtn = el('button', {
      class: 'btn btn-sm', onclick: () => busy(testBtn, async () => {
        put(out, el('p', { class: 'dim small', text: { image: 'Đang vẽ thử một ảnh nhỏ (lần đầu lâu hơn vì phải nạp mô hình)…', voices: 'Đang đọc thử một câu (lần đầu lâu hơn vì phải nạp mô hình)…' }[pack.id] || 'Đang dịch thử…' }));
        try {
          const r = await api('POST', `/api/ai/packs/${pack.id}/test`);
          put(out, el('p', { class: 'small ok-text', text: r.message }), r.image ? el('img', { class: 'aip-img', src: r.image, alt: 'Ảnh vẽ thử' }) : null,
            r.audio ? el('audio', { class: 'aip-audio', controls: true, autoplay: true, src: r.audio }) : null);
        } catch (e) { put(out, el('p', { class: 'test-out small err', text: e.message })); }
      }),
    }, icon(pack.id === 'image' ? 'image' : 'play'), { image: 'Vẽ thử', voices: 'Nghe thử' }[pack.id] || 'Dịch thử');
    const del = el('button', {
      class: 'btn btn-sm btn-ghost', onclick: () => busy(del, async () => {
        const ok = await confirmDialog(`Xóa ${pack.name}?`, `Giải phóng khoảng ${gbText(pack.total_mb)} ổ đĩa. Cần dùng lại thì bấm Tải lần nữa.`, { okText: 'Xóa', danger: true });
        if (!ok) return;
        await api('DELETE', `/api/ai/packs/${pack.id}`);
        toast(`Đã xóa ${pack.name}`, 'success');
        ctx.refresh();
        loadStatus();
      }),
    }, icon('trash'), 'Xóa');
    kids.push(el('div', { class: 'off-line' }, testBtn, el('span', { class: 'grow' }), del), out, el('p', { class: 'dim small', text: pack.limits }), deviceNote(pack, ctx.devices));
    return el('div', { class: 'aip-card ready' }, kids);
  }

  const paused = t && !t.error && !t.done && t.message;
  const partial = pack.files.some((f) => f.ok) || paused;
  const need = pack.need_mb;
  const lowDisk = ctx.free_mb && ctx.free_mb < need * 1.05 + 500;
  const go = el('button', {
    class: 'btn btn-sm btn-primary', disabled: lowDisk ? true : null, onclick: () => busy(go, async () => {
      await api('POST', `/api/ai/packs/${pack.id}/download`);
      ctx.refresh();
    }),
  }, icon('download'), t && t.error ? 'Tải tiếp' : partial ? 'Tải tiếp' : `Tải về (${gbText(need)})`);
  if (t && t.error) kids.push(el('p', { class: 'test-out small err', text: t.error }));
  else if (paused) kids.push(el('p', { class: 'dim small', text: t.message }));
  kids.push(el('div', { class: 'off-line' }, go,
    el('span', { class: 'dim small', text: lowDisk ? `Ổ đĩa chỉ còn trống ${gbText(ctx.free_mb)}, cần khoảng ${gbText(need)}.` : `Ổ đĩa còn trống ${gbText(ctx.free_mb)}. Chỉ tải một lần.` })),
  pack.reuse_ollama ? el('p', { class: 'small ok-text', text: 'Máy đã có mô hình dịch từ Ollama: Studio566 dùng lại, không phải tải lại phần đó.' }) : null,
  el('p', { class: 'dim small', text: pack.limits }), deviceNote(pack, ctx.devices));
  return el('div', { class: 'aip-card' }, kids);
}

/** Khung chứa các thẻ gói, tự hỏi lại khi đang tải. only: chỉ hiện một gói. */
export function aiPacks({ only = '', onReady } = {}) {
  const box = el('div', { class: 'aip-list' }, el('p', { class: 'dim small', text: 'Đang kiểm tra…' }));
  let timer = 0;
  let wasReady = null;
  const ctx = {
    devices: null, free_mb: 0,
    refresh: async () => {
      clearTimeout(timer);
      let d;
      try { d = await api('GET', '/api/ai/packs'); } catch (e) { put(box, el('p', { class: 'test-out small err', text: e.message })); return; }
      ctx.devices = d.devices;
      ctx.free_mb = d.free_mb;
      const packs = d.packs.filter((p) => !only || p.id === only);
      put(box, ...packs.map((p) => packCard(p, ctx)));
      const ready = packs.every((p) => p.ready);
      if (wasReady === false && ready && onReady) onReady();
      wasReady = ready;
      if (packs.some((p) => p.task && p.task.running) && (box.isConnected || !wasReady)) timer = setTimeout(ctx.refresh, 1000);
      else if (packs.some((p) => p.task && p.task.done)) loadStatus();
    },
  };
  ctx.refresh();
  if (!only || only === 'image' || only === 'voices') api('GET', '/api/ai/devices').then((r) => { if (r.devices != null && ctx.devices == null) { ctx.devices = r.devices; ctx.refresh(); } }).catch(() => {});
  return box;
}

/** Hộp thoại tải một gói (nút trong khung Cách khắc phục, Trang chủ). */
export function openAiPack(pid, { onReady } = {}) {
  let m;
  m = openModal([
    modalHead({ image: 'image', voices: 'mic' }[pid] || 'globe', 'Mô-đun AI miễn phí', () => m),
    el('div', { class: 'modal-body' }, aiPacks({ only: pid, onReady })),
  ], { cls: 'aip-modal' });
  return m;
}

/** Sang Cài đặt và cuộn tới khung Mô-đun AI miễn phí. */
export function goAiSettings() {
  try { sessionStorage.setItem('ic.settings.focus', 'mo-dun-ai'); } catch (_) { /* không lưu được: vẫn sang trang */ }
  location.hash = '#/settings';
}
