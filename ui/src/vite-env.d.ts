/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE: string;
  /** Optional override when the DuckDB UI host port is not 4213 (browser cannot read Docker publish mapping). */
  readonly VITE_DUCKDB_UI_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
