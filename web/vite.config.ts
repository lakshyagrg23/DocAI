/// <reference types="vitest" />
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'

// Dev: the Vite server proxies /api to FastAPI (uvicorn api.main:app --port 8000).
// Prod: `npm run build` writes web/dist, which FastAPI serves.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { port: 5173, proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } } },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test-setup.ts'], css: false },
})
