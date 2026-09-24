import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5199,
    host: true,
    proxy: {
      '/api': 'http://localhost:9003',
      '/ws': { target: 'ws://localhost:9003', ws: true },
    },
  },
})
