// Production server for the built React app (`npm run build`, then `npm start`).
// No dependencies beyond Node itself, so it also runs where devDependencies are pruned.
//
//   PORT=8080                         port to listen on (hosting platforms set this)
//   HOST=0.0.0.0                      interface to bind
//   API_URL=https://api.example.com   optional: forward /api/* to the CellLoop API (same-origin, no CORS)
//   VITE_API_BASE=https://api…        if the browser calls the API directly, it's allowed by the CSP
//
// Serves dist/ with: SPA fallback (deep links like /dashboard work), long-term caching for
// fingerprinted assets, gzip, security headers, /healthz, and graceful shutdown.

import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import http from "node:http";
import https from "node:https";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { securityHeaders } from "./security-headers.js";

const ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "dist");
const PORT = Number(process.env.PORT) || 4173;
const HOST = process.env.HOST || "0.0.0.0";
const API_URL = (process.env.API_URL || "").replace(/\/+$/, "");

function originOf(url) {
  try {
    return url ? new URL(url).origin : "";
  } catch {
    return "";
  }
}

if (!existsSync(join(ROOT, "index.html"))) {
  console.error(`[cellloop-web] ${ROOT}/index.html not found. Run "npm run build" before "npm start".`);
  process.exit(1);
}
if (API_URL && !/^https?:\/\//.test(API_URL)) {
  console.error(`[cellloop-web] API_URL must start with http:// or https:// (got "${API_URL}").`);
  process.exit(1);
}

const HEADERS = securityHeaders(originOf(process.env.VITE_API_BASE));
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
  ".map": "application/json; charset=utf-8",
};
const COMPRESSIBLE = new Set([".html", ".js", ".css", ".json", ".svg", ".txt", ".map"]);
const gzCache = new Map(); // path -> gzipped buffer (dist/ is immutable while running)
const INDEX = join(ROOT, "index.html");

function send(res, status, body, headers = {}) {
  res.writeHead(status, { ...HEADERS, ...headers });
  res.end(body);
}

function sendJson(res, status, detail, code) {
  send(res, status, JSON.stringify({ detail, code }), { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
}

function serveFile(req, res, file) {
  const ext = extname(file).toLowerCase();
  const isIndex = file === INDEX;
  const headers = {
    "Content-Type": TYPES[ext] || "application/octet-stream",
    // Vite fingerprints everything under /assets, so it can be cached forever; index.html never.
    "Cache-Control": isIndex ? "no-cache" : file.includes(`${sep}assets${sep}`) ? "public, max-age=31536000, immutable" : "public, max-age=3600",
    Vary: "Accept-Encoding",
  };
  if (COMPRESSIBLE.has(ext) && /\bgzip\b/.test(req.headers["accept-encoding"] || "")) {
    let gz = gzCache.get(file);
    if (!gz) {
      gz = gzipSync(readFileSync(file), { level: 9 });
      gzCache.set(file, gz);
    }
    headers["Content-Encoding"] = "gzip";
    headers["Content-Length"] = gz.length;
    res.writeHead(200, { ...HEADERS, ...headers });
    return res.end(req.method === "HEAD" ? undefined : gz);
  }
  headers["Content-Length"] = statSync(file).size;
  res.writeHead(200, { ...HEADERS, ...headers });
  if (req.method === "HEAD") return res.end();
  createReadStream(file).on("error", () => res.destroy()).pipe(res);
}

function proxyApi(req, res) {
  if (!API_URL) {
    return sendJson(res, 404, "API proxy not configured: set API_URL, or build with VITE_API_BASE.", "api_not_configured");
  }
  const target = new URL(req.url, API_URL);
  const client = target.protocol === "https:" ? https : http;
  const headers = { ...req.headers, host: target.host };
  headers["x-forwarded-for"] = [req.headers["x-forwarded-for"], req.socket.remoteAddress].filter(Boolean).join(", ");
  headers["x-forwarded-proto"] = req.headers["x-forwarded-proto"] || "http";
  const upstream = client.request(target, { method: req.method, headers, timeout: 300_000 }, (up) => {
    res.writeHead(up.statusCode || 502, up.headers);
    up.pipe(res);
  });
  upstream.on("timeout", () => upstream.destroy(new Error("timeout")));
  upstream.on("error", (err) => {
    console.error(`[cellloop-web] API proxy error: ${err.message}`);
    if (!res.headersSent) sendJson(res, 502, "The CellLoop API isn't responding. Please try again shortly.", "api_unreachable");
    else res.destroy();
  });
  req.pipe(upstream);
}

const server = http.createServer((req, res) => {
  try {
    const url = new URL(req.url || "/", "http://localhost");
    if (url.pathname === "/healthz") return send(res, 200, "ok", { "Content-Type": "text/plain", "Cache-Control": "no-store" });
    if (url.pathname === "/api" || url.pathname.startsWith("/api/")) return proxyApi(req, res);
    if (req.method !== "GET" && req.method !== "HEAD") return send(res, 405, "Method Not Allowed", { Allow: "GET, HEAD" });

    let pathname;
    try {
      pathname = decodeURIComponent(url.pathname);
    } catch {
      return send(res, 400, "Bad Request");
    }
    // Resolve inside dist/ only (blocks ../ traversal and absolute paths).
    const file = normalize(join(ROOT, pathname));
    if (file !== ROOT && !file.startsWith(ROOT + sep)) return send(res, 400, "Bad Request");

    if (existsSync(file) && statSync(file).isFile()) return serveFile(req, res, file);
    // Missing file with an extension (e.g. an old /assets/x.js) is a real 404, not the app shell.
    if (extname(pathname)) return send(res, 404, "Not Found", { "Content-Type": "text/plain", "Cache-Control": "no-store" });
    // Client-side route (/dashboard, /experiments/123…): serve the app shell.
    return serveFile(req, res, INDEX);
  } catch (err) {
    console.error("[cellloop-web] request failed:", err);
    if (!res.headersSent) send(res, 500, "Internal Server Error");
    else res.destroy();
  }
});

server.listen(PORT, HOST, () => {
  console.log(`[cellloop-web] Serving ${ROOT} on http://${HOST === "0.0.0.0" ? "localhost" : HOST}:${PORT}` +
    (API_URL ? ` (proxying /api to ${API_URL})` : ""));
});

for (const signal of ["SIGTERM", "SIGINT"]) {
  process.on(signal, () => {
    console.log(`[cellloop-web] ${signal} received, shutting down`);
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 5000).unref();
  });
}
