import logging
import traceback
from datetime import datetime, timedelta, timezone
from flask import current_app, url_for
from flask_mail import Message
from extensions import db, mail
from models import User, EmailLog, SubscribedUser, Subscription

UTC = timezone.utc


def send_verification_email(user):
    """Send email verification with enhanced error handling and logging"""
    try:
        token = user.get_email_confirm_token()
        subject = 'Email Verification - Fourth Dimension'

        msg = Message(subject,
                      sender=current_app.config['MAIL_USERNAME'],
                      recipients=[user.company_email])

        # Text version for email clients that don't support HTML
        msg.body = f'''Hello {user.name},

Thank you for signing up with Fourth Dimension!

To verify your email address, please click the following link:

{url_for('auth.verify_email', token=token, _external=True)}

This link will expire in 24 hours.

If you did not create an account, please ignore this email.

Thanks,
Fourth Dimension Team
'''

        # Use logo from static images folder
        logo_url = url_for('static', filename='images/seodada.png', _external=True)
        # HTML version for better presentation
        msg.html = f'''
<!DOCTYPE html>
<html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Email Verification - SEO Dada</title>
    </head>
    <body style="font-family: system-ui, -apple-system, sans-serif; line-height: 1.6; color: #1e293b; margin: 0; padding: 0; background-color: #f8fafc;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #273879 0%, #0f74b2 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
                <img src="{logo_url}" alt="SEO Dada" style="max-height: 60px; width: auto; margin-bottom: 10px;" />
                <p style="color: rgba(255,255,255,0.9); margin: 8px 0 0 0; font-size: 14px;">Professional SEO Analysis Platform</p>
            </div>

            <div style="background-color: #ffffff; padding: 40px 35px; border-radius: 0 0 12px 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.07);">
                <h2 style="background: linear-gradient(135deg, #273879 0%, #0f74b2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-bottom: 20px; font-size: 24px;">Welcome to SEO Dada!</h2>

                <p style="margin-bottom: 20px; color: #1e293b;">Hello <strong style="color: #273879;">{user.name}</strong>,</p>

                <p style="margin-bottom: 25px; color: #64748b; line-height: 1.7;">Thank you for signing up with SEO Dada! To complete your account setup and start analyzing websites, please verify your email address by clicking the button below.</p>

                <div style="text-align: center; margin: 35px 0;">
                    <a href="{url_for('auth.verify_email', token=token, _external=True)}"
                       style="background: linear-gradient(135deg, #273879 0%, #0f74b2 100%); color: white; padding: 15px 35px; text-decoration: none; border-radius: 8px; display: inline-block; font-weight: 600; font-size: 16px; box-shadow: 0 4px 6px rgba(39, 56, 121, 0.3); transition: all 0.3s ease;">
                        Verify Email Address
                    </a>
                </div>

                <div style="margin-top: 30px; padding-top: 20px; border-top: 2px solid #e2e8f0;">
                    <p style="margin-bottom: 12px; color: #273879; font-weight: 600; font-size: 15px;">📌 Important:</p>
                    <ul style="color: #64748b; font-size: 14px; margin: 0; padding-left: 20px; line-height: 1.8;">
                        <li>This verification link will expire in 24 hours</li>
                        <li>If you did not create an account, please ignore this email</li>
                        <li>For security reasons, do not share this link with anyone</li>
                    </ul>
                </div>

                <div style="margin-top: 35px; padding-top: 25px; border-top: 1px solid #e2e8f0; text-align: center; color: #64748b; font-size: 13px;">
                    <p style="margin: 0; color: #1e293b;">Best regards,<br><strong style="background: linear-gradient(135deg, #273879 0%, #0f74b2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;">SEO Dada Team</strong></p>
                    <p style="margin: 12px 0 0 0;">Need help? Contact us at <a href="mailto:support@seodada.com" style="color: #0f74b2; text-decoration: none;">support@seodada.com</a></p>
                </div>
            </div>

            <div style="text-align: center; padding: 20px; color: #94a3b8; font-size: 12px;">
                <p style="margin: 0;">&copy; {datetime.now().year} SEO Dada. All rights reserved.</p>
            </div>
        </div>
    </body>
</html>
        '''

        # Send the email
        mail.send(msg)

        # Log successful email
        EmailLog.log_email(
            recipient_email=user.company_email,
            recipient_name=user.name,
            email_type='verification',
            subject=subject,
            user_id=user.id,
            status='sent',
            metadata={'token_expires_hours': 24}
        )

        logging.info(f"Verification email sent successfully to {user.company_email}")

    except Exception as e:
        # Log failed email
        EmailLog.log_email(
            recipient_email=user.company_email,
            recipient_name=user.name,
            email_type='verification',
            subject=subject,
            user_id=user.id,
            status='failed',
            error_message=str(e)
        )

        logging.error(f"Failed to send verification email to {user.company_email}: {str(e)}")
        raise  # Re-raise the exception so the calling code can handle it


def send_reset_email(user):
    """Send password reset email with enhanced error handling and logging"""
    try:
        token = user.get_reset_token()
        subject = 'Password Reset Request - Fourth Dimension'

        msg = Message(subject,
                      sender=current_app.config['MAIL_USERNAME'],
                      recipients=[user.company_email])

        # Text version for email clients that don't support HTML
        msg.body = f'''Hello {user.name},

You have requested a password reset for your Fourth Dimension account.

To reset your password, please click the following link:

{url_for('auth.reset_token', token=token, _external=True)}

This link will expire in 30 minutes.

If you did not request this password reset, please ignore this email and your password will remain unchanged.

Thanks,
Fourth Dimension Team
'''

        # Use logo from static images folder
        logo_url = url_for('static', filename='images/seodada.png', _external=True)
        # HTML version for better presentation
        msg.html = f'''
<!DOCTYPE html>
<html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Password Reset Request - SEO Dada</title>
    </head>
    <body style="font-family: system-ui, -apple-system, sans-serif; line-height: 1.6; color: #1e293b; margin: 0; padding: 0; background-color: #f8fafc;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #273879 0%, #0f74b2 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
                <img src="{logo_url}" alt="SEO Dada" style="max-height: 60px; width: auto; margin-bottom: 10px;" />
                <p style="color: rgba(255,255,255,0.9); margin: 8px 0 0 0; font-size: 14px;">Professional SEO Analysis Platform</p>
            </div>

            <div style="background-color: #ffffff; padding: 40px 35px; border-radius: 0 0 12px 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.07);">
                <h2 style="color: #ef4444; margin-bottom: 20px; font-size: 24px;">🔒 Password Reset Request</h2>

                <p style="margin-bottom: 20px; color: #1e293b;">Hello <strong style="color: #273879;">{user.name}</strong>,</p>

                <p style="margin-bottom: 25px; color: #64748b; line-height: 1.7;">You have requested a password reset for your SEO Dada account. Click the button below to create a new password.</p>

                <div style="text-align: center; margin: 35px 0;">
                    <a href="{url_for('auth.reset_token', token=token, _external=True)}"
                       style="background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); color: white; padding: 15px 35px; text-decoration: none; border-radius: 8px; display: inline-block; font-weight: 600; font-size: 16px; box-shadow: 0 4px 6px rgba(239, 68, 68, 0.3); transition: all 0.3s ease;">
                        Reset Password
                    </a>
                </div>

                <div style="margin-top: 30px; padding-top: 20px; border-top: 2px solid #e2e8f0;">
                    <p style="margin-bottom: 12px; color: #ef4444; font-weight: 600; font-size: 15px;">⚠️ Important Security Notice:</p>
                    <ul style="color: #64748b; font-size: 14px; margin: 0; padding-left: 20px; line-height: 1.8;">
                        <li>This password reset link will expire in 30 minutes</li>
                        <li>If you did not request this password reset, please ignore this email</li>
                        <li>Your password will remain unchanged unless you click the link above</li>
                        <li>For security reasons, do not share this link with anyone</li>
                    </ul>
                </div>

                <div style="margin-top: 35px; padding-top: 25px; border-top: 1px solid #e2e8f0; text-align: center; color: #64748b; font-size: 13px;">
                    <p style="margin: 0; color: #1e293b;">Best regards,<br><strong style="background: linear-gradient(135deg, #273879 0%, #0f74b2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;">SEO Dada Team</strong></p>
                    <p style="margin: 12px 0 0 0;">Need help? Contact us at <a href="mailto:support@seodada.com" style="color: #0f74b2; text-decoration: none;">support@seodada.com</a></p>
                </div>
            </div>

            <div style="text-align: center; padding: 20px; color: #94a3b8; font-size: 12px;">
                <p style="margin: 0;">&copy; {datetime.now().year} SEO Dada. All rights reserved.</p>
            </div>
        </div>
    </body>
</html>
        '''

        # Send the email
        mail.send(msg)

        # Log successful email
        EmailLog.log_email(
            recipient_email=user.company_email,
            recipient_name=user.name,
            email_type='password_reset',
            subject=subject,
            user_id=user.id,
            status='sent',
            metadata={'token_expires_minutes': 30}
        )

        logging.info(f"Password reset email sent successfully to {user.company_email}")

    except Exception as e:
        # Log failed email
        EmailLog.log_email(
            recipient_email=user.company_email,
            recipient_name=user.name,
            email_type='password_reset',
            subject=subject,
            user_id=user.id,
            status='failed',
            error_message=str(e)
        )

        logging.error(f"Failed to send password reset email to {user.company_email}: {str(e)}")
        raise


def send_token_purchase_confirmation_email(user, token_purchase):
    """Send token purchase confirmation email with logging"""
    try:
        subject = f"Token Purchase Confirmation - {token_purchase.token_count} Additional Tokens"
        # Use payment@seodada.com for payment-related emails
        sender_email = 'payment@seodada.com'

        message = Message(
            subject,
            sender=sender_email,
            recipients=[user.company_email]
        )

        # Text version for email clients that don't support HTML
        message.body = f"""Dear {user.name},

Great news! Your token purchase has been processed successfully. You now have {token_purchase.token_count} additional tokens available in your account.

Purchase Details:
- Tokens Purchased: {token_purchase.token_count} tokens
- Amount Paid: ₹{token_purchase.total_amount}
- Invoice Number: {token_purchase.invoice_number}
- Purchase Date: {token_purchase.created_at.strftime('%d %b %Y, %H:%M UTC')}
- Order ID: {token_purchase.razorpay_order_id}

How Your Tokens Work:
✅ Tokens are immediately available in your account
⏰ Valid for 1 year from purchase date
🔄 Used automatically when daily quota is exhausted
📊 Track usage in your subscription dashboard

You can view your dashboard and download your invoice from your account.

Thanks for choosing SEO Dada!

The SEO Dada Team
Need help? Contact us at payment@seodada.com
"""

        # Use logo from static images folder
        logo_url = url_for('static', filename='images/seodada.png', _external=True)
        # HTML version using the template content directly
        message.html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Token Purchase Confirmation - SEO Dada</title>
</head>
<body style="font-family: system-ui, -apple-system, sans-serif; line-height: 1.6; color: #1e293b; margin: 0; padding: 0; background-color: #f8fafc;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #273879 0%, #0f74b2 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
            <img src="{logo_url}" alt="SEO Dada" style="max-height: 60px; width: auto; margin-bottom: 10px;" />
            <p style="color: rgba(255,255,255,0.9); margin: 8px 0 0 0; font-size: 14px;">Token Purchase Confirmation</p>
        </div>

        <div style="background-color: #ffffff; padding: 40px 35px; border-radius: 0 0 12px 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.07);">
            <h2 style="background: linear-gradient(135deg, #059669 0%, #10b981 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-bottom: 20px; font-size: 24px;">🎉 Token Purchase Successful!</h2>

            <p style="margin-bottom: 20px; color: #1e293b;">Hello <strong style="color: #273879;">{user.name}</strong>,</p>

            <p style="margin-bottom: 25px; color: #64748b; line-height: 1.7;">Great news! Your token purchase has been processed successfully. You now have <strong style="color: #059669;">{token_purchase.token_count} additional tokens</strong> available in your account.</p>

            <div style="background: linear-gradient(to right, rgba(16, 185, 129, 0.05), rgba(16, 185, 129, 0.02)); padding: 25px; border-radius: 10px; border-left: 4px solid #10b981; margin: 25px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                <h3 style="color: #047857; margin: 0 0 20px 0; font-size: 18px;">Purchase Details</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 10px 0; font-weight: 600; color: #475569; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">Tokens Purchased:</td>
                        <td style="padding: 10px 0; color: #059669; font-weight: bold; text-align: right; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">{token_purchase.token_count} tokens</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; font-weight: 600; color: #475569; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">Amount Paid:</td>
                        <td style="padding: 10px 0; color: #1e293b; font-weight: 600; text-align: right; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">₹{token_purchase.total_amount}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; font-weight: 600; color: #475569; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">Invoice Number:</td>
                        <td style="padding: 10px 0; color: #1e293b; text-align: right; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">{token_purchase.invoice_number}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; font-weight: 600; color: #475569; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">Purchase Date:</td>
                        <td style="padding: 10px 0; color: #1e293b; text-align: right; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">{token_purchase.created_at.strftime('%d %b %Y, %H:%M UTC')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; font-weight: 600; color: #475569;">Order ID:</td>
                        <td style="padding: 10px 0; color: #64748b; font-size: 12px; text-align: right;">{token_purchase.razorpay_order_id}</td>
                    </tr>
                </table>
            </div>

            <div style="margin-top: 35px; padding-top: 25px; border-top: 1px solid #e2e8f0; text-align: center; color: #64748b; font-size: 13px;">
                <p style="margin: 0; color: #1e293b;">Thanks for choosing SEO Dada!<br><strong style="background: linear-gradient(135deg, #273879 0%, #0f74b2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;">The SEO Dada Team</strong></p>
                <p style="margin: 12px 0 0 0;">Need help? Contact us at <a href="mailto:payment@seodada.com" style="color: #0f74b2; text-decoration: none;">payment@seodada.com</a></p>
            </div>
        </div>

        <div style="text-align: center; padding: 20px; color: #94a3b8; font-size: 12px;">
            <p style="margin: 0;">&copy; {datetime.now().year} SEO Dada. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
"""

        # Save original support credentials
        original_username = current_app.config['MAIL_USERNAME']
        original_password = current_app.config['MAIL_PASSWORD']

        try:
            # Switch to payment SMTP credentials
            current_app.config['MAIL_USERNAME'] = current_app.config.get('MAIL_PAYMENT_USERNAME', sender_email)
            current_app.config['MAIL_PASSWORD'] = current_app.config.get('MAIL_PAYMENT_PASSWORD')
            mail.init_app(current_app._get_current_object())  # Reinitialize mail with new credentials

            mail.send(message)
        finally:
            # Always restore support SMTP credentials
            current_app.config['MAIL_USERNAME'] = original_username
            current_app.config['MAIL_PASSWORD'] = original_password
            mail.init_app(current_app._get_current_object())  # Reinitialize mail with support credentials

        # Log successful email
        EmailLog.log_email(
            recipient_email=user.company_email,
            recipient_name=user.name,
            email_type='token_purchase',
            subject=subject,
            user_id=user.id,
            status='sent',
            metadata={
                'token_count': token_purchase.token_count,
                'amount': token_purchase.total_amount,
                'invoice_number': token_purchase.invoice_number,
                'order_id': token_purchase.razorpay_order_id
            }
        )

        current_app.logger.info(f"Token purchase confirmation email sent to {user.company_email}")

    except Exception as e:
        # Log failed email
        EmailLog.log_email(
            recipient_email=user.company_email,
            recipient_name=user.name,
            email_type='token_purchase',
            subject=subject,
            user_id=user.id,
            status='failed',
            error_message=str(e),
            metadata={
                'token_count': token_purchase.token_count,
                'amount': token_purchase.total_amount,
                'order_id': token_purchase.razorpay_order_id
            }
        )

        current_app.logger.error(f"Failed to send token purchase confirmation email: {str(e)}")
        raise


def check_email_configuration():
    """Check if email configuration is properly set up"""
    required_config = [
        'MAIL_SERVER',
        'MAIL_PORT',
        'MAIL_USERNAME',
        'MAIL_PASSWORD'
    ]

    missing_config = []
    for config_key in required_config:
        if not current_app.config.get(config_key):
            missing_config.append(config_key)

    if missing_config:
        current_app.logger.error(f"Missing email configuration: {missing_config}")
        return False, missing_config

    return True, []


def send_subscription_expiry_warning_email(user, subscription, subscribed_user):
    """Send subscription expiry warning email with logging"""
    try:
        current_app.logger.info(f"Starting to send expiry warning email to {user.company_email}")

        # Calculate days and hours remaining
        now = datetime.now(UTC)
        if subscribed_user.end_date.tzinfo is None:
            end_date = subscribed_user.end_date.replace(tzinfo=UTC)
        else:
            end_date = subscribed_user.end_date

        time_remaining = end_date - now
        days_remaining = time_remaining.days
        hours_remaining = int(time_remaining.total_seconds() / 3600)

        # Use days if more than 1 day, otherwise use hours
        if days_remaining >= 1:
            time_display = f"{days_remaining} day{'s' if days_remaining != 1 else ''}"
            subject = f"⚠️ Your {subscription.plan} subscription expires in {days_remaining} day{'s' if days_remaining != 1 else ''}"
        else:
            time_display = f"{hours_remaining} hour{'s' if hours_remaining != 1 else ''}"
            subject = f"⚠️ Your {subscription.plan} subscription expires in {hours_remaining} hour{'s' if hours_remaining != 1 else ''}"
        # Use payment@seodada.com for subscription-related emails
        sender_email = 'payment@seodada.com'

        # Use logo from static images folder - use SITE_URL config for scheduled jobs (no request context)
        site_url = current_app.config.get('SITE_URL', 'https://seodada.com')
        logo_url = f"{site_url}/static/images/seodada.png"

        current_app.logger.info(f"Email subject: {subject}")
        current_app.logger.info(f"Sending from: {sender_email}")
        current_app.logger.info(f"Sending to: {user.company_email}")

        # Text version for email clients that don't support HTML
        body_text = f"""Dear {user.name},

This is a reminder that your {subscription.plan} subscription will expire soon.

Subscription Details:
- Plan: {subscription.plan}
- Expires: {end_date.strftime('%d %b %Y at %H:%M UTC')}
- Time Remaining: {time_display}

To continue using our services without interruption, please renew your subscription.

Auto-renewal Status: {'Enabled' if subscribed_user.is_auto_renew else 'Disabled'}

If you have any questions or need assistance, please contact our support team.

Thank you for choosing SEO Dada!

Best regards,
The SEO Dada Team
"""

        body_html = f'''
        <!DOCTYPE html>
        <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Subscription Expiry Warning</title>
            </head>
            <body style="font-family: system-ui, -apple-system, sans-serif; line-height: 1.6; color: #1e293b; margin: 0; padding: 0; background-color: #f8fafc;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <div style="background: linear-gradient(135deg, #273879 0%, #0f74b2 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
                        <img src="{logo_url}" alt="SEO Dada" style="max-height: 60px; width: auto; margin-bottom: 10px;" />
                        <p style="color: rgba(255,255,255,0.9); margin: 8px 0 0 0; font-size: 14px;">Professional SEO Analysis Platform</p>
                    </div>

                    <div style="background-color: #ffffff; padding: 40px 35px; border-radius: 0 0 12px 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.07);">

                        <div style="text-align: center; margin-bottom: 25px;">
                            <div style="background-color: #fef3c7; border: 2px solid #f59e0b; border-radius: 8px; padding: 15px; margin-bottom: 20px;">
                                <h2 style="color: #92400e; margin: 0 0 10px 0; font-size: 18px;">⚠️ Subscription Expiring Soon</h2>
                                <p style="color: #92400e; margin: 0; font-weight: 600;">Your subscription expires in {time_display}</p>
                            </div>
                        </div>

                        <p style="margin-bottom: 20px;">Hello <strong>{user.name}</strong>,</p>

                        <p style="margin-bottom: 25px;">This is a friendly reminder that your <strong>{subscription.plan}</strong> subscription will expire soon. To continue enjoying uninterrupted access to our SEO Dada tools, please renew your subscription.</p>

                        <div style="margin-top: 35px; padding-top: 25px; border-top: 1px solid #e2e8f0; text-align: center; color: #64748b; font-size: 13px;">
                            <p style="margin: 0; color: #1e293b;">Best regards,<br><strong style="background: linear-gradient(135deg, #273879 0%, #0f74b2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;">SEO Dada Team</strong></p>
                            <p style="margin: 12px 0 0 0;">Need help? Contact us at <a href="mailto:support@seodada.com" style="color: #0f74b2; text-decoration: none;">support@seodada.com</a></p>
                        </div>
                    </div>

                    <div style="text-align: center; padding: 20px; color: #94a3b8; font-size: 12px;">
                        <p style="margin: 0;">&copy; {datetime.now().year} SEO Dada. All rights reserved.</p>
                    </div>
                </div>
            </body>
        </html>
        '''

        # Send via SMTP using Flask-Mail
        current_app.logger.info(f"Sending email via SMTP from {sender_email}...")
        message = Message(subject, sender=sender_email, recipients=[user.company_email])
        message.body = body_text
        message.html = body_html

        # Save original support credentials
        original_username = current_app.config['MAIL_USERNAME']
        original_password = current_app.config['MAIL_PASSWORD']

        try:
            # Switch to payment SMTP credentials
            current_app.config['MAIL_USERNAME'] = current_app.config.get('MAIL_PAYMENT_USERNAME', sender_email)
            current_app.config['MAIL_PASSWORD'] = current_app.config.get('MAIL_PAYMENT_PASSWORD')
            mail.init_app(current_app._get_current_object())  # Reinitialize mail with new credentials

            mail.send(message)
        finally:
            # Always restore support SMTP credentials
            current_app.config['MAIL_USERNAME'] = original_username
            current_app.config['MAIL_PASSWORD'] = original_password
            mail.init_app(current_app._get_current_object())  # Reinitialize mail with support credentials
        current_app.logger.info(f"Email sent successfully via SMTP")

        # Log successful email
        EmailLog.log_email(
            recipient_email=user.company_email,
            recipient_name=user.name,
            email_type='subscription_expiry',
            subject=subject,
            user_id=user.id,
            status='sent',
            metadata={
                'subscription_plan': subscription.plan,
                'hours_remaining': hours_remaining,
                'auto_renew': subscribed_user.is_auto_renew,
                'expiry_date': end_date.isoformat()
            }
        )

        current_app.logger.info(f"✓ Subscription expiry warning email sent successfully to {user.company_email}")
        return True

    except Exception as e:
        error_details = f"{type(e).__name__}: {str(e)}"
        current_app.logger.error(f"✗ Failed to send subscription expiry warning email to {user.company_email}")
        current_app.logger.error(f"Error details: {error_details}")
        current_app.logger.error(f"Traceback: {traceback.format_exc()}")

        # Log failed email
        try:
            EmailLog.log_email(
                recipient_email=user.company_email if user else 'unknown',
                recipient_name=user.name if user else 'Unknown',
                email_type='subscription_expiry',
                subject=subject if 'subject' in locals() else 'Subscription Expiry Warning',
                user_id=user.id if user else None,
                status='failed',
                error_message=error_details,
                metadata={
                    'subscription_plan': subscription.plan if subscription else None,
                    'auto_renew': subscribed_user.is_auto_renew if subscribed_user else None
                }
            )
        except Exception as log_error:
            current_app.logger.error(f"Failed to log email error: {str(log_error)}")

        raise


def send_payment_confirmation_email(user, payment, subscription):
    """Send payment confirmation email with invoice PDF attachment"""
    try:
        subject = f"Payment Confirmation - {subscription.plan} Subscription"
        # Use payment@seodada.com for payment-related emails
        sender_email = 'payment@seodada.com'

        # Calculate subscription end date
        start_date = datetime.now(UTC)
        end_date = start_date + timedelta(days=subscription.days)

        # Use logo from static images folder
        logo_url = url_for('static', filename='images/seodada.png', _external=True)
        # Plain text version
        body_text = f"""Dear {user.name},

Thank you for your payment of {payment.total_amount} {payment.currency} for the {subscription.plan} subscription plan.

Payment Details:
- Order ID: {payment.razorpay_order_id}
- Payment ID: {payment.razorpay_payment_id}
- Invoice Number: {payment.invoice_number}
- Amount: {payment.total_amount} {payment.currency}
- Date: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC

Subscription Details:
- Plan: {subscription.plan}
- Start Date: {start_date.strftime('%Y-%m-%d')}
- End Date: {end_date.strftime('%Y-%m-%d')}
- Daily Usage Limit: {subscription.usage_per_day} operations

Please find your invoice attached to this email.

Thank you for choosing our service!

Best regards,
The SEO Dada Team
"""

        # HTML version
        body_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Confirmation - SEO Dada</title>
</head>
<body style="font-family: system-ui, -apple-system, sans-serif; line-height: 1.6; color: #1e293b; margin: 0; padding: 0; background-color: #f8fafc;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #273879 0%, #0f74b2 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
            <img src="{logo_url}" alt="SEO Dada" style="max-height: 60px; width: auto; margin-bottom: 10px;" />
            <p style="color: rgba(255,255,255,0.9); margin: 8px 0 0 0; font-size: 14px;">Payment Confirmation</p>
        </div>

        <div style="background-color: #ffffff; padding: 40px 35px; border-radius: 0 0 12px 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.07);">
            <h2 style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-bottom: 20px; font-size: 24px;">✅ Payment Successful!</h2>

            <p style="margin-bottom: 20px; color: #1e293b;">Dear <strong style="color: #273879;">{user.name}</strong>,</p>

            <p style="margin-bottom: 25px; color: #64748b; line-height: 1.7;">Thank you for your payment of <strong style="color: #059669;">₹{payment.total_amount}</strong> for the <strong>{subscription.plan}</strong> subscription plan.</p>

            <div style="background: linear-gradient(to right, rgba(15, 116, 178, 0.05), rgba(39, 56, 121, 0.05)); padding: 25px; border-radius: 10px; border-left: 4px solid #0f74b2; margin: 25px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                <h3 style="color: #273879; margin: 0 0 20px 0; font-size: 18px;">Payment Details</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 10px 0; font-weight: 600; color: #475569; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">Order ID:</td>
                        <td style="padding: 10px 0; color: #1e293b; text-align: right; border-bottom: 1px solid rgba(226, 232, 240, 0.5); font-size: 12px;">{payment.razorpay_order_id}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; font-weight: 600; color: #475569; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">Payment ID:</td>
                        <td style="padding: 10px 0; color: #1e293b; text-align: right; border-bottom: 1px solid rgba(226, 232, 240, 0.5); font-size: 12px;">{payment.razorpay_payment_id}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; font-weight: 600; color: #475569; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">Invoice Number:</td>
                        <td style="padding: 10px 0; color: #1e293b; text-align: right; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">{payment.invoice_number}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; font-weight: 600; color: #475569; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">Amount Paid:</td>
                        <td style="padding: 10px 0; color: #059669; font-weight: bold; text-align: right; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">₹{payment.total_amount}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; font-weight: 600; color: #475569;">Date:</td>
                        <td style="padding: 10px 0; color: #1e293b; text-align: right;">{datetime.now(UTC).strftime('%d %b %Y, %H:%M UTC')}</td>
                    </tr>
                </table>
            </div>

            <div style="background: linear-gradient(to right, rgba(16, 185, 129, 0.05), rgba(16, 185, 129, 0.02)); padding: 25px; border-radius: 10px; border-left: 4px solid #10b981; margin: 25px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                <h3 style="color: #047857; margin: 0 0 20px 0; font-size: 18px;">Subscription Details</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 10px 0; font-weight: 600; color: #475569; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">Plan:</td>
                        <td style="padding: 10px 0; color: #1e293b; font-weight: 600; text-align: right; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">{subscription.plan}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; font-weight: 600; color: #475569; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">Start Date:</td>
                        <td style="padding: 10px 0; color: #1e293b; text-align: right; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">{start_date.strftime('%d %b %Y')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; font-weight: 600; color: #475569; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">End Date:</td>
                        <td style="padding: 10px 0; color: #1e293b; text-align: right; border-bottom: 1px solid rgba(226, 232, 240, 0.5);">{end_date.strftime('%d %b %Y')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; font-weight: 600; color: #475569;">Daily Usage Limit:</td>
                        <td style="padding: 10px 0; color: #1e293b; text-align: right;">{subscription.usage_per_day} operations</td>
                    </tr>
                </table>
            </div>

            <div style="background-color: #fef3c7; padding: 15px; border-radius: 8px; border-left: 3px solid #f59e0b; margin: 20px 0;">
                <p style="margin: 0; color: #92400e; font-size: 14px;"><strong>📎 Invoice Attached:</strong> Your invoice PDF is attached to this email for your records.</p>
            </div>

            <div style="margin-top: 35px; padding-top: 25px; border-top: 1px solid #e2e8f0; text-align: center; color: #64748b; font-size: 13px;">
                <p style="margin: 0; color: #1e293b;">Thank you for choosing our service!<br><strong style="background: linear-gradient(135deg, #273879 0%, #0f74b2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;">The SEO Dada Team</strong></p>
                <p style="margin: 12px 0 0 0;">Need help? Contact us at <a href="mailto:payment@seodada.com" style="color: #0f74b2; text-decoration: none;">payment@seodada.com</a></p>
            </div>
        </div>

        <div style="text-align: center; padding: 20px; color: #94a3b8; font-size: 12px;">
            <p style="margin: 0;">&copy; {datetime.now().year} SEO Dada. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
"""

        # Send via SMTP using Flask-Mail
        # Configure sender based on email type (payment emails from payment@seodada.com)
        message = Message(subject, sender=sender_email, recipients=[user.company_email])
        message.body = body_text
        message.html = body_html

        # Generate and attach invoice PDF
        from app import generate_invoice_pdf_for_email
        invoice_pdf = generate_invoice_pdf_for_email(payment, subscription, user)
        if invoice_pdf:
            message.attach(
                filename=f"Invoice_{payment.invoice_number}.pdf",
                content_type="application/pdf",
                data=invoice_pdf.read()
            )
            current_app.logger.info(f"Invoice PDF attached to payment confirmation email")

        # Save original support credentials
        original_username = current_app.config['MAIL_USERNAME']
        original_password = current_app.config['MAIL_PASSWORD']

        try:
            # Switch to payment SMTP credentials
            current_app.config['MAIL_USERNAME'] = current_app.config.get('MAIL_PAYMENT_USERNAME', sender_email)
            current_app.config['MAIL_PASSWORD'] = current_app.config.get('MAIL_PAYMENT_PASSWORD')
            mail.init_app(current_app._get_current_object())  # Reinitialize mail with new credentials

            mail.send(message)
        finally:
            # Always restore support SMTP credentials
            current_app.config['MAIL_USERNAME'] = original_username
            current_app.config['MAIL_PASSWORD'] = original_password
            mail.init_app(current_app._get_current_object())  # Reinitialize mail with support credentials

        # Log successful email
        EmailLog.log_email(
            recipient_email=user.company_email,
            recipient_name=user.name,
            email_type='payment_confirmation',
            subject=subject,
            user_id=user.id,
            status='sent',
            metadata={
                'payment_id': payment.razorpay_payment_id,
                'order_id': payment.razorpay_order_id,
                'amount': payment.total_amount,
                'subscription_plan': subscription.plan,
                'invoice_number': payment.invoice_number
            }
        )

        current_app.logger.info(f"Payment confirmation email sent to {user.company_email}")

    except Exception as e:
        # Log failed email
        EmailLog.log_email(
            recipient_email=user.company_email,
            recipient_name=user.name,
            email_type='payment_confirmation',
            subject=subject,
            user_id=user.id,
            status='failed',
            error_message=str(e),
            metadata={
                'payment_id': payment.razorpay_payment_id if hasattr(payment, 'razorpay_payment_id') else None,
                'order_id': payment.razorpay_order_id if hasattr(payment, 'razorpay_order_id') else None,
                'amount': payment.total_amount if hasattr(payment, 'total_amount') else None,
                'subscription_plan': subscription.plan if subscription else None
            }
        )

        current_app.logger.error(f"Failed to send payment confirmation email: {str(e)}")
        raise


def check_and_notify_expiring_subscriptions():
    """
    Check for subscriptions expiring within 7 days and send notification emails
    Returns the number of notifications sent
    """
    try:
        now = datetime.now(UTC)
        seven_days_later = now + timedelta(days=7)

        # Find subscriptions expiring within 7 days
        expiring_subscriptions = (
            db.session.query(SubscribedUser, User, Subscription)
            .join(User, SubscribedUser.U_ID == User.id)
            .join(Subscription, SubscribedUser.S_ID == Subscription.S_ID)
            .filter(
                SubscribedUser._is_active == True,  # Only active subscriptions
                SubscribedUser.end_date > now,  # Not already expired
                SubscribedUser.end_date <= seven_days_later  # Expiring within 7 days
            )
            .all()
        )

        notifications_sent = 0

        for subscribed_user, user, subscription in expiring_subscriptions:
            try:
                # Check if we already sent a notification today for this subscription
                # (to avoid spam if the job runs multiple times)
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

                # Check EmailLog to see if we already sent an expiry notification today
                existing_notification = EmailLog.query.filter(
                    EmailLog.recipient_email == user.company_email,
                    EmailLog.email_type == 'subscription_expiry',
                    EmailLog.sent_at >= today_start,
                    EmailLog.status == 'sent'
                ).first()

                if existing_notification:
                    current_app.logger.info(f"Skipping notification to {user.company_email} - already sent today")
                    continue

                # Send notification email
                send_subscription_expiry_warning_email(user, subscription, subscribed_user)
                notifications_sent += 1

                current_app.logger.info(f"Sent expiry notification to {user.company_email} for {subscription.plan} subscription expiring at {subscribed_user.end_date}")

            except Exception as e:
                current_app.logger.error(f"Failed to send expiry notification to {user.company_email}: {str(e)}")
                continue

        current_app.logger.info(f"Subscription expiry check completed. Sent {notifications_sent} notifications.")
        return notifications_sent

    except Exception as e:
        current_app.logger.error(f"Error in check_and_notify_expiring_subscriptions: {str(e)}")
        return 0
