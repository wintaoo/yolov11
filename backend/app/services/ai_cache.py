import os
import json
import hashlib
import logging

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cache_ai')


def _cache_path(image_path):
    h = hashlib.md5()
    with open(image_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f'{h.hexdigest()}.json')


def get(image_path):
    """Return cached AI result or None."""
    path = _cache_path(image_path)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.info(f"[缓存命中] {os.path.basename(image_path)}")
            return data
        except Exception:
            return None
    return None


def set(image_path, result):
    """Persist AI result to cache."""
    path = _cache_path(image_path)
    try:
        safe = dict(result)
        safe.pop('raw_content', None)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(safe, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[缓存写入失败] {image_path}: {e}")
