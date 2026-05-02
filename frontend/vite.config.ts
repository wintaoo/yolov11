import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

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
                target: 'http://localhost:5000',
                changeOrigin: true
            }
        }
    },
    optimizeDeps: {
        include: ['element-plus', '@element-plus/icons-vue', 'axios', 'lodash-es']
    }
}) 