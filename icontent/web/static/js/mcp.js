/* Cài đặt > Kết nối AI dịch > AI qua MCP: cổng MCP của Studio566 trên Cloudflare Workers (tài khoản của người dùng). */
import { api, busy, confirmDialog, copyText, el, icon, toast } from './core.js';

const TOKEN_PAGE = 'https://dash.cloudflare.com/profile/api-tokens';
const SIGNUP = 'https://dash.cloudflare.com/sign-up';

function when(ms) {
  if (!ms) return '';
  const d = new Date(ms);
  return d.toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' });
}

function statusLine(st, err) {
  if (err) return el('p', { class: 'small err', text: 'Không gọi được cổng: ' + err });
  if (!st) return null;
  const who = st.ai_seen ? `${st.ai_name || 'AI'} vào lần cuối lúc ${when(st.ai_seen)}` : 'Chưa có AI nào nối vào cổng';
  return el('p', { class: 'small ok' }, icon('check'), ` Cổng đang chạy · ${who} · ${st.pending} việc đang chờ`);
}

function step(n, ...kids) {
  return el('div', { class: 'mcp-step' }, el('span', { class: 'mcp-n', text: String(n) }), el('div', { class: 'mcp-step-body' }, ...kids));
}

function setupForm(onDone, retoken = false) {
  const inp = el('input', { class: 'input', type: 'password', autocomplete: 'off', spellcheck: 'false', placeholder: 'Dán API token Cloudflare vào đây', 'aria-label': 'API token Cloudflare' });
  const out = el('span', { class: 'test-out small' });
  const go = el('button', {
    class: 'btn btn-sm btn-primary', onclick: () => busy(go, async () => {
      out.className = 'test-out small muted';
      out.textContent = 'Đang tải cổng lên Cloudflare, mất khoảng 10 đến 40 giây…';
      try {
        const r = await api('POST', '/api/mcp/deploy', { token: inp.value.trim() });
        inp.value = '';
        toast('Đã cài cổng MCP lên Cloudflare', 'success');
        onDone(r);
      } catch (e) {
        out.className = 'test-out small err';
        out.textContent = e.message;
      }
    }),
  }, icon('upload'), retoken ? 'Cài lại' : 'Cài cổng MCP');
  return el('div', { class: 'mcp-setup' },
    retoken ? null : step(1, el('b', { text: 'Tạo tài khoản Cloudflare miễn phí' }), ' (bỏ qua nếu đã có): ',
      el('a', { href: SIGNUP, target: '_blank', rel: 'noreferrer', text: 'dash.cloudflare.com/sign-up' })),
    step(retoken ? 1 : 2, el('b', { text: 'Tạo API token: ' }),
      el('a', { href: TOKEN_PAGE, target: '_blank', rel: 'noreferrer', text: 'mở trang API Tokens' }),
      ' → Create Token → dòng ', el('b', { text: 'Edit Cloudflare Workers' }), ' bấm Use template → Continue to summary → Create Token → chép token.'),
    step(retoken ? 2 : 3, el('b', { text: 'Dán token và bấm cài.' }), ' Studio566 tự dựng cổng trên tài khoản của bạn, ở địa chỉ mặc định dạng ',
      el('code', { text: 'studio566-mcp.<tên>.workers.dev' }), '. Gói miễn phí là đủ.',
      el('div', { class: 'key-row' }, inp, go), out));
}

/** Khung chi tiết của lựa chọn "AI qua MCP". */
export function mcpPanel() {
  const box = el('div', { class: 'mcp-panel' }, el('p', { class: 'muted small', text: 'Đang đọc trạng thái cổng MCP…' }));

  async function paint() {
    let s;
    try { s = await api('GET', '/api/mcp'); } catch (e) { box.replaceChildren(el('p', { class: 'small err', text: e.message })); return; }
    if (!s.configured) {
      box.replaceChildren(
        el('p', { class: 'dim small', text: 'Dùng Claude, ChatGPT hoặc Grok bạn đang trả phí để dịch, không cần API key. Cổng MCP đặt trên Cloudflare (tài khoản của bạn, miễn phí), máy bạn không phải mở cổng nào ra Internet.' }),
        setupForm(() => paint()));
      return;
    }
    const urlInp = el('input', { class: 'input mcp-url', readonly: true, value: s.ai_url, 'aria-label': 'Địa chỉ MCP cho AI', onfocus: (e) => e.target.select() });
    const copy = el('button', { class: 'btn btn-sm btn-primary', onclick: () => copyText(s.ai_url, 'Đã chép địa chỉ MCP') }, icon('copy'), 'Chép địa chỉ');
    const check = el('button', { class: 'btn btn-sm', onclick: () => busy(check, paint) }, icon('refresh'), 'Kiểm tra');
    const rotate = el('button', {
      class: 'btn btn-sm btn-ghost', onclick: async () => {
        if (!s.has_token) { toast('Cần dán lại API token Cloudflare ở mục Cài lại bên dưới', 'info'); return; }
        const ok = await confirmDialog('Đổi địa chỉ MCP?', 'Địa chỉ cũ sẽ ngừng chạy. Bạn phải dán địa chỉ mới vào lại Claude, ChatGPT, Grok. Nên đổi khi lỡ để lộ địa chỉ.', { okText: 'Đổi địa chỉ', danger: true });
        if (!ok) return;
        await busy(rotate, async () => { await api('POST', '/api/mcp/deploy', { rotate: true }); toast('Đã đổi địa chỉ MCP', 'success'); await paint(); });
      },
    }, icon('key'), 'Đổi địa chỉ');
    const update = el('button', {
      class: 'btn btn-sm btn-ghost', onclick: () => busy(update, async () => {
        if (!s.has_token) { toast('Cần dán lại API token Cloudflare ở mục Cài lại bên dưới', 'info'); return; }
        await api('POST', '/api/mcp/deploy', {});
        toast('Đã cập nhật cổng lên bản mới nhất', 'success');
        await paint();
      }),
    }, icon('upload'), 'Cập nhật cổng');
    const forget = el('button', {
      class: 'btn btn-sm btn-ghost', onclick: async () => {
        const ok = await confirmDialog('Gỡ cổng MCP khỏi Studio566?', 'Studio566 quên địa chỉ và mật khẩu. Worker trên Cloudflare vẫn còn, muốn xóa hẳn thì vào Cloudflare > Workers.', { okText: 'Gỡ', danger: true });
        if (ok) { await api('DELETE', '/api/mcp'); await paint(); }
      },
    }, icon('trash'), 'Gỡ');
    const retoken = el('details', { class: 'mcp-more' }, el('summary', { text: 'Cài lại bằng API token khác' }), setupForm(() => paint(), true));
    box.replaceChildren(
      el('div', { class: 'mcp-addr' }, el('b', { text: 'Địa chỉ MCP cho AI' }),
        el('div', { class: 'key-row' }, urlInp, copy, check)),
      el('p', { class: 'dim small', text: 'Địa chỉ này có sẵn mật khẩu bên trong: ai có địa chỉ là gửi được việc vào. Đừng chia sẻ.' }),
      statusLine(s.status, s.error),
      el('div', { class: 'mcp-how' },
        el('b', { text: 'Nối AI vào cổng (làm một lần):' }),
        el('ul', {},
          el('li', {}, el('b', { text: 'Claude: ' }), 'Cài đặt > Connectors > Add custom connector > dán địa chỉ.'),
          el('li', {}, el('b', { text: 'ChatGPT: ' }), 'Settings > Apps & Connectors > Advanced > bật Developer mode > Create > dán địa chỉ, chọn No authentication.'),
          el('li', {}, el('b', { text: 'Grok: ' }), 'grok.com/connectors > New Connector > Custom > dán địa chỉ.')),
        el('p', { class: 'dim small', text: 'Mỗi lần làm video: mở AI đó và nhắn "làm việc đang chờ". Quá thời gian chờ mà chưa AI nào nhận việc, Studio566 tự dịch tiếp bằng dịch offline hoặc Google.' })),
      el('div', { class: 'key-row' }, rotate, update, forget),
      retoken);
  }
  paint();
  return box;
}
