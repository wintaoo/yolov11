from flask import Blueprint, request, jsonify, current_app, send_file
from backend.app.services.docx_service import extract_images_from_docx, guess_category_from_context
from backend.app.services.ai_analysis_service import analyze_image_with_ai
from backend.app.services import task_service
from backend.app.config import Config
import os
import re
import uuid
import threading
import logging
import time
import random
import concurrent.futures
from datetime import datetime

docx_bp = Blueprint('docx', __name__)
analysis_tasks = {}
logger = logging.getLogger(__name__)


def _task_dir(task_id):
    return task_service.task_dir(Config.TASKS_DIR, task_id)


def _images_dir(task_id):
    return task_service.images_dir(Config.TASKS_DIR, task_id)


@docx_bp.route('/upload', methods=['POST'])
def upload_docx():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': '未找到上传的文件'})

        file = request.files['file']
        if not file.filename.lower().endswith('.docx'):
            return jsonify({'success': False, 'error': '仅支持 .docx 格式的Word文档'})

        safe_name = re.sub(r'[\\/:*?"<>|]', '_', file.filename.rsplit('.', 1)[0])[:20]
        task_id = f"{safe_name}_{str(uuid.uuid4())[:6]}"
        td = _task_dir(task_id)
        img_dir = _images_dir(task_id)
        os.makedirs(td, exist_ok=True)

        docx_path = os.path.join(td, 'original.docx')
        file.save(docx_path)

        extract_result = extract_images_from_docx(docx_path, img_dir)

        for img in extract_result['images']:
            img['guessed_category'] = guess_category_from_context(img.get('context', ''))

        analysis_tasks[task_id] = {
            'status': 'extracted',
            'task_id': task_id,
            'original_filename': file.filename,
            'total_images': extract_result['total'],
            'images': extract_result['images'],
            'output_dir': img_dir,
            'results': {},
            'summary': '',
            'created_at': datetime.now().isoformat(),
        }

        task_service.save_task(Config.TASKS_DIR, task_id, analysis_tasks[task_id])

        category_guess_stats = {}
        for img in extract_result['images']:
            cat = img.get('guessed_category', '其他')
            category_guess_stats[cat] = category_guess_stats.get(cat, 0) + 1

        return jsonify({
            'success': True,
            'task_id': task_id,
            'total_images': extract_result['total'],
            'images': [{
                'index': img['index'],
                'filename': img['filename'],
                'context': img['context'],
                'guessed_category': img['guessed_category'],
            } for img in extract_result['images']],
            'category_guess': category_guess_stats,
        })

    except Exception as e:
        current_app.logger.error(f"DOCX上传失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


@docx_bp.route('/analyze/<task_id>', methods=['POST'])
def analyze_batch(task_id):
    if task_id not in analysis_tasks:
        return jsonify({'success': False, 'error': '任务不存在，请重新上传'})

    task = analysis_tasks[task_id]
    if task.get('batch_running'):
        return jsonify({'success': False, 'error': '批量分析进行中'})

    task['batch_running'] = True
    task['batch_progress'] = 0
    task['batch_total'] = task['total_images']
    task['batch_results'] = {}
    task['batch_summary'] = ''
    task['status'] = 'analyzing'
    task_service.save_task(Config.TASKS_DIR, task_id, task)

    def run_batch():
        try:
            images = task['images']
            total = len(images)
            progress_lock = threading.Lock()

            def analyze_one(img):
                idx = str(img['index'])
                logger.info(f"批量分析 [{task_id}] #{idx}: {img['filename']}")
                result = analyze_image_with_ai(img['filepath'], img.get('context', ''))
                with progress_lock:
                    task['batch_results'][idx] = result
                    task['batch_progress'] = task.get('batch_progress', 0) + 1
                    task_service.save_results(Config.TASKS_DIR, task_id, {idx: result})
                logger.info(f"  完成 #{idx}: 类型={result.get('image_type', '?')} 摘要={result.get('summary','')[:40]}... 评估={result.get('evaluation','')[:30]}...")
                return result

            max_workers = min(5, total)
            logger.info(f"批量分析 [{task_id}] 共{total}张, 并发数={max_workers}")

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(analyze_one, img): img for img in images}
                concurrent.futures.wait(futures)

            task['batch_status'] = 'summarizing'
            summary = generate_summary(task['batch_results'])
            task['batch_summary'] = summary
            task_service.save_summary(Config.TASKS_DIR, task_id, summary)
            task_service.save_results(Config.TASKS_DIR, task_id, task['batch_results'])
            task_service.generate_analysis_report(Config.TASKS_DIR, task_id)
            task['batch_progress'] = total
            task['status'] = 'completed'
            task['batch_running'] = False
            task_service.save_task(Config.TASKS_DIR, task_id, task)
            logger.info(f"批量分析完成 [{task_id}]")

        except Exception as e:
            logger.error(f"批量分析失败 [{task_id}]: {str(e)}", exc_info=True)
            task['batch_running'] = False
            task['batch_error'] = str(e)
            task['status'] = 'error'
            task_service.save_task(Config.TASKS_DIR, task_id, task)

    t = threading.Thread(target=run_batch, daemon=True)
    t.start()

    return jsonify({'success': True, 'status': 'batch_started', 'total': task['batch_total']})


@docx_bp.route('/analyze-single/<task_id>/<int:index>', methods=['POST'])
def analyze_single(task_id, index):
    if task_id not in analysis_tasks:
        return jsonify({'success': False, 'error': '任务不存在，请重新上传'})

    task = analysis_tasks[task_id]
    img = next((x for x in task['images'] if x['index'] == index), None)
    if not img:
        return jsonify({'success': False, 'error': '图片不存在'})

    try:
        logger.info(f"单张分析 [{task_id}] #{index}: {img['filename']}")
        ai_result = analyze_image_with_ai(img['filepath'], img.get('context', ''))
        task['results'][str(index)] = ai_result
        task_service.save_results(Config.TASKS_DIR, task_id, {str(index): ai_result})
        task_service.generate_analysis_report(Config.TASKS_DIR, task_id)

        return jsonify({
            'success': True,
            'index': index,
            'result': ai_result,
        })
    except Exception as e:
        logger.error(f"单张分析失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


@docx_bp.route('/status/<task_id>', methods=['GET'])
def get_status(task_id):
    if task_id not in analysis_tasks:
        return jsonify({'success': False, 'error': '任务不存在'})

    task = analysis_tasks[task_id]
    return jsonify({
        'success': True,
        'task_id': task_id,
        'status': task.get('status', 'unknown'),
        'total_images': task['total_images'],
        'batch_running': task.get('batch_running', False),
        'batch_progress': task.get('batch_progress', 0),
        'batch_total': task.get('batch_total', 0),
        'batch_status': task.get('batch_status', ''),
        'batch_summary': task.get('batch_summary', ''),
        'results': task.get('batch_results', task.get('results', {})),
    })


@docx_bp.route('/image/<task_id>/<filename>', methods=['GET'])
def get_image(task_id, filename):
    possible_dirs = [
        _images_dir(task_id),
        _task_dir(task_id),
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
        analysis_tasks[task_id] = task_data
        return jsonify({
            'success': True,
            'task_id': task_id,
            'total_images': task_data['total_images'],
            'images': [{
                'index': img['index'],
                'filename': img['filename'],
                'context': img.get('context', ''),
                'guessed_category': img.get('guessed_category', '其他'),
            } for img in task_data.get('images', [])],
            'results': task_data.get('results', {}),
            'batch_summary': task_data.get('batch_summary', ''),
            'status': task_data.get('status', 'extracted'),
            'has_report': os.path.exists(os.path.join(_task_dir(task_id), 'analysis_report.md')),
        })
    except Exception as e:
        logger.error(f"加载任务失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@docx_bp.route('/task/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    try:
        analysis_tasks.pop(task_id, None)
        task_service.delete_task(Config.TASKS_DIR, task_id)
        return jsonify({'success': True, 'message': '任务已删除'})
    except Exception as e:
        logger.error(f"删除任务失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


def generate_summary(all_results):
    import requests
    contents = []
    for idx, r in sorted(all_results.items()):
        contents.append(f"- 图片{idx}: 类型[{r.get('image_type','未知')}] {r.get('summary','无')[:200]}")

    text = '\n'.join(contents)
    prompt = f"""以下是施工方案文档中所有图纸的分析结果，请生成一份综合摘要报告：

{text}

请生成结构化的汇总报告，包含：
1. 总体概述（该项目包含哪些类型的图纸，共多少张）
2. 各类型图纸统计
3. 关键发现和亮点
4. 存在的问题和风险点
5. 总体评价和建议

请直接输出报告内容，不要使用JSON格式。"""

    api_keys = Config.SILICONFLOW_API_KEY_LIST
    if not api_keys:
        return "汇总生成失败: 未配置API Key"
    api_key = random.choice(api_keys)

    try:
        resp = requests.post(
            Config.SILICONFLOW_API_URL,
            json={
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "messages": [
                    {"role": "system", "content": "你是一个专业的建筑工程图纸审查专家。"},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 2048,
                "temperature": 0.3,
            },
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content']
        return f"汇总生成失败: HTTP {resp.status_code}"
    except Exception as e:
        logger.error(f"摘要生成失败: {e}")
        return f"摘要生成失败: {str(e)}"
