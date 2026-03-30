import requests
from urllib.parse import urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup
from scrapy.selector import Selector
from flask import flash
import random
import time
import logging
from typing import List, Dict, Optional, Tuple
import re
import json

# Selenium imports
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("Selenium not available. Install with: pip install selenium webdriver-manager")

# Import the robots parser - try both relative and absolute imports
try:
    from robots_parser import RobotsParser, analyze_robots_txt
except ImportError:
    try:
        from robots_parser import RobotsParser, analyze_robots_txt
    except ImportError:
        try:
            from robots_parser import RobotsParser, analyze_robots_txt
        except ImportError:
            print("Warning: robots_parser not found. Robots.txt support disabled.")
            def analyze_robots_txt(url):
                return None

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('link_analyzer.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class LinkAnalyzer:
    """
    Advanced link analyzer with robust error handling, 
    requests, and Selenium as a fallback mechanism.
    """
    
    # Expanded and more diverse user agents
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.63 Safari/537.36 Edg/93.0.961.47'
    ]

    # Regex to filter out unwanted link types
    INVALID_LINK_PATTERNS = [
        r'^javascript:',
        r'^mailto:',
        r'^tel:',
        r'^#',
        r'^data:',
        r'^blob:',
        r'^file:'
    ]

    def __init__(
        self, 
        url: str, 
        user_agent: Optional[str] = None, 
        retry_count: int = 3, 
        delay_between_retries: int = 2, 
        respect_robots: bool = True,
        headless: bool = True
    ):
        """
        Initialize the Link Analyzer with Selenium fallback.
        
        :param url: URL to analyze
        :param user_agent: Custom user agent (optional)
        :param retry_count: Number of retry attempts
        :param delay_between_retries: Seconds between retries
        :param respect_robots: Whether to respect robots.txt
        :param headless: Whether to run browser in headless mode
        """
        self.url = url
        self.user_agent = user_agent or random.choice(self.USER_AGENTS)
        self.retry_count = retry_count
        self.delay_between_retries = delay_between_retries
        self.respect_robots = respect_robots
        self.headless = headless
        self.robots_info = None
        self.robots_parser = None
        self.driver = None

    def _setup_selenium_driver(self) -> Optional[webdriver.Chrome]:
        """
        Set up Selenium WebDriver with custom options optimized for EC2.

        :return: Configured Chrome WebDriver
        """
        if not SELENIUM_AVAILABLE:
            logger.warning("Selenium not available, skipping WebDriver setup")
            return None

        try:
            # Configure Chrome options for headless EC2 environment
            chrome_options = Options()

            # Set user agent
            chrome_options.add_argument(f'user-agent={self.user_agent}')

            # Headless mode (required for server environments)
            if self.headless:
                chrome_options.add_argument('--headless=new')

            # Critical options for EC2/server environments
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-software-rasterizer')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-setuid-sandbox')

            # Memory and performance optimizations
            chrome_options.add_argument('--disable-logging')
            chrome_options.add_argument('--log-level=3')
            chrome_options.add_argument('--silent')
            chrome_options.add_argument('--disable-background-networking')
            chrome_options.add_argument('--disable-background-timer-throttling')
            chrome_options.add_argument('--disable-backgrounding-occluded-windows')
            chrome_options.add_argument('--disable-breakpad')
            chrome_options.add_argument('--disable-component-extensions-with-background-pages')
            chrome_options.add_argument('--disable-features=TranslateUI,BlinkGenPropertyTrees')
            chrome_options.add_argument('--disable-ipc-flooding-protection')
            chrome_options.add_argument('--disable-renderer-backgrounding')
            chrome_options.add_argument('--enable-features=NetworkService,NetworkServiceInProcess')
            chrome_options.add_argument('--force-color-profile=srgb')
            chrome_options.add_argument('--hide-scrollbars')
            chrome_options.add_argument('--metrics-recording-only')
            chrome_options.add_argument('--mute-audio')

            # Window size for headless mode
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--start-maximized')

            # Disable automation flags
            chrome_options.add_experimental_option(
                "excludeSwitches", ["enable-automation", "enable-logging"]
            )
            chrome_options.add_experimental_option(
                'useAutomationExtension', False
            )

            # Additional preferences
            prefs = {
                'profile.default_content_setting_values': {
                    'images': 2,  # Disable images for faster loading
                    'plugins': 2,
                    'popups': 2,
                    'geolocation': 2,
                    'notifications': 2,
                    'media_stream': 2,
                }
            }
            chrome_options.add_experimental_option('prefs', prefs)

            # Setup WebDriver
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)

            # Set timeouts - increased for AWS environment
            driver.set_page_load_timeout(120)
            driver.set_script_timeout(60)

            return driver

        except Exception as e:
            logger.error(f"Error setting up Selenium WebDriver: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _extract_links_selenium(self, driver) -> List[str]:
        """
        Extract links using Selenium.
        
        :param driver: Selenium WebDriver
        :return: List of extracted links
        """
        try:
            # Wait for page to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, 'body'))
            )
            
            # Find all anchor elements
            links = driver.find_elements(By.TAG_NAME, 'a')
            
            # Extract href attributes
            extracted_links = [
                link.get_attribute('href') 
                for link in links 
                if link.get_attribute('href')
            ]
            
            return extracted_links
        
        except Exception as e:
            logger.error(f"Error extracting links with Selenium: {e}")
            return []

    def _make_request(self) -> Optional[str]:
        """
        Make request with fallback to Selenium and connection pooling.

        :return: Page source or None
        """
        # Create a session with connection pooling for better performance
        session = requests.Session()

        # Configure connection pooling and retries
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=requests.adapters.Retry(
                total=0,  # We handle retries manually
                connect=0,
                read=0,
                backoff_factor=0
            )
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        # Quick connectivity check on first attempt only
        if self.retry_count > 0:
            try:
                logger.info(f"Quick connectivity check for {self.url}")
                # Try a quick HEAD request first (faster than GET)
                head_resp = session.head(
                    self.url,
                    headers={'User-Agent': self.user_agent},
                    timeout=(30, 30),  # Shorter timeout for HEAD
                    allow_redirects=True
                )
                if head_resp.status_code < 400:
                    logger.info(f"Quick check passed: {head_resp.status_code}")
                else:
                    logger.warning(f"Quick check returned: {head_resp.status_code}")
            except Exception as e:
                logger.warning(f"Quick check failed: {e}, proceeding with full request...")

        # Try requests with connection pooling
        for attempt in range(self.retry_count):
            try:
                # Sophisticated headers
                headers = {
                    'User-Agent': self.user_agent,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                    'Cache-Control': 'max-age=0',
                }

                # Add random delay with exponential backoff
                if attempt > 0:
                    wait_time = self.delay_between_retries * (2 ** attempt) + random.random()
                    logger.info(f"Waiting {wait_time:.2f}s before retry {attempt+1}...")
                    time.sleep(wait_time)

                logger.info(f"Attempt {attempt+1}/{self.retry_count} to fetch {self.url}")

                resp = session.get(
                    self.url,
                    headers=headers,
                    timeout=(90, 120),  # Increased: (connect timeout, read timeout)
                    allow_redirects=True,
                    verify=True  # Verify SSL certificates
                )

                # Check for successful response
                if resp.status_code == 200:
                    logger.info(f"Successfully fetched {self.url} with requests on attempt {attempt+1}")
                    session.close()
                    return resp.text

                logger.warning(f"Attempt {attempt+1} failed with status code {resp.status_code}")

            except requests.exceptions.RequestException as e:
                logger.error(f"Request error on attempt {attempt+1}: {e}")

        # Close session after all attempts
        session.close()
        
        # Fallback to Selenium if available
        if SELENIUM_AVAILABLE:
            try:
                logger.info("Falling back to Selenium...")
                # Setup Selenium WebDriver
                self.driver = self._setup_selenium_driver()
                
                if not self.driver:
                    logger.error("Failed to initialize Selenium WebDriver")
                    return None

                # Navigate to URL
                self.driver.get(self.url)
                logger.info(f"Successfully fetched {self.url} with Selenium")
                
                # Return page source
                return self.driver.page_source
            
            except Exception as e:
                logger.error(f"Selenium request failed: {e}")
                return None
        else:
            logger.error("Selenium not available and requests failed")
            return None

    def analyze_links(self) -> Tuple[List[str], List[str], Optional[Dict]]:
        """
        Analyze links from the given URL with improved error handling and logging.
        
        :return: Tuple of (home_links, other_links, robots_info)
        """
        # Validate initial URL
        if not self.url.startswith(("http://", "https://")):
            logger.error(f"Invalid URL format: {self.url}")
            return [], [], None

        # Parse base URL for domain comparison
        try:
            parsed_base = urlparse(self.url)
            base_domain = parsed_base.netloc.lower()
            # Remove www. prefix for consistent comparison
            if base_domain.startswith('www.'):
                base_domain = base_domain[4:]
            # Remove port for comparison
            base_domain = base_domain.split(':')[0]
            
            logger.info(f"Analyzing {self.url} - Base domain: {base_domain}")
            
        except Exception as e:
            logger.error(f"Error parsing base URL {self.url}: {e}")
            return [], [], None

        # Check robots.txt if needed
        if self.respect_robots:
            try:
                logger.info("Checking robots.txt...")
                self.robots_info = analyze_robots_txt(self.url)
                
                if self.robots_info and self.robots_info.get('success'):
                    parser_id = self.robots_info.get('parser_id')
                    
                    # Get parser from the cache using the updated interface
                    if hasattr(analyze_robots_txt, 'parsers') and parser_id in analyze_robots_txt.parsers:
                        self.robots_parser = analyze_robots_txt.parsers[parser_id]
                        logger.info("Robots.txt parser initialized successfully")
                    else:
                        logger.warning("Robots.txt parser not found in global parsers")
                else:
                    logger.info("No robots.txt found or failed to parse")
                    
            except Exception as e:
                logger.error(f"Error analyzing robots.txt: {e}")
                self.robots_info = None
                self.robots_parser = None

        # Make request (with Selenium fallback)
        page_source = self._make_request()
        
        # Clean up Selenium driver if used
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Selenium driver closed successfully")
            except Exception as e:
                logger.error(f"Error closing Selenium driver: {e}")

        if not page_source:
            logger.error("Failed to retrieve page source")
            return [], [], self.robots_info

        # Extract links with improved error handling
        all_links = []
        
        try:
            # Method 1: Scrapy Selector
            try:
                sel = Selector(text=page_source)
                links_xpath = sel.xpath('//a[@href]/@href').getall()
                all_links.extend(links_xpath)
                logger.info(f"Scrapy extracted {len(links_xpath)} links")
            except Exception as e:
                logger.warning(f"Scrapy link extraction failed: {e}")
            
            # Method 2: BeautifulSoup
            try:
                soup = BeautifulSoup(page_source, "html.parser")
                links_bs = [a.get('href') for a in soup.find_all('a', href=True) if a.get('href')]
                all_links.extend(links_bs)
                logger.info(f"BeautifulSoup extracted {len(links_bs)} additional links")
            except Exception as e:
                logger.warning(f"BeautifulSoup link extraction failed: {e}")
            
            # Remove duplicates while preserving order
            seen = set()
            unique_links = []
            for link in all_links:
                if link and link not in seen:
                    seen.add(link)
                    unique_links.append(link)
            
            logger.info(f"Total unique links before filtering: {len(unique_links)}")
            
        except Exception as e:
            logger.error(f"Error parsing HTML: {e}")
            return [], [], self.robots_info

        # Convert relative URLs to absolute and normalize
        absolute_links = []
        for link in unique_links:
            if not self._is_valid_link(link):
                continue
                
            try:
                absolute_url = urljoin(self.url, link)
                normalized_url = self._normalize_url(absolute_url)
                
                # Validate the resulting URL
                parsed_link = urlparse(normalized_url)
                if parsed_link.netloc:  # Must have a domain
                    absolute_links.append(normalized_url)
                    
            except Exception as e:
                logger.debug(f"Error processing link {link}: {e}")
                continue

        logger.info(f"Valid absolute links: {len(absolute_links)}")

        # Filter links by robots.txt if needed
        if self.respect_robots and self.robots_parser:
            try:
                allowed_links = []
                blocked_count = 0
                for link in absolute_links:
                    if self.robots_parser.is_allowed(link):
                        allowed_links.append(link)
                    else:
                        blocked_count += 1
                
                absolute_links = allowed_links
                logger.info(f"Robots.txt filtering: {len(allowed_links)} allowed, {blocked_count} blocked")
                
            except Exception as e:
                logger.error(f"Error applying robots.txt filtering: {e}")

        # Categorize links with improved domain matching
        home_links = []
        other_links = []

        for link in absolute_links:
            try:
                parsed_link = urlparse(link)
                if not parsed_link.netloc:
                    continue

                # Normalize link domain for comparison
                link_domain = parsed_link.netloc.lower()
                if link_domain.startswith('www.'):
                    link_domain = link_domain[4:]
                # Remove port for comparison
                link_domain = link_domain.split(':')[0]

                # Compare domains
                if link_domain == base_domain:
                    home_links.append(link)
                else:
                    other_links.append(link)
                    
            except Exception as e:
                logger.debug(f"Error categorizing link {link}: {e}")
                # If we can't categorize, add to other_links as safe fallback
                other_links.append(link)

        # Final deduplication and sorting
        home_links = sorted(list(set(home_links)))
        other_links = sorted(list(set(other_links)))
        
        logger.info(f"Final results - Home links: {len(home_links)}, Other links: {len(other_links)}")
        
        # Log warning if no home links found
        if len(home_links) == 0:
            logger.warning(f"No home links found for {self.url} (base domain: {base_domain})")
            # Log first few links for debugging
            for i, link in enumerate(absolute_links[:5]):
                try:
                    parsed = urlparse(link)
                    link_domain = parsed.netloc.lower().replace('www.', '').split(':')[0]
                    logger.warning(f"Sample link {i+1}: {link} (domain: {link_domain})")
                except:
                    logger.warning(f"Sample link {i+1}: {link} (could not parse domain)")

        return home_links, other_links, self.robots_info

    def _is_valid_link(self, link: str) -> bool:
        """
        Check if a link is valid based on predefined patterns.
        
        :param link: URL to validate
        :return: Boolean indicating link validity
        """
        if not link or not isinstance(link, str):
            return False
            
        return not any(
            re.match(pattern, link, re.IGNORECASE) 
            for pattern in self.INVALID_LINK_PATTERNS
        )

    def _normalize_url(self, url: str) -> str:
        """
        Normalize URL by removing fragments and standardizing
        
        :param url: URL to normalize
        :return: Normalized URL
        """
        try:
            parsed = urlparse(url)
            # Remove fragment
            cleaned = parsed._replace(fragment='')
            # Don't lowercase the entire URL, just the scheme and netloc
            cleaned = cleaned._replace(
                scheme=cleaned.scheme.lower(),
                netloc=cleaned.netloc.lower()
            )
            return urlunparse(cleaned).rstrip('/')
        except Exception:
            return url


def analyze_links(
    url: str, 
    user_agent: Optional[str] = None, 
    retry_count: int = 3, 
    delay_between_retries: int = 2, 
    respect_robots: bool = True,
    headless: bool = True
) -> Tuple[List[str], List[str], Optional[Dict]]:
    """
    Convenience function to analyze links from a URL.
    This is the main function that should be imported and used.
    
    :param url: URL to analyze
    :param user_agent: Custom user agent (optional)
    :param retry_count: Number of retry attempts
    :param delay_between_retries: Seconds between retries
    :param respect_robots: Whether to respect robots.txt
    :param headless: Whether to run browser in headless mode
    :return: Tuple of (home_links, other_links, robots_info)
    """
    try:
        logger.info(f"Starting link analysis for: {url}")
        
        analyzer = LinkAnalyzer(
            url, 
            user_agent, 
            retry_count, 
            delay_between_retries, 
            respect_robots,
            headless
        )
        
        result = analyzer.analyze_links()
        
        # Log summary
        home_count, other_count = len(result[0]), len(result[1])
        logger.info(f"Analysis complete - Home: {home_count}, Other: {other_count}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in analyze_links function: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return [], [], None


# Backward compatibility - ensure this function exists with the right signature
def analyze_links_with_debug(url, respect_robots=True):
    """
    Wrapper around analyze_links with debugging
    This function matches the signature expected by your app.py
    """
    try:
        logger.info(f"Starting link analysis for: {url}")
        
        # Call the main analyze_links function
        home_links, other_links, robots_info = analyze_links(
            url=url,
            respect_robots=respect_robots
        )
        
        # Debug the results
        try:
            parsed_url = urlparse(url)
            base_domain = parsed_url.netloc.lower().replace('www.', '')
            
            logger.info(f"=== Link Analysis Debug for {url} ===")
            logger.info(f"Base domain: {base_domain}")
            logger.info(f"Home links count: {len(home_links)}")
            logger.info(f"Other links count: {len(other_links)}")
            logger.info(f"Robots info available: {robots_info is not None}")
            
            if len(home_links) == 0:
                logger.warning(f"WARNING: No home links found for {url}")
                
            # Log first few home links for debugging
            for i, link in enumerate(home_links[:5]):
                logger.info(f"Home link {i+1}: {link}")
                
            # Log first few other links for debugging
            for i, link in enumerate(other_links[:5]):
                logger.info(f"Other link {i+1}: {link}")
                
        except Exception as e:
            logger.error(f"Error in debug logging: {str(e)}")
        
        return home_links, other_links, robots_info
        
    except Exception as e:
        logger.error(f"Error in analyze_links_with_debug: {str(e)}")
        import traceback
        logger.error(f"Exception details: {traceback.format_exc()}")
        return [], [], None


# Example usage
if __name__ == "__main__":
    # Example of how to use the function
    example_url = "https://example.com"
    home_links, other_links, robots_info = analyze_links(example_url)
    
    print("Home Links:", len(home_links))
    print("Other Links:", len(other_links))
    print("Robots Info:", robots_info is not None)
