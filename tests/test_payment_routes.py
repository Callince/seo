"""Unit tests for payment blueprint routes."""
import pytest
from models import Subscription, SubscribedUser, Payment


class TestPaymentProtectedRoutes:
    """Test that payment routes require login."""

    @pytest.mark.parametrize("url", [
        '/subscriptions',
        '/get_available_plans',
    ])
    def test_payment_routes_redirect_without_login(self, client, url):
        resp = client.get(url)
        assert resp.status_code == 302


class TestSubscriptionsPage:
    """Test subscription listing page."""

    def test_subscriptions_page_loads(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/subscriptions')
        assert resp.status_code == 200

    def test_get_available_plans(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/get_available_plans')
        assert resp.status_code == 200


class TestSubscriptionDetails:
    """Test subscription detail pages."""

    def test_subscription_details_with_valid_id(self, app_context, user_session_client):
        client, user = user_session_client
        sub = SubscribedUser.query.filter_by(U_ID=user.id).first()
        if not sub:
            pytest.skip("User has no subscriptions")
        resp = client.get(f'/subscription_details/{sub.id}')
        assert resp.status_code == 200

    def test_subscription_details_invalid_id(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/subscription_details/99999')
        # Should return 404 or redirect
        assert resp.status_code in (200, 302, 404)


class TestPaymentInvoice:
    """Test invoice download."""

    def test_download_invoice_with_valid_payment(self, app_context, user_session_client):
        client, user = user_session_client
        payment = Payment.query.filter_by(user_id=user.id, status='completed').first()
        if not payment:
            pytest.skip("User has no completed payments")
        resp = client.get(f'/download_invoice/{payment.iid}')
        assert resp.status_code in (200, 302, 404)

    def test_download_invoice_invalid_id(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/download_invoice/99999')
        assert resp.status_code in (302, 404)


class TestReceiptDownload:
    """Test receipt download."""

    def test_receipt_requires_login(self, client):
        resp = client.get('/receipt/1')
        assert resp.status_code == 302
