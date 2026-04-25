"""Email Settings Model - Add this to your models.py"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class EmailSettings(db.Model):
    """Email configuration settings stored in database for admin panel"""
    __tablename__ = 'email_settings'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    
    # Provider selection: 'zoho' or 'gmail'
    provider = db.Column(db.String(20), default='zoho')
    
    # Zoho Settings
    zoho_smtp_server = db.Column(db.String(100), default='smtppro.zoho.in')
    zoho_smtp_port = db.Column(db.Integer, default=465)
    zoho_email = db.Column(db.String(120), default='support@smartetfalgo.com')
    zoho_password = db.Column(db.Text)  # Encrypted app password
    
    # Gmail Settings
    gmail_smtp_server = db.Column(db.String(100), default='smtp.gmail.com')
    gmail_smtp_port = db.Column(db.Integer, default=587)
    gmail_email = db.Column(db.String(120), default='smartetfalgo@gmail.com')
    gmail_password = db.Column(db.Text)  # Encrypted app password
    
    # Common settings
    admin_email = db.Column(db.String(120))
    sender_name = db.Column(db.String(100), default='SmartETF Algo')
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.String(50))

    @staticmethod
    def get_settings():
        """Get or create default email settings"""
        settings = EmailSettings.query.first()
        if not settings:
            settings = EmailSettings()
            db.session.add(settings)
            db.session.commit()
        return settings

    def get_smtp_config(self):
        """Get SMTP configuration based on selected provider"""
        if self.provider == 'zoho':
            return {
                'server': self.zoho_smtp_server,
                'port': self.zoho_smtp_port,
                'email': self.zoho_email,
                'password': self.zoho_password,
                'use_ssl': self.zoho_smtp_port == 465
            }
        else:  # gmail
            return {
                'server': self.gmail_smtp_server,
                'port': self.gmail_smtp_port,
                'email': self.gmail_email,
                'password': self.gmail_password,
                'use_ssl': self.gmail_smtp_port == 465
            }
