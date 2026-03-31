import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv('.env')


class Config:
    # Basic Flask configuration
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-this-in-production')

    # Cache configuration
    CACHE_TYPE = 'simple'
    CACHE_DEFAULT_TIMEOUT = 7200
    CACHE_KEY_PREFIX = 'seo_app_'

    # Redis configuration
    CACHE_REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
    CACHE_REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
    CACHE_REDIS_DB = int(os.environ.get('REDIS_DB', 0))
    CACHE_REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD') or None

    # Database configuration
    # DigitalOcean App Platform injects DATABASE_URL automatically.
    # Falls back to individual DB_* env vars for local development.
    _database_url = os.environ.get('DATABASE_URL')
    if _database_url:
        # DO may provide postgres:// but SQLAlchemy 2.x requires postgresql://
        if _database_url.startswith('postgres://'):
            _database_url = _database_url.replace('postgres://', 'postgresql://', 1)
        SQLALCHEMY_DATABASE_URI = _database_url
    else:
        DB_USERNAME = os.environ.get('DB_USERNAME')
        DB_PASSWORD = os.environ.get('DB_PASSWORD')
        DB_HOST = os.environ.get('DB_HOST', '127.0.0.1')
        DB_PORT = os.environ.get('DB_PORT', '5432')
        DB_NAME = os.environ.get('DB_NAME')
        DB_SSLMODE = os.environ.get('DB_SSLMODE', '')

        _db_uri = (
            f"postgresql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
            if DB_USERNAME and DB_PASSWORD and DB_NAME
            else None
        )
        if _db_uri and DB_SSLMODE:
            _db_uri += f"?sslmode={DB_SSLMODE}"

        SQLALCHEMY_DATABASE_URI = _db_uri
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_timeout': 20,
        'pool_recycle': 280,
        'pool_pre_ping': True,
        'pool_size': 10,
        'max_overflow': 20
    }

    # Mail configuration - SMTP Only
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False') == 'True'

    # Support Mail
    MAIL_USERNAME = os.environ.get('MAIL_SUPPORT_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_SUPPORT_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_SUPPORT_SENDER')

    # Payment Mail (separate)
    MAIL_PAYMENT_USERNAME = os.environ.get('MAIL_PAYMENT_USERNAME')
    MAIL_PAYMENT_PASSWORD = os.environ.get('MAIL_PAYMENT_PASSWORD')
    MAIL_PAYMENT_SENDER = os.environ.get('MAIL_PAYMENT_SENDER')

    # Gmail API - DISABLED
    USE_GMAIL_API = False

    # Razorpay credentials - from .env only, NO hardcoded keys
    RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID')
    RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET')
    RAZORPAY_WEBHOOK_SECRET = os.environ.get('RAZORPAY_WEBHOOK_SECRET')

    # reCAPTCHA
    RECAPTCHA_SITE_KEY = os.environ.get('RECAPTCHA_SITE_KEY')
    RECAPTCHA_SECRET_KEY = os.environ.get('RECAPTCHA_SECRET_KEY')

    # CSRF Configuration
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 43200
    WTF_CSRF_SSL_STRICT = False

    # Session configuration
    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    SESSION_KEY_PREFIX = 'seodada:'
    SESSION_COOKIE_NAME = 'seodada_session'
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = None
    SESSION_COOKIE_PATH = '/'
    SESSION_COOKIE_DOMAIN = None
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)

    # Cleanup job configuration
    CRAWL_DATA_RETENTION_DAYS = 7
    CRAWL_MEMORY_CLEANUP_HOURS = 1
    DAILY_CLEANUP_HOUR = 2

    # Security
    CRON_SECRET = os.environ.get('CRON_SECRET')
    SUPER_ADMIN_PASSWORD = os.environ.get('SUPER_ADMIN_PASSWORD')
    SITE_URL = os.environ.get('SITE_URL', 'https://seodada.com')


class DevelopmentConfig(Config):
    DEBUG = True
    WTF_CSRF_SSL_STRICT = False
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = True


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    WTF_CSRF_ENABLED = True
    SESSION_COOKIE_SECURE = True
    WTF_CSRF_SSL_STRICT = False

    # Redis caching - use REDIS_URL if available (DigitalOcean managed Redis)
    _redis_url = os.environ.get('REDIS_URL')
    if _redis_url:
        CACHE_TYPE = 'redis'
        CACHE_REDIS_URL = _redis_url
    else:
        CACHE_TYPE = 'simple'
