import logging
import re
import traceback
import requests
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, make_response, current_app
from flask_mail import Message
from flask_wtf.csrf import generate_csrf
from sqlalchemy import text

from extensions import db, mail, csrf
from models import (User, Subscription, SubscribedUser, ContactSubmission, EmailLog,
                    Blog, BlogCategory, WebStory, WebsiteSettings)

UTC = timezone.utc

public_bp = Blueprint('public', __name__)


# ========================
# CSRF TOKEN
# ========================

@public_bp.route('/get-csrf-token')
def get_csrf_token():
    return jsonify({'csrf_token': generate_csrf()})


# ========================
# LANDING & STATIC PAGES
# ========================

@public_bp.route('/')
def landing():
    """Landing page route that doesn't require login"""
    return render_template('landing.html')


@public_bp.route('/technical-seo')
def pillar_technical_seo():
    """Pillar page for Technical SEO guide"""
    return render_template('pillar_technical_seo.html')


@public_bp.route('/privacy')
def privacy():
    return render_template('privacy.html')


@public_bp.route('/terms')
def terms():
    return render_template('terms.html')


@public_bp.route('/about')
def about():
    return render_template('about.html')


@public_bp.route('/cookie-policy')
def cookie_policy():
    return render_template('cookie_policy.html')


@public_bp.route('/help')
def help_page():
    """Help page with comprehensive documentation"""
    return render_template('help.html')


# ========================
# CONTACT
# ========================

@public_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        try:
            # Get form data
            name = request.form.get('name')
            email = request.form.get('email')
            message = request.form.get('message')

            # Validate required fields
            if not all([name, email, message]):
                # Check if AJAX request
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': False, 'message': 'Please fill in all required fields.'}), 400
                flash('Please fill in all required fields.', 'warning')
                return render_template('contact.html')

            # Verify reCAPTCHA v2
            recaptcha_response = request.form.get('g-recaptcha-response')
            secret_key = current_app.config.get('RECAPTCHA_SECRET_KEY')

            if secret_key:
                if not recaptcha_response:
                    current_app.logger.warning("reCAPTCHA validation failed: No response provided")
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'success': False, 'message': 'Please complete the security check.'}), 400
                    flash('Please complete the security check.', 'danger')
                    return render_template('contact.html', name=name, email=email, message=message)

                try:
                    verify_response = requests.post(
                        'https://www.google.com/recaptcha/api/siteverify',
                        data={
                            'secret': secret_key,
                            'response': recaptcha_response,
                            'remoteip': request.remote_addr
                        },
                        timeout=10
                    )
                    verify_result = verify_response.json()

                    if not verify_result.get('success', False):
                        current_app.logger.warning(f"reCAPTCHA validation failed for {email}")
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return jsonify({'success': False, 'message': 'Security verification failed. Please try again.'}), 400
                        flash('Security verification failed. Please try again.', 'danger')
                        return render_template('contact.html', name=name, email=email, message=message)

                except Exception as e:
                    current_app.logger.error(f"reCAPTCHA verification error: {str(e)}")
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'success': False, 'message': 'Security check error. Please try again.'}), 500
                    flash('Security check error. Please try again.', 'danger')
                    return render_template('contact.html', name=name, email=email, message=message)

            # Save to database first
            contact_submission = ContactSubmission(
                name=name,
                email=email,
                message=message,
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent', '')
            )

            db.session.add(contact_submission)
            db.session.commit()

            # Send email to support
            subject = f"SEO Dada Contact Form: {name}"
            msg = Message(
                subject=subject,
                sender=current_app.config['MAIL_USERNAME'],
                recipients=[current_app.config['MAIL_USERNAME']]
            )

            # Include submission ID in email for tracking
            msg.body = f"""
            Contact Form Submission (ID: {contact_submission.id}):

            Name: {name}
            Email: {email}
            IP Address: {request.remote_addr}
            Submitted: {contact_submission.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}

            Message:
            {message}
            """

            mail.send(msg)

            # Send auto-reply
            auto_reply = Message(
                subject="Thank you for contacting SEO Dada",
                sender=current_app.config['MAIL_USERNAME'],
                recipients=[email]
            )

            auto_reply.body = f"""
            Dear {name},

            Thank you for contacting SEO Dada. We have received your message (Reference ID: {contact_submission.id}) and will get back to you as soon as possible, typically within 24 hours during business days.

            For urgent inquiries, please call our support line at +1 (800) 123-4567.

            Best Regards,
            The SEO Dada Team
            """

            mail.send(auto_reply)

            # Check if AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': 'Your message has been sent successfully! We will contact you soon.'}), 200

            flash('contact:Your message has been sent successfully! We will contact you soon.', 'success')
            return redirect(url_for('public.contact'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error processing contact form: {str(e)}")
            # Check if AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'There was an error sending your message. Please try again later.'}), 500
            flash('There was an error sending your message. Please try again later.', 'danger')

    return render_template('contact.html')


# ========================
# PRICING
# ========================

@public_bp.route('/pricing')
def pricing():
    """Display pricing page with subscription plans"""
    try:
        subscriptions = Subscription.query.filter_by(
            is_active=True,
            archived_at=None
        ).order_by(Subscription.tier.asc()).all()
    except Exception as e:
        current_app.logger.error(f"Error fetching subscriptions: {str(e)}")
        subscriptions = []
    return render_template('pricing.html', subscriptions=subscriptions)


# ========================
# SERVICE PAGES
# ========================

@public_bp.route('/services/url-analysis')
def url_analysis_page():
    """URL Analysis service page"""
    return render_template('service/url_analysis.html')


@public_bp.route('/services/heading-analysis')
def heading_analysis_page():
    """Heading Analysis service page"""
    return render_template('service/heading_analysis.html')


@public_bp.route('/services/keyword-analysis')
def keyword_analysis_page():
    """Keyword Analysis service page"""
    return render_template('service/keyword_analysis.html')


@public_bp.route('/services/image-analysis')
def image_analysis_page():
    """Image Analysis service page"""
    return render_template('service/image_analysis.html')


@public_bp.route('/services/meta-analysis')
def meta_analysis_page():
    """Meta Analysis service page"""
    return render_template('service/meta_analysis.html')


@public_bp.route('/services/sitemap-analysis')
def sitemap_analysis_page():
    """Sitemap Analysis service page"""
    return render_template('service/sitemap_analysis.html')


# ========================
# PUBLIC BLOG ROUTES
# ========================

@public_bp.route('/blogs')
def public_blogs():
    """Public blog listing page"""
    try:
        # Get filter parameters
        category_id = request.args.get('category', type=int)
        page = request.args.get('page', 1, type=int)
        per_page = 9  # Show 9 blogs per page

        # Base query - only active blogs
        query = Blog.query.filter_by(status=True)

        # Filter by category if specified
        selected_category = None
        if category_id:
            selected_category = BlogCategory.query.get(category_id)
            if selected_category:
                query = query.filter_by(category_id=category_id)

        # Order by latest first
        query = query.order_by(Blog.created_at.desc())

        # Paginate results
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        blogs = pagination.items

        # Get all active categories for filter
        categories = BlogCategory.query.filter_by(status=True).order_by(BlogCategory.sort_order, BlogCategory.name).all()

        return render_template('blogs.html',
                             blogs=blogs,
                             categories=categories,
                             pagination=pagination,
                             selected_category=selected_category)
    except Exception as e:
        current_app.logger.error(f"Error loading blogs: {str(e)}")
        flash('Error loading blogs', 'danger')
        return redirect(url_for('public.landing'))


@public_bp.route('/blog/<slug>')
def blog_detail(slug):
    """Individual blog detail page"""
    try:
        # Get blog by slug
        blog = Blog.query.filter_by(slug=slug, status=True).first_or_404()

        # Debug: Log schema_data
        current_app.logger.info(f"Blog '{blog.title}' - ORM schema_data: {blog.schema_data}")

        # If schema_data is None, try to fetch it directly from database
        # This bypasses SQLAlchemy ORM reflection issues
        if blog.schema_data is None:
            result = db.session.execute(
                text("SELECT schema_data FROM blogs WHERE id = :id"),
                {"id": blog.id}
            ).fetchone()
            print(f"[DEBUG] Raw SQL result for blog {blog.id}: {result}")
            if result and result[0]:
                blog.schema_data = result[0]
                print(f"[DEBUG] schema_data loaded successfully: {blog.schema_data[:100]}...")
            else:
                print(f"[DEBUG] No schema_data found in database for blog {blog.id}")
        else:
            print(f"[DEBUG] ORM already has schema_data: {blog.schema_data[:100] if blog.schema_data else 'None'}...")

        # Get related blogs from same category (excluding current blog)
        related_blogs = []
        if blog.category_id:
            related_blogs = (Blog.query
                           .filter_by(category_id=blog.category_id, status=True)
                           .filter(Blog.id != blog.id)
                           .order_by(Blog.created_at.desc())
                           .limit(3)
                           .all())

        # If no related blogs from category, get latest blogs
        if not related_blogs:
            related_blogs = (Blog.query
                           .filter_by(status=True)
                           .filter(Blog.id != blog.id)
                           .order_by(Blog.created_at.desc())
                           .limit(3)
                           .all())

        return render_template('blog_detail.html',
                             blog=blog,
                             related_blogs=related_blogs)
    except Exception as e:
        current_app.logger.error(f"Error loading blog detail: {str(e)}")
        flash('Blog not found', 'danger')
        return redirect(url_for('public.public_blogs'))


# ========================
# PUBLIC WEBSTORY ROUTES
# ========================

@public_bp.route('/webstories')
def public_webstories():
    """Public web story listing page"""
    try:
        # Get filter parameters
        page = request.args.get('page', 1, type=int)
        per_page = 12  # Show 12 web stories per page

        # Base query - only active web stories
        query = WebStory.query.filter_by(status=True)

        # Order by latest first
        query = query.order_by(WebStory.created_at.desc())

        # Paginate results
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        webstories = pagination.items

        return render_template('webstories.html',
                             webstories=webstories,
                             pagination=pagination)
    except Exception as e:
        current_app.logger.error(f"Error loading web stories: {str(e)}")
        flash('Error loading web stories', 'danger')
        return redirect(url_for('public.landing'))


@public_bp.route('/webstory/<slug>')
def webstory_detail(slug):
    """Individual web story detail page"""
    try:
        # Get web story by slug
        webstory = WebStory.query.filter_by(slug=slug, status=True).first_or_404()

        # Get related web stories (excluding current one)
        related_webstories = (WebStory.query
                           .filter_by(status=True)
                           .filter(WebStory.id != webstory.id)
                           .order_by(WebStory.created_at.desc())
                           .limit(6)
                           .all())

        return render_template('webstory_detail.html',
                             webstory=webstory,
                             related_webstories=related_webstories)
    except Exception as e:
        current_app.logger.error(f"Error loading web story detail: {str(e)}")
        flash('Web story not found', 'danger')
        return redirect(url_for('public.public_webstories'))


# ========================
# SITEMAP ROUTES
# ========================

@public_bp.route('/sitemap')
def sitemap_page():
    """Display sitemap categories page"""
    blogs_count = 0
    webstories_count = 0
    website_settings = None
    pages_count = 19  # Main pages + services + legal pages

    try:
        blogs_count = Blog.query.filter_by(status=True).count()
    except Exception as e:
        print(f"Error fetching blogs count: {e}")

    try:
        webstories_count = WebStory.query.filter_by(status=True).count()
    except Exception as e:
        print(f"Error fetching webstories count: {e}")

    try:
        website_settings = WebsiteSettings.query.first()
    except Exception as e:
        print(f"Error fetching website settings: {e}")

    return render_template(
        'sitemap_index.html',
        blogs_count=blogs_count,
        webstories_count=webstories_count,
        pages_count=pages_count,
        website_settings=website_settings
    )


@public_bp.route('/page-sitemap')
def sitemap_pages():
    """Display all website pages"""
    website_settings = None
    base_url = request.url_root.rstrip('/')
    current_date = datetime.now().strftime('%b %d, %Y')

    try:
        website_settings = WebsiteSettings.query.first()
    except Exception as e:
        print(f"Error fetching website settings: {e}")

    return render_template(
        'sitemap_pages.html',
        website_settings=website_settings,
        base_url=base_url,
        current_date=current_date
    )


@public_bp.route('/post-sitemap')
def sitemap_blogs():
    """Display all blog articles"""
    blogs = []
    website_settings = None
    base_url = request.url_root.rstrip('/')
    current_date = datetime.now().strftime('%b %d, %Y')

    try:
        blogs = Blog.query.filter_by(status=True).order_by(Blog.updated_at.desc()).all()
        # Calculate image count for each blog
        for blog in blogs:
            image_count = 0
            # Count cover image
            if blog.image:
                image_count += 1
            # Count images in description HTML
            if blog.description:
                img_tags = re.findall(r'<img[^>]+>', blog.description, re.IGNORECASE)
                image_count += len(img_tags)
            blog.image_count = image_count
    except Exception as e:
        print(f"Error fetching blogs: {e}")

    try:
        website_settings = WebsiteSettings.query.first()
    except Exception as e:
        print(f"Error fetching website settings: {e}")

    return render_template(
        'sitemap_blogs.html',
        blogs=blogs,
        website_settings=website_settings,
        base_url=base_url,
        current_date=current_date
    )


@public_bp.route('/web-story-sitemap')
def sitemap_webstories():
    """Display all web stories"""
    webstories = []
    website_settings = None
    base_url = request.url_root.rstrip('/')
    current_date = datetime.now().strftime('%b %d, %Y')

    try:
        webstories = WebStory.query.filter_by(status=True).order_by(WebStory.updated_at.desc()).all()
        # Calculate image count for each webstory
        for story in webstories:
            image_count = 0
            # Count cover image
            if story.cover_image:
                image_count += 1
            # Count images in slides
            if story.slides:
                for slide in story.slides:
                    if slide.get('image'):
                        image_count += 1
            story.image_count = image_count
    except Exception as e:
        print(f"Error fetching webstories: {e}")

    try:
        website_settings = WebsiteSettings.query.first()
    except Exception as e:
        print(f"Error fetching website settings: {e}")

    return render_template(
        'sitemap_webstories.html',
        webstories=webstories,
        website_settings=website_settings,
        base_url=base_url,
        current_date=current_date
    )


@public_bp.route('/sitemap.xml')
@public_bp.route('/sitemap_index.xml')
def sitemap_xml():
    """Generate sitemap XML for search engines"""
    # Get the base URL from the request
    base_url = request.url_root.rstrip('/')

    # Fetch dynamic content
    blogs = []
    webstories = []

    try:
        blogs = Blog.query.filter_by(status=True).order_by(Blog.updated_at.desc()).all()
    except Exception as e:
        print(f"Error fetching blogs for sitemap: {e}")

    try:
        webstories = WebStory.query.filter_by(status=True).order_by(WebStory.updated_at.desc()).all()
    except Exception as e:
        print(f"Error fetching webstories for sitemap: {e}")

    # Render the sitemap template
    xml_content = render_template(
        'sitemap.xml',
        base_url=base_url,
        blogs=blogs,
        webstories=webstories
    )

    # Create response with proper content type
    response = make_response(xml_content)
    response.headers['Content-Type'] = 'application/xml'
    response.headers['Cache-Control'] = 'public, max-age=3600'  # Cache for 1 hour

    return response


# ========================
# ROBOTS.TXT
# ========================

@public_bp.route('/robots.txt')
def robots():
    """Generate robots.txt dynamically using template"""
    base_url = request.url_root.rstrip('/')

    # Render the robots template
    robots_content = render_template('robots.txt', base_url=base_url)

    response = make_response(robots_content)
    response.headers['Content-Type'] = 'text/plain'

    return response


# ========================
# CRON JOB ROUTES
# ========================

@public_bp.route('/cron/check-expiring-subscriptions')
def cron_check_expiring_subscriptions():
    """
    Cron job endpoint to check for expiring subscriptions
    This can be called by external cron jobs if needed
    """
    try:
        # Optional: Add authentication for cron job
        cron_secret = request.headers.get('X-Cron-Secret')
        expected_secret = current_app.config.get('CRON_SECRET', 'your-secret-key')

        if cron_secret != expected_secret:
            return jsonify({'error': 'Unauthorized'}), 401

        from services.email import check_and_notify_expiring_subscriptions
        notifications_sent = check_and_notify_expiring_subscriptions()

        result = {
            'success': True,
            'notifications_sent': notifications_sent,
            'timestamp': datetime.now(UTC).isoformat()
        }

        current_app.logger.info(f"Expiry check cron job completed: {result}")
        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Expiry check cron job failed: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now(UTC).isoformat()
        }), 500


@public_bp.route('/cron/handle-expired-subscriptions')
def cron_handle_expired_subscriptions():
    """
    Cron job endpoint to handle expired subscriptions and pause tokens
    This should be called daily by your server's cron job
    """
    try:
        # Optional: Add authentication for cron job
        cron_secret = request.headers.get('X-Cron-Secret')
        expected_secret = current_app.config.get('CRON_SECRET', 'your-secret-key')

        if cron_secret != expected_secret:
            return jsonify({'error': 'Unauthorized'}), 401

        from services.subscription import handle_expired_subscriptions, process_auto_renewals

        # Process expired subscriptions
        subscriptions_processed, tokens_paused = handle_expired_subscriptions()

        # Also run auto-renewal process
        process_auto_renewals()

        result = {
            'success': True,
            'subscriptions_processed': subscriptions_processed,
            'tokens_paused': tokens_paused,
            'timestamp': datetime.now(UTC).isoformat()
        }

        current_app.logger.info(f"Cron job completed: {result}")
        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Cron job failed: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now(UTC).isoformat()
        }), 500
