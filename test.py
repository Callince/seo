#!/usr/bin/env python3
"""
Test Support Email Configuration
This script tests if support@seodada.com can send emails via SMTP
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# Email Configuration
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SUPPORT_EMAIL = "support@seodada.com"
SUPPORT_PASSWORD = "okwf chfs gppu fztj"  # Updated password

def test_support_email(recipient_email):
    """
    Test sending email from support@seodada.com

    Args:
        recipient_email: Email address to send test email to
    """

    print("=" * 60)
    print("Testing Support Email Configuration")
    print("=" * 60)
    print(f"From: {SUPPORT_EMAIL}")
    print(f"To: {recipient_email}")
    print(f"SMTP Server: {SMTP_SERVER}:{SMTP_PORT}")
    print("=" * 60)

    # Create message
    message = MIMEMultipart('alternative')
    message['Subject'] = "Test Email from SEO Dada Support"
    message['From'] = SUPPORT_EMAIL
    message['To'] = recipient_email

    # Plain text version
    text_content = f"""
Hello,

This is a test email from SEO Dada Support.

Test Details:
- Sent from: {SUPPORT_EMAIL}
- Sent to: {recipient_email}
- Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- SMTP Server: {SMTP_SERVER}
- SMTP Port: {SMTP_PORT}

If you received this email, the support email configuration is working correctly!

Best regards,
SEO Dada Support Team
    """

    # HTML version
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Test Email from SEO Dada Support</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background-color: #4f46e5; color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
        <h1 style="margin: 0;">SEO Dada</h1>
        <p style="margin: 5px 0 0 0;">Support Email Test</p>
    </div>

    <div style="background-color: #ffffff; padding: 30px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 10px 10px;">
        <h2 style="color: #4f46e5;">✅ Test Email Successful!</h2>

        <p>Hello,</p>

        <p>This is a test email from SEO Dada Support. If you're reading this, the email configuration is working correctly!</p>

        <div style="background-color: #f0fdf4; padding: 15px; border-radius: 8px; border-left: 4px solid #059669; margin: 20px 0;">
            <h3 style="color: #047857; margin: 0 0 10px 0;">Test Details</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 5px 0; font-weight: 600; color: #374151;">Sent from:</td>
                    <td style="padding: 5px 0; color: #059669;">{SUPPORT_EMAIL}</td>
                </tr>
                <tr>
                    <td style="padding: 5px 0; font-weight: 600; color: #374151;">Sent to:</td>
                    <td style="padding: 5px 0;">{recipient_email}</td>
                </tr>
                <tr>
                    <td style="padding: 5px 0; font-weight: 600; color: #374151;">Date/Time:</td>
                    <td style="padding: 5px 0;">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</td>
                </tr>
                <tr>
                    <td style="padding: 5px 0; font-weight: 600; color: #374151;">SMTP Server:</td>
                    <td style="padding: 5px 0;">{SMTP_SERVER}:{SMTP_PORT}</td>
                </tr>
            </table>
        </div>

        <p>Best regards,<br><strong>SEO Dada Support Team</strong></p>
        <p style="color: #6b7280; font-size: 12px; margin-top: 30px;">Need help? Contact us at {SUPPORT_EMAIL}</p>
    </div>
</body>
</html>
    """

    # Attach both versions
    part1 = MIMEText(text_content, 'plain')
    part2 = MIMEText(html_content, 'html')
    message.attach(part1)
    message.attach(part2)

    try:
        print("\n[1/4] Connecting to SMTP server...")
        # Create SMTP session
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)

        print("[2/4] Starting TLS encryption...")
        # Enable TLS encryption
        server.starttls()

        print("[3/4] Logging in to support email account...")
        # Login to support email
        server.login(SUPPORT_EMAIL, SUPPORT_PASSWORD)

        print("[4/4] Sending email...")
        # Send email
        server.send_message(message)

        print("\n✅ SUCCESS! Email sent successfully!")
        print(f"✅ Check {recipient_email} for the test email")

        # Close connection
        server.quit()

        print("\n" + "=" * 60)
        print("Test completed successfully!")
        print("=" * 60)

        return True

    except smtplib.SMTPAuthenticationError as e:
        print("\n❌ AUTHENTICATION FAILED!")
        print(f"Error: {e}")
        print("\nPossible causes:")
        print("1. Wrong email or password")
        print("2. App password not enabled for support@seodada.com")
        print("3. 2-Step Verification not enabled")
        print("\nSolution:")
        print("1. Go to: https://myaccount.google.com/apppasswords")
        print("2. Sign in with support@seodada.com")
        print("3. Generate a new app password")
        print("4. Update MAIL_PASSWORD in .env file")
        return False

    except smtplib.SMTPException as e:
        print("\n❌ SMTP ERROR!")
        print(f"Error: {e}")
        return False

    except Exception as e:
        print("\n❌ UNEXPECTED ERROR!")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_payment_email(recipient_email):
    """
    Test sending email from payment@seodada.com

    Args:
        recipient_email: Email address to send test email to
    """

    PAYMENT_EMAIL = "payment@seodada.com"
    PAYMENT_PASSWORD = "axdj kwgf kcfh qlfj"

    print("\n" + "=" * 60)
    print("Testing Payment Email Configuration")
    print("=" * 60)
    print(f"From: {PAYMENT_EMAIL}")
    print(f"To: {recipient_email}")
    print("=" * 60)

    # Create message
    message = MIMEMultipart('alternative')
    message['Subject'] = "Test Email from SEO Dada Payments"
    message['From'] = PAYMENT_EMAIL
    message['To'] = recipient_email

    # Plain text version
    text_content = f"""
Hello,

This is a test email from SEO Dada Payments.

Test Details:
- Sent from: {PAYMENT_EMAIL}
- Sent to: {recipient_email}
- Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

If you received this email, the payment email configuration is working correctly!

Best regards,
SEO Dada Payments Team
    """

    # HTML version
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Test Email from SEO Dada Payments</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background-color: #059669; color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
        <h1 style="margin: 0;">SEO Dada</h1>
        <p style="margin: 5px 0 0 0;">Payment Email Test</p>
    </div>

    <div style="background-color: #ffffff; padding: 30px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 10px 10px;">
        <h2 style="color: #059669;">✅ Payment Email Test Successful!</h2>

        <p>Hello,</p>

        <p>This is a test email from SEO Dada Payments. If you're reading this, the payment email configuration is working correctly!</p>

        <div style="background-color: #f0fdf4; padding: 15px; border-radius: 8px; border-left: 4px solid #059669; margin: 20px 0;">
            <h3 style="color: #047857; margin: 0 0 10px 0;">Test Details</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 5px 0; font-weight: 600; color: #374151;">Sent from:</td>
                    <td style="padding: 5px 0; color: #059669;">{PAYMENT_EMAIL}</td>
                </tr>
                <tr>
                    <td style="padding: 5px 0; font-weight: 600; color: #374151;">Sent to:</td>
                    <td style="padding: 5px 0;">{recipient_email}</td>
                </tr>
                <tr>
                    <td style="padding: 5px 0; font-weight: 600; color: #374151;">Date/Time:</td>
                    <td style="padding: 5px 0;">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</td>
                </tr>
            </table>
        </div>

        <p>Best regards,<br><strong>SEO Dada Payments Team</strong></p>
        <p style="color: #6b7280; font-size: 12px; margin-top: 30px;">Need help? Contact us at support@seodada.com</p>
    </div>
</body>
</html>
    """

    # Attach both versions
    part1 = MIMEText(text_content, 'plain')
    part2 = MIMEText(html_content, 'html')
    message.attach(part1)
    message.attach(part2)

    try:
        print("\n[1/4] Connecting to SMTP server...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)

        print("[2/4] Starting TLS encryption...")
        server.starttls()

        print("[3/4] Logging in to payment email account...")
        server.login(PAYMENT_EMAIL, PAYMENT_PASSWORD)

        print("[4/4] Sending email...")
        server.send_message(message)

        print("\n✅ SUCCESS! Payment email sent successfully!")
        print(f"✅ Check {recipient_email} for the test email")

        server.quit()

        print("\n" + "=" * 60)
        print("Payment email test completed successfully!")
        print("=" * 60)

        return True

    except Exception as e:
        print("\n❌ PAYMENT EMAIL ERROR!")
        print(f"Error: {e}")
        return False


if __name__ == "__main__":
    print("\n")
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║          SEO Dada Email Configuration Test Tool          ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    print()

    # Get recipient email
    recipient = input("Enter recipient email address to test: ").strip()

    if not recipient or '@' not in recipient:
        print("\n❌ Invalid email address!")
        exit(1)

    print("\nSelect which email to test:")
    print("1. Support email (support@seodada.com)")
    print("2. Payment email (payment@seodada.com)")
    print("3. Both emails")

    choice = input("\nEnter your choice (1/2/3): ").strip()

    print("\n")

    if choice == "1":
        test_support_email(recipient)
    elif choice == "2":
        test_payment_email(recipient)
    elif choice == "3":
        # Test support email first
        support_result = test_support_email(recipient)

        # Wait a bit before testing payment email
        import time
        time.sleep(2)

        # Test payment email
        payment_result = test_payment_email(recipient)

        # Summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"Support Email: {'✅ PASSED' if support_result else '❌ FAILED'}")
        print(f"Payment Email: {'✅ PASSED' if payment_result else '❌ FAILED'}")
        print("=" * 60)
    else:
        print("\n❌ Invalid choice!")
        exit(1)

    print("\nTest completed!\n")
