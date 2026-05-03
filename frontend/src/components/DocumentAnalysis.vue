<template>
  <div class="docx-panel">
    <div class="upload-zone" v-if="!taskId">
      <div class="history-panel" v-if="taskList.length > 0">
        <div class="history-header">
          <div class="history-title">
            <el-icon :size="20"><Clock /></el-icon>
            <span>历史分析记录</span>
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
                <el-tag size="small" :type="statusTagType(t.status)">{{ statusLabel(t) }}</el-tag>
                <span>{{ t.total_images }} 张图片</span>
                <span v-if="t.result_count > 0">{{ t.result_count }} 张已分析</span>
                <span v-if="t.has_report" class="report-badge">分析报告</span>
                <span v-if="t.has_summary" class="summary-badge">已汇总</span>
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
          <el-tag v-if="analyzedCount > 0" size="small" type="success">已分析 {{ analyzedCount }}</el-tag>
          <el-tag v-if="pendingCount > 0" size="small" type="warning">待分析 {{ pendingCount }}</el-tag>
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
            {{ analyzedCount > 0 ? '继续批量分析' : '批量分析全部' }}
          </el-button>
          <el-button size="small" type="danger" plain @click="resetTask">返回列表</el-button>
        </div>
      </div>

      <el-progress
        v-if="batchRunning"
        :percentage="batchPercent"
        :status="batchErrorCount > 0 ? 'warning' : (batchStatus === 'summarizing' ? 'success' : '')"
        :stroke-width="8"
        style="margin-bottom: 12px;"
      >
        <template #default v-if="batchErrorCount > 0">
          {{ batchPercent }}% ({{ batchErrorCount }} 张异常)
        </template>
      </el-progress>

      <div v-if="errorImageCount > 0" class="error-banner">
        <el-icon><WarningFilled /></el-icon>
        <span>AI分析未完成（网络连接异常），建议重新分析或人工审核。</span>
      </div>

      <div class="content-layout">
        <div class="image-grid">
          <div
            v-for="img in images"
            :key="img.index"
            class="image-card"
            :class="{
              selected: selectedImg === img.index,
              analyzed: resultMap[img.index] && !resultMap[img.index]._error,
              'status-analyzing': statusMap[img.index] === 'analyzing',
              'status-error': resultMap[img.index]?._error,
            }"
            @click="selectImage(img)"
          >
            <img :src="`/api/docx/image/${taskId}/${img.filename}`" class="card-img" loading="lazy" />
            <div class="card-info">
              <span class="card-idx">#{{ img.index }}</span>
              <span class="card-cat">{{ resultMap[img.index]?.image_type || img.guessed_category || '-' }}</span>
            </div>
            <div class="card-status" v-if="statusMap[img.index] === 'analyzing'">
              <div class="status-spinner"></div>
            </div>
            <div class="card-status-dot" :class="'dot-' + (statusMap[img.index] || 'waiting')"></div>
            <div class="card-badge" v-if="resultMap[img.index] && !resultMap[img.index]._error">
              <el-icon><Check /></el-icon>
            </div>
            <div class="card-badge card-badge-error" v-if="resultMap[img.index]?._error">
              <el-icon><WarningFilled /></el-icon>
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
            <span v-if="resultMap[selectedImage.index]?._error" class="error-hint">AI分析未完成（网络连接异常），建议重新分析或人工审核。</span>
          </div>

          <div class="detail-info" v-if="selectedResult">
            <div class="info-header">
              <el-tag :type="getTypeColor(selectedResult.image_type)" size="large">
                {{ selectedResult.image_type || '未分类' }}
              </el-tag>
              <el-tag v-if="selectedResult._error" type="danger" size="small" effect="dark">
                分析异常
              </el-tag>
            </div>

            <div class="info-section summary-section" v-if="selectedResult.summary">
              <h4>AI 摘要</h4>
              <p>{{ selectedResult.summary }}</p>
            </div>
            <div class="info-section summary-section" v-else>
              <h4>AI 摘要</h4>
              <p class="no-data">未获取到摘要信息，请重新分析</p>
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
          <div class="summary-header-left">
            <el-icon :size="20"><Trophy /></el-icon>
            <h3>智能汇总报告</h3>
          </div>
          <el-button size="small" type="primary" plain @click="exportPdf">
            <el-icon><Printer /></el-icon>
            导出PDF
          </el-button>
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Upload, Picture, VideoPlay, Check, Trophy, Clock, FolderOpened, Delete, WarningFilled, Printer } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { marked } from 'marked'

marked.setOptions({
  breaks: true,
  gfm: true,
})

const docxInput = ref<HTMLInputElement | null>(null)
const taskId = ref('')
const totalImages = ref(0)
const analyzedCount = ref(0)
const images = ref<any[]>([])
const resultMap = ref<Record<number, any>>({})
const imageCategories = ref<Record<number, string>>({})
const categoryStats = ref<Record<string, number>>({})
const batchRunning = ref(false)
const batchPercent = ref(0)
const batchStatus = ref('')
const batchErrorCount = ref(0)
const batchSummary = ref('')
const selectedImg = ref<number | null>(null)
const selectedImage = ref<any>(null)
const analyzingSingle = ref(false)
const pollTimer = ref<number | null>(null)
const eventSource = ref<EventSource | null>(null)
const taskList = ref<any[]>([])
const statusMap = ref<Record<number, string>>({})

const selectedResult = computed(() => {
  if (!selectedImg.value) return null
  return resultMap.value[selectedImg.value] || null
})

const errorImageCount = computed(() => {
  return Object.values(resultMap.value).filter((r: any) => r._error).length
})

const pendingCount = computed(() => {
  return images.value.filter(img => {
    const r = resultMap.value[img.index]
    return !r || r._error
  }).length
})

const batchSummaryHtml = computed(() => {
  try {
    return marked.parse(batchSummary.value) as string
  } catch {
    return batchSummary.value.replace(/\n/g, '<br>')
  }
})

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

const statusTagType = (s: string): 'success'|'warning'|'danger'|'info' => {
  if (s === 'completed') return 'success'
  if (s === 'analyzing') return 'warning'
  if (s === 'error') return 'danger'
  return 'info'
}

const statusLabel = (t: any) => {
  const s = t.status
  if (s === 'completed') return '已完成'
  if (s === 'analyzing') return '进行中'
  if (s === 'error') return '异常'
  if (t.result_count > 0) return `部分完成(${t.result_count}/${t.total_images})`
  return '待分析'
}

const populateResults = (results: Record<string, any>, images: any[]) => {
  const cats: Record<number, string> = {}
  const sm: Record<number, string> = {}
  for (const img of images) {
    cats[img.index] = img.guessed_category || '其他'
  }
  Object.entries(results).forEach(([k, v]: [string, any]) => {
    const idx = parseInt(k)
    resultMap.value[idx] = v
    cats[idx] = v.image_type || cats[idx] || '其他'
    sm[idx] = v._error ? 'error' : 'done'
  })
  // Set waiting status for unanalyzed images
  for (const img of images) {
    if (!(img.index in sm)) {
      sm[img.index] = 'waiting'
    }
  }
  statusMap.value = sm
  imageCategories.value = cats
  updateCategoryStats()
  analyzedCount.value = Object.keys(results).length
}

const updateCategoryStats = () => {
  const stats: Record<string, number> = {}
  for (const [, cat] of Object.entries(imageCategories.value)) {
    const c = (cat as string) || '其他'
    stats[c] = (stats[c] || 0) + 1
  }
  categoryStats.value = stats
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
          res.data.reuse_hint + '，是否打开该历史任务？',
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
  resultMap.value = {}
  populateResults(data.results || {}, data.images || [])
  batchSummary.value = data.batch_summary || ''
  // Initialize status from existing results
  const sm: Record<number, string> = {}
  const res = data.results || {}
  for (const img of data.images || []) {
    const r = res[img.index] || res[String(img.index)]
    sm[img.index] = r && !r._error ? 'done' : r && r._error ? 'error' : 'waiting'
  }
  statusMap.value = sm
  if (data.reused) {
    ElMessage.success(`已加载历史任务（已分析 ${data.analyzed_count || 0}/${data.total_images} 张）`)
  } else {
    ElMessage.success(`文档解析完成，共提取 ${data.total_images} 张图片`)
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
      analyzedCount.value = Object.keys(resultMap.value).length
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

const startBatchAnalysis = async () => {
  if (!taskId.value || batchRunning.value) return
  try {
    const res = await axios.post(`/api/docx/analyze/${taskId.value}`)
    if (res.data.success) {
      batchRunning.value = true
      batchPercent.value = 0
      batchErrorCount.value = 0
      // Initialize status for pending images
      const sm: Record<number, string> = {}
      images.value.forEach(img => {
        const r = resultMap.value[img.index]
        if (!r || r._error) sm[img.index] = 'waiting'
        else sm[img.index] = 'done'
      })
      statusMap.value = sm
      const total = res.data.total || 0
      if (total === 0) {
        ElMessage.info('所有图片已分析完成，无待处理项')
        batchRunning.value = false
        return
      }
      const prevDone = totalImages.value - total
      const hint = prevDone > 0 ? `（跳过 ${prevDone} 张已完成，重试 ${total} 张失败/未处理）` : `共 ${total} 张图片`
      ElMessage.info(`批量分析已启动，${hint}`)
      startPolling()
    }
  } catch (err: any) {
    ElMessage.error(err.message || '启动失败')
  }
}

const startPolling = () => {
  closeEventSource()
  const baseUrl = axios.defaults.baseURL || ''
  const url = `${baseUrl}/api/docx/status/${taskId.value}/stream`
  const es = new EventSource(url)
  eventSource.value = es

  es.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data.type === 'ping') return

      if (data.type === 'analyzing') {
        const idx = parseInt(data.idx)
        statusMap.value = { ...statusMap.value, [idx]: 'analyzing' }
      } else if (data.type === 'progress') {
        const result = data.result
        const idx = parseInt(data.idx)
        resultMap.value[idx] = result
        statusMap.value = { ...statusMap.value, [idx]: result._error ? 'error' : 'done' }
        imageCategories.value[idx] = result.image_type || imageCategories.value[idx] || '其他'
        updateCategoryStats()
        analyzedCount.value = Object.keys(resultMap.value).length
        batchPercent.value = data.total > 0 ? Math.round((data.progress / data.total) * 100) : 100
        batchErrorCount.value = data.error_count || 0
      } else if (data.type === 'summarizing') {
        batchStatus.value = 'summarizing'
        batchPercent.value = data.total > 0 ? Math.round((data.progress / data.total) * 100) : 100
      } else if (data.type === 'done') {
        batchRunning.value = false
        batchPercent.value = 100
        batchErrorCount.value = data.error_count || 0
        if (data.summary) batchSummary.value = data.summary
        es.close()
        const errMsg = batchErrorCount.value > 0 ? `（${batchErrorCount.value} 张异常）` : ''
        ElMessage.success(`批量分析完成！${errMsg}`)
      } else if (data.type === 'error') {
        batchRunning.value = false
        es.close()
        ElMessage.error(`分析异常: ${data.error}`)
      } else if (data.type === 'snapshot') {
        batchPercent.value = data.total > 0 ? Math.round((data.progress / data.total) * 100) : 100 || 0
        if (data.results) {
          const sm: Record<number, string> = {}
          Object.entries(data.results).forEach(([k, v]: [string, any]) => {
            sm[parseInt(k)] = v._error ? 'error' : 'done'
          })
          statusMap.value = sm
        }
        batchErrorCount.value = data.batch_error_count || 0
        if (data.results) {
          Object.entries(data.results).forEach(([k, v]: [string, any]) => {
            resultMap.value[parseInt(k)] = v
            imageCategories.value[parseInt(k)] = v.image_type || imageCategories.value[parseInt(k)] || '其他'
          })
        }
        updateCategoryStats()
        analyzedCount.value = Object.keys(resultMap.value).length
        if (!data.batch_running && data.batch_summary) {
          batchRunning.value = false
          batchSummary.value = data.batch_summary
          es.close()
        } else if (!data.batch_running) {
          batchRunning.value = false
          es.close()
        } else {
          batchRunning.value = true
        }
      }
    } catch {}
  }

  es.onerror = () => {
    es.close()
    // fallback to polling if SSE fails
    startHttpPolling()
  }
}

const startHttpPolling = () => {
  if (pollTimer.value) clearInterval(pollTimer.value)
  pollTimer.value = window.setInterval(async () => {
    try {
      const res = await axios.get(`/api/docx/status/${taskId.value}`)
      if (res.data.batch_running) {
        batchPercent.value = res.data.batch_total > 0 ? Math.round((res.data.batch_progress / res.data.batch_total) * 100) : 100
        batchErrorCount.value = res.data.batch_error_count || 0
        const fres = res.data.results || {}
        Object.entries(fres).forEach(([k, v]: [string, any]) => {
          const idx = parseInt(k)
          resultMap.value[idx] = v
          statusMap.value = { ...statusMap.value, [idx]: v._error ? 'error' : 'done' }
          imageCategories.value[idx] = v.image_type || imageCategories.value[idx] || '其他'
        })
        updateCategoryStats()
        analyzedCount.value = Object.keys(resultMap.value).length
        batchStatus.value = res.data.batch_status || ''
      } else if (res.data.batch_summary) {
        batchSummary.value = res.data.batch_summary
        batchRunning.value = false
        batchPercent.value = 100
        batchErrorCount.value = res.data.batch_error_count || 0
        const fres = res.data.results || {}
        Object.entries(fres).forEach(([k, v]: [string, any]) => {
          resultMap.value[parseInt(k)] = v
          imageCategories.value[parseInt(k)] = v.image_type || imageCategories.value[parseInt(k)] || '其他'
        })
        updateCategoryStats()
        analyzedCount.value = Object.keys(resultMap.value).length
        if (pollTimer.value) clearInterval(pollTimer.value)
        const errMsg = batchErrorCount.value > 0 ? `（${batchErrorCount.value} 张异常）` : ''
        ElMessage.success(`批量分析完成！${errMsg}`)
      }
    } catch {}
  }, 1000)
}

const closeEventSource = () => {
  if (eventSource.value) {
    eventSource.value.close()
    eventSource.value = null
  }
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

const resetTask = () => {
  closeEventSource()
  taskId.value = ''
  images.value = []
  resultMap.value = {}
  imageCategories.value = {}
  categoryStats.value = {}
  batchRunning.value = false
  batchPercent.value = 0
  batchErrorCount.value = 0
  batchSummary.value = ''
  selectedImg.value = null
  selectedImage.value = null
  analyzedCount.value = 0
  statusMap.value = {}
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
      resultMap.value = {}
      populateResults(res.data.results || {}, res.data.images || [])
      batchSummary.value = res.data.batch_summary || ''
      ElMessage.success(`已加载历史任务，共 ${res.data.total_images} 张图片`)
    } else {
      ElMessage.error(res.data.error || '加载失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '加载失败')
  }
}

const exportPdf = () => {
  if (!taskId.value) return
  const baseUrl = axios.defaults.baseURL || ''
  window.open(`${baseUrl}/api/docx/report/${taskId.value}/html`, '_blank')
}

const removeTask = async (tid: string) => {
  try {
    await ElMessageBox.confirm('确定要删除此任务吗？所有分析结果将被清除。', '确认删除', {
      confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning'
    })
    await axios.delete(`/api/docx/task/${tid}`)
    taskList.value = taskList.value.filter(t => t.task_id !== tid)
    ElMessage.success('任务已删除')
  } catch {
    // user cancelled or error
  }
}

onMounted(() => {
  fetchTasks()
})

onUnmounted(() => {
  closeEventSource()
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
.history-meta .summary-badge { color: #6366f1; font-weight: 600; }
.history-meta .report-badge { color: #059669; font-weight: 600; font-size: 11px; padding: 1px 6px; background: #d1fae5; border-radius: 4px; }
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

.error-banner {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 16px; background: #fef2f2; border: 1px solid #fecaca;
  border-radius: 8px; color: #b91c1c; font-size: 12px;
  margin-bottom: 4px;
}

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
.card-badge.card-badge-error { background: #ef4444; }

.card-status {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  background: rgba(255,255,255,.75); z-index: 5;
}
.status-spinner {
  width: 24px; height: 24px; border: 3px solid #e0e7ff;
  border-top-color: #6366f1; border-radius: 50%; animation: spin .7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.card-status-dot {
  position: absolute; top: 6px; left: 6px; width: 8px; height: 8px;
  border-radius: 50%; z-index: 2;
}
.dot-waiting { background: #cbd5e1; }
.dot-analyzing { background: #6366f1; animation: pulse-dot .8s ease-in-out infinite; }
.dot-done { background: #22c55e; }
.dot-error { background: #ef4444; }
@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: .4; }
}

.image-card.status-analyzing { border-color: #6366f1; box-shadow: 0 0 0 1px rgba(99,102,241,.3); }
.image-card.status-error { border-color: #fecaca; }

.detail-panel {
  width: 400px; flex-shrink: 0; background: white; border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06); overflow-y: auto; max-height: 600px;
}
.empty-detail { display: flex; align-items: center; justify-content: center; }
.empty-hint { display: flex; flex-direction: column; align-items: center; gap: 12px; color: #94a3b8; font-size: 14px; padding: 40px 20px; text-align: center; }

.detail-image { padding: 12px; }
.preview-large { width: 100%; border-radius: 8px; }
.detail-actions { padding: 8px 16px; border-bottom: 1px solid #f1f5f9; display: flex; align-items: center; gap: 8px; }
.error-hint { font-size: 12px; color: #ef4444; }
.detail-info { padding: 0 16px 16px; }
.info-header { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; margin-top: 12px; }
.info-section { margin-bottom: 16px; }
.info-section h4 { font-size: 12px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
.info-section p { font-size: 13px; color: #334155; line-height: 1.7; }
.no-data { color: #94a3b8; font-style: italic; }
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
.summary-header { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: #6366f1; margin-bottom: 14px; }
.summary-header-left { display: flex; align-items: center; gap: 10px; }
.summary-header h3 { font-size: 16px; color: #1e293b; }
.summary-content { font-size: 14px; line-height: 1.9; color: #334155; }
.summary-content :deep(h1) { font-size: 20px; margin: 16px 0 8px; }
.summary-content :deep(h2) { font-size: 17px; margin: 14px 0 6px; color: #1e293b; }
.summary-content :deep(h3) { font-size: 15px; margin: 12px 0 6px; color: #334155; }
.summary-content :deep(table) { border-collapse: collapse; width: 100%; margin: 10px 0; }
.summary-content :deep(th), .summary-content :deep(td) { border: 1px solid #e2e8f0; padding: 6px 12px; text-align: left; font-size: 13px; }
.summary-content :deep(th) { background: #f8fafc; font-weight: 600; }
.summary-content :deep(blockquote) { border-left: 3px solid #6366f1; padding: 4px 12px; color: #64748b; margin: 10px 0; }
.summary-content :deep(strong) { color: #1e293b; }
.summary-content :deep(hr) { border: none; border-top: 1px solid #e2e8f0; margin: 16px 0; }

.category-summary { background: white; border-radius: 12px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.category-summary h4 { font-size: 13px; margin-bottom: 10px; color: #475569; }
.cat-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.cat-chip { padding: 4px 12px; border-radius: 14px; font-size: 13px; background: #f1f5f9; color: #475569; }
.cat-chip strong { color: #1e293b; margin-left: 2px; }
</style>
