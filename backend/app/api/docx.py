from flask import Blueprint, request, jsonify, current_app, send_file
from backend.app.services.docx_service import extract_images_from_docx, guess_category_from_context, guess_category_with_confidence
from backend.app.services import task_service
from backend.app.config import Config
import os
import re
import json
import hashlib
import shutil
import logging
import threading
from datetime import datetime

docx_bp = Blueprint('docx', __name__)
logger = logging.getLogger(__name__)


def _task_dir(task_id):
    return task_service.task_dir(Config.TASKS_DIR, task_id)


def _images_dir(task_id):
    return task_service.images_dir(Config.TASKS_DIR, task_id)


def _parsed_dir(task_id=None):
    base = Config.PARSED_IMAGES_DIR
    if task_id:
        return os.path.join(base, task_id)
    return base


def _file_md5(file_storage):
    """Compute MD5 hash of an uploaded file's content."""
    h = hashlib.md5()
    file_storage.seek(0)
    for chunk in iter(lambda: file_storage.read(8192), b''):
        h.update(chunk)
    file_storage.seek(0)
    return h.hexdigest()


def _process_in_background(task_id, docx_path, img_dir, original_filename):
    """后台线程：提取图片、分类、保存任务、复制到 parsed_images"""
    try:
        logger.info(f"后台处理开始 [{task_id}]")
        extract_result = extract_images_from_docx(docx_path, img_dir)

        for img in extract_result['images']:
            classification = guess_category_with_confidence(
                context=img.get('context', ''),
                figure_name=img.get('figure_name', ''),
                filename=img.get('filename', ''),
            )
            img['guessed_category'] = classification.category
            img['classification_confidence'] = classification.confidence
            img['classification_signals'] = classification.signal_breakdown

        task_data = {
            'status': 'extracted',
            'task_id': task_id,
            'original_filename': original_filename,
            'content_md5': '',
            'total_images': extract_result['total'],
            'duplicates_removed': extract_result.get('duplicates_removed', 0),
            'images': extract_result['images'],
            'output_dir': img_dir,
            'results': {},
            'summary': '',
            'created_at': datetime.now().isoformat(),
        }
        task_service.save_task(Config.TASKS_DIR, task_id, task_data)

        # 复制到 parsed_images
        parsed_task_dir = _parsed_dir(task_id)
        if os.path.exists(parsed_task_dir):
            shutil.rmtree(parsed_task_dir)
        os.makedirs(parsed_task_dir, exist_ok=True)
        for img in extract_result['images']:
            src = img['filepath']
            ext = img.get('ext', os.path.splitext(img['filename'])[1].lstrip('.'))
            figure_name = img.get('figure_name', '')
            if figure_name:
                safe_fn = re.sub(r'[\\/:*?"<>|]', '_', figure_name)[:100]
                base_filename = f"{safe_fn}.{ext}"
            else:
                base_filename = img['filename']
            dst_filename = base_filename
            collision = 2
            while os.path.exists(os.path.join(parsed_task_dir, dst_filename)):
                name_part, dot_ext = os.path.splitext(base_filename)
                dst_filename = f"{name_part}_{collision}{dot_ext}"
                collision += 1
            img['parsed_filename'] = dst_filename
            dst = os.path.join(parsed_task_dir, dst_filename)
            if os.path.exists(src):
                shutil.copy2(src, dst)

        _save_parsed_ref(task_id)
        logger.info(f"后台处理完成 [{task_id}]: {extract_result['total']} 张图片")

    except Exception as e:
        logger.error(f"后台处理失败 [{task_id}]: {e}", exc_info=True)
        try:
            task_service.save_task(Config.TASKS_DIR, task_id, {
                'status': 'error',
                'task_id': task_id,
                'original_filename': original_filename,
                'content_md5': '',
                'total_images': 0,
                'duplicates_removed': 0,
                'images': [],
                'output_dir': img_dir,
                'results': {},
                'summary': '',
                'error': str(e),
                'created_at': datetime.now().isoformat(),
            })
        except Exception:
            pass


@docx_bp.route('/upload', methods=['POST'])
def upload_docx():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': '未找到上传的文件'})

        file = request.files['file']
        if not file.filename.lower().endswith(('.docx', '.doc')):
            return jsonify({'success': False, 'error': '仅支持 .doc / .docx 格式的Word文档'})

        safe_name = re.sub(r'[\\/:*?"<>|]', '_', file.filename.rsplit('.', 1)[0])[:50]

        existing_tasks = task_service.list_tasks(Config.TASKS_DIR)
        same_doc = next((t for t in existing_tasks if t['original_filename'] == file.filename), None)

        if same_doc:
            task_id = same_doc['task_id']
            logger.info(f"检测到重复文档 [{file.filename}], 复用任务: {task_id}")
            task_data = task_service.load_task(Config.TASKS_DIR, task_id)
            if task_data:
                if task_data.get('status') == 'processing':
                    return jsonify({
                        'success': True, 'task_id': task_id,
                        'status': 'processing', 'message': '该文件正在后台解析中...',
                    })
                return _build_upload_response(task_data, task_id, reused=True)
            else:
                return jsonify({'success': False, 'error': '任务数据读取失败'})

        content_md5 = _file_md5(file)
        existing_by_hash = next(
            (t for t in existing_tasks
             if task_service.load_task_meta_field(Config.TASKS_DIR, t['task_id'], 'content_md5') == content_md5),
            None
        )
        if existing_by_hash:
            task_id = existing_by_hash['task_id']
            logger.info(f"检测到内容相同文档 (MD5={content_md5[:8]}), 复用任务: {task_id}")
            existing_data = task_service.load_task(Config.TASKS_DIR, task_id)
            if existing_data and existing_data.get('status') == 'processing':
                return jsonify({
                    'success': True, 'task_id': task_id,
                    'status': 'processing', 'message': '该文件正在后台解析中...',
                })
        else:
            task_id = safe_name
            base_id = task_id
            counter = 1
            while os.path.exists(_task_dir(task_id)):
                task_id = f"{base_id}_{counter}"
                counter += 1

        td = _task_dir(task_id)
        img_dir = _images_dir(task_id)
        os.makedirs(td, exist_ok=True)

        docx_path = os.path.join(td, 'original.docx')
        file.save(docx_path)

        if not os.path.exists(docx_path):
            return jsonify({'success': False, 'error': f'文件保存失败，路径不存在: {docx_path}'})
        if not os.path.getsize(docx_path):
            return jsonify({'success': False, 'error': '上传的文件为空'})

        # 保存初始任务状态，立即返回
        task_data = {
            'status': 'processing',
            'task_id': task_id,
            'original_filename': file.filename,
            'content_md5': content_md5,
            'total_images': 0,
            'duplicates_removed': 0,
            'images': [],
            'output_dir': img_dir,
            'results': {},
            'summary': '',
            'created_at': datetime.now().isoformat(),
        }
        task_service.save_task(Config.TASKS_DIR, task_id, task_data)

        # 后台线程处理
        thread = threading.Thread(
            target=_process_in_background,
            args=(task_id, docx_path, img_dir, file.filename),
            daemon=True
        )
        thread.start()

        logger.info(f"文档已保存，后台处理中 [{task_id}]: {file.filename}")
        return jsonify({
            'success': True,
            'task_id': task_id,
            'status': 'processing',
            'message': '文件已上传，正在后台解析...',
        })

    except Exception as e:
        current_app.logger.error(f"DOCX上传失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


def _build_upload_response(task_data, task_id, reused=False):
    """Build standardized upload response."""
    images = task_data.get('images', [])
    category_stats = {}
    for img in images:
        cat = img.get('guessed_category', '其他')
        category_stats[cat] = category_stats.get(cat, 0) + 1

    return jsonify({
        'success': True,
        'task_id': task_id,
        'reused': reused,
        'total_images': len(images),
        'duplicates_removed': task_data.get('duplicates_removed', 0),
        'images': [{
            'index': img['index'],
            'filename': img.get('parsed_filename', img['filename']),
            'original_filename': img.get('filename', ''),
            'context': img.get('context', ''),
            'context_before': img.get('context_before', ''),
            'context_after': img.get('context_after', ''),
            'guessed_category': img.get('guessed_category', '其他'),
            'classification_confidence': img.get('classification_confidence', 0.0),
            'classification_signals': img.get('classification_signals', {}),
            'figure_name': img.get('figure_name', ''),
            'page_number': img.get('page_number', 1),
            'manual_label': img.get('manual_label', ''),
        } for img in images],
        'category_stats': category_stats,
    })


def _save_parsed_ref(task_id):
    """Save reference to the latest parsed task."""
    ref_path = os.path.join(_parsed_dir(), '.last_parsed')
    os.makedirs(_parsed_dir(), exist_ok=True)
    with open(ref_path, 'w') as f:
        f.write(task_id)


def _get_latest_parsed_task_id():
    """Get the task_id of the most recently parsed document."""
    ref_path = os.path.join(_parsed_dir(), '.last_parsed')
    if os.path.exists(ref_path):
        with open(ref_path, 'r') as f:
            return f.read().strip()
    return None


@docx_bp.route('/parsed-folder', methods=['GET'])
def get_parsed_folder():
    """Return info about the latest parsed images folder."""
    task_id = _get_latest_parsed_task_id()
    if not task_id:
        return jsonify({'success': False, 'error': '没有解析过的文档'})

    parsed_task_dir = _parsed_dir(task_id)
    if not os.path.exists(parsed_task_dir):
        return jsonify({'success': False, 'error': '解析文件夹不存在，请重新上传文档'})

    images = []
    for fname in sorted(os.listdir(parsed_task_dir)):
        if not fname.startswith('.') and os.path.isfile(os.path.join(parsed_task_dir, fname)):
            fpath = os.path.join(parsed_task_dir, fname)
            images.append({
                'filename': fname,
                'size': os.path.getsize(fpath),
            })

    # Load task data for category info
    task_data = task_service.load_task(Config.TASKS_DIR, task_id)
    category_stats = {}
    image_figure_map = {}
    if task_data:
        for img in task_data.get('images', []):
            cat = img.get('guessed_category', '其他')
            category_stats[cat] = category_stats.get(cat, 0) + 1
            if img.get('parsed_filename') or img.get('figure_name'):
                image_figure_map[img.get('parsed_filename', img.get('filename', ''))] = {
                    'figure_name': img.get('figure_name', ''),
                    'guessed_category': img.get('guessed_category', '其他'),
                    'classification_confidence': img.get('classification_confidence', 0.0),
                    'page_number': img.get('page_number', 1),
                    'index': img.get('index', 0),
                }

    # Enrich image list with figure_name, page_number, and confidence
    for img_info in images:
        mapped = image_figure_map.get(img_info['filename'], {})
        img_info['figure_name'] = mapped.get('figure_name', '')
        img_info['guessed_category'] = mapped.get('guessed_category', '其他')
        img_info['classification_confidence'] = mapped.get('classification_confidence', 0.0)
        img_info['page_number'] = mapped.get('page_number', 1)
        img_info['index'] = mapped.get('index', 0)

    return jsonify({
        'success': True,
        'task_id': task_id,
        'folder': parsed_task_dir,
        'image_count': len(images),
        'images': images,
        'category_stats': category_stats,
        'doc_name': task_data.get('original_filename', '') if task_data else '',
    })


@docx_bp.route('/parsed-images/<task_id>', methods=['GET'])
def list_parsed_images(task_id):
    """List all images in a parsed folder."""
    parsed_task_dir = _parsed_dir(task_id)
    if not os.path.exists(parsed_task_dir):
        return jsonify({'success': False, 'error': '解析文件夹不存在'})

    images = []
    for fname in sorted(os.listdir(parsed_task_dir)):
        if not fname.startswith('.') and os.path.isfile(os.path.join(parsed_task_dir, fname)):
            fpath = os.path.join(parsed_task_dir, fname)
            images.append({
                'filename': fname,
                'size': os.path.getsize(fpath),
                'url': f'/api/docx/parsed-image/{task_id}/{fname}',
            })

    return jsonify({
        'success': True,
        'task_id': task_id,
        'images': images,
        'total': len(images),
    })


@docx_bp.route('/parsed-image/<task_id>/<filename>', methods=['GET'])
def serve_parsed_image(task_id, filename):
    """Serve an image from the parsed folder."""
    parsed_task_dir = _parsed_dir(task_id)
    p = os.path.join(parsed_task_dir, filename)
    if not os.path.exists(p):
        return jsonify({'success': False, 'error': '文件不存在'}), 404
    ext = os.path.splitext(filename)[1].lower()
    mime = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
            '.bmp': 'image/bmp', '.gif': 'image/gif', '.webp': 'image/webp'}
    return send_file(p, mimetype=mime.get(ext, 'image/png'))


@docx_bp.route('/status/<task_id>', methods=['GET'])
def get_status(task_id):
    """Get simple status for a task."""
    task_data = task_service.load_task(Config.TASKS_DIR, task_id)
    if not task_data:
        return jsonify({'success': False, 'error': '任务不存在'})

    category_stats = {}
    for img in task_data.get('images', []):
        cat = img.get('guessed_category', '其他')
        category_stats[cat] = category_stats.get(cat, 0) + 1

    return jsonify({
        'success': True,
        'task_id': task_id,
        'status': task_data.get('status', 'extracted'),
        'total_images': task_data.get('total_images', 0),
        'duplicates_removed': task_data.get('duplicates_removed', 0),
        'images': [{
            'index': img['index'],
            'filename': img.get('parsed_filename', img.get('filename', '')),
            'original_filename': img.get('filename', ''),
            'context': img.get('context', ''),
            'context_before': img.get('context_before', ''),
            'context_after': img.get('context_after', ''),
            'guessed_category': img.get('guessed_category', '其他'),
            'classification_confidence': img.get('classification_confidence', 0.0),
            'classification_signals': img.get('classification_signals', {}),
            'figure_name': img.get('figure_name', ''),
            'page_number': img.get('page_number', 1),
            'manual_label': img.get('manual_label', ''),
        } for img in task_data.get('images', [])],
        'category_stats': category_stats,
    })


@docx_bp.route('/image/<task_id>/<filename>', methods=['GET'])
def get_image(task_id, filename):
    possible_dirs = [
        _images_dir(task_id),
        _task_dir(task_id),
        _parsed_dir(task_id),
    ]
    for d in possible_dirs:
        p = os.path.join(d, filename)
        if os.path.exists(p):
            ext = os.path.splitext(filename)[1].lower()
            mime = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                    '.bmp': 'image/bmp', '.gif': 'image/gif', '.webp': 'image/webp'}
            return send_file(p, mimetype=mime.get(ext, 'image/png'))
    return jsonify({'success': False, 'error': '文件不存在'}), 404


@docx_bp.route('/tasks', methods=['GET'])
def list_tasks():
    try:
        tasks = task_service.list_tasks(Config.TASKS_DIR)
        return jsonify({'success': True, 'tasks': tasks})
    except Exception as e:
        logger.error(f"列出任务失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@docx_bp.route('/task/<task_id>/load', methods=['POST'])
def load_task(task_id):
    try:
        task_data = task_service.load_task(Config.TASKS_DIR, task_id)
        if not task_data:
            return jsonify({'success': False, 'error': '任务不存在'})

        category_stats = {}
        for img in task_data.get('images', []):
            cat = img.get('guessed_category', '其他')
            category_stats[cat] = category_stats.get(cat, 0) + 1

        return jsonify({
            'success': True,
            'task_id': task_id,
            'total_images': task_data.get('total_images', 0),
            'duplicates_removed': task_data.get('duplicates_removed', 0),
            'images': [{
                'index': img['index'],
                'filename': img.get('parsed_filename', img.get('filename', '')),
                'original_filename': img.get('filename', ''),
                'context': img.get('context', ''),
                'context_before': img.get('context_before', ''),
                'context_after': img.get('context_after', ''),
                'guessed_category': img.get('guessed_category', '其他'),
                'classification_confidence': img.get('classification_confidence', 0.0),
                'classification_signals': img.get('classification_signals', {}),
                'figure_name': img.get('figure_name', ''),
                'page_number': img.get('page_number', 1),
                'manual_label': img.get('manual_label', ''),
            } for img in task_data.get('images', [])],
            'category_stats': category_stats,
            'status': task_data.get('status', 'extracted'),
        })
    except Exception as e:
        logger.error(f"加载任务失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@docx_bp.route('/task/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    try:
        task_service.delete_task(Config.TASKS_DIR, task_id)
        # Also clean up parsed folder
        parsed_task_dir = _parsed_dir(task_id)
        if os.path.exists(parsed_task_dir):
            shutil.rmtree(parsed_task_dir)
        # Clear ref if it points to this task
        ref_path = os.path.join(_parsed_dir(), '.last_parsed')
        if os.path.exists(ref_path):
            with open(ref_path, 'r') as f:
                if f.read().strip() == task_id:
                    os.remove(ref_path)
        return jsonify({'success': True, 'message': '任务已删除'})
    except Exception as e:
        logger.error(f"删除任务失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@docx_bp.route('/docs-files', methods=['GET'])
def list_docs_files():
    """列出 docs 文件夹中的所有 Word 文件"""
    docs_dir = Config.DOCS_DIR
    if not os.path.exists(docs_dir):
        return jsonify({'success': True, 'files': [], 'folder': docs_dir})
    try:
        files = []
        for fname in sorted(os.listdir(docs_dir)):
            if fname.startswith('.'):
                continue
            fpath = os.path.join(docs_dir, fname)
            fname_lower = fname.lower()
            if os.path.isfile(fpath) and (fname_lower.endswith('.docx') or fname_lower.endswith('.doc')):
                files.append({
                    'name': fname,
                    'size': os.path.getsize(fpath),
                    'mtime': os.path.getmtime(fpath),
                })
        return jsonify({'success': True, 'files': files, 'folder': docs_dir})
    except Exception as e:
        logger.error(f"列出docs文件失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@docx_bp.route('/upload-from-docs', methods=['POST'])
def upload_from_docs():
    """从 docs 文件夹中选择文件进行解析（避免重复上传大文件）"""
    try:
        data = request.get_json() or {}
        filename = data.get('filename', '')
        if not filename:
            return jsonify({'success': False, 'error': '缺少文件名'})

        # 安全检查：防止目录穿越
        safe_name = os.path.basename(filename)
        filepath = os.path.join(Config.DOCS_DIR, safe_name)
        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': '文件不存在'})
        if not safe_name.lower().endswith(('.docx', '.doc')):
            return jsonify({'success': False, 'error': '仅支持 .doc / .docx 格式'})

        safe_id = re.sub(r'[\\/:*?"<>|]', '_', safe_name.rsplit('.', 1)[0])[:50]
        content_md5 = _file_md5_path(filepath)

        # 检查重复
        existing_tasks = task_service.list_tasks(Config.TASKS_DIR)
        same_doc = next((t for t in existing_tasks if t['original_filename'] == safe_name), None)
        if same_doc:
            task_id = same_doc['task_id']
            logger.info(f"检测到重复文档 [{safe_name}], 复用任务: {task_id}")
            task_data = task_service.load_task(Config.TASKS_DIR, task_id)
            if task_data:
                if task_data.get('status') == 'processing':
                    return jsonify({
                        'success': True, 'task_id': task_id,
                        'status': 'processing', 'message': '该文件正在后台解析中...',
                    })
                return _build_upload_response(task_data, task_id, reused=True)

        existing_by_hash = next(
            (t for t in existing_tasks
             if task_service.load_task_meta_field(Config.TASKS_DIR, t['task_id'], 'content_md5') == content_md5),
            None
        )
        if existing_by_hash:
            task_id = existing_by_hash['task_id']
            logger.info(f"检测到内容相同文档 (MD5={content_md5[:8]}), 复用任务: {task_id}")
            existing_data = task_service.load_task(Config.TASKS_DIR, task_id)
            if existing_data and existing_data.get('status') == 'processing':
                return jsonify({
                    'success': True, 'task_id': task_id,
                    'status': 'processing', 'message': '该文件正在后台解析中...',
                })
        else:
            task_id = safe_id
            base_id = task_id
            counter = 1
            while os.path.exists(_task_dir(task_id)):
                task_id = f"{base_id}_{counter}"
                counter += 1

        td = _task_dir(task_id)
        img_dir = _images_dir(task_id)
        os.makedirs(td, exist_ok=True)

        docx_path = os.path.join(td, 'original.docx')
        if filepath != docx_path:
            shutil.copy2(filepath, docx_path)

        if not os.path.exists(docx_path):
            return jsonify({'success': False, 'error': f'文件复制失败，路径不存在: {docx_path}'})
        if not os.path.getsize(docx_path):
            return jsonify({'success': False, 'error': 'docs 文件夹中的文件为空'})

        # 保存初始状态，后台处理
        task_data = {
            'status': 'processing',
            'task_id': task_id,
            'original_filename': safe_name,
            'content_md5': content_md5,
            'total_images': 0,
            'duplicates_removed': 0,
            'images': [],
            'output_dir': img_dir,
            'results': {},
            'summary': '',
            'created_at': datetime.now().isoformat(),
        }
        task_service.save_task(Config.TASKS_DIR, task_id, task_data)

        thread = threading.Thread(
            target=_process_in_background,
            args=(task_id, docx_path, img_dir, safe_name),
            daemon=True
        )
        thread.start()

        logger.info(f"从docs文件已复制，后台处理中 [{task_id}]: {safe_name}")
        return jsonify({
            'success': True,
            'task_id': task_id,
            'status': 'processing',
            'message': '文件已就绪，正在后台解析...',
        })

    except Exception as e:
        current_app.logger.error(f"从docs解析失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


def _file_md5_path(filepath):
    """Compute MD5 hash of a file on disk."""
    h = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


@docx_bp.route('/task/<task_id>/label', methods=['POST'])
def update_image_label(task_id):
    """手动更新图片分类标签（支持预定义类别和自定义输入）"""
    try:
        data = request.get_json() or {}
        image_index = data.get('image_index')
        manual_label = data.get('manual_label', '').strip()

        if image_index is None:
            return jsonify({'success': False, 'error': '缺少 image_index'})

        task_data = task_service.load_task(Config.TASKS_DIR, task_id)
        if not task_data:
            return jsonify({'success': False, 'error': '任务不存在'})

        # 查找并更新指定图片
        found = False
        for img in task_data.get('images', []):
            if img['index'] == image_index:
                img['manual_label'] = manual_label
                found = True
                break

        if not found:
            return jsonify({'success': False, 'error': f'图片 #{image_index} 不存在'})

        # 保存更新后的任务数据
        task_service.save_task(Config.TASKS_DIR, task_id, task_data)

        # 重新计算分类统计（手动标签优先）
        category_stats = {}
        for img in task_data.get('images', []):
            cat = img.get('manual_label') or img.get('guessed_category', '其他')
            category_stats[cat] = category_stats.get(cat, 0) + 1

        logger.info(f"图片标签已更新 [{task_id}] #{image_index} -> '{manual_label}'")
        return jsonify({
            'success': True,
            'task_id': task_id,
            'image_index': image_index,
            'manual_label': manual_label,
            'category_stats': category_stats,
        })

    except Exception as e:
        logger.error(f"更新标签失败: {e}")
        return jsonify({'success': False, 'error': str(e)})
