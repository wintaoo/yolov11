from flask import Blueprint, request, jsonify, current_app, send_file
from backend.app.services.docx_service import extract_images_from_docx, guess_category_from_context
from backend.app.services import task_service
from backend.app.config import Config
import os
import re
import json
import hashlib
import shutil
import logging
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


@docx_bp.route('/upload', methods=['POST'])
def upload_docx():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': '未找到上传的文件'})

        file = request.files['file']
        if not file.filename.lower().endswith('.docx'):
            return jsonify({'success': False, 'error': '仅支持 .docx 格式的Word文档'})

        safe_name = re.sub(r'[\\/:*?"<>|]', '_', file.filename.rsplit('.', 1)[0])[:50]

        existing_tasks = task_service.list_tasks(Config.TASKS_DIR)
        same_doc = next((t for t in existing_tasks if t['original_filename'] == file.filename), None)

        if same_doc:
            task_id = same_doc['task_id']
            logger.info(f"检测到重复文档 [{file.filename}], 复用任务: {task_id}")
            task_data = task_service.load_task(Config.TASKS_DIR, task_id)
            if task_data:
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

        extract_result = extract_images_from_docx(docx_path, img_dir)

        for img in extract_result['images']:
            img['guessed_category'] = guess_category_from_context(img.get('context', ''))

        task_data = {
            'status': 'extracted',
            'task_id': task_id,
            'original_filename': file.filename,
            'content_md5': content_md5,
            'total_images': extract_result['total'],
            'images': extract_result['images'],
            'output_dir': img_dir,
            'results': {},
            'summary': '',
            'created_at': datetime.now().isoformat(),
        }

        task_service.save_task(Config.TASKS_DIR, task_id, task_data)

        # Copy extracted images to parsed_images folder for DetectionPanel access
        # Rename using figure_name when available
        parsed_task_dir = _parsed_dir(task_id)
        if os.path.exists(parsed_task_dir):
            shutil.rmtree(parsed_task_dir)
        os.makedirs(parsed_task_dir, exist_ok=True)
        for img in extract_result['images']:
            src = img['filepath']
            ext = img.get('ext', os.path.splitext(img['filename'])[1].lstrip('.'))
            figure_name = img.get('figure_name', '')
            if figure_name:
                safe_name = re.sub(r'[\\/:*?"<>|]', '_', figure_name)[:100]
                base_filename = f"{safe_name}.{ext}"
            else:
                base_filename = img['filename']
            # Deduplicate: if file exists, append _2, _3, etc.
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

        # Save the active parsed task reference
        _save_parsed_ref(task_id)

        logger.info(f"文档解析完成 [{task_id}]: {extract_result['total']} 张图片 -> {parsed_task_dir}")

        return _build_upload_response(task_data, task_id, reused=False)

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
        'images': [{
            'index': img['index'],
            'filename': img.get('parsed_filename', img['filename']),
            'original_filename': img.get('filename', ''),
            'context': img.get('context', ''),
            'guessed_category': img.get('guessed_category', '其他'),
            'figure_name': img.get('figure_name', ''),
            'page_number': img.get('page_number', 1),
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
                    'page_number': img.get('page_number', 1),
                    'index': img.get('index', 0),
                }

    # Enrich image list with figure_name and page_number
    for img_info in images:
        mapped = image_figure_map.get(img_info['filename'], {})
        img_info['figure_name'] = mapped.get('figure_name', '')
        img_info['guessed_category'] = mapped.get('guessed_category', '其他')
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
        'images': [{
            'index': img['index'],
            'filename': img.get('parsed_filename', img.get('filename', '')),
            'original_filename': img.get('filename', ''),
            'context': img.get('context', ''),
            'guessed_category': img.get('guessed_category', '其他'),
            'figure_name': img.get('figure_name', ''),
            'page_number': img.get('page_number', 1),
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
            'images': [{
                'index': img['index'],
                'filename': img.get('parsed_filename', img.get('filename', '')),
                'original_filename': img.get('filename', ''),
                'context': img.get('context', ''),
                'guessed_category': img.get('guessed_category', '其他'),
                'figure_name': img.get('figure_name', ''),
                'page_number': img.get('page_number', 1),
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
