import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Production Content-Security-Policy. nginx.conf sends the same policy; `npm run preview`
// applies it locally so a production build can be checked against it.
// style-src needs 'unsafe-inline': Plotly and React inline styles on SVG elements.
export const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self' https://*.amazoncognito.com",
  "frame-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self' https://*.amazoncognito.com",
  "frame-ancestors 'none'",
].join("; ");

const apiProxy = { "/api": { target: process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000", changeOrigin: true } };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    chunkSizeWarningLimit: 5000,
    rollupOptions: { output: { manualChunks: { plotly: ["plotly.js-dist-min"] } } },
  },
  server: { port: 5173, proxy: apiProxy },
  preview: {
    port: 4173,
    proxy: apiProxy,
    headers: {
      "Content-Security-Policy": CONTENT_SECURITY_POLICY,
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "strict-origin-when-cross-origin",
    },
  },
});
