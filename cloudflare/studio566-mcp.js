// Cổng MCP trung tâm của Studio566, chạy trên Cloudflare Workers của chủ app. Mọi người dùng Studio566 kết nối qua đây.
//
// Mỗi máy cài Studio566 tự đăng ký một KÊNH riêng (hàng chờ riêng, mật khẩu riêng, không cần tài khoản).
// Studio566 gửi việc chữ (dịch, rút gọn, phân tích, viết kịch bản...) vào kênh; Claude, ChatGPT hay Grok của người dùng
// nối vào link MCP của kênh, lấy việc, làm, trả kết quả. Máy người dùng không mở cổng nào.
//
//   POST /api/register                      đăng ký kênh mới -> {id, app_secret, mcp_secret}
//   /api/<kênh>/<mật khẩu app>/...          REST cho Studio566: jobs, jobs/<id>[?wait=giây], status, rotate, DELETE (xóa kênh)
//   /mcp/<kênh>/<mật khẩu MCP>              MCP (Streamable HTTP, chỉ JSON) cho app AI
//
// Mỗi kênh là một Durable Object (SQLite, có trên gói miễn phí). Việc tự xóa sau 2 giờ. Dựng bằng wrangler (wrangler.toml).

const PROTOCOLS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];
const KEEP_MS = 2 * 3600 * 1000;          // việc cũ hơn thế thì xóa
const STALE_TAKEN_MS = 5 * 60 * 1000;     // AI nhận việc mà quá 5 phút chưa trả: trả lại hàng chờ cho lượt khác
const LONGPOLL_MS = 20 * 1000;            // hàng trống mà app vẫn đang chạy: lay_viec chờ thêm chừng này
const APP_ACTIVE_MS = 90 * 1000;          // app hỏi kết quả trong khoảng này coi như đang chạy video
const MAX_BODY = 2 * 1024 * 1024;
const MAX_PENDING = 100;                  // mỗi kênh tối đa chừng này việc chưa xong
const MAX_JOBS_DAY = 1500;                // mỗi kênh tối đa chừng này việc mỗi ngày (chống lạm dụng)
const MAX_REGISTER_DAY = 30;              // mỗi địa chỉ IP tối đa chừng này kênh mới mỗi ngày
const RESULT_WAIT_MAX = 25 * 1000;        // Studio566 hỏi kết quả kiểu chờ sẵn: tối đa chừng này mỗi lượt

const INSTRUCTIONS = [
  "Cổng vào app Studio566 (dịch và lồng tiếng video). Bạn là bộ não AI của app cho các việc chữ: dịch phụ đề, rút gọn câu, phân tích video, viết kịch bản. App là nơi hiển thị kết quả, chat chỉ là nơi nhận lệnh.",
  "Người dùng nhắc tới \"việc đang chờ\", \"làm việc\", \"làm tiếp\" (hoặc câu tương tự): TỰ LÀM NGAY, KHÔNG HỎI LẠI, KHÔNG xin xác nhận.",
  "Gọi lay_viec → làm ĐÚNG phần YÊU CẦU với DỮ LIỆU → tra_ket_qua với JSON đúng KHUÔN → gọi lay_viec tiếp, lặp tới khi hàng trống. tra_ket_qua báo lỗi khuôn → tự sửa và gửi lại, không hỏi.",
  "Việc của một video tới theo từng đợt (phân tích → dịch → rút gọn): lay_viec báo app vẫn đang chạy thì gọi lay_viec thêm vài lần trước khi dừng.",
  "KHÔNG trình bày hay tóm tắt kết quả trong chat. Khi hàng trống chỉ trả lời MỘT dòng, ví dụ: \"Xong 4 việc, xem trong Studio566.\"",
].join("\n");

const TOOLS = [
  {
    name: "viec_dang_cho",
    title: "Việc đang chờ",
    description: "Xem Studio566 đang có bao nhiêu việc chờ AI làm.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: { readOnlyHint: true },
  },
  {
    name: "lay_viec",
    title: "Lấy việc",
    description: "Nhận việc tiếp theo trong hàng chờ của Studio566: YÊU CẦU, DỮ LIỆU và KHUÔN kết quả (JSON Schema). Làm xong gọi tra_ket_qua.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "tra_ket_qua",
    title: "Trả kết quả",
    description: "Gửi kết quả của một việc về Studio566. ket_qua là JSON đúng KHUÔN của việc đó (object, hoặc chuỗi JSON). Sai khuôn thì công cụ báo lỗi cụ thể để sửa và gửi lại.",
    inputSchema: {
      type: "object",
      properties: {
        id: { type: "string", description: "Mã việc, lấy từ lay_viec" },
        ket_qua: { description: "Kết quả: JSON đúng KHUÔN (object hoặc chuỗi JSON)" },
      },
      required: ["id", "ket_qua"],
    },
  },
];

// ------------------------------------------------------------------ tiện ích

function json(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json; charset=utf-8", ...headers } });
}

function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || !b || a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

function typeOf(v) {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  if (typeof v === "number") return Number.isInteger(v) ? "integer" : "number";
  return typeof v;
}

/** Kiểm JSON theo JSON Schema rút gọn (đủ cho các khuôn của Studio566). Trả về danh sách lỗi, rỗng là đạt. */
export function validate(value, schema, path = "ket_qua", out = []) {
  if (!schema || typeof schema !== "object" || out.length >= 12) return out;
  if (schema.type) {
    const want = Array.isArray(schema.type) ? schema.type : [schema.type];
    const got = typeOf(value);
    const ok = want.some((t) => t === got || (t === "number" && got === "integer"));
    if (!ok) { out.push(`${path}: cần kiểu ${want.join("|")}, nhận ${got}`); return out; }
  }
  if (schema.enum && !schema.enum.some((e) => JSON.stringify(e) === JSON.stringify(value))) {
    out.push(`${path}: chỉ được là một trong ${JSON.stringify(schema.enum).slice(0, 120)}`);
  }
  const t = typeOf(value);
  if (t === "object") {
    const props = schema.properties || {};
    for (const k of schema.required || []) if (!(k in value)) out.push(`${path}: thiếu trường "${k}"`);
    for (const [k, v] of Object.entries(value)) {
      if (props[k]) validate(v, props[k], `${path}.${k}`, out);
      else if (schema.additionalProperties === false) out.push(`${path}: thừa trường "${k}"`);
      else if (schema.additionalProperties && typeof schema.additionalProperties === "object") validate(v, schema.additionalProperties, `${path}.${k}`, out);
    }
  } else if (t === "array") {
    if (schema.minItems != null && value.length < schema.minItems) out.push(`${path}: cần ít nhất ${schema.minItems} phần tử`);
    if (schema.maxItems != null && value.length > schema.maxItems) out.push(`${path}: tối đa ${schema.maxItems} phần tử`);
    if (schema.items) value.forEach((v, i) => validate(v, schema.items, `${path}[${i}]`, out));
  } else if (t === "string") {
    if (schema.minLength != null && value.length < schema.minLength) out.push(`${path}: chuỗi quá ngắn`);
  }
  return out;
}

/** ket_qua có thể là object, hoặc chuỗi JSON (có khi kèm ```json ... ```). */
export function parseResult(raw) {
  if (raw && typeof raw === "object") return { value: raw };
  if (typeof raw !== "string") return { error: "ket_qua phải là JSON (object hoặc chuỗi JSON)" };
  let s = raw.trim();
  const fence = s.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (fence) s = fence[1];
  try {
    return { value: JSON.parse(s) };
  } catch (e) {
    return { error: `ket_qua không phải JSON hợp lệ: ${String(e.message || e).slice(0, 160)}` };
  }
}

function newId() {
  const b = new Uint8Array(6);
  crypto.getRandomValues(b);
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}

// ------------------------------------------------------------------ Worker: đăng ký kênh, chuyển yêu cầu vào đúng kênh

const HOME = `<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Studio566 MCP</title><style>body{font:16px/1.6 system-ui,sans-serif;max-width:640px;margin:48px auto;padding:0 20px;color:#1b1d22}
h1{font-size:24px}code{background:#f1f2f4;padding:1px 6px;border-radius:5px}</style>
<h1>Studio566 · cổng AI qua MCP</h1>
<p>Cổng này cho phép Claude, ChatGPT, Grok của người dùng làm các việc chữ (dịch phụ đề, rút gọn câu, viết kịch bản) cho phần mềm Studio566 trên máy của họ.</p>
<h2>Quyền riêng tư</h2>
<ul><li>Mỗi máy có một kênh riêng, có mật khẩu riêng. Không cần tài khoản, không thu thập tên, email.</li>
<li>Nội dung việc (lời thoại cần dịch) chỉ được giữ tạm để AI của chính người dùng lấy và trả kết quả, rồi xóa ngay khi Studio566 nhận kết quả. Việc bỏ dở tự xóa sau tối đa 2 giờ.</li>
<li>Không dùng nội dung cho mục đích nào khác. Người dùng có thể xóa kênh bất cứ lúc nào trong Studio566 (Ngắt kết nối).</li></ul></html>`;

async function bodyOf(request) {
  return request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();
}

function clientIp(request) {
  return request.headers.get("cf-connecting-ip") || request.headers.get("x-forwarded-for") || "local";
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const parts = url.pathname.split("/").filter(Boolean);
    if (parts.length === 0) return new Response(HOME, { headers: { "content-type": "text/html; charset=utf-8" } });
    const len = Number(request.headers.get("content-length") || 0);
    if (len > MAX_BODY) return json({ error: "Dữ liệu quá lớn" }, 413);
    if (parts[0] === "api" && parts[1] === "register" && request.method === "POST") {
      const day = new Date().toISOString().slice(0, 10);
      const reg = env.REG.get(env.REG.idFromName("ip:" + clientIp(request) + ":" + day));
      const r = await reg.fetch(new Request("https://reg/hit", { method: "POST" }));
      if (r.status !== 200) return json({ error: "Đăng ký quá nhiều kênh hôm nay, thử lại ngày mai" }, 429);
      const id = newId() + newId();
      const stub = env.QUEUE.get(env.QUEUE.idFromName("ch:" + id));
      return stub.fetch(new Request("https://queue/init/" + id, { method: "POST" }));
    }
    if (parts[0] === "api" && /^[0-9a-f]{24}$/.test(parts[1] || "") && parts[2]) {
      const stub = env.QUEUE.get(env.QUEUE.idFromName("ch:" + parts[1]));
      const fwd = new URL("https://queue/api/" + parts.slice(3).join("/"));
      fwd.search = url.search;
      const h = new Headers(request.headers);
      h.set("x-s566-key", parts[2]);
      return stub.fetch(new Request(fwd, { method: request.method, headers: h, body: await bodyOf(request) }));
    }
    if (parts[0] === "mcp" && /^[0-9a-f]{24}$/.test(parts[1] || "") && parts[2]) {
      const stub = env.QUEUE.get(env.QUEUE.idFromName("ch:" + parts[1]));
      const h = new Headers(request.headers);
      h.set("x-s566-key", parts[2]);
      return stub.fetch(new Request("https://queue/mcp", { method: request.method, headers: h, body: await bodyOf(request) }));
    }
    return json({ error: "Không tìm thấy" }, 404);
  },
};

// ------------------------------------------------------------------ đếm số kênh đăng ký theo IP mỗi ngày

export class Registry {
  constructor(ctx) { this.storage = ctx.storage; }
  async fetch() {
    const n = ((await this.storage.get("n")) || 0) + 1;
    if (n > MAX_REGISTER_DAY) return json({ ok: false }, 429);
    await this.storage.put("n", n);
    if (n === 1 && this.storage.setAlarm) await this.storage.setAlarm(Date.now() + 2 * 24 * 3600 * 1000);
    return json({ ok: true });
  }
  async alarm() { await this.storage.deleteAll(); }
}

// ------------------------------------------------------------------ hàng chờ

export class Queue {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.storage = ctx.storage;
    this.waiters = new Set();          // lay_viec đang chờ việc mới
    this.doneWaiters = new Map();      // Studio566 đang chờ kết quả: id việc -> các hàm đánh thức
  }

  async meta() {
    return (await this.storage.get("meta")) || {};
  }

  async touch(fields) {
    const m = await this.meta();
    await this.storage.put("meta", { ...m, ...fields });
  }

  async jobs() {
    const map = await this.storage.list({ prefix: "job:" });
    const now = Date.now();
    const out = [];
    for (const [key, job] of map) {
      if (now - job.created > KEEP_MS) { await this.storage.delete(key); continue; }
      if (job.status === "taken" && now - job.taken_at > STALE_TAKEN_MS) {
        job.status = "pending";
        job.taken_at = 0;
        await this.storage.put(key, job);
      }
      out.push(job);
    }
    out.sort((a, b) => a.created - b.created);
    return out;
  }

  wake() {
    for (const w of [...this.waiters]) w();
  }

  wakeDone(id) {
    for (const w of [...(this.doneWaiters.get(id) || [])]) w();
  }

  waitDone(id, ms) {
    return new Promise((resolve) => {
      let timer;
      const set = this.doneWaiters.get(id) || new Set();
      this.doneWaiters.set(id, set);
      const w = () => { clearTimeout(timer); set.delete(w); resolve(true); };
      timer = setTimeout(() => { set.delete(w); resolve(false); }, ms);
      set.add(w);
    });
  }

  waitForJob(ms) {
    return new Promise((resolve) => {
      let timer;
      const w = () => { clearTimeout(timer); this.waiters.delete(w); resolve(true); };
      timer = setTimeout(() => { this.waiters.delete(w); resolve(false); }, ms);
      this.waiters.add(w);
    });
  }

  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/init/")) {
      if (await this.storage.get("keys")) return json({ error: "Kênh đã có" }, 409);
      const keys = { app: newId() + newId() + newId(), mcp: newId() + newId() + newId(), created: Date.now() };
      await this.storage.put("keys", keys);
      return json({ id: url.pathname.slice(6), app_secret: keys.app, mcp_secret: keys.mcp });
    }
    const keys = await this.storage.get("keys");
    const given = request.headers.get("x-s566-key") || "";
    if (url.pathname === "/mcp") {
      if (!keys || !safeEqual(given, keys.mcp)) return json({ error: "Không tìm thấy" }, 404);
      return this.mcp(request);
    }
    if (!keys || !safeEqual(given, keys.app)) return json({ error: "Không tìm thấy" }, 404);
    return this.api(request, url.pathname.replace(/^\/api\/?/, ""), url);
  }

  // ---------------------------------------------------------------- REST cho Studio566

  async api(request, path, url) {
    const now = Date.now();
    await this.touch({ app_seen: now });
    const m = request.method;
    if (path === "" && m === "DELETE") {          // ngắt kết nối: xóa sạch kênh
      for (const w of [...this.waiters]) w();
      await this.storage.deleteAll();
      return json({ ok: true });
    }
    if (path === "rotate" && m === "POST") {      // đổi link MCP (lỡ để lộ)
      const keys = await this.storage.get("keys");
      keys.mcp = newId() + newId() + newId();
      await this.storage.put("keys", keys);
      return json({ mcp_secret: keys.mcp });
    }
    if (path === "status" && m === "GET") {
      const all = await this.jobs();
      const meta = await this.meta();
      return json({
        ok: true,
        pending: all.filter((j) => j.status === "pending").length,
        taken: all.filter((j) => j.status === "taken").length,
        ai_seen: meta.ai_seen || 0, ai_name: meta.ai_name || "", now,
      });
    }
    if (path === "jobs" && m === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "JSON không hợp lệ" }, 400); }
      if (typeof body.user !== "string" || typeof body.system !== "string") return json({ error: "Thiếu system/user" }, 400);
      const all = await this.jobs();
      if (all.filter((j) => j.status !== "done").length >= MAX_PENDING) return json({ error: "Kênh có quá nhiều việc chưa xong" }, 429);
      const day = new Date(now).toISOString().slice(0, 10);
      const meta = await this.meta();
      const count = meta.day === day ? (meta.count || 0) + 1 : 1;
      if (count > MAX_JOBS_DAY) return json({ error: "Kênh đã dùng hết lượt hôm nay" }, 429);
      await this.touch({ day, count });
      const job = {
        id: newId(), status: "pending", created: now, taken_at: 0, done_at: 0,
        title: String(body.title || "Việc chữ").slice(0, 120), system: body.system, user: body.user,
        schema: body.schema && typeof body.schema === "object" ? body.schema : null, result: null, by: "",
      };
      await this.storage.put("job:" + job.id, job);
      this.wake();
      return json({ id: job.id });
    }
    const mm = path.match(/^jobs\/([0-9a-f]{6,32})$/);
    if (mm) {
      const key = "job:" + mm[1];
      const job = await this.storage.get(key);
      if (m === "DELETE") { await this.storage.delete(key); return json({ ok: true }); }
      if (m === "GET") {
        if (!job) return json({ status: "missing" });
        await this.jobs();     // trả việc nhận quá hạn về hàng chờ
        let cur = (await this.storage.get(key)) || job;
        const wait = Math.min(RESULT_WAIT_MAX, Math.max(0, Number(url.searchParams.get("wait") || 0) * 1000));
        if (cur.status !== "done" && wait > 0) {      // chờ sẵn tới khi AI trả kết quả: ít lượt gọi hơn hỏi liên tục
          await this.waitDone(mm[1], wait);
          cur = (await this.storage.get(key)) || cur;
        }
        const out = { status: cur.status, taken_at: cur.taken_at, by: cur.by };
        if (cur.status === "done") { out.result = cur.result; await this.storage.delete(key); }
        return json(out);
      }
    }
    return json({ error: "Không tìm thấy" }, 404);
  }

  // ---------------------------------------------------------------- MCP (JSON-RPC 2.0 qua HTTP POST)

  async mcp(request) {
    if (request.method !== "POST") return new Response("Chỉ hỗ trợ POST", { status: 405, headers: { allow: "POST" } });
    let msg;
    try { msg = await request.json(); } catch { return json({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } }, 400); }
    const batch = Array.isArray(msg);
    const out = [];
    for (const one of batch ? msg : [msg]) {
      const res = await this.rpc(one);
      if (res) out.push(res);
    }
    if (!out.length) return new Response(null, { status: 202 });
    return json(batch ? out : out[0]);
  }

  async rpc(msg) {
    if (!msg || msg.jsonrpc !== "2.0" || typeof msg.method !== "string") {
      return { jsonrpc: "2.0", id: msg && msg.id != null ? msg.id : null, error: { code: -32600, message: "Invalid Request" } };
    }
    const isNote = msg.id === undefined || msg.id === null;
    const ok = (result) => (isNote ? null : { jsonrpc: "2.0", id: msg.id, result });
    const fail = (code, message) => (isNote ? null : { jsonrpc: "2.0", id: msg.id, error: { code, message } });
    const p = msg.params || {};
    switch (msg.method) {
      case "initialize": {
        const want = p.protocolVersion;
        const name = (p.clientInfo && p.clientInfo.name) || "";
        await this.touch({ ai_seen: Date.now(), ai_name: String(name).slice(0, 60) });
        return ok({
          protocolVersion: PROTOCOLS.includes(want) ? want : PROTOCOLS[0],
          capabilities: { tools: { listChanged: false } },
          serverInfo: { name: "studio566", title: "Studio566", version: "1.0.0" },
          instructions: INSTRUCTIONS,
        });
      }
      case "ping":
        return ok({});
      case "tools/list":
        return ok({ tools: TOOLS });
      case "tools/call": {
        await this.touch({ ai_seen: Date.now() });
        try {
          return ok(await this.call(p.name, p.arguments || {}));
        } catch (e) {
          return ok({ content: [{ type: "text", text: "Lỗi: " + String(e.message || e) }], isError: true });
        }
      }
      default:
        if (msg.method.startsWith("notifications/")) return null;
        return fail(-32601, "Method not found: " + msg.method);
    }
  }

  async call(name, args) {
    const text = (t, isError = false) => ({ content: [{ type: "text", text: t }], isError });
    if (name === "viec_dang_cho") {
      const all = await this.jobs();
      const pend = all.filter((j) => j.status === "pending");
      const taken = all.filter((j) => j.status === "taken");
      if (!pend.length && !taken.length) return text(await this.idleHint("Không có việc nào đang chờ."));
      const lines = pend.map((j) => `- ${j.id}: ${j.title}`);
      return text(`${pend.length} việc đang chờ, ${taken.length} việc đang có AI làm.` + (lines.length ? "\n" + lines.join("\n") : "") + "\nGọi lay_viec để bắt đầu.");
    }
    if (name === "lay_viec") {
      let job = await this.claim();
      if (!job && (await this.appActive())) {
        if (await this.waitForJob(LONGPOLL_MS)) job = await this.claim();
      }
      if (!job) return text(await this.idleHint("Hàng trống."));
      const left = (await this.jobs()).filter((j) => j.status === "pending").length;
      const parts = [
        `VIỆC ${job.id} · ${job.title}`,
        left ? `Còn ${left} việc khác đang chờ.` : "",
        "",
        "=== YÊU CẦU ===",
        job.system,
        "",
        "=== DỮ LIỆU ===",
        job.user,
      ];
      if (job.schema) parts.push("", "=== KHUÔN KẾT QUẢ (JSON Schema) ===", JSON.stringify(job.schema));
      parts.push("", `Làm đúng YÊU CẦU với DỮ LIỆU, rồi gọi tra_ket_qua với id="${job.id}" và ket_qua là JSON đúng KHUÔN. Chỉ gửi JSON, không giải thích.`);
      return text(parts.filter((x, i) => x !== "" || i > 1).join("\n"));
    }
    if (name === "tra_ket_qua") {
      const id = String(args.id || "").trim();
      const key = "job:" + id;
      const job = await this.storage.get(key);
      if (!job || job.status === "done") return text(`Việc ${id || "(trống)"} không còn (đã xong, bị hủy hoặc hết hạn). Gọi lay_viec để lấy việc khác.`, true);
      const parsed = parseResult(args.ket_qua);
      if (parsed.error) return text(parsed.error + "\nSửa rồi gọi tra_ket_qua lại với cùng id.", true);
      const errs = job.schema ? validate(parsed.value, job.schema) : [];
      if (errs.length) return text("Kết quả chưa đúng khuôn:\n- " + errs.join("\n- ") + "\nSửa rồi gọi tra_ket_qua lại với cùng id.", true);
      job.status = "done";
      job.result = parsed.value;
      job.done_at = Date.now();
      await this.storage.put(key, job);
      this.wakeDone(id);
      const left = (await this.jobs()).filter((j) => j.status === "pending").length;
      return text(left ? `Đã nhận. Còn ${left} việc đang chờ: gọi lay_viec tiếp.` : await this.idleHint("Đã nhận. Hàng đã trống."));
    }
    return text("Không có công cụ " + name, true);
  }

  async claim() {
    const all = await this.jobs();
    const job = all.find((j) => j.status === "pending");
    if (!job) return null;
    job.status = "taken";
    job.taken_at = Date.now();
    job.by = ((await this.meta()).ai_name || "").slice(0, 60);
    await this.storage.put("job:" + job.id, job);
    return job;
  }

  async appActive() {
    const m = await this.meta();
    return Date.now() - (m.app_seen || 0) < APP_ACTIVE_MS;
  }

  async idleHint(base) {
    return (await this.appActive())
      ? base + " Studio566 vẫn đang chạy video và có thể sắp có việc mới: gọi lay_viec thêm lần nữa trước khi dừng."
      : base + " Studio566 không chạy video nào lúc này.";
  }
}
