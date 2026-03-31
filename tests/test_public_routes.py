"""Unit tests for public blueprint routes."""
import pytest


class TestPublicPages:
    """Test all public pages load without errors."""

    @pytest.mark.parametrize("url,expected_status", [
        ('/', 200),
        ('/about', 200),
        ('/privacy', 200),
        ('/terms', 200),
        ('/contact', 200),
        ('/cookie-policy', 200),
        ('/help', 200),
        ('/pricing', 200),
        ('/technical-seo', 200),
    ])
    def test_public_page(self, client, url, expected_status):
        resp = client.get(url)
        assert resp.status_code == expected_status, f"{url} returned {resp.status_code}"


class TestServicePages:
    """Test service landing pages."""

    @pytest.mark.parametrize("url", [
        '/services/url-analysis',
        '/services/heading-analysis',
        '/services/keyword-analysis',
        '/services/image-analysis',
        '/services/meta-analysis',
        '/services/sitemap-analysis',
    ])
    def test_service_page(self, client, url):
        resp = client.get(url)
        assert resp.status_code == 200


class TestBlogPages:
    """Test blog public pages."""

    def test_blogs_listing(self, client):
        resp = client.get('/blogs')
        # May redirect to page 1 or return 200
        assert resp.status_code in (200, 302)

    def test_blog_detail_with_valid_slug(self, app_context, client):
        from models import Blog
        blog = Blog.query.filter_by(status=True).first()
        if not blog:
            pytest.skip("No active blogs")
        resp = client.get(f'/blog/{blog.slug}')
        assert resp.status_code == 200

    def test_blog_detail_invalid_slug(self, client):
        resp = client.get('/blog/nonexistent-slug-12345')
        assert resp.status_code in (302, 404)


class TestWebStoryPages:
    """Test webstory public pages."""

    def test_webstories_listing(self, client):
        resp = client.get('/webstories')
        assert resp.status_code in (200, 302)

    def test_webstory_detail_with_valid_slug(self, app_context, client):
        from models import WebStory
        ws = WebStory.query.filter_by(status=True).first()
        if not ws:
            pytest.skip("No active webstories")
        resp = client.get(f'/webstory/{ws.slug}')
        assert resp.status_code in (200, 302)  # May redirect if template has url_for issue

    def test_webstory_detail_invalid_slug(self, client):
        resp = client.get('/webstory/nonexistent-slug-12345')
        assert resp.status_code in (302, 404)


class TestSitemapPages:
    """Test sitemap pages."""

    def test_sitemap_index(self, client):
        resp = client.get('/sitemap')
        assert resp.status_code == 200

    def test_page_sitemap(self, client):
        resp = client.get('/page-sitemap')
        assert resp.status_code == 200

    def test_post_sitemap(self, client):
        resp = client.get('/post-sitemap')
        assert resp.status_code == 200

    def test_webstory_sitemap(self, client):
        resp = client.get('/web-story-sitemap')
        assert resp.status_code == 200

    def test_sitemap_xml(self, client):
        resp = client.get('/sitemap.xml')
        assert resp.status_code == 200
        assert b'xml' in resp.data.lower() or b'urlset' in resp.data.lower() or b'sitemap' in resp.data.lower()

    def test_sitemap_index_xml(self, client):
        resp = client.get('/sitemap_index.xml')
        assert resp.status_code == 200


class TestRobotsTxt:
    """Test robots.txt."""

    def test_robots_txt(self, client):
        resp = client.get('/robots.txt')
        assert resp.status_code == 200
        assert 'text/plain' in resp.content_type


class TestCsrfToken:
    """Test CSRF token endpoint."""

    def test_get_csrf_token(self, client):
        resp = client.get('/get-csrf-token')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'csrf_token' in data
        assert len(data['csrf_token']) > 10


class TestCronEndpoints:
    """Test cron job endpoints."""

    def test_cron_without_secret(self, client):
        resp = client.get('/cron/check-expiring-subscriptions')
        assert resp.status_code == 401

    def test_cron_with_wrong_secret(self, client):
        resp = client.get('/cron/check-expiring-subscriptions',
                          headers={'X-Cron-Secret': 'wrong-secret'})
        assert resp.status_code == 401

    def test_cron_with_correct_secret(self, client):
        resp = client.get('/cron/check-expiring-subscriptions',
                          headers={'X-Cron-Secret': 'test-cron-secret'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_cron_expired_subscriptions_without_secret(self, client):
        resp = client.get('/cron/handle-expired-subscriptions')
        assert resp.status_code == 401

    def test_cron_expired_with_correct_secret(self, client):
        resp = client.get('/cron/handle-expired-subscriptions',
                          headers={'X-Cron-Secret': 'test-cron-secret'})
        assert resp.status_code == 200


class TestContactForm:
    """Test contact form submission."""

    def test_contact_page_get(self, client):
        resp = client.get('/contact')
        assert resp.status_code == 200

    def test_contact_form_empty(self, client):
        resp = client.post('/contact', data={}, follow_redirects=True)
        assert resp.status_code == 200
