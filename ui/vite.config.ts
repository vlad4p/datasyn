import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Browser → same-origin `/api` → Vite → this target (must be the **Docker-mapped** brain port).
 * Default `8002` matches `docker-compose.yaml` (`8002:8000`). Override: `VITE_PROXY_TARGET=http://127.0.0.1:8002`.
 */
const proxyTarget = process.env.VITE_PROXY_TARGET || "http://127.0.0.1:8002";

/** Agent turns can exceed default proxy timeouts (LiteLLM + many tool calls). */
const apiProxy = {
  "/api": {
    target: proxyTarget,
    changeOrigin: true,
    timeout: 600_000,
    proxyTimeout: 600_000,
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
