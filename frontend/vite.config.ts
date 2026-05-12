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
  return 5050
}

const backendPort = getBackendPort()
console.log(`[vite] 后端端口检测: ${backendPort}`)

const frontendPortFile = path.resolve(__dirname, '..', 'backend', '.frontend-port')
const startPort = parseInt(process.env.FRONTEND_PORT || '8088', 10)

export default defineConfig({
    plugins: [
        vue(),
        {
            name: 'write-frontend-port',
            configureServer(server) {
                server.httpServer?.once('listening', () => {
                    const addr = server.httpServer?.address()
                    if (addr && typeof addr === 'object') {
                        fs.writeFileSync(frontendPortFile, String(addr.port))
                        console.log(`[vite] 前端端口已写入: ${addr.port}`)
                    }
                })
            }
        }
    ],
    resolve: {
        alias: {
            '@': path.resolve(__dirname, 'src'),
            'element-plus': path.resolve(__dirname, 'node_modules/element-plus'),
            '@element-plus/icons-vue': path.resolve(__dirname, 'node_modules/@element-plus/icons-vue')
        }
    },
    server: {
        port: startPort,
        strictPort: false,
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