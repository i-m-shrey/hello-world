#!/usr/bin/env python3
"""
Test script to verify email configuration for SmartETF platform
Run this script to test if email notifications are working properly
"""

import os
from dotenv import load_dotenv
from email_notifications import send_new_registration_notification

# Load environment variables
load_dotenv()

def test_email_configuration():
    """Test email configuration by sending a sample registration notification"""
    
    print("🧪 Testing SmartETF Email Configuration...")
    print("=" * 50)
    
    # Check if email environment variables are set
    admin_email = os.getenv('ADMIN_EMAIL')
    smtp_server = os.getenv('SMTP_SERVER')
    smtp_user = os.getenv('SMTP_USER')
    smtp_password = os.getenv('SMTP_PASSWORD')
    
    print(f"📧 Admin Email: {admin_email}")
    print(f"🌐 SMTP Server: {smtp_server}")
    print(f"👤 SMTP User: {smtp_user}")
    print(f"🔐 SMTP Password: {'***' if smtp_password else 'NOT SET'}")
    print()
    
    if not all([admin_email, smtp_server, smtp_user, smtp_password]):
        print("❌ Email configuration incomplete!")
        print("Please update the .env file with proper email settings:")
        print("   ADMIN_EMAIL='your-email@gmail.com'")
        print("   SMTP_SERVER='smtp.gmail.com'")
        print("   SMTP_USER='your-email@gmail.com'")
        print("   SMTP_PASSWORD='your-app-password'")
        print()
        print("📝 Note: Use Gmail App Password, not your regular password")
        print("   Visit: https://support.google.com/accounts/answer/185833")
        return False
    
    # Sample user data for testing
    test_user_data = {
        'full_name': 'John Doe (TEST USER)',
        'username': 'johndoe_test',
        'email': 'johndoe.test@example.com',
        'mobile': '9876543210',
        'address': '123 Test Street, Test Colony',
        'city': 'Test City',
        'state': 'Test State',
        'pin': '123456',
        'customer_id': 'CUST_TEST_001'
    }
    
    print("🚀 Sending test registration notification...")
    try:
        send_new_registration_notification(test_user_data)
        print("✅ Test email sent successfully!")
        print(f"📬 Check your inbox at: {admin_email}")
        return True
    except Exception as e:
        print(f"❌ Failed to send test email: {e}")
        print()
        print("🔧 Troubleshooting tips:")
        print("1. Verify your email and app password are correct")
        print("2. Make sure 2-factor authentication is enabled for Gmail")
        print("3. Use App Password instead of regular password")
        print("4. Check if 'Less secure app access' is enabled (if not using App Password)")
        return False

if __name__ == "__main__":
    print("SmartETF Email Test Utility")
    print("=" * 30)
    test_email_configuration()