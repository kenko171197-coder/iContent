/* Cài đặt > Kết nối AI dịch > AI qua MCP: kết nối tới cổng MCP trung tâm của Studio566, mỗi máy một kênh riêng. */
import { api, busy, confirmDialog, copyText, el, icon, toast } from './core.js';

function when(ms) {
  if (!ms) return '';
  return new Date(ms).toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' });
}

function statusLine(st, err) {
  if (err) return el('p', { class: 'small err', text: err });
  if (!st) return null;
  const who = st.ai_seen ? `${st.ai_name || 'AI'} vào lần cuối lúc ${when(st.ai_seen)}` : 'Chưa có AI nào nối vào';
  return el('p', { class: 'small ok' }, icon('check'), ` Đã kết nối · ${who} · ${st.pending} việc đang chờ`);
}

/** Khung chi tiết của lựa chọn "AI qua MCP". */
export function mcpPanel() {
  const box = el('div', { class: 'mcp-panel' }, el('p', { class: 'muted small', text: 'Đang đọc trạng thái…' }));
  const intro = () => el('p', { class: 'dim small', text: 'Dùng Claude, ChatGPT hoặc Grok bạn đang trả phí để dịch, rút gọn câu, phân tích video, viết kịch bản. Không cần API key.' });

  async function paint() {
    let s;
    try { s = await api('GET', '/api/mcp'); } catch (e) { box.replaceChildren(el('p', { class: 'small err', text: e.message })); return; }
    if (!s.server) {
      box.replaceChildren(intro(), el('p', { class: 'small err', text: 'Bản Studio566 này chưa có cổng MCP. Hãy cài bản mới nhất.' }));
      return;
    }
    if (!s.configured) {
      const out = el('span', { class: 'test-out small' });
      const go = el('button', {
        class: 'btn btn-primary', onclick: () => busy(go, async () => {
          try {
            await api('POST', '/api/mcp/connect');
            toast('Đã kết nối AI qua MCP', 'success');
            await paint();
          } catch (e) { out.className = 'test-out small err'; out.textContent = e.message; }
        }),
      }, icon('plug'), 'Kết nối');
      box.replaceChildren(intro(), el('div', { class: 'key-row' }, go), out);
      return;
    }
    const urlInp = el('input', { class: 'input mcp-url', readonly: true, value: s.ai_url, 'aria-label': 'Địa chỉ MCP cho AI', onfocus: (e) => e.target.select() });
    const copy = el('button', { class: 'btn btn-sm btn-primary', onclick: () => copyText(s.ai_url, 'Đã chép địa chỉ MCP') }, icon('copy'), 'Chép địa chỉ');
    const check = el('button', { class: 'btn btn-sm', onclick: () => busy(check, paint) }, icon('refresh'), 'Kiểm tra');
    const rotate = el('button', {
      class: 'btn btn-sm btn-ghost', onclick: async () => {
        const ok = await confirmDialog('Đổi địa chỉ MCP?', 'Địa chỉ cũ sẽ ngừng chạy. Bạn phải dán địa chỉ mới vào lại Claude, ChatGPT, Grok. Nên đổi khi lỡ để lộ địa chỉ.', { okText: 'Đổi địa chỉ', danger: true });
        if (!ok) return;
        await busy(rotate, async () => { await api('POST', '/api/mcp/rotate'); toast('Đã đổi địa chỉ MCP', 'success'); await paint(); });
      },
    }, icon('key'), 'Đổi địa chỉ');
    const off = el('button', {
      class: 'btn btn-sm btn-ghost', onclick: async () => {
        const ok = await confirmDialog('Ngắt kết nối AI qua MCP?', 'Kênh của bạn trên cổng bị xóa, địa chỉ MCP hiện tại ngừng chạy. Kết nối lại sẽ có địa chỉ mới.', { okText: 'Ngắt kết nối', danger: true });
        if (ok) { await api('DELETE', '/api/mcp'); await paint(); }
      },
    }, icon('x'), 'Ngắt kết nối');
    box.replaceChildren(
      el('div', { class: 'mcp-addr' }, el('b', { text: 'Địa chỉ MCP của bạn' }), el('div', { class: 'key-row' }, urlInp, copy, check)),
      el('p', { class: 'dim small', text: 'Địa chỉ này là riêng của máy bạn và có mật khẩu bên trong. Đừng chia sẻ.' }),
      statusLine(s.status, s.error),
      el('div', { class: 'mcp-how' },
        el('b', { text: 'Dán địa chỉ vào AI (làm một lần):' }),
        el('ul', {},
          el('li', {}, el('b', { text: 'Claude: ' }), 'Cài đặt > Connectors > Add custom connector > dán địa chỉ.'),
          el('li', {}, el('b', { text: 'ChatGPT: ' }), 'Settings > Apps & Connectors > Advanced > bật Developer mode > Create > dán địa chỉ, chọn No authentication.'),
          el('li', {}, el('b', { text: 'Grok: ' }), 'grok.com/connectors > New Connector > Custom > dán địa chỉ.')),
        el('p', { class: 'dim small', text: 'Mỗi lần làm video: mở AI đó và nhắn "làm việc đang chờ". Quá thời gian chờ mà chưa AI nào nhận việc, Studio566 tự dịch tiếp bằng dịch offline hoặc Google.' })),
      el('div', { class: 'key-row' }, rotate, off));
  }
  paint();
  return box;
}
