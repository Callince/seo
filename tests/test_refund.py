"""Unit tests for refund service and payment protection."""
import pytest
from models import Payment, User, Subscription, SubscribedUser


class TestRefundService:
    """Tests for services/refund.py functions."""

    def test_import_refund_service(self, app_context):
        from services.refund import (
            issue_razorpay_refund,
            auto_refund_failed_payment,
            admin_refund_payment,
            cancel_subscription_with_refund,
            check_duplicate_payment,
            handle_webhook_payment
        )
        # All functions importable
        assert callable(issue_razorpay_refund)
        assert callable(auto_refund_failed_payment)
        assert callable(admin_refund_payment)
        assert callable(cancel_subscription_with_refund)
        assert callable(check_duplicate_payment)
        assert callable(handle_webhook_payment)

    def test_auto_refund_nonexistent_payment(self, app_context):
        from services.refund import auto_refund_failed_payment
        result = auto_refund_failed_payment(99999)
        assert result['success'] is False
        assert 'not found' in result['message'].lower()

    def test_admin_refund_nonexistent_payment(self, app_context):
        from services.refund import admin_refund_payment
        result = admin_refund_payment(99999, admin_id=1, reason='test')
        assert result['success'] is False
        assert 'not found' in result['message'].lower()

    def test_admin_refund_non_completed_payment(self, app_context):
        from services.refund import admin_refund_payment
        payment = Payment.query.filter_by(status='created').first()
        if not payment:
            pytest.skip("No created payments")
        result = admin_refund_payment(payment.iid, admin_id=1, reason='test')
        assert result['success'] is False
        assert 'cannot refund' in result['message'].lower()

    def test_cancel_subscription_nonexistent(self, app_context):
        from services.refund import cancel_subscription_with_refund
        result = cancel_subscription_with_refund(99999, 99999)
        assert result['success'] is False
        assert 'not found' in result['message'].lower()


class TestDuplicatePaymentCheck:
    """Tests for duplicate payment protection."""

    def test_no_duplicate_for_new_user(self, app_context):
        from services.refund import check_duplicate_payment
        result = check_duplicate_payment(99999, 1)
        assert result['is_duplicate'] is False

    def test_duplicate_check_returns_dict(self, app_context):
        from services.refund import check_duplicate_payment
        user = User.query.first()
        sub = Subscription.query.first()
        result = check_duplicate_payment(user.id, sub.S_ID)
        assert isinstance(result, dict)
        assert 'is_duplicate' in result


class TestWebhookEndpoint:
    """Tests for Razorpay webhook endpoint."""

    def test_webhook_empty_body(self, client):
        resp = client.post('/webhook/razorpay',
                           data='{}',
                           content_type='application/json')
        assert resp.status_code in (200, 400)

    def test_webhook_invalid_event(self, client):
        resp = client.post('/webhook/razorpay',
                           json={'event': 'unknown.event', 'payload': {}})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'ignored'

    def test_webhook_payment_failed_event(self, client):
        resp = client.post('/webhook/razorpay',
                           json={
                               'event': 'payment.failed',
                               'payload': {
                                   'payment': {
                                       'entity': {
                                           'id': 'pay_fake123',
                                           'order_id': 'order_fake123',
                                           'status': 'failed'
                                       }
                                   }
                               }
                           })
        assert resp.status_code == 200


class TestAdminRefundRoute:
    """Tests for admin refund route."""

    def test_refund_requires_admin_login(self, client):
        resp = client.get('/admin/payments/refund/1')
        assert resp.status_code == 302  # Redirects to admin login

    def test_refund_page_with_admin(self, admin_client):
        client, admin = admin_client
        payment = Payment.query.first()
        if not payment:
            pytest.skip("No payments in database")
        resp = client.get(f'/admin/payments/refund/{payment.iid}')
        assert resp.status_code in (200, 302)  # 200 if has permission, 302 if not


class TestCancelSubscriptionRefund:
    """Tests for cancel with refund option."""

    def test_cancel_page_shows_refund_info(self, app_context, user_session_client):
        client, user = user_session_client
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        sub = SubscribedUser.query.filter(
            SubscribedUser.U_ID == user.id,
            SubscribedUser.end_date > now,
            SubscribedUser._is_active == True
        ).first()
        if not sub:
            pytest.skip("User has no active subscription")
        resp = client.get(f'/subscription/cancel/{sub.id}')
        assert resp.status_code == 200
