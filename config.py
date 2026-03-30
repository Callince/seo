import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv('.env')

class Config:
    # Basic Flask configuration
    SECRET_KEY = os.environ.get('SECRET_KEY', 'your-super-secret-production-key-change-this')

    # Cache configuration
    CACHE_TYPE = 'simple'
    CACHE_DEFAULT_TIMEOUT = 7200
    CACHE_KEY_PREFIX = 'seo_app_'

    # Redis configuration (for production)
    CACHE_REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
    CACHE_REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
    CACHE_REDIS_DB = int(os.environ.get('REDIS_DB', 0))
    CACHE_REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD')

    # Database configuration
    DB_USERNAME = os.environ.get('DB_USERNAME', 'flaskuser')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', 'MyStrongPassword123')
    DB_HOST = os.environ.get('DB_HOST', '127.0.0.1')
    DB_PORT = os.environ.get('DB_PORT', '5432')
    DB_NAME = os.environ.get('DB_NAME', 'flaskdb')

    SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_timeout': 20,
        'pool_recycle': 280,
        'pool_pre_ping': True,
        'pool_size': 10,
        'max_overflow': 20
    }

    # Mail configuration - SMTP Only
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True') == 'True'
    MAIL_USE_SSL = os.getenv('MAIL_USE_SSL', 'False') == 'True'

    # Support Mail
    MAIL_USERNAME = os.getenv('MAIL_SUPPORT_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_SUPPORT_PASSWORD')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_SUPPORT_SENDER')

    # Payment Mail (separate)
    MAIL_PAYMENT_USERNAME = os.getenv('MAIL_PAYMENT_USERNAME')
    MAIL_PAYMENT_PASSWORD = os.getenv('MAIL_PAYMENT_PASSWORD')
    MAIL_PAYMENT_SENDER = os.getenv('MAIL_PAYMENT_SENDER')

    # Gmail API - DISABLED (using SMTP only)
    USE_GMAIL_API = False

    # Razorpay credentials
    RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID', 'rzp_live_RcO4xIW6L4A8Kh')
    RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', 'pnOmfnCRpG9rP1JXe6dBlGWV')

    # CSRF Configuration
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 43200
    WTF_CSRF_SSL_STRICT = False  # Keep False even with HTTPS to avoid strict referrer checks

    # ⭐ SESSION CONFIGURATION - OPTIMIZED FOR AWS/NGINX WITH HTTPS ⭐
    SESSION_TYPE = 'filesystem'  # Use filesystem sessions for better persistence
    SESSION_PERMANENT = False  # Don't make sessions permanent by default
    SESSION_USE_SIGNER = True  # Sign session cookies for security
    SESSION_KEY_PREFIX = 'seodada:'  # Prefix for session keys
    SESSION_COOKIE_NAME = 'seodada_session'  # Custom session cookie name
    SESSION_COOKIE_SECURE = True  # True for HTTPS (you have SSL)
    SESSION_COOKIE_HTTPONLY = True
    # IMPORTANT: Use None for nginx proxy to avoid POST redirect issues
    # With 'Lax', cookies may not be sent after POST → redirect with nginx
    SESSION_COOKIE_SAMESITE = None  # None allows cookie in redirects (best for nginx)
    SESSION_COOKIE_PATH = '/'  # Ensure cookie is available for all paths
    SESSION_COOKIE_DOMAIN = None  # Let Flask handle domain automatically
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)

    # Cleanup job configuration
    CRAWL_DATA_RETENTION_DAYS = 7
    CRAWL_MEMORY_CLEANUP_HOURS = 1
    DAILY_CLEANUP_HOUR = 2

    # Cron secret
    CRON_SECRET = os.environ.get('CRON_SECRET', 'change-this-secret-key')
    # Site URL for generating links outside request context (e.g., scheduled emails)
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
    # ✅ CONFIGURED FOR HTTPS (you have SSL certificate)
    SESSION_COOKIE_SECURE = True  # True for HTTPS
    WTF_CSRF_SSL_STRICT = False   # Keep False to avoid strict referrer issues with nginx
    CACHE_TYPE = 'redis'
    CACHE_REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
