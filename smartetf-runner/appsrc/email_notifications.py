import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()


def get_email_config():
    """Get email configuration from database or fall back to environment variables"""
    try:
        # Try to import models and get EmailSettings from database
        import sys
        parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        from models import EmailSettings
        from app import app
        with app.app_context():
            settings = EmailSettings.query.first()
            if settings:
                cfg = settings.get_smtp_config()
                return {
                    'sender_email': cfg['email'],
                    'sender_name': cfg.get('sender_name', 'SmartETF Algo'),
                    'smtp_server': cfg['server'],
                    'smtp_port': cfg['port'],
                    'smtp_user': cfg['email'],
                    'smtp_pass': cfg['password'],
                    'use_ssl': cfg['use_ssl']
                }
    except Exception as e:
        print(f"⚠️ Could not load EmailSettings from DB: {e}")
    
    # Fall back to environment variables
    return {
        'sender_email': os.getenv('ADMIN_EMAIL', 'smartetfalgo@gmail.com'),
        'sender_name': os.getenv('SENDER_NAME', 'SmartETF Algo'),
        'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
        'smtp_port': int(os.getenv('SMTP_PORT', '587')),
        'smtp_user': os.getenv('SMTP_USER', os.getenv('ADMIN_EMAIL', 'smartetfalgo@gmail.com')),
        'smtp_pass': os.getenv('SMTP_PASSWORD', 'your_app_password'),
        'use_ssl': os.getenv('SMTP_PORT', '587') == '465'
    }


def _html_to_plain(html):
    """Convert HTML to clean plain text, removing style/script blocks."""
    import re
    text = re.sub(r'(?s)<style[^>]*>.*?</style>', '', html)
    text = re.sub(r'(?s)<script[^>]*>.*?</script>', '', text)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</h[1-6]>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    import html as html_mod
    text = html_mod.unescape(text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def send_email(to_address, subject, body, is_html=False):
    """Send email using SMTP configuration from admin panel settings"""
    import email.utils
    import uuid
    from email.utils import formatdate
    config = get_email_config()
    
    sender_email = config['sender_email']
    sender_name  = config.get('sender_name', 'SmartETF Algo')
    smtp_server  = config['smtp_server']
    smtp_port    = config['smtp_port']
    smtp_user    = config['smtp_user']
    smtp_pass    = config['smtp_pass']
    use_ssl      = config['use_ssl'] or smtp_port == 465

    from_header = email.utils.formataddr((sender_name, sender_email))
    domain = sender_email.split('@')[-1]

    if is_html:
        msg = MIMEMultipart('alternative')
        plain_text = _html_to_plain(body)
        msg.attach(MIMEText(plain_text, 'plain', 'utf-8'))
        msg.attach(MIMEText(body, 'html', 'utf-8'))
    else:
        msg = MIMEText(body, 'plain', 'utf-8')

    msg["Subject"]    = subject
    msg["From"]       = from_header
    msg["To"]         = to_address
    msg["Reply-To"]   = from_header
    msg["Date"]       = formatdate(localtime=True)
    msg["Message-ID"] = f"<{uuid.uuid4().hex}@{domain}>"

    try:
        # Use SSL for port 465 (Zoho), STARTTLS for port 587 (Gmail)
        if smtp_port == 465 or use_ssl:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(sender_email, to_address, msg.as_string())
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(sender_email, to_address, msg.as_string())
        print(f"✅ Email sent to {to_address}")
    except Exception as e:
        print(f"❌ Failed to send email to {to_address}: {e}")


_C = {'navy':'#0f172a','blue':'#1e40af','blue2':'#3b82f6','green':'#059669','gold':'#f59e0b','red':'#dc2626','slate':'#64748b'}

def _brand_email(content_html, accent='blue', subtitle='Automated Investment Platform'):
    ac = {'blue':_C['blue'],'green':_C['green'],'gold':_C['gold'],'red':_C['red']}.get(accent,_C['blue'])
    yr = datetime.now().year
    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"></head>'
        '<body style="margin:0;padding:0;background:#eef2f7;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;">'
        '<table width="100%" cellpadding="0" cellspacing="0" style="background:#eef2f7;padding:24px 0;"><tr><td align="center">'
        '<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">'
        f'<tr><td style="background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%);border-radius:12px 12px 0 0;padding:28px 40px;text-align:center;">'
        f'<span style="font-size:26px;font-weight:800;color:#fff;">Smart</span>'
        f'<span style="font-size:26px;font-weight:800;color:#3b82f6;">ETF</span>'
        f'<span style="font-size:16px;font-weight:600;color:#94a3b8;margin-left:4px;">ALGO</span>'
        f'<div style="width:40px;height:3px;background:{ac};margin:10px auto 6px;border-radius:2px;"></div>'
        f'<p style="margin:0;color:#94a3b8;font-size:12px;">{subtitle}</p></td></tr>'
        f'<tr><td style="height:4px;background:{ac};"></td></tr>'
        f'<tr><td style="background:#fff;padding:36px 40px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">{content_html}</td></tr>'
        f'<tr><td style="background:#0f172a;border-radius:0 0 12px 12px;padding:24px 40px;text-align:center;">'
        f'<p style="margin:0 0 8px;font-size:13px;">'
        f'<a href="mailto:support@smartetfalgo.com" style="color:#3b82f6;text-decoration:none;">support@smartetfalgo.com</a> &nbsp;|&nbsp; '
        f'<a href="tel:+917597583636" style="color:#3b82f6;text-decoration:none;">+91-7597583636</a> &nbsp;|&nbsp; '
        f'<a href="https://smartetfalgo.com" style="color:#3b82f6;text-decoration:none;">smartetfalgo.com</a></p>'
        f'<p style="margin:0;color:#334155;font-size:11px;">&copy; {yr} SmartETF Algo. All rights reserved. Investments subject to market risks.</p>'
        '</td></tr></table></td></tr></table></body></html>'
    )

def _row(label, value):
    return (
        '<tr>'
        f'<td style="padding:9px 0;border-bottom:1px solid #f1f5f9;color:#64748b;font-size:14px;font-weight:600;width:160px;">{label}</td>'
        f'<td style="padding:9px 0;border-bottom:1px solid #f1f5f9;color:#1e293b;font-size:14px;">{value}</td>'
        '</tr>'
    )

def _badge(text, color='blue'):
    bg = {'blue':'#dbeafe','green':'#d1fae5','gold':'#fef3c7','red':'#fee2e2'}.get(color,'#dbeafe')
    fg = {'blue':'#1e40af','green':'#065f46','gold':'#92400e','red':'#991b1b'}.get(color,'#1e40af')
    return f'<span style="background:{bg};color:{fg};font-size:12px;font-weight:700;padding:3px 10px;border-radius:20px;">{text}</span>'

def _btn(text, url, color='blue'):
    bg = {'blue':_C['blue'],'green':_C['green'],'gold':_C['gold']}.get(color,_C['blue'])
    return f'<a href="{url}" style="display:inline-block;background:{bg};color:#fff;text-decoration:none;font-weight:700;font-size:15px;padding:14px 32px;border-radius:8px;">{text}</a>'

def _box(text, kind='info'):
    styles = {
        'info':    'border-left:4px solid #3b82f6;background:#eff6ff;color:#1e40af;',
        'success': 'border-left:4px solid #059669;background:#f0fdf4;color:#065f46;',
        'warning': 'border-left:4px solid #f59e0b;background:#fffbeb;color:#92400e;',
        'danger':  'border-left:4px solid #dc2626;background:#fef2f2;color:#991b1b;',
    }
    s = styles.get(kind, styles['info'])
    return f'<div style="{s}padding:14px 18px;border-radius:0 8px 8px 0;margin:20px 0;font-size:14px;">{text}</div>'


def send_verification_email(user_email, user_name, verification_token):
    link = f"https://smartetfalgo.com/verify-email/{verification_token}"
    content = (
        f'<h2 style="margin:0 0 4px;color:#0f172a;font-size:22px;">Welcome, {user_name}!</h2>'
        f'<p style="margin:0 0 20px;color:#64748b;">Verify your email to activate your SmartETF account.</p>'
        + _box('<strong>One more step:</strong> Please verify your email address to start automated investing.', 'info')
        + f'<div style="text-align:center;margin:28px 0;">' + _btn('Verify Email Address', link, 'blue') + '</div>'
        + f'<p style="color:#64748b;font-size:13px;">Or paste: <a href="{link}" style="color:#3b82f6;word-break:break-all;">{link}</a><br><br>Link expires in <strong>24 hours</strong>.</p>'
    )
    try:
        send_email(user_email, 'Verify Your Email - SmartETF Algo', _brand_email(content, 'blue', 'Email Verification'), is_html=True)
        print(f"✅ Verification email sent to {user_email}")
    except Exception as e:
        print(f"❌ Error sending verification email: {e}")


def send_new_registration_notification(user_data):
    admin_email = os.getenv('ADMIN_EMAIL', 'support@smartetfalgo.com')
    rows = ''.join([
        _row('Full Name', user_data['full_name']),
        _row('Username', user_data['username']),
        _row('Email', user_data['email']),
        _row('Phone', user_data.get('mobile', '—')),
        _row('City / State', f"{user_data.get('city','—')} / {user_data.get('state','—')}"),
        _row('Customer ID', user_data.get('customer_id', '—')),
        _row('Registered', datetime.now().strftime('%d %b %Y, %I:%M %p IST')),
    ])
    content = (
        '<h2 style="margin:0 0 4px;color:#0f172a;font-size:22px;">New User Registered</h2>'
        '<p style="margin:0 0 20px;color:#64748b;font-size:14px;">A new customer signed up on SmartETF.</p>'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{rows}</table>'
    )
    try:
        send_email(admin_email, f"New Registration - {user_data['full_name']}", _brand_email(content, 'blue', 'Admin Notification'), is_html=True)
    except Exception as e:
        print(f"❌ Registration notification failed: {e}")


def send_admin_alert_email(subject, message):
    admin_email = os.getenv('ADMIN_EMAIL', 'support@smartetfalgo.com')
    content = (
        '<h2 style="margin:0 0 4px;color:#dc2626;font-size:22px;">System Alert</h2>'
        f'<p style="margin:0 0 20px;color:#64748b;font-size:13px;">{datetime.now().strftime("%d %b %Y, %I:%M %p IST")}</p>'
        + _box(f'<strong>{subject}</strong>', 'danger')
        + '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:20px;">'
        + f'<pre style="margin:0;white-space:pre-wrap;font-family:monospace;font-size:13px;color:#1e293b;">{message}</pre></div>'
    )
    send_email(admin_email, f'[SmartETF Alert] {subject}', _brand_email(content, 'red', 'System Monitor'), is_html=True)


def send_health_check_email(success: bool, summary: str):
    admin_email = os.getenv('ADMIN_EMAIL', 'support@smartetfalgo.com')
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    accent = 'green' if success else 'red'
    badge = _badge('HEALTHY', 'green') if success else _badge('ISSUES DETECTED', 'red')
    content = (
        f'<h2 style="margin:0 0 8px;color:#0f172a;font-size:22px;">Health Check &nbsp;{badge}</h2>'
        f'<p style="margin:0 0 20px;color:#64748b;font-size:13px;">{datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")}</p>'
        '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:20px;">'
        f'<pre style="margin:0;white-space:pre-wrap;font-family:monospace;font-size:13px;color:#1e293b;line-height:1.6;">{summary}</pre></div>'
    )
    send_email(admin_email, f"SmartETF Health - {'Healthy' if success else 'Issues Detected'}",
               _brand_email(content, accent, 'System Health Report'), is_html=True)


def send_execution_email(success: bool, metrics: dict, files: dict, mode: str, started_at_utc, ended_at_utc, pid=None, log_path=None):
    admin_email = os.getenv('ADMIN_EMAIL', 'support@smartetfalgo.com')
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    def ti(dt):
        try: return dt.astimezone(IST).strftime('%d %b %Y, %I:%M:%S %p IST')
        except: return '—'
    def sv(v): return v if v not in (None, '') else '—'
    accent = 'green' if success else 'red'
    badge = _badge('SUCCESS', 'green') if success else _badge('FAILED', 'red')
    rows = ''.join([
        _row('Mode', mode),
        _row('Started', ti(started_at_utc)),
        _row('Ended', ti(ended_at_utc)),
        _row('Clients', sv(metrics.get('total_clients'))),
        _row('Passed / Failed', f"{sv(metrics.get('passed'))} / {sv(metrics.get('failed'))}"),
        _row('Orders OK / Fail', f"{sv(metrics.get('ok_orders'))} / {sv(metrics.get('fail_orders'))}"),
    ])
    fhtml = ''.join([f'<li style="font-size:13px;color:#64748b;">{k}: <code>{v}</code></li>' for k, v in (files or {}).items() if v])
    content = (
        f'<h2 style="margin:0 0 8px;color:#0f172a;font-size:22px;">Execution Summary &nbsp;{badge}</h2>'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{rows}</table>'
        + (f'<h3 style="margin:20px 0 8px;color:#0f172a;">Files</h3><ul>{fhtml}</ul>' if fhtml else '')
    )
    send_email(admin_email, f"SmartETF Execution - {'Success' if success else 'Failed'}",
               _brand_email(content, accent, 'Execution Report'), is_html=True)


def send_client_notification_email(client_email, subject, message):
    content = (
        f'<h2 style="margin:0 0 20px;color:#0f172a;font-size:20px;">{subject}</h2>'
        '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:20px;">'
        f'<pre style="margin:0;white-space:pre-wrap;font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;font-size:14px;color:#1e293b;line-height:1.7;">{message}</pre></div>'
    )
    send_email(client_email, subject, _brand_email(content, 'blue'), is_html=True)


def send_password_expiry_warning(user_email, user_name, broker_name, days_remaining):
    accent = 'red' if days_remaining <= 3 else 'gold'
    kind = 'danger' if days_remaining <= 3 else 'warning'
    content = (
        f'<h2 style="margin:0 0 4px;color:#0f172a;font-size:22px;">Hi {user_name},</h2>'
        '<p style="margin:0 0 20px;color:#64748b;">Your broker password needs attention.</p>'
        + _box(f'<strong>{broker_name} password expires in {days_remaining} day(s).</strong> Update now to avoid trading interruptions.', kind)
        + f'<div style="text-align:center;margin:28px 0;">' + _btn('Update Password', 'https://smartetfalgo.com/dashboard', 'gold') + '</div>'
    )
    try:
        send_email(user_email, f'Action Required: {broker_name} Password Expires in {days_remaining} Days',
                   _brand_email(content, accent, 'Security Reminder'), is_html=True)
    except Exception as e:
        print(f"❌ Password expiry warning failed: {e}")


def send_broker_added_success_email(user_data, broker_data):
    admin_email = os.getenv('ADMIN_EMAIL', 'support@smartetfalgo.com')
    sip = broker_data.get('monthly_sip_target', 0)
    rows = ''.join([
        _row('Broker', broker_data['broker_name']),
        _row('Monthly SIP', f'<strong style="color:#059669;font-size:18px;">&#8377;{sip:,.2f}</strong>'),
        _row('Status', _badge('Active', 'green')),
    ])
    content = (
        f'<h2 style="margin:0 0 4px;color:#0f172a;font-size:22px;">Congratulations, {user_data["full_name"]}!</h2>'
        '<p style="margin:0 0 20px;color:#64748b;">Your broker is connected and algo investment is now active.</p>'
        + _box(f'<strong>{broker_data["broker_name"]}</strong> linked successfully. ' + _badge('ACTIVE', 'green'), 'success')
        + f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:20px 0;">{rows}</table>'
        + f'<div style="text-align:center;margin:28px 0;">' + _btn('View Dashboard', 'https://smartetfalgo.com/dashboard', 'blue') + '</div>'
    )
    try:
        send_email(user_data['email'], 'Your Algo Investment Has Started!',
                   _brand_email(content, 'green', 'Welcome to SmartETF Algo'), is_html=True)
        print(f"✅ Broker addition email sent to {user_data['email']}")
        admin_rows = ''.join([_row(l, v) for l, v in [
            ('Customer', user_data['full_name']), ('Email', user_data['email']),
            ('Broker', broker_data['broker_name']), ('SIP', f"&#8377;{sip:,.2f}")
        ]])
        send_email(admin_email, f"New Broker: {user_data['full_name']} - {broker_data['broker_name']}",
                   _brand_email('<h2 style="margin:0 0 20px;color:#0f172a;">New Broker Connected</h2>'
                                f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{admin_rows}</table>',
                                'green', 'Admin Notification'), is_html=True)
    except Exception as e:
        print(f"❌ Broker addition email failed: {e}")


def send_copy_trading_enabled_email(user_data):
    admin_email = os.getenv('ADMIN_EMAIL', 'support@smartetfalgo.com')
    content = (
        f'<h2 style="margin:0 0 4px;color:#0f172a;font-size:22px;">Hi {user_data["full_name"]},</h2>'
        '<p style="margin:0 0 20px;color:#64748b;">Your algo investment is now live!</p>'
        + _box('Algo Investment is <strong>ACTIVE</strong>. ' + _badge('LIVE', 'green') + ' Investments execute automatically every trading day.', 'success')
        + f'<div style="text-align:center;margin:28px 0;">' + _btn('View Dashboard', 'https://smartetfalgo.com/dashboard', 'green') + '</div>'
    )
    try:
        send_email(user_data['email'], f"Algo Investment Activated - {user_data['full_name']}",
                   _brand_email(content, 'green', 'Account Activation'), is_html=True)
    except Exception as e:
        print(f"❌ Copy trading email failed: {e}")


def generate_purchase_invoice_pdf(invoice_data):
    import io
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    elements = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('T', parent=styles['Heading1'], fontSize=24, textColor=colors.HexColor('#1e40af'), alignment=TA_CENTER)
    h2 = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=14, textColor=colors.HexColor('#0f172a'))
    elements.append(Paragraph("SmartETF Algo", title_style))
    elements.append(Paragraph("Payment Receipt & Invoice", styles['Normal']))
    elements.append(Spacer(1, 0.3*inch))
    for lbl, val in [('Invoice #', invoice_data.get('invoice_number','N/A')), ('Date', invoice_data.get('invoice_date', datetime.now().strftime('%d %B %Y')))]:
        t = Table([[lbl+':', val]], colWidths=[2*inch, 3*inch])
        t.setStyle(TableStyle([('FONTNAME',(0,0),(0,-1),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),10),('TEXTCOLOR',(0,0),(0,-1),colors.grey)]))
        elements.append(t)
    elements.append(Spacer(1, 0.2*inch))
    elements.append(Paragraph("BILL TO", h2))
    ct = Table([[l+':', invoice_data.get(k,'N/A')] for l,k in [('Name','user_name'),('Email','user_email'),('Mobile','user_mobile')]], colWidths=[2*inch,4*inch])
    ct.setStyle(TableStyle([('FONTNAME',(0,0),(0,-1),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),10)]))
    elements.append(ct)
    elements.append(Spacer(1, 0.3*inch))
    elements.append(Paragraph("SUBSCRIPTION DETAILS", h2))
    pt = Table([['Plan','Billing Cycle','Amount'],[invoice_data.get('plan_name','N/A'),invoice_data.get('billing_cycle','N/A'),f"Rs.{invoice_data.get('amount',0):,.2f}"]], colWidths=[2.5*inch,2*inch,1.5*inch])
    pt.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1e40af')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('ALIGN',(0,0),(-1,-1),'CENTER'),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),10),('GRID',(0,0),(-1,-1),1,colors.grey)]))
    elements.append(pt)
    elements.append(Spacer(1,0.3*inch))
    tt = Table([['Total Amount Paid:', f"Rs.{invoice_data.get('amount',0):,.2f}"]], colWidths=[4*inch,2*inch])
    tt.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),12),('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f0f4f8')),('BOX',(0,0),(-1,-1),2,colors.HexColor('#1e40af'))]))
    elements.append(tt)
    elements.append(Spacer(1,0.4*inch))
    elements.append(Paragraph("Thank you for choosing SmartETF Algo! support@smartetfalgo.com | +91-7597583636", styles['Normal']))
    doc.build(elements)
    buffer.seek(0)
    return buffer


def send_purchase_confirmation_admin(purchase_data):
    admin_email = os.getenv('ADMIN_EMAIL', 'support@smartetfalgo.com')
    rows = ''.join([_row(l, v) for l, v in [
        ('Customer', purchase_data['user_name']), ('Email', purchase_data['user_email']),
        ('Plan', purchase_data['plan_name']), ('Billing', purchase_data['billing_cycle'].title()),
        ('Amount', f'<strong style="color:#059669;font-size:18px;">&#8377;{purchase_data["amount"]:,.2f}</strong>'),
        ('Valid Until', str(purchase_data.get('expiry_date', '—'))),
        ('Invoice #', purchase_data.get('invoice_number', '—')),
        ('Payment ID', purchase_data.get('payment_id', '—')),
    ]])
    content = (
        '<h2 style="margin:0 0 4px;color:#0f172a;font-size:22px;">New Purchase &nbsp;' + _badge('PAID', 'green') + '</h2>'
        f'<p style="margin:0 0 20px;color:#64748b;font-size:13px;">{datetime.now().strftime("%d %b %Y, %I:%M %p IST")}</p>'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{rows}</table>'
    )
    try:
        send_email(admin_email, f"New Purchase: {purchase_data['user_name']} - Rs.{purchase_data['amount']:,.2f}",
                   _brand_email(content, 'green', 'Admin - Sales'), is_html=True)
    except Exception as e:
        print(f"❌ Purchase admin email failed: {e}")


def send_purchase_confirmation_client(purchase_data):
    from email.mime.application import MIMEApplication
    user_email = purchase_data['user_email']
    user_name = purchase_data['user_full_name']
    subject = f"Welcome to SmartETF - Invoice #{purchase_data.get('invoice_number','N/A')}"
    rows = ''.join([_row(l, v) for l, v in [
        ('Plan', f'<strong>{purchase_data["plan_name"]}</strong>'),
        ('Billing', purchase_data['billing_cycle'].title()),
        ('Amount', f'<strong style="color:#059669;font-size:18px;">&#8377;{purchase_data["amount"]:,.2f}</strong>'),
        ('Valid Until', f'<strong>{purchase_data.get("expiry_date","—")}</strong>'),
        ('Invoice #', purchase_data.get('invoice_number', '—')),
    ]])
    content = (
        f'<h2 style="margin:0 0 4px;color:#0f172a;font-size:22px;">Welcome, {user_name}!</h2>'
        '<p style="margin:0 0 20px;color:#64748b;">Your SmartETF subscription is now active.</p>'
        + _box('<strong>Payment Confirmed.</strong> Your invoice is attached as a PDF.', 'success')
        + f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:20px 0;">{rows}</table>'
        + f'<div style="text-align:center;margin:28px 0;">' + _btn('Access Dashboard', 'https://smartetfalgo.com/dashboard', 'blue') + '</div>'
    )
    try:
        invoice_pdf = generate_purchase_invoice_pdf(purchase_data)
        config = get_email_config()
        import email.utils, uuid
        from email.utils import formatdate
        se = config['sender_email']
        sn = config.get('sender_name', 'SmartETF Algo')
        msg = MIMEMultipart('mixed')
        msg['Subject'] = subject
        msg['From'] = email.utils.formataddr((sn, se))
        msg['To'] = user_email
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = f"<{uuid.uuid4().hex}@{se.split('@')[-1]}>"
        html_body = _brand_email(content, 'green', 'Purchase Confirmation')
        alt = MIMEMultipart('alternative')
        alt.attach(MIMEText(_html_to_plain(html_body), 'plain', 'utf-8'))
        alt.attach(MIMEText(html_body, 'html', 'utf-8'))
        msg.attach(alt)
        pa = MIMEApplication(invoice_pdf.read(), _subtype='pdf')
        pa.add_header('Content-Disposition', 'attachment', filename=f'SmartETF_Invoice_{purchase_data.get("invoice_number","N/A")}.pdf')
        msg.attach(pa)
        if config['smtp_port'] == 465 or config['use_ssl']:
            with smtplib.SMTP_SSL(config['smtp_server'], config['smtp_port']) as srv:
                srv.login(config['smtp_user'], config['smtp_pass'])
                srv.sendmail(se, user_email, msg.as_string())
        else:
            with smtplib.SMTP(config['smtp_server'], config['smtp_port']) as srv:
                srv.starttls()
                srv.login(config['smtp_user'], config['smtp_pass'])
                srv.sendmail(se, user_email, msg.as_string())
        print(f"✅ Purchase confirmation+PDF sent to {user_email}")
    except Exception as e:
        print(f"❌ Purchase client email failed: {e}")
        import traceback; traceback.print_exc()


def send_renewal_reminder_email(user_data, days_remaining):
    user_email = user_data['email']
    user_name = user_data.get('full_name') or user_data.get('username', 'Valued Customer')
    plan_name = user_data.get('plan_name', 'Current Plan')
    expiry = user_data.get('expiry_date', '—')
    accent = 'red' if days_remaining <= 3 else 'gold'
    kind = 'danger' if days_remaining <= 3 else 'warning'
    rows = ''.join([
        _row('Plan', plan_name),
        _row('Expiry', str(expiry)),
        _row('Days Left', f'<strong style="color:#dc2626;">{days_remaining}</strong>'),
    ])
    content = (
        f'<h2 style="margin:0 0 4px;color:#0f172a;font-size:22px;">Hi {user_name},</h2>'
        '<p style="margin:0 0 20px;color:#64748b;">Your subscription is expiring soon.</p>'
        + _box(f'<strong>{plan_name} expires in {days_remaining} day(s)</strong> on {expiry}. Renew to keep algo investment running.', kind)
        + f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:20px 0;">{rows}</table>'
        + f'<div style="text-align:center;margin:28px 0;">' + _btn('Renew My Plan', 'https://smartetfalgo.com/dashboard', 'blue') + '</div>'
    )
    try:
        send_email(user_email, f'Your {plan_name} Expires in {days_remaining} Days - Renew Now',
                   _brand_email(content, accent, 'Subscription Reminder'), is_html=True)
    except Exception as e:
        print(f"❌ Renewal reminder failed: {e}")


def send_sip_update_notification_email(user_data, new_sip_amount, broker_count):
    user_email = user_data['email']
    user_name = user_data.get('full_name') or user_data.get('username', 'Valued Customer')
    rows = ''.join([
        _row('New SIP Target', f'<strong style="color:#059669;font-size:18px;">&#8377;{new_sip_amount:,.2f}</strong>'),
        _row('Connected Brokers', str(broker_count)),
        _row('Effective From', 'Next session (3:10 PM IST)'),
        _row('Status', _badge('Active', 'green')),
    ])
    content = (
        f'<h2 style="margin:0 0 4px;color:#0f172a;font-size:22px;">Hi {user_name},</h2>'
        '<p style="margin:0 0 20px;color:#64748b;">Your monthly SIP target has been updated.</p>'
        + _box(f'SIP updated to <strong>&#8377;{new_sip_amount:,.2f}</strong> across {broker_count} broker(s).', 'success')
        + f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:20px 0;">{rows}</table>'
        + f'<div style="text-align:center;margin:28px 0;">' + _btn('View Dashboard', 'https://smartetfalgo.com/dashboard', 'blue') + '</div>'
    )
    try:
        send_email(user_email, f'SIP Target Updated - Rs.{new_sip_amount:,.2f}',
                   _brand_email(content, 'green', 'Investment Update'), is_html=True)
    except Exception as e:
        print(f"❌ SIP update email failed: {e}")


def send_client_broker_password_email(user_email, full_name, broker_name, new_password, broker_username):
    first = (full_name.split()[0] if full_name else None) or broker_username
    rows = ''.join([
        _row('Broker', broker_name),
        _row('Username', f'<code style="background:#f1f5f9;padding:2px 8px;border-radius:4px;">{broker_username}</code>'),
        _row('New Password', f'<code style="background:#f1f5f9;padding:2px 8px;border-radius:4px;font-size:15px;font-weight:700;">{new_password}</code>'),
    ])
    content = (
        f'<h2 style="margin:0 0 4px;color:#0f172a;font-size:22px;">Hi {first},</h2>'
        '<p style="margin:0 0 20px;color:#64748b;">Your broker password was automatically rotated.</p>'
        + _box('<strong>No action required.</strong> SmartETF will use the new password automatically for all trades.', 'success')
        + f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:20px 0;">{rows}</table>'
        + _box(f'If you log in to {broker_name} directly, use the new password shown above.', 'warning')
    )
    try:
        send_email(user_email, f'Your {broker_name} Password Has Been Updated',
                   _brand_email(content, 'blue', 'Security Update'), is_html=True)
        print(f"✅ Broker password email sent to {user_email}")
    except Exception as e:
        print(f"❌ Broker password email failed: {e}")


def send_finvasia_password_reset_email(client_email, full_name, customer_id, new_password):
    """Send a branded email to the client when their Finvasia password is auto-rotated."""
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    timestamp = datetime.now(IST).strftime("%d %B %Y at %I:%M %p IST")
    first = (full_name.split()[0] if full_name else None) or customer_id

    rows = "".join([
        _row("Broker", "Finvasia"),
        _row("Customer ID", customer_id),
        _row("New Password", f"<code style=\"background:#f1f5f9;padding:2px 8px;border-radius:4px;font-size:15px;font-weight:700;\">{new_password}</code>"),
        _row("Updated On", timestamp),
    ])
    content = (
        f"<h2 style=\"margin:0 0 4px;color:#0f172a;font-size:22px;\">Hi {first},</h2>"
        "<p style=\"margin:0 0 20px;color:#64748b;\">Your Finvasia trading account password has been automatically updated.</p>"
        + _box("<strong>No action required.</strong> SmartETF has already updated your credentials and your automated investments will continue without interruption.", "success")
        + f"<table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"border-collapse:collapse;margin:20px 0;\">{rows}</table>"
        + _box("Finvasia requires a password reset every <strong>90 days</strong> as part of their security policy. SmartETF detected this and rotated your password automatically.", "info")
        + _box("Please save your new password securely. If you log in to Finvasia directly, use the new password shown above.", "warning")
    )
    try:
        send_email(client_email, "Your Finvasia Password Has Been Updated",
                   _brand_email(content, "blue", "Security Update"), is_html=True)
        print(f"  ✅ Finvasia password reset email sent to {client_email}")
    except Exception as e:
        print(f"  ❌ Finvasia password reset email failed for {client_email}: {e}")
        raise

