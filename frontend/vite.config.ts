import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': 'http://localhost:9002',
      '/ws': { target: 'ws://localhost:9002', ws: true },
    },
  },
})
