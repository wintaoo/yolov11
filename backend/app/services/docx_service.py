import os
import io
import re
import hashlib
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


def _collect_all_paras(doc_or_part):
    """Return ALL <w:p> elements in document order (depth-first body walk).

    Includes paragraphs nested inside table cells. Each entry is a
    (element, text_string) tuple. Works with Document, _Header, or _Footer objects.
    """
    result = []
    if hasattr(doc_or_part, 'element'):
        root = doc_or_part.element
    elif hasattr(doc_or_part, '_element'):
        root = doc_or_part._element
    else:
        return result
    for para in root.iter(f'{{{W_NS}}}p'):
        result.append((para, _get_text(para)))
    return result


def _detect_page_breaks(paras):
    """Scan paragraphs for page break signals.

    Returns a list of (index, starts_new_page) tuples:
      - starts_new_page=True:  paragraph at this index IS on the new page
        (lastRenderedPageBreak — Word's natural page break marker)
      - starts_new_page=False: paragraph at this index STAYS on the old page
        (w:br type="page" — explicit break within/between paragraphs)
    """
    breaks = []
    for i, (elem, _text) in enumerate(paras):
        xml_str = etree.tostring(elem, encoding='unicode')
        has_lrpb = 'lastRenderedPageBreak' in xml_str
        has_br = 'type="page"' in xml_str or "type='page'" in xml_str

        if has_lrpb and not has_br:
            breaks.append((i, True))
        elif has_br:
            breaks.append((i, False))
    return breaks


def _build_page_map(paras):
    """Build flat-index -> page-number map from a list of (elem, text) tuples.

    Detects page breaks by scanning each paragraph's serialized XML.
    When no breaks are found, estimates pages based on accumulated character
    count (~600 chars/page for mixed technical docs).
    """
    if not paras:
        return {}, 0

    breaks = _detect_page_breaks(paras)
    total = len(paras)

    if breaks:
        page_map = {}
        current_page = 1
        break_cursor = 0
        for i in range(total):
            if break_cursor < len(breaks) and i == breaks[break_cursor][0]:
                starts_new_page = breaks[break_cursor][1]
                if starts_new_page:
                    current_page += 1
                    page_map[i] = current_page
                else:
                    page_map[i] = current_page
                    current_page += 1
                break_cursor += 1
            else:
                page_map[i] = current_page
        total_pages = current_page
    else:
        # No explicit breaks — estimate from accumulated character count
        CHARS_PER_PAGE = 600
        page_map = {}
        current_page = 1
        char_count = 0
        for i in range(total):
            page_map[i] = current_page
            char_count += len(paras[i][1])
            if char_count >= CHARS_PER_PAGE:
                current_page += 1
                char_count = 0
        total_pages = current_page

    return page_map, total_pages


MAX_CONTEXT_CHARS = 100
MAX_CONTEXT_WITH_NEARBY_IMAGE = 80


def _para_has_image(elem, image_rel_ids):
    """Check if a paragraph element contains any image relationship reference."""
    xml_str = etree.tostring(elem, encoding='unicode')
    for rid in image_rel_ids:
        if re.search(rf'\b{re.escape(rid)}\b', xml_str):
            return True
    return False


def _extract_context_before(para_flat_idx, all_paras, image_rel_ids):
    """Extract up to 100 chars of text before an image, or 80 if another image is nearby."""
    chars = []
    char_count = 0
    hit_image = False

    for i in range(para_flat_idx - 1, -1, -1):
        elem, text = all_paras[i]
        if _para_has_image(elem, image_rel_ids):
            hit_image = True
            break
        if text:
            remaining = MAX_CONTEXT_CHARS - char_count
            if len(text) <= remaining:
                chars.insert(0, text)
                char_count += len(text)
            else:
                chars.insert(0, text[-remaining:])
                char_count = MAX_CONTEXT_CHARS
                break
        if char_count >= MAX_CONTEXT_CHARS:
            break

    result = ' '.join(chars).strip()
    limit = MAX_CONTEXT_WITH_NEARBY_IMAGE if hit_image else MAX_CONTEXT_CHARS
    if len(result) > limit:
        result = result[-limit:]
    return result


def _extract_context_after(para_flat_idx, all_paras, image_rel_ids):
    """Extract up to 100 chars of text after an image, or 80 if another image is nearby."""
    chars = []
    char_count = 0
    hit_image = False

    for i in range(para_flat_idx + 1, len(all_paras)):
        elem, text = all_paras[i]
        if _para_has_image(elem, image_rel_ids):
            hit_image = True
            break
        if text:
            remaining = MAX_CONTEXT_CHARS - char_count
            if len(text) <= remaining:
                chars.append(text)
                char_count += len(text)
            else:
                chars.append(text[:remaining])
                char_count = MAX_CONTEXT_CHARS
                break
        if char_count >= MAX_CONTEXT_CHARS:
            break

    result = ' '.join(chars).strip()
    limit = MAX_CONTEXT_WITH_NEARBY_IMAGE if hit_image else MAX_CONTEXT_CHARS
    if len(result) > limit:
        result = result[:limit]
    return result


def _collect_part_images(part, paras, seen_hashes, image_idx, output_dir, all_paras_all, image_rel_ids_all, page_map, source_tag=''):
    """Extract images from a single document part (body, header, or footer).

    Returns: (images_list, image_idx, duplicates_list, seen_hashes)
    """
    images = []
    duplicates = []

    rels = part.rels
    for rel_id, rel in rels.items():
        if "image" not in rel.reltype:
            continue
        try:
            image_data = rel.target_part.blob
            image_md5 = hashlib.md5(image_data).hexdigest()

            if image_md5 in seen_hashes:
                duplicates.append({
                    'md5': image_md5,
                    'first_index': seen_hashes[image_md5],
                    'rel_id': rel_id,
                })
                continue

            ext = rel.target_part.partname.split('.')[-1]
            ext_lower = ext.lower()
            if ext_lower not in ('png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'):
                ext = 'png'

            image_idx += 1
            seen_hashes[image_md5] = image_idx
            filename = f"image_{image_idx:03d}.{ext}"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'wb') as f:
                f.write(image_data)

            # EMF/WMF 转换：浏览器无法显示，尝试用 Pillow 转 PNG
            if ext_lower in ('emf', 'wmf'):
                try:
                    from PIL import Image
                    img = Image.open(filepath)
                    img.load()
                    os.remove(filepath)
                    filename = f"image_{image_idx:03d}.png"
                    filepath = os.path.join(output_dir, filename)
                    img.save(filepath, 'PNG')
                    ext = 'png'
                    logger.info(f"EMF/WMF 已转换为 PNG: {filename}")
                except Exception as e:
                    logger.warning(f"EMF/WMF 转换失败，保留原文件: {e}")

            # Find the paragraph that contains this image's relationship ID
            para_flat_idx = -1
            para_text = ""
            rel_pattern = re.compile(rf'\b{re.escape(rel_id)}\b')
            for flat_idx, (elem, text) in enumerate(paras):
                xml_str = etree.tostring(elem, encoding='unicode')
                if rel_pattern.search(xml_str):
                    para_flat_idx = flat_idx
                    para_text = text
                    break

            # 如果当前 part 的段落里没找到，尝试在全部段落中搜索（表格嵌套等场景）
            if para_flat_idx < 0 and all_paras_all is not paras:
                for flat_idx, (elem, text) in enumerate(all_paras_all):
                    xml_str = etree.tostring(elem, encoding='unicode')
                    if rel_pattern.search(xml_str):
                        para_flat_idx = flat_idx
                        para_text = text
                        break

            # 上下文提取
            context_before = ""
            context_after = ""
            if para_flat_idx >= 0:
                search_paras = all_paras_all if all_paras_all is not paras else paras
                context_before = _extract_context_before(para_flat_idx, search_paras, image_rel_ids_all)
                context_after = _extract_context_after(para_flat_idx, search_paras, image_rel_ids_all)

            # Full context for classification
            full_context = ""
            if para_flat_idx >= 0:
                search_paras = all_paras_all if all_paras_all is not paras else paras
                start = max(0, para_flat_idx - 1)
                end = min(len(search_paras), para_flat_idx + 3)
                for i in range(start, end):
                    t = search_paras[i][1]
                    if t:
                        full_context += t + " "
            full_context = full_context.strip()

            figure_name = (context_after or '').strip()[:20] or '图后无文字'
            pg = page_map.get(para_flat_idx, 1) if para_flat_idx >= 0 else 1

            images.append({
                'index': image_idx,
                'filename': filename,
                'filepath': filepath,
                'context': full_context[:500],
                'context_before': context_before[:300],
                'context_after': context_after[:300],
                'ext': ext,
                'figure_name': figure_name,
                'page_number': pg,
                'para_position': para_flat_idx,
                'source': source_tag,
            })

            logger.info(f"图片 {image_idx}: {filename} 来源={source_tag or '正文'} 图名=[{figure_name}] 下文=[{context_after[:50] or '无'}]")

        except Exception as e:
            logger.error(f"提取图片失败 rel_id={rel_id}: {e}")

    return images, image_idx, duplicates, seen_hashes


def extract_images_from_docx(file_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    try:
        doc = Document(file_path)
    except Exception as e:
        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"文件不存在: {abs_path}")
        if os.path.getsize(abs_path) == 0:
            raise ValueError(f"文件为空: {abs_path}")
        with open(abs_path, 'rb') as f:
            header = f.read(4)
        if header[:2] == b'\xd0\xcf':
            raise ValueError(
                f"该文件是旧版 .doc 格式（二进制），无法直接解析。"
                f"请用 Word 另存为 .docx 格式后重新上传。"
            )
        raise ValueError(f"无法打开文档: {e}")

    all_images = []
    all_duplicates = []
    image_idx = 0
    seen_hashes = {}

    # 正文段落
    body_paras = _collect_all_paras(doc)
    page_map, total_pages = _build_page_map(body_paras)

    # 收集全局 image_rel_ids（用于上下文提取时的邻近图片检测）
    global_image_rel_ids = set()
    global_image_rel_ids.update(rid for rid, r in doc.part.rels.items() if "image" in r.reltype)
    for section in doc.sections:
        for hf_part in [_hf for _hf in [section.header, section.footer] if _hf]:
            global_image_rel_ids.update(rid for rid, r in hf_part.part.rels.items() if "image" in r.reltype)
    # 也收集所有节的页眉页脚
    for i, section in enumerate(doc.sections):
        for hf_type, hf_name in [('header', '页眉'), ('footer', '页脚')]:
            hf = section.header if hf_type == 'header' else section.footer
            if not hf:
                continue
            try:
                hf_paras = _collect_all_paras(hf)
                hf_imgs, image_idx, hf_dups, seen_hashes = _collect_part_images(
                    hf.part, hf_paras, seen_hashes, image_idx,
                    output_dir, body_paras, global_image_rel_ids, page_map,
                    source_tag=f'{hf_name}(第{i+1}节)'
                )
                all_images.extend(hf_imgs)
                all_duplicates.extend(hf_dups)
            except Exception as e:
                logger.warning(f"提取{hf_name}图片失败: {e}")

    # 正文图片
    body_imgs, image_idx, body_dups, seen_hashes = _collect_part_images(
        doc.part, body_paras, seen_hashes, image_idx,
        output_dir, body_paras, global_image_rel_ids, page_map,
        source_tag='正文'
    )
    all_images.extend(body_imgs)
    all_duplicates.extend(body_dups)

    # 排序：正文在前（按段落位置），页眉页脚在后
    all_images.sort(key=lambda img: (
        0 if img.get('source', '').startswith('正文') else 1,
        img['para_position'] if img['para_position'] >= 0 else 9999,
    ))

    # 重新编号
    for new_idx, img in enumerate(all_images, 1):
        img['index'] = new_idx

    logger.info(f"从文档中提取了 {len(all_images)} 张图片（正文+页眉页脚），去除 {len(all_duplicates)} 张重复")
    return {
        'total': len(all_images),
        'images': all_images,
        'output_dir': output_dir,
        'duplicates_removed': len(all_duplicates),
        'duplicate_details': all_duplicates,
    }


def extract_figure_name(context, context_after=''):
    """Extract figure name from context text like '图1 总平面布置图' or '图1-1 基础结构'.

    Falls back to trying context_after text if context doesn't match patterns.
    """
    if not context and not context_after:
        return ''

    sources = [context] if context else []
    if context_after and context_after != context:
        sources.append(context_after)

    for source in sources:
        if not source:
            continue

        patterns = [
            # 图1-1 xxx / 图1.1 xxx / 图1—1 xxx
            r'图\s*(\d+[-–—―.]\d+)\s*[：:\s]+(.{1,60})',
            # 图1 xxx
            r'图\s*(\d+)\s*[：:\s]+(.{1,60})',
            # Figure 1-1 xxx / Figure 1 xxx
            r'Figure\s*(\d+[-–—―.]?\d*)\s*[：:\s]+(.{1,60})',
            # 附图1 xxx / 示意图1-1 xxx
            r'(?:附图|示意图|图纸)\s*(\d+[-–—―.]?\d*)\s*[：:\s]+(.{1,60})',
            # 表1 xxx (some docs label images as tables)
            r'表\s*(\d+[-–—―.]?\d*)\s*[：:\s]+(.{1,60})',
        ]

        for pattern in patterns:
            match = re.search(pattern, source)
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
            match = re.search(pattern, source)
            if match:
                return f'图{match.group(1)}'

    # 最终兜底：用 context_after 的第一段有意义文字作为图名
    if context_after:
        first_line = context_after.strip().split('\n')[0].strip()
        # 去掉明显不是图名的内容（长度、特殊字符等）
        if 2 < len(first_line) <= 40 and not first_line.startswith(('http', 'www', '（', '(')):
            first_line = re.sub(r'\s+', ' ', first_line).strip()
            return first_line[:30]

    return ''


def guess_category_from_context(context, figure_name='', filename=''):
    """委托到 ClassifierService，返回最可能的类别名称。

    保留旧签名兼容 (context: str) -> str，同时支持新参数。
    """
    from .classifier_service import classify
    result = classify(
        context=context or '',
        figure_name=figure_name or '',
        filename=filename or '',
    )
    return result.category


def guess_category_with_confidence(context='', figure_name='', filename=''):
    """多信号融合分类，返回完整的 ClassificationResult（含置信度）。"""
    from .classifier_service import classify
    return classify(
        context=context or '',
        figure_name=figure_name or '',
        filename=filename or '',
    )


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
