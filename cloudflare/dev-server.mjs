// Chạy cổng MCP trung tâm ngay trên máy để thử (không cần Cloudflare): node cloudflare/dev-server.mjs <cổng>
import http from "node:http";
import worker, { Queue, Registry } from "./studio566-mcp.js";

class MemStorage {
  constructor() { this.m = new Map(); }
  async get(k) { return this.m.has(k) ? structuredClone(this.m.get(k)) : undefined; }
  async put(k, v) { this.m.set(k, structuredClone(v)); }
  async delete(k) { return this.m.delete(k); }
  async deleteAll() { this.m.clear(); }
  async setAlarm() {}
  async list({ prefix = "" } = {}) { return new Map([...this.m].filter(([k]) => k.startsWith(prefix)).map(([k, v]) => [k, structuredClone(v)])); }
}
function ns(Cls) {
  const objs = new Map();
  return { idFromName: (n) => n, get: (n) => { if (!objs.has(n)) objs.set(n, new Cls({ storage: new MemStorage() }, {})); return { fetch: (r) => objs.get(n).fetch(r) }; } };
}

const port = Number(process.argv[2] || 8787);
const env = { QUEUE: ns(Queue), REG: ns(Registry) };

http.createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = req.method === "GET" || req.method === "HEAD" ? undefined : Buffer.concat(chunks);
  const r = await worker.fetch(new Request(`http://127.0.0.1:${port}${req.url}`, { method: req.method, headers: req.headers, body }), env);
  res.writeHead(r.status, Object.fromEntries(r.headers));
  res.end(Buffer.from(await r.arrayBuffer()));
}).listen(port, "127.0.0.1", () => console.log(`dev MCP on ${port}`));
