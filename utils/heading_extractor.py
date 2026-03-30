import requests
from scrapy.selector import Selector
from flask import flash

# Headers to mimic a real browser request (avoid 403 Forbidden errors)
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0',
}

def extract_headings_in_order(url):
    """
    Fetches a URL and extracts all <h1> through <h6> tags in the order
    they appear in the DOM, even if they are empty.
    """
    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=(90, 120))  # Increased: (connect, read) timeouts for AWS
        resp.raise_for_status()
    except Exception as e:
        flash(f"Error fetching URL: {e}", "danger")
        return []
    
    sel = Selector(text=resp.text)
    
    # One XPath to get h1..h6 in DOM order (including empty)
    heading_elements = sel.xpath('//h1|//h2|//h3|//h4|//h5|//h6')
    
    headings_in_order = []
    for elem in heading_elements:
        tag_name = elem.root.tag.lower()  # e.g. 'h2'
        level = int(tag_name[-1])         # e.g. '2'
        
        # Get combined text
        texts = elem.xpath('.//text()').getall()
        heading_text = " ".join(t.strip() for t in texts)  # might be empty
        
        headings_in_order.append({
            'tag': tag_name,       
            'level': level,        
            'text': heading_text,   
        })

    return headings_in_order
