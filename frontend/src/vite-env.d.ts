/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Absolute backend origin. Left unset in development, where the Vite dev
   * server proxies `/api` and `/health` to the backend so the browser only
   * ever sees one origin.
   */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
