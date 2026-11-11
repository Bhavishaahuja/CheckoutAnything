import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// Who may show this app in an iframe: itself, and the Checkout Anything app (VITE_CONNECT_URL),
// whose review drawer frames the confirm page. Nobody else, so the approve button can't be
// dressed up inside someone else's page. This only covers `vite` and `vite preview`: the hosted
// site is static files, so the same header is set in render.yaml.
function frameAncestors(connectUrl: string | undefined): string {
  let allowed = "'self'"
  if (connectUrl) {
    try {
      allowed += ' ' + new URL(connectUrl).origin
    } catch {
      // not a URL, so only this app itself may frame it
    }
  }
  return 'frame-ancestors ' + allowed
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const headers = { 'Content-Security-Policy': frameAncestors(env.VITE_CONNECT_URL) }
  return {
    // tailwind and the @ alias match the Checkout Anything app (frontend/vite.config.ts)
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { '@': path.resolve(import.meta.dirname, 'src') },
    },
    server: { headers },
    preview: { headers },
  }
})
