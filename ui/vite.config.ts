import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** Default: `src/api.ts` uses same-origin `/api`; dev and preview proxy that to the brain. */
const proxyTarget = process.env.VITE_PROXY_TARGET || "http://127.0.0.1:8000";

const apiProxy = {
  "/api": {
    target: proxyTarget,
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api/, "") || "/",
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: apiProxy,
  },
  preview: {
    port: 4173,
    strictPort: true,
    proxy: apiProxy,
  },
});
