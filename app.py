import os
import re
import json
import logging
import atexit
import traceback
from datetime import datetime, timezone

import pytz
from flask import Flask, request, redirect, url_for, flash, session, jsonify, render_template
from flask_wtf.csrf import CSRFError, generate_csrf
from markupsafe import Markup
from sqlalchemy import inspect, text

from config import Config, DevelopmentConfig, ProductionConfig
from extensions import db, init_extensions, csrf

UTC = timezone.utc


def create_app(config_class=None):
    """Application factory."""
    app = Flask(__name__)

    # Load config based on environment
    if config_class:
        app.config.from_object(config_class)
    elif os.environ.get('FLASK_ENV') == 'production':
        app.config.from_object(ProductionConfig)
    else:
        app.config.from_object(DevelopmentConfig)

    # Validate critical config
    if not app.config.get('SQLALCHEMY_DATABASE_URI'):
        raise RuntimeError(
            "Database not configured. Set DB_USERNAME, DB_PASSWORD, and DB_NAME in .env"
        )

    # Initialize extensions
    init_extensions(app)

    # Setup logging
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flask_app.log')
    logging.basicConfig(
        filename=log_path, level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Ensure directories exist
    os.makedirs("download_files", exist_ok=True)
    os.makedirs("crawled_data", exist_ok=True)

    # Register blueprints
    _register_blueprints(app)

    # Register error handlers
    _register_error_handlers(app)

    # Register template filters and context processors
    _register_template_helpers(app)

    # Register request hooks
    _register_request_hooks(app)

    # Database teardown handlers
    _register_teardown_handlers(app)

    # Initialize database and startup tasks
    with app.app_context():
        _initialize_database(app)

    # Setup scheduled tasks
    _setup_scheduler(app)

    app.logger.info("Application initialized successfully")
    return app


def _register_blueprints(app):
    """Register all application blueprints."""
    from blueprints.auth import auth_bp
    from blueprints.admin import admin_bp
    from blueprints.payment import payment_bp
    from blueprints.seo_tools import seo_tools_bp
    from blueprints.public import public_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(payment_bp)
    app.register_blueprint(seo_tools_bp)
    app.register_blueprint(public_bp)


def _register_error_handlers(app):
    """Register error handlers."""

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        app.logger.warning(
            f"CSRF Token Failed: Route: {request.endpoint}, "
            f"Method: {request.method}, IP: {request.remote_addr}"
        )
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'error': 'CSRF token missing or invalid',
                'message': 'Please refresh the page and try again'
            }), 400
        flash('Your session has expired. Please refresh the page and try again.', 'danger')
        if request.endpoint in ['auth.login', 'auth.signup']:
            return redirect(url_for(request.endpoint))
        return redirect(url_for('public.landing'))

    @app.errorhandler(500)
    def handle_internal_error(e):
        app.logger.error(f"Internal Server Error: {str(e)}")
        try:
            db.session.rollback()
        except Exception:
            pass

        is_ajax = (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
            request.headers.get('Accept', '').startswith('application/json') or
            request.content_type == 'application/json'
        )
        if is_ajax:
            return jsonify({'error': {'message': 'Internal server error.'}, 'success': False}), 500
        return render_template('errors/500.html'), 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        app.logger.error(f"Unhandled Exception: {str(e)}")
        try:
            db.session.rollback()
        except Exception:
            pass

        is_ajax = (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
            request.headers.get('Accept', '').startswith('application/json') or
            request.content_type == 'application/json'
        )
        if is_ajax:
            return jsonify({'error': {'message': 'An unexpected error occurred.'}, 'success': False}), 500
        return render_template('errors/500.html'), 500


def _register_template_helpers(app):
    """Register template filters and context processors."""

    @app.template_filter('highlight_keywords')
    def highlight_keywords(text, keywords_colors):
        if not keywords_colors:
            return Markup(text)
        highlighted = text
        sorted_keywords = sorted(keywords_colors.items(), key=lambda x: len(x[0]), reverse=True)
        for keyword, color in sorted_keywords:
            pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
            highlighted = pattern.sub(
                lambda m: f'<span style="background-color: {color}; color: white; font-weight: bold; '
                          f'padding: 2px 6px; border-radius: 4px; margin: 0 2px;">{m.group(0)}</span>',
                highlighted
            )
        return Markup(highlighted)

    @app.template_filter('from_json')
    def from_json(value):
        if value is None:
            return []
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []

    @app.template_filter('to_ist_time')
    def to_ist_time(dt):
        if dt is None:
            return "N/A"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        ist_timezone = pytz.timezone('Asia/Calcutta')
        ist_time = dt.astimezone(ist_timezone)
        return ist_time.strftime('%d %b %Y, %H:%M %p IST')

    @app.template_filter('urlparse')
    def urlparse_filter(url):
        from urllib.parse import urlparse
        return urlparse(url)

    @app.template_test('match')
    def match_test(value, pattern):
        return re.search(pattern, str(value)) is not None

    @app.template_filter('parse_json_features')
    def parse_json_features(features_str):
        if not features_str:
            return []
        features_str = features_str.strip()
        try:
            if features_str.startswith('{') and features_str.endswith('}'):
                features_dict = json.loads(features_str)
                return [(key, value) for key, value in features_dict.items()]
            else:
                return [(f.strip(), True) for f in features_str.split(',') if f.strip()]
        except (json.JSONDecodeError, AttributeError):
            try:
                return [(f.strip(), True) for f in features_str.split(',') if f.strip()]
            except Exception:
                return []

    @app.template_filter('format_feature_name')
    def format_feature_name(name):
        if not name:
            return ''
        name = str(name)
        if name.startswith('feature') and len(name) > 7 and name[-1].isdigit():
            match = re.match(r'feature(\d+)', name)
            if match:
                return f'Feature {match.group(1)}'
        name = name.replace('_', ' ')
        name = re.sub('([a-z])([A-Z])', r'\1 \2', name)
        return ' '.join(word.capitalize() for word in name.split()).strip()

    @app.template_filter('feature_icon')
    def feature_icon(value):
        if value is True or str(value).lower() == 'true':
            return 'fa-check-circle text-secondary'
        elif value is False or str(value).lower() == 'false':
            return 'fa-times-circle text-gray-400'
        else:
            return 'fa-check-circle text-secondary'

    @app.template_filter('format_feature')
    def format_feature(value):
        if isinstance(value, bool):
            return ''
        elif isinstance(value, (int, float)):
            return str(value)
        return str(value) if value else ''

    @app.context_processor
    def inject_csrf_token():
        return dict(csrf_token=generate_csrf(), generate_csrf=generate_csrf)

    @app.context_processor
    def inject_website_settings():
        try:
            from models import WebsiteSettings
            website_name = WebsiteSettings.get_setting('website_name', '')
            website_icon = WebsiteSettings.get_setting('website_icon', 'fas fa-chart-line')
            website_logo_file = WebsiteSettings.get_setting('website_logo_file')
            website_tagline = WebsiteSettings.get_setting('website_tagline', 'Professional SEO Dada Tools')

            if website_name is None:
                website_name = ''
            if not website_icon or not website_icon.strip():
                website_icon = 'fas fa-chart-line'
            if not website_tagline or not website_tagline.strip():
                website_tagline = 'Professional SEO Dada Tools'

            return dict(
                website_settings={
                    'website_name': website_name,
                    'website_icon': website_icon,
                    'website_logo_file': website_logo_file,
                    'website_tagline': website_tagline
                },
                current_year=datetime.now().year
            )
        except Exception as e:
            app.logger.error(f"Error loading website settings: {str(e)}")
            return dict(
                website_settings={
                    'website_name': '',
                    'website_icon': 'fas fa-chart-line',
                    'website_logo_file': None,
                    'website_tagline': ''
                },
                current_year=datetime.now().year
            )


def _register_request_hooks(app):
    """Register before/after request hooks."""

    # CSRF exempt routes
    CSRF_EXEMPT_ROUTES = [
        'seo_tools.url_search_ajax', 'seo_tools.record_search',
        'seo_tools.get_usage_history', 'seo_tools.progress', 'seo_tools.get_data',
        'seo_tools.time_and_date_today',
        'payment.user_subscriptions', 'payment.subscribe', 'payment.checkout',
        'payment.verify_payment', 'payment.cancel_subscription',
        'payment.change_subscription', 'payment.subscription_details',
        'payment.toggle_auto_renew', 'payment.download_invoice',
        'admin.admin_blog_categories', 'admin.admin_add_blog_category',
        'admin.admin_edit_blog_category', 'admin.admin_delete_blog_category',
        'admin.admin_blogs', 'admin.admin_blog_upload_image',
        'admin.admin_add_blog', 'admin.admin_edit_blog', 'admin.admin_delete_blog',
        'admin.admin_webstories', 'admin.admin_webstory_upload_image',
        'admin.admin_webstory_check_slug', 'admin.admin_add_webstory',
        'admin.admin_edit_webstory', 'admin.admin_delete_webstory',
        'public.public_blogs', 'public.blog_detail',
        'public.public_webstories', 'public.webstory_detail',
    ]

    @app.before_request
    def csrf_protect():
        if request.endpoint in CSRF_EXEMPT_ROUTES:
            return
        view_function = app.view_functions.get(request.endpoint)
        if view_function and getattr(view_function, '_csrf_exempt', False):
            return
        if request.method == 'GET' and request.endpoint in [
            'public.landing', 'public.about', 'public.privacy', 'public.terms'
        ]:
            return
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            token = request.headers.get('X-CSRFToken') or request.form.get('csrf_token')
            if not token:
                return jsonify({'error': 'CSRF token missing'}), 400

    @app.after_request
    def add_no_cache_headers(response):
        if request.endpoint in [
            'seo_tools.image_search', 'seo_tools.url_search',
            'seo_tools.h_search', 'seo_tools.keyword_search'
        ]:
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '-1'
        return response


def _register_teardown_handlers(app):
    """Register database teardown handlers."""

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        if exception:
            db.session.rollback()
        db.session.remove()

    @app.teardown_request
    def teardown_request(exception=None):
        if exception:
            try:
                db.session.rollback()
            except Exception:
                pass


def _initialize_database(app):
    """Initialize database tables and startup data."""
    from models import Admin, WebsiteSettings

    try:
        _update_database_tables(app)
        db.create_all()
        _create_super_admin(app)
        _normalize_existing_admin_emails(app)
        _fix_user_timestamps(app)
        _initialize_website_settings(app)

        try:
            from services.subscription import cleanup_duplicate_subscriptions
            count = cleanup_duplicate_subscriptions()
            if count > 0:
                app.logger.info(f"Cleaned up {count} duplicate subscriptions")
        except Exception as e:
            app.logger.error(f"Error cleaning up subscriptions: {str(e)}")

    except Exception as e:
        app.logger.error(f"Error during app initialization: {str(e)}")


def _update_database_tables(app):
    """Update existing database tables with new columns."""
    inspector = inspect(db.engine)

    table_updates = {
        'users': [
            ('last_login_at', 'DATETIME NULL'),
            ('profile_updated_at', 'DATETIME NULL'),
            ('password_changed_at', 'DATETIME NULL'),
        ],
        'user_tokens': [
            ('is_paused', 'BOOLEAN DEFAULT 0'),
            ('paused_at', 'DATETIME NULL'),
            ('original_subscription_id', 'INTEGER NULL'),
        ],
        'usage_logs': [
            ('is_trial', 'BOOLEAN DEFAULT FALSE'),
        ],
        'blogs': [
            ('title', 'VARCHAR(255) NOT NULL DEFAULT \'\''),
            ('slug', 'VARCHAR(255) NOT NULL DEFAULT \'\''),
            ('description', 'TEXT NULL'),
            ('meta_title', 'VARCHAR(255) NULL'),
            ('meta_keyword', 'TEXT NULL'),
            ('meta_description', 'TEXT NULL'),
            ('image', 'VARCHAR(255) NULL'),
            ('category_id', 'INTEGER NULL'),
            ('status', 'BOOLEAN DEFAULT 1'),
            ('schema_data', 'TEXT NULL'),
            ('created_by', 'VARCHAR(100) NULL'),
            ('created_at', 'DATETIME NULL'),
            ('updated_at', 'DATETIME NULL'),
        ],
        'webstories': [
            ('meta_title', 'VARCHAR(255) NOT NULL DEFAULT \'\''),
            ('meta_description', 'TEXT NULL'),
            ('slug', 'VARCHAR(255) NOT NULL DEFAULT \'\''),
            ('cover_image', 'VARCHAR(255) NULL'),
            ('publish_date', 'DATE NULL'),
            ('status', 'BOOLEAN DEFAULT 1'),
            ('slides', 'JSON NULL'),
            ('created_by', 'VARCHAR(100) NULL'),
            ('created_at', 'DATETIME NULL'),
            ('updated_at', 'DATETIME NULL'),
        ],
        'blog_categories': [
            ('name', 'VARCHAR(100) NOT NULL DEFAULT \'\''),
            ('sort_order', 'INTEGER DEFAULT 0'),
            ('status', 'BOOLEAN DEFAULT 1'),
            ('created_at', 'DATETIME NULL'),
            ('updated_at', 'DATETIME NULL'),
        ],
    }

    # Make subscription_id nullable in usage_logs
    if 'usage_logs' in inspector.get_table_names():
        try:
            db.session.execute(text("ALTER TABLE usage_logs ALTER COLUMN subscription_id DROP NOT NULL"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    for table_name, columns in table_updates.items():
        if table_name not in inspector.get_table_names():
            continue
        existing_columns = [col['name'] for col in inspector.get_columns(table_name)]
        for column_name, column_definition in columns:
            if column_name not in existing_columns:
                try:
                    db.session.execute(text(
                        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
                    ))
                    db.session.commit()
                    app.logger.info(f"Added column '{column_name}' to '{table_name}'")
                except Exception as e:
                    db.session.rollback()
                    app.logger.error(f"Error adding column '{column_name}' to '{table_name}': {str(e)}")


def _create_super_admin(app):
    """Create a super admin user if it doesn't already exist."""
    from models import Admin

    super_admin_email = "manikandan@fourdm.com"
    existing_admin = Admin.query.filter_by(email_id=super_admin_email).first()

    if existing_admin:
        return

    super_admin = Admin(
        email_id=super_admin_email,
        NAME="Super Admin",
        role="Super Admin",
        phone_number="8132156825",
        assigned_by="System",
        permission=[
            "dashboard", "manage_roles", "subscription_management",
            "subscribed_users_view", "user_management", "payments",
            "contact_submissions", "website_settings", "search_history",
            "email_logs", "blog_management", "blog_categories", "webstory_management"
        ],
        is_active=True,
        created_at=datetime.now(UTC)
    )

    password = app.config.get('SUPER_ADMIN_PASSWORD')
    if not password:
        app.logger.warning("SUPER_ADMIN_PASSWORD not set in .env! Using fallback.")
        password = "ChangeThisPassword!123"

    super_admin.set_password(password)

    try:
        db.session.add(super_admin)
        db.session.commit()
        app.logger.info(f"Super admin created: {super_admin_email}")
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating super admin: {str(e)}")


def _normalize_existing_admin_emails(app):
    """Normalize existing admin email addresses to lowercase."""
    from models import Admin
    try:
        admins = Admin.query.all()
        for admin in admins:
            if admin.email_id and admin.email_id != admin.email_id.lower():
                admin.email_id = admin.email_id.lower()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error normalizing admin emails: {str(e)}")


def _fix_user_timestamps(app):
    """Fix user timestamps that may be null."""
    from models import User
    try:
        users_without_login = User.query.filter(User.last_login_at.is_(None)).all()
        for user in users_without_login:
            if user.created_at:
                user.last_login_at = user.created_at
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error fixing user timestamps: {str(e)}")


def _initialize_website_settings(app):
    """Initialize default website settings."""
    from models import WebsiteSettings
    try:
        defaults = [
            ('website_name', 'SEO Dada'),
            ('website_icon', 'fas fa-chart-line'),
            ('website_tagline', 'Professional SEO Dada Tools'),
            ('website_logo_file', None)
        ]
        for key, default_value in defaults:
            existing = WebsiteSettings.query.filter_by(setting_key=key).first()
            if not existing:
                setting = WebsiteSettings(
                    setting_key=key,
                    setting_value=default_value,
                    description=f'Default {key.replace("_", " ").title()}'
                )
                db.session.add(setting)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error initializing website settings: {str(e)}")


def _setup_scheduler(app):
    """Set up background schedulers for cleanup and notifications."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from pytz import utc

        scheduler = BackgroundScheduler(timezone=utc)

        def run_cleanup():
            with app.app_context():
                from services.subscription import cleanup_old_crawl_data, cleanup_crawl_status_memory
                try:
                    cleanup_old_crawl_data(days_to_keep=7)
                except Exception as e:
                    app.logger.error(f"Cleanup error: {str(e)}")

        def run_memory_cleanup():
            with app.app_context():
                from services.subscription import cleanup_crawl_status_memory
                try:
                    cleanup_crawl_status_memory()
                except Exception as e:
                    app.logger.error(f"Memory cleanup error: {str(e)}")

        def run_expiry_check():
            with app.app_context():
                try:
                    from services.email import check_and_notify_expiring_subscriptions
                    count = check_and_notify_expiring_subscriptions()
                    app.logger.info(f"Expiry check: {count} notifications sent")
                except Exception as e:
                    app.logger.error(f"Expiry check error: {str(e)}")

        scheduler.add_job(run_cleanup, trigger="cron", hour=2, minute=0,
                          id='daily_crawl_cleanup', max_instances=1, coalesce=True)
        scheduler.add_job(run_memory_cleanup, trigger="cron", minute=0,
                          id='hourly_memory_cleanup', max_instances=1, coalesce=True)
        scheduler.add_job(run_expiry_check, trigger="cron", hour=9, minute=0,
                          id='daily_expiry_check', max_instances=1, coalesce=True)

        scheduler.start()
        atexit.register(lambda: scheduler.shutdown())

        app.logger.info("Scheduler started: cleanup@2AM, memory@hourly, expiry@9AM UTC")

    except Exception as e:
        app.logger.error(f"Error setting up scheduler: {str(e)}")


# Create the application
application = create_app()

if __name__ == "__main__":
    if os.environ.get('FLASK_ENV') != 'production':
        application.run(debug=True, host='0.0.0.0', port=5050)
    else:
        print("Use a WSGI server like Gunicorn for production")
