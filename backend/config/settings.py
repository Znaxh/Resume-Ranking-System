import os
from dotenv import load_dotenv

import app_config

load_dotenv()

class Config:
    # Flask Settings
    SECRET_KEY = os.getenv('SECRET_KEY')
    if not SECRET_KEY:
        import warnings
        warnings.warn("SECRET_KEY not set — using random fallback (sessions will not persist across restarts)")
        import secrets
        SECRET_KEY = secrets.token_hex(32)
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
    RATELIMIT_ENABLED = os.getenv('RATELIMIT_ENABLED', 'true').lower() in ('1', 'true', 'yes')
    
    # File Upload Settings (aligned with app_config)
    MAX_CONTENT_LENGTH = app_config.MAX_CONTENT_LENGTH_BYTES
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')
    ALLOWED_EXTENSIONS = set(app_config.ALLOWED_EXTENSIONS)
    MAX_FILES_PER_REQUEST = app_config.MAX_FILES_PER_REQUEST
    
    # Model Settings
    MODEL_CACHE_DIR = os.getenv('MODEL_CACHE_DIR', 'models_cache')
    DEVICE = 'cuda' if os.getenv('USE_GPU', 'False').lower() == 'true' else 'cpu'
    
    # Algorithm Settings
    DEFAULT_ALGORITHMS = ['bert', 'cosine', 'ner']
    ALGORITHM_TIMEOUT = 300  # 5 minutes
    BATCH_SIZE = 32
    
    # Redis Settings (Flask-Caching under /v2/api paths)
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    CACHE_TYPE = 'RedisCache'
    CACHE_REDIS_URL = REDIS_URL
    CACHE_DEFAULT_TIMEOUT = 3600
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'app.log')

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False
    
class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False

config_dict = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
