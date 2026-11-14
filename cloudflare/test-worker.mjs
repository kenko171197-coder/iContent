// Kiểm thử cổng MCP không cần Cloudflare: giả lập Durable Object bằng Map. Chạy: node cloudflare/test-worker.mjs
import assert from "node:assert/strict";
import worker, { Queue, validate, parseResult } from "./studio566-mcp.js";

class MemStorage {
  constructor() { this.m = new Map(); }
  async get(k) { return this.m.has(k) ? structuredClone(this.m.get(k)) : undefined; }
  async put(k, v) { this.m.set(k, structuredClone(v)); }
  async delete(k) { return this.m.delete(k); }
  async list({ prefix = "" } = {}) {
    return new Map([...this.m].filter(([k]) => k.startsWith(prefix)).sort(([a], [b]) => (a < b ? -1 : 1)).map(([k, v]) => [k, structuredClone(v)]));
  }
}

const q = new Queue({ storage: new MemStorage() }, {});
const env = {
  MCP_SECRET: "m".repeat(32), APP_SECRET: "a".repeat(32),
  QUEUE: { idFromName: () => "main", get: () => ({ fetch: (req) => q.fetch(req) }) },
};
const base = "https://studio566-mcp.x.workers.dev";
const call = (path, init) => worker.fetch(new Request(base + path, init), env);
const app = (path, method = "GET", body) => call(`/api/${env.APP_SECRET}/${path}`, { method, body: body && JSON.stringify(body), headers: { "content-type": "application/json" } });
let rid = 0;
const rpc = async (method, params) => {
  const r = await call(`/mcp/${env.MCP_SECRET}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: ++rid, method, params }) });
  return r.json();
};
const tool = async (name, args = {}) => (await rpc("tools/call", { name, arguments: args })).result;

// mật khẩu sai: không vào được
assert.equal((await call("/mcp/sai", { method: "POST", body: "{}" })).status, 404);
assert.equal((await call("/api/sai/status")).status, 404);

// bắt tay MCP
const init = await rpc("initialize", { protocolVersion: "2025-06-18", clientInfo: { name: "claude-ai" }, capabilities: {} });
assert.equal(init.result.protocolVersion, "2025-06-18");
assert.ok(init.result.instructions.includes("lay_viec"));
const note = await call(`/mcp/${env.MCP_SECRET}`, { method: "POST", body: JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) });
assert.equal(note.status, 202);
assert.deepEqual((await rpc("tools/list")).result.tools.map((t) => t.name), ["viec_dang_cho", "lay_viec", "tra_ket_qua"]);
assert.equal((await rpc("khong/co")).error.code, -32601);

// Studio566 gửi việc dịch
const SCHEMA = { type: "object", properties: { items: { type: "array", items: { type: "object", properties: { id: { type: "integer" }, text: { type: "string" } }, required: ["id", "text"], additionalProperties: false } } }, required: ["items"], additionalProperties: false };
const { id } = await (await app("jobs", "POST", { title: "Dịch 2 câu", system: "Dịch sang tiếng Việt.", user: '[{"id":1,"zh":"你好"},{"id":2,"zh":"再见"}]', schema: SCHEMA })).json();
assert.match(id, /^[0-9a-f]{12}$/);
assert.equal((await (await app("status")).json()).pending, 1);
assert.ok((await tool("viec_dang_cho")).content[0].text.includes("Dịch 2 câu"));

// AI lấy việc
const got = (await tool("lay_viec")).content[0].text;
assert.ok(got.includes(`VIỆC ${id}`) && got.includes("=== YÊU CẦU ===") && got.includes("你好") && got.includes("KHUÔN"));
assert.equal((await (await app(`jobs/${id}`)).json()).status, "taken");

// trả sai khuôn: bị báo lỗi cụ thể
let r = await tool("tra_ket_qua", { id, ket_qua: { items: [{ id: "1", text: "Xin chào" }] } });
assert.equal(r.isError, true);
assert.ok(r.content[0].text.includes("ket_qua.items[0].id"));
r = await tool("tra_ket_qua", { id, ket_qua: "không phải json" });
assert.equal(r.isError, true);

// trả đúng (chuỗi JSON trong ```json```): app nhận được, việc tự xóa
r = await tool("tra_ket_qua", { id, ket_qua: '```json\n{"items":[{"id":1,"text":"Xin chào"},{"id":2,"text":"Tạm biệt"}]}\n```' });
assert.equal(r.isError, false);
const done = await (await app(`jobs/${id}`)).json();
assert.equal(done.status, "done");
assert.equal(done.result.items[1].text, "Tạm biệt");
assert.equal((await (await app(`jobs/${id}`)).json()).status, "missing");
r = await tool("tra_ket_qua", { id, ket_qua: {} });
assert.equal(r.isError, true);

// hàng trống khi app đang chạy: lay_viec chờ, việc mới tới thì nhận luôn
const waiting = tool("lay_viec");
await new Promise((res) => setTimeout(res, 50));
const j2 = await (await app("jobs", "POST", { title: "Rút gọn 1 câu", system: "Rút gọn.", user: "abc", schema: null })).json();
const got2 = (await waiting).content[0].text;
assert.ok(got2.includes(`VIỆC ${j2.id}`), got2);

// hủy việc
await app(`jobs/${j2.id}`, "DELETE");
assert.equal((await (await app(`jobs/${j2.id}`)).json()).status, "missing");

// việc AI nhận rồi bỏ quá 5 phút: trả lại hàng chờ
const j3 = await (await app("jobs", "POST", { title: "x", system: "s", user: "u" })).json();
await tool("lay_viec");
const stored = await q.storage.get("job:" + j3.id);
stored.taken_at -= 6 * 60 * 1000;
await q.storage.put("job:" + j3.id, stored);
assert.equal((await (await app(`jobs/${j3.id}`)).json()).status, "pending");

// trình kiểm khuôn
assert.deepEqual(validate({ a: 1 }, { type: "object", properties: { a: { type: "number" } }, required: ["a"] }), []);
assert.equal(validate([1, "x"], { type: "array", items: { type: "integer" } }).length, 1);
assert.equal(parseResult(" {\"a\":1} ").value.a, 1);

console.log("Cổng MCP: tất cả kiểm thử đạt");
