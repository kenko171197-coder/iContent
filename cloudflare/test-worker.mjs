// Kiểm thử cổng MCP trung tâm không cần Cloudflare: giả lập Durable Object bằng Map. Chạy: node cloudflare/test-worker.mjs
import assert from "node:assert/strict";
import worker, { Queue, Registry, validate, parseResult } from "./studio566-mcp.js";

class MemStorage {
  constructor() { this.m = new Map(); }
  async get(k) { return this.m.has(k) ? structuredClone(this.m.get(k)) : undefined; }
  async put(k, v) { this.m.set(k, structuredClone(v)); }
  async delete(k) { return this.m.delete(k); }
  async deleteAll() { this.m.clear(); }
  async setAlarm() {}
  async list({ prefix = "" } = {}) {
    return new Map([...this.m].filter(([k]) => k.startsWith(prefix)).sort(([a], [b]) => (a < b ? -1 : 1)).map(([k, v]) => [k, structuredClone(v)]));
  }
}

function ns(Cls) {
  const objs = new Map();
  return {
    idFromName: (n) => n,
    get: (n) => {
      if (!objs.has(n)) objs.set(n, new Cls({ storage: new MemStorage() }, {}));
      return { fetch: (req) => objs.get(n).fetch(req), obj: objs.get(n) };
    },
  };
}
const env = { QUEUE: ns(Queue), REG: ns(Registry) };
const base = "https://studio566-mcp.x.workers.dev";
const call = (path, init) => worker.fetch(new Request(base + path, init), env);

async function register(ip = "1.2.3.4") {
  const r = await call("/api/register", { method: "POST", headers: { "cf-connecting-ip": ip } });
  return { status: r.status, ...(await r.json()) };
}
function channel(c) {
  let rid = 0;
  const app = (path, method = "GET", body) => call(`/api/${c.id}/${c.app_secret}/${path}`, { method, body: body && JSON.stringify(body), headers: { "content-type": "application/json" } });
  const rpc = async (method, params) => {
    const r = await call(`/mcp/${c.id}/${c.mcp_secret}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: ++rid, method, params }) });
    return r.status === 200 ? r.json() : { status: r.status };
  };
  const tool = async (name, args = {}) => (await rpc("tools/call", { name, arguments: args })).result;
  return { app, rpc, tool };
}

// trang chủ có chính sách quyền riêng tư
assert.ok((await (await call("/")).text()).includes("Quyền riêng tư"));

// đăng ký hai kênh
const A = await register();
const B = await register();
assert.equal(A.status, 200);
assert.match(A.id, /^[0-9a-f]{24}$/);
assert.notEqual(A.id, B.id);
const a = channel(A), b = channel(B);

// mật khẩu sai hoặc kênh lạ: không vào được
assert.equal((await call(`/mcp/${A.id}/sai`, { method: "POST", body: "{}" })).status, 404);
assert.equal((await call(`/api/${A.id}/${B.app_secret}/status`)).status, 404);
assert.equal((await call(`/mcp/${A.id}/${A.app_secret}`, { method: "POST", body: "{}" })).status, 404);      // mật khẩu app không dùng cho MCP
assert.equal((await call(`/api/${"0".repeat(24)}/x/status`)).status, 404);

// bắt tay MCP
const init = await a.rpc("initialize", { protocolVersion: "2025-06-18", clientInfo: { name: "claude-ai" }, capabilities: {} });
assert.equal(init.result.protocolVersion, "2025-06-18");
assert.ok(init.result.instructions.includes("lay_viec"));
assert.deepEqual((await a.rpc("tools/list")).result.tools.map((t) => t.name), ["viec_dang_cho", "lay_viec", "tra_ket_qua"]);

// kênh A gửi việc; kênh B không thấy
const SCHEMA = { type: "object", properties: { items: { type: "array", items: { type: "object", properties: { id: { type: "integer" }, text: { type: "string" } }, required: ["id", "text"], additionalProperties: false } } }, required: ["items"], additionalProperties: false };
const { id } = await (await a.app("jobs", "POST", { title: "Dịch 2 câu", system: "Dịch sang tiếng Việt.", user: '[{"id":1,"zh":"你好"},{"id":2,"zh":"再见"}]', schema: SCHEMA })).json();
assert.equal((await (await a.app("status")).json()).pending, 1);
assert.equal((await (await b.app("status")).json()).pending, 0);
assert.ok((await b.tool("lay_viec")).content[0].text.startsWith("Hàng trống"));

// AI của A lấy việc, trả sai rồi trả đúng
const got = (await a.tool("lay_viec")).content[0].text;
assert.ok(got.includes(`VIỆC ${id}`) && got.includes("你好"));
let r = await a.tool("tra_ket_qua", { id, ket_qua: { items: [{ id: "1", text: "Xin chào" }] } });
assert.equal(r.isError, true);
assert.ok(r.content[0].text.includes("ket_qua.items[0].id"));
// Studio566 chờ sẵn kết quả, AI trả trong lúc đó: nhận ngay
const waiting = a.app(`jobs/${id}?wait=10`);
await new Promise((res) => setTimeout(res, 50));
r = await a.tool("tra_ket_qua", { id, ket_qua: '```json\n{"items":[{"id":1,"text":"Xin chào"},{"id":2,"text":"Tạm biệt"}]}\n```' });
assert.equal(r.isError, false);
const done = await (await waiting).json();
assert.equal(done.status, "done");
assert.equal(done.result.items[1].text, "Tạm biệt");
assert.equal((await (await a.app(`jobs/${id}`)).json()).status, "missing");

// AI của B không trả được việc của A
const j2 = await (await a.app("jobs", "POST", { title: "x", system: "s", user: "u" })).json();
r = await b.tool("tra_ket_qua", { id: j2.id, ket_qua: {} });
assert.equal(r.isError, true);

// hàng trống khi app đang chạy: lay_viec chờ, việc mới tới thì nhận luôn
await a.app(`jobs/${j2.id}`, "DELETE");
const w = a.tool("lay_viec");
await new Promise((res) => setTimeout(res, 50));
const j3 = await (await a.app("jobs", "POST", { title: "Rút gọn 1 câu", system: "Rút gọn.", user: "abc" })).json();
assert.ok((await w).content[0].text.includes(`VIỆC ${j3.id}`));

// đổi link MCP: link cũ hết dùng
const rot = await (await a.app("rotate", "POST")).json();
assert.notEqual(rot.mcp_secret, A.mcp_secret);
assert.equal((await a.rpc("ping")).status, 404);
const a2 = channel({ ...A, mcp_secret: rot.mcp_secret });
assert.deepEqual((await a2.rpc("ping")).result, {});

// ngắt kết nối: kênh bị xóa
await a.app("", "DELETE");
assert.equal((await a.app("status")).status, 404);

// giới hạn đăng ký theo IP mỗi ngày
let last;
for (let i = 0; i < 31; i++) last = await register("9.9.9.9");
assert.equal(last.status, 429);

// trình kiểm khuôn
assert.deepEqual(validate({ a: 1 }, { type: "object", properties: { a: { type: "number" } }, required: ["a"] }), []);
assert.equal(validate([1, "x"], { type: "array", items: { type: "integer" } }).length, 1);
assert.equal(parseResult(" {\"a\":1} ").value.a, 1);

console.log("Cổng MCP trung tâm: tất cả kiểm thử đạt");
