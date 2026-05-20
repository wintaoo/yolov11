<template>
  <div class="detection-panel">
    <div class="parsed-banner" v-if="parsedInfo && !serverMode && !imageFiles.length">
      <div class="parsed-banner-left">
        <el-icon :size="18"><FolderOpened /></el-icon>
        <span>检测到已解析的投标文件：<strong>{{ parsedInfo.doc_name || parsedInfo.task_id }}</strong>，共 <strong>{{ parsedInfo.image_count }}</strong> 张图片</span>
      </div>
      <div class="parsed-banner-actions">
        <el-button size="small" type="primary" plain @click="loadAllFromParsedFolder">
          <el-icon><FolderOpened /></el-icon>
          加载所有图片
        </el-button>
        <el-button size="small" type="success" plain @click="loadFilteredFromParsedFolder">
          <el-icon><FolderOpened /></el-icon>
          只加载有类别图片
        </el-button>
      </div>
    </div>

    <div class="toolbar">
      <div class="toolbar-left">
        <label class="upload-trigger">
          <el-icon :size="18"><FolderAdd /></el-icon>
          <span>打开本地文件夹</span>
          <input type="file" ref="folderInput" @change="handleFolderSelect" webkitdirectory directory hidden />
        </label>
        <span class="file-count" v-if="imageFiles.length || serverImages.length">
          {{ currentImageIndex + 1 }} / {{ totalImageCount }}
        </span>
        <el-tag v-if="serverMode" size="small" type="success" effect="plain">解析文件模式</el-tag>
      </div>
      <div class="toolbar-right" v-if="imageFiles.length || serverImages.length">
        <el-button size="small" :disabled="!hasPreviousImage" @click="showPreviousImage">
          <el-icon><ArrowLeft /></el-icon>
          上一张
        </el-button>
        <div class="jump-control">
          <span class="jump-label">跳转至第</span>
          <input
            class="jump-input"
            type="number"
            :min="1"
            :max="totalImageCount"
            v-model.number="jumpIndex"
            @keyup.enter="goToImage"
          />
          <span class="jump-label">张</span>
          <el-button size="small" type="primary" plain @click="goToImage">跳转</el-button>
        </div>
        <el-button size="small" :disabled="!hasNextImage" @click="showNextImage">
          下一张
          <el-icon><ArrowRight /></el-icon>
        </el-button>
      </div>
    </div>

    <div class="workspace" v-if="imageFiles.length || serverImages.length">
      <div class="viewer-area">
        <div class="viewer-header">
          <div class="viewer-tabs">
            <button :class="{ active: viewMode === 'compare' }" @click="viewMode = 'compare'">对比视图</button>
            <button :class="{ active: viewMode === 'result' }" @click="viewMode = 'result'">仅看结果</button>
          </div>
          <div class="viewer-info" v-if="currentDisplayName">
            <span class="filename">{{ currentDisplayName }}</span>
            <el-tag v-if="serverMode && currentServerImage?.guessed_category" size="small" type="info">
              {{ currentServerImage.guessed_category }}
              <span v-if="currentServerImage?.classification_confidence > 0" style="margin-left:4px;opacity:0.85">
                {{ (currentServerImage.classification_confidence * 100).toFixed(0) }}%
              </span>
            </el-tag>
            <span class="detect-time" v-if="processingTime">检测耗时 {{ processingTime }}ms</span>
          </div>
        </div>

        <div class="image-stage">
          <div class="image-panel" :class="{ half: viewMode === 'compare', full: viewMode === 'result' }">
            <div class="image-label">原始图片</div>
            <div class="image-wrapper">
              <img v-if="originalImage" :src="originalImage" class="preview-img" />
              <div v-else class="empty-state">
                <el-icon :size="40"><Picture /></el-icon>
                <span>未加载图片</span>
              </div>
            </div>
          </div>

          <div class="image-panel result-panel" :class="{ half: viewMode === 'compare', hidden: viewMode !== 'compare' }">
            <div class="image-label">
              检测结果
              <span v-if="detectionData.length" class="badge">{{ detectionData.length }}个目标</span>
            </div>
            <div class="image-wrapper">
              <div v-if="detecting" class="loading-overlay">
                <div class="spinner"></div>
                <span>AI 正在分析中...</span>
              </div>
              <img v-else-if="detectedImage" :src="detectedImage" class="preview-img" />
              <div v-else class="empty-state">
                <el-icon :size="40"><PictureFilled /></el-icon>
                <span>点击"开始检测"</span>
              </div>
            </div>
          </div>
        </div>

        <div class="filmstrip" v-if="totalImageCount > 1">
          <div
            v-for="(item, idx) in allImageDisplayNames"
            :key="idx"
            class="filmstrip-item"
            :class="{ active: idx === currentImageIndex }"
            @click="selectImage(idx)"
            :title="item"
          >
            <span class="filmstrip-name">{{ item }}</span>
          </div>
        </div>
      </div>

      <aside class="sidebar">
        <div class="action-card">
          <el-button
            type="primary"
            size="large"
            @click="handleDetect"
            :loading="detecting"
            :disabled="!hasCurrentImage"
            class="detect-btn"
          >
            <el-icon v-if="!detecting"><VideoPlay /></el-icon>
            {{ detecting ? '检测中...' : '开始检测' }}
          </el-button>
          <el-button
            v-if="detectionResult"
            type="success"
            size="large"
            @click="downloadResults"
            class="export-btn"
          >
            <el-icon><Download /></el-icon>
            导出结果
          </el-button>
        </div>

        <div class="stats-grid" v-if="detectionResult?.data?.class_counts">
          <h4 class="section-label">检测统计</h4>
          <div
            v-for="(category, name) in detectionResult.data.class_counts"
            :key="name"
            class="stat-item"
          >
            <span class="stat-dot" :style="{ background: categoryColors[name] || '#6366f1' }"></span>
            <span class="stat-name">{{ name }}</span>
            <span class="stat-num">{{ category.count }}</span>
          </div>
        </div>

        <div class="detection-list" v-if="detectionData.length">
          <h4 class="section-label">检测列表</h4>
          <div
            v-for="(item, idx) in detectionData"
            :key="idx"
            class="detection-item"
            @mouseenter="highlightBbox(item.bbox)"
            @mouseleave="highlightBbox(null)"
          >
            <span class="item-color" :style="{ background: categoryColors[item.category] || '#6366f1' }"></span>
            <div class="item-info">
              <span class="item-class">{{ item.class }}</span>
              <span class="item-category">{{ item.category }}</span>
            </div>
            <span class="item-confidence">{{ (item.confidence * 100).toFixed(0) }}%</span>
          </div>
        </div>

      </aside>
    </div>

    <div class="upload-hero" v-else>
      <div class="hero-icon">
        <svg viewBox="0 0 80 80" fill="none" width="80" height="80">
          <rect x="8" y="20" width="64" height="50" rx="6" stroke="#c7d2fe" stroke-width="2" fill="#eef2ff"/>
          <path d="M8 54l16-16 12 12 16-16 20 14" stroke="#818cf8" stroke-width="2" fill="none"/>
          <circle cx="30" cy="34" r="4" fill="#6366f1"/>
        </svg>
      </div>
      <h2 class="hero-title">布置图检测</h2>
      <p class="hero-desc">先在"投标文件解析"中上传 .docx 文件，然后在此加载布置图进行检测，也支持直接打开本地图片文件夹</p>
      <div class="hero-actions">
        <el-button
          v-if="parsedInfo"
          type="primary"
          size="large"
          @click="loadAllFromParsedFolder"
        >
          <el-icon><FolderOpened /></el-icon>
          加载所有图片 ({{ parsedInfo.image_count }} 张)
        </el-button>
        <el-button
          v-if="parsedInfo"
          type="success"
          size="large"
          plain
          @click="loadFilteredFromParsedFolder"
        >
          <el-icon><FolderOpened /></el-icon>
          只加载有类别图片
        </el-button>
        <label class="hero-btn">
          <el-icon :size="20"><FolderAdd /></el-icon>
          <span>选择本地图片文件夹</span>
          <input type="file" ref="folderInput2" @change="handleFolderSelect" webkitdirectory directory hidden />
        </label>
      </div>
    </div>

    <!-- Docs 文件夹选择对话框 -->
    <el-dialog v-model="showDocsDialog" title="从 docs 文件夹选择投标文件" width="520px" :close-on-click-modal="false">
      <div class="docs-dialog-body">
        <div class="docs-folder-path">
          <el-icon :size="14"><Folder /></el-icon>
          <span>{{ docsFolder }}</span>
        </div>
        <div class="docs-empty" v-if="docsFiles.length === 0 && !docsLoading">
          <el-icon :size="32"><FolderOpened /></el-icon>
          <p>docs 文件夹为空，请将 .doc / .docx 文件放入项目根目录下的 docs 文件夹</p>
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
        <el-button type="primary" @click="processDocsFile" :disabled="!selectedDocsFile" :loading="docsProcessing">
          解析并加载图片
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import {
  FolderAdd, FolderOpened, VideoPlay, Download, Delete,
  Picture, PictureFilled, ArrowLeft, ArrowRight, Document,
  Check, Loading, Folder
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
const folderInput = ref<HTMLInputElement | null>(null)
const folderInput2 = ref<HTMLInputElement | null>(null)

interface FileNode { name: string; path: string; type: 'file' | 'directory'; children?: FileNode[]; raw?: File }
interface ServerImage { filename: string; size: number; url: string; figure_name?: string; guessed_category?: string; page_number?: number; index?: number }
interface DetectionItem { class: string; confidence: number; bbox: number[]; category: string }

const fileTreeData = ref<FileNode[]>([])
const imageFiles = ref<FileNode[]>([])
const currentImageIndex = ref(-1)
const currentFile = ref<any>(null)
const detecting = ref(false)
const processingTime = ref(0)
const detectionResult = ref<any>(null)
const detectionData = ref<DetectionItem[]>([])
const originalImage = ref('')
const detectedImage = ref('')
const viewMode = ref<'compare' | 'result'>('compare')

// Server-side parsed folder state
const serverMode = ref(false)
const parsedTaskId = ref('')
const parsedFolder = ref('')
const serverImages = ref<ServerImage[]>([])
const parsedInfo = ref<any>(null)

const totalImageCount = computed(() => {
  if (serverMode.value) return serverImages.value.length
  return imageFiles.value.length
})

const allImageDisplayNames = computed(() => {
  if (serverMode.value) return serverImages.value.map(s => s.figure_name || s.filename)
  return imageFiles.value.map(f => f.name)
})

const currentServerImage = computed(() => {
  if (serverMode.value && serverImages.value[currentImageIndex.value]) {
    return serverImages.value[currentImageIndex.value]
  }
  return null
})

const currentDisplayName = computed(() => {
  if (currentServerImage.value) {
    return currentServerImage.value.figure_name || currentServerImage.value.filename
  }
  if (currentFile.value) return currentFile.value.name
  return ''
})

const hasCurrentImage = computed(() => {
  if (serverMode.value) return currentImageIndex.value >= 0 && currentImageIndex.value < serverImages.value.length
  return !!currentFile.value
})

const hasPreviousImage = computed(() => currentImageIndex.value > 0)
const hasNextImage = computed(() => currentImageIndex.value < totalImageCount.value - 1)

// Docs folder dialog
const showDocsDialog = ref(false)
const docsFiles = ref<any[]>([])
const docsLoading = ref(false)
const docsProcessing = ref(false)
const selectedDocsFile = ref('')
const docsFolder = ref('')

const formatFileSize = (bytes: number) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

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

const processDocsFile = async () => {
  if (!selectedDocsFile.value) return
  docsProcessing.value = true
  try {
    const res = await axios.post('/api/docx/upload-from-docs', {
      filename: selectedDocsFile.value,
    })
    if (res.data.success) {
      showDocsDialog.value = false
      if (res.data.status === 'processing') {
        // 轮询等待后台处理完成
        const tid = res.data.task_id
        const startTime = Date.now()
        const POLL_INTERVAL = 1500
        const MAX_WAIT = 300000
        await new Promise<void>((resolve, reject) => {
          const poll = async () => {
            const elapsed = Math.round((Date.now() - startTime) / 1000)
            try {
              const statusRes = await axios.get(`/api/docx/status/${tid}`)
              if (statusRes.data.status === 'extracted') {
                resolve()
              } else if (statusRes.data.status === 'error') {
                reject(new Error('解析失败，请重试'))
              } else if (Date.now() - startTime > MAX_WAIT) {
                reject(new Error('解析超时，请稍后重试'))
              } else {
                setTimeout(poll, POLL_INTERVAL)
              }
            } catch {
              if (Date.now() - startTime > MAX_WAIT) {
                reject(new Error('解析超时'))
              } else {
                setTimeout(poll, POLL_INTERVAL)
              }
            }
          }
          poll()
        })
      }
      // 加载解析结果
      await loadFromParsedFolderById(res.data.task_id)
    } else {
      ElMessage.error(res.data.error || '解析失败')
    }
  } catch (err: any) {
    ElMessage.error(err.response?.data?.error || err.message || '解析失败')
  } finally {
    docsProcessing.value = false
  }
}

const categoryColors: Record<string, string> = {
  '垂直运输机械': '#ef4444',
  '施工机械': '#f97316',
  '临时设施-生活及办公区': '#22c55e',
  '临时设施-生产加工区': '#3b82f6',
  '临时设施-辅助设施': '#a855f7',
  '基础设施': '#eab308',
  '其他': '#64748b',
}

const isImageFile = (name: string) => /\.(jpg|jpeg|png|bmp|webp)$/i.test(name)

const buildFileTree = (files: File[]): FileNode[] => {
  const tree: FileNode[] = []
  const map = new Map<string, FileNode>()
  files.forEach(file => {
    const path = file.webkitRelativePath || file.name
    const parts = path.split('/')
    let currentPath = ''
    let parent: FileNode | null = null
    parts.forEach((part, idx) => {
      currentPath = idx === 0 ? part : `${currentPath}/${part}`
      if (idx === parts.length - 1) {
        const node: FileNode = { name: part, path: currentPath, type: 'file', raw: file }
        map.set(currentPath, node)
        if (parent) { parent.children = parent.children || []; parent.children.push(node) }
        else { tree.push(node) }
      } else {
        let dirNode = map.get(currentPath)
        if (!dirNode) {
          dirNode = { name: part, path: currentPath, type: 'directory', children: [] }
          map.set(currentPath, dirNode)
          if (parent) { parent.children = parent.children || []; parent.children.push(dirNode) }
          else { tree.push(dirNode) }
        }
        parent = dirNode
      }
    })
  })
  return tree
}

const getAllImageFiles = (tree: FileNode[]): FileNode[] => {
  const files: FileNode[] = []
  const walk = (nodes: FileNode[]) => nodes.forEach(n => {
    if (n.type === 'file' && n.raw && isImageFile(n.name)) files.push(n)
    else if (n.children) walk(n.children)
  })
  walk(tree)
  return files
}

const fetchParsedFolder = async () => {
  try {
    const res = await axios.get('/api/docx/parsed-folder')
    if (res.data.success) {
      parsedInfo.value = res.data
    }
  } catch {}
}

const loadImagesFromParsed = async (filtered: boolean) => {
  if (!parsedInfo.value) return
  try {
    const params = filtered ? {} : { all: 'true' }
    const res = await axios.get(`/api/docx/parsed-images/${parsedInfo.value.task_id}`, { params })
    if (res.data.success && res.data.images.length > 0) {
      serverMode.value = true
      parsedTaskId.value = res.data.task_id
      parsedFolder.value = parsedInfo.value.folder

      let images = res.data.images
      if (filtered) {
        images = images.filter((img: any) => {
          const cat = img.guessed_category || ''
          return cat && cat !== '其他' && cat !== '未分类'
        })
      }

      serverImages.value = images.map((img: any) => ({
        ...img,
        figure_name: img.figure_name || '',
        guessed_category: img.guessed_category || '其他',
        classification_confidence: img.classification_confidence || 0,
        page_number: img.page_number || 1,
      }))
      imageFiles.value = []
      clearResults()
      currentImageIndex.value = 0
      selectImage(0)
      const msg = filtered
        ? `已加载 ${serverImages.value.length} 张布置图（已过滤无类别）`
        : `已加载全部 ${serverImages.value.length} 张图片`
      ElMessage.success(msg)
    } else {
      ElMessage.warning('解析文件夹中没有图片')
    }
  } catch (err: any) {
    ElMessage.error('加载解析图片失败')
  }
}

const loadAllFromParsedFolder = () => loadImagesFromParsed(false)
const loadFilteredFromParsedFolder = () => loadImagesFromParsed(true)

const loadFromParsedFolderById = async (tid: string, filtered: boolean = true) => {
  try {
    const params = filtered ? {} : { all: 'true' }
    const res = await axios.get(`/api/docx/parsed-images/${tid}`, { params })
    if (res.data.success && res.data.images.length > 0) {
      serverMode.value = true
      parsedTaskId.value = res.data.task_id
      try {
        const folderRes = await axios.get('/api/docx/parsed-folder')
        if (folderRes.data.success) {
          parsedInfo.value = folderRes.data
          parsedFolder.value = folderRes.data.folder || parsedFolder.value
        }
      } catch {}

      let images = res.data.images
      if (filtered) {
        images = images.filter((img: any) => {
          const cat = img.guessed_category || ''
          return cat && cat !== '其他' && cat !== '未分类'
        })
      }

      serverImages.value = images.map((img: any) => ({
        ...img,
        figure_name: img.figure_name || '',
        guessed_category: img.guessed_category || '其他',
        classification_confidence: img.classification_confidence || 0,
        page_number: img.page_number || 1,
      }))
      imageFiles.value = []
      clearResults()
      currentImageIndex.value = 0
      selectImage(0)
      const msg = filtered
        ? `已加载 ${serverImages.value.length} 张布置图（已过滤无类别）`
        : `已加载全部 ${serverImages.value.length} 张图片`
      ElMessage.success(msg)
    } else {
      ElMessage.warning('解析文件夹中没有图片')
    }
  } catch (err: any) {
    ElMessage.error('加载解析图片失败')
  }
}

const handleFolderSelect = (event: Event) => {



  const target = event.target as HTMLInputElement
  const files = Array.from(target.files || []).filter(f => isImageFile(f.name))
  if (!files.length) { ElMessage.warning('未找到图片文件'); return }
  const tree = buildFileTree(files)
  fileTreeData.value = tree
  imageFiles.value = getAllImageFiles(tree)
  serverMode.value = false
  serverImages.value = []
  target.value = ''
  if (imageFiles.value.length) {
    currentImageIndex.value = 0
    selectImage(0)
  }
  ElMessage.success(`已加载 ${imageFiles.value.length} 张本地图片`)
}

const selectImage = async (idx: number) => {
  const total = totalImageCount.value
  if (idx < 0 || idx >= total) return
  currentImageIndex.value = idx
  jumpIndex.value = idx + 1
  clearResults()

  if (serverMode.value) {
    const simg = serverImages.value[idx]
    if (!simg) return
    currentFile.value = null
    originalImage.value = simg.url
    await nextTick()
  } else {
    const fileNode = imageFiles.value[idx]
    if (!fileNode?.raw) return
    const rawFile = new File([fileNode.raw], fileNode.raw.name, { type: fileNode.raw.type, lastModified: fileNode.raw.lastModified }) as any
    rawFile.uid = Date.now()
    currentFile.value = { name: fileNode.name, raw: rawFile, uid: rawFile.uid, status: 'success' }
    originalImage.value = URL.createObjectURL(fileNode.raw)
    await nextTick()
  }

  // 选中/切换图片后自动发起检测
  handleDetect()
}

const showPreviousImage = () => { if (hasPreviousImage.value) selectImage(currentImageIndex.value - 1) }
const showNextImage = () => { if (hasNextImage.value) selectImage(currentImageIndex.value + 1) }

const jumpIndex = ref(1)
const goToImage = () => {
  const idx = jumpIndex.value - 1
  if (idx >= 0 && idx < totalImageCount.value) {
    selectImage(idx)
  } else {
    ElMessage.warning(`请输入 1 ~ ${totalImageCount.value} 之间的数字`)
  }
}

const handleDetect = async () => {
  if (serverMode.value) {
    await handleDetectServer()
  } else {
    await handleDetectLocal()
  }
}

const handleDetectServer = async () => {
  const simg = serverImages.value[currentImageIndex.value]
  if (!simg) { ElMessage.warning('请先选择图片'); return }
  detecting.value = true
  const startTime = Date.now()
  try {
    const filePath = parsedFolder.value + '/' + simg.filename
    const response = await axios.post('/api/detection/detect-by-path', { file_path: filePath })
    if (response.data.success) {
      processingTime.value = Date.now() - startTime
      detectionResult.value = response.data
      detectionData.value = response.data.data.detections
      detectedImage.value = `data:image/png;base64,${response.data.data.detected_image}`
      ElMessage.success(`检测完成，发现 ${detectionData.value.length} 个目标`)
    } else {
      ElMessage.error(response.data.error || '检测失败')
    }
  } catch (err: any) {
    ElMessage.error(err.response?.data?.error || err.message || '检测失败')
  } finally {
    detecting.value = false
  }
}

const handleDetectLocal = async () => {
  if (!currentFile.value) { ElMessage.warning('请先选择图片'); return }
  detecting.value = true
  const startTime = Date.now()
  try {
    const formData = new FormData()
    formData.append('file', currentFile.value.raw)
    const response = await axios.post('/api/detection/detect', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
    if (response.data.success) {
      processingTime.value = Date.now() - startTime
      detectionResult.value = response.data
      detectionData.value = response.data.data.detections
      detectedImage.value = `data:image/png;base64,${response.data.data.detected_image}`
      ElMessage.success(`检测完成，发现 ${detectionData.value.length} 个目标`)
    } else {
      ElMessage.error(response.data.error || '检测失败')
    }
  } catch (err: any) {
    ElMessage.error(err.response?.data?.error || err.message || '检测失败')
  } finally {
    detecting.value = false
  }
}

const highlightBbox = (bbox: number[] | null) => {}
const clearResults = () => {
  detectedImage.value = ''
  detectionResult.value = null
  detectionData.value = []
  processingTime.value = 0
}

const downloadResults = () => {
  ElMessageBox.confirm('请选择导出方式', '导出结果', { confirmButtonText: '导出图片', cancelButtonText: '导出JSON', distinguishCancelAndClose: true, type: 'info' })
    .then(() => {
      if (!detectedImage.value) return
      const a = document.createElement('a')
      a.href = detectedImage.value
      a.download = `result_${Date.now()}.png`
      a.click()
      ElMessage.success('图片已导出')
    })
    .catch((action: string) => {
      if (action !== 'cancel') return
      if (!detectionResult.value) return
      const blob = new Blob([JSON.stringify(detectionResult.value, null, 2)], { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `result_${Date.now()}.json`
      a.click()
      ElMessage.success('JSON已导出')
    })
}

onMounted(() => {
  fetchParsedFolder()
})

onUnmounted(() => {
  if (originalImage.value && originalImage.value.startsWith('blob:')) {
    URL.revokeObjectURL(originalImage.value)
  }
})
</script>

<style scoped>
.detection-panel { display: flex; flex-direction: column; gap: 16px; }

.parsed-banner {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 20px; background: #f0fdf4; border: 1px solid #bbf7d0;
  border-radius: 10px; font-size: 14px; color: #166534;
}
.parsed-banner-left { display: flex; align-items: center; gap: 8px; }
.parsed-banner-left strong { color: #15803d; }
.parsed-banner-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

.toolbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 20px; background: white; border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06);
}

.toolbar-left { display: flex; align-items: center; gap: 12px; }

.upload-trigger {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; background: #6366f1; color: white; border-radius: 8px;
  font-size: 14px; font-weight: 500; cursor: pointer; transition: background .2s;
}
.upload-trigger:hover { background: #4f46e5; }

.file-count { font-size: 13px; color: #64748b; }

.toolbar-right { display: flex; align-items: center; gap: 12px; }

.jump-control { display: flex; align-items: center; gap: 6px; }
.jump-label { font-size: 12px; color: #64748b; white-space: nowrap; }
.jump-input {
  width: 60px; padding: 4px 8px; border: 1px solid #d1d5db; border-radius: 6px;
  font-size: 13px; text-align: center; color: #1e293b; outline: none;
}
.jump-input:focus { border-color: #6366f1; box-shadow: 0 0 0 2px rgba(99,102,241,.15); }
.jump-input::-webkit-inner-spin-button,
.jump-input::-webkit-outer-spin-button { opacity: 1; }

.workspace { display: flex; gap: 16px; min-height: calc(100vh - 200px); }

.viewer-area { flex: 1; display: flex; flex-direction: column; gap: 12px; min-width: 0; }

.viewer-header {
  display: flex; align-items: center; justify-content: space-between;
  background: white; border-radius: 10px; padding: 8px 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06);
}

.viewer-tabs { display: flex; gap: 4px; }
.viewer-tabs button {
  padding: 6px 14px; border: none; background: transparent; border-radius: 6px;
  font-size: 13px; color: #64748b; cursor: pointer; transition: all .15s;
}
.viewer-tabs button.active { background: #eef2ff; color: #4f46e5; font-weight: 600; }

.viewer-info { display: flex; align-items: center; gap: 16px; }
.filename { font-size: 13px; color: #334155; font-weight: 500; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detect-time { font-size: 12px; color: #94a3b8; }

.image-stage { display: flex; gap: 12px; flex: 1; min-height: 400px; }

.image-panel {
  background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.06);
  display: flex; flex-direction: column; overflow: hidden;
}
.image-panel.half { flex: 1; }
.image-panel.full { flex: 1; }
.image-panel.hidden { display: none; }

.image-label {
  padding: 10px 16px; font-size: 13px; font-weight: 600; color: #475569;
  border-bottom: 1px solid #f1f5f9; display: flex; align-items: center; gap: 8px;
  flex-shrink: 0;
}
.result-panel .image-label { color: #059669; }
.badge { font-size: 11px; background: #d1fae5; color: #059669; padding: 2px 8px; border-radius: 10px; font-weight: 500; }

.image-wrapper {
  flex: 1; display: flex; align-items: center; justify-content: center;
  background: #f8fafc; position: relative; overflow: hidden; padding: 16px;
}
.preview-img { max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 4px; }

.empty-state {
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  color: #94a3b8; font-size: 14px;
}

.loading-overlay {
  display: flex; flex-direction: column; align-items: center; gap: 14px;
  color: #6366f1; font-size: 14px; font-weight: 500;
}
.spinner {
  width: 36px; height: 36px; border: 3px solid #e0e7ff;
  border-top-color: #6366f1; border-radius: 50%; animation: spin .7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.filmstrip {
  display: flex; gap: 6px; overflow-x: auto; padding: 8px 4px;
  background: white; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.06);
}
.filmstrip-item {
  padding: 6px 12px; white-space: nowrap; font-size: 12px; color: #64748b;
  border-radius: 6px; cursor: pointer; transition: all .15s; border: 1px solid transparent;
}
.filmstrip-item:hover { background: #f1f5f9; }
.filmstrip-item.active { background: #eef2ff; color: #4f46e5; border-color: #c7d2fe; font-weight: 600; }
.filmstrip-name { max-width: 120px; display: inline-block; overflow: hidden; text-overflow: ellipsis; }

.sidebar {
  width: 320px; flex-shrink: 0; display: flex; flex-direction: column; gap: 14px;
}

.action-card {
  background: white; border-radius: 12px; padding: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06); display: flex; flex-direction: column; gap: 10px;
}
.detect-btn,
.export-btn {
  width: 100% !important;
  height: 44px !important;
  display: flex !important;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  font-weight: 600;
}
.export-btn { margin-left: 0px !important; }

.section-label {
  font-size: 12px; font-weight: 700; color: #94a3b8; text-transform: uppercase;
  letter-spacing: 0.8px; margin-bottom: 8px;
}

.stats-grid {
  background: white; border-radius: 12px; padding: 14px 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06);
}
.stat-item {
  display: flex; align-items: center; gap: 8px; padding: 6px 0;
  font-size: 13px; color: #334155;
}
.stat-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.stat-name { flex: 1; }
.stat-num { font-weight: 700; color: #1e293b; }

.detection-list {
  background: white; border-radius: 12px; padding: 14px 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06); max-height: 300px; overflow-y: auto;
}
.detection-item {
  display: flex; align-items: center; gap: 10px; padding: 8px 0;
  border-bottom: 1px solid #f1f5f9; cursor: pointer; transition: background .15s;
}
.detection-item:last-child { border-bottom: none; }
.detection-item:hover { background: #f8fafc; border-radius: 6px; padding-left: 6px; padding-right: 6px; }
.item-color { width: 4px; height: 28px; border-radius: 2px; flex-shrink: 0; }
.item-info { flex: 1; display: flex; flex-direction: column; gap: 1px; }
.item-class { font-size: 13px; font-weight: 600; color: #1e293b; }
.item-category { font-size: 11px; color: #94a3b8; }
.item-confidence {
  font-size: 12px; font-weight: 700; color: #6366f1;
  background: #eef2ff; padding: 2px 8px; border-radius: 6px;
}

.upload-hero {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  height: calc(100vh - 160px); text-align: center; gap: 16px;
}
.hero-icon { margin-bottom: 4px; }
.hero-title { font-size: 20px; font-weight: 700; color: #1e293b; }
.hero-desc { font-size: 14px; color: #94a3b8; max-width: 500px; line-height: 1.6; }
.hero-actions { display: flex; flex-direction: column; align-items: center; gap: 12px; margin-top: 8px; }
.hero-btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 14px 32px; background: #6366f1; color: white; border-radius: 10px;
  font-size: 15px; font-weight: 600; cursor: pointer; transition: all .2s;
  box-shadow: 0 4px 14px rgba(99,102,241,.35);
}
.hero-btn:hover { background: #4f46e5; transform: translateY(-1px); box-shadow: 0 6px 20px rgba(99,102,241,.4); }

/* Docs dialog */
.docs-dialog-body { min-height: 180px; }
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
</style>
