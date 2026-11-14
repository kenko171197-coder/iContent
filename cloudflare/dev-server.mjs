// Chạy cổng MCP ngay trên máy để thử (không cần Cloudflare): node cloudflare/dev-server.mjs <cổng> <mật khẩu MCP> <mật khẩu app>
import http from "node:http";
import worker, { Queue } from "./studio566-mcp.js";

class MemStorage {
  constructor() { this.m = new Map(); }
  async get(k) { return this.m.has(k) ? structuredClone(this.m.get(k)) : undefined; }
  async put(k, v) { this.m.set(k, structuredClone(v)); }
  async delete(k) { return this.m.delete(k); }
  async list({ prefix = "" } = {}) { return new Map([...this.m].filter(([k]) => k.startsWith(prefix)).map(([k, v]) => [k, structuredClone(v)])); }
}

const [port = "8787", mcpSecret = "dev-mcp", appSecret = "dev-app"] = process.argv.slice(2);
const q = new Queue({ storage: new MemStorage() }, {});
const env = { MCP_SECRET: mcpSecret, APP_SECRET: appSecret, QUEUE: { idFromName: () => "main", get: () => ({ fetch: (r) => q.fetch(r) }) } };

http.createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = chunks.length ? Buffer.concat(chunks) : undefined;
  const r = await worker.fetch(new Request(`http://127.0.0.1:${port}${req.url}`, { method: req.method, headers: req.headers, body: req.method === "GET" || req.method === "HEAD" ? undefined : body }), env);
  res.writeHead(r.status, Object.fromEntries(r.headers));
  res.end(Buffer.from(await r.arrayBuffer()));
}).listen(Number(port), "127.0.0.1", () => console.log(`dev MCP on ${port}`));
