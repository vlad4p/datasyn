/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE: string;
  /** Optional override when the DuckDB UI host port is not 4213 (browser cannot read Docker publish mapping). */
  readonly VITE_DUCKDB_UI_URL?: string;
  /** Browser URL for JupyterLab (host port 8888 when using root docker-compose). */
  readonly VITE_JUPYTER_URL?: string;
  /** Optional; if set, appended as `token` query param for embedded Lab (visible in the JS bundle). */
  readonly VITE_JUPYTER_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
