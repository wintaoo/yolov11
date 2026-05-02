import os
import json
import logging
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
    "facilities": {
      "gates": {"found": true/false, "items": ["大门名称"]},
      "fences": {"found": true/false, "items": ["围挡/围墙"]},
      "office_areas": {"found": true/false, "items": ["办公室", "会议室", "接待室等"]},
      "living_areas": {"found": true/false, "items": ["宿舍", "食堂", "卫生间/厕所", "门卫室等"]},
      "construction_areas": {"found": true/false, "items": ["施工区描述"]},
      "roads": {"found": true/false, "items": ["道路名称"]},
      "material_yards": {"found": true/false, "items": ["钢筋堆场", "预制构件堆场", "钢构件堆场", "砌体材料堆场等"]},
      "processing_areas": {"found": true/false, "items": ["钢筋加工区", "木工加工区", "机电加工区等"]},
      "machinery": {"found": true/false, "items": ["塔吊", "汽车吊", "挖掘机", "施工电梯", "搅拌桩机等"]},
      "utility": {"found": true/false, "items": ["配电房", "配电箱", "临电线路", "临水线路", "消防栓等"]},
      "other_facilities": {"found": true/false, "items": ["仓库", "标养室", "洗车台等"]}
    },
    "zone_names": [],
    "legend_items": [],
    "annotations": []
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


def analyze_image_with_ai(image_path, context_text=""):
    try:
        from backend.app.services.docx_service import convert_to_base64

        image_b64 = convert_to_base64(image_path)
        ext = os.path.splitext(image_path)[1].lower().replace('.', '')
        mime_map = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png', 'bmp': 'bmp', 'webp': 'webp', 'gif': 'gif'}
        mime = mime_map.get(ext, 'jpeg')

        user_prompt = "请分析这张施工图片"
        if context_text:
            user_prompt += f"\n\n图片在文档中的上下文描述：{context_text[:300]}"

        payload = {
            "model": Config.SILICONFLOW_VISION_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{image_b64}"}}
                    ]
                }
            ],
            "max_tokens": 4096,
            "temperature": 0.1,
        }

        headers = {
            "Authorization": f"Bearer {Config.SILICONFLOW_API_KEY}",
            "Content-Type": "application/json"
        }

        logger.info(f"发送AI分析请求: {image_path} (上下文: {context_text[:60]}...)")
        resp = requests.post(Config.SILICONFLOW_API_URL, json=payload, headers=headers, timeout=120)

        if resp.status_code != 200:
            logger.error(f"AI API返回错误: {resp.status_code} {resp.text[:300]}")
            return {"error": f"API错误: {resp.status_code}", "raw_response": resp.text[:500]}

        data = resp.json()
        content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
        logger.info(f"AI分析完成: 返回内容长度={len(content)}")

        try:
            json_match = search_json(content)
            if json_match:
                result = json.loads(json_match)
                result['raw_content'] = content
                return result
        except json.JSONDecodeError:
            pass

        return {
            "image_type": "其他",
            "summary": content[:500],
            "has_drawing": False,
            "elements": {},
            "construction_schedule": {"has_schedule": False},
            "raw_content": content,
        }

    except Exception as e:
        logger.error(f"AI分析失败: {str(e)}", exc_info=True)
        return {"error": str(e)}


def batch_analyze_images(images_meta, output_dir):
    results = []
    for i, img in enumerate(images_meta):
        logger.info(f"分析进度: {i+1}/{len(images_meta)} - {img['filename']}")
        ai_result = analyze_image_with_ai(img['filepath'], img.get('context', ''))

        guessed = img.get('guessed_category', '其他')
        if isinstance(ai_result, dict) and 'error' not in ai_result:
            ai_type = ai_result.get('image_type', guessed)
            if ai_type == '其他' and guessed != '其他':
                ai_result['image_type'] = guessed

        results.append({
            'index': img['index'],
            'filename': img['filename'],
            'context': img.get('context', ''),
            'guessed_category': guessed,
            'ai_analysis': ai_result,
        })
        logger.info(f"图片 {img['index']}: 类型={ai_result.get('image_type', 'N/A')}")

    category_stats = {}
    for r in results:
        ai_type = r.get('ai_analysis', {})
        cat = ai_type.get('image_type', '其他') if isinstance(ai_type, dict) else '其他'
        category_stats[cat] = category_stats.get(cat, 0) + 1

    return {
        'total': len(results),
        'category_stats': category_stats,
        'results': results,
    }


def search_json(text):
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return None
