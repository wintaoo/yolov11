<template>
  <div class="docx-panel">
    <div class="upload-zone" v-if="!taskId">
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
        <h3>上传 Word 文档分析</h3>
        <p>上传 .docx 格式的施工方案文档，系统将自动提取图片并使用 AI 进行智能分析</p>
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
          <span class="image-count">共 {{ totalImages }} 张</span>
        </div>
        <div class="status-actions">
          <el-button
            size="small"
            type="primary"
            @click="startBatchAnalysis"
            :loading="batchRunning"
            :disabled="batchRunning"
          >
            <el-icon><VideoPlay /></el-icon>
            批量分析全部
          </el-button>
          <el-button size="small" type="danger" plain @click="resetTask">重新上传</el-button>
        </div>
      </div>

      <el-progress
        v-if="batchRunning"
        :percentage="batchPercent"
        :status="batchStatus === 'summarizing' ? 'success' : ''"
        :stroke-width="8"
        style="margin-bottom: 12px;"
      />

      <div class="content-layout">
        <div class="image-grid">
          <div
            v-for="img in images"
            :key="img.index"
            class="image-card"
            :class="{ selected: selectedImg === img.index, analyzed: resultMap[img.index] }"
            @click="selectImage(img)"
          >
            <img :src="`/api/docx/image/${taskId}/${img.filename}`" class="card-img" loading="lazy" />
            <div class="card-info">
              <span class="card-idx">#{{ img.index }}</span>
              <span class="card-cat">{{ resultMap[img.index]?.image_type || img.guessed_category || '-' }}</span>
            </div>
            <div class="card-badge" v-if="resultMap[img.index]">
              <el-icon><Check /></el-icon>
            </div>
          </div>
        </div>

        <aside class="detail-panel" v-if="selectedImage">
          <div class="detail-image">
            <img :src="`/api/docx/image/${taskId}/${selectedImage.filename}`" class="preview-large" />
          </div>

          <div class="detail-actions">
            <el-button
              type="primary"
              size="small"
              @click="analyzeCurrentImage"
              :loading="analyzingSingle"
            >
              <el-icon><VideoPlay /></el-icon>
              {{ resultMap[selectedImage.index] ? '重新分析' : 'AI 分析此图' }}
            </el-button>
          </div>

          <div class="detail-info" v-if="selectedResult">
            <div class="info-header">
              <el-tag :type="getTypeColor(selectedResult.image_type)" size="large">
                {{ selectedResult.image_type || '未分类' }}
              </el-tag>
            </div>

            <div class="info-section summary-section" v-if="selectedResult.summary">
              <h4>AI 摘要</h4>
              <p>{{ selectedResult.summary }}</p>
            </div>

            <div class="info-section" v-if="selectedResult.evaluation">
              <h4>AI 评估</h4>
              <div class="evaluation-box" :class="'eval-' + getEvalLevel(selectedResult.evaluation)">
                <el-tag :type="getEvalTagColor(getEvalLevel(selectedResult.evaluation))" size="large" effect="dark">
                  {{ getEvalLevel(selectedResult.evaluation) }}
                </el-tag>
                <p>{{ selectedResult.evaluation }}</p>
              </div>
            </div>

            <div class="info-section" v-if="selectedResult.construction_schedule?.has_schedule">
              <h4>施工计划</h4>
              <p v-if="selectedResult.construction_schedule.start_date">
                工期：{{ selectedResult.construction_schedule.start_date }} ~ {{ selectedResult.construction_schedule.end_date }}
              </p>
              <div v-for="(t, i) in selectedResult.construction_schedule.tasks" :key="i" class="task-item">
                <span class="task-name">{{ t.name }}</span>
                <span class="task-time">{{ t.start }} ~ {{ t.end }} ({{ t.duration }})</span>
              </div>
            </div>

            <div class="info-section" v-if="selectedResult.dimensions_specs?.found">
              <h4>尺寸规格</h4>
              <div v-for="(s, i) in selectedResult.dimensions_specs.items" :key="i" class="spec-item">
                <strong>{{ s.name }}</strong>
                <span v-if="s.dimension">尺寸: {{ s.dimension }}</span>
                <span v-if="s.model">型号: {{ s.model }}</span>
                <span v-if="s.quantity">数量: {{ s.quantity }}</span>
              </div>
            </div>
          </div>

          <div class="detail-info" v-else-if="!analyzingSingle && !batchRunning">
            <div class="empty-hint">
              <el-icon :size="24"><Picture /></el-icon>
              <span>点击上方"AI 分析此图"按钮开始分析</span>
            </div>
          </div>
        </aside>

        <div class="detail-panel empty-detail" v-else-if="!selectedImage">
          <div class="empty-hint">
            <el-icon :size="32"><Picture /></el-icon>
            <span>点击左侧图片查看详情和分析</span>
          </div>
        </div>
      </div>

      <div class="batch-summary" v-if="batchSummary">
        <div class="summary-header">
          <el-icon :size="20"><Trophy /></el-icon>
          <h3>智能汇总报告</h3>
        </div>
        <div class="summary-content" v-html="batchSummaryHtml"></div>
      </div>

      <div class="category-summary" v-if="Object.keys(categoryStats).length">
        <h4>图片分类统计</h4>
        <div class="cat-chips">
          <span v-for="(count, cat) in categoryStats" :key="cat" class="cat-chip">
            {{ cat }} <strong>{{ count }}</strong>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { Upload, Picture, VideoPlay, Check, Trophy } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'

const docxInput = ref<HTMLInputElement | null>(null)
const taskId = ref('')
const totalImages = ref(0)
const images = ref<any[]>([])
const resultMap = ref<Record<number, any>>({})
const imageCategories = ref<Record<number, string>>({})
const categoryStats = ref<Record<string, number>>({})
const batchRunning = ref(false)
const batchPercent = ref(0)
const batchStatus = ref('')
const batchSummary = ref('')
const selectedImg = ref<number | null>(null)
const selectedImage = ref<any>(null)
const analyzingSingle = ref(false)
const pollTimer = ref<number | null>(null)

const selectedResult = computed(() => {
  if (!selectedImg.value) return null
  return resultMap.value[selectedImg.value] || null
})

const batchSummaryHtml = computed(() => batchSummary.value.replace(/\n/g, '<br>'))

const getTypeColor = (t: string) => {
  const m: Record<string, string> = { '进度计划图': 'warning', '施工计划图': 'warning', '总平面布置图': '', '分区规划图': 'success' }
  return m[t] || 'info'
}

const getEvalLevel = (text: string) => {
  if (/优/.test(text)) return '优'
  if (/良/.test(text)) return '良'
  if (/差/.test(text)) return '差'
  return '中'
}

const getEvalTagColor = (level: string): 'success'|'warning'|'danger'|'info' => {
  if (level === '优') return 'success'
  if (level === '良') return 'warning'
  if (level === '差') return 'danger'
  return 'info'
}

const handleUpload = async (event: Event) => {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  try {
    const res = await axios.post('/api/docx/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    if (res.data.success) {
      taskId.value = res.data.task_id
      totalImages.value = res.data.total_images
      images.value = res.data.images
      resultMap.value = {}
      const cats: Record<number, string> = {}
      for (const img of (res.data.images || [])) {
        cats[img.index] = img.guessed_category || '其他'
      }
      imageCategories.value = cats
      categoryStats.value = res.data.category_guess || {}
      batchSummary.value = ''
      ElMessage.success(`文档解析完成，共提取 ${res.data.total_images} 张图片`)
    } else {
      ElMessage.error(res.data.error || '解析失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '上传失败')
  }
}

const selectImage = (img: any) => {
  selectedImg.value = img.index
  selectedImage.value = img
}

const analyzeCurrentImage = async () => {
  if (!selectedImg.value) return
  analyzingSingle.value = true
  try {
    const res = await axios.post(`/api/docx/analyze-single/${taskId.value}/${selectedImg.value}`)
    if (res.data.success) {
      resultMap.value[selectedImg.value] = res.data.result
      imageCategories.value[selectedImg.value] = res.data.result.image_type || '其他'
      updateCategoryStats()
      ElMessage.success('分析完成')
    } else {
      ElMessage.error(res.data.error || '分析失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '分析失败')
  } finally {
    analyzingSingle.value = false
  }
}

const updateCategoryStats = () => {
  const stats: Record<string, number> = {}
  for (const [, cat] of Object.entries(imageCategories.value)) {
    const c = (cat as string) || '其他'
    stats[c] = (stats[c] || 0) + 1
  }
  categoryStats.value = stats
}

const startBatchAnalysis = async () => {
  if (!taskId.value || batchRunning.value) return
  try {
    const res = await axios.post(`/api/docx/analyze/${taskId.value}`)
    if (res.data.success) {
      batchRunning.value = true
      batchPercent.value = 0
      ElMessage.info(`批量分析已启动，共 ${res.data.total} 张图片`)
      startPolling()
    }
  } catch (err: any) {
    ElMessage.error(err.message || '启动失败')
  }
}

const startPolling = () => {
  if (pollTimer.value) clearInterval(pollTimer.value)
  pollTimer.value = window.setInterval(async () => {
    try {
      const res = await axios.get(`/api/docx/status/${taskId.value}`)
      if (res.data.batch_running) {
        batchPercent.value = Math.round((res.data.batch_progress / res.data.batch_total) * 100)
        const fres = res.data.results || {}
        Object.entries(fres).forEach(([k, v]: [string, any]) => {
          resultMap.value[parseInt(k)] = v
          imageCategories.value[parseInt(k)] = v.image_type || '其他'
        })
        updateCategoryStats()
        batchStatus.value = res.data.batch_status || ''
      } else if (res.data.batch_summary) {
        batchSummary.value = res.data.batch_summary
        batchRunning.value = false
        batchPercent.value = 100
        const fres = res.data.results || {}
        Object.entries(fres).forEach(([k, v]: [string, any]) => {
          resultMap.value[parseInt(k)] = v
          imageCategories.value[parseInt(k)] = v.image_type || '其他'
        })
        updateCategoryStats()
        if (pollTimer.value) clearInterval(pollTimer.value)
        ElMessage.success('批量分析完成！')
      }
    } catch {}
  }, 2000)
}

const resetTask = () => {
  if (pollTimer.value) clearInterval(pollTimer.value)
  taskId.value = ''
  images.value = []
  resultMap.value = {}
  imageCategories.value = {}
  categoryStats.value = {}
  batchRunning.value = false
  batchPercent.value = 0
  batchSummary.value = ''
  selectedImg.value = null
  selectedImage.value = null
}

onUnmounted(() => {
  if (pollTimer.value) clearInterval(pollTimer.value)
})
</script>

<style scoped>
.docx-panel { display: flex; flex-direction: column; gap: 16px; }

.upload-zone { display: flex; justify-content: center; padding: 40px 0; }
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
.image-card.analyzed { border-color: #22c55e; }
.image-card.analyzed::after { content: ''; position: absolute; inset: 0; background: rgba(34,197,94,.06); pointer-events: none; }
.card-img { width: 100%; aspect-ratio: 4/3; object-fit: cover; display: block; }
.card-info { display: flex; justify-content: space-between; padding: 6px 8px; font-size: 11px; }
.card-idx { color: #94a3b8; }
.card-cat { color: #6366f1; font-weight: 600; max-width: 70px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-badge { position: absolute; top: 6px; right: 6px; width: 20px; height: 20px; background: #22c55e; color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; }

.detail-panel {
  width: 400px; flex-shrink: 0; background: white; border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06); overflow-y: auto; max-height: 600px;
}
.empty-detail { display: flex; align-items: center; justify-content: center; }
.empty-hint { display: flex; flex-direction: column; align-items: center; gap: 12px; color: #94a3b8; font-size: 14px; padding: 40px 20px; text-align: center; }

.detail-image { padding: 12px; }
.preview-large { width: 100%; border-radius: 8px; }
.detail-actions { padding: 8px 16px; border-bottom: 1px solid #f1f5f9; }
.detail-info { padding: 0 16px 16px; }
.info-header { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; margin-top: 12px; }
.info-ctx { font-size: 12px; color: #64748b; line-height: 1.5; }
.info-section { margin-bottom: 16px; }
.info-section h4 { font-size: 12px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
.info-section p { font-size: 13px; color: #334155; line-height: 1.7; }
.summary-section { background: #f8fafc; padding: 12px 14px; border-radius: 10px; border: 1px solid #e2e8f0; }
.summary-section h4 { color: #6366f1; }

.evaluation-box { display: flex; flex-direction: column; gap: 8px; padding: 12px; border-radius: 10px; border-left: 4px solid #94a3b8; background: #f8fafc; }
.evaluation-box.eval-优 { border-left-color: #22c55e; background: #f0fdf4; }
.evaluation-box.eval-良 { border-left-color: #f59e0b; background: #fffbeb; }
.evaluation-box.eval-中 { border-left-color: #6366f1; background: #eef2ff; }
.evaluation-box.eval-差 { border-left-color: #ef4444; background: #fef2f2; }
.evaluation-box p { font-size: 13px; color: #334155; line-height: 1.7; margin-top: 4px; }

.task-item { display: flex; gap: 8px; padding: 4px 0; font-size: 12px; border-bottom: 1px solid #f1f5f9; align-items: center; }
.task-name { flex: 1; font-weight: 500; color: #334155; }
.task-time { color: #6366f1; font-size: 11px; }
.spec-item { display: flex; flex-wrap: wrap; gap: 6px; padding: 4px 0; font-size: 12px; color: #475569; }

.batch-summary { background: white; border-radius: 12px; padding: 20px 24px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.summary-header { display: flex; align-items: center; gap: 10px; color: #6366f1; margin-bottom: 14px; }
.summary-header h3 { font-size: 16px; color: #1e293b; }
.summary-content { font-size: 14px; line-height: 1.9; color: #334155; }

.category-summary { background: white; border-radius: 12px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.category-summary h4 { font-size: 13px; margin-bottom: 10px; color: #475569; }
.cat-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.cat-chip { padding: 4px 12px; border-radius: 14px; font-size: 13px; background: #f1f5f9; color: #475569; }
.cat-chip strong { color: #1e293b; margin-left: 2px; }
</style>
