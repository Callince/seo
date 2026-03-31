import os
from datetime import datetime, timedelta, timezone
from functools import wraps
import logging
import re

from flask import current_app, session, flash, redirect, url_for, jsonify, request
from flask_login import current_user
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError

from extensions import db, razorpay_client
from models import (User, Subscription, SubscribedUser, SubscriptionHistory,
                    UserToken, UsageLog, TokenPurchase, Payment, SearchHistory)

UTC = timezone.utc


def has_active_subscription(user_id):
    """
    Strict check to ensure at least one active subscription exists.
    - Must be active
    - End date in the future
    """
    now = datetime.now(UTC)
    active_subs = (
        SubscribedUser.query
        .filter(SubscribedUser.U_ID == user_id)
        .filter(SubscribedUser.end_date > now)
        .filter(SubscribedUser._is_active == True)
        .count()
    )
    return active_subs > 0


def increment_usage_with_tokens(user_id, tokens_needed=1):
    """
    Enhanced usage increment that handles both daily quota and additional tokens.
    Returns detailed information about what was used.
    """
    try:
        # Get active subscription
        sub = (
            SubscribedUser.query
            .filter(SubscribedUser.U_ID == user_id)
            .filter(SubscribedUser.end_date > datetime.now(UTC))
            .filter(SubscribedUser._is_active == True)
            .first()
        )

        if not sub:
            # Check if user has trial tokens available (only for non-subscribed users)
            user = db.session.get(User, user_id)
            if user and user.trial_tokens >= tokens_needed:
                # Use trial tokens
                user.trial_tokens -= tokens_needed
                db.session.commit()
                current_app.logger.info(
                    f"User {user_id}: Used {tokens_needed} trial token(s). "
                    f"Remaining: {user.trial_tokens}"
                )
                return {
                    'success': True,
                    'usage_breakdown': f'Used {tokens_needed} trial token(s)',
                    'tokens_from_daily': 0,
                    'additional_tokens_used': 0,
                    'trial_tokens_used': tokens_needed,
                    'trial_tokens_remaining': user.trial_tokens,
                    'is_trial': True
                }
            elif user and user.trial_tokens > 0:
                # Not enough trial tokens
                return {
                    'success': False,
                    'reason': 'insufficient_trial_tokens',
                    'usage_breakdown': (
                        f'Need {tokens_needed} tokens but only '
                        f'{user.trial_tokens} trial tokens remaining'
                    ),
                    'trial_tokens_remaining': user.trial_tokens
                }
            else:
                return {
                    'success': False,
                    'reason': 'no_active_subscription',
                    'usage_breakdown': 'No active subscription and no trial tokens available'
                }

        # Check if we need to reset the usage counter (new day)
        today = datetime.now(UTC).date()
        last_reset_date = getattr(sub, 'last_usage_reset', None)

        if not last_reset_date or last_reset_date.date() < today:
            # Reset counter for new day
            sub.current_usage = 0
            sub.last_usage_reset = datetime.now(UTC)
            current_app.logger.info(f"Daily usage reset for user {user_id}")

        daily_limit = sub.get_total_usage_limit()
        current_usage = sub.current_usage

        # Calculate how much we can use from daily quota
        daily_quota_available = max(0, daily_limit - current_usage)
        tokens_from_daily = min(tokens_needed, daily_quota_available)
        additional_tokens_needed = tokens_needed - tokens_from_daily

        current_app.logger.info(
            f"User {user_id}: Need {tokens_needed}, Daily available: "
            f"{daily_quota_available}, Additional needed: {additional_tokens_needed}"
        )

        # If we need additional tokens, check if they're available
        additional_tokens_used = 0
        if additional_tokens_needed > 0:
            # Get available additional tokens - only check expiration, not subscription match
            available_token_records = (
                UserToken.query
                .filter(UserToken.user_id == user_id)
                .filter(UserToken.tokens_remaining > 0)
                .filter(UserToken.expires_at > datetime.now(UTC))
                .order_by(UserToken.created_at.asc())  # Use oldest first
                .all()
            )

            total_additional_available = sum(
                record.tokens_remaining for record in available_token_records
            )
            current_app.logger.info(
                f"User {user_id}: Available additional tokens: {total_additional_available}"
            )

            if total_additional_available < additional_tokens_needed:
                return {
                    'success': False,
                    'reason': 'no_tokens',
                    'usage_breakdown': (
                        f'Need {additional_tokens_needed} additional tokens, '
                        f'but only {total_additional_available} available'
                    ),
                    'daily_used': current_usage,
                    'daily_limit': daily_limit,
                    'additional_available': total_additional_available
                }

            # Use additional tokens
            tokens_to_use = additional_tokens_needed
            for token_record in available_token_records:
                if tokens_to_use <= 0:
                    break

                tokens_from_this_record = min(tokens_to_use, token_record.tokens_remaining)
                token_record.tokens_used += tokens_from_this_record
                token_record.tokens_remaining -= tokens_from_this_record
                tokens_to_use -= tokens_from_this_record
                additional_tokens_used += tokens_from_this_record

                current_app.logger.info(
                    f"Used {tokens_from_this_record} tokens from purchase "
                    f"{token_record.purchase_id}"
                )

        # Update daily usage
        sub.current_usage += tokens_from_daily

        # Commit all changes
        db.session.commit()

        # Prepare usage breakdown message
        usage_parts = []
        if tokens_from_daily > 0:
            usage_parts.append(f"{tokens_from_daily} from daily quota")
        if additional_tokens_used > 0:
            usage_parts.append(f"{additional_tokens_used} additional tokens")

        usage_breakdown = f"Used {' + '.join(usage_parts)} (Total: {tokens_needed})"

        current_app.logger.info(f"User {user_id}: {usage_breakdown}")

        return {
            'success': True,
            'usage_breakdown': usage_breakdown,
            'tokens_from_daily': tokens_from_daily,
            'additional_tokens_used': additional_tokens_used,
            'new_daily_usage': sub.current_usage,
            'daily_limit': daily_limit
        }

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in increment_usage_with_tokens: {str(e)}")
        return {
            'success': False,
            'reason': 'system_error',
            'usage_breakdown': f'System error: {str(e)}'
        }


def pause_expired_subscription_tokens(subscription_id):
    """
    Pause tokens when a subscription expires.
    Called when a subscription ends.
    """
    try:
        # Get all active tokens for this subscription
        active_tokens = (
            UserToken.query
            .filter(UserToken.subscription_id == subscription_id)
            .filter(UserToken.tokens_remaining > 0)
            .filter(UserToken.is_paused == False)
            .all()
        )

        paused_count = 0
        for token in active_tokens:
            token.pause_tokens()
            paused_count += 1

        if paused_count > 0:
            db.session.commit()
            current_app.logger.info(
                f"Paused {paused_count} token records for expired "
                f"subscription {subscription_id}"
            )

        return paused_count

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Error pausing tokens for subscription {subscription_id}: {str(e)}"
        )
        return 0


def reactivate_user_paused_tokens(user_id, new_subscription_id):
    """
    Reactivate paused tokens when user gets new subscription.
    Called when a new subscription is created.
    """
    try:
        # Get all paused tokens for this user
        paused_tokens = (
            UserToken.query
            .filter(UserToken.user_id == user_id)
            .filter(UserToken.is_paused == True)
            .filter(UserToken.tokens_remaining > 0)
            .all()
        )

        reactivated_count = 0
        total_tokens_reactivated = 0

        for token in paused_tokens:
            token.reactivate_tokens(new_subscription_id)
            reactivated_count += 1
            total_tokens_reactivated += token.tokens_remaining

        if reactivated_count > 0:
            db.session.commit()
            current_app.logger.info(
                f"Reactivated {reactivated_count} token records "
                f"({total_tokens_reactivated} tokens) for user {user_id} "
                f"with new subscription {new_subscription_id}"
            )

        return reactivated_count, total_tokens_reactivated

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Error reactivating tokens for user {user_id}: {str(e)}"
        )
        return 0, 0


def increment_usage(user_id, tokens=1):
    """Backward compatibility wrapper."""
    result = increment_usage_with_tokens(user_id, tokens)
    return result['success']


def handle_expired_subscriptions():
    """
    Handle expired subscriptions and pause their unused tokens.
    This should be called periodically (e.g., daily via cron job).
    """
    try:
        now = datetime.now(UTC)

        # Find subscriptions that just expired (within last 24 hours)
        # and are still marked as active
        expired_subscriptions = (
            SubscribedUser.query
            .filter(SubscribedUser.end_date <= now)
            .filter(SubscribedUser.end_date >= now - timedelta(hours=24))
            .filter(SubscribedUser._is_active == True)
            .all()
        )

        total_paused_tokens = 0
        total_subscriptions_processed = 0

        for sub in expired_subscriptions:
            try:
                # Mark subscription as inactive
                sub._is_active = False

                # Pause unused tokens for this subscription
                paused_count = pause_expired_subscription_tokens(sub.id)
                total_paused_tokens += paused_count
                total_subscriptions_processed += 1

                # Add history entry
                history_entry = SubscriptionHistory(
                    U_ID=sub.U_ID,
                    S_ID=sub.S_ID,
                    action='expire',
                    created_at=now
                )
                db.session.add(history_entry)

                current_app.logger.info(
                    f"Processed expired subscription {sub.id} for user "
                    f"{sub.U_ID}, paused {paused_count} token records"
                )

            except Exception as e:
                current_app.logger.error(
                    f"Error processing expired subscription {sub.id}: {str(e)}"
                )

        if total_subscriptions_processed > 0:
            db.session.commit()
            current_app.logger.info(
                f"Processed {total_subscriptions_processed} expired subscriptions, "
                f"paused {total_paused_tokens} token records"
            )

        return total_subscriptions_processed, total_paused_tokens

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Error handling expired subscriptions: {str(e)}"
        )
        return 0, 0


def process_auto_renewals():
    """Process auto-renewals for expiring subscriptions and handle token pausing."""
    # Get subscriptions expiring in the next 24 hours with auto-renew enabled
    now = datetime.now(UTC)
    expiring_soon = (
        SubscribedUser.query
        .filter(SubscribedUser.is_auto_renew == True)
        .filter(SubscribedUser._is_active == True)
        .filter(SubscribedUser.end_date <= now + timedelta(days=1))
        .filter(SubscribedUser.end_date > now)
        .options(joinedload(SubscribedUser.subscription))
        .all()
    )

    for sub in expiring_soon:
        try:
            # Process auto-renewal
            subscription = sub.subscription

            # Create Razorpay order for renewal
            payment = Payment(
                base_amount=subscription.price,
                user_id=sub.U_ID,
                subscription_id=sub.S_ID,
                razorpay_order_id=None,  # Will be set by Razorpay
                status='created',
                payment_type='renewal'
            )

            # Create Razorpay order
            razorpay_order = razorpay_client.order.create({
                'amount': int(payment.total_amount * 100),
                'currency': 'INR',
                'payment_capture': '1'
            })

            # Update with Razorpay order ID
            payment.razorpay_order_id = razorpay_order['id']
            db.session.add(payment)
            db.session.commit()

        except Exception as e:
            current_app.logger.error(
                f"Auto-renewal failed for user {sub.U_ID}: {str(e)}"
            )

    # Handle expired subscriptions and pause tokens
    try:
        handle_expired_subscriptions()
    except Exception as e:
        current_app.logger.error(
            f"Error handling expired subscriptions in auto-renewal process: {str(e)}"
        )

    db.session.commit()


def record_usage_log(user_id, subscription_id, operation_type, details=None,
                     tokens_used=1, is_trial=False):
    """
    Record a usage log entry for a subscription or trial user with token cost.

    Args:
        user_id (int): ID of the user
        subscription_id (int): ID of the SubscribedUser record (None for trial users)
        operation_type (str): Type of operation performed
        details (str, optional): Additional details about the operation
        tokens_used (int): Number of tokens consumed (default: 1)
        is_trial (bool): Whether this is a trial user usage (default: False)

    Returns:
        bool: True if recording succeeded, False otherwise
    """
    try:
        # Include token cost in details if not already specified
        if details and "tokens" not in details.lower():
            details = f"{details} - Tokens used: {tokens_used}"
        elif not details:
            details = f"Tokens used: {tokens_used}"

        # Create new usage log entry
        usage_log = UsageLog(
            user_id=user_id,
            subscription_id=subscription_id,
            operation_type=operation_type,
            details=details,
            timestamp=datetime.now(UTC),
            is_trial=is_trial
        )

        db.session.add(usage_log)
        db.session.commit()
        return True

    except Exception as e:
        current_app.logger.error(f"Error recording usage log: {str(e)}")
        db.session.rollback()
        return False


def subscription_required_with_tokens(tokens=1):
    """
    Decorator that checks subscription and uses tokens (daily quota + additional tokens).
    Also supports trial tokens for users without subscription.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Check if user is logged in
            if not current_user.is_authenticated:
                if 'user_id' not in session:
                    flash("Please login to access this feature.", "warning")
                    return redirect(url_for('auth.login'))
                user_id = session.get('user_id')
            else:
                user_id = current_user.id

            # Try to increment usage (handles subscription tokens AND trial tokens)
            usage_result = increment_usage_with_tokens(user_id, tokens)

            if not usage_result['success']:
                if usage_result['reason'] == 'no_tokens':
                    flash(
                        f"You've reached your daily limit and don't have enough "
                        f"additional tokens. This action requires {tokens} tokens.",
                        "warning"
                    )
                    return redirect(url_for('payment.user_subscriptions'))
                elif usage_result['reason'] == 'insufficient_trial_tokens':
                    flash(
                        f"Not enough trial tokens. You have "
                        f"{usage_result.get('trial_tokens_remaining', 0)} remaining "
                        f"but need {tokens}.",
                        "warning"
                    )
                    return redirect(url_for('payment.user_subscriptions'))
                elif usage_result['reason'] == 'no_active_subscription':
                    flash("Please subscribe to access this feature.", "warning")
                    return redirect(url_for('payment.user_subscriptions'))
                else:
                    flash(
                        f"Unable to process request: {usage_result['reason']}",
                        "warning"
                    )
                    return redirect(url_for('payment.user_subscriptions'))

            # Record usage log with detailed token information
            if usage_result.get('is_trial'):
                # Trial token usage
                tokens_used = usage_result.get('trial_tokens_used', tokens)
                remaining = usage_result.get('trial_tokens_remaining', 0)

                # Record usage log for trial user
                record_usage_log(
                    user_id=user_id,
                    subscription_id=None,
                    operation_type=f.__name__,
                    details=f"Trial usage - {usage_result['usage_breakdown']}",
                    tokens_used=tokens_used,
                    is_trial=True
                )

                flash(
                    f"Used {tokens_used} trial token"
                    f"{'s' if tokens_used != 1 else ''}. "
                    f"{remaining} trial token"
                    f"{'s' if remaining != 1 else ''} remaining.",
                    "info"
                )
                current_app.logger.info(
                    f"Trial tokens used by user {user_id}: {tokens_used}. "
                    f"Remaining: {remaining}"
                )
            else:
                # Get active subscription for logging
                now = datetime.now(UTC)
                active_subscription = (
                    SubscribedUser.query
                    .filter(SubscribedUser.U_ID == user_id)
                    .filter(SubscribedUser.end_date > now)
                    .filter(SubscribedUser._is_active == True)
                    .first()
                )
                if active_subscription:
                    record_usage_log(
                        user_id=user_id,
                        subscription_id=active_subscription.id,
                        operation_type=f.__name__,
                        details=(
                            f"Operation completed - "
                            f"{usage_result['usage_breakdown']}"
                        ),
                        tokens_used=tokens
                    )

                # Show token usage notification for subscribed users
                tokens_from_daily = usage_result.get('tokens_from_daily', 0)
                additional_tokens_used = usage_result.get('additional_tokens_used', 0)
                daily_limit = usage_result.get('daily_limit', 0)
                new_daily_usage = usage_result.get('new_daily_usage', 0)
                daily_remaining = max(0, daily_limit - new_daily_usage)

                if additional_tokens_used > 0:
                    flash(
                        f"Used {tokens} token{'s' if tokens != 1 else ''} "
                        f"({tokens_from_daily} daily + {additional_tokens_used} "
                        f"additional). Daily limit reached.",
                        "info"
                    )
                else:
                    flash(
                        f"Used {tokens} token{'s' if tokens != 1 else ''}. "
                        f"{daily_remaining} daily token"
                        f"{'s' if daily_remaining != 1 else ''} remaining.",
                        "info"
                    )

                current_app.logger.info(
                    f"Subscribed user {user_id}: Used {tokens} tokens. "
                    f"Daily: {new_daily_usage}/{daily_limit}, "
                    f"Additional used: {additional_tokens_used}"
                )

            return f(*args, **kwargs)

        return decorated_function
    return decorator


def subscription_check_only(f):
    """
    Decorator that checks if user has active subscription but doesn't count usage.
    Use this for pages that should be accessible to subscribers without consuming
    daily quota.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # First check if user is logged in
        if not current_user.is_authenticated:
            if 'user_id' not in session:
                current_app.logger.warning(
                    "subscription_check_only: User not authenticated, no session"
                )
                flash("Please login to access this feature.", "warning")
                return redirect(url_for('auth.login'))
            user_id = session.get('user_id')
        else:
            user_id = current_user.id

        current_app.logger.info(
            f"subscription_check_only: Checking subscription for user {user_id}"
        )

        # Check subscription without incrementing usage
        now = datetime.now(UTC)
        active_subscription = (
            SubscribedUser.query
            .filter(SubscribedUser.U_ID == user_id)
            .filter(SubscribedUser.end_date > now)
            .filter(SubscribedUser._is_active == True)
            .first()
        )

        if not active_subscription:
            # Check if user has trial tokens available
            user = db.session.get(User, user_id)
            if user and user.trial_tokens > 0:
                current_app.logger.info(
                    f"subscription_check_only: No subscription but user "
                    f"{user_id} has {user.trial_tokens} trial tokens, "
                    f"allowing access"
                )
                return f(*args, **kwargs)

            current_app.logger.warning(
                f"subscription_check_only: No active subscription and no "
                f"trial tokens for user {user_id}"
            )
            flash("Please subscribe to access this feature.", "warning")
            return redirect(url_for('payment.user_subscriptions'))

        current_app.logger.info(
            f"subscription_check_only: Active subscription found for user "
            f"{user_id}, allowing access to {f.__name__}"
        )
        # No usage increment - just allow access
        return f(*args, **kwargs)

    return decorated_function


def cleanup_duplicate_subscriptions():
    """
    Utility function to clean up duplicate active subscriptions for users.
    Keeps only the most recent active subscription per user.
    """
    now = datetime.now(UTC)

    # Get all users
    users = User.query.all()

    deactivated_count = 0

    for user in users:
        # Get all active subscriptions for this user
        active_subscriptions = (
            SubscribedUser.query
            .filter(SubscribedUser.U_ID == user.id)
            .filter(SubscribedUser.end_date > now)
            .filter(SubscribedUser._is_active == True)
            .order_by(SubscribedUser.start_date.desc())
            .all()
        )

        # If user has more than one active subscription
        if len(active_subscriptions) > 1:
            # Keep the first (most recent) one, deactivate the rest
            for sub in active_subscriptions[1:]:
                sub.is_active = False
                deactivated_count += 1
                current_app.logger.info(
                    f"Deactivated duplicate subscription {sub.id} "
                    f"for user {user.id}"
                )

    if deactivated_count > 0:
        db.session.commit()
        current_app.logger.info(
            f"Cleaned up {deactivated_count} duplicate subscriptions"
        )

    return deactivated_count


def get_available_tokens(user_id):
    """
    Get the number of tokens available for a user today.

    Returns:
        dict: {'available': int, 'total': int, 'used': int}
    """
    now = datetime.now(UTC)
    active_subscription = (
        SubscribedUser.query
        .filter(SubscribedUser.U_ID == user_id)
        .filter(SubscribedUser.end_date > now)
        .filter(SubscribedUser._is_active == True)
        .first()
    )

    if not active_subscription:
        return {'available': 0, 'total': 0, 'used': 0}

    # Apply daily reset logic
    today = datetime.now(UTC).date()
    last_reset_date = getattr(active_subscription, 'last_usage_reset', None)

    if not last_reset_date or last_reset_date.date() < today:
        active_subscription.current_usage = 0
        active_subscription.last_usage_reset = datetime.now(UTC)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    total_tokens = active_subscription.get_total_usage_limit()
    used_tokens = active_subscription.current_usage
    available_tokens = max(0, total_tokens - used_tokens)

    return {
        'available': available_tokens,
        'total': total_tokens,
        'used': used_tokens
    }


def get_user_token_summary(user_id):
    """Get comprehensive token usage summary for a user."""
    try:
        # Get active subscription
        active_subscription = (
            SubscribedUser.query
            .filter(SubscribedUser.U_ID == user_id)
            .filter(SubscribedUser.end_date > datetime.now(UTC))
            .filter(SubscribedUser._is_active == True)
            .first()
        )

        if not active_subscription:
            return None

        # Check if daily limit is reached
        daily_limit_reached = (
            active_subscription.current_usage
            >= active_subscription.get_total_usage_limit()
        )

        # Get ALL user's token records that haven't expired
        user_tokens = (
            UserToken.query
            .filter(UserToken.user_id == user_id)
            .filter(UserToken.expires_at > datetime.now(UTC))
            .all()
        )

        # Calculate token totals
        total_tokens_purchased = sum(
            token.tokens_purchased for token in user_tokens
        )
        total_tokens_used = sum(token.tokens_used for token in user_tokens)
        purchased_tokens_available = sum(
            token.tokens_remaining for token in user_tokens
        )

        return {
            'daily_limit_reached': daily_limit_reached,
            'total_tokens_purchased': total_tokens_purchased,
            'total_tokens_used': total_tokens_used,
            'purchased_tokens_available': purchased_tokens_available,
            'active_subscription': active_subscription
        }

    except Exception as e:
        current_app.logger.error(f"Error getting token summary: {str(e)}")
        return None


def use_additional_token(user_id):
    """Use one additional token if available."""
    try:
        # Get available tokens (oldest first)
        available_tokens = (
            UserToken.query
            .filter(UserToken.user_id == user_id)
            .filter(UserToken.tokens_remaining > 0)
            .filter(UserToken.expires_at > datetime.now(UTC))
            .order_by(UserToken.created_at.asc())
            .all()
        )

        if not available_tokens:
            return False

        # Use token from oldest purchase first
        token_record = available_tokens[0]
        token_record.tokens_used += 1
        token_record.tokens_remaining -= 1

        db.session.commit()
        return True

    except Exception as e:
        current_app.logger.error(f"Error using additional token: {str(e)}")
        db.session.rollback()
        return False


def get_today_token_usage_breakdown(user_id):
    """
    Get detailed breakdown of today's token usage including additional tokens.

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
                current_app.logger.error(
                    f"Error resetting daily usage: {str(e)}"
                )

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
                    # Check for new format:
                    # "Operation completed - Used X from daily quota + Y additional tokens (Total: Z)"
                    total_match = re.search(
                        r'Total:\s*(\d+)', log.details, re.IGNORECASE
                    )
                    if total_match:
                        total_tokens_from_logs += int(total_match.group(1))

                        # Look for additional tokens pattern
                        additional_match = re.search(
                            r'(\d+)\s+additional\s+tokens',
                            log.details,
                            re.IGNORECASE
                        )
                        if additional_match:
                            additional_tokens_used += int(
                                additional_match.group(1)
                            )

                    # Check for old format: "Tokens used: X"
                    elif "Tokens used:" in log.details:
                        token_match = re.search(
                            r'Tokens used:\s*(\d+)', log.details
                        )
                        if token_match:
                            tokens_in_log = int(token_match.group(1))
                            total_tokens_from_logs += tokens_in_log

            except Exception as e:
                current_app.logger.error(
                    f"Error parsing usage log {log.id}: {str(e)}"
                )
                continue

        # Use total from logs if available, otherwise calculate
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
        current_app.logger.error(
            f"Error calculating today's token usage: {str(e)}"
        )
        return {
            'daily_quota_used': 0,
            'additional_tokens_used': 0,
            'total_tokens_used_today': 0,
            'daily_limit': 0
        }


def add_search_history(user_id, usage_tool, search_query):
    """Logs every search performed by a user with full timestamp."""
    if not user_id:
        return False

    try:
        # Fetch user or fallback to "Guest"
        user = db.session.get(User, user_id)
        user_name = user.name if user else "Guest"

        # Create a new SearchHistory entry (always)
        entry = SearchHistory(
            u_id=user_id,
            user_name=user_name,
            usage_tool=usage_tool,
            search_history=search_query,
            search_count=1,
            created_at=datetime.now(UTC)
        )

        db.session.add(entry)
        db.session.commit()
        return True

    except SQLAlchemyError as e:
        current_app.logger.error(f"Error logging search history: {e}")
        db.session.rollback()
        return False


def remove_search_history(user_id, search_query):
    """Removes search history entries for a specific URL when analysis fails."""
    if not user_id or not search_query:
        return False

    try:
        # Delete all entries matching user_id and search_query
        deleted = SearchHistory.query.filter(
            SearchHistory.u_id == user_id,
            SearchHistory.search_history == search_query
        ).delete()

        db.session.commit()
        if deleted > 0:
            current_app.logger.info(
                f"Removed {deleted} search history entries for user "
                f"{user_id}, URL: {search_query}"
            )
        return True

    except SQLAlchemyError as e:
        current_app.logger.error(f"Error removing search history: {e}")
        db.session.rollback()
        return False


def cleanup_old_crawl_data(days_to_keep=7):
    """Delete crawl data files older than specified days."""
    import time
    import glob

    try:
        crawl_data_dir = "crawled_data"
        deleted_count = 0

        if not os.path.exists(crawl_data_dir):
            os.makedirs(crawl_data_dir, exist_ok=True)
            return 0

        cutoff_time = time.time() - (days_to_keep * 24 * 60 * 60)

        crawl_files = glob.glob(os.path.join(crawl_data_dir, 'crawl_*.json'))
        crawl_files.extend(glob.glob(os.path.join(crawl_data_dir, 'crawl_*.csv')))

        for file_path in crawl_files:
            try:
                file_mtime = os.path.getmtime(file_path)
                if file_mtime < cutoff_time:
                    os.remove(file_path)
                    deleted_count += 1
                    current_app.logger.info(f"Deleted old crawl file: {os.path.basename(file_path)}")
            except Exception as e:
                current_app.logger.error(f"Error deleting file {file_path}: {str(e)}")

        if deleted_count > 0:
            current_app.logger.info(f"Cleanup completed. Deleted {deleted_count} files")

        return deleted_count

    except Exception as e:
        current_app.logger.error(f"Error during crawl data cleanup: {str(e)}")
        return 0


def cleanup_crawl_status_memory():
    """Clean up old crawl status entries from Redis."""
    try:
        from crawl_status_manager import CrawlStatusManager
        manager = CrawlStatusManager(
            redis_host=os.environ.get('REDIS_HOST', 'localhost'),
            redis_port=int(os.environ.get('REDIS_PORT', 6379)),
            redis_db=1,
            redis_password=os.environ.get('REDIS_PASSWORD', None)
        )
        cleaned_count = manager.cleanup_old_jobs(max_age_seconds=3600)
        if cleaned_count > 0:
            current_app.logger.info(f"Cleaned up {cleaned_count} old crawl status entries")
        return cleaned_count
    except Exception as e:
        current_app.logger.error(f"Error cleaning up crawl status: {str(e)}")
        return 0
