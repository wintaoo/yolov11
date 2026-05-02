# 海南机器管招投标项目 - 建筑图纸分析系统

基于计算机视觉与大模型技术的建筑工程图纸智能分析系统，支持多模型 YOLO 目标检测、施工规范规则检查、Word 文档图纸提取与多模态 AI 分析。

## 功能概览

| 模块 | 功能 | 技术 |
|------|------|------|
| 图片检测 | YOLO 目标检测 + 施工规范规则检查 | YOLOv11 + Shapely |
| 文档分析 | .docx 图纸提取 + 多模态 AI 分析 | python-docx + GLM-4.6V |
| 前端界面 | 对比视图、胶片导航、分类统计 | Vue 3 + Element Plus |

## 快速开始

### 环境要求

- Python 3.8+
- Node.js 16+
- CUDA 11.0+ (仅 GPU 推理需要)

### 安装

```bash
git clone https://github.com/wintaoo/yolov11.git
cd yolov11
```

**后端**
```bash
cd backend
pip install -r requirements.txt
```

**前端**
```bash
cd frontend
npm install
```

**配置**
```bash
# 复制环境变量模板，填入你的 SiliconFlow API Key
cp .env.example .env
# 编辑 .env，设置 SILICONFLOW_API_KEY

# 放置 YOLO 模型文件
# 将 best.pt 放到 backend/models/
```

### 启动

**一键启动 (Windows)**
```bash
start.bat
```

**手动启动**
```bash
# 后端 (终端 1)
cd backend
python run.py

# 前端 (终端 2)
cd frontend
npm run dev
```

访问 http://localhost:8080

### 停止服务 (Windows)
```bash
stop.bat
```

## 项目结构

```
yolov11/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── api/               # API 路由
│   │   │   ├── detection.py    # 检测相关 API
│   │   │   └── docx.py         # 文档分析 API
│   │   ├── services/          # 业务逻辑层
│   │   │   ├── detection.py    # YOLO 检测服务
│   │   │   ├── rules_checker.py # 施工规范检查
│   │   │   ├── docx_service.py # Word 文档解析
│   │   │   └── ai_analysis_service.py # 多模态 AI 分析
│   │   ├── utils/             # 工具模块
│   │   ├── main.py            # 主蓝图 (兼容路由)
│   │   └── config.py          # 配置管理
│   ├── models/                # 模型文件目录
│   ├── uploads/               # 上传文件暂存
│   ├── docx_images/           # 文档提取图片
│   └── run.py                 # 启动入口
├── frontend/                   # 前端界面
│   └── src/
│       ├── components/
│       │   ├── DetectionPanel.vue  # 图片检测面板
│       │   └── DocumentAnalysis.vue # 文档分析面板
│       └── App.vue                 # 主布局
├── training/                  # 模型训练
│   └── config/
│       └── cad2024.yaml       # 训练配置
├── demos/                     # 演示数据与工具
│   ├── demophotos/            # 示例施工图纸
│   └── demodocx/              # 示例 Word 文档
├── docs/                      # 文档
│   ├── SYSTEM_DESIGN.md       # 系统设计文档
│   ├── USER_MANUAL.md         # 使用说明书
│   └── API.md                 # API 文档
├── scripts/                   # 工具脚本
├── .env.example               # 环境变量模板
├── start.bat / stop.bat       # 启动/停止脚本
└── .gitignore
```

## 主要技术栈

| 层次 | 技术 |
|------|------|
| 后端框架 | Python 3.8+ / Flask |
| AI 推理 | ultralytics YOLOv11 / PyTorch |
| 视觉模型 | zai-org/GLM-4.6V (SiliconFlow API) |
| 文本模型 | Qwen2.5-7B-Instruct (SiliconFlow API) |
| 文档解析 | python-docx / PIL / lxml |
| 几何计算 | Shapely |
| 前端框架 | Vue 3 / Element Plus |
| 构建工具 | Vite |
| HTTP 客户端 | Axios |

## 配置说明

所有敏感配置通过 `.env` 文件管理：

| 变量 | 说明 | 必需 |
|------|------|:---:|
| `SILICONFLOW_API_KEY` | 硅基流动 API 密钥 | ✅ |
| `SILICONFLOW_API_URL` | API 端点地址 | - |
| `SILICONFLOW_VISION_MODEL` | 视觉模型名称 | - |
| `SECRET_KEY` | Flask 密钥 | - |
| `DEBUG` | 调试模式 | - |

> 注册 SiliconFlow：https://siliconflow.cn

## 开发指南

### Git 提交规范
- `feat:` 新功能
- `fix:` 修复 bug
- `docs:` 文档更新
- `refactor:` 代码重构
- `style:` 代码格式
- `chore:` 构建/工具

### 扩展开发

**添加新检测类别**
1. 在 `backend/app/services/detection.py` 的 `CATEGORY_MAPPING` 添加新类别
2. 在 `backend/app/services/rules_checker.py` 添加对应规则

**添加新施工规范**
在 `RulesChecker._initialize_rules()` 中追加规则 dict，实现对应 `_check_*` 方法。

## 注意事项

1. `.env` 文件包含 API 密钥，已加入 `.gitignore`，切勿提交到仓库
2. 模型文件 (`*.pt`) 不入 Git，需单独放置到 `backend/models/`
3. 大型 PNG 文件 (100MB+) 在 .docx 中处理较慢，建议预压缩

## 许可证

MIT License
