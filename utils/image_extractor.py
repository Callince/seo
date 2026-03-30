import requests
import os
import time
import logging
import re
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from scrapy.selector import Selector
from flask import flash
from PIL import Image
from io import BytesIO
from functools import lru_cache

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# Configure session with connection pooling - increased pool sizes for better performance
session = requests.Session()
session.headers.update(BROWSER_HEADERS)  # Apply browser headers to all session requests
adapter = requests.adapters.HTTPAdapter(
    pool_connections=25,  # Increased for better performance
    pool_maxsize=50,      # Increased for better performance
    max_retries=requests.adapters.Retry(
        total=3,
        backoff_factor=1,  # ADDED: Exponential backoff
        status_forcelist=[500, 502, 503, 504],  # ADDED: Retry on these status codes
        allowed_methods=["GET"]  # ADDED: Only retry GET requests
    )
)
session.mount('http://', adapter)
session.mount('https://', adapter)

@lru_cache(maxsize=300)  # Increased cache size for better performance
def get_image_metadata(img_url, base_url, timeout=90):
    """
    Get metadata for a single image with caching for efficiency.
    Returns error information when image fails to load instead of skipping.
    """
    try:
        # Handle protocol-relative URLs (starting with "//")
        if img_url.startswith('//'):
            base_scheme = urlparse(base_url).scheme or 'http'
            img_url = f"{base_scheme}:{img_url}"
        
        absolute_img_url = urljoin(base_url, img_url)
        parsed = urlparse(absolute_img_url)
        file_extension = os.path.splitext(parsed.path)[-1].lower() or 'Unknown'
        
        # Download the image with timeout
        start_time = time.time()
        img_resp = session.get(absolute_img_url, stream=True, timeout=(90, timeout))  # Increased connect timeout
        img_resp.raise_for_status()
        
        # Read the full content
        img_resp.raw.decode_content = True
        content = img_resp.raw.read()
        file_size_kb = len(content) / 1024.0
        download_time = time.time() - start_time

        # Get additional metadata
        content_type = img_resp.headers.get('Content-Type', 'Unknown')
        last_modified = img_resp.headers.get('Last-Modified', 'Unknown')
        
        # Open the image to determine its resolution
        try:
            with Image.open(BytesIO(content)) as im:
                resolution = f"{im.width}x{im.height}"
                image_format = im.format
                color_mode = im.mode
                width = im.width
                height = im.height
        except Exception as e:
            # Handle corrupt images that can't be processed by PIL
            # Only log if it's not a common SVG issue
            if 'cannot identify image file' not in str(e) or not absolute_img_url.lower().endswith('.svg'):
                logger.warning(f"Image format error for {absolute_img_url}: {e}")
            resolution = "Unknown"
            image_format = "Unknown"
            color_mode = "Unknown"
            width = 0
            height = 0
        
        return {
            'url': absolute_img_url,
            'file_extension': file_extension,
            'content_type': content_type,
            'file_size': f"{file_size_kb:.2f} KB",
            'raw_size': file_size_kb,
            'resolution': resolution,
            'width': width,
            'height': height,
            'format': image_format,
            'color_mode': color_mode,
            'last_modified': last_modified,
            'download_time': f"{download_time:.2f}s",
            'status': 'success'
        }
    except requests.RequestException as e:
        # Only log significant errors, not 404s which are common and expected
        error_str = str(e)
        if '404' not in error_str and 'Not Found' not in error_str:
            logger.warning(f"Request error for {img_url}: {e}")
        return {
            'url': urljoin(base_url, img_url),
            'status': 'error',
            'error_message': f"Error loading image: {str(e)}",
            'error_type': 'request_error',
            'file_extension': os.path.splitext(urlparse(img_url).path)[-1].lower() or 'Unknown'
        }
    except Exception as e:
        logger.error(f"Error processing {img_url}: {e}", exc_info=True)
        return {
            'url': urljoin(base_url, img_url),
            'status': 'error',
            'error_message': f"Error loading image: {str(e)}",
            'error_type': 'processing_error',
            'file_extension': os.path.splitext(urlparse(img_url).path)[-1].lower() or 'Unknown'
        }

def parse_srcset(srcset):
    """
    Parse srcset attribute to find all image variations, not just the highest resolution.
    Returns a list of image URLs found in the srcset.
    """
    if not srcset:
        return []
    
    img_urls = []
    
    # Split the srcset by commas
    items = [item.strip() for item in srcset.split(',') if item.strip()]
    
    for item in items:
        parts = item.rsplit(' ', 1)  # Split from right to handle URLs with spaces
        if len(parts) < 2:
            # Handle cases where there's no descriptor
            url = item.strip()
            if url:
                img_urls.append(url)
            continue
            
        url, _ = parts
        url = url.strip()
        if url:
            img_urls.append(url)
    
    # Get the highest resolution image (for backward compatibility)
    best_img_url = None
    best_width = 0
    best_density = 0
    
    for item in items:
        parts = item.rsplit(' ', 1)
        if len(parts) < 2:
            continue
            
        url, descriptor = parts
        url = url.strip()
        descriptor = descriptor.strip()
        
        # Handle width descriptor (e.g., "420w")
        if descriptor.endswith('w'):
            try:
                width = int(descriptor[:-1])
                if width > best_width:
                    best_width = width
                    best_img_url = url
            except ValueError:
                continue
        
        # Handle pixel density descriptor (e.g., "2x")
        elif descriptor.endswith('x'):
            try:
                density = float(descriptor[:-1])
                if density > best_density and not best_width:  # Width takes precedence
                    best_density = density
                    best_img_url = url
            except ValueError:
                continue
    
    # Return both the best image URL and all URLs from the srcset
    return best_img_url if best_img_url else (img_urls[0] if img_urls else None), img_urls

def extract_images_from_css(css_content, base_url):
    """
    Extract image URLs from CSS content using regex.
    Enhanced to catch more image patterns.
    """
    urls = []
    # Match url() patterns in CSS - more comprehensive pattern
    url_pattern = r'url\([\'"]?([^\'")]+\.(?:jpg|jpeg|png|gif|webp|svg|bmp|ico|tiff|avif)(?:\?[^\'")*]*)?)[\'"]?\)'
    for match in re.finditer(url_pattern, css_content, re.IGNORECASE):
        url = match.group(1)
        # Skip data URLs and SVG
        if not url.startswith('data:') and not url.startswith('#'):
            urls.append(url)
    
    # Also find image URLs in CSS rules like 'background-image: url(...)'
    bg_pattern = r'background(?:-image)?\s*:\s*url\([\'"]?([^\'")]+)[\'"]?\)'
    for match in re.finditer(bg_pattern, css_content, re.IGNORECASE):
        url = match.group(1)
        if not url.startswith('data:') and not url.startswith('#'):
            if not any(url.endswith(ext) for ext in ['.css', '.js', '.html']):
                urls.append(url)
    
    return urls

def extract_images_from_js(js_content, base_url):
    """
    Extract potential image URLs from JavaScript content.
    Enhanced to catch more patterns and formats.
    """
    urls = []
    # More comprehensive combined pattern
    combined_pattern = r'[\'"]([^\'\"]*\.(?:jpg|jpeg|png|gif|webp|svg|bmp|ico|tiff|avif)(?:\?[^\'\"]*)?)[\'\"]|[\'\"]([^\'\"]*\/(?:images|img|photos|pics|media|assets|uploads)\/[^\'\"]+)[\'\"]'
    
    for match in re.finditer(combined_pattern, js_content, re.IGNORECASE):
        url = match.group(1) or match.group(2)
        if url and not url.startswith('data:'):
            # Filter out some common false positives
            if not any(url.endswith(ext) for ext in ['.js', '.css', '.html', '.php']):
                urls.append(url)
    
    # Also look for image URLs in JS objects
    js_object_pattern = r'[\'\"](?:src|url|image|img|thumbnail)[\'\"]:\s*[\'\"]([^\'\"]+\.(?:jpg|jpeg|png|gif|webp|svg|bmp|ico|tiff|avif)[^\'\"]*)'
    for match in re.finditer(js_object_pattern, js_content, re.IGNORECASE):
        url = match.group(1)
        if url and not url.startswith('data:'):
            urls.append(url)
    
    return urls

def find_background_images(html_content, base_url):
    """
    Find background images in inline styles and style elements.
    Enhanced to catch more patterns.
    """
    urls = []
    
    # Extract inline styles with background images - more comprehensive pattern
    inline_bg_pattern = r'style=[\'"].*?background(?:-image)?\s*:\s*url\([\'"]?([^\'")]+)[\'"]?\).*?[\'"]'
    for match in re.finditer(inline_bg_pattern, html_content, re.IGNORECASE):
        url = match.group(1)
        if not url.startswith('data:') and not url.startswith('#'):
            urls.append(url)
    
    # Extract style elements
    style_pattern = r'<style[^>]*>(.*?)</style>'
    for match in re.finditer(style_pattern, html_content, re.DOTALL | re.IGNORECASE):
        style_content = match.group(1)
        urls.extend(extract_images_from_css(style_content, base_url))
    
    return urls

def extract_images(url, max_workers=12, timeout=90):  # Increased timeout for AWS/slow connections
    """
    Enhanced image extraction that finds images from multiple sources with improved performance.
    Includes error information for failed images instead of skipping them.
    """
    image_urls_seen = set()  # To avoid duplicates
    potential_images = []    # Store potential images before processing
    
    try:
        logger.info(f"Fetching URL: {url}")
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        html_content = resp.text
    except requests.RequestException as e:
        error_msg = f"Error fetching URL: {e}"
        logger.error(error_msg)
        flash(error_msg, "danger")
        return [{'error': error_msg, 'status': 'error'}]
    
    sel = Selector(text=html_content)
    
    # Gather all potential image sources in one pass
    
    # 1. Find all <img> elements
    for img in sel.xpath('//img'):
        img_url = None
        srcset_urls = []
        
        # Check for srcset
        srcset = img.xpath('./@srcset').get() or img.xpath('./@data-srcset').get()
        if srcset:
            best_srcset_url, all_srcset_urls = parse_srcset(srcset)
            if best_srcset_url:
                img_url = best_srcset_url
            srcset_urls.extend(all_srcset_urls)
        
        # Check various attributes for the image URL
        if not img_url:
            # Try these attributes in order of preference
            for attr in [
                '@src', '@data-src', '@data-original', '@data-lazy-src', 
                '@data-lazy', '@data-original-src', '@data-fallback-src',
                '@data-delayed-src', '@data-img', '@data-full-src',
                '@data-srcset-webp', '@data-thumb', '@loading-src',
                '@data-high-res-src', '@data-high-resolution'
            ]:
                img_url = img.xpath(f'./{attr}').get()
                if img_url:
                    break
        
        if not img_url and not srcset_urls:
            continue
        
        alt_text = img.xpath('./@alt').get() or 'None'
        title = img.xpath('./@title').get() or alt_text
        
        # Add main image URL
        if img_url and not img_url.startswith('data:'):
            potential_images.append({
                'img_url': img_url,
                'alt_text': alt_text,
                'title': title,
                'source_type': 'img_tag'
            })
        
        # Add all srcset URLs as separate potential images
        for srcset_url in srcset_urls:
            if srcset_url and not srcset_url.startswith('data:'):
                potential_images.append({
                    'img_url': srcset_url,
                    'alt_text': alt_text,
                    'title': f"{title} (srcset variant)",
                    'source_type': 'img_srcset'
                })
    
    # 2. Find all <picture>/<source> elements
    for source in sel.xpath('//picture/source | //source[@srcset]'):
        srcset = source.xpath('./@srcset').get()
        if not srcset:
            continue
            
        best_src_url, all_src_urls = parse_srcset(srcset)
        
        alt_text = source.xpath('../img/@alt').get() or 'None'
        title = source.xpath('../img/@title').get() or alt_text
        
        # Add all source URLs as separate potential images
        for src_url in all_src_urls:
            if src_url and not src_url.startswith('data:'):
                potential_images.append({
                    'img_url': src_url,
                    'alt_text': alt_text,
                    'title': f"{title} (source variant)",
                    'source_type': 'source_element'
                })
    
    # 3. Find background images in inline styles
    background_image_urls = find_background_images(html_content, url)
    
    # Check for any <a> tags that link directly to images
    image_links = sel.xpath('//a[contains(@href, ".jpg") or contains(@href, ".jpeg") or contains(@href, ".png") or contains(@href, ".gif") or contains(@href, ".webp")]/@href').getall()
    for link in image_links:
        if link and not link.startswith('data:'):
            potential_images.append({
                'img_url': link,
                'alt_text': 'Linked Image',
                'title': 'Direct Image Link',
                'source_type': 'image_link'
            })
    
    # Fetch CSS and JS in parallel for better performance
    resource_urls = []
    
    # Get CSS links - more comprehensive selection
    css_links = sel.xpath('//link[@rel="stylesheet" or contains(@type, "css")]/@href').getall()
    for css_link in css_links:
        if css_link:
            resource_urls.append(('css', urljoin(url, css_link)))
    
    # Get JS links - more comprehensive selection
    js_links = sel.xpath('//script[contains(@src, "gallery") or contains(@src, "image") or contains(@src, "media") or contains(@src, "main") or contains(@src, "common") or contains(@src, "assets")]/@src').getall()
    for js_link in js_links:
        if js_link:
            resource_urls.append(('js', urljoin(url, js_link)))
    
    # Process resources in parallel
    def fetch_resource(resource_info):
        resource_type, resource_url = resource_info
        try:
            resp = session.get(resource_url, timeout=timeout)
            if not resp.ok:
                return []
            
            if resource_type == 'css':
                return extract_images_from_css(resp.text, url)
            elif resource_type == 'js':
                return extract_images_from_js(resp.text, url)
        except:
            return []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for result in executor.map(fetch_resource, resource_urls):
            background_image_urls.extend(result)
    
    # Add background images to potential images
    for bg_url in background_image_urls:
        if not bg_url.startswith('data:'):
            potential_images.append({
                'img_url': bg_url,
                'alt_text': 'Background Image',
                'title': 'CSS Background',
                'source_type': 'background'
            })
    
    # Look for JSON-LD structured data that might contain images
    json_ld_scripts = sel.xpath('//script[@type="application/ld+json"]/text()').getall()
    for script in json_ld_scripts:
        try:
            import json
            data = json.loads(script)
            # Extract image URLs from JSON-LD more efficiently
            image_urls = []
            
            def extract_image_urls(obj):
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        if key in ['image', 'thumbnailUrl', 'contentUrl', 'url', 'logo', 'photo'] and isinstance(value, str):
                            if any(value.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.ico']) or '/image' in value:
                                image_urls.append(value)
                        elif isinstance(value, (dict, list)):
                            extract_image_urls(value)
                elif isinstance(obj, list):
                    for item in obj:
                        extract_image_urls(item)
            
            extract_image_urls(data)
            
            for img_url in image_urls:
                potential_images.append({
                    'img_url': img_url,
                    'alt_text': 'Structured Data Image',
                    'title': 'JSON-LD Image',
                    'source_type': 'json_ld'
                })
        except:
            continue
    
    # Also check for Open Graph and Twitter card images
    meta_image_urls = []
    for meta in sel.xpath('//meta[contains(@property, "image") or contains(@name, "image")]/@content').getall():
        if meta and not meta.startswith('data:'):
            meta_image_urls.append(meta)
    
    for meta_url in meta_image_urls:
        potential_images.append({
            'img_url': meta_url,
            'alt_text': 'Meta Image',
            'title': 'Open Graph/Twitter Card',
            'source_type': 'meta_tags'
        })
    
    logger.info(f"Found {len(potential_images)} potential images to process")
    
    # Remove duplicates before processing
    unique_images = []
    for img in potential_images:
        abs_img_url = urljoin(url, img['img_url'])
        if abs_img_url not in image_urls_seen:
            image_urls_seen.add(abs_img_url)
            img['base_url'] = url
            unique_images.append(img)
    
    logger.info(f"After removing duplicates: {len(unique_images)} unique images")
    
    # Process images in parallel
    images_data = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_image = {
            executor.submit(get_image_metadata, task['img_url'], task['base_url'], timeout): task
            for task in unique_images
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_image):
            task = future_to_image[future]
            try:
                metadata = future.result()
                
                # Combine task info with metadata - include all images, even those with errors
                result = {
                    'alt_text': task['alt_text'],
                    'title': task['title'],
                    'source_type': task['source_type'],
                    **metadata
                }
                
                images_data.append(result)
                
            except Exception as e:
                logger.error(f"Unexpected error processing image {task['img_url']}: {e}")
                # Add error image to results
                images_data.append({
                    'alt_text': task['alt_text'],
                    'title': task['title'],
                    'source_type': task['source_type'],
                    'url': urljoin(task['base_url'], task['img_url']),
                    'status': 'error',
                    'error_message': f"Error loading image: {str(e)}",
                    'error_type': 'processing_error'
                })
    
    # Sort images: successful first, then error images
    images_data.sort(key=lambda x: 0 if x.get('status') != 'error' else 1)
    
    # Only add image numbers to the final filtered results
    for i, img in enumerate(images_data, 1):
        img['image_number'] = i
    
    # Add summary statistics
    if images_data:
        # Count successful and error images
        success_count = sum(1 for img in images_data if img.get('status') != 'error')
        error_count = len(images_data) - success_count
        
        total_size_kb = sum(img.get('raw_size', 0) for img in images_data if isinstance(img.get('raw_size'), (int, float)))
        avg_width = sum(img.get('width', 0) for img in images_data if isinstance(img.get('width'), (int, float)) and img.get('width', 0) > 0) / success_count if success_count else 0
        avg_height = sum(img.get('height', 0) for img in images_data if isinstance(img.get('height'), (int, float)) and img.get('height', 0) > 0) / success_count if success_count else 0
        
        logger.info(f"Successfully extracted {success_count} images, {error_count} errors. Total size: {total_size_kb:.2f} KB")
    
    return images_data
