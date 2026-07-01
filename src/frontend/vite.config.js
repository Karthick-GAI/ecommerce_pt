import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api/users':      { target: 'http://localhost:8000', rewrite: p => p.replace(/^\/api\/users/, '') },
      '/api/products':   { target: 'http://localhost:8001', rewrite: p => p.replace(/^\/api\/products/, '') },
      '/api/assistant':  { target: 'http://localhost:8002', rewrite: p => p.replace(/^\/api\/assistant/, '') },
      '/api/checkout':   { target: 'http://localhost:8003', rewrite: p => p.replace(/^\/api\/checkout/, '') },
      '/api/orders':     { target: 'http://localhost:8004', rewrite: p => p.replace(/^\/api\/orders/, '') },
      '/api/sessions':   { target: 'http://localhost:8008', rewrite: p => p.replace(/^\/api\/sessions/, '') },
      '/api/agent':      { target: 'http://localhost:8007', rewrite: p => p.replace(/^\/api\/agent/, '') },
      '/imgproxy':       { target: 'http://localhost:8001', changeOrigin: false },
    }
  }
})
