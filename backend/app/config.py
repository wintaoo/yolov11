import os
import logging

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
MODEL_DIR = os.path.join(BASE_DIR, 'models')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev'
    DEBUG = True

    BASE_DIR = BASE_DIR
    ROOT_DIR = os.path.dirname(BASE_DIR)
    MODEL_DIR = MODEL_DIR
    MODEL_PATH = os.path.join(MODEL_DIR, 'best.pt')

    UPLOAD_FOLDER = UPLOAD_FOLDER
    DOCX_IMAGE_DIR = os.path.join(BASE_DIR, 'docx_images')
    LOG_FILE = os.path.join(BASE_DIR, 'logs', 'app.log')

    API_PREFIX = '/api'
    MAX_CONTENT_LENGTH = 200 * 1024 * 1024

    SILICONFLOW_API_KEY = os.environ.get('SILICONFLOW_API_KEY') or 'sk-ryoqxzjolunrurqpdxghyqdkfdlmstexhhotlkofwzhbxjjs'
    SILICONFLOW_API_URL = os.environ.get('SILICONFLOW_API_URL') or 'https://api.siliconflow.cn/v1/chat/completions'
    SILICONFLOW_VISION_MODEL = 'zai-org/GLM-4.6V'

    LOG_LEVEL = logging.INFO
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    @staticmethod
    def init_app(app):
        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(Config.DOCX_IMAGE_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(Config.LOG_FILE), exist_ok=True)

        if not os.path.exists('logs'):
            os.makedirs('logs')

        app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER
        app.config['MAX_CONTENT_LENGTH'] = Config.MAX_CONTENT_LENGTH
