# 系统设计文档

## 一、系统概述

建筑图纸分析系统服务于海南机器管招投标项目，核心目标是对施工方案文档中的图纸进行自动化审查。

系统分为两条处理管线：
- **图片检测管线**: 单张图片 → YOLO 目标检测 → 施工规范检查 → 可视化标注
- **文档分析管线**: .docx 文档 → 提取图片 → 多模态 AI 分析 → 分类+评估 → 汇总报告

## 二、架构设计

```
┌──────────────────────────────────────────────────┐
│                   前端 (Vue 3)                     │
│  DetectionPanel.vue  │  DocumentAnalysis.vue      │
│  图片检测 + 规范检查   │  文档分析 + 批量进度 + 报告  │
└──────────────┬───────────────────────────────────┘
               │ HTTP / SSE
┌──────────────▼───────────────────────────────────┐
│              后端 (Flask)                          │
│  ┌─────────────┐  ┌──────────────────────┐       │
│  │ detection   │  │ docx (Blueprint)      │       │
│  │ /api/detect │  │ /api/docx/*           │       │
│  └──────┬──────┘  └────────┬─────────────┘       │
│         │                  │                      │
│  ┌──────▼──────┐  ┌───────▼──────────────┐       │
│  │ detection   │  │ ai_analysis_service  │       │
│  │ (YOLO)      │  │ (SiliconFlow API)    │       │
│  └──────┬──────┘  └───────┬──────────────┘       │
│         │                  │                      │
│  ┌──────▼──────┐  ┌───────▼──────────────┐       │
│  │ rules_      │  │ task_service         │       │
│  │ checker     │  │ (JSON 持久化)         │       │
│  └─────────────┘  └──────────────────────┘       │
└──────────────────────────────────────────────────┘
```

## 三、文档分析管线详解

### 3.1 图片提取
`docx_service.py:extract_images_from_docx()`

1. 用 `python-docx` 解析 .docx，遍历 `document.part.rels` 提取所有图片
2. 提取图片的文档上下文（所在段落前后文字）
3. 基于关键词匹配预分类 (`guess_category_from_context`)
4. 输出: `{total, images[{index, filepath, context, guessed_category}]}`

### 3.2 AI 分析
`ai_analysis_service.py:analyze_image_with_ai()`

**请求策略**:
1. 图片压缩: 长边 max 2048px, JPEG Q=85 → base64
2. 候选列表: [压缩图] + [原图（仅 ≤5MB）]
3. Key + Model 随机选择 → SiliconFlow Chat Completions API
4. 每候选最多 2 次尝试（`MAX_RETRIES_PER_CANDIDATE=1`）
5. 超时: 视觉 75s, Thinking 120s
6. 失败降级: HTTP 403 → 拉黑 Key+Model; Timeout → 切换候选; 均失败 → fallback

**缓存机制** (`ai_cache.py`):
- 图片 MD5 作为 key，结果 JSON 序列化到 `backend/cache_ai/`
- 同图跨文档复用，避免重复 API 调用
- 仅缓存成功结果，失败（含 `_error`）不缓存

**JSON 解析与容错**:
1. 括号匹配提取 JSON 块
2. 多轮修复: 去尾逗号、补全括号
3. 失败降级: 关键词匹配分类 → `_build_fallback()`

**结果结构**:
```json
{
  "image_type": "总平面布置图",
  "summary": "200-400字摘要",
  "evaluation": "分维度评估，含总体评价等级（优/良/中/差）",
  "has_drawing": true,
  "elements": {"recognized_items": [], "facilities": {}},
  "construction_schedule": {"has_schedule": false},
  "dimensions_specs": {"found": false}
}
```

### 3.3 批量分析
`docx.py:analyze_batch()`

1. 筛选待处理图片: 无结果或 `_error` 的加入队列，已成功的保留
2. `ThreadPoolExecutor` 并发分析，并发数 = `min(Key数 × 模型数, 待处理数)`
3. 每张图完成后通过 SSE push `progress` 事件
4. 全部完成后生成汇总报告

### 3.4 汇总报告
`docx.py:generate_summary()`

**两级策略**:
1. **数据驱动报告**（`_build_fallback_summary`）: 100% 准确
   - 类型分布统计、评级分布统计
   - 各图片评估详情
   - 关键施工参数汇总（尺寸规格、工期等）
2. **AI 补充评审**（可选）: 调用文本模型生成简短评审意见
   - 失败不影响主报告

### 3.5 SSE 进度推送
`docx.py:get_status_stream()`

- 事件类型: `analyzing` → `progress` → `summarizing` → `done`
- 连接断开自动降级 HTTP 轮询 (`get_status()`)
- 重连时发送 `snapshot` 快照恢复状态

## 四、模型配置

| 配置变量 | 用途 | 当前值 |
|----------|------|--------|
| `SILICONFLOW_VISION_MODEL` | 主视觉模型 | `zai-org/GLM-4.6V` |
| `SILICONFLOW_VISION_MODELS` | 备选视觉模型 | `zai-org/GLM-4.5V` |
| `SILICONFLOW_SUMMARY_MODEL` | 汇总文本模型 | `Qwen/Qwen2.5-7B-Instruct` |
| `SILICONFLOW_API_KEYS` | API 密钥列表 | 5 个 Key |

5 Key × 2 Model = 最大并发 10 线程。

## 五、数据持久化

任务数据以 JSON 文件存储，目录结构:
```
backend/tasks/{task_id}/
├── task.json          # 元数据（文件名、状态、图片列表）
├── results.json       # 分析结果 {图片编号: 结果对象}
├── summary.md         # 汇总报告
├── analysis_report.md # 可读报告
└── images/            # 提取的图片
```

## 六、前端架构

### 组件树
```
App.vue
├── 免责声明条 (ai-disclaimer)
├── Tab 切换 (图片检测 / 文档分析)
├── DetectionPanel.vue
│   ├── 工具栏 (文件夹选择 / 导航 / 清除)
│   ├── 对比视图 (原图 vs 检测结果)
│   ├── 胶片导航
│   └── 侧栏 (检测按钮 / 统计 / 列表 / 规范检查)
└── DocumentAnalysis.vue
    ├── 上传区 (历史任务列表 / 上传卡片)
    └── 分析区
        ├── 状态栏 (任务ID / 图片数 / 已分析 / 待分析)
        ├── 进度条
        ├── 异常横幅
        ├── 图片网格 (含队列状态指示)
        ├── 详情面板 (预览 / 分析按钮 / AI 结果)
        ├── 汇总报告 (Markdown 渲染 + 导出PDF)
        └── 分类统计
```

### 关键状态
| 状态 | 类型 | 说明 |
|------|------|------|
| `statusMap` | `Record<number, string>` | 每张图状态: waiting/analyzing/done/error |
| `resultMap` | `Record<number, any>` | 每张图的 AI 分析结果 |
| `batchRunning` | `boolean` | 批量分析进行中 |
| `batchPercent` | `number` | 进度百分比（仅算待处理数） |
| `batchSummary` | `string` | Markdown 汇总报告 |
