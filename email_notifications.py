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
        # Try to import and get settings from database
        from models import EmailSettings
        settings = EmailSettings.query.first()
        if settings and settings.is_active:
            config = settings.get_smtp_config()
            return {
                'sender_email': config['email'],
                'smtp_server': config['server'],
                'smtp_port': config['port'],
                'smtp_user': config['email'],
                'smtp_pass': config['password'],
                'use_ssl': config['use_ssl']
            }
    except Exception:
        pass
    
    # Fall back to environment variables
    sender_email = os.getenv('ADMIN_EMAIL', 'smartetfalgo@gmail.com')
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER', sender_email)
    smtp_pass = os.getenv('SMTP_PASSWORD', 'your_app_password')
    
    return {
        'sender_email': sender_email,
        'smtp_server': smtp_server,
        'smtp_port': smtp_port,
        'smtp_user': smtp_user,
        'smtp_pass': smtp_pass,
        'use_ssl': smtp_port == 465
    }


def send_email(to_address, subject, body, is_html=False):
    """Send email using SMTP configuration from database or environment variables"""
    # Get email configuration
    config = get_email_config()
    sender_email = config['sender_email']
    smtp_server = config['smtp_server']
    smtp_port = config['smtp_port']
    smtp_user = config['smtp_user']
    smtp_pass = config['smtp_pass']
    use_ssl = config['use_ssl']

    if is_html:
        msg = MIMEMultipart('alternative')
        html_part = MIMEText(body, 'html')
        msg.attach(html_part)
    else:
        msg = MIMEText(body)

    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = to_address

    try:
        # Use SSL for port 465 (Zoho), STARTTLS for port 587 (Gmail)
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(sender_email, to_address, msg.as_string())
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(sender_email, to_address, msg.as_string())
        print(f"✅ Email sent to {to_address}")
        return True
    except Exception as e:
        print(f"❌ Failed to send email to {to_address}: {e}")
        return False


def send_verification_email(user_email, user_name, verification_token):
    """Send email verification link to user"""
    verification_link = f"https://smartetfalgo.com/verify-email/{verification_token}"

    subject = "Verify Your Email - SmartETF Algo"

    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
            .button {{ display: inline-block; padding: 15px 30px; background: #667eea; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; }}
            .footer {{ text-align: center; padding: 20px; color: #777; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Welcome to SmartETF Algo!</h1>
            </div>
            <div class="content">
                <h2>Hi {user_name},</h2>
                <p>Thanks for registering with SmartETF Algo. Please verify your email address to activate your account.</p>

                <div style="text-align: center; margin: 30px 0;">
                    <a href="{verification_link}" class="button">Verify Email Address</a>
                </div>

                <p style="color: #666; font-size: 14px;">Or copy and paste this link in your browser:<br>
                <a href="{verification_link}">{verification_link}</a></p>

                <p style="margin-top: 30px;">This link will expire in 24 hours.</p>

                <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">

                <p><strong>Need Help?</strong><br>
                Email: smartetfalgo@gmail.com<br>
                Whatsapp/Phone: +91-7597583636 (10 AM - 5 PM)</p>
            </div>
            <div class="footer">
                <p>© 2025 SmartETF Algo. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """

    try:
        send_email(user_email, subject, html_body, is_html=True)
        print(f"✅ Verification email sent to {user_email}")
    except Exception as e:
        print(f"❌ Error sending verification email: {e}")


def send_new_registration_notification(user_data):
    """Send email notification to admin when a new user registers"""
    admin_email = os.getenv('ADMIN_EMAIL', 'admin@smartetf.com')

    subject = f"🎉 New User Registration - {user_data['full_name']}"

    # Create a nicely formatted HTML email
    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0; text-align: center; }}
            .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; }}
            .user-info {{ background: white; padding: 20px; border-radius: 6px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .info-row {{ display: flex; margin: 10px 0; padding: 8px 0; border-bottom: 1px solid #eee; }}
            .info-label {{ font-weight: bold; color: #555; width: 140px; }}
            .info-value {{ color: #333; }}
            .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 20px; }}
            .highlight {{ background: #e3f2fd; padding: 15px; border-left: 4px solid #2196f3; margin: 15px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎉 New User Registration</h1>
                <p>SmartETF Platform</p>
            </div>

            <div class="content">
                <div class="highlight">
                    <strong>A new user has successfully registered on the SmartETF platform!</strong>
                </div>

                <div class="user-info">
                    <h3 style="margin-top: 0; color: #2196f3;">📋 User Details</h3>

                    <div class="info-row">
                        <div class="info-label">👤 Full Name:</div>
                        <div class="info-value">{user_data['full_name']}</div>
                    </div>

                    <div class="info-row">
                        <div class="info-label">👤 Username:</div>
                        <div class="info-value">{user_data['username']}</div>
                    </div>

                    <div class="info-row">
                        <div class="info-label">📧 Email:</div>
                        <div class="info-value">{user_data['email']}</div>
                    </div>

                    <div class="info-row">
                        <div class="info-label">📱 Phone:</div>
                        <div class="info-value">{user_data['mobile']}</div>
                    </div>

                    <div class="info-row">
                        <div class="info-label">🏠 Address:</div>
                        <div class="info-value">{user_data['address']}</div>
                    </div>

                    <div class="info-row">
                        <div class="info-label">🏙️ City:</div>
                        <div class="info-value">{user_data['city']}</div>
                    </div>

                    <div class="info-row">
                        <div class="info-label">🗺️ State:</div>
                        <div class="info-value">{user_data['state']}</div>
                    </div>

                    <div class="info-row">
                        <div class="info-label">📮 PIN Code:</div>
                        <div class="info-value">{user_data['pin']}</div>
                    </div>

                    <div class="info-row">
                        <div class="info-label">🆔 Customer ID:</div>
                        <div class="info-value">{user_data['customer_id']}</div>
                    </div>

                    <div class="info-row">
                        <div class="info-label">⏰ Registration Time:</div>
                        <div class="info-value">{datetime.now().strftime('%d %B %Y at %I:%M %p IST')}</div>
                    </div>
                </div>

                <div class="highlight">
                    <p><strong>💡 Next Steps:</strong></p>
                    <ul>
                        <li>User can now log in to the platform</li>
                        <li>They can connect their broker accounts</li>
                        <li>Ready to subscribe to investment plans</li>
                    </ul>
                </div>
            </div>

            <div class="footer">
                <p>This is an automated notification from SmartETF Platform</p>
                <p>Generated on {datetime.now().strftime('%d %B %Y at %I:%M %p IST')}</p>
            </div>
        </div>
    </body>
    </html>
    """

    try:
        send_email(to_address=admin_email, subject=subject, body=html_body, is_html=True)
        print(f"✅ New registration notification sent to admin: {user_data['full_name']} ({user_data['email']})")
    except Exception as e:
        print(f"❌ Failed to send registration notification: {e}")


def send_admin_alert_email(subject, message):
    """Send alert email to admin with system issues"""
    admin_email = os.getenv('ADMIN_EMAIL', 'admin@smartetf.com')

    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .alert-header {{ background: #dc3545; color: white; padding: 15px; border-radius: 5px; }}
            .alert-content {{ background: #f8d7da; padding: 20px; border-radius: 5px; margin: 10px 0; border-left: 4px solid #dc3545; }}
            .info {{ margin: 10px 0; }}
            .footer {{ color: #666; font-size: 12px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="alert-header">
            <h2>🚨 SmartETF System Alert</h2>
        </div>

        <div class="alert-content">
            <h3>{subject}</h3>
            <pre style="white-space: pre-wrap; font-family: Arial, sans-serif;">{message}</pre>
        </div>

        <div class="info">
            <strong>Timestamp:</strong> {datetime.now().strftime('%d %B %Y, %I:%M %p IST')}<br>
            <strong>Server:</strong> SmartETF Production System
        </div>

        <div class="footer">
            <p>This is an automated alert from SmartETF monitoring system.</p>
            <p>Please review and take appropriate action if required.</p>
        </div>
    </body>
    </html>
    """

    send_email(admin_email, f"[SmartETF Alert] {subject}", html_body, is_html=True)


def send_health_check_email(success: bool, summary: str):
    """Send Health Check email with green header on success, red on failure."""
    admin_email = os.getenv('ADMIN_EMAIL', 'admin@smartetf.com')
    header_bg = '#28a745' if success else '#dc3545'
    content_bg = '#d4edda' if success else '#f8d7da'
    border = '#28a745' if success else '#dc3545'
    title = 'Health Check'
    # Use IST time
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .header {{ background: {header_bg}; color: white; padding: 15px; border-radius: 5px; }}
            .content {{ background: {content_bg}; padding: 20px; border-radius: 5px; margin: 10px 0; border-left: 4px solid {border}; }}
            .info {{ margin: 10px 0; }}
            .footer {{ color: #666; font-size: 12px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>{title}</h2>
        </div>
        <div class="content">
            <pre style="white-space: pre-wrap; font-family: Arial, sans-serif;">{summary}</pre>
        </div>
        <div class="info">
            <strong>Timestamp:</strong> {datetime.now(IST).strftime('%d %B %Y, %I:%M %p IST')}
        </div>
    </body>
    </html>
    """
    send_email(admin_email, title, html_body, is_html=True)


def send_execution_email(success: bool, metrics: dict, files: dict, mode: str, started_at_utc, ended_at_utc,
                         pid: int | None = None, log_path: str | None = None):
    """Send Execution Summary email (green on success, red on failure) with totals and file links.
    - metrics: {total_clients, passed, failed, total_orders, ok_orders, fail_orders}
    - files: {zip_file, etf_csv, user_csv, todays_etf}
    Times are displayed in IST.
    """
    admin_email = os.getenv('ADMIN_EMAIL', 'admin@smartetf.com')
    header_bg = '#28a745' if success else '#dc3545'
    content_bg = '#d4edda' if success else '#f8d7da'
    border = '#28a745' if success else '#dc3545'
    title = 'Execution Summary'

    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))

    try:
        start_ist = started_at_utc.astimezone(IST) if hasattr(started_at_utc, 'astimezone') else None
    except Exception:
        start_ist = None
    try:
        end_ist = ended_at_utc.astimezone(IST) if hasattr(ended_at_utc, 'astimezone') else None
    except Exception:
        end_ist = None

    def safe(v, default='—'):
        return v if v not in (None, '') else default

    totals_html = f"""
    <ul>
      <li><strong>Mode:</strong> {mode}</li>
      <li><strong>Total Clients:</strong> {safe(metrics.get('total_clients'))}</li>
      <li><strong>Passed:</strong> {safe(metrics.get('passed'))} &nbsp; <strong>Failed:</strong> {safe(metrics.get('failed'))}</li>
      <li><strong>Total Orders:</strong> {safe(metrics.get('total_orders'))} &nbsp; <strong>OK:</strong> {safe(metrics.get('ok_orders'))} &nbsp; <strong>Fail:</strong> {safe(metrics.get('fail_orders'))}</li>
    </ul>
    """

    files_html = "<ul>"
    if files.get('zip_file'):
        files_html += f"<li><strong>ZIP:</strong> {files['zip_file']}</li>"
    if files.get('etf_csv'):
        files_html += f"<li><strong>ETF Orders CSV:</strong> {files['etf_csv']}</li>"
    if files.get('user_csv'):
        files_html += f"<li><strong>User Tracking CSV:</strong> {files['user_csv']}</li>"
    if files.get('todays_etf'):
        files_html += f"<li><strong>Today\'s ETF:</strong> {files['todays_etf']}</li>"
    files_html += "</ul>"

    meta_html = "<ul>"
    if pid is not None:
        meta_html += f"<li><strong>PID:</strong> {pid}</li>"
    if log_path:
        meta_html += f"<li><strong>Log:</strong> {log_path}</li>"
    if start_ist:
        meta_html += f"<li><strong>Started:</strong> {start_ist.strftime('%d %B %Y, %I:%M %p IST')}</li>"
    if end_ist:
        meta_html += f"<li><strong>Ended:</strong> {end_ist.strftime('%d %B %Y, %I:%M %p IST')}</li>"
    meta_html += "</ul>"

    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .header {{ background: {header_bg}; color: white; padding: 15px; border-radius: 5px; }}
            .content {{ background: {content_bg}; padding: 20px; border-radius: 5px; margin: 10px 0; border-left: 4px solid {border}; }}
            .section {{ margin-top: 10px; }}
            .footer {{ color: #666; font-size: 12px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>{title}</h2>
        </div>
        <div class="content">
            <h3>Totals</h3>
            {totals_html}
            <div class="section">
                <h3>Files</h3>
                {files_html}
            </div>
            <div class="section">
                <h3>Run Details</h3>
                {meta_html}
            </div>
        </div>
        <div class="footer">
            <p>Timestamp: {datetime.now(IST).strftime('%d %B %Y, %I:%M %p IST')}</p>
        </div>
    </body>
    </html>
    """

    subject = "✅ Execution Success" if success else "🚨 Execution Failed"
    send_email(admin_email, subject, html_body, is_html=True)


def send_client_notification_email(client_email, subject, message):
    """Send notification email to client"""
    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .header {{ background: #007bff; color: white; padding: 15px; border-radius: 5px; }}
            .content {{ background: #f8f9fa; padding: 20px; border-radius: 5px; margin: 10px 0; }}
            .footer {{ color: #666; font-size: 12px; margin-top: 20px; border-top: 1px solid #ddd; padding-top: 10px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>SmartETF Notification</h2>
        </div>

        <div class="content">
            <pre style="white-space: pre-wrap; font-family: Arial, sans-serif;">{message}</pre>
        </div>

        <div class="footer">
            <p>Best regards,<br>SmartETF Team</p>
            <p style="font-size: 10px; color: #999;">This is an automated notification. Please do not reply to this email.</p>
        </div>
    </body>
    </html>
    """

    send_email(client_email, subject, html_body, is_html=True)


def send_password_expiry_warning(user_email, user_name, broker_name, days_remaining):
    """Send password expiry warning to user"""
    subject = f"🔔 Broker Password Expiry Warning - {broker_name}"

    message = f"""
Dear {user_name},

Your {broker_name} broker password will expire in {days_remaining} days.

To ensure uninterrupted automated trading, please update your broker credentials:

1. Login to your SmartETF dashboard
2. Go to Broker Management  
3. Update your {broker_name} credentials

Important: {broker_name} requires password changes every 3 months for security.

Update now to avoid any trading interruptions.

Login: [Your Dashboard URL]
    """

    send_client_notification_email(user_email, subject, message)


def send_finvasia_password_reset_email(client_email, full_name, customer_id, new_password):
    """Send a styled HTML email to the client when their Finvasia password is auto-rotated."""
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    timestamp = datetime.now(IST).strftime('%d %B %Y at %I:%M %p IST')

    subject = "Your Finvasia Trading Account Password Has Been Updated"

    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; background: #f0f4f8; }}
            .wrapper {{ padding: 30px 15px; }}
            .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
            .header {{ background: linear-gradient(135deg, #1a237e 0%, #1976d2 100%); color: white; padding: 32px 30px; text-align: center; }}
            .header-icon {{ font-size: 48px; margin-bottom: 10px; }}
            .header h1 {{ margin: 0; font-size: 22px; font-weight: 700; }}
            .header p {{ margin: 8px 0 0 0; font-size: 14px; opacity: 0.85; }}
            .content {{ padding: 30px; }}
            .greeting {{ font-size: 16px; margin-bottom: 16px; }}
            .info-box {{ background: #e3f2fd; border-left: 4px solid #1976d2; border-radius: 6px; padding: 16px 20px; margin: 20px 0; }}
            .info-box p {{ margin: 0 0 6px 0; font-size: 14px; color: #1a237e; }}
            .password-box {{ background: #f3f0ff; border: 2px dashed #7c4dff; border-radius: 8px; padding: 18px 20px; margin: 20px 0; text-align: center; }}
            .password-box .label {{ font-size: 12px; color: #7c4dff; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 6px; }}
            .password-box .pw {{ font-size: 26px; font-weight: 900; color: #1a237e; letter-spacing: 2px; font-family: monospace; }}
            .password-box .note {{ font-size: 12px; color: #666; margin-top: 8px; }}
            .success-banner {{ background: #e8f5e9; border-left: 4px solid #43a047; border-radius: 6px; padding: 14px 18px; margin: 20px 0; display: flex; align-items: flex-start; }}
            .success-banner .icon {{ font-size: 20px; margin-right: 12px; flex-shrink: 0; }}
            .success-banner p {{ margin: 0; font-size: 14px; color: #1b5e20; }}
            .steps {{ background: #fafafa; border-radius: 8px; padding: 18px 20px; margin: 20px 0; }}
            .steps h4 {{ margin: 0 0 10px 0; color: #1976d2; font-size: 14px; }}
            .steps ul {{ margin: 0; padding-left: 20px; font-size: 14px; color: #555; }}
            .steps ul li {{ margin-bottom: 6px; }}
            .support {{ margin: 24px 0 0 0; padding-top: 20px; border-top: 1px solid #e5e7eb; font-size: 14px; color: #555; }}
            .support strong {{ color: #1976d2; }}
            .footer {{ background: #f9f9f9; text-align: center; padding: 18px; font-size: 12px; color: #999; border-top: 1px solid #eee; }}
            .footer a {{ color: #1976d2; text-decoration: none; }}
        </style>
    </head>
    <body>
        <div class="wrapper">
            <div class="container">
                <div class="header">
                    <div class="header-icon">🔐</div>
                    <h1>Finvasia Password Auto-Updated</h1>
                    <p>SmartETF Algo — Automated Security Maintenance</p>
                </div>

                <div class="content">
                    <p class="greeting">Dear <strong>{full_name or customer_id}</strong>,</p>

                    <div class="info-box">
                        <p>Your Finvasia trading account password has been <strong>automatically updated</strong> by SmartETF Algo as part of Finvasia's 90-day security policy.</p>
                        <p style="margin:0; font-size:13px; color:#555;">No action is required on your part. Your account remains fully operational.</p>
                    </div>

                    <div class="password-box">
                        <div class="label">Your New Password</div>
                        <div class="pw">{new_password}</div>
                        <div class="note">Please save this password securely for your records.</div>
                    </div>

                    <div class="success-banner">
                        <span class="icon">✅</span>
                        <p>Your account has been verified and is <strong>active</strong>. SmartETF Algo will continue executing your automated investments without interruption.</p>
                    </div>

                    <div class="steps">
                        <h4>ℹ️ Why did this happen?</h4>
                        <ul>
                            <li>Finvasia requires all users to reset their password every <strong>90 days</strong>.</li>
                            <li>SmartETF Algo detected the expiry and rotated your password automatically to prevent missed orders.</li>
                            <li>Your new password has been securely stored in our system.</li>
                        </ul>
                    </div>

                    <div class="support">
                        <p><strong>Need Help?</strong><br>
                        Email: <a href="mailto:smartetfalgo@gmail.com">smartetfalgo@gmail.com</a><br>
                        WhatsApp / Phone: <strong>+91-7597583636</strong><br>
                        Timings: 10:00 AM – 5:00 PM (Mon–Fri)</p>
                        <p style="font-size:13px; color:#888;">Customer ID: {customer_id} &nbsp;|&nbsp; Updated: {timestamp}</p>
                    </div>
                </div>

                <div class="footer">
                    <p>© 2025 SmartETF Algo. All rights reserved.</p>
                    <p><a href="https://smartetfalgo.com/">smartetfalgo.com</a> &nbsp;|&nbsp; This is an automated notification. Please do not reply to this email.</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    try:
        send_email(client_email, subject, html_body, is_html=True)
        print(f"  ✅ Password reset email sent to {client_email}")
    except Exception as e:
        print(f"  ❌ Failed to send password reset email to {client_email}: {e}")


def send_broker_added_success_email(user_data, broker_data):
    """Send email when broker is successfully added"""
    subject = f"🎉 Your Future-Proof Algo Investment Has Started!"

    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
            .highlight {{ background: #e8f5e9; padding: 15px; border-left: 4px solid #4caf50; margin: 20px 0; }}
            .stats {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; }}
            .button {{ display: inline-block; padding: 12px 30px; background: #667eea; color: white; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
            .footer {{ text-align: center; padding: 20px; color: #777; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🚀 Congratulations {user_data['full_name']}!</h1>
                <p style="font-size: 18px; margin: 10px 0;">Your Algo Investment Journey Begins Now</p>
            </div>
            <div class="content">
                <h2 style="color: #667eea;">✅ Broker Successfully Connected</h2>
                <p>Your <strong>{broker_data['broker_name']}</strong> account has been successfully linked to SmartETF Algo.</p>

                <div class="highlight">
                    <h3 style="margin-top: 0;">💰 Monthly SIP Amount: ₹{broker_data.get('monthly_sip_target', 0):,.2f}</h3>
                    <p>Your automated investment journey starts now!</p>
                </div>

                <h3 style="color: #667eea;">📈 Why SmartETF Algo?</h3>
                <div class="stats">
                    <p><strong>🏆 Last Year Performance Comparison:</strong></p>
                    <ul>
                        <li><strong>Mutual Funds Average Return:</strong> 12-15% annually</li>
                        <li><strong>SmartETF Algo Strategy:</strong> <span style="color: #4caf50; font-size: 18px; font-weight: bold;">20-23% potential returns</span></li>
                    </ul>
                    <p style="color: #666; font-size: 14px;">*Past performance doesn't guarantee future results. Investments are subject to market risks.</p>
                </div>

                <h3 style="color: #667eea;">🎯 What Happens Next?</h3>
                <ul>
                    <li>✅ Your account is now active for automated investments</li>
                    <li>📊 Our algorithm will analyze market opportunities daily</li>
                    <li>💼 Smart ETF investments will be executed automatically</li>
                    <li>📈 Track your portfolio growth in real-time on your dashboard</li>
                </ul>

                <div style="text-align: center;">
                    <a href="https://smartetfalgo.com/dashboard" class="button">Visit Your Dashboard</a>
                </div>

                <div style="margin-top: 30px; padding: 20px; background: #fff3cd; border-radius: 8px;">
                    <h4 style="margin-top: 0; color: #856404;">💡 Pro Tip</h4>
                    <p>Check your dashboard regularly to monitor your investment performance and stay updated with our algo recommendations!</p>
                </div>

                <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">

                <h3 style="color: #667eea;">📞 We're Always Here For You</h3>
                <p><strong>Email:</strong> smartetfalgo@gmail.com<br>
                <strong>Customer Care:</strong> +91-7597583636<br>
                <strong>Timings:</strong> 10:00 AM - 5:00 PM (Mon-Fri)</p>

                <p style="margin-top: 30px;">Have questions? Need assistance? Our team is just a call or email away!</p>
            </div>
            <div class="footer">
                <p>© 2025 SmartETF Algo. All rights reserved.</p>
                <p><a href="https://smartetfalgo.com/" style="color: #667eea;">smartetfalgo.com</a></p>
            </div>
        </div>
    </body>
    </html>
    """

    try:
        send_email(user_data['email'], subject, html_body, is_html=True)
        print(f"✅ Broker addition email sent to {user_data['email']}")
    except Exception as e:
        print(f"❌ Error sending broker addition email: {e}")


def send_copy_trading_enabled_email(user_data):
    """Send email notification when algo investment is enabled for a user"""
    admin_email = os.getenv('ADMIN_EMAIL', 'admin@smartetf.com')

    subject = f"✅ Algo Investment Activated - {user_data['full_name']}"

    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .header {{ background: #28a745; color: white; padding: 15px; border-radius: 5px; }}
            .content {{ background: #f8f9fa; padding: 20px; border-radius: 5px; margin: 10px 0; }}
            .info {{ margin: 10px 0; }}
            .footer {{ color: #666; font-size: 12px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>🎉 Algo Investment Successfully Activated!</h2>
        </div>

        <p>Great news! Algo Investment has been activated for a user.</p>

        <div class="content">
            <h3>👤 User Details</h3>
            <div class="info"><strong>Name:</strong> {user_data['full_name']}</div>
            <div class="info"><strong>Email:</strong> {user_data['email']}</div>
            <div class="info"><strong>Customer ID:</strong> {user_data['customer_id']}</div>
            <div class="info"><strong>Username:</strong> {user_data['username']}</div>
            <div class="info"><strong>Mobile:</strong> {user_data.get('mobile', 'Not provided')}</div>
            <div class="info"><strong>City:</strong> {user_data.get('city', 'Not provided')}</div>
            <div class="info"><strong>State:</strong> {user_data.get('state', 'Not provided')}</div>

            <h3>💰 Subscription Details</h3>
            <div class="info"><strong>Monthly SIP Target:</strong> ₹{user_data.get('monthly_sip_target', 8500):,.2f}</div>
            <div class="info"><strong>Plan:</strong> {user_data.get('plan_name', 'Not specified')}</div>
            <div class="info"><strong>Broker Count:</strong> {user_data.get('broker_count', 0)}</div>

            <h3>🔧 Technical Details</h3>
            <div class="info"><strong>Activation Time:</strong> {datetime.now().strftime('%d %B %Y, %I:%M %p IST')}</div>
            <div class="info"><strong>Status:</strong> Ready for automated trading</div>
        </div>

        <p>The user will start receiving automated ETF orders from the next trading session (3:10 PM IST).</p>

        <div class="footer">
            <p>This is an automated notification from SmartETF system.</p>
        </div>
    </body>
    </html>
    """

    try:
        send_email(admin_email, subject, html_body, is_html=True)
        print(f"✅ Algo Investment enabled notification sent to admin")

    except Exception as e:
        print(f"❌ Error sending Algo Investment notification: {e}")


def generate_purchase_invoice_pdf(invoice_data):
    """Generate PDF invoice for subscription purchase

    invoice_data should contain:
    - invoice_number, invoice_date, user_name, user_email, user_mobile
    - plan_name, billing_cycle, amount, start_date, expiry_date
    - referrer_name (optional), commission_amount (optional)
    """
    import io
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5 * inch, bottomMargin=0.5 * inch)

    elements = []
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=24,
                                 textColor=colors.HexColor('#667eea'), alignment=TA_CENTER)
    header_style = ParagraphStyle('CustomHeader', parent=styles['Heading2'], fontSize=16,
                                  textColor=colors.HexColor('#764ba2'))

    # Header
    elements.append(Paragraph("SmartETF Algo", title_style))
    elements.append(Paragraph("Payment Receipt & Invoice", styles['Normal']))
    elements.append(Spacer(1, 0.3 * inch))

    # Invoice details
    invoice_table_data = [
        ['Invoice Number:', invoice_data.get('invoice_number', 'N/A')],
        ['Invoice Date:', invoice_data.get('invoice_date', datetime.now().strftime('%d %B %Y'))],
    ]
    invoice_table = Table(invoice_table_data, colWidths=[2 * inch, 3 * inch])
    invoice_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.grey),
    ]))
    elements.append(invoice_table)
    elements.append(Spacer(1, 0.3 * inch))

    # Customer details
    elements.append(Paragraph("BILL TO", header_style))
    customer_table_data = [
        ['Name:', invoice_data.get('user_name', 'N/A')],
        ['Email:', invoice_data.get('user_email', 'N/A')],
        ['Mobile:', invoice_data.get('user_mobile', 'N/A')],
    ]
    customer_table = Table(customer_table_data, colWidths=[2 * inch, 4 * inch])
    customer_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]))
    elements.append(customer_table)
    elements.append(Spacer(1, 0.3 * inch))

    # Plan details
    elements.append(Paragraph("SUBSCRIPTION DETAILS", header_style))
    plan_table_data = [
        ['Plan Name', 'Billing Cycle', 'Amount'],
        [invoice_data.get('plan_name', 'N/A'), invoice_data.get('billing_cycle', 'N/A'),
         f"₹{invoice_data.get('amount', 0):,.2f}"],
    ]
    plan_table = Table(plan_table_data, colWidths=[2.5 * inch, 2 * inch, 1.5 * inch])
    plan_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
    ]))
    elements.append(plan_table)
    elements.append(Spacer(1, 0.2 * inch))

    # Period details
    period_table_data = [
        ['Subscription Period:',
         f"{invoice_data.get('start_date', 'N/A')} to {invoice_data.get('expiry_date', 'N/A')}"],
    ]
    period_table = Table(period_table_data, colWidths=[2 * inch, 4 * inch])
    period_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]))
    elements.append(period_table)
    elements.append(Spacer(1, 0.3 * inch))

    # Total
    total_table_data = [
        ['Total Amount Paid:', f"₹{invoice_data.get('amount', 0):,.2f}"],
    ]
    total_table = Table(total_table_data, colWidths=[4 * inch, 2 * inch])
    total_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f0f0f0')),
        ('BOX', (0, 0), (-1, -1), 2, colors.HexColor('#667eea')),
    ]))
    elements.append(total_table)
    elements.append(Spacer(1, 0.5 * inch))

    # Footer
    footer_text = """
    <para alignment="center">
    Thank you for choosing SmartETF Algo!<br/>
    For any queries, contact us at smartetfalgo@gmail.com or call +91-7597583636<br/>
    <font size="8">This is a computer-generated invoice and does not require a signature.</font>
    </para>
    """
    elements.append(Paragraph(footer_text, styles['Normal']))

    doc.build(elements)
    buffer.seek(0)
    return buffer


def send_purchase_confirmation_admin(purchase_data):
    """Send beautiful purchase confirmation email to admin

    purchase_data should contain:
    - user_name, user_email, user_mobile, user_full_name
    - plan_name, billing_cycle, amount, start_date, expiry_date
    - referrer_name (optional), commission_amount (optional)
    - payment_id, payment_method
    """
    admin_email = os.getenv('ADMIN_EMAIL', 'smartetfalgo@gmail.com')

    subject = f"💰 New Purchase: {purchase_data['user_name']} - ₹{purchase_data['amount']:,.2f}"

    referrer_info = ""
    if purchase_data.get('referrer_name'):
        referrer_info = f"""
        <div class="info-row">
            <div class="info-label">🤝 Referrer:</div>
            <div class="info-value">{purchase_data['referrer_name']}</div>
        </div>
        <div class="info-row">
            <div class="info-label">💵 Commission:</div>
            <div class="info-value">₹{purchase_data.get('commission_amount', 0):,.2f}</div>
        </div>
        """

    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 700px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
            .purchase-box {{ background: white; padding: 25px; border-radius: 8px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .info-row {{ display: flex; margin: 12px 0; padding: 10px 0; border-bottom: 1px solid #eee; }}
            .info-label {{ font-weight: bold; color: #555; width: 160px; }}
            .info-value {{ color: #333; flex: 1; }}
            .highlight {{ background: #fff3cd; padding: 15px; border-left: 4px solid #ffc107; margin: 15px 0; border-radius: 4px; }}
            .amount-box {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; margin: 20px 0; }}
            .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>💰 New Subscription Purchase</h1>
                <p style="font-size: 18px; margin: 10px 0;">SmartETF Platform</p>
            </div>

            <div class="content">
                <div class="amount-box">
                    <h2 style="margin: 0;">₹{purchase_data['amount']:,.2f}</h2>
                    <p style="margin: 5px 0; opacity: 0.9;">Total Amount Received</p>
                </div>

                <div class="purchase-box">
                    <h3 style="margin-top: 0; color: #28a745;">👤 Customer Details</h3>
                    <div class="info-row">
                        <div class="info-label">📝 Full Name:</div>
                        <div class="info-value">{purchase_data['user_full_name']}</div>
                    </div>
                    <div class="info-row">
                        <div class="info-label">👤 Username:</div>
                        <div class="info-value">{purchase_data['user_name']}</div>
                    </div>
                    <div class="info-row">
                        <div class="info-label">📧 Email:</div>
                        <div class="info-value">{purchase_data['user_email']}</div>
                    </div>
                    <div class="info-row">
                        <div class="info-label">📱 Mobile:</div>
                        <div class="info-value">{purchase_data['user_mobile']}</div>
                    </div>
                </div>

                <div class="purchase-box">
                    <h3 style="margin-top: 0; color: #667eea;">📦 Plan Details</h3>
                    <div class="info-row">
                        <div class="info-label">📋 Plan Name:</div>
                        <div class="info-value"><strong>{purchase_data['plan_name']}</strong></div>
                    </div>
                    <div class="info-row">
                        <div class="info-label">🔄 Billing Cycle:</div>
                        <div class="info-value">{purchase_data['billing_cycle'].title()}</div>
                    </div>
                    <div class="info-row">
                        <div class="info-label">💰 Amount:</div>
                        <div class="info-value"><strong>₹{purchase_data['amount']:,.2f}</strong></div>
                    </div>
                    <div class="info-row">
                        <div class="info-label">📅 Start Date:</div>
                        <div class="info-value">{purchase_data['start_date']}</div>
                    </div>
                    <div class="info-row">
                        <div class="info-label">📅 Expiry Date:</div>
                        <div class="info-value">{purchase_data['expiry_date']}</div>
                    </div>
                </div>

                <div class="purchase-box">
                    <h3 style="margin-top: 0; color: #17a2b8;">💳 Payment Details</h3>
                    <div class="info-row">
                        <div class="info-label">🆔 Payment ID:</div>
                        <div class="info-value">{purchase_data['payment_id']}</div>
                    </div>
                    <div class="info-row">
                        <div class="info-label">💳 Payment Method:</div>
                        <div class="info-value">{purchase_data['payment_method']}</div>
                    </div>
                    {referrer_info}
                </div>

                <div class="highlight">
                    <strong>⏰ Purchase Time:</strong> {datetime.now().strftime('%d %B %Y at %I:%M %p IST')}
                </div>
            </div>

            <div class="footer">
                <p>© 2025 SmartETF Algo. All rights reserved.</p>
                <p>This is an automated notification from the SmartETF Platform</p>
            </div>
        </div>
    </body>
    </html>
    """

    try:
        send_email(admin_email, subject, html_body, is_html=True)
        print(f"✅ Purchase confirmation sent to admin")
    except Exception as e:
        print(f"❌ Error sending admin purchase email: {e}")


def send_purchase_confirmation_client(purchase_data):
    """Send beautiful purchase confirmation with PDF invoice to client

    purchase_data should contain all fields from send_purchase_confirmation_admin
    """
    from email.mime.application import MIMEApplication

    user_email = purchase_data['user_email']
    user_name = purchase_data['user_full_name']

    subject = f"🎉 Welcome to the Future of ETF Automation - Invoice #{purchase_data.get('invoice_number', 'N/A')}"

    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; }}
            .container {{ max-width: 650px; margin: 0 auto; background: #ffffff; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 40px 30px; text-align: center; }}
            .content {{ padding: 40px 30px; background: #f9f9f9; }}
            .welcome-box {{ background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white; padding: 30px; border-radius: 12px; text-align: center; margin: 20px 0; }}
            .plan-box {{ background: white; padding: 25px; border-radius: 10px; margin: 20px 0; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            .plan-header {{ color: #667eea; font-size: 24px; margin-bottom: 15px; }}
            .info-row {{ display: flex; padding: 12px 0; border-bottom: 1px solid #eee; }}
            .info-label {{ font-weight: 600; color: #666; width: 140px; }}
            .info-value {{ color: #333; flex: 1; }}
            .benefit-box {{ background: #e8f5e9; padding: 20px; border-left: 4px solid #4caf50; margin: 20px 0; border-radius: 4px; }}
            .cta-button {{ display: inline-block; padding: 15px 35px; background: #667eea; color: white; text-decoration: none; border-radius: 8px; font-weight: bold; margin: 20px 0; }}
            .stats-box {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; }}
            .footer {{ text-align: center; padding: 30px; background: #2c3e50; color: white; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0; font-size: 32px;">🚀 Welcome Aboard!</h1>
                <p style="margin: 10px 0 0 0; font-size: 18px; opacity: 0.95;">Your Journey to Smarter Investing Begins Now</p>
            </div>

            <div class="content">
                <div class="welcome-box">
                    <h2 style="margin: 0; font-size: 28px;">Congratulations, {user_name}!</h2>
                    <p style="margin: 15px 0 0 0; font-size: 16px; opacity: 0.95;">You've just joined the elite circle of investors who leverage cutting-edge algorithms to maximize returns!</p>
                </div>

                <h2 style="color: #667eea; font-size: 24px;">📋 Your Subscription Details</h2>

                <div class="plan-box">
                    <div class="plan-header">📦 {purchase_data['plan_name']}</div>
                    <div class="info-row">
                        <div class="info-label">🔄 Billing Cycle:</div>
                        <div class="info-value"><strong>{purchase_data['billing_cycle'].title()}</strong></div>
                    </div>
                    <div class="info-row">
                        <div class="info-label">💰 Amount Paid:</div>
                        <div class="info-value"><strong style="color: #28a745; font-size: 18px;">₹{purchase_data['amount']:,.2f}</strong></div>
                    </div>
                    <div class="info-row">
                        <div class="info-label">📅 Start Date:</div>
                        <div class="info-value">{purchase_data['start_date']}</div>
                    </div>
                    <div class="info-row">
                        <div class="info-label">📅 Valid Until:</div>
                        <div class="info-value"><strong>{purchase_data['expiry_date']}</strong></div>
                    </div>
                    <div class="info-row">
                        <div class="info-label">🆔 Invoice Number:</div>
                        <div class="info-value">{purchase_data.get('invoice_number', 'N/A')}</div>
                    </div>
                </div>

                <div class="benefit-box">
                    <h3 style="margin-top: 0; color: #2e7d32;">🎯 Why SmartETF Beats Traditional Investing</h3>
                    <div class="stats-box">
                        <p><strong>📊 Performance Comparison (Last Year):</strong></p>
                        <ul style="line-height: 1.8;">
                            <li><strong>Traditional Mutual Funds:</strong> 12-15% average returns</li>
                            <li><strong>SmartETF Algorithm:</strong> <span style="color: #4caf50; font-size: 20px; font-weight: bold;">20-23%</span> potential returns*</li>
                            <li><strong>Your Advantage:</strong> <span style="color: #ff5722; font-weight: bold;">Up to 8% higher returns!</span></li>
                        </ul>
                        <p style="color: #666; font-size: 13px; margin: 10px 0 0 0;">*Past performance is not indicative of future results. Investments are subject to market risks.</p>
                    </div>
                </div>

                <h3 style="color: #667eea;">🚀 What Happens Next?</h3>
                <ul style="line-height: 1.8;">
                    <li>✅ Your account is <strong>ACTIVE</strong> and ready for automated investing</li>
                    <li>📊 Our advanced algorithm analyzes market opportunities 24/7</li>
                    <li>💼 Automated ETF investments executed at optimal times</li>
                    <li>📈 Real-time portfolio tracking on your dashboard</li>
                    <li>📧 Regular performance reports delivered to your inbox</li>
                </ul>

                <div style="text-align: center; margin: 30px 0;">
                    <a href="https://smartetfalgo.com/dashboard" class="cta-button">🎯 Access Your Dashboard Now</a>
                </div>

                <div style="background: #fff3cd; padding: 20px; border-radius: 8px; border-left: 4px solid #ffc107;">
                    <h4 style="margin-top: 0; color: #856404;">📎 Invoice Attached</h4>
                    <p style="margin-bottom: 0;">Your official payment receipt is attached to this email as a PDF. Please save it for your records.</p>
                </div>

                <div style="margin-top: 30px; padding: 25px; background: white; border-radius: 8px; border: 2px solid #667eea;">
                    <h4 style="margin-top: 0; color: #667eea;">💡 Pro Tips for Maximum Returns</h4>
                    <ul style="line-height: 1.8; margin-bottom: 0;">
                        <li>Monitor your dashboard regularly for insights</li>
                        <li>Enable email notifications for all order updates</li>
                        <li>Ensure sufficient balance in your broker account</li>
                        <li>Review monthly performance reports</li>
                    </ul>
                </div>

                <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">

                <h3 style="color: #667eea;">📞 We're Here to Help!</h3>
                <div style="background: white; padding: 20px; border-radius: 8px;">
                    <p><strong>Email:</strong> <a href="mailto:smartetfalgo@gmail.com" style="color: #667eea;">smartetfalgo@gmail.com</a></p>
                    <p><strong>Customer Care:</strong> <a href="tel:+917597583636" style="color: #667eea;">+91-7597583636</a></p>
                    <p><strong>Support Hours:</strong> 10:00 AM - 5:00 PM IST (Mon-Fri)</p>
                    <p style="margin-bottom: 0;">Have questions? Our expert team is ready to assist you!</p>
                </div>
            </div>

            <div class="footer">
                <h3 style="margin-top: 0;">Thank You for Choosing SmartETF Algo!</h3>
                <p>Your trust empowers us to deliver excellence</p>
                <p style="margin: 20px 0 0 0; font-size: 12px; opacity: 0.8;">© 2025 SmartETF Algo. All rights reserved.</p>
                <p style="margin: 5px 0 0 0; font-size: 12px;"><a href="https://smartetfalgo.com" style="color: #64b5f6;">smartetfalgo.com</a></p>
            </div>
        </div>
    </body>
    </html>
    """

    try:
        # Generate PDF invoice
        invoice_pdf = generate_purchase_invoice_pdf(purchase_data)

        # Get email config — honours SSL vs STARTTLS and DB settings
        config = get_email_config()
        sender_email = config['sender_email']
        smtp_server = config['smtp_server']
        smtp_port = config['smtp_port']
        smtp_user = config['smtp_user']
        smtp_pass = config['smtp_pass']

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = user_email

        # Attach HTML body
        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)

        # Attach PDF invoice
        pdf_attachment = MIMEApplication(invoice_pdf.read(), _subtype='pdf')
        pdf_attachment.add_header('Content-Disposition', 'attachment',
                                  filename=f'SmartETF_Invoice_{purchase_data.get("invoice_number", "N/A")}.pdf')
        msg.attach(pdf_attachment)

        # Send using SSL (port 465) or STARTTLS (port 587)
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(sender_email, user_email, msg.as_string())
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(sender_email, user_email, msg.as_string())

        print(f"✅ Purchase confirmation with PDF sent to {user_email}")
    except Exception as e:
        print(f"❌ Error sending client purchase email: {e}")
        import traceback
        traceback.print_exc()


def send_renewal_reminder_email(user_data, days_remaining):
    """Send plan renewal reminder email to client

    user_data should contain:
    - full_name, email, plan_name, expiry_date, billing_cycle, amount
    """
    user_email = user_data['email']
    user_name = user_data['full_name']
    plan_name = user_data['plan_name']
    expiry_date = user_data['expiry_date']

    subject = f"⏰ Your {plan_name} Plan Expires in {days_remaining} Days - Renew Now!"

    urgency_color = "#ffc107" if days_remaining > 7 else "#ff5722"
    urgency_message = "Don't miss out!" if days_remaining > 7 else "Urgent: Renew immediately!"

    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 650px; margin: 0 auto; background: #ffffff; }}
            .header {{ background: linear-gradient(135deg, {urgency_color} 0%, #ff6b6b 100%); color: white; padding: 35px 30px; text-align: center; }}
            .content {{ padding: 35px 30px; background: #f9f9f9; }}
            .alert-box {{ background: #fff3cd; border-left: 5px solid {urgency_color}; padding: 20px; margin: 20px 0; border-radius: 4px; }}
            .plan-box {{ background: white; padding: 25px; border-radius: 10px; margin: 20px 0; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            .cta-button {{ display: inline-block; padding: 15px 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 8px; font-weight: bold; margin: 20px 0; font-size: 16px; }}
            .benefits-box {{ background: #e8f5e9; padding: 20px; border-radius: 8px; margin: 20px 0; }}
            .footer {{ text-align: center; padding: 25px; background: #2c3e50; color: white; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0; font-size: 32px;">⏰ Renewal Reminder</h1>
                <p style="margin: 10px 0 0 0; font-size: 18px;">Your Subscription is Expiring Soon!</p>
            </div>

            <div class="content">
                <h2 style="color: #333;">Hi {user_name},</h2>

                <div class="alert-box">
                    <h3 style="margin-top: 0; color: #856404;">🚨 {urgency_message}</h3>
                    <p style="font-size: 18px; margin: 10px 0;"><strong>Your {plan_name} subscription expires in just {days_remaining} days!</strong></p>
                    <p style="margin-bottom: 0;"><strong>Expiry Date:</strong> {expiry_date}</p>
                </div>

                <div class="plan-box">
                    <h3 style="color: #667eea; margin-top: 0;">📦 Current Plan Details</h3>
                    <ul style="line-height: 1.8;">
                        <li><strong>Plan:</strong> {plan_name}</li>
                        <li><strong>Billing Cycle:</strong> {user_data.get('billing_cycle', 'N/A').title()}</li>
                        <li><strong>Expiring On:</strong> {expiry_date}</li>
                    </ul>
                </div>

                <h3 style="color: #667eea;">⚠️ What Happens if You Don't Renew?</h3>
                <ul style="line-height: 1.8; color: #555;">
                    <li>❌ Your automated ETF investments will <strong>STOP</strong></li>
                    <li>❌ You'll lose access to our advanced algorithms</li>
                    <li>❌ No more market opportunity alerts</li>
                    <li>❌ Dashboard and portfolio tracking will be disabled</li>
                </ul>

                <div class="benefits-box">
                    <h3 style="margin-top: 0; color: #2e7d32;">✅ Renew Now & Keep Enjoying:</h3>
                    <ul style="line-height: 1.8; margin-bottom: 0;">
                        <li>🚀 <strong>20-23% potential returns</strong> (vs 12-15% traditional MFs)</li>
                        <li>🤖 Fully automated investment execution</li>
                        <li>📊 Real-time portfolio tracking & analytics</li>
                        <li>💰 Smart market entry timing for maximum gains</li>
                        <li>📧 Regular performance reports & insights</li>
                    </ul>
                </div>

                <div style="text-align: center; margin: 30px 0;">
                    <a href="https://smartetfalgo.com/plans" class="cta-button">💳 Renew Your Plan Now</a>
                </div>

                <div style="background: #e3f2fd; padding: 20px; border-radius: 8px; border-left: 4px solid #2196f3;">
                    <h4 style="margin-top: 0; color: #1565c0;">💡 Special Offer</h4>
                    <p style="margin-bottom: 0;">Renew before expiry and continue your journey to financial success without any interruption. Don't let market opportunities slip away!</p>
                </div>

                <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">

                <h3 style="color: #667eea;">📞 Need Help with Renewal?</h3>
                <div style="background: white; padding: 20px; border-radius: 8px;">
                    <p><strong>Email:</strong> <a href="mailto:smartetfalgo@gmail.com" style="color: #667eea;">smartetfalgo@gmail.com</a></p>
                    <p><strong>Customer Care:</strong> <a href="tel:+917597583636" style="color: #667eea;">+91-7597583636</a></p>
                    <p style="margin-bottom: 0;"><strong>Support Hours:</strong> 10:00 AM - 5:00 PM IST (Mon-Fri)</p>
                </div>
            </div>

            <div class="footer">
                <p style="margin: 0; font-size: 14px;">Thank you for being a valued SmartETF member!</p>
                <p style="margin: 15px 0 0 0; font-size: 12px; opacity: 0.8;">© 2025 SmartETF Algo. All rights reserved.</p>
                <p style="margin: 5px 0 0 0; font-size: 12px;"><a href="https://smartetfalgo.com" style="color: #64b5f6;">smartetfalgo.com</a></p>
            </div>
        </div>
    </body>
    </html>
    """

    try:
        send_email(user_email, subject, html_body, is_html=True)
        print(f"✅ Renewal reminder sent to {user_email} ({days_remaining} days remaining)")
    except Exception as e:
        print(f"❌ Error sending renewal reminder: {e}")


def send_sip_update_notification_email(user_data, new_sip_amount, broker_count):
    """Send email notification when user updates their SIP amount

    user_data should contain:
    - full_name, email
    """
    user_email = user_data['email']
    user_name = user_data['full_name']

    subject = f"✅ SIP Target Updated - ₹{new_sip_amount:,.2f}"

    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 650px; margin: 0 auto; background: #ffffff; }}
            .header {{ background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; padding: 35px 30px; text-align: center; }}
            .content {{ padding: 35px 30px; background: #f9f9f9; }}
            .success-box {{ background: #d4edda; border-left: 5px solid #28a745; padding: 20px; margin: 20px 0; border-radius: 4px; }}
            .info-box {{ background: white; padding: 25px; border-radius: 10px; margin: 20px 0; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            .cta-button {{ display: inline-block; padding: 15px 35px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 8px; font-weight: bold; margin: 20px 0; }}
            .highlight-box {{ background: #fff3cd; padding: 20px; border-radius: 8px; border-left: 4px solid #ffc107; margin: 20px 0; }}
            .footer {{ text-align: center; padding: 25px; background: #2c3e50; color: white; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0; font-size: 32px;">✅ SIP Target Updated!</h1>
                <p style="margin: 10px 0 0 0; font-size: 18px;">Your Monthly Investment Plan is Now Active</p>
            </div>

            <div class="content">
                <h2 style="color: #333;">Hi {user_name},</h2>

                <div class="success-box">
                    <h3 style="margin-top: 0; color: #155724;">🎉 Update Successful!</h3>
                    <p style="font-size: 16px; margin-bottom: 0;">Your monthly SIP target has been updated successfully and algo investment is now active.</p>
                </div>

                <div class="info-box">
                    <h3 style="color: #667eea; margin-top: 0;">📊 Your New Investment Details</h3>
                    <ul style="line-height: 1.8; font-size: 16px;">
                        <li><strong>Monthly SIP Target:</strong> <span style="color: #28a745; font-size: 20px;">₹{new_sip_amount:,.2f}</span></li>
                        <li><strong>Connected Brokers:</strong> {broker_count}</li>
                        <li><strong>Effective From:</strong> Next trading session (3:10 PM IST)</li>
                        <li><strong>Status:</strong> <span style="color: #28a745;">✅ Active</span></li>
                    </ul>
                </div>

                <h3 style="color: #667eea;">🚀 What Happens Next?</h3>
                <ul style="line-height: 1.8;">
                    <li>📈 Your algo investment will automatically adjust to meet your new target</li>
                    <li>💼 Smart ETF investments will be executed across your {broker_count} connected broker{'s' if broker_count > 1 else ''}</li>
                    <li>📊 You can track your investment progress in real-time on your dashboard</li>
                    <li>📧 You'll receive notifications for all investment activities</li>
                </ul>

                <div class="highlight-box">
                    <h4 style="margin-top: 0; color: #856404;">💡 Important Reminders</h4>
                    <ul style="line-height: 1.8; margin-bottom: 0;">
                        <li>Ensure your broker account has sufficient balance (at least ₹{new_sip_amount:,.2f})</li>
                        <li>Check your dashboard regularly to monitor investment progress</li>
                        <li>Our algorithm will distribute investments optimally across market opportunities</li>
                    </ul>
                </div>

                <div style="text-align: center; margin: 30px 0;">
                    <a href="https://smartetfalgo.com/dashboard" class="cta-button">📊 View Dashboard</a>
                </div>

                <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">

                <h3 style="color: #667eea;">📞 Need Assistance?</h3>
                <div style="background: white; padding: 20px; border-radius: 8px;">
                    <p><strong>Email:</strong> <a href="mailto:smartetfalgo@gmail.com" style="color: #667eea;">smartetfalgo@gmail.com</a></p>
                    <p><strong>Customer Care:</strong> <a href="tel:+917597583636" style="color: #667eea;">+91-7597583636</a></p>
                    <p style="margin-bottom: 0;"><strong>Support Hours:</strong> 10:00 AM - 5:00 PM IST (Mon-Fri)</p>
                </div>
            </div>

            <div class="footer">
                <p style="margin: 0; font-size: 14px;">Happy Investing with SmartETF!</p>
                <p style="margin: 15px 0 0 0; font-size: 12px; opacity: 0.8;">© 2025 SmartETF Algo. All rights reserved.</p>
                <p style="margin: 5px 0 0 0; font-size: 12px;"><a href="https://smartetfalgo.com" style="color: #64b5f6;">smartetfalgo.com</a></p>
            </div>
        </div>
    </body>
    </html>
    """

    try:
        send_email(user_email, subject, html_body, is_html=True)
        print(f"✅ SIP update notification sent to {user_email}")
    except Exception as e:
        print(f"❌ Error sending SIP update notification: {e}")
