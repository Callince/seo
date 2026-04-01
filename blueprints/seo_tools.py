import os
import re
import csv
import json
import logging
import asyncio
import uuid
import time
import hashlib
import traceback
import threading
from io import BytesIO, StringIO
from collections import Counter
from datetime import datetime, timedelta, timezone, date
from urllib.parse import quote, urljoin, urlparse, unquote

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    session, jsonify, send_file, current_app, after_this_request, make_response
)
from flask_login import current_user
from markupsafe import Markup
from sqlalchemy import func

from extensions import db, cache, csrf, executor
from models import User, SubscribedUser, Subscription, SearchHistory, UsageLog
from blueprints.auth import login_required
from services.subscription import (
    subscription_required_with_tokens,
    subscription_check_only,
    add_search_history,
    remove_search_history
)
from utils.link_analyzer import analyze_links
from utils.text_extractor import (
    extract_text, correct_text, process_keywords,
    extract_keywords_tfidf, extract_keywords_rake, extract_keywords_combined
)
from utils.image_extractor import extract_images
from utils.seo_analyzer import extract_seo_data
from utils.heading_extractor import extract_headings_in_order
from robots_parser import analyze_robots_txt
from crawler import crawl, save_to_json
from crawl_status_manager import CrawlStatusManager, CrawlStatusDict

UTC = timezone.utc

seo_tools_bp = Blueprint('seo_tools', __name__)

download_dir = "download_files"

# --------------------------------
# Crawl Status (shared state)
# --------------------------------
crawl_status_manager = CrawlStatusManager(
    redis_host=os.environ.get('REDIS_HOST', 'localhost'),
    redis_port=int(os.environ.get('REDIS_PORT', 6379)),
    redis_db=1,
    redis_password=os.environ.get('REDIS_PASSWORD', None)
)
crawl_status = CrawlStatusDict(crawl_status_manager)


# --------------------------------
# Cache Helper Functions
# --------------------------------
def generate_cache_key(user_id, search_type, url):
    """Generate a unique cache key for search results"""
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    timestamp = int(time.time())  # Add timestamp for uniqueness
    return f"search_{user_id}_{search_type}_{url_hash}_{timestamp}"


def store_search_results(search_type, url, home_links, other_links, robots_info):
    """Store search results in cache instead of session"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            current_app.logger.error(f"store_search_results: No user_id in session!")
            return False

        cache_key = generate_cache_key(user_id, search_type, url)

        # Store in cache with 2 hour expiration
        cache_data = {
            'url': url,
            'home_links': home_links,
            'other_links': other_links,
            'robots_info': robots_info.copy() if robots_info else None,
            'timestamp': time.time()
        }

        # Remove parser_id if present (not serializable)
        if cache_data['robots_info'] and 'parser_id' in cache_data['robots_info']:
            cache_data['robots_info'].pop('parser_id', None)

        cache.set(cache_key, cache_data, timeout=7200)  # 2 hours

        # Store only the cache key in session (much smaller)
        session[f'{search_type}_cache_key'] = cache_key
        session.modified = True

        current_app.logger.info(f"STORED in cache: {cache_key} | URL: {url} | Home: {len(home_links)} | Other: {len(other_links)}")
        return True

    except Exception as e:
        current_app.logger.error(f"Error storing search results in cache: {str(e)}", exc_info=True)
        return False


def get_search_results(search_type):
    """Get search results from cache"""
    try:
        cache_key = session.get(f'{search_type}_cache_key')
        current_app.logger.info(f"GET_SEARCH_RESULTS: search_type={search_type}, cache_key={cache_key}")

        if not cache_key:
            current_app.logger.warning(f"No cache_key found in session for {search_type}")
            return '', None, None

        cache_data = cache.get(cache_key)
        if not cache_data:
            # Cache expired or missing
            current_app.logger.warning(f"Cache data not found for key: {cache_key}")
            session.pop(f'{search_type}_cache_key', None)
            return '', None, None

        url = cache_data.get('url', '')
        home_links = cache_data.get('home_links', [])
        other_links = cache_data.get('other_links', [])
        robots_info = cache_data.get('robots_info')

        links_data = None
        if home_links or other_links:
            links_data = {'home': home_links, 'other': other_links}

        current_app.logger.info(f"RETRIEVED from cache: {cache_key} | URL: {url} | Home: {len(home_links)} | Other: {len(other_links)}")
        return url, links_data, robots_info

    except Exception as e:
        current_app.logger.error(f"Error retrieving search results from cache: {str(e)}", exc_info=True)
        return '', None, None


def clear_search_results(search_type):
    """Clear search results from cache"""
    try:
        cache_key = session.get(f'{search_type}_cache_key')
        if cache_key:
            cache.delete(cache_key)
            current_app.logger.info(f"Cleared cache: {cache_key}")
        session.pop(f'{search_type}_cache_key', None)
        session.modified = True
    except Exception as e:
        current_app.logger.error(f"Error clearing search results: {str(e)}")


def store_simple_data(key, data, timeout=3600):
    """Store simple data in cache (for non-search related data)"""
    try:
        user_id = session.get('user_id')
        cache_key = f"user_{user_id}_{key}"
        cache.set(cache_key, data, timeout=timeout)
        session[f'{key}_cache_key'] = cache_key
        session.modified = True
        return True
    except Exception as e:
        current_app.logger.error(f"Error storing simple data: {str(e)}")
        return False


def get_simple_data(key):
    """Get simple data from cache"""
    try:
        cache_key = session.get(f'{key}_cache_key')
        if not cache_key:
            return None
        return cache.get(cache_key)
    except Exception as e:
        current_app.logger.error(f"Error getting simple data: {str(e)}")
        return None


# --------------------------------
# Highlight Keywords Helper
# --------------------------------
def highlight_keywords_func(text, keywords_colors):
    """
    Highlight keywords in text with their assigned colors.
    Handles both single-word and multi-word keywords properly.
    Returns HTML string with highlighted keywords.
    """
    if not keywords_colors:
        return text

    highlighted = text

    # Sort keywords by length (longest first) to handle multi-word keywords properly
    # This prevents shorter keywords from interfering with longer ones
    sorted_keywords = sorted(keywords_colors.items(), key=lambda x: len(x[0]), reverse=True)

    for keyword, color in sorted_keywords:
        # Escape special regex characters in the keyword
        pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)

        # Use background color for better visibility
        highlighted = pattern.sub(
            lambda m: f'<span style="background-color: {color}; color: white; font-weight: bold; padding: 2px 6px; border-radius: 4px; margin: 0 2px;">{m.group(0)}</span>',
            highlighted
        )

    return highlighted


# --------------------------------
# Async / Crawl Helpers
# --------------------------------
def run_async_in_thread(coro):
    """Helper function to run async code in a thread"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def run_async_in_thread_with_progress(coro, job_id):
    """Run an async coroutine in a thread and update progress"""
    try:
        current_app.logger.info(f"Background thread started for job {job_id}")

        # Run the async coroutine
        result = run_async_in_thread(coro)

        # Double-check the status is set - CORRECT WAY for Redis
        if job_id in crawl_status:
            status_data = crawl_status.get(job_id)
            if status_data and status_data.get('status') != 'completed':
                current_app.logger.warning(f"Job {job_id} finished but status is {status_data.get('status')}, forcing completion")
                status_data['status'] = 'completed'
                status_data['progress'] = 100
                crawl_status[job_id] = status_data  # Save back to Redis
                current_app.logger.info(f"Forced completion for job {job_id}, status saved to Redis")
            else:
                current_app.logger.info(f"Job {job_id} already marked as completed")
        else:
            current_app.logger.error(f"Job {job_id} not found in crawl_status after completion")

        current_app.logger.info(f"Background thread completed for job {job_id}")
        return result

    except Exception as e:
        current_app.logger.error(f"Error in background task for job {job_id}: {str(e)}")
        if job_id in crawl_status:
            status_data = crawl_status.get(job_id)
            if status_data:
                status_data['status'] = 'failed'
                status_data['progress'] = 0
                crawl_status[job_id] = status_data  # Save back to Redis
        return None


def load_results():
    """Load crawl results with enhanced error handling and debugging."""
    job_id = session.get('job_id')
    current_app.logger.info(f"Loading results for job_id: {job_id}")

    if not job_id:
        current_app.logger.warning("No job_id found in session")
        return {"status_codes": {}, "home_links": {}, "other_links": {}}

    # Ensure crawled_data directory exists
    crawled_data_dir = "crawled_data"
    if not os.path.exists(crawled_data_dir):
        current_app.logger.error(f"Crawled data directory does not exist: {crawled_data_dir}")
        os.makedirs(crawled_data_dir, exist_ok=True)
        return {"status_codes": {}, "home_links": {}, "other_links": {}}

    # Build the JSON file path using the job ID
    crawled_data = f"crawled_data/crawl_{job_id}.json"
    current_app.logger.info(f"Looking for data file: {crawled_data}")

    if os.path.exists(crawled_data):
        try:
            # Check file size
            file_size = os.path.getsize(crawled_data)
            current_app.logger.info(f"Data file size: {file_size} bytes")

            if file_size == 0:
                current_app.logger.error(f"Data file is empty: {crawled_data}")
                return {"status_codes": {}, "home_links": {}, "other_links": {}}

            # ENHANCED FILE READING WITH RETRY
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    with open(crawled_data, "r", encoding="utf-8") as file:
                        data = json.load(file)
                        current_app.logger.info(f"Successfully loaded data from {crawled_data}")

                        # VALIDATE LOADED DATA
                        if not isinstance(data, dict):
                            current_app.logger.error("Data is not a dictionary")
                            return {"status_codes": {}, "home_links": {}, "other_links": {}}

                        # ENSURE ALL REQUIRED KEYS EXIST
                        if "home_links" not in data:
                            data["home_links"] = {}
                        if "status_codes" not in data:
                            data["status_codes"] = {}
                        if "other_links" not in data:
                            data["other_links"] = {}

                        # LOG DATA SUMMARY
                        home_links_count = len(data.get("home_links", {}))
                        status_codes_count = len(data.get("status_codes", {}))
                        other_links_count = len(data.get("other_links", {}))

                        current_app.logger.info(f"Data contains {home_links_count} home links, {status_codes_count} status codes, {other_links_count} other links")

                        return data

                except json.JSONDecodeError as e:
                    current_app.logger.error(f"JSON decode error (attempt {attempt + 1}): {str(e)}")
                    if attempt == max_retries - 1:
                        # On final attempt, log file content for debugging
                        try:
                            with open(crawled_data, "r", encoding="utf-8") as file:
                                first_lines = file.read(500)
                                current_app.logger.error(f"First 500 chars of file: {first_lines}")
                        except:
                            pass
                        raise
                    else:
                        time.sleep(0.5)  # Wait before retry

        except Exception as e:
            current_app.logger.error(f"Error reading {crawled_data}: {str(e)}")
    else:
        current_app.logger.warning(f"Data file does not exist: {crawled_data}")

    return {"status_codes": {}, "home_links": {}, "other_links": {}}


async def main_crawl(start_url, job_id):
    """Run the crawler asynchronously and save results with the job ID."""
    try:
        current_app.logger.info(f"Starting crawl for job {job_id}")

        # Update status to show we're actually crawling - CORRECT WAY for Redis
        status_data = crawl_status.get(job_id)
        if status_data:
            status_data['status'] = 'running'
            status_data['progress'] = 10
            crawl_status[job_id] = status_data  # Save back to Redis
            current_app.logger.info(f"Updated job {job_id} status to running, progress 10%")

        # Define progress callback to update Redis during crawling
        async def update_progress(progress_pct):
            """Callback to update crawl progress in Redis"""
            status_data = crawl_status.get(job_id)
            if status_data:
                status_data['progress'] = progress_pct
                crawl_status[job_id] = status_data  # Save back to Redis
                current_app.logger.info(f"Progress update for job {job_id}: {progress_pct}%")

        # OPTIMIZED FOR SPEED: Balanced settings for fast but reliable crawling
        url_status, home_links, other_links = await crawl(
            start_url,
            max_concurrency=10,
            max_pages=1000,
            delay_between_requests=0.2,
            progress_callback=update_progress  # Pass the callback
        )

        current_app.logger.info(f"Crawl completed for job {job_id}. Processing {len(url_status)} URLs")

        # Update progress before saving - CORRECT WAY for Redis
        status_data = crawl_status.get(job_id)
        if status_data:
            status_data['progress'] = 90
            crawl_status[job_id] = status_data  # Save back to Redis
            current_app.logger.info(f"Updated job {job_id} progress to 90%")

        # Save results
        save_to_json(url_status, home_links, other_links, job_id)

        current_app.logger.info(f"Results saved for job {job_id}")

        # Mark as completed - CORRECT WAY for Redis
        status_data = crawl_status.get(job_id)
        if status_data:
            status_data['status'] = 'completed'
            status_data['progress'] = 100
            crawl_status[job_id] = status_data  # Save back to Redis
            current_app.logger.info(f"Job {job_id} marked as completed with progress 100%")

        return True

    except Exception as e:
        current_app.logger.error(f"Error in main_crawl for job {job_id}: {str(e)}")
        status_data = crawl_status.get(job_id)
        if status_data:
            status_data['status'] = 'failed'
            status_data['progress'] = 0
            crawl_status[job_id] = status_data  # Save back to Redis
        return False


# --------------------------------
# Link Analysis Helpers
# --------------------------------
def safe_analyze_links(url, respect_robots=True, timeout=30):
    """
    Safe wrapper around analyze_links with comprehensive error handling
    """
    try:
        current_app.logger.info(f"Starting safe link analysis for: {url}")

        # Call the main analyze_links function with correct signature
        home_links, other_links, robots_info = analyze_links(
            url=url,
            respect_robots=respect_robots,
            retry_count=3,
            delay_between_retries=3,
            headless=True
        )

        # Debug the results
        debug_link_analysis(url, home_links, other_links, robots_info)

        return home_links, other_links, robots_info

    except Exception as e:
        current_app.logger.error(f"Error in safe_analyze_links: {str(e)}")
        current_app.logger.error(f"Exception details: {traceback.format_exc()}")
        return [], [], None


def is_same_domain(url1, url2):
    """Enhanced domain comparison with better handling of edge cases"""
    try:
        parsed1 = urlparse(url1)
        parsed2 = urlparse(url2)

        # Normalize domains
        domain1 = parsed1.netloc.lower()
        domain2 = parsed2.netloc.lower()

        # Remove www. prefix
        if domain1.startswith('www.'):
            domain1 = domain1[4:]
        if domain2.startswith('www.'):
            domain2 = domain2[4:]

        # Remove port numbers for comparison
        domain1 = domain1.split(':')[0]
        domain2 = domain2.split(':')[0]

        return domain1 == domain2

    except Exception as e:
        current_app.logger.error(f"Error comparing domains {url1} and {url2}: {str(e)}")
        return False


def debug_link_analysis(url, home_links, other_links, robots_info):
    """Debug function to log link analysis results"""
    try:
        parsed_url = urlparse(url)
        base_domain = parsed_url.netloc.lower().replace('www.', '')

        current_app.logger.info(f"=== Link Analysis Debug for {url} ===")
        current_app.logger.info(f"Base domain: {base_domain}")
        current_app.logger.info(f"Home links count: {len(home_links)}")
        current_app.logger.info(f"Other links count: {len(other_links)}")
        current_app.logger.info(f"Robots info available: {robots_info is not None}")

        if len(home_links) == 0:
            current_app.logger.warning(f"WARNING: No home links found for {url}")

        # Log first few home links for debugging
        for i, link in enumerate(home_links[:5]):
            current_app.logger.info(f"Home link {i+1}: {link}")

        # Log first few other links for debugging
        for i, link in enumerate(other_links[:5]):
            current_app.logger.info(f"Other link {i+1}: {link}")

    except Exception as e:
        current_app.logger.error(f"Error in debug_link_analysis: {str(e)}")


# --------------------------------
# Dashboard Token Usage Helper
# --------------------------------
def get_today_token_usage_breakdown(user_id):
    """
    Get detailed breakdown of today's token usage including additional tokens

    Returns:
        dict: {
            'daily_quota_used': int,
            'additional_tokens_used': int,
            'total_tokens_used_today': int,
            'daily_limit': int
        }
    """
    try:
        # Get active subscription
        now = datetime.now(UTC)
        active_subscription = (
            SubscribedUser.query
            .filter(SubscribedUser.U_ID == user_id)
            .filter(SubscribedUser.end_date > now)
            .filter(SubscribedUser._is_active == True)
            .first()
        )

        if not active_subscription:
            return {
                'daily_quota_used': 0,
                'additional_tokens_used': 0,
                'total_tokens_used_today': 0,
                'daily_limit': 0
            }

        # Apply daily reset logic (same as increment_usage_with_tokens)
        today_utc = datetime.now(UTC).date()
        last_reset_date = getattr(active_subscription, 'last_usage_reset', None)

        if not last_reset_date or last_reset_date.date() < today_utc:
            # Reset counter for new day
            active_subscription.current_usage = 0
            active_subscription.last_usage_reset = datetime.now(UTC)
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error resetting daily usage: {str(e)}")

        daily_limit = active_subscription.get_total_usage_limit()
        daily_quota_used = active_subscription.current_usage

        # Calculate additional tokens used today by checking usage logs
        today_start = datetime.combine(today_utc, datetime.min.time())
        today_end = datetime.combine(today_utc, datetime.max.time())

        today_logs = UsageLog.query.filter(
            UsageLog.user_id == user_id,
            UsageLog.timestamp >= today_start,
            UsageLog.timestamp <= today_end
        ).all()

        additional_tokens_used = 0
        total_tokens_from_logs = 0

        # Parse usage logs to extract token information
        for log in today_logs:
            try:
                if log.details:
                    # Check for new format: "Operation completed - Used X from daily quota + Y additional tokens (Total: Z)"
                    total_match = re.search(r'Total:\s*(\d+)', log.details, re.IGNORECASE)
                    if total_match:
                        total_tokens_from_logs += int(total_match.group(1))

                        # Look for additional tokens pattern
                        additional_match = re.search(r'(\d+)\s+additional\s+tokens', log.details, re.IGNORECASE)
                        if additional_match:
                            additional_tokens_used += int(additional_match.group(1))

                    # Check for old format: "Tokens used: X"
                    elif "Tokens used:" in log.details:
                        token_match = re.search(r'Tokens used:\s*(\d+)', log.details)
                        if token_match:
                            tokens_in_log = int(token_match.group(1))
                            total_tokens_from_logs += tokens_in_log

            except Exception as e:
                current_app.logger.error(f"Error parsing usage log {log.id}: {str(e)}")
                continue

        # Use the total from logs if available, otherwise calculate from daily quota + additional
        if total_tokens_from_logs > 0:
            total_tokens_used_today = total_tokens_from_logs
        else:
            total_tokens_used_today = daily_quota_used + additional_tokens_used

        return {
            'daily_quota_used': daily_quota_used,
            'additional_tokens_used': additional_tokens_used,
            'total_tokens_used_today': total_tokens_used_today,
            'daily_limit': daily_limit
        }

    except Exception as e:
        current_app.logger.error(f"Error calculating today's token usage: {str(e)}")
        return {
            'daily_quota_used': 0,
            'additional_tokens_used': 0,
            'total_tokens_used_today': 0,
            'daily_limit': 0
        }


# ================================
# ROUTES
# ================================

# --------------------------------
# Dashboard
# --------------------------------
@seo_tools_bp.route('/dashboard', methods=['GET'])
@login_required
def index():
    # Get the user_id from session if user is logged in
    user_id = session.get('user_id')
    view_mode = "dashboard"  # Default to dashboard view

    # Initialize ALL data with default values
    recent_analyses = []
    today_token_usage = 0
    total_token_usage = 0
    top_operation_type = "N/A"
    weekly_trend = 0
    today_vs_yesterday = 0
    user_name = "User"
    tool_distribution = []
    milestone_progress = 0
    has_active_subscription = False
    recent_activity = {}
    available_tokens = 0
    trial_tokens = 0
    trial_tokens_used = 0  # Track trial tokens used (for display)
    total_daily_tokens = 0
    token_usage_percentage = 0
    daily_quota_used = 0
    additional_tokens_used_today = 0
    next_milestone = 100

    # Only fetch data if a user is logged in
    if user_id:
        # Get the user's name from the database
        user = User.query.get(user_id)
        if user:
            user_name = user.name
            trial_tokens = user.trial_tokens
            trial_tokens_used = 5 - trial_tokens  # Calculate trial tokens used (5 initial - remaining)
            recent_activity = {
                'last_login': user.get_last_login_display(),
                'profile_updated': user.get_profile_updated_display(),
                'password_changed': user.get_password_changed_display()
            }

        # Get time ranges
        today = date.today()
        yesterday = today - timedelta(days=1)
        week_ago = today - timedelta(days=7)
        two_weeks_ago = today - timedelta(days=14)
        now = datetime.now(UTC)

        # Get the user's active subscription using the same logic as increment_usage
        active_subscription = (
            SubscribedUser.query
            .filter(SubscribedUser.U_ID == user_id)
            .filter(SubscribedUser.end_date > datetime.now(UTC))
            .filter(SubscribedUser._is_active == True)
            .first()
        )

        # Set subscription status for template
        has_active_subscription = active_subscription is not None

        # Proceed with detailed analytics for all logged-in users
        if True:  # Always show stats for logged-in users
            # Apply the same daily reset logic as increment_usage (only for subscribed users)
            if active_subscription:
                today_utc = datetime.now(UTC).date()
                last_reset_date = getattr(active_subscription, 'last_usage_reset', None)

                # Check if usage needs daily reset (same logic as increment_usage)
                if not last_reset_date or last_reset_date.date() < today_utc:
                    # Reset counter for new day
                    active_subscription.current_usage = 0
                    active_subscription.last_usage_reset = datetime.now(UTC)
                    try:
                        db.session.commit()
                    except Exception as e:
                        db.session.rollback()
                        current_app.logger.error(f"Error resetting daily usage: {str(e)}")

                # Get detailed today's token usage breakdown
                today_usage = get_today_token_usage_breakdown(user_id)

                today_token_usage = today_usage['total_tokens_used_today']
                daily_quota_used = today_usage['daily_quota_used']
                additional_tokens_used_today = today_usage['additional_tokens_used']
                total_daily_tokens = today_usage['daily_limit']
                available_tokens = max(0, total_daily_tokens - daily_quota_used)
                token_usage_percentage = (daily_quota_used / total_daily_tokens * 100) if total_daily_tokens > 0 else 0
            else:
                # Trial user stats - show trial tokens as available
                # Calculate today's trial token usage from usage logs
                today_utc = datetime.now(UTC).date()
                today_start = datetime.combine(today_utc, datetime.min.time())
                today_end = datetime.combine(today_utc, datetime.max.time())

                today_trial_logs = UsageLog.query.filter(
                    UsageLog.user_id == user_id,
                    UsageLog.is_trial == True,
                    UsageLog.timestamp >= today_start,
                    UsageLog.timestamp <= today_end
                ).all()

                # Calculate today's trial token usage from logs
                today_token_usage = 0
                for log in today_trial_logs:
                    try:
                        if log.details:
                            token_match = re.search(r'Tokens used:\s*(\d+)', log.details)
                            if token_match:
                                today_token_usage += int(token_match.group(1))
                            else:
                                today_token_usage += 1
                        else:
                            today_token_usage += 1
                    except Exception as e:
                        current_app.logger.error(f"Error parsing trial token usage from log {log.id}: {str(e)}")
                        today_token_usage += 1

                daily_quota_used = today_token_usage
                additional_tokens_used_today = 0
                total_daily_tokens = 5  # Trial tokens total
                available_tokens = trial_tokens
                token_usage_percentage = ((5 - trial_tokens) / 5 * 100) if trial_tokens < 5 else 0

            # Query recent analyses from search history (for URLs/queries)
            recent_analyses = SearchHistory.query.filter_by(u_id=user_id)\
                .order_by(SearchHistory.created_at.desc())\
                .limit(5)\
                .all()

            # Get yesterday's token usage (including additional tokens)
            yesterday = date.today() - timedelta(days=1)
            yesterday_start = datetime.combine(yesterday, datetime.min.time())
            yesterday_end = datetime.combine(yesterday, datetime.max.time())

            yesterday_logs = UsageLog.query.filter(
                UsageLog.user_id == user_id,
                UsageLog.timestamp >= yesterday_start,
                UsageLog.timestamp <= yesterday_end
            ).all()

            # Calculate yesterday's total token usage (daily + additional)
            yesterday_token_usage = 0
            for log in yesterday_logs:
                try:
                    if log.details:
                        # Check for new format first: "Operation completed - Used X from daily quota + Y additional tokens (Total: Z)"
                        total_match = re.search(r'Total:\s*(\d+)', log.details, re.IGNORECASE)
                        if total_match:
                            yesterday_token_usage += int(total_match.group(1))
                        # Check for old format: "Tokens used: X"
                        elif "Tokens used:" in log.details:
                            match = re.search(r'Tokens used:\s*(\d+)', log.details)
                            if match:
                                yesterday_token_usage += int(match.group(1))
                            else:
                                yesterday_token_usage += 1
                        else:
                            # Fallback for logs without token info
                            yesterday_token_usage += 1
                    else:
                        yesterday_token_usage += 1
                except Exception as e:
                    current_app.logger.error(f"Error parsing yesterday token usage from log {log.id}: {str(e)}")
                    yesterday_token_usage += 1

            # Calculate percentage change vs yesterday (now comparing total tokens)
            if yesterday_token_usage > 0:
                today_vs_yesterday = ((today_token_usage - yesterday_token_usage) / yesterday_token_usage) * 100
            else:
                today_vs_yesterday = 100 if today_token_usage > 0 else 0

            # Total token usage (from all usage logs)
            all_logs = UsageLog.query.filter(UsageLog.user_id == user_id).all()
            total_token_usage = 0
            for log in all_logs:
                try:
                    if log.details:
                        # Check for new format: "Operation completed - Used X from daily quota + Y additional tokens (Total: Z)"
                        total_match = re.search(r'Total:\s*(\d+)', log.details, re.IGNORECASE)
                        if total_match:
                            total_token_usage += int(total_match.group(1))
                        # Check for old format: "Tokens used: X"
                        elif "Tokens used:" in log.details:
                            match = re.search(r'Tokens used:\s*(\d+)', log.details)
                            if match:
                                total_token_usage += int(match.group(1))
                            else:
                                total_token_usage += 1
                        else:
                            # Fallback for logs without token info
                            total_token_usage += 1
                    else:
                        # Fallback for logs without details
                        total_token_usage += 1
                except Exception as e:
                    current_app.logger.error(f"Error parsing total token usage from log {log.id}: {str(e)}")
                    total_token_usage += 1

            # For users who used trial tokens BEFORE usage logging was implemented,
            # add any unaccounted trial tokens to the total
            trial_logs_count = UsageLog.query.filter(
                UsageLog.user_id == user_id,
                UsageLog.is_trial == True
            ).count()

            if trial_logs_count == 0:
                # No trial usage logs exist - this means trial tokens were used before logging
                trial_tokens_used_count = 5 - trial_tokens
                if trial_tokens_used_count > 0:
                    total_token_usage += trial_tokens_used_count

            # Calculate milestone progress based on token usage
            milestone_thresholds = [100, 500, 1000, 5000, 10000, 50000]
            next_milestone = next((m for m in milestone_thresholds if m > total_token_usage), milestone_thresholds[-1] * 2)
            previous_milestone = next((m for m in reversed(milestone_thresholds) if m < total_token_usage), 0)

            if next_milestone > previous_milestone:
                milestone_progress = int(((total_token_usage - previous_milestone) / (next_milestone - previous_milestone)) * 100)
            else:
                milestone_progress = 100  # At or beyond highest milestone

            # Get the user's top operation type
            top_operation_query = db.session.query(
                UsageLog.operation_type,
                func.count(UsageLog.id).label('total')
            )\
            .filter(UsageLog.user_id == user_id)\
            .group_by(UsageLog.operation_type)\
            .order_by(func.count(UsageLog.id).desc())\
            .first()

            # Map operation types to user-friendly names
            OPERATION_DISPLAY_NAMES = {
                'url_search': 'Url Analysis',
                'url_search_ajax': 'Url Analysis',
                'keyword_detail': 'Keyword Analysis',
                'h_detail': 'Heading Analysis',
                'meta_detail': 'Meta Analysis',
                'image_detail': 'Image Analysis',
                'site_structure': 'Sitemap Analysis',
                'loading': 'Sitemap Analysis',
                'visualize': 'Sitemap Analysis',
                'url_analysis': 'Url Analysis',
                'keyword_search': 'Keyword Analysis',
                'heading_search': 'Heading Analysis',
                'meta_search': 'Meta Analysis',
                'image_search': 'Image Analysis'
            }

            if top_operation_query:
                raw_operation = top_operation_query[0]
                # Convert to user-friendly name
                top_operation_type = OPERATION_DISPLAY_NAMES.get(raw_operation, raw_operation.replace('_', ' ').title())
            else:
                # Fallback: Try to get from SearchHistory if UsageLog is empty
                top_search_query = db.session.query(
                    SearchHistory.usage_tool,
                    func.count(SearchHistory.id).label('total')
                )\
                .filter(SearchHistory.u_id == user_id)\
                .group_by(SearchHistory.usage_tool)\
                .order_by(func.count(SearchHistory.id).desc())\
                .first()

                if top_search_query:
                    top_operation_type = top_search_query[0]
                else:
                    top_operation_type = "No usage yet"

            # Get tool distribution for visualization (weighted by token cost)
            tool_usage_query = db.session.query(
                UsageLog.operation_type,
                func.count(UsageLog.id).label('count')
            )\
            .filter(UsageLog.user_id == user_id)\
            .group_by(UsageLog.operation_type)\
            .order_by(func.count(UsageLog.id).desc())\
            .all()

            # Calculate tool distribution with token weighting
            tool_token_usage = {}

            # Define token costs for each operation
            OPERATION_TOKEN_COSTS = {
                'url_search': 1,
                'keyword_detail': 3,
                'h_detail': 1,
                'meta_detail': 2,
                'image_detail': 2,
                'loading': 5,  # site structure
                'site_structure': 2,
            }

            for operation, count in tool_usage_query:
                # Get token cost for this operation (default to 1 if not defined)
                token_cost = OPERATION_TOKEN_COSTS.get(operation, 1)
                tool_token_usage[operation] = count * token_cost

            # Calculate percentages for tool distribution based on token usage
            total_tool_tokens = sum(tool_token_usage.values())

            if total_tool_tokens > 0:
                # Define CSS classes for different tools
                css_classes = ['primary', 'secondary', 'tertiary', 'quaternary', 'success', 'warning']

                tool_distribution = []
                for i, (tool, token_count) in enumerate(sorted(tool_token_usage.items(), key=lambda x: x[1], reverse=True)):
                    percentage = (token_count / total_tool_tokens) * 100

                    # Clean up operation names for display
                    display_name = tool.replace('_', ' ').title()
                    if 'Detail' in display_name:
                        display_name = display_name.replace(' Detail', ' Analysis')
                    elif 'Ajax' in display_name:
                        display_name = display_name.replace(' Ajax', '')

                    tool_distribution.append({
                        'name': display_name,
                        'percentage': round(percentage, 1),
                        'tokens': token_count,
                        'class': css_classes[i % len(css_classes)]
                    })

            # Calculate weekly trend based on token usage (this week vs. last week)
            this_week_start = week_ago
            last_week_start = two_weeks_ago
            last_week_end = week_ago

            # Get this week's logs
            this_week_logs = UsageLog.query.filter(
                UsageLog.user_id == user_id,
                UsageLog.timestamp >= this_week_start
            ).all()

            # Get last week's logs
            last_week_logs = UsageLog.query.filter(
                UsageLog.user_id == user_id,
                UsageLog.timestamp >= last_week_start,
                UsageLog.timestamp < last_week_end
            ).all()

            # Calculate token usage for each week
            this_week_tokens = 0
            for log in this_week_logs:
                try:
                    if log.details and "Tokens used:" in log.details:
                        match = re.search(r'Tokens used: (\d+)', log.details)
                        if match:
                            this_week_tokens += int(match.group(1))
                        else:
                            this_week_tokens += 1
                    else:
                        operation = log.operation_type
                        this_week_tokens += OPERATION_TOKEN_COSTS.get(operation, 1)
                except:
                    this_week_tokens += 1

            last_week_tokens = 0
            for log in last_week_logs:
                try:
                    if log.details and "Tokens used:" in log.details:
                        match = re.search(r'Tokens used: (\d+)', log.details)
                        if match:
                            last_week_tokens += int(match.group(1))
                        else:
                            last_week_tokens += 1
                    else:
                        operation = log.operation_type
                        last_week_tokens += OPERATION_TOKEN_COSTS.get(operation, 1)
                except:
                    last_week_tokens += 1

            # Calculate percentage change (avoid division by zero)
            if last_week_tokens > 0:
                weekly_trend = ((this_week_tokens - last_week_tokens) / last_week_tokens) * 100
            else:
                weekly_trend = 100 if this_week_tokens > 0 else 0

    # Prepare dashboard statistics (now all variables are guaranteed to be defined)
    dashboard_stats = {
        'today_tokens_used': today_token_usage,
        'daily_quota_used': daily_quota_used,
        'additional_tokens_used_today': additional_tokens_used_today,
        'available_tokens': available_tokens,
        'total_daily_tokens': total_daily_tokens,
        'token_usage_percentage': round(token_usage_percentage, 1),
        'total_lifetime_tokens': total_token_usage,
        'yesterday_comparison': round(today_vs_yesterday, 1),
        'weekly_trend': round(weekly_trend, 1),
        'milestone_progress': milestone_progress,
        'next_milestone': next_milestone
    }

    # Pass all data to template including subscription status and token info
    return render_template('index.html',
                      user_name=user_name,
                      recent_analyses=recent_analyses,
                      websites_analyzed_today=today_token_usage,
                      total_analyses=total_token_usage,
                      favorite_tool=top_operation_type,
                      weekly_trend=weekly_trend,
                      today_vs_yesterday=today_vs_yesterday,
                      tool_distribution=tool_distribution,
                      milestone_progress=milestone_progress,
                      now=now if user_id else datetime.now(UTC),
                      recent_activity=recent_activity,
                      links_data=None,
                      view_mode=view_mode,
                      has_active_subscription=has_active_subscription,
                      trial_tokens=trial_tokens,
                      trial_tokens_used=trial_tokens_used,
                      dashboard_stats=dashboard_stats,
                      available_tokens=available_tokens,
                      total_daily_tokens=total_daily_tokens,
                      token_usage_percentage=token_usage_percentage)


# --------------------------------
# URL Search Routes
# --------------------------------
@seo_tools_bp.route('/url_search', methods=['GET', 'POST'])
@login_required
@subscription_check_only
def url_search():
    links_data = None
    url_input = request.args.get('url', '')
    robots_info = None

    # Check for refresh or clear request
    if request.args.get('refresh') == 'true':
        clear_search_results('url_search')
        return redirect(url_for('seo_tools.url_search'))

    if request.method == 'POST' and not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        url_input = request.form.get('url')
        respect_robots = request.form.get('respect_robots') == 'on'

        if url_input:
            try:
                home_links, other_links, robots_info = analyze_links(
                    url=url_input,
                    respect_robots=respect_robots
                )

                # Extract domains for external links
                other_links_with_domains = []
                for link in other_links:
                    try:
                        parsed = urlparse(link)
                        domain = parsed.netloc
                        other_links_with_domains.append({
                            'url': link,
                            'domain': domain
                        })
                    except:
                        other_links_with_domains.append({
                            'url': link,
                            'domain': 'unknown'
                        })

                links_data = {
                    'home': home_links,
                    'other': other_links,
                    'other_with_domains': other_links_with_domains
                }

                # Store in cache instead of session
                store_search_results('url_search', url_input, home_links, other_links, robots_info)
                # Note: Search history is added in url_search_ajax which consumes tokens

            except Exception as e:
                current_app.logger.error(f"Error analyzing URL: {str(e)}")
                flash(f"Error analyzing URL: {str(e)}", "danger")
                return redirect(url_for('seo_tools.url_search'))

    # Get data from cache if available
    if not links_data and url_input:
        url_input, links_data, robots_info = get_search_results('url_search')

    return render_template(
        'url_search.html',
        url_input=url_input,
        links_data=links_data,
        robots_info=robots_info
    )


# ===== URL SEARCH AJAX ROUTE =====
@seo_tools_bp.route('/url_search_ajax', methods=['POST'])
@login_required
@subscription_required_with_tokens(1)
@csrf.exempt
def url_search_ajax():
    links_data = None
    url_input = request.form.get('url', '')
    respect_robots = request.form.get('respect_robots') == 'on'
    robots_info = None

    if url_input:
        try:
            user_id = session.get('user_id')
            if not user_id:
                return jsonify({"error": "Please log in to continue."}), 401

            # Clear previous cache before new search
            clear_search_results('url_search')

            home_links, other_links, robots_info = analyze_links(
                url=url_input,
                respect_robots=respect_robots
            )

            # Extract domains for external links
            other_links_with_domains = []
            for link in other_links:
                try:
                    parsed = urlparse(link)
                    domain = parsed.netloc
                    other_links_with_domains.append({
                        'url': link,
                        'domain': domain
                    })
                except:
                    other_links_with_domains.append({
                        'url': link,
                        'domain': 'unknown'
                    })

            links_data = {
                'home': home_links,
                'other': other_links,
                'other_with_domains': other_links_with_domains
            }

            # Store in cache
            store_search_results('url_search', url_input, home_links, other_links, robots_info)

            # Record search history only if we got results, remove if no results
            if home_links or other_links:
                add_search_history(user_id, "Url Analysis", url_input)
            else:
                remove_search_history(user_id, url_input)

        except Exception as e:
            current_app.logger.error(f"Error analyzing URL: {str(e)}")
            # Remove search history on error
            remove_search_history(user_id, url_input)
            return jsonify({"error": f"Error analyzing URL: {str(e)}"}), 500

    return render_template(
        'url_search_results.html',
        url_input=url_input,
        links_data=links_data,
        robots_info=robots_info
    )


@seo_tools_bp.route('/record_search', methods=['POST'])
@login_required
@csrf.exempt
def record_search():
    """
    This route is kept for backward compatibility but no longer adds search history.
    Search history is now only added from routes that consume tokens.
    """
    # Return success but don't add to history (handled by token-consuming routes)
    return jsonify({"success": True})


@seo_tools_bp.route('/download_url')
@login_required
def download_url():
    url_input = request.args.get('url')
    respect_robots = request.args.get('respect_robots', 'true') == 'true'

    if not url_input:
        flash("No URL provided for download.", "warning")
        return redirect(url_for('seo_tools.url_search'))

    try:
        # Try using previously analyzed data from session (if available)
        cached_data = session.get('url_analysis_cache')
        if cached_data and cached_data.get('url') == url_input:
            home_links = cached_data.get('home_links', [])
            other_links = cached_data.get('other_links', [])
            robots_info = cached_data.get('robots_info', {})
        else:
            # Re-run analysis only if cache not available
            home_links, other_links, robots_info = analyze_links(
                url=url_input,
                respect_robots=respect_robots
            )
            # Cache for next time
            session['url_analysis_cache'] = {
                'url': url_input,
                'home_links': home_links,
                'other_links': other_links,
                'robots_info': robots_info
            }

        # Ensure links are absolute
        home_links = [urljoin(url_input, link) for link in home_links]
        other_links = [urljoin(url_input, link) for link in other_links]

        # Prepare CSV data
        data = []
        for link in home_links:
            data.append({"Link": link, "Type": "Home", "Allowed": "Yes"})
        for link in other_links:
            data.append({"Link": link, "Type": "External", "Allowed": "Yes"})

        # Add disallowed links if robots.txt present
        if robots_info and robots_info.get('parser_id'):
            parser_id = robots_info.get('parser_id')
            parser = getattr(analyze_robots_txt, 'parsers', {}).get(parser_id, None)

            if parser:
                base_domain = urlparse(url_input).netloc
                if base_domain.startswith("www."):
                    base_domain = base_domain[4:]

                disallow_rules = robots_info.get('disallow_rules', [])
                if disallow_rules:
                    data.append({
                        "Link": "--- DISALLOWED LINKS (NOT CRAWLED) ---",
                        "Type": "",
                        "Allowed": ""
                    })
                    data.append({
                        "Link": f"robots.txt for {base_domain}",
                        "Type": "Info",
                        "Allowed": "N/A"
                    })
                    for rule in disallow_rules:
                        full_link = f"{urlparse(url_input).scheme}://{base_domain}{rule}"
                        data.append({"Link": full_link, "Type": "Disallowed", "Allowed": "No"})

        # Handle empty data safely
        if not data:
            flash("No links found to download. Try re-running URL analysis.", "warning")
            return redirect(url_for('seo_tools.url_search'))

        # Ensure download directory exists
        os.makedirs(download_dir, exist_ok=True)

        # Write CSV
        file_path = os.path.join(download_dir, 'links.csv')
        with open(file_path, 'w', newline='', encoding='utf-8') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=["Link", "Type", "Allowed"])
            writer.writeheader()
            writer.writerows(data)

        # Correct filename
        filename = 'Url_analysis_with_robots.csv' if respect_robots else 'Links.csv'

        return send_file(file_path, mimetype='text/csv', as_attachment=True, download_name=filename)

    except Exception as e:
        current_app.logger.error(f"Error in download_url: {str(e)}")
        flash(f"Error generating download: {str(e)}", "danger")
        return redirect(url_for('seo_tools.url_search'))


# --------------------------------
# Keyword Search Routes
# --------------------------------
@seo_tools_bp.route('/keyword_search', methods=['GET', 'POST'])
@login_required
@subscription_check_only
def keyword_search():
    # Clear cache when entering route fresh (not from POST)
    if request.method == 'GET' and not request.args.get('from_post'):
        clear_search_results('keyword_search')
    url_input = ""
    links_data = None
    robots_info = None

    # Check for explicit refresh
    if request.method == 'GET':
        is_explicit_refresh = request.args.get('refresh') == 'true'
        if is_explicit_refresh:
            clear_search_results('keyword_search')
            current_app.logger.info("Cleared keyword_search results - explicit refresh")
            return redirect(url_for('seo_tools.keyword_search'))

    if request.method == 'POST':
        url_input = request.form.get('url')
        respect_robots = request.form.get('respect_robots') == 'on'

        if url_input:
            try:
                current_app.logger.info(f"Keyword search POST: analyzing {url_input}")
                home_links, other_links, robots_info = analyze_links(
                    url=url_input,
                    respect_robots=respect_robots
                )

                current_app.logger.info(f"Analysis complete: {len(home_links)} home links, {len(other_links)} other links")

                # Store in cache
                store_result = store_search_results('keyword_search', url_input, home_links, other_links, robots_info)
                # Note: Search history is added in keyword_detail which consumes tokens

                if not store_result:
                    current_app.logger.error("Failed to store search results")
                    flash("Error saving results. Please try again.", "error")
                    return redirect(url_for('seo_tools.keyword_search'))

                # Prepare data for immediate display
                links_data = {'home': home_links, 'other': other_links}
                current_app.logger.info(f"Returning results immediately without redirect")

            except Exception as e:
                current_app.logger.error(f"Error in keyword_search: {str(e)}", exc_info=True)
                flash(f"Error analyzing URL: {str(e)}", "danger")
                return redirect(url_for('seo_tools.keyword_search'))
    else:
        # GET request - retrieve from cache
        url_input, links_data, robots_info = get_search_results('keyword_search')
        if links_data:
            current_app.logger.info(f"Retrieved cached results for {url_input}")
        else:
            current_app.logger.info("No cached results found")

    return render_template(
        'keyword_search.html',
        url_input=url_input,
        links_data=links_data,
        robots_info=robots_info
    )


@seo_tools_bp.route('/keyword_detail_ajax', methods=['POST'])
@login_required
def keyword_detail_ajax():
    """AJAX endpoint for keyword analysis without page reload"""
    try:
        link = request.form.get('link')
        keywords_input = request.form.get('keywords', '')

        if not link or not keywords_input:
            return jsonify({
                'success': False,
                'message': 'Link and keywords are required'
            })

        # Extract text from the link
        extracted_text = extract_text(link)

        # Process keywords
        keywords_list = [k.strip() for k in keywords_input.split(',') if k.strip()]
        if len(keywords_list) > 10:
            keywords_list = keywords_list[:10]

        keyword_results = process_keywords(extracted_text, keywords_list)

        # Generate colors for keywords with better visibility for background highlighting
        colors = ["#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c", "#0891b2", "#be123c", "#4f46e5", "#65a30d", "#db2777"]
        keywords_colors = {}
        for i, (kw, data) in enumerate(keyword_results["keywords"].items()):
            keywords_colors[kw] = colors[i] if i < len(colors) else 'black'

        # Highlight keywords in extracted text
        highlighted_text = highlight_keywords_func(extracted_text, keywords_colors)

        return jsonify({
            'success': True,
            'keyword_results': keyword_results,
            'keywords_colors': keywords_colors,
            'highlighted_text': highlighted_text,
            'total_words': keyword_results['total_words'],
            'keywords_input': keywords_input
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@seo_tools_bp.route('/keyword_detail', methods=['GET', 'POST'])
@login_required
@subscription_required_with_tokens(3)
def keyword_detail():
    link = request.args.get('link')
    if not link:
        flash("No link provided for keyword analysis.")
        return redirect(url_for('seo_tools.keyword_search'))

    # Get home links from cache
    stored_url, links_data, robots_info = get_search_results('keyword_search')
    home_links = links_data.get('home', []) if links_data else []

    # If no home links in cache, analyze the URL to get related links
    if not home_links:
        try:
            current_app.logger.info(f"No cached links found, analyzing {link} for related links")
            home_links_new, other_links, robots_info = analyze_links(
                url=link,
                respect_robots=True
            )
            home_links = home_links_new
            current_app.logger.info(f"Found {len(home_links)} related links")
        except Exception as e:
            current_app.logger.error(f"Error analyzing links: {str(e)}")
            home_links = []

    # Extract clean text for display (without weighted duplicates)
    extracted_text = extract_text(link, weighted=False)

    keyword_results = None
    corrected_results = None
    keywords_input = ""
    # Updated colors with better visibility for background highlighting with white text
    colors = ["#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c", "#0891b2", "#be123c", "#4f46e5", "#65a30d", "#db2777"]

    # Extract keywords automatically using TF-IDF and RAKE algorithms (20 multi-word keywords)
    # Use weighted text (with title/headings emphasized) for better keyword extraction
    auto_keywords = []  # Initialize as empty list of tuples (keyword, score)
    try:
        # Check if text extraction was successful
        if extracted_text and not extracted_text.startswith("Error"):
            # Record search history only on successful extraction
            u_id = session.get('user_id')
            add_search_history(u_id, "Keyword Analysis", link)

            # Get weighted text for keyword extraction (emphasizes title and headings)
            weighted_text = extract_text(link, weighted=True)
            current_app.logger.info(f"Extracting keywords from displayed text of length: {len(extracted_text)}")
            current_app.logger.info(f"Using weighted text of length: {len(weighted_text)} for keyword extraction")

            # Extract keywords from the weighted text, but validate against the displayed extracted_text
            # Get top 10 meaningful keywords only (combined algorithm)
            all_keywords = extract_keywords_combined(weighted_text, max_keywords=30, source_text=extracted_text)
            # Use only combined results and limit to 10
            combined_results = all_keywords.get('combined', []) if all_keywords else []
            # Ensure each item is a tuple of exactly 2 values (keyword, score)
            auto_keywords = [(kw, sc) for kw, sc in combined_results[:10] if isinstance(kw, str)]
            current_app.logger.info(f"Top 10 keywords extracted: {len(auto_keywords)}")
        else:
            current_app.logger.warning(f"Text extraction failed or returned error: {extracted_text[:100] if extracted_text else 'None'}")
            # Remove search history on failed extraction
            u_id = session.get('user_id')
            remove_search_history(u_id, link)
    except Exception as e:
        current_app.logger.error(f"Error extracting keywords: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        auto_keywords = []  # Ensure it's an empty list on error
        # Remove search history on error
        u_id = session.get('user_id')
        remove_search_history(u_id, link)

    if request.method == 'POST':
        keywords_input = request.form.get('keywords', '')
        keywords_list = [k.strip() for k in keywords_input.split(',') if k.strip()]
        if len(keywords_list) > 10:
            keywords_list = keywords_list[:10]
        keyword_results = process_keywords(extracted_text, keywords_list)
        corrected_results = correct_text(extracted_text)

    keywords_colors = {}
    if keyword_results:
        for i, (kw, data) in enumerate(keyword_results["keywords"].items()):
            keywords_colors[kw] = colors[i] if i < len(colors) else 'black'

    return render_template('keyword_detail.html',
                           link=link,
                           extracted_text=extracted_text,
                           keyword_results=keyword_results,
                           corrected_results=corrected_results,
                           keywords_input=keywords_input,
                           colors=colors,
                           home_links=home_links,
                           keywords_colors=keywords_colors,
                           auto_keywords=auto_keywords,
                           current_time=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
            )


@seo_tools_bp.route('/download_keyword_txt')
@login_required
def download_keyword_txt():
    link = request.args.get('link')
    keywords_input = request.args.get('keywords_input', '')

    if not link:
        flash("No link provided for download.")
        return redirect(url_for('seo_tools.keyword_search'))

    extracted_text = extract_text(link)
    cleaned_text = " ".join(extracted_text.split())

    output_text = cleaned_text
    analysis_text = "No keywords provided for analysis."

    if keywords_input:
        keywords_list = [k.strip() for k in keywords_input.split(',') if k.strip()]
        if keywords_list:
            keyword_results = process_keywords(extracted_text, keywords_list)
            analysis_lines = []
            for keyword, data in keyword_results["keywords"].items():
                line = f"Keyword: {keyword}, Count: {data['count']}, Density: {round(data['density'], 2)}%"
                analysis_lines.append(line)
            analysis_text = "\n".join(analysis_lines)

    output = f"Extracted Text:\n{output_text}\n\nKeyword Analysis:\n{analysis_text}"
    file_path = os.path.join(download_dir, 'keyword_analysis.txt')
    os.makedirs(download_dir, exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(output)

    return send_file(file_path, mimetype='text/plain', as_attachment=True, download_name='Keyword_analysis.txt')


# --------------------------------
# Image Search Routes
# --------------------------------
@seo_tools_bp.route('/image_search', methods=['GET', 'POST'])
@login_required
@subscription_check_only
def image_search():
    # Clear cache when entering route fresh (not from POST)
    if request.method == 'GET' and not request.args.get('from_post'):
        clear_search_results('image_search')
    links_data = None
    url_input = ""
    robots_info = None

    # Check if coming from navigation (clear cache when navigating back)
    if request.method == 'GET':
        # Check if this is a fresh navigation (from menu/other pages)
        referer = request.referrer
        is_from_other_page = referer and 'image_detail' not in referer and 'image_search' not in referer

        # Check if this is explicit refresh via button/link
        is_explicit_refresh = request.args.get('refresh') == 'true'

        # Clear cache if coming from another page OR explicit refresh
        if is_explicit_refresh or is_from_other_page:
            clear_search_results('image_search')
            current_app.logger.info("Cleared image_search results - fresh navigation or explicit refresh")
            # If explicit refresh, redirect to clean URL
            if is_explicit_refresh:
                return redirect(url_for('seo_tools.image_search'))

    if request.method == 'POST':
        url_input = request.form.get('url')
        # Get URL from the mobile input if desktop input is empty
        if not url_input:
            url_input = request.form.get('mobile-url')

        respect_robots = request.form.get('respect_robots') == 'on'

        if url_input:
            try:
                current_app.logger.info(f"Image search POST: analyzing {url_input}")
                home_links, other_links, robots_info = analyze_links(
                    url=url_input,
                    respect_robots=respect_robots
                )

                current_app.logger.info(f"Analysis complete: {len(home_links)} home links, {len(other_links)} other links")

                # Store in cache
                store_result = store_search_results('image_search', url_input, home_links, other_links, robots_info)
                # Note: Search history is added in image_detail which consumes tokens

                if not store_result:
                    current_app.logger.error("Failed to store search results")
                    flash("Error saving results. Please try again.", "error")
                    return redirect(url_for('seo_tools.image_search'))

                # Prepare data for immediate display (don't redirect)
                links_data = {'home': home_links, 'other': other_links}
                current_app.logger.info(f"Returning results immediately without redirect")

            except Exception as e:
                current_app.logger.error(f"Error in image_search: {str(e)}", exc_info=True)
                flash(f"Error analyzing URL: {str(e)}", "error")
                return redirect(url_for('seo_tools.image_search'))
    else:
        # GET request - retrieve from cache ONLY if not from other pages
        referer = request.referrer
        is_from_other_page = referer and 'image_detail' not in referer and 'image_search' not in referer

        if not is_from_other_page:
            url_input, links_data, robots_info = get_search_results('image_search')
            if links_data:
                current_app.logger.info(f"Retrieved cached results for {url_input}")
            else:
                current_app.logger.info("No cached results found")
        else:
            current_app.logger.info("Fresh page load - not loading cached results")

    return render_template(
        'image_search.html',
        url_input=url_input,
        links_data=links_data,
        robots_info=robots_info
    )


@seo_tools_bp.route('/image_detail', methods=['GET'])
@login_required
@subscription_required_with_tokens(2)
def image_detail():
    """
    Display image analysis results for a given link.
    Token consumption and usage logging handled by decorator.
    """
    # DEBUG: Log that we entered the route
    current_app.logger.info("=" * 80)
    current_app.logger.info("IMAGE_DETAIL ROUTE ACCESSED")
    current_app.logger.info(f"Request args: {request.args}")
    current_app.logger.info(f"Request method: {request.method}")
    current_app.logger.info(f"Request path: {request.path}")

    link = request.args.get('link')
    current_app.logger.info(f"Link parameter: {link}")

    if not link:
        current_app.logger.error("NO LINK PROVIDED!")
        flash("No link provided for image analysis.", "warning")
        return redirect(url_for('seo_tools.image_search'))

    # Get user ID for search history
    user_id = session.get('user_id') if not current_user.is_authenticated else current_user.id

    cache_key = f"images_{link}"
    images = cache.get(cache_key)

    if images is None:
        # Extract images (tokens already consumed by decorator)
        current_app.logger.info(f"User {user_id} requesting image analysis for {link} (not in cache)")

        try:
            current_app.logger.info(f"Extracting images from {link}")
            images = extract_images(link)
            # Ensure images is always a list
            if images is None:
                images = []

            current_app.logger.info(f"Successfully extracted {len(images)} images from {link}")

            # Add is_error flag to each image for template compatibility
            for img in images:
                if img.get('status') == 'error':
                    img['is_error'] = True
                    img['error'] = img.get('error_message', 'Unknown error')
                    img['details'] = img.get('error_type', '')
                else:
                    img['is_error'] = False

            current_app.logger.info(f"Processed image data, setting cache")
            cache.set(cache_key, images, timeout=3600)  # Cache for 1 hour

        except Exception as e:
            current_app.logger.error(f"Error extracting images from {link}: {str(e)}", exc_info=True)
            flash(f"Error extracting images: {str(e)}", "error")
            return redirect(url_for('seo_tools.image_search'))
    else:
        # Images loaded from cache
        current_app.logger.info(f"User {user_id} viewing cached image results for {link} ({len(images)} images)")

    # Always record search history since tokens are consumed by decorator
    if images:
        add_search_history(user_id, "Image Analysis", link)

    current_app.logger.info(f"=" * 80)
    current_app.logger.info(f"RENDERING image_detail.html with {len(images)} images")
    current_app.logger.info(f"=" * 80)

    try:
        response = render_template('image_detail.html', link=link, images=images)
        current_app.logger.info("Template rendered successfully, returning response")
        return response
    except Exception as e:
        current_app.logger.error(f"ERROR RENDERING TEMPLATE: {str(e)}", exc_info=True)
        flash(f"Error displaying results: {str(e)}", "error")
        return redirect(url_for('seo_tools.image_search'))


@seo_tools_bp.route('/download_image_csv')
@login_required
def download_image_csv():
    link = request.args.get('link')
    if not link:
        flash("No link provided for download.")
        return redirect(url_for('seo_tools.image_search'))

    cache_key = f"images_{link}"
    images = cache.get(cache_key)
    if images is None:
        try:
            images = extract_images(link)
            cache.set(cache_key, images)
        except Exception as e:
            flash(f"Error extracting images for download: {str(e)}", "error")
            return redirect(url_for('seo_tools.image_search'))

    try:
        # Ensure the download directory exists
        os.makedirs(download_dir, exist_ok=True)

        # Prepare a path for saving our CSV
        filepath = os.path.join(download_dir, 'Image_analysis.csv')

        # Define CSV fieldnames
        fieldnames = ['Image Number', 'URL', 'Alt Text', 'Title', 'File Extension', 'File Size', 'Resolution', 'Status', 'Error Message']

        # Prepare data for CSV
        csv_data = []
        for idx, img in enumerate(images, 1):
            row = {
                'Image Number': idx,
                'URL': img.get('url', ''),
                'Alt Text': img.get('alt_text', 'None'),
                'Title': img.get('title', 'None'),
                'File Extension': img.get('file_extension', ''),
                'File Size': img.get('file_size', ''),
                'Resolution': img.get('resolution', ''),
                'Status': 'Error' if img.get('is_error', False) else 'Success',
                'Error Message': img.get('error', '') if img.get('is_error', False) else ''
            }
            csv_data.append(row)

        # Write CSV via built-in DictWriter
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_data)

        return send_file(
            filepath,
            mimetype='text/csv',
            as_attachment=True,
            download_name='Image_analysis.csv'
        )
    except Exception as e:
        current_app.logger.error(f'Error generating CSV file: {str(e)}')
        flash(f"Error generating CSV file: {str(e)}", "error")
        return redirect(url_for('seo_tools.image_search'))


@seo_tools_bp.route('/download_single_image', methods=['POST'])
@login_required
def download_single_image():
    """Download a single image in its original format from URL"""
    import tempfile
    import requests as http_requests
    # Import certifi for SSL certificate verification on servers
    try:
        import certifi
        ssl_verify = certifi.where()
    except ImportError:
        ssl_verify = True  # Fall back to system certificates
    # imghdr is deprecated in Python 3.11+ and removed in 3.13, use try-except
    try:
        import imghdr
    except ImportError:
        imghdr = None

    temp_file_path = None

    try:
        data = request.get_json()
        image_url = data.get('url')
        image_number = data.get('image_number', '1')

        if not image_url:
            return jsonify({'error': 'No image URL provided'}), 400

        current_app.logger.info(f'Attempting to download: {image_url}')

        # Enhanced headers to bypass anti-hotlinking and bot detection
        parsed_url = urlparse(image_url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': base_url + '/',
            'Origin': base_url,
            'Sec-Fetch-Dest': 'image',
            'Sec-Fetch-Mode': 'no-cors',
            'Sec-Fetch-Site': 'same-origin',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }

        # Download the image with proper headers and follow redirects
        try:
            response = http_requests.get(
                image_url,
                headers=headers,
                timeout=30,
                verify=ssl_verify,
                allow_redirects=True,
                stream=False
            )
            response.raise_for_status()
        except http_requests.exceptions.SSLError as ssl_err:
            # SSL verification failed, retry without verification
            current_app.logger.warning(f'SSL verification failed, retrying without verification: {ssl_err}')
            response = http_requests.get(
                image_url,
                headers=headers,
                timeout=30,
                verify=False,
                allow_redirects=True,
                stream=False
            )
            response.raise_for_status()

        # Get the actual content
        image_content = response.content

        # CRITICAL: Validate we got actual image content, not HTML
        if not image_content or len(image_content) == 0:
            raise ValueError('Downloaded content is empty')

        # Check if content is HTML instead of image
        content_type = response.headers.get('content-type', '').lower()
        if 'text/html' in content_type or 'application/xhtml' in content_type:
            raise ValueError('Server returned HTML page instead of image. The website may be blocking direct image downloads.')

        # Additional check: look for HTML tags in content
        try:
            content_start = image_content[:500].decode('utf-8', errors='ignore').lower()
            if '<!doctype html' in content_start or '<html' in content_start or '<head>' in content_start:
                raise ValueError('Server returned HTML page instead of image. This website has anti-hotlinking protection.')
        except UnicodeDecodeError:
            pass  # Binary content, which is good for images

        current_app.logger.info(f'Downloaded content: {len(image_content)} bytes, Content-Type: {content_type}')

        # Debug: Log first 16 bytes of content
        if len(image_content) >= 16:
            hex_bytes = ' '.join(f'{b:02X}' for b in image_content[:16])
            current_app.logger.info(f'First 16 bytes (hex): {hex_bytes}')

        # Detect format from magic bytes (file signature) - MOST RELIABLE METHOD
        def detect_format_from_magic_bytes(content):
            """Detect image format by checking file signature (magic bytes)"""
            if not content or len(content) < 4:
                current_app.logger.warning('Content too short for magic bytes detection')
                return None, None

            # Log the first few bytes for debugging
            if len(content) >= 12:
                first_bytes = content[:12]
                current_app.logger.info(f'Magic bytes check - First 12 bytes: {first_bytes.hex()}')

            # PNG: 89 50 4E 47 0D 0A 1A 0A
            if len(content) >= 8 and content[:8] == b'\x89PNG\r\n\x1a\n':
                current_app.logger.info('PNG signature detected!')
                return '.png', 'image/png'

            # JPEG: FF D8 FF
            if len(content) >= 3 and content[0:3] == b'\xff\xd8\xff':
                current_app.logger.info('JPEG signature detected!')
                return '.jpg', 'image/jpeg'

            # GIF: 47 49 46 38 (GIF8)
            if len(content) >= 4 and content[:4] in (b'GIF8', b'GIF89a', b'GIF87a'):
                current_app.logger.info('GIF signature detected!')
                return '.gif', 'image/gif'

            # WebP: RIFF....WEBP
            if len(content) >= 12 and content[:4] == b'RIFF' and content[8:12] == b'WEBP':
                current_app.logger.info('WebP signature detected!')
                return '.webp', 'image/webp'

            # BMP: 42 4D (BM)
            if len(content) >= 2 and content[:2] == b'BM':
                current_app.logger.info('BMP signature detected!')
                return '.bmp', 'image/bmp'

            # TIFF: 49 49 2A 00 (little-endian) or 4D 4D 00 2A (big-endian)
            if len(content) >= 4:
                if content[:4] == b'II\x2a\x00' or content[:4] == b'MM\x00\x2a':
                    current_app.logger.info('TIFF signature detected!')
                    return '.tiff', 'image/tiff'

            # ICO: 00 00 01 00
            if len(content) >= 4 and content[:4] == b'\x00\x00\x01\x00':
                current_app.logger.info('ICO signature detected!')
                return '.ico', 'image/x-icon'

            # AVIF: Check for ftyp box with avif
            if len(content) >= 12 and content[4:8] == b'ftyp':
                if b'avif' in content[8:20] or b'avis' in content[8:20]:
                    current_app.logger.info('AVIF signature detected!')
                    return '.avif', 'image/avif'

            # SVG: Check for XML/SVG tag
            try:
                text_start = content[:200].decode('utf-8', errors='ignore').lower()
                if '<svg' in text_start or ('<?xml' in text_start and 'svg' in text_start):
                    current_app.logger.info('SVG signature detected!')
                    return '.svg', 'image/svg+xml'
            except:
                pass

            current_app.logger.warning('No magic bytes signature matched')
            return None, None

        # PRIORITY 1: Try detection from magic bytes - MOST RELIABLE
        file_ext = None
        content_type_detected = None

        file_ext, content_type_detected = detect_format_from_magic_bytes(image_content)

        if file_ext and content_type_detected:
            current_app.logger.info(f'Format detected from MAGIC BYTES: {file_ext} ({content_type_detected})')
            content_type = content_type_detected  # Use detected content type
        else:
            # Method 2: Use Python's imghdr module (if available - deprecated in Python 3.11+)
            if imghdr is not None:
                try:
                    detected_type = imghdr.what(None, h=image_content)
                    if detected_type:
                        type_mapping = {
                            'jpeg': ('.jpg', 'image/jpeg'),
                            'png': ('.png', 'image/png'),
                            'gif': ('.gif', 'image/gif'),
                            'bmp': ('.bmp', 'image/bmp'),
                            'tiff': ('.tiff', 'image/tiff'),
                            'webp': ('.webp', 'image/webp')
                        }
                        if detected_type in type_mapping:
                            file_ext, content_type = type_mapping[detected_type]
                            current_app.logger.info(f'Detected format from imghdr: {detected_type} -> {file_ext}')
                except Exception as e:
                    current_app.logger.warning(f'imghdr detection failed: {e}')

        # Method 3: Try Content-Type header from response (only if format still not detected)
        if not file_ext:
            response_content_type = response.headers.get('content-type', '').split(';')[0].strip().lower()
            if response_content_type and response_content_type.startswith('image/'):
                content_type_mapping = {
                    'image/jpeg': ('.jpg', 'image/jpeg'),
                    'image/jpg': ('.jpg', 'image/jpeg'),
                    'image/png': ('.png', 'image/png'),
                    'image/gif': ('.gif', 'image/gif'),
                    'image/webp': ('.webp', 'image/webp'),
                    'image/svg+xml': ('.svg', 'image/svg+xml'),
                    'image/bmp': ('.bmp', 'image/bmp'),
                    'image/x-icon': ('.ico', 'image/x-icon'),
                    'image/tiff': ('.tiff', 'image/tiff'),
                    'image/avif': ('.avif', 'image/avif'),
                    'image/heic': ('.heic', 'image/heic'),
                    'image/heif': ('.heif', 'image/heif')
                }
                if response_content_type in content_type_mapping:
                    file_ext, content_type = content_type_mapping[response_content_type]
                    current_app.logger.info(f'Detected from Content-Type header: {response_content_type} -> {file_ext}')

        # Method 4: Try from URL path (only if still not detected)
        if not file_ext:
            parsed_url = urlparse(image_url)
            url_path = unquote(parsed_url.path)
            url_ext = os.path.splitext(url_path)[-1].lower()
            # Remove query parameters and fragments
            url_ext = url_ext.split('?')[0].split('#')[0]

            if url_ext and len(url_ext) >= 2 and url_ext.startswith('.'):
                # Map common extensions to proper content types
                ext_to_content_type = {
                    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                    '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml',
                    '.bmp': 'image/bmp', '.ico': 'image/x-icon', '.tiff': 'image/tiff',
                    '.tif': 'image/tiff', '.avif': 'image/avif', '.heic': 'image/heic',
                    '.heif': 'image/heif'
                }
                file_ext = url_ext
                content_type = ext_to_content_type.get(url_ext, 'image/jpeg')
                current_app.logger.info(f'Detected extension from URL: {file_ext}')

        # FINAL VALIDATION: Check if we detected a valid image format
        if not file_ext or len(file_ext) < 2:
            raise ValueError('Could not detect image format. The downloaded content may not be a valid image file.')

        # Ensure content_type is set
        if not content_type:
            ext_without_dot = file_ext[1:] if file_ext.startswith('.') else file_ext
            content_type_map = {
                'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
                'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml',
                'bmp': 'image/bmp', 'ico': 'image/x-icon', 'tiff': 'image/tiff',
                'tif': 'image/tiff', 'avif': 'image/avif', 'heic': 'image/heic',
                'heif': 'image/heif'
            }
            content_type = content_type_map.get(ext_without_dot, 'image/jpeg')

        # Create filename with proper extension
        filename = f'image_{image_number}{file_ext}'

        # Create temporary file with proper extension
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=file_ext, mode='wb')
        temp_file_path = temp_file.name
        temp_file.write(image_content)
        temp_file.close()

        current_app.logger.info(f'Created temp file: {temp_file_path}, Filename: {filename}, Content-Type: {content_type}, Size: {len(image_content)} bytes')

        # Create response with proper headers
        @after_this_request
        def cleanup(response):
            try:
                if temp_file_path and os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                    current_app.logger.info(f'Cleaned up temp file: {temp_file_path}')
            except Exception as e:
                current_app.logger.error(f'Error cleaning up temp file: {e}')
            return response

        # Send file with proper mimetype and filename
        return send_file(
            temp_file_path,
            mimetype=content_type,
            as_attachment=True,
            download_name=filename
        )

    except http_requests.RequestException as e:
        current_app.logger.error(f'Error downloading image from {image_url}: {str(e)}')
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except:
                pass

        # Provide user-friendly error message
        error_msg = str(e)
        if 'SSL' in error_msg or 'certificate' in error_msg.lower():
            error_msg = 'SSL certificate verification failed. The website may have security issues.'
        elif 'timeout' in error_msg.lower():
            error_msg = 'Connection timeout. The server is taking too long to respond.'
        elif '403' in error_msg:
            error_msg = 'Access forbidden. The website is blocking automated downloads.'
        elif '404' in error_msg:
            error_msg = 'Image not found. The URL may be incorrect or the image has been removed.'

        return jsonify({'error': f'Failed to download image: {error_msg}'}), 500

    except ValueError as e:
        # Handle validation errors
        current_app.logger.error(f'Validation error: {str(e)}')
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except:
                pass
        return jsonify({'error': str(e)}), 400

    except Exception as e:
        current_app.logger.error(f'Unexpected error in download_single_image: {str(e)}')
        current_app.logger.error(traceback.format_exc())
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except:
                pass
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500


@seo_tools_bp.route('/download_images_zip', methods=['POST'])
@login_required
def download_images_zip():
    """Download multiple images as a ZIP file in their original formats"""
    import tempfile
    import zipfile
    import requests as http_requests
    # Import certifi for SSL certificate verification on servers
    try:
        import certifi
        ssl_verify = certifi.where()
    except ImportError:
        ssl_verify = True  # Fall back to system certificates
    # imghdr is deprecated in Python 3.11+ and removed in 3.13, use try-except
    try:
        import imghdr
    except ImportError:
        imghdr = None

    temp_zip_path = None

    try:
        data = request.get_json()
        images = data.get('images', [])

        if not images:
            return jsonify({'error': 'No images provided'}), 400

        current_app.logger.info(f'Creating ZIP file with {len(images)} images')

        # Create temporary ZIP file
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip', mode='wb')
        temp_zip_path = temp_zip.name
        temp_zip.close()

        current_app.logger.info(f'Creating ZIP at: {temp_zip_path}')

        # Detect image format from magic bytes
        def detect_format_from_magic_bytes(content):
            """Detect image format by checking file signature (magic bytes)"""
            if not content or len(content) < 4:
                return None

            # PNG: 89 50 4E 47 0D 0A 1A 0A
            if len(content) >= 8 and content[:8] == b'\x89PNG\r\n\x1a\n':
                return '.png'

            # JPEG: FF D8 FF
            if len(content) >= 3 and content[0:3] == b'\xff\xd8\xff':
                return '.jpg'

            # GIF: GIF89a or GIF87a
            if len(content) >= 4 and content[:4] in (b'GIF8', b'GIF89a', b'GIF87a'):
                return '.gif'

            # WebP: RIFF....WEBP
            if len(content) >= 12 and content[:4] == b'RIFF' and content[8:12] == b'WEBP':
                return '.webp'

            # BMP: BM
            if len(content) >= 2 and content[:2] == b'BM':
                return '.bmp'

            # TIFF: II or MM (little-endian or big-endian)
            if len(content) >= 4:
                if content[:4] == b'II\x2a\x00' or content[:4] == b'MM\x00\x2a':
                    return '.tiff'

            # ICO: 00 00 01 00
            if len(content) >= 4 and content[:4] == b'\x00\x00\x01\x00':
                return '.ico'

            # AVIF: Check for ftyp box with avif
            if len(content) >= 12 and content[4:8] == b'ftyp':
                if b'avif' in content[8:20] or b'avis' in content[8:20]:
                    return '.avif'

            # SVG: Check for XML/SVG tag
            try:
                text_start = content[:200].decode('utf-8', errors='ignore').lower()
                if '<svg' in text_start or ('<?xml' in text_start and 'svg' in text_start):
                    return '.svg'
            except:
                pass

            return None

        # Validate if content is actually an image
        def validate_image_content(content, url):
            """Check if downloaded content is actually an image"""
            # Check for HTML content
            try:
                content_start = content[:500].decode('utf-8', errors='ignore').lower()
                if '<!doctype html' in content_start or '<html' in content_start or '<head>' in content_start:
                    return False, 'HTML page returned instead of image (anti-hotlinking protection)'
            except UnicodeDecodeError:
                pass  # Binary content, which is good

            # Check if we can detect any image format
            detected_format = detect_format_from_magic_bytes(content)
            if not detected_format:
                # Try imghdr as backup (if available)
                if imghdr is not None:
                    try:
                        detected_type = imghdr.what(None, h=content)
                        if not detected_type:
                            return False, 'Not a valid image format'
                    except:
                        return False, 'Not a valid image format'
                else:
                    # imghdr not available, assume valid if we got here
                    pass

            return True, None

        # Create ZIP file with compression
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zip_file:
            successful_downloads = 0
            failed_downloads = 0
            used_filenames = set()  # Track used filenames to avoid duplicates

            for idx, image_data in enumerate(images, 1):
                image_url = image_data.get('url')
                image_number = image_data.get('image_number', idx)

                try:
                    current_app.logger.info(f'Downloading image {idx}/{len(images)}: {image_url}')

                    # Enhanced headers to bypass anti-hotlinking
                    parsed_url = urlparse(image_url)
                    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Connection': 'keep-alive',
                        'Referer': base_url + '/',
                        'Origin': base_url,
                        'Sec-Fetch-Dest': 'image',
                        'Sec-Fetch-Mode': 'no-cors',
                        'Sec-Fetch-Site': 'same-origin',
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache'
                    }

                    # Download image with SSL verification, fallback to no verification
                    try:
                        response = http_requests.get(
                            image_url,
                            headers=headers,
                            timeout=30,
                            verify=ssl_verify,
                            allow_redirects=True
                        )
                        response.raise_for_status()
                    except http_requests.exceptions.SSLError as ssl_err:
                        # SSL verification failed, retry without verification
                        current_app.logger.warning(f'SSL verification failed for {image_url}, retrying: {ssl_err}')
                        response = http_requests.get(
                            image_url,
                            headers=headers,
                            timeout=30,
                            verify=False,
                            allow_redirects=True
                        )
                        response.raise_for_status()

                    # Get image content
                    image_content = response.content

                    # Verify content
                    if not image_content or len(image_content) == 0:
                        raise ValueError('Downloaded content is empty')

                    # VALIDATE: Check if content is actually an image
                    is_valid, error_reason = validate_image_content(image_content, image_url)
                    if not is_valid:
                        raise ValueError(error_reason)

                    current_app.logger.info(f'Downloaded image {idx}: {len(image_content)} bytes')

                    # Detect actual image format using multiple methods
                    file_ext = detect_format_from_magic_bytes(image_content)

                    if file_ext:
                        current_app.logger.info(f'Image {idx} detected format from magic bytes: {file_ext}')

                    # Method 2: Use Python's imghdr module as fallback (if available)
                    if not file_ext and imghdr is not None:
                        try:
                            detected_type = imghdr.what(None, h=image_content)
                            if detected_type:
                                type_to_ext = {
                                    'jpeg': '.jpg', 'png': '.png', 'gif': '.gif',
                                    'bmp': '.bmp', 'tiff': '.tiff', 'webp': '.webp'
                                }
                                file_ext = type_to_ext.get(detected_type, f'.{detected_type}')
                                current_app.logger.info(f'Image {idx} detected format from imghdr: {detected_type} -> {file_ext}')
                        except Exception as e:
                            current_app.logger.warning(f'Image {idx} imghdr detection failed: {e}')

                    # Method 3: Try Content-Type header
                    if not file_ext:
                        resp_content_type = response.headers.get('content-type', '').split(';')[0].strip().lower()
                        if resp_content_type and resp_content_type.startswith('image/'):
                            content_type_to_ext = {
                                'image/jpeg': '.jpg', 'image/jpg': '.jpg', 'image/png': '.png',
                                'image/gif': '.gif', 'image/webp': '.webp', 'image/svg+xml': '.svg',
                                'image/bmp': '.bmp', 'image/x-icon': '.ico', 'image/tiff': '.tiff',
                                'image/avif': '.avif', 'image/heic': '.heic', 'image/heif': '.heif'
                            }
                            file_ext = content_type_to_ext.get(resp_content_type)
                            if file_ext:
                                current_app.logger.info(f'Image {idx} detected extension from Content-Type: {resp_content_type} -> {file_ext}')

                    # Method 4: Try from URL
                    if not file_ext:
                        parsed_url = urlparse(image_url)
                        url_path = unquote(parsed_url.path)
                        url_ext = os.path.splitext(url_path)[-1].lower()
                        url_ext = url_ext.split('?')[0].split('#')[0]

                        if url_ext and len(url_ext) >= 2 and url_ext.startswith('.'):
                            file_ext = url_ext
                            current_app.logger.info(f'Image {idx} detected extension from URL: {file_ext}')

                    # If still no extension detected, this is probably not an image
                    if not file_ext or len(file_ext) < 2:
                        raise ValueError('Could not detect valid image format')

                    # Create unique filename
                    base_filename = f'image_{image_number}{file_ext}'
                    filename = base_filename
                    counter = 1

                    # Ensure unique filename in ZIP
                    while filename in used_filenames:
                        filename = f'image_{image_number}_{counter}{file_ext}'
                        counter += 1

                    used_filenames.add(filename)

                    # Write to ZIP file - CRITICAL: Use writestr with bytes
                    zip_file.writestr(filename, image_content)
                    successful_downloads += 1
                    current_app.logger.info(f'Successfully added to ZIP: {filename} ({len(image_content)} bytes)')

                except http_requests.RequestException as e:
                    failed_downloads += 1
                    error_msg = f'Failed to download image {idx}\nURL: {image_url}\nError: {str(e)}'

                    # Add user-friendly error details
                    if 'SSL' in str(e) or 'certificate' in str(e).lower():
                        error_msg += '\n\nReason: SSL certificate verification failed'
                    elif 'timeout' in str(e).lower():
                        error_msg += '\n\nReason: Connection timeout'
                    elif '403' in str(e):
                        error_msg += '\n\nReason: Access forbidden (website blocking downloads)'
                    elif '404' in str(e):
                        error_msg += '\n\nReason: Image not found'

                    current_app.logger.error(error_msg)
                    error_filename = f'ERROR_image_{image_number}.txt'
                    zip_file.writestr(error_filename, error_msg)

                except ValueError as e:
                    failed_downloads += 1
                    error_msg = f'Failed to process image {idx}\nURL: {image_url}\nError: {str(e)}'
                    current_app.logger.error(error_msg)
                    error_filename = f'ERROR_image_{image_number}.txt'
                    zip_file.writestr(error_filename, error_msg)

                except Exception as e:
                    failed_downloads += 1
                    error_msg = f'Failed to process image {idx}\nURL: {image_url}\nError: {str(e)}\n\n{traceback.format_exc()}'
                    current_app.logger.error(error_msg)
                    error_filename = f'ERROR_image_{image_number}.txt'
                    zip_file.writestr(error_filename, error_msg)

            # Add summary file
            summary = f"""Download Summary
================
Total images requested: {len(images)}
Successfully downloaded: {successful_downloads}
Failed downloads: {failed_downloads}

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Note: If images failed with "anti-hotlinking protection" errors,
the website is blocking direct downloads of images. This is a common
security measure used by many websites.
"""
            zip_file.writestr('DOWNLOAD_SUMMARY.txt', summary)

            current_app.logger.info(f'Download summary: {successful_downloads} successful, {failed_downloads} failed')

        # CRITICAL: Verify ZIP file was created successfully
        if not os.path.exists(temp_zip_path):
            raise ValueError('ZIP file was not created')

        zip_size = os.path.getsize(temp_zip_path)
        current_app.logger.info(f'ZIP file created successfully: {temp_zip_path}, Size: {zip_size} bytes')

        if zip_size == 0:
            raise ValueError('ZIP file is empty - no content was added')

        if zip_size < 100:  # Suspiciously small
            current_app.logger.warning(f'ZIP file is very small ({zip_size} bytes), might be corrupted')

        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_filename = f'images_{timestamp}.zip'

        # FIXED: Read file into memory to avoid Windows file locking issue
        with open(temp_zip_path, 'rb') as f:
            zip_data = f.read()

        # Now we can safely delete the temp file
        try:
            os.unlink(temp_zip_path)
            current_app.logger.info(f'Cleaned up temp ZIP file: {temp_zip_path}')
        except Exception as e:
            current_app.logger.error(f'Error cleaning up temp ZIP file: {e}')
            # Schedule background cleanup if immediate deletion fails
            def delayed_cleanup():
                time.sleep(5)
                try:
                    if os.path.exists(temp_zip_path):
                        os.unlink(temp_zip_path)
                        current_app.logger.info(f'Delayed cleanup succeeded for: {temp_zip_path}')
                except Exception as cleanup_err:
                    current_app.logger.warning(f'Delayed cleanup also failed: {cleanup_err}')

            cleanup_thread = threading.Thread(target=delayed_cleanup, daemon=True)
            cleanup_thread.start()

        # Send the ZIP file from memory
        current_app.logger.info(f'Sending ZIP file: {zip_filename}')
        return send_file(
            BytesIO(zip_data),
            mimetype='application/zip',
            as_attachment=True,
            download_name=zip_filename
        )

    except Exception as e:
        current_app.logger.error(f'Error creating ZIP file: {str(e)}')
        current_app.logger.error(traceback.format_exc())

        # Clean up on error
        if temp_zip_path and os.path.exists(temp_zip_path):
            try:
                os.unlink(temp_zip_path)
                current_app.logger.info(f'Cleaned up temp ZIP file after error: {temp_zip_path}')
            except Exception as cleanup_error:
                current_app.logger.error(f'Error cleaning up temp ZIP file: {cleanup_error}')

        return jsonify({'error': f'Failed to create ZIP file: {str(e)}'}), 500


# --------------------------------
# Heading Search Routes
# --------------------------------
@seo_tools_bp.route('/h_search', methods=['GET', 'POST'])
@login_required
@subscription_check_only
def h_search():
    # Clear cache when entering route fresh (not from POST)
    if request.method == 'GET' and not request.args.get('from_post'):
        clear_search_results('h_search')
    url_input = ""
    links_data = None
    robots_info = None

    # Check for explicit refresh
    is_refresh = request.args.get('refresh') == 'true'
    if is_refresh:
        clear_search_results('h_search')
        return redirect(url_for('seo_tools.h_search'))

    if request.method == 'POST':
        url_input = request.form.get('url')
        respect_robots = request.form.get('respect_robots') == 'on'

        if url_input:
            try:
                current_app.logger.info(f"Heading search POST: analyzing {url_input}")
                home_links, other_links, robots_info = analyze_links(
                    url=url_input,
                    respect_robots=respect_robots
                )

                # Store in cache
                store_search_results('h_search', url_input, home_links, other_links, robots_info)
                # Note: Search history is added in h_detail which consumes tokens

                # Prepare data for immediate display (no redirect)
                links_data = {'home': home_links, 'other': other_links}
                current_app.logger.info(f"Returning results immediately without redirect")

            except Exception as e:
                current_app.logger.error(f"Error in h_search: {str(e)}")
                flash(f"Error analyzing URL: {str(e)}", "danger")
                return redirect(url_for('seo_tools.h_search'))
    else:
        # GET request - retrieve from cache
        url_input, links_data, robots_info = get_search_results('h_search')
        if links_data:
            current_app.logger.info(f"Retrieved h_search results from cache")

    return render_template(
        'h_search.html',
        url_input=url_input,
        links_data=links_data,
        robots_info=robots_info
    )


@seo_tools_bp.route('/h_detail', methods=['GET'])
@login_required
@subscription_required_with_tokens(1)
def h_detail():
    url_input = request.args.get('url')
    if not url_input:
        flash("No URL provided for H Tags analysis.")
        return redirect(url_for('seo_tools.h_search'))

    # Extract headings in DOM order
    headings_in_order = extract_headings_in_order(url_input)

    # Record search history only on successful extraction, remove if no results
    u_id = session.get('user_id')
    if headings_in_order:
        add_search_history(u_id, "Heading Analysis", url_input)
    else:
        remove_search_history(u_id, url_input)

    # Count how many of each tag
    tag_counts = Counter(h["tag"] for h in headings_in_order)

    # Get home links from cache
    stored_url, links_data, robots_info = get_search_results('h_search')
    home_links = links_data.get('home', []) if links_data else []
    # If no home links in cache, analyze the URL to get related links
    if not home_links:
        try:
            current_app.logger.info(f"No cached links found, analyzing {url_input} for related links")
            home_links_new, other_links, robots_info = analyze_links(
                url=url_input,
                respect_robots=True
            )
            home_links = home_links_new
            current_app.logger.info(f"Found {len(home_links)} related links")
        except Exception as e:
            current_app.logger.error(f"Error analyzing links: {str(e)}")
            home_links = []

    # Check if all H1s are under 60 chars
    h1_headings = [h for h in headings_in_order if h['tag'] == 'h1']
    all_h1_under_60 = all(len(h['text']) < 60 for h in h1_headings)

    return render_template(
        'h_detail.html',
        url_input=url_input,
        headings_in_order=headings_in_order,
        tag_counts=tag_counts,
        home_links=home_links,
        all_h1_under_60=all_h1_under_60
    )


@seo_tools_bp.route('/download_h_csv')
@login_required
def download_h_csv():
    url_input = request.args.get('url')
    if not url_input:
        flash("No URL provided for download.")
        return redirect(url_for('seo_tools.h_search'))

    # Use the function that returns headings in order
    headings_in_order = extract_headings_in_order(url_input)

    # Convert data into a list of dictionaries for CSV
    data = []
    for h in headings_in_order:
        data.append({
            'Tag': h['tag'].upper(),
            'Heading': h['text'],
            'HeadingLength': len(h['text']),
            'Level': h['level']
        })

    # Ensure the download directory exists
    os.makedirs(download_dir, exist_ok=True)

    # Write CSV via built-in csv library
    file_path = os.path.join(download_dir, 'headings.csv')
    with open(file_path, 'w', newline='', encoding='utf-8') as csv_file:
        fieldnames = ['Tag', 'Heading', 'HeadingLength', 'Level']
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

    return send_file(
        file_path,
        mimetype='text/csv',
        as_attachment=True,
        download_name='Heading_analysis.csv'
    )


# --------------------------------
# Meta Search Routes
# --------------------------------
@seo_tools_bp.route('/meta_search', methods=['GET', 'POST'])
@login_required
@subscription_check_only
def meta_search():
    # Clear cache when entering route fresh (not from POST)
    if request.method == 'GET' and not request.args.get('from_post'):
        clear_search_results('meta_search')
    links_data = None
    url_input = ""
    robots_info = None

    # Check for explicit refresh
    is_refresh = request.args.get('refresh') == 'true'
    if is_refresh:
        clear_search_results('meta_search')
        return redirect(url_for('seo_tools.meta_search'))

    if request.method == 'POST':
        url_input = request.form.get('url')
        # Get URL from the mobile input if desktop input is empty
        if not url_input:
            url_input = request.form.get('mobile-url')

        respect_robots = request.form.get('respect_robots') == 'on'

        if url_input:
            try:
                current_app.logger.info(f"Meta search POST: analyzing {url_input}")
                home_links, other_links, robots_info = analyze_links(
                    url=url_input,
                    respect_robots=respect_robots
                )

                # Store in cache
                store_search_results('meta_search', url_input, home_links, other_links, robots_info)
                # Note: Search history is added in meta_detail which consumes tokens

                # Prepare data for immediate display (no redirect)
                links_data = {'home': home_links, 'other': other_links}
                current_app.logger.info(f"Returning results immediately without redirect")

            except Exception as e:
                current_app.logger.error(f"Error in meta_search: {str(e)}")
                flash("An error occurred while analyzing the URL. Please try again.", "danger")
                return redirect(url_for('seo_tools.meta_search'))
    else:
        # GET request - retrieve from cache
        url_input, links_data, robots_info = get_search_results('meta_search')
        if links_data:
            current_app.logger.info(f"Retrieved meta_search results from cache")

    return render_template(
        'meta_search.html',
        url_input=url_input,
        links_data=links_data,
        robots_info=robots_info
    )


@seo_tools_bp.route('/meta_detail')
@login_required
@subscription_required_with_tokens(2)
def meta_detail():
    link = request.args.get('link')
    if not link:
        flash("No link provided for meta analysis.", "warning")
        return redirect(url_for('seo_tools.meta_search'))

    try:
        # Get links data from cache if available
        stored_url, links_data, robots_info = get_search_results('meta_search')

        # If no cached data, analyze the link
        if not links_data:
            home_links, other_links, robots_info = analyze_links(url=link)
            links_data = {
                'home': home_links,
                'other': other_links
            }

        # Extract meta information
        meta_info = extract_seo_data(link)

        u_id = session.get('user_id')
        if meta_info.get('error'):
            # Remove search history on error
            remove_search_history(u_id, link)
            flash(meta_info['error'], 'danger')
            return redirect(url_for('seo_tools.meta_search'))

        # Record search history only on successful extraction
        add_search_history(u_id, "Meta Analysis", link)

        return render_template(
            'meta_detail.html',
            link=link,
            meta_info=meta_info,
            links_data=links_data,
            robots_info=robots_info
        )

    except Exception as e:
        current_app.logger.error(f"Error in meta_detail: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        # Remove search history on error
        u_id = session.get('user_id')
        remove_search_history(u_id, link)
        flash("An error occurred while analyzing the URL.", "danger")
        return redirect(url_for('seo_tools.meta_search'))


@seo_tools_bp.route('/download_meta_csv')
@login_required
def download_meta_csv():
    link = request.args.get('link')
    if not link:
        flash("No link provided for download.")
        return redirect(url_for('seo_tools.meta_search'))

    meta_info = extract_seo_data(link)
    if meta_info.get('error'):
        flash(meta_info['error'])
        return redirect(url_for('seo_tools.meta_search'))

    # Convert the SEO data into a CSV-friendly format
    data = []
    # Title row
    data.append({
        'Type': 'title',
        'Attribute': 'title',
        'Content': meta_info['title']
    })
    # Meta tags
    for m in meta_info['meta_tags']:
        data.append({
            'Type': 'meta',
            'Attribute': m['attribute'],
            'Content': m['content']
        })
    # Schema (JSON-LD)
    for s in meta_info['schema']:
        data.append({
            'Type': 'schema',
            'Attribute': 'JSON-LD',
            'Content': json.dumps(s)  # convert the schema object to a JSON string
        })

    # Ensure the download directory exists
    os.makedirs(download_dir, exist_ok=True)

    # Write CSV file using built-in csv
    file_path = os.path.join(download_dir, 'meta_data.csv')
    with open(file_path, 'w', newline='', encoding='utf-8') as csv_file:
        fieldnames = ['Type', 'Attribute', 'Content']
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

    return send_file(
        file_path,
        mimetype='text/csv',
        as_attachment=True,
        download_name='Meta_analysis.csv'
    )


# --------------------------------
# Site Structure Routes
# --------------------------------
@seo_tools_bp.route("/site_structure", methods=["GET", "POST"])
@subscription_check_only
@login_required
def site_structure():
    # Handle GET request with URL parameter (from recent analyses)
    if request.method == "GET":
        url_param = request.args.get('url')
        if url_param:
            # Auto-submit the form when URL is provided via GET parameter
            return render_template("site_structure.html", auto_submit_url=url_param)
        else:
            # Regular GET request - show empty form
            return render_template("site_structure.html")

    # Handle POST request (form submission)
    if request.method == "POST":
        start_url = request.form["url"]

        if not start_url:
            return render_template("site_structure.html", error="Please provide a URL.")
        if not start_url.startswith("http"):
            start_url = "http://" + start_url

        # Create a unique ID for this crawl job
        job_id = str(uuid.uuid4())

        # CRITICAL: Set session data and force save
        session['job_id'] = job_id
        session['crawl_url'] = start_url  # Store URL as backup
        session.modified = True  # Ensure session is saved

        # Debug logging
        current_app.logger.info(f"SESSION BEFORE SAVE: job_id={session.get('job_id')}, user_id={session.get('user_id')}")

        crawl_status[job_id] = {
            'status': 'running',
            'progress': 0,
            'url': start_url,
            'start_time': time.time()
        }

        current_app.logger.info(f"Created crawl job {job_id} for URL: {start_url}")

        # Run the crawler in a background thread with app context
        try:
            app = current_app._get_current_object()
            coro = main_crawl(start_url, job_id)
            def run_with_context(app, coro, job_id):
                with app.app_context():
                    return run_async_in_thread_with_progress(coro, job_id)
            executor.submit(run_with_context, app, coro, job_id)
            current_app.logger.info(f"Crawler submitted to executor for job {job_id}")
        except Exception as e:
            current_app.logger.error(f"Error submitting crawler: {e}")
            crawl_status[job_id]['status'] = 'failed'
            return render_template("site_structure.html", error="An error occurred while crawling the URL.")

        current_app.logger.info(f"Redirecting to loading page for job {job_id}")

        # Create redirect response and ensure session cookie is set
        response = make_response(redirect(url_for("seo_tools.loading")))
        response.set_cookie('job_id_backup', job_id, max_age=3600)  # Backup cookie for 1 hour
        return response

    return render_template("site_structure.html")


@seo_tools_bp.route("/loading")
@login_required
@subscription_check_only
def loading():
    """Loading page - tokens already checked in POST request"""
    # Try to get job_id from session first
    job_id = session.get('job_id')

    # Debug logging
    current_app.logger.info(f"SESSION ON LOADING: job_id={job_id}, session_keys={list(session.keys())}")

    # If not in session, try backup cookie
    if not job_id:
        job_id = request.cookies.get('job_id_backup')
        current_app.logger.info(f"Trying backup cookie: job_id_backup={job_id}")

        # If found in cookie, restore to session
        if job_id:
            session['job_id'] = job_id
            session.modified = True
            current_app.logger.info(f"Restored job_id from backup cookie: {job_id}")

    if not job_id or job_id not in crawl_status:
        current_app.logger.warning(f"Loading page accessed without valid job_id. job_id={job_id}, crawl_status_keys={list(crawl_status.keys())[:5]}")
        flash("No active crawl job found. Please start a new crawl.", "warning")
        return redirect(url_for("seo_tools.site_structure"))

    current_app.logger.info(f"Loading page accessed for job_id: {job_id}, status: {crawl_status[job_id]['status']}")
    return render_template("loading.html", job_id=job_id)


@seo_tools_bp.route("/progress/<job_id>")
def progress(job_id):
    if job_id not in crawl_status:
        return jsonify({"status": "unknown"})

    status_data = crawl_status[job_id]

    # Calculate elapsed time
    elapsed = time.time() - status_data['start_time']

    # Return actual progress from Redis (no simulation)
    return jsonify({
        "status": status_data['status'],
        "progress": min(round(status_data['progress'], 1), 100),
        "elapsed": round(elapsed, 1),
        "url": status_data['url']
    })


@seo_tools_bp.route("/visualize")
@login_required
@subscription_required_with_tokens(2)
def visualize():
    """
    Display sitemap visualization results.
    Token consumption and usage logging handled by decorator.
    """
    user_id = session.get('user_id')
    job_id = session.get('job_id')

    current_app.logger.info(f"Visualize page requested for job_id: {job_id} by user: {user_id}")

    if not job_id:
        current_app.logger.warning("No job_id in session, redirecting to site_structure")
        flash("No crawl job found. Please start a new crawl.", "warning")
        return redirect(url_for("seo_tools.site_structure"))

    # ENHANCED STATUS CHECKING
    if job_id in crawl_status:
        status = crawl_status[job_id]['status']
        progress_val = crawl_status[job_id].get('progress', 0)
        current_app.logger.info(f"Crawl status for {job_id}: {status} ({progress_val}%)")

        if status == 'running':
            current_app.logger.info("Crawl still running, redirecting to loading page")
            return redirect(url_for("seo_tools.loading"))
        elif status == 'failed':
            current_app.logger.error("Crawl failed, redirecting to site_structure")
            flash("Crawl failed. Please try again.", "danger")
            return redirect(url_for("seo_tools.site_structure"))

    # CHECK IF DATA FILE EXISTS
    crawled_data = f"crawled_data/crawl_{job_id}.json"
    if not os.path.exists(crawled_data):
        current_app.logger.warning(f"Data file missing: {crawled_data}")
        flash("Crawl data not found. Please start a new crawl.", "warning")
        return redirect(url_for("seo_tools.site_structure"))

    # Record search history only on successful crawl completion
    crawl_url = crawl_status.get(job_id, {}).get('url', '')
    if crawl_url:
        add_search_history(user_id, "Sitemap Analysis", crawl_url)

    current_app.logger.info("Rendering visualize.html")
    return render_template("visualize.html", job_id=job_id)


@seo_tools_bp.route("/data")
@csrf.exempt
def get_data():
    """Return crawl data as JSON with enhanced error handling."""
    try:
        # Check if user has session and is logged in
        user_id = session.get('user_id')
        if not user_id:
            current_app.logger.warning("No user_id in session for data request")
            return jsonify({
                "error": "Authentication required",
                "home_links": {},
                "status_codes": {},
                "other_links": {}
            }), 401

        job_id = session.get('job_id')
        current_app.logger.info(f"Data request for job_id: {job_id} by user: {user_id}")

        if not job_id:
            current_app.logger.warning("No job_id in session for data request")
            return jsonify({
                "error": "No crawl job found. Please start a new crawl.",
                "home_links": {},
                "status_codes": {},
                "other_links": {},
                "redirect": "/site_structure"
            }), 404

        # ENHANCED CRAWL STATUS CHECK
        if job_id in crawl_status:
            status = crawl_status[job_id]['status']
            progress_val = crawl_status[job_id].get('progress', 0)
            current_app.logger.info(f"Crawl status for {job_id}: {status} ({progress_val}%)")

            if status == 'running':
                return jsonify({
                    "error": "Crawl still in progress",
                    "status": "running",
                    "progress": progress_val,
                    "message": f"Crawl is {progress_val}% complete. Please wait...",
                    "redirect": "/loading"
                }), 202
            elif status == 'failed':
                return jsonify({
                    "error": "Crawl failed",
                    "status": "failed",
                    "message": "The website crawl failed. Please try again.",
                    "redirect": "/site_structure"
                }), 500

        # ENHANCED FILE EXISTENCE CHECK
        crawled_data_path = f"crawled_data/crawl_{job_id}.json"
        current_app.logger.info(f"Looking for data file: {crawled_data_path}")

        if not os.path.exists(crawled_data_path):
            current_app.logger.warning(f"Data file missing: {crawled_data_path}")

            # Wait a bit for file to be written
            for i in range(3):  # Wait up to 3 seconds
                time.sleep(1)
                if os.path.exists(crawled_data_path):
                    break

            if not os.path.exists(crawled_data_path):
                return jsonify({
                    "error": "Crawl data not found",
                    "message": "The crawl data file is missing. Please start a new crawl.",
                    "redirect": "/site_structure",
                    "debug_info": {
                        "job_id": job_id,
                        "expected_file": crawled_data_path
                    }
                }), 404

        # ENHANCED FILE SIZE CHECK
        try:
            file_size = os.path.getsize(crawled_data_path)
            if file_size == 0:
                current_app.logger.error(f"Data file is empty: {crawled_data_path}")
                return jsonify({
                    "error": "Empty crawl data",
                    "message": "The crawl data file is empty. Please start a new crawl.",
                    "redirect": "/site_structure"
                }), 500
        except Exception as e:
            current_app.logger.error(f"Error checking file size: {str(e)}")

        # Load the actual data
        data = load_results()

        # ENHANCED DATA VALIDATION
        if not data or not isinstance(data, dict):
            current_app.logger.error(f"Invalid data structure loaded for job {job_id}")
            return jsonify({
                "error": "Invalid data structure",
                "message": "The crawl data is corrupted. Please start a new crawl.",
                "home_links": {},
                "status_codes": {},
                "other_links": {},
                "redirect": "/site_structure"
            }), 500

        # Ensure required keys exist with defaults
        home_links = data.get("home_links", {})
        status_codes = data.get("status_codes", {})
        other_links = data.get("other_links", {})

        # VALIDATE DATA IS NOT EMPTY
        if not home_links and not other_links:
            current_app.logger.warning(f"No link data found for job {job_id}")
            return jsonify({
                "error": "No crawl data found",
                "message": "The crawl completed but found no links. The website might be inaccessible or have no content.",
                "home_links": {},
                "status_codes": {},
                "other_links": {},
                "redirect": "/site_structure"
            }), 404

        # Log data summary
        home_links_count = len(home_links)
        status_codes_count = len(status_codes)
        other_links_count = len(other_links)

        current_app.logger.info(f"Returning data for job {job_id}: {home_links_count} home links, {status_codes_count} status codes, {other_links_count} other links")

        # Build response
        response_data = {
            "home_links": home_links,
            "status_codes": status_codes,
            "other_links": other_links,
            "domain": data.get("domain", ""),
            "status": "success",
            "summary": {
                "home_links_count": home_links_count,
                "status_codes_count": status_codes_count,
                "other_links_count": other_links_count,
                "job_id": job_id
            }
        }

        return jsonify(response_data)

    except Exception as e:
        current_app.logger.error(f"Error in get_data: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({
            "error": f"Server error: {str(e)}",
            "message": "An unexpected error occurred while loading the data.",
            "home_links": {},
            "status_codes": {},
            "other_links": {},
            "redirect": "/site_structure"
        }), 500


@seo_tools_bp.route('/download_results')
@login_required
def download_results():
    # Retrieve the crawl job ID from the session
    job_id = session.get('job_id')
    if not job_id:
        flash("No crawl job found. Please start a new crawl and upload the files again.")
        return redirect(url_for('seo_tools.site_structure'))

    # Build the CSV file path using the job ID
    csv_path = f"crawled_data/crawl_{job_id}.csv"

    if not os.path.exists(csv_path):
        flash("Crawl results file not found or expired. Please start a new crawl and upload the files again.")
        return redirect(url_for('seo_tools.site_structure'))

    return send_file(csv_path, mimetype='text/csv', as_attachment=True, download_name=f'crawl_results_{job_id}.csv')


# --------------------------------
# Content Checker
# --------------------------------
@seo_tools_bp.route("/content-checker")
def content_checker():
    """Serve the main SEO content checker page."""
    return render_template("content_checker.html")


# --------------------------------
# Time & Date
# --------------------------------
@seo_tools_bp.route('/time-date')
def time_and_date_today():
    current_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({"current_time": current_time})
