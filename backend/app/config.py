import os
import logging
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
MODEL_DIR = os.path.join(BASE_DIR, 'models')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev'
    DEBUG = os.environ.get('DEBUG', 'true').lower() == 'true'

    BASE_DIR = BASE_DIR
    ROOT_DIR = os.path.dirname(BASE_DIR)
    MODEL_DIR = MODEL_DIR
    MODEL_PATH = os.path.join(MODEL_DIR, 'best.pt')

    UPLOAD_FOLDER = UPLOAD_FOLDER
    TASKS_DIR = os.path.join(BASE_DIR, 'tasks')
    PARSED_IMAGES_DIR = os.path.join(BASE_DIR, 'parsed_images')
    LOG_FILE = os.path.join(BASE_DIR, 'logs', 'app.log')

    API_PREFIX = '/api'
    MAX_CONTENT_LENGTH = 200 * 1024 * 1024

    SILICONFLOW_API_KEYS = os.environ.get('SILICONFLOW_API_KEYS', os.environ.get('SILICONFLOW_API_KEY', ''))
    SILICONFLOW_API_KEY_LIST = [k.strip() for k in SILICONFLOW_API_KEYS.split(',') if k.strip()]
    SILICONFLOW_API_URL = os.environ.get('SILICONFLOW_API_URL', 'https://api.siliconflow.cn/v1/chat/completions')
    SILICONFLOW_VISION_MODEL = os.environ.get('SILICONFLOW_VISION_MODEL', 'zai-org/GLM-4.6V')

    _extra_models = os.environ.get('SILICONFLOW_VISION_MODELS', '')
    _parsed_extra = [m.strip() for m in _extra_models.split(',') if m.strip()]
    SILICONFLOW_VISION_MODELS = [SILICONFLOW_VISION_MODEL] + _parsed_extra

    IMAGE_COMPRESSION_ENABLED = os.environ.get('IMAGE_COMPRESSION_ENABLED', 'true').lower() == 'true'
    IMAGE_MAX_DIMENSION = int(os.environ.get('IMAGE_MAX_DIMENSION', '2048'))
    IMAGE_JPEG_QUALITY = int(os.environ.get('IMAGE_JPEG_QUALITY', '85'))

    AI_CACHE_ENABLED = os.environ.get('AI_CACHE_ENABLED', 'true').lower() == 'true'
    CACHE_AI_DIR = os.path.join(BASE_DIR, 'cache_ai')

    LOG_LEVEL = logging.INFO
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    @staticmethod
    def init_app(app):
        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(Config.TASKS_DIR, exist_ok=True)
        os.makedirs(Config.PARSED_IMAGES_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(Config.LOG_FILE), exist_ok=True)

        if not os.path.exists('logs'):
            os.makedirs('logs')

        app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER
        app.config['MAX_CONTENT_LENGTH'] = Config.MAX_CONTENT_LENGTH
