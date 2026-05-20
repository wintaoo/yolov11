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
                <span v-if="t.duplicates_removed" class="dedup-hint">去重 {{ t.duplicates_removed }}</span>
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
        <p>上传 .doc / .docx 格式的投标文件，系统将自动提取图片并按规则匹配分类，图片自动存储供布置图检测使用</p>
        <div class="upload-actions">
          <label class="upload-btn">
            <el-icon :size="18"><Upload /></el-icon>
            <span>选择 Word 文件</span>
            <input type="file" ref="docxInput" accept=".docx,.doc" @change="handleUpload" hidden />
          </label>
          <button class="docs-btn" @click="openDocsDialog">
            <el-icon :size="18"><FolderOpened /></el-icon>
            <span>从 docs 文件夹选择</span>
          </button>
        </div>
        <div class="upload-progress" v-if="uploading">
          <div class="progress-bar-track">
            <div class="progress-bar-fill" :style="{ width: uploadPercent + '%' }"></div>
          </div>
          <span class="progress-text">{{ uploadStatus }}</span>
        </div>
        <div class="dedup-banner" v-if="duplicatesRemoved > 0">
          <el-icon :size="16"><CircleCheck /></el-icon>
          已自动去除 {{ duplicatesRemoved }} 张重复图片（页眉/页脚等重复内容）
        </div>
      </div>
    </div>

    <div class="analysis-container" v-else>
      <div class="status-bar">
        <div class="status-info">
          <span class="task-id">任务 #{{ taskId }}</span>
          <span class="image-count">共 {{ totalImages }} 张图片</span>
          <el-tag v-if="duplicatesRemoved > 0" size="small" type="success" effect="plain">
            去重 {{ duplicatesRemoved }} 张
          </el-tag>
          <span v-if="categoryFilter" class="filter-badge">
            筛选: {{ categoryFilter }}（{{ filteredImages.length }} 张）
          </span>
        </div>
        <div class="status-actions">
          <el-select
            v-model="categoryFilter"
            placeholder="按类别筛选"
            clearable
            size="small"
            style="width: 180px;"
            @change="onCategoryFilterChange"
          >
            <el-option
              v-for="cat in availableCategories"
              :key="cat"
              :label="`${cat} (${getCategoryCount(cat)})`"
              :value="cat"
            />
          </el-select>
          <el-button v-if="categoryFilter" size="small" type="primary" plain @click="categoryFilter = ''">
            <el-icon><List /></el-icon>
            显示全部
          </el-button>
          <el-button size="small" type="danger" plain @click="resetTask">返回列表</el-button>
        </div>
      </div>

      <div class="content-layout">
        <div class="image-grid">
          <div
            v-for="img in filteredImages"
            :key="img.index"
            class="image-card"
            :class="{ selected: selectedImg === img.index, 'has-manual-label': !!img.manual_label }"
            @click="selectImage(img)"
            @dblclick="openPreview(img)"
          >
            <img :src="`/api/docx/image/${taskId}/${img.filename}`" class="card-img" loading="lazy" />
            <div class="card-info">
              <span class="card-figname" :title="img.figure_name">{{ img.figure_name || '#' + img.index }}</span>
              <span class="card-cat">
                {{ getEffectiveCategory(img) }}
                <span class="card-conf" v-if="img.classification_confidence > 0" :class="confidenceClass(img.classification_confidence)">
                  {{ (img.classification_confidence * 100).toFixed(0) }}%
                </span>
              </span>
            </div>
            <div class="card-page">第{{ img.index }}张</div>
            <div class="card-manual-dot" v-if="img.manual_label" title="人工标注: {{ img.manual_label }}">✎</div>
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
                <el-tag :type="getTypeColor(getEffectiveCategory(selectedImage))" size="large">
                  {{ getEffectiveCategory(selectedImage) || '未分类' }}
                </el-tag>
                <el-tag v-if="selectedImage.classification_confidence > 0" :type="confidenceTagType(selectedImage.classification_confidence)" size="large" effect="dark">
                  置信度 {{ (selectedImage.classification_confidence * 100).toFixed(0) }}%
                </el-tag>
                <el-tag type="warning" size="large" effect="plain">
                  <el-icon :size="14" style="margin-right: 4px;"><Document /></el-icon>
                  第 {{ selectedImage.index }} 张
                </el-tag>
              </div>
            </div>

            <!-- 手动标注区域 -->
            <div class="info-section label-section">
              <h4>
                <el-icon :size="14"><Edit /></el-icon>
                图片类别标注
              </h4>
              <div class="label-row">
                <el-select
                  v-model="labelForm.category"
                  placeholder="选择预定义类别"
                  clearable
                  filterable
                  size="small"
                  style="flex: 1;"
                  @change="onLabelCategoryChange"
                >
                  <el-option
                    v-for="cat in PREDEFINED_CATEGORIES"
                    :key="cat"
                    :label="cat"
                    :value="cat"
                  />
                  <el-option label="其他（自输入）" value="__custom__" />
                </el-select>
              </div>
              <div class="label-row" v-if="labelForm.category === '__custom__'">
                <el-input
                  v-model="labelForm.customCategory"
                  placeholder="请输入自定义类别名称"
                  size="small"
                  style="flex: 1;"
                  @keyup.enter="saveLabel"
                />
              </div>
              <div class="label-row label-actions">
                <span class="label-hint" v-if="selectedImage.manual_label">
                  当前标注: <strong>{{ selectedImage.manual_label }}</strong>
                </span>
                <span class="label-hint" v-else-if="selectedImage.guessed_category">
                  系统判定: <strong>{{ selectedImage.guessed_category }}</strong>
                </span>
                <el-button size="small" type="primary" @click="saveLabel" :loading="labelSaving">
                  <el-icon :size="14"><Check /></el-icon>
                  保存标签
                </el-button>
                <el-button v-if="selectedImage.manual_label" size="small" type="warning" plain @click="clearLabel">
                  清除标签
                </el-button>
              </div>
            </div>

            <div class="info-section" v-if="selectedImage.context_before">
              <h4>文档上文</h4>
              <p>{{ selectedImage.context_before }}</p>
            </div>
            <div class="info-section" v-if="selectedImage.context_after">
              <h4>文档下文</h4>
              <p>{{ selectedImage.context_after }}</p>
            </div>
          </div>
        </aside>

        <div class="detail-panel empty-detail" v-else-if="!selectedImage">
          <div class="empty-hint">
            <el-icon :size="32"><Picture /></el-icon>
            <span>点击左侧图片查看详情</span>
          </div>
        </div>

        <!-- AI 分析面板（固定区域，始终显示） -->
        <aside class="analysis-panel" v-if="selectedImage">
          <div class="analysis-header">
            <h3>
              <el-icon :size="16"><DataAnalysis /></el-icon>
              AI 图纸分析
            </h3>
            <div class="analysis-header-actions">
              <el-button v-if="analysisState === 'loaded'" size="small" text title="复制报告" @click="copyReport">
                <el-icon :size="16"><CopyDocument /></el-icon>
              </el-button>
              <el-button v-if="analysisState === 'loaded'" size="small" text title="导出PDF" @click="exportPdf">
                <el-icon :size="16"><Printer /></el-icon>
              </el-button>
              <el-button v-if="analysisState === 'loaded'" size="small" text title="导出MD" @click="exportReport">
                <el-icon :size="16"><Download /></el-icon>
              </el-button>
            </div>
          </div>

          <div class="analysis-disclaimer">
            <el-icon :size="14"><WarningFilled /></el-icon>
            <span>基于视觉大模型和图片上下文生成，内容可能有误，请仔细甄别</span>
          </div>

          <div class="analysis-body">
            <div v-if="analysisState === 'idle'" class="analysis-idle">
              <el-icon :size="40" color="#6366f1"><DataAnalysis /></el-icon>
              <p>点击下方按钮，AI 将自动识别图纸类型、关键要素并生成详细报告</p>
              <p class="analysis-hint">分析包含文档上下文作为参考</p>
              <el-button type="primary" @click="startAnalysis">
                <el-icon><VideoPlay /></el-icon>
                开始AI分析
              </el-button>
            </div>

            <div v-if="analysisState === 'loading'" class="analysis-loading">
              <div class="analysis-spinner"></div>
              <p>{{ analysisLoadingMsg }}</p>
              <p class="analysis-hint">首次分析约需 30-60 秒，请耐心等待</p>
            </div>

            <div v-if="analysisError" class="analysis-error">
              <el-icon :size="24" color="#dc2626"><WarningFilled /></el-icon>
              <p>{{ analysisError }}</p>
              <el-button size="small" type="primary" @click="startAnalysis">重试</el-button>
            </div>

            <div v-if="analysisState === 'loaded' && analysisReport" class="analysis-content">
              <div class="markdown-body" v-html="renderedReport"></div>
            </div>
          </div>
        </aside>
      </div>

      <div class="category-summary" v-if="Object.keys(categoryStats).length">
        <h4>
          图片分类统计（点击筛选）
          <el-button v-if="categoryFilter" size="small" text type="primary" @click="categoryFilter = ''">清除筛选</el-button>
        </h4>
        <div class="cat-chips">
          <span
            v-for="(count, cat) in sortedCategoryStats"
            :key="cat"
            class="cat-chip"
            :class="{ active: categoryFilter === cat }"
            @click="categoryFilter = categoryFilter === cat ? '' : cat"
          >
            {{ cat }} <strong>{{ count }}</strong>
          </span>
        </div>
        <div class="confidence-summary" v-if="averageConfidence > 0">
          平均分类置信度: <strong :style="{ color: confidenceSummaryColor }">{{ (averageConfidence * 100).toFixed(1) }}%</strong>
        </div>
      </div>
    </div>

    <!-- Docs 文件夹文件选择对话框 -->
    <el-dialog v-model="showDocsDialog" title="从 docs 文件夹选择投标文件" width="560px" :close-on-click-modal="false">
      <div class="docs-dialog-body">
        <div class="docs-folder-path">
          <el-icon :size="14"><Folder /></el-icon>
          <span>{{ docsFolder }}</span>
        </div>
        <div class="docs-empty" v-if="docsFiles.length === 0 && !docsLoading">
          <el-icon :size="32"><FolderOpened /></el-icon>
          <p>docs 文件夹为空，请将 .doc / .docx 文件放入项目根目录下的 docs 文件夹</p>
          <el-button size="small" type="primary" @click="openDocsFolder">
            <el-icon><FolderOpened /></el-icon>
            打开 docs 文件夹
          </el-button>
        </div>
        <div class="docs-loading" v-if="docsLoading">
          <el-icon :size="24" class="loading-icon"><Loading /></el-icon>
          <span>加载中...</span>
        </div>
        <div class="docs-file-list" v-if="docsFiles.length > 0">
          <div
            v-for="f in docsFiles"
            :key="f.name"
            class="docs-file-item"
            :class="{ selected: selectedDocsFile === f.name }"
            @click="selectedDocsFile = f.name"
          >
            <el-icon :size="20"><Document /></el-icon>
            <div class="docs-file-info">
              <span class="docs-file-name">{{ f.name }}</span>
              <span class="docs-file-size">{{ formatFileSize(f.size) }}</span>
            </div>
            <el-icon v-if="selectedDocsFile === f.name" :size="18" color="#6366f1"><Check /></el-icon>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="showDocsDialog = false">取消</el-button>
        <el-button type="primary" @click="processDocsFile" :disabled="!selectedDocsFile" :loading="uploading">
          解析此文件
        </el-button>
      </template>
    </el-dialog>

    <!-- 图片放大预览 -->
    <el-dialog v-model="previewVisible" :title="previewImage?.figure_name || '图片预览'" width="95%" top="2vh" :close-on-click-modal="true" destroy-on-close>
      <div class="preview-dialog-body">
        <img :src="`/api/docx/image/${taskId}/${previewImage?.filename}`" class="preview-dialog-img" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { Upload, Picture, Clock, FolderOpened, Delete, Document, Edit, Check, CircleCheck, Loading, Folder, DataAnalysis, CopyDocument, Close, WarningFilled, VideoPlay, Printer, List } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { marked } from 'marked'

// Configure marked for safe rendering
marked.setOptions({ breaks: true, gfm: true })

const PREDEFINED_CATEGORIES = [
  '周边环境图', '进度计划图', '分区规划图', '基础结构图',
  '临时用电布置图', '临时用水布置图', '土方工程图',
  '主体结构图', '装饰装修图', '总平面布置图',
  '施工计划图', '临建设施平面布置图', '施工分区图',
]

const docxInput = ref<HTMLInputElement | null>(null)
const taskId = ref('')
const totalImages = ref(0)
const duplicatesRemoved = ref(0)
const images = ref<any[]>([])
const categoryStats = ref<Record<string, number>>({})
const selectedImg = ref<number | null>(null)
const selectedImage = ref<any>(null)
const taskList = ref<any[]>([])

// Upload progress
const uploading = ref(false)
const uploadPercent = ref(0)
const uploadStatus = ref('')

// Category filter
const categoryFilter = ref('')
const filteredImages = computed(() => {
  if (!categoryFilter.value) return images.value
  return images.value.filter(img => getEffectiveCategory(img) === categoryFilter.value)
})
const availableCategories = computed(() => {
  const cats = new Set<string>()
  images.value.forEach(img => {
    const cat = getEffectiveCategory(img)
    if (cat && cat !== '其他') cats.add(cat)
  })
  return Array.from(cats).sort()
})
const getCategoryCount = (cat: string) => {
  return images.value.filter(img => getEffectiveCategory(img) === cat).length
}
const onCategoryFilterChange = () => {
  // filter change handled by v-model + computed
}

// Docs folder dialog
const showDocsDialog = ref(false)
const docsFiles = ref<any[]>([])
const docsLoading = ref(false)
const selectedDocsFile = ref('')
const docsFolder = ref('')

// AI Analysis Panel
const analysisState = ref<'idle' | 'loading' | 'loaded'>('idle')
const analysisReport = ref('')
const analysisError = ref('')
const analysisLoadingMsg = ref('')
let analysisAbortController: AbortController | null = null

const renderedReport = computed(() => {
  if (!analysisReport.value) return ''
  return marked.parse(analysisReport.value) as string
})

// Manual labeling
const labelSaving = ref(false)
const labelForm = ref({ category: '', customCategory: '' })

const getEffectiveCategory = (img: any) => {
  return img.manual_label || img.guessed_category || '其他'
}

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

const formatFileSize = (bytes: number) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

// Watch for image selection to pre-fill label form
watch(selectedImage, (img) => {
  if (img) {
    const existingLabel = img.manual_label || ''
    if (existingLabel && PREDEFINED_CATEGORIES.includes(existingLabel)) {
      labelForm.value = { category: existingLabel, customCategory: '' }
    } else if (existingLabel) {
      labelForm.value = { category: '__custom__', customCategory: existingLabel }
    } else {
      labelForm.value = { category: '', customCategory: '' }
    }
  }
})

// 轮询等待后台处理完成
const waitForTask = async (tid: string, startTime: number) => {
  const POLL_INTERVAL = 1500  // 1.5秒轮询一次
  const MAX_WAIT = 300000     // 最多等5分钟

  return new Promise<void>((resolve, reject) => {
    const poll = async () => {
      const elapsed = Math.round((Date.now() - startTime) / 1000)
      uploadStatus.value = `后台解析中... 已等待 ${elapsed} 秒`
      try {
        const res = await axios.get(`/api/docx/status/${tid}`)
        if (res.data.status === 'extracted') {
          uploadStatus.value = '解析完成，加载结果中...'
          // 加载完整任务数据
          const loadRes = await axios.post(`/api/docx/task/${tid}/load`)
          if (loadRes.data.success) {
            openTask(loadRes.data)
            resolve()
          } else {
            reject(new Error(loadRes.data.error || '加载结果失败'))
          }
        } else if (res.data.status === 'error') {
          reject(new Error('解析失败，请重试'))
        } else if (Date.now() - startTime > MAX_WAIT) {
          reject(new Error('解析超时，请稍后在历史记录中查看'))
        } else {
          setTimeout(poll, POLL_INTERVAL)
        }
      } catch (err: any) {
        // 网络错误时继续重试
        if (Date.now() - startTime > MAX_WAIT) {
          reject(new Error('解析超时，请稍后在历史记录中查看'))
        } else {
          setTimeout(poll, POLL_INTERVAL)
        }
      }
    }
    poll()
  })
}

const handleUpload = async (event: Event) => {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)

  uploading.value = true
  uploadPercent.value = 0
  uploadStatus.value = '上传中...'
  const startTime = Date.now()

  try {
    const res = await axios.post('/api/docx/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (e.total) {
          uploadPercent.value = Math.round((e.loaded / e.total) * 100)
          uploadStatus.value = `上传中 ${uploadPercent.value}%`
        }
      },
    })
    if (res.data.success) {
      if (res.data.status === 'processing') {
        // 后台处理中（含重复文件仍在处理的情况），开始轮询
        uploadPercent.value = 100
        await waitForTask(res.data.task_id, startTime)
      } else if (res.data.reused) {
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
    uploading.value = false
    uploadPercent.value = 0
    uploadStatus.value = ''
    if (docxInput.value) docxInput.value.value = ''
  }
}

const openTask = (data: any) => {
  taskId.value = data.task_id
  totalImages.value = data.total_images
  duplicatesRemoved.value = data.duplicates_removed || 0
  images.value = data.images
  categoryStats.value = data.category_stats || {}
  if (data.reused) {
    ElMessage.success(`已加载历史解析记录，共 ${data.total_images} 张图片`)
  } else {
    const dedupMsg = data.duplicates_removed ? `，已自动去重 ${data.duplicates_removed} 张` : ''
    ElMessage.success(`投标文件解析完成，共提取 ${data.total_images} 张图片${dedupMsg}，已自动存储`)
  }
}

// Docs folder functions
const openDocsDialog = async () => {
  showDocsDialog.value = true
  selectedDocsFile.value = ''
  docsLoading.value = true
  try {
    const res = await axios.get('/api/docx/docs-files')
    if (res.data.success) {
      docsFiles.value = res.data.files || []
      docsFolder.value = res.data.folder || ''
    }
  } catch {
    docsFiles.value = []
  } finally {
    docsLoading.value = false
  }
}

const openDocsFolder = () => {
  // 无法在浏览器中直接打开文件系统，提示用户路径
  ElMessage.info(`请将 .docx 文件放入: ${docsFolder.value || '项目根目录/docs'}`)
}

const processDocsFile = async () => {
  if (!selectedDocsFile.value) return
  uploading.value = true
  uploadStatus.value = '解析中...'
  const startTime = Date.now()
  try {
    const res = await axios.post('/api/docx/upload-from-docs', {
      filename: selectedDocsFile.value,
    })
    if (res.data.success) {
      showDocsDialog.value = false
      if (res.data.reused) {
        ElMessageBox.confirm(
          '检测到重复文件，是否打开历史解析记录？',
          '检测到重复文件',
          { confirmButtonText: '打开历史结果', cancelButtonText: '取消', type: 'info' }
        ).then(() => {
          openTask(res.data)
        }).catch(() => {})
      } else if (res.data.status === 'processing') {
        await waitForTask(res.data.task_id, startTime)
      } else {
        openTask(res.data)
      }
    } else {
      ElMessage.error(res.data.error || '解析失败')
    }
  } catch (err: any) {
    ElMessage.error(err.response?.data?.error || err.message || '解析失败')
  } finally {
    uploading.value = false
    uploadStatus.value = ''
  }
}

// Manual labeling functions
const onLabelCategoryChange = (val: string) => {
  if (val !== '__custom__') {
    labelForm.value.customCategory = ''
  }
}

const saveLabel = async () => {
  if (!selectedImage.value || !taskId.value) return
  let label = ''
  if (labelForm.value.category === '__custom__') {
    label = labelForm.value.customCategory.trim()
    if (!label) {
      ElMessage.warning('请输入自定义类别名称')
      return
    }
  } else if (labelForm.value.category) {
    label = labelForm.value.category
  } else {
    ElMessage.warning('请选择或输入类别')
    return
  }

  labelSaving.value = true
  try {
    const res = await axios.post(`/api/docx/task/${taskId.value}/label`, {
      image_index: selectedImage.value.index,
      manual_label: label,
    })
    if (res.data.success) {
      // Update local state
      selectedImage.value.manual_label = label
      const imgInList = images.value.find(i => i.index === selectedImage.value.index)
      if (imgInList) {
        imgInList.manual_label = label
      }
      categoryStats.value = res.data.category_stats || {}
      ElMessage.success('标签已保存')
    } else {
      ElMessage.error(res.data.error || '保存失败')
    }
  } catch (err: any) {
    ElMessage.error(err.response?.data?.error || err.message || '保存失败')
  } finally {
    labelSaving.value = false
  }
}

const clearLabel = async () => {
  if (!selectedImage.value || !taskId.value) return
  labelSaving.value = true
  try {
    const res = await axios.post(`/api/docx/task/${taskId.value}/label`, {
      image_index: selectedImage.value.index,
      manual_label: '',
    })
    if (res.data.success) {
      selectedImage.value.manual_label = ''
      const imgInList = images.value.find(i => i.index === selectedImage.value.index)
      if (imgInList) {
        imgInList.manual_label = ''
      }
      categoryStats.value = res.data.category_stats || {}
      labelForm.value = { category: '', customCategory: '' }
      ElMessage.success('标签已清除')
    } else {
      ElMessage.error(res.data.error || '清除失败')
    }
  } catch (err: any) {
    ElMessage.error(err.response?.data?.error || err.message || '清除失败')
  } finally {
    labelSaving.value = false
  }
}

// AI Analysis functions
const checkExistingReport = async (tid: string, imgIdx: number) => {
  if (!tid || imgIdx == null) return
  try {
    const res = await axios.get(`/api/docx/analysis-report/${tid}/${imgIdx}`)
    if (res.data.success && res.data.found && res.data.report) {
      analysisReport.value = res.data.report
      analysisState.value = 'loaded'
      // 有报告但不自动弹开面板，保持布局稳定
    } else {
      analysisState.value = 'idle'
      analysisReport.value = ''
    }
  } catch {
    analysisState.value = 'idle'
    analysisReport.value = ''
  }
}

const startAnalysis = async () => {
  if (!taskId.value || !selectedImage.value) return
  if (analysisAbortController) { analysisAbortController.abort() }
  analysisAbortController = new AbortController()
  analysisState.value = 'loading'
  analysisError.value = ''
  analysisReport.value = ''
  analysisLoadingMsg.value = 'AI 正在分析图纸，预计 30-60 秒...'
  try {
    const res = await axios.post(
      `/api/docx/analyze-image/${taskId.value}/${selectedImage.value.index}`,
      {}, { signal: analysisAbortController.signal }
    )
    if (res.data.success && res.data.report) {
      analysisReport.value = res.data.report
      analysisState.value = 'loaded'
    } else {
      analysisError.value = res.data.error || '分析失败，请重试'
      analysisState.value = 'idle'
    }
  } catch (err: any) {
    if (err.name === 'CanceledError' || err.name === 'AbortError') return
    analysisError.value = err.response?.data?.error || err.message || '请求失败'
    analysisState.value = 'idle'
  } finally {
    analysisAbortController = null
  }
}

const copyReport = async () => {
  if (!analysisReport.value) return
  try {
    await navigator.clipboard.writeText(analysisReport.value)
    ElMessage.success('报告已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动复制')
  }
}

const exportReport = () => {
  if (!analysisReport.value) return
  const blob = new Blob([analysisReport.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `analysis_${taskId.value}_${selectedImage.value?.index || 'unknown'}.md`
  a.click()
  URL.revokeObjectURL(url)
}

const exportPdf = () => {
  if (!analysisReport.value) return
  const htmlContent = marked.parse(analysisReport.value) as string
  const w = window.open('', '_blank', 'width=900,height=700')
  if (!w) { ElMessage.error('请允许弹出窗口以导出PDF'); return }
  w.document.write(`
    <!DOCTYPE html><html><head><meta charset="utf-8"><title>图纸分析报告</title>
    <style>
      *{box-sizing:border-box}body{font-family:'Microsoft YaHei','PingFang SC',sans-serif;max-width:800px;margin:0 auto;padding:30px;color:#1e293b;line-height:1.8}
      h1{font-size:22px;border-bottom:2px solid #eef2ff;padding-bottom:10px;margin-bottom:20px}
      h2{font-size:16px;color:#4f46e5;margin-top:24px;border-bottom:1px solid #f1f5f9;padding-bottom:4px}
      h3{font-size:14px;color:#475569;margin-top:16px}
      table{width:100%;border-collapse:collapse;margin:10px 0;font-size:13px}
      th{background:#f1f5f9;padding:6px 10px;text-align:left;font-weight:600;border:1px solid #e2e8f0}
      td{padding:5px 10px;border:1px solid #e2e8f0}
      blockquote{border-left:3px solid #818cf8;padding:4px 12px;color:#64748b;margin:10px 0;background:#f8fafc}
      ul,ol{padding-left:20px}li{margin-bottom:4px}
      strong{color:#1e293b;font-weight:600}
      hr{border:none;border-top:1px solid #e2e8f0;margin:16px 0}
      @media print{body{padding:20px}@page{margin:15mm}}
    </style></head><body>
    ${htmlContent}
    <script>window.onload=function(){window.print();setTimeout(function(){window.close()},500)}<\/script>
    </body></html>
  `)
  w.document.close()
}

const resetAnalysis = () => {
  if (analysisAbortController) { analysisAbortController.abort(); analysisAbortController = null }
  analysisState.value = 'idle'
  analysisReport.value = ''
  analysisError.value = ''
  analysisLoadingMsg.value = ''
}

// 图片放大预览
const previewVisible = ref(false)
const previewImage = ref<any>(null)

const openPreview = (img: any) => {
  previewImage.value = img
  previewVisible.value = true
}

const selectImage = (img: any) => {
  selectedImg.value = img.index
  selectedImage.value = img
  resetAnalysis()
  if (taskId.value) {
    checkExistingReport(taskId.value, img.index)
  }
}

const resetTask = () => {
  resetAnalysis()
  taskId.value = ''
  images.value = []
  categoryStats.value = {}
  duplicatesRemoved.value = 0
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
      duplicatesRemoved.value = res.data.duplicates_removed || 0
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
  } catch {
    return
  }
  try {
    const res = await axios.delete(`/api/docx/task/${tid}`)
    if (res.data && res.data.success) {
      taskList.value = taskList.value.filter(t => t.task_id !== tid)
      ElMessage.success('记录已删除')
    } else {
      ElMessage.error(res.data?.error || '删除失败')
    }
  } catch (err: any) {
    ElMessage.error(err.message || '删除失败')
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
.dedup-hint { color: #16a34a; font-weight: 500; }
.history-actions { display: flex; gap: 6px; flex-shrink: 0; }

.upload-card {
  text-align: center; background: white; border-radius: 16px; padding: 48px 40px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06); max-width: 520px; width: 100%;
}
.upload-card h3 { margin: 16px 0 8px; font-size: 18px; color: #1e293b; }
.upload-card p { color: #94a3b8; font-size: 14px; margin-bottom: 24px; line-height: 1.6; }
.upload-actions { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }
.upload-btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 12px 28px; background: #6366f1; color: white; border-radius: 10px;
  font-size: 15px; font-weight: 600; cursor: pointer; transition: all .2s;
  box-shadow: 0 4px 14px rgba(99,102,241,.35);
}
.upload-btn:hover { background: #4f46e5; transform: translateY(-1px); }
.docs-btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 12px 28px; background: white; color: #6366f1; border: 2px solid #6366f1;
  border-radius: 10px; font-size: 15px; font-weight: 600; cursor: pointer; transition: all .2s;
}
.docs-btn:hover { background: #eef2ff; }

.upload-progress { margin-top: 20px; width: 100%; }
.progress-bar-track {
  width: 100%; height: 6px; background: #e2e8f0; border-radius: 3px; overflow: hidden;
}
.progress-bar-fill {
  height: 100%; background: linear-gradient(90deg, #6366f1, #818cf8);
  border-radius: 3px; transition: width .3s ease;
}
.progress-text { font-size: 12px; color: #64748b; margin-top: 6px; display: block; }

.dedup-banner {
  display: inline-flex; align-items: center; gap: 6px;
  margin-top: 16px; padding: 8px 16px; background: #f0fdf4;
  border: 1px solid #bbf7d0; border-radius: 8px;
  font-size: 13px; color: #16a34a; font-weight: 500;
}

.status-bar {
  display: flex; align-items: center; justify-content: space-between;
  background: white; border-radius: 10px; padding: 12px 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06);
}
.status-info { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
.filter-badge {
  font-size: 12px; color: #6366f1; background: #eef2ff;
  padding: 2px 10px; border-radius: 12px; font-weight: 600;
}
.task-id { font-weight: 700; color: #6366f1; font-family: monospace; }
.image-count { color: #64748b; font-size: 14px; }
.status-actions { display: flex; gap: 8px; }

.content-layout { display: flex; gap: 16px; align-items: flex-start; overflow-x: auto; padding-bottom: 8px; }

.image-grid {
  flex: 1; display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 8px; min-width: 0; max-height: calc(100vh - 260px); overflow-y: auto;
  background: white; border-radius: 12px; padding: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06);
}
.image-card {
  border-radius: 8px; overflow: hidden; cursor: pointer; transition: all .15s;
  border: 2px solid transparent; background: #f8fafc; position: relative;
}
.image-card:hover { border-color: #c7d2fe; }
.image-card.selected { border-color: #6366f1; box-shadow: 0 0 0 2px rgba(99,102,241,.2); }
.image-card.has-manual-label { border-color: #a5b4fc; }
.image-card.has-manual-label::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: #22c55e; z-index: 2;
}
.card-img { width: 100%; min-height: 100px; aspect-ratio: 4/3; object-fit: cover; display: block; }
.card-info { display: flex; justify-content: space-between; padding: 6px 8px; font-size: 11px; }
.card-figname { color: #1e293b; font-weight: 600; font-size: 10px; max-width: 70px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-cat { color: #6366f1; font-weight: 500; font-size: 10px; max-width: 55px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: flex; flex-direction: column; gap: 1px; }
.card-conf { font-size: 9px; font-weight: 700; }
.card-conf.conf-high { color: #16a34a; }
.card-conf.conf-mid { color: #d97706; }
.card-conf.conf-low { color: #dc2626; }
.card-page { position: absolute; bottom: 4px; right: 4px; font-size: 9px; color: #94a3b8; background: #f1f5f9; padding: 1px 5px; border-radius: 3px; font-weight: 600; }
.card-manual-dot {
  position: absolute; top: 4px; right: 4px; font-size: 10px; color: #22c55e;
  background: #f0fdf4; padding: 0 4px; border-radius: 3px; font-weight: 700;
}

.detail-panel {
  width: 360px; flex-shrink: 0; background: white; border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06); overflow-y: auto;
  max-height: calc(100vh - 260px);
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

/* Labeling section */
.label-section {
  background: #fafafe; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px;
}
.label-section h4 {
  display: flex; align-items: center; gap: 6px; margin-bottom: 10px; color: #6366f1;
}
.label-row { display: flex; gap: 8px; margin-bottom: 8px; }
.label-row:last-child { margin-bottom: 0; }
.label-actions { align-items: center; justify-content: flex-end; flex-wrap: wrap; }
.label-hint { font-size: 12px; color: #94a3b8; flex: 1; }
.label-hint strong { color: #6366f1; }

.category-summary { background: white; border-radius: 12px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.category-summary h4 { font-size: 13px; margin-bottom: 10px; color: #475569; display: flex; align-items: center; gap: 8px; }
.cat-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.cat-chip {
  padding: 4px 12px; border-radius: 14px; font-size: 13px; background: #f1f5f9;
  color: #475569; cursor: pointer; transition: all .15s; user-select: none;
}
.cat-chip:hover { background: #e0e7ff; color: #4338ca; }
.cat-chip.active { background: #6366f1; color: #fff; }
.cat-chip.active strong { color: #fff; }
.cat-chip strong { color: #1e293b; margin-left: 2px; }
.confidence-summary { margin-top: 10px; font-size: 13px; color: #64748b; }

/* Docs dialog */
.docs-dialog-body { min-height: 200px; }
.docs-folder-path {
  display: flex; align-items: center; gap: 6px; padding: 8px 12px;
  background: #f1f5f9; border-radius: 6px; font-size: 13px; color: #64748b;
  margin-bottom: 16px; word-break: break-all;
}
.docs-empty {
  display: flex; flex-direction: column; align-items: center; gap: 12px;
  padding: 32px 20px; text-align: center; color: #94a3b8; font-size: 14px;
}
.docs-loading {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 32px; color: #94a3b8; font-size: 14px;
}
.loading-icon { animation: spin .7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.docs-file-list { display: flex; flex-direction: column; gap: 6px; max-height: 360px; overflow-y: auto; }
.docs-file-item {
  display: flex; align-items: center; gap: 10px; padding: 10px 14px;
  border: 1px solid #e2e8f0; border-radius: 8px; cursor: pointer; transition: all .15s;
}
.docs-file-item:hover { background: #f8fafc; border-color: #c7d2fe; }
.docs-file-item.selected { background: #eef2ff; border-color: #6366f1; }
.docs-file-info { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.docs-file-name { font-size: 14px; font-weight: 500; color: #1e293b; }
.docs-file-size { font-size: 12px; color: #94a3b8; }

/* AI Analysis Panel */
.analysis-panel {
  width: 420px; flex-shrink: 0; background: white; border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06);
  display: flex; flex-direction: column;
  max-height: calc(100vh - 260px); overflow: hidden;
}
.analysis-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px; border-bottom: 1px solid #f1f5f9; flex-shrink: 0;
}
.analysis-header h3 {
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; color: #1e293b; font-weight: 700;
}
.analysis-header-actions { display: flex; gap: 4px; }
.analysis-disclaimer {
  display: flex; align-items: center; gap: 6px; padding: 6px 16px;
  background: #fff7ed; border-top: 1px solid #fed7aa; border-bottom: 1px solid #fed7aa;
  font-size: 11px; color: #c2410c; flex-shrink: 0;
}
.analysis-body { flex: 1; overflow-y: auto; padding: 16px; }

.analysis-idle, .analysis-loading, .analysis-error {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 12px; padding: 40px 20px;
  text-align: center; color: #64748b; font-size: 14px; min-height: 250px;
}
.analysis-hint { font-size: 12px; color: #94a3b8; }
.analysis-spinner {
  width: 36px; height: 36px; border: 3px solid #e0e7ff;
  border-top-color: #6366f1; border-radius: 50%;
  animation: a-spin .7s linear infinite;
}
@keyframes a-spin { to { transform: rotate(360deg); } }
.analysis-error p { color: #dc2626; }

.analysis-content { padding: 4px 0; }
.markdown-body { font-size: 14px; line-height: 1.75; color: #334155; }
.markdown-body h1 { font-size: 18px; font-weight: 700; color: #1e293b; margin: 0 0 12px; padding-bottom: 8px; border-bottom: 2px solid #eef2ff; }
.markdown-body h2 { font-size: 15px; font-weight: 700; color: #4f46e5; margin: 20px 0 8px; padding-bottom: 4px; border-bottom: 1px solid #f1f5f9; }
.markdown-body h3 { font-size: 14px; font-weight: 600; color: #475569; margin: 14px 0 6px; }
.markdown-body p { margin: 0 0 8px; }
.markdown-body ul, .markdown-body ol { padding-left: 20px; margin: 0 0 8px; }
.markdown-body li { margin-bottom: 4px; }
.markdown-body strong { color: #1e293b; font-weight: 600; }
.markdown-body blockquote { border-left: 3px solid #818cf8; padding: 4px 12px; color: #64748b; margin: 12px 0; background: #f8fafc; }
.markdown-body hr { border: none; border-top: 1px solid #e2e8f0; margin: 16px 0; }
.markdown-body table { width: 100%; border-collapse: collapse; margin: 8px 0 12px; font-size: 13px; }
.markdown-body th { background: #f1f5f9; padding: 6px 10px; text-align: left; font-weight: 600; color: #475569; border: 1px solid #e2e8f0; }
.markdown-body td { padding: 5px 10px; border: 1px solid #e2e8f0; color: #334155; }
.markdown-body em { color: #94a3b8; }

.preview-dialog-body { display: flex; align-items: center; justify-content: center; background: #0f172a; border-radius: 8px; padding: 16px; }
.preview-dialog-img { max-width: 100%; max-height: 85vh; object-fit: contain; border-radius: 4px; }

</style>
