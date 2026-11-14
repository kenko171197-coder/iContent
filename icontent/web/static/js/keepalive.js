/* Luồng nền hỏi thăm máy chủ Studio566: "cửa sổ còn mở". Trình duyệt hãm bộ hẹn giờ của trang bị thu nhỏ (một lần mỗi phút,
   có khi ngừng hẳn), luồng nền thì không bị hãm như vậy. Kết quả gửi về trang (conn.js): {ok, boot} hoặc {ok: false}. */
async function ping() {
  try {
    const r = await fetch('/api/ui/ping', { cache: 'no-store' });
    const j = await r.json();
    postMessage({ ok: true, boot: j.boot || null });
  } catch (_) {
    postMessage({ ok: false });
  }
}
ping();
setInterval(ping, 15000);
onmessage = (e) => { if (e.data === 'ping') ping(); };
