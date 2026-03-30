import requests
import json
import traceback
from scrapy.selector import Selector
from flask import flash
import logging
import random
import time

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AdvancedSEOAnalyzer:
    """
    Advanced SEO data extractor with multiple fallback mechanisms
    """
    
    # Expanded user agents list
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.63 Safari/537.36 Edg/93.0.961.47'
    ]

    # Referrer list to rotate
    REFERRERS = [
        'https://www.google.com',
        'https://www.bing.com',
        'https://www.yahoo.com',
        'https://duckduckgo.com'
    ]

    def __init__(self, url, retry_count=3, delay_between_retries=2, headless=True):
        """
        Initialize SEO Analyzer with advanced request strategies
        
        :param url: URL to analyze
        :param retry_count: Number of retry attempts
        :param delay_between_retries: Seconds between retries
        :param headless: Whether to run browser in headless mode
        """
        self.url = url.strip()
        self.retry_count = retry_count
        self.delay_between_retries = delay_between_retries
        self.headless = headless
        self.driver = None

    def _sanitize_url(self):
        """
        Ensure URL has a proper scheme
        
        :return: Sanitized URL
        """
        if not self.url:
            raise ValueError("Empty URL provided")
        
        if not self.url.startswith(('http://', 'https://')):
            return f'https://{self.url}'
        
        return self.url

    def _setup_selenium_driver(self):
        """
        Configure Selenium WebDriver with anti-detection strategies
        
        :return: Configured Chrome WebDriver
        """
        try:
            # Configure Chrome options
            chrome_options = Options()
            
            # Set random user agent
            user_agent = random.choice(self.USER_AGENTS)
            chrome_options.add_argument(f'user-agent={user_agent}')
            
            # Headless mode
            if self.headless:
                chrome_options.add_argument('--headless')
            
            # Anti-detection strategies
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            # Additional options
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            
            # Setup WebDriver
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Additional stealth techniques
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            return driver
        
        except Exception as e:
            logger.error(f"Selenium WebDriver setup error: {e}")
            return None

    def extract_seo_data(self):
        """
        Extract SEO data with multiple fallback strategies
        
        :return: Dictionary of SEO data
        """
        try:
            # Sanitize URL
            url = self._sanitize_url()
            
            # First attempt: Standard requests
            response_text = self._fetch_with_requests(url)
            
            # If requests fail, try Selenium
            if not response_text:
                response_text = self._fetch_with_selenium(url)
            
            # If both fail, return error
            if not response_text:
                return {
                    'error': f"Failed to fetch URL: {url}",
                    'title': '',
                    'meta_tags': [],
                    'schema': []
                }
            
            # Parse the fetched content
            return self._parse_seo_data(response_text)
        
        except Exception as e:
            logger.error(f"SEO extraction error: {traceback.format_exc()}")
            return {
                'error': f"Unexpected error: {e}",
                'title': '',
                'meta_tags': [],
                'schema': []
            }
        finally:
            # Ensure WebDriver is closed
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass

    def _fetch_with_requests(self, url):
        """
        Fetch URL content using requests with advanced strategies
        
        :param url: URL to fetch
        :return: Page source or None
        """
        for attempt in range(self.retry_count):
            try:
                # Sophisticated headers
                headers = {
                    'User-Agent': random.choice(self.USER_AGENTS),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Referer': random.choice(self.REFERRERS),
                    'DNT': '1',
                    'Upgrade-Insecure-Requests': '1',
                }
                
                # Exponential backoff
                if attempt > 0:
                    time.sleep(self.delay_between_retries * (2 ** attempt) + random.random())
                
                resp = requests.get(
                    url,
                    headers=headers,
                    timeout=(90, 120),  # Increased: (connect, read) timeouts for AWS
                    allow_redirects=True
                )
                
                # Check content type and status
                if resp.status_code == 200 and 'text/html' in resp.headers.get('Content-Type', '').lower():
                    return resp.text
                
                logger.warning(f"Attempt {attempt+1} failed. Status: {resp.status_code}")
            
            except requests.RequestException as e:
                logger.error(f"Request attempt {attempt+1} failed: {e}")
        
        return None

    def _fetch_with_selenium(self, url):
        """
        Fetch URL content using Selenium as a fallback
        
        :param url: URL to fetch
        :return: Page source or None
        """
        try:
            # Setup Selenium WebDriver
            self.driver = self._setup_selenium_driver()
            
            if not self.driver:
                logger.error("Failed to initialize Selenium WebDriver")
                return None
            
            # Navigate to URL
            self.driver.get(url)
            
            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, 'body'))
            )
            
            # Return page source
            return self.driver.page_source
        
        except Exception as e:
            logger.error(f"Selenium fetch error: {e}")
            return None

    def _parse_seo_data(self, html_content):
        """
        Parse SEO data from HTML content
        
        :param html_content: HTML source code
        :return: Dictionary of SEO data
        """
        try:
            sel = Selector(text=html_content)

            # Extract <title> tag content
            title = sel.xpath('//title/text()').get() or ''
            
            # Extract meta tags
            meta_elements = sel.xpath('//meta')
            meta_data = []
            for m in meta_elements:
                name_attr = m.xpath('@name').get() or m.xpath('@property').get()
                content = m.xpath('@content').get()
                if name_attr or content:
                    meta_data.append({
                        'attribute': name_attr if name_attr else '',
                        'content': content if content else ''
                    })
            
            # Extract schema data from JSON-LD
            schema_elements = sel.xpath('//script[@type="application/ld+json"]/text()').getall()
            schema_data = []
            for schema in schema_elements:
                try:
                    parsed = json.loads(schema)
                    schema_data.append(parsed)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse schema: {schema[:100]}...")
                    continue

            return {
                'error': '',
                'title': title.strip(),
                'meta_tags': meta_data,
                'schema': schema_data
            }
        
        except Exception as e:
            logger.error(f"Parsing error: {traceback.format_exc()}")
            return {
                'error': f"Error parsing URL content: {e}",
                'title': '',
                'meta_tags': [],
                'schema': []
            }

def extract_seo_data(url):
    """
    Convenience function to extract SEO data
    
    :param url: URL to analyze
    :return: Dictionary of SEO data
    """
    analyzer = AdvancedSEOAnalyzer(url)
    return analyzer.extract_seo_data()

# Example usage
if __name__ == "__main__":
    test_url = "https://example.com"
    seo_data = extract_seo_data(test_url)
    print(json.dumps(seo_data, indent=2))
