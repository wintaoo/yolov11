# 系统设计文档

## 1. 系统概述

建筑图纸分析系统是一个面向施工招投标场景的智能分析平台，主要用于自动化检测施工平面布置图中的设施与元素，检查施工规范合规性，并对 Word 格式的施工方案文档中的图纸进行多模态 AI 分析。

**应用场景**：海南机器管招投标项目 — 施工方案评审与图纸合规性检查。

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     浏览器前端 (Vue 3)                       │
│  DetectionPanel │ DocumentAnalysis │ RulesCheckResult      │
│  Element Plus UI  │  Axios HTTP Client                     │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP REST API
┌──────────────────────┴──────────────────────────────────────┐
│                    Flask 后端服务 (:5000)                     │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ detection.py │  │   docx.py    │  │   main.py       │  │
│  │ /api/detect  │  │ /api/docx/*  │  │ /api/detection/ │  │
│  │ /api/analyze │  │              │  │ /api/check-rules│  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                 │                    │            │
│  ┌──────┴─────────────────┴────────────────────┴─────────┐  │
│  │                   Services Layer                       │  │
│  │  ┌──────────────┐  ┌───────────────┐  ┌────────────┐  │  │
│  │  │ detection.py │  │rules_checker  │  │docx_service │  │  │
│  │  │ (YOLO推理)   │  │ (Shapely几何) │  │ (OPC解析)   │  │  │
│  │  └──────────────┘  └───────────────┘  └────────────┘  │  │
│  │  ┌──────────────────────────────────────────────┐     │  │
│  │  │      ai_analysis_service.py                   │     │  │
│  │  │      (SiliconFlow GLM-4.6V / Qwen2.5)        │     │  │
│  │  └──────────────────────────────────────────────┘     │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                    Data Layer                          │  │
│  │  models/ │ uploads/ │ docx_images/ │ .env (secrets)    │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   External Services                          │
│         SiliconFlow API (GLM-4.6V / Qwen2.5-7B)            │
└─────────────────────────────────────────────────────────────┘
```

## 3. 核心模块设计

### 3.1 图片检测模块 (Detection)

**入口**: `POST /api/detection/detect`

**流程**:
```
上传图片 → YOLO 模型推理 → 结果解析 (坐标/类别/置信度) → 规则检查 → JSON 响应
```

**关键类**:

- `DetectionService` (单例模式，[detection.py](file:///c:/Users/wint/Desktop/yolov11/backend/app/services/detection.py))
  - `load_model()`: 加载 YOLO 模型
  - `process_image()`: 图片预处理 + 推理 + 后处理
  - `switch_model()`: 运行时切换模型文件
  - `get_model_status()`: 获取模型加载状态

- `RulesChecker` ([rules_checker.py](file:///c:/Users/wint/Desktop/yolov11/backend/app/services/rules_checker.py))
  - 基于规则的施工规范检查引擎
  - 使用 Shapely 进行几何空间关系计算 (点/多边形包含、距离等)
  - 支持规则: 钢筋加工场设置、塔吊覆盖范围、大门道路连通、消防设施等

**检测类别 (12类)**:
起重机、塔吊、挖掘机、搅拌机、钢筋加工厂、宿舍、办公室、厕所、大门、红线、道路、楼梯

### 3.2 文档分析模块 (Document Analysis)

**入口**: `POST /api/docx/upload` → `POST /api/docx/analyze`

**流程**:
```
上传 .docx → python-docx OPC 解析 → 提取内嵌图片 → 
猜测分类(关键词匹配) → GLM-4.6V 多模态分析 → 
Qwen2.5-7B 生成汇总报告
```

**关键类**:

- `extract_images_from_docx()` ([docx_service.py](file:///c:/Users/wint/Desktop/yolov11/backend/app/services/docx_service.py))
  - 通过 OPC Relationships 方式提取文档内嵌图片 (不走 XML 解析)
  - 提取图片上下文文字 (前后段落)
  - `guess_category_from_context()`: 关键词匹配初分类

- `analyze_image_with_ai()` ([ai_analysis_service.py](file:///c:/Users/wint/Desktop/yolov11/backend/app/services/ai_analysis_service.py))
  - Base64 编码图片 → SiliconFlow GLM-4.6V API
  - 结构化 JSON 输出: 类型/摘要/评价/设施/工期/尺寸
  - 13 种图纸类型识别

- `generate_summary()` ([docx.py](file:///c:/Users/wint/Desktop/yolov11/backend/app/api/docx.py))
  - 汇总所有单图分析结果
  - 调用 Qwen2.5-7B-Instruct 生成结构化报告

### 3.3 API 路由设计

| 蓝图 | 前缀 | 说明 |
|------|------|------|
| `detection_bp` | `/api/detection/` | 检测、模型切换、规则检查 |
| `docx_bp` | `/api/docx/` | 文档上传、分析、图片服务 |
| `api_bp` | `/api/` | 模型信息查询 |
| `main_bp` | `/` | 系统状态、网络检查 |

详见 [API 文档](./API.md)

## 4. 数据流设计

### 4.1 检测流程数据流

```
Image File (multipart/form-data)
  → Flask request.files
    → tempfile 暂存
      → YOLO model(input_tensor) → [detections]
        → post_process: 坐标归一化 + 中文类别映射
          → RulesChecker.check(detections) → [rule_results]
            → JSON Response {detections, class_counts, rule_check}
```

### 4.2 文档分析数据流

```
.docx File (multipart/form-data)
  → flask.save() → docx_service.extract_images()
    → [image_files] + [context_texts]
      → guess_category_from_context() → category_guess_stats
        ← (前端轮询) GET /status → {progress, results}
      → 异步线程: GLM-4.6V analysis → batch_results
        → Qwen2.5-7B summary generation → batch_summary
```

## 5. 前端架构

### 5.1 组件树

```
App.vue
├── 顶部导航栏 (模型状态、品牌标识)
├── Tab 切换 (图片检测 | 文档分析)
├── DetectionPanel.vue
│   ├── 工具栏 (模式切换、导航)
│   ├── 画布区 (原图 / 检测结果 / 对比视图)
│   ├── 胶片导航 (缩略图列表)
│   └── 侧边栏 (检测统计、规则检查结果)
└── DocumentAnalysis.vue
    ├── 上传区域 (Hero 样式)
    ├── 状态栏 (任务ID、批量分析按钮)
    ├── 图片网格 (可点击卡片)
    ├── 详情面板 (图片预览、AI分析结果)
    ├── 智能汇总报告
    └── 图片分类统计
```

### 5.2 关键交互

- **图片检测**: 切换图片自动触发检测 (无需点击)
- **对比视图**: 拖拽滑块查看原图 vs 检测结果
- **文档分析**: 支持单张分析和批量分析两种模式
- **分类统计**: 基于 `imageCategories` 映射表 统计全部图片

## 6. 安全设计

| 措施 | 说明 |
|------|------|
| 环境变量 | API Key 通过 `.env` 管理，不入版本控制 |
| 文件隔离 | 每次上传生成独立 `task_id` 目录 |
| 用户认证 | `require_auth` 装饰器 (默认关闭) |
| CORS | Flask-CORS 白名单限制 |
| 文件大小 | `MAX_CONTENT_LENGTH = 200MB` |
| 日志脱敏 | API Key 不输出到日志 |

## 7. 部署说明

### 开发环境

```bash
# 后端 (Flask dev server)
cd backend && python run.py
# 前端 (Vite dev server)
cd frontend && npm run dev
```

### 生产环境建议

```bash
# 后端: Gunicorn (已在 requirements.txt)
cd backend && gunicorn -w 4 -b 0.0.0.0:5000 run:app

# 前端: Nginx 静态文件服务
cd frontend && npm run build
# 将 dist/ 部署到 Nginx
```

## 8. 性能考量

| 环节 | 策略 |
|------|------|
| YOLO 模型 | 单例模式预加载，避免重复 IO |
| 大图检测 | 长边限制到 1920px |
| .docx 解析 | 惰性上下文提取，避免全文遍历 |
| AI 分析 | 异步线程处理，前端轮询进度 |
| 前端渲染 | Virtual scroll 思想 (grid lazy load) |
| 大 PNG (100MB+) | docx 内压缩，但提取仍耗时 |
