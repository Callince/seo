"""
Refund service for handling Razorpay refunds, cancellation refunds,
and failed payment recovery.
"""
import logging
import traceback
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import current_app

from extensions import db, razorpay_client
from models import (
    User, Payment, Subscription, SubscribedUser, SubscriptionHistory,
    TokenPurchase, UserToken, EmailLog
)

UTC = timezone.utc


def issue_razorpay_refund(razorpay_payment_id, amount_in_paise=None, notes=None):
    """
    Issue a refund via Razorpay API.

    Args:
        razorpay_payment_id: Razorpay payment ID (pay_xxxxx)
        amount_in_paise: Amount to refund in paise (None = full refund)
        notes: Optional dict of notes to attach to refund

    Returns:
        dict: {'success': bool, 'refund_id': str or None, 'error': str or None}
    """
    try:
        refund_data = {}
        if amount_in_paise is not None:
            refund_data['amount'] = int(amount_in_paise)
        if notes:
            refund_data['notes'] = notes

        refund = razorpay_client.payment.refund(razorpay_payment_id, refund_data)

        current_app.logger.info(
            f"Razorpay refund issued: refund_id={refund.get('id')}, "
            f"payment_id={razorpay_payment_id}, amount={amount_in_paise}"
        )

        return {
            'success': True,
            'refund_id': refund.get('id'),
            'amount': refund.get('amount'),
            'status': refund.get('status'),
            'error': None
        }

    except Exception as e:
        current_app.logger.error(
            f"Razorpay refund failed for payment {razorpay_payment_id}: {str(e)}"
        )
        return {
            'success': False,
            'refund_id': None,
            'error': str(e)
        }


def auto_refund_failed_payment(payment_id):
    """
    Auto-refund a payment that was debited but verification failed.
    Called when signature/amount verification fails after Razorpay deducted money.

    Args:
        payment_id: Internal Payment.iid

    Returns:
        dict: {'success': bool, 'refund_id': str, 'message': str}
    """
    try:
        payment = db.session.get(Payment, payment_id)
        if not payment:
            return {'success': False, 'message': 'Payment not found'}

        if not payment.razorpay_payment_id:
            return {'success': False, 'message': 'No Razorpay payment ID - money was not debited'}

        if payment.status == 'refunded':
            return {'success': False, 'message': 'Payment already refunded'}

        if payment.status == 'completed':
            return {'success': False, 'message': 'Cannot auto-refund completed payment. Use admin refund.'}

        # Issue full refund via Razorpay
        result = issue_razorpay_refund(
            payment.razorpay_payment_id,
            notes={
                'reason': 'verification_failed',
                'payment_id': str(payment.iid),
                'user_id': str(payment.user_id)
            }
        )

        if result['success']:
            payment.status = 'refunded'
            payment.notes = (payment.notes or '') + f"\nAuto-refunded: {result['refund_id']} at {datetime.now(UTC).isoformat()}"
            db.session.commit()

            current_app.logger.info(
                f"Auto-refund successful: payment={payment.iid}, "
                f"refund_id={result['refund_id']}"
            )

            return {
                'success': True,
                'refund_id': result['refund_id'],
                'message': f"Full refund of Rs.{payment.total_amount} issued successfully"
            }
        else:
            payment.notes = (payment.notes or '') + f"\nAuto-refund FAILED: {result['error']} at {datetime.now(UTC).isoformat()}"
            db.session.commit()

            return {
                'success': False,
                'message': f"Refund failed: {result['error']}. Contact Razorpay support."
            }

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Auto-refund error: {str(e)}")
        return {'success': False, 'message': f'System error: {str(e)}'}


def admin_refund_payment(payment_id, admin_id, reason='admin_refund', partial_amount=None):
    """
    Admin-initiated refund for a completed payment.

    Args:
        payment_id: Internal Payment.iid
        admin_id: Admin who initiated the refund
        reason: Reason for refund
        partial_amount: Amount to refund (None = full refund)

    Returns:
        dict: {'success': bool, 'refund_id': str, 'message': str}
    """
    try:
        payment = db.session.get(Payment, payment_id)
        if not payment:
            return {'success': False, 'message': 'Payment not found'}

        if payment.status == 'refunded':
            return {'success': False, 'message': 'Payment already refunded'}

        if payment.status != 'completed':
            return {'success': False, 'message': f'Cannot refund payment with status: {payment.status}'}

        if not payment.razorpay_payment_id:
            return {'success': False, 'message': 'No Razorpay payment ID found'}

        # Calculate refund amount
        if partial_amount:
            refund_amount = float(partial_amount)
            if refund_amount > payment.total_amount:
                return {'success': False, 'message': 'Refund amount exceeds payment amount'}
            amount_in_paise = int(refund_amount * 100)
        else:
            refund_amount = payment.total_amount
            amount_in_paise = None  # Full refund

        # Issue refund via Razorpay
        result = issue_razorpay_refund(
            payment.razorpay_payment_id,
            amount_in_paise=amount_in_paise,
            notes={
                'reason': reason,
                'admin_id': str(admin_id),
                'payment_id': str(payment.iid)
            }
        )

        if result['success']:
            # Update payment status
            payment.status = 'refunded'
            payment.notes = (
                (payment.notes or '') +
                f"\nRefunded by admin {admin_id}: Rs.{refund_amount} "
                f"(Reason: {reason}) Refund ID: {result['refund_id']} "
                f"at {datetime.now(UTC).isoformat()}"
            )

            # Deactivate the subscription if full refund
            if not partial_amount:
                subscribed_user = (
                    SubscribedUser.query
                    .filter(SubscribedUser.U_ID == payment.user_id)
                    .filter(SubscribedUser.S_ID == payment.subscription_id)
                    .filter(SubscribedUser._is_active == True)
                    .first()
                )
                if subscribed_user:
                    subscribed_user._is_active = False

                    # Add cancellation history
                    history = SubscriptionHistory(
                        U_ID=payment.user_id,
                        S_ID=payment.subscription_id,
                        action='refund',
                        created_at=datetime.now(UTC)
                    )
                    db.session.add(history)

                    # Pause tokens
                    from services.subscription import pause_expired_subscription_tokens
                    pause_expired_subscription_tokens(subscribed_user.id)

            db.session.commit()

            current_app.logger.info(
                f"Admin refund successful: payment={payment.iid}, "
                f"amount=Rs.{refund_amount}, admin={admin_id}"
            )

            return {
                'success': True,
                'refund_id': result['refund_id'],
                'amount': refund_amount,
                'message': f"Refund of Rs.{refund_amount} processed successfully"
            }
        else:
            payment.notes = (
                (payment.notes or '') +
                f"\nRefund FAILED by admin {admin_id}: {result['error']} "
                f"at {datetime.now(UTC).isoformat()}"
            )
            db.session.commit()
            return {'success': False, 'message': f"Razorpay refund failed: {result['error']}"}

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin refund error: {str(e)}\n{traceback.format_exc()}")
        return {'success': False, 'message': f'System error: {str(e)}'}


def cancel_subscription_with_refund(subscription_id, user_id):
    """
    Cancel subscription with prorated refund for remaining days.

    Args:
        subscription_id: SubscribedUser.id
        user_id: User.id

    Returns:
        dict: {'success': bool, 'refund_amount': float, 'refund_id': str, 'message': str}
    """
    try:
        subscribed_user = (
            SubscribedUser.query
            .filter(SubscribedUser.id == subscription_id)
            .filter(SubscribedUser.U_ID == user_id)
            .first()
        )

        if not subscribed_user:
            return {'success': False, 'message': 'Subscription not found'}

        if not subscribed_user.is_active:
            return {'success': False, 'message': 'Subscription is not active'}

        # Calculate prorated refund
        now = datetime.now(UTC)
        start = subscribed_user.start_date
        end = subscribed_user.end_date

        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)

        total_days = (end - start).total_seconds() / 86400
        remaining_days = max(0, (end - now).total_seconds() / 86400)

        if total_days <= 0 or remaining_days <= 0:
            return {'success': False, 'message': 'No remaining days to refund'}

        # Find the completed payment for this subscription
        payment = (
            Payment.query
            .filter(Payment.user_id == user_id)
            .filter(Payment.subscription_id == subscribed_user.S_ID)
            .filter(Payment.status == 'completed')
            .order_by(Payment.created_at.desc())
            .first()
        )

        if not payment or not payment.razorpay_payment_id:
            # No payment to refund, just cancel
            subscribed_user._is_active = False
            subscribed_user.is_auto_renew = False
            history = SubscriptionHistory(
                U_ID=user_id, S_ID=subscribed_user.S_ID,
                action='cancel', created_at=now
            )
            db.session.add(history)
            db.session.commit()
            return {
                'success': True,
                'refund_amount': 0,
                'refund_id': None,
                'message': 'Subscription cancelled. No payment found to refund.'
            }

        # Calculate prorated refund amount
        refund_ratio = Decimal(str(remaining_days)) / Decimal(str(total_days))
        refund_amount = (Decimal(str(payment.total_amount)) * refund_ratio).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        refund_amount = float(refund_amount)

        # Minimum refund Rs.1
        if refund_amount < 1.0:
            refund_amount = 0
            refund_result = {'success': True, 'refund_id': None}
        else:
            # Issue prorated refund
            refund_result = issue_razorpay_refund(
                payment.razorpay_payment_id,
                amount_in_paise=int(refund_amount * 100),
                notes={
                    'reason': 'prorated_cancellation',
                    'remaining_days': str(round(remaining_days, 1)),
                    'total_days': str(round(total_days, 1)),
                    'user_id': str(user_id)
                }
            )

        if refund_result['success']:
            # Cancel subscription
            subscribed_user._is_active = False
            subscribed_user.is_auto_renew = False

            # Update payment
            if refund_amount > 0:
                payment.status = 'partial_refund'
                payment.notes = (
                    (payment.notes or '') +
                    f"\nProrated refund: Rs.{refund_amount} "
                    f"({round(remaining_days, 1)}/{round(total_days, 1)} days remaining) "
                    f"Refund ID: {refund_result.get('refund_id')} "
                    f"at {now.isoformat()}"
                )

            # History entry
            history = SubscriptionHistory(
                U_ID=user_id, S_ID=subscribed_user.S_ID,
                action='cancel_refund', created_at=now
            )
            db.session.add(history)

            # Pause tokens
            from services.subscription import pause_expired_subscription_tokens
            pause_expired_subscription_tokens(subscribed_user.id)

            db.session.commit()

            current_app.logger.info(
                f"Subscription cancelled with refund: user={user_id}, "
                f"refund=Rs.{refund_amount}, remaining_days={round(remaining_days, 1)}"
            )

            return {
                'success': True,
                'refund_amount': refund_amount,
                'refund_id': refund_result.get('refund_id'),
                'remaining_days': round(remaining_days, 1),
                'message': (
                    f"Subscription cancelled. Refund of Rs.{refund_amount} "
                    f"for {round(remaining_days, 1)} remaining days will be "
                    f"credited within 5-7 business days."
                    if refund_amount > 0
                    else "Subscription cancelled successfully."
                )
            }
        else:
            return {
                'success': False,
                'message': f"Refund failed: {refund_result.get('error')}. Subscription not cancelled."
            }

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Cancel with refund error: {str(e)}\n{traceback.format_exc()}")
        return {'success': False, 'message': f'System error: {str(e)}'}


def check_duplicate_payment(user_id, subscription_id):
    """
    Check if there's already a pending/completed payment for this subscription.

    Returns:
        dict: {'is_duplicate': bool, 'existing_payment': Payment or None}
    """
    now = datetime.now(UTC)

    # Check for recent pending payments (created in last 30 minutes)
    recent_payment = (
        Payment.query
        .filter(Payment.user_id == user_id)
        .filter(Payment.subscription_id == subscription_id)
        .filter(Payment.status.in_(['created', 'completed']))
        .filter(Payment.created_at >= now - __import__('datetime').timedelta(minutes=30))
        .order_by(Payment.created_at.desc())
        .first()
    )

    if recent_payment:
        if recent_payment.status == 'completed':
            return {
                'is_duplicate': True,
                'existing_payment': recent_payment,
                'message': 'You already have a completed payment for this subscription.'
            }
        elif recent_payment.status == 'created':
            return {
                'is_duplicate': True,
                'existing_payment': recent_payment,
                'message': 'You have a pending payment. Please complete it or wait 30 minutes.'
            }

    return {'is_duplicate': False, 'existing_payment': None}


def handle_webhook_payment(razorpay_payment_id, razorpay_order_id, razorpay_signature):
    """
    Handle payment confirmation from Razorpay webhook.
    This catches payments even if user closed the browser.

    Returns:
        dict: {'success': bool, 'message': str}
    """
    try:
        # Find payment by order ID
        payment = Payment.query.filter_by(razorpay_order_id=razorpay_order_id).first()

        if not payment:
            current_app.logger.warning(f"Webhook: No payment found for order {razorpay_order_id}")
            return {'success': False, 'message': 'Payment not found'}

        # Already processed
        if payment.status == 'completed':
            return {'success': True, 'message': 'Payment already processed'}

        if payment.status == 'refunded':
            return {'success': False, 'message': 'Payment was refunded'}

        # Verify signature
        import hmac
        import hashlib
        message = f"{razorpay_order_id}|{razorpay_payment_id}"
        expected_signature = hmac.new(
            current_app.config['RAZORPAY_KEY_SECRET'].encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        if expected_signature != razorpay_signature:
            current_app.logger.error(f"Webhook: Invalid signature for order {razorpay_order_id}")
            return {'success': False, 'message': 'Invalid signature'}

        # Fetch payment details from Razorpay
        payment_details = razorpay_client.payment.fetch(razorpay_payment_id)
        expected_amount = int(payment.total_amount * 100)

        if payment_details['amount'] != expected_amount:
            current_app.logger.error(
                f"Webhook: Amount mismatch for order {razorpay_order_id}: "
                f"expected={expected_amount}, got={payment_details['amount']}"
            )
            # Auto-refund on amount mismatch
            auto_refund_failed_payment(payment.iid)
            return {'success': False, 'message': 'Amount mismatch - refund initiated'}

        if payment_details['status'] not in ['authorized', 'captured']:
            current_app.logger.error(
                f"Webhook: Payment not captured for order {razorpay_order_id}: "
                f"status={payment_details['status']}"
            )
            return {'success': False, 'message': f"Payment status: {payment_details['status']}"}

        # Process the payment
        payment.razorpay_payment_id = razorpay_payment_id
        payment.status = 'completed'

        # Create subscription
        subscription = db.session.get(Subscription, payment.subscription_id)
        if subscription:
            from datetime import timedelta
            start_date = datetime.now(UTC)
            end_date = start_date + timedelta(days=subscription.days)

            new_sub = SubscribedUser(
                U_ID=payment.user_id,
                S_ID=subscription.S_ID,
                start_date=start_date,
                end_date=end_date,
                is_auto_renew=True,
                current_usage=0,
                last_usage_reset=start_date,
                _is_active=True
            )
            db.session.add(new_sub)
            db.session.flush()

            # Reactivate paused tokens
            try:
                from services.subscription import reactivate_user_paused_tokens
                reactivate_user_paused_tokens(payment.user_id, new_sub.id)
            except Exception:
                pass

            # History entry
            history = SubscriptionHistory(
                U_ID=payment.user_id,
                S_ID=subscription.S_ID,
                action=payment.payment_type or 'new',
                previous_S_ID=payment.previous_subscription_id,
                created_at=datetime.now(UTC)
            )
            db.session.add(history)

        db.session.commit()

        current_app.logger.info(
            f"Webhook: Payment processed successfully: order={razorpay_order_id}, "
            f"payment={razorpay_payment_id}, user={payment.user_id}"
        )

        # Send confirmation email
        try:
            from services.email import send_payment_confirmation_email
            user = db.session.get(User, payment.user_id)
            if user and subscription:
                send_payment_confirmation_email(user, payment, subscription)
        except Exception as e:
            current_app.logger.error(f"Webhook: Failed to send email: {str(e)}")

        return {'success': True, 'message': 'Payment processed via webhook'}

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Webhook payment error: {str(e)}\n{traceback.format_exc()}")
        return {'success': False, 'message': f'Error: {str(e)}'}
