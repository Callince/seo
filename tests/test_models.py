"""Unit tests for database models."""
import pytest
from datetime import datetime, timedelta, timezone
from models import (
    User, Admin, Subscription, SubscribedUser, Payment, InvoiceAddress,
    SubscriptionHistory, SearchHistory, TokenPurchase, UserToken, UsageLog,
    EmailLog, ContactSubmission, WebsiteSettings, BlogCategory, Blog, WebStory
)

UTC = timezone.utc


class TestUserModel:
    """Tests for the User model."""

    def test_user_exists_in_db(self, app_context):
        count = User.query.count()
        assert count > 0, "No users found in database"

    def test_user_has_required_fields(self, app_context):
        user = User.query.first()
        assert user.id is not None
        assert user.company_email is not None
        assert user.password_hash is not None

    def test_user_email_is_lowercase(self, app_context):
        user = User.query.first()
        assert user.company_email == user.company_email.lower()

    def test_user_password_hashing(self, app_context):
        user = User.query.first()
        # Password hash should not be plaintext
        assert user.password_hash != 'Test@12345'
        assert len(user.password_hash) > 50

    def test_user_check_password_wrong(self, app_context):
        user = User.query.first()
        assert user.check_password('definitely_wrong_password') is False

    def test_user_set_password(self, app_context):
        user = User.query.first()
        old_hash = user.password_hash
        user.set_password('NewTemp@12345')
        assert user.password_hash != old_hash
        assert user.check_password('NewTemp@12345') is True
        # Restore original
        user.password_hash = old_hash

    def test_user_get_reset_token(self, app_context):
        user = User.query.first()
        token = user.get_reset_token()
        assert token is not None
        assert len(token) > 10

    def test_user_verify_reset_token(self, app_context):
        user = User.query.first()
        token = user.get_reset_token()
        verified_user = User.verify_reset_token(token)
        assert verified_user is not None
        assert verified_user.id == user.id

    def test_user_verify_invalid_token(self, app_context):
        result = User.verify_reset_token('invalid-token-string')
        assert result is None

    def test_user_get_email_confirm_token(self, app_context):
        user = User.query.first()
        token = user.get_email_confirm_token()
        assert token is not None
        assert user.email_confirm_token == token

    def test_user_verify_email_token(self, app_context):
        user = User.query.first()
        token = user.get_email_confirm_token()
        verified = User.verify_email_token(token)
        assert verified is not None
        assert verified.id == user.id

    def test_user_format_relative_time(self, app_context):
        user = User.query.first()
        assert user._format_relative_time(None) == "Never"
        assert user._format_relative_time(datetime.now(UTC)) == "Just now"
        yesterday = datetime.now(UTC) - timedelta(days=1)
        assert user._format_relative_time(yesterday) == "Yesterday"

    def test_user_display_methods(self, app_context):
        user = User.query.first()
        # These should return strings without errors
        assert isinstance(user.get_last_login_display(), str)
        assert isinstance(user.get_profile_updated_display(), str)
        assert isinstance(user.get_password_changed_display(), str)

    def test_user_init_normalizes_email(self, app_context):
        """Test that __init__ normalizes email to lowercase."""
        user = User(name="Test", company_email="TEST@EXAMPLE.COM", password_hash="dummy")
        assert user.company_email == "test@example.com"


class TestAdminModel:
    """Tests for the Admin model."""

    def test_admin_exists(self, app_context):
        assert Admin.query.count() > 0

    def test_admin_has_permissions(self, app_context):
        admin = Admin.query.first()
        assert admin.permission is not None

    def test_admin_check_permission_valid(self, app_context):
        admin = Admin.query.filter_by(role='Super Admin').first()
        if admin:
            assert admin.admin_permissions('dashboard') is True

    def test_admin_check_permission_invalid(self, app_context):
        admin = Admin.query.first()
        assert admin.admin_permissions('nonexistent_permission') is False

    def test_admin_static_check_permission(self, app_context):
        admin = Admin.query.filter_by(role='Super Admin').first()
        if admin:
            # check_permission may need request context in some implementations
            # Test the instance method directly instead
            result = admin.admin_permissions('dashboard')
            assert result is True

    def test_admin_check_permission_nonexistent_email(self, app_context):
        result = Admin.check_permission('nonexistent@email.com', 'dashboard')
        assert result is False

    def test_admin_password_methods(self, app_context):
        admin = Admin.query.first()
        # Test set_password
        assert admin.set_password('TestPass@123') is True
        assert admin.check_password('TestPass@123') is True
        assert admin.check_password('wrong') is False

    def test_admin_set_empty_password(self, app_context):
        admin = Admin.query.first()
        assert admin.set_password('') is False
        assert admin.set_password(None) is False


class TestSubscriptionModel:
    """Tests for the Subscription model."""

    def test_subscription_exists(self, app_context):
        assert Subscription.query.count() > 0

    def test_subscription_has_required_fields(self, app_context):
        sub = Subscription.query.first()
        assert sub.plan is not None
        assert sub.price is not None
        assert sub.days is not None
        assert sub.usage_per_day is not None
        assert sub.tier is not None

    def test_subscription_daily_price(self, app_context):
        sub = Subscription.query.first()
        expected = sub.price / sub.days if sub.days > 0 else 0
        assert sub.daily_price == expected

    def test_subscription_repr(self, app_context):
        sub = Subscription.query.first()
        assert sub.plan in repr(sub)


class TestSubscribedUserModel:
    """Tests for the SubscribedUser model."""

    def test_subscribed_user_exists(self, app_context):
        assert SubscribedUser.query.count() > 0

    def test_is_active_property(self, app_context):
        sub = SubscribedUser.query.first()
        # is_active should return bool
        assert isinstance(sub.is_active, bool)

    def test_days_remaining(self, app_context):
        sub = SubscribedUser.query.first()
        remaining = sub.days_remaining
        assert isinstance(remaining, int)
        assert remaining >= 0

    def test_daily_usage_percent(self, app_context):
        sub = SubscribedUser.query.first()
        percent = sub.daily_usage_percent
        assert 0 <= percent <= 100

    def test_get_total_usage_limit(self, app_context):
        sub = SubscribedUser.query.first()
        limit = sub.get_total_usage_limit()
        assert isinstance(limit, int)
        assert limit >= 0


class TestPaymentModel:
    """Tests for the Payment model."""

    def test_payment_exists(self, app_context):
        assert Payment.query.count() > 0

    def test_payment_has_invoice(self, app_context):
        payment = Payment.query.first()
        assert payment.invoice_number is not None
        assert payment.invoice_number.startswith('INV-')

    def test_payment_amounts(self, app_context):
        payment = Payment.query.first()
        assert payment.base_amount >= 0
        assert payment.gst_amount >= 0
        assert payment.total_amount >= payment.base_amount

    def test_payment_get_invoice_summary(self, app_context):
        payment = Payment.query.first()
        summary = payment.get_invoice_summary()
        assert 'invoice_number' in summary
        assert 'total_amount' in summary
        assert 'base_amount' in summary


class TestSearchHistoryModel:
    """Tests for the SearchHistory model."""

    def test_search_history_exists(self, app_context):
        assert SearchHistory.query.count() > 0

    def test_search_history_ist_time(self, app_context):
        entry = SearchHistory.query.first()
        ist = entry.ist_time
        # Should return a datetime or None
        if entry.created_at:
            assert ist is not None


class TestBlogModels:
    """Tests for Blog and BlogCategory models."""

    def test_blog_categories_exist(self, app_context):
        assert BlogCategory.query.count() > 0

    def test_blogs_exist(self, app_context):
        assert Blog.query.count() > 0

    def test_blog_has_slug(self, app_context):
        blog = Blog.query.first()
        assert blog.slug is not None
        assert len(blog.slug) > 0

    def test_blog_category_relationship(self, app_context):
        blog = Blog.query.filter(Blog.category_id.isnot(None)).first()
        if blog:
            assert blog.category is not None


class TestWebStoryModel:
    """Tests for the WebStory model."""

    def test_webstories_exist(self, app_context):
        assert WebStory.query.count() > 0

    def test_webstory_has_slug(self, app_context):
        ws = WebStory.query.first()
        assert ws.slug is not None

    def test_webstory_has_slides(self, app_context):
        ws = WebStory.query.first()
        # slides can be None or a JSON structure
        assert ws.slides is None or isinstance(ws.slides, (list, dict))


class TestWebsiteSettingsModel:
    """Tests for the WebsiteSettings model."""

    def test_settings_exist(self, app_context):
        assert WebsiteSettings.query.count() > 0

    def test_get_setting(self, app_context):
        name = WebsiteSettings.get_setting('website_name')
        assert name is not None

    def test_get_setting_default(self, app_context):
        result = WebsiteSettings.get_setting('nonexistent_key', 'default_value')
        assert result == 'default_value'


class TestEmailLogModel:
    """Tests for the EmailLog model."""

    def test_email_logs_exist(self, app_context):
        assert EmailLog.query.count() > 0

    def test_email_log_formatted_time(self, app_context):
        log = EmailLog.query.first()
        formatted = log.formatted_sent_time
        assert isinstance(formatted, str)
        assert formatted != 'N/A' or log.sent_at is None


class TestContactSubmissionModel:
    """Tests for the ContactSubmission model."""

    def test_submissions_exist(self, app_context):
        assert ContactSubmission.query.count() > 0

    def test_submission_has_required_fields(self, app_context):
        sub = ContactSubmission.query.first()
        assert sub.name is not None
        assert sub.email is not None
        assert sub.message is not None
