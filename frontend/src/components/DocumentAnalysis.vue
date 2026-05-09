<template>
  <div class="docx-panel">
    <div class="upload-zone" v-if="!taskId">
      <div class="history-panel" v-if="taskList.length > 0">
        <div class="history-header">
          <div class="history-title">
            <el-icon :size="20"><Clock /></el-icon>
            <span>历史解析记录</span>
            <el-badge :value="taskList.length" class="history-badge" />
          </div>
        </div>
        <div class="history-list">
          <div
            v-for="t in taskList"
            :key="t.task_id"
            class="history-card"
            @click="loadTask(t.task_id)"
          >
            <div class="history-info">
              <div class="history-name" :title="t.original_filename">{{ t.original_filename }}</div>
              <div class="history-meta">
                <el-tag size="small" :type="t.status === 'extracted' ? 'success' : 'info'">已解析</el-tag>
                <span>{{ t.total_images }} 张图片</span>
              </div>
            </div>
            <div class="history-actions" @click.stop>
              <el-button size="small" type="primary" plain @click="loadTask(t.task_id)">
                <el-icon><FolderOpened /></el-icon>
                打开
              </el-button>
              <el-button size="small" type="danger" plain @click="removeTask(t.task_id)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <div class="upload-card">
        <div class="upload-icon">
          <svg viewBox="0 0 64 64" width="64" height="64" fill="none">
            <rect x="10" y="4" width="44" height="56" rx="4" stroke="#c7d2fe" stroke-width="2" fill="#eef2ff"/>
            <line x1="18" y1="18" x2="46" y2="18" stroke="#818cf8" stroke-width="2"/>
            <line x1="18" y1="27" x2="46" y2="27" stroke="#a5b4fc" stroke-width="2"/>
            <line x1="18" y1="36" x2="38" y2="36" stroke="#a5b4fc" stroke-width="2"/>
            <circle cx="48" cy="44" r="8" fill="#6366f1"/>
            <path d="M46 44h4M48 42v4" stroke="white" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </div>
        <h3>上传投标文件进行解析</h3>
        <p>上传 .docx 格式的投标文件，系统将自动提取图片并按规则匹配分类，图片自动存储供布置图检测使用</p>
        <label class="upload-btn">
          <el-icon :size="18"><Upload /></el-icon>
          <span>选择 .docx 文件</span>
          <input type="file" ref="docxInput" accept=".docx" @change="handleUpload" hidden />
        </label>
      </div>
    </div>

    <div class="analysis-container" v-else>
      <div class="status-bar">
        <div class="status-info">
          <span class="task-id">任务 #{{ taskId }}</span>
          <span class="image-count">共 {{ totalImages }} 张图片</span>
        </div>
        <div class="status-actions">
          <el-button size="small" type="danger" plain @click="resetTask">返回列表</el-button>
        </div>
      </div>

      <div class="content-layout">
        <div class="image-grid">
          <div
            v-for="img in images"
            :key="img.index"
            class="image-card"
            :class="{ selected: selectedImg === img.index }"
            @click="selectImage(img)"
          >
            <img :src="`/api/docx/image/${taskId}/${img.filename}`" class="card-img" loading="lazy" />
            <div class="card-info">
              <span class="card-figname" :title="img.figure_name">{{ img.figure_name || '#' + img.index }}</span>
              <span class="card-cat">
                {{ img.guessed_category || '其他' }}
                <span class="card-conf" v-if="img.classification_confidence > 0" :class="confidenceClass(img.classification_confidence)">
                  {{ (img.classification_confidence * 100).toFixed(0) }}%
                </span>
              </span>
            </div>
            <div class="card-page">P{{ img.page_number || 1 }}</div>
          </div>
        </div>

        <aside class="detail-panel" v-if="selectedImage">
          <div class="detail-image">
            <img :src="`/api/docx/image/${taskId}/${selectedImage.filename}`" class="preview-large" />
          </div>
          <div class="detail-info">
            <div class="info-header">
              <div class="info-figname" v-if="selectedImage.figure_name">
                <el-icon :size="16"><Picture /></el-icon>
                <strong>{{ selectedImage.figure_name }}</strong>
              </div>
              <div class="info-meta-row">
                <el-tag :type="getTypeColor(selectedImage.guessed_category)" size="large">
                  {{ selectedImage.guessed_category || '未分类' }}
                </el-tag>
                <el-tag v-if="selectedImage.classification_confidence > 0" :type="confidenceTagType(selectedImage.classification_confidence)" size="large" effect="dark">
                  置信度 {{ (selectedImage.classification_confidence * 100).toFixed(0) }}%
                </el-tag>
                <el-tag type="warning" size="large" effect="plain">
                  <el-icon :size="14" style="margin-right: 4px;"><Document /></el-icon>
                  第 {{ selectedImage.page_number || 1 }} 页
                </el-tag>
              </div>
            </div>
            <div class="info-section" v-if="selectedImage.context">
              <h4>文档上下文</h4>
              <p>{{ selectedImage.context }}</p>
            </div>
          </div>
        </aside>

        <div class="detail-panel empty-detail" v-else-if="!selectedImage">
          <div class="empty-hint">
            <el-icon :size="32"><Picture /></el-icon>
            <span>点击左侧图片查看详情</span>
          </div>
        </div>
      </div>

      <div class="category-summary" v-if="Object.keys(categoryStats).length">
        <h4>图片分类统计（多信号融合匹配）</h4>
        <div class="cat-chips">
          <span v-for="(count, cat) in sortedCategoryStats" :key="cat" class="cat-chip">
            {{ cat }} <strong>{{ count }}</strong>
          </span>
        </div>
        <div class="confidence-summary" v-if="averageConfidence > 0">
          平均分类置信度: <strong :style="{ color: confidenceSummaryColor }">{{ (averageConfidence * 100).toFixed(1) }}%</strong>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Upload, Picture, Clock, FolderOpened, Delete, Document } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

const docxInput = ref<HTMLInputElement | null>(null)
const taskId = ref('')
const totalImages = ref(0)
const images = ref<any[]>([])
const categoryStats = ref<Record<string, number>>({})
const selectedImg = ref<number | null>(null)
const selectedImage = ref<any>(null)
const taskList = ref<any[]>([])

const sortedCategoryStats = computed(() => {
  const entries = Object.entries(categoryStats.value)
  entries.sort((a, b) => b[1] - a[1])
  return Object.fromEntries(entries)
})

const averageConfidence = computed(() => {
  const confs = images.value
    .map(i => i.classification_confidence)
    .filter((c: any) => c !== undefined && c !== null && c > 0)
  if (!confs.length) return 0
  return confs.reduce((a: number, b: number) => a + b, 0) / confs.length
})

const confidenceSummaryColor = computed(() => {
  const avg = averageConfidence.value
  if (avg >= 0.8) return '#16a34a'
  if (avg >= 0.5) return '#d97706'
  return '#dc2626'
})

const confidenceClass = (conf: number) => {
  if (conf >= 0.8) return 'conf-high'
  if (conf >= 0.5) return 'conf-mid'
  return 'conf-low'
}

const confidenceTagType = (conf: number): 'success' | 'warning' | 'danger' => {
  if (conf >= 0.8) return 'success'
  if (conf >= 0.5) return 'warning'
  return 'danger'
}

const getTypeColor = (t: string) => {
  const m: Record<string, string> = {
    '进度计划图': 'warning', '施工计划图': 'warning',
    '总平面布置图': '', '分区规划图': 'success',
    '施工分区图': 'success', '基础结构图': 'info',
    '主体结构图': 'info', '土方工程图': 'danger',
    '临时用电布置图': 'warning', '临时用水布置图': 'warning',
    '临建设施平面布置图': 'info', '装饰装修图': '',
    '周边环境图': 'success',
  }
  return m[t] || 'info'
}

const handleUpload = async (event: Event) => {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  try {
    const res = await axios.post('/api/docx/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    if (res.data.success) {
      if (res.data.reused) {
        ElMessageBox.confirm(
          '检测到重复文件，是否打开历史解析记录？',
          '检测到重复文件',
          { confirmButtonText: '打开历史结果', cancelButtonText: '取消', type: 'info' }
        ).then(() => {
          openTask(res.data)
        }).catch(() => {})
      } else {
        openTask(res.data)
      }
    } else {
      ElMessage.error(res.data.error || '解析失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '上传失败')
  } finally {
    if (docxInput.value) docxInput.value.value = ''
  }
}

const openTask = (data: any) => {
  taskId.value = data.task_id
  totalImages.value = data.total_images
  images.value = data.images
  categoryStats.value = data.category_stats || {}
  if (data.reused) {
    ElMessage.success(`已加载历史解析记录，共 ${data.total_images} 张图片`)
  } else {
    ElMessage.success(`投标文件解析完成，共提取 ${data.total_images} 张图片，已自动存储`)
  }
}

const selectImage = (img: any) => {
  selectedImg.value = img.index
  selectedImage.value = img
}

const resetTask = () => {
  taskId.value = ''
  images.value = []
  categoryStats.value = {}
  selectedImg.value = null
  selectedImage.value = null
  totalImages.value = 0
  fetchTasks()
}

const fetchTasks = async () => {
  try {
    const res = await axios.get('/api/docx/tasks')
    if (res.data.success) {
      taskList.value = res.data.tasks || []
    }
  } catch {}
}

const loadTask = async (tid: string) => {
  try {
    const res = await axios.post(`/api/docx/task/${tid}/load`)
    if (res.data.success) {
      taskId.value = res.data.task_id
      totalImages.value = res.data.total_images
      images.value = res.data.images
      categoryStats.value = res.data.category_stats || {}
      ElMessage.success(`已加载历史记录，共 ${res.data.total_images} 张图片`)
    } else {
      ElMessage.error(res.data.error || '加载失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '加载失败')
  }
}

const removeTask = async (tid: string) => {
  try {
    await ElMessageBox.confirm('确定要删除此解析记录吗？', '确认删除', {
      confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning'
    })
    await axios.delete(`/api/docx/task/${tid}`)
    taskList.value = taskList.value.filter(t => t.task_id !== tid)
    ElMessage.success('记录已删除')
  } catch {
    // user cancelled or error
  }
}

onMounted(() => {
  fetchTasks()
})
</script>

<style scoped>
.docx-panel { display: flex; flex-direction: column; gap: 16px; }

.upload-zone { display: flex; flex-direction: column; align-items: center; gap: 24px; padding: 24px 0; }

.history-panel { width: 100%; max-width: 600px; }
.history-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.history-title { display: flex; align-items: center; gap: 8px; color: #1e293b; font-size: 15px; font-weight: 700; }
.history-badge { margin-left: 4px; }
.history-list { display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow-y: auto; }
.history-card {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  background: white; border-radius: 10px; padding: 14px 18px;
  box-shadow: 0 1px 3px rgba(0,0,0,.05); border: 1px solid #f1f5f9;
  transition: all .15s; cursor: pointer;
}
.history-card:hover { border-color: #c7d2fe; background: #fafafe; }
.history-info { flex: 1; min-width: 0; }
.history-name { font-size: 14px; font-weight: 600; color: #1e293b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-meta { display: flex; gap: 10px; align-items: center; margin-top: 5px; font-size: 12px; color: #94a3b8; flex-wrap: wrap; }
.history-actions { display: flex; gap: 6px; flex-shrink: 0; }

.upload-card {
  text-align: center; background: white; border-radius: 16px; padding: 48px 40px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06); max-width: 480px; width: 100%;
}
.upload-card h3 { margin: 16px 0 8px; font-size: 18px; color: #1e293b; }
.upload-card p { color: #94a3b8; font-size: 14px; margin-bottom: 24px; line-height: 1.6; }
.upload-btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 12px 28px; background: #6366f1; color: white; border-radius: 10px;
  font-size: 15px; font-weight: 600; cursor: pointer; transition: all .2s;
  box-shadow: 0 4px 14px rgba(99,102,241,.35);
}
.upload-btn:hover { background: #4f46e5; transform: translateY(-1px); }

.status-bar {
  display: flex; align-items: center; justify-content: space-between;
  background: white; border-radius: 10px; padding: 12px 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06);
}
.status-info { display: flex; gap: 16px; align-items: center; }
.task-id { font-weight: 700; color: #6366f1; font-family: monospace; }
.image-count { color: #64748b; font-size: 14px; }
.status-actions { display: flex; gap: 8px; }

.content-layout { display: flex; gap: 16px; min-height: 500px; }

.image-grid {
  flex: 1; display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px; align-content: start; min-width: 0; max-height: 600px; overflow-y: auto;
  background: white; border-radius: 12px; padding: 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06);
}
.image-card {
  border-radius: 8px; overflow: hidden; cursor: pointer; transition: all .15s;
  border: 2px solid transparent; background: #f8fafc; position: relative;
}
.image-card:hover { border-color: #c7d2fe; }
.image-card.selected { border-color: #6366f1; box-shadow: 0 0 0 2px rgba(99,102,241,.2); }
.card-img { width: 100%; aspect-ratio: 4/3; object-fit: cover; display: block; }
.card-info { display: flex; justify-content: space-between; padding: 6px 8px; font-size: 11px; }
.card-figname { color: #1e293b; font-weight: 600; font-size: 10px; max-width: 70px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-cat { color: #6366f1; font-weight: 500; font-size: 10px; max-width: 55px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: flex; flex-direction: column; gap: 1px; }
.card-conf { font-size: 9px; font-weight: 700; }
.card-conf.conf-high { color: #16a34a; }
.card-conf.conf-mid { color: #d97706; }
.card-conf.conf-low { color: #dc2626; }
.card-page { position: absolute; bottom: 4px; right: 4px; font-size: 9px; color: #94a3b8; background: #f1f5f9; padding: 1px 5px; border-radius: 3px; font-weight: 600; }

.detail-panel {
  width: 400px; flex-shrink: 0; background: white; border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06); overflow-y: auto; max-height: 600px;
}
.empty-detail { display: flex; align-items: center; justify-content: center; }
.empty-hint { display: flex; flex-direction: column; align-items: center; gap: 12px; color: #94a3b8; font-size: 14px; padding: 40px 20px; text-align: center; }

.detail-image { padding: 12px; }
.preview-large { width: 100%; border-radius: 8px; }
.detail-info { padding: 0 16px 16px; }
.info-header { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; margin-top: 12px; }
.info-figname { display: flex; align-items: center; gap: 6px; color: #1e293b; font-size: 15px; padding: 8px 12px; background: #f1f5f9; border-radius: 8px; }
.info-meta-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.info-section { margin-bottom: 16px; }
.info-section h4 { font-size: 12px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
.info-section p { font-size: 13px; color: #334155; line-height: 1.7; }

.category-summary { background: white; border-radius: 12px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.category-summary h4 { font-size: 13px; margin-bottom: 10px; color: #475569; }
.cat-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.cat-chip { padding: 4px 12px; border-radius: 14px; font-size: 13px; background: #f1f5f9; color: #475569; }
.cat-chip strong { color: #1e293b; margin-left: 2px; }
.confidence-summary { margin-top: 10px; font-size: 13px; color: #64748b; }
</style>
