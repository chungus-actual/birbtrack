import { defineConfig } from "vite";

// `npm run dev` proxies the API to a local backend (serve.py on :8894)
export default defineConfig({
  build: { target: "es2020", assetsInlineLimit: 0, modulePreload: { polyfill: false } },
  server: {
    proxy: { "/api": "http://127.0.0.1:8894", "/media": "http://127.0.0.1:8894" },
  },
});
