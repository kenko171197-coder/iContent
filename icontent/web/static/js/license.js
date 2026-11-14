/* Bản quyền: màn Kích hoạt (khi bản phát hành chưa có key hợp lệ) và mục Bản quyền trong Cài đặt. Key do bot Telegram @Kichhoatkey_bot cấp. */
import { S, api, busy, copyText, el, icon, toast } from './core.js';

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString('vi-VN') : '');

function keyBox(onDone) {
  const inp = el('textarea', { class: 'input lic-key', rows: 3, spellcheck: 'false', placeholder: 'Dán key bot gửi vào đây (một dòng rất dài, có dấu chấm ở giữa)', 'aria-label': 'Key bản quyền' });
  const out = el('div', { class: 'ob-out', hidden: true });
  const paste = el('button', {
    class: 'btn', onclick: async () => {
      try { inp.value = (await navigator.clipboard.readText()).trim(); } catch (_) { inp.focus(); toast('Bấm vào ô rồi nhấn Ctrl+V để dán', 'info'); }
    },
  }, icon('paste'), 'Dán');
  const go = el('button', {
    class: 'btn btn-primary', onclick: () => busy(go, async () => {
      out.hidden = false;
      try {
        const r = await api('POST', '/api/license', { key: inp.value });
        out.className = 'ob-out ok';
        out.replaceChildren(icon('check'), el('span', { text: r.detail + (r.customer ? ` Chào ${r.customer}!` : '') }));
        S.license = r;
        onDone(r);
      } catch (e) {
        out.className = 'ob-out err';
        out.replaceChildren(icon('alert'), el('span', { text: e.message }));
      }
    }),
  }, icon('key'), 'Kích hoạt');
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go.click(); } });
  return { root: el('div', { class: 'lic-keybox' }, inp, el('div', { class: 'lic-keyrow' }, paste, go), out), inp };
}

function machineBox(st) {
  return el('div', { class: 'lic-machine' },
    el('span', { class: 'small dim', text: 'MÃ MÁY' }),
    el('code', { class: 'lic-fp', text: st.machine }),
    el('button', { class: 'btn btn-sm', onclick: () => copyText(st.machine, 'Đã chép mã máy') }, icon('copy'), 'Sao chép'));
}

/** Màn Kích hoạt phủ toàn bộ cửa sổ. Gọi lại khi đang hiện thì chỉ cập nhật lời nhắn. */
export function showLicenseGate(st) {
  const old = document.querySelector('.lic-gate');
  if (old) { const m = old.querySelector('.lic-why'); if (m && st.reason !== 'no_license') { m.hidden = false; m.lastChild.textContent = st.message; } return; }
  const kb = keyBox(() => { setTimeout(() => location.reload(), 1200); });
  const why = el('div', { class: 'ob-out err lic-why', hidden: st.reason === 'no_license' }, icon('alert'), el('span', { text: st.message }));
  const tg = el('a', { class: 'btn btn-primary', href: st.telegram, target: '_blank', rel: 'noreferrer' }, icon('send'), 'Nhận key qua Telegram');
  const gate = el('div', { class: 'lic-gate', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Kích hoạt Studio566' },
    el('div', { class: 'lic-card' },
      el('div', { class: 'lic-head' }, el('img', { src: '/static/icon.png', alt: '', class: 'lic-logo' }),
        el('div', {}, el('h1', { text: st.reason === 'expired' ? 'Gia hạn Studio566' : 'Kích hoạt Studio566' }),
          el('p', { class: 'dim', text: 'Mỗi máy cần một key. Key do bot Telegram cấp, thường chỉ mất một phút.' }))),
      why,
      machineBox(st),
      el('ol', { class: 'ob-steps lic-steps' },
        el('li', {}, 'Bấm ', el('b', { text: 'Nhận key qua Telegram' }), `: mở bot @${st.bot} với mã máy có sẵn. `, tg,
          el('div', { class: 'small dim', text: `Máy này không có Telegram? Trên điện thoại, nhắn mã máy ở trên cho @${st.bot} rồi chọn Studio566.` })),
        el('li', {}, 'Trong bot bấm ', el('b', { text: 'Yêu cầu kích hoạt' }), '. Được duyệt, bot gửi key cho bạn.'),
        el('li', {}, 'Chép nguyên key, dán vào ô dưới, bấm ', el('b', { text: 'Kích hoạt' }), '.')),
      kb.root,
      el('p', { class: 'small dim', text: 'Key gắn với máy này. Cài lại hay cập nhật bản mới trên cùng máy không phải xin key lại.' })));
  document.body.append(gate);
  setTimeout(() => kb.inp.focus(), 80);
}

/** Mục Bản quyền trong Cài đặt: còn hạn bao lâu, nhập key mới khi gia hạn. Bản chạy từ mã nguồn (không khoá) thì không hiện. */
export function licensePanel(st) {
  if (!st || !st.enforced) return null;
  const kb = keyBox((r) => { paint(r); kb.inp.value = ''; });
  const info = el('div', { class: 'lic-info' });
  function paint(s) {
    const left = s.days_left;
    info.replaceChildren(
      el('div', { class: 'lic-status ' + (s.licensed ? (left != null && left <= 14 ? 'warn' : 'ok') : 'bad') },
        icon(s.licensed ? 'check' : 'alert'),
        el('b', { text: s.licensed ? (s.lifetime ? 'Đã kích hoạt, dùng trọn đời' : `Đã kích hoạt, còn ${left} ngày (hết hạn ${fmtDate(s.expires)})`) : s.message })),
      s.customer ? el('div', { class: 'small dim', text: `Khách: ${s.customer}` }) : '',
      machineBox(s),
      el('a', { class: 'btn btn-sm', href: s.telegram, target: '_blank', rel: 'noreferrer' }, icon('send'), s.licensed ? 'Gia hạn qua Telegram' : 'Nhận key qua Telegram'));
  }
  paint(st);
  return el('div', { class: 'lic-panel' }, info, el('div', { class: 'small dim', text: 'Nhập key mới (gia hạn, đổi máy):' }), kb.root);
}

/** Dòng nhắc gia hạn ở Trang chủ khi còn ít ngày. */
export function renewBanner(st) {
  if (!st || !st.enforced || !st.licensed || st.days_left == null || st.days_left > 14) return null;
  return el('div', { class: 'lic-banner' }, icon('clock'),
    el('span', { class: 'lic-banner-t' }, el('b', { text: `Bản quyền Studio566 còn ${st.days_left} ngày` }), ` (hết hạn ${fmtDate(st.expires)}). Gia hạn sớm để không bị gián đoạn.`),
    el('a', { class: 'btn btn-sm btn-primary', href: st.telegram, target: '_blank', rel: 'noreferrer' }, icon('send'), 'Gia hạn qua Telegram'),
    el('a', { class: 'btn btn-sm btn-ghost', href: '#/settings' }, 'Nhập key mới'));
}
