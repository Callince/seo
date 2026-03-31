"""Unit tests for auth blueprint routes."""
import pytest
from models import User


class TestPublicAuthPages:
    """Test auth pages accessible without login."""

    def test_login_page(self, client):
        resp = client.get('/login')
        assert resp.status_code == 200
        assert b'login' in resp.data.lower() or b'sign in' in resp.data.lower()

    def test_signup_page(self, client):
        resp = client.get('/signup')
        assert resp.status_code == 200
        assert b'sign' in resp.data.lower()

    def test_reset_password_page(self, client):
        resp = client.get('/reset_password')
        assert resp.status_code == 200

    def test_resend_verification_page(self, client):
        resp = client.get('/resend_verification')
        assert resp.status_code == 200

    def test_verify_account_page(self, client):
        resp = client.get('/verify_account?email=test@test.com')
        assert resp.status_code == 200


class TestLoginFlow:
    """Test login functionality."""

    def test_login_post_empty(self, client):
        resp = client.post('/login', data={}, follow_redirects=True)
        assert resp.status_code == 200

    def test_login_post_invalid_email(self, client):
        resp = client.post('/login', data={
            'companyEmail': 'nonexistent@fake.com',
            'password': 'wrong'
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Invalid' in resp.data or b'invalid' in resp.data

    def test_login_post_wrong_password(self, app_context, client):
        user = User.query.filter_by(email_confirmed=True).first()
        if not user:
            pytest.skip("No confirmed user")
        resp = client.post('/login', data={
            'companyEmail': user.company_email,
            'password': 'WrongPassword@123'
        }, follow_redirects=True)
        assert resp.status_code == 200


class TestSignupFlow:
    """Test signup functionality."""

    def test_signup_post_empty(self, client):
        resp = client.post('/signup', data={}, follow_redirects=True)
        assert resp.status_code == 200

    def test_signup_post_short_name(self, client):
        resp = client.post('/signup', data={
            'name': 'A',
            'companyEmail': 'newuser@test.com',
            'password': 'Test@12345',
            'retypePassword': 'Test@12345'
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'at least 2' in resp.data.lower() or b'danger' in resp.data.lower()

    def test_signup_post_invalid_email(self, client):
        resp = client.post('/signup', data={
            'name': 'Test User',
            'companyEmail': 'invalid-email',
            'password': 'Test@12345',
            'retypePassword': 'Test@12345'
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_signup_post_password_mismatch(self, client):
        resp = client.post('/signup', data={
            'name': 'Test User',
            'companyEmail': 'newtest@test.com',
            'password': 'Test@12345',
            'retypePassword': 'Different@123'
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'match' in resp.data.lower()

    def test_signup_post_weak_password(self, client):
        resp = client.post('/signup', data={
            'name': 'Test User',
            'companyEmail': 'newtest@test.com',
            'password': 'weak',
            'retypePassword': 'weak'
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_signup_existing_email(self, app_context, client):
        user = User.query.first()
        resp = client.post('/signup', data={
            'name': 'Test User',
            'companyEmail': user.company_email,
            'password': 'Test@12345',
            'retypePassword': 'Test@12345'
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'already registered' in resp.data.lower()


class TestCheckEmail:
    """Test email availability check endpoint."""

    def test_check_email_available(self, client):
        resp = client.post('/check_email', data={
            'email': 'definitely_not_taken_12345@test.com'
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['available'] is True

    def test_check_email_taken(self, app_context, client):
        user = User.query.first()
        resp = client.post('/check_email', data={
            'email': user.company_email
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['available'] is False

    def test_check_email_invalid(self, client):
        resp = client.post('/check_email', data={
            'email': 'not-an-email'
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['available'] is False

    def test_check_email_empty(self, client):
        resp = client.post('/check_email', data={'email': ''})
        assert resp.status_code == 200


class TestPasswordReset:
    """Test password reset flow."""

    def test_reset_request_nonexistent_email(self, client):
        resp = client.post('/reset_password', data={
            'companyEmail': 'nonexistent@fake.com'
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'not found' in resp.data.lower() or b'register' in resp.data.lower()

    def test_reset_token_invalid(self, client):
        resp = client.get('/reset_password/invalid-token', follow_redirects=True)
        assert resp.status_code == 200

    def test_verify_email_invalid_token(self, client):
        resp = client.get('/verify_email/invalid-token', follow_redirects=True)
        assert resp.status_code == 200


class TestLogout:
    """Test logout."""

    def test_logout_redirects(self, client):
        resp = client.get('/logout')
        assert resp.status_code == 302


class TestProtectedPages:
    """Test that protected pages redirect without login."""

    def test_profile_requires_login(self, client):
        resp = client.get('/profile')
        assert resp.status_code == 302

    def test_search_history_requires_login(self, client):
        resp = client.get('/search_history')
        assert resp.status_code == 302

    def test_update_profile_requires_login(self, client):
        resp = client.post('/update_profile', data={})
        assert resp.status_code == 302


class TestProfileWithSession:
    """Test profile pages with user session."""

    def test_profile_page_loads(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/profile')
        assert resp.status_code == 200

    def test_search_history_loads(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/search_history')
        assert resp.status_code == 200

    def test_update_profile_name(self, user_session_client):
        client, user = user_session_client
        resp = client.post('/update_profile', data={
            'update_type': 'account',
            'name': user.name  # Keep same name
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_verify_current_password_wrong(self, user_session_client):
        client, user = user_session_client
        resp = client.post('/verify_current_password',
                           json={'currentPassword': 'wrong'},
                           content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['valid'] is False
