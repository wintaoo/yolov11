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


W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def _get_text(elem):
    """Extract all text from a paragraph element."""
    parts = []
    for t in elem.iter(f'{{{W_NS}}}t'):
        if t.text:
            parts.append(t.text)
    return ''.join(parts).strip()


def _has_page_break(xml_str):
    """Check if a paragraph XML contains a page break indicator.

    Works across namespace prefixes (w:, ns0:, etc.) by matching
    the local element name and attribute value patterns.
    """
    if 'lastRenderedPageBreak' in xml_str:
        return True
    if 'type="page"' in xml_str or "type='page'" in xml_str:
        return True
    return False


def _collect_all_paras(doc):
    """Return ALL <w:p> elements in document order (depth-first body walk).

    Includes paragraphs nested inside table cells. Each entry is a
    (element, text_string) tuple. The flat index is used for both
    image location and page-number lookup.
    """
    result = []
    body = doc.element.body
    for para in body.iter(f'{{{W_NS}}}p'):
        result.append((para, _get_text(para)))
    return result


def _build_page_map(paras):
    """Build flat-index -> page-number map from a list of (elem, text) tuples.

    Detects page breaks by scanning each paragraph's serialized XML.
    Uses detected breaks as absolute anchors; falls back to a conservative
    heuristic when no breaks are found.
    """
    if not paras:
        return {}, 0

    page_break_indices = []
    for i, (elem, _text) in enumerate(paras):
        xml_str = etree.tostring(elem, encoding='unicode')
        if _has_page_break(xml_str):
            page_break_indices.append(i)

    total = len(paras)

    if page_break_indices:
        page_map = {}
        current_page = 1
        break_cursor = 0
        for i in range(total):
            if break_cursor < len(page_break_indices) and i == page_break_indices[break_cursor]:
                page_map[i] = current_page
                current_page += 1
                break_cursor += 1
            else:
                page_map[i] = current_page
        total_pages = current_page
    else:
        # No breaks — assume ~10 paragraphs per page
        units_per_page = max(6, min(15, total // 4)) if total > 4 else max(3, total)
        page_map = {}
        for i in range(total):
            page_map[i] = max(1, (i // units_per_page) + 1)
        total_pages = max(page_map.values()) if page_map else 1

    return page_map, total_pages


def extract_images_from_docx(file_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    doc = Document(file_path)
    images = []
    image_idx = 0

    all_paras = _collect_all_paras(doc)
    page_map, total_pages = _build_page_map(all_paras)

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

            # Find the paragraph that contains this image's relationship ID.
            # Use \b word boundaries so "rId1" does NOT match inside "rId10".
            para_flat_idx = -1
            para_text = ""
            rel_pattern = re.compile(rf'\b{re.escape(rel_id)}\b')
            for flat_idx, (elem, text) in enumerate(all_paras):
                xml_str = etree.tostring(elem, encoding='unicode')
                if rel_pattern.search(xml_str):
                    para_flat_idx = flat_idx
                    para_text = text
                    break

            # Gather caption from the containing paragraph + nearby paragraphs
            caption = ""
            if para_flat_idx >= 0:
                start = max(0, para_flat_idx - 1)
                end = min(len(all_paras), para_flat_idx + 3)
                for i in range(start, end):
                    t = all_paras[i][1]
                    if t:
                        caption += t + " "
            caption = caption.strip()

            figure_name = extract_figure_name(caption)
            page_number = page_map.get(para_flat_idx, 1) if para_flat_idx >= 0 else 1

            images.append({
                'index': image_idx,
                'filename': filename,
                'filepath': filepath,
                'context': caption[:500],
                'ext': ext,
                'figure_name': figure_name,
                'page_number': page_number,
                'para_position': para_flat_idx,
            })

            logger.info(f"提取图片 {image_idx}: {filename} 图名={figure_name or '(无)'} 页码≈{page_number} (上下文: {caption[:80]}...)")

        except Exception as e:
            logger.error(f"提取图片失败 rel_id={rel_id}: {e}")

    logger.info(f"从文档中提取了 {len(images)} 张图片")
    return {
        'total': len(images),
        'images': images,
        'output_dir': output_dir,
    }


def extract_figure_name(context):
    """Extract figure name from context text like '图1 总平面布置图' or '图1-1 基础结构'."""
    if not context:
        return ''

    patterns = [
        # 图1-1 xxx / 图1.1 xxx / 图1—1 xxx
        r'图\s*(\d+[-–—―.]\d+)\s*[：:\s]+(.{0,60})',
        # 图1 xxx
        r'图\s*(\d+)\s*[：:\s]+(.{0,60})',
        # Figure 1-1 xxx
        r'Figure\s*(\d+[-–—―.]\d+)\s*[：:\s]+(.{0,60})',
        # Figure 1 xxx
        r'Figure\s*(\d+)\s*[：:\s]+(.{0,60})',
        # (附图1 xxx) / (附图1-1 xxx)
        r'(?:附图|示意图|图纸)\s*(\d+[-–—―.]?\d*)\s*[：:\s]+(.{0,60})',
    ]

    for pattern in patterns:
        match = re.search(pattern, context)
        if match:
            num = match.group(1)
            title = match.group(2).strip() if match.lastindex >= 2 and match.group(2) else ''
            title = re.sub(r'[\\/:*?"<>|]', '_', title)
            title = re.sub(r'\s+', ' ', title).strip()
            if title:
                return f'图{num} {title}'
            else:
                return f'图{num}'

    # Fallback: look for bare "图X" or "图X-X" patterns without colon
    for pattern in [r'图\s*(\d+[-–—―.]\d+)', r'图\s*(\d+)']:
        match = re.search(pattern, context)
        if match:
            return f'图{match.group(1)}'

    return ''


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


def compress_and_encode(filepath, max_dimension=2048, quality=85):
    """Compress image and return base64 string. Returns None if compression fails."""
    import base64
    import io
    try:
        from PIL import Image
        img = Image.open(filepath)
        original_w, original_h = img.size
        ratio = min(max_dimension / max(original_w, original_h), 1.0)
        if ratio < 1.0:
            new_size = (int(original_w * ratio), int(original_h * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality, optimize=True)
        compressed_size = buf.tell()
        original_size = os.path.getsize(filepath)

        if compressed_size >= original_size * 0.8:
            logger.debug(f"压缩无显著收益 ({original_size}->{compressed_size} bytes), 跳过")
            return None

        logger.debug(f"压缩: {original_w}x{original_h}->{new_size[0] if ratio < 1.0 else original_w}x{new_size[1] if ratio < 1.0 else original_h}, {original_size}->{compressed_size} bytes")
        return base64.b64encode(buf.getvalue()).decode('utf-8')
    except Exception as e:
        logger.warning(f"图片压缩失败, 使用原图: {e}")
        return None
