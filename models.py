from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import decimal
import json
import uuid
import logging

import pytz
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer as Serializer
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import JSON

from extensions import db

UTC = timezone.utc


# ----------------------
# User Model
# ----------------------
class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    company_email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    email_confirmed = db.Column(db.Boolean, default=False)
    email_confirm_token = db.Column(db.String(100), nullable=True)
    email_token_created_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
    trial_tokens = db.Column(db.Integer, default=5, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    profile_updated_at = db.Column(db.DateTime, nullable=True)
    password_changed_at = db.Column(db.DateTime, nullable=True)

    def __init__(self, **kwargs):
        if 'company_email' in kwargs:
            kwargs['company_email'] = kwargs['company_email'].lower().strip()
        super(User, self).__init__(**kwargs)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        self.password_changed_at = datetime.now(UTC)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def update_last_login(self):
        self.last_login_at = datetime.now(UTC)
        db.session.commit()

    def update_profile_timestamp(self):
        self.profile_updated_at = datetime.now(UTC)

    def get_last_login_display(self):
        if not self.last_login_at:
            return "Never"
        return self._format_relative_time(self.last_login_at)

    def get_profile_updated_display(self):
        if not self.profile_updated_at:
            return "Never"
        return self._format_relative_time(self.profile_updated_at)

    def get_password_changed_display(self):
        if not self.password_changed_at:
            return "Never"
        return self._format_relative_time(self.password_changed_at)

    def _format_relative_time(self, timestamp):
        if not timestamp:
            return "Never"

        now = datetime.now(UTC)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        diff = now - timestamp
        if diff.total_seconds() < 0:
            return "Just now"

        total_seconds = int(diff.total_seconds())
        days = diff.days

        if days == 0:
            hours = total_seconds // 3600
            if hours == 0:
                minutes = total_seconds // 60
                if minutes == 0:
                    return "Just now"
                elif minutes == 1:
                    return "1 minute ago"
                else:
                    return f"{minutes} minutes ago"
            elif hours == 1:
                return "1 hour ago"
            else:
                return f"{hours} hours ago"
        elif days == 1:
            return "Yesterday"
        elif days < 7:
            return f"{days} days ago"
        elif days < 30:
            weeks = days // 7
            return "1 week ago" if weeks == 1 else f"{weeks} weeks ago"
        elif days < 365:
            months = days // 30
            return "1 month ago" if months == 1 else f"{months} months ago"
        else:
            years = days // 365
            return "1 year ago" if years == 1 else f"{years} years ago"

    def get_reset_token(self, expires_sec=1800):
        s = Serializer(current_app.secret_key)
        return s.dumps({'user_id': self.id})

    def get_email_confirm_token(self):
        s = Serializer(current_app.secret_key)
        token = s.dumps({'user_id': self.id})
        self.email_confirm_token = token
        self.email_token_created_at = datetime.now(UTC)
        return token

    @staticmethod
    def verify_email_token(token):
        s = Serializer(current_app.secret_key)
        try:
            user_id = s.loads(token, max_age=86400)['user_id']
        except Exception:
            return None
        return db.session.get(User, user_id)

    @staticmethod
    def verify_reset_token(token):
        s = Serializer(current_app.secret_key)
        try:
            user_id = s.loads(token, max_age=1800)['user_id']
        except Exception:
            return None
        return db.session.get(User, user_id)


# ----------------------
# Subscription Model
# ----------------------
class Subscription(db.Model):
    __tablename__ = 'subscriptions'

    S_ID = db.Column(db.Integer, primary_key=True)
    plan = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    days = db.Column(db.Integer, nullable=False)
    usage_per_day = db.Column(db.Integer, nullable=False)
    tier = db.Column(db.Integer, nullable=False)
    features = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    archived_at = db.Column(db.DateTime, nullable=True)

    subscribed_users = relationship("SubscribedUser", back_populates="subscription", overlaps="subscribers")

    def __repr__(self):
        return f"<Subscription {self.plan}>"

    @property
    def daily_price(self):
        return self.price / self.days if self.days > 0 else 0


# ----------------------
# SubscribedUser Model
# ----------------------
class SubscribedUser(db.Model):
    __tablename__ = 'subscribed_users'

    id = db.Column(db.Integer, primary_key=True)
    U_ID = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    S_ID = db.Column(db.Integer, db.ForeignKey('subscriptions.S_ID'), nullable=False)
    start_date = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
    end_date = db.Column(db.DateTime, nullable=False)
    current_usage = db.Column(db.Integer, default=0)
    last_usage_reset = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
    is_auto_renew = db.Column(db.Boolean, default=True)
    _is_active = db.Column('is_active', db.Boolean, default=True, nullable=False)
    custom_usage_limit = db.Column(db.Integer, nullable=True)

    user = db.relationship('User', backref=db.backref('subscriptions', lazy=True))
    subscription = db.relationship('Subscription', backref=db.backref('subscribers', lazy=True))

    def remaining_value(self):
        now = datetime.now(UTC)
        start_date = self.start_date.replace(tzinfo=UTC) if self.start_date.tzinfo is None else self.start_date
        end_date = self.end_date.replace(tzinfo=UTC) if self.end_date.tzinfo is None else self.end_date

        if end_date <= now:
            return 0

        total_days = (end_date - start_date).total_seconds() / (24 * 3600)
        remaining_days = (end_date - now).total_seconds() / (24 * 3600)
        subscription = db.session.get(Subscription, self.S_ID)
        daily_rate = subscription.price / total_days if total_days > 0 else 0
        return daily_rate * remaining_days

    def get_total_usage_limit(self):
        base_limit = self.subscription.usage_per_day if self.subscription else 0
        custom_limit = self.custom_usage_limit if self.custom_usage_limit else 0
        return base_limit + custom_limit

    @property
    def daily_usage_percent(self):
        total_limit = self.get_total_usage_limit()
        if not total_limit:
            return 0
        return min(100, (self.current_usage / total_limit) * 100)

    @property
    def is_active(self):
        now = datetime.now(UTC)
        end_date = self.end_date
        if end_date and end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=UTC)
        return self._is_active and end_date > now

    @is_active.setter
    def is_active(self, value):
        self._is_active = value

    @property
    def days_remaining(self):
        now = datetime.now(UTC)
        end_date = self.end_date.replace(tzinfo=UTC) if self.end_date.tzinfo is None else self.end_date
        if end_date <= now:
            return 0
        remaining_seconds = (end_date - now).total_seconds()
        return max(0, int(remaining_seconds / (24 * 3600)))


# ----------------------
# InvoiceAddress Model
# ----------------------
class InvoiceAddress(db.Model):
    __tablename__ = 'invoice_addresses'

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.iid'), nullable=False)
    company_name = db.Column(db.String(255), nullable=True)
    full_name = db.Column(db.String(255), nullable=False)
    street_address = db.Column(db.String(255), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(100), nullable=False)
    postal_code = db.Column(db.String(20), nullable=False)
    country = db.Column(db.String(100), default='India')
    email = db.Column(db.String(255), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    gst_number = db.Column(db.String(20), nullable=True)
    pan_number = db.Column(db.String(20), nullable=True)

    payment = relationship("Payment", back_populates="invoice_address")


# ----------------------
# Payment Model
# ----------------------
class Payment(db.Model):
    __tablename__ = 'payments'

    iid = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscriptions.S_ID', ondelete='SET NULL'), nullable=False)
    razorpay_order_id = db.Column(db.String(100), nullable=False)
    razorpay_payment_id = db.Column(db.String(100), nullable=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    invoice_date = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
    order_number = db.Column(db.String(50), nullable=True)
    customer_number = db.Column(db.String(50), nullable=True)
    purchase_order = db.Column(db.String(50), nullable=True)
    payment_terms = db.Column(db.String(100), default='Credit Card')
    base_amount = db.Column(db.Float, nullable=False)
    gst_rate = db.Column(db.Float, default=0.18)
    gst_amount = db.Column(db.Float, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    hsn_code = db.Column(db.String(20), nullable=True)
    cin_number = db.Column(db.String(50), nullable=True)
    currency = db.Column(db.String(10), default='INR')
    status = db.Column(db.String(20), default='created')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
    payment_type = db.Column(db.String(20), default='new')
    previous_subscription_id = db.Column(db.Integer, db.ForeignKey('subscriptions.S_ID'), nullable=True)
    credit_applied = db.Column(db.Float, default=0.0)
    notes = db.Column(db.Text, nullable=True)

    user = relationship("User", backref="payments")
    subscription = relationship("Subscription", foreign_keys=[subscription_id], backref="payments")
    previous_subscription = relationship("Subscription", foreign_keys=[previous_subscription_id])
    invoice_address = relationship("InvoiceAddress", back_populates="payment", uselist=False)

    def __init__(self, *args, **kwargs):
        base_amount = kwargs.pop('base_amount', 0)
        gst_rate = kwargs.pop('gst_rate', 0.18)

        try:
            base_amount = float(base_amount)
            if base_amount < 0:
                raise ValueError("Base amount must be non-negative")
        except (TypeError, ValueError):
            raise ValueError("Invalid base amount provided")

        super().__init__(*args, **kwargs)
        self.base_amount = base_amount
        self.gst_rate = gst_rate
        self._generate_invoice_details()
        self._calculate_total_amount()

    def _generate_invoice_details(self):
        timestamp = datetime.now(UTC).strftime("%Y%m%d")
        unique_id = str(uuid.uuid4().hex)[:6].upper()
        self.invoice_number = f"INV-{timestamp}-{unique_id}"
        self.invoice_date = datetime.now(UTC)

    def _calculate_total_amount(self):
        try:
            base = Decimal(str(self.base_amount)).quantize(Decimal('0.01'))
            gst_rate = Decimal(str(self.gst_rate)).quantize(Decimal('0.01'))
            gst_amount = (base * gst_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            total_amount = (base + gst_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            self.gst_amount = float(gst_amount)
            self.total_amount = float(total_amount)
        except (TypeError, ValueError, decimal.InvalidOperation) as e:
            logging.error(f"Error in amount calculation: {e}")
            self.gst_amount = 0
            self.total_amount = self.base_amount

    def get_invoice_summary(self):
        return {
            'invoice_number': self.invoice_number,
            'invoice_date': self.invoice_date,
            'order_number': self.order_number,
            'customer_number': self.customer_number,
            'base_amount': self.base_amount,
            'gst_rate': self.gst_rate * 100,
            'gst_amount': self.gst_amount,
            'total_amount': self.total_amount,
            'currency': self.currency,
            'status': self.status
        }

    def __repr__(self):
        return f"<Payment {self.invoice_number} - {self.total_amount}>"


# ----------------------
# SubscriptionHistory Model
# ----------------------
class SubscriptionHistory(db.Model):
    __tablename__ = 'subscription_history'

    id = db.Column(db.Integer, primary_key=True)
    U_ID = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    S_ID = db.Column(db.Integer, db.ForeignKey('subscriptions.S_ID'), nullable=False)
    action = db.Column(db.String(20), nullable=False)
    previous_S_ID = db.Column(db.Integer, db.ForeignKey('subscriptions.S_ID'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))

    user = relationship("User", backref="subscription_history")
    subscription = relationship("Subscription", foreign_keys=[S_ID])
    previous_subscription = relationship("Subscription", foreign_keys=[previous_S_ID])

    def __repr__(self):
        return f"<SubscriptionHistory {self.action} for user {self.U_ID}>"


# ----------------------
# SearchHistory Model
# ----------------------
class SearchHistory(db.Model):
    __tablename__ = 'search_history'

    id = db.Column(db.Integer, primary_key=True)
    u_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user_name = db.Column(db.String(100), nullable=False)
    usage_tool = db.Column(db.String(100), nullable=False)
    search_history = db.Column(db.String(255), nullable=False)
    search_count = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))

    user = db.relationship('User', backref='search_histories')

    @property
    def ist_time(self):
        if self.created_at:
            if self.created_at.tzinfo is None:
                return pytz.timezone('UTC').localize(self.created_at).astimezone(pytz.timezone('Asia/Kolkata'))
            return self.created_at.astimezone(pytz.timezone('Asia/Kolkata'))
        return None

    def __repr__(self):
        return f"<SearchHistory id={self.id}, u_id={self.u_id}, usage_tool='{self.usage_tool}'>"


# ----------------------
# TokenPurchase Model
# ----------------------
class TokenPurchase(db.Model):
    __tablename__ = 'token_purchases'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscribed_users.id'), nullable=False)
    token_count = db.Column(db.Integer, nullable=False)
    base_amount = db.Column(db.Float, nullable=False)
    gst_amount = db.Column(db.Float, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    razorpay_order_id = db.Column(db.String(100), nullable=False)
    razorpay_payment_id = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), default='created')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
    invoice_number = db.Column(db.String(50), unique=True, nullable=True)
    invoice_date = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref='token_purchases')
    subscription = db.relationship('SubscribedUser', backref='token_purchases')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.status == 'completed' and not self.invoice_number:
            self._generate_invoice_details()

    def _generate_invoice_details(self):
        timestamp = datetime.now(UTC).strftime("%Y%m%d")
        unique_id = str(uuid.uuid4().hex)[:6].upper()
        self.invoice_number = f"TKN-{timestamp}-{unique_id}"
        self.invoice_date = datetime.now(UTC)

    def __repr__(self):
        return f"<TokenPurchase {self.id}: {self.token_count} tokens>"


# ----------------------
# UserToken Model
# ----------------------
class UserToken(db.Model):
    __tablename__ = 'user_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscribed_users.id'), nullable=False)
    purchase_id = db.Column(db.Integer, db.ForeignKey('token_purchases.id'), nullable=False)
    tokens_purchased = db.Column(db.Integer, nullable=False)
    tokens_used = db.Column(db.Integer, default=0)
    tokens_remaining = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
    expires_at = db.Column(db.DateTime, nullable=False)
    is_paused = db.Column(db.Boolean, default=False)
    paused_at = db.Column(db.DateTime, nullable=True)
    original_subscription_id = db.Column(db.Integer, nullable=True)

    user = db.relationship('User', backref='user_tokens')
    subscription = db.relationship('SubscribedUser', backref='user_tokens')
    purchase = db.relationship('TokenPurchase', backref='user_tokens')

    def pause_tokens(self):
        if self.tokens_remaining > 0 and not self.is_paused:
            self.is_paused = True
            self.paused_at = datetime.now(UTC)
            if not self.original_subscription_id:
                self.original_subscription_id = self.subscription_id

    def reactivate_tokens(self, new_subscription_id):
        if self.is_paused and self.tokens_remaining > 0:
            self.is_paused = False
            self.subscription_id = new_subscription_id
            new_subscription = db.session.get(SubscribedUser, new_subscription_id)
            if new_subscription:
                self.expires_at = new_subscription.end_date

    def __repr__(self):
        status = "PAUSED" if self.is_paused else "ACTIVE"
        return f"<UserToken {self.id}: {self.tokens_remaining}/{self.tokens_purchased} - {status}>"


# ----------------------
# UsageLog Model
# ----------------------
class UsageLog(db.Model):
    __tablename__ = 'usage_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscribed_users.id'), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
    operation_type = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text, nullable=True)
    is_trial = db.Column(db.Boolean, default=False)

    user = db.relationship('User', backref=db.backref('usage_logs', lazy=True))
    subscription = db.relationship('SubscribedUser', backref=db.backref('usage_logs', lazy=True))

    def __repr__(self):
        return f"<UsageLog id={self.id}, user_id={self.user_id}, operation={self.operation_type}>"


# ----------------------
# Admin Model
# ----------------------
class Admin(db.Model):
    __tablename__ = 'admin'

    id = db.Column(db.Integer, primary_key=True)
    email_id = db.Column(db.String(120), nullable=False, unique=True)
    NAME = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    phone_number = db.Column(db.String(15), nullable=True)
    assigned_by = db.Column(db.String(50), nullable=False)
    permission = db.Column(db.ARRAY(db.String(50)))
    password_hash = db.Column(db.String(256), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
    updated_at = db.Column(db.DateTime, onupdate=lambda: datetime.now(UTC))
    is_active = db.Column(db.Boolean, default=True)

    def set_password(self, password):
        if password and password.strip():
            try:
                self.password_hash = generate_password_hash(password)
                return True
            except Exception as e:
                logging.error(f"Password hashing error: {str(e)}")
                return False
        return False

    def check_password(self, password):
        if not self.password_hash or not password:
            return False
        try:
            return check_password_hash(self.password_hash, password)
        except Exception as e:
            logging.error(f"Password check error: {str(e)}")
            return False

    def admin_permissions(self, required_permission):
        if not self.permission:
            return False

        if isinstance(self.permission, str):
            try:
                permissions_list = json.loads(self.permission)
                return required_permission in permissions_list
            except Exception:
                return False
        elif isinstance(self.permission, list):
            return required_permission in self.permission
        return False

    @staticmethod
    def check_permission(email_id, required_permission):
        admin = Admin.query.filter_by(email_id=email_id).first()
        if not admin:
            return False
        return admin.admin_permissions(required_permission)

    def __repr__(self):
        return f"<Admin {self.NAME} - {self.role}>"


# ----------------------
# EmailLog Model
# ----------------------
class EmailLog(db.Model):
    __tablename__ = 'email_logs'

    id = db.Column(db.Integer, primary_key=True)
    recipient_email = db.Column(db.String(255), nullable=False, index=True)
    recipient_name = db.Column(db.String(100), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    email_type = db.Column(db.String(50), nullable=False, index=True)
    subject = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default='sent', nullable=False)
    email_metadata = db.Column(db.Text, nullable=True)
    sent_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)

    user = db.relationship('User', backref='email_logs')

    def __repr__(self):
        return f"<EmailLog {self.email_type} to {self.recipient_email}>"

    @property
    def formatted_sent_time(self):
        if self.sent_at:
            if self.sent_at.tzinfo is None:
                return pytz.UTC.localize(self.sent_at).astimezone(
                    pytz.timezone('Asia/Kolkata')
                ).strftime('%d %b %Y, %H:%M %p IST')
            return self.sent_at.astimezone(
                pytz.timezone('Asia/Kolkata')
            ).strftime('%d %b %Y, %H:%M %p IST')
        return 'N/A'

    @staticmethod
    def log_email(recipient_email, recipient_name, email_type, subject, user_id=None,
                  status='sent', metadata=None, error_message=None):
        try:
            from flask import request
            ip_address = None
            user_agent = None
            try:
                ip_address = request.remote_addr
                user_agent = request.headers.get('User-Agent', '')
            except RuntimeError:
                pass

            metadata_json = json.dumps(metadata) if metadata else None

            email_log = EmailLog(
                recipient_email=recipient_email,
                recipient_name=recipient_name,
                user_id=user_id,
                email_type=email_type,
                subject=subject,
                status=status,
                email_metadata=metadata_json,
                error_message=error_message,
                ip_address=ip_address,
                user_agent=user_agent,
                sent_at=datetime.now(UTC)
            )
            db.session.add(email_log)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Failed to log email: {str(e)}")
            return False


# ----------------------
# ContactSubmission Model
# ----------------------
class ContactSubmission(db.Model):
    __tablename__ = 'contact_submissions'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(20), default='new')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
    responded_at = db.Column(db.DateTime, nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<ContactSubmission {self.name} - {self.email}>"


# ----------------------
# WebsiteSettings Model
# ----------------------
class WebsiteSettings(db.Model):
    __tablename__ = 'website_settings'

    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False)
    setting_value = db.Column(db.Text, nullable=True)
    setting_type = db.Column(db.String(50), default='text')
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    updated_by = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)

    updated_by_admin = db.relationship('Admin', backref='settings_updates')

    def __repr__(self):
        return f"<WebsiteSettings {self.setting_key}={self.setting_value}>"

    @staticmethod
    def get_setting(key, default=None):
        try:
            setting = WebsiteSettings.query.filter_by(setting_key=key).first()
            if setting and setting.setting_value is not None and setting.setting_value.strip():
                return setting.setting_value
            return default
        except Exception as e:
            logging.error(f"Error getting setting {key}: {str(e)}")
            return default

    @staticmethod
    def set_setting(key, value, admin_id=None, description=None, setting_type='text'):
        setting = WebsiteSettings.query.filter_by(setting_key=key).first()
        if setting:
            setting.setting_value = value
            setting.updated_at = datetime.now(UTC)
            setting.updated_by = admin_id
            if description:
                setting.description = description
        else:
            setting = WebsiteSettings(
                setting_key=key,
                setting_value=value,
                setting_type=setting_type,
                description=description,
                updated_by=admin_id
            )
            db.session.add(setting)
        db.session.commit()
        return setting


# ----------------------
# Blog System Models
# ----------------------
class BlogCategory(db.Model):
    __tablename__ = 'blog_categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    status = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    blogs = db.relationship('Blog', backref='category', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<BlogCategory {self.name}>"


class Blog(db.Model):
    __tablename__ = 'blogs'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    author_name = db.Column(db.String(255), nullable=True)
    meta_title = db.Column(db.String(255), nullable=True)
    meta_keyword = db.Column(db.Text, nullable=True)
    meta_description = db.Column(db.Text, nullable=True)
    image = db.Column(db.String(255), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('blog_categories.id'), nullable=True)
    status = db.Column(db.Boolean, default=True)
    schema_data = db.Column(db.Text, nullable=True)
    publish_date = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    def __repr__(self):
        return f"<Blog {self.title}>"


class WebStory(db.Model):
    __tablename__ = 'webstories'

    id = db.Column(db.Integer, primary_key=True)
    meta_title = db.Column(db.String(255), nullable=False)
    meta_description = db.Column(db.Text, nullable=True)
    slug = db.Column(db.String(255), unique=True, nullable=False)
    cover_image = db.Column(db.String(255), nullable=True)
    publish_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.Boolean, default=True)
    slides = db.Column(db.JSON, nullable=True)
    created_by = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    def __repr__(self):
        return f"<WebStory {self.meta_title}>"
