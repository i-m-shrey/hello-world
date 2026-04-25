from app import app
from client_fetcher import get_active_clients
from broker_dispatcher import get_executor_for_broker
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()


def send_email(to_address, subject, body, is_html=False):
    # Email configuration from environment variables
    sender_email = os.getenv('ADMIN_EMAIL', 'alerts@smartetf.com')
    admin_email = os.getenv('ADMIN_EMAIL', 'admin@smartetf.com')
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


def validate_client_sessions():
    print("🔍 Starting session validation for all subscribed clients...")
    with app.app_context():
        clients = get_active_clients()
        broker_clients = {}

        for client in clients:
            broker_name = client['broker_name'].upper()
            broker_clients.setdefault(broker_name, []).append(client)

        for broker_name, client_list in broker_clients.items():
            try:
                print(f"⚙️ Validating {broker_name} clients...")
                executor = get_executor_for_broker(broker_name)

                # each executor must support a test_sessions(client_list) function
                if hasattr(executor, "test_sessions"):
                    executor.test_sessions(client_list)
                else:
                    print(f"⚠️ Executor for {broker_name} does not support session test.")

            except Exception as e:
                print(f"❌ Error validating clients for {broker_name}: {e}")


if __name__ == "__main__":
    validate_client_sessions()
