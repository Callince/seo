import requests
from urllib.parse import urlparse, urljoin
import logging
import re
from flask import flash
import weakref
import hashlib

logger = logging.getLogger(__name__)

class RobotsParser:
    def __init__(self, user_agent="*"):
        """
        Initialize the robots parser with a default user agent.
        
        Args:
            user_agent (str): The user agent to check against. Defaults to "*" (all user agents).
        """
        self.user_agent = user_agent
        self.disallow_rules = {}  # Domain -> list of disallow rules
        self.allow_rules = {}     # Domain -> list of allow rules
        self.sitemaps = {}        # Domain -> list of sitemaps
        self.crawl_delays = {}    # Domain -> crawl delay in seconds
        
    def fetch_and_parse(self, url):
        """
        Fetch and parse the robots.txt file for the given URL.
        
        Args:
            url (str): The URL of the website to fetch robots.txt from.
            
        Returns:
            bool: True if robots.txt was fetched and parsed successfully, False otherwise.
        """
        try:
            parsed_url = urlparse(url)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            robots_url = urljoin(base_url, '/robots.txt')
            
            # Fetch the robots.txt file
            response = requests.get(robots_url, timeout=10)
            
            # If robots.txt doesn't exist or is inaccessible, assume everything is allowed
            if response.status_code != 200:
                logger.info(f"No robots.txt found at {robots_url} (status code: {response.status_code})")
                return True
                
            # Parse the robots.txt content
            domain = parsed_url.netloc
            self._parse_robots_txt(domain, response.text)
            return True
            
        except Exception as e:
            logger.error(f"Error fetching robots.txt: {str(e)}")
            return False
            
    def _parse_robots_txt(self, domain, content):
        """
        Parse the robots.txt content and extract rules.
        
        Args:
            domain (str): The domain for which the robots.txt applies.
            content (str): The content of the robots.txt file.
        """
        current_agent = None
        self.disallow_rules[domain] = []
        self.allow_rules[domain] = []
        self.sitemaps[domain] = []
        
        for line in content.split('\n'):
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
                
            # Extract directive and value
            parts = line.split(':', 1)
            if len(parts) != 2:
                # Try with space as separator (some robots.txt use spaces instead of colons)
                parts = line.split(' ', 1)
                if len(parts) != 2:
                    continue
                
            directive = parts[0].strip().lower()
            value = parts[1].strip()
            
            # Handle User-agent
            if directive == 'user-agent':
                current_agent = value
                continue
                
            # Skip rules for other user agents
            if current_agent and current_agent != self.user_agent and current_agent != '*':
                continue
                
            # Process directives
            if directive == 'disallow' and value:
                self.disallow_rules[domain].append(value)
            elif directive == 'allow' and value:
                self.allow_rules[domain].append(value)
            elif directive == 'sitemap':
                self.sitemaps[domain].append(value)
            elif directive == 'crawl-delay':
                try:
                    self.crawl_delays[domain] = float(value)
                except ValueError:
                    pass
    
    def is_allowed(self, url):
        """
        Check if a URL is allowed to be crawled according to robots.txt rules.
        
        Args:
            url (str): The URL to check.
            
        Returns:
            bool: True if the URL is allowed, False otherwise.
        """
        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc
            path = parsed_url.path
            
            # If domain has no rules, allow by default
            if domain not in self.disallow_rules:
                return True
                
            # Check against disallow rules
            for rule in self.disallow_rules.get(domain, []):
                if self._matches_rule(path, rule):
                    # Check if there's a more specific allow rule
                    for allow_rule in self.allow_rules.get(domain, []):
                        if self._matches_rule(path, allow_rule) and len(allow_rule) > len(rule):
                            return True
                    return False
                    
            # If no matching disallow rule, allow by default
            return True
        except Exception as e:
            logger.error(f"Error checking if URL is allowed: {e}")
            return True  # Default to allowing if there's an error
    
    def _matches_rule(self, path, rule):
        """
        Check if a path matches a robots.txt rule.
        
        Args:
            path (str): The URL path to check.
            rule (str): The robots.txt rule.
            
        Returns:
            bool: True if the path matches the rule, False otherwise.
        """
        try:
            # Make sure path starts with /
            if not path:
                path = "/"
            elif not path.startswith("/"):
                path = "/" + path
                
            # Handle wildcards and end-of-string markers safely
            pattern = "^"
            i = 0
            while i < len(rule):
                if rule[i] == '*':
                    pattern += '.*'
                elif rule[i] == '$' and i == len(rule) - 1:
                    pattern += '$'
                else:
                    pattern += re.escape(rule[i])
                i += 1
                
            # If the rule doesn't end with $, it matches the prefix
            if not rule.endswith('$'):
                pattern += '.*'
                
            return bool(re.match(pattern, path, re.IGNORECASE))
        except Exception as e:
            logger.error(f"Error matching rule: {e}")
            return False
    
    def get_sitemaps(self, domain):
        """
        Get the sitemaps listed in robots.txt for a domain.
        
        Args:
            domain (str): The domain to get sitemaps for.
            
        Returns:
            list: List of sitemap URLs.
        """
        return self.sitemaps.get(domain, [])
    
    def get_crawl_delay(self, domain):
        """
        Get the crawl delay for a domain.
        
        Args:
            domain (str): The domain to get crawl delay for.
            
        Returns:
            float: The crawl delay in seconds, or None if not specified.
        """
        return self.crawl_delays.get(domain, None)
        
    def filter_allowed_urls(self, urls):
        """
        Filter a list of URLs to only include those allowed by robots.txt.
        
        Args:
            urls (list): List of URLs to filter.
            
        Returns:
            list: List of allowed URLs.
        """
        return [url for url in urls if self.is_allowed(url)]

# Use WeakValueDictionary to prevent memory leaks
_parsers_cache = {}
_MAX_CACHE_SIZE = 100

# Replace the bottom section of your robots_parser.py with this:

def analyze_robots_txt(url):
    """
    Analyze the robots.txt file for a given URL and return information about it.
    
    Args:
        url (str): The URL to analyze robots.txt for.
        
    Returns:
        dict: Dictionary containing robots.txt information.
    """
    # Generate a unique key for the URL
    url_key = hashlib.md5(url.encode('utf-8')).hexdigest()
    
    # Check if we already have a parser for this URL
    if url_key in _parsers_cache:
        parser = _parsers_cache[url_key]
    else:
        # Create a new parser
        parser = RobotsParser()
        success = parser.fetch_and_parse(url)
        
        if not success:
            # Don't flash here as it might not be in Flask context
            logger.warning("Could not fetch or parse robots.txt file. Proceeding with caution.")
            return {
                "success": False,
                "message": "Could not fetch or parse robots.txt"
            }
        
        # Manage cache size
        if len(_parsers_cache) >= _MAX_CACHE_SIZE:
            # Remove a random item
            try:
                _parsers_cache.pop(next(iter(_parsers_cache)))
            except:
                # Clear the entire cache if that fails
                _parsers_cache.clear()
        
        # Store parser in cache
        _parsers_cache[url_key] = parser
    
    parsed_url = urlparse(url)
    domain = parsed_url.netloc
    
    # Get robots.txt content for display
    robots_url = urljoin(f"{parsed_url.scheme}://{parsed_url.netloc}", '/robots.txt')
    robots_content = ""
    try:
        response = requests.get(robots_url, timeout=10)
        if response.status_code == 200:
            robots_content = response.text
    except:
        pass
    
    return {
        "success": True,
        "domain": domain,
        "robots_url": robots_url,
        "has_robots_txt": domain in parser.disallow_rules,
        "disallow_rules": parser.disallow_rules.get(domain, []),
        "allow_rules": parser.allow_rules.get(domain, []),
        "sitemaps": parser.sitemaps.get(domain, []),
        "crawl_delay": parser.crawl_delays.get(domain, None),
        "parser_id": url_key,  # Store the cache key for reference
        "content": robots_content[:1000] + ('...' if len(robots_content) > 1000 else ''),
        "total_lines": len(robots_content.split('\n')) if robots_content else 0
    }

# IMPORTANT: Add this to make it compatible with link_analyzer.py
# This exposes the parsers cache as an attribute of the analyze_robots_txt function
# so that link_analyzer.py can access it as analyze_robots_txt.parsers
def _get_parsers():
    """Getter for parsers cache"""
    return _parsers_cache

def _set_parsers(value):
    """Setter for parsers cache"""
    global _parsers_cache
    _parsers_cache = value

# Make parsers accessible as analyze_robots_txt.parsers
analyze_robots_txt.parsers = property(_get_parsers, _set_parsers)

# Alternative approach - directly set the attribute
# This is simpler and should work with the link_analyzer.py
analyze_robots_txt.parsers = _parsers_cache

