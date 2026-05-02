import os
import json
import shutil
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

TASK_FILENAME = 'task.json'
RESULTS_FILENAME = 'results.json'
SUMMARY_FILENAME = 'summary.md'


def task_dir(tasks_root, task_id):
    return os.path.join(tasks_root, task_id)


def images_dir(tasks_root, task_id):
    return os.path.join(task_dir(tasks_root, task_id), 'images')


def save_task(tasks_root, task_id, task_data):
    d = task_dir(tasks_root, task_id)
    os.makedirs(d, exist_ok=True)
    saveable = {
        'task_id': task_id,
        'original_filename': task_data.get('original_filename', ''),
        'status': task_data.get('status', 'extracted'),
        'total_images': task_data.get('total_images', 0),
        'images': [{
            'index': img['index'],
            'filename': img['filename'],
            'context': img.get('context', ''),
            'guessed_category': img.get('guessed_category', '其他'),
        } for img in task_data.get('images', [])],
        'batch_summary': task_data.get('batch_summary', ''),
        'created_at': task_data.get('created_at', datetime.now().isoformat()),
        'updated_at': datetime.now().isoformat(),
    }
    filepath = os.path.join(d, TASK_FILENAME)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(saveable, f, ensure_ascii=False, indent=2)
    logger.info(f"任务已保存: {task_id}")


def load_task(tasks_root, task_id):
    filepath = os.path.join(task_dir(tasks_root, task_id), TASK_FILENAME)
    if not os.path.exists(filepath):
        return None
    with open(filepath, 'r', encoding='utf-8') as f:
        task_data = json.load(f)
    img_dir = images_dir(tasks_root, task_id)
    for img in task_data.get('images', []):
        img['filepath'] = os.path.join(img_dir, img['filename'])
    results = load_results(tasks_root, task_id)
    task_data['results'] = results
    task_data['output_dir'] = img_dir
    summary_path = os.path.join(task_dir(tasks_root, task_id), SUMMARY_FILENAME)
    if os.path.exists(summary_path):
        with open(summary_path, 'r', encoding='utf-8') as f:
            task_data['batch_summary'] = f.read()
    return task_data


def save_results(tasks_root, task_id, results):
    d = task_dir(tasks_root, task_id)
    os.makedirs(d, exist_ok=True)
    filepath = os.path.join(d, RESULTS_FILENAME)
    existing = {}
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                pass
    existing.update({str(k): v for k, v in results.items()})
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def load_results(tasks_root, task_id):
    filepath = os.path.join(task_dir(tasks_root, task_id), RESULTS_FILENAME)
    if not os.path.exists(filepath):
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_summary(tasks_root, task_id, summary):
    d = task_dir(tasks_root, task_id)
    os.makedirs(d, exist_ok=True)
    filepath = os.path.join(d, SUMMARY_FILENAME)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(summary)


def list_tasks(tasks_root):
    if not os.path.exists(tasks_root):
        return []
    tasks = []
    for name in os.listdir(tasks_root):
        d = os.path.join(tasks_root, name)
        if not os.path.isdir(d):
            continue
        filepath = os.path.join(d, TASK_FILENAME)
        if not os.path.exists(filepath):
            continue
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            result_count = len(load_results(tasks_root, name))
            has_summary = os.path.exists(os.path.join(d, SUMMARY_FILENAME))
            tasks.append({
                'task_id': name,
                'original_filename': meta.get('original_filename', '未知文档'),
                'total_images': meta.get('total_images', 0),
                'status': meta.get('status', 'extracted'),
                'result_count': result_count,
                'has_summary': has_summary,
                'created_at': meta.get('created_at', ''),
                'updated_at': meta.get('updated_at', ''),
            })
        except Exception as e:
            logger.warning(f"读取任务 {name} 失败: {e}")
    tasks.sort(key=lambda x: x['created_at'], reverse=True)
    return tasks


def delete_task(tasks_root, task_id):
    d = task_dir(tasks_root, task_id)
    if os.path.exists(d):
        shutil.rmtree(d)
        logger.info(f"任务已删除: {task_id}")
        return True
    return False
