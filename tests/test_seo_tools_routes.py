"""Unit tests for SEO tools blueprint routes."""
import pytest


class TestSeoToolsProtectedRoutes:
    """Test that SEO tool routes require login."""

    @pytest.mark.parametrize("url", [
        '/dashboard',
        '/url_search',
        '/keyword_search',
        '/image_search',
        '/h_search',
        '/meta_search',
        '/site_structure',
        '/loading',
        '/visualize',
        '/download_url',
        '/download_h_csv',
        '/download_image_csv',
        '/download_keyword_txt',
        '/download_meta_csv',
        '/download_results',
    ])
    def test_seo_routes_redirect_without_login(self, client, url):
        resp = client.get(url)
        assert resp.status_code == 302, f"{url} should redirect without login"


class TestPublicSeoPages:
    """Test SEO tool pages that are publicly accessible."""

    def test_content_checker(self, client):
        resp = client.get('/content-checker')
        assert resp.status_code == 200

    def test_time_date(self, client):
        resp = client.get('/time-date')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'date' in data or 'time' in data or isinstance(data, dict)


class TestDashboard:
    """Test dashboard with user session."""

    def test_dashboard_loads(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/dashboard')
        assert resp.status_code == 200


class TestUrlSearch:
    """Test URL search pages."""

    def test_url_search_page(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/url_search')
        assert resp.status_code == 200

    def test_url_search_ajax_no_url(self, user_session_client):
        client, user = user_session_client
        resp = client.post('/url_search_ajax', data={'url': ''})
        assert resp.status_code in (200, 302, 400)

    def test_record_search(self, user_session_client):
        client, user = user_session_client
        resp = client.post('/record_search', data={})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True


class TestKeywordSearch:
    """Test keyword search pages."""

    def test_keyword_search_page(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/keyword_search')
        assert resp.status_code == 200


class TestImageSearch:
    """Test image search pages."""

    def test_image_search_page(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/image_search')
        assert resp.status_code == 200


class TestHeadingSearch:
    """Test heading search pages."""

    def test_h_search_page(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/h_search')
        assert resp.status_code == 200


class TestMetaSearch:
    """Test meta search pages."""

    def test_meta_search_page(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/meta_search')
        assert resp.status_code == 200


class TestSiteStructure:
    """Test site structure pages."""

    def test_site_structure_page(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/site_structure')
        assert resp.status_code == 200

    def test_loading_page_redirects_without_job(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/loading')
        # Redirects to site_structure when no job_id in session
        assert resp.status_code in (200, 302)

    def test_visualize_redirects_without_job(self, user_session_client):
        client, user = user_session_client
        resp = client.get('/visualize')
        # Redirects to site_structure when no job_id in session
        assert resp.status_code in (200, 302)
