/// <reference types="vite/client" />

interface ImportMetaEnv {
  // where the Leash API lives, e.g. http://127.0.0.1:8000 or the Render URL
  readonly VITE_API_URL?: string
  // "false" to call the real API, anything else (or unset) uses mock data
  readonly VITE_USE_MOCKS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
