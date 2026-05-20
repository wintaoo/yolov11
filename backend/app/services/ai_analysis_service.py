import os
import json
import re
import logging
import time
import random
import requests
from backend.app.config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个专业的建筑工程图纸分析专家。你的任务是对施工图纸进行深度分析，识别图纸类型并提取所有可识别的结构化信息。

请严格按照以下JSON格式返回分析结果，不要添加任何额外说明。每个字段都要尽可能详细、准确：

{
  "image_type": "图纸类型，从以下选项中选择最匹配的一个：周边环境图、进度计划图、分区规划图、基础结构图、临时用电布置图、临时用水布置图、土方工程图、主体结构图、装饰装修图、总平面布置图、施工计划图、临建设施平面布置图、施工分区图。如无法确定则填'其他'",
  "summary": "对该图片内容的详细摘要（400-600字），必须涵盖以下方面：(1)图纸整体描述：图纸的用途、所属工程阶段、表达的核心内容；(2)空间布局分析：各区域、建筑物、构筑物的位置关系和空间组织逻辑；(3)标注与说明：图中出现的所有文字标注、尺寸标注、图例说明、附注等关键信息；(4)关键数据：任何可辨识的数字、比例尺、面积、标高、坐标等定量信息；(5)图面特征：图框、标题栏、指北针、比例尺等制图要素的存在情况。请用连贯的段落叙述，不要使用无序列表",
  "evaluation": "从以下五个维度逐项详细评价（每项2-3句话，最后给出总评）：(1)图纸完整性：图中要素是否齐全，有无明显缺漏或不完整之处；(2)标注清晰度：文字标注、尺寸标注、图例是否清晰可辨，是否有模糊或重叠；(3)布局合理性：空间布局、设施布置的合理性和逻辑性；(4)制图规范性：是否符合施工图绘制标准（线型、图层、字体等）；(5)实用性与可施工性：图纸对实际施工的指导价值如何，是否有需要补充或修正的地方。最后给出总体评价等级：优（各方面优秀）/良（整体良好，个别不足）/中（存在明显问题）/差（严重缺陷）",
  "has_drawing": true/false,
  "drawing_name": "图名称（从图中标题栏或图名标注中提取，如无则填空字符串）",
  "elements": {
    "recognized_items": ["列出图中所有可识别的重要元素，包括但不限于：建筑物轮廓、道路、围墙、大门、临时设施（办公区、生活区、加工棚、仓库等）、机械设备（塔吊、施工电梯、混凝土泵车等）、材料堆场、管线、绿化、水系、测量控制点等。每个要素用简短的名称描述"],
    "facilities": {"设施名称": "数量（如可辨识）"}
  },
  "construction_schedule": {
    "has_schedule": true/false,
    "start_date": "开工日期（如有，格式YYYY-MM-DD）",
    "end_date": "竣工日期（如有，格式YYYY-MM-DD）",
    "total_duration": "总工期（如有，如'180天'）",
    "key_milestones": ["关键节点（如有）"],
    "tasks": [
      {"name": "施工内容", "start": "开始时间", "end": "结束时间", "duration": "工期"}
    ]
  },
  "dimensions_specs": {
    "found": true/false,
    "items": [
      {
        "name": "构件/设施/区域名称",
        "dimension": "尺寸（长×宽×高或面积等）",
        "spec": "规格/材质/强度等级等",
        "quantity": "数量",
        "location": "位置描述"
      }
    ]
  },
  "safety_environment": {
    "has_info": true/false,
    "fire_fighting": "消防设施布置情况（灭火器、消火栓、消防通道等）",
    "safety_signs": "安全标识情况",
    "environmental": "环保措施（降尘、排污、噪音控制等）",
    "emergency": "应急预案相关设施（如疏散路线、集合点等）"
  }
}"""

RETRY_PROMPT_SUFFIX = """\n\n重要：请只输出JSON，不要包含任何其他文字说明。确保JSON格式正确、完整，所有字段都要包含。"""

ALL_CATEGORIES = [
    '总平面布置图', '基础结构图', '主体结构图', '土方工程图',
    '进度计划图', '施工计划图', '分区规划图', '施工分区图',
    '临时用电布置图', '临时用水布置图', '临建设施平面布置图',
    '装饰装修图', '周边环境图',
]

THINKING_MODELS = {'Qwen/Qwen3-VL-235B-A22B-Thinking'}

BASE_TIMEOUT = 75
THINKING_TIMEOUT = 120
MAX_RETRIES_PER_CANDIDATE = 1
MAX_ORIGINAL_IMAGE_KB = 5120


def _pick_key_and_model(blocked_keys=None, blocked_models=None, prefer_non_thinking=True):
    keys = Config.SILICONFLOW_API_KEY_LIST
    if not keys:
        return '', ''

    available_keys = [k for k in keys if not blocked_keys or k not in blocked_keys]
    if not available_keys:
        available_keys = keys

    models = Config.SILICONFLOW_VISION_MODELS
    available_models = [m for m in models if not blocked_models or m not in blocked_models]
    if not available_models:
        available_models = models

    if prefer_non_thinking and len(available_models) > 1:
        non_thinking = [m for m in available_models if m not in THINKING_MODELS]
        if non_thinking:
            available_models = non_thinking

    key = random.choice(available_keys)
    model = random.choice(available_models)
    masked_key = key[:10] + '...' + key[-4:] if len(key) > 14 else key[:6] + '...'
    logger.info(f"[选择] Key={masked_key} Model={model}")
    return key, model


def _repair_json(candidate):
    repairs = [
        candidate,
        re.sub(r',\s*}', '}', candidate),
        re.sub(r',\s*]', ']', candidate),
        re.sub(r',\s*}', '}', re.sub(r',\s*]', ']', candidate)),
    ]
    for r in repairs:
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            continue
    return None


def _extract_json(text):
    if not text:
        return None, '内容为空'
    cleaned = text.strip()

    if cleaned.startswith('```'):
        lines = cleaned.split('\n')
        cleaned = '\n'.join(l for l in lines if not l.strip().startswith('```'))
    cleaned = cleaned.strip()

    start = cleaned.find('{')
    if start == -1:
        return None, '未找到JSON起始'

    depth = 0
    end = -1
    for i in range(start, len(cleaned)):
        if cleaned[i] == '{':
            depth += 1
        elif cleaned[i] == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        return None, 'JSON不完整'

    candidate = cleaned[start:end]
    parsed = _repair_json(candidate)
    if parsed:
        return parsed, None
    return None, 'JSON解析失败'


def _match_category_from_text(raw_content, context_text=''):
    if not raw_content:
        raw_content = ''

    combined = raw_content + ' ' + context_text

    for cat in ALL_CATEGORIES:
        if cat in combined:
            return cat

    keyword_map = {
        '总平面布置图': ['总平面', '平面布置', '施工总平面', '场地布置', '施工现场总平面'],
        '基础结构图': ['基础结构', '桩基', '筏板', '承台', '基础平面', '桩位'],
        '主体结构图': ['主体结构', '框架', '剪力墙', '柱网', '梁板', '结构平面'],
        '土方工程图': ['土方', '开挖', '基坑', '边坡', '支护', '土钉墙'],
        '进度计划图': ['进度计划', '施工进度', '横道图', '网络图', '甘特图', '工期'],
        '施工计划图': ['施工计划', '施工部署', '施工组织', '施工段'],
        '分区规划图': ['分区', '流水施工', '分区作业', '施工分区'],
        '施工分区图': ['分区', '流水段', '施工区'],
        '临时用电布置图': ['临时用电', '配电', '用电', '配电房', '配电箱'],
        '临时用水布置图': ['临时用水', '给水', '排水', '用水', '供水'],
        '临建设施平面布置图': ['临建', '办公区', '生活区', '宿舍', '食堂', '门卫', '洗车',
                           '临设', '临时设施', '标养室', '办公室'],
        '装饰装修图': ['装饰', '装修', '精装修', '外立面', '内装'],
        '周边环境图': ['周边环境', '环境', '绿化', '景观', '园林', '踏勘', '监控'],
    }

    for cat, keywords in keyword_map.items():
        for kw in keywords:
            if kw in combined:
                return cat

    return None


def _build_fallback(raw_content, context_text='', guessed_category='其他', failure_reason=''):
    result = {
        'image_type': guessed_category if guessed_category != '其他' else '其他',
        'summary': '',
        'evaluation': '',
        'has_drawing': False,
        'drawing_name': '',
        'elements': {},
        'construction_schedule': {'has_schedule': False},
        'dimensions_specs': {'found': False},
        'raw_content': raw_content or '',
        '_fallback': True,
    }

    if not raw_content:
        raw_content = ''

    matched = _match_category_from_text(raw_content, context_text)
    if matched:
        result['image_type'] = matched
    elif guessed_category != '其他':
        result['image_type'] = guessed_category

    if raw_content.strip():
        result['summary'] = raw_content[:500]

    if failure_reason:
        reason_map = {
            'network': '网络连接异常',
            'auth': 'API密钥认证失败',
            'timeout': 'AI服务响应超时',
            'parse': 'AI返回内容解析失败',
            'empty': 'AI返回内容为空',
            'unknown': '未知原因',
        }
        reason_cn = '、'.join(reason_map.get(r, r) for r in failure_reason.split(','))
    else:
        reason_cn = '未知原因'

    ctx_label = ''
    if context_text:
        ctx_label = f'（文档上下文：{context_text[:100]}）'

    if not result['summary']:
        result['summary'] = (
            f'该图推测为{result["image_type"]}。{ctx_label}'
            f'AI分析未成功（原因：{reason_cn}），'
            f'建议检查网络后点击"重新分析"，或切换到单张分析模式。'
        )

    result['evaluation'] = f'AI分析未完成（{reason_cn}），建议重新分析或人工审核。'

    if failure_reason:
        result['_error'] = f'{reason_cn}: {failure_reason}'

    return result


def analyze_image_with_ai(image_path, context_text=""):
    from backend.app.services.docx_service import convert_to_base64

    if Config.AI_CACHE_ENABLED:
        from backend.app.services.ai_cache import get as cache_get, set as cache_set
        cached = cache_get(image_path)
        if cached:
            return cached

    image_b64 = convert_to_base64(image_path)
    ext = os.path.splitext(image_path)[1].lower().replace('.', '')
    mime_map = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png', 'bmp': 'bmp', 'webp': 'webp', 'gif': 'gif'}
    mime = mime_map.get(ext, 'jpeg')

    compressed_b64 = None
    if Config.IMAGE_COMPRESSION_ENABLED:
        from backend.app.services.docx_service import compress_and_encode
        compressed_b64 = compress_and_encode(image_path, Config.IMAGE_MAX_DIMENSION, Config.IMAGE_JPEG_QUALITY)
        if compressed_b64:
            mime = 'jpeg'

    user_prompt = "请分析这张施工图片"
    if context_text:
        user_prompt += f"\n\n图片在文档中的上下文描述：{context_text[:300]}"

    guessed_category = _match_category_from_text('', context_text) or '其他'
    filename = os.path.basename(image_path)

    candidates = [(compressed_b64, 'jpeg')] if compressed_b64 else []
    original_kb = len(image_b64) // 1024
    if original_kb <= MAX_ORIGINAL_IMAGE_KB:
        candidates.append((image_b64, mime))
    else:
        logger.info(f"[分析] 原图过大({original_kb}KB > {MAX_ORIGINAL_IMAGE_KB}KB), 跳过")

    last_error = ''
    last_raw = ''
    failure_types = []

    for cand_idx, (img_data, img_mime) in enumerate(candidates):
        label = "压缩" if cand_idx == 0 and compressed_b64 else "原图"
        img_kb = len(img_data) // 1024
        logger.info(f"[分析] {label} ({img_kb}KB) {filename}")

        blocked_keys = set()
        blocked_models = set()

        for attempt in range(MAX_RETRIES_PER_CANDIDATE + 1):
            prefer_non_thinking = (attempt == 0)
            api_key, model = _pick_key_and_model(
                blocked_keys=blocked_keys if len(blocked_keys) < len(Config.SILICONFLOW_API_KEY_LIST) else None,
                blocked_models=blocked_models if len(blocked_models) < len(Config.SILICONFLOW_VISION_MODELS) else None,
                prefer_non_thinking=prefer_non_thinking,
            )
            if not api_key:
                break

            prompt = user_prompt
            if attempt > 0:
                prompt += RETRY_PROMPT_SUFFIX

            is_thinking = model in THINKING_MODELS
            timeout = THINKING_TIMEOUT if is_thinking else BASE_TIMEOUT

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/{img_mime};base64,{img_data}"}}
                        ]
                    }
                ],
                "max_tokens": 8192,
                "temperature": 0.1,
            }

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

            logger.info(f"  [{label}] 第{attempt+1}次 {filename} model={model} timeout={timeout}s")

            try:
                resp = requests.post(Config.SILICONFLOW_API_URL, json=payload, headers=headers, timeout=timeout)

                if resp.status_code in (401, 403):
                    logger.warning(f"  [{label}] HTTP {resp.status_code} (model={model}), 拉黑此Key+Model重试")
                    blocked_keys.add(api_key)
                    blocked_models.add(model)
                    if 'auth' not in failure_types:
                        failure_types.append('auth')
                    continue

                if resp.status_code == 429:
                    logger.warning(f"  [{label}] HTTP 429 限流, 等待5s后重试")
                    time.sleep(5)
                    if 'auth' not in failure_types:
                        failure_types.append('auth')
                    continue

                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}"
                    logger.warning(f"  [{label}] API异常: HTTP {resp.status_code}")
                    time.sleep(2 ** attempt)
                    continue

                data = resp.json()
                msg = data.get('choices', [{}])[0].get('message', {})

                content = msg.get('content', '')
                if is_thinking and not content:
                    reasoning = msg.get('reasoning_content', '')
                    if reasoning:
                        logger.info(f"  [{label}] Thinking模型content为空, 使用reasoning({len(reasoning)}字)")
                        content = reasoning

                last_raw = content

                if not content or len(content.strip()) < 10:
                    logger.warning(f"  [{label}] 返回内容过短: '{content[:80]}'")
                    if 'empty' not in failure_types:
                        failure_types.append('empty')
                    time.sleep(2 ** attempt)
                    continue

                logger.info(f"  [{label}] 响应{len(content)}字: {content[:80]}...")

                parsed, err = _extract_json(content)
                if parsed:
                    if not parsed.get('image_type') or parsed.get('image_type') == '其他':
                        matched = _match_category_from_text(content, context_text)
                        if matched:
                            parsed['image_type'] = matched
                        elif guessed_category != '其他':
                            parsed['image_type'] = guessed_category

                    if not parsed.get('summary'):
                        parsed['summary'] = content[:500] if content else f'该图为{parsed.get("image_type", "图纸")}的施工图纸。'
                    if not parsed.get('evaluation'):
                        parsed['evaluation'] = '已识别图纸内容，评估信息不完整。'

                    logger.info(f"  [{label}] 成功: 类型={parsed.get('image_type','?')}")

                    if Config.AI_CACHE_ENABLED:
                        try:
                            cache_set(image_path, parsed)
                        except Exception:
                            pass
                    return parsed

                last_error = f'JSON解析失败: {err}'
                logger.warning(f"  [{label}] {last_error}")
                if 'parse' not in failure_types:
                    failure_types.append('parse')
                time.sleep(2 ** attempt)

            except requests.exceptions.Timeout:
                last_error = f'超时({timeout}s)'
                logger.warning(f"  [{label}] 第{attempt+1}次{last_error}")
                if 'timeout' not in failure_types:
                    failure_types.append('timeout')
                time.sleep(2 ** attempt)

            except (requests.exceptions.ConnectionError, requests.exceptions.ProxyError) as e:
                last_error = f'网络连接异常'
                logger.warning(f"  [{label}] 第{attempt+1}次{last_error}: {type(e).__name__}")
                if 'network' not in failure_types:
                    failure_types.append('network')
                delay = min(2 ** (attempt + 1), 10)
                time.sleep(delay)

            except Exception as e:
                last_error = f'{type(e).__name__}: {e}'
                logger.error(f"  [{label}] 第{attempt+1}次异常: {e}", exc_info=True)
                time.sleep(2 ** attempt)

    reason = ','.join(failure_types) if failure_types else 'unknown'
    logger.error(f"[分析] {filename} 所有尝试失败 (原因:{reason}), 降级. 最后错误: {last_error}")
    result = _build_fallback(last_raw, context_text, guessed_category, reason)
    return result


def _safe_str(val):
    """Normalize AI result value to string."""
    if isinstance(val, dict):
        parts = [f'{k}: {v}' for k, v in val.items()]
        return '；'.join(parts)
    if isinstance(val, list):
        return '；'.join(str(v) for v in val)
    if not isinstance(val, str):
        return str(val)
    return val


def _json_to_markdown(result: dict, figure_name: str = "", context_before: str = "", context_after: str = "") -> str:
    """Convert AI JSON analysis result to a structured markdown report."""
    lines = []

    # 标题
    title = f"# 图纸深度分析报告"
    if figure_name and figure_name != '图后无文字':
        title += f" — {figure_name}"
    lines.append(title)
    lines.append("")

    # 1. 基本信息
    image_type = result.get('image_type', '未识别')
    drawing_name = result.get('drawing_name', '')
    lines.append("## 1. 图纸基本信息")
    lines.append(f"| 项目 | 内容 |")
    lines.append(f"|------|------|")
    lines.append(f"| 图纸类型 | **{image_type}** |")
    if drawing_name:
        lines.append(f"| 图纸名称 | {drawing_name} |")
    if figure_name and figure_name != '图后无文字':
        lines.append(f"| 文档标注 | {figure_name} |")
    lines.append("")

    # 2. 内容深度概述
    summary = _safe_str(result.get('summary', '未提供'))
    lines.append("## 2. 图纸内容深度概述")
    lines.append(summary)
    lines.append("")

    # 3. 关键要素清单
    elements = result.get('elements', {}) or {}
    recognized_items = elements.get('recognized_items', []) or []
    facilities = elements.get('facilities', {}) or {}
    lines.append("## 3. 关键要素识别")
    if recognized_items:
        lines.append(f"共识别 **{len(recognized_items)}** 项要素：")
        lines.append("")
        for item in recognized_items:
            lines.append(f"- {item}")
        lines.append("")
    if facilities:
        lines.append("### 设施/设备统计")
        lines.append("")
        lines.append("| 设施名称 | 数量 |")
        lines.append("|----------|------|")
        for name, count in facilities.items():
            lines.append(f"| {name} | {count} |")
        lines.append("")
    if not recognized_items and not facilities:
        lines.append("> 图中未识别到明确的离散要素，可能为示意性图纸或纯文字图表。")
        lines.append("")

    # 4. 施工计划分析
    schedule = result.get('construction_schedule', {}) or {}
    lines.append("## 4. 施工计划与工期分析")
    if schedule.get('has_schedule'):
        lines.append(f"- **开工日期**: {schedule.get('start_date', '未知')}")
        lines.append(f"- **竣工日期**: {schedule.get('end_date', '未知')}")
        if schedule.get('total_duration'):
            lines.append(f"- **总工期**: {schedule.get('total_duration', '')}")
        milestones = schedule.get('key_milestones', []) or []
        if milestones:
            lines.append("")
            lines.append("### 关键里程碑")
            for m in milestones:
                lines.append(f"- {m}")
            lines.append("")
        tasks = schedule.get('tasks', []) or []
        if tasks:
            lines.append("")
            lines.append("### 施工任务分解")
            lines.append("")
            lines.append("| 施工内容 | 开始时间 | 结束时间 | 工期 |")
            lines.append("|----------|----------|----------|------|")
            for task in tasks:
                lines.append(f"| {task.get('name', '')} | {task.get('start', '')} | {task.get('end', '')} | {task.get('duration', '')} |")
            lines.append("")
    else:
        lines.append("> 图中未包含施工计划或工期相关信息。")
        lines.append("")

    # 5. 尺寸规格与技术参数
    dims = result.get('dimensions_specs', {}) or {}
    lines.append("## 5. 尺寸规格与技术参数")
    if dims.get('found') and dims.get('items'):
        items = dims.get('items', [])
        lines.append(f"共识别 **{len(items)}** 项规格数据：")
        lines.append("")
        lines.append("| 名称 | 尺寸 | 规格/材质 | 数量 | 位置 |")
        lines.append("|------|------|-----------|------|------|")
        for item in items:
            lines.append(f"| {item.get('name', '')} | {item.get('dimension', '-')} | {item.get('spec', '-')} | {item.get('quantity', '-')} | {item.get('location', '-')} |")
        lines.append("")
    else:
        lines.append("> 图中未提取到明确的尺寸规格或技术参数。")
        lines.append("")

    # 6. 安全与环保
    safety = result.get('safety_environment', {}) or {}
    if safety.get('has_info'):
        lines.append("## 6. 安全与环保措施")
        if safety.get('fire_fighting'):
            lines.append(f"### 消防设施\n{safety['fire_fighting']}")
            lines.append("")
        if safety.get('safety_signs'):
            lines.append(f"### 安全标识\n{safety['safety_signs']}")
            lines.append("")
        if safety.get('environmental'):
            lines.append(f"### 环保措施\n{safety['environmental']}")
            lines.append("")
        if safety.get('emergency'):
            lines.append(f"### 应急设施\n{safety['emergency']}")
            lines.append("")

    # 7. 规范性评估
    evaluation = _safe_str(result.get('evaluation', '未提供'))
    lines.append("## 7. 综合评估")
    lines.append(evaluation)
    lines.append("")

    # 8. 文档上下文
    if context_before or context_after:
        lines.append("## 8. 文档上下文参考")
        if context_before:
            lines.append(f"> **上文**: {context_before[:300]}")
        if context_after:
            lines.append(f"> **下文**: {context_after[:300]}")
        lines.append("")

    # 页脚
    from datetime import datetime
    lines.append("---")
    lines.append(f"*分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 分析引擎: 多模态视觉大模型（SiliconFlow）*")

    return "\n".join(lines)


def analyze_image_markdown_report(image_path: str, context_text: str = "", figure_name: str = "",
                                   context_before: str = "", context_after: str = "") -> dict:
    """Analyze image and return a markdown-formatted report.

    Wraps analyze_image_with_ai and converts the structured JSON result to readable markdown.
    """
    try:
        json_result = analyze_image_with_ai(image_path, context_text)
        md = _json_to_markdown(json_result, figure_name, context_before, context_after)
        return {
            'success': True,
            'json': json_result,
            'markdown': md,
        }
    except Exception as e:
        logger.error(f"Markdown报告生成失败: {e}", exc_info=True)
        return {
            'success': False,
            'json': {},
            'markdown': f"# AI分析失败\n\n分析过程中出现错误: {str(e)}\n\n请稍后重试。",
            'error': str(e),
        }
