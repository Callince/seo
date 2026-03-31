import re
import logging
from datetime import datetime, timedelta, timezone

import pytz
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_user, logout_user, current_user
from sqlalchemy import func

from extensions import db
from models import User, SearchHistory, SubscribedUser, Subscription, Payment

UTC = timezone.utc

auth_bp = Blueprint('auth', __name__)


def login_required(f):
    """Custom login_required decorator using session."""
    from functools import wraps

    @wraps(f)
    def wrap(*args, **kwargs):
        if 'user_id' not in session:
            flash("You need to log in first.", "warning")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrap


# ----------------------
# Auth Routes
# ----------------------

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('seo_tools.index'))

    if request.method == 'POST':
        company_email = request.form.get('companyEmail', '').lower().strip()
        password = request.form.get('password', '')

        user = User.query.filter(func.lower(User.company_email) == company_email).first()

        if not user:
            flash("Invalid email or password.", "danger")
            return render_template('login.html', email_value=company_email)

        if not user.email_confirmed:
            flash("Please verify your email before logging in.", "warning")
            return redirect(url_for('auth.resend_verification'))

        if user.check_password(password):
            login_user(user)
            user.update_last_login()
            session['user_id'] = user.id
            session['user_name'] = user.name
            flash("Login successful!", "success")
            return redirect(url_for('seo_tools.index'))
        else:
            flash("Invalid email or password.", "danger")
            return render_template('login.html', email_value=company_email)

    return render_template('login.html', email_value='')


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('seo_tools.index'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        company_email = request.form.get('companyEmail', '').lower().strip()
        password = request.form.get('password', '')
        retype_password = request.form.get('retypePassword', '')

        errors = []

        # Name validation
        if not name:
            errors.append("Name is required.")
        elif len(name) < 2:
            errors.append("Name should be at least 2 characters long.")
        elif len(name) > 100:
            errors.append("Name should not exceed 100 characters.")

        # Email validation
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not company_email:
            errors.append("Email is required.")
        elif not re.match(email_pattern, company_email):
            errors.append("Please enter a valid email address.")
        elif len(company_email) > 255:
            errors.append("Email address is too long.")

        # Password validation
        if not password:
            errors.append("Password is required.")
        elif len(password) < 8:
            errors.append("Password must be at least 8 characters long.")
        elif len(password) > 128:
            errors.append("Password should not exceed 128 characters.")
        else:
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

        if password and retype_password and password != retype_password:
            errors.append("Passwords do not match.")
        elif not retype_password:
            errors.append("Please confirm your password.")

        # Check existing email
        if company_email and re.match(email_pattern, company_email):
            try:
                existing_user = User.query.filter(func.lower(User.company_email) == company_email).first()
                if existing_user:
                    if existing_user.email_confirmed:
                        errors.append("This email is already registered and verified.")
                    else:
                        errors.append("This email is already registered but not verified.")
            except Exception as e:
                logging.error(f"Database error during email check: {str(e)}")
                errors.append("A system error occurred. Please try again.")

        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template('signup.html', name=name, company_email=company_email)

        try:
            new_user = User(name=name, company_email=company_email, email_confirmed=False, trial_tokens=5)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()

            try:
                from services.email import send_verification_email
                send_verification_email(new_user)
                flash("Signup successful! Please check your email to verify your account.", "success")
            except Exception as e:
                logging.error(f"Error sending verification email: {str(e)}")
                flash("Signup successful but there was an issue sending the verification email.", "warning")

            return redirect(url_for('auth.verify_account', email=company_email))

        except Exception as e:
            db.session.rollback()
            logging.error(f"Database error during user creation: {str(e)}")
            flash("A system error occurred during registration.", "danger")
            return render_template('signup.html', name=name, company_email=company_email)

    return render_template('signup.html')


@auth_bp.route('/check_email', methods=['POST'])
def check_email():
    try:
        if request.is_json:
            data = request.get_json()
            email = data.get('email', '').lower().strip()
        else:
            email = request.form.get('email', '').lower().strip()

        if not email:
            return jsonify({'available': True, 'message': ''})

        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return jsonify({'available': False, 'message': 'Please enter a valid email address.'})

        existing_user = User.query.filter(func.lower(User.company_email) == email).first()

        if existing_user:
            return jsonify({
                'available': False,
                'message': 'This email is already registered. Please use a different email or <a href="/login">login here</a>.'
            })
        return jsonify({'available': True, 'message': 'Email is available.'})

    except Exception as e:
        logging.error(f"Error checking email: {str(e)}")
        return jsonify({'available': False, 'message': 'Unable to verify email availability.'}), 500


@auth_bp.route("/verify_account")
def verify_account():
    email = request.args.get('email')
    return render_template('verify_account.html', email=email)


@auth_bp.route('/verify_email/<token>')
def verify_email(token):
    try:
        user = User.verify_email_token(token)
        if user is None:
            flash('The verification link is invalid or has expired.', 'danger')
            return redirect(url_for('auth.resend_verification'))

        if user.email_confirmed:
            flash('Your email has already been verified.', 'info')
            return redirect(url_for('auth.login'))

        user.email_confirmed = True
        user.email_confirm_token = None
        user.email_token_created_at = None
        db.session.commit()

        flash('Your email has been verified successfully!', 'success')
        return redirect(url_for('auth.login'))

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error verifying email: {str(e)}")
        flash('An error occurred while verifying your email.', 'danger')
        return redirect(url_for('auth.signup'))


@auth_bp.route('/resend_verification', methods=['GET', 'POST'])
def resend_verification():
    if request.method == 'POST':
        email = request.form.get('companyEmail', '').lower().strip()

        if not email:
            flash('Please enter your email address.', 'warning')
            return render_template('resend_verification.html')

        user = User.query.filter(func.lower(User.company_email) == email).first()

        if user and not user.email_confirmed:
            try:
                from services.email import send_verification_email
                send_verification_email(user)
                flash('A new verification email has been sent.', 'success')
                return redirect(url_for('auth.verify_account', email=email))
            except Exception as e:
                logging.error(f"Error resending verification email: {str(e)}")
                flash('There was an issue sending the verification email.', 'danger')
        elif user and user.email_confirmed:
            flash('This email is already verified.', 'info')
            return redirect(url_for('auth.login'))
        else:
            flash('Email not found. Please sign up first.', 'warning')
            return redirect(url_for('auth.signup'))

    return render_template('resend_verification.html')


@auth_bp.route('/reset_password', methods=['GET', 'POST'])
def reset_request():
    if request.method == 'POST':
        email = request.form.get('companyEmail', '').lower().strip()

        if not email:
            flash('Please enter your email address.', 'warning')
            return render_template('reset_request.html')

        user = User.query.filter(func.lower(User.company_email) == email).first()

        if user:
            try:
                from services.email import send_reset_email
                send_reset_email(user)
                flash('An email has been sent with instructions to reset your password.', 'info')
                return redirect(url_for('auth.login'))
            except Exception as e:
                logging.error(f"Error sending reset email: {str(e)}")
                flash('There was an issue sending the reset email.', 'danger')
                return render_template('reset_request.html')
        else:
            flash('Email not found. Please register first.', 'warning')
            return render_template('reset_request.html')

    return render_template('reset_request.html')


@auth_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_token(token):
    try:
        user = User.verify_reset_token(token)
        if not user:
            flash('Invalid or expired token.', 'danger')
            return redirect(url_for('auth.reset_request'))

        if request.method == 'POST':
            password = request.form.get('password')
            confirm_password = request.form.get('confirm_password')

            if not password or not confirm_password:
                flash('Both password fields are required.', 'danger')
                return render_template('reset_token.html', token=token)

            if password != confirm_password:
                flash('Passwords do not match.', 'danger')
                return render_template('reset_token.html', token=token)

            if len(password) < 8:
                flash('Password must be at least 8 characters long.', 'danger')
                return render_template('reset_token.html', token=token)

            user.set_password(password)
            db.session.commit()

            flash('Your password has been updated!', 'success')
            return redirect(url_for('auth.login'))

    except Exception as e:
        logging.error(f"Error during password reset: {str(e)}")
        flash('An error occurred during password reset.', 'danger')
        return redirect(url_for('auth.reset_request'))

    return render_template('reset_token.html', token=token)


@auth_bp.route('/logout')
def logout():
    logout_user()
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for('auth.login'))


# ----------------------
# Profile Routes
# ----------------------

@auth_bp.route('/search_history', methods=['GET'])
@login_required
def search_history():
    user_id = session.get('user_id')
    user = db.session.get(User, user_id)
    user_name = user.name if user else "Guest"

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    query = SearchHistory.query.filter_by(u_id=user_id)

    try:
        if start_date:
            start_obj = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(SearchHistory.created_at >= start_obj)
        if end_date:
            end_obj = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(SearchHistory.created_at < end_obj)
    except ValueError:
        flash("Invalid date format.", "danger")

    history = query.order_by(SearchHistory.created_at.desc()).all()

    user_most_used_tools = {}
    if history:
        tool_usage = (
            db.session.query(SearchHistory.usage_tool, db.func.sum(SearchHistory.search_count))
            .filter(SearchHistory.u_id == user_id)
            .group_by(SearchHistory.usage_tool)
            .all()
        )
        if tool_usage:
            most_used_tool = max(tool_usage, key=lambda x: x[1])[0]
            user_most_used_tools[user_id] = most_used_tool
        else:
            user_most_used_tools[user_id] = "No tools used yet"

    for entry in history:
        if entry.created_at:
            if entry.created_at.tzinfo is None:
                entry.formatted_date = pytz.UTC.localize(entry.created_at).strftime('%d-%m-%Y %I:%M:%S %p UTC')
            else:
                entry.formatted_date = entry.created_at.astimezone(pytz.UTC).strftime('%d-%m-%Y %I:%M:%S %p UTC')
        else:
            entry.formatted_date = 'N/A'

    return render_template(
        'search_history.html',
        history=history,
        user_name=user_name,
        user_most_used_tools=user_most_used_tools,
        start_date=start_date,
        end_date=end_date
    )


@auth_bp.route('/profile')
@login_required
def profile():
    user_id = session.get('user_id')
    user = db.session.get(User, user_id)
    now = datetime.now()

    active_subscription = None
    subscriptions = (
        db.session.query(SubscribedUser, Subscription)
        .join(Subscription, SubscribedUser.S_ID == Subscription.S_ID)
        .filter(SubscribedUser.U_ID == user_id)
        .filter(SubscribedUser.end_date > now)
        .filter(SubscribedUser._is_active == True)
        .filter(Subscription.archived_at.is_(None))
        .order_by(SubscribedUser.start_date.desc())
        .all()
    )

    if len(subscriptions) > 1:
        active_subscription = subscriptions[0]
        for sub, plan in subscriptions[1:]:
            sub.is_active = False
        db.session.commit()
    elif len(subscriptions) == 1:
        active_subscription = subscriptions[0]

    payments = (
        Payment.query
        .filter_by(user_id=user_id)
        .order_by(Payment.created_at.desc())
        .limit(10)
        .all()
    )

    recent_activity = {
        'last_login': user.get_last_login_display(),
        'profile_updated': user.get_profile_updated_display(),
        'password_changed': user.get_password_changed_display()
    }

    return render_template(
        'profile.html',
        user=user,
        active_subscription=active_subscription,
        payments=payments,
        recent_activity=recent_activity,
        now=now
    )


@auth_bp.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    user_id = session.get('user_id')
    user = db.session.get(User, user_id)
    update_type = request.form.get('update_type')

    if update_type == 'account':
        new_name = request.form.get('name', '').strip()
        if new_name and len(new_name) >= 2:
            user.name = new_name
            user.update_profile_timestamp()
            db.session.commit()
            flash('Profile updated successfully!', 'success')
        else:
            flash('Name must be at least 2 characters long.', 'danger')

    elif update_type == 'security':
        current_password = request.form.get('currentPassword')
        new_password = request.form.get('newPassword')
        confirm_password = request.form.get('confirmPassword')

        if not current_password:
            flash('Current password is required.', 'danger')
        elif not user.check_password(current_password):
            flash('Current password is incorrect.', 'danger')
        elif not new_password or len(new_password) < 8:
            flash('New password must be at least 8 characters long.', 'danger')
        elif new_password != confirm_password:
            flash('New passwords do not match.', 'danger')
        elif current_password == new_password:
            flash('New password must be different from current password.', 'danger')
        else:
            if not (re.search(r'[A-Z]', new_password) and
                    re.search(r'[a-z]', new_password) and
                    re.search(r'[0-9]', new_password) and
                    re.search(r'[!@#$%^&*(),.?":{}|<>]', new_password)):
                flash('Password must contain uppercase, lowercase, number and special character.', 'danger')
            else:
                user.set_password(new_password)
                db.session.commit()
                flash('Password updated successfully!', 'success')

    return redirect(url_for('auth.profile'))


@auth_bp.route('/verify_current_password', methods=['POST'])
@login_required
def verify_current_password():
    user_id = session.get('user_id')
    user = db.session.get(User, user_id)
    current_password = request.json.get('currentPassword', '')

    if not current_password:
        return jsonify({'valid': False, 'message': 'Password is required'})

    is_valid = user.check_password(current_password)
    if is_valid:
        return jsonify({'valid': True, 'message': 'Password is correct'})
    return jsonify({'valid': False, 'message': 'Current password is incorrect'})
