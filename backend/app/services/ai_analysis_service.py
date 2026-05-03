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


def _pick_key_and_model(exclude_key='', exclude_model=''):
    keys = [k for k in Config.SILICONFLOW_API_KEY_LIST if k != exclude_key]
    if not keys:
        keys = Config.SILICONFLOW_API_KEY_LIST
    models = [m for m in Config.SILICONFLOW_VISION_MODELS if m != exclude_model]
    if not models:
        models = Config.SILICONFLOW_VISION_MODELS

    if not keys:
        return '', ''
    key = random.choice(keys)
    model = random.choice(models)
    masked_key = key[:10] + '...' + key[-4:] if len(key) > 14 else key[:6] + '...'
    logger.info(f"选用 Key={masked_key} Model={model}")
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


def _build_fallback(raw_content, context_text='', guessed_category='其他'):
    result = {
        'image_type': '其他',
        'summary': '',
        'evaluation': '',
        'has_drawing': False,
        'drawing_name': '',
        'elements': {},
        'construction_schedule': {'has_schedule': False},
        'dimensions_specs': {'found': False},
        'raw_content': raw_content or '',
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

    ctx_label = ''
    if context_text:
        ctx_label = f'（文档上下文：{context_text[:100]}）'
    if not result['summary'] and ctx_label:
        result['summary'] = f'该图为{result["image_type"]}{ctx_label}。AI详细分析未成功返回，请尝试重新分析。'

    result['evaluation'] = 'AI自动分析未返回完整结果，建议重新分析或人工审核。'

    return result


def analyze_image_with_ai(image_path, context_text=""):
    from backend.app.services.docx_service import convert_to_base64

    # 1. Check AI result cache
    if Config.AI_CACHE_ENABLED:
        from backend.app.services.ai_cache import get as cache_get, set as cache_set
        cached = cache_get(image_path)
        if cached:
            return cached

    image_b64 = convert_to_base64(image_path)
    ext = os.path.splitext(image_path)[1].lower().replace('.', '')
    mime_map = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png', 'bmp': 'bmp', 'webp': 'webp', 'gif': 'gif'}
    mime = mime_map.get(ext, 'jpeg')

    # 2. Try compressed version first, fall back to original
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

    max_retries = 1
    last_error = ''
    last_raw = ''
    tried_keys = set()
    tried_models = set()

    candidates = [(compressed_b64, 'jpeg')] if compressed_b64 else []
    candidates.append((image_b64, mime))

    last_error = ''
    last_raw = ''

    for cand_idx, (img_data, img_mime) in enumerate(candidates):
        tried_keys.clear()
        tried_models.clear()
        label = "压缩" if cand_idx == 0 and compressed_b64 else "原图"
        logger.info(f"[分析] 使用{label}图像 ({len(img_data)//1024}KB)")

        for attempt in range(max_retries + 1):
            api_key, model = _pick_key_and_model(
                exclude_key=random.choice(list(tried_keys)) if tried_keys else '',
                exclude_model=random.choice(list(tried_models)) if tried_models else ''
            )
            if not api_key:
                break

            tried_keys.add(api_key)
            tried_models.add(model)

            prompt = user_prompt
            if attempt > 0:
                prompt += RETRY_PROMPT_SUFFIX

            is_thinking = model in THINKING_MODELS

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

            filename = os.path.basename(image_path)
            logger.info(f"[分析] {label} 第{attempt+1}次 {filename} model={model}")

            try:
                resp = requests.post(Config.SILICONFLOW_API_URL, json=payload, headers=headers, timeout=90)

                if resp.status_code in (401, 403):
                    logger.warning(f"[分析] 认证失败 (HTTP {resp.status_code}), 换Key/Model")
                    continue

                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    logger.warning(f"[分析] API异常: {last_error}")
                    time.sleep(1)
                    continue

                data = resp.json()
                msg = data.get('choices', [{}])[0].get('message', {})

                content = msg.get('content', '')
                if is_thinking and not content:
                    reasoning = msg.get('reasoning_content', '')
                    content = reasoning

                last_raw = content
                logger.info(f"[分析] 响应长度={len(content)}, 前80字: {content[:80]}")

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

                    logger.info(f"[分析] 成功: 类型={parsed.get('image_type','?')}")

                    if Config.AI_CACHE_ENABLED:
                        try:
                            cache_set(image_path, parsed)
                        except Exception:
                            pass
                    return parsed

                last_error = err or 'JSON解析失败'
                logger.warning(f"[分析] JSON解析失败 (第{attempt+1}次): {err}")
                if attempt < max_retries:
                    time.sleep(1)

            except requests.exceptions.Timeout:
                last_error = '请求超时(90s)'
                logger.warning(f"[分析] {label} 第{attempt+1}次超时")
                time.sleep(1)

            except requests.exceptions.ConnectionError as e:
                last_error = f'连接失败: {e}'
                logger.warning(f"[分析] {label} 第{attempt+1}次连接失败")
                time.sleep(1)

            except Exception as e:
                last_error = str(e)
                logger.error(f"[分析] {label} 第{attempt+1}次异常: {e}", exc_info=True)
                time.sleep(1)

    logger.error(f"[分析] 所有尝试均失败, 降级. 错误: {last_error}")
    result = _build_fallback(last_raw, context_text, guessed_category)
    result['_error'] = last_error
    return result
