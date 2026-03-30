import asyncio
import json
import re
import os
import csv
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs, urlencode
import aiohttp
import nest_asyncio
from collections import defaultdict
import logging

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

# Fix for "aiodns needs a SelectorEventLoop on Windows"
if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

###############################################################################
# Improved regex patterns for better link extraction
###############################################################################
LINK_PATTERNS = [
    re.compile(r'href\s*=\s*[\'"]([^\'"]+)[\'"]', re.IGNORECASE),
    re.compile(r'href\s*=\s*([^\s>]+)', re.IGNORECASE),  # href without quotes
    re.compile(r'src\s*=\s*[\'"]([^\'"]+)[\'"]', re.IGNORECASE),  # src attributes for some dynamic content
]

# More comprehensive unwanted patterns
UNWANTED_PATTERNS = [
    # File extensions
    r'\.(jpg|jpeg|png|gif|bmp|webp|svg|ico|css|js|pdf|doc|docx|xls|xlsx|zip|rar|tar|gz)(\?.*)?$',
    # Common unwanted paths
    r'/wp-admin/',
    r'/wp-content/uploads/',
    r'/admin/',
    r'/login',
    r'/logout',
    r'/register',
    r'mailto:',
    r'tel:',
    r'ftp:',
    r'javascript:',
    r'#',  # Pure anchors
    # Social media and external widgets
    r'facebook\.com',
    r'twitter\.com',
    r'linkedin\.com',
    r'instagram\.com',
    r'youtube\.com',
    r'google\.com/maps',
]

UNWANTED_REGEX = re.compile('|'.join(UNWANTED_PATTERNS), re.IGNORECASE)

def normalize_url(url, base_url=None):
    """
    Comprehensive URL normalization to avoid duplicates and clean URLs.
    """
    if not url or not url.strip():
        return None
    
    url = url.strip()
    
    # Handle relative URLs
    if base_url and not url.startswith(('http://', 'https://', '//')):
        url = urljoin(base_url, url)
    
    # Parse URL
    parsed = urlparse(url)
    
    # Skip non-HTTP(S) URLs
    if parsed.scheme not in ('http', 'https'):
        return None
    
    # Normalize domain (lowercase)
    netloc = parsed.netloc.lower()
    
    # Remove default ports
    if netloc.endswith(':80') and parsed.scheme == 'http':
        netloc = netloc[:-3]
    elif netloc.endswith(':443') and parsed.scheme == 'https':
        netloc = netloc[:-4]
    
    # Normalize path
    path = parsed.path.rstrip('/')
    if not path:
        path = '/'
    
    # Sort query parameters for consistency
    query = ''
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        sorted_params = sorted(params.items())
        query = urlencode(sorted_params, doseq=True)
    
    # Reconstruct URL without fragment
    normalized = urlunparse((
        parsed.scheme,
        netloc,
        path,
        parsed.params,
        query,
        ''  # Remove fragment
    ))
    
    return normalized

def is_unwanted_url(url):
    """Enhanced unwanted URL detection."""
    if not url:
        return True
    
    # Check against unwanted patterns
    if UNWANTED_REGEX.search(url):
        return True
    
    # Check for very long URLs (potential spam/malformed)
    if len(url) > 2000:
        return True
    
    # Check for suspicious patterns
    suspicious_patterns = [
        r'\.\./',  # Directory traversal
        r'[<>"\']',  # Potential XSS
        r'\s',  # URLs with spaces
    ]
    
    for pattern in suspicious_patterns:
        if re.search(pattern, url):
            return True
    
    return False

def extract_links_from_html(html, base_url):
    """
    Enhanced link extraction from HTML content.
    """
    if not html:
        return set()
    
    all_links = set()
    
    # Extract using multiple regex patterns
    for pattern in LINK_PATTERNS:
        matches = pattern.findall(html)
        all_links.update(matches)
    
    # Normalize and filter links
    normalized_links = set()
    for link in all_links:
        # Skip obviously invalid links
        if not link or link.startswith(('javascript:', 'mailto:', 'tel:', '#')):
            continue
        
        # Normalize the URL
        normalized = normalize_url(link, base_url)
        if normalized and not is_unwanted_url(normalized):
            normalized_links.add(normalized)
    
    return normalized_links

def add_to_tree(tree, url, status_codes):
    """Recursively adds a URL to the nested dictionary tree with status information."""
    parsed = urlparse(url)
    parts = [part for part in parsed.path.strip('/').split('/') if part]
    domain = parsed.netloc

    # If the domain doesn't exist in the tree, add it as a node.
    if domain not in tree:
        domain_url = f"{parsed.scheme}://{domain}"
        domain_status = status_codes.get(domain_url, {}).get("status", "Unknown")
        tree[domain] = {
            "name": domain,
            "url": domain_url,
            "status": domain_status,
            "children": {}
        }
    
    node = tree[domain]["children"]

    # Build the tree recursively for each part of the path.
    for index, part in enumerate(parts):
        # Create a full URL for this node
        path = "/".join(parts[:index+1])
        full_url = f"{parsed.scheme}://{domain}/{path}"
        if part not in node:
            node[part] = {
                "name": part,
                "url": full_url,
                "status": status_codes.get(full_url, {}).get("status", "Unknown"),
                "children": {}
            }
        node = node[part]["children"]

def build_tree(links, status_codes):
    """Builds a nested dictionary tree from a set of URLs and adds status for each node."""
    tree = {}
    for link in links:
        add_to_tree(tree, link, status_codes)
    return tree

async def fetch_page(session, url, timeout=20, max_retries=1):
    """ULTRA-OPTIMIZED: Fetch page with minimal timeout and retries for fastest crawling."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0',
    }

    # ULTRA-OPTIMIZED: Minimal timeout for fastest failures (was 30s, now 20s)
    request_timeout = aiohttp.ClientTimeout(total=timeout, connect=8, sock_read=15)

    # Retry logic for transient failures with special handling for rate limiting
    for attempt in range(max_retries):
        try:
            async with session.get(url, timeout=request_timeout, headers=headers, allow_redirects=True) as resp:
                # Handle different content types
                content_type = resp.headers.get('content-type', '').lower()
                if 'text/html' not in content_type and 'application/xhtml' not in content_type:
                    return url, resp.status, "", f"Non-HTML content: {content_type}"

                # Special handling for rate limiting (HTTP 429)
                if resp.status == 429:
                    if attempt < max_retries - 1:
                        wait_time = min(60, 10 * (2 ** attempt))  # Cap at 60 seconds
                        logger.warning(f"Rate limited (429) for {url}, waiting {wait_time}s before retry {attempt + 2}/{max_retries}")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"Rate limited (429) for {url} after {max_retries} attempts")
                        return url, resp.status, "", f"HTTP Error {resp.status} - Rate Limited"

                # Handle other 4xx/5xx errors
                if resp.status >= 400:
                    logger.warning(f"HTTP {resp.status} for {url}")
                    return url, resp.status, "", f"HTTP Error {resp.status}"

                try:
                    html = await resp.text(encoding='utf-8')
                except UnicodeDecodeError:
                    html = await resp.text(encoding='latin-1', errors='ignore')

                # Success!
                if html:
                    logger.info(f"Successfully fetched {url} (status: {resp.status}, size: {len(html)} bytes)")
                return url, resp.status, html, None

        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning(f"Timeout on attempt {attempt + 1}/{max_retries} for {url}, retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue
            return url, None, "", "TimeoutError"
        except aiohttp.ClientError as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning(f"Client error on attempt {attempt + 1}/{max_retries} for {url}: {str(e)}, retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue
            return url, None, "", f"ClientError: {str(e)}"
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning(f"Unexpected error on attempt {attempt + 1}/{max_retries} for {url}: {str(e)}, retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue
            return url, None, "", f"UnexpectedError: {str(e)}"

    return url, None, "", "Max retries exceeded"

async def extract_links(session, url, base_domain, visited):
    """Fetch a URL, parse links, and return sets of home-domain links and other-domain links."""
    url, status, html, error = await fetch_page(session, url)
    
    if error or not html:
        logger.warning(f"Failed to fetch {url}: {error}")
        return url, status, error, set(), set()

    # Extract all links from HTML
    all_links = extract_links_from_html(html, url)
    
    # Separate home domain links from external domain links
    home_links = set()
    other_links = set()
    
    for link in all_links:
        parsed_link = urlparse(link)
        if parsed_link.netloc == base_domain:
            home_links.add(link)
        else:
            other_links.add(link)
    
    logger.info(f"Extracted {len(home_links)} home links and {len(other_links)} external links from {url}")
    return url, status, error, home_links, other_links

async def worker(session, queue, visited, url_status, home_links, external_links, base_domain, stats, delay=0.05):
    """ULTRA-OPTIMIZED worker function to process URLs with minimal rate limiting."""
    while True:
        url = await queue.get()
        if url in visited:
            queue.task_done()
            continue

        visited.add(url)
        stats['processed'] += 1

        # Minimal delay to avoid rate limiting (reduced from 0.1s to 0.05s)
        # Only delay if we've made requests before
        if stats.get('last_request_time', 0) > 0:
            time_since_last = asyncio.get_event_loop().time() - stats.get('last_request_time', 0)
            if time_since_last < delay:
                wait_time = delay - time_since_last
                await asyncio.sleep(wait_time)

        stats['last_request_time'] = asyncio.get_event_loop().time()

        url, status, error, new_home_links, new_other_links = await extract_links(
            session, url, base_domain, visited
        )

        # Store the status code
        url_status[url] = {
            "status": status if status else "not connected",
            "error": error or "No error",
        }

        # Update link sets
        home_links.update(new_home_links)
        external_links.update(new_other_links)

        # Enqueue newly found home-domain links for further crawling
        new_urls_added = 0
        for link in new_home_links:
            if link not in visited:
                await queue.put(link)
                new_urls_added += 1

        stats['new_urls_found'] += new_urls_added
        logger.info(f"Processed: {stats['processed']}, Queue size: {queue.qsize()}, New URLs: {new_urls_added}")

        queue.task_done()

async def crawl(start_url, max_concurrency=30, max_pages=500, delay_between_requests=0.05, progress_callback=None):
    """
    ULTRA-OPTIMIZED asynchronous web crawler - MAXIMUM SPEED.
    - Increased concurrency from 20 to 30 for 1.5x faster crawling
    - Reduced delay from 0.1s to 0.05s for 2x faster crawling
    - Max_pages=500 for reasonable completion time
    - Aggressive timeout settings for faster response
    - progress_callback: Optional function to call with progress updates (percentage)
    """
    visited = set()
    url_status = {}
    base_domain = urlparse(start_url).netloc
    home_links = set()
    external_links = set()
    stats = {'processed': 0, 'new_urls_found': 0, 'last_request_time': 0}

    # Normalize start URL
    start_url = normalize_url(start_url)
    if not start_url:
        raise ValueError("Invalid start URL")

    queue = asyncio.Queue()
    await queue.put(start_url)

    # ULTRA-OPTIMIZED session configuration for MAXIMUM SPEED
    # Very aggressive timeouts for faster failures, very high concurrency
    timeout = aiohttp.ClientTimeout(total=30, connect=8, sock_read=20)  # Reduced from 45/10/30 for speed
    connector = aiohttp.TCPConnector(
        limit=max_concurrency * 4,  # Allow even more total connections (was *3)
        limit_per_host=12,  # Increased from 8 to 12 for same domain
        ttl_dns_cache=300,
        use_dns_cache=True,
        force_close=False,
        enable_cleanup_closed=True,
    )

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (compatible; WebCrawler/1.0)"}
    ) as session:

        workers = [
            asyncio.create_task(
                worker(session, queue, visited, url_status, home_links, external_links, base_domain, stats, delay_between_requests)
            )
            for _ in range(max_concurrency)
        ]

        # Monitor progress and apply limits
        last_progress = 10  # Start from 10% (set in main_crawl)
        while not queue.empty() and stats['processed'] < max_pages:
            await asyncio.sleep(1)  # Brief pause to allow processing

            # Calculate progress (10% to 85% based on pages processed)
            progress_pct = min(10 + int((stats['processed'] / max_pages) * 75), 85)

            # Report progress if callback provided and progress changed
            if progress_callback and progress_pct > last_progress:
                await progress_callback(progress_pct)
                last_progress = progress_pct

            if stats['processed'] % 50 == 0 and stats['processed'] > 0:
                logger.info(f"Progress: {stats['processed']} pages processed, {len(visited)} URLs visited, {progress_pct}%")

        await queue.join()  # Wait until all tasks are done

        for w in workers:
            w.cancel()

    logger.info(f"Crawling completed: {stats['processed']} pages processed, {len(home_links)} home links, {len(external_links)} external links")
    return url_status, home_links, external_links

def save_to_json(url_status, home_links, other_links, domain):
    """Saves crawled data as JSON and also prepares a CSV download using the provided domain."""
    
    if not domain:
        raise ValueError("A valid domain must be provided")
    
    # Build tree structure for JSON storage
    home_tree = build_tree(home_links, url_status)
    other_tree = build_tree(other_links, url_status)

    # Calculate statistics
    total_links = len(home_links) + len(other_links)
    successful_crawls = sum(1 for status_info in url_status.values() 
                           if isinstance(status_info.get('status'), int) and 200 <= status_info['status'] < 300)
    
    data = {
        "domain": domain,
        "statistics": {
            "total_links": total_links,
            "home_links": len(home_links),
            "external_links": len(other_links),
            "successful_crawls": successful_crawls,
            "crawl_success_rate": f"{(successful_crawls / len(url_status) * 100):.2f}%" if url_status else "0%"
        },
        "status_codes": url_status,
        "home_links": home_tree,
        "other_links": other_tree,
    }

    # Prepare CSV data
    csv_data = []
    for link in home_links:
        status_info = url_status.get(link, {})
        csv_data.append({
            "Link": link,
            "Status": status_info.get("status", "Unknown"),
            "Error": status_info.get("error", ""),
            "Type": "Home"
        })
    for link in other_links:
        status_info = url_status.get(link, {})
        csv_data.append({
            "Link": link,
            "Status": status_info.get("status", "Unknown"),
            "Error": status_info.get("error", ""),
            "Type": "External"
        })

    os.makedirs("crawled_data", exist_ok=True)
    
    # FIXED: Check if domain is a UUID (job_id) vs actual domain
    import re
    
    # UUID pattern: 8-4-4-4-12 hexadecimal digits
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    
    if re.match(uuid_pattern, domain, re.IGNORECASE):
        # This is a job_id (UUID), don't add timestamp
        json_path = f"crawled_data/crawl_{domain}.json"
        csv_path = f"crawled_data/crawl_{domain}.csv"
        print(f"Using job_id format - saving without timestamp")
    else:
        # This is a regular domain, add timestamp for uniqueness
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = f"crawled_data/crawl_{domain}_{timestamp}.json"
        csv_path = f"crawled_data/crawl_{domain}_{timestamp}.csv"
        print(f"Using domain format - saving with timestamp")

    print(f"Saving JSON to: {json_path}")
    print(f"Saving CSV to: {csv_path}")

    # Save the data as JSON
    with open(json_path, 'w', encoding='utf-8') as json_file:
        json.dump(data, json_file, indent=4, ensure_ascii=False)

    # Save the data as CSV
    with open(csv_path, 'w', newline='', encoding='utf-8') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["Link", "Status", "Error", "Type"])
        writer.writeheader()
        writer.writerows(csv_data)

    return json_path, csv_path

###############################################################################
# Example usage:
if __name__ == "__main__":
    start_url = "https://example.com"
    url_status, home_links, other_links = asyncio.run(crawl(start_url, max_concurrency=30, max_pages=500))
    domain = urlparse(start_url).netloc
    json_path, csv_path = save_to_json(url_status, home_links, other_links, domain)
    print(f"Crawling completed! Data saved to {json_path} and {csv_path}")
###############################################################################
