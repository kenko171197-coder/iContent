/* Giữ kết nối với máy chủ iContent chạy trên máy.
   - Hỏi thăm từ luồng nền (keepalive.js) để máy chủ biết cửa sổ còn mở, kể cả khi thu nhỏ lâu.
   - Đóng/tải lại trang thì báo máy chủ (pagehide): đóng thật thì máy chủ tắt sớm, không phải đoán.
   - Mất kết nối: băng báo ở trên cùng, tự nối lại mỗi 2 giây. Máy chủ vừa chạy lại (appwin.supervise) thì báo, không tải lại trang. */
import { connHooks, el, icon, toast } from './core.js';

let boot = null;
let down = false;
let since = 0;
let timer = null;
let worker = null;
let onBack = null;
const title = el('b', { class: 'conn-t' });
const sub = el('div', { class: 'conn-sub' });
const retryBtn = el('button', { class: 'btn btn-sm', onclick: () => check() }, icon('refresh'), 'Thử lại ngay');
const bar = el('div', { class: 'conn-bar', role: 'alert', hidden: true },
  el('span', { class: 'spinner' }), el('div', { class: 'conn-text' }, title, sub), retryBtn);

function paint() {
  bar.hidden = !down;
  if (!down) return;
  const long = Date.now() - since > 12000;
  title.textContent = long ? 'iContent đã dừng, đang chờ chạy lại…' : 'Mất kết nối với iContent, đang kết nối lại…';
  sub.textContent = long
    ? 'Thường iContent tự chạy lại sau vài giây và cửa sổ này tự nối lại. Quá 1 phút vẫn vậy: đóng cửa sổ này rồi mở iContent Studio bằng biểu tượng trên màn hình nền; vẫn không được thì mở Sửa lỗi iContent trong menu Start.'
    : 'Cửa sổ sẽ tự nối lại khi iContent trả lời.';
}

function lost() {
  if (!down) { down = true; since = Date.now(); }
  paint();
  clearTimeout(timer);
  timer = setTimeout(check, 2000);
}

function back(b) {
  const restarted = !!(boot && b && b !== boot);
  if (b) boot = b;
  if (!down && !restarted) return;
  down = false;
  clearTimeout(timer);
  paint();
  // Không tải lại trang: thiết kế thumbnail, chữ đang gõ... chưa lưu sẽ mất (đã gặp khi thử thật). Trang đang báo lỗi thì vẽ lại.
  if (restarted) toast('iContent vừa khởi động lại. Việc đang chạy dở (nếu có) cần bấm chạy lại.', 'info', { timeout: 9000 });
  else toast('Đã kết nối lại iContent', 'success');
  if (onBack) onBack();
}

export async function check() {
  try {
    const r = await fetch('/api/ui/ping', { cache: 'no-store' });
    const j = await r.json();
    back(j.boot || null);
  } catch (_) {
    lost();
  }
}

/** Bật ở đầu boot() (cả màn Kích hoạt: khách sang Telegram xin key vài phút, máy chủ phải biết cửa sổ còn mở).
 *  reconnected(): gọi khi nối lại được mà máy chủ không chạy lại (ví dụ vẽ lại trang đang báo lỗi). */
export function startConn(reconnected) {
  onBack = reconnected;
  document.body.append(bar);
  connHooks.add(lost);
  try {
    worker = new Worker('/static/js/keepalive.js');
    worker.onmessage = (e) => { if (e.data && e.data.ok) back(e.data.boot); else lost(); };
  } catch (_) {
    setInterval(check, 15000);      // không tạo được luồng nền: hỏi thăm từ trang
  }
  // đóng cửa sổ hoặc tải lại trang: báo máy chủ. Trang mới (tải lại) hỏi thăm ngay sau đó nên máy chủ không tắt nhầm
  window.addEventListener('pagehide', () => { try { navigator.sendBeacon('/api/ui/bye'); } catch (_) { /* không gửi được: máy chủ tự đợi lâu hơn */ } });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && worker) worker.postMessage('ping'); });
}
