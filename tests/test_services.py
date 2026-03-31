"""Unit tests for service modules."""
import pytest
from models import User, SubscribedUser, Subscription, SearchHistory


class TestSubscriptionService:
    """Tests for services/subscription.py functions."""

    def test_has_active_subscription(self, app_context):
        from services.subscription import has_active_subscription
        # Test with a user that may or may not have subscription
        user = User.query.first()
        result = has_active_subscription(user.id)
        assert isinstance(result, bool)

    def test_has_active_subscription_nonexistent_user(self, app_context):
        from services.subscription import has_active_subscription
        result = has_active_subscription(99999)
        assert result is False

    def test_increment_usage_with_tokens_no_subscription(self, app_context):
        from services.subscription import increment_usage_with_tokens
        # Find a user without active subscription
        result = increment_usage_with_tokens(99999, 1)
        assert result['success'] is False

    def test_increment_usage_with_tokens_valid_user(self, app_context):
        from services.subscription import increment_usage_with_tokens
        # Find a user with active subscription
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        sub = SubscribedUser.query.filter(
            SubscribedUser.end_date > now,
            SubscribedUser._is_active == True
        ).first()
        if not sub:
            pytest.skip("No active subscriptions")
        result = increment_usage_with_tokens(sub.U_ID, 1)
        assert isinstance(result, dict)
        assert 'success' in result

    def test_record_usage_log(self, app_context):
        from services.subscription import record_usage_log
        user = User.query.first()
        result = record_usage_log(
            user_id=user.id,
            subscription_id=None,
            operation_type='test_operation',
            details='Unit test',
            tokens_used=0,
            is_trial=True
        )
        assert result is True

    def test_get_available_tokens_nonexistent_user(self, app_context):
        from services.subscription import get_available_tokens
        result = get_available_tokens(99999)
        assert isinstance(result, dict)

    def test_get_user_token_summary(self, app_context):
        from services.subscription import get_user_token_summary
        user = User.query.first()
        result = get_user_token_summary(user.id)
        # Returns dict or None depending on whether user has token purchases
        assert result is None or isinstance(result, dict)

    def test_get_today_token_usage_breakdown(self, app_context):
        from services.subscription import get_today_token_usage_breakdown
        user = User.query.first()
        result = get_today_token_usage_breakdown(user.id)
        assert isinstance(result, dict)
        assert 'daily_quota_used' in result
        assert 'daily_limit' in result

    def test_cleanup_duplicate_subscriptions(self, app_context):
        from services.subscription import cleanup_duplicate_subscriptions
        result = cleanup_duplicate_subscriptions()
        assert isinstance(result, int)
        assert result >= 0

    def test_add_search_history(self, app_context):
        from services.subscription import add_search_history
        user = User.query.first()
        result = add_search_history(user.id, 'test_tool', 'https://test.com')
        assert result is True

    def test_add_search_history_no_user(self, app_context):
        from services.subscription import add_search_history
        result = add_search_history(None, 'test_tool', 'https://test.com')
        assert result is False

    def test_remove_search_history(self, app_context):
        from services.subscription import remove_search_history
        result = remove_search_history(99999, 'nonexistent')
        assert result is True  # Returns True even if nothing to delete

    def test_cleanup_old_crawl_data(self, app_context):
        from services.subscription import cleanup_old_crawl_data
        result = cleanup_old_crawl_data(days_to_keep=365)
        assert isinstance(result, int)
        assert result >= 0

    def test_handle_expired_subscriptions(self, app_context):
        from services.subscription import handle_expired_subscriptions
        subs_processed, tokens_paused = handle_expired_subscriptions()
        assert isinstance(subs_processed, int)
        assert isinstance(tokens_paused, int)

    def test_pause_expired_subscription_tokens(self, app_context):
        from services.subscription import pause_expired_subscription_tokens
        result = pause_expired_subscription_tokens(99999)
        assert isinstance(result, int)
        assert result == 0

    def test_reactivate_user_paused_tokens(self, app_context):
        from services.subscription import reactivate_user_paused_tokens
        count, total = reactivate_user_paused_tokens(99999, 99999)
        assert count == 0
        assert total == 0


class TestEmailService:
    """Tests for services/email.py functions."""

    def test_check_email_configuration(self, app_context):
        from services.email import check_email_configuration
        is_valid, missing = check_email_configuration()
        # In test config, all keys are set
        assert isinstance(is_valid, bool)
        assert isinstance(missing, list)

    def test_check_and_notify_expiring_subscriptions(self, app_context):
        from services.email import check_and_notify_expiring_subscriptions
        # Should run without error (mail is suppressed in test)
        result = check_and_notify_expiring_subscriptions()
        assert isinstance(result, int)
        assert result >= 0
