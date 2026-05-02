import os
import io
import re
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from lxml import etree
import logging
from PIL import Image

logger = logging.getLogger(__name__)

TARGET_CATEGORIES = [
    '周边环境图', '进度计划图', '分区规划图', '基础结构图',
    '临时用电布置图', '临时用水布置图', '土方工程图',
    '主体结构图', '装饰装修图', '总平面布置图',
    '施工计划图', '临建设施平面布置图', '施工分区图',
]

IMG_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
DRAWING_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
RID_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def extract_images_from_docx(file_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    doc = Document(file_path)
    images = []
    image_idx = 0
    paragraph_texts = []

    for para in doc.paragraphs:
        text = para.text.strip()
        paragraph_texts.append(text)

    rels = doc.part.rels
    for rel_id, rel in rels.items():
        if "image" not in rel.reltype:
            continue
        try:
            image_data = rel.target_part.blob
            ext = rel.target_part.partname.split('.')[-1]
            if ext.lower() not in ('png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'):
                ext = 'png'

            image_idx += 1
            filename = f"image_{image_idx:03d}.{ext}"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'wb') as f:
                f.write(image_data)

            context_text = ""
            for para in doc.paragraphs:
                xml_str = para._element.xml
                if rel_id in xml_str:
                    context_text += para.text + " "

            if context_text.strip():
                caption = context_text.strip()
            else:
                try:
                    caption = ''
                    current_pos = -1
                    for pi, para in enumerate(doc.paragraphs):
                        if rel_id in para._element.xml:
                            current_pos = pi
                            break
                    if current_pos >= 0:
                        for i in range(max(0, current_pos - 1), min(len(doc.paragraphs), current_pos + 3)):
                            t = doc.paragraphs[i].text.strip()
                            if t:
                                caption += t + ' '
                    caption = caption.strip()
                except:
                    caption = ''

            images.append({
                'index': image_idx,
                'filename': filename,
                'filepath': filepath,
                'context': caption[:500],
                'ext': ext,
            })

            logger.info(f"提取图片 {image_idx}: {filename} (上下文: {caption[:80]}...)")

        except Exception as e:
            logger.error(f"提取图片失败 rel_id={rel_id}: {e}")

    logger.info(f"从文档中提取了 {len(images)} 张图片")
    return {
        'total': len(images),
        'images': images,
        'output_dir': output_dir,
    }


def guess_category_from_context(context):
    if not context:
        return '其他'

    keywords_map = {
        '周边环境图': ['周边环境', '项目区位', '现场踏勘', '环境图', '区位图', '地理位置', '周边概况'],
        '进度计划图': ['进度计划', '横道图', '开竣工', '施工进度', '进度图', '工期安排', '进度表'],
        '分区规划图': ['分区规划', '规划图', '阶段划分', '分区示意', '分区图'],
        '总平面布置图': ['总平面布置', '施工总平面', '平面布置图', '总平面', '总平图', '总平布置'],
        '基础结构图': ['基础结构', '基础图', '结构布置', '桩基', '基础平面', '基础施工'],
        '临时用电布置图': ['临时用电', '用电布置', '配电', '临电图', '用电图', '临电', '现场用电'],
        '临时用水布置图': ['临时用水', '用水布置', '给水', '排水', '临水图', '临水', '现场用水'],
        '土方工程图': ['土方工程', '土方开挖', '基坑', '土方图', '开挖图', '挖方'],
        '主体结构图': ['主体结构', '结构层', '主体图', '主体施工', '结构施工'],
        '装饰装修图': ['装饰装修', '装修图', '装饰图', '装修做法'],
        '施工计划图': ['施工计划', '施工安排', '计划图', '施工部署', '总体安排'],
        '临建设施平面布置图': ['临建设施', '临建平面', '临建布置', '活动板房', '临建图', '临设', '临时设施'],
        '施工分区图': ['施工分区', '分区施工', '施工段划分', '施工段', '流水段'],
    }

    scores = {}
    match_counts = {}

    for cat, keywords in keywords_map.items():
        total = 0
        count = 0
        for kw in keywords:
            if kw in context:
                total += len(kw)
                count += 1
        if total > 0:
            scores[cat] = total
            match_counts[cat] = count

    if not scores:
        return '其他'

    max_score = max(scores.values())
    best = [c for c, s in scores.items() if s == max_score]

    if len(best) == 1:
        return best[0]

    best_with_counts = [(c, match_counts[c]) for c in best]
    best_with_counts.sort(key=lambda x: (-x[1], x[0]))
    return best_with_counts[0][0]


def convert_to_base64(filepath):
    import base64
    with open(filepath, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')
