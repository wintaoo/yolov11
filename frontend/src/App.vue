<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="header-inner">
        <div class="brand">
          <img src="/seu.svg" alt="SEU" class="brand-logo" />
          <div class="brand-info">
            <span class="brand-text">海南机器管招投标项目 2026</span>
            <span class="brand-sub">投标文件解析与布置图检测系统</span>
          </div>
        </div>
        <div class="header-status">
          <span class="status-dot" :class="modelReady ? 'online' : 'offline'"></span>
          <span class="status-text">{{ modelReady ? '模型就绪' : '模型加载中' }}</span>
        </div>
      </div>
    </header>
    <div class="ai-disclaimer">
      <span>本系统使用CV模型进行目标检测，图片分类基于规则匹配，结果仅供参考，请仔细甄别。</span>
    </div>
    <main class="app-main">
      <div class="main-tabs">
        <button :class="{ active: activeTab === 'docx' }" @click="activeTab = 'docx'">
          <el-icon><Document /></el-icon>
          投标文件解析
        </button>
        <button :class="{ active: activeTab === 'detect' }" @click="activeTab = 'detect'">
          <el-icon><Picture /></el-icon>
          布置图检测
        </button>
      </div>
      <DocumentAnalysis v-if="activeTab === 'docx'" />
      <DetectionPanel v-if="activeTab === 'detect'" />
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Picture, Document } from '@element-plus/icons-vue'
import DetectionPanel from './components/DetectionPanel.vue'
import DocumentAnalysis from './components/DocumentAnalysis.vue'

const modelReady = ref(false)
const activeTab = ref('docx')

onMounted(async () => {
  try {
    const axios = (await import('axios')).default
    const res = await axios.get('/api/detection/model/status')
    modelReady.value = res.data?.loaded || false
  } catch {}
})
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  background: #f0f2f5;
  color: #1f2937;
  -webkit-font-smoothing: antialiased;
}

.app-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  background: linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #3730a3 100%);
  color: white;
  box-shadow: 0 1px 3px rgba(0,0,0,.12), 0 1px 2px rgba(0,0,0,.08);
  position: sticky;
  top: 0;
  z-index: 100;
}

.header-inner {
  max-width: 1440px;
  margin: 0 auto;
  padding: 0 24px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.brand {
  display: flex;
  align-items: center;
  gap: 14px;
}

.brand-logo {
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  border-radius: 10px;
}

.brand-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.brand-text {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.5px;
  line-height: 1.3;
}

.brand-sub {
  font-size: 13px;
  font-weight: 400;
  opacity: 0.75;
  letter-spacing: 0.5px;
}

.header-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  opacity: 0.85;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
}

.status-dot.online {
  background: #34d399;
  box-shadow: 0 0 6px #34d39980;
}

.status-dot.offline {
  background: #fbbf24;
  box-shadow: 0 0 6px #fbbf2480;
}

.ai-disclaimer {
  text-align: center;
  padding: 6px 16px;
  background: #fff7ed;
  border-bottom: 1px solid #fed7aa;
  color: #c2410c;
  font-size: 12px;
  letter-spacing: 0.3px;
}

.app-main {
  flex: 1;
  padding: 20px 24px 32px;
  max-width: 1440px;
  margin: 0 auto;
  width: 100%;
}

.main-tabs {
  display: flex; gap: 4px; margin-bottom: 20px;
  background: #e2e8f0; border-radius: 10px; padding: 4px;
  width: fit-content;
}
.main-tabs button {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 20px; border: none; background: transparent; border-radius: 8px;
  font-size: 14px; font-weight: 500; color: #64748b; cursor: pointer;
  transition: all .15s;
}
.main-tabs button.active { background: white; color: #4f46e5; font-weight: 600; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
</style>
