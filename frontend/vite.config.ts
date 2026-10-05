import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { securityHeaders } from "./security-headers.js";

// Security headers live in security-headers.js, shared with the production server (server.mjs).
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
    headers: securityHeaders(),
  },
});
