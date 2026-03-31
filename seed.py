"""
Database Seed Script for DigitalOcean Deployment
-------------------------------------------------
Creates all tables and seeds initial data (super admin, default subscriptions).

Usage:
    python seed.py              # Create tables + seed data
    python seed.py --tables     # Only create tables (no seed data)
    python seed.py --seed       # Only seed data (tables must exist)
    python seed.py --reset      # Drop all tables and recreate (DESTRUCTIVE)
"""

import sys
import os
import logging
from datetime import datetime, timezone

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv('.env')

from app import create_app
from extensions import db
from models import (
    User, Admin, Subscription, SubscribedUser, Payment, InvoiceAddress,
    SubscriptionHistory, SearchHistory, TokenPurchase, UserToken, UsageLog,
    EmailLog, ContactSubmission, WebsiteSettings, BlogCategory, Blog, WebStory
)

UTC = timezone.utc

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ================================
# Default Subscription Plans
# ================================
DEFAULT_SUBSCRIPTIONS = [
    {
        'plan': 'Basic',
        'price': 499.0,
        'days': 30,
        'usage_per_day': 5,
        'tier': 1,
        'features': 'Basic SEO Tools,5 Searches/Day,Email Support',
        'is_active': True,
    },
    {
        'plan': 'Standard',
        'price': 999.0,
        'days': 30,
        'usage_per_day': 15,
        'tier': 2,
        'features': 'All Basic Features,15 Searches/Day,Priority Support,Advanced Reports',
        'is_active': True,
    },
    {
        'plan': 'Premium',
        'price': 1999.0,
        'days': 30,
        'usage_per_day': 50,
        'tier': 3,
        'features': 'All Standard Features,50 Searches/Day,Dedicated Support,API Access,Custom Reports',
        'is_active': True,
    },
]


def create_tables(app):
    """Create all database tables."""
    with app.app_context():
        logger.info("Creating database tables...")
        db.create_all()
        logger.info("All tables created successfully.")

        # List created tables
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(db.engine)
        tables = inspector.get_table_names()
        logger.info(f"Tables in database: {', '.join(tables)}")


def seed_super_admin(app):
    """Create the super admin account."""
    with app.app_context():
        super_admin_email = "manikandan@fourdm.com"
        existing = Admin.query.filter_by(email_id=super_admin_email).first()

        if existing:
            logger.info(f"Super admin already exists: {super_admin_email}")
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
            password = "ChangeThisPassword!123"
            logger.warning("SUPER_ADMIN_PASSWORD not set in .env! Using fallback password.")

        super_admin.set_password(password)

        db.session.add(super_admin)
        db.session.commit()
        logger.info(f"Super admin created: {super_admin_email}")


def seed_subscriptions(app):
    """Create default subscription plans."""
    with app.app_context():
        for plan_data in DEFAULT_SUBSCRIPTIONS:
            existing = Subscription.query.filter_by(plan=plan_data['plan']).first()
            if existing:
                logger.info(f"Subscription plan already exists: {plan_data['plan']}")
                continue

            subscription = Subscription(**plan_data)
            db.session.add(subscription)
            logger.info(f"Created subscription plan: {plan_data['plan']}")

        db.session.commit()
        logger.info("Subscription plans seeded successfully.")


def seed_default_settings(app):
    """Create default website settings."""
    with app.app_context():
        defaults = {
            'site_name': ('SEO Dada', 'Website name'),
            'site_tagline': ('Your SEO Partner', 'Website tagline'),
            'support_email': ('support@seodada.com', 'Support email address'),
            'trial_tokens': ('5', 'Number of free trial tokens for new users'),
        }

        for key, (value, description) in defaults.items():
            existing = WebsiteSettings.query.filter_by(setting_key=key).first()
            if existing:
                logger.info(f"Setting already exists: {key}")
                continue

            setting = WebsiteSettings(
                setting_key=key,
                setting_value=value,
                setting_type='text',
                description=description,
            )
            db.session.add(setting)
            logger.info(f"Created setting: {key} = {value}")

        db.session.commit()
        logger.info("Default settings seeded successfully.")


def reset_database(app):
    """Drop all tables and recreate them. DESTRUCTIVE!"""
    with app.app_context():
        logger.warning("DROPPING ALL TABLES...")
        db.drop_all()
        logger.info("All tables dropped.")
        db.create_all()
        logger.info("All tables recreated.")


def test_connection(app):
    """Test the database connection."""
    with app.app_context():
        try:
            from sqlalchemy import text
            db.session.execute(text('SELECT 1'))
            logger.info("Database connection successful!")
            return True
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            return False


def main():
    app = create_app()

    # Test connection first
    if not test_connection(app):
        logger.error("Cannot connect to database. Check your .env configuration.")
        sys.exit(1)

    args = sys.argv[1:]

    if '--reset' in args:
        confirm = input("WARNING: This will DELETE all data. Type 'yes' to confirm: ")
        if confirm.lower() != 'yes':
            logger.info("Reset cancelled.")
            return
        reset_database(app)
        seed_super_admin(app)
        seed_subscriptions(app)
        seed_default_settings(app)

    elif '--tables' in args:
        create_tables(app)

    elif '--seed' in args:
        seed_super_admin(app)
        seed_subscriptions(app)
        seed_default_settings(app)

    else:
        # Default: create tables + seed
        create_tables(app)
        seed_super_admin(app)
        seed_subscriptions(app)
        seed_default_settings(app)

    logger.info("Done!")


if __name__ == '__main__':
    main()
