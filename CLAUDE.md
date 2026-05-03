# 建筑图纸分析系统（海南机器管招投标项目）

## 技术栈

- **后端**: Python Flask, venv (`C:\Users\wint\Desktop\yolov11\venv`)
- **前端**: Vue 3 + Vite + Element Plus (`frontend\node_modules`)
- **启动**: 双击 `start.bat`（自动激活 venv → 后端 :5000 → 前端 :8080）
- **Python 环境**: `venv\Scripts\python`，依赖见 `backend\requirements-minimal.txt`

## 项目结构

```
yolov11/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── docx.py          # 文档分析 API（上传/批量分析/单张分析/SSE/报告）
│   │   │   └── detection.py     # YOLO 检测 API
│   │   ├── services/
│   │   │   ├── ai_analysis_service.py  # AI 分析（SiliconFlow API 调用）
│   │   │   ├── ai_cache.py            # 图片 MD5 缓存
│   │   │   ├── docx_service.py        # .docx 图片提取 + 压缩
│   │   │   ├── task_service.py        # 任务持久化 + 报告生成
│   │   │   ├── detection.py           # YOLO 检测逻辑
│   │   │   └── rules_checker.py       # 12 条 Shapely 规范检查规则
│   │   ├── config.py            # 配置（从 .env 读取）
│   │   └── main.py              # Flask 应用入口
│   ├── cache_ai/                # AI 缓存目录（不提交）
│   ├── tasks/                   # 任务数据（不提交）
│   └── run.py                   # 启动脚本
├── frontend/
│   └── src/
│       ├── App.vue              # 主布局（免责声明 + Tab 切换）
│       └── components/
│           ├── DetectionPanel.vue      # 图片检测页
│           ├── DocumentAnalysis.vue    # 文档分析页（核心组件）
│           └── RulesCheckResult.vue    # 规范检查结果展示
├── .env                      # 环境变量（API Keys / 模型配置）
├── .gitignore
└── start.bat
```

## 核心功能

### 1. YOLO 目标检测（单张图片）
- `POST /api/detection/detect` — 上传图片，返回检测结果 + base64 标注图
- `GET /api/detection/model/status` — 模型加载状态

### 2. 文档分析管道（.docx → 提取图片 → AI 分析 → 汇总报告）
- `POST /api/docx/upload` — 上传 .docx，提取图片，任务 ID=文件名去重，MD5 二次校验
- `POST /api/docx/analyze/<id>` — 批量分析（仅处理未分析+失败的图，已成功的跳过）
- `POST /api/docx/analyze-single/<id>/<index>` — 单张分析
- `GET /api/docx/status/<id>/stream` — SSE 实时进度（事件类型: analyzing/progress/summarizing/done/snapshot）
- `GET /api/docx/image/<id>/<filename>` — 查看提取的图片
- `GET /api/docx/report/<id>/html` — 打印版 HTML 报告（含自动弹出打印对话框）
- `GET /api/docx/tasks` / `POST /api/docx/task/<id>/load` / `DELETE /api/docx/task/<id>`

### 3. 汇总报告（数据驱动 + AI 补充）
- 主报告由代码生成，数字 100% 准确（类型统计、评级分布、关键参数汇总）
- 可选 AI 补充评审意见（LLM 失败不影响报告完整性）
- `SILICONFLOW_SUMMARY_MODEL` 指定文本模型，默认 `Qwen/Qwen2.5-7B-Instruct`

### 4. 施工规范检查
- 12 条几何规则（Shapely），如塔吊覆盖、大门-道路连接等

## AI 分析服务 (`ai_analysis_service.py`)

- **API**: SiliconFlow (`api.siliconflow.cn`)，5 个 Key 轮换
- **视觉模型**: `zai-org/GLM-4.6V`（主）+ `zai-org/GLM-4.5V`（备），通过 `SILICONFLOW_VISION_MODEL` + `SILICONFLOW_VISION_MODELS` 配置
- **压缩策略**: 先发压缩图（长边 2048px/JPEG 85），失败降级原图（但原图 > 5MB 直接跳过）
- **超时与重试**: `BASE_TIMEOUT=75s`, `MAX_RETRIES_PER_CANDIDATE=1`（2 次尝试/候选图）
- **容错**: 403 拉黑 Key+Model, 429 等 5s, 指数退避, 错误分类标记
- **JSON 解析**: 括号匹配提取 + 多轮修复（去尾逗号），失败用关键词匹配分类
- **缓存**: 图片 MD5 缓存到 `backend/cache_ai/`，同图跨文档复用
- **分类体系**: 总平面布置图、基础结构图、主体结构图、土方工程图、进度计划图、施工计划图、分区规划图、施工分区图、临时用电布置图、临时用水布置图、临建设施平面布置图、装饰装修图、周边环境图

## 前端特性（近期新增）

- **AI 免责声明**: 顶部导航栏下方橘色警示条
- **分析异常提示**: 有异常图片时显示红色横幅 + 单张异常提示
- **待分析计数**: 状态栏显示"待分析 N"橙色标签
- **进度百分比**: 批量分析时显示进度条，百分比仅计算待处理图片
- **队列状态可视化**: 每张图片左上角彩色状态点（灰=等待/紫脉冲=分析中/绿=成功/红=异常）
- **Markdown 报告渲染**: 汇总报告使用 `marked` 渲染表格、标题、引用等
- **一键导出 PDF**: 汇总报告右上角按钮，新标签页打开打印版 → 自动弹出打印对话框

## .env 配置说明

```
SILICONFLOW_API_KEYS=key1,key2,...          # API Key 列表（逗号分隔）
SILICONFLOW_API_URL=https://api.siliconflow.cn/v1/chat/completions
SILICONFLOW_VISION_MODEL=zai-org/GLM-4.6V   # 主视觉模型
SILICONFLOW_VISION_MODELS=zai-org/GLM-4.5V  # 备选视觉模型（逗号分隔）
SILICONFLOW_SUMMARY_MODEL=Qwen/Qwen2.5-7B-Instruct  # 汇总用文本模型
IMAGE_COMPRESSION_ENABLED=true
IMAGE_MAX_DIMENSION=2048
IMAGE_JPEG_QUALITY=85
AI_CACHE_ENABLED=true
DEBUG=true
```

## 已知问题

1. 网络不稳定时部分图片仍会分析失败，降级显示具体错误原因
2. LLM 返回的 `evaluation` 字段格式不统一（string/dict 混排），代码已做归一化处理
3. 部分 docx 中的 PNG 图片可能非常大（100MB+），压缩后 JPEG ~400KB，原图跳过不发送
4. venv 用 Python 3.13，部分依赖边缘兼容

## 代码约定

- 所有 AI 结果字段（`summary`, `evaluation`）取值前必须通过 `_safe_str()` 归一化，避免 dict/string 混排导致切片崩溃
- 汇总报告统计数据必须由代码计算，不依赖 LLM 输出数字
- 新增 API 端点注册在对应的 Blueprint 中
- 前端状态管理用 Vue 3 Composition API（`ref`/`computed`），不引入额外状态库
