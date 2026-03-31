from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_caching import Cache
from flask_mail import Mail
from flask_login import LoginManager
from flask_session import Session
from flask_wtf.csrf import CSRFProtect
from concurrent.futures import ThreadPoolExecutor
import razorpay
import os

# Initialize extensions (without app binding)
db = SQLAlchemy()
migrate = Migrate()
cache = Cache()
mail = Mail()
login_manager = LoginManager()
csrf = CSRFProtect()
sess = Session()
executor = ThreadPoolExecutor(max_workers=5)

# Razorpay client (initialized in create_app)
razorpay_client = None


def init_extensions(app):
    """Initialize all Flask extensions with the app instance."""
    global razorpay_client

    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    csrf.init_app(app)

    # Login manager
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'You need to log in to access this page.'
    login_manager.login_message_category = 'info'

    # Session
    session_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flask_session')
    os.makedirs(session_dir, exist_ok=True)
    app.config['SESSION_FILE_DIR'] = session_dir
    sess.init_app(app)

    # Cache
    cache.init_app(app)

    # Razorpay
    razorpay_client = razorpay.Client(
        auth=(app.config['RAZORPAY_KEY_ID'], app.config['RAZORPAY_KEY_SECRET'])
    )

    # User loader for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        from models import User
        return db.session.get(User, int(user_id))
