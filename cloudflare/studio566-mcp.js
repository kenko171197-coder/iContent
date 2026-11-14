// Cổng MCP của Studio566, chạy trên Cloudflare Workers (tài khoản Cloudflare của chính người dùng, gói miễn phí).
//
// Studio566 trên máy gửi việc chữ (dịch, rút gọn, phân tích, viết kịch bản...) lên đây; Claude, ChatGPT hay Grok nối vào
// /mcp/<MCP_SECRET> qua MCP, lấy việc, làm, trả kết quả; Studio566 lấy kết quả về. Máy người dùng không mở cổng nào.
//
//   /mcp/<MCP_SECRET>        MCP (Streamable HTTP, chỉ JSON, không SSE) cho các app AI
//   /api/<APP_SECRET>/...    REST cho Studio566: jobs (POST), jobs/<id> (GET, DELETE), status (GET)
//
// Hàng chờ nằm trong một Durable Object (lưu SQLite, có trên gói miễn phí). Việc tự xóa sau 2 giờ.
// Studio566 tự tải file này lên bằng API Cloudflare (icontent/mcpcloud.py): không cần wrangler hay Node.

const PROTOCOLS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];
const KEEP_MS = 2 * 3600 * 1000;          // việc cũ hơn thế thì xóa
const STALE_TAKEN_MS = 5 * 60 * 1000;     // AI nhận việc mà quá 5 phút chưa trả: trả lại hàng chờ cho lượt khác
const LONGPOLL_MS = 20 * 1000;            // hàng trống mà app vẫn đang chạy: lay_viec chờ thêm chừng này
const APP_ACTIVE_MS = 90 * 1000;          // app hỏi kết quả trong khoảng này coi như đang chạy video
const MAX_BODY = 4 * 1024 * 1024;

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

// ------------------------------------------------------------------ Worker: chỉ kiểm mật khẩu rồi chuyển vào hàng chờ

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const parts = url.pathname.split("/").filter(Boolean);
    if (parts.length === 0) {
      return new Response("Studio566 MCP: cổng đang chạy.", { headers: { "content-type": "text/plain; charset=utf-8" } });
    }
    const len = Number(request.headers.get("content-length") || 0);
    if (len > MAX_BODY) return json({ error: "Dữ liệu quá lớn" }, 413);
    const stub = env.QUEUE.get(env.QUEUE.idFromName("main"));
    if (parts[0] === "mcp" && safeEqual(parts[1] || "", env.MCP_SECRET)) {
      return stub.fetch(new Request("https://queue/mcp", request));
    }
    if (parts[0] === "api" && safeEqual(parts[1] || "", env.APP_SECRET)) {
      return stub.fetch(new Request("https://queue/api/" + parts.slice(2).join("/"), request));
    }
    return json({ error: "Không tìm thấy" }, 404);
  },
};

// ------------------------------------------------------------------ hàng chờ

export class Queue {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.storage = ctx.storage;
    this.waiters = new Set();
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
    if (url.pathname === "/mcp") return this.mcp(request);
    return this.api(request, url.pathname.replace(/^\/api\/?/, ""));
  }

  // ---------------------------------------------------------------- REST cho Studio566

  async api(request, path) {
    const now = Date.now();
    await this.touch({ app_seen: now });
    const m = request.method;
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
        const cur = (await this.storage.get(key)) || job;
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
