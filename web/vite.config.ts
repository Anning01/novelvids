import { fileURLToPath, URL } from 'node:url'
import { readFileSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const release = JSON.parse(readFileSync(new URL('../release.json', import.meta.url), 'utf8'))
const build = randomUUID()
export default defineConfig({
  define: { 'import.meta.env.VITE_STUDIO_BUILD': JSON.stringify(build) },
  // Shared icons otherwise become dozens of tiny requests when opening the canvas.
  build: {
    rolldownOptions: {
      output: { codeSplitting: { groups: [{ name: 'shared-icons', test: /[/\\]lucide-vue-next[/\\]/, minShareCount: 2 }] } },
    },
  },
  server: {
    port: 3000,
    host: '0.0.0.0',
    proxy: {
      '/v1': { target: process.env.NOVELVIDS_DEV_BACKEND || 'http://127.0.0.1:9000', changeOrigin: true },
      '/api': { target: process.env.NOVELVIDS_DEV_BACKEND || 'http://127.0.0.1:9000', changeOrigin: true },
      '/media': { target: process.env.NOVELVIDS_DEV_BACKEND || 'http://127.0.0.1:9000', changeOrigin: true },
    },
  },
  plugins: [vue(), { name: 'studio-release', generateBundle() {
    this.emitFile({ type: 'asset', fileName: 'studio-build.json', source: JSON.stringify({ version: release.version, build }) })
  } }],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
})
