import os
import sys
import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import create_app
from extensions import db as _db
from models import (
    User, Admin, Subscription, SubscribedUser, Payment, InvoiceAddress,
    SubscriptionHistory, SearchHistory, TokenPurchase, UserToken, UsageLog,
    EmailLog, ContactSubmission, WebsiteSettings, BlogCategory, Blog, WebStory
)


class TestConfig:
    """Test configuration using the real local database."""
    TESTING = True
    SECRET_KEY = 'test-secret-key'
    WTF_CSRF_ENABLED = False  # Disable CSRF for testing
    SESSION_COOKIE_SECURE = False
    SERVER_NAME = 'localhost'

    # Use database from environment (.env file)
    DB_USERNAME = os.environ.get('DB_USERNAME', 'doadmin')
    DB_PASSWORD = os.environ.get('DB_PASSWORD')
    DB_HOST = os.environ.get('DB_HOST', '127.0.0.1')
    DB_PORT = os.environ.get('DB_PORT', '25060')
    DB_NAME = os.environ.get('DB_NAME', 'defaultdb')
    DB_SSLMODE = os.environ.get('DB_SSLMODE', 'require')
    _db_uri = f"postgresql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    if DB_SSLMODE:
        _db_uri += f"?sslmode={DB_SSLMODE}"
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', _db_uri)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_timeout': 20,
        'pool_recycle': 280,
        'pool_pre_ping': True,
        'pool_size': 5,
        'max_overflow': 10
    }

    # Mail - disable sending
    MAIL_SUPPRESS_SEND = True
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = 'test@test.com'
    MAIL_PASSWORD = 'test'
    MAIL_DEFAULT_SENDER = 'test@test.com'
    MAIL_PAYMENT_USERNAME = 'test@test.com'
    MAIL_PAYMENT_PASSWORD = 'test'
    MAIL_PAYMENT_SENDER = 'test@test.com'

    # Razorpay - test keys
    RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID', 'rzp_test_dummy')
    RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', 'dummy_secret')

    # reCAPTCHA - disabled for tests
    RECAPTCHA_SITE_KEY = 'test'
    RECAPTCHA_SECRET_KEY = 'test'

    # Session
    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    SESSION_KEY_PREFIX = 'test:'
    SESSION_COOKIE_NAME = 'test_session'

    # Cache
    CACHE_TYPE = 'simple'
    CACHE_DEFAULT_TIMEOUT = 300

    # Security
    CRON_SECRET = 'test-cron-secret'
    SUPER_ADMIN_PASSWORD = 'TestAdmin@123'
    SITE_URL = 'http://localhost'


@pytest.fixture(scope='session')
def app():
    """Create application for testing."""
    application = create_app(TestConfig)
    yield application


@pytest.fixture(scope='function')
def client(app):
    """Create a test client for each test."""
    with app.test_client() as client:
        yield client


@pytest.fixture(scope='function')
def app_context(app):
    """Push an app context for each test."""
    with app.app_context():
        yield app


@pytest.fixture(scope='function')
def logged_in_client(app, client):
    """Client with a logged-in regular user session."""
    with app.app_context():
        user = User.query.filter_by(email_confirmed=True).first()
        if not user:
            pytest.skip("No confirmed user in database")
        with client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['user_name'] = user.name
        # Also login via Flask-Login
        client.post('/login', data={
            'companyEmail': user.company_email,
            'password': 'Test@12345'  # May not work for all users
        }, follow_redirects=True)
        yield client, user


@pytest.fixture(scope='function')
def admin_client(app, client):
    """Client with an admin session."""
    with app.app_context():
        admin = Admin.query.filter_by(is_active=True).first()
        if not admin:
            pytest.skip("No active admin in database")
        with client.session_transaction() as sess:
            sess['admin_id'] = admin.id
            sess['email_id'] = admin.email_id
            sess['admin_name'] = admin.NAME
            sess['admin_role'] = admin.role
        yield client, admin


@pytest.fixture(scope='function')
def user_session_client(app, client):
    """Client with user_id in session (without needing real password)."""
    with app.app_context():
        user = User.query.filter_by(email_confirmed=True).first()
        if not user:
            pytest.skip("No confirmed user in database")
        with client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['user_name'] = user.name
        yield client, user
