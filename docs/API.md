# API 文档

Base URL: `http://localhost:5000/api`

---

## 一、文档分析

### POST /docx/upload
上传 .docx 文档，提取图片。

**Request**: `multipart/form-data`
| 字段 | 类型 | 说明 |
|------|------|------|
| file | File | .docx 文件 |

**Response**:
```json
{
  "success": true,
  "task_id": "施工方案测试文档",
  "total_images": 10,
  "images": [{"index": 1, "filename": "image_001.jpg", "context": "...", "guessed_category": "总平面布置图"}],
  "reused": false
}
```
- `reused: true` 时表示检测到重复文档，附带 `reuse_hint` 提示文字

---

### POST /docx/analyze/{task_id}
启动批量 AI 分析。仅处理未分析或上次异常的图片，已成功的跳过。

**Response**:
```json
{"success": true, "status": "batch_started", "total": 3}
```
- `total` = 本次待处理图片数（不含已完成的）

---

### POST /docx/analyze-single/{task_id}/{index}
分析单张图片。`index` 为图片编号（从 1 开始）。

**Response**:
```json
{
  "success": true,
  "index": 1,
  "result": {
    "image_type": "总平面布置图",
    "summary": "...",
    "evaluation": "...",
    "has_drawing": true,
    "drawing_name": "地下室施工阶段三平面图",
    "elements": {"recognized_items": [...], "facilities": {}},
    "construction_schedule": {"has_schedule": false},
    "dimensions_specs": {"found": true, "items": [...]}
  }
}
```

---

### GET /docx/status/{task_id}
获取任务状态（HTTP 轮询）。

**Response**:
```json
{
  "success": true,
  "task_id": "...",
  "status": "analyzing",
  "total_images": 10,
  "batch_running": true,
  "batch_progress": 5,
  "batch_total": 8,
  "batch_status": "",
  "batch_summary": "",
  "batch_error_count": 1,
  "results": {"1": {...}, "2": {...}}
}
```

---

### GET /docx/status/{task_id}/stream
SSE 实时进度推送（推荐）。

**事件类型**:

| type | 说明 | 附加字段 |
|------|------|----------|
| `analyzing` | 开始分析某张图 | `idx` |
| `progress` | 某张图分析完成 | `idx`, `result`, `progress`, `total`, `error_count` |
| `summarizing` | 正在生成汇总报告 | `progress`, `total` |
| `done` | 批量分析完成 | `summary`, `error_count`, `status` |
| `error` | 批量分析崩溃 | `error` |
| `snapshot` | 初始快照（断线重连） | `results`, `batch_running`, `batch_summary` |
| `ping` | 心跳 | - |

SSE 连接失败时前端自动降级为 HTTP 轮询。

---

### GET /docx/image/{task_id}/{filename}
获取提取的图片。

---

### GET /docx/report/{task_id}/html
返回可打印的 HTML 报告页面。页面加载后自动弹出浏览器打印对话框，支持"另存为 PDF"。

---

### GET /docx/tasks
列出所有历史任务。

**Response**:
```json
{
  "success": true,
  "tasks": [{
    "task_id": "...",
    "original_filename": "...",
    "total_images": 10,
    "status": "completed",
    "result_count": 10,
    "has_summary": true,
    "has_report": true,
    "created_at": "..."
  }]
}
```

---

### POST /docx/task/{task_id}/load
加载历史任务到内存。

---

### DELETE /docx/task/{task_id}
删除任务及所有数据。

---

## 二、图片检测

### POST /detection/detect
YOLO 目标检测。

**Request**: `multipart/form-data`
| 字段 | 类型 | 说明 |
|------|------|------|
| file | File | 图片文件（JPG/PNG/BMP） |

**Response**:
```json
{
  "success": true,
  "data": {
    "detections": [
      {"class": "塔吊", "confidence": 0.95, "bbox": [x1,y1,x2,y2], "category": "垂直运输机械"}
    ],
    "class_counts": {"塔吊": {"count": 2}},
    "detected_image": "base64..."
  }
}
```

### GET /detection/model/status
模型加载状态。
```json
{"loaded": true}
```

---

## 三、施工规范检查

### POST /check-rules
对检测结果执行 12 条规范检查。

**Request**:
```json
{"detections": [...]}
```

**Response**:
```json
{
  "success": true,
  "results": [{
    "rule_id": "R01",
    "category": "塔吊覆盖范围",
    "description": "塔吊覆盖范围应覆盖全部施工区域",
    "severity": "严重",
    "status": "合规",
    "message": "..."
  }]
}
```

**规则列表**（共 12 条）：

| ID | 类别 | 严重程度 |
|----|------|----------|
| R01 | 塔吊覆盖范围 | 严重 |
| R02 | 塔吊数量 | 重要 |
| R03 | 施工大门位置 | 重要 |
| R04 | 大门-道路连接 | 严重 |
| R05 | 临时道路完整性 | 重要 |
| R06 | 道路宽度 | 一般 |
| R07 | 办公区布局 | 一般 |
| R08 | 材料堆场位置 | 重要 |
| R09 | 钢筋加工区位置 | 重要 |
| R10 | 安全设施配置 | 严重 |
| R11 | 消防设施覆盖 | 严重 |
| R12 | 临电设施安全距离 | 严重 |
