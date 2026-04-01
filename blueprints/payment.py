import os
import json
import logging
import traceback
import uuid
import hmac
import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, send_file, current_app
from flask_login import current_user
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from extensions import db, csrf, razorpay_client
from models import (User, Subscription, SubscribedUser, SubscriptionHistory, Payment, InvoiceAddress,
                    TokenPurchase, UserToken, UsageLog)

UTC = timezone.utc

payment_bp = Blueprint('payment', __name__)


# ----------------------
# Helper / Utility Functions
# ----------------------

def login_required(f):
    """Import login_required from blueprints.auth at call time to avoid circular imports."""
    from blueprints.auth import login_required as _login_required
    return _login_required(f)


# Use a lazy wrapper so the decorator works at import time
def _lazy_login_required(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash("You need to log in first.", "warning")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapper


def validate_razorpay_order(subscription, amount, payment):
    """
    Validate Razorpay order details

    :param subscription: Subscription object
    :param amount: Amount in paisa
    :param payment: Payment object
    :return: Boolean indicating if order is valid
    """
    try:
        expected_amount = int(payment.total_amount * 100)
        return amount == expected_amount
    except Exception as e:
        current_app.logger.error(f"Order validation error: {str(e)}")
        return False


def verify_razorpay_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature, razorpay_key_secret):
    """
    Verify Razorpay payment signature using HMAC SHA-256

    Args:
        razorpay_order_id (str): Order ID from Razorpay
        razorpay_payment_id (str): Payment ID from Razorpay
        razorpay_signature (str): Signature from Razorpay
        razorpay_key_secret (str): Razorpay key secret

    Returns:
        bool: True if signature is valid, False otherwise
    """
    try:
        # Create signature payload
        payload = f"{razorpay_order_id}|{razorpay_payment_id}"

        # Generate expected signature
        generated_signature = hmac.new(
            razorpay_key_secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Use constant-time comparison to prevent timing attacks
        return hmac.compare_digest(generated_signature, razorpay_signature)

    except Exception as e:
        current_app.logger.error(f"Signature verification error: {str(e)}")
        return False


def generate_unique_invoice_number():
    """
    Generate a unique invoice number
    """
    timestamp = datetime.now(UTC).strftime("%y%m%d")
    unique_id = str(uuid.uuid4().hex)[:8]
    return f"INV-{timestamp}-{unique_id}"


def create_or_update_subscription(payment):
    """
    Create or update subscription based on payment
    """
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
    """
    Create invoice address for payment if not exists
    """
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


def _process_subscription_change(user_id, current_subscription, new_plan_id, is_upgrade, credit_applied=0):
    """Process a subscription change (upgrade or downgrade)"""
    try:
        # Get the new subscription plan
        new_plan = Subscription.query.get(new_plan_id)

        # Deactivate current subscription
        current_subscription.is_active = False

        # Calculate new subscription dates
        start_date = datetime.now(UTC)

        if is_upgrade:
            # For upgrades, standard plan duration
            end_date = start_date + timedelta(days=new_plan.days)
        else:
            # For downgrades, calculate additional days from remaining credit
            new_plan_daily_price = new_plan.price / new_plan.days if new_plan.days > 0 else 0
            additional_days = int(credit_applied / new_plan_daily_price) if new_plan_daily_price > 0 else 0
            end_date = start_date + timedelta(days=new_plan.days + additional_days)

        # Create NEW active subscription
        new_subscription = SubscribedUser(
            U_ID=user_id,
            S_ID=new_plan_id,
            start_date=start_date,
            end_date=end_date,
            is_auto_renew=current_subscription.is_auto_renew,
            current_usage=0,
            last_usage_reset=start_date
        )

        # Add the new subscription
        db.session.add(new_subscription)

        # Log subscription change history
        history_entry = SubscriptionHistory(
            U_ID=user_id,
            S_ID=new_plan_id,
            action='upgrade' if is_upgrade else 'downgrade',
            previous_S_ID=current_subscription.S_ID,
            created_at=datetime.now(UTC)
        )
        db.session.add(history_entry)

        # Commit changes
        db.session.commit()

        return True

    except Exception as e:
        # Rollback in case of any errors
        db.session.rollback()
        current_app.logger.error(f"Subscription change error: {str(e)}")
        return False


# ----------------------
# PDF Generation Functions
# ----------------------

def generate_invoice_pdf(payment):
    """
    Generate a modern, visually aesthetic PDF invoice for a specific payment

    :param payment: Payment model instance
    :return: BytesIO buffer containing the PDF
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch, mm
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
    from num2words import num2words

    # Define brand colors to match the logo
    brand_color = colors.Color(0.73, 0.20, 0.04)  # Rust/orange color from logo
    secondary_color = colors.Color(0.95, 0.95, 0.95)  # Light gray for backgrounds
    text_color = colors.Color(0.25, 0.25, 0.25)  # Dark gray for text

    # Prepare buffer and document with reduced margins
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=12*mm,
        rightMargin=12*mm,
        topMargin=12*mm,
        bottomMargin=12*mm
    )
    width, height = A4

    # Create custom styles
    brand_title_style = ParagraphStyle(
        name='BrandTitleCustom',
        fontName='Helvetica-Bold',
        fontSize=16,
        textColor=brand_color,
        spaceAfter=3,
        alignment=TA_CENTER
    )

    company_name_style = ParagraphStyle(
        name='CompanyNameCustom',
        fontName='Helvetica-Bold',
        fontSize=12,
        textColor=text_color,
        spaceAfter=2
    )

    invoice_title_style = ParagraphStyle(
        name='InvoiceTitleCustom',
        fontName='Helvetica-Bold',
        fontSize=16,
        alignment=TA_RIGHT,
        textColor=brand_color,
        spaceAfter=4
    )

    section_title_style = ParagraphStyle(
        name='SectionTitleCustom',
        fontName='Helvetica-Bold',
        fontSize=9,
        textColor=text_color,
        spaceAfter=2
    )

    normal_style = ParagraphStyle(
        name='NormalCustom',
        fontName='Helvetica',
        fontSize=8,
        textColor=text_color,
        leading=10
    )

    right_aligned_style = ParagraphStyle(
        name='RightAlignedCustom',
        fontName='Helvetica',
        fontSize=9,
        alignment=TA_RIGHT,
        textColor=text_color
    )

    center_aligned_style = ParagraphStyle(
        name='CenterAlignedCustom',
        fontName='Helvetica',
        fontSize=9,
        alignment=TA_CENTER,
        textColor=text_color
    )

    # Prepare elements
    elements = []

    # Logo and Title side by side
    logo_path = os.path.join(current_app.root_path, 'assert', '4d-logo.webp')

    try:
        logo = Image(logo_path, width=1.5*inch, height=0.75*inch)
        header_data = [[
            logo,
            Paragraph("TAX INVOICE", invoice_title_style)
        ]]

        header_table = Table(header_data, colWidths=[doc.width/2, doc.width/2])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(header_table)
    except:
        # Fallback if logo not found
        elements.append(Paragraph("TAX INVOICE", invoice_title_style))

    elements.append(Spacer(1, 5))

    # Company Details Section
    company_details = [
        [Paragraph("<b>Company Name:</b>", section_title_style)],
        [Paragraph("M/s. Fourth Dimension Media Solutions Pvt Ltd", normal_style)],
        [Paragraph("State & Code: Tamil Nadu (33)", normal_style)],
        [Paragraph("GSTIN: 33AABCF6993P1ZY", normal_style)],
        [Paragraph("PAN: AABCF6993P", normal_style)],
        [Paragraph("CIN: U22130TN2011PTC079276", normal_style)]
    ]

    company_table = Table(company_details, colWidths=[doc.width])
    company_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1)
    ]))
    elements.append(company_table)
    elements.append(Spacer(1, 5))

    # Bill To and Invoice Details Section (two columns)
    if payment.invoice_address:
        addr = payment.invoice_address
        bill_to_content = [
            [Paragraph("<b>Bill To,</b>", section_title_style)],
            [Paragraph(f"M/s. {addr.company_name or addr.full_name or 'Customer'}", normal_style)],
            [Paragraph(f"{addr.street_address or 'N/A'}", normal_style)],
            [Paragraph(f"{addr.city or 'N/A'} - {addr.postal_code or 'N/A'}", normal_style)],
            [Paragraph(f"{addr.state or 'N/A'}, India", normal_style)],
            [Paragraph(f"GST No. {addr.gst_number or 'N/A'}", normal_style)],
            [Paragraph(f"PAN No. {addr.pan_number or 'N/A'}", normal_style)]
        ]
    else:
        user = payment.user
        if user:
            bill_to_content = [
                [Paragraph("<b>Bill To,</b>", section_title_style)],
                [Paragraph(f"M/s. {user.name or 'Customer'}", normal_style)],
                [Paragraph(f"Email: {user.company_email or 'N/A'}", normal_style)]
            ]
        else:
            bill_to_content = [
                [Paragraph("<b>Bill To,</b>", section_title_style)],
                [Paragraph("M/s. Customer", normal_style)],
                [Paragraph("Email: N/A", normal_style)]
            ]

    # Invoice details - safely handle invoice_date if it's None
    invoice_date_str = payment.invoice_date.strftime('%d/%m/%Y') if payment.invoice_date else 'N/A'
    invoice_details_content = [
        [Paragraph(f"<b>Invoice No:</b> {payment.invoice_number}", normal_style)],
        [Paragraph(f"<b>Date:</b> {invoice_date_str}", normal_style)],
        [Spacer(1, 5)],
        [Paragraph(f"<b>Reverse Charge (Yes/No):</b> No", normal_style)],
        [Paragraph(f"<b>Place of supply:</b> Tamil Nadu (33)", normal_style)]
    ]

    # Create two-column layout for bill to and invoice details
    bill_invoice_data = [[
        Table(bill_to_content),
        Table(invoice_details_content)
    ]]

    bill_invoice_table = Table(bill_invoice_data, colWidths=[doc.width*0.6, doc.width*0.4])
    bill_invoice_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'LEFT')
    ]))
    elements.append(bill_invoice_table)
    elements.append(Spacer(1, 8))

    # Service Details Table
    headers = ['Sl No', 'Description of Service', 'SAC/HSN', 'Qty', 'Rate', 'Amount (Rs)']

    # Calculate amounts - safely handle None values
    base_amount = payment.base_amount or 0
    gst_rate = payment.gst_rate or 0.18
    gst_amount = payment.gst_amount or 0
    total_amount = payment.total_amount or 0
    cgst_rate = gst_rate / 2
    sgst_rate = gst_rate / 2
    cgst_amount = gst_amount / 2
    sgst_amount = gst_amount / 2

    # Build table data
    table_data = []
    table_data.append(headers)

    # Service row - safely get subscription plan name
    plan_name = payment.subscription.plan if payment.subscription else 'Subscription'
    table_data.append([
        '1.',
        f'Digital Service - {plan_name}',
        '998314',
        '1',
        f'{base_amount:.2f}',
        f'{base_amount:.2f}'
    ])

    # Totals
    table_data.append(['', '', '', '', 'Total', f'{base_amount:.2f}'])
    table_data.append(['', '', '', '', f'CGST @ {cgst_rate*100:.0f}%', f'{cgst_amount:.2f}'])
    table_data.append(['', '', '', '', f'SGST @ {sgst_rate*100:.0f}%', f'{sgst_amount:.2f}'])

    # Create service table
    col_widths = [doc.width*0.08, doc.width*0.35, doc.width*0.12, doc.width*0.08, doc.width*0.17, doc.width*0.2]
    service_table = Table(table_data, colWidths=col_widths)

    service_table.setStyle(TableStyle([
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), brand_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),

        # Data rows
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # Sl No
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),    # Description
        ('ALIGN', (2, 1), (2, -1), 'CENTER'),  # SAC/HSN
        ('ALIGN', (3, 1), (3, -1), 'CENTER'),  # Qty
        ('ALIGN', (4, 1), (4, -1), 'RIGHT'),   # Rate
        ('ALIGN', (5, 1), (5, -1), 'RIGHT'),   # Amount

        # Borders
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('TOPPADDING', (0, 1), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
        ('FONTSIZE', (0, 1), (-1, -1), 8),

        # Total rows have special formatting
        ('FONTNAME', (4, 2), (5, -1), 'Helvetica-Bold'),
    ]))

    elements.append(service_table)

    # Total Invoice Value
    total_table_data = [
        ['Total Invoice Value', f'{total_amount:.2f}']
    ]

    total_table = Table(total_table_data, colWidths=[doc.width*0.8, doc.width*0.2])
    total_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), secondary_color),
        ('TEXTCOLOR', (0, 0), (-1, -1), brand_color),
        ('ALIGN', (0, 0), (0, 0), 'RIGHT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
        ('RIGHTPADDING', (1, 0), (1, 0), 10),
    ]))
    elements.append(total_table)
    elements.append(Spacer(1, 5))

    # Rupees in words - safely handle conversion
    try:
        amount_words = num2words(int(total_amount), lang='en_IN').title()
    except (ValueError, TypeError):
        amount_words = "Zero"
    words_data = [[f'Rupees in words: {amount_words} Rupees Only']]

    words_table = Table(words_data, colWidths=[doc.width])
    words_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(words_table)
    elements.append(Spacer(1, 15))

    # Signature area
    signature_data = [
        ['', 'For Fourth Dimension Media Solutions (P) Ltd'],
        ['', ''],
        ['', 'Authorised Signatory']
    ]

    signature_table = Table(signature_data, colWidths=[doc.width*0.6, doc.width*0.4])
    signature_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (1, 0), (1, -1), 9),
    ]))
    elements.append(signature_table)
    elements.append(Spacer(1, 15))

    # Terms & Conditions and Bank Details
    terms_conditions = [
        [Paragraph("<b>Terms & Condition</b>", section_title_style)],
        [Paragraph("* All disputes are subject to Chennai Jurisdiction only", normal_style)],
        [Paragraph('* Kindly Make all payments favoring "Fourth Dimension Media Solutions Pvt Ltd"', normal_style)],
        [Paragraph("* Payment terms: Immediate", normal_style)],
        [Paragraph("* Bank Name: City Union Bank., Tambaram West, Chennai -45", normal_style)],
        [Paragraph("  Account No: 512120020019966", normal_style)],
        [Paragraph("  Account Type: OD", normal_style)],
        [Paragraph("  IFSC Code: CIUB0000117", normal_style)]
    ]

    terms_table = Table(terms_conditions, colWidths=[doc.width])
    terms_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('FONTSIZE', (0, 1), (-1, -1), 7),  # Smaller font for terms
    ]))
    elements.append(terms_table)

    # Build PDF
    doc.build(elements)

    # Reset buffer position
    buffer.seek(0)

    return buffer


def generate_invoice_pdf_for_email(payment, subscription, user):
    """Generate invoice PDF for payment confirmation email"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors
        from reportlab.platypus import Table, TableStyle

        # Create a BytesIO buffer to store PDF
        buffer = BytesIO()

        # Create PDF with ReportLab
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4

        # Set colors matching website theme
        primary_color = colors.HexColor('#273879')
        secondary_color = colors.HexColor('#0f74b2')

        # Header with gradient effect (simulated with shapes)
        c.setFillColor(primary_color)
        c.rect(0, height - 150, width, 150, fill=True, stroke=False)

        # Company logo/name
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 32)
        c.drawCentredString(width / 2, height - 80, "SEO Dada")
        c.setFont("Helvetica", 12)
        c.drawCentredString(width / 2, height - 100, "Professional SEO Analysis Platform")

        # Invoice title
        c.setFillColor(primary_color)
        c.setFont("Helvetica-Bold", 24)
        c.drawString(50, height - 180, "INVOICE")

        # Invoice details
        c.setFont("Helvetica", 10)
        c.drawString(50, height - 210, f"Invoice Number: {payment.invoice_number}")
        c.drawString(50, height - 225, f"Date: {datetime.now(UTC).strftime('%d %B %Y')}")
        c.drawString(50, height - 240, f"Order ID: {payment.razorpay_order_id}")

        # Bill to section
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, height - 280, "Bill To:")
        c.setFont("Helvetica", 10)
        c.drawString(50, height - 300, user.name)
        c.drawString(50, height - 315, user.company_email)

        # Calculate dates
        start_date = datetime.now(UTC)
        end_date = start_date + timedelta(days=subscription.days)

        # Items table data
        table_data = [
            ['Description', 'Period', 'Amount'],
            [f'{subscription.plan} Subscription',
             f'{start_date.strftime("%d %b %Y")} - {end_date.strftime("%d %b %Y")}',
             f'\u20b9{payment.base_amount:.2f}'],
            ['GST ({:.0f}%)'.format(payment.gst_rate * 100), '', f'\u20b9{payment.gst_amount:.2f}'],
            ['Total Amount', '', f'\u20b9{payment.total_amount:.2f}']
        ]

        # Create table
        table = Table(table_data, colWidths=[3*inch, 2*inch, 1.5*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), secondary_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f0fdf4')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -1), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))

        # Draw table
        table.wrapOn(c, width, height)
        table.drawOn(c, 50, height - 450)

        # Footer
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.grey)
        c.drawCentredString(width / 2, 80, "Thank you for your business!")
        c.drawCentredString(width / 2, 65, "For support, contact us at payment@seodada.com")
        c.drawCentredString(width / 2, 50, f"\u00a9 {datetime.now().year} SEO Dada. All rights reserved.")

        # Finalize PDF
        c.showPage()
        c.save()

        # Get PDF data
        buffer.seek(0)
        return buffer

    except Exception as e:
        current_app.logger.error(f"Error generating invoice PDF: {str(e)}")
        return None


def generate_token_invoice_pdf(token_purchase):
    """
    Generate PDF invoice for token purchase
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch, mm
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
    from num2words import num2words

    # Define brand colors to match the logo
    brand_color = colors.Color(0.73, 0.20, 0.04)
    secondary_color = colors.Color(0.95, 0.95, 0.95)
    text_color = colors.Color(0.25, 0.25, 0.25)

    # Prepare buffer and document
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=12*mm,
        rightMargin=12*mm,
        topMargin=12*mm,
        bottomMargin=12*mm
    )

    # Create custom styles (same as regular invoice)
    invoice_title_style = ParagraphStyle(
        name='InvoiceTitleCustom',
        fontName='Helvetica-Bold',
        fontSize=13,
        alignment=TA_RIGHT,
        textColor=brand_color,
        spaceAfter=4
    )

    section_title_style = ParagraphStyle(
        name='SectionTitleCustom',
        fontName='Helvetica-Bold',
        fontSize=9,
        textColor=text_color,
        spaceAfter=2
    )

    normal_style = ParagraphStyle(
        name='NormalCustom',
        fontName='Helvetica',
        fontSize=8,
        textColor=text_color,
        leading=10
    )

    elements = []

    # Logo and Title
    logo_path = os.path.join(current_app.root_path, 'assert', '4d-logo.webp')

    try:
        logo = Image(logo_path, width=1.5*inch, height=0.75*inch)
        header_data = [[
            logo,
            Paragraph("TAX INVOICE - TOKEN PURCHASE", invoice_title_style)
        ]]

        header_table = Table(header_data, colWidths=[doc.width/2, doc.width/2])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(header_table)
    except:
        elements.append(Paragraph("TAX INVOICE - TOKEN PURCHASE", invoice_title_style))

    elements.append(Spacer(1, 10))

    # Company Details
    company_details = [
        [Paragraph("<b>Company Name:</b>", section_title_style)],
        [Paragraph("M/s. Fourth Dimension Media Solutions Pvt Ltd", normal_style)],
        [Paragraph("State & Code: Tamil Nadu (33)", normal_style)],
        [Paragraph("GSTIN: 33AABCF6993P1ZY", normal_style)],
        [Paragraph("PAN: AABCF6993P", normal_style)],
        [Paragraph("CIN: U22130TN2011PTC079276", normal_style)]
    ]

    company_table = Table(company_details, colWidths=[doc.width])
    elements.append(company_table)
    elements.append(Spacer(1, 10))

    # Bill To and Invoice Details
    user = token_purchase.user
    bill_to_content = [
        [Paragraph("<b>Bill To,</b>", section_title_style)],
        [Paragraph(f"M/s. {user.name}", normal_style)],
        [Paragraph(f"Email: {user.company_email}", normal_style)]
    ]

    invoice_details_content = [
        [Paragraph(f"<b>Invoice No:</b> {token_purchase.invoice_number}", normal_style)],
        [Paragraph(f"<b>Date:</b> {token_purchase.invoice_date.strftime('%d/%m/%Y')}", normal_style)],
        [Paragraph(f"<b>Order ID:</b> {token_purchase.razorpay_order_id}", normal_style)],
        [Paragraph(f"<b>Payment ID:</b> {token_purchase.razorpay_payment_id}", normal_style)]
    ]

    bill_invoice_data = [[
        Table(bill_to_content),
        Table(invoice_details_content)
    ]]

    bill_invoice_table = Table(bill_invoice_data, colWidths=[doc.width*0.6, doc.width*0.4])
    elements.append(bill_invoice_table)
    elements.append(Spacer(1, 15))

    # Service Details Table
    headers = ['Sl No', 'Description of Service', 'SAC/HSN', 'Qty', 'Rate', 'Amount (Rs)']

    table_data = []
    table_data.append(headers)

    # Token purchase row
    table_data.append([
        '1.',
        f'Additional Usage Tokens ({token_purchase.token_count} tokens)',
        '998314',
        str(token_purchase.token_count),
        '2.00',
        f'{token_purchase.base_amount:.2f}'
    ])

    # Tax rows
    cgst_amount = token_purchase.gst_amount / 2
    sgst_amount = token_purchase.gst_amount / 2

    table_data.append(['', '', '', '', 'Subtotal', f'{token_purchase.base_amount:.2f}'])
    table_data.append(['', '', '', '', 'CGST @ 9%', f'{cgst_amount:.2f}'])
    table_data.append(['', '', '', '', 'SGST @ 9%', f'{sgst_amount:.2f}'])

    col_widths = [doc.width*0.08, doc.width*0.40, doc.width*0.12, doc.width*0.08, doc.width*0.16, doc.width*0.16]
    service_table = Table(table_data, colWidths=col_widths)

    service_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), brand_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (5, 1), (5, -1), 'RIGHT'),
        ('FONTNAME', (4, 2), (5, -1), 'Helvetica-Bold'),
    ]))

    elements.append(service_table)

    # Total
    total_table_data = [
        ['Total Invoice Value', f'\u20b9{token_purchase.total_amount:.2f}']
    ]

    total_table = Table(total_table_data, colWidths=[doc.width*0.8, doc.width*0.2])
    total_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), secondary_color),
        ('TEXTCOLOR', (0, 0), (-1, -1), brand_color),
        ('ALIGN', (0, 0), (0, 0), 'RIGHT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(total_table)

    # Amount in words
    amount_words = num2words(int(token_purchase.total_amount), lang='en_IN').title()
    words_data = [[f'Rupees in words: {amount_words} Rupees Only']]
    words_table = Table(words_data, colWidths=[doc.width])
    words_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(words_table)
    elements.append(Spacer(1, 15))

    # Signature area
    signature_data = [
        ['', 'For Fourth Dimension Media Solutions (P) Ltd'],
        ['', ''],
        ['', 'Authorised Signatory']
    ]

    signature_table = Table(signature_data, colWidths=[doc.width*0.6, doc.width*0.4])
    signature_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (1, 0), (1, -1), 9),
    ]))
    elements.append(signature_table)
    elements.append(Spacer(1, 15))

    # Terms & Conditions and Bank Details
    terms_conditions = [
        [Paragraph("<b>Terms & Condition</b>", section_title_style)],
        [Paragraph("* All disputes are subject to Chennai Jurisdiction only", normal_style)],
        [Paragraph('* Kindly Make all payments favoring "Fourth Dimension Media Solutions Pvt Ltd"', normal_style)],
        [Paragraph("* Payment terms: Immediate", normal_style)],
        [Paragraph("* Bank Name: City Union Bank., Tambaram West, Chennai -45", normal_style)],
        [Paragraph("  Account No: 512120020019966", normal_style)],
        [Paragraph("  Account Type: OD", normal_style)],
        [Paragraph("  IFSC Code: CIUB0000117", normal_style)]
    ]

    terms_table = Table(terms_conditions, colWidths=[doc.width])
    terms_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('FONTSIZE', (0, 1), (-1, -1), 7),  # Smaller font for terms
    ]))
    elements.append(terms_table)

    # Build PDF
    doc.build(elements)

    # Reset buffer position
    buffer.seek(0)

    return buffer


# ----------------------
# Subscription Routes
# ----------------------

@payment_bp.route('/subscriptions')
@_lazy_login_required
@csrf.exempt
def user_subscriptions():
    user_id = session.get('user_id')
    if not user_id:
        flash("You need to log in first.", "warning")
        return redirect(url_for('auth.login'))

    # Get current time
    now = datetime.now(UTC)

    # Get the most recent active subscription for the user
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
            flash(f'Duplicate subscription "{plan.plan}" has been deactivated.', 'info')
        db.session.commit()
    elif len(subscriptions) == 1:
        active_subscription = subscriptions[0]

    # Ensure timezone awareness
    if active_subscription:
        sub, plan = active_subscription
        if sub.start_date and sub.start_date.tzinfo is None:
            sub.start_date = sub.start_date.replace(tzinfo=UTC)
        if sub.end_date and sub.end_date.tzinfo is None:
            sub.end_date = sub.end_date.replace(tzinfo=UTC)

    # Get payment history
    payment_history = Payment.query.filter_by(user_id=user_id).order_by(Payment.created_at.desc()).all()

    # Get available plans
    available_plans = (
        Subscription.query
        .filter(Subscription.is_active == True)
        .filter(Subscription.archived_at.is_(None))
        .all()
    )

    # Get token usage summary
    from services.subscription import get_user_token_summary
    usage_summary = get_user_token_summary(user_id)

    return render_template(
        'user/subscriptions.html',
        active_subscription=active_subscription,
        payment_history=payment_history,
        available_plans=available_plans,
        usage_summary=usage_summary,
        now=now,
        hasattr=hasattr
    )


@payment_bp.route('/subscribe/<int:plan_id>', methods=['POST'])
@_lazy_login_required
@csrf.exempt
def subscribe(plan_id):
    user_id = session.get('user_id')
    current_app.logger.info(f"Subscribe request received for plan {plan_id} by user {user_id}")

    # Check if user already has an active subscription
    now = datetime.now(UTC)
    active_subscription = SubscribedUser.query.filter(
        SubscribedUser.U_ID == user_id,
        SubscribedUser.end_date > now,
        SubscribedUser._is_active == True
    ).first()

    if active_subscription:
        flash('You already have an active subscription. Please wait for it to expire or cancel it before subscribing to a new plan.', 'warning')
        return redirect(url_for('payment.user_subscriptions'))

    # Get the subscription plan
    subscription = (
        Subscription.query
        .filter(Subscription.S_ID == plan_id)
        .filter(Subscription.is_active == True)
        .filter(Subscription.archived_at.is_(None))
        .first_or_404()
    )

    # Check for duplicate/pending payments
    from services.refund import check_duplicate_payment
    dup_check = check_duplicate_payment(user_id, subscription.S_ID)
    if dup_check['is_duplicate']:
        existing = dup_check['existing_payment']
        if existing.status == 'completed':
            flash('You already have a completed payment for this plan.', 'warning')
            return redirect(url_for('payment.user_subscriptions'))
        elif existing.status == 'created':
            # Expire old pending payment and create a fresh one
            existing.status = 'expired'
            existing.notes = (existing.notes or '') + f"\nExpired: replaced by new order at {datetime.now(UTC).isoformat()}"
            db.session.commit()
            current_app.logger.info(f"Expired old pending payment {existing.iid} for user {user_id}")

    # Create Razorpay order
    try:
        # Consistent GST calculation
        gst_rate = 0.18  # 18% GST
        base_amount = subscription.price
        gst_amount = base_amount * gst_rate
        total_amount = base_amount + gst_amount

        # Convert to paisa and round to integer
        amount_in_paisa = int(total_amount * 100)
        currency = 'INR'

        # Robust price validation
        if total_amount <= 0 or amount_in_paisa <= 0:
            current_app.logger.error(f'Invalid subscription price for plan {plan_id}')
            flash('Invalid subscription price. Please contact support.', 'danger')
            return redirect(url_for('payment.user_subscriptions'))

        # Create Razorpay order
        razorpay_order = razorpay_client.order.create({
            'amount': amount_in_paisa,
            'currency': currency,
            'payment_capture': '1',
            'notes': {
                'user_id': user_id,
                'plan_id': plan_id,
                'description': f'Subscription for {subscription.plan}'
            }
        })

        # Store order details in session (don't create payment record yet)
        session['pending_order'] = {
            'base_amount': base_amount,
            'gst_amount': gst_amount,
            'total_amount': total_amount,
            'subscription_id': plan_id,
            'razorpay_order_id': razorpay_order['id'],
            'currency': currency,
            'gst_rate': gst_rate
        }
        session.modified = True

        # Redirect to checkout page with Razorpay details
        return redirect(url_for('payment.checkout', order_id=razorpay_order['id']))

    except Exception as e:
        current_app.logger.error(f"Error in subscribe route: {str(e)}", exc_info=True)
        db.session.rollback()
        flash(f'Error creating payment. Please try again or contact support.', 'danger')
        return redirect(url_for('payment.user_subscriptions'))


@payment_bp.route('/get_available_plans')
@_lazy_login_required
@csrf.exempt
def get_available_plans():
    user_id = session.get('user_id')

    # Get current active subscription
    current_subscription = (
        SubscribedUser.query
        .filter(SubscribedUser.U_ID == user_id)
        .filter(SubscribedUser.end_date > datetime.now(UTC))
        .filter(SubscribedUser._is_active == True)
        .first()
    )

    # Get query parameter to exclude current plan
    exclude_plan_id = request.args.get('exclude', type=int)

    # Get available plans
    available_plans = (
        Subscription.query
        .filter(Subscription.is_active == True)
        .filter(Subscription.archived_at.is_(None))
        .filter(Subscription.S_ID != exclude_plan_id)
        .all()
    )

    # Convert to JSON
    plans_json = [
        {
            'S_ID': plan.S_ID,
            'plan': plan.plan,
            'price': plan.price,
            'days': plan.days,
            'tier': plan.tier
        } for plan in available_plans
    ]

    return jsonify(plans_json)


@payment_bp.route('/subscription_details/<int:subscription_id>')
@_lazy_login_required
@csrf.exempt
def subscription_details(subscription_id):
    user_id = session.get('user_id')
    page = request.args.get('page', 1, type=int)
    per_page = 10

    try:
        # Get the SubscribedUser record
        subscribed_user = (
            SubscribedUser.query
            .filter(SubscribedUser.id == subscription_id)
            .filter(SubscribedUser.U_ID == user_id)
            .first()
        )

        if not subscribed_user:
            flash('Subscription not found.', 'danger')
            return redirect(url_for('payment.user_subscriptions'))

        # Get the subscription plan details
        subscription_plan = (
            Subscription.query
            .filter(Subscription.S_ID == subscribed_user.S_ID)
            .first()
        )

        if not subscription_plan:
            flash('Subscription plan not found.', 'danger')
            return redirect(url_for('payment.user_subscriptions'))

        # Get paginated usage history
        usage_query = (
            UsageLog.query
            .filter(UsageLog.subscription_id == subscription_id)
            .order_by(UsageLog.timestamp.desc())
        )

        usage_history = usage_query.paginate(page=page, per_page=per_page, error_out=False)

        # Get payment records
        payment_records = (
            Payment.query
            .filter_by(user_id=user_id, subscription_id=subscribed_user.S_ID)
            .order_by(Payment.created_at.desc())
            .all()
        )

        # Calculate daily usage statistics
        daily_usage = {}
        all_usage = usage_query.limit(100).all()

        if all_usage:
            for usage in all_usage:
                date_key = usage.timestamp.strftime('%Y-%m-%d')
                if date_key not in daily_usage:
                    daily_usage[date_key] = 0
                daily_usage[date_key] += 1

        sorted_daily_usage = sorted(daily_usage.items(), key=lambda x: x[0], reverse=True)

        # Calculate days remaining
        now = datetime.now(UTC)
        if subscribed_user.end_date.tzinfo is None:
            subscribed_user.end_date = subscribed_user.end_date.replace(tzinfo=UTC)

        days_remaining = max(0, (subscribed_user.end_date - now).days)

        # Calculate usage percentage
        if subscription_plan.usage_per_day and subscription_plan.usage_per_day > 0:
            usage_percentage = min(100, (subscribed_user.current_usage / subscription_plan.usage_per_day) * 100)
        else:
            usage_percentage = 0

        # Get token usage summary
        from services.subscription import get_user_token_summary
        usage_summary = get_user_token_summary(user_id)

        return render_template(
            'user/subscription_details.html',
            subscription=subscribed_user,
            plan=subscription_plan,
            usage_history=usage_history,
            payment_records=payment_records,
            daily_usage=sorted_daily_usage,
            days_remaining=days_remaining,
            usage_percentage=usage_percentage,
            usage_summary=usage_summary,
            now=now
        )

    except Exception as e:
        current_app.logger.error(f"Error in subscription_details: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        flash('Error loading subscription details.', 'danger')
        return redirect(url_for('payment.user_subscriptions'))


@payment_bp.route('/subscription/<int:subscription_id>/usage_history')
@_lazy_login_required
@csrf.exempt
def get_usage_history(subscription_id):
    """AJAX endpoint to get paginated usage history"""
    user_id = session.get('user_id')
    page = request.args.get('page', 1, type=int)
    per_page = 10

    try:
        # Verify the subscription belongs to the logged-in user
        subscribed_user = (
            SubscribedUser.query
            .filter(SubscribedUser.id == subscription_id)
            .filter(SubscribedUser.U_ID == user_id)
            .first()
        )

        if not subscribed_user:
            return "Subscription not found", 404

        # Get paginated usage history
        usage_history = (
            UsageLog.query
            .filter(UsageLog.subscription_id == subscription_id)
            .order_by(UsageLog.timestamp.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )

        # Check if this is an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return render_template(
                'user/partials/usage_history.html',
                subscription=subscribed_user,
                usage_history=usage_history
            )

        # If not an AJAX request, redirect to the main page
        return redirect(url_for('payment.subscription_details', subscription_id=subscription_id, page=page))

    except Exception as e:
        current_app.logger.error(f"Error in get_usage_history: {str(e)}")
        return "Error loading usage history", 500


@payment_bp.route('/download_invoice/<int:payment_id>')
@_lazy_login_required
@csrf.exempt
def download_invoice(payment_id):
    try:
        # Fetch the payment
        payment = Payment.query.get_or_404(payment_id)

        # Verify user authorization
        if payment.user_id != current_user.id:
            flash('Unauthorized access to invoice', 'error')
            return redirect(url_for('seo_tools.dashboard'))

        # Generate the invoice PDF
        pdf_buffer = generate_invoice_pdf(payment)

        if pdf_buffer is None:
            current_app.logger.error(f"generate_invoice_pdf returned None for payment {payment_id}")
            flash('Error generating invoice. Please try again later.', 'error')
            return redirect(url_for('payment.user_subscriptions'))

        # Send the PDF as a download
        return send_file(
            pdf_buffer,
            download_name=f"invoice_{payment.invoice_number}.pdf",
            as_attachment=True,
            mimetype='application/pdf'
        )
    except Exception as e:
        current_app.logger.error(f"Error generating invoice for payment {payment_id}: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        flash('Error generating invoice. Please try again later.', 'error')
        return redirect(url_for('payment.user_subscriptions'))


@payment_bp.route('/subscription/<int:subscription_id>')
@_lazy_login_required
def view_subscription_details(subscription_id):
    subscription = SubscribedUser.query.get_or_404(subscription_id)

    # Verify this subscription belongs to the current user
    if subscription.U_ID != session.get('user_id'):
        flash('Unauthorized action', 'danger')
        return redirect(url_for('payment.user_subscriptions'))

    # Get plan details
    plan = Subscription.query.get(subscription.S_ID)

    # Get payment history
    payments = Payment.query.filter_by(
        user_id=session.get('user_id'),
        subscription_id=subscription.S_ID
    ).order_by(Payment.created_at.desc()).all()

    return render_template('user/subscription_details.html',
                          subscription=subscription,
                          plan=plan,
                          payments=payments)


@payment_bp.route('/checkout/<order_id>', methods=['GET', 'POST'])
@_lazy_login_required
@csrf.exempt
def checkout(order_id):
    user_id = session.get('user_id')

    # Get user details using get() method recommended for SQLAlchemy 2.0
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found', 'danger')
        return redirect(url_for('auth.login'))

    # Get pending order from session
    pending_order = session.get('pending_order')
    if not pending_order or pending_order.get('razorpay_order_id') != order_id:
        flash('Invalid or expired checkout session. Please try again.', 'danger')
        return redirect(url_for('payment.user_subscriptions'))

    # Use get() method for subscription
    subscription = db.session.get(Subscription, pending_order['subscription_id'])
    if not subscription:
        flash('Subscription not found', 'danger')
        return redirect(url_for('payment.user_subscriptions'))

    if request.method == 'POST':
        # Validate required fields
        required_fields = [
            'full_name', 'street_address', 'city',
            'state', 'postal_code', 'country',
            'email', 'phone_number'
        ]

        # Check if all required fields are filled
        for field in required_fields:
            if not request.form.get(field):
                flash(f'Please fill in all required fields, especially {field.replace("_", " ")}', 'warning')
                # Create a temporary payment object for template rendering
                class TempPayment:
                    def __init__(self, order_data):
                        self.razorpay_order_id = order_data['razorpay_order_id']
                        self.base_amount = order_data['base_amount']
                        self.gst_rate = order_data['gst_rate']
                        self.gst_amount = order_data['gst_amount']
                        self.total_amount = order_data['total_amount']

                temp_payment = TempPayment(pending_order)
                return render_template('user/checkout.html', user=user, payment=temp_payment, subscription=subscription,
                                     base_amount=pending_order['base_amount'],
                                     gst_rate=pending_order['gst_rate'],
                                     gst_amount=pending_order['gst_amount'],
                                     total_amount=pending_order['total_amount'])

        # NOW create the payment record (only when user submits the form)
        payment = Payment(
            base_amount=pending_order['base_amount'],
            gst_amount=pending_order['gst_amount'],
            total_amount=pending_order['total_amount'],
            user_id=user_id,
            subscription_id=pending_order['subscription_id'],
            razorpay_order_id=pending_order['razorpay_order_id'],
            currency=pending_order['currency'],
            status='created',
            payment_type='new',
            gst_rate=pending_order['gst_rate']
        )
        db.session.add(payment)
        db.session.flush()  # Flush to get the payment.iid

        # Create invoice address
        invoice_address = InvoiceAddress(
            payment_id=payment.iid,
            full_name=request.form.get('full_name'),
            company_name=request.form.get('company_name', ''),
            street_address=request.form.get('street_address'),
            city=request.form.get('city'),
            state=request.form.get('state'),
            postal_code=request.form.get('postal_code'),
            country=request.form.get('country', 'India'),
            email=request.form.get('email', user.company_email),
            phone_number=request.form.get('phone_number'),
            gst_number=request.form.get('gst_number', ''),
            pan_number=request.form.get('pan_number', '')
        )

        db.session.add(invoice_address)
        db.session.commit()

        # Clear the pending order from session
        session.pop('pending_order', None)
        session.modified = True

        return redirect(url_for('payment.verify_payment', order_id=order_id))

    # GET request - show checkout form
    class TempPayment:
        def __init__(self, order_data):
            self.razorpay_order_id = order_data['razorpay_order_id']
            self.base_amount = order_data['base_amount']
            self.gst_rate = order_data['gst_rate']
            self.gst_amount = order_data['gst_amount']
            self.total_amount = order_data['total_amount']

    temp_payment = TempPayment(pending_order)

    return render_template(
        'user/checkout.html',
        user=user,
        payment=temp_payment,
        subscription=subscription,
        base_amount=pending_order['base_amount'],
        gst_rate=pending_order['gst_rate'],
        gst_amount=pending_order['gst_amount'],
        total_amount=pending_order['total_amount'],
        razorpay_key_id=current_app.config['RAZORPAY_KEY_ID']
    )


@payment_bp.route('/payment/verify/<order_id>', methods=['GET', 'POST'])
@_lazy_login_required
def verify_payment(order_id):
    user_id = session.get('user_id')
    if not user_id:
        flash("You need to log in first.", "warning")
        return redirect(url_for('auth.login'))

    # Get user details
    user = User.query.get_or_404(user_id)

    # Handle GET request - show payment verification page
    if request.method == 'GET':
        # Find pending payment for this order_id and user
        payment = Payment.query.filter_by(
            razorpay_order_id=order_id,
            user_id=user_id,
            status='created'
        ).first()

        if not payment:
            flash('No pending payment found for this order.', 'warning')
            return redirect(url_for('payment.user_subscriptions'))

        # Load subscription details for display
        subscription = Subscription.query.get(payment.subscription_id)
        if not subscription:
            flash('Subscription not found.', 'danger')
            return redirect(url_for('payment.user_subscriptions'))

        # Render verification page with all necessary data
        return render_template('payment/verify.html',
                               payment=payment,
                               subscription=subscription,
                               user=user,
                               razorpay_key_id=current_app.config['RAZORPAY_KEY_ID'])

    # Handle POST request - actual payment verification
    try:
        # Get payment details from Razorpay callback
        razorpay_payment_id = request.form.get('razorpay_payment_id')
        razorpay_order_id = request.form.get('razorpay_order_id')
        razorpay_signature = request.form.get('razorpay_signature')

        # Validate input parameters
        if not all([razorpay_payment_id, razorpay_order_id, razorpay_signature]):
            current_app.logger.error(f"Missing payment details for order: {order_id}")
            flash('Missing payment details. Please try again.', 'danger')
            return redirect(url_for('payment.user_subscriptions'))

        # Find the payment record
        payment = Payment.query.filter_by(
            razorpay_order_id=razorpay_order_id,
            user_id=user_id,
            status='created'
        ).first()

        if not payment:
            current_app.logger.error(f"Payment record not found for order: {razorpay_order_id}, user: {user_id}")
            flash('Payment record not found.', 'danger')
            return redirect(url_for('payment.user_subscriptions'))

        # Verify signature using custom method
        signature_valid = verify_razorpay_signature(
            razorpay_order_id,
            razorpay_payment_id,
            razorpay_signature,
            current_app.config['RAZORPAY_KEY_SECRET']
        )

        if not signature_valid:
            current_app.logger.error(f"Signature verification failed for payment: {razorpay_payment_id}")
            # Auto-refund if money was debited but signature failed
            payment.razorpay_payment_id = razorpay_payment_id
            db.session.commit()
            from services.refund import auto_refund_failed_payment
            refund_result = auto_refund_failed_payment(payment.iid)
            if refund_result['success']:
                flash('Payment verification failed. A full refund has been initiated. It will be credited within 5-7 business days.', 'warning')
            else:
                flash('Payment verification failed. Please contact support for a refund.', 'danger')
            return redirect(url_for('payment.user_subscriptions'))

        # Fetch payment details from Razorpay to verify amount
        try:
            payment_details = razorpay_client.payment.fetch(razorpay_payment_id)

            # Convert total_amount to paisa for comparison
            expected_amount_in_paisa = int(payment.total_amount * 100)

            # Verify the amount matches the expected amount
            if payment_details['amount'] != expected_amount_in_paisa:
                current_app.logger.error(
                    f"Amount mismatch: Expected {expected_amount_in_paisa}, "
                    f"Got {payment_details['amount']} for payment: {razorpay_payment_id}"
                )
                # Auto-refund on amount mismatch
                payment.razorpay_payment_id = razorpay_payment_id
                db.session.commit()
                from services.refund import auto_refund_failed_payment
                refund_result = auto_refund_failed_payment(payment.iid)
                if refund_result['success']:
                    flash('Payment amount mismatch detected. A full refund has been initiated.', 'warning')
                else:
                    flash('Payment amount verification failed. Please contact support.', 'danger')
                return redirect(url_for('payment.user_subscriptions'))

            # Verify payment is authorized/captured
            if payment_details['status'] not in ['authorized', 'captured']:
                current_app.logger.error(f"Payment not authorized: {payment_details['status']}")
                flash('Payment was not authorized. Please try again.', 'danger')
                return redirect(url_for('payment.user_subscriptions'))

        except Exception as fetch_error:
            current_app.logger.error(f"Error fetching payment details from Razorpay: {str(fetch_error)}")
            flash('Unable to verify payment details with Razorpay.', 'danger')
            return redirect(url_for('payment.user_subscriptions'))

        # Begin database transaction
        try:
            db.session.begin_nested()

            # Update payment details
            payment.razorpay_payment_id = razorpay_payment_id
            payment.status = 'completed'

            # Create new subscription (or update existing)
            subscription = Subscription.query.get(payment.subscription_id)

            # Calculate subscription dates
            start_date = datetime.now(UTC)
            end_date = start_date + timedelta(days=subscription.days)

            # Create new SubscribedUser record
            new_subscription = SubscribedUser(
                U_ID=user_id,
                S_ID=subscription.S_ID,
                start_date=start_date,
                end_date=end_date,
                is_auto_renew=True,  # Default to auto-renew
                current_usage=0,
                last_usage_reset=start_date,
                _is_active=True  # Set as active subscription
            )

            db.session.add(new_subscription)
            db.session.flush()  # Flush to get the new subscription ID

            # Reactivate paused tokens
            try:
                from services.subscription import reactivate_user_paused_tokens
                reactivated_count, total_tokens = reactivate_user_paused_tokens(user_id, new_subscription.id)
                if reactivated_count > 0:
                    current_app.logger.info(f"Reactivated {reactivated_count} token records ({total_tokens} tokens) for user {user_id}")
                    flash(f'Subscription activated! {total_tokens} previously unused tokens have been reactivated.', 'success')
                else:
                    flash(f'Payment successful! You are now subscribed to the {subscription.plan} plan.', 'success')
            except Exception as token_error:
                current_app.logger.error(f"Error reactivating tokens: {str(token_error)}")
                # Continue anyway - don't fail the payment for token reactivation issues
                flash(f'Payment successful! You are now subscribed to the {subscription.plan} plan.', 'success')

            # Add subscription history entry
            history_entry = SubscriptionHistory(
                U_ID=user_id,
                S_ID=subscription.S_ID,
                action=payment.payment_type,  # 'new', 'upgrade', etc.
                previous_S_ID=payment.previous_subscription_id,
                created_at=datetime.now(UTC)
            )
            db.session.add(history_entry)

            # Send confirmation email (optional)
            try:
                from services.email import send_payment_confirmation_email
                send_payment_confirmation_email(user, payment, subscription)
            except Exception as email_error:
                # Log but don't fail if email sending fails
                current_app.logger.error(f"Failed to send confirmation email: {str(email_error)}")

            # Commit all changes
            db.session.commit()

            current_app.logger.info(f"Payment successful: {razorpay_payment_id} for user: {user_id}")
            return redirect(url_for('payment.user_subscriptions'))

        except Exception as db_error:
            # Roll back transaction on error
            db.session.rollback()
            current_app.logger.error(f"Database error during payment processing: {str(db_error)}")
            flash('Error processing payment. Please contact support.', 'danger')
            return redirect(url_for('payment.user_subscriptions'))

    except Exception as e:
        # Catch-all for unexpected errors
        current_app.logger.error(f"Unexpected error in payment verification: {str(e)}", exc_info=True)
        flash('An unexpected error occurred. Please try again or contact support.', 'danger')
        return redirect(url_for('payment.user_subscriptions'))


@payment_bp.route('/subscription/change/<int:new_plan_id>', methods=['GET', 'POST'])
@_lazy_login_required
@csrf.exempt
def change_subscription(new_plan_id):
    user_id = session.get('user_id')

    # Extensive logging for debugging
    current_app.logger.info(f"Attempting to change subscription for user {user_id}")

    # Fetch all subscriptions for the user for detailed inspection
    all_subscriptions = (
        SubscribedUser.query
        .filter(SubscribedUser.U_ID == user_id)
        .all()
    )

    # Log details of all subscriptions
    for sub in all_subscriptions:
        current_app.logger.info(f"Subscription ID: {sub.id}")
        current_app.logger.info(f"Subscription Plan ID: {sub.S_ID}")
        current_app.logger.info(f"Start Date: {sub.start_date}")
        current_app.logger.info(f"End Date: {sub.end_date}")
        current_app.logger.info(f"Is Active (property): {sub.is_active}")
        current_app.logger.info(f"Is Active (column): {sub._is_active}")
        current_app.logger.info(f"Current Time (UTC): {datetime.now(UTC)}")

    # Get current active subscription with more detailed conditions
    current_subscription = (
        SubscribedUser.query
        .filter(SubscribedUser.U_ID == user_id)
        .filter(SubscribedUser.end_date > datetime.now(UTC))
        .filter(
            # Check both the property and the column
            or_(
                SubscribedUser._is_active == True,
                SubscribedUser.is_active == True
            )
        )
        .first()
    )

    # If no subscription found, log detailed information
    if not current_subscription:
        current_app.logger.warning(f"No active subscription found for user {user_id}")

        # Additional checks
        expired_subs = (
            SubscribedUser.query
            .filter(SubscribedUser.U_ID == user_id)
            .filter(SubscribedUser.end_date <= datetime.now(UTC))
            .all()
        )

        if expired_subs:
            current_app.logger.warning("Found expired subscriptions:")
            for sub in expired_subs:
                current_app.logger.warning(f"Subscription ID: {sub.id}, End Date: {sub.end_date}")

        flash('You don\'t have an active subscription to change.', 'warning')
        return redirect(url_for('payment.user_subscriptions'))

    # Get the new subscription plan
    new_plan = Subscription.query.get_or_404(new_plan_id)

    # Determine if this is an upgrade or downgrade
    is_upgrade = new_plan.tier > current_subscription.subscription.tier

    # Calculate remaining value of current subscription
    remaining_value = current_subscription.remaining_value()

    if request.method == 'POST':
        try:
            # Start a database transaction
            db.session.begin_nested()

            # Calculate the amount to charge with GST consideration
            if is_upgrade:
                # Amount to charge after applying remaining value credit
                amount_to_charge = max(0, new_plan.price - remaining_value)

                # Create a Payment instance
                payment = Payment(
                    user_id=user_id,
                    subscription_id=new_plan_id,
                    base_amount=amount_to_charge,
                    payment_type='upgrade',
                    previous_subscription_id=current_subscription.S_ID,
                    credit_applied=remaining_value,
                    razorpay_order_id=None,  # Will be set later
                    status='created',
                    currency='INR'
                )

                # If there's an amount to charge, create Razorpay order
                if payment.total_amount > 0:
                    razorpay_order = razorpay_client.order.create({
                        'amount': int(payment.total_amount * 100),
                        'currency': 'INR',
                        'payment_capture': '1'
                    })

                    payment.razorpay_order_id = razorpay_order['id']
                    db.session.add(payment)
                    db.session.commit()

                    return redirect(url_for('payment.checkout', order_id=razorpay_order['id']))
                else:
                    # No additional payment needed
                    _process_subscription_change(
                        user_id,
                        current_subscription,
                        new_plan_id,
                        is_upgrade=True,
                        credit_applied=remaining_value
                    )

                    flash(f'Your subscription has been upgraded to {new_plan.plan}!', 'success')
                    return redirect(url_for('payment.user_subscriptions'))

            else:
                # Downgrade case - process change without payment
                _process_subscription_change(
                    user_id,
                    current_subscription,
                    new_plan_id,
                    is_upgrade=False,
                    credit_applied=remaining_value
                )

                flash(f'Your subscription has been changed to {new_plan.plan}.', 'success')
                return redirect(url_for('payment.user_subscriptions'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error processing subscription change: {str(e)}")
            flash(f'Error processing subscription change: {str(e)}', 'danger')
            return redirect(url_for('payment.user_subscriptions'))

    # GET request - show confirmation page
    return render_template(
        'user/change_subscription.html',
        current_subscription=current_subscription,
        new_plan=new_plan,
        is_upgrade=is_upgrade,
        remaining_value=remaining_value,
        amount_to_charge=max(0, new_plan.price - remaining_value) if is_upgrade else 0,
        gst_rate=0.18  # Standard GST rate
    )


@payment_bp.route('/subscription/auto-renew/<int:subscription_id>/<int:status>')
@_lazy_login_required
def toggle_auto_renew(subscription_id, status):
    user_id = session.get('user_id')

    # Find the specific subscription
    subscription = (
        SubscribedUser.query
        .filter(SubscribedUser.id == subscription_id)
        .filter(SubscribedUser.U_ID == user_id)
        .first_or_404()
    )

    # Update auto-renew status
    subscription.is_auto_renew = bool(status)
    db.session.commit()

    if subscription.is_auto_renew:
        flash('Auto-renewal has been enabled for your subscription.', 'success')
    else:
        flash('Auto-renewal has been disabled for your subscription.', 'info')

    return redirect(url_for('payment.user_subscriptions'))


@payment_bp.route('/subscription/cancel/<int:subscription_id>', methods=['GET', 'POST'])
@_lazy_login_required
@csrf.exempt
def cancel_subscription(subscription_id):
    user_id = session.get('user_id')

    # Find the specific subscription
    subscription = (
        SubscribedUser.query
        .filter(SubscribedUser.id == subscription_id)
        .filter(SubscribedUser.U_ID == user_id)
        .first_or_404()
    )

    if request.method == 'POST':
        request_refund = request.form.get('request_refund') == 'yes'

        if request_refund:
            # Cancel with prorated refund
            from services.refund import cancel_subscription_with_refund
            result = cancel_subscription_with_refund(subscription_id, user_id)

            if result['success']:
                if result.get('refund_amount', 0) > 0:
                    flash(result['message'], 'success')
                else:
                    flash('Subscription cancelled successfully.', 'info')
            else:
                flash(result['message'], 'danger')
        else:
            # Cancel without refund (original behavior)
            subscription.is_auto_renew = False
            subscription.is_active = False

            history_entry = SubscriptionHistory(
                U_ID=user_id,
                S_ID=subscription.S_ID,
                action='cancel',
                previous_S_ID=subscription.S_ID,
                created_at=datetime.now(UTC)
            )
            db.session.add(history_entry)
            db.session.commit()
            flash('Your subscription has been cancelled successfully.', 'info')

        return redirect(url_for('payment.user_subscriptions'))

    # GET request - calculate prorated refund for display
    refund_info = None
    try:
        now = datetime.now(UTC)
        start = subscription.start_date
        end = subscription.end_date
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)

        total_days = (end - start).total_seconds() / 86400
        remaining_days = max(0, (end - now).total_seconds() / 86400)

        # Find the payment
        payment = (
            Payment.query
            .filter(Payment.user_id == user_id)
            .filter(Payment.subscription_id == subscription.S_ID)
            .filter(Payment.status == 'completed')
            .order_by(Payment.created_at.desc())
            .first()
        )

        if payment and total_days > 0 and remaining_days > 0:
            from decimal import Decimal, ROUND_HALF_UP
            refund_ratio = Decimal(str(remaining_days)) / Decimal(str(total_days))
            refund_amount = float(
                (Decimal(str(payment.total_amount)) * refund_ratio)
                .quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            )
            refund_info = {
                'total_paid': payment.total_amount,
                'remaining_days': round(remaining_days, 1),
                'total_days': round(total_days, 1),
                'refund_amount': refund_amount
            }
    except Exception as e:
        current_app.logger.error(f"Error calculating refund: {str(e)}")

    return render_template(
        'user/cancel_subscription.html',
        subscription=subscription,
        refund_info=refund_info
    )


# ----------------------
# Token Purchase Routes
# ----------------------

@payment_bp.route('/purchase_tokens', methods=['POST'])
@_lazy_login_required
@csrf.exempt
def purchase_tokens():
    """Initialize token purchase process"""
    try:
        user_id = session.get('user_id')
        token_count = int(request.form.get('token_count', 0))

        # Validate token count
        valid_token_counts = [10, 25, 50, 100]
        if token_count not in valid_token_counts:
            return jsonify({'error': 'Invalid token count'}), 400

        # Check if user has active subscription
        active_subscription = (
            SubscribedUser.query
            .filter(SubscribedUser.U_ID == user_id)
            .filter(SubscribedUser.end_date > datetime.now(UTC))
            .filter(SubscribedUser._is_active == True)
            .first()
        )

        if not active_subscription:
            return jsonify({'error': 'No active subscription found'}), 400

        # Calculate pricing (Rs 2 per token including GST)
        price_per_token = 2.00
        total_amount = token_count * price_per_token
        gst_rate = 0.18
        base_amount = total_amount / (1 + gst_rate)
        gst_amount = total_amount - base_amount

        # Create Razorpay order
        razorpay_order = razorpay_client.order.create({
            'amount': int(total_amount * 100),  # Amount in paisa
            'currency': 'INR',
            'payment_capture': '1',
            'notes': {
                'user_id': user_id,
                'subscription_id': active_subscription.id,
                'token_count': token_count,
                'type': 'token_purchase'
            }
        })

        # Store token purchase record
        token_purchase = TokenPurchase(
            user_id=user_id,
            subscription_id=active_subscription.id,
            token_count=token_count,
            base_amount=base_amount,
            gst_amount=gst_amount,
            total_amount=total_amount,
            razorpay_order_id=razorpay_order['id'],
            status='created'
        )

        db.session.add(token_purchase)
        db.session.commit()

        return jsonify({
            'success': True,
            'order_id': razorpay_order['id'],
            'amount': total_amount,
            'token_count': token_count,
            'razorpay_key': current_app.config['RAZORPAY_KEY_ID']
        })

    except Exception as e:
        current_app.logger.error(f"Error in purchase_tokens: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@payment_bp.route('/verify_token_payment', methods=['POST'])
@_lazy_login_required
@csrf.exempt
def verify_token_payment():
    """Verify token payment and add tokens to user account"""
    try:
        user_id = session.get('user_id')
        razorpay_payment_id = request.form.get('razorpay_payment_id')
        razorpay_order_id = request.form.get('razorpay_order_id')
        razorpay_signature = request.form.get('razorpay_signature')

        # Get user object first
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Validate signature
        signature_valid = verify_razorpay_signature(
            razorpay_order_id,
            razorpay_payment_id,
            razorpay_signature,
            current_app.config['RAZORPAY_KEY_SECRET']
        )

        if not signature_valid:
            return jsonify({'error': 'Payment verification failed'}), 400

        # Find the token purchase record
        token_purchase = TokenPurchase.query.filter_by(
            razorpay_order_id=razorpay_order_id,
            user_id=user_id,
            status='created'
        ).first()

        if not token_purchase:
            return jsonify({'error': 'Token purchase record not found'}), 404

        # Verify payment with Razorpay
        try:
            payment_details = razorpay_client.payment.fetch(razorpay_payment_id)

            if payment_details['status'] not in ['authorized', 'captured']:
                return jsonify({'error': 'Payment not authorized'}), 400

            expected_amount = int(token_purchase.total_amount * 100)
            if payment_details['amount'] != expected_amount:
                return jsonify({'error': 'Amount mismatch'}), 400

        except Exception as e:
            current_app.logger.error(f"Razorpay verification error: {str(e)}")
            return jsonify({'error': 'Payment verification failed'}), 400

        # Update token purchase record with invoice details
        token_purchase.razorpay_payment_id = razorpay_payment_id
        token_purchase.status = 'completed'
        token_purchase._generate_invoice_details()  # Generate invoice number and date

        # Get user's active subscription
        active_subscription = SubscribedUser.query.get(token_purchase.subscription_id)

        # Create user token record
        user_token = UserToken(
            user_id=user_id,
            subscription_id=active_subscription.id,
            purchase_id=token_purchase.id,
            tokens_purchased=token_purchase.token_count,
            tokens_used=0,
            tokens_remaining=token_purchase.token_count,
            expires_at=datetime.now(UTC) + timedelta(days=365)
        )

        db.session.add(user_token)

        # Send confirmation email
        email_sent = False
        try:
            from services.email import send_token_purchase_confirmation_email
            send_token_purchase_confirmation_email(user, token_purchase)
            current_app.logger.info(f"Token purchase confirmation email sent to {user.company_email}")
            email_sent = True
        except Exception as email_error:
            # Log email error but don't fail the transaction
            current_app.logger.error(f"Failed to send token purchase confirmation email: {str(email_error)}")
            current_app.logger.error(f"Email error traceback: {traceback.format_exc()}")

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Successfully purchased {token_purchase.token_count} additional tokens!',
            'invoice_number': token_purchase.invoice_number,
            'email_sent': email_sent
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in verify_token_payment: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@payment_bp.route('/download_token_invoice/<int:token_purchase_id>')
@_lazy_login_required
@csrf.exempt
def download_token_invoice(token_purchase_id):
    user_id = session.get('user_id')

    # Get token purchase
    token_purchase = TokenPurchase.query.filter_by(
        id=token_purchase_id,
        user_id=user_id,
        status='completed'
    ).first_or_404()

    if not token_purchase.invoice_number:
        flash('Invoice not available for this token purchase.', 'warning')
        return redirect(url_for('payment.user_subscriptions'))

    # Generate invoice PDF
    pdf_buffer = generate_token_invoice_pdf(token_purchase)

    return send_file(
        pdf_buffer,
        download_name=f"token_invoice_{token_purchase.invoice_number}.pdf",
        as_attachment=True,
        mimetype='application/pdf'
    )


# ----------------------
# Receipt Route
# ----------------------

@payment_bp.route('/receipt/<int:payment_id>')
@_lazy_login_required
def download_receipt(payment_id):
    user_id = session.get('user_id')

    # Get payment details - fix: use Payment.iid instead of Payment.id
    payment = Payment.query.filter_by(iid=payment_id, user_id=user_id).first_or_404()

    # TODO: Generate and return PDF receipt
    # This would typically use a PDF generation library like ReportLab or WeasyPrint

    flash('Receipt download feature coming soon!', 'info')
    return redirect(url_for('auth.profile') + '#activity')


# ----------------------
# Razorpay Webhook
# ----------------------

@payment_bp.route('/webhook/razorpay', methods=['POST'])
@csrf.exempt
def razorpay_webhook():
    """
    Razorpay webhook endpoint for server-side payment confirmation.
    This catches payments even if user closed the browser after paying.

    Configure in Razorpay Dashboard:
      URL: https://seodada.com/webhook/razorpay
      Events: payment.authorized, payment.captured, payment.failed
      Secret: Set in .env as RAZORPAY_WEBHOOK_SECRET
    """
    import hmac
    import hashlib

    try:
        # Verify webhook signature
        webhook_secret = current_app.config.get('RAZORPAY_WEBHOOK_SECRET', '')
        webhook_signature = request.headers.get('X-Razorpay-Signature', '')
        webhook_body = request.get_data(as_text=True)

        if webhook_secret and webhook_signature:
            expected = hmac.new(
                webhook_secret.encode('utf-8'),
                webhook_body.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            if expected != webhook_signature:
                current_app.logger.warning("Webhook: Invalid signature")
                return jsonify({'status': 'invalid_signature'}), 401

        payload = request.get_json()
        if not payload:
            return jsonify({'status': 'empty_payload'}), 400

        event = payload.get('event', '')
        payment_entity = payload.get('payload', {}).get('payment', {}).get('entity', {})

        razorpay_payment_id = payment_entity.get('id')
        razorpay_order_id = payment_entity.get('order_id')
        payment_status = payment_entity.get('status')

        current_app.logger.info(
            f"Webhook received: event={event}, payment={razorpay_payment_id}, "
            f"order={razorpay_order_id}, status={payment_status}"
        )

        if event in ('payment.authorized', 'payment.captured'):
            # Find payment record
            payment = Payment.query.filter_by(razorpay_order_id=razorpay_order_id).first()

            if not payment:
                current_app.logger.warning(f"Webhook: Payment not found for order {razorpay_order_id}")
                return jsonify({'status': 'payment_not_found'}), 200

            if payment.status == 'completed':
                return jsonify({'status': 'already_processed'}), 200

            # Process via refund service
            from services.refund import handle_webhook_payment
            result = handle_webhook_payment(
                razorpay_payment_id, razorpay_order_id,
                webhook_signature  # Not the actual payment signature - handled inside
            )

            return jsonify({'status': 'processed' if result['success'] else 'failed'}), 200

        elif event == 'payment.failed':
            # Mark payment as failed
            payment = Payment.query.filter_by(razorpay_order_id=razorpay_order_id).first()
            if payment and payment.status == 'created':
                payment.status = 'failed'
                payment.notes = (payment.notes or '') + f"\nPayment failed via webhook at {datetime.now(UTC).isoformat()}"
                db.session.commit()
                current_app.logger.info(f"Webhook: Payment marked as failed: {razorpay_order_id}")

            return jsonify({'status': 'noted'}), 200

        elif event == 'refund.created':
            current_app.logger.info(f"Webhook: Refund created for payment {razorpay_payment_id}")
            return jsonify({'status': 'noted'}), 200

        return jsonify({'status': 'ignored'}), 200

    except Exception as e:
        current_app.logger.error(f"Webhook error: {str(e)}")
        return jsonify({'status': 'error'}), 500


# ----------------------
# Payment Recovery (for stuck/orphan payments)
# ----------------------

@payment_bp.route('/payment/recover/<order_id>')
@_lazy_login_required
def recover_payment(order_id):
    """
    Recover a stuck payment by checking Razorpay directly.
    Use when: payment was debited but verification never happened
    (user closed browser, network error, webhook failed).
    """
    user_id = session.get('user_id')

    try:
        # Find the stuck payment
        payment = Payment.query.filter_by(
            razorpay_order_id=order_id,
            user_id=user_id
        ).first()

        if not payment:
            flash('Payment not found.', 'danger')
            return redirect(url_for('payment.user_subscriptions'))

        if payment.status == 'completed':
            flash('This payment is already completed.', 'info')
            return redirect(url_for('payment.user_subscriptions'))

        if payment.status == 'refunded':
            flash('This payment was refunded.', 'info')
            return redirect(url_for('payment.user_subscriptions'))

        # Fetch order details from Razorpay to find the payment
        try:
            order_details = razorpay_client.order.fetch(order_id)
            current_app.logger.info(f"Razorpay order status: {order_details.get('status')}")

            if order_details.get('status') != 'paid':
                flash(f"Razorpay order status is '{order_details.get('status')}', not 'paid'. No payment was captured.", 'warning')
                return redirect(url_for('payment.user_subscriptions'))

            # Fetch payments for this order
            payments_list = razorpay_client.order.payments(order_id)
            captured_payment = None

            for rp in payments_list.get('items', []):
                if rp.get('status') in ('captured', 'authorized'):
                    captured_payment = rp
                    break

            if not captured_payment:
                flash('No captured payment found for this order on Razorpay.', 'warning')
                return redirect(url_for('payment.user_subscriptions'))

            razorpay_payment_id = captured_payment['id']
            paid_amount = captured_payment['amount']  # in paise
            expected_amount = int(payment.total_amount * 100)

            # Verify amount
            if paid_amount != expected_amount:
                current_app.logger.error(
                    f"Recovery: Amount mismatch. Expected {expected_amount}, got {paid_amount}"
                )
                flash(f'Amount mismatch: paid Rs.{paid_amount/100} but expected Rs.{payment.total_amount}. Contact support.', 'danger')
                return redirect(url_for('payment.user_subscriptions'))

            # Payment is valid - process it
            payment.razorpay_payment_id = razorpay_payment_id
            payment.status = 'completed'
            payment.notes = (payment.notes or '') + f"\nRecovered via /payment/recover at {datetime.now(UTC).isoformat()}"

            # Create subscription
            subscription = db.session.get(Subscription, payment.subscription_id)
            if subscription:
                start_date = datetime.now(UTC)
                end_date = start_date + timedelta(days=subscription.days)

                new_sub = SubscribedUser(
                    U_ID=user_id,
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
                    reactivate_user_paused_tokens(user_id, new_sub.id)
                except Exception:
                    pass

                # History
                history = SubscriptionHistory(
                    U_ID=user_id,
                    S_ID=subscription.S_ID,
                    action='new',
                    created_at=datetime.now(UTC)
                )
                db.session.add(history)

            db.session.commit()

            current_app.logger.info(
                f"Payment recovered: order={order_id}, payment={razorpay_payment_id}, user={user_id}"
            )

            # Send confirmation email
            try:
                from services.email import send_payment_confirmation_email
                user = db.session.get(User, user_id)
                if user and subscription:
                    send_payment_confirmation_email(user, payment, subscription)
            except Exception:
                pass

            flash(f'Payment recovered successfully! Your {subscription.plan} subscription is now active.', 'success')
            return redirect(url_for('payment.user_subscriptions'))

        except Exception as rp_error:
            current_app.logger.error(f"Razorpay API error during recovery: {str(rp_error)}")
            flash(f'Error checking Razorpay: {str(rp_error)}. Contact support.', 'danger')
            return redirect(url_for('payment.user_subscriptions'))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Payment recovery error: {str(e)}")
        flash('Error recovering payment. Contact support.', 'danger')
        return redirect(url_for('payment.user_subscriptions'))
