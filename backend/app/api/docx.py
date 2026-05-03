from flask import Blueprint, request, jsonify, current_app, send_file, Response, stream_with_context
from backend.app.services.docx_service import extract_images_from_docx, guess_category_from_context
from backend.app.services.ai_analysis_service import analyze_image_with_ai
from backend.app.services import task_service
from backend.app.config import Config
import os
import re
import json
import hashlib
import queue
import threading
import logging
import time
import random
import concurrent.futures
from datetime import datetime

docx_bp = Blueprint('docx', __name__)
analysis_tasks = {}
progress_queues = {}
logger = logging.getLogger(__name__)


def _task_dir(task_id):
    return task_service.task_dir(Config.TASKS_DIR, task_id)


def _images_dir(task_id):
    return task_service.images_dir(Config.TASKS_DIR, task_id)


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
                task_data['task_id'] = task_id
                analysis_tasks[task_id] = task_data
                results = task_data.get('results', {})
                batch_summary = task_data.get('batch_summary', '')
                analyzed_count = len(results)
                total = task_data.get('total_images', 0)

                cat_stats = {}
                for img in task_data.get('images', []):
                    idx = img['index']
                    if str(idx) in results:
                        cat_stats[results[str(idx)].get('image_type', img.get('guessed_category', '其他'))] = \
                            cat_stats.get(results[str(idx)].get('image_type', img.get('guessed_category', '其他')), 0) + 1
                    else:
                        cat_stats[img.get('guessed_category', '其他')] = \
                            cat_stats.get(img.get('guessed_category', '其他'), 0) + 1

                status = task_data.get('status', 'extracted')
                if status == 'completed':
                    hint = f'该文件已有完整分析结果（{analyzed_count}/{total} 张），已自动恢复'
                elif status == 'analyzing' or status == 'extracted':
                    hint = f'该文件已有历史任务（已分析 {analyzed_count}/{total} 张），可继续分析'
                elif status == 'error':
                    hint = f'该文件上次分析异常，已恢复（已分析 {analyzed_count}/{total} 张），可继续分析'
                else:
                    hint = f'该文件已有历史记录（{analyzed_count}/{total} 张）'

                return jsonify({
                    'success': True,
                    'task_id': task_id,
                    'reused': True,
                    'reuse_hint': hint,
                    'analyzed_count': analyzed_count,
                    'total_images': total,
                    'status': status,
                    'images': [{
                        'index': img['index'],
                        'filename': img['filename'],
                        'context': img.get('context', ''),
                        'guessed_category': img.get('guessed_category', '其他'),
                    } for img in task_data.get('images', [])],
                    'results': results,
                    'batch_summary': batch_summary,
                    'category_guess': cat_stats,
                })

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

        analysis_tasks[task_id] = {
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
    task['batch_error_count'] = 0
    task_service.save_task(Config.TASKS_DIR, task_id, task)

    def run_batch():
        try:
            # Only re-process unanalyzed or previously-errored images
            existing_results = task.get('results', {})
            pending_images = []
            for img in task['images']:
                idx = str(img['index'])
                result = existing_results.get(idx)
                if result is None or result.get('_error'):
                    pending_images.append(img)

            total = len(pending_images)
            progress_lock = threading.Lock()
            error_count = 0
            pq = queue.Queue()
            progress_queues[task_id] = pq

            # Pre-populate with already successful results so they survive the batch
            for img in task['images']:
                idx = str(img['index'])
                result = existing_results.get(idx)
                if result is not None and not result.get('_error'):
                    task['batch_results'][idx] = result
                    task_service.save_results(Config.TASKS_DIR, task_id, {idx: result})

            logger.info(f"批量分析 [{task_id}] 共{task['total_images']}张, 待处理{total}张(跳过{task['total_images'] - total}张已完成)")

            if total == 0:
                task['batch_progress'] = 0
                task['batch_total'] = 0
                task['batch_error_count'] = 0
                task['batch_status'] = 'completed'
                task['status'] = 'completed'
                task['batch_running'] = False
                task_service.save_task(Config.TASKS_DIR, task_id, task)
                try:
                    pq.put_nowait(json.dumps({
                        'type': 'done',
                        'progress': 0,
                        'total': 0,
                        'summary': task.get('batch_summary', ''),
                        'error_count': 0,
                        'status': 'completed',
                    }))
                except queue.Full:
                    pass
                progress_queues.pop(task_id, None)
                return

            def analyze_one(img):
                idx = str(img['index'])
                logger.info(f"批量分析 [{task_id}] #{idx}/{total}: {img['filename']}")
                try:
                    result = analyze_image_with_ai(img['filepath'], img.get('context', ''))
                except Exception as e:
                    logger.error(f"图片 #{idx} 分析异常: {e}", exc_info=True)
                    result = {
                        'image_type': img.get('guessed_category', '其他'),
                        'summary': f'分析失败: {str(e)[:200]}',
                        'evaluation': '分析异常，请重试',
                        'has_drawing': False,
                        'drawing_name': '',
                        'elements': {},
                        'construction_schedule': {'has_schedule': False},
                        'dimensions_specs': {'found': False},
                        '_error': str(e),
                    }
                with progress_lock:
                    task['batch_results'][idx] = result
                    task['batch_progress'] = task.get('batch_progress', 0) + 1
                    task_service.save_results(Config.TASKS_DIR, task_id, {idx: result})
                    try:
                        pq.put_nowait(json.dumps({
                            'type': 'progress',
                            'idx': idx,
                            'progress': task['batch_progress'],
                            'total': total,
                            'result': result,
                        }))
                    except queue.Full:
                        pass
                img_type = result.get('image_type', '?')
                summary_preview = (result.get('summary', '') or '')[:40]
                eval_preview = (result.get('evaluation', '') or '')[:30]
                logger.info(f"  完成 #{idx}: 类型={img_type} 摘要={summary_preview}... 评估={eval_preview}...")
                return result

            api_key_count = len(Config.SILICONFLOW_API_KEY_LIST) if Config.SILICONFLOW_API_KEY_LIST else 1
            model_count = len(Config.SILICONFLOW_VISION_MODELS) if Config.SILICONFLOW_VISION_MODELS else 1
            max_workers = min(max(api_key_count * model_count, 4), max(total, 1))
            logger.info(f"批量分析 [{task_id}] 并发数={max_workers} (Keys={api_key_count} Models={model_count})")

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(analyze_one, img): img for img in pending_images}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        error_count += 1
                        logger.error(f"线程执行异常: {e}", exc_info=True)

            task['batch_error_count'] = error_count
            task['batch_status'] = 'summarizing'
            task_service.save_task(Config.TASKS_DIR, task_id, task)
            try:
                pq.put_nowait(json.dumps({'type': 'summarizing', 'progress': task['batch_progress'], 'total': total}))
            except queue.Full:
                pass

            task['batch_results'] = dict(sorted(task['batch_results'].items(), key=lambda x: int(x[0])))
            task_service.save_results(Config.TASKS_DIR, task_id, task['batch_results'])

            full_total = task['total_images']
            summary = None
            try:
                summary = generate_summary(task['batch_results'])
            except Exception as e:
                logger.error(f"摘要生成失败 [{task_id}]: {e}", exc_info=True)
                summary = f"汇总生成失败: {str(e)}\n\n已完成 {len(task['batch_results'])}/{full_total} 张图片分析。"
            task['batch_summary'] = summary
            task_service.save_summary(Config.TASKS_DIR, task_id, summary)

            try:
                task_service.generate_analysis_report(Config.TASKS_DIR, task_id)
            except Exception as e:
                logger.error(f"报告生成失败 [{task_id}]: {e}", exc_info=True)

            task['batch_progress'] = total
            task['status'] = 'completed'
            task['batch_running'] = False
            task_service.save_task(Config.TASKS_DIR, task_id, task)
            logger.info(f"批量分析完成 [{task_id}] (完成{len(task['batch_results'])}/{full_total}张, 本次处理{total}张, 异常{error_count}张)")
            try:
                pq.put_nowait(json.dumps({
                    'type': 'done',
                    'progress': total,
                    'total': total,
                    'summary': summary,
                    'error_count': error_count,
                    'status': 'completed',
                }))
            except queue.Full:
                pass

        except Exception as e:
            logger.error(f"批量分析崩溃 [{task_id}]: {str(e)}", exc_info=True)
            task['batch_running'] = False
            task['batch_error'] = str(e)
            task['status'] = 'error'
            task_service.save_task(Config.TASKS_DIR, task_id, task)
            try:
                pq.put_nowait(json.dumps({'type': 'error', 'error': str(e)}))
            except queue.Full:
                pass
        finally:
            progress_queues.pop(task_id, None)

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
        'batch_error_count': task.get('batch_error_count', 0),
        'results': task.get('batch_results', task.get('results', {})),
    })


@docx_bp.route('/status/<task_id>/stream', methods=['GET'])
def get_status_stream(task_id):
    if task_id not in analysis_tasks:
        return jsonify({'success': False, 'error': '任务不存在'})

    def event_stream():
        pq = progress_queues.get(task_id)
        if not pq:
            task = analysis_tasks.get(task_id)
            if task:
                yield f"data: {json.dumps({'type': 'snapshot', 'progress': task.get('batch_progress', 0), 'total': task.get('total_images', 0), 'results': task.get('batch_results', task.get('results', {})), 'batch_running': task.get('batch_running', False), 'batch_summary': task.get('batch_summary', ''), 'batch_error_count': task.get('batch_error_count', 0), 'status': task.get('status', 'unknown')})}\n\n"
            yield "data: {\"type\":\"done\",\"reason\":\"no_queue\"}\n\n"
            return

        while True:
            try:
                msg = pq.get(timeout=30)
                yield f"data: {msg}\n\n"
                data = json.loads(msg)
                if data.get('type') in ('done', 'error'):
                    break
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"

    return Response(
        stream_with_context(event_stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


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


def _safe_str(val, max_len=None):
    """Normalize AI result value to string, handling dict/list/string types."""
    if isinstance(val, dict):
        # Extract overall rating and key points from dict-style evaluation
        grade = val.get('总体评价等级') or val.get('总体评价') or ''
        if not grade:
            for v in val.values():
                if isinstance(v, str) and any(g in v for g in ('优', '良', '中', '差')):
                    import re
                    m = re.search(r'[优良中差](?=\s|$|。|，|,)', v)
                    if m:
                        grade = m.group()
                        break
        parts = [f'{k}: {v}' for k, v in val.items()]
        result = '；'.join(parts)
        if grade and '总体评价' not in result:
            result += f'；总体评价：{grade}'
        return result[:max_len] if max_len else result
    if isinstance(val, list):
        result = '；'.join(str(v) for v in val)
        return result[:max_len] if max_len else result
    if not isinstance(val, str):
        val = str(val)
    return val[:max_len] if max_len else val


def _extract_grade(evaluation):
    """Extract overall rating (优/良/中/差) from evaluation value."""
    text = _safe_str(evaluation)
    import re
    for pattern in [r'总体评价[等级]*[：:]\s*([优良中差])', r'总体评价[等级]*[：:]\s*(\S+)',
                    r'[（(]([优良中差])[）)]', r'([优良中差])\s*$', r'评级[：:]\s*([优良中差])']:
        m = re.search(pattern, text)
        if m:
            g = m.group(1)
            if g in ('优', '良', '中', '差'):
                return g
            if '优' in g:
                return '优'
            if '良' in g:
                return '良'
            if '差' in g:
                return '差'
    if '优' in text:
        return '优'
    if '良' in text:
        return '良'
    if '差' in text:
        return '差'
    return '中'


def generate_summary(all_results):
    """Generate summary report. Always uses data-driven base (no hallucination),
    optionally appends LLM insights if API call succeeds."""
    import requests
    from collections import Counter

    total = len(all_results)
    if total == 0:
        return "暂无分析结果，无法生成汇总报告。"

    type_counts = Counter()
    grade_counts = Counter()
    content_lines = []
    key_findings = []

    for idx, r in sorted(all_results.items(), key=lambda x: int(x[0])):
        img_type = r.get('image_type', '未知')
        type_counts[img_type] += 1

        summary = _safe_str(r.get('summary', '无'), 150)
        evaluation = r.get('evaluation', '')
        grade = _extract_grade(evaluation)
        grade_counts[grade] += 1

        error_tag = ' [分析异常]' if r.get('_error') else ''
        content_lines.append(
            f"图片{idx}: 类型[{img_type}] 评级[{grade}]{error_tag}\n"
            f"  摘要: {summary}\n"
            f"  评估: {_safe_str(evaluation, 120)}"
        )

        # Collect notable findings
        dims = r.get('dimensions_specs', {})
        if isinstance(dims, dict) and dims.get('found') and dims.get('items'):
            for item in dims['items']:
                name = item.get('name', '')
                dim = item.get('dimension', '')
                qty = item.get('quantity', '')
                detail = f"{name}: {dim}" if dim else name
                if qty:
                    detail += f" ({qty})"
                key_findings.append(f"- 图片{idx}[{img_type}]: {detail}")

        schedule = r.get('construction_schedule', {})
        if isinstance(schedule, dict) and schedule.get('has_schedule'):
            start = schedule.get('start_date', '')
            end = schedule.get('end_date', '')
            if start or end:
                key_findings.append(f"- 图片{idx}[{img_type}]: 工期 {start} ~ {end}")

    # Always build data-driven report first (guaranteed accurate)
    base_report = _build_fallback_summary(all_results, type_counts, grade_counts)

    # Append key findings section
    if key_findings:
        base_report += "\n\n### 六、关键施工参数汇总\n"
        base_report += '\n'.join(key_findings[:30])  # limit to avoid bloat
        base_report += '\n'

    # Try LLM for additional insights
    api_keys = Config.SILICONFLOW_API_KEY_LIST
    summary_model = os.environ.get('SILICONFLOW_SUMMARY_MODEL', '')

    if not summary_model or not api_keys:
        return base_report

    text = '\n\n'.join(content_lines)
    type_lines = '\n'.join(f"  - {t}: {c} 张" for t, c in type_counts.most_common())
    grade_lines = ', '.join(f'{g}{c}张' for g, c in grade_counts.most_common())

    prompt = f"""请对以下施工方案图纸分析结果进行综合评审。

图纸总数：{total} 张
类型分布：{type_lines}
评级分布：{grade_lines}

各图分析：
{text}

请用3-5句话总结：这套图纸的整体质量水平、最突出的亮点、最需要关注的问题。直接给结论，不要用JSON。"""

    api_key = random.choice(api_keys)
    try:
        resp = requests.post(
            Config.SILICONFLOW_API_URL,
            json={
                "model": summary_model,
                "messages": [
                    {"role": "system", "content": "你是专业建筑工程图纸审查专家。请给出简短、具体、有洞察力的评审意见。"},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 600,
                "temperature": 0.3,
            },
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=60,
        )
        if resp.status_code == 200:
            llm_insight = resp.json()['choices'][0]['message']['content']
            if llm_insight and len(llm_insight) > 20:
                base_report += f"\n\n---\n### AI 综合评审意见\n\n{llm_insight}\n"
            return base_report
        logger.warning(f"汇总API返回 {resp.status_code}")
        return base_report
    except Exception as e:
        logger.warning(f"AI评审补充失败（报告数据部分不受影响）: {e}")
        return base_report


def _build_fallback_summary(all_results, type_counts=None, grade_counts=None):
    """Build summary from raw data when LLM is unavailable. Never crashes."""
    from collections import Counter
    try:
        total = len(all_results)

        if type_counts is None:
            type_counts = Counter()
            for r in all_results.values():
                type_counts[r.get('image_type', '未知')] += 1

        if grade_counts is None:
            grade_counts = Counter()
            for r in all_results.values():
                grade_counts[_extract_grade(r.get('evaluation', ''))] += 1

        error_count = sum(1 for r in all_results.values() if r.get('_error'))

        overall_grade = '良'
        if grade_counts.get('优', 0) >= total * 0.7:
            overall_grade = '优'
        elif grade_counts.get('差', 0) >= total * 0.3:
            overall_grade = '差'
        elif grade_counts.get('中', 0) + grade_counts.get('差', 0) >= total * 0.5:
            overall_grade = '中'

        lines = []
        lines.append("## 施工方案图纸质量综合评估报告\n")
        lines.append(f"> 生成方式：系统自动汇总 | 图纸总数：{total} 张 | 异常数：{error_count} 张\n")

        lines.append("### 一、总体概述\n")
        lines.append(f"本项目施工方案包含 **{total}** 张图纸，涵盖 **{len(type_counts)}** 种类型。")
        lines.append(f"整体质量评定：**{overall_grade}**。")
        lines.append("")

        lines.append("### 二、图纸类型分布\n")
        lines.append("| 类型 | 数量 |")
        lines.append("|------|------|")
        for t, c in type_counts.most_common():
            lines.append(f"| {t} | {c} |")
        lines.append("")

        lines.append("### 三、质量评级统计\n")
        grade_order = ['优', '良', '中', '差']
        lines.append("| 评级 | 数量 | 占比 |")
        lines.append("|------|------|------|")
        for g in grade_order:
            c = grade_counts.get(g, 0)
            if c > 0:
                pct = round(c / total * 100)
                lines.append(f"| {g} | {c} | {pct}% |")
        lines.append("")

        lines.append("### 四、各图片评估详情\n")
        for idx in sorted(all_results.keys(), key=lambda x: int(x)):
            r = all_results[idx]
            img_type = r.get('image_type', '未知')
            grade = _extract_grade(r.get('evaluation', ''))
            error_mark = ' ⚠️分析异常' if r.get('_error') else ''
            lines.append(f"**图片{idx}** [{img_type}] 评级：{grade}{error_mark}")
            summary = _safe_str(r.get('summary', ''), 200)
            if summary:
                lines.append(f"> {summary}")
            evaluation = _safe_str(r.get('evaluation', ''), 200)
            if evaluation:
                lines.append(f"评估：{evaluation}")
            lines.append("")

        lines.append("### 五、关键发现与建议\n")
        lines.append(f"- 共识别 **{len(type_counts)}** 种图纸类型，覆盖面{'较全' if len(type_counts) >= 8 else '一般'}。")
        lines.append(f"- 质量分布：{' | '.join(f'{g}级{c}张' for g, c in grade_counts.most_common())}。")

        if grade_counts.get('差', 0) > 0:
            lines.append(f"- ⚠️ **{grade_counts['差']} 张图纸评级为差**，建议重点复核并重新出图。")
        if grade_counts.get('中', 0) > 0:
            lines.append(f"- {grade_counts['中']} 张图纸评级为中，建议优化完善。")
        if error_count > 0:
            lines.append(f"- {error_count} 张图片AI分析异常，建议单独重新分析或人工审核。")

        lines.append("")
        lines.append("---")
        lines.append("*本报告由系统基于AI分析结果自动生成，评级仅供参考，最终审查意见以人工复核为准。*")

        return '\n'.join(lines)
    except Exception as e:
        logger.error(f"fallback汇总也失败了: {e}", exc_info=True)
        return f"汇总生成失败: {str(e)}\n\n已完成 {len(all_results)} 张图片分析，请查看各图片详情。"

