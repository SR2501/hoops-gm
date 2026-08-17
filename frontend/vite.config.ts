/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'

// ADR-001 is a host-binding rule, not a container rule. The dev server binds
// loopback by default; DEV_SERVER_HOST is overridden to 0.0.0.0 only inside a
// container, where the published port is what restricts access (see
// docker-compose.yml).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000'
  const host = env.DEV_SERVER_HOST ?? '127.0.0.1'

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host,
      port: 5173,
      strictPort: true,
      // Proxying means the browser only ever talks to one origin, so CORS is
      // not part of the development path. The backend still sets CORS headers
      // for anyone who runs the two apps separately.
      proxy: {
        '/api': { target: proxyTarget, changeOrigin: false },
        '/health': { target: proxyTarget, changeOrigin: false },
      },
    },
    preview: { host, port: 4173, strictPort: true },
    build: { outDir: 'dist', sourcemap: true },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      css: false,
      include: ['src/**/*.{test,spec}.{ts,tsx}'],
    },
  }
})
