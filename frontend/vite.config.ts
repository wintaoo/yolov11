import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import fs from 'fs'

function getBackendPort(): number {
  const portFile = path.resolve(__dirname, '..', 'backend', '.port')
  try {
    const port = parseInt(fs.readFileSync(portFile, 'utf-8').trim(), 10)
    if (port > 0 && port < 65536) return port
  } catch {}
  // 回退：扫描 5000-5009 找到第一个空闲端口（与后端逻辑一致）
  return 5000
}

const backendPort = getBackendPort()
console.log(`[vite] 后端端口检测: ${backendPort}`)

export default defineConfig({
    plugins: [vue()],
    resolve: {
        alias: {
            '@': path.resolve(__dirname, 'src'),
            'element-plus': path.resolve(__dirname, 'node_modules/element-plus'),
            '@element-plus/icons-vue': path.resolve(__dirname, 'node_modules/@element-plus/icons-vue')
        }
    },
    server: {
        port: 8080,
        host: true,
        proxy: {
            '/api': {
                target: `http://localhost:${backendPort}`,
                changeOrigin: true
            }
        }
    },
    optimizeDeps: {
        include: ['element-plus', '@element-plus/icons-vue', 'axios', 'lodash-es']
    }
}) 