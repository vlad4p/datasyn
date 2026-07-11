import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
/**
 * Browser → same-origin `/api` → Vite → this target (must be the **Docker-mapped** brain port).
 * Default `8002` matches `docker-compose.yaml` (`8002:8000`). Override: `VITE_PROXY_TARGET=http://127.0.0.1:8002`.
 */
const proxyTarget = process.env.VITE_PROXY_TARGET || "http://127.0.0.1:8002";
/** Hostnames allowed when accessing Vite via reverse proxy / VPN (Host header check). */
const allowedHosts = ["test-datasyn.vpn.rlab.lat"];
/** Agent turns can exceed default proxy timeouts (LiteLLM + many tool calls). */
const apiProxy = {
    "/api": {
        target: proxyTarget,
        changeOrigin: true,
        timeout: 600_000,
        proxyTimeout: 600_000,
        rewrite: (path) => path.replace(/^\/api/, "") || "/",
    },
};
/** Docker publish: VITE_FAST_BUILD=1 skips minify (~2–3 min faster on large vendor chunks). */
const fastBuild = Boolean(process.env.VITE_FAST_BUILD);
export default defineConfig({
    plugins: [react()],
    build: {
        minify: fastBuild ? false : "esbuild",
        sourcemap: false,
        reportCompressedSize: false,
        chunkSizeWarningLimit: 6000,
        target: "es2022",
        rollupOptions: {
            output: {
                manualChunks(id) {
                    if (!id.includes("node_modules"))
                        return;
                    if (id.includes("plotly"))
                        return "vendor-plotly";
                    if (id.includes("vega"))
                        return "vendor-vega";
                    if (id.includes("react-dom") || id.includes("/react/"))
                        return "vendor-react";
                },
            },
        },
    },
    server: {
        port: 5173,
        strictPort: true,
        allowedHosts,
        proxy: apiProxy,
    },
    preview: {
        port: 4173,
        strictPort: true,
        allowedHosts,
        proxy: apiProxy,
    },
});
