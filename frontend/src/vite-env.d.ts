/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_USE_MOCK: string;
  readonly VITE_MAX_UPLOAD_BYTES?: string;
  /** true: extra console logs for mic/VU/RE-03 while recording (also on in dev). */
  readonly VITE_DEBUG_AUDIO?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
