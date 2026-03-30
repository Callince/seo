"""
Sitemap Analysis Utilities

This module combines your original functionality with improved error handling
and HTML detection capabilities.
"""

import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin
import logging
from datetime import datetime
import re
import gzip
from bs4 import BeautifulSoup

# Configure logging
logger = logging.getLogger(__name__)

def analyze_sitemap(url):
    try:
        sitemap_content = fetch_sitemap(url)
        
        # Remove XML declaration and trim any whitespace
        sitemap_content = re.sub(r'<\?xml[^>]+\?>', '', sitemap_content).strip()
        
        # Try parsing with different namespace handling
        try:
            root = ET.fromstring(sitemap_content)
        except ET.ParseError:
            # Try adding a default namespace if missing
            if 'xmlns:ns0' not in sitemap_content:
                sitemap_content = sitemap_content.replace('<sitemapindex', 
                    '<sitemapindex xmlns:ns0="http://www.sitemaps.org/schemas/sitemap/0.9">')
            
            root = ET.fromstring(sitemap_content)
        
        # Define namespace mapping
        ns = {
            'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9',
            'ns0': 'http://www.sitemaps.org/schemas/sitemap/0.9'
        }
        
        # Find sitemap elements with multiple namespace options
        sitemap_elements = (
            root.findall('.//sm:sitemap', ns) or 
            root.findall('.//ns0:sitemap', ns) or 
            root.findall('.//sitemap')
        )
        
        sitemaps = []
        for sitemap_elem in sitemap_elements:
            # Try finding loc with different namespace possibilities
            loc_elem = (
                sitemap_elem.find('./sm:loc', ns) or 
                sitemap_elem.find('./ns0:loc', ns) or 
                sitemap_elem.find('./loc')
            )
            
            if loc_elem is not None and loc_elem.text:
                sitemap_url = loc_elem.text.strip()
                sitemaps.append({'loc': sitemap_url})
        
        # Compile statistics
        stats = {
            'is_index': True,
            'total_sitemaps': len(sitemaps),
            'source_url': url
        }
        
        return sitemaps, stats
    
    except Exception as e:
        raise ValueError(f"Error analyzing sitemap: {str(e)}")

        
def is_html_content(content):
    """
    Check if the content appears to be HTML rather than XML.
    
    Args:
        content (str): The content to check
        
    Returns:
        bool: True if the content appears to be HTML, False otherwise
    """
    # Check for common HTML indicators
    html_indicators = [
        '<html', '<body', '<head', '<!doctype html', '<meta', '<title>',
        'charset=', '<div', '<script', '<style', '<link rel='
    ]
    
    content_lower = content.lower()
    for indicator in html_indicators:
        if indicator in content_lower:
            return True
    
    # If it has XML structure but no sitemap elements, it's probably not a sitemap
    if '<urlset' not in content_lower and '<sitemapindex' not in content_lower:
        if '<?xml' in content_lower or '<' in content:
            # It's XML-like but not a sitemap
            return True
    
    return False

def find_sitemap_links_in_html(html_content, base_url):
    """
    Find potential sitemap links in HTML content.
    
    Args:
        html_content (str): The HTML content to search
        base_url (str): The base URL for resolving relative links
        
    Returns:
        list: A list of dictionaries with sitemap URLs and descriptions
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    links = []
    
    # Common sitemap patterns in links
    sitemap_patterns = [
        r'sitemap\.xml$', r'sitemap_index\.xml$', r'wp-sitemap\.xml$',
        r'sitemap\.xml\.gz$', r'sitemap\d+\.xml$', r'sitemap-index\.xml$',
        r'sitemaps/', r'sitemap/'
    ]
    
    # Find all links
    for a_tag in soup.find_all('a', href=True):
        href = a_tag.get('href', '').strip()
        
        # Skip empty links
        if not href or href == '#' or href.startswith('javascript:'):
            continue
        
        # Create absolute URL if needed
        if not href.startswith(('http://', 'https://')):
            href = urljoin(base_url, href)
        
        # Check if link matches sitemap patterns
        is_sitemap = any(re.search(pattern, href, re.IGNORECASE) for pattern in sitemap_patterns)
        
        if is_sitemap:
            link_text = a_tag.get_text().strip()
            if not link_text:
                link_text = "Sitemap"
            
            links.append({
                'loc': href,
                'description': link_text,
                'is_discovered': True
            })
    
    # Check for robots.txt which often contains sitemap references
    domain = urlparse(base_url).netloc
    scheme = urlparse(base_url).scheme
    robots_url = f"{scheme}://{domain}/robots.txt"
    
    try:
        robots_response = requests.get(robots_url, timeout=10)
        if robots_response.status_code == 200:
            robots_content = robots_response.text
            sitemap_lines = re.findall(r'Sitemap:\s*(.+)$', robots_content, re.MULTILINE | re.IGNORECASE)
            
            for sitemap_url in sitemap_lines:
                sitemap_url = sitemap_url.strip()
                if sitemap_url:
                    links.append({
                        'loc': sitemap_url,
                        'description': "Found in robots.txt",
                        'is_discovered': True
                    })
    except Exception as e:
        logger.warning(f"Could not fetch robots.txt: {str(e)}")
    
    # Add common sitemap locations if none found
    if not links:
        common_locations = [
            f"{scheme}://{domain}/sitemap.xml",
            f"{scheme}://{domain}/sitemap_index.xml",
            f"{scheme}://{domain}/wp-sitemap.xml"
        ]
        
        for url in common_locations:
            links.append({
                'loc': url,
                'description': "Common sitemap location",
                'is_discovered': True,
                'is_suggestion': True
            })
    
    return links

def fetch_sitemap(url):
    """
    Fetch the content of a sitemap URL, handling compression if needed.
    
    Args:
        url (str): The URL of the sitemap to fetch
        
    Returns:
        str: The XML content of the sitemap
        
    Raises:
        ValueError: If the URL cannot be fetched
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; YourWebAnalyzer/1.0; +http://yourwebsite.com/bot)'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise ValueError(f"Failed to fetch sitemap: {str(e)}")
    
    content = response.content
    
    # Check if the content is actually gzipped
    # Try to decompress if it looks like gzipped content
    if (url.endswith('.gz') or response.headers.get('Content-Encoding') == 'gzip'):
        # Check if content starts with the gzip magic number (b'\x1f\x8b')
        if content.startswith(b'\x1f\x8b'):
            try:
                return gzip.decompress(content).decode('utf-8')
            except Exception as e:
                logger.warning(f"Failed to decompress gzipped content: {str(e)}")
                # Fall back to treating it as regular content
        else:
            logger.warning("Content marked as gzipped but doesn't have gzip header")
            # Content isn't actually gzipped despite filename or header suggesting it is
    
    # If we get here, either the content is not gzipped or decompression failed
    try:
        # Try to decode as UTF-8
        return content.decode('utf-8')
    except UnicodeDecodeError:
        # If UTF-8 fails, try other encodings
        try:
            return content.decode('latin-1')
        except Exception as e:
            raise ValueError(f"Failed to decode sitemap content: {str(e)}")

def process_sitemap(root, source_url, ns, max_urls=1000):
    """
    Process a regular sitemap and extract URLs and metadata.
    
    Args:
        root (ET.Element): The XML root element
        source_url (str): The URL of the sitemap
        ns (dict): Namespace dictionary
        max_urls (int): Maximum number of URLs to extract
        
    Returns:
        tuple: (urls, stats) where urls is a list of dictionaries containing
               URL data and stats is a dictionary of statistics
    """
    urls = []
    total_count = 0
    has_lastmod = 0
    has_priority = 0
    has_changefreq = 0
    has_images = 0
    has_video = 0
    has_alternates = 0
    
    # Use namespace-aware method to find all URL elements
    url_elements = root.findall('.//sm:url', ns) or root.findall('.//url')
    
    for url_elem in url_elements:
        if len(urls) >= max_urls:
            break
            
        total_count += 1
        url_data = {}
        
        # Find elements with or without namespace
        loc_elem = (url_elem.find('./sm:loc', ns) or url_elem.find('./loc'))
        lastmod_elem = (url_elem.find('./sm:lastmod', ns) or url_elem.find('./lastmod'))
        changefreq_elem = (url_elem.find('./sm:changefreq', ns) or url_elem.find('./changefreq'))
        priority_elem = (url_elem.find('./sm:priority', ns) or url_elem.find('./priority'))
        
        # Get URL location (required)
        if loc_elem is not None and loc_elem.text:
            url_data['loc'] = loc_elem.text.strip()
        else:
            continue  # Skip URLs without location
        
        # Parse URL to extract domain and path
        parsed_url = urlparse(url_data['loc'])
        url_data['domain'] = parsed_url.netloc
        url_data['path'] = parsed_url.path
        
        # Get last modified date
        if lastmod_elem is not None and lastmod_elem.text:
            lastmod = lastmod_elem.text.strip()
            url_data['lastmod'] = lastmod
            
            # Format lastmod date if present
            formatted_lastmod = None
            try:
                # Try different date formats
                for fmt in ('%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%d'):
                    try:
                        parsed_date = datetime.strptime(lastmod, fmt)
                        formatted_lastmod = parsed_date.strftime('%Y-%m-%d %H:%M:%S')
                        break
                    except ValueError:
                        continue
                if formatted_lastmod:
                    url_data['formatted_lastmod'] = formatted_lastmod
            except Exception as e:
                logger.warning(f"Could not parse lastmod date: {lastmod} - {str(e)}")
                
            has_lastmod += 1
        
        # Get change frequency
        if changefreq_elem is not None and changefreq_elem.text:
            url_data['changefreq'] = changefreq_elem.text.strip()
            has_changefreq += 1
        
        # Get priority
        if priority_elem is not None and priority_elem.text:
            url_data['priority'] = priority_elem.text.strip()
            has_priority += 1
        
        # Check for images
        image_elements = url_elem.findall('./image:image', ns) or url_elem.findall('./image')
        if image_elements:
            has_images += 1
            url_data['image_count'] = len(image_elements)
        
        # Check for videos
        video_elements = url_elem.findall('./video:video', ns) or url_elem.findall('./video')
        if video_elements:
            has_video += 1
            url_data['video_count'] = len(video_elements)
            
        # Extract alternate language versions (XHTML namespace)
        alternates = []
        for alternate_elem in url_elem.findall('./xhtml:link', ns):
            if alternate_elem.get('rel') == 'alternate':
                alternates.append({
                    'href': alternate_elem.get('href'),
                    'hreflang': alternate_elem.get('hreflang')
                })
                
        if alternates:
            url_data['alternates'] = alternates
            has_alternates += 1
        
        urls.append(url_data)
    
    # Check if we actually found any URLs
    if total_count == 0:
        # No URLs found, maybe this isn't a sitemap or has a different structure
        # Show a sample of the root to help debugging
        root_str = ET.tostring(root, encoding='unicode')
        sample = root_str[:500] + '...' if len(root_str) > 500 else root_str
        raise ValueError(f"No URLs found in the sitemap. Content may not be a valid sitemap. Sample: {sample}")
    
    # Compile statistics
    stats = {
        'total_urls': total_count,
        'displayed_urls': len(urls),
        'has_lastmod_percent': round((has_lastmod / total_count * 100) if total_count > 0 else 0, 1),
        'has_priority_percent': round((has_priority / total_count * 100) if total_count > 0 else 0, 1),
        'has_changefreq_percent': round((has_changefreq / total_count * 100) if total_count > 0 else 0, 1),
        'has_alternates_percent': round((has_alternates / total_count * 100) if total_count > 0 else 0, 1),
        'has_images_count': has_images,
        'has_video_count': has_video,
        'source_url': source_url
    }
    
    return urls, stats

def process_sitemap_index(root, source_url, ns, max_urls=1000):
    """
    Process a sitemap index file and extract all child sitemaps.
    
    Args:
        root (ET.Element): The XML root element
        source_url (str): The URL of the sitemap index
        ns (dict): Namespace dictionary
        max_urls (int): Maximum number of URLs to extract from child sitemaps
        
    Returns:
        tuple: (sitemaps, stats) where sitemaps is a list of dictionaries
               containing sitemap data and stats is a dictionary of statistics
    """
    sitemaps = []
    all_urls = []
    processed_count = 0
    
    # Find all sitemap elements (with or without namespace)
    sitemap_elements = root.findall('.//sm:sitemap', ns) or root.findall('.//sitemap')
    
    for sitemap_elem in sitemap_elements:
        sitemap_data = {}
        
        # Find location element (with or without namespace)
        loc_elem = (sitemap_elem.find('./sm:loc', ns) or sitemap_elem.find('./loc'))
        lastmod_elem = (sitemap_elem.find('./sm:lastmod', ns) or sitemap_elem.find('./lastmod'))
        
        if loc_elem is not None and loc_elem.text:
            sitemap_data['loc'] = loc_elem.text.strip()
        else:
            continue  # Skip sitemaps without location
        
        if lastmod_elem is not None and lastmod_elem.text:
            sitemap_data['lastmod'] = lastmod_elem.text.strip()
            
            # Format lastmod date
            try:
                # Try different date formats
                for fmt in ('%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%d'):
                    try:
                        parsed_date = datetime.strptime(sitemap_data['lastmod'], fmt)
                        sitemap_data['formatted_lastmod'] = parsed_date.strftime('%Y-%m-%d %H:%M:%S')
                        break
                    except ValueError:
                        continue
            except Exception as e:
                logger.warning(f"Could not parse lastmod date: {sitemap_data['lastmod']} - {str(e)}")
        
        # Option 1: For simple listing of sitemaps without parsing them
        sitemaps.append(sitemap_data)
        
        # Option 2: For recursively parsing each child sitemap (commented out to avoid long processing)
        # Note: Uncomment this if you want to parse all child sitemaps automatically
        '''
        # Parse the child sitemap to get URL counts
        try:
            processed_count += 1
            child_sitemap_url = sitemap_data['loc']
            child_urls, _ = analyze_sitemap(child_sitemap_url, max_urls=max_urls - len(all_urls))
            sitemap_data['urls_count'] = len(child_urls)
            sitemap_data['success'] = True
            all_urls.extend(child_urls)
            
            # Stop if we've reached the max URLs
            if len(all_urls) >= max_urls:
                break
        except Exception as e:
            sitemap_data['error'] = str(e)
            sitemap_data['success'] = False
            sitemap_data['urls_count'] = 0
        '''
    
    # Check if we actually found any sitemaps
    if len(sitemaps) == 0:
        # No sitemaps found, maybe this isn't a sitemap index
        # Try to process it as a regular sitemap as a fallback
        try:
            return process_sitemap(root, source_url, ns, max_urls)
        except ValueError:
            # If that also fails, report the original error
            root_str = ET.tostring(root, encoding='unicode')
            sample = root_str[:500] + '...' if len(root_str) > 500 else root_str
            raise ValueError(f"No sitemaps found in the sitemap index. Content may not be a valid sitemap index. Sample: {sample}")
    
    # Compile statistics
    stats = {
        'is_index': True,
        'total_sitemaps': len(sitemaps),
        'processed_sitemaps': processed_count,
        'source_url': source_url
    }
    
    # If we parsed child sitemaps (Option 2), include URL stats
    if processed_count > 0:
        stats['total_urls'] = len(all_urls)
    
    return sitemaps, stats