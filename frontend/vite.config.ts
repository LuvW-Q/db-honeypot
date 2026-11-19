import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发环境：Vite dev server 把 /api 代理到本机 FastAPI（127.0.0.1:8000），
// 生产环境：由 FastAPI StaticFiles 托管 dist/，/api 与页面同源，无需 CORS。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false
      }
    }
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true
  }
})
