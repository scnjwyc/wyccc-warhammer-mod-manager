import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: './',
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
  },
  build: {
    target: 'chrome120',
    sourcemap: false,
  },
})
