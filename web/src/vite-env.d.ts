/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base path or absolute URL of the REST API (default `/api/v1`, see `web/.env.example`). */
  readonly VITE_API_BASE_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
