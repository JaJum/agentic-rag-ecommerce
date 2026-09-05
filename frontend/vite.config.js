// Vite 配置：Vue 插件 + /api 代理到 FastAPI（开发期免 CORS）
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 前端请求 /api/v1/* → 转发到后端 8000
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
})
