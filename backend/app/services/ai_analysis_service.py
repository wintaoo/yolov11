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
    "facilities": { ... }
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


def _pick_key():
    keys = Config.SILICONFLOW_API_KEY_LIST
    if not keys:
        logger.warning("没有配置任何 SILICONFLOW API Key")
        return ''
    key = random.choice(keys)
    masked = key[:10] + '...' + key[-4:] if len(key) > 14 else key[:6] + '...'
    logger.info(f"选用 API Key: {masked}")
    return key


def _repair_json(candidate):
    """Try progressively harder repairs on a broken JSON string."""
    repairs = [
        candidate,
        re.sub(r',\s*}', '}', candidate),
        re.sub(r',\s*]', ']', candidate),
        re.sub(r',\s*}', '}', re.sub(r',\s*]', ']', candidate)),
        re.sub(r'}\s*$', '}', candidate),
        candidate.rstrip() + '"}}',
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
        return None, '未找到JSON起始 {'

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
        candidate = cleaned[start:] + '"}}'
        parsed = _repair_json(candidate)
        if parsed:
            return parsed, None
        return None, 'JSON不完整（缺少闭合 }）'

    candidate = cleaned[start:end]
    parsed = _repair_json(candidate)
    if parsed:
        return parsed, None
    return None, f'JSON解析失败'


def _match_category_from_text(raw_content, context_text=''):
    """Try multiple strategies to determine image_type from text."""
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
        '临时用电布置图': ['临时用电', '配电', '用电', '配电房', '配电箱', '监控'],
        '临时用水布置图': ['临时用水', '给水', '排水', '用水', '供水'],
        '临建设施平面布置图': ['临建', '办公区', '生活区', '宿舍', '食堂', '门卫', '洗车',
                           '临设', '临时设施', '标养室', '办公室'],
        '装饰装修图': ['装饰', '装修', '精装修', '外立面', '内装'],
        '周边环境图': ['周边环境', '环境', '绿化', '景观', '园林', '踏勘'],
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
        ctx_label = f'（文档上下文描述：{context_text[:100]}）'
    if not result['summary'] and ctx_label:
        result['summary'] = f'该图为{result["image_type"]}{ctx_label}。AI详细分析未成功返回，请尝试重新分析。'

    result['evaluation'] = 'AI自动分析未返回完整结果，建议重新分析或人工审核。'

    return result


def analyze_image_with_ai(image_path, context_text=""):
    from backend.app.services.docx_service import convert_to_base64

    image_b64 = convert_to_base64(image_path)
    ext = os.path.splitext(image_path)[1].lower().replace('.', '')
    mime_map = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png', 'bmp': 'bmp', 'webp': 'webp', 'gif': 'gif'}
    mime = mime_map.get(ext, 'jpeg')

    user_prompt = "请分析这张施工图片"
    if context_text:
        user_prompt += f"\n\n图片在文档中的上下文描述：{context_text[:300]}"

    guessed_category = _match_category_from_text('', context_text) or '其他'

    max_retries = 2
    last_error = ''
    last_raw = ''

    for attempt in range(max_retries + 1):
        api_key = _pick_key()
        if not api_key:
            return _build_fallback('', context_text, guessed_category)

        prompt = user_prompt
        if attempt > 0:
            prompt += RETRY_PROMPT_SUFFIX

        payload = {
            "model": Config.SILICONFLOW_VISION_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{image_b64}"}}
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
        logger.info(f"[分析] 第{attempt+1}次尝试 {filename} (上下文: {context_text[:50]}...)")

        try:
            resp = requests.post(Config.SILICONFLOW_API_URL, json=payload, headers=headers, timeout=120)

            if resp.status_code == 401 or resp.status_code == 403:
                logger.warning(f"[分析] API Key 认证失败 (HTTP {resp.status_code}), 尝试其他Key")
                continue

            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.warning(f"[分析] API返回异常: {last_error}")
                time.sleep(2 ** attempt)
                continue

            data = resp.json()
            content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
            last_raw = content
            logger.info(f"[分析] API响应长度={len(content)}, 前100字: {content[:100]}")

            parsed, err = _extract_json(content)
            if parsed:
                if not parsed.get('image_type') or parsed.get('image_type') == '其他':
                    matched = _match_category_from_text(content, context_text)
                    if matched:
                        parsed['image_type'] = matched
                    elif guessed_category != '其他':
                        parsed['image_type'] = guessed_category
                if not parsed.get('summary'):
                    parsed['summary'] = content[:500] if content else f'该图为{parsed.get("image_type", "图纸")}，位于文档中。'
                if not parsed.get('evaluation'):
                    parsed['evaluation'] = '已识别图纸内容，评估信息不完整。'

                logger.info(f"[分析] JSON解析成功: 类型={parsed.get('image_type','?')}")
                return parsed

            last_error = err or 'JSON解析失败'
            logger.warning(f"[分析] JSON解析失败 (第{attempt+1}次): {err}")

            if attempt < max_retries:
                wait = 2 ** attempt
                logger.info(f"[分析] 等待 {wait}s 后重试...")
                time.sleep(wait)

        except requests.exceptions.Timeout:
            last_error = '请求超时(120s)'
            logger.warning(f"[分析] 第{attempt+1}次超时, 重试...")
            time.sleep(2 ** attempt)

        except requests.exceptions.ConnectionError as e:
            last_error = f'连接失败: {e}'
            logger.warning(f"[分析] 第{attempt+1}次连接失败, 重试...")
            time.sleep(2 ** attempt)

        except Exception as e:
            last_error = str(e)
            logger.error(f"[分析] 第{attempt+1}次异常: {e}", exc_info=True)
            time.sleep(2 ** attempt)

    logger.error(f"[分析] {max_retries+1}次尝试均失败, 返回降级结果. 最终错误: {last_error}")
    result = _build_fallback(last_raw, context_text, guessed_category)
    result['_error'] = last_error
    return result
