import os
import re
import csv
import json
import logging
import traceback
import time
import uuid
import secrets
import string
import datetime as dt_module
from io import StringIO, BytesIO
from datetime import datetime, timedelta, timezone
from functools import wraps

import pytz
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session, jsonify, send_file, make_response, current_app)
from flask_mail import Message
from flask_login import logout_user
from sqlalchemy import func, or_, case, literal, cast, String
from werkzeug.utils import secure_filename

from extensions import db, mail, cache, razorpay_client, csrf

from models import (User, Subscription, SubscribedUser, SubscriptionHistory,
                    Payment, InvoiceAddress, Admin, SearchHistory, EmailLog,
                    ContactSubmission, WebsiteSettings, BlogCategory, Blog,
                    WebStory, TokenPurchase, UserToken, UsageLog)

UTC = timezone.utc

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# ----------------------
# Upload configuration
# ----------------------
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico'}

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ----------------------
# Admin required decorator
# ----------------------
def admin_required(f):
    """
    Decorator to check if user is logged in as admin.
    If not, redirects to admin login page.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if admin is logged in
        if 'admin_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('admin.admin_login'))

        return f(*args, **kwargs)
    return decorated_function


# ----------------------
# CSRF exempt decorator
# ----------------------
def csrf_exempt(f):
    """Decorator to exempt a route from CSRF protection"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    decorated_function._csrf_exempt = True
    return decorated_function


# ----------------------
# Helper functions
# ----------------------
def updated_check_permission(email_id, required_permission):
    """Updated static method to check permissions by email without using SQL contains()"""
    admin = Admin.query.filter_by(email_id=email_id).first()
    if not admin:
        return False

    # For POST requests, check against form data
    if request.method == 'POST':
        form_email = request.form.get('email_id')
        if form_email == email_id:
            permissions = request.form.getlist('permissions[]')
            return required_permission in permissions

    # Otherwise check stored permissions using Python logic
    if admin.permission and isinstance(admin.permission, list):
        return required_permission in admin.permission

    return False


# Replace the existing check_permission method in your Admin class
Admin.check_permission = staticmethod(updated_check_permission)


def get_user_status_display(user):
    """Returns user account status (separate from subscription status)"""
    if user.email_confirmed:
        return ("Active", "bg-success", "fas fa-check-circle")
    else:
        return ("Unconfirmed", "bg-warning", "fas fa-exclamation-triangle")


def validate_user_data(name, email, password, user_id=None):
    """Validate user data and return list of errors"""
    errors = []

    # Name validation
    if not name:
        errors.append("Name is required.")
    elif len(name) < 2:
        errors.append("Name must be at least 2 characters long.")
    elif len(name) > 100:
        errors.append("Name cannot exceed 100 characters.")

    # Email validation
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not email:
        errors.append("Email is required.")
    elif not re.match(email_pattern, email):
        errors.append("Please enter a valid email address.")
    elif len(email) > 255:
        errors.append("Email address is too long.")
    else:
        # Check if email already exists (exclude current user if editing)
        query = User.query.filter(func.lower(User.company_email) == email.lower())
        if user_id:
            query = query.filter(User.id != user_id)
        existing_user = query.first()
        if existing_user:
            errors.append("A user with this email already exists.")

    # Password validation (only if password is provided)
    if password:
        if len(password) < 8:
            errors.append("Password must be at least 8 characters long.")
        elif len(password) > 128:
            errors.append("Password cannot exceed 128 characters.")
        else:
            # Check password complexity
            password_errors = []
            if not re.search(r'[A-Z]', password):
                password_errors.append("one uppercase letter")
            if not re.search(r'[a-z]', password):
                password_errors.append("one lowercase letter")
            if not re.search(r'[0-9]', password):
                password_errors.append("one number")
            if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
                password_errors.append("one special character")

            if password_errors:
                errors.append(f"Password must contain at least {', '.join(password_errors)}.")

    return errors


def generate_unique_invoice_number():
    """Generate a unique invoice number"""
    timestamp = datetime.now(UTC).strftime("%y%m%d")
    unique_id = str(uuid.uuid4().hex)[:8]
    return f"INV-{timestamp}-{unique_id}"


def create_or_update_subscription(payment):
    """Create or update subscription based on payment"""
    # Check if subscription already exists
    existing_sub = SubscribedUser.query.filter_by(
        U_ID=payment.user_id,
        S_ID=payment.subscription_id
    ).first()

    if not existing_sub:
        subscription = Subscription.query.get(payment.subscription_id)
        start_date = datetime.now(UTC)
        end_date = start_date + timedelta(days=subscription.days)

        new_subscription = SubscribedUser(
            U_ID=payment.user_id,
            S_ID=payment.subscription_id,
            start_date=start_date,
            end_date=end_date,
            current_usage=0,
            is_auto_renew=True
        )

        # Record subscription history
        history_entry = SubscriptionHistory(
            U_ID=payment.user_id,
            S_ID=payment.subscription_id,
            action=payment.payment_type,
            previous_S_ID=payment.previous_subscription_id
        )

        db.session.add(new_subscription)
        db.session.add(history_entry)


def create_invoice_address_for_payment(payment):
    """Create invoice address for payment if not exists"""
    existing_address = InvoiceAddress.query.filter_by(payment_id=payment.iid).first()

    if not existing_address:
        # Try to get user details
        user = User.query.get(payment.user_id)

        new_address = InvoiceAddress(
            payment_id=payment.iid,
            full_name=user.name,
            email=user.company_email,
            company_name=user.company_name if hasattr(user, 'company_name') else None,
            street_address=user.address if hasattr(user, 'address') else 'N/A',
            city=user.city if hasattr(user, 'city') else 'N/A',
            state=user.state if hasattr(user, 'state') else 'N/A',
            postal_code=user.postal_code if hasattr(user, 'postal_code') else 'N/A',
            gst_number=user.gst_number if hasattr(user, 'gst_number') else None
        )

        db.session.add(new_address)


# ===========================
# Test Routes
# ===========================

@admin_bp.route('/test-expiry-notifications')
@admin_required
def test_expiry_notifications():
    """Test route for admins to manually trigger expiry notifications check"""
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'subscription_management'):
        flash("You don't have permission to test expiry notifications.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    try:
        from app import check_and_notify_expiring_subscriptions
        notifications_sent = check_and_notify_expiring_subscriptions()

        if notifications_sent > 0:
            flash(f'Successfully sent {notifications_sent} expiry notification emails.', 'success')
        else:
            flash('No subscriptions found expiring within 24 hours.', 'info')

    except Exception as e:
        current_app.logger.error(f"Error testing expiry notifications: {str(e)}")
        flash('Error sending expiry notifications. Check logs for details.', 'danger')

    return redirect(url_for('admin.admin_subscriptions'))


@admin_bp.route('/test-email-config')
@admin_required
def test_email_config():
    """Test route to verify email configuration and send a test email"""
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'subscription_management'):
        flash("You don't have permission to test email configuration.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    try:
        # Get admin user to send test email
        admin = Admin.query.filter_by(email_id=email_id).first()

        # Create a test message
        subject = "SEO Dada - Test Email Configuration"
        message = Message(
            subject,
            sender=current_app.config['MAIL_USERNAME'],
            recipients=[email_id]  # Send to admin's email
        )

        message.body = f"""Hello {admin.NAME},

This is a test email to verify that the email configuration is working correctly.

Email Configuration:
- MAIL_SERVER: {current_app.config.get('MAIL_SERVER')}
- MAIL_PORT: {current_app.config.get('MAIL_PORT')}
- MAIL_USE_TLS: {current_app.config.get('MAIL_USE_TLS')}
- MAIL_USE_SSL: {current_app.config.get('MAIL_USE_SSL')}
- MAIL_USERNAME: {current_app.config.get('MAIL_USERNAME')}
- Sender: {current_app.config.get('MAIL_USERNAME')}
- Recipient: {email_id}

If you received this email, the email configuration is working correctly!

Best regards,
SEO Dada System
"""

        message.html = f'''
        <!DOCTYPE html>
        <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #4f46e5;">Email Configuration Test</h2>
                <p>Hello <strong>{admin.NAME}</strong>,</p>
                <p>This is a test email to verify that the email configuration is working correctly.</p>

                <h3>Email Configuration:</h3>
                <ul>
                    <li><strong>MAIL_SERVER:</strong> {current_app.config.get('MAIL_SERVER')}</li>
                    <li><strong>MAIL_PORT:</strong> {current_app.config.get('MAIL_PORT')}</li>
                    <li><strong>MAIL_USE_TLS:</strong> {current_app.config.get('MAIL_USE_TLS')}</li>
                    <li><strong>MAIL_USE_SSL:</strong> {current_app.config.get('MAIL_USE_SSL')}</li>
                    <li><strong>MAIL_USERNAME:</strong> {current_app.config.get('MAIL_USERNAME')}</li>
                    <li><strong>Sender:</strong> {current_app.config.get('MAIL_USERNAME')}</li>
                    <li><strong>Recipient:</strong> {email_id}</li>
                </ul>

                <p style="color: #10b981; font-weight: bold;">If you received this email, the email configuration is working correctly!</p>

                <p>Best regards,<br>SEO Dada System</p>
            </body>
        </html>
        '''

        current_app.logger.info(f"Sending test email to {email_id}")
        mail.send(message)
        current_app.logger.info(f"Test email sent successfully to {email_id}")

        flash(f'Test email sent successfully to {email_id}. Please check your inbox.', 'success')

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        current_app.logger.error(f"Failed to send test email: {error_msg}")
        current_app.logger.error(f"Traceback: {traceback.format_exc()}")
        flash(f'Failed to send test email: {error_msg}', 'danger')

    return redirect(url_for('admin.admin_dashboard'))


# ===========================
# Admin Dashboard
# ===========================

@admin_bp.route('/')
@admin_required
def admin_dashboard():
    now = datetime.now(UTC)
    # Get current page number from query params (default: 1)
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Number of payments per page

    class RecentPayment:
        def __init__(self, user, subscription, payment):
            self.user = user
            self.subscription = subscription
            self.payment = payment

        def format_amount(self):
            try:
                return "{:,.2f}".format(self.payment.total_amount if hasattr(self.payment, 'total_amount') else self.payment.amount)
            except (AttributeError, TypeError):
                return "0.00"

    # Basic Stats - FIXED
    total_users = User.query.count()
    active_users = User.query.filter_by(email_confirmed=True).count()
    unconfirmed_users = total_users - active_users

    # Active subscriptions - only count those that are active AND not expired
    active_subscriptions = SubscribedUser.query.filter(
        SubscribedUser.end_date > now,
        SubscribedUser._is_active == True
    ).count()

    # Expired subscriptions - those that have passed end_date
    expired_subscriptions = SubscribedUser.query.filter(
        SubscribedUser.end_date <= now
    ).count()

    # Revenue - ONLY FROM COMPLETED PAYMENTS
    thirty_days_ago = now - timedelta(days=30)
    total_revenue = db.session.query(func.sum(Payment.total_amount)).filter(
        Payment.status == 'completed'
    ).scalar() or 0

    monthly_revenue = db.session.query(func.sum(Payment.total_amount)).filter(
        Payment.status == 'completed',
        Payment.created_at >= thirty_days_ago
    ).scalar() or 0

    # Recent Payments - ONLY COMPLETED ONES
    recent_payments_query = (
        db.session.query(Payment, User, Subscription, InvoiceAddress)
        .join(User, Payment.user_id == User.id)
        .join(Subscription, Payment.subscription_id == Subscription.S_ID)
        .outerjoin(InvoiceAddress, Payment.iid == InvoiceAddress.payment_id)
        .filter(Payment.status == 'completed')
        .order_by(Payment.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    recent_payments = [
        RecentPayment(user=user, subscription=subscription, payment=payment)
        for payment, user, subscription, invoice_address in recent_payments_query.items
    ]

    # Popular Plans - Convert to list of dicts
    popular_plans_query = (
        db.session.query(
            Subscription.plan,
            func.count(SubscribedUser.id).label('subscribers')
        )
        .join(SubscribedUser, Subscription.S_ID == SubscribedUser.S_ID)
        .filter(
            SubscribedUser.end_date > now,
            SubscribedUser._is_active == True
        )
        .group_by(Subscription.plan)
        .order_by(func.count(SubscribedUser.id).desc())
        .limit(3)
        .all()
    )
    popular_plans = [{"plan": row.plan, "subscribers": row.subscribers} for row in popular_plans_query]

    # Expiring Soon - ONLY ACTIVE SUBSCRIPTIONS
    seven_days_from_now = now + timedelta(days=7)
    expiring_soon = (
        db.session.query(User, Subscription, SubscribedUser)
        .join(SubscribedUser, User.id == SubscribedUser.U_ID)
        .join(Subscription, SubscribedUser.S_ID == Subscription.S_ID)
        .filter(
            SubscribedUser.end_date > now,
            SubscribedUser.end_date <= seven_days_from_now,
            SubscribedUser._is_active == True
        )
        .all()
    )
    for user, subscription, subscribed_user in expiring_soon:
        if subscribed_user.end_date.tzinfo is None:
            subscribed_user.end_date = subscribed_user.end_date.replace(tzinfo=UTC)

    # Subscription Actions (30 days)
    subscription_actions_query = (
        db.session.query(
            SubscriptionHistory.action,
            func.count(SubscriptionHistory.id).label('count')
        )
        .filter(SubscriptionHistory.created_at >= thirty_days_ago)
        .group_by(SubscriptionHistory.action)
        .all()
    )
    subscription_actions = [{"action": row.action, "count": row.count} for row in subscription_actions_query]

    # Auto-renewal stats - ONLY ACTIVE SUBSCRIPTIONS
    auto_renewal_count = SubscribedUser.query.filter(
        SubscribedUser.is_auto_renew == True,
        SubscribedUser.end_date > now,
        SubscribedUser._is_active == True
    ).count()

    non_renewal_count = SubscribedUser.query.filter(
        SubscribedUser.is_auto_renew == False,
        SubscribedUser.end_date > now,
        SubscribedUser._is_active == True
    ).count()

    # Payment Types - ONLY COMPLETED PAYMENTS
    payment_types_query = (
        db.session.query(
            Payment.payment_type,
            Payment.currency,
            func.count(Payment.iid).label('count'),
            func.sum(Payment.total_amount).label('total_revenue')
        )
        .filter(Payment.status == 'completed')
        .group_by(Payment.payment_type, Payment.currency)
        .all()
    )
    payment_types = [
        {
            "payment_type": row.payment_type,
            "currency": row.currency,
            "count": row.count,
            "total_revenue": row.total_revenue
        }
        for row in payment_types_query
    ]

    # Tax Breakdown - ONLY COMPLETED PAYMENTS
    tax_breakdown_query = (
        db.session.query(
            Payment.gst_rate,
            func.sum(Payment.gst_amount).label('total_tax'),
            func.count(Payment.iid).label('payment_count')
        )
        .filter(Payment.status == 'completed')
        .group_by(Payment.gst_rate)
        .all()
    )
    tax_breakdown = [
        {
            "gst_rate": row.gst_rate,
            "total_tax": row.total_tax,
            "payment_count": row.payment_count
        }
        for row in tax_breakdown_query
    ]

    # Token Purchase Stats with correct field names
    token_stats_query = db.session.query(
        func.sum(TokenPurchase.token_count).label('total_tokens'),
        func.sum(TokenPurchase.total_amount).label('total_amount')
    ).filter(
        TokenPurchase.status == 'completed'
    ).first()

    token_chart_data = {
        "tokens_purchased": token_stats_query.total_tokens or 0,
        "total_amount": token_stats_query.total_amount or 0
    }

    return render_template('admin/dashboard.html',
        now=now,
        total_users=total_users,
        active_users=active_users,
        unconfirmed_users=unconfirmed_users,
        active_subscriptions=active_subscriptions,
        expired_subscriptions=expired_subscriptions,
        recent_payments=recent_payments,
        total_revenue=total_revenue,
        monthly_revenue=monthly_revenue,
        popular_plans=popular_plans,
        token_chart_data=token_chart_data,
        expiring_soon=expiring_soon,
        subscription_actions=subscription_actions,
        auto_renewal_count=auto_renewal_count,
        non_renewal_count=non_renewal_count,
        payment_types=payment_types,
        recent_payments_pagination=recent_payments_query,
        tax_breakdown=tax_breakdown
    )


# ===========================
# Admin Login and Logout
# ===========================

@admin_bp.route('/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        # Input validation
        if not email or not password:
            flash('Email and password are required.', 'danger')
            return render_template('admin/login.html')

        # NORMALIZE EMAIL TO LOWERCASE FOR CONSISTENT LOOKUP
        email = email.lower().strip()

        # USE CASE-INSENSITIVE QUERY
        admin = Admin.query.filter(
            func.lower(Admin.email_id) == email
        ).first()

        # Check if admin exists and has password set
        if not admin:
            flash('Invalid email or password.', 'danger')
            return render_template('admin/login.html')

        # Check if password hash exists
        if not admin.password_hash:
            flash('Password not set for this admin account.', 'danger')
            return render_template('admin/login.html')

        # Verify password
        try:
            if admin.check_password(password):
                session['admin_id'] = admin.id
                session['admin_name'] = admin.NAME
                session['email_id'] = admin.email_id
                session['admin_role'] = admin.role

                # Store permissions as list - parse JSON if it's a string
                if isinstance(admin.permission, str):
                    try:
                        session['admin_permissions'] = json.loads(admin.permission)
                    except:
                        session['admin_permissions'] = []
                elif isinstance(admin.permission, list):
                    session['admin_permissions'] = admin.permission
                else:
                    session['admin_permissions'] = []

                flash('Login successful!', 'success')
                return redirect(url_for('admin.admin_dashboard'))
            else:
                flash('Invalid email or password.', 'danger')
                return render_template('admin/login.html')
        except Exception as e:
            current_app.logger.error(f"Password verification error: {str(e)}")
            flash('Error verifying password. Please contact administrator.', 'danger')
            return render_template('admin/login.html')

    return render_template('admin/login.html', email_id='')


@admin_bp.route('/logout')
@admin_required
def admin_logout():
    logout_user()  # Flask-Login function
    session.clear()
    # Clear only admin session data (not user session if any)
    session.pop('admin_id', None)

    flash('You have been logged out.', 'info')
    return redirect(url_for('admin.admin_login'))


# ===========================
# Role Management
# ===========================

@admin_bp.route('/roles', methods=['GET', 'POST'])
@admin_required
def manage_roles():
    # Check if the user has permission to manage roles
    email_id = session.get('email_id')
    if not Admin.check_permission(email_id, 'manage_roles'):
        flash("You don't have permission to manage roles.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    if request.method == 'POST':
        try:
            # Get form data and normalize email
            name = request.form.get('NAME')
            email_id = request.form.get('email_id')
            role = request.form.get('role')
            phone_number = request.form.get('phone_number')
            password = request.form.get('password')
            permissions = request.form.getlist('permissions[]')

            # NORMALIZE EMAIL TO LOWERCASE
            if email_id:
                email_id = email_id.lower().strip()

            # Validate required fields
            if not all([name, email_id, role]):
                flash('Name, email and role are required fields.', 'danger')
                return redirect(url_for('admin.manage_roles'))

            # USE CASE-INSENSITIVE QUERY
            admin_role = Admin.query.filter(
                func.lower(Admin.email_id) == email_id
            ).first()

            if admin_role:
                # Update existing admin
                admin_role.NAME = name
                admin_role.email_id = email_id
                admin_role.role = role
                admin_role.phone_number = phone_number
                admin_role.permission = permissions
                admin_role.updated_at = datetime.now(UTC)

                # Only update password if provided
                if password and password.strip():
                    if not admin_role.set_password(password):
                        flash('Error setting password.', 'danger')
                        return redirect(url_for('admin.manage_roles'))

                flash(f'Role updated successfully for {name}!', 'success')
            else:
                # Create new admin
                if not password:
                    flash('Password is required for new admin roles.', 'danger')
                    return redirect(url_for('admin.manage_roles'))

                new_role = Admin(
                    NAME=name,
                    email_id=email_id,
                    role=role,
                    phone_number=phone_number,
                    permission=permissions,
                    assigned_by=session.get('admin_name', 'System'),
                    is_active=True,
                    created_at=datetime.now(UTC)
                )

                # Set password for new admin
                if not new_role.set_password(password):
                    flash('Error setting password.', 'danger')
                    return redirect(url_for('admin.manage_roles'))

                db.session.add(new_role)
                flash(f'New role created successfully for {name}!', 'success')

            db.session.commit()
            return redirect(url_for('admin.manage_roles'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Role management error: {str(e)}")
            flash(f'Error: {str(e)}', 'danger')
            return redirect(url_for('admin.manage_roles'))

    roles = Admin.query.all()
    return render_template('admin/roles.html', roles=roles)


@admin_bp.route('/roles/edit/<int:role_id>', methods=['GET', 'POST'])
@admin_required
def edit_role(role_id):
    role = Admin.query.get_or_404(role_id)

    if request.method == 'POST':
        try:
            # Get form data and normalize email
            role.NAME = request.form.get('NAME')
            email_id = request.form.get('email_id')
            role.role = request.form.get('role')
            role.phone_number = request.form.get('phone_number')
            permissions = request.form.getlist('permissions[]')
            password = request.form.get('password')

            # NORMALIZE EMAIL TO LOWERCASE
            if email_id:
                email_id = email_id.lower().strip()
                role.email_id = email_id

            # Validate required fields
            if not all([role.NAME, role.email_id, role.role]):
                flash('Name, email and role are required fields.', 'danger')
                return redirect(url_for('admin.edit_role', role_id=role_id))

            # CHECK FOR DUPLICATE EMAIL (CASE-INSENSITIVE, EXCLUDING CURRENT ROLE)
            existing_admin = Admin.query.filter(
                func.lower(Admin.email_id) == email_id,
                Admin.id != role_id
            ).first()

            if existing_admin:
                flash('An admin with this email address already exists.', 'danger')
                return redirect(url_for('admin.edit_role', role_id=role_id))

            # Update password if provided
            if password and password.strip():
                if not role.set_password(password):
                    flash('Error updating password.', 'danger')
                    return redirect(url_for('admin.edit_role', role_id=role_id))

            # Update other fields
            role.permission = permissions
            role.updated_at = datetime.now(UTC)

            db.session.commit()
            flash(f'Role updated successfully for {role.NAME}!', 'success')
            return redirect(url_for('admin.manage_roles'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Role update error: {str(e)}")
            flash(f'Error updating role: {str(e)}', 'danger')
            return redirect(url_for('admin.edit_role', role_id=role_id))

    return render_template('admin/edit_role.html',
                         role=role,
                         role_permissions=role.permission if role.permission else [])


@admin_bp.route('/roles/delete/<int:role_id>', methods=['POST'])
@admin_required
def delete_role(role_id):
    """Delete an admin role with proper validation"""
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'manage_roles'):
        flash("You don't have permission to delete roles.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    role = Admin.query.get_or_404(role_id)

    # Prevent self-deletion
    current_admin_id = session.get('admin_id')
    if role.id == current_admin_id:
        flash('You cannot delete your own role.', 'danger')
        return redirect(url_for('admin.manage_roles'))

    # FIXED: Check if this is the last super admin using Python logic instead of SQL contains()
    role_has_manage_roles = False
    if role.permission and isinstance(role.permission, list):
        role_has_manage_roles = 'manage_roles' in role.permission

    if role_has_manage_roles:
        # Count other admins with manage_roles permission using Python filtering
        all_other_admins = Admin.query.filter(
            Admin.is_active == True,
            Admin.id != role_id
        ).all()

        super_admins_count = 0
        for admin in all_other_admins:
            if admin.permission and isinstance(admin.permission, list):
                if 'manage_roles' in admin.permission:
                    super_admins_count += 1

        if super_admins_count == 0:
            flash('Cannot delete the last admin with role management permissions.', 'warning')
            return redirect(url_for('admin.manage_roles'))

    try:
        # Store role details for success message
        role_name = role.NAME
        role_email = role.email_id

        # Delete the role
        db.session.delete(role)
        db.session.commit()

        flash(f'Role for {role_name} ({role_email}) has been deleted successfully.', 'success')
        current_app.logger.info(f"Admin role deleted: {role_email} by {session.get('email_id')}")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting role {role_id}: {str(e)}")
        flash(f'Error deleting role: {str(e)}', 'danger')

    return redirect(url_for('admin.manage_roles'))


# ===========================
# Search History
# ===========================

@admin_bp.route('/search_history', methods=['GET'])
@admin_required
def admin_search_history():
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'search_history'):
        flash("You don't have permission to access this page.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    # Get all filter parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    tool_filter = request.args.get('tool_filter', 'all')
    user_filter = request.args.get('user_filter', 'all')
    query_filter = request.args.get('query_filter')
    sort_by = request.args.get('sort_by', 'date_desc')
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Number of items per page

    # Base query to fetch all search histories
    query = SearchHistory.query

    # Apply date filters if provided
    if start_date:
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(SearchHistory.created_at >= start_date_obj)
        except ValueError:
            flash("Invalid start date format. Please use YYYY-MM-DD.", "danger")

    if end_date:
        try:
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
            # Add one day to include the entire end date
            end_date_obj += timedelta(days=1)
            query = query.filter(SearchHistory.created_at < end_date_obj)
        except ValueError:
            flash("Invalid end date format. Please use YYYY-MM-DD.", "danger")

    # Apply tool filter if provided
    if tool_filter != 'all':
        query = query.filter(SearchHistory.usage_tool == tool_filter)

    # Apply user filter if provided
    if user_filter != 'all':
        query = query.filter(SearchHistory.u_id == user_filter)

    # Apply query filter if provided
    if query_filter:
        search_term = f"%{query_filter}%"
        query = query.filter(SearchHistory.search_history.like(search_term))

    # Apply sorting
    if sort_by == 'date_desc':
        query = query.order_by(SearchHistory.created_at.desc())
    elif sort_by == 'date_asc':
        query = query.order_by(SearchHistory.created_at.asc())
    elif sort_by == 'count_desc':
        query = query.order_by(SearchHistory.search_count.desc())
    elif sort_by == 'count_asc':
        query = query.order_by(SearchHistory.search_count.asc())

    # Calculate metrics for summary cards
    total_searches = 0
    all_logs = UsageLog.query.all()
    for log in all_logs:
        try:
            if log.details:
                total_match = re.search(r'Total:\s*(\d+)', log.details, re.IGNORECASE)
                if total_match:
                    total_searches += int(total_match.group(1))
                else:
                    match = re.search(r'Tokens used:\s*(\d+)', log.details, re.IGNORECASE)
                    if match:
                        total_searches += int(match.group(1))
                    else:
                        total_searches += 1
            else:
                total_searches += 1
        except Exception as e:
            current_app.logger.error(f"Error parsing token usage from log {log.id}: {str(e)}")
            total_searches += 1

    active_users = db.session.query(db.func.count(db.distinct(SearchHistory.u_id))).scalar() or 0

    # Most popular tool
    popular_tool_query = db.session.query(
        SearchHistory.usage_tool,
        db.func.sum(SearchHistory.search_count).label('total')
    ).group_by(SearchHistory.usage_tool).order_by(db.desc('total')).first()

    most_popular_tool = popular_tool_query[0] if popular_tool_query else "N/A"

    # Today's searches
    today = datetime.today().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    searches_today = 0
    today_logs = UsageLog.query.filter(UsageLog.timestamp.between(today_start, today_end)).all()
    for log in today_logs:
        try:
            if log.details:
                total_match = re.search(r'Total:\s*(\d+)', log.details, re.IGNORECASE)
                if total_match:
                    searches_today += int(total_match.group(1))
                else:
                    match = re.search(r'Tokens used:\s*(\d+)', log.details, re.IGNORECASE)
                    if match:
                        searches_today += int(match.group(1))
                    else:
                        searches_today += 1
            else:
                searches_today += 1
        except Exception as e:
            current_app.logger.error(f"Error parsing today's token usage from log {log.id}: {str(e)}")
            searches_today += 1

    # Get available tools for dropdown
    available_tools = db.session.query(db.distinct(SearchHistory.usage_tool)).all()
    available_tools = [tool[0] for tool in available_tools]

    # Get available users for dropdown
    available_users = User.query.join(SearchHistory).distinct().all()

    # Paginate results
    paginated_history = query.paginate(page=page, per_page=per_page, error_out=False)

    # Fetch the most-used tool for each user
    user_most_used_tools = {}
    for entry in paginated_history.items:
        user_id = entry.u_id
        if user_id not in user_most_used_tools:
            tool_usage = db.session.query(SearchHistory.usage_tool, db.func.sum(SearchHistory.search_count))\
                .filter(SearchHistory.u_id == user_id)\
                .group_by(SearchHistory.usage_tool).all()
            if tool_usage:
                most_used_tool = max(tool_usage, key=lambda x: x[1])[0]
                user_most_used_tools[user_id] = most_used_tool
            else:
                user_most_used_tools[user_id] = "No tools used yet"

    return render_template(
        'admin/search_history.html',
        history=paginated_history.items,
        pagination=paginated_history,
        user_most_used_tools=user_most_used_tools,
        start_date=start_date,
        end_date=end_date,
        tool_filter=tool_filter,
        user_filter=user_filter,
        query_filter=query_filter,
        sort_by=sort_by,
        available_tools=available_tools,
        available_users=available_users,
        total_searches=total_searches,
        active_users=active_users,
        most_popular_tool=most_popular_tool,
        searches_today=searches_today
    )


@admin_bp.route('/search_history/export', methods=['GET'])
@admin_required
def admin_export_search_history():
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'search_history'):
        flash("You don't have permission to access this feature.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    # Get the same filter parameters as the main view
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    tool_filter = request.args.get('tool_filter', 'all')
    user_filter = request.args.get('user_filter', 'all')
    query_filter = request.args.get('query_filter')

    # Base query to fetch all search histories
    query = SearchHistory.query

    # Apply the same filters as the main view
    # ... (copy the filter code from admin_search_history)

    # Fetch all matching records
    all_history = query.all()

    # Create a CSV in memory
    output = StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(['User ID', 'User Name', 'Tool', 'Search Query/URL', 'Count', 'Date & Time'])

    # Write data rows
    for entry in all_history:
        writer.writerow([
            entry.u_id,
            entry.user.name,
            entry.usage_tool,
            entry.search_history,
            entry.search_count,
            entry.created_at.strftime('%Y-%m-%d %H:%M:%S')
        ])

    # Prepare the response
    output.seek(0)
    return send_file(
        BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'search_history_{datetime.now(UTC).strftime("%Y%m%d_%H%M%S")}.csv'
    )


# ===========================
# Subscription Management
# ===========================

@admin_bp.route('/subscriptions')
@admin_required
def admin_subscriptions():
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'subscription_management'):
        flash("You don't have permission to access this page.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    # Get all subscription plans with subscriber counts
    subscriptions = (
        db.session.query(
            Subscription,
            func.count(SubscribedUser.id).label('active_subscribers'),
            func.sum(case(
                (SubscribedUser.end_date > datetime.now(UTC), 1),
                else_=0
            )).label('active_count')
        )
        .outerjoin(SubscribedUser, Subscription.S_ID == SubscribedUser.S_ID)
        .group_by(Subscription.S_ID)
        .all()
    )

    subscription_data = [
        {
            "subscription": row[0],
            "active_subscribers": row[1],
            "active_count": row[2]
        }
        for row in subscriptions
    ]

    return render_template('admin/subscriptions.html', subscriptions=subscription_data)


@admin_bp.route('/subscriptions/new', methods=['GET', 'POST'])
@admin_required
def admin_new_subscription():
    if request.method == 'POST':
        plan = request.form.get('plan')
        price = float(request.form.get('price'))
        days = int(request.form.get('days'))
        usage_per_day = int(request.form.get('usage_per_day'))
        tier = int(request.form.get('tier', 1))
        features = request.form.get('features', '')

        # Validate inputs
        if not plan or price <= 0 or days <= 0 or usage_per_day <= 0 or tier <= 0:
            flash('Invalid subscription details. Please check your input.', 'danger')
            return redirect(url_for('admin.admin_new_subscription'))

        # Check if plan name already exists
        existing_plan = Subscription.query.filter_by(plan=plan).first()
        if existing_plan:
            flash('A subscription plan with this name already exists.', 'danger')
            return redirect(url_for('admin.admin_new_subscription'))

        new_subscription = Subscription(
            plan=plan,
            price=price,
            days=days,
            usage_per_day=usage_per_day,
            tier=tier,
            features=features
        )

        db.session.add(new_subscription)
        db.session.commit()

        flash('Subscription plan created successfully!', 'success')
        return redirect(url_for('admin.admin_subscriptions'))

    return render_template('admin/new_subscription.html')


@admin_bp.route('/subscriptions/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_subscription(id):
    subscription = Subscription.query.get_or_404(id)

    # Get active subscribers count
    active_subscribers = SubscribedUser.query.filter(
        SubscribedUser.S_ID == id,
        SubscribedUser.end_date > datetime.now(UTC)
    ).count()

    if request.method == 'POST':
        plan = request.form.get('plan')
        price = float(request.form.get('price'))
        days = int(request.form.get('days'))
        usage_per_day = int(request.form.get('usage_per_day'))
        tier = int(request.form.get('tier', subscription.tier))
        features = request.form.get('features', subscription.features)

        # Validate inputs
        if not plan or price <= 0 or days <= 0 or usage_per_day <= 0 or tier <= 0:
            flash('Invalid subscription details. Please check your input.', 'danger')
            return redirect(url_for('admin.admin_edit_subscription', id=id))

        # Check if plan name already exists with a different ID
        existing_plan = Subscription.query.filter(
            Subscription.plan == plan,
            Subscription.S_ID != id
        ).first()

        if existing_plan:
            flash('A subscription plan with this name already exists.', 'danger')
            return redirect(url_for('admin.admin_edit_subscription', id=id))

        subscription.plan = plan
        subscription.price = price
        subscription.days = days
        subscription.usage_per_day = usage_per_day
        subscription.tier = tier
        subscription.features = features

        db.session.commit()

        flash('Subscription plan updated successfully!', 'success')
        return redirect(url_for('admin.admin_subscriptions'))

    return render_template('admin/edit_subscription.html',
                          subscription=subscription,
                          active_subscribers=active_subscribers)


@admin_bp.route('/subscriptions/archive/<int:id>', methods=['POST'])
@admin_required
def admin_archive_subscription(id):
    subscription = Subscription.query.get_or_404(id)

    # Check if already archived
    if subscription.archived_at:
        flash('This subscription plan is already archived.', 'warning')
        return redirect(url_for('admin.admin_subscriptions'))

    # Archive the subscription plan
    subscription.is_active = False
    subscription.archived_at = datetime.now(UTC)
    db.session.commit()

    flash('Subscription plan has been archived successfully.', 'success')
    return redirect(url_for('admin.admin_subscriptions'))


@admin_bp.route('/subscriptions/restore/<int:id>', methods=['POST'])
@admin_required
def admin_restore_subscription(id):
    subscription = Subscription.query.get_or_404(id)

    # Check if not archived
    if not subscription.archived_at:
        flash('This subscription plan is not archived.', 'warning')
        return redirect(url_for('admin.admin_subscriptions'))

    # Restore the subscription plan
    subscription.is_active = True
    subscription.archived_at = None
    db.session.commit()

    flash('Subscription plan has been restored successfully.', 'success')
    return redirect(url_for('admin.admin_subscriptions'))


@admin_bp.route('/subscriptions/delete/<int:id>', methods=['POST'])
@admin_required
def admin_delete_subscription(id):
    subscription = Subscription.query.get_or_404(id)

    # Check if there are any users subscribed to this plan (active or inactive)
    if subscription.subscribed_users:
        flash('Cannot delete subscription plan as it has users associated with it. Please remove the user subscriptions first.', 'danger')
        return redirect(url_for('admin.admin_subscriptions'))

    # Check if there are any payments or history records associated with this plan
    payment_count = Payment.query.filter_by(subscription_id=id).count()
    history_count = SubscriptionHistory.query.filter(
        (SubscriptionHistory.S_ID == id) |
        (SubscriptionHistory.previous_S_ID == id)
    ).count()

    if payment_count > 0 or history_count > 0:
        # Instead of blocking, mark as archived
        subscription.is_active = False
        subscription.archived_at = datetime.now(UTC)
        db.session.commit()

        flash('Subscription plan has been archived as it has payment or history records associated with it.', 'warning')
        return redirect(url_for('admin.admin_subscriptions'))

    # If no constraints, perform actual deletion
    db.session.delete(subscription)
    db.session.commit()

    flash('Subscription plan deleted successfully!', 'success')
    return redirect(url_for('admin.admin_subscriptions'))


# ===========================
# Subscribed Users Management
# ===========================

@admin_bp.route('/subscribed-users')
@admin_required
def admin_subscribed_users():
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'subscribed_users_view'):
        flash("You don't have permission to access this page.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    # Get filter parameters
    status_filter = request.args.get('status', 'all')
    plan_filter = request.args.get('plan', 'all')
    search_email = request.args.get('search_email', '').strip()

    # Get current time
    now = datetime.now(UTC)

    # Base query with joins
    query = (
        db.session.query(
            SubscribedUser,
            User,
            Subscription
        )
        .join(User, SubscribedUser.U_ID == User.id)
        .join(Subscription, SubscribedUser.S_ID == Subscription.S_ID)
    )

    # Apply email search filter
    if search_email:
        query = query.filter(User.company_email.ilike(f'%{search_email}%'))

    # Apply filters based on status
    if status_filter == 'active':
        query = query.filter(
            SubscribedUser._is_active == True,
            SubscribedUser.end_date > now
        )
    elif status_filter == 'cancelled':
        query = query.filter(
            SubscribedUser._is_active == False,
            SubscribedUser.end_date > now
        )
    elif status_filter == 'expired':
        query = query.filter(SubscribedUser.end_date <= now)

    if plan_filter != 'all':
        query = query.filter(Subscription.S_ID == plan_filter)

    # Get all subscription plans for the filter dropdown
    all_plans = Subscription.query.all()

    # Execute the query
    subscribed_users = query.order_by(SubscribedUser.end_date.desc()).all()

    # CALCULATE CORRECT STATISTICS
    total_subscriptions = SubscribedUser.query.count()

    active_subscriptions = SubscribedUser.query.filter(
        SubscribedUser._is_active == True,
        SubscribedUser.end_date > now
    ).count()

    seven_days_from_now = now + timedelta(days=7)
    expiring_soon_count = SubscribedUser.query.filter(
        SubscribedUser._is_active == True,
        SubscribedUser.end_date > now,
        SubscribedUser.end_date <= seven_days_from_now
    ).count()

    cancelled_subscriptions = SubscribedUser.query.filter(
        SubscribedUser._is_active == False,
        SubscribedUser.end_date > now
    ).count()

    # Ensure timezone awareness and calculate token data for each subscription
    subscribed_users_with_tokens = []
    for i, (sub_user, user, sub) in enumerate(subscribed_users):
        if sub_user.end_date.tzinfo is None:
            sub_user.end_date = sub_user.end_date.replace(tzinfo=UTC)

        # Get token purchase data for this subscription
        token_data = db.session.query(
            func.sum(TokenPurchase.token_count).label('total_tokens_purchased'),
            func.count(TokenPurchase.id).label('purchase_count')
        ).filter(
            TokenPurchase.subscription_id == sub_user.id,
            TokenPurchase.status == 'completed'
        ).first()

        # Get remaining tokens from UserToken
        remaining_tokens = db.session.query(
            func.sum(UserToken.tokens_remaining)
        ).filter(
            UserToken.subscription_id == sub_user.id
        ).scalar() or 0

        subscribed_users_with_tokens.append({
            'sub_user': sub_user,
            'user': user,
            'subscription': sub,
            'total_tokens_purchased': token_data.total_tokens_purchased or 0,
            'purchase_count': token_data.purchase_count or 0,
            'tokens_remaining': remaining_tokens
        })

    # Define a function to check if a subscription is active
    def is_active(sub_user):
        return sub_user._is_active and sub_user.end_date > now

    return render_template('admin/subscribed_users.html',
                          subscribed_users=subscribed_users_with_tokens,
                          all_plans=all_plans,
                          status_filter=status_filter,
                          plan_filter=plan_filter,
                          search_email=search_email,
                          now=now,
                          is_active=is_active,
                          total_subscriptions=total_subscriptions,
                          active_subscriptions=active_subscriptions,
                          expiring_soon_count=expiring_soon_count,
                          cancelled_subscriptions=cancelled_subscriptions)


@admin_bp.route('/subscribed-users/new', methods=['GET', 'POST'])
@admin_required
def admin_new_subscribed_user():
    if request.method == 'POST':
        user_id = int(request.form.get('user_id'))
        subscription_id = int(request.form.get('subscription_id'))
        auto_renew = request.form.get('auto_renew', 'off') == 'on'

        # Check if user exists
        user = User.query.get(user_id)
        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('admin.admin_new_subscribed_user'))

        # Check if subscription exists
        subscription = Subscription.query.get(subscription_id)
        if not subscription:
            flash('Subscription plan not found.', 'danger')
            return redirect(url_for('admin.admin_new_subscribed_user'))

        # Check if user already has this subscription
        existing_sub = SubscribedUser.query.filter(
            SubscribedUser.U_ID == user_id,
            SubscribedUser.S_ID == subscription_id,
            SubscribedUser.end_date > datetime.now(UTC)
        ).first()

        if existing_sub:
            flash('User already has an active subscription to this plan.', 'warning')
            return redirect(url_for('admin.admin_subscribed_users'))

        # Calculate dates
        start_date = datetime.now(UTC)
        end_date = start_date + timedelta(days=subscription.days)

        new_subscribed_user = SubscribedUser(
            U_ID=user_id,
            S_ID=subscription_id,
            start_date=start_date,
            end_date=end_date,
            current_usage=0,
            is_auto_renew=auto_renew
        )

        new_payment = Payment(
            base_amount=subscription.price,
            user_id=user_id,
            subscription_id=subscription_id,
            razorpay_order_id=f"manual_admin_{int(time.time())}",
            razorpay_payment_id=f"manual_admin_{int(time.time())}",
            currency='INR',
            status='completed',
            payment_type='new',
            created_at=datetime.now(UTC)
        )

        # Add subscription history record
        new_history = SubscriptionHistory(
            U_ID=user_id,
            S_ID=subscription_id,
            action='new',
            created_at=datetime.now(UTC)
        )

        db.session.add(new_subscribed_user)
        db.session.add(new_payment)
        db.session.add(new_history)
        db.session.commit()

        flash('User subscription added successfully with payment record!', 'success')
        return redirect(url_for('admin.admin_subscribed_users'))

    # Get all active users (email confirmed)
    users = User.query.filter_by(email_confirmed=True).all()

    # Get all subscription plans
    subscriptions = Subscription.query.all()

    return render_template('admin/new_subscribed_user.html',
                          users=users,
                          subscriptions=subscriptions)


@admin_bp.route('/subscribed-users/reactivate/<int:id>', methods=['POST'])
@admin_required
def admin_reactivate_subscription(id):
    """Reactivate a cancelled subscription"""
    subscribed_user = SubscribedUser.query.get_or_404(id)

    # Check if subscription is actually cancelled and not expired
    if subscribed_user._is_active:
        flash('This subscription is already active.', 'warning')
        return redirect(url_for('admin.admin_subscribed_users'))

    if subscribed_user.end_date <= datetime.now(UTC):
        flash('Cannot reactivate an expired subscription. Please create a new subscription.', 'danger')
        return redirect(url_for('admin.admin_subscribed_users'))

    try:
        # Reactivate the subscription
        subscribed_user._is_active = True

        # Create a history record for reactivation
        history_record = SubscriptionHistory(
            U_ID=subscribed_user.U_ID,
            S_ID=subscribed_user.S_ID,
            action='reactivate',
            created_at=datetime.now(UTC)
        )

        db.session.add(history_record)
        db.session.commit()

        # Get user details for the flash message
        user = User.query.get(subscribed_user.U_ID)
        subscription = Subscription.query.get(subscribed_user.S_ID)

        flash(f'Subscription for {user.name} to {subscription.plan} plan has been reactivated successfully!', 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error reactivating subscription: {str(e)}")
        flash(f'Error reactivating subscription: {str(e)}', 'danger')

    return redirect(url_for('admin.admin_subscribed_users'))


@admin_bp.route('/subscribed-users/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_subscribed_user(id):
    # Fetch the subscribed user and related data
    subscribed_user = SubscribedUser.query.get_or_404(id)
    user = User.query.get(subscribed_user.U_ID)

    if request.method == 'POST':
        # Extract form data
        subscription_id = int(request.form.get('subscription_id'))
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        additional_usage = int(request.form.get('additional_usage', 0))
        decrement_usage = int(request.form.get('decrement_usage', 0))
        auto_renew = request.form.get('auto_renew', 'off') == 'on'
        is_active = request.form.get('is_active', 'off') == 'on'

        # Validate the subscription plan exists
        subscription = Subscription.query.get(subscription_id)
        if not subscription:
            flash('Subscription plan not found.', 'danger')
            return redirect(url_for('admin.admin_edit_subscribed_user', id=id))

        # Check if start_date and end_date are provided
        if not start_date_str or not end_date_str:
            flash('Start date and End date are required.', 'danger')
            return redirect(url_for('admin.admin_edit_subscribed_user', id=id))

        # Parse dates
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(tzinfo=UTC)
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(tzinfo=UTC)
            if end_date <= start_date:
                raise ValueError("End date must be after start date")
        except Exception as e:
            flash(f'Invalid date format: {str(e)}', 'danger')
            return redirect(url_for('admin.admin_edit_subscribed_user', id=id))

        # Validate additional usage and decrement
        if additional_usage < 0:
            flash('Additional usage cannot be negative.', 'danger')
            return redirect(url_for('admin.admin_edit_subscribed_user', id=id))

        if decrement_usage < 0:
            flash('Decrement usage cannot be negative.', 'danger')
            return redirect(url_for('admin.admin_edit_subscribed_user', id=id))

        # Check if subscription has changed and record history
        old_subscription_id = subscribed_user.S_ID
        old_is_active = subscribed_user._is_active

        if old_subscription_id != subscription_id:
            action = 'upgrade' if subscription.tier > Subscription.query.get(old_subscription_id).tier else 'downgrade'

            # Create subscription history record
            history_record = SubscriptionHistory(
                U_ID=subscribed_user.U_ID,
                S_ID=subscription_id,
                action=action,
                previous_S_ID=old_subscription_id,
                created_at=datetime.now(UTC)
            )
            db.session.add(history_record)

        # Check if status changed from inactive to active or vice versa
        if old_is_active != is_active:
            action = 'reactivate' if is_active else 'admin_cancel'
            history_record = SubscriptionHistory(
                U_ID=subscribed_user.U_ID,
                S_ID=subscribed_user.S_ID,
                action=action,
                created_at=datetime.now(UTC)
            )
            db.session.add(history_record)

        # Update the subscribed user's details
        subscribed_user.S_ID = subscription_id
        subscribed_user.start_date = start_date
        subscribed_user.end_date = end_date

        # Update custom usage limit: handle both increment and decrement
        current_custom = subscribed_user.custom_usage_limit if subscribed_user.custom_usage_limit else 0
        usage_change_message = None

        if additional_usage > 0 and decrement_usage > 0:
            flash('Cannot add and subtract usage at the same time. Please use only one field.', 'danger')
            return redirect(url_for('admin.admin_edit_subscribed_user', id=id))
        elif additional_usage > 0:
            subscribed_user.custom_usage_limit = current_custom + additional_usage
            usage_change_message = f'Added {additional_usage} to usage limit.'
        elif decrement_usage > 0:
            new_custom = current_custom - decrement_usage
            if new_custom < 0:
                flash(f'Cannot subtract {decrement_usage} from current additional limit of {current_custom}. Result would be negative.', 'danger')
                return redirect(url_for('admin.admin_edit_subscribed_user', id=id))
            subscribed_user.custom_usage_limit = new_custom if new_custom > 0 else None
            usage_change_message = f'Subtracted {decrement_usage} from usage limit.'

        subscribed_user.is_auto_renew = auto_renew
        subscribed_user._is_active = is_active

        db.session.commit()

        if usage_change_message:
            flash(f'User subscription updated successfully! {usage_change_message}', 'success')
        else:
            flash('User subscription updated successfully!', 'success')
        return redirect(url_for('admin.admin_subscribed_users'))

    # Fetch all subscriptions for the dropdown
    subscriptions = Subscription.query.all()
    return render_template('admin/edit_subscribed_user.html',
                           subscribed_user=subscribed_user,
                           user=user,
                           subscriptions=subscriptions)


@admin_bp.route('/subscribed-users/extend/<int:id>', methods=['POST'])
@admin_required
def admin_extend_subscription(id):
    subscribed_user = SubscribedUser.query.get_or_404(id)
    extension_days = int(request.form.get('extension_days', 0))

    if extension_days <= 0:
        flash('Extension days must be positive.', 'danger')
    elif not subscribed_user._is_active:
        flash('Cannot extend a cancelled subscription. Please reactivate it first.', 'warning')
    else:
        # Extend the subscription
        current_end_date = subscribed_user.end_date
        new_end_date = current_end_date + timedelta(days=extension_days)
        subscribed_user.end_date = new_end_date

        # Create a history record for this extension
        history_record = SubscriptionHistory(
            U_ID=subscribed_user.U_ID,
            S_ID=subscribed_user.S_ID,
            action='extend',
            created_at=datetime.now(UTC)
        )

        db.session.add(history_record)
        db.session.commit()
        flash(f'Subscription extended by {extension_days} days successfully!', 'success')

    return redirect(url_for('admin.admin_subscribed_users'))


@admin_bp.route('/subscribed-users/delete/<int:id>', methods=['POST'])
@admin_required
def admin_delete_subscribed_user(id):
    subscribed_user = SubscribedUser.query.get_or_404(id)

    # Get user details for the flash message
    user = User.query.get(subscribed_user.U_ID)
    subscription = Subscription.query.get(subscribed_user.S_ID)

    try:
        # Check if there are any usage logs associated with this subscription
        usage_logs = UsageLog.query.filter_by(subscription_id=id).all()

        if usage_logs:
            # Find if user has any other active subscription
            other_subscription = SubscribedUser.query.filter(
                SubscribedUser.U_ID == subscribed_user.U_ID,
                SubscribedUser.id != id,
                SubscribedUser.end_date > datetime.now(UTC)
            ).first()

            if other_subscription:
                # Reassign logs to that subscription
                for log in usage_logs:
                    log.subscription_id = other_subscription.id
                db.session.flush()
            else:
                # Delete the usage logs since there's no other subscription
                for log in usage_logs:
                    db.session.delete(log)
                db.session.flush()

        # Create a history record for deletion
        history_record = SubscriptionHistory(
            U_ID=subscribed_user.U_ID,
            S_ID=subscribed_user.S_ID,
            action='admin_delete',
            created_at=datetime.now(UTC)
        )

        db.session.add(history_record)
        db.session.delete(subscribed_user)
        db.session.commit()

        flash(f'Subscription for {user.name} to {subscription.plan} plan deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting subscription: {str(e)}', 'danger')
        current_app.logger.error(f"Error deleting subscription: {str(e)}")

    return redirect(url_for('admin.admin_subscribed_users'))


# ===========================
# User Management
# ===========================

@admin_bp.route('/users')
@admin_required
def admin_users():
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'user_management'):
        flash("You don't have permission to access this page.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    # Get filter parameters
    status_filter = request.args.get('status', 'all')
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # Start with base query
    query = User.query

    # Apply filters based on USER status (not subscription status)
    if status_filter == 'active':
        query = query.filter_by(email_confirmed=True)
    elif status_filter == 'unconfirmed':
        query = query.filter_by(email_confirmed=False)
    elif status_filter == 'admin':
        query = query.filter_by(is_admin=True)

    # Apply search if provided
    if search_query:
        search_filter = or_(
            User.name.ilike(f'%{search_query}%'),
            User.company_email.ilike(f'%{search_query}%')
        )
        query = query.filter(search_filter)

    # Execute query with pagination
    pagination = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Get subscription status for each user (separate from user account status)
    user_subscriptions = {}
    for user in pagination.items:
        active_sub = (
            db.session.query(SubscribedUser, Subscription)
            .join(Subscription, SubscribedUser.S_ID == Subscription.S_ID)
            .filter(
                SubscribedUser.U_ID == user.id,
                SubscribedUser.end_date > datetime.now(UTC),
                SubscribedUser._is_active == True
            )
            .first()
        )
        user_subscriptions[user.id] = active_sub

    # Calculate user statistics
    total_users = User.query.count()
    active_users = User.query.filter_by(email_confirmed=True).count()
    unconfirmed_users = User.query.filter_by(email_confirmed=False).count()
    admin_users_count = User.query.filter_by(is_admin=True).count()

    # Calculate subscription statistics separately
    now = datetime.now(UTC)
    users_with_active_subscriptions = db.session.query(
        func.count(func.distinct(SubscribedUser.U_ID))
    ).filter(
        SubscribedUser.end_date > now,
        SubscribedUser._is_active == True
    ).scalar() or 0

    return render_template('admin/users.html',
                           users=pagination.items,
                           pagination=pagination,
                           user_subscriptions=user_subscriptions,
                           status_filter=status_filter,
                           search_query=search_query,
                           total_users=total_users,
                           active_users=active_users,
                           unconfirmed_users=unconfirmed_users,
                           admin_users=admin_users_count,
                           users_with_active_subscriptions=users_with_active_subscriptions,
                           get_user_status_display=get_user_status_display)


@admin_bp.route('/add_user', methods=['POST'])
@admin_required
def admin_add_user():
    name = request.form.get('name', '').strip()
    company_email = request.form.get('company_email', '').lower().strip()
    password = request.form.get('password', '')
    email_confirmed = 'email_confirmed' in request.form
    is_admin = 'is_admin' in request.form

    # Validate input data
    errors = validate_user_data(name, company_email, password)
    if not password:
        errors.append("Password is required for new users.")

    # If there are validation errors, flash them and redirect
    if errors:
        for error in errors:
            flash(error, 'danger')
        return redirect(url_for('admin.admin_users'))

    try:
        # Create new user
        new_user = User(
            name=name,
            company_email=company_email,
            email_confirmed=email_confirmed,
            is_admin=is_admin,
            created_at=datetime.now(UTC)
        )
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()
        flash(f'User {name} ({company_email}) created successfully!', 'success')
        current_app.logger.info(f"Admin created new user: {company_email}")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Database error creating user: {str(e)}")
        flash(f'Error creating user: {str(e)}', 'danger')

    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/edit_user/<int:user_id>', methods=['POST'])
@admin_required
def admin_edit_user(user_id):
    user = User.query.get_or_404(user_id)

    name = request.form.get('name', '').strip()
    email = request.form.get('company_email', '').lower().strip()
    email_confirmed = 'email_confirmed' in request.form
    is_admin = 'is_admin' in request.form
    password = request.form.get('password', '').strip()

    # Validate input data
    errors = validate_user_data(name, email, password, user_id)

    # If there are validation errors, flash them and redirect
    if errors:
        for error in errors:
            flash(error, 'danger')
        return redirect(url_for('admin.admin_users'))

    try:
        # Update user details
        user.name = name
        user.company_email = email
        user.email_confirmed = email_confirmed

        # Only update admin status if current user is not modifying themselves
        current_admin_id = session.get('admin_id')
        if user_id != current_admin_id:
            user.is_admin = is_admin
        else:
            if not is_admin:
                flash('You cannot remove your own admin privileges.', 'warning')

        # Update password if provided
        if password:
            user.set_password(password)

        db.session.commit()
        flash('User updated successfully!', 'success')
        current_app.logger.info(f"Admin updated user: {user.company_email}")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating user {user_id}: {str(e)}")
        flash(f'Error updating user: {str(e)}', 'danger')

    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/remove_user/<int:user_id>', methods=['POST'])
@admin_required
def remove_user(user_id):
    """Remove a user and all associated data from the system."""
    user = User.query.get_or_404(user_id)

    # Prevent deleting a user that has the same email as the logged-in admin
    current_admin_email = session.get('email_id', '').lower()
    if user.company_email and user.company_email.lower() == current_admin_email:
        flash('You cannot delete a user account associated with your admin email.', 'danger')
        return redirect(url_for('admin.admin_users'))

    # Check if the user has active subscriptions
    active_subscription = SubscribedUser.query.filter(
        SubscribedUser.U_ID == user_id,
        SubscribedUser.end_date > datetime.now(UTC),
        SubscribedUser._is_active == True
    ).first()

    if active_subscription:
        flash('Cannot delete user with active subscriptions. Please cancel their subscriptions first.', 'warning')
        return redirect(url_for('admin.admin_users'))

    # Store user details for the success message
    user_email = user.company_email
    user_name = user.name

    try:
        # Begin a transaction
        db.session.begin_nested()

        # Delete all related records in the correct order

        # 1. Delete invoice addresses associated with the user's payments
        payment_ids = [p.iid for p in Payment.query.filter_by(user_id=user_id).all()]
        if payment_ids:
            InvoiceAddress.query.filter(InvoiceAddress.payment_id.in_(payment_ids)).delete(synchronize_session=False)

        # 2. Delete payments
        Payment.query.filter_by(user_id=user_id).delete(synchronize_session=False)

        # 3. Delete search history
        SearchHistory.query.filter_by(u_id=user_id).delete(synchronize_session=False)

        # 4. Delete usage logs
        UsageLog.query.filter_by(user_id=user_id).delete(synchronize_session=False)

        # 5. Delete subscription history
        SubscriptionHistory.query.filter_by(U_ID=user_id).delete(synchronize_session=False)

        # 6. Delete subscribed users
        SubscribedUser.query.filter_by(U_ID=user_id).delete(synchronize_session=False)

        # 7. Finally, delete the user
        db.session.delete(user)

        # Commit the transaction
        db.session.commit()

        current_app.logger.info(f"User {user_id} ({user_email}) successfully deleted by admin")
        flash(f'User {user_name} ({user_email}) removed successfully.', 'success')

    except Exception as e:
        # Rollback in case of error
        db.session.rollback()
        current_app.logger.error(f"Error deleting user {user_id}: {str(e)}")
        flash(f'Error deleting user: {str(e)}', 'danger')

    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/reset_user_password/<int:user_id>', methods=['POST'])
@admin_required
def admin_reset_user_password(user_id):
    user = User.query.get_or_404(user_id)

    # Generate a 12-character password with mix of letters, numbers, and symbols
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    new_password = ''.join(secrets.choice(alphabet) for i in range(12))

    try:
        # Update the user's password
        user.set_password(new_password)
        db.session.commit()

        flash(f'Password reset successfully! New password: {new_password}', 'success')
        current_app.logger.info(f"Admin reset password for user: {user.company_email}")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error resetting password for user {user_id}: {str(e)}")
        flash(f'Error resetting password: {str(e)}', 'danger')

    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/users/<int:user_id>')
@admin_required
def admin_user_details(user_id):
    user = User.query.get_or_404(user_id)

    # Get user's subscription history
    subscriptions = (
        db.session.query(SubscribedUser, Subscription)
        .join(Subscription, SubscribedUser.S_ID == Subscription.S_ID)
        .filter(SubscribedUser.U_ID == user_id)
        .order_by(SubscribedUser.start_date.desc())
        .all()
    )

    # Get user's payment history
    payments = (
        db.session.query(Payment, Subscription)
        .join(Subscription, Payment.subscription_id == Subscription.S_ID)
        .filter(Payment.user_id == user_id)
        .order_by(Payment.created_at.desc())
        .all()
    )

    # Get user's search/usage history (recent)
    search_history = SearchHistory.query.filter_by(u_id=user_id)\
        .order_by(SearchHistory.created_at.desc())\
        .limit(10)\
        .all()

    # Calculate current date for checking subscription status - TIMEZONE AWARE
    now = datetime.now(UTC)

    # TIMEZONE FIX: Ensure all datetime objects are timezone-aware before template rendering

    # Fix user datetime fields
    if user.created_at and user.created_at.tzinfo is None:
        user.created_at = user.created_at.replace(tzinfo=UTC)

    # Fix subscription datetime fields
    for sub_user, subscription in subscriptions:
        if sub_user.start_date and sub_user.start_date.tzinfo is None:
            sub_user.start_date = sub_user.start_date.replace(tzinfo=UTC)
        if sub_user.end_date and sub_user.end_date.tzinfo is None:
            sub_user.end_date = sub_user.end_date.replace(tzinfo=UTC)
        if hasattr(sub_user, 'last_usage_reset') and sub_user.last_usage_reset and sub_user.last_usage_reset.tzinfo is None:
            sub_user.last_usage_reset = sub_user.last_usage_reset.replace(tzinfo=UTC)

    # Fix payment datetime fields
    for payment, subscription in payments:
        if payment.created_at and payment.created_at.tzinfo is None:
            payment.created_at = payment.created_at.replace(tzinfo=UTC)
        if hasattr(payment, 'invoice_date') and payment.invoice_date and payment.invoice_date.tzinfo is None:
            payment.invoice_date = payment.invoice_date.replace(tzinfo=UTC)

    # Fix search history datetime fields
    for search in search_history:
        if search.created_at and search.created_at.tzinfo is None:
            search.created_at = search.created_at.replace(tzinfo=UTC)

    return render_template('admin/user_details.html',
                          user=user,
                          subscriptions=subscriptions,
                          payments=payments,
                          search_history=search_history,
                          now=now,
                          timezone=dt_module.timezone)


# ===========================
# Payments
# ===========================

@admin_bp.route('/payments')
@admin_required
def admin_payments():
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'payments'):
        flash("You don't have permission to access this page.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    # Get filter parameters
    status_filter = request.args.get('status', 'all')
    date_filter = request.args.get('date_range', '30')
    search_query = request.args.get('search', '')
    payment_type_filter = request.args.get('payment_type', 'all')
    page = request.args.get('page', 1, type=int)
    per_page = 50

    now = datetime.now(UTC)

    # Build date filter
    date_ranges = {
        '7': now - timedelta(days=7),
        '30': now - timedelta(days=30),
        '90': now - timedelta(days=90),
        '180': now - timedelta(days=180),
        '365': now - timedelta(days=365)
    }
    date_threshold = date_ranges.get(date_filter, date_ranges['30'])

    try:
        # Query subscription payments
        subscription_results = []
        if payment_type_filter in ['all', 'subscription']:
            sub_query = (
                db.session.query(
                    Payment.iid.label('payment_id'),
                    literal('subscription').label('payment_category'),
                    Payment.invoice_number,
                    Payment.razorpay_order_id,
                    Payment.razorpay_payment_id,
                    Payment.total_amount,
                    Payment.base_amount,
                    Payment.gst_amount,
                    Payment.status,
                    Payment.created_at,
                    Payment.payment_type,
                    Payment.user_id,
                    User.name.label('user_name'),
                    User.company_email,
                    Subscription.plan.label('description'),
                    literal(None).label('token_count')
                )
                .join(User, Payment.user_id == User.id)
                .join(Subscription, Payment.subscription_id == Subscription.S_ID)
            )

            # Apply filters to subscription query
            if status_filter != 'all':
                sub_query = sub_query.filter(Payment.status == status_filter)
            if date_filter in date_ranges:
                sub_query = sub_query.filter(Payment.created_at >= date_threshold)
            if search_query:
                sub_query = sub_query.filter(
                    or_(
                        User.name.ilike(f'%{search_query}%'),
                        User.company_email.ilike(f'%{search_query}%'),
                        Payment.invoice_number.ilike(f'%{search_query}%'),
                        Payment.razorpay_order_id.ilike(f'%{search_query}%')
                    )
                )

            subscription_results = sub_query.order_by(Payment.created_at.desc()).all()

        # Query token payments
        token_results = []
        if payment_type_filter in ['all', 'tokens']:
            token_query = (
                db.session.query(
                    TokenPurchase.id.label('payment_id'),
                    literal('tokens').label('payment_category'),
                    TokenPurchase.invoice_number,
                    TokenPurchase.razorpay_order_id,
                    TokenPurchase.razorpay_payment_id,
                    TokenPurchase.total_amount,
                    TokenPurchase.base_amount,
                    TokenPurchase.gst_amount,
                    TokenPurchase.status,
                    TokenPurchase.created_at,
                    literal('token_purchase').label('payment_type'),
                    TokenPurchase.user_id,
                    User.name.label('user_name'),
                    User.company_email,
                    cast(TokenPurchase.token_count, String).label('description'),
                    TokenPurchase.token_count
                )
                .join(User, TokenPurchase.user_id == User.id)
                .join(SubscribedUser, TokenPurchase.subscription_id == SubscribedUser.id)
            )

            # Apply filters to token query
            if status_filter != 'all':
                token_query = token_query.filter(TokenPurchase.status == status_filter)
            if date_filter in date_ranges:
                token_query = token_query.filter(TokenPurchase.created_at >= date_threshold)
            if search_query:
                token_query = token_query.filter(
                    or_(
                        User.name.ilike(f'%{search_query}%'),
                        User.company_email.ilike(f'%{search_query}%'),
                        TokenPurchase.invoice_number.ilike(f'%{search_query}%'),
                        TokenPurchase.razorpay_order_id.ilike(f'%{search_query}%')
                    )
                )

            token_results = token_query.order_by(TokenPurchase.created_at.desc()).all()

        # Combine results and sort by created_at
        all_results = list(subscription_results) + list(token_results)
        all_results.sort(key=lambda x: x.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)

        # Calculate pagination
        total_count = len(all_results)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        payments_data = all_results[start_idx:end_idx]

    except Exception as e:
        current_app.logger.error(f"Error in payments query: {str(e)}")
        payments_data = []
        total_count = 0

    # Calculate pagination info
    total_pages = (total_count + per_page - 1) // per_page
    has_prev = page > 1
    has_next = page < total_pages

    # Create pagination object-like structure
    class PaginationInfo:
        def __init__(self, items, page, per_page, total, has_prev, has_next, prev_num, next_num, pages):
            self.items = items
            self.page = page
            self.per_page = per_page
            self.total = total
            self.has_prev = has_prev
            self.has_next = has_next
            self.prev_num = prev_num if has_prev else None
            self.next_num = next_num if has_next else None
            self.pages = pages

        def iter_pages(self, left_edge=2, left_current=2, right_current=3, right_edge=2):
            last = self.pages
            for num in range(1, last + 1):
                if (num <= left_edge or
                    (self.page - left_current - 1 < num < self.page + right_current) or
                    num > last - right_edge):
                    yield num

    payments = PaginationInfo(
        items=payments_data,
        page=page,
        per_page=per_page,
        total=total_count,
        has_prev=has_prev,
        has_next=has_next,
        prev_num=page - 1,
        next_num=page + 1,
        pages=total_pages
    )

    # Calculate statistics
    subscription_stats = {
        'total_payments': Payment.query.count(),
        'total_revenue': db.session.query(func.sum(Payment.total_amount))
                            .filter(Payment.status == 'completed').scalar() or 0,
        'completed_payments': Payment.query.filter(Payment.status == 'completed').count()
    }

    token_stats = {
        'total_payments': TokenPurchase.query.count(),
        'total_revenue': db.session.query(func.sum(TokenPurchase.total_amount))
                            .filter(TokenPurchase.status == 'completed').scalar() or 0,
        'completed_payments': TokenPurchase.query.filter(TokenPurchase.status == 'completed').count()
    }

    # Combined stats
    stats = {
        'total_payments': subscription_stats['total_payments'] + token_stats['total_payments'],
        'total_revenue': subscription_stats['total_revenue'] + token_stats['total_revenue'],
        'completed_payments': subscription_stats['completed_payments'] + token_stats['completed_payments'],
        'subscription_stats': subscription_stats,
        'token_stats': token_stats,
        'payment_type_breakdown': {
            'subscription': subscription_stats['completed_payments'],
            'tokens': token_stats['completed_payments']
        }
    }

    # Revenue trend for chart - combined from both tables
    subscription_trend = (
        db.session.query(
            func.date_trunc('day', Payment.created_at).label('day'),
            func.sum(Payment.total_amount).label('total_revenue'),
            literal('subscription').label('type')
        )
        .filter(Payment.status == 'completed')
        .filter(Payment.created_at >= now - timedelta(days=30))
        .group_by('day')
        .all()
    )

    token_trend = (
        db.session.query(
            func.date_trunc('day', TokenPurchase.created_at).label('day'),
            func.sum(TokenPurchase.total_amount).label('total_revenue'),
            literal('tokens').label('type')
        )
        .filter(TokenPurchase.status == 'completed')
        .filter(TokenPurchase.created_at >= now - timedelta(days=30))
        .group_by('day')
        .all()
    )

    # Combine and aggregate revenue trends
    revenue_by_day = {}
    for trend in subscription_trend + token_trend:
        day = trend.day.date()
        if day not in revenue_by_day:
            revenue_by_day[day] = 0
        revenue_by_day[day] += trend.total_revenue

    # Convert to list format for template
    revenue_trend = [
        type('obj', (object,), {'day': day, 'total_revenue': revenue})()
        for day, revenue in sorted(revenue_by_day.items())
    ]

    return render_template('admin/payments.html',
                           payments=payments,
                           stats=stats,
                           revenue_trend=revenue_trend,
                           filters={
                               'status': status_filter,
                               'date_range': date_filter,
                               'search': search_query,
                               'payment_type': payment_type_filter
                           })


@admin_bp.route('/payments/<string:order_id>')
@admin_required
def admin_payment_details(order_id):
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'payments'):
        flash("You don't have permission to access this page.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    # Determine payment type and get details
    payment_details = None
    payment_type = None

    # Try to find in subscription payments first (by invoice_number)
    subscription_payment = (
        db.session.query(Payment, User, Subscription, InvoiceAddress)
        .join(User, Payment.user_id == User.id)
        .join(Subscription, Payment.subscription_id == Subscription.S_ID)
        .outerjoin(InvoiceAddress, InvoiceAddress.payment_id == Payment.iid)
        .filter(Payment.invoice_number == order_id)
        .first()
    )

    if subscription_payment:
        payment_type = 'subscription'
        payment, user, subscription, invoice_address = subscription_payment
        payment_details = {
            'payment': payment,
            'user': user,
            'subscription': subscription,
            'invoice_address': invoice_address,
            'description': f"{subscription.plan} Subscription",
            'related_items': None
        }
    else:
        # Try to find in token purchases (by invoice_number)
        token_payment = (
            db.session.query(TokenPurchase, User, SubscribedUser, Subscription)
            .join(User, TokenPurchase.user_id == User.id)
            .join(SubscribedUser, TokenPurchase.subscription_id == SubscribedUser.id)
            .join(Subscription, SubscribedUser.S_ID == Subscription.S_ID)
            .filter(TokenPurchase.invoice_number == order_id)
            .first()
        )

        if token_payment:
            payment_type = 'tokens'
            payment, user, subscribed_user, subscription = token_payment

            # Get related user tokens
            user_tokens = (
                UserToken.query
                .filter(UserToken.purchase_id == payment.id)
                .all()
            )

            payment_details = {
                'payment': payment,
                'user': user,
                'subscription': subscription,
                'subscribed_user': subscribed_user,
                'user_tokens': user_tokens,
                'description': f"{payment.token_count} Additional Tokens",
                'related_items': user_tokens
            }

    if not payment_details:
        flash(f"No payment found for Order ID: {order_id}", "danger")
        return redirect(url_for('admin.admin_payments'))

    # Get Razorpay details if available
    razorpay_details = None
    payment_obj = payment_details['payment']

    if (payment_obj.razorpay_payment_id and
        not payment_obj.razorpay_payment_id.startswith('manual_')):
        try:
            razorpay_details = razorpay_client.payment.fetch(payment_obj.razorpay_payment_id)
        except Exception as e:
            current_app.logger.warning(f"Razorpay fetch error: {str(e)}")

    # Get related payment history for this user
    user_id = payment_details['user'].id

    related_subscription_payments = (
        Payment.query
        .filter(Payment.user_id == user_id)
        .order_by(Payment.created_at.desc())
        .limit(5)
        .all()
    )

    related_token_payments = (
        TokenPurchase.query
        .filter(TokenPurchase.user_id == user_id)
        .order_by(TokenPurchase.created_at.desc())
        .limit(5)
        .all()
    )

    return render_template('admin/payment_details.html',
                           payment_details=payment_details,
                           payment_type=payment_type,
                           razorpay_details=razorpay_details,
                           related_subscription_payments=related_subscription_payments,
                           related_token_payments=related_token_payments)


@admin_bp.route('/token_payments/update/<string:order_id>', methods=['POST'])
@admin_required
def admin_update_token_payment(order_id):
    """Update token payment status"""
    token_payment = TokenPurchase.query.filter_by(invoice_number=order_id).first_or_404()

    # Validate and update payment status
    new_status = request.form.get('status')
    valid_statuses = ['created', 'completed', 'failed', 'cancelled']

    if new_status in valid_statuses:
        old_status = token_payment.status
        token_payment.status = new_status

        try:
            if new_status == 'completed' and old_status != 'completed':
                # Generate invoice details if not exists
                if not token_payment.invoice_number:
                    token_payment._generate_invoice_details()

                # Create user tokens if they don't exist
                existing_user_token = UserToken.query.filter_by(purchase_id=token_payment.id).first()
                if not existing_user_token:
                    # Get the subscription
                    subscribed_user = SubscribedUser.query.get(token_payment.subscription_id)

                    user_token = UserToken(
                        user_id=token_payment.user_id,
                        subscription_id=token_payment.subscription_id,
                        purchase_id=token_payment.id,
                        tokens_purchased=token_payment.token_count,
                        tokens_used=0,
                        tokens_remaining=token_payment.token_count,
                        expires_at=subscribed_user.end_date
                    )
                    db.session.add(user_token)

            db.session.commit()
            flash('Token payment status updated successfully', 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Token payment update error: {str(e)}")
            flash(f'Error updating token payment: {str(e)}', 'danger')
    else:
        flash('Invalid status', 'danger')

    return redirect(url_for('admin.admin_payment_details', order_id=order_id))


@admin_bp.route('/payments/update/<string:order_id>', methods=['POST'])
@admin_required
def admin_update_payment(order_id):
    payment = Payment.query.filter_by(invoice_number=order_id).first_or_404()

    # Validate and update payment status
    new_status = request.form.get('status')
    valid_statuses = ['created', 'completed', 'failed', 'cancelled']

    if new_status in valid_statuses:
        old_status = payment.status
        payment.status = new_status

        # Additional status change logic
        try:
            if new_status == 'completed' and old_status != 'completed':
                # Ensure invoice is generated
                if not payment.invoice_number:
                    payment.invoice_number = generate_unique_invoice_number()

                # Create or update subscription
                create_or_update_subscription(payment)

                # Generate invoice address if not exists
                create_invoice_address_for_payment(payment)

            db.session.commit()
            flash('Payment status updated successfully', 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Payment update error: {str(e)}")
            flash(f'Error updating payment: {str(e)}', 'danger')
    else:
        flash('Invalid status', 'danger')

    return redirect(url_for('admin.admin_payment_details', order_id=order_id))


@admin_bp.route('/payment/<order_id>/invoice')
@admin_required
def admin_payment_invoice(order_id):
    """Generate and serve a PDF invoice for a specific payment order"""
    from app import generate_invoice_pdf

    # Find the payment by order_id
    payment = Payment.query.filter_by(razorpay_order_id=order_id).first_or_404()

    # Generate PDF invoice
    pdf_buffer = generate_invoice_pdf(payment)

    # Send the PDF as a download
    return send_file(
        pdf_buffer,
        download_name=f"invoice_{payment.invoice_number}.pdf",
        as_attachment=True,
        mimetype='application/pdf'
    )


@admin_bp.route('/token/invoice/<string:invoice_number>')
@admin_required
def admin_token_invoice(invoice_number):
    # Get the token purchase by invoice number
    token_purchase = TokenPurchase.query.filter_by(invoice_number=invoice_number).first_or_404()
    user = User.query.get(token_purchase.user_id)
    subscription = SubscribedUser.query.get(token_purchase.subscription_id)

    # Render the invoice HTML
    rendered_html = render_template('admin/invoice_token.html',
                                    token_purchase=token_purchase,
                                    user=user,
                                    subscription=subscription)

    # Convert HTML to PDF
    import pdfkit
    pdf = pdfkit.from_string(rendered_html, False)

    # Send as downloadable response
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Token-Invoice-{invoice_number}.pdf'
    return response


# ===========================
# Contact Submissions
# ===========================

@admin_bp.route('/contact_submissions')
@admin_required
def admin_contact_submissions():
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'contact_submissions'):
        flash("You don't have permission to access this page.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', 'all')

    query = ContactSubmission.query

    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    submissions = query.order_by(ContactSubmission.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )

    # Calculate stats
    total_count = ContactSubmission.query.count()
    new_count = ContactSubmission.query.filter_by(status='new').count()
    responded_count = ContactSubmission.query.filter_by(status='responded').count()

    # Today's submissions
    today = datetime.now(UTC).date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    today_count = ContactSubmission.query.filter(
        ContactSubmission.created_at.between(today_start, today_end)
    ).count()

    return render_template('admin/contact_submissions.html',
                          submissions=submissions,
                          status_filter=status_filter,
                          total_count=total_count,
                          new_count=new_count,
                          responded_count=responded_count,
                          today_count=today_count)


@admin_bp.route('/contact_submissions/<int:id>/send_reply', methods=['POST'])
@admin_required
def send_reply(id):
    submission = ContactSubmission.query.get_or_404(id)
    subject = request.form.get('subject')
    message_body = request.form.get('message')
    recipient_email = submission.email

    if not subject or not message_body:
        return jsonify(success=False, message="Subject and message are required."), 400

    try:
        msg = Message(subject=subject, sender=current_app.config['MAIL_USERNAME'], recipients=[recipient_email])
        msg.body = message_body
        mail.send(msg)

        submission.status = 'responded'
        db.session.commit()
        return jsonify(success=True, message="Reply email sent successfully.")
    except Exception as e:
        error_detail = traceback.format_exc()
        current_app.logger.error(f"Failed to send reply email: {str(e)}\n{error_detail}")
        return jsonify(success=False, message=f"Failed to send email. Error: {str(e)}"), 500


@admin_bp.route('/contact_submissions/<int:submission_id>')
@admin_required
def admin_contact_submission_detail(submission_id):
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'contact_submissions'):
        flash("You don't have permission to access this page.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    submission = ContactSubmission.query.get_or_404(submission_id)

    # Mark as read if it was new
    if submission.status == 'new':
        submission.status = 'read'
        db.session.commit()

    return render_template('admin/contact_submission_detail.html',
                          submission=submission,
                          admin_email=email_id)


@admin_bp.route('/contact_submissions/<int:submission_id>/update', methods=['POST'])
@admin_required
def update_contact_submission(submission_id):
    try:
        submission = ContactSubmission.query.get_or_404(submission_id)

        new_status = request.form.get('status')
        admin_notes = request.form.get('admin_notes')

        if new_status in ['new', 'read', 'responded', 'spam']:
            submission.status = new_status
            if new_status == 'responded' and not submission.responded_at:
                submission.responded_at = datetime.now(UTC)

        if admin_notes is not None:
            submission.admin_notes = admin_notes

        db.session.commit()

        # Check if it's an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True,
                'message': 'Submission updated successfully',
                'status': submission.status
            })

        flash('Submission updated successfully!', 'success')
        return redirect(url_for('admin.admin_contact_submission_detail', submission_id=submission_id))

    except Exception as e:
        db.session.rollback()
        print(f"Error updating submission: {str(e)}")

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'message': str(e)
            }), 500

        flash(f'Error updating submission: {str(e)}', 'danger')
        return redirect(url_for('admin.admin_contact_submission_detail', submission_id=submission_id))


@admin_bp.route('/contact_submissions/<int:submission_id>/spam', methods=['POST'])
@admin_required
def mark_submission_as_spam(submission_id):
    try:
        submission = ContactSubmission.query.get_or_404(submission_id)
        submission.status = 'spam'
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Submission marked as spam'
        })

    except Exception as e:
        db.session.rollback()
        print(f"Error marking as spam: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@admin_bp.route('/contact_submissions/<int:submission_id>/delete', methods=['POST'])
@admin_required
def delete_contact_submission(submission_id):
    try:
        submission = ContactSubmission.query.get_or_404(submission_id)
        db.session.delete(submission)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Submission deleted successfully'
        })

    except Exception as e:
        db.session.rollback()
        print(f"Error deleting submission: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@admin_bp.route('/export_contact_submissions')
@admin_required
def admin_export_contact_submissions():
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'contact_submissions'):
        flash("You don't have permission to access this feature.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    status_filter = request.args.get('status', 'all')

    query = ContactSubmission.query
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    submissions = query.order_by(ContactSubmission.created_at.desc()).all()

    # Create CSV in memory
    output = StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(['ID', 'Name', 'Email', 'Message', 'Status', 'IP Address', 'Submitted Date', 'Admin Notes'])

    # Write data rows
    for submission in submissions:
        writer.writerow([
            submission.id,
            submission.name,
            submission.email,
            submission.message,
            submission.status,
            submission.ip_address or '',
            submission.created_at.strftime('%Y-%m-%d %I:%M:%S %p') if submission.created_at else '',
            submission.admin_notes or ''
        ])

    # Prepare response
    output.seek(0)
    return send_file(
        BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'contact_submissions_{datetime.now(UTC).strftime("%Y%m%d_%H%M%S")}.csv'
    )


# ===========================
# Email Logs
# ===========================

@admin_bp.route('/email_logs')
@admin_required
def admin_email_logs():
    """Admin page to view all email logs with filtering and search"""
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'email_logs'):
        flash("You don't have permission to access email logs.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    # Get filter parameters
    email_type_filter = request.args.get('email_type', 'all')
    status_filter = request.args.get('status', 'all')
    date_range_filter = request.args.get('date_range', '30')
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 50

    # Build base query
    query = EmailLog.query

    # Apply email type filter
    if email_type_filter != 'all':
        query = query.filter(EmailLog.email_type == email_type_filter)

    # Apply status filter
    if status_filter != 'all':
        query = query.filter(EmailLog.status == status_filter)

    # Apply date range filter
    now = datetime.now(UTC)
    if date_range_filter == '7':
        start_date = now - timedelta(days=7)
        query = query.filter(EmailLog.sent_at >= start_date)
    elif date_range_filter == '30':
        start_date = now - timedelta(days=30)
        query = query.filter(EmailLog.sent_at >= start_date)
    elif date_range_filter == '90':
        start_date = now - timedelta(days=90)
        query = query.filter(EmailLog.sent_at >= start_date)
    elif date_range_filter == '365':
        start_date = now - timedelta(days=365)
        query = query.filter(EmailLog.sent_at >= start_date)

    # Apply search filter
    if search_query:
        search_filter = or_(
            EmailLog.recipient_email.ilike(f'%{search_query}%'),
            EmailLog.recipient_name.ilike(f'%{search_query}%'),
            EmailLog.subject.ilike(f'%{search_query}%')
        )
        query = query.filter(search_filter)

    # Execute query with pagination
    email_logs = query.order_by(EmailLog.sent_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Calculate statistics
    total_emails = EmailLog.query.count()
    sent_emails = EmailLog.query.filter_by(status='sent').count()
    failed_emails = EmailLog.query.filter_by(status='failed').count()

    # Today's emails
    today_start = datetime.combine(now.date(), datetime.min.time())
    today_emails = EmailLog.query.filter(EmailLog.sent_at >= today_start).count()

    # Email type statistics
    email_type_stats = (
        db.session.query(
            EmailLog.email_type,
            func.count(EmailLog.id).label('count'),
            func.sum(case((EmailLog.status == 'sent', 1), else_=0)).label('sent_count'),
            func.sum(case((EmailLog.status == 'failed', 1), else_=0)).label('failed_count')
        )
        .group_by(EmailLog.email_type)
        .order_by(func.count(EmailLog.id).desc())
        .all()
    )

    # Get available email types for filter dropdown
    available_email_types = (
        db.session.query(EmailLog.email_type.distinct().label('email_type'))
        .order_by(EmailLog.email_type)
        .all()
    )

    # Create filter args without 'page' for pagination links
    filter_args = {k: v for k, v in request.args.items() if k != 'page'}

    return render_template('admin/email_logs.html',
                          email_logs=email_logs,
                          email_type_filter=email_type_filter,
                          status_filter=status_filter,
                          date_range_filter=date_range_filter,
                          search_query=search_query,
                          available_email_types=available_email_types,
                          total_emails=total_emails,
                          sent_emails=sent_emails,
                          failed_emails=failed_emails,
                          today_emails=today_emails,
                          email_type_stats=email_type_stats,
                          filter_args=filter_args)


@admin_bp.route('/email_logs/<int:log_id>')
@admin_required
def admin_email_log_detail(log_id):
    """View detailed information about a specific email log"""
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'email_logs'):
        flash("You don't have permission to access email logs.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    email_log = EmailLog.query.get_or_404(log_id)

    # Parse metadata if available
    metadata = None
    if email_log.email_metadata:
        try:
            metadata = json.loads(email_log.email_metadata)
        except:
            metadata = None

    return render_template('admin/email_log_detail.html',
                          email_log=email_log,
                          metadata=metadata)


@admin_bp.route('/email_logs/export')
@admin_required
def admin_export_email_logs():
    """Export email logs to CSV"""
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'email_logs'):
        flash("You don't have permission to export email logs.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    # Get same filters as main page
    email_type_filter = request.args.get('email_type', 'all')
    status_filter = request.args.get('status', 'all')
    date_range_filter = request.args.get('date_range', '30')
    search_query = request.args.get('search', '')

    # Build query with same filters
    query = EmailLog.query

    if email_type_filter != 'all':
        query = query.filter(EmailLog.email_type == email_type_filter)

    if status_filter != 'all':
        query = query.filter(EmailLog.status == status_filter)

    # Apply date range filter
    now = datetime.now(UTC)
    if date_range_filter == '7':
        start_date = now - timedelta(days=7)
        query = query.filter(EmailLog.sent_at >= start_date)
    elif date_range_filter == '30':
        start_date = now - timedelta(days=30)
        query = query.filter(EmailLog.sent_at >= start_date)
    elif date_range_filter == '90':
        start_date = now - timedelta(days=90)
        query = query.filter(EmailLog.sent_at >= start_date)
    elif date_range_filter == '365':
        start_date = now - timedelta(days=365)
        query = query.filter(EmailLog.sent_at >= start_date)

    if search_query:
        search_filter = or_(
            EmailLog.recipient_email.ilike(f'%{search_query}%'),
            EmailLog.recipient_name.ilike(f'%{search_query}%'),
            EmailLog.subject.ilike(f'%{search_query}%')
        )
        query = query.filter(search_filter)

    # Get all matching records
    email_logs = query.order_by(EmailLog.sent_at.desc()).all()

    # Create CSV in memory
    output = StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow([
        'ID', 'Recipient Email', 'Recipient Name', 'Email Type',
        'Subject', 'Status', 'Sent Date', 'Error Message', 'User ID'
    ])

    # Write data rows
    for log in email_logs:
        writer.writerow([
            log.id,
            log.recipient_email,
            log.recipient_name or '',
            log.email_type,
            log.subject,
            log.status,
            log.sent_at.strftime('%Y-%m-%d %H:%M:%S UTC'),
            log.error_message or '',
            log.user_id or ''
        ])

    # Prepare response
    output.seek(0)
    return send_file(
        BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'email_logs_{datetime.now(UTC).strftime("%Y%m%d_%H%M%S")}.csv'
    )


@admin_bp.route('/email_logs/retry/<int:log_id>', methods=['POST'])
@admin_required
def admin_retry_email(log_id):
    """Retry sending a failed email"""
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'email_logs'):
        flash("You don't have permission to retry emails.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    email_log = EmailLog.query.get_or_404(log_id)

    if email_log.status != 'failed':
        flash("Can only retry failed emails.", "warning")
        return redirect(url_for('admin.admin_email_log_detail', log_id=log_id))

    try:
        # Create a simple retry email
        subject = f"[RETRY] {email_log.subject}"

        msg = Message(
            subject,
            sender=current_app.config['MAIL_USERNAME'],
            recipients=[email_log.recipient_email]
        )

        msg.body = f"""Dear {email_log.recipient_name or 'User'},

This is a retry of a previously failed email.

Original Subject: {email_log.subject}
Original Send Date: {email_log.sent_at.strftime('%Y-%m-%d %H:%M:%S UTC')}

If you need assistance, please contact our support team.

Best regards,
The Support Team
"""

        mail.send(msg)

        # Log the retry attempt
        EmailLog.log_email(
            recipient_email=email_log.recipient_email,
            recipient_name=email_log.recipient_name,
            email_type=f"{email_log.email_type}_retry",
            subject=subject,
            user_id=email_log.user_id,
            status='sent',
            metadata={'original_log_id': log_id, 'retry': True}
        )

        flash("Email retry sent successfully.", "success")

    except Exception as e:
        # Log the failed retry
        EmailLog.log_email(
            recipient_email=email_log.recipient_email,
            recipient_name=email_log.recipient_name,
            email_type=f"{email_log.email_type}_retry",
            subject=subject,
            user_id=email_log.user_id,
            status='failed',
            error_message=str(e),
            metadata={'original_log_id': log_id, 'retry': True}
        )

        flash(f"Failed to retry email: {str(e)}", "danger")

    return redirect(url_for('admin.admin_email_log_detail', log_id=log_id))


# ===========================
# Website Settings
# ===========================

@admin_bp.route('/website-settings')
@admin_required
def admin_website_settings():
    """Admin page to manage website settings"""
    email_id = session.get('email_id')

    # Check permission
    if not Admin.check_permission(email_id, 'website_settings'):
        flash("You don't have permission to access website settings.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    # Get all website settings
    settings = WebsiteSettings.query.all()
    settings_dict = {setting.setting_key: setting for setting in settings}

    # Get current values - return exactly what's stored, no defaults
    current_settings = {
        'website_icon': WebsiteSettings.get_setting('website_icon'),
        'website_logo_file': WebsiteSettings.get_setting('website_logo_file')
    }

    # Get list of FontAwesome icons for the dropdown
    fontawesome_icons = [
        {'class': 'fas fa-chart-line', 'name': 'Chart Line'},
        {'class': 'fas fa-analytics', 'name': 'Analytics'},
        {'class': 'fas fa-search', 'name': 'Search'},
        {'class': 'fas fa-globe', 'name': 'Globe'},
        {'class': 'fas fa-chart-bar', 'name': 'Chart Bar'},
        {'class': 'fas fa-chart-pie', 'name': 'Chart Pie'},
        {'class': 'fas fa-chart-area', 'name': 'Chart Area'},
        {'class': 'fas fa-sitemap', 'name': 'Sitemap'},
        {'class': 'fas fa-code', 'name': 'Code'},
        {'class': 'fas fa-desktop', 'name': 'Desktop'},
        {'class': 'fas fa-mobile-alt', 'name': 'Mobile'},
        {'class': 'fas fa-laptop', 'name': 'Laptop'},
        {'class': 'fas fa-cog', 'name': 'Settings'},
        {'class': 'fas fa-tools', 'name': 'Tools'},
        {'class': 'fas fa-wrench', 'name': 'Wrench'},
        {'class': 'fas fa-rocket', 'name': 'Rocket'},
        {'class': 'fas fa-star', 'name': 'Star'},
        {'class': 'fas fa-bolt', 'name': 'Bolt'},
        {'class': 'fas fa-fire', 'name': 'Fire'},
        {'class': 'fas fa-gem', 'name': 'Gem'}
    ]

    return render_template('admin/website_settings.html',
                          current_settings=current_settings,
                          settings_dict=settings_dict,
                          fontawesome_icons=fontawesome_icons)


@admin_bp.route('/website-settings/update', methods=['POST'])
@admin_required
def admin_update_website_settings():
    """Update website settings"""
    email_id = session.get('email_id')
    admin_id = session.get('admin_id')

    # Check permission
    if not Admin.check_permission(email_id, 'website_settings'):
        flash("You don't have permission to update website settings.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    try:
        # Get form data - store exactly what user submits, None if empty
        website_icon = request.form.get('website_icon', '').strip() or None
        use_custom_logo = request.form.get('use_custom_logo') == 'on'

        # Handle logo file upload
        logo_filename = None
        if use_custom_logo and 'logo_file' in request.files:
            file = request.files['logo_file']
            if file and file.filename != '' and allowed_file(file.filename):
                # Secure the filename
                filename = secure_filename(file.filename)
                # Add timestamp to avoid conflicts
                timestamp = str(int(time.time()))
                name, ext = os.path.splitext(filename)
                logo_filename = f"logo_{timestamp}{ext}"

                # Save the file
                file_path = os.path.join(UPLOAD_FOLDER, logo_filename)
                file.save(file_path)

                # Delete old logo file if exists
                old_logo = WebsiteSettings.get_setting('website_logo_file')
                if old_logo:
                    old_file_path = os.path.join(UPLOAD_FOLDER, old_logo)
                    if os.path.exists(old_file_path):
                        try:
                            os.remove(old_file_path)
                        except:
                            pass

        # Update settings in database
        WebsiteSettings.set_setting('website_icon', website_icon, admin_id, 'FontAwesome icon updated' if website_icon else 'Website icon cleared')

        # Update logo file setting
        if use_custom_logo and logo_filename:
            WebsiteSettings.set_setting('website_logo_file', logo_filename, admin_id, 'Custom logo file uploaded', 'file')
        elif not use_custom_logo:
            # Clear custom logo if not using it
            old_logo = WebsiteSettings.get_setting('website_logo_file')
            if old_logo:
                old_file_path = os.path.join(UPLOAD_FOLDER, old_logo)
                if os.path.exists(old_file_path):
                    try:
                        os.remove(old_file_path)
                    except:
                        pass
            WebsiteSettings.set_setting('website_logo_file', None, admin_id, 'Custom logo file cleared', 'file')

        flash('Website settings updated successfully!', 'success')
        current_app.logger.info(f"Website settings updated by admin {email_id}")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating website settings: {str(e)}")
        flash(f'Error updating settings: {str(e)}', 'danger')

    return redirect(url_for('admin.admin_website_settings'))


@admin_bp.route('/website-settings/reset', methods=['POST'])
@admin_required
def admin_reset_website_settings():
    """Reset website settings to empty values"""
    email_id = session.get('email_id')
    admin_id = session.get('admin_id')

    # Check permission
    if not Admin.check_permission(email_id, 'website_settings'):
        flash("You don't have permission to reset website settings.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    try:
        # Delete custom logo file if exists
        old_logo = WebsiteSettings.get_setting('website_logo_file')
        if old_logo:
            old_file_path = os.path.join(UPLOAD_FOLDER, old_logo)
            if os.path.exists(old_file_path):
                try:
                    os.remove(old_file_path)
                except:
                    pass

        # Clear all settings (set to None/empty)
        WebsiteSettings.set_setting('website_icon', None, admin_id, 'Website icon cleared')
        WebsiteSettings.set_setting('website_logo_file', None, admin_id, 'Custom logo file cleared', 'file')

        flash('All website settings have been cleared successfully!', 'success')
        current_app.logger.info(f"Website settings cleared by admin {email_id}")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error clearing website settings: {str(e)}")
        flash(f'Error clearing settings: {str(e)}', 'danger')

    return redirect(url_for('admin.admin_website_settings'))


# ===========================
# Blog Category Routes
# ===========================

@admin_bp.route('/blog_categories')
@admin_required
@csrf_exempt
def admin_blog_categories():
    """List all blog categories"""
    email_id = session.get('email_id')

    # Check permission
    if not Admin.check_permission(email_id, 'blog_categories'):
        flash("You don't have permission to manage blog categories.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    try:
        categories = BlogCategory.query.order_by(BlogCategory.sort_order, BlogCategory.name).all()
        return render_template('admin/blog_categories.html', categories=categories)
    except Exception as e:
        current_app.logger.error(f"Error loading blog categories: {str(e)}")
        flash('Error loading blog categories', 'danger')
        return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/blog_category/add', methods=['GET', 'POST'])
@admin_required
@csrf_exempt
def admin_add_blog_category():
    """Add new blog category"""
    email_id = session.get('email_id')

    # Check permission
    if not Admin.check_permission(email_id, 'blog_categories'):
        flash("You don't have permission to manage blog categories.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    current_app.logger.info(f"admin_add_blog_category called - Method: {request.method}")

    if request.method == 'POST':
        try:
            current_app.logger.info(f"POST request received for add blog category")
            current_app.logger.info(f"Form data: {request.form}")
            current_app.logger.info(f"Admin session: admin_id={session.get('admin_id')}, email={session.get('email_id')}")

            name = request.form.get('name', '').strip()
            sort_order = request.form.get('sort_order', 0)
            status = request.form.get('status') == 'on'

            if not name:
                current_app.logger.warning("Category name is empty")
                flash('Category name is required', 'danger')
                return redirect(url_for('admin.admin_add_blog_category'))

            # Check if category already exists
            existing = BlogCategory.query.filter_by(name=name).first()
            if existing:
                current_app.logger.warning(f"Category '{name}' already exists")
                flash('A category with this name already exists', 'danger')
                return redirect(url_for('admin.admin_add_blog_category'))

            category = BlogCategory(
                name=name,
                sort_order=int(sort_order) if sort_order else 0,
                status=status
            )

            db.session.add(category)
            db.session.commit()

            current_app.logger.info(f"Blog category '{name}' added successfully")
            flash('Blog category added successfully!', 'success')
            return redirect(url_for('admin.admin_blog_categories'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding blog category: {str(e)}")
            current_app.logger.error(f"Traceback: {traceback.format_exc()}")
            flash(f'Error adding category: {str(e)}', 'danger')
            return redirect(url_for('admin.admin_add_blog_category'))

    return render_template('admin/add_blog_category.html')


@admin_bp.route('/blog_category/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
@csrf_exempt
def admin_edit_blog_category(id):
    """Edit blog category"""
    email_id = session.get('email_id')

    # Check permission
    if not Admin.check_permission(email_id, 'blog_categories'):
        flash("You don't have permission to manage blog categories.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    category = BlogCategory.query.get_or_404(id)

    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            sort_order = request.form.get('sort_order', 0)
            status = request.form.get('status') == 'on'

            if not name:
                flash('Category name is required', 'danger')
                return redirect(url_for('admin.admin_edit_blog_category', id=id))

            # Check if another category has this name
            existing = BlogCategory.query.filter(BlogCategory.name == name, BlogCategory.id != id).first()
            if existing:
                flash('A category with this name already exists', 'danger')
                return redirect(url_for('admin.admin_edit_blog_category', id=id))

            category.name = name
            category.sort_order = int(sort_order) if sort_order else 0
            category.status = status
            category.updated_at = datetime.now(UTC)

            db.session.commit()

            flash('Blog category updated successfully!', 'success')
            return redirect(url_for('admin.admin_blog_categories'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating blog category: {str(e)}")
            flash(f'Error updating category: {str(e)}', 'danger')
            return redirect(url_for('admin.admin_edit_blog_category', id=id))

    return render_template('admin/edit_blog_category.html', category=category)


@admin_bp.route('/blog_category/delete/<int:id>', methods=['POST'])
@admin_required
@csrf_exempt
def admin_delete_blog_category(id):
    """Delete blog category"""
    email_id = session.get('email_id')

    # Check permission
    if not Admin.check_permission(email_id, 'blog_categories'):
        flash("You don't have permission to manage blog categories.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    try:
        category = BlogCategory.query.get_or_404(id)

        # Check if category has blogs
        if category.blogs.count() > 0:
            flash('Cannot delete category with existing blogs. Please delete or reassign the blogs first.', 'danger')
            return redirect(url_for('admin.admin_blog_categories'))

        db.session.delete(category)
        db.session.commit()

        flash('Blog category deleted successfully!', 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting blog category: {str(e)}")
        flash(f'Error deleting category: {str(e)}', 'danger')

    return redirect(url_for('admin.admin_blog_categories'))


# ===========================
# Blog Post Routes
# ===========================

@admin_bp.route('/blogs')
@admin_required
@csrf_exempt
def admin_blogs():
    """List all blogs"""
    email_id = session.get('email_id')

    # Check permission
    if not Admin.check_permission(email_id, 'blog_management'):
        flash("You don't have permission to manage blogs.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    try:
        # Get filter parameters
        category_filter = request.args.get('category', '')
        status_filter = request.args.get('status', '')

        query = Blog.query

        if category_filter:
            query = query.filter_by(category_id=int(category_filter))

        if status_filter:
            query = query.filter_by(status=(status_filter == 'active'))

        blogs = query.order_by(Blog.created_at.desc()).all()
        categories = BlogCategory.query.filter_by(status=True).order_by(BlogCategory.name).all()

        return render_template('admin/blogs.html', blogs=blogs, categories=categories)
    except Exception as e:
        current_app.logger.error(f"Error loading blogs: {str(e)}")
        flash('Error loading blogs', 'danger')
        return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/blog/upload-image', methods=['POST'])
@csrf_exempt
def admin_blog_upload_image():
    """Upload image for CKEditor in blog description"""
    try:
        current_app.logger.info("Image upload request received")

        # Check admin authentication manually (for JSON response)
        if 'admin_id' not in session:
            current_app.logger.error("Unauthorized upload attempt - no admin_id in session")
            return jsonify({'error': {'message': 'Unauthorized. Please log in as admin.'}}), 401

        # Check permission
        email_id = session.get('email_id')
        if not Admin.check_permission(email_id, 'blog_management'):
            current_app.logger.error("Unauthorized upload attempt - no blog_management permission")
            return jsonify({'error': {'message': 'You do not have permission to upload blog images.'}}), 403

        if 'upload' not in request.files:
            current_app.logger.error("No 'upload' field in request.files")
            return jsonify({'error': {'message': 'No file uploaded'}}), 400

        file = request.files['upload']

        if not file or not file.filename:
            current_app.logger.error("File object is empty or has no filename")
            return jsonify({'error': {'message': 'No file selected'}}), 400

        # Check file extension
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        filename = secure_filename(file.filename)
        file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

        current_app.logger.info(f"Uploading file: {filename}, extension: {file_ext}")

        if file_ext not in allowed_extensions:
            current_app.logger.error(f"Invalid file extension: {file_ext}")
            return jsonify({'error': {'message': 'Invalid file type. Allowed: PNG, JPG, JPEG, GIF, WEBP'}}), 400

        # Create uploads directory if it doesn't exist
        upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'blogs', 'content')
        os.makedirs(upload_folder, exist_ok=True)

        # Generate unique filename
        unique_filename = f"{uuid.uuid4()}_{filename}"
        file_path = os.path.join(upload_folder, unique_filename)
        file.save(file_path)

        current_app.logger.info(f"File saved to: {file_path}")

        # Return the URL for CKEditor
        from flask import url_for as flask_url_for
        file_url = flask_url_for('static', filename=f'uploads/blogs/content/{unique_filename}', _external=True)

        current_app.logger.info(f"File URL: {file_url}")

        return jsonify({
            'uploaded': 1,
            'fileName': unique_filename,
            'url': file_url
        })

    except Exception as e:
        current_app.logger.error(f"Error uploading image: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': {'message': str(e)}}), 500


@admin_bp.route('/blog/add', methods=['GET', 'POST'])
@admin_required
@csrf_exempt
def admin_add_blog():
    """Add new blog"""
    email_id = session.get('email_id')

    # Check permission
    if not Admin.check_permission(email_id, 'blog_management'):
        flash("You don't have permission to manage blogs.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    if request.method == 'POST':
        try:
            title = request.form.get('title', '').strip()
            slug = request.form.get('slug', '').strip()
            author_name = request.form.get('author_name', '').strip()
            description = request.form.get('description', '').strip()
            meta_title = request.form.get('meta_title', '').strip()
            meta_keyword = request.form.get('meta_keyword', '').strip()
            meta_description = request.form.get('meta_description', '').strip()
            category_id = request.form.get('category_id')
            status = request.form.get('status') == 'on'
            publish_date_str = request.form.get('publish_date', '').strip()

            # Parse publish_date
            publish_date = None
            if publish_date_str:
                try:
                    publish_date = datetime.strptime(publish_date_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

            # Process FAQ data
            faq_questions = request.form.getlist('faq_questions[]')
            faq_answers = request.form.getlist('faq_answers[]')

            faqs = []
            for q, a in zip(faq_questions, faq_answers):
                if q.strip() and a.strip():
                    faqs.append({
                        'question': q.strip(),
                        'answer': a.strip()
                    })

            schema_data = json.dumps(faqs) if faqs else None

            if not title:
                flash('Blog title is required', 'danger')
                return redirect(url_for('admin.admin_add_blog'))

            if not slug:
                flash('Blog slug is required', 'danger')
                return redirect(url_for('admin.admin_add_blog'))

            # Check if slug already exists
            existing_blog = Blog.query.filter_by(slug=slug).first()
            if existing_blog:
                flash('A blog with this slug already exists. Please use a different slug.', 'danger')
                return redirect(url_for('admin.admin_add_blog'))

            # Handle image upload
            image_filename = None
            if 'image' in request.files:
                file = request.files['image']
                if file and file.filename:
                    # Create uploads directory if it doesn't exist
                    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'blogs')
                    os.makedirs(upload_folder, exist_ok=True)

                    # Generate unique filename
                    filename = secure_filename(file.filename)
                    unique_filename = f"{uuid.uuid4()}_{filename}"
                    file_path = os.path.join(upload_folder, unique_filename)
                    file.save(file_path)
                    image_filename = unique_filename

            blog = Blog(
                title=title,
                slug=slug,
                description=description,
                meta_title=meta_title,
                meta_keyword=meta_keyword,
                meta_description=meta_description,
                category_id=int(category_id) if category_id else None,
                image=image_filename,
                status=status,
                schema_data=schema_data,
                publish_date=publish_date,
                created_by=email_id,
                author_name=author_name
            )

            db.session.add(blog)
            db.session.commit()

            flash('Blog added successfully!', 'success')
            return redirect(url_for('admin.admin_blogs'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding blog: {str(e)}")
            flash(f'Error adding blog: {str(e)}', 'danger')

    # GET request
    categories = BlogCategory.query.filter_by(status=True).order_by(BlogCategory.name).all()
    return render_template('admin/add_blog.html', categories=categories)


@admin_bp.route('/blog/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
@csrf_exempt
def admin_edit_blog(id):
    """Edit blog"""
    email_id = session.get('email_id')

    # Check permission
    if not Admin.check_permission(email_id, 'blog_management'):
        flash("You don't have permission to manage blogs.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    blog = Blog.query.get_or_404(id)

    if request.method == 'POST':
        try:
            title = request.form.get('title', '').strip()
            slug = request.form.get('slug', '').strip()
            author_name = request.form.get('author_name', '').strip()
            description = request.form.get('description', '').strip()
            meta_title = request.form.get('meta_title', '').strip()
            meta_keyword = request.form.get('meta_keyword', '').strip()
            meta_description = request.form.get('meta_description', '').strip()
            category_id = request.form.get('category_id')
            status = request.form.get('status') == 'on'
            publish_date_str = request.form.get('publish_date', '').strip()

            # Parse publish_date
            publish_date = None
            if publish_date_str:
                try:
                    publish_date = datetime.strptime(publish_date_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

            # Process FAQ data
            faq_questions = request.form.getlist('faq_questions[]')
            faq_answers = request.form.getlist('faq_answers[]')

            faqs = []
            for q, a in zip(faq_questions, faq_answers):
                if q.strip() and a.strip():
                    faqs.append({
                        'question': q.strip(),
                        'answer': a.strip()
                    })

            schema_data = json.dumps(faqs) if faqs else None

            if not title:
                flash('Blog title is required', 'danger')
                return redirect(url_for('admin.admin_edit_blog', id=id))

            if not slug:
                flash('Blog slug is required', 'danger')
                return redirect(url_for('admin.admin_edit_blog', id=id))

            # Check if slug already exists (excluding current blog)
            existing_blog = Blog.query.filter(Blog.slug == slug, Blog.id != id).first()
            if existing_blog:
                flash('A blog with this slug already exists. Please use a different slug.', 'danger')
                return redirect(url_for('admin.admin_edit_blog', id=id))

            # Handle image upload
            if 'image' in request.files:
                file = request.files['image']
                if file and file.filename:
                    # Delete old image if exists
                    if blog.image:
                        old_image_path = os.path.join(current_app.root_path, 'static', 'uploads', 'blogs', blog.image)
                        if os.path.exists(old_image_path):
                            try:
                                os.remove(old_image_path)
                            except:
                                pass

                    # Save new image
                    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'blogs')
                    os.makedirs(upload_folder, exist_ok=True)

                    filename = secure_filename(file.filename)
                    unique_filename = f"{uuid.uuid4()}_{filename}"
                    file_path = os.path.join(upload_folder, unique_filename)
                    file.save(file_path)
                    blog.image = unique_filename

            blog.title = title
            blog.slug = slug
            blog.author_name = author_name
            blog.description = description
            blog.meta_title = meta_title
            blog.meta_keyword = meta_keyword
            blog.meta_description = meta_description
            blog.category_id = int(category_id) if category_id else None
            blog.status = status
            blog.schema_data = schema_data
            blog.publish_date = publish_date
            blog.updated_at = datetime.now(UTC)

            db.session.commit()

            flash('Blog updated successfully!', 'success')
            return redirect(url_for('admin.admin_blogs'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating blog: {str(e)}")
            flash(f'Error updating blog: {str(e)}', 'danger')
            return redirect(url_for('admin.admin_edit_blog', id=id))

    # GET request
    categories = BlogCategory.query.filter_by(status=True).order_by(BlogCategory.name).all()
    return render_template('admin/edit_blog.html', blog=blog, categories=categories)


@admin_bp.route('/blog/delete/<int:id>', methods=['POST'])
@admin_required
@csrf_exempt
def admin_delete_blog(id):
    """Delete blog"""
    email_id = session.get('email_id')

    # Check permission
    if not Admin.check_permission(email_id, 'blog_management'):
        flash("You don't have permission to manage blogs.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    try:
        blog = Blog.query.get_or_404(id)

        # Delete associated image
        if blog.image:
            image_path = os.path.join(current_app.root_path, 'static', 'uploads', 'blogs', blog.image)
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except:
                    pass

        db.session.delete(blog)
        db.session.commit()

        flash('Blog deleted successfully!', 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting blog: {str(e)}")
        flash(f'Error deleting blog: {str(e)}', 'danger')

    return redirect(url_for('admin.admin_blogs'))


# ===========================
# WebStory Routes
# ===========================

@admin_bp.route('/webstories', methods=['GET'])
@admin_required
@csrf_exempt
def admin_webstories():
    """List all webstories with filtering"""
    email_id = session.get('email_id')

    # Check permission
    if not Admin.check_permission(email_id, 'webstory_management'):
        flash("You don't have permission to access webstories.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    # Get filter parameters
    status_filter = request.args.get('status', '')

    # Build query
    query = WebStory.query

    # Apply status filter
    if status_filter == 'active':
        query = query.filter_by(status=True)
    elif status_filter == 'inactive':
        query = query.filter_by(status=False)

    # Get all webstories ordered by newest first
    webstories = query.order_by(WebStory.created_at.desc()).all()

    return render_template('admin/webstories.html', webstories=webstories)


@admin_bp.route('/webstory/upload-image', methods=['POST'])
@admin_required
@csrf_exempt
def admin_webstory_upload_image():
    """Handle image uploads for webstory slides"""
    try:
        if 'upload' not in request.files:
            return jsonify({
                'uploaded': False,
                'error': {'message': 'No file uploaded'}
            })

        file = request.files['upload']

        if file.filename == '':
            return jsonify({
                'uploaded': False,
                'error': {'message': 'No file selected'}
            })

        # Check file size (max 3MB)
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)

        max_size = 3 * 1024 * 1024
        if file_size > max_size:
            return jsonify({
                'uploaded': False,
                'error': {'message': 'File size exceeds 3MB limit. Please compress or resize the image.'}
            })

        if file and allowed_file(file.filename):
            # Generate unique filename
            filename = str(uuid.uuid4()) + '_' + secure_filename(file.filename)

            # Create upload directory if it doesn't exist
            upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'webstories', 'slides')
            os.makedirs(upload_dir, exist_ok=True)

            # Save file
            filepath = os.path.join(upload_dir, filename)
            file.save(filepath)

            # Return URL for the uploaded image
            url = url_for('static', filename=f'uploads/webstories/slides/{filename}', _external=False)

            return jsonify({
                'uploaded': True,
                'url': url
            })
        else:
            return jsonify({
                'uploaded': False,
                'error': {'message': 'Invalid file type'}
            })

    except Exception as e:
        current_app.logger.error(f"Error uploading webstory image: {str(e)}")
        return jsonify({
            'uploaded': False,
            'error': {'message': str(e)}
        })


@admin_bp.route('/webstory/check-slug', methods=['POST'])
@admin_required
def admin_webstory_check_slug():
    """Check if a slug is available"""
    try:
        data = request.get_json()
        slug = data.get('slug', '').strip()
        webstory_id = data.get('webstory_id')

        if not slug:
            return jsonify({'available': False, 'message': 'Slug cannot be empty'})

        # Check if slug exists
        existing = WebStory.query.filter_by(slug=slug).first()

        # If we're editing, ignore the current webstory
        if existing:
            if webstory_id and existing.id == int(webstory_id):
                return jsonify({'available': True, 'message': 'Current slug'})
            else:
                # Suggest alternative slug
                counter = 1
                suggested_slug = slug
                while WebStory.query.filter_by(slug=suggested_slug).first():
                    suggested_slug = f"{slug}-{counter}"
                    counter += 1
                return jsonify({
                    'available': False,
                    'message': f'Slug already exists',
                    'suggestion': suggested_slug
                })

        return jsonify({'available': True, 'message': 'Slug is available'})

    except Exception as e:
        current_app.logger.error(f"Error checking slug: {str(e)}")
        return jsonify({'available': False, 'message': 'Error checking slug'}), 500


@admin_bp.route('/webstory/add', methods=['GET', 'POST'])
@admin_required
@csrf_exempt
def admin_add_webstory():
    """Add new webstory"""
    email_id = session.get('email_id')

    # Check permission
    if not Admin.check_permission(email_id, 'webstory_management'):
        flash("You don't have permission to add webstories.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    if request.method == 'POST':
        try:
            # Get form data
            meta_title = request.form.get('meta_title', '').strip()
            meta_description = request.form.get('meta_description', '').strip()
            slug = request.form.get('slug', '').strip()
            publish_date_str = request.form.get('publish_date', '')
            status = bool(request.form.get('status'))

            # Validate required fields
            if not meta_title:
                flash('Meta title is required.', 'danger')
                today = datetime.now(UTC).strftime('%Y-%m-%d')
                return render_template('admin/add_webstory.html', today=today)

            if not slug:
                flash('Slug is required.', 'danger')
                today = datetime.now(UTC).strftime('%Y-%m-%d')
                return render_template('admin/add_webstory.html', today=today)

            # Check if slug already exists and auto-increment if needed
            original_slug = slug
            counter = 1
            while WebStory.query.filter_by(slug=slug).first() is not None:
                slug = f"{original_slug}-{counter}"
                counter += 1

            # If slug was modified, notify the user
            if slug != original_slug:
                flash(f'Slug "{original_slug}" already exists. Using "{slug}" instead.', 'warning')

            # Parse publish date
            publish_date = datetime.strptime(publish_date_str, '%Y-%m-%d').date() if publish_date_str else datetime.now(UTC).date()

            # Handle cover image upload
            cover_image = None
            if 'cover_image' in request.files:
                file = request.files['cover_image']
                if file and file.filename != '' and allowed_file(file.filename):
                    filename = str(uuid.uuid4()) + '_' + secure_filename(file.filename)
                    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'webstories')
                    os.makedirs(upload_dir, exist_ok=True)
                    file.save(os.path.join(upload_dir, filename))
                    cover_image = filename

            # Process slides from form
            slides = []
            slide_count = int(request.form.get('slide_count', 0))

            for i in range(slide_count):
                image = request.form.get(f'slide_{i}_image', '').strip()
                image_alt = request.form.get(f'slide_{i}_image_alt', '').strip()
                content_spacing_top = request.form.get(f'slide_{i}_content_spacing_top', '75').strip()
                heading = request.form.get(f'slide_{i}_heading', '').strip()
                text = request.form.get(f'slide_{i}_text', '').strip()
                learn_more_url = request.form.get(f'slide_{i}_learn_more_url', '').strip()
                sort_order = request.form.get(f'slide_{i}_sort_order', str(i)).strip()
                slide_status = request.form.get(f'slide_{i}_status', 'on') == 'on'

                # Get position data for draggable elements
                heading_left = request.form.get(f'slide_{i}_heading_left', '').strip()
                heading_bottom = request.form.get(f'slide_{i}_heading_bottom', '').strip()
                text_left = request.form.get(f'slide_{i}_text_left', '').strip()
                text_bottom = request.form.get(f'slide_{i}_text_bottom', '').strip()

                # Get image zoom and pan values
                zoom = request.form.get(f'slide_{i}_zoom', '100').strip()
                pan_x = request.form.get(f'slide_{i}_pan_x', '50').strip()
                pan_y = request.form.get(f'slide_{i}_pan_y', '50').strip()

                # Get font settings
                heading_font = request.form.get(f'slide_{i}_heading_font', 'inherit').strip()
                heading_size = request.form.get(f'slide_{i}_heading_size', '18').strip()
                text_font = request.form.get(f'slide_{i}_text_font', 'inherit').strip()
                text_size = request.form.get(f'slide_{i}_text_size', '14').strip()

                if image:
                    slide_data = {
                        'image': image,
                        'image_alt': image_alt,
                        'content_spacing_top': content_spacing_top,
                        'heading': heading,
                        'text': text,
                        'learn_more_url': learn_more_url,
                        'sort_order': int(sort_order),
                        'status': slide_status,
                        'zoom': int(zoom) if zoom else 100,
                        'pan_x': int(pan_x) if pan_x else 50,
                        'pan_y': int(pan_y) if pan_y else 50,
                        'heading_font': heading_font if heading_font else 'inherit',
                        'heading_size': int(heading_size) if heading_size else 18,
                        'text_font': text_font if text_font else 'inherit',
                        'text_size': int(text_size) if text_size else 14
                    }

                    if heading_left:
                        slide_data['heading_left'] = heading_left
                    if heading_bottom:
                        slide_data['heading_bottom'] = heading_bottom
                    if text_left:
                        slide_data['text_left'] = text_left
                    if text_bottom:
                        slide_data['text_bottom'] = text_bottom

                    slides.append(slide_data)

            # Create new webstory
            new_webstory = WebStory(
                meta_title=meta_title,
                meta_description=meta_description,
                slug=slug,
                cover_image=cover_image,
                publish_date=publish_date,
                status=status,
                slides=slides,
                created_by=email_id
            )

            db.session.add(new_webstory)
            db.session.commit()

            flash('Webstory created successfully!', 'success')
            return redirect(url_for('admin.admin_webstories'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating webstory: {str(e)}")
            flash(f'Error creating webstory: {str(e)}', 'danger')
            today = datetime.now(UTC).strftime('%Y-%m-%d')
            return render_template('admin/add_webstory.html', today=today)

    # Pass current date to template
    today = datetime.now(UTC).strftime('%Y-%m-%d')
    return render_template('admin/add_webstory.html', today=today)


@admin_bp.route('/webstory/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
@csrf_exempt
def admin_edit_webstory(id):
    """Edit existing webstory"""
    email_id = session.get('email_id')

    # Check permission
    if not Admin.check_permission(email_id, 'webstory_management'):
        flash("You don't have permission to edit webstories.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    webstory = WebStory.query.get_or_404(id)

    if request.method == 'POST':
        try:
            # Get form data
            meta_title = request.form.get('meta_title', '').strip()
            meta_description = request.form.get('meta_description', '').strip()
            new_slug = request.form.get('slug', '').strip()
            publish_date_str = request.form.get('publish_date', '')
            status = bool(request.form.get('status'))

            # Validate required fields
            if not meta_title:
                flash('Meta title is required.', 'danger')
                return render_template('admin/edit_webstory.html', webstory=webstory)

            if not new_slug:
                flash('Slug is required.', 'danger')
                return render_template('admin/edit_webstory.html', webstory=webstory)

            # Check if slug already exists (excluding current webstory)
            if new_slug != webstory.slug:
                existing_webstory = WebStory.query.filter_by(slug=new_slug).first()
                if existing_webstory and existing_webstory.id != webstory.id:
                    flash(f'Slug "{new_slug}" is already in use by another webstory. Please choose a different slug.', 'danger')
                    return render_template('admin/edit_webstory.html', webstory=webstory)

            # Update webstory fields
            webstory.meta_title = meta_title
            webstory.meta_description = meta_description
            webstory.slug = new_slug
            webstory.publish_date = datetime.strptime(publish_date_str, '%Y-%m-%d').date() if publish_date_str else datetime.now(UTC).date()
            webstory.status = status

            # Handle cover image upload
            if 'cover_image' in request.files:
                file = request.files['cover_image']
                if file and file.filename != '' and allowed_file(file.filename):
                    # Delete old image if exists
                    if webstory.cover_image:
                        old_image_path = os.path.join(current_app.root_path, 'static', 'uploads', 'webstories', webstory.cover_image)
                        if os.path.exists(old_image_path):
                            try:
                                os.remove(old_image_path)
                            except:
                                pass

                    # Save new image
                    filename = str(uuid.uuid4()) + '_' + secure_filename(file.filename)
                    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'webstories')
                    os.makedirs(upload_dir, exist_ok=True)
                    file.save(os.path.join(upload_dir, filename))
                    webstory.cover_image = filename

            # Process slides from form
            slides = []
            slide_count = int(request.form.get('slide_count', 0))

            for i in range(slide_count):
                image = request.form.get(f'slide_{i}_image', '').strip()
                image_alt = request.form.get(f'slide_{i}_image_alt', '').strip()
                content_spacing_top = request.form.get(f'slide_{i}_content_spacing_top', '75').strip()
                heading = request.form.get(f'slide_{i}_heading', '').strip()
                text = request.form.get(f'slide_{i}_text', '').strip()
                learn_more_url = request.form.get(f'slide_{i}_learn_more_url', '').strip()
                sort_order = request.form.get(f'slide_{i}_sort_order', str(i)).strip()
                slide_status = request.form.get(f'slide_{i}_status', 'on') == 'on'

                # Get position data for draggable elements
                heading_left = request.form.get(f'slide_{i}_heading_left', '').strip()
                heading_bottom = request.form.get(f'slide_{i}_heading_bottom', '').strip()
                text_left = request.form.get(f'slide_{i}_text_left', '').strip()
                text_bottom = request.form.get(f'slide_{i}_text_bottom', '').strip()

                # Get image zoom and pan values
                zoom = request.form.get(f'slide_{i}_zoom', '100').strip()
                pan_x = request.form.get(f'slide_{i}_pan_x', '50').strip()
                pan_y = request.form.get(f'slide_{i}_pan_y', '50').strip()

                # Get font settings
                heading_font = request.form.get(f'slide_{i}_heading_font', 'inherit').strip()
                heading_size = request.form.get(f'slide_{i}_heading_size', '18').strip()
                text_font = request.form.get(f'slide_{i}_text_font', 'inherit').strip()
                text_size = request.form.get(f'slide_{i}_text_size', '14').strip()

                if image:
                    slide_data = {
                        'image': image,
                        'image_alt': image_alt,
                        'content_spacing_top': content_spacing_top,
                        'heading': heading,
                        'text': text,
                        'learn_more_url': learn_more_url,
                        'sort_order': int(sort_order),
                        'status': slide_status,
                        'zoom': int(zoom) if zoom else 100,
                        'pan_x': int(pan_x) if pan_x else 50,
                        'pan_y': int(pan_y) if pan_y else 50,
                        'heading_font': heading_font if heading_font else 'inherit',
                        'heading_size': int(heading_size) if heading_size else 18,
                        'text_font': text_font if text_font else 'inherit',
                        'text_size': int(text_size) if text_size else 14
                    }

                    if heading_left:
                        slide_data['heading_left'] = heading_left
                    if heading_bottom:
                        slide_data['heading_bottom'] = heading_bottom
                    if text_left:
                        slide_data['text_left'] = text_left
                    if text_bottom:
                        slide_data['text_bottom'] = text_bottom

                    slides.append(slide_data)

            webstory.slides = slides
            webstory.updated_at = datetime.now(UTC)

            db.session.commit()

            flash('Webstory updated successfully!', 'success')
            return redirect(url_for('admin.admin_webstories'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating webstory: {str(e)}")
            flash(f'Error updating webstory: {str(e)}', 'danger')

    return render_template('admin/edit_webstory.html', webstory=webstory)


@admin_bp.route('/webstory/delete/<int:id>', methods=['POST'])
@admin_required
@csrf_exempt
def admin_delete_webstory(id):
    """Delete webstory"""
    email_id = session.get('email_id')

    # Check permission
    if not Admin.check_permission(email_id, 'webstory_management'):
        flash("You don't have permission to delete webstories.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    try:
        webstory = WebStory.query.get_or_404(id)

        # Delete cover image if exists
        if webstory.cover_image:
            image_path = os.path.join(current_app.root_path, 'static', 'uploads', 'webstories', webstory.cover_image)
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except:
                    pass

        # Delete slide images if exist
        if webstory.slides:
            for slide in webstory.slides:
                if slide.get('image'):
                    slide_image = slide['image']
                    if slide_image.startswith('/static/'):
                        slide_image = slide_image.replace('/static/uploads/webstories/slides/', '')

                    slide_image_path = os.path.join(current_app.root_path, 'static', 'uploads', 'webstories', 'slides', slide_image)
                    if os.path.exists(slide_image_path):
                        try:
                            os.remove(slide_image_path)
                        except:
                            pass

        db.session.delete(webstory)
        db.session.commit()

        flash('Webstory deleted successfully!', 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting webstory: {str(e)}")
        flash(f'Error deleting webstory: {str(e)}', 'danger')

    return redirect(url_for('admin.admin_webstories'))


# =============================================
# ADMIN REFUND MANAGEMENT
# =============================================

@admin_bp.route('/payments/refund/<int:payment_id>', methods=['GET', 'POST'])
@admin_required
def admin_refund_payment(payment_id):
    """Admin route to process a refund for a payment."""
    email_id = session.get('email_id')

    if not Admin.check_permission(email_id, 'payments'):
        flash("You don't have permission to process refunds.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    payment = db.session.get(Payment, payment_id)
    if not payment:
        flash('Payment not found.', 'danger')
        return redirect(url_for('admin.admin_payments'))

    user = db.session.get(User, payment.user_id)
    subscription = db.session.get(Subscription, payment.subscription_id)

    if request.method == 'POST':
        refund_type = request.form.get('refund_type', 'full')
        reason = request.form.get('reason', 'Admin refund')
        partial_amount = request.form.get('partial_amount')

        from services.refund import admin_refund_payment as process_refund

        if refund_type == 'partial' and partial_amount:
            try:
                partial_amount = float(partial_amount)
            except ValueError:
                flash('Invalid refund amount.', 'danger')
                return redirect(url_for('admin.admin_refund_payment', payment_id=payment_id))

            result = process_refund(
                payment_id=payment.iid,
                admin_id=session.get('admin_id'),
                reason=reason,
                partial_amount=partial_amount
            )
        else:
            result = process_refund(
                payment_id=payment.iid,
                admin_id=session.get('admin_id'),
                reason=reason
            )

        if result['success']:
            flash(result['message'], 'success')
        else:
            flash(result['message'], 'danger')

        return redirect(url_for('admin.admin_payment_details', order_id=payment.razorpay_order_id))

    # GET - show refund form
    return render_template(
        'admin/refund_payment.html',
        payment=payment,
        user=user,
        subscription=subscription
    )


@admin_bp.route('/payments/recover/<int:payment_id>', methods=['POST'])
@admin_required
def admin_recover_payment(payment_id):
    """Admin route to recover a stuck payment by checking Razorpay directly."""
    email_id = session.get('email_id')
    if not Admin.check_permission(email_id, 'payments'):
        flash("You don't have permission.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    payment = db.session.get(Payment, payment_id)
    if not payment:
        flash('Payment not found.', 'danger')
        return redirect(url_for('admin.admin_payments'))

    if payment.status == 'completed':
        flash('Payment already completed.', 'info')
        return redirect(url_for('admin.admin_payments'))

    try:
        from extensions import razorpay_client
        order_details = razorpay_client.order.fetch(payment.razorpay_order_id)

        if order_details.get('status') != 'paid':
            flash(f"Order status is '{order_details.get('status')}'. No payment captured by Razorpay.", 'warning')
            return redirect(url_for('admin.admin_payment_details', order_id=payment.razorpay_order_id))

        # Find the captured payment
        payments_list = razorpay_client.order.payments(payment.razorpay_order_id)
        captured = None
        for rp in payments_list.get('items', []):
            if rp.get('status') in ('captured', 'authorized'):
                captured = rp
                break

        if not captured:
            flash('No captured payment found on Razorpay.', 'warning')
            return redirect(url_for('admin.admin_payment_details', order_id=payment.razorpay_order_id))

        # Process the payment
        from datetime import timedelta
        payment.razorpay_payment_id = captured['id']
        payment.status = 'completed'
        payment.notes = (payment.notes or '') + f"\nRecovered by admin {email_id} at {datetime.now(UTC).isoformat()}"

        subscription = db.session.get(Subscription, payment.subscription_id)
        if subscription:
            start_date = datetime.now(UTC)
            end_date = start_date + timedelta(days=subscription.days)
            new_sub = SubscribedUser(
                U_ID=payment.user_id, S_ID=subscription.S_ID,
                start_date=start_date, end_date=end_date,
                is_auto_renew=True, current_usage=0,
                last_usage_reset=start_date, _is_active=True
            )
            db.session.add(new_sub)
            history = SubscriptionHistory(
                U_ID=payment.user_id, S_ID=subscription.S_ID,
                action='new', created_at=datetime.now(UTC)
            )
            db.session.add(history)

        db.session.commit()
        flash(f"Payment recovered! Subscription activated for user {payment.user_id}.", 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin payment recovery error: {str(e)}")
        flash(f'Recovery failed: {str(e)}', 'danger')

    return redirect(url_for('admin.admin_payments'))
