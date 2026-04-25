import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

def send_email(to_address, subject, body, is_html=False):
    """Send email using SMTP configuration from environment variables"""
    # Email configuration from environment variables
    sender_email = os.getenv('ADMIN_EMAIL', 'alerts@smartetf.com')
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER', sender_email)
    smtp_pass = os.getenv('SMTP_PASSWORD', 'your_app_password')

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
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(sender_email, to_address, msg.as_string())
            print(f"✅ Email sent to {to_address}")
    except Exception as e:
        print(f"❌ Failed to send email to {to_address}: {e}")

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


def send_execution_email(success: bool, metrics: dict, files: dict, mode: str, started_at_utc, ended_at_utc, pid: int | None = None, log_path: str | None = None):
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


def send_copy_trading_enabled_email(user_data):
    """Send email notification when Algo Investment is enabled for a user"""
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
            <div class="info"><strong>Monthly SIP Target:</strong> ₹{user_data.get('monthly_sip_target', 0):,.2f}</div>
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