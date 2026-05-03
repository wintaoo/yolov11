import os
import json
import re
import logging
import time
import random
import requests
from backend.app.config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个专业的建筑工程图纸分析助手。你的任务是分析施工图纸图片，识别图纸类型并提取结构化信息。

请严格按照以下JSON格式返回分析结果，不要添加任何额外说明：

{
  "image_type": "图纸类型，从以下选项中选择：周边环境图、进度计划图、分区规划图、基础结构图、临时用电布置图、临时用水布置图、土方工程图、主体结构图、装饰装修图、总平面布置图、施工计划图、临建设施平面布置图、施工分区图、其他",
  "summary": "对该图片内容的摘要，涵盖图中展示的核心信息、空间布局、标注内容、关键数据等，要求200-400字，尽可能详细",
  "evaluation": "对该图纸的客观评价，从以下维度逐项分析（每项一句话）：1)图纸完整性：图中要素是否齐全，有无缺漏；2)标注清晰度：文字标注、尺寸标注、图例是否清晰可辨；3)布局合理性：空间布局和设施布置是否合理；4)与规范符合性：是否符合施工图绘制规范。最后给出总体评价等级（优/良/中/差）",
  "has_drawing": true/false,
  "drawing_name": "图名称（如有）",
  "elements": {
    "recognized_items": ["识别到的要素列表"],
    "facilities": {}
  },
  "construction_schedule": {
    "has_schedule": true/false,
    "start_date": "开始日期（如有，格式YYYY-MM-DD）",
    "end_date": "结束日期（如有，格式YYYY-MM-DD）",
    "tasks": [
      {"name": "施工内容", "start": "开始时间", "end": "结束时间", "duration": "工期"}
    ]
  },
  "dimensions_specs": {
    "found": true/false,
    "items": [{"name": "构件/设施名称", "dimension": "尺寸", "model": "型号", "quantity": "数量"}]
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

BASE_TIMEOUT = 60
THINKING_TIMEOUT = 90
MAX_RETRIES_PER_CANDIDATE = 1


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
    candidates.append((image_b64, mime))

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
                "max_tokens": 4096,
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
