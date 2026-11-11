import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  server: {
    port: 3000,
    host: '0.0.0.0',
    proxy: {
      '/v1': { target: process.env.NOVELVIDS_DEV_BACKEND || 'http://127.0.0.1:9000', changeOrigin: true },
      '/api': { target: process.env.NOVELVIDS_DEV_BACKEND || 'http://127.0.0.1:9000', changeOrigin: true },
      '/media': { target: process.env.NOVELVIDS_DEV_BACKEND || 'http://127.0.0.1:9000', changeOrigin: true },
    },
  },
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
})
