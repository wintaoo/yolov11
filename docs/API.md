# API 文档

Base URL: `http://localhost:5000`

---

## 图片检测接口

### `POST /api/detection/detect`

对上传的施工图纸进行 YOLO 目标检测。

**请求**
```
POST /api/detection/detect
Content-Type: multipart/form-data
```

| 参数 | 类型 | 必需 | 说明 |
|------|------|:---:|------|
| `file` | File | ✅ | 图片文件 (.jpg/.jpeg/.png/.bmp) |
| `model_path` | String | ❌ | 指定模型路径，不传则使用默认模型 |

**响应**
```json
{
  "success": true,
  "data": {
    "detections": [
      {
        "class": "塔吊",
        "confidence": 0.892,
        "bbox": [120, 80, 380, 420],
        "category": "垂直运输机械",
        "color": "#FF4D4F"
      }
    ],
    "class_counts": {
      "塔吊": 2,
      "大门": 1
    },
    "image_base64": "data:image/jpeg;base64,...",
    "message": "检测完成"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `detections` | Array | 检测结果列表 |
| `detections[].class` | String | 中文类别名称 |
| `detections[].confidence` | Float | 置信度 (0-1) |
| `detections[].bbox` | [Int] | 边界框 [x1, y1, x2, y2] |
| `class_counts` | Object | 各类别出现次数统计 |
| `image_base64` | String | 带检测框的图片 Base64 编码 |

---

### `POST /api/detection/switch-model`

切换当前使用的 YOLO 模型。

**请求**
```
POST /api/detection/switch-model
Content-Type: application/json

{
  "model_name": "best0313"
}
```

| 参数 | 类型 | 必需 | 说明 |
|------|------|:---:|------|
| `model_name` | String | ✅ | 模型文件名 (不含路径) |

**响应**
```json
{
  "success": true,
  "message": "已切换到模型: best0313"
}
```

---

### `POST /api/check-rules`

基于检测结果执行施工规范合规性检查。

**请求**
```
POST /api/check-rules
Content-Type: application/json

{
  "detections": [...]
}
```

| 参数 | 类型 | 必需 | 说明 |
|------|------|:---:|------|
| `detections` | Array | ✅ | 检测结果数组 (来自 /detect 返回) |

**响应**
```json
{
  "success": true,
  "results": [
    {
      "id": "1.5.4-1",
      "category": "加工场",
      "description": "4、钢筋加工场",
      "severity": "重要",
      "passed": true,
      "reason": "已检测到钢筋加工场"
    },
    {
      "id": "1.5.1-2",
      "category": "塔吊",
      "description": "2）塔吊应至少覆盖95%面积的地下车库",
      "severity": "严重",
      "passed": false,
      "reason": "塔吊覆盖范围未满足要求"
    }
  ],
  "summary": {
    "total": 15,
    "passed": 12,
    "failed": 3
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `results[]` | Array | 各规则检查结果 |
| `results[].passed` | Boolean | 是否通过 |
| `results[].severity` | String | 严重程度: 严重 / 重要 / 一般 |
| `summary` | Object | 汇总统计 |

---

### `GET /api/detection/model/status`

获取当前 YOLO 模型加载状态。

**响应**
```json
{
  "current_model": "best.pt",
  "loaded": true,
  "available_models": {
    "best": { "path": "...", "exists": true },
    "best0313": { "path": "...", "exists": true }
  }
}
```

---

### `GET /api/models/current`

获取当前模型基本信息 (简化版)。

**响应**
```json
{
  "success": true,
  "data": {
    "current_model": "best.pt",
    "is_loaded": true
  }
}
```

---

### `GET /api/network_check`

检查与 SiliconFlow API 的网络连通性。

**响应**
```json
{
  "online": true,
  "status": "ok"
}
```

---

## 文档分析接口

### `POST /api/docx/upload`

上传 Word 文档，提取内嵌图片。

**请求**
```
POST /api/docx/upload
Content-Type: multipart/form-data
```

| 参数 | 类型 | 必需 | 说明 |
|------|------|:---:|------|
| `file` | File | ✅ | .docx 格式文件 |

**响应**
```json
{
  "success": true,
  "task_id": "a1b2c3d4",
  "total_images": 10,
  "images": [
    {
      "index": 1,
      "filename": "image_001.png",
      "context": "2.1 总平面布置图 施工现场总平面布置图",
      "guessed_category": "总平面布置图"
    }
  ],
  "category_guess": {
    "总平面布置图": 3,
    "基础结构图": 2,
    "其他": 5
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | String | 任务唯一标识 (8位) |
| `total_images` | Int | 提取的图片总数 |
| `images[].index` | Int | 图片序号 (1-based) |
| `images[].filename` | String | 图片文件名 |
| `images[].context` | String | 文档上下文文字 (前500字) |
| `images[].guessed_category` | String | 关键词匹配的预估分类 |
| `category_guess` | Object | 预估分类统计 |

---

### `POST /api/docx/analyze/<task_id>`

启动批量分析任务 (异步执行)。

**响应**
```json
{
  "success": true,
  "status": "batch_started",
  "total": 10
}
```

---

### `POST /api/docx/analyze-single/<task_id>/<int:index>`

对单张图片进行同步 AI 分析。

**URL 参数**:
- `task_id`: 任务 ID
- `index`: 图片序号 (1-based)

**响应**
```json
{
  "success": true,
  "index": 3,
  "result": {
    "image_type": "总平面布置图",
    "summary": "该图为施工现场总平面布置图，展示了施工区、办公区、生活区、材料堆场、钢筋加工区等设施的整体布局...",
    "evaluation": "优",
    "drawing_name": "施工现场总平面布置图",
    "elements": {
      "facilities": {
        "gates": { "found": true, "items": ["施工大门", "应急大门"] },
        "office_areas": { "found": true, "items": ["项目部办公室", "会议室"] }
      }
    },
    "construction_schedule": {
      "has_schedule": false
    },
    "dimensions_specs": {
      "found": false
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `result.image_type` | String | AI 识别的图纸类型 (13种之一 或 "其他") |
| `result.summary` | String | 200-400字摘要 |
| `result.evaluation` | String | 综合评价: 优/良/中/差 |
| `result.elements.facilities.*` | Object | 各设施类别识别结果 |
| `result.construction_schedule` | Object | 施工计划信息 (如有) |
| `result.dimensions_specs` | Object | 尺寸规格信息 (如有) |

---

### `GET /api/docx/status/<task_id>`

查询批量分析任务的实时状态。

**响应 (分析中)**
```json
{
  "success": true,
  "task_id": "a1b2c3d4",
  "status": "analyzing",
  "total_images": 10,
  "batch_running": true,
  "batch_progress": 5,
  "batch_total": 10,
  "batch_status": "",
  "batch_summary": "",
  "results": {
    "1": { "image_type": "总平面布置图", "summary": "...", ... },
    "2": { "image_type": "基础结构图", "summary": "...", ... }
  }
}
```

**响应 (已完成)**
```json
{
  "success": true,
  "status": "completed",
  "batch_running": false,
  "batch_progress": 10,
  "batch_total": 10,
  "batch_summary": "## 综合汇总报告\n\n### 1. 总体概述\n...",
  "results": { ... }
}
```

---

### `GET /api/docx/image/<task_id>/<filename>`

获取提取的图片文件，用于前端预览。

**响应**: 图片二进制流 (Content-Type: image/jpeg 或 image/png)

---

## 错误响应格式

所有接口在出错时返回统一格式：

```json
{
  "success": false,
  "error": "错误描述信息"
}
```

HTTP 状态码:
| 状态码 | 说明 |
|:---:|------|
| 200 | 请求成功 (含 `success: false` 的业务错误) |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 检测类别对照表

| 英文类别 | 中文类别 | 分类 |
|------|------|------|
| `Crane` | 起重机 | 施工机械 |
| `Tower_Crane` | 塔吊 | 垂直运输机械 |
| `Excavator` | 挖掘机 | 施工机械 |
| `Mixer` | 搅拌机 | 施工机械 |
| `Steel_processing` | 钢筋加工厂 | 临时设施-生产加工区 |
| `Dormitory` | 宿舍 | 临时设施-生活及办公区 |
| `Office` | 办公室 | 临时设施-生活及办公区 |
| `toilet` | 厕所 | 临时设施-生活及办公区 |
| `Gate` | 大门 | 基础设施 |
| `Red_Line` | 红线 | 基础设施 |
| `Road` | 道路 | 基础设施 |
| `Stairs` | 楼梯 | 临时设施-辅助设施 |
