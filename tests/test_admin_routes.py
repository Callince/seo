"""Unit tests for admin blueprint routes."""
import pytest
from models import Admin


class TestAdminLoginPage:
    """Test admin login page."""

    def test_admin_login_page(self, client):
        resp = client.get('/admin/login')
        assert resp.status_code == 200

    def test_admin_login_wrong_credentials(self, client):
        resp = client.post('/admin/login', data={
            'email_id': 'wrong@email.com',
            'password': 'wrong'
        }, follow_redirects=True)
        assert resp.status_code == 200


class TestAdminProtectedRoutes:
    """Test that admin routes require authentication."""

    @pytest.mark.parametrize("url", [
        '/admin/',
        '/admin/users',
        '/admin/payments',
        '/admin/subscriptions',
        '/admin/subscribed-users',
        '/admin/contact_submissions',
        '/admin/email_logs',
        '/admin/website-settings',
        '/admin/blog_categories',
        '/admin/blogs',
        '/admin/webstories',
        '/admin/roles',
        '/admin/search_history',
    ])
    def test_admin_routes_redirect_without_login(self, client, url):
        resp = client.get(url)
        assert resp.status_code == 302, f"{url} should redirect without admin session"


class TestAdminDashboard:
    """Test admin dashboard with session."""

    def test_dashboard_loads(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/')
        assert resp.status_code == 200

    def test_users_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/users')
        assert resp.status_code in (200, 302)  # 302 if missing permission

    def test_payments_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/payments')
        assert resp.status_code in (200, 302)

    def test_subscriptions_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/subscriptions')
        assert resp.status_code in (200, 302)

    def test_subscribed_users_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/subscribed-users')
        assert resp.status_code in (200, 302)

    def test_contact_submissions_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/contact_submissions')
        assert resp.status_code in (200, 302)

    def test_email_logs_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/email_logs')
        assert resp.status_code in (200, 302)

    def test_website_settings_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/website-settings')
        assert resp.status_code in (200, 302)

    def test_search_history_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/search_history')
        assert resp.status_code in (200, 302)

    def test_roles_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/roles')
        assert resp.status_code in (200, 302)


class TestAdminBlogRoutes:
    """Test admin blog management routes."""

    def test_blog_categories_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/blog_categories')
        assert resp.status_code == 200

    def test_blogs_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/blogs')
        assert resp.status_code == 200

    def test_add_blog_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/blog/add')
        assert resp.status_code in (200, 302)

    def test_add_blog_category_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/blog_category/add')
        assert resp.status_code == 200


class TestAdminWebStoryRoutes:
    """Test admin webstory management routes."""

    def test_webstories_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/webstories')
        assert resp.status_code == 200

    def test_add_webstory_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/webstory/add')
        assert resp.status_code in (200, 302)


class TestAdminSubscriptionRoutes:
    """Test admin subscription management."""

    def test_new_subscription_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/subscriptions/new')
        assert resp.status_code == 200

    def test_new_subscribed_user_page(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/subscribed-users/new')
        assert resp.status_code == 200


class TestAdminExports:
    """Test admin export endpoints."""

    def test_export_search_history(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/search_history/export')
        assert resp.status_code in (200, 302)

    def test_export_contact_submissions(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/export_contact_submissions')
        assert resp.status_code in (200, 302)

    def test_export_email_logs(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/email_logs/export')
        assert resp.status_code in (200, 302)


class TestAdminLogout:
    """Test admin logout."""

    def test_admin_logout(self, admin_client):
        client, admin = admin_client
        resp = client.get('/admin/logout')
        assert resp.status_code == 302
